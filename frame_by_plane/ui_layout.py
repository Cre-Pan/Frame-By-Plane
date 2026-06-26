"""Reusable UI layout helpers for Frame by Plane panels and lists."""

import os

import bpy

from .constants import fbp_icon
from .path_utils import (
    is_supported_media_file,
    is_supported_video_file,
    is_technical_map_file,
    natural_sort_key,
)
from .runtime import (
    fbp_warn, FBP_DATA_ERRORS, FBP_DATA_IO_ERRORS,
    fbp_obj_runtime_key, fbp_find_id_by_runtime_key,
)
from .layers import (
    fbp_prime_collection_ui_state_cache,
    fbp_layer_depth_value_from_cache,
    fbp_make_depth_context_cache,
    get_primary_fbp_collection,
    is_fbp_layer_object,
)
from .core import (
    draw_scene_fbp_color_ramp,
    fbp_draw_color_plane_color_row,
    fbp_draw_gradient_choice_rows,
    pending_collection_is_open,
)
from .ui_icons import ui_icon
from . import safe_tasks as _safe_tasks


# SECTION 01 - Multiplane Setup: layout helpers #
# ###ICON Panel Multiplane Setup, Function Collection: setup.collection
# ###ICON Panel Multiplane Setup, Function Collapse: setup.collapse_closed / setup.collapse_open
# ###ICON Panel Multiplane Setup, Function Remove: setup.remove
# ###ICON Panel Multiplane Setup, Function Sequence/Image: setup.sequence / setup.image


def _fbp_pending_collection_parts(name):
    """Split a setup collection path into visual tree parts."""
    raw = (name or "").strip()
    if not raw:
        return ["Unsorted"]
    return [part.strip() for part in raw.split('/') if part.strip()] or ["Unsorted"]


def _fbp_pending_tree(scene):
    """Build a lightweight tree from fbp_pending_planes collection_name values."""
    root = {"children": {}, "items": []}
    for index, item in enumerate(getattr(scene, 'fbp_pending_planes', [])):
        collection_name = (getattr(item, 'collection_name', '') or '').strip()
        if not collection_name:
            # Empty collection means a real root-level layer, not an "Unsorted"
            # virtual collection. This keeps single-sequence and single-static-image folders from
            # being displayed/generated as redundant folder collections.
            root["items"].append((index, item))
            continue
        parts = _fbp_pending_collection_parts(collection_name)
        node = root
        for depth, part in enumerate(parts):
            path = ' / '.join(parts[:depth + 1])
            node = node["children"].setdefault(part, {"path": path, "name": part, "children": {}, "items": []})
        node["items"].append((index, item))
    return root

def _fbp_pending_files(item):
    try:
        return tuple(
            name for name in str(getattr(item, "files_str", "") or "").split("|")
            if name
        )
    except FBP_DATA_ERRORS:
        return ()


def _fbp_pending_layer_can_split(item, files=None):
    files = tuple(files) if files is not None else _fbp_pending_files(item)
    return bool(
        len(files) > 1
        and all(
            is_supported_media_file(name)
            and not is_supported_video_file(name)
            and not is_technical_map_file(name)
            for name in files
        )
    )


def _fbp_pending_group_can_merge(node):
    if node.get("children"):
        return False
    items = tuple(node.get("items", ()) or ())
    if len(items) < 2:
        return False
    directories = set()
    for _index, item in items:
        files = _fbp_pending_files(item)
        if len(files) != 1:
            return False
        filename = files[0]
        if (
            not is_supported_media_file(filename)
            or is_supported_video_file(filename)
            or is_technical_map_file(filename)
        ):
            return False
        directory = str(getattr(item, "directory", "") or "").strip()
        if not directory:
            return False
        directories.add(os.path.normcase(os.path.abspath(bpy.path.abspath(directory))))
        if len(directories) > 1:
            return False
    return True


def _fbp_pending_collection_color_is_editable(node):
    """True only when direct rows really inherit this collection color."""
    if node.get('children'):
        return False
    items = list(node.get('items', []))
    return bool(items) and all(bool(getattr(item, 'follow_collection_color', True)) for _index, item in items)


def _fbp_pending_collection_display_color(node):
    """Return the effective collection color shown by a setup group row."""
    if not _fbp_pending_collection_color_is_editable(node):
        return 'NONE'
    tags = []
    for _index, item in node.get('items', []):
        tag = str(getattr(item, 'fbp_color_tag', 'COLOR_09') or 'COLOR_09')
        if tag == 'COLOR_09':
            tag = 'NONE'
        if tag not in {'NONE', 'COLOR_01', 'COLOR_02', 'COLOR_03', 'COLOR_04', 'COLOR_05', 'COLOR_06', 'COLOR_07', 'COLOR_08'}:
            tag = 'NONE'
        tags.append(tag)
    if not tags:
        return 'NONE'
    return tags[-1]


def fbp_apply_pending_collection_color(scene, collection_path, color_tag):
    """Apply an editable preview collection color to its direct pending layers."""
    path = (collection_path or '').strip()
    tag = str(color_tag or 'NONE')
    if tag not in {'NONE', 'COLOR_01', 'COLOR_02', 'COLOR_03', 'COLOR_04', 'COLOR_05', 'COLOR_06', 'COLOR_07', 'COLOR_08'}:
        tag = 'NONE'
    layer_tag = 'COLOR_09' if tag == 'NONE' else tag
    changed = False
    for item in getattr(scene, 'fbp_pending_planes', []):
        if (getattr(item, 'collection_name', '') or '').strip() != path:
            continue
        if not bool(getattr(item, 'follow_collection_color', True)):
            continue
        if getattr(item, 'fbp_color_tag', 'COLOR_09') != layer_tag:
            item.fbp_color_tag = layer_tag
            changed = True
    return changed


def fbp_rebuild_pending_tree_rows(scene):
    """Rebuild the virtual UIList rows for the Multiplane Setup tree.

    The actual import data stays in scene.fbp_pending_planes. This function only
    creates visible rows for the UIList: folder group rows + layer rows.
    Collapsed folders skip their children, exactly like a normal tree view.
    """
    rows = getattr(scene, 'fbp_pending_tree_rows', None)
    if rows is None:
        return

    try:
        previous_active = int(getattr(scene, 'fbp_pending_tree_rows_idx', 0))
    except Exception:
        previous_active = 0

    # Preserve the logical row instead of only its visual index. Collapsing,
    # renaming or reordering a collection can insert/remove virtual rows before
    # the active item; keeping only the old integer made selection jump to an
    # unrelated layer.
    previous_key = None
    try:
        if 0 <= previous_active < len(rows):
            active_row = rows[previous_active]
            if getattr(active_row, 'row_type', 'LAYER') == 'GROUP':
                previous_key = ('GROUP', str(getattr(active_row, 'collection_path', '') or ''))
            else:
                pending_index = int(getattr(active_row, 'pending_index', -1))
                pending = getattr(scene, 'fbp_pending_planes', ())
                if 0 <= pending_index < len(pending):
                    active_item = pending[pending_index]
                    previous_key = (
                        'LAYER',
                        str(getattr(active_item, 'name', '') or ''),
                        str(getattr(active_item, 'collection_name', '') or ''),
                        str(getattr(active_item, 'directory', '') or ''),
                        str(getattr(active_item, 'files_str', '') or ''),
                    )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError):
        previous_key = None

    rows.clear()

    tree = _fbp_pending_tree(scene)
    sort_alpha = bool(getattr(scene, 'fbp_sort_layers_alpha', False))

    def add_layer_row(index, item, depth, *, can_move_up=False, can_move_down=False):
        row = rows.add()
        row.row_type = 'LAYER'
        row.name = getattr(item, 'name', '') or 'Unnamed Layer'
        row.collection_path = getattr(item, 'collection_name', '') or 'Unsorted'
        files = _fbp_pending_files(item)
        row.pending_index = int(index)
        row.depth = max(0, int(depth))
        row.file_count = len(files)
        row.layer_count = 0
        row.child_count = 0
        row.can_move_up = bool(can_move_up)
        row.can_move_down = bool(can_move_down)
        row.can_toggle_structure = _fbp_pending_layer_can_split(item, files)

    def add_node(node, depth=0):
        children = list(node.get('children', {}).values())
        items = list(node.get('items', []))

        if sort_alpha:
            children.sort(key=lambda n: natural_sort_key(n.get('name', '')))
            items.sort(key=lambda pair: natural_sort_key(getattr(pair[1], 'name', '')))

        for child in children:
            path = child.get('path', child.get('name', '')) or 'Unsorted'
            group = rows.add()
            group.row_type = 'GROUP'
            group.name = child.get('name', '') or 'Unsorted'
            group.collection_path = path
            group.pending_index = -1
            group.depth = max(0, int(depth))
            group.file_count = 0
            group.layer_count = len(child.get('items', []))
            group.child_count = len(child.get('children', {}))
            group.can_toggle_structure = _fbp_pending_group_can_merge(child)
            group.collection_color_editable = _fbp_pending_collection_color_is_editable(child)
            group.collection_color_tag = _fbp_pending_collection_display_color(child)

            if pending_collection_is_open(scene, path):
                add_node(child, depth + 1)

        item_count = len(items)
        for position, (index, item) in enumerate(items):
            add_layer_row(
                index,
                item,
                depth,
                can_move_up=bool(not sort_alpha and position > 0),
                can_move_down=bool(not sort_alpha and position < item_count - 1),
            )

    add_node(tree, 0)

    try:
        restored_index = -1
        if previous_key:
            for row_index, row in enumerate(rows):
                if previous_key[0] == 'GROUP':
                    candidate = ('GROUP', str(getattr(row, 'collection_path', '') or ''))
                else:
                    pending_index = int(getattr(row, 'pending_index', -1))
                    pending = getattr(scene, 'fbp_pending_planes', ())
                    if not (0 <= pending_index < len(pending)):
                        continue
                    pending_item = pending[pending_index]
                    candidate = (
                        'LAYER',
                        str(getattr(pending_item, 'name', '') or ''),
                        str(getattr(pending_item, 'collection_name', '') or ''),
                        str(getattr(pending_item, 'directory', '') or ''),
                        str(getattr(pending_item, 'files_str', '') or ''),
                    )
                if candidate == previous_key:
                    restored_index = row_index
                    break
        if len(rows):
            if restored_index < 0:
                restored_index = min(max(0, previous_active), len(rows) - 1)
            scene.fbp_pending_tree_rows_idx = restored_index
        else:
            scene.fbp_pending_tree_rows_idx = 0
    except FBP_DATA_IO_ERRORS:
        pass


def fbp_schedule_pending_tree_rebuild(scene):
    """Schedule a safe rebuild of virtual Multiplane Setup UIList rows.

    UI draw callbacks cannot write to Scene data. This schedules the rebuild
    for the next safe timer tick instead of calling rows.clear()/rows.add()
    from draw(). Operators still call fbp_rebuild_pending_tree_rows() directly.
    """
    rows = getattr(scene, 'fbp_pending_tree_rows', None)
    pending = getattr(scene, 'fbp_pending_planes', None)
    if rows is None or pending is None:
        return

    # If rows already exist, do not constantly rebuild during redraw.
    try:
        if len(rows) > 0:
            return
    except FBP_DATA_IO_ERRORS:
        pass

    scene_key = fbp_obj_runtime_key(scene)
    try:
        scene_name = str(scene.name)
    except FBP_DATA_ERRORS:
        return
    if scene_key is None:
        return

    def _timer():
        target_scene = fbp_find_id_by_runtime_key(
            bpy.data.scenes, scene_key, scene_name
        )
        if not target_scene:
            return None
        try:
            fbp_rebuild_pending_tree_rows(target_scene)
        except Exception as exc:
            try:
                fbp_warn('Multiplane Setup tree rebuild failed', exc)
            except FBP_DATA_IO_ERRORS:
                pass
        return None

    _safe_tasks.schedule_once(
        f'ui.pending_tree_rebuild.{scene_key}',
        _timer,
        first_interval=0.10,
    )


def fbp_refresh_pending_tree_rows(context_or_scene):
    """Public helper for operators: rebuild setup UIList rows after data changes."""
    scene = getattr(context_or_scene, 'scene', context_or_scene)
    try:
        fbp_rebuild_pending_tree_rows(scene)
        return True
    except Exception as exc:
        try:
            fbp_warn('Multiplane Setup tree refresh failed', exc)
        except FBP_DATA_IO_ERRORS:
            pass
    return False


# SECTION 02B - Layers UIList tree helpers #
# ###ICON Panel Layer Stack UIList, Function Collection: setup.collection
# ###ICON Panel Layer Stack UIList, Function Collapse: setup.collapsed / setup.expanded
# ###ICON Panel Layer Stack UIList, Function Layer: layer.color_tag / thumbnail


def _fbp_id_key(datablock):
    """Return a stable local key without retaining RNA references globally."""
    if datablock is None:
        return (0, "")
    try:
        return (
            int(datablock.as_pointer()),
            str(getattr(datablock, "name_full", getattr(datablock, "name", "")) or ""),
        )
    except FBP_DATA_ERRORS:
        return (0, str(getattr(datablock, "name", "") or ""))


def _fbp_build_layer_tree_cache(context):
    """Build one O(layers + collections) snapshot for Layer Tree draw/rebuild.

    The old UI path repeatedly scanned every Scene layer once per Collection and
    rebuilt a signature from visibility, selection, colors and thumbnails even
    though those values are read live by ``draw_item``. Large projects therefore
    performed O(collections × layers) work on ordinary sidebar redraws.

    This local snapshot computes rig membership, depth and collection ordering
    once. It is deliberately not stored globally, so deleted Blender datablocks
    can never survive in a Python cache between depsgraph/Undo operations.
    """
    scene = getattr(context, "scene", None)
    if scene is None:
        return None

    alpha_sort = bool(getattr(scene, "fbp_sort_layers_alpha", False))
    depth_context = fbp_make_depth_context_cache(context)
    root = getattr(scene, "collection", None)
    root_key = _fbp_id_key(root)

    collections = {}
    children = {}
    pending = [root] if root is not None else []
    seen_collections = set()
    while pending:
        collection = pending.pop()
        key = _fbp_id_key(collection)
        if not key[0] or key in seen_collections:
            continue
        seen_collections.add(key)
        collections[key] = collection
        try:
            child_items = tuple(getattr(collection, "children", ()) or ())
        except FBP_DATA_ERRORS:
            child_items = ()
        children[key] = child_items
        pending.extend(child_items)

    rigs = []
    rig_by_key = {}
    layer_item_by_key = {}
    layer_index_by_key = {}
    rig_depth = {}
    direct_rigs = {key: [] for key in collections}
    seen_rigs = set()

    try:
        layer_items = tuple(getattr(scene, "fbp_layers", ()) or ())
    except FBP_DATA_ERRORS:
        layer_items = ()

    for index, layer_item in enumerate(layer_items):
        try:
            rig = getattr(layer_item, "obj", None)
            if not rig or not is_fbp_layer_object(rig):
                continue
            rig_name = str(getattr(rig, "name", "") or "")
            if not rig_name or scene.objects.get(rig_name) != rig:
                continue
        except FBP_DATA_ERRORS:
            continue

        rig_key = _fbp_id_key(rig)
        if not rig_key[0] or rig_key in seen_rigs:
            continue
        seen_rigs.add(rig_key)
        rigs.append(rig)
        rig_by_key[rig_key] = rig
        layer_item_by_key[rig_key] = layer_item
        layer_index_by_key[rig_key] = index
        rig_depth[rig_key] = fbp_layer_depth_value_from_cache(rig, depth_context)

        collection = get_primary_fbp_collection(rig)
        collection_key = _fbp_id_key(collection)
        if collection_key not in direct_rigs:
            collection_key = root_key
        direct_rigs.setdefault(collection_key, []).append(rig)

    def rig_sort_key(rig):
        rig_key = _fbp_id_key(rig)
        if alpha_sort:
            return natural_sort_key(str(getattr(rig, "name", "") or ""))
        # Python's stable sort preserves Scene.fbp_layers order for equal-depth
        # layers. Renaming therefore cannot silently change the physical stack.
        return rig_depth.get(rig_key, 0.0)

    for collection_rigs in direct_rigs.values():
        collection_rigs.sort(key=rig_sort_key, reverse=not alpha_sort)

    descendant_rig_keys = {}

    def descendant_keys(collection, active=None):
        collection_key = _fbp_id_key(collection)
        cached = descendant_rig_keys.get(collection_key)
        if cached is not None:
            return cached
        active = set(active or ())
        if collection_key in active:
            return frozenset()
        active.add(collection_key)
        keys = {_fbp_id_key(rig) for rig in direct_rigs.get(collection_key, ())}
        for child in children.get(collection_key, ()):
            keys.update(descendant_keys(child, active))
        result = frozenset(key for key in keys if key[0])
        descendant_rig_keys[collection_key] = result
        return result

    for collection in tuple(collections.values()):
        descendant_keys(collection)

    def collection_sort_key(collection):
        name_key = natural_sort_key(str(getattr(collection, "name", "") or ""))
        if alpha_sort:
            return name_key
        keys = descendant_rig_keys.get(_fbp_id_key(collection), ())
        average_depth = (
            sum(rig_depth.get(key, 0.0) for key in keys) / len(keys)
            if keys else 0.0
        )
        return (average_depth, name_key)

    visible_children = {}
    for collection_key, child_items in children.items():
        filtered = [
            child for child in child_items
            if descendant_rig_keys.get(_fbp_id_key(child), ())
        ]
        filtered.sort(key=collection_sort_key, reverse=not alpha_sort)
        visible_children[collection_key] = tuple(filtered)

    return {
        "scene": scene,
        "alpha_sort": alpha_sort,
        "root": root,
        "root_key": root_key,
        "collections": collections,
        "rigs": tuple(rigs),
        "rig_by_key": rig_by_key,
        "layer_item_by_key": layer_item_by_key,
        "rig_depth": rig_depth,
        "layer_index_by_key": layer_index_by_key,
        "direct_rigs": {key: tuple(value) for key, value in direct_rigs.items()},
        "descendant_rig_keys": descendant_rig_keys,
        "children": visible_children,
        "top_collections": visible_children.get(root_key, ()),
    }


def fbp_layer_tree_signature(context, tree_cache=None):
    """Return only the structural identity of the visible Layer Tree rows.

    Visibility, selection, color, thumbnail and frame-count values are read live
    by the UIList and no longer trigger a transient collection rebuild.
    """
    cache = tree_cache or _fbp_build_layer_tree_cache(context)
    if not cache:
        return ""

    bits = ["alpha=1" if cache["alpha_sort"] else "alpha=0"]
    direct_rigs = cache["direct_rigs"]
    child_map = cache["children"]

    def add_rig(rig, collection, depth):
        bits.append(
            "L:{depth}:{collection}:{rig}".format(
                depth=int(depth),
                collection=str(getattr(collection, "name", "") or ""),
                rig=str(getattr(rig, "name", "") or ""),
            )
        )

    def add_collection(collection, depth=0, active=None):
        collection_key = _fbp_id_key(collection)
        active = set(active or ())
        if collection_key in active:
            return
        active.add(collection_key)
        collapsed = bool(getattr(collection, "fbp_collapsed", False))
        bits.append(
            "C:{depth}:{name}:{collapsed}".format(
                depth=int(depth),
                name=str(getattr(collection, "name", "") or ""),
                collapsed=int(collapsed),
            )
        )
        if collapsed:
            return
        for child in child_map.get(collection_key, ()):
            add_collection(child, depth + 1, active)
        for rig in reversed(direct_rigs.get(collection_key, ())):
            add_rig(rig, collection, depth + 1)

    try:
        for collection in cache["top_collections"]:
            add_collection(collection, 0)
        root = cache["root"]
        for rig in reversed(direct_rigs.get(cache["root_key"], ())):
            add_rig(rig, root, 0)
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Layer tree signature failed", exc)
    return "|".join(bits)


def fbp_rebuild_layer_tree_rows(context):
    """Rebuild the transient Layer Tree rows from one cached project snapshot."""
    scene = getattr(context, "scene", None)
    if scene is None:
        return False
    rows = getattr(scene, "fbp_layer_tree_rows", None)
    if rows is None:
        return False

    try:
        previous_active = int(getattr(scene, "fbp_layer_tree_rows_idx", 0))
    except FBP_DATA_ERRORS:
        previous_active = 0

    previous_identity = None
    try:
        if 0 <= previous_active < len(rows):
            active_row = rows[previous_active]
            previous_identity = (
                str(getattr(active_row, "row_type", "") or ""),
                str(getattr(active_row, "collection_name", "") or ""),
                str(getattr(active_row, "rig_name", "") or ""),
                int(getattr(active_row, "layer_index", -1) or -1),
            )
    except FBP_DATA_ERRORS:
        previous_identity = None

    cache = _fbp_build_layer_tree_cache(context)
    if not cache:
        return False

    rows.clear()
    direct_rigs = cache["direct_rigs"]
    child_map = cache["children"]
    layer_indices = cache["layer_index_by_key"]

    def add_layer(rig, collection, depth):
        if rig is None:
            return
        row = rows.add()
        row.row_type = "LAYER"
        row.name = str(getattr(rig, "name", "") or "Unnamed Layer")
        row.rig_name = str(getattr(rig, "name", "") or "")
        row.collection_name = str(getattr(collection, "name", "") or "")
        row.layer_index = int(layer_indices.get(_fbp_id_key(rig), -1))
        row.depth = max(0, int(depth))
        row.layer_count = 0
        row.child_count = 0

    def add_collection(collection, depth=0, active=None):
        if collection is None:
            return
        collection_key = _fbp_id_key(collection)
        active = set(active or ())
        if collection_key in active:
            return
        active.add(collection_key)

        child_items = child_map.get(collection_key, ())
        collection_rigs = direct_rigs.get(collection_key, ())
        row = rows.add()
        row.row_type = "GROUP"
        row.name = str(getattr(collection, "name", "") or "Collection")
        row.collection_name = str(getattr(collection, "name", "") or "")
        row.rig_name = ""
        row.layer_index = -1
        row.depth = max(0, int(depth))
        row.layer_count = len(collection_rigs)
        row.child_count = len(child_items)

        if bool(getattr(collection, "fbp_collapsed", False)):
            return
        for child in child_items:
            add_collection(child, depth + 1, active)
        for rig in reversed(collection_rigs):
            add_layer(rig, collection, depth + 1)

    try:
        for collection in cache["top_collections"]:
            add_collection(collection, 0)
        root = cache["root"]
        for rig in reversed(direct_rigs.get(cache["root_key"], ())):
            add_layer(rig, root, 0)
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Layer tree rebuild failed", exc)

    restored_index = None
    if previous_identity is not None:
        try:
            for index, item in enumerate(rows):
                identity = (
                    str(getattr(item, "row_type", "") or ""),
                    str(getattr(item, "collection_name", "") or ""),
                    str(getattr(item, "rig_name", "") or ""),
                    int(getattr(item, "layer_index", -1) or -1),
                )
                if identity == previous_identity:
                    restored_index = index
                    break
                # A renamed layer keeps its Scene.fbp_layers index, while a
                # reordered layer keeps its object name. Accept either stable
                # half of the identity so the active row does not jump.
                if (
                    previous_identity[0] == "LAYER"
                    and identity[0] == "LAYER"
                    and identity[1] == previous_identity[1]
                    and (
                        (identity[2] and identity[2] == previous_identity[2])
                        or (
                            identity[3] >= 0
                            and identity[3] == previous_identity[3]
                        )
                    )
                ):
                    restored_index = index
                    break
        except FBP_DATA_ERRORS:
            restored_index = None

    try:
        if len(rows):
            scene.fbp_layer_tree_rows_idx = (
                restored_index
                if restored_index is not None
                else min(max(0, previous_active), len(rows) - 1)
            )
        else:
            scene.fbp_layer_tree_rows_idx = 0
        scene.fbp_layer_tree_signature = fbp_layer_tree_signature(
            context, tree_cache=cache
        )
    except FBP_DATA_ERRORS:
        pass
    return True


def fbp_schedule_layer_tree_rebuild(context, *, tree_cache=None):
    """Schedule a safe row rebuild only when the structural signature changed."""
    scene = getattr(context, "scene", None)
    if scene is None:
        return
    rows = getattr(scene, "fbp_layer_tree_rows", None)
    if rows is None:
        return

    cache = tree_cache or _fbp_build_layer_tree_cache(context)
    current_signature = fbp_layer_tree_signature(context, tree_cache=cache)
    try:
        stored_signature = str(getattr(scene, "fbp_layer_tree_signature", "") or "")
        needs_rebuild = len(rows) == 0 or stored_signature != current_signature
    except FBP_DATA_ERRORS:
        needs_rebuild = True
    if not needs_rebuild:
        return

    scene_key = fbp_obj_runtime_key(scene)
    if scene_key is None:
        return

    def _timer():
        current_context = bpy.context
        current_scene = getattr(current_context, "scene", None)
        try:
            if current_scene is None or fbp_obj_runtime_key(current_scene) != scene_key:
                return None
            fbp_rebuild_layer_tree_rows(current_context)
        except Exception as exc:
            fbp_warn("Layer tree scheduled rebuild failed", exc)
        return None

    _safe_tasks.schedule_once(
        f"ui.layer_tree_rebuild.{scene_key}",
        _timer,
        first_interval=0.10,
    )


def fbp_refresh_layer_tree_rows(context_or_scene):
    """Public helper for operators/handlers after layer data changes."""
    context = context_or_scene if hasattr(context_or_scene, 'scene') else bpy.context
    try:
        return bool(fbp_rebuild_layer_tree_rows(context))
    except Exception as exc:
        try:
            fbp_warn('Layer tree refresh failed', exc)
        except FBP_DATA_IO_ERRORS:
            pass
    return False


def draw_layer_tree_uilist(layout, context, *, min_rows=4):
    """Draw the Layers panel using one shared O(layers + collections) snapshot."""
    sc = context.scene
    tree_cache = _fbp_build_layer_tree_cache(context)
    fbp_prime_collection_ui_state_cache(context, tree_cache)
    roots = tuple(tree_cache.get("top_collections", ())) if tree_cache else ()
    direct_scene_rigs = (
        tuple(tree_cache.get("direct_rigs", {}).get(tree_cache.get("root_key"), ()))
        if tree_cache else ()
    )
    if not roots and not direct_scene_rigs:
        # During a Scene switch the transient Scene.fbp_layers cache may still be
        # empty. A bounded Scene object check prevents a false permanent empty
        # state while the regular sync timer catches up.
        try:
            has_fbp_objects = any(is_fbp_layer_object(obj) for obj in sc.objects)
        except FBP_DATA_ERRORS:
            has_fbp_objects = False
        if has_fbp_objects or len(getattr(sc, "fbp_layers", ()) or ()):
            fbp_schedule_layer_tree_rebuild(context, tree_cache=tree_cache)
            layout.label(text="Refreshing layer tree...", icon=ui_icon("generic.info"))
            return
        layout.label(text="No Frame by Plane layers", icon=ui_icon("generic.info"))
        return

    fbp_schedule_layer_tree_rebuild(context, tree_cache=tree_cache)

    row_count = len(getattr(sc, "fbp_layer_tree_rows", ()) or ())
    if row_count == 0:
        layout.label(text="Refreshing layer tree...", icon=ui_icon("generic.info"))
    # Keep the list at least as tall as the adjacent toolbar.  A shorter
    # UIList left an empty grey strip below it while the side buttons continued
    # farther down, especially in compact projects with only a few layers.
    minimum = max(1, int(min_rows or 1))
    visible_rows = max(minimum, min(18, max(row_count, 1)))
    layout.template_list(
        "FBP_UL_LayerTreeList",
        "",
        sc,
        "fbp_layer_tree_rows",
        sc,
        "fbp_layer_tree_rows_idx",
        rows=visible_rows,
    )

def draw_pending_setup_grouped(layout, context):
    """Draw the responsive Multiplane Setup tree with a standard side toolbar.

    The caller already owns the outer box. The UIList is the flexible element
    on the left, while a single icon-wide column on the right mirrors Blender's
    other list controls. Per-row actions remain inside the UIList itself.
    """
    sc = context.scene

    items = getattr(sc, 'fbp_pending_planes', [])
    if not items:
        layout.label(text='No layers in setup')
        tools = layout.row(align=True)
        tools.operator('fbp.add_pending_plane', icon=ui_icon('generic.add'), text='Add Layer')
        tools.operator('fbp.add_pending_collection', icon=ui_icon('setup.collection_new'), text='New Collection')
        return

    # IMPORTANT: never rebuild Scene collections inside draw().
    fbp_schedule_pending_tree_rebuild(sc)


    visible_row_count = len(getattr(sc, 'fbp_pending_tree_rows', []))
    if visible_row_count == 0:
        layout.label(text='Refreshing setup tree...')
    rows = max(9, min(14, max(visible_row_count, 1)))

    list_row = layout.row(align=False)
    list_row.template_list(
        'FBP_UL_PendingTreeList',
        '',
        sc,
        'fbp_pending_tree_rows',
        sc,
        'fbp_pending_tree_rows_idx',
        rows=rows,
    )

    side = list_row.column(align=True)
    side.operator('fbp.add_pending_plane', text='', icon=ui_icon('generic.add'))
    side.operator('fbp.add_pending_collection', text='', icon=ui_icon('setup.collection_new'))
    if any(bool(getattr(item, 'source_from_layered', False)) for item in items):
        side.separator()
        side.operator('fbp.layered_import_report', text='', icon=fbp_icon('INFO'))

    active_row = None
    try:
        tree_index = int(getattr(sc, 'fbp_pending_tree_rows_idx', -1))
        tree_rows = getattr(sc, 'fbp_pending_tree_rows', ())
        if 0 <= tree_index < len(tree_rows):
            active_row = tree_rows[tree_index]
    except FBP_DATA_IO_ERRORS:
        active_row = None

    active_is_layer = bool(active_row and getattr(active_row, 'row_type', 'LAYER') == 'LAYER')
    active_pending_index = int(getattr(active_row, 'pending_index', -1)) if active_is_layer else -1

    side.separator()
    toggle_structure = side.row(align=True)
    toggle_structure.enabled = bool(
        active_row is not None
        and getattr(active_row, 'can_toggle_structure', False)
    )
    toggle_structure.operator(
        'fbp.toggle_pending_sequence_collection',
        text='',
        icon=ui_icon('sequence.split'),
    )

    checked_by_collection = {}
    reverse_available = False
    for pending_item in items:
        if not bool(getattr(pending_item, 'is_selected', False)):
            continue
        collection_name = str(getattr(pending_item, 'collection_name', '') or '')
        checked_by_collection[collection_name] = checked_by_collection.get(collection_name, 0) + 1
        if checked_by_collection[collection_name] >= 2:
            reverse_available = True
            break
    reverse_selected = side.row(align=True)
    reverse_selected.enabled = reverse_available
    reverse_selected.operator(
        'fbp.reverse_pending_selected_order',
        text='',
        icon=ui_icon('sequence.reverse'),
    )

    side.separator()
    move_up = side.row(align=True)
    move_up.enabled = bool(active_is_layer and getattr(active_row, 'can_move_up', False))
    op = move_up.operator('fbp.move_pending_plane', text='', icon=ui_icon('generic.up'))
    op.direction = 'UP'
    op.index = active_pending_index

    move_down = side.row(align=True)
    move_down.enabled = bool(active_is_layer and getattr(active_row, 'can_move_down', False))
    op = move_down.operator('fbp.move_pending_plane', text='', icon=ui_icon('generic.down'))
    op.direction = 'DOWN'
    op.index = active_pending_index

    side.separator()
    remove = side.row(align=True)
    remove.enabled = active_row is not None
    remove.operator('fbp.remove_pending_tree_selection', text='', icon=ui_icon('generic.delete'))


def _draw_import_alpha_crop_options(layout, scene):
    """Draw import-time alpha crop controls without changing current media."""
    row = layout.row(align=False)
    row.prop(scene, "fbp_import_crop_alpha", text="Crop Transparent Borders", icon='FULLSCREEN_EXIT')
    padding = row.row(align=False)
    padding.enabled = bool(getattr(scene, "fbp_import_crop_alpha", False))
    padding.prop(scene, "fbp_import_crop_alpha_padding", text="Padding")


# SECTION 02 - Create UI: Single / Multiplane / Color #
# ###ICON Panel Create, Function Color Plane: create.color_plane
# ###ICON Panel Create, Function Single Plane: create.single_plane
# ###ICON Panel Create, Function Multiplane: create.multiplane
# ###ICON Panel Create, Function Emission: create.emission
# ###ICON Panel Create, Function Camera/Fit: create.camera / create.fit_camera

def draw_creation_ui(layout, context):
    """Draw explicit creation backends from one compact selector.

    The selector mirrors the six primary Shift+A entries. Clipboard and Hex
    utilities intentionally remain menu-only because they are quick actions,
    not persistent creation modes.
    """
    sc = context.scene
    mode = str(getattr(sc, 'fbp_creation_mode', 'SINGLE') or 'SINGLE')
    mode_icon = {
        'SINGLE': ui_icon('menu.image_plane'),
        'MULTI': ui_icon('menu.multiplane'),
        'CUTOUT': ui_icon('create.cutout_plane'),
        'COLOR': ui_icon('menu.color_plane'),
        'GRADIENT': ui_icon('menu.gradient_plane'),
        'HOLDOUT': ui_icon('menu.holdout_plane'),
    }.get(mode, ui_icon('create.header'))

    selector = layout.row(align=False)
    selector.scale_y = 1.15
    selector.prop(sc, "fbp_creation_mode", text="Create", icon=mode_icon)
    layout.separator()

    if mode == 'SINGLE':
        box = layout.box()
        box.label(text="Image Plane", icon=fbp_icon("FILE_IMAGE"))
        row = box.row(align=False)
        row.prop(sc, "fbp_pre_duration", text='Frame Hold')
        row.prop(sc, "fbp_pre_shadeless", text="Emission Texture", icon=fbp_icon("LIGHT_SUN"), toggle=True)
        row = box.row(align=True)
        row.prop(sc, "fbp_pre_loop_mode", expand=True)
        box.prop(sc, "fbp_pre_interpolation", text="Filtering", expand=False)
        box.prop(sc, "fbp_pre_orientation", expand=False)
        _draw_import_alpha_crop_options(box, sc)
        layout.separator()
        row = layout.row(align=False)
        row.scale_y = 1.2
        row.operator("fbp.import_sequence", text="Generate Image Plane", icon=fbp_icon("FILE_IMAGE"))
        return

    if mode == 'CUTOUT':
        box = layout.box()
        box.label(text="Cutout Plane", icon=ui_icon("create.cutout_plane"))
        box.prop(sc, "fbp_pre_interpolation", text="Filtering", expand=False)
        box.prop(sc, "fbp_pre_orientation", expand=False)
        layout.separator()
        row = layout.row(align=False)
        row.scale_y = 1.2
        row.operator("fbp.import_drawing_plane", text="Generate Cutout Plane", icon=ui_icon("create.cutout_plane"))
        return

    if mode in {'COLOR', 'GRADIENT', 'HOLDOUT'}:
        box = layout.box()
        if mode == 'COLOR':
            box.label(text="Color Plane", icon=fbp_icon("MATERIAL"))
            row = box.row(align=False)
            row.prop(sc, "fbp_color_plane_emission", text="Emission", icon=fbp_icon("LIGHT_SUN"), toggle=True)
            fbp_draw_color_plane_color_row(box, sc)
            button_text = "Generate Color Plane"
            button_icon = fbp_icon("IMAGE")
            plane_type = 'CUSTOM'
        elif mode == 'GRADIENT':
            box.label(text="Gradient Plane", icon=fbp_icon("NODE_TEXTURE"))
            row = box.row(align=False)
            row.prop(sc, "fbp_color_plane_emission", text="Emission", icon=fbp_icon("LIGHT_SUN"), toggle=True)
            fbp_draw_gradient_choice_rows(box, sc)
            draw_scene_fbp_color_ramp(box, sc)
            gbox = box.box()
            is_open = bool(getattr(sc, 'fbp_show_gradient_transform', True))
            row = gbox.row(align=True)
            row.prop(
                sc,
                'fbp_show_gradient_transform',
                text='Position',
                icon=(fbp_icon('DOWNARROW_HLT') if is_open else fbp_icon('RIGHTARROW')),
                emboss=False,
            )
            if is_open:
                row = gbox.row(align=False)
                row.prop(sc, "fbp_gradient_offset_x", text="X")
                row.prop(sc, "fbp_gradient_offset_y", text="Y")
                row = gbox.row(align=False)
                row.prop(sc, "fbp_gradient_scale_x", text="Scale X")
                row.prop(sc, "fbp_gradient_scale_y", text="Scale Y")
                gbox.prop(sc, "fbp_gradient_rotation", text="Rotation")
            button_text = "Generate Gradient Plane"
            button_icon = fbp_icon("NODE_TEXTURE")
            plane_type = 'GRADIENT'
        else:
            box.label(text="Holdout Plane", icon=fbp_icon("GHOST_DISABLED"))
            button_text = "Generate Holdout Plane"
            button_icon = fbp_icon("GHOST_DISABLED")
            plane_type = 'HOLDOUT'

        box.prop(sc, "fbp_pre_orientation", expand=False)
        layout.separator()
        row = layout.row(align=False)
        row.scale_y = 1.2
        op = row.operator("fbp.create_color_plane", text=button_text, icon=button_icon)
        op.plane_type = plane_type
        return

    # MULTIPLANE
    box = layout.box()
    box.label(text="Multiplane", icon=fbp_icon("RENDERLAYERS"))
    row = box.row(align=False)
    row.prop(sc, "fbp_pre_duration", text="Frame Hold")
    row.prop(sc, "fbp_pre_shadeless", text="Emission Texture", icon=fbp_icon("LIGHT_SUN"), toggle=True)
    box.prop(sc, "fbp_pre_loop_mode", expand=False)
    box.prop(sc, "fbp_pre_interpolation", expand=False)
    box.prop(sc, "fbp_pre_orientation", expand=False)
    _draw_import_alpha_crop_options(box, sc)

    box = layout.box()
    box.label(text="Camera Setup", icon=fbp_icon("RESTRICT_VIEW_ON"))
    row = box.row(align=False)
    cam_icon = fbp_icon("VIEW_CAMERA") if sc.fbp_gen_camera else 'CAMERA_DATA'
    row.operator("fbp.popup_generate_camera", text="Generate Camera", icon=cam_icon, depress=bool(sc.fbp_gen_camera))
    row.prop(sc, "fbp_cam_pivot", text='3D Cursor on Camera', icon=fbp_icon("PIVOT_CURSOR"), toggle=True)
    row = box.row(align=False)
    row.prop(sc, "fbp_layer_offset", text='Plane Distance')
    row.prop(sc, "fbp_auto_scale", text='Fit to Camera', icon=fbp_icon("FULLSCREEN_ENTER"), toggle=True)

    layout.separator()

    row = layout.row(align=False)
    row.prop(
        sc,
        "fbp_show_project_tools",
        text="Import Project",
        icon=(fbp_icon("DOWNARROW_HLT") if sc.fbp_show_project_tools else fbp_icon("RIGHTARROW")),
    )
    if sc.fbp_show_project_tools:
        box = layout.box()
        box.prop(sc, "fbp_project_path", text="")
        row = box.row(align=True)
        row.operator("fbp.scan_project_to_setup", icon=fbp_icon("IMPORT"), text="Import to Setup")
        row.operator("fbp.auto_scene_builder", icon=fbp_icon("OUTLINER_COLLECTION"), text="Build Direct")

    box = layout.box()
    box.label(text="Multiplane Setup", icon=fbp_icon("RENDERLAYERS"))
    draw_pending_setup_grouped(box, context)

    row = layout.row(align=False)
    row.scale_y = 1.2
    split = row.split(factor=0.67, align=False)
    left = split.row(align=True)
    right = split.row(align=True)
    pending = bool(getattr(sc, "fbp_pending_planes", None) and len(sc.fbp_pending_planes) > 0)
    left.enabled = pending
    right.enabled = pending
    left.operator("fbp.generate_multiplane", text="Generate Multiplane", icon=fbp_icon("RENDERLAYERS"))
    right.operator("fbp.clear_pending_planes", icon=fbp_icon("TRASH"), text="Clear Setup")
