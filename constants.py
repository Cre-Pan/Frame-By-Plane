"""Shared constants for Frame by Plane.

This module is intentionally Blender-light: it avoids bpy imports so it can be
tested and refactored independently.
"""

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
    'MODIFIER': 'MODIFIER',  # Plane tools/repair actions. ### DUPLICATE
    'MOD_BOOLEAN': 'MOD_BOOLEAN',  # Crop tool icon. ### DUPLICATE
    'NODE_TEXTURE': 'NODE_TEXTURE',  # Gradient / texture-node plane icon.  # Pending folder without files.
    'OPTIONS': 'OPTIONS',  # Create/pre-settings section icon. ### DUPLICATE
    'OUTLINER': 'OUTLINER',  # Project settings tab.
    'OUTLINER_COLLECTION': 'OUTLINER_COLLECTION',
    'OUTPUT': 'OUTPUT',  # Collection rows, project import, collection creation. ### DUPLICATE
    'OUTLINER_OB_LIGHT': 'OUTLINER_OB_LIGHT',  # Solo/Bulb enabled state. ### DUPLICATE
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
    'TEXTURE': 'TEXTURE',  # Add a transparent logical frame.
    'TEXTURE_DATA': 'TEXTURE_DATA',  # Transparent procedural/empty frame icon.
    'TRIA_DOWN_BAR': 'TRIA_DOWN_BAR',  # Move active frame to the bottom.
    'TRIA_UP_BAR': 'TRIA_UP_BAR',  # Move active frame to the top.
    'TIME': 'TIME',  # Import/profile report icon. ### DUPLICATE
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

