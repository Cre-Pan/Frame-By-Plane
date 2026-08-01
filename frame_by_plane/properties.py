"""Scene, Object, Collection and add-on preference properties."""

import bpy
from types import SimpleNamespace
from bpy.props import (
    StringProperty, IntProperty, BoolProperty, FloatProperty, FloatVectorProperty,
    CollectionProperty, PointerProperty, EnumProperty
)
from bpy.types import PropertyGroup, AddonPreferences
from .constants import (
    COLLECTION_COLOR_ENUM_ITEMS, FBP_LAYER_BLEND_MODE_ITEMS,
    FBP_BLENDER_VERSION_SERIES_STRING, FBP_LTS_TARGET_VERSION,
    FBP_RELEASE_CHANNEL_LABEL, FBP_SUPPORTED_PLATFORM_LABEL,
    FBP_VERSION_STRING, fbp_icon,
)
from .matrix_presets import ASCII_ATLAS_COLUMNS, ASCII_TEXT_GLYPH_LIMIT, ascii_enum_items
from .ui_icons import custom_icon_generation, layer_custom_icon_value, ui_icon, ui_icon_kwargs
from .ui_style import adaptive_row, configure_layout, hint_row, section_gap, section_header
from .shortcut_runtime import (
    alt_shortcut_label,
    primary_modifier_name,
    primary_shortcut_label,
    refresh_all_shortcuts,
)

from .storage_keys import fbp_effect_storage_key
from .registration import register_classes, unregister_classes, unregister_type_properties
from .interface_preferences import (
    clear_interface_preferences_cache,
    fbp_get_addon_preferences,
)
from .preference_application import (
    fbp_apply_preferences_to_scene,
    fbp_mark_scenes_preferences_initialized,
)
from .runtime import (
    FBP_DATA_ERRORS,
    fbp_undo_guard_active,
    fbp_is_silent_property_update,
    fbp_set_rna_property_silent,
    fbp_warn,
    fbp_obj_runtime_token,
    fbp_obj_matches_runtime_token,
    fbp_request_redraw,
)


# Exact RNA ownership registry for this module.  Keep it across in-place Python
# reloads so properties removed from a newer source generation can still be
# retired during the next unregister instead of leaking on bpy.types.
_FBP_REGISTERED_TYPE_PROPERTIES = globals().get(
    "_FBP_REGISTERED_TYPE_PROPERTIES", {}
)
if not isinstance(_FBP_REGISTERED_TYPE_PROPERTIES, dict):
    _FBP_REGISTERED_TYPE_PROPERTIES = {}


def _fbp_rna_property_name(value):
    """Return a safe exact RNA identifier for reload-time ownership data."""
    try:
        return "" if value is None else str(value).strip()
    except FBP_DATA_ERRORS:
        return ""


def _fbp_normalize_rna_registry(value):
    if isinstance(value, dict):
        values = tuple(value)
    elif isinstance(value, (tuple, list, set, frozenset)):
        values = tuple(value)
    else:
        return {}
    normalized = {}
    for raw_name in values:
        name = _fbp_rna_property_name(raw_name)
        if name:
            normalized[name] = None
    return normalized


for _owner_name in ("Scene", "Collection", "Object"):
    _FBP_REGISTERED_TYPE_PROPERTIES[_owner_name] = _fbp_normalize_rna_registry(
        _FBP_REGISTERED_TYPE_PROPERTIES.get(_owner_name, {})
    )


class _FBPTrackedRNAOwner:
    """Delegate RNA assignments while recording exact module ownership.

    Direct ``bpy.types`` assignments are convenient but offer no ownership
    metadata.  The previous teardown scanned every ``fbp_*`` attribute and
    could therefore delete unrelated properties.  These proxies preserve the
    familiar assignment syntax while making partial registration transactional.
    """

    __slots__ = ("_owner", "_owner_name")

    def __init__(self, owner, owner_name):
        object.__setattr__(self, "_owner", owner)
        object.__setattr__(
            self, "_owner_name", _fbp_rna_property_name(owner_name)
        )

    def assign(self, name, definition):
        property_name = _fbp_rna_property_name(name)
        if not property_name:
            raise AttributeError("RNA property name cannot be empty")
        registry = _FBP_REGISTERED_TYPE_PROPERTIES.setdefault(
            self._owner_name, {}
        )
        # Record before delegating: if Blender rejects a stale or partially
        # registered descriptor, rollback still knows the exact name to remove.
        registry[property_name] = None
        setattr(self._owner, property_name, definition)
        return definition

    def __setattr__(self, name, definition):
        self.assign(name, definition)


_FBP_SCENE_RNA = _FBPTrackedRNAOwner(bpy.types.Scene, "Scene")
_FBP_COLLECTION_RNA = _FBPTrackedRNAOwner(bpy.types.Collection, "Collection")
_FBP_OBJECT_RNA = _FBPTrackedRNAOwner(bpy.types.Object, "Object")


CAMERA_RATIO_ITEMS = [
    ('CUSTOM',       "Custom",         "Use the custom render resolution", fbp_icon("PREFERENCES"), 0),
    ('4_3',          "4:3",            "1920x1440 classic animation and TV format", fbp_icon("IMAGE_DATA"), 1),
    ('3_4',          "3:4 Vertical",   "1440x1920 vertical classic format", fbp_icon("FILE_IMAGE"), 2),
    ('HD_16_9',      "HD 16:9",        "1920x1080 horizontal HD format", fbp_icon("IMAGE_DATA"), 3),
    ('UHD_4K',       "4K UHD",         "3840x2160 horizontal 4K format", fbp_icon("RENDER_RESULT"), 4),
    ('STORY_9_16',   "Story 9:16",     "1080x1920 vertical social/story format", fbp_icon("FILE_IMAGE"), 5),
    ('1_1',          "Square 1:1",     "2000x2000 square format", fbp_icon("MESH_PLANE"), 6),
    ('5_4',          "5:4",            "2000x1600 classic monitor/print ratio", fbp_icon("IMAGE_DATA"), 7),
    ('16_10',        "16:10",          "1920x1200 widescreen workspace ratio", fbp_icon("IMAGE_DATA"), 8),
    ('PHOTO_3_2',    "Photo 3:2",      "3000x2000 photographic ratio", fbp_icon("FILE_IMAGE"), 9),
    ('PHOTO_2_3',    "Photo 2:3",      "2000x3000 vertical photographic ratio", fbp_icon("FILE_IMAGE"), 10),
    ('CINEMA_185',   "Cinema 1.85:1",  "1850x1000 cinema ratio", fbp_icon("CAMERA_DATA"), 11),
    ('CINEMA_239',   "Cinema 2.39:1",  "2390x1000 widescreen cinema ratio", fbp_icon("CAMERA_DATA"), 12),
    ('TWO_1',        "2:1",            "2000x1000 wide format", fbp_icon("CAMERA_DATA"), 13),
    ('ULTRAWIDE_21_9', "21:9",         "2520x1080 ultrawide format", fbp_icon("CAMERA_DATA"), 14),
    ('A4_LANDSCAPE', "A4 Landscape",  "2480x1754 paper ratio", fbp_icon("FILE_IMAGE"), 15),
    ('A4_PORTRAIT',  "A4 Portrait",   "1754x2480 paper ratio", fbp_icon("FILE_IMAGE"), 16),
]

CAMERA_PROJECTION_ITEMS = [
    ('PERSP', "Perspective", "Create a perspective camera and fit planes using their distance from the camera", 'VIEW_PERSPECTIVE', 0),
    ('ORTHO', "Orthographic", "Create an orthographic camera and fit planes using the camera orthographic scale", 'VIEW_ORTHO', 1),
]

PLAYBACK_ITEMS = [
    ('NONE', "One Shot", "Play once", fbp_icon("FORWARD"), 0),
    ('REPEAT', "Loop", "Repeat forever", fbp_icon("FILE_REFRESH"), 1),
    ('PINGPONG', "Ping-Pong", "Play forward and backward", fbp_icon("UV_SYNC_SELECT"), 2),
]

PLANE_START_FRAME_MODE_ITEMS = (
    ('PLAYHEAD', "Timeline Cursor", "Start new planes at the current timeline cursor, matching the existing Frame By Plane behavior", fbp_icon("PIVOT_CURSOR"), 0),
    ('TIMELINE_START', "Timeline Start", "Start new planes at the Scene start frame", fbp_icon("PREV_KEYFRAME"), 1),
)

RENDER_FILENAME_MODE_ITEMS = (
    ('NATIVE', "Native Pattern", "Use Blender's native output filename pattern exactly"),
    ('COMPOSE', "Name Builder", "Compose the filename from document, prefix, letter, number, suffix and frame tokens"),
)

RENDER_NAME_SOURCE_ITEMS = (
    ('DOCUMENT', "Document Name", "Use the current .blend filename without its extension", 'FILE_BLEND', 0),
    ('CUSTOM', "Custom Name", "Use a custom base filename", fbp_icon("FONT_DATA"), 1),
    ('NONE', "No Base Name", "Build the filename only from the optional tokens", fbp_icon("X"), 2),
)

RENDER_SEPARATOR_ITEMS = (
    ('DASH', "Spaced Dash", "Separate filename tokens with a spaced dash", 'EVENT_MINUS', 0),
    ('UNDERSCORE', "Underscore", "Separate filename tokens with underscores", 'IPO_CONSTANT', 1),
    ('HYPHEN', "Hyphen", "Separate filename tokens with hyphens", 'REMOVE', 2),
    ('SPACE', "Space", "Separate filename tokens with spaces", 'EVENT_SPACEKEY', 3),
    ('NONE', "None", "Join filename tokens without a separator", fbp_icon("X"), 4),
)

RENDER_FOLDER_BUILDER_MODE_ITEMS = (
    ('SELECT', "Select Folder", "Write directly into a folder selected in the file browser"),
    ('GENERATE', "Generate Folder", "Build a named folder inside the Frame By Plane project folder"),
)

RENDER_FOLDER_TAG_ITEMS = (
    ('NONE', "None", "Do not append a production tag"),
    ('TEST', "TEST", "Append TEST to the generated folder name"),
    ('ANIM', "ANIM", "Append ANIM to the generated folder name"),
    ('FINAL', "FINAL", "Append FINAL to the generated folder name"),
    ('PREV', "PREV", "Append PREV to the generated folder name"),
)

RENDER_TOKEN_MODE_ITEMS = (
    ('NONE', "None", "Do not add a letter or fixed number token"),
    ('LETTER', "Letter", "Add the custom starting letter"),
    ('NUMBER', "Number", "Add the custom starting number"),
    ('LETTER_NUMBER', "Letter + Number", "Add the custom starting letter followed by the number"),
)

RENDER_TOKEN_POSITION_ITEMS = (
    ('BEFORE', "Before", "Place the letter/number token before Prefix"),
    ('AFTER', "After", "Place the letter/number token after Suffix"),
)

RENDER_OUTPUT_KIND_ITEMS = (
    ('IMAGES', "Images", "Render the selected still-image format or image sequence"),
    ('VIDEO', "Video", "Render PNG frames safely in background, then create an MP4 automatically with FFmpeg"),
)

RENDER_FRAME_POSITION_ITEMS = (
    ('BEFORE_SUFFIX', "Frame Before Suffix", "Place the frame number immediately before the suffix"),
    ('AFTER_SUFFIX', "Frame After Suffix", "Place the frame number at the end of the filename"),
)

RENDER_FOLDER_MODE_ITEMS = (
    ('ROOT', "Selected Folder", "Write directly into the selected output folder", fbp_icon("FILE_FOLDER"), 0),
    ('TEST', "TEST Number", "Create a numbered TEST folder, optionally with a suffix", fbp_icon("FILE_REFRESH"), 1),
    ('FINAL', "FINAL", "Create a FINAL folder, optionally with a suffix", fbp_icon("FILE_TICK"), 2),
    ('CUSTOM', "Custom Folder", "Create a named subfolder inside the selected output folder", fbp_icon("PREFERENCES"), 3),
)


def update_render_output_path_cb(self, _context):
    """Push FBP output controls to Blender's native render filepath."""
    if fbp_is_silent_property_update(self) or fbp_undo_guard_active():
        return
    try:
        from .render_output import fbp_sync_native_render_path
        fbp_sync_native_render_path(self)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not update Blender render output path", exc)

FBP_COLOR_TAG_ITEM_LABELS = (
    ('NONE', "None / Default", "Default plane icon; no color tag", 0),
    ('COLOR_01', "Red", "Red plane tag", 1),
    ('COLOR_02', "Orange", "Orange plane tag", 2),
    ('COLOR_03', "Yellow", "Yellow plane tag", 3),
    ('COLOR_04', "Green", "Green plane tag", 4),
    ('COLOR_05', "Cyan", "Cyan plane tag", 5),
    ('COLOR_06', "Purple", "Purple plane tag", 6),
    ('COLOR_07', "Magenta", "Magenta plane tag", 7),
)
_FBP_COLOR_TAG_ITEM_CACHE = {}


def _fbp_color_tag_backend_hint(owner):
    """Best-effort backend hint for color-tag dropdown preview icons."""
    try:
        if bool(getattr(owner, 'fbp_is_drawing_plane', False)):
            return 'CUTOUT'
        if bool(getattr(owner, 'fbp_is_color_plane', False)):
            mode = str(getattr(owner, 'fbp_color_plane_mode', 'SOLID') or 'SOLID').upper()
            return {
                'GRADIENT': 'PROCEDURAL_GRADIENT',
                'HOLDOUT': 'PROCEDURAL_HOLDOUT',
            }.get(mode, 'PROCEDURAL_COLOR')
    except FBP_DATA_ERRORS:
        pass
    try:
        explicit = str(owner.get('fbp_backend_type', '') or '').upper()
        if explicit:
            return explicit
    except FBP_DATA_ERRORS:
        pass
    return 'NATIVE_IMAGE'


def fbp_color_tag_enum_items(owner, _context):
    """Color tags with custom plane-type previews where Blender supports it."""
    backend = _fbp_color_tag_backend_hint(owner)
    cache_key = (str(backend or 'NATIVE_IMAGE').upper(), custom_icon_generation())
    cached = _FBP_COLOR_TAG_ITEM_CACHE.get(cache_key)
    if cached is not None:
        return cached
    items = []
    for identifier, label, description, number in FBP_COLOR_TAG_ITEM_LABELS:
        icon_value = 0
        try:
            icon_value = int(layer_custom_icon_value(cache_key[0], identifier, inactive=False) or 0)
        except Exception:
            icon_value = 0
        if icon_value:
            items.append((identifier, label, description, icon_value, number))
        else:
            fallback_icon = fbp_icon('STRIP_COLOR_09') if identifier == 'NONE' else fbp_icon(f'STRIP_{identifier}')
            items.append((identifier, label, description, fallback_icon, number))
    if len(_FBP_COLOR_TAG_ITEM_CACHE) > 32:
        _FBP_COLOR_TAG_ITEM_CACHE.clear()
    _FBP_COLOR_TAG_ITEM_CACHE[cache_key] = tuple(items)
    return _FBP_COLOR_TAG_ITEM_CACHE[cache_key]


ALPHA_RENDER_METHOD_ITEMS = [
    ('AUTO', "Auto — Depth Safe", "Use depth-safe Dithered alpha for Frame By Plane materials while preserving image and layer transparency", fbp_icon("ANTIALIASED"), 0),
    ('DITHERED', "Dithered", "Use Dithered alpha rendering for transparent Frame By Plane materials. Recommended for Eevee depth of field, motion blur and depth passes", fbp_icon("ANTIALIASED"), 1),
    ('BLENDED', "Blended", "Use smooth blended transparency. This can produce incomplete depth information in Eevee and may limit depth of field", fbp_icon("IMAGE_ALPHA"), 2),
    ('OPAQUE', "Opaque", "Ignore image and layer alpha in the shader so transparent pixels no longer reveal layers behind the plane", fbp_icon("MATERIAL"), 3),
]

GP_FILL_SOLVER_ITEMS = [
    ('DELAUNAY', "Delaunay", "Use Blender 5.2's geometry-based fill solver with native gap detection", fbp_icon("MESH_DATA"), 0),
    ('PIXEL', "Pixel", "Use Blender's pixel-based Grease Pencil fill solver", fbp_icon("ALIASED"), 1),
]

GP_CURVE_TYPE_ITEMS = [
    ('POLY', "Polyline", "Create direct point-to-point Grease Pencil curves; recommended for masks and frame-by-frame drawing", fbp_icon("IPO_LINEAR"), 0),
    ('CATMULL_ROM', "Catmull-Rom", "Create smooth interpolating Grease Pencil curves using Blender 5.2", fbp_icon("IPO_EASE_IN_OUT"), 1),
    ('BEZIER', "Bézier", "Create editable Bézier Grease Pencil curves using Blender 5.2", fbp_icon("IPO_BEZIER"), 2),
    ('NURBS', "NURBS", "Create smooth NURBS Grease Pencil curves using Blender 5.2", fbp_icon("CURVE_NCURVE"), 3),
]

SCENE_PLAYBACK_LOOP_MODE_ITEMS = [
    ('INFINITE', "Infinite", "Loop continuously from the end frame back to the start frame", fbp_icon("FILE_REFRESH"), 0),
    ('STOP_END_FRAME', "Stop at End", "Stop playback on the final frame", fbp_icon("PAUSE"), 1),
    ('STOP_START_FRAME', "Return to Start", "Return to the first frame and stop", fbp_icon("REW"), 2),
    ('RESTORE', "Restore Frame", "Stop on the frame where playback started", fbp_icon("RECOVER_LAST"), 3),
    ('BOUNCE', "Bounce", "Reverse playback direction at the range boundaries", fbp_icon("ARROW_LEFTRIGHT"), 4),
]

ANISOTROPIC_FILTER_ITEMS = [
    ('FILTER_0', "Off", "Disable anisotropic texture filtering", fbp_icon("ALIASED"), 0),
    ('FILTER_2', "2×", "Use two anisotropic samples", fbp_icon("ANTIALIASED"), 1),
    ('FILTER_4', "4×", "Use four anisotropic samples", fbp_icon("ANTIALIASED"), 2),
    ('FILTER_8', "8×", "Use eight anisotropic samples for sharper image planes at oblique angles", fbp_icon("ANTIALIASED"), 3),
    ('FILTER_16', "16×", "Use sixteen anisotropic samples for maximum texture sharpness", fbp_icon("ANTIALIASED"), 4),
]

INTERPOLATION_ITEMS = [
    ('Closest', "Pixel", "Sharp edges and pixel-art filtering", fbp_icon("ALIASED"), 0),
    ('Linear', "Smooth", "Bilinear image filtering", fbp_icon("ANTIALIASED"), 1),
]

RIG_SHAPE_ITEMS = [
    ('DEFAULT', "Default", "Adaptive square or rectangle matching the visible plane", fbp_icon("MOD_MESHDEFORM"), 0),
    ('RECTANGLE', "Rectangle", "Rectangular Frame By Plane control", fbp_icon("MESH_PLANE"), 1),
    ('CIRCLE', "Circle", "Circular control, useful for suns, heads and round assets", fbp_icon("MESH_CIRCLE"), 2),
    ('DIAMOND', "Diamond", "Diamond-shaped control", fbp_icon("MESH_CUBE"), 3),
    ('HEXAGON', "Hexagon", "Six-sided control", fbp_icon("MESH_GRID"), 4),
    ('OCTAGON', "Octagon", "Eight-sided control", fbp_icon("MESH_CIRCLE"), 5),
    ('CUSTOM', "Custom", "Edit and keep the control-rig mesh itself", fbp_icon("TOOL_SETTINGS"), 6),
]


ORIENTATION_ITEMS = [
    ('HORIZ', "Horizontal", "Generate planes parallel to the ground", fbp_icon("AXIS_TOP"), 0),
    ('VERT', "Vertical", "Generate standing planes facing the camera", fbp_icon("AXIS_FRONT"), 1),
]

CREATION_MODE_ITEMS = [
    ('SINGLE', "Single Plane", "Create one Frame By Plane layer from a still image or numbered image sequence.", fbp_icon("IMAGE_DATA"), 0),
    ('VIDEO', "Video Plane", "Create one Frame By Plane rig from a supported video/movie file while keeping the source linked to disk.", fbp_icon("FILE_MOVIE"), 1),
    ('MULTI', "Multiplane", "Open Multiplane Setup to organize multiple stills, sequences, videos and folder collections before generating depth-spaced layers for parallax animation.", fbp_icon("RENDERLAYERS"), 2),
    ('CUTOUT', "Cutout Plane", "Create one lightweight Cutout Plane whose ordered drawing library can be switched or keyframed for mouths, poses, expressions and replacement animation.", fbp_icon("MESH_DATA"), 3),
    ('COLOR', "Color Plane", "Create a camera-ratio procedural plane with an editable solid RGBA color, optional emission shading and no external image dependency.", fbp_icon("IMAGE"), 4),
    ('GRADIENT', "Gradient Plane", "Create a camera-ratio plane with an editable linear or radial ColorRamp, alpha mode and local mapping controls.", fbp_icon("NODE_TEXTURE"), 5),
    ('HOLDOUT', "Holdout Plane", "Create an alpha-aware Holdout Plane for masking and compositing while preserving Frame By Plane layer controls and camera fitting.", fbp_icon("GHOST_DISABLED"), 6),
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

SHIFT_A_MENU_POSITION_ITEMS = [
    ('TOP', "Top", "Show Frame By Plane at the top of the main Shift+A list", 'TRIA_UP', 0),
    ('IMAGE', "Image", "Show Frame By Plane inside Blender's Shift+A > Image submenu", 'IMAGE_DATA', 1),
    ('BOTTOM', "Bottom", "Show Frame By Plane at the bottom of the main Shift+A list", 'TRIA_DOWN', 2),
]

UILIST_ICON_PRESET_ITEMS = [
    ('FULL', "Full", "Show all supported Layer and Effect UI List icons", fbp_icon("HIDE_OFF"), 0),
    ('ESSENTIAL', "Essential", "Keep the most useful visibility, clipping, lock and selection controls", fbp_icon("CHECKMARK"), 1),
    ('MINIMAL', "Minimal", "Reduce UI Lists to names and core visibility/selection controls", fbp_icon("HIDE_ON"), 2),
    ('CUSTOM', "Custom", "Choose each optional UI List icon independently", fbp_icon("PREFERENCES"), 3),
]

EFFECTS_VIEW_ITEMS = [
    ('2D', "Image Effects", "Open the Image effects tab by default", fbp_icon("SHADERFX"), 0),
    ('MASK', "Mask", "Open the Mask tab by default", fbp_icon("MOD_MASK"), 1),
    ('3D', "Mesh Effects", "Open the Mesh effects tab by default", fbp_icon("MOD_SCATTER_ON_SURFACE"), 2),
]

PREVIEW_MODE_ITEMS = [
    ('MINIMAL', "Minimal", "Use type icons only; disable thumbnails and procedural color chips", fbp_icon("HIDE_ON"), 0),
    ('COLORS', "Color Chips", "Show Color and Gradient previews without loading image thumbnails", fbp_icon("COLOR"), 1),
    ('THUMBNAILS', "Thumbnails", "Show image thumbnails plus Color and Gradient previews", fbp_icon("IMAGE_DATA"), 2),
]

LAYER_ORDER_ITEMS = [
    ('SCENE', "Scene Order", "Follow collection and scene order in the Layer List", fbp_icon("OUTLINER"), 0),
    ('ALPHABETICAL', "Alphabetical", "Sort Layer List rows alphabetically without changing scene order", fbp_icon("SORTALPHA"), 1),
]


def _get_default_preview_mode(self):
    if bool(getattr(self, "default_show_previews", False)):
        return 2
    if bool(getattr(self, "default_show_color_previews", True)):
        return 1
    return 0


def _set_default_preview_mode(self, value):
    value = int(value or 0)
    self.default_show_previews = value >= 2
    self.default_show_color_previews = value >= 1


def _get_default_layer_order(self):
    return 1 if bool(getattr(self, "default_sort_layers_alpha", False)) else 0


def _set_default_layer_order(self, value):
    self.default_sort_layers_alpha = int(value or 0) == 1


_PREFERENCES_INIT_RETRY_LIMIT = 40
_preferences_init_attempts = 0


# SECTION 00B - Proxy callbacks to core.py #
def _fbp_core_func(name):
    from . import core
    return getattr(core, name)


def _call_core(name, *args, default=None):
    owner = args[0] if args else None
    if fbp_undo_guard_active() or (owner is not None and fbp_is_silent_property_update(owner)):
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
    owner = args[0] if args else None
    if fbp_undo_guard_active() or (owner is not None and fbp_is_silent_property_update(owner)):
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
    if fbp_undo_guard_active() or fbp_is_silent_property_update(self):
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
        fbp_warn("Could not rename Frame By Plane layer", exc)


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
        fbp_warn("Could not clear Frame By Plane thumbnail previews", exc)


def update_alpha_render_method_cb(self, context):
    """Apply the selected alpha method to every owned FBP material in this Scene."""
    if fbp_is_silent_property_update(self) or fbp_undo_guard_active():
        return
    try:
        from .materials import fbp_refresh_material_render_methods
        fbp_refresh_material_render_methods(scene=self)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not update Frame By Plane alpha rendering", exc)
    fbp_request_redraw(
        context,
        area_types={'VIEW_3D', 'PROPERTIES'},
        all_windows=True,
    )


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


def _fbp_effect_requires_material_preview(effect_id):
    """Return whether Solid/Wireframe cannot show the edited effect."""
    effect_id = str(effect_id or "").upper()
    if not effect_id:
        return False
    try:
        from .effects_registry import fbp_effect_definition
        definition = fbp_effect_definition(effect_id)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        definition = {}
    return bool(
        str(definition.get("kind", "") or "").upper() == "SHADER"
        or effect_id == "EMISSION"
        or bool(definition.get("material_preview", False))
    )


def _fbp_effect_preview_area(context):
    """Resolve one intentional viewport target without changing other windows."""
    if context is None:
        return None
    try:
        area = getattr(context, "area", None)
        if str(getattr(area, "type", "") or "") == "VIEW_3D":
            return area
        window = getattr(context, "window", None)
        screen = (
            getattr(window, "screen", None)
            if window is not None
            else getattr(context, "screen", None)
        )
        candidates = [
            candidate
            for candidate in tuple(getattr(screen, "areas", ()) or ())
            if str(getattr(candidate, "type", "") or "") == "VIEW_3D"
        ]
        return max(
            candidates,
            key=lambda candidate: int(getattr(candidate, "width", 0) or 0)
            * int(getattr(candidate, "height", 0) or 0),
            default=None,
        )
    except FBP_DATA_ERRORS:
        return None


def fbp_ensure_effect_preview_mode(context, effect_id):
    """Reveal one shader effect after a real add/edit interaction.

    Material Preview and Rendered are both accepted. The function deliberately
    touches only the active screen's most relevant 3D View and is never called
    by tab selection, row selection, redraw, load or frame handlers.
    """
    if context is None or not _fbp_effect_requires_material_preview(effect_id):
        return False
    area = _fbp_effect_preview_area(context)
    if area is None:
        return False
    try:
        space = getattr(getattr(area, "spaces", None), "active", None)
        shading = getattr(space, "shading", None)
        shading_type = (
            str(getattr(shading, "type", "SOLID") or "SOLID")
            if shading is not None else ""
        )
        if shading is None or shading_type in {"MATERIAL", "RENDERED"}:
            return False
        shading.type = "MATERIAL"
        area.tag_redraw()
        return True
    except FBP_DATA_ERRORS:
        return False

def update_effects_index_cb(self, context):
    """Reveal controls without changing the artist's viewport shading."""
    if fbp_undo_guard_active() or fbp_is_silent_property_update(self):
        return
    effect_id = ""
    try:
        items = getattr(self, "fbp_effects", ())
        index = int(getattr(self, "fbp_effects_index", 0) or 0)
        if 0 <= index < len(items):
            effect_id = str(getattr(items[index], "effect_id", "") or "")
    except (AttributeError, IndexError, ReferenceError, RuntimeError, TypeError, ValueError):
        effect_id = ""
    try:
        from .effect_controls import (
            prepare_effect_control_selection,
            schedule_active_effect_controls,
        )
        prepare_effect_control_selection(context, self, effect_id)
        schedule_active_effect_controls(context, select_active=False)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        from .geometry_nodes import fbp_load_active_effect_instance_settings
        fbp_load_active_effect_instance_settings(self)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


def update_effect_controls_enabled_cb(self, context):
    if fbp_undo_guard_active() or fbp_is_silent_property_update(self):
        return
    try:
        from .effect_controls import (
            hide_rig_effect_controls,
            sync_active_effect_controls,
        )
        if bool(getattr(self, "fbp_effect_controls_enabled", True)):
            # The toggle itself is an explicit Blender UI edit. Create missing
            # helpers synchronously so the controller becomes usable at once
            # and remains inside the same Undo step.
            sync_active_effect_controls(
                context,
                select_active=False,
                create_missing=True,
            )
        else:
            hide_rig_effect_controls(self)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


# SECTION 00C - Add-on Preferences #

def update_interface_preferences_cb(self, context):
    """Invalidate UI caches and redraw without changing the user's sidebar state."""
    clear_interface_preferences_cache()
    fbp_request_redraw(
        context,
        area_types={'VIEW_3D', 'PROPERTIES', 'PREFERENCES'},
        all_windows=True,
    )


def update_shift_a_menu_position_cb(self, context):
    """Re-register the Shift+A entry at its newly selected location."""
    if fbp_undo_guard_active() or fbp_is_silent_property_update(self):
        return
    try:
        from .service_registry import call_service
        call_service("ui.refresh_shift_a_menu", default=None)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    update_interface_preferences_cb(self, context)


def update_shortcut_preferences_cb(self, context):
    """Rebuild interactive keymaps immediately after a shortcut preference edit."""
    if fbp_undo_guard_active() or fbp_is_silent_property_update(self):
        return
    try:
        refresh_all_shortcuts()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    update_interface_preferences_cb(self, context)


class FBP_AddonPreferences(AddonPreferences):
    bl_idname = __package__ if __package__ else "frame_by_plane"

    shift_a_menu_position: EnumProperty(
        name="Shift+A Position",
        description="Choose where the Frame By Plane submenu appears in Blender's Add menu",
        items=SHIFT_A_MENU_POSITION_ITEMS,
        default='TOP',
        update=update_shift_a_menu_position_cb,
    )
    show_control_panel_properties: BoolProperty(
        name="Properties",
        description="Show Frame By Plane control panels in Blender Properties and the standard Tool context",
        default=True,
        update=update_interface_preferences_cb,
    )
    show_control_panel_n_panel: BoolProperty(
        name="N-Panel / Side Panel",
        description="Show Frame By Plane control panels in the dedicated Frame By Plane tab of the 3D View N-Panel",
        default=False,
        update=update_interface_preferences_cb,
    )
    shortcut_duplicate_layer: BoolProperty(
        name="Duplicate Layer",
        description="Use Shift+D for Frame By Plane-aware duplication in Object Mode; ordinary objects still use Blender Duplicate",
        default=True,
        update=update_shortcut_preferences_cb,
    )
    shortcut_group_layers: BoolProperty(
        name="Move Layers to/from Collections",
        description=f"Use {primary_shortcut_label('G')} to group selected layers and {primary_shortcut_label('G', shift=True)} to ungroup them",
        default=True,
        update=update_shortcut_preferences_cb,
    )
    shortcut_viewport_pie: BoolProperty(
        name="Viewport Pie",
        description="Use Z for the native Blender Frame By Plane Pie Menu",
        default=True,
        update=update_shortcut_preferences_cb,
    )
    pie_north_content: EnumProperty(
        name="North Area",
        description="Choose what the north sector of the native Z Pie displays",
        items=(
            (
                'CURSOR_PIVOT',
                "Cursor + Pivot",
                "Show Cursor On Camera when available and the compact pivot controls",
                'PIVOT_CURSOR',
                0,
            ),
            (
                'PIVOT',
                "Pivot Point",
                "Show only the compact pivot controls",
                'PIVOT_MEDIAN',
                1,
            ),
            (
                'ORIENTATION',
                "Orientation",
                "Show the active transform orientation",
                'ORIENTATION_GLOBAL',
                2,
            ),
            (
                'HIDDEN',
                "Hidden",
                "Leave the north sector empty",
                'HIDE_ON',
                3,
            ),
        ),
        default='CURSOR_PIVOT',
    )
    pie_show_south_actions: BoolProperty(
        name="South Actions",
        description="Show Hide, Solo, Lock, Selectability and Holdout in the south sector",
        default=True,
    )
    pie_show_masks: BoolProperty(
        name="Mask Area",
        description="Show Frame By Plane mask favourites in the south-west sector",
        default=True,
    )
    pie_show_effects: BoolProperty(
        name="Effect Area",
        description="Show Frame By Plane or Grease Pencil effects in the south-east sector",
        default=True,
    )
    shortcut_tab_layer_edit: BoolProperty(
        name="Layer Edit Mode",
        description="Use Tab to enter the relevant edit mode for Frame By Plane layers while passing ordinary objects through to Blender",
        default=True,
        update=update_shortcut_preferences_cb,
    )
    shortcut_gp_alt_s_guard: BoolProperty(
        name="Grease Pencil Radius Guard",
        description=f"Observe {alt_shortcut_label('S')} during Grease Pencil mask editing so the live mask preview refreshes after Blender changes stroke radius",
        default=True,
        update=update_shortcut_preferences_cb,
    )
    shortcut_gp_frame_scrub: BoolProperty(
        name="Grease Pencil Frame Scrub",
        description="Tap < in any 3D View mode to toggle the interactive Scrub Bar, or hold it for momentary scrubbing",
        default=True,
        update=update_shortcut_preferences_cb,
    )
    gp_scrub_max_range: IntProperty(
        name="Scrub Range",
        description="Total number of frames shown by the Scrub Bar before edge hold continues scrolling",
        default=50,
        min=1,
        max=240,
        update=update_interface_preferences_cb,
    )
    gp_scrub_position: EnumProperty(
        name="Position",
        description="Edge of the active Viewport used by the Grease Pencil frame scrub slider",
        items=(
            ('TOP', "North", "Horizontal slider at the top", 'TRIA_UP', 0),
            ('BOTTOM', "South", "Horizontal slider at the bottom", 'TRIA_DOWN', 1),
            ('LEFT', "West", "Vertical slider on the left", 'TRIA_LEFT', 2),
            ('RIGHT', "East", "Vertical slider on the right", 'TRIA_RIGHT', 3),
        ),
        default='LEFT',
        update=update_interface_preferences_cb,
    )
    gp_scrub_show_info: BoolProperty(
        name="Show Interaction Info",
        description="Show the Snap status and keyboard help beside the Scrub Slider",
        default=False,
        update=update_interface_preferences_cb,
    )
    gp_scrub_invert_vertical: BoolProperty(
        name="Invert Top and Bottom Frames",
        description="For vertical sliders, place earlier frames at the top and later frames at the bottom",
        default=False,
        update=update_interface_preferences_cb,
    )
    gp_scrub_sensitivity: FloatProperty(
        name="Sensitivity", description="Mouse movement multiplier", default=2.0, min=0.1, max=12.0,
        update=update_interface_preferences_cb,
    )
    gp_scrub_shift_factor: FloatProperty(
        name="Shift Slowdown", description="Sensitivity multiplier while Shift is held", default=0.2, min=0.02, max=1.0,
        update=update_interface_preferences_cb,
    )
    gp_scrub_length_ratio: FloatProperty(
        name="Length", description="Slider length relative to the active Viewport", subtype='FACTOR', default=0.5, min=0.2, max=1.0,
        update=update_interface_preferences_cb,
    )
    gp_scrub_edge_offset: FloatProperty(
        name="Edge Offset", description="Distance of the slider from the selected Viewport edge", default=240.0, min=8.0, max=240.0, subtype='PIXEL',
        update=update_interface_preferences_cb,
    )
    gp_scrub_mouse_magnet: BoolProperty(
        name="Mouse Magnet",
        description="Pull the Scrub Bar toward the cursor when it approaches the axis",
        default=True,
        update=update_interface_preferences_cb,
    )
    gp_scrub_mouse_magnet_distance: FloatProperty(
        name="Magnet Range",
        description="Distance in pixels at which the Scrub Bar starts moving toward the cursor",
        default=96.0,
        min=24.0,
        max=240.0,
        subtype='PIXEL',
        update=update_interface_preferences_cb,
    )
    gp_scrub_mouse_magnet_strength: FloatProperty(
        name="Magnet Strength",
        description="How closely the Scrub Bar follows the cursor inside the magnetic range",
        subtype='FACTOR',
        default=1.0,
        min=0.0,
        max=1.0,
        update=update_interface_preferences_cb,
    )
    gp_scrub_mouse_magnet_smoothing: FloatProperty(
        name="Magnet Smoothing",
        description="Transition speed used when the Scrub Bar attaches to or releases from the cursor",
        subtype='FACTOR',
        default=0.22,
        min=0.01,
        max=1.0,
        update=update_interface_preferences_cb,
    )
    gp_scrub_tick_scale: FloatProperty(
        name="Tick Size", description="Scale of frame and second ticks", default=0.5, min=0.25, max=3.0,
        update=update_interface_preferences_cb,
    )
    gp_scrub_line_width: FloatProperty(
        name="Line Thickness",
        description="Thickness of the slider axis, ticks and keyframe borders",
        default=1.0,
        min=0.5,
        max=6.0,
        update=update_interface_preferences_cb,
    )
    gp_scrub_cursor_width: FloatProperty(
        name="Cursor Thickness", description="Thickness of the current-frame cursor connector", default=2.0, min=0.5, max=8.0,
        update=update_interface_preferences_cb,
    )
    gp_scrub_cursor_label_scale: FloatProperty(
        name="Cursor Label Size", description="Scale of the rounded current-frame number label", default=1.0, min=0.6, max=2.0,
        update=update_interface_preferences_cb,
    )
    gp_scrub_major_interval: IntProperty(
        name="Long Tick Interval", description="Draw a longer lower tick every N frames", default=10, min=2, max=100,
        update=update_interface_preferences_cb,
    )
    gp_scrub_micro_tick_length: FloatProperty(
        name="Frame Tick Length", description="Length of the small tick drawn for every frame", default=3.0, min=1.0, max=20.0,
        update=update_interface_preferences_cb,
    )
    gp_scrub_major_tick_length: FloatProperty(
        name="Long Tick Length", description="Length of the lower interval ticks", default=7.0, min=2.0, max=32.0,
        update=update_interface_preferences_cb,
    )
    gp_scrub_second_tick_length: FloatProperty(
        name="Second Tick Length", description="Half-length of ticks drawn across both sides at every scene second", default=11.0, min=3.0, max=48.0,
        update=update_interface_preferences_cb,
    )
    gp_scrub_cursor_color: FloatVectorProperty(
        name="Cursor Color", description="Color of the current-frame line and rounded number label", subtype='COLOR', size=3,
        default=(71 / 255, 114 / 255, 179 / 255), min=0.0, max=1.0,
        update=update_interface_preferences_cb,
    )
    gp_scrub_cursor_text_color: FloatVectorProperty(
        name="Cursor Text Color", description="Text color inside the current-frame label", subtype='COLOR', size=3,
        default=(1.0, 1.0, 1.0), min=0.0, max=1.0,
        update=update_interface_preferences_cb,
    )
    gp_scrub_line_color: FloatVectorProperty(
        name="Axis Color",
        description="Color of the free-floating scrub axis",
        subtype='COLOR',
        size=3,
        default=(0.0, 0.0, 0.0),
        min=0.0,
        max=1.0,
        update=update_interface_preferences_cb,
    )
    gp_scrub_frame_tick_color: FloatVectorProperty(
        name="Frame Tick Color",
        description="RGBA color of the small tick drawn for every frame",
        subtype='COLOR',
        size=4,
        default=(0.0, 0.0, 0.0, 0.58),
        min=0.0,
        max=1.0,
        update=update_interface_preferences_cb,
    )
    gp_scrub_major_tick_color: FloatVectorProperty(
        name="Long Tick Color",
        description="RGBA color of the configurable interval ticks",
        subtype='COLOR',
        size=4,
        default=(0.0, 0.0, 0.0, 1.0),
        min=0.0,
        max=1.0,
        update=update_interface_preferences_cb,
    )
    gp_scrub_second_tick_color: FloatVectorProperty(
        name="Second Tick Color",
        description="RGBA color of the framerate-based second ticks",
        subtype='COLOR',
        size=4,
        default=(0.0, 0.0, 0.0, 1.0),
        min=0.0,
        max=1.0,
        update=update_interface_preferences_cb,
    )
    gp_scrub_text_color: FloatVectorProperty(
        name="Text Color",
        description="Color of frame numbers and the live snap status",
        subtype='COLOR',
        size=3,
        default=(0.0, 0.0, 0.0),
        min=0.0,
        max=1.0,
        update=update_interface_preferences_cb,
    )
    show_panel_layers: BoolProperty(
        name="Layers Panel",
        description="Show the Frame By Plane Layers section in enabled panel locations",
        default=True,
        update=update_interface_preferences_cb,
    )
    show_panel_grease_pencil: BoolProperty(
        name="Grease Pencil Panel",
        description="Show the Frame By Plane Grease Pencil section in enabled panel locations",
        default=True,
        update=update_interface_preferences_cb,
    )
    show_panel_layer_settings: BoolProperty(
        name="Layer Settings Panel",
        description="Show selected-layer settings in enabled panel locations",
        default=True,
        update=update_interface_preferences_cb,
    )
    uilist_icon_preset: EnumProperty(
        name="UI List Icon Preset",
        description="Choose how many controls and status icons appear in Frame By Plane UI Lists",
        items=UILIST_ICON_PRESET_ITEMS,
        default='FULL',
        update=update_interface_preferences_cb,
    )
    uilist_label_alignment: EnumProperty(
        name="List Name Alignment",
        description="Align the flexible name cell in every customizable UI List row",
        items=(
            ('LEFT', "Left", "Align row names to the left"),
            ('CENTER', "Center", "Center row names"),
            ('RIGHT', "Right", "Align row names to the right"),
        ),
        default='LEFT',
        update=update_interface_preferences_cb,
    )
    uilist_show_preview: BoolProperty(name="Layer Type / Preview", description="Show the layer type, color tag or thumbnail slot beside layer names", default=True, update=update_interface_preferences_cb)
    uilist_show_clipping: BoolProperty(name="Clipping Mask", description="Show the clipping-mask control beside layer names", default=True, update=update_interface_preferences_cb)
    uilist_show_visibility: BoolProperty(name="Visibility", description="Show layer and collection visibility controls", default=True, update=update_interface_preferences_cb)
    uilist_show_solo: BoolProperty(name="Solo", description="Show layer, collection and effect solo controls", default=True, update=update_interface_preferences_cb)
    uilist_show_holdout: BoolProperty(name="Holdout", description="Show layer and collection holdout controls", default=True, update=update_interface_preferences_cb)
    uilist_show_motion: BoolProperty(name="Motion", description="Show the Motion enable control when a layer has Motion effects", default=True, update=update_interface_preferences_cb)
    uilist_show_plane: BoolProperty(name="Select Plane", description="Show the linked-plane selection control", default=True, update=update_interface_preferences_cb)
    uilist_show_lock: BoolProperty(name="Lock", description="Show layer, collection and Grease Pencil lock controls", default=True, update=update_interface_preferences_cb)
    uilist_show_select: BoolProperty(name="Select Rig", description="Show layer, collection and Grease Pencil selection checkboxes", default=True, update=update_interface_preferences_cb)
    uilist_show_effect_type: BoolProperty(name="Effect Type", description="Show each effect's category icon beside its name", default=True, update=update_interface_preferences_cb)
    uilist_show_effect_viewport: BoolProperty(name="Effect Viewport", description="Show effect viewport visibility controls", default=True, update=update_interface_preferences_cb)
    uilist_show_effect_mask: BoolProperty(name="Effect Mask", description="Show the per-effect mask shortcut in Image Effects lists", default=True, update=update_interface_preferences_cb)

    # Per-list column layout. Values are compact comma-separated stable IDs so
    # preferences remain portable and do not require mutable RNA collections.
    uilist_order_layer_planes: StringProperty(default="preview,clipping,label,visibility,solo,holdout,plane,lock,select", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_visible_layer_planes: StringProperty(default="preview,clipping,label,visibility,solo,holdout,plane,lock,select", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_order_layer_gp: StringProperty(default="preview,label,visibility,solo,plane,lock,select", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_visible_layer_gp: StringProperty(default="preview,label,visibility,solo,plane,lock,select", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_order_effect_image: StringProperty(default="effect_select,effect_type,label,effect_solo,effect_viewport,effect_mask", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_visible_effect_image: StringProperty(default="effect_select,effect_type,label,effect_solo,effect_viewport,effect_mask", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_order_effect_mask: StringProperty(default="effect_type,label,effect_solo,effect_viewport", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_visible_effect_mask: StringProperty(default="effect_type,label,effect_solo,effect_viewport", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_order_effect_mesh: StringProperty(default="effect_type,label,effect_solo,effect_viewport", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_visible_effect_mesh: StringProperty(default="effect_type,label,effect_solo,effect_viewport", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_order_sequence_frames: StringProperty(default="frame_state,frame_preview,label,frame_duration,frame_select", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_visible_sequence_frames: StringProperty(default="frame_state,frame_preview,label,frame_duration,frame_select", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_order_pending_setup: StringProperty(default="pending_color,pending_status,label,pending_reverse,pending_select,pending_edit,pending_delete", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_visible_pending_setup: StringProperty(default="pending_color,pending_status,label,pending_reverse,pending_select,pending_edit,pending_delete", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_order_layer_sets: StringProperty(default="label,count,apply", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_visible_layer_sets: StringProperty(default="label,count,apply", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_order_visibility_snapshots: StringProperty(default="label,count,apply", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_visible_visibility_snapshots: StringProperty(default="label,count,apply", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_order_mask_sources: StringProperty(default="preview,label,apply", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_visible_mask_sources: StringProperty(default="preview,label,apply", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_order_effect_stack_presets: StringProperty(default="preview,label,count,apply", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_visible_effect_stack_presets: StringProperty(default="preview,label,count,apply", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_order_layer_filter_presets: StringProperty(default="preview,label,apply", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_visible_layer_filter_presets: StringProperty(default="preview,label,apply", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_order_drawings: StringProperty(default="current,preview,label,remove", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_visible_drawings: StringProperty(default="current,preview,label,remove", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_order_motion_items: StringProperty(default="enabled,preview,selected,label,slot,link,remove", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_visible_motion_items: StringProperty(default="enabled,preview,selected,label,slot,link,remove", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_order_generation_rename: StringProperty(default="status,label", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_visible_generation_rename: StringProperty(default="status,label", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_order_performance_rows: StringProperty(default="status,label,metric_primary,metric_secondary", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_visible_performance_rows: StringProperty(default="status,label,metric_primary,metric_secondary", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_order_compositor_layers: StringProperty(default="label,compositor_visibility,compositor_holdout,compositor_indirect", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_visible_compositor_layers: StringProperty(default="label,compositor_visibility,compositor_holdout,compositor_indirect", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_order_compositor_effects: StringProperty(default="label,compositor_enabled,compositor_mix", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_visible_compositor_effects: StringProperty(default="label,compositor_enabled,compositor_mix", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_order_project_doctor: StringProperty(default="doctor_severity,label,doctor_fix,doctor_select", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_visible_project_doctor: StringProperty(default="doctor_severity,label,doctor_fix,doctor_select", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_order_compositor_packages: StringProperty(default="package_select,package_type,label,package_visibility,package_output", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_visible_compositor_packages: StringProperty(default="package_select,package_type,label,package_visibility,package_output", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_order_layer_set_rows: StringProperty(default="set_source,label,set_visibility,set_select,set_pin", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_visible_layer_set_rows: StringProperty(default="set_source,label,set_visibility,set_select,set_pin", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_order_output_passes: StringProperty(default="label,output_enabled,output_link,output_format", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_visible_output_passes: StringProperty(default="label,output_enabled,output_link,output_format", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_order_compositor_stack: StringProperty(default="label,stack_enabled,stack_link", options={'HIDDEN'}, update=update_interface_preferences_cb)
    uilist_visible_compositor_stack: StringProperty(default="label,stack_enabled,stack_link", options={'HIDDEN'}, update=update_interface_preferences_cb)

    default_effects_view: EnumProperty(
        name="Default Effects Tab",
        description="Effects category selected when Frame By Plane initializes a scene",
        items=EFFECTS_VIEW_ITEMS,
        default='2D',
    )
    default_preview_mode: EnumProperty(
        name="List Preview Style",
        description="Choose how much visual information appears in Layer, Frame and Cutout lists",
        items=PREVIEW_MODE_ITEMS,
        get=_get_default_preview_mode,
        set=_set_default_preview_mode,
    )
    default_layer_order: EnumProperty(
        name="Default Layer Order",
        description="Choose whether new scenes follow scene order or display layers alphabetically",
        items=LAYER_ORDER_ITEMS,
        get=_get_default_layer_order,
        set=_set_default_layer_order,
    )

    default_project_path: StringProperty(
        name="Default Project Folder",
        description="Folder automatically assigned to new Frame By Plane scenes",
        subtype='DIR_PATH',
        default="",
    )
    default_last_directory: StringProperty(
        name="Default File Browser Folder",
        description="Starting folder used by Frame By Plane import file browsers",
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
    default_plane_start_frame_mode: EnumProperty(
        name="New Plane Start",
        description="Choose whether newly generated planes begin at the current timeline cursor or at the Scene start frame",
        items=PLANE_START_FRAME_MODE_ITEMS,
        default='PLAYHEAD',
    )
    default_scene_fps: IntProperty(
        name="Default Scene FPS",
        description="Frames per second assigned to new Frame By Plane scenes",
        default=24, min=1, max=240,
    )
    default_playback: EnumProperty(description="Playback behavior assigned by default to newly imported animated planes: One Shot, Loop or Ping-Pong.", name="Default Playback", items=PLAYBACK_ITEMS, default='NONE')
    default_scene_playback_loop_mode: EnumProperty(
        name="Timeline Loop Mode",
        description="Native Blender 5.2 behavior when timeline playback reaches the final frame",
        items=SCENE_PLAYBACK_LOOP_MODE_ITEMS,
        default='INFINITE',
    )
    default_scene_allow_preroll: BoolProperty(
        name="Allow Timeline Preroll",
        description="Allow Blender 5.2 playback before the scene start frame",
        default=False,
    )
    default_interpolation: EnumProperty(description="Texture filtering assigned by default to new image layers. Pixel preserves hard edges; Smooth uses linear interpolation.", name="Default Image Filter", items=INTERPOLATION_ITEMS, default='Closest')
    default_emission: BoolProperty(
        name="Emission Textures",
        description="Use lightweight shadeless materials for newly imported image layers",
        default=True,
    )
    default_import_crop_alpha: BoolProperty(
        name="Crop Transparent Borders",
        description=(
            "Automatically remove fully transparent outer pixels from newly imported images, "
            "image sequences, PSD/PSB layers and Procreate layers while keeping the rig origin "
            "at the center of the original canvas"
        ),
        default=False,
    )
    default_import_crop_alpha_padding: IntProperty(
        name="Alpha Crop Padding",
        description="Transparent-border margin retained around automatically cropped visible pixels",
        default=0, min=0, soft_max=32, max=256,
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
    default_camera_fit_source_aspect: BoolProperty(
        name="Camera Uses Source Aspect",
        description="When Frame By Plane generates a camera from Shift+A or Multiplane tools, match output resolution to the first generated layer source aspect",
        default=True,
    )
    default_track_camera: BoolProperty(
        name="Track Camera on New Layers",
        description="Add camera tracking to newly created Frame By Plane layers",
        default=False,
    )
    default_generate_camera: BoolProperty(
        name="Create Camera",
        description="Create a camera by default for new Multiplane projects",
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
        description="Remove orphaned Frame By Plane planes and unused owned datablocks after normal deletion",
        default=True,
    )
    default_preview_compositor: BoolProperty(
        name="Compositor Layers",
        description="Enable the Compositor Layers preview in newly initialized files; it is outside the Frame By Plane 7.1 LTS core scope",
        default=False,
    )
    default_preview_procreate_import: BoolProperty(
        name="Procreate Import",
        description="Enable the Procreate archive decoder preview in newly initialized files; PSD/PSB import remains in the LTS scope",
        default=False,
    )
    default_preview_generic_mesh_effects: BoolProperty(
        name="Generic Mesh Effects",
        description="Enable the preview that applies selected Frame By Plane Geometry Nodes effects to ordinary mesh objects",
        default=False,
    )
    default_show_previews: BoolProperty(
        name="List Thumbnails",
        description="Show thumbnails inside layer, frame and Cutout library lists; the large active Cutout preview always remains visible",
        default=False,
    )
    default_show_color_previews: BoolProperty(
        name="Color Previews",
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
        default=False,
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
        description="Surface transparency method assigned to Frame By Plane materials. Auto uses depth-safe Dithered alpha",
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
        description="Optional filename prefix used by the render name builder",
        default="",
    )
    default_render_folder_mode: EnumProperty(
        name="Default Render Destination",
        description="Default destination mode used when explicitly applying Frame By Plane render defaults",
        items=RENDER_FOLDER_MODE_ITEMS,
        default='ROOT',
    )
    default_render_name_source: EnumProperty(
        name="Default Render Name",
        description="Default principal filename component used by the render name builder",
        items=RENDER_NAME_SOURCE_ITEMS,
        default='DOCUMENT',
    )
    default_render_separator: EnumProperty(
        name="Default Name Separator",
        description="Default separator inserted between render filename components",
        items=RENDER_SEPARATOR_ITEMS,
        default='DASH',
    )
    default_render_frame_digits: IntProperty(
        name="Default Frame Digits",
        description="Default frame-number zero padding used by the render name builder",
        default=4,
        min=1,
        max=8,
    )
    default_render_auto_increment_test: BoolProperty(
        name="Auto-increment TEST Folders",
        description="Select the next available TEST number before each background render",
        default=True,
    )
    default_cycles_texture_cache: BoolProperty(
        name="Cycles Texture Cache",
        description="Use Blender 5.2's disk-backed texture cache for image-heavy Cycles scenes",
        default=True,
    )
    default_cycles_auto_texture_cache: BoolProperty(
        name="Generate Texture Cache Automatically",
        description="Allow Cycles to generate missing cached texture tiles automatically during rendering",
        default=False,
    )
    default_anisotropic_filter: EnumProperty(
        name="Anisotropic Filtering",
        description="Blender 5.2 texture filtering quality used by the current scene",
        items=ANISOTROPIC_FILTER_ITEMS,
        default='FILTER_2',
    )
    default_gp_fill_solver: EnumProperty(
        name="Grease Pencil Fill Solver",
        description="Native Blender 5.2 fill solver selected when entering Fill from Frame By Plane",
        items=GP_FILL_SOLVER_ITEMS,
        default='DELAUNAY',
    )
    default_gp_fill_gap_factor: FloatProperty(
        name="Fill Gap Detection",
        description="Maximum gap size considered by Blender's Delaunay Grease Pencil fill solver",
        default=0.4,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
    )
    default_gp_fill_auto_remove_guides: BoolProperty(
        name="Remove Fill Guides",
        description="Automatically remove temporary Grease Pencil fill guide strokes after filling",
        default=True,
    )
    default_gp_fill_internal_gaps: BoolProperty(
        name="Stop at Internal Gaps",
        description="Use Blender 5.2 internal-gap boundaries while generating Delaunay fills",
        default=True,
    )
    default_gp_curve_type: EnumProperty(
        name="Grease Pencil Curve Type",
        description="Blender 5.2 curve type selected when entering Draw from Frame By Plane",
        items=GP_CURVE_TYPE_ITEMS,
        default='POLY',
    )
    default_gp_curve_conversion_threshold: FloatProperty(
        name="Curve Conversion Threshold",
        description="Distance threshold Blender 5.2 uses when converting drawn input into smooth Grease Pencil curves",
        default=0.001,
        min=0.0,
        max=1000.0,
        soft_max=1.0,
        subtype='DISTANCE',
        unit='LENGTH',
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

    pref_ui_show_workflow_category: BoolProperty(name="Workflow", description="Show workflow, import, timing and procedural defaults", default=False)
    pref_ui_show_interface_category: BoolProperty(name="Interface", description="Show panel placement, list and interface customization", default=False)
    pref_ui_show_camera_render_category: BoolProperty(name="Camera & Render", description="Show camera, output and render defaults", default=False)
    pref_ui_show_advanced_category: BoolProperty(name="Advanced", description="Show performance, diagnostics, update and support tools", default=False)

    pref_ui_show_release: BoolProperty(name="Splash", description="Show release, splash and tutorial actions in Add-on Preferences", default=False)
    pref_ui_show_paths: BoolProperty(name="Paths", description="Show default folders and startup choices", default=False)
    pref_ui_show_import: BoolProperty(name="Import", description="Show import defaults", default=False)
    pref_ui_show_timing: BoolProperty(name="Timing", description="Show timing and playback defaults", default=False)
    pref_ui_show_gp_fill: BoolProperty(name="Grease Pencil Fill", description="Show Blender 5.2 Grease Pencil fill defaults", default=False)
    pref_ui_show_gp_scrub: BoolProperty(name="Frame Scrub Slider", description="Show Grease Pencil frame scrub slider settings", default=False)
    pref_ui_show_layers: BoolProperty(name="Layer UI", description="Show layer, list and preview defaults", default=False)
    pref_ui_show_camera: BoolProperty(name="Camera", description="Show camera and aspect defaults", default=False)
    pref_ui_show_render: BoolProperty(name="Render", description="Show render and output defaults", default=False)
    pref_ui_show_interface: BoolProperty(name="Interface", description="Show interface, preview and layer-list defaults", default=False)
    pref_ui_show_shortcuts: BoolProperty(name="Shortcuts", description="Show Frame By Plane shortcut controls", default=False)
    pref_ui_show_list_icons: BoolProperty(name="UI List Rows", description="Show modular UI List label and control customization", default=False)
    pref_ui_show_expanded: BoolProperty(name="Expanded Sections", description="Show defaults for expanded workflow sections", default=False)
    pref_ui_show_procedural: BoolProperty(name="Procedural", description="Show Color, Gradient and Holdout plane defaults", default=False)
    pref_ui_show_performance: BoolProperty(name="Performance", description="Show cleanup and performance defaults", default=False)
    pref_ui_show_preview_features: BoolProperty(name="Feature Scope", description="Show stable and preview feature controls", default=False)
    pref_ui_show_diagnostics: BoolProperty(name="Diagnostics", description="Show repair, health and report tools", default=False)
    pref_ui_show_links: BoolProperty(name="Links", description="Show update, review and support actions", default=False)

    pie_quick_effect_1: StringProperty(
        name="Pie Quick Effect 1",
        description="Effect assigned to Slot 1 in the Frame By Plane viewport Pie Menu",
        default="",
        options={'HIDDEN'},
    )
    pie_quick_effect_2: StringProperty(
        name="Pie Quick Effect 2",
        description="Effect assigned to Slot 2 in the Frame By Plane viewport Pie Menu",
        default="",
        options={'HIDDEN'},
    )
    pie_quick_effect_3: StringProperty(
        name="Pie Quick Effect 3",
        description="Effect assigned to Slot 3 in the Frame By Plane viewport Pie Menu",
        default="",
        options={'HIDDEN'},
    )
    pie_quick_effect_4: StringProperty(
        name="Pie Quick Effect 4",
        description="Effect assigned to Slot 4 in the Frame By Plane viewport Pie Menu",
        default="",
        options={'HIDDEN'},
    )
    pie_quick_effect_5: StringProperty(
        name="Pie Quick Effect 5",
        description="Effect assigned to Slot 5 in the Frame By Plane viewport Pie Menu",
        default="",
        options={'HIDDEN'},
    )
    pie_quick_mask_1: StringProperty(
        name="Pie Quick Mask 1",
        description="First mask shown in the Frame By Plane viewport Pie Menu",
        default="SHAPE_MASK",
        options={'HIDDEN'},
    )
    pie_quick_mask_2: StringProperty(
        name="Pie Quick Mask 2",
        description="Second mask shown in the Frame By Plane viewport Pie Menu",
        default="GREASE_PENCIL_MASK",
        options={'HIDDEN'},
    )
    pie_quick_mask_3: StringProperty(
        name="Pie Quick Mask 3",
        description="Third mask shown in the Frame By Plane viewport Pie Menu",
        default="COLOR_MASK",
        options={'HIDDEN'},
    )
    pie_quick_mask_4: StringProperty(
        name="Pie Quick Mask 4",
        description="Fourth mask shown in the Frame By Plane viewport Pie Menu",
        default="",
        options={'HIDDEN'},
    )
    pie_quick_mask_5: StringProperty(
        name="Pie Quick Mask 5",
        description="Fifth mask shown in the Frame By Plane viewport Pie Menu",
        default="",
        options={'HIDDEN'},
    )

    whats_new_enabled: BoolProperty(
        name="What's New After Updates",
        description="Show the local release-notes popup once after each new Frame By Plane release key. Fresh installs still create a silent baseline; intermediate updates can show their notes once. No telemetry or project data is collected",
        default=True,
    )
    whats_new_last_seen_version: StringProperty(description='Whats New Last Seen Version value used by the current Frame By Plane tool. Changes are applied only to compatible Frame By Plane data.',
        name="Last Viewed What's New Version",
        default="",
        options={'HIDDEN'},
    )

    def draw(self, context):
        layout = configure_layout(self.layout)

        def _pref_icon_kwargs(key, fallback='PREFERENCES'):
            try:
                kwargs = ui_icon_kwargs(key, fallback=key)
                if int(kwargs.get('icon_value', 0) or 0) > 0:
                    return kwargs
            except FBP_DATA_ERRORS:
                pass
            return {'icon': ui_icon(key) or fbp_icon(fallback)}

        # Fixed presentation: Comfortable responsive rows and Extra Airy spacing.
        def _preference_row_gap():
            return 0.46

        def _preference_section_gap():
            return 0.66

        def _minimal_collapsible(
            parent,
            prop_name,
            title,
            *,
            icon='PREFERENCES',
            icon_value=0,
            major=False,
            boxed=False,
        ):
            # Top-level categories stay directly on the Preferences canvas.
            # Only their individual subsections receive a compact box, avoiding
            # one large nested container around an entire category.
            section_gap(parent, 0.78 if major else _preference_section_gap())
            container = parent.box() if boxed else parent
            configure_layout(container)

            expanded = bool(getattr(self, prop_name, True))
            header = container.row(align=False)
            header.scale_y = 1.18 if major else 1.08
            header.prop(
                self,
                prop_name,
                text='',
                icon='DOWNARROW_HLT' if expanded else 'RIGHTARROW',
                emboss=False,
            )
            if int(icon_value or 0) > 0:
                header.label(text=title, icon_value=int(icon_value))
            else:
                header.label(text=title, icon=icon)
            if not expanded:
                return None

            body = container.column(align=False)
            configure_layout(body)
            return body

        def _section(parent, prop_name, title, icon_key, fallback='PREFERENCES'):
            icon_kwargs = _pref_icon_kwargs(icon_key, fallback)
            return _minimal_collapsible(
                parent,
                prop_name,
                title,
                icon=icon_kwargs.get('icon', 'NONE'),
                icon_value=icon_kwargs.get('icon_value', 0),
                major=False,
                boxed=True,
            )

        def _row(parent, scale=1.08, gap=True):
            if gap:
                parent.separator(factor=_preference_row_gap())
            return adaptive_row(
                parent,
                context,
                align=False,
                scale=scale,
                threshold=520.0,
            )

        def _category(prop_name, title, icon='PREFERENCES'):
            return _minimal_collapsible(
                layout,
                prop_name,
                title,
                icon=icon,
                major=True,
                boxed=False,
            )

        header_row = layout.row(align=False)
        header_row.scale_y = 1.18
        header_row.label(
            text=f"Frame By Plane {FBP_VERSION_STRING} · {FBP_RELEASE_CHANNEL_LABEL}",
            icon=fbp_icon('CHECKMARK'),
        )
        hint_row(
            layout,
            f"Target {FBP_BLENDER_VERSION_SERIES_STRING} · {FBP_SUPPORTED_PLATFORM_LABEL} · LTS {FBP_LTS_TARGET_VERSION}",
            icon='INFO',
        )
        hint_row(layout, 'Defaults affect new scenes; update the current file from the controls below.', icon='INFO')

        def _diagnostic_row(parent, operator_id, label, icon, report_name):
            row = _row(parent, scale=1.04)
            row.operator(operator_id, text=label, icon=icon)
            copy = row.operator(
                'fbp.copy_diagnostic_messages',
                text='',
                icon='COPYDOWN',
            )
            copy.report_name = report_name
            copy.full_report = True
            return row

        category = _category('pref_ui_show_workflow_category', 'Workflow', 'TOOL_SETTINGS')
        if category:
            body = _section(category, 'pref_ui_show_release', 'Onboarding', 'menu.shift_a_root', 'PRESET')
            if body:
                row = _row(body)
                row.prop(self, 'whats_new_enabled', text='Show After Updates', toggle=True, icon=fbp_icon('PRESET'))
                splash = row.operator('fbp.whats_new_prompt', text="What's New", icon=fbp_icon('PRESET'))
                splash.force = True
                splash.start_tutorial = False
                row.operator('fbp.live_tutorial', text='Tutorial', icon='QUESTION')

            body = _section(category, 'pref_ui_show_paths', 'Startup and Paths', 'settings.project_folder', 'FILE_FOLDER')
            if body:
                row = _row(body)
                row.prop(self, 'default_project_path', text='Project Folder')
                row = _row(body)
                row.prop(
                    self,
                    'default_last_directory',
                    text='Import Folder',
                    icon='FOLDER_REDIRECT',
                )
                filepaths = getattr(getattr(context, 'preferences', None), 'filepaths', None)
                if filepaths is not None and hasattr(filepaths, 'save_modified_images'):
                    row = _row(body)
                    row.prop(filepaths, 'save_modified_images', text='Modified Images')
                row = _row(body)
                row.label(text='', **_pref_icon_kwargs('menu.image_plane', 'IMAGE_DATA'))
                row.prop(self, 'default_creation_mode', text='Create Panel')
                row.prop(self, 'default_show_project_tools', text='Expand Project Import', toggle=True, icon='TOOL_SETTINGS')

            body = _section(category, 'pref_ui_show_import', 'Import Defaults', 'menu.multiplane', 'IMAGE_DATA')
            if body:
                row = _row(body)
                row.prop(self, 'default_orientation', text='Orientation', icon=fbp_icon('AXIS_FRONT'))
                row.prop(self, 'default_interpolation', text='Filtering')
                row = _row(body)
                row.prop(self, 'default_emission', text='Emission', toggle=True, icon='LIGHT_SUN')
                row.prop(self, 'default_import_crop_alpha', text='Crop Alpha', toggle=True, icon='IMAGE_ALPHA')
                pad = row.row(align=False)
                pad.enabled = bool(self.default_import_crop_alpha)
                pad.prop(self, 'default_import_crop_alpha_padding', text='Padding', slider=True)
                row = _row(body)
                row.prop(self, 'default_layer_offset', text='Layer Spacing', slider=True)
                row.prop(self, 'default_fit_to_camera', text='Fit Camera', toggle=True, icon='FULLSCREEN_ENTER')
                row.prop(self, 'default_track_camera', text='Track Camera', toggle=True, icon='CON_CAMERASOLVER')

            body = _section(category, 'pref_ui_show_timing', 'Timing and Playback', 'settings.render_sequence', 'TIME')
            if body:
                row = _row(body)
                row.prop(self, 'default_frame_duration', text='Frames per Image', slider=True)
                row.prop(self, 'default_scene_fps', text='Scene FPS', slider=True)
                row = _row(body)
                row.prop(self, 'default_plane_start_frame_mode', text='New Plane Start', icon='TIME')
                row = _row(body)
                row.prop(self, 'default_playback', text='Animated Playback')
                row = _row(body)
                row.prop(self, 'default_scene_playback_loop_mode', text='Timeline End')
                row.prop(self, 'default_scene_allow_preroll', text='Preroll', toggle=True, icon='PREVIEW_RANGE')

            body = _section(category, 'pref_ui_show_gp_fill', 'Grease Pencil 5.2', 'menu.gp_layer', 'BRUSH_DATA')
            if body:
                row = _row(body)
                row.prop(self, 'default_gp_fill_solver', text='Solver')
                row.prop(self, 'default_gp_fill_auto_remove_guides', text='Remove Guides', toggle=True, icon='TRASH')
                gap = _row(body)
                gap.enabled = self.default_gp_fill_solver == 'DELAUNAY'
                gap.prop(self, 'default_gp_fill_gap_factor', text='Gap Detection', slider=True)
                gap.prop(self, 'default_gp_fill_internal_gaps', text='Internal Gaps', toggle=True, icon='AUTOMERGE_ON')
                draw = _row(body)
                draw.prop(self, 'default_gp_curve_type', text='Draw Curves')
                draw.prop(self, 'default_gp_curve_conversion_threshold', text='Conversion Threshold')

            body = _section(category, 'pref_ui_show_gp_scrub', 'Frame Scrub Slider', 'settings.scrub_slider', 'TIME')
            if body:
                try:
                    from .grease_pencil_scrub import is_scrub_preview_active
                    scrub_preview_active = bool(is_scrub_preview_active())
                except (ImportError, AttributeError, RuntimeError):
                    scrub_preview_active = False

                preview_box = body.box()
                configure_layout(preview_box)
                preview_box.label(text='Preview and Placement', icon='VIEW3D')
                row = _row(preview_box)
                row.operator(
                    'fbp.grease_pencil_scrub_preview',
                    text='Hide Live Preview' if scrub_preview_active else 'Show Live Preview',
                    icon='HIDE_OFF' if scrub_preview_active else 'HIDE_ON',
                    depress=scrub_preview_active,
                )
                row.prop(self, 'gp_scrub_position', text='Position')
                row = _row(preview_box)
                row.prop(self, 'gp_scrub_max_range', text='Visible Frames')
                row.prop(self, 'gp_scrub_show_info', text='Interaction Info', toggle=True)
                if self.gp_scrub_position in {'LEFT', 'RIGHT'}:
                    row.prop(self, 'gp_scrub_invert_vertical', text='Invert Vertical', toggle=True)
                hint_row(preview_box, 'The live preview updates appearance and placement; bookmark and onion interactions remain available in the persistent Scrub Bar.', icon='INFO')

                motion_box = body.box()
                configure_layout(motion_box)
                motion_box.label(text='Scrubbing and Layout', icon='MOUSE_MOVE')
                row = _row(motion_box)
                row.prop(self, 'gp_scrub_sensitivity', text='Sensitivity', slider=True)
                row.prop(self, 'gp_scrub_shift_factor', text='Shift Slowdown', slider=True)
                row.prop(self, 'gp_scrub_length_ratio', text='Length', slider=True)
                row.prop(self, 'gp_scrub_edge_offset', text='Offset')
                row = _row(body)
                row.prop(self, 'gp_scrub_mouse_magnet', text='Mouse Magnet', toggle=True)
                magnet = row.row(align=False)
                magnet.enabled = self.gp_scrub_mouse_magnet
                magnet.prop(self, 'gp_scrub_mouse_magnet_distance', text='Range')
                row = _row(body)
                row.enabled = self.gp_scrub_mouse_magnet
                row.prop(self, 'gp_scrub_mouse_magnet_strength', text='Strength', slider=True)
                row.prop(self, 'gp_scrub_mouse_magnet_smoothing', text='Smoothing', slider=True)
                row = _row(body)
                row.prop(self, 'gp_scrub_tick_scale', text='Tick Scale', slider=True)
                row.prop(self, 'gp_scrub_line_width', text='Line', slider=True)
                row.prop(self, 'gp_scrub_major_interval', text='Long Tick Every')
                row = _row(appearance_box)
                row.prop(self, 'gp_scrub_micro_tick_length', text='Frame Tick')
                row.prop(self, 'gp_scrub_major_tick_length', text='Long Tick')
                row.prop(self, 'gp_scrub_second_tick_length', text='Second Tick')
                row = _row(appearance_box)
                row.prop(self, 'gp_scrub_cursor_width', text='Cursor', slider=True)
                row.prop(self, 'gp_scrub_cursor_label_scale', text='Cursor Label', slider=True)
                row = _row(appearance_box)
                row.prop(self, 'gp_scrub_cursor_color', text='Cursor Color')
                row.prop(self, 'gp_scrub_cursor_text_color', text='Cursor Text')
                hint_row(appearance_box, f'Tap < to toggle · hold < to scrub · A bookmark · Shift+D duplicate · G move · X delete.', icon='TIME')

            body = _section(category, 'pref_ui_show_procedural', 'Procedural Planes', 'menu.color_plane', 'MATERIAL')
            if body:
                row = _row(body)
                row.label(text='', **_pref_icon_kwargs('menu.color_plane', 'MATERIAL'))
                row.prop(self, 'default_color_plane_type', text='Plane Type')
                row.prop(self, 'default_color_plane_preset', text='Color Preset')
                if self.default_color_plane_preset == 'CUSTOM':
                    row = _row(body)
                    row.prop(self, 'default_color_plane_color', text='Custom Color')
                row = _row(body)
                row.prop(self, 'default_color_plane_emission', text='Emission', toggle=True, icon='LIGHT_SUN')
                row.prop(self, 'default_gradient_reverse', text='Reverse Gradient', toggle=True, icon='ARROW_LEFTRIGHT')
                row = _row(body)
                row.label(text='', **_pref_icon_kwargs('menu.gradient_plane', 'COLOR'))
                row.prop(self, 'default_gradient_mode', text='Gradient Shape')
                row.prop(self, 'default_gradient_kind', text='Alpha Mode')
                row = _row(body)
                row.prop(self, 'default_gradient_color_a', text='Color A')
                row.prop(self, 'default_gradient_color_b', text='Color B')
                row = _row(body)
                row.prop(self, 'default_gradient_offset_x', text='Offset X', slider=True)
                row.prop(self, 'default_gradient_offset_y', text='Offset Y', slider=True)
                row = _row(body)
                row.prop(self, 'default_gradient_scale_x', text='Scale X', slider=True)
                row.prop(self, 'default_gradient_scale_y', text='Scale Y', slider=True)
                row.prop(self, 'default_gradient_rotation', text='Rotation', slider=True)

        category = _category('pref_ui_show_interface_category', 'Interface', 'PREFERENCES')
        if category:
            body = _section(category, 'pref_ui_show_interface', 'Interface Behavior', 'settings.display', 'PREFERENCES')
            if body:
                row = _row(body)
                row.prop(self, 'default_preview_mode', text='List Previews')
                row = _row(body)
                row.prop(self, 'default_layer_order', text='Layer Order')
                row = _row(body)
                row.label(text='Shift+A Frame By Plane', icon='ADD')
                row.prop(self, 'shift_a_menu_position', text='', expand=True)
                hint_row(body, 'Panels use a Comfortable responsive layout; Preferences use Extra Airy spacing.', icon='INFO')

            body = _section(category, 'pref_ui_show_shortcuts', 'Shortcuts', 'settings.shortcuts', 'PREFERENCES')
            if body:
                row = _row(body)
                row.prop(self, 'shortcut_viewport_pie', text='Z · Viewport Pie', toggle=True, icon='SHADING_RENDERED')
                row.prop(self, 'shortcut_tab_layer_edit', text='Tab · Layer Edit', toggle=True, icon='EDITMODE_HLT')
                if self.shortcut_viewport_pie:
                    hint_row(
                        body,
                        'All Z Pie controls use Blender native buttons and gesture handling.',
                        icon='INFO',
                    )
                    pie_box = body.box()
                    section_header(pie_box, 'Z Pie Layout', icon='SHADING_RENDERED')
                    row = _row(pie_box)
                    row.prop(self, 'pie_north_content', text='North')
                    row = _row(pie_box)
                    row.prop(self, 'pie_show_south_actions', text='South', toggle=True, icon='TRIA_DOWN')
                    row.prop(self, 'pie_show_masks', text='Masks', toggle=True, icon='MOD_MASK')
                    row.prop(self, 'pie_show_effects', text='Effects', toggle=True, icon='SHADERFX')
                    slots = pie_box.column(align=True)
                    slots.label(text='Effect Slots', icon='COLLAPSEMENU')
                    for index in range(1, 6):
                        slots.menu(
                            f'FBP_MT_quick_effect_slot_{index}',
                            text=f'Slot {index}',
                            icon='SHADERFX',
                        )
                row = _row(body)
                row.prop(self, 'shortcut_duplicate_layer', text='Shift+D · Duplicate', toggle=True, icon='DUPLICATE')
                row.prop(self, 'shortcut_group_layers', text=f"{primary_shortcut_label('G')} · Collection", toggle=True, icon='OUTLINER_COLLECTION')
                row = _row(body)
                row.prop(self, 'shortcut_gp_alt_s_guard', text=f"{alt_shortcut_label('S')} · GP Radius", toggle=True, icon='OUTLINER_OB_GREASEPENCIL')
                row = _row(body)
                row.prop(self, 'shortcut_gp_frame_scrub', text='< · GP Frame Scrub', toggle=True, icon='TIME')
                try:
                    import rna_keymap_ui
                    keyconfig = context.window_manager.keyconfigs.addon
                    for keymap in tuple(getattr(keyconfig, 'keymaps', ()) or ()):
                        for keymap_item in tuple(getattr(keymap, 'keymap_items', ()) or ()):
                            if str(getattr(keymap_item, 'idname', '') or '').startswith('fbp.'):
                                rna_keymap_ui.draw_kmi([], keyconfig, keymap, keymap_item, body, 0)
                except (ImportError, AttributeError, RuntimeError, ReferenceError):
                    pass
                hint_row(body, 'Bindings edited here are the same Keymap items shown in Blender Preferences > Keymap.', icon='INFO')

            body = _section(category, 'pref_ui_show_layers', 'Control Panel Position', 'settings.display', 'PROPERTIES')
            if body:
                # Two explicit icon+text toggle buttons are clearer than a four-state
                # enum and allow both locations to be independently enabled/disabled.
                placement = body.row(align=False)
                placement.scale_y = 1.18
                placement.prop(
                    self,
                    'show_control_panel_properties',
                    text='Properties',
                    toggle=True,
                    icon=fbp_icon('PROPERTIES'),
                )
                placement.prop(
                    self,
                    'show_control_panel_n_panel',
                    text='N-Panel / Side Panel',
                    toggle=True,
                    icon=fbp_icon('MENU_PANEL'),
                )

                controls = body.column(align=False)
                any_location = bool(self.show_control_panel_properties or self.show_control_panel_n_panel)
                controls.enabled = any_location
                header_row = controls.row(align=False)
                header_row.label(text='Visible Control Panels', icon=fbp_icon('PROPERTIES'))
                row = _row(controls)
                row.prop(self, 'show_panel_layers', text='Layers', toggle=True, icon='RENDERLAYERS')
                row.prop(self, 'show_panel_grease_pencil', text='Grease Pencil', toggle=True, icon='OUTLINER_OB_GREASEPENCIL')
                row.prop(self, 'show_panel_layer_settings', text='Layer Settings', toggle=True, icon='TOOL_SETTINGS')
                if not any_location:
                    hint_row(body, 'Both control-panel locations are disabled. Shift+A, Modifiers, Output and Camera tools remain available.', icon='HIDE_ON')
                else:
                    hint_row(body, 'Properties = Tool tab. N-Panel = dedicated Frame By Plane tab.', icon='INFO')

            body = _section(category, 'pref_ui_show_list_icons', 'List Controls and Icons', 'settings.display', 'PREFERENCES')
            if body:
                row = adaptive_row(body, context, align=False, scale=1.08, threshold=720.0)
                row.prop(self, 'uilist_icon_preset', text='', expand=True)
                alignment = body.row(align=True)
                alignment.prop(
                    self,
                    'uilist_label_alignment',
                    text='Name',
                    expand=True,
                )
                if self.uilist_icon_preset == 'CUSTOM':
                    hint_row(
                        body,
                        'Each list owns its row layout. Toggle icons above and drag the real preview across the name to change sides.',
                        icon='ARROW_LEFTRIGHT',
                    )
                else:
                    hint_row(body, 'Choose Custom or edit any list below to move and hide individual row items.', icon='INFO')

                from .interface_preferences import (
                    UILIST_PROFILES,
                    fbp_draw_uilist_profile_preview,
                )
                for profile_id, profile in UILIST_PROFILES.items():
                    panel_id = f"fbp_preferences_uilist_{profile_id.lower()}"
                    try:
                        profile_header, profile_body = body.panel(panel_id, default_closed=True)
                    except (AttributeError, RuntimeError, TypeError, ValueError):
                        profile_header = body.row(align=False)
                        profile_body = body.column(align=False)
                    profile_header.label(
                        text=str(profile.get('label', profile_id.title())),
                        icon=str(profile.get('icon', 'PRESET')),
                    )
                    edit = profile_header.operator(
                        'fbp.uilist_columns_popup', text='', icon='THREE_DOTS'
                    )
                    edit.profile = profile_id
                    if profile_body is not None:
                        fbp_draw_uilist_profile_preview(
                            profile_body, context, profile_id, draggable=True
                        )
                        action = profile_body.operator(
                            'fbp.uilist_columns_popup',
                            text='Edit Columns',
                            icon='PREFERENCES',
                        )
                        action.profile = profile_id

            body = _section(category, 'pref_ui_show_expanded', 'Expanded Sections', 'settings.display', 'PREFERENCES')
            if body:
                row = _row(body)
                row.prop(self, 'default_color_variants', text='Collection Color Variants', toggle=True, icon='OUTLINER_COLLECTION')
                row.prop(self, 'default_show_project_tools', text='Expand Project Import', toggle=True, icon='TOOL_SETTINGS')
                row = _row(body)
                row.prop(self, 'default_show_gradient_ramp', text='Expand Color Ramp', toggle=True, icon='COLOR')
                row.prop(self, 'default_show_gradient_transform', text='Expand Gradient Transform', toggle=True, icon='EMPTY_ARROWS')

        category = _category('pref_ui_show_camera_render_category', 'Camera & Render', 'CAMERA_DATA')
        if category:
            body = _section(category, 'pref_ui_show_camera', 'Camera Defaults', 'settings.camera_tab', 'CAMERA_DATA')
            if body:
                row = _row(body)
                row.prop(self, 'default_generate_camera', text='Create Camera', toggle=True, icon='CAMERA_DATA')
                row.prop(self, 'default_camera_fit_source_aspect', text='Use Source Aspect', toggle=True, icon='IMAGE_DATA')
                row.prop(self, 'default_camera_pivot', text='Cursor on Camera', toggle=True, icon='PIVOT_CURSOR')
                row = _row(body)
                row.prop(self, 'default_camera_projection', text='Projection', icon=ui_icon('settings.projection'))
                if self.default_camera_projection == 'ORTHO':
                    row.prop(self, 'default_camera_ortho_scale', text='Ortho Scale', slider=True)
                else:
                    row.prop(self, 'default_camera_lens', text='Lens', slider=True)
                row = _row(body)
                row.prop(self, 'default_camera_ratio', text='Output Aspect', icon=ui_icon('settings.camera_frame'))
                if self.default_camera_ratio == 'CUSTOM':
                    row.prop(self, 'default_resolution_x', text='Width', slider=True)
                    row.prop(self, 'default_resolution_y', text='Height', slider=True)
                row = _row(body)
                row.prop(self, 'default_camera_clip_start', text='Clip Start', slider=True)
                row.prop(self, 'default_camera_clip_end', text='Clip End', slider=True)

            body = _section(category, 'pref_ui_show_render', 'Render Defaults', 'settings.render_tab', 'RENDER_ANIMATION')
            if body:
                row = _row(body)
                row.prop(self, 'default_alpha_render_method', text='Alpha Rendering', icon='IMAGE_ALPHA')
                row.prop(self, 'default_render_folder_mode', text='Destination')
                row = _row(body)
                row.prop(self, 'default_render_name_source', text='Base Name')
                row.prop(self, 'default_render_prefix', text='Prefix', icon=ui_icon('layer.sort_alpha'))
                row = _row(body)
                row.prop(self, 'default_render_separator', text='Separator')
                row.prop(self, 'default_render_frame_digits', text='Frame Digits')
                row.prop(self, 'default_render_auto_increment_test', text='New TEST per Render', toggle=True, icon='FILE_REFRESH')
                row = _row(body)
                row.label(text='', icon=ui_icon('settings.output'))
                row.prop(self, 'default_render_output_dir', text='Render Folder')
                row = _row(body)
                row.prop(self, 'default_anisotropic_filter', text='Anisotropic Filtering')
                row = _row(body)
                row.prop(self, 'default_cycles_texture_cache', text='Cycles Texture Cache', toggle=True, icon='TEXTURE')
                auto = row.row(align=False)
                auto.enabled = bool(self.default_cycles_texture_cache)
                auto.prop(self, 'default_cycles_auto_texture_cache', text='Auto Generate', toggle=True, icon='FILE_REFRESH')

        # File actions remain visible before the optional Advanced tools.
        section_gap(layout, _preference_section_gap())
        footer = layout.row(align=False)
        footer.scale_y = 1.12
        footer.operator('fbp.apply_preferences_to_scene', text='Update Current File', icon=fbp_icon('CHECKMARK'))
        footer.operator('fbp.save_file', text='Save .blend', icon=fbp_icon('FILE_TICK'))

        category = _category('pref_ui_show_advanced_category', 'Advanced', 'MODIFIER')
        if category:
            body = _section(category, 'pref_ui_show_preview_features', 'LTS Feature Scope', 'settings.health', 'CHECKMARK')
            if body:
                scope = body.row(align=False)
                scope.label(text=f'Core target: {FBP_LTS_TARGET_VERSION}', icon='CHECKMARK')
                scope.label(text='Preview features are excluded from the LTS promise', icon='INFO')
                row = _row(body)
                row.prop(self, 'default_preview_compositor', text='Compositor', toggle=True, icon='NODE_COMPOSITING')
                row.prop(self, 'default_preview_procreate_import', text='Procreate', toggle=True, icon='BRUSH_DATA')
                row.prop(self, 'default_preview_generic_mesh_effects', text='Generic Mesh', toggle=True, icon='MESH_DATA')
                scene = getattr(context, 'scene', None)
                if scene is not None:
                    current = body.box()
                    configure_layout(current)
                    current.label(text='Current File', icon='FILE_BLEND')
                    row = _row(current)
                    row.prop(scene, 'fbp_experimental_compositor', text='Compositor', toggle=True, icon='NODE_COMPOSITING')
                    row.prop(scene, 'fbp_preview_procreate_import', text='Procreate', toggle=True, icon='BRUSH_DATA')
                    row.prop(scene, 'fbp_preview_generic_mesh_effects', text='Generic Mesh', toggle=True, icon='MESH_DATA')
                    hint_row(current, 'Project Doctor reports every enabled Preview feature.', icon='INFO')

            body = _section(category, 'pref_ui_show_performance', 'Performance and Safety', 'settings.repair', 'MODIFIER')
            if body:
                row = _row(body)
                row.prop(
                    self,
                    'default_auto_clean_orphans',
                    text='Clean Orphaned Runtime Data',
                    toggle=True,
                    icon='MODIFIER',
                )
                filepaths = getattr(getattr(context, 'preferences', None), 'filepaths', None)
                if filepaths is not None and hasattr(filepaths, 'texture_cache_directory'):
                    row = _row(body)
                    row.prop(filepaths, 'texture_cache_directory', text='Cycles Texture Cache')

            body = _section(category, 'pref_ui_show_diagnostics', 'Diagnostics and Repair', 'settings.repair', 'MODIFIER')
            if body:
                # One diagnostic per row, with a dedicated icon-only report copy.
                _diagnostic_row(body, 'fbp.project_health_check', 'Project Doctor', ui_icon('settings.health'), 'FBP_Project_Health')
                _diagnostic_row(body, 'fbp.run_persistence_audit', 'Persistence Audit', 'FILE_TICK', 'FBP_Persistence_Audit')

                section_gap(body, 0.45)
                maintenance = adaptive_row(body, context, align=False, scale=1.02, threshold=620.0)
                maintenance.alert = True
                maintenance.operator('fbp.relink_from_project_root', icon=ui_icon('settings.relink'), text='Relink Files')
                maintenance.operator('fbp.select_missing_layers', icon=ui_icon('generic.error'), text='Select Missing')

            body = _section(category, 'pref_ui_show_links', 'Updates and Support', 'menu.video_plane', 'MESH_MONKEY')
            if body:
                row = _row(body)
                op = row.operator('fbp.whats_new_prompt', text="What's New", icon=fbp_icon('PRESET'))
                op.force = True
                op.start_tutorial = False
                row.operator('fbp.open_review_page', text='Leave a Review', icon=fbp_icon('SOLO_ON'))
                row.operator('fbp.open_support_page', text='Report a Bug', icon=fbp_icon('GHOST_DISABLED'))

def _initialize_scene_preferences_after_register():
    """Apply preference defaults only after Blender exposes a stable Main.

    ``register()`` can run while ``bpy.data`` is an internal ``_RestrictData``
    proxy. Returning a retry interval lets the safe-task scheduler wait without
    losing startup initialization or raising during extension enable. Retries
    are bounded so a broken Preferences context cannot leave a permanent timer.
    """
    global _preferences_init_attempts
    try:
        data = bpy.data
        scenes = tuple(getattr(data, "scenes"))
        is_saved = bool(getattr(data, "is_saved"))
        context = bpy.context
    except FBP_DATA_ERRORS:
        _preferences_init_attempts += 1
        return 0.10 if _preferences_init_attempts < _PREFERENCES_INIT_RETRY_LIMIT else None

    prefs = fbp_get_addon_preferences(context)
    if prefs is None:
        _preferences_init_attempts += 1
        return 0.10 if _preferences_init_attempts < _PREFERENCES_INIT_RETRY_LIMIT else None

    if bool(getattr(prefs, 'show_control_panel_properties', True)):
        update_interface_preferences_cb(prefs, context)

    if is_saved:
        _preferences_init_attempts = 0
        fbp_mark_scenes_preferences_initialized(scenes)
        return None

    _preferences_init_attempts = 0
    active_scene = getattr(context, "scene", None)
    if active_scene is not None:
        fbp_apply_preferences_to_scene(active_scene, force=False, context=context)
    for scene in scenes:
        if scene == active_scene:
            continue
        fbp_mark_scenes_preferences_initialized((scene,))
    return None


def update_color_plane_color_cb(self, context):
    return _call_core('update_color_plane_color_cb', self, context)

def update_color_plane_preset_cb(self, context):
    return _call_core('update_color_plane_preset_cb', self, context)

def update_color_tag_cb(self, context):
    result = _call_core('update_color_tag_cb', self, context)
    try:
        from .compositor import fbp_schedule_compositor_update
        fbp_schedule_compositor_update(getattr(context, "scene", None))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return result

def update_rig_shape_cb(self, context):
    try:
        from .builder import fbp_apply_rig_shape
        fbp_apply_rig_shape(self, getattr(self, "fbp_rig_shape", "DEFAULT"))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not update Frame By Plane rig shape", exc)
    return None

def update_emission_cb(self, context):
    return _call_core('update_emission_cb', self, context)

def update_global_duration_cb(self, context):
    return _call_core('update_global_duration_cb', self, context)

def update_image_duration_cb(self, context):
    return _call_core('update_image_duration_cb', self, context)

def update_gradient_mapping_cb(self, context):
    return _call_core('update_gradient_mapping_cb', self, context)


def update_gradient_controller_cb(self, context):
    try:
        from .materials import fbp_bind_gradient_controller_drivers
        fbp_bind_gradient_controller_drivers(
            self, getattr(self, "fbp_gradient_controller", None)
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not update the Gradient controller", exc)
    return None

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
    # Layer mute belongs to the Layer Tree backend. Routing this through core
    # left the UI boolean changed without applying layer visibility.
    return _call_layers('update_mute_cb', self, context)

def _call_geometry_nodes(name, *args, default=None):
    owner = args[0] if args else None
    if fbp_undo_guard_active() or (owner is not None and fbp_is_silent_property_update(owner)):
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


_FBP_VIEW_RENDER_PROPERTY_PAIRS = {
    "fbp_mesh_wiggle_subdivisions": "fbp_mesh_wiggle_render_subdivisions",
    "fbp_stop_motion_resolution": "fbp_stop_motion_render_resolution",
    "fbp_cutout_outline_viewport_resolution": "fbp_cutout_outline_render_resolution",
    "fbp_wind_subdivision": "fbp_wind_render_subdivision",
    "fbp_image_relief_subdivision": "fbp_image_relief_render_subdivision",
    "fbp_glass_subdivision": "fbp_glass_render_subdivision",
    "fbp_crystal_subdivision": "fbp_crystal_render_subdivision",
    "fbp_surface_conform_subdivision": "fbp_surface_conform_render_subdivision",
    "fbp_accordion_subdivision": "fbp_accordion_render_subdivision",
    "fbp_sculpt_waves_subdivision": "fbp_sculpt_waves_render_subdivision",
    "fbp_kinetic_tiles_subdivision": "fbp_kinetic_tiles_render_subdivision",
    "fbp_layered_echo_layers": "fbp_layered_echo_render_layers",
    "fbp_thickness_viewport_pixels_x": "fbp_thickness_render_pixels_x",
    "fbp_thickness_viewport_pixels_y": "fbp_thickness_render_pixels_y",
    "fbp_text_matrix_viewport_columns": "fbp_text_matrix_render_columns",
    "fbp_text_matrix_viewport_rows": "fbp_text_matrix_render_rows",
    "fbp_sphere_screen_viewport_columns": "fbp_sphere_screen_render_columns",
    "fbp_sphere_screen_viewport_rows": "fbp_sphere_screen_render_rows",
}


def _fbp_raise_render_quality_from_view(owner, prop_name):
    """Keep final-render quality at least as high as an increased View value."""
    render_prop = _FBP_VIEW_RENDER_PROPERTY_PAIRS.get(str(prop_name or ""))
    if not render_prop or not hasattr(owner, render_prop):
        return False
    try:
        view_value = getattr(owner, prop_name)
        render_value = getattr(owner, render_prop)
        if view_value <= render_value:
            return False
        fbp_set_rna_property_silent(owner, render_prop, view_value)
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _fbp_active_effect_instance_for_update(owner, effect_id):
    """Return an instance id only for effects with a real per-instance backend.

    Every concrete stack row has a persistent ``instance_id``, including
    SINGLE and Geometry effects. Treating that storage identity as an editable
    shader-instance channel routed all slider changes through
    ``fbp_update_effect_instance_setting_value()``, which deliberately rejects
    SINGLE and non-shader effects. The RNA value changed in the UI, but the
    generated material or modifier was therefore never updated.
    """
    effect_id = str(effect_id or "")
    if not effect_id:
        return ""
    try:
        from .effects_registry import (
            fbp_effect_definition,
            fbp_effect_multi_instance_enabled,
        )
        definition = fbp_effect_definition(effect_id)
        if (
            not fbp_effect_multi_instance_enabled(effect_id)
            or str(definition.get("kind", "") or "").upper() != "SHADER"
        ):
            return ""
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return ""
    try:
        index = int(getattr(owner, "fbp_effects_index", 0) or 0)
        items = getattr(owner, "fbp_effects", ())
        if 0 <= index < len(items):
            item = items[index]
            if (
                str(getattr(item, "row_type", "EFFECT") or "EFFECT") == "EFFECT"
                and str(getattr(item, "effect_id", "") or "") == effect_id
            ):
                return str(getattr(item, "instance_id", "") or "")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, IndexError):
        pass
    return ""


def _queue_effect_setting_update(self, context, effect_id, prop_name):
    """Queue one user edit without leaking silent/Undo restoration callbacks.

    Blender invokes RNA update callbacks while Undo/Redo restores Object data and
    while Frame By Plane performs guarded internal writes. Queuing those callbacks
    for a later timer replays a transient state after the history operation has
    completed, which can remove or rebuild a newly restored effect or mask.
    """
    if fbp_undo_guard_active() or fbp_is_silent_property_update(self):
        return None
    # RNA supplies a live UI context for user edits. Deferred/internal writes
    # use ``None`` or the silent guard and therefore never force viewport mode.
    if context is not None:
        fbp_ensure_effect_preview_mode(context, effect_id)
    _fbp_raise_render_quality_from_view(self, prop_name)
    instance_id = _fbp_active_effect_instance_for_update(self, effect_id)
    try:
        from .fbp_dirty import mark_effect_setting
        if mark_effect_setting(
            self, effect_id, prop_name, context=context,
            controls=not bool(instance_id), instance_id=instance_id,
        ):
            return None
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    _call_geometry_nodes(
        'update_effect_setting_cb', self, context, effect_id, prop_name, instance_id
    )
    if not instance_id:
        try:
            from .effect_controls import schedule_sync_controls_from_properties
            schedule_sync_controls_from_properties(self, effect_id, create=False)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    # Blender RNA update callbacks must return None. The backend's changed flag
    # is intentionally not propagated through this callback boundary.
    return None


def update_mesh_wiggle_shade_smooth_cb(self, context):
    return _queue_effect_setting_update(self, context, 'MESH_WIGGLE', 'fbp_mesh_wiggle_shade_smooth')


def update_mesh_wiggle_strength_cb(self, context):
    return _queue_effect_setting_update(self, context, 'MESH_WIGGLE', 'fbp_mesh_wiggle_strength')


def update_mesh_wiggle_speed_cb(self, context):
    return _queue_effect_setting_update(self, context, 'MESH_WIGGLE', 'fbp_mesh_wiggle_speed')


def update_mesh_wiggle_hold_cb(self, context):
    return _queue_effect_setting_update(self, context, 'MESH_WIGGLE', 'fbp_mesh_wiggle_hold')


def update_mesh_wiggle_w_cb(self, context):
    return _queue_effect_setting_update(self, context, 'MESH_WIGGLE', 'fbp_mesh_wiggle_w')


def update_mesh_wiggle_seed_cb(self, context):
    return _queue_effect_setting_update(self, context, 'MESH_WIGGLE', 'fbp_mesh_wiggle_seed')


def update_mesh_wiggle_unique_seed_cb(self, context):
    return _queue_effect_setting_update(self, context, 'MESH_WIGGLE', 'fbp_mesh_wiggle_unique_seed')


def update_mesh_wiggle_noise_scale_cb(self, context):
    return _queue_effect_setting_update(self, context, 'MESH_WIGGLE', 'fbp_mesh_wiggle_noise_scale')


def update_mesh_wiggle_detail_cb(self, context):
    return _queue_effect_setting_update(self, context, 'MESH_WIGGLE', 'fbp_mesh_wiggle_detail')


def update_mesh_wiggle_subdivisions_cb(self, context):
    return _queue_effect_setting_update(self, context, 'MESH_WIGGLE', 'fbp_mesh_wiggle_subdivisions')


def update_mesh_wiggle_playback_subdivisions_cb(self, context):
    return _queue_effect_setting_update(self, context, 'MESH_WIGGLE', 'fbp_mesh_wiggle_playback_subdivisions')


def update_mesh_wiggle_render_subdivisions_cb(self, context):
    return _queue_effect_setting_update(self, context, 'MESH_WIGGLE', 'fbp_mesh_wiggle_render_subdivisions')


def _make_effect_update_callback(effect_id, prop_name):
    """Create a small RNA update callback for a registered FBP effect property."""
    def _update(self, context):
        return _queue_effect_setting_update(self, context, effect_id, prop_name)
    return _update


update_uv_distortion_scale_cb = _make_effect_update_callback('UV_DISTORTION', 'fbp_uv_distortion_scale')
update_uv_distortion_amount_cb = _make_effect_update_callback('UV_DISTORTION', 'fbp_uv_distortion_amount')
update_uv_distortion_evolution_cb = _make_effect_update_callback('UV_DISTORTION', 'fbp_uv_distortion_evolution')
update_pixelate_resolution_cb = _make_effect_update_callback('PIXELATE', 'fbp_pixelate_resolution')
update_pixelate_height_cb = _make_effect_update_callback('PIXELATE', 'fbp_pixelate_height')
update_pixelate_grid_mode_cb = _make_effect_update_callback('PIXELATE', 'fbp_pixelate_grid_mode')
update_pixelate_size_cb = _make_effect_update_callback('PIXELATE', 'fbp_pixelate_size')
update_pixelate_stretch_cb = _make_effect_update_callback('PIXELATE', 'fbp_pixelate_stretch')
update_pixelate_rotation_cb = _make_effect_update_callback('PIXELATE', 'fbp_pixelate_rotation')
update_pixelate_offset_x_cb = _make_effect_update_callback('PIXELATE', 'fbp_pixelate_offset_x')
update_pixelate_offset_y_cb = _make_effect_update_callback('PIXELATE', 'fbp_pixelate_offset_y')
update_swirl_center_x_cb = _make_effect_update_callback('SWIRL', 'fbp_swirl_center_x')
update_swirl_center_y_cb = _make_effect_update_callback('SWIRL', 'fbp_swirl_center_y')
update_swirl_radius_cb = _make_effect_update_callback('SWIRL', 'fbp_swirl_radius')
update_swirl_angle_cb = _make_effect_update_callback('SWIRL', 'fbp_swirl_angle')
update_swirl_factor_cb = _make_effect_update_callback('SWIRL', 'fbp_swirl_factor')
update_bulge_pinch_center_x_cb = _make_effect_update_callback('BULGE_PINCH', 'fbp_bulge_pinch_center_x')
update_bulge_pinch_center_y_cb = _make_effect_update_callback('BULGE_PINCH', 'fbp_bulge_pinch_center_y')
update_bulge_pinch_radius_cb = _make_effect_update_callback('BULGE_PINCH', 'fbp_bulge_pinch_radius')
update_bulge_pinch_strength_cb = _make_effect_update_callback('BULGE_PINCH', 'fbp_bulge_pinch_strength')
update_bulge_pinch_factor_cb = _make_effect_update_callback('BULGE_PINCH', 'fbp_bulge_pinch_factor')
update_lens_warp_center_x_cb = _make_effect_update_callback('LENS_WARP', 'fbp_lens_warp_center_x')
update_lens_warp_center_y_cb = _make_effect_update_callback('LENS_WARP', 'fbp_lens_warp_center_y')
update_lens_warp_distortion_cb = _make_effect_update_callback('LENS_WARP', 'fbp_lens_warp_distortion')
update_lens_warp_zoom_cb = _make_effect_update_callback('LENS_WARP', 'fbp_lens_warp_zoom')
update_lens_warp_factor_cb = _make_effect_update_callback('LENS_WARP', 'fbp_lens_warp_factor')
update_wave_warp_amplitude_cb = _make_effect_update_callback('WAVE_WARP', 'fbp_wave_warp_amplitude')
update_wave_warp_frequency_cb = _make_effect_update_callback('WAVE_WARP', 'fbp_wave_warp_frequency')
update_wave_warp_phase_cb = _make_effect_update_callback('WAVE_WARP', 'fbp_wave_warp_phase')
update_wave_warp_angle_cb = _make_effect_update_callback('WAVE_WARP', 'fbp_wave_warp_angle')
update_wave_warp_factor_cb = _make_effect_update_callback('WAVE_WARP', 'fbp_wave_warp_factor')
update_wave_warp_speed_cb = _make_effect_update_callback('WAVE_WARP', 'fbp_wave_warp_speed')
update_ripple_distortion_center_x_cb = _make_effect_update_callback('RIPPLE_DISTORTION', 'fbp_ripple_distortion_center_x')
update_ripple_distortion_center_y_cb = _make_effect_update_callback('RIPPLE_DISTORTION', 'fbp_ripple_distortion_center_y')
update_ripple_distortion_amplitude_cb = _make_effect_update_callback('RIPPLE_DISTORTION', 'fbp_ripple_distortion_amplitude')
update_ripple_distortion_frequency_cb = _make_effect_update_callback('RIPPLE_DISTORTION', 'fbp_ripple_distortion_frequency')
update_ripple_distortion_phase_cb = _make_effect_update_callback('RIPPLE_DISTORTION', 'fbp_ripple_distortion_phase')
update_ripple_distortion_radius_cb = _make_effect_update_callback('RIPPLE_DISTORTION', 'fbp_ripple_distortion_radius')
update_ripple_distortion_falloff_cb = _make_effect_update_callback('RIPPLE_DISTORTION', 'fbp_ripple_distortion_falloff')
update_ripple_distortion_factor_cb = _make_effect_update_callback('RIPPLE_DISTORTION', 'fbp_ripple_distortion_factor')
update_ripple_distortion_speed_cb = _make_effect_update_callback('RIPPLE_DISTORTION', 'fbp_ripple_distortion_speed')
update_kaleidoscope_center_x_cb = _make_effect_update_callback('KALEIDOSCOPE', 'fbp_kaleidoscope_center_x')
update_kaleidoscope_center_y_cb = _make_effect_update_callback('KALEIDOSCOPE', 'fbp_kaleidoscope_center_y')
update_kaleidoscope_segments_cb = _make_effect_update_callback('KALEIDOSCOPE', 'fbp_kaleidoscope_segments')
update_kaleidoscope_rotation_cb = _make_effect_update_callback('KALEIDOSCOPE', 'fbp_kaleidoscope_rotation')
update_kaleidoscope_factor_cb = _make_effect_update_callback('KALEIDOSCOPE', 'fbp_kaleidoscope_factor')
update_hex_pixelate_cells_x_cb = _make_effect_update_callback('HEX_PIXELATE', 'fbp_hex_pixelate_cells_x')
update_hex_pixelate_cells_y_cb = _make_effect_update_callback('HEX_PIXELATE', 'fbp_hex_pixelate_cells_y')
update_hex_pixelate_rotation_cb = _make_effect_update_callback('HEX_PIXELATE', 'fbp_hex_pixelate_rotation')
update_hex_pixelate_factor_cb = _make_effect_update_callback('HEX_PIXELATE', 'fbp_hex_pixelate_factor')
update_mosaic_jitter_cells_x_cb = _make_effect_update_callback('MOSAIC_JITTER', 'fbp_mosaic_jitter_cells_x')
update_mosaic_jitter_cells_y_cb = _make_effect_update_callback('MOSAIC_JITTER', 'fbp_mosaic_jitter_cells_y')
update_mosaic_jitter_rotation_cb = _make_effect_update_callback('MOSAIC_JITTER', 'fbp_mosaic_jitter_rotation')
update_mosaic_jitter_amount_cb = _make_effect_update_callback('MOSAIC_JITTER', 'fbp_mosaic_jitter_amount')
update_mosaic_jitter_offset_x_cb = _make_effect_update_callback('MOSAIC_JITTER', 'fbp_mosaic_jitter_offset_x')
update_mosaic_jitter_offset_y_cb = _make_effect_update_callback('MOSAIC_JITTER', 'fbp_mosaic_jitter_offset_y')
update_mosaic_jitter_seed_cb = _make_effect_update_callback('MOSAIC_JITTER', 'fbp_mosaic_jitter_seed')
update_mosaic_jitter_factor_cb = _make_effect_update_callback('MOSAIC_JITTER', 'fbp_mosaic_jitter_factor')
update_slice_shift_angle_cb = _make_effect_update_callback('SLICE_SHIFT', 'fbp_slice_shift_angle')
update_slice_shift_bands_cb = _make_effect_update_callback('SLICE_SHIFT', 'fbp_slice_shift_bands')
update_slice_shift_shift_cb = _make_effect_update_callback('SLICE_SHIFT', 'fbp_slice_shift_shift')
update_slice_shift_random_cb = _make_effect_update_callback('SLICE_SHIFT', 'fbp_slice_shift_random')
update_slice_shift_seed_cb = _make_effect_update_callback('SLICE_SHIFT', 'fbp_slice_shift_seed')
update_slice_shift_factor_cb = _make_effect_update_callback('SLICE_SHIFT', 'fbp_slice_shift_factor')
update_depth_blur_mode_cb = _make_effect_update_callback('DEPTH_BLUR', 'fbp_depth_blur_mode')
update_depth_blur_manual_radius_cb = _make_effect_update_callback('DEPTH_BLUR', 'fbp_depth_blur_manual_radius')
update_depth_blur_max_radius_cb = _make_effect_update_callback('DEPTH_BLUR', 'fbp_depth_blur_max_radius')
update_depth_blur_use_camera_focus_cb = _make_effect_update_callback('DEPTH_BLUR', 'fbp_depth_blur_use_camera_focus')
update_depth_blur_focus_distance_cb = _make_effect_update_callback('DEPTH_BLUR', 'fbp_depth_blur_focus_distance')
update_depth_blur_focus_range_cb = _make_effect_update_callback('DEPTH_BLUR', 'fbp_depth_blur_focus_range')
update_depth_blur_falloff_cb = _make_effect_update_callback('DEPTH_BLUR', 'fbp_depth_blur_falloff')
update_depth_blur_near_strength_cb = _make_effect_update_callback('DEPTH_BLUR', 'fbp_depth_blur_near_strength')
update_depth_blur_far_strength_cb = _make_effect_update_callback('DEPTH_BLUR', 'fbp_depth_blur_far_strength')
update_gaussian_blur_radius_x_cb = _make_effect_update_callback('GAUSSIAN_BLUR', 'fbp_gaussian_blur_radius_x')
update_gaussian_blur_radius_y_cb = _make_effect_update_callback('GAUSSIAN_BLUR', 'fbp_gaussian_blur_radius_y')
update_gaussian_blur_samples_cb = _make_effect_update_callback('GAUSSIAN_BLUR', 'fbp_gaussian_blur_samples')
update_gaussian_blur_factor_cb = _make_effect_update_callback('GAUSSIAN_BLUR', 'fbp_gaussian_blur_factor')
update_directional_blur_angle_cb = _make_effect_update_callback('DIRECTIONAL_BLUR', 'fbp_directional_blur_angle')
update_directional_blur_distance_cb = _make_effect_update_callback('DIRECTIONAL_BLUR', 'fbp_directional_blur_distance')
update_directional_blur_samples_cb = _make_effect_update_callback('DIRECTIONAL_BLUR', 'fbp_directional_blur_samples')
update_directional_blur_factor_cb = _make_effect_update_callback('DIRECTIONAL_BLUR', 'fbp_directional_blur_factor')
update_triangle_blur_radius_cb = _make_effect_update_callback('TRIANGLE_BLUR', 'fbp_triangle_blur_radius')
update_triangle_blur_samples_cb = _make_effect_update_callback('TRIANGLE_BLUR', 'fbp_triangle_blur_samples')
update_triangle_blur_factor_cb = _make_effect_update_callback('TRIANGLE_BLUR', 'fbp_triangle_blur_factor')
update_tilt_shift_position_cb = _make_effect_update_callback('TILT_SHIFT', 'fbp_tilt_shift_position')
update_tilt_shift_width_cb = _make_effect_update_callback('TILT_SHIFT', 'fbp_tilt_shift_width')
update_tilt_shift_angle_cb = _make_effect_update_callback('TILT_SHIFT', 'fbp_tilt_shift_angle')
update_tilt_shift_radius_cb = _make_effect_update_callback('TILT_SHIFT', 'fbp_tilt_shift_radius')
update_tilt_shift_factor_cb = _make_effect_update_callback('TILT_SHIFT', 'fbp_tilt_shift_factor')
update_unsharp_radius_cb = _make_effect_update_callback('UNSHARP_MASK', 'fbp_unsharp_radius')
update_unsharp_amount_cb = _make_effect_update_callback('UNSHARP_MASK', 'fbp_unsharp_amount')
update_unsharp_factor_cb = _make_effect_update_callback('UNSHARP_MASK', 'fbp_unsharp_factor')
update_edge_detect_width_cb = _make_effect_update_callback('EDGE_DETECT', 'fbp_edge_detect_width')
update_edge_detect_strength_cb = _make_effect_update_callback('EDGE_DETECT', 'fbp_edge_detect_strength')
update_edge_detect_threshold_cb = _make_effect_update_callback('EDGE_DETECT', 'fbp_edge_detect_threshold')
update_edge_detect_softness_cb = _make_effect_update_callback('EDGE_DETECT', 'fbp_edge_detect_softness')
update_edge_detect_color_cb = _make_effect_update_callback('EDGE_DETECT', 'fbp_edge_detect_color')
update_edge_detect_factor_cb = _make_effect_update_callback('EDGE_DETECT', 'fbp_edge_detect_factor')
update_smooth_toon_levels_cb = _make_effect_update_callback('SMOOTH_TOON', 'fbp_smooth_toon_levels')
update_smooth_toon_softness_cb = _make_effect_update_callback('SMOOTH_TOON', 'fbp_smooth_toon_softness')
update_smooth_toon_factor_cb = _make_effect_update_callback('SMOOTH_TOON', 'fbp_smooth_toon_factor')
update_adaptive_threshold_radius_cb = _make_effect_update_callback('ADAPTIVE_THRESHOLD', 'fbp_adaptive_threshold_radius')
update_adaptive_threshold_offset_cb = _make_effect_update_callback('ADAPTIVE_THRESHOLD', 'fbp_adaptive_threshold_offset')
update_adaptive_threshold_softness_cb = _make_effect_update_callback('ADAPTIVE_THRESHOLD', 'fbp_adaptive_threshold_softness')
update_adaptive_threshold_invert_cb = _make_effect_update_callback('ADAPTIVE_THRESHOLD', 'fbp_adaptive_threshold_invert')
update_adaptive_threshold_factor_cb = _make_effect_update_callback('ADAPTIVE_THRESHOLD', 'fbp_adaptive_threshold_factor')
update_false_color_dark_cb = _make_effect_update_callback('FALSE_COLOR', 'fbp_false_color_dark')
update_false_color_light_cb = _make_effect_update_callback('FALSE_COLOR', 'fbp_false_color_light')
update_false_color_factor_cb = _make_effect_update_callback('FALSE_COLOR', 'fbp_false_color_factor')
update_chromatic_aberration_distance_cb = _make_effect_update_callback('CHROMATIC_ABERRATION', 'fbp_chromatic_aberration_distance')
update_chromatic_aberration_angle_cb = _make_effect_update_callback('CHROMATIC_ABERRATION', 'fbp_chromatic_aberration_angle')
update_chromatic_aberration_factor_cb = _make_effect_update_callback('CHROMATIC_ABERRATION', 'fbp_chromatic_aberration_factor')
update_ink_width_cb = _make_effect_update_callback('INK', 'fbp_ink_width')
update_ink_threshold_cb = _make_effect_update_callback('INK', 'fbp_ink_threshold')
update_ink_softness_cb = _make_effect_update_callback('INK', 'fbp_ink_softness')
update_ink_strength_cb = _make_effect_update_callback('INK', 'fbp_ink_strength')
update_ink_color_cb = _make_effect_update_callback('INK', 'fbp_ink_color')
update_ink_paper_color_cb = _make_effect_update_callback('INK', 'fbp_ink_paper_color')
update_ink_preserve_color_cb = _make_effect_update_callback('INK', 'fbp_ink_preserve_color')
update_ink_factor_cb = _make_effect_update_callback('INK', 'fbp_ink_factor')
update_edge_work_radius_cb = _make_effect_update_callback('EDGE_WORK', 'fbp_edge_work_radius')
update_edge_work_thickness_cb = _make_effect_update_callback('EDGE_WORK', 'fbp_edge_work_thickness')
update_edge_work_strength_cb = _make_effect_update_callback('EDGE_WORK', 'fbp_edge_work_strength')
update_edge_work_threshold_cb = _make_effect_update_callback('EDGE_WORK', 'fbp_edge_work_threshold')
update_edge_work_softness_cb = _make_effect_update_callback('EDGE_WORK', 'fbp_edge_work_softness')
update_edge_work_color_cb = _make_effect_update_callback('EDGE_WORK', 'fbp_edge_work_color')
update_edge_work_factor_cb = _make_effect_update_callback('EDGE_WORK', 'fbp_edge_work_factor')
update_pencil_sketch_radius_cb = _make_effect_update_callback('PENCIL_SKETCH', 'fbp_pencil_sketch_radius')
update_pencil_sketch_contrast_cb = _make_effect_update_callback('PENCIL_SKETCH', 'fbp_pencil_sketch_contrast')
update_pencil_sketch_graphite_cb = _make_effect_update_callback('PENCIL_SKETCH', 'fbp_pencil_sketch_graphite')
update_pencil_sketch_paper_cb = _make_effect_update_callback('PENCIL_SKETCH', 'fbp_pencil_sketch_paper')
update_pencil_sketch_color_amount_cb = _make_effect_update_callback('PENCIL_SKETCH', 'fbp_pencil_sketch_color_amount')
update_pencil_sketch_factor_cb = _make_effect_update_callback('PENCIL_SKETCH', 'fbp_pencil_sketch_factor')
update_poster_edges_levels_cb = _make_effect_update_callback('POSTER_EDGES', 'fbp_poster_edges_levels')
update_poster_edges_softness_cb = _make_effect_update_callback('POSTER_EDGES', 'fbp_poster_edges_softness')
update_poster_edges_width_cb = _make_effect_update_callback('POSTER_EDGES', 'fbp_poster_edges_width')
update_poster_edges_strength_cb = _make_effect_update_callback('POSTER_EDGES', 'fbp_poster_edges_strength')
update_poster_edges_threshold_cb = _make_effect_update_callback('POSTER_EDGES', 'fbp_poster_edges_threshold')
update_poster_edges_color_cb = _make_effect_update_callback('POSTER_EDGES', 'fbp_poster_edges_color')
update_poster_edges_factor_cb = _make_effect_update_callback('POSTER_EDGES', 'fbp_poster_edges_factor')
update_crosshatch_scale_cb = _make_effect_update_callback('CROSSHATCH', 'fbp_crosshatch_scale')
update_crosshatch_rotation_cb = _make_effect_update_callback('CROSSHATCH', 'fbp_crosshatch_rotation')
update_crosshatch_line_width_cb = _make_effect_update_callback('CROSSHATCH', 'fbp_crosshatch_line_width')
update_crosshatch_levels_cb = _make_effect_update_callback('CROSSHATCH', 'fbp_crosshatch_levels')
update_crosshatch_ink_cb = _make_effect_update_callback('CROSSHATCH', 'fbp_crosshatch_ink')
update_crosshatch_paper_cb = _make_effect_update_callback('CROSSHATCH', 'fbp_crosshatch_paper')
update_crosshatch_preserve_color_cb = _make_effect_update_callback('CROSSHATCH', 'fbp_crosshatch_preserve_color')
update_crosshatch_factor_cb = _make_effect_update_callback('CROSSHATCH', 'fbp_crosshatch_factor')
update_emboss_angle_cb = _make_effect_update_callback('EMBOSS', 'fbp_emboss_angle')
update_emboss_distance_cb = _make_effect_update_callback('EMBOSS', 'fbp_emboss_distance')
update_emboss_strength_cb = _make_effect_update_callback('EMBOSS', 'fbp_emboss_strength')
update_emboss_bias_cb = _make_effect_update_callback('EMBOSS', 'fbp_emboss_bias')
update_emboss_color_amount_cb = _make_effect_update_callback('EMBOSS', 'fbp_emboss_color_amount')
update_emboss_factor_cb = _make_effect_update_callback('EMBOSS', 'fbp_emboss_factor')
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
update_luma_matte_source_type_cb = _make_effect_update_callback('LUMA_MATTE', 'fbp_luma_matte_source_type')
update_luma_matte_path_cb = _make_effect_update_callback('LUMA_MATTE', 'fbp_luma_matte_path')
update_luma_matte_image_cb = _make_effect_update_callback('LUMA_MATTE', 'fbp_luma_matte_image')
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
update_clipping_mask_use_camera_projection_cb = _make_effect_update_callback('CLIPPING_MASK', 'fbp_clipping_mask_use_camera_projection')
update_clipping_mask_uv_offset_x_cb = _make_effect_update_callback('CLIPPING_MASK', 'fbp_clipping_mask_uv_offset_x')
update_clipping_mask_uv_offset_y_cb = _make_effect_update_callback('CLIPPING_MASK', 'fbp_clipping_mask_uv_offset_y')
update_clipping_mask_uv_scale_x_cb = _make_effect_update_callback('CLIPPING_MASK', 'fbp_clipping_mask_uv_scale_x')
update_clipping_mask_uv_scale_y_cb = _make_effect_update_callback('CLIPPING_MASK', 'fbp_clipping_mask_uv_scale_y')
update_clipping_mask_uv_rotation_cb = _make_effect_update_callback('CLIPPING_MASK', 'fbp_clipping_mask_uv_rotation')
update_imported_mask_path_cb = _make_effect_update_callback('IMPORTED_MASK', 'fbp_imported_mask_path')
update_imported_mask_factor_cb = _make_effect_update_callback('IMPORTED_MASK', 'fbp_imported_mask_factor')
update_imported_mask_invert_cb = _make_effect_update_callback('IMPORTED_MASK', 'fbp_imported_mask_invert')
update_gp_mask_slot_2_path_cb = _make_effect_update_callback('GP_MASK_SLOT_2', 'fbp_gp_mask_slot_2_path')
update_gp_mask_slot_2_factor_cb = _make_effect_update_callback('GP_MASK_SLOT_2', 'fbp_gp_mask_slot_2_factor')
update_gp_mask_slot_2_invert_cb = _make_effect_update_callback('GP_MASK_SLOT_2', 'fbp_gp_mask_slot_2_invert')
update_gp_mask_slot_3_path_cb = _make_effect_update_callback('GP_MASK_SLOT_3', 'fbp_gp_mask_slot_3_path')
update_gp_mask_slot_3_factor_cb = _make_effect_update_callback('GP_MASK_SLOT_3', 'fbp_gp_mask_slot_3_factor')
update_gp_mask_slot_3_invert_cb = _make_effect_update_callback('GP_MASK_SLOT_3', 'fbp_gp_mask_slot_3_invert')
update_gp_mask_slot_4_path_cb = _make_effect_update_callback('GP_MASK_SLOT_4', 'fbp_gp_mask_slot_4_path')
update_gp_mask_slot_4_factor_cb = _make_effect_update_callback('GP_MASK_SLOT_4', 'fbp_gp_mask_slot_4_factor')
update_gp_mask_slot_4_invert_cb = _make_effect_update_callback('GP_MASK_SLOT_4', 'fbp_gp_mask_slot_4_invert')
update_layer_blend_source_cb = _make_effect_update_callback('LAYER_BLEND', 'fbp_layer_blend_source')
update_layer_blend_mode_cb = _make_effect_update_callback('LAYER_BLEND', 'fbp_layer_blend_mode')
update_layer_blend_factor_cb = _make_effect_update_callback('LAYER_BLEND', 'fbp_layer_blend_factor')
update_square_mask_object_cb = _make_effect_update_callback('SQUARE_MASK', 'fbp_square_mask_object')
update_square_mask_factor_cb = _make_effect_update_callback('SQUARE_MASK', 'fbp_square_mask_factor')
update_square_mask_invert_cb = _make_effect_update_callback('SQUARE_MASK', 'fbp_square_mask_invert')
update_square_mask_feather_cb = _make_effect_update_callback('SQUARE_MASK', 'fbp_square_mask_feather')
update_circle_mask_object_cb = _make_effect_update_callback('CIRCLE_MASK', 'fbp_circle_mask_object')
update_circle_mask_factor_cb = _make_effect_update_callback('CIRCLE_MASK', 'fbp_circle_mask_factor')
update_circle_mask_invert_cb = _make_effect_update_callback('CIRCLE_MASK', 'fbp_circle_mask_invert')
update_circle_mask_feather_cb = _make_effect_update_callback('CIRCLE_MASK', 'fbp_circle_mask_feather')
update_emission_strength_cb = _make_effect_update_callback('EMISSION', 'fbp_emission_strength')
update_triangle_mask_object_cb = _make_effect_update_callback('TRIANGLE_MASK', 'fbp_triangle_mask_object')
update_triangle_mask_factor_cb = _make_effect_update_callback('TRIANGLE_MASK', 'fbp_triangle_mask_factor')
update_triangle_mask_invert_cb = _make_effect_update_callback('TRIANGLE_MASK', 'fbp_triangle_mask_invert')
update_triangle_mask_feather_cb = _make_effect_update_callback('TRIANGLE_MASK', 'fbp_triangle_mask_feather')
update_color_mask_color_cb = _make_effect_update_callback('COLOR_MASK', 'fbp_color_mask_color')
update_color_mask_tolerance_cb = _make_effect_update_callback('COLOR_MASK', 'fbp_color_mask_tolerance')
update_color_mask_softness_cb = _make_effect_update_callback('COLOR_MASK', 'fbp_color_mask_softness')
update_color_mask_factor_cb = _make_effect_update_callback('COLOR_MASK', 'fbp_color_mask_factor')
update_color_mask_invert_cb = _make_effect_update_callback('COLOR_MASK', 'fbp_color_mask_invert')
update_luminance_mask_minimum_cb = _make_effect_update_callback('LUMINANCE_MASK', 'fbp_luminance_mask_minimum')
update_luminance_mask_maximum_cb = _make_effect_update_callback('LUMINANCE_MASK', 'fbp_luminance_mask_maximum')
update_luminance_mask_softness_cb = _make_effect_update_callback('LUMINANCE_MASK', 'fbp_luminance_mask_softness')
update_luminance_mask_factor_cb = _make_effect_update_callback('LUMINANCE_MASK', 'fbp_luminance_mask_factor')
update_luminance_mask_invert_cb = _make_effect_update_callback('LUMINANCE_MASK', 'fbp_luminance_mask_invert')
update_channel_mask_channel_cb = _make_effect_update_callback('CHANNEL_MASK', 'fbp_channel_mask_channel')
update_channel_mask_minimum_cb = _make_effect_update_callback('CHANNEL_MASK', 'fbp_channel_mask_minimum')
update_channel_mask_maximum_cb = _make_effect_update_callback('CHANNEL_MASK', 'fbp_channel_mask_maximum')
update_channel_mask_softness_cb = _make_effect_update_callback('CHANNEL_MASK', 'fbp_channel_mask_softness')
update_channel_mask_factor_cb = _make_effect_update_callback('CHANNEL_MASK', 'fbp_channel_mask_factor')
update_channel_mask_invert_cb = _make_effect_update_callback('CHANNEL_MASK', 'fbp_channel_mask_invert')
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
update_voronoi_mask_scale_cb = _make_effect_update_callback('VORONOI_MASK', 'fbp_voronoi_mask_scale')
update_voronoi_mask_angle_cb = _make_effect_update_callback('VORONOI_MASK', 'fbp_voronoi_mask_angle')
update_voronoi_mask_randomness_cb = _make_effect_update_callback('VORONOI_MASK', 'fbp_voronoi_mask_randomness')
update_voronoi_mask_threshold_cb = _make_effect_update_callback('VORONOI_MASK', 'fbp_voronoi_mask_threshold')
update_voronoi_mask_softness_cb = _make_effect_update_callback('VORONOI_MASK', 'fbp_voronoi_mask_softness')
update_voronoi_mask_seed_cb = _make_effect_update_callback('VORONOI_MASK', 'fbp_voronoi_mask_seed')
update_voronoi_mask_factor_cb = _make_effect_update_callback('VORONOI_MASK', 'fbp_voronoi_mask_factor')
update_voronoi_mask_invert_cb = _make_effect_update_callback('VORONOI_MASK', 'fbp_voronoi_mask_invert')
update_wave_mask_scale_cb = _make_effect_update_callback('WAVE_MASK', 'fbp_wave_mask_scale')
update_wave_mask_angle_cb = _make_effect_update_callback('WAVE_MASK', 'fbp_wave_mask_angle')
update_wave_mask_distortion_cb = _make_effect_update_callback('WAVE_MASK', 'fbp_wave_mask_distortion')
update_wave_mask_detail_cb = _make_effect_update_callback('WAVE_MASK', 'fbp_wave_mask_detail')
update_wave_mask_detail_scale_cb = _make_effect_update_callback('WAVE_MASK', 'fbp_wave_mask_detail_scale')
update_wave_mask_detail_roughness_cb = _make_effect_update_callback('WAVE_MASK', 'fbp_wave_mask_detail_roughness')
update_wave_mask_phase_cb = _make_effect_update_callback('WAVE_MASK', 'fbp_wave_mask_phase')
update_wave_mask_threshold_cb = _make_effect_update_callback('WAVE_MASK', 'fbp_wave_mask_threshold')
update_wave_mask_softness_cb = _make_effect_update_callback('WAVE_MASK', 'fbp_wave_mask_softness')
update_wave_mask_factor_cb = _make_effect_update_callback('WAVE_MASK', 'fbp_wave_mask_factor')
update_wave_mask_invert_cb = _make_effect_update_callback('WAVE_MASK', 'fbp_wave_mask_invert')




def _make_shape_mask_external_null_update(shape):
    shape = str(shape or "SQUARE").upper()
    prefix = shape.lower()
    def _update(self, context):
        if fbp_undo_guard_active() or fbp_is_silent_property_update(self):
            return
        try:
            target = getattr(self, f"fbp_{prefix}_mask_external_null", None)
            if target is not None:
                fbp_set_rna_property_silent(self, f"fbp_{prefix}_mask_follow_bounds", False)
            from .object_masks import sync_shape_mask_external_null
            sync_shape_mask_external_null(self, shape)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn(f"Could not update {shape.title()} Mask external Null", exc)
        fbp_request_redraw(context, area_types={'VIEW_3D'})
    return _update


update_square_mask_external_null_cb = _make_shape_mask_external_null_update("SQUARE")
update_circle_mask_external_null_cb = _make_shape_mask_external_null_update("CIRCLE")
update_triangle_mask_external_null_cb = _make_shape_mask_external_null_update("TRIANGLE")

def _make_object_mask_follow_update(shape, effect_id, prop_name):
    def _update(self, context):
        if fbp_undo_guard_active() or fbp_is_silent_property_update(self):
            return
        try:
            from .object_masks import sync_object_mask_helper_to_bounds
            sync_object_mask_helper_to_bounds(self, shape, force=True)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not update Shape Mask bounds", exc)
        return _queue_effect_setting_update(self, context, effect_id, prop_name)
    return _update


def _make_object_mask_runtime_update(shape):
    def _update(self, context):
        if fbp_undo_guard_active() or fbp_is_silent_property_update(self):
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
        fbp_request_redraw(context, area_types={'VIEW_3D'})
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
update_halftone_dot_scale_cb = _make_effect_update_callback('HALFTONE', 'fbp_halftone_dot_scale')
update_halftone_blend_cb = _make_effect_update_callback('HALFTONE', 'fbp_halftone_blend')
update_halftone_softness_cb = _make_effect_update_callback('HALFTONE', 'fbp_halftone_softness')
update_halftone_rotation_cb = _make_effect_update_callback('HALFTONE', 'fbp_halftone_rotation')
update_halftone_contrast_cb = _make_effect_update_callback('HALFTONE', 'fbp_halftone_contrast')
update_halftone_invert_cb = _make_effect_update_callback('HALFTONE', 'fbp_halftone_invert')
update_halftone_pattern_cb = _make_effect_update_callback('HALFTONE', 'fbp_halftone_pattern')
update_halftone_color_mode_cb = _make_effect_update_callback('HALFTONE', 'fbp_halftone_color_mode')
update_halftone_shape_cb = _make_effect_update_callback('HALFTONE', 'fbp_halftone_shape')
update_halftone_use_source_color_cb = _make_effect_update_callback('HALFTONE', 'fbp_halftone_use_source_color')
update_halftone_foreground_cb = _make_effect_update_callback('HALFTONE', 'fbp_halftone_foreground')
update_halftone_background_cb = _make_effect_update_callback('HALFTONE', 'fbp_halftone_background')
update_halftone_transparent_background_cb = _make_effect_update_callback('HALFTONE', 'fbp_halftone_transparent_background')
update_halftone_center_x_cb = _make_effect_update_callback('HALFTONE', 'fbp_halftone_center_x')
update_halftone_center_y_cb = _make_effect_update_callback('HALFTONE', 'fbp_halftone_center_y')
update_halftone_clip_alpha_cb = _make_effect_update_callback('HALFTONE', 'fbp_halftone_clip_alpha')
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
update_ascii_gamma_cb = _make_effect_update_callback('ASCII_MATRIX', 'fbp_ascii_gamma')
update_ascii_glyph_scale_cb = _make_effect_update_callback('ASCII_MATRIX', 'fbp_ascii_glyph_scale')
update_ascii_glyph_width_cb = _make_effect_update_callback('ASCII_MATRIX', 'fbp_ascii_glyph_width')
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
update_solarize_threshold_cb = _make_effect_update_callback('SOLARIZE', 'fbp_solarize_threshold')
update_solarize_softness_cb = _make_effect_update_callback('SOLARIZE', 'fbp_solarize_softness')
update_solarize_factor_cb = _make_effect_update_callback('SOLARIZE', 'fbp_solarize_factor')
update_tritone_shadows_cb = _make_effect_update_callback('TRITONE', 'fbp_tritone_shadows')
update_tritone_midtones_cb = _make_effect_update_callback('TRITONE', 'fbp_tritone_midtones')
update_tritone_highlights_cb = _make_effect_update_callback('TRITONE', 'fbp_tritone_highlights')
update_tritone_midpoint_cb = _make_effect_update_callback('TRITONE', 'fbp_tritone_midpoint')
update_tritone_factor_cb = _make_effect_update_callback('TRITONE', 'fbp_tritone_factor')
update_film_fade_color_cb = _make_effect_update_callback('FILM_FADE', 'fbp_film_fade_color')
update_film_fade_amount_cb = _make_effect_update_callback('FILM_FADE', 'fbp_film_fade_amount')
update_film_fade_desaturation_cb = _make_effect_update_callback('FILM_FADE', 'fbp_film_fade_desaturation')
update_film_fade_contrast_loss_cb = _make_effect_update_callback('FILM_FADE', 'fbp_film_fade_contrast_loss')
update_solid_mask_color_cb = _make_effect_update_callback('SOLID_MASK', 'fbp_solid_mask_color')
update_solid_mask_factor_cb = _make_effect_update_callback('SOLID_MASK', 'fbp_solid_mask_factor')
update_stop_motion_resolution_cb = _make_effect_update_callback('STOP_MOTION_CRUMPLE', 'fbp_stop_motion_resolution')
update_stop_motion_playback_resolution_cb = _make_effect_update_callback('STOP_MOTION_CRUMPLE', 'fbp_stop_motion_playback_resolution')
update_stop_motion_render_resolution_cb = _make_effect_update_callback('STOP_MOTION_CRUMPLE', 'fbp_stop_motion_render_resolution')
update_stop_motion_strength_cb = _make_effect_update_callback('STOP_MOTION_CRUMPLE', 'fbp_stop_motion_strength')
update_stop_motion_step_frames_cb = _make_effect_update_callback('STOP_MOTION_CRUMPLE', 'fbp_stop_motion_step_frames')
update_wind_bend_amount_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_bend_amount')
update_wind_speed_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_speed')
update_wind_shade_smooth_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_shade_smooth')
update_wind_playback_subdivision_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_playback_subdivision')
update_wind_render_subdivision_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_render_subdivision')
update_wind_subdivision_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_subdivision')
update_wind_stepped_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_stepped')
update_wind_pin_edge_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_pin_edge')
update_wind_pin_strength_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_pin_strength')
update_wind_pin_vertex_group_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_pin_vertex_group')
update_wind_motion_mode_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_motion_mode')
update_wind_ripple_direction_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_ripple_direction')
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
def update_lattice_effect_cb(self, context):
    try:
        from .fbp_dirty import mark_geometry_callback
        if mark_geometry_callback(self, 'update_lattice_effect_cb', context=context, effect_id='LATTICE'):
            return None
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return _call_geometry_nodes('update_lattice_effect_cb', self, context)


def update_lattice_mesh_detail_cb(self, context):
    try:
        from .fbp_dirty import mark_geometry_callback
        if mark_geometry_callback(self, 'update_lattice_mesh_detail_cb', context=context, effect_id='LATTICE'):
            return None
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return _call_geometry_nodes('update_lattice_mesh_detail_cb', self, context)


def update_lattice_grid_preset_cb(self, context):
    try:
        from .fbp_dirty import mark_geometry_callback
        if mark_geometry_callback(self, 'update_lattice_grid_preset_cb', context=context, effect_id='LATTICE'):
            return None
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return _call_geometry_nodes('update_lattice_grid_preset_cb', self, context)


def update_lattice_custom_loops_u_cb(self, context):
    try:
        from .fbp_dirty import mark_geometry_callback
        if mark_geometry_callback(self, 'update_lattice_custom_loops_cb', 'U', context=context, effect_id='LATTICE'):
            return None
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return _call_geometry_nodes('update_lattice_custom_loops_cb', self, context, 'U')


def update_lattice_custom_loops_v_cb(self, context):
    try:
        from .fbp_dirty import mark_geometry_callback
        if mark_geometry_callback(self, 'update_lattice_custom_loops_cb', 'V', context=context, effect_id='LATTICE'):
            return None
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return _call_geometry_nodes('update_lattice_custom_loops_cb', self, context, 'V')


def update_lattice_loop_link_cb(self, context):
    try:
        from .fbp_dirty import mark_geometry_callback
        if mark_geometry_callback(self, 'update_lattice_loop_link_cb', context=context, effect_id='LATTICE'):
            return None
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return _call_geometry_nodes('update_lattice_loop_link_cb', self, context)


def update_lattice_camera_settings_cb(self, context):
    try:
        from .fbp_dirty import mark_geometry_callback
        if mark_geometry_callback(self, 'update_lattice_camera_settings_cb', context=context, effect_id='LATTICE'):
            return None
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return _call_geometry_nodes('update_lattice_camera_settings_cb', self, context)


def update_lattice_visibility_cb(self, context):
    return _call_geometry_nodes('update_lattice_visibility_cb', self, context)


def update_lattice_interpolation_cb(self, context):
    try:
        from .fbp_dirty import mark_geometry_callback
        if mark_geometry_callback(self, 'update_lattice_interpolation_cb', context=context, effect_id='LATTICE'):
            return None
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return _call_geometry_nodes('update_lattice_interpolation_cb', self, context)


update_cutout_outline_viewport_resolution_cb = _make_effect_update_callback('CUTOUT_OUTLINE', 'fbp_cutout_outline_viewport_resolution')
update_cutout_outline_playback_resolution_cb = _make_effect_update_callback('CUTOUT_OUTLINE', 'fbp_cutout_outline_playback_resolution')
update_cutout_outline_render_resolution_cb = _make_effect_update_callback('CUTOUT_OUTLINE', 'fbp_cutout_outline_render_resolution')
update_cutout_outline_alpha_threshold_cb = _make_effect_update_callback('CUTOUT_OUTLINE', 'fbp_cutout_outline_alpha_threshold')
update_cutout_outline_width_cb = _make_effect_update_callback('CUTOUT_OUTLINE', 'fbp_cutout_outline_width')
update_cutout_outline_offset_cb = _make_effect_update_callback('CUTOUT_OUTLINE', 'fbp_cutout_outline_offset')
update_cutout_outline_color_cb = _make_effect_update_callback('CUTOUT_OUTLINE', 'fbp_cutout_outline_color')
update_cutout_outline_show_image_cb = _make_effect_update_callback('CUTOUT_OUTLINE', 'fbp_cutout_outline_show_image')
update_cutout_outline_wiggle_amount_cb = _make_effect_update_callback('CUTOUT_OUTLINE', 'fbp_cutout_outline_wiggle_amount')
update_cutout_outline_wiggle_scale_cb = _make_effect_update_callback('CUTOUT_OUTLINE', 'fbp_cutout_outline_wiggle_scale')
update_cutout_outline_wiggle_phase_cb = _make_effect_update_callback('CUTOUT_OUTLINE', 'fbp_cutout_outline_wiggle_phase')
update_camera_scale_lock_reference_distance_cb = _make_effect_update_callback('CAMERA_SCALE_LOCK', 'fbp_camera_scale_lock_reference_distance')
update_camera_scale_lock_reference_lens_cb = _make_effect_update_callback('CAMERA_SCALE_LOCK', 'fbp_camera_scale_lock_reference_lens')
update_camera_scale_lock_reference_sensor_width_cb = _make_effect_update_callback('CAMERA_SCALE_LOCK', 'fbp_camera_scale_lock_reference_sensor_width')
update_camera_scale_lock_influence_cb = _make_effect_update_callback('CAMERA_SCALE_LOCK', 'fbp_camera_scale_lock_influence')
def _update_camera_track_cb(self, context):
    if fbp_undo_guard_active() or fbp_is_silent_property_update(self):
        return
    try:
        from .geometry_nodes import fbp_update_track_to_camera
        fbp_update_track_to_camera(self, getattr(context, 'scene', None))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn('Could not update Track to Camera', exc)

update_camera_billboard_mode_cb = _update_camera_track_cb
update_camera_billboard_flip_cb = _update_camera_track_cb
update_camera_billboard_influence_cb = _update_camera_track_cb
update_mirror_x_cb = _make_effect_update_callback('MIRROR', 'fbp_mirror_x')
update_mirror_y_cb = _make_effect_update_callback('MIRROR', 'fbp_mirror_y')
update_thickness_viewport_pixels_x_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_viewport_pixels_x')
update_thickness_viewport_pixels_y_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_viewport_pixels_y')
update_thickness_playback_pixels_x_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_playback_pixels_x')
update_thickness_playback_pixels_y_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_playback_pixels_y')
update_thickness_render_pixels_x_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_render_pixels_x')
update_thickness_render_pixels_y_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_render_pixels_y')
update_thickness_grid_mode_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_grid_mode')
update_thickness_follow_pixelate_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_follow_pixelate')
update_thickness_safe_grid_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_safe_grid')
update_thickness_amount_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_amount')
update_thickness_mode_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_mode')
update_thickness_array_count_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_array_count')
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
update_fiber_render_density_cb = _make_effect_update_callback('FIBER_TUFTS', 'fbp_fiber_render_density')
update_fiber_viewport_percentage_cb = _make_effect_update_callback('FIBER_TUFTS', 'fbp_fiber_viewport_percentage')
update_fiber_length_cb = _make_effect_update_callback('FIBER_TUFTS', 'fbp_fiber_length')
update_fiber_luminance_length_cb = _make_effect_update_callback('FIBER_TUFTS', 'fbp_fiber_luminance_length')
update_fiber_radius_cb = _make_effect_update_callback('FIBER_TUFTS', 'fbp_fiber_radius')
update_fiber_segments_cb = _make_effect_update_callback('FIBER_TUFTS', 'fbp_fiber_segments')
update_fiber_bend_cb = _make_effect_update_callback('FIBER_TUFTS', 'fbp_fiber_bend')
update_fiber_randomness_cb = _make_effect_update_callback('FIBER_TUFTS', 'fbp_fiber_randomness')
update_fiber_seed_cb = _make_effect_update_callback('FIBER_TUFTS', 'fbp_fiber_seed')
update_fiber_alpha_threshold_cb = _make_effect_update_callback('FIBER_TUFTS', 'fbp_fiber_alpha_threshold')
update_fiber_alpha_resolution_cb = _make_effect_update_callback('FIBER_TUFTS', 'fbp_fiber_alpha_resolution')
update_shards_render_density_cb = _make_effect_update_callback('PAPER_SHARDS', 'fbp_shards_render_density')
update_shards_viewport_percentage_cb = _make_effect_update_callback('PAPER_SHARDS', 'fbp_shards_viewport_percentage')
update_shards_size_cb = _make_effect_update_callback('PAPER_SHARDS', 'fbp_shards_size')
update_shards_aspect_cb = _make_effect_update_callback('PAPER_SHARDS', 'fbp_shards_aspect')
update_shards_thickness_cb = _make_effect_update_callback('PAPER_SHARDS', 'fbp_shards_thickness')
update_shards_lift_cb = _make_effect_update_callback('PAPER_SHARDS', 'fbp_shards_lift')
update_shards_luminance_lift_cb = _make_effect_update_callback('PAPER_SHARDS', 'fbp_shards_luminance_lift')
update_shards_tilt_cb = _make_effect_update_callback('PAPER_SHARDS', 'fbp_shards_tilt')
update_shards_scale_randomness_cb = _make_effect_update_callback('PAPER_SHARDS', 'fbp_shards_scale_randomness')
update_shards_seed_cb = _make_effect_update_callback('PAPER_SHARDS', 'fbp_shards_seed')
update_shards_alpha_threshold_cb = _make_effect_update_callback('PAPER_SHARDS', 'fbp_shards_alpha_threshold')
update_shards_alpha_resolution_cb = _make_effect_update_callback('PAPER_SHARDS', 'fbp_shards_alpha_resolution')
update_sphere_screen_viewport_columns_cb = _make_effect_update_callback('SPHERE_SCREEN', 'fbp_sphere_screen_viewport_columns')
update_sphere_screen_viewport_rows_cb = _make_effect_update_callback('SPHERE_SCREEN', 'fbp_sphere_screen_viewport_rows')
update_sphere_screen_render_columns_cb = _make_effect_update_callback('SPHERE_SCREEN', 'fbp_sphere_screen_render_columns')
update_sphere_screen_render_rows_cb = _make_effect_update_callback('SPHERE_SCREEN', 'fbp_sphere_screen_render_rows')
update_sphere_screen_shape_cb = _make_effect_update_callback('SPHERE_SCREEN', 'fbp_sphere_screen_shape')
update_sphere_screen_scale_cb = _make_effect_update_callback('SPHERE_SCREEN', 'fbp_sphere_screen_scale')
update_sphere_screen_luminance_size_cb = _make_effect_update_callback('SPHERE_SCREEN', 'fbp_sphere_screen_luminance_size')
update_sphere_screen_subdivisions_cb = _make_effect_update_callback('SPHERE_SCREEN', 'fbp_sphere_screen_subdivisions')
update_sphere_screen_depth_cb = _make_effect_update_callback('SPHERE_SCREEN', 'fbp_sphere_screen_depth')
update_sphere_screen_depth_mode_cb = _make_effect_update_callback('SPHERE_SCREEN', 'fbp_sphere_screen_depth_mode')
update_sphere_screen_depth_image_cb = _make_effect_update_callback('SPHERE_SCREEN', 'fbp_sphere_screen_depth_image')
update_sphere_screen_flicker_cb = _make_effect_update_callback('SPHERE_SCREEN', 'fbp_sphere_screen_flicker')
update_sphere_screen_phase_cb = _make_effect_update_callback('SPHERE_SCREEN', 'fbp_sphere_screen_phase')
update_sphere_screen_alpha_threshold_cb = _make_effect_update_callback('SPHERE_SCREEN', 'fbp_sphere_screen_alpha_threshold')
update_sphere_screen_show_source_cb = _make_effect_update_callback('SPHERE_SCREEN', 'fbp_sphere_screen_show_source')
update_sphere_screen_emission_cb = _make_effect_update_callback('SPHERE_SCREEN', 'fbp_sphere_screen_emission')
update_image_relief_subdivision_cb = _make_effect_update_callback('IMAGE_RELIEF', 'fbp_image_relief_subdivision')
update_image_relief_playback_subdivision_cb = _make_effect_update_callback('IMAGE_RELIEF', 'fbp_image_relief_playback_subdivision')
update_image_relief_render_subdivision_cb = _make_effect_update_callback('IMAGE_RELIEF', 'fbp_image_relief_render_subdivision')
update_image_relief_depth_cb = _make_effect_update_callback('IMAGE_RELIEF', 'fbp_image_relief_depth')
update_image_relief_midlevel_cb = _make_effect_update_callback('IMAGE_RELIEF', 'fbp_image_relief_midlevel')
update_image_relief_depth_mode_cb = _make_effect_update_callback('IMAGE_RELIEF', 'fbp_image_relief_depth_mode')
update_image_relief_depth_image_cb = _make_effect_update_callback('IMAGE_RELIEF', 'fbp_image_relief_depth_image')
update_image_relief_smooth_cb = _make_effect_update_callback('IMAGE_RELIEF', 'fbp_image_relief_smooth')
update_image_relief_smooth_iterations_cb = _make_effect_update_callback('IMAGE_RELIEF', 'fbp_image_relief_smooth_iterations')
update_image_relief_alpha_threshold_cb = _make_effect_update_callback('IMAGE_RELIEF', 'fbp_image_relief_alpha_threshold')
update_image_relief_shade_smooth_cb = _make_effect_update_callback('IMAGE_RELIEF', 'fbp_image_relief_shade_smooth')
update_glass_subdivision_cb = _make_effect_update_callback('GLASS', 'fbp_glass_subdivision')
update_glass_playback_subdivision_cb = _make_effect_update_callback('GLASS', 'fbp_glass_playback_subdivision')
update_glass_render_subdivision_cb = _make_effect_update_callback('GLASS', 'fbp_glass_render_subdivision')
update_glass_thickness_cb = _make_effect_update_callback('GLASS', 'fbp_glass_thickness')
update_glass_relief_cb = _make_effect_update_callback('GLASS', 'fbp_glass_relief')
update_glass_source_cb = _make_effect_update_callback('GLASS', 'fbp_glass_source')
update_glass_normal_image_cb = _make_effect_update_callback('GLASS', 'fbp_glass_normal_image')
update_glass_noise_scale_cb = _make_effect_update_callback('GLASS', 'fbp_glass_noise_scale')
update_glass_correct_aspect_cb = _make_effect_update_callback('GLASS', 'fbp_glass_correct_aspect')
update_glass_texture_scale_x_cb = _make_effect_update_callback('GLASS', 'fbp_glass_texture_scale_x')
update_glass_texture_scale_y_cb = _make_effect_update_callback('GLASS', 'fbp_glass_texture_scale_y')
update_glass_crack_width_cb = _make_effect_update_callback('GLASS', 'fbp_glass_crack_width')
update_glass_damage_cb = _make_effect_update_callback('GLASS', 'fbp_glass_damage')
update_glass_noise_detail_cb = _make_effect_update_callback('GLASS', 'fbp_glass_noise_detail')
update_glass_phase_cb = _make_effect_update_callback('GLASS', 'fbp_glass_phase')
update_glass_alpha_threshold_cb = _make_effect_update_callback('GLASS', 'fbp_glass_alpha_threshold')
update_glass_shade_smooth_cb = _make_effect_update_callback('GLASS', 'fbp_glass_shade_smooth')
update_glass_distortion_cb = _make_effect_update_callback('GLASS', 'fbp_glass_distortion')
update_glass_bevel_cb = _make_effect_update_callback('GLASS', 'fbp_glass_bevel')
update_glass_roughness_cb = _make_effect_update_callback('GLASS', 'fbp_glass_roughness')
update_glass_ior_cb = _make_effect_update_callback('GLASS', 'fbp_glass_ior')
update_glass_tint_cb = _make_effect_update_callback('GLASS', 'fbp_glass_tint')
update_glass_source_color_cb = _make_effect_update_callback('GLASS', 'fbp_glass_source_color')
update_glass_edge_tint_cb = _make_effect_update_callback('GLASS', 'fbp_glass_edge_tint')
update_glass_absorption_cb = _make_effect_update_callback('GLASS', 'fbp_glass_absorption')
update_crystal_subdivision_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_subdivision')
update_crystal_playback_subdivision_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_playback_subdivision')
update_crystal_render_subdivision_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_render_subdivision')
update_crystal_silhouette_detail_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_silhouette_detail')
update_crystal_depth_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_depth')
update_crystal_thickness_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_thickness')
update_crystal_roundness_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_roundness')
update_crystal_edge_pinning_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_edge_pinning')
update_crystal_blur_iterations_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_blur_iterations')
update_crystal_use_influence_map_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_use_influence_map')
update_crystal_influence_image_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_influence_image')
update_crystal_invert_influence_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_invert_influence')
update_crystal_influence_strength_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_influence_strength')
update_crystal_texture_type_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_texture_type')
update_crystal_pattern_mode_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_pattern_mode')
update_crystal_pattern_scale_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_pattern_scale')
update_crystal_correct_aspect_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_correct_aspect')
update_crystal_texture_scale_x_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_texture_scale_x')
update_crystal_texture_scale_y_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_texture_scale_y')
update_crystal_pattern_detail_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_pattern_detail')
update_crystal_pattern_strength_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_pattern_strength')
update_crystal_cell_randomness_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_cell_randomness')
update_crystal_cell_seed_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_cell_seed')
update_crystal_phase_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_phase')
update_crystal_alpha_threshold_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_alpha_threshold')
update_crystal_surface_subdivision_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_surface_subdivision')
update_crystal_shade_smooth_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_shade_smooth')
update_crystal_distortion_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_distortion')
update_crystal_roughness_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_roughness')
update_crystal_ior_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_ior')
update_crystal_tint_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_tint')
update_crystal_source_color_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_source_color')
update_crystal_absorption_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_absorption')
update_crystal_thin_wall_cb = _make_effect_update_callback('CRYSTAL', 'fbp_crystal_thin_wall')
update_surface_conform_target_cb = _make_effect_update_callback('SURFACE_CONFORM', 'fbp_surface_conform_target')
update_surface_conform_subdivision_cb = _make_effect_update_callback('SURFACE_CONFORM', 'fbp_surface_conform_subdivision')
update_surface_conform_playback_subdivision_cb = _make_effect_update_callback('SURFACE_CONFORM', 'fbp_surface_conform_playback_subdivision')
update_surface_conform_render_subdivision_cb = _make_effect_update_callback('SURFACE_CONFORM', 'fbp_surface_conform_render_subdivision')
update_surface_conform_factor_cb = _make_effect_update_callback('SURFACE_CONFORM', 'fbp_surface_conform_factor')
update_surface_conform_offset_cb = _make_effect_update_callback('SURFACE_CONFORM', 'fbp_surface_conform_offset')
update_surface_conform_max_distance_cb = _make_effect_update_callback('SURFACE_CONFORM', 'fbp_surface_conform_max_distance')
update_surface_conform_shade_smooth_cb = _make_effect_update_callback('SURFACE_CONFORM', 'fbp_surface_conform_shade_smooth')
update_accordion_subdivision_cb = _make_effect_update_callback('ACCORDION_FOLD', 'fbp_accordion_subdivision')
update_accordion_playback_subdivision_cb = _make_effect_update_callback('ACCORDION_FOLD', 'fbp_accordion_playback_subdivision')
update_accordion_render_subdivision_cb = _make_effect_update_callback('ACCORDION_FOLD', 'fbp_accordion_render_subdivision')
update_accordion_folds_cb = _make_effect_update_callback('ACCORDION_FOLD', 'fbp_accordion_folds')
update_accordion_depth_cb = _make_effect_update_callback('ACCORDION_FOLD', 'fbp_accordion_depth')
update_accordion_phase_cb = _make_effect_update_callback('ACCORDION_FOLD', 'fbp_accordion_phase')
update_accordion_vertical_cb = _make_effect_update_callback('ACCORDION_FOLD', 'fbp_accordion_vertical')
update_accordion_shade_smooth_cb = _make_effect_update_callback('ACCORDION_FOLD', 'fbp_accordion_shade_smooth')
update_sculpt_waves_subdivision_cb = _make_effect_update_callback('SCULPT_WAVES', 'fbp_sculpt_waves_subdivision')
update_sculpt_waves_playback_subdivision_cb = _make_effect_update_callback('SCULPT_WAVES', 'fbp_sculpt_waves_playback_subdivision')
update_sculpt_waves_render_subdivision_cb = _make_effect_update_callback('SCULPT_WAVES', 'fbp_sculpt_waves_render_subdivision')
update_sculpt_waves_style_cb = _make_effect_update_callback('SCULPT_WAVES', 'fbp_sculpt_waves_style')
update_sculpt_waves_amplitude_cb = _make_effect_update_callback('SCULPT_WAVES', 'fbp_sculpt_waves_amplitude')
update_sculpt_waves_frequency_cb = _make_effect_update_callback('SCULPT_WAVES', 'fbp_sculpt_waves_frequency')
update_sculpt_waves_phase_cb = _make_effect_update_callback('SCULPT_WAVES', 'fbp_sculpt_waves_phase')
update_sculpt_waves_edge_falloff_cb = _make_effect_update_callback('SCULPT_WAVES', 'fbp_sculpt_waves_edge_falloff')
update_sculpt_waves_shade_smooth_cb = _make_effect_update_callback('SCULPT_WAVES', 'fbp_sculpt_waves_shade_smooth')
update_kinetic_tiles_subdivision_cb = _make_effect_update_callback('KINETIC_TILES', 'fbp_kinetic_tiles_subdivision')
update_kinetic_tiles_playback_subdivision_cb = _make_effect_update_callback('KINETIC_TILES', 'fbp_kinetic_tiles_playback_subdivision')
update_kinetic_tiles_render_subdivision_cb = _make_effect_update_callback('KINETIC_TILES', 'fbp_kinetic_tiles_render_subdivision')
update_kinetic_tiles_pattern_cb = _make_effect_update_callback('KINETIC_TILES', 'fbp_kinetic_tiles_pattern')
update_kinetic_tiles_gap_cb = _make_effect_update_callback('KINETIC_TILES', 'fbp_kinetic_tiles_gap')
update_kinetic_tiles_thickness_cb = _make_effect_update_callback('KINETIC_TILES', 'fbp_kinetic_tiles_thickness')
update_kinetic_tiles_motion_cb = _make_effect_update_callback('KINETIC_TILES', 'fbp_kinetic_tiles_motion')
update_kinetic_tiles_frequency_cb = _make_effect_update_callback('KINETIC_TILES', 'fbp_kinetic_tiles_frequency')
update_kinetic_tiles_phase_cb = _make_effect_update_callback('KINETIC_TILES', 'fbp_kinetic_tiles_phase')
update_kinetic_tiles_shade_smooth_cb = _make_effect_update_callback('KINETIC_TILES', 'fbp_kinetic_tiles_shade_smooth')
update_layered_echo_layers_cb = _make_effect_update_callback('LAYERED_ECHO', 'fbp_layered_echo_layers')
update_layered_echo_playback_layers_cb = _make_effect_update_callback('LAYERED_ECHO', 'fbp_layered_echo_playback_layers')
update_layered_echo_render_layers_cb = _make_effect_update_callback('LAYERED_ECHO', 'fbp_layered_echo_render_layers')
update_layered_echo_offset_x_cb = _make_effect_update_callback('LAYERED_ECHO', 'fbp_layered_echo_offset_x')
update_layered_echo_offset_y_cb = _make_effect_update_callback('LAYERED_ECHO', 'fbp_layered_echo_offset_y')
update_layered_echo_spacing_cb = _make_effect_update_callback('LAYERED_ECHO', 'fbp_layered_echo_spacing')
update_layered_echo_scale_step_cb = _make_effect_update_callback('LAYERED_ECHO', 'fbp_layered_echo_scale_step')
update_layered_echo_rotation_x_cb = _make_effect_update_callback('LAYERED_ECHO', 'fbp_layered_echo_rotation_x')
update_layered_echo_rotation_y_cb = _make_effect_update_callback('LAYERED_ECHO', 'fbp_layered_echo_rotation_y')
update_layered_echo_twist_cb = _make_effect_update_callback('LAYERED_ECHO', 'fbp_layered_echo_twist')
update_layered_echo_wave_cb = _make_effect_update_callback('LAYERED_ECHO', 'fbp_layered_echo_wave')
update_layered_echo_phase_cb = _make_effect_update_callback('LAYERED_ECHO', 'fbp_layered_echo_phase')
update_color_isolate_target_cb = _make_effect_update_callback('COLOR_ISOLATE', 'fbp_color_isolate_target')
update_color_isolate_tolerance_cb = _make_effect_update_callback('COLOR_ISOLATE', 'fbp_color_isolate_tolerance')
update_color_isolate_falloff_cb = _make_effect_update_callback('COLOR_ISOLATE', 'fbp_color_isolate_falloff')
update_color_isolate_factor_cb = _make_effect_update_callback('COLOR_ISOLATE', 'fbp_color_isolate_factor')
update_white_balance_temperature_cb = _make_effect_update_callback('WHITE_BALANCE', 'fbp_white_balance_temperature')
update_white_balance_tint_cb = _make_effect_update_callback('WHITE_BALANCE', 'fbp_white_balance_tint')
update_white_balance_factor_cb = _make_effect_update_callback('WHITE_BALANCE', 'fbp_white_balance_factor')
update_curves_factor_cb = _make_effect_update_callback('CURVES', 'fbp_curves_factor')
update_duotone_shadows_cb = _make_effect_update_callback('DUOTONE', 'fbp_duotone_shadows')
update_duotone_highlights_cb = _make_effect_update_callback('DUOTONE', 'fbp_duotone_highlights')
update_recolor_factor_cb = _make_effect_update_callback('RECOLOR', 'fbp_recolor_factor')
update_gradient_map_factor_cb = _make_effect_update_callback('GRADIENT_MAP', 'fbp_gradient_map_factor')
update_channel_mixer_red_cb = _make_effect_update_callback('CHANNEL_MIXER', 'fbp_channel_mixer_red')
update_channel_mixer_green_cb = _make_effect_update_callback('CHANNEL_MIXER', 'fbp_channel_mixer_green')
update_channel_mixer_blue_cb = _make_effect_update_callback('CHANNEL_MIXER', 'fbp_channel_mixer_blue')
update_channel_mixer_factor_cb = _make_effect_update_callback('CHANNEL_MIXER', 'fbp_channel_mixer_factor')
update_dither_style_cb = _make_effect_update_callback('DITHER', 'fbp_dither_style')
update_dither_size_cb = _make_effect_update_callback('DITHER', 'fbp_dither_size')
update_dither_brightness_cb = _make_effect_update_callback('DITHER', 'fbp_dither_brightness')
update_dither_contrast_cb = _make_effect_update_callback('DITHER', 'fbp_dither_contrast')
update_dither_mono_cb = _make_effect_update_callback('DITHER', 'fbp_dither_mono')
update_dither_mono_color_cb = _make_effect_update_callback('DITHER', 'fbp_dither_mono_color')
update_dither_factor_cb = _make_effect_update_callback('DITHER', 'fbp_dither_factor')
update_bloom_threshold_cb = _make_effect_update_callback('BLOOM', 'fbp_bloom_threshold')
update_bloom_softness_cb = _make_effect_update_callback('BLOOM', 'fbp_bloom_softness')
update_bloom_intensity_cb = _make_effect_update_callback('BLOOM', 'fbp_bloom_intensity')
update_bloom_color_cb = _make_effect_update_callback('BLOOM', 'fbp_bloom_color')
update_bloom_factor_cb = _make_effect_update_callback('BLOOM', 'fbp_bloom_factor')
update_filter_preset_sepia_cb = _make_effect_update_callback('FILTER_PRESETS', 'fbp_filter_preset_sepia')
update_filter_preset_warm_cb = _make_effect_update_callback('FILTER_PRESETS', 'fbp_filter_preset_warm')
update_filter_preset_cool_cb = _make_effect_update_callback('FILTER_PRESETS', 'fbp_filter_preset_cool')
update_filter_preset_noir_cb = _make_effect_update_callback('FILTER_PRESETS', 'fbp_filter_preset_noir')
update_filter_preset_factor_cb = _make_effect_update_callback('FILTER_PRESETS', 'fbp_filter_preset_factor')
update_paper_fiber_scale_cb = _make_effect_update_callback('PAPER_FIBERS', 'fbp_paper_fiber_scale')
update_paper_fiber_intensity_cb = _make_effect_update_callback('PAPER_FIBERS', 'fbp_paper_fiber_intensity')
update_paper_fiber_phase_cb = _make_effect_update_callback('PAPER_FIBERS', 'fbp_paper_fiber_phase')
update_gradient_light_center_x_cb = _make_effect_update_callback('GRADIENT_LIGHT', 'fbp_gradient_light_center_x')
update_gradient_light_center_y_cb = _make_effect_update_callback('GRADIENT_LIGHT', 'fbp_gradient_light_center_y')
update_gradient_light_angle_cb = _make_effect_update_callback('GRADIENT_LIGHT', 'fbp_gradient_light_angle')
update_gradient_light_strength_cb = _make_effect_update_callback('GRADIENT_LIGHT', 'fbp_gradient_light_strength')
update_gradient_shadow_position_cb = _make_effect_update_callback('GRADIENT_LIGHT', 'fbp_gradient_shadow_position')
update_gradient_softness_cb = _make_effect_update_callback('GRADIENT_LIGHT', 'fbp_gradient_softness')
update_gradient_shadow_color_cb = _make_effect_update_callback('GRADIENT_LIGHT', 'fbp_gradient_shadow_color')
update_rim_mode_cb = _make_effect_update_callback('RIM', 'fbp_rim_mode')
update_rim_blend_mode_cb = _make_effect_update_callback('RIM', 'fbp_rim_blend_mode')
update_rim_width_cb = _make_effect_update_callback('RIM', 'fbp_rim_width')
update_rim_expand_cb = _make_effect_update_callback('RIM', 'fbp_rim_expand')
update_rim_offset_x_cb = _make_effect_update_callback('RIM', 'fbp_rim_offset_x')
update_rim_offset_y_cb = _make_effect_update_callback('RIM', 'fbp_rim_offset_y')
update_rim_rotation_cb = _make_effect_update_callback('RIM', 'fbp_rim_rotation')
update_rim_blur_cb = _make_effect_update_callback('RIM', 'fbp_rim_blur')
update_rim_softness_cb = _make_effect_update_callback('RIM', 'fbp_rim_softness')
update_rim_intensity_cb = _make_effect_update_callback('RIM', 'fbp_rim_intensity')
update_rim_color_cb = _make_effect_update_callback('RIM', 'fbp_rim_color')
update_shadow_mode_cb = _make_effect_update_callback('SHADOW', 'fbp_shadow_mode')
update_shadow_blend_mode_cb = _make_effect_update_callback('SHADOW', 'fbp_shadow_blend_mode')
update_shadow_offset_x_cb = _make_effect_update_callback('SHADOW', 'fbp_shadow_offset_x')
update_shadow_offset_y_cb = _make_effect_update_callback('SHADOW', 'fbp_shadow_offset_y')
update_shadow_blur_cb = _make_effect_update_callback('SHADOW', 'fbp_shadow_blur')
update_shadow_opacity_cb = _make_effect_update_callback('SHADOW', 'fbp_shadow_opacity')
update_shadow_color_cb = _make_effect_update_callback('SHADOW', 'fbp_shadow_color')
update_gobo_pattern_scale_cb = _make_effect_update_callback('GOBO_SHADOWS', 'fbp_gobo_pattern_scale')
update_gobo_rotation_cb = _make_effect_update_callback('GOBO_SHADOWS', 'fbp_gobo_rotation')
update_gobo_sharpness_cb = _make_effect_update_callback('GOBO_SHADOWS', 'fbp_gobo_sharpness')
update_crt_line_count_cb = _make_effect_update_callback('CRT_SCANLINES', 'fbp_crt_line_count')
update_crt_opacity_cb = _make_effect_update_callback('CRT_SCANLINES', 'fbp_crt_opacity')
update_vignette_radius_cb = _make_effect_update_callback('VIGNETTE', 'fbp_vignette_radius')
update_vignette_smoothness_cb = _make_effect_update_callback('VIGNETTE', 'fbp_vignette_smoothness')
update_vignette_strength_cb = _make_effect_update_callback('VIGNETTE', 'fbp_vignette_strength')


_EFFECT_ANIMATION_IDS = (
    'MESH_WIGGLE',
    'WIND_BENDER',
    'CUTOUT_OUTLINE',
    'FELT_FUZZ',
    'FIBER_TUFTS',
    'PAPER_SHARDS',
    'SPHERE_SCREEN',
    'IMAGE_RELIEF',
    'GLASS',
    'CRYSTAL',
    'SURFACE_CONFORM',
    'ACCORDION_FOLD',
    'SCULPT_WAVES',
    'KINETIC_TILES',
    'LAYERED_ECHO',
    'UV_DISTORTION',
    'WAVE_WARP',
    'RIPPLE_DISTORTION',
    'MOSAIC_JITTER',
    'SLICE_SHIFT',
    'NOISE_MASK',
    'VORONOI_MASK',
    'WAVE_MASK',
    'SOLID_MASK',
    'HUE_SATURATION',
    'GRAIN',
    'PAPER_FIBERS',
    'POSTERIZE',
    'DIGITAL_NOISE',
    'DOT_MATRIX',
    'ASCII_MATRIX',
    'ASCII',
    'TEXT_MATRIX',
)

def _effect_animation_property_name(effect_id, suffix):
    return fbp_effect_storage_key("fbp_anim_", effect_id, f"_{suffix}")


def _make_effect_animation_update_callback(effect_id, suffix):
    def _update(self, context):
        if fbp_undo_guard_active() or fbp_is_silent_property_update(self):
            return None
        try:
            from .fbp_dirty import mark_effect_animation_setting
            if mark_effect_animation_setting(self, effect_id, suffix, context=context):
                return None
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        _call_geometry_nodes(
            'update_effect_animation_setting_cb', self, context, effect_id, suffix
        )
        return None
    return _update


def _register_effect_animation_properties():
    for effect_id in _EFFECT_ANIMATION_IDS:
        _FBP_OBJECT_RNA.assign(
            _effect_animation_property_name(effect_id, 'evolve'),
            BoolProperty(
                name="Evolve", default=False,
                description="Animate the preferred procedural parameter with deterministic non-repeating noise",
                update=_make_effect_animation_update_callback(effect_id, 'evolve'),
            ),
        )
        _FBP_OBJECT_RNA.assign(
            _effect_animation_property_name(effect_id, 'speed'),
            FloatProperty(
                name="Speed", default=1.0, min=-20.0, max=20.0,
                description="Multiplier applied to Evolution. Zero freezes it; negative values reverse the progression",
                update=_make_effect_animation_update_callback(effect_id, 'speed'),
            ),
        )
        _FBP_OBJECT_RNA.assign(
            _effect_animation_property_name(effect_id, 'step'),
            IntProperty(
                name="Stepped", default=4, min=1, max=240,
                description="Number of frames held before a new procedural value is generated. Set to 1 for a new value every frame",
                update=_make_effect_animation_update_callback(effect_id, 'step'),
            ),
        )
        _FBP_OBJECT_RNA.assign(
            _effect_animation_property_name(effect_id, 'seed'),
            IntProperty(
                name="Seed", default=0, min=0, max=999999,
                description="Select the deterministic infinite procedural-noise stream",
                update=_make_effect_animation_update_callback(effect_id, 'seed'),
            ),
        )
        _FBP_OBJECT_RNA.assign(
            _effect_animation_property_name(effect_id, 'unique'),
            BoolProperty(
                name="Unique per Layer", default=False,
                description="Give every layer a persistent independent procedural-noise stream",
                update=_make_effect_animation_update_callback(effect_id, 'unique'),
            ),
        )
        _FBP_OBJECT_RNA.assign(
            _effect_animation_property_name(effect_id, 'layer_seed'),
            IntProperty(
                name="Internal Layer Seed", default=0, min=0, max=2147483647,
                description="Persistent internal seed used by Unique per Layer",
                options={'HIDDEN'},
            ),
        )



def _fbp_mask_source_poll(owner, candidate):
    """Expose only compatible FBP media rigs from the owner's Scene."""
    try:
        if candidate is None or candidate == owner:
            return False
        if (
            not bool(getattr(candidate, "is_fbp_control", False))
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


def _fbp_layer_blend_source_poll(owner, candidate):
    """Expose image-backed and flat Color Plane sources in the same Scene."""
    try:
        if candidate is None or candidate == owner:
            return False
        if (
            not bool(getattr(candidate, "is_fbp_control", False))
            or getattr(candidate, "fbp_plane_target", None) is None
        ):
            return False
        owner_scenes = tuple(getattr(owner, "users_scene", ()) or ())
        candidate_scenes = tuple(getattr(candidate, "users_scene", ()) or ())
        if owner_scenes and candidate_scenes:
            owner_keys = {int(scene.as_pointer()) for scene in owner_scenes}
            if not any(int(scene.as_pointer()) in owner_keys for scene in candidate_scenes):
                return False
        from .layers import fbp_layer_is_blend_source
        return bool(fbp_layer_is_blend_source(candidate))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
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
    # collection. Blender 5.2 can become unstable while Undo frees such nested
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
        # Aggressive branch: current layer rows keep object names synchronized.
        # Do not scan every Object by runtime token on each UI access.
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
    if fbp_undo_guard_active() or fbp_is_silent_property_update(self):
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
        getattr(self, 'instance_id', ''), default=True,
    ))


def set_effect_item_visible(self, value):
    rig = getattr(self, "id_data", None)
    _call_geometry_nodes(
        'fbp_effect_item_visible_set', rig, getattr(self, 'effect_id', ''),
        bool(value), getattr(self, 'instance_id', ''), default=False,
    )



def update_effect_instance_channel_cb(self, context):
    if fbp_undo_guard_active() or fbp_is_silent_property_update(self):
        return None
    _call_geometry_nodes(
        'update_effect_instance_channel_cb', self, context, default=False
    )
    return None


def _make_effect_instance_animation_update_callback(suffix):
    def _update(self, context):
        if fbp_undo_guard_active() or fbp_is_silent_property_update(self):
            return None
        _call_geometry_nodes(
            'update_effect_instance_animation_setting_cb',
            self, context, suffix, default=False,
        )
        return None
    return _update


class FBP_EffectInstanceChannel(PropertyGroup):
    """Stable, keyframeable value owned by one concrete effect instance.

    Entries are tombstoned instead of removed so Blender F-Curve data paths do
    not change when effects are reordered or another instance is deleted.
    """

    active: BoolProperty(default=True, options={'HIDDEN'})
    effect_id: StringProperty(default='', options={'HIDDEN'})
    instance_id: StringProperty(default='', options={'HIDDEN'})
    property_name: StringProperty(default='', options={'HIDDEN'})
    socket_name: StringProperty(default='', options={'HIDDEN'})
    value_kind: EnumProperty(
        items=(
            ('FLOAT', 'Float', ''),
            ('POSITIVE', 'Positive', ''),
            ('FACTOR', 'Factor', ''),
            ('ANGLE', 'Angle', ''),
            ('INT', 'Integer', ''),
            ('BOOL', 'Boolean', ''),
        ),
        default='FLOAT',
        options={'HIDDEN'},
    )
    float_value: FloatProperty(
        name='Value', default=0.0, min=-1000000.0, max=1000000.0,
        update=update_effect_instance_channel_cb,
    )
    positive_value: FloatProperty(
        name='Value', default=0.0, min=0.0, max=1000000.0,
        update=update_effect_instance_channel_cb,
    )
    factor_value: FloatProperty(
        name='Value', default=0.0, min=0.0, max=1.0, subtype='FACTOR',
        update=update_effect_instance_channel_cb,
    )
    angle_value: FloatProperty(
        name='Value', default=0.0, min=-1000.0, max=1000.0, subtype='ANGLE',
        update=update_effect_instance_channel_cb,
    )
    int_value: IntProperty(
        name='Value', default=0, min=-2147483647, max=2147483647,
        update=update_effect_instance_channel_cb,
    )
    bool_value: BoolProperty(
        name='Value', default=False, update=update_effect_instance_channel_cb,
    )


class FBP_EffectInstanceAnimation(PropertyGroup):
    """Procedural animation settings for one concrete MULTI instance."""

    active: BoolProperty(default=True, options={'HIDDEN'})
    effect_id: StringProperty(default='', options={'HIDDEN'})
    instance_id: StringProperty(default='', options={'HIDDEN'})
    evolve: BoolProperty(
        name='Animate', default=False,
        description='Animate this concrete effect instance independently',
        update=_make_effect_instance_animation_update_callback('evolve'),
    )
    speed: FloatProperty(
        name='Speed', default=1.0, min=-20.0, max=20.0,
        description='Evolution speed for this concrete effect instance',
        update=_make_effect_instance_animation_update_callback('speed'),
    )
    step: IntProperty(
        name='Stepped', default=4, min=1, max=240,
        description='Number of timeline frames held by this instance',
        update=_make_effect_instance_animation_update_callback('step'),
    )
    seed: IntProperty(
        name='Seed', default=0, min=0, max=999999,
        description='Deterministic procedural stream used by this instance',
        update=_make_effect_instance_animation_update_callback('seed'),
    )
    unique: BoolProperty(
        name='Unique per Layer', default=False,
        description='Offset this instance by the persistent seed of its layer',
        update=_make_effect_instance_animation_update_callback('unique'),
    )
    layer_seed: IntProperty(
        name='Internal Layer Seed', default=0, min=0, max=2147483647,
        options={'HIDDEN'},
    )
    amount: FloatProperty(
        name='Evolution Amount', default=1.0, min=-100000.0, max=100000.0,
        options={'HIDDEN'},
        update=_make_effect_instance_animation_update_callback('amount'),
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
    row_uid: StringProperty(
        name="Effect Stack Row ID",
        description="Deterministic runtime identity used to preserve selection anchors when effect rows are rebuilt or reordered",
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    instance_id: StringProperty(
        name="Effect Instance ID",
        description="Persistent identity of the concrete effect instance represented by this stack row",
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
        name="Visible",
        description="Show or hide this effect everywhere, in both the viewport and final render. Click-drag across eye icons to paint visibility",
        get=get_effect_item_visible,
        set=set_effect_item_visible,
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
    duration:    IntProperty(
        name="Duration",
        description="Number of timeline frames this image/frame stays visible. Dragging is limited to 128; type a larger value when needed",
        default=2,
        min=1,
        soft_max=128,
        update=update_image_duration_cb,
    )
    is_selected: BoolProperty(name="Select", description="Include this frame in frame-list actions such as duplicate, split, sort or delete", default=True)
    is_empty:    BoolProperty(name="Empty", description="Marks this row as a transparent placeholder frame", default=False)
    filepath:    StringProperty(name="File", description="External image or video path used by this logical frame. Frame By Plane links the source and never deletes the file from disk.", subtype='FILE_PATH', default="")
    image:        PointerProperty(name="Image", description="Persistent Blender Image used by Cutout Plane entries", type=bpy.types.Image)
    image_name:   StringProperty(name="Image Data-Block", description="Fallback datablock name for Cutout Plane compatibility", default="")
    managed_image: BoolProperty(name="Managed Buffer", description="Allow Frame By Plane to release inactive CPU/GPU buffers for this external Cutout image", default=False)
    source_width: IntProperty(name="Source Width", description="Cached source width used without decoding the image again", default=0, min=0)
    source_height: IntProperty(name="Source Height", description="Cached source height used without decoding the image again", default=0, min=0)
    stable_id:    StringProperty(name="Stable ID", description="Persistent unique identifier for this frame or drawing row, used to preserve selection, active state and animation references when lists are reordered, duplicated or rebuilt.", default="")
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
            ('GROUP', "Collection", "Collection header row"),
            ('LAYER', "Layer", "Frame By Plane layer row"),
            ('GP_CANVAS', "Grease Pencil", "Grease Pencil canvas linked to a Frame By Plane layer"),
            ('GP_LAYER', "Grease Pencil Layer", "Internal layer inside a Grease Pencil canvas"),
        ],
        default='LAYER'
    )
    name: StringProperty(description="User-facing name stored for this Frame By Plane list entry.", name="Display Name", default="")
    collection_name: StringProperty(description="Name of the Blender or pending setup collection targeted by this action.", name="Collection Name", default="")
    rig_name: StringProperty(description="Name of the Frame By Plane control rig targeted by this action. Stored only long enough to resolve the object safely.", name="Rig Name", default="")
    canvas_name: StringProperty(description="Name of the linked Grease Pencil canvas represented by this virtual layer row.", name="Canvas Name", default="")
    gp_layer_name: StringProperty(description="Name of the internal Grease Pencil layer represented by this virtual row.", name="Grease Pencil Layer Name", default="")
    layer_index: IntProperty(description="Index of the corresponding Frame By Plane layer in the scene runtime layer list.", name="Layer Index", default=-1)
    depth: IntProperty(description="Cached hierarchy indentation depth used to draw this tree row.", name="Depth", default=0, min=0)
    layer_count: IntProperty(description="Cached number of Frame By Plane plane layers contained in this collection row.", name="Plane Layer Count", default=0, min=0)
    gp_count: IntProperty(description="Cached number of Grease Pencil drawing layers contained in this collection row.", name="Grease Pencil Layer Count", default=0, min=0)
    child_count: IntProperty(description="Cached number of direct child collections represented by this collection.", name="Child Collection Count", default=0, min=0)
    list_domain: EnumProperty(
        name="Layer List Domain",
        description="Runtime list ownership used to keep Plane and Grease Pencil collection trees completely separate",
        items=[
            ('PLANES', "Planes", "Collection belongs to the plane Layer List"),
            ('GP', "Grease Pencil", "Collection belongs to the Grease Pencil Layer List"),
        ],
        default='PLANES',
        options={'SKIP_SAVE'},
    )
    empty_managed_path: BoolProperty(
        name="Empty Managed Group Path",
        description="Whether this collection row is part of the visible path to an empty Frame By Plane group",
        default=False,
        options={'SKIP_SAVE'},
    )
    collection_collapsed: BoolProperty(name="Collection Collapsed", default=False, options={'SKIP_SAVE'})
    collection_visible: BoolProperty(name="Collection Visible", default=True, options={'SKIP_SAVE'})
    collection_solo: BoolProperty(name="Collection Solo", default=False, options={'SKIP_SAVE'})
    collection_holdout: BoolProperty(name="Collection Holdout", default=False, options={'SKIP_SAVE'})
    collection_plane_locked: BoolProperty(name="Collection Plane Locked", default=True, options={'SKIP_SAVE'})
    collection_locked: BoolProperty(name="Collection Locked", default=False, options={'SKIP_SAVE'})
    collection_selected: BoolProperty(name="Collection Selected", default=False, options={'SKIP_SAVE'})
    collection_color_tag: StringProperty(name="Collection Color Tag", default="NONE", options={'SKIP_SAVE'})


class FBP_PendingPlaneItem(PropertyGroup):
    stable_id: StringProperty(
        name="Setup Row ID",
        description="Persistent identity used to preserve the active Multiplane Setup row after sorting, collapse, reorder or deletion",
        default="",
        options={'HIDDEN'},
    )
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
    fbp_color_tag: EnumProperty(name="Color Tag", description="Color tag to assign to the generated rig and collection", items=fbp_color_tag_enum_items, default=0)
    source_from_layered: BoolProperty(
        name="Layered Document Source",
        description="Internal flag indicating that this setup row was extracted from a layered source document",
        default=False,
    )
    source_document: StringProperty(
        name="Source Document",
        description="Original layered document that produced this cached image",
        subtype='FILE_PATH',
        default="",
    )
    source_layer_path: StringProperty(
        name="Source Layer Path",
        description="Original group and layer path inside the layered document",
        default="",
    )
    source_layer_kind: StringProperty(
        name="Source Layer Type",
        description="Original layered-document source type such as PSD pixel, smart object, Procreate pixel or preview fallback",
        default="",
    )
    source_layer_visible: BoolProperty(
        name="Source Layer Visible",
        description="Visibility stored in the original layered document",
        default=True,
    )
    source_layer_opacity: FloatProperty(
        name="Source Layer Opacity",
        description="Effective opacity inherited from the source layer and its parent groups",
        default=1.0, min=0.0, max=1.0,
    )
    source_blend_mode: StringProperty(
        name="Source Blend Mode",
        description="Source blend mode stored for diagnostics and future material mapping",
        default="NORMAL",
    )
    source_is_clipping: BoolProperty(
        name="Source Clipping Layer",
        description="Original layered-document layer was clipped to the alpha of the layer below",
        default=False,
    )
    source_mask_file: StringProperty(
        name="Source Layer Mask",
        description="Extracted full-canvas raster mask associated with this source layer",
        subtype='FILE_PATH',
        default="",
    )
    source_blend_supported: BoolProperty(
        name="Transfer Source Blend",
        description="Source blend mode has a supported Frame By Plane material mapping",
        default=False,
    )
    source_cache_key: StringProperty(
        name="Source Revision",
        description="Revision key of the layered document used to create this cached PNG",
        default="",
    )
    source_preset: StringProperty(
        name="Import Preset",
        description="Source workflow preset used to prepare this Multiplane Setup row",
        default="",
    )
    source_frame_numbers_str: StringProperty(
        name="Source Frame Numbers",
        description="Internal ordered source drawing/frame numbers preserved by animation export presets",
        default="",
    )
    source_durations_str: StringProperty(
        name="Source Exposures",
        description="Internal per-frame exposure durations prepared before Multiplane generation",
        default="",
    )
    source_flattened_group: BoolProperty(
        name="Flattened PSD Group",
        description="Whether this plane represents a complex PSD group flattened to preserve its appearance",
        default=False,
    )
    source_warnings: StringProperty(
        name="Layer Import Warnings",
        description="Compatibility notes produced while extracting this PSD, PSB or Procreate layer",
        default="",
    )


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
    stable_id: StringProperty(
        name="Report Row ID",
        description="Runtime identity used to preserve the active generation-report row across refreshes",
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    rig_name: StringProperty(description="Name of the Frame By Plane control rig targeted by this action. Stored only long enough to resolve the object safely.", name="Rig Name", default="", options={'SKIP_SAVE'})
    display_name: StringProperty(description="User-facing sequence name shown in the generation repair report.", name="Sequence", default="", options={'SKIP_SAVE'})
    message: StringProperty(description="Diagnostic message describing the sequence or generation problem.", name="Issue", default="", options={'SKIP_SAVE'})
    preview_files: StringProperty(description="Compact list of example filenames shown for this generation problem.", name="Files", default="", options={'SKIP_SAVE'})
    is_renamed: BoolProperty(description="Whether this reported sequence has already been repaired by the safe rename operation.", name="Renamed", default=False, options={'SKIP_SAVE'})
    selected: BoolProperty(
        name="Selected",
        description="Include this report row in a multi-row selection",
        default=False,
        options={'SKIP_SAVE'},
    )


# SECTION 02 - Scene / Collection / Object property registration #


def update_experimental_compositor_cb(self, _context):
    """Keep preview-only sections inaccessible while their gate is disabled."""
    try:
        if (
            not bool(getattr(self, "fbp_experimental_compositor", False))
            and str(getattr(self, "fbp_settings_section", "PROJECT") or "PROJECT") == "COMPOSITOR"
        ):
            self.fbp_settings_section = 'MAINTENANCE'
    except FBP_DATA_ERRORS:
        pass

def register_properties():
    _FBP_SCENE_RNA.fbp_last_directory = StringProperty(name="Last Folder", description="Last folder used by Frame By Plane file browsers", subtype='DIR_PATH', default="")
    _FBP_SCENE_RNA.fbp_effect_mask_edit_target = StringProperty(
        name="Effect Mask Editor",
        description="Transient 2D effect whose local masks are expanded below the Effects Stack",
        default="", options={'SKIP_SAVE'},
    )
    _FBP_SCENE_RNA.fbp_project_path = StringProperty(
        name="Project Folder", description="Root folder used for project import, relinking, generated render folders and health checks", subtype='DIR_PATH', default="", update=update_render_output_path_cb)
    _FBP_SCENE_RNA.fbp_parent_import_path = StringProperty(
        name="Project Folder", description="Root folder currently represented by Multiplane Setup. It is used for relative paths, rescanning and relinking without copying source media.", subtype='DIR_PATH')
    _FBP_SCENE_RNA.fbp_cam_ratio = EnumProperty(description="Select the output aspect-ratio preset used when Frame By Plane creates or configures a camera. The preset updates render width and height while Custom keeps the current resolution.",
        name="Camera Ratio",
        items=CAMERA_RATIO_ITEMS,
        default='4_3')
    _FBP_SCENE_RNA.fbp_camera_projection = EnumProperty(
        name="Camera Projection",
        description="Projection used by newly generated Frame By Plane cameras",
        items=CAMERA_PROJECTION_ITEMS,
        default='PERSP')
    _FBP_SCENE_RNA.fbp_camera_lens = FloatProperty(
        name="Perspective Lens",
        description="Lens in millimeters used by newly generated perspective cameras",
        default=50.0, min=1.0, max=500.0)
    _FBP_SCENE_RNA.fbp_camera_ortho_scale = FloatProperty(
        name="Orthographic Scale",
        description="View scale used by newly generated orthographic cameras",
        default=10.0, min=0.001, soft_max=100.0)
    _FBP_SCENE_RNA.fbp_camera_clip_start = FloatProperty(
        name="Clip Start", description="Near clipping distance for newly generated cameras",
        default=0.1, min=0.001, soft_max=10.0, unit='LENGTH')
    _FBP_SCENE_RNA.fbp_camera_clip_end = FloatProperty(
        name="Clip End", description="Far clipping distance for newly generated cameras",
        default=1000.0, min=1.0, soft_max=10000.0, unit='LENGTH')
    _FBP_SCENE_RNA.fbp_show_previews = BoolProperty(
        name="List Thumbnails",
        description="Show thumbnails inside layer, frame and Cutout library lists; the large active Cutout preview always remains visible",
        default=False,
        update=update_show_previews_cb,
    )
    _FBP_SCENE_RNA.fbp_thumbnail_background_enabled = BoolProperty(
        name="Thumbnail Background",
        description="Place all Frame By Plane image thumbnails over the selected background color",
        default=False,
    )
    _FBP_SCENE_RNA.fbp_thumbnail_background_color = FloatVectorProperty(
        name="Thumbnail Background Color",
        description="Color shown behind transparent pixels in all Frame By Plane image thumbnails",
        subtype='COLOR', size=3, min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0),
    )
    _FBP_SCENE_RNA.fbp_show_color_previews = BoolProperty(name="Color Previews", description="Show color/gradient chips in Layer and Frame lists instead of generic procedural icons", default=True)
    _FBP_SCENE_RNA.fbp_sort_layers_alpha = BoolProperty(
        name="A-Z",
        description="Sort layers and collections alphabetically instead of by camera distance",
        default=False)
    _FBP_SCENE_RNA.fbp_auto_clean_orphans = BoolProperty(
        name="Auto-clean Orphan Frame By Plane Objects",
        description="After normal deletion, remove orphan FBP planes and safely purge unused FBP mesh/material datablocks. Image datablocks and files on disk are never deleted automatically",
        default=True)
    _FBP_SCENE_RNA.fbp_show_create_tools = BoolProperty(name="Create Tools", description="Show additional tools in the current creation workflow", default=False)
    _FBP_SCENE_RNA.fbp_sequence_show_animation = BoolProperty(
        name="Playback",
        description="Expand the Sequence panel playback controls for all Frame By Plane layers in this scene",
        default=True,
    )
    _FBP_SCENE_RNA.fbp_alpha_render_method = EnumProperty(
        name="Alpha Rendering",
        description="Surface transparency method used by Frame By Plane materials. Auto selects depth-safe Dithered alpha",
        items=ALPHA_RENDER_METHOD_ITEMS,
        default='AUTO',
        update=update_alpha_render_method_cb,
    )
    _FBP_SCENE_RNA.fbp_render_output_dir = StringProperty(
        name="Render Folder",
        description="Root output folder synchronized with Blender's native Render File Path",
        subtype='DIR_PATH',
        default="",
        update=update_render_output_path_cb,
    )
    _FBP_SCENE_RNA.fbp_render_show_folder = BoolProperty(
        name="Folder",
        description="Expand the render-folder builder",
        default=True,
    )
    _FBP_SCENE_RNA.fbp_render_show_file_naming = BoolProperty(
        name="File Naming",
        description="Expand the render filename builder",
        default=True,
    )
    _FBP_SCENE_RNA.fbp_render_show_file_extension = BoolProperty(
        name="File Extension",
        description="Expand file format, transparency and image sampling settings",
        default=True,
    )
    _FBP_SCENE_RNA.fbp_render_show_frame_range = BoolProperty(
        name="Frame Range",
        description="Expand animation start, end and step settings",
        default=True,
    )
    _FBP_SCENE_RNA.fbp_render_folder_builder_mode = EnumProperty(
        name="Folder Source",
        description="Select an exact output folder or generate one inside Project Folder",
        items=RENDER_FOLDER_BUILDER_MODE_ITEMS,
        default='GENERATE',
        update=update_render_output_path_cb,
    )
    _FBP_SCENE_RNA.fbp_render_folder_prefix = StringProperty(
        name="Prefix",
        description="Optional prefix for the generated folder; empty values are skipped",
        default="",
        update=update_render_output_path_cb,
    )
    _FBP_SCENE_RNA.fbp_render_folder_name = StringProperty(
        name="Name",
        description="Generated folder name; empty uses the current .blend project filename",
        default="",
        update=update_render_output_path_cb,
    )
    _FBP_SCENE_RNA.fbp_render_folder_tag = EnumProperty(
        name="Production Tag",
        description="Optional TEST, ANIM, FINAL or PREV tag appended to the generated folder name",
        items=RENDER_FOLDER_TAG_ITEMS,
        default='TEST',
        update=update_render_output_path_cb,
    )
    _FBP_SCENE_RNA.fbp_render_folder_builder_suffix = StringProperty(
        name="Suffix",
        description="Optional suffix for the generated folder; empty values are skipped",
        default="",
        update=update_render_output_path_cb,
    )
    _FBP_SCENE_RNA.fbp_render_folder_mode = EnumProperty(
        name="Destination",
        description="Write directly into the selected folder or create a TEST, FINAL or custom subfolder",
        items=RENDER_FOLDER_MODE_ITEMS,
        default='ROOT',
        update=update_render_output_path_cb,
    )
    _FBP_SCENE_RNA.fbp_render_folder_suffix = StringProperty(
        name="Folder Suffix",
        description="Optional suffix appended to TEST, FINAL and custom render folders",
        default="",
        update=update_render_output_path_cb,
    )
    _FBP_SCENE_RNA.fbp_render_test_number = IntProperty(
        name="Test Number",
        description="Number used by the TEST destination folder",
        default=1,
        min=0,
        max=999999,
        update=update_render_output_path_cb,
    )
    _FBP_SCENE_RNA.fbp_render_test_digits = IntProperty(
        name="Test Digits",
        description="Zero-padding used by the TEST folder number",
        default=2,
        min=1,
        max=6,
        update=update_render_output_path_cb,
    )
    _FBP_SCENE_RNA.fbp_render_auto_increment_test = BoolProperty(
        name="New TEST Folder per Render",
        description="Before a background render, scan the root folder once and select the next available TEST number",
        default=True,
    )
    _FBP_SCENE_RNA.fbp_render_custom_folder = StringProperty(
        name="Custom Folder",
        description="Custom subfolder created inside the selected render root",
        default="Render",
        update=update_render_output_path_cb,
    )
    _FBP_SCENE_RNA.fbp_render_filename_mode = EnumProperty(
        name="File Naming",
        description="Use Blender's native filename pattern or the Frame By Plane token builder",
        items=RENDER_FILENAME_MODE_ITEMS,
        default='COMPOSE',
        update=update_render_output_path_cb,
    )
    _FBP_SCENE_RNA.fbp_render_native_pattern = StringProperty(
        name="Native Pattern",
        description="Filename pattern read directly from Blender; # characters define frame-number padding",
        default="frame_####",
        update=update_render_output_path_cb,
    )
    _FBP_SCENE_RNA.fbp_render_name_source = EnumProperty(
        name="Base Name",
        description="Choose the principal filename component",
        items=RENDER_NAME_SOURCE_ITEMS,
        default='DOCUMENT',
        update=update_render_output_path_cb,
    )
    _FBP_SCENE_RNA.fbp_render_custom_name = StringProperty(
        name="Custom Name",
        description="Custom base filename used by the render name builder",
        default="",
        update=update_render_output_path_cb,
    )
    _FBP_SCENE_RNA.fbp_render_prefix = StringProperty(
        name="Prefix",
        description="Optional component placed before the base filename",
        default="",
        update=update_render_output_path_cb,
    )
    _FBP_SCENE_RNA.fbp_render_letter = StringProperty(
        name="Start from Letter",
        description="Custom starting letter or short take identifier used by the filename token",
        default="A",
        update=update_render_output_path_cb,
    )
    _FBP_SCENE_RNA.fbp_render_token_mode = EnumProperty(
        name="Token",
        description="Add a starting letter, number or both to the filename",
        items=RENDER_TOKEN_MODE_ITEMS,
        default='NONE',
        update=update_render_output_path_cb,
    )
    _FBP_SCENE_RNA.fbp_render_token_position = EnumProperty(
        name="Position",
        description="Place the letter/number token before Prefix or after Suffix",
        items=RENDER_TOKEN_POSITION_ITEMS,
        default='BEFORE',
        update=update_render_output_path_cb,
    )
    _FBP_SCENE_RNA.fbp_render_use_number = BoolProperty(
        name="Number",
        description="Add a fixed padded job, version or take number before the frame number",
        default=False,
        update=update_render_output_path_cb,
    )
    _FBP_SCENE_RNA.fbp_render_number = IntProperty(
        name="Number",
        description="Fixed serial, version or take number added to every output filename",
        default=1,
        min=0,
        max=99999999,
        update=update_render_output_path_cb,
    )
    _FBP_SCENE_RNA.fbp_render_number_digits = IntProperty(
        name="Digits",
        description="Zero-padding used by the fixed number token",
        default=1,
        min=1,
        max=8,
        update=update_render_output_path_cb,
    )
    _FBP_SCENE_RNA.fbp_render_suffix = StringProperty(
        name="Suffix",
        description="Optional component placed after the frame number or before it, depending on Number Position",
        default="",
        update=update_render_output_path_cb,
    )
    _FBP_SCENE_RNA.fbp_render_separator = EnumProperty(
        name="Separator",
        description="Separator inserted between active filename components",
        items=RENDER_SEPARATOR_ITEMS,
        default='DASH',
        update=update_render_output_path_cb,
    )
    _FBP_SCENE_RNA.fbp_render_frame_digits = IntProperty(
        name="Frame Digits",
        description="Number of # characters used for the native Blender frame number",
        default=4,
        min=1,
        max=8,
        update=update_render_output_path_cb,
    )
    _FBP_SCENE_RNA.fbp_render_frame_position = EnumProperty(
        name="Number Position",
        description="Place the frame number before the suffix or at the end of the filename",
        items=RENDER_FRAME_POSITION_ITEMS,
        default='BEFORE_SUFFIX',
        update=update_render_output_path_cb,
    )
    _FBP_SCENE_RNA.fbp_render_output_kind = EnumProperty(
        name="Output Type",
        description="Render images normally or render a safe PNG sequence and automatically encode an MP4",
        items=RENDER_OUTPUT_KIND_ITEMS,
        default='IMAGES',
        update=update_render_output_path_cb,
    )
    _FBP_SCENE_RNA.fbp_render_ffmpeg_executable = StringProperty(
        name="FFmpeg",
        description="Optional path to ffmpeg.exe; leave empty to search the system PATH and common installation folders",
        subtype='FILE_PATH',
        default="",
    )
    _FBP_SCENE_RNA.fbp_background_render_keep_log = BoolProperty(
        name="Keep Successful Log",
        description="Copy the completed background-render log and job-state JSON into the output folder; failed and cancelled jobs are always preserved",
        default=False,
    )
    _FBP_SCENE_RNA.fbp_background_render_running = BoolProperty(description="Runtime flag indicating that a Frame By Plane background-render process is currently active. This value is managed automatically and is not saved in the .blend file.", name="Background Render Running", default=False, options={'SKIP_SAVE'})
    _FBP_SCENE_RNA.fbp_background_render_status = StringProperty(description="Human-readable runtime status reported by the active Frame By Plane background renderer, including idle, rendering, completed, stopped or error states.", name="Background Render Status", default="Idle", options={'SKIP_SAVE'})
    _FBP_SCENE_RNA.fbp_background_render_progress = IntProperty(description="Number of frames confirmed as completed by the current Frame By Plane background-render process.", name="Rendered Frames", default=0, min=0, options={'SKIP_SAVE'})
    _FBP_SCENE_RNA.fbp_background_render_total = IntProperty(description="Total number of frames scheduled for the current Frame By Plane background render.", name="Total Frames", default=0, min=0, options={'SKIP_SAVE'})
    _FBP_SCENE_RNA.fbp_background_render_output_dir = StringProperty(description="Resolved output directory used by the active background-render process. This runtime path is updated automatically and is not stored in the project.", name="Output Folder", default="", subtype='DIR_PATH', options={'SKIP_SAVE'})
    _FBP_SCENE_RNA.fbp_background_render_current_frame = IntProperty(description="Frame currently reported by the isolated Blender render process.", name="Current Render Frame", default=0, options={'SKIP_SAVE'})
    _FBP_SCENE_RNA.fbp_background_render_eta = StringProperty(description="Estimated remaining render time calculated from the most recent completed frames.", name="Render ETA", default="", options={'SKIP_SAVE'})
    _FBP_SCENE_RNA.fbp_background_render_last_log = StringProperty(description="Path to the last preserved background-render failure log.", name="Last Render Log", default="", subtype='FILE_PATH', options={'SKIP_SAVE'})
    _FBP_SCENE_RNA.fbp_generation_rename_items = CollectionProperty(description="Runtime list of problematic image sequences reported during generation and available for safe filename repair.", type=FBP_GenerationRenameItem, options={'SKIP_SAVE'})
    _FBP_SCENE_RNA.fbp_generation_rename_index = IntProperty(name="Rename Sequence Index", description="Active problematic sequence in the generation rename list", default=0, min=0, options={'SKIP_SAVE'})
    _FBP_SCENE_RNA.fbp_auto_collection_color_variants = BoolProperty(
        name="Collection Color Variants",
        description="Give layers small viewport color variations based on their collection color",
        default=True,
        update=update_collection_color_variants_cb,
    )
    _FBP_SCENE_RNA.fbp_layers = CollectionProperty(description="Runtime mirror of Frame By Plane rig layers in the active scene, used by the Layers tree and multi-layer controls.", type=FBP_LayerItem, options={'SKIP_SAVE'})
    _FBP_SCENE_RNA.fbp_layer_stack_index = IntProperty(
        name="Layer Index", description="Active layer row in the Frame By Plane layer list", default=0, update=update_layer_stack_index_cb)
    _FBP_SCENE_RNA.fbp_layer_tree_rows = CollectionProperty(description="Flattened runtime rows used to display collections and layers in the Frame By Plane Layers tree without rebuilding hierarchy data for every visible row.", type=FBP_LayerTreeRowItem, options={'SKIP_SAVE'})
    _FBP_SCENE_RNA.fbp_layer_tree_rows_idx = IntProperty(name="Layer Tree Row", description="Runtime index of the active visible Layer Tree row. Frame By Plane keeps it synchronized with the selected rig while collections are collapsed or reordered.", default=0, options={'SKIP_SAVE'})
    _FBP_SCENE_RNA.fbp_layer_tree_signature = StringProperty(description="Internal cache signature used to rebuild the Layers tree only when its structure actually changes.", name="Layer Tree Signature", default="", options={'SKIP_SAVE'})
    _FBP_SCENE_RNA.fbp_pending_open_collections = StringProperty(description="Internal serialized set of Multiplane Setup collections currently expanded in the preview tree.", name="Open Setup Collections", default="", options={'SKIP_SAVE'})
    _FBP_SCENE_RNA.fbp_gradient_preview_material_name = StringProperty(description="Internal name of the temporary material used to generate procedural gradient thumbnails in the user interface.", name="Gradient Preview Material", default="", options={'SKIP_SAVE'})
    _FBP_SCENE_RNA.fbp_creation_mode = EnumProperty(description="Choose the Frame By Plane type shown in Create: Single Plane, Video Plane, Multiplane, Cutout Plane, Color Plane, Gradient Plane or Holdout Plane.",
        name="Mode",
        items=CREATION_MODE_ITEMS,
        default='SINGLE')
    _FBP_SCENE_RNA.fbp_effects_view = EnumProperty(
        name="Effect Type",
        description="Choose whether the Effects panel shows image effects, masks or mesh effects",
        items=(
            ('2D', "Image Effects", "Show Base and image-processing shader effects", fbp_icon("SHADERFX"), 0),
            ('MASK', "Mask", "Show Alpha Matte, Luma Matte and future mask-stack effects", fbp_icon("MOD_MASK"), 1),
            ('3D', "Mesh Effects", "Show Geometry Nodes and mesh effects", fbp_icon("MOD_SCATTER_ON_SURFACE"), 2),
        ),
        default='2D',
    )
    _FBP_SCENE_RNA.fbp_pending_planes = CollectionProperty(description="Pending media layers and collections prepared in Multiplane Setup before scene objects are generated.", type=FBP_PendingPlaneItem)
    _FBP_SCENE_RNA.fbp_pending_planes_idx = IntProperty(name="Setup Layer Index", description="Index of the active pending Multiplane Setup entry, used by edit, move, replace and remove actions before scene generation.", default=0)
    _FBP_SCENE_RNA.fbp_pending_tree_rows = CollectionProperty(description="Flattened runtime rows used to display the collapsible Multiplane Setup hierarchy efficiently.", type=FBP_PendingTreeRowItem, options={'SKIP_SAVE'})
    _FBP_SCENE_RNA.fbp_pending_tree_rows_idx = IntProperty(name="Setup Tree Row", description="Active visual row in the Multiplane Setup tree UIList", default=0, options={'SKIP_SAVE'})
    _FBP_SCENE_RNA.fbp_pending_collection_name = StringProperty(name="Collection", description="Name used when creating a new Multiplane Setup collection", default="New Collection")
    _FBP_SCENE_RNA.fbp_layered_report_source = StringProperty(name="Layered Import Source", description="Original PSD, PSB or Procreate document represented by the current Multiplane Setup report", subtype='FILE_PATH', default="")
    _FBP_SCENE_RNA.fbp_layered_report_format = StringProperty(name="Layered Import Format", description="Source layered-document format used by the current import report", default="")
    _FBP_SCENE_RNA.fbp_layered_report_backend = StringProperty(name="Layered Import Backend", description="Decoder version used to extract the current layered-document setup", default="")
    _FBP_SCENE_RNA.fbp_layered_report_cache_reused = BoolProperty(name="Reused Layer Cache", description="Whether the current layered import reused a previously extracted PNG cache", default=False)
    _FBP_SCENE_RNA.fbp_layered_report_fallback_preview = BoolProperty(name="Flattened Preview Fallback", description="Whether the layered document had to fall back to one flattened preview image", default=False)
    _FBP_SCENE_RNA.fbp_layered_report_skipped_layers = IntProperty(name="Skipped Source Layers", description="Number of source layers that could not produce an importable image", default=0, min=0)
    _FBP_SCENE_RNA.fbp_layered_report_flattened_groups = IntProperty(name="Flattened Source Groups", description="Number of complex source groups flattened to preserve their appearance", default=0, min=0)
    _FBP_SCENE_RNA.fbp_layered_report_merged_clipping = IntProperty(name="Baked Clipping Layers", description="Number of clipping layers baked into raster fallbacks instead of transferred as editable clipping", default=0, min=0)
    _FBP_SCENE_RNA.fbp_layered_report_decoded_layers = IntProperty(name="Decoded Source Layers", description="Number of independently decoded source layers", default=0, min=0)
    _FBP_SCENE_RNA.fbp_layered_report_transferred_blends = IntProperty(name="Transferred Blend Modes", description="Number of source blend modes mapped to Frame By Plane layer blending", default=0, min=0)
    _FBP_SCENE_RNA.fbp_layered_report_transferred_masks = IntProperty(name="Transferred Masks", description="Number of source masks extracted as editable Frame By Plane masks", default=0, min=0)
    _FBP_SCENE_RNA.fbp_layered_report_transferred_clipping = IntProperty(name="Transferred Clipping Layers", description="Number of source clipping relations transferred as editable Frame By Plane clipping", default=0, min=0)
    _FBP_SCENE_RNA.fbp_layered_report_unsupported_blends = IntProperty(name="Unsupported Blend Modes", description="Number of source blend modes preserved only as metadata because no reliable mapping was available", default=0, min=0)
    _FBP_SCENE_RNA.fbp_layered_report_warnings = StringProperty(name="Layered Import Warnings", description="Document-level compatibility notes from the current layered import", default="")
    _FBP_SCENE_RNA.fbp_pre_duration = IntProperty(
        name="Duration (Frames)", description="Default duration assigned to each imported image frame", default=2, min=1)
    _FBP_SCENE_RNA.fbp_pre_shadeless = BoolProperty(name="Shadeless", description="Use lightweight emission materials so image planes are not affected by scene lighting", default=True)
    _FBP_SCENE_RNA.fbp_import_crop_alpha = BoolProperty(
        name="Crop Transparent Borders",
        description=(
            "At import, crop only fully transparent outer pixels while preserving the original full-canvas pivot and layer alignment. "
            "Image sequences use the union of every frame; videos are left unchanged"
        ),
        default=False,
    )
    _FBP_SCENE_RNA.fbp_import_crop_alpha_padding = IntProperty(
        name="Alpha Crop Padding",
        description="Number of transparent pixels retained around the detected alpha bounds; zero crops exactly to every pixel with alpha greater than zero",
        default=0, min=0, soft_max=32, max=256,
    )
    _FBP_SCENE_RNA.fbp_pre_loop_mode = EnumProperty(description="Default playback behavior assigned to newly created animated Single Planes: play once, loop continuously or alternate forward and backward.",
        name="Playback",
        items=PLAYBACK_ITEMS,
        default='NONE')
    _FBP_SCENE_RNA.fbp_pre_interpolation = EnumProperty(description="Default texture filtering for newly generated planes. Pixel keeps hard nearest-neighbor edges; Smooth uses linear filtering for scaled artwork.",
        name="",
        items=INTERPOLATION_ITEMS,
        default='Closest')
    _FBP_SCENE_RNA.fbp_pre_orientation = EnumProperty(description="Default spatial orientation for newly generated planes. Vertical faces the camera as artwork; Horizontal places the plane parallel to the ground.",
        name="",
        items=ORIENTATION_ITEMS,
        default='VERT')
    _FBP_SCENE_RNA.fbp_gen_camera   = BoolProperty(name="Create Camera", description="Create or update a camera suitable for the generated multiplane setup", default=True)
    _FBP_SCENE_RNA.fbp_cam_pivot    = BoolProperty(name="Pivot on Camera", description="Move the 3D cursor to the camera pivot when creating a camera setup", default=True)
    _FBP_SCENE_RNA.fbp_layer_offset = FloatProperty(name="Plane Distance (m)", description="Distance between generated layers; imported top-level collections use a larger gap", default=0.2, min=0.001)
    _FBP_SCENE_RNA.fbp_auto_scale   = BoolProperty(name="Auto-Scale (Fit to Cam)", description="Scale generated planes to the camera frame using the image aspect ratio", default=True)
    _FBP_SCENE_RNA.fbp_camera_fit_source_aspect = BoolProperty(
        name="Camera Uses Source Aspect",
        description="When generating a Frame By Plane camera, match the output resolution to the first generated layer source aspect instead of a fixed preset",
        default=True,
    )
    _FBP_SCENE_RNA.fbp_pre_track_cam = BoolProperty(name="Track Camera on New Layers", description="Add camera tracking to newly generated Frame By Plane layers", default=False)
    _FBP_SCENE_RNA.fbp_settings_section = EnumProperty(
        name="Settings Section",
        description="Choose which Frame By Plane settings group to display",
        items=[
            ('PROJECT', "Project", "Project folder and file settings"),
            ('DISPLAY', "Display", "Layer-list thumbnails, sorting and scene workflow options"),
            ('CAMERA', "Camera", "Camera projection and frame ratio"),
            ('RENDER', "Render", "Background render controls"),
            ('MAINTENANCE', "Tools", "Repair, diagnostics and recovery tools for production projects"),
        ],
        default='PROJECT',
    )
    _FBP_SCENE_RNA.fbp_show_project_tools = BoolProperty(name="Project Import", description="Show advanced project and folder import controls", default=False)
    _FBP_SCENE_RNA.fbp_experimental_compositor = BoolProperty(
        name="Compositor Preview",
        description=(
            "Enable the preview Compositor Layers workflow. This feature is outside the Frame By Plane 7.1 LTS core scope; "
            "disable it to hide and prevent selection of that section"
        ),
        default=False,
        update=update_experimental_compositor_cb,
    )
    _FBP_SCENE_RNA.fbp_preview_procreate_import = BoolProperty(
        name="Procreate Preview",
        description="Enable the Procreate archive/tile decoder. This importer is outside the Frame By Plane 7.1 LTS core scope",
        default=False,
    )
    _FBP_SCENE_RNA.fbp_preview_generic_mesh_effects = BoolProperty(
        name="Generic Mesh Preview",
        description="Enable Frame By Plane Geometry Nodes effects on ordinary mesh objects. This workflow is outside the Frame By Plane 7.1 LTS core scope",
        default=False,
    )
    _FBP_SCENE_RNA.fbp_color_plane_type = EnumProperty(
        name="Plane Type",
        description="Choose what kind of camera-ratio plane to create",
        items=COLOR_PLANE_TYPE_ITEMS,
        default='CUSTOM')
    _FBP_SCENE_RNA.fbp_color_plane_color = FloatVectorProperty(
        name="Color", description="RGBA color used for the next generated Color Plane when Custom is selected. Alpha controls transparency and the source color is not color-managed outside Blender.", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0, 1.0), update=update_color_plane_color_cb)
    _FBP_SCENE_RNA.fbp_color_plane_preset = EnumProperty(
        name="Preset",
        description="Quick color preset for solid Color Plane creation",
        items=COLOR_PLANE_PRESET_ITEMS,
        default='CUSTOM', update=update_color_plane_preset_cb)
    _FBP_SCENE_RNA.fbp_color_plane_emission = BoolProperty(name="Emission", description="Use a lightweight emission shader for the color plane", default=True, update=update_scene_gradient_preview_cb)
    _FBP_SCENE_RNA.fbp_gradient_mode = EnumProperty(
        name="Gradient Mode", description="Choose a linear gradient across the plane or a centered radial gradient. The selection updates the procedural preview and newly generated Gradient Plane.",
        items=GRADIENT_MODE_ITEMS, default='LINEAR', update=update_scene_gradient_preview_cb)
    _FBP_SCENE_RNA.fbp_gradient_kind = EnumProperty(
        name="Gradient Type", description="Choose whether the gradient blends between two colors or changes alpha",
        items=GRADIENT_KIND_ITEMS, default='COLOR', update=update_scene_gradient_preview_cb)
    _FBP_SCENE_RNA.fbp_gradient_color_a = FloatVectorProperty(name="From", subtype='COLOR', size=4, min=0.0, max=1.0, description="Start color of the gradient ramp. In alpha mode this side is forced transparent", default=(1.0, 0.3686274509803922, 0.596078431372549, 1.0), update=update_scene_gradient_preview_cb)
    _FBP_SCENE_RNA.fbp_gradient_color_b = FloatVectorProperty(name="To", subtype='COLOR', size=4, min=0.0, max=1.0, description="End color of the gradient ramp or visible color in alpha mode", default=(0.058823529411764705, 0.12941176470588237, 0.24313725490196078, 1.0), update=update_scene_gradient_preview_cb)
    _FBP_SCENE_RNA.fbp_gradient_reverse = BoolProperty(name="Reverse Gradient", description="Swap the start and end of the generated gradient", default=True, update=update_scene_gradient_preview_cb)
    _FBP_SCENE_RNA.fbp_gradient_offset_x = FloatProperty(name="Gradient X Offset", description="Move the generated gradient horizontally before creating the plane", default=0.0, soft_min=-2.0, soft_max=2.0)
    _FBP_SCENE_RNA.fbp_gradient_offset_y = FloatProperty(name="Gradient Y Offset", description="Move the generated gradient vertically before creating the plane", default=0.0, soft_min=-2.0, soft_max=2.0)
    _FBP_SCENE_RNA.fbp_gradient_scale_x = FloatProperty(name="Gradient Scale X", description="Stretch or compress the generated gradient horizontally", default=1.0, min=0.001, soft_min=0.1, soft_max=10.0)
    _FBP_SCENE_RNA.fbp_gradient_scale_y = FloatProperty(name="Gradient Scale Y", description="Stretch or compress the generated gradient vertically", default=1.0, min=0.001, soft_min=0.1, soft_max=10.0)
    _FBP_SCENE_RNA.fbp_gradient_rotation = FloatProperty(name="Gradient Rotation", description="Rotate the procedural gradient mapping around the center of the plane in degrees without rotating the plane object itself.", default=0.0, soft_min=-180.0, soft_max=180.0)
    _FBP_SCENE_RNA.fbp_show_gradient_ramp = BoolProperty(name="Gradient Ramp", description="Expand or collapse the advanced ColorRamp editor used to adjust gradient stops, positions, interpolation and alpha values.", default=True)
    _FBP_SCENE_RNA.fbp_show_gradient_transform = BoolProperty(name="Gradient Position", description="Show gradient position, scale and rotation controls", default=True)
    _FBP_COLLECTION_RNA.is_fbp_collection = BoolProperty(description="Internal marker identifying a Blender collection as managed by Frame By Plane.", default=False)
    _FBP_COLLECTION_RNA.fbp_collapsed = BoolProperty(name="Collapsed", description="Collapse or expand this collection in the Frame By Plane Layers list", default=True)
    _FBP_COLLECTION_RNA.fbp_layer_order = FloatProperty(name="Layer List Order", description="Persistent mixed stack position used when a collection is placed between layers or other collections in the Frame By Plane Layer List", default=-1.0, min=-1.0, options={'HIDDEN'})
    _FBP_COLLECTION_RNA.fbp_layer_order_mixed = BoolProperty(
        name="Mixed Layer List Order",
        description="Use explicit mixed ordering for layers and nested collections",
        default=False,
        options={'HIDDEN'},
    )
    _FBP_COLLECTION_RNA.fbp_color_tag_explicit = BoolProperty(
        name="Explicit Collection Color",
        description="Keep the collection icon color captured from the active layer when the collection was created",
        default=False,
        options={'HIDDEN'},
    )
    _FBP_COLLECTION_RNA.fbp_layer_list_domain = EnumProperty(
        name="Layer List",
        description="Choose which dedicated Frame By Plane Layer List owns this collection",
        items=[
            ('AUTO', "Automatic", "Infer the list from the collection contents"),
            ('PLANES', "Planes", "Show this collection only in the plane Layer List"),
            ('GP', "Grease Pencil", "Show this collection only in the Grease Pencil Layer List"),
        ],
        default='AUTO',
        options={'HIDDEN'},
    )
    _FBP_COLLECTION_RNA.fbp_collection_selected = BoolProperty(name="Select Collection Layers", description="Select or deselect all Frame By Plane and Grease Pencil layers inside this collection. Click-drag across matching icons to paint selection", get=get_collection_selected, set=set_collection_selected)
    _FBP_COLLECTION_RNA.fbp_collection_solo = BoolProperty(name="Solo Collection Layers", description="Solo or unsolo all Frame By Plane and Grease Pencil layers inside this collection. Click-drag across matching icons to paint solo state", get=get_collection_solo, set=set_collection_solo)
    _FBP_COLLECTION_RNA.fbp_collection_locked = BoolProperty(name="Lock Collection Layers", description="Lock or unlock all Frame By Plane rigs and Grease Pencil layers in this collection. Click-drag across matching icons to paint locks", get=get_collection_locked, set=set_collection_locked)
    _FBP_COLLECTION_RNA.fbp_collection_plane_locked = BoolProperty(name="Lock Collection Planes", description="Lock or unlock linked image/color planes in this collection. Click-drag across matching icons to paint plane selectability", get=get_collection_plane_locked, set=set_collection_plane_locked)
    _FBP_COLLECTION_RNA.fbp_collection_visible = BoolProperty(name="Collection Visibility", description="Show or hide all Frame By Plane and Grease Pencil layers in this collection. Click-drag across matching icons to paint visibility", get=get_collection_visible, set=set_collection_visible)
    _FBP_COLLECTION_RNA.fbp_collection_holdout = BoolProperty(name="Holdout Collection Layers", description="Toggle alpha-aware holdout on all Frame By Plane layers inside this collection. Click-drag across matching icons to paint holdouts", get=get_collection_holdout, set=set_collection_holdout)

    _FBP_OBJECT_RNA.is_fbp_control     = BoolProperty(description="Internal marker identifying an object as a Frame By Plane control rig rather than an ordinary scene object.", default=False)
    _FBP_OBJECT_RNA.is_fbp_plane       = BoolProperty(description="Internal marker identifying an object as a plane owned by a Frame By Plane rig.", default=False)
    _FBP_OBJECT_RNA.fbp_layer_order = FloatProperty(
        name="Layer List Order",
        description="Optional explicit mixed-stack order. Plane layers normally use their physical camera depth and reset this value after a completed move",
        default=-1.0,
        min=-1.0,
        options={'HIDDEN'},
    )
    _FBP_OBJECT_RNA.fbp_is_drawing_plane = BoolProperty(
        name="Is Cutout Plane",
        description="Internal flag for manually selected Cutout Plane image libraries",
        default=False,
    )
    _FBP_OBJECT_RNA.fbp_drawing_auto_key = BoolProperty(
        name="Auto Key Drawing",
        description="Insert or update a Constant keyframe when the drawing slider changes",
        default=True,
    )
    _FBP_OBJECT_RNA.fbp_layer_name = StringProperty(
        name="Layer Name",
        description="Rename this Frame By Plane layer and update all linked UI references immediately",
        get=get_fbp_layer_name,
        set=set_fbp_layer_name,
        options={'SKIP_SAVE'},
    )
    _FBP_OBJECT_RNA.fbp_collection_name = StringProperty(name="FBP Collection", description="Internal name of the collection this Frame By Plane layer belongs to", default="")
    _FBP_OBJECT_RNA.fbp_follow_collection_color = BoolProperty(name="Follow Collection Color", description="Use the parent collection color tag as the rig viewport color", default=True)
    _FBP_OBJECT_RNA.fbp_color_variant_index = IntProperty(name="Color Variant", description="Internal color variation index used to make layers readable", default=0)
    _FBP_OBJECT_RNA.fbp_base_scale_vec = FloatVectorProperty(name="Base Scale Vector", description="Original generated scale vector used by Fit to Camera", default=(1.0, 1.0, 1.0))
    _FBP_OBJECT_RNA.fbp_preview_path   = StringProperty(name="Preview Path", description="Image path used for the layer thumbnail preview", default="")
    _FBP_OBJECT_RNA.fbp_is_vertical    = BoolProperty(name="Vertical", description="Whether this layer is standing vertically instead of lying horizontally", default=False)
    _FBP_OBJECT_RNA.fbp_images         = CollectionProperty(description="Ordered logical frame list used by this Frame By Plane layer, including linked media, durations, transparent frames and Cutout entries.", type=FBP_ImageItem)
    _FBP_OBJECT_RNA.fbp_images_index   = IntProperty(name="Active Frame", description="Active frame row in the selected Frame By Plane sequence", update=update_image_index_cb)
    _FBP_OBJECT_RNA.fbp_sequence_reversed = BoolProperty(
        name="Reverse Sequence",
        description="Internal direction state controlled by the sequence-side reverse icon",
        default=False,
    )
    _FBP_OBJECT_RNA.fbp_color_tag      = EnumProperty(
        name="Color Tag", description="Viewport and collection color tag for this Frame By Plane layer",
        items=fbp_color_tag_enum_items, default=0, update=update_color_tag_cb)
    _FBP_OBJECT_RNA.fbp_rig_shape = EnumProperty(
        name="Rig Shape",
        description="Choose the viewport wire shape of this Frame By Plane control without changing its image plane",
        items=RIG_SHAPE_ITEMS,
        default='DEFAULT',
        update=update_rig_shape_cb,
    )
    _FBP_OBJECT_RNA.fbp_rig_shape_expand = FloatProperty(
        name="Expand",
        description="Extra controller border around the visible plane; 0 matches the plane exactly, 1 uses the standard spacing and 2 doubles it",
        default=1.0, min=0.0, max=2.0, soft_min=0.0, soft_max=2.0,
        precision=2, update=update_rig_shape_cb,
    )
    _FBP_OBJECT_RNA.fbp_rig_shape_fit_mode = EnumProperty(
        name="Shape Fit",
        description="Fit the chosen controller shape to the plane bounds or preserve perfect proportions",
        items=(
            ('FIT_PLANE', "Fit to Plane", "Stretch the controller shape to the visible plane bounds", fbp_icon("FULLSCREEN_ENTER"), 0),
            ('PERFECT', "Perfect Shape", "Preserve a square, circle or regular polygon", fbp_icon("MESH_CIRCLE"), 1),
        ),
        default='FIT_PLANE',
        update=update_rig_shape_cb,
    )
    _FBP_OBJECT_RNA.fbp_sequence_show_frames = BoolProperty(
        name="Frames",
        description="Expand this layer's frame list; single-image layers start collapsed",
        default=False,
    )
    _FBP_OBJECT_RNA.fbp_gp_layers_expanded = BoolProperty(
        name="Grease Pencil Layers",
        description="Expand the internal Grease Pencil layers in Frame By Plane UI lists",
        default=False,
    )
    _FBP_OBJECT_RNA.fbp_depth_order    = IntProperty(name="Depth Order", description="Internal depth order used for generated layers", default=0)
    _FBP_OBJECT_RNA.fbp_loop_mode = EnumProperty(description="Choose how this animated layer behaves outside its logical image range. One Shot holds the end frame, Loop repeats, and Ping-Pong alternates direction.",
        name="Playback",
        items=[
            ('NONE',     "One Shot",  "Play the sequence once and hold the last frame", fbp_icon("FORWARD"),        0),
            ('REPEAT',   "Loop",      "Repeat the image sequence indefinitely", fbp_icon("FILE_REFRESH"),   1),
            ('PINGPONG', "Ping-Pong", "Play forward and backward in a loop", fbp_icon("UV_SYNC_SELECT"), 2),
        ],
        default='NONE', update=update_loop_mode_cb)
    _FBP_OBJECT_RNA.fbp_emission_strength = FloatProperty(
        name="Strength",
        description="Real Emission shader strength. Values above 1 create high-dynamic-range light for Cycles and bloom/compositing workflows",
        default=1.0, min=0.0, soft_max=100.0, max=100000.0, precision=3,
        update=update_emission_strength_cb,
    )
    _FBP_OBJECT_RNA.fbp_use_emission   = BoolProperty(
        name="Shadeless", description="Use an emission-style material so the image is not affected by scene lighting", default=False, update=update_emission_cb)
    _FBP_OBJECT_RNA.fbp_interpolation  = EnumProperty(description="Choose how the image texture is sampled. Pixel preserves sharp pixel-art edges; Smooth blends neighboring pixels during scaling and camera movement.",
        name="Filter",
        items=[
            ('Closest', "Pixel",  "Use nearest-neighbor filtering for sharp pixel edges", fbp_icon("ALIASED"), 0),
            ('Linear',  "Smooth", "Use linear filtering for smoother image scaling", fbp_icon("ANTIALIASED"), 1),
        ],
        default='Closest', update=update_interpolation_cb)
    _FBP_OBJECT_RNA.fbp_plane_target    = PointerProperty(name="Linked Plane", description="Image plane controlled by this Frame By Plane rig", type=bpy.types.Object)
    _FBP_OBJECT_RNA.fbp_global_duration = IntProperty(
        name="Global Duration", description="Set the duration in frames for all frames in this sequence", default=2, min=1, update=update_global_duration_cb)
    _FBP_OBJECT_RNA.fbp_start_frame     = IntProperty(
        name="Start Frame", description="Timeline frame where this sequence starts playing", default=1, update=update_start_frame_cb)
    _FBP_OBJECT_RNA.fbp_opacity         = FloatProperty(
        name="Opacity", description="Overall opacity multiplier for this layer. At 100% Frame By Plane removes unnecessary multiply nodes where safe; lower values preserve source alpha.", default=1.0, min=0.0, max=1.0,
        subtype='FACTOR', update=update_opacity_cb)
    _FBP_OBJECT_RNA.fbp_track_cam       = BoolProperty(
        name="Track Camera", description="Constrain this layer to face the active camera", default=False, update=update_track_cb)
    _FBP_OBJECT_RNA.fbp_is_visible      = BoolProperty(
        name="Visible", description="Show or hide this Frame By Plane layer in the viewport and render", default=True, update=update_visibility_cb)
    _FBP_OBJECT_RNA.fbp_is_color_plane = BoolProperty(name="Is Color Plane", description="Internal flag for rigged Frame By Plane color, holdout and gradient planes", default=False)
    _FBP_OBJECT_RNA.fbp_color_plane_mode = EnumProperty(
        name="Plane Type", description="Change the selected color plane between solid color, gradient and holdout material",
        items=[('SOLID', "Solid", "Use one editable solid color"), ('GRADIENT', "Gradient", "Use an editable color-ramp gradient"), ('HOLDOUT', "Holdout", "Use a compositor holdout material")],
        default='SOLID', update=update_object_color_plane_cb)
    _FBP_OBJECT_RNA.fbp_color_plane_color = FloatVectorProperty(name="Color", subtype='COLOR', size=4, min=0.0, max=1.0, description="Solid color used by this Frame By Plane color plane", default=(1.0, 1.0, 1.0, 1.0), update=update_object_color_plane_cb)
    _FBP_OBJECT_RNA.fbp_color_plane_emission = BoolProperty(name="Emission", description="Use a lightweight emission shader for this color or gradient plane", default=True, update=update_object_color_plane_cb)
    _FBP_OBJECT_RNA.fbp_gradient_mode = EnumProperty(
        name="Gradient Mode", description="Choose whether this existing Gradient Plane uses a linear mapping or a centered radial mapping. The material preview updates immediately.",
        items=[('LINEAR', "Linear", "Linear gradient from one side of the plane to the other", fbp_icon("ARROW_LEFTRIGHT"), 0), ('CENTER', "Radial", "Centered radial gradient useful for vignettes", fbp_icon("EMPTY_ARROWS"), 1)], default='LINEAR', update=update_object_color_plane_cb)
    _FBP_OBJECT_RNA.fbp_gradient_kind = EnumProperty(
        name="Gradient Type", description="Choose whether this gradient blends between two colors or changes alpha",
        items=[('COLOR', "Color to Color", "Blend between the From and To colors", fbp_icon("COLOR"), 0), ('ALPHA', "Transparent to Visible", "Fade from the From color at 0 alpha to the To color", fbp_icon("IMAGE_ALPHA"), 1)], default='COLOR', update=update_object_color_plane_cb)
    _FBP_OBJECT_RNA.fbp_gradient_color_a = FloatVectorProperty(name="From", subtype='COLOR', size=4, min=0.0, max=1.0, description="Start color of the gradient ramp. In alpha mode this side is forced transparent", default=(1.0, 0.3686274509803922, 0.596078431372549, 1.0), update=update_object_color_plane_cb)
    _FBP_OBJECT_RNA.fbp_gradient_color_b = FloatVectorProperty(name="To", subtype='COLOR', size=4, min=0.0, max=1.0, description="RGBA color at the To side of this Gradient Plane. Its alpha participates in the material transparency and updates the preview immediately.", default=(0.058823529411764705, 0.12941176470588237, 0.24313725490196078, 1.0), update=update_object_color_plane_cb)
    _FBP_OBJECT_RNA.fbp_gradient_reverse = BoolProperty(name="Reverse Gradient", description="Reverse the gradient direction by swapping its two endpoints without changing their stored colors or the plane transform.", default=True, update=update_object_color_plane_cb)
    _FBP_OBJECT_RNA.fbp_gradient_offset_x = FloatProperty(name="Gradient X Offset", description="Offset the procedural gradient horizontally in local plane coordinates without moving the object or changing its UV layout.", default=0.0, soft_min=-2.0, soft_max=2.0, update=update_gradient_mapping_cb)
    _FBP_OBJECT_RNA.fbp_gradient_offset_y = FloatProperty(name="Gradient Y Offset", description="Offset the procedural gradient vertically in local plane coordinates without moving the object or changing its UV layout.", default=0.0, soft_min=-2.0, soft_max=2.0, update=update_gradient_mapping_cb)
    _FBP_OBJECT_RNA.fbp_gradient_scale_x = FloatProperty(name="Gradient Scale X", description="Stretch or compress this gradient horizontally", default=1.0, min=0.001, soft_min=0.1, soft_max=10.0, update=update_gradient_mapping_cb)
    _FBP_OBJECT_RNA.fbp_gradient_scale_y = FloatProperty(name="Gradient Scale Y", description="Scale the procedural gradient vertically around its center. Values below one compress the transition; larger values stretch it.", default=1.0, min=0.001, soft_min=0.1, soft_max=10.0, update=update_gradient_mapping_cb)
    _FBP_OBJECT_RNA.fbp_gradient_rotation = FloatProperty(name="Gradient Rotation", description="Rotate this Gradient Plane's procedural mapping around the local center in degrees without rotating the object.", default=0.0, soft_min=-180.0, soft_max=180.0, update=update_gradient_mapping_cb)
    _FBP_OBJECT_RNA.fbp_gradient_controller = PointerProperty(
        name="Gradient Controller",
        description="External Empty whose local X/Y position drives this Gradient frame center and can be keyframed like any Blender object",
        type=bpy.types.Object,
        poll=lambda self, candidate: candidate is not self and getattr(candidate, "type", "") == "EMPTY",
        update=update_gradient_controller_cb,
    )
    _FBP_OBJECT_RNA.fbp_gradient_light_controller = PointerProperty(
        name="Gradient Light Controller",
        description="External Empty whose plane-local position drives the Gradient Light effect and can be animated with ordinary Location keyframes",
        type=bpy.types.Object,
        poll=lambda self, candidate: candidate is not self and getattr(candidate, "type", "") == "EMPTY",
    )
    _FBP_OBJECT_RNA.fbp_show_gradient_ramp = BoolProperty(name="Gradient Ramp", description="Show the advanced ColorRamp controls for this plane", default=True)
    _FBP_OBJECT_RNA.fbp_show_gradient_transform = BoolProperty(name="Gradient Position", description="Show the gradient position, scale and rotation controls for this plane", default=True)
    _FBP_OBJECT_RNA.fbp_extend_mode = EnumProperty(
        name="Extend Mode",
        description="How added border geometry samples pixels outside the original image",
        items=[
            ('EDGE', "Edge Pixel", "Clamp added geometry to the nearest image-edge pixel"),
            ('TRANSPARENT', "Transparent", "Keep added geometry transparent outside the image; recommended for outer shadows and glows"),
            ('REPEAT', "Repeat Texture", "Repeat the texture into the added geometry"),
            ('MIRROR', "Repeat Flipped", "Repeat the texture while alternating normal and mirrored tiles for a continuous border"),
        ],
        default='MIRROR', update=update_extend_mode_cb,
    )
    _FBP_OBJECT_RNA.fbp_extend_left = FloatProperty(name="Left", description="Extend the left edge after crop without scaling the image center", default=0.0, min=0.0, soft_min=0.0, soft_max=1.0, step=1, precision=3, update=update_object_padding_cb)
    _FBP_OBJECT_RNA.fbp_extend_right = FloatProperty(name="Right", description="Extend the right edge after crop without scaling the image center", default=0.0, min=0.0, soft_min=0.0, soft_max=1.0, step=1, precision=3, update=update_object_padding_cb)
    _FBP_OBJECT_RNA.fbp_extend_top = FloatProperty(name="Top", description="Extend the top edge after crop without scaling the image center", default=0.0, min=0.0, soft_min=0.0, soft_max=1.0, step=1, precision=3, update=update_object_padding_cb)
    _FBP_OBJECT_RNA.fbp_extend_bottom = FloatProperty(name="Bottom", description="Extend the bottom edge after crop without scaling the image center", default=0.0, min=0.0, soft_min=0.0, soft_max=1.0, step=1, precision=3, update=update_object_padding_cb)
    _FBP_OBJECT_RNA.fbp_crop_left = FloatProperty(name="Left", description="Crop the left edge before extension is applied", default=0.0, min=0.0, max=1.999999, soft_min=0.0, soft_max=1.0, step=1, precision=3, update=update_object_padding_cb)
    _FBP_OBJECT_RNA.fbp_crop_right = FloatProperty(name="Right", description="Crop the right edge before extension is applied", default=0.0, min=0.0, max=1.999999, soft_min=0.0, soft_max=1.0, step=1, precision=3, update=update_object_padding_cb)
    _FBP_OBJECT_RNA.fbp_crop_top = FloatProperty(name="Top", description="Crop the top edge before extension is applied", default=0.0, min=0.0, max=1.999999, soft_min=0.0, soft_max=1.0, step=1, precision=3, update=update_object_padding_cb)
    _FBP_OBJECT_RNA.fbp_crop_bottom = FloatProperty(name="Bottom", description="Crop the bottom edge before extension is applied", default=0.0, min=0.0, max=1.999999, soft_min=0.0, soft_max=1.0, step=1, precision=3, update=update_object_padding_cb)
    _FBP_OBJECT_RNA.fbp_effects = CollectionProperty(
        type=FBP_EffectItem,
        description="Runtime list of geometry and shader effects shared by the selected Frame By Plane layers",
        options={'SKIP_SAVE'})
    _FBP_OBJECT_RNA.fbp_effect_instance_channels = CollectionProperty(
        type=FBP_EffectInstanceChannel,
        description="Stable keyframeable channels owned by concrete effect instances")
    _FBP_OBJECT_RNA.fbp_effect_instance_animations = CollectionProperty(
        type=FBP_EffectInstanceAnimation,
        description="Stable procedural animation settings owned by concrete effect instances")
    _FBP_OBJECT_RNA.fbp_effects_index = IntProperty(
        name="Active Effect",
        description="Selected effect in the Frame By Plane effect stack",
        default=0, min=0, options={'SKIP_SAVE'}, update=update_effects_index_cb)
    _FBP_OBJECT_RNA.fbp_effect_controls_enabled = BoolProperty(
        name="Effect Controls",
        description="Show a selectable viewport control for the active spatial effect",
        default=True, update=update_effect_controls_enabled_cb)
    _FBP_OBJECT_RNA.fbp_effects_signature = StringProperty(description="Internal cache signature of the current effect stack, used to avoid unnecessary UI synchronization and node-tree rebuilds.",
        name="Effect Stack Signature", default="", options={'SKIP_SAVE'})
    _FBP_OBJECT_RNA.fbp_effect_groups = CollectionProperty(
        type=FBP_EffectGroupItem,
        description="Persistent organizational groups used by the Frame By Plane Effects Stack")
    _FBP_OBJECT_RNA.fbp_effect_groups_index = IntProperty(
        name="Active Effect Group",
        description="Reserved index for the future Effect Groups interface",
        default=0, min=0)
    _FBP_OBJECT_RNA.fbp_mesh_wiggle_enabled = BoolProperty(
        name="Wiggle",
        description="Enable the bundled Wiggle Geometry Nodes effect on this Frame By Plane layer",
        default=False,
        update=update_mesh_wiggle_enabled_cb)
    _FBP_OBJECT_RNA.fbp_mesh_wiggle_shade_smooth = BoolProperty(
        name="Shade Smooth",
        description="Apply smooth face shading after Wiggle subdivision. Disable it to preserve a faceted paper or low-poly appearance.",
        default=True,
        update=update_mesh_wiggle_shade_smooth_cb)
    _FBP_OBJECT_RNA.fbp_mesh_wiggle_strength = FloatProperty(
        name="Strength",
        description="Strength of the Wiggle deformation. Set to zero to keep the noise fixed visually",
        default=1.0, min=0.0, soft_max=3.0, precision=3,
        update=update_mesh_wiggle_strength_cb)
    _FBP_OBJECT_RNA.fbp_mesh_wiggle_speed = FloatProperty(
        name="Speed",
        description="Multiplier applied to Scene Time when Wiggle animation evolves automatically. Higher values change the noise pattern more rapidly.",
        default=10.0, soft_min=-20.0, soft_max=20.0, precision=3,
        update=update_mesh_wiggle_speed_cb)
    _FBP_OBJECT_RNA.fbp_mesh_wiggle_hold = IntProperty(
        name="Stepped",
        description="Number of frames held before the Wiggle noise updates",
        default=4, min=1, soft_max=24,
        update=update_mesh_wiggle_hold_cb)
    _FBP_OBJECT_RNA.fbp_mesh_wiggle_w = FloatProperty(
        name="Noise Phase (W)",
        description="Fourth coordinate of the 4D Noise Texture. It shifts the noise pattern without moving the plane",
        default=0.0, soft_min=-20.0, soft_max=20.0, precision=3,
        update=update_mesh_wiggle_w_cb)
    _FBP_OBJECT_RNA.fbp_mesh_wiggle_seed = IntProperty(
        name="Seed",
        description="Integer offset used to choose a repeatable Wiggle noise pattern",
        default=0, min=0, max=999999,
        update=update_mesh_wiggle_seed_cb)
    _FBP_OBJECT_RNA.fbp_mesh_wiggle_unique_seed = BoolProperty(
        name="Unique per Layer",
        description="Add a persistent per-layer seed so selected planes can share settings without sharing the same noise pattern",
        default=False,
        update=update_mesh_wiggle_unique_seed_cb)
    _FBP_OBJECT_RNA.fbp_mesh_wiggle_layer_seed = IntProperty(
        name="Internal Layer Seed",
        description="Persistent internal seed used by Unique per Layer",
        default=0, min=0, max=2147483647, options={'HIDDEN'})
    _FBP_OBJECT_RNA.fbp_mesh_wiggle_noise_scale = FloatProperty(
        name="Noise Scale",
        description="Spatial scale of the procedural noise deforming the mesh. Lower values create broad bends; higher values create smaller detailed movement.",
        default=5.0, min=0.001, soft_max=20.0, precision=3,
        update=update_mesh_wiggle_noise_scale_cb)
    _FBP_OBJECT_RNA.fbp_mesh_wiggle_detail = FloatProperty(
        name="Noise Detail",
        description="Number of additional fractal noise octaves used by Wiggle. Higher values add fine deformation detail but increase evaluation cost.",
        default=0.0, min=0.0, soft_max=15.0, precision=3,
        update=update_mesh_wiggle_detail_cb)
    _FBP_OBJECT_RNA.fbp_mesh_wiggle_subdivisions = IntProperty(
        name="Viewport",
        description="Viewport subdivision level applied before Mesh Wiggle deformation. Lower values are faster while editing.",
        default=3, min=0, max=6,
        update=update_mesh_wiggle_subdivisions_cb)
    _FBP_OBJECT_RNA.fbp_mesh_wiggle_playback_subdivisions = IntProperty(
        name="Playback",
        description="Maximum Mesh Wiggle subdivision level used during timeline playback. It limits the viewport value temporarily for smoother playback.",
        default=2, min=0, max=6,
        update=update_mesh_wiggle_playback_subdivisions_cb)
    _FBP_OBJECT_RNA.fbp_mesh_wiggle_render_subdivisions = IntProperty(
        name="Render",
        description="Subdivision level used for Mesh Wiggle during final render.",
        default=4, min=0, max=6,
        update=update_mesh_wiggle_render_subdivisions_cb)

    # Additional geometry effects from the corrected bundled library
    _FBP_OBJECT_RNA.fbp_stop_motion_resolution = IntProperty(description="Viewport subdivision level used before Crumple deformation. Higher values preserve finer bends but increase viewport cost.", name="Viewport", default=3, min=0, max=6, update=update_stop_motion_resolution_cb)
    _FBP_OBJECT_RNA.fbp_stop_motion_playback_resolution = IntProperty(description="Maximum Crumple subdivision level used during timeline playback. Lower values keep playback responsive.", name="Playback", default=2, min=0, max=6, update=update_stop_motion_playback_resolution_cb)
    _FBP_OBJECT_RNA.fbp_stop_motion_render_resolution = IntProperty(description="Subdivision level used by Crumple during final render.", name="Render", default=4, min=0, max=6, update=update_stop_motion_render_resolution_cb)
    _FBP_OBJECT_RNA.fbp_stop_motion_strength = FloatProperty(description="Maximum displacement applied by Crumple. Increase for stronger paper-like deformation; zero keeps the plane flat.", name="Strength", default=0.05, min=0.0, soft_max=1.0, precision=3, update=update_stop_motion_strength_cb)
    _FBP_OBJECT_RNA.fbp_stop_motion_step_frames = IntProperty(description="Number of timeline frames each Crumple pose is held before a new deterministic deformation is evaluated.", name="Stepped", default=3, min=1, soft_max=24, update=update_stop_motion_step_frames_cb)
    _FBP_OBJECT_RNA.fbp_wind_bend_amount = FloatProperty(description="Overall amount and direction of Mesh Motion deformation. Positive and negative values bend the free side in opposite directions.", name="Bend Amount", default=0.5, soft_min=-2.0, soft_max=2.0, precision=3, update=update_wind_bend_amount_cb)
    _FBP_OBJECT_RNA.fbp_wind_speed = FloatProperty(description="Animation speed used by Wind. Negative values reverse temporal direction; zero freezes the current wind phase.", name="Speed", default=2.0, soft_min=-20.0, soft_max=20.0, precision=3, update=update_wind_speed_cb)
    _FBP_OBJECT_RNA.fbp_wind_shade_smooth = BoolProperty(
        name="Shade Smooth",
        description="Smooth the subdivided Wind mesh after deformation. Disable it for a faceted paper look.",
        default=True,
        update=update_wind_shade_smooth_cb)
    _FBP_OBJECT_RNA.fbp_wind_pin_edge = EnumProperty(
        name="Pin Mode", description="Pin one evaluated mesh border, all borders, or a named vertex group. Evaluated bounds automatically follow Crop and Extend.",
        items=(('LEFT', "Left", "Pin the left border"), ('RIGHT', "Right", "Pin the right border"), ('BOTTOM', "Bottom", "Pin the bottom border"), ('TOP', "Top", "Pin the top border"), ('ALL', "All Borders", "Pin all four evaluated borders"), ('VERTEX_GROUP', "Vertex Group", "Use a vertex group where weight one is fully pinned")),
        default='LEFT', update=update_wind_pin_edge_cb)
    _FBP_OBJECT_RNA.fbp_wind_pin_strength = FloatProperty(
        name="Pin Strength", description="Blend between unpinned motion and the selected border or vertex-group pinning.",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_wind_pin_strength_cb)
    _FBP_OBJECT_RNA.fbp_wind_pin_vertex_group = StringProperty(
        name="Vertex Group", description="Name of the vertex group used when Pin Mode is Vertex Group. Weight one is pinned; zero remains free.",
        default="", update=update_wind_pin_vertex_group_cb)
    _FBP_OBJECT_RNA.fbp_wind_motion_mode = EnumProperty(
        name="Behavior", description="Choose a broad sway, traveling flag waves, or a directional/radial ripple.",
        items=(('SWAY', "Sway", "Bend the free area as one broad motion"), ('FLOW', "Flow", "Generate traveling flag-like waves"), ('RIPPLE', "Ripple", "Generate directional or radial surface ripples")),
        default='SWAY', update=update_wind_motion_mode_cb)
    _FBP_OBJECT_RNA.fbp_wind_ripple_direction = EnumProperty(
        name="Ripple Direction", description="Coordinate used by Ripple behavior.",
        items=(('X', "Horizontal", "Waves travel across local X"), ('Y', "Vertical", "Waves travel across local Y"), ('RADIAL', "Radial", "Waves expand from the evaluated mesh center")),
        default='X', update=update_wind_ripple_direction_cb)
    _FBP_OBJECT_RNA.fbp_wind_wave_count = FloatProperty(
        name="Wave Count", description="Number of waves distributed between pinned and free edge",
        default=2.0, min=0.0, soft_max=10.0, max=40.0, update=update_wind_wave_count_cb)
    _FBP_OBJECT_RNA.fbp_wind_wave_amplitude = FloatProperty(description="Strength of traveling waves layered over the main Mesh Motion deformation.",
        name="Wave Amplitude", default=0.12, min=0.0, soft_max=1.0, max=10.0, update=update_wind_wave_amplitude_cb)
    _FBP_OBJECT_RNA.fbp_wind_wave_speed = FloatProperty(description="Speed and direction of traveling waves in Mesh Motion. Negative values make waves move backward.",
        name="Wave Speed", default=2.0, soft_min=-20.0, soft_max=20.0, update=update_wind_wave_speed_cb)
    _FBP_OBJECT_RNA.fbp_wind_phase = FloatProperty(description="Manual phase offset for Mesh Motion waves. Animate this value to control motion independently from automatic Scene Time.",
        name="Starting Phase", default=0.0, soft_min=-6.283185, soft_max=6.283185, subtype='ANGLE', update=update_wind_phase_cb)
    _FBP_OBJECT_RNA.fbp_wind_turbulence = FloatProperty(
        name="Turbulence", description="Small irregular motion layered over the main deformation",
        default=0.03, min=0.0, soft_max=0.3, max=2.0, update=update_wind_turbulence_cb)
    _FBP_OBJECT_RNA.fbp_wind_reverse = BoolProperty(
        name="Reverse Direction", description="Reverse the wind displacement vector while preserving all other Wind strength, turbulence and animation settings.",
        default=False, update=update_wind_reverse_cb)
    _FBP_OBJECT_RNA.fbp_wind_falloff = FloatProperty(
        name="Falloff", description="Shape how strongly the pinned edge stays fixed",
        default=1.5, min=0.1, max=8.0, update=update_wind_falloff_cb)
    _FBP_OBJECT_RNA.fbp_wind_noise_scale = FloatProperty(
        name="Noise Scale", description="Size of the turbulence pattern used by Mesh Motion. Lower values produce broad gusts; higher values create smaller local variations.",
        default=3.0, min=0.01, soft_max=20.0, max=100.0, update=update_wind_noise_scale_cb)
    _FBP_OBJECT_RNA.fbp_wind_gust_strength = FloatProperty(
        name="Gust Strength", description="Amount of slow irregular gust variation layered over the main wind cycle to reduce visibly repetitive motion.",
        default=0.0, min=0.0, soft_max=1.0, max=4.0, update=update_wind_gust_strength_cb)
    _FBP_OBJECT_RNA.fbp_wind_direction_space = EnumProperty(
        name="Direction Space",
        description="Interpret Wind Direction in the plane local axes or in world axes",
        items=(("LOCAL", "Local", "Direction rotates with the plane"),
               ("WORLD", "World", "Direction stays aligned to the world")),
        default="LOCAL", update=update_wind_direction_space_cb)
    _FBP_OBJECT_RNA.fbp_wind_direction = FloatVectorProperty(
        name="Direction", description="Direction vector used by Wind. Rotate the viewport directional null to edit this value.",
        size=3, subtype='DIRECTION', default=(0.0, 0.0, 1.0),
        min=-1.0, max=1.0, update=update_wind_direction_cb)
    _FBP_OBJECT_RNA.fbp_wind_preview_falloff = BoolProperty(
        name="Preview Falloff",
        description="Temporarily replace animated wind with a static displacement that visualizes pinned-edge falloff",
        default=False, update=update_wind_preview_falloff_cb)
    _FBP_OBJECT_RNA.fbp_felt_render_density = IntProperty(
        name="Render Density",
        description="Approximate strand count generated by Felt Fuzz at render quality. Higher values increase density, memory use and render time substantially.",
        default=50000, min=1000, soft_max=3000000, max=3000000, step=100,
        options={'ANIMATABLE'}, update=update_felt_render_density_cb)
    _FBP_OBJECT_RNA.fbp_felt_viewport_percentage = FloatProperty(
        name="Viewport %", description="Fraction of the render strand count displayed in the viewport",
        default=0.0025, min=0.0, max=1.0, subtype='FACTOR', options={'ANIMATABLE'},
        update=update_felt_viewport_percentage_cb)
    _FBP_OBJECT_RNA.fbp_felt_fuzz_length = FloatProperty(description="Length of generated Felt Fuzz strands measured in scene units. Longer strands create softer wool but cost more to evaluate and render.",
        name="Fuzz Length", default=0.04, min=0.0, soft_max=0.5, max=10.0,
        precision=4, subtype='DISTANCE', options={'ANIMATABLE'}, update=update_felt_fuzz_length_cb)
    _FBP_OBJECT_RNA.fbp_felt_subdivisions = IntProperty(
        name="Subdivisions", description="Number of points along every strand; increase for smooth, tightly curled wool",
        default=3, min=2, soft_max=24, max=64, options={'ANIMATABLE'}, update=update_felt_subdivisions_cb)
    _FBP_OBJECT_RNA.fbp_felt_curl_amount = FloatProperty(
        name="Curl Turns", description="Curl frequency and intensity. The response accelerates toward the upper range so fibers can coil back around themselves.",
        default=1.0, min=0.0, soft_max=8.0, max=24.0, precision=3,
        options={'ANIMATABLE'}, update=update_felt_curl_amount_cb)
    _FBP_OBJECT_RNA.fbp_felt_fuzz_radius = FloatProperty(description="Radius of each generated Felt Fuzz strand. Very small values create fine fibers; larger values produce thick yarn-like strands.",
        name="Fuzz Radius", default=0.0005, min=0.00001, soft_min=0.0005,
        soft_max=0.05, max=1.0, precision=6, subtype='DISTANCE', options={'ANIMATABLE'},
        update=update_felt_fuzz_radius_cb)
    _FBP_OBJECT_RNA.fbp_felt_seed = IntProperty(description="Deterministic random seed controlling Felt Fuzz strand placement and variation. The same value reproduces the same result.",
        name="Seed", default=0, min=0, max=2147483647, options={'ANIMATABLE'}, update=update_felt_seed_cb)
    _FBP_OBJECT_RNA.fbp_felt_alpha_threshold = FloatProperty(description="Minimum source alpha required to generate Felt Fuzz. Increase this value to keep fibers away from soft or partially transparent edges.", name="Alpha Threshold", default=0.05, min=0.0, max=1.0, subtype='FACTOR', update=update_felt_alpha_threshold_cb)
    _FBP_OBJECT_RNA.fbp_felt_alpha_resolution = IntProperty(name="Alpha Resolution", description="Subdivision detail used only to sample the image alpha for fiber placement", default=2, min=2, max=6, update=update_felt_alpha_resolution_cb)
    _FBP_OBJECT_RNA.fbp_fiber_render_density = IntProperty(
        name="Render Density", description="Approximate Fiber Tufts per square scene unit at render quality",
        default=12000, min=0, soft_max=250000, max=3000000, step=100,
        options={'ANIMATABLE'}, update=update_fiber_render_density_cb)
    _FBP_OBJECT_RNA.fbp_fiber_viewport_percentage = FloatProperty(
        name="Viewport %", description="Fraction of render density evaluated in the viewport",
        default=0.05, min=0.0, max=1.0, subtype='FACTOR', options={'ANIMATABLE'},
        update=update_fiber_viewport_percentage_cb)
    _FBP_OBJECT_RNA.fbp_fiber_length = FloatProperty(
        name="Length", description="Length of each instanced fiber clump",
        default=0.035, min=0.0, soft_max=0.5, max=10.0, precision=4, subtype='DISTANCE',
        options={'ANIMATABLE'}, update=update_fiber_length_cb)
    _FBP_OBJECT_RNA.fbp_fiber_luminance_length = FloatProperty(
        name="Luminance Length", description="Make bright texture regions grow longer fibers and dark regions shorter; use negative values to invert the response",
        default=0.5, min=-1.0, max=1.0, subtype='FACTOR', options={'ANIMATABLE'},
        update=update_fiber_luminance_length_cb)
    _FBP_OBJECT_RNA.fbp_fiber_radius = FloatProperty(
        name="Radius", description="Radius of the low-poly fiber profile",
        default=0.0007, min=0.00001, soft_max=0.02, max=1.0, precision=6, subtype='DISTANCE',
        options={'ANIMATABLE'}, update=update_fiber_radius_cb)
    _FBP_OBJECT_RNA.fbp_fiber_segments = IntProperty(
        name="Segments", description="Control points along the shared bent fiber prototype",
        default=4, min=2, soft_max=8, max=32, update=update_fiber_segments_cb)
    _FBP_OBJECT_RNA.fbp_fiber_bend = FloatProperty(
        name="Bend", description="Sideways bow applied to the shared fiber prototype",
        default=0.008, min=-1.0, max=1.0, soft_min=-0.1, soft_max=0.1, precision=4,
        subtype='DISTANCE', options={'ANIMATABLE'}, update=update_fiber_bend_cb)
    _FBP_OBJECT_RNA.fbp_fiber_randomness = FloatProperty(
        name="Randomness", description="Per-instance tilt and scale variation",
        default=0.35, min=0.0, max=1.0, subtype='FACTOR', options={'ANIMATABLE'},
        update=update_fiber_randomness_cb)
    _FBP_OBJECT_RNA.fbp_fiber_seed = IntProperty(
        name="Seed", description="Deterministic seed for Fiber Tufts placement and variation",
        default=0, min=0, max=2147483647, options={'ANIMATABLE'}, update=update_fiber_seed_cb)
    _FBP_OBJECT_RNA.fbp_fiber_alpha_threshold = FloatProperty(
        name="Alpha Threshold", description="Minimum source alpha that receives fibers",
        default=0.05, min=0.0, max=1.0, subtype='FACTOR', update=update_fiber_alpha_threshold_cb)
    _FBP_OBJECT_RNA.fbp_fiber_alpha_resolution = IntProperty(
        name="Alpha Resolution", description="Subdivision detail used only for alpha silhouette sampling",
        default=2, min=0, max=6, update=update_fiber_alpha_resolution_cb)

    _FBP_OBJECT_RNA.fbp_shards_render_density = IntProperty(
        name="Render Density", description="Approximate Paper Shards per square scene unit at render quality",
        default=1800, min=0, soft_max=50000, max=1000000, step=50,
        options={'ANIMATABLE'}, update=update_shards_render_density_cb)
    _FBP_OBJECT_RNA.fbp_shards_viewport_percentage = FloatProperty(
        name="Viewport %", description="Fraction of render density evaluated in the viewport",
        default=0.15, min=0.0, max=1.0, subtype='FACTOR', options={'ANIMATABLE'},
        update=update_shards_viewport_percentage_cb)
    _FBP_OBJECT_RNA.fbp_shards_size = FloatProperty(
        name="Shard Size", description="Base width of every instanced paper chip",
        default=0.025, min=0.0001, soft_max=0.25, max=10.0, subtype='DISTANCE', precision=4,
        options={'ANIMATABLE'}, update=update_shards_size_cb)
    _FBP_OBJECT_RNA.fbp_shards_aspect = FloatProperty(
        name="Aspect", description="Length-to-width ratio of each paper chip",
        default=1.8, min=0.05, soft_max=8.0, max=100.0, precision=3,
        options={'ANIMATABLE'}, update=update_shards_aspect_cb)
    _FBP_OBJECT_RNA.fbp_shards_thickness = FloatProperty(
        name="Thickness", description="Physical thickness of each instanced chip",
        default=0.001, min=0.00001, soft_max=0.05, max=2.0, subtype='DISTANCE', precision=5,
        options={'ANIMATABLE'}, update=update_shards_thickness_cb)
    _FBP_OBJECT_RNA.fbp_shards_lift = FloatProperty(
        name="Lift", description="Offset paper chips away from the source surface",
        default=0.002, min=-1.0, max=10.0, soft_min=0.0, soft_max=0.1, subtype='DISTANCE', precision=4,
        options={'ANIMATABLE'}, update=update_shards_lift_cb)
    _FBP_OBJECT_RNA.fbp_shards_luminance_lift = FloatProperty(
        name="Luminance Lift", description="Move bright and dark shards to opposite sides of the base lift using the sampled plane texture",
        default=0.01, min=-10.0, max=10.0, soft_min=-0.1, soft_max=0.1,
        subtype='DISTANCE', precision=4, options={'ANIMATABLE'}, update=update_shards_luminance_lift_cb)
    _FBP_OBJECT_RNA.fbp_shards_tilt = FloatProperty(
        name="Tilt", description="Maximum random local tilt for each paper chip",
        default=0.35, min=0.0, max=3.141593, subtype='ANGLE', options={'ANIMATABLE'}, update=update_shards_tilt_cb)
    _FBP_OBJECT_RNA.fbp_shards_scale_randomness = FloatProperty(
        name="Scale Randomness", description="Per-instance size variation",
        default=0.4, min=0.0, max=0.95, subtype='FACTOR', options={'ANIMATABLE'},
        update=update_shards_scale_randomness_cb)
    _FBP_OBJECT_RNA.fbp_shards_seed = IntProperty(
        name="Seed", description="Deterministic seed for Paper Shards placement and variation",
        default=0, min=0, max=2147483647, options={'ANIMATABLE'}, update=update_shards_seed_cb)
    _FBP_OBJECT_RNA.fbp_shards_alpha_threshold = FloatProperty(
        name="Alpha Threshold", description="Minimum source alpha that receives paper chips",
        default=0.05, min=0.0, max=1.0, subtype='FACTOR', update=update_shards_alpha_threshold_cb)
    _FBP_OBJECT_RNA.fbp_shards_alpha_resolution = IntProperty(
        name="Alpha Resolution", description="Subdivision detail used only for alpha silhouette sampling",
        default=2, min=0, max=6, update=update_shards_alpha_resolution_cb)

    _FBP_OBJECT_RNA.fbp_sphere_screen_viewport_columns = IntProperty(
        name="Viewport Columns", description="Image-solid columns evaluated while editing",
        default=24, min=2, soft_max=128, max=512, update=update_sphere_screen_viewport_columns_cb)
    _FBP_OBJECT_RNA.fbp_sphere_screen_viewport_rows = IntProperty(
        name="Viewport Rows", description="Image-solid rows evaluated while editing",
        default=14, min=2, soft_max=128, max=512, update=update_sphere_screen_viewport_rows_cb)
    _FBP_OBJECT_RNA.fbp_sphere_screen_render_columns = IntProperty(
        name="Render Columns", description="Image-solid columns evaluated for final rendering",
        default=64, min=2, soft_max=256, max=1024, update=update_sphere_screen_render_columns_cb)
    _FBP_OBJECT_RNA.fbp_sphere_screen_render_rows = IntProperty(
        name="Render Rows", description="Image-solid rows evaluated for final rendering",
        default=36, min=2, soft_max=256, max=1024, update=update_sphere_screen_render_rows_cb)
    _FBP_OBJECT_RNA.fbp_sphere_screen_shape = EnumProperty(
        name="Solid", description="Shared solid instanced at every sampled image cell",
        items=(
            ('SPHERE', "Sphere", "Icosphere display cells"),
            ('CUBE', "Cube", "Cubic display cells"),
            ('CYLINDER', "Cylinder", "Cylindrical display cells"),
            ('CONE', "Cone", "Conical display cells"),
        ), default='SPHERE', update=update_sphere_screen_shape_cb)
    _FBP_OBJECT_RNA.fbp_sphere_screen_scale = FloatProperty(
        name="Solid Scale", description="Solid size relative to the spacing between display cells",
        default=0.82, min=0.01, soft_max=1.5, max=4.0, precision=3,
        options={'ANIMATABLE'}, update=update_sphere_screen_scale_cb)
    _FBP_OBJECT_RNA.fbp_sphere_screen_luminance_size = FloatProperty(
        name="Luminance Size", description="Make bright image cells larger and dark cells smaller; negative values invert the response",
        default=0.5, min=-1.0, max=1.0, subtype='FACTOR', options={'ANIMATABLE'},
        update=update_sphere_screen_luminance_size_cb)
    _FBP_OBJECT_RNA.fbp_sphere_screen_subdivisions = IntProperty(
        name="Sphere Detail", description="Icosphere subdivision level; other solid types use optimized fixed topology",
        default=1, min=1, soft_max=3, max=5, update=update_sphere_screen_subdivisions_cb)
    _FBP_OBJECT_RNA.fbp_sphere_screen_depth = FloatProperty(
        name="Depth", description="Move sampled solids away from the plane to create an image-driven relief",
        default=0.0, soft_min=-0.25, soft_max=0.25, min=-10.0, max=10.0,
        subtype='DISTANCE', options={'ANIMATABLE'}, update=update_sphere_screen_depth_cb)
    _FBP_OBJECT_RNA.fbp_sphere_screen_depth_mode = EnumProperty(
        name="Depth Source", description="Image measurement used to move solids in depth",
        items=(
            ('LIGHTS', "Highlights", "Bright pixels move furthest"),
            ('SHADOWS', "Shadows", "Dark pixels move furthest"),
            ('SATURATION', "Saturation", "Color saturation controls depth"),
            ('CUSTOM', "Custom Map", "Use the selected depth image or sequence"),
        ), default='LIGHTS', update=update_sphere_screen_depth_mode_cb)
    _FBP_OBJECT_RNA.fbp_sphere_screen_depth_image = PointerProperty(
        name="Depth Map", description="Custom image or sequence used when Depth Source is Custom Map",
        type=bpy.types.Image, update=update_sphere_screen_depth_image_cb)
    _FBP_OBJECT_RNA.fbp_sphere_screen_flicker = FloatProperty(
        name="Flicker", description="Procedural per-solid brightness variation driven by Phase",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR', options={'ANIMATABLE'},
        update=update_sphere_screen_flicker_cb)
    _FBP_OBJECT_RNA.fbp_sphere_screen_phase = FloatProperty(
        name="Phase", description="Starting phase for animated solid flicker",
        default=0.0, soft_min=-100.0, soft_max=100.0, options={'ANIMATABLE'},
        update=update_sphere_screen_phase_cb)
    _FBP_OBJECT_RNA.fbp_sphere_screen_emission = FloatProperty(
        name="Emission", description="Light intensity emitted by the sampled image colors",
        default=3.0, min=0.0, soft_max=20.0, max=1000.0, options={'ANIMATABLE'},
        update=update_sphere_screen_emission_cb)
    _FBP_OBJECT_RNA.fbp_sphere_screen_alpha_threshold = FloatProperty(
        name="Alpha Threshold", description="Hide solids where source alpha is below this value",
        default=0.05, min=0.0, max=1.0, subtype='FACTOR', update=update_sphere_screen_alpha_threshold_cb)
    _FBP_OBJECT_RNA.fbp_sphere_screen_show_source = BoolProperty(
        name="Show Source", description="Keep the original textured plane behind the solid display",
        default=False, update=update_sphere_screen_show_source_cb)

    _FBP_OBJECT_RNA.fbp_image_relief_subdivision = IntProperty(
        name="Viewport", description="Aspect-balanced triangular remesh detail used while editing Image Relief",
        default=5, min=0, max=8, update=update_image_relief_subdivision_cb)
    _FBP_OBJECT_RNA.fbp_image_relief_playback_subdivision = IntProperty(
        name="Playback", description="Maximum Image Relief remesh detail during timeline playback",
        default=4, min=0, max=8, update=update_image_relief_playback_subdivision_cb)
    _FBP_OBJECT_RNA.fbp_image_relief_render_subdivision = IntProperty(
        name="Render", description="Image Relief remesh detail used for final rendering",
        default=7, min=0, max=8, update=update_image_relief_render_subdivision_cb)
    _FBP_OBJECT_RNA.fbp_image_relief_depth = FloatProperty(
        name="Depth", description="Maximum signed displacement of the textured surface",
        default=0.12, min=-10.0, max=10.0, soft_min=-0.5, soft_max=0.5,
        subtype='DISTANCE', options={'ANIMATABLE'}, update=update_image_relief_depth_cb)
    _FBP_OBJECT_RNA.fbp_image_relief_midlevel = FloatProperty(
        name="Midlevel", description="Depth value that remains on the original plane",
        default=0.5, min=0.0, max=1.0, subtype='FACTOR', options={'ANIMATABLE'}, update=update_image_relief_midlevel_cb)
    _FBP_OBJECT_RNA.fbp_image_relief_depth_mode = EnumProperty(
        name="Depth Source", description="Image measurement used to displace the plane",
        items=(
            ('LIGHTS', "Highlights", "Bright pixels rise"),
            ('SHADOWS', "Shadows", "Dark pixels rise"),
            ('SATURATION', "Saturation", "Color saturation controls relief"),
            ('CUSTOM', "Custom Map", "Use the selected depth image or sequence"),
        ), default='LIGHTS', update=update_image_relief_depth_mode_cb)
    _FBP_OBJECT_RNA.fbp_image_relief_depth_image = PointerProperty(
        name="Depth Map", description="Custom image or sequence used when Depth Source is Custom Map",
        type=bpy.types.Image, update=update_image_relief_depth_image_cb)
    _FBP_OBJECT_RNA.fbp_image_relief_smooth = FloatProperty(
        name="Smooth", description="Blend the depth field toward a spatially smoothed surface to soften transitions between forward and backward displacement",
        default=0.35, min=0.0, max=1.0, subtype='FACTOR', options={'ANIMATABLE'},
        update=update_image_relief_smooth_cb)
    _FBP_OBJECT_RNA.fbp_image_relief_smooth_iterations = IntProperty(
        name="Iterations", description="Number of neighboring depth-smoothing passes; higher values create broader, softer transitions",
        default=4, min=0, soft_max=16, max=64, options={'ANIMATABLE'},
        update=update_image_relief_smooth_iterations_cb)
    _FBP_OBJECT_RNA.fbp_image_relief_alpha_threshold = FloatProperty(
        name="Alpha Threshold", description="Displace only pixels whose source alpha exceeds this value",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=update_image_relief_alpha_threshold_cb)
    _FBP_OBJECT_RNA.fbp_image_relief_shade_smooth = BoolProperty(
        name="Shade Smooth", description="Smooth-shade the displaced image surface",
        default=True, update=update_image_relief_shade_smooth_cb)

    _FBP_OBJECT_RNA.fbp_glass_subdivision = IntProperty(
        name="Viewport", description="Aspect-balanced quad remesh detail used to resolve Broken Glass fractures while editing",
        default=5, min=0, max=8, update=update_glass_subdivision_cb)
    _FBP_OBJECT_RNA.fbp_glass_playback_subdivision = IntProperty(
        name="Playback", description="Maximum Broken Glass remesh detail evaluated during timeline playback",
        default=4, min=0, max=8, update=update_glass_playback_subdivision_cb)
    _FBP_OBJECT_RNA.fbp_glass_render_subdivision = IntProperty(
        name="Render", description="Broken Glass remesh detail used for final rendering",
        default=6, min=0, max=8, update=update_glass_render_subdivision_cb)
    _FBP_OBJECT_RNA.fbp_glass_thickness = FloatProperty(
        name="Thickness", description="Depth of every closed refractive glass shard",
        default=0.025, min=0.0001, soft_max=0.25, max=10.0,
        subtype='DISTANCE', options={'ANIMATABLE'}, update=update_glass_thickness_cb)
    _FBP_OBJECT_RNA.fbp_glass_relief = FloatProperty(
        name="Shard Lift", description="Offset each Voronoi cell by a stable random amount so the fragments no longer share one perfectly flat face",
        default=0.015, min=-10.0, max=10.0, soft_min=-0.25, soft_max=0.25,
        subtype='DISTANCE', options={'ANIMATABLE'}, update=update_glass_relief_cb)
    _FBP_OBJECT_RNA.fbp_glass_source = EnumProperty(
        name="Damage Source", description="Field that decides where procedural fracture gaps are allowed",
        items=(
            ('ALPHA', "Source Alpha", "Multiply damage by source alpha variation"),
            ('PROCEDURAL', "Full Surface", "Fracture the complete visible silhouette"),
            ('NORMAL', "Damage Map", "Use the selected image luminance as a painted damage mask"),
        ), default='PROCEDURAL', update=update_glass_source_cb)
    _FBP_OBJECT_RNA.fbp_glass_normal_image = PointerProperty(
        name="Damage Map", description="Painted grayscale image controlling where Broken Glass cracks appear",
        type=bpy.types.Image, update=update_glass_normal_image_cb)
    _FBP_OBJECT_RNA.fbp_glass_noise_scale = FloatProperty(
        name="Cell Scale", description="Number and size of Voronoi fracture cells",
        default=7.0, min=0.01, soft_max=50.0, max=10000.0,
        options={'ANIMATABLE'}, update=update_glass_noise_scale_cb)
    _FBP_OBJECT_RNA.fbp_glass_correct_aspect = BoolProperty(
        name="Auto Aspect",
        description="Keep Voronoi cells proportional on wide or tall planes using the mesh dimensions",
        default=True, update=update_glass_correct_aspect_cb)
    _FBP_OBJECT_RNA.fbp_glass_texture_scale_x = FloatProperty(
        name="Scale X", description="Additional horizontal Voronoi frequency after automatic aspect correction",
        default=1.0, min=0.01, soft_max=10.0, max=10000.0,
        options={'ANIMATABLE'}, update=update_glass_texture_scale_x_cb)
    _FBP_OBJECT_RNA.fbp_glass_texture_scale_y = FloatProperty(
        name="Scale Y", description="Additional vertical Voronoi frequency after automatic aspect correction",
        default=1.0, min=0.01, soft_max=10.0, max=10000.0,
        options={'ANIMATABLE'}, update=update_glass_texture_scale_y_cb)
    _FBP_OBJECT_RNA.fbp_glass_crack_width = FloatProperty(
        name="Crack Width", description="Width of the geometry removed along Voronoi cell borders",
        default=0.035, min=0.0, soft_max=0.15, max=0.5,
        options={'ANIMATABLE'}, update=update_glass_crack_width_cb)
    _FBP_OBJECT_RNA.fbp_glass_damage = FloatProperty(
        name="Damage", description="Overall amount of open fracture; zero keeps the sheet intact",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR',
        options={'ANIMATABLE'}, update=update_glass_damage_cb)
    _FBP_OBJECT_RNA.fbp_glass_noise_detail = FloatProperty(
        name="Chaos", description="Strength of the stable per-cell random lift and crack irregularity",
        default=0.65, min=0.0, max=1.0, subtype='FACTOR', options={'ANIMATABLE'}, update=update_glass_noise_detail_cb)
    _FBP_OBJECT_RNA.fbp_glass_phase = FloatProperty(
        name="Seed", description="Move the procedural cell field to generate or animate a different fracture layout",
        default=0.0, soft_min=-100.0, soft_max=100.0,
        options={'ANIMATABLE'}, update=update_glass_phase_cb)
    _FBP_OBJECT_RNA.fbp_glass_alpha_threshold = FloatProperty(
        name="Alpha Threshold", description="Remove geometry where source alpha is below this value",
        default=0.02, min=0.0, max=1.0, subtype='FACTOR', update=update_glass_alpha_threshold_cb)
    _FBP_OBJECT_RNA.fbp_glass_shade_smooth = BoolProperty(
        name="Shade Smooth", description="Smooth-shade the closed glass shards",
        default=True, update=update_glass_shade_smooth_cb)
    _FBP_OBJECT_RNA.fbp_glass_distortion = FloatProperty(
        name="Crack Distortion", description="Strength of procedural shard bump refraction",
        default=0.65, min=0.0, soft_max=3.0, max=10.0,
        options={'ANIMATABLE'}, update=update_glass_distortion_cb)
    _FBP_OBJECT_RNA.fbp_glass_bevel = FloatProperty(
        name="Edge Bevel",
        description="Blender 5.2 real-geometry Mesh Bevel radius; zero bypasses the node without adding topology",
        default=0.0, min=0.0, soft_max=0.03, max=1.0,
        subtype='DISTANCE', options={'ANIMATABLE'}, update=update_glass_bevel_cb)
    _FBP_OBJECT_RNA.fbp_glass_roughness = FloatProperty(
        name="Roughness", description="Blur and softness of reflections and refraction",
        default=0.12, min=0.0, max=1.0, subtype='FACTOR',
        options={'ANIMATABLE'}, update=update_glass_roughness_cb)
    _FBP_OBJECT_RNA.fbp_glass_ior = FloatProperty(
        name="IOR", description="Index of refraction; common glass is around 1.45",
        default=1.45, min=1.0, soft_max=2.5, max=10.0,
        options={'ANIMATABLE'}, update=update_glass_ior_cb)
    _FBP_OBJECT_RNA.fbp_glass_tint = FloatVectorProperty(
        name="Tint", description="Base color of the broken glass",
        default=(0.72, 0.92, 1.0, 1.0), min=0.0, max=1.0,
        size=4, subtype='COLOR', options={'ANIMATABLE'}, update=update_glass_tint_cb)
    _FBP_OBJECT_RNA.fbp_glass_source_color = FloatProperty(
        name="Source Color", description="Blend from Tint to the unmodified source image; 100% disables Tint, Edge Tint and tinted volume absorption",
        default=0.35, min=0.0, max=1.0, subtype='FACTOR',
        options={'ANIMATABLE'}, update=update_glass_source_color_cb)
    _FBP_OBJECT_RNA.fbp_glass_edge_tint = FloatProperty(
        name="Edge Tint",
        description="Strength of the Fresnel-colored crystal edge at grazing angles",
        default=0.55, min=0.0, max=1.0, subtype='FACTOR',
        options={'ANIMATABLE'}, update=update_glass_edge_tint_cb)
    _FBP_OBJECT_RNA.fbp_glass_absorption = FloatProperty(
        name="Absorption",
        description="Tint density accumulated through the closed crystal volume; zero disables volume absorption",
        default=0.35, min=0.0, soft_max=10.0, max=100.0,
        options={'ANIMATABLE'}, update=update_glass_absorption_cb)

    _FBP_OBJECT_RNA.fbp_crystal_subdivision = IntProperty(
        name="Viewport", description="Aspect-balanced quad remesh used to sample alpha and build the Crystal depth field",
        default=4, min=0, max=8, update=update_crystal_subdivision_cb)
    _FBP_OBJECT_RNA.fbp_crystal_playback_subdivision = IntProperty(
        name="Playback", description="Maximum Crystal source remesh detail during timeline playback",
        default=3, min=0, max=8, update=update_crystal_playback_subdivision_cb)
    _FBP_OBJECT_RNA.fbp_crystal_render_subdivision = IntProperty(
        name="Render", description="Crystal source remesh detail used for final rendering",
        default=6, min=0, max=8, update=update_crystal_render_subdivision_cb)
    _FBP_OBJECT_RNA.fbp_crystal_silhouette_detail = IntProperty(
        name="Silhouette Boost",
        description="Extra local subdivisions after transparent canvas is culled; Source Remesh 4 plus Boost 4 reaches edge density comparable to Source Remesh 8 without refining the full canvas",
        default=2, min=0, max=4, update=update_crystal_silhouette_detail_cb)
    _FBP_OBJECT_RNA.fbp_crystal_depth = FloatProperty(
        name="Depth", description="Height of the rounded alpha-derived crystal body",
        default=0.14, min=-10.0, max=10.0, soft_min=-0.5, soft_max=0.5,
        subtype='DISTANCE', options={'ANIMATABLE'}, update=update_crystal_depth_cb)
    _FBP_OBJECT_RNA.fbp_crystal_thickness = FloatProperty(
        name="Back Thickness", description="Optional closed volume behind the crystal; zero keeps one transparent refractive surface and is much lighter",
        default=0.0, min=0.0, soft_max=0.25, max=10.0,
        subtype='DISTANCE', options={'ANIMATABLE'}, update=update_crystal_thickness_cb)
    _FBP_OBJECT_RNA.fbp_crystal_roundness = FloatProperty(
        name="Roundness", description="Blend from a flat alpha body at 0 to the maximum rounded edge-distance profile at 1",
        default=0.8, min=0.0, max=1.0, subtype='FACTOR',
        options={'ANIMATABLE'}, update=update_crystal_roundness_cb)
    _FBP_OBJECT_RNA.fbp_crystal_edge_pinning = FloatProperty(
        name="Edge Pinning",
        description="Keep the crystal body and procedural extrusion attached to the original plane along alpha and influence-map borders",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR',
        options={'ANIMATABLE'}, update=update_crystal_edge_pinning_cb)
    _FBP_OBJECT_RNA.fbp_crystal_blur_iterations = IntProperty(
        name="Edge Width", description="Width of the topology-derived black-to-white edge-distance profile; it behaves like an internal AO map without changing the exact silhouette cutoff",
        default=4, min=0, soft_max=16, max=32, options={'ANIMATABLE'},
        update=update_crystal_blur_iterations_cb)
    _FBP_OBJECT_RNA.fbp_crystal_use_influence_map = BoolProperty(
        name="Use Influence Map",
        description="Limit crystal displacement, transparency and refractive distortion with a painted grayscale image",
        default=False, update=update_crystal_use_influence_map_cb)
    _FBP_OBJECT_RNA.fbp_crystal_influence_image = PointerProperty(
        name="Influence Map",
        description="Grayscale map where white receives the Crystal effect and black keeps the original opaque image surface",
        type=bpy.types.Image, update=update_crystal_influence_image_cb)
    _FBP_OBJECT_RNA.fbp_crystal_invert_influence = BoolProperty(
        name="Invert Influence",
        description="Swap the black and white regions of the Crystal influence map",
        default=False, update=update_crystal_invert_influence_cb)
    _FBP_OBJECT_RNA.fbp_crystal_influence_strength = FloatProperty(
        name="Influence Strength",
        description="Blend between Crystal everywhere and the painted influence map",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR',
        options={'ANIMATABLE'}, update=update_crystal_influence_strength_cb)
    _FBP_OBJECT_RNA.fbp_crystal_texture_type = EnumProperty(
        name="Generator",
        description="Generated texture used for Crystal surface relief",
        items=(
            ('VORONOI', "Voronoi", "Cellular mineral islands; Voronoi Shape selects the shaping style"),
            ('NOISE', "Fractal Noise", "Organic multi-scale crystalline roughness"),
            ('WAVE', "Crystal Bands", "Concentric generated bands suitable for layered mineral growth"),
            ('BRICK', "Geometric Blocks", "Regular generated block facets separated by thin mortar lines"),
        ),
        default='VORONOI', update=update_crystal_texture_type_cb)
    _FBP_OBJECT_RNA.fbp_crystal_pattern_mode = EnumProperty(
        name="Voronoi Shape", description="Voronoi shaping style used when Generator is Voronoi",
        items=(
            ('DIAMOND', "Diamond", "Sharp faceted ridges following Voronoi cell borders"),
            ('CRYSTAL', "Crystal", "Angular mineral cells with irregular inner height"),
            ('LIQUID', "Liquid", "Rounded flowing cells with softer transitions"),
        ), default='CRYSTAL', update=update_crystal_pattern_mode_cb)
    _FBP_OBJECT_RNA.fbp_crystal_pattern_scale = FloatProperty(
        name="Scale", description="Size and frequency of the procedural crystal cells",
        default=8.0, min=0.01, soft_max=50.0, max=10000.0,
        options={'ANIMATABLE'}, update=update_crystal_pattern_scale_cb)
    _FBP_OBJECT_RNA.fbp_crystal_correct_aspect = BoolProperty(
        name="Auto Aspect",
        description="Keep Crystal Voronoi cells proportional on wide or tall planes using the mesh dimensions",
        default=True, update=update_crystal_correct_aspect_cb)
    _FBP_OBJECT_RNA.fbp_crystal_texture_scale_x = FloatProperty(
        name="Scale X", description="Additional horizontal Crystal texture frequency after automatic aspect correction",
        default=1.0, min=0.01, soft_max=10.0, max=10000.0,
        options={'ANIMATABLE'}, update=update_crystal_texture_scale_x_cb)
    _FBP_OBJECT_RNA.fbp_crystal_texture_scale_y = FloatProperty(
        name="Scale Y", description="Additional vertical Crystal texture frequency after automatic aspect correction",
        default=1.0, min=0.01, soft_max=10.0, max=10000.0,
        options={'ANIMATABLE'}, update=update_crystal_texture_scale_y_cb)
    _FBP_OBJECT_RNA.fbp_crystal_pattern_detail = FloatProperty(
        name="Detail", description="Sharpness and secondary variation inside the procedural cells",
        default=4.0, min=0.0, soft_max=16.0, max=64.0,
        options={'ANIMATABLE'}, update=update_crystal_pattern_detail_cb)
    _FBP_OBJECT_RNA.fbp_crystal_pattern_strength = FloatProperty(
        name="Surface Strength", description="Height of Diamond, Crystal or Liquid detail over the rounded body",
        default=0.035, min=-10.0, max=10.0, soft_min=-0.25, soft_max=0.25,
        subtype='DISTANCE', options={'ANIMATABLE'}, update=update_crystal_pattern_strength_cb)
    _FBP_OBJECT_RNA.fbp_crystal_cell_randomness = FloatProperty(
        name="Cell Randomness",
        description="Vary extrusion height independently for each Voronoi island while preserving shared border pinning",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR',
        options={'ANIMATABLE'}, update=update_crystal_cell_randomness_cb)
    _FBP_OBJECT_RNA.fbp_crystal_cell_seed = IntProperty(
        name="Cell Seed",
        description="Choose another deterministic distribution of randomized Voronoi island heights",
        default=0, min=0, max=2147483647, options={'ANIMATABLE'},
        update=update_crystal_cell_seed_cb)
    _FBP_OBJECT_RNA.fbp_crystal_phase = FloatProperty(
        name="Phase", description="Animate the procedural structure without moving the Frame by Plane layer",
        default=0.0, soft_min=-100.0, soft_max=100.0,
        options={'ANIMATABLE'}, update=update_crystal_phase_cb)
    _FBP_OBJECT_RNA.fbp_crystal_alpha_threshold = FloatProperty(
        name="Alpha Cutoff", description="Exact binary silhouette cutoff; source alpha still shapes depth but never creates a translucent edge fade",
        default=0.5, min=0.0, max=1.0, subtype='FACTOR', update=update_crystal_alpha_threshold_cb)
    _FBP_OBJECT_RNA.fbp_crystal_surface_subdivision = IntProperty(
        name="Clay Smoothing", description="Subdivision Surface passes applied after closing the volume; use zero for crisp silhouettes",
        default=1, min=0, max=2, update=update_crystal_surface_subdivision_cb)
    _FBP_OBJECT_RNA.fbp_crystal_shade_smooth = BoolProperty(
        name="Shade Smooth", description="Smooth-shade the closed Crystal volume",
        default=True, update=update_crystal_shade_smooth_cb)
    _FBP_OBJECT_RNA.fbp_crystal_distortion = FloatProperty(
        name="Refraction Detail", description="Strength of procedural surface bump used by the refractive material",
        default=0.8, min=0.0, soft_max=3.0, max=10.0,
        options={'ANIMATABLE'}, update=update_crystal_distortion_cb)
    _FBP_OBJECT_RNA.fbp_crystal_roughness = FloatProperty(
        name="Roughness", description="Blur and softness of Crystal reflections and refraction",
        default=0.1, min=0.0, max=1.0, subtype='FACTOR',
        options={'ANIMATABLE'}, update=update_crystal_roughness_cb)
    _FBP_OBJECT_RNA.fbp_crystal_ior = FloatProperty(
        name="IOR", description="Index of refraction for the Crystal volume",
        default=1.47, min=1.0, soft_max=2.5, max=10.0,
        options={'ANIMATABLE'}, update=update_crystal_ior_cb)
    _FBP_OBJECT_RNA.fbp_crystal_tint = FloatVectorProperty(
        name="Tint", description="Base Crystal color",
        default=(0.48, 0.82, 1.0, 1.0), min=0.0, max=1.0,
        size=4, subtype='COLOR', options={'ANIMATABLE'}, update=update_crystal_tint_cb)
    _FBP_OBJECT_RNA.fbp_crystal_source_color = FloatProperty(
        name="Source Color", description="Blend from Tint to the unmodified animated source image; 100% removes Tint from both surface and absorption",
        default=0.4, min=0.0, max=1.0, subtype='FACTOR',
        options={'ANIMATABLE'}, update=update_crystal_source_color_cb)
    _FBP_OBJECT_RNA.fbp_crystal_absorption = FloatProperty(
        name="Absorption", description="Tint density accumulated through the closed Crystal volume",
        default=0.7, min=0.0, soft_max=10.0, max=100.0,
        options={'ANIMATABLE'}, update=update_crystal_absorption_cb)
    _FBP_OBJECT_RNA.fbp_crystal_thin_wall = BoolProperty(
        name="Thin Wall",
        description="Use Blender 5.2 thin-surface transmission. Disabled preserves full refractive distortion; enable it for a lighter sheet-like look",
        default=False, update=update_crystal_thin_wall_cb)

    _FBP_OBJECT_RNA.fbp_surface_conform_target = PointerProperty(
        name="Target Surface", description="Mesh surface that receives the aspect-balanced remeshed plane",
        type=bpy.types.Object, update=update_surface_conform_target_cb)
    _FBP_OBJECT_RNA.fbp_surface_conform_subdivision = IntProperty(
        name="Viewport", description="Aspect-balanced triangular remesh detail used while editing Surface Conform",
        default=3, min=0, max=8, update=update_surface_conform_subdivision_cb)
    _FBP_OBJECT_RNA.fbp_surface_conform_playback_subdivision = IntProperty(
        name="Playback", description="Maximum remesh detail used during timeline playback",
        default=2, min=0, max=8, update=update_surface_conform_playback_subdivision_cb)
    _FBP_OBJECT_RNA.fbp_surface_conform_render_subdivision = IntProperty(
        name="Render", description="Remesh detail used for final rendering",
        default=5, min=0, max=8, update=update_surface_conform_render_subdivision_cb)
    _FBP_OBJECT_RNA.fbp_surface_conform_factor = FloatProperty(
        name="Factor", description="Blend between the original plane and the conformed surface",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR', options={'ANIMATABLE'},
        update=update_surface_conform_factor_cb)
    _FBP_OBJECT_RNA.fbp_surface_conform_offset = FloatProperty(
        name="Offset", description="Move the conformed plane along the sampled target normal",
        default=0.002, soft_min=-0.1, soft_max=0.1, min=-10.0, max=10.0,
        subtype='DISTANCE', options={'ANIMATABLE'}, update=update_surface_conform_offset_cb)
    _FBP_OBJECT_RNA.fbp_surface_conform_max_distance = FloatProperty(
        name="Max Distance", description="Only conform vertices within this distance of the target surface",
        default=10.0, min=0.0, soft_max=100.0, max=100000.0, subtype='DISTANCE',
        update=update_surface_conform_max_distance_cb)
    _FBP_OBJECT_RNA.fbp_surface_conform_shade_smooth = BoolProperty(
        name="Shade Smooth", description="Smooth-shade the conformed plane",
        default=True, update=update_surface_conform_shade_smooth_cb)

    _FBP_OBJECT_RNA.fbp_accordion_subdivision = IntProperty(
        name="Viewport", description="Aspect-balanced triangular remesh detail used while editing Accordion Fold",
        default=5, min=0, max=8, update=update_accordion_subdivision_cb)
    _FBP_OBJECT_RNA.fbp_accordion_playback_subdivision = IntProperty(
        name="Playback", description="Maximum remesh detail used during Accordion Fold playback",
        default=4, min=0, max=8, update=update_accordion_playback_subdivision_cb)
    _FBP_OBJECT_RNA.fbp_accordion_render_subdivision = IntProperty(
        name="Render", description="Remesh detail used for the final Accordion Fold render",
        default=6, min=0, max=8, update=update_accordion_render_subdivision_cb)
    _FBP_OBJECT_RNA.fbp_accordion_folds = IntProperty(
        name="Folds", description="Number of alternating ridges across the plane",
        default=8, min=1, soft_max=64, max=256, options={'ANIMATABLE'}, update=update_accordion_folds_cb)
    _FBP_OBJECT_RNA.fbp_accordion_depth = FloatProperty(
        name="Depth", description="Height of the accordion ridges",
        default=0.06, min=-10.0, max=10.0, soft_min=-0.5, soft_max=0.5,
        subtype='DISTANCE', options={'ANIMATABLE'}, update=update_accordion_depth_cb)
    _FBP_OBJECT_RNA.fbp_accordion_phase = FloatProperty(
        name="Phase", description="Shift and animate the fold profile across the plane",
        default=0.0, soft_min=-20.0, soft_max=20.0, options={'ANIMATABLE'}, update=update_accordion_phase_cb)
    _FBP_OBJECT_RNA.fbp_accordion_vertical = BoolProperty(
        name="Vertical", description="Run the folds along the vertical axis instead of the horizontal axis",
        default=False, update=update_accordion_vertical_cb)
    _FBP_OBJECT_RNA.fbp_accordion_shade_smooth = BoolProperty(
        name="Shade Smooth", description="Smooth the accordion surface shading",
        default=False, update=update_accordion_shade_smooth_cb)

    _FBP_OBJECT_RNA.fbp_sculpt_waves_subdivision = IntProperty(
        name="Viewport", description="Aspect-balanced triangular remesh detail used while editing Sculpt Waves",
        default=5, min=0, max=8, update=update_sculpt_waves_subdivision_cb)
    _FBP_OBJECT_RNA.fbp_sculpt_waves_playback_subdivision = IntProperty(
        name="Playback", description="Maximum Sculpt Waves remesh detail during timeline playback",
        default=4, min=0, max=8, update=update_sculpt_waves_playback_subdivision_cb)
    _FBP_OBJECT_RNA.fbp_sculpt_waves_render_subdivision = IntProperty(
        name="Render", description="Sculpt Waves remesh detail used for final rendering",
        default=6, min=0, max=8, update=update_sculpt_waves_render_subdivision_cb)
    _FBP_OBJECT_RNA.fbp_sculpt_waves_style = EnumProperty(
        name="Style", description="Artistic displacement field used to sculpt the textured plane",
        items=(
            ('RADIAL', "Radial", "Concentric expanding waves"),
            ('MOIRE', "Moiré", "Crossed interference waves"),
            ('SPIRAL', "Spiral", "Rotating multi-arm spiral waves"),
        ), default='RADIAL', update=update_sculpt_waves_style_cb)
    _FBP_OBJECT_RNA.fbp_sculpt_waves_amplitude = FloatProperty(
        name="Amplitude", description="Signed height of the sculpted wave surface",
        default=0.08, min=-10.0, max=10.0, soft_min=-0.5, soft_max=0.5,
        subtype='DISTANCE', options={'ANIMATABLE'}, update=update_sculpt_waves_amplitude_cb)
    _FBP_OBJECT_RNA.fbp_sculpt_waves_frequency = FloatProperty(
        name="Frequency", description="Number and density of wave bands across the plane",
        default=5.0, min=0.01, soft_max=30.0, max=1000.0,
        options={'ANIMATABLE'}, update=update_sculpt_waves_frequency_cb)
    _FBP_OBJECT_RNA.fbp_sculpt_waves_phase = FloatProperty(
        name="Phase", description="Animate propagation or rotation of the selected wave style",
        default=0.0, soft_min=-100.0, soft_max=100.0,
        options={'ANIMATABLE'}, update=update_sculpt_waves_phase_cb)
    _FBP_OBJECT_RNA.fbp_sculpt_waves_edge_falloff = FloatProperty(
        name="Edge Falloff", description="Fade displacement toward the outer edge while preserving the center",
        default=0.35, min=0.0, max=1.0, subtype='FACTOR', options={'ANIMATABLE'},
        update=update_sculpt_waves_edge_falloff_cb)
    _FBP_OBJECT_RNA.fbp_sculpt_waves_shade_smooth = BoolProperty(
        name="Shade Smooth", description="Smooth-shade the sculpted surface",
        default=True, update=update_sculpt_waves_shade_smooth_cb)

    _FBP_OBJECT_RNA.fbp_kinetic_tiles_subdivision = IntProperty(
        name="Viewport", description="Aspect-balanced quad remesh detail controlling the visible tile count",
        default=3, min=0, max=7, update=update_kinetic_tiles_subdivision_cb)
    _FBP_OBJECT_RNA.fbp_kinetic_tiles_playback_subdivision = IntProperty(
        name="Playback", description="Maximum tile remesh detail evaluated during timeline playback",
        default=2, min=0, max=7, update=update_kinetic_tiles_playback_subdivision_cb)
    _FBP_OBJECT_RNA.fbp_kinetic_tiles_render_subdivision = IntProperty(
        name="Render", description="Tile remesh detail used for final rendering",
        default=4, min=0, max=7, update=update_kinetic_tiles_render_subdivision_cb)
    _FBP_OBJECT_RNA.fbp_kinetic_tiles_pattern = EnumProperty(
        name="Pattern", description="Animated height pattern applied to the separated tiles",
        items=(
            ('WAVE', "Wave", "Traveling diagonal wave"),
            ('CHECKER', "Checker", "Interlocking checker-wave pattern"),
            ('RIPPLE', "Ripple", "Concentric moving ripple"),
        ), default='WAVE', update=update_kinetic_tiles_pattern_cb)
    _FBP_OBJECT_RNA.fbp_kinetic_tiles_gap = FloatProperty(
        name="Gap", description="Space between neighboring tiles",
        default=0.08, min=0.0, max=0.95, subtype='FACTOR', options={'ANIMATABLE'},
        update=update_kinetic_tiles_gap_cb)
    _FBP_OBJECT_RNA.fbp_kinetic_tiles_thickness = FloatProperty(
        name="Thickness", description="Base signed extrusion depth of every tile",
        default=0.02, min=-10.0, max=10.0, soft_min=-0.5, soft_max=0.5,
        subtype='DISTANCE', options={'ANIMATABLE'}, update=update_kinetic_tiles_thickness_cb)
    _FBP_OBJECT_RNA.fbp_kinetic_tiles_motion = FloatProperty(
        name="Motion", description="Additional animated height variation from the selected pattern",
        default=0.04, min=-10.0, max=10.0, soft_min=-0.5, soft_max=0.5,
        subtype='DISTANCE', options={'ANIMATABLE'}, update=update_kinetic_tiles_motion_cb)
    _FBP_OBJECT_RNA.fbp_kinetic_tiles_frequency = FloatProperty(
        name="Frequency", description="Spatial density of the tile animation pattern",
        default=6.0, min=0.01, soft_max=30.0, max=1000.0,
        options={'ANIMATABLE'}, update=update_kinetic_tiles_frequency_cb)
    _FBP_OBJECT_RNA.fbp_kinetic_tiles_phase = FloatProperty(
        name="Phase", description="Animate the tile height pattern across the plane",
        default=0.0, soft_min=-100.0, soft_max=100.0,
        options={'ANIMATABLE'}, update=update_kinetic_tiles_phase_cb)
    _FBP_OBJECT_RNA.fbp_kinetic_tiles_shade_smooth = BoolProperty(
        name="Shade Smooth", description="Smooth-shade tile tops and side walls",
        default=False, update=update_kinetic_tiles_shade_smooth_cb)

    _FBP_OBJECT_RNA.fbp_layered_echo_layers = IntProperty(
        name="Viewport", description="Number of shared textured plane instances shown while editing",
        default=8, min=1, soft_max=64, max=512, options={'ANIMATABLE'}, update=update_layered_echo_layers_cb)
    _FBP_OBJECT_RNA.fbp_layered_echo_playback_layers = IntProperty(
        name="Playback", description="Maximum number of array layers evaluated during timeline playback",
        default=6, min=1, soft_max=64, max=512, update=update_layered_echo_playback_layers_cb)
    _FBP_OBJECT_RNA.fbp_layered_echo_render_layers = IntProperty(
        name="Render", description="Number of array layers evaluated for final rendering",
        default=16, min=1, soft_max=128, max=512, update=update_layered_echo_render_layers_cb)
    _FBP_OBJECT_RNA.fbp_layered_echo_offset_x = FloatProperty(
        name="Offset X", description="Per-layer horizontal offset",
        default=0.0, min=-10.0, max=10.0, soft_min=-0.5, soft_max=0.5,
        subtype='DISTANCE', options={'ANIMATABLE'}, update=update_layered_echo_offset_x_cb)
    _FBP_OBJECT_RNA.fbp_layered_echo_offset_y = FloatProperty(
        name="Offset Y", description="Per-layer vertical offset",
        default=0.0, min=-10.0, max=10.0, soft_min=-0.5, soft_max=0.5,
        subtype='DISTANCE', options={'ANIMATABLE'}, update=update_layered_echo_offset_y_cb)
    _FBP_OBJECT_RNA.fbp_layered_echo_spacing = FloatProperty(
        name="Spacing", description="Distance between successive array layers",
        default=0.025, min=-10.0, max=10.0, soft_min=-0.5, soft_max=0.5,
        subtype='DISTANCE', options={'ANIMATABLE'}, update=update_layered_echo_spacing_cb)
    _FBP_OBJECT_RNA.fbp_layered_echo_scale_step = FloatProperty(
        name="Scale Step", description="Per-layer scale change; negative values taper the stack",
        default=-0.025, min=-10.0, max=10.0, soft_min=-0.25, soft_max=0.25,
        options={'ANIMATABLE'}, update=update_layered_echo_scale_step_cb)
    _FBP_OBJECT_RNA.fbp_layered_echo_rotation_x = FloatProperty(
        name="Rotation X", description="Per-layer rotation around local X",
        default=0.0, min=-100.0, max=100.0, subtype='ANGLE', options={'ANIMATABLE'}, update=update_layered_echo_rotation_x_cb)
    _FBP_OBJECT_RNA.fbp_layered_echo_rotation_y = FloatProperty(
        name="Rotation Y", description="Per-layer rotation around local Y",
        default=0.0, min=-100.0, max=100.0, subtype='ANGLE', options={'ANIMATABLE'}, update=update_layered_echo_rotation_y_cb)
    _FBP_OBJECT_RNA.fbp_layered_echo_twist = FloatProperty(
        name="Twist", description="Base rotation added by every successive layer",
        default=0.08, min=-100.0, max=100.0, subtype='ANGLE', options={'ANIMATABLE'}, update=update_layered_echo_twist_cb)
    _FBP_OBJECT_RNA.fbp_layered_echo_wave = FloatProperty(
        name="Wave", description="Animated alternating rotation layered over the base twist",
        default=0.12, min=-6.283185, max=6.283185, subtype='ANGLE', options={'ANIMATABLE'}, update=update_layered_echo_wave_cb)
    _FBP_OBJECT_RNA.fbp_layered_echo_phase = FloatProperty(
        name="Phase", description="Starting phase for the animated layer wave",
        default=0.0, soft_min=-100.0, soft_max=100.0, options={'ANIMATABLE'}, update=update_layered_echo_phase_cb)

    _FBP_OBJECT_RNA.fbp_wind_subdivision = IntProperty(description="Viewport mesh subdivision level used by Wind. Higher values bend more smoothly but increase viewport cost.", name="Viewport", default=3, min=0, max=6, update=update_wind_subdivision_cb)
    _FBP_OBJECT_RNA.fbp_wind_playback_subdivision = IntProperty(description="Maximum Wind subdivision level used during timeline playback. Lower values keep playback responsive.", name="Playback", default=2, min=0, max=6, update=update_wind_playback_subdivision_cb)
    _FBP_OBJECT_RNA.fbp_wind_render_subdivision = IntProperty(description="Subdivision level used by Wind during final render.", name="Render", default=4, min=0, max=6, update=update_wind_render_subdivision_cb)
    _FBP_OBJECT_RNA.fbp_wind_stepped = IntProperty(description="Number of frames each Wind deformation state is held. Set to 1 for continuous per-frame motion.", name="Stepped", default=1, min=1, soft_max=24, update=update_wind_stepped_cb)

    # 4.9 Geometry effect quality contract reference implementation.

    # 4.9.2 Paper Curl uses the shared Geometry Nodes quality contract.

    # Reusable alpha-to-geometry contract reference effect.
    _FBP_OBJECT_RNA.fbp_lattice_object = PointerProperty(name="Lattice", description="Native editable Lattice cage generated around the linked Frame By Plane plane. Deform it in Edit Mode; Object Mode transforms are locked for stability.", type=bpy.types.Object)
    _FBP_OBJECT_RNA.fbp_lattice_mode = EnumProperty(
        name="Mode",
        description="Use the Lattice as a manually editable cage or bake the current camera-space perspective onto a plane parallel to the active camera",
        items=[
            ('FREEFORM', 'Freeform', 'Edit the native Lattice control points in Edit Mode; select all points to move, rotate or scale the full cage'),
            ('CAMERA_FLATTEN', 'Camera Flatten', 'Bake the plane perspective into the Lattice so the deformed surface becomes parallel to the active camera'),
        ],
        default='FREEFORM',
        update=update_lattice_camera_settings_cb,
    )
    _FBP_OBJECT_RNA.fbp_lattice_flatten_influence = FloatProperty(
        name="Flatten Influence",
        description="Blend between the original 3D plane and the camera-parallel flattened result while preserving its current camera projection",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR',
        options={'ANIMATABLE'}, update=update_lattice_camera_settings_cb,
    )
    _FBP_OBJECT_RNA.fbp_lattice_live_update = BoolProperty(
        name="Live Update",
        description="Recalculate Camera Flatten while the plane, its parents or the active camera move. Disable it to keep the current Lattice shape as a lightweight baked correction",
        default=True, update=update_lattice_camera_settings_cb,
    )
    _FBP_OBJECT_RNA.fbp_lattice_show_cage = BoolProperty(
        name="Cage",
        description="Show the non-rendering Lattice cage in the viewport while the effect is enabled",
        default=True, update=update_lattice_visibility_cb,
    )
    _FBP_OBJECT_RNA.fbp_lattice_grid_preset = EnumProperty(
        name="Cage Grid",
        description="Choose the number of internal planar control loops. Corners uses only the four corner points; the numbered presets count internal loops rather than corner points",
        items=[
            ('CORNERS', 'Corners', 'Four corner points with no internal control loops'),
            ('BASIC', 'Basic (1 × 1)', 'One internal control loop on each axis'),
            ('LOOPS_2', '2 × 2', 'Two internal control loops on each axis'),
            ('LOOPS_4', '4 × 4', 'Four internal control loops on each axis'),
            ('CUSTOM', 'Custom', 'Set horizontal and vertical internal loop counts independently or keep them linked'),
        ],
        default='LOOPS_2', update=update_lattice_grid_preset_cb,
    )
    _FBP_OBJECT_RNA.fbp_lattice_link_loops = BoolProperty(
        name="Link Loop Counts",
        description="Keep horizontal and vertical custom loop counts equal. Disable the chain to create rectangular grids such as 2 × 6 or 4 × 1",
        default=True, update=update_lattice_loop_link_cb,
    )
    _FBP_OBJECT_RNA.fbp_lattice_custom_loops_u = IntProperty(
        name="Horizontal Loops",
        description="Number of internal vertical control loops across the plane. Corner points are added automatically and are not included in this value",
        default=6, min=0, max=62, soft_max=16, update=update_lattice_custom_loops_u_cb,
    )
    _FBP_OBJECT_RNA.fbp_lattice_custom_loops_v = IntProperty(
        name="Vertical Loops",
        description="Number of internal horizontal control loops across the plane. Corner points are added automatically and are not included in this value",
        default=6, min=0, max=62, soft_max=16, update=update_lattice_custom_loops_v_cb,
    )
    _FBP_OBJECT_RNA.fbp_lattice_mesh_detail_mode = EnumProperty(
        name="Mesh Detail",
        description="Automatically derive the deformable plane density from the cage grid, or set Blender Simple Subdivision levels manually",
        items=[
            ('AUTO', 'Automatic', 'Choose enough mesh subdivisions from the cage grid and Density setting'),
            ('CUSTOM', 'Custom', 'Set Blender Simple Subdivision levels directly'),
        ],
        default='AUTO', update=update_lattice_mesh_detail_cb,
    )
    _FBP_OBJECT_RNA.fbp_lattice_mesh_density = EnumProperty(
        name="Density",
        description="Target deformable mesh density relative to the number of planar Lattice cells",
        items=[
            ('MATCH', 'Match Cage', 'Use approximately one deformable face segment for each cage cell'),
            ('DOUBLE', '2× Cage', 'Use approximately twice as many deformable face segments as cage cells'),
            ('QUADRUPLE', '4× Cage', 'Use approximately four times as many deformable face segments as cage cells'),
        ],
        default='DOUBLE', update=update_lattice_mesh_detail_cb,
    )
    _FBP_OBJECT_RNA.fbp_lattice_mesh_subdivisions = IntProperty(
        name="Subdivision Levels",
        description="Custom Blender Simple Subdivision levels applied before the Lattice. Each level doubles the mesh segments per axis",
        default=2, min=0, max=6, soft_max=4, update=update_lattice_mesh_detail_cb,
    )
    _FBP_OBJECT_RNA.fbp_lattice_points_u = IntProperty(name="Cage Columns", description="Number of planar control-point columns along the plane local X axis. Changing it rebuilds the cage and resets current point edits.", default=4, min=2, max=64, update=update_lattice_effect_cb)
    _FBP_OBJECT_RNA.fbp_lattice_points_v = IntProperty(name="Cage Rows", description="Number of planar control-point rows along the plane local Y axis. Changing it rebuilds the cage and resets current point edits.", default=4, min=2, max=64, update=update_lattice_effect_cb)
    _FBP_OBJECT_RNA.fbp_lattice_interpolation = EnumProperty(name="Interpolation", description="Interpolation used between Lattice control points. This can be changed without resetting the current deformation.", items=[('LINEAR','Linear','Linear interpolation'),('CARDINAL','Cardinal','Cardinal interpolation'),('CATMULL_ROM','Catmull-Rom','Catmull-Rom interpolation'),('BSPLINE','B-Spline','Smooth B-Spline interpolation')], default='BSPLINE', update=update_lattice_interpolation_cb)
    _FBP_OBJECT_RNA.fbp_cutout_outline_viewport_resolution = IntProperty(
        name="Viewport Alpha Detail", description="Subdivision level used to trace the alpha silhouette while editing",
        default=4, min=0, max=8, update=update_cutout_outline_viewport_resolution_cb)
    _FBP_OBJECT_RNA.fbp_cutout_outline_playback_resolution = IntProperty(
        name="Playback Alpha Detail", description="Temporary alpha tracing detail used during timeline playback",
        default=2, min=0, max=8, update=update_cutout_outline_playback_resolution_cb)
    _FBP_OBJECT_RNA.fbp_cutout_outline_render_resolution = IntProperty(
        name="Render Alpha Detail", description="Temporary alpha tracing detail used for final rendering",
        default=6, min=0, max=8, update=update_cutout_outline_render_resolution_cb)
    _FBP_OBJECT_RNA.fbp_cutout_outline_alpha_threshold = FloatProperty(
        name="Alpha Threshold", description="Pixels below this alpha value are excluded from the cutout silhouette",
        default=0.05, min=0.0, max=1.0, subtype='FACTOR', options={'ANIMATABLE'},
        update=update_cutout_outline_alpha_threshold_cb)
    _FBP_OBJECT_RNA.fbp_cutout_outline_width = FloatProperty(
        name="Outline Width", description="World-space radius of the generated Cutout Outline geometry. Larger values create a thicker visible border around the source alpha silhouette.",
        default=0.012, min=0.00001, soft_max=0.25, max=10.0, subtype='DISTANCE', precision=5,
        options={'ANIMATABLE'}, update=update_cutout_outline_width_cb)
    _FBP_OBJECT_RNA.fbp_cutout_outline_offset = FloatProperty(
        name="Offset", description="Move the outline along the plane local Z axis",
        default=0.001, min=-10.0, max=10.0, soft_min=-0.1, soft_max=0.1,
        subtype='DISTANCE', precision=5, options={'ANIMATABLE'}, update=update_cutout_outline_offset_cb)
    _FBP_OBJECT_RNA.fbp_cutout_outline_color = FloatVectorProperty(
        description="RGBA color assigned to the generated Cutout Outline geometry.",
        name="Outline Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.02, 0.02, 0.02, 1.0), update=update_cutout_outline_color_cb)
    _FBP_OBJECT_RNA.fbp_cutout_outline_show_image = BoolProperty(name="Image", description="Keep the original image visible together with the generated outline.", default=True, update=update_cutout_outline_show_image_cb)
    _FBP_OBJECT_RNA.fbp_cutout_outline_wiggle_amount = FloatProperty(name="Wiggle Line", description="Procedural displacement applied to the generated outline. Zero keeps the contour perfectly stable.", default=0.0, min=0.0, soft_max=0.05, max=10.0, subtype='DISTANCE', update=update_cutout_outline_wiggle_amount_cb)
    _FBP_OBJECT_RNA.fbp_cutout_outline_wiggle_scale = FloatProperty(name="Wiggle Scale", description="Spatial frequency of the Cutout Outline line wiggle.", default=8.0, min=0.01, soft_max=64.0, max=1000.0, update=update_cutout_outline_wiggle_scale_cb)
    _FBP_OBJECT_RNA.fbp_cutout_outline_wiggle_phase = FloatProperty(name="Wiggle Phase", description="Animation phase used by Cutout Outline Evolution.", default=0.0, soft_min=-10.0, soft_max=10.0, min=-100000.0, max=100000.0, update=update_cutout_outline_wiggle_phase_cb)


    # Camera-space foundation reference effect.
    _FBP_OBJECT_RNA.fbp_camera_scale_lock_reference_distance = FloatProperty(
        name="Reference Distance",
        description="Camera-space depth at which the plane keeps its current apparent size",
        default=10.0, min=0.0001, soft_max=1000.0, max=1000000.0,
        precision=4, subtype='DISTANCE', options={'ANIMATABLE'},
        update=update_camera_scale_lock_reference_distance_cb)
    _FBP_OBJECT_RNA.fbp_camera_scale_lock_reference_lens = FloatProperty(
        name="Reference Lens",
        description="Focal length captured with the reference camera depth",
        default=50.0, min=0.1, soft_max=300.0, max=10000.0,
        precision=2, options={'ANIMATABLE'},
        update=update_camera_scale_lock_reference_lens_cb)
    _FBP_OBJECT_RNA.fbp_camera_scale_lock_reference_sensor_width = FloatProperty(
        name="Reference Sensor Width",
        description="Camera sensor width captured with the reference camera depth",
        default=36.0, min=0.1, soft_max=70.0, max=1000.0,
        precision=2, options={'ANIMATABLE'},
        update=update_camera_scale_lock_reference_sensor_width_cb)
    _FBP_OBJECT_RNA.fbp_camera_scale_lock_influence = FloatProperty(
        name="Influence",
        description="Blend between the original size and full projection-aware compensation",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR', options={'ANIMATABLE'},
        update=update_camera_scale_lock_influence_cb)

    _FBP_OBJECT_RNA.fbp_camera_billboard_mode = EnumProperty(
        description="Choose whether the complete Frame By Plane rig tracks the camera freely or keeps one local axis locked.",
        name="Tracking Mode",
        items=(('FULL', "Full", "Track the camera with full rig rotation"),
               ('HORIZONTAL', "Horizontal", "Keep the rig vertical while tracking horizontally"),
               ('VERTICAL', "Vertical", "Keep the rig horizontal while tracking vertically")),
        default='FULL', update=update_camera_billboard_mode_cb)
    _FBP_OBJECT_RNA.fbp_camera_billboard_flip = BoolProperty(
        name="Face Away", description="Track the opposite local Z direction when the layer faces away from the camera.",
        default=False, options={'ANIMATABLE'}, update=update_camera_billboard_flip_cb)
    _FBP_OBJECT_RNA.fbp_camera_billboard_influence = FloatProperty(
        name="Influence", description="Blend between the original rig rotation and full camera tracking.",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR', options={'ANIMATABLE'}, update=update_camera_billboard_influence_cb)
    _FBP_OBJECT_RNA.fbp_mirror_x = BoolProperty(
        name="Mirror X", description="Mirror the plane horizontally around the rig pivot.",
        default=True, options={'ANIMATABLE'}, update=update_mirror_x_cb)
    _FBP_OBJECT_RNA.fbp_mirror_y = BoolProperty(
        name="Mirror Y", description="Mirror the plane vertically around the rig pivot.",
        default=False, options={'ANIMATABLE'}, update=update_mirror_y_cb)

    _FBP_OBJECT_RNA.fbp_thickness_viewport_pixels_x = IntProperty(
        name="Viewport Alpha Pixels X", description="Exact horizontal alpha samples used by Extrude while editing",
        default=128, min=1, soft_max=1024, max=4096, update=update_thickness_viewport_pixels_x_cb)
    _FBP_OBJECT_RNA.fbp_thickness_viewport_pixels_y = IntProperty(
        name="Viewport Alpha Pixels Y", description="Exact vertical alpha samples used by Extrude while editing",
        default=128, min=1, soft_max=1024, max=4096, update=update_thickness_viewport_pixels_y_cb)
    _FBP_OBJECT_RNA.fbp_thickness_playback_pixels_x = IntProperty(
        name="Playback Alpha Pixels X", description="Exact horizontal alpha samples temporarily used by Extrude during playback",
        default=64, min=1, soft_max=1024, max=4096, update=update_thickness_playback_pixels_x_cb)
    _FBP_OBJECT_RNA.fbp_thickness_playback_pixels_y = IntProperty(
        name="Playback Alpha Pixels Y", description="Exact vertical alpha samples temporarily used by Extrude during playback",
        default=64, min=1, soft_max=1024, max=4096, update=update_thickness_playback_pixels_y_cb)
    _FBP_OBJECT_RNA.fbp_thickness_render_pixels_x = IntProperty(
        name="Render Alpha Pixels X", description="Exact horizontal alpha samples used by Extrude for final rendering",
        default=256, min=1, soft_max=2048, max=4096, update=update_thickness_render_pixels_x_cb)
    _FBP_OBJECT_RNA.fbp_thickness_render_pixels_y = IntProperty(
        name="Render Alpha Pixels Y", description="Exact vertical alpha samples used by Extrude for final rendering",
        default=256, min=1, soft_max=2048, max=4096, update=update_thickness_render_pixels_y_cb)
    _FBP_OBJECT_RNA.fbp_thickness_grid_mode = EnumProperty(
        name="Extrude Grid Mode",
        description="Derive Pixels Y from the plane aspect ratio or use an exact X by Y alpha grid",
        items=(
            ('AUTO', "Auto Height", "Set Pixels X and derive Pixels Y so Extrude cells remain square", 'FULLSCREEN_ENTER', 0),
            ('EXACT', "Exact Grid", "Enter independent Pixels X and Pixels Y values", 'MESH_GRID', 1),
        ),
        default='AUTO', update=update_thickness_grid_mode_cb)
    _FBP_OBJECT_RNA.fbp_thickness_follow_pixelate = BoolProperty(
        name="Follow Pixelate",
        description="When Pixelate is present, use its effective X by Y grid for the Extrude silhouette",
        default=True, update=update_thickness_follow_pixelate_cb)
    _FBP_OBJECT_RNA.fbp_thickness_safe_grid = BoolProperty(
        name="Safe Grid Limits",
        description="Limit the effective Extrude alpha grid per quality profile to avoid multi-million-cell geometry. Disable only for deliberate high-resolution final work.",
        default=True, update=update_thickness_safe_grid_cb)
    _FBP_OBJECT_RNA.fbp_thickness_mode = EnumProperty(
        name="Method", description="Volume creates real alpha-derived side walls; Array repeats the complete textured plane through the chosen depth.",
        items=(('VOLUME', "Volume", "Generate front, back and alpha-derived side walls"), ('ARRAY', "Array", "Create a fake extrusion from repeated textured planes")),
        default='VOLUME', update=update_thickness_mode_cb)
    _FBP_OBJECT_RNA.fbp_thickness_array_count = IntProperty(
        name="Array Copies", description="Number of textured plane copies distributed across the Extrude depth in Array mode.",
        default=12, min=2, soft_max=48, max=128, update=update_thickness_array_count_cb)
    _FBP_OBJECT_RNA.fbp_thickness_amount = FloatProperty(description="Depth of the Extrude side walls. Zero removes the generated volume.", name="Thickness", default=0.02, min=0.0, soft_max=0.25, max=10.0, precision=4, subtype='DISTANCE', options={'ANIMATABLE'}, update=update_thickness_amount_cb)
    _FBP_OBJECT_RNA.fbp_thickness_direction = FloatProperty(name="Direction", description="-1 extrudes behind the plane; +1 extrudes toward local front", default=-1.0, min=-1.0, max=1.0, options={'ANIMATABLE'}, update=update_thickness_direction_cb)
    _FBP_OBJECT_RNA.fbp_thickness_side_material = PointerProperty(description="Optional material assigned to Extrude side faces. Leave empty to use the side color instead.", name="Side Material", type=bpy.types.Material, update=update_thickness_side_material_cb)
    _FBP_OBJECT_RNA.fbp_thickness_side_color = FloatVectorProperty(description="RGBA fallback color used on Extrude side faces when no custom material is assigned.", name="Side Color", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.18, 0.12, 0.08, 1.0), update=update_thickness_side_color_cb)
    _FBP_OBJECT_RNA.fbp_thickness_use_plane_colors = BoolProperty(
        name="Use Plane Colors",
        description="Use the animated plane material on Extrude side faces so their colors follow the current image or pixel-art frame",
        default=False,
        update=update_thickness_use_plane_colors_cb,
    )
    _FBP_OBJECT_RNA.fbp_thickness_alpha_threshold = FloatProperty(description="Minimum source alpha included in the Extrude silhouette. Increase to remove translucent edge fringes.", name="Alpha Threshold", default=0.05, min=0.0, max=1.0, subtype='FACTOR', options={'ANIMATABLE'}, update=update_thickness_alpha_threshold_cb)

    _FBP_OBJECT_RNA.fbp_infinite_rotation_speed = FloatProperty(name="Speed", description="Automatic rotation speed in degrees per timeline frame. Negative values reverse direction and zero produces no time-based rotation.", default=1.0, min=0.0, soft_max=30.0, precision=3, update=update_infinite_rotation_speed_cb)
    _FBP_OBJECT_RNA.fbp_infinite_rotation_direction = EnumProperty(description="Direction of automatic Infinite Rotation around the configured axis.", name="Direction", items=(('RIGHT', "Clockwise", "Rotate clockwise"), ('LEFT', "Counter-clockwise", "Rotate counter-clockwise")), default='RIGHT', update=update_infinite_rotation_direction_cb)
    _FBP_OBJECT_RNA.fbp_infinite_rotation_stepped = IntProperty(description="Number of frames each Infinite Rotation angle is held. Set to 1 for smooth motion or higher values for stepped animation.", name="Stepped", default=1, min=1, soft_max=24, update=update_infinite_rotation_stepped_cb)
    _FBP_OBJECT_RNA.fbp_infinite_rotation_offset = FloatProperty(description="Manual angular offset added to Infinite Rotation without changing its speed or direction.", name="Offset (°)", default=0.0, soft_min=-360.0, soft_max=360.0, precision=2, update=update_infinite_rotation_offset_cb)

    # Shader effects
    _FBP_OBJECT_RNA.fbp_uv_distortion_scale = FloatProperty(description="Spatial scale of the procedural noise used to distort image UV coordinates. Higher values create smaller distortion features.",
        name="Noise Scale", default=10.0, min=0.001, soft_max=100.0, precision=3, update=update_uv_distortion_scale_cb)
    _FBP_OBJECT_RNA.fbp_uv_distortion_amount = FloatProperty(description="Strength of UV displacement applied to the image texture. Zero preserves the original mapping.",
        name="Distortion Amount", default=0.05, soft_min=-1.0, soft_max=1.0, precision=3, update=update_uv_distortion_amount_cb)
    _FBP_OBJECT_RNA.fbp_uv_distortion_evolution = FloatProperty(description="Phase of the four-dimensional turbulence field. Animate this value to evolve the pattern without changing distortion strength.",
        name="Evolution", default=0.0, soft_min=-100.0, soft_max=100.0, precision=3, options={'ANIMATABLE'}, update=update_uv_distortion_evolution_cb)
    _FBP_OBJECT_RNA.fbp_pixelate_grid_mode = EnumProperty(
        name="Pixel Grid Mode",
        description="Choose automatic square cells or an explicit horizontal and vertical pixel grid.",
        items=(
            ('AUTO', "Auto Height", "Set the horizontal pixel count and derive the vertical count so cells remain square", 'FULLSCREEN_ENTER', 0),
            ('EXACT', "Exact Grid", "Enter an explicit pixel grid such as 16 by 10 or 1920 by 1080", 'MESH_GRID', 1),
        ),
        default='AUTO', update=update_pixelate_grid_mode_cb)
    _FBP_OBJECT_RNA.fbp_pixelate_size = FloatProperty(
        name="Size",
        description="Figma-style tile size. Lower values create more/smaller tiles; higher values create chunkier pixels.",
        default=10.0, min=1.0, soft_max=128.0, max=512.0, precision=1, update=update_pixelate_size_cb)
    _FBP_OBJECT_RNA.fbp_pixelate_stretch = FloatProperty(
        name="Stretch",
        description="Stretch tile height as a percentage while preserving the layer aspect contract.",
        default=1.0, min=0.05, soft_max=3.0, max=10.0, subtype='FACTOR', update=update_pixelate_stretch_cb)
    _FBP_OBJECT_RNA.fbp_pixelate_resolution = IntProperty(
        name="Pixels X", description="Horizontal grid count used in Exact Grid mode and by effects that follow the Pixelate grid.",
        default=64, min=1, soft_max=2048, max=8192, update=update_pixelate_resolution_cb)
    _FBP_OBJECT_RNA.fbp_pixelate_height = IntProperty(
        name="Pixels Y", description="Vertical grid count used in Exact Grid mode.",
        default=36, min=1, soft_max=2048, max=8192, update=update_pixelate_height_cb)
    _FBP_OBJECT_RNA.fbp_pixelate_rotation = FloatProperty(name="Rotation", description="Rotate the complete Pixelate sampling grid around the image center.", default=0.0, min=-6.283185307, max=6.283185307, subtype='ANGLE', update=update_pixelate_rotation_cb)
    _FBP_OBJECT_RNA.fbp_pixelate_offset_x = FloatProperty(name="Offset X", description="Move the Pixelate grid horizontally without moving the plane.", default=0.0, soft_min=-0.5, soft_max=0.5, min=-1.0, max=1.0, update=update_pixelate_offset_x_cb)
    _FBP_OBJECT_RNA.fbp_pixelate_offset_y = FloatProperty(name="Offset Y", description="Move the Pixelate grid vertically without moving the plane.", default=0.0, soft_min=-0.5, soft_max=0.5, min=-1.0, max=1.0, update=update_pixelate_offset_y_cb)

    _FBP_OBJECT_RNA.fbp_swirl_center_x = FloatProperty(name="Center X", description="Horizontal center of the Swirl in normalized image coordinates.", default=0.5, soft_min=0.0, soft_max=1.0, min=-2.0, max=3.0, update=update_swirl_center_x_cb)
    _FBP_OBJECT_RNA.fbp_swirl_center_y = FloatProperty(name="Center Y", description="Vertical center of the Swirl in normalized image coordinates.", default=0.5, soft_min=0.0, soft_max=1.0, min=-2.0, max=3.0, update=update_swirl_center_y_cb)
    _FBP_OBJECT_RNA.fbp_swirl_radius = FloatProperty(name="Radius", description="Normalized radius affected by Swirl.", default=0.5, min=0.001, soft_max=1.5, max=4.0, update=update_swirl_radius_cb)
    _FBP_OBJECT_RNA.fbp_swirl_angle = FloatProperty(name="Angle", description="Maximum twist at the center of Swirl.", default=3.141592654, min=-25.13274123, max=25.13274123, subtype='ANGLE', update=update_swirl_angle_cb)
    _FBP_OBJECT_RNA.fbp_swirl_factor = FloatProperty(name="Factor", description="Blend between the original and swirled UV coordinates.", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_swirl_factor_cb)

    _FBP_OBJECT_RNA.fbp_bulge_pinch_center_x = FloatProperty(name="Center X", description="Horizontal center of the Bulge or Pinch.", default=0.5, soft_min=0.0, soft_max=1.0, min=-2.0, max=3.0, update=update_bulge_pinch_center_x_cb)
    _FBP_OBJECT_RNA.fbp_bulge_pinch_center_y = FloatProperty(name="Center Y", description="Vertical center of the Bulge or Pinch.", default=0.5, soft_min=0.0, soft_max=1.0, min=-2.0, max=3.0, update=update_bulge_pinch_center_y_cb)
    _FBP_OBJECT_RNA.fbp_bulge_pinch_radius = FloatProperty(name="Radius", description="Normalized radius affected by Bulge or Pinch.", default=0.5, min=0.001, soft_max=1.5, max=4.0, update=update_bulge_pinch_radius_cb)
    _FBP_OBJECT_RNA.fbp_bulge_pinch_strength = FloatProperty(name="Strength", description="Positive values bulge the image outward; negative values pinch it inward.", default=0.5, min=-2.0, max=2.0, update=update_bulge_pinch_strength_cb)
    _FBP_OBJECT_RNA.fbp_bulge_pinch_factor = FloatProperty(name="Factor", description="Blend between original and Bulge or Pinch distortion.", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_bulge_pinch_factor_cb)

    _FBP_OBJECT_RNA.fbp_lens_warp_center_x = FloatProperty(name="Center X", description="Horizontal optical center of Lens Warp.", default=0.5, soft_min=0.0, soft_max=1.0, min=-2.0, max=3.0, update=update_lens_warp_center_x_cb)
    _FBP_OBJECT_RNA.fbp_lens_warp_center_y = FloatProperty(name="Center Y", description="Vertical optical center of Lens Warp.", default=0.5, soft_min=0.0, soft_max=1.0, min=-2.0, max=3.0, update=update_lens_warp_center_y_cb)
    _FBP_OBJECT_RNA.fbp_lens_warp_distortion = FloatProperty(name="Distortion", description="Barrel or pincushion radial distortion. Positive and negative values bend in opposite directions.", default=0.0, min=-4.0, max=4.0, update=update_lens_warp_distortion_cb)
    _FBP_OBJECT_RNA.fbp_lens_warp_zoom = FloatProperty(name="Zoom", description="Compensating zoom applied after radial Lens Warp.", default=1.0, min=0.01, soft_max=2.0, max=8.0, update=update_lens_warp_zoom_cb)
    _FBP_OBJECT_RNA.fbp_lens_warp_factor = FloatProperty(name="Factor", description="Blend between original and lens-warped UV coordinates.", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_lens_warp_factor_cb)

    _FBP_OBJECT_RNA.fbp_wave_warp_amplitude = FloatProperty(name="Amplitude", description="Maximum normalized displacement produced by Wave Warp.", default=0.025, soft_min=-0.25, soft_max=0.25, min=-1.0, max=1.0, update=update_wave_warp_amplitude_cb)
    _FBP_OBJECT_RNA.fbp_wave_warp_frequency = FloatProperty(name="Frequency", description="Number of Wave Warp oscillations across the image.", default=6.0, min=0.01, soft_max=32.0, max=256.0, update=update_wave_warp_frequency_cb)
    _FBP_OBJECT_RNA.fbp_wave_warp_phase = FloatProperty(name="Starting Phase", description="Starting phase of Wave Warp.", default=0.0, soft_min=-6.283185307, soft_max=6.283185307, min=-1000.0, max=1000.0, subtype='ANGLE', update=update_wave_warp_phase_cb)
    _FBP_OBJECT_RNA.fbp_wave_warp_angle = FloatProperty(name="Angle", description="Direction of the Wave Warp bands.", default=0.0, min=-6.283185307, max=6.283185307, subtype='ANGLE', update=update_wave_warp_angle_cb)
    _FBP_OBJECT_RNA.fbp_wave_warp_factor = FloatProperty(name="Factor", description="Blend between original and Wave distortion.", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_wave_warp_factor_cb)
    _FBP_OBJECT_RNA.fbp_wave_warp_speed = FloatProperty(name="Speed", description="Multiplier applied to automatic Wave Evolution. Zero freezes the animation.", default=1.0, min=-20.0, max=20.0, update=update_wave_warp_speed_cb)

    _FBP_OBJECT_RNA.fbp_ripple_distortion_center_x = FloatProperty(name="Center X", description="Horizontal center of Ripple Distortion.", default=0.5, soft_min=0.0, soft_max=1.0, min=-2.0, max=3.0, update=update_ripple_distortion_center_x_cb)
    _FBP_OBJECT_RNA.fbp_ripple_distortion_center_y = FloatProperty(name="Center Y", description="Vertical center of Ripple Distortion.", default=0.5, soft_min=0.0, soft_max=1.0, min=-2.0, max=3.0, update=update_ripple_distortion_center_y_cb)
    _FBP_OBJECT_RNA.fbp_ripple_distortion_amplitude = FloatProperty(name="Amplitude", description="Maximum radial UV displacement produced by Ripple Distortion.", default=0.02, soft_min=-0.25, soft_max=0.25, min=-1.0, max=1.0, update=update_ripple_distortion_amplitude_cb)
    _FBP_OBJECT_RNA.fbp_ripple_distortion_frequency = FloatProperty(name="Frequency", description="Number of radial ripple oscillations per normalized image unit.", default=12.0, min=0.01, soft_max=64.0, max=512.0, update=update_ripple_distortion_frequency_cb)
    _FBP_OBJECT_RNA.fbp_ripple_distortion_phase = FloatProperty(name="Starting Phase", description="Starting phase of Ripple Distortion.", default=0.0, soft_min=-6.283185307, soft_max=6.283185307, min=-1000.0, max=1000.0, subtype='ANGLE', update=update_ripple_distortion_phase_cb)
    _FBP_OBJECT_RNA.fbp_ripple_distortion_radius = FloatProperty(name="Radius", description="Normalized maximum radius reached by Ripple Distortion.", default=0.75, min=0.001, soft_max=1.5, max=4.0, update=update_ripple_distortion_radius_cb)
    _FBP_OBJECT_RNA.fbp_ripple_distortion_falloff = FloatProperty(name="Falloff", description="How rapidly Ripple Distortion fades near its outer radius.", default=1.0, min=0.05, soft_max=4.0, max=8.0, update=update_ripple_distortion_falloff_cb)
    _FBP_OBJECT_RNA.fbp_ripple_distortion_factor = FloatProperty(name="Factor", description="Blend between original and circular Wave coordinates.", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_ripple_distortion_factor_cb)
    _FBP_OBJECT_RNA.fbp_ripple_distortion_speed = FloatProperty(name="Speed", description="Multiplier applied to automatic circular Wave Evolution. Zero freezes the animation.", default=1.0, min=-20.0, max=20.0, update=update_ripple_distortion_speed_cb)

    _FBP_OBJECT_RNA.fbp_kaleidoscope_center_x = FloatProperty(name="Center X", description="Horizontal center of the Kaleidoscope.", default=0.5, soft_min=0.0, soft_max=1.0, min=-2.0, max=3.0, update=update_kaleidoscope_center_x_cb)
    _FBP_OBJECT_RNA.fbp_kaleidoscope_center_y = FloatProperty(name="Center Y", description="Vertical center of the Kaleidoscope.", default=0.5, soft_min=0.0, soft_max=1.0, min=-2.0, max=3.0, update=update_kaleidoscope_center_y_cb)
    _FBP_OBJECT_RNA.fbp_kaleidoscope_segments = IntProperty(name="Segments", description="Number of mirrored radial Kaleidoscope segments.", default=6, min=1, soft_max=24, max=64, update=update_kaleidoscope_segments_cb)
    _FBP_OBJECT_RNA.fbp_kaleidoscope_rotation = FloatProperty(name="Rotation", description="Rotate the Kaleidoscope segment pattern.", default=0.0, min=-6.283185307, max=6.283185307, subtype='ANGLE', update=update_kaleidoscope_rotation_cb)
    _FBP_OBJECT_RNA.fbp_kaleidoscope_factor = FloatProperty(name="Factor", description="Blend between original and Kaleidoscope mapping.", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_kaleidoscope_factor_cb)

    _FBP_OBJECT_RNA.fbp_hex_pixelate_cells_x = IntProperty(name="Cells X", description="Horizontal resolution of the staggered Hex Pixelate grid.", default=48, min=1, soft_max=512, max=8192, update=update_hex_pixelate_cells_x_cb)
    _FBP_OBJECT_RNA.fbp_hex_pixelate_cells_y = IntProperty(name="Cells Y", description="Vertical resolution of the staggered Hex Pixelate grid.", default=32, min=1, soft_max=512, max=8192, update=update_hex_pixelate_cells_y_cb)
    _FBP_OBJECT_RNA.fbp_hex_pixelate_rotation = FloatProperty(name="Rotation", description="Rotate the staggered Hex Pixelate grid around the image center.", default=0.0, min=-6.283185307, max=6.283185307, subtype='ANGLE', update=update_hex_pixelate_rotation_cb)
    _FBP_OBJECT_RNA.fbp_hex_pixelate_factor = FloatProperty(name="Factor", description="Blend between original and Hex Pixelate mapping.", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_hex_pixelate_factor_cb)

    _FBP_OBJECT_RNA.fbp_mosaic_jitter_cells_x = IntProperty(name="Cells X", description="Horizontal number of Mosaic Jitter blocks.", default=32, min=1, soft_max=512, max=8192, update=update_mosaic_jitter_cells_x_cb)
    _FBP_OBJECT_RNA.fbp_mosaic_jitter_cells_y = IntProperty(name="Cells Y", description="Vertical number of Mosaic Jitter blocks.", default=18, min=1, soft_max=512, max=8192, update=update_mosaic_jitter_cells_y_cb)
    _FBP_OBJECT_RNA.fbp_mosaic_jitter_rotation = FloatProperty(name="Rotation", description="Rotate the Mosaic Jitter grid around the image center without rotating the plane.", default=0.0, min=-6.283185307, max=6.283185307, subtype='ANGLE', update=update_mosaic_jitter_rotation_cb)
    _FBP_OBJECT_RNA.fbp_mosaic_jitter_amount = FloatProperty(name="Jitter", description="Random sample displacement measured in cell widths. Values above one can overlap neighboring blocks.", default=0.6, min=0.0, soft_max=2.0, max=4.0, update=update_mosaic_jitter_amount_cb)
    _FBP_OBJECT_RNA.fbp_mosaic_jitter_offset_x = FloatProperty(name="Offset X", description="Move the Mosaic Jitter grid horizontally without moving the plane.", default=0.0, soft_min=-0.5, soft_max=0.5, min=-2.0, max=2.0, update=update_mosaic_jitter_offset_x_cb)
    _FBP_OBJECT_RNA.fbp_mosaic_jitter_offset_y = FloatProperty(name="Offset Y", description="Move the Mosaic Jitter grid vertically without moving the plane.", default=0.0, soft_min=-0.5, soft_max=0.5, min=-2.0, max=2.0, update=update_mosaic_jitter_offset_y_cb)
    _FBP_OBJECT_RNA.fbp_mosaic_jitter_seed = IntProperty(name="Seed", description="Random pattern seed used by Mosaic Jitter.", default=0, min=-100000, max=100000, update=update_mosaic_jitter_seed_cb)
    _FBP_OBJECT_RNA.fbp_mosaic_jitter_factor = FloatProperty(name="Factor", description="Blend between original and Mosaic Jitter mapping.", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_mosaic_jitter_factor_cb)
    _FBP_OBJECT_RNA.fbp_slice_shift_angle = FloatProperty(
        description="Angle of the Figma-inspired Slice Shift bands.",
        name="Angle", default=0.0, soft_min=-3.141593, soft_max=3.141593, subtype='ANGLE', update=update_slice_shift_angle_cb)
    _FBP_OBJECT_RNA.fbp_slice_shift_bands = FloatProperty(
        description="Number of angled bands used by Slice Shift. Higher values create thinner slices.",
        name="Bands", default=18.0, min=1.0, soft_max=96.0, max=512.0, precision=0, update=update_slice_shift_bands_cb)
    _FBP_OBJECT_RNA.fbp_slice_shift_shift = FloatProperty(
        description="UV offset applied to each Slice Shift band along the band direction.",
        name="Shift", default=0.08, soft_min=-0.5, soft_max=0.5, min=-2.0, max=2.0, precision=4, update=update_slice_shift_shift_cb)
    _FBP_OBJECT_RNA.fbp_slice_shift_random = FloatProperty(
        description="Per-band random offset added to Slice Shift for a more handmade/glitch look.",
        name="Random", default=0.0, min=0.0, soft_max=0.4, max=2.0, precision=4, update=update_slice_shift_random_cb)
    _FBP_OBJECT_RNA.fbp_slice_shift_seed = FloatProperty(
        description="Seed that changes the per-band random Slice Shift offsets.",
        name="Seed", default=0.0, soft_min=-100.0, soft_max=100.0, update=update_slice_shift_seed_cb)
    _FBP_OBJECT_RNA.fbp_slice_shift_factor = FloatProperty(
        description="Blend between the original UVs and the Slice Shift distortion.",
        name="Factor", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_slice_shift_factor_cb)
    _FBP_OBJECT_RNA.fbp_depth_blur_mode = EnumProperty(
        name="Blur Mode",
        description="Use a fixed manual radius or derive the radius from camera-space distance to the focus plane",
        items=(
            ('MANUAL', "Manual", "Use the same blur radius for the complete plane", 'MOD_SMOOTH', 0),
            ('DEPTH', "Depth", "Increase blur as the plane moves away from the focus distance", 'CAMERA_DATA', 1),
        ),
        default='MANUAL', update=update_depth_blur_mode_cb)
    _FBP_OBJECT_RNA.fbp_depth_blur_manual_radius = FloatProperty(
        name="Manual Radius", description="Blur radius in source-image pixels used in Manual mode",
        default=4.0, min=0.0, soft_max=32.0, max=256.0, precision=2,
        update=update_depth_blur_manual_radius_cb)
    _FBP_OBJECT_RNA.fbp_depth_blur_max_radius = FloatProperty(
        name="Maximum Radius", description="Maximum source-image blur radius reached in Depth mode",
        default=16.0, min=0.0, soft_max=64.0, max=256.0, precision=2,
        update=update_depth_blur_max_radius_cb)
    _FBP_OBJECT_RNA.fbp_depth_blur_use_camera_focus = BoolProperty(
        name="Use Camera Focus", description="Read Focus Distance or the Focus Object from the active scene camera",
        default=True, update=update_depth_blur_use_camera_focus_cb)
    _FBP_OBJECT_RNA.fbp_depth_blur_focus_distance = FloatProperty(
        name="Focus Distance", description="Camera-space distance that remains in focus when Camera Focus is disabled",
        default=10.0, min=0.0, soft_max=100.0, max=1000000.0, subtype='DISTANCE', precision=3,
        update=update_depth_blur_focus_distance_cb)
    _FBP_OBJECT_RNA.fbp_depth_blur_focus_range = FloatProperty(
        name="Focus Range", description="Distance around the focus plane that remains sharp",
        default=0.25, min=0.0, soft_max=10.0, max=1000000.0, subtype='DISTANCE', precision=3,
        update=update_depth_blur_focus_range_cb)
    _FBP_OBJECT_RNA.fbp_depth_blur_falloff = FloatProperty(
        name="Falloff", description="Distance required to reach the maximum blur outside the focus range",
        default=5.0, min=0.001, soft_max=50.0, max=1000000.0, subtype='DISTANCE', precision=3,
        update=update_depth_blur_falloff_cb)
    _FBP_OBJECT_RNA.fbp_depth_blur_near_strength = FloatProperty(
        name="Near Strength", description="Multiplier applied to layers closer than the focus plane",
        default=1.0, min=0.0, max=2.0, soft_max=1.0, subtype='FACTOR',
        update=update_depth_blur_near_strength_cb)
    _FBP_OBJECT_RNA.fbp_depth_blur_far_strength = FloatProperty(
        name="Far Strength", description="Multiplier applied to layers farther than the focus plane",
        default=1.0, min=0.0, max=2.0, soft_max=1.0, subtype='FACTOR',
        update=update_depth_blur_far_strength_cb)
    _FBP_OBJECT_RNA.fbp_gaussian_blur_radius_x = FloatProperty(
        name="Radius X",
        description="Horizontal Gaussian blur radius measured in source-image pixels. Zero disables horizontal spreading",
        default=4.0, min=0.0, soft_max=64.0, max=256.0, precision=2,
        update=update_gaussian_blur_radius_x_cb)
    _FBP_OBJECT_RNA.fbp_gaussian_blur_radius_y = FloatProperty(
        name="Radius Y",
        description="Vertical Gaussian blur radius measured in source-image pixels. Zero disables vertical spreading",
        default=4.0, min=0.0, soft_max=64.0, max=256.0, precision=2,
        update=update_gaussian_blur_radius_y_cb)
    _FBP_OBJECT_RNA.fbp_gaussian_blur_samples = IntProperty(
        description="Number of balanced texture samples used by Gaussian Blur. Higher values hide visible copies and create a smoother result at greater shader cost.",
        name="Samples", default=17, min=3, max=25, soft_min=5, soft_max=25, step=2,
        update=update_gaussian_blur_samples_cb)
    _FBP_OBJECT_RNA.fbp_gaussian_blur_factor = FloatProperty(
        name="Factor",
        description="Blend between the original layer and the alpha-safe Gaussian blur result",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR',
        update=update_gaussian_blur_factor_cb)
    _FBP_OBJECT_RNA.fbp_directional_blur_control_x = FloatProperty(
        name="Control X",
        description="Normalized horizontal viewport position of the Directional Blur controller; moving the helper updates this value without changing the sampled blur center",
        default=0.5, soft_min=0.0, soft_max=1.0, min=-2.0, max=3.0)
    _FBP_OBJECT_RNA.fbp_directional_blur_control_y = FloatProperty(
        name="Control Y",
        description="Normalized vertical viewport position of the Directional Blur controller; moving the helper updates this value without changing the sampled blur center",
        default=0.5, soft_min=0.0, soft_max=1.0, min=-2.0, max=3.0)
    _FBP_OBJECT_RNA.fbp_directional_blur_angle = FloatProperty(
        name="Angle",
        description="Direction of the blur streak. Zero points horizontally along the image X axis",
        default=0.0, soft_min=-3.141593, soft_max=3.141593, subtype='ANGLE',
        update=update_directional_blur_angle_cb)
    _FBP_OBJECT_RNA.fbp_directional_blur_distance = FloatProperty(
        name="Distance",
        description="Total centered directional blur distance measured in source-image pixels",
        default=12.0, min=0.0, soft_max=128.0, max=512.0, precision=2,
        update=update_directional_blur_distance_cb)
    _FBP_OBJECT_RNA.fbp_directional_blur_samples = IntProperty(
        description="Number of centered texture copies used by Directional Blur. Higher values smooth long motion streaks while increasing shader cost.",
        name="Samples", default=17, min=3, max=25, soft_min=5, soft_max=25, step=2,
        update=update_directional_blur_samples_cb)
    _FBP_OBJECT_RNA.fbp_directional_blur_factor = FloatProperty(
        name="Factor",
        description="Blend between the original layer and the alpha-safe directional blur result",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR',
        update=update_directional_blur_factor_cb)
    _FBP_OBJECT_RNA.fbp_alpha_matte_source = PointerProperty(
        name="Source Layer", description="Frame By Plane image or sequence whose alpha channel masks this layer. The source is sampled in normalized UV space",
        type=bpy.types.Object, poll=_fbp_mask_source_poll, update=update_alpha_matte_source_cb)
    _FBP_OBJECT_RNA.fbp_alpha_matte_factor = FloatProperty(
        name="Factor", description="Blend between the original layer alpha and the Alpha Matte result",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_alpha_matte_factor_cb)
    _FBP_OBJECT_RNA.fbp_alpha_matte_invert = BoolProperty(
        name="Invert", description="Invert the source alpha before applying the matte",
        default=False, update=update_alpha_matte_invert_cb)
    _FBP_OBJECT_RNA.fbp_alpha_matte_use_source_transform = BoolProperty(
        name="Follow Source Transform",
        description="Project the matte through the source plane so its position, rotation and scale affect the target. Disable to sample both layers in normalized UV space",
        default=False, update=update_alpha_matte_use_source_transform_cb)
    _FBP_OBJECT_RNA.fbp_alpha_matte_source_display = EnumProperty(
        name="Source Display",
        description="Choose whether the source layer remains a normal rendered layer, works as a viewport-only guide, or stays hidden while still driving the matte",
        items=[
            ('NORMAL', "Normal", "Respect the source layer's normal viewport and render visibility"),
            ('GUIDE', "Guide", "Show the source in the viewport but hide it from final renders"),
            ('HIDDEN', "Hidden", "Hide the source in both viewport and render while keeping the matte active"),
        ],
        default='GUIDE', update=update_alpha_matte_source_display_cb)
    _FBP_OBJECT_RNA.fbp_alpha_matte_uv_offset_x = FloatProperty(
        name="Offset X", description="Move the sampled matte horizontally in UV space",
        default=0.0, soft_min=-2.0, soft_max=2.0, precision=3, update=update_alpha_matte_uv_offset_x_cb)
    _FBP_OBJECT_RNA.fbp_alpha_matte_uv_offset_y = FloatProperty(
        name="Offset Y", description="Move the sampled matte vertically in UV space",
        default=0.0, soft_min=-2.0, soft_max=2.0, precision=3, update=update_alpha_matte_uv_offset_y_cb)
    _FBP_OBJECT_RNA.fbp_alpha_matte_uv_scale_x = FloatProperty(
        name="Scale X", description="Scale the matte horizontally around its center; values above one make the matte larger",
        default=1.0, min=0.001, soft_max=4.0, max=1000.0, precision=3, update=update_alpha_matte_uv_scale_x_cb)
    _FBP_OBJECT_RNA.fbp_alpha_matte_uv_scale_y = FloatProperty(
        name="Scale Y", description="Scale the matte vertically around its center; values above one make the matte larger",
        default=1.0, min=0.001, soft_max=4.0, max=1000.0, precision=3, update=update_alpha_matte_uv_scale_y_cb)
    _FBP_OBJECT_RNA.fbp_alpha_matte_uv_rotation = FloatProperty(
        name="Rotation", description="Rotate the matte around the center of its sampled UV space",
        default=0.0, soft_min=-3.141593, soft_max=3.141593, subtype='ANGLE', update=update_alpha_matte_uv_rotation_cb)
    _FBP_OBJECT_RNA.fbp_luma_matte_source_type = EnumProperty(
        name="Source",
        description="Use another Frame By Plane sequence or import an external single image/video",
        items=(
            ('FBP_SEQUENCE', "Frame by Plane Sequence", "Use another Frame By Plane image or sequence layer"),
            ('FILE', "Import Single Image/Video", "Load an external image or movie directly as the Luma Matte"),
        ),
        default='FBP_SEQUENCE', update=update_luma_matte_source_type_cb)
    _FBP_OBJECT_RNA.fbp_luma_matte_source = PointerProperty(
        name="Source Layer", description="Frame By Plane image or sequence whose luminance masks this layer. The source is sampled in normalized UV space",
        type=bpy.types.Object, poll=_fbp_mask_source_poll, update=update_luma_matte_source_cb)
    _FBP_OBJECT_RNA.fbp_luma_matte_path = StringProperty(
        name="Image / Video", description="External single image or movie used as the Luma Matte",
        subtype='FILE_PATH', default="", update=update_luma_matte_path_cb)
    _FBP_OBJECT_RNA.fbp_luma_matte_image = PointerProperty(
        name="Loaded Matte Media", description="Image datablock loaded from the external Luma Matte path",
        type=bpy.types.Image, update=update_luma_matte_image_cb)
    _FBP_OBJECT_RNA.fbp_luma_matte_factor = FloatProperty(
        name="Factor", description="Blend between the original layer alpha and the Luma Matte result",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_luma_matte_factor_cb)
    _FBP_OBJECT_RNA.fbp_luma_matte_invert = BoolProperty(
        name="Invert", description="Invert the luminance matte before applying it",
        default=False, update=update_luma_matte_invert_cb)
    _FBP_OBJECT_RNA.fbp_luma_matte_threshold = FloatProperty(
        name="Threshold", description="Luminance value used as the center of the matte transition",
        default=0.5, min=0.0, max=1.0, subtype='FACTOR', update=update_luma_matte_threshold_cb)
    _FBP_OBJECT_RNA.fbp_luma_matte_softness = FloatProperty(
        name="Softness", description="Width of the smooth luminance transition around Threshold",
        default=0.15, min=0.0, max=1.0, subtype='FACTOR', update=update_luma_matte_softness_cb)
    _FBP_OBJECT_RNA.fbp_luma_matte_use_source_transform = BoolProperty(
        name="Follow Source Transform",
        description="Project the matte through the source plane so its position, rotation and scale affect the target. Disable to sample both layers in normalized UV space",
        default=False, update=update_luma_matte_use_source_transform_cb)
    _FBP_OBJECT_RNA.fbp_luma_matte_source_display = EnumProperty(
        name="Source Display",
        description="Choose whether the source layer remains a normal rendered layer, works as a viewport-only guide, or stays hidden while still driving the matte",
        items=[
            ('NORMAL', "Normal", "Respect the source layer's normal viewport and render visibility"),
            ('GUIDE', "Guide", "Show the source in the viewport but hide it from final renders"),
            ('HIDDEN', "Hidden", "Hide the source in both viewport and render while keeping the matte active"),
        ],
        default='GUIDE', update=update_luma_matte_source_display_cb)
    _FBP_OBJECT_RNA.fbp_luma_matte_uv_offset_x = FloatProperty(
        name="Offset X", description="Move the sampled matte horizontally in UV space",
        default=0.0, soft_min=-2.0, soft_max=2.0, precision=3, update=update_luma_matte_uv_offset_x_cb)
    _FBP_OBJECT_RNA.fbp_luma_matte_uv_offset_y = FloatProperty(
        name="Offset Y", description="Move the sampled matte vertically in UV space",
        default=0.0, soft_min=-2.0, soft_max=2.0, precision=3, update=update_luma_matte_uv_offset_y_cb)
    _FBP_OBJECT_RNA.fbp_luma_matte_uv_scale_x = FloatProperty(
        name="Scale X", description="Scale the matte horizontally around its center; values above one make the matte larger",
        default=1.0, min=0.001, soft_max=4.0, max=1000.0, precision=3, update=update_luma_matte_uv_scale_x_cb)
    _FBP_OBJECT_RNA.fbp_luma_matte_uv_scale_y = FloatProperty(
        name="Scale Y", description="Scale the matte vertically around its center; values above one make the matte larger",
        default=1.0, min=0.001, soft_max=4.0, max=1000.0, precision=3, update=update_luma_matte_uv_scale_y_cb)
    _FBP_OBJECT_RNA.fbp_luma_matte_uv_rotation = FloatProperty(
        name="Rotation", description="Rotate the matte around the center of its sampled UV space",
        default=0.0, soft_min=-3.141593, soft_max=3.141593, subtype='ANGLE', update=update_luma_matte_uv_rotation_cb)
    _FBP_OBJECT_RNA.fbp_color_mask_color = FloatVectorProperty(
        name="Target Color", description="Source color selected by Color Mask",
        subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.0, 1.0, 0.0, 1.0),
        update=update_color_mask_color_cb)
    _FBP_OBJECT_RNA.fbp_color_mask_tolerance = FloatProperty(
        name="Tolerance", description="Maximum RGB distance treated as a color match",
        default=0.12, min=0.0, max=1.732, soft_max=1.0, subtype='FACTOR',
        update=update_color_mask_tolerance_cb)
    _FBP_OBJECT_RNA.fbp_color_mask_softness = FloatProperty(
        name="Softness", description="Smooth transition outside the Color Mask tolerance",
        default=0.08, min=0.0, max=1.0, subtype='FACTOR',
        update=update_color_mask_softness_cb)
    _FBP_OBJECT_RNA.fbp_color_mask_factor = FloatProperty(
        name="Factor", description="Blend between the unmasked result and Color Mask",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR',
        update=update_color_mask_factor_cb)
    _FBP_OBJECT_RNA.fbp_color_mask_invert = BoolProperty(
        name="Invert", description="Use colors outside the selected range",
        default=False, update=update_color_mask_invert_cb)
    _FBP_OBJECT_RNA.fbp_luminance_mask_minimum = FloatProperty(
        name="Minimum", description="Lowest source luminance included by Luminance Mask. Minimum and Maximum are automatically ordered if their values cross",
        default=0.2, min=0.0, max=1.0, subtype='FACTOR',
        update=update_luminance_mask_minimum_cb)
    _FBP_OBJECT_RNA.fbp_luminance_mask_maximum = FloatProperty(
        name="Maximum", description="Highest source luminance included by Luminance Mask. Minimum and Maximum are automatically ordered if their values cross",
        default=0.8, min=0.0, max=1.0, subtype='FACTOR',
        update=update_luminance_mask_maximum_cb)
    _FBP_OBJECT_RNA.fbp_luminance_mask_softness = FloatProperty(
        name="Softness", description="Feather inward from both edges of the selected luminance interval; 0 is hard and 1 uses the widest valid transition",
        default=0.1, min=0.0, max=1.0, subtype='FACTOR',
        update=update_luminance_mask_softness_cb)
    _FBP_OBJECT_RNA.fbp_luminance_mask_factor = FloatProperty(
        name="Factor", description="Blend between the unmasked result and Luminance Mask",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR',
        update=update_luminance_mask_factor_cb)
    _FBP_OBJECT_RNA.fbp_luminance_mask_invert = BoolProperty(
        name="Invert", description="Use luminance values outside the selected interval",
        default=False, update=update_luminance_mask_invert_cb)
    _FBP_OBJECT_RNA.fbp_channel_mask_channel = EnumProperty(
        name="Channel", description="Source channel evaluated by Channel Mask",
        items=[
            ('RED', "Red", "Use the source red channel"),
            ('GREEN', "Green", "Use the source green channel"),
            ('BLUE', "Blue", "Use the source blue channel"),
            ('ALPHA', "Alpha", "Use the source alpha channel without multiplying it twice"),
            ('LUMINANCE', "Luminance", "Use perceptual source luminance"),
        ], default='LUMINANCE', update=update_channel_mask_channel_cb)
    _FBP_OBJECT_RNA.fbp_channel_mask_minimum = FloatProperty(
        name="Minimum", description="Lowest selected value in the chosen source channel; Minimum and Maximum are ordered automatically",
        default=0.2, min=0.0, max=1.0, subtype='FACTOR',
        update=update_channel_mask_minimum_cb)
    _FBP_OBJECT_RNA.fbp_channel_mask_maximum = FloatProperty(
        name="Maximum", description="Highest selected value in the chosen source channel; Minimum and Maximum are ordered automatically",
        default=0.8, min=0.0, max=1.0, subtype='FACTOR',
        update=update_channel_mask_maximum_cb)
    _FBP_OBJECT_RNA.fbp_channel_mask_softness = FloatProperty(
        name="Softness", description="Feather inward from both edges of the selected channel interval; 0 is hard and 1 uses the widest valid transition",
        default=0.1, min=0.0, max=1.0, subtype='FACTOR',
        update=update_channel_mask_softness_cb)
    _FBP_OBJECT_RNA.fbp_channel_mask_factor = FloatProperty(
        name="Factor", description="Blend between the unmasked result and Channel Mask",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR',
        update=update_channel_mask_factor_cb)
    _FBP_OBJECT_RNA.fbp_channel_mask_invert = BoolProperty(
        name="Invert", description="Use source-channel values outside the selected interval",
        default=False, update=update_channel_mask_invert_cb)
    _FBP_OBJECT_RNA.fbp_gradient_mask_type = EnumProperty(
        name="Type", description="Gradient shape used by the mask",
        items=[
            ('LINEAR', "Linear", "Directional linear gradient"),
            ('RADIAL', "Radial", "Circular gradient around the mask center"),
        ], default='LINEAR', update=update_gradient_mask_type_cb)
    _FBP_OBJECT_RNA.fbp_gradient_mask_center_x = FloatProperty(
        name="Center X", description="Horizontal center of the Gradient Mask in UV space",
        default=0.5, soft_min=-1.0, soft_max=2.0, precision=3,
        update=update_gradient_mask_center_x_cb)
    _FBP_OBJECT_RNA.fbp_gradient_mask_center_y = FloatProperty(
        name="Center Y", description="Vertical center of the Gradient Mask in UV space",
        default=0.5, soft_min=-1.0, soft_max=2.0, precision=3,
        update=update_gradient_mask_center_y_cb)
    _FBP_OBJECT_RNA.fbp_gradient_mask_scale = FloatProperty(
        name="Scale", description="Tighten or widen the Gradient Mask around its center; higher values make the transition more compact",
        default=1.0, min=0.001, soft_max=10.0, max=1000.0, precision=3,
        update=update_gradient_mask_scale_cb)
    _FBP_OBJECT_RNA.fbp_gradient_mask_angle = FloatProperty(
        name="Angle", description="Rotate a Linear Gradient Mask around its center",
        default=0.0, soft_min=-3.141593, soft_max=3.141593, subtype='ANGLE',
        update=update_gradient_mask_angle_cb)
    _FBP_OBJECT_RNA.fbp_gradient_mask_position = FloatProperty(
        name="Position", description="Position of the gradient transition",
        default=0.5, soft_min=-1.0, soft_max=2.0, precision=3,
        update=update_gradient_mask_position_cb)
    _FBP_OBJECT_RNA.fbp_gradient_mask_feather = FloatProperty(
        name="Feather", description="Width of the Gradient Mask transition",
        default=0.2, min=0.0, soft_max=1.0, max=2.0, subtype='FACTOR',
        update=update_gradient_mask_feather_cb)
    _FBP_OBJECT_RNA.fbp_gradient_mask_factor = FloatProperty(
        name="Factor", description="Blend between the unmasked result and Gradient Mask",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR',
        update=update_gradient_mask_factor_cb)
    _FBP_OBJECT_RNA.fbp_gradient_mask_invert = BoolProperty(
        name="Invert", description="Invert the Gradient Mask",
        default=False, update=update_gradient_mask_invert_cb)
    _FBP_OBJECT_RNA.fbp_noise_mask_scale = FloatProperty(
        name="Scale", description="Spatial frequency of the Noise Mask",
        default=11.34, min=0.001, soft_max=100.0, max=1000.0, precision=3,
        update=update_noise_mask_scale_cb)
    _FBP_OBJECT_RNA.fbp_noise_mask_detail = FloatProperty(
        name="Detail", description="Fractal detail of the Noise Mask",
        default=1.0, min=0.0, max=15.0, precision=2,
        update=update_noise_mask_detail_cb)
    _FBP_OBJECT_RNA.fbp_noise_mask_roughness = FloatProperty(
        name="Roughness", description="Contribution of fine Noise Mask octaves",
        default=0.5, min=0.0, max=1.0, subtype='FACTOR',
        update=update_noise_mask_roughness_cb)
    _FBP_OBJECT_RNA.fbp_noise_mask_threshold = FloatProperty(
        name="Threshold", description="Noise value used as the mask cutoff",
        default=0.5, min=0.0, max=1.0, subtype='FACTOR',
        update=update_noise_mask_threshold_cb)
    _FBP_OBJECT_RNA.fbp_noise_mask_softness = FloatProperty(
        name="Softness", description="Width of the smooth transition around the Noise Mask threshold",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR',
        update=update_noise_mask_softness_cb)
    _FBP_OBJECT_RNA.fbp_noise_mask_seed = FloatProperty(
        name="Seed", description="Fourth-dimensional coordinate used to animate the Noise Mask",
        default=0.0, soft_min=-1000.0, soft_max=1000.0, precision=3,
        update=update_noise_mask_seed_cb)
    _FBP_OBJECT_RNA.fbp_noise_mask_factor = FloatProperty(
        name="Factor", description="Blend between the unmasked result and Noise Mask",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR',
        update=update_noise_mask_factor_cb)
    _FBP_OBJECT_RNA.fbp_noise_mask_invert = BoolProperty(
        name="Invert", description="Invert the Noise Mask",
        default=False, update=update_noise_mask_invert_cb)
    _FBP_OBJECT_RNA.fbp_voronoi_mask_scale = FloatProperty(
        name="Scale", description="Spatial frequency of the Voronoi cells",
        default=5.0, min=0.001, soft_max=100.0, max=1000.0, precision=3,
        update=update_voronoi_mask_scale_cb)
    _FBP_OBJECT_RNA.fbp_voronoi_mask_angle = FloatProperty(
        name="Angle", description="Rotate the Voronoi texture in UV space",
        default=0.7853981633974483, soft_min=-3.141593, soft_max=3.141593, subtype='ANGLE',
        update=update_voronoi_mask_angle_cb)
    _FBP_OBJECT_RNA.fbp_voronoi_mask_randomness = FloatProperty(
        name="Randomness", description="Random displacement of Voronoi feature points",
        default=0.5, min=0.0, max=1.0, subtype='FACTOR',
        update=update_voronoi_mask_randomness_cb)
    _FBP_OBJECT_RNA.fbp_voronoi_mask_threshold = FloatProperty(
        name="Threshold", description="Distance cutoff used to form the cellular mask",
        default=0.5, min=0.0, max=1.0, subtype='FACTOR',
        update=update_voronoi_mask_threshold_cb)
    _FBP_OBJECT_RNA.fbp_voronoi_mask_softness = FloatProperty(
        name="Softness", description="Width of the smooth transition around the Voronoi threshold",
        default=0.5, min=0.0, max=1.0, subtype='FACTOR',
        update=update_voronoi_mask_softness_cb)
    _FBP_OBJECT_RNA.fbp_voronoi_mask_seed = FloatProperty(
        name="Seed", description="Fourth-dimensional coordinate used to vary or animate the Voronoi pattern",
        default=0.0, soft_min=-1000.0, soft_max=1000.0, precision=3,
        update=update_voronoi_mask_seed_cb)
    _FBP_OBJECT_RNA.fbp_voronoi_mask_factor = FloatProperty(
        name="Factor", description="Blend between the unmasked result and Voronoi Mask",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR',
        update=update_voronoi_mask_factor_cb)
    _FBP_OBJECT_RNA.fbp_voronoi_mask_invert = BoolProperty(
        name="Invert", description="Invert the Voronoi Mask",
        default=False, update=update_voronoi_mask_invert_cb)
    _FBP_OBJECT_RNA.fbp_wave_mask_scale = FloatProperty(
        name="Scale", description="Frequency of the Wave Mask stripes",
        default=2.0, min=0.001, soft_max=100.0, max=1000.0, precision=3,
        update=update_wave_mask_scale_cb)
    _FBP_OBJECT_RNA.fbp_wave_mask_angle = FloatProperty(
        name="Angle", description="Rotate the Wave Mask direction in UV space",
        default=0.7853981633974483, soft_min=-3.141593, soft_max=3.141593, subtype='ANGLE',
        update=update_wave_mask_angle_cb)
    _FBP_OBJECT_RNA.fbp_wave_mask_distortion = FloatProperty(
        name="Distortion", description="Warp the Wave Mask with procedural noise",
        default=10.0, min=0.0, soft_max=10.0, max=100.0, precision=3,
        update=update_wave_mask_distortion_cb)
    _FBP_OBJECT_RNA.fbp_wave_mask_detail = FloatProperty(
        name="Detail", description="Fractal detail used by Wave distortion",
        default=5.0, min=0.0, max=15.0, precision=2,
        update=update_wave_mask_detail_cb)
    _FBP_OBJECT_RNA.fbp_wave_mask_detail_scale = FloatProperty(
        name="Detail Scale", description="Scale of the distortion detail",
        default=1.75, min=0.0, soft_max=100.0, max=1000.0, precision=3,
        update=update_wave_mask_detail_scale_cb)
    _FBP_OBJECT_RNA.fbp_wave_mask_detail_roughness = FloatProperty(
        name="Detail Roughness", description="Contribution of fine distortion octaves",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR',
        update=update_wave_mask_detail_roughness_cb)
    _FBP_OBJECT_RNA.fbp_wave_mask_phase = FloatProperty(
        name="Phase", description="Translate or animate the Wave pattern",
        default=3.0, soft_min=-1000.0, soft_max=1000.0, precision=3,
        update=update_wave_mask_phase_cb)
    _FBP_OBJECT_RNA.fbp_wave_mask_threshold = FloatProperty(
        name="Threshold", description="Wave value used as the mask cutoff",
        default=0.5, min=0.0, max=1.0, subtype='FACTOR',
        update=update_wave_mask_threshold_cb)
    _FBP_OBJECT_RNA.fbp_wave_mask_softness = FloatProperty(
        name="Softness", description="Width of the smooth transition around the Wave threshold",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR',
        update=update_wave_mask_softness_cb)
    _FBP_OBJECT_RNA.fbp_wave_mask_factor = FloatProperty(
        name="Factor", description="Blend between the unmasked result and Wave Mask",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR',
        update=update_wave_mask_factor_cb)
    _FBP_OBJECT_RNA.fbp_wave_mask_invert = BoolProperty(
        name="Invert", description="Invert the Wave Mask",
        default=False, update=update_wave_mask_invert_cb)
    _FBP_OBJECT_RNA.fbp_clipping_mask_source = PointerProperty(
        name="Source Layer", description="Layer directly below this one, used automatically as the clipping alpha source",
        type=bpy.types.Object, poll=_fbp_mask_source_poll, update=update_clipping_mask_source_cb)
    _FBP_OBJECT_RNA.fbp_clipping_mask_factor = FloatProperty(
        name="Factor", description="Blend between the original layer alpha and the clipping result",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_clipping_mask_factor_cb)
    _FBP_OBJECT_RNA.fbp_clipping_mask_invert = BoolProperty(
        name="Invert", description="Invert the alpha of the layer below before clipping",
        default=False, update=update_clipping_mask_invert_cb)
    _FBP_OBJECT_RNA.fbp_clipping_mask_use_source_transform = BoolProperty(
        name="Use Source Transform",
        description="Project through the source plane so its position, rotation, scale and cropped bounds define the clipping result. Disable only for full-canvas layered imports",
        default=True, update=update_clipping_mask_use_source_transform_cb)
    _FBP_OBJECT_RNA.fbp_clipping_mask_use_camera_projection = BoolProperty(
        name="Camera Projection",
        description="Project the source alpha through the active camera so clipping remains aligned in perspective and orthographic camera views",
        default=True, update=update_clipping_mask_use_camera_projection_cb)
    _FBP_OBJECT_RNA.fbp_clipping_mask_uv_offset_x = FloatProperty(
        name="Offset X", description="Move the sampled clipping alpha horizontally in UV space",
        default=0.0, soft_min=-2.0, soft_max=2.0, precision=3, update=update_clipping_mask_uv_offset_x_cb)
    _FBP_OBJECT_RNA.fbp_clipping_mask_uv_offset_y = FloatProperty(
        name="Offset Y", description="Move the sampled clipping alpha vertically in UV space",
        default=0.0, soft_min=-2.0, soft_max=2.0, precision=3, update=update_clipping_mask_uv_offset_y_cb)
    _FBP_OBJECT_RNA.fbp_clipping_mask_uv_scale_x = FloatProperty(
        name="Scale X", description="Scale the clipping alpha horizontally around its center",
        default=1.0, min=0.001, soft_max=4.0, max=1000.0, precision=3, update=update_clipping_mask_uv_scale_x_cb)
    _FBP_OBJECT_RNA.fbp_clipping_mask_uv_scale_y = FloatProperty(
        name="Scale Y", description="Scale the clipping alpha vertically around its center",
        default=1.0, min=0.001, soft_max=4.0, max=1000.0, precision=3, update=update_clipping_mask_uv_scale_y_cb)
    _FBP_OBJECT_RNA.fbp_clipping_mask_uv_rotation = FloatProperty(
        name="Rotation", description="Rotate the clipping alpha around the center of its sampled UV space",
        default=0.0, soft_min=-3.141593, soft_max=3.141593, subtype='ANGLE', update=update_clipping_mask_uv_rotation_cb)

    _FBP_OBJECT_RNA.fbp_imported_mask_path = StringProperty(
        name="Imported Mask", description="Full-canvas raster layer mask extracted from a PSD or another layered document",
        subtype='FILE_PATH', default="", update=update_imported_mask_path_cb)
    _FBP_OBJECT_RNA.fbp_imported_mask_factor = FloatProperty(
        name="Factor", description="Blend between the original alpha and imported layer mask",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_imported_mask_factor_cb)
    _FBP_OBJECT_RNA.fbp_imported_mask_invert = BoolProperty(
        name="Invert", description="Invert the imported layer mask",
        default=False, update=update_imported_mask_invert_cb)
    _FBP_OBJECT_RNA.fbp_gp_mask_slot_2_path = StringProperty(name="Grease Pencil Mask Slot 2", description="Internal raster source for Grease Pencil mask slot 2", subtype='FILE_PATH', default="", update=update_gp_mask_slot_2_path_cb)
    _FBP_OBJECT_RNA.fbp_gp_mask_slot_2_factor = FloatProperty(name="Factor", description="Strength of Grease Pencil mask slot 2", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_gp_mask_slot_2_factor_cb)
    _FBP_OBJECT_RNA.fbp_gp_mask_slot_2_invert = BoolProperty(name="Invert", description="Invert Grease Pencil mask slot 2", default=False, update=update_gp_mask_slot_2_invert_cb)
    _FBP_OBJECT_RNA.fbp_gp_mask_slot_3_path = StringProperty(name="Grease Pencil Mask Slot 3", description="Internal raster source for Grease Pencil mask slot 3", subtype='FILE_PATH', default="", update=update_gp_mask_slot_3_path_cb)
    _FBP_OBJECT_RNA.fbp_gp_mask_slot_3_factor = FloatProperty(name="Factor", description="Strength of Grease Pencil mask slot 3", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_gp_mask_slot_3_factor_cb)
    _FBP_OBJECT_RNA.fbp_gp_mask_slot_3_invert = BoolProperty(name="Invert", description="Invert Grease Pencil mask slot 3", default=False, update=update_gp_mask_slot_3_invert_cb)
    _FBP_OBJECT_RNA.fbp_gp_mask_slot_4_path = StringProperty(name="Grease Pencil Mask Slot 4", description="Internal raster source for Grease Pencil mask slot 4", subtype='FILE_PATH', default="", update=update_gp_mask_slot_4_path_cb)
    _FBP_OBJECT_RNA.fbp_gp_mask_slot_4_factor = FloatProperty(name="Factor", description="Strength of Grease Pencil mask slot 4", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_gp_mask_slot_4_factor_cb)
    _FBP_OBJECT_RNA.fbp_gp_mask_slot_4_invert = BoolProperty(name="Invert", description="Invert Grease Pencil mask slot 4", default=False, update=update_gp_mask_slot_4_invert_cb)

    _FBP_OBJECT_RNA.fbp_layer_blend_source = PointerProperty(
        name="Layer Below", description="Image or flat Color Plane directly below this one, used automatically as the blend base",
        type=bpy.types.Object, poll=_fbp_layer_blend_source_poll, update=update_layer_blend_source_cb)
    _FBP_OBJECT_RNA.fbp_layer_blend_mode = EnumProperty(
        name="Blend Mode", description="Blend this layer against the image layer below",
        items=FBP_LAYER_BLEND_MODE_ITEMS, default='MULTIPLY', update=update_layer_blend_mode_cb)
    _FBP_OBJECT_RNA.fbp_layer_blend_factor = FloatProperty(
        name="Factor", description="Strength of the transferred layer blend mode",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_layer_blend_factor_cb)

    _FBP_OBJECT_RNA.fbp_square_mask_object = PointerProperty(
        name="Mask Shape", description="Editable Square Shape Mask helper. Select it and enter Edit Mode to change the silhouette",
        type=bpy.types.Object, update=update_square_mask_object_cb)
    _FBP_OBJECT_RNA.fbp_square_mask_external_null = PointerProperty(
        name="External Null",
        description="External Empty whose world position drives this Square Mask while preserving its layer-specific size",
        type=bpy.types.Object,
        poll=lambda self, candidate: candidate is not self and getattr(candidate, "type", "") == "EMPTY",
        update=update_square_mask_external_null_cb,
    )
    _FBP_OBJECT_RNA.fbp_square_mask_factor = FloatProperty(
        name="Factor", description="Blend between the original alpha and the Square Shape Mask result",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_square_mask_factor_cb)
    _FBP_OBJECT_RNA.fbp_square_mask_invert = BoolProperty(
        name="Invert", description="Invert the Square Shape Mask", default=False, update=update_square_mask_invert_cb)
    _FBP_OBJECT_RNA.fbp_square_mask_feather = FloatProperty(
        name="Feather", description="Dissolve the Square Shape Mask progressively inward without revealing its rectangular texture bounds",
        default=0.05, min=0.0, max=1.0, subtype='FACTOR', update=update_square_mask_feather_cb)
    _FBP_OBJECT_RNA.fbp_square_mask_follow_bounds = BoolProperty(
        name="Follow Layer Bounds", description="Preserve the helper's normalized position and size when Crop or Extend changes the layer bounds",
        default=True, update=update_square_mask_follow_bounds_cb)
    _FBP_OBJECT_RNA.fbp_square_mask_show_helper = BoolProperty(
        name="Mask Shape", description="Show the Square helper while this layer or its helper is selected",
        default=True, update=update_square_mask_runtime_cb)
    _FBP_OBJECT_RNA.fbp_square_mask_lock_to_plane = BoolProperty(
        name="Lock to Plane", description="Keep G movement on the layer plane by locking local depth and off-plane rotation",
        default=True, update=update_square_mask_runtime_cb)

    _FBP_OBJECT_RNA.fbp_circle_mask_object = PointerProperty(
        name="Mask Shape", description="Editable Circle Shape Mask helper. Select it and enter Edit Mode to change the silhouette",
        type=bpy.types.Object, update=update_circle_mask_object_cb)
    _FBP_OBJECT_RNA.fbp_circle_mask_external_null = PointerProperty(
        name="External Null",
        description="External Empty whose world position drives this Circle Mask while preserving its layer-specific size",
        type=bpy.types.Object,
        poll=lambda self, candidate: candidate is not self and getattr(candidate, "type", "") == "EMPTY",
        update=update_circle_mask_external_null_cb,
    )
    _FBP_OBJECT_RNA.fbp_circle_mask_factor = FloatProperty(
        name="Factor", description="Blend between the original alpha and the Circle Shape Mask result",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_circle_mask_factor_cb)
    _FBP_OBJECT_RNA.fbp_circle_mask_invert = BoolProperty(
        name="Invert", description="Invert the Circle Shape Mask", default=False, update=update_circle_mask_invert_cb)
    _FBP_OBJECT_RNA.fbp_circle_mask_feather = FloatProperty(
        name="Feather", description="Dissolve the Circle Shape Mask progressively inward without revealing its rectangular texture bounds",
        default=0.05, min=0.0, max=1.0, subtype='FACTOR', update=update_circle_mask_feather_cb)
    _FBP_OBJECT_RNA.fbp_circle_mask_follow_bounds = BoolProperty(
        name="Follow Layer Bounds", description="Preserve the helper's normalized position and size when Crop or Extend changes the layer bounds",
        default=True, update=update_circle_mask_follow_bounds_cb)
    _FBP_OBJECT_RNA.fbp_circle_mask_show_helper = BoolProperty(
        name="Mask Shape", description="Show the Circle helper while this layer or its helper is selected",
        default=True, update=update_circle_mask_runtime_cb)
    _FBP_OBJECT_RNA.fbp_circle_mask_lock_to_plane = BoolProperty(
        name="Lock to Plane", description="Keep G movement on the layer plane by locking local depth and off-plane rotation",
        default=True, update=update_circle_mask_runtime_cb)

    _FBP_OBJECT_RNA.fbp_triangle_mask_object = PointerProperty(
        name="Mask Shape", description="Editable Triangle Shape Mask helper. Select it and enter Edit Mode to change the silhouette",
        type=bpy.types.Object, update=update_triangle_mask_object_cb)
    _FBP_OBJECT_RNA.fbp_triangle_mask_external_null = PointerProperty(
        name="External Null",
        description="External Empty whose world position drives this Triangle Mask while preserving its layer-specific size",
        type=bpy.types.Object,
        poll=lambda self, candidate: candidate is not self and getattr(candidate, "type", "") == "EMPTY",
        update=update_triangle_mask_external_null_cb,
    )
    _FBP_OBJECT_RNA.fbp_triangle_mask_factor = FloatProperty(
        name="Factor", description="Blend between the original alpha and the Triangle Shape Mask result",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_triangle_mask_factor_cb)
    _FBP_OBJECT_RNA.fbp_triangle_mask_invert = BoolProperty(
        name="Invert", description="Invert the Triangle Shape Mask", default=False, update=update_triangle_mask_invert_cb)
    _FBP_OBJECT_RNA.fbp_triangle_mask_feather = FloatProperty(
        name="Feather", description="Dissolve the Triangle Shape Mask progressively inward without revealing its rectangular texture bounds",
        default=0.05, min=0.0, max=1.0, subtype='FACTOR', update=update_triangle_mask_feather_cb)
    _FBP_OBJECT_RNA.fbp_triangle_mask_follow_bounds = BoolProperty(
        name="Follow Layer Bounds", description="Preserve the helper's normalized position and size when Crop or Extend changes the layer bounds",
        default=True, update=update_triangle_mask_follow_bounds_cb)
    _FBP_OBJECT_RNA.fbp_triangle_mask_show_helper = BoolProperty(
        name="Mask Shape", description="Show the Triangle helper while this layer or its helper is selected",
        default=True, update=update_triangle_mask_runtime_cb)
    _FBP_OBJECT_RNA.fbp_triangle_mask_lock_to_plane = BoolProperty(
        name="Lock to Plane", description="Keep G movement on the layer plane by locking local depth and off-plane rotation",
        default=True, update=update_triangle_mask_runtime_cb)
    _FBP_OBJECT_RNA.fbp_grain_strength = FloatProperty(description="Opacity and intensity of Film Grain layered over the source image.",
        name="Intensity", default=0.2, min=0.0, max=1.0, subtype='FACTOR', update=update_grain_strength_cb)
    _FBP_OBJECT_RNA.fbp_grain_scale = FloatProperty(description="Spatial size of Film Grain. Higher values create finer grain; lower values create larger visible noise clusters.",
        name="Grain Scale", default=180.0, min=0.01, soft_max=2000.0, precision=2, update=update_grain_scale_cb)
    _FBP_OBJECT_RNA.fbp_grain_seed = FloatProperty(description="Deterministic phase or seed controlling the Film Grain pattern. Animate it to make the grain evolve over time.",
        name="Animate (W)", default=0.0, soft_min=-100.0, soft_max=100.0, precision=3, update=update_grain_seed_cb)
    _FBP_OBJECT_RNA.fbp_digital_noise_luma = FloatProperty(
        name="Luminance Noise", description="Strength of luminance-only digital sensor noise added to the image. This simulates monochromatic high-ISO grain without color speckles.",
        default=0.12, min=0.0, max=1.0, subtype='FACTOR', update=update_digital_noise_luma_cb)
    _FBP_OBJECT_RNA.fbp_digital_noise_chroma = FloatProperty(
        name="Chroma Noise", description="Strength of independent RGB sensor noise. Higher values create colored speckles and can be more visually aggressive than monochromatic noise.",
        default=0.08, min=0.0, max=1.0, subtype='FACTOR', update=update_digital_noise_chroma_cb)
    _FBP_OBJECT_RNA.fbp_digital_noise_scale = FloatProperty(
        name="Noise Scale", description="Spatial scale of the digital noise pattern. Lower values produce larger blotches; higher values produce finer sensor-like grain.",
        default=500.0, min=1.0, soft_max=3000.0, max=10000.0, precision=1, update=update_digital_noise_scale_cb)
    _FBP_OBJECT_RNA.fbp_digital_noise_shadow_bias = FloatProperty(
        name="Shadow Bias", description="Bias that increases digital noise in shadows relative to highlights, approximating reduced signal quality in underexposed areas.",
        default=0.65, min=0.0, max=2.0, update=update_digital_noise_shadow_bias_cb)
    _FBP_OBJECT_RNA.fbp_digital_noise_seed = FloatProperty(
        name="Animate (W)", description="Temporal noise phase; animate or enable Evolve for moving sensor noise",
        default=0.0, soft_min=-100.0, soft_max=100.0, precision=3, update=update_digital_noise_seed_cb)
    _FBP_OBJECT_RNA.fbp_chroma_key_color = FloatVectorProperty(
        name="Key Color", description="Target RGBA key color removed by Chroma Key. Choose the screen color as closely as possible before adjusting tolerance and despill.",
        subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.0, 1.0, 0.0, 1.0), update=update_chroma_key_color_cb)
    _FBP_OBJECT_RNA.fbp_chroma_key_tolerance = FloatProperty(
        name="Tolerance", description="Distance from the key color that becomes transparent",
        default=0.20, min=0.0, soft_max=1.0, max=1.732, update=update_chroma_key_tolerance_cb)
    _FBP_OBJECT_RNA.fbp_chroma_key_softness = FloatProperty(
        name="Softness", description="Soft transition width around the keyed color boundary. Increase it to reduce hard edges, but excessive values can erode the subject.",
        default=0.08, min=0.0, max=1.0, subtype='FACTOR', update=update_chroma_key_softness_cb)
    _FBP_OBJECT_RNA.fbp_chroma_key_despill = FloatProperty(
        name="Despill", description="Desaturate key-color contamination near transparent edges",
        default=0.5, min=0.0, max=1.0, subtype='FACTOR', update=update_chroma_key_despill_cb)
    _FBP_OBJECT_RNA.fbp_chroma_key_invert = BoolProperty(
        name="Invert", description="Keep the selected key color and remove the rest",
        default=False, update=update_chroma_key_invert_cb)
    _FBP_OBJECT_RNA.fbp_halftone_pattern = EnumProperty(
        name="Pattern", description="Halftone dot response. Dot keeps crisper newspaper cells, while Blended lets dots feather and merge more softly.",
        items=(("DOT", "Dot", "Crisp circular print dots"), ("BLENDED", "Blended", "Softer dots that blend into the print pattern")),
        default="BLENDED", update=update_halftone_pattern_cb)
    _FBP_OBJECT_RNA.fbp_halftone_color_mode = EnumProperty(
        name="Color Mode", description="Color separation style used by the Halftone pass.",
        items=(("CMYK", "CMYK", "Source-color print look for offset-style artwork"),
               ("RGB", "RGB", "Source-color digital screen look"),
               ("BW_LIGHT", "BW Light", "Black dots on light paper"),
               ("BW_DARK", "BW Dark", "Light dots on dark paper")),
        default="CMYK", update=update_halftone_color_mode_cb)
    _FBP_OBJECT_RNA.fbp_halftone_scale = FloatProperty(
        name="Cell Scale", description="Number of Halftone cells across the plane width. Higher values create finer print dots.",
        default=80.0, min=1.0, soft_max=500.0, max=2000.0, update=update_halftone_scale_cb)
    _FBP_OBJECT_RNA.fbp_halftone_dot_size = FloatProperty(description="Base size of Halftone dots inside each sampling cell.",
        name="Dot Size", default=0.9, min=0.0, soft_max=1.2, max=1.5, update=update_halftone_dot_size_cb)
    _FBP_OBJECT_RNA.fbp_halftone_dot_scale = FloatProperty(description="How much each dot can grow in darker regions. Lower values keep more white paper visible; higher values make dots merge sooner.",
        name="Dot Scale", default=0.82, min=0.0, soft_max=1.5, max=3.0, update=update_halftone_dot_scale_cb)
    _FBP_OBJECT_RNA.fbp_halftone_blend = FloatProperty(description="Controls how much Blended Halftone dots melt into each other. 0 keeps crisp dot edges; 1 gives the soft Figma-style blended screen.",
        name="Blend", default=0.65, min=0.0, max=1.0, subtype='FACTOR', update=update_halftone_blend_cb)
    _FBP_OBJECT_RNA.fbp_halftone_softness = FloatProperty(description="Feathering around dot edges. Use low values for crisp print dots and higher values for Figma-style blended halftone.",
        name="Softness", default=0.44, min=0.0, max=1.0, subtype='FACTOR', update=update_halftone_softness_cb)
    _FBP_OBJECT_RNA.fbp_halftone_rotation = FloatProperty(description="Rotate the Halftone sampling grid to change the screen angle and moir\u00e9 direction.",
        name="Rotation", subtype='ANGLE', default=0.0, soft_min=-3.141593, soft_max=3.141593, update=update_halftone_rotation_cb)
    _FBP_OBJECT_RNA.fbp_halftone_contrast = FloatProperty(description="Contrast applied before Halftone dot generation. Higher values produce harder separation between large and small dots.",
        name="Contrast", default=1.4, min=0.0, soft_max=4.0, max=8.0, update=update_halftone_contrast_cb)
    _FBP_OBJECT_RNA.fbp_halftone_invert = BoolProperty(description="Invert luminance before generating Halftone dots, swapping dense dark regions with dense bright regions.",
        name="Invert", default=False, update=update_halftone_invert_cb)
    _FBP_OBJECT_RNA.fbp_halftone_shape = EnumProperty(
        name="Shape", description="Geometric shape used for Halftone cells. Shape changes the printed texture while luminance still controls cell coverage.",
        items=(("CIRCLE", "Circle", "Circular dots"), ("SQUARE", "Square", "Square cells"),
               ("DIAMOND", "Diamond", "Diamond-shaped cells"), ("LINE", "Line", "Parallel print lines")),
        default="CIRCLE", update=update_halftone_shape_cb)
    _FBP_OBJECT_RNA.fbp_halftone_use_source_color = BoolProperty(
        name="Use Source Color", description="Color Halftone cells from the source image. Disable it to use the custom foreground ink color instead.",
        default=True, update=update_halftone_use_source_color_cb)
    _FBP_OBJECT_RNA.fbp_halftone_foreground = FloatVectorProperty(description="RGBA ink color used for Halftone dots when source-color mode is disabled.",
        name="Ink Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.0, 0.0, 0.0, 1.0), update=update_halftone_foreground_cb)
    _FBP_OBJECT_RNA.fbp_halftone_background = FloatVectorProperty(description="RGBA paper color shown between Halftone dots when the background is not transparent.",
        name="Paper Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0, 1.0), update=update_halftone_background_cb)
    _FBP_OBJECT_RNA.fbp_halftone_transparent_background = BoolProperty(
        name="Transparent Background", description="Make the spaces between Halftone cells transparent instead of filling them with the configured background color.",
        default=False, update=update_halftone_transparent_background_cb)
    _FBP_OBJECT_RNA.fbp_halftone_center_x = FloatProperty(
        name="X", description="Horizontal Halftone origin, matching the on-canvas center control used by design tools.",
        default=0.5, min=-10.0, max=10.0, subtype='FACTOR', update=update_halftone_center_x_cb)
    _FBP_OBJECT_RNA.fbp_halftone_center_y = FloatProperty(
        name="Y", description="Vertical Halftone origin, matching the on-canvas center control used by design tools.",
        default=0.5, min=-10.0, max=10.0, subtype='FACTOR', update=update_halftone_center_y_cb)
    _FBP_OBJECT_RNA.fbp_halftone_clip_alpha = BoolProperty(
        name="Clip to Alpha", description="Keep the Halftone result clipped to the source alpha instead of filling the whole plane bounds.",
        default=True, update=update_halftone_clip_alpha_cb)
    _FBP_OBJECT_RNA.fbp_dot_matrix_scale = FloatProperty(
        name="Cell Scale", description="Approximate number of Dot Matrix cells across the local plane width. Higher values increase detail and shader sampling frequency.",
        default=64.0, min=1.0, soft_max=500.0, max=2000.0, update=update_dot_matrix_scale_cb)
    _FBP_OBJECT_RNA.fbp_dot_matrix_dot_size = FloatProperty(description="Base diameter of Dot Matrix cells before luminance response and random size variation are applied.",
        name="Dot Size", default=0.85, min=0.0, soft_max=1.2, max=1.5, update=update_dot_matrix_dot_size_cb)
    _FBP_OBJECT_RNA.fbp_dot_matrix_spacing = FloatProperty(
        name="Spacing", description="Fraction of each Dot Matrix cell reserved as empty spacing. Higher values separate elements and make the pattern less dense.",
        default=0.10, min=0.0, max=0.95, subtype='FACTOR', update=update_dot_matrix_spacing_cb)
    _FBP_OBJECT_RNA.fbp_dot_matrix_contrast = FloatProperty(
        name="Contrast", description="Contrast used to derive dot radius and brightness from the source image",
        default=1.0, min=0.0, soft_max=4.0, max=8.0, update=update_dot_matrix_contrast_cb)
    _FBP_OBJECT_RNA.fbp_dot_matrix_response = FloatProperty(
        name="Brightness Response",
        description="Shape the luminance-to-size response: below 1 lifts dark regions, above 1 concentrates dots in highlights",
        default=1.0, min=0.1, soft_max=4.0, max=8.0, update=update_dot_matrix_response_cb)
    _FBP_OBJECT_RNA.fbp_dot_matrix_invert = BoolProperty(
        name="Invert", description="Invert source luminance before generating dot size and brightness",
        default=False, update=update_dot_matrix_invert_cb)
    _FBP_OBJECT_RNA.fbp_dot_matrix_random_size = FloatProperty(
        name="Random Size", description="Amount of deterministic per-cell size variation applied to Dot Matrix elements. Zero keeps every cell uniform.",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=update_dot_matrix_random_size_cb)
    _FBP_OBJECT_RNA.fbp_dot_matrix_random_brightness = FloatProperty(
        name="Random Brightness", description="Amount of deterministic per-cell brightness variation applied to Dot Matrix elements without changing their source positions.",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=update_dot_matrix_random_brightness_cb)
    _FBP_OBJECT_RNA.fbp_dot_matrix_seed = FloatProperty(
        name="Pattern Seed", description="Deterministic dot variation; animate or enable Evolve",
        default=0.0, soft_min=-100000.0, soft_max=100000.0, precision=0, update=update_dot_matrix_seed_cb)
    _FBP_OBJECT_RNA.fbp_dot_matrix_glow = FloatProperty(
        name="Glow", description="Soft anti-aliased edge around each dot; set to zero for a hard edge",
        default=0.04, min=0.0, soft_max=0.2, max=0.5, update=update_dot_matrix_glow_cb)
    _FBP_OBJECT_RNA.fbp_dot_matrix_use_source_color = BoolProperty(
        name="Use Source Color", description="Sample the source image color for each Dot Matrix element. Disable it to use the custom foreground light color.",
        default=True, update=update_dot_matrix_use_source_color_cb)
    _FBP_OBJECT_RNA.fbp_dot_matrix_foreground = FloatVectorProperty(description="RGBA color used for Dot Matrix lights when source-color mode is disabled.",
        name="Dot Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(1.0, 0.65, 0.15, 1.0), update=update_dot_matrix_foreground_cb)
    _FBP_OBJECT_RNA.fbp_dot_matrix_background = FloatVectorProperty(description="RGBA background color shown behind Dot Matrix lights when transparency is disabled.",
        name="Background Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.0, 0.0, 0.0, 1.0), update=update_dot_matrix_background_cb)
    _FBP_OBJECT_RNA.fbp_dot_matrix_transparent_background = BoolProperty(
        name="Transparent Background", description="Show only the dots and preserve transparent gaps",
        default=True, update=update_dot_matrix_transparent_background_cb)
    _FBP_OBJECT_RNA.fbp_dot_matrix_shape = EnumProperty(
        name="Shape", description="Geometry used for each Dot Matrix element: circle, square, diamond or horizontal bar. Luminance continues to control visible size.",
        items=(("CIRCLE", "Circle", "Circular lights"), ("SQUARE", "Square", "Square lights"),
               ("DIAMOND", "Diamond", "Diamond lights"), ("LINE", "Line", "Horizontal light bars")),
        default="CIRCLE", update=update_dot_matrix_shape_cb)
    _FBP_OBJECT_RNA.fbp_dot_matrix_min_size = FloatProperty(
        name="Minimum Size", description="Smallest Dot Matrix element size allowed after luminance mapping. Raise it to keep faint elements visible in dark areas.",
        default=0.0, min=0.0, max=1.5, update=update_dot_matrix_min_size_cb)
    _FBP_OBJECT_RNA.fbp_dot_matrix_max_size = FloatProperty(
        name="Maximum Size", description="Maximum visible element size in bright regions",
        default=1.0, min=0.0, max=1.5, update=update_dot_matrix_max_size_cb)
    _FBP_OBJECT_RNA.fbp_dot_matrix_dead_pixels = FloatProperty(
        name="Dead Pixels", description="Random fraction of permanently disabled elements",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=update_dot_matrix_dead_pixels_cb)
    _FBP_OBJECT_RNA.fbp_dot_matrix_flicker = FloatProperty(
        name="Flicker", description="Random brightness variation driven by Seed and Evolve",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=update_dot_matrix_flicker_cb)

    _FBP_OBJECT_RNA.fbp_ascii_scale = FloatProperty(
        name="Cell Scale", description="Number of character cells across the plane width",
        default=48.0, min=1.0, soft_max=300.0, max=1000.0, update=update_ascii_scale_cb)
    _FBP_OBJECT_RNA.fbp_ascii_contrast = FloatProperty(description="Contrast used to map source luminance to Textellation glyph density. Higher values use the lightest and densest characters more aggressively.",
        name="Contrast", default=1.3, min=0.0, soft_max=4.0, max=8.0, update=update_ascii_contrast_cb)
    _FBP_OBJECT_RNA.fbp_ascii_gamma = FloatProperty(
        name="Gamma", description="Bias midtones before Textellation chooses a glyph; values above one favor denser characters",
        default=1.0, min=0.05, soft_max=3.0, max=5.0, update=update_ascii_gamma_cb)
    _FBP_OBJECT_RNA.fbp_ascii_glyph_scale = FloatProperty(
        name="Glyph Scale", description="Scale characters inside each Textellation cell without changing grid resolution",
        default=1.0, min=0.25, soft_max=1.5, max=2.5, update=update_ascii_glyph_scale_cb)
    _FBP_OBJECT_RNA.fbp_ascii_glyph_width = FloatProperty(
        name="Glyph Width", description="Compress or widen Textellation characters inside each cell",
        default=1.0, min=0.25, soft_max=1.5, max=2.5, update=update_ascii_glyph_width_cb)
    _FBP_OBJECT_RNA.fbp_ascii_invert = BoolProperty(description="Reverse the Textellation luminance mapping so bright areas use dense glyphs and dark areas use light glyphs.", name="Invert", default=False, update=update_ascii_invert_cb)
    _FBP_OBJECT_RNA.fbp_ascii_colorize = BoolProperty(
        name="Use Source Color", description="Color each glyph with the source image instead of Text Color",
        default=True, update=update_ascii_colorize_cb)
    _FBP_OBJECT_RNA.fbp_ascii_foreground = FloatVectorProperty(description="RGBA glyph color used by Textellation when source-color mode is disabled.",
        name="Text Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.1, 1.0, 0.2, 1.0), update=update_ascii_foreground_cb)
    _FBP_OBJECT_RNA.fbp_ascii_background = FloatVectorProperty(description="RGBA background color used by Textellation when transparent background is disabled.",
        name="Background Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.0, 0.0, 0.0, 1.0), update=update_ascii_background_cb)
    _FBP_OBJECT_RNA.fbp_ascii_transparent_background = BoolProperty(
        name="Transparent Background", description="Replace the source image with glyphs on transparent gaps",
        default=True, update=update_ascii_transparent_background_cb)
    _FBP_OBJECT_RNA.fbp_ascii_variation = FloatProperty(
        name="Character Variation", description="Vary neighboring glyph choices while preserving luminance",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=update_ascii_variation_cb)
    _FBP_OBJECT_RNA.fbp_ascii_random_seed = FloatProperty(
        name="Character Seed", description="Deterministic glyph variation; animate or enable Evolve",
        default=0.0, soft_min=-100000.0, soft_max=100000.0, precision=0, update=update_ascii_random_seed_cb)
    _FBP_OBJECT_RNA.fbp_ascii_charset = EnumProperty(
        name="Character Set", description="Character gradient used to map image luminance",
        items=ascii_enum_items(), default='CLASSIC', update=update_ascii_charset_cb)
    _FBP_OBJECT_RNA.fbp_ascii_character_count = IntProperty(
        name="Character Count", description="Number of luminance levels used from the selected character set",
        default=16, min=2, max=ASCII_ATLAS_COLUMNS, update=update_ascii_character_count_cb)
    _FBP_OBJECT_RNA.fbp_ascii_edge_boost = FloatProperty(
        name="Edge Boost", description="Emphasize image edges before choosing glyph density",
        default=0.0, min=0.0, max=2.0, update=update_ascii_edge_boost_cb)
    _FBP_OBJECT_RNA.fbp_ascii_dither = FloatProperty(
        name="Dither", description="Add ordered cell variation to preserve gradients",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=update_ascii_dither_cb)

    _FBP_OBJECT_RNA.fbp_text_matrix_quality = EnumProperty(
        name="Quality", description="Quick viewport/render column presets; rows return to Auto",
        items=(("DRAFT", "Draft", "24 viewport / 48 render columns"),
               ("PREVIEW", "Preview", "48 viewport / 96 render columns"),
               ("FINAL", "Final", "72 viewport / 160 render columns"),
               ("CUSTOM", "Custom", "Use the manual column values")),
        default="PREVIEW", update=update_text_matrix_quality_cb)
    _FBP_OBJECT_RNA.fbp_text_matrix_viewport_columns = IntProperty(
        name="Viewport Columns", description="Number of real Text Matrix columns generated at viewport quality. Lower values improve interaction speed and do not change render-quality columns.",
        default=48, min=2, soft_max=96, max=256, update=update_text_matrix_viewport_columns_cb)
    _FBP_OBJECT_RNA.fbp_text_matrix_viewport_rows = IntProperty(
        name="Viewport Rows",
        description="Text rows used in the viewport; 0 derives rows automatically from plane and font aspect",
        default=0, min=0, soft_max=128, max=512, update=update_text_matrix_viewport_rows_cb)
    _FBP_OBJECT_RNA.fbp_text_matrix_render_columns = IntProperty(
        name="Render Columns", description="Text columns temporarily used for final rendering",
        default=96, min=2, soft_max=192, max=512, update=update_text_matrix_render_columns_cb)
    _FBP_OBJECT_RNA.fbp_text_matrix_render_rows = IntProperty(
        name="Render Rows",
        description="Text rows used for final rendering; 0 derives rows automatically from plane and font aspect",
        default=0, min=0, soft_max=256, max=512, update=update_text_matrix_render_rows_cb)
    _FBP_OBJECT_RNA.fbp_text_matrix_auto_playback_limit = BoolProperty(
        name="Limit During Playback",
        description="Temporarily lower Text Matrix grid density while timeline playback is running",
        default=True, update=update_text_matrix_auto_playback_limit_cb)
    _FBP_OBJECT_RNA.fbp_text_matrix_playback_columns = IntProperty(
        name="Playback Columns",
        description="Maximum Text Matrix columns used during timeline playback",
        default=24, min=2, soft_max=64, max=128, update=update_text_matrix_playback_columns_cb)
    _FBP_OBJECT_RNA.fbp_text_matrix_playback_rows = IntProperty(
        name="Playback Rows",
        description="Maximum explicit Text Matrix rows during playback; 0 keeps automatic rows",
        default=0, min=0, soft_max=64, max=128, update=update_text_matrix_playback_rows_cb)

    # Terminal-style Ascii effect based on Blender-Image-To-ASCII assets.
    _FBP_OBJECT_RNA.fbp_terminal_ascii_scale = FloatProperty(
        name="Cell Scale", description="Approximate number of terminal character cells placed across the local plane width. Higher values preserve more image detail but increase texture sampling frequency.",
        default=64.0, min=1.0, soft_max=300.0, max=1000.0, update=update_terminal_ascii_scale_cb)
    _FBP_OBJECT_RNA.fbp_terminal_ascii_contrast = FloatProperty(
        name="Contrast", description="Contrast applied before Terminal Ascii maps source luminance to fill glyph density. Higher values separate dark and bright character choices more strongly.",
        default=1.25, min=0.0, soft_max=4.0, max=8.0, update=update_terminal_ascii_contrast_cb)
    _FBP_OBJECT_RNA.fbp_terminal_ascii_invert = BoolProperty(
        name="Invert", description="Reverse Terminal Ascii density mapping so bright regions use dense glyphs and dark regions use sparse glyphs.",
        default=False, update=update_terminal_ascii_invert_cb)
    _FBP_OBJECT_RNA.fbp_terminal_ascii_fill_strength = FloatProperty(
        name="Fill Strength", description="Multiply the source-luminance contribution used to choose fill glyphs. Higher values favor denser terminal characters before thresholding.",
        default=1.0, min=0.0, soft_max=2.0, max=4.0, update=update_terminal_ascii_fill_strength_cb)
    _FBP_OBJECT_RNA.fbp_terminal_ascii_fill_threshold = FloatProperty(
        name="Fill Threshold", description="Threshold below which Terminal Ascii fill glyphs are suppressed, leaving more background or edge characters visible.",
        default=0.0, min=0.0, max=0.95, subtype='FACTOR', update=update_terminal_ascii_fill_threshold_cb)
    _FBP_OBJECT_RNA.fbp_terminal_ascii_use_edges = BoolProperty(
        name="Use Edges", description="Enable directional slash, dash and bar glyphs where local luminance gradients detect an edge. Disable it to render only tonal fill characters.",
        default=True, update=update_terminal_ascii_use_edges_cb)
    _FBP_OBJECT_RNA.fbp_terminal_ascii_edge_strength = FloatProperty(
        name="Edge Strength", description="Multiply local luminance gradients before edge thresholding. Higher values reveal weaker contours but can introduce noisy edge glyphs.",
        default=4.0, min=0.0, soft_max=12.0, max=32.0, update=update_terminal_ascii_edge_strength_cb)
    _FBP_OBJECT_RNA.fbp_terminal_ascii_edge_threshold = FloatProperty(
        name="Edge Threshold", description="Minimum amplified local luminance difference required to replace a fill glyph with a directional edge glyph. Raise it to keep only strong contours.",
        default=0.08, min=0.0, max=1.0, subtype='FACTOR', update=update_terminal_ascii_edge_threshold_cb)
    _FBP_OBJECT_RNA.fbp_terminal_ascii_edge_mix = FloatProperty(
        name="Edge Mix", description="Blend directional edge glyphs over the tonal fill result. Zero keeps only fill characters; one gives detected edges full priority.",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_terminal_ascii_edge_mix_cb)
    _FBP_OBJECT_RNA.fbp_terminal_ascii_use_source_color = BoolProperty(
        name="Use Source Color", description="Sample the source image color for every generated fill and edge glyph. Disable it to use the uniform terminal Text Color.",
        default=False, update=update_terminal_ascii_use_source_color_cb)
    _FBP_OBJECT_RNA.fbp_terminal_ascii_foreground = FloatVectorProperty(description="RGBA terminal-glyph color used by the Ascii effect when source-color mode is disabled.",
        name="Text Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.42, 1.0, 0.42, 1.0), update=update_terminal_ascii_foreground_cb)
    _FBP_OBJECT_RNA.fbp_terminal_ascii_background = FloatVectorProperty(description="RGBA color placed behind Ascii fill and edge glyphs when transparent background is disabled.",
        name="Background Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.0, 0.0, 0.0, 1.0), update=update_terminal_ascii_background_cb)
    _FBP_OBJECT_RNA.fbp_terminal_ascii_transparent_background = BoolProperty(
        name="Transparent Background", description="Keep only generated terminal glyphs and preserve transparent gaps between them. Disable it to fill those gaps with Background Color.",
        default=True, update=update_terminal_ascii_transparent_background_cb)
    _FBP_OBJECT_RNA.fbp_terminal_ascii_seed = FloatProperty(
        name="Evolution Seed",
        description="Deterministic terminal-glyph variation. Animate it directly or enable Evolution for stepped non-repeating changes",
        default=0.0, soft_min=-100000.0, soft_max=100000.0, precision=0,
        update=update_terminal_ascii_seed_cb)

    _FBP_OBJECT_RNA.fbp_text_matrix_character_count = IntProperty(
        name="Character Levels", description="Number of distinct glyph-density steps used by Text Matrix. More levels improve tonal detail but increase generated text complexity.",
        default=16, min=2, max=ASCII_TEXT_GLYPH_LIMIT, update=update_text_matrix_character_count_cb)
    _FBP_OBJECT_RNA.fbp_text_matrix_character_aspect = FloatProperty(
        name="Character Aspect", description="Width-to-height compensation applied to each Text Matrix cell for the selected vector font. Adjust it when glyphs appear stretched or compressed.",
        default=0.60, min=0.1, max=2.0, update=update_text_matrix_character_aspect_cb)
    _FBP_OBJECT_RNA.fbp_text_matrix_glyph_scale = FloatProperty(
        name="Glyph Scale", description="Scale each generated Text Matrix glyph inside its cell. Values below one increase spacing; values above one can overlap neighboring cells.",
        default=0.88, min=0.05, max=2.0, update=update_text_matrix_glyph_scale_cb)
    _FBP_OBJECT_RNA.fbp_text_matrix_contrast = FloatProperty(description="Contrast used to map source luminance to real Text Matrix glyph density. Higher values emphasize the lightest and densest characters.",
        name="Contrast", default=1.3, min=0.0, soft_max=4.0, max=8.0, update=update_text_matrix_contrast_cb)
    _FBP_OBJECT_RNA.fbp_text_matrix_invert = BoolProperty(description="Reverse Text Matrix luminance mapping so bright areas receive dense glyphs and dark areas receive light glyphs.",
        name="Invert", default=False, update=update_text_matrix_invert_cb)
    _FBP_OBJECT_RNA.fbp_text_matrix_variation = FloatProperty(
        name="Character Variation", description="Randomly choose nearby glyphs while preserving luminance",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=update_text_matrix_variation_cb)
    _FBP_OBJECT_RNA.fbp_text_matrix_seed = FloatProperty(
        name="Character Seed", description="Deterministic glyph variation; animate or enable Evolve",
        default=0.0, soft_min=-100000.0, soft_max=100000.0, precision=0, update=update_text_matrix_seed_cb)
    _FBP_OBJECT_RNA.fbp_text_matrix_alpha_threshold = FloatProperty(
        name="Alpha Threshold", description="Discard cells at or below this alpha value; zero keeps every non-transparent cell and reads partial alpha as lighter luminance",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=update_text_matrix_alpha_threshold_cb)
    _FBP_OBJECT_RNA.fbp_text_matrix_transparent_background = BoolProperty(
        name="Transparent Background", description="Generate only text geometry without a background plane",
        default=True, update=update_text_matrix_transparent_background_cb)
    _FBP_OBJECT_RNA.fbp_text_matrix_realize = BoolProperty(
        name="Realize Text Geometry", description="Convert glyph instances to mesh only when a later modifier needs real geometry",
        default=False, update=update_text_matrix_realize_cb)
    _FBP_OBJECT_RNA.fbp_text_matrix_charset = EnumProperty(
        name="Character Set", description="Character gradient used to generate real text geometry",
        items=ascii_enum_items(include_custom=True), default='CLASSIC', update=update_text_matrix_charset_cb)
    _FBP_OBJECT_RNA.fbp_text_matrix_custom_charset = StringProperty(
        name="Characters", description="Custom glyphs ordered from lightest to darkest",
        default=" .:-=+*#%@", maxlen=256, update=update_text_matrix_custom_charset_cb)
    _FBP_OBJECT_RNA.fbp_text_matrix_font = PointerProperty(
        name="Font", description="Optional Blender Vector Font used to generate real Text Matrix geometry. Leave empty to use Blender's built-in font; changing it rebuilds glyph geometry.",
        type=bpy.types.VectorFont, update=update_text_matrix_font_cb)
    _FBP_OBJECT_RNA.fbp_text_matrix_use_source_color = BoolProperty(
        name="Use Source Color",
        description="Color each vector glyph with the sampled source pixel instead of Text Color",
        default=True, update=update_text_matrix_use_source_color_cb)
    _FBP_OBJECT_RNA.fbp_text_matrix_text_color = FloatVectorProperty(description="RGBA color assigned to generated Text Matrix glyph geometry when source-color sampling is disabled.",
        name="Text Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.1, 1.0, 0.2, 1.0), update=update_text_matrix_text_color_cb)
    _FBP_OBJECT_RNA.fbp_text_matrix_background_color = FloatVectorProperty(description="RGBA background color generated behind Text Matrix glyphs when transparent background is disabled.",
        name="Background Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.0, 0.0, 0.0, 1.0), update=update_text_matrix_background_color_cb)
    _FBP_OBJECT_RNA.fbp_hue_saturation_hue = FloatProperty(description="Hue rotation centered at the neutral value 0.5. Move below or above 0.5 to rotate colors in opposite directions.", name="Hue", default=0.5, min=0.0, max=1.0, subtype='FACTOR', update=update_hue_saturation_hue_cb)
    _FBP_OBJECT_RNA.fbp_hue_saturation_saturation = FloatProperty(description="Multiply source saturation. Zero produces grayscale, one preserves the source, and values above one intensify color.", name="Saturation", default=1.0, min=0.0, soft_max=2.0, update=update_hue_saturation_saturation_cb)
    _FBP_OBJECT_RNA.fbp_hue_saturation_value = FloatProperty(description="Multiply source brightness/value. One preserves the source; lower values darken and higher values brighten.", name="Value", default=1.0, min=0.0, soft_max=2.0, update=update_hue_saturation_value_cb)
    _FBP_OBJECT_RNA.fbp_brightness_contrast_brightness = FloatProperty(description="Add or subtract brightness before the effect output. Zero leaves source brightness unchanged.", name="Brightness", default=0.0, soft_min=-1.0, soft_max=1.0, update=update_brightness_contrast_brightness_cb)
    _FBP_OBJECT_RNA.fbp_brightness_contrast_contrast = FloatProperty(description="Increase or decrease separation around middle gray. Zero leaves source contrast unchanged.", name="Contrast", default=0.0, soft_min=-1.0, soft_max=1.0, update=update_brightness_contrast_contrast_cb)
    _FBP_OBJECT_RNA.fbp_invert_factor = FloatProperty(description="Blend between the original image and its inverted colors. Zero is unchanged; one is fully inverted.", name="Factor", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_invert_factor_cb)
    _FBP_OBJECT_RNA.fbp_threshold_value = FloatProperty(description="Luminance cutoff used to separate pixels into black and white regions. Values below the threshold become dark.", name="Threshold", default=0.5, min=0.0, max=1.0, subtype='FACTOR', update=update_threshold_value_cb)
    _FBP_OBJECT_RNA.fbp_posterize_steps = FloatProperty(description="Number of discrete color levels retained per channel by Posterize. Lower values create stronger graphic banding.",
        name="Color Steps", default=4.0, min=2.0, soft_max=64.0, precision=0, update=update_posterize_steps_cb)
    _FBP_OBJECT_RNA.fbp_solarize_threshold = FloatProperty(
        description="Luminance level above which Solarize begins to invert the image.",
        name="Threshold", default=0.5, min=0.0, max=1.0, subtype='FACTOR', update=update_solarize_threshold_cb)
    _FBP_OBJECT_RNA.fbp_solarize_softness = FloatProperty(
        description="Width of the transition around the Solarize threshold. Zero produces a sharp photographic solarization boundary.",
        name="Softness", default=0.08, min=0.0, max=1.0, subtype='FACTOR', update=update_solarize_softness_cb)
    _FBP_OBJECT_RNA.fbp_solarize_factor = FloatProperty(
        description="Blend between the original image and the solarized result.",
        name="Factor", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_solarize_factor_cb)
    _FBP_OBJECT_RNA.fbp_tritone_shadows = FloatVectorProperty(
        description="Color assigned to the darkest source luminance values by Tritone.",
        name="Shadows Tone", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.02, 0.03, 0.08, 1.0), update=update_tritone_shadows_cb)
    _FBP_OBJECT_RNA.fbp_tritone_midtones = FloatVectorProperty(
        description="Color assigned around the editable Tritone midpoint.",
        name="Midtones Tone", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.55, 0.20, 0.22, 1.0), update=update_tritone_midtones_cb)
    _FBP_OBJECT_RNA.fbp_tritone_highlights = FloatVectorProperty(
        description="Color assigned to the brightest source luminance values by Tritone.",
        name="Highlights Tone", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(1.0, 0.86, 0.55, 1.0), update=update_tritone_highlights_cb)
    _FBP_OBJECT_RNA.fbp_tritone_midpoint = FloatProperty(
        description="Luminance position of the Tritone midtone color. Lower values expand highlights; higher values expand shadows.",
        name="Midpoint", default=0.5, min=0.01, max=0.99, subtype='FACTOR', update=update_tritone_midpoint_cb)
    _FBP_OBJECT_RNA.fbp_tritone_factor = FloatProperty(
        description="Blend between the original image and the Tritone mapping.",
        name="Factor", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_tritone_factor_cb)
    _FBP_OBJECT_RNA.fbp_film_fade_color = FloatVectorProperty(
        description="Color cast introduced by Film Fade. Warm brown, amber or faded cyan tones reproduce different aged-film stocks.",
        name="Fade Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.72, 0.48, 0.28, 1.0), update=update_film_fade_color_cb)
    _FBP_OBJECT_RNA.fbp_film_fade_amount = FloatProperty(
        description="Overall strength of Film Fade, including tint, desaturation and contrast compression.",
        name="Amount", default=0.35, min=0.0, max=1.0, subtype='FACTOR', update=update_film_fade_amount_cb)
    _FBP_OBJECT_RNA.fbp_film_fade_desaturation = FloatProperty(
        description="How strongly Film Fade removes color as Amount increases.",
        name="Desaturation", default=0.45, min=0.0, max=1.0, subtype='FACTOR', update=update_film_fade_desaturation_cb)
    _FBP_OBJECT_RNA.fbp_film_fade_contrast_loss = FloatProperty(
        description="How strongly Film Fade compresses highlights and shadows toward middle grey.",
        name="Contrast Loss", default=0.30, min=0.0, max=1.0, subtype='FACTOR', update=update_film_fade_contrast_loss_cb)
    _FBP_OBJECT_RNA.fbp_triangle_blur_radius = FloatProperty(name="Radius", description="Triangle Blur radius measured in source-image pixels.", default=8.0, min=0.0, soft_max=128.0, max=512.0, update=update_triangle_blur_radius_cb)
    _FBP_OBJECT_RNA.fbp_triangle_blur_samples = IntProperty(name="Samples", description="Number of active Triangle Blur texture samples.", default=17, min=3, max=25, update=update_triangle_blur_samples_cb)
    _FBP_OBJECT_RNA.fbp_triangle_blur_factor = FloatProperty(name="Factor", description="Blend between source and Triangle Blur.", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_triangle_blur_factor_cb)
    _FBP_OBJECT_RNA.fbp_tilt_shift_position = FloatProperty(name="Focus Position", description="Position of the sharp Tilt Shift band along its rotated normal axis.", default=0.5, min=-1.0, max=2.0, soft_min=0.0, soft_max=1.0, update=update_tilt_shift_position_cb)
    _FBP_OBJECT_RNA.fbp_tilt_shift_width = FloatProperty(name="Focus Width", description="Width of the sharp Tilt Shift band measured perpendicular to its angle.", default=0.25, min=0.001, max=2.0, soft_max=1.0, update=update_tilt_shift_width_cb)
    _FBP_OBJECT_RNA.fbp_tilt_shift_angle = FloatProperty(name="Focus Angle", description="Rotate the sharp Tilt Shift band across the image. The yellow center control and blue/orange boundary controls edit this value directly.", default=0.0, subtype='ANGLE', update=update_tilt_shift_angle_cb)
    _FBP_OBJECT_RNA.fbp_tilt_shift_radius = FloatProperty(name="Blur Radius", description="Maximum Tilt Shift blur radius in source-image pixels.", default=16.0, min=0.0, soft_max=128.0, max=512.0, update=update_tilt_shift_radius_cb)
    _FBP_OBJECT_RNA.fbp_tilt_shift_factor = FloatProperty(name="Factor", description="Blend between source and Tilt Shift result.", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_tilt_shift_factor_cb)
    _FBP_OBJECT_RNA.fbp_unsharp_radius = FloatProperty(name="Radius", description="Neighbor sampling radius used by Unsharp Mask.", default=1.0, min=0.0, max=32.0, update=update_unsharp_radius_cb)
    _FBP_OBJECT_RNA.fbp_unsharp_amount = FloatProperty(name="Amount", description="Strength of sharpened local detail.", default=1.0, min=0.0, max=4.0, update=update_unsharp_amount_cb)
    _FBP_OBJECT_RNA.fbp_unsharp_factor = FloatProperty(name="Factor", description="Blend between source and sharpened image.", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_unsharp_factor_cb)
    _FBP_OBJECT_RNA.fbp_edge_detect_width = FloatProperty(name="Width", description="Edge sampling distance in source-image pixels.", default=1.0, min=0.0, max=32.0, update=update_edge_detect_width_cb)
    _FBP_OBJECT_RNA.fbp_edge_detect_strength = FloatProperty(name="Strength", description="Multiplier applied to detected edge contrast.", default=2.0, min=0.0, max=10.0, update=update_edge_detect_strength_cb)
    _FBP_OBJECT_RNA.fbp_edge_detect_threshold = FloatProperty(name="Threshold", description="Minimum Sobel edge magnitude retained.", default=0.05, min=0.0, max=1.0, subtype='FACTOR', update=update_edge_detect_threshold_cb)
    _FBP_OBJECT_RNA.fbp_edge_detect_softness = FloatProperty(name="Softness", description="Smooth transition width around the edge threshold.", default=0.04, min=0.0, max=1.0, subtype='FACTOR', update=update_edge_detect_softness_cb)
    _FBP_OBJECT_RNA.fbp_edge_detect_color = FloatVectorProperty(name="Edge Color", description="Color applied to detected edges.", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.0,0.0,0.0,1.0), update=update_edge_detect_color_cb)
    _FBP_OBJECT_RNA.fbp_edge_detect_factor = FloatProperty(name="Factor", description="Blend between source and Edge Detect.", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_edge_detect_factor_cb)
    _FBP_OBJECT_RNA.fbp_smooth_toon_levels = FloatProperty(name="Levels", description="Number of tonal bands retained by Smooth Toon.", default=6.0, min=2.0, max=64.0, precision=0, update=update_smooth_toon_levels_cb)
    _FBP_OBJECT_RNA.fbp_smooth_toon_softness = FloatProperty(name="Softness", description="Blend quantized bands back toward the source for smoother transitions.", default=0.15, min=0.0, max=1.0, subtype='FACTOR', update=update_smooth_toon_softness_cb)
    _FBP_OBJECT_RNA.fbp_smooth_toon_factor = FloatProperty(name="Factor", description="Blend between source and Smooth Toon.", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_smooth_toon_factor_cb)
    _FBP_OBJECT_RNA.fbp_adaptive_threshold_radius = FloatProperty(name="Radius", description="Neighborhood radius used to calculate local luminance.", default=4.0, min=0.0, max=64.0, update=update_adaptive_threshold_radius_cb)
    _FBP_OBJECT_RNA.fbp_adaptive_threshold_offset = FloatProperty(name="Offset", description="Bias added to local luminance before thresholding.", default=0.0, min=-1.0, max=1.0, update=update_adaptive_threshold_offset_cb)
    _FBP_OBJECT_RNA.fbp_adaptive_threshold_softness = FloatProperty(name="Softness", description="Soft transition around the adaptive threshold.", default=0.05, min=0.0, max=1.0, subtype='FACTOR', update=update_adaptive_threshold_softness_cb)
    _FBP_OBJECT_RNA.fbp_adaptive_threshold_invert = BoolProperty(name="Invert", description="Swap black and white regions in the adaptive threshold result.", default=False, update=update_adaptive_threshold_invert_cb)
    _FBP_OBJECT_RNA.fbp_adaptive_threshold_factor = FloatProperty(name="Factor", description="Blend between source and adaptive threshold result.", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_adaptive_threshold_factor_cb)
    _FBP_OBJECT_RNA.fbp_false_color_dark = FloatVectorProperty(name="Dark Color", description="Color mapped to dark source luminance.", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.0,0.05,0.3,1.0), update=update_false_color_dark_cb)
    _FBP_OBJECT_RNA.fbp_false_color_light = FloatVectorProperty(name="Light Color", description="Color mapped to bright source luminance.", subtype='COLOR', size=4, min=0.0, max=1.0, default=(1.0,0.65,0.05,1.0), update=update_false_color_light_cb)
    _FBP_OBJECT_RNA.fbp_false_color_factor = FloatProperty(name="Factor", description="Blend between source and False Color mapping.", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_false_color_factor_cb)
    _FBP_OBJECT_RNA.fbp_chromatic_aberration_distance = FloatProperty(name="Distance", description="Opposite red and blue channel offset measured in source-image pixels.", default=3.0, min=0.0, max=128.0, update=update_chromatic_aberration_distance_cb)
    _FBP_OBJECT_RNA.fbp_chromatic_aberration_angle = FloatProperty(name="Angle", description="Direction of the chromatic channel separation.", default=0.0, subtype='ANGLE', update=update_chromatic_aberration_angle_cb)
    _FBP_OBJECT_RNA.fbp_chromatic_aberration_factor = FloatProperty(name="Factor", description="Blend between source and Chromatic Aberration.", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_chromatic_aberration_factor_cb)
    _FBP_OBJECT_RNA.fbp_ink_width = FloatProperty(name="Width", description="Sobel sampling distance used to extract ink lines, measured in source-image pixels.", default=1.0, min=0.0, max=32.0, update=update_ink_width_cb)
    _FBP_OBJECT_RNA.fbp_ink_threshold = FloatProperty(name="Threshold", description="Minimum edge magnitude converted into ink.", default=0.045, min=0.0, max=1.0, subtype='FACTOR', update=update_ink_threshold_cb)
    _FBP_OBJECT_RNA.fbp_ink_softness = FloatProperty(name="Softness", description="Feather the ink threshold for smoother or rougher line transitions.", default=0.05, min=0.0, max=1.0, subtype='FACTOR', update=update_ink_softness_cb)
    _FBP_OBJECT_RNA.fbp_ink_strength = FloatProperty(name="Strength", description="Multiply the detected edge response before thresholding.", default=2.5, min=0.0, max=16.0, update=update_ink_strength_cb)
    _FBP_OBJECT_RNA.fbp_ink_color = FloatVectorProperty(name="Ink Color", description="Color applied to extracted ink lines.", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.015,0.01,0.008,1.0), update=update_ink_color_cb)
    _FBP_OBJECT_RNA.fbp_ink_paper_color = FloatVectorProperty(name="Paper Color", description="Base paper color used when Preserve Color is reduced.", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.94,0.90,0.80,1.0), update=update_ink_paper_color_cb)
    _FBP_OBJECT_RNA.fbp_ink_preserve_color = FloatProperty(name="Preserve Color", description="Blend the original image color into the paper base before applying ink lines.", default=0.20, min=0.0, max=1.0, subtype='FACTOR', update=update_ink_preserve_color_cb)
    _FBP_OBJECT_RNA.fbp_ink_factor = FloatProperty(name="Factor", description="Blend between the original image and the complete Ink treatment.", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_ink_factor_cb)
    _FBP_OBJECT_RNA.fbp_edge_work_radius = FloatProperty(name="Radius", description="Inner local-average radius used by Edge Work, measured in source-image pixels.", default=1.5, min=0.0, max=64.0, update=update_edge_work_radius_cb)
    _FBP_OBJECT_RNA.fbp_edge_work_thickness = FloatProperty(name="Thickness", description="Distance between the inner and outer luminance scales used to form broad illustrated edges.", default=4.0, min=0.0, max=128.0, update=update_edge_work_thickness_cb)
    _FBP_OBJECT_RNA.fbp_edge_work_strength = FloatProperty(name="Strength", description="Multiplier applied to the difference between the two local luminance scales.", default=5.0, min=0.0, max=32.0, update=update_edge_work_strength_cb)
    _FBP_OBJECT_RNA.fbp_edge_work_threshold = FloatProperty(name="Threshold", description="Minimum Edge Work response retained.", default=0.025, min=0.0, max=1.0, subtype='FACTOR', update=update_edge_work_threshold_cb)
    _FBP_OBJECT_RNA.fbp_edge_work_softness = FloatProperty(name="Softness", description="Feather the Edge Work threshold.", default=0.06, min=0.0, max=1.0, subtype='FACTOR', update=update_edge_work_softness_cb)
    _FBP_OBJECT_RNA.fbp_edge_work_color = FloatVectorProperty(name="Edge Color", description="Color applied to Edge Work lines.", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.02,0.015,0.01,1.0), update=update_edge_work_color_cb)
    _FBP_OBJECT_RNA.fbp_edge_work_factor = FloatProperty(name="Factor", description="Blend between source and Edge Work.", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_edge_work_factor_cb)
    _FBP_OBJECT_RNA.fbp_pencil_sketch_radius = FloatProperty(name="Radius", description="Local luminance blur radius controlling Pencil Sketch line size.", default=6.0, min=0.0, max=128.0, update=update_pencil_sketch_radius_cb)
    _FBP_OBJECT_RNA.fbp_pencil_sketch_contrast = FloatProperty(name="Contrast", description="Darken and strengthen generated graphite marks.", default=1.6, min=0.0, max=8.0, update=update_pencil_sketch_contrast_cb)
    _FBP_OBJECT_RNA.fbp_pencil_sketch_graphite = FloatVectorProperty(name="Graphite Color", description="Color used for dark pencil marks.", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.03,0.025,0.02,1.0), update=update_pencil_sketch_graphite_cb)
    _FBP_OBJECT_RNA.fbp_pencil_sketch_paper = FloatVectorProperty(name="Paper Color", description="Color used for unmarked paper regions.", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.96,0.93,0.84,1.0), update=update_pencil_sketch_paper_cb)
    _FBP_OBJECT_RNA.fbp_pencil_sketch_color_amount = FloatProperty(name="Color Amount", description="Reintroduce source color beneath the graphite shading.", default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=update_pencil_sketch_color_amount_cb)
    _FBP_OBJECT_RNA.fbp_pencil_sketch_factor = FloatProperty(name="Factor", description="Blend between source and Pencil Sketch.", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_pencil_sketch_factor_cb)
    _FBP_OBJECT_RNA.fbp_poster_edges_levels = FloatProperty(name="Levels", description="Number of smooth color bands retained before outlines are applied.", default=5.0, min=2.0, max=64.0, precision=0, update=update_poster_edges_levels_cb)
    _FBP_OBJECT_RNA.fbp_poster_edges_softness = FloatProperty(name="Band Softness", description="Transition softness between posterized color bands.", default=0.08, min=0.0, max=1.0, subtype='FACTOR', update=update_poster_edges_softness_cb)
    _FBP_OBJECT_RNA.fbp_poster_edges_width = FloatProperty(name="Edge Width", description="Sobel edge sampling distance in source-image pixels.", default=1.0, min=0.0, max=32.0, update=update_poster_edges_width_cb)
    _FBP_OBJECT_RNA.fbp_poster_edges_strength = FloatProperty(name="Edge Strength", description="Multiplier applied to Poster Edges outlines.", default=2.8, min=0.0, max=16.0, update=update_poster_edges_strength_cb)
    _FBP_OBJECT_RNA.fbp_poster_edges_threshold = FloatProperty(name="Edge Threshold", description="Minimum Poster Edges outline magnitude retained.", default=0.045, min=0.0, max=1.0, subtype='FACTOR', update=update_poster_edges_threshold_cb)
    _FBP_OBJECT_RNA.fbp_poster_edges_color = FloatVectorProperty(name="Edge Color", description="Outline color used by Poster Edges.", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.01,0.008,0.006,1.0), update=update_poster_edges_color_cb)
    _FBP_OBJECT_RNA.fbp_poster_edges_factor = FloatProperty(name="Factor", description="Blend between source and Poster Edges.", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_poster_edges_factor_cb)
    _FBP_OBJECT_RNA.fbp_crosshatch_scale = FloatProperty(name="Scale", description="Density of procedural hatch lines across the source canvas.", default=72.0, min=1.0, soft_max=400.0, max=2000.0, update=update_crosshatch_scale_cb)
    _FBP_OBJECT_RNA.fbp_crosshatch_rotation = FloatProperty(name="Rotation", description="Rotate all Crosshatch directions around the image center.", default=0.0, subtype='ANGLE', update=update_crosshatch_rotation_cb)
    _FBP_OBJECT_RNA.fbp_crosshatch_line_width = FloatProperty(name="Line Width", description="Thickness of each hatch line inside its repeating cell.", default=0.10, min=0.001, max=0.49, subtype='FACTOR', update=update_crosshatch_line_width_cb)
    _FBP_OBJECT_RNA.fbp_crosshatch_levels = IntProperty(name="Levels", description="Maximum number of hatch directions used in progressively darker regions.", default=4, min=1, max=4, update=update_crosshatch_levels_cb)
    _FBP_OBJECT_RNA.fbp_crosshatch_ink = FloatVectorProperty(name="Ink Color", description="Color used for Crosshatch lines.", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.02,0.015,0.01,1.0), update=update_crosshatch_ink_cb)
    _FBP_OBJECT_RNA.fbp_crosshatch_paper = FloatVectorProperty(name="Paper Color", description="Base color used behind Crosshatch lines.", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.95,0.91,0.80,1.0), update=update_crosshatch_paper_cb)
    _FBP_OBJECT_RNA.fbp_crosshatch_preserve_color = FloatProperty(name="Preserve Color", description="Blend original image color into the Crosshatch paper base.", default=0.10, min=0.0, max=1.0, subtype='FACTOR', update=update_crosshatch_preserve_color_cb)
    _FBP_OBJECT_RNA.fbp_crosshatch_factor = FloatProperty(name="Factor", description="Blend between source and Crosshatch.", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_crosshatch_factor_cb)
    _FBP_OBJECT_RNA.fbp_emboss_angle = FloatProperty(name="Angle", description="Direction of the opposing samples that create the embossed relief.", default=0.78539816339, subtype='ANGLE', update=update_emboss_angle_cb)
    _FBP_OBJECT_RNA.fbp_emboss_distance = FloatProperty(name="Distance", description="Distance between opposing Emboss samples in source-image pixels.", default=2.0, min=0.0, max=128.0, update=update_emboss_distance_cb)
    _FBP_OBJECT_RNA.fbp_emboss_strength = FloatProperty(name="Strength", description="Contrast multiplier applied to directional relief.", default=2.0, min=-8.0, max=8.0, update=update_emboss_strength_cb)
    _FBP_OBJECT_RNA.fbp_emboss_bias = FloatProperty(name="Bias", description="Middle-grey resting value of the embossed relief.", default=0.5, min=0.0, max=1.0, subtype='FACTOR', update=update_emboss_bias_cb)
    _FBP_OBJECT_RNA.fbp_emboss_color_amount = FloatProperty(name="Color Amount", description="Blend source color into the grayscale embossed relief.", default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=update_emboss_color_amount_cb)
    _FBP_OBJECT_RNA.fbp_emboss_factor = FloatProperty(name="Factor", description="Blend between source and Emboss.", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_emboss_factor_cb)
    _FBP_OBJECT_RNA.fbp_solid_mask_color = FloatVectorProperty(description="RGBA color blended over the source by Solid Mask.",
        name="Mask Color", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.0, 0.0, 0.0, 1.0), update=update_solid_mask_color_cb)
    _FBP_OBJECT_RNA.fbp_solid_mask_factor = FloatProperty(description="Blend amount between the original source and Solid Mask color. Zero keeps the source; one outputs only the mask color.",
        name="Mask Factor", default=0.5, min=0.0, max=1.0, subtype='FACTOR', update=update_solid_mask_factor_cb)
    _FBP_OBJECT_RNA.fbp_color_isolate_target = FloatVectorProperty(description="Color that Color Isolate keeps or emphasizes while suppressing colors outside the tolerance range.", name="Target Color", subtype='COLOR', size=4, min=0.0, max=1.0, default=(1.0, 0.0, 0.0, 1.0), update=update_color_isolate_target_cb)
    _FBP_OBJECT_RNA.fbp_color_isolate_tolerance = FloatProperty(description="Maximum color distance considered a match to the target color. Higher values include a broader range of hues.", name="Tolerance", default=0.12, min=0.0, max=1.0, subtype='FACTOR', update=update_color_isolate_tolerance_cb)
    _FBP_OBJECT_RNA.fbp_color_isolate_falloff = FloatProperty(description="Soft transition width around the Color Isolate tolerance boundary. Higher values create smoother masks.", name="Falloff", default=0.1, min=0.0, max=1.0, subtype='FACTOR', update=update_color_isolate_falloff_cb)
    _FBP_OBJECT_RNA.fbp_color_isolate_factor = FloatProperty(description="Blend between the original image and Color Isolate.", name="Factor", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_color_isolate_factor_cb)
    _FBP_OBJECT_RNA.fbp_white_balance_temperature = FloatProperty(name="Temperature", description="Shift white balance from cold blue at negative values to warm amber at positive values.", default=0.0, min=-1.0, max=1.0, update=update_white_balance_temperature_cb)
    _FBP_OBJECT_RNA.fbp_white_balance_tint = FloatProperty(name="Tint", description="Shift white balance from green at negative values to magenta at positive values.", default=0.0, min=-1.0, max=1.0, update=update_white_balance_tint_cb)
    _FBP_OBJECT_RNA.fbp_white_balance_factor = FloatProperty(name="Factor", description="Blend between the original image and White Balance correction.", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_white_balance_factor_cb)
    _FBP_OBJECT_RNA.fbp_curves_factor = FloatProperty(name="Factor", description="Blend between the original image and the RGB Curves result.", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_curves_factor_cb)
    _FBP_OBJECT_RNA.fbp_duotone_shadows = FloatVectorProperty(description="RGBA color mapped to dark source values by Duotone.", name="Shadows Tone", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.0, 0.0, 0.2, 1.0), update=update_duotone_shadows_cb)
    _FBP_OBJECT_RNA.fbp_duotone_highlights = FloatVectorProperty(description="RGBA color mapped to bright source values by Duotone.", name="Highlights Tone", subtype='COLOR', size=4, min=0.0, max=1.0, default=(1.0, 0.8, 0.6, 1.0), update=update_duotone_highlights_cb)
    _FBP_OBJECT_RNA.fbp_recolor_factor = FloatProperty(
        description="Blend between the original source and the colors mapped through the editable Color Ramp.",
        name="Factor", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_recolor_factor_cb)
    _FBP_OBJECT_RNA.fbp_gradient_map_factor = FloatProperty(
        description="Blend between the original source and the Figma-style Gradient Map color ramp.",
        name="Factor", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_gradient_map_factor_cb)
    _FBP_OBJECT_RNA.fbp_channel_mixer_red = FloatProperty(
        description="Contribution of the source red channel in the Figma-style Channel Mixer.",
        name="Red", default=1.0, min=-2.0, max=2.0, soft_min=0.0, soft_max=2.0, update=update_channel_mixer_red_cb)
    _FBP_OBJECT_RNA.fbp_channel_mixer_green = FloatProperty(
        description="Contribution of the source green channel in the Figma-style Channel Mixer.",
        name="Green", default=1.0, min=-2.0, max=2.0, soft_min=0.0, soft_max=2.0, update=update_channel_mixer_green_cb)
    _FBP_OBJECT_RNA.fbp_channel_mixer_blue = FloatProperty(
        description="Contribution of the source blue channel in the Figma-style Channel Mixer.",
        name="Blue", default=1.0, min=-2.0, max=2.0, soft_min=0.0, soft_max=2.0, update=update_channel_mixer_blue_cb)
    _FBP_OBJECT_RNA.fbp_channel_mixer_factor = FloatProperty(
        description="Blend between the original source and the mixed RGB channel result.",
        name="Factor", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_channel_mixer_factor_cb)
    _FBP_OBJECT_RNA.fbp_dither_style = EnumProperty(
        name="Style",
        description="Real ordered dithering. Source luminance is compared against a threshold matrix.",
        items=(
            ('ORDERED', "Bayer 4x4", "Classic ordered dithering using a 4x4 Bayer threshold matrix", 'MESH_GRID', 0),
            ('PLUS_X', "Bayer 2x2", "Chunkier ordered dithering using a 2x2 Bayer threshold matrix", 'SNAP_GRID', 1),
            ('PLUS', "Noise dither", "Stable stochastic dithering using per-cell noise thresholds", 'RNDCURVE', 2),
            ('XPIXELS', "Threshold", "Plain one-bit threshold without a matrix", 'IPO_CONSTANT', 3),
            ('LINES', "Line screen", "Line-screen fallback based on source luminance", 'IPO_LINEAR', 4),
        ),
        default='ORDERED', update=update_dither_style_cb)
    _FBP_OBJECT_RNA.fbp_dither_size = FloatProperty(
        description="Dither pixel size. Lower values create finer dithering, higher values make chunkier pixels.",
        name="Pixel Size", default=3.0, min=1.0, soft_max=64.0, max=512.0, precision=1, update=update_dither_size_cb)
    _FBP_OBJECT_RNA.fbp_dither_brightness = FloatProperty(
        description="Brightness multiplier applied before threshold comparison.",
        name="Brightness", default=1.0, min=0.0, soft_max=3.0, max=8.0, subtype='FACTOR', update=update_dither_brightness_cb)
    _FBP_OBJECT_RNA.fbp_dither_contrast = FloatProperty(
        description="Pre-contrast applied before converting luminance into dithered pixels.",
        name="Contrast", default=1.0, min=0.0, soft_max=3.0, max=8.0, precision=3, update=update_dither_contrast_cb)
    _FBP_OBJECT_RNA.fbp_dither_mono = BoolProperty(
        description="Use Mono Color for the dithered ink. When disabled, future enhanced modes can preserve source color.",
        name="Mono", default=True, update=update_dither_mono_cb)
    _FBP_OBJECT_RNA.fbp_dither_mono_color = FloatVectorProperty(
        description="Ink color used when Mono is enabled.",
        name="Mono Color", subtype='COLOR', size=4, default=(0.0, 0.0, 0.0, 1.0), min=0.0, max=1.0, update=update_dither_mono_color_cb)
    _FBP_OBJECT_RNA.fbp_dither_factor = FloatProperty(
        description="Blend between the original image and the Dither result.",
        name="Factor", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_dither_factor_cb)

    _FBP_OBJECT_RNA.fbp_bloom_threshold = FloatProperty(
        description="Luminance level that starts contributing to the Bloom glow.",
        name="Threshold", default=0.72, min=0.0, max=1.0, subtype='FACTOR', update=update_bloom_threshold_cb)
    _FBP_OBJECT_RNA.fbp_bloom_softness = FloatProperty(
        description="Soft transition around the Bloom threshold. Higher values create a broader glow region.",
        name="Softness", default=0.18, min=0.001, max=1.0, subtype='FACTOR', update=update_bloom_softness_cb)
    _FBP_OBJECT_RNA.fbp_bloom_intensity = FloatProperty(
        description="Strength of the added Bloom color in highlight regions.",
        name="Intensity", default=0.65, min=0.0, soft_max=2.0, max=4.0, precision=3, update=update_bloom_intensity_cb)
    _FBP_OBJECT_RNA.fbp_bloom_color = FloatVectorProperty(
        description="Color added to bright regions by the Bloom effect.",
        name="Glow Color", subtype='COLOR', size=4, default=(1.0, 0.82, 0.48, 1.0), min=0.0, max=1.0, update=update_bloom_color_cb)
    _FBP_OBJECT_RNA.fbp_bloom_factor = FloatProperty(
        description="Blend between the original image and the Bloom result.",
        name="Factor", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_bloom_factor_cb)
    _FBP_OBJECT_RNA.fbp_filter_preset_sepia = FloatProperty(
        description="Blend in a sepia preset based on luminance.",
        name="Sepia", default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=update_filter_preset_sepia_cb)
    _FBP_OBJECT_RNA.fbp_filter_preset_warm = FloatProperty(
        description="Blend in a warm orange filter preset.",
        name="Warm", default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=update_filter_preset_warm_cb)
    _FBP_OBJECT_RNA.fbp_filter_preset_cool = FloatProperty(
        description="Blend in a cool blue filter preset.",
        name="Cool", default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=update_filter_preset_cool_cb)
    _FBP_OBJECT_RNA.fbp_filter_preset_noir = FloatProperty(
        description="Blend in a high-contrast monochrome noir preset.",
        name="Noir", default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=update_filter_preset_noir_cb)
    _FBP_OBJECT_RNA.fbp_filter_preset_factor = FloatProperty(
        description="Overall intensity of the Figma-inspired Filter Presets stack.",
        name="Factor", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_filter_preset_factor_cb)
    _FBP_OBJECT_RNA.fbp_paper_fiber_scale = FloatProperty(description="Spatial frequency of Paper Fibers. Higher values produce finer, more numerous fibers.", name="Fiber Scale", default=140.0, min=0.01, soft_max=3000.0, precision=1, update=update_paper_fiber_scale_cb)
    _FBP_OBJECT_RNA.fbp_paper_fiber_intensity = FloatProperty(description="Strength of Paper Fibers mixed into the source image.", name="Intensity", default=0.40, min=0.0, max=1.0, subtype='FACTOR', update=update_paper_fiber_intensity_cb)
    _FBP_OBJECT_RNA.fbp_paper_fiber_phase = FloatProperty(description="Fourth-dimensional noise coordinate used to animate or select a different Paper Fibers pattern.", name="Animate (W)", default=0.0, soft_min=-100.0, soft_max=100.0, precision=3, update=update_paper_fiber_phase_cb)
    _FBP_OBJECT_RNA.fbp_gradient_light_center_x = FloatProperty(description="Horizontal center of the Gradient controller in source-image UV space. Move the paired viewport controls to reposition it freely across the cropped image.", name="Center X", default=0.5, soft_min=0.0, soft_max=1.0, min=-2.0, max=3.0, update=update_gradient_light_center_x_cb)
    _FBP_OBJECT_RNA.fbp_gradient_light_center_y = FloatProperty(description="Vertical center of the Gradient controller in source-image UV space. Move the paired viewport controls to reposition it freely across the cropped image.", name="Center Y", default=0.5, soft_min=0.0, soft_max=1.0, min=-2.0, max=3.0, update=update_gradient_light_center_y_cb)
    _FBP_OBJECT_RNA.fbp_gradient_light_angle = FloatProperty(description="Direction of Gradient Light across the plane, expressed as an angle.", name="Light Angle", default=0.0, soft_min=-3.141593, soft_max=3.141593, subtype='ANGLE', update=update_gradient_light_angle_cb)
    _FBP_OBJECT_RNA.fbp_gradient_light_strength = FloatProperty(description="Blend between the original source and the directional Color Ramp lighting.", name="Strength", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_gradient_light_strength_cb)
    _FBP_OBJECT_RNA.fbp_gradient_shadow_position = FloatProperty(description="Offset of the Gradient Light shadow boundary across the plane.", name="Shadow Position", default=0.0, soft_min=-2.0, soft_max=2.0, precision=3, update=update_gradient_shadow_position_cb)
    _FBP_OBJECT_RNA.fbp_gradient_softness = FloatProperty(description="Width of the Gradient Light transition between lit and shadowed regions.", name="Softness", default=0.5, min=0.0, max=1.0, subtype='FACTOR', update=update_gradient_softness_cb)
    _FBP_OBJECT_RNA.fbp_gradient_shadow_color = FloatVectorProperty(description="RGBA color mixed into the shadow side of Gradient Light.", name="Shadow Color", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.0, 0.0, 0.05, 1.0), update=update_gradient_shadow_color_cb)
    _FBP_OBJECT_RNA.fbp_rim_mode = EnumProperty(
        name="Rim Type",
        description="Place the colored rim inside the alpha silhouette, outside it, or on both sides",
        items=(
            ('INNER', 'Inner', 'Draw the rim inside the source silhouette'),
            ('OUTER', 'Outer', 'Expand alpha and draw the rim outside the source silhouette'),
            ('BOTH', 'Both', 'Draw a continuous rim on both sides of the source edge'),
        ),
        default='INNER', update=update_rim_mode_cb)
    _FBP_OBJECT_RNA.fbp_rim_blend_mode = EnumProperty(
        name="Blend Mode",
        description="Blend Rim Color with the current layer color",
        items=(
            ('NORMAL', 'Normal', 'Use Rim Color directly'),
            ('MULTIPLY', 'Multiply', 'Darken with Rim Color'),
            ('SCREEN', 'Screen', 'Lighten with Rim Color'),
            ('OVERLAY', 'Overlay', 'Increase contrast with Rim Color'),
            ('SOFT_LIGHT', 'Soft Light', 'Apply a gentle contrast blend'),
            ('HARD_LIGHT', 'Hard Light', 'Apply a strong contrast blend'),
            ('ADD', 'Add', 'Add Rim Color to the layer'),
            ('DIFFERENCE', 'Difference', 'Use the absolute color difference'),
        ),
        default='NORMAL', update=update_rim_blend_mode_cb)
    _FBP_OBJECT_RNA.fbp_rim_width = FloatProperty(description="Base UV distance used to select the source alpha edge.", name="Width", default=0.012, min=0.00001, soft_max=0.1, max=0.5, precision=5, update=update_rim_width_cb)
    _FBP_OBJECT_RNA.fbp_rim_expand = FloatProperty(description="Grow positive or shrink negative the selected edge band without changing the source image.", name="Expand / Shrink", default=0.0, soft_min=-0.1, soft_max=0.1, min=-0.5, max=0.5, precision=4, update=update_rim_expand_cb)
    _FBP_OBJECT_RNA.fbp_rim_offset_x = FloatProperty(description="Move the generated rim horizontally in UV space while preserving the source layer position.", name="Offset X", default=0.0, soft_min=-0.25, soft_max=0.25, min=-1.0, max=1.0, precision=4, update=update_rim_offset_x_cb)
    _FBP_OBJECT_RNA.fbp_rim_offset_y = FloatProperty(description="Move the generated rim vertically in UV space while preserving the source layer position.", name="Offset Y", default=0.0, soft_min=-0.25, soft_max=0.25, min=-1.0, max=1.0, precision=4, update=update_rim_offset_y_cb)
    _FBP_OBJECT_RNA.fbp_rim_rotation = FloatProperty(description="Rotate the Rim offset direction in the local space of the plane. This value is driven by rotating the viewport control.", name="Rotation", default=0.0, min=-6.283185307, max=6.283185307, subtype='ANGLE', update=update_rim_rotation_cb)
    _FBP_OBJECT_RNA.fbp_rim_blur = FloatProperty(description="Spatial radius of the second alpha kernel. Increase it for a visibly broader, softer edge.", name="Blur Radius", default=0.015, min=0.0, soft_max=0.1, max=0.5, precision=4, update=update_rim_blur_cb)
    _FBP_OBJECT_RNA.fbp_rim_softness = FloatProperty(description="Mix between the sharp Width kernel and the wider Blur Radius kernel.", name="Feather", default=0.5, min=0.0, max=1.0, subtype='FACTOR', update=update_rim_softness_cb)
    _FBP_OBJECT_RNA.fbp_rim_intensity = FloatProperty(description="Opacity and strength of the colored rim.", name="Intensity", default=1.0, min=0.0, soft_max=2.0, max=2.0, update=update_rim_intensity_cb)
    _FBP_OBJECT_RNA.fbp_rim_color = FloatVectorProperty(description="RGBA color applied to the generated rim.", name="Rim Color", subtype='COLOR', size=4, min=0.0, max=1.0, default=(1.0, 0.35, 0.05, 1.0), update=update_rim_color_cb)
    _FBP_OBJECT_RNA.fbp_shadow_mode = EnumProperty(
        name="Shadow Type",
        description="Choose whether the blurred offset alpha is drawn outside the source silhouette or carved inside its visible alpha",
        items=[
            ('OUTER', 'Outer', 'Place the shadow outside the source alpha silhouette'),
            ('INNER', 'Inner', 'Place the shadow inside the source alpha silhouette'),
        ],
        default='OUTER', update=update_shadow_mode_cb,
    )
    _FBP_OBJECT_RNA.fbp_shadow_blend_mode = EnumProperty(
        name="Blend Mode",
        description="Blend the shadow color with the current layer color. This affects the layer effect itself; blending against layers behind the plane is controlled by Layer Blend",
        items=[
            ('NORMAL', 'Normal', 'Use the selected Shadow Color without additional color blending'),
            ('MULTIPLY', 'Multiply', 'Darken the layer with the shadow color'),
            ('SCREEN', 'Screen', 'Lighten the layer with the shadow color'),
            ('OVERLAY', 'Overlay', 'Increase contrast using the shadow color'),
            ('SOFT_LIGHT', 'Soft Light', 'Apply a softer contrast blend'),
            ('HARD_LIGHT', 'Hard Light', 'Apply a stronger contrast blend'),
            ('ADD', 'Add', 'Add the shadow color to the layer'),
            ('DIFFERENCE', 'Difference', 'Use the absolute difference from the shadow color'),
        ],
        default='NORMAL', update=update_shadow_blend_mode_cb,
    )
    _FBP_OBJECT_RNA.fbp_shadow_offset_x = FloatProperty(
        name="Position X",
        description="Move the shadow horizontally in image UV space without moving the source layer",
        default=0.025, soft_min=-0.25, soft_max=0.25, min=-1.0, max=1.0,
        precision=4, update=update_shadow_offset_x_cb,
    )
    _FBP_OBJECT_RNA.fbp_shadow_offset_y = FloatProperty(
        name="Position Y",
        description="Move the shadow vertically in image UV space without moving the source layer",
        default=-0.025, soft_min=-0.25, soft_max=0.25, min=-1.0, max=1.0,
        precision=4, update=update_shadow_offset_y_cb,
    )
    _FBP_OBJECT_RNA.fbp_shadow_blur = FloatProperty(
        name="Blur",
        description="Radius of the alpha sampling kernel used to soften the shadow edge",
        default=0.02, min=0.0, soft_max=0.12, max=0.5, precision=4,
        update=update_shadow_blur_cb,
    )
    _FBP_OBJECT_RNA.fbp_shadow_opacity = FloatProperty(
        name="Opacity",
        description="Maximum opacity of the generated inner or outer shadow",
        default=0.65, min=0.0, max=1.0, subtype='FACTOR', update=update_shadow_opacity_cb,
    )
    _FBP_OBJECT_RNA.fbp_shadow_color = FloatVectorProperty(
        name="Shadow Color",
        description="Color used by the generated shadow. Overall transparency is controlled by Opacity",
        subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.0, 0.0, 0.0, 1.0), update=update_shadow_color_cb,
    )
    _FBP_OBJECT_RNA.fbp_gobo_pattern_scale = FloatProperty(description="Spatial scale of the procedural Gobo Shadows pattern. Higher values create smaller projected shapes.", name="Pattern Scale", default=10.0, min=0.001, soft_max=100.0, precision=3, update=update_gobo_pattern_scale_cb)
    _FBP_OBJECT_RNA.fbp_gobo_rotation = FloatProperty(description="Rotate the Gobo Shadows pattern around the plane center.", name="Rotation Angle", default=0.5, soft_min=-3.141593, soft_max=3.141593, subtype='ANGLE', update=update_gobo_rotation_cb)
    _FBP_OBJECT_RNA.fbp_gobo_sharpness = FloatProperty(description="Hardness of Gobo Shadows pattern edges. Lower values blur transitions; higher values create crisp shapes.", name="Sharpness", default=0.8, min=0.0, max=1.0, subtype='FACTOR', update=update_gobo_sharpness_cb)
    _FBP_OBJECT_RNA.fbp_crt_line_count = FloatProperty(description="Approximate number of horizontal CRT scanlines distributed across the image height.", name="Line Count", default=200.0, min=1.0, soft_max=2000.0, precision=0, update=update_crt_line_count_cb)
    _FBP_OBJECT_RNA.fbp_crt_opacity = FloatProperty(description="Strength of dark CRT scanlines blended over the source image.", name="Opacity", default=0.15, min=0.0, max=1.0, subtype='FACTOR', update=update_crt_opacity_cb)
    _FBP_OBJECT_RNA.fbp_vignette_radius = FloatProperty(description="Distance from the image center before Vignette darkening becomes prominent.", name="Radius", default=0.5, min=0.0, soft_max=2.0, precision=3, update=update_vignette_radius_cb)
    _FBP_OBJECT_RNA.fbp_vignette_smoothness = FloatProperty(description="Width and softness of the Vignette transition. Higher values create a broader gradual falloff.", name="Smoothness", default=0.2, min=0.0, max=1.0, subtype='FACTOR', update=update_vignette_smoothness_cb)
    _FBP_OBJECT_RNA.fbp_vignette_strength = FloatProperty(description="Maximum amount of Vignette darkening applied near the image edges.", name="Strength", default=0.8, min=0.0, max=1.0, subtype='FACTOR', update=update_vignette_strength_cb)

    _register_effect_animation_properties()


# SECTION 03 - Unregister properties #
def fbp_registered_type_property_snapshot():
    """Return immutable exact RNA ownership data for diagnostics."""
    snapshot = {}
    for raw_owner_name, registry in _FBP_REGISTERED_TYPE_PROPERTIES.items():
        owner_name = _fbp_rna_property_name(raw_owner_name)
        if not owner_name or not isinstance(registry, dict) or not registry:
            continue
        snapshot[owner_name] = tuple(registry)
    return snapshot


def _unregister_fbp_type_properties(owner, owner_name):
    """Remove only RNA properties assigned by this module generation."""
    owner_name = _fbp_rna_property_name(owner_name)
    registry = _FBP_REGISTERED_TYPE_PROPERTIES.get(owner_name, {})
    names = tuple(registry) if isinstance(registry, dict) else tuple(registry or ())
    removed = unregister_type_properties(owner, names)
    if isinstance(registry, dict):
        registry.clear()
    else:
        _FBP_REGISTERED_TYPE_PROPERTIES[owner_name] = {}
    return removed


def unregister_properties():
    removed = 0
    for owner, owner_name in (
        (bpy.types.Scene, "Scene"),
        (bpy.types.Collection, "Collection"),
        (bpy.types.Object, "Object"),
    ):
        removed += _unregister_fbp_type_properties(owner, owner_name)
    return removed


# SECTION 04 - Registerable classes #
property_classes = (
    FBP_AddonPreferences,
    FBP_LayerItem,
    FBP_EffectInstanceChannel,
    FBP_EffectInstanceAnimation,
    FBP_EffectItem,
    FBP_EffectGroupItem,
    FBP_LayerTreeRowItem,
    FBP_ImageItem,
    FBP_PendingPlaneItem,
    FBP_PendingTreeRowItem,
    FBP_GenerationRenameItem,
)


def register():
    global _preferences_init_attempts
    _preferences_init_attempts = 0
    clear_interface_preferences_cache()
    register_classes(property_classes)
    try:
        register_properties()
    except Exception:
        unregister_properties()
        unregister_classes(property_classes)
        raise
    # The isolated background child loads a snapshot that already contains all
    # Scene properties. Do not start a preference-initialization timer that could
    # wake while Cycles is rendering and rewrite output or UI defaults.
    if not bool(getattr(bpy.app, "background", False)):
        try:
            from .safe_tasks import schedule_once
            schedule_once(
                "properties.initialize_scene_preferences",
                _initialize_scene_preferences_after_register,
                first_interval=0.05,
            )
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not schedule Frame By Plane preference initialization", exc)



def _clear_runtime_ui_rows_before_unregister():
    """Release transient PropertyGroup rows before their RNA classes disappear."""
    try:
        scenes = tuple(getattr(getattr(bpy, 'data', None), 'scenes', ()) or ())
    except FBP_DATA_ERRORS:
        return
    for scene in scenes:
        for attr in ('fbp_layer_tree_rows', 'fbp_pending_tree_rows', 'fbp_layers'):
            try:
                rows = getattr(scene, attr, None)
                if rows is not None:
                    rows.clear()
            except FBP_DATA_ERRORS:
                pass
        try:
            scene.fbp_layer_tree_signature = ''
        except FBP_DATA_ERRORS:
            pass


def unregister():
    global _preferences_init_attempts
    _preferences_init_attempts = 0
    clear_interface_preferences_cache()
    _clear_runtime_ui_rows_before_unregister()
    unregister_properties()
    unregister_classes(property_classes)
