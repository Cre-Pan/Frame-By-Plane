"""Panels, UILists, Shift+A menu entries and render menu hooks."""

import bpy
from bpy.types import Panel, UIList, Menu

from .geometry_nodes import (
    fbp_active_effect_id,
    fbp_can_move_effect_selection,
    fbp_draw_effect_settings,
    fbp_draw_effect_mask_editor,
    fbp_effect_presence,
    fbp_effect_source_rig,
    fbp_schedule_effect_items_sync,
    fbp_selected_effect_ids,
)
from .effects_registry import (
    FBP_EFFECT_CLIPPING_MASK,
    FBP_EFFECT_SQUARE_MASK,
    FBP_EFFECT_CIRCLE_MASK,
    FBP_EFFECT_TRIANGLE_MASK,
    fbp_effect_definition,
    fbp_normalize_effect_id,
)


from .constants import fbp_collection_color_icon, fbp_strip_icon
from .path_utils import cached_file_exists, natural_sort_key
from .runtime import fbp_warn, FBP_DATA_ERRORS, FBP_DATA_IO_ERRORS
from .layers import (
    fbp_collection_icon,
    fbp_collection_plane_icon,
    fbp_collection_rows_are_disabled,
    fbp_collection_select_icon,
    fbp_color_plane_type_icon,
    fbp_layer_depth_value_from_cache,
    fbp_layer_row_type_icon,
    fbp_layer_backend_label,
    fbp_layer_backend_type,
    fbp_make_depth_context_cache,
    fbp_mask_icon,
    fbp_procedural_kind_for_item,
    fbp_procedural_kind_from_material,
    fbp_select_plane_icon,
    fbp_select_rig_icon,
    fbp_set_ui_units_x,
    get_layer_item_for_rig,
    get_primary_fbp_collection,
    get_selected_fbp_roots,
    get_selected_rigs,
    is_fbp_layer_object,
    is_layer_item_visible_in_collections,
    load_preview,
)
from .core import (
    draw_native_fbp_color_ramp,
    fbp_color_plane_can_have_frames,
    fbp_rig_native_sequence_needs_rename,
    fbp_sequence_index_at_frame,
    pending_collection_is_open,
)
from .ui_icons import ui_icon
from .drawing_plane import fbp_is_drawing_rig, draw_drawing_plane_ui
from .ui_layout import (
    draw_creation_ui,
    draw_layer_tree_uilist,
)


# SECTION 00B - Quick UI icon map #
# Change icons globally in constants.py > FBP_ICONS.
_FBP_CLIPPING_ENABLED_KEY = str(
    fbp_effect_definition(FBP_EFFECT_CLIPPING_MASK).get(
        'enabled_key', 'fbp_effect_clipping_mask'
    ) or 'fbp_effect_clipping_mask'
)
# The markers below identify the relevant UI locations.
# ###ICON Panel Layer Stack, Function Preview/Color Tag: preview.icon_id, fbp_strip_icon(rig.fbp_color_tag)
# ###ICON Panel Layer Stack, Function Solo: OUTLINER_OB_LIGHT / LIGHT
# ###ICON Panel Layer Stack, Function Select: CHECKBOX_HLT / CHECKBOX_DEHLT
# ###ICON Panel Layer Stack, Function Clipping Mask: plane type icon / TRACKING_REFINE_BACKWARDS
# ###ICON Panel Layer Stack, Function Holdout: fbp_mask_icon(...)
# ###ICON Panel Layer Stack, Function Visibility: HIDE_OFF / HIDE_ON
# ###ICON Panel Layer Stack, Function Lock: LOCKED / UNLOCKED
# ###ICON Panel Sequence, Function Current Frame: RECORD_ON
# ###ICON Panel Sequence, Function Normal Frame: DOT
# ###ICON Panel Sequence, Function Missing File: ERROR
# ###ICON Panel Sequence, Function Transparent Frame: TEXTURE_DATA
# ###ICON Panel Sequence, Function Import/Replace: FILE_FOLDER / FOLDER_REDIRECT
# ###ICON Panel Multiplane Setup, Function Collection: OUTLINER_COLLECTION
# ###ICON Panel Multiplane Setup, Function Collapse: RIGHTARROW / DOWNARROW_HLT
# ###ICON Panel Multiplane Setup, Function Add/Remove: ADD / REMOVE / TRASH
# ###ICON Panel Settings, Function Project Folder: FILE_FOLDER
# ###ICON Panel Settings, Function Import Project: IMPORT
# ###ICON Panel Settings, Function Build Direct: OUTLINER_COLLECTION
# ###ICON Panel Settings, Function Diagnostics: LINKED / ERROR / CHECKMARK / TIME
# ###ICON Panel Settings, Function Background Render: RENDER_ANIMATION
# ###ICON Panel Create, Function Color Plane: MATERIAL / IMAGE
# ###ICON Panel Create, Function Emission: LIGHT_SUN
# ###ICON Panel Create, Function Camera/Fit: RESTRICT_VIEW_ON / FULLSCREEN_ENTER
# ###ICON Menu Shift+A, Function Color Plane: IMAGE
# ###ICON Menu Shift+A, Function Gradient Plane: COLOR
# ###ICON Menu Shift+A, Function Holdout Plane: GHOST_DISABLED
# ###ICON Menu Shift+A, Function Image Plane: IMAGE_DATA
# ###ICON Menu Shift+A, Function Multiplane: RENDER_RESULT


def fbp_layer_backend_icon(rig):
    """Return one stable icon per plane backend for layer-list recognition."""
    backend = fbp_layer_backend_type(rig)
    return {
        'NATIVE_IMAGE': ui_icon('menu.image_plane'),
        'NATIVE_SEQUENCE': ui_icon('sequence.frames'),
        'NATIVE_MOVIE': 'FILE_MOVIE',
        'CUTOUT': ui_icon('menu.cutout_plane'),
        'PROCEDURAL_COLOR': ui_icon('menu.color_plane'),
        'PROCEDURAL_GRADIENT': ui_icon('menu.gradient_plane'),
        'PROCEDURAL_HOLDOUT': ui_icon('menu.holdout_plane'),
    }.get(backend, ui_icon('sequence.normal_frame'))
# ###ICON Menu Render, Function Background Render: RENDER_ANIMATION
#
# Main icon aliases live in ui_icons.py.



_FBP_SHAPE_MASK_EFFECTS = (
    FBP_EFFECT_SQUARE_MASK,
    FBP_EFFECT_CIRCLE_MASK,
    FBP_EFFECT_TRIANGLE_MASK,
)
_FBP_SHAPE_TO_EFFECT = {
    "SQUARE": FBP_EFFECT_SQUARE_MASK,
    "CIRCLE": FBP_EFFECT_CIRCLE_MASK,
    "TRIANGLE": FBP_EFFECT_TRIANGLE_MASK,
}


def _fbp_context_shape_mask_effect(context, rig, listed_effects, active_effect):
    """Return the Shape Mask whose controls should remain immediately visible.

    Selecting the helper should never require manually changing the Effects tab
    or finding the corresponding stack row. Selecting its plane also exposes
    controls automatically when that layer owns a single Shape Mask. The
    function uses the already-built effect list, so it does not rescan shader
    nodes during a UI redraw.
    """
    # ``listed_effects`` is already the synchronized stack mirror. Rechecking
    # each mask through material/modifier presence scans duplicated work during
    # every sidebar redraw and could temporarily disagree during Undo.
    available = tuple(
        effect_id for effect_id in listed_effects
        if effect_id in _FBP_SHAPE_MASK_EFFECTS
    )
    if not available:
        return ""

    active_obj = getattr(context, "active_object", None) if context else None
    selected_objects = tuple(getattr(context, "selected_objects", ()) or ()) if context else ()
    candidates = ([active_obj] if active_obj is not None else []) + [
        obj for obj in selected_objects if obj is not active_obj
    ]
    try:
        from .object_masks import (
            find_object_mask_owner,
            is_object_mask_helper,
            object_mask_contract,
        )
        for candidate in candidates:
            if not is_object_mask_helper(candidate):
                continue
            owner = find_object_mask_owner(candidate)
            contract = object_mask_contract(candidate) or {}
            effect_id = _FBP_SHAPE_TO_EFFECT.get(
                str(contract.get("shape", "") or "").upper(), ""
            )
            if owner is rig and effect_id in available:
                return effect_id
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    if active_effect in available:
        return active_effect
    # A plane can own more than one Shape Mask. Keep at least one set of
    # controls visible, choosing the first mask in the actual stack order; the
    # user can select another helper or stack row to change the context.
    return available[0]

def fbp_draw_procedural_frame_swatch(row, rig, index):
    """Draw a live per-frame procedural preview chip in the Frames UIList."""
    if not rig or not getattr(rig, 'fbp_is_color_plane', False):
        return
    try:
        item = rig.fbp_images[int(index)]
    except Exception:
        return
    try:
        chips = row.row(align=True)
        chips.alignment = 'LEFT'
        mat = None
        plane = getattr(rig, 'fbp_plane_target', None)
        if plane and getattr(plane, 'data', None) and 0 <= int(index) < len(plane.data.materials):
            mat = plane.data.materials[int(index)]
        kind = fbp_procedural_kind_from_material(mat, getattr(item, 'procedural_kind', 'SOLID')) if mat else str(getattr(item, 'procedural_kind', 'AUTO') or 'AUTO')
        if kind == 'AUTO':
            kind = fbp_procedural_kind_for_item(rig, index, 'SOLID')
        if kind == 'GRADIENT':
            chip_a = chips.row(align=False)
            fbp_set_ui_units_x(chip_a, 1.0)
            chip_a.prop(item, 'preview_color_a', text='')
            chip_b = chips.row(align=False)
            fbp_set_ui_units_x(chip_b, 1.0)
            chip_b.prop(item, 'preview_color_b', text='')
            return
        if kind == 'HOLDOUT':
            chips.label(text='', icon=ui_icon('menu.holdout_plane'))
            return
        chip = chips.row(align=False)
        fbp_set_ui_units_x(chip, 2.0)
        chip.prop(item, 'preview_color_a', text='')
    except FBP_DATA_IO_ERRORS:
        pass


def fbp_draw_layer_tag_and_preview(row, rig, context):
    """Draw a thumbnail when enabled; otherwise draw the layer Color Tag."""
    if not rig:
        return

    if bool(getattr(context.scene, 'fbp_show_previews', False)) and not bool(getattr(rig, 'fbp_is_color_plane', False)):
        try:
            _type_icon, preview_icon = fbp_layer_row_type_icon(rig, context)
            if preview_icon:
                row.label(text='', icon_value=preview_icon)
                return
        except FBP_DATA_IO_ERRORS:
            pass

    try:
        row.label(text='', icon=fbp_strip_icon(getattr(rig, 'fbp_color_tag', 'COLOR_09')))
    except Exception:
        row.label(text='', icon=ui_icon('layer.color_tag_fallback'))


# SECTION 01 - UIList: Layer Stack #
# ###ICON Panel Layer Stack, Functions: thumbnail, color tag, solo, select, holdout, visibility, lock.
class FBP_UL_LayerStack(UIList):
    def filter_items(self, context, data, propname):
        objs = getattr(data, propname)
        flt_flags = []
        flt_neworder = list(range(len(objs)))
        if getattr(context.scene, 'fbp_sort_layers_alpha', False):
            flt_neworder.sort(key=lambda i: natural_sort_key(getattr(getattr(objs[i], 'obj', None), 'name', '')))
        else:
            depth_ctx = fbp_make_depth_context_cache(context)
            depth_cache = {}
            name_cache = {}
            for i, item in enumerate(objs):
                rig = getattr(item, 'obj', None)
                name_cache[i] = getattr(rig, 'name', '') if rig else ''
                depth_cache[i] = fbp_layer_depth_value_from_cache(rig, depth_ctx)
            flt_neworder.sort(key=lambda i: (depth_cache.get(i, 0.0), natural_sort_key(name_cache.get(i, ''))), reverse=True)
        for item in objs:
            visible = is_layer_item_visible_in_collections(context, item)
            flt_flags.append(self.bitflag_filter_item if visible else 0)
        return flt_flags, flt_neworder

    def draw_item(self, context, layout, data, item, icon, _active_data, _active_propname, index):
        try:
            rig = item.obj
            if not rig or not is_fbp_layer_object(rig):
                layout.label(text="<Deleted Layer>")
                return

            row = layout.row(align=True)
            fbp_draw_layer_tag_and_preview(row, rig, context)

            op_name = row.operator("fbp.ui_list_name_action", text=rig.name, icon=fbp_layer_backend_icon(rig), emboss=False)
            op_name.target_type = 'LAYER'
            op_name.rig_name = rig.name
            op_name.index = index
            row.separator()
            row.label(text=f"F.{len(rig.fbp_images)}")

            solo_icon=ui_icon("layer.solo_on") if item.solo_view else ui_icon("layer.solo_off")
            row.prop(item, "solo_view", text="", icon=solo_icon, emboss=False)
            sel_icon=ui_icon("layer.select_on") if item.selected else ui_icon("layer.select_off")
            row.prop(item, "selected", text="", icon=sel_icon, emboss=False)
            hold_icon = fbp_mask_icon(item.holdout)
            op_hold = row.operator("fbp.toggle_layer_holdout", text="", icon=hold_icon, emboss=False)
            op_hold.rig_name = rig.name
            vis_icon=ui_icon("layer.visible_on") if rig.fbp_is_visible else ui_icon("layer.visible_off")
            row.prop(rig, "fbp_is_visible", text="", icon=vis_icon, icon_only=True, emboss=False)
            lock_icon=ui_icon("layer.lock_on") if item.rig_locked else ui_icon("layer.lock_off")
            row.prop(item, "rig_locked", text="", icon=lock_icon, emboss=False)

        except ReferenceError:
            layout.label(text="<Deleted Layer>")


class FBP_UL_LayerTreeList(UIList):
    """True Blender UIList tree for the Layers panel.

    Layer and collection names stay left-aligned; action icons sit in a fixed
    right-side strip. This gives a stable
    visual column for Solo/Holdout/Plane Lock/Lock/Select while keeping the eye
    as the first icon on every row. The plane-type icon doubles as the
    Clipping Mask control, so layer names keep one stable left alignment.
    """

    def draw_item(self, context, layout, data, item, icon, _active_data, _active_propname, index):
        if item is None:
            return

        row_type = getattr(item, 'row_type', 'LAYER')
        depth = max(0, min(10, int(getattr(item, 'depth', 0))))

        # Split the UIList row into a flexible left area and a fixed right
        # action strip. This is more stable than appending icons after the text,
        # because long layer names no longer push the buttons out of alignment.
        split = layout.split(factor=0.76, align=True)
        left = split.row(align=True)
        right = split.row(align=True)
        right.alignment = 'RIGHT'
        fbp_set_ui_units_x(right, 5.75)

        if row_type == 'GROUP':
            coll_name = getattr(item, 'collection_name', '') or getattr(item, 'name', '')
            coll = bpy.data.collections.get(coll_name)
            if not coll:
                left.label(text='', icon=ui_icon('layer.visible_off'))
                left.label(text=getattr(item, 'name', '') or 'Missing Collection', icon=ui_icon('generic.error'))
                return

            # Keep the eye in its own active layout. Setting ``left.active`` after
            # drawing it disabled the already-created button as well, so hidden
            # folders could no longer be made visible from the UIList.
            vis_icon = ui_icon('layer.visible_on') if getattr(coll, 'fbp_collection_visible', True) else ui_icon('layer.visible_off')
            eye = left.row(align=True)
            eye.prop(coll, 'fbp_collection_visible', text='', icon=vis_icon, icon_only=True, emboss=False)

            content = left.row(align=True)
            try:
                content.active = not fbp_collection_rows_are_disabled(coll, context)
            except FBP_DATA_IO_ERRORS:
                pass

            # Indentation stays after the eye, as requested.
            for _ in range(depth):
                content.label(text='', icon=ui_icon('generic.blank'))

            # ###ICON Panel Layer Stack UIList, Function Collection Collapse: setup.collapsed / setup.expanded
            fold_icon = ui_icon('setup.collapsed') if bool(getattr(coll, 'fbp_collapsed', False)) else ui_icon('setup.expanded')
            op = content.operator('fbp.toggle_collection_collapse', text='', icon=fold_icon, emboss=False)
            op.collection_name = coll.name

            content.alignment = 'LEFT'
            content.label(text='', icon=fbp_collection_icon(coll))
            op_sel = content.operator('fbp.ui_list_name_action', text=coll.name, emboss=False)
            op_sel.target_type = 'COLLECTION'
            op_sel.collection_name = coll.name
            op_sel.tree_index = index

            solo_icon = ui_icon('layer.solo_on') if getattr(coll, 'fbp_collection_solo', False) else ui_icon('layer.solo_off')
            right.prop(coll, 'fbp_collection_solo', text='', icon=solo_icon, icon_only=True, emboss=False)

            # Property buttons keep Blender hold-and-slide painting.
            right.prop(coll, 'fbp_collection_holdout', text='', icon=fbp_mask_icon(getattr(coll, 'fbp_collection_holdout', False)), icon_only=True, emboss=False)
            right.prop(coll, 'fbp_collection_plane_locked', text='', icon=fbp_collection_plane_icon(coll, context), icon_only=True, emboss=False)

            lock_icon = ui_icon('layer.lock_on') if getattr(coll, 'fbp_collection_locked', False) else ui_icon('layer.lock_off')
            right.prop(coll, 'fbp_collection_locked', text='', icon=lock_icon, icon_only=True, emboss=False)

            sel_row = right.row(align=True)
            sel_row.enabled = not getattr(coll, 'fbp_collection_locked', False)
            sel_row.prop(coll, 'fbp_collection_selected', text='', icon=fbp_collection_select_icon(coll, context), icon_only=True, emboss=False)
            return

        rig_name = getattr(item, 'rig_name', '') or getattr(item, 'name', '')
        rig = bpy.data.objects.get(rig_name) if rig_name else None
        layer_item = None

        # The virtual row already stores the source Scene.fbp_layers index.
        # Resolve it directly instead of linearly scanning the complete layer
        # collection once for every visible UIList row. The name lookup remains
        # the authority, while the index also keeps a renamed layer interactive
        # during the short interval before the scheduled tree rebuild.
        try:
            layer_index = int(getattr(item, 'layer_index', -1))
            scene_layers = context.scene.fbp_layers
            if 0 <= layer_index < len(scene_layers):
                indexed_item = scene_layers[layer_index]
                indexed_rig = getattr(indexed_item, 'obj', None)
                if rig is not None and indexed_rig == rig:
                    layer_item = indexed_item
                elif rig is None and indexed_rig and is_fbp_layer_object(indexed_rig):
                    rig = indexed_rig
                    layer_item = indexed_item
        except FBP_DATA_ERRORS:
            layer_item = None

        if rig is not None and layer_item is None:
            layer_item = get_layer_item_for_rig(context, rig)
        if not rig or not layer_item or not is_fbp_layer_object(rig):
            left.label(text='', icon=ui_icon('layer.visible_off'))
            left.label(text=getattr(item, 'name', '') or '<Deleted Layer>', icon=ui_icon('generic.error'))
            return

        # Keep visibility independently clickable even while the layer content is
        # visually disabled. This also fixes hidden rows that could not be restored.
        vis_icon = ui_icon('layer.visible_on') if getattr(rig, 'fbp_is_visible', True) else ui_icon('layer.visible_off')
        eye = left.row(align=True)
        eye.prop(rig, 'fbp_is_visible', text='', icon=vis_icon, icon_only=True, emboss=False)

        content = left.row(align=True)
        try:
            content_enabled = bool(getattr(rig, 'fbp_is_visible', True)) and not bool(layer_item.rig_locked)
        except FBP_DATA_IO_ERRORS:
            content_enabled = True

        for _ in range(depth):
            content.label(text='', icon=ui_icon('generic.blank'))

        # Placeholder aligns layers under the collection arrow column.
        content.label(text='', icon=ui_icon('generic.blank'))

        content.alignment = 'LEFT'
        preview_content = content.row(align=True)
        preview_content.active = content_enabled
        fbp_draw_layer_tag_and_preview(preview_content, rig, context)

        # The plane-type icon itself is the Clipping Mask button. When the
        # relationship is inactive it keeps the normal backend icon; when active
        # it changes to TRACKING_REFINE_BACKWARDS. This avoids adding a second
        # identity column and keeps the layer name aligned exactly as before.
        # Read the persistent enabled hint instead of traversing material nodes
        # during each UIList redraw. Repair paths still validate the shader graph
        # when the operator is invoked.
        try:
            clipping_active = bool(rig.get(_FBP_CLIPPING_ENABLED_KEY, False))
        except FBP_DATA_ERRORS:
            clipping_active = False
        clipping = content.operator(
            'fbp.toggle_clipping_mask',
            text='',
            icon=(
                'TRACKING_REFINE_BACKWARDS'
                if clipping_active
                else fbp_layer_backend_icon(rig)
            ),
            emboss=False,
        )
        clipping.rig_name = rig.name

        name_content = content.row(align=True)
        name_content.active = content_enabled
        name_content.alignment = 'LEFT'
        op_name = name_content.operator('fbp.ui_list_name_action', text=rig.name, emboss=False)
        op_name.target_type = 'LAYER'
        op_name.rig_name = rig.name
        op_name.tree_index = index

        solo_icon = ui_icon('layer.solo_on') if layer_item.solo_view else ui_icon('layer.solo_off')
        right.prop(layer_item, 'solo_view', text='', icon=solo_icon, icon_only=True, emboss=False)

        # Holdout remains a paintable property. Plane selectability uses an
        # operator because unlocking a plane should also make it the active
        # viewport object and remove the rig from the selection.
        right.prop(layer_item, 'holdout', text='', icon=fbp_mask_icon(layer_item.holdout), icon_only=True, emboss=False)
        op_plane = right.operator(
            'fbp.select_linked_plane',
            text='',
            icon=fbp_select_plane_icon(rig, context),
            emboss=False,
        )
        op_plane.rig_name = rig.name

        lock_icon = ui_icon('layer.lock_on') if layer_item.rig_locked else ui_icon('layer.lock_off')
        right.prop(layer_item, 'rig_locked', text='', icon=lock_icon, icon_only=True, emboss=False)

        sel_row = right.row(align=True)
        sel_row.enabled = not layer_item.rig_locked
        sel_row.prop(layer_item, 'selected', text='', icon=fbp_select_rig_icon(layer_item.rig_locked, rig.select_get()), icon_only=True, emboss=False)


# SECTION 02 - UIList: Frames / Images #
# ###ICON Panel Sequence, Functions: current frame, empty frame, missing file, image preview.
class FBP_UL_ImageList(UIList):
    def draw_item(self, context, layout, data, item, icon, _active_data, _active_propname, index):
        rig = data
        is_empty = bool(getattr(item, "is_empty", False))
        is_missing = False
        try:
            current_index = fbp_sequence_index_at_frame(rig, getattr(context.scene, 'frame_current', None))
        except Exception:
            current_index = getattr(rig, 'fbp_images_index', -1)
        is_active = index == current_index
        is_color_plane = bool(getattr(rig, "fbp_is_color_plane", False))

        custom_icon = ui_icon("menu.image_plane")
        if is_empty:
            custom_icon = ui_icon("sequence.empty_frame")
        elif is_color_plane:
            custom_icon = fbp_color_plane_type_icon(rig) or ui_icon("sequence.empty_frame")
        else:
            try:
                img_path = getattr(item, "filepath", "") or ""
                if img_path and not cached_file_exists(bpy.path.abspath(img_path)):
                    is_missing = True
                if img_path and context.scene.fbp_show_previews:
                    thumb = load_preview(img_path, scene=context.scene)
                    if thumb:
                        custom_icon = thumb.icon_id
            except FBP_DATA_IO_ERRORS:
                pass

        row = layout.row(align=True)
        split = row.split(factor=0.70)
        left = split.row(align=True)

        # Single DOT/REC only. This is the clickable active-frame target and
        # avoids the previous double-DOT row in the frame UIList.
        op = left.operator(
            "fbp.select_image_exclusive",
            text="",
            icon=ui_icon("sequence.current_frame") if is_active else ui_icon("sequence.normal_frame"),
            emboss=False,
        )
        op.rig_name = rig.name
        op.index = index

        if is_missing:
            left.label(text="", icon=ui_icon("generic.error"))

        show_proc_preview = bool(
            getattr(context.scene, 'fbp_show_color_previews', False)
            and is_color_plane
            and not is_empty
        )

        if show_proc_preview:
            # Procedural frame previews live in the Frames UIList: DOT/REC first,
            # then color/gradient chips.
            fbp_draw_procedural_frame_swatch(left, rig, index)
        elif is_empty:
            left.label(text="", icon=ui_icon("sequence.empty_frame"))
        else:
            if isinstance(custom_icon, int):
                left.label(text='', icon_value=custom_icon)
            else:
                left.label(text='', icon=custom_icon)

        display_name = item.name if not is_empty else "Transparent Frame"
        name_op = left.operator(
            "fbp.ui_list_name_action",
            text=f"{index + 1} - ({display_name})" if is_empty else f"{index + 1} - {display_name}",
            emboss=False,
        )
        name_op.target_type = 'FRAME'
        name_op.rig_name = rig.name
        name_op.index = index

        right = split.row(align=False)
        compact = right.row(align=False)
        compact.prop(item, "duration", text="")
        right.prop(item, "is_selected", text="")


# SECTION 03 - UIList: Multiplane Setup #
# ###ICON Panel Multiplane Setup, Functions: collection, folder, remove, file count.
class FBP_UL_PendingList(UIList):
    """Scrollable preview list for the Multiplane Setup import."""

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        flags = [self.bitflag_filter_item] * len(items)
        order = list(range(len(items)))
        if getattr(context.scene, 'fbp_sort_layers_alpha', False):
            order.sort(key=lambda i: natural_sort_key(getattr(items[i], 'collection_name', '') + ' / ' + getattr(items[i], 'name', '')))
        return flags, order

    def _collection_parts(self, item):
        raw = (getattr(item, 'collection_name', '') or '').strip()
        if not raw:
            return []
        return [part.strip() for part in raw.split('/') if part.strip()]

    def _file_count(self, item):
        try:
            return len([f for f in str(getattr(item, 'files_str', '') or '').split('|') if f])
        except Exception:
            return 0

    def _row_icon(self, context, item, file_count, parts):
        # ###ICON Panel Multiplane Setup, Function Folder/Collection: setup.folder
        # ###ICON Panel Multiplane Setup, Function Sequence: setup.sequence
        # ###ICON Panel Multiplane Setup, Function Static Image: setup.image
        if parts:
            return ui_icon('setup.folder')
        return ui_icon('setup.sequence') if file_count > 1 else ui_icon('setup.image')

    def draw_item(self, context, layout, data, item, icon, _active_data, _active_propname, index):
        if item is None:
            return

        parts = self._collection_parts(item)
        depth = min(8, len(parts))
        file_count = self._file_count(item)
        row_icon = self._row_icon(context, item, file_count, parts)
        is_sequence = file_count > 1

        row = layout.row(align=True)

        # BLANK1 indentation before icon + text, based on folder/scene depth.
        for _ in range(depth):
            row.label(text='', icon=ui_icon('generic.blank'))

        # Tiny color marker, then editable layer name.
        row.prop(item, 'fbp_color_tag', text='', icon_only=True)
        if parts:
            row.label(text=f"{parts[-1]} /", icon=row_icon)
        name_op = row.operator('fbp.ui_list_name_action', text=item.name, icon=row_icon if not parts else 'NONE', emboss=False)
        name_op.target_type = 'PENDING'
        name_op.index = index

        if is_sequence:
            row.label(text=f"F {file_count}")
        elif file_count == 1:
            row.label(text="F 1")
        else:
            row.label(text="empty", icon=ui_icon('generic.error'))

        edit = row.operator('fbp.edit_pending_plane', text='', icon=ui_icon('setup.edit'), emboss=False)
        edit.index = index


class FBP_UL_PendingTreeList(UIList):
    """True Blender UIList used as a collapsible tree for Multiplane Setup.

    Rows are virtual display items rebuilt from Scene.fbp_pending_planes.
    Group rows use TRIA_RIGHT / TRIA_DOWN; layer rows keep edit/remove controls.
    """

    def draw_item(self, context, layout, data, item, icon, _active_data, _active_propname, index):
        if item is None:
            return

        scene = context.scene
        depth = max(0, min(10, int(getattr(item, 'depth', 0))))

        row_type = getattr(item, 'row_type', 'LAYER')

        # Collection rows keep their native full-width row. Layer indentation is
        # drawn later inside the flexible content side of the split.
        if row_type == 'GROUP':
            row = layout.row(align=True)
            row.alignment = 'LEFT'
            for _ in range(depth):
                row.label(text='', icon=ui_icon('generic.blank'))
            path = getattr(item, 'collection_path', '') or getattr(item, 'name', '') or 'Unsorted'
            is_open = pending_collection_is_open(scene, path)

            # ###ICON Panel Multiplane Setup UIList, Function Collapse/Open: setup.collapsed / setup.expanded
            fold_icon = ui_icon('setup.expanded') if is_open else ui_icon('setup.collapsed')
            op = row.operator('fbp.toggle_pending_collection_collapse', text='', icon=fold_icon, emboss=False)
            op.collection_name = path

            # Real leaf collections expose the same editable colored collection
            # selector used by Blender's Outliner.
            has_children = int(getattr(item, 'child_count', 0)) > 0
            color_editable = bool(getattr(item, 'collection_color_editable', True))
            if has_children or not color_editable:
                row.label(text='', icon=fbp_collection_color_icon('NONE'))
            else:
                row.prop(item, 'collection_color_tag', text='', icon_only=True)

            name_op = row.operator('fbp.ui_list_name_action', text=getattr(item, 'name', '') or 'Unsorted', icon='NONE', emboss=False)
            name_op.target_type = 'PENDING_GROUP'
            name_op.collection_name = path
            name_op.tree_index = index
            return

        # Layer row. The virtual row points back to the real pending setup item.
        pending_index = int(getattr(item, 'pending_index', -1))
        pending = None
        try:
            if 0 <= pending_index < len(scene.fbp_pending_planes):
                pending = scene.fbp_pending_planes[pending_index]
        except Exception:
            pending = None

        file_count = int(getattr(item, 'file_count', 0))
        layer_icon = ui_icon('setup.animated') if file_count > 1 else ui_icon('setup.image')

        # Match the Layer List structure exactly: the UIList-provided layout
        # is split directly into a flexible left side and a right-aligned action
        # strip. Avoiding a nested row and a fixed width on the whole action
        # container removes the extra gutter previously visible after Trash.
        split = layout.split(factor=0.70, align=True)
        content = split.row(align=True)
        content.alignment = 'LEFT'
        actions = split.row(align=True)
        actions.alignment = 'RIGHT'

        for _ in range(depth):
            content.label(text='', icon=ui_icon('generic.blank'))

        # Keep the grip visible even when this row cannot move. This preserves a
        # stable visual column while clearly communicating the disabled state.
        drag_row = content.row(align=True)
        drag_row.enabled = bool(
            pending is not None
            and (getattr(item, 'can_move_up', False) or getattr(item, 'can_move_down', False))
        )
        drag = drag_row.operator(
            'fbp.drag_pending_plane',
            text='',
            icon='GRIP',
            emboss=False,
        )
        drag.index = pending_index

        if pending is not None:
            content.prop(pending, 'fbp_color_tag', text='', icon_only=True)
            name_row = content.row(align=True)
            name_row.alignment = 'LEFT'
            name_op = name_row.operator(
                'fbp.ui_list_name_action',
                text=pending.name,
                icon=layer_icon,
                emboss=False,
            )
            name_op.target_type = 'PENDING'
            name_op.index = pending_index
            name_op.tree_index = index
        else:
            content.label(
                text=getattr(item, 'name', '') or 'Missing Layer',
                icon=ui_icon('generic.error'),
            )

        if file_count > 1:
            actions.label(text=f'F {file_count}')
            reverse_sequence = actions.operator(
                'fbp.reverse_pending_sequence',
                text='',
                icon=ui_icon('sequence.reverse'),
                emboss=False,
            )
            reverse_sequence.index = pending_index
        elif file_count == 1:
            actions.label(text='F 1')
        else:
            actions.label(text='', icon=ui_icon('generic.error'))

        if pending is not None:
            actions.prop(
                pending,
                'is_selected',
                text='',
                icon='CHECKBOX_HLT' if bool(getattr(pending, 'is_selected', False)) else 'CHECKBOX_DEHLT',
                icon_only=True,
                emboss=False,
            )

        edit = actions.operator(
            'fbp.edit_pending_plane',
            text='',
            icon=ui_icon('setup.edit'),
            emboss=False,
        )
        edit.index = pending_index


        remove = actions.operator(
            'fbp.remove_pending_plane_at_index',
            text='',
            icon=ui_icon('generic.delete'),
            emboss=False,
        )
        remove.index = pending_index

# SECTION 04 - Helper UI: Pending Setup and Tree View #
# Layout helper lives in ui_layout.py.
# ###ICON Tree View, Functions: collection collapse, visibility, solo, holdout, select rigs/planes, lock.

# SECTION 05 - Panel: Settings / Project / Camera / Render / Maintenance #
# Every tab deliberately draws four content rows. The panel therefore stays
# visually stable while switching sections and does not scan project data.


def _fbp_settings_row(layout, *, align=False):
    row = layout.row(align=align)
    row.scale_y = 1.0
    return row


class FBP_PT_Settings(Panel):
    bl_label = "Settings"
    bl_description = "Current project, display, camera, render and maintenance settings"
    bl_idname = "FBP_PT_settings"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Frame by Plane"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 0

    def draw_header(self, context):
        self.layout.label(text="", icon=ui_icon("settings.header"))

    def draw(self, context):
        layout = self.layout
        sc = context.scene

        tabs = layout.grid_flow(row_major=True, columns=3, even_columns=True, even_rows=True, align=True)
        tabs.prop_enum(sc, "fbp_settings_section", 'PROJECT', text="Project", icon=ui_icon("settings.project"))
        tabs.prop_enum(sc, "fbp_settings_section", 'DISPLAY', text="Display", icon=ui_icon("settings.display"))
        tabs.prop_enum(sc, "fbp_settings_section", 'CAMERA', text="Camera", icon=ui_icon("settings.camera_tab"))
        tabs.prop_enum(sc, "fbp_settings_section", 'RENDER', text="Render", icon=ui_icon("settings.render_tab"))
        tabs.prop_enum(sc, "fbp_settings_section", 'MAINTENANCE', text="Tools", icon=ui_icon("settings.repair"))

        layout.separator()
        content = layout.box()
        section = getattr(sc, 'fbp_settings_section', 'PROJECT')

        if section == 'PROJECT':
            row = _fbp_settings_row(content)
            row.label(text="", icon=ui_icon("settings.project_folder"))
            row.prop(sc, "fbp_project_path", text="Project Folder")

            row = _fbp_settings_row(content)
            row.label(text="", icon='FILE_FOLDER')
            row.prop(sc, "fbp_last_directory", text="Import Folder")

            row = _fbp_settings_row(content, align=True)
            row.operator("fbp.save_file", text="Save", icon=ui_icon("settings.save"))
            row.operator("fbp.scan_project_to_setup", text="Import Project", icon='IMPORT')
            row.operator("fbp.import_folder_hierarchy", text="Import Folder", icon='OUTLINER_COLLECTION')

            row = _fbp_settings_row(content)
            row.prop(sc, "fbp_show_project_tools", text="Import Tools", icon='TOOL_SETTINGS')
            row.operator("fbp.apply_preferences_to_scene", text="Apply Defaults", icon='CHECKMARK')

        elif section == 'DISPLAY':
            row = _fbp_settings_row(content)
            row.prop(sc, "fbp_show_previews", text="List Thumbnails", icon='IMAGE_DATA')
            row.prop(sc, "fbp_show_color_previews", text="Color Previews", icon='COLOR')

            row = _fbp_settings_row(content)
            row.prop(sc, "fbp_thumbnail_background_enabled", text="Thumbnail BG", icon='IMAGE_BACKGROUND')
            color = row.row(align=True)
            color.enabled = bool(sc.fbp_thumbnail_background_enabled)
            color.prop(sc, "fbp_thumbnail_background_color", text="")

            row = _fbp_settings_row(content)
            row.prop(sc, "fbp_sort_layers_alpha", text="Alphabetical", icon=ui_icon("layer.sort_alpha"))
            row.prop(sc, "fbp_auto_collection_color_variants", text="Color Variants", icon='OUTLINER_COLLECTION')

            row = _fbp_settings_row(content)
            row.prop(sc, "fbp_show_create_tools", text="Create Tools", icon='TOOL_SETTINGS')
            row.operator("fbp.sync_collection_colors", text="Sync", icon='COLOR')
            row.operator("fbp.apply_preferences_to_scene", text="Defaults", icon='CHECKMARK')

        elif section == 'CAMERA':
            row = _fbp_settings_row(content)
            row.prop(sc, "fbp_camera_projection", text="Projection", icon=ui_icon("settings.projection"))
            if sc.fbp_camera_projection == 'ORTHO':
                row.prop(sc, "fbp_camera_ortho_scale", text="Scale", icon='VIEW_CAMERA_UNSELECTED')
            else:
                row.prop(sc, "fbp_camera_lens", text="Lens", icon='CAMERA_DATA')

            row = _fbp_settings_row(content)
            row.prop(sc, "fbp_cam_ratio", text="Aspect", icon=ui_icon("settings.camera_frame"))
            resolution = row.row(align=True)
            resolution.active = sc.fbp_cam_ratio == 'CUSTOM'
            resolution.prop(sc.render, "resolution_x", text="X")
            resolution.prop(sc.render, "resolution_y", text="Y")

            row = _fbp_settings_row(content, align=True)
            row.prop(sc, "fbp_camera_clip_start", text="Clip Start")
            row.prop(sc, "fbp_camera_clip_end", text="Clip End")

            row = _fbp_settings_row(content, align=True)
            row.prop(sc, "fbp_gen_camera", text="Generate", toggle=True, icon='CAMERA_DATA')
            row.prop(sc, "fbp_cam_pivot", text="Cursor", toggle=True, icon='PIVOT_CURSOR')
            row.prop(sc, "fbp_auto_scale", text="Fit", toggle=True, icon='FULLSCREEN_ENTER')

        elif section == 'RENDER':
            row = _fbp_settings_row(content)
            row.label(text="", icon=ui_icon("settings.output"))
            row.prop(sc, "fbp_render_output_dir", text="Output Folder")

            row = _fbp_settings_row(content)
            row.prop(sc, "fbp_alpha_render_method", text="Alpha", icon='IMAGE_ALPHA')

            row = _fbp_settings_row(content)
            row.prop(sc, "fbp_render_prefix", text="Prefix", icon=ui_icon("layer.sort_alpha"))
            row.prop(sc, "frame_start", text="In")
            row.prop(sc, "frame_end", text="Out")

            row = _fbp_settings_row(content, align=True)
            row.operator("fbp.repair_render_state", icon=ui_icon("settings.repair"), text="Check State")
            if getattr(sc, 'fbp_background_render_running', False):
                row.operator("fbp.stop_background_render", icon='CANCEL', text="Stop")
            else:
                row.operator("fbp.background_render_frames", icon=ui_icon("settings.render_sequence"), text="Render Sequence")

            row = _fbp_settings_row(content)
            row.operator("fbp.save_file", text="Save Before Render", icon=ui_icon("settings.save"))

        else:
            row = _fbp_settings_row(content)
            row.prop(sc, "fbp_auto_clean_orphans", text="Auto-clean Orphans", icon='MODIFIER')
            row.operator("fbp.relink_from_project_root", icon=ui_icon("settings.relink"), text="Relink")
            row.operator("fbp.select_missing_layers", icon=ui_icon("generic.error"), text="Missing")

            row = _fbp_settings_row(content, align=True)
            row.operator("fbp.project_health_check", icon=ui_icon("settings.health"), text="Health")
            row.operator("fbp.deep_addon_audit", icon='CHECKMARK', text="Audit")
            repair = row.operator("fbp.deep_addon_audit", icon=ui_icon("settings.repair"), text="Repair")
            repair.repair = True

            row = _fbp_settings_row(content, align=True)
            row.operator("fbp.run_lifecycle_audit", icon='RECOVER_LAST', text="Lifecycle")
            row.operator("fbp.profile_effects", icon='TIME', text="Profiler")
            row.operator("fbp.run_native_backend_regression", icon='FILE_REFRESH', text="Native Test")

            row = _fbp_settings_row(content)
            row.operator("fbp.run_lts_release_gate", icon='CHECKMARK', text="LTS Release Gate")

            row = _fbp_settings_row(content, align=True)
            row.operator("fbp.create_native_regression_scene", icon='IMAGE_DATA', text="Native Scene")
            row.operator("fbp.create_effect_regression_scene", icon='SCENE_DATA', text="Effects Scene")

            row = _fbp_settings_row(content)
            row.operator("fbp.apply_preferences_to_scene", icon='CHECKMARK', text="Apply Defaults")


def fbp_scene_has_cached_rigs(context):
    """Use the synchronized layer cache instead of scanning Scene objects in UI polls."""
    scene = getattr(context, "scene", None) if context else None
    if not scene:
        return False
    try:
        for item in getattr(scene, "fbp_layers", ()) or ():
            rig = getattr(item, "obj", None)
            if rig and is_fbp_layer_object(rig):
                return True
    except FBP_DATA_ERRORS:
        pass
    try:
        active = getattr(context, "active_object", None)
        return bool(active and is_fbp_layer_object(active))
    except FBP_DATA_ERRORS:
        return False


# SECTION 06 - Panel: Layer Stack #
# ###ICON Panel Layer Stack, Functions: sort, add, color plane, duplicate, delete, select all.
class FBP_PT_LayerStack(Panel):
    bl_label       = "Layers"
    bl_description = "Manage Frame by Plane layers, collections, visibility, holdout masks and selection"
    bl_idname      = "FBP_PT_layer_stack"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "Frame by Plane"
    bl_order       = 1

    @classmethod
    def poll(cls, context):
        return fbp_scene_has_cached_rigs(context)

    def draw_header(self, context):
        self.layout.label(text="", icon=ui_icon("layer.header"))

    def draw(self, context):
        layout = self.layout
        sc = context.scene
        selected_rigs = get_selected_rigs(context)

        active_tree_is_layer = False
        try:
            tree_index = int(getattr(sc, "fbp_layer_tree_rows_idx", -1))
            rows = getattr(sc, "fbp_layer_tree_rows", ())
            active_tree_is_layer = bool(
                0 <= tree_index < len(rows)
                and str(getattr(rows[tree_index], "row_type", "")) == "LAYER"
            )
        except FBP_DATA_ERRORS:
            active_tree_is_layer = False

        row = layout.row(align=False)
        box = row.box()
        draw_layer_tree_uilist(box, context, min_rows=8)
        col = row.column(align=True)
        fbp_set_ui_units_x(col, 1.15)

        # Alphabetical order is the primary list-level action, followed by the
        # thumbnail visibility toggle.  The eye icons communicate the current
        # state directly instead of using a generic image datablock icon.
        col.prop(sc, "fbp_sort_layers_alpha", text="", toggle=True, icon=ui_icon("layer.sort_alpha"))
        thumbnail_icon = 'RESTRICT_VIEW_OFF' if bool(getattr(sc, "fbp_show_previews", False)) else 'RESTRICT_VIEW_ON'
        col.prop(sc, "fbp_show_previews", text="", toggle=True, icon=thumbnail_icon)
        col.separator()
        can_move_layer = bool(
            len(selected_rigs) == 1
            or (active_tree_is_layer and not selected_rigs)
        )
        move = col.row(align=True)
        move.enabled = can_move_layer
        move.operator("fbp.move_layer_stack", text="", icon=ui_icon("generic.up")).direction = 'UP'
        move = col.row(align=True)
        move.enabled = can_move_layer
        move.operator("fbp.move_layer_stack", text="", icon=ui_icon("generic.down")).direction = 'DOWN'
        selected_by_collection = {}
        reverse_available = False
        for rig in selected_rigs:
            collection = get_primary_fbp_collection(rig)
            if collection is None:
                continue
            try:
                key = int(collection.as_pointer())
            except FBP_DATA_ERRORS:
                continue
            selected_by_collection[key] = selected_by_collection.get(key, 0) + 1
            if selected_by_collection[key] >= 2:
                reverse_available = True
                break
        reverse_order = col.row(align=True)
        reverse_order.enabled = reverse_available
        reverse_order.operator(
            "fbp.reverse_selected_layer_order",
            text="",
            icon=ui_icon("sequence.reverse"),
        )
        col.separator()
        duplicate = col.row(align=True)
        duplicate.enabled = bool(selected_rigs)
        duplicate.operator("fbp.duplicate_selected_layers", text="", icon=ui_icon("layer.duplicate"))
        delete = col.row(align=True)
        delete.enabled = bool(selected_rigs)
        delete.operator("fbp.delete_sequence", text="", icon=ui_icon("generic.delete"))


def draw_effects_ui(layout, context):
    """Draw Image, Mask and Mesh stacks without replacing the main controls.

    Shape Mask helpers expose contextual settings, but those settings are
    deliberately drawn *after* the normal stack. This keeps the category tabs,
    effect list and side toolbar visible at all times.
    """
    selected_rigs = get_selected_rigs(context)
    if not selected_rigs:
        return

    sc = context.scene
    rig = selected_rigs[0]
    listed_effects = fbp_schedule_effect_items_sync(rig, selected_rigs)
    effect_definitions = {
        effect_id: (fbp_effect_definition(effect_id) or {})
        for effect_id in listed_effects
    }
    active_effect = fbp_active_effect_id(rig) if listed_effects else ""
    active_definition = effect_definitions.get(active_effect, {}) if active_effect else {}
    presence_cache = {}

    def effect_presence(effect_id):
        effect_id = str(effect_id or "")
        if not effect_id:
            return (0, len(selected_rigs))
        cached = presence_cache.get(effect_id)
        if cached is None:
            cached = fbp_effect_presence(selected_rigs, effect_id)
            presence_cache[effect_id] = cached
        return cached

    present_count, selected_count = effect_presence(active_effect)
    contextual_shape_effect = _fbp_context_shape_mask_effect(
        context, rig, listed_effects, active_effect
    )

    # Category controls always remain the first visible row. Previously the
    # contextual Shape Mask box could push or replace the normal stack, making
    # the Effects panel appear to disappear.
    switch = layout.row(align=True)
    switch.scale_y = 1.1
    switch.prop_enum(sc, "fbp_effects_view", '2D', text="Image", icon="NODE_TEXTURE")
    switch.prop_enum(sc, "fbp_effects_view", 'MASK', text="Masks", icon="IMAGE_ALPHA")
    switch.prop_enum(sc, "fbp_effects_view", '3D', text="Mesh", icon="MODIFIER")

    effects_view = str(getattr(sc, "fbp_effects_view", "2D") or "2D")
    visible_categories = (
        {"3D"} if effects_view == "3D"
        else ({"MASK"} if effects_view == "MASK" else {"BASE", "2D"})
    )
    if active_effect and str(active_definition.get("category", "2D") or "2D") not in visible_categories:
        active_effect = ""
        active_definition = {}
        present_count, selected_count = (0, len(selected_rigs))

    visible_effects = [
        effect_id for effect_id in listed_effects
        if str(effect_definitions.get(effect_id, {}).get("category", "2D") or "2D")
        in visible_categories
    ]

    if visible_effects:
        list_type = (
            "FBP_UL_EffectStack3D" if effects_view == "3D"
            else ("FBP_UL_EffectStackMask" if effects_view == "MASK" else "FBP_UL_EffectStack2D")
        )
        list_id = "MESH" if effects_view == "3D" else ("MASK" if effects_view == "MASK" else "IMAGE")
        stack_row = layout.row(align=False)
        stack_row.template_list(
            list_type, list_id,
            rig, "fbp_effects",
            rig, "fbp_effects_index",
            rows=8,
        )

        selected_effect_ids = fbp_selected_effect_ids(
            rig, fallback_active=True, movable_only=True, categories=visible_categories
        )
        shared_selection = bool(
            selected_effect_ids
            and all(
                effect_presence(effect_id)[0] == selected_count
                for effect_id in selected_effect_ids
            )
        )
        controls = stack_row.column(align=True)
        fbp_set_ui_units_x(controls, 1.25)

        for direction, icon_name in (
            ("TOP", "generic.top"),
            ("UP", "generic.up"),
            ("DOWN", "generic.down"),
            ("BOTTOM", "generic.bottom"),
        ):
            move = controls.row(align=True)
            move.enabled = bool(
                shared_selection
                and fbp_can_move_effect_selection(
                    selected_rigs, selected_effect_ids, direction
                )
            )
            op = move.operator(
                "fbp.move_active_effect", text="", icon=ui_icon(icon_name)
            )
            op.direction = direction

        controls.separator()
        add = controls.operator(
            "fbp.open_effect_toolbar_menu", text="", icon=ui_icon("generic.add")
        )
        add.menu = "ADD"

        controls.separator()
        controls.operator(
            "fbp.create_effect_group", text="", icon="COLLECTION_NEW"
        )

        controls.separator()
        actions = controls.operator(
            "fbp.open_effect_toolbar_menu", text="", icon="DOWNARROW_HLT"
        )
        actions.menu = "ACTIONS"

        if active_effect:
            source_rig = fbp_effect_source_rig(selected_rigs, active_effect)
            if source_rig:
                fbp_draw_effect_settings(
                    layout, source_rig, active_effect,
                    selected_count=selected_count,
                    present_count=present_count,
                )
    else:
        empty = layout.box()
        label = (
            "No Mesh Effects" if effects_view == "3D"
            else ("No Masks" if effects_view == "MASK" else "No Image Effects")
        )
        empty.label(text=label, icon="INFO")
        empty.menu("FBP_MT_add_effect", text="Add Effect", icon=ui_icon("generic.add"))

    mask_edit_target = fbp_normalize_effect_id(
        getattr(sc, "fbp_effect_mask_edit_target", "") or ""
    )
    if effects_view == "2D" and mask_edit_target:
        if mask_edit_target in visible_effects:
            layout.separator()
            if not fbp_draw_effect_mask_editor(
                layout, context, selected_rigs, mask_edit_target
            ):
                try:
                    sc.fbp_effect_mask_edit_target = ""
                except FBP_DATA_ERRORS:
                    pass
        else:
            try:
                sc.fbp_effect_mask_edit_target = ""
            except FBP_DATA_ERRORS:
                pass

    # Keep the selected Shape Mask immediately editable without ever replacing
    # the regular Effects stack. When it is already the active row in Masks,
    # its settings were drawn above and are not duplicated.
    if contextual_shape_effect and not (
        effects_view == "MASK" and active_effect == contextual_shape_effect
    ):
        contextual_source = fbp_effect_source_rig(
            selected_rigs, contextual_shape_effect
        ) or rig
        contextual_present, contextual_selected = effect_presence(
            contextual_shape_effect
        )
        layout.separator()
        context_header = layout.row(align=False)
        context_header.label(text="Selected Shape Mask", icon="MOD_MASK")
        show = context_header.operator(
            "fbp.select_effect",
            text="Show in Masks",
            icon="IMAGE_ALPHA",
        )
        show.effect_id = contextual_shape_effect
        fbp_draw_effect_settings(
            layout, contextual_source, contextual_shape_effect,
            selected_count=contextual_selected,
            present_count=contextual_present,
        )


# SECTION 07 - Panel: Sequence / Selected Layer #
# ###ICON Panel Sequence, Functions: replace, visibility, emission, fit, transform and frames.
class FBP_PT_Sequence(Panel):
    bl_label       = "Sequence"
    bl_description = "Edit the selected Frame by Plane layer, timing, frames, color, transform and tools"
    bl_idname      = "FBP_PT_sequence"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "Frame by Plane"
    bl_order       = 2

    @classmethod
    def poll(cls, context):
        return bool(get_selected_rigs(context))

    def draw_header(self, context):
        self.layout.label(text="", icon=ui_icon("sequence.header"))

    def draw(self, context):
        layout = self.layout
        selected_rigs = get_selected_rigs(context)
        if not selected_rigs:
            return

        rig = selected_rigs[0]
        backend_type = fbp_layer_backend_type(rig)
        backend_types = {fbp_layer_backend_type(item) for item in selected_rigs}
        mixed_backends = len(backend_types) > 1
        is_native_backend = backend_type in {'NATIVE_IMAGE', 'NATIVE_SEQUENCE', 'NATIVE_MOVIE'}
        is_movie = backend_type == 'NATIVE_MOVIE'
        is_static_image = backend_type == 'NATIVE_IMAGE'
        if mixed_backends or len(selected_rigs) > 1:
            backend_row = layout.row(align=False)
            if mixed_backends:
                backend_row.label(text="Mixed Layer Types", icon="INFO")
            if len(selected_rigs) > 1:
                backend_row.label(text=f"{len(selected_rigs)} Selected", icon="RESTRICT_SELECT_OFF")

        if not mixed_backends and fbp_is_drawing_rig(rig):
            draw_drawing_plane_ui(layout, context, rig)
            return

        box = layout.box()

        row = box.row(align=False)
        row.prop(rig, "fbp_color_tag", text="", icon_only=False)
        if len(selected_rigs) == 1:
            row.prop(rig, "fbp_layer_name", text="", icon=ui_icon("sequence.header"))
        else:
            row.label(text=f"Primary: {rig.name}", icon=ui_icon("sequence.header"))
        if is_native_backend and not mixed_backends:
            row.operator("fbp.replace_sequence", text="", icon=ui_icon("setup.edit"))

        row = box.row(align=False)
        vis_icon=ui_icon("layer.visible_on") if rig.fbp_is_visible else ui_icon("layer.visible_off")
        row.prop(rig, "fbp_is_visible", text="", icon=vis_icon)
        is_holdout_plane = bool(
            not mixed_backends
            and getattr(rig, "fbp_is_color_plane", False)
            and getattr(rig, "fbp_color_plane_mode", 'SOLID') == 'HOLDOUT'
        )
        if not is_holdout_plane:
            row.prop(rig, "fbp_opacity", text="Opacity", slider=True)
            if not mixed_backends:
                emiss_icon=ui_icon("sequence.emission")
                if getattr(rig, "fbp_is_color_plane", False):
                    row.prop(rig, "fbp_color_plane_emission", text="", icon=emiss_icon, toggle=True)
                else:
                    row.prop(rig, "fbp_use_emission", text="", icon=emiss_icon, toggle=True)

        row = box.row(align=False)
        if len(selected_rigs) > 1:
            row.operator("fbp.multi_fit_camera", text="Fit", icon=ui_icon("sequence.fit"))
        else:
            row.operator("fbp.fit_camera", icon=ui_icon("sequence.fit"), text="Fit")
        row.operator("fbp.popup_transform", text="Transform", icon=ui_icon("sequence.transform"))

        if mixed_backends:
            summary = layout.box()
            summary.alert = True
            summary.label(text="Type-specific controls are hidden for mixed selections", icon="INFO")
            counts = {}
            for selected in selected_rigs:
                label = fbp_layer_backend_label(selected)
                counts[label] = counts.get(label, 0) + 1
            for label, count in sorted(counts.items()):
                summary.label(text=f"{label}: {count}")
            summary.label(text="Visibility, opacity, camera fit and transform remain available")
            return

        if getattr(rig, "fbp_is_color_plane", False):
            mode_box = layout.box()
            mode_box.label(text="Color / Gradient Plane", icon=ui_icon("create.color_plane"))
            row = mode_box.row(align=True)
            row.prop_enum(rig, "fbp_color_plane_mode", 'SOLID', text="Color", icon=ui_icon("menu.color_plane"))
            row.prop_enum(rig, "fbp_color_plane_mode", 'GRADIENT', text="Gradient", icon=ui_icon("menu.gradient_plane"))

        show_animation_panel = (
            is_movie
            or backend_type == 'NATIVE_SEQUENCE'
            or (getattr(rig, "fbp_is_color_plane", False) and len(rig.fbp_images) > 0)
        )
        if is_static_image:
            box = layout.box()
            box.label(text="Static Image", icon=ui_icon("sequence.frames"))
            box.operator(
                "fbp.insert_linked_image_after_selected",
                text="Add Image Frame",
                icon=ui_icon("settings.project_folder"),
            )
        elif show_animation_panel:
            box = layout.box()
            box.label(text="Movie Playback" if is_movie else "Animation", icon=ui_icon("sequence.frames"))
            row = box.row(align=False)
            sub1 = row.row(align=True)
            sub1.prop(rig, "fbp_start_frame")
            sub1.operator("fbp.set_current_frame", text="", icon=ui_icon("sequence.set_current"))
            if is_movie:
                playback = row.row(align=True)
                playback.prop_enum(rig, "fbp_loop_mode", 'NONE', text="One Shot")
                playback.prop_enum(rig, "fbp_loop_mode", 'REPEAT', text="Loop")
            else:
                row.prop(rig, "fbp_loop_mode", text="")
                row.prop(rig, "fbp_global_duration", text="Frame Hold")

        if len(selected_rigs) <= 1 and not is_movie:
            show_frame_tools = not getattr(rig, "fbp_is_color_plane", False) or len(rig.fbp_images) > 0
            can_add_frames = not getattr(rig, "fbp_is_color_plane", False) or fbp_color_plane_can_have_frames(rig)

            if not (getattr(rig, "fbp_is_color_plane", False) and not fbp_color_plane_can_have_frames(rig)):
                box = layout.box()
                box.label(text="Frames" if show_frame_tools else "Animation Frames", icon=ui_icon("layer.header"))
                if show_frame_tools:
                    frame_count = len(rig.fbp_images)
                    checked_indices = [
                        index for index, item in enumerate(rig.fbp_images)
                        if bool(getattr(item, "is_selected", False))
                    ]
                    active_frame_index = max(
                        0,
                        min(int(getattr(rig, "fbp_images_index", 0) or 0), frame_count - 1),
                    ) if frame_count else -1
                    action_indices = checked_indices or (
                        [active_frame_index] if active_frame_index >= 0 else []
                    )
                    action_index_set = set(action_indices)
                    can_move_top = bool(action_indices) and action_indices != list(range(len(action_indices)))
                    can_move_up = any(
                        index > 0 and (index - 1) not in action_index_set
                        for index in action_indices
                    )
                    can_move_down = any(
                        index < frame_count - 1 and (index + 1) not in action_index_set
                        for index in action_indices
                    )
                    can_move_bottom = bool(action_indices) and action_indices != list(
                        range(frame_count - len(action_indices), frame_count)
                    )
                    can_duplicate = bool(checked_indices)
                    can_reverse_sequence = frame_count > 1
                    can_split = bool(checked_indices) and len(checked_indices) < frame_count
                    can_remove = frame_count > 1 or bool(getattr(rig, "fbp_is_color_plane", False))

                    row = box.row(align=False)
                    row.template_list("FBP_UL_ImageList", "",
                                      rig, "fbp_images",
                                      rig, "fbp_images_index", rows=12)
                    col = row.column(align=False)

                    control = col.row(align=False)
                    control.enabled = can_move_top
                    control.operator("fbp.list_action", icon=ui_icon("sequence.move_top"), text="").action = 'MOVE_TOP'
                    control = col.row(align=False)
                    control.enabled = can_move_up
                    control.operator("fbp.list_action", icon=ui_icon("sequence.move_up"), text="").action = 'MOVE_UP'
                    control = col.row(align=False)
                    control.enabled = can_move_down
                    control.operator("fbp.list_action", icon=ui_icon("sequence.move_down"), text="").action = 'MOVE_DOWN'
                    control = col.row(align=False)
                    control.enabled = can_move_bottom
                    control.operator("fbp.list_action", icon=ui_icon("sequence.move_bottom"), text="").action = 'MOVE_BOTTOM'
                    col.separator()
                    control = col.row(align=False)
                    control.enabled = can_duplicate
                    control.operator("fbp.list_action", icon=ui_icon("sequence.duplicate"), text="").action = 'DUPLICATE_SELECTED'
                    control = col.row(align=False)
                    control.enabled = can_reverse_sequence
                    control.operator(
                        "fbp.reverse_sequence",
                        icon=ui_icon("sequence.reverse"),
                        text="",
                        depress=bool(getattr(rig, "fbp_sequence_reversed", False)),
                    )
                    if getattr(rig, "fbp_is_color_plane", False):
                        op = col.operator("fbp.insert_images_after_selected", icon=ui_icon("menu.color_plane"), text="")
                        op.frame_mode = 'COLOR'
                        op = col.operator("fbp.insert_images_after_selected", icon=ui_icon("menu.gradient_plane"), text="")
                        op.frame_mode = 'GRADIENT'
                    else:
                        col.operator("fbp.insert_linked_image_after_selected", icon=ui_icon("settings.project_folder"), text="")
                        col.operator("fbp.insert_transparent_frame", icon=ui_icon("sequence.add_transparent"), text="")
                    col.separator()
                    control = col.row(align=False)
                    control.enabled = can_split
                    control.operator("fbp.split_selected_images_to_new_plane", icon=ui_icon("sequence.split"), text="")
                    col.separator()
                    control = col.row(align=False)
                    control.enabled = can_remove
                    control.operator("fbp.list_action", icon=ui_icon("sequence.delete"), text="").action = 'REMOVE'

                    if fbp_rig_native_sequence_needs_rename(rig):
                        warn = box.box()
                        warn.alert = True
                        warn.label(text="Native sequence filenames may show pink in Blender.", icon=ui_icon("generic.error"))
                        warn.operator("fbp.rename_sequence_for_blender", text="Rename Original Files for Blender", icon=ui_icon("sequence.replace"))

                    row = box.row(align=True)
                    all_selected = len(rig.fbp_images) > 0 and all(bool(item.is_selected) for item in rig.fbp_images)
                    row.operator("fbp.select_all", text="None" if all_selected else "All", icon=ui_icon("sequence.select_none") if all_selected else ui_icon("sequence.select_all")).action = 'TOGGLE'
                    row.operator("fbp.select_all", text="Invert", icon=ui_icon("sequence.select_invert")).action = 'INVERT'
                elif can_add_frames:
                    if getattr(rig, "fbp_is_color_plane", False):
                        row = box.row(align=True)
                        op = row.operator("fbp.insert_images_after_selected", text="Add Color Frame", icon=ui_icon("menu.color_plane"))
                        op.frame_mode = 'COLOR'
                        op = row.operator("fbp.insert_images_after_selected", text="Add Gradient Frame", icon=ui_icon("menu.gradient_plane"))
                        op.frame_mode = 'GRADIENT'
                    else:
                        row = box.row(align=True)
                        row.operator("fbp.insert_linked_image_after_selected", text="Import Image Frame", icon=ui_icon("settings.project_folder"))

        if getattr(rig, "fbp_is_color_plane", False):
            details_box = layout.box()
            details_box.label(text="Frame Appearance", icon=ui_icon("sequence.node_texture"))

            color_row = details_box.row(align=False)
            color_row.enabled = (rig.fbp_color_plane_mode == 'SOLID')
            color_row.prop(rig, "fbp_color_plane_color", text="Color")

            if rig.fbp_color_plane_mode == 'GRADIENT':
                grad_col = details_box.column(align=False)
                row = grad_col.row(align=True)
                row.prop(rig, "fbp_gradient_mode", text="")
                row.prop(rig, "fbp_gradient_kind", text="")
                draw_native_fbp_color_ramp(grad_col, rig)
                transform_box = grad_col.box()
                is_open = bool(getattr(rig, 'fbp_show_gradient_transform', True))
                row = transform_box.row(align=True)
                row.prop(rig, 'fbp_show_gradient_transform', text='Position', icon=(ui_icon("setup.expanded") if is_open else ui_icon("setup.collapsed")), emboss=False)
                if is_open:
                    row = transform_box.row(align=True)
                    row.prop(rig, "fbp_gradient_offset_x", text="X")
                    row.prop(rig, "fbp_gradient_offset_y", text="Y")
                    row = transform_box.row(align=True)
                    row.prop(rig, "fbp_gradient_scale_x", text="Scale X")
                    row.prop(rig, "fbp_gradient_scale_y", text="Scale Y")
                    transform_box.prop(rig, "fbp_gradient_rotation", text="Rotation")


# SECTION 08 - Panel: Effects #
class FBP_PT_Effects(Panel):
    bl_label = "Effects"
    bl_description = "Apply and reorder image-processing and mesh effects"
    bl_idname = "FBP_PT_effects"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Frame by Plane"
    bl_order = 3

    @classmethod
    def poll(cls, context):
        return bool(get_selected_rigs(context))

    def draw_header(self, context):
        self.layout.label(text="", icon=ui_icon("sequence.tools"))

    def draw(self, context):
        draw_effects_ui(self.layout, context)


# SECTION 09 - Panel: Initial Create #
# ###ICON Panel Create, Function: first setup when no FBP rigs exist.
class FBP_PT_CreateFirst(Panel):
    bl_label       = "Create"
    bl_description = "Create image planes, procedural planes and multiplane setups"
    bl_idname      = "FBP_PT_create_first"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "Frame by Plane"
    bl_order       = 4

    @classmethod
    def poll(cls, context):
        return not fbp_scene_has_cached_rigs(context)

    def draw_header(self, context):
        self.layout.label(text="", icon=ui_icon("create.header"))

    def draw(self, context):
        draw_creation_ui(self.layout, context)


# SECTION 09 - Panel: Advanced Create #
# ###ICON Panel Create, Function: additional setup when FBP rigs already exist.
class FBP_PT_CreateExisting(Panel):
    bl_label       = "Create"
    bl_description = "Create additional image planes, procedural planes and multiplane setups"
    bl_idname      = "FBP_PT_create_existing"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "Frame by Plane"
    bl_order       = 5

    @classmethod
    def poll(cls, context):
        return (
            fbp_scene_has_cached_rigs(context)
            and getattr(context.scene, "fbp_show_create_tools", False)
        )

    def draw_header(self, context):
        self.layout.label(text="", icon=ui_icon("create.header"))

    def draw(self, context):
        draw_creation_ui(self.layout, context)


# SECTION 10 - Menu: Shift+A > Frame by Plane #
# ###ICON Menu Shift+A, Functions: Color Plane, Gradient, Holdout, Image Plane, Multiplane, Clipboard.
class FBP_MT_FrameByPlaneAdd(Menu):
    bl_idname = "FBP_MT_frame_by_plane_add"
    bl_label = "Frame By Plane"
    bl_description = "Create Frame by Plane layers and multiplane projects"

    def draw(self, context):
        layout = self.layout
        # Every primary entry opens a popup or file browser. Force invoke
        # context so Shift+A never bypasses the operator's setup dialog.
        layout.operator_context = 'INVOKE_DEFAULT'

        # Keep Shift+A compact: related tools are separated visually without
        # non-clickable section labels taking vertical space.
        layout.operator("fbp.popup_single_plane", text="Image Plane", icon=ui_icon("menu.image_plane"))
        op = layout.operator("fbp.popup_multiplane", text="Multiplane", icon=ui_icon("menu.multiplane"))
        op.animation = True

        layout.separator()
        layout.operator("fbp.import_drawing_plane", text="Cutout Plane", icon=ui_icon("menu.cutout_plane"))

        layout.separator()
        op = layout.operator("fbp.popup_color_plane", text="Color Plane", icon=ui_icon("menu.color_plane"))
        op.preset_type = 'CUSTOM'
        op = layout.operator("fbp.popup_color_plane", text="Gradient Plane", icon=ui_icon("menu.gradient_plane"))
        op.preset_type = 'GRADIENT'
        op = layout.operator("fbp.popup_color_plane", text="Holdout Plane", icon=ui_icon("menu.holdout_plane"))
        op.preset_type = 'HOLDOUT'

        layout.separator()
        layout.operator("fbp.create_color_plane_from_hex", text="Color Plane from Hex Color Code", icon=ui_icon("menu.hex"))
        layout.operator("fbp.import_single_image_from_clipboard", text="Single Plane from Clipboard", icon=ui_icon("menu.clipboard"))


class FBP_MT_ObjectHoldout(Menu):
    bl_idname = "FBP_MT_object_holdout"
    bl_label = "Frame by Plane Holdout"

    def draw(self, context):
        layout = self.layout
        if not get_selected_fbp_roots(context):
            layout.label(text="Select a Frame by Plane layer", icon="INFO")
            return
        layout.operator(
            "fbp.set_selected_holdout",
            text="Set Selected as Holdout",
            icon=ui_icon("menu.holdout_plane"),
        )
        layout.operator(
            "fbp.holdout_all_except_selected",
            text="Holdout All Except Selected",
            icon=ui_icon("menu.holdout_plane"),
        )
        layout.separator()
        layout.operator(
            "fbp.restore_holdout_materials",
            text="Restore Frame by Plane Holdouts",
            icon="LOOP_BACK",
        )


# SECTION 11 - Native menus: Add / Context / Delete / Render #
# ###ICON Menu Render, Function: Background Render at the top of the Topbar.


def _fbp_button_operator_identifier(properties):
    """Return searchable RNA identity text for a hovered operator button."""
    try:
        rna = getattr(properties, 'bl_rna', None)
        parts = (
            getattr(rna, 'identifier', ''),
            getattr(rna, 'name', ''),
            getattr(properties, 'bl_idname', ''),
        )
        return ' '.join(str(value or '') for value in parts).lower()
    except FBP_DATA_ERRORS:
        return ''


def _fbp_context_rename_operator(layout, *, target_type, text, icon='GREASEPENCIL',
                                 rig_name='', collection_name='', index=-1,
                                 tree_index=-1):
    """Draw one reusable rename entry backed by the normal UIList operator."""
    op = layout.operator('fbp.ui_list_name_action', text=text, icon=icon)
    op.target_type = target_type
    op.rig_name = rig_name
    op.collection_name = collection_name
    op.index = index
    op.tree_index = tree_index
    op.rename_mode = True
    return op


def _fbp_context_select_operator(layout, *, target_type, text, icon,
                                 rig_name='', collection_name='', index=-1,
                                 tree_index=-1):
    """Draw one target-specific selection entry without scanning the full tree."""
    op = layout.operator('fbp.ui_list_name_action', text=text, icon=icon)
    op.target_type = target_type
    op.rig_name = rig_name
    op.collection_name = collection_name
    op.index = index
    op.tree_index = tree_index
    return op


def _fbp_layer_move_availability(context, rig):
    """Return (can_move_up, can_move_down) using the same physical order as the toolbar."""
    collection = get_primary_fbp_collection(rig)
    if collection is None:
        return False, False

    stable_order = {}
    candidates = []
    try:
        for stable_index, layer_item in enumerate(context.scene.fbp_layers):
            candidate = getattr(layer_item, 'obj', None)
            if not candidate or not is_fbp_layer_object(candidate):
                continue
            stable_order[candidate] = stable_index
            if get_primary_fbp_collection(candidate) != collection:
                continue
            try:
                visible = bool(candidate.visible_get(view_layer=context.view_layer))
            except TypeError:
                visible = bool(candidate.visible_get())
            if visible:
                candidates.append(candidate)
    except FBP_DATA_ERRORS:
        return False, False

    depth_context = fbp_make_depth_context_cache(context)
    candidates.sort(
        key=lambda candidate: (
            fbp_layer_depth_value_from_cache(candidate, depth_context),
            stable_order.get(candidate, 1 << 30),
        )
    )
    try:
        position = candidates.index(rig)
    except ValueError:
        return False, False
    return position > 0, position + 1 < len(candidates)


def _fbp_can_reverse_selected_layer_context(context):
    """Return True once two selected layers share a canonical collection."""
    counts = {}
    for rig in get_selected_fbp_roots(context):
        if not is_fbp_layer_object(rig):
            continue
        collection = get_primary_fbp_collection(rig)
        if collection is None:
            continue
        try:
            key = int(collection.as_pointer())
        except FBP_DATA_ERRORS:
            continue
        counts[key] = counts.get(key, 0) + 1
        if counts[key] >= 2:
            return True
    return False


def _fbp_can_reverse_pending_context(scene):
    """Return True once two checked setup layers share a direct collection."""
    counts = {}
    try:
        items = scene.fbp_pending_planes
    except FBP_DATA_ERRORS:
        return False
    for item in items:
        try:
            if not bool(getattr(item, 'is_selected', False)):
                continue
            key = str(getattr(item, 'collection_name', '') or '')
        except FBP_DATA_ERRORS:
            continue
        counts[key] = counts.get(key, 0) + 1
        if counts[key] >= 2:
            return True
    return False


def _fbp_draw_layer_button_context(layout, context, rig_name):
    rig = bpy.data.objects.get(str(rig_name or ''))
    if not rig or not is_fbp_layer_object(rig):
        return False

    try:
        clipping_active = bool(rig.get(_FBP_CLIPPING_ENABLED_KEY, False))
    except FBP_DATA_ERRORS:
        clipping_active = False
    identity_icon = (
        'TRACKING_REFINE_BACKWARDS'
        if clipping_active
        else fbp_layer_backend_icon(rig)
    )

    layout.separator()
    layout.label(text='Frame By Plane Layer', icon=identity_icon)
    _fbp_context_rename_operator(
        layout,
        target_type='LAYER',
        text='Rename Layer',
        rig_name=rig.name,
    )
    _fbp_context_select_operator(
        layout,
        target_type='LAYER',
        text='Select Layer',
        icon=ui_icon('layer.select_all'),
        rig_name=rig.name,
    )

    clipping = layout.operator(
        'fbp.toggle_clipping_mask',
        text='Disable Clipping Mask' if clipping_active else 'Enable Clipping Mask',
        icon=identity_icon,
    )
    clipping.rig_name = rig.name
    plane = layout.operator(
        'fbp.select_linked_plane',
        text='Select Linked Plane',
        icon=fbp_select_plane_icon(rig, context),
    )
    plane.rig_name = rig.name

    layout.separator()
    can_move_up, can_move_down = _fbp_layer_move_availability(context, rig)
    move_row = layout.row()
    move_row.enabled = can_move_up
    move = move_row.operator('fbp.move_layer_stack', text='Move Up', icon=ui_icon('generic.up'))
    move.direction = 'UP'
    move.rig_name = rig.name
    move_row = layout.row()
    move_row.enabled = can_move_down
    move = move_row.operator('fbp.move_layer_stack', text='Move Down', icon=ui_icon('generic.down'))
    move.direction = 'DOWN'
    move.rig_name = rig.name

    reverse = layout.row()
    reverse.enabled = _fbp_can_reverse_selected_layer_context(context)
    reverse.operator(
        'fbp.reverse_selected_layer_order',
        text='Reverse Selected Layer Order',
        icon=ui_icon('sequence.reverse'),
    )

    layout.separator()
    duplicate = layout.operator(
        'fbp.duplicate_selected_layers',
        text='Duplicate Layer',
        icon=ui_icon('layer.duplicate'),
    )
    duplicate.rig_name = rig.name
    delete = layout.operator(
        'fbp.delete_sequence',
        text='Delete Layer',
        icon=ui_icon('generic.delete'),
    )
    delete.rig_name = rig.name
    return True


def _fbp_draw_collection_button_context(layout, context, collection_name, tree_index=-1):
    collection = bpy.data.collections.get(str(collection_name or ''))
    if collection is None:
        return False

    layout.separator()
    layout.label(text='Frame By Plane Collection', icon=fbp_collection_icon(collection))
    _fbp_context_rename_operator(
        layout,
        target_type='COLLECTION',
        text='Rename Collection',
        collection_name=collection.name,
        tree_index=tree_index,
    )
    _fbp_context_select_operator(
        layout,
        target_type='COLLECTION',
        text='Select Collection Layers',
        icon=ui_icon('layer.select_all'),
        collection_name=collection.name,
        tree_index=tree_index,
    )

    collapse = layout.operator(
        'fbp.toggle_collection_collapse',
        text='Expand Collection' if bool(getattr(collection, 'fbp_collapsed', False)) else 'Collapse Collection',
        icon=ui_icon('setup.collapsed') if bool(getattr(collection, 'fbp_collapsed', False)) else ui_icon('setup.expanded'),
    )
    collapse.collection_name = collection.name
    layout.prop(
        collection,
        'fbp_collection_visible',
        text='Collection Visible',
        icon=(
            ui_icon('layer.visible_on')
            if getattr(collection, 'fbp_collection_visible', True)
            else ui_icon('layer.visible_off')
        ),
    )
    layout.prop(
        collection,
        'fbp_collection_locked',
        text='Collection Locked',
        icon=(
            ui_icon('layer.lock_on')
            if getattr(collection, 'fbp_collection_locked', False)
            else ui_icon('layer.lock_off')
        ),
    )

    layout.separator()
    delete = layout.operator(
        'fbp.delete_collection_layers',
        text='Delete Collection Layers',
        icon=ui_icon('generic.delete'),
    )
    delete.collection_name = collection.name
    return True


def _fbp_pending_tree_row(scene, tree_index):
    try:
        rows = scene.fbp_pending_tree_rows
        index = int(tree_index)
        if 0 <= index < len(rows):
            return rows[index]
    except FBP_DATA_ERRORS:
        pass
    return None


def _fbp_draw_pending_layer_button_context(layout, context, pending_index, tree_index=-1):
    scene = context.scene
    try:
        index = int(pending_index)
        if not (0 <= index < len(scene.fbp_pending_planes)):
            return False
        pending = scene.fbp_pending_planes[index]
    except FBP_DATA_ERRORS:
        return False

    files = [name for name in str(getattr(pending, 'files_str', '') or '').split('|') if name]
    file_count = len(files)
    tree_row = _fbp_pending_tree_row(scene, tree_index)

    layout.separator()
    layout.label(
        text='Multiplane Setup Layer',
        icon=ui_icon('setup.animated') if file_count > 1 else ui_icon('setup.image'),
    )
    _fbp_context_rename_operator(
        layout,
        target_type='PENDING',
        text='Rename Setup Layer',
        rig_name='',
        index=index,
        tree_index=tree_index,
    )
    edit = layout.operator('fbp.edit_pending_plane', text='Edit Setup Layer', icon=ui_icon('setup.edit'))
    edit.index = index

    reverse = layout.row()
    reverse.enabled = file_count > 1
    op = reverse.operator('fbp.reverse_pending_sequence', text='Reverse Sequence', icon=ui_icon('sequence.reverse'))
    op.index = index

    split = layout.row()
    split.enabled = file_count > 1
    op = split.operator('fbp.toggle_pending_sequence_collection', text='Split into Frame Collection', icon=ui_icon('sequence.split'))
    op.pending_index = index
    op.collection_path = str(getattr(pending, 'collection_name', '') or '')
    op.row_type = 'LAYER'

    layout.separator()
    move = layout.row()
    move.enabled = bool(tree_row is None or getattr(tree_row, 'can_move_up', False))
    op = move.operator('fbp.move_pending_plane', text='Move Up', icon=ui_icon('generic.up'))
    op.direction = 'UP'
    op.index = index
    move = layout.row()
    move.enabled = bool(tree_row is None or getattr(tree_row, 'can_move_down', False))
    op = move.operator('fbp.move_pending_plane', text='Move Down', icon=ui_icon('generic.down'))
    op.direction = 'DOWN'
    op.index = index

    reverse_checked = layout.row()
    reverse_checked.enabled = _fbp_can_reverse_pending_context(scene)
    reverse_checked.operator(
        'fbp.reverse_pending_selected_order',
        text='Reverse Checked Layer Order',
        icon=ui_icon('sequence.reverse'),
    )

    layout.separator()
    remove = layout.operator('fbp.remove_pending_plane_at_index', text='Remove Setup Layer', icon=ui_icon('generic.delete'))
    remove.index = index
    return True


def _fbp_draw_pending_group_button_context(layout, context, collection_path, tree_index=-1):
    path = str(collection_path or '').strip()
    if not path:
        return False
    scene = context.scene
    tree_row = _fbp_pending_tree_row(scene, tree_index)
    is_open = pending_collection_is_open(scene, path)

    layout.separator()
    layout.label(text='Multiplane Setup Collection', icon=ui_icon('setup.collection'))
    _fbp_context_rename_operator(
        layout,
        target_type='PENDING_GROUP',
        text='Rename Setup Collection',
        collection_name=path,
        tree_index=tree_index,
    )

    collapse = layout.operator(
        'fbp.toggle_pending_collection_collapse',
        text='Collapse Collection' if is_open else 'Expand Collection',
        icon=ui_icon('setup.expanded') if is_open else ui_icon('setup.collapsed'),
    )
    collapse.collection_name = path

    merge = layout.row()
    merge.enabled = bool(tree_row is None or getattr(tree_row, 'can_toggle_structure', False))
    op = merge.operator(
        'fbp.toggle_pending_sequence_collection',
        text='Merge Collection into Animated Plane',
        icon=ui_icon('sequence.split'),
    )
    op.pending_index = -1
    op.collection_path = path
    op.row_type = 'GROUP'
    return True


def draw_fbp_button_context_menu(self, context):
    """Append Photoshop-style Frame By Plane actions to UI button menus."""
    try:
        properties = getattr(context, 'button_operator', None)
    except FBP_DATA_ERRORS:
        properties = None
    if properties is None:
        return

    identifier = _fbp_button_operator_identifier(properties)
    layout = self.layout

    if 'toggleclippingmask' in identifier or 'toggle_clipping_mask' in identifier:
        _fbp_draw_layer_button_context(
            layout,
            context,
            getattr(properties, 'rig_name', ''),
        )
        return

    if not ('uilistnameaction' in identifier or 'ui_list_name_action' in identifier):
        return

    target_type = str(getattr(properties, 'target_type', '') or '')
    if target_type == 'LAYER':
        _fbp_draw_layer_button_context(layout, context, getattr(properties, 'rig_name', ''))
    elif target_type == 'COLLECTION':
        _fbp_draw_collection_button_context(
            layout,
            context,
            getattr(properties, 'collection_name', ''),
            getattr(properties, 'tree_index', -1),
        )
    elif target_type == 'PENDING':
        _fbp_draw_pending_layer_button_context(
            layout,
            context,
            getattr(properties, 'index', -1),
            getattr(properties, 'tree_index', -1),
        )
    elif target_type == 'PENDING_GROUP':
        _fbp_draw_pending_group_button_context(
            layout,
            context,
            getattr(properties, 'collection_name', ''),
            getattr(properties, 'tree_index', -1),
        )

def draw_fbp_image_add_menu(self, context):
    layout = self.layout
    layout.separator()
    layout.menu("FBP_MT_frame_by_plane_add", icon=ui_icon("menu.shift_a_root"))
def draw_fbp_object_context_menu(self, context):
    if get_selected_fbp_roots(context):
        self.layout.separator()
        self.layout.menu(
            FBP_MT_ObjectHoldout.bl_idname,
            text="Holdout",
            icon=ui_icon("menu.holdout_plane"),
        )
        self.layout.separator()
        self.layout.operator("fbp.delete_sequence", text="Delete Frame by Plane Layer + Plane", icon=ui_icon("generic.delete"))
        self.layout.operator("fbp.merge_selected_to_active_sequence", text="Convert to Single Animated Plane", icon=ui_icon("layer.duplicate"))
def draw_fbp_delete_menu(self, context):
    if get_selected_fbp_roots(context):
        self.layout.separator()
        self.layout.operator("fbp.delete_sequence", text="Frame by Plane: Delete Rig + Image Plane", icon=ui_icon("generic.delete"))
def fbp_render_menu_draw(self, context):
    """Place Frame by Plane background render at the top of Blender's Render menu."""
    layout = self.layout
    layout.operator(
        "fbp.background_render_frames",
        text="Frame by Plane: Background Render",
        icon=ui_icon("settings.render"),
    )
    layout.separator()
def fbp_render_menu_class():
    """Return Blender 5.1's Topbar Render menu."""
    return getattr(bpy.types, "TOPBAR_MT_render", None)



_FBP_REGISTERED_MENU_CALLBACKS = globals().get("_FBP_REGISTERED_MENU_CALLBACKS", [])


def _fbp_remove_registered_menu_callbacks():
    """Remove callbacks from previous module generations by their stored identity."""
    for menu_cls, callback in reversed(list(_FBP_REGISTERED_MENU_CALLBACKS)):
        try:
            menu_cls.remove(callback)
        except FBP_DATA_ERRORS:
            pass
    _FBP_REGISTERED_MENU_CALLBACKS.clear()


def _fbp_register_menu_callback(menu_cls, callback, method='append'):
    if not menu_cls:
        return False
    try:
        getattr(menu_cls, method)(callback)
        _FBP_REGISTERED_MENU_CALLBACKS.append((menu_cls, callback))
        return True
    except FBP_DATA_ERRORS as exc:
        fbp_warn(f"Could not register Frame by Plane menu callback on {getattr(menu_cls, '__name__', menu_cls)}", exc)
        return False


def register_fbp_menus():
    # Remove callbacks kept by an older module generation before adding the
    # current functions. Blender's Menu.remove() compares function identity.
    _fbp_remove_registered_menu_callbacks()

    _fbp_register_menu_callback(
        getattr(bpy.types, "VIEW3D_MT_add", None),
        draw_fbp_image_add_menu,
        method='prepend',
    )
    _fbp_register_menu_callback(
        fbp_render_menu_class(),
        fbp_render_menu_draw,
        method='prepend',
    )
    _fbp_register_menu_callback(
        getattr(bpy.types, "WM_MT_button_context", None),
        draw_fbp_button_context_menu,
        method='append',
    )
    for menu_name in ("VIEW3D_MT_object_context_menu", "OUTLINER_MT_context_menu"):
        _fbp_register_menu_callback(
            getattr(bpy.types, menu_name, None),
            draw_fbp_object_context_menu,
            method='append',
        )
    for menu_name in ("VIEW3D_MT_object_delete", "OUTLINER_MT_object_delete"):
        _fbp_register_menu_callback(
            getattr(bpy.types, menu_name, None),
            draw_fbp_delete_menu,
            method='prepend',
        )


def unregister_fbp_menus():
    _fbp_remove_registered_menu_callbacks()


# SECTION 12 - UI registration #
# Add or remove panels/UILists here without changing core.py.
ui_classes = (
    FBP_UL_LayerStack,
    FBP_UL_LayerTreeList,
    FBP_UL_ImageList,
    FBP_UL_PendingList,
    FBP_UL_PendingTreeList,
    FBP_PT_Settings,
    FBP_PT_LayerStack,
    FBP_PT_Sequence,
    FBP_PT_Effects,
    FBP_PT_CreateFirst,
    FBP_PT_CreateExisting,
    FBP_MT_FrameByPlaneAdd,
    FBP_MT_ObjectHoldout,
)


def register():
    for cls in ui_classes:
        bpy.utils.register_class(cls)
    register_fbp_menus()


def unregister():
    unregister_fbp_menus()
    for cls in reversed(ui_classes):
        try:
            bpy.utils.unregister_class(cls)
        except FBP_DATA_IO_ERRORS:
            pass
