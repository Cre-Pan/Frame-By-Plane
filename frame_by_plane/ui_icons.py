"""Frame by Plane - UI icon aliases.

This module is intentionally tiny and Blender-light.
Edit this file when you want to change the visual style of panels, buttons,
menus and UI rows without touching operators or scene logic.

Values on the right are keys from constants.FBP_ICONS, not raw Blender icon
strings. If you need a brand-new icon, add it first to constants.py > FBP_ICONS.
"""

import os
import time

from .constants import FBP_ICONS, fbp_icon, preview_collections


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
    "settings.display": "PREFERENCES",
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
    "settings.stats": "CHECKMARK",

    # Layer Stack
    "layer.header": "RENDERLAYERS",
    "layer.color_tag_fallback": "IMAGE_DATA",
    "layer.solo_on": "OUTLINER_OB_LIGHT",
    "layer.solo_off": "LIGHT",
    "layer.select_on": "CHECKBOX_HLT",
    "layer.select_off": "CHECKBOX_DEHLT",
    "layer.visible_on": "HIDE_OFF",
    "layer.visible_off": "HIDE_ON",
    "layer.lock_on": "LOCKED",
    "layer.lock_off": "UNLOCKED",
    "layer.clipping_on": "CLIPUV_HLT",
    "layer.clipping_off": "CLIPUV_DEHLT",
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
    "sequence.add_transparent": "TEXTURE",
    "sequence.delete": "TRASH",
    "sequence.node_texture": "NODE_TEXTURE",
    "sequence.select_all": "PROP_ON",
    "sequence.select_none": "PROP_OFF",
    "sequence.select_invert": "PROP_CON",
    "sequence.optimize": "FILE_REFRESH",

    # Create / Setup
    "create.header": "EVENT_PLUS",
    "create.color_plane": "MATERIAL",
    "create.cutout_plane": "MESH_DATA",
    "setup.collection": "OUTLINER_COLLECTION",
    "setup.collection_new": "COLLECTION_NEW",
    "setup.collapsed": "RIGHTARROW",
    "setup.expanded": "DOWNARROW_HLT",
    "setup.edit": "FOLDER_REDIRECT",
    "setup.folder": "FILE_FOLDER",
    "setup.sequence": "FILE_IMAGE",
    "setup.split_sequence": "MOD_EXPLODE",
    "setup.animated": "RENDERLAYERS",
    "setup.image": "IMAGE_DATA",

    # Menus
    "menu.color_plane": "IMAGE",
    "menu.cutout_plane": "MESH_DATA",
    "menu.gradient_plane": "COLOR",
    "menu.holdout_plane": "GHOST_DISABLED",
    "menu.image_plane": "IMAGE_DATA",
    "menu.multiplane": "RENDERLAYERS",
    "menu.video_plane": "RENDER_ANIMATION",
    "menu.hex": "PASTEDOWN",
    "menu.clipboard": "IMAGE_PLANE",
    "menu.gp_layer": "OUTLINER_OB_GREASEPENCIL",
    "menu.shift_a_root": "RENDERLAYERS",

    # Semantic actions
    "action.invert": "INVERT",
    "action.rename": "RENAME",
    "action.delete": "TRASH",
    "action.close": "X",
    "action.reset": "FILE_REFRESH",
    "action.refresh": "FILE_REFRESH",
    "action.link": "LINKED",
    "action.unlink": "UNLINKED",
    "action.mask": "MOD_MASK",
    "action.export": "EXPORT",

    # Generic
    "generic.blank": "BLANK1",
    "generic.info": "INFO",
    "generic.error": "ERROR",
    "generic.add": "ADD",
    "generic.delete": "TRASH",
    "generic.menu": "COLLAPSEMENU",
    "generic.down": "SORT_ASC",
    "generic.up": "SORT_DESC",
    "generic.top": "TRIA_UP_BAR",
    "generic.bottom": "TRIA_DOWN_BAR",
}


# Custom PNG icon registry -------------------------------------------------
#
# Blender UI draw calls use either a native icon name (``icon=``) or a custom
# preview id (``icon_value=``).  Keep the two systems parallel: ``ui_icon``
# remains the safe native fallback, while the helpers below return preview ids
# only when the PNG file is present and successfully loaded by Blender.

_FBP_CUSTOM_ICON_COLLECTION = "fbp_custom_ui_icons"
_FBP_CUSTOM_ICON_DIR = os.path.join(os.path.dirname(__file__), "assets", "icons")

_FBP_CUSTOM_ICON_FILES = {
    "color_plane": "icon_color_plane.png",
    "cutout_plane": "icon_cutout_plane.png",
    "gp_layer": "icon_gp_layer.png",
    "gradient_plane": "icon_gradient_plane.png",
    "holdout_plane": "icon_holdout_plane.png",
    "image_paste": "icon_image_paste.png",
    "multi_plane": "icon_multi_plane.png",
    "single_plane": "icon_single_plane.png",
    "video_plane": "icon_video_plane.png",
    "clipping_mask_on": "icon_clipping_mask_ON.png",
    "clipping_mask_off": "icon_clipping_mask_OFF.png",
}

# Effect and mask artwork supplied for the 7.1 interface. Keys are stable
# effect identifiers, so display labels can evolve without breaking icon lookup.
_FBP_EFFECT_CUSTOM_ICON_FILES = {
    "ALPHA_MATTE": "icon_ALPHA_mask.png",
    "LUMA_MATTE": "icon_LUMA_mask.png",
    "SQUARE_MASK": "icon_SQUARE_mask.png",
    "CIRCLE_MASK": "icon_CIRCLE_mask.png",
    "TRIANGLE_MASK": "icon_TRIANGLE_mask.png",
    "CLIPPING_MASK": "icon_MASK.png",
    "IMPORTED_MASK": "icon_IMPORTED_mask.png",
    "GP_MASK_SLOT_2": "icon_GREASEPENCIL_mask.png",
    "GP_MASK_SLOT_3": "icon_GREASEPENCIL_mask.png",
    "GP_MASK_SLOT_4": "icon_GREASEPENCIL_mask.png",
    "COLOR_MASK": "icon_COLOR_mask.png",
    "LUMINANCE_MASK": "icon_LUMINANCE_mask.png",
    "CHANNEL_MASK": "icon_CHANNEL_mask.png",
    "GRADIENT_MASK": "icon_GRADIENT_mask.png",
    "NOISE_MASK": "icon_NOISE_mask.png",
    "VORONOI_MASK": "icon_VORONOI_mask.png",
    "WAVE_MASK": "icon_WAVE_mask.png",
    # Viewport Pie / quick-slot pseudo identifiers.
    "GREASE_PENCIL_MASK": "icon_GREASEPENCIL_mask.png",
    "SHAPE_MASK": "icon_SQUARE_mask.png",
}
for _effect_id, _filename in _FBP_EFFECT_CUSTOM_ICON_FILES.items():
    _FBP_CUSTOM_ICON_FILES[f"effect:{_effect_id}"] = _filename
_FBP_CUSTOM_ICON_FILES["floating_timeline"] = "icon_FLOATINGTIMELINE_paste.png"

_FBP_CUSTOM_ICON_UI_KEYS = {
    "settings.scrub_slider": "floating_timeline",
    "menu.color_plane": "color_plane",
    "menu.cutout_plane": "cutout_plane",
    "menu.gradient_plane": "gradient_plane",
    "menu.holdout_plane": "holdout_plane",
    "menu.image_plane": "single_plane",
    "menu.multiplane": "multi_plane",
    "menu.video_plane": "video_plane",
    "menu.clipboard": "image_paste",
    "menu.gp_layer": "gp_layer",
    "layer.clipping_on": "clipping_mask_on",
    "layer.clipping_off": "clipping_mask_off",
    "create.color_plane": "color_plane",
    "setup.image": "single_plane",
    "setup.sequence": "single_plane",
    "setup.animated": "multi_plane",
}

_FBP_LAYER_BACKEND_ICON_BASE = {
    "NATIVE_IMAGE": "single_plane",
    "NATIVE_SEQUENCE": "single_plane",
    "NATIVE_MOVIE": "video_plane",
    "CUTOUT": "cutout_plane",
    "PROCEDURAL_COLOR": "color_plane",
    "PROCEDURAL_GRADIENT": "gradient_plane",
    "PROCEDURAL_HOLDOUT": "holdout_plane",
    "GP_CANVAS": "gp_layer",
}

_FBP_COLOR_TAG_SUFFIX = {
    "COLOR_01": "R",  # Red
    "COLOR_02": "O",  # Orange
    "COLOR_03": "Y",  # Yellow
    "COLOR_04": "G",  # Green
    "COLOR_05": "C",  # Cyan
    "COLOR_06": "P",  # Purple
    "COLOR_07": "M",  # Magenta
    # Brown and Gray are not artist-facing color tags. Internal values fall back
    # to the neutral base icon instead of inventing missing artwork.
}

_FBP_CUSTOM_ICON_VALUE_CACHE = globals().get("_FBP_CUSTOM_ICON_VALUE_CACHE", {})
if not isinstance(_FBP_CUSTOM_ICON_VALUE_CACHE, dict):
    _FBP_CUSTOM_ICON_VALUE_CACHE = {}
_FBP_CUSTOM_ICON_PATH_ALIASES = globals().get("_FBP_CUSTOM_ICON_PATH_ALIASES", {})
if not isinstance(_FBP_CUSTOM_ICON_PATH_ALIASES, dict):
    _FBP_CUSTOM_ICON_PATH_ALIASES = {}
_FBP_CUSTOM_ICON_CANONICAL_KEYS = globals().get("_FBP_CUSTOM_ICON_CANONICAL_KEYS", {})
if not isinstance(_FBP_CUSTOM_ICON_CANONICAL_KEYS, dict):
    _FBP_CUSTOM_ICON_CANONICAL_KEYS = {}
_FBP_CUSTOM_ICON_PATH_EXISTS = globals().get("_FBP_CUSTOM_ICON_PATH_EXISTS", {})
if not isinstance(_FBP_CUSTOM_ICON_PATH_EXISTS, dict):
    _FBP_CUSTOM_ICON_PATH_EXISTS = {}
_FBP_CUSTOM_ICON_GENERATION = int(globals().get("_FBP_CUSTOM_ICON_GENERATION", 0) or 0)
_FBP_ICON_METRIC_DEFAULTS = {
    "requests": 0,
    "cache_hits": 0,
    "cache_misses": 0,
    "filesystem_checks": 0,
    "preview_loads": 0,
    "path_alias_hits": 0,
    "load_failures": 0,
    "load_total_ms": 0.0,
    "preload_total_ms": 0.0,
}
_FBP_ICON_METRICS = globals().get("_FBP_ICON_METRICS", {})
if not isinstance(_FBP_ICON_METRICS, dict):
    _FBP_ICON_METRICS = {}
for _metric_key, _metric_default in _FBP_ICON_METRIC_DEFAULTS.items():
    _FBP_ICON_METRICS.setdefault(_metric_key, _metric_default)


def custom_icon_metrics(*, reset=False):
    result = dict(_FBP_ICON_METRICS)
    result.update({
        "logical_cache_entries": len(_FBP_CUSTOM_ICON_VALUE_CACHE),
        "preview_collection_entries": 0,
    })
    pcoll = preview_collections.get(_FBP_CUSTOM_ICON_COLLECTION)
    try:
        result["preview_collection_entries"] = len(pcoll) if pcoll is not None else 0
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    if reset:
        _FBP_ICON_METRICS.clear()
        _FBP_ICON_METRICS.update(_FBP_ICON_METRIC_DEFAULTS)
    return result


def clear_custom_icon_cache():
    """Forget cached custom icon ids and advance the preview generation."""
    global _FBP_CUSTOM_ICON_GENERATION
    _FBP_CUSTOM_ICON_VALUE_CACHE.clear()
    _FBP_CUSTOM_ICON_PATH_ALIASES.clear()
    _FBP_CUSTOM_ICON_CANONICAL_KEYS.clear()
    _FBP_CUSTOM_ICON_PATH_EXISTS.clear()
    _FBP_CUSTOM_ICON_GENERATION += 1
    return True


def custom_icon_generation():
    """Return a monotonic token for caches that store preview icon ids."""
    return int(_FBP_CUSTOM_ICON_GENERATION)


def _fbp_custom_icon_collection():
    """Return the preview collection used by Frame By Plane PNG icons."""
    pcoll = preview_collections.get(_FBP_CUSTOM_ICON_COLLECTION)
    if pcoll is not None:
        return pcoll
    try:
        import bpy.utils.previews
        pcoll = bpy.utils.previews.new()
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        return None
    preview_collections[_FBP_CUSTOM_ICON_COLLECTION] = pcoll
    return pcoll


def _fbp_custom_icon_path(custom_key):
    filename = _FBP_CUSTOM_ICON_FILES.get(str(custom_key or ""))
    if not filename:
        return ""
    return os.path.join(_FBP_CUSTOM_ICON_DIR, filename)


def _fbp_normalized_icon_path(custom_key):
    path = _fbp_custom_icon_path(custom_key)
    return os.path.normcase(os.path.abspath(path)) if path else ""


def _fbp_existing_icon_path(custom_key):
    path = _fbp_normalized_icon_path(custom_key)
    if not path:
        return ""
    exists = _FBP_CUSTOM_ICON_PATH_EXISTS.get(path)
    if exists is None:
        _FBP_ICON_METRICS["filesystem_checks"] += 1
        exists = bool(os.path.isfile(path))
        _FBP_CUSTOM_ICON_PATH_EXISTS[path] = exists
    return path if exists else ""


def custom_icon_path_for_ui_key(key):
    """Return the existing custom PNG path behind a readable UI icon alias.

    Pixel overlays such as the live tutorial cannot consume Blender preview
    ``icon_value`` ids directly. Exposing the registry path keeps them on the
    same artwork as menus and UILists without duplicating filename maps.
    """
    custom_key = _FBP_CUSTOM_ICON_UI_KEYS.get(str(key or ""), "")
    return _fbp_existing_icon_path(custom_key)


def custom_icon_value(custom_key):
    """Return a Blender ``icon_value`` for a custom PNG icon, or 0.

    The loader is lazy and cached. Missing files stay cheap: a negative cache
    stores ``0`` so UI redraws do not touch the filesystem repeatedly.
    """
    custom_key = str(custom_key or "")
    if not custom_key:
        return 0
    _FBP_ICON_METRICS["requests"] += 1
    cached = _FBP_CUSTOM_ICON_VALUE_CACHE.get(custom_key)
    if cached is not None:
        _FBP_ICON_METRICS["cache_hits"] += 1
        # File > Revert / Load can invalidate Blender preview icon ids without
        # re-importing this module. Never return a stale positive id unless the
        # matching preview still exists in the live collection.
        if not int(cached or 0):
            return 0
        pcoll = preview_collections.get(_FBP_CUSTOM_ICON_COLLECTION)
        preview_key = _FBP_CUSTOM_ICON_PATH_ALIASES.get(custom_key, custom_key)
        try:
            if pcoll is not None and preview_key in pcoll:
                live_id = int(getattr(pcoll[preview_key], "icon_id", 0) or 0)
                if live_id:
                    _FBP_CUSTOM_ICON_VALUE_CACHE[custom_key] = live_id
                    return live_id
        except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
            pass
        _FBP_CUSTOM_ICON_VALUE_CACHE.pop(custom_key, None)
    _FBP_ICON_METRICS["cache_misses"] += 1
    path = _fbp_existing_icon_path(custom_key)
    if not path:
        _FBP_CUSTOM_ICON_VALUE_CACHE[custom_key] = 0
        return 0
    pcoll = _fbp_custom_icon_collection()
    if pcoll is None:
        _FBP_CUSTOM_ICON_VALUE_CACHE[custom_key] = 0
        return 0
    canonical_key = _FBP_CUSTOM_ICON_CANONICAL_KEYS.get(path, "")
    if canonical_key:
        try:
            value = int(getattr(pcoll[canonical_key], "icon_id", 0) or 0)
        except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
            value = 0
        if value:
            _FBP_CUSTOM_ICON_PATH_ALIASES[custom_key] = canonical_key
            _FBP_CUSTOM_ICON_VALUE_CACHE[custom_key] = value
            _FBP_ICON_METRICS["path_alias_hits"] += 1
            return value
        _FBP_CUSTOM_ICON_CANONICAL_KEYS.pop(path, None)

    canonical_key = custom_key
    try:
        load_started = time.perf_counter()
        if canonical_key not in pcoll:
            pcoll.load(canonical_key, path, 'IMAGE')
            _FBP_ICON_METRICS["preview_loads"] += 1
        value = int(getattr(pcoll[canonical_key], "icon_id", 0) or 0)
    except Exception:
        _FBP_ICON_METRICS["load_failures"] += 1
        value = 0
    finally:
        _FBP_ICON_METRICS["load_total_ms"] += max(
            0.0, (time.perf_counter() - load_started) * 1000.0
        )
    _FBP_CUSTOM_ICON_VALUE_CACHE[custom_key] = value
    if value:
        _FBP_CUSTOM_ICON_CANONICAL_KEYS[path] = canonical_key
        _FBP_CUSTOM_ICON_PATH_ALIASES[custom_key] = canonical_key
    return value


def ui_icon_value(key):
    """Return a custom preview id for a readable UI alias, or 0."""
    return custom_icon_value(_FBP_CUSTOM_ICON_UI_KEYS.get(str(key or ""), ""))


def effect_custom_icon_value(effect_id):
    """Return the custom 7.1 icon for an effect or mask identifier, or 0."""
    effect_id = str(effect_id or "").upper()
    if effect_id not in _FBP_EFFECT_CUSTOM_ICON_FILES:
        return 0
    return custom_icon_value(f"effect:{effect_id}")


def effect_icon_kwargs(effect_id, fallback="MODIFIER"):
    """Return layout kwargs using custom mask artwork when available."""
    value = effect_custom_icon_value(effect_id)
    if value:
        return {"icon_value": value}
    fallback = str(fallback or "MODIFIER")
    return {"icon": fbp_icon(fallback)}


def effect_enum_icon(effect_id, fallback="MODIFIER"):
    """Return an EnumProperty-compatible custom icon id or native icon name."""
    value = effect_custom_icon_value(effect_id)
    return value if value else fbp_icon(str(fallback or "MODIFIER"))


def floating_timeline_icon_kwargs(fallback="ACTION"):
    """Return the supplied Scrub Slider icon with a native fallback."""
    value = custom_icon_value("floating_timeline")
    return {"icon_value": value} if value else {"icon": fbp_icon(fallback)}


def _ui_icon_kwargs(key, fallback):
    value = ui_icon_value(key)
    if value:
        return {"icon_value": value}
    return {"icon": ui_icon(key, fallback=fallback)}


def ui_label_icon_kwargs(key, fallback="generic.blank"):
    """Return kwargs for ``layout.label`` using PNG icon when available."""
    return _ui_icon_kwargs(key, fallback)


def ui_icon_kwargs(key, fallback="generic.blank"):
    """Return kwargs for ``layout.operator`` using PNG icon when available.

    Example:
        layout.operator("fbp.popup_single_plane", text="Single Plane", **ui_icon_kwargs("menu.image_plane"))
    """
    return _ui_icon_kwargs(key, fallback)


def clipping_mask_icon_kwargs(active=False):
    """Return icon kwargs for a Clipping Mask toggle operator/label."""
    key = "layer.clipping_on" if bool(active) else "layer.clipping_off"
    value = ui_icon_value(key)
    if value:
        return {"icon_value": value}
    return {"icon": ui_icon(key)}


def layer_custom_icon_value(backend, color_tag="", inactive=False):
    """Return a custom Layer List icon for plane backend + color tag.

    ``inactive`` uses the dedicated *_OFF icon supplied by the user. Fallback
    Brown/Gray values deliberately fall back to the neutral base icon because
    those variants are not part of the artist-facing artwork set.
    """
    base = _FBP_LAYER_BACKEND_ICON_BASE.get(str(backend or "").upper(), "single_plane")
    if inactive:
        key = f"{base}_OFF"
        filename = f"icon_{base}_OFF.png"
    else:
        suffix = _FBP_COLOR_TAG_SUFFIX.get(str(color_tag or "").upper(), "")
        key = f"{base}_{suffix}" if suffix else base
        filename = f"icon_{base}_{suffix}.png" if suffix else f"icon_{base}.png"
    if key not in _FBP_CUSTOM_ICON_FILES:
        _FBP_CUSTOM_ICON_FILES[key] = filename
    return custom_icon_value(key)


def register_custom_icons():
    """Preload the most visible custom icons.

    Lazy loading still covers every variant. Preloading only the Shift+A icons
    keeps add-on registration light while making the Add menu immediate.
    """
    # Revert File / Load can retire native preview ids while leaving this Python
    # module alive. Always rebuild positive ids from the active preview collection.
    preload_started = time.perf_counter()
    clear_custom_icon_cache()
    for key in (
        "single_plane", "multi_plane", "cutout_plane", "gp_layer",
        "color_plane", "gradient_plane", "holdout_plane", "image_paste",
        "video_plane", "clipping_mask_on", "clipping_mask_off",
        "floating_timeline",
    ):
        custom_icon_value(key)
    _FBP_ICON_METRICS["preload_total_ms"] = max(
        0.0, (time.perf_counter() - preload_started) * 1000.0
    )
    return True


def unregister_custom_icons():
    """Release custom preview icons during add-on unregister/reload."""
    pcoll = preview_collections.pop(_FBP_CUSTOM_ICON_COLLECTION, None)
    if pcoll is not None:
        try:
            import bpy.utils.previews
            bpy.utils.previews.remove(pcoll)
        except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
            pass
    clear_custom_icon_cache()
    return True


def reload_custom_icons_after_file_load():
    """Recreate PNG preview ids after Blender replaces Main data.

    ``File > Revert`` keeps add-on Python modules alive but can invalidate custom
    preview ids.  A full release/reload pair is cheap for this small icon set and
    prevents dashed/missing icons in Shift+A menus and layer rows.
    """
    unregister_custom_icons()
    clear_ui_icon_cache()
    register_custom_icons()
    return True


_FBP_UI_ICON_CACHE = globals().get("_FBP_UI_ICON_CACHE", {})
if not isinstance(_FBP_UI_ICON_CACHE, dict):
    _FBP_UI_ICON_CACHE = {}


def _registered_icon_key(token):
    token = token if isinstance(token, str) else str(token or "")
    alias = FBP_UI_ICON_KEYS.get(token)
    if alias is not None:
        return alias
    # Some call sites use a centralized raw FBP key in compact status rows.
    if token in FBP_ICONS:
        return token
    return None


def ui_icon(key, fallback="generic.blank"):
    """Return a Blender icon string from a readable UI alias.

    UI draw code calls this hundreds of times while the Layer List and effect
    stack repaint. The common default-fallback path now avoids tuple allocation
    and repeated fallback normalization; custom fallbacks still use a distinct
    cache key for correctness.
    """
    key = key if isinstance(key, str) else str(key or "")

    if fallback == "generic.blank":
        cache_key = key
        cached = _FBP_UI_ICON_CACHE.get(cache_key)
        if cached is not None:
            return cached
        icon_key = _registered_icon_key(key) or "BLANK1"
    else:
        fallback = fallback if isinstance(fallback, str) else str(fallback or "generic.blank")
        cache_key = (key, fallback)
        cached = _FBP_UI_ICON_CACHE.get(cache_key)
        if cached is not None:
            return cached
        icon_key = _registered_icon_key(key)
        if icon_key is None:
            icon_key = _registered_icon_key(fallback) or "BLANK1"
    resolved = fbp_icon(icon_key)
    if len(_FBP_UI_ICON_CACHE) >= 512 and cache_key not in _FBP_UI_ICON_CACHE:
        _FBP_UI_ICON_CACHE.clear()
    _FBP_UI_ICON_CACHE[cache_key] = resolved
    return resolved


def clear_ui_icon_cache():
    _FBP_UI_ICON_CACHE.clear()
    return True
