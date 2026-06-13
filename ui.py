"""Panels, UILists, Shift+A menu entries and render menu hooks."""

import os

import bpy
from bpy.types import Panel, UIList, Menu

from .core import (
    draw_native_fbp_color_ramp,
    fbp_collection_icon,
    fbp_collection_color_icon,
    fbp_collection_plane_icon,
    fbp_collection_rows_are_disabled,
    fbp_collection_select_icon,
    fbp_color_plane_can_have_frames,
    fbp_color_plane_type_icon,
    fbp_layer_depth_value_from_cache,
    fbp_layer_row_type_icon,
    fbp_make_depth_context_cache,
    fbp_mask_icon,
    fbp_procedural_kind_for_item,
    fbp_procedural_kind_from_material,
    fbp_rig_native_sequence_needs_rename,
    fbp_select_plane_icon,
    fbp_select_rig_icon,
    fbp_sequence_index_at_frame,
    fbp_set_ui_units_x,
    fbp_strip_icon,
    fbp_warn,
    get_layer_item_for_rig,
    get_primary_fbp_collection,
    get_selected_fbp_roots,
    get_selected_rigs,
    is_fbp_layer_object,
    is_layer_item_visible_in_collections,
    load_preview,
    natural_sort_key,
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
            chip_a = chips.row(align=False); fbp_set_ui_units_x(chip_a, 1.0)
            chip_a.prop(item, 'preview_color_a', text='')
            chip_b = chips.row(align=False); fbp_set_ui_units_x(chip_b, 1.0)
            chip_b.prop(item, 'preview_color_b', text='')
            return
        if kind == 'HOLDOUT':
            chips.label(text='', icon=ui_icon('menu.holdout_plane'))
            return
        chip = chips.row(align=False); fbp_set_ui_units_x(chip, 2.0)
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

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
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

            # ###ICON Panel Layer Stack UIList, Function Collection Visibility: layer.visible_on / layer.visible_off
            vis_icon = ui_icon('layer.visible_on') if getattr(coll, 'fbp_collection_visible', True) else ui_icon('layer.visible_off')
            left.prop(coll, 'fbp_collection_visible', text='', icon=vis_icon, icon_only=True, emboss=False)

            # Indentation stays after the eye, as requested.
            for _ in range(depth):
                left.label(text='', icon=ui_icon('generic.blank'))

            # ###ICON Panel Layer Stack UIList, Function Collection Collapse: setup.collapsed / setup.expanded
            fold_icon = ui_icon('setup.collapsed') if bool(getattr(coll, 'fbp_collapsed', False)) else ui_icon('setup.expanded')
            op = left.operator('fbp.toggle_collection_collapse', text='', icon=fold_icon, emboss=False)
            op.collection_name = coll.name

            try:
                left.active = not fbp_collection_rows_are_disabled(coll, context)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
            left.alignment = 'LEFT'
            left.label(text='', icon=fbp_collection_icon(coll))
            op_sel = left.operator('fbp.ui_list_name_action', text=coll.name, emboss=False)
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

        # ###ICON Panel Layer Stack UIList, Function Layer Visibility: layer.visible_on / layer.visible_off
        vis_icon = ui_icon('layer.visible_on') if getattr(rig, 'fbp_is_visible', True) else ui_icon('layer.visible_off')
        left.prop(rig, 'fbp_is_visible', text='', icon=vis_icon, icon_only=True, emboss=False)

        for _ in range(depth):
            left.label(text='', icon=ui_icon('generic.blank'))

        # Placeholder aligns layers under the collection arrow column.
        left.label(text='', icon=ui_icon('generic.blank'))

        try:
            left.active = bool(getattr(rig, 'fbp_is_visible', True)) and not bool(layer_item.rig_locked)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        left.alignment = 'LEFT'
        fbp_draw_layer_tag_and_preview(left, rig, context)
        op_name = left.operator('fbp.ui_list_name_action', text=rig.name, icon=ui_icon('sequence.normal_frame'), emboss=False)
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
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
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
        filter_collection = getattr(context.scene, 'fbp_pending_filter_collection', '')
        flags = []
        order = list(range(len(items)))
        if getattr(context.scene, 'fbp_sort_layers_alpha', False):
            order.sort(key=lambda i: natural_sort_key(getattr(items[i], 'collection_name', '') + ' / ' + getattr(items[i], 'name', '')))
        for item in items:
            coll_name = getattr(item, 'collection_name', '') or 'Unsorted'
            flags.append(self.bitflag_filter_item if (not filter_collection or coll_name == filter_collection) else 0)
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
        # ###ICON Panel Multiplane Setup, Function Main Folder as Scene: setup.scene
        # ###ICON Panel Multiplane Setup, Function Folder/Collection: setup.folder
        # ###ICON Panel Multiplane Setup, Function Sequence: setup.sequence
        # ###ICON Panel Multiplane Setup, Function Static Image: setup.image
        if parts:
            if getattr(context.scene, 'fbp_import_main_folders_as_scenes', False):
                return ui_icon('setup.scene')
            return ui_icon('setup.folder')
        return ui_icon('setup.sequence') if file_count > 1 else ui_icon('setup.image')

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
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

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
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

            # Scene roots keep the scene icon. Real leaf collections expose the
            # same editable colored collection selector used by Blender's Outliner.
            is_scene = bool(getattr(item, 'is_scene', False))
            has_children = int(getattr(item, 'child_count', 0)) > 0
            color_editable = bool(getattr(item, 'collection_color_editable', True))
            if is_scene:
                row.label(text='', icon=ui_icon('setup.scene'))
            elif has_children or not color_editable:
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

# SECTION 05 - Panel: Settings / Project / Render #
# ###ICON Panel Settings, Functions: project folder, import, maintenance, render, stats.
class FBP_PT_Settings(Panel):
    bl_label       = "Settings"
    bl_description = "Project import, output format, diagnostics and background render settings"
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
        tabs.prop_enum(sc, "fbp_settings_section", 'PROJECT', text="Project", icon=ui_icon("settings.import_project"))
        tabs.prop_enum(sc, "fbp_settings_section", 'MAINTENANCE', text="Maintenance", icon=ui_icon("settings.repair"))
        tabs.prop_enum(sc, "fbp_settings_section", 'RENDER', text="Render", icon=ui_icon("settings.render"))
        tabs.prop_enum(sc, "fbp_settings_section", 'DISPLAY', text="Display", icon=ui_icon("settings.header"))

        layout.separator()
        section = getattr(sc, 'fbp_settings_section', 'PROJECT')

        if section == 'PROJECT':
            box = layout.box()
            box.label(text="Project Import", icon=ui_icon("settings.import_project"))
            box.prop(sc, "fbp_project_path", text="")
            row = box.row(align=True)
            row.prop(sc, "fbp_import_main_folders_as_scenes", text="Main Folders as Separate Scenes", toggle=True)
            row = box.row(align=True)
            row.operator("fbp.scan_project_to_setup", icon=ui_icon("settings.import_project"), text="Import Project")
            row.operator("fbp.auto_scene_builder", icon=ui_icon("settings.build_direct"), text="Build Direct")

        elif section == 'MAINTENANCE':
            box = layout.box()
            box.label(text="Maintenance / Diagnostics", icon=ui_icon("settings.repair"))
            row = box.row(align=True)
            row.operator("fbp.relink_from_project_root", icon=ui_icon("settings.relink"), text="Relink Missing")
            row.operator("fbp.select_missing_layers", icon=ui_icon("generic.error"), text="Select Missing")
            row = box.row(align=True)
            row.operator("fbp.project_health_check", icon=ui_icon("settings.health"), text="Health Check")
            row.operator("fbp.show_import_profile", icon=ui_icon("settings.profile"), text="Import Report")
            box.operator("fbp.rename_sequence_for_blender", icon=ui_icon("sequence.replace"), text="Rename Sequence Files")
            row = box.row(align=True)
            row.prop(sc, "fbp_auto_collection_color_variants", text="Color Variants", toggle=True)
            row.prop(sc, "fbp_auto_clean_orphans", text="Auto-clean Orphans", toggle=True)

        elif section == 'RENDER':
            box = layout.box()
            box.label(text="Background Render", icon=ui_icon("settings.render"))
            row = box.row(align=True)
            row.prop(sc, "fbp_emergency_render_start", text="Start")
            row.prop(sc, "fbp_emergency_render_end", text="End")
            box.prop(sc, "fbp_emergency_render_prefix", text="Prefix")
            row = box.row(align=True)
            row.operator("fbp.repair_render_state", icon=ui_icon("settings.repair"), text="Repair")
            if getattr(sc, 'fbp_background_render_running', False):
                row.operator("fbp.stop_background_render", icon='CANCEL', text="Stop Render")
            else:
                row.operator("fbp.background_render_frames", icon=ui_icon("settings.render"), text="Background Render")
            if getattr(sc, 'fbp_background_render_running', False) or int(getattr(sc, 'fbp_background_render_total', 0) or 0) > 0:
                status_box = box.box()
                status_box.label(text=getattr(sc, 'fbp_background_render_status', 'Idle'), icon='RENDER_ANIMATION')
                total = int(getattr(sc, 'fbp_background_render_total', 0) or 0)
                progress = int(getattr(sc, 'fbp_background_render_progress', 0) or 0)
                if total > 0:
                    status_box.label(text=f"Rendered: {progress}/{total} · Remaining: {max(0, total - progress)}")
                status_box.operator("fbp.background_render_status", icon='INFO', text="Open Status")

        else:
            box = layout.box()
            box.label(text="Output and Display", icon=ui_icon("settings.header"))
            box.prop(sc, "fbp_cam_ratio", text="Ratio")
            if sc.fbp_cam_ratio == 'CUSTOM':
                col = box.column(align=True)
                col.prop(sc.render, "resolution_x", text="X (px)")
                col.prop(sc.render, "resolution_y", text="Y (px)")
            row = box.row(align=True)
            row.prop(sc, "fbp_show_previews", text="Show Thumbnails", toggle=True)
            row.prop(sc, "fbp_show_color_previews", text="Show Color Preview", toggle=True)

        layout.separator()
        layout.operator("fbp.save_file", text="Save Project", icon=ui_icon("settings.save"))

        selected_rigs = get_selected_rigs(context)
        if selected_rigs:
            box = layout.box()
            box.label(text="Stats", icon=ui_icon("generic.info"))
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
                col.label(text=f"⚠ {missing_count} Missing Files!", icon=ui_icon("generic.error"))


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
        return any(is_fbp_layer_object(obj) for obj in context.scene.objects)

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


# SECTION 07 - Panel: Sequence / Selected Layer #
# ###ICON Panel Sequence, Functions: replace, visibility, emission, fit, transform, crop, extend, frames.
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

        tools = layout.box()
        tools.label(text="Floating Tools", icon=ui_icon("settings.repair"))
        row = tools.row(align=True)
        crop_active = any(
            any(abs(float(getattr(_r, prop, 0.0) or 0.0)) > 1e-6 for prop in (
                'fbp_crop_top', 'fbp_crop_left', 'fbp_crop_right', 'fbp_crop_bottom',
            )) for _r in selected_rigs
        )
        extend_active = any(
            any(abs(float(getattr(_r, prop, 0.0) or 0.0)) > 1e-6 for prop in (
                'fbp_extend_top', 'fbp_extend_left', 'fbp_extend_right', 'fbp_extend_bottom',
            )) for _r in selected_rigs
        )
        row.operator("fbp.popup_crop", text="Crop", icon=ui_icon("sequence.edges"), depress=crop_active)
        row.operator("fbp.popup_extend", text="Extend", icon=ui_icon("sequence.fit"), depress=extend_active)

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
                    # Icons only inverted: function/order stays MOVE_UP then MOVE_DOWN.
                    col.operator("fbp.list_action", icon=ui_icon("generic.down"), text="").action = 'MOVE_UP'
                    col.operator("fbp.list_action", icon=ui_icon("generic.up"), text="").action = 'MOVE_DOWN'
                    col.separator()
                    if getattr(rig, "fbp_is_color_plane", False):
                        op = col.operator("fbp.insert_images_after_selected", icon=ui_icon("menu.color_plane"), text="")
                        op.frame_mode = 'COLOR'
                        op = col.operator("fbp.insert_images_after_selected", icon=ui_icon("menu.gradient_plane"), text="")
                        op.frame_mode = 'GRADIENT'
                    else:
                        col.operator("fbp.insert_linked_image_after_selected", icon=ui_icon("settings.project_folder"), text="")
                    col.separator()
                    col.operator("fbp.split_selected_images_to_new_plane", icon=ui_icon("sequence.split"), text="")
                    col.operator("fbp.list_action", icon=ui_icon("layer.sort_alpha"), text="").action = 'SORT_NATURAL'
                    col.operator("fbp.list_action", icon=ui_icon("layer.duplicate"), text="").action = 'DUPLICATE_SELECTED'
                    col.operator("fbp.list_action", icon=ui_icon("generic.delete"), text="").action = 'REMOVE'

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


# SECTION 08 - Panel: Initial Create #
# ###ICON Panel Create, Function: first setup when no FBP rigs exist.
class FBP_PT_CreateFirst(Panel):
    bl_label       = "Create"
    bl_description = "Create image planes, procedural planes and multiplane setups"
    bl_idname      = "FBP_PT_create_first"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "Frame by Plane"
    bl_order       = 3

    @classmethod
    def poll(cls, context):
        return not any(getattr(obj, "is_fbp_control", False) for obj in context.scene.objects)

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
    bl_order       = 4

    @classmethod
    def poll(cls, context):
        return (any(getattr(obj, "is_fbp_control", False) for obj in context.scene.objects)
                and getattr(context.scene, "fbp_show_create_tools", False))

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
    """Return the modern Topbar Render menu, with a legacy fallback for old local installs."""
    return getattr(bpy.types, "TOPBAR_MT_render", None) or getattr(bpy.types, "INFO_MT_render", None)


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
