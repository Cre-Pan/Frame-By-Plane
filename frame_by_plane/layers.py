"""Layer, collection, preview and project-file helpers.

Extracted from core.py so UI and scene synchronization can depend on a focused
layer API instead of the monolithic core module.
"""

import colorsys
import os
import time
from collections import deque

import bpy
import bpy.utils.previews
import mathutils

from .constants import (
    STRIP_COLORS_DICT, preview_collections, fbp_icon, fbp_strip_icon,
    fbp_collection_color_icon,
)
from .path_utils import (
    natural_sort_key, is_supported_video_file, is_supported_media_file,
    is_technical_map_file, invalidate_file_exists_cache,
)
from .materials import (
    iter_material_image_nodes, find_fbp_gradient_ramp_node,
    fbp_apply_holdout_materials_to_rig, restore_original_materials_from_holdout,
    rig_holdout_is_active,
)
from .runtime import (
    FBP_DATA_ERRORS,
    FBP_DATA_IO_ERRORS,
    fbp_runtime_set, fbp_warn, fbp_set_rna_property_silent,
)


_FBP_SYNCING_PROCEDURAL_PREVIEW_ITEMS = set()
_FBP_PREVIEW_MISS_CACHE = {}
_FBP_PREVIEW_MISS_TTL = 2.0
_FBP_COMPOSITE_PREVIEW_COLLECTION = "fbp_thumbnail_composites"
_FBP_COMPOSITE_PREVIEW_LIMIT = 256
_FBP_COMPOSITE_PREVIEW_KEYS = deque()
_FBP_RAW_PREVIEW_LIMIT = 512
_FBP_RAW_PREVIEW_KEYS = deque()
_FBP_LAYER_VIEW_TAGGED_COLLECTIONS = set()
_FBP_LAYER_VIEW_DIRECT_COLLECTIONS = set()
_FBP_LAYER_VIEW_RECURSIVE_COLLECTIONS = set()
_FBP_LAYER_VIEW_CACHE_INITIALIZED = False
_FBP_COLLECTION_UI_STATE_CACHE = {
    "context_key": None,
    "states": {},
}
_COLLECTION_COLOR_TAGS = {f"COLOR_{index:02d}" for index in range(1, 9)}


def sync_layer_collection(context):
    """Lazy scene-sync bridge without a module-import cycle."""
    from .scene_sync import sync_layer_collection as _sync
    return _sync(context)


def is_fbp_image_rig(obj):
    try:
        return obj is not None and bool(getattr(obj, 'is_fbp_control', False))
    except FBP_DATA_ERRORS:
        return False


def is_fbp_layer_object(obj):
    return is_fbp_image_rig(obj)


def fbp_layer_backend_type(rig):
    """Return the effective backend used by one Frame by Plane layer.

    The result is inferred from live flags/materials first, so old files without
    the explicit ``fbp_backend_type`` metadata are classified correctly. Keeping
    this distinction centralized prevents native sequence caches, procedural
    timing caches and Cutout image buffers from being touched by unrelated plane
    types.
    """
    if not is_fbp_layer_object(rig):
        return 'UNKNOWN'
    try:
        if bool(getattr(rig, 'fbp_is_drawing_plane', False)):
            return 'CUTOUT'
        if bool(getattr(rig, 'fbp_is_color_plane', False)):
            mode = str(getattr(rig, 'fbp_color_plane_mode', 'SOLID') or 'SOLID').upper()
            return {
                'GRADIENT': 'PROCEDURAL_GRADIENT',
                'HOLDOUT': 'PROCEDURAL_HOLDOUT',
            }.get(mode, 'PROCEDURAL_COLOR')
    except FBP_DATA_ERRORS:
        return 'UNKNOWN'

    plane = getattr(rig, 'fbp_plane_target', None)
    mesh = getattr(plane, 'data', None) if plane else None
    try:
        for material in getattr(mesh, 'materials', ()) or ():
            if not material:
                continue
            if bool(material.get('fbp_drawing_material', False)):
                return 'CUTOUT'
            if bool(material.get('fbp_native_sequence', False)):
                if bool(material.get('fbp_native_video', False)):
                    return 'NATIVE_MOVIE'
                if bool(material.get('fbp_native_static_image', False)):
                    return 'NATIVE_IMAGE'
                return 'NATIVE_SEQUENCE'
    except FBP_DATA_ERRORS:
        pass

    try:
        explicit = str(rig.get('fbp_backend_type', '') or '').upper()
    except FBP_DATA_ERRORS:
        explicit = ''
    aliases = {
        'DRAWING': 'CUTOUT',
        'STATIC_IMAGE': 'NATIVE_IMAGE',
        'IMAGE_SEQUENCE': 'NATIVE_SEQUENCE',
        'MOVIE': 'NATIVE_MOVIE',
        'PROCEDURAL_SOLID': 'PROCEDURAL_COLOR',
    }
    return aliases.get(explicit, explicit or 'UNKNOWN')


_FBP_SAMPLEABLE_IMAGE_BACKENDS = frozenset({
    'NATIVE_IMAGE', 'NATIVE_SEQUENCE', 'NATIVE_MOVIE', 'CUTOUT',
})


def fbp_layer_has_sampleable_image(rig):
    """Return whether relation effects can sample this layer's image texture."""
    try:
        return fbp_layer_backend_type(rig) in _FBP_SAMPLEABLE_IMAGE_BACKENDS
    except FBP_DATA_ERRORS:
        return False


def fbp_layer_clipping_active_hint(rig):
    """Return the authoritative persistent Clipping Mask enabled state.

    Import metadata and a stale source pointer must never keep a disabled layer
    inside a clipping chain. Effect repair restores this flag for genuinely
    active legacy nodes during normal stack synchronization.
    """
    if not rig or not is_fbp_layer_object(rig):
        return False
    try:
        return bool(rig.get("fbp_effect_clipping_mask", False))
    except FBP_DATA_ERRORS:
        return False


def fbp_layer_backend_label(rig):
    return {
        'NATIVE_IMAGE': 'Image Plane',
        'NATIVE_SEQUENCE': 'Sequence',
        'NATIVE_MOVIE': 'Video Plane',
        'CUTOUT': 'Cutout Plane',
        'PROCEDURAL_COLOR': 'Color Plane',
        'PROCEDURAL_GRADIENT': 'Gradient Plane',
        'PROCEDURAL_HOLDOUT': 'Holdout Plane',
    }.get(fbp_layer_backend_type(rig), 'Frame By Plane Layer')


def safe_collection_color_tag(collection, fallback='COLOR_09'):
    try:
        tag = getattr(collection, 'color_tag', 'NONE')
        return tag if tag in _COLLECTION_COLOR_TAGS else fallback
    except Exception:
        return fallback


def set_collection_color_tag(collection, color_tag):
    """Assign a valid Blender Collection color tag.

    Collection tags support NONE and COLOR_01..COLOR_08. Frame by Plane's
    COLOR_09 is the neutral layer grey, so it maps to NONE for collections.
    """
    if not collection:
        return
    tag = str(color_tag or 'NONE')
    if tag == 'COLOR_09':
        tag = 'NONE'
    if tag != 'NONE' and tag not in _COLLECTION_COLOR_TAGS:
        return
    try:
        collection.color_tag = tag
    except FBP_DATA_IO_ERRORS:
        pass


def make_color_variant(color_tag, index=0):
    """Return a clearly readable depth variant while preserving the tag hue."""
    base = STRIP_COLORS_DICT.get(color_tag, STRIP_COLORS_DICT['COLOR_09'])
    r, g, b, a = base
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    depth = max(0, int(index or 0))

    # Make the difference visible on wire rigs: the nearest layer starts
    # brighter, then each deeper sibling becomes progressively darker.
    value_factor = max(0.42, 1.28 - (0.13 * min(depth, 7)))
    saturation_factor = min(1.12, 0.96 + (0.02 * min(depth, 7)))
    rr, gg, bb = colorsys.hsv_to_rgb(
        h,
        max(0.0, min(1.0, s * saturation_factor)),
        max(0.0, min(1.0, v * value_factor)),
    )
    return (rr, gg, bb, 1.0)


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
    except FBP_DATA_IO_ERRORS:
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
        except FBP_DATA_IO_ERRORS:
            pass
    for coll in list(obj.users_collection):
        if coll != collection:
            try:
                coll.objects.unlink(obj)
            except FBP_DATA_IO_ERRORS:
                pass


def get_primary_fbp_collection(obj):
    """Resolve one canonical collection from the object's live links.

    ``fbp_collection_name`` is only a hint: old files or manual Outliner moves
    can leave it pointing to a collection that no longer owns the layer.
    """
    if not obj:
        return None
    try:
        user_collections = tuple(getattr(obj, 'users_collection', ()) or ())
    except FBP_DATA_ERRORS:
        user_collections = ()
    try:
        stored_name = str(getattr(obj, 'fbp_collection_name', '') or '')
        if stored_name:
            collection = bpy.data.collections.get(stored_name)
            if collection is not None and collection in user_collections:
                return collection
    except FBP_DATA_ERRORS:
        pass
    try:
        for collection in user_collections:
            if getattr(collection, 'is_fbp_collection', False):
                return collection
        return user_collections[0] if user_collections else None
    except FBP_DATA_ERRORS:
        return None

def is_layer_item_visible_in_collections(context, item):
    try:
        rig = item.obj
    except ReferenceError:
        return False
    if not rig or not is_fbp_layer_object(rig):
        return False
    try:
        # visible_get respects Collection hide/exclude state in the View Layer.
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


def fbp_active_layer_index(scene):
    """Resolve the active layer from the virtual tree, then legacy fallback."""
    if scene is None:
        return -1
    try:
        legacy_index = int(getattr(scene, "fbp_layer_stack_index", -1))
    except FBP_DATA_ERRORS:
        legacy_index = -1
    try:
        layers = getattr(scene, "fbp_layers", ())
        tree_index = int(getattr(scene, "fbp_layer_tree_rows_idx", -1))
        rows = getattr(scene, "fbp_layer_tree_rows", ())
        if 0 <= tree_index < len(rows):
            row = rows[tree_index]
            if str(getattr(row, "row_type", "") or "") == "LAYER":
                candidate = int(getattr(row, "layer_index", -1))
                if 0 <= candidate < len(layers):
                    rig = _safe_layer_obj(layers[candidate])
                    expected_name = str(getattr(row, "rig_name", "") or "")
                    if rig and (not expected_name or rig.name == expected_name):
                        return candidate
        if 0 <= legacy_index < len(layers):
            return legacy_index
    except FBP_DATA_ERRORS:
        pass
    return -1


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
        try:
            fbp_set_rna_property_silent(obj, 'fbp_color_tag', color_tag)
        except Exception:
            obj.fbp_color_tag = color_tag
    if variant_index is None:
        variant_index = getattr(obj, 'fbp_color_variant_index', 0)
    try:
        fbp_set_rna_property_silent(obj, 'fbp_color_variant_index', int(variant_index))
    except FBP_DATA_IO_ERRORS:
        pass
    obj.color = make_color_variant(color_tag, variant_index)
    plane = getattr(obj, 'fbp_plane_target', None)
    if plane:
        try:
            plane.color = obj.color
        except FBP_DATA_IO_ERRORS:
            pass
    if push_collection and coll:
        set_collection_color_tag(coll, color_tag)


def apply_collection_color_to_rig(rig, color_tag=None, variant_index=None, push_collection=False):
    apply_collection_color_to_layer(rig, color_tag, variant_index, push_collection)


def sync_collection_colors_to_rigs(context):
    if not context:
        return
    groups = {}
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
            groups.setdefault(coll.name, (coll, tag, []))[2].append(rig)
        except ReferenceError:
            pass

    for _name, (_coll, tag, rigs) in groups.items():
        rigs.sort(key=lambda rig: (
            int(getattr(rig, 'fbp_depth_order', 0)),
            getattr(rig, 'name', ''),
        ))
        use_variants = bool(getattr(context.scene, 'fbp_auto_collection_color_variants', True))
        for idx, rig in enumerate(rigs):
            try:
                variant_index = idx if use_variants else 0
                rig.fbp_color_variant_index = variant_index
                apply_collection_color_to_layer(rig, tag, variant_index, push_collection=False)
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
    except FBP_DATA_IO_ERRORS:
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
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        layer_coll = find_layer_collection(context.view_layer.layer_collection, collection)
        if layer_coll and (getattr(layer_coll, 'hide_viewport', False) or getattr(layer_coll, 'exclude', False)):
            return True
    except FBP_DATA_IO_ERRORS:
        pass
    return False


def _fbp_collection_ui_context_key(context=None):
    """Return a draw-local key without retaining Blender RNA references."""
    context = context or getattr(bpy, "context", None)
    scene = getattr(context, "scene", None) if context else None
    view_layer = getattr(context, "view_layer", None) if context else None
    if scene is None or view_layer is None:
        return None
    try:
        return (
            int(scene.as_pointer()),
            str(getattr(scene, "name_full", getattr(scene, "name", "")) or ""),
            int(view_layer.as_pointer()),
            str(getattr(view_layer, "name", "") or ""),
        )
    except FBP_DATA_ERRORS:
        return None


def _fbp_collection_ui_collection_key(collection):
    if collection is None:
        return None
    try:
        return (
            int(collection.as_pointer()),
            str(getattr(collection, "name_full", getattr(collection, "name", "")) or ""),
        )
    except FBP_DATA_ERRORS:
        return None


def fbp_clear_collection_ui_state_cache():
    """Drop immutable collection-row aggregates after a UI mutation."""
    _FBP_COLLECTION_UI_STATE_CACHE["context_key"] = None
    _FBP_COLLECTION_UI_STATE_CACHE["states"] = {}


def fbp_prime_collection_ui_state_cache(context, tree_cache=None):
    """Precompute all collection-row booleans once for the current UI draw.

    A collection row exposes several computed BoolProperties (solo, holdout,
    selection, rig lock and plane lock). Blender can query each property more
    than once while drawing the same row. Without this snapshot, every query
    recursively traversed the collection tree and repeatedly resolved the same
    rigs. Only immutable keys and scalar values are kept globally; Blender RNA
    objects remain local to this function.
    """
    context_key = _fbp_collection_ui_context_key(context)
    if context_key is None or not isinstance(tree_cache, dict):
        fbp_clear_collection_ui_state_cache()
        return {}

    collections = tree_cache.get("collections", {}) or {}
    descendant_keys = tree_cache.get("descendant_rig_keys", {}) or {}
    rig_by_key = tree_cache.get("rig_by_key", {}) or {}
    layer_item_by_key = tree_cache.get("layer_item_by_key", {}) or {}
    states = {}

    # Resolve expensive Blender state once per rig. Parent/child collections can
    # reference the same descendants, so doing this inside the collection loop
    # would repeat ViewLayer membership, material holdout and selection queries.
    rig_states = {}
    for rig_key, rig in rig_by_key.items():
        if rig is None:
            continue
        try:
            item = layer_item_by_key.get(rig_key)
            plane = getattr(rig, "fbp_plane_target", None)
            rig_states[rig_key] = {
                "rig": rig,
                "plane": plane,
                "in_view": object_in_view_layer(rig, context),
                "plane_in_view": bool(plane and object_in_view_layer(plane, context)),
                "selected": bool(rig.select_get()),
                "locked": bool(getattr(rig, "hide_select", False)),
                "plane_locked": bool(plane and getattr(plane, "hide_select", True)),
                "solo": bool(item and getattr(item, "solo", False)),
                "visible": bool(getattr(rig, "fbp_is_visible", True)),
                "holdout": bool(rig_holdout_is_active(rig)),
            }
        except FBP_DATA_ERRORS:
            continue

    for collection_key, collection in collections.items():
        rig_keys = tuple(descendant_keys.get(collection_key, ()) or ())
        if not rig_keys:
            continue
        member_states = [rig_states.get(key) for key in rig_keys]
        member_states = [state for state in member_states if state is not None]
        if not member_states:
            continue

        try:
            hidden = collection_is_hidden_in_view_layer(context, collection)
            all_locked = all(state["locked"] for state in member_states)
            plane_states = [state for state in member_states if state["plane"] is not None]
            all_planes_locked = bool(
                plane_states and all(state["plane_locked"] for state in plane_states)
            )
            all_selected = all(state["selected"] for state in member_states)
            visible_states = [state for state in member_states if state["in_view"]]
            visible_all_selected = bool(
                visible_states and all(state["selected"] for state in visible_states)
            )
            all_solo = all(state["solo"] for state in member_states)
            any_holdout = any(state["holdout"] for state in member_states)
            visible_plane_states = [state for state in plane_states if state["plane_in_view"]]
            visible_planes_locked = bool(
                visible_plane_states
                and all(state["plane_locked"] for state in visible_plane_states)
            )
            rows_disabled = bool(
                hidden
                or all_locked
                or all(not state["visible"] for state in member_states)
            )
        except FBP_DATA_ERRORS:
            continue

        states[collection_key] = {
            "visible": not hidden,
            "selected": all_selected,
            "selected_visible": visible_all_selected,
            "solo": all_solo,
            "locked": all_locked,
            "plane_locked": all_planes_locked,
            "plane_locked_visible": visible_planes_locked,
            "holdout": any_holdout,
            "rows_disabled": rows_disabled,
        }

    _FBP_COLLECTION_UI_STATE_CACHE["context_key"] = context_key
    _FBP_COLLECTION_UI_STATE_CACHE["states"] = states
    return states


def _fbp_cached_collection_ui_state(collection, context=None):
    context_key = _fbp_collection_ui_context_key(context)
    if context_key is None or context_key != _FBP_COLLECTION_UI_STATE_CACHE.get("context_key"):
        return None
    collection_key = _fbp_collection_ui_collection_key(collection)
    if collection_key is None:
        return None
    return (_FBP_COLLECTION_UI_STATE_CACHE.get("states", {}) or {}).get(collection_key)


def fbp_reset_layer_view_cache_state():
    """Forget Python-side collection cache ownership before loading a new Main."""
    global _FBP_LAYER_VIEW_CACHE_INITIALIZED
    _FBP_LAYER_VIEW_TAGGED_COLLECTIONS.clear()
    _FBP_LAYER_VIEW_DIRECT_COLLECTIONS.clear()
    _FBP_LAYER_VIEW_RECURSIVE_COLLECTIONS.clear()
    _FBP_LAYER_VIEW_CACHE_INITIALIZED = False
    fbp_clear_collection_ui_state_cache()


def _clear_layer_view_collection_flags(collection):
    if collection is None:
        return
    for key in ("fbp_has_fbp_content", "fbp_has_fbp_content_recursive"):
        try:
            if key in collection:
                del collection[key]
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
            pass


def fbp_rebuild_layer_view_cache(context):
    """Pre-compute which collections contain Frame by Plane rigs.

    Layer UI draw functions read these cached booleans instead of recursively
    scanning collection trees every redraw.
    """
    if not context or not getattr(context, "scene", None):
        return
    global _FBP_LAYER_VIEW_CACHE_INITIALIZED
    sc = context.scene

    # The old implementation rewrote two ID properties on every collection on
    # every sync. Besides scaling poorly, those writes can trigger unnecessary
    # depsgraph/notifier work. Clear all stale properties once per loaded Main,
    # then touch only collections tagged by the previous active-scene rebuild.
    try:
        if not _FBP_LAYER_VIEW_CACHE_INITIALIZED:
            collections_to_clear = tuple(bpy.data.collections)
        else:
            collections_to_clear = tuple(
                collection
                for name in tuple(_FBP_LAYER_VIEW_TAGGED_COLLECTIONS)
                if (collection := bpy.data.collections.get(name)) is not None
            )
        for collection in collections_to_clear:
            _clear_layer_view_collection_flags(collection)
        # Scene master collections are not guaranteed to resolve through
        # bpy.data.collections on every Blender version. There are normally only
        # a handful of Scenes, so clear those roots explicitly as well.
        for scene in getattr(bpy.data, "scenes", ()):
            _clear_layer_view_collection_flags(getattr(scene, "collection", None))
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not reset layer view cache", exc)
        return

    _FBP_LAYER_VIEW_TAGGED_COLLECTIONS.clear()
    _FBP_LAYER_VIEW_DIRECT_COLLECTIONS.clear()
    _FBP_LAYER_VIEW_RECURSIVE_COLLECTIONS.clear()
    _FBP_LAYER_VIEW_CACHE_INITIALIZED = True

    parent_map = {}
    try:
        stack = [sc.collection]
        seen = set()
        while stack:
            parent = stack.pop()
            if parent is None:
                continue
            parent_name = str(getattr(parent, "name", "") or "")
            if parent_name in seen:
                continue
            seen.add(parent_name)
            for child in getattr(parent, "children", ()):
                child_name = str(getattr(child, "name", "") or "")
                if child_name:
                    parent_map.setdefault(child_name, []).append(parent)
                stack.append(child)
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not map layer collection hierarchy", exc)
        parent_map = {}

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
                _FBP_LAYER_VIEW_TAGGED_COLLECTIONS.add(current.name)
                _FBP_LAYER_VIEW_RECURSIVE_COLLECTIONS.add(current.name)
            except FBP_DATA_IO_ERRORS:
                pass
            for parent in parent_map.get(current.name, []):
                stack.append(parent)

    # A collection can contain hundreds of layers. Mark each collection and its
    # ancestors once instead of rewriting the same ID properties once per layer.
    direct_collections = {}
    for item in getattr(sc, "fbp_layers", []):
        try:
            rig = item.obj
            if not rig or not is_fbp_layer_object(rig) or not object_in_scene(rig, sc):
                continue
            collection = get_primary_fbp_collection(rig)
            if collection is None:
                continue
            direct_collections[int(collection.as_pointer())] = collection
        except FBP_DATA_ERRORS:
            continue
        except Exception as exc:
            fbp_warn("Could not resolve layer collection for UI cache", exc)

    for collection in direct_collections.values():
        try:
            collection["fbp_has_fbp_content"] = True
            _FBP_LAYER_VIEW_TAGGED_COLLECTIONS.add(collection.name)
            _FBP_LAYER_VIEW_DIRECT_COLLECTIONS.add(collection.name)
            mark_collection(collection)
        except FBP_DATA_IO_ERRORS as exc:
            fbp_warn("Could not cache layer collection", exc)

    fbp_runtime_set("fbp_layer_cache_dirty", False, context)


def fbp_mark_layer_cache_dirty(context=None):
    fbp_runtime_set("fbp_layer_cache_dirty", True, context)


def collection_has_fbp_content(collection, recursive=True):
    if not collection:
        return False
    if _FBP_LAYER_VIEW_CACHE_INITIALIZED:
        try:
            name = str(getattr(collection, "name", "") or "")
            cache = (
                _FBP_LAYER_VIEW_RECURSIVE_COLLECTIONS
                if recursive else _FBP_LAYER_VIEW_DIRECT_COLLECTIONS
            )
            return name in cache
        except FBP_DATA_ERRORS:
            return False
    key = "fbp_has_fbp_content_recursive" if recursive else "fbp_has_fbp_content"
    try:
        if key in collection:
            return bool(collection.get(key, False))
    except FBP_DATA_IO_ERRORS:
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
    """Return each direct layer once, using its canonical FBP collection.

    Old or manually linked objects may belong to multiple Blender collections.
    The Layers UI must still show one stable row, so membership follows the same
    primary-collection resolver used by reorder and Clipping Mask operations.
    """
    if not collection:
        return []
    rigs = []
    seen = set()
    for item in getattr(context.scene, "fbp_layers", ()):
        try:
            rig = getattr(item, "obj", None)
            if (
                not rig
                or not is_fbp_layer_object(rig)
                or not object_in_scene(rig, context.scene)
            ):
                continue
            key = int(rig.as_pointer())
            if key in seen or get_primary_fbp_collection(rig) != collection:
                continue
            seen.add(key)
            rigs.append(rig)
        except FBP_DATA_ERRORS:
            continue
    return sort_rigs_by_depth_for_layer_view(context, rigs)


def fbp_clipping_source_map(context, rigs=None, *, collections=None):
    """Return the Procreate-style clipping source for each layer.

    Clipping follows physical camera depth, never the optional alphabetical UI
    view. Each layer is assigned through its canonical FBP collection so a
    legacy object linked into multiple Blender collections cannot acquire an
    unstable or cross-collection source. ``collections`` optionally limits the
    calculation to collections affected by one reorder operation.

    Scoped calls read only the direct objects of the requested collections.
    This avoids traversing every Scene layer when one icon is clicked or one
    collection is reordered.
    """
    result = {}
    scene = getattr(context, "scene", None)
    if scene is None:
        return result

    collection_scope = tuple(collections or ()) if collections is not None else None
    scope_keys = None
    if collection_scope is not None:
        scope_keys = set()
        for collection in collection_scope:
            try:
                if collection is not None:
                    scope_keys.add(int(collection.as_pointer()))
            except FBP_DATA_ERRORS:
                continue
        if not scope_keys:
            return result

    try:
        if rigs is not None:
            scene_rigs = tuple(rigs)
        elif collection_scope is not None:
            scoped_rigs = []
            seen_rigs = set()
            for collection in collection_scope:
                if collection is None:
                    continue
                try:
                    collection_objects = tuple(collection.objects)
                except FBP_DATA_ERRORS:
                    collection_objects = ()
                for rig in collection_objects:
                    try:
                        if (
                            not is_fbp_layer_object(rig)
                            or not object_in_scene(rig, scene)
                            or get_primary_fbp_collection(rig) != collection
                        ):
                            continue
                        key = int(rig.as_pointer())
                        if key in seen_rigs:
                            continue
                        seen_rigs.add(key)
                        scoped_rigs.append(rig)
                    except FBP_DATA_ERRORS:
                        continue
            scene_rigs = tuple(scoped_rigs)
        else:
            scene_rigs = tuple(iter_scene_fbp_rigs(scene))
    except (ReferenceError, RuntimeError, TypeError, ValueError):
        return result
    if not scene_rigs:
        return result

    by_collection = {}
    seen_rig_keys = set()
    try:
        for rig in scene_rigs:
            if (
                not rig
                or not is_fbp_layer_object(rig)
                or not object_in_scene(rig, scene)
            ):
                continue
            rig_key = int(rig.as_pointer())
            if rig_key in seen_rig_keys:
                continue
            seen_rig_keys.add(rig_key)
            collection = get_primary_fbp_collection(rig)
            if collection is None:
                continue
            collection_key = int(collection.as_pointer())
            if scope_keys is not None and collection_key not in scope_keys:
                continue
            by_collection.setdefault(collection_key, []).append(rig)
    except FBP_DATA_ERRORS:
        return result

    try:
        depth_context = fbp_make_depth_context_cache(context)
        depth_cache = {
            rig: fbp_layer_depth_value_from_cache(rig, depth_context)
            for collection_rigs in by_collection.values()
            for rig in collection_rigs if rig
        }
    except FBP_DATA_ERRORS:
        depth_cache = {}

    # Equal-depth layers are physically ambiguous. Keep their fallback order
    # stable across renames by preferring the Scene runtime order before names.
    scene_order = {}
    try:
        scene_order = {
            int(rig.as_pointer()): index
            for index, rig in enumerate(scene_rigs)
            if rig is not None
        }
    except FBP_DATA_ERRORS:
        scene_order = {}

    for collection_rigs in by_collection.values():
        displayed = sorted(
            collection_rigs,
            key=lambda rig: (
                (depth_cache or {}).get(rig, 0.0),
                scene_order.get(int(rig.as_pointer()), 1 << 30),
                natural_sort_key(rig.name),
            ),
        )
        clipping_flags = [
            fbp_layer_clipping_active_hint(candidate)
            for candidate in displayed
        ]
        for index, rig in enumerate(displayed):
            source = displayed[index + 1] if index + 1 < len(displayed) else None
            if clipping_flags[index]:
                # Stacked clipping layers share the first non-clipping base
                # below them instead of clipping to one another recursively.
                source = None
                for candidate_index in range(index + 1, len(displayed)):
                    if not clipping_flags[candidate_index]:
                        source = displayed[candidate_index]
                        break
            result[rig] = source if fbp_layer_has_sampleable_image(source) else None
    return result


def fbp_immediate_layer_below_map(context, rigs=None, *, collections=None):
    """Return the sampleable image layer immediately below each rig.

    Procedural Color, Gradient and Holdout layers currently have no image node
    that the pairwise shader can sample. They intentionally break the automatic
    relation instead of silently skipping to a more distant layer.
    """
    result = {}
    scene = getattr(context, "scene", None)
    if scene is None:
        return result
    collection_scope = tuple(collections or ()) if collections is not None else None
    try:
        if rigs is not None:
            scene_rigs = tuple(rigs)
        elif collection_scope is not None:
            scene_rigs = tuple(
                rig
                for collection in collection_scope if collection is not None
                for rig in iter_fbp_rigs_in_collection(collection, recursive=False)
                if get_primary_fbp_collection(rig) == collection
            )
        else:
            scene_rigs = tuple(iter_scene_fbp_rigs(scene))
    except FBP_DATA_ERRORS:
        return result
    by_collection = {}
    for rig in scene_rigs:
        try:
            if not rig or not is_fbp_layer_object(rig) or not object_in_scene(rig, scene):
                continue
            collection = get_primary_fbp_collection(rig)
            if collection is not None:
                by_collection.setdefault(int(collection.as_pointer()), []).append(rig)
        except FBP_DATA_ERRORS:
            continue
    try:
        depth_context = fbp_make_depth_context_cache(context)
        depth_cache = {rig: fbp_layer_depth_value_from_cache(rig, depth_context) for rigs_in_collection in by_collection.values() for rig in rigs_in_collection}
    except FBP_DATA_ERRORS:
        depth_cache = {}
    scene_order = {}
    try:
        scene_order = {int(rig.as_pointer()): index for index, rig in enumerate(scene_rigs) if rig is not None}
    except FBP_DATA_ERRORS:
        pass
    for collection_rigs in by_collection.values():
        displayed = sorted(
            collection_rigs,
            key=lambda rig: (
                depth_cache.get(rig, 0.0),
                scene_order.get(int(rig.as_pointer()), 1 << 30),
                natural_sort_key(rig.name),
            ),
        )
        for index, rig in enumerate(displayed):
            source = displayed[index + 1] if index + 1 < len(displayed) else None
            result[rig] = source if fbp_layer_has_sampleable_image(source) else None
    return result

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


def fbp_procedural_layer_type(rig):
    """Return the stable procedural layer type used by the Layers UI.

    Color/Gradient planes can have animated procedural frames. Holdout planes
    stay static masks. Selecting a frame updates the editable controls (`fbp_color_plane_mode`) to that
    material, but the layer row icon should not turn into an image/sequence icon
    just because the active frame changed. This custom property stores the
    original procedural family of the layer.
    """
    if not rig or not getattr(rig, 'fbp_is_color_plane', False):
        return ''
    try:
        stable = str(rig.get('fbp_procedural_layer_type', '') or '')
        if stable in {'SOLID', 'GRADIENT', 'HOLDOUT'}:
            return stable
    except FBP_DATA_IO_ERRORS:
        pass
    mode = str(getattr(rig, 'fbp_color_plane_mode', 'SOLID') or 'SOLID')
    if mode not in {'SOLID', 'GRADIENT', 'HOLDOUT'}:
        mode = 'SOLID'
    try:
        rig['fbp_procedural_layer_type'] = mode
    except FBP_DATA_IO_ERRORS:
        pass
    return mode


def fbp_color_plane_type_icon(rig):
    """Icon used for rigged color/gradient/holdout planes in layer rows."""
    if not rig or not getattr(rig, 'fbp_is_color_plane', False):
        return None

    mode = fbp_procedural_layer_type(rig)

    if mode == 'GRADIENT':
        return fbp_icon("COLOR")
    if mode == 'HOLDOUT':
        return fbp_icon("GHOST_DISABLED")

    # Use a material/color icon for solid color planes. Do not use IMAGE here:
    # it looks like an imported image sequence and confused the layer list.
    return fbp_icon("MATERIAL")


def fbp_procedural_kind_from_material(mat, fallback='SOLID'):
    """Return SOLID / GRADIENT / HOLDOUT for a procedural frame material."""
    if not mat:
        return fallback if fallback in {'SOLID', 'GRADIENT', 'HOLDOUT'} else 'SOLID'
    try:
        explicit = str(mat.get('fbp_procedural_kind', '') or '')
        if explicit in {'SOLID', 'GRADIENT', 'HOLDOUT'}:
            return explicit
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        if bool(mat.get('fbp_gradient_material', False)):
            return 'GRADIENT'
        if bool(mat.get('fbp_holdout_material', False)):
            return 'HOLDOUT'
    except FBP_DATA_IO_ERRORS:
        pass
    return fallback if fallback in {'SOLID', 'GRADIENT', 'HOLDOUT'} else 'SOLID'


def fbp_procedural_kind_for_item(rig, index, fallback='SOLID'):
    """Return the stored per-row procedural type, falling back to its material."""
    try:
        if 0 <= int(index) < len(rig.fbp_images):
            item_kind = str(getattr(rig.fbp_images[int(index)], 'procedural_kind', 'AUTO') or 'AUTO')
            if item_kind in {'SOLID', 'GRADIENT', 'HOLDOUT'}:
                return item_kind
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        plane = getattr(rig, 'fbp_plane_target', None)
        if plane and getattr(plane, 'data', None) and 0 <= int(index) < len(plane.data.materials):
            return fbp_procedural_kind_from_material(plane.data.materials[int(index)], fallback)
    except FBP_DATA_IO_ERRORS:
        pass
    return fallback if fallback in {'SOLID', 'GRADIENT', 'HOLDOUT'} else 'SOLID'


def fbp_set_procedural_metadata(mat, kind):
    """Store the procedural kind on a material when possible."""
    if not mat:
        return
    try:
        if kind in {'SOLID', 'GRADIENT', 'HOLDOUT'}:
            mat['fbp_procedural_kind'] = kind
    except FBP_DATA_IO_ERRORS:
        pass


def fbp_procedural_preview_from_material(mat, fallback_kind='SOLID'):
    """Return (kind, color_a, color_b) for UIList drawing without later node scans.

    This is intentionally called while changing sequence data, not from UIList
    draw_item(). The UI can then read cached colors from each FBP_ImageItem.
    """
    kind = fbp_procedural_kind_from_material(mat, fallback_kind)
    color_a = (1.0, 1.0, 1.0, 1.0)
    color_b = (1.0, 1.0, 1.0, 1.0)
    if not mat:
        return kind, color_a, color_b
    try:
        if kind == 'GRADIENT':
            ramp = find_fbp_gradient_ramp_node(mat)
            elems = list(getattr(getattr(ramp, 'color_ramp', None), 'elements', [])) if ramp else []
            if elems:
                color_a = tuple(elems[0].color)
                color_b = tuple(elems[-1].color)
                return kind, color_a, color_b
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        color_a = tuple(getattr(mat, 'diffuse_color', color_a))
        color_b = color_a
    except FBP_DATA_IO_ERRORS:
        pass
    return kind, color_a, color_b


def fbp_cache_procedural_preview_on_item(item, mat, fallback_kind='SOLID'):
    if not item:
        return
    try:
        ptr = item.as_pointer()
    except Exception:
        ptr = None
    try:
        if ptr is not None:
            _FBP_SYNCING_PROCEDURAL_PREVIEW_ITEMS.add(ptr)
        kind, color_a, color_b = fbp_procedural_preview_from_material(mat, fallback_kind)
        if kind in {'SOLID', 'GRADIENT', 'HOLDOUT'}:
            item.procedural_kind = kind
        item.preview_color_a = color_a
        item.preview_color_b = color_b
    except FBP_DATA_IO_ERRORS:
        pass
    finally:
        try:
            if ptr is not None:
                _FBP_SYNCING_PROCEDURAL_PREVIEW_ITEMS.discard(ptr)
        except FBP_DATA_IO_ERRORS:
            pass


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
    cached = _fbp_cached_collection_ui_state(collection, context)
    if cached is not None:
        if bool(cached.get("locked", False)):
            return fbp_icon("LAYER_USED")
        return fbp_icon("CHECKBOX_HLT") if bool(cached.get("selected_visible", False)) else fbp_icon("CHECKBOX_DEHLT")
    if bool(getattr(collection, 'fbp_collection_locked', False)):
        return fbp_icon("LAYER_USED")
    rigs = [rig for rig in iter_fbp_rigs_in_collection(collection, True) if object_in_view_layer(rig, context)]
    if rigs and all(rig.select_get() for rig in rigs):
        return fbp_icon("CHECKBOX_HLT")
    return fbp_icon("CHECKBOX_DEHLT")


def fbp_collection_plane_icon(collection, context):
    """Icon for linked image/color plane selectability inside a collection."""
    cached = _fbp_cached_collection_ui_state(collection, context)
    if cached is not None:
        return fbp_icon("RESTRICT_SELECT_ON") if bool(cached.get("plane_locked_visible", False)) else fbp_icon("RESTRICT_SELECT_OFF")
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
    """Return a thumbnail when enabled, otherwise the rig Color Tag icon."""
    if bool(getattr(context.scene, 'fbp_show_previews', False)) and not bool(getattr(rig, 'fbp_is_color_plane', False)):
        preview = get_layer_thumbnail(rig, scene=getattr(context, "scene", None))
        if preview:
            return None, preview.icon_id
    try:
        return fbp_strip_icon(getattr(rig, 'fbp_color_tag', 'COLOR_09')), None
    except Exception:
        return fbp_icon("STRIP_COLOR_09"), None


def fbp_set_ui_units_x(ui_layout, units):
    """Best-effort fixed UI width helper for compact icon blocks.

    Blender supports ui_units_x on recent versions. When unavailable, this
    quietly falls back to the normal dynamic layout instead of breaking UI draw.
    """
    try:
        ui_layout.ui_units_x = units
    except FBP_DATA_IO_ERRORS:
        pass


def fbp_collection_rows_are_disabled(collection, context):
    """Return whether collection text/icon should look inactive while controls stay usable."""
    cached = _fbp_cached_collection_ui_state(collection, context)
    if cached is not None:
        return bool(cached.get("rows_disabled", False))
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

    op_hold = right.operator("fbp.toggle_layer_holdout", text="", icon=fbp_mask_icon(item.holdout), emboss=False)
    op_hold.rig_name = rig.name

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

    op_hold = right.operator("fbp.toggle_collection_holdout", text="", icon=fbp_mask_icon(collection.fbp_collection_holdout), emboss=False)
    op_hold.collection_name = collection.name

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
            if not is_supported_media_file(filename) or (not is_supported_video_file(filename) and is_technical_map_file(filename)):
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
                except FBP_DATA_IO_ERRORS:
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


def swap_layer_depth_only(context, rig_a, rig_b, *, depth_context=None):
    if not rig_a or not rig_b:
        return
    # Match the same camera-relative depth metric used by the Layer List. This
    # keeps Move Up/Down and Reverse Selected correct even with a rotated camera.
    try:
        depth_context = depth_context or fbp_make_depth_context_cache(context)
        if depth_context.get("has_camera"):
            camera_location = depth_context["camera_location"]
            forward = depth_context["camera_forward"].normalized()
            world_a = rig_a.matrix_world.copy()
            world_b = rig_b.matrix_world.copy()
            depth_a = float((world_a.translation - camera_location).dot(forward))
            depth_b = float((world_b.translation - camera_location).dot(forward))
            world_a.translation += forward * (depth_b - depth_a)
            world_b.translation += forward * (depth_a - depth_b)
            rig_a.matrix_world = world_a
            rig_b.matrix_world = world_b
            return
    except FBP_DATA_ERRORS:
        pass

    # No usable camera: preserve the established vertical/horizontal axis rule.
    axis = 1 if (getattr(rig_a, 'fbp_is_vertical', False) or getattr(rig_b, 'fbp_is_vertical', False)) else 2
    try:
        world_a = rig_a.matrix_world.copy()
        world_b = rig_b.matrix_world.copy()
        depth_a = float(world_a.translation[axis])
        depth_b = float(world_b.translation[axis])
        world_a.translation[axis] = depth_b
        world_b.translation[axis] = depth_a
        rig_a.matrix_world = world_a
        rig_b.matrix_world = world_b
    except FBP_DATA_ERRORS:
        # Conservative fallback for incomplete objects during file load.
        loc_a = rig_a.location.copy()
        loc_b = rig_b.location.copy()
        loc_a[axis], loc_b[axis] = loc_b[axis], loc_a[axis]
        rig_a.location = loc_a
        rig_b.location = loc_b


def iter_scene_fbp_rigs(scene, *, fallback=True):
    """Yield synchronized FBP rigs without rescanning the Scene on hot paths."""
    if not scene:
        return
    seen = set()
    yielded = False
    try:
        for item in getattr(scene, "fbp_layers", ()) or ():
            rig = getattr(item, "obj", None)
            if not rig or not is_fbp_layer_object(rig):
                continue
            try:
                key = int(rig.as_pointer())
            except FBP_DATA_ERRORS:
                key = str(getattr(rig, "name", "") or "")
            if key in seen or not object_in_scene(rig, scene):
                continue
            seen.add(key)
            yielded = True
            yield rig
    except FBP_DATA_ERRORS:
        pass

    # The cache is populated by initial/import/depsgraph synchronization. A full
    # fallback is needed only during the very first tick of an unsynchronized file.
    if yielded or not fallback:
        return
    try:
        for obj in scene.objects:
            if is_fbp_layer_object(obj):
                yield obj
    except FBP_DATA_ERRORS:
        return


def object_in_scene(obj, scene=None):
    """Return membership without linearly scanning every object in the Scene."""
    if obj is None:
        return False
    try:
        name = str(obj.name)
        if bpy.data.objects.get(name) != obj:
            return False
        scene = scene or (bpy.context.scene if bpy.context else None)
        if not scene:
            return True
        return scene.objects.get(name) == obj
    except FBP_DATA_ERRORS:
        return False


def object_in_view_layer(obj, context=None):
    context = context or bpy.context
    if obj is None or context is None:
        return False
    try:
        if not object_in_scene(obj, context.scene):
            return False
        return context.view_layer.objects.get(str(obj.name)) == obj
    except FBP_DATA_ERRORS:
        return False


def ensure_object_in_active_collection(obj, context=None):
    context = context or bpy.context
    if obj is None or context is None:
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
    return get_selected_fbp_roots(context)


def fbp_resolve_rig_from_any_object(obj, context=None):
    """Return the current FBP rig represented by a rig or its linked plane."""
    if obj is None:
        return None
    try:
        if getattr(obj, "is_fbp_control", False):
            return obj
        try:
            from .effect_controls import effect_control_owner, is_effect_control
            if is_effect_control(obj):
                owner = effect_control_owner(obj)
                if owner and getattr(owner, "is_fbp_control", False):
                    return owner
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        if str(getattr(obj, "type", "") or "") == "LATTICE":
            # Parenting is the native ownership contract and survives rig
            # renames. The readable name tag is only a repair fallback. Older
            # builds resolved the tag first, so a stale name could make the
            # Effects panel disappear even while the cage was correctly parented.
            owner = getattr(obj, "parent", None)
            if owner and getattr(owner, "is_fbp_control", False):
                return owner
            owner_name = str(obj.get("fbp_lattice_owner", "") or "")
            owner = bpy.data.objects.get(owner_name) if owner_name else None
            if owner and getattr(owner, "is_fbp_control", False):
                return owner
        try:
            from .object_masks import find_object_mask_owner, is_object_mask_helper
            if is_object_mask_helper(obj):
                plane = getattr(obj, "parent", None)
                parent_rig = getattr(plane, "parent", None) if plane else None
                if parent_rig and getattr(parent_rig, "is_fbp_control", False):
                    return parent_rig
                # Repair-tolerant fallback for helpers whose parenting was
                # changed manually or temporarily lost during Undo/file load.
                owner = find_object_mask_owner(obj)
                if owner and getattr(owner, "is_fbp_control", False):
                    return owner
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        if not getattr(obj, "is_fbp_plane", False):
            return None
        parent = getattr(obj, "parent", None)
        if parent and getattr(parent, "is_fbp_control", False):
            return parent
        rig_name = str(obj.get("fbp_parent_rig_name", "") or "")
        rig = bpy.data.objects.get(rig_name) if rig_name else None
        return rig if rig and getattr(rig, "is_fbp_control", False) else None
    except ReferenceError:
        return None


def get_selected_fbp_roots(context):
    """Return selected FBP rigs with the active rig first for reliable multi-edit UI."""
    roots = []
    selected = list(getattr(context, "selected_objects", []) or [])
    active = getattr(context, "object", None)
    ordered = ([active] if active else []) + [obj for obj in selected if obj != active]
    for ob in ordered:
        rig = fbp_resolve_rig_from_any_object(ob, context)
        if rig and rig not in roots:
            roots.append(rig)
    return roots


def invalidate_preview_path(image_path):
    """Invalidate one media thumbnail without flushing unrelated previews."""
    if not image_path:
        return False
    try:
        abs_path = os.path.normcase(os.path.abspath(bpy.path.abspath(image_path)))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OSError):
        return False
    invalidate_file_exists_cache(abs_path)
    changed = False
    raw = preview_collections.get("fbp_previews")
    if raw is not None:
        try:
            if abs_path in raw:
                del raw[abs_path]
                changed = True
        except (KeyError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    try:
        _FBP_RAW_PREVIEW_KEYS.remove(abs_path)
    except ValueError:
        pass
    composite = preview_collections.get(_FBP_COMPOSITE_PREVIEW_COLLECTION)
    if composite is not None:
        prefix = f"{abs_path}|"
        try:
            stale = [key for key in composite.keys() if str(key).startswith(prefix)]
        except FBP_DATA_ERRORS:
            stale = []
        for key in stale:
            try:
                del composite[key]
                changed = True
            except (KeyError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        if stale:
            stale_set = set(stale)
            retained = [key for key in _FBP_COMPOSITE_PREVIEW_KEYS if key not in stale_set]
            _FBP_COMPOSITE_PREVIEW_KEYS.clear()
            _FBP_COMPOSITE_PREVIEW_KEYS.extend(retained)
    _FBP_PREVIEW_MISS_CACHE.pop(abs_path, None)
    return changed


def clear_previews():
    _FBP_COMPOSITE_PREVIEW_KEYS.clear()
    _FBP_RAW_PREVIEW_KEYS.clear()
    for pcoll in preview_collections.values():
        try:
            bpy.utils.previews.remove(pcoll)
        except FBP_DATA_ERRORS:
            pass
    preview_collections.clear()
    _FBP_PREVIEW_MISS_CACHE.clear()
    try:
        from .drawing_plane import clear_drawing_preview_runtime_state
        clear_drawing_preview_runtime_state()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


def update_rig_visibility(rig, layer_item=None, context=None):
    """Apply one rig's visibility contract without scanning every layer."""
    if not rig:
        return False
    try:
        if layer_item is None:
            context = context or getattr(bpy, "context", None)
            layer_item = get_layer_item_for_rig(context, rig) if context else None
        visible = bool(getattr(rig, "fbp_is_visible", True)) and not bool(
            getattr(layer_item, "mute", False) if layer_item is not None else False
        )
        plane = getattr(rig, "fbp_plane_target", None)
        if not plane:
            return False
        hidden = not visible
        if bool(getattr(plane, "hide_viewport", False)) != hidden:
            plane.hide_viewport = hidden
        if bool(getattr(plane, "hide_render", False)) != hidden:
            plane.hide_render = hidden
        try:
            from .geometry_nodes import (
                fbp_apply_matte_source_visibility,
                fbp_schedule_clipping_mask_sync,
            )
            target_scene = getattr(context, "scene", None) if context else None
            fbp_apply_matte_source_visibility(
                rig, scene=target_scene, restore_normal=False
            )
            # Clipping Mask follows the visible alpha of its base layer.  The
            # scheduler coalesces collection/solo operations into one repair.
            fbp_schedule_clipping_mask_sync(target_scene)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        return True
    except FBP_DATA_ERRORS:
        return False


def update_global_visibility(context=None):
    context = context or getattr(bpy, "context", None)
    scene = getattr(context, "scene", None) if context else None
    if scene is None:
        return
    for item in getattr(scene, "fbp_layers", ()) or ():
        try:
            update_rig_visibility(item.obj, item, context)
        except ReferenceError:
            pass
    fbp_clear_collection_ui_state_cache()


def update_mute_cb(self, context):
    """Mute only the edited layer; collection/solo operations call the global path."""
    try:
        update_rig_visibility(self.obj, self, context)
    except FBP_DATA_ERRORS:
        pass
    fbp_clear_collection_ui_state_cache()


def get_preview_collection():
    pcoll = preview_collections.get("fbp_previews")
    if not pcoll:
        pcoll = bpy.utils.previews.new()
        preview_collections["fbp_previews"] = pcoll
    return pcoll


def _get_composite_preview_collection():
    pcoll = preview_collections.get(_FBP_COMPOSITE_PREVIEW_COLLECTION)
    if pcoll is None:
        pcoll = bpy.utils.previews.new()
        preview_collections[_FBP_COMPOSITE_PREVIEW_COLLECTION] = pcoll
    return pcoll


def thumbnail_background_state(scene=None):
    """Return ``(enabled, rgba)`` for the active Scene thumbnail background."""
    if scene is None:
        try:
            scene = bpy.context.scene
        except (AttributeError, ReferenceError, RuntimeError):
            scene = None
    enabled = bool(getattr(scene, "fbp_thumbnail_background_enabled", False)) if scene else False
    try:
        color = tuple(float(value) for value in scene.fbp_thumbnail_background_color) if scene else (1.0, 1.0, 1.0)
        rgba = (color[0], color[1], color[2], 1.0)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, IndexError):
        rgba = (1.0, 1.0, 1.0, 1.0)
    return enabled, rgba


def _remember_composite_preview(pcoll, cache_key):
    _FBP_COMPOSITE_PREVIEW_KEYS.append(cache_key)
    while len(_FBP_COMPOSITE_PREVIEW_KEYS) > _FBP_COMPOSITE_PREVIEW_LIMIT:
        oldest = _FBP_COMPOSITE_PREVIEW_KEYS.popleft()
        if oldest == cache_key:
            continue
        try:
            del pcoll[oldest]
        except (KeyError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass


def _remember_raw_preview(pcoll, cache_key):
    """Maintain a bounded LRU for source thumbnails.

    Blender preview collections retain native thumbnail buffers. Large Cutout
    and multiplane libraries previously accumulated one entry per visited file
    for the whole session, even after the UI moved on to other projects.
    """
    try:
        _FBP_RAW_PREVIEW_KEYS.remove(cache_key)
    except ValueError:
        pass
    _FBP_RAW_PREVIEW_KEYS.append(cache_key)
    while len(_FBP_RAW_PREVIEW_KEYS) > _FBP_RAW_PREVIEW_LIMIT:
        oldest = _FBP_RAW_PREVIEW_KEYS.popleft()
        try:
            if oldest in pcoll:
                del pcoll[oldest]
        except (KeyError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass


def _load_raw_preview(image_path):
    """Load Blender's source thumbnail and throttle repeated filesystem misses."""
    pcoll = get_preview_collection()
    abs_path = os.path.normcase(os.path.abspath(bpy.path.abspath(image_path)))
    if abs_path in pcoll:
        _FBP_PREVIEW_MISS_CACHE.pop(abs_path, None)
        _remember_raw_preview(pcoll, abs_path)
        return pcoll[abs_path], abs_path
    now = time.monotonic()
    last_miss = float(_FBP_PREVIEW_MISS_CACHE.get(abs_path, 0.0) or 0.0)
    if last_miss and now - last_miss < _FBP_PREVIEW_MISS_TTL:
        return None, abs_path
    if os.path.isfile(abs_path):
        try:
            preview = pcoll.load(abs_path, abs_path, 'IMAGE')
            _FBP_PREVIEW_MISS_CACHE.pop(abs_path, None)
            _remember_raw_preview(pcoll, abs_path)
            return preview, abs_path
        except FBP_DATA_IO_ERRORS:
            pass
    _FBP_PREVIEW_MISS_CACHE[abs_path] = now
    if len(_FBP_PREVIEW_MISS_CACHE) > 2048:
        cutoff = now - _FBP_PREVIEW_MISS_TTL
        for path, timestamp in list(_FBP_PREVIEW_MISS_CACHE.items()):
            if float(timestamp or 0.0) < cutoff:
                _FBP_PREVIEW_MISS_CACHE.pop(path, None)
        while len(_FBP_PREVIEW_MISS_CACHE) > 2048:
            oldest = next(iter(_FBP_PREVIEW_MISS_CACHE), None)
            if oldest is None:
                break
            _FBP_PREVIEW_MISS_CACHE.pop(oldest, None)
    return None, abs_path


def _square_preview_pixels(width, height, pixels, *, background_enabled, background):
    """Letterbox a small Blender thumbnail without touching source Image pixels."""
    width = max(1, int(width))
    height = max(1, int(height))
    side = max(width, height)
    output = [0.0] * (side * side * 4)
    br, bg, bb = background[:3]
    if background_enabled:
        for offset in range(0, len(output), 4):
            output[offset:offset + 4] = (br, bg, bb, 1.0)

    x_offset = (side - width) // 2
    y_offset = (side - height) // 2
    for y in range(height):
        source_row = y * width * 4
        target_row = (y + y_offset) * side * 4
        for x in range(width):
            source = source_row + x * 4
            target = target_row + (x + x_offset) * 4
            red, green, blue, alpha = pixels[source:source + 4]
            alpha = max(0.0, min(1.0, float(alpha)))
            if background_enabled:
                output[target] = float(red) * alpha + br * (1.0 - alpha)
                output[target + 1] = float(green) * alpha + bg * (1.0 - alpha)
                output[target + 2] = float(blue) * alpha + bb * (1.0 - alpha)
                output[target + 3] = 1.0
            else:
                output[target:target + 4] = (float(red), float(green), float(blue), alpha)
    return side, output


def load_preview(image_path, scene=None, *, force_square=False):
    """Return a cached thumbnail with optional global background and letterboxing.

    Full-resolution Image pixels are never read. Compositing operates only on
    Blender's small preview buffer and is cached independently from the source
    thumbnail, keeping normal UI redraws cheap.
    """
    if not image_path:
        return None
    base, abs_path = _load_raw_preview(image_path)
    if base is None:
        return None
    background_enabled, background = thumbnail_background_state(scene)
    if not background_enabled and not force_square:
        return base

    try:
        width, height = (int(value) for value in base.image_size)
    except FBP_DATA_ERRORS:
        return base
    if width <= 0 or height <= 0:
        return base
    # A square source already fits a square custom icon. Without a background
    # there is nothing to composite, so avoid copying its preview pixels.
    if force_square and not background_enabled and width == height:
        return base

    color_key = tuple(round(value, 4) for value in background[:3])
    square_output = bool(background_enabled or force_square)
    cache_key = f"{abs_path}|{int(getattr(base, 'icon_id', 0) or 0)}|bg{int(background_enabled)}|{color_key}|square{int(square_output)}|v3"
    pcoll = _get_composite_preview_collection()
    if cache_key in pcoll:
        return pcoll[cache_key]
    try:
        pixels = list(base.image_pixels_float)
        if len(pixels) != width * height * 4:
            return base
        side, output = _square_preview_pixels(
            width,
            height,
            pixels,
            background_enabled=background_enabled,
            background=background,
        )
        preview = pcoll.new(cache_key)
        preview.image_size = (side, side)
        preview.image_pixels_float = output
        _remember_composite_preview(pcoll, cache_key)
        return preview
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError):
        try:
            del pcoll[cache_key]
        except (KeyError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        return base


def get_layer_thumbnail(obj, scene=None):
    if not obj:
        return None
    if bool(getattr(obj, "fbp_is_drawing_plane", False)):
        try:
            from .drawing_plane import (
                fbp_drawing_index,
                load_drawing_preview,
                load_empty_drawing_preview,
            )
            if fbp_drawing_index(obj) == 0:
                return load_empty_drawing_preview(obj, scene=scene)
            path = str(getattr(obj, "fbp_preview_path", "") or "")
            return load_drawing_preview(obj, path, scene=scene) if path else None
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    if not hasattr(obj, "fbp_preview_path") or not obj.fbp_preview_path:
        return None
    return load_preview(obj.fbp_preview_path, scene=scene)


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
                        except FBP_DATA_IO_ERRORS:
                            pass
                    # Use object colors for wire display if available in this Blender version.
                    for attr in ('wireframe_color_type', 'wire_color_type'):
                        if hasattr(shading, attr):
                            try:
                                setattr(shading, attr, 'OBJECT')
                            except FBP_DATA_IO_ERRORS:
                                pass


def fbp_make_depth_context_cache(context):
    """Precompute camera vectors once for UI sorting/redraw paths.

    UIList.filter_items can be called very often while the mouse is moving.
    Keeping the active camera matrix calculation outside the per-layer sort key
    prevents repeated matrix work during redraw.
    """
    try:
        scene = getattr(context, "scene", None) if context else None
        cam = scene.camera if scene else None
        if cam:
            forward = cam.matrix_world.to_quaternion() @ mathutils.Vector((0.0, 0.0, -1.0))
            if forward.length_squared > 1.0e-12:
                forward.normalize()
                return {
                    "has_camera": True,
                    "camera_location": cam.matrix_world.translation.copy(),
                    "camera_forward": forward,
                }
    except ReferenceError:
        pass
    except (AttributeError, TypeError, RuntimeError) as exc:
        fbp_warn("Could not build layer depth camera cache", exc)
    return {"has_camera": False}


def fbp_layer_depth_value_from_cache(rig, depth_cache=None):
    """Return a stable depth value using a precomputed context cache when available."""
    if not rig:
        return 0.0
    try:
        if depth_cache and depth_cache.get("has_camera"):
            return float((rig.matrix_world.translation - depth_cache["camera_location"]).dot(depth_cache["camera_forward"]))
        return float(rig.location.y if getattr(rig, "fbp_is_vertical", False) else rig.location.z)
    except ReferenceError:
        return 0.0
    except (AttributeError, TypeError, RuntimeError, ValueError) as exc:
        fbp_warn("Could not compute layer depth", exc)
        return 0.0


def sort_rigs_for_layer_view(context, rigs):
    # Materialize once: some callers may provide generators. Building a depth
    # cache and then sorting the same generator would otherwise consume it twice
    # and return an empty layer list.
    rigs = tuple(rigs or ())
    if not context:
        return list(rigs)
    if getattr(context.scene, 'fbp_sort_layers_alpha', False):
        return sorted(rigs, key=lambda rig: natural_sort_key(rig.name))
    # Farther layers first internally; UI reverses this where needed so closest appears on top.
    # Sort only by physical depth. The input order is already the stable runtime
    # order, so equal-depth layers no longer jump when their names change.
    depth_ctx = fbp_make_depth_context_cache(context)
    depth_cache = {
        rig: fbp_layer_depth_value_from_cache(rig, depth_ctx)
        for rig in rigs if rig
    }
    return sorted(
        rigs,
        key=lambda rig: depth_cache.get(rig, 0.0),
        reverse=True,
    )


def sort_rigs_by_depth_for_layer_view(context, rigs):
    return sort_rigs_for_layer_view(context, rigs)


def sort_collections_for_layer_view(context, collections):
    if getattr(context.scene, 'fbp_sort_layers_alpha', False):
        return sorted(collections, key=lambda c: natural_sort_key(c.name))
    depth_ctx = fbp_make_depth_context_cache(context)
    def _collection_depth(coll):
        rigs = list(iter_fbp_rigs_in_collection(coll, True))
        if not rigs:
            return 0.0
        return sum(fbp_layer_depth_value_from_cache(rig, depth_ctx) for rig in rigs) / max(1, len(rigs))
    return sorted(collections, key=lambda c: (_collection_depth(c), natural_sort_key(c.name)), reverse=True)


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
    except FBP_DATA_IO_ERRORS:
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
                    fbp_set_rna_property_silent(obj, "fbp_is_visible", False)

        self.solo = True
        if rig:
            fbp_set_rna_property_silent(rig, "fbp_is_visible", True)
    else:
        self.solo = False
        if rig:
            fbp_set_rna_property_silent(rig, "fbp_is_visible", False)

        # If no layer remains soloed, restore all layers.
        if not any(item.solo for item in sc.fbp_layers):
            for item in sc.fbp_layers:
                obj = _safe_layer_obj(item)
                if obj:
                    fbp_set_rna_property_silent(obj, "fbp_is_visible", True)

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
        fbp_warn("Holdout toggle skipped", exc)


def _collection_rigs_for_ui(collection):
    try:
        return list(iter_fbp_rigs_in_collection(collection, True))
    except Exception:
        return []


def get_collection_selected(self):
    cached = _fbp_cached_collection_ui_state(self)
    if cached is not None:
        return bool(cached.get("selected", False))
    rigs = _collection_rigs_for_ui(self)
    try:
        items = [get_layer_item_for_rig(bpy.context, rig) for rig in rigs]
        items = [item for item in items if item is not None]
        return bool(items and len(items) == len(rigs) and all(item.selected for item in items))
    except Exception:
        return False


def set_collection_selected(self, value):
    context = getattr(bpy, "context", None)
    selected_value = bool(value)
    last_selected = None
    for rig in _collection_rigs_for_ui(self):
        try:
            if selected_value and context and not object_in_view_layer(rig, context):
                if not ensure_object_in_active_collection(rig, context):
                    continue
            rig.select_set(selected_value)
            if selected_value and object_in_view_layer(rig, context):
                last_selected = rig
        except FBP_DATA_IO_ERRORS:
            continue
    if last_selected is not None and context and getattr(context, "view_layer", None):
        try:
            context.view_layer.objects.active = last_selected
        except FBP_DATA_IO_ERRORS:
            pass
    fbp_clear_collection_ui_state_cache()


def get_collection_solo(self):
    cached = _fbp_cached_collection_ui_state(self)
    if cached is not None:
        return bool(cached.get("solo", False))
    rigs = _collection_rigs_for_ui(self)
    try:
        items = [get_layer_item_for_rig(bpy.context, rig) for rig in rigs]
        items = [item for item in items if item is not None]
        return bool(items and len(items) == len(rigs) and all(item.solo_view for item in items))
    except Exception:
        return False


def set_collection_solo(self, value):
    context = getattr(bpy, "context", None)
    scene = getattr(context, "scene", None) if context else None
    if not scene:
        return
    target_rigs = _collection_rigs_for_ui(self)
    try:
        target_keys = {
            int(rig.as_pointer())
            for rig in target_rigs
            if rig is not None
        }
        value = bool(value)
        items = list(getattr(scene, "fbp_layers", ()) or ())

        if value and not any(bool(getattr(item, "solo", False)) for item in items):
            for item in items:
                item.solo = False
                rig = _safe_layer_obj(item)
                if rig:
                    fbp_set_rna_property_silent(rig, "fbp_is_visible", False)

        for item in items:
            rig = _safe_layer_obj(item)
            if not rig:
                continue
            try:
                key = int(rig.as_pointer())
            except FBP_DATA_ERRORS:
                continue
            if key not in target_keys:
                continue
            item.solo = value
            fbp_set_rna_property_silent(rig, "fbp_is_visible", value)

        if not any(bool(getattr(item, "solo", False)) for item in items):
            for item in items:
                rig = _safe_layer_obj(item)
                if rig:
                    fbp_set_rna_property_silent(rig, "fbp_is_visible", True)

        update_global_visibility(context)
    except Exception as exc:
        fbp_warn("Could not update collection solo visibility", exc)

def get_collection_locked(self):
    cached = _fbp_cached_collection_ui_state(self)
    if cached is not None:
        return bool(cached.get("locked", False))
    rigs = _collection_rigs_for_ui(self)
    return bool(rigs and all(getattr(rig, 'hide_select', False) for rig in rigs))


def set_collection_locked(self, value):
    for rig in _collection_rigs_for_ui(self):
        rig.hide_select = bool(value)
    fbp_clear_collection_ui_state_cache()


def get_collection_plane_locked(self):
    cached = _fbp_cached_collection_ui_state(self)
    if cached is not None:
        return bool(cached.get("plane_locked", False))
    planes = []
    for rig in _collection_rigs_for_ui(self):
        plane = getattr(rig, 'fbp_plane_target', None)
        if plane:
            planes.append(plane)
    return bool(planes and all(bool(getattr(plane, 'hide_select', True)) for plane in planes))


def set_collection_plane_locked(self, value):
    for rig in _collection_rigs_for_ui(self):
        plane = getattr(rig, 'fbp_plane_target', None)
        if not plane:
            continue
        try:
            plane.hide_select = bool(value)
            if plane.hide_select and plane.select_get():
                plane.select_set(False)
        except ReferenceError:
            continue
        except Exception as exc:
            fbp_warn('Could not paint collection linked plane selectability', exc)
    fbp_clear_collection_ui_state_cache()


def get_collection_visible(self):
    cached = _fbp_cached_collection_ui_state(self)
    if cached is not None:
        return bool(cached.get("visible", True))
    try:
        return not collection_is_hidden_in_view_layer(bpy.context, self)
    except Exception:
        return True


def set_collection_visible(self, value):
    hidden = not bool(value)
    try:
        self.hide_viewport = hidden
    except FBP_DATA_IO_ERRORS:
        pass
    fbp_clear_collection_ui_state_cache()
    try:
        layer_coll = find_layer_collection(bpy.context.view_layer.layer_collection, self)
        if layer_coll:
            layer_coll.hide_viewport = hidden
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        update_global_visibility(bpy.context)
    except FBP_DATA_IO_ERRORS:
        pass
    # The UIList is a virtual tree. Force its signature to rebuild immediately
    # after parent visibility changes so stale child-eye states are never shown.
    try:
        scene = getattr(bpy.context, "scene", None)
        if scene:
            scene.fbp_layer_tree_signature = ""
        for area in getattr(getattr(bpy.context, "screen", None), "areas", ()):
            if getattr(area, "type", "") == 'VIEW_3D':
                area.tag_redraw()
    except FBP_DATA_ERRORS:
        pass


def get_collection_holdout(self):
    cached = _fbp_cached_collection_ui_state(self)
    if cached is not None:
        return bool(cached.get("holdout", False))
    rigs = _collection_rigs_for_ui(self)
    try:
        # Folder icon is considered active if at least one child layer is currently in temporary holdout.
        return bool(rigs and any(rig_holdout_is_active(rig) for rig in rigs))
    except Exception:
        return False


def set_collection_holdout(self, value):
    for rig in _collection_rigs_for_ui(self):
        try:
            if value:
                fbp_apply_holdout_materials_to_rig(rig)
            else:
                restore_original_materials_from_holdout(rig)
        except FBP_DATA_IO_ERRORS:
            pass
    fbp_clear_collection_ui_state_cache()
