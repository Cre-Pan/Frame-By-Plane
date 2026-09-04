"""Blender 5.2 compositor layers for Frame By Plane collections.

The implementation deliberately keeps the author's collection hierarchy intact.
Managed shadow collections only add temporary object links, allowing nested FBP
groups to become isolated View Layers without moving or duplicating objects.
"""

import os
import re
import uuid

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import NodeTree, Operator, Panel, PropertyGroup, UIList

from .ui_list_state import invoke_with_selection_modifiers
from .runtime import FBP_DATA_ERRORS, fbp_warn
from .feature_scope import fbp_feature_enabled
from .registration import register_classes, unregister_classes, unregister_type_properties
from .shortcut_runtime import primary_modifier_name, primary_modifier_pressed, primary_shortcut_label
from .safe_tasks import cancel_scheduled_prefixes, schedule_once, scheduled_task_pending
from .service_registry import register_service, unregister_service
from .ui_list_state import (
    clear_anchor,
    ensure_item_identity,
    ensure_unique_item_identities,
    resolve_anchor_index,
    restore_active_index,
    store_anchor,
    transient_get,
)
from .ui_list_state import mark_ui_list_draw, ui_list_mutation_delay
from .interface_preferences import (
    fbp_draw_uilist_spacer,
    fbp_draw_uilist_header,
    fbp_uilist_icon_order,
    fbp_uilist_is_spacer,
    fbp_uilist_visible_columns,
)


FBP_COMPOSITOR_TREE_TAG = "fbp_compositor_owned"
FBP_COMPOSITOR_SOURCE_TREE_TAG = "fbp_compositor_source_group"
FBP_COMPOSITOR_EFFECTS_TREE_TAG = "fbp_compositor_effects_group"
FBP_COMPOSITOR_LAYER_TAG = "fbp_compositor_layer_id"
FBP_COMPOSITOR_SHADOW_TAG = "fbp_compositor_shadow"
FBP_COMPOSITOR_ROOT_TAG = "fbp_compositor_shadow_root"
FBP_COMPOSITOR_ASSET_TAG = "fbp_blender_52_compositor_asset"
FBP_COMPOSITOR_LAYER_NODE_SCHEMA_VERSION = 1
FBP_COMPOSITOR_LAYER_NODE_SCHEMA_KEY = "fbp_compositor_layer_node_schema"
FBP_COMPOSITOR_LAYER_NODE_GENERATION_KEY = (
    "fbp_compositor_layer_node_generation"
)

FBP_COMPOSITOR_GENERATION_ITEMS = (
    ('TAGS', "Tags as Layers", "Create one output layer for each color tag used in the Layer List"),
    ('LAYERS', "Layers as Layers", "Create one isolated output for every Frame By Plane layer"),
    ('LAYERS_GROUPS', "Layers and Groups as Layers", f"Keep every layer editable and organize {primary_shortcut_label('G')} groups as compositor folders"),
    ('COLLECTIONS', "Collections as Layers", "Create one output for each collection containing Frame By Plane layers"),
)

FBP_COMPOSITOR_SOURCE_KIND_ITEMS = (
    ('MANUAL', "Manual", "Use manually assigned Frame By Plane collections"),
    ('TAG', "Tag", "Layers sharing one Layer List color tag"),
    ('LAYER', "Layer", "One Frame By Plane layer"),
    ('GROUP', "Group", f"One {primary_shortcut_label('G')} Layer List group"),
    ('COLLECTION', "Collection", "Layers directly represented by one collection"),
)

FBP_COMPOSITOR_EFFECT_ITEMS = (
    ('NONE', "None", "No per-layer compositor effect"),
    ('GLOW', "Glow", "Fog Glow using Blender 5.2 Glare sockets"),
    ('BLUR', "Blur", "Gaussian compositor blur"),
    ('DEFOCUS', "Defocus", "Depth-aware defocus from this layer's Z pass"),
    ('COLOR_GRADE', "Color Grade", "Temperature and tint color balance"),
    ('PIXELATE', "Pixelate", "Blocky nearest-neighbour pixels using native Blender 5.2 compositor nodes"),
    ('VIGNETTE', "Vignette", "Blender 5.2 Vignette compositor asset"),
    ('UNSHARP_MASK', "Unsharp Mask", "Blender 5.2 Unsharp Mask compositor asset"),
    ('TUNE_IMAGE', "Tune Image", "Blender 5.2 Tune Image compositor asset"),
    ('FILM_GRAIN', "Film Grain", "Blender 5.2 analog Film Grain compositor asset"),
    ('CHROMATIC_ABERRATION', "Chromatic Aberration", "Blender 5.2 lens-fringing compositor asset"),
    ('SEPIA', "Sepia", "Blender 5.2 vintage Sepia compositor asset"),
)
FBP_COMPOSITOR_ADD_EFFECT_ITEMS = tuple(
    item for item in FBP_COMPOSITOR_EFFECT_ITEMS if item[0] != 'NONE'
)
_FBP_ROOT_ROLE_BY_IDNAME = {
    "FBPCompositorLayerSetNode": "layer_set",
    "FBPCompositorOutputNode": "output",
    "FBPCompositorStackNode": "over_stack",
}


def _fbp_root_node_role(node):
    """Classify FBP root nodes without probing arbitrary IDProperty groups."""
    try:
        role = _FBP_ROOT_ROLE_BY_IDNAME.get(str(getattr(node, "bl_idname", "") or ""))
        if role:
            return role
        child = getattr(node, "node_tree", None)
        child_name = str(getattr(child, "name", "") or "") if child is not None else ""
        node_name = str(getattr(node, "name", "") or "")
    except FBP_DATA_ERRORS:
        return ""
    if child_name.startswith("FBP Layers") or node_name in {"FBP Layers", "FBP Layers & Groups"}:
        return "layers_package"
    if child_name.startswith("FBP Effects & Masks") or node_name == "FBP Effects & Masks":
        return "effects_stage"
    if child_name.startswith("FBP Output -"):
        return "output"
    if child_name.startswith("FBP Over Stack -"):
        return "over_stack"
    if node_name == "FBP Composite Output":
        return "legacy_group_output"
    return ""


FBP_COMPOSITOR_TAG_LABELS = {
    'NONE': "None / Default",
    'COLOR_01': "Red",
    'COLOR_02': "Orange",
    'COLOR_03': "Yellow",
    'COLOR_04': "Green",
    'COLOR_05': "Cyan",
    'COLOR_06': "Purple",
    'COLOR_07': "Magenta",
}


def _new_id():
    return uuid.uuid4().hex


def _clean_name(value, fallback="Layer"):
    value = re.sub(r"[^\w .-]+", "_", str(value or "").strip(), flags=re.UNICODE)
    return value[:54] or fallback


def _scene_id(scene):
    value = str(getattr(scene, "fbp_compositor_scene_id", "") or "")
    if not value:
        value = _new_id()
        scene.fbp_compositor_scene_id = value
    return value


def _scene_runtime_key(scene):
    """Return a primitive scene identity safe for deferred compositor work.

    Scene names are user-editable and therefore cannot be the sole identity of
    a queued update.  The pointer is only used within the current Main database;
    load/undo lifecycle handlers invalidate all scheduled work before it can be
    reused by a replacement scene.
    """
    try:
        return (
            int(scene.as_pointer()),
            str(getattr(scene, "name_full", "") or getattr(scene, "name", "") or ""),
        )
    except FBP_DATA_ERRORS:
        return (0, str(getattr(scene, "name", "") or ""))


def _scene_from_runtime_key(key):
    try:
        pointer, name = key
        pointer = int(pointer or 0)
        name = str(name or "")
    except (TypeError, ValueError):
        pointer, name = 0, str(key or "")
    if pointer:
        try:
            for scene in bpy.data.scenes:
                try:
                    if int(scene.as_pointer()) == pointer:
                        return scene
                except FBP_DATA_ERRORS:
                    continue
        except FBP_DATA_ERRORS:
            return None
    try:
        return bpy.data.scenes.get(name) if name else None
    except FBP_DATA_ERRORS:
        return None


def _queue_compositor_scene(scene):
    if scene is None:
        return None
    key = _scene_runtime_key(scene)
    _FBP_PENDING_COMPOSITOR_SCENES.add(key)
    return key


def fbp_compositor_layer_node_schema_status(scene):
    """Return schema state without modifying the Scene."""
    if scene is None:
        return {
            "stored": 0,
            "current": FBP_COMPOSITOR_LAYER_NODE_SCHEMA_VERSION,
            "outdated": True,
            "unsupported_future": False,
            "generation": 0,
        }
    try:
        stored = int(
            scene.get(FBP_COMPOSITOR_LAYER_NODE_SCHEMA_KEY, 0) or 0
        )
        generation = int(
            scene.get(FBP_COMPOSITOR_LAYER_NODE_GENERATION_KEY, 0) or 0
        )
    except (ReferenceError, RuntimeError, TypeError, ValueError):
        stored = 0
        generation = 0
    return {
        "stored": stored,
        "current": FBP_COMPOSITOR_LAYER_NODE_SCHEMA_VERSION,
        "outdated": stored < FBP_COMPOSITOR_LAYER_NODE_SCHEMA_VERSION,
        "unsupported_future": (
            stored > FBP_COMPOSITOR_LAYER_NODE_SCHEMA_VERSION
        ),
        "generation": generation,
    }


def _guard_compositor_layer_node_schema(scene):
    status = fbp_compositor_layer_node_schema_status(scene)
    if status["unsupported_future"]:
        raise RuntimeError(
            "Compositor Layer Node schema "
            f"v{status['stored']} is newer than this build supports "
            f"(v{status['current']}); use the matching Frame By Plane version"
        )
    return status


def _mark_compositor_layer_node_schema(scene, tree):
    status = fbp_compositor_layer_node_schema_status(scene)
    generation = max(0, int(status["generation"])) + 1
    scene[FBP_COMPOSITOR_LAYER_NODE_SCHEMA_KEY] = int(
        FBP_COMPOSITOR_LAYER_NODE_SCHEMA_VERSION
    )
    scene[FBP_COMPOSITOR_LAYER_NODE_GENERATION_KEY] = generation
    if tree is not None:
        tree[FBP_COMPOSITOR_LAYER_NODE_SCHEMA_KEY] = int(
            FBP_COMPOSITOR_LAYER_NODE_SCHEMA_VERSION
        )
        tree[FBP_COMPOSITOR_LAYER_NODE_GENERATION_KEY] = generation
        for node in tuple(getattr(tree, "nodes", ()) or ()):
            if _fbp_root_node_role(node) != "layers_package":
                continue
            source_tree = getattr(node, "node_tree", None)
            if source_tree is not None:
                source_tree[FBP_COMPOSITOR_LAYER_NODE_SCHEMA_KEY] = int(
                    FBP_COMPOSITOR_LAYER_NODE_SCHEMA_VERSION
                )
                source_tree[FBP_COMPOSITOR_LAYER_NODE_GENERATION_KEY] = (
                    generation
                )
    return generation


def _walk_collections(collection):
    for child in getattr(collection, "children", ()):
        yield child
        yield from _walk_collections(child)


def _walk_layer_collections(layer_collection):
    yield layer_collection
    for child in getattr(layer_collection, "children", ()):
        yield from _walk_layer_collections(child)


def _collection_has_fbp_objects(collection, recursive=True):
    try:
        if any(
            bool(getattr(obj, "is_fbp_control", False))
            or bool(getattr(obj, "is_fbp_plane", False))
            for obj in collection.objects
        ):
            return True
        return bool(
            recursive
            and any(_collection_has_fbp_objects(child, True) for child in collection.children)
        )
    except FBP_DATA_ERRORS:
        return False


def fbp_compositor_group_collections(scene):
    """Return scene-local FBP groups in deterministic hierarchy order."""
    rigs = _scene_fbp_rigs(scene)
    primary_collections = set()
    for rig in rigs:
        collection = _primary_collection(rig)
        if collection is not None:
            primary_collections.add(collection)
    represented_collections = set(primary_collections)
    parent_map = _collection_parent_map(scene)
    for collection in tuple(primary_collections):
        visited = set()
        current = collection
        while current is not None:
            try:
                pointer = int(current.as_pointer())
            except FBP_DATA_ERRORS:
                break
            if pointer in visited:
                break
            visited.add(pointer)
            represented_collections.add(current)
            current = parent_map.get(pointer)
    result = []
    for collection in _walk_collections(scene.collection):
        if bool(collection.get(FBP_COMPOSITOR_ROOT_TAG, False)):
            continue
        if not bool(getattr(collection, "is_fbp_collection", False)):
            continue
        if (
            collection in represented_collections
            or _collection_has_fbp_objects(collection, True)
        ):
            result.append(collection)
    return result


def _scene_fbp_rigs(scene):
    """Return FBP layer rigs in Layer List order without retaining RNA globally."""
    if scene is None:
        return ()
    result = []
    seen = set()

    def add(rig):
        try:
            if rig is None or not bool(getattr(rig, "is_fbp_control", False)):
                return
            if scene.objects.get(rig.name) != rig:
                return
            key = int(rig.as_pointer())
            if key in seen:
                return
            seen.add(key)
            result.append(rig)
        except FBP_DATA_ERRORS:
            return

    for item in tuple(getattr(scene, "fbp_layers", ()) or ()):
        try:
            add(getattr(item, "obj", None))
        except FBP_DATA_ERRORS:
            continue
    if not result:
        for obj in tuple(getattr(scene, "objects", ()) or ()):
            add(obj)
    return tuple(result)


def _primary_collection(rig):
    try:
        from .layers import get_primary_fbp_collection
        return get_primary_fbp_collection(rig)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None


def _physical_fbp_collection(rig, scene):
    """Return the real non-shadow collection that owns a rig."""
    try:
        collections = tuple(getattr(rig, "users_collection", ()) or ())
    except FBP_DATA_ERRORS:
        collections = ()
    candidates = []
    for collection in collections:
        try:
            if bool(collection.get(FBP_COMPOSITOR_SHADOW_TAG, False)):
                continue
            if bool(collection.get(FBP_COMPOSITOR_ROOT_TAG, False)):
                continue
            candidates.append(collection)
        except FBP_DATA_ERRORS:
            continue
    preferred = [
        collection for collection in candidates
        if bool(getattr(collection, "is_fbp_collection", False))
    ]
    if preferred:
        return preferred[0]
    if candidates:
        return candidates[0]
    return getattr(scene, "collection", None) if scene is not None else None


def _ensure_source_id(datablock):
    if datablock is None:
        return ""
    try:
        value = str(getattr(datablock, "fbp_compositor_source_id", "") or "")
    except FBP_DATA_ERRORS:
        value = ""
    if not value:
        value = _new_id()
        try:
            datablock.fbp_compositor_source_id = value
        except FBP_DATA_ERRORS:
            try:
                datablock["fbp_compositor_source_id"] = value
            except FBP_DATA_ERRORS:
                return ""
    return value


def _ensure_unique_source_ids(datablocks):
    """Repair copied UUIDs in one linear pass before generating sources."""
    seen = set()
    for datablock in tuple(datablocks or ()):
        if datablock is None:
            continue
        try:
            value = str(
                getattr(datablock, "fbp_compositor_source_id", "") or ""
            )
        except FBP_DATA_ERRORS:
            value = ""
        if not value or value in seen:
            value = _new_id()
            try:
                datablock.fbp_compositor_source_id = value
            except FBP_DATA_ERRORS:
                continue
        seen.add(value)
    return seen


def _collection_parent_map(scene):
    result = {}
    root = getattr(scene, "collection", None) if scene is not None else None
    if root is None:
        return result
    stack = [root]
    seen = set()
    while stack:
        parent = stack.pop()
        try:
            pointer = int(parent.as_pointer())
            if pointer in seen:
                continue
            seen.add(pointer)
            children = tuple(getattr(parent, "children", ()) or ())
        except FBP_DATA_ERRORS:
            continue
        for child in children:
            result[int(child.as_pointer())] = parent
            stack.append(child)
    return result


def _collection_is_descendant(candidate, ancestor, scene, parent_map=None):
    if candidate is None or ancestor is None:
        return False
    if candidate == ancestor:
        return True
    parent_map = parent_map if parent_map is not None else _collection_parent_map(scene)
    current = candidate
    seen = set()
    while current is not None:
        try:
            pointer = int(current.as_pointer())
        except FBP_DATA_ERRORS:
            return False
        if pointer in seen:
            return False
        seen.add(pointer)
        current = parent_map.get(pointer)
        if current == ancestor:
            return True
    return False


def _collection_by_source_id(scene, source_id):
    source_id = str(source_id or "")
    if not source_id or scene is None:
        return None
    candidates = (scene.collection,) + tuple(_walk_collections(scene.collection))
    for collection in candidates:
        try:
            if str(getattr(collection, "fbp_compositor_source_id", "") or "") == source_id:
                return collection
        except FBP_DATA_ERRORS:
            continue
    return None


def _is_layer_group(collection, rigs):
    if collection is None:
        return False
    try:
        if bool(getattr(collection, "fbp_layer_group", False)):
            return True
    except FBP_DATA_ERRORS:
        pass
    # Compatibility with groups created before the persistent marker existed:
    # Ctrl+G changes the Layer List collection hint without physically relinking
    # the rig. That mismatch is a reliable signature of a virtual group.
    for rig in rigs:
        if _primary_collection(rig) != collection:
            continue
        try:
            if collection.objects.get(rig.name) != rig:
                return True
        except FBP_DATA_ERRORS:
            continue
    return False


def _top_layer_groups(scene, rigs, parent_map=None):
    parent_map = parent_map if parent_map is not None else _collection_parent_map(scene)
    groups = [
        collection for collection in _walk_collections(scene.collection)
        if _is_layer_group(collection, rigs)
    ]
    for collection in groups:
        try:
            collection.fbp_layer_group = True
        except FBP_DATA_ERRORS:
            pass
    group_pointers = {int(collection.as_pointer()) for collection in groups}
    result = []
    for collection in groups:
        current = parent_map.get(int(collection.as_pointer()))
        nested = False
        while current is not None:
            pointer = int(current.as_pointer())
            if pointer in group_pointers:
                nested = True
                break
            current = parent_map.get(pointer)
        if not nested:
            result.append(collection)
    return tuple(result)


def fbp_compositor_source_specs(scene, mode=None):
    """Describe deterministic, non-overlapping sources for Auto Layers."""
    mode = str(
        mode or getattr(scene, "fbp_compositor_generation_mode", 'LAYERS_GROUPS')
        or 'LAYERS_GROUPS'
    ).upper()
    rigs = _scene_fbp_rigs(scene)
    collections = (scene.collection,) + tuple(_walk_collections(scene.collection))
    _ensure_unique_source_ids(rigs)
    _ensure_unique_source_ids(collections)
    order = {int(rig.as_pointer()): index for index, rig in enumerate(rigs)}
    parent_map = _collection_parent_map(scene)
    specs = []

    def add(
        kind,
        key,
        name,
        members,
        *,
        allow_empty=False,
        folder_key="",
        folder_name="",
    ):
        members = tuple(dict.fromkeys(rig for rig in members if rig is not None))
        if not members and not allow_empty:
            return
        specs.append({
            "kind": kind,
            "key": str(key or ""),
            "name": _clean_name(name),
            "rigs": members,
            "folder_key": str(folder_key or ""),
            "folder_name": _clean_name(folder_name, "Folder") if folder_key else "",
            "order": (
                min(order.get(int(rig.as_pointer()), 1 << 30) for rig in members)
                if members else 1 << 30
            ),
        })

    if mode == 'TAGS':
        buckets = {}
        for rig in rigs:
            tag = str(getattr(rig, "fbp_color_tag", 'NONE') or 'NONE').upper()
            if tag not in FBP_COMPOSITOR_TAG_LABELS:
                tag = 'NONE'
            buckets.setdefault(tag, []).append(rig)
        for tag, members in buckets.items():
            add('TAG', tag, f"Tag - {FBP_COMPOSITOR_TAG_LABELS[tag]}", members)
    elif mode == 'LAYERS':
        for rig in rigs:
            add('LAYER', _ensure_source_id(rig), rig.name, (rig,))
    elif mode == 'COLLECTIONS':
        buckets = {}
        for rig in rigs:
            collection = _physical_fbp_collection(rig, scene) or scene.collection
            buckets.setdefault(collection, []).append(rig)
        for collection, members in buckets.items():
            add(
                'COLLECTION',
                _ensure_source_id(collection),
                getattr(collection, "name", "Scene Collection"),
                members,
            )
        if not buckets:
            for collection in fbp_compositor_group_collections(scene):
                add(
                    'COLLECTION',
                    _ensure_source_id(collection),
                    collection.name,
                    (),
                    allow_empty=True,
                )
    else:
        if not rigs:
            for collection in fbp_compositor_group_collections(scene):
                add(
                    'COLLECTION',
                    _ensure_source_id(collection),
                    collection.name,
                    (),
                    allow_empty=True,
                )
            specs.sort(key=lambda item: (item["order"], item["name"]), reverse=True)
            return tuple(specs)
        groups = _top_layer_groups(scene, rigs, parent_map)
        for rig in rigs:
            physical = _primary_collection(rig)
            hinted = bpy.data.collections.get(
                str(getattr(rig, "fbp_collection_name", "") or "")
            )
            folder = next(
                (
                    collection for collection in groups
                    if collection in {physical, hinted}
                    or _collection_is_descendant(
                        physical, collection, scene, parent_map
                    )
                    or _collection_is_descendant(
                        hinted, collection, scene, parent_map
                    )
                ),
                None,
            )
            add(
                'LAYER',
                _ensure_source_id(rig),
                rig.name,
                (rig,),
                folder_key=_ensure_source_id(folder) if folder is not None else "",
                folder_name=folder.name if folder is not None else "",
            )

    # The Layer List is front-to-back; Alpha Over needs back-to-front sources.
    specs.sort(key=lambda item: (item["order"], item["name"]), reverse=True)
    return tuple(specs)


def _source_rigs_for_item(scene, item, rigs=None):
    rigs = tuple(rigs if rigs is not None else _scene_fbp_rigs(scene))
    kind = str(getattr(item, "source_kind", 'MANUAL') or 'MANUAL').upper()
    key = str(getattr(item, "source_key", "") or "")
    if kind == 'TAG':
        return tuple(
            rig for rig in rigs
            if str(getattr(rig, "fbp_color_tag", 'NONE') or 'NONE').upper() == key
        )
    if kind == 'LAYER':
        return tuple(
            rig for rig in rigs
            if str(getattr(rig, "fbp_compositor_source_id", "") or "") == key
        )
    if kind in {'GROUP', 'COLLECTION'}:
        collection = _collection_by_source_id(scene, key)
        if collection is None:
            return ()
        parent_map = _collection_parent_map(scene)
        if kind == 'GROUP':
            return tuple(
                rig for rig in rigs
                if _collection_is_descendant(
                    _primary_collection(rig), collection, scene, parent_map
                )
            )
        return tuple(
            rig for rig in rigs
            if (_physical_fbp_collection(rig, scene) == collection)
        )
    return ()


def _source_rig_index(scene, rigs, parent_map=None):
    """Index all automatic source memberships once for shadow synchronization."""
    parent_map = parent_map if parent_map is not None else _collection_parent_map(scene)
    result = {}

    def add(kind, key, rig):
        key = str(key or "")
        if key:
            result.setdefault((kind, key), []).append(rig)

    for rig in rigs:
        add(
            'LAYER',
            getattr(rig, "fbp_compositor_source_id", ""),
            rig,
        )
        tag = str(getattr(rig, "fbp_color_tag", 'NONE') or 'NONE').upper()
        if tag not in FBP_COMPOSITOR_TAG_LABELS:
            tag = 'NONE'
        add('TAG', tag, rig)

        physical = _physical_fbp_collection(rig, scene)
        add(
            'COLLECTION',
            getattr(physical, "fbp_compositor_source_id", "") if physical else "",
            rig,
        )

        collection = _primary_collection(rig)
        visited = set()
        while collection is not None:
            try:
                pointer = int(collection.as_pointer())
            except FBP_DATA_ERRORS:
                break
            if pointer in visited:
                break
            visited.add(pointer)
            add(
                'GROUP',
                getattr(collection, "fbp_compositor_source_id", ""),
                rig,
            )
            collection = parent_map.get(pointer)
    return {key: tuple(value) for key, value in result.items()}


def _owned_object_index(scene, rigs):
    """Map each rig to its renderable hierarchy in one Scene pass."""
    rigs = tuple(rig for rig in rigs if rig is not None)
    rig_by_pointer = {}
    target_owner = {}
    result = {}
    for rig in rigs:
        try:
            rig_pointer = int(rig.as_pointer())
            rig_by_pointer[rig_pointer] = rig
            result[rig_pointer] = {}
            for candidate in (
                getattr(rig, "fbp_plane_target", None),
                getattr(rig, "fbp_gp_canvas", None),
            ):
                if candidate is None:
                    continue
                candidate_pointer = int(candidate.as_pointer())
                target_owner[candidate_pointer] = rig_pointer
                if not bool(getattr(candidate, "hide_render", False)):
                    result[rig_pointer][candidate_pointer] = candidate
        except FBP_DATA_ERRORS:
            continue

    for obj in tuple(getattr(scene, "objects", ()) or ()):
        try:
            if bool(getattr(obj, "is_fbp_control", False)):
                continue
            if bool(getattr(obj, "hide_render", False)):
                continue
            obj_pointer = int(obj.as_pointer())
        except FBP_DATA_ERRORS:
            continue
        current = obj
        visited = set()
        owner_pointer = target_owner.get(obj_pointer)
        while owner_pointer is None and current is not None:
            try:
                pointer = int(current.as_pointer())
            except FBP_DATA_ERRORS:
                break
            if pointer in rig_by_pointer:
                owner_pointer = pointer
                break
            if pointer in target_owner:
                owner_pointer = target_owner[pointer]
                break
            if pointer in visited:
                break
            visited.add(pointer)
            try:
                current = getattr(current, "parent", None)
            except FBP_DATA_ERRORS:
                break
        if owner_pointer in result:
            result[owner_pointer][obj_pointer] = obj
    return {
        pointer: tuple(objects.values())
        for pointer, objects in result.items()
    }


def _objects_owned_by_rigs(scene, rigs, owned_index=None):
    rigs = tuple(rig for rig in rigs if rig is not None)
    owned_index = owned_index if owned_index is not None else _owned_object_index(
        scene, rigs
    )
    result = {}
    for rig in rigs:
        try:
            for obj in owned_index.get(int(rig.as_pointer()), ()):
                result[int(obj.as_pointer())] = obj
        except FBP_DATA_ERRORS:
            continue
    return tuple(result.values())


def _item_by_id(scene, layer_id):
    layer_id = str(layer_id or "")
    return next(
        (item for item in scene.fbp_compositor_layers if item.layer_id == layer_id),
        None,
    )


def _is_folder_item(item):
    return str(getattr(item, "row_type", 'LAYER') or 'LAYER') == 'FOLDER'


def _render_layer_items(scene):
    return tuple(
        item for item in scene.fbp_compositor_layers
        if not _is_folder_item(item)
    )


def _folder_item_by_id(scene, folder_id):
    folder_id = str(folder_id or "")
    if not folder_id:
        return None
    return next(
        (
            item for item in scene.fbp_compositor_layers
            if _is_folder_item(item) and item.layer_id == folder_id
        ),
        None,
    )


def _item_effective_enabled(scene, item):
    if not bool(getattr(item, "enabled", True)):
        return False
    folder = _folder_item_by_id(
        scene, str(getattr(item, "parent_folder_id", "") or "")
    )
    return bool(folder is None or getattr(folder, "enabled", True))


def _ensure_item_id(item):
    if not str(getattr(item, "layer_id", "") or ""):
        item.layer_id = _new_id()
    return item.layer_id


def _ensure_compositor_layer_ids(scene):
    return ensure_unique_item_identities(scene.fbp_compositor_layers, "layer_id")


def _ensure_compositor_effect_ids(item):
    return ensure_unique_item_identities(item.effects, "effect_uuid")


def _normalize_layer_effect_stack(item):
    """Repair persistent identities in the current compositor effect stack."""
    return bool(_ensure_compositor_effect_ids(item))


def _layer_uses_depth(item):
    if bool(getattr(item, "use_depth", False)):
        return True
    _normalize_layer_effect_stack(item)
    return any(
        effect.enabled and effect.effect_type == 'DEFOCUS'
        for effect in item.effects
    )


def _unique_view_layer_name(scene, item):
    requested = _clean_name(getattr(item, "view_layer_name", ""), "")
    if not requested:
        requested = f"FBP • {_clean_name(item.name)}"
    current_id = _ensure_item_id(item)
    existing = next(
        (
            layer for layer in scene.view_layers
            if str(layer.get(FBP_COMPOSITOR_LAYER_TAG, "") or "") == current_id
        ),
        None,
    )
    used = {layer.name for layer in scene.view_layers if layer != existing}
    base = requested[:63]
    candidate = base
    suffix = 2
    while candidate in used:
        tail = f" {suffix}"
        candidate = f"{base[:63 - len(tail)]}{tail}"
        suffix += 1
    item.view_layer_name = candidate
    return candidate


def _ensure_shadow_root(scene):
    scene_token = _scene_id(scene)
    for collection in _walk_collections(scene.collection):
        if (
            bool(collection.get(FBP_COMPOSITOR_ROOT_TAG, False))
            and str(collection.get("fbp_compositor_scene_id", "") or "") == scene_token
        ):
            return collection
    root = bpy.data.collections.new(f"FBP Compositor Sources • {_clean_name(scene.name)}")
    root[FBP_COMPOSITOR_ROOT_TAG] = True
    root["fbp_compositor_scene_id"] = scene_token
    scene.collection.children.link(root)
    return root


def _shadow_child_by_id(root, layer_id):
    return next(
        (
            child for child in root.children
            if str(child.get(FBP_COMPOSITOR_LAYER_TAG, "") or "") == layer_id
        ),
        None,
    )


def _ensure_shadow_child(root, item):
    layer_id = _ensure_item_id(item)
    child = _shadow_child_by_id(root, layer_id)
    if child is None:
        child = bpy.data.collections.new(f"FBP Source • {_clean_name(item.name)}")
        child[FBP_COMPOSITOR_SHADOW_TAG] = True
        child[FBP_COMPOSITOR_LAYER_TAG] = layer_id
        root.children.link(child)
    else:
        child.name = f"FBP Source • {_clean_name(item.name)}"
    return child


def _objects_for_layer_source(collection, target_id, seen_collections=None):
    """Yield objects while stopping at child groups assigned to another output."""
    seen_collections = seen_collections if seen_collections is not None else set()
    pointer = collection.as_pointer()
    if pointer in seen_collections:
        return
    seen_collections.add(pointer)
    for obj in collection.objects:
        yield obj
    for child in collection.children:
        assigned = str(getattr(child, "fbp_compositor_layer_id", "") or "")
        if assigned and assigned != target_id:
            continue
        yield from _objects_for_layer_source(child, target_id, seen_collections)


def _sync_shadow_collections(scene, root):
    render_items = _render_layer_items(scene)
    active_ids = {_ensure_item_id(item) for item in render_items}
    groups = fbp_compositor_group_collections(scene)
    rigs = _scene_fbp_rigs(scene)
    parent_map = _collection_parent_map(scene)
    source_rig_index = _source_rig_index(scene, rigs, parent_map)
    owned_object_index = _owned_object_index(scene, rigs)
    unassigned = [
        collection for collection in groups
        if not str(getattr(collection, "fbp_compositor_layer_id", "") or "")
    ]
    for item in render_items:
        target_id = item.layer_id
        shadow = _ensure_shadow_child(root, item)
        for obj in tuple(shadow.objects):
            shadow.objects.unlink(obj)
        objects = {}
        source_kind = str(getattr(item, "source_kind", 'MANUAL') or 'MANUAL')
        if source_kind != 'MANUAL':
            source_rigs = source_rig_index.get((
                source_kind,
                str(getattr(item, "source_key", "") or ""),
            ), ())
            for obj in _objects_owned_by_rigs(
                scene, source_rigs, owned_object_index
            ):
                objects[obj.as_pointer()] = obj
            if source_kind == 'COLLECTION' and not source_rigs:
                collection = _collection_by_source_id(
                    scene, str(getattr(item, "source_key", "") or "")
                )
                if collection is not None:
                    for obj in _objects_for_layer_source(collection, target_id):
                        objects[obj.as_pointer()] = obj
        else:
            sources = [
                collection for collection in groups
                if str(getattr(collection, "fbp_compositor_layer_id", "") or "") == target_id
            ]
            if bool(scene.fbp_compositor_include_unassigned):
                sources.extend(unassigned)
            for source in sources:
                for obj in _objects_for_layer_source(source, target_id):
                    objects[obj.as_pointer()] = obj

            # Ctrl+G groups are virtual: resolve their Layer List membership
            # from each rig's canonical collection hint, then link the owned
            # render hierarchy into the same shadow source.
            virtual_rigs = []
            for rig in rigs:
                collection = _primary_collection(rig)
                assigned = ""
                visited = set()
                while collection is not None:
                    pointer = int(collection.as_pointer())
                    if pointer in visited:
                        break
                    visited.add(pointer)
                    assigned = str(
                        getattr(collection, "fbp_compositor_layer_id", "") or ""
                    )
                    if assigned:
                        break
                    collection = parent_map.get(pointer)
                if assigned == target_id or (
                    not assigned and bool(scene.fbp_compositor_include_unassigned)
                ):
                    virtual_rigs.append(rig)
            for obj in _objects_owned_by_rigs(
                scene, virtual_rigs, owned_object_index
            ):
                objects[obj.as_pointer()] = obj
        for obj in objects.values():
            shadow.objects.link(obj)

    for child in tuple(root.children):
        child_id = str(child.get(FBP_COMPOSITOR_LAYER_TAG, "") or "")
        if bool(child.get(FBP_COMPOSITOR_SHADOW_TAG, False)) and child_id not in active_ids:
            root.children.unlink(child)
            bpy.data.collections.remove(child)


def _set_layer_collection_visibility(scene, view_layer, shadow_root, item):
    """Include one shadow source and exclude original FBP collection branches."""
    shadow_pointer = shadow_root.as_pointer()
    target_id = _ensure_item_id(item)
    folder = _folder_item_by_id(
        scene, str(getattr(item, "parent_folder_id", "") or "")
    )
    holdout = bool(getattr(item, "holdout", False)) or bool(
        folder is not None and getattr(folder, "holdout", False)
    )
    indirect_only = (
        bool(getattr(item, "indirect_only", False))
        or bool(folder is not None and getattr(folder, "indirect_only", False))
    ) and not holdout

    def visit(layer_collection, inside_shadow=False):
        collection = layer_collection.collection
        pointer = collection.as_pointer()
        if pointer == shadow_pointer:
            layer_collection.exclude = False
            for child in layer_collection.children:
                child_id = str(child.collection.get(FBP_COMPOSITOR_LAYER_TAG, "") or "")
                child.exclude = child_id != target_id
                if not child.exclude:
                    try:
                        child.holdout = holdout
                        child.indirect_only = indirect_only
                    except FBP_DATA_ERRORS:
                        pass
                    for descendant in _walk_layer_collections(child):
                        descendant.exclude = False
            return
        if bool(getattr(collection, "is_fbp_collection", False)):
            layer_collection.exclude = True
            return
        layer_collection.exclude = False
        for child in layer_collection.children:
            visit(child, inside_shadow)

    visit(view_layer.layer_collection)


def _managed_view_layer(scene, layer_id):
    return next(
        (
            layer for layer in scene.view_layers
            if str(layer.get(FBP_COMPOSITOR_LAYER_TAG, "") or "") == layer_id
        ),
        None,
    )


def _sync_view_layers(scene, shadow_root):
    render_items = _render_layer_items(scene)
    active_ids = {_ensure_item_id(item) for item in render_items}
    for item in render_items:
        layer = _managed_view_layer(scene, item.layer_id)
        name = _unique_view_layer_name(scene, item)
        if layer is None:
            layer = scene.view_layers.new(name)
            layer[FBP_COMPOSITOR_LAYER_TAG] = item.layer_id
        elif layer.name != name:
            layer.name = name
        layer.use = _item_effective_enabled(scene, item)
        folder = _folder_item_by_id(
            scene, str(getattr(item, "parent_folder_id", "") or "")
        )
        layer.use_pass_z = _layer_uses_depth(item) or bool(
            folder is not None and _layer_uses_depth(folder)
        )
        _set_layer_collection_visibility(scene, layer, shadow_root, item)

    for layer in tuple(scene.view_layers):
        layer_id = str(layer.get(FBP_COMPOSITOR_LAYER_TAG, "") or "")
        if layer_id and layer_id not in active_ids and len(scene.view_layers) > 1:
            scene.view_layers.remove(layer)

    for layer in scene.view_layers:
        if str(layer.get(FBP_COMPOSITOR_LAYER_TAG, "") or ""):
            continue
        # Shadow links exist only to isolate managed renders. Excluding their
        # root from native View Layers prevents a hidden FBP group from leaking
        # back into the artist's normal viewport through the extra link.
        for layer_collection in _walk_layer_collections(layer.layer_collection):
            if layer_collection.collection == shadow_root:
                layer_collection.exclude = True
                break
        if "fbp_compositor_original_use" not in layer:
            layer["fbp_compositor_original_use"] = bool(layer.use)
        if bool(scene.fbp_compositor_disable_unmanaged_layers):
            layer.use = False
        else:
            layer.use = bool(layer.get("fbp_compositor_original_use", True))


def _socket(node, name, occurrence=0):
    matches = [item for item in node.inputs if item.name == name]
    return matches[occurrence] if 0 <= occurrence < len(matches) else None


def _set_socket(node, name, value, occurrence=None):
    matches = [item for item in node.inputs if item.name == name]
    if occurrence is not None:
        matches = matches[occurrence:occurrence + 1]
    success = False
    for socket in matches:
        try:
            socket.default_value = value
            success = True
        except FBP_DATA_ERRORS:
            pass
    return success


def _blend_effect(tree, original, processed, mix, x, y, persistent_id=""):
    # Keep the mix node for every effect.  A fixed topology lets parameter
    # edits update one socket instead of rebuilding the compositor graph.
    blend = tree.nodes.new("CompositorNodeAlphaOver")
    _tag_node(blend, "source_effect_mix", persistent_id)
    blend.label = "FBP Effect Mix"
    blend.name = f"FBP FX Mix {persistent_id}"
    blend.location = (x, y)
    _set_socket(blend, "Factor", float(mix))
    tree.links.new(original, _socket(blend, "Background"))
    tree.links.new(processed, _socket(blend, "Foreground"))
    return blend.outputs["Image"]


def _compositor_asset_library_path():
    candidates = []
    for resource_kind in ('LOCAL', 'SYSTEM'):
        try:
            root = bpy.utils.resource_path(resource_kind)
        except FBP_DATA_ERRORS:
            root = ""
        if root:
            candidates.append(os.path.join(
                root, "datafiles", "assets", "nodes",
                "compositing_nodes_essentials.blend",
            ))
    try:
        candidates.append(os.path.join(
            os.path.dirname(bpy.app.binary_path),
            f"{bpy.app.version[0]}.{bpy.app.version[1]}",
            "datafiles", "assets", "nodes",
            "compositing_nodes_essentials.blend",
        ))
    except FBP_DATA_ERRORS:
        pass
    return next((path for path in candidates if os.path.isfile(path)), "")


def _ensure_compositor_asset_group(asset_name):
    for group in tuple(getattr(bpy.data, "node_groups", ()) or ()):
        try:
            if (
                getattr(group, "bl_idname", "") == "CompositorNodeTree"
                and str(group.get(FBP_COMPOSITOR_ASSET_TAG, "") or "") == asset_name
            ):
                return group
        except FBP_DATA_ERRORS:
            continue
    path = _compositor_asset_library_path()
    if not path:
        raise RuntimeError(
            "Blender 5.2 compositor essentials asset library was not found"
        )
    with bpy.data.libraries.load(path, link=False, assets_only=True) as (source, target):
        if asset_name not in source.node_groups:
            raise RuntimeError(
                f"Blender 5.2 compositor asset is unavailable: {asset_name}"
            )
        target.node_groups = [asset_name]
    group = target.node_groups[0] if target.node_groups else None
    if group is None:
        raise RuntimeError(f"Could not load compositor asset: {asset_name}")
    group[FBP_COMPOSITOR_ASSET_TAG] = asset_name
    return group


def _asset_effect_node(tree, asset_name, settings):
    node = tree.nodes.new("CompositorNodeGroup")
    node.node_tree = _ensure_compositor_asset_group(asset_name)
    for socket_name, value in settings.items():
        _set_socket(node, socket_name, value)
    return node


def _cleanup_unused_compositor_asset_groups():
    for group in tuple(getattr(bpy.data, "node_groups", ()) or ()):
        try:
            if (
                str(group.get(FBP_COMPOSITOR_ASSET_TAG, "") or "")
                and int(getattr(group, "users", 0) or 0) == 0
            ):
                bpy.data.node_groups.remove(group)
        except FBP_DATA_ERRORS:
            continue


def _effect_output(
    tree, layer_item, effect, render_layers, image_socket, x, y, effect_index,
    *, scene=None, depth_socket=None,
):
    effect_type = str(effect.effect_type or 'NONE')
    if effect_type == 'NONE':
        return image_socket, x
    input_name = "Image"
    output_name = "Image"
    if effect_type == 'GLOW':
        node = tree.nodes.new("CompositorNodeGlare")
        _set_socket(node, "Type", "Fog Glow")
        _set_socket(node, "Quality", "High")
        _set_socket(node, "Threshold", effect.glow_threshold)
        _set_socket(node, "Strength", effect.glow_strength)
        _set_socket(node, "Size", effect.glow_size)
    elif effect_type == 'BLUR':
        node = tree.nodes.new("CompositorNodeBlur")
        _set_socket(node, "Type", "Gaussian")
        _set_socket(node, "Size", (effect.blur_size, effect.blur_size))
    elif effect_type == 'DEFOCUS':
        node = tree.nodes.new("CompositorNodeDefocus")
        node.use_zbuffer = True
        node.scene = getattr(render_layers, "scene", None) or scene
        node.f_stop = effect.defocus_f_stop
        node.blur_max = float(effect.defocus_blur_max)
        depth = (
            render_layers.outputs.get("Depth")
            if render_layers is not None else depth_socket
        )
        if depth is not None:
            tree.links.new(depth, node.inputs["Z"])
    elif effect_type == 'COLOR_GRADE':
        node = tree.nodes.new("CompositorNodeColorBalance")
        _set_socket(node, "Type", "Offset/Power/Slope (ASC-CDL)")
        _set_socket(node, "Temperature", effect.color_temperature)
        _set_socket(node, "Tint", effect.color_tint)
    elif effect_type == 'PIXELATE':
        node = tree.nodes.new("CompositorNodePixelate")
        input_name = "Color"
        output_name = "Color"
        _set_socket(node, "Size", int(effect.pixel_size))
    elif effect_type == 'VIGNETTE':
        scale = float(effect.vignette_scale)
        node = _asset_effect_node(tree, "Vignette", {
            "Factor": float(effect.vignette_factor),
            "Feather": float(effect.vignette_feather),
            "Corner Roundness": float(effect.vignette_roundness),
            "Scale": (scale, scale, 0.0),
        })
    elif effect_type == 'UNSHARP_MASK':
        node = _asset_effect_node(tree, "Unsharp Mask", {
            "Radius": float(effect.unsharp_radius),
            "Factor": float(effect.unsharp_factor),
            "Threshold": float(effect.unsharp_threshold),
        })
        output_name = "Result"
    elif effect_type == 'TUNE_IMAGE':
        node = _asset_effect_node(tree, "Tune Image", {
            "Contrast": float(effect.tune_contrast),
            "Color Boost": float(effect.tune_color_boost),
            "Clarity": float(effect.tune_clarity),
            "Detail": float(effect.tune_detail),
            "Sharpen": float(effect.tune_sharpen),
            "Preserve Colors": True,
        })
    elif effect_type == 'FILM_GRAIN':
        node = _asset_effect_node(tree, "Film Grain", {
            "Factor": float(effect.film_grain_factor),
            "Animated": bool(effect.film_grain_animated),
            "ISO": int(effect.film_grain_iso),
            "Softness": float(effect.film_grain_softness),
            "Coarseness": float(effect.film_grain_coarseness),
        })
        input_name = "Input"
        output_name = "Result"
    elif effect_type == 'CHROMATIC_ABERRATION':
        node = _asset_effect_node(tree, "Chromatic Aberration", {
            "Factor": float(effect.chromatic_factor),
            "Samples": int(effect.chromatic_samples),
            "Fit": bool(effect.chromatic_fit),
        })
    elif effect_type == 'SEPIA':
        node = _asset_effect_node(tree, "Sepia", {
            "Contrast": float(effect.sepia_contrast),
            "Tone": float(effect.sepia_tone),
            "Saturation": float(effect.sepia_saturation),
        })
    else:
        return image_socket, x
    effect_label = {
        identifier: label
        for identifier, label, _description in FBP_COMPOSITOR_EFFECT_ITEMS
    }.get(effect_type, effect_type.replace('_', ' ').title())
    node.name = f"FBP FX {layer_item.layer_id[:8]} {effect_index:02d} {effect_type}"
    node.label = f"FBP • {layer_item.name} • {effect_label}"
    node.location = (x, y)
    effect_input = node.inputs.get(input_name)
    effect_output = node.outputs.get(output_name)
    if effect_input is None or effect_output is None:
        raise RuntimeError(f"Invalid {effect_label} compositor asset interface")
    tree.links.new(image_socket, effect_input)
    _tag_node(node, "source_effect", f"{layer_item.layer_id}:effect:{effect_index}")
    node["fbp_layer_id"] = layer_item.layer_id
    node["fbp_effect_index"] = effect_index
    processed = _blend_effect(
        tree,
        image_socket,
        effect_output,
        effect.effect_mix,
        x + 220,
        y,
        f"{layer_item.layer_id}:effect:{effect_index}:mix",
    )
    return processed, x + 460


def _layer_effect_output(
    tree, item, render_layers, image_socket, x, y, *, scene=None, depth_socket=None
):
    _normalize_layer_effect_stack(item)
    current = image_socket
    next_x = x
    for index, effect in enumerate(item.effects):
        if not effect.enabled or effect.effect_type == 'NONE':
            continue
        current, next_x = _effect_output(
            tree,
            item,
            effect,
            render_layers,
            current,
            next_x,
            y,
            index,
            scene=scene,
            depth_socket=depth_socket,
        )
    return current, next_x


def _clear_tree(tree):
    tree.nodes.clear()
    try:
        tree.interface.clear()
    except FBP_DATA_ERRORS:
        for item in reversed(tuple(tree.interface.items_tree)):
            try:
                tree.interface.remove(item)
            except FBP_DATA_ERRORS:
                pass


def _clear_managed_outer_nodes(tree):
    """Remove tagged Frame By Plane technical nodes, preserving artist nodes."""
    for node in tuple(tree.nodes):
        role = _fbp_root_node_role(node)
        if role.startswith("legacy_"):
            tree.nodes.remove(node)


def _tag_node(node, role, persistent_id=""):
    node["fbp_owned"] = True
    node["fbp_role"] = role
    node["fbp_uuid"] = str(persistent_id or _new_id())
    node["fbp_version"] = 2
    return node


def _owned_tree(scene):
    token = _scene_id(scene)
    current = scene.compositing_node_group
    if (
        current is not None
        and bool(current.get(FBP_COMPOSITOR_TREE_TAG, False))
        and str(current.get("fbp_compositor_scene_id", "") or "") == token
    ):
        return current
    for tree in bpy.data.node_groups:
        if (
            getattr(tree, "bl_idname", "") == "CompositorNodeTree"
            and bool(tree.get(FBP_COMPOSITOR_TREE_TAG, False))
            and str(tree.get("fbp_compositor_scene_id", "") or "") == token
        ):
            return tree
    tree = bpy.data.node_groups.new(
        f"FBP Compositor • {_clean_name(scene.name)}", "CompositorNodeTree"
    )
    tree[FBP_COMPOSITOR_TREE_TAG] = True
    tree["fbp_compositor_scene_id"] = token
    return tree


def _owned_source_tree(scene):
    token = _scene_id(scene)
    tree = next(
        (
            candidate for candidate in bpy.data.node_groups
            if getattr(candidate, "bl_idname", "") == "CompositorNodeTree"
            and bool(candidate.get(FBP_COMPOSITOR_SOURCE_TREE_TAG, False))
            and str(candidate.get("fbp_compositor_scene_id", "") or "") == token
        ),
        None,
    )
    if tree is None:
        tree = bpy.data.node_groups.new(
            f"FBP Layers - {_clean_name(scene.name)}",
            "CompositorNodeTree",
        )
    tree[FBP_COMPOSITOR_SOURCE_TREE_TAG] = True
    tree["fbp_compositor_scene_id"] = token
    tree["fbp_owned"] = True
    tree["fbp_role"] = "layers_package"
    tree["fbp_uuid"] = token
    tree["fbp_version"] = 3
    return tree


def _ensure_group_interface_socket(tree, name, in_out, socket_type):
    socket = next(
        (
            item for item in tree.interface.items_tree
            if getattr(item, "item_type", "") == 'SOCKET'
            and getattr(item, "in_out", "") == in_out
            and item.name == name
        ),
        None,
    )
    return socket or tree.interface.new_socket(
        name=name,
        in_out=in_out,
        socket_type=socket_type,
    )


def fbp_ensure_native_render_output(scene, tree=None):
    """Ensure the scene compositor exposes one active renderable Image output.

    Blender's native Render Image command requires a real active Group Output
    (or a File Output). FBP always restores the non-destructive Group Output so
    F12 works even after an interrupted sync, Undo, or manual node deletion.
    """
    if scene is None:
        return None
    tree = tree or getattr(scene, "compositing_node_group", None)
    if tree is None or getattr(tree, "bl_idname", "") != "CompositorNodeTree":
        return None
    try:
        image_interface = _ensure_group_interface_socket(
            tree, "Image", "OUTPUT", "NodeSocketColor"
        )
        outputs = [
            node for node in tree.nodes
            if getattr(node, "bl_idname", "") == "NodeGroupOutput"
        ]
        output = next(
            (
                node for node in outputs
                if bool(getattr(node, "is_active_output", False))
                and node.inputs.get("Image") is not None
            ),
            None,
        )
        output = output or next(
            (
                node for node in outputs
                if node.inputs.get("Image") is not None
                and (
                    str(getattr(node, "name", "") or "") == "FBP Composite Output"
                    or _fbp_root_node_role(node) == "legacy_group_output"
                )
            ),
            None,
        )
        output = output or next(
            (node for node in outputs if node.inputs.get("Image") is not None),
            None,
        )
        if output is None:
            output = _tag_node(
                tree.nodes.new("NodeGroupOutput"), "legacy_group_output"
            )
        output.name = "FBP Composite Output"
        output.label = "Output"
        output.hide = False
        output.location.x = max(930.0, float(getattr(output.location, "x", 930.0)))
        for candidate in outputs:
            candidate.is_active_output = candidate is output
        output.is_active_output = True

        image_input = next(
            (
                socket for socket in output.inputs
                if str(getattr(socket, "identifier", "") or "")
                == str(getattr(image_interface, "identifier", "") or "")
            ),
            None,
        ) or output.inputs.get("Image")
        if image_input is None:
            return None

        if not bool(getattr(image_input, "is_linked", False)):
            source = None
            for role, socket_names in (
                ("output", ("Image", "Beauty")),
                ("effects_stage", ("Image",)),
                ("layers_package", ("TOT", "Image")),
            ):
                node = next(
                    (
                        candidate for candidate in tree.nodes
                        if candidate is not output
                        and _fbp_root_node_role(candidate) == role
                    ),
                    None,
                )
                if node is None:
                    continue
                source = next(
                    (node.outputs.get(name) for name in socket_names if node.outputs.get(name)),
                    None,
                )
                if source is not None:
                    break
            if source is not None:
                _replace_socket_input_link(tree, source, image_input)

        tree.update_tag()
        scene.update_tag()
        return output
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None


def _owned_effects_tree(scene):
    """Return and safely repair the user-editable Effects / Masks stage."""
    token = _scene_id(scene)
    tree = next(
        (
            candidate for candidate in bpy.data.node_groups
            if getattr(candidate, "bl_idname", "") == "CompositorNodeTree"
            and bool(candidate.get(FBP_COMPOSITOR_EFFECTS_TREE_TAG, False))
            and str(candidate.get("fbp_compositor_scene_id", "") or "") == token
        ),
        None,
    )
    if tree is None:
        tree = bpy.data.node_groups.new(
            f"FBP Effects & Masks - {_clean_name(scene.name)}",
            "CompositorNodeTree",
        )
    tree[FBP_COMPOSITOR_EFFECTS_TREE_TAG] = True
    tree["fbp_compositor_scene_id"] = token
    tree["fbp_owned"] = True
    tree["fbp_role"] = "effects_stage"
    tree["fbp_version"] = 1

    image_in = _ensure_group_interface_socket(tree, "Image", 'INPUT', 'NodeSocketColor')
    mask_in = _ensure_group_interface_socket(tree, "Mask", 'INPUT', 'NodeSocketFloat')
    image_out = _ensure_group_interface_socket(tree, "Image", 'OUTPUT', 'NodeSocketColor')
    mask_out = _ensure_group_interface_socket(tree, "Mask", 'OUTPUT', 'NodeSocketFloat')
    group_in = next((node for node in tree.nodes if node.bl_idname == 'NodeGroupInput'), None)
    if group_in is None:
        group_in = tree.nodes.new("NodeGroupInput")
    group_in.name = "FBP Effects Inputs"
    group_in.location = (-260, 0)
    group_out = next(
        (
            node for node in tree.nodes
            if node.bl_idname == 'NodeGroupOutput' and bool(node.is_active_output)
        ),
        None,
    )
    if group_out is None:
        group_out = tree.nodes.new("NodeGroupOutput")
        group_out.is_active_output = True
    group_out.name = "FBP Effects Outputs"
    group_out.location.x = max(260, group_out.location.x)

    image_target = next(
        (socket for socket in group_out.inputs if socket.identifier == image_out.identifier),
        None,
    )
    mask_target = next(
        (socket for socket in group_out.inputs if socket.identifier == mask_out.identifier),
        None,
    )
    image_source = next(
        (socket for socket in group_in.outputs if socket.identifier == image_in.identifier),
        None,
    )
    mask_source = next(
        (socket for socket in group_in.outputs if socket.identifier == mask_in.identifier),
        None,
    )
    if image_target is not None and not image_target.is_linked and image_source is not None:
        tree.links.new(image_source, image_target)
    if mask_target is not None and not mask_target.is_linked and mask_source is not None:
        tree.links.new(mask_source, mask_target)
    return tree



def _unique_socket_name(item, used, prefix=""):
    base = _clean_name(f"{prefix}{item.name}", "Layer")[:52]
    candidate = base
    suffix = 2
    while candidate in used:
        tail = f" {suffix}"
        candidate = f"{base[:52 - len(tail)]}{tail}"
        suffix += 1
    used.add(candidate)
    item.output_socket_name = candidate
    return candidate


def _opacity_output(tree, image_socket, factor, x, y, label, persistent_id=""):
    if not hasattr(factor, "bl_idname") and float(factor) >= 0.999:
        return image_socket
    transparent = tree.nodes.new("CompositorNodeRGB")
    _tag_node(transparent, "source_transparent", persistent_id)
    transparent.label = f"{label} Transparent"
    transparent.location = (x, y - 90)
    transparent.outputs[0].default_value = (0.0, 0.0, 0.0, 0.0)
    over = tree.nodes.new("CompositorNodeAlphaOver")
    _tag_node(over, "source_opacity", persistent_id)
    over.label = f"{label} Opacity"
    over.location = (x + 180, y)
    tree.links.new(transparent.outputs[0], over.inputs["Background"])
    tree.links.new(image_socket, over.inputs["Foreground"])
    if hasattr(factor, "bl_idname"):
        tree.links.new(factor, over.inputs["Factor"])
    else:
        _set_socket(over, "Factor", float(factor))
    return over.outputs["Image"]


def _build_source_group(scene):
    """Build one real compositor node group containing every FBP source.

    This is the equivalent of selecting the generated Render Layers, per-layer
    effects, folder composites and package Alpha Over nodes and pressing
    ``Ctrl+G``.  The scene compositor root therefore exposes one artist-facing
    FBP Layers node instead of a hidden stack of root-level technical nodes.
    """
    source = _owned_source_tree(scene)
    _clear_tree(source)
    render_items = list(_render_layer_items(scene))
    folders = [item for item in scene.fbp_compositor_layers if _is_folder_item(item)]
    used_names = {"TOT", "MASK"}

    total_output_name = "TOT"
    mask_output_name = "MASK"
    source.interface.new_socket(
        name=total_output_name, in_out='OUTPUT', socket_type='NodeSocketColor'
    )
    source.interface.new_socket(
        name=mask_output_name, in_out='OUTPUT', socket_type='NodeSocketFloat'
    )
    output_names = {}
    for item in scene.fbp_compositor_layers:
        name = _unique_socket_name(
            item, used_names, prefix="Folder - " if _is_folder_item(item) else ""
        )
        source.interface.new_socket(
            name=name, in_out='OUTPUT', socket_type='NodeSocketColor'
        )
        output_names[item.layer_id] = name

    group_output = source.nodes.new("NodeGroupOutput")
    group_output.name = "FBP Layer Outputs"
    group_output.label = "Layer and Folder Outputs"
    group_output.is_active_output = True

    images = {}
    depth_sockets = {}
    maximum_effects = max(
        (
            sum(
                1 for effect in item.effects
                if effect.enabled and effect.effect_type != 'NONE'
            )
            for item in scene.fbp_compositor_layers
        ),
        default=0,
    )
    output_x = 260 + maximum_effects * 460
    group_output.location = (output_x + 900, 0)

    for index, item in enumerate(render_items):
        y = -index * 280
        render_layers = source.nodes.new("CompositorNodeRLayers")
        _tag_node(render_layers, "source_render_layer", item.layer_id)
        render_layers.name = f"FBP Source - {item.layer_id[:8]}"
        render_layers.label = item.name
        render_layers.scene = scene
        render_layers.layer = item.view_layer_name
        render_layers.location = (-980, y)
        render_layers.width = 180
        image_socket = render_layers.outputs.get("Image")
        depth_socket = render_layers.outputs.get("Depth")
        if image_socket is None:
            continue
        image, layer_output_x = _layer_effect_output(
            source,
            item,
            render_layers,
            image_socket,
            -700,
            y,
            scene=scene,
            depth_socket=depth_socket,
        )
        image = _opacity_output(
            source,
            image,
            float(item.opacity) if _item_effective_enabled(scene, item) else 0.0,
            max(layer_output_x, 20),
            y,
            item.name,
            item.layer_id,
        )
        images[item.layer_id] = image
        depth_sockets[item.layer_id] = depth_socket
        target = group_output.inputs.get(output_names.get(item.layer_id, ""))
        if target is not None:
            source.links.new(image, target)

    for folder_index, folder in enumerate(folders):
        children = [
            item for item in render_items
            if str(getattr(item, "parent_folder_id", "") or "") == folder.layer_id
            and _item_effective_enabled(scene, item)
        ]
        combined = None
        nearest_child = children[0] if children else None
        y = -(len(render_items) + folder_index) * 280
        # The Layer List is front-to-back. Alpha Over is assembled from the
        # back so the first row remains visually nearest to the camera.
        for child_index, child in enumerate(reversed(children)):
            child_image = images.get(child.layer_id)
            if child_image is None:
                continue
            if combined is None:
                combined = child_image
                continue
            over = source.nodes.new("CompositorNodeAlphaOver")
            _tag_node(over, "folder_alpha_over", f"{folder.layer_id}:{child.layer_id}")
            over.label = f"{folder.name} - {child.name}"
            over.location = (output_x, y - child_index * 90)
            _set_socket(over, "Factor", 1.0)
            source.links.new(combined, over.inputs["Background"])
            source.links.new(child_image, over.inputs["Foreground"])
            combined = over.outputs["Image"]
        if combined is None:
            transparent = source.nodes.new("CompositorNodeRGB")
            _tag_node(transparent, "folder_empty", folder.layer_id)
            transparent.outputs[0].default_value = (0.0, 0.0, 0.0, 0.0)
            transparent.location = (output_x, y)
            combined = transparent.outputs[0]
        elif folder.effects:
            combined, _folder_x = _layer_effect_output(
                source,
                folder,
                None,
                combined,
                output_x + 220,
                y,
                scene=scene,
                depth_socket=(
                    depth_sockets.get(nearest_child.layer_id)
                    if nearest_child is not None else None
                ),
            )
        combined = _opacity_output(
            source,
            combined,
            float(folder.opacity) if folder.enabled else 0.0,
            output_x + 440,
            y,
            folder.name,
            folder.layer_id,
        )
        images[folder.layer_id] = combined
        target = group_output.inputs.get(output_names.get(folder.layer_id, ""))
        if target is not None:
            source.links.new(combined, target)

    folder_ids = {item.layer_id for item in folders}
    package_items = [
        item for item in scene.fbp_compositor_layers
        if bool(getattr(item, "enabled", True))
        and (
            _is_folder_item(item)
            or str(getattr(item, "parent_folder_id", "") or "") not in folder_ids
        )
    ]
    package = None
    package_y = -(len(render_items) + len(folders) + 1) * 280
    for stack_index, item in enumerate(reversed(package_items)):
        image = images.get(item.layer_id)
        if image is None:
            continue
        if package is None:
            package = image
            continue
        over = source.nodes.new("CompositorNodeAlphaOver")
        _tag_node(over, "package_alpha_over", item.layer_id)
        over.label = f"Package - {item.name}"
        over.location = (output_x + 520, package_y - stack_index * 90)
        _set_socket(over, "Factor", 1.0)
        source.links.new(package, over.inputs["Background"])
        source.links.new(image, over.inputs["Foreground"])
        package = over.outputs["Image"]
    if package is None:
        transparent = source.nodes.new("CompositorNodeRGB")
        _tag_node(transparent, "package_empty", _scene_id(scene))
        transparent.label = "Empty Package"
        transparent.location = (output_x + 520, package_y)
        transparent.outputs[0].default_value = (0.0, 0.0, 0.0, 0.0)
        package = transparent.outputs[0]

    total_target = group_output.inputs.get(total_output_name)
    if total_target is not None:
        source.links.new(package, total_target)
    separate = source.nodes.new("CompositorNodeSeparateColor")
    _tag_node(separate, "package_mask", _scene_id(scene))
    separate.name = "FBP Package Alpha"
    separate.label = "Package Mask"
    separate.mode = 'RGB'
    separate.location = (output_x + 740, package_y - 120)
    source.links.new(package, separate.inputs[0])
    alpha = separate.outputs.get("Alpha") or separate.outputs[-1]
    mask_target = group_output.inputs.get(mask_output_name)
    if mask_target is not None:
        source.links.new(alpha, mask_target)

    scene_token = _scene_id(scene)
    for node in source.nodes:
        if not bool(node.get("fbp_owned", False)):
            _tag_node(node, "source_internal", f"{scene_token}:{node.name}")
    return source, output_names

def _capture_layers_package_links(scene, tree, node):
    """Capture artist-facing output links by persistent layer UUID."""
    if scene is None or tree is None or node is None:
        return ()
    socket_keys = {"TOT": "TOT", "MASK": "MASK"}
    for item in getattr(scene, "fbp_compositor_layers", ()):
        name = str(getattr(item, "output_socket_name", "") or "")
        layer_id = str(getattr(item, "layer_id", "") or "")
        if name and layer_id:
            socket_keys[name] = layer_id
    captured = []
    for socket in getattr(node, "outputs", ()):
        key = socket_keys.get(str(socket.name or ""))
        if not key:
            continue
        for link in tuple(getattr(socket, "links", ())):
            try:
                captured.append((key, link.to_node, link.to_socket))
            except (AttributeError, ReferenceError):
                continue
    return tuple(captured)


def _restore_layers_package_links(scene, tree, node, captured):
    if scene is None or tree is None or node is None:
        return 0
    outputs = {"TOT": node.outputs.get("TOT"), "MASK": node.outputs.get("MASK")}
    for item in getattr(scene, "fbp_compositor_layers", ()):
        layer_id = str(getattr(item, "layer_id", "") or "")
        name = str(getattr(item, "output_socket_name", "") or "")
        if layer_id and name:
            outputs[layer_id] = node.outputs.get(name)
    restored = 0
    for key, to_node, to_socket in captured or ():
        source = outputs.get(str(key or ""))
        if source is None or to_node is None or to_socket is None:
            continue
        try:
            duplicate = any(
                link.from_socket == source and link.to_socket == to_socket
                for link in tuple(tree.links)
            )
            if not duplicate:
                tree.links.new(source, to_socket)
                restored += 1
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return restored


def _sync_layers_package_socket_visibility(scene, node):
    """Show only requested individual outputs while never hiding linked sockets."""
    if scene is None or node is None:
        return 0
    changed = 0
    items_by_name = {
        str(getattr(item, "output_socket_name", "") or ""): item
        for item in getattr(scene, "fbp_compositor_layers", ())
        if str(getattr(item, "output_socket_name", "") or "")
    }
    for socket in getattr(node, "outputs", ()):
        if socket.name in {"TOT", "MASK"}:
            should_hide = False
        else:
            item = items_by_name.get(str(socket.name or ""))
            artist_linked = any(
                _fbp_root_node_role(getattr(link, "to_node", None)) != "layer_set"
                for link in tuple(getattr(socket, "links", ()))
                if getattr(link, "to_node", None) is not None
            )
            should_hide = bool(
                item is None
                or (not bool(getattr(item, "expose_output", False)) and not artist_linked)
            )
        try:
            if bool(socket.hide) != should_hide:
                socket.hide = should_hide
                changed += 1
        except (AttributeError, RuntimeError, TypeError):
            continue
    return changed


def _copy_node_output_links(tree, source_node, target_node):
    """Move outgoing links between equivalent group nodes by visible socket name."""
    if tree is None or source_node is None or target_node is None:
        return 0
    moved = 0
    for source_socket in tuple(getattr(source_node, "outputs", ())):
        target_socket = target_node.outputs.get(source_socket.name)
        if target_socket is None:
            continue
        for link in tuple(getattr(source_socket, "links", ())):
            try:
                tree.links.new(target_socket, link.to_socket)
                moved += 1
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
    return moved


def _ensure_standard_layers_group(scene, tree, source_tree):
    """Return a normal CompositorNodeGroup, never the old custom-group wrapper."""
    existing = next(
        (
            node for node in tree.nodes
            if _fbp_root_node_role(node) in {"layers_package", "legacy_sources"}
        ),
        None,
    )
    if existing is not None and existing.bl_idname == "CompositorNodeGroup":
        existing.node_tree = source_tree
        _tag_node(existing, "layers_package", _scene_id(scene))
        return existing

    group = tree.nodes.new("CompositorNodeGroup")
    group.node_tree = source_tree
    _tag_node(group, "layers_package", _scene_id(scene))
    group.name = "FBP Layers"
    group.label = "Layers"
    group.width = 230
    if existing is not None:
        group.location = existing.location
        _copy_node_output_links(tree, existing, group)
        try:
            tree.nodes.remove(existing)
        except (ReferenceError, RuntimeError):
            pass
    return group


def _node_editor_override(context, tree, scene=None):
    """Return a compositor Node Editor override and optional area restore state."""
    if context is None:
        return None, None
    candidates = []
    area = getattr(context, "area", None)
    if area is not None and getattr(area, "type", "") == 'NODE_EDITOR':
        candidates.append((getattr(context, "window", None), area))
    wm = getattr(context, "window_manager", None)
    for window in getattr(wm, "windows", ()) if wm is not None else ():
        screen = getattr(window, "screen", None)
        for candidate in getattr(screen, "areas", ()) if screen is not None else ():
            if (
                getattr(candidate, "type", "") == 'NODE_EDITOR'
                and all(candidate is not item[1] for item in candidates)
            ):
                candidates.append((window, candidate))

    def make_override(window, candidate, require_tree=True):
        region = next((item for item in candidate.regions if item.type == 'WINDOW'), None)
        space = getattr(candidate.spaces, "active", None)
        if region is None or space is None:
            return None
        if require_tree and str(getattr(space, "tree_type", "") or "") != 'CompositorNodeTree':
            return None
        try:
            space.tree_type = 'CompositorNodeTree'
        except (AttributeError, RuntimeError, TypeError):
            return None
        edit_tree = getattr(space, "edit_tree", None)
        node_tree = getattr(space, "node_tree", None)
        if require_tree and edit_tree is not tree and node_tree is not tree:
            return None
        override = {
            "window": window or getattr(context, "window", None),
            "screen": (
                getattr(window, "screen", None)
                if window is not None
                else getattr(context, "screen", None)
            ),
            "area": candidate,
            "region": region,
            "space_data": space,
        }
        if scene is not None:
            override["scene"] = scene
        return {key: value for key, value in override.items() if value is not None}

    for window, candidate in candidates:
        override = make_override(window, candidate, require_tree=True)
        if override is not None:
            return override, None

    # Generate is also exposed in Output Properties. When no compositor editor
    # is open, temporarily turn the invoking area into one, perform the native
    # operators, then restore the original editor type before returning.
    fallback_area = getattr(context, "area", None)
    fallback_window = getattr(context, "window", None)
    if fallback_area is None or fallback_window is None:
        return None, None
    original_type = str(getattr(fallback_area, "type", "") or "")
    if not original_type:
        return None, None
    try:
        fallback_area.type = 'NODE_EDITOR'
        fallback_space = getattr(fallback_area.spaces, "active", None)
        if fallback_space is not None:
            fallback_space.tree_type = 'CompositorNodeTree'
            try:
                fallback_space.pin = False
            except (AttributeError, RuntimeError, TypeError):
                pass
        override = make_override(fallback_window, fallback_area, require_tree=False)
        if override is not None:
            return override, (fallback_area, original_type)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        fallback_area.type = original_type
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return None, None


def _temporary_output_collector(tree, group):
    """Keep every exposed group output alive while native Ctrl+G is replayed."""
    collector_tree = bpy.data.node_groups.new(
        f"FBP Group Collector - {_new_id()[:8]}", "CompositorNodeTree"
    )
    collector_tree["fbp_owned"] = True
    collector_tree["fbp_role"] = "native_group_collector"
    socket_names = []
    for socket in tuple(group.outputs):
        socket_type = 'NodeSocketFloat' if getattr(socket, "type", "") == 'VALUE' else 'NodeSocketColor'
        collector_tree.interface.new_socket(
            name=str(socket.name or "Output"),
            in_out='INPUT',
            socket_type=socket_type,
        )
        socket_names.append(str(socket.name or "Output"))
    collector = tree.nodes.new("CompositorNodeGroup")
    collector.node_tree = collector_tree
    collector.name = "FBP Native Group Collector"
    collector.label = "FBP Native Group Collector"
    collector.hide = True
    collector.location = (group.location.x + 360, group.location.y - 420)
    collector["fbp_owned"] = True
    collector["fbp_role"] = "native_group_collector"
    for source, target in zip(tuple(group.outputs), tuple(collector.inputs), strict=False):
        try:
            tree.links.new(source, target)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    return collector, collector_tree, tuple(socket_names)


def _rename_native_group_outputs(group, collector, expected_names):
    """Restore every output after Blender's native ``group_make`` operation.

    Blender normally preserves names through the temporary collector links, but
    the editor can briefly expose generic ``Image``/``Value`` names while the
    group interface is rebuilding.  Match by live links first and then by the
    deterministic collector order so the two mandatory outputs can never be
    lost.
    """
    if group is None or group.node_tree is None or collector is None:
        return 0
    renamed = 0
    mappings = []
    for link in tuple(group.id_data.links):
        if link.from_node is group and link.to_node is collector:
            mappings.append((link.from_socket, link.to_socket))

    mapped_ids = set()
    for source_socket, collector_socket in mappings:
        name = str(collector_socket.name or source_socket.name or "Output")
        mapped_ids.add(str(source_socket.identifier or ""))
        interface_socket = next(
            (
                item for item in group.node_tree.interface.items_tree
                if getattr(item, "item_type", "") == 'SOCKET'
                and getattr(item, "in_out", "") == 'OUTPUT'
                and item.identifier == source_socket.identifier
            ),
            None,
        )
        if interface_socket is not None and interface_socket.name != name:
            interface_socket.name = name
            renamed += 1

    # Fallback to the collector order. This specifically covers the transient
    # state where group_make created the socket but the root link has not yet
    # reached the RNA link collection used above.
    live_outputs = list(group.outputs)
    collector_inputs = list(collector.inputs)
    for source_socket, collector_socket in zip(live_outputs, collector_inputs, strict=False):
        identifier = str(source_socket.identifier or "")
        if identifier in mapped_ids:
            continue
        name = str(collector_socket.name or source_socket.name or "Output")
        interface_socket = next(
            (
                item for item in group.node_tree.interface.items_tree
                if getattr(item, "item_type", "") == 'SOCKET'
                and getattr(item, "in_out", "") == 'OUTPUT'
                and item.identifier == source_socket.identifier
            ),
            None,
        )
        if interface_socket is not None and interface_socket.name != name:
            interface_socket.name = name
            renamed += 1

    # Last-resort positional repair: original FBP Layers always exposes TOT,
    # MASK, then the individual UIList outputs in that exact order.
    wanted = [str(name or "") for name in expected_names if str(name or "")]
    outputs = [
        item for item in group.node_tree.interface.items_tree
        if getattr(item, "item_type", "") == 'SOCKET'
        and getattr(item, "in_out", "") == 'OUTPUT'
    ]
    existing_names = {str(item.name or "") for item in outputs}
    for index, name in enumerate(wanted):
        if name in existing_names or index >= len(outputs):
            continue
        outputs[index].name = name
        existing_names.add(name)
        renamed += 1

    # Reorder deterministically: TOT, MASK, then the UIList order.
    outputs_by_name = {str(item.name or ""): item for item in outputs}
    input_count = sum(
        1 for item in group.node_tree.interface.items_tree
        if getattr(item, "item_type", "") == 'SOCKET'
        and getattr(item, "in_out", "") == 'INPUT'
    )
    for offset, name in enumerate(wanted):
        item = outputs_by_name.get(name)
        if item is None:
            continue
        current = list(group.node_tree.interface.items_tree).index(item)
        target = input_count + offset
        if current != target:
            try:
                group.node_tree.interface.move(item, target)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
    try:
        group.node_tree.interface_update(bpy.context)
        group.node_tree.update()
        group.id_data.update_tag()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return renamed


def _mandatory_layers_outputs(group):
    """Return the visible mandatory FBP Layers outputs or raise a clear error."""
    if group is None or group.node_tree is None:
        raise RuntimeError("FBP Layers node group is missing")
    try:
        group.node_tree.interface_update(bpy.context)
        group.node_tree.update()
        group.id_data.update_tag()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    total = group.outputs.get("TOT")
    mask = group.outputs.get("MASK")
    if total is None or mask is None:
        missing = [name for name, socket in (("TOT", total), ("MASK", mask)) if socket is None]
        raise RuntimeError(f"FBP Layers is missing mandatory output: {', '.join(missing)}")
    try:
        total.hide = False
        mask.hide = False
    except (AttributeError, RuntimeError, TypeError):
        pass
    return total, mask


def _replace_socket_input_link(tree, source, target):
    if tree is None or source is None or target is None:
        return False
    for link in tuple(getattr(target, "links", ())):
        try:
            tree.links.remove(link)
        except (ReferenceError, RuntimeError):
            pass
    tree.links.new(source, target)
    return True


def _wire_default_compositor_pipeline(tree, group, effects, export_node, output):
    """Rebuild the renderable default path after native Ctrl+G changed sockets.

    The default result is always:
    ``FBP Layers.TOT -> Effects/Image -> Export/Beauty -> Group Output/Image``.
    MASK is connected to the Effects/Mask input in parallel.  Rebuilding this
    after the native round trip avoids relying on links captured before Blender
    recreated the group interface.
    """
    total, mask = _mandatory_layers_outputs(group)
    effects_image = effects.inputs.get("Image") if effects is not None else None
    effects_mask = effects.inputs.get("Mask") if effects is not None else None
    effects_output = effects.outputs.get("Image") if effects is not None else None

    if effects_image is not None:
        _replace_socket_input_link(tree, total, effects_image)
    if effects_mask is not None:
        _replace_socket_input_link(tree, mask, effects_mask)

    image_source = effects_output or total
    if export_node is not None:
        beauty = export_node.inputs.get("Beauty")
        export_image = export_node.outputs.get("Image")
        if beauty is None or export_image is None:
            raise RuntimeError("Export node is missing Beauty or Image")
        _replace_socket_input_link(tree, image_source, beauty)
        image_source = export_image

    group_output_image = output.inputs.get("Image") if output is not None else None
    if group_output_image is None:
        raise RuntimeError("Main Group Output is missing Image")
    _replace_socket_input_link(tree, image_source, group_output_image)
    try:
        output.hide = False
        output.label = "Output"
    except (AttributeError, RuntimeError, TypeError):
        pass
    return True


def _native_ctrl_g_roundtrip(context, scene, tree, group):
    """Recreate FBP Layers through Blender's actual ungroup/group_make operators.

    Building a CompositorNodeTree directly is close to Ctrl+G but not identical
    in Blender's editor runtime. This performs the same native round trip the
    user demonstrated: ungroup the generated package, then group the selected
    nodes again with NODE_OT_group_make.
    """
    override, area_restore = _node_editor_override(context, tree, scene)
    if override is None or group is None or group.bl_idname != 'CompositorNodeGroup':
        return group, False, "Open the scene compositor and run Generate again"

    collector = collector_tree = None
    old_source_tree = group.node_tree
    original_group_name = str(group.name or "FBP Layers")
    original_group_location = tuple(group.location)
    expected_names = tuple(socket.name for socket in group.outputs)
    external_links = []
    moved_nodes = []
    native_group = None

    def restore_external_links(target_group):
        if target_group is None:
            return 0
        restored = 0
        for socket_name, to_node, to_socket in external_links:
            source_socket = target_group.outputs.get(socket_name)
            if source_socket is None or to_node is None or to_socket is None:
                continue
            try:
                if not any(
                    link.from_socket == source_socket and link.to_socket == to_socket
                    for link in tuple(tree.links)
                ):
                    tree.links.new(source_socket, to_socket)
                    restored += 1
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
        return restored

    def restore_original_group():
        existing = tree.nodes.get(original_group_name)
        if existing is not None and existing.bl_idname == 'CompositorNodeGroup':
            replacement = existing
        else:
            replacement = tree.nodes.new('CompositorNodeGroup')
            replacement.name = original_group_name
        replacement.node_tree = old_source_tree
        replacement.location = original_group_location
        replacement.label = 'Layers'
        replacement.width = max(230, replacement.width)
        _tag_node(replacement, 'layers_package', _scene_id(scene))
        restore_external_links(replacement)
        return replacement

    try:
        space = override.get("space_data")
        with context.temp_override(**override):
            for _step in range(32):
                if getattr(space, "edit_tree", None) is tree:
                    break
                result = bpy.ops.node.group_edit(exit=True)
                if 'FINISHED' not in result:
                    break
        if getattr(space, "edit_tree", None) is not tree:
            return group, False, "Return to the root compositor and run Generate again"

        # The native operator creates one interface socket per external link.
        # Temporarily detach artist links and keep exactly one collector link
        # per output so TOT/MASK and individual layer outputs are not duplicated.
        for socket in tuple(group.outputs):
            for link in tuple(getattr(socket, "links", ())):
                try:
                    external_links.append((str(socket.name or ""), link.to_node, link.to_socket))
                    tree.links.remove(link)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    continue

        collector, collector_tree, expected_names = _temporary_output_collector(tree, group)
        for node in tree.nodes:
            node.select = False
        group.select = True
        tree.nodes.active = group
        with context.temp_override(**override):
            result = bpy.ops.node.group_ungroup()
        if 'FINISHED' not in result:
            restore_external_links(group)
            return group, False, "Blender could not ungroup the generated Layers package"

        # Native ungroup keeps the moved internal nodes selected. Ensure every
        # unrelated root node remains outside the new group.
        collector.select = False
        for node in tree.nodes:
            if node is collector or _fbp_root_node_role(node) in {
                "effects_stage", "output", "legacy_group_output", "layer_set", "over_stack"
            }:
                node.select = False
        selected = [node for node in tree.nodes if node.select]
        moved_nodes = list(selected)
        if not selected:
            return restore_original_group(), False, "Blender ungrouped the package but selected no internal nodes"
        tree.nodes.active = selected[0]
        with context.temp_override(**override):
            result = bpy.ops.node.group_make()
            if 'FINISHED' in result:
                # NODE_OT_group_make enters the new group automatically. Return
                # to the root so Generate leaves the user looking at the single
                # compact FBP Layers node, not at its internal Render Layers.
                try:
                    bpy.ops.node.group_edit(exit=True)
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    pass
        if 'FINISHED' not in result:
            for moved in tuple(moved_nodes):
                try:
                    if moved.name in tree.nodes:
                        tree.nodes.remove(moved)
                except (AttributeError, ReferenceError, RuntimeError, TypeError):
                    continue
            return restore_original_group(), False, f"Blender could not create the native {primary_shortcut_label('G')} group"

        native_group = tree.nodes.active
        if native_group is None or native_group.bl_idname != 'CompositorNodeGroup' or native_group.node_tree is None:
            native_group = next(
                (
                    node for node in tree.nodes
                    if node.bl_idname == 'CompositorNodeGroup'
                    and node is not collector
                    and node.select
                ),
                None,
            )
        if native_group is None or native_group.node_tree is None:
            return restore_original_group(), False, "The native group operator did not return a node group"

        _rename_native_group_outputs(native_group, collector, expected_names)
        _mandatory_layers_outputs(native_group)
        _tag_node(native_group, "layers_package", _scene_id(scene))
        native_group.name = "FBP Layers"
        native_group.label = "Layers"
        native_group.width = max(230, native_group.width)
        native_group.node_tree[FBP_COMPOSITOR_SOURCE_TREE_TAG] = True
        native_group.node_tree["fbp_compositor_scene_id"] = _scene_id(scene)
        native_group.node_tree["fbp_owned"] = True
        native_group.node_tree["fbp_role"] = "layers_package"
        native_group.node_tree["fbp_uuid"] = _scene_id(scene)
        native_group["fbp_native_ctrl_g"] = True
        native_group.node_tree["fbp_native_ctrl_g"] = True
        native_group.node_tree["fbp_version"] = 4
        restore_external_links(native_group)
        return native_group, True, ""
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not create the native FBP Layers group", exc)
        if native_group is not None:
            restore_external_links(native_group)
            return native_group, False, str(exc)
        try:
            return restore_original_group(), False, str(exc)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return None, False, str(exc)
    finally:
        if collector is not None:
            try:
                if collector.name in tree.nodes:
                    tree.nodes.remove(collector)
            except (AttributeError, ReferenceError, RuntimeError, TypeError):
                pass
        if collector_tree is not None:
            try:
                if collector_tree.users == 0:
                    bpy.data.node_groups.remove(collector_tree)
            except (AttributeError, ReferenceError, RuntimeError, TypeError):
                pass
        if old_source_tree is not None:
            try:
                if old_source_tree.users == 0:
                    bpy.data.node_groups.remove(old_source_tree)
            except (AttributeError, ReferenceError, RuntimeError, TypeError):
                pass
        if area_restore is not None:
            restore_area, restore_type = area_restore
            try:
                restore_area.type = restore_type
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass


def _native_layers_group_contract(tree):
    """Return structural errors for the artist-facing root compositor."""
    errors = []
    groups = [
        node for node in tree.nodes
        if _fbp_root_node_role(node) == "layers_package"
    ]
    if len(groups) != 1:
        errors.append(f"Expected one FBP Layers group, found {len(groups)}")
    elif groups[0].bl_idname != 'CompositorNodeGroup' or groups[0].node_tree is None:
        errors.append("FBP Layers is not a standard compositor node group")
    else:
        group = groups[0]
        if not bool(group.get("fbp_native_ctrl_g", False)):
            errors.append(f"FBP Layers was not created by the native {primary_shortcut_label('G')} path")
        internal_render_layers = sum(
            1 for node in group.node_tree.nodes
            if node.bl_idname == 'CompositorNodeRLayers'
        )
        if internal_render_layers == 0:
            errors.append("FBP Layers contains no internal Render Layers nodes")
    for node in tree.nodes:
        role = _fbp_root_node_role(node)
        if node.bl_idname == 'CompositorNodeRLayers' and bool(node.get("fbp_owned", False)):
            errors.append(f"Root compositor still contains Render Layers: {node.name}")
        if node.bl_idname == 'NodeFrame' and (
            role in {"legacy_source_frame", "native_group_collector"}
            or node.name in {"FBP Internal Sources", "FBP Technical Sources"}
        ):
            errors.append(f"Root compositor still contains a technical frame: {node.name}")
        if node.bl_idname == 'CompositorNodeAlphaOver' and bool(node.get("fbp_owned", False)):
            errors.append(f"Root compositor still contains a technical Alpha Over: {node.name}")
    return tuple(dict.fromkeys(errors))


def _remove_default_stack_stage(scene, tree):
    """Remove only the generated default Alpha Over controller.

    User-created Composite Stack nodes remain untouched and can still be used
    for nested packages or alternate branches.
    """
    removed = 0
    for node in tuple(tree.nodes):
        if _fbp_root_node_role(node) == "over_stack" and bool(node.get("fbp_default_pipeline", False)):
            tree.nodes.remove(node)
            removed += 1
    try:
        stacks = getattr(scene, "fbp_over_stacks", None)
        if stacks is not None:
            for index in range(len(stacks) - 1, -1, -1):
                if bool(getattr(stacks[index], "is_default_pipeline", False)):
                    stacks.remove(index)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass
    return removed


def _build_compact_node_tree(scene, context=None, native_group=False, activate_compositor=False):
    """Build the compact Layers → Effects / Masks → Export compositor."""
    current = scene.compositing_node_group
    tree = _owned_tree(scene)
    if current is not tree and not bool(getattr(scene, "fbp_compositor_enabled", False)):
        scene.fbp_compositor_previous_group = current
        scene.fbp_compositor_previous_use_compositing = bool(scene.render.use_compositing)
    existing_layers_node = next(
        (
            node for node in tree.nodes
            if _fbp_root_node_role(node) in {"layers_package", "legacy_sources"}
        ),
        None,
    )
    preserved_layer_links = _capture_layers_package_links(
        scene, tree, existing_layers_node
    )
    source, _output_names = _build_source_group(scene)
    _clear_managed_outer_nodes(tree)
    if not any(
        getattr(item, "item_type", "") == 'SOCKET'
        and getattr(item, "in_out", "") == 'OUTPUT'
        and item.name == "Image"
        for item in tree.interface.items_tree
    ):
        tree.interface.new_socket(
            name="Image", in_out='OUTPUT', socket_type='NodeSocketColor'
        )
    group = _ensure_standard_layers_group(scene, tree, source)
    group.name = "FBP Layers"
    group.label = "Layers"
    group.node_tree = source
    group.location = (-760, 40)
    group.width = max(230, group.width)
    # All Render Layers and their processing now live inside ``source``.
    # The root compositor contains one real node group, exactly like Ctrl+G.
    _restore_layers_package_links(scene, tree, group, preserved_layer_links)

    # The Layers node now owns the default Alpha Over package internally.
    # Keep user-created Composite Stack nodes, but remove the old generated
    # middle stage so the visible pipeline is Layers -> Effects/Masks -> Export.
    _remove_default_stack_stage(scene, tree)
    try:
        from .compositor_sets import fbp_ensure_default_output, fbp_sync_layer_set_nodes
    except ImportError as exc:
        fbp_warn("Could not load compositor controllers", exc)
        fbp_ensure_default_output = None
        fbp_sync_layer_set_nodes = None

    effects = next(
        (node for node in tree.nodes if _fbp_root_node_role(node) == "effects_stage"),
        None,
    )
    if effects is None:
        effects = _tag_node(tree.nodes.new("CompositorNodeGroup"), "effects_stage")
    effects.name = "FBP Effects & Masks"
    effects.label = "Effects / Masks"
    effects.node_tree = _owned_effects_tree(scene)
    effects.location = (220, 40)
    effects.width = max(180, effects.width)

    output = _tag_node(tree.nodes.new("NodeGroupOutput"), "legacy_group_output")
    output.name = "FBP Composite Output"
    output.label = "Output"
    output.is_active_output = True
    output.hide = False
    output.location = (930, 40)

    package_image = group.outputs.get("TOT")
    package_mask = group.outputs.get("MASK")
    effects_image = effects.inputs.get("Image")
    effects_mask = effects.inputs.get("Mask")
    if package_image is not None and effects_image is not None:
        for link in tuple(effects_image.links):
            tree.links.remove(link)
        tree.links.new(package_image, effects_image)
    if package_mask is not None and effects_mask is not None:
        for link in tuple(effects_mask.links):
            tree.links.remove(link)
        tree.links.new(package_mask, effects_mask)

    export_node = None
    try:
        export_node = fbp_ensure_default_output(scene, tree) if callable(fbp_ensure_default_output) else None
        if export_node is not None:
            export_node.hide = False
            export_node.label = "Export"
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not build the Export stage", exc)
    final_image = effects.outputs.get("Image")
    if export_node is not None:
        beauty = export_node.inputs.get("Beauty")
        export_image = export_node.outputs.get("Image")
        if final_image is not None and beauty is not None:
            for link in tuple(beauty.links):
                tree.links.remove(link)
            tree.links.new(final_image, beauty)
        if export_image is not None and output.inputs.get("Image") is not None:
            tree.links.new(export_image, output.inputs["Image"])
    elif final_image is not None and output.inputs.get("Image") is not None:
        tree.links.new(final_image, output.inputs["Image"])

    needs_native_roundtrip = bool(
        native_group
        and (
            not bool(group.get("fbp_native_ctrl_g", False))
            or group.node_tree is None
            or not bool(group.node_tree.get("fbp_native_ctrl_g", False))
        )
    )
    if needs_native_roundtrip:
        group, native_ok, native_error = _native_ctrl_g_roundtrip(
            context, scene, tree, group
        )
        if not native_ok or group is None:
            raise RuntimeError(
                native_error or f"Could not create FBP Layers with Blender's native {primary_shortcut_label('G')} operator"
            )

    # Native Ctrl+G recreates the group interface and invalidates socket RNA
    # references captured earlier in this function. Re-fetch TOT/MASK and wire
    # the complete render path only after the round trip has finished.
    _wire_default_compositor_pipeline(tree, group, effects, export_node, output)

    if native_group:
        contract_errors = _native_layers_group_contract(tree)
        if contract_errors:
            raise RuntimeError("; ".join(contract_errors))

    group.label = "Layers"
    group.location = (-760, 40)
    _sync_layers_package_socket_visibility(scene, group)
    render = getattr(scene, "render", None)
    use_compositing_before = bool(getattr(render, "use_compositing", False)) if render is not None else False
    scene.compositing_node_group = tree
    # Assigning a compositor root may change Blender's native render state. A
    # managed FBP graph is renderable only after the explicit scene opt-in;
    # detached graph maintenance preserves the artist's pre-sync state.
    if render is not None:
        if activate_compositor or bool(getattr(scene, "fbp_compositor_enabled", False)):
            _apply_render_compositor_opt_in(
                scene,
                managed_activation=bool(activate_compositor),
            )
        else:
            render.use_compositing = use_compositing_before
    if callable(fbp_sync_layer_set_nodes):
        try:
            fbp_sync_layer_set_nodes(scene, tree=tree, source_node=group)
            _sync_layers_package_socket_visibility(scene, group)
            _wire_default_compositor_pipeline(tree, group, effects, export_node, output)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not synchronize FBP compositor controllers", exc)
    fbp_ensure_native_render_output(scene, tree)
    return tree


def _fbp_sync_compositor_impl(scene, context=None, native_group=False, activate_compositor=False):
    """Synchronize groups, shadow sources, View Layers, and Blender 5.2 nodes."""
    if scene is None:
        return {"layers": 0, "groups": 0, "effects": 0, "nodes": 0}
    _guard_compositor_layer_node_schema(scene)
    seen_ids = set()
    for item in scene.fbp_compositor_layers:
        try:
            exposure_saved = item.is_property_set("expose_output")
        except (AttributeError, TypeError):
            exposure_saved = True
        if not exposure_saved and _is_folder_item(item):
            item.expose_output = True
        _normalize_layer_effect_stack(item)
        layer_id = _ensure_item_id(item)
        if layer_id in seen_ids:
            item.layer_id = _new_id()
        seen_ids.add(item.layer_id)
    render_items = _render_layer_items(scene)
    if not render_items:
        raise RuntimeError("Add or auto-create at least one compositor layer")
    if not bool(getattr(scene, "fbp_compositor_enabled", False)):
        scene.fbp_compositor_previous_film_transparent = bool(
            scene.render.film_transparent
        )
    root = _ensure_shadow_root(scene)
    _sync_shadow_collections(scene, root)
    _sync_view_layers(scene, root)
    tree = _build_compact_node_tree(
        scene, context=context, native_group=native_group,
        activate_compositor=activate_compositor,
    )
    generation = _mark_compositor_layer_node_schema(scene, tree)
    if activate_compositor:
        # ``enabled`` means the FBP graph is managed and may receive live syncs;
        # only ``fbp_compositor_render_enabled`` opts Render Image into it.
        scene.fbp_compositor_enabled = True
    group_count = len(fbp_compositor_group_collections(scene))
    effect_count = sum(
        1 for item in scene.fbp_compositor_layers
        for effect in item.effects if effect.enabled and effect.effect_type != 'NONE'
    )
    folder_count = sum(1 for item in scene.fbp_compositor_layers if _is_folder_item(item))
    visible_roles = {"layers_package", "effects_stage", "output"}
    visible_nodes = sum(
        1 for node in tree.nodes
        if _fbp_root_node_role(node) in visible_roles
    )
    scene.fbp_compositor_status = (
        f"Synced {len(render_items)} layers, {folder_count} folders, "
        f"{effect_count} effects · {visible_nodes} visible stages"
    )
    return {
        "layers": len(render_items),
        "groups": group_count,
        "folders": folder_count,
        "effects": effect_count,
        "nodes": len(tree.nodes),
        "visible_nodes": visible_nodes,
        "schema": FBP_COMPOSITOR_LAYER_NODE_SCHEMA_VERSION,
        "generation": generation,
    }


_FBP_COMPOSITOR_SYNCING = False


def fbp_sync_compositor(scene, context=None, native_group=False, activate_compositor=False):
    """Guarded public compositor synchronization entry point."""
    global _FBP_COMPOSITOR_SYNCING
    if _FBP_COMPOSITOR_SYNCING:
        return {"layers": 0, "groups": 0, "effects": 0, "nodes": 0}
    _FBP_COMPOSITOR_SYNCING = True
    try:
        return _fbp_sync_compositor_impl(
            scene, context=context, native_group=native_group,
            activate_compositor=activate_compositor,
        )
    finally:
        _FBP_COMPOSITOR_SYNCING = False


def fbp_restore_compositor(scene, remove_generated=True):
    """Restore the user's compositor and native View Layer render switches."""
    if scene is None:
        return
    current = scene.compositing_node_group
    previous = scene.fbp_compositor_previous_group
    scene.compositing_node_group = previous
    scene.render.use_compositing = bool(scene.fbp_compositor_previous_use_compositing)
    scene.render.film_transparent = bool(
        scene.fbp_compositor_previous_film_transparent
    )
    for layer in tuple(scene.view_layers):
        layer_id = str(layer.get(FBP_COMPOSITOR_LAYER_TAG, "") or "")
        if layer_id:
            if remove_generated and len(scene.view_layers) > 1:
                scene.view_layers.remove(layer)
            else:
                layer.use = False
            continue
        if "fbp_compositor_original_use" in layer:
            layer.use = bool(layer["fbp_compositor_original_use"])
            del layer["fbp_compositor_original_use"]
    if remove_generated:
        for collection in tuple(_walk_collections(scene.collection)):
            if (
                bool(collection.get(FBP_COMPOSITOR_ROOT_TAG, False))
                and str(collection.get("fbp_compositor_scene_id", "") or "") == _scene_id(scene)
            ):
                for child in tuple(collection.children):
                    collection.children.unlink(child)
                    if bool(child.get(FBP_COMPOSITOR_SHADOW_TAG, False)):
                        bpy.data.collections.remove(child)
                bpy.data.collections.remove(collection)
                break
        if (
            current is not None
            and bool(current.get(FBP_COMPOSITOR_TREE_TAG, False))
            and str(current.get("fbp_compositor_scene_id", "") or "") == _scene_id(scene)
        ):
            # A pinned Node Editor can keep one UI user after the Scene pointer
            # is restored. This tree is scene-owned, so unlink that UI reference
            # as part of a full restore instead of leaking the compact group.
            bpy.data.node_groups.remove(current, do_unlink=True)
        for tree in tuple(bpy.data.node_groups):
            if (
                (
                    bool(tree.get(FBP_COMPOSITOR_SOURCE_TREE_TAG, False))
                    or bool(tree.get(FBP_COMPOSITOR_EFFECTS_TREE_TAG, False))
                )
                and str(tree.get("fbp_compositor_scene_id", "") or "") == _scene_id(scene)
            ):
                bpy.data.node_groups.remove(tree, do_unlink=True)
        _cleanup_unused_compositor_asset_groups()
    scene.fbp_compositor_enabled = False
    scene.fbp_compositor_status = "Native compositor restored"
    for key in (
        FBP_COMPOSITOR_LAYER_NODE_SCHEMA_KEY,
        FBP_COMPOSITOR_LAYER_NODE_GENERATION_KEY,
    ):
        try:
            if key in scene:
                del scene[key]
        except FBP_DATA_ERRORS:
            pass


def fbp_add_compositor_layer(scene, name=""):
    item = scene.fbp_compositor_layers.add()
    item.layer_id = _new_id()
    item.name = _clean_name(name, f"Composite Layer {len(scene.fbp_compositor_layers)}")
    item.view_layer_name = f"FBP • {item.name}"
    scene.fbp_compositor_layer_index = len(scene.fbp_compositor_layers) - 1
    return item


def fbp_auto_compositor_layers(scene):
    """Reconcile generated layers for the selected source mode.

    Matching generated entries keep their effect stacks. Entries from another
    generation mode are removed, while explicitly manual layers remain intact.
    """
    mode = str(
        getattr(scene, "fbp_compositor_generation_mode", 'LAYERS_GROUPS')
        or 'LAYERS_GROUPS'
    )
    specs = fbp_compositor_source_specs(scene, mode)
    folder_specs = {}
    for spec in specs:
        folder_key = str(spec.get("folder_key", "") or "")
        if folder_key:
            folder_specs.setdefault(
                folder_key,
                {
                    "kind": "GROUP",
                    "key": folder_key,
                    "name": str(spec.get("folder_name", "") or "Folder"),
                },
            )
    desired_keys = {(spec["kind"], spec["key"]) for spec in specs}
    desired_keys.update(("GROUP", key) for key in folder_specs)
    items = scene.fbp_compositor_layers
    groups = fbp_compositor_group_collections(scene)

    removed_ids = set()
    removed = 0
    for index in range(len(items) - 1, -1, -1):
        item = items[index]
        if not bool(getattr(item, "auto_generated", False)):
            continue
        item_key = (
            str(getattr(item, "source_kind", 'MANUAL') or 'MANUAL'),
            str(getattr(item, "source_key", "") or ""),
        )
        if item_key in desired_keys:
            continue
        removed_ids.add(str(getattr(item, "layer_id", "") or ""))
        items.remove(index)
        removed += 1
    if removed_ids:
        for collection in groups:
            if str(getattr(collection, "fbp_compositor_layer_id", "") or "") in removed_ids:
                collection.fbp_compositor_layer_id = ""

    existing = {
        (
            str(getattr(item, "source_kind", 'MANUAL') or 'MANUAL'),
            str(getattr(item, "source_key", "") or ""),
        ): item
        for item in items
        if bool(getattr(item, "auto_generated", False))
    }
    added = 0
    folders_by_key = {}
    for folder_key, folder_spec in folder_specs.items():
        item_key = ("GROUP", folder_key)
        folder = existing.get(item_key)
        if folder is None:
            folder = fbp_add_compositor_layer(scene, folder_spec["name"])
            folder.source_kind = 'GROUP'
            folder.source_key = folder_key
            folder.auto_generated = True
            folder.expose_output = True
            existing[item_key] = folder
            added += 1
        folder.row_type = 'FOLDER'
        folder.name = folder_spec["name"]
        folder.view_layer_name = ""
        folder.parent_folder_id = ""
        folders_by_key[folder_key] = folder
        collection = _collection_by_source_id(scene, folder_key)
        if collection is not None:
            collection.fbp_compositor_layer_id = folder.layer_id

    for spec in specs:
        item_key = (spec["kind"], spec["key"])
        item = existing.get(item_key)
        if item is None:
            item = fbp_add_compositor_layer(scene, spec["name"])
            item.source_kind = spec["kind"]
            item.source_key = spec["key"]
            item.auto_generated = True
            existing[item_key] = item
            added += 1
        else:
            item.name = spec["name"]
            requested = f"FBP • {spec['name']}"
            if str(getattr(item, "view_layer_name", "") or "").startswith("FBP"):
                item.view_layer_name = requested
        item.row_type = 'LAYER'
        folder = folders_by_key.get(str(spec.get("folder_key", "") or ""))
        # A user-created compositor folder is an explicit organizational
        # override. Regenerating source rows must not silently pull its layers
        # back into an automatic Ctrl+G folder.
        current_parent = _folder_item_by_id(
            scene, str(getattr(item, "parent_folder_id", "") or "")
        )
        if current_parent is None or bool(
            getattr(current_parent, "auto_generated", False)
        ):
            item.parent_folder_id = folder.layer_id if folder is not None else ""
        if spec["kind"] == 'COLLECTION':
            collection = _collection_by_source_id(scene, spec["key"])
            if collection is not None:
                collection.fbp_compositor_layer_id = item.layer_id

    # Generated sources follow back-to-front Layer List order. A compositor
    # folder is inserted before its first child; every layer remains an
    # independent View Layer and output socket.
    desired_sequence = []
    emitted_folders = set()
    for spec in specs:
        folder_key = str(spec.get("folder_key", "") or "")
        if folder_key and folder_key not in emitted_folders:
            desired_sequence.append(("GROUP", folder_key))
            emitted_folders.add(folder_key)
        desired_sequence.append((spec["kind"], spec["key"]))

    for target_index, item_key in enumerate(desired_sequence):
        current_index = next(
            (
                index for index, item in enumerate(items)
                if bool(getattr(item, "auto_generated", False))
                and str(getattr(item, "source_kind", 'MANUAL') or 'MANUAL') == item_key[0]
                and str(getattr(item, "source_key", "") or "") == item_key[1]
            ),
            -1,
        )
        if current_index >= 0 and current_index != target_index:
            items.move(current_index, target_index)

    # Re-form explicit manual folder blocks after source reconciliation. Their
    # generated child layers retain source identity, but user organization has
    # priority over the automatic source order.
    manual_folder_ids = [
        item.layer_id for item in items
        if _is_folder_item(item) and not bool(getattr(item, "auto_generated", False))
    ]
    for folder_id in manual_folder_ids:
        folder_index = next(
            (index for index, item in enumerate(items) if item.layer_id == folder_id),
            -1,
        )
        child_ids = [
            item.layer_id for item in items
            if str(getattr(item, "parent_folder_id", "") or "") == folder_id
        ]
        if folder_index < 0 or not child_ids:
            continue
        child_indices = [
            index for index, item in enumerate(items) if item.layer_id in child_ids
        ]
        insert_at = min([folder_index, *child_indices])
        items.move(folder_index, insert_at)
        for offset, child_id in enumerate(child_ids, start=1):
            current_index = next(
                (index for index, item in enumerate(items) if item.layer_id == child_id),
                -1,
            )
            if current_index >= 0:
                items.move(current_index, insert_at + offset)

    # Manual folder rows are persistent user data. Older manual layer rows
    # already use the RNA default (LAYER), so no blanket type reset is needed.

    if len(items):
        scene.fbp_compositor_layer_index = min(
            max(0, int(getattr(scene, "fbp_compositor_layer_index", 0))),
            len(items) - 1,
        )
    else:
        scene.fbp_compositor_layer_index = 0
    return added


def fbp_compositor_assignment_count(scene, layer_id):
    item = _item_by_id(scene, layer_id)
    if item is not None and _is_folder_item(item):
        return sum(
            fbp_compositor_assignment_count(scene, child.layer_id)
            for child in scene.fbp_compositor_layers
            if str(getattr(child, "parent_folder_id", "") or "") == item.layer_id
        )
    if item is not None and str(
        getattr(item, "source_kind", 'MANUAL') or 'MANUAL'
    ) != 'MANUAL':
        source_rigs = _source_rigs_for_item(scene, item)
        if source_rigs:
            return len(source_rigs)
        if str(getattr(item, "source_kind", "") or "") == 'COLLECTION':
            collection = _collection_by_source_id(
                scene, str(getattr(item, "source_key", "") or "")
            )
            if collection is not None:
                return sum(
                    1 for obj in _objects_for_layer_source(collection, item.layer_id)
                    if bool(getattr(obj, "is_fbp_control", False))
                    or bool(getattr(obj, "is_fbp_plane", False))
                )
        return 0
    return sum(
        1 for collection in fbp_compositor_group_collections(scene)
        if str(getattr(collection, "fbp_compositor_layer_id", "") or "") == layer_id
    )


def _update_transparency(scene, _context):
    """Apply the desired alpha mode only while FBP is opted into rendering."""
    if not bool(getattr(scene, "fbp_compositor_enabled", False)):
        return
    if not bool(getattr(scene, "fbp_compositor_render_enabled", False)):
        return
    try:
        scene.render.film_transparent = bool(scene.fbp_compositor_transparent)
    except FBP_DATA_ERRORS:
        pass


def _apply_render_compositor_opt_in(scene, *, managed_activation=False):
    """Apply the explicit FBP render opt-in without touching an artist graph.

    Blender 5.2 starts new scenes with ``RenderSettings.use_compositing`` set to
    true even when no compositor graph exists.  Preserving that native default
    after assigning the generated FBP graph therefore enables the compositor as
    an accidental side effect.  FBP uses its own scene-level opt-in while its
    managed graph is active and restores the pre-FBP values when it is not.
    """
    if scene is None:
        return False
    if not (
        bool(managed_activation)
        or bool(getattr(scene, "fbp_compositor_enabled", False))
    ):
        return False
    if not managed_activation:
        tree = getattr(scene, "compositing_node_group", None)
        try:
            if (
                tree is None
                or not bool(tree.get(FBP_COMPOSITOR_TREE_TAG, False))
                or str(tree.get("fbp_compositor_scene_id", "") or "") != _scene_id(scene)
            ):
                return False
        except FBP_DATA_ERRORS:
            return False
    render = getattr(scene, "render", None)
    if render is None:
        return False
    enabled = bool(getattr(scene, "fbp_compositor_render_enabled", False))
    try:
        render.use_compositing = enabled
        render.film_transparent = (
            bool(getattr(scene, "fbp_compositor_transparent", True))
            if enabled
            else bool(getattr(scene, "fbp_compositor_previous_film_transparent", False))
        )
    except FBP_DATA_ERRORS:
        return False
    return enabled


def _update_render_compositor_opt_in(scene, _context):
    """Update native render state only after the managed graph exists."""
    _apply_render_compositor_opt_in(scene)


_FBP_PENDING_COMPOSITOR_SCENES = set()
_FBP_COMPOSITOR_UPDATE_RETRIES = {}
_FBP_COMPOSITOR_UPDATE_MAX_RETRIES = 3
_FBP_COMPOSITOR_UPDATE_TIMER_RUNNING = False


def fbp_reset_compositor_runtime_state():
    """Clear deferred compositor state after Blender history replaces Main."""
    global _FBP_COMPOSITOR_UPDATE_TIMER_RUNNING
    _FBP_PENDING_COMPOSITOR_SCENES.clear()
    _FBP_COMPOSITOR_UPDATE_RETRIES.clear()
    _FBP_COMPOSITOR_UPDATE_TIMER_RUNNING = False


def _flush_compositor_updates():
    global _FBP_COMPOSITOR_UPDATE_TIMER_RUNNING
    retry_delay = ui_list_mutation_delay()
    if retry_delay > 0.0:
        return retry_delay
    if bpy.app.is_job_running('RENDER'):
        return 0.2

    scene_keys = tuple(_FBP_PENDING_COMPOSITOR_SCENES)
    _FBP_PENDING_COMPOSITOR_SCENES.clear()
    _FBP_COMPOSITOR_UPDATE_TIMER_RUNNING = False
    for scene_key in scene_keys:
        scene = _scene_from_runtime_key(scene_key)
        if scene is None or not bool(getattr(scene, "fbp_compositor_enabled", False)):
            _FBP_COMPOSITOR_UPDATE_RETRIES.pop(scene_key, None)
            continue
        try:
            fbp_sync_compositor(scene)
            _FBP_COMPOSITOR_UPDATE_RETRIES.pop(scene_key, None)
        except FBP_DATA_ERRORS as exc:
            attempts = int(_FBP_COMPOSITOR_UPDATE_RETRIES.get(scene_key, 0) or 0) + 1
            if attempts < _FBP_COMPOSITOR_UPDATE_MAX_RETRIES:
                _FBP_COMPOSITOR_UPDATE_RETRIES[scene_key] = attempts
                _FBP_PENDING_COMPOSITOR_SCENES.add(scene_key)
                try:
                    scene.fbp_compositor_status = (
                        f"Compositor update retry {attempts}/{_FBP_COMPOSITOR_UPDATE_MAX_RETRIES - 1}"
                    )
                except FBP_DATA_ERRORS:
                    pass
            else:
                _FBP_COMPOSITOR_UPDATE_RETRIES.pop(scene_key, None)
                try:
                    scene.fbp_compositor_status = "Compositor update failed safely · use Sync or Safe Repair"
                except FBP_DATA_ERRORS:
                    pass
            fbp_warn("Could not apply live compositor effect update", exc)

    if _FBP_PENDING_COMPOSITOR_SCENES:
        _FBP_COMPOSITOR_UPDATE_TIMER_RUNNING = True
        return 0.15
    return None


def _schedule_compositor_update(owner, context):
    global _FBP_COMPOSITOR_UPDATE_TIMER_RUNNING
    if _FBP_COMPOSITOR_SYNCING:
        return
    scene = getattr(context, "scene", None) if context is not None else None
    if scene is None:
        scene = getattr(owner, "id_data", None)
    if scene is None or not bool(getattr(scene, "fbp_compositor_enabled", False)):
        return
    _queue_compositor_scene(scene)
    if _FBP_COMPOSITOR_UPDATE_TIMER_RUNNING:
        if scheduled_task_pending("compositor.live_update"):
            return
        # Undo/load can invalidate the shared task while this module-local hint
        # remains true. Re-arm instead of dropping the first following edit.
        _FBP_COMPOSITOR_UPDATE_TIMER_RUNNING = False
    _FBP_COMPOSITOR_UPDATE_TIMER_RUNNING = True
    accepted = schedule_once(
        "compositor.live_update",
        _flush_compositor_updates,
        first_interval=0.15,
    )
    if not accepted or not scheduled_task_pending("compositor.live_update"):
        _FBP_COMPOSITOR_UPDATE_TIMER_RUNNING = False


def _existing_source_tree(scene):
    token = _scene_id(scene)
    return next((
        tree for tree in bpy.data.node_groups
        if getattr(tree, "bl_idname", "") == "CompositorNodeTree"
        and bool(tree.get(FBP_COMPOSITOR_SOURCE_TREE_TAG, False))
        and str(tree.get("fbp_compositor_scene_id", "") or "") == token
    ), None)


def _effect_owner(scene, effect):
    pointer = int(effect.as_pointer())
    for layer in scene.fbp_compositor_layers:
        for index, candidate in enumerate(layer.effects):
            if int(candidate.as_pointer()) == pointer:
                return layer, index
    return None, -1


def _apply_live_effect_settings(node, effect):
    effect_type = str(effect.effect_type or 'NONE')
    if effect_type == 'GLOW':
        _set_socket(node, "Threshold", effect.glow_threshold)
        _set_socket(node, "Strength", effect.glow_strength)
        _set_socket(node, "Size", effect.glow_size)
    elif effect_type == 'BLUR':
        _set_socket(node, "Size", (effect.blur_size, effect.blur_size))
    elif effect_type == 'DEFOCUS':
        node.f_stop = effect.defocus_f_stop
        node.blur_max = float(effect.defocus_blur_max)
    elif effect_type == 'COLOR_GRADE':
        _set_socket(node, "Temperature", effect.color_temperature)
        _set_socket(node, "Tint", effect.color_tint)
    elif effect_type == 'PIXELATE':
        _set_socket(node, "Size", int(effect.pixel_size))
    elif effect_type == 'VIGNETTE':
        scale = float(effect.vignette_scale)
        _set_socket(node, "Factor", float(effect.vignette_factor))
        _set_socket(node, "Feather", float(effect.vignette_feather))
        _set_socket(node, "Corner Roundness", float(effect.vignette_roundness))
        _set_socket(node, "Scale", (scale, scale, 0.0))
    elif effect_type == 'UNSHARP_MASK':
        _set_socket(node, "Radius", float(effect.unsharp_radius))
        _set_socket(node, "Factor", float(effect.unsharp_factor))
        _set_socket(node, "Threshold", float(effect.unsharp_threshold))
    elif effect_type == 'TUNE_IMAGE':
        for name, value in (("Contrast", effect.tune_contrast), ("Color Boost", effect.tune_color_boost), ("Clarity", effect.tune_clarity), ("Detail", effect.tune_detail), ("Sharpen", effect.tune_sharpen)):
            _set_socket(node, name, float(value))
    elif effect_type == 'FILM_GRAIN':
        for name, value in (("Factor", effect.film_grain_factor), ("Animated", effect.film_grain_animated), ("ISO", effect.film_grain_iso), ("Softness", effect.film_grain_softness), ("Coarseness", effect.film_grain_coarseness)):
            _set_socket(node, name, value)
    elif effect_type == 'CHROMATIC_ABERRATION':
        for name, value in (("Factor", effect.chromatic_factor), ("Samples", effect.chromatic_samples), ("Fit", effect.chromatic_fit)):
            _set_socket(node, name, value)
    elif effect_type == 'SEPIA':
        for name, value in (("Contrast", effect.sepia_contrast), ("Tone", effect.sepia_tone), ("Saturation", effect.sepia_saturation)):
            _set_socket(node, name, float(value))


def _update_compositor_effect_parameter(effect, context):
    """Update effect sockets in place; rebuild only when topology is absent."""
    if _FBP_COMPOSITOR_SYNCING:
        return
    scene = getattr(context, "scene", None) if context is not None else getattr(effect, "id_data", None)
    if scene is None or not bool(getattr(scene, "fbp_compositor_enabled", False)):
        return
    layer, index = _effect_owner(scene, effect)
    source = _existing_source_tree(scene)
    if layer is None or source is None:
        _schedule_compositor_update(effect, context)
        return
    node = next((candidate for candidate in source.nodes if candidate.get("fbp_role", "") == "source_effect" and candidate.get("fbp_layer_id", "") == layer.layer_id and int(candidate.get("fbp_effect_index", -1)) == index), None)
    mix = next((candidate for candidate in source.nodes if candidate.get("fbp_role", "") == "source_effect_mix" and candidate.get("fbp_uuid", "") == f"{layer.layer_id}:effect:{index}:mix"), None)
    if node is None or mix is None:
        if effect.enabled and effect.effect_type != 'NONE':
            _schedule_compositor_update(effect, context)
        return
    try:
        _apply_live_effect_settings(node, effect)
        _set_socket(mix, "Factor", float(effect.effect_mix))
        source.update_tag()
    except FBP_DATA_ERRORS:
        _schedule_compositor_update(effect, context)


def _update_compositor_opacity(owner, context):
    """Apply opacity without recreating View Layers or compositor nodes."""
    if _FBP_COMPOSITOR_SYNCING:
        return
    scene = getattr(context, "scene", None) if context is not None else getattr(owner, "id_data", None)
    if scene is None or not bool(getattr(scene, "fbp_compositor_enabled", False)):
        return
    source = _existing_source_tree(scene)
    node = next((candidate for candidate in source.nodes if candidate.get("fbp_role", "") == "source_opacity" and candidate.get("fbp_uuid", "") == owner.layer_id), None) if source else None
    if node is None:
        if float(owner.opacity) < 0.999:
            _schedule_compositor_update(owner, context)
        return
    factor = node.inputs.get("Factor")
    if factor is None:
        _schedule_compositor_update(owner, context)
        return
    value = float(owner.opacity if owner.enabled else 0.0)
    if factor.is_linked:
        identifier = factor.links[0].from_socket.identifier
        root = scene.compositing_node_group
        for group in root.nodes if root else ():
            if getattr(group, "node_tree", None) is source:
                socket = next((item for item in group.inputs if item.identifier == identifier), None)
                if socket is not None:
                    socket.default_value = value
    else:
        factor.default_value = value
    source.update_tag()


def _update_compositor_holdout(owner, context):
    if bool(getattr(owner, "holdout", False)) and bool(
        getattr(owner, "indirect_only", False)
    ):
        owner.indirect_only = False
    _schedule_compositor_update(owner, context)


def _update_compositor_indirect(owner, context):
    if bool(getattr(owner, "indirect_only", False)) and bool(
        getattr(owner, "holdout", False)
    ):
        owner.holdout = False
    _schedule_compositor_update(owner, context)


def fbp_schedule_compositor_update(scene):
    """Debounce a source/effect rebuild after Layer List metadata changes."""
    global _FBP_COMPOSITOR_UPDATE_TIMER_RUNNING
    if scene is None or not bool(getattr(scene, "fbp_compositor_enabled", False)):
        return False
    try:
        _queue_compositor_scene(scene)
        if _FBP_COMPOSITOR_UPDATE_TIMER_RUNNING and not scheduled_task_pending(
            "compositor.live_update"
        ):
            _FBP_COMPOSITOR_UPDATE_TIMER_RUNNING = False
        if not _FBP_COMPOSITOR_UPDATE_TIMER_RUNNING:
            _FBP_COMPOSITOR_UPDATE_TIMER_RUNNING = True
            accepted = schedule_once(
                "compositor.live_update",
                _flush_compositor_updates,
                first_interval=0.15,
            )
            if not accepted or not scheduled_task_pending("compositor.live_update"):
                _FBP_COMPOSITOR_UPDATE_TIMER_RUNNING = False
                return False
        return True
    except FBP_DATA_ERRORS:
        _FBP_COMPOSITOR_UPDATE_TIMER_RUNNING = False
        return False


class FBP_CompositorEffect(PropertyGroup):
    effect_uuid: StringProperty(
        name="Effect UUID",
        description="Persistent identity used to preserve selection and active rows after stack edits",
        options={'HIDDEN'},
    )
    selected: BoolProperty(
        name="Selected",
        description="Include this effect in multi-row compositor actions",
        default=False,
    )
    enabled: BoolProperty(
        name="Enabled",
        description="Enable this compositor effect without removing its settings",
        default=True,
        update=_schedule_compositor_update,
    )
    effect_type: EnumProperty(
        name="Effect",
        description="Blender 5.2 compositor node appended at this stack position",
        items=FBP_COMPOSITOR_EFFECT_ITEMS,
        default='GLOW',
        update=_schedule_compositor_update,
    )
    effect_mix: FloatProperty(
        name="Mix", min=0.0, max=1.0, default=1.0,
        description="Blend this processed result with the previous stack image",
        update=_update_compositor_effect_parameter,
    )
    glow_threshold: FloatProperty(
        name="Threshold", min=0.0, soft_max=10.0, default=1.0,
        update=_update_compositor_effect_parameter,
    )
    glow_strength: FloatProperty(
        name="Strength", min=0.0, max=1.0, default=1.0,
        update=_update_compositor_effect_parameter,
    )
    glow_size: FloatProperty(
        name="Size", min=0.0, max=1.0, default=0.5,
        update=_update_compositor_effect_parameter,
    )
    blur_size: IntProperty(
        name="Size", min=0, soft_max=128, default=8,
        update=_update_compositor_effect_parameter,
    )
    defocus_f_stop: FloatProperty(
        name="F-Stop", min=0.0, soft_max=32.0, default=128.0,
        update=_update_compositor_effect_parameter,
    )
    defocus_blur_max: IntProperty(
        name="Max Blur", min=0, soft_max=128, default=32,
        update=_update_compositor_effect_parameter,
    )
    color_temperature: FloatProperty(
        name="Temperature", min=1000.0, max=40000.0, default=6500.0,
        update=_update_compositor_effect_parameter,
    )
    color_tint: FloatProperty(
        name="Tint", min=-100.0, max=100.0, default=10.0,
        update=_update_compositor_effect_parameter,
    )
    pixel_size: IntProperty(
        name="Pixel Size", min=2, soft_max=128, max=512, default=12,
        description="Approximate square pixel block size in output pixels",
        update=_update_compositor_effect_parameter,
    )
    vignette_factor: FloatProperty(
        name="Factor", min=0.0, max=1.0, default=0.65,
        update=_update_compositor_effect_parameter,
    )
    vignette_feather: FloatProperty(
        name="Feather", min=0.0, max=1.0, default=0.25,
        update=_update_compositor_effect_parameter,
    )
    vignette_roundness: FloatProperty(
        name="Roundness", min=0.0, max=1.0, default=0.75,
        update=_update_compositor_effect_parameter,
    )
    vignette_scale: FloatProperty(
        name="Scale", min=0.05, max=2.0, default=0.9,
        update=_update_compositor_effect_parameter,
    )
    unsharp_radius: FloatProperty(
        name="Radius", min=0.0, soft_max=32.0, max=128.0, default=2.0,
        update=_update_compositor_effect_parameter,
    )
    unsharp_factor: FloatProperty(
        name="Factor", min=0.0, soft_max=2.0, max=8.0, default=0.65,
        update=_update_compositor_effect_parameter,
    )
    unsharp_threshold: FloatProperty(
        name="Threshold", min=0.0, max=1.0, default=0.02,
        update=_update_compositor_effect_parameter,
    )
    tune_contrast: FloatProperty(
        name="Contrast", min=-1.0, max=1.0, default=0.1,
        update=_update_compositor_effect_parameter,
    )
    tune_color_boost: FloatProperty(
        name="Color Boost", min=-1.0, max=1.0, default=0.1,
        update=_update_compositor_effect_parameter,
    )
    tune_clarity: FloatProperty(
        name="Clarity", min=0.0, max=1.0, default=0.15,
        update=_update_compositor_effect_parameter,
    )
    tune_detail: FloatProperty(
        name="Detail", min=0.0, max=1.0, default=0.1,
        update=_update_compositor_effect_parameter,
    )
    tune_sharpen: FloatProperty(
        name="Sharpen", min=0.0, max=1.0, default=0.1,
        update=_update_compositor_effect_parameter,
    )
    film_grain_factor: FloatProperty(
        name="Factor", min=0.0, max=1.0, default=0.35,
        update=_update_compositor_effect_parameter,
    )
    film_grain_iso: IntProperty(
        name="ISO", min=25, soft_max=3200, max=12800, default=400,
        update=_update_compositor_effect_parameter,
    )
    film_grain_softness: FloatProperty(
        name="Softness", min=0.0, max=1.0, default=0.4,
        update=_update_compositor_effect_parameter,
    )
    film_grain_coarseness: FloatProperty(
        name="Coarseness", min=0.0, max=1.0, default=0.35,
        update=_update_compositor_effect_parameter,
    )
    film_grain_animated: BoolProperty(
        name="Animated", default=True,
        update=_update_compositor_effect_parameter,
    )
    chromatic_factor: FloatProperty(
        name="Factor", min=-1.0, max=1.0, default=0.015,
        update=_update_compositor_effect_parameter,
    )
    chromatic_samples: IntProperty(
        name="Samples", min=1, soft_max=32, max=128, default=12,
        update=_update_compositor_effect_parameter,
    )
    chromatic_fit: BoolProperty(
        name="Fit", default=True,
        update=_update_compositor_effect_parameter,
    )
    sepia_contrast: FloatProperty(
        name="Contrast", min=-1.0, max=1.0, default=0.1,
        update=_update_compositor_effect_parameter,
    )
    sepia_tone: FloatProperty(
        name="Tone", min=0.0, max=1.0, default=1.0,
        update=_update_compositor_effect_parameter,
    )
    sepia_saturation: FloatProperty(
        name="Saturation", min=0.0, max=2.0, default=0.8,
        update=_update_compositor_effect_parameter,
    )


def _update_compositor_output_exposure(owner, context):
    scene = getattr(context, "scene", None) if context is not None else getattr(owner, "id_data", None)
    if scene is None:
        return
    try:
        tree = getattr(scene, "compositing_node_group", None)
        node = next(
            (
                item for item in getattr(tree, "nodes", ())
                if _fbp_root_node_role(item) in {"layers_package", "legacy_sources"}
            ),
            None,
        )
        if node is not None:
            _sync_layers_package_socket_visibility(scene, node)
            tree.update_tag()
            return
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    _schedule_compositor_update(owner, context)


class FBP_CompositorLayer(PropertyGroup):
    layer_id: StringProperty(options={'HIDDEN'})
    row_type: EnumProperty(
        name="Row Type",
        items=(
            ('LAYER', "Layer", "Independent compositor layer"),
            ('FOLDER', "Folder", "Folder containing individually editable compositor layers"),
        ),
        default='LAYER',
        options={'HIDDEN'},
    )
    parent_folder_id: StringProperty(options={'HIDDEN'})
    output_socket_name: StringProperty(options={'HIDDEN'})
    expose_output: BoolProperty(
        name="Expose Output",
        description="Show this layer or folder as an individual output of the compact Layers node",
        default=False,
        update=_update_compositor_output_exposure,
    )
    selected: BoolProperty(
        name="Selected",
        description="Include this row in multi-row compositor actions",
        default=False,
    )
    expanded: BoolProperty(
        name="Expanded",
        description="Show the layers stored in this compositor folder",
        default=True,
    )
    source_kind: EnumProperty(
        name="Source",
        items=FBP_COMPOSITOR_SOURCE_KIND_ITEMS,
        default='MANUAL',
        options={'HIDDEN'},
    )
    source_key: StringProperty(options={'HIDDEN'})
    auto_generated: BoolProperty(default=False, options={'HIDDEN'})
    view_layer_name: StringProperty(
        name="View Layer",
        description="Name of the generated Blender View Layer",
    )
    enabled: BoolProperty(
        name="Visibility",
        description="Render and include this compositor layer or folder",
        default=True,
        update=_schedule_compositor_update,
    )
    holdout: BoolProperty(
        name="Holdout",
        description="Use this layer or all layers in this folder as holdout",
        default=False,
        update=_update_compositor_holdout,
    )
    indirect_only: BoolProperty(
        name="Indirect Light Only",
        description="Render only indirect lighting for this layer or folder",
        default=False,
        update=_update_compositor_indirect,
    )
    opacity: FloatProperty(
        name="Opacity",
        description="Folder or layer contribution to the final Over stack",
        min=0.0,
        max=1.0,
        default=1.0,
        subtype='FACTOR',
        update=_update_compositor_opacity,
    )
    use_depth: BoolProperty(
        name="Depth Pass",
        description="Enable the Blender Z/Depth pass for this View Layer",
        default=False,
        update=_schedule_compositor_update,
    )
    effects: CollectionProperty(type=FBP_CompositorEffect)
    effects_index: IntProperty(default=0)



class FBP_UL_CompositorPackageRows(UIList):
    """Compact Layers-node list with configurable row controls."""

    bl_idname = "FBP_UL_CompositorPackageRows"
    _PROFILE = "COMPOSITOR_PACKAGES"

    def filter_items(self, context, data, propname):
        mark_ui_list_draw()
        items = getattr(data, propname, ())
        flags = [self.bitflag_filter_item] * len(items)
        folders = {
            str(getattr(item, "layer_id", "") or ""): item
            for item in items
            if str(getattr(item, "row_type", 'LAYER') or 'LAYER') == 'FOLDER'
        }
        scene = getattr(context, "scene", None)
        query = str(scene.get("fbp_uilist_filter_compositor_packages", "") or "").strip().casefold() if scene else ""
        matching_folders = set()
        if query:
            for item in items:
                haystack = " ".join((str(getattr(item, "name", "") or ""), str(getattr(item, "source_kind", "") or ""))).casefold()
                if query in haystack:
                    parent_id = str(getattr(item, "parent_folder_id", "") or "")
                    while parent_id:
                        matching_folders.add(parent_id)
                        parent = folders.get(parent_id)
                        parent_id = str(getattr(parent, "parent_folder_id", "") or "") if parent else ""
        for index, item in enumerate(items):
            parent_id = str(getattr(item, "parent_folder_id", "") or "")
            visited = ()
            while parent_id and parent_id not in visited:
                visited += (parent_id,)
                parent = folders.get(parent_id)
                if parent is None:
                    break
                if not bool(getattr(parent, "expanded", True)):
                    flags[index] = 0
                    break
                parent_id = str(getattr(parent, "parent_folder_id", "") or "")
            if query and flags[index]:
                haystack = " ".join((str(getattr(item, "name", "") or ""), str(getattr(item, "source_kind", "") or ""))).casefold()
                if query not in haystack and str(getattr(item, "layer_id", "") or "") not in matching_folders:
                    flags[index] = 0
        alphabetical = bool(scene.get("fbp_uilist_sort_compositor_packages", False)) if scene else False
        reverse = bool(scene.get("fbp_uilist_reverse_compositor_packages", False)) if scene else False
        order = list(range(len(items)))
        if alphabetical:
            order.sort(key=lambda i: str(getattr(items[i], "name", "") or "").casefold())
        if reverse:
            order.reverse()
        return flags, order if order != list(range(len(items))) else []

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        mark_ui_list_draw()
        is_folder = str(getattr(item, 'row_type', 'LAYER') or 'LAYER') == 'FOLDER'
        if self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text='', icon='FILE_FOLDER' if is_folder else 'RENDERLAYERS')
            return
        row = layout.row(align=True)
        if is_folder:
            row.prop(item, 'expanded', text='', icon='DISCLOSURE_TRI_DOWN' if bool(getattr(item, 'expanded', True)) else 'DISCLOSURE_TRI_RIGHT', emboss=False)
        elif str(getattr(item, 'parent_folder_id', '') or ''):
            row.label(text='', icon='BLANK1')
        visible = set(fbp_uilist_visible_columns(context, self._PROFILE))
        for key in fbp_uilist_icon_order(context, self._PROFILE):
            if key not in visible:
                continue
            if fbp_uilist_is_spacer(key):
                fbp_draw_uilist_spacer(row)
                continue
            if key == 'package_select':
                row.prop(item, 'selected', text='', icon='CHECKBOX_HLT' if item.selected else 'CHECKBOX_DEHLT', emboss=False)
            elif key == 'package_type':
                row.label(text='', icon='FILE_FOLDER' if is_folder else 'RENDERLAYERS')
            elif key == 'label':
                row.prop(item, 'name', text='', emboss=False)
            elif key == 'package_visibility':
                row.prop(item, 'enabled', text='', icon='HIDE_OFF' if item.enabled else 'HIDE_ON', emboss=False)
            elif key == 'package_output':
                row.prop(item, 'expose_output', text='', icon='OUTPUT' if item.expose_output else 'DOT', emboss=False)


class FBP_CompositorLayersNode(bpy.types.CompositorNodeCustomGroup):
    bl_idname = "FBPCompositorLayersNode"
    bl_label = "FBP Layers"
    bl_icon = 'RENDERLAYERS'

    @classmethod
    def poll(cls, node_tree):
        return getattr(node_tree, "bl_idname", "") == 'CompositorNodeTree'

    def init(self, context):
        scene = getattr(context, "scene", None)
        token = _scene_id(scene) if scene is not None else _new_id()
        _tag_node(self, "layers_package", token)
        self.name = "FBP Layers"
        self.label = "Layers"
        self.width = 230

    def draw_buttons(self, context, layout):
        scene = getattr(context, "scene", None)
        if scene is None or not hasattr(scene, "fbp_compositor_layers"):
            layout.label(text="Scene layers unavailable", icon='ERROR')
            return
        list_box = fbp_draw_uilist_header(
            layout, context, "COMPOSITOR_PACKAGES"
        )
        list_box.template_list(
            "FBP_UL_CompositorPackageRows",
            "node",
            scene,
            "fbp_compositor_layers",
            scene,
            "fbp_compositor_layer_index",
            rows=max(4, min(8, len(scene.fbp_compositor_layers) or 4)),
        )
        controls = layout.row(align=False)
        for action, icon in (
            ('EXPOSE_SELECTED', 'OUTPUT'),
            ('HIDE_SELECTED', 'X'),
            ('SYNC', 'FILE_REFRESH'),
        ):
            op = controls.operator("fbp.compositor_package_action", text="", icon=icon)
            op.action = action
        layout.label(text="TOT / MASK are always available", icon='INFO')


class _FBP_CompositorPreviewPoll:
    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        return bool(scene is not None and fbp_feature_enabled(scene, "compositor_layers"))


class FBP_PT_CompositorLayersGroup(Panel):
    bl_label = "FBP Layers"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = 'Frame By Plane'

    @classmethod
    def poll(cls, context):
        if not _FBP_CompositorPreviewPoll.poll(context):
            return False
        node = getattr(context, "active_node", None)
        try:
            return bool(
                node is not None
                and str(getattr(node, "bl_idname", "") or "") == "CompositorNodeGroup"
                and _fbp_root_node_role(node) == "layers_package"
            )
        except FBP_DATA_ERRORS:
            return False

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        node = context.active_node
        if node.bl_idname != 'CompositorNodeGroup':
            layout.label(text="Outdated Layers node", icon='ERROR')
            layout.operator("fbp.compositor_sync", text=f"Convert with {primary_shortcut_label('G')}", icon='NODETREE')
            return
        list_box = fbp_draw_uilist_header(
            layout, context, "COMPOSITOR_PACKAGES"
        )
        list_box.template_list(
            "FBP_UL_CompositorPackageRows",
            "native_group",
            scene,
            "fbp_compositor_layers",
            scene,
            "fbp_compositor_layer_index",
            rows=8,
        )
        controls = layout.row(align=False)
        for action, icon in (
            ('EXPOSE_SELECTED', 'OUTPUT'),
            ('HIDE_SELECTED', 'X'),
            ('SYNC', 'FILE_REFRESH'),
        ):
            op = controls.operator("fbp.compositor_package_action", text="", icon=icon)
            op.action = action
        layout.label(text="Outputs follow the Layer List", icon='LINKED')
        layout.label(text="Double-click the node to edit its internal graph", icon='NODETREE')


class FBP_OT_CompositorPackageAction(_FBP_CompositorPreviewPoll, Operator):
    bl_idname = "fbp.compositor_package_action"
    bl_label = "Edit FBP Layers Package"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(items=(
        ('EXPOSE_SELECTED', "Expose Selected", "Expose selected layers or folders as node outputs"),
        ('HIDE_SELECTED', "Hide Selected", "Hide selected outputs when they are not linked"),
        ('SYNC', "Sync", "Rebuild the internal Layers group and refresh its outputs"),
    ))

    def execute(self, context):
        scene = context.scene
        if self.action in {'EXPOSE_SELECTED', 'HIDE_SELECTED'}:
            value = self.action == 'EXPOSE_SELECTED'
            changed = 0
            for item in scene.fbp_compositor_layers:
                if bool(getattr(item, 'selected', False)):
                    item.expose_output = value
                    changed += 1
            if changed == 0 and 0 <= scene.fbp_compositor_layer_index < len(scene.fbp_compositor_layers):
                scene.fbp_compositor_layers[scene.fbp_compositor_layer_index].expose_output = value
        try:
            fbp_sync_compositor(
                scene,
                context=context,
                activate_compositor=True,
            )
        except (RuntimeError, AttributeError, ReferenceError, TypeError, ValueError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class FBP_OT_CompositorAutoLayers(_FBP_CompositorPreviewPoll, Operator):
    bl_idname = "fbp.compositor_auto_layers"
    bl_label = "Generate Compositor Layers"
    bl_description = f"Generate compositor layers and package them in one native {primary_shortcut_label('G')} node group"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        added = fbp_auto_compositor_layers(scene)
        if not scene.fbp_compositor_layers:
            self.report({'WARNING'}, "No Frame By Plane layer sources found")
            return {'CANCELLED'}
        try:
            result = fbp_sync_compositor(
                scene, context=context, native_group=True, activate_compositor=True
            )
        except (RuntimeError, AttributeError, ReferenceError, TypeError, ValueError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report(
            {'INFO'},
            f"Added {added}; created native FBP Layers group with {result['layers']} sources",
        )
        return {'FINISHED'}


class FBP_OT_CompositorSelectRow(_FBP_CompositorPreviewPoll, Operator):
    bl_idname = "fbp.compositor_select_row"
    bl_label = "Select Compositor Row"
    bl_description = f"Click to select; Shift selects a range and {primary_modifier_name()} toggles individual rows"
    bl_options = {'UNDO'}

    index: IntProperty(default=-1, options={'SKIP_SAVE'})
    use_shift: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})
    use_ctrl: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        self.use_shift = bool(getattr(event, "shift", False))
        self.use_ctrl = primary_modifier_pressed(event)
        return self.execute(context)

    def execute(self, context):
        scene = context.scene
        items = scene.fbp_compositor_layers
        _ensure_compositor_layer_ids(scene)
        if not (0 <= self.index < len(items)):
            return {'CANCELLED'}
        visible = []
        collapsed = {
            item.layer_id for item in items
            if _is_folder_item(item) and not bool(getattr(item, "expanded", True))
        }
        for index, item in enumerate(items):
            parent_id = str(getattr(item, "parent_folder_id", "") or "")
            if parent_id and parent_id in collapsed:
                continue
            visible.append(index)

        anchor_index_key = "_fbp_compositor_selection_anchor"
        anchor_uid_key = "_fbp_compositor_selection_anchor_uid"
        anchor = resolve_anchor_index(
            scene, anchor_index_key, anchor_uid_key, items,
            "layer_id", fallback=self.index,
        )
        if self.use_shift and anchor in visible and self.index in visible:
            lo, hi = sorted((visible.index(anchor), visible.index(self.index)))
            selected_indices = set(visible[lo:hi + 1])
            if not self.use_ctrl:
                for item in items:
                    item.selected = False
            for index in selected_indices:
                items[index].selected = True
        elif self.use_ctrl:
            items[self.index].selected = not bool(items[self.index].selected)
            store_anchor(
                scene, anchor_index_key, anchor_uid_key, items,
                "layer_id", self.index,
            )
        else:
            for item in items:
                item.selected = False
            items[self.index].selected = True
            store_anchor(
                scene, anchor_index_key, anchor_uid_key, items,
                "layer_id", self.index,
            )
        scene.fbp_compositor_layer_index = self.index
        return {'FINISHED'}


def _compositor_delete_remap_items(self, context):
    layer_id = str(getattr(self, "layer_id", "") or "")
    return [
        (str(item.source_key or item.layer_id), item.name, "Remap references to this compositor source")
        for item in context.scene.fbp_compositor_layers
        if item.layer_id != layer_id and str(item.source_key or item.layer_id) != layer_id and not _is_folder_item(item)
    ] or [('NONE', "No replacement source", "")]


def _compositor_source_dependencies(scene, layer_id):
    try:
        from .compositor_sets import fbp_source_dependency_usage

        usage = fbp_source_dependency_usage(scene, layer_id)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        usage = {}
    dependencies = []
    for value in usage.get("layer_sets", ()):
        dependencies.append(f"Layer Set: {value}")
    for value in usage.get("outputs", ()):
        dependencies.append(f"FBP Output: {value}")
    for value in usage.get("artist_nodes", ()):
        dependencies.append(f"Connected Node: {value}")
    if not dependencies:
        for layer_set in getattr(scene, "fbp_layer_sets", ()):
            if any(row.source_uuid == layer_id for row in layer_set.rows):
                dependencies.append(f"Layer Set: {layer_set.name}")
    return list(dict.fromkeys(dependencies))


class FBP_OT_CompositorLayerAction(_FBP_CompositorPreviewPoll, Operator):
    bl_idname = "fbp.compositor_layer_action"
    bl_label = "Edit Compositor Layers"
    bl_options = {'REGISTER', 'UNDO'}

    _DESCRIPTIONS = {
        'ADD': "Add a compositor layer",
        'ADD_FOLDER': "Add an empty compositor folder",
        'GROUP_SELECTED': "Place selected compositor layers in a new folder",
        'UNGROUP_SELECTED': "Move selected compositor layers out of their folder",
        'REMOVE': "Remove the active compositor layer",
        'UP': "Move the active compositor layer up",
        'DOWN': "Move the active compositor layer down",
    }

    @classmethod
    def description(cls, context, properties):
        return cls._DESCRIPTIONS.get(str(getattr(properties, 'action', '') or ''), cls.bl_label)

    action: EnumProperty(
        items=(
            ('ADD', "Add", "Add a compositor layer"),
            ('ADD_FOLDER', "Add Folder", "Add an empty compositor folder"),
            ('GROUP_SELECTED', "Group Selected", "Place selected compositor layers in a folder"),
            ('UNGROUP_SELECTED', "Ungroup Selected", "Remove selected layers from their folder"),
            ('REMOVE', "Remove", "Remove the active compositor layer"),
            ('UP', "Up", "Move the active layer earlier in the composite stack"),
            ('DOWN', "Down", "Move the active layer later in the composite stack"),
        )
    )
    layer_id: StringProperty(
        name="Layer ID",
        description="Persistent ID of the row targeted by an inline action",
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    reference_action: EnumProperty(
        name="References",
        items=(
            ('CANCEL', "Cancel", "Keep the source and all references"),
            ('DISABLE', "Disable References", "Turn off references, then remove the source"),
            ('REMAP', "Remap", "Move references to another source before deletion"),
            ('DELETE', "Delete Anyway", "Keep dependent rows as Missing so links can be repaired later"),
        ),
        default='CANCEL',
        options={'SKIP_SAVE'},
    )
    remap_layer_id: EnumProperty(name="Replacement", items=_compositor_delete_remap_items, options={'SKIP_SAVE'})

    def invoke(self, context, event):
        if self.action != 'REMOVE':
            return self.execute(context)
        items = context.scene.fbp_compositor_layers
        layer_id = self.layer_id
        if not layer_id and 0 <= context.scene.fbp_compositor_layer_index < len(items):
            layer_id = items[context.scene.fbp_compositor_layer_index].layer_id
            self.layer_id = layer_id
        item = _item_by_id(context.scene, layer_id)
        source_uuid = str(item.source_key or item.layer_id) if item is not None else layer_id
        if source_uuid and _compositor_source_dependencies(context.scene, source_uuid):
            return context.window_manager.invoke_props_dialog(self, width=440)
        self.reference_action = 'DELETE'
        return self.execute(context)

    def draw(self, context):
        layout = self.layout
        item = _item_by_id(context.scene, self.layer_id)
        source_uuid = str(item.source_key or item.layer_id) if item is not None else self.layer_id
        dependencies = _compositor_source_dependencies(context.scene, source_uuid)
        layout.label(text=f"This source is used by {len(dependencies)} dependency item(s).", icon='ERROR')
        for name in dependencies[:6]:
            layout.label(text=name, icon='LINKED')
        layout.prop(self, "reference_action", expand=True)
        if self.reference_action == 'REMAP':
            layout.prop(self, "remap_layer_id")

    def execute(self, context):
        scene = context.scene
        items = scene.fbp_compositor_layers
        _ensure_compositor_layer_ids(scene)
        index = int(scene.fbp_compositor_layer_index)
        if self.layer_id:
            index = next(
                (
                    row_index
                    for row_index, item in enumerate(items)
                    if str(getattr(item, "layer_id", "") or "") == self.layer_id
                ),
                -1,
            )
            if index >= 0:
                scene.fbp_compositor_layer_index = index
        if self.action == 'ADD':
            fbp_add_compositor_layer(scene)
            return {'FINISHED'}
        if self.action == 'ADD_FOLDER':
            folder = fbp_add_compositor_layer(scene, "Folder")
            folder.row_type = 'FOLDER'
            folder.source_kind = 'MANUAL'
            folder.view_layer_name = ""
            return {'FINISHED'}
        if self.action == 'GROUP_SELECTED':
            selected_indices = [
                i for i, item in enumerate(items)
                if bool(getattr(item, "selected", False)) and not _is_folder_item(item)
            ]
            if not selected_indices and 0 <= index < len(items) and not _is_folder_item(items[index]):
                selected_indices = [index]
            if not selected_indices:
                return {'CANCELLED'}
            insert_at = min(selected_indices)
            child_ids = [items[i].layer_id for i in selected_indices]
            folder = items.add()
            folder.layer_id = _new_id()
            folder.name = "Folder"
            folder.row_type = 'FOLDER'
            folder.source_kind = 'MANUAL'
            folder.view_layer_name = ""
            folder_id = folder.layer_id
            items.move(len(items) - 1, insert_at)
            target = insert_at + 1
            for child_id in child_ids:
                current = next(
                    (i for i, item in enumerate(items) if item.layer_id == child_id),
                    -1,
                )
                if current < 0:
                    continue
                items[current].parent_folder_id = folder_id
                items.move(current, target)
                target += 1
            resolved_folder = _item_by_id(scene, folder_id)
            if resolved_folder is not None:
                resolved_folder.selected = True
            scene.fbp_compositor_layer_index = insert_at
            if scene.fbp_compositor_enabled:
                fbp_sync_compositor(scene)
            return {'FINISHED'}
        if self.action == 'UNGROUP_SELECTED':
            targets = [
                item for item in items
                if bool(getattr(item, "selected", False))
                and not _is_folder_item(item)
                and str(getattr(item, "parent_folder_id", "") or "")
            ]
            if not targets and 0 <= index < len(items):
                active_item = items[index]
                if (
                    not _is_folder_item(active_item)
                    and str(getattr(active_item, "parent_folder_id", "") or "")
                ):
                    targets = [active_item]
            for item in targets:
                item.parent_folder_id = ""
            if targets and scene.fbp_compositor_enabled:
                fbp_sync_compositor(scene)
            return {'FINISHED'} if targets else {'CANCELLED'}
        if not (0 <= index < len(items)):
            return {'CANCELLED'}
        if self.action == 'REMOVE':
            layer_id = items[index].layer_id
            source_uuid = str(items[index].source_key or layer_id)
            dependencies = _compositor_source_dependencies(scene, source_uuid)
            if dependencies and self.reference_action == 'CANCEL':
                return {'CANCELLED'}
            if dependencies and self.reference_action in {'DISABLE', 'REMAP'}:
                try:
                    from .compositor_sets import _row_socket_linked
                    replacement = next((item for item in items if str(item.source_key or item.layer_id) == self.remap_layer_id), None) if self.reference_action == 'REMAP' else None
                    if self.reference_action == 'REMAP' and replacement is None:
                        self.report({'WARNING'}, "Choose a valid replacement source")
                        return {'CANCELLED'}
                    replacement_uuid = str(replacement.source_key or replacement.layer_id) if replacement is not None else ""
                    for layer_set in scene.fbp_layer_sets:
                        row = next((candidate for candidate in layer_set.rows if candidate.source_uuid == source_uuid), None)
                        if row is None:
                            continue
                        if replacement is None:
                            row.eye = False
                            row.pinned = False
                            row.override = 'EXCLUDE'
                            continue
                        existing = next((candidate for candidate in layer_set.rows if candidate.source_uuid == replacement_uuid and candidate != row), None)
                        if existing is not None:
                            row_protected = row.pinned or _row_socket_linked(scene, layer_set, row)
                            existing_protected = existing.pinned or _row_socket_linked(scene, layer_set, existing)
                            if row_protected and existing_protected:
                                self.report({'WARNING'}, f"Both remap sockets are pinned or linked in {layer_set.name}")
                                return {'CANCELLED'}
                            keeper, removed = (row, existing) if row_protected else (existing, row)
                            keeper.eye = keeper.eye or removed.eye
                            keeper.selected = keeper.selected or removed.selected
                            keeper.pinned = keeper.pinned or removed.pinned
                            if hasattr(keeper, "exclusive_excluded"):
                                keeper.exclusive_excluded = bool(
                                    getattr(keeper, "exclusive_excluded", False)
                                    and getattr(removed, "exclusive_excluded", False)
                                )
                            if keeper.override == 'AUTO' and removed.override != 'AUTO':
                                keeper.override = removed.override
                            removed_pointer = int(removed.as_pointer())
                            removed_index = next(i for i, candidate in enumerate(layer_set.rows) if int(candidate.as_pointer()) == removed_pointer)
                            layer_set.rows.remove(removed_index)
                            row = keeper
                        row.source_uuid = replacement_uuid
                        row.name = replacement.name
                        row.missing = False
                except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
                    fbp_warn("Could not update compositor dependencies", exc)
                    return {'CANCELLED'}
            if _is_folder_item(items[index]):
                for child in items:
                    if str(getattr(child, "parent_folder_id", "") or "") == layer_id:
                        child.parent_folder_id = ""
            for collection in fbp_compositor_group_collections(scene):
                if str(getattr(collection, "fbp_compositor_layer_id", "") or "") == layer_id:
                    collection.fbp_compositor_layer_id = ""
            removed_layer_id = layer_id
            items.remove(index)
            anchor_uid = str(transient_get(scene, "_fbp_compositor_selection_anchor_uid", "") or "")
            if anchor_uid == removed_layer_id:
                if items:
                    store_anchor(
                        scene, "_fbp_compositor_selection_anchor",
                        "_fbp_compositor_selection_anchor_uid", items,
                        "layer_id", min(index, len(items) - 1),
                    )
                else:
                    clear_anchor(
                        scene, "_fbp_compositor_selection_anchor",
                        "_fbp_compositor_selection_anchor_uid",
                    )
            if self.reference_action == 'REMAP' and hasattr(scene, "fbp_compositor_sources"):
                for record_index in reversed(range(len(scene.fbp_compositor_sources))):
                    if scene.fbp_compositor_sources[record_index].source_uuid == source_uuid:
                        scene.fbp_compositor_sources.remove(record_index)
            scene.fbp_compositor_layer_index = min(index, len(items) - 1) if items else 0
        else:
            target = index + (-1 if self.action == 'UP' else 1)
            if target < 0 or target >= len(items):
                return {'CANCELLED'}
            items.move(index, target)
            scene.fbp_compositor_layer_index = target
        if items and scene.fbp_compositor_enabled:
            fbp_sync_compositor(scene)
        return {'FINISHED'}


class FBP_OT_CompositorEffectSelectRow(_FBP_CompositorPreviewPoll, Operator):
    bl_idname = "fbp.compositor_effect_select_row"
    bl_label = "Select Compositor Effect"
    bl_description = f"Select one effect; Shift selects a range and {primary_modifier_name()} toggles one row"
    bl_options = {'INTERNAL'}

    layer_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    index: IntProperty(default=-1, options={'HIDDEN', 'SKIP_SAVE'})
    use_shift: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})
    use_ctrl: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        return invoke_with_selection_modifiers(self, context, event)

    def execute(self, context):
        scene = context.scene
        layer = _item_by_id(scene, self.layer_id)
        if layer is None or not (0 <= self.index < len(layer.effects)):
            return {'CANCELLED'}
        _ensure_compositor_effect_ids(layer)
        anchor_index_key = f"_fbp_compositor_effect_anchor_{self.layer_id[:12]}"
        anchor_uid_key = f"_fbp_compositor_effect_anchor_uid_{self.layer_id[:12]}"
        anchor = resolve_anchor_index(
            scene, anchor_index_key, anchor_uid_key, layer.effects,
            "effect_uuid", fallback=self.index,
        )
        lo, hi = sorted((anchor, self.index))
        for row_index, effect in enumerate(layer.effects):
            if self.use_shift:
                selected = (lo <= row_index <= hi) or (
                    self.use_ctrl and bool(effect.selected)
                )
            elif self.use_ctrl:
                selected = not bool(effect.selected) if row_index == self.index else bool(effect.selected)
            else:
                selected = row_index == self.index
            effect.selected = selected
        layer.effects_index = self.index
        scene.fbp_compositor_layer_index = next(
            (
                index for index, item in enumerate(scene.fbp_compositor_layers)
                if item.layer_id == self.layer_id
            ),
            scene.fbp_compositor_layer_index,
        )
        if not self.use_shift:
            store_anchor(
                scene, anchor_index_key, anchor_uid_key, layer.effects,
                "effect_uuid", self.index,
            )
        return {'FINISHED'}


class FBP_OT_CompositorEffectAction(_FBP_CompositorPreviewPoll, Operator):
    bl_idname = "fbp.compositor_effect_action"
    bl_label = "Edit Compositor Effect Stack"
    bl_description = "Add, remove, or reorder compositor effects on the active output layer"
    bl_options = {'REGISTER', 'UNDO'}

    _DESCRIPTIONS = {
        'ADD': "Add a compositor effect to the selected layers",
        'REMOVE': "Remove the selected compositor effects",
        'UP': "Move the active compositor effect earlier in the chain",
        'DOWN': "Move the active compositor effect later in the chain",
    }

    @classmethod
    def description(cls, context, properties):
        action = str(getattr(properties, 'action', '') or '')
        return cls._DESCRIPTIONS.get(action, cls.bl_description)

    action: EnumProperty(
        items=(
            ('ADD', "Add", "Add a compositor effect"),
            ('REMOVE', "Remove", "Remove the active compositor effect"),
            ('UP', "Up", "Move the active effect earlier in the node chain"),
            ('DOWN', "Down", "Move the active effect later in the node chain"),
        ),
        default='ADD',
    )
    effect_type: EnumProperty(
        name="Effect",
        items=FBP_COMPOSITOR_ADD_EFFECT_ITEMS,
        default='GLOW',
    )

    def execute(self, context):
        scene = context.scene
        layer_index = int(scene.fbp_compositor_layer_index)
        if not (0 <= layer_index < len(scene.fbp_compositor_layers)):
            self.report({'WARNING'}, "Select a compositor layer first")
            return {'CANCELLED'}
        layer_item = scene.fbp_compositor_layers[layer_index]
        _normalize_layer_effect_stack(layer_item)
        effects = layer_item.effects
        _ensure_compositor_effect_ids(layer_item)
        index = int(layer_item.effects_index)
        if self.action == 'ADD':
            targets = [
                item for item in scene.fbp_compositor_layers
                if bool(getattr(item, "selected", False))
            ] or [layer_item]
            for target_item in targets:
                _normalize_layer_effect_stack(target_item)
                effect = target_item.effects.add()
                effect.effect_uuid = _new_id()
                effect.effect_type = self.effect_type
                effect.name = {
                    identifier: label
                    for identifier, label, _description in FBP_COMPOSITOR_EFFECT_ITEMS
                }.get(self.effect_type, "Effect")
                target_item.effects_index = len(target_item.effects) - 1
                store_anchor(
                    scene,
                    f"_fbp_compositor_effect_anchor_{target_item.layer_id[:12]}",
                    f"_fbp_compositor_effect_anchor_uid_{target_item.layer_id[:12]}",
                    target_item.effects, "effect_uuid", target_item.effects_index,
                )
        elif not (0 <= index < len(effects)):
            return {'CANCELLED'}
        elif self.action == 'REMOVE':
            active_uuid = ensure_item_identity(effects[index], "effect_uuid")
            selected_indices = [
                row_index for row_index, effect in enumerate(effects)
                if bool(getattr(effect, "selected", False))
            ] or [index]
            removed_uuids = {
                ensure_item_identity(effects[row_index], "effect_uuid")
                for row_index in selected_indices
            }
            anchor_index_key = f"_fbp_compositor_effect_anchor_{layer_item.layer_id[:12]}"
            anchor_uid_key = f"_fbp_compositor_effect_anchor_uid_{layer_item.layer_id[:12]}"
            anchor_uid = str(transient_get(scene, anchor_uid_key, "") or "")
            for row_index in reversed(selected_indices):
                effects.remove(row_index)
            if effects:
                layer_item.effects_index = restore_active_index(
                    effects, "effect_uuid",
                    "" if active_uuid in removed_uuids else active_uuid,
                    fallback=min(selected_indices[0], len(effects) - 1),
                )
                if anchor_uid in removed_uuids:
                    store_anchor(
                        scene, anchor_index_key, anchor_uid_key, effects,
                        "effect_uuid", layer_item.effects_index,
                    )
            else:
                layer_item.effects_index = 0
                clear_anchor(scene, anchor_index_key, anchor_uid_key)
        else:
            active_uuid = ensure_item_identity(effects[index], "effect_uuid")
            selected_indices = [
                row_index for row_index, effect in enumerate(effects)
                if bool(getattr(effect, "selected", False))
            ] or [index]
            selected_set = set(selected_indices)
            moved = False
            if self.action == 'UP':
                for row_index in selected_indices:
                    if row_index > 0 and row_index - 1 not in selected_set:
                        effects.move(row_index, row_index - 1)
                        selected_set.remove(row_index)
                        selected_set.add(row_index - 1)
                        moved = True
            else:
                for row_index in reversed(selected_indices):
                    if row_index + 1 < len(effects) and row_index + 1 not in selected_set:
                        effects.move(row_index, row_index + 1)
                        selected_set.remove(row_index)
                        selected_set.add(row_index + 1)
                        moved = True
            if not moved:
                return {'CANCELLED'}
            layer_item.effects_index = restore_active_index(
                effects, "effect_uuid", active_uuid, fallback=min(selected_set),
            )
        if scene.fbp_compositor_enabled:
            _FBP_PENDING_COMPOSITOR_SCENES.discard(_scene_runtime_key(scene))
            fbp_sync_compositor(scene)
        return {'FINISHED'}


class FBP_OT_CompositorAssignGroup(_FBP_CompositorPreviewPoll, Operator):
    bl_idname = "fbp.compositor_assign_group"
    bl_label = "Assign Active FBP Group"
    bl_description = "Assign the active Layer Stack group to the selected compositor layer"
    bl_options = {'REGISTER', 'UNDO'}

    clear: BoolProperty(default=False, options={'HIDDEN'})

    def execute(self, context):
        from .layers import fbp_active_work_collection

        scene = context.scene
        collection = fbp_active_work_collection(context)
        if collection is None or not bool(getattr(collection, "is_fbp_collection", False)):
            self.report({'WARNING'}, "Select a Frame By Plane group in the Layer Stack")
            return {'CANCELLED'}
        if self.clear:
            collection.fbp_compositor_layer_id = ""
        else:
            index = int(scene.fbp_compositor_layer_index)
            if not (0 <= index < len(scene.fbp_compositor_layers)):
                self.report({'WARNING'}, "Select a compositor layer first")
                return {'CANCELLED'}
            collection.fbp_compositor_layer_id = scene.fbp_compositor_layers[index].layer_id
        if scene.fbp_compositor_enabled:
            fbp_sync_compositor(scene)
        return {'FINISHED'}


class FBP_OT_CompositorSync(_FBP_CompositorPreviewPoll, Operator):
    bl_idname = "fbp.compositor_sync"
    bl_label = "Build / Sync Compositor"
    bl_description = f"Build the compositor and convert FBP Layers through Blender’s native {primary_shortcut_label('G')} operator"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            result = fbp_sync_compositor(
                context.scene, context=context, native_group=True, activate_compositor=True
            )
        except (RuntimeError, AttributeError, ReferenceError, TypeError, ValueError) as exc:
            fbp_warn("Could not sync FBP compositor", exc)
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, f"Synced {result['layers']} compositor layers")
        return {'FINISHED'}


class FBP_OT_CompositorRepairRebuild(_FBP_CompositorPreviewPoll, Operator):
    bl_idname = "fbp.compositor_repair_rebuild"
    bl_label = "Repair / Rebuild FBP Compositor"
    bl_description = "Rebuild only Frame By Plane technical nodes while preserving artist nodes, Layer Set state and reconstructible links"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        try:
            result = fbp_sync_compositor(
                context.scene, context=context, native_group=True, activate_compositor=True
            )
        except (RuntimeError, AttributeError, ReferenceError, TypeError, ValueError) as exc:
            fbp_warn("Could not repair FBP compositor", exc)
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, f"Rebuilt {result['layers']} sources; artist nodes preserved")
        return {'FINISHED'}


class FBP_OT_CompositorRestore(_FBP_CompositorPreviewPoll, Operator):
    bl_idname = "fbp.compositor_restore"
    bl_label = "Restore Native Compositor"
    bl_description = "Remove generated View Layers and restore the previous compositor setup"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            fbp_restore_compositor(context.scene, remove_generated=True)
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not restore native compositor", exc)
            self.report({'ERROR'}, "Restore stopped safely; no further changes were applied")
            return {'CANCELLED'}
        self.report({'INFO'}, "Native compositor restored")
        return {'FINISHED'}


classes = (
    FBP_CompositorEffect,
    FBP_CompositorLayer,
    FBP_UL_CompositorPackageRows,
    FBP_CompositorLayersNode,
    FBP_PT_CompositorLayersGroup,
    FBP_OT_CompositorPackageAction,
    FBP_OT_CompositorAutoLayers,
    FBP_OT_CompositorSelectRow,
    FBP_OT_CompositorLayerAction,
    FBP_OT_CompositorEffectSelectRow,
    FBP_OT_CompositorEffectAction,
    FBP_OT_CompositorAssignGroup,
    FBP_OT_CompositorSync,
    FBP_OT_CompositorRepairRebuild,
    FBP_OT_CompositorRestore,
)


_SCENE_PROPERTIES = (
    "fbp_compositor_scene_id",
    "fbp_compositor_enabled",
    "fbp_compositor_render_enabled",
    "fbp_compositor_transparent",
    "fbp_compositor_include_unassigned",
    "fbp_compositor_disable_unmanaged_layers",
    "fbp_compositor_generation_mode",
    "fbp_compositor_layers",
    "fbp_compositor_layer_index",
    "fbp_compositor_previous_group",
    "fbp_compositor_previous_use_compositing",
    "fbp_compositor_previous_film_transparent",
    "fbp_compositor_status",
)


def _remove_compositor_properties():
    removed = unregister_type_properties(
        bpy.types.Object, ("fbp_compositor_source_id",)
    )
    removed += unregister_type_properties(
        bpy.types.Collection,
        ("fbp_layer_group", "fbp_compositor_source_id", "fbp_compositor_layer_id"),
    )
    removed += unregister_type_properties(bpy.types.Scene, _SCENE_PROPERTIES)
    return removed


def register():
    register_classes(classes)
    try:
        bpy.types.Scene.fbp_compositor_scene_id = StringProperty(options={'HIDDEN'})
        bpy.types.Scene.fbp_compositor_enabled = BoolProperty(default=False, options={'HIDDEN'})
        bpy.types.Scene.fbp_compositor_render_enabled = BoolProperty(
            name="Use Compositor in Render",
            description=(
                "Explicitly use the managed Frame By Plane compositor for renders; "
                "leave disabled to build and edit the graph without activating it"
            ),
            default=False,
            update=_update_render_compositor_opt_in,
        )
        bpy.types.Scene.fbp_compositor_transparent = BoolProperty(
            name="Transparent Film",
            description=(
                "Use transparent film for alpha-ready output while the Frame By Plane "
                "compositor is enabled for renders"
            ),
            default=True,
            update=_update_transparency,
        )
        bpy.types.Scene.fbp_compositor_include_unassigned = BoolProperty(
            name="Share Unassigned Groups",
            description="Include groups without an explicit assignment in every managed layer",
            default=False,
        )
        bpy.types.Scene.fbp_compositor_disable_unmanaged_layers = BoolProperty(
            name="Render Managed Layers Only",
            description="Temporarily disable native View Layers that are not part of this stack to avoid duplicate rendering",
            default=True,
        )
        bpy.types.Scene.fbp_compositor_generation_mode = EnumProperty(
            name="Layer Source",
            description="Choose how the Layer List becomes isolated Blender View Layers",
            items=FBP_COMPOSITOR_GENERATION_ITEMS,
            default='LAYERS_GROUPS',
        )
        bpy.types.Scene.fbp_compositor_layers = CollectionProperty(type=FBP_CompositorLayer)
        bpy.types.Scene.fbp_compositor_layer_index = IntProperty(default=0)
        bpy.types.Scene.fbp_compositor_previous_group = PointerProperty(type=NodeTree)
        bpy.types.Scene.fbp_compositor_previous_use_compositing = BoolProperty(default=False, options={'HIDDEN'})
        bpy.types.Scene.fbp_compositor_previous_film_transparent = BoolProperty(
            default=False,
            options={'HIDDEN'},
        )
        bpy.types.Scene.fbp_compositor_status = StringProperty(options={'HIDDEN'})
        bpy.types.Collection.fbp_compositor_layer_id = StringProperty(
            name="Compositor Layer",
            description="Persistent assignment of this FBP group to a compositor output layer",
            default="",
        )
        bpy.types.Collection.fbp_compositor_source_id = StringProperty(
            name="Compositor Source ID",
            default="",
            options={'HIDDEN'},
        )
        bpy.types.Collection.fbp_layer_group = BoolProperty(
            name="Layer List Group",
            description=f"Collection created by the Layer List {primary_shortcut_label('G')} grouping workflow",
            default=False,
            options={'HIDDEN'},
        )
        bpy.types.Object.fbp_compositor_source_id = StringProperty(
            name="Compositor Source ID",
            default="",
            options={'HIDDEN'},
        )
        register_service("compositor.auto_layers", fbp_auto_compositor_layers, owner=__name__)
        register_service("compositor.sync", fbp_sync_compositor, owner=__name__)
        register_service("compositor.ensure_asset_group", _ensure_compositor_asset_group, owner=__name__)
    except Exception:
        unregister_service("compositor.ensure_asset_group")
        unregister_service("compositor.sync")
        unregister_service("compositor.auto_layers")
        _remove_compositor_properties()
        unregister_classes(classes)
        raise


def unregister():
    global _FBP_COMPOSITOR_UPDATE_TIMER_RUNNING
    unregister_service("compositor.ensure_asset_group")
    unregister_service("compositor.sync")
    unregister_service("compositor.auto_layers")
    _FBP_PENDING_COMPOSITOR_SCENES.clear()
    _FBP_COMPOSITOR_UPDATE_RETRIES.clear()
    cancel_scheduled_prefixes("compositor.live_update")
    _FBP_COMPOSITOR_UPDATE_TIMER_RUNNING = False
    _remove_compositor_properties()
    unregister_classes(classes)
