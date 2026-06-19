"""Focused Frame by Plane operator module."""

import bpy
import math
import os
import re
import tempfile
import time
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Operator

from .constants import FBP_PROJECT_COLLECTION_PREFIX, fbp_icon
from .path_utils import (
    clean_layer_name_from_path,
    is_supported_media_file,
    is_supported_video_file,
    is_technical_map_file,
    natural_sort_key,
)
from .builder import (
    apply_fit_to_camera,
    build_fbp_rig,
    fbp_scene_orientation_is_horizontal,
)
from .materials import (
    do_update_emission,
    do_update_opacity,
    get_or_create_fbp_gradient_preview_material,
)
from .importer import (
    fbp_begin_fast_import,
    fbp_build_project_folder,
    fbp_child_entries,
    fbp_collect_mixed_folder_entries,
    fbp_end_fast_import,
    fbp_fast_import_is_active,
    fbp_folder_direct_dirs,
    fbp_scan_project_layers_for_setup,
)
from .layers import (
    fbp_mark_layer_cache_dirty,
    fbp_resolve_rig_from_any_object,
    get_or_create_child_collection,
    get_selected_fbp_roots,
    move_object_to_collection,
    object_in_view_layer,
    set_collection_color_tag,
    set_viewport_object_color,
    sync_collection_colors_to_rigs,
)
from .scene_sync import fbp_remove_plane_datablock, sync_layer_collection
from .runtime import fbp_set_rna_property_silent, fbp_warn
from .core import (
    apply_camera_ratio_settings,
    do_update_animation,
    draw_scene_fbp_color_ramp,
    fbp_draw_color_plane_color_row,
    fbp_draw_gradient_choice_rows,
    fbp_native_sequence_files_from_rig,
    fbp_rebuild_sequence_backend_from_rig,
    fbp_replace_sequence_backend,
    fbp_rig_native_sequence_needs_rename,
)
from .operator_common import (
    _fbp_active_generation_rename_item,
    _fbp_active_pending_index_and_collection,
    _fbp_add_generation_timer,
    _fbp_build_issue,
    _fbp_clear_generation_report,
    _fbp_color_tag_for_group,
    _fbp_find_insert_index_for_pending,
    _fbp_finish_generation_ui,
    _fbp_generation_report,
    _fbp_get_or_create_collection_path,
    _fbp_mark_generation_sequence_renamed,
    _fbp_refresh_pending_tree,
    _fbp_remove_generation_timer,
    _fbp_rigs_from_report,
    _fbp_select_pending_index,
    _fbp_show_generation_start_popup,
    _fbp_store_generation_report,
    _fbp_sync_generation_rename_items,
)



def _fbp_configure_generated_camera(scene, camera_object):
    """Apply the Scene camera settings to a newly generated camera."""
    camera_data = getattr(camera_object, 'data', None)
    if not camera_data:
        return False
    projection = str(getattr(scene, 'fbp_camera_projection', 'PERSP') or 'PERSP')
    try:
        camera_data.type = 'ORTHO' if projection == 'ORTHO' else 'PERSP'
        if camera_data.type == 'ORTHO':
            camera_data.ortho_scale = max(0.001, float(getattr(scene, 'fbp_camera_ortho_scale', 10.0) or 10.0))
        else:
            camera_data.lens = max(1.0, float(getattr(scene, 'fbp_camera_lens', 50.0) or 50.0))
        clip_start = max(0.001, float(getattr(scene, 'fbp_camera_clip_start', 0.1) or 0.1))
        clip_end = max(clip_start + 0.001, float(getattr(scene, 'fbp_camera_clip_end', 1000.0) or 1000.0))
        camera_data.clip_start = clip_start
        camera_data.clip_end = clip_end
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False



class FBP_OT_ImportFolderHierarchy(Operator):
    bl_idname      = "fbp.import_folder_hierarchy"
    bl_label       = "Import from Folder"
    bl_description = "Auto-import mixed folders and single images to the Pending List"
    bl_options     = {'UNDO'}

    def execute(self, context):
        sc = context.scene
        base = bpy.path.abspath(sc.fbp_parent_import_path)
        if not os.path.isdir(base):
            self.report({'ERROR'}, "Invalid or unset directory!")
            return {'CANCELLED'}

        entries = fbp_collect_mixed_folder_entries(base)
        sc.fbp_pending_planes.clear()

        color_map = {}
        for name, directory, files, _kind in entries:
            item = sc.fbp_pending_planes.add()
            item.name = name
            item.directory = directory
            item.files_str = '|'.join(files)
            rel_folder = os.path.relpath(directory, base) if directory else "."
            # An image-only folder is a layer source, not a Blender Collection.
            # Only folders that contain child folders create a setup collection.
            if rel_folder not in {".", ""} and fbp_folder_direct_dirs(directory):
                parts = [clean_layer_name_from_path(part) for part in rel_folder.split(os.sep) if part]
                item.collection_name = " / ".join(parts)
            else:
                item.collection_name = ""
            item.follow_collection_color = bool(item.collection_name)
            color_key = (
                item.collection_name
                if item.follow_collection_color
                else f"{os.path.normcase(os.path.abspath(item.directory or base))}::{item.name}"
            )
            item.fbp_color_tag = _fbp_color_tag_for_group(color_key, color_map)

        if entries:
            self.report({'INFO'}, f"Imported {len(entries)} layer(s) from mixed folder")
        else:
            self.report({'WARNING'}, "No valid image sequences or single images found.")
        return {'FINISHED'}

class FBP_OT_AddPendingPlane(Operator):
    bl_idname      = "fbp.add_pending_plane"
    bl_label       = "Add Empty Layer"
    bl_description = "Add a new setup layer below the selected layer or inside the selected collection"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        sc = context.scene
        active_index, collection_name, _row_type = _fbp_active_pending_index_and_collection(sc)
        insert_index = _fbp_find_insert_index_for_pending(sc, active_index, collection_name)
        item = sc.fbp_pending_planes.add()
        new_index = len(sc.fbp_pending_planes) - 1
        item.name = f"Layer {new_index + 1}"
        item.collection_name = collection_name or ""
        item.fbp_color_tag = f"COLOR_{(new_index % 9) + 1:02d}"
        if 0 <= insert_index < new_index:
            sc.fbp_pending_planes.move(new_index, insert_index)
            new_index = insert_index
        _fbp_select_pending_index(context, new_index)
        return {'FINISHED'}

class FBP_OT_EditPendingPlane(Operator):
    bl_idname      = "fbp.edit_pending_plane"
    bl_label       = "Choose Images"
    bl_description = "Open file manager to assign images to this layer"

    index:     IntProperty()
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
        if not self.files:
            return {'CANCELLED'}
        sc = context.scene
        sc.fbp_last_directory = self.directory
        if 0 <= self.index < len(sc.fbp_pending_planes):
            item = sc.fbp_pending_planes[self.index]
            item.directory = self.directory
            sorted_files = sorted([f.name for f in self.files], key=natural_sort_key)
            item.files_str = "|".join(sorted_files)
            if len(sorted_files) == 1:
                item.name = clean_layer_name_from_path(sorted_files[0])
            else:
                folder_name = clean_layer_name_from_path(os.path.basename(os.path.normpath(self.directory)))
                if folder_name:
                    item.name = folder_name
        return {'FINISHED'}

class FBP_OT_MovePendingPlane(Operator):
    bl_idname      = "fbp.move_pending_plane"
    bl_label       = "Move Layer"
    bl_description = "Change the order of layers in the MultiPlane setup"

    direction: StringProperty()

    def execute(self, context):
        sc = context.scene
        idx = sc.fbp_pending_planes_idx
        new_idx = idx - 1 if self.direction == 'UP' else idx + 1
        if 0 <= new_idx < len(sc.fbp_pending_planes):
            sc.fbp_pending_planes.move(idx, new_idx)
            sc.fbp_pending_planes_idx = new_idx
            _fbp_refresh_pending_tree(context)
        return {'FINISHED'}

class FBP_OT_RemovePendingPlane(Operator):
    bl_idname      = "fbp.remove_pending_plane"
    bl_label       = "Remove Layer"
    bl_description = "Delete the selected setup layer"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        sc = context.scene
        idx, _collection_name, _row_type = _fbp_active_pending_index_and_collection(sc)
        if 0 <= idx < len(sc.fbp_pending_planes):
            sc.fbp_pending_planes.remove(idx)
            _fbp_select_pending_index(context, min(idx, max(0, len(sc.fbp_pending_planes) - 1)))
            return {'FINISHED'}
        return {'CANCELLED'}

class FBP_OT_ClearPendingPlanes(Operator):
    bl_idname      = "fbp.clear_pending_planes"
    bl_label       = "Clear List"
    bl_description = "Completely empty the MultiPlane setup"
    bl_options     = {'UNDO'}

    def execute(self, context):
        context.scene.fbp_pending_planes.clear()
        _fbp_refresh_pending_tree(context)
        return {'FINISHED'}

class FBP_OT_ScanProjectToSetup(Operator):
    bl_idname = "fbp.scan_project_to_setup"
    bl_label = "Import Project"
    bl_description = "Scan the Project Folder into the MultiPlane Setup list before generating planes"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        sc = context.scene
        base = bpy.path.abspath(getattr(sc, "fbp_project_path", "") or "")
        if not base or not os.path.isdir(base):
            self.report({'WARNING'}, "Set a valid Project Folder in Settings")
            return {'CANCELLED'}
        rows = fbp_scan_project_layers_for_setup(base)
        sc.fbp_pending_planes.clear()
        color_map = {}
        for name, collection_name, directory, files, follow_collection_color in rows:
            item = sc.fbp_pending_planes.add()
            item.name = name
            item.collection_name = collection_name
            item.directory = directory
            item.files_str = "|".join(sorted(files, key=natural_sort_key))
            item.follow_collection_color = bool(follow_collection_color)
            color_key = (
                collection_name
                if item.follow_collection_color and collection_name
                else f"{os.path.normcase(os.path.abspath(directory or base))}::{name}"
            )
            item.fbp_color_tag = _fbp_color_tag_for_group(color_key, color_map)
        sc.fbp_parent_import_path = base
        sc.fbp_pending_open_collections = ""
        _fbp_refresh_pending_tree(context)
        self.report({'INFO'}, f"Imported {len(rows)} setup row(s) from Project Folder")
        return {'FINISHED'} if rows else {'CANCELLED'}

class FBP_OT_AddPendingCollection(Operator):
    bl_idname = "fbp.add_pending_collection"
    bl_label = "Create Collection"
    bl_description = "Create a setup collection with a first empty layer"
    bl_options = {'REGISTER', 'UNDO'}

    collection_name: StringProperty(name="Collection", default="New Collection")

    def invoke(self, context, event):
        _idx, parent_collection, row_type = _fbp_active_pending_index_and_collection(context.scene)
        base = "New Collection"
        if parent_collection and row_type == 'GROUP':
            base = parent_collection + " / New Collection"
        self.collection_name = getattr(context.scene, "fbp_pending_collection_name", base) or base
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "collection_name")

    def execute(self, context):
        sc = context.scene
        collection_name = (self.collection_name or "New Collection").strip()
        if not collection_name:
            collection_name = "New Collection"
        sc.fbp_pending_collection_name = collection_name
        active_index, _collection_name, _row_type = _fbp_active_pending_index_and_collection(sc)
        insert_index = _fbp_find_insert_index_for_pending(sc, active_index, collection_name)
        item = sc.fbp_pending_planes.add()
        new_index = len(sc.fbp_pending_planes) - 1
        item.name = "New Layer"
        item.collection_name = collection_name
        item.fbp_color_tag = f"COLOR_{(new_index % 9) + 1:02d}"
        if 0 <= insert_index < new_index:
            sc.fbp_pending_planes.move(new_index, insert_index)
            new_index = insert_index
        _fbp_select_pending_index(context, new_index)
        return {'FINISHED'}

class FBP_OT_AutoSceneBuilder(Operator):
    bl_idname      = "fbp.auto_scene_builder"
    bl_label       = "Auto Build Project"
    bl_description = "Build Collections, camera and Frame by Plane layers from the Project Folder"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # Fast import is entered directly here instead of monkey-patching the class.
        if fbp_fast_import_is_active():
            return self._execute_impl(context)
        fbp_begin_fast_import(context)
        try:
            return self._execute_impl(context)
        finally:
            fbp_end_fast_import(context)

    def _execute_impl(self, context):
        sc = context.scene
        base = bpy.path.abspath(sc.fbp_project_path)
        if not base or not os.path.isdir(base):
            self.report({'WARNING'}, "Set a valid Project Folder in Settings!")
            return {'CANCELLED'}

        root_name = FBP_PROJECT_COLLECTION_PREFIX + clean_layer_name_from_path(base)
        root_coll = get_or_create_child_collection(sc.collection, root_name)
        set_collection_color_tag(root_coll, 'NONE')
        if sc.fbp_gen_camera:
            apply_camera_ratio_settings(sc)
        cursor_loc = sc.cursor.location.copy()
        depth_counter = [0]

        bpy.ops.object.select_all(action='DESELECT')

        # The project builder now behaves like the MultiPlane generator:
        # it respects the setup box settings and can create/move the camera
        # directly inside the generated project Collection.
        if sc.fbp_gen_camera:
            cam_dist = 10.0
            cam_loc = cursor_loc.copy()
            if fbp_scene_orientation_is_horizontal(sc):
                cam_loc.z += cam_dist
                bpy.ops.object.camera_add(location=cam_loc, rotation=(0, 0, 0))
            else:
                cam_loc.y -= cam_dist
                bpy.ops.object.camera_add(location=cam_loc, rotation=(math.radians(90), 0, 0))
            sc.camera = context.active_object
            _fbp_configure_generated_camera(sc, sc.camera)
            move_object_to_collection(sc.camera, root_coll)
            if sc.fbp_cam_pivot:
                sc.cursor.location = cam_loc
                context.scene.tool_settings.transform_pivot_point = 'CURSOR'

        generated = []

        top_entries = fbp_child_entries(base)
        collection_color_state = {'next': 0}
        for kind, name, full in top_entries:
            before_count = len(generated)
            if kind == 'DIR':
                generated.extend(fbp_build_project_folder(
                    context, full, root_coll, cursor_loc, depth_counter,
                    color_seed=0, depth=0, color_state=collection_color_state,
                ))
                # Leave a clearer visual gap between imported collections.
                if len(generated) > before_count:
                    depth_counter[0] += 3
            elif kind == 'IMAGE':
                # Audio and non-image files are already excluded; direct image file = root static layer.
                rig_loc = cursor_loc.copy()
                offset = sc.fbp_layer_offset * depth_counter[0]
                if fbp_scene_orientation_is_horizontal(sc):
                    rig_loc.z -= offset
                else:
                    rig_loc.y += offset
                color_index = int(collection_color_state.get('next', 0))
                collection_color_state['next'] = color_index + 1
                rig = build_fbp_rig(context, name, base, [os.path.basename(full)], rig_loc,
                                    color_tag=f"COLOR_{(color_index % 8) + 1:02d}", target_collection=root_coll,
                                    color_variant_index=color_index, follow_collection_color=False)
                rig.fbp_depth_order = depth_counter[0]
                depth_counter[0] += 1
                generated.append(rig)
            elif kind == 'IMAGE_GROUP':
                # Multiple animations inside the same root folder, e.g. An1 - 1/2 and An2 - 1/2.
                group_path, group_files = full
                rig_loc = cursor_loc.copy()
                offset = sc.fbp_layer_offset * depth_counter[0]
                if fbp_scene_orientation_is_horizontal(sc):
                    rig_loc.z -= offset
                else:
                    rig_loc.y += offset
                color_index = int(collection_color_state.get('next', 0))
                collection_color_state['next'] = color_index + 1
                rig = build_fbp_rig(context, name, group_path, group_files, rig_loc,
                                    color_tag=f"COLOR_{(color_index % 8) + 1:02d}", target_collection=root_coll,
                                    color_variant_index=color_index, follow_collection_color=False)
                rig.fbp_depth_order = depth_counter[0]
                depth_counter[0] += 1
                generated.append(rig)

        if not generated:
            self.report({'WARNING'}, "No valid image layers found in Project Folder")
            return {'CANCELLED'}

        if sc.fbp_auto_scale and sc.camera:
            context.view_layer.update()
            context.evaluated_depsgraph_get().update()
            for rig in generated:
                apply_fit_to_camera(context, rig, sc.camera)


        sync_layer_collection(context)
        sync_collection_colors_to_rigs(context)
        for rig in generated:
            if object_in_view_layer(rig, context):
                rig.select_set(True)
        if generated and object_in_view_layer(generated[-1], context):
            context.view_layer.objects.active = generated[-1]

        set_viewport_object_color(context)
        sc.fbp_show_create_tools = False
        self.report({'INFO'}, f"Auto Build Project: {len(generated)} layer(s) created")
        return {'FINISHED'}

class FBP_OT_GenerateMultiplane(Operator):
    bl_idname      = "fbp.generate_multiplane"
    bl_label       = "Generate Multiplane"
    bl_description = "Generate the full plane system in 3D space"
    bl_options     = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        _fbp_show_generation_start_popup(context, "Generating Frame By Plane Sequence")
        deferred = _fbp_add_generation_timer(context, self, delay=0.20)
        if deferred:
            return deferred
        return self._run_generation(context)

    def modal(self, context, event):
        if event.type == 'ESC':
            _fbp_remove_generation_timer(context, self)
            _fbp_store_generation_report(context, mode="Multiplane", generated_rigs=[], cancelled=True, message="Multiplane generation was cancelled before it started.")
            _fbp_finish_generation_ui(context)
            return {'CANCELLED'}
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        # Blender 5.1 does not reliably expose/compare the originating Timer
        # through the modal Event. Filtering on event.timer can therefore keep
        # this operator alive forever and prevent generation from starting.
        # The first TIMER event starts the deferred generation.
        _fbp_remove_generation_timer(context, self)
        return self._run_generation(context)

    def execute(self, context):
        # Some UI entry points, especially Shift+A popup buttons, call execute()
        # directly instead of invoke(). Defer from here too so the generation
        # popup can appear before the heavy Python import starts.
        _fbp_show_generation_start_popup(context, "Generating Frame By Plane Sequence")
        deferred = _fbp_add_generation_timer(context, self, delay=0.20)
        if deferred:
            return deferred
        return self._run_generation(context)

    def _run_generation(self, context):
        # Fast import is entered directly here instead of monkey-patching the class.
        owns_fast_import = not fbp_fast_import_is_active()
        if owns_fast_import:
            fbp_begin_fast_import(context)
        try:
            try:
                result = self._execute_impl(context)
            except Exception as exc:
                fbp_warn("Unexpected Multiplane generation failure", exc)
                _fbp_store_generation_report(
                    context,
                    mode="Multiplane",
                    generated_rigs=[],
                    cancelled=True,
                    message=f"Multiplane generation failed: {exc}",
                )
                _fbp_finish_generation_ui(context)
                self.report({'ERROR'}, f"Multiplane generation failed: {exc}")
                return {'CANCELLED'}
            if result != {'FINISHED'}:
                _fbp_store_generation_report(context, mode="Multiplane", generated_rigs=[], cancelled=True, message="Multiplane generation did not complete.")
                _fbp_finish_generation_ui(context)
            return result
        finally:
            if owns_fast_import:
                fbp_end_fast_import(context)

    def _execute_impl(self, context):
        sc = context.scene
        if not sc.fbp_pending_planes:
            self.report({'WARNING'}, "No layers added to the list!")
            return {'CANCELLED'}
        for p in sc.fbp_pending_planes:
            if not p.directory or not p.files_str:
                self.report({'ERROR'}, f"Layer '{p.name}' has no images assigned!")
                return {'CANCELLED'}

        if sc.fbp_gen_camera:
            apply_camera_ratio_settings(sc)
        cursor_loc = sc.cursor.location.copy()
        cam_dist = 10.0
        cam_loc = cursor_loc.copy()

        if fbp_scene_orientation_is_horizontal(sc):
            cam_loc.z += cam_dist
        else:
            cam_loc.y -= cam_dist

        bpy.ops.object.select_all(action='DESELECT')

        source_path = bpy.path.abspath(sc.fbp_parent_import_path) if getattr(sc, "fbp_parent_import_path", "") else ""
        coll_base_name = clean_layer_name_from_path(source_path) if source_path else "Multi Plane"
        target_collection = get_or_create_child_collection(sc.collection, FBP_PROJECT_COLLECTION_PREFIX + coll_base_name)
        set_collection_color_tag(target_collection, 'NONE')

        if sc.fbp_gen_camera:
            if fbp_scene_orientation_is_horizontal(sc):
                bpy.ops.object.camera_add(location=cam_loc, rotation=(0, 0, 0))
            else:
                bpy.ops.object.camera_add(
                    location=cam_loc, rotation=(math.radians(90), 0, 0))
            sc.camera = context.active_object
            _fbp_configure_generated_camera(sc, sc.camera)
            move_object_to_collection(sc.camera, target_collection)
            if sc.fbp_cam_pivot:
                sc.cursor.location = cam_loc
                context.scene.tool_settings.transform_pivot_point = 'CURSOR'

        cam = sc.camera
        last_rig = None
        generated_rigs = []
        generation_issues = []

        depth_index = 0
        last_collection_name = None
        color_variant_counters = {}
        collection_paths = {
            (getattr(item, "collection_name", "") or "")
            for item in sc.fbp_pending_planes
            if (getattr(item, "collection_name", "") or "")
        }
        non_leaf_collections = {
            path for path in collection_paths
            if any(other.startswith(path + " / ") for other in collection_paths)
        }
        for p_item in sc.fbp_pending_planes:
            f_list = sorted([f for f in p_item.files_str.split("|") if f], key=natural_sort_key)
            collection_name = getattr(p_item, "collection_name", "") or ""
            if collection_name and last_collection_name is not None and collection_name != last_collection_name:
                depth_index += 3
            last_collection_name = collection_name or last_collection_name

            rig_loc = cursor_loc.copy()
            offset = sc.fbp_layer_offset * depth_index
            if fbp_scene_orientation_is_horizontal(sc):
                rig_loc.z -= offset
            else:
                rig_loc.y += offset

            layer_collection = target_collection
            follows_collection = bool(
                collection_name
                and getattr(p_item, "follow_collection_color", True)
                and collection_name not in non_leaf_collections
            )
            if collection_name:
                collection_color = p_item.fbp_color_tag if follows_collection else 'NONE'
                layer_collection = _fbp_get_or_create_collection_path(
                    target_collection, collection_name, collection_color,
                )

            color_group = (
                collection_name
                if follows_collection
                else f"{os.path.normcase(os.path.abspath(p_item.directory or ''))}::{p_item.name}"
            )
            variant_index = color_variant_counters.get(color_group, 0)
            color_variant_counters[color_group] = variant_index + 1

            try:
                rig = build_fbp_rig(
                    context, p_item.name, p_item.directory, f_list, rig_loc,
                    p_item.fbp_color_tag,
                    target_collection=layer_collection,
                    color_variant_index=variant_index,
                    follow_collection_color=follows_collection,
                )
            except Exception as exc:
                fbp_warn(f"Could not generate layer '{p_item.name}'", exc)
                generation_issues.append(_fbp_build_issue(
                    p_item.name, p_item.directory, f_list,
                    f"Could not generate this layer: {exc}",
                    kind="BUILD_FAILED",
                ))
                depth_index += 1
                continue

            rig.fbp_depth_order = depth_index
            depth_index += 1

            if sc.fbp_auto_scale and cam and not fbp_fast_import_is_active():
                context.view_layer.update()
                context.evaluated_depsgraph_get().update()
                apply_fit_to_camera(context, rig, cam)

            if not fbp_fast_import_is_active():
                rig.select_set(True)
            generated_rigs.append(rig)
            last_rig = rig


        if sc.fbp_auto_scale and cam:
            context.view_layer.update()
            context.evaluated_depsgraph_get().update()
            for rig in generated_rigs:
                apply_fit_to_camera(context, rig, cam)

        if fbp_fast_import_is_active():
            for rig in generated_rigs:
                if object_in_view_layer(rig, context):
                    rig.select_set(True)

        if last_rig:
            context.view_layer.objects.active = last_rig

        sync_layer_collection(context)
        sync_collection_colors_to_rigs(context)
        set_viewport_object_color(context)
        sc.fbp_show_create_tools = False
        report = _fbp_store_generation_report(
            context,
            mode="Multiplane",
            generated_rigs=generated_rigs,
            extra_issues=generation_issues,
            cancelled=not bool(generated_rigs) and bool(generation_issues),
            message="Some layers could not be generated." if generation_issues else "",
        )
        _fbp_finish_generation_ui(context, report)
        if generation_issues:
            self.report({'WARNING'}, f"Generated {len(generated_rigs)} layer(s); {len(generation_issues)} layer(s) failed")
        return {'FINISHED'}

class FBP_OT_ImportSequence(Operator):
    bl_idname      = "fbp.import_sequence"
    bl_label       = "Select Images"
    bl_description = "Open the file manager to import a sequence"
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
        _fbp_show_generation_start_popup(context, "Generating Frame By Plane Sequence")
        deferred = _fbp_add_generation_timer(context, self, delay=0.20)
        if deferred:
            return deferred
        return self._run_generation(context)

    def modal(self, context, event):
        if event.type == 'ESC':
            _fbp_remove_generation_timer(context, self)
            _fbp_store_generation_report(context, mode="Image Sequence", generated_rigs=[], cancelled=True, message="Image sequence generation was cancelled before it started.")
            _fbp_finish_generation_ui(context)
            return {'CANCELLED'}
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        # Blender 5.1 does not reliably expose/compare the originating Timer
        # through the modal Event. Filtering on event.timer can therefore keep
        # this operator alive forever and prevent generation from starting.
        # The first TIMER event starts the deferred generation.
        _fbp_remove_generation_timer(context, self)
        return self._run_generation(context)

    def _run_generation(self, context):
        # Fast import is now entered directly here instead of monkey-patching the class at module load.
        owns_fast_import = not fbp_fast_import_is_active()
        if owns_fast_import:
            fbp_begin_fast_import(context)
        try:
            try:
                result = self._execute_impl(context)
            except Exception as exc:
                fbp_warn("Unexpected Image Sequence generation failure", exc)
                _fbp_store_generation_report(
                    context,
                    mode="Image Sequence",
                    generated_rigs=[],
                    cancelled=True,
                    message=f"Image sequence generation failed: {exc}",
                )
                _fbp_finish_generation_ui(context)
                self.report({'ERROR'}, f"Image sequence generation failed: {exc}")
                return {'CANCELLED'}
            if result != {'FINISHED'}:
                _fbp_store_generation_report(context, mode="Image Sequence", generated_rigs=[], cancelled=True, message="Image sequence generation did not complete.")
                _fbp_finish_generation_ui(context)
            return result
        finally:
            if owns_fast_import:
                fbp_end_fast_import(context)

    def _execute_impl(self, context):
        filenames = [f.name for f in self.files] if self.files else []
        if not filenames and self.filepath:
            if os.path.isfile(bpy.path.abspath(self.filepath)):
                self.directory = os.path.dirname(self.filepath)
                filenames = [os.path.basename(self.filepath)]
            elif os.path.isdir(bpy.path.abspath(self.filepath)):
                self.directory = self.filepath
        if not filenames and self.directory and os.path.isdir(bpy.path.abspath(self.directory)):
            try:
                filenames = [
                    name for name in os.listdir(bpy.path.abspath(self.directory))
                    if is_supported_media_file(name)
                    and (is_supported_video_file(name) or not is_technical_map_file(name))
                    and os.path.isfile(os.path.join(bpy.path.abspath(self.directory), name))
                ]
            except Exception:
                filenames = []
        filenames = [f for f in filenames if is_supported_media_file(f) and (is_supported_video_file(f) or not is_technical_map_file(f))]
        if not filenames:
            self.report({'WARNING'}, "SELECT AT LEAST ONE IMAGE or choose a folder containing supported media")
            return {'CANCELLED'}
        context.scene.fbp_last_directory = self.directory
        f_list = sorted(filenames, key=natural_sort_key)
        single_name = clean_layer_name_from_path(f_list[0]) if len(f_list) == 1 else clean_layer_name_from_path(os.path.basename(os.path.normpath(self.directory))) or "Sequence_Rig"
        target_collection = context.collection if context.collection else context.scene.collection
        try:
            rig = build_fbp_rig(
                context, single_name, self.directory, f_list,
                context.scene.cursor.location.copy(), target_collection=target_collection)
        except Exception as exc:
            issue = _fbp_build_issue(single_name, self.directory, f_list, f"Could not generate this sequence: {exc}")
            _fbp_store_generation_report(
                context,
                mode="Image Sequence",
                generated_rigs=[],
                cancelled=True,
                message="Image sequence generation failed.",
                extra_issues=[issue],
            )
            _fbp_finish_generation_ui(context)
            self.report({'ERROR'}, f"Image sequence import failed: {exc}")
            return {'CANCELLED'}
        bpy.ops.object.select_all(action='DESELECT')
        rig.select_set(True)
        context.view_layer.objects.active = rig
        set_viewport_object_color(context)
        context.scene.fbp_show_create_tools = False
        report = _fbp_store_generation_report(context, mode="Image Sequence", generated_rigs=[rig])
        _fbp_finish_generation_ui(context, report)
        return {'FINISHED'}

class FBP_OT_ReplaceSequence(Operator):
    bl_idname      = "fbp.replace_sequence"
    bl_label       = "Replace Sequence"
    bl_description = "Replace plane files while keeping timing and keyframes"
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
        if not self.files:
            return {'CANCELLED'}
        context.scene.fbp_last_directory = self.directory

        rig = fbp_resolve_rig_from_any_object(getattr(context, 'object', None), context)
        if not rig:
            self.report({'WARNING'}, "Select a Frame by Plane layer")
            return {'CANCELLED'}
        original_plane = getattr(rig, 'fbp_plane_target', None)
        if not original_plane:
            return {'CANCELLED'}

        plane = original_plane
        created_plane = None
        try:
            if plane.parent != rig:
                new_mesh = plane.data.copy()
                created_plane = plane.copy()
                created_plane.data = new_mesh
                context.collection.objects.link(created_plane)
                created_plane.parent = rig
                created_plane.matrix_local = plane.matrix_local
                rig.fbp_plane_target = created_plane
                plane = created_plane
                if plane.data.animation_data:
                    plane.data.animation_data_clear()

            sorted_files = sorted([f.name for f in self.files], key=natural_sort_key)
            if fbp_replace_sequence_backend(rig, self.directory, sorted_files):
                do_update_animation(rig)
                do_update_emission(rig)
                do_update_opacity(rig)
                return {'FINISHED'}
        except Exception as exc:
            fbp_warn("Could not replace image sequence backend", exc)

        if created_plane:
            try:
                rig.fbp_plane_target = original_plane
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
            try:
                fbp_remove_plane_datablock(created_plane)
            except Exception as exc:
                fbp_warn("Could not remove partial replacement plane", exc)

        self.report({'WARNING'}, "Could not replace image sequence backend; previous sequence restored")
        return {'CANCELLED'}

class FBP_OT_RenameSequenceForBlender(Operator):
    bl_idname = "fbp.rename_sequence_for_blender"
    bl_label = "Rename Sequence for Blender"
    bl_description = "Rename the original image files to a simple consecutive pattern that Blender's native Image Sequence reader can load reliably"
    bl_options = {'REGISTER'}

    prefix: StringProperty(
        name="Prefix",
        description="New filename prefix. Files will become Prefix_0001.png, Prefix_0002.png, etc.",
        default="fbp"
    )
    start_index: IntProperty(
        name="Start",
        description="First frame number to use in the renamed files",
        default=1,
        min=0
    )
    digits: IntProperty(
        name="Digits",
        description="Number padding used in the renamed files",
        default=4,
        min=3,
        max=8
    )
    apply_to_selected: BoolProperty(
        name="Selected Rigs",
        description="Rename problematic sequences on all selected Frame by Plane rigs instead of only the active rig",
        default=False
    )

    def _safe_prefix(self, value):
        value = str(value or "fbp")
        value = re.sub(r"[^0-9A-Za-z_\-]+", "_", value).strip("._- ")
        return value or "fbp"

    def _active_rig(self, context):
        return fbp_resolve_rig_from_any_object(getattr(context, 'object', None), context)

    def _target_rigs(self, context):
        if self.apply_to_selected:
            rigs = get_selected_fbp_roots(context)
            return [rig for rig in rigs if rig and not getattr(rig, 'fbp_is_color_plane', False)]
        rig = self._active_rig(context)
        return [rig] if rig and not getattr(rig, 'fbp_is_color_plane', False) else []

    def invoke(self, context, event):
        rig = self._active_rig(context)
        if rig:
            self.prefix = self._safe_prefix(getattr(rig, 'name', 'fbp'))
        self.apply_to_selected = len(get_selected_fbp_roots(context)) > 1
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        layout = self.layout
        layout.label(text="This renames the original files on disk.", icon='ERROR')
        layout.label(text="No cache copies will be created.", icon='INFO')
        col = layout.column(align=True)
        col.prop(self, "apply_to_selected")
        col.prop(self, "prefix")
        row = col.row(align=True)
        row.prop(self, "start_index")
        row.prop(self, "digits")
        rig = self._active_rig(context)
        if rig and fbp_rig_native_sequence_needs_rename(rig):
            layout.label(text="Recommended: this sequence may show pink until renamed.", icon='QUESTION')

    @staticmethod
    def _normalized_path(path):
        try:
            return os.path.normcase(os.path.abspath(bpy.path.abspath(str(path or ""))))
        except Exception:
            return os.path.normcase(os.path.abspath(str(path or "")))

    def _rig_item_source_path(self, rig, item):
        raw = str(getattr(item, 'filepath', '') or '')
        if raw:
            return self._normalized_path(raw)
        directory, _files = fbp_native_sequence_files_from_rig(rig)
        name = str(getattr(item, 'name', '') or '')
        return self._normalized_path(os.path.join(directory, name)) if directory and name else ""

    def _rename_one_rig(self, rig, context):
        directory, files = fbp_native_sequence_files_from_rig(rig)
        if not directory or len(files) <= 1:
            return False, "No image sequence found"

        abs_sources = []
        for filename in files:
            raw_path = str(filename or "")
            path = raw_path if os.path.isabs(raw_path) else os.path.join(directory, raw_path)
            abs_sources.append(os.path.abspath(bpy.path.abspath(path)))
        if not all(os.path.isfile(path) for path in abs_sources):
            return False, "Some source files are missing"
        normalized_sources = [self._normalized_path(path) for path in abs_sources]
        if len(set(normalized_sources)) != len(normalized_sources):
            return False, "The source sequence contains duplicate file references"
        source_directories = {
            os.path.normcase(os.path.dirname(path))
            for path in abs_sources
        }
        if len(source_directories) != 1:
            return False, "Frames from multiple folders cannot be renamed as one disk sequence"
        # Always derive the target folder from the validated files. Source
        # metadata may contain an outdated or relative directory value.
        directory = os.path.dirname(abs_sources[0])

        exts = {os.path.splitext(path)[1].lower() for path in abs_sources}
        if len(exts) != 1:
            return False, "Mixed file extensions cannot be renamed as one native sequence"

        prefix = self._safe_prefix(self.prefix or getattr(rig, 'name', 'fbp'))
        ext = os.path.splitext(abs_sources[0])[1]
        width = max(int(self.digits), len(str(int(self.start_index) + len(abs_sources) - 1)))
        targets = [
            os.path.join(directory, f"{prefix}_{int(self.start_index) + index:0{width}d}{ext}")
            for index in range(len(abs_sources))
        ]

        norm_sources = {self._normalized_path(path) for path in abs_sources}
        for target in targets:
            norm_target = self._normalized_path(target)
            if os.path.exists(target) and norm_target not in norm_sources:
                return False, f"Target already exists: {os.path.basename(target)}"

        if [self._normalized_path(p) for p in abs_sources] == [self._normalized_path(p) for p in targets]:
            return False, "Files are already using the requested pattern"

        rename_map = {
            self._normalized_path(source): target
            for source, target in zip(abs_sources, targets, strict=True)
        }

        # Find every FBP rig that references these source files before changing
        # anything on disk. Shared sequences must be updated together or the
        # other rigs would keep stale paths and turn pink.
        affected_rigs = []
        for candidate in list(bpy.data.objects):
            if not getattr(candidate, 'is_fbp_control', False) or getattr(candidate, 'fbp_is_color_plane', False):
                continue
            try:
                if any(self._rig_item_source_path(candidate, item) in rename_map for item in candidate.fbp_images):
                    affected_rigs.append(candidate)
            except Exception:
                continue
        if rig not in affected_rigs:
            affected_rigs.append(rig)

        snapshots = []
        for affected in affected_rigs:
            snapshots.append((
                affected,
                [
                    {
                        'name': str(getattr(item, 'name', 'Image') or 'Image'),
                        'duration': max(1, int(getattr(item, 'duration', 1) or 1)),
                        'is_selected': bool(getattr(item, 'is_selected', False)),
                        'is_empty': bool(getattr(item, 'is_empty', False)),
                        'filepath': str(getattr(item, 'filepath', '') or ''),
                        'procedural_kind': str(getattr(item, 'procedural_kind', 'AUTO') or 'AUTO'),
                    }
                    for item in affected.fbp_images
                ],
                int(getattr(affected, 'fbp_images_index', 0) or 0),
                str(getattr(affected, 'fbp_preview_path', '') or ''),
            ))

        def restore_rig_snapshot(affected, rows, active_index, preview_path):
            affected.fbp_images.clear()
            for data in rows:
                item = affected.fbp_images.add()
                item.name = data['name']
                fbp_set_rna_property_silent(item, 'duration', data['duration'])
                item.is_selected = data['is_selected']
                item.is_empty = data['is_empty']
                item.filepath = data['filepath']
                try:
                    item.procedural_kind = data['procedural_kind']
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                    pass
            affected.fbp_images_index = max(
                0,
                min(active_index, max(0, len(affected.fbp_images) - 1)),
            )
            affected.fbp_preview_path = preview_path

        def rollback_disk_names():
            rollback_errors = []
            rollback_stamp = str(int(time.time() * 1000))
            rollback_pairs = []
            for index, (target, source) in enumerate(zip(targets, abs_sources, strict=True)):
                tmp = os.path.join(
                    directory,
                    f".fbp_rollback_{rollback_stamp}_{index}_{os.path.basename(target)}",
                )
                try:
                    if not os.path.exists(target):
                        raise FileNotFoundError(target)
                    os.rename(target, tmp)
                    rollback_pairs.append((tmp, source))
                except Exception as exc:
                    rollback_errors.append(f"{os.path.basename(target)}: {exc}")
            for tmp, source in rollback_pairs:
                try:
                    os.rename(tmp, source)
                except Exception as exc:
                    rollback_errors.append(f"{os.path.basename(source)}: {exc}")
            return rollback_errors

        stamp = str(int(time.time() * 1000))
        temps = [os.path.join(directory, f".fbp_tmp_{stamp}_{i}_{os.path.basename(src)}") for i, src in enumerate(abs_sources)]

        moved_to_temp = []
        moved_to_target = []
        try:
            for src, tmp in zip(abs_sources, temps, strict=True):
                os.rename(src, tmp)
                moved_to_temp.append((tmp, src))
            for tmp, target in zip(temps, targets, strict=True):
                os.rename(tmp, target)
                moved_to_target.append((target, tmp))
        except Exception as exc:
            for target, tmp in reversed(moved_to_target):
                try:
                    if os.path.exists(target) and not os.path.exists(tmp):
                        os.rename(target, tmp)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                    pass
            for tmp, src in reversed(moved_to_temp):
                try:
                    if os.path.exists(tmp) and not os.path.exists(src):
                        os.rename(tmp, src)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                    pass
            return False, f"Rename failed: {exc}"

        refresh_errors = []
        for affected in affected_rigs:
            try:
                for item in affected.fbp_images:
                    old_key = self._rig_item_source_path(affected, item)
                    target = rename_map.get(old_key)
                    if not target:
                        continue
                    item.name = os.path.basename(target)
                    item.filepath = target

                preview_key = self._normalized_path(getattr(affected, 'fbp_preview_path', ''))
                if preview_key in rename_map:
                    affected.fbp_preview_path = rename_map[preview_key]
                elif affected == rig:
                    affected.fbp_preview_path = targets[0]

                if not fbp_rebuild_sequence_backend_from_rig(affected):
                    raise RuntimeError('native sequence rebuild returned False')
                do_update_animation(affected)
                do_update_emission(affected)
                do_update_opacity(affected)
            except Exception as exc:
                refresh_errors.append(f"{getattr(affected, 'name', 'Rig')}: {exc}")
                break

        if refresh_errors:
            disk_rollback_errors = rollback_disk_names()
            rig_rollback_errors = []
            for affected, rows, active_index, preview_path in snapshots:
                try:
                    restore_rig_snapshot(affected, rows, active_index, preview_path)
                    if not fbp_rebuild_sequence_backend_from_rig(affected):
                        raise RuntimeError('restored native sequence rebuild returned False')
                    do_update_animation(affected)
                    do_update_emission(affected)
                    do_update_opacity(affected)
                except Exception as exc:
                    rig_rollback_errors.append(f"{getattr(affected, 'name', 'Rig')}: {exc}")
            try:
                fbp_mark_layer_cache_dirty(context)
            except Exception as exc:
                fbp_warn("Could not refresh the layer cache after rename rollback", exc)

            details = refresh_errors[:1]
            if disk_rollback_errors:
                details.append("Disk rollback errors: " + "; ".join(disk_rollback_errors[:2]))
            if rig_rollback_errors:
                details.append("Rig rollback errors: " + "; ".join(rig_rollback_errors[:2]))
            return False, "Rename cancelled and previous names restored. " + " | ".join(details)

        for affected in affected_rigs:
            _fbp_mark_generation_sequence_renamed(
                context,
                getattr(affected, 'name', ''),
                files=[os.path.basename(path) for path in targets],
            )

        try:
            fbp_mark_layer_cache_dirty(context)
        except Exception as exc:
            fbp_warn("Could not refresh the layer cache after renaming", exc)

        shared_count = max(0, len(affected_rigs) - 1)
        suffix = f" and updated {shared_count} shared rig(s)" if shared_count else ""
        return True, f"Renamed {len(targets)} files{suffix}"

    def execute(self, context):
        rigs = self._target_rigs(context)
        if not rigs:
            self.report({'WARNING'}, "Select a Frame by Plane image sequence rig")
            return {'CANCELLED'}

        renamed = 0
        errors = []
        seen_sources = set()
        for rig in rigs:
            directory, files = fbp_native_sequence_files_from_rig(rig)
            signature = tuple(self._normalized_path(os.path.join(directory, name)) for name in files) if directory else ()
            if signature and signature in seen_sources:
                continue
            if signature:
                seen_sources.add(signature)
            ok, message = self._rename_one_rig(rig, context)
            if ok:
                renamed += 1
            else:
                errors.append(f"{getattr(rig, 'name', 'Rig')}: {message}")

        if errors:
            self.report({'WARNING'}, "; ".join(errors[:3]))
        if renamed:
            self.report({'INFO'}, f"Renamed {renamed} sequence(s) for Blender native playback")
            return {'FINISHED'}
        return {'CANCELLED'}

class FBP_UL_GenerationRenameList(bpy.types.UIList):
    bl_idname = "FBP_UL_generation_rename_list"

    def draw_item(self, context, layout, data, item, icon, _active_data, _active_propname, index=0, _flt_flag=0):
        # Keep every row compact and selectable: one status icon + one sequence name.
        # Details for the selected row are shown once below the list.
        status_icon = 'CHECKMARK' if getattr(item, 'is_renamed', False) else 'ERROR'
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.label(text=getattr(item, 'display_name', '') or getattr(item, 'rig_name', '') or 'Sequence', icon=status_icon)
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon=status_icon)

class FBP_OT_GenerationReportPopup(Operator):
    bl_idname = "fbp.generation_report_popup"
    bl_label = "Frame by Plane Generation Report"
    bl_description = "Show the result of the last Frame by Plane generation"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        _fbp_sync_generation_rename_items(context)
        report = _fbp_generation_report(context)
        status = report.get("status", "SUCCESS")
        width = 360 if status == "SUCCESS" else 580
        title = {
            "SUCCESS": "Generation Completed",
            "WARNING": "Import Completed with Warnings",
            "CANCELLED": "Generation Cancelled",
        }.get(status, "Frame by Plane Generation Report")
        return context.window_manager.invoke_props_dialog(
            self,
            width=width,
            title=title,
            confirm_text="Let's Go",
            cancel_default=False,
        )

    def execute(self, context):
        _fbp_clear_generation_report(context)
        return {'FINISHED'}

    def cancel(self, context):
        _fbp_clear_generation_report(context)

    def draw(self, context):
        layout = self.layout
        report = _fbp_generation_report(context)
        status = report.get("status", "SUCCESS")
        mode = report.get("mode", "Sequence")
        planes = int(report.get("planes_created", 0) or 0)
        issues = list(report.get("issues", []) or [])

        if status == "SUCCESS":
            layout.label(text="Everything is ready.", icon='CHECKMARK')
            layout.label(text=f"{mode}: {planes} plane(s) generated successfully.")
            return

        if status == "WARNING":
            active_issues = [issue for issue in issues if issue.get("kind") != "RENAMED_SEQUENCE"]
            if active_issues:
                layout.label(text=f"{mode}: {planes} plane(s) generated, {len(active_issues)} item(s) need attention.", icon='ERROR')
            else:
                layout.label(text=f"{mode}: {planes} plane(s) generated. All reported sequences were renamed.", icon='CHECKMARK')

            if report.get("rename_rigs", []) or report.get("renamed_rigs", []):
                items = context.scene.fbp_generation_rename_items
                box = layout.box()
                box.label(text="Sequences that may need renaming:", icon='SEQUENCE')
                box.template_list(
                    "FBP_UL_generation_rename_list",
                    "report",
                    context.scene,
                    "fbp_generation_rename_items",
                    context.scene,
                    "fbp_generation_rename_index",
                    rows=max(3, min(7, len(items) or 3)),
                )
                item = _fbp_active_generation_rename_item(context)
                if item:
                    details = box.box()
                    renamed = bool(getattr(item, 'is_renamed', False))
                    details.label(
                        text=f"Selected: {getattr(item, 'display_name', '') or getattr(item, 'rig_name', '')}",
                        icon='CHECKMARK' if renamed else 'ERROR',
                    )
                    msg = getattr(item, 'message', '') or ("Renamed successfully" if renamed else "Needs rename")
                    details.label(text=msg, icon='CHECKMARK' if renamed else 'INFO')
                    files = getattr(item, 'preview_files', '')
                    if files:
                        details.label(text=f"Files: {files}", icon='FILE_IMAGE')

            other_issues = [issue for issue in issues if issue.get("kind") not in {"RENAME_SEQUENCE", "RENAMED_SEQUENCE"}]
            if other_issues:
                box = layout.box()
                box.label(text="Other problematic items:", icon='INFO')
                for issue in other_issues[:6]:
                    rig_name = issue.get("rig", "Layer")
                    message = issue.get("message", "Needs attention")
                    box.label(text=f"• {rig_name}: {message}")
                if len(other_issues) > 6:
                    box.label(text=f"...and {len(other_issues) - 6} more.")

            actions = layout.row(align=True)
            actions.operator_context = 'EXEC_DEFAULT'
            if issues:
                actions.operator("fbp.remove_corrupted_generated_planes", text="Remove Corrupted Planes", icon='TRASH')
                if report.get("rename_rigs", []) or report.get("renamed_rigs", []):
                    rename_row = actions.row(align=True)
                    selected_item = _fbp_active_generation_rename_item(context)
                    rename_row.enabled = not bool(getattr(selected_item, 'is_renamed', False))
                    rename_row.operator("fbp.rename_generation_problem_sequence", text="Fix Selected", icon=fbp_icon("FOLDER_REDIRECT"))
            actions.operator("fbp.clear_generation_report", text="", icon='TRASH')
            layout.label(text="Choose a fix above, or press Let's Go to keep the imported planes.", icon='INFO')
            return

        if status == "CANCELLED":
            message = report.get("message", "No planes were generated.")
            layout.label(text=message, icon='CANCEL')
            return

        layout.label(text="Generation finished.", icon='INFO')

class FBP_OT_RemoveCorruptedGeneratedPlanes(Operator):
    bl_idname = "fbp.remove_corrupted_generated_planes"
    bl_label = "Remove Corrupted Planes"
    bl_description = "Delete the generated planes that were reported as missing or unsafe"
    bl_options = {'REGISTER'}

    def execute(self, context):
        rigs = _fbp_rigs_from_report(context, "problem_rigs")
        if not rigs:
            self.report({'WARNING'}, "No reported generated planes to remove")
            return {'CANCELLED'}
        rig_names = [getattr(rig, 'name', '') for rig in rigs if rig]
        _fbp_clear_generation_report(context)
        from .scene_sync import schedule_delete_fbp_rigs
        scheduled = schedule_delete_fbp_rigs(rig_names, first_interval=0.35)
        if not scheduled:
            self.report({'WARNING'}, "Could not schedule safe corrupted-plane removal")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Removing {len(rig_names)} generated plane(s) safely")
        return {'FINISHED'}

class FBP_OT_RenameGenerationProblemSequence(Operator):
    bl_idname = "fbp.rename_generation_problem_sequence"
    bl_label = "Rename Selected Sequence"
    bl_description = "Open the safe rename popup for the selected sequence in the generation report"
    bl_options = {'REGISTER'}

    def _selected_rig(self, context):
        if not getattr(context.scene, 'fbp_generation_rename_items', None):
            _fbp_sync_generation_rename_items(context)
        item = _fbp_active_generation_rename_item(context)
        if item:
            rig = bpy.data.objects.get(getattr(item, 'rig_name', ''))
            if rig and not getattr(rig, 'fbp_is_color_plane', False):
                return rig

        rigs = _fbp_rigs_from_report(context, "rename_rigs")
        if not rigs:
            rigs = _fbp_rigs_from_report(context, "problem_rigs")
        rigs = [rig for rig in rigs if rig and not getattr(rig, 'fbp_is_color_plane', False)]
        return rigs[0] if rigs else None

    def invoke(self, context, event):
        # If this operator is called outside the report popup, still use the
        # selected UIList item instead of opening a second non-clickable list.
        return self.execute(context)

    def execute(self, context):
        item = _fbp_active_generation_rename_item(context)
        if item and getattr(item, 'is_renamed', False):
            self.report({'INFO'}, "This sequence has already been renamed")
            return {'CANCELLED'}

        rig = self._selected_rig(context)
        if not rig:
            self.report({'WARNING'}, "No reported image sequence can be renamed")
            return {'CANCELLED'}

        bpy.ops.object.select_all(action='DESELECT')
        if object_in_view_layer(rig, context):
            rig.select_set(True)
            context.view_layer.objects.active = rig
        self.report({'INFO'}, f"Opening rename tool for {rig.name}")
        try:
            return bpy.ops.fbp.rename_sequence_for_blender('INVOKE_DEFAULT')
        except Exception:
            return bpy.ops.fbp.rename_sequence_for_blender()

class FBP_OT_ClearGenerationReport(Operator):
    bl_idname = "fbp.clear_generation_report"
    bl_label = "Clear Generation Report"
    bl_description = "Clear the last generation report"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        _fbp_clear_generation_report(context)
        return {'FINISHED'}

class FBP_OT_ImportSingleImage(Operator):
    bl_idname = "fbp.import_single_image"
    bl_label = "Single Plane"
    bl_description = "Create one Frame by Plane layer from one image/video, or one animated plane from multiple selected images"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')
    directory: StringProperty(subtype='DIR_PATH')
    files: CollectionProperty(type=bpy.types.OperatorFileListElement)

    def invoke(self, context, event):
        path = context.scene.fbp_project_path or context.scene.fbp_last_directory
        if path:
            self.directory = path
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        filenames = [f.name for f in self.files] if self.files else []
        if not filenames and self.filepath:
            if os.path.isfile(bpy.path.abspath(self.filepath)):
                self.directory = os.path.dirname(self.filepath)
                filenames = [os.path.basename(self.filepath)]
            elif os.path.isdir(bpy.path.abspath(self.filepath)):
                self.directory = self.filepath

        # If the file browser is left on a folder and no file is explicitly
        # selected, import the supported direct media in that folder as one plane.
        # This avoids silently creating an empty/square plane from Shift+A.
        if not filenames and self.directory and os.path.isdir(bpy.path.abspath(self.directory)):
            try:
                filenames = [
                    name for name in os.listdir(bpy.path.abspath(self.directory))
                    if is_supported_media_file(name)
                    and (is_supported_video_file(name) or not is_technical_map_file(name))
                    and os.path.isfile(os.path.join(bpy.path.abspath(self.directory), name))
                ]
            except Exception:
                filenames = []

        filenames = [f for f in filenames if is_supported_media_file(f) and (is_supported_video_file(f) or not is_technical_map_file(f))]
        if not filenames:
            self.report({'WARNING'}, "SELECT AT LEAST ONE IMAGE or choose a folder containing supported media")
            return {'CANCELLED'}
        context.scene.fbp_last_directory = self.directory
        sorted_files = sorted(filenames, key=natural_sort_key)
        if len(sorted_files) == 1:
            rig_name = clean_layer_name_from_path(sorted_files[0])
        else:
            rig_name = clean_layer_name_from_path(os.path.basename(os.path.normpath(self.directory))) or clean_layer_name_from_path(sorted_files[0]) or "Sequence_Rig"
        target_collection = context.collection if context.collection else context.scene.collection
        try:
            rig = build_fbp_rig(
                context, rig_name, self.directory, sorted_files,
                context.scene.cursor.location.copy(), target_collection=target_collection)
        except Exception as exc:
            issue = _fbp_build_issue(rig_name, self.directory, sorted_files, f"Could not generate this layer: {exc}")
            _fbp_store_generation_report(
                context,
                mode="Single Plane",
                generated_rigs=[],
                cancelled=True,
                message="Single plane generation failed.",
                extra_issues=[issue],
            )
            _fbp_finish_generation_ui(context)
            self.report({'ERROR'}, f"Single plane import failed: {exc}")
            return {'CANCELLED'}
        bpy.ops.object.select_all(action='DESELECT')
        if object_in_view_layer(rig, context):
            rig.select_set(True)
            context.view_layer.objects.active = rig
        set_viewport_object_color(context)
        if len(sorted_files) > 1:
            self.report({'INFO'}, f"Imported {len(sorted_files)} images as one animated plane")
        return {'FINISHED'}

class FBP_OT_ImportFolderMultiplane(Operator):
    bl_idname = "fbp.import_folder_multiplane"
    bl_label = "Multiplane"
    bl_description = "Create a multiplane setup directly from a folder"
    bl_options = {'REGISTER', 'UNDO'}

    animation: BoolProperty(default=True)
    filepath: StringProperty(subtype='FILE_PATH')
    directory: StringProperty(subtype='DIR_PATH')
    files: CollectionProperty(type=bpy.types.OperatorFileListElement)

    def invoke(self, context, event):
        path = context.scene.fbp_project_path or context.scene.fbp_last_directory
        if path:
            self.directory = path
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        base = self.directory or (os.path.dirname(self.filepath) if self.filepath else "")
        base = bpy.path.abspath(base)
        if not base or not os.path.isdir(base):
            self.report({'WARNING'}, "Choose a valid folder")
            return {'CANCELLED'}
        sc = context.scene
        rows = fbp_scan_project_layers_for_setup(base)
        if not self.animation:
            rows = [(name, coll, directory, files[:1], follow) for name, coll, directory, files, follow in rows if files]
        if not rows:
            self.report({'WARNING'}, "No supported images found")
            return {'CANCELLED'}
        sc.fbp_creation_mode = 'MULTI'
        sc.fbp_parent_import_path = base
        sc.fbp_pending_planes.clear()
        color_map = {}
        for name, collection_name, directory, files, follow_collection_color in rows:
            item = sc.fbp_pending_planes.add()
            item.name = name
            item.collection_name = collection_name
            item.directory = directory
            item.files_str = "|".join(sorted(files, key=natural_sort_key))
            item.follow_collection_color = bool(follow_collection_color)
            color_key = (
                collection_name
                if item.follow_collection_color and collection_name
                else f"{os.path.normcase(os.path.abspath(directory or base))}::{name}"
            )
            item.fbp_color_tag = _fbp_color_tag_for_group(color_key, color_map)
        return bpy.ops.fbp.generate_multiplane()

class FBP_OT_PopupSinglePlane(Operator):
    bl_idname = "fbp.popup_single_plane"
    bl_label = "Single Plane"
    bl_description = "Quick setup, then choose an image for a single plane"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        # Prepare the preview material outside draw(), otherwise Blender may reject ID writes
        # while the popup UI is being rendered.
        try:
            get_or_create_fbp_gradient_preview_material(context.scene)
        except Exception as exc:
            fbp_warn("Could not prepare gradient preview ColorRamp for popup", exc)
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        sc = context.scene
        layout = self.layout
        layout.label(text="Single Plane", icon=fbp_icon("IMAGE_DATA"))
        layout.prop(sc, "fbp_pre_orientation", text="Orientation")
        layout.prop(sc, "fbp_pre_shadeless", text="Emission Texture", icon=fbp_icon("LIGHT_SUN"))
        layout.prop(sc, "fbp_pre_interpolation", text="Filter")

    def execute(self, context):
        return bpy.ops.fbp.import_single_image('INVOKE_DEFAULT')

class FBP_OT_PopupSinglePlaneAnimation(Operator):
    bl_idname = "fbp.popup_single_plane_animation"
    bl_label = "Single Plane Animation"
    bl_description = "Quick setup, then choose images for one animated plane"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=380)

    def draw(self, context):
        sc = context.scene
        layout = self.layout
        layout.label(text="Single Plane Animation", icon=fbp_icon("FILE_IMAGE"))
        row = layout.row(align=True)
        row.prop(sc, "fbp_pre_duration", text="Frame Duration")
        row.prop(sc, "fbp_pre_shadeless", text="Emission Texture", icon=fbp_icon("LIGHT_SUN"), toggle=True)
        layout.prop(sc, "fbp_pre_loop_mode", text="Playback")
        layout.prop(sc, "fbp_pre_interpolation", text="Filter")
        layout.prop(sc, "fbp_pre_orientation", text="Orientation")

    def execute(self, context):
        return bpy.ops.fbp.import_sequence('INVOKE_DEFAULT')

class FBP_OT_PopupMultiplane(Operator):
    bl_idname = "fbp.popup_multiplane"
    bl_label = "Multiplane"
    bl_description = "Quick multiplane setup. Use Send To N-Panel for advanced setup review"
    bl_options = {'REGISTER', 'UNDO'}

    animation: BoolProperty(default=True)
    send_to_panel: BoolProperty(name="Send To N-Panel", default=False)
    folder: StringProperty(name="Folder", subtype='DIR_PATH', default="")

    def invoke(self, context, event):
        self.folder = context.scene.fbp_project_path or context.scene.fbp_parent_import_path or context.scene.fbp_last_directory
        return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, context):
        sc = context.scene
        layout = self.layout
        layout.label(text="Multiplane Animation" if self.animation else "Multiplane", icon=fbp_icon("RENDERLAYERS") if self.animation else 'MESH_PLANE')
        layout.prop(self, "folder", text="Folder")
        row = layout.row(align=True)
        row.prop(sc, "fbp_pre_duration", text="Frame Duration")
        row.prop(sc, "fbp_pre_shadeless", text="Emission Texture", icon=fbp_icon("LIGHT_SUN"), toggle=True)
        layout.prop(sc, "fbp_pre_loop_mode", text="Playback")
        layout.prop(sc, "fbp_pre_interpolation", text="Filter")
        layout.prop(sc, "fbp_pre_orientation", text="Orientation")
        layout.separator()
        layout.prop(sc, "fbp_gen_camera", text="Generate Camera", icon=fbp_icon("VIEW_CAMERA"))
        layout.prop(sc, "fbp_layer_offset", text="Plane Distance")
        layout.prop(sc, "fbp_auto_scale", text="Fit to Camera", icon=fbp_icon("FULLSCREEN_ENTER"))
        layout.prop(self, "send_to_panel", text="Send To N-Panel")

    def execute(self, context):
        base = bpy.path.abspath(self.folder or "")
        if not base or not os.path.isdir(base):
            self.report({'WARNING'}, "Choose a valid folder")
            return {'CANCELLED'}
        sc = context.scene
        sc.fbp_creation_mode = 'MULTI'
        sc.fbp_parent_import_path = base
        sc.fbp_project_path = base
        rows = fbp_scan_project_layers_for_setup(base)
        if not self.animation:
            rows = [(name, coll, directory, files[:1], follow) for name, coll, directory, files, follow in rows if files]
        sc.fbp_pending_planes.clear()
        color_map = {}
        for name, collection_name, directory, files, follow_collection_color in rows:
            item = sc.fbp_pending_planes.add()
            item.name = name
            item.collection_name = collection_name
            item.directory = directory
            item.files_str = "|".join(sorted(files, key=natural_sort_key))
            item.follow_collection_color = bool(follow_collection_color)
            color_key = (
                collection_name
                if item.follow_collection_color and collection_name
                else f"{os.path.normcase(os.path.abspath(directory or base))}::{name}"
            )
            item.fbp_color_tag = _fbp_color_tag_for_group(color_key, color_map)
        sc.fbp_pending_open_collections = ""
        if self.send_to_panel:
            self.report({'INFO'}, f"Sent {len(rows)} layer(s) to the N-Panel Multiplane Setup")
            return {'FINISHED'}
        if not rows:
            self.report({'WARNING'}, "No supported images found")
            return {'CANCELLED'}
        return bpy.ops.fbp.generate_multiplane()

class FBP_OT_PopupColorPlane(Operator):
    bl_idname = "fbp.popup_color_plane"
    bl_label = "Color Plane"
    bl_description = "Create a camera-ratio color, gradient or holdout plane"
    bl_options = {'REGISTER', 'UNDO'}

    preset_type: StringProperty(default="")

    def invoke(self, context, event):
        if self.preset_type in {'CUSTOM', 'GRADIENT', 'HOLDOUT'}:
            context.scene.fbp_color_plane_type = self.preset_type
        # Prepare the preview material outside draw(), otherwise Blender may reject ID writes
        # while the popup UI is being rendered.
        try:
            get_or_create_fbp_gradient_preview_material(context.scene)
        except Exception as exc:
            fbp_warn("Could not prepare gradient preview ColorRamp for popup", exc)
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        sc = context.scene
        layout = self.layout
        title = "Gradient Plane" if sc.fbp_color_plane_type == 'GRADIENT' else ("Holdout Plane" if sc.fbp_color_plane_type == 'HOLDOUT' else "Color Plane")
        layout.label(text=title, icon=fbp_icon("MATERIAL"))
        row = layout.row(align=False)
        split = row.split(factor=0.78, align=False)
        type_row = split.row(align=True)
        type_row.prop(sc, "fbp_color_plane_type", expand=True)
        emiss = split.row(align=True)
        emiss.enabled = sc.fbp_color_plane_type != 'HOLDOUT'
        emiss.prop(sc, "fbp_color_plane_emission", text="", icon=fbp_icon("LIGHT_SUN"), toggle=True)
        if sc.fbp_color_plane_type == 'CUSTOM':
            fbp_draw_color_plane_color_row(layout, sc)
        elif sc.fbp_color_plane_type == 'GRADIENT':
            fbp_draw_gradient_choice_rows(layout, sc)
            draw_scene_fbp_color_ramp(layout, sc)
            gbox = layout.box()
            row = gbox.row(align=True)
            row.label(text="Position", icon=fbp_icon("EMPTY_ARROWS"))
            row = gbox.row(align=True)
            row.prop(sc, "fbp_gradient_offset_x", text="X")
            row.prop(sc, "fbp_gradient_offset_y", text="Y")
            row = gbox.row(align=True)
            row.prop(sc, "fbp_gradient_scale_x", text="Scale X")
            row.prop(sc, "fbp_gradient_scale_y", text="Scale Y")
            gbox.prop(sc, "fbp_gradient_rotation", text="Rotation")
        layout.prop(sc, "fbp_pre_orientation", text="Orientation")

    def execute(self, context):
        return bpy.ops.fbp.create_color_plane()

class FBP_OT_CreateColorPlaneFromHex(Operator):
    bl_idname = "fbp.create_color_plane_from_hex"
    bl_label = "Color Plane from Hex Color Code"
    bl_description = "Create a solid Color Plane from a hexadecimal color code copied from another app or website"
    bl_options = {'REGISTER', 'UNDO'}

    hex_color: StringProperty(
        name="Hex Color",
        description="Hexadecimal color code, for example #FFCC00 or FFCC00FF",
        default="#FFFFFF")

    def invoke(self, context, event):
        clip = getattr(context.window_manager, 'clipboard', '') or ''
        clip = clip.strip().strip('"').strip("'")
        if clip.startswith('#') or (len(clip) in {6, 8} and all(c in '0123456789abcdefABCDEF' for c in clip)):
            self.hex_color = clip
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "hex_color")
        layout.prop(context.scene, "fbp_pre_orientation", text="Orientation")

    def execute(self, context):
        value = (self.hex_color or '').strip().strip('#')
        if len(value) not in {6, 8} or any(c not in '0123456789abcdefABCDEF' for c in value):
            self.report({'ERROR'}, "Use a valid hex color such as #FFCC00 or #FFCC00FF")
            return {'CANCELLED'}
        try:
            r = int(value[0:2], 16) / 255.0
            g = int(value[2:4], 16) / 255.0
            b = int(value[4:6], 16) / 255.0
            a = int(value[6:8], 16) / 255.0 if len(value) == 8 else 1.0
        except ValueError:
            self.report({'ERROR'}, "Invalid hex color")
            return {'CANCELLED'}
        sc = context.scene
        sc.fbp_color_plane_type = 'CUSTOM'
        sc.fbp_color_plane_color = (r, g, b, a)
        return bpy.ops.fbp.create_color_plane()

def _fbp_clipboard_image_from_native_operator(context):
    """Paste an OS clipboard image with Blender's native image operator.

    ``image.clipboard_paste`` is an Image Editor operator. Shift+A invokes this
    code from the 3D View, so use an existing Image Editor when available or
    temporarily turn the current area into one. The original editor is always
    restored before returning.
    """
    before = {image.as_pointer() for image in bpy.data.images}
    pasted = None

    def pasted_candidate(area):
        try:
            space = area.spaces.active
            image = getattr(space, 'image', None)
            if image and image.as_pointer() not in before:
                return image
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        return None

    def invoke_in_area(window, screen, area):
        region = next((item for item in area.regions if item.type == 'WINDOW'), None)
        if region is None:
            return None
        try:
            with context.temp_override(
                window=window,
                screen=screen,
                area=area,
                region=region,
                space_data=area.spaces.active,
            ):
                result = bpy.ops.image.clipboard_paste()
            if 'FINISHED' not in result:
                return None
            return pasted_candidate(area)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return None

    # Prefer a real Image Editor so no visible editor has to change type.
    try:
        for window in context.window_manager.windows:
            screen = getattr(window, 'screen', None)
            if screen is None:
                continue
            for area in screen.areas:
                if area.type != 'IMAGE_EDITOR':
                    continue
                pasted = invoke_in_area(window, screen, area)
                if pasted is not None:
                    return pasted
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    # Shift+A normally runs in a 3D View. Temporarily reuse that area so the
    # native operator gets the exact editor context it expects.
    area = getattr(context, 'area', None)
    window = getattr(context, 'window', None)
    screen = getattr(context, 'screen', None)
    if area is not None and window is not None and screen is not None:
        original_type = area.type
        try:
            area.type = 'IMAGE_EDITOR'
            pasted = invoke_in_area(window, screen, area)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pasted = None
        finally:
            try:
                area.type = original_type
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass

    if pasted is not None:
        return pasted

    # Defensive fallback in case Blender created the datablock without making
    # it the active Image Editor image.
    for image in reversed(list(bpy.data.images)):
        try:
            if image.as_pointer() not in before:
                return image
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return None


def _fbp_clipboard_storage_directory(context):
    """Return a writable persistent folder for clipboard-created PNG files."""
    candidates = []
    scene = context.scene
    project_path = bpy.path.abspath(getattr(scene, 'fbp_project_path', '') or '')
    if project_path and os.path.isdir(project_path):
        candidates.append(os.path.join(project_path, 'Clipboard'))

    try:
        user_directory = bpy.utils.user_resource(
            'DATAFILES',
            path=os.path.join('frame_by_plane', 'clipboard'),
            create=True,
        )
        if user_directory:
            candidates.append(user_directory)
    except (AttributeError, RuntimeError, TypeError, ValueError, OSError):
        pass

    candidates.append(os.path.join(tempfile.gettempdir(), 'frame_by_plane_clipboard'))

    for directory in candidates:
        try:
            os.makedirs(directory, exist_ok=True)
            test_path = os.path.join(directory, '.fbp_write_test')
            with open(test_path, 'w', encoding='utf-8') as handle:
                handle.write('ok')
            os.remove(test_path)
            return os.path.abspath(directory)
        except OSError:
            continue

    raise OSError("No writable directory is available for clipboard images")


def _fbp_save_clipboard_image(context, image):
    """Persist a native clipboard image as PNG for the file-based FBP backend."""
    if image is None:
        return ''
    try:
        width, height = image.size
        if int(width) <= 0 or int(height) <= 0:
            return ''
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return ''

    directory = _fbp_clipboard_storage_directory(context)
    raw_name = str(getattr(image, 'name', '') or 'Clipboard Image')
    safe_name = re.sub(r'[^A-Za-z0-9._-]+', '_', raw_name).strip('._-') or 'Clipboard_Image'
    stamp = time.strftime('%Y%m%d_%H%M%S')
    suffix = str(time.time_ns())[-6:]
    filepath = os.path.join(directory, f'{safe_name}_{stamp}_{suffix}.png')

    old_filepath = str(getattr(image, 'filepath_raw', '') or '')
    old_format = str(getattr(image, 'file_format', 'PNG') or 'PNG')
    try:
        image.filepath_raw = filepath
        image.file_format = 'PNG'
        image.save()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OSError):
        try:
            image.save_render(filepath, scene=context.scene)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OSError):
            return ''
    finally:
        # The native clipboard datablock is only an intermediate source. Keep
        # its original metadata intact until it can be removed safely.
        try:
            image.filepath_raw = old_filepath
            image.file_format = old_format
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass

    return filepath if os.path.isfile(filepath) else ''


def _fbp_create_single_rig_from_path(context, path):
    """Create and select one standard Frame by Plane rig from a media path."""
    directory = os.path.dirname(path)
    filename = os.path.basename(path)
    context.scene.fbp_last_directory = directory
    target_collection = context.collection if context.collection else context.scene.collection
    rig = build_fbp_rig(
        context,
        clean_layer_name_from_path(filename),
        directory,
        [filename],
        context.scene.cursor.location.copy(),
        target_collection=target_collection,
    )
    bpy.ops.object.select_all(action='DESELECT')
    if object_in_view_layer(rig, context):
        rig.select_set(True)
        context.view_layer.objects.active = rig
    set_viewport_object_color(context)
    return rig


class FBP_OT_ImportSingleImageFromClipboard(Operator):
    bl_idname = "fbp.import_single_image_from_clipboard"
    bl_label = "Single Plane from Clipboard"
    bl_description = "Create a Frame by Plane rig from an image copied to the operating system clipboard, or from a copied media file path"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # Preserve the old and useful workflow for paths copied from Explorer,
        # Finder or another file manager.
        raw = getattr(context.window_manager, 'clipboard', '') or ''
        path = raw.strip().strip('"').strip("'")
        if path.startswith('file://'):
            path = path[7:]
        path = os.path.expanduser(path)
        if (
            os.path.isfile(path)
            and is_supported_media_file(path)
            and (is_supported_video_file(path) or not is_technical_map_file(path))
        ):
            _fbp_create_single_rig_from_path(context, path)
            return {'FINISHED'}

        # For screenshots, browser images and copied pixels, use the exact
        # native Blender clipboard operator, save the result as a persistent PNG
        # and pass that PNG through the normal FBP rig builder.
        pasted_image = _fbp_clipboard_image_from_native_operator(context)
        if pasted_image is None:
            self.report({'WARNING'}, "Clipboard does not contain a supported image")
            return {'CANCELLED'}

        saved_path = _fbp_save_clipboard_image(context, pasted_image)
        if not saved_path:
            self.report({'ERROR'}, "The clipboard image could not be saved as PNG")
            return {'CANCELLED'}

        try:
            _fbp_create_single_rig_from_path(context, saved_path)
        except Exception:
            # Keep the pasted image datablock available for inspection if rig
            # creation fails; only successful imports clean the temporary block.
            raise
        else:
            # Do not free the clipboard Image datablock synchronously. Blender 5.1
            # may still own clipboard/image-cache state when the popup closes or a
            # new file is opened. Explicit orphan purge can remove it later.
            try:
                pasted_image["fbp_temporary"] = True
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass

        self.report({'INFO'}, "Created Frame by Plane rig from clipboard image")
        return {'FINISHED'}
