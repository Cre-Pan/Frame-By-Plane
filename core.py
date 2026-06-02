bl_info = {
    "name": "Frame by Plane",
    "author": "Alessandro Pannoli",
    "version": (2, 3, 10),
    "blender": (5, 1, 0),
    "location": "View3D > Sidebar > Frame by Plane",
    "description": "Import image sequences as controllable animation planes with folders, fast import, scene split and profiling.",
    "category": "Animation",
}

import bpy
import os
import subprocess
import tempfile
import math
import mathutils
import time
import re
import bpy.utils.previews
from bpy.props import (
    StringProperty, IntProperty, BoolProperty, FloatProperty, FloatVectorProperty,
    CollectionProperty, PointerProperty, EnumProperty
)
from bpy.types import PropertyGroup, Operator, Panel, UIList, Menu

try:
    from . import profiling as fbp_profiling
except Exception:
    import profiling as fbp_profiling



try:
    from .constants import (
        STRIP_COLORS_DICT,
        COLOR_ENUM_ITEMS,
        preview_collections,
        FBP_SUPPORTED_IMAGE_EXT,
        FBP_TECHNICAL_MAP_SUFFIXES,
        FBP_PROJECT_COLLECTION_PREFIX,
        FBP_SUPPORT_EMAIL,
    )
    from .path_utils import (
        natural_sort_key,
        is_supported_image_file,
        is_hidden_import_name,
        is_technical_map_file,
        clean_layer_name_from_path,
        ensure_folder,
    )
except Exception:
    from constants import (
        STRIP_COLORS_DICT,
        COLOR_ENUM_ITEMS,
        preview_collections,
        FBP_SUPPORTED_IMAGE_EXT,
        FBP_TECHNICAL_MAP_SUFFIXES,
        FBP_PROJECT_COLLECTION_PREFIX,
        FBP_SUPPORT_EMAIL,
    )
    from path_utils import (
        natural_sort_key,
        is_supported_image_file,
        is_hidden_import_name,
        is_technical_map_file,
        clean_layer_name_from_path,
        ensure_folder,
    )


# ICON REGISTRY IMPORT FALLBACK #
#################################
# Keep icon access safe even when testing core.py against an older constants.py.
# In the full add-on package, these functions are provided by constants.py.
try:
    from . import constants as _fbp_constants
except Exception:
    try:
        import constants as _fbp_constants
    except Exception:
        _fbp_constants = None

FBP_ICONS = getattr(_fbp_constants, "FBP_ICONS", {}) if _fbp_constants else {}


def fbp_icon(name, fallback="BLANK1"):
    """Return a Blender icon string from the centralized registry.

    Edit constants.py > FBP_ICONS to change icons globally. This local fallback
    prevents NameError when only core.py is replaced during live testing.
    """
    icon_func = getattr(_fbp_constants, "fbp_icon", None) if _fbp_constants else None
    if callable(icon_func):
        try:
            return icon_func(name, fallback)
        except Exception:
            pass
    return FBP_ICONS.get(name, FBP_ICONS.get(fallback, name if name else fallback))


def fbp_strip_icon(color_tag, fallback="STRIP_COLOR_09"):
    """Return the strip icon for a Frame by Plane color tag."""
    strip_func = getattr(_fbp_constants, "fbp_strip_icon", None) if _fbp_constants else None
    if callable(strip_func):
        try:
            return strip_func(color_tag, fallback)
        except Exception:
            pass
    tag = str(color_tag or "COLOR_09")
    return f"STRIP_{tag}" if tag.startswith("COLOR_") else fallback


def fbp_collection_color_icon(color_tag, fallback="OUTLINER_COLLECTION"):
    """Return the colored collection icon for a Blender collection color tag."""
    collection_func = getattr(_fbp_constants, "fbp_collection_color_icon", None) if _fbp_constants else None
    if callable(collection_func):
        try:
            return collection_func(color_tag, fallback)
        except Exception:
            pass
    tag = str(color_tag or "")
    if tag.startswith("COLOR_"):
        suffix = tag.split("_")[-1]
        if suffix in {"01", "02", "03", "04", "05", "06", "07", "08"}:
            return f"COLLECTION_COLOR_{suffix}"
    return fallback

def fbp_log(message, level="INFO", exc=None):
    """Small addon logger used instead of silently swallowing unexpected errors."""
    try:
        suffix = f": {exc}" if exc else ""
        print(f"[FBP {level}] {message}{suffix}")
    except Exception:
        pass


def fbp_warn(message, exc=None):
    fbp_log(message, "Warning", exc)


def fbp_runtime_wm(context=None):
    return getattr(context, "window_manager", None) if context else getattr(bpy.context, "window_manager", None)


def fbp_runtime_get(key, default=None, context=None):
    wm = fbp_runtime_wm(context)
    if not wm:
        return default
    try:
        return wm.get(key, default)
    except Exception:
        return default


def fbp_runtime_set(key, value, context=None):
    wm = fbp_runtime_wm(context)
    if not wm:
        return False
    try:
        wm[key] = value
        return True
    except Exception as exc:
        fbp_warn(f"Could not store runtime state {key}", exc)
        return False


# ICON REGISTRY NOTE #
######################
# All Frame by Plane UI icons are centralized in constants.py under # ICON REGISTRY #.
# Use fbp_icon("ICON_KEY") or fbp_strip_icon(color_tag) instead of hard-coded icon strings.


# ── HELPERS ──────────────────────────────────────────────────────────────────

def is_fbp_gp_object(obj):
    return False


def is_fbp_image_rig(obj):
    return bool(obj and getattr(obj, 'is_fbp_control', False))


def is_fbp_layer_object(obj):
    return is_fbp_image_rig(obj)


def fbp_layer_type_label(obj):
    return 'IMG' if is_fbp_image_rig(obj) else ''


def safe_collection_color_tag(collection, fallback='COLOR_09'):
    try:
        tag = getattr(collection, 'color_tag', fallback)
        return tag if tag in STRIP_COLORS_DICT else fallback
    except Exception:
        return fallback


def set_collection_color_tag(collection, color_tag):
    if not collection or color_tag not in STRIP_COLORS_DICT:
        return
    try:
        collection.color_tag = color_tag
    except Exception:
        pass


def make_color_variant(color_tag, index=0):
    base = STRIP_COLORS_DICT.get(color_tag, STRIP_COLORS_DICT['COLOR_09'])
    # Micro-variazioni leggere: mantengono il gruppo cromatico ma rendono i rig più leggibili.
    offsets = (-0.10, -0.05, 0.0, 0.06, 0.12, -0.02, 0.09)
    delta = offsets[index % len(offsets)]
    r, g, b, a = base
    if index % 3 == 0:
        r += delta
    elif index % 3 == 1:
        g += delta
    else:
        b += delta
    # Piccola compensazione di luminosità.
    lum = 1.0 + (delta * 0.35)
    return (
        max(0.0, min(1.0, r * lum)),
        max(0.0, min(1.0, g * lum)),
        max(0.0, min(1.0, b * lum)),
        a,
    )


def get_or_create_child_collection(parent_collection, name, color_tag=None):
    parent_collection = parent_collection or bpy.context.scene.collection
    for child in parent_collection.children:
        if child.name == name:
            coll = child
            break
    else:
        coll = bpy.data.collections.new(name)
        parent_collection.children.link(coll)
    try:
        coll.is_fbp_collection = True
    except Exception:
        pass
    if color_tag:
        set_collection_color_tag(coll, color_tag)
    return coll


def move_object_to_collection(obj, collection):
    if not obj or not collection:
        return
    try:
        if obj.name not in collection.objects:
            collection.objects.link(obj)
    except Exception:
        try:
            collection.objects.link(obj)
        except Exception:
            pass
    for coll in list(obj.users_collection):
        if coll != collection:
            try:
                coll.objects.unlink(obj)
            except Exception:
                pass


def get_primary_fbp_collection(obj):
    if not obj:
        return None
    try:
        if getattr(obj, 'fbp_collection_name', ''):
            coll = bpy.data.collections.get(obj.fbp_collection_name)
            if coll:
                return coll
    except Exception:
        pass
    try:
        for coll in obj.users_collection:
            if getattr(coll, 'is_fbp_collection', False):
                return coll
        return obj.users_collection[0] if obj.users_collection else None
    except Exception:
        return None


def is_layer_item_visible_in_collections(context, item):
    try:
        rig = item.obj
    except ReferenceError:
        return False
    if not rig or not is_fbp_layer_object(rig):
        return False
    try:
        # visible_get recepisce hide/exclude delle Collections nel View Layer.
        return bool(rig.visible_get(view_layer=context.view_layer))
    except TypeError:
        try:
            return bool(rig.visible_get())
        except Exception:
            return object_in_scene(rig, context.scene)
    except Exception:
        return object_in_scene(rig, context.scene)


def visible_layer_indices(context, same_collection_as=None):
    indices = []
    target_collection = get_primary_fbp_collection(same_collection_as) if same_collection_as else None
    for i, item in enumerate(context.scene.fbp_layers):
        try:
            rig = item.obj
            if not rig or not is_fbp_layer_object(rig):
                continue
            if target_collection and get_primary_fbp_collection(rig) != target_collection:
                continue
            if is_layer_item_visible_in_collections(context, item):
                indices.append(i)
        except ReferenceError:
            pass
    return indices


def apply_collection_color_to_layer(obj, color_tag=None, variant_index=None, push_collection=False):
    if not obj or not is_fbp_layer_object(obj):
        return
    coll = get_primary_fbp_collection(obj)
    if color_tag is None and coll:
        color_tag = safe_collection_color_tag(coll, getattr(obj, 'fbp_color_tag', 'COLOR_09'))
    if color_tag not in STRIP_COLORS_DICT:
        color_tag = getattr(obj, 'fbp_color_tag', 'COLOR_09')
        if color_tag not in STRIP_COLORS_DICT:
            color_tag = 'COLOR_09'
    if getattr(obj, 'fbp_color_tag', None) != color_tag:
        obj.fbp_color_tag = color_tag
    if variant_index is None:
        variant_index = getattr(obj, 'fbp_color_variant_index', 0)
    obj.color = make_color_variant(color_tag, variant_index)
    plane = getattr(obj, 'fbp_plane_target', None)
    if plane:
        try:
            plane.color = obj.color
        except Exception:
            pass
    if push_collection and coll:
        set_collection_color_tag(coll, color_tag)


def apply_collection_color_to_rig(rig, color_tag=None, variant_index=None, push_collection=False):
    apply_collection_color_to_layer(rig, color_tag, variant_index, push_collection)


def sync_collection_colors_to_rigs(context):
    if not context:
        return
    counters = {}
    for item in context.scene.fbp_layers:
        try:
            rig = item.obj
            if not rig or not is_fbp_layer_object(rig):
                continue
            if not getattr(rig, 'fbp_follow_collection_color', True):
                continue
            coll = get_primary_fbp_collection(rig)
            if not coll:
                continue
            tag = safe_collection_color_tag(coll, None)
            if tag not in STRIP_COLORS_DICT:
                continue
            key = coll.name
            idx = counters.get(key, 0)
            counters[key] = idx + 1
            rig.fbp_color_variant_index = idx
            apply_collection_color_to_layer(rig, tag, idx, push_collection=False)
        except ReferenceError:
            pass




# ── COLLECTION TREE / PROJECT HELPERS ───────────────────────────────────────

def find_layer_collection(layer_collection, collection):
    """Return the ViewLayer LayerCollection wrapper for a bpy.data Collection."""
    if not layer_collection or not collection:
        return None
    try:
        if layer_collection.collection == collection:
            return layer_collection
    except Exception:
        pass
    for child in getattr(layer_collection, 'children', []):
        found = find_layer_collection(child, collection)
        if found:
            return found
    return None


def collection_is_hidden_in_view_layer(context, collection):
    if not collection:
        return False
    try:
        if getattr(collection, 'hide_viewport', False):
            return True
    except Exception:
        pass
    try:
        layer_coll = find_layer_collection(context.view_layer.layer_collection, collection)
        if layer_coll and (getattr(layer_coll, 'hide_viewport', False) or getattr(layer_coll, 'exclude', False)):
            return True
    except Exception:
        pass
    return False


def fbp_rebuild_layer_view_cache(context):
    """Pre-compute which collections contain Frame by Plane rigs.

    Layer UI draw functions read these cached booleans instead of recursively
    scanning collection trees every redraw.
    """
    if not context or not getattr(context, "scene", None):
        return
    sc = context.scene
    parent_map = {}
    try:
        for coll in bpy.data.collections:
            coll["fbp_has_fbp_content"] = False
            coll["fbp_has_fbp_content_recursive"] = False
            for child in coll.children:
                parent_map.setdefault(child.name, []).append(coll)
    except Exception as exc:
        fbp_warn("Could not reset layer view cache", exc)
        return

    def mark_collection(coll):
        stack = [coll]
        seen = set()
        while stack:
            current = stack.pop()
            if not current or current.name in seen:
                continue
            seen.add(current.name)
            try:
                current["fbp_has_fbp_content_recursive"] = True
            except Exception:
                pass
            for parent in parent_map.get(current.name, []):
                stack.append(parent)

    for item in getattr(sc, "fbp_layers", []):
        try:
            rig = item.obj
            if not rig or not is_fbp_layer_object(rig) or not object_in_scene(rig, sc):
                continue
            for coll in getattr(rig, "users_collection", []):
                coll["fbp_has_fbp_content"] = True
                mark_collection(coll)
        except ReferenceError:
            continue
        except Exception as exc:
            fbp_warn("Could not cache layer collection", exc)

    fbp_runtime_set("fbp_layer_cache_dirty", False, context)


def fbp_mark_layer_cache_dirty(context=None):
    fbp_runtime_set("fbp_layer_cache_dirty", True, context)


def collection_has_fbp_content(collection, recursive=True):
    if not collection:
        return False
    key = "fbp_has_fbp_content_recursive" if recursive else "fbp_has_fbp_content"
    try:
        if key in collection:
            return bool(collection.get(key, False))
    except Exception:
        pass

    # Fallback for very early draw calls before the cache exists.
    try:
        for obj in collection.objects:
            if is_fbp_layer_object(obj):
                return True
        if recursive:
            for child in collection.children:
                if collection_has_fbp_content(child, True):
                    return True
    except Exception as exc:
        fbp_warn("Could not evaluate collection FBP content", exc)
    return False


def get_direct_fbp_rigs_in_collection(context, collection):
    rigs = []
    if not collection:
        return rigs
    order = []
    for item in context.scene.fbp_layers:
        try:
            if item.obj and is_fbp_layer_object(item.obj):
                order.append(item.obj)
        except ReferenceError:
            pass
    try:
        for rig in order:
            if any(coll == collection for coll in rig.users_collection):
                rigs.append(rig)
    except Exception:
        pass
    return sort_rigs_by_depth_for_layer_view(context, rigs)


def iter_fbp_rigs_in_collection(collection, recursive=True):
    if not collection:
        return
    seen = set()
    try:
        for obj in collection.objects:
            if is_fbp_layer_object(obj) and obj.name not in seen:
                seen.add(obj.name)
                yield obj
        if recursive:
            for child in collection.children:
                for rig in iter_fbp_rigs_in_collection(child, True):
                    if rig.name not in seen:
                        seen.add(rig.name)
                        yield rig
    except Exception:
        return


def get_child_fbp_collections(collection):
    if not collection:
        return []
    try:
        return sort_collections_for_layer_view(bpy.context, [child for child in collection.children if collection_has_fbp_content(child, True)])
    except Exception:
        return []


def get_top_fbp_collections(context):
    scene_coll = context.scene.collection
    roots = []
    try:
        for coll in scene_coll.children:
            if collection_has_fbp_content(coll, True):
                roots.append(coll)
    except Exception:
        pass
    return sort_collections_for_layer_view(context, roots)


def get_layer_item_for_rig(context, rig):
    if not rig:
        return None
    for item in context.scene.fbp_layers:
        try:
            if item.obj == rig:
                return item
        except ReferenceError:
            pass
    return None


def fbp_color_plane_type_icon(rig):
    """Icon used for rigged color/gradient/holdout planes in layer rows."""
    if not rig or not getattr(rig, 'fbp_is_color_plane', False):
        return None

    mode = getattr(rig, 'fbp_color_plane_mode', 'SOLID')

    if mode == 'GRADIENT':
        return fbp_icon("COLOR")
    if mode == 'HOLDOUT':
        return fbp_icon("GHOST_DISABLED")

    try:
        color = tuple(getattr(rig, 'fbp_color_plane_color', (1, 1, 1, 1)))
        is_white = all(abs(color[i] - 1.0) < 0.01 for i in range(3))
        is_black = all(abs(color[i]) < 0.01 for i in range(3))

        if is_white or is_black:
            return fbp_icon("IMAGE_ALPHA")
    except Exception as exc:
        print(f"[FBP Warning] Could not read color plane type icon: {exc}")

    return fbp_icon("IMAGE")


def fbp_mask_icon(is_on):
    """Use the requested UV clip icons for the holdout/mask state."""
    return fbp_icon("CLIPUV_DEHLT") if is_on else 'CLIPUV_HLT'


def fbp_select_rig_icon(is_locked, is_selected=False):
    """Checkbox icon for rig selection. Locked layers use Blender's used-layer icon."""
    if is_locked:
        return fbp_icon("LAYER_USED")
    return fbp_icon("CHECKBOX_HLT") if is_selected else 'CHECKBOX_DEHLT'


def fbp_select_plane_icon(rig, context):
    """Icon for the linked image/color plane viewport selectability toggle."""
    plane = getattr(rig, 'fbp_plane_target', None) if rig else None
    if not plane:
        return fbp_icon("RESTRICT_SELECT_ON")
    try:
        return fbp_icon("RESTRICT_SELECT_ON") if plane.hide_select else 'RESTRICT_SELECT_OFF'
    except ReferenceError:
        return fbp_icon("RESTRICT_SELECT_ON")


def fbp_collection_select_icon(collection, context):
    """Checkbox icon for collection rig selection."""
    if bool(getattr(collection, 'fbp_collection_locked', False)):
        return fbp_icon("LAYER_USED")
    rigs = [rig for rig in iter_fbp_rigs_in_collection(collection, True) if object_in_view_layer(rig, context)]
    if rigs and all(rig.select_get() for rig in rigs):
        return fbp_icon("CHECKBOX_HLT")
    return fbp_icon("CHECKBOX_DEHLT")


def fbp_collection_plane_icon(collection, context):
    """Icon for linked image/color plane selectability inside a collection."""
    planes = []
    for rig in iter_fbp_rigs_in_collection(collection, True):
        plane = getattr(rig, 'fbp_plane_target', None)
        if plane and object_in_view_layer(plane, context):
            planes.append(plane)
    if planes and all(getattr(p, 'hide_select', True) for p in planes):
        return fbp_icon("RESTRICT_SELECT_ON")
    return fbp_icon("RESTRICT_SELECT_OFF")


def fbp_collection_icon(collection):
    """Return the collection icon, preserving Blender collection color tags when available."""
    return fbp_collection_color_icon(getattr(collection, "color_tag", ""))


def fbp_layer_row_type_icon(rig, context):
    """Return the visual icon/thumbnail for a layer row without making it editable."""
    type_icon = fbp_color_plane_type_icon(rig)
    if type_icon:
        return type_icon, None

    if context.scene.fbp_show_previews:
        preview = get_layer_thumbnail(rig)
        if preview:
            return None, preview.icon_id

    return fbp_strip_icon(getattr(rig, 'fbp_color_tag', 'COLOR_09')), None


def fbp_add_tree_indent(row, depth):
    """Add one fixed BLANK1 icon for each nested collection level."""
    for _ in range(max(0, depth)):
        cell = row.row(align=True)
        fbp_set_ui_units_x(cell, 1.05)
        cell.label(text="", icon=fbp_icon("BLANK1"))


def fbp_set_ui_units_x(ui_layout, units):
    """Best-effort fixed UI width helper for compact icon blocks.

    Blender supports ui_units_x on recent versions. When unavailable, this
    quietly falls back to the normal dynamic layout instead of breaking UI draw.
    """
    try:
        ui_layout.ui_units_x = units
    except Exception:
        pass


def indent_row(row, depth):
    """Backward-compatible compact indentation helper for older UI sections."""
    fbp_add_tree_indent(row, depth)


def fbp_collection_rows_are_disabled(collection, context):
    """Return whether collection text/icon should look inactive while controls stay usable."""
    if collection_is_hidden_in_view_layer(context, collection):
        return True
    if bool(getattr(collection, 'fbp_collection_locked', False)):
        return True
    rigs = [rig for rig in iter_fbp_rigs_in_collection(collection, True) if object_in_view_layer(rig, context)]
    if rigs and all(not getattr(rig, 'fbp_is_visible', True) for rig in rigs):
        return True
    return False


def draw_fbp_layer_row(layout, context, rig, depth=0):
    item = get_layer_item_for_rig(context, rig)
    if not item:
        return

    is_disabled = (not getattr(rig, 'fbp_is_visible', True)) or bool(item.rig_locked)

    row = layout.row(align=False)
    split = row.split(factor=0.68, align=False)

    # LEFT: Eye - depth BLANK1(s) - arrow placeholder - icon+name operator.
    # Icon and name are drawn by the same operator to avoid the extra gap created
    # by separate icon_row/name_row blocks.
    left = split.row(align=True)
    left.alignment = 'LEFT'

    vis_icon = fbp_icon("HIDE_OFF") if rig.fbp_is_visible else fbp_icon("HIDE_ON")
    left.prop(rig, "fbp_is_visible", text="", icon=vis_icon, icon_only=True, emboss=False)

    for _ in range(max(0, depth)):
        left.label(text="", icon=fbp_icon("BLANK1"))

    # Keep layer names aligned with collection names, which have a disclosure arrow.
    left.label(text="", icon=fbp_icon("BLANK1"))

    name_row = left.row(align=True)
    name_row.alignment = 'LEFT'
    name_row.active = not is_disabled
    type_icon, preview_icon = fbp_layer_row_type_icon(rig, context)
    if preview_icon:
        op_name = name_row.operator("fbp.select_layer_exclusive", text=rig.name, icon_value=preview_icon, emboss=False)
    else:
        op_name = name_row.operator("fbp.select_layer_exclusive", text=rig.name, icon=type_icon or fbp_icon("STRIP_COLOR_09"), emboss=False)
    op_name.rig_name = rig.name

    # RIGHT: fixed action strip.
    right = split.row(align=True)
    right.alignment = 'RIGHT'
    fbp_set_ui_units_x(right, 5.75)

    solo_icon = fbp_icon("OUTLINER_OB_LIGHT") if item.solo_view else fbp_icon("LIGHT")
    right.prop(item, "solo_view", text="", icon=solo_icon, icon_only=True, emboss=False)

    right.prop(item, "holdout", text="", icon=fbp_mask_icon(item.holdout), icon_only=True, emboss=False)

    op_plane = right.operator("fbp.select_linked_plane", text="", icon=fbp_select_plane_icon(rig, context), emboss=False)
    op_plane.rig_name = rig.name

    lock_icon = fbp_icon("LOCKED") if item.rig_locked else fbp_icon("UNLOCKED")
    right.prop(item, "rig_locked", text="", icon=lock_icon, icon_only=True, emboss=False)

    sel_row = right.row(align=True)
    sel_row.enabled = not item.rig_locked
    sel_row.prop(item, "selected", text="", icon=fbp_select_rig_icon(item.rig_locked, rig.select_get()), icon_only=True, emboss=False)

def draw_fbp_collection_row(layout, context, collection, depth=0):
    if not collection_has_fbp_content(collection, True):
        return

    hidden = collection_is_hidden_in_view_layer(context, collection)
    collapsed = bool(getattr(collection, 'fbp_collapsed', False))
    is_disabled = fbp_collection_rows_are_disabled(collection, context)

    row = layout.row(align=False)
    split = row.split(factor=0.68, align=False)

    # LEFT: Eye - depth BLANK1(s) - disclosure arrow - collection icon+name operator.
    left = split.row(align=True)
    left.alignment = 'LEFT'

    vis_icon = fbp_icon("HIDE_OFF") if collection.fbp_collection_visible else fbp_icon("HIDE_ON")
    left.prop(collection, "fbp_collection_visible", text="", icon=vis_icon, icon_only=True, emboss=False)

    for _ in range(max(0, depth)):
        left.label(text="", icon=fbp_icon("BLANK1"))

    fold_icon = fbp_icon("RIGHTARROW") if collapsed else fbp_icon("DOWNARROW_HLT")
    op = left.operator("fbp.toggle_collection_collapse", text="", icon=fold_icon, emboss=False)
    op.collection_name = collection.name

    name_row = left.row(align=True)
    name_row.alignment = 'LEFT'
    name_row.active = not is_disabled
    op_sel = name_row.operator("fbp.select_collection_layers", text=collection.name, icon=fbp_collection_icon(collection), emboss=False)
    op_sel.collection_name = collection.name

    # RIGHT: fixed action strip.
    right = split.row(align=True)
    right.alignment = 'RIGHT'
    fbp_set_ui_units_x(right, 5.75)

    solo_icon = fbp_icon("OUTLINER_OB_LIGHT") if collection.fbp_collection_solo else fbp_icon("LIGHT")
    right.prop(collection, "fbp_collection_solo", text="", icon=solo_icon, icon_only=True, emboss=False)

    right.prop(collection, "fbp_collection_holdout", text="", icon=fbp_mask_icon(collection.fbp_collection_holdout), icon_only=True, emboss=False)

    op_planes = right.operator("fbp.select_collection_planes", text="", icon=fbp_collection_plane_icon(collection, context), emboss=False)
    op_planes.collection_name = collection.name

    lock_icon = fbp_icon("LOCKED") if collection.fbp_collection_locked else fbp_icon("UNLOCKED")
    right.prop(collection, "fbp_collection_locked", text="", icon=lock_icon, icon_only=True, emboss=False)

    sel_row = right.row(align=True)
    sel_row.enabled = not collection.fbp_collection_locked
    sel_row.prop(collection, "fbp_collection_selected", text="", icon=fbp_collection_select_icon(collection, context), icon_only=True, emboss=False)

    if collapsed or hidden:
        return

    for child in get_child_fbp_collections(collection):
        draw_fbp_collection_row(layout, context, child, depth + 1)

    direct = list(reversed(get_direct_fbp_rigs_in_collection(context, collection)))
    for rig in direct:
        draw_fbp_layer_row(layout, context, rig, depth + 1)

def draw_fbp_hierarchical_layer_view(layout, context):
    roots = get_top_fbp_collections(context)
    direct_scene_rigs = get_direct_fbp_rigs_in_collection(context, context.scene.collection)

    if not roots and not direct_scene_rigs:
        layout.label(text="No Frame by Plane layers", icon=fbp_icon("INFO"))
        return

    col = layout.column(align=True)
    for coll in roots:
        draw_fbp_collection_row(col, context, coll, 0)
    for rig in reversed(direct_scene_rigs):
        draw_fbp_layer_row(col, context, rig, 0)

def iter_material_image_nodes():
    for mat in bpy.data.materials:
        if not mat or not getattr(mat, 'use_nodes', False) or not mat.node_tree:
            continue
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and getattr(node, 'image', None):
                yield mat, node, node.image


def collect_project_image_paths():
    paths = []
    for _mat, _node, img in iter_material_image_nodes():
        p = getattr(img, 'filepath', '')
        if p:
            paths.append(p)
    return paths


def missing_project_images():
    missing = []
    for p in collect_project_image_paths():
        abs_p = bpy.path.abspath(p)
        if abs_p and not os.path.exists(abs_p):
            missing.append(p)
    return sorted(set(missing), key=natural_sort_key)


def build_project_file_index(root):
    index = {}
    root = bpy.path.abspath(root)
    if not root or not os.path.isdir(root):
        return index
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            if not is_supported_image_file(filename) or is_technical_map_file(filename):
                continue
            index.setdefault(filename.lower(), []).append(os.path.join(dirpath, filename))
    return index


def relink_missing_images_from_root(root, make_relative=True):
    file_index = build_project_file_index(root)
    relinked = 0
    ambiguous = []
    still_missing = []
    for _mat, _node, img in iter_material_image_nodes():
        old_path = getattr(img, 'filepath', '')
        if not old_path:
            continue
        abs_old = bpy.path.abspath(old_path)
        if os.path.exists(abs_old):
            if make_relative:
                try:
                    img.filepath = bpy.path.relpath(abs_old)
                except Exception:
                    pass
            continue
        filename = os.path.basename(old_path).lower()
        matches = file_index.get(filename, [])
        if len(matches) == 1:
            new_path = matches[0]
            img.filepath = bpy.path.relpath(new_path) if make_relative else new_path
            relinked += 1
        elif len(matches) > 1:
            ambiguous.append(old_path)
        else:
            still_missing.append(old_path)
    return relinked, ambiguous, still_missing




def project_root_for_package(context):
    sc = context.scene
    root = bpy.path.abspath(getattr(sc, 'fbp_project_path', '') or '')
    if root and os.path.isdir(root):
        return root
    if bpy.data.is_saved:
        return os.path.dirname(bpy.data.filepath)
    return ''


def rig_has_missing_images(rig):
    plane = getattr(rig, 'fbp_plane_target', None)
    if not plane:
        return False
    for mat in plane.data.materials:
        if not mat or not getattr(mat, 'use_nodes', False) or not mat.node_tree:
            continue
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and getattr(node, 'image', None):
                p = getattr(node.image, 'filepath', '')
                if p and not os.path.exists(bpy.path.abspath(p)):
                    return True
    return False


def swap_layer_depth_only(context, rig_a, rig_b):
    if not rig_a or not rig_b:
        return
    # Scambia solo la profondità, senza ricalcolare tutti i layer.
    axis = 1 if (getattr(rig_a, 'fbp_is_vertical', False) or getattr(rig_b, 'fbp_is_vertical', False)) else 2
    loc_a = rig_a.location.copy()
    loc_b = rig_b.location.copy()
    loc_a[axis], loc_b[axis] = loc_b[axis], loc_a[axis]
    rig_a.location = loc_a
    rig_b.location = loc_b


def object_in_scene(obj, scene=None):
    if not obj:
        return False
    try:
        if bpy.data.objects.get(obj.name) != obj:
            return False
        scene = scene or (bpy.context.scene if bpy.context else None)
        if not scene:
            return True
        return any(scene_obj == obj for scene_obj in scene.objects)
    except ReferenceError:
        return False


def object_in_view_layer(obj, context=None):
    context = context or bpy.context
    if not obj or not context:
        return False
    try:
        if not object_in_scene(obj, context.scene):
            return False
        return any(view_obj == obj for view_obj in context.view_layer.objects)
    except ReferenceError:
        return False


def ensure_object_in_active_collection(obj, context=None):
    context = context or bpy.context
    if not obj or not context:
        return False
    try:
        if object_in_view_layer(obj, context):
            return True
        coll = context.collection or context.scene.collection
        if not any(existing == obj for existing in coll.objects):
            coll.objects.link(obj)
        context.view_layer.update()
        return object_in_view_layer(obj, context)
    except Exception:
        return False


def get_selected_rigs(context):
    return [ob for ob in context.selected_objects if getattr(ob, "is_fbp_control", False)]


def get_selected_fbp_roots(context):
    roots = []
    for ob in context.selected_objects:
        rig = None
        if getattr(ob, "is_fbp_control", False):
            rig = ob
        elif getattr(ob, "is_fbp_plane", False) and getattr(ob.parent, "is_fbp_control", False):
            rig = ob.parent
        if rig and rig not in roots:
            roots.append(rig)
    return roots


def clear_previews():
    for pcoll in preview_collections.values():
        bpy.utils.previews.remove(pcoll)
    preview_collections.clear()


def update_global_visibility(context=None):
    if not context:
        context = bpy.context
    for item in context.scene.fbp_layers:
        try:
            obj = item.obj
            if not obj:
                continue
            vis = obj.fbp_is_visible and not item.mute
            plane = getattr(obj, 'fbp_plane_target', None)
            if not plane:
                continue
            plane.hide_viewport = not vis
            plane.hide_render = not vis
        except ReferenceError:
            pass


def update_mute_cb(self, context):
    update_global_visibility(context)


def get_preview_collection():
    pcoll = preview_collections.get("fbp_previews")
    if not pcoll:
        pcoll = bpy.utils.previews.new()
        preview_collections["fbp_previews"] = pcoll
    return pcoll


def load_preview(image_path):
    pcoll = get_preview_collection()
    abs_path = bpy.path.abspath(image_path)
    if abs_path in pcoll:
        return pcoll[abs_path]
    if os.path.exists(abs_path):
        try:
            return pcoll.load(abs_path, abs_path, 'IMAGE')
        except Exception:
            pass
    return None


def get_layer_thumbnail(obj):
    if not obj or not hasattr(obj, "fbp_preview_path") or not obj.fbp_preview_path:
        return None
    return load_preview(obj.fbp_preview_path)


def safe_get_socket(node, contains, excludes=[]):
    for inp in node.inputs:
        n = inp.name.lower()
        i = inp.identifier.lower()
        if all(c in n or c in i for c in contains) and not any(e in n or e in i for e in excludes):
            return inp
    return None


def set_viewport_object_color(context):
    """Prepare viewport display colors without changing texture display.

    Frame by Plane should keep object color mode on TEXTURE, because textured
    planes must remain visible while editing. Only wireframe colors are switched
    to Object when Blender exposes that setting.
    """
    screen = getattr(context, 'screen', None)
    if not screen:
        return
    for area in screen.areas:
        if area.type == 'VIEW_3D':
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    shading = getattr(space, 'shading', None)
                    if not shading:
                        continue
                    # Keep textured planes visible.
                    if hasattr(shading, 'color_type'):
                        try:
                            shading.color_type = 'TEXTURE'
                        except Exception:
                            pass
                    # Use object colors for wire display if available in this Blender version.
                    for attr in ('wireframe_color_type', 'wire_color_type'):
                        if hasattr(shading, attr):
                            try:
                                setattr(shading, attr, 'OBJECT')
                            except Exception:
                                pass


def get_eval_mat_index(rig, current_frame):
    if not getattr(rig, "fbp_images", None) or len(rig.fbp_images) == 0:
        return -1

    rel_frame = current_frame - rig.fbp_start_frame
    if rel_frame < 0:
        return -1

    N = len(rig.fbp_images)
    total_dur = sum(item.duration for item in rig.fbp_images)
    if total_dur <= 0:
        return 0

    loop_mode = rig.fbp_loop_mode

    if loop_mode == 'NONE':
        if rel_frame >= total_dur:
            return N - 1
    elif loop_mode == 'REPEAT':
        rel_frame = rel_frame % total_dur
    elif loop_mode == 'PINGPONG':
        if N == 1:
            return 0
        mid_dur = sum(item.duration for item in rig.fbp_images[1:-1])
        period = total_dur + mid_dur
        rel_frame = rel_frame % period

        if rel_frame >= total_dur:
            back_rel = rel_frame - total_dur
            accumulated = 0
            for j in range(N - 2, 0, -1):
                dur = rig.fbp_images[j].duration
                if accumulated <= back_rel < accumulated + dur:
                    return j
                accumulated += dur
            return 0

    accumulated = 0
    for i, item in enumerate(rig.fbp_images):
        if accumulated <= rel_frame < accumulated + item.duration:
            return i
        accumulated += item.duration
    return N - 1




def fbp_layer_depth_value(context, rig):
    """Return a stable depth value for sorting layers by distance from the active camera.
    Smaller values are closer to the camera. If no camera exists, use Y for vertical rigs and Z for horizontal rigs.
    """
    if not rig:
        return 0.0
    try:
        cam = context.scene.camera if context and context.scene else None
        if cam:
            cam_forward = cam.matrix_world.to_3x3() @ mathutils.Vector((0.0, 0.0, -1.0))
            return float((rig.matrix_world.translation - cam.matrix_world.translation).dot(cam_forward))
        return float(rig.location.y if getattr(rig, "fbp_is_vertical", False) else rig.location.z)
    except Exception:
        return 0.0


def sort_rigs_for_layer_view(context, rigs):
    if not context:
        return list(rigs)
    if getattr(context.scene, 'fbp_sort_layers_alpha', False):
        return sorted(rigs, key=lambda rig: natural_sort_key(rig.name))
    # Farther layers first internally; UI reverses this where needed so closest appears on top.
    return sorted(rigs, key=lambda rig: (fbp_layer_depth_value(context, rig), natural_sort_key(rig.name)), reverse=True)


def sort_rigs_by_depth_for_layer_view(context, rigs):
    return sort_rigs_for_layer_view(context, rigs)


def sort_collections_for_layer_view(context, collections):
    if getattr(context.scene, 'fbp_sort_layers_alpha', False):
        return sorted(collections, key=lambda c: natural_sort_key(c.name))
    def _collection_depth(coll):
        rigs = list(iter_fbp_rigs_in_collection(coll, True))
        if not rigs:
            return 0.0
        return sum(fbp_layer_depth_value(context, rig) for rig in rigs) / max(1, len(rigs))
    return sorted(collections, key=lambda c: (_collection_depth(c), natural_sort_key(c.name)), reverse=True)


def set_timeline_range_from_rigs(context, rigs):
    """Set scene timeline to cover the selected/generated FBP sequences."""
    valid = [rig for rig in rigs if rig and getattr(rig, "is_fbp_control", False)]
    if not valid:
        return False

    starts = []
    ends = []
    for rig in valid:
        total = sum(max(1, item.duration) for item in rig.fbp_images)
        if total <= 0:
            continue
        start = int(rig.fbp_start_frame)
        starts.append(start)
        ends.append(start + total - 1)

    if not starts or not ends:
        return False

    context.scene.frame_start = min(starts)
    context.scene.frame_end = max(ends)
    return True


# ── LAYER UI BOOLEAN HELPERS ─────────────────────────────────────────────────

def _safe_layer_obj(layer_item):
    try:
        obj = layer_item.obj
        if obj and object_in_scene(obj):
            return obj
    except ReferenceError:
        pass
    return None


def get_layer_selected(self):
    obj = _safe_layer_obj(self)
    return bool(obj and obj.select_get())


def set_layer_selected(self, value):
    obj = _safe_layer_obj(self)
    if not obj:
        return
    try:
        context = bpy.context
        if value and not object_in_view_layer(obj, context):
            if not ensure_object_in_active_collection(obj, context):
                sync_layer_collection(context)
                return
        obj.select_set(bool(value))
        if value and context and context.view_layer and object_in_view_layer(obj, context):
            context.view_layer.objects.active = obj
    except Exception:
        pass


def get_layer_rig_locked(self):
    obj = _safe_layer_obj(self)
    return bool(obj.hide_select) if obj else False


def set_layer_rig_locked(self, value):
    obj = _safe_layer_obj(self)
    if obj:
        obj.hide_select = bool(value)


def get_layer_plane_locked(self):
    obj = _safe_layer_obj(self)
    plane = getattr(obj, "fbp_plane_target", None) if obj else None
    return bool(plane.hide_select) if plane else False


def set_layer_plane_locked(self, value):
    obj = _safe_layer_obj(self)
    plane = getattr(obj, "fbp_plane_target", None) if obj else None
    if plane:
        plane.hide_select = bool(value)


def get_layer_solo_view(self):
    return bool(self.solo)


def set_layer_solo_view(self, value):
    context = bpy.context
    sc = context.scene if context else None
    rig = _safe_layer_obj(self)
    value = bool(value)

    if not sc:
        self.solo = value
        return

    if value:
        # First solo click isolates the layer. Further solo clicks add more layers.
        if not any(item.solo for item in sc.fbp_layers):
            for item in sc.fbp_layers:
                item.solo = False
                obj = _safe_layer_obj(item)
                if obj:
                    obj.fbp_is_visible = False

        self.solo = True
        if rig:
            rig.fbp_is_visible = True
    else:
        self.solo = False
        if rig:
            rig.fbp_is_visible = False

        # If no layer remains soloed, restore all layers.
        if not any(item.solo for item in sc.fbp_layers):
            for item in sc.fbp_layers:
                obj = _safe_layer_obj(item)
                if obj:
                    obj.fbp_is_visible = True

    update_global_visibility(context)


def get_layer_holdout(self):
    obj = _safe_layer_obj(self)
    try:
        return bool(obj and rig_holdout_is_active(obj))
    except Exception:
        return False


def set_layer_holdout(self, value):
    obj = _safe_layer_obj(self)
    if not obj:
        return
    try:
        if value:
            fbp_apply_holdout_materials_to_rig(obj)
        else:
            restore_original_materials_from_holdout(obj)
    except Exception as exc:
        print(f"[FBP] Holdout toggle skipped: {exc}")


def _collection_rigs_for_ui(collection):
    try:
        return list(iter_fbp_rigs_in_collection(collection, True))
    except Exception:
        return []



def get_collection_selected(self):
    rigs = _collection_rigs_for_ui(self)
    try:
        return bool(rigs and all(get_layer_item_for_rig(bpy.context, rig).selected for rig in rigs if get_layer_item_for_rig(bpy.context, rig)))
    except Exception:
        return False


def set_collection_selected(self, value):
    for rig in _collection_rigs_for_ui(self):
        item = get_layer_item_for_rig(bpy.context, rig)
        if item:
            item.selected = bool(value)


def get_collection_solo(self):
    rigs = _collection_rigs_for_ui(self)
    try:
        return bool(rigs and all(get_layer_item_for_rig(bpy.context, rig).solo_view for rig in rigs if get_layer_item_for_rig(bpy.context, rig)))
    except Exception:
        return False


def set_collection_solo(self, value):
    for rig in _collection_rigs_for_ui(self):
        item = get_layer_item_for_rig(bpy.context, rig)
        if item:
            item.solo_view = bool(value)
    try:
        update_global_visibility(bpy.context)
    except Exception as exc:
        fbp_warn("Could not update collection solo visibility", exc)

def get_collection_locked(self):
    rigs = _collection_rigs_for_ui(self)
    return bool(rigs and all(getattr(rig, 'hide_select', False) for rig in rigs))


def set_collection_locked(self, value):
    for rig in _collection_rigs_for_ui(self):
        rig.hide_select = bool(value)


def get_collection_visible(self):
    try:
        return not collection_is_hidden_in_view_layer(bpy.context, self)
    except Exception:
        return True


def set_collection_visible(self, value):
    hidden = not bool(value)
    try:
        self.hide_viewport = hidden
    except Exception:
        pass
    try:
        layer_coll = find_layer_collection(bpy.context.view_layer.layer_collection, self)
        if layer_coll:
            layer_coll.hide_viewport = hidden
    except Exception:
        pass
    try:
        update_global_visibility(bpy.context)
    except Exception:
        pass


def get_collection_holdout(self):
    rigs = _collection_rigs_for_ui(self)
    try:
        return bool(rigs and all(rig_holdout_is_active(rig) for rig in rigs))
    except Exception:
        return False


def set_collection_holdout(self, value):
    for rig in _collection_rigs_for_ui(self):
        try:
            if value:
                fbp_apply_holdout_materials_to_rig(rig)
            else:
                restore_original_materials_from_holdout(rig)
        except Exception:
            pass


# ── PROPERTY GROUPS ───────────────────────────────────────────────────────────

class FBP_LayerItem(PropertyGroup):
    obj:    PointerProperty(type=bpy.types.Object)
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
    duration:    IntProperty(name="Duration", default=2, min=1)
    is_selected: BoolProperty(name="Select", default=True)
    is_empty:    BoolProperty(name="Empty", default=False)
    filepath:    StringProperty(name="File", subtype='FILE_PATH', default="")


class FBP_PendingPlaneItem(PropertyGroup):
    name:          StringProperty(name="Name", description="Name of the layer that will be created", default="New Layer")
    collection_name: StringProperty(name="Collection", description="Target collection for this pending layer", default="")
    directory:     StringProperty(name="Source Folder", description="Folder containing the images for this pending layer")
    files_str:     StringProperty(name="Files", description="Internal list of image files that will become this layer sequence")
    fbp_color_tag: EnumProperty(name="Color Tag", description="Color tag to assign to the generated rig and collection", items=COLOR_ENUM_ITEMS, default='COLOR_01')


# ── LAYER / SYNC HELPERS ──────────────────────────────────────────────────────

def sync_layer_collection(context):
    sc = context.scene
    for i in range(len(sc.fbp_layers) - 1, -1, -1):
        try:
            item = sc.fbp_layers[i]
            if not item.obj or not object_in_scene(item.obj, sc):
                sc.fbp_layers.remove(i)
        except ReferenceError:
            sc.fbp_layers.remove(i)

    existing_objs = []
    for item in sc.fbp_layers:
        try:
            if item.obj and object_in_scene(item.obj, sc):
                existing_objs.append(item.obj)
                plane = getattr(item.obj, "fbp_plane_target", None)
                if plane and object_in_scene(plane, sc):
                    plane.is_fbp_plane = True
        except ReferenceError:
            pass

    for obj in sc.objects:
        if is_fbp_layer_object(obj) and obj not in existing_objs:
            item = sc.fbp_layers.add()
            item.obj = obj
            plane = getattr(obj, "fbp_plane_target", None)
            if plane and object_in_scene(plane, sc):
                plane.is_fbp_plane = True
            sc.fbp_layers.move(len(sc.fbp_layers) - 1, 0)

    fbp_rebuild_layer_view_cache(context)


def fbp_linked_planes_for_rig(rig, scene=None):
    """Find every render plane that belongs to a rig, even if the pointer is stale."""
    planes = []
    if not rig:
        return planes

    def add_plane(obj):
        try:
            if obj and getattr(obj, "is_fbp_plane", False) and bpy.data.objects.get(obj.name) == obj and obj not in planes:
                planes.append(obj)
        except ReferenceError:
            pass

    try:
        add_plane(getattr(rig, "fbp_plane_target", None))
    except ReferenceError:
        pass

    objects = list(scene.objects) if scene else list(bpy.data.objects)
    for obj in objects:
        try:
            if not getattr(obj, "is_fbp_plane", False):
                continue
            if getattr(obj, "parent", None) == rig:
                add_plane(obj)
                continue
            if getattr(obj, "name", "") == "Plane_" + getattr(rig, "name", ""):
                add_plane(obj)
                continue
            if obj.get("fbp_parent_rig_name", "") == getattr(rig, "name", ""):
                add_plane(obj)
        except ReferenceError:
            continue
    return planes


def delete_fbp_rigs(context, rigs):
    unique_layers = []
    for rig in rigs:
        if rig and is_fbp_layer_object(rig) and rig not in unique_layers:
            unique_layers.append(rig)

    if not unique_layers:
        return 0

    deleted = 0
    scene = context.scene if context else None
    for rig in unique_layers:
        try:
            planes = fbp_linked_planes_for_rig(rig, scene)
            for plane in planes:
                try:
                    mesh = getattr(plane, 'data', None)
                    mats_to_remove = [mat for mat in mesh.materials if mat] if mesh else []
                    bpy.data.objects.remove(plane, do_unlink=True)
                    if mesh and mesh.users == 0:
                        bpy.data.meshes.remove(mesh)
                    for mat in mats_to_remove:
                        if mat and mat.users == 0:
                            bpy.data.materials.remove(mat)
                except ReferenceError:
                    pass
                except Exception as exc:
                    print(f"[FBP] Could not delete linked plane: {exc}")

            rig_mesh = getattr(rig, 'data', None)
            if bpy.data.objects.get(rig.name) == rig:
                bpy.data.objects.remove(rig, do_unlink=True)
                if rig_mesh and rig_mesh.users == 0:
                    bpy.data.meshes.remove(rig_mesh)
                deleted += 1
        except ReferenceError:
            pass

    for img in list(bpy.data.images):
        if img.users == 0 and not getattr(img, "use_fake_user", False):
            bpy.data.images.remove(img)

    if context:
        cleanup_orphan_fbp_planes(context, force=True)
        sync_layer_collection(context)
    return deleted

def cleanup_orphan_fbp_planes(context, force=False):
    if not context:
        return 0
    if not force and not getattr(context.scene, 'fbp_auto_clean_orphans', False):
        return 0
    removed = 0
    removed_meshes = []
    for obj in list(context.scene.objects):
        try:
            if not getattr(obj, "is_fbp_plane", False):
                continue

            keep = False
            parent = getattr(obj, "parent", None)
            if parent:
                try:
                    keep = bool(getattr(parent, "is_fbp_control", False) and object_in_scene(parent, context.scene))
                except ReferenceError:
                    keep = False

            # Fallback for normal Blender delete: the parent pointer can be cleared,
            # but the plane keeps the original rig name as an ID property.
            rig_name = obj.get("fbp_parent_rig_name", "")
            if not keep and rig_name:
                rig = bpy.data.objects.get(rig_name)
                keep = bool(rig and getattr(rig, "is_fbp_control", False) and object_in_scene(rig, context.scene))

            if keep:
                continue

            mesh = getattr(obj, 'data', None)
            mats_to_remove = [mat for mat in mesh.materials if mat] if mesh else []
            bpy.data.objects.remove(obj, do_unlink=True)
            removed += 1
            if mesh and mesh.users == 0:
                removed_meshes.append(mesh)
            for mat in mats_to_remove:
                if mat and mat.users == 0:
                    bpy.data.materials.remove(mat)
        except ReferenceError:
            pass
        except Exception as exc:
            print(f"[FBP] Orphan cleanup skipped object: {exc}")
    for mesh in removed_meshes:
        try:
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        except Exception:
            pass
    # Only remove unused Blender datablocks. Never delete image files from disk.
    for img in list(bpy.data.images):
        try:
            if img.users == 0 and not getattr(img, "use_fake_user", False):
                bpy.data.images.remove(img)
        except Exception:
            pass
    return removed


def apply_layer_depth(context):
    sc = context.scene
    offset = sc.fbp_layer_offset
    valid_objs = [item.obj for item in sc.fbp_layers if item.obj]
    if not valid_objs:
        return

    is_vert = getattr(valid_objs[0], "fbp_is_vertical", False)
    base_depth = (min(obj.location.y for obj in valid_objs) if is_vert
                  else max(obj.location.z for obj in valid_objs))

    for i, layer_idx in enumerate(range(len(sc.fbp_layers) - 1, -1, -1)):
        obj = sc.fbp_layers[layer_idx].obj
        if not obj:
            continue
        if getattr(obj, "fbp_is_vertical", False):
            obj.location.y = base_depth + (i * offset)
        else:
            obj.location.z = base_depth - (i * offset)
        if sc.fbp_auto_scale and sc.camera and not fbp_fast_import_is_active():
            context.view_layer.update()
            context.evaluated_depsgraph_get().update()
            apply_fit_to_camera(context, obj, sc.camera)


def sync_fbp_property(self, context, prop_name):
    if getattr(context, "active_object", None) != self:
        return
    val = getattr(self, prop_name)
    for obj in context.selected_objects:
        if obj != self and getattr(obj, "is_fbp_control", False):
            if getattr(obj, prop_name) != val:
                setattr(obj, prop_name, val)


# ── CORE OPERATIONS ───────────────────────────────────────────────────────────


def fbp_set_rna_property_silent(obj, prop_name, value):
    """Set an ID/RNA custom property without firing its update callback.

    Frame by Plane stores several bpy.props on Object IDProperties. Assigning
    through obj["prop"] updates the stored value but avoids recursive update
    callbacks caused by obj.prop = value.
    """
    if not obj:
        return False
    try:
        obj[prop_name] = value
        return True
    except Exception:
        try:
            setattr(obj, prop_name, value)
            return True
        except Exception:
            return False


def do_update_animation(rig):
    plane = rig.fbp_plane_target
    if not plane or not plane.data.materials:
        return
    if plane.parent != rig:
        return
    if plane.data.animation_data:
        plane.data.animation_data_clear()
    if plane.data.polygons and rig.fbp_images:
        try:
            idx = get_eval_mat_index(rig, bpy.context.scene.frame_current)
            if idx < 0:
                idx = 0
            if idx < len(plane.data.materials):
                for poly in plane.data.polygons:
                    poly.material_index = idx
                plane.data.update()
        except Exception as e:
            print(f"[FBP] Animation update error: {e}")


def rebuild_fbp_image_material(mat, use_emission=None, opacity=None):
    if not mat or is_fbp_empty_material(mat):
        return mat
    try:
        image_path = mat.get("fbp_image_path", "")
    except Exception:
        image_path = ""
    if not image_path:
        # Legacy material: try to recover the image path from the existing node tree.
        if getattr(mat, 'use_nodes', False) and mat.node_tree:
            for node in mat.node_tree.nodes:
                if node.type == 'TEX_IMAGE' and getattr(node, 'image', None):
                    image_path = getattr(node.image, 'filepath', '')
                    break
    if not image_path:
        return mat
    interp = mat.get("fbp_interpolation", "Closest") if hasattr(mat, 'get') else "Closest"
    if use_emission is None:
        use_emission = bool(mat.get("fbp_use_emission", True)) if hasattr(mat, 'get') else True
    if opacity is None:
        opacity = float(mat.get("fbp_opacity", 1.0)) if hasattr(mat, 'get') else 1.0
    return create_fbp_material(mat.name, image_path, interp=interp, opacity=opacity, use_emission=use_emission)


def do_update_emission(rig):
    plane = rig.fbp_plane_target
    if not plane:
        return
    use_emission = bool(getattr(rig, 'fbp_color_plane_emission', getattr(rig, 'fbp_use_emission', True))) if getattr(rig, 'fbp_is_color_plane', False) else bool(getattr(rig, 'fbp_use_emission', True))
    fbp_set_rna_property_silent(rig, 'fbp_use_emission', use_emission)
    if getattr(rig, 'fbp_is_color_plane', False):
        fbp_set_rna_property_silent(rig, 'fbp_color_plane_emission', use_emission)
    plane.visible_shadow = not use_emission
    opacity = max(0.0, min(1.0, float(getattr(rig, 'fbp_opacity', 1.0))))
    for i, mat in enumerate(list(plane.data.materials)):
        if not mat or not getattr(mat, 'use_nodes', False) or is_fbp_empty_material(mat):
            continue
        if getattr(rig, 'fbp_is_color_plane', False):
            new_mat = fbp_rebuild_procedural_material_for_emission(mat, rig, use_emission)
        else:
            new_mat = rebuild_fbp_image_material(mat, use_emission=use_emission, opacity=opacity)
        if new_mat:
            plane.data.materials[i] = new_mat

def set_fbp_material_transparency(mat, opacity=1.0):
    configure_fbp_material_surface(mat, opacity, has_alpha=True)


def is_fbp_empty_material(mat):
    try:
        return bool(mat and mat.get("fbp_empty_frame", False))
    except Exception:
        return False


def create_fbp_empty_material(mat_name="FBP_Empty_Frame"):
    mat = bpy.data.materials.get(mat_name)
    if not mat:
        mat = bpy.data.materials.new(name=mat_name)
    mat["fbp_empty_frame"] = True
    mat.use_nodes = True
    set_fbp_material_transparency(mat, 0.0)

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out = nodes.new(type='ShaderNodeOutputMaterial')
    out.location = (250, 0)
    transparent = nodes.new(type='ShaderNodeBsdfTransparent')
    transparent.location = (0, 0)
    links.new(transparent.outputs[0], out.inputs[0])

    try:
        mat.diffuse_color = (0.0, 0.0, 0.0, 0.0)
    except Exception:
        pass
    return mat


def do_update_opacity(rig):
    plane = rig.fbp_plane_target
    if not plane:
        return
    opacity = max(0.0, min(1.0, float(getattr(rig, 'fbp_opacity', 1.0))))
    try:
        plane.show_transparent = opacity < 1.0
    except Exception:
        pass
    for i, mat in enumerate(list(plane.data.materials)):
        if is_fbp_empty_material(mat):
            set_fbp_material_transparency(mat, 0.0)
            continue
        if mat and mat.use_nodes:
            if getattr(rig, 'fbp_is_color_plane', False):
                if not update_fbp_procedural_material_opacity(mat, opacity):
                    new_mat = fbp_rebuild_procedural_material_for_emission(mat, rig, bool(getattr(rig, 'fbp_color_plane_emission', getattr(rig, 'fbp_use_emission', True))))
                    if new_mat:
                        plane.data.materials[i] = new_mat
            else:
                new_mat = rebuild_fbp_image_material(mat, use_emission=getattr(rig, 'fbp_use_emission', True), opacity=opacity)
                if new_mat:
                    plane.data.materials[i] = new_mat
        else:
            set_fbp_material_transparency(mat, opacity)


def do_update_track(rig, context):
    cam = context.scene.camera
    if rig.fbp_track_cam and cam:
        cons = rig.constraints.get("FBP_Track")
        if not cons:
            cons = rig.constraints.new(type='DAMPED_TRACK')
            cons.name = "FBP_Track"
        cons.target = cam
        cons.track_axis = 'TRACK_Z'
    else:
        cons = rig.constraints.get("FBP_Track")
        if cons:
            rig.constraints.remove(cons)


# ── CAMERA DEPTH GETTER/SETTER ────────────────────────────────────────────────

def get_fbp_cam_depth(self):
    cam = bpy.context.scene.camera
    if not cam:
        return self.location.y if getattr(self, "fbp_is_vertical", False) else self.location.z
    cam_z = cam.matrix_world.to_3x3() @ mathutils.Vector((0.0, 0.0, -1.0))
    return (self.location - cam.location).dot(cam_z)


def set_fbp_cam_depth(self, value):
    context = bpy.context
    sc = context.scene
    cam = sc.camera

    valid_objs = [item.obj for item in sc.fbp_layers
                  if item.obj and getattr(item.obj, "is_fbp_control", False)]

    if self in valid_objs and len(valid_objs) > 1:
        my_idx = valid_objs.index(self)
        depths = []
        for obj in valid_objs:
            if not cam:
                d = obj.location.y if getattr(obj, "fbp_is_vertical", False) else obj.location.z
            else:
                cam_z = cam.matrix_world.to_3x3() @ mathutils.Vector((0.0, 0.0, -1.0))
                d = (obj.location - cam.location).dot(cam_z)
            depths.append(d)

        my_depth = depths[my_idx]
        if my_idx > 0:
            d_prev = depths[my_idx - 1]
            value = (max(value, d_prev + 0.001) if my_depth >= d_prev
                     else min(value, d_prev - 0.001))
        if my_idx < len(valid_objs) - 1:
            d_next = depths[my_idx + 1]
            value = (max(value, d_next + 0.001) if my_depth >= d_next
                     else min(value, d_next - 0.001))

    if not cam:
        if getattr(self, "fbp_is_vertical", False):
            self.location.y = value
        else:
            self.location.z = value
        return

    cam_z = cam.matrix_world.to_3x3() @ mathutils.Vector((0.0, 0.0, -1.0))
    vec = self.location - cam.location
    current_depth = vec.dot(cam_z)
    if abs(current_depth) < 0.001:
        return

    scale_factor = value / current_depth
    self.location = cam.location + vec * scale_factor
    self.scale = (
        self.scale.x * abs(scale_factor),
        self.scale.y * abs(scale_factor),
        self.scale.z * abs(scale_factor),
    )


# ── UPDATE CALLBACKS ──────────────────────────────────────────────────────────

def update_object_padding_cb(self, context):
    # Live-update this rig's Crop and Extend values. Crop is evaluated before Extend.
    if not is_fbp_layer_object(self):
        return
    try:
        set_plane_mesh_extension(
            self,
            getattr(self, 'fbp_extend_left', 0.0), getattr(self, 'fbp_extend_right', 0.0),
            getattr(self, 'fbp_extend_bottom', 0.0), getattr(self, 'fbp_extend_top', 0.0),
            getattr(self, 'fbp_extend_mode', 'EDGE'),
            getattr(self, 'fbp_crop_left', 0.0), getattr(self, 'fbp_crop_right', 0.0),
            getattr(self, 'fbp_crop_bottom', 0.0), getattr(self, 'fbp_crop_top', 0.0),
        )
    except Exception as exc:
        print(f"[FBP] Plane padding update skipped: {exc}")


def update_extend_plane_cb(self, context):
    # Legacy scene-level callback. New Crop/Extend values are stored per rig.
    rig = getattr(context, 'active_object', None) if context else None
    if rig and is_fbp_layer_object(rig):
        update_object_padding_cb(rig, context)


def update_loop_mode_cb(self, context):
    sync_fbp_property(self, context, "fbp_loop_mode")
    do_update_animation(self)

def update_start_frame_cb(self, context):
    sync_fbp_property(self, context, "fbp_start_frame")
    do_update_animation(self)

def update_emission_cb(self, context):
    sync_fbp_property(self, context, "fbp_use_emission")
    do_update_emission(self)

def update_opacity_cb(self, context):
    sync_fbp_property(self, context, "fbp_opacity")
    do_update_opacity(self)

def update_track_cb(self, context):
    sync_fbp_property(self, context, "fbp_track_cam")
    do_update_track(self, context)

def update_global_duration_cb(self, context):
    sync_fbp_property(self, context, "fbp_global_duration")

def update_visibility_cb(self, context):
    sync_fbp_property(self, context, "fbp_is_visible")
    update_global_visibility(context)

def update_color_tag_cb(self, context):
    sync_fbp_property(self, context, "fbp_color_tag")
    if is_fbp_layer_object(self):
        apply_collection_color_to_layer(
            self,
            self.fbp_color_tag,
            getattr(self, "fbp_color_variant_index", 0),
            push_collection=getattr(self, "fbp_follow_collection_color", True)
        )

def update_image_index_cb(self, context):
    # Do not move the timeline when selecting an image row.
    # The visible frame is evaluated from the current timeline position.
    if not getattr(self, "is_fbp_control", False):
        return
    do_update_animation(self)
    if getattr(self, "fbp_is_color_plane", False):
        fbp_load_active_procedural_frame_to_rig(self)

def update_layer_stack_index_cb(self, context):
    try:
        idx = self.fbp_layer_stack_index
        if 0 <= idx < len(self.fbp_layers):
            obj = self.fbp_layers[idx].obj
            if obj and is_fbp_layer_object(obj):
                if context.view_layer.objects.active != obj:
                    # Keep previous selections alive so the layer list can support multi-select painting.
                    obj.select_set(True)
                    context.view_layer.objects.active = obj
    except Exception as e:
        print(f"[FBP] Stack index error: {e}")

def apply_camera_ratio_settings(scene):
    # Apply selected output ratio before camera or camera-ratio plane creation.
    if not scene:
        return
    ratio = getattr(scene, 'fbp_cam_ratio', '4_3')
    presets = {
        'HD_16_9': (1920, 1080), 'UHD_4K': (3840, 2160), '16_9': (1920, 1080),
        'STORY_9_16': (1080, 1920), '9_16': (1080, 1920), '4_3': (1920, 1440),
        '3_4': (1440, 1920), '1_1': (2000, 2000), '5_4': (2000, 1600),
        '16_10': (1920, 1200), 'PHOTO_3_2': (3000, 2000), 'PHOTO_2_3': (2000, 3000),
        'CINEMA_185': (1850, 1000), 'CINEMA_239': (2390, 1000), 'TWO_1': (2000, 1000),
        'ULTRAWIDE_21_9': (2520, 1080), 'A4_LANDSCAPE': (2480, 1754), 'A4_PORTRAIT': (1754, 2480),
    }
    if ratio in presets:
        scene.render.resolution_x, scene.render.resolution_y = presets[ratio]


def update_cam_ratio_cb(self, context):
    # Store the chosen camera/output ratio only.
    # Do not change the current scene/camera frame just because the preset changes:
    # Frame by Plane applies this ratio only when it creates a new camera.
    return None




# ── RENDER STABILITY HELPERS ─────────────────────────────────────────────────

def fbp_is_rendering_now():
    """Best-effort render guard. Avoid UI side effects while Blender renders."""
    if bool(fbp_runtime_get("fbp_render_guard_active", False)):
        return True
    try:
        return bool(bpy.app.is_job_running('RENDER'))
    except Exception:
        return False


def fbp_safe_empty_material():
    """Opaque-ish zero alpha material used to fill invalid material slots safely."""
    mat = bpy.data.materials.get("FBP_SAFE_EMPTY_RENDER_MAT")
    if not mat:
        mat = bpy.data.materials.new("FBP_SAFE_EMPTY_RENDER_MAT")
    mat["fbp_empty_frame"] = True
    mat.use_nodes = True
    try:
        mat.diffuse_color = (0.0, 0.0, 0.0, 0.0)
    except Exception:
        pass
    for attr, value in (
        ('surface_render_method', 'BLENDED'),
        ('blend_method', 'BLEND'),
        ('show_transparent_back', True),
    ):
        if hasattr(mat, attr):
            try:
                setattr(mat, attr, value)
            except Exception:
                pass
    try:
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()
        out = nodes.new(type='ShaderNodeOutputMaterial')
        transparent = nodes.new(type='ShaderNodeBsdfTransparent')
        links.new(transparent.outputs[0], out.inputs[0])
    except Exception:
        pass
    return mat


def fbp_ensure_plane_render_safe(rig, frame=None):
    """Make sure a FBP plane has valid materials, UVs and polygon material indices."""
    if not rig or not getattr(rig, "is_fbp_control", False):
        return False
    plane = getattr(rig, "fbp_plane_target", None)
    if not plane or not getattr(plane, "data", None):
        return False
    mesh = plane.data
    safe_mat = fbp_safe_empty_material()

    try:
        target_count = max(len(getattr(rig, "fbp_images", [])), 1)
    except Exception:
        target_count = max(len(mesh.materials), 1)

    try:
        while len(mesh.materials) < target_count:
            mesh.materials.append(safe_mat)
        for i in range(len(mesh.materials)):
            if mesh.materials[i] is None:
                mesh.materials[i] = safe_mat
    except Exception:
        pass

    try:
        if not mesh.uv_layers:
            mesh.uv_layers.new(name="UVMap")
    except Exception:
        pass

    idx = 0
    try:
        if frame is None:
            frame = bpy.context.scene.frame_current
        idx = get_eval_mat_index(rig, frame)
        if idx < 0:
            idx = 0
        if len(mesh.materials) > 0:
            idx = max(0, min(idx, len(mesh.materials) - 1))
        else:
            idx = 0
    except Exception:
        idx = 0

    try:
        for poly in mesh.polygons:
            if len(mesh.materials) > 0:
                poly.material_index = idx
            else:
                poly.material_index = 0
        mesh.update()
    except Exception:
        pass

    try:
        plane.hide_render = not bool(getattr(rig, "fbp_is_visible", True))
    except Exception:
        pass

    return True


def fbp_repair_all_render_state(scene=None, frame=None):
    scene = scene or bpy.context.scene
    fixed = 0
    for obj in list(scene.objects):
        try:
            if getattr(obj, "is_fbp_control", False):
                if fbp_ensure_plane_render_safe(obj, frame):
                    fixed += 1
                try:
                    obj.hide_render = True
                except Exception:
                    pass
        except ReferenceError:
            pass
    return fixed


@bpy.app.handlers.persistent
def fbp_render_guard_pre(scene):
    fbp_runtime_set("fbp_render_guard_active", True)
    try:
        fbp_repair_all_render_state(scene, scene.frame_current)
    except Exception as e:
        print(f"[FBP] Render guard pre error: {e}")


@bpy.app.handlers.persistent
def fbp_render_guard_post(scene):
    fbp_runtime_set("fbp_render_guard_active", False)



# ── HANDLERS ─────────────────────────────────────────────────────────────────

def sync_layer_collection_timer():
    if bpy.context:
        sync_layer_collection(bpy.context)
    return None


def cleanup_orphan_fbp_planes_timer():
    if bpy.context:
        cleanup_orphan_fbp_planes(bpy.context, force=True)
        sync_layer_collection(bpy.context)
    return 1.5


@bpy.app.handlers.persistent
def fbp_frame_change_handler(scene):
    frame = scene.frame_current
    for item in scene.fbp_layers:
        try:
            obj = item.obj
            if not obj or not getattr(obj, "is_fbp_control", False):
                continue
            plane = obj.fbp_plane_target
            if not plane or not plane.data or not plane.data.polygons:
                continue
            fbp_ensure_plane_render_safe(obj, frame)
        except ReferenceError:
            pass
        except Exception as e:
            print(f"[FBP] Frame update skipped: {e}")
    if not fbp_is_rendering_now():
        try:
            screen = getattr(bpy.context, 'screen', None)
            if screen:
                for area in screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()
        except Exception:
            pass

FBP_COLOR_PLANE_PRESETS = {
    'CUSTOM': ((1.0, 1.0, 1.0, 1.0), 'Custom'),
    'BLACK': ((0.0, 0.0, 0.0, 1.0), 'Black'),
    'WHITE': ((1.0, 1.0, 1.0, 1.0), 'White'),
    'MIDDLE_GREY': ((0.5, 0.5, 0.5, 1.0), 'Middle Grey'),
    'GREENSCREEN': ((0.0, 1.0, 0.0, 1.0), 'Greenscreen'),
    'BLUE': ((0.4, 0.592156862745098, 1.0, 1.0), 'Blue'),
    'PURPLE': ((0.5803921568627451, 0.3137254901960784, 0.9529411764705882, 1.0), 'Purple'),
    'ROSE': ((1.0, 0.25, 0.55, 1.0), 'Rose'),
    'ORANGE': ((1.0, 0.7019607843137254, 0.0, 1.0), 'Yellow'),
    'RED': ((1.0, 0.0, 0.0, 1.0), 'Red'),
}


def update_color_plane_preset_cb(self, context):
    try:
        preset = getattr(self, 'fbp_color_plane_preset', 'CUSTOM')
        if preset == 'CUSTOM':
            return
        color = FBP_COLOR_PLANE_PRESETS.get(preset, FBP_COLOR_PLANE_PRESETS['CUSTOM'])[0]
        self['_fbp_applying_color_preset'] = True
        self.fbp_color_plane_color = color
    except Exception as exc:
        fbp_warn("Could not apply color plane preset", exc)
    finally:
        try:
            self['_fbp_applying_color_preset'] = False
        except Exception:
            pass


def update_color_plane_color_cb(self, context):
    try:
        if bool(self.get('_fbp_applying_color_preset', False)):
            return
        if getattr(self, 'fbp_color_plane_preset', 'CUSTOM') != 'CUSTOM':
            self.fbp_color_plane_preset = 'CUSTOM'
    except Exception as exc:
        fbp_warn("Could not switch color plane preset to Custom", exc)



def update_scene_gradient_preview_cb(self, context):
    """Keep the creation preview material synced with the N-Panel / popup gradient controls."""
    try:
        fbp_update_scene_gradient_preview_material(self)
    except ReferenceError:
        return
    except Exception as exc:
        fbp_warn("Could not update gradient preview material", exc)


def update_wiggle_cb(self, context):
    """Live-update F-Curve noise modifiers while editing the Wiggle popup."""
    try:
        if getattr(self, "is_fbp_control", False):
            fbp_apply_wiggle_to_rig(self, context.scene if context else None)
    except ReferenceError:
        return
    except Exception as exc:
        fbp_warn("Could not update wiggle modifiers", exc)


# ── PROPERTY REGISTRATION ─────────────────────────────────────────────────────

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
    bpy.types.Scene.fbp_show_previews = BoolProperty(name="Show Thumbnails", description="Show small thumbnail previews next to Frame by Plane layer and frame rows", default=False)
    bpy.types.Scene.fbp_layer_view_mode = EnumProperty(
        name="Layer View",
        items=[
            ('COLLECTION', "Collection View", "Separate scrollable lists for each collection", fbp_icon("OUTLINER_COLLECTION"), 0),
            ('TREE', "Tree View", "Single flat layer stack", fbp_icon("RENDERLAYERS"), 1),
        ],
        default='COLLECTION')
    bpy.types.Scene.fbp_use_hierarchical_layers = BoolProperty(name="Hierarchical Layer View", description="Use collection-aware layer display where available", default=True)
    bpy.types.Scene.fbp_auto_sort_layers_by_depth = BoolProperty(
        name="Distance Sort",
        description="Sort layers by camera distance when A-Z is disabled",
        default=True)
    bpy.types.Scene.fbp_sort_layers_alpha = BoolProperty(
        name="A-Z",
        description="Sort layers and collections alphabetically instead of by camera distance",
        default=False)
    bpy.types.Scene.fbp_layer_list_rows = IntProperty(
        name="Layer Rows",
        description="Maximum number of direct layer rows shown inside each expanded collection",
        default=12, min=3, max=40)
    bpy.types.Scene.fbp_layer_filter_collection = StringProperty(default="")
    bpy.types.Scene.fbp_pending_filter_collection = StringProperty(default="")
    bpy.types.Scene.fbp_auto_clean_orphans = BoolProperty(
        name="Auto-clean orphan Frame by Plane objects",
        description="After normal deletion, remove FBP planes left without their rig and purge unused FBP datablocks. Image files on disk are never deleted",
        default=True)
    bpy.types.Scene.fbp_fit_mode = EnumProperty(
        name="Fit Mode",
        items=[
            ('FIT', "Fit Inside", "Fit the full image inside the camera frame"),
            ('FILL', "Fill Camera", "Fill the camera frame and crop if needed"),
            ('WIDTH', "Match Width", "Match the camera frame width"),
            ('HEIGHT', "Match Height", "Match the camera frame height"),
        ],
        default='FIT')
    bpy.types.Scene.fbp_show_create_tools = BoolProperty(name="Show Create Tools", description="Show additional creation tools in the sidebar", default=False)
    bpy.types.Scene.fbp_emergency_render_start = IntProperty(name="Start", description="First frame for the emergency background render", default=0, min=0)
    bpy.types.Scene.fbp_emergency_render_end = IntProperty(name="End", description="Last frame for the emergency background render", default=0, min=0)
    bpy.types.Scene.fbp_emergency_render_prefix = StringProperty(name="Prefix", description="Filename prefix used for emergency rendered frames", default="frame_")
    bpy.types.Scene.fbp_auto_collection_color_variants = BoolProperty(name="Collection Color Variants", description="Give layers small viewport color variations based on their collection color", default=True)
    bpy.types.Scene.fbp_layers = CollectionProperty(type=FBP_LayerItem)
    bpy.types.Scene.fbp_layer_stack_index = IntProperty(
        name="Layer Index", default=0, update=update_layer_stack_index_cb)
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
    bpy.types.Scene.fbp_ui_mode = EnumProperty(
        name="UI Mode",
        items=[
            ('BASIC', "Basic", "Single Plane, MultiPlane and daily tools"),
            ('ADVANCED', "Advanced", "Project import, emergency render and maintenance tools"),
        ],
        default='BASIC')
    bpy.types.Scene.fbp_show_maintenance_tools = BoolProperty(name="Maintenance Tools", description="Show extra project repair, health check and render maintenance tools", default=False)
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
        name="Color", subtype='COLOR', size=4, min=0.0, max=1.0,
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
    bpy.types.Scene.fbp_extend_left = FloatProperty(name="Left", description="Extend the left edge without scaling or deforming the central image", default=0.0, min=0.0, update=update_extend_plane_cb)
    bpy.types.Scene.fbp_extend_right = FloatProperty(name="Right", description="Extend the right edge without scaling or deforming the central image", default=0.0, min=0.0, update=update_extend_plane_cb)
    bpy.types.Scene.fbp_extend_top = FloatProperty(name="Top", description="Extend the top edge without scaling or deforming the central image", default=0.0, min=0.0, update=update_extend_plane_cb)
    bpy.types.Scene.fbp_extend_bottom = FloatProperty(name="Bottom", description="Extend the bottom edge without scaling or deforming the central image", default=0.0, min=0.0, update=update_extend_plane_cb)

    bpy.types.Collection.is_fbp_collection = BoolProperty(default=False)
    bpy.types.Collection.fbp_collapsed = BoolProperty(name="Collapsed", default=True)
    bpy.types.Collection.fbp_collection_selected = BoolProperty(name="Select Collection Layers", description="Select or deselect all Frame by Plane layers inside this collection. Click-drag across matching icons to paint selection", get=get_collection_selected, set=set_collection_selected)
    bpy.types.Collection.fbp_collection_solo = BoolProperty(name="Solo Collection Layers", description="Solo or unsolo all Frame by Plane layers inside this collection. Click-drag across matching icons to paint solo state", get=get_collection_solo, set=set_collection_solo)
    bpy.types.Collection.fbp_collection_locked = BoolProperty(name="Lock Collection Layers", description="Lock or unlock all Frame by Plane rigs and planes in this collection. Click-drag across matching icons to paint locks", get=get_collection_locked, set=set_collection_locked)
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
    bpy.types.Object.fbp_images_index   = IntProperty(update=update_image_index_cb)
    bpy.types.Object.fbp_color_tag      = EnumProperty(
        name="Color Tag", description="Viewport and collection color tag for this Frame by Plane layer",
        items=COLOR_ENUM_ITEMS, default='COLOR_01', update=update_color_tag_cb)
    bpy.types.Object.fbp_depth_order    = IntProperty(name="Depth Order", description="Internal depth order used for generated layers", default=0)
    bpy.types.Object.fbp_cam_depth      = FloatProperty(
        name="Depth",
        description="Visual depth (clamped by adjacent layers to avoid overlapping)",
        get=get_fbp_cam_depth,
        set=set_fbp_cam_depth,
        step=5)
    bpy.types.Object.fbp_loop_mode = EnumProperty(
        name="Playback",
        items=[
            ('NONE',     "One Shot",  "Play the sequence once and hold the last frame", fbp_icon("FORWARD"),        0),
            ('REPEAT',   "Loop",      "Repeat the image sequence indefinitely", fbp_icon("FILE_REFRESH"),   1),
            ('PINGPONG', "Ping-Pong", "Play forward and backward in a loop", fbp_icon("UV_SYNC_SELECT"), 2),
        ],
        default='NONE', update=update_loop_mode_cb)
    bpy.types.Object.fbp_use_emission   = BoolProperty(
        name="Shadeless", default=False, update=update_emission_cb)
    bpy.types.Object.fbp_interpolation  = EnumProperty(
        name="Filter",
        items=[
            ('Closest', "Pixel",  "Use nearest-neighbor filtering for sharp pixel edges", fbp_icon("SNAP_GRID"), 0),
            ('Linear',  "Smooth", "Use linear filtering for smoother image scaling", fbp_icon("IMAGE_RGB"), 1),
        ],
        default='Closest')
    bpy.types.Object.fbp_plane_target    = PointerProperty(name="Linked Plane", description="Image plane controlled by this Frame by Plane rig", type=bpy.types.Object)
    bpy.types.Object.fbp_global_duration = IntProperty(
        name="Global Duration", default=2, min=1, update=update_global_duration_cb)
    bpy.types.Object.fbp_start_frame     = IntProperty(
        name="Start Frame", default=1, update=update_start_frame_cb)
    bpy.types.Object.fbp_opacity         = FloatProperty(
        name="Opacity", default=1.0, min=0.0, max=1.0,
        subtype='FACTOR', update=update_opacity_cb)
    bpy.types.Object.fbp_track_cam       = BoolProperty(
        name="Track Camera", default=False, update=update_track_cb)
    bpy.types.Object.fbp_is_visible      = BoolProperty(
        name="Visible", default=True, update=update_visibility_cb)
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
    bpy.types.Object.fbp_extend_left = FloatProperty(name="Left", description="Extend the left edge after crop without scaling the image center", default=0.0, min=0.0, update=update_object_padding_cb)
    bpy.types.Object.fbp_extend_right = FloatProperty(name="Right", description="Extend the right edge after crop without scaling the image center", default=0.0, min=0.0, update=update_object_padding_cb)
    bpy.types.Object.fbp_extend_top = FloatProperty(name="Top", description="Extend the top edge after crop without scaling the image center", default=0.0, min=0.0, update=update_object_padding_cb)
    bpy.types.Object.fbp_extend_bottom = FloatProperty(name="Bottom", description="Extend the bottom edge after crop without scaling the image center", default=0.0, min=0.0, update=update_object_padding_cb)
    bpy.types.Object.fbp_crop_left = FloatProperty(name="Left", description="Crop the left edge before extension is applied", default=0.0, min=0.0, max=1.95, update=update_object_padding_cb)
    bpy.types.Object.fbp_crop_right = FloatProperty(name="Right", description="Crop the right edge before extension is applied", default=0.0, min=0.0, max=1.95, update=update_object_padding_cb)
    bpy.types.Object.fbp_crop_top = FloatProperty(name="Top", description="Crop the top edge before extension is applied", default=0.0, min=0.0, max=1.95, update=update_object_padding_cb)
    bpy.types.Object.fbp_crop_bottom = FloatProperty(name="Bottom", description="Crop the bottom edge before extension is applied", default=0.0, min=0.0, max=1.95, update=update_object_padding_cb)
    bpy.types.Object.fbp_wiggle_enabled = BoolProperty(name="Wiggle Enabled", description="Enable the Frame by Plane wiggle animation", default=False, update=update_wiggle_cb)
    bpy.types.Object.fbp_wiggle_position = BoolProperty(name="Position", description="Add noise wiggle to the visible in-plane position channels", default=True, update=update_wiggle_cb)
    bpy.types.Object.fbp_wiggle_rotation = BoolProperty(name="Rotation", description="Add noise wiggle to the in-plane rotation channel", default=False, update=update_wiggle_cb)
    bpy.types.Object.fbp_wiggle_pos_strength = FloatProperty(name="Position Strength", description="Strength of the wiggle position noise", default=0.08, min=0.0, soft_max=10.0, update=update_wiggle_cb)
    bpy.types.Object.fbp_wiggle_rot_strength = FloatProperty(name="Rotation Strength", description="Strength of the wiggle rotation noise in degrees", default=3.0, min=0.0, soft_max=180.0, update=update_wiggle_cb)
    bpy.types.Object.fbp_wiggle_scale = FloatProperty(name="Scale", description="Scale of the wiggle noise over time", default=18.0, min=0.01, soft_max=500.0, update=update_wiggle_cb)
    bpy.types.Object.fbp_wiggle_phase = FloatProperty(name="Offset", description="Offset/phase applied to the wiggle noise", default=0.0, soft_min=-1000.0, soft_max=1000.0, update=update_wiggle_cb)
    bpy.types.Object.fbp_wiggle_use_range = BoolProperty(name="Blend In / Out", description="Restrict the wiggle to a frame range and use blend in/out", default=False, update=update_wiggle_cb)
    bpy.types.Object.fbp_wiggle_frame_start = IntProperty(name="Start", description="Start frame for the wiggle modifier", default=1, update=update_wiggle_cb)
    bpy.types.Object.fbp_wiggle_frame_end = IntProperty(name="End", description="End frame for the wiggle modifier", default=250, update=update_wiggle_cb)
    bpy.types.Object.fbp_wiggle_blend_in = FloatProperty(name="Blend In", description="Blend in duration for the wiggle", default=12.0, min=0.0, soft_max=250.0, update=update_wiggle_cb)
    bpy.types.Object.fbp_wiggle_blend_out = FloatProperty(name="Blend Out", description="Blend out duration for the wiggle", default=12.0, min=0.0, soft_max=250.0, update=update_wiggle_cb)


# ── MATERIAL CREATION ─────────────────────────────────────────────────────────

def configure_fbp_material_surface(mat, opacity=1.0, has_alpha=True):
    if not mat:
        return
    alpha = max(0.0, min(1.0, float(opacity)))
    try:
        mat.diffuse_color = (mat.diffuse_color[0], mat.diffuse_color[1], mat.diffuse_color[2], alpha)
    except Exception:
        pass
    # Keep alpha support for image planes, but avoid extra opacity nodes when opacity is 100%.
    render_method = 'BLENDED' if has_alpha or alpha < 0.999 else 'OPAQUE'
    for attr, value in (
        ('surface_render_method', render_method),
        ('blend_method', 'BLEND' if render_method == 'BLENDED' else 'OPAQUE'),
        ('show_transparent_back', True),
        ('use_screen_refraction', False),
    ):
        if hasattr(mat, attr):
            try:
                setattr(mat, attr, value)
            except Exception:
                pass


def create_fbp_material(mat_name, image_path, interp='Closest', opacity=1.0, use_emission=True):
    """Create the lightest node tree needed for this image plane.

    - Shadeless uses Image Texture -> Emission -> Output.
    - Lit uses Image Texture -> Principled BSDF -> Output.
    - Opacity Multiply is created only when opacity is below 100%.
    """
    mat = bpy.data.materials.get(mat_name)
    if not mat:
        mat = bpy.data.materials.new(name=mat_name)

    opacity = max(0.0, min(1.0, float(opacity)))
    mat.use_nodes = True
    configure_fbp_material_surface(mat, opacity, has_alpha=True)
    mat["fbp_image_path"] = image_path or ""
    mat["fbp_interpolation"] = interp
    mat["fbp_use_emission"] = bool(use_emission)
    mat["fbp_opacity"] = opacity

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out = nodes.new(type='ShaderNodeOutputMaterial')
    out.location = (520, 0)

    tex = nodes.new(type='ShaderNodeTexImage')
    tex.location = (-420, 70)
    tex.interpolation = interp
    try:
        img = bpy.data.images.load(image_path, check_existing=True)
        tex.image = img
        img.alpha_mode = 'STRAIGHT'
    except Exception as e:
        print(f"[FBP] Image load error: {e}")

    if use_emission:
        shader = nodes.new(type='ShaderNodeEmission')
        shader.location = (120, 80)
        color_sock = safe_get_socket(shader, ['color']) or shader.inputs[0]
        links.new(tex.outputs['Color'], color_sock)
        try:
            shader.inputs['Strength'].default_value = 1.0
        except Exception:
            pass
    else:
        shader = nodes.new(type='ShaderNodeBsdfPrincipled')
        shader.location = (120, 80)
        base_color = safe_get_socket(shader, ['base', 'color']) or shader.inputs[0]
        links.new(tex.outputs['Color'], base_color)
        # Make lit image planes inexpensive by default.
        for socket_names, value in ((['specular'], 0.0), (['specular', 'ior', 'level'], 0.0), (['roughness'], 1.0)):
            sock = safe_get_socket(shader, socket_names)
            if sock:
                try:
                    sock.default_value = value
                except Exception:
                    pass

    if opacity < 0.999:
        math_node = nodes.new(type='ShaderNodeMath')
        math_node.operation = 'MULTIPLY'
        math_node.name = "FBP_Opacity"
        math_node.location = (-120, -170)
        math_node.inputs[1].default_value = opacity
        links.new(tex.outputs['Alpha'], math_node.inputs[0])
        alpha_source = math_node.outputs['Value']
    else:
        alpha_source = tex.outputs['Alpha']

    if use_emission:
        transparent = nodes.new(type='ShaderNodeBsdfTransparent')
        transparent.location = (110, -160)
        mix = nodes.new(type='ShaderNodeMixShader')
        mix.location = (330, 0)
        # factor 0 = shader1, 1 = shader2. Use alpha for visible emission over transparent.
        links.new(alpha_source, mix.inputs[0])
        links.new(transparent.outputs[0], mix.inputs[1])
        links.new(shader.outputs[0], mix.inputs[2])
        links.new(mix.outputs[0], out.inputs[0])
    else:
        alpha_sock = safe_get_socket(shader, ['alpha'])
        if alpha_sock:
            links.new(alpha_source, alpha_sock)
        links.new(shader.outputs[0], out.inputs[0])

    return mat



# ── COLOR / MASK PLANE HELPERS ───────────────────────────────────────────────

def camera_ratio_scale(context):
    """Return local XY scale matching the active render/camera ratio."""
    sc = context.scene if context else bpy.context.scene
    rx = max(1, int(getattr(sc.render, "resolution_x", 1920)))
    ry = max(1, int(getattr(sc.render, "resolution_y", 1080)))
    aspect = rx / ry
    if aspect >= 1.0:
        return (aspect, 1.0, 1.0)
    return (1.0, 1.0 / aspect, 1.0)

def fbp_link_object(obj, context, target_collection=None):
    """Link an object without bpy.ops so import also works outside a 3D View context."""
    collection = target_collection or getattr(context, "collection", None) or context.scene.collection
    collection.objects.link(obj)
    return obj


def fbp_create_rect_mesh(name, size=2.0, with_face=True):
    """Create a rectangular FBP mesh through the Data API.

    with_face=False is used for the control rig wire rectangle.
    with_face=True is used for the renderable plane and receives a UV map.
    """
    half = float(size) * 0.5
    verts = [(-half, -half, 0.0), (half, -half, 0.0), (half, half, 0.0), (-half, half, 0.0)]
    edges = [] if with_face else [(0, 1), (1, 2), (2, 3), (3, 0)]
    faces = [(0, 1, 2, 3)] if with_face else []
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, edges, faces)
    mesh.update()
    if with_face:
        uv_layer = mesh.uv_layers.new(name="UVMap")
        coords = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
        if mesh.polygons:
            for loop_index, uv in zip(mesh.polygons[0].loop_indices, coords):
                uv_layer.data[loop_index].uv = uv
    return mesh


def fbp_update_rig_frame_mesh_to_bounds(rig, min_x, max_x, min_y, max_y, margin=0.05):
    """Keep the wire rig rectangle aligned with the cropped/extended plane bounds."""
    if not rig or not getattr(rig, 'data', None):
        return False
    try:
        min_x, max_x = float(min_x) - margin, float(max_x) + margin
        min_y, max_y = float(min_y) - margin, float(max_y) + margin
        mesh = rig.data
        mesh.clear_geometry()
        verts = [(min_x, min_y, 0.0), (max_x, min_y, 0.0), (max_x, max_y, 0.0), (min_x, max_y, 0.0)]
        edges = [(0, 1), (1, 2), (2, 3), (3, 0)]
        mesh.from_pydata(verts, edges, [])
        mesh.update()
        return True
    except Exception as exc:
        fbp_warn("Could not update rig frame mesh bounds", exc)
        return False


def fbp_create_mesh_object(name, mesh, context, location=None, target_collection=None):
    obj = bpy.data.objects.new(name, mesh)
    if location is not None:
        obj.location = location
    fbp_link_object(obj, context, target_collection)
    return obj


def create_fbp_color_material(name, color=(1.0, 1.0, 1.0, 1.0), use_emission=True, holdout=False):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name=name)
    mat.use_nodes = True
    configure_fbp_material_surface(mat, color[3], has_alpha=color[3] < 0.999)
    try:
        mat.diffuse_color = color
        mat["fbp_color_material"] = True
        mat["fbp_color_value"] = tuple(color)
    except (TypeError, ValueError) as exc:
        fbp_warn("Could not assign material viewport color", exc)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new(type='ShaderNodeOutputMaterial')
    out.location = (320, 0)
    if holdout:
        hold = nodes.new(type='ShaderNodeHoldout')
        hold.location = (0, 0)
        links.new(hold.outputs[0], out.inputs[0])
        mat["fbp_holdout_material"] = True
        return mat
    if use_emission:
        shader = nodes.new(type='ShaderNodeEmission')
        shader.location = (0, 0)
        color_sock = safe_get_socket(shader, ['color']) or shader.inputs[0]
        color_sock.default_value = color
        try:
            shader.inputs['Strength'].default_value = 1.0
        except Exception:
            pass
    else:
        shader = nodes.new(type='ShaderNodeBsdfPrincipled')
        shader.location = (0, 0)
        base = safe_get_socket(shader, ['base', 'color']) or shader.inputs[0]
        base.default_value = color
        alpha = safe_get_socket(shader, ['alpha'])
        if alpha:
            alpha.default_value = color[3]
        spec = safe_get_socket(shader, ['specular'])
        if spec:
            spec.default_value = 0.0
    if use_emission and color[3] < 0.999:
        transparent = nodes.new(type='ShaderNodeBsdfTransparent')
        transparent.location = (0, -140)
        mix = nodes.new(type='ShaderNodeMixShader')
        mix.location = (180, 0)
        mix.inputs[0].default_value = color[3]
        links.new(transparent.outputs[0], mix.inputs[1])
        links.new(shader.outputs[0], mix.inputs[2])
        links.new(mix.outputs[0], out.inputs[0])
    else:
        links.new(shader.outputs[0], out.inputs[0])
    return mat


def create_fbp_gradient_material(name, mode='LINEAR', kind='COLOR', color_a=(1.0, 0.3686274509803922, 0.596078431372549, 1.0), color_b=(0.058823529411764705, 0.12941176470588237, 0.24313725490196078, 1.0), reverse=False, use_emission=True):
    """Create a lightweight editable gradient material for FBP color planes.

    The material uses UV coordinates so it is visible in material preview/render.
    Radial gradients are centered around a real pivot before Mapping, so scale and
    rotation behave around the visual center instead of drifting from the corner.
    A real ColorRamp node stays exposed for advanced editing.
    """
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name=name)
    mat.use_nodes = True
    configure_fbp_material_surface(mat, 1.0, has_alpha=True)
    try:
        mat.diffuse_color = color_b
    except (TypeError, ValueError) as exc:
        fbp_warn("Could not assign gradient material viewport color", exc)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out = nodes.new(type='ShaderNodeOutputMaterial'); out.location = (980, 0)
    texcoord = nodes.new(type='ShaderNodeTexCoord'); texcoord.location = (-980, 0)

    # Pivot-aware vector chain.
    # UV -> subtract editable center -> rotate/scale around that center.
    center = nodes.new(type='ShaderNodeVectorMath'); center.location = (-760, 0)
    center.name = 'FBP_GradientCenter'; center.label = 'Frame by Plane Gradient Center'
    center.operation = 'SUBTRACT'
    center['fbp_gradient_center'] = True
    center.inputs[1].default_value[0] = 0.5
    center.inputs[1].default_value[1] = 0.5
    center.inputs[1].default_value[2] = 0.0

    mapping = nodes.new(type='ShaderNodeMapping'); mapping.location = (-540, 0)
    mapping.name = 'FBP_GradientMapping'; mapping.label = 'Frame by Plane Gradient Mapping'
    mapping['fbp_gradient_mapping'] = True

    links.new(texcoord.outputs['UV'], center.inputs[0])
    links.new(center.outputs['Vector'], mapping.inputs['Vector'])

    if mode == 'CENTER':
        gradient_vector_output = mapping.outputs['Vector']
        grad_location = (-300, 0)
    else:
        # Linear gradients need the vector moved back to UV space after pivoted transforms,
        # otherwise half the ramp is clamped because coordinates become negative.
        recenter = nodes.new(type='ShaderNodeVectorMath'); recenter.location = (-320, 0)
        recenter.name = 'FBP_GradientRecenter'; recenter.label = 'Frame by Plane Gradient Recenter'
        recenter.operation = 'ADD'
        recenter['fbp_gradient_recenter'] = True
        recenter.inputs[1].default_value[0] = 0.5
        recenter.inputs[1].default_value[1] = 0.5
        recenter.inputs[1].default_value[2] = 0.0
        links.new(mapping.outputs['Vector'], recenter.inputs[0])
        gradient_vector_output = recenter.outputs['Vector']
        grad_location = (-100, 0)

    grad = nodes.new(type='ShaderNodeTexGradient'); grad.location = grad_location
    grad.name = 'FBP_GradientTexture'; grad.label = 'Frame by Plane Gradient Texture'
    grad.gradient_type = 'SPHERICAL' if mode == 'CENTER' else 'LINEAR'
    links.new(gradient_vector_output, grad.inputs['Vector'])

    ramp = nodes.new(type='ShaderNodeValToRGB'); ramp.location = (120, 0)
    ramp.name = 'FBP_ColorRamp'; ramp.label = 'Frame by Plane Color Ramp'
    c0 = tuple(color_a)
    c1 = tuple(color_b)
    if kind == 'ALPHA':
        c0 = (c0[0], c0[1], c0[2], 0.0)
        c1 = (c1[0], c1[1], c1[2], max(0.0, min(1.0, c1[3])))
    if reverse:
        c0, c1 = c1, c0
    ramp['fbp_gradient_ramp'] = True
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = c0
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = c1
    links.new(grad.outputs['Fac'], ramp.inputs['Fac'])

    transparent = nodes.new(type='ShaderNodeBsdfTransparent'); transparent.location = (440, -140)
    shader = nodes.new(type='ShaderNodeEmission' if use_emission else 'ShaderNodeBsdfPrincipled'); shader.location = (440, 110)
    color_sock = safe_get_socket(shader, ['color']) or shader.inputs[0]
    links.new(ramp.outputs['Color'], color_sock)
    if use_emission:
        strength = safe_get_socket(shader, ['strength'])
        if strength:
            strength.default_value = 1.0
    else:
        alpha_sock = safe_get_socket(shader, ['alpha'])
        if alpha_sock:
            links.new(ramp.outputs['Alpha'], alpha_sock)

    mix = nodes.new(type='ShaderNodeMixShader'); mix.location = (760, 0)
    links.new(ramp.outputs['Alpha'], mix.inputs[0])
    links.new(transparent.outputs[0], mix.inputs[1])
    links.new(shader.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs[0])

    mat['fbp_gradient_material'] = True
    mat['fbp_gradient_mode'] = mode
    mat['fbp_gradient_kind'] = kind
    mat['fbp_gradient_reverse'] = bool(reverse)
    mat['fbp_use_emission'] = bool(use_emission)
    mat['fbp_solid_view_note'] = 'Procedural ColorRamp gradients are evaluated in Material Preview/Rendered view. Solid view can only show a flat viewport color unless Blender is set to a texture/attribute display mode.'
    return mat

def fbp_rebuild_color_plane_material(rig):
    """Rebuild the active material of an editable FBP color/gradient/holdout plane.

    When a color/gradient plane has frame rows, each frame must keep an independent
    material. Reuse the active material name instead of a shared rig-wide name, so
    editing one frame never overwrites the others.
    """
    if not rig or not getattr(rig, 'fbp_is_color_plane', False):
        return False
    plane = getattr(rig, 'fbp_plane_target', None)
    if not plane or not getattr(plane, 'data', None):
        return False
    mode = getattr(rig, 'fbp_color_plane_mode', 'SOLID')
    use_emission = bool(getattr(rig, 'fbp_color_plane_emission', getattr(rig, 'fbp_use_emission', True)))

    target_index = None
    target_name = None
    current_mat = None
    if len(getattr(rig, 'fbp_images', [])) > 0 and len(plane.data.materials) > 0:
        target_index = max(0, min(getattr(rig, 'fbp_images_index', 0), len(plane.data.materials) - 1))
        current_mat = plane.data.materials[target_index]
        if current_mat:
            target_name = current_mat.name
    elif len(plane.data.materials) > 0 and plane.data.materials[0]:
        current_mat = plane.data.materials[0]
        target_name = current_mat.name

    old_ramp_data = fbp_capture_color_ramp_data(find_fbp_gradient_ramp_node(current_mat)) if mode == 'GRADIENT' and current_mat else None

    if mode == 'GRADIENT':
        gradient_kind = getattr(rig, 'fbp_gradient_kind', 'COLOR')
        mat = create_fbp_gradient_material(
            target_name or ("FBP_Gradient_" + rig.name),
            getattr(rig, 'fbp_gradient_mode', 'LINEAR'),
            gradient_kind,
            tuple(getattr(rig, 'fbp_gradient_color_a', (1.0, 0.3686274509803922, 0.596078431372549, 1.0))),
            tuple(getattr(rig, 'fbp_gradient_color_b', (0.058823529411764705, 0.12941176470588237, 0.24313725490196078, 1.0))),
            bool(getattr(rig, 'fbp_gradient_reverse', False)),
            use_emission,
        )
        if old_ramp_data:
            fbp_restore_color_ramp_data(old_ramp_data, find_fbp_gradient_ramp_node(mat))
        fbp_apply_gradient_kind_to_ramp_node(find_fbp_gradient_ramp_node(mat), gradient_kind)
    elif mode == 'HOLDOUT':
        mat = create_fbp_color_material(target_name or ("FBP_Mat_" + rig.name), (0.0, 0.0, 0.0, 1.0), use_emission, True)
    else:
        color = tuple(getattr(rig, 'fbp_color_plane_color', (1.0, 1.0, 1.0, 1.0)))
        mat = create_fbp_color_material(target_name or ("FBP_Mat_" + rig.name), color, use_emission, False)
    if target_index is not None and len(plane.data.materials) > 0:
        plane.data.materials[target_index] = mat
    else:
        plane.data.materials.clear()
        plane.data.materials.append(mat)
    fbp_set_rna_property_silent(rig, 'fbp_use_emission', use_emission)
    if mode == 'GRADIENT':
        try:
            apply_fbp_gradient_mapping_to_material(rig, mat)
        except Exception as exc:
            fbp_warn("Could not apply gradient transform after rebuilding material", exc)
    return True


def update_object_color_plane_cb(self, context):
    try:
        if bool(self.get("_fbp_syncing_frame_material", False)):
            return
        fbp_rebuild_color_plane_material(self)
    except ReferenceError:
        return
    except Exception as exc:
        fbp_warn("Could not update color/gradient plane material", exc)


def build_fbp_color_rig(context, name, color, use_emission=True, holdout=False, location=None, target_collection=None, gradient_settings=None):
    sc = context.scene
    location = location or sc.cursor.location.copy()
    target_collection = target_collection or getattr(context, 'collection', None) or sc.collection

    rig_mesh = fbp_create_rect_mesh("Mesh_" + (name or "Color_Plane") + "_Rig", size=2.1, with_face=False)
    rig = fbp_create_mesh_object(name or "Color Plane", rig_mesh, context, location=location, target_collection=target_collection)
    rig.display_type = 'WIRE'
    rig.is_fbp_control = True
    rig.hide_render = True
    fbp_set_rna_property_silent(rig, 'fbp_use_emission', bool(use_emission))
    fbp_set_rna_property_silent(rig, 'fbp_color_plane_emission', bool(use_emission))
    rig.fbp_loop_mode = 'NONE'
    rig.fbp_global_duration = 1
    rig.fbp_start_frame = sc.frame_current
    rig.scale = camera_ratio_scale(context)
    rig.fbp_base_scale_vec = rig.scale
    rig.fbp_color_tag = 'COLOR_01'
    rig.fbp_is_color_plane = True
    rig.fbp_color_plane_color = color
    rig.fbp_color_plane_mode = 'GRADIENT' if gradient_settings else ('HOLDOUT' if holdout else 'SOLID')
    if gradient_settings:
        rig.fbp_gradient_mode = gradient_settings.get('mode', 'LINEAR')
        rig.fbp_gradient_kind = gradient_settings.get('kind', 'COLOR')
        rig.fbp_gradient_color_a = gradient_settings.get('color_a', (0, 0, 0, 0))
        rig.fbp_gradient_color_b = gradient_settings.get('color_b', color)
        rig.fbp_gradient_reverse = bool(gradient_settings.get('reverse', False))
        rig.fbp_gradient_offset_x = float(gradient_settings.get('offset_x', 0.0))
        rig.fbp_gradient_offset_y = float(gradient_settings.get('offset_y', 0.0))
        rig.fbp_gradient_scale_x = float(gradient_settings.get('scale_x', 1.0))
        rig.fbp_gradient_scale_y = float(gradient_settings.get('scale_y', 1.0))
        rig.fbp_gradient_rotation = float(gradient_settings.get('rotation', 0.0))
    if sc.fbp_pre_orientation == 'VERT':
        rig.rotation_euler[0] = math.radians(90)
        rig.fbp_is_vertical = True

    plane_mesh = fbp_create_rect_mesh("Mesh_Plane_" + (name or "Color_Plane"), size=2.0, with_face=True)
    plane = fbp_create_mesh_object("Plane_" + rig.name, plane_mesh, context, location=location, target_collection=target_collection)
    plane.is_fbp_plane = True
    plane["fbp_parent_rig_name"] = rig.name
    plane.parent = rig
    plane.location = (0, 0, 0)
    plane.rotation_euler = (0, 0, 0)
    plane.hide_select = True
    rig.fbp_plane_target = plane

    fbp_rebuild_color_plane_material(rig)

    # Static procedural planes start without frame rows.
    # The image/frame list appears only after the user explicitly adds/imports a frame.
    if target_collection:
        rig.fbp_collection_name = target_collection.name
        plane.fbp_collection_name = target_collection.name
    return rig


def set_plane_mesh_extension(rig, left=0.0, right=0.0, bottom=0.0, top=0.0, mode='EDGE', crop_left=0.0, crop_right=0.0, crop_bottom=0.0, crop_top=0.0):
    """Extend plane borders without scaling/deforming the center image.

    Rebuilds the plane as a 3x3 grid. The middle quad keeps UV 0..1 exactly.
    Border quads either clamp UVs to the side pixel (EDGE) or repeat texture (REPEAT).
    """
    plane = getattr(rig, "fbp_plane_target", None)
    if not plane or not getattr(plane, "data", None):
        return False

    left = max(0.0, float(left))
    right = max(0.0, float(right))
    bottom = max(0.0, float(bottom))
    top = max(0.0, float(top))
    crop_left = max(0.0, min(1.95, float(crop_left)))
    crop_right = max(0.0, min(1.95, float(crop_right)))
    crop_bottom = max(0.0, min(1.95, float(crop_bottom)))
    crop_top = max(0.0, min(1.95, float(crop_top)))
    if crop_left + crop_right > 1.98:
        scale = 1.98 / (crop_left + crop_right)
        crop_left *= scale
        crop_right *= scale
    if crop_bottom + crop_top > 1.98:
        scale = 1.98 / (crop_bottom + crop_top)
        crop_bottom *= scale
        crop_top *= scale
    mode = (mode or 'EDGE').upper()

    mesh = plane.data
    mats = [mat for mat in mesh.materials]

    x0 = -1.0 + crop_left
    x1 = 1.0 - crop_right
    y0 = -1.0 + crop_bottom
    y1 = 1.0 - crop_top
    xs = [x0 - left, x0, x1, x1 + right]
    ys = [y0 - bottom, y0, y1, y1 + top]
    verts = [(x, y, 0.0) for y in ys for x in xs]

    def vid(ix, iy):
        return iy * 4 + ix

    faces = []
    face_cells = []
    for iy in range(3):
        for ix in range(3):
            faces.append((vid(ix, iy), vid(ix + 1, iy), vid(ix + 1, iy + 1), vid(ix, iy + 1)))
            face_cells.append((ix, iy))

    mesh.clear_geometry()
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    mesh.materials.clear()
    for mat in mats:
        if mat:
            mesh.materials.append(mat)

    uv_layer = mesh.uv_layers.new(name="UVMap") if not mesh.uv_layers else mesh.uv_layers.active

    u0 = crop_left / 2.0
    u1 = 1.0 - (crop_right / 2.0)
    v0 = crop_bottom / 2.0
    v1 = 1.0 - (crop_top / 2.0)
    if mode == 'REPEAT':
        ux = [u0 - left / 2.0, u0, u1, u1 + right / 2.0]
        uy = [v0 - bottom / 2.0, v0, v1, v1 + top / 2.0]
    else:
        ux = [u0, u0, u1, u1]
        uy = [v0, v0, v1, v1]

    # Blender's primitive plane UV orientation is local XY. Assign per face loop.
    for poly, (ix, iy) in zip(mesh.polygons, face_cells):
        coords = ((ux[ix], uy[iy]), (ux[ix + 1], uy[iy]), (ux[ix + 1], uy[iy + 1]), (ux[ix], uy[iy + 1]))
        for loop_index, uv in zip(poly.loop_indices, coords):
            uv_layer.data[loop_index].uv = uv
        poly.material_index = 0

    fbp_update_rig_frame_mesh_to_bounds(rig, xs[0], xs[-1], ys[0], ys[-1])

    rig["fbp_extend_left"] = left
    rig["fbp_extend_right"] = right
    rig["fbp_extend_bottom"] = bottom
    rig["fbp_extend_top"] = top
    rig["fbp_extend_mode"] = mode
    rig["fbp_crop_left"] = crop_left
    rig["fbp_crop_right"] = crop_right
    rig["fbp_crop_bottom"] = crop_bottom
    rig["fbp_crop_top"] = crop_top
    return True


def fbp_holdout_material():
    return create_fbp_color_material("FBP_HOLDOUT_MAT", (0.0, 0.0, 0.0, 1.0), True, True)


def fbp_alpha_holdout_material_from_source(source_mat):
    """Create a holdout material that respects the source image alpha channel."""
    if not source_mat or not getattr(source_mat, "use_nodes", False) or not source_mat.node_tree:
        return fbp_holdout_material()
    img = None
    interpolation = 'Closest'
    for node in source_mat.node_tree.nodes:
        if node.type == 'TEX_IMAGE' and getattr(node, "image", None):
            img = node.image
            interpolation = getattr(node, "interpolation", interpolation)
            break
    if not img:
        return fbp_holdout_material()
    mat_name = "FBP_AlphaHoldout_" + source_mat.name
    mat = bpy.data.materials.get(mat_name) or bpy.data.materials.new(mat_name)
    mat.use_nodes = True
    set_fbp_material_transparency(mat, 1.0)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new(type='ShaderNodeOutputMaterial')
    out.location = (500, 0)
    tex = nodes.new(type='ShaderNodeTexImage')
    tex.location = (-450, 120)
    tex.image = img
    tex.interpolation = interpolation
    transparent = nodes.new(type='ShaderNodeBsdfTransparent')
    transparent.location = (-100, -80)
    hold = nodes.new(type='ShaderNodeHoldout')
    hold.location = (-100, 120)
    mix = nodes.new(type='ShaderNodeMixShader')
    mix.location = (220, 40)
    links.new(tex.outputs['Alpha'], mix.inputs[0])
    links.new(transparent.outputs[0], mix.inputs[1])
    links.new(hold.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs[0])
    mat["fbp_holdout_material"] = True
    mat["fbp_alpha_holdout"] = True
    return mat


def fbp_apply_holdout_materials_to_rig(rig):
    plane = getattr(rig, "fbp_plane_target", None)
    if not plane or not getattr(plane, "data", None):
        return False
    store_original_materials_for_holdout(rig)
    source_materials = [mat for mat in plane.data.materials]
    plane.data.materials.clear()
    if not source_materials:
        plane.data.materials.append(fbp_holdout_material())
    else:
        for mat in source_materials:
            plane.data.materials.append(fbp_alpha_holdout_material_from_source(mat))
    return True


def store_original_materials_for_holdout(rig):
    plane = getattr(rig, "fbp_plane_target", None)
    if not plane or not getattr(plane, "data", None):
        return
    rig["fbp_holdout_original_materials"] = "|".join([mat.name if mat else "" for mat in plane.data.materials])


def restore_original_materials_from_holdout(rig):
    plane = getattr(rig, "fbp_plane_target", None)
    names = rig.get("fbp_holdout_original_materials", "") if rig else ""
    if not plane or not names:
        return False
    plane.data.materials.clear()
    for name in names.split("|"):
        mat = bpy.data.materials.get(name) if name else None
        if mat:
            plane.data.materials.append(mat)
    if "fbp_holdout_original_materials" in rig:
        del rig["fbp_holdout_original_materials"]
    return True

# ── FIT TO CAMERA ─────────────────────────────────────────────────────────────

def fbp_rig_base_image_size(rig):
    """Return local image dimensions for fit-to-camera, ignoring rig/mesh extensions."""
    base_x = max(float(getattr(rig, "fbp_base_scale_vec", (1.0, 1.0, 1.0))[0]), 0.0001)
    base_y = max(float(getattr(rig, "fbp_base_scale_vec", (1.0, 1.0, 1.0))[1]), 0.0001)
    # FBP planes are created at local size 2.0; extensions change the mesh but not the image ratio.
    return 2.0 * base_x, 2.0 * base_y


def apply_fit_to_camera(context, rig, cam, fit_mode=None):
    if not rig or not cam:
        return
    fit_mode = fit_mode or getattr(context.scene, "fbp_fit_mode", 'FIT')
    cam_z = cam.matrix_world.to_3x3() @ mathutils.Vector((0.0, 0.0, -1.0))
    vec = rig.matrix_world.translation - cam.matrix_world.translation
    dist = abs(vec.dot(cam_z))
    if dist < 0.001:
        return

    frame = cam.data.view_frame(scene=context.scene)
    min_x = min(v.x for v in frame)
    max_x = max(v.x for v in frame)
    min_y = min(v.y for v in frame)
    max_y = max(v.y for v in frame)
    frame_z = abs(frame[0].z) if abs(frame[0].z) > 1e-6 else 1.0
    projection_scale = dist / frame_z
    frame_width = abs(max_x - min_x) * projection_scale
    frame_height = abs(max_y - min_y) * projection_scale

    base_vec = getattr(rig, "fbp_base_scale_vec", (1.0, 1.0, 1.0))
    base_x = max(float(base_vec[0]), 0.0001)
    base_y = max(float(base_vec[1]), 0.0001)
    base_z = max(float(base_vec[2]), 0.0001)
    img_width, img_height = fbp_rig_base_image_size(rig)
    if img_width <= 0 or img_height <= 0:
        return

    fit_mode = fit_mode.upper()
    if fit_mode == 'WIDTH':
        factor = frame_width / img_width
    elif fit_mode == 'HEIGHT':
        factor = frame_height / img_height
    elif fit_mode == 'FILL':
        factor = max(frame_width / img_width, frame_height / img_height)
    else:
        factor = min(frame_width / img_width, frame_height / img_height)
    rig.scale = (base_x * factor, base_y * factor, base_z * factor)


def fbp_find_node_by_type(nodes, node_type):
    for node in nodes:
        if node.type == node_type:
            return node
    return None


def fbp_relink_node_input(links, socket, output_socket):
    try:
        while socket.links:
            links.remove(socket.links[0])
    except Exception:
        pass
    try:
        links.new(output_socket, socket)
    except Exception:
        pass


def update_fbp_procedural_material_opacity(mat, opacity=1.0):
    """Apply the layer opacity slider to solid/gradient procedural materials."""
    if not mat or not getattr(mat, 'use_nodes', False):
        return False
    opacity = max(0.0, min(1.0, float(opacity)))
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    configure_fbp_material_surface(mat, opacity, has_alpha=True)
    try:
        rgba = list(getattr(mat, 'diffuse_color', (1.0, 1.0, 1.0, 1.0)))
        rgba[3] = opacity
        mat.diffuse_color = tuple(rgba)
    except Exception:
        pass
    mat['fbp_opacity'] = opacity

    if bool(mat.get('fbp_holdout_material', False)):
        return True

    if bool(mat.get('fbp_gradient_material', False)):
        ramp = find_fbp_gradient_ramp_node(mat)
        shader = fbp_find_node_by_type(nodes, 'EMISSION') or fbp_find_node_by_type(nodes, 'BSDF_PRINCIPLED')
        mix = fbp_find_node_by_type(nodes, 'MIX_SHADER')
        if not ramp or not shader or not mix:
            return False
        opacity_node = nodes.get('FBP_Opacity')
        if not opacity_node or opacity_node.type != 'MATH':
            opacity_node = nodes.new(type='ShaderNodeMath')
            opacity_node.name = 'FBP_Opacity'
            opacity_node.location = (570, -60)
            opacity_node.operation = 'MULTIPLY'
        opacity_node.inputs[1].default_value = opacity
        fbp_relink_node_input(links, opacity_node.inputs[0], ramp.outputs['Alpha'])
        fbp_relink_node_input(links, mix.inputs[0], opacity_node.outputs['Value'])
        alpha_sock = safe_get_socket(shader, ['alpha'])
        if alpha_sock:
            fbp_relink_node_input(links, alpha_sock, opacity_node.outputs['Value'])
        return True

    if bool(mat.get('fbp_color_material', False)):
        color = list(fbp_material_color_value(mat, (1.0, 1.0, 1.0, 1.0)))
        color[3] = opacity
        mat['fbp_color_value'] = tuple(color)
        shader = fbp_find_node_by_type(nodes, 'EMISSION') or fbp_find_node_by_type(nodes, 'BSDF_PRINCIPLED')
        mix = fbp_find_node_by_type(nodes, 'MIX_SHADER')
        transparent = fbp_find_node_by_type(nodes, 'BSDF_TRANSPARENT')
        out = fbp_find_node_by_type(nodes, 'OUTPUT_MATERIAL')
        if shader:
            color_sock = safe_get_socket(shader, ['color']) or shader.inputs[0]
            try:
                color_sock.default_value = tuple(color)
            except Exception:
                pass
            alpha_sock = safe_get_socket(shader, ['alpha'])
            if alpha_sock:
                try:
                    alpha_sock.default_value = opacity
                except Exception:
                    pass
        if fbp_find_node_by_type(nodes, 'EMISSION'):
            if mix and transparent and out:
                try:
                    mix.inputs[0].default_value = opacity
                except Exception:
                    pass
            elif opacity < 0.999 and shader and out:
                transparent = nodes.new(type='ShaderNodeBsdfTransparent')
                transparent.location = (0, -140)
                mix = nodes.new(type='ShaderNodeMixShader')
                mix.location = (180, 0)
                mix.inputs[0].default_value = opacity
                try:
                    while out.inputs[0].links:
                        links.remove(out.inputs[0].links[0])
                except Exception:
                    pass
                links.new(transparent.outputs[0], mix.inputs[1])
                links.new(shader.outputs[0], mix.inputs[2])
                links.new(mix.outputs[0], out.inputs[0])
        return True

    return False


def fbp_rebuild_procedural_material_for_emission(mat, rig, use_emission):
    if not mat:
        return None
    opacity = max(0.0, min(1.0, float(getattr(rig, 'fbp_opacity', 1.0))))
    if bool(mat.get('fbp_holdout_material', False)):
        return create_fbp_color_material(mat.name, (0.0, 0.0, 0.0, 1.0), use_emission, True)
    if bool(mat.get('fbp_gradient_material', False)):
        new_mat = create_fbp_gradient_material(
            mat.name,
            str(mat.get('fbp_gradient_mode', getattr(rig, 'fbp_gradient_mode', 'LINEAR'))),
            str(mat.get('fbp_gradient_kind', getattr(rig, 'fbp_gradient_kind', 'COLOR'))),
            tuple(getattr(rig, 'fbp_gradient_color_a', (0,0,0,0))),
            tuple(getattr(rig, 'fbp_gradient_color_b', (0,0,0,1))),
            bool(mat.get('fbp_gradient_reverse', getattr(rig, 'fbp_gradient_reverse', True))),
            bool(use_emission),
        )
        copy_color_ramp(find_fbp_gradient_ramp_node(mat), find_fbp_gradient_ramp_node(new_mat))
        apply_fbp_gradient_mapping_to_material(rig, new_mat)
        update_fbp_procedural_material_opacity(new_mat, opacity)
        return new_mat
    if bool(mat.get('fbp_color_material', False)):
        color = list(fbp_material_color_value(mat, (1.0,1.0,1.0,1.0)))
        color[3] = opacity
        return create_fbp_color_material(mat.name, tuple(color), bool(use_emission), False)
    return mat


def fbp_wiggle_channels_for_rig(rig):
    if getattr(rig, 'fbp_is_vertical', False):
        return (0, 2), 1
    return (0, 1), 2


def fbp_action_fcurves_for_datablock(obj):
    """Return this object's F-Curves on Blender 5.x slotted Actions and legacy Actions."""
    ad = getattr(obj, 'animation_data', None)
    action = getattr(ad, 'action', None) if ad else None
    if not action:
        return []
    try:
        if hasattr(action, 'fcurves'):
            return list(action.fcurves)
    except Exception:
        pass
    try:
        from bpy_extras import anim_utils
        slot = getattr(ad, 'action_slot', None)
        if slot:
            channelbag = anim_utils.action_get_channelbag_for_slot(action, slot)
            if channelbag and hasattr(channelbag, 'fcurves'):
                return list(channelbag.fcurves)
    except Exception:
        pass
    try:
        # Low-level fallback for Blender versions that expose layers/strips/channelbags directly.
        slot = getattr(ad, 'action_slot', None)
        for layer in getattr(action, 'layers', []):
            for strip in getattr(layer, 'strips', []):
                channelbag = None
                if slot and hasattr(strip, 'channelbag'):
                    try:
                        channelbag = strip.channelbag(slot)
                    except Exception:
                        channelbag = None
                if not channelbag and hasattr(strip, 'channelbags'):
                    try:
                        channelbag = strip.channelbags[0]
                    except Exception:
                        channelbag = None
                if channelbag and hasattr(channelbag, 'fcurves'):
                    return list(channelbag.fcurves)
    except Exception:
        pass
    return []


def fbp_get_existing_fcurve(obj, data_path, index):
    for fcurve in fbp_action_fcurves_for_datablock(obj):
        try:
            if fcurve.data_path == data_path and int(fcurve.array_index) == int(index):
                return fcurve
        except Exception:
            continue
    return None


def fbp_remove_wiggle_modifiers(rig):
    removed = 0
    for fcurve in fbp_action_fcurves_for_datablock(rig):
        try:
            for mod in list(fcurve.modifiers):
                if getattr(mod, 'name', '') == 'FBP_Wiggle':
                    fcurve.modifiers.remove(mod)
                    removed += 1
        except Exception:
            continue
    return removed


def fbp_ensure_fcurve(obj, data_path, index, frame):
    if not obj.animation_data:
        obj.animation_data_create()
    if not obj.animation_data.action:
        obj.animation_data.action = bpy.data.actions.new(name=f"FBP_Wiggle_{obj.name}")
    action = obj.animation_data.action

    # Blender 5.x: Action.fcurves is gone; use the slotted-action helper.
    if hasattr(action, "fcurve_ensure_for_datablock"):
        try:
            fcurve = action.fcurve_ensure_for_datablock(
                datablock=obj,
                data_path=data_path,
                index=index,
                group_name="Frame by Plane Wiggle",
            )
        except TypeError:
            fcurve = action.fcurve_ensure_for_datablock(
                datablock=obj,
                data_path=data_path,
                index=index,
            )
        try:
            if not fcurve.keyframe_points:
                obj.keyframe_insert(data_path=data_path, index=index, frame=frame)
                fcurve = action.fcurve_ensure_for_datablock(
                    datablock=obj,
                    data_path=data_path,
                    index=index,
                )
        except Exception:
            pass
        return fcurve

    # Legacy Blender fallback.
    fcurve = None
    try:
        fcurve = action.fcurves.find(data_path, index=index)
    except Exception:
        fcurve = None
    if not fcurve:
        try:
            obj.keyframe_insert(data_path=data_path, index=index, frame=frame)
            fcurve = action.fcurves.find(data_path, index=index)
        except Exception:
            try:
                fcurve = action.fcurves.new(data_path=data_path, index=index)
            except Exception:
                fcurve = None
    return fcurve


def fbp_apply_wiggle_to_rig(rig, scene=None):
    if not rig:
        return False
    scene = scene or bpy.context.scene
    fbp_remove_wiggle_modifiers(rig)
    if not getattr(rig, 'fbp_wiggle_enabled', False):
        return True
    pos_axes, rot_axis = fbp_wiggle_channels_for_rig(rig)
    scale = max(0.01, float(getattr(rig, 'fbp_wiggle_scale', 18.0)))
    phase = float(getattr(rig, 'fbp_wiggle_phase', 0.0))
    use_range = bool(getattr(rig, 'fbp_wiggle_use_range', False))
    frame_start = int(getattr(rig, 'fbp_wiggle_frame_start', scene.frame_start if scene else 1))
    frame_end = int(getattr(rig, 'fbp_wiggle_frame_end', scene.frame_end if scene else 250))
    blend_in = float(getattr(rig, 'fbp_wiggle_blend_in', 12.0))
    blend_out = float(getattr(rig, 'fbp_wiggle_blend_out', 12.0))

    def apply_noise(fcurve, strength):
        mod = fcurve.modifiers.new('NOISE')
        mod.name = 'FBP_Wiggle'
        mod.strength = strength
        mod.scale = scale
        mod.phase = phase
        if use_range:
            try:
                mod.use_restricted_range = True
                mod.frame_start = frame_start
                mod.frame_end = frame_end
                mod.blend_in = blend_in
                mod.blend_out = blend_out
            except Exception:
                pass
        return mod

    current_frame = scene.frame_current if scene else 1
    if bool(getattr(rig, 'fbp_wiggle_position', True)):
        pos_strength = float(getattr(rig, 'fbp_wiggle_pos_strength', 0.08))
        for axis in pos_axes:
            fc = fbp_ensure_fcurve(rig, 'location', axis, current_frame)
            if fc:
                apply_noise(fc, pos_strength)
    if bool(getattr(rig, 'fbp_wiggle_rotation', False)):
        rot_strength = math.radians(float(getattr(rig, 'fbp_wiggle_rot_strength', 3.0)))
        fc = fbp_ensure_fcurve(rig, 'rotation_euler', rot_axis, current_frame)
        if fc:
            apply_noise(fc, rot_strength)
    return True


# ── RIG BUILDER ───────────────────────────────────────────────────────────────

def build_fbp_rig(context, rig_name, directory, files_list, location, color_tag='COLOR_01', target_collection=None, color_variant_index=0):
    sc = context.scene
    target_collection = target_collection or getattr(context, 'collection', None) or sc.collection

    rig_mesh = fbp_create_rect_mesh("Mesh_" + rig_name + "_Rig", size=2.1, with_face=False)
    rig = fbp_create_mesh_object(rig_name, rig_mesh, context, location=location, target_collection=target_collection)
    rig.display_type = 'WIRE'
    rig.is_fbp_control = True
    rig.fbp_global_duration = sc.fbp_pre_duration
    rig.fbp_use_emission = sc.fbp_pre_shadeless
    rig.fbp_loop_mode = sc.fbp_pre_loop_mode
    rig.fbp_interpolation = sc.fbp_pre_interpolation
    rig.fbp_color_tag = color_tag
    rig.fbp_color_variant_index = color_variant_index
    if target_collection:
        rig.fbp_collection_name = target_collection.name
        set_collection_color_tag(target_collection, color_tag)
    apply_collection_color_to_rig(rig, color_tag, color_variant_index, push_collection=False)
    rig.hide_render = True

    if sc.fbp_pre_orientation == 'VERT':
        rig.rotation_euler[0] = math.radians(90)
        rig.fbp_is_vertical = True

    plane_mesh = fbp_create_rect_mesh("Mesh_Plane_" + rig_name, size=2.0, with_face=True)
    plane = fbp_create_mesh_object("Plane_" + rig_name, plane_mesh, context, location=location, target_collection=target_collection)
    plane.is_fbp_plane = True
    plane["fbp_parent_rig_name"] = rig.name
    plane.parent = rig
    plane.location = (0, 0, 0)
    plane.rotation_euler = (0, 0, 0)
    plane.hide_select = True
    rig.fbp_plane_target = plane
    if target_collection:
        plane.fbp_collection_name = target_collection.name

    first_img = None
    for f in files_list:
        img_path = os.path.join(directory, f)
        mat = create_fbp_material(
            f"Mat_{f}", img_path,
            interp=rig.fbp_interpolation,
            opacity=rig.fbp_opacity,
            use_emission=rig.fbp_use_emission)
        plane.data.materials.append(mat)
        item = rig.fbp_images.add()
        item.name = f
        item.duration = rig.fbp_global_duration
        item.is_selected = True
        item.is_empty = False
        item.filepath = img_path
        if not first_img:
            try:
                first_img = bpy.data.images.load(img_path, check_existing=True)
            except Exception:
                pass

    if first_img:
        width, height = first_img.size
        if width > 0 and height > 0:
            if width > height:
                rig.scale = (1, height / width, 1)
            else:
                rig.scale = (width / height, 1, 1)
            rig.fbp_base_scale = rig.scale.x
            rig.fbp_base_scale_vec = rig.scale
            rig.fbp_preview_path = first_img.filepath

    apply_collection_color_to_rig(rig, color_tag, color_variant_index, push_collection=False)
    if fbp_fast_import_is_active():
        fbp_fast_import_queue_rig(rig)
        do_update_emission(rig)
    else:
        context.view_layer.objects.active = rig
        do_update_animation(rig)
        do_update_emission(rig)
        sync_layer_collection(context)
    return rig


# ── UI LISTS ──────────────────────────────────────────────────────────────────

class FBP_UL_LayerStack(UIList):
    def filter_items(self, context, data, propname):
        objs = getattr(data, propname)
        flt_flags = []
        flt_neworder = list(range(len(objs)))
        if getattr(context.scene, 'fbp_sort_layers_alpha', False):
            flt_neworder.sort(key=lambda i: natural_sort_key(getattr(getattr(objs[i], 'obj', None), 'name', '')))
        else:
            flt_neworder.sort(key=lambda i: (fbp_layer_depth_value(context, getattr(objs[i], 'obj', None)), natural_sort_key(getattr(getattr(objs[i], 'obj', None), 'name', ''))), reverse=True)
        filter_collection = getattr(context.scene, 'fbp_layer_filter_collection', '')
        for item in objs:
            visible = is_layer_item_visible_in_collections(context, item)
            if visible and filter_collection:
                try:
                    visible = bool(item.obj and getattr(get_primary_fbp_collection(item.obj), 'name', '') == filter_collection)
                except Exception:
                    visible = False
            flt_flags.append(self.bitflag_filter_item if visible else 0)
        return flt_flags, flt_neworder

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        try:
            rig = item.obj
            if not rig or not is_fbp_layer_object(rig):
                layout.label(text="<Deleted Layer>")
                return

            row = layout.row(align=True)
            if context.scene.fbp_show_previews:
                preview = get_layer_thumbnail(rig)
                if preview:
                    row.template_icon(icon_value=preview.icon_id, scale=1.0)
                else:
                    row.label(text="", icon=fbp_strip_icon(rig.fbp_color_tag))
            else:
                row.label(text="", icon=fbp_strip_icon(rig.fbp_color_tag))

            op_name = row.operator("fbp.select_layer_exclusive", text=rig.name, emboss=False)
            op_name.rig_name = rig.name
            row.separator()
            row.label(text=f"F.{len(rig.fbp_images)}")

            solo_icon=fbp_icon("OUTLINER_OB_LIGHT") if item.solo_view else 'LIGHT'
            row.prop(item, "solo_view", text="", icon=solo_icon, emboss=False)
            sel_icon=fbp_icon("CHECKBOX_HLT") if item.selected else 'CHECKBOX_DEHLT'
            row.prop(item, "selected", text="", icon=sel_icon, emboss=False)
            hold_icon = fbp_mask_icon(item.holdout)
            row.prop(item, "holdout", text="", icon=hold_icon, emboss=False)
            vis_icon=fbp_icon("HIDE_OFF") if rig.fbp_is_visible else 'HIDE_ON'
            row.prop(rig, "fbp_is_visible", text="", icon=vis_icon, icon_only=True, emboss=False)
            lock_icon=fbp_icon("LOCKED") if item.rig_locked else 'UNLOCKED'
            row.prop(item, "rig_locked", text="", icon=lock_icon, emboss=False)

        except ReferenceError:
            layout.label(text="<Deleted Layer>")


class FBP_UL_ImageList(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        rig = data
        plane = getattr(rig, "fbp_plane_target", None)
        custom_icon=fbp_icon("IMAGE_DATA")
        is_missing = False

        is_empty = bool(getattr(item, "is_empty", False))
        if getattr(rig, "fbp_is_color_plane", False):
            custom_icon = fbp_color_plane_type_icon(rig) or fbp_icon("TEXTURE_DATA")
        elif is_empty:
            custom_icon=fbp_icon("TEXTURE_DATA")

        if plane and index < len(plane.data.materials) and not is_empty:
            try:
                mat = plane.data.materials[index]
                if is_fbp_empty_material(mat):
                    custom_icon=fbp_icon("TEXTURE_DATA")
                    is_empty = True
                elif mat and mat.use_nodes:
                    for node in mat.node_tree.nodes:
                        if node.type == 'TEX_IMAGE' and node.image:
                            img_path = node.image.filepath
                            if img_path and not os.path.exists(bpy.path.abspath(img_path)):
                                is_missing = True
                            if context.scene.fbp_show_previews:
                                thumb = load_preview(node.image.filepath)
                                if thumb:
                                    custom_icon = thumb.icon_id
                            break
            except Exception:
                pass

        eval_idx = get_eval_mat_index(rig, context.scene.frame_current)
        row = layout.row(align=True)
        split = row.split(factor=0.70)
        left = split.row(align=True)

        if index == eval_idx:
            row.alert = True
            left.label(text="", icon=fbp_icon("RECORD_ON"))
        else:
            left.label(text="", icon=fbp_icon("DOT"))

        if is_missing:
            left.label(text="", icon=fbp_icon("ERROR"))

        display_name = item.name if not is_empty else "Transparent Frame"
        op_text = f"{index + 1} - ({display_name})"
        if isinstance(custom_icon, int):
            op = left.operator("fbp.select_image_exclusive", text=op_text, icon_value=custom_icon, emboss=False)
        else:
            op = left.operator("fbp.select_image_exclusive", text=op_text, icon=custom_icon, emboss=False)
        op.rig_name = rig.name
        op.index = index

        right = split.row(align=False)
        compact = right.row(align=False)
        compact.prop(item, "duration", text="")
        right.prop(item, "is_selected", text="")


class FBP_UL_PendingList(UIList):
    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        filter_collection = getattr(context.scene, 'fbp_pending_filter_collection', '')
        flags = []
        order = list(range(len(items)))
        if getattr(context.scene, 'fbp_sort_layers_alpha', False):
            order.sort(key=lambda i: natural_sort_key(getattr(items[i], 'name', '')))
        for item in items:
            coll_name = getattr(item, 'collection_name', '') or 'Unsorted'
            flags.append(self.bitflag_filter_item if (not filter_collection or coll_name == filter_collection) else 0)
        return flags, order

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        split = layout.split(factor=0.03, align=True)
        split.label(text=f"{index + 1}")
        row = split.row(align=True)
        row.prop(item, "fbp_color_tag", text="", icon_only=True)
        row.separator()
        if item.collection_name:
            row.label(text=item.collection_name, icon=fbp_icon("OUTLINER_COLLECTION"))
        row.prop(item, "name", text="", emboss=True)
        folder_icon=fbp_icon("NEWFOLDER") if not item.files_str else 'FOLDER_REDIRECT'
        op = row.operator("fbp.edit_pending_plane", icon=folder_icon, text="")
        op.index = index




def rig_holdout_is_active(rig):
    """Return True when a rig currently uses Frame by Plane holdout materials."""
    try:
        return bool(rig and rig.get("fbp_holdout_original_materials", ""))
    except Exception:
        return False


def pending_items_for_collection(scene, collection_name):
    """Return pending setup rows that belong to a named setup collection."""
    target = collection_name or 'Unsorted'
    items = []
    for index, item in enumerate(scene.fbp_pending_planes):
        name = getattr(item, 'collection_name', '') or 'Unsorted'
        if name == target:
            items.append((index, item))
    if getattr(scene, 'fbp_sort_layers_alpha', False):
        items.sort(key=lambda pair: natural_sort_key(getattr(pair[1], 'name', '')))
    return items


def draw_pending_plane_row(layout, context, item, index):
    """Draw one Multiplane Setup row without relying on template_list filters."""
    row = layout.row(align=True)
    row.label(text=f"{index + 1}", icon=fbp_icon("BLANK1"))
    row.prop(item, "fbp_color_tag", text="", icon_only=True)
    row.prop(item, "name", text="")
    file_count = 0
    try:
        file_count = len([f for f in item.files_str.split('|') if f])
    except Exception:
        file_count = 0
    row.label(text=f"{file_count}f", icon=fbp_icon("FILE_IMAGE"))
    op = row.operator("fbp.edit_pending_plane", icon=fbp_icon("FOLDER_REDIRECT"), text="")
    op.index = index
    rem = row.operator("fbp.remove_pending_plane_at_index", icon=fbp_icon("TRASH"), text="")
    rem.index = index

# ── UI HELPERS ────────────────────────────────────────────────────────────────

def draw_layer_list_side_buttons(layout):
    col = layout.column(align=True)
    col.operator("fbp.move_layer_stack", text="", icon=fbp_icon("SORT_DESC")).direction = 'DOWN'
    col.operator("fbp.move_layer_stack", text="", icon=fbp_icon("SORT_ASC")).direction = 'UP'
    col.separator()
    col.operator("fbp.open_create_rig", text="", icon=fbp_icon("ADD"))
    col.operator("fbp.popup_color_plane", text="", icon=fbp_icon("IMAGE"))
    col.separator()
    col.operator("fbp.duplicate_selected_layers", text="", icon=fbp_icon("DUPLICATE"))
    col.operator("fbp.delete_sequence", text="", icon=fbp_icon("TRASH"))
    col.separator()
    col.operator("fbp.select_all_layers", text="", icon=fbp_icon("RESTRICT_SELECT_OFF"))
    return col


def draw_collection_layer_list(layout, context, collection, depth=0):
    if not collection_has_fbp_content(collection, True):
        return
    hidden = collection_is_hidden_in_view_layer(context, collection)
    collapsed = bool(getattr(collection, 'fbp_collapsed', True))

    box = layout.box()
    row = box.row(align=True)
    indent_row(row, depth)

    fold_icon=fbp_icon("RIGHTARROW") if collapsed else 'DOWNARROW_HLT'
    op = row.operator("fbp.toggle_collection_collapse", text="", icon=fold_icon, emboss=False)
    op.collection_name = collection.name

    # Same visual order as layer rows: Eye - tag - name/count - bulb - mask - select image/planes - lock - select rigs.
    row.prop(collection, "fbp_collection_visible", text="", icon=(fbp_icon("HIDE_OFF") if collection.fbp_collection_visible else fbp_icon("HIDE_ON")), emboss=False)
    if hasattr(collection, 'color_tag'):
        row.prop(collection, 'color_tag', text="", icon_only=True)
    else:
        row.label(text="", icon=fbp_icon("OUTLINER_COLLECTION"))

    op_sel = row.operator("fbp.select_collection_layers", text=collection.name, icon=(fbp_icon("HIDE_ON") if hidden else fbp_icon("BLANK1")), emboss=False)
    op_sel.collection_name = collection.name
    total_layers = sum(1 for _ in iter_fbp_rigs_in_collection(collection, True))
    row.label(text=str(total_layers))

    row.prop(collection, "fbp_collection_solo", text="", icon=(fbp_icon("OUTLINER_OB_LIGHT") if collection.fbp_collection_solo else fbp_icon("LIGHT")), emboss=False)
    row.prop(collection, "fbp_collection_holdout", text="", icon=fbp_mask_icon(collection.fbp_collection_holdout), emboss=False)
    op_planes = row.operator("fbp.select_collection_planes", text="", icon=fbp_collection_plane_icon(collection, context), emboss=False)
    op_planes.collection_name = collection.name
    row.prop(collection, "fbp_collection_locked", text="", icon=(fbp_icon("LOCKED") if collection.fbp_collection_locked else fbp_icon("UNLOCKED")), emboss=False)
    op_rigs = row.operator("fbp.select_collection_layers", text="", icon=fbp_collection_select_icon(collection, context), emboss=False)
    op_rigs.collection_name = collection.name

    if collapsed:
        return

    direct_rigs = sort_rigs_for_layer_view(context, get_direct_fbp_rigs_in_collection(context, collection))
    max_rows = max(1, int(getattr(context.scene, 'fbp_layer_list_rows', 12)))
    if direct_rigs:
        layer_col = box.column(align=True)
        for rig in direct_rigs[:max_rows]:
            draw_fbp_layer_row(layer_col, context, rig, depth=0)
        hidden_count = max(0, len(direct_rigs) - max_rows)
    else:
        box.label(text="No direct layers in this collection", icon=fbp_icon("INFO"))

    for child in get_child_fbp_collections(collection):
        draw_collection_layer_list(box, context, child, depth + 1)

def draw_pending_setup_grouped(layout, context):
    sc = context.scene
    names = pending_collection_names(sc)
    if not names:
        layout.label(text="No layers in setup", icon=fbp_icon("INFO"))
        return
    for name in names:
        items = pending_items_for_collection(sc, name)
        count = len(items)
        box = layout.box()
        row = box.row(align=True)
        is_open = pending_collection_is_open(sc, name)
        op = row.operator("fbp.toggle_pending_collection_collapse", text="", icon=(fbp_icon("DOWNARROW_HLT") if is_open else fbp_icon("RIGHTARROW")), emboss=False)
        op.collection_name = name
        row.label(text=name, icon=fbp_icon("OUTLINER_COLLECTION"))
        row.label(text=str(count))
        # A collection color tag is assigned through the first row by default; it will be propagated on generate.
        if items:
            row.prop(items[0][1], "fbp_color_tag", text="", icon_only=True)
        if not is_open:
            continue
        for index, item in items:
            draw_pending_plane_row(box, context, item, index)
        tools = box.row(align=True)
        add = tools.operator("fbp.add_pending_plane", icon=fbp_icon("ADD"), text="Add Layer")
        tools.operator("fbp.add_pending_collection", icon=fbp_icon("OUTLINER_COLLECTION"), text="New Collection")
        tools.operator("fbp.remove_pending_plane", icon=fbp_icon("REMOVE"), text="Remove Active")

def draw_fbp_gradient_controls(layout, owner):
    """Compatibility wrapper: only show the native Advanced ColorRamp."""
    if isinstance(owner, bpy.types.Scene):
        draw_scene_fbp_color_ramp(layout, owner)
    else:
        draw_native_fbp_color_ramp(layout, owner)


def get_fbp_gradient_material_from_rig(rig):
    """Return the editable gradient material assigned to the selected FBP rig, if any."""
    if not rig or not getattr(rig, 'fbp_is_color_plane', False):
        return None
    plane = getattr(rig, 'fbp_plane_target', None)
    if not plane or not getattr(plane, 'data', None) or not getattr(plane.data, 'materials', None):
        return None
    mat = fbp_get_active_frame_material(rig)
    if mat and getattr(mat, 'use_nodes', False) and mat.get('fbp_gradient_material'):
        return mat
    return None


def find_fbp_gradient_ramp_node(mat):
    """Find the real ColorRamp node used by a Frame by Plane gradient material."""
    if not mat or not getattr(mat, 'node_tree', None):
        return None
    nodes = mat.node_tree.nodes
    node = nodes.get('FBP_ColorRamp')
    if node and node.type == 'VALTORGB':
        return node
    for candidate in nodes:
        if candidate.type == 'VALTORGB' and candidate.get('fbp_gradient_ramp'):
            return candidate
    for candidate in nodes:
        if candidate.type == 'VALTORGB' and candidate.label == 'Frame by Plane Color Ramp':
            return candidate
    for candidate in nodes:
        if candidate.type == 'VALTORGB':
            return candidate
    return None



def get_fbp_gradient_mapping_node(mat):
    """Find the Mapping node used to transform Frame by Plane gradient planes."""
    if not mat or not getattr(mat, 'node_tree', None):
        return None
    node = mat.node_tree.nodes.get('FBP_GradientMapping')
    if node and node.type == 'MAPPING':
        return node
    for candidate in mat.node_tree.nodes:
        if candidate.type == 'MAPPING' and candidate.get('fbp_gradient_mapping'):
            return candidate
    return None


def get_fbp_gradient_center_node(mat):
    """Find the Vector Math node that stores the editable gradient pivot."""
    if not mat or not getattr(mat, 'use_nodes', False):
        return None
    node = mat.node_tree.nodes.get('FBP_GradientCenter')
    if node:
        return node
    for candidate in mat.node_tree.nodes:
        if candidate.type == 'VECT_MATH' and candidate.get('fbp_gradient_center'):
            return candidate
    return None


def get_fbp_gradient_recenter_node(mat):
    """Find the optional node that moves linear gradients back to UV space."""
    if not mat or not getattr(mat, 'use_nodes', False):
        return None
    node = mat.node_tree.nodes.get('FBP_GradientRecenter')
    if node:
        return node
    for candidate in mat.node_tree.nodes:
        if candidate.type == 'VECT_MATH' and candidate.get('fbp_gradient_recenter'):
            return candidate
    return None


def update_fbp_gradient_viewport_color(rig, mat=None):
    """Keep Solid View readable by updating the flat viewport color from the ramp.

    Blender Solid View does not evaluate procedural ColorRamp shader nodes. This
    keeps the material/object viewport color close to the visible end color so the
    plane remains recognizable in Solid mode, while the real gradient stays visible
    in Material Preview and Rendered modes.
    """
    mat = mat or get_fbp_gradient_material_from_rig(rig)
    ramp = find_fbp_gradient_ramp_node(mat) if mat else None
    if not mat or not ramp:
        return
    try:
        elems = ramp.color_ramp.elements
        color = tuple(elems[-1].color) if elems else tuple(getattr(rig, 'fbp_gradient_color_b', (0.058823529411764705, 0.12941176470588237, 0.24313725490196078, 1.0)))
        mat.diffuse_color = color
        plane = getattr(rig, 'fbp_plane_target', None)
        if plane:
            plane.color = color
        if rig:
            rig.color = color
    except Exception as exc:
        fbp_warn("Could not update gradient Solid View fallback color", exc)


def apply_fbp_gradient_mapping_to_material(rig, mat=None):
    """Apply selected rig gradient transform controls to the real material nodes."""
    if not rig:
        return
    mat = mat or get_fbp_gradient_material_from_rig(rig)
    mapping = get_fbp_gradient_mapping_node(mat) if mat else None
    if not mapping:
        return
    mode = getattr(rig, 'fbp_gradient_mode', 'LINEAR')
    offset_x = float(getattr(rig, 'fbp_gradient_offset_x', 0.0))
    offset_y = float(getattr(rig, 'fbp_gradient_offset_y', 0.0))
    scale_x = max(0.001, float(getattr(rig, 'fbp_gradient_scale_x', 1.0)))
    scale_y = max(0.001, float(getattr(rig, 'fbp_gradient_scale_y', 1.0)))
    rotation = math.radians(float(getattr(rig, 'fbp_gradient_rotation', 0.0)))

    center = get_fbp_gradient_center_node(mat)
    if center:
        # Positive offset moves the visual center in the same direction on the plane.
        center.inputs[1].default_value[0] = 0.5 + offset_x
        center.inputs[1].default_value[1] = 0.5 + offset_y
        center.inputs[1].default_value[2] = 0.0
        mapping.inputs['Location'].default_value[0] = 0.0
        mapping.inputs['Location'].default_value[1] = 0.0
        mapping.inputs['Location'].default_value[2] = 0.0
    else:
        # Fallback for gradients created by older builds.
        mapping.inputs['Location'].default_value[0] = (-0.5 - offset_x) if mode == 'CENTER' else -offset_x
        mapping.inputs['Location'].default_value[1] = (-0.5 - offset_y) if mode == 'CENTER' else -offset_y
        mapping.inputs['Location'].default_value[2] = 0.0

    # Radial gradients use coordinates centered around zero; scaling by 2 maps
    # the distance from center to plane edge to roughly the full ColorRamp range.
    if mode == 'CENTER':
        mapping.inputs['Scale'].default_value[0] = 2.0 / scale_x
        mapping.inputs['Scale'].default_value[1] = 2.0 / scale_y
    else:
        mapping.inputs['Scale'].default_value[0] = 1.0 / scale_x
        mapping.inputs['Scale'].default_value[1] = 1.0 / scale_y
    mapping.inputs['Scale'].default_value[2] = 1.0
    mapping.inputs['Rotation'].default_value[0] = 0.0
    mapping.inputs['Rotation'].default_value[1] = 0.0
    mapping.inputs['Rotation'].default_value[2] = rotation
    update_fbp_gradient_viewport_color(rig, mat)


def update_gradient_mapping_cb(self, context):
    try:
        if bool(self.get("_fbp_syncing_frame_material", False)):
            return
        apply_fbp_gradient_mapping_to_material(self)
    except Exception as exc:
        fbp_warn("Could not update gradient transform", exc)


def get_fbp_gradient_preview_material(scene):
    """Return the hidden preview material used by the creation ColorRamp without creating data-blocks.

    Blender may call UI draw methods in a read-only context, so data-block creation must
    happen in an operator/invoke/execute step, not while drawing a panel or popup.
    """
    mat_name = scene.get('fbp_gradient_preview_material_name', '') if scene else ''
    mat = bpy.data.materials.get(mat_name) if mat_name else None
    if mat and bool(mat.get('fbp_gradient_preview_material')):
        return mat
    return None


def get_or_create_fbp_gradient_preview_material(scene):
    """Create/reuse the hidden material that exposes Blender's native ColorRamp in creation popups."""
    mode = getattr(scene, 'fbp_gradient_mode', 'LINEAR')
    kind = getattr(scene, 'fbp_gradient_kind', 'COLOR')
    color_a = tuple(getattr(scene, 'fbp_gradient_color_a', (1.0, 0.3686274509803922, 0.596078431372549, 1.0)))
    color_b = tuple(getattr(scene, 'fbp_gradient_color_b', (0.058823529411764705, 0.12941176470588237, 0.24313725490196078, 1.0)))
    reverse = bool(getattr(scene, 'fbp_gradient_reverse', False))
    use_emission = bool(getattr(scene, 'fbp_color_plane_emission', True))

    mat = get_fbp_gradient_preview_material(scene)
    needs_rebuild = mat is None
    if mat is not None:
        try:
            needs_rebuild = (
                mat.get('fbp_gradient_mode') != mode or
                mat.get('fbp_gradient_kind') != kind or
                bool(mat.get('fbp_gradient_reverse', False)) != reverse or
                bool(mat.get('fbp_use_emission', use_emission)) != use_emission
            )
        except Exception:
            needs_rebuild = True

    ramp_data = fbp_capture_color_ramp_data(find_fbp_gradient_ramp_node(mat)) if mat else None
    mat_name = mat.name if mat else "FBP_Gradient_Creation_Preview"
    if needs_rebuild:
        mat = create_fbp_gradient_material(mat_name, mode, kind, color_a, color_b, reverse, use_emission)
        mat.use_fake_user = True
        mat['fbp_gradient_preview_material'] = True
        if scene is not None:
            scene['fbp_gradient_preview_material_name'] = mat.name
        if ramp_data:
            fbp_restore_color_ramp_data(ramp_data, find_fbp_gradient_ramp_node(mat))

    fbp_apply_gradient_kind_to_ramp_node(find_fbp_gradient_ramp_node(mat), kind)
    return mat


def fbp_update_scene_gradient_preview_material(scene):
    mat = get_or_create_fbp_gradient_preview_material(scene)
    fbp_apply_gradient_kind_to_ramp_node(find_fbp_gradient_ramp_node(mat), getattr(scene, 'fbp_gradient_kind', 'COLOR'))
    return mat


def fbp_capture_color_ramp_data(ramp_node):
    """Store ColorRamp values before rebuilding nodes/materials."""
    if not ramp_node:
        return None
    try:
        ramp = ramp_node.color_ramp
        return {
            "interpolation": ramp.interpolation,
            "elements": [(float(el.position), tuple(el.color)) for el in ramp.elements],
        }
    except Exception as exc:
        fbp_warn("Could not capture ColorRamp data", exc)
        return None


def fbp_restore_color_ramp_data(data, target_node):
    """Restore ColorRamp values after rebuilding nodes/materials."""
    if not data or not target_node:
        return False
    try:
        ramp = target_node.color_ramp
        ramp.interpolation = data.get("interpolation", ramp.interpolation)
        elements = list(data.get("elements", []))
        if not elements:
            return False
        while len(ramp.elements) > 2:
            ramp.elements.remove(ramp.elements[-1])
        while len(ramp.elements) < len(elements):
            ramp.elements.new(elements[len(ramp.elements)][0])
        for el, (pos, color) in zip(ramp.elements, elements):
            el.position = max(0.0, min(1.0, float(pos)))
            el.color = tuple(color)
        return True
    except Exception as exc:
        fbp_warn("Could not restore ColorRamp data", exc)
        return False


def fbp_apply_gradient_kind_to_ramp_node(ramp_node, kind):
    """Apply Color-to-Color or Transparent-to-Visible without rebuilding the whole material."""
    if not ramp_node:
        return False
    try:
        ramp = ramp_node.color_ramp
        elements = list(ramp.elements)
        if not elements:
            return False
        kind = (kind or 'ALPHA').upper()
        if kind == 'COLOR':
            for el in elements:
                col = list(el.color)
                col[3] = 1.0
                el.color = tuple(col)
        else:
            if len(elements) == 1:
                col = list(elements[0].color)
                col[3] = 1.0
                elements[0].color = tuple(col)
            else:
                first = list(elements[0].color)
                first[3] = 0.0
                elements[0].color = tuple(first)
                last = list(elements[-1].color)
                last[3] = 1.0
                elements[-1].color = tuple(last)
        return True
    except Exception as exc:
        fbp_warn("Could not apply gradient type to ColorRamp", exc)
        return False


def copy_color_ramp(source_node, target_node):
    """Copy ColorRamp elements and interpolation from one Blender ramp node to another."""
    return fbp_restore_color_ramp_data(fbp_capture_color_ramp_data(source_node), target_node)


def draw_scene_fbp_color_ramp(layout, scene):
    """Draw the native ColorRamp in creation UI by editing a preview material node.

    This function is draw-safe: it never creates or mutates ID data-blocks.
    """
    box = layout.box()
    is_open = bool(getattr(scene, 'fbp_show_gradient_ramp', True))
    row = box.row(align=True)
    row.prop(scene, 'fbp_show_gradient_ramp', text='Color Ramp', icon=(fbp_icon('DOWNARROW_HLT') if is_open else fbp_icon('RIGHTARROW')), emboss=False)
    if not is_open:
        return
    try:
        mat = get_or_create_fbp_gradient_preview_material(scene)
    except Exception as exc:
        fbp_warn("Could not prepare gradient ColorRamp", exc)
        mat = get_fbp_gradient_preview_material(scene)
    ramp_node = find_fbp_gradient_ramp_node(mat) if mat else None
    if not ramp_node:
        box.label(text='No editable ColorRamp found.', icon=fbp_icon('ERROR'))
        return
    box.template_color_ramp(ramp_node, 'color_ramp', expand=True)

def copy_scene_preview_ramp_to_rig(scene, rig):
    """After creating a Gradient Plane, copy the popup/N-Panel creation ramp to the real material."""
    preview = get_or_create_fbp_gradient_preview_material(scene)
    src = find_fbp_gradient_ramp_node(preview) if preview else None
    mat = get_fbp_gradient_material_from_rig(rig)
    dst = find_fbp_gradient_ramp_node(mat) if mat else None
    copy_color_ramp(src, dst)
    apply_fbp_gradient_mapping_to_material(rig, mat)

def draw_native_fbp_color_ramp(layout, rig):
    """Draw Blender's native ColorRamp widget for already-created gradient planes.

    This edits the actual shader node, so colors, stops, interpolation and keyframes
    remain stored directly in the material.
    """
    box = layout.box()
    is_open = bool(getattr(rig, 'fbp_show_gradient_ramp', True))
    row = box.row(align=True)
    row.prop(rig, 'fbp_show_gradient_ramp', text='Color Ramp', icon=(fbp_icon('DOWNARROW_HLT') if is_open else fbp_icon('RIGHTARROW')), emboss=False)
    if not is_open:
        return
    mat = get_fbp_gradient_material_from_rig(rig)
    ramp_node = find_fbp_gradient_ramp_node(mat) if mat else None
    if not ramp_node:
        box.label(text='No editable ColorRamp found on this gradient material.', icon=fbp_icon('ERROR'))
        return
    box.template_color_ramp(ramp_node, 'color_ramp', expand=True)
    box.label(text='Edits the real material node. Add stops, animate colors, or change interpolation here.', icon=fbp_icon('INFO'))
    box.label(text='Tip: Solid View cannot evaluate procedural gradients; use Material Preview/Rendered for the full gradient.', icon=fbp_icon('INFO'))


def fbp_draw_gradient_choice_rows(layout, owner):
    """Draw gradient choices as two stable rows with full-width buttons."""
    row = layout.row(align=True)
    split = row.split(factor=0.5, align=True)
    split.prop_enum(owner, "fbp_gradient_mode", 'LINEAR', text="Linear", icon=fbp_icon("ARROW_LEFTRIGHT"))
    split.prop_enum(owner, "fbp_gradient_mode", 'CENTER', text="Radial", icon=fbp_icon("EMPTY_ARROWS"))
    row = layout.row(align=True)
    split = row.split(factor=0.5, align=True)
    split.prop_enum(owner, "fbp_gradient_kind", 'COLOR', text="Color to Color")
    split.prop_enum(owner, "fbp_gradient_kind", 'ALPHA', text="Transparent to Color")


def fbp_draw_color_plane_color_row(layout, scene):
    row = layout.row(align=False)
    split = row.split(factor=0.62, align=False)
    color_col = split.row(align=True)
    color_col.prop(scene, "fbp_color_plane_color", text="Color")
    preset_col = split.row(align=True)
    preset_col.prop(scene, "fbp_color_plane_preset", text="")


def draw_creation_ui(layout, context):
    sc = context.scene

    row = layout.row(align=False)
    row.scale_y = 1.3
    row.prop(sc, "fbp_creation_mode", expand=True)

    if sc.fbp_creation_mode == 'COLOR':
        box = layout.box()
        box.label(text="Create Color Plane", icon=fbp_icon("MATERIAL"))
        row = box.row(align=False)
        split = row.split(factor=0.78, align=False)
        type_row = split.row(align=True)
        type_row.prop(sc, "fbp_color_plane_type", expand=True)
        emiss = split.row(align=True)
        emiss.enabled = sc.fbp_color_plane_type != 'HOLDOUT'
        emiss.prop(sc, "fbp_color_plane_emission", text="", icon=fbp_icon("LIGHT_SUN"), toggle=True)
        if sc.fbp_color_plane_type == 'CUSTOM':
            fbp_draw_color_plane_color_row(box, sc)
        elif sc.fbp_color_plane_type == 'GRADIENT':
            fbp_draw_gradient_choice_rows(box, sc)
            draw_scene_fbp_color_ramp(box, sc)
            gbox = box.box()
            is_open = bool(getattr(sc, 'fbp_show_gradient_transform', True))
            row = gbox.row(align=True)
            row.prop(sc, 'fbp_show_gradient_transform', text='Position', icon=(fbp_icon('DOWNARROW_HLT') if is_open else fbp_icon('RIGHTARROW')), emboss=False)
            if is_open:
                row = gbox.row(align=True)
                row.prop(sc, "fbp_gradient_offset_x", text="X")
                row.prop(sc, "fbp_gradient_offset_y", text="Y")
                row = gbox.row(align=True)
                row.prop(sc, "fbp_gradient_scale_x", text="Scale X")
                row.prop(sc, "fbp_gradient_scale_y", text="Scale Y")
                gbox.prop(sc, "fbp_gradient_rotation", text="Rotation")
        row = layout.row()
        row.scale_y = 1.2
        row.operator("fbp.create_color_plane", text="Generate Color Plane", icon=fbp_icon("IMAGE"))
        return

    if sc.fbp_creation_mode == 'SINGLE':
        box = layout.box()
        box.label(text="Create Single Plane", icon=fbp_icon("IMAGE_DATA"))
        row = box.row(align=False)
        row.prop(sc, "fbp_pre_duration", text='Frame Duration')
        row.prop(sc, "fbp_pre_shadeless", text="Emission Texture", icon=fbp_icon("LIGHT_SUN"), toggle=True)
        row = box.row(align=True)
        row.prop(sc, "fbp_pre_loop_mode", expand=True)
        box.prop(sc, "fbp_pre_interpolation", expand=False)
        box.prop(sc, "fbp_pre_orientation", expand=False)
        layout.separator()
        row = layout.row()
        row.scale_y = 1.2
        row.operator("fbp.import_sequence", text="Generate Single Plane", icon=fbp_icon("FILE_IMAGE"))
        return

    # MULTI
    box = layout.box()
    box.label(text="Pre-settings", icon=fbp_icon("OPTIONS"))
    row = box.row(align=False)
    row.prop(sc, "fbp_pre_duration", text="Frame Duration")
    row.prop(sc, "fbp_pre_shadeless", text="Emission Texture", icon=fbp_icon("LIGHT_SUN"), toggle=True)
    box.prop(sc, "fbp_pre_loop_mode",     expand=False)
    box.prop(sc, "fbp_pre_interpolation", expand=False)
    box.prop(sc, "fbp_pre_orientation",   expand=False)

    box = layout.box()
    box.label(text="Camera Setup", icon=fbp_icon("RESTRICT_VIEW_ON"))
    row = box.row(align=False)
    cam_icon = fbp_icon("VIEW_CAMERA") if sc.fbp_gen_camera else 'CAMERA_DATA'
    row.prop(sc, "fbp_gen_camera", icon=cam_icon, toggle=True)
    row.prop(sc, "fbp_cam_pivot", text='3D Cursor on Camera', icon=fbp_icon("PIVOT_CURSOR"), toggle=True)
    row = box.row(align=False)
    row.prop(sc, "fbp_layer_offset", text='Plane Distance')
    row.prop(sc, "fbp_auto_scale", text='Fit to Camera', icon=fbp_icon("FULLSCREEN_ENTER"), toggle=True)

    layout.separator()

    if sc.fbp_ui_mode == 'ADVANCED':
        box = layout.box()
        box.label(text="Import Project", icon=fbp_icon("OUTLINER_COLLECTION"))
        box.prop(sc, "fbp_project_path", text="")
        row = box.row(align=True)
        row.scale_y = 1.15
        row.prop(sc, "fbp_import_main_folders_as_scenes", text="Main Folders as Separate Scenes", toggle=True)
        row = box.row(align=True)
        row.operator("fbp.scan_project_to_setup", icon=fbp_icon("IMPORT"), text="Import to Setup")
        row.operator("fbp.auto_scene_builder", icon=fbp_icon("OUTLINER_COLLECTION"), text="Build Direct")

    box = layout.box()
    box.label(text="Multiplane Setup", icon=fbp_icon("RENDERLAYERS"))
    draw_pending_setup_grouped(box, context)

    row = layout.row(align=True)
    row.alignment = 'CENTER'
    row.operator("fbp.add_pending_plane", icon=fbp_icon("ADD"), text="Add Layer")
    row.operator("fbp.add_pending_collection", icon=fbp_icon("OUTLINER_COLLECTION"), text="Create Collection")
    row.operator("fbp.clear_pending_planes", icon=fbp_icon("TRASH"), text="Clear Setup")

    row = layout.row()
    row.scale_y = 1.2
    row.operator("fbp.generate_multiplane", text="Generate Multiplane", icon=fbp_icon("RENDERLAYERS"))


# ── PANELS ────────────────────────────────────────────────────────────────────

class FBP_PT_Settings(Panel):
    bl_label       = "Settings"
    bl_idname      = "FBP_PT_settings"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "Frame by Plane"
    bl_options     = {'DEFAULT_CLOSED'}
    bl_order       = 0

    def draw_header(self, context):
        self.layout.label(text="", icon=fbp_icon("PREFERENCES"))

    def draw(self, context):
        layout = self.layout
        sc = context.scene

        layout.prop(sc, "fbp_ui_mode", expand=True)

        if sc.fbp_ui_mode == 'ADVANCED':
            box = layout.box()
            box.label(text="Project Folder", icon=fbp_icon("FILE_FOLDER"))
            box.prop(sc, "fbp_project_path", text="")
            row = box.row(align=True)
            row.scale_y = 1.15
            row.prop(sc, "fbp_import_main_folders_as_scenes", text="Main Folders as Separate Scenes", toggle=True)
            row = box.row(align=True)
            row.operator("fbp.scan_project_to_setup", icon=fbp_icon("IMPORT"), text="Import Project")
            row.operator("fbp.auto_scene_builder", icon=fbp_icon("OUTLINER_COLLECTION"), text="Build Direct")
            row = box.row(align=True)
            row.prop(sc, "fbp_show_maintenance_tools", text="Maintenance / Diagnostics", icon=(fbp_icon("DOWNARROW_HLT") if sc.fbp_show_maintenance_tools else fbp_icon("RIGHTARROW")), toggle=True)
            if sc.fbp_show_maintenance_tools:
                mbox = box.box()
                row = mbox.row(align=True)
                row.operator("fbp.relink_from_project_root", icon=fbp_icon("LINKED"), text="Relink Missing")
                row.operator("fbp.select_missing_layers", icon=fbp_icon("ERROR"), text="Select Missing")
                row = mbox.row(align=True)
                row.operator("fbp.project_health_check", icon=fbp_icon("CHECKMARK"), text="Health Check")
                row.operator("fbp.show_import_profile", icon=fbp_icon("TIME"), text="Import Report")
                row = mbox.row(align=True)
                row.prop(sc, "fbp_auto_collection_color_variants", text="Color Variants", toggle=True)
                row.prop(sc, "fbp_auto_clean_orphans", text="Auto-clean Orphans", toggle=True)
                render_box = mbox.box()
                render_box.label(text="Emergency Render", icon=fbp_icon("RENDER_ANIMATION"))
                row = render_box.row(align=True)
                row.prop(sc, "fbp_emergency_render_start", text="Start")
                row.prop(sc, "fbp_emergency_render_end", text="End")
                render_box.prop(sc, "fbp_emergency_render_prefix", text="Prefix")
                row = render_box.row(align=True)
                row.operator("fbp.repair_render_state", icon=fbp_icon("MODIFIER"), text="Repair")
                row.operator("fbp.background_render_frames", icon=fbp_icon("RENDER_ANIMATION"), text="Background Render")

        box = layout.box()
        box.label(text="Output Format (Camera)", icon=fbp_icon("SCENE_DATA"))
        box.prop(sc, "fbp_cam_ratio", text="Ratio")
        if sc.fbp_cam_ratio == 'CUSTOM':
            col = box.column(align=True)
            col.prop(sc.render, "resolution_x", text="X (px)")
            col.prop(sc.render, "resolution_y", text="Y (px)")

        row = layout.row(align=True)
        row.prop(sc, "fbp_show_previews", text="Show Thumbnails", toggle=True)
        layout.separator()
        layout.operator("fbp.save_file", text="Save Project", icon=fbp_icon("FILE_TICK"))

        selected_rigs = get_selected_rigs(context)
        if selected_rigs:
            box = layout.box()
            box.label(text="Stats", icon=fbp_icon("INFO"))
            col = box.column(align=False)

            num_images   = sum(len(rig.fbp_images) for rig in selected_rigs)
            total_frames = sum(sum(item.duration for item in rig.fbp_images) for rig in selected_rigs)

            missing_count = 0
            for rig in selected_rigs:
                plane = rig.fbp_plane_target
                if plane:
                    for mat in plane.data.materials:
                        if mat and mat.use_nodes:
                            for node in mat.node_tree.nodes:
                                if node.type == 'TEX_IMAGE' and node.image:
                                    p = node.image.filepath
                                    if p and not os.path.exists(bpy.path.abspath(p)):
                                        missing_count += 1

            if len(selected_rigs) == 1:
                rig   = selected_rigs[0]
                start = rig.fbp_start_frame
                end   = start + total_frames - 1 if total_frames > 0 else start
                col.label(text=f" {num_images} total images")
                col.label(text=f" {total_frames} frames (from {start} to {end})")
            else:
                col.label(text=f"{len(selected_rigs)} selected layers")
                col.label(text=f"{num_images} total images in group")
                col.label(text=f"{total_frames} total frames in group")

            if missing_count > 0:
                col.separator()
                col.label(text=f"⚠ {missing_count} Missing Files!", icon=fbp_icon("ERROR"))


class FBP_PT_LayerStack(Panel):
    bl_label       = "Layers"
    bl_idname      = "FBP_PT_layer_stack"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "Frame by Plane"
    bl_order       = 1

    @classmethod
    def poll(cls, context):
        return any(is_fbp_layer_object(obj) for obj in context.scene.objects)

    def draw_header(self, context):
        self.layout.label(text="", icon=fbp_icon("RENDER_RESULT"))

    def draw(self, context):
        layout = self.layout
        sc = context.scene

        row = layout.row(align=False)
        box = row.box()
        draw_fbp_hierarchical_layer_view(box, context)
        col = row.column(align=True)
        fbp_set_ui_units_x(col, 1.25)
        col.prop(sc, "fbp_sort_layers_alpha", text="", toggle=True, icon=fbp_icon("SORTALPHA"))
        col.operator("fbp.move_layer_stack", text="", icon=fbp_icon("SORT_DESC")).direction = 'DOWN'
        col.operator("fbp.move_layer_stack", text="", icon=fbp_icon("SORT_ASC")).direction  = 'UP'
        col.separator()
        col.operator("fbp.open_create_rig", text="", icon=fbp_icon("ADD"))
        col.operator("fbp.popup_color_plane", text="", icon=fbp_icon("IMAGE"))
        col.separator()
        col.operator("fbp.duplicate_selected_layers", text="", icon=fbp_icon("DUPLICATE"))
        col.operator("fbp.delete_sequence", text="", icon=fbp_icon("TRASH"))
        col.separator()
        col.operator("fbp.select_all_layers", text="", icon=fbp_icon("RESTRICT_SELECT_OFF"))


class FBP_PT_Sequence(Panel):
    bl_label       = "Sequence"
    bl_idname      = "FBP_PT_sequence"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "Frame by Plane"
    bl_order       = 2

    @classmethod
    def poll(cls, context):
        return bool(get_selected_rigs(context))

    def draw_header(self, context):
        self.layout.label(text="", icon=fbp_icon("IMAGE_BACKGROUND"))

    def draw(self, context):
        layout = self.layout
        selected_rigs = get_selected_rigs(context)
        if not selected_rigs:
            return

        rig = selected_rigs[0]

        box = layout.box()

        row = box.row(align=False)
        row.prop(rig, "fbp_color_tag", text="", icon_only=False)
        row.prop(rig, "name", text="", icon=fbp_icon("IMAGE_BACKGROUND"))
        row.operator("fbp.replace_sequence", text="", icon=fbp_icon("FOLDER_REDIRECT"))

        row = box.row(align=False)
        vis_icon=fbp_icon("HIDE_OFF") if rig.fbp_is_visible else 'HIDE_ON'
        row.prop(rig, "fbp_is_visible", text="", icon=vis_icon)
        is_holdout_plane = bool(getattr(rig, "fbp_is_color_plane", False) and getattr(rig, "fbp_color_plane_mode", 'SOLID') == 'HOLDOUT')
        if not is_holdout_plane:
            row.prop(rig, "fbp_opacity", text="Opacity", slider=True)
            emiss_icon=fbp_icon("LIGHT_SUN")
            if getattr(rig, "fbp_is_color_plane", False):
                row.prop(rig, "fbp_color_plane_emission", text="", icon=emiss_icon, toggle=True)
            else:
                row.prop(rig, "fbp_use_emission", text="", icon=emiss_icon, toggle=True)

        row = box.row(align=False)
        row.prop(rig, "fbp_track_cam", toggle=True, icon=fbp_icon("CON_CAMERASOLVER"))
        if len(selected_rigs) > 1:
            row.operator("fbp.multi_fit_camera", text="Fit", icon=fbp_icon("FULLSCREEN_ENTER"))
        else:
            row.operator("fbp.fit_camera", icon=fbp_icon("FULLSCREEN_ENTER"), text="Fit")
        row.operator("fbp.popup_transform", text="Transform", icon=fbp_icon("EMPTY_ARROWS"))

        tools = layout.box()
        tools.label(text="Floating Tools", icon=fbp_icon("MODIFIER"))
        row = tools.row(align=True)
        row.operator("fbp.popup_edges", text="Edges", icon=fbp_icon("MOD_BOOLEAN"))
        row.operator("fbp.popup_wiggle", text="Wiggle", icon=fbp_icon("MOD_NOISE"), depress=bool(getattr(rig, 'fbp_wiggle_enabled', False)))

        if getattr(rig, "fbp_is_color_plane", False):
            color_box = layout.box()
            color_box.label(text="Color / Gradient Plane", icon=fbp_icon("MATERIAL"))
            color_box.prop(rig, "fbp_color_plane_mode", expand=True)
            if rig.fbp_color_plane_mode == 'GRADIENT':
                fbp_draw_gradient_choice_rows(color_box, rig)
                draw_native_fbp_color_ramp(color_box, rig)
                transform_box = color_box.box()
                is_open = bool(getattr(rig, 'fbp_show_gradient_transform', True))
                row = transform_box.row(align=True)
                row.prop(rig, 'fbp_show_gradient_transform', text='Position', icon=(fbp_icon('DOWNARROW_HLT') if is_open else fbp_icon('RIGHTARROW')), emboss=False)
                if is_open:
                    row = transform_box.row(align=True)
                    row.prop(rig, "fbp_gradient_offset_x", text="X")
                    row.prop(rig, "fbp_gradient_offset_y", text="Y")
                    row = transform_box.row(align=True)
                    row.prop(rig, "fbp_gradient_scale_x", text="Scale X")
                    row.prop(rig, "fbp_gradient_scale_y", text="Scale Y")
                    transform_box.prop(rig, "fbp_gradient_rotation", text="Rotation")
            elif rig.fbp_color_plane_mode == 'SOLID':
                color_box.prop(rig, "fbp_color_plane_color", text="Color")

        show_animation_panel = not getattr(rig, "fbp_is_color_plane", False) or len(rig.fbp_images) > 0
        if show_animation_panel:
            box = layout.box()
            box.label(text="Animation", icon=fbp_icon("ONIONSKIN_ON"))
            row = box.row(align=False)
            sub1 = row.row(align=True)
            sub1.prop(rig, "fbp_start_frame")
            sub1.operator("fbp.set_current_frame", text="", icon=fbp_icon("EYEDROPPER"))
            row.prop(rig, "fbp_loop_mode", text="")
            row.operator("fbp.reverse_sequence", text="", icon=fbp_icon("ARROW_LEFTRIGHT"))

        if len(selected_rigs) <= 1:
            show_frame_tools = not getattr(rig, "fbp_is_color_plane", False) or len(rig.fbp_images) > 0
            can_add_frames = not getattr(rig, "fbp_is_color_plane", False) or fbp_color_plane_can_have_frames(rig)

            if not (getattr(rig, "fbp_is_color_plane", False) and not fbp_color_plane_can_have_frames(rig)):
                box = layout.box()
                box.label(text="Frames" if show_frame_tools else "Animation Frames", icon=fbp_icon("RENDER_RESULT"))
                if show_frame_tools:
                    row = box.row()
                    row.template_list("FBP_UL_ImageList", "",
                                      rig, "fbp_images",
                                      rig, "fbp_images_index", rows=8)
                    col = row.column(align=False)
                    # Icons only inverted: function/order stays MOVE_UP then MOVE_DOWN.
                    col.operator("fbp.list_action", icon=fbp_icon("SORT_DESC"), text="").action = 'MOVE_UP'
                    col.operator("fbp.list_action", icon=fbp_icon("SORT_ASC"), text="").action = 'MOVE_DOWN'
                    col.separator()
                    if getattr(rig, "fbp_is_color_plane", False):
                        is_gradient = getattr(rig, "fbp_color_plane_mode", "SOLID") == 'GRADIENT'
                        add_icon = fbp_icon("NODE_TEXTURE") if is_gradient else fbp_icon("IMAGE")
                        op = col.operator("fbp.insert_images_after_selected", icon=add_icon, text="")
                        op.frame_mode = 'AUTO'
                        op = col.operator("fbp.insert_images_after_selected", icon=fbp_icon("TEXTURE_DATA"), text="")
                        op.frame_mode = 'TRANSPARENT'
                    else:
                        op = col.operator("fbp.insert_images_after_selected", icon=fbp_icon("TEXTURE_DATA"), text="")
                        op.frame_mode = 'TRANSPARENT'
                        col.operator("fbp.insert_linked_image_after_selected", icon=fbp_icon("FILE_FOLDER"), text="")
                    col.separator()
                    col.operator("fbp.split_selected_images_to_new_plane", icon=fbp_icon("AREA_DOCK"), text="")
                    col.operator("fbp.list_action", icon=fbp_icon("SORTALPHA"), text="").action = 'SORT_NATURAL'
                    col.operator("fbp.list_action", icon=fbp_icon("DUPLICATE"), text="").action = 'DUPLICATE_SELECTED'
                    col.operator("fbp.list_action", icon=fbp_icon("PANEL_CLOSE"), text="").action = 'REMOVE'

                    row = box.row(align=False)
                    row.operator("fbp.select_all", text="All",    icon=fbp_icon("PROP_ON")).action  = 'ALL'
                    row.operator("fbp.select_all", text="None",   icon=fbp_icon("PROP_OFF")).action = 'NONE'
                    row.operator("fbp.select_all", text="Invert", icon=fbp_icon("PROP_CON")).action = 'INVERT'

                    row = box.row(align=False)
                    row.operator("fbp.list_action", text="Remove Unchecked", icon=fbp_icon("TRASH")).action = 'REMOVE_UNCHECKED'
                elif can_add_frames:
                    if getattr(rig, "fbp_is_color_plane", False):
                        is_gradient = getattr(rig, "fbp_color_plane_mode", "SOLID") == 'GRADIENT'
                        label = "Add New Gradient Frame" if is_gradient else "Add New Color Frame"
                        icon = fbp_icon("NODE_TEXTURE") if is_gradient else fbp_icon("IMAGE")
                        row = box.row(align=True)
                        op = row.operator("fbp.insert_images_after_selected", text=label, icon=icon)
                        op.frame_mode = 'AUTO'
                        op = row.operator("fbp.insert_images_after_selected", text="Create Transparent Frame", icon=fbp_icon("TEXTURE_DATA"))
                        op.frame_mode = 'TRANSPARENT'
                    else:
                        row = box.row(align=True)
                        op = row.operator("fbp.insert_images_after_selected", text="Create Transparent Frame", icon=fbp_icon("TEXTURE_DATA"))
                        op.frame_mode = 'TRANSPARENT'
                        row.operator("fbp.insert_linked_image_after_selected", text="Import Image Frame", icon=fbp_icon("FILE_FOLDER"))

        if len(rig.fbp_images) > 0 or not getattr(rig, "fbp_is_color_plane", False):
            row = layout.row(align=False)
            row.prop(rig, "fbp_global_duration", text="Duration")
            row.operator("fbp.batch_apply", text="Apply", icon=fbp_icon("CHECKMARK"))


class FBP_PT_CreateFirst(Panel):
    bl_label       = "Create"
    bl_idname      = "FBP_PT_create_first"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "Frame by Plane"
    bl_order       = 3

    @classmethod
    def poll(cls, context):
        return not any(getattr(obj, "is_fbp_control", False) for obj in context.scene.objects)

    def draw_header(self, context):
        self.layout.label(text="", icon=fbp_icon("EVENT_PLUS"))

    def draw(self, context):
        draw_creation_ui(self.layout, context)


class FBP_PT_CreateExisting(Panel):
    bl_label       = "Create"
    bl_idname      = "FBP_PT_create_existing"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "Frame by Plane"
    bl_order       = 4

    @classmethod
    def poll(cls, context):
        return (any(getattr(obj, "is_fbp_control", False) for obj in context.scene.objects)
                and getattr(context.scene, "fbp_show_create_tools", False))

    def draw_header(self, context):
        self.layout.label(text="", icon=fbp_icon("EVENT_PLUS"))

    def draw(self, context):
        draw_creation_ui(self.layout, context)


# ── OPERATORS ─────────────────────────────────────────────────────────────────

class FBP_OT_SaveFile(Operator):
    bl_idname      = "fbp.save_file"
    bl_label       = "Save File"
    bl_description = "Quickly save the current .blend file"

    def execute(self, context):
        if not bpy.data.is_saved:
            bpy.ops.wm.save_as_mainfile('INVOKE_DEFAULT')
        else:
            bpy.ops.wm.save_mainfile()
            self.report({'INFO'}, "Project saved!")
        return {'FINISHED'}


class FBP_OT_OpenCreateRig(Operator):
    bl_idname      = "fbp.open_create_rig"
    bl_label       = "Create New Frame by Plane Rig"
    bl_description = "Deselect layers and show the Create New Rig panel"
    bl_options     = {'UNDO'}

    def execute(self, context):
        bpy.ops.object.select_all(action='DESELECT')
        context.scene.fbp_show_create_tools = True
        return {'FINISHED'}


class FBP_OT_SelectLinkedPlane(Operator):
    bl_idname = "fbp.select_linked_plane"
    bl_label = "Toggle Linked Plane Selectability"
    bl_description = "Allow or prevent direct viewport selection of the linked image/color plane. Planes are locked by default"
    bl_options = {'UNDO'}

    rig_name: StringProperty(name="Rig", description="Frame by Plane rig whose linked plane selectability should be toggled")

    def execute(self, context):
        rig = bpy.data.objects.get(self.rig_name)
        plane = getattr(rig, 'fbp_plane_target', None) if rig else None
        if not plane:
            self.report({'WARNING'}, "This layer has no linked plane")
            return {'CANCELLED'}
        try:
            plane.hide_select = not bool(plane.hide_select)
            if plane.hide_select and plane.select_get():
                plane.select_set(False)
                if rig and object_in_view_layer(rig, context):
                    rig.select_set(True)
                    context.view_layer.objects.active = rig
        except ReferenceError:
            return {'CANCELLED'}
        except Exception as exc:
            fbp_warn("Could not toggle linked plane selectability", exc)
            return {'CANCELLED'}
        return {'FINISHED'}


class FBP_OT_SelectCollectionPlanes(Operator):
    bl_idname = "fbp.select_collection_planes"
    bl_label = "Toggle Collection Plane Selectability"
    bl_description = "Allow or prevent direct viewport selection of all linked image/color planes in this Frame by Plane collection"
    bl_options = {'UNDO'}

    collection_name: StringProperty(default="")

    def execute(self, context):
        coll = bpy.data.collections.get(self.collection_name)
        if not coll:
            return {'CANCELLED'}
        planes = []
        for rig in iter_fbp_rigs_in_collection(coll, True):
            plane = getattr(rig, 'fbp_plane_target', None)
            if plane and object_in_view_layer(plane, context):
                planes.append(plane)
        if not planes:
            self.report({'WARNING'}, "No linked planes found in this collection")
            return {'CANCELLED'}
        # If all planes are locked, unlock them. Otherwise lock them all again.
        unlock = all(getattr(plane, 'hide_select', True) for plane in planes)
        for plane in planes:
            try:
                plane.hide_select = not unlock
                if plane.hide_select and plane.select_get():
                    plane.select_set(False)
            except ReferenceError:
                continue
            except Exception as exc:
                fbp_warn("Could not toggle linked plane selectability in collection", exc)
        return {'FINISHED'}


class FBP_OT_AddColorPlaneVariant(Operator):
    bl_idname = "fbp.add_color_plane_variant"
    bl_label = "Add Color/Gradient Plane"
    bl_description = "Duplicate the selected color, gradient or holdout plane as a new editable layer instead of importing image frames"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rigs = [rig for rig in get_selected_rigs(context) if getattr(rig, 'fbp_is_color_plane', False)]
        if not rigs:
            self.report({'WARNING'}, "Select a Frame by Plane color, gradient or holdout rig first")
            return {'CANCELLED'}
        bpy.ops.object.select_all(action='DESELECT')
        for rig in rigs:
            if object_in_view_layer(rig, context):
                rig.select_set(True)
                context.view_layer.objects.active = rig
        return bpy.ops.fbp.duplicate_selected_layers()


class FBP_OT_SelectLayerExclusive(Operator):
    bl_idname      = "fbp.select_layer_exclusive"
    bl_label       = "Select Layer"
    bl_description = "Select only this layer. Use the checkbox for additive multi-selection"
    bl_options     = {'UNDO'}

    rig_name: StringProperty(default="")

    def execute(self, context):
        rig = bpy.data.objects.get(self.rig_name)
        if not rig or not is_fbp_layer_object(rig):
            return {'CANCELLED'}

        if not object_in_view_layer(rig, context):
            if not ensure_object_in_active_collection(rig, context):
                sync_layer_collection(context)
                self.report({'WARNING'}, "Layer is not in the active View Layer")
                return {'CANCELLED'}

        bpy.ops.object.select_all(action='DESELECT')
        rig.select_set(True)
        context.view_layer.objects.active = rig

        for i, item in enumerate(context.scene.fbp_layers):
            try:
                if item.obj == rig:
                    context.scene.fbp_layer_stack_index = i
                    break
            except ReferenceError:
                pass
        return {'FINISHED'}


class FBP_OT_DuplicateOrDefault(Operator):
    bl_idname      = "fbp.duplicate_or_default"
    bl_label       = "Duplicate"
    bl_description = "Shift+D: duplicate FBP rigs safely, otherwise use Blender's standard duplicate"
    bl_options     = {'UNDO'}

    def invoke(self, context, event):
        if get_selected_rigs(context):
            result = bpy.ops.fbp.duplicate_selected_layers()
            if 'FINISHED' in result:
                return bpy.ops.transform.translate('INVOKE_DEFAULT')
            return result
        return bpy.ops.object.duplicate_move('INVOKE_DEFAULT')



class FBP_OT_SelectAllLayers(Operator):
    bl_idname      = "fbp.select_all_layers"
    bl_label       = "Select All Layers"
    bl_description = "Select all Frame By Plane rigs in the scene"

    def execute(self, context):
        bpy.ops.object.select_all(action='DESELECT')
        count = 0
        for idx in visible_layer_indices(context):
            item = context.scene.fbp_layers[idx]
            obj = _safe_layer_obj(item)
            if obj and is_fbp_layer_object(obj):
                obj.select_set(True)
                context.view_layer.objects.active = obj
                count += 1
        self.report({'INFO'}, f"{count} layers selected")
        return {'FINISHED'}


class FBP_OT_ToggleLock(Operator):
    bl_idname      = "fbp.toggle_lock"
    bl_label       = "Toggle Lock"
    bl_description = "Toggle object selectability in viewport. Shift+Click to apply to all selected"
    bl_options     = {'UNDO'}

    rig_name: StringProperty(default="")
    target:   StringProperty(default="RIG")
    shift:    BoolProperty(default=False)

    def invoke(self, context, event):
        self.shift = event.shift
        return self.execute(context)

    def execute(self, context):
        rigs = (get_selected_rigs(context) if self.shift
                else ([bpy.data.objects.get(self.rig_name)] if self.rig_name
                      else get_selected_rigs(context)))
        for rig in rigs:
            if not rig:
                continue
            if self.target == 'RIG':
                rig.hide_select = not rig.hide_select
            elif self.target == 'PLANE':
                plane = rig.fbp_plane_target
                if plane:
                    plane.hide_select = not plane.hide_select
        return {'FINISHED'}


class FBP_OT_ToggleSelectLayer(Operator):
    bl_idname      = "fbp.toggle_select_layer"
    bl_label       = "Toggle Layer Selection"
    bl_description = "Add or remove this layer from the selection"
    bl_options     = {'UNDO'}

    rig_name: StringProperty()

    def execute(self, context):
        rig = bpy.data.objects.get(self.rig_name)
        if rig:
            new_state = not rig.select_get()
            rig.select_set(new_state)
            if new_state:
                context.view_layer.objects.active = rig
        return {'FINISHED'}


class FBP_OT_ToggleSolo(Operator):
    bl_idname      = "fbp.toggle_solo"
    bl_label       = "Solo Layer"
    bl_description = "Isolate this layer. Click others to add them to the view"
    bl_options     = {'UNDO'}

    rig_name: StringProperty()

    def execute(self, context):
        sc = context.scene
        target_item = next(
            (item for item in sc.fbp_layers if item.obj and item.obj.name == self.rig_name),
            None)
        if not target_item:
            return {'CANCELLED'}

        active_items = [item for item in sc.fbp_layers if item.solo]

        if not active_items:
            for item in sc.fbp_layers:
                item.solo = False
                if item.obj:
                    item.obj.fbp_is_visible = False
            target_item.solo = True
            if target_item.obj:
                target_item.obj.fbp_is_visible = True
        elif len(active_items) == 1 and target_item.solo:
            for item in sc.fbp_layers:
                item.solo = False
                if item.obj:
                    item.obj.fbp_is_visible = True
        else:
            target_item.solo = not target_item.solo
            if target_item.obj:
                target_item.obj.fbp_is_visible = target_item.solo

        if not any(item.solo for item in sc.fbp_layers):
            for item in sc.fbp_layers:
                if item.obj:
                    item.obj.fbp_is_visible = True

        update_global_visibility(context)
        return {'FINISHED'}


class FBP_OT_MoveLayerStack(Operator):
    bl_idname      = "fbp.move_layer_stack"
    bl_label       = "Move Layer"
    bl_description = "Move this layer and recalculate depth automatically"

    direction: StringProperty()

    def execute(self, context):
        sc = context.scene
        idx = sc.fbp_layer_stack_index
        layers = sc.fbp_layers
        if not (0 <= idx < len(layers)):
            return {'CANCELLED'}

        current_rig = _safe_layer_obj(layers[idx])
        if not current_rig:
            return {'CANCELLED'}

        visible = visible_layer_indices(context, same_collection_as=current_rig)
        display_order = list(reversed(visible))
        if idx not in display_order or len(display_order) < 2:
            self.report({'WARNING'}, "No visible neighbour in this collection")
            return {'CANCELLED'}

        pos = display_order.index(idx)
        new_pos = pos - 1 if self.direction == 'UP' else pos + 1
        if not (0 <= new_pos < len(display_order)):
            return {'CANCELLED'}

        target_idx = display_order[new_pos]
        target_rig = _safe_layer_obj(layers[target_idx])
        if not target_rig:
            return {'CANCELLED'}

        swap_layer_depth_only(context, current_rig, target_rig)
        layers.move(idx, target_idx)
        sc.fbp_layer_stack_index = target_idx
        return {'FINISHED'}


class FBP_OT_IsolateLayer(Operator):
    bl_idname      = "fbp.isolate_layer"
    bl_label       = "Isolate Layer"
    bl_description = "Hide all other layers. Click again to show all"
    bl_options     = {'UNDO'}

    def execute(self, context):
        selected_rigs = get_selected_rigs(context)
        if not selected_rigs:
            return {'CANCELLED'}
        all_rigs = [ob for ob in context.scene.objects if getattr(ob, "is_fbp_control", False)]
        visible_rigs = [ob for ob in all_rigs if getattr(ob, "fbp_is_visible", False)]
        is_solo = set(visible_rigs) == set(selected_rigs)
        for rig in all_rigs:
            rig.fbp_is_visible = True if is_solo else (rig in selected_rigs)
        return {'FINISHED'}


class FBP_OT_FitToCamera(Operator):
    bl_idname      = "fbp.fit_camera"
    bl_label       = "Fit to Camera"
    bl_description = "Scale the layer using the image ratio, not the extended rig mesh"
    bl_options     = {'REGISTER', 'UNDO'}

    fit_mode: EnumProperty(
        name="Fit Mode",
        items=[
            ('FIT', "Fit Inside", "Fit the full image inside the camera frame", fbp_icon("FULLSCREEN_ENTER"), 0),
            ('FILL', "Fill Camera", "Fill the camera frame and crop if needed", fbp_icon("MOD_LENGTH"), 1),
            ('WIDTH', "Match Width", "Match the camera frame width", fbp_icon("ARROW_LEFTRIGHT"), 2),
            ('HEIGHT', "Match Height", "Match the camera frame height", fbp_icon("EMPTY_SINGLE_ARROW"), 3),
        ],
        default='FIT')

    def invoke(self, context, event):
        self.fit_mode = getattr(context.scene, "fbp_fit_mode", 'FIT')
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Fit Mode", icon=fbp_icon("FULLSCREEN_ENTER"))
        layout.prop(self, "fit_mode", expand=True)

    def execute(self, context):
        cam = context.scene.camera
        if not cam:
            self.report({'WARNING'}, "No active camera!")
            return {'CANCELLED'}
        rigs = get_selected_rigs(context)
        if not rigs:
            return {'CANCELLED'}
        context.scene.fbp_fit_mode = self.fit_mode
        context.view_layer.update()
        context.evaluated_depsgraph_get().update()
        for rig in rigs:
            apply_fit_to_camera(context, rig, cam, self.fit_mode)
        return {'FINISHED'}


class FBP_OT_MultiFitCamera(Operator):
    bl_idname      = "fbp.multi_fit_camera"
    bl_label       = "Fit All to Camera"
    bl_description = "Scale all selected rigs using the image ratio, not the extended rig mesh"
    bl_options     = {'REGISTER', 'UNDO'}

    fit_mode: EnumProperty(
        name="Fit Mode",
        items=[
            ('FIT', "Fit Inside", "Fit the full image inside the camera frame", fbp_icon("FULLSCREEN_ENTER"), 0),
            ('FILL', "Fill Camera", "Fill the camera frame and crop if needed", fbp_icon("MOD_LENGTH"), 1),
            ('WIDTH', "Match Width", "Match the camera frame width", fbp_icon("ARROW_LEFTRIGHT"), 2),
            ('HEIGHT', "Match Height", "Match the camera frame height", fbp_icon("EMPTY_SINGLE_ARROW"), 3),
        ],
        default='FIT')

    def invoke(self, context, event):
        self.fit_mode = getattr(context.scene, "fbp_fit_mode", 'FIT')
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Fit Mode", icon=fbp_icon("FULLSCREEN_ENTER"))
        layout.prop(self, "fit_mode", expand=True)

    def execute(self, context):
        cam = context.scene.camera
        if not cam:
            self.report({'WARNING'}, "No active camera!")
            return {'CANCELLED'}
        rigs = get_selected_rigs(context)
        if not rigs:
            self.report({'WARNING'}, "No rig selected!")
            return {'CANCELLED'}
        context.scene.fbp_fit_mode = self.fit_mode
        context.view_layer.update()
        context.evaluated_depsgraph_get().update()
        for rig in rigs:
            apply_fit_to_camera(context, rig, cam, self.fit_mode)
        self.report({'INFO'}, f"{len(rigs)} layers fitted to camera")
        return {'FINISHED'}


class FBP_OT_SetCurrentFrame(Operator):
    bl_idname      = "fbp.set_current_frame"
    bl_label       = "Set to Current Frame"
    bl_description = "Set the animation start to the current timeline frame"
    bl_options     = {'UNDO'}

    def execute(self, context):
        for rig in get_selected_rigs(context):
            rig.fbp_start_frame = context.scene.frame_current
        return {'FINISHED'}


class FBP_OT_ImportFolderHierarchy(Operator):
    bl_idname      = "fbp.import_folder_hierarchy"
    bl_label       = "Import from Folder"
    bl_description = "Auto-import mixed folders and single images to the Pending List"
    bl_options     = {'UNDO'}

    def execute(self, context):
        sc = context.scene
        base = bpy.path.abspath(sc.fbp_parent_import_path)
        if not os.path.isdir(base):
            self.report({'ERROR'}, "Invalid or unset directory!")
            return {'CANCELLED'}

        entries = []
        for name in os.listdir(base):
            if is_hidden_import_name(name):
                continue
            path = os.path.join(base, name)
            if os.path.isdir(path):
                files = sorted(
                    (f for f in os.listdir(path)
                     if not is_hidden_import_name(f) and is_supported_image_file(f) and not is_technical_map_file(f)),
                    key=natural_sort_key
                )
                if files:
                    entries.append((name, path, files, 'FOLDER'))
            elif is_supported_image_file(name) and not is_technical_map_file(name):
                entries.append((clean_layer_name_from_path(name), base, [name], 'IMAGE'))

        entries.sort(key=lambda e: natural_sort_key(e[0]))
        sc.fbp_pending_planes.clear()

        for index, (name, directory, files, kind) in enumerate(entries):
            item = sc.fbp_pending_planes.add()
            item.name = name
            item.directory = directory
            item.files_str = '|'.join(files)
            item.fbp_color_tag = f"COLOR_{(index % 9) + 1:02d}"

        if entries:
            self.report({'INFO'}, f"Imported {len(entries)} layer(s) from mixed folder")
        else:
            self.report({'WARNING'}, "No valid image sequences or single images found.")
        return {'FINISHED'}


class FBP_OT_AddPendingPlane(Operator):
    bl_idname      = "fbp.add_pending_plane"
    bl_label       = "Add Empty Layer"
    bl_description = "Add an empty row to the MultiPlane setup"

    def execute(self, context):
        sc = context.scene
        idx = len(sc.fbp_pending_planes)
        item = sc.fbp_pending_planes.add()
        item.name = f"Layer {idx + 1}"
        item.fbp_color_tag = f"COLOR_{(idx % 9) + 1:02d}"
        sc.fbp_pending_planes_idx = idx
        return {'FINISHED'}


class FBP_OT_EditPendingPlane(Operator):
    bl_idname      = "fbp.edit_pending_plane"
    bl_label       = "Choose Images"
    bl_description = "Open file manager to assign images to this layer"

    index:     IntProperty()
    filepath:  StringProperty(subtype='FILE_PATH')
    directory: StringProperty(subtype='DIR_PATH')
    files:     CollectionProperty(type=bpy.types.OperatorFileListElement)

    def invoke(self, context, event):
        path = context.scene.fbp_project_path or context.scene.fbp_last_directory
        if path:
            self.directory = path
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if not self.files:
            return {'CANCELLED'}
        sc = context.scene
        sc.fbp_last_directory = self.directory
        if 0 <= self.index < len(sc.fbp_pending_planes):
            item = sc.fbp_pending_planes[self.index]
            item.directory = self.directory
            sorted_files = sorted([f.name for f in self.files], key=natural_sort_key)
            item.files_str = "|".join(sorted_files)
            if len(sorted_files) == 1:
                item.name = clean_layer_name_from_path(sorted_files[0])
            else:
                folder_name = clean_layer_name_from_path(os.path.basename(os.path.normpath(self.directory)))
                if folder_name:
                    item.name = folder_name
        return {'FINISHED'}


class FBP_OT_MovePendingPlane(Operator):
    bl_idname      = "fbp.move_pending_plane"
    bl_label       = "Move Layer"
    bl_description = "Change the order of layers in the MultiPlane setup"

    direction: StringProperty()

    def execute(self, context):
        sc = context.scene
        idx = sc.fbp_pending_planes_idx
        new_idx = idx - 1 if self.direction == 'UP' else idx + 1
        if 0 <= new_idx < len(sc.fbp_pending_planes):
            sc.fbp_pending_planes.move(idx, new_idx)
            sc.fbp_pending_planes_idx = new_idx
        return {'FINISHED'}


class FBP_OT_RemovePendingPlane(Operator):
    bl_idname      = "fbp.remove_pending_plane"
    bl_label       = "Remove Layer"
    bl_description = "Delete the selected layer from the list"

    def execute(self, context):
        sc = context.scene
        idx = sc.fbp_pending_planes_idx
        if 0 <= idx < len(sc.fbp_pending_planes):
            sc.fbp_pending_planes.remove(idx)
            if idx > 0:
                sc.fbp_pending_planes_idx -= 1
        return {'FINISHED'}


class FBP_OT_ClearPendingPlanes(Operator):
    bl_idname      = "fbp.clear_pending_planes"
    bl_label       = "Clear List"
    bl_description = "Completely empty the MultiPlane setup"
    bl_options     = {'UNDO'}

    def execute(self, context):
        context.scene.fbp_pending_planes.clear()
        return {'FINISHED'}


def fbp_scan_project_layers_for_setup(root):
    """Return pending setup rows from a project folder, preserving collection groups."""
    rows = []
    root = bpy.path.abspath(root)
    if not root or not os.path.isdir(root):
        return rows

    def direct_images(path):
        try:
            return sorted(
                [name for name in os.listdir(path)
                 if os.path.isfile(os.path.join(path, name))
                 and not is_hidden_import_name(name)
                 and is_supported_image_file(name)
                 and not is_technical_map_file(name)],
                key=natural_sort_key)
        except Exception:
            return []

    def direct_dirs(path):
        try:
            return sorted(
                [name for name in os.listdir(path)
                 if os.path.isdir(os.path.join(path, name))
                 and not is_hidden_import_name(name)
                 and fbp_folder_has_images_recursive(os.path.join(path, name))],
                key=natural_sort_key)
        except Exception:
            return []

    def visit(path, collection_name=""):
        imgs = direct_images(path)
        dirs = direct_dirs(path)
        folder_name = clean_layer_name_from_path(path)
        if imgs and not dirs and path != root:
            rows.append((folder_name, collection_name, path, imgs))
            return
        # Loose images inside a collection folder become static layers in that collection.
        for img in imgs:
            rows.append((clean_layer_name_from_path(img), collection_name, path, [img]))
        for d in dirs:
            full = os.path.join(path, d)
            child_imgs = direct_images(full)
            child_dirs = direct_dirs(full)
            if path == root:
                # Top-level folders become setup collections, even when they contain a single sequence.
                next_collection = clean_layer_name_from_path(full)
            else:
                base_collection = collection_name or clean_layer_name_from_path(path)
                next_collection = base_collection if (child_imgs and not child_dirs) else (base_collection + " / " + clean_layer_name_from_path(full))
            visit(full, next_collection)

    visit(root, "")
    return rows


class FBP_OT_ScanProjectToSetup(Operator):
    bl_idname = "fbp.scan_project_to_setup"
    bl_label = "Import Project"
    bl_description = "Scan the Project Folder into the MultiPlane Setup list before generating planes"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        sc = context.scene
        base = bpy.path.abspath(getattr(sc, "fbp_project_path", "") or "")
        if not base or not os.path.isdir(base):
            self.report({'WARNING'}, "Set a valid Project Folder in Settings")
            return {'CANCELLED'}
        rows = fbp_scan_project_layers_for_setup(base)
        sc.fbp_pending_planes.clear()
        for index, (name, collection_name, directory, files) in enumerate(rows):
            item = sc.fbp_pending_planes.add()
            item.name = name
            item.collection_name = collection_name
            item.directory = directory
            item.files_str = "|".join(sorted(files, key=natural_sort_key))
            item.fbp_color_tag = f"COLOR_{(index % 9) + 1:02d}"
        sc.fbp_parent_import_path = base
        sc["fbp_pending_open_collections"] = ""
        self.report({'INFO'}, f"Imported {len(rows)} setup row(s) from Project Folder")
        return {'FINISHED'} if rows else {'CANCELLED'}


class FBP_OT_AddPendingCollection(Operator):
    bl_idname = "fbp.add_pending_collection"
    bl_label = "Create Collection"
    bl_description = "Assign a collection name to the selected MultiPlane setup row"
    bl_options = {'REGISTER', 'UNDO'}

    collection_name: StringProperty(name="Collection", default="New Collection")

    def invoke(self, context, event):
        self.collection_name = getattr(context.scene, "fbp_pending_collection_name", "New Collection")
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "collection_name")

    def execute(self, context):
        sc = context.scene
        sc.fbp_pending_collection_name = self.collection_name
        idx = sc.fbp_pending_planes_idx
        if 0 <= idx < len(sc.fbp_pending_planes):
            sc.fbp_pending_planes[idx].collection_name = self.collection_name
        else:
            item = sc.fbp_pending_planes.add()
            item.name = "New Layer"
            item.collection_name = self.collection_name
            sc.fbp_pending_planes_idx = len(sc.fbp_pending_planes) - 1
        return {'FINISHED'}


class FBP_OT_AutoSceneBuilder(Operator):
    bl_idname      = "fbp.auto_scene_builder"
    bl_label       = "Auto Build Project"
    bl_description = "Build Collections, camera and Frame by Plane layers from the Project Folder"
    bl_options     = {'REGISTER', 'UNDO'}

    def _child_entries(self, path):
        entries = []
        try:
            names = os.listdir(path)
        except Exception:
            return entries
        for name in names:
            if is_hidden_import_name(name):
                continue
            full = os.path.join(path, name)
            if os.path.isdir(full):
                if self._folder_has_importable_content(full):
                    entries.append(('DIR', name, full))
            elif is_supported_image_file(name) and not is_technical_map_file(name):
                entries.append(('IMAGE', clean_layer_name_from_path(name), full))
        entries.sort(key=lambda e: natural_sort_key(e[1]))
        return entries

    def _folder_has_importable_content(self, path):
        try:
            for name in os.listdir(path):
                if is_hidden_import_name(name):
                    continue
                full = os.path.join(path, name)
                if os.path.isdir(full) and self._folder_has_importable_content(full):
                    return True
                if not is_hidden_import_name(name) and is_supported_image_file(name) and not is_technical_map_file(name):
                    return True
        except Exception:
            return False
        return False

    def _folder_direct_images(self, path):
        try:
            return sorted(
                [name for name in os.listdir(path)
                 if os.path.isfile(os.path.join(path, name))
                 and not is_hidden_import_name(name)
                 and is_supported_image_file(name)
                 and not is_technical_map_file(name)],
                key=natural_sort_key
            )
        except Exception:
            return []

    def _folder_direct_dirs(self, path):
        try:
            return sorted(
                [name for name in os.listdir(path)
                 if os.path.isdir(os.path.join(path, name))
                 and not is_hidden_import_name(name)
                 and self._folder_has_importable_content(os.path.join(path, name))],
                key=natural_sort_key
            )
        except Exception:
            return []

    def _build_folder(self, context, folder_path, parent_collection, cursor_loc, depth_counter, color_seed=0, depth=0):
        folder_name = clean_layer_name_from_path(folder_path)
        color_tag = f"COLOR_{(color_seed % 9) + 1:02d}"
        coll = get_or_create_child_collection(parent_collection, folder_name, color_tag)

        direct_images = self._folder_direct_images(folder_path)
        direct_dirs = self._folder_direct_dirs(folder_path)

        generated = []

        # A folder containing only importable images is treated as one sequence/layer,
        # at every depth. This supports names like 01_name, 01 - Name, Name01, Name - 1.
        if direct_images and not direct_dirs:
            rig_loc = cursor_loc.copy()
            offset = context.scene.fbp_layer_offset * depth_counter[0]
            if context.scene.fbp_pre_orientation == 'HORIZ':
                rig_loc.z -= offset
            else:
                rig_loc.y += offset
            rig = build_fbp_rig(
                context,
                folder_name,
                folder_path,
                direct_images,
                rig_loc,
                color_tag=color_tag,
                target_collection=parent_collection,
                color_variant_index=depth_counter[0]
            )
            rig.fbp_depth_order = depth_counter[0]
            depth_counter[0] += 1
            return [rig]

        # Se contiene sottocartelle e immagini singole, diventa Collection e ordina tutto insieme.
        entries = self._child_entries(folder_path)
        local_variant = 0
        for kind, name, full in entries:
            if kind == 'IMAGE':
                rig_loc = cursor_loc.copy()
                offset = context.scene.fbp_layer_offset * depth_counter[0]
                if context.scene.fbp_pre_orientation == 'HORIZ':
                    rig_loc.z -= offset
                else:
                    rig_loc.y += offset
                rig = build_fbp_rig(
                    context,
                    name,
                    folder_path,
                    [os.path.basename(full)],
                    rig_loc,
                    color_tag=safe_collection_color_tag(coll, color_tag),
                    target_collection=coll,
                    color_variant_index=local_variant
                )
                rig.fbp_depth_order = depth_counter[0]
                depth_counter[0] += 1
                local_variant += 1
                generated.append(rig)
            elif kind == 'DIR':
                child_images = self._folder_direct_images(full)
                child_dirs = self._folder_direct_dirs(full)
                if child_images and not child_dirs:
                    rig_loc = cursor_loc.copy()
                    offset = context.scene.fbp_layer_offset * depth_counter[0]
                    if context.scene.fbp_pre_orientation == 'HORIZ':
                        rig_loc.z -= offset
                    else:
                        rig_loc.y += offset
                    rig = build_fbp_rig(
                        context,
                        clean_layer_name_from_path(full),
                        full,
                        child_images,
                        rig_loc,
                        color_tag=safe_collection_color_tag(coll, color_tag),
                        target_collection=coll,
                        color_variant_index=local_variant
                    )
                    rig.fbp_depth_order = depth_counter[0]
                    depth_counter[0] += 1
                    local_variant += 1
                    generated.append(rig)
                else:
                    generated.extend(self._build_folder(context, full, coll, cursor_loc, depth_counter, color_seed + local_variant + 1, depth + 1))
                    local_variant += 1
        return generated

    def execute(self, context):
        # Fast import is now entered directly here instead of monkey-patching the class at module load.
        if fbp_fast_import_is_active():
            if getattr(context.scene, "fbp_import_main_folders_as_scenes", False):
                return fbp_auto_build_main_folders_as_scenes(self, context)
            return self._execute_impl(context)
        fbp_begin_fast_import(context)
        try:
            if getattr(context.scene, "fbp_import_main_folders_as_scenes", False):
                return fbp_auto_build_main_folders_as_scenes(self, context)
            return self._execute_impl(context)
        finally:
            fbp_end_fast_import(context)

    def _execute_impl(self, context):
        sc = context.scene
        base = bpy.path.abspath(sc.fbp_project_path)
        if not base or not os.path.isdir(base):
            self.report({'WARNING'}, "Set a valid Project Folder in Settings!")
            return {'CANCELLED'}

        root_name = FBP_PROJECT_COLLECTION_PREFIX + clean_layer_name_from_path(base)
        root_coll = get_or_create_child_collection(sc.collection, root_name, 'COLOR_09')
        if sc.fbp_gen_camera:
            apply_camera_ratio_settings(sc)
        cursor_loc = sc.cursor.location.copy()
        depth_counter = [0]

        bpy.ops.object.select_all(action='DESELECT')

        # The project builder now behaves like the MultiPlane generator:
        # it respects the setup box settings and can create/move the camera
        # directly inside the generated project Collection.
        if sc.fbp_gen_camera:
            cam_dist = 10.0
            cam_loc = cursor_loc.copy()
            if sc.fbp_pre_orientation == 'HORIZ':
                cam_loc.z += cam_dist
                bpy.ops.object.camera_add(location=cam_loc, rotation=(0, 0, 0))
            else:
                cam_loc.y -= cam_dist
                bpy.ops.object.camera_add(location=cam_loc, rotation=(math.radians(90), 0, 0))
            sc.camera = context.active_object
            move_object_to_collection(sc.camera, root_coll)
            if sc.fbp_cam_pivot:
                sc.cursor.location = cam_loc
                context.scene.tool_settings.transform_pivot_point = 'CURSOR'
            sc.fbp_gen_camera = False
            sc.fbp_cam_pivot = False

        generated = []

        top_entries = self._child_entries(base)
        for i, (kind, name, full) in enumerate(top_entries):
            before_count = len(generated)
            if kind == 'DIR':
                generated.extend(self._build_folder(context, full, root_coll, cursor_loc, depth_counter, i, depth=0))
                # Leave a clearer visual gap between imported collections.
                if len(generated) > before_count:
                    depth_counter[0] += 3
            elif kind == 'IMAGE':
                # Audio e file non immagine vengono già esclusi; immagine diretta = layer statico root.
                rig_loc = cursor_loc.copy()
                offset = sc.fbp_layer_offset * depth_counter[0]
                if sc.fbp_pre_orientation == 'HORIZ':
                    rig_loc.z -= offset
                else:
                    rig_loc.y += offset
                rig = build_fbp_rig(context, name, base, [os.path.basename(full)], rig_loc,
                                    color_tag=f"COLOR_{(i % 9) + 1:02d}", target_collection=root_coll,
                                    color_variant_index=i)
                rig.fbp_depth_order = depth_counter[0]
                depth_counter[0] += 1
                generated.append(rig)

        if not generated:
            self.report({'WARNING'}, "No valid image layers found in Project Folder")
            return {'CANCELLED'}

        if sc.fbp_auto_scale and sc.camera:
            context.view_layer.update()
            context.evaluated_depsgraph_get().update()
            for rig in generated:
                apply_fit_to_camera(context, rig, sc.camera)


        sync_layer_collection(context)
        sync_collection_colors_to_rigs(context)
        for rig in generated:
            if object_in_view_layer(rig, context):
                rig.select_set(True)
        if generated and object_in_view_layer(generated[-1], context):
            context.view_layer.objects.active = generated[-1]

        set_viewport_object_color(context)
        sc.fbp_show_create_tools = False
        self.report({'INFO'}, f"Auto Build Project: {len(generated)} layer(s) created")
        return {'FINISHED'}


class FBP_OT_GenerateMultiplane(Operator):
    bl_idname      = "fbp.generate_multiplane"
    bl_label       = "Generate Multiplane"
    bl_description = "Generate the full plane system in 3D space"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # Fast import is now entered directly here instead of monkey-patching the class at module load.
        if fbp_fast_import_is_active():
            return self._execute_impl(context)
        fbp_begin_fast_import(context)
        try:
            return self._execute_impl(context)
        finally:
            fbp_end_fast_import(context)

    def _execute_impl(self, context):
        sc = context.scene
        if not sc.fbp_pending_planes:
            self.report({'WARNING'}, "No layers added to the list!")
            return {'CANCELLED'}
        for p in sc.fbp_pending_planes:
            if not p.directory or not p.files_str:
                self.report({'ERROR'}, f"Layer '{p.name}' has no images assigned!")
                return {'CANCELLED'}

        if sc.fbp_gen_camera:
            apply_camera_ratio_settings(sc)
        cursor_loc = sc.cursor.location.copy()
        cam_dist = 10.0
        cam_loc = cursor_loc.copy()

        if sc.fbp_pre_orientation == 'HORIZ':
            cam_loc.z += cam_dist
        else:
            cam_loc.y -= cam_dist

        bpy.ops.object.select_all(action='DESELECT')

        source_path = bpy.path.abspath(sc.fbp_parent_import_path) if getattr(sc, "fbp_parent_import_path", "") else ""
        coll_base_name = clean_layer_name_from_path(source_path) if source_path else "Multi Plane"
        target_collection = get_or_create_child_collection(sc.collection, FBP_PROJECT_COLLECTION_PREFIX + coll_base_name, 'COLOR_09')

        if sc.fbp_gen_camera:
            if sc.fbp_pre_orientation == 'HORIZ':
                bpy.ops.object.camera_add(location=cam_loc, rotation=(0, 0, 0))
            else:
                bpy.ops.object.camera_add(
                    location=cam_loc, rotation=(math.radians(90), 0, 0))
            sc.camera = context.active_object
            move_object_to_collection(sc.camera, target_collection)
            if sc.fbp_cam_pivot:
                sc.cursor.location = cam_loc
                context.scene.tool_settings.transform_pivot_point = 'CURSOR'
            sc.fbp_gen_camera = False
            sc.fbp_cam_pivot = False

        cam = sc.camera
        last_rig = None
        generated_rigs = []

        depth_index = 0
        last_collection_name = None
        for i, p_item in enumerate(sc.fbp_pending_planes):
            f_list = sorted(p_item.files_str.split("|"), key=natural_sort_key)
            collection_name = getattr(p_item, "collection_name", "") or ""
            if collection_name and last_collection_name is not None and collection_name != last_collection_name:
                depth_index += 3
            last_collection_name = collection_name or last_collection_name

            rig_loc = cursor_loc.copy()
            offset = sc.fbp_layer_offset * depth_index
            if sc.fbp_pre_orientation == 'HORIZ':
                rig_loc.z -= offset
            else:
                rig_loc.y += offset

            layer_collection = target_collection
            if collection_name:
                layer_collection = get_or_create_child_collection(target_collection, collection_name, p_item.fbp_color_tag)

            rig = build_fbp_rig(
                context, p_item.name, p_item.directory, f_list, rig_loc,
                p_item.fbp_color_tag, target_collection=layer_collection, color_variant_index=i)
            rig.fbp_depth_order = depth_index
            depth_index += 1

            if sc.fbp_auto_scale and cam and not fbp_fast_import_is_active():
                context.view_layer.update()
                context.evaluated_depsgraph_get().update()
                apply_fit_to_camera(context, rig, cam)

            if not fbp_fast_import_is_active():
                rig.select_set(True)
            generated_rigs.append(rig)
            last_rig = rig


        if sc.fbp_auto_scale and cam:
            context.view_layer.update()
            context.evaluated_depsgraph_get().update()
            for rig in generated_rigs:
                apply_fit_to_camera(context, rig, cam)

        if fbp_fast_import_is_active():
            for rig in generated_rigs:
                if object_in_view_layer(rig, context):
                    rig.select_set(True)

        if last_rig:
            context.view_layer.objects.active = last_rig

        set_viewport_object_color(context)
        sc.fbp_show_create_tools = False
        return {'FINISHED'}


class FBP_OT_ImportSequence(Operator):
    bl_idname      = "fbp.import_sequence"
    bl_label       = "Select Images"
    bl_description = "Open the file manager to import a sequence"
    bl_options     = {'REGISTER', 'UNDO'}

    filepath:  StringProperty(subtype='FILE_PATH')
    directory: StringProperty(subtype='DIR_PATH')
    files:     CollectionProperty(type=bpy.types.OperatorFileListElement)

    def invoke(self, context, event):
        path = context.scene.fbp_project_path or context.scene.fbp_last_directory
        if path:
            self.directory = path
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        # Fast import is now entered directly here instead of monkey-patching the class at module load.
        if fbp_fast_import_is_active():
            return self._execute_impl(context)
        fbp_begin_fast_import(context)
        try:
            return self._execute_impl(context)
        finally:
            fbp_end_fast_import(context)

    def _execute_impl(self, context):
        if not self.files:
            return {'CANCELLED'}
        context.scene.fbp_last_directory = self.directory
        f_list = sorted([f.name for f in self.files], key=natural_sort_key)
        single_name = clean_layer_name_from_path(f_list[0]) if len(f_list) == 1 else clean_layer_name_from_path(os.path.basename(os.path.normpath(self.directory))) or "Sequence_Rig"
        target_collection = context.collection if context.collection else context.scene.collection
        rig = build_fbp_rig(
            context, single_name, self.directory, f_list,
            context.scene.cursor.location.copy(), target_collection=target_collection)
        bpy.ops.object.select_all(action='DESELECT')
        rig.select_set(True)
        context.view_layer.objects.active = rig
        set_viewport_object_color(context)
        context.scene.fbp_show_create_tools = False
        return {'FINISHED'}


class FBP_OT_ReplaceSequence(Operator):
    bl_idname      = "fbp.replace_sequence"
    bl_label       = "Replace Sequence"
    bl_description = "Replace plane files while keeping timing and keyframes"
    bl_options     = {'REGISTER', 'UNDO'}

    filepath:  StringProperty(subtype='FILE_PATH')
    directory: StringProperty(subtype='DIR_PATH')
    files:     CollectionProperty(type=bpy.types.OperatorFileListElement)

    def invoke(self, context, event):
        path = context.scene.fbp_project_path or context.scene.fbp_last_directory
        if path:
            self.directory = path
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if not self.files:
            return {'CANCELLED'}
        context.scene.fbp_last_directory = self.directory

        rig = context.object
        plane = rig.fbp_plane_target
        if not plane:
            return {'CANCELLED'}

        if plane.parent != rig:
            new_mesh = plane.data.copy()
            new_plane = plane.copy()
            new_plane.data = new_mesh
            context.collection.objects.link(new_plane)
            new_plane.parent = rig
            new_plane.matrix_local = plane.matrix_local
            rig.fbp_plane_target = new_plane
            plane = new_plane
            if plane.data.animation_data:
                plane.data.animation_data_clear()

        sorted_files = sorted([f.name for f in self.files], key=natural_sort_key)
        first_img = None
        plane.data.materials.clear()

        for i, f in enumerate(sorted_files):
            img_path = os.path.join(self.directory, f)
            mat = create_fbp_material(
                f"Mat_{f}", img_path,
                interp=getattr(rig, "fbp_interpolation", 'Closest'),
                opacity=rig.fbp_opacity,
            use_emission=rig.fbp_use_emission)
            plane.data.materials.append(mat)
            if i < len(rig.fbp_images):
                rig.fbp_images[i].name = f
                rig.fbp_images[i].is_empty = False
                rig.fbp_images[i].filepath = img_path
            else:
                item = rig.fbp_images.add()
                item.name = f
                item.duration = rig.fbp_global_duration
                item.is_selected = True
                item.is_empty = False
                item.filepath = img_path
            if not first_img:
                try:
                    first_img = bpy.data.images.load(img_path, check_existing=True)
                except Exception:
                    pass

        while len(rig.fbp_images) > len(sorted_files):
            rig.fbp_images.remove(len(rig.fbp_images) - 1)

        if first_img:
            width, height = first_img.size
            if width > height:
                rig.scale = (1, height / width, 1)
            else:
                rig.scale = (width / height, 1, 1)
            rig.fbp_base_scale_vec = rig.scale
            rig.fbp_preview_path = first_img.filepath

        do_update_animation(rig)
        do_update_emission(rig)

        for img in list(bpy.data.images):
            if img.users == 0 and not getattr(img, "use_fake_user", False):
                bpy.data.images.remove(img)

        return {'FINISHED'}


class FBP_OT_UpdateAnimation(Operator):
    bl_idname  = "fbp.update_animation"
    bl_label   = "Update Animation"
    bl_description = "Rebuild the selected layer animation preview and material frame assignment"
    bl_options = {'UNDO', 'INTERNAL'}

    def execute(self, context):
        for rig in get_selected_rigs(context):
            do_update_animation(rig)
        return {'FINISHED'}


class FBP_OT_Transform(Operator):
    bl_idname      = "fbp.transform"
    bl_label       = "Transform"
    bl_description = "Rotate the plane or place it on the ground"
    bl_options     = {'UNDO'}

    mode: StringProperty()

    def execute(self, context):
        for rig in get_selected_rigs(context):
            if self.mode == 'TOGGLE_ROT':
                if rig.fbp_is_vertical:
                    rig.rotation_euler[0] = 0
                    rig.fbp_is_vertical = False
                else:
                    rig.rotation_euler[0] = math.radians(90)
                    rig.fbp_is_vertical = True
            elif self.mode == 'TO_GROUND':
                bbox_world = [rig.matrix_world @ mathutils.Vector(c) for c in rig.bound_box]
                min_z = min(v.z for v in bbox_world)
                rig.location.z -= min_z
            elif self.mode == 'RESET_ROT':
                rig.rotation_euler = (0.0, 0.0, 0.0)
                rig.fbp_is_vertical = False
            elif self.mode == 'RESET_SCALE':
                base_vec = getattr(rig, "fbp_base_scale_vec", (1.0, 1.0, 1.0))
                rig.scale = base_vec
        return {'FINISHED'}




class FBP_OT_PopupTransform(Operator):
    bl_idname = "fbp.popup_transform"
    bl_label = "Transform Layer"
    bl_description = "Open transform tools for the selected Frame by Plane layer"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        if not get_selected_rigs(context):
            self.report({'WARNING'}, "Select a Frame by Plane layer first")
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        rig = get_selected_rigs(context)[0]
        layout = self.layout
        layout.label(text=rig.name, icon=fbp_icon("EMPTY_ARROWS"))
        col = layout.column(align=True)
        row = col.row(align=True)
        row.operator("fbp.transform", text="Horizontal / Vertical", icon=fbp_icon("FILE_REFRESH")).mode = 'TOGGLE_ROT'
        row.operator("fbp.transform", text="To Ground", icon=fbp_icon("GRID")).mode = 'TO_GROUND'
        row = col.row(align=True)
        row.operator("fbp.transform", text="Reset Rotation", icon=fbp_icon("FILE_REFRESH")).mode = 'RESET_ROT'
        row.operator("fbp.transform", text="Reset Scale", icon=fbp_icon("FULLSCREEN_ENTER")).mode = 'RESET_SCALE'

    def execute(self, context):
        return {'FINISHED'}


class FBP_OT_UpdateEmission(Operator):
    bl_idname  = "fbp.update_emission"
    bl_label   = "Update Emission"
    bl_description = "Rebuild selected layer materials using the current shadeless/emission setting"
    bl_options = {'UNDO', 'INTERNAL'}

    def execute(self, context):
        for rig in get_selected_rigs(context):
            do_update_emission(rig)
        return {'FINISHED'}


class FBP_OT_UpdateOpacity(Operator):
    bl_idname  = "fbp.update_opacity"
    bl_label   = "Update Opacity"
    bl_description = "Apply the current opacity to selected layer materials"
    bl_options = {'UNDO', 'INTERNAL'}

    def execute(self, context):
        for rig in get_selected_rigs(context):
            do_update_opacity(rig)
        return {'FINISHED'}


class FBP_OT_UpdateTrack(Operator):
    bl_idname  = "fbp.update_track"
    bl_label   = "Update Track"
    bl_description = "Update camera tracking constraints on selected Frame by Plane rigs"
    bl_options = {'UNDO', 'INTERNAL'}

    def execute(self, context):
        for rig in get_selected_rigs(context):
            do_update_track(rig, context)
        return {'FINISHED'}


def fbp_color_plane_can_have_frames(rig):
    return bool(getattr(rig, "fbp_is_color_plane", False) and getattr(rig, "fbp_color_plane_mode", "SOLID") != 'HOLDOUT')


def fbp_get_active_frame_material(rig):
    """Return the material assigned to the active frame, falling back to slot 0."""
    plane = getattr(rig, 'fbp_plane_target', None)
    if not plane or not getattr(plane, 'data', None) or not getattr(plane.data, 'materials', None):
        return None
    if not plane.data.materials:
        return None
    if len(getattr(rig, 'fbp_images', [])) > 0:
        idx = max(0, min(int(getattr(rig, 'fbp_images_index', 0)), len(plane.data.materials) - 1))
        return plane.data.materials[idx]
    return plane.data.materials[0]


def fbp_material_color_value(mat, fallback=(1.0, 1.0, 1.0, 1.0)):
    """Read the flat color from an FBP material without assuming one shader type."""
    if not mat:
        return fallback
    try:
        value = mat.get('fbp_color_value')
        if value and len(value) >= 4:
            return tuple(float(v) for v in value[:4])
    except Exception:
        pass
    try:
        if getattr(mat, 'diffuse_color', None):
            return tuple(float(v) for v in mat.diffuse_color)
    except Exception:
        pass
    return fallback


def fbp_load_active_procedural_frame_to_rig(rig):
    """Load the active color/gradient frame material into the rig UI controls.

    Each procedural frame owns its own material. Selecting a frame updates the
    editable color/gradient controls, while the update callbacks are suppressed
    so selecting does not accidentally overwrite that material.
    """
    if not rig or not getattr(rig, 'fbp_is_color_plane', False):
        return False
    mat = fbp_get_active_frame_material(rig)
    if not mat:
        return False
    try:
        rig['_fbp_syncing_frame_material'] = True
        if bool(mat.get('fbp_gradient_material', False)):
            rig.fbp_color_plane_mode = 'GRADIENT'
            rig.fbp_gradient_mode = str(mat.get('fbp_gradient_mode', getattr(rig, 'fbp_gradient_mode', 'LINEAR')))
            rig.fbp_gradient_kind = str(mat.get('fbp_gradient_kind', getattr(rig, 'fbp_gradient_kind', 'COLOR')))
            rig.fbp_gradient_reverse = bool(mat.get('fbp_gradient_reverse', getattr(rig, 'fbp_gradient_reverse', False)))
            ramp = find_fbp_gradient_ramp_node(mat)
            if ramp and len(ramp.color_ramp.elements) >= 2:
                elems = ramp.color_ramp.elements
                rig.fbp_gradient_color_a = tuple(elems[0].color)
                rig.fbp_gradient_color_b = tuple(elems[-1].color)
        elif bool(mat.get('fbp_holdout_material', False)):
            rig.fbp_color_plane_mode = 'HOLDOUT'
        else:
            rig.fbp_color_plane_mode = 'SOLID'
            rig.fbp_color_plane_color = fbp_material_color_value(mat, tuple(getattr(rig, 'fbp_color_plane_color', (1.0, 1.0, 1.0, 1.0))))
        return True
    except Exception as exc:
        fbp_warn('Could not load active procedural frame settings', exc)
        return False
    finally:
        try:
            del rig['_fbp_syncing_frame_material']
        except Exception:
            pass


def fbp_sequence_snapshot(rig):
    """Return image/material data, converting a static procedural plane to frame 1 when needed."""
    plane = getattr(rig, 'fbp_plane_target', None)
    image_data = [(item.name, item.duration, item.is_selected, getattr(item, 'is_empty', False), getattr(item, 'filepath', '')) for item in rig.fbp_images]
    material_data = [
        plane.data.materials[i] if plane and i < len(plane.data.materials) else None
        for i in range(len(image_data))
    ]

    if getattr(rig, "fbp_is_color_plane", False) and not image_data and plane:
        if not fbp_color_plane_can_have_frames(rig):
            return [], []
        source_mat = plane.data.materials[0] if len(plane.data.materials) else None
        if not source_mat:
            fbp_rebuild_color_plane_material(rig)
            source_mat = plane.data.materials[0] if len(plane.data.materials) else None
        label = "Gradient" if getattr(rig, "fbp_color_plane_mode", "SOLID") == 'GRADIENT' else "Color"
        image_data = [(label, max(1, int(getattr(rig, 'fbp_global_duration', 1))), True, False, "")]
        material_data = [source_mat]
    return image_data, material_data


def fbp_create_procedural_frame_material_for_rig(rig, suffix="Frame"):
    """Create an independent procedural material for a new color/gradient frame.

    The new frame copies the currently active procedural material first. This
    preserves edited solid colors and native ColorRamp edits, then the copy can
    be changed without affecting the source frame.
    """
    if not rig or not getattr(rig, "fbp_is_color_plane", False):
        return None, "Transparent Frame", True
    mode = getattr(rig, 'fbp_color_plane_mode', 'SOLID')
    use_emission = bool(getattr(rig, 'fbp_color_plane_emission', getattr(rig, 'fbp_use_emission', True)))
    safe_suffix = str(suffix).replace(" ", "_")

    active_mat = fbp_get_active_frame_material(rig)
    if active_mat and mode != 'HOLDOUT':
        try:
            mat = active_mat.copy()
            mat.name = ("FBP_Gradient_" if active_mat.get('fbp_gradient_material') else "FBP_Color_") + f"{rig.name}_{safe_suffix}"
            label = "Gradient Frame" if active_mat.get('fbp_gradient_material') else "Color Frame"
            return mat, label, False
        except Exception as exc:
            fbp_warn("Could not duplicate active procedural frame material", exc)

    if mode == 'GRADIENT':
        mat = create_fbp_gradient_material(
            f"FBP_Gradient_{rig.name}_{safe_suffix}",
            getattr(rig, 'fbp_gradient_mode', 'LINEAR'),
            getattr(rig, 'fbp_gradient_kind', 'COLOR'),
            tuple(getattr(rig, 'fbp_gradient_color_a', (1.0, 0.3686274509803922, 0.596078431372549, 1.0))),
            tuple(getattr(rig, 'fbp_gradient_color_b', (0.058823529411764705, 0.12941176470588237, 0.24313725490196078, 1.0))),
            bool(getattr(rig, 'fbp_gradient_reverse', False)),
            use_emission,
        )
        try:
            apply_fbp_gradient_mapping_to_material(rig, mat)
        except Exception as exc:
            fbp_warn("Could not copy gradient transform to new frame material", exc)
        return mat, "Gradient Frame", False
    color = tuple(getattr(rig, 'fbp_color_plane_color', (1.0, 1.0, 1.0, 1.0)))
    mat = create_fbp_color_material(f"FBP_Color_{rig.name}_{safe_suffix}", color, use_emission, False)
    return mat, "Color Frame", False


def fbp_insert_sequence_entry(rig, entry, material, insert_at=None):
    plane = getattr(rig, 'fbp_plane_target', None)
    if not plane:
        return -1
    image_data, material_data = fbp_sequence_snapshot(rig)
    if getattr(rig, "fbp_is_color_plane", False) and not fbp_color_plane_can_have_frames(rig):
        return -1
    if insert_at is None:
        checked = [i for i, data in enumerate(image_data) if data[2]]
        if checked:
            insert_at = checked[-1] + 1
        else:
            insert_at = min(max(getattr(rig, 'fbp_images_index', 0), 0), len(image_data) - 1) + 1 if image_data else 0
    image_data.insert(insert_at, entry)
    material_data.insert(insert_at, material)

    rig.fbp_images.clear()
    plane.data.materials.clear()
    for data, mat in zip(image_data, material_data):
        item = rig.fbp_images.add()
        item.name = data[0]
        item.duration = data[1]
        item.is_selected = data[2]
        item.is_empty = bool(data[3])
        item.filepath = data[4]
        if mat:
            plane.data.materials.append(mat)

    rig.fbp_images_index = max(0, min(insert_at, len(rig.fbp_images) - 1)) if rig.fbp_images else 0
    do_update_animation(rig)
    do_update_emission(rig)
    do_update_opacity(rig)
    return insert_at


class FBP_OT_SelectImageExclusive(Operator):
    bl_idname = "fbp.select_image_exclusive"
    bl_label = "Select Frame"
    bl_description = "Select only this frame. Use the checkbox for additive multi-selection"
    bl_options = {'UNDO'}

    rig_name: StringProperty(default="")
    index: IntProperty(default=0)

    def execute(self, context):
        rig = bpy.data.objects.get(self.rig_name)
        if not rig or not getattr(rig, "is_fbp_control", False):
            return {'CANCELLED'}
        if not (0 <= self.index < len(rig.fbp_images)):
            return {'CANCELLED'}

        for i, item in enumerate(rig.fbp_images):
            item.is_selected = (i == self.index)
        rig.fbp_images_index = self.index

        if object_in_view_layer(rig, context):
            bpy.ops.object.select_all(action='DESELECT')
            rig.select_set(True)
            context.view_layer.objects.active = rig

        if getattr(rig, "fbp_is_color_plane", False):
            fbp_load_active_procedural_frame_to_rig(rig)
        do_update_animation(rig)
        return {'FINISHED'}


class FBP_OT_InsertImagesAfterSelected(Operator):
    bl_idname      = "fbp.insert_images_after_selected"
    bl_label       = "Insert Frame"
    bl_description = "Insert a new frame after the active frame or after the last checked frame"
    bl_options     = {'REGISTER', 'UNDO'}

    frame_mode: EnumProperty(
        name="Frame Kind",
        description="Choose whether to add a procedural frame matching the current plane type or a transparent frame",
        items=[('AUTO', "Match Plane Type", "Create a color/gradient frame on procedural planes, or a transparent frame on image planes"),
               ('TRANSPARENT', "Transparent Frame", "Always create a transparent frame")],
        default='AUTO'
    )

    def execute(self, context):
        rig = context.object if context.object and getattr(context.object, "is_fbp_control", False) else None
        if not rig:
            rigs = get_selected_rigs(context)
            rig = rigs[0] if rigs else None
        if not rig or not rig.fbp_plane_target:
            self.report({'WARNING'}, "Select one Frame by Plane rig first")
            return {'CANCELLED'}
        if getattr(rig, "fbp_is_color_plane", False) and not fbp_color_plane_can_have_frames(rig):
            self.report({'WARNING'}, "Holdout planes are static masks and cannot have animation frames")
            return {'CANCELLED'}

        insert_at = None
        make_transparent = (self.frame_mode == 'TRANSPARENT')
        if getattr(rig, "fbp_is_color_plane", False) and not make_transparent:
            mat, label, is_empty = fbp_create_procedural_frame_material_for_rig(rig, len(rig.fbp_images) + 1)
            report_label = label
        else:
            mat = create_fbp_empty_material(f"Mat_Transparent_{rig.name}_{len(rig.fbp_images) + 1}")
            label = "Transparent Frame"
            is_empty = True
            report_label = "transparent frame"
        entry = (label, max(1, int(getattr(rig, 'fbp_global_duration', 1))), True, bool(is_empty), "")
        result = fbp_insert_sequence_entry(rig, entry, mat, insert_at)
        if result < 0:
            return {'CANCELLED'}

        self.report({'INFO'}, f"Inserted {report_label}")
        return {'FINISHED'}


class FBP_OT_InsertLinkedImageAfterSelected(Operator):
    bl_idname      = "fbp.insert_linked_image_after_selected"
    bl_label       = "Import Frame"
    bl_description = "Import a new image frame after the active frame or after the last checked frame"
    bl_options     = {'REGISTER', 'UNDO'}

    filepath:  StringProperty(subtype='FILE_PATH')
    directory: StringProperty(subtype='DIR_PATH')
    files:     CollectionProperty(type=bpy.types.OperatorFileListElement)

    def invoke(self, context, event):
        path = context.scene.fbp_project_path or context.scene.fbp_last_directory
        if path:
            self.directory = path
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        rig = context.object if context.object and getattr(context.object, "is_fbp_control", False) else None
        if not rig:
            rigs = get_selected_rigs(context)
            rig = rigs[0] if rigs else None
        if not rig or not rig.fbp_plane_target:
            self.report({'WARNING'}, "Select one Frame by Plane rig first")
            return {'CANCELLED'}
        if getattr(rig, "fbp_is_color_plane", False):
            self.report({'WARNING'}, "Color, Gradient and Holdout planes use procedural frames only; image import is available only for image planes")
            return {'CANCELLED'}

        chosen = None
        if self.files:
            for f in self.files:
                if os.path.splitext(f.name)[1].lower() in FBP_SUPPORTED_IMAGE_EXT:
                    chosen = f.name
                    break
        elif self.filepath and os.path.splitext(self.filepath)[1].lower() in FBP_SUPPORTED_IMAGE_EXT:
            chosen = os.path.basename(self.filepath)
            self.directory = os.path.dirname(self.filepath)

        if not chosen:
            self.report({'WARNING'}, "No supported image selected")
            return {'CANCELLED'}

        context.scene.fbp_last_directory = self.directory
        img_path = os.path.join(self.directory, chosen)
        mat = create_fbp_material(
            f"Mat_{chosen}", img_path,
            interp=getattr(rig, "fbp_interpolation", 'Closest'),
            opacity=rig.fbp_opacity,
            use_emission=rig.fbp_use_emission)
        entry = (chosen, max(1, int(getattr(rig, 'fbp_global_duration', 1))), True, False, img_path)
        insert_at = fbp_insert_sequence_entry(rig, entry, mat)
        if insert_at < 0:
            return {'CANCELLED'}
        if not rig.fbp_preview_path:
            rig.fbp_preview_path = img_path
        self.report({'INFO'}, f"Imported {chosen}")
        return {'FINISHED'}


class FBP_OT_LinkImageFrame(Operator):
    bl_idname      = "fbp.link_image_frame"
    bl_label       = "Link Image to Frame"
    bl_description = "Link or replace the image used by this frame"
    bl_options     = {'REGISTER', 'UNDO'}

    index:     IntProperty(default=-1)
    rig_name:  StringProperty(default="")
    filepath:  StringProperty(subtype='FILE_PATH')
    directory: StringProperty(subtype='DIR_PATH')
    files:     CollectionProperty(type=bpy.types.OperatorFileListElement)

    def invoke(self, context, event):
        path = context.scene.fbp_project_path or context.scene.fbp_last_directory
        if path:
            self.directory = path
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        rig = bpy.data.objects.get(self.rig_name) if self.rig_name else None
        if not rig or not getattr(rig, "is_fbp_control", False):
            rig = context.object if context.object and getattr(context.object, "is_fbp_control", False) else None
        if not rig:
            rigs = get_selected_rigs(context)
            rig = rigs[0] if rigs else None
        if not rig or not rig.fbp_plane_target:
            self.report({'WARNING'}, "Select one Frame by Plane rig first")
            return {'CANCELLED'}
        if not (0 <= self.index < len(rig.fbp_images)):
            self.report({'WARNING'}, "Invalid frame index")
            return {'CANCELLED'}
        if getattr(rig, "fbp_is_color_plane", False):
            self.report({'WARNING'}, "Procedural color/gradient frame rows cannot be replaced with image files")
            return {'CANCELLED'}

        chosen = None
        if self.files:
            for f in self.files:
                if os.path.splitext(f.name)[1].lower() in FBP_SUPPORTED_IMAGE_EXT:
                    chosen = f.name
                    break
        elif self.filepath and os.path.splitext(self.filepath)[1].lower() in FBP_SUPPORTED_IMAGE_EXT:
            chosen = os.path.basename(self.filepath)
            self.directory = os.path.dirname(self.filepath)

        if not chosen:
            self.report({'WARNING'}, "No supported image selected")
            return {'CANCELLED'}

        context.scene.fbp_last_directory = self.directory
        img_path = os.path.join(self.directory, chosen)
        mat = create_fbp_material(
            f"Mat_{chosen}", img_path,
            interp=getattr(rig, "fbp_interpolation", 'Closest'),
            opacity=rig.fbp_opacity,
            use_emission=rig.fbp_use_emission)

        plane = rig.fbp_plane_target
        while len(plane.data.materials) < len(rig.fbp_images):
            plane.data.materials.append(create_fbp_empty_material("Mat_Empty_Autofill"))
        plane.data.materials[self.index] = mat

        item = rig.fbp_images[self.index]
        item.name = chosen
        item.filepath = img_path
        item.is_empty = False
        item.is_selected = True
        rig.fbp_images_index = self.index

        if not rig.fbp_preview_path:
            rig.fbp_preview_path = img_path

        do_update_animation(rig)
        do_update_emission(rig)
        do_update_opacity(rig)
        self.report({'INFO'}, f"Linked {chosen}")
        return {'FINISHED'}


class FBP_OT_SelectAll(Operator):
    bl_idname      = "fbp.select_all"
    bl_label       = "Select All"
    bl_description = "Quickly select/deselect images in the list"

    action: StringProperty()

    def execute(self, context):
        for rig in get_selected_rigs(context):
            for item in rig.fbp_images:
                if   self.action == 'ALL':    item.is_selected = True
                elif self.action == 'NONE':   item.is_selected = False
                elif self.action == 'INVERT': item.is_selected = not item.is_selected
        return {'FINISHED'}


class FBP_OT_ListAction(Operator):
    bl_idname      = "fbp.list_action"
    bl_label       = "List Action"
    bl_description = "Edit the image list while keeping material slots in sync"
    bl_options     = {'UNDO'}

    action: StringProperty()

    def _snapshot_item(self, item):
        return (item.name, item.duration, item.is_selected, getattr(item, 'is_empty', False), getattr(item, 'filepath', ''))

    def _restore_item(self, dst, data):
        dst.name = data[0]
        dst.duration = data[1]
        dst.is_selected = data[2]
        dst.is_empty = bool(data[3]) if len(data) > 3 else False
        dst.filepath = data[4] if len(data) > 4 else ""

    def _get_sequence_data(self, rig):
        plane = rig.fbp_plane_target
        if not plane:
            return [], []

        image_data = [self._snapshot_item(item) for item in rig.fbp_images]
        material_data = [
            plane.data.materials[i] if i < len(plane.data.materials) else None
            for i in range(len(image_data))
        ]
        return image_data, material_data

    def _rebuild_sequence(self, rig, image_data, material_data, new_index=None):
        plane = rig.fbp_plane_target
        if not plane:
            return

        rig.fbp_images.clear()
        plane.data.materials.clear()

        for data, mat in zip(image_data, material_data):
            item = rig.fbp_images.add()
            self._restore_item(item, data)
            if mat:
                plane.data.materials.append(mat)

        if len(rig.fbp_images) > 0:
            if new_index is None:
                new_index = min(rig.fbp_images_index, len(rig.fbp_images) - 1)
            rig.fbp_images_index = max(0, min(new_index, len(rig.fbp_images) - 1))
        else:
            rig.fbp_images_index = 0

        do_update_animation(rig)

    def _checked_indices(self, image_data):
        return [i for i, data in enumerate(image_data) if data[2]]

    def execute(self, context):
        for rig in get_selected_rigs(context):
            plane = rig.fbp_plane_target
            if not plane or len(rig.fbp_images) == 0:
                continue

            idx = max(0, min(rig.fbp_images_index, len(rig.fbp_images) - 1))
            image_data, material_data = self._get_sequence_data(rig)

            if self.action == 'REMOVE':
                # X = delete checked images. If none are checked, delete only the active row.
                remove_indices = self._checked_indices(image_data)
                if not remove_indices and idx < len(image_data):
                    remove_indices = [idx]

                for i in reversed(remove_indices):
                    if 0 <= i < len(image_data):
                        del image_data[i]
                        del material_data[i]

                new_index = min(idx, len(image_data) - 1) if image_data else 0
                self._rebuild_sequence(rig, image_data, material_data, new_index)

            elif self.action == 'MOVE_UP':
                if idx <= 0:
                    continue

                image_data[idx - 1], image_data[idx] = image_data[idx], image_data[idx - 1]
                material_data[idx - 1], material_data[idx] = material_data[idx], material_data[idx - 1]
                self._rebuild_sequence(rig, image_data, material_data, idx - 1)

            elif self.action == 'MOVE_DOWN':
                if idx >= len(image_data) - 1:
                    continue

                image_data[idx + 1], image_data[idx] = image_data[idx], image_data[idx + 1]
                material_data[idx + 1], material_data[idx] = material_data[idx], material_data[idx + 1]
                self._rebuild_sequence(rig, image_data, material_data, idx + 1)

            elif self.action == 'DUPLICATE_SELECTED':
                selected_indices = self._checked_indices(image_data)

                if not selected_indices:
                    self.report({'WARNING'}, "No checked images to duplicate")
                    continue

                insert_at = selected_indices[-1] + 1
                insert_images = [image_data[i] for i in selected_indices]
                if getattr(rig, "fbp_is_color_plane", False):
                    insert_mats = [material_data[i].copy() if material_data[i] else None for i in selected_indices]
                else:
                    insert_mats = [material_data[i] for i in selected_indices]

                image_data[insert_at:insert_at] = insert_images
                material_data[insert_at:insert_at] = insert_mats
                self._rebuild_sequence(rig, image_data, material_data, insert_at)

            elif self.action == 'SORT_NATURAL':
                pairs = list(zip(image_data, material_data))
                pairs.sort(key=lambda pair: natural_sort_key(pair[0][0]))
                image_data = [pair[0] for pair in pairs]
                material_data = [pair[1] for pair in pairs]
                self._rebuild_sequence(rig, image_data, material_data, 0)

            elif self.action == 'REMOVE_UNCHECKED':
                keep_indices = self._checked_indices(image_data)

                if not keep_indices:
                    self.report({'WARNING'}, "Cannot remove all images: no checked images")
                    continue

                image_data = [image_data[i] for i in keep_indices]
                material_data = [material_data[i] for i in keep_indices]
                new_index = min(idx, len(image_data) - 1)
                self._rebuild_sequence(rig, image_data, material_data, new_index)

        return {'FINISHED'}


class FBP_OT_BatchApply(Operator):
    bl_idname      = "fbp.batch_apply"
    bl_label       = "Apply"
    bl_description = "Apply the duration to all checked images"
    bl_options     = {'UNDO'}

    def execute(self, context):
        for rig in get_selected_rigs(context):
            for item in rig.fbp_images:
                if item.is_selected:
                    item.duration = rig.fbp_global_duration
            do_update_animation(rig)
        return {'FINISHED'}


class FBP_OT_ReverseSequence(Operator):
    bl_idname      = "fbp.reverse_sequence"
    bl_label       = "Reverse Sequence"
    bl_description = "Completely reverse the image order"
    bl_options     = {'UNDO'}

    def execute(self, context):
        for rig in get_selected_rigs(context):
            plane = rig.fbp_plane_target
            if not plane:
                continue
            reversed_data = [(item.name, item.duration, item.is_selected, getattr(item, 'is_empty', False), getattr(item, 'filepath', ''))
                             for item in rig.fbp_images]
            reversed_data.reverse()
            materials = list(plane.data.materials)
            materials.reverse()
            plane.data.materials.clear()
            for mat in materials:
                plane.data.materials.append(mat)
            rig.fbp_images.clear()
            for data in reversed_data:
                item = rig.fbp_images.add()
                item.name = data[0]
                item.duration = data[1]
                item.is_selected = data[2]
                item.is_empty = bool(data[3]) if len(data) > 3 else False
                item.filepath = data[4] if len(data) > 4 else ""
            do_update_animation(rig)
        return {'FINISHED'}



class FBP_OT_PopupSequenceSettings(Operator):
    bl_idname = "fbp.popup_sequence_settings"
    bl_label = "Timing / Sequence Settings"
    bl_description = "Open timing and sequence controls for the selected Frame by Plane layer"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        if not get_selected_rigs(context):
            self.report({'WARNING'}, "Select a Frame by Plane layer first")
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        rig = get_selected_rigs(context)[0]
        layout = self.layout
        layout.label(text=rig.name, icon=fbp_icon("TIME"))
        row = layout.row(align=True)
        row.prop(rig, "fbp_start_frame", text="Start")
        row.operator("fbp.set_current_frame", text="", icon=fbp_icon("EYEDROPPER"))
        layout.prop(rig, "fbp_loop_mode", text="Playback")
        row = layout.row(align=True)
        row.operator("fbp.reverse_sequence", text="Reverse", icon=fbp_icon("ARROW_LEFTRIGHT"))
        row.operator("fbp.list_action", text="Sort A-Z", icon=fbp_icon("SORTALPHA")).action = 'SORT_NATURAL'
        row = layout.row(align=True)
        row.prop(rig, "fbp_global_duration", text="Duration")
        row.operator("fbp.batch_apply", text="Apply to Checked", icon=fbp_icon("CHECKMARK"))

    def execute(self, context):
        return {'FINISHED'}


class FBP_OT_DuplicateSelectedLayers(Operator):
    bl_idname      = "fbp.duplicate_selected_layers"
    bl_label       = "Duplicate Selected Layers"
    bl_description = "Duplicate selected Frame By Plane rigs with their plane, materials and image list"
    bl_options     = {'UNDO'}

    def _copy_image_list(self, src_rig, dst_rig):
        dst_rig.fbp_images.clear()
        for src_item in src_rig.fbp_images:
            dst_item = dst_rig.fbp_images.add()
            dst_item.name = src_item.name
            dst_item.duration = src_item.duration
            dst_item.is_selected = src_item.is_selected
            dst_item.is_empty = getattr(src_item, 'is_empty', False)
            dst_item.filepath = getattr(src_item, 'filepath', '')
        dst_rig.fbp_images_index = min(src_rig.fbp_images_index, max(0, len(dst_rig.fbp_images) - 1))

    def _copy_materials(self, src_plane, dst_plane):
        dst_plane.data.materials.clear()
        for mat in src_plane.data.materials:
            if not mat:
                continue
            new_mat = mat.copy()
            new_mat.name = mat.name + "_Copy"
            dst_plane.data.materials.append(new_mat)

    def execute(self, context):
        selected_rigs = get_selected_rigs(context)
        duplicated = []

        if not selected_rigs:
            self.report({'WARNING'}, "No Frame By Plane rig selected")
            return {'CANCELLED'}

        for rig in selected_rigs:
            plane = rig.fbp_plane_target
            if not plane:
                continue

            source_collection = get_primary_fbp_collection(rig) or context.collection or context.scene.collection
            rig_collections = [source_collection]
            plane_collections = [source_collection]
            active_collection = source_collection

            new_rig = rig.copy()
            if rig.data:
                new_rig.data = rig.data.copy()
            new_rig.name = rig.name + "_Copy"
            new_rig.is_fbp_control = True
            new_rig.fbp_collection_name = source_collection.name if source_collection else ""

            if not any(existing == new_rig for existing in active_collection.objects):
                active_collection.objects.link(new_rig)
            for coll in rig_collections:
                if coll != active_collection and not any(existing == new_rig for existing in coll.objects):
                    coll.objects.link(new_rig)

            new_plane = plane.copy()
            if plane.data:
                new_plane.data = plane.data.copy()
            new_plane.name = plane.name + "_Copy"
            new_plane.is_fbp_plane = True
            new_plane.fbp_collection_name = source_collection.name if source_collection else ""

            if not any(existing == new_plane for existing in active_collection.objects):
                active_collection.objects.link(new_plane)
            for coll in plane_collections:
                if coll != active_collection and not any(existing == new_plane for existing in coll.objects):
                    coll.objects.link(new_plane)

            new_rig.matrix_world = rig.matrix_world.copy()
            plane_world = plane.matrix_world.copy()
            new_plane.matrix_world = plane_world
            new_plane.parent = new_rig
            new_plane.matrix_world = plane_world
            new_plane.hide_select = plane.hide_select

            self._copy_materials(plane, new_plane)
            self._copy_image_list(rig, new_rig)
            new_rig.fbp_plane_target = new_plane
            new_rig.fbp_preview_path = rig.fbp_preview_path

            do_update_animation(new_rig)
            do_update_emission(new_rig)
            do_update_opacity(new_rig)
            duplicated.append(new_rig)

        if not duplicated:
            self.report({'WARNING'}, "No valid Frame By Plane layers duplicated")
            return {'CANCELLED'}

        context.view_layer.update()
        bpy.ops.object.select_all(action='DESELECT')
        selectable = []
        for obj in duplicated:
            if not object_in_view_layer(obj, context):
                ensure_object_in_active_collection(obj, context)
            if object_in_view_layer(obj, context):
                obj.select_set(True)
                selectable.append(obj)
        if selectable:
            context.view_layer.objects.active = selectable[-1]

        sync_layer_collection(context)
        self.report({'INFO'}, f"Duplicated {len(duplicated)} layer(s)")
        return {'FINISHED'}


def fbp_sequence_entries_from_rig(rig):
    plane = getattr(rig, "fbp_plane_target", None)
    entries = []
    if not plane:
        return entries
    for i, item in enumerate(rig.fbp_images):
        mat = plane.data.materials[i] if i < len(plane.data.materials) else None
        entries.append({
            "name": item.name,
            "duration": item.duration,
            "is_selected": item.is_selected,
            "is_empty": getattr(item, "is_empty", False),
            "filepath": getattr(item, "filepath", ""),
            "material": mat,
        })
    return entries


def fbp_apply_sequence_entries_to_rig(rig, entries):
    plane = getattr(rig, "fbp_plane_target", None)
    if not plane:
        return False
    rig.fbp_images.clear()
    plane.data.materials.clear()
    for entry in entries:
        mat = entry.get("material")
        if mat:
            plane.data.materials.append(mat)
        item = rig.fbp_images.add()
        item.name = entry.get("name", "Image")
        item.duration = int(entry.get("duration", getattr(rig, "fbp_global_duration", 1)) or 1)
        item.is_selected = bool(entry.get("is_selected", True))
        item.is_empty = bool(entry.get("is_empty", False))
        item.filepath = entry.get("filepath", "")
    rig.fbp_images_index = min(max(0, rig.fbp_images_index), max(0, len(rig.fbp_images) - 1))
    if entries:
        first_path = entries[0].get("filepath", "")
        if first_path:
            rig.fbp_preview_path = first_path
    do_update_animation(rig)
    do_update_emission(rig)
    do_update_opacity(rig)
    return True


class FBP_OT_MergeSelectedToActiveSequence(Operator):
    bl_idname = "fbp.merge_selected_to_active_sequence"
    bl_label = "Convert to Single Animated Plane"
    bl_description = "Merge selected Frame by Plane layers into the active layer sequence and delete the others"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        active = context.view_layer.objects.active
        if active and getattr(active, "is_fbp_plane", False) and getattr(active.parent, "is_fbp_control", False):
            active = active.parent
        if not active or not is_fbp_layer_object(active):
            self.report({'WARNING'}, "Make the target Frame by Plane rig active")
            return {'CANCELLED'}
        rigs = get_selected_fbp_roots(context)
        if active not in rigs:
            rigs.append(active)
        rigs = sorted(set(rigs), key=lambda r: (getattr(r, "fbp_depth_order", 0), natural_sort_key(r.name)))
        if len(rigs) < 2:
            self.report({'WARNING'}, "Select at least two Frame by Plane layers")
            return {'CANCELLED'}
        entries = []
        for rig in rigs:
            entries.extend(fbp_sequence_entries_from_rig(rig))
        if not entries:
            return {'CANCELLED'}
        fbp_apply_sequence_entries_to_rig(active, entries)
        delete_fbp_rigs(context, [rig for rig in rigs if rig != active])
        bpy.ops.object.select_all(action='DESELECT')
        if object_in_view_layer(active, context):
            active.select_set(True)
            context.view_layer.objects.active = active
        sync_layer_collection(context)
        self.report({'INFO'}, f"Merged {len(rigs)} layers into {active.name}")
        return {'FINISHED'}


class FBP_OT_SplitSelectedImagesToNewPlane(Operator):
    bl_idname = "fbp.split_selected_images_to_new_plane"
    bl_label = "Split Sequence"
    bl_description = "Move selected images from the active sequence to a new plane in the same position"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rig = context.object if context.object and is_fbp_layer_object(context.object) else None
        if not rig:
            rigs = get_selected_rigs(context)
            rig = rigs[0] if rigs else None
        if not rig or not getattr(rig, "fbp_plane_target", None):
            self.report({'WARNING'}, "Select one Frame by Plane rig")
            return {'CANCELLED'}
        plane = rig.fbp_plane_target
        entries = fbp_sequence_entries_from_rig(rig)
        selected_indices = [i for i, item in enumerate(rig.fbp_images) if item.is_selected]
        if not selected_indices:
            self.report({'WARNING'}, "Select images in the sequence list first")
            return {'CANCELLED'}
        selected_entries = [entries[i] for i in selected_indices]
        remaining_entries = [entry for i, entry in enumerate(entries) if i not in set(selected_indices)]
        if not selected_entries or not remaining_entries:
            self.report({'WARNING'}, "Leave at least one image in the original plane")
            return {'CANCELLED'}

        source_collection = get_primary_fbp_collection(rig) or context.collection or context.scene.collection
        new_rig = rig.copy()
        if rig.data:
            new_rig.data = rig.data.copy()
        new_rig.name = rig.name + "_Split"
        new_rig.is_fbp_control = True
        source_collection.objects.link(new_rig)

        new_plane = plane.copy()
        if plane.data:
            new_plane.data = plane.data.copy()
        new_plane.name = plane.name + "_Split"
        new_plane.is_fbp_plane = True
        source_collection.objects.link(new_plane)
        new_plane.parent = new_rig
        new_plane.matrix_world = plane.matrix_world.copy()
        new_plane.hide_select = plane.hide_select
        new_rig.fbp_plane_target = new_plane
        new_rig.fbp_collection_name = getattr(rig, "fbp_collection_name", "")
        new_plane.fbp_collection_name = getattr(plane, "fbp_collection_name", "")

        fbp_apply_sequence_entries_to_rig(new_rig, selected_entries)
        fbp_apply_sequence_entries_to_rig(rig, remaining_entries)

        bpy.ops.object.select_all(action='DESELECT')
        if object_in_view_layer(new_rig, context):
            new_rig.select_set(True)
            context.view_layer.objects.active = new_rig
        sync_layer_collection(context)
        self.report({'INFO'}, f"Split {len(selected_entries)} frame(s) to {new_rig.name}")
        return {'FINISHED'}


class FBP_OT_DeleteSequence(Operator):
    bl_idname      = "fbp.delete_sequence"
    bl_label       = "Delete Sequence"
    bl_description = "Delete selected Frame By Plane rigs and their planes"
    bl_options     = {'UNDO'}

    def execute(self, context):
        selected_rigs = get_selected_fbp_roots(context)
        if not selected_rigs:
            idx = context.scene.fbp_layer_stack_index
            if 0 <= idx < len(context.scene.fbp_layers):
                rig = _safe_layer_obj(context.scene.fbp_layers[idx])
                if rig and is_fbp_layer_object(rig):
                    selected_rigs = [rig]

        if not selected_rigs:
            sync_layer_collection(context)
            self.report({'WARNING'}, "No Frame By Plane rig selected")
            return {'CANCELLED'}
        deleted = delete_fbp_rigs(context, selected_rigs)
        if deleted <= 0:
            return {'CANCELLED'}
        self.report({'INFO'}, f"Deleted {deleted} Frame By Plane layer(s)")
        return {'FINISHED'}


class FBP_OT_DeleteOrDefault(Operator):
    bl_idname      = "fbp.delete_or_default"
    bl_label       = "Delete"
    bl_description = "Delete FBP rigs together with their planes, otherwise use Blender's standard delete"
    bl_options     = {'UNDO'}

    def invoke(self, context, event):
        roots = get_selected_fbp_roots(context)
        if roots:
            deleted = delete_fbp_rigs(context, roots)
            if deleted > 0:
                self.report({'INFO'}, f"Deleted {deleted} Frame By Plane layer(s)")
                return {'FINISHED'}
            return {'CANCELLED'}
        return bpy.ops.object.delete('INVOKE_DEFAULT')



class FBP_OT_ToggleCollectionCollapse(Operator):
    bl_idname      = "fbp.toggle_collection_collapse"
    bl_label       = "Collapse Collection"
    bl_description = "Open or collapse this collection in the Frame by Plane layer tree"
    bl_options     = {'UNDO'}

    collection_name: StringProperty(default="")

    def execute(self, context):
        coll = bpy.data.collections.get(self.collection_name)
        if not coll:
            return {'CANCELLED'}
        coll.fbp_collapsed = not coll.fbp_collapsed
        return {'FINISHED'}


class FBP_OT_TogglePendingCollectionCollapse(Operator):
    bl_idname = "fbp.toggle_pending_collection_collapse"
    bl_label = "Open Setup Collection"
    bl_description = "Open or collapse this collection in the Multiplane Setup preview"
    bl_options = {'UNDO'}

    collection_name: StringProperty(default="")

    def execute(self, context):
        sc = context.scene
        name = self.collection_name or 'Unsorted'
        set_pending_collection_open(sc, name, not pending_collection_is_open(sc, name))
        return {'FINISHED'}


class FBP_OT_SelectCollectionLayers(Operator):
    bl_idname      = "fbp.select_collection_layers"
    bl_label       = "Toggle Collection Layer Selection"
    bl_description = "Select or deselect all Frame by Plane rig layers inside this collection. Shift-click adds/removes without clearing other selections"
    bl_options     = {'UNDO'}

    collection_name: StringProperty(default="")
    extend: BoolProperty(default=False)

    def invoke(self, context, event):
        self.extend = bool(event.shift)
        return self.execute(context)

    def execute(self, context):
        coll = bpy.data.collections.get(self.collection_name)
        if not coll:
            return {'CANCELLED'}
        rigs = [rig for rig in iter_fbp_rigs_in_collection(coll, True) if object_in_view_layer(rig, context)]
        if not rigs:
            return {'CANCELLED'}
        all_selected = all(rig.select_get() for rig in rigs)
        target_state = not all_selected
        if not self.extend and target_state:
            bpy.ops.object.select_all(action='DESELECT')
        for rig in rigs:
            try:
                rig.select_set(target_state)
            except ReferenceError:
                continue
        if target_state:
            active = rigs[-1]
            context.view_layer.objects.active = active
            for i, item in enumerate(context.scene.fbp_layers):
                try:
                    if item.obj == active:
                        context.scene.fbp_layer_stack_index = i
                        break
                except ReferenceError:
                    pass
        return {'FINISHED'}


class FBP_OT_ToggleCollectionVisibility(Operator):
    bl_idname      = "fbp.toggle_collection_visibility"
    bl_label       = "Toggle Collection Visibility"
    bl_description = "Hide/show this collection and all its Frame by Plane layers"
    bl_options     = {'UNDO'}

    collection_name: StringProperty(default="")

    def execute(self, context):
        coll = bpy.data.collections.get(self.collection_name)
        if not coll:
            return {'CANCELLED'}
        new_hidden = not collection_is_hidden_in_view_layer(context, coll)
        try:
            coll.hide_viewport = new_hidden
        except Exception:
            pass
        try:
            layer_coll = find_layer_collection(context.view_layer.layer_collection, coll)
            if layer_coll:
                layer_coll.hide_viewport = new_hidden
        except Exception:
            pass
        # Keep object-level visibility intact; the Collection is the parent switch.
        update_global_visibility(context)
        return {'FINISHED'}


class FBP_OT_ToggleCollectionLock(Operator):
    bl_idname      = "fbp.toggle_collection_lock"
    bl_label       = "Toggle Collection Lock"
    bl_description = "Lock/unlock all Frame by Plane rigs and planes inside this collection"
    bl_options     = {'UNDO'}

    collection_name: StringProperty(default="")

    def execute(self, context):
        coll = bpy.data.collections.get(self.collection_name)
        if not coll:
            return {'CANCELLED'}
        rigs = list(iter_fbp_rigs_in_collection(coll, True))
        if not rigs:
            return {'CANCELLED'}
        all_locked = all(getattr(rig, 'hide_select', False) for rig in rigs)
        new_state = not all_locked
        for rig in rigs:
            rig.hide_select = new_state
            plane = getattr(rig, 'fbp_plane_target', None)
            if plane:
                plane.hide_select = new_state
        return {'FINISHED'}


class FBP_OT_DeleteCollectionLayers(Operator):
    bl_idname      = "fbp.delete_collection_layers"
    bl_label       = "Delete Collection Layers"
    bl_description = "Delete all Frame by Plane layers inside this collection. The collection itself remains"
    bl_options     = {'UNDO'}

    collection_name: StringProperty(default="")

    def execute(self, context):
        coll = bpy.data.collections.get(self.collection_name)
        if not coll:
            return {'CANCELLED'}
        rigs = list(iter_fbp_rigs_in_collection(coll, True))
        deleted = delete_fbp_rigs(context, rigs)
        self.report({'INFO'}, f"Deleted {deleted} layer(s) from {coll.name}")
        return {'FINISHED'} if deleted else {'CANCELLED'}




class FBP_OT_RepairRenderState(Operator):
    bl_idname      = "fbp.repair_render_state"
    bl_label       = "Repair FBP Render State"
    bl_description = "Repair material slots, UVs and material indices before rendering"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        sync_layer_collection(context)
        fixed = fbp_repair_all_render_state(context.scene, context.scene.frame_current)
        self.report({'INFO'}, f"Render state repaired on {fixed} FBP layer(s)")
        return {'FINISHED'}


class FBP_OT_BackgroundRenderFrames(Operator):
    bl_idname      = "fbp.background_render_frames"
    bl_label       = "Background Render FBP Frames"
    bl_description = "Render the animation frame by frame in a separate background Blender process, avoiding viewport crashes"
    bl_options     = {'REGISTER'}

    def execute(self, context):
        sc = context.scene
        if not bpy.data.is_saved:
            self.report({'WARNING'}, "Save the .blend file first")
            return {'CANCELLED'}

        start = int(sc.fbp_emergency_render_start) if sc.fbp_emergency_render_start > 0 else int(sc.frame_start)
        end = int(sc.fbp_emergency_render_end) if sc.fbp_emergency_render_end > 0 else int(sc.frame_end)
        if end < start:
            self.report({'WARNING'}, "End frame must be after Start frame")
            return {'CANCELLED'}

        out_dir = os.path.join(os.path.dirname(bpy.data.filepath), "FBP_Render_Frames")
        os.makedirs(out_dir, exist_ok=True)

        prefix = sc.fbp_emergency_render_prefix or "frame_"
        blend_path = bpy.data.filepath
        blender_bin = bpy.app.binary_path

        # Repair and save before spawning the background instance.
        fbp_repair_all_render_state(sc, sc.frame_current)
        bpy.ops.wm.save_as_mainfile(filepath=blend_path)

        script = f"""
import bpy
import os

OUT_DIR = {out_dir!r}
START = {start}
END = {end}
PREFIX = {prefix!r}

scene = bpy.context.scene
os.makedirs(OUT_DIR, exist_ok=True)

scene.frame_start = START
scene.frame_end = END
scene.render.filepath = os.path.join(OUT_DIR, PREFIX)
scene.render.image_settings.file_format = 'PNG'

if hasattr(scene.render, "use_file_extension"):
    scene.render.use_file_extension = True

print(f"[FBP_BG] Rendering animation {{START}}-{{END}} -> {{scene.render.filepath}}")
bpy.ops.render.render(animation=True)
print("[FBP_BG] DONE")
"""

        temp_dir = tempfile.mkdtemp(prefix="fbp_bg_render_")
        script_path = os.path.join(temp_dir, "fbp_background_render.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script)

        cmd = [blender_bin, "-b", blend_path, "--python", script_path]
        try:
            self.report({'INFO'}, f"Background render started: {start}-{end}. Blender may freeze until it finishes.")
            result = subprocess.run(cmd, check=False)
            if result.returncode != 0:
                self.report({'ERROR'}, f"Background render failed with code {result.returncode}")
                return {'CANCELLED'}
        except Exception as exc:
            self.report({'ERROR'}, f"Could not start background render: {exc}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Rendered frames to {out_dir}")
        return {'FINISHED'}




class FBP_OT_CreateColorPlane(Operator):
    bl_idname = "fbp.create_color_plane"
    bl_label = "Create Color Plane"
    bl_description = "Create a rigged camera-ratio color, gradient or holdout plane"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        sc = context.scene
        kind = getattr(sc, "fbp_color_plane_type", 'CUSTOM')
        gradient_settings = None
        if kind == 'HOLDOUT':
            color = (0.0, 0.0, 0.0, 1.0); name = "Holdout Plane"; holdout = True
        elif kind == 'GRADIENT':
            color = tuple(sc.fbp_gradient_color_b); name = "Gradient Plane"; holdout = False
            gradient_settings = {
                'mode': sc.fbp_gradient_mode, 'kind': sc.fbp_gradient_kind,
                'color_a': tuple(sc.fbp_gradient_color_a), 'color_b': tuple(sc.fbp_gradient_color_b),
                'reverse': bool(sc.fbp_gradient_reverse),
                'offset_x': float(getattr(sc, 'fbp_gradient_offset_x', 0.0)),
                'offset_y': float(getattr(sc, 'fbp_gradient_offset_y', 0.0)),
                'scale_x': float(getattr(sc, 'fbp_gradient_scale_x', 1.0)),
                'scale_y': float(getattr(sc, 'fbp_gradient_scale_y', 1.0)),
                'rotation': float(getattr(sc, 'fbp_gradient_rotation', 0.0)),
            }
        else:
            color = tuple(sc.fbp_color_plane_color); name = "Color Plane"; holdout = False
        coll = get_or_create_child_collection(sc.collection, FBP_PROJECT_COLLECTION_PREFIX + "Color Planes", 'COLOR_09')
        rig = build_fbp_color_rig(context, name, color, sc.fbp_color_plane_emission, holdout, target_collection=coll, gradient_settings=gradient_settings)
        if gradient_settings:
            copy_scene_preview_ramp_to_rig(sc, rig)
        sync_layer_collection(context)
        bpy.ops.object.select_all(action='DESELECT')
        if object_in_view_layer(rig, context):
            rig.select_set(True); context.view_layer.objects.active = rig
        sc.fbp_show_create_tools = False
        self.report({'INFO'}, f"Created {rig.name}")
        return {'FINISHED'}


class FBP_OT_ExtendSelectedPlane(Operator):
    bl_idname = "fbp.extend_selected_plane"
    bl_label = "Extend Plane"
    bl_description = "Extend the selected layer plane borders beyond the rig frame"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rigs = get_selected_rigs(context)
        if not rigs:
            self.report({'WARNING'}, "Select a Frame by Plane layer first")
            return {'CANCELLED'}
        count = 0
        for rig in rigs:
            if set_plane_mesh_extension(
                rig, rig.fbp_extend_left, rig.fbp_extend_right, rig.fbp_extend_bottom, rig.fbp_extend_top,
                rig.fbp_extend_mode, rig.fbp_crop_left, rig.fbp_crop_right, rig.fbp_crop_bottom, rig.fbp_crop_top):
                count += 1
        self.report({'INFO'}, f"Extended {count} plane(s)")
        return {'FINISHED'} if count else {'CANCELLED'}


class FBP_OT_ResetPlaneExtension(Operator):
    bl_idname = "fbp.reset_plane_extension"
    bl_label = "Reset Plane Extension"
    bl_description = "Reset selected layer plane borders to the rig frame"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rigs = get_selected_rigs(context)
        count = 0
        for rig in rigs:
            if set_plane_mesh_extension(rig, 0.0, 0.0, 0.0, 0.0, getattr(context.scene, 'fbp_extend_mode', 'EDGE')):
                count += 1
        context.scene.fbp_extend_left = 0.0
        context.scene.fbp_extend_right = 0.0
        context.scene.fbp_extend_top = 0.0
        context.scene.fbp_extend_bottom = 0.0
        self.report({'INFO'}, f"Reset {count} plane(s)")
        return {'FINISHED'} if count else {'CANCELLED'}


class FBP_OT_ResetWiggle(Operator):
    bl_idname = "fbp.reset_wiggle"
    bl_label = "Reset Wiggle"
    bl_description = "Disable wiggle and remove all noise modifiers created by Frame by Plane"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rigs = get_selected_rigs(context)
        count = 0
        for rig in rigs:
            rig.fbp_wiggle_enabled = False
            rig.fbp_wiggle_position = True
            rig.fbp_wiggle_rotation = False
            rig.fbp_wiggle_pos_strength = 0.08
            rig.fbp_wiggle_rot_strength = 3.0
            rig.fbp_wiggle_scale = 18.0
            rig.fbp_wiggle_phase = 0.0
            rig.fbp_wiggle_use_range = False
            rig.fbp_wiggle_frame_start = context.scene.frame_start
            rig.fbp_wiggle_frame_end = context.scene.frame_end
            rig.fbp_wiggle_blend_in = 12.0
            rig.fbp_wiggle_blend_out = 12.0
            count += fbp_remove_wiggle_modifiers(rig)
        self.report({'INFO'}, f"Reset wiggle on {len(rigs)} rig(s)")
        return {'FINISHED'}


class FBP_OT_PopupWiggle(Operator):
    bl_idname = "fbp.popup_wiggle"
    bl_label = "Wiggle"
    bl_description = "Create a position and/or rotation wiggle using F-Curve noise modifiers"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        rigs = get_selected_rigs(context)
        if not rigs:
            self.report({'WARNING'}, "Select a Frame by Plane layer first")
            return {'CANCELLED'}
        for rig in rigs:
            if rig.fbp_wiggle_frame_end <= rig.fbp_wiggle_frame_start:
                rig.fbp_wiggle_frame_start = context.scene.frame_start
                rig.fbp_wiggle_frame_end = context.scene.frame_end
            rig.fbp_wiggle_enabled = True
            fbp_apply_wiggle_to_rig(rig, context.scene)
        return context.window_manager.invoke_props_dialog(self, width=380)

    def draw(self, context):
        rig = get_selected_rigs(context)[0]
        layout = self.layout
        layout.label(text=rig.name, icon=fbp_icon('MOD_NOISE'))
        axes_text = "Position axes: X/Z · Rotation axis: Y" if getattr(rig, 'fbp_is_vertical', False) else "Position axes: X/Y · Rotation axis: Z"
        box = layout.box()
        row = box.row(align=True)
        row.prop(rig, 'fbp_wiggle_position', text='Position', icon=fbp_icon("EMPTY_ARROWS"), toggle=True)
        row.prop(rig, 'fbp_wiggle_rotation', text='Rotation', icon=fbp_icon("FILE_REFRESH"), toggle=True)
        if rig.fbp_wiggle_position:
            box.prop(rig, 'fbp_wiggle_pos_strength', text='Position Strength')
        if rig.fbp_wiggle_rotation:
            box.prop(rig, 'fbp_wiggle_rot_strength', text='Rotation Strength')
        box.prop(rig, 'fbp_wiggle_scale', text='Scale')
        box.prop(rig, 'fbp_wiggle_phase', text='Offset')
        range_box = layout.box()
        range_box.prop(rig, 'fbp_wiggle_use_range', text='Blend In / Out', toggle=True)
        if rig.fbp_wiggle_use_range:
            row = range_box.row(align=True)
            row.prop(rig, 'fbp_wiggle_frame_start', text='Start')
            row.prop(rig, 'fbp_wiggle_frame_end', text='End')
            row = range_box.row(align=True)
            row.prop(rig, 'fbp_wiggle_blend_in', text='Blend In')
            row.prop(rig, 'fbp_wiggle_blend_out', text='Blend Out')
        layout.separator()
        layout.operator('fbp.reset_wiggle', text='Reset Wiggle', icon=fbp_icon('FILE_REFRESH'))

    def execute(self, context):
        rigs = get_selected_rigs(context)
        for rig in rigs:
            if rig.fbp_wiggle_position or rig.fbp_wiggle_rotation:
                rig.fbp_wiggle_enabled = True
            fbp_apply_wiggle_to_rig(rig, context.scene)
        return {'FINISHED'}



class FBP_OT_PopupEdges(Operator):
    bl_idname = "fbp.popup_edges"
    bl_label = "Edges"
    bl_description = "Edit Crop and Extend in one floating window"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        if not get_selected_rigs(context):
            self.report({'WARNING'}, "Select a Frame by Plane layer first")
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        rig = get_selected_rigs(context)[0]
        layout = self.layout
        layout.label(text=rig.name, icon=fbp_icon("MOD_BOOLEAN"))

        crop_box = layout.box()
        crop_box.label(text="Crop", icon=fbp_icon("MOD_BOOLEAN"))
        grid = crop_box.grid_flow(columns=2, align=True)
        grid.prop(rig, "fbp_crop_left", text="Left")
        grid.prop(rig, "fbp_crop_right", text="Right")
        grid.prop(rig, "fbp_crop_top", text="Top")
        grid.prop(rig, "fbp_crop_bottom", text="Bottom")

        extend_box = layout.box()
        extend_box.label(text="Extend", icon=fbp_icon("FULLSCREEN_ENTER"))
        extend_box.prop(rig, "fbp_extend_mode", text="Mode")
        grid = extend_box.grid_flow(columns=2, align=True)
        grid.prop(rig, "fbp_extend_left", text="Left")
        grid.prop(rig, "fbp_extend_right", text="Right")
        grid.prop(rig, "fbp_extend_top", text="Top")
        grid.prop(rig, "fbp_extend_bottom", text="Bottom")

        row = layout.row(align=True)
        row.operator("fbp.reset_plane_extension", text="Reset Edges", icon=fbp_icon("FILE_REFRESH"))

    def execute(self, context):
        for rig in get_selected_rigs(context):
            update_object_padding_cb(rig, context)
        return {'FINISHED'}


class FBP_OT_SetSelectedHoldout(Operator):
    bl_idname = "fbp.set_selected_holdout"
    bl_label = "Set Selected Holdout"
    bl_description = "Turn selected Frame by Plane planes into holdout masks"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        count = 0
        for rig in get_selected_rigs(context):
            if fbp_apply_holdout_materials_to_rig(rig):
                count += 1
        self.report({'INFO'}, f"Holdout applied to {count} layer(s)")
        return {'FINISHED'} if count else {'CANCELLED'}


class FBP_OT_HoldoutAllExceptSelected(Operator):
    bl_idname = "fbp.holdout_all_except_selected"
    bl_label = "Holdout All Except Selected"
    bl_description = "Apply holdout to every Frame by Plane layer except the selected ones"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected = set(get_selected_rigs(context))
        if not selected:
            self.report({'WARNING'}, "Select the layer(s) that should stay rendered")
            return {'CANCELLED'}
        count = 0
        for rig in [obj for obj in context.scene.objects if is_fbp_layer_object(obj)]:
            if rig in selected:
                restore_original_materials_from_holdout(rig)
                continue
            if fbp_apply_holdout_materials_to_rig(rig):
                count += 1
        self.report({'INFO'}, f"Holdout applied to {count} other layer(s)")
        return {'FINISHED'}


class FBP_OT_RestoreHoldoutMaterials(Operator):
    bl_idname = "fbp.restore_holdout_materials"
    bl_label = "Restore Holdout Materials"
    bl_description = "Restore materials changed by Frame by Plane holdout tools"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        count = 0
        for rig in [obj for obj in context.scene.objects if is_fbp_layer_object(obj)]:
            if restore_original_materials_from_holdout(rig):
                count += 1
        self.report({'INFO'}, f"Restored {count} layer(s)")
        return {'FINISHED'}



class FBP_OT_ToggleLayerHoldout(Operator):
    bl_idname = "fbp.toggle_layer_holdout"
    bl_label = "Toggle Layer Holdout"
    bl_description = "Toggle alpha-aware holdout on this layer. Transparent pixels stay transparent; visible pixels become holdout"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(name="Layer", description="Frame by Plane rig to toggle as holdout")

    def execute(self, context):
        rig = bpy.data.objects.get(self.rig_name)
        if not rig or not is_fbp_layer_object(rig):
            self.report({'WARNING'}, "Frame by Plane layer not found")
            return {'CANCELLED'}
        if rig_holdout_is_active(rig):
            if restore_original_materials_from_holdout(rig):
                self.report({'INFO'}, f"Restored {rig.name}")
                return {'FINISHED'}
            return {'CANCELLED'}
        if fbp_apply_holdout_materials_to_rig(rig):
            self.report({'INFO'}, f"Holdout enabled for {rig.name}")
            return {'FINISHED'}
        return {'CANCELLED'}


class FBP_OT_RemovePendingPlaneAtIndex(Operator):
    bl_idname = "fbp.remove_pending_plane_at_index"
    bl_label = "Remove Setup Layer"
    bl_description = "Remove this pending layer from the Multiplane Setup before generating planes"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(name="Index", description="Pending setup row index to remove", default=-1)

    def execute(self, context):
        sc = context.scene
        if 0 <= self.index < len(sc.fbp_pending_planes):
            sc.fbp_pending_planes.remove(self.index)
            sc.fbp_pending_planes_idx = min(max(0, self.index - 1), max(0, len(sc.fbp_pending_planes) - 1))
            return {'FINISHED'}
        return {'CANCELLED'}


class FBP_OT_ProjectHealthCheck(Operator):
    bl_idname      = "fbp.project_health_check"
    bl_label       = "Project Health Check"
    bl_description = "Check linked images, collections and layers in the current Frame by Plane project"

    def execute(self, context):
        sync_layer_collection(context)
        rigs = [obj for obj in context.scene.objects if is_fbp_layer_object(obj)]
        fbp_colls = [coll for coll in bpy.data.collections if collection_has_fbp_content(coll, True)]
        image_paths = collect_project_image_paths()
        missing = missing_project_images()
        empty_fbp_colls = [coll.name for coll in fbp_colls if not any(True for _ in iter_fbp_rigs_in_collection(coll, True))]

        lines = [
            "Frame by Plane - Project Health",
            "================================",
            f"Layers: {len(rigs)}",
            f"Collections: {len(fbp_colls)}",
            f"Linked images: {len(image_paths)}",
            f"Missing images: {len(missing)}",
            f"Empty FBP collections: {len(empty_fbp_colls)}",
            "",
        ]
        if missing:
            lines.append("Missing files:")
            lines.extend(f"- {p}" for p in missing[:200])
            if len(missing) > 200:
                lines.append(f"...and {len(missing) - 200} more")
        else:
            lines.append("No missing files found.")

        txt = bpy.data.texts.get("FBP_Project_Health") or bpy.data.texts.new("FBP_Project_Health")
        txt.clear()
        txt.write("\n".join(lines))
        self.report({'INFO'}, f"Health: {len(rigs)} layers, {len(missing)} missing image(s)")
        return {'FINISHED'}


class FBP_OT_RelinkFromProjectRoot(Operator):
    bl_idname      = "fbp.relink_from_project_root"
    bl_label       = "Relink From Project Root"
    bl_description = "Relink missing images by searching inside the Project Folder"
    bl_options     = {'UNDO'}

    def execute(self, context):
        root = project_root_for_package(context)
        if not root or not os.path.isdir(root):
            self.report({'WARNING'}, "Set a valid Project Folder first")
            return {'CANCELLED'}
        relinked, ambiguous, still_missing = relink_missing_images_from_root(root, make_relative=True)
        msg = f"Relinked {relinked}; missing {len(still_missing)}; ambiguous {len(ambiguous)}"
        self.report({'INFO' if not still_missing else 'WARNING'}, msg)
        return {'FINISHED'}


class FBP_OT_SelectMissingLayers(Operator):
    bl_idname      = "fbp.select_missing_layers"
    bl_label       = "Select Missing Layers"
    bl_description = "Select Frame by Plane rigs that contain missing linked images"
    bl_options     = {'UNDO'}

    def execute(self, context):
        sync_layer_collection(context)
        bpy.ops.object.select_all(action='DESELECT')
        selected = 0
        skipped_hidden = 0
        active = None
        for rig in [obj for obj in context.scene.objects if getattr(obj, 'is_fbp_control', False)]:
            if not rig_has_missing_images(rig):
                continue
            if collection_is_hidden_in_view_layer(context, get_primary_fbp_collection(rig)):
                skipped_hidden += 1
                continue
            if not object_in_view_layer(rig, context):
                skipped_hidden += 1
                continue
            try:
                rig.select_set(True)
                active = rig
                selected += 1
            except Exception:
                skipped_hidden += 1
        if active:
            context.view_layer.objects.active = active
        level = 'WARNING' if skipped_hidden else 'INFO'
        self.report({level}, f"Selected {selected} missing layer(s); hidden/unavailable {skipped_hidden}")
        return {'FINISHED'} if selected or skipped_hidden else {'CANCELLED'}


class FBP_OT_SyncCollectionColors(Operator):
    bl_idname      = "fbp.sync_collection_colors"
    bl_label       = "Sync Collection Colors"
    bl_description = "Apply visible Collection color tags to Frame by Plane layer viewport colors"
    bl_options     = {'UNDO'}

    def execute(self, context):
        sync_collection_colors_to_rigs(context)
        self.report({'INFO'}, "Collection colors synced")
        return {'FINISHED'}


# ── FAST IMPORT / SCENE SPLIT ─────────────────────────────────────────────────

_FBP_FAST_IMPORT_RUNTIME = {
    # Viewport space references and profile object are runtime-only and cannot be stored as IDProperties.
    "view_shading": [],
    "profile": None,
}


def fbp_fast_import_wm(context=None):
    return getattr(context, "window_manager", None) if context else getattr(bpy.context, "window_manager", None)


def fbp_fast_import_depth(context=None):
    wm = fbp_fast_import_wm(context)
    if not wm:
        return 0
    try:
        return int(wm.get("fbp_fast_import_depth", 0))
    except Exception:
        return 0


def fbp_set_fast_import_depth(value, context=None):
    wm = fbp_fast_import_wm(context)
    if not wm:
        return
    try:
        wm["fbp_fast_import_depth"] = max(0, int(value))
    except Exception as exc:
        fbp_warn("Could not store Fast Import depth on WindowManager", exc)


def fbp_fast_import_is_active():
    return fbp_fast_import_depth() > 0


def fbp_fast_import_queued_names(context=None):
    value = str(fbp_runtime_get("fbp_fast_import_queued_rigs", "", context) or "")
    return [name for name in value.split("|") if name]


def fbp_set_fast_import_queued_names(names, context=None):
    unique = []
    seen = set()
    for name in names:
        if name and name not in seen:
            unique.append(name)
            seen.add(name)
    fbp_runtime_set("fbp_fast_import_queued_rigs", "|".join(unique), context)


def fbp_fast_import_queue_rig(rig):
    if not rig:
        return
    names = fbp_fast_import_queued_names()
    if rig.name not in names:
        names.append(rig.name)
        fbp_set_fast_import_queued_names(names)


def fbp_preserve_current_frame(context, func, *args, **kwargs):
    scene = context.scene if context else bpy.context.scene
    current_frame = None
    current_subframe = 0.0
    if scene:
        try:
            current_frame = int(scene.frame_current)
            current_subframe = float(getattr(scene, "frame_subframe", 0.0))
        except Exception:
            current_frame = None

    result = None
    error = None
    try:
        result = func(*args, **kwargs)
    except Exception as exc:
        error = exc
    finally:
        if scene and current_frame is not None:
            try:
                scene.frame_set(current_frame, subframe=current_subframe)
            except Exception:
                try:
                    scene.frame_current = current_frame
                except Exception:
                    pass
    if error:
        raise error
    return result


def fbp_current_profile():
    return _FBP_FAST_IMPORT_RUNTIME.get("profile")


def fbp_profiled_section(label):
    return fbp_profiling.section(fbp_current_profile(), label)


def fbp_capture_viewport_state():
    saved = []
    wm = getattr(bpy.context, "window_manager", None)
    if not wm:
        return saved
    try:
        for window in wm.windows:
            screen = window.screen
            if not screen:
                continue
            for area in screen.areas:
                if area.type != 'VIEW_3D':
                    continue
                for space in area.spaces:
                    if getattr(space, "type", None) == 'VIEW_3D':
                        saved.append((space, getattr(space.shading, "type", 'SOLID')))
    except Exception:
        pass
    return saved


def fbp_set_viewports_solid(saved):
    for space, _old in saved:
        try:
            space.shading.type = 'SOLID'
        except Exception:
            pass


def fbp_restore_viewport_state(saved):
    for space, old in saved:
        try:
            space.shading.type = old
        except Exception:
            pass


def fbp_begin_fast_import(context):
    depth = fbp_fast_import_depth(context) + 1
    fbp_set_fast_import_depth(depth, context)
    if depth != 1:
        return

    fbp_set_fast_import_queued_names([], context)
    _FBP_FAST_IMPORT_RUNTIME["profile"] = fbp_profiling.begin_profile("Fast Import")

    with fbp_profiled_section("Prepare fast import"):
        prefs_edit = getattr(getattr(bpy.context, "preferences", None), "edit", None)
        if prefs_edit:
            try:
                fbp_runtime_set("fbp_fast_import_undo_state", 1 if prefs_edit.use_global_undo else 0, context)
                prefs_edit.use_global_undo = False
            except Exception:
                fbp_runtime_set("fbp_fast_import_undo_state", -1, context)

        saved = fbp_capture_viewport_state()
        _FBP_FAST_IMPORT_RUNTIME["view_shading"] = saved
        fbp_set_viewports_solid(saved)

    try:
        bpy.context.window_manager.progress_begin(0, 100)
    except Exception:
        pass


def fbp_end_fast_import(context):
    depth = fbp_fast_import_depth(context)
    if depth <= 0:
        return
    depth -= 1
    fbp_set_fast_import_depth(depth, context)
    if depth != 0:
        return

    scene = context.scene if context else bpy.context.scene
    current_frame = None
    current_subframe = 0.0
    if scene:
        try:
            current_frame = int(scene.frame_current)
            current_subframe = float(getattr(scene, "frame_subframe", 0.0))
        except Exception:
            current_frame = None

    with fbp_profiled_section("Finalize generated rigs"):
        seen = set()
        for rig_name in fbp_fast_import_queued_names(context):
            if rig_name in seen:
                continue
            seen.add(rig_name)
            rig = bpy.data.objects.get(rig_name)
            if not rig:
                continue
            try:
                do_update_animation(rig)
                do_update_emission(rig)
                do_update_opacity(rig)
            except Exception as exc:
                fbp_warn("Could not finalize queued rig", exc)

    with fbp_profiled_section("Sync UI and collections"):
        try:
            sync_layer_collection(context)
            sync_collection_colors_to_rigs(context)
        except Exception:
            pass

    with fbp_profiled_section("Final view layer update"):
        try:
            if context and getattr(context, "view_layer", None):
                context.view_layer.update()
        except Exception:
            pass

    if scene and current_frame is not None:
        try:
            scene.frame_set(current_frame, subframe=current_subframe)
        except Exception:
            try:
                scene.frame_current = current_frame
            except Exception:
                pass

    fbp_restore_viewport_state(_FBP_FAST_IMPORT_RUNTIME["view_shading"])
    _FBP_FAST_IMPORT_RUNTIME["view_shading"] = []

    prefs_edit = getattr(getattr(bpy.context, "preferences", None), "edit", None)
    undo_state = int(fbp_runtime_get("fbp_fast_import_undo_state", -1, context) or -1)
    if prefs_edit and undo_state >= 0:
        try:
            prefs_edit.use_global_undo = bool(undo_state)
        except Exception as exc:
            fbp_warn("Could not restore global undo", exc)
    fbp_runtime_set("fbp_fast_import_undo_state", -1, context)

    profile = _FBP_FAST_IMPORT_RUNTIME.get("profile")
    if profile:
        try:
            fbp_profiling.finish_profile(profile)
            fbp_profiling.write_profile_text(bpy, profile)
            print(fbp_profiling.format_profile(profile))
        except Exception as exc:
            print(f"[FBP] Profile report error: {exc}")
    _FBP_FAST_IMPORT_RUNTIME["profile"] = None
    fbp_set_fast_import_queued_names([], context)

    try:
        bpy.context.window_manager.progress_update(100)
        bpy.context.window_manager.progress_end()
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
    except Exception:
        pass


def fbp_folder_has_images_recursive(path):
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            dirnames[:] = [d for d in dirnames if not is_hidden_import_name(d)]
            for filename in filenames:
                if not is_hidden_import_name(filename) and is_supported_image_file(filename) and not is_technical_map_file(filename):
                    return True
    except Exception:
        pass
    return False


def fbp_unique_scene_name(base_name):
    clean = clean_layer_name_from_path(base_name) or "Scene"
    clean = clean[:55]
    if clean not in bpy.data.scenes:
        return clean
    i = 2
    while f"{clean}.{i:03d}" in bpy.data.scenes:
        i += 1
    return f"{clean}.{i:03d}"


def fbp_apply_scene_defaults(scene):
    try:
        scene.fbp_pre_orientation = 'VERT'
    except Exception:
        pass
    try:
        scene.fbp_auto_scale = True
    except Exception:
        pass
    try:
        scene.fbp_cam_ratio = '4_3'
    except Exception:
        pass
    try:
        scene.render.resolution_x = 1920
        scene.render.resolution_y = 1440
    except Exception:
        pass
    try:
        scene.fbp_gen_camera = True
        scene.fbp_cam_pivot = True
    except Exception:
        pass


def fbp_auto_build_main_folders_as_scenes(operator, context):
    original_scene = context.scene
    original_window_scene = None
    try:
        original_window_scene = context.window.scene
    except Exception:
        pass

    base = bpy.path.abspath(getattr(original_scene, "fbp_project_path", "") or "")
    if not base or not os.path.isdir(base):
        operator.report({'ERROR'}, "Set a valid Project Folder first")
        return {'CANCELLED'}

    top_folders = []
    for name in sorted(os.listdir(base), key=natural_sort_key):
        if is_hidden_import_name(name):
            continue
        full = os.path.join(base, name)
        if os.path.isdir(full) and fbp_folder_has_images_recursive(full):
            top_folders.append((name, full))

    if not top_folders:
        operator.report({'WARNING'}, "No valid main folders found")
        return {'CANCELLED'}

    made = 0
    errors = []
    for name, full in top_folders:
        scene = bpy.data.scenes.new(fbp_unique_scene_name(name))
        made += 1

        try:
            scene.render.fps = original_scene.render.fps
            scene.frame_start = original_scene.frame_start
            scene.frame_end = original_scene.frame_end
        except Exception:
            pass

        fbp_apply_scene_defaults(scene)

        try:
            scene.fbp_project_path = full
            scene.fbp_parent_import_path = full
            scene.fbp_import_main_folders_as_scenes = False
        except Exception:
            pass

        try:
            context.window.scene = scene
        except Exception:
            errors.append(f"{name}: could not switch scene")
            continue

        try:
            result = _FBP_ORIGINAL_AUTO_SCENE_BUILDER_EXECUTE(operator, context)
            if 'CANCELLED' in result:
                errors.append(f"{name}: build cancelled")
        except Exception as exc:
            errors.append(f"{name}: {exc}")

    try:
        if original_window_scene:
            context.window.scene = original_window_scene
    except Exception:
        pass

    if errors:
        print("Frame by Plane scene split issues:")
        for err in errors:
            print(" -", err)
        operator.report({'WARNING'}, f"Created {made} scene(s), with {len(errors)} issue(s). Check console.")
    else:
        operator.report({'INFO'}, f"Created {made} scene(s) from main folders")
    return {'FINISHED'}


# Fast Import is invoked directly inside the operator execute methods.
# Avoid monkey-patching operator methods at module load: it makes debugging harder
# and is less suitable for Blender Extensions review.


class FBP_OT_ShowImportProfile(Operator):
    bl_idname      = "fbp.show_import_profile"
    bl_label       = "Show Import Profile"
    bl_description = "Open the last Frame by Plane import profiling report"

    def execute(self, context):
        txt = bpy.data.texts.get("FBP_Last_Import_Profile")
        if not txt:
            txt = bpy.data.texts.new("FBP_Last_Import_Profile")
            txt.write("No import profile yet. Run Auto Build Project or Generate Multi Plane first.")
        try:
            for area in context.screen.areas:
                if area.type == 'TEXT_EDITOR':
                    area.spaces.active.text = txt
                    break
        except Exception:
            pass
        self.report({'INFO'}, "Opened FBP_Last_Import_Profile")
        return {'FINISHED'}


class FBP_OT_ImportSingleImage(Operator):
    bl_idname = "fbp.import_single_image"
    bl_label = "Single Plane"
    bl_description = "Create a single static Frame by Plane layer from one image"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')
    directory: StringProperty(subtype='DIR_PATH')
    files: CollectionProperty(type=bpy.types.OperatorFileListElement)

    def invoke(self, context, event):
        path = context.scene.fbp_project_path or context.scene.fbp_last_directory
        if path:
            self.directory = path
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        filenames = [f.name for f in self.files] if self.files else []
        if not filenames and self.filepath:
            self.directory = os.path.dirname(self.filepath)
            filenames = [os.path.basename(self.filepath)]
        filenames = [f for f in filenames if is_supported_image_file(f) and not is_technical_map_file(f)]
        if not filenames:
            return {'CANCELLED'}
        context.scene.fbp_last_directory = self.directory
        f = sorted(filenames, key=natural_sort_key)[0]
        target_collection = context.collection if context.collection else context.scene.collection
        rig = build_fbp_rig(
            context, clean_layer_name_from_path(f), self.directory, [f],
            context.scene.cursor.location.copy(), target_collection=target_collection)
        bpy.ops.object.select_all(action='DESELECT')
        if object_in_view_layer(rig, context):
            rig.select_set(True)
            context.view_layer.objects.active = rig
        set_viewport_object_color(context)
        return {'FINISHED'}


class FBP_OT_ImportFolderMultiplane(Operator):
    bl_idname = "fbp.import_folder_multiplane"
    bl_label = "Multiplane"
    bl_description = "Create a multiplane setup directly from a folder"
    bl_options = {'REGISTER', 'UNDO'}

    animation: BoolProperty(default=True)
    filepath: StringProperty(subtype='FILE_PATH')
    directory: StringProperty(subtype='DIR_PATH')
    files: CollectionProperty(type=bpy.types.OperatorFileListElement)

    def invoke(self, context, event):
        path = context.scene.fbp_project_path or context.scene.fbp_last_directory
        if path:
            self.directory = path
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        base = self.directory or (os.path.dirname(self.filepath) if self.filepath else "")
        base = bpy.path.abspath(base)
        if not base or not os.path.isdir(base):
            self.report({'WARNING'}, "Choose a valid folder")
            return {'CANCELLED'}
        sc = context.scene
        rows = fbp_scan_project_layers_for_setup(base)
        if not self.animation:
            rows = [(name, coll, directory, files[:1]) for name, coll, directory, files in rows if files]
        if not rows:
            self.report({'WARNING'}, "No supported images found")
            return {'CANCELLED'}
        sc.fbp_creation_mode = 'MULTI'
        sc.fbp_parent_import_path = base
        sc.fbp_pending_planes.clear()
        for index, (name, collection_name, directory, files) in enumerate(rows):
            item = sc.fbp_pending_planes.add()
            item.name = name
            item.collection_name = collection_name
            item.directory = directory
            item.files_str = "|".join(sorted(files, key=natural_sort_key))
            item.fbp_color_tag = f"COLOR_{(index % 9) + 1:02d}"
        return bpy.ops.fbp.generate_multiplane()


class FBP_OT_PopupSinglePlane(Operator):
    bl_idname = "fbp.popup_single_plane"
    bl_label = "Single Plane"
    bl_description = "Quick setup, then choose an image for a single plane"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        # Prepare the preview material outside draw(), otherwise Blender may reject ID writes
        # while the popup UI is being rendered.
        try:
            get_or_create_fbp_gradient_preview_material(context.scene)
        except Exception as exc:
            fbp_warn("Could not prepare gradient preview ColorRamp for popup", exc)
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        sc = context.scene
        layout = self.layout
        layout.label(text="Single Plane", icon=fbp_icon("IMAGE_DATA"))
        layout.prop(sc, "fbp_pre_orientation", text="Orientation")
        layout.prop(sc, "fbp_pre_shadeless", text="Emission Texture", icon=fbp_icon("LIGHT_SUN"))
        layout.prop(sc, "fbp_pre_interpolation", text="Filter")

    def execute(self, context):
        return bpy.ops.fbp.import_single_image('INVOKE_DEFAULT')


class FBP_OT_PopupSinglePlaneAnimation(Operator):
    bl_idname = "fbp.popup_single_plane_animation"
    bl_label = "Single Plane Animation"
    bl_description = "Quick setup, then choose images for one animated plane"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=380)

    def draw(self, context):
        sc = context.scene
        layout = self.layout
        layout.label(text="Single Plane Animation", icon=fbp_icon("FILE_IMAGE"))
        row = layout.row(align=True)
        row.prop(sc, "fbp_pre_duration", text="Frame Duration")
        row.prop(sc, "fbp_pre_shadeless", text="Emission Texture", icon=fbp_icon("LIGHT_SUN"), toggle=True)
        layout.prop(sc, "fbp_pre_loop_mode", text="Playback")
        layout.prop(sc, "fbp_pre_interpolation", text="Filter")
        layout.prop(sc, "fbp_pre_orientation", text="Orientation")

    def execute(self, context):
        return bpy.ops.fbp.import_sequence('INVOKE_DEFAULT')


class FBP_OT_PopupMultiplane(Operator):
    bl_idname = "fbp.popup_multiplane"
    bl_label = "Multiplane"
    bl_description = "Quick multiplane setup. Use Send To N-Panel for advanced setup review"
    bl_options = {'REGISTER', 'UNDO'}

    animation: BoolProperty(default=True)
    send_to_panel: BoolProperty(name="Send To N-Panel", default=False)
    folder: StringProperty(name="Folder", subtype='DIR_PATH', default="")

    def invoke(self, context, event):
        self.folder = context.scene.fbp_project_path or context.scene.fbp_parent_import_path or context.scene.fbp_last_directory
        return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, context):
        sc = context.scene
        layout = self.layout
        layout.label(text="Multiplane Animation" if self.animation else "Multiplane", icon=fbp_icon("RENDERLAYERS") if self.animation else 'MESH_PLANE')
        layout.prop(self, "folder", text="Folder")
        row = layout.row(align=True)
        row.prop(sc, "fbp_pre_duration", text="Frame Duration")
        row.prop(sc, "fbp_pre_shadeless", text="Emission Texture", icon=fbp_icon("LIGHT_SUN"), toggle=True)
        layout.prop(sc, "fbp_pre_loop_mode", text="Playback")
        layout.prop(sc, "fbp_pre_interpolation", text="Filter")
        layout.prop(sc, "fbp_pre_orientation", text="Orientation")
        layout.separator()
        layout.prop(sc, "fbp_gen_camera", text="Generate Camera", icon=fbp_icon("VIEW_CAMERA"))
        layout.prop(sc, "fbp_layer_offset", text="Plane Distance")
        layout.prop(sc, "fbp_auto_scale", text="Fit to Camera", icon=fbp_icon("FULLSCREEN_ENTER"))
        layout.prop(self, "send_to_panel", text="Send To N-Panel")

    def execute(self, context):
        base = bpy.path.abspath(self.folder or "")
        if not base or not os.path.isdir(base):
            self.report({'WARNING'}, "Choose a valid folder")
            return {'CANCELLED'}
        sc = context.scene
        sc.fbp_creation_mode = 'MULTI'
        sc.fbp_parent_import_path = base
        sc.fbp_project_path = base
        rows = fbp_scan_project_layers_for_setup(base)
        if not self.animation:
            rows = [(name, coll, directory, files[:1]) for name, coll, directory, files in rows if files]
        sc.fbp_pending_planes.clear()
        for index, (name, collection_name, directory, files) in enumerate(rows):
            item = sc.fbp_pending_planes.add()
            item.name = name
            item.collection_name = collection_name
            item.directory = directory
            item.files_str = "|".join(sorted(files, key=natural_sort_key))
            item.fbp_color_tag = f"COLOR_{(index % 9) + 1:02d}"
        sc['fbp_pending_open_collections'] = ""
        if self.send_to_panel:
            sc.fbp_ui_mode = 'ADVANCED'
            self.report({'INFO'}, f"Sent {len(rows)} layer(s) to the N-Panel Multiplane Setup")
            return {'FINISHED'}
        if not rows:
            self.report({'WARNING'}, "No supported images found")
            return {'CANCELLED'}
        return bpy.ops.fbp.generate_multiplane()


class FBP_OT_PopupColorPlane(Operator):
    bl_idname = "fbp.popup_color_plane"
    bl_label = "Color Plane"
    bl_description = "Create a camera-ratio color, gradient or holdout plane"
    bl_options = {'REGISTER', 'UNDO'}

    preset_type: StringProperty(default="")

    def invoke(self, context, event):
        if self.preset_type in {'CUSTOM', 'GRADIENT', 'HOLDOUT'}:
            context.scene.fbp_color_plane_type = self.preset_type
        # Prepare the preview material outside draw(), otherwise Blender may reject ID writes
        # while the popup UI is being rendered.
        try:
            get_or_create_fbp_gradient_preview_material(context.scene)
        except Exception as exc:
            fbp_warn("Could not prepare gradient preview ColorRamp for popup", exc)
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        sc = context.scene
        layout = self.layout
        title = "Gradient Plane" if sc.fbp_color_plane_type == 'GRADIENT' else ("Holdout Plane" if sc.fbp_color_plane_type == 'HOLDOUT' else "Color Plane")
        layout.label(text=title, icon=fbp_icon("MATERIAL"))
        row = layout.row(align=False)
        split = row.split(factor=0.78, align=False)
        type_row = split.row(align=True)
        type_row.prop(sc, "fbp_color_plane_type", expand=True)
        emiss = split.row(align=True)
        emiss.enabled = sc.fbp_color_plane_type != 'HOLDOUT'
        emiss.prop(sc, "fbp_color_plane_emission", text="", icon=fbp_icon("LIGHT_SUN"), toggle=True)
        if sc.fbp_color_plane_type == 'CUSTOM':
            fbp_draw_color_plane_color_row(layout, sc)
        elif sc.fbp_color_plane_type == 'GRADIENT':
            fbp_draw_gradient_choice_rows(layout, sc)
            draw_scene_fbp_color_ramp(layout, sc)
            gbox = layout.box()
            row = gbox.row(align=True)
            row.label(text="Position", icon=fbp_icon("EMPTY_ARROWS"))
            row = gbox.row(align=True)
            row.prop(sc, "fbp_gradient_offset_x", text="X")
            row.prop(sc, "fbp_gradient_offset_y", text="Y")
            row = gbox.row(align=True)
            row.prop(sc, "fbp_gradient_scale_x", text="Scale X")
            row.prop(sc, "fbp_gradient_scale_y", text="Scale Y")
            gbox.prop(sc, "fbp_gradient_rotation", text="Rotation")
        layout.prop(sc, "fbp_pre_orientation", text="Orientation")

    def execute(self, context):
        return bpy.ops.fbp.create_color_plane()



class FBP_OT_CreateColorPlaneFromHex(Operator):
    bl_idname = "fbp.create_color_plane_from_hex"
    bl_label = "Color Plane from Hex Color Code"
    bl_description = "Create a solid Color Plane from a hexadecimal color code copied from another app or website"
    bl_options = {'REGISTER', 'UNDO'}

    hex_color: StringProperty(
        name="Hex Color",
        description="Hexadecimal color code, for example #FFCC00 or FFCC00FF",
        default="#FFFFFF")

    def invoke(self, context, event):
        clip = getattr(context.window_manager, 'clipboard', '') or ''
        clip = clip.strip().strip('"').strip("'")
        if clip.startswith('#') or (len(clip) in {6, 8} and all(c in '0123456789abcdefABCDEF' for c in clip)):
            self.hex_color = clip
        return context.window_manager.invoke_props_dialog(self, width=320)

    def execute(self, context):
        value = (self.hex_color or '').strip().strip('#')
        if len(value) not in {6, 8} or any(c not in '0123456789abcdefABCDEF' for c in value):
            self.report({'ERROR'}, "Use a valid hex color such as #FFCC00 or #FFCC00FF")
            return {'CANCELLED'}
        try:
            r = int(value[0:2], 16) / 255.0
            g = int(value[2:4], 16) / 255.0
            b = int(value[4:6], 16) / 255.0
            a = int(value[6:8], 16) / 255.0 if len(value) == 8 else 1.0
        except ValueError:
            self.report({'ERROR'}, "Invalid hex color")
            return {'CANCELLED'}
        sc = context.scene
        sc.fbp_color_plane_type = 'CUSTOM'
        sc.fbp_color_plane_color = (r, g, b, a)
        return bpy.ops.fbp.create_color_plane()


class FBP_OT_ImportSingleImageFromClipboard(Operator):
    bl_idname = "fbp.import_single_image_from_clipboard"
    bl_label = "Single Plane from Clipboard"
    bl_description = "Create an Image Plane from an image file path copied to the clipboard. If the clipboard is not a valid image path, open the file picker"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        raw = getattr(context.window_manager, 'clipboard', '') or ''
        path = raw.strip().strip('"').strip("'")
        if path.startswith('file://'):
            path = path[7:]
        path = os.path.expanduser(path)
        if os.path.isfile(path) and is_supported_image_file(path) and not is_technical_map_file(path):
            directory = os.path.dirname(path)
            filename = os.path.basename(path)
            context.scene.fbp_last_directory = directory
            target_collection = context.collection if context.collection else context.scene.collection
            rig = build_fbp_rig(
                context, clean_layer_name_from_path(filename), directory, [filename],
                context.scene.cursor.location.copy(), target_collection=target_collection)
            bpy.ops.object.select_all(action='DESELECT')
            if object_in_view_layer(rig, context):
                rig.select_set(True)
                context.view_layer.objects.active = rig
            set_viewport_object_color(context)
            return {'FINISHED'}
        self.report({'INFO'}, "Clipboard does not contain a valid image path. Choose an image file")
        return bpy.ops.fbp.import_single_image('INVOKE_DEFAULT')

class FBP_MT_FrameByPlaneAdd(Menu):
    bl_idname = "FBP_MT_frame_by_plane_add"
    bl_label = "Frame By Plane"

    def draw(self, context):
        layout = self.layout
        op = layout.operator("fbp.popup_color_plane", text="Color Plane", icon=fbp_icon("IMAGE"))
        op.preset_type = 'CUSTOM'
        op = layout.operator("fbp.popup_color_plane", text="Gradient Plane", icon=fbp_icon("COLOR"))
        op.preset_type = 'GRADIENT'
        op = layout.operator("fbp.popup_color_plane", text="Holdout Plane", icon=fbp_icon("GHOST_DISABLED"))
        op.preset_type = 'HOLDOUT'
        layout.separator()
        layout.operator("fbp.popup_single_plane", text="Image Plane", icon=fbp_icon("IMAGE_DATA"))
        op = layout.operator("fbp.popup_multiplane", text="Multiplane", icon=fbp_icon("RENDER_RESULT"))
        op.animation = True
        layout.separator()
        layout.operator("fbp.create_color_plane_from_hex", text="Color Plane from Hex Color Code", icon=fbp_icon("PASTEDOWN"))
        layout.operator("fbp.import_single_image_from_clipboard", text="Single Plane from Clipboard", icon=fbp_icon("IMAGE_PLANE"))


# ── MENU HELPERS ─────────────────────────────────────────────────────────────

def draw_fbp_image_add_menu(self, context):
    layout = self.layout
    layout.separator()
    layout.menu("FBP_MT_frame_by_plane_add", icon=fbp_icon("RENDERLAYERS"))


def draw_fbp_object_context_menu(self, context):
    if get_selected_fbp_roots(context):
        self.layout.separator()
        self.layout.operator("fbp.set_selected_holdout", text="Set Selected as Holdout", icon=fbp_icon("GHOST_DISABLED"))
        self.layout.operator("fbp.holdout_all_except_selected", text="Holdout All Except Selected", icon=fbp_icon("GHOST_DISABLED"))
        self.layout.operator("fbp.restore_holdout_materials", text="Restore Frame by Plane Holdouts", icon=fbp_icon("GHOST_DISABLED"))
        self.layout.separator()
        self.layout.operator("fbp.delete_sequence", text="Delete Frame by Plane Layer + Plane", icon=fbp_icon("TRASH"))
        self.layout.operator("fbp.merge_selected_to_active_sequence", text="Convert to Single Animated Plane", icon=fbp_icon("DUPLICATE"))


def register_fbp_menus():
    # Add a top-level Shift+A category: Shift+A > Frame By Plane.
    bpy.types.VIEW3D_MT_add.prepend(draw_fbp_image_add_menu)
    for menu_name in ("VIEW3D_MT_object_context_menu", "OUTLINER_MT_context_menu"):
        ctx_menu = getattr(bpy.types, menu_name, None)
        if ctx_menu:
            ctx_menu.append(draw_fbp_object_context_menu)


def unregister_fbp_menus():
    for menu_name in ("VIEW3D_MT_image_add", "VIEW3D_MT_add"):
        menu_cls = getattr(bpy.types, menu_name, None)
        if not menu_cls:
            continue
        try:
            menu_cls.remove(draw_fbp_image_add_menu)
        except Exception:
            pass
    for menu_name in ("VIEW3D_MT_object_context_menu", "OUTLINER_MT_context_menu"):
        ctx_menu = getattr(bpy.types, menu_name, None)
        if ctx_menu:
            try:
                ctx_menu.remove(draw_fbp_object_context_menu)
            except Exception:
                pass


# ── REGISTRATION ──────────────────────────────────────────────────────────────

classes = (
    FBP_LayerItem,
    FBP_ImageItem,
    FBP_PendingPlaneItem,
    FBP_UL_ImageList,
    FBP_UL_PendingList,
    FBP_UL_LayerStack,
    FBP_PT_Settings,
    FBP_PT_LayerStack,
    FBP_PT_Sequence,
    FBP_PT_CreateFirst,
    FBP_PT_CreateExisting,
    FBP_OT_SaveFile,
    FBP_OT_OpenCreateRig,
    FBP_OT_SelectLinkedPlane,
    FBP_OT_SelectCollectionPlanes,
    FBP_OT_AddColorPlaneVariant,
    FBP_OT_SelectLayerExclusive,
    FBP_OT_DuplicateOrDefault,
    FBP_OT_MoveLayerStack,
    FBP_OT_ToggleSelectLayer,
    FBP_OT_ToggleSolo,
    FBP_OT_ToggleLock,
    FBP_OT_SelectAllLayers,
    FBP_OT_IsolateLayer,
    FBP_OT_FitToCamera,
    FBP_OT_MultiFitCamera,
    FBP_OT_SetCurrentFrame,
    FBP_OT_AddPendingPlane,
    FBP_OT_EditPendingPlane,
    FBP_OT_MovePendingPlane,
    FBP_OT_RemovePendingPlane,
    FBP_OT_ClearPendingPlanes,
    FBP_OT_ScanProjectToSetup,
    FBP_OT_AddPendingCollection,
    FBP_OT_AutoSceneBuilder,
    FBP_OT_GenerateMultiplane,
    FBP_OT_ImportFolderHierarchy,
    FBP_OT_ImportSequence,
    FBP_OT_ReplaceSequence,
    FBP_OT_UpdateAnimation,
    FBP_OT_SelectImageExclusive,
    FBP_OT_InsertImagesAfterSelected,
    FBP_OT_InsertLinkedImageAfterSelected,
    FBP_OT_LinkImageFrame,
    FBP_OT_ListAction,
    FBP_OT_BatchApply,
    FBP_OT_Transform,
    FBP_OT_PopupTransform,
    FBP_OT_UpdateEmission,
    FBP_OT_UpdateOpacity,
    FBP_OT_UpdateTrack,
    FBP_OT_SelectAll,
    FBP_OT_ReverseSequence,
    FBP_OT_PopupSequenceSettings,
    FBP_OT_DuplicateSelectedLayers,
    FBP_OT_MergeSelectedToActiveSequence,
    FBP_OT_SplitSelectedImagesToNewPlane,
    FBP_OT_DeleteSequence,
    FBP_OT_DeleteOrDefault,
    FBP_OT_ToggleCollectionCollapse,
    FBP_OT_TogglePendingCollectionCollapse,
    FBP_OT_SelectCollectionLayers,
    FBP_OT_ToggleCollectionVisibility,
    FBP_OT_ToggleCollectionLock,
    FBP_OT_DeleteCollectionLayers,
    FBP_OT_RepairRenderState,
    FBP_OT_BackgroundRenderFrames,
    FBP_OT_CreateColorPlane,
    FBP_OT_ExtendSelectedPlane,
    FBP_OT_ResetPlaneExtension,
    FBP_OT_ResetWiggle,
    FBP_OT_PopupWiggle,
    FBP_OT_PopupEdges,
    FBP_OT_SetSelectedHoldout,
    FBP_OT_HoldoutAllExceptSelected,
    FBP_OT_RestoreHoldoutMaterials,
    FBP_OT_ToggleLayerHoldout,
    FBP_OT_RemovePendingPlaneAtIndex,
    FBP_OT_ProjectHealthCheck,
    FBP_OT_RelinkFromProjectRoot,
    FBP_OT_SelectMissingLayers,
    FBP_OT_SyncCollectionColors,
    FBP_OT_ShowImportProfile,
    FBP_OT_ImportSingleImage,
    FBP_OT_ImportFolderMultiplane,
    FBP_OT_PopupSinglePlane,
    FBP_OT_PopupSinglePlaneAnimation,
    FBP_OT_PopupMultiplane,
    FBP_OT_PopupColorPlane,
    FBP_OT_CreateColorPlaneFromHex,
    FBP_OT_ImportSingleImageFromClipboard,
    FBP_MT_FrameByPlaneAdd,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    register_properties()

    if bpy.context and not bpy.app.timers.is_registered(sync_layer_collection_timer):
        bpy.app.timers.register(sync_layer_collection_timer, first_interval=0.05)
    if bpy.context and not bpy.app.timers.is_registered(cleanup_orphan_fbp_planes_timer):
        bpy.app.timers.register(cleanup_orphan_fbp_planes_timer, first_interval=1.5)


    # Remove possible duplicated legacy handlers before registering the safer one.
    for _handlers in (bpy.app.handlers.frame_change_pre, bpy.app.handlers.frame_change_post):
        for _h in list(_handlers):
            if getattr(_h, "__name__", "") == "fbp_frame_change_handler":
                try:
                    _handlers.remove(_h)
                except Exception:
                    pass
    bpy.app.handlers.frame_change_post.append(fbp_frame_change_handler)

    if fbp_render_guard_pre not in bpy.app.handlers.render_pre:
        bpy.app.handlers.render_pre.append(fbp_render_guard_pre)
    if fbp_render_guard_post not in bpy.app.handlers.render_post:
        bpy.app.handlers.render_post.append(fbp_render_guard_post)
    if fbp_render_guard_post not in bpy.app.handlers.render_cancel:
        bpy.app.handlers.render_cancel.append(fbp_render_guard_post)
    if fbp_render_guard_post not in bpy.app.handlers.render_complete:
        bpy.app.handlers.render_complete.append(fbp_render_guard_post)

    register_fbp_menus()


def unregister():
    clear_previews()
    unregister_fbp_menus()
    for _timer in (sync_layer_collection_timer, cleanup_orphan_fbp_planes_timer):
        try:
            if bpy.app.timers.is_registered(_timer):
                bpy.app.timers.unregister(_timer)
        except Exception:
            pass


    for _handlers in (bpy.app.handlers.frame_change_pre, bpy.app.handlers.frame_change_post):
        for _h in list(_handlers):
            if getattr(_h, "__name__", "") == "fbp_frame_change_handler":
                try:
                    _handlers.remove(_h)
                except Exception:
                    pass
    for _handlers in (bpy.app.handlers.render_pre, bpy.app.handlers.render_post, bpy.app.handlers.render_cancel, bpy.app.handlers.render_complete):
        for _h in list(_handlers):
            if getattr(_h, "__name__", "") in {"fbp_render_guard_pre", "fbp_render_guard_post"}:
                try:
                    _handlers.remove(_h)
                except Exception:
                    pass

    wm = getattr(bpy.context, "window_manager", None)
    if wm:
        for key in (
            "fbp_render_guard_active", "fbp_layer_cache_dirty", "fbp_fast_import_depth",
            "fbp_fast_import_queued_rigs", "fbp_fast_import_undo_state",
        ):
            try:
                if key in wm:
                    del wm[key]
            except Exception:
                pass

    for coll in bpy.data.collections:
        for key in ("fbp_has_fbp_content", "fbp_has_fbp_content_recursive"):
            try:
                if key in coll:
                    del coll[key]
            except Exception:
                pass

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    props_scene = [
        "fbp_last_directory", "fbp_project_path", "fbp_cam_ratio",
        "fbp_show_previews", "fbp_layer_view_mode", "fbp_fit_mode", "fbp_use_hierarchical_layers", "fbp_auto_sort_layers_by_depth", "fbp_sort_layers_alpha", "fbp_layer_list_rows", "fbp_layer_filter_collection", "fbp_pending_filter_collection", "fbp_auto_clean_orphans", "fbp_show_create_tools", "fbp_emergency_render_start", "fbp_emergency_render_end", "fbp_emergency_render_prefix",
        "fbp_auto_collection_color_variants", "fbp_layers", "fbp_layer_stack_index",
        "fbp_creation_mode", "fbp_pending_planes", "fbp_pending_planes_idx", "fbp_pending_collection_name",
        "fbp_pre_duration", "fbp_pre_shadeless", "fbp_pre_loop_mode",
        "fbp_pre_interpolation", "fbp_pre_orientation",
        "fbp_gen_camera", "fbp_cam_pivot", "fbp_layer_offset", "fbp_auto_scale",
        "fbp_ui_mode", "fbp_show_maintenance_tools", "fbp_color_plane_type", "fbp_color_plane_color", "fbp_color_plane_preset",
        "fbp_color_plane_emission", "fbp_gradient_mode", "fbp_gradient_kind",
        "fbp_gradient_color_a", "fbp_gradient_color_b", "fbp_gradient_reverse", "fbp_show_gradient_ramp", "fbp_show_gradient_transform",
        "fbp_extend_mode", "fbp_extend_left", "fbp_extend_right",
        "fbp_extend_top", "fbp_extend_bottom",
        "fbp_parent_import_path", "fbp_import_main_folders_as_scenes",
    ]
    for p in props_scene:
        if hasattr(bpy.types.Scene, p):
            delattr(bpy.types.Scene, p)

    for attr in ("is_fbp_collection", "fbp_collapsed", "fbp_collection_selected", "fbp_collection_solo", "fbp_collection_locked", "fbp_collection_visible", "fbp_collection_holdout"):
        if hasattr(bpy.types.Collection, attr):
            delattr(bpy.types.Collection, attr)

    props_object = [
        "is_fbp_control", "is_fbp_plane", "fbp_collection_name", "fbp_follow_collection_color",
        "fbp_color_variant_index", "fbp_base_scale", "fbp_base_scale_vec", "fbp_preview_path",
        "fbp_is_color_plane", "fbp_color_plane_mode", "fbp_color_plane_color", "fbp_color_plane_emission",
        "fbp_gradient_mode", "fbp_gradient_kind", "fbp_gradient_color_a", "fbp_gradient_color_b", "fbp_gradient_reverse", "fbp_show_gradient_ramp", "fbp_show_gradient_transform",
        "fbp_extend_mode", "fbp_extend_left", "fbp_extend_right", "fbp_extend_top", "fbp_extend_bottom",
        "fbp_crop_left", "fbp_crop_right", "fbp_crop_top", "fbp_crop_bottom",
        "fbp_wiggle_enabled", "fbp_wiggle_position", "fbp_wiggle_rotation", "fbp_wiggle_pos_strength", "fbp_wiggle_rot_strength", "fbp_wiggle_scale", "fbp_wiggle_phase", "fbp_wiggle_use_range", "fbp_wiggle_frame_start", "fbp_wiggle_frame_end", "fbp_wiggle_blend_in", "fbp_wiggle_blend_out",
        "fbp_is_vertical", "fbp_images", "fbp_images_index", "fbp_color_tag",
        "fbp_depth_order", "fbp_loop_mode", "fbp_use_emission", "fbp_interpolation",
        "fbp_plane_target", "fbp_global_duration", "fbp_start_frame",
        "fbp_opacity", "fbp_track_cam", "fbp_is_visible", "fbp_cam_depth",
    ]
    for p in props_object:
        if hasattr(bpy.types.Object, p):
            delattr(bpy.types.Object, p)


if __name__ == "__main__":
    register()
