"""Focused Frame by Plane operator module."""

try:
    from .operator_common import *
except ImportError:
    from operator_common import *


class FBP_OT_UpdateAnimation(Operator):
    bl_idname  = "fbp.update_animation"
    bl_label   = "Update Animation"
    bl_description = "Refresh the selected layer animation timing"
    bl_options = {'UNDO', 'INTERNAL'}

    def execute(self, context):
        for rig in get_selected_rigs(context):
            do_update_animation(rig)
        return {'FINISHED'}

class FBP_OT_Transform(Operator):
    bl_idname      = "fbp.transform"
    bl_label       = "Transform"
    bl_description = "Rotate the plane or place it on the ground"
    bl_options     = {'UNDO'}

    mode: StringProperty()

    def execute(self, context):
        for rig in get_selected_rigs(context):
            if self.mode == 'TOGGLE_ROT':
                if rig.fbp_is_vertical:
                    rig.rotation_euler[0] = 0
                    rig.fbp_is_vertical = False
                else:
                    rig.rotation_euler[0] = math.radians(90)
                    rig.fbp_is_vertical = True
            elif self.mode == 'TO_GROUND':
                bbox_world = [rig.matrix_world @ mathutils.Vector(c) for c in rig.bound_box]
                min_z = min(v.z for v in bbox_world)
                rig.location.z -= min_z
            elif self.mode == 'RESET_ROT':
                rig.rotation_euler = (0.0, 0.0, 0.0)
                rig.fbp_is_vertical = False
            elif self.mode == 'RESET_SCALE':
                base_vec = getattr(rig, "fbp_base_scale_vec", (1.0, 1.0, 1.0))
                rig.scale = base_vec
        return {'FINISHED'}

class FBP_OT_PopupTransform(Operator):
    bl_idname = "fbp.popup_transform"
    bl_label = "Transform Layer"
    bl_description = "Open transform tools for the selected Frame by Plane layer"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        if not get_selected_rigs(context):
            self.report({'WARNING'}, "Select a Frame by Plane layer first")
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        rig = get_selected_rigs(context)[0]
        layout = self.layout
        layout.label(text=rig.name, icon=fbp_icon("EMPTY_ARROWS"))
        col = layout.column(align=True)
        row = col.row(align=True)
        row.operator("fbp.transform", text="Horizontal / Vertical", icon=fbp_icon("FILE_REFRESH")).mode = 'TOGGLE_ROT'
        row.operator("fbp.transform", text="To Ground", icon=fbp_icon("GRID")).mode = 'TO_GROUND'
        row = col.row(align=True)
        row.operator("fbp.transform", text="Reset Rotation", icon=fbp_icon("FILE_REFRESH")).mode = 'RESET_ROT'
        row.operator("fbp.transform", text="Reset Scale", icon=fbp_icon("FULLSCREEN_ENTER")).mode = 'RESET_SCALE'

    def execute(self, context):
        return {'FINISHED'}

class FBP_OT_UpdateEmission(Operator):
    bl_idname  = "fbp.update_emission"
    bl_label   = "Update Emission"
    bl_description = "Rebuild selected layer materials using the current shadeless/emission setting"
    bl_options = {'UNDO', 'INTERNAL'}

    def execute(self, context):
        for rig in get_selected_rigs(context):
            do_update_emission(rig)
        return {'FINISHED'}

class FBP_OT_UpdateOpacity(Operator):
    bl_idname  = "fbp.update_opacity"
    bl_label   = "Update Opacity"
    bl_description = "Apply the current opacity to selected layer materials"
    bl_options = {'UNDO', 'INTERNAL'}

    def execute(self, context):
        for rig in get_selected_rigs(context):
            do_update_opacity(rig)
        return {'FINISHED'}

class FBP_OT_UpdateTrack(Operator):
    bl_idname  = "fbp.update_track"
    bl_label   = "Update Track"
    bl_description = "Update camera tracking constraints on selected Frame by Plane rigs"
    bl_options = {'UNDO', 'INTERNAL'}

    def execute(self, context):
        for rig in get_selected_rigs(context):
            do_update_track(rig, context)
        return {'FINISHED'}

class FBP_OT_SelectImageExclusive(Operator):
    bl_idname = "fbp.select_image_exclusive"
    bl_label = "Select Frame"
    bl_description = "Select only this frame. Use the checkbox for additive multi-selection"
    bl_options = {'UNDO'}

    rig_name: StringProperty(default="")
    index: IntProperty(default=0)

    def execute(self, context):
        rig = bpy.data.objects.get(self.rig_name)
        if not rig or not getattr(rig, "is_fbp_control", False):
            return {'CANCELLED'}
        if not (0 <= self.index < len(rig.fbp_images)):
            return {'CANCELLED'}

        for i, item in enumerate(rig.fbp_images):
            item.is_selected = (i == self.index)
        rig.fbp_images_index = self.index

        if object_in_view_layer(rig, context):
            bpy.ops.object.select_all(action='DESELECT')
            rig.select_set(True)
            context.view_layer.objects.active = rig

        if getattr(rig, "fbp_is_color_plane", False):
            fbp_load_active_procedural_frame_to_rig(rig)
        do_update_animation(rig)
        return {'FINISHED'}

class FBP_OT_InsertImagesAfterSelected(Operator):
    bl_idname      = "fbp.insert_images_after_selected"
    bl_label       = "Insert Frame"
    bl_description = "Insert a new frame after the active frame or after the last checked frame"
    bl_options     = {'REGISTER', 'UNDO'}

    frame_mode: EnumProperty(
        name="Frame Kind",
        description="Choose the procedural frame type to insert",
        items=[('AUTO', "Match Plane Type", "Create a color/gradient frame matching the current plane type"),
               ('COLOR', "Color Frame", "Create a solid color frame"),
               ('GRADIENT', "Gradient Frame", "Create a gradient frame")],
        default='AUTO'
    )

    def execute(self, context):
        rig = context.object if context.object and getattr(context.object, "is_fbp_control", False) else None
        if not rig:
            rigs = get_selected_rigs(context)
            rig = rigs[0] if rigs else None
        if not rig or not rig.fbp_plane_target:
            self.report({'WARNING'}, "Select one Frame by Plane rig first")
            return {'CANCELLED'}
        if getattr(rig, "fbp_is_color_plane", False) and not fbp_color_plane_can_have_frames(rig):
            self.report({'WARNING'}, "Holdout planes are static masks and cannot have animation frames")
            return {'CANCELLED'}

        if not getattr(rig, "fbp_is_color_plane", False):
            self.report({'WARNING'}, "Native image planes no longer use generated empty material frames. Use an image with alpha, or Start Frame for pre-start transparency.")
            return {'CANCELLED'}


        requested_kind = None
        if self.frame_mode == 'COLOR':
            requested_kind = 'SOLID'
        elif self.frame_mode == 'GRADIENT':
            requested_kind = 'GRADIENT'

        old_mode = getattr(rig, 'fbp_color_plane_mode', 'SOLID')
        if requested_kind:
            # Silent assignment avoids rebuilding the active frame just because
            # the user chooses which kind of new frame to insert.
            try:
                fbp_set_rna_property_silent(rig, 'fbp_color_plane_mode', requested_kind)
            except Exception:
                rig['fbp_pending_insert_kind'] = requested_kind

        mat, label, is_empty = fbp_create_procedural_frame_material_for_rig(rig, len(rig.fbp_images) + 1)

        if requested_kind:
            try:
                fbp_set_rna_property_silent(rig, 'fbp_color_plane_mode', old_mode)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass

        kind = requested_kind or (fbp_procedural_kind_from_material(mat, getattr(rig, 'fbp_color_plane_mode', 'SOLID')) if mat else 'AUTO')
        entry = {
            "name": label,
            "duration": max(1, int(getattr(rig, 'fbp_global_duration', 1))),
            "is_selected": True,
            "is_empty": bool(is_empty),
            "filepath": "",
            "procedural_kind": kind,
        }
        result = fbp_insert_sequence_entry(rig, entry, mat, None)
        if result < 0:
            return {'CANCELLED'}

        self.report({'INFO'}, f"Inserted {label}")
        return {'FINISHED'}

class FBP_OT_InsertLinkedImageAfterSelected(Operator):
    bl_idname      = "fbp.insert_linked_image_after_selected"
    bl_label       = "Import Frame"
    bl_description = "Import a new image/video frame after the active frame or after the last checked frame"
    bl_options     = {'REGISTER', 'UNDO'}

    filepath:  StringProperty(subtype='FILE_PATH')
    directory: StringProperty(subtype='DIR_PATH')
    files:     CollectionProperty(type=bpy.types.OperatorFileListElement)

    def invoke(self, context, event):
        path = context.scene.fbp_project_path or context.scene.fbp_last_directory
        if path:
            self.directory = path
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        rig = context.object if context.object and getattr(context.object, "is_fbp_control", False) else None
        if not rig:
            rigs = get_selected_rigs(context)
            rig = rigs[0] if rigs else None
        if not rig or not rig.fbp_plane_target:
            self.report({'WARNING'}, "Select one Frame by Plane rig first")
            return {'CANCELLED'}
        if getattr(rig, "fbp_is_color_plane", False):
            self.report({'WARNING'}, "Color, Gradient and Holdout planes use procedural frames only; image import is available only for image planes")
            return {'CANCELLED'}

        chosen = None
        if self.files:
            for f in self.files:
                if is_supported_media_file(f.name):
                    chosen = f.name
                    break
        elif self.filepath and is_supported_media_file(self.filepath):
            chosen = os.path.basename(self.filepath)
            self.directory = os.path.dirname(self.filepath)

        if not chosen:
            self.report({'WARNING'}, "No supported image or video selected")
            return {'CANCELLED'}

        context.scene.fbp_last_directory = self.directory
        img_path = os.path.join(self.directory, chosen)
        entry = {
            "name": chosen,
            "duration": max(1, int(getattr(rig, 'fbp_global_duration', 1))),
            "is_selected": True,
            "is_empty": False,
            "filepath": img_path,
            "procedural_kind": "AUTO",
        }
        insert_at = fbp_insert_sequence_entry(rig, entry, None)
        if insert_at < 0:
            self.report({'WARNING'}, "Could not rebuild native image sequence")
            return {'CANCELLED'}
        if not rig.fbp_preview_path:
            rig.fbp_preview_path = img_path
        self.report({'INFO'}, f"Imported {chosen}")
        return {'FINISHED'}

class FBP_OT_LinkImageFrame(Operator):
    bl_idname      = "fbp.link_image_frame"
    bl_label       = "Link Image to Frame"
    bl_description = "Link or replace the image/video used by this frame"
    bl_options     = {'REGISTER', 'UNDO'}

    index:     IntProperty(default=-1)
    rig_name:  StringProperty(default="")
    filepath:  StringProperty(subtype='FILE_PATH')
    directory: StringProperty(subtype='DIR_PATH')
    files:     CollectionProperty(type=bpy.types.OperatorFileListElement)

    def invoke(self, context, event):
        path = context.scene.fbp_project_path or context.scene.fbp_last_directory
        if path:
            self.directory = path
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        rig = bpy.data.objects.get(self.rig_name) if self.rig_name else None
        if not rig or not getattr(rig, "is_fbp_control", False):
            rig = context.object if context.object and getattr(context.object, "is_fbp_control", False) else None
        if not rig:
            rigs = get_selected_rigs(context)
            rig = rigs[0] if rigs else None
        if not rig or not rig.fbp_plane_target:
            self.report({'WARNING'}, "Select one Frame by Plane rig first")
            return {'CANCELLED'}
        if not (0 <= self.index < len(rig.fbp_images)):
            self.report({'WARNING'}, "Invalid frame index")
            return {'CANCELLED'}
        if getattr(rig, "fbp_is_color_plane", False):
            self.report({'WARNING'}, "Procedural color/gradient frame rows cannot be replaced with image files")
            return {'CANCELLED'}

        chosen = None
        if self.files:
            for f in self.files:
                if is_supported_media_file(f.name):
                    chosen = f.name
                    break
        elif self.filepath and is_supported_media_file(self.filepath):
            chosen = os.path.basename(self.filepath)
            self.directory = os.path.dirname(self.filepath)

        if not chosen:
            self.report({'WARNING'}, "No supported image or video selected")
            return {'CANCELLED'}

        context.scene.fbp_last_directory = self.directory
        img_path = os.path.join(self.directory, chosen)

        item = rig.fbp_images[self.index]
        item.name = chosen
        item.filepath = img_path
        item.is_empty = False
        item.is_selected = True
        rig.fbp_images_index = self.index

        if not rig.fbp_preview_path:
            rig.fbp_preview_path = img_path

        try:
            if not fbp_rebuild_sequence_backend_from_rig(rig):
                self.report({'WARNING'}, "Could not rebuild image sequence backend")
                return {'CANCELLED'}
        except Exception as exc:
            fbp_warn("Could not rebuild image sequence backend after relinking", exc)
            self.report({'WARNING'}, "Could not rebuild image sequence backend")
            return {'CANCELLED'}
        do_update_animation(rig)
        do_update_emission(rig)
        do_update_opacity(rig)
        self.report({'INFO'}, f"Linked {chosen}")
        return {'FINISHED'}

class FBP_OT_SelectAll(Operator):
    bl_idname      = "fbp.select_all"
    bl_label       = "Select All"
    bl_description = "Quickly select/deselect images in the list"

    action: StringProperty()

    def execute(self, context):
        for rig in get_selected_rigs(context):
            items = list(getattr(rig, 'fbp_images', []))
            if self.action == 'TOGGLE':
                target = not (len(items) > 0 and all(bool(getattr(item, 'is_selected', False)) for item in items))
                for item in items:
                    item.is_selected = target
                continue
            for item in items:
                if   self.action == 'ALL':    item.is_selected = True
                elif self.action == 'NONE':   item.is_selected = False
                elif self.action == 'INVERT': item.is_selected = not item.is_selected
        return {'FINISHED'}

class FBP_OT_ListAction(Operator):
    bl_idname      = "fbp.list_action"
    bl_label       = "List Action"
    bl_description = "Edit the image list and rebuild the selected sequence backend"
    bl_options     = {'UNDO'}

    action: StringProperty()

    def _snapshot_item(self, item):
        return {
            "name": str(getattr(item, "name", "Image") or "Image"),
            "duration": max(1, int(getattr(item, "duration", 1) or 1)),
            "is_selected": bool(getattr(item, "is_selected", False)),
            "is_empty": bool(getattr(item, "is_empty", False)),
            "filepath": str(getattr(item, "filepath", "") or ""),
            "procedural_kind": str(getattr(item, "procedural_kind", "AUTO") or "AUTO"),
        }

    def _apply_items(self, rig, items, new_index=None):
        if getattr(rig, "fbp_is_color_plane", False):
            try:
                if not fbp_apply_sequence_entries_to_rig(rig, items):
                    self.report({'WARNING'}, "Procedural frame update failed")
                    return False
                if len(rig.fbp_images) > 0:
                    rig.fbp_images_index = max(0, min(int(new_index or 0), len(rig.fbp_images) - 1))
                    fbp_load_active_procedural_frame_to_rig(rig)
                return True
            except Exception as exc:
                fbp_warn("Procedural list action failed", exc)
                self.report({'WARNING'}, "Procedural frame update failed")
                return False

        rig.fbp_images.clear()
        for data in items:
            item = rig.fbp_images.add()
            item.name = data.get("name", "Image")
            item.duration = max(1, int(data.get("duration", getattr(rig, "fbp_global_duration", 1)) or 1))
            item.is_selected = bool(data.get("is_selected", True))
            item.is_empty = bool(data.get("is_empty", False))
            item.filepath = str(data.get("filepath", "") or "")

        if len(rig.fbp_images) > 0:
            if new_index is None:
                new_index = min(getattr(rig, "fbp_images_index", 0), len(rig.fbp_images) - 1)
            rig.fbp_images_index = max(0, min(int(new_index), len(rig.fbp_images) - 1))
        else:
            rig.fbp_images_index = 0

        # Image planes now rebuild from the collection data only. No per-frame
        # material slots are reordered, copied, inserted or deleted here.
        try:
            if not fbp_rebuild_sequence_backend_from_rig(rig):
                self.report({'WARNING'}, "Sequence backend rebuild failed")
                return False
        except Exception as exc:
            fbp_warn("List action backend rebuild failed", exc)
            self.report({'WARNING'}, "Sequence backend rebuild failed")
            return False
        do_update_animation(rig)
        return True

    def _selected_indices(self, items):
        return [i for i, data in enumerate(items) if bool(data.get("is_selected", False))]

    def execute(self, context):
        for rig in get_selected_rigs(context):
            if not getattr(rig, "fbp_plane_target", None):
                continue

            if getattr(rig, "fbp_is_color_plane", False):
                image_data = fbp_sequence_entries_from_rig(rig)
                if not image_data and fbp_color_plane_can_have_frames(rig):
                    # Promote a static Color/Gradient plane to a one-frame procedural sequence.
                    plane = getattr(rig, "fbp_plane_target", None)
                    mat = plane.data.materials[0] if plane and len(plane.data.materials) else None
                    image_data = [{
                        "name": "Gradient" if getattr(rig, "fbp_color_plane_mode", "SOLID") == 'GRADIENT' else "Color",
                        "duration": max(1, int(getattr(rig, "fbp_global_duration", 1) or 1)),
                        "is_selected": True,
                        "is_empty": False,
                        "filepath": "",
                        "material": mat,
                    }]
                if not image_data:
                    continue
            else:
                if len(getattr(rig, "fbp_images", [])) == 0:
                    continue
                image_data = [self._snapshot_item(item) for item in rig.fbp_images]

            idx = max(0, min(getattr(rig, "fbp_images_index", 0), len(image_data) - 1))

            if self.action == 'REMOVE':
                remove_indices = self._selected_indices(image_data) or ([idx] if idx < len(image_data) else [])
                for i in reversed(remove_indices):
                    if 0 <= i < len(image_data):
                        del image_data[i]
                self._apply_items(rig, image_data, min(idx, len(image_data) - 1) if image_data else 0)

            elif self.action == 'MOVE_UP':
                if idx <= 0:
                    continue
                image_data[idx - 1], image_data[idx] = image_data[idx], image_data[idx - 1]
                self._apply_items(rig, image_data, idx - 1)

            elif self.action == 'MOVE_DOWN':
                if idx >= len(image_data) - 1:
                    continue
                image_data[idx + 1], image_data[idx] = image_data[idx], image_data[idx + 1]
                self._apply_items(rig, image_data, idx + 1)

            elif self.action == 'DUPLICATE_SELECTED':
                selected_indices = self._selected_indices(image_data)
                if not selected_indices:
                    self.report({'WARNING'}, "No checked frames to duplicate")
                    continue
                insert_at = selected_indices[-1] + 1
                # After duplication, only the new duplicated rows stay checked.
                for data in image_data:
                    data["is_selected"] = False
                if getattr(rig, "fbp_is_color_plane", False):
                    duplicates = [fbp_clone_sequence_entry_material(image_data[i], rig, f"Duplicate_{n + 1}") for n, i in enumerate(selected_indices)]
                else:
                    duplicates = [dict(image_data[i]) for i in selected_indices]
                    for dup in duplicates:
                        dup["is_selected"] = True
                image_data[insert_at:insert_at] = duplicates
                self._apply_items(rig, image_data, insert_at)

            elif self.action == 'SORT_NATURAL':
                image_data.sort(key=lambda data: natural_sort_key(data.get("name", "")))
                self._apply_items(rig, image_data, 0)

        return {'FINISHED'}

class FBP_OT_ReverseSequence(Operator):
    bl_idname      = "fbp.reverse_sequence"
    bl_label       = "Reverse Sequence"
    bl_description = "Reverse the image order and rebuild the selected sequence backend"
    bl_options     = {'UNDO'}

    def execute(self, context):
        for rig in get_selected_rigs(context):
            if not getattr(rig, "fbp_plane_target", None):
                continue
            if len(getattr(rig, "fbp_images", [])) <= 1:
                continue

            if getattr(rig, "fbp_is_color_plane", False):
                entries = fbp_sequence_entries_from_rig(rig)
                entries.reverse()
                fbp_apply_sequence_entries_to_rig(rig, entries)
                continue

            data = [
                (
                    item.name,
                    int(getattr(item, "duration", 1) or 1),
                    bool(getattr(item, "is_selected", False)),
                    bool(getattr(item, "is_empty", False)),
                    str(getattr(item, "filepath", "") or ""),
                )
                for item in rig.fbp_images
            ]
            data.reverse()

            rig.fbp_images.clear()
            for name, duration, is_selected, is_empty, filepath in data:
                item = rig.fbp_images.add()
                item.name = name
                item.duration = max(1, int(duration))
                item.is_selected = is_selected
                item.is_empty = is_empty
                item.filepath = filepath
            rig.fbp_images_index = 0

            try:
                if fbp_rebuild_sequence_backend_from_rig(rig):
                    continue
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
            do_update_animation(rig)
        return {'FINISHED'}

class FBP_OT_PopupSequenceSettings(Operator):
    bl_idname = "fbp.popup_sequence_settings"
    bl_label = "Timing / Sequence Settings"
    bl_description = "Open timing and sequence controls for the selected Frame by Plane layer"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        if not get_selected_rigs(context):
            self.report({'WARNING'}, "Select a Frame by Plane layer first")
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        rig = get_selected_rigs(context)[0]
        layout = self.layout
        layout.label(text=rig.name, icon=fbp_icon("TIME"))
        row = layout.row(align=True)
        row.prop(rig, "fbp_start_frame", text="Start")
        row.operator("fbp.set_current_frame", text="", icon=fbp_icon("EYEDROPPER"))
        layout.prop(rig, "fbp_loop_mode", text="Playback")
        row = layout.row(align=True)
        row.operator("fbp.reverse_sequence", text="Reverse", icon=fbp_icon("ARROW_LEFTRIGHT"))
        row.operator("fbp.list_action", text="Sort A-Z", icon=fbp_icon("SORTALPHA")).action = 'SORT_NATURAL'
        row = layout.row(align=True)
        row.prop(rig, "fbp_global_duration", text="Duration")

    def execute(self, context):
        return {'FINISHED'}

class FBP_OT_DuplicateSelectedLayers(Operator):
    bl_idname      = "fbp.duplicate_selected_layers"
    bl_label       = "Duplicate Selected Layers"
    bl_description = "Duplicate selected Frame By Plane rigs with their plane, materials and image list"
    bl_options     = {'UNDO'}

    def _copy_image_list(self, src_rig, dst_rig):
        dst_rig.fbp_images.clear()
        for src_item in src_rig.fbp_images:
            dst_item = dst_rig.fbp_images.add()
            dst_item.name = src_item.name
            dst_item.duration = src_item.duration
            dst_item.is_selected = src_item.is_selected
            dst_item.is_empty = getattr(src_item, 'is_empty', False)
            dst_item.filepath = getattr(src_item, 'filepath', '')
            try:
                dst_item.procedural_kind = getattr(src_item, 'procedural_kind', 'AUTO')
                dst_item.preview_color_a = getattr(src_item, 'preview_color_a', (1.0, 1.0, 1.0, 1.0))
                dst_item.preview_color_b = getattr(src_item, 'preview_color_b', (1.0, 1.0, 1.0, 1.0))
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
        dst_rig.fbp_images_index = min(src_rig.fbp_images_index, max(0, len(dst_rig.fbp_images) - 1))

    def _copy_materials(self, src_plane, dst_plane):
        dst_plane.data.materials.clear()
        for mat in src_plane.data.materials:
            if not mat:
                continue
            new_mat = mat.copy()
            new_mat.name = mat.name + "_Copy"
            dst_plane.data.materials.append(new_mat)

    def execute(self, context):
        selected_rigs = get_selected_fbp_roots(context)
        duplicated = []

        if not selected_rigs:
            self.report({'WARNING'}, "No Frame By Plane rig or linked plane selected")
            return {'CANCELLED'}

        for rig in selected_rigs:
            plane = rig.fbp_plane_target
            if not plane:
                continue

            source_collection = get_primary_fbp_collection(rig) or context.collection or context.scene.collection
            rig_collections = [source_collection]
            plane_collections = [source_collection]
            active_collection = source_collection

            new_rig = rig.copy()
            if rig.data:
                new_rig.data = rig.data.copy()
            new_rig.name = rig.name + "_Copy"
            new_rig.is_fbp_control = True
            new_rig.fbp_collection_name = source_collection.name if source_collection else ""

            if not any(existing == new_rig for existing in active_collection.objects):
                active_collection.objects.link(new_rig)
            for coll in rig_collections:
                if coll != active_collection and not any(existing == new_rig for existing in coll.objects):
                    coll.objects.link(new_rig)

            new_plane = plane.copy()
            if plane.data:
                new_plane.data = plane.data.copy()
            new_plane.name = plane.name + "_Copy"
            new_plane.is_fbp_plane = True
            new_plane["fbp_parent_rig_name"] = new_rig.name
            new_plane.fbp_collection_name = source_collection.name if source_collection else ""

            if not any(existing == new_plane for existing in active_collection.objects):
                active_collection.objects.link(new_plane)
            for coll in plane_collections:
                if coll != active_collection and not any(existing == new_plane for existing in coll.objects):
                    coll.objects.link(new_plane)

            new_rig.matrix_world = rig.matrix_world.copy()
            plane_world = plane.matrix_world.copy()
            new_plane.matrix_world = plane_world
            new_plane.parent = new_rig
            new_plane.matrix_world = plane_world
            new_plane.hide_select = plane.hide_select

            self._copy_materials(plane, new_plane)
            self._copy_image_list(rig, new_rig)
            new_rig.fbp_plane_target = new_plane
            new_rig.fbp_preview_path = rig.fbp_preview_path

            do_update_animation(new_rig)
            do_update_emission(new_rig)
            do_update_opacity(new_rig)
            duplicated.append(new_rig)

        if not duplicated:
            self.report({'WARNING'}, "No valid Frame By Plane layers duplicated")
            return {'CANCELLED'}

        context.view_layer.update()
        bpy.ops.object.select_all(action='DESELECT')
        selectable = []
        for obj in duplicated:
            if not object_in_view_layer(obj, context):
                ensure_object_in_active_collection(obj, context)
            if object_in_view_layer(obj, context):
                obj.select_set(True)
                selectable.append(obj)
        if selectable:
            context.view_layer.objects.active = selectable[-1]

        sync_layer_collection(context)
        # Keep only the duplicated layers selected in the UI list as well.
        try:
            dup_names = {obj.name for obj in duplicated}
            for layer in context.scene.fbp_layers:
                obj = getattr(layer, 'obj', None)
                layer.selected = bool(obj and obj.name in dup_names)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        self.report({'INFO'}, f"Duplicated {len(duplicated)} layer(s)")
        return {'FINISHED'}

class FBP_OT_MergeSelectedToActiveSequence(Operator):
    bl_idname = "fbp.merge_selected_to_active_sequence"
    bl_label = "Convert to Single Animated Plane"
    bl_description = "Merge selected Frame by Plane layers into the active layer sequence and delete the others"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        active = context.view_layer.objects.active
        if active and getattr(active, "is_fbp_plane", False) and getattr(active.parent, "is_fbp_control", False):
            active = active.parent
        if not active or not is_fbp_layer_object(active):
            self.report({'WARNING'}, "Make the target Frame by Plane rig active")
            return {'CANCELLED'}
        rigs = get_selected_fbp_roots(context)
        if active not in rigs:
            rigs.append(active)
        rigs = sorted(set(rigs), key=lambda r: (getattr(r, "fbp_depth_order", 0), natural_sort_key(r.name)))
        if len(rigs) < 2:
            self.report({'WARNING'}, "Select at least two Frame by Plane layers")
            return {'CANCELLED'}
        entries = []
        for rig in rigs:
            entries.extend(fbp_sequence_entries_from_rig(rig))
        if not entries:
            return {'CANCELLED'}
        fbp_apply_sequence_entries_to_rig(active, entries)
        delete_fbp_rigs(context, [rig for rig in rigs if rig != active])
        bpy.ops.object.select_all(action='DESELECT')
        if object_in_view_layer(active, context):
            active.select_set(True)
            context.view_layer.objects.active = active
        sync_layer_collection(context)
        self.report({'INFO'}, f"Merged {len(rigs)} layers into {active.name}")
        return {'FINISHED'}

class FBP_OT_SplitSelectedImagesToNewPlane(Operator):
    bl_idname = "fbp.split_selected_images_to_new_plane"
    bl_label = "Split Sequence"
    bl_description = "Move selected images from the active sequence to a new plane in the same position"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rig = context.object if context.object and is_fbp_layer_object(context.object) else None
        if not rig:
            rigs = get_selected_rigs(context)
            rig = rigs[0] if rigs else None
        if not rig or not getattr(rig, "fbp_plane_target", None):
            self.report({'WARNING'}, "Select one Frame by Plane rig")
            return {'CANCELLED'}
        plane = rig.fbp_plane_target
        entries = fbp_sequence_entries_from_rig(rig)
        selected_indices = [i for i, item in enumerate(rig.fbp_images) if item.is_selected]
        if not selected_indices:
            self.report({'WARNING'}, "Select images in the sequence list first")
            return {'CANCELLED'}
        selected_entries = [entries[i] for i in selected_indices]
        remaining_entries = [entry for i, entry in enumerate(entries) if i not in set(selected_indices)]
        if not selected_entries or not remaining_entries:
            self.report({'WARNING'}, "Leave at least one image in the original plane")
            return {'CANCELLED'}

        source_collection = get_primary_fbp_collection(rig) or context.collection or context.scene.collection
        new_rig = rig.copy()
        if rig.data:
            new_rig.data = rig.data.copy()
        new_rig.name = rig.name + "_Split"
        new_rig.is_fbp_control = True
        source_collection.objects.link(new_rig)

        new_plane = plane.copy()
        if plane.data:
            new_plane.data = plane.data.copy()
        new_plane.name = plane.name + "_Split"
        new_plane.is_fbp_plane = True
        source_collection.objects.link(new_plane)
        new_plane.parent = new_rig
        new_plane.matrix_world = plane.matrix_world.copy()
        new_plane.hide_select = plane.hide_select
        new_rig.fbp_plane_target = new_plane
        new_rig.fbp_collection_name = getattr(rig, "fbp_collection_name", "")
        new_plane.fbp_collection_name = getattr(plane, "fbp_collection_name", "")

        fbp_apply_sequence_entries_to_rig(new_rig, selected_entries)
        fbp_apply_sequence_entries_to_rig(rig, remaining_entries)

        bpy.ops.object.select_all(action='DESELECT')
        if object_in_view_layer(new_rig, context):
            new_rig.select_set(True)
            context.view_layer.objects.active = new_rig
        sync_layer_collection(context)
        self.report({'INFO'}, f"Split {len(selected_entries)} frame(s) to {new_rig.name}")
        return {'FINISHED'}

class FBP_OT_DeleteSequence(Operator):
    bl_idname      = "fbp.delete_sequence"
    bl_label       = "Delete Sequence"
    bl_description = "Delete selected Frame By Plane rigs and their planes"
    bl_options     = {'UNDO'}

    def execute(self, context):
        selected_rigs = get_selected_fbp_roots(context)
        if not selected_rigs:
            idx = context.scene.fbp_layer_stack_index
            if 0 <= idx < len(context.scene.fbp_layers):
                rig = _safe_layer_obj(context.scene.fbp_layers[idx])
                if rig and is_fbp_layer_object(rig):
                    selected_rigs = [rig]

        if not selected_rigs:
            sync_layer_collection(context)
            self.report({'WARNING'}, "No Frame By Plane rig selected")
            return {'CANCELLED'}
        deleted = delete_fbp_rigs(context, selected_rigs)
        if deleted <= 0:
            return {'CANCELLED'}
        self.report({'INFO'}, f"Deleted {deleted} Frame By Plane layer(s)")
        return {'FINISHED'}

class FBP_OT_DeleteOrDefault(Operator):
    bl_idname      = "fbp.delete_or_default"
    bl_label       = "Delete"
    bl_description = "Delete FBP rigs together with their planes, otherwise use Blender's standard delete"
    bl_options     = {'UNDO'}

    def invoke(self, context, event):
        roots = get_selected_fbp_roots(context)
        if roots:
            deleted = delete_fbp_rigs(context, roots)
            if deleted > 0:
                self.report({'INFO'}, f"Deleted {deleted} Frame By Plane layer(s)")
                return {'FINISHED'}
            return {'CANCELLED'}
        return bpy.ops.object.delete('INVOKE_DEFAULT')

__all__ = ['FBP_OT_UpdateAnimation', 'FBP_OT_Transform', 'FBP_OT_PopupTransform', 'FBP_OT_UpdateEmission', 'FBP_OT_UpdateOpacity', 'FBP_OT_UpdateTrack', 'FBP_OT_SelectImageExclusive', 'FBP_OT_InsertImagesAfterSelected', 'FBP_OT_InsertLinkedImageAfterSelected', 'FBP_OT_LinkImageFrame', 'FBP_OT_SelectAll', 'FBP_OT_ListAction', 'FBP_OT_ReverseSequence', 'FBP_OT_PopupSequenceSettings', 'FBP_OT_DuplicateSelectedLayers', 'FBP_OT_MergeSelectedToActiveSequence', 'FBP_OT_SplitSelectedImagesToNewPlane', 'FBP_OT_DeleteSequence', 'FBP_OT_DeleteOrDefault']
