"""Focused Frame by Plane operator module."""

try:
    from .operator_common import *
except ImportError:
    from operator_common import *


class FBP_OT_RemovePendingTreeSelection(Operator):
    bl_idname = "fbp.remove_pending_tree_selection"
    bl_label = "Remove Setup Selection"
    bl_description = "Remove the selected setup layer, or the selected collection with all internal layers"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        sc = context.scene
        row = _fbp_active_pending_tree_row(sc)
        if row is not None and getattr(row, 'row_type', 'LAYER') == 'GROUP':
            collection_path = getattr(row, 'collection_path', '') or ''
            if not collection_path:
                return {'CANCELLED'}
            removed = 0
            for i in range(len(sc.fbp_pending_planes) - 1, -1, -1):
                cname = getattr(sc.fbp_pending_planes[i], 'collection_name', '') or ''
                if cname == collection_path or cname.startswith(collection_path + ' /'):
                    sc.fbp_pending_planes.remove(i)
                    removed += 1
            _fbp_select_pending_index(context, min(int(getattr(sc, 'fbp_pending_planes_idx', 0)), max(0, len(sc.fbp_pending_planes) - 1)))
            return {'FINISHED'} if removed else {'CANCELLED'}

        idx, _collection_name, _row_type = _fbp_active_pending_index_and_collection(sc)
        if 0 <= idx < len(sc.fbp_pending_planes):
            sc.fbp_pending_planes.remove(idx)
            _fbp_select_pending_index(context, min(idx, max(0, len(sc.fbp_pending_planes) - 1)))
            return {'FINISHED'}
        return {'CANCELLED'}

class FBP_OT_RemovePendingPlaneAtIndex(Operator):
    bl_idname = "fbp.remove_pending_plane_at_index"
    bl_label = "Remove Setup Layer"
    bl_description = "Remove this pending layer from the Multiplane Setup before generating planes"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(name="Index", description="Pending setup row index to remove", default=-1)

    def execute(self, context):
        sc = context.scene
        if 0 <= self.index < len(sc.fbp_pending_planes):
            sc.fbp_pending_planes.remove(self.index)
            sc.fbp_pending_planes_idx = min(max(0, self.index - 1), max(0, len(sc.fbp_pending_planes) - 1))
            _fbp_refresh_pending_tree(context)
            return {'FINISHED'}
        return {'CANCELLED'}

class FBP_OT_ProjectHealthCheck(Operator):
    bl_idname      = "fbp.project_health_check"
    bl_label       = "Project Health Check"
    bl_description = "Check linked images, collections and layers in the current Frame by Plane project"

    def execute(self, context):
        sync_layer_collection(context)
        rigs = [obj for obj in context.scene.objects if is_fbp_layer_object(obj)]
        fbp_colls = [coll for coll in bpy.data.collections if collection_has_fbp_content(coll, True)]
        image_paths = collect_project_image_paths()
        missing = missing_project_images()
        empty_fbp_colls = [coll.name for coll in fbp_colls if not any(True for _ in iter_fbp_rigs_in_collection(coll, True))]

        lines = [
            "Frame by Plane - Project Health",
            "================================",
            f"Layers: {len(rigs)}",
            f"Collections: {len(fbp_colls)}",
            f"Linked images: {len(image_paths)}",
            f"Missing images: {len(missing)}",
            f"Empty FBP collections: {len(empty_fbp_colls)}",
            "",
        ]
        if missing:
            lines.append("Missing files:")
            lines.extend(f"- {p}" for p in missing[:200])
            if len(missing) > 200:
                lines.append(f"...and {len(missing) - 200} more")
        else:
            lines.append("No missing files found.")

        txt = bpy.data.texts.get("FBP_Project_Health") or bpy.data.texts.new("FBP_Project_Health")
        txt.clear()
        txt.write("\n".join(lines))
        self.report({'INFO'}, f"Health: {len(rigs)} layers, {len(missing)} missing image(s)")
        return {'FINISHED'}

class FBP_OT_RelinkFromProjectRoot(Operator):
    bl_idname      = "fbp.relink_from_project_root"
    bl_label       = "Relink From Project Root"
    bl_description = "Relink missing images by searching inside the Project Folder"
    bl_options     = {'UNDO'}

    def execute(self, context):
        root = project_root_for_package(context)
        if not root or not os.path.isdir(root):
            self.report({'WARNING'}, "Set a valid Project Folder first")
            return {'CANCELLED'}
        relinked, ambiguous, still_missing = relink_missing_images_from_root(root, make_relative=True)
        msg = f"Relinked {relinked}; missing {len(still_missing)}; ambiguous {len(ambiguous)}"
        self.report({'INFO' if not still_missing else 'WARNING'}, msg)
        return {'FINISHED'}

class FBP_OT_SelectMissingLayers(Operator):
    bl_idname      = "fbp.select_missing_layers"
    bl_label       = "Select Missing Layers"
    bl_description = "Select Frame by Plane rigs that contain missing linked images"
    bl_options     = {'UNDO'}

    def execute(self, context):
        sync_layer_collection(context)
        bpy.ops.object.select_all(action='DESELECT')
        selected = 0
        skipped_hidden = 0
        active = None
        for rig in [obj for obj in context.scene.objects if getattr(obj, 'is_fbp_control', False)]:
            if not rig_has_missing_images(rig):
                continue
            if collection_is_hidden_in_view_layer(context, get_primary_fbp_collection(rig)):
                skipped_hidden += 1
                continue
            if not object_in_view_layer(rig, context):
                skipped_hidden += 1
                continue
            try:
                rig.select_set(True)
                active = rig
                selected += 1
            except Exception:
                skipped_hidden += 1
        if active:
            context.view_layer.objects.active = active
        level = 'WARNING' if skipped_hidden else 'INFO'
        self.report({level}, f"Selected {selected} missing layer(s); hidden/unavailable {skipped_hidden}")
        return {'FINISHED'} if selected or skipped_hidden else {'CANCELLED'}

class FBP_OT_SyncCollectionColors(Operator):
    bl_idname      = "fbp.sync_collection_colors"
    bl_label       = "Sync Collection Colors"
    bl_description = "Apply visible Collection color tags to Frame by Plane layer viewport colors"
    bl_options     = {'UNDO'}

    def execute(self, context):
        sync_collection_colors_to_rigs(context)
        self.report({'INFO'}, "Collection colors synced")
        return {'FINISHED'}

class FBP_OT_ShowImportProfile(Operator):
    bl_idname      = "fbp.show_import_profile"
    bl_label       = "Show Import Profile"
    bl_description = "Open the last Frame by Plane import profiling report"

    def execute(self, context):
        txt = bpy.data.texts.get("FBP_Last_Import_Profile")
        if not txt:
            txt = bpy.data.texts.new("FBP_Last_Import_Profile")
            txt.write("No import profile yet. Run Auto Build Project or Generate Multi Plane first.")
        try:
            for area in context.screen.areas:
                if area.type == 'TEXT_EDITOR':
                    area.spaces.active.text = txt
                    break
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        self.report({'INFO'}, "Opened FBP_Last_Import_Profile")
        return {'FINISHED'}

__all__ = ['FBP_OT_RemovePendingTreeSelection', 'FBP_OT_RemovePendingPlaneAtIndex', 'FBP_OT_ProjectHealthCheck', 'FBP_OT_RelinkFromProjectRoot', 'FBP_OT_SelectMissingLayers', 'FBP_OT_SyncCollectionColors', 'FBP_OT_ShowImportProfile']
