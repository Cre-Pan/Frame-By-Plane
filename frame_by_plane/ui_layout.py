"""Reusable UI layout helpers for Frame By Plane panels and lists."""

import os
import time
from collections import OrderedDict

import bpy

from .constants import (
    fbp_icon,
    fbp_normalize_artist_color_tag,
    fbp_shared_artist_color_tag,
)
from .path_utils import (
    is_supported_media_file,
    is_supported_video_file,
    is_technical_map_file,
    natural_sort_key,
)
from .runtime import (
    fbp_warn, FBP_DATA_ERRORS, FBP_DATA_IO_ERRORS,
    fbp_obj_runtime_key, fbp_find_id_by_runtime_key, fbp_registration_busy,
)
from .fbp_index import iter_scene_gp_canvases
from .layers import (
    fbp_layer_depth_value_from_cache,
    fbp_make_depth_context_cache,
    get_primary_fbp_collection,
    is_fbp_layer_object,
    fbp_set_ui_units_x,
    fbp_collection_effective_color_tag,
    get_collection_holdout,
    get_collection_locked,
    get_collection_plane_locked,
    get_collection_selected,
    get_collection_solo,
    get_collection_visible,
)
from .core import (
    draw_scene_fbp_color_ramp,
    fbp_draw_color_plane_color_row,
    fbp_draw_gradient_choice_rows,
    pending_collection_is_open,
)
from .ui_icons import ui_icon, ui_icon_kwargs, ui_label_icon_kwargs
from .interface_preferences import fbp_draw_uilist_header
from .ui_style import (
    adaptive_row,
    configure_layout,
    empty_state,
    hint_row,
    is_compact,
    section_gap,
    section_header,
    list_rows,
)
from . import safe_tasks as _safe_tasks
from .ui_list_state import (
    ensure_unique_item_identities,
    transient_get,
    transient_pop,
    ui_list_mutation_delay,
)
from .layer_tree_snapshot import (
    get_or_build_snapshot,
    invalidate_snapshot,
    mode_counts as fbp_layer_tree_mode_counts,
    set_mode_counts as fbp_set_layer_tree_mode_counts,
)


_FBP_LAYER_TREE_LAST_CHECK = {}
_FBP_LAYER_TREE_CHECK_INTERVAL = 0.75


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
    return fbp_shared_artist_color_tag(
        getattr(item, 'fbp_color_tag', 'NONE')
        for _index, item in node.get('items', [])
    )


def fbp_apply_pending_collection_color(scene, collection_path, color_tag):
    """Apply an editable preview collection color to its direct pending layers."""
    path = (collection_path or '').strip()
    tag = fbp_normalize_artist_color_tag(color_tag)
    layer_tag = tag
    changed = False
    for item in getattr(scene, 'fbp_pending_planes', []):
        if (getattr(item, 'collection_name', '') or '').strip() != path:
            continue
        if not bool(getattr(item, 'follow_collection_color', True)):
            continue
        if getattr(item, 'fbp_color_tag', 'NONE') != layer_tag:
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
    ensure_unique_item_identities(
        getattr(scene, 'fbp_pending_planes', ()), "stable_id"
    )

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
                        str(getattr(active_item, 'stable_id', '') or ''),
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
        row.gp_count = 0
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
        requested_uid = str(
            transient_get(scene, "_fbp_pending_tree_focus_uid", "") or ""
        )
        if requested_uid:
            pending = getattr(scene, 'fbp_pending_planes', ())
            for row_index, row in enumerate(rows):
                if getattr(row, 'row_type', 'LAYER') != 'LAYER':
                    continue
                pending_index = int(getattr(row, 'pending_index', -1))
                if not (0 <= pending_index < len(pending)):
                    continue
                if str(getattr(pending[pending_index], 'stable_id', '') or '') == requested_uid:
                    restored_index = row_index
                    break
            transient_pop(scene, "_fbp_pending_tree_focus_uid")
        if restored_index < 0 and previous_key:
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
                        str(getattr(pending_item, 'stable_id', '') or ''),
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


def fbp_schedule_pending_tree_rebuild(scene, *, force=False):
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
        if not force and len(rows) > 0:
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
    generation = _fbp_ui_rebuild_generation(_FBP_PENDING_TREE_REBUILD_GENERATIONS, scene_key)

    def _timer():
        if _fbp_ui_rebuild_generation(_FBP_PENDING_TREE_REBUILD_GENERATIONS, scene_key) != generation:
            return None
        retry_delay = ui_list_mutation_delay()
        if retry_delay > 0.0:
            return retry_delay
        try:
            target_scene = fbp_find_id_by_runtime_key(
                getattr(bpy.data, "scenes", ()), scene_key, scene_name
            )
            if target_scene is None:
                return None
            try:
                fbp_rebuild_pending_tree_rows(target_scene)
            except Exception as exc:
                try:
                    fbp_warn('Multiplane Setup tree rebuild failed', exc)
                except FBP_DATA_IO_ERRORS:
                    pass
            return None
        finally:
            _fbp_finish_ui_rebuild_generation(
                _FBP_PENDING_TREE_REBUILD_GENERATIONS, scene_key, generation
            )

    accepted = _safe_tasks.schedule_once(
        f'ui.pending_tree_rebuild.{scene_key}',
        _timer,
        first_interval=0.10,
    )
    if not accepted:
        _fbp_finish_ui_rebuild_generation(
            _FBP_PENDING_TREE_REBUILD_GENERATIONS, scene_key, generation
        )
    return bool(accepted)


def fbp_refresh_pending_tree_rows(context_or_scene):
    """Refresh setup rows without mutating their RNA collection during redraw."""
    scene = getattr(context_or_scene, 'scene', context_or_scene)
    _fbp_cancel_pending_tree_rebuild(scene)
    retry_delay = ui_list_mutation_delay()
    if retry_delay > 0.0:
        fbp_schedule_pending_tree_rebuild(scene, force=True)
        return True
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


# Primitive-only generations retire deferred rebuilds created before a newer
# UIList fold/unfold mutation. No Blender RNA references are stored here.
_FBP_UI_REBUILD_GENERATION_LIMIT = 128
_FBP_LAYER_TREE_REBUILD_GENERATIONS = OrderedDict()
_FBP_PENDING_TREE_REBUILD_GENERATIONS = OrderedDict()


def _fbp_ui_rebuild_generation(table, scene_key):
    try:
        return int(table.get(scene_key, 0) or 0)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return 0


def _fbp_set_ui_rebuild_generation(table, scene_key, generation):
    """Store one primitive generation in a bounded LRU table."""
    table[scene_key] = max(0, int(generation))
    try:
        table.move_to_end(scene_key)
    except (AttributeError, KeyError):
        pass
    while len(table) > _FBP_UI_REBUILD_GENERATION_LIMIT:
        try:
            table.popitem(last=False)
        except (AttributeError, KeyError, TypeError):
            break
    return int(table.get(scene_key, 0) or 0)


def _fbp_finish_ui_rebuild_generation(table, scene_key, generation):
    """Drop completed state only when no newer rebuild invalidated it."""
    if _fbp_ui_rebuild_generation(table, scene_key) != int(generation):
        return False
    table.pop(scene_key, None)
    return True


def _fbp_cancel_layer_tree_rebuild(scene):
    scene_key = fbp_obj_runtime_key(scene) if scene is not None else None
    if scene_key is None:
        return 0
    generation = _fbp_set_ui_rebuild_generation(
        _FBP_LAYER_TREE_REBUILD_GENERATIONS,
        scene_key,
        _fbp_ui_rebuild_generation(_FBP_LAYER_TREE_REBUILD_GENERATIONS, scene_key) + 1,
    )
    _safe_tasks.cancel_scheduled_prefixes(f"ui.layer_tree_rebuild.{scene_key}")
    invalidate_snapshot(scene_key)
    return generation


def _fbp_cancel_pending_tree_rebuild(scene):
    scene_key = fbp_obj_runtime_key(scene) if scene is not None else None
    if scene_key is None:
        return 0
    generation = _fbp_set_ui_rebuild_generation(
        _FBP_PENDING_TREE_REBUILD_GENERATIONS,
        scene_key,
        _fbp_ui_rebuild_generation(_FBP_PENDING_TREE_REBUILD_GENERATIONS, scene_key) + 1,
    )
    _safe_tasks.cancel_scheduled_prefixes(f"ui.pending_tree_rebuild.{scene_key}")
    return generation


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


_FBP_INTERNAL_LAYER_TREE_COLLECTIONS = frozenset({
    "FBP Grease Pencil",
    "FBP Grease Pencil Render",
})


def _fbp_collection_is_managed_for_layer_tree(collection):
    """Return whether an empty artist collection belongs in the Layer List.

    Infrastructure collections used by the Grease Pencil bridge are deliberately
    transparent. They may exist in Blender's Outliner, but they are not artist
    groups and must never appear as empty or undeletable rows in either Layer List.
    """
    if collection is None:
        return False
    try:
        if str(getattr(collection, "name", "") or "") in _FBP_INTERNAL_LAYER_TREE_COLLECTIONS:
            return False
        return bool(
            getattr(collection, "is_fbp_collection", False)
            or getattr(collection, "fbp_layer_group", False)
        )
    except FBP_DATA_ERRORS:
        return False



def _fbp_collection_list_domain(collection, plane_count=0, gp_count=0):
    """Resolve one dedicated list owner for a Blender Collection.

    A collection must never appear in both the Plane and Grease Pencil lists.
    Collections store an explicit domain; AUTO collections are
    inferred deterministically, with Plane ownership winning only for genuinely
    mixed current data.
    """
    try:
        explicit = str(getattr(collection, "fbp_layer_list_domain", "AUTO") or "AUTO").upper()
    except FBP_DATA_ERRORS:
        explicit = "AUTO"
    if explicit in {"PLANES", "GP"}:
        return explicit
    try:
        plane_count = int(plane_count or 0)
        gp_count = int(gp_count or 0)
    except (TypeError, ValueError, OverflowError):
        plane_count = gp_count = 0
    if gp_count > 0 and plane_count <= 0:
        return "GP"
    return "PLANES"
def _fbp_build_layer_tree_cache_uncached(context):
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

    # Blender allows one Collection datablock to be linked below multiple
    # parents. The Layer List is a single-parent tree, so choose one canonical
    # scene path and suppress duplicate rows. This also prevents recursive UI
    # duplication after manual Outliner edits or interrupted Undo operations.
    canonical_parent_by_key = {root_key: None}
    if root is not None:
        # Breadth-first traversal gives the shallowest scene path priority when
        # a Collection is linked below multiple parents. A direct root link must
        # not be hidden by a deeper duplicate encountered through an earlier
        # sibling branch.
        canonical_queue = [root]
        canonical_seen = set()
        canonical_index = 0
        while canonical_index < len(canonical_queue):
            parent = canonical_queue[canonical_index]
            canonical_index += 1
            parent_key = _fbp_id_key(parent)
            if parent_key in canonical_seen:
                continue
            canonical_seen.add(parent_key)
            for child in children.get(parent_key, ()):
                child_key = _fbp_id_key(child)
                if not child_key[0] or child_key == root_key:
                    continue
                if child_key not in canonical_parent_by_key:
                    canonical_parent_by_key[child_key] = parent_key
                    canonical_queue.append(child)

    rigs = []
    rig_by_key = {}
    layer_item_by_key = {}
    layer_index_by_key = {}
    rig_depth = {}
    gp_depth = {}
    stack_order = {}
    direct_rigs = {key: [] for key in collections}
    direct_gp_canvases = {key: [] for key in collections}
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
        stack_order[rig_key] = float(index)
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
        # Closest-to-camera layers must appear first in the Layer List;
        # Python's stable sort preserves Scene.fbp_layers order for equal-depth
        # layers, so renaming cannot silently change the physical stack.
        return rig_depth.get(rig_key, 0.0)

    for collection_rigs in direct_rigs.values():
        collection_rigs.sort(key=rig_sort_key)

    # Build the Grease Pencil child map once. Avoid calling
    # gp_canvas_for_rig() per visible row because its recovery path may scan all
    # Objects when a saved pointer is stale.
    gp_canvas_by_rig_key = {}
    independent_gp_canvases = []
    try:
        from .grease_pencil_bridge import is_gp_drawing_canvas, gp_canvas_owner
        seen_gp = set()

        def add_linked_canvas(rig_key, canvas, *, primary=False):
            if not is_gp_drawing_canvas(canvas):
                return
            try:
                canvas_key = int(canvas.as_pointer())
            except FBP_DATA_ERRORS:
                canvas_key = id(canvas)
            if canvas_key in seen_gp:
                return
            seen_gp.add(canvas_key)
            bucket = gp_canvas_by_rig_key.setdefault(rig_key, [])
            if primary:
                bucket.insert(0, canvas)
            else:
                bucket.append(canvas)

        for rig_key, rig in rig_by_key.items():
            canvas = getattr(rig, "fbp_gp_canvas", None)
            if is_gp_drawing_canvas(canvas):
                add_linked_canvas(rig_key, canvas, primary=True)
        for obj in iter_scene_gp_canvases(scene, kind="DRAWING", fallback=True):
            if not is_gp_drawing_canvas(obj):
                continue
            owner = gp_canvas_owner(obj)
            owner_key = _fbp_id_key(owner)
            if owner_key in rig_by_key:
                add_linked_canvas(owner_key, obj)
            elif owner is None:
                independent_gp_canvases.append(obj)
        for rig_key, canvases in tuple(gp_canvas_by_rig_key.items()):
            primary = getattr(rig_by_key.get(rig_key), "fbp_gp_canvas", None)
            tail = [canvas for canvas in canvases if canvas is not primary]
            tail.sort(key=lambda item: natural_sort_key(str(getattr(item, "name", "") or "")))
            gp_canvas_by_rig_key[rig_key] = tuple(([primary] if primary in canvases else []) + tail)
        independent_gp_canvases.sort(
            key=lambda item: natural_sort_key(str(getattr(item, "name", "") or ""))
        )

        # Drawing Planes are now displayed as stack items at collection level,
        # so depth sorting/move buttons treat them like image planes.
        for rig_key, canvases in gp_canvas_by_rig_key.items():
            owner = rig_by_key.get(rig_key)
            owner_collection = get_primary_fbp_collection(owner)
            owner_collection_key = _fbp_id_key(owner_collection)
            for canvas in canvases:
                collection = get_primary_fbp_collection(canvas)
                if (
                    collection is None
                    or str(getattr(collection, "name", "") or "") == "FBP Grease Pencil"
                ):
                    collection = owner_collection
                collection_key = _fbp_id_key(collection)
                if collection_key not in direct_gp_canvases:
                    collection_key = owner_collection_key if owner_collection_key in direct_gp_canvases else root_key
                direct_gp_canvases.setdefault(collection_key, []).append(canvas)
                canvas_key = _fbp_id_key(canvas)
                gp_depth[canvas_key] = fbp_layer_depth_value_from_cache(canvas, depth_context)
                stack_order[canvas_key] = float(layer_index_by_key.get(rig_key, len(layer_items))) + 0.25 + (len(direct_gp_canvases.get(collection_key, ())) * 0.001)
        for independent_index, canvas in enumerate(independent_gp_canvases):
            collection = get_primary_fbp_collection(canvas)
            if str(getattr(collection, "name", "") or "") in {
                "FBP Grease Pencil",
                "FBP Grease Pencil Render",
            }:
                collection = root
            collection_key = _fbp_id_key(collection)
            if collection_key not in direct_gp_canvases:
                collection_key = root_key
            direct_gp_canvases.setdefault(collection_key, []).append(canvas)
            canvas_key = _fbp_id_key(canvas)
            gp_depth[canvas_key] = fbp_layer_depth_value_from_cache(canvas, depth_context)
            stack_order[canvas_key] = float(len(layer_items) + independent_index)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        gp_canvas_by_rig_key = {}
        independent_gp_canvases = []
        direct_gp_canvases = {key: [] for key in collections}
        gp_depth = {}
        stack_order = dict(stack_order)


    descendant_layer_keys = {}
    descendant_gp_keys = {}
    descendant_rig_keys = {}

    def _descendant_stack_keys(collection, direct_map, cache, active=None):
        collection_key = _fbp_id_key(collection)
        cached = cache.get(collection_key)
        if cached is not None:
            return cached
        active = set(active or ())
        if collection_key in active:
            return frozenset()
        active.add(collection_key)
        keys = {_fbp_id_key(obj) for obj in direct_map.get(collection_key, ())}
        for child in children.get(collection_key, ()):
            # Aggregate only the branch displayed by the Layer List.  A Blender
            # Collection linked below multiple parents must not leak its layers
            # into every parent row's counts, colors or bulk actions.
            if canonical_parent_by_key.get(_fbp_id_key(child)) != collection_key:
                continue
            keys.update(_descendant_stack_keys(child, direct_map, cache, active))
        result = frozenset(key for key in keys if key[0])
        cache[collection_key] = result
        return result

    for collection in tuple(collections.values()):
        layer_keys = _descendant_stack_keys(collection, direct_rigs, descendant_layer_keys)
        gp_keys = _descendant_stack_keys(collection, direct_gp_canvases, descendant_gp_keys)
        descendant_rig_keys[_fbp_id_key(collection)] = frozenset(tuple(layer_keys) + tuple(gp_keys))

    def collection_sort_key(collection):
        name_key = natural_sort_key(str(getattr(collection, "name", "") or ""))
        if alpha_sort:
            return name_key
        try:
            explicit_order = int(getattr(collection, "fbp_layer_order", -1))
        except FBP_DATA_ERRORS:
            explicit_order = -1
        if explicit_order >= 0 and bool(getattr(collection, "fbp_layer_order_mixed", False)):
            return (0, float(explicit_order), name_key)
        keys = descendant_rig_keys.get(_fbp_id_key(collection), ())
        if not keys:
            # Keep reusable empty Frame By Plane groups visible but place them
            # after populated siblings instead of treating their depth as zero.
            return (2, 0.0, name_key)
        average_depth = sum(
            rig_depth.get(key, gp_depth.get(key, 0.0)) for key in keys
        ) / len(keys)
        return (1, average_depth, name_key)

    direct_items = {}
    for collection_key in collections:
        items = [("LAYER", rig) for rig in direct_rigs.get(collection_key, ())]
        items.extend(("GP_CANVAS", canvas) for canvas in direct_gp_canvases.get(collection_key, ()))
        if alpha_sort:
            items.sort(key=lambda pair: natural_sort_key(str(getattr(pair[1], "name", "") or "")))
        else:
            items.sort(
                key=lambda pair: (
                    rig_depth.get(_fbp_id_key(pair[1]), gp_depth.get(_fbp_id_key(pair[1]), 0.0)),
                    stack_order.get(_fbp_id_key(pair[1]), 1.0e9),
                )
            )
        direct_items[collection_key] = tuple(items)

    managed_subtree_cache = {}
    empty_managed_subtree_cache = {}

    def subtree_contains_managed_collection(collection, active=None):
        collection_key = _fbp_id_key(collection)
        cached = managed_subtree_cache.get(collection_key)
        if cached is not None:
            return cached
        active = set(active or ())
        if collection_key in active:
            return False
        active.add(collection_key)
        result = _fbp_collection_is_managed_for_layer_tree(collection)
        if not result:
            for child in children.get(collection_key, ()):
                child_key = _fbp_id_key(child)
                if canonical_parent_by_key.get(child_key) != collection_key:
                    continue
                if subtree_contains_managed_collection(child, active):
                    result = True
                    break
        managed_subtree_cache[collection_key] = bool(result)
        return bool(result)

    def subtree_contains_empty_managed_collection(collection, active=None):
        """Return whether this canonical branch contains an empty managed group."""
        collection_key = _fbp_id_key(collection)
        cached = empty_managed_subtree_cache.get(collection_key)
        if cached is not None:
            return cached
        active = set(active or ())
        if collection_key in active:
            return False
        active.add(collection_key)
        result = bool(
            _fbp_collection_is_managed_for_layer_tree(collection)
            and not descendant_rig_keys.get(collection_key, ())
        )
        if not result:
            for child in children.get(collection_key, ()):
                child_key = _fbp_id_key(child)
                if canonical_parent_by_key.get(child_key) != collection_key:
                    continue
                if subtree_contains_empty_managed_collection(child, active):
                    result = True
                    break
        empty_managed_subtree_cache[collection_key] = bool(result)
        return bool(result)

    visible_children = {}
    for collection_key, child_items in children.items():
        filtered = []
        for child in child_items:
            child_key = _fbp_id_key(child)
            if canonical_parent_by_key.get(child_key) != collection_key:
                continue
            if (
                descendant_rig_keys.get(child_key, ())
                or subtree_contains_managed_collection(child)
            ):
                subtree_contains_empty_managed_collection(child)
                filtered.append(child)
        filtered.sort(key=collection_sort_key)
        visible_children[collection_key] = tuple(filtered)

    collection_domains = {}
    for collection_key, collection in collections.items():
        collection_domains[collection_key] = _fbp_collection_list_domain(
            collection,
            len(descendant_layer_keys.get(collection_key, ())),
            len(descendant_gp_keys.get(collection_key, ())),
        )

    def entry_stack_value(entry_type, datablock):
        entry_type = str(entry_type or "").upper()
        try:
            explicit = float(getattr(datablock, "fbp_layer_order", -1.0))
        except FBP_DATA_ERRORS:
            explicit = -1.0
        if (
            explicit >= 0.0
            and (
                entry_type != "COLLECTION"
                or bool(getattr(datablock, "fbp_layer_order_mixed", False))
            )
        ):
            return explicit
        datablock_key = _fbp_id_key(datablock)
        if entry_type == "COLLECTION":
            keys = descendant_rig_keys.get(datablock_key, ())
            if not keys:
                return 1.0e12
            return sum(
                rig_depth.get(key, gp_depth.get(key, 0.0)) for key in keys
            ) / max(1, len(keys))
        return rig_depth.get(datablock_key, gp_depth.get(datablock_key, 0.0))

    entries_by_parent = {}
    for parent_key in collections:
        entries = [
            ("COLLECTION", child)
            for child in visible_children.get(parent_key, ())
        ]
        entries.extend(direct_items.get(parent_key, ()))
        if alpha_sort:
            entries.sort(
                key=lambda entry: natural_sort_key(
                    str(getattr(entry[1], "name", "") or "")
                )
            )
        else:
            entries.sort(
                key=lambda entry: (
                    entry_stack_value(entry[0], entry[1]),
                    0 if str(entry[0]) == "COLLECTION" else 1,
                    natural_sort_key(str(getattr(entry[1], "name", "") or "")),
                )
            )
        entries_by_parent[parent_key] = list(entries)

    # Modal drag previews are drawn as shadow rows by the UIList itself.
    # This cache remains purely structural and is never reordered during MOUSEMOVE.

    entries_by_parent = {
        key: tuple(value) for key, value in entries_by_parent.items()
    }

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
        "gp_depth": gp_depth,
        "stack_order": stack_order,
        "layer_index_by_key": layer_index_by_key,
        "gp_canvas_by_rig_key": gp_canvas_by_rig_key,
        "independent_gp_canvases": tuple(independent_gp_canvases),
        "direct_gp_canvases": {key: tuple(value) for key, value in direct_gp_canvases.items()},
        "direct_items": direct_items,
        "direct_rigs": {key: tuple(value) for key, value in direct_rigs.items()},
        "descendant_rig_keys": descendant_rig_keys,
        "descendant_layer_keys": descendant_layer_keys,
        "descendant_gp_keys": descendant_gp_keys,
        "children": visible_children,
        "entries_by_parent": entries_by_parent,
        "collection_domains": collection_domains,
        "canonical_parent_by_key": canonical_parent_by_key,
        "empty_managed_path_keys": frozenset(
            key for key, value in empty_managed_subtree_cache.items() if value
        ),
        "top_collections": visible_children.get(root_key, ()),
    }


def _fbp_layer_tree_snapshot_fingerprint(context, scene):
    """Return a cheap redraw fingerprint; explicit invalidation handles edits."""
    try:
        root = getattr(scene, "collection", None)
        camera = getattr(scene, "camera", None)
        return (
            bool(getattr(scene, "fbp_sort_layers_alpha", False)),
            len(getattr(scene, "fbp_layers", ()) or ()),
            len(getattr(scene, "objects", ()) or ()),
            len(getattr(root, "children", ()) or ()) if root is not None else 0,
            int(getattr(scene, "frame_current", 0) or 0),
            fbp_obj_runtime_key(camera),
        )
    except FBP_DATA_ERRORS:
        return (bool(getattr(scene, "fbp_sort_layers_alpha", False)),)


def fbp_invalidate_layer_tree_snapshot(context_or_scene=None):
    """Discard cached Layer Tree RNA references after structural changes."""
    if context_or_scene is None:
        return invalidate_snapshot()
    scene = (
        getattr(context_or_scene, "scene", None)
        if hasattr(context_or_scene, "scene")
        else context_or_scene
    )
    scene_key = fbp_obj_runtime_key(scene) if scene is not None else None
    return invalidate_snapshot(scene_key) if scene_key is not None else invalidate_snapshot()


def _fbp_build_layer_tree_cache(context, *, force=False):
    """Return one short-lived snapshot shared by repeated UI redraws."""
    scene = getattr(context, "scene", None)
    if scene is None:
        return None
    scene_key = fbp_obj_runtime_key(scene)
    if scene_key is None:
        return _fbp_build_layer_tree_cache_uncached(context)
    fingerprint = _fbp_layer_tree_snapshot_fingerprint(context, scene)
    return get_or_build_snapshot(
        scene_key,
        fingerprint,
        lambda: _fbp_build_layer_tree_cache_uncached(context),
        force=bool(force),
    )


def fbp_layer_tree_row_visible_for_mode(row, mode):
    """Return whether one flattened row belongs in ALL, PLANES or GP lists."""
    row_type = str(getattr(row, "row_type", "") or "")
    mode = str(mode or "ALL").upper()
    if mode == "ALL":
        return True
    if row_type == "GROUP":
        domain = str(getattr(row, "list_domain", "PLANES") or "PLANES").upper()
        if domain != mode:
            return False
        if mode == "PLANES":
            count = int(getattr(row, "layer_count", 0) or 0)
        elif mode == "GP":
            count = int(getattr(row, "gp_count", 0) or 0)
        else:
            return False
        return count > 0 or bool(getattr(row, "empty_managed_path", False))
    if mode == "PLANES":
        return row_type == "LAYER"
    if mode == "GP":
        return row_type in {"GP_CANVAS", "GP_LAYER"}
    return False


def _fbp_layer_filter_active(scene):
    try:
        from .layer_filters import layer_filter_is_active

        return bool(layer_filter_is_active(scene))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError):
        return False


def fbp_layer_tree_signature(context, tree_cache=None):
    """Return only the structural identity of the visible Layer Tree rows.

    Visibility, selection, color, thumbnail and frame-count values are read live
    by the UIList and no longer trigger a transient collection rebuild.
    """
    cache = tree_cache or _fbp_build_layer_tree_cache(context)
    if not cache:
        return ""
    cached_signature = cache.get("_structural_signature")
    if isinstance(cached_signature, str):
        return cached_signature

    bits = ["alpha=1" if cache["alpha_sort"] else "alpha=0"]
    entries_by_parent = cache.get("entries_by_parent", {})
    collection_domains = cache.get("collection_domains", {})
    rig_depth = cache.get("rig_depth", {})
    gp_depth = cache.get("gp_depth", {})

    def add_rig(rig, collection, depth):
        rig_key = _fbp_id_key(rig)
        depth_value = round(float(rig_depth.get(rig_key, 0.0) or 0.0), 6)
        bits.append(
            "L:{depth}:{collection}:{sort_depth}:{rig}".format(
                depth=int(depth),
                collection=str(getattr(collection, "name", "") or ""),
                sort_depth=depth_value,
                rig=str(getattr(rig, "name", "") or ""),
            )
        )

    def add_gp_canvas(canvas, collection, depth):
        canvas_key = _fbp_id_key(canvas)
        depth_value = round(float(gp_depth.get(canvas_key, 0.0) or 0.0), 6)
        bits.append(
            "G:{depth}:{collection}:{sort_depth}:{canvas}".format(
                depth=int(depth),
                collection=str(getattr(collection, "name", "") or ""),
                sort_depth=depth_value,
                canvas=str(getattr(canvas, "name", "") or ""),
            )
        )

    def add_collection(collection, plane_depth=0, gp_list_depth=0, active=None):
        collection_name = str(getattr(collection, "name", "") or "")
        if not collection_name or bpy.data.collections.get(collection_name) is not collection:
            return
        collection_key = _fbp_id_key(collection)
        if active is None:
            active = set()
        if collection_key in active:
            return
        active.add(collection_key)
        collapsed = bool(getattr(collection, "fbp_collapsed", False))
        domain = str(collection_domains.get(collection_key, "PLANES") or "PLANES")
        row_depth = plane_depth if domain == "PLANES" else gp_list_depth
        try:
            explicit_order = float(getattr(collection, "fbp_layer_order", -1.0))
        except FBP_DATA_ERRORS:
            explicit_order = -1.0
        bits.append(
            "C:{depth}:{name}:{collapsed}:{order}:{domain}".format(
                depth=int(row_depth),
                name=str(getattr(collection, "name", "") or ""),
                collapsed=int(collapsed),
                order=explicit_order,
                domain=domain,
            )
        )
        if collapsed and not _fbp_layer_filter_active(context.scene):
            return
        child_plane_depth = plane_depth + (1 if domain == "PLANES" else 0)
        child_gp_depth = gp_list_depth + (1 if domain == "GP" else 0)
        for item_type, datablock in entries_by_parent.get(collection_key, ()):
            if item_type == "COLLECTION":
                add_collection(datablock, child_plane_depth, child_gp_depth, active)
            elif item_type == "GP_CANVAS":
                add_gp_canvas(datablock, collection, child_gp_depth)
            else:
                add_rig(datablock, collection, child_plane_depth)

    try:
        root = cache["root"]
        for item_type, datablock in entries_by_parent.get(cache["root_key"], ()):
            if item_type == "COLLECTION":
                add_collection(datablock, 0, 0)
            elif item_type == "GP_CANVAS":
                add_gp_canvas(datablock, root, 0)
            else:
                add_rig(datablock, root, 0)
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Layer tree signature failed", exc)
    signature = "|".join(bits)
    cache["_structural_signature"] = signature
    return signature



def _fbp_store_collection_row_snapshot(row, collection, context):
    """Copy collection UI state into scalar row properties outside draw()."""
    try:
        row.collection_collapsed = bool(getattr(collection, "fbp_collapsed", False))
        row.collection_visible = bool(get_collection_visible(collection))
        row.collection_solo = bool(get_collection_solo(collection))
        row.collection_holdout = bool(get_collection_holdout(collection))
        row.collection_plane_locked = bool(get_collection_plane_locked(collection))
        row.collection_locked = bool(get_collection_locked(collection))
        row.collection_selected = bool(get_collection_selected(collection))
        row.collection_color_tag = str(
            fbp_collection_effective_color_tag(collection, context) or "NONE"
        )
        return True
    except FBP_DATA_ERRORS:
        row.collection_collapsed = False
        row.collection_visible = True
        row.collection_solo = False
        row.collection_holdout = False
        row.collection_plane_locked = True
        row.collection_locked = False
        row.collection_selected = False
        row.collection_color_tag = "NONE"
        return False


def fbp_refresh_layer_tree_group_snapshots(context):
    """Refresh only scalar group rows from freshly resolved collections.

    This runs from the idle scheduler, never from Panel.draw/UIList.draw_item.
    It keeps selection and visibility feedback current without rebuilding the
    full tree or retaining Collection RNA wrappers between redraws.
    """
    if fbp_registration_busy():
        return False
    scene = getattr(context, "scene", None)
    rows = getattr(scene, "fbp_layer_tree_rows", None) if scene is not None else None
    if rows is None:
        return False
    changed = False
    try:
        for row in rows:
            if str(getattr(row, "row_type", "") or "") != "GROUP":
                continue
            name = str(getattr(row, "collection_name", "") or "")
            collection = bpy.data.collections.get(name) if name else None
            if collection is None:
                continue
            before = (
                bool(getattr(row, "collection_collapsed", False)),
                bool(getattr(row, "collection_visible", True)),
                bool(getattr(row, "collection_solo", False)),
                bool(getattr(row, "collection_holdout", False)),
                bool(getattr(row, "collection_plane_locked", True)),
                bool(getattr(row, "collection_locked", False)),
                bool(getattr(row, "collection_selected", False)),
                str(getattr(row, "collection_color_tag", "NONE") or "NONE"),
            )
            _fbp_store_collection_row_snapshot(row, collection, context)
            after = (
                bool(getattr(row, "collection_collapsed", False)),
                bool(getattr(row, "collection_visible", True)),
                bool(getattr(row, "collection_solo", False)),
                bool(getattr(row, "collection_holdout", False)),
                bool(getattr(row, "collection_plane_locked", True)),
                bool(getattr(row, "collection_locked", False)),
                bool(getattr(row, "collection_selected", False)),
                str(getattr(row, "collection_color_tag", "NONE") or "NONE"),
            )
            changed = changed or before != after
    except FBP_DATA_ERRORS:
        return changed
    return changed

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
    previous_collection_name = ""
    previous_row_type = ""
    try:
        if 0 <= previous_active < len(rows):
            active_row = rows[previous_active]
            previous_row_type = str(getattr(active_row, "row_type", "") or "")
            previous_collection_name = str(getattr(active_row, "collection_name", "") or "")
            previous_identity = (
                str(getattr(active_row, "row_type", "") or ""),
                str(getattr(active_row, "collection_name", "") or ""),
                str(getattr(active_row, "rig_name", "") or ""),
                str(getattr(active_row, "canvas_name", "") or ""),
                int(getattr(active_row, "layer_index", -1) or -1),
                str(getattr(active_row, "gp_layer_name", "") or ""),
            )
    except FBP_DATA_ERRORS:
        previous_identity = None

    cache = _fbp_build_layer_tree_cache(context, force=True)
    if not cache:
        return False

    rows.clear()
    entries_by_parent = cache.get("entries_by_parent", {})
    collection_domains = cache.get("collection_domains", {})
    layer_indices = cache["layer_index_by_key"]
    descendant_layer_keys = cache.get("descendant_layer_keys", {}) or {}
    descendant_gp_keys = cache.get("descendant_gp_keys", {}) or {}

    def _iter_gp_internal_layers(canvas):
        try:
            layers = getattr(getattr(canvas, "data", None), "layers", ()) or ()
            return tuple(layers)
        except FBP_DATA_ERRORS:
            return ()

    def add_gp_internal_layer(canvas, layer, collection, depth):
        if canvas is None or layer is None:
            return
        layer_name = str(getattr(layer, "name", "") or "Grease Pencil Layer")
        row = rows.add()
        row.row_type = "GP_LAYER"
        row.name = layer_name
        row.rig_name = ""
        row.canvas_name = str(getattr(canvas, "name", "") or "")
        row.gp_layer_name = layer_name
        row.collection_name = str(getattr(collection, "name", "") or "")
        row.layer_index = -1
        row.depth = max(0, int(depth))
        row.layer_count = 0
        row.gp_count = 0
        row.child_count = 0

    def add_gp_canvas(rig, canvas, collection, depth):
        if canvas is None:
            return
        canvas_name = str(getattr(canvas, "name", "") or "")
        if not canvas_name or bpy.data.objects.get(canvas_name) is not canvas:
            return
        row = rows.add()
        row.row_type = "GP_CANVAS"
        row.name = str(getattr(canvas, "name", "") or "Grease Pencil")
        row.rig_name = str(getattr(rig, "name", "") or "") if rig is not None else ""
        row.canvas_name = str(getattr(canvas, "name", "") or "")
        row.collection_name = str(getattr(collection, "name", "") or "")
        row.layer_index = int(layer_indices.get(_fbp_id_key(rig), -1)) if rig is not None else -1
        row.depth = max(0, int(depth))
        row.layer_count = 0
        internal_layers = _iter_gp_internal_layers(canvas)
        row.gp_count = 1 + len(internal_layers)
        row.child_count = len(internal_layers)
        try:
            expanded = bool(getattr(canvas, 'fbp_gp_layers_expanded', False))
        except FBP_DATA_ERRORS:
            expanded = False
        if expanded:
            # Blender's Grease Pencil layer stack is normally read bottom-to-top
            # from the RNA collection. The UI list must read like an animation
            # layer stack instead: the visually upper GP layer is drawn first,
            # matching the native Grease Pencil layer panel and keeping mask
            # operations intuitive (current layer clips to the row directly
            # underneath it). Do not mutate the native layer order here; this is
            # display-only.
            for layer in reversed(internal_layers):
                add_gp_internal_layer(canvas, layer, collection, depth + 1)

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
        row.gp_count = 0
        row.child_count = 0

    def add_collection(collection, plane_depth=0, gp_list_depth=0, active=None):
        if collection is None:
            return
        collection_name = str(getattr(collection, "name", "") or "")
        if not collection_name or bpy.data.collections.get(collection_name) is not collection:
            return
        collection_key = _fbp_id_key(collection)
        active = set(active or ())
        if collection_key in active:
            return
        active.add(collection_key)

        child_items = tuple(
            entry for entry in entries_by_parent.get(collection_key, ())
            if str(entry[0]) == "COLLECTION"
        )
        domain = str(collection_domains.get(collection_key, "PLANES") or "PLANES")
        row = rows.add()
        row.row_type = "GROUP"
        row.name = str(getattr(collection, "name", "") or "Collection")
        row.collection_name = str(getattr(collection, "name", "") or "")
        row.rig_name = ""
        row.layer_index = -1
        row.depth = max(0, int(plane_depth if domain == "PLANES" else gp_list_depth))
        row.layer_count = len(descendant_layer_keys.get(collection_key, ()))
        row.gp_count = len(descendant_gp_keys.get(collection_key, ()))
        row.child_count = len(child_items)
        row.list_domain = domain
        row.empty_managed_path = bool(
            collection_key in (cache.get("empty_managed_path_keys", ()) or ())
        )
        # Collection controls are rendered from this scalar snapshot. UIList
        # draw_item never reads Collection BoolProperties.
        _fbp_store_collection_row_snapshot(row, collection, context)

        if (
            bool(getattr(collection, "fbp_collapsed", False))
            and not _fbp_layer_filter_active(scene)
        ):
            return
        child_plane_depth = plane_depth + (1 if domain == "PLANES" else 0)
        child_gp_depth = gp_list_depth + (1 if domain == "GP" else 0)
        for item_type, datablock in entries_by_parent.get(collection_key, ()):
            if item_type == "COLLECTION":
                add_collection(datablock, child_plane_depth, child_gp_depth, active)
            elif item_type == "GP_CANVAS":
                add_gp_canvas(None, datablock, collection, child_gp_depth)
            else:
                add_layer(datablock, collection, child_plane_depth)

    try:
        root = cache["root"]
        for item_type, datablock in entries_by_parent.get(cache["root_key"], ()):
            if item_type == "COLLECTION":
                add_collection(datablock, 0, 0)
            elif item_type == "GP_CANVAS":
                add_gp_canvas(None, datablock, root, 0)
            else:
                add_layer(datablock, root, 0)
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
                    str(getattr(item, "canvas_name", "") or ""),
                    int(getattr(item, "layer_index", -1) or -1),
                    str(getattr(item, "gp_layer_name", "") or ""),
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
                            identity[4] >= 0
                            and identity[4] == previous_identity[4]
                        )
                    )
                ):
                    restored_index = index
                    break
                if (
                    previous_identity[0] == "GP_CANVAS"
                    and identity[0] == "GP_CANVAS"
                    and identity[1] == previous_identity[1]
                    and identity[3]
                    and identity[3] == previous_identity[3]
                ):
                    restored_index = index
                    break
                if (
                    previous_identity[0] == "GP_LAYER"
                    and identity[0] == "GP_LAYER"
                    and len(previous_identity) > 5
                    and len(identity) > 5
                    and identity[3] == previous_identity[3]
                    and identity[5] == previous_identity[5]
                ):
                    restored_index = index
                    break
        except FBP_DATA_ERRORS:
            restored_index = None

    # When collapsing a parent, the active child row disappears. Select the
    # nearest still-visible ancestor instead of clamping the stale integer to an
    # unrelated row farther down the list.
    if restored_index is None and previous_collection_name:
        try:
            collection_key_by_name = {
                str(getattr(collection, "name", "") or ""): key
                for key, collection in (cache.get("collections", {}) or {}).items()
            }
            collection_by_key = cache.get("collections", {}) or {}
            parent_by_key = cache.get("canonical_parent_by_key", {}) or {}
            current_key = collection_key_by_name.get(previous_collection_name)
            visible_group_indices = {
                str(getattr(item, "collection_name", "") or ""): index
                for index, item in enumerate(rows)
                if str(getattr(item, "row_type", "") or "") == "GROUP"
            }
            if previous_row_type == "GROUP" and previous_collection_name not in visible_group_indices:
                current_key = parent_by_key.get(current_key)
            while current_key and current_key != cache.get("root_key"):
                collection = collection_by_key.get(current_key)
                name = str(getattr(collection, "name", "") or "") if collection else ""
                if name in visible_group_indices:
                    restored_index = visible_group_indices[name]
                    break
                current_key = parent_by_key.get(current_key)
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
        signature = fbp_layer_tree_signature(context, tree_cache=cache)
        scene.fbp_layer_tree_signature = signature
        scene_key = fbp_obj_runtime_key(scene)
        if scene_key is not None:
            plane_count = 0
            gp_count = 0
            for row in rows:
                if fbp_layer_tree_row_visible_for_mode(row, "PLANES"):
                    plane_count += 1
                if fbp_layer_tree_row_visible_for_mode(row, "GP"):
                    gp_count += 1
            fbp_set_layer_tree_mode_counts(
                scene_key,
                signature,
                total=len(rows),
                planes=plane_count,
                grease_pencil=gp_count,
            )
    except FBP_DATA_ERRORS:
        pass
    return True


def fbp_schedule_layer_tree_rebuild(context, *, tree_cache=None, force=False):
    """Schedule a Layer Tree rebuild without traversing Collection RNA in draw."""
    scene = getattr(context, "scene", None)
    if scene is None:
        return False
    rows = getattr(scene, "fbp_layer_tree_rows", None)
    if rows is None:
        return False
    scene_key = fbp_obj_runtime_key(scene)
    if scene_key is None:
        return False
    try:
        rows_ready = bool(len(rows))
        signature_ready = bool(str(getattr(scene, "fbp_layer_tree_signature", "") or ""))
    except FBP_DATA_ERRORS:
        rows_ready = False
        signature_ready = False
    now = time.monotonic()
    last_check = float(_FBP_LAYER_TREE_LAST_CHECK.get(scene_key, 0.0) or 0.0)
    if (
        not force
        and rows_ready
        and signature_ready
        and now - last_check < _FBP_LAYER_TREE_CHECK_INTERVAL
    ):
        return False
    _FBP_LAYER_TREE_LAST_CHECK[scene_key] = now
    if len(_FBP_LAYER_TREE_LAST_CHECK) > 16:
        oldest = sorted(_FBP_LAYER_TREE_LAST_CHECK.items(), key=lambda item: item[1])[:-8]
        for stale_key, _timestamp in oldest:
            _FBP_LAYER_TREE_LAST_CHECK.pop(stale_key, None)
    generation = _fbp_ui_rebuild_generation(_FBP_LAYER_TREE_REBUILD_GENERATIONS, scene_key)

    def _timer():
        if _fbp_ui_rebuild_generation(_FBP_LAYER_TREE_REBUILD_GENERATIONS, scene_key) != generation:
            return None
        retry_delay = ui_list_mutation_delay()
        if retry_delay > 0.0:
            return retry_delay
        try:
            current_context = bpy.context
            current_scene = getattr(current_context, "scene", None)
            try:
                if current_scene is None or fbp_obj_runtime_key(current_scene) != scene_key:
                    return None
                if fbp_registration_busy():
                    return 0.20
                current_rows = getattr(current_scene, "fbp_layer_tree_rows", None)
                if current_rows is None:
                    return None
                cache = _fbp_build_layer_tree_cache(current_context, force=True)
                current_signature = fbp_layer_tree_signature(
                    current_context, tree_cache=cache
                )
                stored_signature = str(
                    getattr(current_scene, "fbp_layer_tree_signature", "") or ""
                )
                if force or len(current_rows) == 0 or stored_signature != current_signature:
                    fbp_rebuild_layer_tree_rows(current_context)
                else:
                    # Structural identity is unchanged, but collection state may
                    # have changed through the Outliner, viewport or shortcuts.
                    fbp_refresh_layer_tree_group_snapshots(current_context)
            except Exception as exc:
                fbp_warn("Layer tree scheduled rebuild failed", exc)
            return None
        finally:
            _fbp_finish_ui_rebuild_generation(
                _FBP_LAYER_TREE_REBUILD_GENERATIONS, scene_key, generation
            )

    accepted = _safe_tasks.schedule_once(
        f"ui.layer_tree_rebuild.{scene_key}",
        _timer,
        first_interval=0.10,
    )
    if not accepted:
        _fbp_finish_ui_rebuild_generation(
            _FBP_LAYER_TREE_REBUILD_GENERATIONS, scene_key, generation
        )
    return bool(accepted)


def fbp_refresh_layer_tree_rows(context_or_scene):
    """Refresh layer rows only after Blender has released active UIList wrappers."""
    context = context_or_scene if hasattr(context_or_scene, 'scene') else bpy.context
    _fbp_cancel_layer_tree_rebuild(getattr(context, "scene", None))
    retry_delay = ui_list_mutation_delay()
    if retry_delay > 0.0:
        fbp_schedule_layer_tree_rebuild(context, force=True)
        return True
    try:
        return bool(fbp_rebuild_layer_tree_rows(context))
    except Exception as exc:
        try:
            fbp_warn('Layer tree refresh failed', exc)
        except FBP_DATA_IO_ERRORS:
            pass
    return False


def draw_layer_tree_uilist(layout, context, *, min_rows=10, list_type='ALL'):
    """Draw the Layers panel using one shared O(layers + collections) snapshot.

    list_type can be 'ALL', 'PLANES' or 'GP'.  The rows collection is shared;
    UIList filtering determines which virtual rows are visible.
    """
    sc = context.scene
    # Panel draw consumes only scalar virtual rows. Hierarchy traversal and RNA
    # access happen later from Blender's idle timer.
    if fbp_registration_busy():
        hint_row(layout, "Reloading Frame By Plane…", icon="FILE_REFRESH")
        return
    rows_collection = getattr(sc, "fbp_layer_tree_rows", ()) or ()
    fbp_schedule_layer_tree_rebuild(context)
    if not rows_collection:
        try:
            has_runtime_layers = bool(len(getattr(sc, "fbp_layers", ()) or ()))
        except FBP_DATA_ERRORS:
            has_runtime_layers = False
        if has_runtime_layers:
            hint_row(layout, "Refreshing layer tree…", icon="FILE_REFRESH")
        else:
            empty_state(layout, "No Frame By Plane layers", "Create or import a plane to begin.", icon="INFO", boxed=False)
        return

    row_count = len(rows_collection)
    if row_count == 0:
        hint_row(layout, "Refreshing layer tree…", icon="FILE_REFRESH")
    else:
        mode = str(list_type or 'ALL').upper()
        scene_key = fbp_obj_runtime_key(sc)
        stored_signature = str(getattr(sc, "fbp_layer_tree_signature", "") or "")
        cached_counts = (
            fbp_layer_tree_mode_counts(scene_key, stored_signature)
            if scene_key is not None else None
        )
        if mode == 'PLANES':
            # Counts are produced once by the structural rebuild instead of
            # rescanning every virtual row for every panel redraw.
            visible_row_count = (
                int(cached_counts.get("planes", 0))
                if cached_counts is not None
                else sum(
                    1 for row in rows_collection
                    if fbp_layer_tree_row_visible_for_mode(row, 'PLANES')
                )
            )
            if visible_row_count <= 0:
                empty_state(layout, "No plane layers", "Create or import a plane to populate this list.", icon="INFO", boxed=False)
                return
        elif mode == 'GP':
            visible_row_count = (
                int(cached_counts.get("gp", 0))
                if cached_counts is not None
                else sum(
                    1 for row in rows_collection
                    if fbp_layer_tree_row_visible_for_mode(row, 'GP')
                )
            )
            if visible_row_count <= 0:
                empty_state(layout, "No Grease Pencil layers", "Create a Grease Pencil canvas to populate this list.", icon="GREASEPENCIL", boxed=False)
                return
        else:
            visible_row_count = row_count
    # Keep the list at least as tall as the adjacent toolbar.  A shorter
    # UIList left an empty grey strip below it while the side buttons continued
    # farther down, especially in compact projects with only a few layers.
    minimum = max(1, int(min_rows or 1))
    mode = str(list_type or 'ALL').upper()
    if mode in {'PLANES', 'GP'}:
        # The dedicated Plane and Grease Pencil lists must keep a compact,
        # predictable height even when their collections are expanded.  Their
        # visible row count is controlled by scrolling, not by growing the panel.
        visible_rows = minimum
    else:
        try:
            count_for_height = int(visible_row_count)
        except Exception:
            count_for_height = row_count
        visible_rows = max(minimum, min(18, max(count_for_height, 1)))
    list_cls = "FBP_UL_LayerTreeList"
    if mode == 'PLANES':
        list_cls = "FBP_UL_LayerTreePlanesList"
    elif mode == 'GP':
        list_cls = "FBP_UL_GreasePencilLayerList"
    layout.template_list(
        list_cls,
        "",
        sc,
        "fbp_layer_tree_rows",
        sc,
        "fbp_layer_tree_rows_idx",
        rows=visible_rows,
    )

def draw_gp_layer_tree_uilist(layout, context, *, min_rows=7):
    """Draw only Grease Pencil canvas rows using the shared layer-tree cache."""
    return draw_layer_tree_uilist(layout, context, min_rows=min_rows, list_type='GP')


def draw_pending_setup_grouped(layout, context):
    """Draw the responsive Multiplane Setup tree with a standard side toolbar.

    The caller already owns the outer box. The UIList is the flexible element
    on the left, while a single icon-wide column on the right mirrors Blender's
    other list controls. Per-row actions remain inside the UIList itself.
    """
    sc = context.scene

    items = getattr(sc, 'fbp_pending_planes', [])
    if not items:
        empty_state(
            layout,
            "Setup is empty",
            "Add a layer or scan a project folder before generating the Multiplane.",
            icon="INFO",
            boxed=False,
        )
        tools = layout.row(align=True)
        tools.operator('fbp.add_pending_plane', icon=ui_icon('generic.add'), text='Add Layer')
        tools.operator('fbp.add_pending_collection', icon=ui_icon('setup.collection_new'), text='Add Collection')
        return

    # IMPORTANT: never rebuild Scene collections inside draw().
    fbp_schedule_pending_tree_rebuild(sc)


    visible_row_count = len(getattr(sc, 'fbp_pending_tree_rows', []))
    if visible_row_count == 0:
        hint_row(layout, 'Refreshing setup tree…', icon='FILE_REFRESH')
    rows = list_rows(visible_row_count, minimum=9, maximum=14)

    list_box = fbp_draw_uilist_header(
        layout, context, "PENDING_SETUP"
    )

    list_row = list_box.row(align=False)
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
    fbp_set_ui_units_x(side, 1.0)
    side.menu("FBP_MT_pending_setup_actions", text="", icon="COLLAPSEMENU")

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
    movement = side.column(align=True)
    move_up = movement.row(align=True)
    move_up.enabled = bool(active_is_layer and getattr(active_row, 'can_move_up', False))
    op = move_up.operator('fbp.move_pending_plane', text='', icon='SORT_DESC')
    op.direction = 'UP'
    op.index = active_pending_index

    move_down = movement.row(align=True)
    move_down.enabled = bool(active_is_layer and getattr(active_row, 'can_move_down', False))
    op = move_down.operator('fbp.move_pending_plane', text='', icon='SORT_ASC')
    op.direction = 'DOWN'
    op.index = active_pending_index

    side.separator()
    side.menu("FBP_MT_pending_setup_add", text="", icon="ADD")


def _draw_import_alpha_crop_options(layout, scene, context=None):
    """Draw import-time alpha crop controls without clipping narrow sidebars."""
    row = adaptive_row(layout, context) if context is not None else layout.row(align=True)
    row.prop(scene, "fbp_import_crop_alpha", text="Crop Transparent Borders", icon='FULLSCREEN_EXIT')
    padding = row.row(align=True)
    padding.enabled = bool(getattr(scene, "fbp_import_crop_alpha", False))
    padding.prop(scene, "fbp_import_crop_alpha_padding", text="Padding")


def _fbp_ui_icon_section_header(layout, title, icon_key, fallback="BLANK1", *, count=None):
    """Draw a shared section header using a native or registered custom icon."""
    kwargs = ui_label_icon_kwargs(icon_key, fallback=fallback)
    return section_header(
        layout,
        title,
        icon=kwargs.get("icon", fallback),
        icon_value=kwargs.get("icon_value", 0),
        count=count,
    )


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
    configure_layout(layout)
    sc = context.scene
    mode = str(getattr(sc, 'fbp_creation_mode', 'SINGLE') or 'SINGLE')
    mode_icon = {
        'SINGLE': ui_icon('menu.image_plane'),
        'MULTI': ui_icon('menu.multiplane'),
        'CUTOUT': ui_icon('create.cutout_plane'),
        'VIDEO': ui_icon('menu.video_plane'),
        'COLOR': ui_icon('menu.color_plane'),
        'GRADIENT': ui_icon('menu.gradient_plane'),
        'HOLDOUT': ui_icon('menu.holdout_plane'),
    }.get(mode, ui_icon('create.header'))

    selector = layout.row(align=False)
    selector.scale_y = 1.15
    selector.prop(sc, "fbp_creation_mode", text="Create", icon=mode_icon)
    section_gap(layout)

    if mode == 'SINGLE':
        box = layout.box()
        _fbp_ui_icon_section_header(box, "Single Plane", "menu.image_plane", "setup.image")
        row = adaptive_row(box, context)
        row.prop(sc, "fbp_pre_duration", text='Frame Hold')
        row.prop(sc, "fbp_pre_shadeless", text="Emission Texture", icon=fbp_icon("LIGHT_SUN"), toggle=True)
        row = box.row(align=True)
        row.prop(sc, "fbp_pre_loop_mode", expand=True)
        box.prop(sc, "fbp_pre_interpolation", text="Filtering", expand=False)
        box.prop(sc, "fbp_pre_orientation", expand=False)
        _draw_import_alpha_crop_options(box, sc, context)
        section_gap(layout)
        row = layout.row(align=False)
        row.scale_y = 1.2
        op = row.operator("fbp.import_sequence", text="Create Single Plane", **ui_icon_kwargs("menu.image_plane", fallback="setup.image"))
        op.media_filter = 'IMAGES'
        return


    if mode == 'VIDEO':
        box = layout.box()
        _fbp_ui_icon_section_header(box, "Video Plane", "menu.video_plane", "FILE_MOVIE")
        row = adaptive_row(box, context)
        row.prop(sc, "fbp_pre_duration", text='Frame Hold')
        row.prop(sc, "fbp_pre_shadeless", text="Emission Texture", icon=fbp_icon("LIGHT_SUN"), toggle=True)
        box.prop(sc, "fbp_pre_interpolation", text="Filtering", expand=False)
        box.prop(sc, "fbp_pre_orientation", expand=False)
        section_gap(layout)
        row = layout.row(align=False)
        row.scale_y = 1.2
        op = row.operator("fbp.import_sequence", text="Create Video Plane", **ui_icon_kwargs("menu.video_plane", fallback="FILE_MOVIE"))
        op.media_filter = 'VIDEO'
        return

    if mode == 'CUTOUT':
        box = layout.box()
        _fbp_ui_icon_section_header(box, "Cutout Plane", "menu.cutout_plane", "create.cutout_plane")
        box.prop(sc, "fbp_pre_interpolation", text="Filtering", expand=False)
        box.prop(sc, "fbp_pre_orientation", expand=False)
        section_gap(layout)
        row = layout.row(align=False)
        row.scale_y = 1.2
        row.operator("fbp.import_drawing_plane", text="Create Cutout Plane", **ui_icon_kwargs("menu.cutout_plane", fallback="create.cutout_plane"))
        return

    if mode in {'COLOR', 'GRADIENT', 'HOLDOUT'}:
        box = layout.box()
        if mode == 'COLOR':
            _fbp_ui_icon_section_header(box, "Color Plane", "menu.color_plane", "create.color_plane")
            row = box.row(align=False)
            row.prop(sc, "fbp_color_plane_emission", text="Emission", icon=fbp_icon("LIGHT_SUN"), toggle=True)
            fbp_draw_color_plane_color_row(box, sc)
            button_text = "Create Color Plane"
            button_icon_key = "menu.color_plane"
            button_icon_fallback = "create.color_plane"
            plane_type = 'CUSTOM'
        elif mode == 'GRADIENT':
            _fbp_ui_icon_section_header(box, "Gradient Plane", "menu.gradient_plane", "menu.gradient_plane")
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
                row = adaptive_row(gbox, context)
                row.prop(sc, "fbp_gradient_offset_x", text="X")
                row.prop(sc, "fbp_gradient_offset_y", text="Y")
                row = adaptive_row(gbox, context)
                row.prop(sc, "fbp_gradient_scale_x", text="Scale X")
                row.prop(sc, "fbp_gradient_scale_y", text="Scale Y")
                gbox.prop(sc, "fbp_gradient_rotation", text="Rotation")
            button_text = "Create Gradient Plane"
            button_icon_key = "menu.gradient_plane"
            button_icon_fallback = "menu.gradient_plane"
            plane_type = 'GRADIENT'
        else:
            _fbp_ui_icon_section_header(box, "Holdout Plane", "menu.holdout_plane", "menu.holdout_plane")
            button_text = "Create Holdout Plane"
            button_icon_key = "menu.holdout_plane"
            button_icon_fallback = "menu.holdout_plane"
            plane_type = 'HOLDOUT'

        box.prop(sc, "fbp_pre_orientation", expand=False)
        section_gap(layout)
        row = layout.row(align=False)
        row.scale_y = 1.2
        op = row.operator(
            "fbp.create_color_plane",
            text=button_text,
            **ui_icon_kwargs(button_icon_key, fallback=button_icon_fallback),
        )
        op.plane_type = plane_type
        return

    # MULTIPLANE
    box = layout.box()
    _fbp_ui_icon_section_header(box, "Multiplane", "menu.multiplane", "menu.multiplane")
    row = adaptive_row(box, context)
    row.prop(sc, "fbp_pre_duration", text="Frame Hold")
    row.prop(sc, "fbp_pre_shadeless", text="Emission Texture", icon=fbp_icon("LIGHT_SUN"), toggle=True)
    box.prop(sc, "fbp_pre_loop_mode", expand=False)
    box.prop(sc, "fbp_pre_interpolation", expand=False)
    box.prop(sc, "fbp_pre_orientation", expand=False)
    _draw_import_alpha_crop_options(box, sc, context)

    box = layout.box()
    section_header(box, "Camera Setup", icon=fbp_icon("RESTRICT_VIEW_ON"))
    row = adaptive_row(box, context)
    cam_icon = fbp_icon("VIEW_CAMERA") if sc.fbp_gen_camera else 'CAMERA_DATA'
    row.operator("fbp.popup_generate_camera", text="Create Camera", icon=cam_icon, depress=bool(sc.fbp_gen_camera))
    row.prop(sc, "fbp_cam_pivot", text='3D Cursor on Camera', icon=fbp_icon("PIVOT_CURSOR"), toggle=True)
    row = adaptive_row(box, context)
    row.prop(sc, "fbp_layer_offset", text='Plane Distance')
    row.prop(sc, "fbp_auto_scale", text='Fit to Camera', icon=fbp_icon("FULLSCREEN_ENTER"), toggle=True)

    section_gap(layout)

    row = layout.row(align=False)
    row.prop(
        sc,
        "fbp_show_project_tools",
        text="Project Folder",
        icon=(fbp_icon("DOWNARROW_HLT") if sc.fbp_show_project_tools else fbp_icon("RIGHTARROW")),
    )
    if sc.fbp_show_project_tools:
        box = layout.box()
        box.prop(sc, "fbp_project_path", text="")
        row = adaptive_row(box, context)
        row.operator("fbp.scan_project_to_setup", icon=fbp_icon("IMPORT"), text="Scan to Setup")
        row.operator("fbp.auto_scene_builder", icon=fbp_icon("OUTLINER_COLLECTION"), text="Build Direct")

    box = layout.box()
    _fbp_ui_icon_section_header(box, "Multiplane Setup", "menu.multiplane", "menu.multiplane")
    draw_pending_setup_grouped(box, context)

    pending = bool(getattr(sc, "fbp_pending_planes", None) and len(sc.fbp_pending_planes) > 0)
    if is_compact(context):
        primary = layout.row(align=True)
        primary.scale_y = 1.2
        primary.enabled = pending
        primary.operator("fbp.generate_multiplane", text="Create Multiplane", **ui_icon_kwargs("menu.multiplane", fallback="menu.multiplane"))
        secondary = layout.row(align=True)
        secondary.enabled = pending
        secondary.operator("fbp.clear_pending_planes", icon=fbp_icon("TRASH"), text="Clear Setup")
    else:
        row = layout.row(align=False)
        row.scale_y = 1.2
        split = row.split(factor=0.67, align=False)
        left = split.row(align=True)
        right = split.row(align=True)
        left.enabled = pending
        right.enabled = pending
        left.operator("fbp.generate_multiplane", text="Create Multiplane", **ui_icon_kwargs("menu.multiplane", fallback="menu.multiplane"))
        right.operator("fbp.clear_pending_planes", icon=fbp_icon("TRASH"), text="Clear Setup")


def register():
    _FBP_LAYER_TREE_REBUILD_GENERATIONS.clear()
    _FBP_PENDING_TREE_REBUILD_GENERATIONS.clear()
    _FBP_LAYER_TREE_LAST_CHECK.clear()


def unregister():
    _safe_tasks.cancel_scheduled_prefixes(
        "ui.layer_tree_rebuild.",
        "ui.pending_tree_rebuild.",
    )
    _FBP_LAYER_TREE_REBUILD_GENERATIONS.clear()
    _FBP_PENDING_TREE_REBUILD_GENERATIONS.clear()
    _FBP_LAYER_TREE_LAST_CHECK.clear()
