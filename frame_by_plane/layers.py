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
    FBP_ARTIST_COLOR_TAGS, STRIP_COLORS_DICT, preview_collections, fbp_icon,
    fbp_strip_icon, fbp_collection_color_icon, fbp_normalize_artist_color_tag,
    fbp_shared_artist_color_tag,
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
from .ui_icons import layer_custom_icon_value
from .runtime import (
    FBP_DATA_ERRORS,
    FBP_DATA_IO_ERRORS,
    fbp_runtime_set, fbp_warn, fbp_set_rna_property_silent,
    fbp_request_redraw, fbp_undo_guard_active,
    fbp_object_name as _object_name
)
from .service_registry import call_service


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
_COLLECTION_COLOR_TAGS = FBP_ARTIST_COLOR_TAGS - {"NONE"}
_FBP_LAYER_BACKEND_CACHE = globals().get("_FBP_LAYER_BACKEND_CACHE", {})
_FBP_LAYER_BACKEND_CACHE_LIMIT = 2048
_FBP_RESOLVE_RIG_CACHE = globals().get("_FBP_RESOLVE_RIG_CACHE", {})
if not isinstance(_FBP_RESOLVE_RIG_CACHE, dict):
    _FBP_RESOLVE_RIG_CACHE = {}
_FBP_RESOLVE_RIG_CACHE_SECONDS = 0.08
_FBP_RESOLVE_RIG_CACHE_LIMIT = 4096
_FBP_SELECTED_ROOTS_CACHE = globals().get("_FBP_SELECTED_ROOTS_CACHE", {})
if not isinstance(_FBP_SELECTED_ROOTS_CACHE, dict):
    _FBP_SELECTED_ROOTS_CACHE = {}
_FBP_SELECTED_ROOTS_CACHE_SECONDS = 0.08
_FBP_SELECTED_ROOTS_CACHE_LIMIT = 512
_EFFECT_CONTROL_API = None
_GP_CANVAS_API = None
_OBJECT_MASK_API = None
_MOTION_HELPER_API = None


def _object_pointer(obj):
    try:
        return int(obj.as_pointer()) if obj is not None else 0
    except FBP_DATA_ERRORS:
        return 0


def _idprop_string(obj, key):
    try:
        return str(obj.get(key, "") or "") if obj is not None else ""
    except FBP_DATA_ERRORS:
        return ""


def _effect_control_api():
    global _EFFECT_CONTROL_API
    if _EFFECT_CONTROL_API is not None:
        return _EFFECT_CONTROL_API
    try:
        from .effect_controls import effect_control_owner, is_effect_control
        _EFFECT_CONTROL_API = (is_effect_control, effect_control_owner)
        return _EFFECT_CONTROL_API
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None


def _gp_canvas_api():
    global _GP_CANVAS_API
    if _GP_CANVAS_API is not None:
        return _GP_CANVAS_API
    try:
        from .grease_pencil_bridge import gp_canvas_owner, is_gp_canvas
        _GP_CANVAS_API = (is_gp_canvas, gp_canvas_owner)
        return _GP_CANVAS_API
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None


def _object_mask_api():
    global _OBJECT_MASK_API
    if _OBJECT_MASK_API is not None:
        return _OBJECT_MASK_API
    try:
        from .object_masks import find_object_mask_controller_owner, is_object_mask_controller
        _OBJECT_MASK_API = (is_object_mask_controller, find_object_mask_controller_owner)
        return _OBJECT_MASK_API
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None


def _motion_helper_api():
    global _MOTION_HELPER_API
    if _MOTION_HELPER_API is not None:
        return _MOTION_HELPER_API
    try:
        from .motion_runtime import is_motion_helper, motion_helper_owner
        _MOTION_HELPER_API = (is_motion_helper, motion_helper_owner)
        return _MOTION_HELPER_API
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None


def _resolve_cache_key(obj, context=None):
    try:
        parent = getattr(obj, "parent", None)
        grandparent = getattr(parent, "parent", None) if parent is not None else None
        scene = getattr(context, "scene", None) if context is not None else None
        return (
            _object_pointer(scene),
            _object_pointer(obj),
            _object_name(obj),
            str(getattr(obj, "type", "") or ""),
            bool(getattr(obj, "is_fbp_control", False)),
            bool(getattr(obj, "is_fbp_plane", False)),
            _object_pointer(parent),
            _object_name(parent),
            bool(getattr(parent, "is_fbp_control", False)) if parent is not None else False,
            _object_pointer(grandparent),
            _object_name(grandparent),
            bool(getattr(grandparent, "is_fbp_control", False)) if grandparent is not None else False,
            _idprop_string(obj, "fbp_parent_rig_name"),
            _idprop_string(obj, "fbp_lattice_owner"),
            _idprop_string(obj, "fbp_effect_control_owner"),
            bool(obj.get("fbp_gradient_controller", False)) if obj is not None else False,
            _idprop_string(obj, "fbp_gradient_controller_owner"),
            _idprop_string(obj, "fbp_gp_owner_name"),
            _idprop_string(obj, "fbp_object_mask_owner_name"),
            bool(obj.get("fbp_is_object_mask_bounds_handle", False)) if obj is not None else False,
            _idprop_string(obj, "fbp_object_mask_handle_role"),
            _idprop_string(obj, "fbp_motion_helper_target_name"),
            _idprop_string(obj, "fbp_motion_helper_item_uid"),
            bool(obj.get("fbp_motion_helper", False)) if obj is not None else False,
        )
    except FBP_DATA_ERRORS:
        return None


def _resolve_cached_rig(name, pointer=0, context=None):
    if not name and not pointer:
        return None
    name = str(name or "")
    pointer = int(pointer or 0)

    def _valid_rig(rig):
        try:
            return bool(
                rig is not None
                and getattr(rig, "is_fbp_control", False)
                and (not pointer or _object_pointer(rig) == pointer)
            )
        except FBP_DATA_ERRORS:
            return False

    objects = getattr(getattr(context, "scene", None), "objects", None) if context is not None else None
    scene_rig = None
    try:
        scene_rig = objects.get(name) if objects is not None and name else None
        if _valid_rig(scene_rig):
            return scene_rig
    except FBP_DATA_ERRORS:
        scene_rig = None
    try:
        data_rig = bpy.data.objects.get(name) if name else None
        if data_rig is not scene_rig and _valid_rig(data_rig):
            return data_rig
    except FBP_DATA_ERRORS:
        pass
    return None


def _cache_resolved_rig(cache_key, rig):
    if cache_key is None:
        return rig
    if len(_FBP_RESOLVE_RIG_CACHE) >= _FBP_RESOLVE_RIG_CACHE_LIMIT and cache_key not in _FBP_RESOLVE_RIG_CACHE:
        _FBP_RESOLVE_RIG_CACHE.clear()
    _FBP_RESOLVE_RIG_CACHE[cache_key] = (
        time.monotonic(),
        _object_name(rig),
        _object_pointer(rig),
    )
    return rig


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


def _fbp_layer_backend_cache_key(rig):
    try:
        plane = getattr(rig, 'fbp_plane_target', None)
        mesh = getattr(plane, 'data', None) if plane else None
        materials = getattr(mesh, 'materials', ()) if mesh else ()
        material_key = tuple(
            (
                int(material.as_pointer()),
                str(getattr(material, 'name', '') or ''),
                bool(material.get('fbp_drawing_material', False)),
                bool(material.get('fbp_native_sequence', False)),
                bool(material.get('fbp_native_video', False)),
                bool(material.get('fbp_native_static_image', False)),
            )
            for material in tuple(materials or ())
            if material is not None
        )
        return (
            int(rig.as_pointer()),
            str(getattr(rig, 'name', '') or ''),
            bool(getattr(rig, 'is_fbp_control', False)),
            bool(getattr(rig, 'fbp_is_drawing_plane', False)),
            bool(getattr(rig, 'fbp_is_color_plane', False)),
            str(getattr(rig, 'fbp_color_plane_mode', 'SOLID') or 'SOLID'),
            str(rig.get('fbp_backend_type', '') or ''),
            material_key,
        )
    except FBP_DATA_ERRORS:
        return None


def clear_layer_backend_cache():
    _FBP_LAYER_BACKEND_CACHE.clear()
    _FBP_RESOLVE_RIG_CACHE.clear()
    _FBP_SELECTED_ROOTS_CACHE.clear()
    return True


def clear_layer_runtime_caches():
    """Clear hot UI/runtime caches after undo, load or add-on reload."""
    global _EFFECT_CONTROL_API, _GP_CANVAS_API, _OBJECT_MASK_API, _MOTION_HELPER_API
    clear_layer_backend_cache()
    try:
        call_service("layers.invalidate_tree_snapshot")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    _EFFECT_CONTROL_API = None
    _GP_CANVAS_API = None
    _OBJECT_MASK_API = None
    _MOTION_HELPER_API = None
    return True


def _fbp_cache_layer_backend(cache_key, backend):
    if cache_key is None:
        return backend
    if len(_FBP_LAYER_BACKEND_CACHE) >= _FBP_LAYER_BACKEND_CACHE_LIMIT and cache_key not in _FBP_LAYER_BACKEND_CACHE:
        _FBP_LAYER_BACKEND_CACHE.clear()
    _FBP_LAYER_BACKEND_CACHE[cache_key] = backend
    return backend


def fbp_layer_backend_type(rig):
    """Return the effective backend used by one Frame by Plane layer.

    The result is inferred from live flags/materials first and then from the
    explicit 7.1 ``fbp_backend_type`` metadata. Keeping
    this distinction centralized prevents native sequence caches, procedural
    timing caches and Cutout image buffers from being touched by unrelated plane
    types.
    """
    cache_key = _fbp_layer_backend_cache_key(rig)
    cached = _FBP_LAYER_BACKEND_CACHE.get(cache_key) if cache_key is not None else None
    if cached is not None:
        return cached
    if not is_fbp_layer_object(rig):
        return _fbp_cache_layer_backend(cache_key, 'UNKNOWN')
    try:
        if bool(getattr(rig, 'fbp_is_drawing_plane', False)):
            return _fbp_cache_layer_backend(cache_key, 'CUTOUT')
        if bool(getattr(rig, 'fbp_is_color_plane', False)):
            mode = str(getattr(rig, 'fbp_color_plane_mode', 'SOLID') or 'SOLID').upper()
            return _fbp_cache_layer_backend(cache_key, {
                'GRADIENT': 'PROCEDURAL_GRADIENT',
                'HOLDOUT': 'PROCEDURAL_HOLDOUT',
            }.get(mode, 'PROCEDURAL_COLOR'))
    except FBP_DATA_ERRORS:
        return _fbp_cache_layer_backend(cache_key, 'UNKNOWN')

    plane = getattr(rig, 'fbp_plane_target', None)
    mesh = getattr(plane, 'data', None) if plane else None
    try:
        for material in getattr(mesh, 'materials', ()) or ():
            if not material:
                continue
            if bool(material.get('fbp_drawing_material', False)):
                return _fbp_cache_layer_backend(cache_key, 'CUTOUT')
            if bool(material.get('fbp_native_sequence', False)):
                if bool(material.get('fbp_native_video', False)):
                    return _fbp_cache_layer_backend(cache_key, 'NATIVE_MOVIE')
                if bool(material.get('fbp_native_static_image', False)):
                    return _fbp_cache_layer_backend(cache_key, 'NATIVE_IMAGE')
                return _fbp_cache_layer_backend(cache_key, 'NATIVE_SEQUENCE')
    except FBP_DATA_ERRORS:
        pass

    try:
        explicit = str(rig.get('fbp_backend_type', '') or '').upper()
    except FBP_DATA_ERRORS:
        explicit = ''
    return _fbp_cache_layer_backend(cache_key, explicit or 'UNKNOWN')


_FBP_SAMPLEABLE_IMAGE_BACKENDS = frozenset({
    'NATIVE_IMAGE', 'NATIVE_SEQUENCE', 'NATIVE_MOVIE', 'CUTOUT',
})
_FBP_LAYER_BLEND_SOURCE_BACKENDS = frozenset({
    *_FBP_SAMPLEABLE_IMAGE_BACKENDS,
    'PROCEDURAL_COLOR',
})


def fbp_layer_has_sampleable_image(rig):
    """Return whether relation effects can sample this layer's image texture."""
    try:
        return fbp_layer_backend_type(rig) in _FBP_SAMPLEABLE_IMAGE_BACKENDS
    except FBP_DATA_ERRORS:
        return False


def fbp_layer_is_blend_source(rig):
    """Return whether Layer Blend can read this layer without rasterizing it.

    Image-backed layers are sampled through their Image Texture. Flat Color
    Plane frames are transferred as an RGBA value by the Layer Blend v2 group.
    Gradient and Holdout planes remain excluded because a single color cannot
    represent their spatial shader result faithfully.
    """
    try:
        backend = fbp_layer_backend_type(rig)
        if backend not in _FBP_LAYER_BLEND_SOURCE_BACKENDS:
            return False
        if backend != 'PROCEDURAL_COLOR':
            return True
        plane = getattr(rig, "fbp_plane_target", None)
        mesh = getattr(plane, "data", None) if plane else None
        materials = getattr(mesh, "materials", None) if mesh else None
        if not materials or len(materials) == 0:
            return False
        if len(getattr(rig, "fbp_images", ()) or ()):
            # A mixed procedural sequence is valid only while its current frame
            # is a flat color/transparent row. The synchronizer refreshes this
            # decision when the timeline changes.
            try:
                from .core import fbp_sequence_index_at_frame
                scene = next(iter(tuple(getattr(rig, "users_scene", ()) or ())), None)
                index = fbp_sequence_index_at_frame(
                    rig, getattr(scene, "frame_current", 1) if scene else 1
                )
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                index = int(getattr(rig, "fbp_images_index", 0) or 0)
            if index < 0:
                return True
            index = max(0, min(int(index), len(materials) - 1))
            return fbp_procedural_kind_for_item(rig, index, 'SOLID') == 'SOLID'
        return fbp_procedural_kind_from_material(
            materials[0], getattr(rig, "fbp_color_plane_mode", "SOLID")
        ) == 'SOLID'
    except FBP_DATA_ERRORS:
        return False


def fbp_layer_clipping_active_hint(rig):
    """Return the authoritative persistent Clipping Mask enabled state.

    Import metadata and a stale source pointer must never keep a disabled layer
    inside a clipping chain. Effect repair restores this flag for genuinely
    active generated nodes during normal stack synchronization.
    """
    try:
        try:
            from .grease_pencil_bridge import is_gp_drawing_canvas
            if is_gp_drawing_canvas(rig):
                # Native Grease Pencil does not participate in the same shader
                # alpha contract as Frame By Plane mesh planes. Treat GP/Plane
                # clipping as unavailable until the dedicated proxy/raster
                # pipeline is implemented, instead of exposing a broken chain.
                return False
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        if not rig or not is_fbp_layer_object(rig):
            return False
        return bool(rig.get("fbp_effect_clipping_mask", False))
    except FBP_DATA_ERRORS:
        return False


def fbp_layer_backend_label(rig):
    return {
        'NATIVE_IMAGE': 'Single Plane',
        'NATIVE_SEQUENCE': 'Sequence',
        'NATIVE_MOVIE': 'Video Plane',
        'CUTOUT': 'Cutout Plane',
        'PROCEDURAL_COLOR': 'Color Plane',
        'PROCEDURAL_GRADIENT': 'Gradient Plane',
        'PROCEDURAL_HOLDOUT': 'Holdout Plane',
    }.get(fbp_layer_backend_type(rig), 'Frame By Plane Layer')


def safe_collection_color_tag(collection, fallback='NONE'):
    try:
        tag = getattr(collection, 'color_tag', 'NONE')
        return tag if tag in _COLLECTION_COLOR_TAGS else fallback
    except FBP_DATA_ERRORS:
        return fallback


def set_collection_color_tag(collection, color_tag):
    """Assign a valid Blender Collection color tag.

    Collection tags support NONE and COLOR_01..COLOR_07. Brown/Grey are not exposed as artist-facing Frame By Plane color tags.
    """
    if not collection:
        return
    tag = str(color_tag or 'NONE')
    if tag in {'COLOR_08', 'COLOR_09'}:
        tag = 'NONE'
    if tag != 'NONE' and tag not in _COLLECTION_COLOR_TAGS:
        return
    try:
        collection.color_tag = tag
    except FBP_DATA_IO_ERRORS:
        pass


def make_color_variant(color_tag, index=0):
    """Return a clearly readable depth variant while preserving the tag hue."""
    if str(color_tag or '').upper() == 'NONE':
        return (1.0, 1.0, 1.0, 1.0)
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


def fbp_active_work_collection(context):
    """Return the collection an artist is currently working in.

    Preference order:
    1. The active Layer List group or selected row collection.
    2. The selected/active Frame By Plane object's primary collection.
    3. Blender's active context collection.
    4. The scene master collection.

    This keeps procedural Color/Gradient/Holdout planes in the same collection
    the user is editing instead of sending them to a global Color Planes folder.
    """
    scene = getattr(context, "scene", None) if context is not None else None
    if scene is None:
        return None

    def _collection_from_name(name):
        name = str(name or "")
        return bpy.data.collections.get(name) if name else None

    try:
        rows = getattr(scene, "fbp_layer_tree_rows", ())
        index = int(getattr(scene, "fbp_layer_tree_rows_idx", -1))
        if 0 <= index < len(rows):
            row = rows[index]
            row_type = str(getattr(row, "row_type", "") or "")
            if row_type == "GROUP":
                collection = _collection_from_name(getattr(row, "collection_name", ""))
                if collection is not None:
                    return collection
            if row_type in {"LAYER", "GP_CANVAS"}:
                obj_name = (
                    str(getattr(row, "rig_name", "") or "")
                    or str(getattr(row, "canvas_name", "") or "")
                    or str(getattr(row, "name", "") or "")
                )
                obj = bpy.data.objects.get(obj_name)
                collection = get_primary_fbp_collection(obj) if obj is not None else None
                if collection is not None:
                    return collection
    except FBP_DATA_ERRORS:
        pass

    try:
        active = getattr(getattr(context, "view_layer", None), "objects", None)
        active_obj = getattr(active, "active", None) if active is not None else None
        collection = get_primary_fbp_collection(active_obj) if active_obj is not None else None
        if collection is not None:
            return collection
    except FBP_DATA_ERRORS:
        pass

    try:
        for obj in tuple(getattr(context, "selected_objects", ()) or ()):  # viewport selection fallback
            collection = get_primary_fbp_collection(obj)
            if collection is not None:
                return collection
    except FBP_DATA_ERRORS:
        pass

    try:
        collection = getattr(context, "collection", None)
        if collection is not None:
            return collection
    except FBP_DATA_ERRORS:
        pass

    return getattr(scene, "collection", None)


def get_primary_fbp_collection(obj):
    """Resolve one canonical collection from the object's live links.

    ``fbp_collection_name`` is only a hint: manual Outliner moves can leave it
    pointing to a collection that no longer owns the layer.
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
        except FBP_DATA_ERRORS:
            return object_in_scene(rig, context.scene)
    except FBP_DATA_ERRORS:
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
    """Resolve the active layer from the virtual tree or its synchronized index."""
    if scene is None:
        return -1
    try:
        fallback_index = int(getattr(scene, "fbp_layer_stack_index", -1))
    except FBP_DATA_ERRORS:
        fallback_index = -1
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
        if 0 <= fallback_index < len(layers):
            return fallback_index
    except FBP_DATA_ERRORS:
        pass
    return -1


def apply_collection_color_to_layer(obj, color_tag=None, variant_index=None, push_collection=False):
    if not obj or not is_fbp_layer_object(obj):
        return
    coll = get_primary_fbp_collection(obj)
    if color_tag is None and coll:
        color_tag = safe_collection_color_tag(coll, getattr(obj, 'fbp_color_tag', 'NONE'))
    color_tag = str(color_tag or 'NONE')
    if color_tag != 'NONE' and color_tag not in STRIP_COLORS_DICT:
        color_tag = getattr(obj, 'fbp_color_tag', 'NONE')
        if color_tag != 'NONE' and color_tag not in STRIP_COLORS_DICT:
            color_tag = 'NONE'
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


def fbp_build_canonical_collection_tree(scene):
    """Return one deterministic single-parent view of the Scene collection graph.

    Blender permits the same Collection datablock to be linked below multiple
    parents.  The Layer List can only display one hierarchy path, so every
    collection-row operation must use the same canonical breadth-first tree as
    the UI builder.  The shallowest scene path wins; sibling order breaks ties.

    The returned dictionaries are local snapshots and never retain RNA objects
    beyond the current operation/draw.
    """
    root = getattr(scene, "collection", None) if scene is not None else None
    if root is None:
        return {
            "root": None,
            "root_key": None,
            "collections": {},
            "children": {},
            "parent_by_key": {},
        }

    def key(collection):
        if collection is None:
            return None
        try:
            return int(collection.as_pointer())
        except FBP_DATA_ERRORS:
            return id(collection)

    root_key = key(root)
    collections = {root_key: root}
    children = {}
    parent_by_key = {root_key: None}
    queue = [root]
    index = 0
    while index < len(queue):
        parent = queue[index]
        index += 1
        parent_key = key(parent)
        canonical_children = []
        try:
            raw_children = tuple(getattr(parent, "children", ()) or ())
        except FBP_DATA_ERRORS:
            raw_children = ()
        for child in raw_children:
            child_key = key(child)
            if child_key is None or child_key == root_key:
                continue
            # The first breadth-first occurrence is the canonical path.
            if child_key in parent_by_key:
                continue
            parent_by_key[child_key] = parent_key
            collections[child_key] = child
            canonical_children.append(child)
            queue.append(child)
        children[parent_key] = tuple(canonical_children)

    return {
        "root": root,
        "root_key": root_key,
        "collections": collections,
        "children": children,
        "parent_by_key": parent_by_key,
    }


def fbp_canonical_collection_descendants(scene, collection, *, include_self=True):
    """Return the collection's descendants from the canonical Layer List tree."""
    if collection is None:
        return []
    tree = fbp_build_canonical_collection_tree(scene)
    collections = tree.get("collections", {}) or {}
    child_map = tree.get("children", {}) or {}
    try:
        start_key = int(collection.as_pointer())
    except FBP_DATA_ERRORS:
        start_key = id(collection)
    if start_key not in collections:
        # Datablocks outside the Scene tree can still be queried during undo or
        # deletion.  Keep a safe raw fallback instead of returning stale state.
        result = []
        seen = set()
        stack = [collection]
        while stack:
            current = stack.pop()
            if current is None:
                continue
            try:
                current_key = int(current.as_pointer())
            except FBP_DATA_ERRORS:
                current_key = id(current)
            if current_key in seen:
                continue
            seen.add(current_key)
            result.append(current)
            try:
                stack.extend(reversed(tuple(getattr(current, "children", ()) or ())))
            except FBP_DATA_ERRORS:
                pass
        return result if include_self else result[1:]

    result = []
    seen = set()
    stack = [start_key]
    while stack:
        current_key = stack.pop()
        if current_key in seen:
            continue
        seen.add(current_key)
        current = collections.get(current_key)
        if current is not None:
            result.append(current)
        child_keys = []
        for child in child_map.get(current_key, ()):
            try:
                child_keys.append(int(child.as_pointer()))
            except FBP_DATA_ERRORS:
                child_keys.append(id(child))
        stack.extend(reversed(child_keys))
    return result if include_self else result[1:]


def fbp_reset_layer_view_cache_state():
    """Forget Python-side collection cache ownership before loading a new Main."""
    global _FBP_LAYER_VIEW_CACHE_INITIALIZED
    _FBP_LAYER_VIEW_TAGGED_COLLECTIONS.clear()
    _FBP_LAYER_VIEW_DIRECT_COLLECTIONS.clear()
    _FBP_LAYER_VIEW_RECURSIVE_COLLECTIONS.clear()
    _FBP_LAYER_VIEW_CACHE_INITIALIZED = False
    call_service("layers.invalidate_tree_snapshot", None, default=None)


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
    """Pre-compute canonical collection membership for Layer List consumers.

    The cache follows the same single-parent tree shown by the UIList and
    includes both mesh planes and GP Drawing Planes.  This avoids duplicate views
    and project diagnostics reporting content below a second, non-displayed
    parent when a Blender Collection is linked more than once.
    """
    if not context or not getattr(context, "scene", None):
        return
    global _FBP_LAYER_VIEW_CACHE_INITIALIZED
    scene = context.scene

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
        for datablock_scene in getattr(bpy.data, "scenes", ()):
            _clear_layer_view_collection_flags(getattr(datablock_scene, "collection", None))
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not reset layer view cache", exc)
        return

    _FBP_LAYER_VIEW_TAGGED_COLLECTIONS.clear()
    _FBP_LAYER_VIEW_DIRECT_COLLECTIONS.clear()
    _FBP_LAYER_VIEW_RECURSIVE_COLLECTIONS.clear()
    _FBP_LAYER_VIEW_CACHE_INITIALIZED = True

    tree = fbp_build_canonical_collection_tree(scene)
    collections = tree.get("collections", {}) or {}
    parent_by_key = tree.get("parent_by_key", {}) or {}

    def collection_key(collection):
        try:
            return int(collection.as_pointer())
        except FBP_DATA_ERRORS:
            return id(collection)

    def mark_collection(collection):
        current = collection
        seen = set()
        while current is not None:
            key = collection_key(current)
            if key in seen:
                break
            seen.add(key)
            try:
                current["fbp_has_fbp_content_recursive"] = True
                name = str(getattr(current, "name", "") or "")
                if name:
                    _FBP_LAYER_VIEW_TAGGED_COLLECTIONS.add(name)
                    _FBP_LAYER_VIEW_RECURSIVE_COLLECTIONS.add(name)
            except FBP_DATA_IO_ERRORS:
                pass
            parent_key = parent_by_key.get(key)
            if parent_key is None or parent_key == key:
                break
            current = collections.get(parent_key)

    direct_collections = {}
    for item in getattr(scene, "fbp_layers", ()) or ():
        try:
            rig = item.obj
            if not rig or not is_fbp_layer_object(rig) or not object_in_scene(rig, scene):
                continue
            collection = get_primary_fbp_collection(rig)
            if collection is not None:
                direct_collections[collection_key(collection)] = collection
        except FBP_DATA_ERRORS:
            continue
        except Exception as exc:
            fbp_warn("Could not resolve layer collection for UI cache", exc)

    try:
        from .fbp_index import iter_scene_gp_canvases
        from .grease_pencil_bridge import is_gp_drawing_canvas
        for canvas in iter_scene_gp_canvases(scene, kind="DRAWING", fallback=True):
            if canvas is None or not is_gp_drawing_canvas(canvas):
                continue
            collection = get_primary_fbp_collection(canvas)
            if collection is not None:
                direct_collections[collection_key(collection)] = collection
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    for collection in direct_collections.values():
        try:
            collection["fbp_has_fbp_content"] = True
            name = str(getattr(collection, "name", "") or "")
            if name:
                _FBP_LAYER_VIEW_TAGGED_COLLECTIONS.add(name)
                _FBP_LAYER_VIEW_DIRECT_COLLECTIONS.add(name)
            mark_collection(collection)
        except FBP_DATA_IO_ERRORS as exc:
            fbp_warn("Could not cache layer collection", exc)

    fbp_runtime_set("fbp_layer_cache_dirty", False, context)

def fbp_mark_layer_cache_dirty(context=None):
    fbp_runtime_set("fbp_layer_cache_dirty", True, context)
    try:
        call_service("layers.invalidate_tree_snapshot", context)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


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
    object linked into multiple Blender collections cannot acquire an
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
        from .grease_pencil_bridge import is_gp_drawing_canvas
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        is_gp_drawing_canvas = lambda _obj: False

    def is_clipping_stack_candidate(obj):
        """Only FBP mesh layers participate in shader clipping chains.

        Drawing Planes are visible Layer List items, but their native Grease
        Pencil draw pipeline is not the same image/material pipeline used by
        FBP plane clipping. A GP row between two planes must therefore be
        ignored, not treated as a broken source that cancels plane-to-plane
        clipping.
        """
        return bool(obj and is_fbp_layer_object(obj) and not is_gp_drawing_canvas(obj))

    target_items = []
    target_keys = set()
    target_collections = []
    target_collection_keys = set()
    if rigs is not None:
        try:
            for obj in tuple(rigs):
                if obj is None or not object_in_scene(obj, scene):
                    continue
                if not is_clipping_stack_candidate(obj):
                    continue
                key = int(obj.as_pointer())
                if key in target_keys:
                    continue
                target_keys.add(key)
                target_items.append(obj)
                collection = get_primary_fbp_collection(obj)
                if collection is None:
                    continue
                collection_key = int(collection.as_pointer())
                if collection_key in target_collection_keys:
                    continue
                target_collection_keys.add(collection_key)
                target_collections.append(collection)
        except (ReferenceError, RuntimeError, TypeError, ValueError):
            return result

    try:
        if collection_scope is not None:
            scan_collections = tuple(collection_scope)
        elif target_collections:
            scan_collections = tuple(target_collections)
        else:
            scan_collections = ()
    except FBP_DATA_ERRORS:
        scan_collections = ()

    try:
        if scan_collections:
            scene_items = []
            seen_items = set()
            scan_keys = set()
            for collection in scan_collections:
                try:
                    if collection is not None:
                        scan_keys.add(int(collection.as_pointer()))
                except FBP_DATA_ERRORS:
                    continue
            for obj in iter_scene_fbp_rigs(scene, fallback=True):
                try:
                    if not is_clipping_stack_candidate(obj):
                        continue
                    collection = get_primary_fbp_collection(obj)
                    if collection is None or int(collection.as_pointer()) not in scan_keys:
                        continue
                    key = int(obj.as_pointer())
                    if key in seen_items:
                        continue
                    seen_items.add(key)
                    scene_items.append(obj)
                except FBP_DATA_ERRORS:
                    continue
        else:
            scene_items = []
            seen_items = set()
            for obj in iter_scene_fbp_rigs(scene, fallback=True):
                try:
                    if not is_clipping_stack_candidate(obj):
                        continue
                    key = int(obj.as_pointer())
                    if key in seen_items:
                        continue
                    seen_items.add(key)
                    scene_items.append(obj)
                except FBP_DATA_ERRORS:
                    continue
    except (ReferenceError, RuntimeError, TypeError, ValueError):
        return result
    if not scene_items:
        return result

    by_collection = {}
    seen_item_keys = set()
    try:
        for rig in scene_items:
            if (
                not rig
                or not is_clipping_stack_candidate(rig)
                or not object_in_scene(rig, scene)
            ):
                continue
            rig_key = int(rig.as_pointer())
            if rig_key in seen_item_keys:
                continue
            seen_item_keys.add(rig_key)
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
            for index, rig in enumerate(scene_items)
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
            source = None
            # Stacked clipping layers share the first non-clipping, sampleable
            # FBP mesh layer below them. Non-sampleable rows and GP Drawing
            # Planes are skipped so a visible GP layer between two image planes
            # does not break plane-to-plane clipping.
            for candidate_index in range(index + 1, len(displayed)):
                if clipping_flags[index] and clipping_flags[candidate_index]:
                    continue
                candidate = displayed[candidate_index]
                if fbp_layer_has_sampleable_image(candidate):
                    source = candidate
                    break
            if target_keys and int(rig.as_pointer()) not in target_keys:
                continue
            result[rig] = source
    return result


def fbp_immediate_layer_below_map(context, rigs=None, *, collections=None):
    """Return the immediate Image or flat Color layer below each rig.

    A spatial procedural Gradient/Holdout layer still breaks the relation: it
    cannot be represented by the Layer Blend group's constant RGBA source.
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
            result[rig] = source if fbp_layer_is_blend_source(source) else None
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
    except FBP_DATA_ERRORS:
        return


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
    """Store one canonical procedural kind and clear conflicting material flags."""
    if not mat:
        return
    kind = kind if kind in {'SOLID', 'GRADIENT', 'HOLDOUT'} else 'SOLID'
    try:
        mat['fbp_procedural_kind'] = kind
        if kind == 'GRADIENT':
            mat['fbp_gradient_material'] = True
            try:
                if 'fbp_holdout_material' in mat:
                    del mat['fbp_holdout_material']
            except FBP_DATA_IO_ERRORS:
                pass
        elif kind == 'HOLDOUT':
            mat['fbp_holdout_material'] = True
            try:
                if 'fbp_gradient_material' in mat:
                    del mat['fbp_gradient_material']
            except FBP_DATA_IO_ERRORS:
                pass
        else:
            for key in ('fbp_gradient_material', 'fbp_holdout_material'):
                try:
                    if key in mat:
                        del mat[key]
                except FBP_DATA_IO_ERRORS:
                    pass
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


def _fbp_normalize_layer_color_tag(color_tag):
    """Return one artist-facing layer tag, normalizing internal values."""
    return fbp_normalize_artist_color_tag(color_tag)


def fbp_collection_effective_color_tag(collection, context=None):
    """Return the shared color of all FBP plane layers in a collection tree.

    Collection datablock colors are not authoritative for the Layer List: they
    can be inherited from imports or manually changed in the Outliner. A
    collection row is colored only when every
    descendant Frame By Plane plane has the same artist-facing tag. Empty or
    mixed collections stay white/default.
    """
    if collection is None:
        return 'NONE'
    try:
        if bool(getattr(collection, 'fbp_color_tag_explicit', False)):
            return _fbp_normalize_layer_color_tag(
                safe_collection_color_tag(collection, 'NONE')
            )
    except FBP_DATA_ERRORS:
        pass
    try:
        rigs, gp_canvases = _collection_ui_members(collection)
        tags = (
            _fbp_normalize_layer_color_tag(getattr(member, 'fbp_color_tag', 'NONE'))
            for member in tuple(rigs) + tuple(gp_canvases)
            if member is not None
        )
    except FBP_DATA_ERRORS:
        return 'NONE'
    return fbp_shared_artist_color_tag(tags)


def fbp_collection_icon(collection, context=None):
    """Return a collection icon derived from the colors of its plane layers."""
    return fbp_collection_color_icon(
        fbp_collection_effective_color_tag(collection, context=context)
    )


def fbp_layer_tag_backend_icon_value(rig, inactive=None):
    """Return the bundled PNG icon for a layer backend and color tag.

    Layer-list icons are never generated at runtime.  This keeps the artwork
    consistent with the rest of Frame By Plane, avoids allocating preview image
    buffers during UI redraw, and respects the user's custom icon assets.
    """
    if not rig:
        return 0
    try:
        color_tag = str(getattr(rig, 'fbp_color_tag', 'NONE') or 'NONE')
        inactive_state = (
            not bool(getattr(rig, 'fbp_is_visible', True))
            if inactive is None else bool(inactive)
        )
        return int(layer_custom_icon_value(
            fbp_layer_backend_type(rig),
            color_tag,
            inactive=inactive_state,
        ) or 0)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return 0

def fbp_layer_row_type_icon(rig, context):
    """Return a thumbnail when enabled, otherwise the rig Color Tag icon."""
    if bool(getattr(context.scene, 'fbp_show_previews', False)) and not bool(getattr(rig, 'fbp_is_color_plane', False)):
        preview = get_layer_thumbnail(rig, scene=getattr(context, "scene", None))
        if preview:
            return None, preview.icon_id
    try:

        if str(getattr(rig, 'fbp_color_tag', 'NONE') or '').upper() == 'NONE':
            value = layer_custom_icon_value(fbp_layer_backend_type(rig), 'NONE')
            if value:
                return None, value
        return fbp_strip_icon(getattr(rig, 'fbp_color_tag', 'NONE')), None
    except FBP_DATA_ERRORS:
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


def collect_project_image_paths():
    """Return FBP media paths, expanding Blender 5.2 image sequences when possible."""
    images = []
    image_pointers = set()
    for _mat, _node, image in iter_material_image_nodes():
        try:
            pointer = int(image.as_pointer())
        except FBP_DATA_ERRORS:
            pointer = id(image)
        if pointer in image_pointers:
            continue
        image_pointers.add(pointer)
        images.append(image)

    paths = []
    path_foreach = getattr(getattr(bpy, 'data', None), 'file_path_foreach', None)
    if callable(path_foreach) and images:
        def _visit(id_block, path, meta):
            try:
                pointer = int(id_block.as_pointer())
            except FBP_DATA_ERRORS:
                return
            if pointer not in image_pointers or bool(getattr(meta, 'is_cache', False)):
                return
            value = str(path or '')
            if value:
                paths.append(value)
        flags = {
            'SKIP_PACKED',
            'SKIP_WEAK_REFERENCES',
            'EXPAND_SEQUENCES',
        }
        try:
            # Blender 5.2 can scope traversal to the Image datablocks actually
            # used by FBP. This avoids visiting every library/cache path in large
            # productions and, in particular, avoids expanding Cycles .tx files
            # that are deliberately ignored by this media-only collector.
            path_foreach(_visit, subset=images, flags=flags)
        except TypeError:
            # Defensive fallback for API builds that expose file_path_foreach
            # without the scoped subset keyword.
            try:
                path_foreach(_visit, flags=flags)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                paths.clear()
        except (AttributeError, ReferenceError, RuntimeError, ValueError):
            paths.clear()

    if not paths:
        for image in images:
            path = str(getattr(image, 'filepath', '') or '')
            if path:
                paths.append(path)

    # FBP rows retain the intended complete sequence, including frames that are
    # currently missing on disk and therefore cannot be returned by Blender's
    # expanded-path traversal.
    try:
        for scene in bpy.data.scenes:
            for rig in iter_scene_fbp_rigs(scene, fallback=True):
                for item in tuple(getattr(rig, 'fbp_images', ()) or ()):
                    path = str(getattr(item, 'filepath', '') or '')
                    if path:
                        paths.append(path)
    except FBP_DATA_ERRORS:
        pass
    return list(dict.fromkeys(paths))


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
        if not mat or not getattr(mat, 'node_tree', None):
            continue
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and getattr(node, 'image', None):
                p = getattr(node.image, 'filepath', '')
                if p and not os.path.exists(bpy.path.abspath(p)):
                    return True
    return False


_FBP_LAYER_DEPTH_EPSILON = 0.01


def _fbp_depth_nudge_amount(depth_a=0.0, depth_b=0.0):
    """Return a visible-but-small camera-depth nudge for equal-depth layers."""
    try:
        scale = max(abs(float(depth_a)), abs(float(depth_b)), 1.0)
    except (TypeError, ValueError):
        scale = 1.0
    return max(_FBP_LAYER_DEPTH_EPSILON, scale * 1.0e-5)
def move_layer_to_depth_preserve_projection(context, obj, target_depth, *, depth_context=None):
    """Move one stack object without moving neighbours and preserve screen size.

    Perspective cameras require the object's scale to change by the same ratio
    as its camera depth. Orthographic cameras and no-camera scenes keep scale
    unchanged. The complete world matrix is written once so parented rigs do not
    accumulate translation/scale drift across repeated Layer List moves.
    """
    if obj is None:
        return False
    depth_context = depth_context or fbp_make_depth_context_cache(context)
    try:
        world = obj.matrix_world.copy()
        if depth_context.get("has_camera"):
            camera_location = depth_context["camera_location"]
            forward = depth_context["camera_forward"].normalized()
            current_depth = float((world.translation - camera_location).dot(forward))
            target_depth = float(target_depth)
            if target_depth <= 1.0e-6:
                return False
            location, rotation, scale = world.decompose()
            location += forward * (target_depth - current_depth)
            if (
                str(depth_context.get("camera_type", "PERSP") or "PERSP") == "PERSP"
                and current_depth > 1.0e-6
            ):
                ratio = target_depth / current_depth
                if ratio > 1.0e-6:
                    scale = scale * ratio
            obj.matrix_world = mathutils.Matrix.LocRotScale(location, rotation, scale)
            return True

        axis = 1 if getattr(obj, 'fbp_is_vertical', False) else 2
        world.translation[axis] = float(target_depth)
        obj.matrix_world = world
        return True
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not move layer while preserving camera projection", exc)
        return False


def swap_layer_depth_only(context, rig_a, rig_b, *, depth_context=None, direction=""):
    """Swap or nudge two stack items using the same depth metric as the Layer List.

    ``Move Up/Down`` used to be a no-op for layers sharing exactly the same
    distance from the camera: both objects swapped identical depth values, then
    the UI fell back to name ordering and appeared to ignore the command.  When a
    direction is supplied and the neighbour has the same projected distance, move
    only the active object by a tiny camera-depth step past the neighbour.
    """
    if not rig_a or not rig_b:
        return
    direction = str(direction or "").upper()
    try:
        depth_context = depth_context or fbp_make_depth_context_cache(context)
        if depth_context.get("has_camera"):
            camera_location = depth_context["camera_location"]
            forward = depth_context["camera_forward"].normalized()
            world_a = rig_a.matrix_world.copy()
            world_b = rig_b.matrix_world.copy()
            depth_a = float((world_a.translation - camera_location).dot(forward))
            depth_b = float((world_b.translation - camera_location).dot(forward))
            epsilon = _fbp_depth_nudge_amount(depth_a, depth_b)
            if direction in {"UP", "DOWN"} and abs(depth_a - depth_b) <= epsilon * 0.25:
                target_depth = depth_b - epsilon if direction == "UP" else depth_b + epsilon
                move_layer_to_depth_preserve_projection(
                    context,
                    rig_a,
                    target_depth,
                    depth_context=depth_context,
                )
                return
            # Reverse both projected depths through the same perspective-aware
            # path used by ordinary Up/Down moves. The rear/larger plane thus
            # becomes the nearer/smaller plane (and vice versa) while keeping
            # its apparent camera framing. Orthographic cameras intentionally
            # change only position.
            move_layer_to_depth_preserve_projection(
                context,
                rig_a,
                depth_b,
                depth_context=depth_context,
            )
            move_layer_to_depth_preserve_projection(
                context,
                rig_b,
                depth_a,
                depth_context=depth_context,
            )
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
        epsilon = _fbp_depth_nudge_amount(depth_a, depth_b)
        if direction in {"UP", "DOWN"} and abs(depth_a - depth_b) <= epsilon * 0.25:
            world_a.translation[axis] = depth_b - epsilon if direction == "UP" else depth_b + epsilon
            rig_a.matrix_world = world_a
            return
        world_a.translation[axis] = depth_b
        world_b.translation[axis] = depth_a
        rig_a.matrix_world = world_a
        rig_b.matrix_world = world_b
    except FBP_DATA_ERRORS:
        # Conservative fallback for incomplete objects during file load.
        loc_a = rig_a.location.copy()
        loc_b = rig_b.location.copy()
        if direction in {"UP", "DOWN"}:
            epsilon = _fbp_depth_nudge_amount(loc_a[axis], loc_b[axis])
            loc_a[axis] = loc_b[axis] - epsilon if direction == "UP" else loc_b[axis] + epsilon
        else:
            loc_a[axis], loc_b[axis] = loc_b[axis], loc_a[axis]
            rig_b.location = loc_b
        rig_a.location = loc_a


def iter_scene_fbp_rigs(scene, *, fallback=False):
    """Yield synchronized FBP rigs without rescanning the Scene on hot paths."""
    if not scene:
        return
    try:
        from .fbp_index import iter_scene_fbp_rigs as _indexed_scene_rigs
        yield from _indexed_scene_rigs(scene, fallback=fallback)
        return
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

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

    if fallback and not yielded:
        try:
            for rig in tuple(getattr(scene, "objects", ()) or ()):  # scene-local repair path
                if not is_fbp_layer_object(rig) or not object_in_scene(rig, scene):
                    continue
                try:
                    key = int(rig.as_pointer())
                except FBP_DATA_ERRORS:
                    key = str(getattr(rig, "name", "") or "")
                if key in seen:
                    continue
                seen.add(key)
                yield rig
        except FBP_DATA_ERRORS:
            pass
    return


def iter_scene_fbp_planes(scene, *, fallback=False):
    """Yield synchronized FBP layer planes without rescanning on hot paths."""
    if not scene:
        return
    try:
        from .fbp_index import iter_scene_fbp_planes as _indexed_scene_planes
        yield from _indexed_scene_planes(scene, fallback=fallback)
        return
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    seen = set()
    try:
        for rig in iter_scene_fbp_rigs(scene, fallback=fallback):
            plane = getattr(rig, "fbp_plane_target", None)
            if not plane or not getattr(plane, "is_fbp_plane", False):
                continue
            if not object_in_scene(plane, scene):
                continue
            try:
                key = int(plane.as_pointer())
            except FBP_DATA_ERRORS:
                key = str(getattr(plane, "name", "") or "")
            if key in seen:
                continue
            seen.add(key)
            yield plane
    except FBP_DATA_ERRORS:
        return
    if fallback:
        try:
            for plane in tuple(getattr(scene, "objects", ()) or ()):  # scene-local repair path
                if not plane or not getattr(plane, "is_fbp_plane", False) or not object_in_scene(plane, scene):
                    continue
                try:
                    key = int(plane.as_pointer())
                except FBP_DATA_ERRORS:
                    key = str(getattr(plane, "name", "") or "")
                if key in seen:
                    continue
                seen.add(key)
                yield plane
        except FBP_DATA_ERRORS:
            return

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
    except FBP_DATA_ERRORS:
        return False


def get_selected_rigs(context):
    return get_selected_fbp_roots(context)


def get_selected_or_active_rigs(context):
    """Return selected rigs, falling back to the active object's owner."""
    rigs = list(get_selected_rigs(context) or ())
    if rigs:
        return rigs
    active = getattr(context, "object", None) if context is not None else None
    rig = fbp_resolve_rig_from_any_object(active, context) if active is not None else None
    return [rig] if rig is not None else []


def fbp_resolve_rig_from_any_object(obj, context=None):
    """Return the current FBP rig represented by a rig, helper, GP canvas or plane.

    Selection polling and Properties panels can call this repeatedly within the
    same redraw. Cache the answer for a tiny UI tick using an ownership
    signature that changes when parent/object tags change.
    """
    if obj is None:
        return None
    cache_key = _resolve_cache_key(obj, context)
    if cache_key is not None:
        cached = _FBP_RESOLVE_RIG_CACHE.get(cache_key)
        if cached is not None:
            try:
                checked_at, name, pointer = cached
                if time.monotonic() - float(checked_at or 0.0) <= _FBP_RESOLVE_RIG_CACHE_SECONDS:
                    rig = _resolve_cached_rig(name, pointer, context)
                    if rig is not None or not name:
                        return rig
            except (TypeError, ValueError):
                pass
    rig = _fbp_resolve_rig_from_any_object_uncached(obj, context)
    return _cache_resolved_rig(cache_key, rig)


def _fbp_resolve_rig_from_any_object_uncached(obj, context=None):
    """Return the current FBP rig represented by a rig or its linked plane."""
    if obj is None:
        return None
    try:
        if getattr(obj, "is_fbp_control", False):
            return obj
        if bool(obj.get("fbp_gradient_controller", False)):
            plane = getattr(obj, "parent", None)
            owner = getattr(plane, "parent", None) if plane else None
            if owner and getattr(owner, "is_fbp_control", False):
                return owner
            owner_name = str(obj.get("fbp_gradient_controller_owner", "") or "")
            owner = bpy.data.objects.get(owner_name) if owner_name else None
            if owner and getattr(owner, "is_fbp_control", False):
                return owner
        api = _effect_control_api()
        if api is not None:
            try:
                is_effect_control, effect_control_owner = api
                if is_effect_control(obj):
                    owner = effect_control_owner(obj)
                    if owner and getattr(owner, "is_fbp_control", False):
                        return owner
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        api = _motion_helper_api()
        if api is not None:
            try:
                is_motion_helper, motion_helper_owner = api
                if is_motion_helper(obj):
                    owner = motion_helper_owner(obj)
                    if owner is not None:
                        # Motion can target an FBP layer rig or a camera/regular object.
                        # For FBP layers, route the Properties UI back to the owning rig
                        # so selecting the helper behaves exactly like selecting the plane.
                        if getattr(owner, "is_fbp_control", False):
                            return owner
                        plane_parent = getattr(owner, "parent", None)
                        if getattr(owner, "is_fbp_plane", False) and plane_parent and getattr(plane_parent, "is_fbp_control", False):
                            return plane_parent
                        return owner
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
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
        api = _gp_canvas_api()
        if api is not None:
            try:
                is_gp_canvas, gp_canvas_owner = api
                if is_gp_canvas(obj):
                    owner = gp_canvas_owner(obj)
                    if owner and getattr(owner, "is_fbp_control", False):
                        return owner
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        api = _object_mask_api()
        if api is not None:
            try:
                is_object_mask_controller, find_object_mask_controller_owner = api
                if is_object_mask_controller(obj):
                    plane = getattr(obj, "parent", None)
                    parent_rig = getattr(plane, "parent", None) if plane else None
                    if parent_rig and getattr(parent_rig, "is_fbp_control", False):
                        return parent_rig
                    # Repair-tolerant fallback for helpers whose parenting was
                    # changed manually or temporarily lost during Undo/file load.
                    owner = find_object_mask_controller_owner(obj)
                    if owner and getattr(owner, "is_fbp_control", False):
                        return owner
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
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


def _selected_roots_cache_key(context):
    try:
        scene = getattr(context, "scene", None)
        active = getattr(context, "object", None)
        selected = tuple(getattr(context, "selected_objects", ()) or ())
        selection_sig = tuple(
            (
                _object_pointer(obj),
                _object_name(obj),
                str(getattr(obj, "type", "") or ""),
                _object_pointer(getattr(obj, "parent", None)),
            )
            for obj in selected
            if obj is not None
        )
        return (_object_pointer(scene), _object_pointer(active), selection_sig)
    except FBP_DATA_ERRORS:
        return None


def get_selected_fbp_roots(context):
    """Return selected FBP rigs with the active rig first for reliable multi-edit UI."""
    cache_key = _selected_roots_cache_key(context)
    if cache_key is not None:
        cached = _FBP_SELECTED_ROOTS_CACHE.get(cache_key)
        if cached is not None:
            try:
                checked_at, names = cached
                if time.monotonic() - float(checked_at or 0.0) <= _FBP_SELECTED_ROOTS_CACHE_SECONDS:
                    roots = []
                    for name in tuple(names or ()):
                        rig = _resolve_cached_rig(name, 0, context)
                        if rig is not None and rig not in roots:
                            roots.append(rig)
                    return roots
            except (TypeError, ValueError):
                pass
    roots = []
    selected = tuple(getattr(context, "selected_objects", ()) or ())
    active = getattr(context, "object", None)
    # Blender can keep context.object pointing at the former active object after
    # Select None.  This function promises selected roots only; callers that
    # intentionally want an active-object fallback use get_selected_or_active_rigs().
    ordered = (
        (active,) + tuple(obj for obj in selected if obj is not active)
        if active is not None and active in selected
        else selected
    )
    for ob in ordered:
        rig = fbp_resolve_rig_from_any_object(ob, context)
        if rig and rig not in roots:
            roots.append(rig)
    if cache_key is not None:
        if len(_FBP_SELECTED_ROOTS_CACHE) >= _FBP_SELECTED_ROOTS_CACHE_LIMIT and cache_key not in _FBP_SELECTED_ROOTS_CACHE:
            _FBP_SELECTED_ROOTS_CACHE.clear()
        _FBP_SELECTED_ROOTS_CACHE[cache_key] = (
            time.monotonic(),
            tuple(_object_name(rig) for rig in roots),
        )
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
    """Release layer thumbnails without touching unrelated UI icon collections."""
    _FBP_COMPOSITE_PREVIEW_KEYS.clear()
    _FBP_RAW_PREVIEW_KEYS.clear()
    for key in ("fbp_previews", _FBP_COMPOSITE_PREVIEW_COLLECTION):
        pcoll = preview_collections.pop(key, None)
        if pcoll is None:
            continue
        try:
            bpy.utils.previews.remove(pcoll)
        except FBP_DATA_ERRORS:
            pass
    _FBP_PREVIEW_MISS_CACHE.clear()
    try:
        from .drawing_plane import clear_drawing_preview_runtime_state
        clear_drawing_preview_runtime_state()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


def update_rig_visibility(rig, layer_item=None, context=None):
    """Apply one rig's visibility contract without scanning every layer."""
    # RNA update callbacks can run while Undo is replacing Main. Never touch
    # object visibility, materials or image-backed planes in that interval.
    if fbp_undo_guard_active() or not rig:
        return False
    try:
        if layer_item is None:
            context = context or getattr(bpy, "context", None)
            layer_item = get_layer_item_for_rig(context, rig) if context else None
        visible = bool(getattr(rig, "fbp_is_visible", True)) and not bool(
            getattr(layer_item, "mute", False) if layer_item is not None else False
        )
        try:
            scene = getattr(context, "scene", None) if context else None
            gp_solo_active = False
            if scene is not None:
                from .grease_pencil_bridge import any_gp_canvas_solo
                gp_solo_active = bool(any_gp_canvas_solo(scene))
            layer_solo_active = bool(
                context and scene is not None
                and any(bool(getattr(item, "solo", False)) for item in getattr(scene, "fbp_layers", ()) or ())
            )
            if gp_solo_active or layer_solo_active:
                visible = bool(visible and getattr(layer_item, "solo", False))
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        hidden = not visible
        try:
            if bool(rig.hide_get()) != hidden:
                rig.hide_set(hidden)
        except FBP_DATA_IO_ERRORS:
            pass
        plane = getattr(rig, "fbp_plane_target", None)
        if not plane:
            return True
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
    if fbp_undo_guard_active():
        return
    context = context or getattr(bpy, "context", None)
    scene = getattr(context, "scene", None) if context else None
    if scene is None:
        return
    for item in getattr(scene, "fbp_layers", ()) or ():
        try:
            update_rig_visibility(item.obj, item, context)
        except ReferenceError:
            pass
    try:
        from .grease_pencil_bridge import sync_gp_canvas_visibility
        sync_gp_canvas_visibility(context)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


def update_mute_cb(self, context):
    """Mute only the edited layer; collection/solo operations call the global path."""
    try:
        update_rig_visibility(self.obj, self, context)
    except FBP_DATA_ERRORS:
        pass


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
    """Maintain a bounded LRU for square/processed thumbnails."""
    try:
        _FBP_COMPOSITE_PREVIEW_KEYS.remove(cache_key)
    except ValueError:
        pass
    _FBP_COMPOSITE_PREVIEW_KEYS.append(cache_key)
    while len(_FBP_COMPOSITE_PREVIEW_KEYS) > _FBP_COMPOSITE_PREVIEW_LIMIT:
        oldest = _FBP_COMPOSITE_PREVIEW_KEYS.popleft()
        if oldest == cache_key:
            continue
        try:
            if oldest in pcoll:
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
                    "camera_type": str(getattr(getattr(cam, "data", None), "type", "PERSP") or "PERSP"),
                    "camera_name": str(getattr(cam, "name", "") or ""),
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
    # Layer view order is Photoshop/Procreate-like: closest to camera first
    # at the top of the list, farthest layers last at the bottom.  Sort only by
    # physical depth; the input order remains the stable tie-breaker.
    depth_ctx = fbp_make_depth_context_cache(context)
    depth_cache = {
        rig: fbp_layer_depth_value_from_cache(rig, depth_ctx)
        for rig in rigs if rig
    }
    return sorted(
        rigs,
        key=lambda rig: depth_cache.get(rig, 0.0),
    )


def sort_rigs_by_depth_for_layer_view(context, rigs):
    return sort_rigs_for_layer_view(context, rigs)


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
        # Plane solo must isolate against Grease Pencil canvases as well.
        try:
            from .grease_pencil_bridge import clear_gp_canvas_solo
            clear_gp_canvas_solo(sc)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
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
    except FBP_DATA_ERRORS:
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
    """Resolve members through the canonical Layer-List collection contract.

    Layer List collections are real Blender Collections and membership is
    resolved only from the current canonical collection hierarchy.
    """
    if collection is None:
        return []
    try:
        context = getattr(bpy, "context", None)
        scene = getattr(context, "scene", None) if context else None
        if scene is None:
            return []

        collection_keys = {
            int(current.as_pointer())
            for current in fbp_canonical_collection_descendants(scene, collection)
            if current is not None
        }

        result = []
        seen = set()
        for rig in iter_scene_fbp_rigs(scene, fallback=True):
            if rig is None:
                continue
            primary = get_primary_fbp_collection(rig)
            if primary is None or int(primary.as_pointer()) not in collection_keys:
                continue
            key = int(rig.as_pointer())
            if key in seen:
                continue
            seen.add(key)
            result.append(rig)
        return result
    except FBP_DATA_ERRORS:
        return []


def _collection_tree_for_ui(collection):
    """Return the canonical Layer List collection subtree once, depth-first."""
    if collection is None:
        return []
    context = getattr(bpy, "context", None)
    scene = getattr(context, "scene", None) if context else None
    return fbp_canonical_collection_descendants(scene, collection)


def _collection_gp_canvases_for_ui(collection):
    """Resolve Drawing Plane rows assigned to a visual collection tree."""
    if collection is None:
        return []
    try:
        context = getattr(bpy, "context", None)
        scene = getattr(context, "scene", None) if context else None
        if scene is None:
            return []
        from .fbp_index import iter_scene_gp_canvases
        from .grease_pencil_bridge import is_gp_drawing_canvas

        collection_keys = {
            int(current.as_pointer())
            for current in _collection_tree_for_ui(collection)
            if current is not None
        }
        result = []
        seen = set()
        for canvas in iter_scene_gp_canvases(scene, kind="DRAWING", fallback=True):
            if canvas is None or not is_gp_drawing_canvas(canvas):
                continue
            primary = get_primary_fbp_collection(canvas)
            if primary is None or int(primary.as_pointer()) not in collection_keys:
                continue
            key = int(canvas.as_pointer())
            if key in seen:
                continue
            seen.add(key)
            result.append(canvas)
        return result
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return []


def _collection_ui_members(collection):
    """Return mesh rigs and GP Drawing Planes represented by one folder row."""
    return _collection_rigs_for_ui(collection), _collection_gp_canvases_for_ui(collection)


def get_collection_selected(self):
    rigs, gp_canvases = _collection_ui_members(self)
    members = tuple(rigs) + tuple(gp_canvases)
    try:
        return bool(members and all(bool(member.select_get()) for member in members))
    except FBP_DATA_ERRORS:
        return False


def set_collection_selected(self, value):
    context = getattr(bpy, "context", None)
    selected_value = bool(value)
    last_selected = None
    rigs, gp_canvases = _collection_ui_members(self)
    for member in tuple(rigs) + tuple(gp_canvases):
        try:
            if selected_value and context and not object_in_view_layer(member, context):
                if not ensure_object_in_active_collection(member, context):
                    continue
            # Folder selection must never silently unlock a locked child.  This
            # differs from the direct GP row proxy, where clicking the row is an
            # explicit request to edit that canvas.
            if selected_value and bool(getattr(member, "hide_select", False)):
                continue
            member.select_set(selected_value)
            if selected_value and object_in_view_layer(member, context):
                last_selected = member
        except FBP_DATA_IO_ERRORS:
            continue
    if last_selected is not None and context and getattr(context, "view_layer", None):
        try:
            context.view_layer.objects.active = last_selected
        except FBP_DATA_IO_ERRORS:
            pass
    # Property-icon selection must keep the collection row active just like a
    # click on its name. Otherwise the active-object message bus immediately
    # paints one child layer blue instead of the collection.
    if context is not None:
        scene = getattr(context, "scene", None)
        if scene is not None:
            try:
                tree_index = next((
                    index for index, row in enumerate(getattr(scene, "fbp_layer_tree_rows", ()) or ())
                    if str(getattr(row, "row_type", "") or "") == "GROUP"
                    and str(getattr(row, "collection_name", "") or "") == str(getattr(self, "name", "") or "")
                ), -1)
                if tree_index >= 0:
                    scene.fbp_layer_tree_rows_idx = tree_index
                fbp_runtime_set(
                    "fbp.collection_row_selection_guard",
                    {
                        "scene_pointer": int(scene.as_pointer()),
                        "collection_name": str(getattr(self, "name", "") or ""),
                        "tree_index": int(tree_index),
                        "expires": time.monotonic() + 0.85,
                    },
                )
            except FBP_DATA_IO_ERRORS:
                pass


def get_collection_solo(self):
    rigs, gp_canvases = _collection_ui_members(self)
    states = []
    try:
        for rig in rigs:
            item = get_layer_item_for_rig(bpy.context, rig)
            states.append(bool(item and getattr(item, "solo", False)))
        from .grease_pencil_bridge import gp_canvas_solo_active
        states.extend(bool(gp_canvas_solo_active(canvas)) for canvas in gp_canvases)
        return bool(states and all(states))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def set_collection_solo(self, value):
    context = getattr(bpy, "context", None)
    scene = getattr(context, "scene", None) if context else None
    if not scene:
        return
    target_rigs, target_canvases = _collection_ui_members(self)
    try:
        target_rig_keys = {_object_pointer(rig) for rig in target_rigs if rig is not None}
        target_canvas_keys = {_object_pointer(canvas) for canvas in target_canvases if canvas is not None}
        value = bool(value)
        items = list(getattr(scene, "fbp_layers", ()) or ())
        from .grease_pencil_bridge import (
            KEY_CANVAS_SOLO,
            gp_canvas_solo_active,
            is_gp_drawing_canvas,
        )
        from .fbp_index import iter_scene_gp_canvases
        all_canvases = tuple(
            canvas for canvas in iter_scene_gp_canvases(scene, kind="DRAWING", fallback=True)
            if canvas is not None and is_gp_drawing_canvas(canvas)
        )
        had_any_solo = bool(
            any(bool(getattr(item, "solo", False)) for item in items)
            or any(gp_canvas_solo_active(canvas) for canvas in all_canvases)
        )

        # Preserve the established Layer List contract: entering the first solo
        # state stores the isolation in solo flags and suppresses non-target
        # mesh eye states. Additional folder solos remain additive.
        if value and not had_any_solo:
            for item in items:
                item.solo = False
                rig = _safe_layer_obj(item)
                if rig:
                    fbp_set_rna_property_silent(rig, "fbp_is_visible", False)

        for item in items:
            rig = _safe_layer_obj(item)
            if not rig or _object_pointer(rig) not in target_rig_keys:
                continue
            item.solo = value
            if value:
                fbp_set_rna_property_silent(rig, "fbp_is_visible", True)

        for canvas in all_canvases:
            if _object_pointer(canvas) not in target_canvas_keys:
                continue
            canvas[KEY_CANVAS_SOLO] = value
            if value:
                fbp_set_rna_property_silent(canvas, "fbp_gp_canvas_visible", True)

        any_solo_remaining = bool(
            any(bool(getattr(item, "solo", False)) for item in items)
            or any(gp_canvas_solo_active(canvas) for canvas in all_canvases)
        )
        if not any_solo_remaining:
            for item in items:
                rig = _safe_layer_obj(item)
                if rig:
                    fbp_set_rna_property_silent(rig, "fbp_is_visible", True)

        update_global_visibility(context)
    except Exception as exc:
        fbp_warn("Could not update collection solo visibility", exc)


def get_collection_locked(self):
    rigs, gp_canvases = _collection_ui_members(self)
    members = tuple(rigs) + tuple(gp_canvases)
    return bool(members and all(bool(getattr(member, "hide_select", False)) for member in members))


def set_collection_locked(self, value):
    locked = bool(value)
    rigs, gp_canvases = _collection_ui_members(self)
    for member in tuple(rigs) + tuple(gp_canvases):
        try:
            member.hide_select = locked
            if locked and bool(member.select_get()):
                member.select_set(False)
        except FBP_DATA_IO_ERRORS:
            continue

def get_collection_plane_locked(self):
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


def get_collection_visible(self):
    try:
        return not collection_is_hidden_in_view_layer(bpy.context, self)
    except FBP_DATA_ERRORS:
        return True


def set_collection_visible(self, value):
    # Custom RNA setters may be replayed while Ctrl+Z restores IDs. Side-effect
    # writes here would race Eevee's image/material sync and can crash Blender.
    if fbp_undo_guard_active():
        return
    visible = bool(value)
    hidden = not visible
    context = getattr(bpy, "context", None)
    collections = _collection_tree_for_ui(self)
    for collection in collections:
        try:
            collection.hide_viewport = hidden
        except FBP_DATA_IO_ERRORS:
            pass
        try:
            view_layer = getattr(context, "view_layer", None) if context else None
            layer_coll = find_layer_collection(view_layer.layer_collection, collection) if view_layer else None
            if layer_coll:
                layer_coll.hide_viewport = hidden
        except FBP_DATA_IO_ERRORS:
            pass

    for rig in _collection_rigs_for_ui(self):
        try:
            fbp_set_rna_property_silent(rig, "fbp_is_visible", visible)
        except FBP_DATA_IO_ERRORS:
            pass

    gp_canvases = _collection_gp_canvases_for_ui(self)
    for canvas in gp_canvases:
        try:
            fbp_set_rna_property_silent(canvas, "fbp_gp_canvas_visible", visible)
        except FBP_DATA_IO_ERRORS:
            pass

    try:
        update_global_visibility(context)
    except FBP_DATA_IO_ERRORS:
        pass
    # The UIList is a virtual tree. Force its signature to rebuild immediately
    # after parent visibility changes so stale child-eye states are never shown.
    try:
        scene = getattr(bpy.context, "scene", None)
        if scene:
            scene.fbp_layer_tree_signature = ""
        fbp_request_redraw(area_types={'VIEW_3D', 'PROPERTIES'})
    except FBP_DATA_ERRORS:
        pass


def get_collection_holdout(self):
    rigs = _collection_rigs_for_ui(self)
    try:
        # Folder icon is considered active if at least one child layer is currently in temporary holdout.
        return bool(rigs and any(rig_holdout_is_active(rig) for rig in rigs))
    except FBP_DATA_ERRORS:
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
