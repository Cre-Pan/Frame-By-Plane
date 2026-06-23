"""Focused Frame by Plane operator module."""

import bpy
from bpy.props import (
    BoolProperty,
    IntProperty,
    StringProperty,
    EnumProperty,
)
from bpy.types import Operator

from .constants import fbp_icon
from .effects_registry import FBP_EFFECT_CLIPPING_MASK, fbp_effect_definition
from .path_utils import natural_sort_key
from .builder import apply_fit_to_camera
from .layers import (
    _safe_layer_obj,
    collection_is_hidden_in_view_layer,
    ensure_object_in_active_collection,
    fbp_active_layer_index,
    fbp_clipping_source_map,
    fbp_layer_backend_type,
    fbp_layer_depth_value_from_cache,
    fbp_make_depth_context_cache,
    find_layer_collection,
    get_primary_fbp_collection,
    get_selected_fbp_roots,
    get_selected_rigs,
    is_fbp_layer_object,
    iter_fbp_rigs_in_collection,
    iter_scene_fbp_rigs,
    object_in_view_layer,
    swap_layer_depth_only,
    update_global_visibility,
    visible_layer_indices,
)
from .scene_sync import delete_fbp_rigs, fbp_rename_layer_rig, sync_layer_collection
from .runtime import (
    FBP_DATA_ERRORS,
    FBP_DATA_IO_ERRORS,
    fbp_set_rna_property_silent,
    fbp_warn,
)
from .core import (
    do_update_animation,
    fbp_load_active_procedural_frame_to_rig,
    pending_collection_is_open,
    set_pending_collection_open,
)
from .operator_common import (
    _fbp_refresh_layer_tree,
    _fbp_refresh_pending_tree,
    _fbp_select_pending_index,
    fbp_jump_timeline_to_sequence_row,
)



class FBP_OT_RecreateObjectMaskHelper(Operator):
    bl_idname = "fbp.recreate_object_mask_helper"
    bl_label = "Recreate Shape Mask"
    bl_description = "Recreate and select the editable Shape Mask helper aligned to this layer"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(name="Layer", options={'SKIP_SAVE'})
    shape: EnumProperty(
        name="Shape",
        items=(
            ('SQUARE', "Square", "Editable square helper"),
            ('CIRCLE', "Circle", "Editable circular helper"),
            ('TRIANGLE', "Triangle", "Editable triangular helper"),
        ),
        default='SQUARE', options={'SKIP_SAVE'},
    )

    def execute(self, context):
        rig = bpy.data.objects.get(self.rig_name)
        if not rig or not is_fbp_layer_object(rig):
            return {'CANCELLED'}
        try:
            from .object_masks import remove_object_mask_helper, create_object_mask_helper
            remove_object_mask_helper(rig, self.shape)
            helper = create_object_mask_helper(rig, self.shape, context=context, select=True)
            if helper is None:
                return {'CANCELLED'}
            from .geometry_nodes import fbp_refresh_object_mask_binding
            effect_id = {
                'SQUARE': 'SQUARE_MASK',
                'CIRCLE': 'CIRCLE_MASK',
                'TRIANGLE': 'TRIANGLE_MASK',
            }[self.shape]
            fbp_refresh_object_mask_binding(rig, effect_id)
            return {'FINISHED'}
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not recreate Shape Mask helper", exc)
            return {'CANCELLED'}


class FBP_OT_EditObjectMaskHelper(Operator):
    bl_idname = "fbp.edit_object_mask_helper"
    bl_label = "Edit Shape Mask"
    bl_description = "Select the Shape Mask helper and enter Edit Mode so its vertices define the mask silhouette"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(name="Layer", options={'SKIP_SAVE'})
    shape: EnumProperty(
        name="Shape",
        items=(
            ('SQUARE', "Square", "Editable square helper"),
            ('CIRCLE', "Circle", "Editable circular helper"),
            ('TRIANGLE', "Triangle", "Editable triangular helper"),
        ),
        default='SQUARE', options={'SKIP_SAVE'},
    )

    def execute(self, context):
        rig = bpy.data.objects.get(self.rig_name)
        if not rig or not is_fbp_layer_object(rig):
            return {'CANCELLED'}
        try:
            from .object_masks import ensure_object_mask_helper
            helper = ensure_object_mask_helper(rig, self.shape, context=context, select=False)
            if helper is None or not object_in_view_layer(helper, context):
                self.report({'WARNING'}, "Shape Mask helper is not available in this View Layer")
                return {'CANCELLED'}
            if getattr(context, 'mode', 'OBJECT') != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.select_all(action='DESELECT')
            helper.hide_viewport = False
            helper.hide_set(False)
            helper.hide_select = False
            helper.select_set(True)
            context.view_layer.objects.active = helper
            bpy.ops.object.mode_set(mode='EDIT')
            # Shape helpers are edge-only cages. Force vertex selection so a
            # workspace left in Face Select does not make the editable shape
            # appear empty after the legacy face is removed.
            try:
                bpy.ops.mesh.select_mode(type='VERT')
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
            bpy.ops.mesh.select_all(action='SELECT')
            return {'FINISHED'}
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not enter Shape Mask Edit Mode", exc)
            return {'CANCELLED'}


class FBP_OT_ToggleClippingMask(Operator):
    bl_idname = "fbp.toggle_clipping_mask"
    bl_label = "Toggle Clipping Mask"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(name="Layer", options={'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        rig = bpy.data.objects.get(str(getattr(properties, "rig_name", "") or ""))
        if not rig:
            return "Clip this layer to the alpha of the physically lower layer in the same collection"
        try:
            definition = fbp_effect_definition(FBP_EFFECT_CLIPPING_MASK)
            enabled_key = str(definition.get("enabled_key", "fbp_effect_clipping_mask") or "fbp_effect_clipping_mask")
            enabled = bool(rig.get(enabled_key, False))
            source = getattr(rig, "fbp_clipping_mask_source", None)
            if enabled:
                source_name = str(getattr(source, "name", "") or "")
                if source_name:
                    return f"Disable Clipping Mask currently using {source_name} as its alpha source"
                return "Disable this Clipping Mask; its previous source is no longer available"
        except FBP_DATA_IO_ERRORS:
            pass
        return "Clip this layer to the alpha of the physically lower layer in the same collection; alphabetical sorting does not change the source"

    def execute(self, context):
        rig = bpy.data.objects.get(self.rig_name)
        if not rig or not is_fbp_layer_object(rig):
            return {'CANCELLED'}
        try:
            from .geometry_nodes import (
                fbp_add_effect,
                fbp_effect_is_active,
                fbp_remove_effect,
            )
            definition = fbp_effect_definition(FBP_EFFECT_CLIPPING_MASK)
            enabled_key = str(
                definition.get('enabled_key', 'fbp_effect_clipping_mask')
                or 'fbp_effect_clipping_mask'
            )
            stored_enabled = bool(rig.get(enabled_key, False))
            clipping_active = stored_enabled or fbp_effect_is_active(
                rig, FBP_EFFECT_CLIPPING_MASK
            )
            if clipping_active:
                # fbp_remove_effect also clears stale enabled metadata when an
                # older file lost its shader node but kept the feature flag.
                if not fbp_remove_effect(rig, FBP_EFFECT_CLIPPING_MASK):
                    return {'CANCELLED'}
                self.report({'INFO'}, "Clipping Mask disabled")
                return {'FINISHED'}

            collection = get_primary_fbp_collection(rig)
            scoped_rigs = tuple(
                iter_fbp_rigs_in_collection(collection, recursive=False)
            ) if collection else (rig,)
            source = fbp_clipping_source_map(
                context,
                rigs=scoped_rigs,
                collections=(collection,) if collection else None,
            ).get(rig)
            if source is None:
                self.report({'WARNING'}, "This layer has no layer directly below it in the same collection")
                return {'CANCELLED'}
            if fbp_layer_backend_type(source) not in {
                'NATIVE_IMAGE', 'NATIVE_SEQUENCE', 'NATIVE_MOVIE', 'CUTOUT'
            }:
                self.report({'WARNING'}, "The layer below has no image alpha available for clipping")
                return {'CANCELLED'}

            previous_source = getattr(rig, 'fbp_clipping_mask_source', None)
            # Bind the source before creating the shader node. This prevents a
            # transient unbound mask and lets initial socket synchronization use
            # the correct alpha source immediately.
            fbp_set_rna_property_silent(
                rig, 'fbp_clipping_mask_source', source
            )
            if not fbp_add_effect(rig, FBP_EFFECT_CLIPPING_MASK):
                fbp_set_rna_property_silent(
                    rig, 'fbp_clipping_mask_source', previous_source
                )
                self.report({'WARNING'}, "Could not add Clipping Mask")
                return {'CANCELLED'}
            self.report({'INFO'}, f"Clipped to {source.name}")
            return {'FINISHED'}
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not toggle Clipping Mask", exc)
            return {'CANCELLED'}


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
    bl_label = "Select Linked Plane"
    bl_description = "Unlock and select all mesh planes belonging to this rig; click again to lock them"
    bl_options = {'UNDO'}

    rig_name: StringProperty(name="Rig", description="Frame by Plane rig whose child planes should be selected")

    def execute(self, context):
        rig = bpy.data.objects.get(self.rig_name)
        if not rig:
            return {'CANCELLED'}

        planes = []
        linked = getattr(rig, 'fbp_plane_target', None)
        if linked and getattr(linked, 'type', '') == 'MESH':
            planes.append(linked)
        try:
            descendants = list(rig.children_recursive)
        except (AttributeError, ReferenceError):
            descendants = list(getattr(rig, 'children', ()) or ())
        for child in descendants:
            if getattr(child, 'type', '') != 'MESH' or child in planes:
                continue
            if bool(getattr(child, 'is_fbp_plane', False)) or child.parent == rig:
                planes.append(child)
        planes = [plane for plane in planes if object_in_view_layer(plane, context)]

        if not planes:
            self.report({'WARNING'}, "This layer has no linked mesh plane")
            return {'CANCELLED'}

        # Locked is the default state. Clicking Select Plane unlocks and selects
        # every child mesh. Clicking again restores the lock and the rig selection.
        unlock_and_select = all(bool(getattr(plane, 'hide_select', True)) for plane in planes)
        try:
            if unlock_and_select:
                bpy.ops.object.select_all(action='DESELECT')
                for plane in planes:
                    plane.hide_select = False
                    plane.select_set(True)
                context.view_layer.objects.active = planes[0]
            else:
                for plane in planes:
                    plane.select_set(False)
                    plane.hide_select = True
                if object_in_view_layer(rig, context) and not bool(getattr(rig, 'hide_select', False)):
                    rig.select_set(True)
                    context.view_layer.objects.active = rig
        except ReferenceError:
            return {'CANCELLED'}
        except Exception as exc:
            fbp_warn("Could not select linked planes", exc)
            return {'CANCELLED'}
        return {'FINISHED'}


class FBP_OT_SelectCollectionPlanes(Operator):
    bl_idname = "fbp.select_collection_planes"
    bl_label = "Toggle Collection Plane Selectability"
    bl_description = "Allow or prevent direct viewport selection of all linked image/color planes in this Frame by Plane collection"
    bl_options = {'UNDO'}

    collection_name: StringProperty(description="Name of the Blender or pending setup collection targeted by this action.", default="")

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

class FBP_OT_UIListNameAction(Operator):
    bl_idname = "fbp.ui_list_name_action"
    bl_label = "Select or Rename Item"
    bl_description = "Click to select, double-click to rename, or right-click for contextual actions"
    bl_options = {'REGISTER', 'UNDO'}

    target_type: StringProperty(description="Internal Frame By Plane value used for target type in operator_layers. It is managed by the add-on and normally should not be edited directly.", default="")
    rig_name: StringProperty(description="Name of the Frame By Plane control rig targeted by this action. Stored only long enough to resolve the object safely.", default="")
    collection_name: StringProperty(description="Name of the Blender or pending setup collection targeted by this action.", default="")
    index: IntProperty(description="Zero-based index of the frame, drawing, layer or setup entry targeted by this action.", default=-1)
    tree_index: IntProperty(description="Index of the flattened UI tree row targeted by this action.", default=-1)
    rename_mode: BoolProperty(description="Open inline rename behavior instead of performing the normal single-click selection action.", default=False, options={'HIDDEN', 'SKIP_SAVE'})
    new_name: StringProperty(description="New name that will replace the current visible name while preserving Frame By Plane internal links and identities.", name="Name", default="")

    def _current_name(self, context):
        if self.target_type == 'LAYER':
            rig = bpy.data.objects.get(self.rig_name)
            return getattr(rig, 'name', '') if rig else ''
        if self.target_type == 'FRAME':
            rig = bpy.data.objects.get(self.rig_name)
            if rig and 0 <= self.index < len(rig.fbp_images):
                return rig.fbp_images[self.index].name
            return ''
        if self.target_type == 'PENDING':
            if 0 <= self.index < len(context.scene.fbp_pending_planes):
                return context.scene.fbp_pending_planes[self.index].name
            return ''
        if self.target_type == 'COLLECTION':
            return self.collection_name
        if self.target_type == 'PENDING_GROUP':
            return self.collection_name.rsplit(' / ', 1)[-1]
        return ''

    def invoke(self, context, event):
        # Context-menu Rename sets rename_mode before invoking this operator;
        # double-click remains the direct UIList shortcut.
        if bool(getattr(self, 'rename_mode', False)) or getattr(event, 'value', '') == 'DOUBLE_CLICK':
            # Keep the row/object selection in sync before opening the rename
            # field. This is especially important for layers: the user can
            # double-click an unselected row and immediately edit that layer.
            if self.target_type in {'LAYER', 'FRAME', 'COLLECTION', 'PENDING', 'PENDING_GROUP'}:
                self._select(context)
            self.rename_mode = True
            self.new_name = self._current_name(context)
            return context.window_manager.invoke_props_dialog(self, width=360)
        self.rename_mode = False
        return self.execute(context)

    def draw(self, context):
        self.layout.prop(self, 'new_name', text='Name')

    def _rename(self, context):
        new_name = str(self.new_name or '').strip()
        if not new_name:
            self.report({'WARNING'}, "Name cannot be empty")
            return {'CANCELLED'}

        if self.target_type == 'LAYER':
            rig = bpy.data.objects.get(self.rig_name)
            if not rig or not is_fbp_layer_object(rig):
                return {'CANCELLED'}
            actual_name = fbp_rename_layer_rig(rig, new_name, context)
            if not actual_name:
                return {'CANCELLED'}
            if actual_name != new_name:
                self.report({'INFO'}, f"Layer renamed to {actual_name}")
            return {'FINISHED'}

        if self.target_type == 'FRAME':
            rig = bpy.data.objects.get(self.rig_name)
            if not rig or not (0 <= self.index < len(rig.fbp_images)):
                return {'CANCELLED'}
            rig.fbp_images[self.index].name = new_name
            return {'FINISHED'}

        if self.target_type == 'PENDING':
            if not (0 <= self.index < len(context.scene.fbp_pending_planes)):
                return {'CANCELLED'}
            context.scene.fbp_pending_planes[self.index].name = new_name
            _fbp_refresh_pending_tree(context)
            return {'FINISHED'}

        if self.target_type == 'COLLECTION':
            coll = bpy.data.collections.get(self.collection_name)
            if not coll:
                return {'CANCELLED'}
            old_name = coll.name
            coll.name = new_name
            # Only Frame by Plane rigs and their linked planes can carry this
            # cached collection name. Avoid scanning every Object in large files.
            for obj in iter_scene_fbp_rigs(context.scene):
                try:
                    if getattr(obj, 'fbp_collection_name', '') == old_name:
                        obj.fbp_collection_name = coll.name
                    plane = getattr(obj, 'fbp_plane_target', None)
                    if plane and getattr(plane, 'fbp_collection_name', '') == old_name:
                        plane.fbp_collection_name = coll.name
                except FBP_DATA_IO_ERRORS:
                    pass
            _fbp_refresh_layer_tree(context)
            return {'FINISHED'}

        if self.target_type == 'PENDING_GROUP':
            old_path = self.collection_name
            parent = old_path.rsplit(' / ', 1)[0] if ' / ' in old_path else ''
            new_path = f"{parent} / {new_name}" if parent else new_name
            for item in context.scene.fbp_pending_planes:
                path = str(getattr(item, 'collection_name', '') or '')
                if path == old_path or path.startswith(old_path + ' / '):
                    item.collection_name = new_path + path[len(old_path):]
            _fbp_refresh_pending_tree(context)
            return {'FINISHED'}

        return {'CANCELLED'}

    def _select(self, context):
        if self.target_type == 'LAYER':
            rig = bpy.data.objects.get(self.rig_name)
            if not rig or not is_fbp_layer_object(rig):
                return {'CANCELLED'}
            if not object_in_view_layer(rig, context) and not ensure_object_in_active_collection(rig, context):
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
            if self.tree_index >= 0:
                context.scene.fbp_layer_tree_rows_idx = self.tree_index
            return {'FINISHED'}

        if self.target_type == 'FRAME':
            rig = bpy.data.objects.get(self.rig_name)
            if not rig or not (0 <= self.index < len(rig.fbp_images)):
                return {'CANCELLED'}
            for i, item in enumerate(rig.fbp_images):
                item.is_selected = (i == self.index)
            rig.fbp_images_index = self.index
            fbp_jump_timeline_to_sequence_row(context, rig, self.index)
            if object_in_view_layer(rig, context):
                bpy.ops.object.select_all(action='DESELECT')
                rig.select_set(True)
                context.view_layer.objects.active = rig
            if getattr(rig, 'fbp_is_color_plane', False):
                fbp_load_active_procedural_frame_to_rig(rig)
            do_update_animation(rig)
            return {'FINISHED'}

        if self.target_type == 'PENDING':
            _fbp_select_pending_index(context, self.index)
            if self.tree_index >= 0:
                context.scene.fbp_pending_tree_rows_idx = self.tree_index
            return {'FINISHED'}

        if self.target_type == 'COLLECTION':
            coll = bpy.data.collections.get(self.collection_name)
            if not coll:
                return {'CANCELLED'}
            try:
                bpy.ops.object.select_all(action='DESELECT')
                selected = []
                for rig in iter_fbp_rigs_in_collection(coll, True):
                    if not object_in_view_layer(rig, context):
                        continue
                    rig.select_set(True)
                    selected.append(rig)
                if selected:
                    context.view_layer.objects.active = selected[-1]
                    selected_keys = {int(rig.as_pointer()) for rig in selected}
                    for i, item in enumerate(context.scene.fbp_layers):
                        rig = _safe_layer_obj(item)
                        if rig and int(rig.as_pointer()) in selected_keys:
                            context.scene.fbp_layer_stack_index = i
                            break
            except FBP_DATA_IO_ERRORS:
                pass
            if self.tree_index >= 0:
                context.scene.fbp_layer_tree_rows_idx = self.tree_index
            return {'FINISHED'}

        if self.target_type == 'PENDING_GROUP':
            if self.tree_index >= 0:
                context.scene.fbp_pending_tree_rows_idx = self.tree_index
            return {'FINISHED'}

        return {'CANCELLED'}

    def execute(self, context):
        return self._rename(context) if self.rename_mode else self._select(context)

class FBP_OT_SelectLayerExclusive(Operator):
    bl_idname      = "fbp.select_layer_exclusive"
    bl_label       = "Select Layer"
    bl_description = "Select only this layer. Use the checkbox for additive multi-selection"
    bl_options     = {'UNDO'}

    rig_name: StringProperty(description="Name of the Frame By Plane control rig targeted by this action. Stored only long enough to resolve the object safely.", default="")

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
        if get_selected_fbp_roots(context):
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

    rig_name: StringProperty(description="Name of the Frame By Plane control rig targeted by this action. Stored only long enough to resolve the object safely.", default="")
    target:   StringProperty(description="Target component affected by this operation, such as the Frame By Plane rig or its linked plane.", default="RIG")
    shift:    BoolProperty(description="Whether the action was invoked with Shift to apply it additively or to all currently selected Frame By Plane layers.", default=False)

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

    rig_name: StringProperty(description="Name of the Frame By Plane control rig targeted by this action. Stored only long enough to resolve the object safely.")

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

    rig_name: StringProperty(description="Name of the Frame By Plane control rig targeted by this action. Stored only long enough to resolve the object safely.")

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
                    fbp_set_rna_property_silent(item.obj, 'fbp_is_visible', False)
            target_item.solo = True
            if target_item.obj:
                fbp_set_rna_property_silent(target_item.obj, 'fbp_is_visible', True)
        elif len(active_items) == 1 and target_item.solo:
            for item in sc.fbp_layers:
                item.solo = False
                if item.obj:
                    fbp_set_rna_property_silent(item.obj, 'fbp_is_visible', True)
        else:
            target_item.solo = not target_item.solo
            if target_item.obj:
                fbp_set_rna_property_silent(
                    target_item.obj,
                    'fbp_is_visible',
                    target_item.solo,
                )

        if not any(item.solo for item in sc.fbp_layers):
            for item in sc.fbp_layers:
                if item.obj:
                    fbp_set_rna_property_silent(item.obj, 'fbp_is_visible', True)

        update_global_visibility(context)
        _fbp_refresh_layer_tree(context)
        return {'FINISHED'}

class FBP_OT_MoveLayerStack(Operator):
    bl_idname      = "fbp.move_layer_stack"
    bl_label       = "Move Layer"
    bl_description = "Move this layer one camera-depth step and return the Layers list to physical depth order"

    direction: StringProperty(description="Requested movement or step direction for this action, such as previous, next, up or down.")
    rig_name: StringProperty(
        name="Layer",
        description="Optional exact layer target used by context-menu actions",
        default="",
        options={'SKIP_SAVE'},
    )

    def execute(self, context):
        if self.direction not in {'UP', 'DOWN'}:
            self.report({'ERROR'}, 'Unknown layer movement direction')
            return {'CANCELLED'}

        sc = context.scene
        layers = sc.fbp_layers
        idx = fbp_active_layer_index(sc)
        current_rig = None

        exact_target = bpy.data.objects.get(str(getattr(self, 'rig_name', '') or ''))
        if exact_target and is_fbp_layer_object(exact_target):
            current_rig = exact_target
            idx = -1
            for candidate, item in enumerate(layers):
                if _safe_layer_obj(item) == exact_target:
                    idx = candidate
                    break
        else:
            selected_roots = get_selected_fbp_roots(context)
            if len(selected_roots) > 1:
                self.report({'WARNING'}, 'Select a single layer before moving it')
                return {'CANCELLED'}
            if selected_roots:
                current_rig = selected_roots[0]
                for candidate, item in enumerate(layers):
                    if _safe_layer_obj(item) == current_rig:
                        idx = candidate
                        break
            elif 0 <= idx < len(layers):
                current_rig = _safe_layer_obj(layers[idx])

        if not current_rig or not (0 <= idx < len(layers)):
            return {'CANCELLED'}
        collection = get_primary_fbp_collection(current_rig)
        if collection is None:
            self.report({'WARNING'}, 'This layer is not inside a valid collection')
            return {'CANCELLED'}

        depth_context = fbp_make_depth_context_cache(context)
        visible_rigs = []
        for rig in iter_fbp_rigs_in_collection(collection, recursive=False):
            try:
                if get_primary_fbp_collection(rig) != collection:
                    continue
                try:
                    is_visible = bool(rig.visible_get(view_layer=context.view_layer))
                except TypeError:
                    is_visible = bool(rig.visible_get())
                if not is_visible:
                    continue
                visible_rigs.append(rig)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
        stable_order = {}
        for stable_index, layer_item in enumerate(layers):
            stable_rig = _safe_layer_obj(layer_item)
            if stable_rig is not None:
                stable_order[stable_rig] = stable_index
        display_order = sorted(
            visible_rigs,
            key=lambda rig: (
                fbp_layer_depth_value_from_cache(rig, depth_context),
                stable_order.get(rig, 1 << 30),
            ),
        )
        if current_rig not in display_order or len(display_order) < 2:
            self.report({'WARNING'}, 'No visible neighbour in this collection')
            return {'CANCELLED'}

        pos = display_order.index(current_rig)
        new_pos = pos - 1 if self.direction == 'UP' else pos + 1
        if not (0 <= new_pos < len(display_order)):
            return {'CANCELLED'}
        target_rig = display_order[new_pos]
        target_idx = stable_order.get(target_rig, -1)
        if target_idx < 0:
            return {'CANCELLED'}

        swap_layer_depth_only(
            context,
            current_rig,
            target_rig,
            depth_context=depth_context,
        )
        # Scene.fbp_layers is a runtime identity cache, not the visual stack.
        # Moving its entries would shift unrelated collections. Keep the active
        # rig at its stable cache index; the virtual tree redraws from depth.
        sc.fbp_layer_stack_index = idx
        if exact_target and object_in_view_layer(current_rig, context):
            try:
                bpy.ops.object.select_all(action='DESELECT')
                current_rig.select_set(True)
                context.view_layer.objects.active = current_rig
            except FBP_DATA_ERRORS:
                pass
        try:
            sc.fbp_sort_layers_alpha = False
        except FBP_DATA_IO_ERRORS:
            pass
        _fbp_refresh_layer_tree(context)
        try:
            from .geometry_nodes import fbp_sync_clipping_masks
            fbp_sync_clipping_masks(context, collections=(collection,))
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn('Could not refresh Clipping Masks after reordering', exc)
        return {'FINISHED'}


class FBP_OT_ReverseSelectedLayerOrder(Operator):
    bl_idname = 'fbp.reverse_selected_layer_order'
    bl_label = 'Reverse Selected Layer Order'
    bl_description = 'Reverse the depth order of selected layers inside each collection while leaving unselected layers in place'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected = [
            rig for rig in get_selected_fbp_roots(context)
            if is_fbp_layer_object(rig)
        ]
        if len(selected) < 2:
            self.report({'WARNING'}, 'Select at least two Frame By Plane layers')
            return {'CANCELLED'}

        groups = {}
        for rig in selected:
            collection = get_primary_fbp_collection(rig)
            if collection is None:
                continue
            try:
                key = int(collection.as_pointer())
            except FBP_DATA_IO_ERRORS:
                continue
            groups.setdefault(key, (collection, []))[1].append(rig)

        depth_context = fbp_make_depth_context_cache(context)
        stable_order = {}
        for stable_index, layer_item in enumerate(context.scene.fbp_layers):
            stable_rig = _safe_layer_obj(layer_item)
            if stable_rig is not None:
                stable_order[stable_rig] = stable_index
        changed_groups = 0
        affected_collections = []
        for collection, rigs in groups.values():
            if len(rigs) < 2:
                continue
            ordered = sorted(
                rigs,
                key=lambda rig: (
                    fbp_layer_depth_value_from_cache(rig, depth_context),
                    stable_order.get(rig, 1 << 30),
                ),
            )
            for left, right in zip(
                ordered[:len(ordered) // 2],
                reversed(ordered[(len(ordered) + 1) // 2:]),
            ):
                swap_layer_depth_only(
                    context,
                    left,
                    right,
                    depth_context=depth_context,
                )
            changed_groups += 1
            affected_collections.append(collection)

        if not changed_groups:
            self.report({'WARNING'}, 'Select at least two layers inside the same collection')
            return {'CANCELLED'}

        try:
            context.scene.fbp_sort_layers_alpha = False
        except FBP_DATA_IO_ERRORS:
            pass
        _fbp_refresh_layer_tree(context)
        try:
            from .geometry_nodes import fbp_sync_clipping_masks
            fbp_sync_clipping_masks(
                context,
                collections=tuple(affected_collections),
            )
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn('Could not refresh Clipping Masks after reversing layer order', exc)
        self.report({'INFO'}, f"Reversed selected layer order in {changed_groups} collection(s)")
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
        all_rigs = list(iter_scene_fbp_rigs(context.scene))
        visible_rigs = [ob for ob in all_rigs if getattr(ob, "fbp_is_visible", False)]
        is_solo = set(visible_rigs) == set(selected_rigs)
        for rig in all_rigs:
            fbp_set_rna_property_silent(
                rig,
                'fbp_is_visible',
                True if is_solo else (rig in selected_rigs),
            )
        update_global_visibility(context)
        return {'FINISHED'}

class FBP_OT_PopupGenerateCamera(Operator):
    bl_idname = "fbp.popup_generate_camera"
    bl_label = "Generate Camera"
    bl_description = "Enable camera generation and choose the camera/output ratio for the next generated project"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        sc = context.scene
        sc.fbp_gen_camera = True
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        sc = context.scene
        layout = self.layout
        box = layout.box()
        box.label(text="Camera Generation", icon=fbp_icon("VIEW_CAMERA"))
        box.prop(sc, "fbp_gen_camera", text="Generate Camera", toggle=True)
        box.prop(sc, "fbp_camera_projection", text="Projection")
        if sc.fbp_camera_projection == 'ORTHO':
            box.prop(sc, "fbp_camera_ortho_scale", text="Orthographic Scale")
        else:
            box.prop(sc, "fbp_camera_lens", text="Lens (mm)")
        row = box.row(align=True)
        row.prop(sc, "fbp_camera_clip_start", text="Clip Start")
        row.prop(sc, "fbp_camera_clip_end", text="Clip End")
        box.prop(sc, "fbp_cam_ratio", text="Camera Ratio")
        if sc.fbp_cam_ratio == 'CUSTOM':
            row = box.row(align=True)
            row.prop(sc.render, "resolution_x", text="Width")
            row.prop(sc.render, "resolution_y", text="Height")
        row = box.row(align=True)
        row.prop(sc, "fbp_cam_pivot", text="3D Cursor on Camera", toggle=True, icon=fbp_icon("PIVOT_CURSOR"))
        row.prop(sc, "fbp_auto_scale", text="Fit Layers", toggle=True, icon=fbp_icon("FULLSCREEN_ENTER"))
        layout.label(text="Defaults can be changed in Add-on Preferences.", icon=fbp_icon("INFO"))

    def execute(self, context):
        context.scene.fbp_gen_camera = True
        return {'FINISHED'}

class FBP_OT_FitToCamera(Operator):
    bl_idname      = "fbp.fit_camera"
    bl_label       = "Fit to Camera"
    bl_description = "Fit the real image rectangle inside the active camera"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        cam = context.scene.camera
        if not cam:
            self.report({'WARNING'}, "No active camera!")
            return {'CANCELLED'}
        rigs = get_selected_rigs(context)
        if not rigs:
            return {'CANCELLED'}
        context.view_layer.update()
        context.evaluated_depsgraph_get().update()
        for rig in rigs:
            apply_fit_to_camera(context, rig, cam)
        return {'FINISHED'}

class FBP_OT_MultiFitCamera(Operator):
    bl_idname      = "fbp.multi_fit_camera"
    bl_label       = "Fit All to Camera"
    bl_description = "Fit all selected real image rectangles inside the active camera"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        cam = context.scene.camera
        if not cam:
            self.report({'WARNING'}, "No active camera!")
            return {'CANCELLED'}
        rigs = get_selected_rigs(context)
        if not rigs:
            self.report({'WARNING'}, "No rig selected!")
            return {'CANCELLED'}
        context.view_layer.update()
        context.evaluated_depsgraph_get().update()
        for rig in rigs:
            apply_fit_to_camera(context, rig, cam)
        self.report({'INFO'}, f"{len(rigs)} layer(s) fitted to camera")
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

class FBP_OT_ToggleCollectionCollapse(Operator):
    bl_idname      = "fbp.toggle_collection_collapse"
    bl_label       = "Collapse Collection"
    bl_description = "Open or collapse this collection in the Frame by Plane layer tree"
    bl_options     = {'UNDO'}

    collection_name: StringProperty(description="Name of the Blender or pending setup collection targeted by this action.", default="")

    def execute(self, context):
        coll = bpy.data.collections.get(self.collection_name)
        if not coll:
            return {'CANCELLED'}
        coll.fbp_collapsed = not coll.fbp_collapsed
        _fbp_refresh_layer_tree(context)
        return {'FINISHED'}

class FBP_OT_TogglePendingCollectionCollapse(Operator):
    bl_idname = "fbp.toggle_pending_collection_collapse"
    bl_label = "Open Setup Collection"
    bl_description = "Open or collapse this collection in the Multiplane Setup preview"
    bl_options = {'UNDO'}

    collection_name: StringProperty(description="Name of the Blender or pending setup collection targeted by this action.", default="")

    def execute(self, context):
        sc = context.scene
        name = self.collection_name or 'Unsorted'
        set_pending_collection_open(sc, name, not pending_collection_is_open(sc, name))
        _fbp_refresh_pending_tree(context)
        return {'FINISHED'}


class FBP_OT_SetPendingCollectionsOpen(Operator):
    bl_idname = "fbp.set_pending_collections_open"
    bl_label = "Expand or Collapse Setup Collections"
    bl_description = "Expand or collapse every collection in the Multiplane Setup tree"
    bl_options = {'UNDO'}

    open_all: BoolProperty(description="Expand every setup collection when enabled, or collapse every setup collection when disabled.", default=False)

    def execute(self, context):
        scene = context.scene
        if not self.open_all:
            scene.fbp_pending_open_collections = ""
            _fbp_refresh_pending_tree(context)
            return {'FINISHED'}

        paths = set()
        for item in getattr(scene, 'fbp_pending_planes', ()):
            raw = str(getattr(item, 'collection_name', '') or '').strip()
            if not raw:
                continue
            parts = [part.strip() for part in raw.split('/') if part.strip()]
            for depth in range(1, len(parts) + 1):
                paths.add(' / '.join(parts[:depth]))
        scene.fbp_pending_open_collections = '|'.join(sorted(paths, key=natural_sort_key))
        _fbp_refresh_pending_tree(context)
        return {'FINISHED'}

class FBP_OT_SelectCollectionLayers(Operator):
    bl_idname      = "fbp.select_collection_layers"
    bl_label       = "Toggle Collection Layer Selection"
    bl_description = "Select or deselect all Frame by Plane rig layers inside this collection. Shift-click adds/removes without clearing other selections"
    bl_options     = {'UNDO'}

    collection_name: StringProperty(description="Name of the Blender or pending setup collection targeted by this action.", default="")
    extend: BoolProperty(description="Add this collection to the current layer selection instead of replacing the existing selection.", default=False)

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

    collection_name: StringProperty(description="Name of the Blender or pending setup collection targeted by this action.", default="")

    def execute(self, context):
        coll = bpy.data.collections.get(self.collection_name)
        if not coll:
            return {'CANCELLED'}
        new_hidden = not collection_is_hidden_in_view_layer(context, coll)
        try:
            coll.hide_viewport = new_hidden
        except FBP_DATA_IO_ERRORS:
            pass
        try:
            layer_coll = find_layer_collection(context.view_layer.layer_collection, coll)
            if layer_coll:
                layer_coll.hide_viewport = new_hidden
        except FBP_DATA_IO_ERRORS:
            pass
        # Keep object-level visibility intact; the Collection is the parent switch.
        update_global_visibility(context)
        return {'FINISHED'}

class FBP_OT_ToggleCollectionLock(Operator):
    bl_idname      = "fbp.toggle_collection_lock"
    bl_label       = "Toggle Collection Lock"
    bl_description = "Lock/unlock all Frame by Plane rigs and planes inside this collection"
    bl_options     = {'UNDO'}

    collection_name: StringProperty(description="Name of the Blender or pending setup collection targeted by this action.", default="")

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

    collection_name: StringProperty(description="Name of the Blender or pending setup collection targeted by this action.", default="")

    def execute(self, context):
        coll = bpy.data.collections.get(self.collection_name)
        if not coll:
            return {'CANCELLED'}
        rigs = list(iter_fbp_rigs_in_collection(coll, True))
        deleted = delete_fbp_rigs(context, rigs)
        self.report({'INFO'}, f"Deleted {deleted} layer(s) from {coll.name}")
        return {'FINISHED'} if deleted else {'CANCELLED'}
