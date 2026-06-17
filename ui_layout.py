"""Reusable UI layout helpers for Frame by Plane panels and lists."""

import bpy

from .constants import fbp_icon
from .path_utils import natural_sort_key
from .runtime import fbp_warn
from .layers import (
    collection_has_fbp_content,
    get_child_fbp_collections,
    get_direct_fbp_rigs_in_collection,
    get_primary_fbp_collection,
    get_top_fbp_collections,
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


def _fbp_pending_file_count(item):
    try:
        return len([f for f in str(getattr(item, 'files_str', '') or '').split('|') if f])
    except Exception:
        return 0


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

    rows.clear()

    tree = _fbp_pending_tree(scene)
    sort_alpha = bool(getattr(scene, 'fbp_sort_layers_alpha', False))

    def add_layer_row(index, item, depth):
        row = rows.add()
        row.row_type = 'LAYER'
        row.name = getattr(item, 'name', '') or 'Unnamed Layer'
        row.collection_path = getattr(item, 'collection_name', '') or 'Unsorted'
        row.pending_index = int(index)
        row.depth = max(0, int(depth))
        row.file_count = _fbp_pending_file_count(item)
        row.layer_count = 0
        row.child_count = 0

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
            group.collection_color_editable = _fbp_pending_collection_color_is_editable(child)
            group.collection_color_tag = _fbp_pending_collection_display_color(child)

            if pending_collection_is_open(scene, path):
                add_node(child, depth + 1)

        for index, item in items:
            add_layer_row(index, item, depth)

    add_node(tree, 0)

    try:
        if len(rows):
            scene.fbp_pending_tree_rows_idx = min(max(0, previous_active), len(rows) - 1)
        else:
            scene.fbp_pending_tree_rows_idx = 0
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

    try:
        scene_pointer = int(scene.as_pointer())
        scene_name = str(scene.name)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return

    def _timer():
        target_scene = bpy.data.scenes.get(scene_name)
        try:
            if not target_scene or int(target_scene.as_pointer()) != scene_pointer:
                target_scene = next(
                    (item for item in bpy.data.scenes if int(item.as_pointer()) == scene_pointer),
                    None,
                )
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            target_scene = None
        if not target_scene:
            return None
        try:
            fbp_rebuild_pending_tree_rows(target_scene)
        except Exception as exc:
            try:
                fbp_warn('Multiplane Setup tree rebuild failed', exc)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
        return None

    _safe_tasks.schedule_once(
        f'ui.pending_tree_rebuild.{scene_pointer}',
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
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    return False


# SECTION 02B - Layers UIList tree helpers #
# ###ICON Panel Layer Stack UIList, Function Collection: setup.collection
# ###ICON Panel Layer Stack UIList, Function Collapse: setup.collapsed / setup.expanded
# ###ICON Panel Layer Stack UIList, Function Layer: layer.color_tag / thumbnail


def _fbp_layer_index_map(scene):
    mapping = {}
    try:
        for idx, item in enumerate(scene.fbp_layers):
            rig = getattr(item, 'obj', None)
            if rig:
                mapping[getattr(rig, 'name', '')] = idx
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    return mapping


def fbp_layer_tree_signature(context):
    """Return a lightweight signature for the visible Layer Stack tree.

    This is safe to call from draw(): it only reads Scene/Collection/Object state.
    If the signature changes, a timer rebuilds the virtual UIList rows later.
    """
    scene = getattr(context, 'scene', None)
    if not scene:
        return ''
    bits = []
    try:
        bits.append('alpha=' + str(bool(getattr(scene, 'fbp_sort_layers_alpha', False))))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

    def add_collection(coll, depth=0):
        if not coll or not collection_has_fbp_content(coll, True):
            return
        try:
            bits.append(f"C:{depth}:{coll.name}:{getattr(coll, 'color_tag', '')}:{bool(getattr(coll, 'fbp_collapsed', False))}:{bool(getattr(coll, 'fbp_collection_visible', True))}:{bool(getattr(coll, 'fbp_collection_locked', False))}:{bool(getattr(coll, 'fbp_collection_solo', False))}:{bool(getattr(coll, 'fbp_collection_holdout', False))}")
        except Exception:
            bits.append(f"C:{depth}:{getattr(coll, 'name', '')}")
        # Visibility must not collapse the virtual tree: hidden folders still
        # expose their children so local layer eyes and other controls remain
        # reachable. Only the explicit disclosure state hides child rows.
        if bool(getattr(coll, 'fbp_collapsed', False)):
            return
        for child in get_child_fbp_collections(coll):
            add_collection(child, depth + 1)
        for rig in reversed(get_direct_fbp_rigs_in_collection(context, coll)):
            add_rig(rig, depth + 1)

    def add_rig(rig, depth=0):
        if not rig:
            return
        try:
            bits.append(
                f"L:{depth}:{rig.name}:"
                f"{bool(getattr(rig, 'fbp_is_visible', True))}:"
                f"{bool(rig.select_get())}:"
                f"{getattr(rig, 'fbp_color_tag', '')}:"
                f"{getattr(rig, 'fbp_preview_path', '')}:"
                f"{getattr(rig, 'fbp_color_plane_mode', '')}:"
                f"{tuple(getattr(rig, 'fbp_color_plane_color', ())) if hasattr(rig, 'fbp_color_plane_color') else ''}:"
                f"{tuple(getattr(rig, 'fbp_gradient_color_a', ())) if hasattr(rig, 'fbp_gradient_color_a') else ''}:"
                f"{tuple(getattr(rig, 'fbp_gradient_color_b', ())) if hasattr(rig, 'fbp_gradient_color_b') else ''}:"
                f"{len(getattr(rig, 'fbp_images', []))}"
            )
        except Exception:
            bits.append(f"L:{depth}:{getattr(rig, 'name', '')}")

    try:
        for coll in get_top_fbp_collections(context):
            add_collection(coll, 0)
        for rig in reversed(get_direct_fbp_rigs_in_collection(context, scene.collection)):
            add_rig(rig, 0)
    except Exception as exc:
        try:
            fbp_warn('Layer tree signature failed', exc)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    return '|'.join(bits)


def fbp_rebuild_layer_tree_rows(context):
    """Rebuild the virtual UIList rows for the Layers panel tree.

    The actual data remains in Scene.fbp_layers and the real Collection/Object
    properties. This function only creates visible rows for template_list().
    It must never be called from draw(); use fbp_schedule_layer_tree_rebuild().
    """
    scene = getattr(context, 'scene', None)
    if not scene:
        return False
    rows = getattr(scene, 'fbp_layer_tree_rows', None)
    if rows is None:
        return False

    try:
        previous_active = int(getattr(scene, 'fbp_layer_tree_rows_idx', 0))
    except Exception:
        previous_active = 0

    rows.clear()
    layer_indices = _fbp_layer_index_map(scene)

    def add_layer(rig, depth):
        if not rig:
            return
        row = rows.add()
        row.row_type = 'LAYER'
        row.name = getattr(rig, 'name', '') or 'Unnamed Layer'
        row.rig_name = getattr(rig, 'name', '') or ''
        row.collection_name = ''
        try:
            primary = get_primary_fbp_collection(rig)
            row.collection_name = getattr(primary, 'name', '') or ''
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        row.layer_index = int(layer_indices.get(row.rig_name, -1))
        row.depth = max(0, int(depth))
        row.layer_count = 0
        row.child_count = 0

    def add_collection(coll, depth=0):
        if not coll or not collection_has_fbp_content(coll, True):
            return
        row = rows.add()
        row.row_type = 'GROUP'
        row.name = getattr(coll, 'name', '') or 'Collection'
        row.collection_name = getattr(coll, 'name', '') or ''
        row.rig_name = ''
        row.layer_index = -1
        row.depth = max(0, int(depth))
        try:
            row.layer_count = len(get_direct_fbp_rigs_in_collection(context, coll))
            row.child_count = len(get_child_fbp_collections(coll))
        except Exception:
            row.layer_count = 0
            row.child_count = 0

        # Visibility must not collapse the virtual tree: hidden folders still
        # expose their children so local layer eyes and other controls remain
        # reachable. Only the explicit disclosure state hides child rows.
        if bool(getattr(coll, 'fbp_collapsed', False)):
            return
        for child in get_child_fbp_collections(coll):
            add_collection(child, depth + 1)
        for rig in reversed(get_direct_fbp_rigs_in_collection(context, coll)):
            add_layer(rig, depth + 1)

    try:
        for coll in get_top_fbp_collections(context):
            add_collection(coll, 0)
        for rig in reversed(get_direct_fbp_rigs_in_collection(context, scene.collection)):
            add_layer(rig, 0)
    except Exception as exc:
        try:
            fbp_warn('Layer tree rebuild failed', exc)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass

    try:
        if len(rows):
            scene.fbp_layer_tree_rows_idx = min(max(0, previous_active), len(rows) - 1)
        else:
            scene.fbp_layer_tree_rows_idx = 0
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

    try:
        scene.fbp_layer_tree_signature = fbp_layer_tree_signature(context)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    return True


def fbp_schedule_layer_tree_rebuild(context):
    """Schedule a safe rebuild of the Layers UIList tree after draw()."""
    scene = getattr(context, 'scene', None)
    if not scene:
        return
    rows = getattr(scene, 'fbp_layer_tree_rows', None)
    if rows is None:
        return

    current_sig = fbp_layer_tree_signature(context)
    try:
        stored_sig = getattr(scene, 'fbp_layer_tree_signature', '')
    except Exception:
        stored_sig = ''

    needs_rebuild = False
    try:
        needs_rebuild = len(rows) == 0 or stored_sig != current_sig
    except Exception:
        needs_rebuild = True
    if not needs_rebuild:
        return

    try:
        scene_pointer = int(scene.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return

    def _timer():
        current_context = bpy.context
        current_scene = getattr(current_context, 'scene', None)
        try:
            if (
                not current_scene
                or int(current_scene.as_pointer()) != scene_pointer
            ):
                # Do not rebuild rows for a different active Scene. The target
                # panel will schedule itself again the next time it is drawn.
                return None
            fbp_rebuild_layer_tree_rows(current_context)
        except Exception as exc:
            try:
                fbp_warn('Layer tree scheduled rebuild failed', exc)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
        return None

    _safe_tasks.schedule_once(
        f'ui.layer_tree_rebuild.{scene_pointer}',
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
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    return False


def draw_layer_tree_uilist(layout, context):
    """Draw the Layers panel as a true Blender UIList tree."""
    sc = context.scene
    roots = get_top_fbp_collections(context)
    direct_scene_rigs = get_direct_fbp_rigs_in_collection(context, sc.collection)
    if not roots and not direct_scene_rigs:
        # Scene switches can happen before the scene-sync timer has rebuilt the
        # collection cache. Do not permanently show an empty state if FBP rigs
        # exist in the new scene; schedule a safe refresh instead.
        has_fbp_objects = False
        try:
            has_fbp_objects = any(is_fbp_layer_object(obj) for obj in sc.objects)
        except Exception:
            has_fbp_objects = False
        if has_fbp_objects or len(getattr(sc, 'fbp_layers', [])):
            fbp_schedule_layer_tree_rebuild(context)
            layout.label(text='Refreshing layer tree...', icon=ui_icon('generic.info'))
            return
        layout.label(text='No Frame by Plane layers', icon=ui_icon('generic.info'))
        return

    fbp_schedule_layer_tree_rebuild(context)

    row_count = len(getattr(sc, 'fbp_layer_tree_rows', []))
    if row_count == 0:
        layout.label(text='Refreshing layer tree...', icon=ui_icon('generic.info'))
    rows = max(4, min(18, max(row_count, 1)))
    layout.template_list(
        'FBP_UL_LayerTreeList',
        '',
        sc,
        'fbp_layer_tree_rows',
        sc,
        'fbp_layer_tree_rows_idx',
        rows=rows,
    )

def draw_pending_setup_grouped(layout, context):
    """Draw the Multiplane Setup as a real Blender UIList tree.

    Uses template_list() while keeping tree behaviour:
    folder/scene rows are virtual UIList rows with TRIA_RIGHT / TRIA_DOWN,
    while child layers are hidden or shown depending on the collapsed state.
    """
    sc = context.scene
    items = getattr(sc, 'fbp_pending_planes', [])
    if not items:
        layout.label(text='No layers in setup')
        tools = layout.row(align=True)
        tools.operator('fbp.add_pending_plane', icon=ui_icon('generic.add'), text='Add Layer')
        tools.operator('fbp.add_pending_collection', icon=ui_icon('setup.collection_new'), text='New Collection')
        return

    # IMPORTANT: do not rebuild Scene.fbp_pending_tree_rows inside draw().
    # Blender forbids writing to ID data-blocks from UI draw callbacks.
    # The virtual tree rows are rebuilt by setup operators and, as a fallback,
    # by a small delayed timer scheduled from here without touching Scene data.
    fbp_schedule_pending_tree_rebuild(sc)

    tree_box = layout.box()
    header = tree_box.row(align=True)
    header.label(text='Import Tree', icon=ui_icon('setup.collection'))

    visible_row_count = len(getattr(sc, 'fbp_pending_tree_rows', []))
    if visible_row_count == 0:
        tree_box.label(text='Refreshing setup tree...')
    rows = max(4, min(14, max(visible_row_count, 1)))
    list_row = tree_box.row(align=True)
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
    side.operator('fbp.add_pending_plane', icon=ui_icon('generic.add'), text='')
    side.operator('fbp.add_pending_collection', icon=ui_icon('setup.collection_new'), text='')
    side.separator()
    side.operator('fbp.remove_pending_tree_selection', icon=ui_icon('generic.delete'), text='')


# SECTION 02 - Create UI: Single / Multiplane / Color #
# ###ICON Panel Create, Function Color Plane: create.color_plane
# ###ICON Panel Create, Function Single Plane: create.single_plane
# ###ICON Panel Create, Function Multiplane: create.multiplane
# ###ICON Panel Create, Function Emission: create.emission
# ###ICON Panel Create, Function Camera/Fit: create.camera / create.fit_camera

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
        box.prop(sc, "fbp_pre_orientation", expand=False)
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
    row.operator("fbp.popup_generate_camera", text="Generate Camera", icon=cam_icon, depress=bool(sc.fbp_gen_camera))
    row.prop(sc, "fbp_cam_pivot", text='3D Cursor on Camera', icon=fbp_icon("PIVOT_CURSOR"), toggle=True)
    row = box.row(align=False)
    row.prop(sc, "fbp_layer_offset", text='Plane Distance')
    row.prop(sc, "fbp_auto_scale", text='Fit to Camera', icon=fbp_icon("FULLSCREEN_ENTER"), toggle=True)

    layout.separator()

    row = layout.row(align=True)
    row.prop(sc, "fbp_show_project_tools", text="Import Project", icon=(fbp_icon("DOWNARROW_HLT") if sc.fbp_show_project_tools else fbp_icon("RIGHTARROW")))
    if sc.fbp_show_project_tools:
        box = layout.box()
        box.prop(sc, "fbp_project_path", text="")
        row = box.row(align=True)
        row.operator("fbp.scan_project_to_setup", icon=fbp_icon("IMPORT"), text="Import to Setup")
        row.operator("fbp.auto_scene_builder", icon=fbp_icon("OUTLINER_COLLECTION"), text="Build Direct")

    box = layout.box()
    box.label(text="Multiplane Setup", icon=fbp_icon("RENDERLAYERS"))
    draw_pending_setup_grouped(box, context)

    row = layout.row(align=True)
    row.scale_y = 1.2
    split = row.split(factor=0.67, align=True)
    left = split.row(align=True)
    right = split.row(align=True)
    pending = bool(getattr(sc, "fbp_pending_planes", None) and len(sc.fbp_pending_planes) > 0)
    left.enabled = pending
    right.enabled = pending
    left.operator("fbp.generate_multiplane", text="Generate Multiplane", icon=fbp_icon("RENDERLAYERS"))
    right.operator("fbp.clear_pending_planes", icon=fbp_icon("TRASH"), text="Clear Setup")

