"""Frame by Plane - UI icon aliases.

This module is intentionally tiny and Blender-light.
Edit this file when you want to change the visual style of panels, buttons,
menus and UI rows without touching operators or scene logic.

Values on the right are keys from constants.FBP_ICONS, not raw Blender icon
strings. If you need a brand-new icon, add it first to constants.py > FBP_ICONS.
"""

from .constants import fbp_icon


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
    "settings.project": "OUTLINER",
    "settings.camera_tab": "CAMERA_DATA",
    "settings.projection": "CAMERA_STEREO",
    "settings.camera_frame": "IMAGE_BACKGROUND",
    "settings.project_folder": "FILE_FOLDER",
    "settings.relink": "LINKED",
    "settings.health": "CHECKMARK",
    "settings.render": "RENDER_ANIMATION",
    "settings.render_tab": "RENDER_ANIMATION",
    "settings.render_sequence": "RENDER_RESULT",
    "settings.repair": "MODIFIER",
    "settings.output": "OUTPUT",
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
    "layer.duplicate": "DUPLICATE",
    "layer.select_all": "RESTRICT_SELECT_OFF",

    # Sequence / Selected Layer
    "sequence.header": "IMAGE_BACKGROUND",
    "sequence.current_frame": "RECORD_ON",
    "sequence.normal_frame": "DOT",
    "sequence.empty_frame": "TEXTURE_DATA",
    "sequence.replace": "FOLDER_REDIRECT",
    "sequence.emission": "LIGHT_SUN",
    "sequence.camera_track": "CON_CAMERASOLVER",
    "sequence.fit": "FULLSCREEN_ENTER",
    "sequence.transform": "EMPTY_ARROWS",
    "sequence.tools": "MODIFIER",
    "sequence.edges": "MOD_BOOLEAN",
    "sequence.frames": "RENDER_RESULT",
    "sequence.split": "LINK_BLEND",
    "sequence.set_current": "EYEDROPPER",
    "sequence.reverse": "ARROW_LEFTRIGHT",
    "sequence.move_top": "TRIA_UP_BAR",
    "sequence.move_up": "SORT_DESC",
    "sequence.move_down": "SORT_ASC",
    "sequence.move_bottom": "TRIA_DOWN_BAR",
    "sequence.duplicate": "DUPLICATE",
    "sequence.reverse_selected": "ARROW_LEFTRIGHT",
    "sequence.add_transparent": "TEXTURE",
    "sequence.delete": "TRASH",
    "sequence.node_texture": "NODE_TEXTURE",
    "sequence.select_all": "PROP_ON",
    "sequence.select_none": "PROP_OFF",
    "sequence.select_invert": "PROP_CON",

    # Create / Setup
    "create.header": "EVENT_PLUS",
    "create.color_plane": "MATERIAL",
    "setup.collection": "OUTLINER_COLLECTION",
    "setup.collection_new": "OUTLINER_COLLECTION",
    "setup.collapsed": "RIGHTARROW",
    "setup.expanded": "DOWNARROW_HLT",
    "setup.edit": "FOLDER_REDIRECT",
    "setup.folder": "FILE_FOLDER",
    "setup.sequence": "FILE_IMAGE",
    "setup.animated": "RENDERLAYERS",
    "setup.image": "IMAGE_DATA",

    # Menus
    "menu.color_plane": "IMAGE",
    "menu.gradient_plane": "COLOR",
    "menu.holdout_plane": "GHOST_DISABLED",
    "menu.image_plane": "IMAGE_DATA",
    "menu.multiplane": "RENDER_RESULT",
    "menu.hex": "PASTEDOWN",
    "menu.clipboard": "IMAGE_PLANE",
    "menu.shift_a_root": "RENDERLAYERS",

    # Generic
    "generic.blank": "BLANK1",
    "generic.info": "INFO",
    "generic.error": "ERROR",
    "generic.add": "ADD",
    "generic.delete": "TRASH",
    "generic.down": "SORT_ASC",
    "generic.up": "SORT_DESC",
}


def ui_icon(key, fallback="generic.blank"):
    """Return a Blender icon string from a readable UI alias."""
    icon_key = FBP_UI_ICON_KEYS.get(key)
    if icon_key is None:
        icon_key = FBP_UI_ICON_KEYS.get(fallback, "BLANK1")
    return fbp_icon(icon_key)
