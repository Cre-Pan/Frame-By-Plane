"""Shared constants for Frame By Plane.

This module is intentionally Blender-light: it avoids bpy imports so it can be
tested and refactored independently.
"""
from .support_policy import (
    FBP_LTS_CORE_SCOPE as _FBP_LTS_CORE_SCOPE,
    FBP_LTS_PLATFORM_IDS as _FBP_LTS_PLATFORM_IDS,
    FBP_LTS_PLATFORM_LABEL as _FBP_LTS_PLATFORM_LABEL,
    FBP_LTS_PREVIEW_SCOPE as _FBP_LTS_PREVIEW_SCOPE,
    FBP_LTS_SOURCE_FORMATS as _FBP_LTS_SOURCE_FORMATS,
    FBP_LTS_TARGET_VERSION as _FBP_LTS_TARGET_VERSION,
)

# Release metadata lives here so the add-on header, preferences and local
# What's New UI cannot silently drift apart during incremental releases.
FBP_VERSION = (7, 1, 10)
FBP_VERSION_STRING = ".".join(str(part) for part in FBP_VERSION)
FBP_VERSION_FAMILY = ".".join(str(part) for part in FBP_VERSION[:2])

# Final LTS runtime policy. Keep these values aligned with blender_manifest.toml.
FBP_RELEASE_CHANNEL = "LTS"
FBP_RELEASE_CHANNEL_LABEL = "7.1 LTS"
FBP_LTS_TARGET_VERSION = _FBP_LTS_TARGET_VERSION
FBP_BLENDER_VERSION_MIN = (5, 2, 0)
FBP_BLENDER_VERSION_MIN_STRING = ".".join(str(part) for part in FBP_BLENDER_VERSION_MIN)
FBP_BLENDER_VERSION_SERIES = (5, 2)
FBP_BLENDER_VERSION_SERIES_STRING = "5.2 LTS"
FBP_BLENDER_VERSION_MAX_EXCLUSIVE = (5, 3, 0)
FBP_SUPPORTED_PLATFORM_IDS = _FBP_LTS_PLATFORM_IDS
FBP_SUPPORTED_PLATFORM_LABEL = _FBP_LTS_PLATFORM_LABEL
FBP_STRICT_RUNTIME_SCOPE = True

# Core scope being stabilized for the 7.1 LTS target. Preview features remain available only
# behind their explicit opt-in and are not part of the LTS stability promise.
FBP_LTS_CORE_SCOPE = _FBP_LTS_CORE_SCOPE
FBP_LTS_PREVIEW_SCOPE = _FBP_LTS_PREVIEW_SCOPE

# Public release metadata. Keep this key aligned with the manifest so the
# one-time What's New state and visible version string cannot drift apart.
FBP_FEEDBACK_RELEASE = FBP_VERSION_STRING
FBP_PUBLIC_VERSION_STRING = FBP_VERSION_STRING
FBP_RELEASE_SUMMARY = (
    "Frame By Plane 7.1 LTS: Grease Pencil, Scrub Slider, masks, effects and a refined UI for Blender 5.2 LTS."
)

# Principal layer blend modes shared by RNA properties, operators and UI.
# ``short`` is intentionally compact so every layer can expose a Procreate-style
# badge without pushing long names or the fixed action strip out of alignment.
FBP_LAYER_BLEND_MODE_DEFINITIONS = (
    {"id": "NORMAL", "label": "Normal", "short": "N", "description": "Disable Layer Blend and show the layer normally", "icon": "DOT", "section": "Normal"},
    {"id": "MULTIPLY", "label": "Multiply", "short": "M", "description": "Multiply this layer with the image layer below", "icon": "REMOVE", "section": "Darken"},
    {"id": "DARKEN", "label": "Darken", "short": "D", "description": "Keep the darker channel values", "icon": "HIDE_ON", "section": "Darken"},
    {"id": "COLOR_BURN", "label": "Color Burn", "short": "CB", "description": "Darken the base using the current layer", "icon": "REMOVE", "section": "Darken"},
    {"id": "SCREEN", "label": "Screen", "short": "S", "description": "Screen blend against the image layer below", "icon": "ADD", "section": "Lighten"},
    {"id": "LIGHTEN", "label": "Lighten", "short": "L", "description": "Keep the lighter channel values", "icon": "HIDE_OFF", "section": "Lighten"},
    {"id": "COLOR_DODGE", "label": "Color Dodge", "short": "CD", "description": "Brighten the base using the current layer", "icon": "ADD", "section": "Lighten"},
    {"id": "ADD", "label": "Add / Linear Dodge", "short": "A", "description": "Add the current layer to the base", "icon": "ADD", "section": "Lighten"},
    {"id": "OVERLAY", "label": "Overlay", "short": "O", "description": "Overlay blend against the image layer below", "icon": "NODE_MATERIAL", "section": "Contrast"},
    {"id": "SOFT_LIGHT", "label": "Soft Light", "short": "SL", "description": "Soft Light blend against the image layer below", "icon": "LIGHT_SUN", "section": "Contrast"},
    {"id": "HARD_LIGHT", "label": "Hard Light", "short": "HL", "description": "Hard Light blend against the image layer below", "icon": "LIGHT_SUN", "section": "Contrast"},
    {"id": "LINEAR_LIGHT", "label": "Linear Light", "short": "LL", "description": "Apply Linear Light against the layer below", "icon": "LIGHT_SUN", "section": "Contrast"},
    {"id": "DIFFERENCE", "label": "Difference", "short": "Di", "description": "Use the absolute difference between layers", "icon": "SELECT_DIFFERENCE", "section": "Comparison"},
    {"id": "EXCLUSION", "label": "Exclusion", "short": "Ex", "description": "Apply a softer, lower-contrast Difference blend", "icon": "PROP_CON", "section": "Comparison"},
    {"id": "SUBTRACT", "label": "Subtract", "short": "Su", "description": "Subtract the current layer from the base", "icon": "REMOVE", "section": "Comparison"},
    {"id": "DIVIDE", "label": "Divide", "short": "Dv", "description": "Divide the base by the current layer", "icon": "MODIFIER", "section": "Comparison"},
    {"id": "HUE", "label": "Hue", "short": "H", "description": "Use current-layer hue with base saturation and luminance", "icon": "COLOR", "section": "Color"},
    {"id": "SATURATION", "label": "Saturation", "short": "Sa", "description": "Use current-layer saturation with base hue and luminance", "icon": "COLOR", "section": "Color"},
    {"id": "COLOR", "label": "Color", "short": "C", "description": "Use current-layer hue and saturation with base luminance", "icon": "COLOR", "section": "Color"},
    {"id": "LUMINOSITY", "label": "Luminosity", "short": "Lu", "description": "Use current-layer luminance with base hue and saturation", "icon": "COLOR", "section": "Color"},
)

FBP_LAYER_BLEND_MODE_BY_ID = {item["id"]: item for item in FBP_LAYER_BLEND_MODE_DEFINITIONS}
FBP_LAYER_BLEND_MODE_ITEMS = tuple(
    (item["id"], item["label"], item["description"])
    for item in FBP_LAYER_BLEND_MODE_DEFINITIONS
    if item["id"] != "NORMAL"
)
FBP_LAYER_BLEND_MENU_ITEMS = tuple(
    (item["id"], item["label"], item["description"])
    for item in FBP_LAYER_BLEND_MODE_DEFINITIONS
)

def fbp_layer_blend_definition(mode):
    return FBP_LAYER_BLEND_MODE_BY_ID.get(str(mode or "NORMAL").upper(), FBP_LAYER_BLEND_MODE_BY_ID["NORMAL"])

def fbp_layer_blend_short(mode):
    return str(fbp_layer_blend_definition(mode).get("short", "N") or "N")

def fbp_layer_blend_label(mode):
    return str(fbp_layer_blend_definition(mode).get("label", "Normal") or "Normal")


_FBP_LAYER_BLEND_MODE_COLUMNS = None

def fbp_layer_blend_mode_columns():
    """Group blend definitions into compact horizontal menu columns.

    The result is static for a running build, so cache it instead of rebuilding
    the same nested tuple on every layer-list/menu redraw.
    """
    global _FBP_LAYER_BLEND_MODE_COLUMNS
    if _FBP_LAYER_BLEND_MODE_COLUMNS is not None:
        return _FBP_LAYER_BLEND_MODE_COLUMNS
    columns = []
    current_section = None
    for definition in FBP_LAYER_BLEND_MODE_DEFINITIONS:
        section = str(definition.get("section", "") or "")
        if section != current_section:
            columns.append([])
            current_section = section
        columns[-1].append(definition)
    if len(columns) > 1 and len(columns[0]) == 1:
        columns[1] = columns[0] + columns[1]
        columns.pop(0)
    _FBP_LAYER_BLEND_MODE_COLUMNS = tuple(tuple(column) for column in columns if column)
    return _FBP_LAYER_BLEND_MODE_COLUMNS


# ICON REGISTRY #
#################
# Edit icon values here to change them everywhere in Frame by Plane.
# IMPORTANT: this dictionary must use raw Blender icon strings only.
# Do not call fbp_icon() inside FBP_ICONS, because fbp_icon is defined after this dictionary.
# Keep the dictionary keys stable; change only the Blender icon string on the right.
FBP_ICONS = {
    'ADD': 'ADD',
    'EVENT_PLUS': 'EVENT_PLUS',  # Create/add new rig panel.  # Add/create buttons (Layers side tools, Multiplane Setup, image insert).
    'ALIASED': 'ALIASED',  # Pixel interpolation enum icon.
    'ANTIALIASED': 'ANTIALIASED',  # Smooth interpolation enum icon.
    'ARROW_LEFTRIGHT': 'ARROW_LEFTRIGHT',  # Reverse, mirror and horizontal flip commands.
    'SELECT_DIFFERENCE': 'SELECT_DIFFERENCE',  # Invert masks, selections and image values.
    'INVERT': 'SELECT_DIFFERENCE',  # Semantic alias for every Invert action.
    'AXIS_FRONT': 'AXIS_FRONT',  # Vertical orientation enum icon.
    'AXIS_TOP': 'AXIS_TOP',  # Horizontal orientation enum icon.
    'BACK': 'BACK',  # Return from generated timing to the editable source drawing.
    'BLANK1': 'BLANK1',  # Tree indentation and placeholders.
    'CHECKBOX_DEHLT': 'CHECKBOX_DEHLT',  # Unchecked rig/layer selection checkbox.
    'CHECKBOX_HLT': 'CHECKBOX_HLT',  # Checked rig/layer selection checkbox.
    'CHECKMARK': 'CHECKMARK',  # Apply/health/check actions.
    'CLIPUV_DEHLT': 'CLIPUV_DEHLT',  # Inactive clipping/mask state.
    'CLIPUV_HLT': 'CLIPUV_HLT',  # Active clipping/mask state.
    'COLLECTION_NEW': 'COLLECTION_NEW',  # Create a new collection/group.
    'COLOR': 'COLOR',  # Gradient/ColorRamp UI and gradient plane type.
    'COLORSET_20_VEC': 'COLORSET_20_VEC',  # Black color preset icon.
    'CURVE_DATA': 'CURVE_DATA',  # Curve motion and path-related release notes.
    'CON_CAMERASOLVER': 'CON_CAMERASOLVER',  # Track camera toggle.
    'DOT': 'DOT',  # Inactive frame marker.
    'DOWNARROW_HLT': 'DOWNARROW_HLT',  # Expanded thin disclosure arrow.
    'DUPLICATE': 'DUPLICATE',  # Duplicate layer/frame actions.
    'EMPTY_ARROWS': 'EMPTY_ARROWS',  # Gradient transform controls.
    'ERROR': 'ERROR',  # Missing files / error warnings.
    'EYEDROPPER': 'EYEDROPPER',  # Set start frame from current frame.
    'FILE_FOLDER': 'FILE_FOLDER',  # Folders/open path/empty frame indicators.
    'FILE': 'FILE',  # Layered-document import.
    'FILE_IMAGE': 'FILE_IMAGE',  # Image import/frame count indicators.
    'FILE_MOVIE': 'FILE_MOVIE',  # Video/movie import and creation.
    'FILE_REFRESH': 'FILE_REFRESH',  # Refresh, rebuild and reset actions.
    'REFRESH': 'FILE_REFRESH',  # Semantic refresh/reset alias.
    'RECOVER_LAST': 'RECOVER_LAST',  # Repair/recovery action.
    'FILE_TICK': 'FILE_TICK',  # Save project action.
    'FOLDER_REDIRECT': 'FOLDER_REDIRECT',  # Replace/link image sequence actions.
    'FORWARD': 'FORWARD',  # One-shot playback enum.
    'FULLSCREEN_ENTER': 'FULLSCREEN_ENTER',  # Fit to camera / extend actions.
    'GHOST_DISABLED': 'GHOST_DISABLED',  # Holdout plane / holdout-off icon.
    'GRID': 'GRID',  # To Ground transform action.
    'HIDE_OFF': 'HIDE_OFF',  # Visible layer/collection state.
    'HIDE_ON': 'HIDE_ON',  # Hidden layer/collection state.
    'IMAGE_ALPHA': 'IMAGE_ALPHA',  # White/Black color plane and alpha plane type.
    'IMAGE_BACKGROUND': 'IMAGE_BACKGROUND',  # Sequence panel and selected layer name row.
    'KEYFRAME': 'KEYFRAME',  # Grease Pencil timing and generated-keyframe release notes.
    'IMAGE': 'IMAGE_DATA',  # User-facing Color Plane icon mapped to stable Blender IMAGE_DATA.
    'IMAGE_DATA': 'IMAGE_DATA',  # Image plane/menu/import icon.
    'IMAGE_PLANE': 'IMAGE_PLANE',  # Clipboard single-plane menu icon.
    'IMAGE_RGB': 'IMAGE_RGB',  # Smooth filter enum icon.
    'IMPORT': 'IMPORT',  # Import project/setup actions.
    'INFO': 'INFO',  # Native information icon for hints, status rows and empty states.
    'LAYER_USED': 'LAYER_USED',  # Locked layer selection checkbox replacement.
    'LIGHT': 'LIGHT',  # Solo/Bulb disabled state.
    'LIGHT_SUN': 'LIGHT_SUN',  # Shadeless/Emission toggle icon.
    'LINK_BLEND': 'LINK_BLEND',  # Split selected frames to a new plane.
    'LINKED': 'LINKED',  # Relink missing images action.
    'LOCKED': 'LOCKED',  # Locked state for rigs/collections.
    'MATERIAL': 'MATERIAL',  # Material/color plane panels.
    'MESH_PLANE': 'MESH_PLANE',  # Plane creation menu icon.
    'MESH_DATA': 'MESH_DATA',  # Generic mesh/cutout fallback.
    'MESH_MONKEY': 'MESH_MONKEY',  # Feedback and community section icon.
    'MODIFIER': 'MODIFIER',  # Plane tools/repair actions.
    'MOD_EXPLODE': 'MOD_EXPLODE',  # Split/explode sequence action.
    'MOD_MASK': 'MOD_MASK',  # Imported/clipping mask status.
    'MOD_SCATTER_ON_SURFACE': 'MOD_SCATTER_ON_SURFACE',  # Mesh Effects category.
    'NODE_MATERIAL': 'NODE_MATERIAL',  # Layer blend and shader-material status.
    'NODETREE': 'NODETREE',  # User-defined node effects.
    'MOD_DISPLACE': 'MOD_DISPLACE',
    'MOD_WAVE': 'MOD_WAVE',
    'MOD_SCREW': 'MOD_SCREW',
    'IPO_EASE_IN_OUT': 'IPO_EASE_IN_OUT',
    'FORCE_VORTEX': 'FORCE_VORTEX',
    'MOD_SIMPLEDEFORM': 'MOD_SIMPLEDEFORM',
    'MOD_SOLIDIFY': 'MOD_SOLIDIFY',
    'SHADING_RENDERED': 'SHADING_RENDERED',
    'SOLO_ON': 'SOLO_ON',  # Review/support primary action icon.
    'RNDCURVE': 'RNDCURVE',
    'FORCE_WIND': 'FORCE_WIND',
    'PARTICLES': 'PARTICLES',
    'WORLD': 'WORLD',
    'MESH_GRID': 'MESH_GRID',
    'MESH_CIRCLE': 'MESH_CIRCLE',
    'MESH_CUBE': 'MESH_CUBE',
    'FONT_DATA': 'FONT_DATA',
    'BRUSH_DATA': 'BRUSH_DATA',
    'SPARKLES': 'LIGHT_SUN',  # Sparkle-style fallback available in Blender 5.2.
    'MOD_BOOLEAN': 'MOD_BOOLEAN',  # Crop tool icon.
    'NODE_TEXTURE': 'NODE_TEXTURE',  # Gradient / texture-node plane icon.  # Pending folder without files.
    'OPTIONS': 'OPTIONS',  # Create/pre-settings section icon.
    'OUTLINER': 'OUTLINER',  # Project settings tab.
    'OUTLINER_COLLECTION': 'OUTLINER_COLLECTION',
    'OUTLINER_OB_GREASEPENCIL': 'OUTLINER_OB_GREASEPENCIL',
    'GREASEPENCIL': 'GREASEPENCIL',  # Edit/rename pencil action and GP drawing tools.
    'RENAME': 'FONT_DATA',  # Blender 5.2-native text/rename semantic alias.
    'OUTPUT': 'OUTPUT',  # Collection rows, project import, collection creation.
    'OUTLINER_OB_LIGHT': 'OUTLINER_OB_LIGHT',  # Solo/Bulb enabled state.
    'OUTLINER_OB_ARMATURE': 'OUTLINER_OB_ARMATURE',  # Dedicated Cutout Plane icon.
    'PASTEDOWN': 'PASTEDOWN',  # Hex color from clipboard menu icon.
    'PIVOT_CURSOR': 'PIVOT_CURSOR',  # Camera pivot toggle.
    'PREFERENCES': 'PREFERENCES',  # Add-on preferences/settings header.
    'PROPERTIES': 'PROPERTIES',  # Blender Properties editor / Properties Panel placement.
    'AREA_DOCK': 'AREA_DOCK',  # 3D View N-Panel / docked sidebar placement.
    'MENU_PANEL': 'MENU_PANEL',  # 3D View sidebar / N-Panel placement.
    'COLLAPSEMENU': 'COLLAPSEMENU',  # Generic overflow/menu action.
    'PROP_CON': 'PROP_CON',  # Invert selection action.
    'PROP_OFF': 'PROP_OFF',  # Select none action.
    'PROP_ON': 'PROP_ON',  # Select all action.
    'RECORD_ON': 'RECORD_ON',  # Current visible frame marker.
    'RENDERLAYERS': 'RENDERLAYERS',  # Multiplane mode/setup icon.
    'RENDER_ANIMATION': 'RENDER_ANIMATION',  # Emergency/background render.
    'RENDER_RESULT': 'RENDER_RESULT',  # Layers panel and image list icon.
    'RENDER_SWAP_DIMENSIONS': 'RENDER_SWAP_DIMENSIONS',  # Horizontal/vertical plane switch.
    'RESTRICT_SELECT_OFF': 'RESTRICT_SELECT_OFF',  # Linked plane selectable/unlocked selectability.
    'RESTRICT_SELECT_ON': 'RESTRICT_SELECT_ON',  # Linked plane not selectable/locked selectability.
    'RESTRICT_VIEW_ON': 'RESTRICT_VIEW_ON',  # Camera setup section.
    'RIGHTARROW': 'RIGHTARROW',  # Collapsed thin disclosure arrow.
    'SHADERFX': 'SHADERFX',  # Effects and Image Effects categories.
    'SNAP_GRID': 'SNAP_GRID',  # Pixel/Closest filter icon.
    'SNAP_FACE': 'SNAP_FACE',  # White preset icon.
    'SORTALPHA': 'SORTALPHA',  # A-Z sort buttons.
    'SORT_ASC': 'SORT_ASC',  # Thin down arrow / move down.
    'SORT_DESC': 'SORT_DESC',  # Thin up arrow / move up.
    'STRIP_COLOR_01': 'STRIP_COLOR_01',  # Color tag enum/icon 01.
    'STRIP_COLOR_02': 'STRIP_COLOR_02',  # Color tag enum/icon 02.
    'STRIP_COLOR_03': 'STRIP_COLOR_03',  # Color tag enum/icon 03.
    'STRIP_COLOR_04': 'STRIP_COLOR_04',  # Color tag enum/icon 04.
    'STRIP_COLOR_05': 'STRIP_COLOR_05',  # Color tag enum/icon 05.
    'STRIP_COLOR_06': 'STRIP_COLOR_06',  # Color tag enum/icon 06.
    'STRIP_COLOR_07': 'STRIP_COLOR_07',  # Color tag enum/icon 07.
    'STRIP_COLOR_08': 'STRIP_COLOR_08',  # Color tag enum/icon 08.
    'STRIP_COLOR_09': 'STRIP_COLOR_09',  # Color tag enum/icon 09.
    'TEXT': 'TEXT',  # Text datablock and diagnostic report actions.
    'X': 'X',  # Close/dismiss only; deletion uses TRASH.
    'UNLINKED': 'UNLINKED',  # Detach/unlink relationship.
    'EXPORT': 'EXPORT',  # Export external files or packages.
    'TEXTURE': 'TEXTURE',  # Add a transparent logical frame.
    'TEXTURE_DATA': 'TEXTURE_DATA',  # Transparent procedural/empty frame icon.
    'TRIA_DOWN_BAR': 'TRIA_DOWN_BAR',  # Move active frame to the bottom.
    'TRIA_UP_BAR': 'TRIA_UP_BAR',  # Move active frame to the top.
    'TIME': 'TIME',  # Import/profile report icon.
    'TOOL_SETTINGS': 'TOOL_SETTINGS',  # Settings cleanup and maintenance actions.
    'URL': 'URL',  # External review/support links.
    'CANCEL': 'CANCEL',  # Dismiss/disable optional prompts.
    'PRESET': 'PRESET',  # What's New section header.
    'TRASH': 'TRASH',  # Delete/clear/remove actions.
    'UV_SYNC_SELECT': 'UV_SYNC_SELECT',  # Ping-pong playback enum.
    'UNLOCKED': 'UNLOCKED',  # Unlocked state for rigs/collections.
    'VIEW_CAMERA': 'VIEW_CAMERA',
    'CAMERA_DATA': 'CAMERA_DATA',
    'CAMERA_STEREO': 'CAMERA_STEREO',  # Existing camera icon.
    'COLLECTION_COLOR_01': 'COLLECTION_COLOR_01',  # Outliner collection color icon 01.
    'COLLECTION_COLOR_02': 'COLLECTION_COLOR_02',  # Outliner collection color icon 02.
    'COLLECTION_COLOR_03': 'COLLECTION_COLOR_03',  # Outliner collection color icon 03.
    'COLLECTION_COLOR_04': 'COLLECTION_COLOR_04',  # Outliner collection color icon 04.
    'COLLECTION_COLOR_05': 'COLLECTION_COLOR_05',  # Outliner collection color icon 05.
    'COLLECTION_COLOR_06': 'COLLECTION_COLOR_06',  # Outliner collection color icon 06.
    'COLLECTION_COLOR_07': 'COLLECTION_COLOR_07',  # Outliner collection color icon 07.
    'COLLECTION_COLOR_08': 'COLLECTION_COLOR_08',  # Outliner collection color icon 08.
}

FBP_ARTIST_COLOR_TAGS = frozenset({
    "NONE",
    "COLOR_01",
    "COLOR_02",
    "COLOR_03",
    "COLOR_04",
    "COLOR_05",
    "COLOR_06",
    "COLOR_07",
})


def fbp_normalize_artist_color_tag(color_tag):
    """Normalize internal color tags to the artist-facing palette."""
    tag = str(color_tag or "NONE").upper()
    return tag if tag in FBP_ARTIST_COLOR_TAGS else "NONE"


def fbp_shared_artist_color_tag(values):
    """Return one shared artist color, or ``NONE`` for empty/mixed values."""
    tags = {fbp_normalize_artist_color_tag(value) for value in tuple(values or ())}
    return next(iter(tags)) if len(tags) == 1 else "NONE"


def fbp_icon(name, fallback="BLANK1"):
    """Return a centralized Blender icon name used by Frame by Plane UI."""
    return FBP_ICONS.get(name, FBP_ICONS.get(fallback, fallback))

def fbp_strip_icon(color_tag, fallback="STRIP_COLOR_09"):
    """Return a centralized strip color icon for layer color tags.

    ``NONE`` is a real artist-facing state: it means “use the default plane
    icon”. Brown/Grey are kept only as internal fallbacks,
    not as artist-facing dropdown items.
    """
    tag = str(color_tag or "NONE").upper()
    if tag == "NONE":
        return fbp_icon("IMAGE_DATA")
    key = f"STRIP_{tag}" if tag.startswith("COLOR_") else str(fallback)
    return fbp_icon(key, fallback)

def fbp_collection_color_icon(color_tag):
    """Return a centralized collection color icon, or the generic collection icon."""
    tag = str(color_tag or "")
    if tag.startswith("COLOR_"):
        suffix = tag.split("_")[-1]
        key = f"COLLECTION_COLOR_{suffix}"
        if key in FBP_ICONS:
            return fbp_icon(key)
    return fbp_icon("OUTLINER_COLLECTION")


STRIP_COLORS_DICT = {
    'COLOR_01': (0.8, 0.1, 0.1, 1.0),
    'COLOR_02': (0.9, 0.4, 0.1, 1.0),
    'COLOR_03': (0.8, 0.8, 0.1, 1.0),
    'COLOR_04': (0.2, 0.8, 0.2, 1.0),
    'COLOR_05': (0.1, 0.6, 0.8, 1.0),
    'COLOR_06': (0.4, 0.2, 0.8, 1.0),
    'COLOR_07': (0.8, 0.2, 0.5, 1.0),
    'COLOR_08': (0.4, 0.2, 0.1, 1.0),
    'COLOR_09': (0.5, 0.5, 0.5, 1.0),
}

COLOR_ENUM_ITEMS = [
    ('NONE', "None / Default", "Use the default plane icon without a color tag", fbp_icon('STRIP_COLOR_09'), 0),
    ('COLOR_01', "Red",     "", fbp_icon('STRIP_COLOR_01'), 1),
    ('COLOR_02', "Orange",  "", fbp_icon('STRIP_COLOR_02'), 2),
    ('COLOR_03', "Yellow",  "", fbp_icon('STRIP_COLOR_03'), 3),
    ('COLOR_04', "Green",   "", fbp_icon('STRIP_COLOR_04'), 4),
    ('COLOR_05', "Cyan",    "", fbp_icon('STRIP_COLOR_05'), 5),
    ('COLOR_06', "Purple",  "", fbp_icon('STRIP_COLOR_06'), 6),
    ('COLOR_07', "Magenta", "", fbp_icon('STRIP_COLOR_07'), 7),
]

COLLECTION_COLOR_ENUM_ITEMS = [
    ('NONE', "None", "Do not assign a color tag to this collection", fbp_icon('OUTLINER_COLLECTION'), 0),
    ('COLOR_01', "Color 01", "Collection color 01", fbp_icon('COLLECTION_COLOR_01'), 1),
    ('COLOR_02', "Color 02", "Collection color 02", fbp_icon('COLLECTION_COLOR_02'), 2),
    ('COLOR_03', "Color 03", "Collection color 03", fbp_icon('COLLECTION_COLOR_03'), 3),
    ('COLOR_04', "Color 04", "Collection color 04", fbp_icon('COLLECTION_COLOR_04'), 4),
    ('COLOR_05', "Color 05", "Collection color 05", fbp_icon('COLLECTION_COLOR_05'), 5),
    ('COLOR_06', "Color 06", "Collection color 06", fbp_icon('COLLECTION_COLOR_06'), 6),
    ('COLOR_07', "Color 07", "Collection color 07", fbp_icon('COLLECTION_COLOR_07'), 7),
]

preview_collections = {}
FBP_SUPPORTED_IMAGE_EXT = frozenset(_FBP_LTS_SOURCE_FORMATS["images"])
FBP_SUPPORTED_VIDEO_EXT = frozenset(_FBP_LTS_SOURCE_FORMATS["videos"])
FBP_SUPPORTED_MEDIA_EXT = FBP_SUPPORTED_IMAGE_EXT | FBP_SUPPORTED_VIDEO_EXT

FBP_TECHNICAL_MAP_SUFFIXES = (
    '_normal', '_norm', '_nrm', '_displace', '_disp', '_height',
    '_spec', '_specular', '_roughness', '_rough', '_metallic', '_metalness',
    '_ao', '_ambientocclusion', '_bump'
)

FBP_PROJECT_COLLECTION_PREFIX = 'FBP - '
