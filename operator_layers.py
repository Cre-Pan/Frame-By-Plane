"""Focused Frame by Plane operator module."""

try:
    from .operator_common import *
except ImportError:
    from operator_common import *


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
    bl_label = "Toggle Linked Plane Selectability"
    bl_description = "Allow or prevent direct viewport selection of the linked image/color plane. Planes are locked by default"
    bl_options = {'UNDO'}

    rig_name: StringProperty(name="Rig", description="Frame by Plane rig whose linked plane selectability should be toggled")

    def execute(self, context):
        rig = bpy.data.objects.get(self.rig_name)
        plane = getattr(rig, 'fbp_plane_target', None) if rig else None
        if not plane:
            self.report({'WARNING'}, "This layer has no linked plane")
            return {'CANCELLED'}
        try:
            plane.hide_select = not bool(plane.hide_select)
            if plane.hide_select and plane.select_get():
                plane.select_set(False)
                if rig and object_in_view_layer(rig, context):
                    rig.select_set(True)
                    context.view_layer.objects.active = rig
        except ReferenceError:
            return {'CANCELLED'}
        except Exception as exc:
            fbp_warn("Could not toggle linked plane selectability", exc)
            return {'CANCELLED'}
        return {'FINISHED'}

class FBP_OT_SelectCollectionPlanes(Operator):
    bl_idname = "fbp.select_collection_planes"
    bl_label = "Toggle Collection Plane Selectability"
    bl_description = "Allow or prevent direct viewport selection of all linked image/color planes in this Frame by Plane collection"
    bl_options = {'UNDO'}

    collection_name: StringProperty(default="")

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
    bl_description = "Click to select this row; double-click to rename it"
    bl_options = {'REGISTER', 'UNDO'}

    target_type: StringProperty(default="")
    rig_name: StringProperty(default="")
    collection_name: StringProperty(default="")
    index: IntProperty(default=-1)
    tree_index: IntProperty(default=-1)
    rename_mode: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})
    new_name: StringProperty(name="Name", default="")

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
        if getattr(event, 'value', '') == 'DOUBLE_CLICK':
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
            if not rig:
                return {'CANCELLED'}
            rig.name = new_name
            _fbp_refresh_layer_tree(context)
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
            for obj in bpy.data.objects:
                try:
                    if getattr(obj, 'fbp_collection_name', '') == old_name:
                        obj.fbp_collection_name = coll.name
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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
                for other in bpy.data.collections:
                    if hasattr(other, 'fbp_collection_selected'):
                        other.fbp_collection_selected = False
                coll.fbp_collection_selected = True
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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

    rig_name: StringProperty(default="")

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

    rig_name: StringProperty(default="")
    target:   StringProperty(default="RIG")
    shift:    BoolProperty(default=False)

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

    rig_name: StringProperty()

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

    rig_name: StringProperty()

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
                    item.obj.fbp_is_visible = False
            target_item.solo = True
            if target_item.obj:
                target_item.obj.fbp_is_visible = True
        elif len(active_items) == 1 and target_item.solo:
            for item in sc.fbp_layers:
                item.solo = False
                if item.obj:
                    item.obj.fbp_is_visible = True
        else:
            target_item.solo = not target_item.solo
            if target_item.obj:
                target_item.obj.fbp_is_visible = target_item.solo

        if not any(item.solo for item in sc.fbp_layers):
            for item in sc.fbp_layers:
                if item.obj:
                    item.obj.fbp_is_visible = True

        update_global_visibility(context)
        _fbp_refresh_layer_tree(context)
        return {'FINISHED'}

class FBP_OT_MoveLayerStack(Operator):
    bl_idname      = "fbp.move_layer_stack"
    bl_label       = "Move Layer"
    bl_description = "Move this layer and recalculate depth automatically"

    direction: StringProperty()

    def execute(self, context):
        sc = context.scene
        idx = sc.fbp_layer_stack_index
        layers = sc.fbp_layers
        if not (0 <= idx < len(layers)):
            return {'CANCELLED'}

        current_rig = _safe_layer_obj(layers[idx])
        if not current_rig:
            return {'CANCELLED'}

        visible = visible_layer_indices(context, same_collection_as=current_rig)
        display_order = list(reversed(visible))
        if idx not in display_order or len(display_order) < 2:
            self.report({'WARNING'}, "No visible neighbour in this collection")
            return {'CANCELLED'}

        pos = display_order.index(idx)
        new_pos = pos - 1 if self.direction == 'UP' else pos + 1
        if not (0 <= new_pos < len(display_order)):
            return {'CANCELLED'}

        target_idx = display_order[new_pos]
        target_rig = _safe_layer_obj(layers[target_idx])
        if not target_rig:
            return {'CANCELLED'}

        swap_layer_depth_only(context, current_rig, target_rig)
        layers.move(idx, target_idx)
        sc.fbp_layer_stack_index = target_idx
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
        all_rigs = [ob for ob in context.scene.objects if getattr(ob, "is_fbp_control", False)]
        visible_rigs = [ob for ob in all_rigs if getattr(ob, "fbp_is_visible", False)]
        is_solo = set(visible_rigs) == set(selected_rigs)
        for rig in all_rigs:
            rig.fbp_is_visible = True if is_solo else (rig in selected_rigs)
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
        box.prop(sc, "fbp_cam_ratio", text="Camera Ratio")
        row = box.row(align=True)
        row.prop(sc, "fbp_cam_pivot", text="3D Cursor on Camera", toggle=True, icon=fbp_icon("PIVOT_CURSOR"))
        row.prop(sc, "fbp_auto_scale", text="Fit Layers", toggle=True, icon=fbp_icon("FULLSCREEN_ENTER"))
        layout.label(text="The selected ratio is also stored as the default.", icon=fbp_icon("INFO"))

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

    collection_name: StringProperty(default="")

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

    collection_name: StringProperty(default="")

    def execute(self, context):
        sc = context.scene
        name = self.collection_name or 'Unsorted'
        set_pending_collection_open(sc, name, not pending_collection_is_open(sc, name))
        _fbp_refresh_pending_tree(context)
        return {'FINISHED'}

class FBP_OT_SelectCollectionLayers(Operator):
    bl_idname      = "fbp.select_collection_layers"
    bl_label       = "Toggle Collection Layer Selection"
    bl_description = "Select or deselect all Frame by Plane rig layers inside this collection. Shift-click adds/removes without clearing other selections"
    bl_options     = {'UNDO'}

    collection_name: StringProperty(default="")
    extend: BoolProperty(default=False)

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

    collection_name: StringProperty(default="")

    def execute(self, context):
        coll = bpy.data.collections.get(self.collection_name)
        if not coll:
            return {'CANCELLED'}
        new_hidden = not collection_is_hidden_in_view_layer(context, coll)
        try:
            coll.hide_viewport = new_hidden
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        try:
            layer_coll = find_layer_collection(context.view_layer.layer_collection, coll)
            if layer_coll:
                layer_coll.hide_viewport = new_hidden
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        # Keep object-level visibility intact; the Collection is the parent switch.
        update_global_visibility(context)
        return {'FINISHED'}

class FBP_OT_ToggleCollectionLock(Operator):
    bl_idname      = "fbp.toggle_collection_lock"
    bl_label       = "Toggle Collection Lock"
    bl_description = "Lock/unlock all Frame by Plane rigs and planes inside this collection"
    bl_options     = {'UNDO'}

    collection_name: StringProperty(default="")

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

    collection_name: StringProperty(default="")

    def execute(self, context):
        coll = bpy.data.collections.get(self.collection_name)
        if not coll:
            return {'CANCELLED'}
        rigs = list(iter_fbp_rigs_in_collection(coll, True))
        deleted = delete_fbp_rigs(context, rigs)
        self.report({'INFO'}, f"Deleted {deleted} layer(s) from {coll.name}")
        return {'FINISHED'} if deleted else {'CANCELLED'}

__all__ = ['FBP_OT_SaveFile', 'FBP_OT_OpenCreateRig', 'FBP_OT_SelectLinkedPlane', 'FBP_OT_SelectCollectionPlanes', 'FBP_OT_AddColorPlaneVariant', 'FBP_OT_UIListNameAction', 'FBP_OT_SelectLayerExclusive', 'FBP_OT_DuplicateOrDefault', 'FBP_OT_SelectAllLayers', 'FBP_OT_ToggleLock', 'FBP_OT_ToggleSelectLayer', 'FBP_OT_ToggleSolo', 'FBP_OT_MoveLayerStack', 'FBP_OT_IsolateLayer', 'FBP_OT_PopupGenerateCamera', 'FBP_OT_FitToCamera', 'FBP_OT_MultiFitCamera', 'FBP_OT_SetCurrentFrame', 'FBP_OT_ToggleCollectionCollapse', 'FBP_OT_TogglePendingCollectionCollapse', 'FBP_OT_SelectCollectionLayers', 'FBP_OT_ToggleCollectionVisibility', 'FBP_OT_ToggleCollectionLock', 'FBP_OT_DeleteCollectionLayers']
