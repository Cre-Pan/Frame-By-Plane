"""Shared constants for Frame by Plane.

This module is intentionally Blender-light: it avoids bpy imports so it can be
tested and refactored independently.
"""

# Release metadata lives here so the add-on header, preferences and local
# What's New UI cannot silently drift apart during incremental releases.
FBP_VERSION = (6, 1, 0)
FBP_VERSION_STRING = ".".join(str(part) for part in FBP_VERSION)
FBP_VERSION_FAMILY = ".".join(str(part) for part in FBP_VERSION[:2])
# Public 6.1 LTS release metadata. Keep the semantic version numeric in the
# manifest and expose the LTS designation only in user-facing text.
FBP_PUBLIC_VERSION_STRING = "6.1 LTS"
FBP_RELEASE_SUMMARY = "Frame By Plane 6.1.0 LTS: stable native workflow, autonomous release tests and lighter platform packages"

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
    {"id": "DIFFERENCE", "label": "Difference", "short": "Di", "description": "Use the absolute difference between layers", "icon": "ARROW_LEFTRIGHT", "section": "Comparison"},
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


def fbp_layer_blend_mode_columns():
    """Group blend definitions into compact horizontal menu columns.

    The single Normal entry is merged into Darken so it does not waste an
    entire column. Registry order remains the source of truth everywhere.
    """
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
    return tuple(tuple(column) for column in columns if column)


# ICON REGISTRY #
#################
# Edit icon values here to change them everywhere in Frame by Plane.
# IMPORTANT: this dictionary must use raw Blender icon strings only.
# Do not call fbp_icon() inside FBP_ICONS, because fbp_icon is defined after this dictionary.
# Keep the dictionary keys stable; change only the Blender icon string on the right.
# Lines marked ### DUPLICATE intentionally reuse the same Blender icon in multiple UI contexts.
FBP_ICONS = {
    'ADD': 'ADD',
    'EVENT_PLUS': 'EVENT_PLUS',  # Create/add new rig panel.  # Add/create buttons (Layers side tools, Multiplane Setup, image insert). ### DUPLICATE
    'ALIASED': 'ALIASED',  # Pixel interpolation enum icon.
    'ANTIALIASED': 'ANTIALIASED',  # Smooth interpolation enum icon.
    'ARROW_LEFTRIGHT': 'ARROW_LEFTRIGHT',  # Reverse sequence command. ### DUPLICATE
    'AXIS_FRONT': 'AXIS_FRONT',  # Vertical orientation enum icon.
    'AXIS_TOP': 'AXIS_TOP',  # Horizontal orientation enum icon.
    'BLANK1': 'BLANK1',  # Tree indentation and placeholders. ### DUPLICATE
    'CHECKBOX_DEHLT': 'CHECKBOX_DEHLT',  # Unchecked rig/layer selection checkbox.
    'CHECKBOX_HLT': 'CHECKBOX_HLT',  # Checked rig/layer selection checkbox. ### DUPLICATE
    'CHECKMARK': 'CHECKMARK',  # Apply/health/check actions. ### DUPLICATE
    'CLIPUV_DEHLT': 'CLIPUV_DEHLT',  # Mask/Holdout enabled icon.
    'COLOR': 'COLOR',  # Gradient/ColorRamp UI and gradient plane type. ### DUPLICATE
    'COLORSET_20_VEC': 'COLORSET_20_VEC',  # Black color preset icon.
    'CON_CAMERASOLVER': 'CON_CAMERASOLVER',  # Track camera toggle. ### DUPLICATE
    'DOT': 'DOT',  # Inactive frame marker. ### DUPLICATE
    'DOWNARROW_HLT': 'DOWNARROW_HLT',  # Expanded thin disclosure arrow. ### DUPLICATE
    'DUPLICATE': 'DUPLICATE',  # Duplicate layer/frame actions. ### DUPLICATE
    'EMPTY_ARROWS': 'EMPTY_ARROWS',  # Gradient transform controls. ### DUPLICATE
    'ERROR': 'ERROR',  # Missing files / error warnings. ### DUPLICATE
    'EYEDROPPER': 'EYEDROPPER',  # Set start frame from current frame. ### DUPLICATE
    'FILE_FOLDER': 'FILE_FOLDER',  # Folders/open path/empty frame indicators. ### DUPLICATE
    'FILE_IMAGE': 'FILE_IMAGE',  # Image import/frame count indicators. ### DUPLICATE
    'FILE_REFRESH': 'FILE_REFRESH',  # Loop playback / rotate toggle. ### DUPLICATE
    'FILE_TICK': 'FILE_TICK',  # Save project action. ### DUPLICATE
    'FOLDER_REDIRECT': 'FOLDER_REDIRECT',  # Replace/link image sequence actions. ### DUPLICATE
    'FORWARD': 'FORWARD',  # One-shot playback enum. ### DUPLICATE
    'FULLSCREEN_ENTER': 'FULLSCREEN_ENTER',  # Fit to camera / extend actions. ### DUPLICATE
    'GHOST_DISABLED': 'GHOST_DISABLED',  # Holdout plane / holdout-off icon. ### DUPLICATE
    'GRID': 'GRID',  # To Ground transform action. ### DUPLICATE
    'HIDE_OFF': 'HIDE_OFF',  # Visible layer/collection state. ### DUPLICATE
    'HIDE_ON': 'HIDE_ON',  # Hidden layer/collection state. ### DUPLICATE
    'IMAGE_ALPHA': 'IMAGE_ALPHA',  # White/Black color plane and alpha plane type. ### DUPLICATE
    'IMAGE_BACKGROUND': 'IMAGE_BACKGROUND',  # Sequence panel and selected layer name row. ### DUPLICATE
    'IMAGE': 'IMAGE_DATA',  # User-facing Color Plane icon mapped to stable Blender IMAGE_DATA.
    'IMAGE_DATA': 'IMAGE_DATA',  # Image plane/menu/import icon. ### DUPLICATE
    'IMAGE_PLANE': 'IMAGE_PLANE',  # Clipboard single-plane menu icon. ### DUPLICATE
    'IMAGE_RGB': 'IMAGE_RGB',  # Smooth filter enum icon.
    'IMPORT': 'IMPORT',  # Import project/setup actions. ### DUPLICATE
    'INFO': 'INFO',  # Info/help/status rows. ### DUPLICATE
    'LAYER_USED': 'LAYER_USED',  # Locked layer selection checkbox replacement. ### DUPLICATE
    'LIGHT': 'LIGHT',  # Solo/Bulb disabled state.
    'LIGHT_SUN': 'LIGHT_SUN',  # Shadeless/Emission toggle icon. ### DUPLICATE
    'LINK_BLEND': 'LINK_BLEND',  # Split selected frames to a new plane.
    'LINKED': 'LINKED',  # Relink missing images action. ### DUPLICATE
    'LOCKED': 'LOCKED',  # Locked state for rigs/collections. ### DUPLICATE
    'MATERIAL': 'MATERIAL',  # Material/color plane panels. ### DUPLICATE
    'MESH_PLANE': 'MESH_PLANE',  # Plane creation menu icon. ### DUPLICATE
    'MESH_MONKEY': 'MESH_MONKEY',  # Feedback and community section icon.
    'MODIFIER': 'MODIFIER',  # Plane tools/repair actions. ### DUPLICATE
    'MOD_MASK': 'MOD_MASK',  # Imported/clipping mask status.
    'NODE_MATERIAL': 'NODE_MATERIAL',  # Layer blend and shader-material status.
    'NODETREE': 'NODETREE',  # User-defined node effects.
    'MOD_DISPLACE': 'MOD_DISPLACE',
    'MOD_WAVE': 'MOD_WAVE',
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
    'SPARKLES': 'LIGHT_SUN',  # Sparkle-style fallback available in Blender 5.1.2.
    'MOD_BOOLEAN': 'MOD_BOOLEAN',  # Crop tool icon. ### DUPLICATE
    'NODE_TEXTURE': 'NODE_TEXTURE',  # Gradient / texture-node plane icon.  # Pending folder without files.
    'OPTIONS': 'OPTIONS',  # Create/pre-settings section icon. ### DUPLICATE
    'OUTLINER': 'OUTLINER',  # Project settings tab.
    'OUTLINER_COLLECTION': 'OUTLINER_COLLECTION',
    'OUTPUT': 'OUTPUT',  # Collection rows, project import, collection creation. ### DUPLICATE
    'OUTLINER_OB_LIGHT': 'OUTLINER_OB_LIGHT',  # Solo/Bulb enabled state. ### DUPLICATE
    'OUTLINER_OB_ARMATURE': 'OUTLINER_OB_ARMATURE',  # Dedicated Cutout Plane icon.
    'PASTEDOWN': 'PASTEDOWN',  # Hex color from clipboard menu icon. ### DUPLICATE
    'PIVOT_CURSOR': 'PIVOT_CURSOR',  # Camera pivot toggle. ### DUPLICATE
    'PREFERENCES': 'PREFERENCES',  # Settings panel header. ### DUPLICATE
    'PROP_CON': 'PROP_CON',  # Invert selection action. ### DUPLICATE
    'PROP_OFF': 'PROP_OFF',  # Select none action. ### DUPLICATE
    'PROP_ON': 'PROP_ON',  # Select all action. ### DUPLICATE
    'RECORD_ON': 'RECORD_ON',  # Current visible frame marker. ### DUPLICATE
    'RENDERLAYERS': 'RENDERLAYERS',  # Multiplane mode/setup icon. ### DUPLICATE
    'RENDER_ANIMATION': 'RENDER_ANIMATION',  # Emergency/background render. ### DUPLICATE
    'RENDER_RESULT': 'RENDER_RESULT',  # Layers panel and image list icon. ### DUPLICATE
    'RESTRICT_SELECT_OFF': 'RESTRICT_SELECT_OFF',  # Linked plane selectable/unlocked selectability. ### DUPLICATE
    'RESTRICT_SELECT_ON': 'RESTRICT_SELECT_ON',  # Linked plane not selectable/locked selectability. ### DUPLICATE
    'RESTRICT_VIEW_ON': 'RESTRICT_VIEW_ON',  # Camera setup section. ### DUPLICATE
    'RIGHTARROW': 'RIGHTARROW',  # Collapsed thin disclosure arrow. ### DUPLICATE
    'SNAP_GRID': 'SNAP_GRID',  # Pixel/Closest filter icon.
    'SNAP_FACE': 'SNAP_FACE',  # White preset icon.
    'SORTALPHA': 'SORTALPHA',  # A-Z sort buttons. ### DUPLICATE
    'SORT_ASC': 'SORT_ASC',  # Thin down arrow / move down. ### DUPLICATE
    'SORT_DESC': 'SORT_DESC',  # Thin up arrow / move up. ### DUPLICATE
    'STRIP_': 'STRIP_',  # Dynamic strip color prefix for layer color tags. ### DUPLICATE
    'STRIP_COLOR_01': 'STRIP_COLOR_01',  # Color tag enum/icon 01. ### DUPLICATE
    'STRIP_COLOR_02': 'STRIP_COLOR_02',  # Color tag enum/icon 02. ### DUPLICATE
    'STRIP_COLOR_03': 'STRIP_COLOR_03',  # Color tag enum/icon 03. ### DUPLICATE
    'STRIP_COLOR_04': 'STRIP_COLOR_04',  # Color tag enum/icon 04. ### DUPLICATE
    'STRIP_COLOR_05': 'STRIP_COLOR_05',  # Color tag enum/icon 05. ### DUPLICATE
    'STRIP_COLOR_06': 'STRIP_COLOR_06',  # Color tag enum/icon 06. ### DUPLICATE
    'STRIP_COLOR_07': 'STRIP_COLOR_07',  # Color tag enum/icon 07. ### DUPLICATE
    'STRIP_COLOR_08': 'STRIP_COLOR_08',  # Color tag enum/icon 08. ### DUPLICATE
    'STRIP_COLOR_09': 'STRIP_COLOR_09',  # Color tag enum/icon 09. ### DUPLICATE
    'TEXT': 'TEXT',  # Text datablock and diagnostic report actions.
    'TEXTURE': 'TEXTURE',  # Add a transparent logical frame.
    'TEXTURE_DATA': 'TEXTURE_DATA',  # Transparent procedural/empty frame icon.
    'TRIA_DOWN_BAR': 'TRIA_DOWN_BAR',  # Move active frame to the bottom.
    'TRIA_UP_BAR': 'TRIA_UP_BAR',  # Move active frame to the top.
    'TIME': 'TIME',  # Import/profile report icon. ### DUPLICATE
    'TOOL_SETTINGS': 'TOOL_SETTINGS',  # Settings cleanup and maintenance actions.
    'URL': 'URL',  # External review/support links.
    'CANCEL': 'CANCEL',  # Dismiss/disable optional prompts.
    'PRESET': 'PRESET',  # What's New section header.
    'TRASH': 'TRASH',  # Delete/clear/remove actions. ### DUPLICATE
    'UV_SYNC_SELECT': 'UV_SYNC_SELECT',  # Ping-pong playback enum. ### DUPLICATE
    'UNLOCKED': 'UNLOCKED',  # Unlocked state for rigs/collections. ### DUPLICATE
    'VIEW_CAMERA': 'VIEW_CAMERA',
    'CAMERA_DATA': 'CAMERA_DATA',
    'CAMERA_STEREO': 'CAMERA_STEREO',  # Existing camera icon.
    'COLLECTION_COLOR_01': 'COLLECTION_COLOR_01',  # Outliner collection color icon 01. ### DUPLICATE
    'COLLECTION_COLOR_02': 'COLLECTION_COLOR_02',  # Outliner collection color icon 02. ### DUPLICATE
    'COLLECTION_COLOR_03': 'COLLECTION_COLOR_03',  # Outliner collection color icon 03. ### DUPLICATE
    'COLLECTION_COLOR_04': 'COLLECTION_COLOR_04',  # Outliner collection color icon 04. ### DUPLICATE
    'COLLECTION_COLOR_05': 'COLLECTION_COLOR_05',  # Outliner collection color icon 05. ### DUPLICATE
    'COLLECTION_COLOR_06': 'COLLECTION_COLOR_06',  # Outliner collection color icon 06. ### DUPLICATE
    'COLLECTION_COLOR_07': 'COLLECTION_COLOR_07',  # Outliner collection color icon 07. ### DUPLICATE
    'COLLECTION_COLOR_08': 'COLLECTION_COLOR_08',  # Outliner collection color icon 08. ### DUPLICATE
}

def fbp_icon(name, fallback="BLANK1"):
    """Return a centralized Blender icon name used by Frame by Plane UI."""
    return FBP_ICONS.get(name, FBP_ICONS.get(fallback, fallback))

def fbp_strip_icon(color_tag, fallback="STRIP_COLOR_09"):
    """Return a centralized strip color icon for layer color tags."""
    tag = str(color_tag or "COLOR_09")
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
    ('COLOR_01', "Red",     "", fbp_icon('STRIP_COLOR_01'), 1),
    ('COLOR_02', "Orange",  "", fbp_icon('STRIP_COLOR_02'), 2),
    ('COLOR_03', "Yellow",  "", fbp_icon('STRIP_COLOR_03'), 3),
    ('COLOR_04', "Green",   "", fbp_icon('STRIP_COLOR_04'), 4),
    ('COLOR_05', "Cyan",    "", fbp_icon('STRIP_COLOR_05'), 5),
    ('COLOR_06', "Purple",  "", fbp_icon('STRIP_COLOR_06'), 6),
    ('COLOR_07', "Magenta", "", fbp_icon('STRIP_COLOR_07'), 7),
    ('COLOR_08', "Brown",   "", fbp_icon('STRIP_COLOR_08'), 8),
    ('COLOR_09', "Gray",    "", fbp_icon('STRIP_COLOR_09'), 9),
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
    ('COLOR_08', "Color 08", "Collection color 08", fbp_icon('COLLECTION_COLOR_08'), 8),
]

preview_collections = {}
FBP_SUPPORTED_IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.webp', '.exr', '.tif', '.tiff', '.bmp', '.gif', '.jp2', '.j2k', '.hdr', '.pic', '.sgi', '.rgb', '.rgba', '.dds'}
FBP_SUPPORTED_VIDEO_EXT = {'.mp4', '.mov', '.m4v', '.avi', '.mkv', '.webm', '.mpeg', '.mpg', '.mxf', '.ogv'}
FBP_SUPPORTED_MEDIA_EXT = FBP_SUPPORTED_IMAGE_EXT | FBP_SUPPORTED_VIDEO_EXT

FBP_TECHNICAL_MAP_SUFFIXES = (
    '_normal', '_norm', '_nrm', '_displace', '_disp', '_height',
    '_spec', '_specular', '_roughness', '_rough', '_metallic', '_metalness',
    '_ao', '_ambientocclusion', '_bump'
)

FBP_PROJECT_COLLECTION_PREFIX = 'FBP - '
