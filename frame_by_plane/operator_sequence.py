"""Focused Frame by Plane operator module."""

import bpy
import math
import mathutils
import os
from bpy.props import (
    CollectionProperty,
    EnumProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Operator

from .constants import fbp_icon
from .path_utils import is_supported_media_file, is_supported_video_file, natural_sort_key
from .materials import (
    do_update_emission,
    do_update_opacity,
    fbp_create_procedural_frame_material_for_rig,
    fbp_copy_material_slots_unique,
)
from .layers import (
    _safe_layer_obj,
    ensure_object_in_active_collection,
    fbp_active_layer_index,
    fbp_procedural_kind_from_material,
    get_primary_fbp_collection,
    get_selected_fbp_roots,
    get_selected_rigs,
    is_fbp_layer_object,
    fbp_layer_backend_type,
    object_in_view_layer,
)
from .scene_sync import (
    delete_fbp_rigs,
    fbp_remove_plane_datablock,
    sync_layer_collection,
)
from .runtime import fbp_set_rna_property_silent, fbp_warn, FBP_DATA_ERRORS, FBP_DATA_IO_ERRORS
from .core import (
    do_update_animation,
    do_update_track,
    fbp_apply_sequence_entries_to_rig,
    fbp_clone_sequence_entry_material,
    fbp_color_plane_can_have_frames,
    fbp_insert_sequence_entry,
    fbp_load_active_procedural_frame_to_rig,
    fbp_rebuild_sequence_backend_from_rig,
    fbp_refresh_sequence_backend_from_rig,
    fbp_sequence_entries_from_rig,
)
from .operator_common import (
    fbp_jump_timeline_to_sequence_row,
)


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

    mode: StringProperty(description="Operation mode passed to this Frame By Plane action. The available meaning depends on the button or menu entry that invoked it.")

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
    bl_description = "Select this frame and move the timeline to its first scene frame. Use the checkbox for additive multi-selection"
    bl_options = {'UNDO'}

    rig_name: StringProperty(description="Name of the Frame By Plane control rig targeted by this action. Stored only long enough to resolve the object safely.", default="")
    index: IntProperty(description="Zero-based index of the frame, drawing, layer or setup entry targeted by this action.", default=0)

    def execute(self, context):
        rig = bpy.data.objects.get(self.rig_name)
        if not rig or not getattr(rig, "is_fbp_control", False):
            return {'CANCELLED'}
        if not (0 <= self.index < len(rig.fbp_images)):
            return {'CANCELLED'}

        for i, item in enumerate(rig.fbp_images):
            item.is_selected = (i == self.index)
        rig.fbp_images_index = self.index
        fbp_jump_timeline_to_sequence_row(context, rig, self.index)

        if object_in_view_layer(rig, context):
            bpy.ops.object.select_all(action='DESELECT')
            rig.select_set(True)
            context.view_layer.objects.active = rig

        backend = fbp_layer_backend_type(rig)
        if backend.startswith('PROCEDURAL_'):
            fbp_load_active_procedural_frame_to_rig(rig)
            do_update_animation(rig)
        elif backend == 'CUTOUT':
            do_update_animation(rig)
        # Native layers evaluate their existing ImageUser F-Curve immediately
        # after the timeline jump; rebuilding it here only adds filesystem and
        # dependency-graph work to a list-selection action.
        return {'FINISHED'}

class FBP_OT_InsertImagesAfterSelected(Operator):
    bl_idname      = "fbp.insert_images_after_selected"
    bl_label       = "Insert Frame"
    bl_description = "Insert a new frame after the active frame or after the last checked frame"
    bl_options     = {'REGISTER', 'UNDO'}

    frame_mode: EnumProperty(
        name="Frame Kind",
        description="Choose whether the new logical frame is a solid Color frame, a Gradient frame or a transparent Empty interval before rebuilding sequence timing.",
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
            # the user chooses which kind of new frame to insert. Abort instead
            # of creating a material with the wrong type if the RNA write fails.
            if not fbp_set_rna_property_silent(rig, 'fbp_color_plane_mode', requested_kind):
                self.report({'ERROR'}, "Could not change the procedural frame type")
                return {'CANCELLED'}

        try:
            mat, label, is_empty = fbp_create_procedural_frame_material_for_rig(
                rig, len(rig.fbp_images) + 1
            )
        except Exception as exc:
            fbp_warn("Could not create procedural frame material", exc)
            self.report({'ERROR'}, "Could not create the procedural frame material")
            return {'CANCELLED'}
        finally:
            if requested_kind and not fbp_set_rna_property_silent(
                rig, 'fbp_color_plane_mode', old_mode
            ):
                self.report({'WARNING'}, "The previous procedural plane type could not be restored")

        if not mat:
            self.report({'ERROR'}, "Could not create the procedural frame material")
            return {'CANCELLED'}

        kind = requested_kind or fbp_procedural_kind_from_material(
            mat, getattr(rig, 'fbp_color_plane_mode', 'SOLID')
        )
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
    bl_description = "Import a new image frame after the active frame or after the last checked frame"
    bl_options     = {'REGISTER', 'UNDO'}

    filepath:  StringProperty(description="Selected media file path returned by Blender's file browser.", subtype='FILE_PATH')
    directory: StringProperty(description="Folder currently selected in Blender's file browser.", subtype='DIR_PATH')
    files:     CollectionProperty(description="Files selected in Blender's file browser for this import or replacement action.", type=bpy.types.OperatorFileListElement)

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
        backend_type = fbp_layer_backend_type(rig)
        if backend_type not in {'NATIVE_IMAGE', 'NATIVE_SEQUENCE'}:
            self.report({'WARNING'}, "Import Frame is available only for image planes and image sequences")
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
            self.report({'WARNING'}, "No supported image selected")
            return {'CANCELLED'}
        if is_supported_video_file(chosen):
            self.report({'WARNING'}, "Videos are standalone Movie Planes and cannot be inserted into an image sequence")
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

class FBP_OT_InsertTransparentFrame(Operator):
    bl_idname = "fbp.insert_transparent_frame"
    bl_label = "Add Transparent Frame"
    bl_description = "Insert a transparent logical frame without creating or renaming an image file"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rig = context.object if context.object and getattr(context.object, "is_fbp_control", False) else None
        if not rig:
            rigs = get_selected_rigs(context)
            rig = rigs[0] if rigs else None
        if not rig or not getattr(rig, "fbp_plane_target", None):
            self.report({'WARNING'}, "Select one Frame by Plane layer first")
            return {'CANCELLED'}
        backend_type = fbp_layer_backend_type(rig)
        if backend_type not in {'NATIVE_IMAGE', 'NATIVE_SEQUENCE'}:
            self.report({'WARNING'}, "Transparent frames are available only for image planes and image sequences")
            return {'CANCELLED'}

        entry = {
            "name": "Transparent Frame",
            "duration": max(1, int(getattr(rig, 'fbp_global_duration', 1) or 1)),
            "is_selected": True,
            "is_empty": True,
            "filepath": "",
            "procedural_kind": "AUTO",
        }
        insert_at = fbp_insert_sequence_entry(rig, entry, None)
        if insert_at < 0:
            self.report({'WARNING'}, "Could not insert transparent frame")
            return {'CANCELLED'}
        self.report({'INFO'}, "Transparent frame added")
        return {'FINISHED'}


class FBP_OT_LinkImageFrame(Operator):
    bl_idname      = "fbp.link_image_frame"
    bl_label       = "Link Image to Frame"
    bl_description = "Link or replace the image/video used by this frame"
    bl_options     = {'REGISTER', 'UNDO'}

    index:     IntProperty(description="Zero-based index of the frame, drawing, layer or setup entry targeted by this action.", default=-1)
    rig_name:  StringProperty(description="Name of the Frame By Plane control rig targeted by this action. Stored only long enough to resolve the object safely.", default="")
    filepath:  StringProperty(description="Selected media file path returned by Blender's file browser.", subtype='FILE_PATH')
    directory: StringProperty(description="Folder currently selected in Blender's file browser.", subtype='DIR_PATH')
    files:     CollectionProperty(description="Files selected in Blender's file browser for this import or replacement action.", type=bpy.types.OperatorFileListElement)

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
        backend_type = fbp_layer_backend_type(rig)
        if backend_type not in {'NATIVE_IMAGE', 'NATIVE_SEQUENCE', 'NATIVE_MOVIE'}:
            self.report({'WARNING'}, "Only native image and movie rows can be relinked")
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
        if is_supported_video_file(chosen) and len(rig.fbp_images) != 1:
            self.report({'WARNING'}, "A video must remain a standalone one-row Movie Plane")
            return {'CANCELLED'}

        context.scene.fbp_last_directory = self.directory
        img_path = os.path.join(self.directory, chosen)

        item = rig.fbp_images[self.index]
        previous = {
            'name': str(getattr(item, 'name', '') or ''),
            'filepath': str(getattr(item, 'filepath', '') or ''),
            'is_empty': bool(getattr(item, 'is_empty', False)),
            'is_selected': bool(getattr(item, 'is_selected', False)),
            'index': int(getattr(rig, 'fbp_images_index', 0) or 0),
            'preview': str(getattr(rig, 'fbp_preview_path', '') or ''),
        }

        def restore_row():
            item.name = previous['name']
            item.filepath = previous['filepath']
            item.is_empty = previous['is_empty']
            item.is_selected = previous['is_selected']
            fbp_set_rna_property_silent(rig, 'fbp_images_index', previous['index'])
            rig.fbp_preview_path = previous['preview']
            try:
                if not (
                    fbp_refresh_sequence_backend_from_rig(rig)
                    or fbp_rebuild_sequence_backend_from_rig(rig)
                ):
                    fbp_warn("Could not restore native backend after failed frame relink")
            except Exception as exc:
                fbp_warn("Could not restore native backend after failed frame relink", exc)

        item.name = chosen
        item.filepath = img_path
        item.is_empty = False
        item.is_selected = True
        fbp_set_rna_property_silent(rig, 'fbp_images_index', self.index)

        if not rig.fbp_preview_path:
            rig.fbp_preview_path = img_path

        try:
            if not (
                fbp_refresh_sequence_backend_from_rig(rig)
                or fbp_rebuild_sequence_backend_from_rig(rig)
            ):
                restore_row()
                self.report({'WARNING'}, "Could not rebuild image sequence backend")
                return {'CANCELLED'}
        except Exception as exc:
            restore_row()
            fbp_warn("Could not rebuild image sequence backend after relinking", exc)
            self.report({'WARNING'}, "Could not rebuild image sequence backend")
            return {'CANCELLED'}

        # The transactional rebuild already uses the current timing, emission and
        # opacity settings. Repeating all three updates here only rebuilt/validated
        # the same material a second time.
        self.report({'INFO'}, f"Linked {chosen}")
        return {'FINISHED'}

class FBP_OT_SelectAll(Operator):
    bl_idname      = "fbp.select_all"
    bl_label       = "Select All"
    bl_description = "Quickly select/deselect images in the list"

    action: StringProperty(description="Specific list or selection action requested by the clicked UI button.")

    def execute(self, context):
        for rig in get_selected_rigs(context):
            items = list(getattr(rig, 'fbp_images', []))
            if self.action == 'TOGGLE':
                target = not (len(items) > 0 and all(bool(getattr(item, 'is_selected', False)) for item in items))
                for item in items:
                    item.is_selected = target
                continue
            for item in items:
                if self.action == 'ALL':
                    item.is_selected = True
                elif self.action == 'NONE':
                    item.is_selected = False
                elif self.action == 'INVERT':
                    item.is_selected = not item.is_selected
        return {'FINISHED'}

class FBP_OT_ListAction(Operator):
    bl_idname      = "fbp.list_action"
    bl_label       = "List Action"
    bl_description = "Edit the image list and rebuild the selected sequence backend"
    bl_options     = {'UNDO'}

    action: StringProperty(description="Specific list or selection action requested by the clicked UI button.")

    @classmethod
    def description(cls, context, properties):
        descriptions = {
            'MOVE_TOP': "Move the checked frames to the top of the sequence",
            'MOVE_UP': "Move all checked frames up by one position",
            'MOVE_DOWN': "Move all checked frames down by one position",
            'MOVE_BOTTOM': "Move the checked frames to the bottom of the sequence",
            'DUPLICATE_SELECTED': "Duplicate the checked frames without modifying the original image files",
            'REMOVE': "Delete the checked frames from the logical sequence",
        }
        return descriptions.get(getattr(properties, 'action', ''), cls.bl_description)

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
        """Apply list edits through the shared transactional sequence path."""
        is_procedural = bool(getattr(rig, "fbp_is_color_plane", False))
        try:
            if not fbp_apply_sequence_entries_to_rig(rig, items):
                label = "Procedural frame" if is_procedural else "Sequence backend"
                self.report({'WARNING'}, f"{label} update failed; the previous frame list was restored")
                return False
            if len(rig.fbp_images) > 0:
                if new_index is None:
                    new_index = min(
                        int(getattr(rig, "fbp_images_index", 0) or 0),
                        len(rig.fbp_images) - 1,
                    )
                rig.fbp_images_index = max(0, min(int(new_index), len(rig.fbp_images) - 1))
                if is_procedural:
                    fbp_load_active_procedural_frame_to_rig(rig)
            else:
                rig.fbp_images_index = 0
            return True
        except Exception as exc:
            fbp_warn("Transactional list action failed", exc)
            self.report({'WARNING'}, "Sequence update failed; the previous frame list was restored")
            return False

    def _selected_indices(self, items):
        return [i for i, data in enumerate(items) if bool(data.get("is_selected", False))]

    def _action_indices(self, items, active_index):
        """Return checked rows, falling back to the active row for move actions."""
        selected = self._selected_indices(items)
        if selected:
            return selected
        if 0 <= active_index < len(items):
            return [active_index]
        return []

    def _active_index_after_reorder(self, items, active_entry, fallback=0):
        if active_entry is not None:
            for index, entry in enumerate(items):
                if entry is active_entry:
                    return index
        if not items:
            return 0
        return max(0, min(int(fallback), len(items) - 1))

    def _move_indices_top(self, items, indices):
        selected_set = set(indices)
        selected = [entry for index, entry in enumerate(items) if index in selected_set]
        remaining = [entry for index, entry in enumerate(items) if index not in selected_set]
        items[:] = selected + remaining

    def _move_indices_bottom(self, items, indices):
        selected_set = set(indices)
        remaining = [entry for index, entry in enumerate(items) if index not in selected_set]
        selected = [entry for index, entry in enumerate(items) if index in selected_set]
        items[:] = remaining + selected

    def _move_indices_up(self, items, indices):
        selected_set = set(indices)
        for index in range(1, len(items)):
            if index in selected_set and (index - 1) not in selected_set:
                items[index - 1], items[index] = items[index], items[index - 1]
                selected_set.remove(index)
                selected_set.add(index - 1)

    def _move_indices_down(self, items, indices):
        selected_set = set(indices)
        for index in range(len(items) - 2, -1, -1):
            if index in selected_set and (index + 1) not in selected_set:
                items[index + 1], items[index] = items[index], items[index + 1]
                selected_set.remove(index)
                selected_set.add(index + 1)


    def execute(self, context):
        for rig in get_selected_rigs(context):
            if not getattr(rig, "fbp_plane_target", None):
                continue

            backend_type = fbp_layer_backend_type(rig)
            if backend_type == 'CUTOUT':
                continue
            if backend_type == 'NATIVE_MOVIE':
                self.report({'WARNING'}, "Movie Planes use one source row and do not support frame-list edits")
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
                if backend_type in {'NATIVE_IMAGE', 'NATIVE_SEQUENCE'} and len(remove_indices) >= len(image_data):
                    self.report({'WARNING'}, "An image plane must keep at least one frame")
                    continue
                for i in reversed(remove_indices):
                    if 0 <= i < len(image_data):
                        del image_data[i]
                self._apply_items(rig, image_data, min(idx, len(image_data) - 1) if image_data else 0)

            elif self.action in {'MOVE_TOP', 'MOVE_UP', 'MOVE_DOWN', 'MOVE_BOTTOM'}:
                action_indices = self._action_indices(image_data, idx)
                if not action_indices:
                    continue
                active_entry = image_data[idx] if 0 <= idx < len(image_data) else None

                if self.action == 'MOVE_TOP':
                    if action_indices == list(range(len(action_indices))):
                        continue
                    self._move_indices_top(image_data, action_indices)
                elif self.action == 'MOVE_UP':
                    before = list(image_data)
                    self._move_indices_up(image_data, action_indices)
                    if all(left is right for left, right in zip(before, image_data, strict=True)):
                        continue
                elif self.action == 'MOVE_DOWN':
                    before = list(image_data)
                    self._move_indices_down(image_data, action_indices)
                    if all(left is right for left, right in zip(before, image_data, strict=True)):
                        continue
                else:
                    trailing_start = len(image_data) - len(action_indices)
                    if action_indices == list(range(trailing_start, len(image_data))):
                        continue
                    self._move_indices_bottom(image_data, action_indices)

                new_index = self._active_index_after_reorder(image_data, active_entry, idx)
                self._apply_items(rig, image_data, new_index)

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


        return {'FINISHED'}

def _fbp_strict_sequence_direction(entries, fallback=False):
    """Return the natural numbered-sequence direction when it is unambiguous."""
    tokens = []
    for entry in entries or ():
        if bool(entry.get("is_empty", False)):
            return bool(fallback)
        token = str(entry.get("filepath", "") or entry.get("name", "") or "")
        if not token:
            return bool(fallback)
        tokens.append(token)
    if len(tokens) <= 1 or len(set(tokens)) != len(tokens):
        return bool(fallback)
    natural = sorted(tokens, key=lambda value: natural_sort_key(os.path.basename(value)))
    if tokens == natural:
        return False
    if tokens == list(reversed(natural)):
        return True
    return bool(fallback)


def fbp_reverse_sequence_rig(rig, *, desired_state=None):
    """Reverse the complete logical sequence through one transactional action.

    This is intentionally independent from frame checkboxes: the side-toolbar
    icon always reverses every row. The active row is mirrored so the same media
    remains selected after the list is rebuilt. Native sequences use their fast
    ImageUser/F-Curve refresh first and fall back to one verified full rebuild if
    the material order did not commit correctly.
    """
    if rig is None or not getattr(rig, "fbp_plane_target", None):
        return False
    backend_type = fbp_layer_backend_type(rig)
    if backend_type in {'CUTOUT', 'NATIVE_MOVIE'}:
        return False

    old_entries = fbp_sequence_entries_from_rig(rig)
    count = len(old_entries)
    if count <= 1:
        return False

    old_index = max(0, min(int(getattr(rig, "fbp_images_index", 0) or 0), count - 1))
    previous_state = _fbp_strict_sequence_direction(
        old_entries,
        fallback=bool(getattr(rig, "fbp_sequence_reversed", False)),
    )
    target_state = bool(desired_state) if desired_state is not None else not previous_state
    reversed_entries = list(reversed(old_entries))

    try:
        if not fbp_apply_sequence_entries_to_rig(rig, reversed_entries):
            return False

        # A native refresh should normally be enough. Verify the committed row
        # mapping because older 5.5.x materials could keep a valid-looking but
        # forward source-index curve after a reorder. Rebuild only on mismatch.
        if backend_type in {'NATIVE_IMAGE', 'NATIVE_SEQUENCE'}:
            try:
                from . import native_backend
                order_ok = native_backend.fbp_native_sequence_order_matches_rig(rig)
                if not order_ok:
                    order_ok = bool(native_backend.rebuild_native_sequence_from_rig(rig))
                    order_ok = order_ok and native_backend.fbp_native_sequence_order_matches_rig(rig)
                if not order_ok:
                    raise RuntimeError("native sequence order verification failed")
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
                # Restore both logical rows and backend rather than leaving the UI
                # reversed while Blender still evaluates the original direction.
                fbp_apply_sequence_entries_to_rig(rig, old_entries)
                fbp_set_rna_property_silent(rig, "fbp_images_index", old_index)
                fbp_set_rna_property_silent(rig, "fbp_sequence_reversed", previous_state)
                fbp_warn("Could not verify reversed native sequence", exc)
                return False

        fbp_set_rna_property_silent(rig, "fbp_images_index", count - 1 - old_index)
        fbp_set_rna_property_silent(rig, "fbp_sequence_reversed", target_state)
        if getattr(rig, "fbp_is_color_plane", False):
            fbp_load_active_procedural_frame_to_rig(rig)
        return True
    except Exception as exc:
        try:
            fbp_apply_sequence_entries_to_rig(rig, old_entries)
            fbp_set_rna_property_silent(rig, "fbp_images_index", old_index)
            fbp_set_rna_property_silent(rig, "fbp_sequence_reversed", previous_state)
        except Exception as restore_exc:
            fbp_warn("Could not restore sequence after reverse failure", restore_exc)
        fbp_warn("Could not reverse sequence", exc)
        return False


class FBP_OT_ReverseSequence(Operator):
    bl_idname      = "fbp.reverse_sequence"
    bl_label       = "Reverse Sequence"
    bl_description = "Reverse the complete sequence in one click, independently from frame checkboxes"
    bl_options     = {'UNDO'}

    def execute(self, context):
        changed = 0
        failed = 0
        for rig in get_selected_rigs(context):
            if not getattr(rig, "fbp_plane_target", None):
                continue
            backend_type = fbp_layer_backend_type(rig)
            if backend_type in {'CUTOUT', 'NATIVE_MOVIE'}:
                failed += 1
                continue
            if len(getattr(rig, "fbp_images", ())) <= 1:
                continue
            if fbp_reverse_sequence_rig(rig):
                changed += 1
            else:
                failed += 1

        if failed:
            self.report(
                {'WARNING'},
                f"Reversed {changed} sequence(s); {failed} sequence(s) were restored after rebuild failure",
            )
        if changed:
            try:
                context.view_layer.update()
            except (AttributeError, ReferenceError, RuntimeError):
                pass
            try:
                if context.area:
                    context.area.tag_redraw()
            except (AttributeError, ReferenceError, RuntimeError):
                pass
            return {'FINISHED'}
        if failed:
            return {'CANCELLED'}
        self.report({'WARNING'}, "Select a sequence with at least two frames")
        return {'CANCELLED'}

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
        row.prop(rig, "fbp_global_duration", text="Duration")

    def execute(self, context):
        return {'FINISHED'}

class FBP_OT_DuplicateSelectedLayers(Operator):
    bl_idname      = "fbp.duplicate_selected_layers"
    bl_label       = "Duplicate Selected Layers"
    bl_description = "Duplicate selected Frame By Plane rigs with their plane, materials and image list"
    bl_options     = {'UNDO'}

    rig_name: StringProperty(
        name="Layer",
        description="Optional exact layer target used by context-menu actions",
        default="",
        options={'SKIP_SAVE'},
    )

    def _copy_image_list(self, src_rig, dst_rig):
        dst_rig.fbp_images.clear()
        for src_item in src_rig.fbp_images:
            dst_item = dst_rig.fbp_images.add()
            dst_item.name = src_item.name
            fbp_set_rna_property_silent(dst_item, 'duration', src_item.duration)
            dst_item.is_selected = src_item.is_selected
            dst_item.is_empty = getattr(src_item, 'is_empty', False)
            dst_item.filepath = getattr(src_item, 'filepath', '')
            dst_item.image = getattr(src_item, 'image', None)
            dst_item.image_name = getattr(src_item, 'image_name', '')
            try:
                dst_item.managed_image = bool(getattr(src_item, 'managed_image', False))
                dst_item.source_width = max(0, int(getattr(src_item, 'source_width', 0) or 0))
                dst_item.source_height = max(0, int(getattr(src_item, 'source_height', 0) or 0))
            except FBP_DATA_ERRORS:
                pass
            if bool(getattr(src_rig, "fbp_is_drawing_plane", False)):
                try:
                    import uuid
                    dst_item.stable_id = uuid.uuid4().hex
                except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
                    dst_item.stable_id = getattr(src_item, 'stable_id', '')
            else:
                dst_item.stable_id = getattr(src_item, 'stable_id', '')
            try:
                dst_item.procedural_kind = getattr(src_item, 'procedural_kind', 'AUTO')
                dst_item.preview_color_a = getattr(src_item, 'preview_color_a', (1.0, 1.0, 1.0, 1.0))
                dst_item.preview_color_b = getattr(src_item, 'preview_color_b', (1.0, 1.0, 1.0, 1.0))
            except FBP_DATA_IO_ERRORS:
                pass
        fbp_set_rna_property_silent(
            dst_rig,
            'fbp_images_index',
            min(src_rig.fbp_images_index, max(0, len(dst_rig.fbp_images) - 1)),
        )
        if bool(getattr(src_rig, "fbp_is_drawing_plane", False)):
            try:
                from .drawing_plane import DRAWING_INDEX_KEY
                dst_rig[DRAWING_INDEX_KEY] = int(src_rig.get(DRAWING_INDEX_KEY, 0) or 0)
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
                pass

    def _copy_materials(self, src_plane, dst_plane):
        return bool(fbp_copy_material_slots_unique(src_plane, dst_plane))

    def _cleanup_partial_duplicate(self, new_rig, new_plane):
        try:
            if new_plane and bpy.data.objects.get(getattr(new_plane, 'name', '')) == new_plane:
                fbp_remove_plane_datablock(new_plane)
        except Exception as exc:
            fbp_warn("Could not clean failed duplicated plane", exc)
        try:
            if new_rig and bpy.data.objects.get(getattr(new_rig, 'name', '')) == new_rig:
                rig_mesh = getattr(new_rig, 'data', None)
                bpy.data.objects.remove(new_rig, do_unlink=True)
                if rig_mesh and getattr(rig_mesh, 'users', 0) == 0:
                    bpy.data.meshes.remove(rig_mesh)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError) as exc:
            fbp_warn("Could not clean failed duplicated rig", exc)

    def execute(self, context):
        exact_target = bpy.data.objects.get(str(getattr(self, 'rig_name', '') or ''))
        selected_rigs = (
            [exact_target]
            if exact_target and is_fbp_layer_object(exact_target)
            else get_selected_fbp_roots(context)
        )
        duplicated = []

        if not selected_rigs:
            self.report({'WARNING'}, "No Frame By Plane rig or linked plane selected")
            return {'CANCELLED'}

        for rig in selected_rigs:
            new_rig = None
            new_plane = None
            try:
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
                # The retired Layer List parenting feature must never leak into
                # new duplicates, even when an older .blend has not synced yet.
                if is_fbp_layer_object(getattr(new_rig, "parent", None)):
                    inherited_world = new_rig.matrix_world.copy()
                    new_rig.parent = None
                    new_rig.matrix_parent_inverse.identity()
                    new_rig.matrix_world = inherited_world
                new_rig.name = rig.name + "_Copy"
                new_rig.is_fbp_control = True
                new_rig.fbp_collection_name = source_collection.name if source_collection else ""
                if bool(getattr(rig, "fbp_is_drawing_plane", False)):
                    try:
                        import uuid
                        new_rig["fbp_drawing_uuid"] = uuid.uuid4().hex
                        animation_data = getattr(new_rig, "animation_data", None)
                        action = getattr(animation_data, "action", None) if animation_data else None
                        if action is not None:
                            animation_data.action = action.copy()
                    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
                        pass

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
                try:
                    if getattr(new_plane, "data", None) is not None:
                        new_plane.data["fbp_plane_mesh"] = True
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
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

                if not self._copy_materials(plane, new_plane):
                    self._cleanup_partial_duplicate(new_rig, new_plane)
                    continue
                self._copy_image_list(rig, new_rig)
                new_rig.fbp_plane_target = new_plane
                new_rig.fbp_preview_path = rig.fbp_preview_path

                # Preserve the copied effect stack but regenerate persistent per-layer
                # seeds so Unique per Layer remains unique on the duplicate.
                try:
                    from .geometry_nodes import (
                        fbp_assign_effect_layer_seed,
                        fbp_assign_mesh_wiggle_layer_seed,
                        fbp_effect_ids_for_rig,
                        fbp_reapply_all_effects,
                        fbp_sync_effect_items,
                        fbp_update_mesh_wiggle_modifier,
                    )
                    fbp_assign_mesh_wiggle_layer_seed(new_rig, force=True)
                    for effect_id in fbp_effect_ids_for_rig(new_rig):
                        fbp_assign_effect_layer_seed(new_rig, effect_id, force=True)
                    fbp_update_mesh_wiggle_modifier(new_rig)
                    fbp_reapply_all_effects(new_rig)
                    fbp_sync_effect_items(new_rig)
                except FBP_DATA_ERRORS:
                    pass

                updated = do_update_animation(new_rig)
                backend_type = fbp_layer_backend_type(new_rig)
                if backend_type.startswith('NATIVE_') and not updated:
                    raise RuntimeError('duplicated native playback contract could not be refreshed')
                if backend_type == 'CUTOUT':
                    try:
                        from .drawing_plane import fbp_drawing_render_ready
                        if not fbp_drawing_render_ready(new_rig):
                            raise RuntimeError('duplicated Cutout Plane is not render-ready')
                    except ImportError as exc:
                        raise RuntimeError('Cutout Plane validation is unavailable') from exc
                # Material copies already preserve emission and opacity. Rebuilding
                # both immediately after duplication would replace the same node
                # tree twice and repeat effect restoration for every selected layer.
                duplicated.append(new_rig)
            except Exception as exc:
                self._cleanup_partial_duplicate(new_rig, new_plane)
                fbp_warn(f"Could not duplicate layer '{getattr(rig, 'name', 'unknown')}'", exc)
                continue

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
        except FBP_DATA_IO_ERRORS:
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
        backend_types = {fbp_layer_backend_type(rig) for rig in rigs}
        if 'CUTOUT' in backend_types or 'NATIVE_MOVIE' in backend_types:
            self.report({'WARNING'}, "Cutout and Movie planes cannot be merged into a frame-list sequence")
            return {'CANCELLED'}
        active_is_color = bool(getattr(active, "fbp_is_color_plane", False))
        incompatible = [
            rig for rig in rigs
            if bool(getattr(rig, "fbp_is_color_plane", False)) != active_is_color
        ]
        if incompatible:
            self.report({'WARNING'}, "Merge image layers separately from Color/Gradient layers")
            return {'CANCELLED'}
        if active_is_color and not fbp_color_plane_can_have_frames(active):
            self.report({'WARNING'}, "Static Holdout planes cannot become animated sequences")
            return {'CANCELLED'}

        entries = []
        for rig in rigs:
            rig_entries = fbp_sequence_entries_from_rig(rig)
            if not rig_entries and active_is_color:
                plane = getattr(rig, "fbp_plane_target", None)
                material = plane.data.materials[0] if plane and len(plane.data.materials) else None
                if not material or not fbp_color_plane_can_have_frames(rig):
                    self.report({'WARNING'}, f"{rig.name} cannot be converted to an animated procedural frame")
                    return {'CANCELLED'}
                mode = getattr(rig, "fbp_color_plane_mode", "SOLID")
                rig_entries = [{
                    "name": "Gradient" if mode == 'GRADIENT' else "Color",
                    "duration": max(1, int(getattr(rig, "fbp_global_duration", 1) or 1)),
                    "is_selected": True,
                    "is_empty": False,
                    "filepath": "",
                    "procedural_kind": fbp_procedural_kind_from_material(material, mode),
                    "material": material,
                }]
            if not rig_entries:
                self.report({'WARNING'}, f"{rig.name} has no valid sequence frames to merge")
                return {'CANCELLED'}
            entries.extend(rig_entries)
        try:
            if not fbp_apply_sequence_entries_to_rig(active, entries):
                self.report({'WARNING'}, "Merge cancelled: the target sequence could not be rebuilt")
                return {'CANCELLED'}
        except Exception as exc:
            fbp_warn("Could not merge selected sequences", exc)
            self.report({'WARNING'}, "Merge cancelled: the target sequence could not be rebuilt")
            return {'CANCELLED'}

        source_rigs = [rig for rig in rigs if rig != active]
        deleted = delete_fbp_rigs(context, source_rigs)
        if deleted != len(source_rigs):
            self.report(
                {'WARNING'},
                f"Sequence merged, but only {deleted} of {len(source_rigs)} source layer(s) were deleted",
            )
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

    def _cleanup_partial_layer(self, context, new_rig, new_plane):
        """Remove only datablocks created by this split attempt."""
        try:
            if new_plane and bpy.data.objects.get(getattr(new_plane, 'name', '')) == new_plane:
                fbp_remove_plane_datablock(new_plane)
        except Exception as exc:
            fbp_warn("Could not remove partial split plane", exc)
        try:
            if new_rig and bpy.data.objects.get(getattr(new_rig, 'name', '')) == new_rig:
                rig_mesh = getattr(new_rig, 'data', None)
                bpy.data.objects.remove(new_rig, do_unlink=True)
                if rig_mesh and getattr(rig_mesh, 'users', 0) == 0:
                    bpy.data.meshes.remove(rig_mesh)
        except Exception as exc:
            fbp_warn("Could not remove partial split rig", exc)

    def execute(self, context):
        rig = context.object if context.object and is_fbp_layer_object(context.object) else None
        if not rig:
            rigs = get_selected_rigs(context)
            rig = rigs[0] if rigs else None
        if not rig or not getattr(rig, "fbp_plane_target", None):
            self.report({'WARNING'}, "Select one Frame by Plane rig")
            return {'CANCELLED'}
        backend_type = fbp_layer_backend_type(rig)
        if backend_type in {'CUTOUT', 'NATIVE_MOVIE'}:
            self.report({'WARNING'}, "Cutout and Movie planes do not support frame-list splitting")
            return {'CANCELLED'}
        plane = rig.fbp_plane_target
        entries = fbp_sequence_entries_from_rig(rig)
        selected_indices = [i for i, item in enumerate(rig.fbp_images) if item.is_selected]
        if not selected_indices:
            self.report({'WARNING'}, "Select images in the sequence list first")
            return {'CANCELLED'}
        selected_index_set = set(selected_indices)
        selected_entries = [entries[i] for i in selected_indices]
        remaining_entries = [entry for i, entry in enumerate(entries) if i not in selected_index_set]
        if not selected_entries or not remaining_entries:
            self.report({'WARNING'}, "Leave at least one image in the original plane")
            return {'CANCELLED'}

        source_collection = get_primary_fbp_collection(rig) or context.collection or context.scene.collection
        new_rig = None
        new_plane = None
        try:
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
            try:
                if getattr(new_plane, "data", None) is not None:
                    new_plane.data["fbp_plane_mesh"] = True
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
            source_collection.objects.link(new_plane)
            new_plane.parent = new_rig
            new_plane.matrix_world = plane.matrix_world.copy()
            new_plane.hide_select = plane.hide_select
            new_plane["fbp_parent_rig_name"] = new_rig.name
            new_rig.fbp_plane_target = new_plane
            new_rig.fbp_collection_name = getattr(rig, "fbp_collection_name", "")
            new_plane.fbp_collection_name = getattr(plane, "fbp_collection_name", "")

            if not fbp_apply_sequence_entries_to_rig(new_rig, selected_entries):
                raise RuntimeError("the new split sequence could not be rebuilt")
            if not fbp_apply_sequence_entries_to_rig(rig, remaining_entries):
                raise RuntimeError("the original sequence could not be rebuilt")
        except Exception as exc:
            self._cleanup_partial_layer(context, new_rig, new_plane)
            fbp_warn("Could not split selected sequence frames", exc)
            self.report({'WARNING'}, "Split cancelled; the original sequence was restored")
            sync_layer_collection(context)
            return {'CANCELLED'}

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

    rig_name: StringProperty(
        name="Layer",
        description="Optional exact layer target used by context-menu actions",
        default="",
        options={'SKIP_SAVE'},
    )

    def execute(self, context):
        exact_target = bpy.data.objects.get(str(getattr(self, 'rig_name', '') or ''))
        selected_rigs = (
            [exact_target]
            if exact_target and is_fbp_layer_object(exact_target)
            else get_selected_fbp_roots(context)
        )
        if not selected_rigs:
            idx = fbp_active_layer_index(context.scene)
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
