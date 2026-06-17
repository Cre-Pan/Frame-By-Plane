"""Panels, UILists, Shift+A menu entries and render menu hooks."""

import os
import time

import bpy
from bpy.types import Panel, UIList, Menu

from .geometry_nodes import (
    fbp_active_effect_id,
    fbp_can_move_effect,
    fbp_draw_effect_settings,
    fbp_effect_definition,
    fbp_effect_ids_for_rig,
    fbp_effect_presence,
    fbp_effect_source_rig,
    fbp_schedule_effect_items_sync,
)

from .constants import fbp_collection_color_icon, fbp_strip_icon
from .path_utils import natural_sort_key
from .runtime import fbp_warn
from .layers import (
    fbp_collection_icon,
    fbp_collection_plane_icon,
    fbp_collection_rows_are_disabled,
    fbp_collection_select_icon,
    fbp_color_plane_type_icon,
    fbp_layer_depth_value_from_cache,
    fbp_layer_row_type_icon,
    fbp_make_depth_context_cache,
    fbp_mask_icon,
    fbp_procedural_kind_for_item,
    fbp_procedural_kind_from_material,
    fbp_select_plane_icon,
    fbp_select_rig_icon,
    fbp_set_ui_units_x,
    get_layer_item_for_rig,
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
from .ui_layout import (
    draw_creation_ui,
    draw_layer_tree_uilist,
)


# SECTION 00B - Quick UI icon map #
# Change icons globally in constants.py > FBP_ICONS.
# The markers below identify the relevant UI locations.
# ###ICON Panel Layer Stack, Function Preview/Color Tag: preview.icon_id, fbp_strip_icon(rig.fbp_color_tag)
# ###ICON Panel Layer Stack, Function Solo: OUTLINER_OB_LIGHT / LIGHT
# ###ICON Panel Layer Stack, Function Select: CHECKBOX_HLT / CHECKBOX_DEHLT
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
# ###ICON Menu Render, Function Background Render: RENDER_ANIMATION
#
# Main icon aliases live in ui_icons.py.


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
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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

            op_name = row.operator("fbp.ui_list_name_action", text=rig.name, icon=ui_icon("sequence.normal_frame"), emboss=False)
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
    visual column for Solo/Mask/Plane Lock/Lock/Select while keeping the eye as
    the first icon on every row.
    """

    def draw_item(self, context, layout, data, item, icon, _active_data, _active_propname, index):
        if item is None:
            return

        row_type = getattr(item, 'row_type', 'LAYER')
        depth = max(0, min(10, int(getattr(item, 'depth', 0))))

        # Split the UIList row into a flexible left area and a fixed right
        # action strip. This is more stable than appending icons after the text,
        # because long layer names no longer push the buttons out of alignment.
        split = layout.split(factor=0.72, align=True)
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
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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
        rig = bpy.data.objects.get(rig_name)
        layer_item = get_layer_item_for_rig(context, rig) if rig else None
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
            content.active = bool(getattr(rig, 'fbp_is_visible', True)) and not bool(layer_item.rig_locked)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass

        for _ in range(depth):
            content.label(text='', icon=ui_icon('generic.blank'))

        # Placeholder aligns layers under the collection arrow column.
        content.label(text='', icon=ui_icon('generic.blank'))

        content.alignment = 'LEFT'
        fbp_draw_layer_tag_and_preview(content, rig, context)
        op_name = content.operator('fbp.ui_list_name_action', text=rig.name, icon=ui_icon('sequence.normal_frame'), emboss=False)
        op_name.target_type = 'LAYER'
        op_name.rig_name = rig.name
        op_name.tree_index = index

        solo_icon = ui_icon('layer.solo_on') if layer_item.solo_view else ui_icon('layer.solo_off')
        right.prop(layer_item, 'solo_view', text='', icon=solo_icon, icon_only=True, emboss=False)

        # Property buttons keep Blender hold-and-slide painting.
        right.prop(layer_item, 'holdout', text='', icon=fbp_mask_icon(layer_item.holdout), icon_only=True, emboss=False)
        right.prop(layer_item, 'plane_locked', text='', icon=fbp_select_plane_icon(rig, context), icon_only=True, emboss=False)

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
                if img_path and not os.path.exists(bpy.path.abspath(img_path)):
                    is_missing = True
                if img_path and context.scene.fbp_show_previews:
                    thumb = load_preview(img_path)
                    if thumb:
                        custom_icon = thumb.icon_id
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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
        row = layout.row(align=True)
        depth = max(0, min(10, int(getattr(item, 'depth', 0))))

        # Visible indentation: BLANK1 before arrow/icon/text.
        for _ in range(depth):
            row.label(text='', icon=ui_icon('generic.blank'))

        row_type = getattr(item, 'row_type', 'LAYER')
        if row_type == 'GROUP':
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

        # Extra blank keeps layer rows visually under the folder/scene label, after the arrow column.
        row.label(text='', icon=ui_icon('generic.blank'))
        if pending is not None:
            row.prop(pending, 'fbp_color_tag', text='', icon_only=True)
            name_op = row.operator('fbp.ui_list_name_action', text=pending.name, icon=layer_icon, emboss=False)
            name_op.target_type = 'PENDING'
            name_op.index = pending_index
            name_op.tree_index = index
        else:
            row.label(text=getattr(item, 'name', '') or 'Missing Layer', icon=ui_icon('generic.error'))

        if file_count > 1:
            row.label(text=f'F {file_count}')
        elif file_count == 1:
            row.label(text='F 1')
        else:
            row.label(text='empty', icon=ui_icon('generic.error'))

        edit = row.operator('fbp.edit_pending_plane', text='', icon=ui_icon('setup.edit'), emboss=False)
        edit.index = pending_index

# SECTION 04 - Helper UI: Pending Setup and Tree View #
# Layout helper lives in ui_layout.py.
# ###ICON Tree View, Functions: collection collapse, visibility, solo, holdout, select rigs/planes, lock.

# SECTION 05 - Panel: Settings / Project / Camera / Render / Maintenance #
# ###ICON Panel Settings, Functions: project folder, camera, render, maintenance and project stats.
_FBP_PROJECT_STATS_CACHE = {"timestamp": 0.0, "signature": None, "data": None}
_FBP_PROJECT_STATS_CACHE_SECONDS = 0.75


def _fbp_project_statistics(scene):
    """Collect file-wide Frame by Plane statistics without changing data.

    The Settings panel can redraw many times per second. A short-lived runtime
    cache avoids repeatedly walking every scene, collection and source path
    while keeping the displayed values responsive to edits.
    """
    now = time.monotonic()
    try:
        signature = (
            str(getattr(bpy.data, "filepath", "") or ""),
            len(bpy.data.scenes),
            len(bpy.data.objects),
            len(bpy.data.collections),
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        signature = None
    cached = _FBP_PROJECT_STATS_CACHE.get("data")
    if (
        cached is not None
        and signature == _FBP_PROJECT_STATS_CACHE.get("signature")
        and now - float(_FBP_PROJECT_STATS_CACHE.get("timestamp", 0.0)) < _FBP_PROJECT_STATS_CACHE_SECONDS
    ):
        return cached

    try:
        project_scenes = bpy.data.scenes
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        project_scenes = (scene,) if scene else ()

    rigs_by_pointer = {}
    planes_by_pointer = {}
    collection_ptrs = set()
    visited_collection_ptrs = set()
    scenes_with_fbp = 0

    def pointer_key(datablock):
        try:
            return int(datablock.as_pointer())
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return id(datablock)

    def visit_collection(collection):
        try:
            collection_key = pointer_key(collection)
            if collection_key in visited_collection_ptrs:
                return
            visited_collection_ptrs.add(collection_key)
            if bool(getattr(collection, 'is_fbp_collection', False)):
                collection_ptrs.add(collection_key)
            for child in collection.children:
                visit_collection(child)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return

    for project_scene in project_scenes:
        scene_has_fbp = False
        try:
            for obj in project_scene.objects:
                if bool(getattr(obj, 'is_fbp_control', False)):
                    rigs_by_pointer[pointer_key(obj)] = obj
                    scene_has_fbp = True
                if bool(getattr(obj, 'is_fbp_plane', False)):
                    planes_by_pointer[pointer_key(obj)] = obj
            visit_collection(project_scene.collection)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        if scene_has_fbp:
            scenes_with_fbp += 1

    rigs = list(rigs_by_pointer.values())
    planes = list(planes_by_pointer.values())
    live_rig_ptrs = set(rigs_by_pointer)
    target_plane_ptrs = set()
    source_paths = set()
    missing_paths = set()
    content_starts = []
    content_ends = []

    image_layers = 0
    color_layers = 0
    gradient_layers = 0
    holdout_layers = 0
    logical_frames = 0
    combined_duration = 0
    active_effects = 0
    shader_effects = 0
    geometry_effects = 0
    heavy_effects = 0
    text_matrix_cells = 0
    text_matrix_render_cells = 0

    for rig in rigs:
        try:
            if bool(getattr(rig, 'fbp_is_color_plane', False)):
                mode = str(getattr(rig, 'fbp_color_plane_mode', 'SOLID') or 'SOLID')
                if mode == 'GRADIENT':
                    gradient_layers += 1
                elif mode == 'HOLDOUT':
                    holdout_layers += 1
                else:
                    color_layers += 1
            else:
                image_layers += 1

            rows = list(getattr(rig, 'fbp_images', []))
            logical_frames += len(rows)
            duration = sum(max(1, int(getattr(item, 'duration', 1) or 1)) for item in rows)
            combined_duration += duration
            start_frame = int(getattr(rig, 'fbp_start_frame', 1) or 1)
            if rows:
                content_starts.append(start_frame)
                content_ends.append(start_frame + max(0, duration - 1))

            for item in rows:
                if bool(getattr(item, 'is_empty', False)):
                    continue
                raw = str(getattr(item, 'filepath', '') or '').strip()
                if not raw:
                    continue
                absolute = os.path.abspath(bpy.path.abspath(raw))
                normalized = os.path.normcase(os.path.normpath(absolute))
                source_paths.add(normalized)
                if not os.path.isfile(absolute):
                    missing_paths.add(normalized)

            plane = getattr(rig, 'fbp_plane_target', None)
            if plane and bool(getattr(plane, 'is_fbp_plane', False)):
                target_plane_ptrs.add(pointer_key(plane))
            for collection in getattr(rig, 'users_collection', []):
                collection_ptrs.add(pointer_key(collection))
            for effect_id in fbp_effect_ids_for_rig(rig):
                definition = fbp_effect_definition(effect_id)
                kind = str(definition.get("kind", "") or "")
                if kind not in {"SHADER", "GEOMETRY"}:
                    continue
                active_effects += 1
                if kind == "SHADER":
                    shader_effects += 1
                else:
                    geometry_effects += 1
                if str(definition.get("performance", "") or "").upper() in {"HEAVY", "VERY_HEAVY"}:
                    heavy_effects += 1
                if effect_id == "TEXT_MATRIX":
                    columns = max(2, int(getattr(rig, "fbp_text_matrix_viewport_columns", 24) or 24))
                    aspect = max(0.1, float(getattr(rig, "fbp_text_matrix_character_aspect", 0.6) or 0.6))
                    plane = getattr(rig, "fbp_plane_target", None)
                    width = height = 1.0
                    try:
                        width = max(1e-4, abs(float(plane.dimensions.x)))
                        height = max(1e-4, abs(float(plane.dimensions.y)))
                    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                        pass
                    manual_rows = int(getattr(rig, "fbp_text_matrix_viewport_rows", 0) or 0)
                    rows = manual_rows if manual_rows > 0 else max(2, round((height / width) * columns * aspect))
                    text_matrix_cells += columns * rows
                    render_columns = max(2, int(getattr(rig, "fbp_text_matrix_render_columns", columns) or columns))
                    manual_render_rows = int(getattr(rig, "fbp_text_matrix_render_rows", 0) or 0)
                    render_rows = manual_render_rows if manual_render_rows > 0 else max(2, round((height / width) * render_columns * aspect))
                    text_matrix_render_cells += render_columns * render_rows
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            continue

    linked_planes = 0
    orphan_planes = 0
    for plane in planes:
        try:
            plane_ptr = pointer_key(plane)
            parent = getattr(plane, 'parent', None)
            parent_is_live_rig = bool(
                parent
                and getattr(parent, 'is_fbp_control', False)
                and pointer_key(parent) in live_rig_ptrs
            )
            if plane_ptr in target_plane_ptrs or parent_is_live_rig:
                linked_planes += 1
            else:
                orphan_planes += 1
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            orphan_planes += 1

    generated_effect_node_groups = 0
    generated_effect_materials = 0
    try:
        generated_effect_node_groups = sum(
            1 for node_group in bpy.data.node_groups
            if str(node_group.get("fbp_effect_asset_id", "") or "")
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        generated_effect_node_groups = 0
    try:
        generated_effect_materials = sum(
            1 for material in bpy.data.materials
            if str(material.get("fbp_effect_material_id", "") or "")
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        generated_effect_materials = 0

    statistics = {
        'scenes': scenes_with_fbp,
        'layers': len(rigs),
        'image_layers': image_layers,
        'color_layers': color_layers,
        'gradient_layers': gradient_layers,
        'holdout_layers': holdout_layers,
        'logical_frames': logical_frames,
        'combined_duration': combined_duration,
        'source_files': len(source_paths),
        'missing_files': len(missing_paths),
        'collections': len(collection_ptrs),
        'linked_planes': linked_planes,
        'orphan_planes': orphan_planes,
        'effects': active_effects,
        'shader_effects': shader_effects,
        'geometry_effects': geometry_effects,
        'heavy_effects': heavy_effects,
        'text_matrix_cells': text_matrix_cells,
        'text_matrix_render_cells': text_matrix_render_cells,
        'generated_effect_node_groups': generated_effect_node_groups,
        'generated_effect_materials': generated_effect_materials,
        'content_start': min(content_starts) if content_starts else None,
        'content_end': max(content_ends) if content_ends else None,
    }
    _FBP_PROJECT_STATS_CACHE["timestamp"] = now
    _FBP_PROJECT_STATS_CACHE["signature"] = signature
    _FBP_PROJECT_STATS_CACHE["data"] = statistics
    return statistics


def _fbp_settings_foldout(layout, scene, property_name, label, icon):
    """Draw a compact disclosure box and return its content layout when open."""
    box = layout.box()
    is_open = bool(getattr(scene, property_name, False))
    row = box.row(align=True)
    row.label(text="", icon=icon)
    row.prop(
        scene,
        property_name,
        text=label,
        icon=ui_icon("setup.expanded") if is_open else ui_icon("setup.collapsed"),
        emboss=False,
    )
    return box if is_open else None


class FBP_PT_Settings(Panel):
    bl_label       = "Settings"
    bl_description = "Project, camera, render, maintenance and project statistics"
    bl_idname      = "FBP_PT_settings"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "Frame by Plane"
    bl_options     = {'DEFAULT_CLOSED'}
    bl_order       = 0

    def draw_header(self, context):
        self.layout.label(text="", icon=ui_icon("settings.header"))

    def draw(self, context):
        layout = self.layout
        sc = context.scene

        tabs = layout.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=True, align=True)
        tabs.prop_enum(sc, "fbp_settings_section", 'PROJECT', text="Project", icon=ui_icon("settings.project"))
        tabs.prop_enum(sc, "fbp_settings_section", 'CAMERA', text="Camera", icon=ui_icon("settings.camera_tab"))
        tabs.prop_enum(sc, "fbp_settings_section", 'RENDER', text="Render", icon=ui_icon("settings.render_tab"))
        tabs.prop_enum(sc, "fbp_settings_section", 'MAINTENANCE', text="Maintenance", icon=ui_icon("settings.repair"))

        layout.separator()
        section = getattr(sc, 'fbp_settings_section', 'PROJECT')

        if section == 'PROJECT':
            primary = _fbp_settings_foldout(
                layout, sc, 'fbp_settings_primary_open', 'Project Folder', ui_icon("settings.project")
            )
            if primary is not None:
                primary.prop(sc, "fbp_project_path", text="Project Folder")

            secondary = _fbp_settings_foldout(
                layout, sc, 'fbp_settings_secondary_open', 'Blender File', ui_icon("settings.save")
            )
            if secondary is not None:
                row = secondary.row()
                row.scale_y = 1.2
                row.operator("fbp.save_file", text="Save Blender File", icon=ui_icon("settings.save"))

        elif section == 'CAMERA':
            primary = _fbp_settings_foldout(
                layout, sc, 'fbp_settings_primary_open', 'Projection', ui_icon("settings.projection")
            )
            if primary is not None:
                primary.prop(sc, "fbp_camera_projection", text="Projection")
                if sc.fbp_camera_projection == 'ORTHO':
                    primary.prop(sc, "fbp_camera_ortho_scale", text="Orthographic Scale")
                else:
                    primary.prop(sc, "fbp_camera_lens", text="Lens (mm)")
                row = primary.row(align=True)
                row.prop(sc, "fbp_camera_clip_start", text="Clip Start")
                row.prop(sc, "fbp_camera_clip_end", text="Clip End")

            secondary = _fbp_settings_foldout(
                layout, sc, 'fbp_settings_secondary_open', 'Camera Frame', ui_icon("settings.camera_frame")
            )
            if secondary is not None:
                secondary.prop(sc, "fbp_cam_ratio", text="Aspect Ratio")
                if sc.fbp_cam_ratio == 'CUSTOM':
                    row = secondary.row(align=True)
                    row.prop(sc.render, "resolution_x", text="Width")
                    row.prop(sc.render, "resolution_y", text="Height")

        elif section == 'RENDER':
            primary = _fbp_settings_foldout(
                layout, sc, 'fbp_settings_primary_open', 'Output', ui_icon("settings.output")
            )
            if primary is not None:
                primary.prop(sc, "fbp_render_output_dir", text="Output Folder")
                primary.prop(sc, "fbp_render_prefix", text="Filename Prefix")

            secondary = _fbp_settings_foldout(
                layout, sc, 'fbp_settings_secondary_open', 'Render Sequence', ui_icon("settings.render_sequence")
            )
            if secondary is not None:
                range_row = secondary.row(align=True)
                range_row.label(text=f"Sequence In: {int(sc.frame_start)}", icon='PREV_KEYFRAME')
                range_row.label(text=f"Sequence Out: {int(sc.frame_end)}", icon='NEXT_KEYFRAME')
                row = secondary.row(align=True)
                row.operator("fbp.repair_render_state", icon=ui_icon("settings.repair"), text="Repair Render State")
                if getattr(sc, 'fbp_background_render_running', False):
                    row.operator("fbp.stop_background_render", icon='CANCEL', text="Stop Render")
                else:
                    row.operator("fbp.background_render_frames", icon=ui_icon("settings.render_sequence"), text="Render Sequence")
                if getattr(sc, 'fbp_background_render_running', False) or int(getattr(sc, 'fbp_background_render_total', 0) or 0) > 0:
                    status_box = secondary.box()
                    status_box.label(text=getattr(sc, 'fbp_background_render_status', 'Idle'), icon='RENDER_ANIMATION')
                    total = int(getattr(sc, 'fbp_background_render_total', 0) or 0)
                    progress = int(getattr(sc, 'fbp_background_render_progress', 0) or 0)
                    if total > 0:
                        status_box.label(text=f"Rendered Frames: {progress} of {total} · Remaining: {max(0, total - progress)}")
                    status_box.operator("fbp.background_render_status", icon='INFO', text="Open Render Status")

        else:
            primary = _fbp_settings_foldout(
                layout, sc, 'fbp_settings_primary_open', 'Maintenance Tools', ui_icon("settings.repair")
            )
            if primary is not None:
                row = primary.row(align=True)
                row.operator("fbp.relink_from_project_root", icon=ui_icon("settings.relink"), text="Relink Missing Files")
                row.operator("fbp.select_missing_layers", icon=ui_icon("generic.error"), text="Select Missing Layers")
                primary.operator("fbp.project_health_check", icon=ui_icon("settings.health"), text="Create Detailed Health Report")
                primary.operator("fbp.profile_effects", icon="TIME", text="Run Effects Profiler")
                primary.operator("fbp.create_effect_regression_scene", icon="SCENE_DATA", text="Create Effects Regression Scene")

            secondary = _fbp_settings_foldout(
                layout, sc, 'fbp_settings_secondary_open', 'Project Statistics', ui_icon("settings.stats")
            )
            if secondary is not None:
                stats = _fbp_project_statistics(sc)
                col = secondary.column(align=True)
                col.label(text=f"ACTIVE FBP Scenes: {stats['scenes']}")
                col.label(text=f"ACTIVE FBP Layers: {stats['layers']} total · {stats['image_layers']} image/video")
                col.label(text=f"Procedural Layers: {stats['color_layers']} color · {stats['gradient_layers']} gradient · {stats['holdout_layers']} holdout")
                col.label(text=f"Logical Frame Rows: {stats['logical_frames']}")
                col.label(text=f"Combined Layer Duration: {stats['combined_duration']} timeline-frame units")
                if stats['content_start'] is not None:
                    content_length = max(0, stats['content_end'] - stats['content_start'] + 1)
                    col.label(text=f"Overall Authored Range: {stats['content_start']} to {stats['content_end']} · {content_length} frames")
                else:
                    col.label(text="Overall Authored Range: no animated layers")
                scene_length = max(0, int(sc.frame_end) - int(sc.frame_start) + 1)
                col.label(text=f"Current Scene Range: {int(sc.frame_start)} to {int(sc.frame_end)} · {scene_length} frames")
                col.label(text=f"Project Structure: {stats['collections']} FBP collections · {stats['linked_planes']} linked render planes")
                col.label(text=f"Source Media: {stats['source_files']} unique files · {stats['missing_files']} missing")
                col.label(text=f"ACTIVE Effects: {stats['effects']} · {stats['shader_effects']} image · {stats['geometry_effects']} mesh")
                if stats['heavy_effects']:
                    col.label(text=f"Heavy Effects: {stats['heavy_effects']}", icon='ERROR')
                if stats['generated_effect_node_groups']:
                    col.label(text=f"Generated Effect Node Groups: {stats['generated_effect_node_groups']}", icon='NODETREE')
                if stats['generated_effect_materials']:
                    col.label(text=f"Generated Effect Materials: {stats['generated_effect_materials']}", icon='MATERIAL')
                if stats['text_matrix_cells']:
                    col.label(text=f"Text Matrix Characters: {stats['text_matrix_cells']:,} viewport · {stats['text_matrix_render_cells']:,} render")
                if 'fbp_effect_profile_avg_ms' in sc:
                    col.separator()
                    col.label(
                        text=(
                            f"Last Effects Profile: {float(sc.get('fbp_effect_profile_avg_ms', 0.0)):.2f} ms avg · "
                            f"{float(sc.get('fbp_effect_profile_max_ms', 0.0)):.2f} ms max"
                        ),
                        icon='TIME',
                    )
                    if float(sc.get('fbp_effect_profile_rss_mb', 0.0) or 0.0) > 0.0:
                        col.label(
                            text=(
                                f"Blender Working Set: {float(sc.get('fbp_effect_profile_rss_mb', 0.0)):.1f} MiB · "
                                f"Profile Delta: {float(sc.get('fbp_effect_profile_delta_mb', 0.0)):+.1f} MiB"
                            ),
                            icon='INFO',
                        )
                if stats['orphan_planes']:
                    col.separator()
                    col.label(text=f"Potential orphan planes: {stats['orphan_planes']}", icon=ui_icon("generic.error"))
                elif stats['missing_files']:
                    col.separator()
                    col.label(text=f"Missing source files: {stats['missing_files']}", icon=ui_icon("generic.error"))
                else:
                    col.separator()
                    col.label(text="No missing files or orphan planes detected.", icon=ui_icon("settings.health"))


def fbp_scene_has_cached_rigs(context):
    """Use the synchronized layer cache instead of scanning Scene objects in UI polls."""
    scene = getattr(context, "scene", None) if context else None
    if not scene:
        return False
    try:
        for item in list(getattr(scene, "fbp_layers", ()) or ()):
            rig = getattr(item, "obj", None)
            if rig and is_fbp_layer_object(rig):
                return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        active = getattr(context, "active_object", None)
        return bool(active and is_fbp_layer_object(active))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
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

        row = layout.row(align=False)
        box = row.box()
        draw_layer_tree_uilist(box, context)
        col = row.column(align=True)
        fbp_set_ui_units_x(col, 1.25)
        col.prop(sc, "fbp_sort_layers_alpha", text="", toggle=True, icon=ui_icon("layer.sort_alpha"))
        col.operator("fbp.move_layer_stack", text="", icon=ui_icon("generic.down")).direction = 'DOWN'
        col.operator("fbp.move_layer_stack", text="", icon=ui_icon("generic.up")).direction  = 'UP'
        col.separator()
        col.operator("fbp.open_create_rig", text="", icon=ui_icon("generic.add"))
        col.operator("fbp.popup_color_plane", text="", icon=ui_icon("menu.color_plane"))
        col.separator()
        col.operator("fbp.duplicate_selected_layers", text="", icon=ui_icon("layer.duplicate"))
        col.operator("fbp.delete_sequence", text="", icon=ui_icon("generic.delete"))
        col.separator()
        col.operator("fbp.select_all_layers", text="", icon=ui_icon("layer.select_all"))


def draw_effects_ui(layout, context):
    """Draw the independent Image/Mesh effects stack for selected FBP rigs."""
    selected_rigs = get_selected_rigs(context)
    if not selected_rigs:
        return

    sc = context.scene
    rig = selected_rigs[0]
    listed_effects = fbp_schedule_effect_items_sync(rig, selected_rigs)
    active_effect = fbp_active_effect_id(rig) if listed_effects else ""
    active_definition = fbp_effect_definition(active_effect) if active_effect else {}
    present_count, selected_count = (
        fbp_effect_presence(selected_rigs, active_effect)
        if active_effect else (0, len(selected_rigs))
    )

    switch = layout.row(align=True)
    switch.scale_y = 1.1
    switch.prop_enum(
        sc, "fbp_effects_view", '2D',
        text="Image Effects", icon="NODE_TEXTURE",
    )
    switch.prop_enum(
        sc, "fbp_effects_view", '3D',
        text="Mesh Effects", icon="MODIFIER",
    )

    effects_view = getattr(sc, "fbp_effects_view", "2D")
    visible_categories = {"3D"} if effects_view == "3D" else {"BASE", "2D"}
    if active_effect and str(active_definition.get("category", "2D") or "2D") not in visible_categories:
        active_effect = ""
        active_definition = {}
        present_count, selected_count = (0, len(selected_rigs))

    list_type = "FBP_UL_EffectStack3D" if effects_view == "3D" else "FBP_UL_EffectStack2D"
    list_id = "MESH" if effects_view == "3D" else "IMAGE"
    stack_row = layout.row(align=False)
    stack_row.template_list(
        list_type, list_id,
        rig, "fbp_effects",
        rig, "fbp_effects_index",
        rows=6,
    )

    shared_effect = bool(
        active_effect
        and present_count == selected_count
        and active_definition.get("kind") in {"SHADER", "GEOMETRY"}
    )
    controls = stack_row.column(align=True)
    fbp_set_ui_units_x(controls, 1.25)

    move_up = controls.row(align=True)
    move_up.enabled = bool(
        shared_effect
        and all(fbp_can_move_effect(item, active_effect, "UP") for item in selected_rigs)
    )
    op = move_up.operator("fbp.move_active_effect", text="", icon=ui_icon("generic.up"))
    op.direction = "UP"

    move_down = controls.row(align=True)
    move_down.enabled = bool(
        shared_effect
        and all(fbp_can_move_effect(item, active_effect, "DOWN") for item in selected_rigs)
    )
    op = move_down.operator("fbp.move_active_effect", text="", icon=ui_icon("generic.down"))
    op.direction = "DOWN"

    controls.separator()
    add_menu = controls.operator("wm.call_menu", text="", icon=ui_icon("generic.add"))
    add_menu.name = "FBP_MT_add_effect"
    controls.separator()
    duplicate = controls.row(align=True)
    duplicate.enabled = bool(active_effect and 0 < present_count < selected_count)
    duplicate.operator("fbp.duplicate_active_effect", text="", icon="DUPLICATE")
    controls.separator()
    actions_menu = controls.operator("wm.call_menu", text="", icon="DOWNARROW_HLT")
    actions_menu.name = "FBP_MT_effect_stack_actions"

    if active_effect:
        source_rig = fbp_effect_source_rig(selected_rigs, active_effect)
        if source_rig:
            fbp_draw_effect_settings(
                layout,
                source_rig,
                active_effect,
                selected_count=selected_count,
                present_count=present_count,
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
        sc = context.scene
        selected_rigs = get_selected_rigs(context)
        if not selected_rigs:
            return

        rig = selected_rigs[0]

        box = layout.box()

        row = box.row(align=False)
        row.prop(rig, "fbp_color_tag", text="", icon_only=False)
        row.prop(rig, "name", text="", icon=ui_icon("sequence.header"))
        row.operator("fbp.replace_sequence", text="", icon=ui_icon("setup.edit"))

        row = box.row(align=False)
        vis_icon=ui_icon("layer.visible_on") if rig.fbp_is_visible else ui_icon("layer.visible_off")
        row.prop(rig, "fbp_is_visible", text="", icon=vis_icon)
        is_holdout_plane = bool(getattr(rig, "fbp_is_color_plane", False) and getattr(rig, "fbp_color_plane_mode", 'SOLID') == 'HOLDOUT')
        if not is_holdout_plane:
            row.prop(rig, "fbp_opacity", text="Opacity", slider=True)
            emiss_icon=ui_icon("sequence.emission")
            if getattr(rig, "fbp_is_color_plane", False):
                row.prop(rig, "fbp_color_plane_emission", text="", icon=emiss_icon, toggle=True)
            else:
                row.prop(rig, "fbp_use_emission", text="", icon=emiss_icon, toggle=True)

        row = box.row(align=False)
        row.prop(rig, "fbp_track_cam", toggle=True, icon=ui_icon("sequence.camera_track"))
        if len(selected_rigs) > 1:
            row.operator("fbp.multi_fit_camera", text="Fit", icon=ui_icon("sequence.fit"))
        else:
            row.operator("fbp.fit_camera", icon=ui_icon("sequence.fit"), text="Fit")
        row.operator("fbp.popup_transform", text="Transform", icon=ui_icon("sequence.transform"))

        if getattr(rig, "fbp_is_color_plane", False):
            mode_box = layout.box()
            mode_box.label(text="Color / Gradient Plane", icon=ui_icon("create.color_plane"))
            row = mode_box.row(align=True)
            row.prop_enum(rig, "fbp_color_plane_mode", 'SOLID', text="Color", icon=ui_icon("menu.color_plane"))
            row.prop_enum(rig, "fbp_color_plane_mode", 'GRADIENT', text="Gradient", icon=ui_icon("menu.gradient_plane"))

        show_animation_panel = not getattr(rig, "fbp_is_color_plane", False) or len(rig.fbp_images) > 0
        if show_animation_panel:
            box = layout.box()
            box.label(text="Animation", icon=ui_icon("sequence.frames"))
            row = box.row(align=False)
            sub1 = row.row(align=True)
            sub1.prop(rig, "fbp_start_frame")
            sub1.operator("fbp.set_current_frame", text="", icon=ui_icon("sequence.set_current"))
            row.prop(rig, "fbp_loop_mode", text="")
            row.prop(rig, "fbp_global_duration", text="FPS")
            row.operator("fbp.reverse_sequence", text="", icon=ui_icon("sequence.reverse"))

        if len(selected_rigs) <= 1:
            show_frame_tools = not getattr(rig, "fbp_is_color_plane", False) or len(rig.fbp_images) > 0
            can_add_frames = not getattr(rig, "fbp_is_color_plane", False) or fbp_color_plane_can_have_frames(rig)

            if not (getattr(rig, "fbp_is_color_plane", False) and not fbp_color_plane_can_have_frames(rig)):
                box = layout.box()
                box.label(text="Frames" if show_frame_tools else "Animation Frames", icon=ui_icon("layer.header"))
                if show_frame_tools:
                    row = box.row()
                    row.template_list("FBP_UL_ImageList", "",
                                      rig, "fbp_images",
                                      rig, "fbp_images_index", rows=8)
                    col = row.column(align=False)
                    col.operator("fbp.list_action", icon=ui_icon("sequence.move_top"), text="").action = 'MOVE_TOP'
                    col.operator("fbp.list_action", icon=ui_icon("sequence.move_up"), text="").action = 'MOVE_UP'
                    col.operator("fbp.list_action", icon=ui_icon("sequence.move_down"), text="").action = 'MOVE_DOWN'
                    col.operator("fbp.list_action", icon=ui_icon("sequence.move_bottom"), text="").action = 'MOVE_BOTTOM'
                    col.separator()
                    col.operator("fbp.list_action", icon=ui_icon("sequence.duplicate"), text="").action = 'DUPLICATE_SELECTED'
                    col.operator("fbp.list_action", icon=ui_icon("sequence.reverse_selected"), text="").action = 'REVERSE_SELECTED'
                    if getattr(rig, "fbp_is_color_plane", False):
                        op = col.operator("fbp.insert_images_after_selected", icon=ui_icon("menu.color_plane"), text="")
                        op.frame_mode = 'COLOR'
                        op = col.operator("fbp.insert_images_after_selected", icon=ui_icon("menu.gradient_plane"), text="")
                        op.frame_mode = 'GRADIENT'
                    else:
                        col.operator("fbp.insert_transparent_frame", icon=ui_icon("sequence.add_transparent"), text="")
                    col.separator()
                    col.operator("fbp.split_selected_images_to_new_plane", icon=ui_icon("sequence.split"), text="")
                    col.separator()
                    col.operator("fbp.list_action", icon=ui_icon("sequence.delete"), text="").action = 'REMOVE'

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
            else:
                closed = details_box.row(align=True)
                closed.enabled = False
                closed.label(text="Gradient controls closed", icon=ui_icon("setup.collapsed"))


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
    bl_description = "Create Frame by Plane image, color, gradient, holdout and multiplane layers"

    def draw(self, context):
        layout = self.layout
        op = layout.operator("fbp.popup_color_plane", text="Color Plane", icon=ui_icon("menu.color_plane"))
        op.preset_type = 'CUSTOM'
        op = layout.operator("fbp.popup_color_plane", text="Gradient Plane", icon=ui_icon("menu.gradient_plane"))
        op.preset_type = 'GRADIENT'
        op = layout.operator("fbp.popup_color_plane", text="Holdout Plane", icon=ui_icon("menu.holdout_plane"))
        op.preset_type = 'HOLDOUT'
        layout.separator()
        layout.operator("fbp.popup_single_plane", text="Image Plane", icon=ui_icon("menu.image_plane"))
        op = layout.operator("fbp.popup_multiplane", text="Multiplane", icon=ui_icon("menu.multiplane"))
        op.animation = True
        layout.separator()
        layout.operator("fbp.create_color_plane_from_hex", text="Color Plane from Hex Color Code", icon=ui_icon("menu.hex"))
        layout.operator("fbp.import_single_image_from_clipboard", text="Single Plane from Clipboard", icon=ui_icon("menu.clipboard"))


# SECTION 11 - Native menus: Add / Context / Delete / Render #
# ###ICON Menu Render, Function: Background Render at the top of the Topbar.
def draw_fbp_image_add_menu(self, context):
    layout = self.layout
    layout.separator()
    layout.menu("FBP_MT_frame_by_plane_add", icon=ui_icon("menu.shift_a_root"))
def draw_fbp_object_context_menu(self, context):
    if get_selected_fbp_roots(context):
        self.layout.separator()
        self.layout.operator("fbp.set_selected_holdout", text="Set Selected as Holdout", icon=ui_icon("menu.holdout_plane"))
        self.layout.operator("fbp.holdout_all_except_selected", text="Holdout All Except Selected", icon=ui_icon("menu.holdout_plane"))
        self.layout.operator("fbp.restore_holdout_materials", text="Restore Frame by Plane Holdouts", icon=ui_icon("menu.holdout_plane"))
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
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    _FBP_REGISTERED_MENU_CALLBACKS.clear()


def _fbp_register_menu_callback(menu_cls, callback, method='append'):
    if not menu_cls:
        return False
    try:
        getattr(menu_cls, method)(callback)
        _FBP_REGISTERED_MENU_CALLBACKS.append((menu_cls, callback))
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
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
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
