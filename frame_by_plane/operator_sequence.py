"""Focused Frame By Plane operator module."""

import bpy
import math
import mathutils
import os
import uuid
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Operator

from .constants import fbp_icon, FBP_SUPPORTED_IMAGE_EXT, FBP_SUPPORTED_VIDEO_EXT
from .builder import fbp_prepare_media_source
from .pillow_media import fbp_optimize_sequence_entries
from .ui_style import configure_layout, section_header
from .path_utils import is_supported_media_file, is_supported_video_file, natural_sort_key
from .materials import (
    do_update_emission,
    do_update_opacity,
    fbp_create_procedural_frame_material_for_rig,
    fbp_copy_material_slots_unique,
    fbp_procedural_frame_display_name,
)
from .layers import (
    _safe_layer_obj,
    ensure_object_in_active_collection,
    fbp_active_layer_index,
    fbp_procedural_kind_from_material,
    fbp_procedural_layer_type,
    fbp_set_procedural_metadata,
    get_primary_fbp_collection,
    get_selected_fbp_roots,
    get_selected_rigs,
    is_fbp_layer_object,
    fbp_layer_backend_type,
    object_in_view_layer,
    invalidate_preview_path,
    iter_scene_fbp_rigs,
)
from .scene_sync import (
    delete_fbp_rigs,
    fbp_remove_plane_datablock,
    sync_layer_collection,
)
from .runtime import (
    fbp_set_rna_property_silent, fbp_warn, FBP_DATA_ERRORS, FBP_DATA_IO_ERRORS,
    fbp_tag_redraw, fbp_obj_runtime_token, fbp_find_id_by_runtime_key,
)
from .transactions import FBPTransaction
from .ui_list_state import (
    ensure_item_identity,
    ensure_unique_item_identities,
    index_for_identity,
)
from .core import (
    do_update_animation,
    do_update_track,
    fbp_apply_sequence_entries_to_rig,
    fbp_clone_sequence_entry_material,
    fbp_color_plane_can_have_frames,
    fbp_insert_sequence_entry,
    fbp_load_active_procedural_frame_to_rig,
    fbp_rebuild_sequence_backend_from_rig,
    fbp_set_solid_material_color,
    fbp_refresh_sequence_backend_from_rig,
    fbp_sequence_entries_from_rig,
)
from .shortcut_runtime import alt_modifier_name
from .operator_common import (
    FBP_VerticalDragModalMixin,
    fbp_jump_timeline_to_sequence_row,
)


def _fbp_requested_procedural_frame_kind(rig):
    """Return the explicit Color/Gradient kind requested by the current UI state."""
    if not rig:
        return 'SOLID'
    mode = str(getattr(rig, 'fbp_color_plane_mode', 'SOLID') or 'SOLID')
    if mode == 'GRADIENT':
        return 'GRADIENT'
    if mode == 'HOLDOUT':
        return 'HOLDOUT'
    if mode == 'SOLID':
        return 'SOLID'
    stable = fbp_procedural_layer_type(rig)
    return stable if stable in {'SOLID', 'GRADIENT', 'HOLDOUT'} else 'SOLID'


class FBP_OT_SetColorPlaneMode(Operator):
    bl_idname = "fbp.set_color_plane_mode"
    bl_label = "Set Procedural Type"
    bl_description = "Switch the selected procedural plane between Color and Gradient"
    bl_options = {'REGISTER', 'UNDO'}

    mode: StringProperty(description="Procedural plane mode to activate", default="SOLID")

    def execute(self, context):
        rig = context.object if context.object and getattr(context.object, "is_fbp_control", False) else None
        if not rig:
            rigs = get_selected_rigs(context)
            rig = rigs[0] if rigs else None
        if not rig or not getattr(rig, "fbp_is_color_plane", False):
            self.report({'WARNING'}, "Select one Color or Gradient Plane first")
            return {'CANCELLED'}
        mode = self.mode if self.mode in {'SOLID', 'GRADIENT'} else 'SOLID'
        try:
            rig.fbp_color_plane_mode = mode
            rig['fbp_procedural_layer_type'] = mode
            rig['fbp_backend_type'] = 'PROCEDURAL_GRADIENT' if mode == 'GRADIENT' else 'PROCEDURAL_COLOR'
            plane = getattr(rig, 'fbp_plane_target', None)
            if plane:
                plane['fbp_backend_type'] = rig['fbp_backend_type']
        except Exception as exc:
            fbp_warn("Could not change procedural Color Plane mode", exc)
            self.report({'ERROR'}, "Could not change procedural type")
            return {'CANCELLED'}
        return {'FINISHED'}


class FBP_OT_GradientController(Operator):
    bl_idname = "fbp.gradient_controller"
    bl_label = "Gradient Controller"
    bl_description = f"Use another selected Empty, or create one, to animate the Gradient position; {alt_modifier_name()}-click unlinks the current controller"
    bl_options = {'REGISTER', 'UNDO'}

    def _rig(self, context):
        active = getattr(context, "object", None)
        if active is not None and bool(getattr(active, "is_fbp_control", False)):
            return active
        rigs = get_selected_rigs(context)
        return rigs[0] if rigs else None

    def invoke(self, context, event):
        rig = self._rig(context)
        if rig is None or not bool(getattr(rig, "fbp_is_color_plane", False)):
            self.report({'WARNING'}, "Select one Color or Gradient Plane")
            return {'CANCELLED'}
        if bool(getattr(event, "alt", False)) and getattr(rig, "fbp_gradient_controller", None) is not None:
            rig.fbp_gradient_controller = None
            self.report({'INFO'}, "Gradient controller unlinked")
            return {'FINISHED'}
        return self.execute(context)

    def execute(self, context):
        rig = self._rig(context)
        if rig is None or not bool(getattr(rig, "fbp_is_color_plane", False)):
            self.report({'WARNING'}, "Select one Color or Gradient Plane")
            return {'CANCELLED'}
        if str(getattr(rig, "fbp_color_plane_mode", "SOLID") or "SOLID") != "GRADIENT":
            self.report({'WARNING'}, "Select a Gradient frame first")
            return {'CANCELLED'}

        controller = getattr(rig, "fbp_gradient_controller", None)
        if controller is not None:
            for obj in tuple(getattr(context, "selected_objects", ()) or ()):
                obj.select_set(False)
            controller.hide_viewport = False
            controller.hide_set(False)
            controller.select_set(True)
            context.view_layer.objects.active = controller
            self.report({'INFO'}, "Gradient controller selected; keyframe its Location")
            return {'FINISHED'}

        controller = next(
            (
                obj for obj in tuple(getattr(context, "selected_objects", ()) or ())
                if obj is not rig and getattr(obj, "type", "") == "EMPTY"
            ),
            None,
        )
        plane = getattr(rig, "fbp_plane_target", None)
        vertices = tuple(getattr(getattr(plane, "data", None), "vertices", ()) or ())
        try:
            xs = [float(vertex.co.x) for vertex in vertices]
            ys = [float(vertex.co.y) for vertex in vertices]
            width = max(1.0e-6, max(xs) - min(xs))
            height = max(1.0e-6, max(ys) - min(ys))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            width = height = 1.0

        created = controller is None
        if created:
            controller = bpy.data.objects.new(f"{rig.name} · Gradient Controller", None)
            collection = next(iter(getattr(rig, "users_collection", ()) or ()), context.scene.collection)
            collection.objects.link(controller)
            controller.empty_display_type = 'SPHERE'
            controller.empty_display_size = max(0.05, min(width, height) * 0.08)
            controller.parent = plane or rig
            controller.matrix_parent_inverse = mathutils.Matrix.Identity(4)
            controller.location = (
                float(getattr(rig, "fbp_gradient_offset_x", 0.0)) * width,
                float(getattr(rig, "fbp_gradient_offset_y", 0.0)) * height,
                0.006,
            )
        elif controller.parent is not (plane or rig):
            world_matrix = controller.matrix_world.copy()
            controller.parent = plane or rig
            controller.matrix_parent_inverse = mathutils.Matrix.Identity(4)
            controller.matrix_world = world_matrix

        controller["fbp_gradient_controller"] = True
        controller["fbp_gradient_controller_owner"] = str(rig.name)
        rig.fbp_gradient_controller = controller
        try:
            from .materials import fbp_bind_gradient_controller_drivers
            fbp_bind_gradient_controller_drivers(rig, controller)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not bind Gradient controller drivers", exc)
            return {'CANCELLED'}

        for obj in tuple(getattr(context, "selected_objects", ()) or ()):
            obj.select_set(False)
        controller.select_set(True)
        context.view_layer.objects.active = controller
        self.report({'INFO'}, "Created Gradient controller" if created else "Linked selected Empty to Gradient")
        return {'FINISHED'}


class FBP_OT_UpdateAnimation(Operator):
    bl_idname  = "fbp.update_animation"
    bl_label   = "Update Animation"
    bl_description = "Refresh the selected layer animation timing"
    bl_options = {'UNDO', 'INTERNAL'}

    def execute(self, context):
        for rig in get_selected_rigs(context):
            do_update_animation(rig)
        return {'FINISHED'}


def _fbp_source_image_nodes_for_rig(rig):
    """Return only media-source texture nodes, never effect/mask textures."""
    plane = getattr(rig, "fbp_plane_target", None) if rig else None
    mesh = getattr(plane, "data", None) if plane else None
    materials = tuple(getattr(mesh, "materials", ()) or ()) if mesh else ()
    result = []
    seen = set()
    for material in materials:
        tree = getattr(material, "node_tree", None) if material else None
        for node in tuple(getattr(tree, "nodes", ()) or ()) if tree else ():
            if str(getattr(node, "type", "") or "") != "TEX_IMAGE":
                continue
            try:
                owned_source = bool(
                    node.get("fbp_native_sequence_node", False)
                    or node.get("fbp_drawing_image_node", False)
                )
            except FBP_DATA_ERRORS:
                owned_source = False
            if not owned_source:
                continue
            try:
                key = int(node.as_pointer())
            except FBP_DATA_ERRORS:
                key = id(node)
            if key in seen:
                continue
            seen.add(key)
            result.append((material, node))
    return tuple(result)


def _fbp_media_images_for_rig(rig):
    """Return unique source Image datablocks referenced by one media layer."""
    images = []
    seen = set()
    for _material, node in _fbp_source_image_nodes_for_rig(rig):
        image = getattr(node, "image", None)
        if image is None:
            continue
        try:
            key = int(image.as_pointer())
        except FBP_DATA_ERRORS:
            key = id(image)
        if key in seen:
            continue
        seen.add(key)
        images.append(image)
    return tuple(images)


def _fbp_existing_absolute_path(path):
    try:
        absolute = os.path.normpath(bpy.path.abspath(str(path or "")))
        return absolute if absolute and os.path.isfile(absolute) else ""
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return ""


def _fbp_adopt_relinked_media_paths(rig):
    """Mirror Blender-side relinks back into persistent FBP frame rows.

    Find Missing Files and manual Image Editor relinks update ``Image.filepath``
    but not Frame By Plane's logical sequence rows. Without this reconciliation,
    a refresh rebuild can reapply the stale missing path. Only unambiguous source
    layouts are adopted; generated proxy sequences remain untouched.
    """
    backend = fbp_layer_backend_type(rig)
    rows = tuple(getattr(rig, "fbp_images", ()) or ())
    if not rows or backend not in {'NATIVE_IMAGE', 'NATIVE_SEQUENCE', 'CUTOUT'}:
        return 0

    source_nodes = _fbp_source_image_nodes_for_rig(rig)
    live_paths = []
    proxy_source = False
    for material, node in source_nodes:
        try:
            proxy_source = proxy_source or bool(material.get("fbp_native_uses_proxy", False))
        except FBP_DATA_ERRORS:
            pass
        image = getattr(node, "image", None)
        live = _fbp_existing_absolute_path(getattr(image, "filepath", "") if image else "")
        if live and live not in live_paths:
            live_paths.append(live)
    if not live_paths or proxy_source:
        return 0

    real_indices = [
        index for index, item in enumerate(rows)
        if not bool(getattr(item, "is_empty", False))
    ]
    if not real_indices:
        return 0

    replacements = {}
    if backend == 'NATIVE_IMAGE' and len(real_indices) == 1:
        replacements[real_indices[0]] = live_paths[0]
    elif backend == 'CUTOUT':
        active = max(0, min(len(rows) - 1, int(getattr(rig, "fbp_images_index", 0) or 0)))
        if active in real_indices:
            replacements[active] = live_paths[0]
    elif backend == 'NATIVE_SEQUENCE':
        first_index = real_indices[0]
        first_name = os.path.basename(str(getattr(rows[first_index], "filepath", "") or ""))
        live = next(
            (path for path in live_paths if os.path.basename(path).casefold() == first_name.casefold()),
            "",
        )
        if live:
            directory = os.path.dirname(live)
            candidate = {
                index: os.path.join(
                    directory,
                    os.path.basename(str(getattr(rows[index], "filepath", "") or "")),
                )
                for index in real_indices
            }
            if all(_fbp_existing_absolute_path(path) for path in candidate.values()):
                replacements = candidate

    changed = 0
    old_preview = str(getattr(rig, "fbp_preview_path", "") or "")
    new_preview = old_preview
    for index, new_path in replacements.items():
        item = rows[index]
        old_path = str(getattr(item, "filepath", "") or "")
        old_absolute = os.path.normcase(os.path.normpath(bpy.path.abspath(old_path))) if old_path else ""
        new_absolute = os.path.normcase(os.path.normpath(new_path))
        if old_absolute == new_absolute:
            continue
        invalidate_preview_path(old_path)
        invalidate_preview_path(new_path)
        item.filepath = new_path
        new_name = os.path.basename(new_path)
        if new_name and str(getattr(item, "name", "") or "") != new_name:
            item.name = new_name
        if old_preview and old_absolute == os.path.normcase(os.path.normpath(bpy.path.abspath(old_preview))):
            new_preview = new_path
        changed += 1
    if changed and new_preview != old_preview:
        rig.fbp_preview_path = new_preview
    return changed


def _fbp_refresh_media_rig(rig, *, seen_images=None):
    backend = fbp_layer_backend_type(rig) if rig else ""
    if backend not in {'NATIVE_IMAGE', 'NATIVE_SEQUENCE', 'NATIVE_MOVIE', 'CUTOUT'}:
        return None
    seen_images = seen_images if seen_images is not None else set()
    relinked = _fbp_adopt_relinked_media_paths(rig)
    for item in tuple(getattr(rig, "fbp_images", ()) or ()):
        path = str(getattr(item, "filepath", "") or "")
        if path:
            invalidate_preview_path(path)

    reloaded = 0
    sources = 0
    failures = 0
    for image in _fbp_media_images_for_rig(rig):
        try:
            key = int(image.as_pointer())
        except FBP_DATA_ERRORS:
            key = id(image)
        if key in seen_images:
            continue
        seen_images.add(key)
        try:
            source = str(getattr(image, "source", "") or "")
            if source not in {'FILE', 'SEQUENCE', 'MOVIE'}:
                continue
            sources += 1
            if source == 'SEQUENCE' and not bool(getattr(image, "has_data", False)):
                continue
            image.reload()
            reloaded += 1
        except FBP_DATA_ERRORS as exc:
            failures += 1
            fbp_warn(f"Could not refresh media datablock '{getattr(image, 'name', 'Image')}'", exc)

    rebuilt = bool(fbp_refresh_sequence_backend_from_rig(rig))
    if backend in {'NATIVE_IMAGE', 'NATIVE_SEQUENCE', 'NATIVE_MOVIE'}:
        try:
            from .native_backend import fbp_refresh_native_media_dimensions
            fbp_refresh_native_media_dimensions(rig)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            failures += 1
            fbp_warn("Could not refresh media aspect geometry", exc)
    try:
        do_update_animation(rig)
    except FBP_DATA_ERRORS:
        pass
    return {
        "backend": backend,
        "relinked": relinked,
        "reloaded": reloaded,
        "rebuilt": rebuilt,
        "failures": failures,
        "sources": sources,
        "ok": bool(rebuilt or reloaded or relinked or sources),
    }


class FBP_OT_RefreshMedia(Operator):
    bl_idname = "fbp.refresh_media"
    bl_label = "Refresh Media"
    bl_description = (
        "Reload the current image, movie or complete image sequence from disk; "
        "also rebuild the native source when frame paths were relinked"
    )
    # Reloading external files is not an undoable Blender data edit. Avoid
    # inserting a misleading history step before the user's next Ctrl+Z.
    bl_options = {'REGISTER'}

    rig_name: StringProperty(
        name="Layer",
        description="Exact Frame By Plane layer to refresh",
        default="",
        options={'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        rigs = get_selected_rigs(context)
        return bool(rigs and any(
            fbp_layer_backend_type(rig) in {
                'NATIVE_IMAGE', 'NATIVE_SEQUENCE', 'NATIVE_MOVIE', 'CUTOUT'
            }
            for rig in rigs
        ))

    def execute(self, context):
        rig = bpy.data.objects.get(str(self.rig_name or "")) if self.rig_name else None
        if rig is None or not is_fbp_layer_object(rig):
            rigs = get_selected_rigs(context)
            rig = rigs[0] if rigs else None
        stats = _fbp_refresh_media_rig(rig)
        if stats is None:
            self.report({'WARNING'}, "Select an image, sequence, movie or Cutout Plane")
            return {'CANCELLED'}
        fbp_tag_redraw(context, all_windows=True)
        if not stats["ok"]:
            self.report({'ERROR'}, "Media refresh failed; check the source paths")
            return {'CANCELLED'}
        label = "sequence" if stats["backend"] == 'NATIVE_SEQUENCE' else (
            "movie" if stats["backend"] == 'NATIVE_MOVIE' else "image"
        )
        message = f"Refreshed {label}"
        if stats["relinked"]:
            message += f" · {stats['relinked']} relinked path{'s' if stats['relinked'] != 1 else ''}"
        if stats["reloaded"]:
            message += f" · {stats['reloaded']} datablock{'s' if stats['reloaded'] != 1 else ''}"
        if stats["failures"]:
            message += f" · {stats['failures']} failed"
        self.report({'WARNING'} if stats["failures"] else {'INFO'}, message)
        return {'FINISHED'}


class FBP_OT_RefreshAllMedia(Operator):
    bl_idname = "fbp.refresh_all_media"
    bl_label = "Refresh All Media"
    bl_description = (
        "Reload every Frame By Plane image, sequence, movie and Cutout source in the scene; "
        "shared Blender image datablocks are reloaded only once"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        scene = getattr(context, 'scene', None)
        return bool(scene and any(
            fbp_layer_backend_type(rig) in {
                'NATIVE_IMAGE', 'NATIVE_SEQUENCE', 'NATIVE_MOVIE', 'CUTOUT'
            }
            for rig in iter_scene_fbp_rigs(scene, fallback=True)
        ))

    def execute(self, context):
        rigs = [
            rig for rig in iter_scene_fbp_rigs(context.scene, fallback=True)
            if fbp_layer_backend_type(rig) in {
                'NATIVE_IMAGE', 'NATIVE_SEQUENCE', 'NATIVE_MOVIE', 'CUTOUT'
            }
        ]
        seen_images = set()
        refreshed = relinked = reloaded = failures = 0
        for rig in rigs:
            stats = _fbp_refresh_media_rig(rig, seen_images=seen_images)
            if stats is None:
                continue
            refreshed += int(bool(stats["ok"]))
            relinked += int(stats["relinked"])
            reloaded += int(stats["reloaded"])
            failures += int(stats["failures"])
        fbp_tag_redraw(context, all_windows=True)
        if not refreshed:
            self.report({'ERROR'}, "No Frame By Plane media could be refreshed")
            return {'CANCELLED'}
        message = f"Refreshed {refreshed}/{len(rigs)} media layer{'s' if len(rigs) != 1 else ''}"
        if reloaded:
            message += f" · {reloaded} datablock{'s' if reloaded != 1 else ''}"
        if relinked:
            message += f" · {relinked} relinked path{'s' if relinked != 1 else ''}"
        if failures:
            message += f" · {failures} failed"
        self.report({'WARNING'} if failures else {'INFO'}, message)
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
    bl_description = "Open transform tools for the selected Frame By Plane layer"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        if not get_selected_rigs(context):
            self.report({'WARNING'}, "Select a Frame By Plane layer first")
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        rig = get_selected_rigs(context)[0]
        layout = configure_layout(self.layout)
        section_header(layout, rig.name, icon=fbp_icon("EMPTY_ARROWS"))
        col = layout.column(align=True)
        row = col.row(align=True)
        row.operator("fbp.transform", text="Horizontal / Vertical", icon=fbp_icon("RENDER_SWAP_DIMENSIONS")).mode = 'TOGGLE_ROT'
        row.operator("fbp.transform", text="To Ground", icon=fbp_icon("GRID")).mode = 'TO_GROUND'
        row = col.row(align=True)
        row.operator("fbp.transform", text="Reset Rotation", icon=fbp_icon("FILE_REFRESH")).mode = 'RESET_ROT'
        row.operator("fbp.transform", text="Reset Scale", icon=fbp_icon("FILE_REFRESH")).mode = 'RESET_SCALE'

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
    bl_description = "Update camera tracking constraints on selected Frame By Plane rigs"
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


class FBP_OT_DragSequenceFrame(FBP_VerticalDragModalMixin, Operator):
    bl_idname = "fbp.drag_sequence_frame"
    bl_label = "Drag Frame"
    bl_description = "Drag vertically to reorder this Color/Gradient animation frame and jump the timeline to it"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL', 'BLOCKING'}

    rig_name: StringProperty(
        name="Layer",
        description="Frame By Plane layer that owns this frame row",
        default="",
        options={'SKIP_SAVE'},
    )
    index: IntProperty(
        name="Frame",
        description="Frame row to drag",
        default=-1,
        options={'SKIP_SAVE'},
    )

    def _redraw(self, context):
        fbp_tag_redraw(context, area_types={'VIEW_3D', 'PROPERTIES'})

    def _resolve_drag_index(self, entries=None):
        rig = getattr(self, '_rig', None)
        if rig is None:
            return -1
        if entries is None:
            entries = getattr(rig, 'fbp_images', ())
        identity = str(getattr(self, '_drag_uid', '') or '')
        if identity:
            for index, entry in enumerate(entries or ()):
                if str(getattr(entry, 'stable_id', '') or '') == identity:
                    return index
                if isinstance(entry, dict) and str(entry.get('stable_id', '') or '') == identity:
                    return index
        index = int(getattr(self, '_index', -1))
        return index if 0 <= index < len(entries or ()) else -1

    def _select_row(self, context):
        rig = getattr(self, '_rig', None)
        index = self._resolve_drag_index()
        if rig is None or index < 0:
            return
        try:
            self._index = index
            fbp_set_rna_property_silent(rig, 'fbp_images_index', index)
            for i, item in enumerate(rig.fbp_images):
                item.is_selected = (i == index)
            if getattr(rig, 'fbp_is_color_plane', False):
                fbp_load_active_procedural_frame_to_rig(rig)
            fbp_jump_timeline_to_sequence_row(context, rig, index)
        except FBP_DATA_IO_ERRORS as exc:
            fbp_warn('Could not select dragged frame row', exc)

    def _move_once(self, context, direction):
        rig = getattr(self, '_rig', None)
        if rig is None or not getattr(rig, 'fbp_plane_target', None):
            return False
        backend_type = fbp_layer_backend_type(rig)
        if backend_type in {'CUTOUT', 'NATIVE_MOVIE'}:
            return False
        entries = fbp_sequence_entries_from_rig(rig)
        count = len(entries)
        source = self._resolve_drag_index(entries)
        if count <= 1 or not (0 <= source < count):
            return False
        target = source - 1 if direction == 'UP' else source + 1
        if not (0 <= target < count):
            return False
        entries[source], entries[target] = entries[target], entries[source]
        try:
            if not fbp_apply_sequence_entries_to_rig(rig, entries):
                return False
            self._index = target
            fbp_set_rna_property_silent(rig, 'fbp_images_index', target)
            if getattr(rig, 'fbp_is_color_plane', False):
                fbp_load_active_procedural_frame_to_rig(rig)
            do_update_animation(rig)
            fbp_jump_timeline_to_sequence_row(context, rig, target)
            return True
        except FBP_DATA_IO_ERRORS as exc:
            fbp_warn('Could not drag-reorder frame', exc)
            return False

    def _cancel_drag(self, context):
        """Restore the entire frame list once instead of replaying inverse moves."""
        rig = getattr(self, '_rig', None)
        snapshot = getattr(self, '_original_entries', None)
        if rig is None or snapshot is None:
            return False
        try:
            restored_entries = [dict(entry) for entry in snapshot]
            if not fbp_apply_sequence_entries_to_rig(rig, restored_entries):
                return False
            active_uid = str(getattr(self, '_original_active_uid', '') or '')
            active_index = -1
            if active_uid:
                for index, entry in enumerate(getattr(rig, 'fbp_images', ()) or ()):
                    if str(getattr(entry, 'stable_id', '') or '') == active_uid:
                        active_index = index
                        break
            if active_index < 0:
                active_index = max(0, min(
                    int(getattr(self, '_original_active_index', 0) or 0),
                    max(0, len(getattr(rig, 'fbp_images', ())) - 1),
                ))
            fbp_set_rna_property_silent(rig, 'fbp_images_index', active_index)
            if getattr(rig, 'fbp_is_color_plane', False):
                fbp_load_active_procedural_frame_to_rig(rig)
            do_update_animation(rig)
            scene = getattr(context, 'scene', None)
            original_frame = getattr(self, '_original_scene_frame', None)
            if scene is not None and original_frame is not None:
                scene.frame_set(int(original_frame))
            self._index = self._resolve_drag_index()
            return True
        except FBP_DATA_IO_ERRORS as exc:
            fbp_warn('Could not restore cancelled frame drag', exc)
            return False

    def invoke(self, context, event):
        rig = bpy.data.objects.get(str(getattr(self, 'rig_name', '') or ''))
        if not rig or not getattr(rig, 'is_fbp_control', False):
            return {'CANCELLED'}
        if not (0 <= int(getattr(self, 'index', -1)) < len(getattr(rig, 'fbp_images', []))):
            return {'CANCELLED'}
        ensure_unique_item_identities(getattr(rig, 'fbp_images', ()), 'stable_id')
        self._rig = rig
        self._index = int(self.index)
        self._drag_uid = ensure_item_identity(rig.fbp_images[self._index], 'stable_id')
        self._original_entries = [
            dict(entry) for entry in fbp_sequence_entries_from_rig(rig)
        ]
        self._original_active_index = int(getattr(rig, 'fbp_images_index', 0) or 0)
        self._original_active_uid = (
            str(getattr(rig.fbp_images[self._original_active_index], 'stable_id', '') or '')
            if 0 <= self._original_active_index < len(rig.fbp_images)
            else ''
        )
        self._original_scene_frame = int(getattr(context.scene, 'frame_current', 0) or 0)
        self._anchor_y = int(getattr(event, 'mouse_y', 0) or 0)
        self._history = []
        self._did_change = False
        self._finish_on_release = str(getattr(event, 'value', '') or '') in {'PRESS', 'CLICK_DRAG'}
        self._saw_drag_motion = False
        try:
            ui_scale = float(context.preferences.system.ui_scale)
        except FBP_DATA_ERRORS:
            ui_scale = 1.0
        self._threshold = max(10, int(round(18.0 * ui_scale)))
        self._select_row(context)
        try:
            if not self._begin_modal_mutation():
                raise RuntimeError("Could not acquire the UIList modal mutation guard")
            context.window_manager.modal_handler_add(self)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            try:
                self._end_modal_mutation()
            except Exception:
                pass
            fbp_warn("Could not start UIList drag", exc)
            return {'CANCELLED'}
        try:
            context.window.cursor_modal_set('SCROLL_Y')
        except FBP_DATA_ERRORS:
            pass
        self._redraw(context)
        return {'RUNNING_MODAL'}

class FBP_OT_ConvertColorPlaneToAnimation(Operator):
    bl_idname = "fbp.convert_color_plane_to_animation"
    bl_label = "Convert to Color Animation"
    bl_description = "Turn the selected static Color or Gradient plane into a one-frame procedural animation list"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rig = context.object if context.object and getattr(context.object, "is_fbp_control", False) else None
        if not rig:
            rigs = get_selected_rigs(context)
            rig = rigs[0] if rigs else None
        if not rig or not getattr(rig, "fbp_plane_target", None):
            self.report({'WARNING'}, "Select one Frame By Plane color layer first")
            return {'CANCELLED'}
        if not getattr(rig, "fbp_is_color_plane", False):
            self.report({'WARNING'}, "Convert to Color Animation is available only for Color and Gradient planes")
            return {'CANCELLED'}
        if not fbp_color_plane_can_have_frames(rig):
            self.report({'WARNING'}, "Holdout planes are static masks and cannot have animation frames")
            return {'CANCELLED'}
        if len(getattr(rig, "fbp_images", [])) > 0:
            self.report({'INFO'}, "This Color plane already has animation frames")
            return {'FINISHED'}

        desired_kind = _fbp_requested_procedural_frame_kind(rig)
        if desired_kind == 'HOLDOUT':
            self.report({'WARNING'}, "Holdout planes are static masks and cannot have animation frames")
            return {'CANCELLED'}

        # Convert must follow the visible Color/Gradient choice, not stale material
        # metadata. If the material disagrees with the UI state, rebuild it before
        # creating the first row so a Color plane cannot become a Gradient frame.
        if getattr(rig, 'fbp_color_plane_mode', 'SOLID') != desired_kind:
            fbp_set_rna_property_silent(rig, 'fbp_color_plane_mode', desired_kind)

        # Build the first list material from the visible button state instead of
        # reusing the static plane material. Reusing the static material is unsafe
        # after switching Gradient -> Color because old ColorRamp nodes can remain
        # in the shader even when metadata has been reset to SOLID.
        try:
            source_mat, _source_label, _is_empty = fbp_create_procedural_frame_material_for_rig(rig, 1)
        except Exception as exc:
            fbp_warn("Could not create first procedural animation material", exc)
            source_mat = None
        if not source_mat:
            self.report({'ERROR'}, "Could not create the first procedural frame")
            return {'CANCELLED'}

        fbp_set_procedural_metadata(source_mat, desired_kind)
        label = fbp_procedural_frame_display_name(
            rig, source_mat, desired_kind
        )
        entry = {
            "name": label,
            "duration": max(1, int(getattr(rig, 'fbp_global_duration', 1) or 1)),
            "is_selected": True,
            "is_empty": False,
            "filepath": "",
            "procedural_kind": desired_kind,
            "material": source_mat,
        }
        if not fbp_apply_sequence_entries_to_rig(rig, [entry]):
            self.report({'ERROR'}, "Could not convert the Color plane to animation")
            return {'CANCELLED'}
        rig.fbp_images_index = 0
        try:
            if len(rig.fbp_images):
                rig.fbp_images[0].is_selected = True
        except FBP_DATA_ERRORS:
            pass
        fbp_load_active_procedural_frame_to_rig(rig)
        do_update_animation(rig)
        fbp_jump_timeline_to_sequence_row(context, rig, 0)
        self.report({'INFO'}, f"Created one {label} animation frame")
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
            self.report({'WARNING'}, "Select one Frame By Plane rig first")
            return {'CANCELLED'}
        if getattr(rig, "fbp_is_color_plane", False) and not fbp_color_plane_can_have_frames(rig):
            self.report({'WARNING'}, "Holdout planes are static masks and cannot have animation frames")
            return {'CANCELLED'}

        if not getattr(rig, "fbp_is_color_plane", False):
            self.report({'WARNING'}, "Native image planes no longer use generated empty material frames. Use an image with alpha, or Start Frame for pre-start transparency.")
            return {'CANCELLED'}


        if self.frame_mode == 'COLOR':
            requested_kind = 'SOLID'
        elif self.frame_mode == 'GRADIENT':
            requested_kind = 'GRADIENT'
        else:
            requested_kind = _fbp_requested_procedural_frame_kind(rig)
            if requested_kind == 'HOLDOUT':
                self.report({'WARNING'}, "Holdout planes are static masks and cannot have animation frames")
                return {'CANCELLED'}

        old_mode = getattr(rig, 'fbp_color_plane_mode', 'SOLID')
        # Silent assignment avoids rebuilding the active frame just because
        # the user chooses which kind of new frame to insert. Abort instead
        # of creating a material with the wrong type if the RNA write fails.
        if (
            str(getattr(rig, "fbp_color_plane_mode", "SOLID") or "SOLID")
            != requested_kind
            and not fbp_set_rna_property_silent(
                rig, "fbp_color_plane_mode", requested_kind
            )
        ):
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
            if old_mode != requested_kind and not fbp_set_rna_property_silent(
                rig, 'fbp_color_plane_mode', old_mode
            ):
                self.report({'WARNING'}, "The previous procedural plane type could not be restored")

        if not mat:
            self.report({'ERROR'}, "Could not create the procedural frame material")
            return {'CANCELLED'}

        fbp_set_procedural_metadata(mat, requested_kind)
        kind = requested_kind
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
        fbp_jump_timeline_to_sequence_row(context, rig, result)

        self.report({'INFO'}, f"Inserted {label}")
        return {'FINISHED'}

class FBP_OT_InsertLinkedImageAfterSelected(Operator):
    bl_idname      = "fbp.insert_linked_image_after_selected"
    bl_label       = "Import Frame"
    bl_description = "Import a new image frame after the active frame or after the last checked frame"
    bl_options     = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(
        name="Layer",
        description="Frame By Plane layer captured before the file browser opens",
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    rig_key: StringProperty(
        name="Layer Runtime ID",
        description="Runtime identity used to resolve a renamed layer safely",
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    anchor_uid: StringProperty(
        name="Insert After Row ID",
        description="Persistent frame identity used as the insertion anchor",
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    filepath:  StringProperty(description="Selected media file path returned by Blender's file browser.", subtype='FILE_PATH')
    directory: StringProperty(description="Folder currently selected in Blender's file browser.", subtype='DIR_PATH')
    files:     CollectionProperty(description="Files selected in Blender's file browser for this import or replacement action.", type=bpy.types.OperatorFileListElement)

    def invoke(self, context, event):
        del event
        rig = context.object if context.object and getattr(context.object, "is_fbp_control", False) else None
        if not rig:
            rigs = get_selected_rigs(context)
            rig = rigs[0] if rigs else None
        if not rig or not getattr(rig, 'fbp_plane_target', None):
            return {'CANCELLED'}
        ensure_unique_item_identities(getattr(rig, 'fbp_images', ()), 'stable_id')
        self.rig_name = str(getattr(rig, 'name', '') or '')
        self.rig_key = fbp_obj_runtime_token(rig)
        items = getattr(rig, 'fbp_images', ())
        checked = [index for index, item in enumerate(items) if bool(getattr(item, 'is_selected', False))]
        if checked:
            anchor_index = checked[-1]
        elif items:
            anchor_index = max(0, min(
                int(getattr(rig, 'fbp_images_index', 0) or 0), len(items) - 1,
            ))
        else:
            anchor_index = -1
        self.anchor_uid = (
            str(getattr(items[anchor_index], 'stable_id', '') or '')
            if anchor_index >= 0 else ''
        )
        path = context.scene.fbp_project_path or context.scene.fbp_last_directory
        if path:
            self.directory = path
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        rig = fbp_find_id_by_runtime_key(
            bpy.data.objects, self.rig_key, self.rig_name,
        ) if self.rig_key else None
        if not rig and not self.rig_key:
            rig = context.object if context.object and getattr(context.object, "is_fbp_control", False) else None
        if not rig and not self.rig_key:
            rigs = get_selected_rigs(context)
            rig = rigs[0] if rigs else None
        if not rig or not rig.fbp_plane_target:
            self.report({'WARNING'}, "Select one Frame By Plane rig first")
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
        try:
            source_directory, source_files, durations, prepared_media = (
                fbp_prepare_media_source(context, self.directory, [chosen])
            )
        except Exception as exc:
            fbp_warn("Could not prepare imported frame media", exc)
            self.report({'ERROR'}, f"Could not import {chosen}: {exc}")
            return {'CANCELLED'}

        default_duration = max(1, int(getattr(rig, 'fbp_global_duration', 1) or 1))
        durations = list(durations or ())
        new_entries = [
            {
                "name": filename,
                "duration": durations[index] if index < len(durations) else default_duration,
                "is_selected": True,
                "is_empty": False,
                "filepath": os.path.join(source_directory, filename),
                "procedural_kind": "AUTO",
            }
            for index, filename in enumerate(source_files)
        ]
        entries = fbp_sequence_entries_from_rig(rig)
        anchor_index = index_for_identity(
            getattr(rig, 'fbp_images', ()), 'stable_id', self.anchor_uid,
            default=-1,
        )
        if anchor_index >= 0:
            insert_at = anchor_index + 1
        elif not self.anchor_uid:
            checked = [index for index, data in enumerate(entries) if bool(data.get("is_selected", False))]
            if checked:
                insert_at = checked[-1] + 1
            else:
                current = int(getattr(rig, "fbp_images_index", 0) or 0)
                insert_at = min(max(current, 0), len(entries) - 1) + 1 if entries else 0
        else:
            self.report({'WARNING'}, "The insertion frame no longer exists")
            return {'CANCELLED'}
        entries[insert_at:insert_at] = new_entries
        if not fbp_apply_sequence_entries_to_rig(rig, entries):
            self.report({'WARNING'}, "Could not rebuild native image sequence")
            return {'CANCELLED'}
        rig.fbp_images_index = insert_at
        first_path = new_entries[0]["filepath"]
        if not rig.fbp_preview_path:
            rig.fbp_preview_path = first_path
        fbp_jump_timeline_to_sequence_row(context, rig, insert_at)
        if prepared_media is not None and prepared_media.animated:
            self.report({'INFO'}, f"Imported {len(new_entries)} animated frames from {chosen}")
        else:
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
            self.report({'WARNING'}, "Select one Frame By Plane layer first")
            return {'CANCELLED'}
        backend_type = fbp_layer_backend_type(rig)
        is_color_plane = bool(getattr(rig, "fbp_is_color_plane", False))
        if not is_color_plane and backend_type not in {'NATIVE_IMAGE', 'NATIVE_SEQUENCE'}:
            self.report({'WARNING'}, "Transparent frames are available only for image and Color Plane sequences")
            return {'CANCELLED'}

        material = None
        if is_color_plane:
            old_mode = getattr(rig, 'fbp_color_plane_mode', 'SOLID')
            fbp_set_rna_property_silent(rig, 'fbp_color_plane_mode', 'SOLID')
            try:
                material, _label, _is_empty = fbp_create_procedural_frame_material_for_rig(
                    rig, len(getattr(rig, 'fbp_images', ())) + 1
                )
                if material:
                    fbp_set_procedural_metadata(material, 'SOLID')
                    fbp_set_solid_material_color(material, (0.0, 0.0, 0.0, 0.0))
                    material.diffuse_color = (0.0, 0.0, 0.0, 0.0)
            finally:
                if old_mode != 'SOLID':
                    fbp_set_rna_property_silent(rig, 'fbp_color_plane_mode', old_mode)
            if material is None:
                self.report({'ERROR'}, "Could not create a transparent Color Plane frame")
                return {'CANCELLED'}
        entry = {
            "name": "Alpha",
            "duration": max(1, int(getattr(rig, 'fbp_global_duration', 1) or 1)),
            "is_selected": True,
            "is_empty": True,
            "filepath": "",
            "procedural_kind": "AUTO" if not is_color_plane else "SOLID",
        }
        insert_at = fbp_insert_sequence_entry(rig, entry, material)
        if insert_at < 0:
            self.report({'WARNING'}, "Could not insert transparent frame")
            return {'CANCELLED'}
        fbp_jump_timeline_to_sequence_row(context, rig, insert_at)
        self.report({'INFO'}, "Alpha frame added")
        return {'FINISHED'}


class FBP_OT_LinkImageFrame(Operator):
    bl_idname      = "fbp.link_image_frame"
    bl_label       = "Link Image to Frame"
    bl_description = "Link or replace the image/video used by this frame"
    bl_options     = {'REGISTER', 'UNDO'}

    index:     IntProperty(description="Zero-based index of the frame, drawing, layer or setup entry targeted by this action.", default=-1)
    rig_name:  StringProperty(description="Name of the Frame By Plane control rig targeted by this action. Stored only long enough to resolve the object safely.", default="")
    rig_key: StringProperty(
        name="Layer Runtime ID",
        description="Runtime identity used to resolve a renamed layer safely",
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    frame_uid: StringProperty(
        name="Frame Row ID",
        description="Persistent frame identity captured before the file browser opens",
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    filepath:  StringProperty(description="Selected media file path returned by Blender's file browser.", subtype='FILE_PATH')
    directory: StringProperty(description="Folder currently selected in Blender's file browser.", subtype='DIR_PATH')
    files:     CollectionProperty(description="Files selected in Blender's file browser for this import or replacement action.", type=bpy.types.OperatorFileListElement)
    filter_glob: StringProperty(
        description="Show only media compatible with this layer backend",
        default=";".join(f"*{ext}" for ext in sorted(FBP_SUPPORTED_IMAGE_EXT)),
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    def invoke(self, context, event):
        del event
        rig = bpy.data.objects.get(self.rig_name) if self.rig_name else None
        if rig is None:
            rigs = get_selected_rigs(context)
            rig = rigs[0] if rigs else None
        if rig is None or not (0 <= int(self.index) < len(getattr(rig, 'fbp_images', ()))):
            return {'CANCELLED'}
        self.rig_name = str(getattr(rig, 'name', '') or '')
        self.rig_key = fbp_obj_runtime_token(rig)
        ensure_unique_item_identities(getattr(rig, 'fbp_images', ()), 'stable_id')
        self.frame_uid = str(getattr(rig.fbp_images[int(self.index)], 'stable_id', '') or '')
        backend_type = fbp_layer_backend_type(rig) if rig is not None else 'NATIVE_IMAGE'
        extensions = FBP_SUPPORTED_VIDEO_EXT if backend_type == 'NATIVE_MOVIE' else FBP_SUPPORTED_IMAGE_EXT
        self.filter_glob = ";".join(f"*{ext}" for ext in sorted(extensions))
        path = context.scene.fbp_project_path or context.scene.fbp_last_directory
        if path:
            self.directory = path
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        rig = fbp_find_id_by_runtime_key(
            bpy.data.objects, self.rig_key, self.rig_name,
        ) if self.rig_key else (bpy.data.objects.get(self.rig_name) if self.rig_name else None)
        if (not rig or not getattr(rig, "is_fbp_control", False)) and not self.rig_key:
            rig = context.object if context.object and getattr(context.object, "is_fbp_control", False) else None
        if not rig and not self.rig_key:
            rigs = get_selected_rigs(context)
            rig = rigs[0] if rigs else None
        if not rig or not rig.fbp_plane_target:
            self.report({'WARNING'}, "The target Frame By Plane layer no longer exists")
            return {'CANCELLED'}
        resolved_index = index_for_identity(
            rig.fbp_images, 'stable_id', self.frame_uid, default=-1,
        )
        if resolved_index < 0 and not self.frame_uid:
            resolved_index = int(self.index)
        if not (0 <= resolved_index < len(rig.fbp_images)):
            self.report({'WARNING'}, "Invalid frame index")
            return {'CANCELLED'}
        self.index = resolved_index
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
        chosen_is_video = is_supported_video_file(chosen)
        if backend_type == 'NATIVE_MOVIE' and not chosen_is_video:
            self.report({'WARNING'}, "Movie Plane rows accept video files only")
            return {'CANCELLED'}
        if backend_type != 'NATIVE_MOVIE' and chosen_is_video:
            self.report({'WARNING'}, "Image Plane rows accept image files only")
            return {'CANCELLED'}
        if chosen_is_video and len(rig.fbp_images) != 1:
            self.report({'WARNING'}, "A video must remain a standalone one-row Movie Plane")
            return {'CANCELLED'}

        context.scene.fbp_last_directory = self.directory
        try:
            source_directory, source_files, _durations, prepared_media = (
                fbp_prepare_media_source(context, self.directory, [chosen])
            )
        except Exception as exc:
            fbp_warn("Could not prepare relinked media", exc)
            self.report({'ERROR'}, f"Could not link {chosen}: {exc}")
            return {'CANCELLED'}
        if len(source_files) != 1:
            if backend_type == 'NATIVE_MOVIE':
                self.report({'WARNING'}, "Use Replace Sequence to convert a Movie Plane to animated image frames")
                return {'CANCELLED'}
            entries = fbp_sequence_entries_from_rig(rig)
            durations = list(_durations or ())
            fallback_duration = max(1, int(entries[self.index].get("duration", 1) or 1))
            replacement_entries = [
                {
                    "name": filename,
                    "duration": durations[index] if index < len(durations) else fallback_duration,
                    "is_selected": True,
                    "is_empty": False,
                    "filepath": os.path.join(source_directory, filename),
                    "procedural_kind": "AUTO",
                }
                for index, filename in enumerate(source_files)
            ]
            entries[self.index:self.index + 1] = replacement_entries
            if not fbp_apply_sequence_entries_to_rig(rig, entries):
                self.report({'WARNING'}, "Could not replace this row with animated media")
                return {'CANCELLED'}
            fbp_set_rna_property_silent(rig, 'fbp_images_index', self.index)
            if not rig.fbp_preview_path:
                rig.fbp_preview_path = replacement_entries[0]["filepath"]
            self.report({'INFO'}, f"Replaced one row with {len(replacement_entries)} frames from {chosen}")
            return {'FINISHED'}
        img_path = os.path.join(source_directory, source_files[0])

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
            return True

        try:
            with FBPTransaction(
                f"Relink frame {self.index + 1}",
                kind="MEDIA_RELINK",
                journal_owner=rig,
                context={
                    "frame_uid": self.frame_uid,
                    "index": self.index,
                    "source": previous['filepath'],
                    "destination": img_path,
                },
            ) as transaction:
                transaction.defer_rollback(
                    restore_row,
                    label="restore media row and native backend",
                )
                transaction.checkpoint("UPDATE_ROW")
                item.name = chosen if prepared_media is not None else source_files[0]
                item.filepath = img_path
                item.is_empty = False
                item.is_selected = True
                fbp_set_rna_property_silent(rig, 'fbp_images_index', self.index)
                if not rig.fbp_preview_path:
                    rig.fbp_preview_path = img_path

                transaction.checkpoint("REBUILD_BACKEND")
                if not (
                    fbp_refresh_sequence_backend_from_rig(rig)
                    or fbp_rebuild_sequence_backend_from_rig(rig)
                ):
                    raise RuntimeError("Could not rebuild image sequence backend")
                transaction.checkpoint("VALIDATED")
                transaction.commit()
        except Exception as exc:
            fbp_warn("Could not rebuild image sequence backend after relinking", exc)
            self.report({'WARNING'}, "Could not rebuild image sequence backend")
            return {'CANCELLED'}

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
            "stable_id": str(getattr(item, "stable_id", "") or "") or uuid.uuid4().hex,
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
        changed = False
        feedback_given = False
        for rig in get_selected_rigs(context):
            if not getattr(rig, "fbp_plane_target", None):
                continue

            backend_type = fbp_layer_backend_type(rig)
            if backend_type == 'CUTOUT':
                continue
            if backend_type == 'NATIVE_MOVIE':
                self.report({'WARNING'}, "Movie Planes use one source row and do not support frame-list edits")
                feedback_given = True
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
            active_stable_id = str(image_data[idx].get("stable_id", "") or "") if image_data else ""

            if self.action == 'REMOVE':
                remove_indices = self._selected_indices(image_data) or ([idx] if idx < len(image_data) else [])
                if backend_type in {'NATIVE_IMAGE', 'NATIVE_SEQUENCE'} and len(remove_indices) >= len(image_data):
                    self.report({'WARNING'}, "An image plane must keep at least one frame")
                    feedback_given = True
                    continue
                for i in reversed(remove_indices):
                    if 0 <= i < len(image_data):
                        del image_data[i]
                new_index = next((
                    row_index for row_index, data in enumerate(image_data)
                    if active_stable_id and str(data.get("stable_id", "") or "") == active_stable_id
                ), min(idx, len(image_data) - 1) if image_data else 0)
                applied = self._apply_items(rig, image_data, new_index)
                changed = applied or changed
                feedback_given = (not applied) or feedback_given

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
                applied = self._apply_items(rig, image_data, new_index)
                changed = applied or changed
                feedback_given = (not applied) or feedback_given

            elif self.action == 'DUPLICATE_SELECTED':
                selected_indices = self._selected_indices(image_data)
                if not selected_indices:
                    self.report({'WARNING'}, "No checked frames to duplicate")
                    feedback_given = True
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
                        dup["stable_id"] = uuid.uuid4().hex
                        dup["is_selected"] = True
                image_data[insert_at:insert_at] = duplicates
                applied = self._apply_items(rig, image_data, insert_at)
                changed = applied or changed
                feedback_given = (not applied) or feedback_given

        if changed:
            return {'FINISHED'}
        if not feedback_given:
            self.report({'INFO'}, "No frame-list changes were needed")
        return {'CANCELLED'}

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


class FBP_OT_OptimizeSequenceFrames(Operator):
    bl_idname = "fbp.optimize_sequence_frames"
    bl_label = "Analyze and Consolidate Holds"
    bl_description = (
        "Analyze decoded pixels, merge consecutive identical frames into holds, "
        "and replace fully transparent files with logical empty frames"
    )
    bl_options = {'REGISTER', 'UNDO'}

    collapse_duplicates: BoolProperty(
        name="Consolidate Exact Holds",
        description=(
            "Merge only consecutive pixel-identical frames and add their durations; "
            "source image files are not deleted or changed"
        ),
        default=True,
    )
    replace_transparent: BoolProperty(
        name="Use Logical Transparent Frames",
        description=(
            "Replace fully transparent image rows with Frame By Plane empty intervals; "
            "source files remain untouched"
        ),
        default=True,
    )
    alpha_threshold: IntProperty(
        name="Transparent Alpha Threshold",
        description="Treat a frame as empty only when every alpha value is at or below this byte value",
        default=0,
        min=0,
        max=255,
    )
    rig_name: StringProperty(
        name="Sequence Layer",
        description="Layer captured before the analysis dialog opens",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    rig_key: StringProperty(
        name="Sequence Layer Runtime ID",
        description="Runtime identity used to resolve a renamed layer safely",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )

    @staticmethod
    def _active_rig(context):
        obj = getattr(context, "object", None)
        if obj and getattr(obj, "is_fbp_control", False):
            return obj
        rigs = get_selected_rigs(context)
        return rigs[0] if rigs else None

    def _resolved_rig(self, context):
        if self.rig_key:
            return fbp_find_id_by_runtime_key(
                bpy.data.objects, self.rig_key, self.rig_name,
            )
        if self.rig_name:
            return bpy.data.objects.get(self.rig_name)
        return self._active_rig(context)

    def invoke(self, context, event):
        del event
        rig = self._active_rig(context)
        if not rig or fbp_layer_backend_type(rig) not in {'NATIVE_IMAGE', 'NATIVE_SEQUENCE'}:
            self.report({'WARNING'}, "Select one image or image-sequence layer")
            return {'CANCELLED'}
        if not len(getattr(rig, "fbp_images", ())):
            self.report({'WARNING'}, "The selected layer has no image frames")
            return {'CANCELLED'}
        self.rig_name = str(getattr(rig, "name", "") or "")
        self.rig_key = fbp_obj_runtime_token(rig)
        return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, context):
        layout = configure_layout(self.layout)
        rig = self._resolved_rig(context)
        section_header(layout, "Sequence Analysis", icon=fbp_icon("IMAGE_DATA"))
        if rig:
            layout.label(text=f"{rig.name}: {len(rig.fbp_images)} frame(s)")
        layout.prop(self, "collapse_duplicates")
        layout.prop(self, "replace_transparent")
        threshold = layout.row(align=True)
        threshold.enabled = self.replace_transparent
        threshold.prop(self, "alpha_threshold")
        layout.separator()
        layout.label(text="Comparison is exact after RGBA decoding.", icon=fbp_icon("INFO"))
        layout.label(text="Timing is preserved; source files are never modified.", icon=fbp_icon("LOCKED"))

    def execute(self, context):
        if not self.collapse_duplicates and not self.replace_transparent:
            self.report({'WARNING'}, "Enable at least one optimization")
            return {'CANCELLED'}
        rig = self._resolved_rig(context)
        if not rig or fbp_layer_backend_type(rig) not in {'NATIVE_IMAGE', 'NATIVE_SEQUENCE'}:
            self.report({'WARNING'}, "The sequence layer no longer exists")
            return {'CANCELLED'}

        entries = fbp_sequence_entries_from_rig(rig)
        old_index = int(getattr(rig, "fbp_images_index", 0) or 0)
        before_duration = sum(max(1, int(entry.get("duration", 1) or 1)) for entry in entries)
        try:
            optimized, stats = fbp_optimize_sequence_entries(
                entries,
                collapse_duplicates=bool(self.collapse_duplicates),
                replace_transparent=bool(self.replace_transparent),
                alpha_threshold=int(self.alpha_threshold),
                path_resolver=lambda path: os.path.abspath(bpy.path.abspath(path)),
            )
        except Exception as exc:
            fbp_warn("Sequence image analysis failed", exc)
            self.report({'ERROR'}, f"Sequence analysis failed: {exc}")
            return {'CANCELLED'}

        after_duration = sum(max(1, int(entry.get("duration", 1) or 1)) for entry in optimized)
        if after_duration != before_duration:
            self.report({'ERROR'}, "Sequence optimization was cancelled because timing changed")
            return {'CANCELLED'}
        if stats.unreadable_paths:
            self.report({'WARNING'}, f"Skipped {len(stats.unreadable_paths)} missing or unreadable frame(s)")
        if not stats.collapsed_rows and not stats.transparent_rows:
            self.report({'INFO'}, "Analysis complete: no exact holds or transparent files to consolidate")
            return {'FINISHED'}
        if not fbp_apply_sequence_entries_to_rig(rig, optimized):
            self.report({'ERROR'}, "Could not rebuild the optimized sequence; original rows were restored")
            return {'CANCELLED'}

        fbp_set_rna_property_silent(
            rig,
            "fbp_images_index",
            max(0, min(old_index, len(optimized) - 1)),
        )
        fbp_tag_redraw(context)
        self.report(
            {'INFO'},
            f"Consolidated {stats.collapsed_rows} duplicate frame(s) and "
            f"{stats.transparent_rows} transparent frame(s); timing preserved",
        )
        return {'FINISHED'}


class FBP_OT_PopupSequenceSettings(Operator):
    bl_idname = "fbp.popup_sequence_settings"
    bl_label = "Timing / Sequence Settings"
    bl_description = "Open timing and sequence controls for the selected Frame By Plane layer"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        if not get_selected_rigs(context):
            self.report({'WARNING'}, "Select a Frame By Plane layer first")
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        rig = get_selected_rigs(context)[0]
        layout = configure_layout(self.layout)
        section_header(layout, rig.name, icon=fbp_icon("TIME"))
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
                    try:
                        from .object_masks import clone_object_mask_helpers
                        clone_object_mask_helpers(rig, new_rig, context=context)
                    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                        pass
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
    bl_description = "Merge selected Frame By Plane layers into the active layer sequence and delete the others"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        active = context.view_layer.objects.active
        if active and getattr(active, "is_fbp_plane", False) and getattr(active.parent, "is_fbp_control", False):
            active = active.parent
        if not active or not is_fbp_layer_object(active):
            self.report({'WARNING'}, "Make the target Frame By Plane rig active")
            return {'CANCELLED'}
        rigs = get_selected_fbp_roots(context)
        if active not in rigs:
            rigs.append(active)
        rigs = sorted(set(rigs), key=lambda r: (getattr(r, "fbp_depth_order", 0), natural_sort_key(r.name)))
        if len(rigs) < 2:
            self.report({'WARNING'}, "Select at least two Frame By Plane layers")
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
            self.report({'WARNING'}, "Select one Frame By Plane rig")
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
        # A Grease Pencil canvas represents a child row of an FBP layer, not
        # the layer itself. Never resolve it back to the owner for deletion,
        # including explicit name-based actions from the Layer List.
        target_name = str(getattr(self, 'rig_name', '') or '')
        try:
            from .grease_pencil_bridge import delete_gp_canvas, is_gp_canvas
            canvas = bpy.data.objects.get(target_name) if target_name else getattr(context, 'object', None)
            if is_gp_canvas(canvas):
                deleted, users, error = delete_gp_canvas(context, canvas)
                if not deleted:
                    self.report({'ERROR'}, error or 'Could not delete the Grease Pencil canvas')
                    return {'CANCELLED'}
                self.report({'INFO'}, f"Deleted Grease Pencil canvas and detached {users} mask user{'s' if users != 1 else ''}")
                return {'FINISHED'}
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        exact_target = bpy.data.objects.get(target_name)
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
        try:
            from .grease_pencil_bridge import is_gp_canvas
            if is_gp_canvas(getattr(context, 'object', None)):
                return bpy.ops.fbp.delete_grease_pencil_canvas('INVOKE_DEFAULT')
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        roots = get_selected_fbp_roots(context)
        if roots:
            deleted = delete_fbp_rigs(context, roots)
            if deleted > 0:
                self.report({'INFO'}, f"Deleted {deleted} Frame By Plane layer(s)")
                return {'FINISHED'}
            return {'CANCELLED'}
        return bpy.ops.object.delete('INVOKE_DEFAULT')
