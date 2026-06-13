"""Frame by Plane - UI icon aliases.

This module is intentionally tiny and Blender-light.
Edit this file when you want to change the visual style of panels, buttons,
menus and UI rows without touching operators or scene logic.

Values on the right are keys from constants.FBP_ICONS, not raw Blender icon
strings. If you need a brand-new icon, add it first to constants.py > FBP_ICONS.
"""

try:
    from .constants import fbp_icon
except ImportError:
    from constants import fbp_icon


# SECTION 01 - Panel Settings / Project / Render #
# ### ICON Panel Settings, Function Header
# ### ICON Panel Settings, Function Project Folder
# ### ICON Panel Settings, Function Import Project
# ### ICON Panel Settings, Function Build Direct
# ### ICON Panel Settings, Function Background Render

# SECTION 02 - Panel Layer Stack #
# ### ICON Panel Layer Stack, Function Header
# ### ICON Panel Layer Stack, Function Solo
# ### ICON Panel Layer Stack, Function Select
# ### ICON Panel Layer Stack, Function Holdout
# ### ICON Panel Layer Stack, Function Visibility
# ### ICON Panel Layer Stack, Function Lock

# SECTION 03 - Panel Sequence / Selected Layer #
# ### ICON Panel Sequence, Function Header
# ### ICON Panel Sequence, Function Current Frame
# ### ICON Panel Sequence, Function Normal Frame
# ### ICON Panel Sequence, Function Missing File
# ### ICON Panel Sequence, Function Empty/Transparent Frame

# SECTION 04 - Panel Create / Multiplane Setup #
# ### ICON Panel Create, Function Header
# ### ICON Panel Create, Function Color Plane
# ### ICON Panel Create, Function Single Plane
# ### ICON Panel Create, Function Multiplane
# ### ICON Panel Multiplane Setup, Function Collection
# ### ICON Panel Multiplane Setup, Function Collapse
# ### ICON Panel Multiplane Setup, Function Add/Remove

# SECTION 05 - Menu #
# ### ICON Menu Shift+A, Function Color Plane
# ### ICON Menu Shift+A, Function Gradient Plane
# ### ICON Menu Shift+A, Function Holdout Plane
# ### ICON Menu Shift+A, Function Single Image Plane
# ### ICON Menu Shift+A, Function Multiplane
# ### ICON Menu Render, Function Background Render

FBP_UI_ICON_KEYS = {
    # Settings / Project / Render
    "settings.header": "PREFERENCES",
    "settings.project_folder": "FILE_FOLDER",
    "settings.import_project": "IMPORT",
    "settings.build_direct": "OUTLINER_COLLECTION",
    "settings.relink": "LINKED",
    "settings.missing": "ERROR",
    "settings.health": "CHECKMARK",
    "settings.profile": "TIME",
    "settings.render": "RENDER_ANIMATION",
    "settings.repair": "MODIFIER",
    "settings.output": "SCENE_DATA",
    "settings.save": "FILE_TICK",
    "settings.stats": "INFO",

    # Layer Stack
    "layer.header": "RENDER_RESULT",
    "layer.color_tag_fallback": "STRIP_COLOR_09",
    "layer.solo_on": "OUTLINER_OB_LIGHT",
    "layer.solo_off": "LIGHT",
    "layer.select_on": "CHECKBOX_HLT",
    "layer.select_off": "CHECKBOX_DEHLT",
    "layer.visible_on": "HIDE_OFF",
    "layer.visible_off": "HIDE_ON",
    "layer.lock_on": "LOCKED",
    "layer.lock_off": "UNLOCKED",
    "layer.sort_alpha": "SORTALPHA",
    "layer.move_down": "SORT_DESC",
    "layer.move_up": "SORT_ASC",
    "layer.add": "ADD",
    "layer.add_color": "IMAGE",
    "layer.duplicate": "DUPLICATE",
    "layer.delete": "TRASH",
    "layer.select_all": "RESTRICT_SELECT_OFF",

    # Sequence / Selected Layer
    "sequence.header": "IMAGE_BACKGROUND",
    "sequence.current_frame": "RECORD_ON",
    "sequence.normal_frame": "DOT",
    "sequence.missing_file": "ERROR",
    "sequence.empty_frame": "TEXTURE_DATA",
    "sequence.image": "IMAGE_DATA",
    "sequence.replace": "FOLDER_REDIRECT",
    "sequence.emission": "LIGHT_SUN",
    "sequence.camera_track": "CON_CAMERASOLVER",
    "sequence.fit": "FULLSCREEN_ENTER",
    "sequence.transform": "EMPTY_ARROWS",
    "sequence.tools": "MODIFIER",
    "sequence.edges": "MOD_BOOLEAN",
    "sequence.frames": "RENDER_RESULT",
    "sequence.add_image": "IMAGE",
    "sequence.add_empty": "TEXTURE_DATA",
    "sequence.import_frame": "FILE_FOLDER",
    "sequence.split": "AREA_DOCK",
    "sequence.remove": "PANEL_CLOSE",
    "sequence.apply": "CHECKMARK",
    "sequence.set_current": "EYEDROPPER",
    "sequence.reverse": "ARROW_LEFTRIGHT",
    "sequence.node_texture": "NODE_TEXTURE",
    "sequence.select_all": "PROP_ON",
    "sequence.select_none": "PROP_OFF",
    "sequence.select_invert": "PROP_CON",

    # Create / Setup
    "create.header": "EVENT_PLUS",
    "create.settings": "OPTIONS",
    "create.camera": "RESTRICT_VIEW_ON",
    "create.camera_new": "VIEW_CAMERA",
    "create.camera_existing": "CAMERA_DATA",
    "create.color_plane": "MATERIAL",
    "create.single_plane": "IMAGE_DATA",
    "create.multiplane": "RENDERLAYERS",
    "create.generate_color": "IMAGE",
    "create.generate_single": "FILE_IMAGE",
    "create.generate_multi": "RENDERLAYERS",
    "setup.collection": "OUTLINER_COLLECTION",
    "setup.collection_new": "OUTLINER_COLLECTION",
    "setup.collapsed": "RIGHTARROW",
    "setup.expanded": "DOWNARROW_HLT",
    "setup.add": "ADD",
    "setup.remove": "REMOVE",
    "setup.delete": "TRASH",
    "setup.file_count": "FILE_IMAGE",
    "setup.edit": "FOLDER_REDIRECT",
    "setup.folder_empty": "NEWFOLDER",
    "setup.folder_files": "FOLDER_REDIRECT",
    "setup.folder": "FILE_FOLDER",
    "setup.scene": "SCENE_DATA",
    "setup.sequence": "FILE_IMAGE",
    "setup.animated": "RENDERLAYERS",
    "setup.image": "IMAGE_DATA",
    "setup.info": "INFO",

    # Menus
    "menu.color_plane": "IMAGE",
    "menu.gradient_plane": "COLOR",
    "menu.holdout_plane": "GHOST_DISABLED",
    "menu.image_plane": "IMAGE_DATA",
    "menu.multiplane": "RENDER_RESULT",
    "menu.hex": "PASTEDOWN",
    "menu.clipboard": "IMAGE_PLANE",
    "menu.shift_a_root": "RENDERLAYERS",
    "menu.context_holdout": "GHOST_DISABLED",
    "menu.context_delete": "TRASH",
    "menu.context_merge": "DUPLICATE",
    "menu.render_background": "RENDER_ANIMATION",

    # Generic
    "generic.blank": "BLANK1",
    "generic.grip_v": "GRIP_V",
    "generic.info": "INFO",
    "generic.error": "ERROR",
    "generic.add": "ADD",
    "generic.remove": "REMOVE",
    "generic.delete": "TRASH",
    "generic.down": "SORT_DESC",
    "generic.up": "SORT_ASC",
}


def ui_icon(key, fallback="generic.blank"):
    """Return a Blender icon string from a readable UI alias."""
    icon_key = FBP_UI_ICON_KEYS.get(key)
    if icon_key is None:
        icon_key = FBP_UI_ICON_KEYS.get(fallback, "BLANK1")
    return fbp_icon(icon_key)
