"""Focused Frame by Plane operator module."""

import hashlib
import math
import os
import re
import tempfile
import time
from urllib.parse import unquote, urlparse

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Operator

from .constants import FBP_PROJECT_COLLECTION_PREFIX, FBP_SUPPORTED_MEDIA_EXT, fbp_icon
from .path_utils import (
    clean_layer_name_from_path,
    is_supported_media_file,
    is_supported_video_file,
    is_technical_map_file,
)
from .builder import (
    apply_fit_to_camera,
    build_fbp_rig,
    fbp_scene_orientation_is_horizontal,
)
from .materials import get_or_create_fbp_gradient_preview_material
from .importer import (
    fbp_begin_fast_import,
    fbp_build_project_folder,
    fbp_child_entries,
    fbp_collect_mixed_folder_entries,
    fbp_end_fast_import,
    fbp_fast_import_is_active,
    fbp_folder_direct_dirs,
    fbp_folder_direct_images,
    fbp_group_direct_media_into_layers,
    fbp_order_sequence_files,
    fbp_sequence_exposure_durations,
    fbp_scan_project_layers_for_setup,
)
from .layered_import import (
    FBP_LAYERED_EXTENSIONS,
    fbp_default_psd_cache_root,
    fbp_default_procreate_cache_root,
    fbp_extract_psd_layers,
    fbp_extract_procreate_layers,
    fbp_inspect_psd_layers,
    fbp_inspect_procreate_layers,
    fbp_layered_backend_status,
    fbp_layered_blend_mode_for_blender,
    fbp_probe_layered_document,
)
from .effects_registry import (
    FBP_EFFECT_CLIPPING_MASK,
    FBP_EFFECT_IMPORTED_MASK,
    FBP_EFFECT_LAYER_BLEND,
)
from .geometry_nodes import (
    fbp_add_effect,
    fbp_sync_clipping_masks,
    fbp_update_shader_effect,
)
from .layers import (
    fbp_mark_layer_cache_dirty,
    fbp_layer_backend_type,
    fbp_resolve_rig_from_any_object,
    get_or_create_child_collection,
    get_selected_fbp_roots,
    move_object_to_collection,
    object_in_view_layer,
    set_collection_color_tag,
    set_viewport_object_color,
    sync_collection_colors_to_rigs,
    update_rig_visibility,
)
from .scene_sync import fbp_remove_plane_datablock, sync_layer_collection
from .runtime import (
    fbp_set_rna_property_silent, fbp_warn, FBP_DATA_ERRORS, FBP_DATA_IO_ERRORS,
    fbp_obj_runtime_key, fbp_find_id_by_runtime_key,
)
from .core import (
    apply_camera_ratio_settings,
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


def _fbp_draw_import_alpha_crop_options(layout, scene):
    """Draw the shared import-only transparent-border crop controls."""
    row = layout.row(align=False)
    row.prop(scene, "fbp_import_crop_alpha", text="Crop Transparent Borders", icon='FULLSCREEN_EXIT')
    padding = row.row(align=False)
    padding.enabled = bool(getattr(scene, "fbp_import_crop_alpha", False))
    padding.prop(scene, "fbp_import_crop_alpha_padding", text="Padding")


_FBP_SAFE_SEQUENCE_PREFIX_RE = re.compile(r"[^0-9A-Za-z_\-]+")
_FBP_SAFE_CLIPBOARD_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

# Short-lived runtime cache shared by the folder picker and media FileHandler.
# It prevents the same hierarchy from being rescanned between invoke/draw/execute
# while never serializing filesystem state into the .blend file.
_FBP_FOLDER_SCAN_CACHE = globals().get("_FBP_FOLDER_SCAN_CACHE", {})
_FBP_FOLDER_SCAN_CACHE_TTL = 20.0
_FBP_FOLDER_SCAN_CACHE_MAX = 8
_FBP_FOLDER_SCAN_CACHE_SCHEMA = 3

# Folder imports can create many Blender datablocks in one operation. These
# thresholds do not block ordinary projects: the first pair only adds a visible
# warning, while the second pair requires an explicit confirmation checkbox.
_FBP_FOLDER_IMPORT_WARNING_LAYERS = 256
_FBP_FOLDER_IMPORT_WARNING_FILES = 2000
_FBP_FOLDER_IMPORT_CONFIRM_LAYERS = 1000
_FBP_FOLDER_IMPORT_CONFIRM_FILES = 10000
_FBP_FOLDER_PREVIEW_LIMIT = 8
_FBP_TOON_BOOM_WARNING_TIMELINE_FRAMES = 100_000
_FBP_TOON_BOOM_CONFIRM_TIMELINE_FRAMES = 1_000_000


def _fbp_reset_folder_import_confirmations(self, context):
    """Clear confirmations whenever an import choice changes."""
    for name in ("allow_very_large_import", "confirm_large_folder", "confirm_single_root_only"):
        try:
            setattr(self, name, False)
        except (AttributeError, TypeError, ValueError):
            continue


def _fbp_note_successful_import(context, *, multiplane=False):
    """Update the optional local review counter after a completed import."""
    try:
        from .feedback import fbp_note_successful_operation
        fbp_note_successful_operation(context, multiplane=bool(multiplane))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not update the optional review reminder", exc)


def _fbp_multiplane_runtime_snapshot(context):
    """Capture only lightweight IDs needed to roll back an unexpected build."""
    scene = getattr(context, 'scene', None)
    if scene is None:
        return None
    try:
        return {
            'scene_key': fbp_obj_runtime_key(scene),
            'scene_name': str(scene.name),
            'object_keys': {
                key for obj in scene.objects
                for key in (fbp_obj_runtime_key(obj),)
                if key is not None
            },
            'collection_keys': {
                key for collection in bpy.data.collections
                for key in (fbp_obj_runtime_key(collection),)
                if key is not None
            },
            'camera': getattr(scene, 'camera', None),
            'cursor': scene.cursor.location.copy(),
            'pivot': str(getattr(scene.tool_settings, 'transform_pivot_point', 'MEDIAN_POINT')),
        }
    except FBP_DATA_ERRORS:
        return None


def _fbp_rollback_unexpected_multiplane_build(context, snapshot):
    """Remove only data created by a failed Multiplane operator run."""
    if not snapshot:
        return False
    scene = fbp_find_id_by_runtime_key(
        bpy.data.scenes,
        snapshot.get('scene_key'),
        str(snapshot.get('scene_name', '') or ''),
    )
    if scene is None:
        return False

    try:
        scene.camera = snapshot.get('camera')
    except FBP_DATA_ERRORS:
        pass
    try:
        scene.cursor.location = snapshot.get('cursor')
        scene.tool_settings.transform_pivot_point = snapshot.get('pivot', 'MEDIAN_POINT')
    except FBP_DATA_ERRORS:
        pass

    previous_objects = set(snapshot.get('object_keys', ()))
    orphan_data = []
    for obj in tuple(scene.objects):
        try:
            if fbp_obj_runtime_key(obj) in previous_objects:
                continue
            owned = bool(getattr(obj, 'is_fbp_control', False) or getattr(obj, 'is_fbp_plane', False))
            owned = owned or bool(obj.get('fbp_generated_multiplane_camera', False))
            if not owned:
                continue
            data = getattr(obj, 'data', None)
            if data is not None:
                orphan_data.append(data)
            bpy.data.objects.remove(obj, do_unlink=True)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
            continue

    for datablock in orphan_data:
        try:
            if int(getattr(datablock, 'users', 0) or 0) != 0:
                continue
            if isinstance(datablock, bpy.types.Mesh):
                bpy.data.meshes.remove(datablock)
            elif isinstance(datablock, bpy.types.Camera):
                bpy.data.cameras.remove(datablock)
        except FBP_DATA_ERRORS:
            continue

    previous_collections = set(snapshot.get('collection_keys', ()))
    # Child collections must be removed before their parents. Repeat only while
    # progress is made and never touch a pre-existing or non-empty collection.
    for _pass in range(8):
        removed = False
        for collection in reversed(tuple(bpy.data.collections)):
            try:
                if fbp_obj_runtime_key(collection) in previous_collections:
                    continue
                if collection.objects or collection.children:
                    continue
                bpy.data.collections.remove(collection)
                removed = True
            except FBP_DATA_ERRORS:
                continue
        if not removed:
            break

    try:
        fbp_mark_layer_cache_dirty(scene)
        sync_layer_collection(context)
    except FBP_DATA_ERRORS:
        pass
    return True


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
        camera_data.show_passepartout = True
        camera_data.passepartout_alpha = 1.0
        return True
    except FBP_DATA_ERRORS:
        return False


def _fbp_clear_pending_source_metadata(item):
    """Clear external-source metadata after manually replacing setup media."""
    defaults = {
        'source_from_layered': False,
        'source_document': '',
        'source_layer_path': '',
        'source_layer_kind': '',
        'source_layer_visible': True,
        'source_layer_opacity': 1.0,
        'source_blend_mode': 'NORMAL',
        'source_is_clipping': False,
        'source_mask_file': '',
        'source_blend_supported': False,
        'source_cache_key': '',
        'source_preset': '',
        'source_frame_numbers_str': '',
        'source_durations_str': '',
        'source_flattened_group': False,
        'source_warnings': '',
    }
    for name, value in defaults.items():
        try:
            setattr(item, name, value)
        except FBP_DATA_ERRORS:
            continue


def _fbp_clear_layered_import_report(scene):
    """Reset scene-level layered import diagnostics without touching setup rows."""
    defaults = {
        'fbp_layered_report_source': '',
        'fbp_layered_report_format': '',
        'fbp_layered_report_backend': '',
        'fbp_layered_report_cache_reused': False,
        'fbp_layered_report_fallback_preview': False,
        'fbp_layered_report_skipped_layers': 0,
        'fbp_layered_report_flattened_groups': 0,
        'fbp_layered_report_merged_clipping': 0,
        'fbp_layered_report_decoded_layers': 0,
        'fbp_layered_report_transferred_blends': 0,
        'fbp_layered_report_transferred_masks': 0,
        'fbp_layered_report_transferred_clipping': 0,
        'fbp_layered_report_unsupported_blends': 0,
        'fbp_layered_report_warnings': '',
    }
    for name, value in defaults.items():
        try:
            setattr(scene, name, value)
        except FBP_DATA_ERRORS:
            continue


def _fbp_store_layered_import_report(scene, source_path, extraction):
    """Persist a compact report for the current PSD/PSB/Procreate setup."""
    _fbp_clear_layered_import_report(scene)
    values = {
        'fbp_layered_report_source': str(source_path or ''),
        'fbp_layered_report_format': str(getattr(extraction, 'source_format', '') or 'LAYERED'),
        'fbp_layered_report_backend': str(getattr(extraction, 'backend_version', '') or ''),
        'fbp_layered_report_cache_reused': bool(getattr(extraction, 'reused_cache', False)),
        'fbp_layered_report_fallback_preview': bool(getattr(extraction, 'fallback_preview', False)),
        'fbp_layered_report_skipped_layers': max(0, int(getattr(extraction, 'skipped_layers', 0) or 0)),
        'fbp_layered_report_flattened_groups': max(0, int(getattr(extraction, 'flattened_groups', 0) or 0)),
        'fbp_layered_report_merged_clipping': max(0, int(getattr(extraction, 'merged_clipping_layers', 0) or 0)),
        'fbp_layered_report_decoded_layers': max(0, int(getattr(extraction, 'decoded_layers', 0) or 0)),
        'fbp_layered_report_transferred_blends': max(0, int(getattr(extraction, 'transferred_blend_modes', 0) or 0)),
        'fbp_layered_report_transferred_masks': max(0, int(getattr(extraction, 'transferred_masks', 0) or 0)),
        'fbp_layered_report_transferred_clipping': max(0, int(getattr(extraction, 'transferred_clipping_layers', 0) or 0)),
        'fbp_layered_report_unsupported_blends': max(0, int(getattr(extraction, 'unsupported_blend_modes', 0) or 0)),
        'fbp_layered_report_warnings': '\n'.join(
            str(value) for value in getattr(extraction, 'warnings', ()) if str(value).strip()
        ),
    }
    for name, value in values.items():
        try:
            setattr(scene, name, value)
        except FBP_DATA_ERRORS:
            continue


def _fbp_pending_snapshot(item):
    """Copy one pending setup item into plain Python data."""
    return {
        'name': str(getattr(item, 'name', '') or 'Layer'),
        'collection_name': str(getattr(item, 'collection_name', '') or ''),
        'directory': str(getattr(item, 'directory', '') or ''),
        'files_str': str(getattr(item, 'files_str', '') or ''),
        'is_selected': bool(getattr(item, 'is_selected', False)),
        'follow_collection_color': bool(getattr(item, 'follow_collection_color', True)),
        'fbp_color_tag': str(getattr(item, 'fbp_color_tag', 'COLOR_01') or 'COLOR_01'),
        'source_from_layered': bool(getattr(item, 'source_from_layered', False)),
        'source_document': str(getattr(item, 'source_document', '') or ''),
        'source_layer_path': str(getattr(item, 'source_layer_path', '') or ''),
        'source_layer_kind': str(getattr(item, 'source_layer_kind', '') or ''),
        'source_layer_visible': bool(getattr(item, 'source_layer_visible', True)),
        'source_layer_opacity': float(getattr(item, 'source_layer_opacity', 1.0) or 0.0),
        'source_blend_mode': str(getattr(item, 'source_blend_mode', 'NORMAL') or 'NORMAL'),
        'source_is_clipping': bool(getattr(item, 'source_is_clipping', False)),
        'source_mask_file': str(getattr(item, 'source_mask_file', '') or ''),
        'source_blend_supported': bool(getattr(item, 'source_blend_supported', False)),
        'source_cache_key': str(getattr(item, 'source_cache_key', '') or ''),
        'source_preset': str(getattr(item, 'source_preset', '') or ''),
        'source_frame_numbers_str': str(getattr(item, 'source_frame_numbers_str', '') or ''),
        'source_durations_str': str(getattr(item, 'source_durations_str', '') or ''),
        'source_flattened_group': bool(getattr(item, 'source_flattened_group', False)),
        'source_warnings': str(getattr(item, 'source_warnings', '') or ''),
    }


def _fbp_restore_pending_snapshots(scene, snapshots):
    """Replace pending setup data in one pass without per-row tree rebuilds."""
    scene.fbp_pending_planes.clear()
    for data in snapshots:
        item = scene.fbp_pending_planes.add()
        item.name = data.get('name', 'Layer')
        item.collection_name = data.get('collection_name', '')
        item.directory = data.get('directory', '')
        item.files_str = data.get('files_str', '')
        item.is_selected = bool(data.get('is_selected', False))
        item.follow_collection_color = bool(data.get('follow_collection_color', True))
        item.fbp_color_tag = data.get('fbp_color_tag', 'COLOR_01')
        item.source_from_layered = bool(data.get('source_from_layered', False))
        item.source_document = data.get('source_document', '')
        item.source_layer_path = data.get('source_layer_path', '')
        item.source_layer_kind = data.get('source_layer_kind', '')
        item.source_layer_visible = bool(data.get('source_layer_visible', True))
        item.source_layer_opacity = max(0.0, min(1.0, float(data.get('source_layer_opacity', 1.0))))
        item.source_blend_mode = data.get('source_blend_mode', 'NORMAL')
        item.source_is_clipping = bool(data.get('source_is_clipping', False))
        item.source_mask_file = data.get('source_mask_file', '')
        item.source_blend_supported = bool(data.get('source_blend_supported', False))
        item.source_cache_key = data.get('source_cache_key', '')
        item.source_preset = data.get('source_preset', '')
        item.source_frame_numbers_str = data.get('source_frame_numbers_str', '')
        item.source_durations_str = data.get('source_durations_str', '')
        item.source_flattened_group = bool(data.get('source_flattened_group', False))
        item.source_warnings = data.get('source_warnings', '')


def _fbp_expand_pending_snapshot(data):
    """Expand one multi-file pending row into static one-file plane rows."""
    files = [
        name for name in str(data.get('files_str', '') or '').split('|') if name
    ]
    if len(files) <= 1:
        return [data]
    expanded = []
    base_color = str(data.get('fbp_color_tag', 'COLOR_01') or 'COLOR_01')
    try:
        base_color_index = max(1, min(9, int(base_color.rsplit('_', 1)[-1])))
    except (TypeError, ValueError):
        base_color_index = 1
    follows_collection = bool(data.get('follow_collection_color', True))
    source_numbers = [value for value in str(data.get('source_frame_numbers_str', '') or '').split('|') if value]
    source_durations = [value for value in str(data.get('source_durations_str', '') or '').split('|') if value]
    for offset, filename in enumerate(files):
        row = dict(data)
        row['name'] = clean_layer_name_from_path(filename)
        row['files_str'] = filename
        row['source_frame_numbers_str'] = source_numbers[offset] if offset < len(source_numbers) else ''
        row['source_durations_str'] = source_durations[offset] if offset < len(source_durations) else ''
        if not follows_collection:
            row['fbp_color_tag'] = f"COLOR_{((base_color_index - 1 + offset) % 9) + 1:02d}"
        expanded.append(row)
    return expanded


def _fbp_collection_parent_and_leaf(collection_path):
    """Return the direct parent path and visible leaf name for one setup collection."""
    parts = [part.strip() for part in str(collection_path or '').split('/') if part.strip()]
    if not parts:
        return '', ''
    return ' / '.join(parts[:-1]), parts[-1]


def _fbp_unique_pending_collection_path(scene, desired_path):
    """Return a collection path that does not collide with an existing setup path."""
    desired = str(desired_path or '').strip() or 'Sequence'
    used = {
        str(getattr(item, 'collection_name', '') or '').strip()
        for item in getattr(scene, 'fbp_pending_planes', ())
        if str(getattr(item, 'collection_name', '') or '').strip()
    }
    if desired not in used and not any(path.startswith(desired + ' /') for path in used):
        return desired
    suffix = 2
    while True:
        candidate = f"{desired} {suffix}"
        if candidate not in used and not any(path.startswith(candidate + ' /') for path in used):
            return candidate
        suffix += 1


def _fbp_split_pending_sequence_to_collection(context, index):
    """Replace one pending animated row with a same-named collection of still rows."""
    scene = context.scene
    index = int(index)
    if not (0 <= index < len(scene.fbp_pending_planes)):
        return 0, ''
    snapshots = [_fbp_pending_snapshot(item) for item in scene.fbp_pending_planes]
    source = snapshots[index]
    expanded = _fbp_expand_pending_snapshot(source)
    if len(expanded) <= 1:
        return 0, ''

    parent_path = str(source.get('collection_name', '') or '').strip()
    leaf = str(source.get('name', '') or 'Sequence').strip() or 'Sequence'
    desired_path = f"{parent_path} / {leaf}" if parent_path else leaf
    collection_path = _fbp_unique_pending_collection_path(scene, desired_path)
    for row in expanded:
        row['collection_name'] = collection_path
        row['follow_collection_color'] = True
        row['fbp_color_tag'] = source.get('fbp_color_tag', 'COLOR_01')
        row['is_selected'] = bool(source.get('is_selected', False))

    rebuilt = snapshots[:index] + expanded + snapshots[index + 1:]
    _fbp_restore_pending_snapshots(scene, rebuilt)
    _fbp_select_pending_index(context, index)
    return len(expanded), collection_path


def _fbp_merge_pending_collection_to_sequence(context, collection_path):
    """Replace one leaf collection of still images with a single animated row."""
    scene = context.scene
    path = str(collection_path or '').strip()
    if not path:
        return 0, ''
    snapshots = [_fbp_pending_snapshot(item) for item in scene.fbp_pending_planes]
    direct_indices = [
        index for index, data in enumerate(snapshots)
        if str(data.get('collection_name', '') or '').strip() == path
    ]
    has_children = any(
        str(data.get('collection_name', '') or '').strip().startswith(path + ' /')
        for data in snapshots
    )
    if has_children or len(direct_indices) < 2:
        return 0, ''

    rows = [snapshots[index] for index in direct_indices]
    if any(len([name for name in str(row.get('files_str', '') or '').split('|') if name]) != 1 for row in rows):
        return 0, ''
    filenames = [str(row.get('files_str', '') or '') for row in rows]
    if any(
        not is_supported_media_file(filename)
        or is_supported_video_file(filename)
        or is_technical_map_file(filename)
        for filename in filenames
    ):
        return 0, ''

    raw_directories = [str(row.get('directory', '') or '').strip() for row in rows]
    if any(not directory for directory in raw_directories):
        return 0, ''
    directories = {
        os.path.normcase(os.path.abspath(bpy.path.abspath(directory)))
        for directory in raw_directories
    }
    if len(directories) != 1:
        return 0, ''

    parent_path, leaf = _fbp_collection_parent_and_leaf(path)
    first = dict(rows[0])
    first['name'] = leaf or str(first.get('name', '') or 'Sequence')
    first['collection_name'] = parent_path
    first['files_str'] = '|'.join(str(row.get('files_str', '') or '') for row in rows)
    merged_numbers = [str(row.get('source_frame_numbers_str', '') or '') for row in rows]
    merged_durations = [str(row.get('source_durations_str', '') or '') for row in rows]
    first['source_frame_numbers_str'] = '|'.join(value for value in merged_numbers if value)
    first['source_durations_str'] = '|'.join(value for value in merged_durations if value)
    first['follow_collection_color'] = bool(parent_path)
    first['is_selected'] = any(bool(row.get('is_selected', False)) for row in rows)

    selected_set = set(direct_indices)
    insert_index = direct_indices[0]
    rebuilt = []
    for index, data in enumerate(snapshots):
        if index == insert_index:
            rebuilt.append(first)
        if index in selected_set:
            continue
        rebuilt.append(data)

    _fbp_restore_pending_snapshots(scene, rebuilt)
    _fbp_select_pending_index(context, insert_index)
    return len(rows), first['name']


def _fbp_reverse_pending_selected_order(context):
    """Reverse checked setup rows inside each direct collection, preserving unselected slots."""
    scene = context.scene
    snapshots = [_fbp_pending_snapshot(item) for item in scene.fbp_pending_planes]
    groups = {}
    for index, data in enumerate(snapshots):
        if not bool(data.get('is_selected', False)):
            continue
        key = str(data.get('collection_name', '') or '').strip()
        groups.setdefault(key, []).append(index)

    changed_groups = 0
    for indices in groups.values():
        if len(indices) < 2:
            continue
        reversed_rows = [snapshots[index] for index in reversed(indices)]
        for target_index, row in zip(indices, reversed_rows, strict=True):
            snapshots[target_index] = row
        changed_groups += 1
    if not changed_groups:
        return 0

    _fbp_restore_pending_snapshots(scene, snapshots)
    try:
        scene.fbp_sort_layers_alpha = False
    except FBP_DATA_IO_ERRORS:
        pass
    _fbp_refresh_pending_tree(context)
    return changed_groups


class FBP_OT_TogglePendingSequenceCollection(Operator):
    bl_idname = 'fbp.toggle_pending_sequence_collection'
    bl_label = 'Split / Merge Sequence'
    bl_description = 'Convert the active sequence into a collection of still planes, or merge a compatible leaf collection back into one animated plane; source files are never changed'
    bl_options = {'REGISTER', 'UNDO'}

    pending_index: IntProperty(
        name='Setup Layer',
        description='Optional exact pending layer used by context-menu actions',
        default=-1,
        options={'SKIP_SAVE'},
    )
    collection_path: StringProperty(
        name='Setup Collection',
        description='Optional exact pending collection used by context-menu actions',
        default='',
        options={'SKIP_SAVE'},
    )
    row_type: StringProperty(
        name='Setup Row Type',
        description='Optional exact setup row type used by context-menu actions',
        default='',
        options={'SKIP_SAVE'},
    )

    def execute(self, context):
        scene = context.scene
        original = [_fbp_pending_snapshot(item) for item in scene.fbp_pending_planes]
        requested_type = str(getattr(self, 'row_type', '') or '').upper()
        if requested_type in {'LAYER', 'GROUP'}:
            _pending_index = int(getattr(self, 'pending_index', -1))
            collection_path = str(getattr(self, 'collection_path', '') or '')
            row_type = requested_type
        else:
            _pending_index, collection_path, row_type = _fbp_active_pending_index_and_collection(scene)
        try:
            if row_type == 'GROUP':
                merged, name = _fbp_merge_pending_collection_to_sequence(context, collection_path)
                if not merged:
                    self.report({'WARNING'}, 'Select a leaf collection containing at least two single-image layers from the same folder')
                    return {'CANCELLED'}
                self.report({'INFO'}, f"Merged {merged} still planes into animated layer '{name}'")
                return {'FINISHED'}

            if row_type == 'LAYER':
                created, path = _fbp_split_pending_sequence_to_collection(context, _pending_index)
                if not created:
                    self.report({'WARNING'}, 'Select an animated image sequence with at least two frames')
                    return {'CANCELLED'}
                self.report({'INFO'}, f"Split sequence into collection '{path}' with {created} planes")
                return {'FINISHED'}
            return {'CANCELLED'}
        except FBP_DATA_IO_ERRORS as exc:
            try:
                _fbp_restore_pending_snapshots(scene, original)
                _fbp_refresh_pending_tree(context)
            except FBP_DATA_IO_ERRORS as restore_exc:
                fbp_warn('Could not restore Multiplane Setup after failed Split / Merge', restore_exc)
            fbp_warn('Split / Merge failed safely', exc)
            self.report({'ERROR'}, 'Split / Merge failed; the previous setup was restored')
            return {'CANCELLED'}


class FBP_OT_ReversePendingSelectedOrder(Operator):
    bl_idname = 'fbp.reverse_pending_selected_order'
    bl_label = 'Reverse Selected Layer Order'
    bl_description = 'Reverse checked setup layers independently inside each collection while every unselected row remains in its current slot'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        changed = _fbp_reverse_pending_selected_order(context)
        if not changed:
            self.report({'WARNING'}, 'Check at least two setup layers in the same collection')
            return {'CANCELLED'}
        self.report({'INFO'}, f"Reversed selected order in {changed} collection(s)")
        return {'FINISHED'}


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

        entries = fbp_collect_mixed_folder_entries(
            base,
            separate_sequences=False,
            reverse_sequences=False,
        )
        sc.fbp_pending_planes.clear()

        color_map = {}
        folder_content_cache = {}
        for name, directory, files, _kind in entries:
            item = sc.fbp_pending_planes.add()
            item.name = name
            item.directory = directory
            item.files_str = '|'.join(files)
            rel_folder = os.path.relpath(directory, base) if directory else "."
            # An image-only folder is a layer source, not a Blender Collection.
            # Only folders that contain child folders create a setup collection.
            if rel_folder not in {".", ""} and fbp_folder_direct_dirs(
                directory,
                content_cache=folder_content_cache,
            ):
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


def _fbp_pending_sibling_indices(scene, index):
    """Return source indices sharing the same direct setup collection."""
    pending = getattr(scene, 'fbp_pending_planes', ())
    if not (0 <= int(index) < len(pending)):
        return ()
    collection_name = str(getattr(pending[int(index)], 'collection_name', '') or '').strip()
    return tuple(
        item_index
        for item_index, item in enumerate(pending)
        if str(getattr(item, 'collection_name', '') or '').strip() == collection_name
    )


def _fbp_move_pending_plane_once(context, index, direction):
    """Move one pending layer among siblings without changing collection."""
    scene = context.scene
    index = int(index)
    siblings = _fbp_pending_sibling_indices(scene, index)
    try:
        position = siblings.index(index)
    except ValueError:
        return -1
    step = -1 if str(direction).upper() == 'UP' else 1
    target_position = position + step
    if not (0 <= target_position < len(siblings)):
        return -1
    target_index = int(siblings[target_position])
    try:
        scene.fbp_pending_planes.move(index, target_index)
    except FBP_DATA_IO_ERRORS:
        return -1
    _fbp_select_pending_index(context, target_index)
    return target_index


class FBP_OT_DragPendingPlane(Operator):
    bl_idname = 'fbp.drag_pending_plane'
    bl_label = 'Drag Setup Layer'
    bl_description = 'Click and drag vertically to reorder this setup layer inside its current collection'
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL', 'BLOCKING'}

    index: IntProperty(
        name='Index',
        description='Source index of the pending Multiplane Setup layer to reorder',
        default=-1,
        options={'SKIP_SAVE'},
    )

    def _redraw(self, context):
        try:
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
        except FBP_DATA_ERRORS:
            try:
                context.area.tag_redraw()
            except FBP_DATA_ERRORS:
                pass

    def _restore_cursor(self, context):
        try:
            context.window.cursor_modal_restore()
        except FBP_DATA_ERRORS:
            pass

    def _move_once(self, context, direction):
        new_index = _fbp_move_pending_plane_once(context, self._index, direction)
        if new_index < 0:
            return False
        self._index = new_index
        return True

    def invoke(self, context, event):
        siblings = _fbp_pending_sibling_indices(context.scene, self.index)
        if len(siblings) < 2 or int(self.index) not in siblings:
            return {'CANCELLED'}
        self._index = int(self.index)
        self._anchor_y = int(getattr(event, 'mouse_y', 0) or 0)
        self._history = []
        # A direct PRESS/CLICK_DRAG invocation can finish on the matching
        # LEFTMOUSE release. Standard Python panel buttons are commonly invoked
        # only after their activation click has already been released, so that
        # path retains the safe click-move-click fallback.
        self._finish_on_release = str(getattr(event, 'value', '') or '') in {
            'PRESS', 'CLICK_DRAG',
        }
        self._saw_drag_motion = False
        try:
            ui_scale = float(context.preferences.system.ui_scale)
        except FBP_DATA_ERRORS:
            ui_scale = 1.0
        self._threshold = max(10, int(round(16.0 * ui_scale)))
        _fbp_select_pending_index(context, self._index)
        context.window_manager.modal_handler_add(self)
        try:
            context.window.cursor_modal_set('SCROLL_Y')
        except FBP_DATA_ERRORS:
            pass
        self._redraw(context)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            self._saw_drag_motion = True
            mouse_y = int(getattr(event, 'mouse_y', self._anchor_y) or self._anchor_y)
            delta = mouse_y - self._anchor_y
            while abs(delta) >= self._threshold:
                direction = 'UP' if delta > 0 else 'DOWN'
                if not self._move_once(context, direction):
                    self._anchor_y = mouse_y
                    break
                self._history.append(direction)
                self._anchor_y += self._threshold if delta > 0 else -self._threshold
                delta = mouse_y - self._anchor_y
            self._redraw(context)
            return {'RUNNING_MODAL'}

        if event.type in {'ESC', 'RIGHTMOUSE'}:
            inverse = {'UP': 'DOWN', 'DOWN': 'UP'}
            for direction in reversed(getattr(self, '_history', ())):
                self._move_once(context, inverse[direction])
            self._restore_cursor(context)
            self._redraw(context)
            return {'CANCELLED'}

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            if self._finish_on_release or self._saw_drag_motion:
                self._restore_cursor(context)
                self._redraw(context)
                return {'FINISHED'}
            return {'RUNNING_MODAL'}

        if event.type == 'WINDOW_DEACTIVATE':
            self._restore_cursor(context)
            return {'FINISHED'}

        return {'RUNNING_MODAL'}

class FBP_OT_EditPendingPlane(Operator):
    bl_idname      = "fbp.edit_pending_plane"
    bl_label       = "Choose Images"
    bl_description = "Open file manager to assign images to this layer"

    index:     IntProperty(description="Zero-based index of the frame, drawing, layer or setup entry targeted by this action.")
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
        if not self.files:
            return {'CANCELLED'}
        sc = context.scene
        sc.fbp_last_directory = self.directory
        if 0 <= self.index < len(sc.fbp_pending_planes):
            item = sc.fbp_pending_planes[self.index]
            item.directory = self.directory
            sorted_files = fbp_order_sequence_files(
                [f.name for f in self.files],
                reverse=False,
            )
            item.files_str = "|".join(sorted_files)
            # Manual replacement invalidates every external-source contract.
            # A new image must not inherit PSD/Procreate masks, clipping, opacity
            # or blend data, nor stale Toon Boom exposure metadata.
            _fbp_clear_pending_source_metadata(item)
            if len(sorted_files) == 1:
                item.name = clean_layer_name_from_path(sorted_files[0])
            else:
                folder_name = clean_layer_name_from_path(os.path.basename(os.path.normpath(self.directory)))
                if folder_name:
                    item.name = folder_name
        _fbp_refresh_pending_tree(context)
        return {'FINISHED'}

class FBP_OT_MovePendingPlane(Operator):
    bl_idname      = "fbp.move_pending_plane"
    bl_label       = "Move Layer"
    bl_description = "Move this setup layer up or down inside its current collection"
    bl_options = {'REGISTER', 'UNDO'}

    direction: StringProperty(description="Requested movement direction: UP or DOWN.")
    index: IntProperty(
        name='Index',
        description='Explicit pending setup layer index; the active layer is used when omitted',
        default=-1,
        options={'SKIP_SAVE'},
    )

    def execute(self, context):
        sc = context.scene
        idx = int(self.index)
        if not (0 <= idx < len(sc.fbp_pending_planes)):
            idx, _collection_name, row_type = _fbp_active_pending_index_and_collection(sc)
            if row_type != 'LAYER':
                return {'CANCELLED'}
        return {'FINISHED'} if _fbp_move_pending_plane_once(context, idx, self.direction) >= 0 else {'CANCELLED'}

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
        _fbp_clear_layered_import_report(context.scene)
        _fbp_refresh_pending_tree(context)
        return {'FINISHED'}

def _fbp_reverse_pending_sequences(context, indices=None):
    """Reverse stored file order for selected pending animated sequences."""
    scene = context.scene
    targets = None if indices is None else {int(index) for index in indices}
    changed = 0
    for index, item in enumerate(scene.fbp_pending_planes):
        if targets is not None and index not in targets:
            continue
        files = [name for name in str(getattr(item, "files_str", "") or "").split("|") if name]
        if len(files) <= 1:
            continue
        files.reverse()
        item.files_str = "|".join(files)
        for attr_name in ('source_frame_numbers_str', 'source_durations_str'):
            values = [
                value for value in str(getattr(item, attr_name, '') or '').split('|')
                if value
            ]
            if len(values) == len(files):
                values.reverse()
                setattr(item, attr_name, '|'.join(values))
        changed += 1
    if changed:
        _fbp_refresh_pending_tree(context)
    return changed


class FBP_OT_ReversePendingSequence(Operator):
    bl_idname = "fbp.reverse_pending_sequence"
    bl_label = "Reverse Sequence"
    bl_description = "Reverse this pending image sequence without renaming or modifying its source files"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(
        name="Setup Layer",
        description="Pending Multiplane Setup sequence to reverse",
        default=-1,
        options={'SKIP_SAVE'},
    )

    def execute(self, context):
        if not _fbp_reverse_pending_sequences(context, {self.index}):
            self.report({'INFO'}, "This setup row does not contain an image sequence")
            return {'CANCELLED'}
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
        rows = fbp_scan_project_layers_for_setup(
            base,
            separate_sequences=False,
            reverse_sequences=False,
        )
        sc.fbp_pending_planes.clear()
        color_map = {}
        for name, collection_name, directory, files, follow_collection_color in rows:
            item = sc.fbp_pending_planes.add()
            item.name = name
            item.collection_name = collection_name
            item.directory = directory
            item.files_str = "|".join(files)
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

    collection_name: StringProperty(description="Name of the Blender or pending setup collection targeted by this action.", name="Collection", default="New Collection")

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

        folder_content_cache = {}
        top_entries = fbp_child_entries(
            base,
            separate_sequences=False,
            reverse_sequences=False,
            content_cache=folder_content_cache,
        )
        collection_color_state = {'next': 0}
        for kind, name, full in top_entries:
            before_count = len(generated)
            if kind == 'DIR':
                generated.extend(fbp_build_project_folder(
                    context, full, root_coll, cursor_loc, depth_counter,
                    color_seed=0, depth=0, color_state=collection_color_state,
                    separate_sequences=False,
                    reverse_sequences=False,
                    content_cache=folder_content_cache,
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
        report = _fbp_store_generation_report(context, mode="Project", generated_rigs=generated)
        _fbp_finish_generation_ui(context, report)
        self.report({'INFO'}, f"Auto Build Project: {len(generated)} layer(s) created")
        _fbp_note_successful_import(context, multiplane=True)
        return {'FINISHED'}

class FBP_OT_GenerateMultiplane(Operator):
    bl_idname      = "fbp.generate_multiplane"
    bl_label       = "Generate Multiplane"
    bl_description = "Generate the full plane system in 3D space"
    bl_options     = {'REGISTER', 'UNDO'}

    synchronous: BoolProperty(
        name="Synchronous Generation",
        description="Internal regression option that skips the UI deferral timer",
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

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
        if self.synchronous:
            return self._run_generation(context)
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
        rollback_snapshot = _fbp_multiplane_runtime_snapshot(context)
        owns_fast_import = not fbp_fast_import_is_active()
        if owns_fast_import:
            fbp_begin_fast_import(context)
        try:
            try:
                result = self._execute_impl(context)
            except Exception as exc:
                fbp_warn("Unexpected Multiplane generation failure", exc)
                _fbp_rollback_unexpected_multiplane_build(context, rollback_snapshot)
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
            else:
                _fbp_note_successful_import(context, multiplane=True)
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

        previous_camera = getattr(sc, "camera", None)
        previous_cursor = sc.cursor.location.copy()
        previous_pivot = getattr(sc.tool_settings, "transform_pivot_point", 'MEDIAN_POINT')
        created_camera = None

        source_path = bpy.path.abspath(sc.fbp_parent_import_path) if getattr(sc, "fbp_parent_import_path", "") else ""
        coll_base_name = clean_layer_name_from_path(source_path) if source_path else "Multi Plane"
        target_name = FBP_PROJECT_COLLECTION_PREFIX + coll_base_name
        target_preexisting = any(child.name == target_name for child in sc.collection.children)
        collections_before = {
            coll.as_pointer() for coll in bpy.data.collections
            if hasattr(coll, "as_pointer")
        }
        target_collection = get_or_create_child_collection(sc.collection, target_name)
        set_collection_color_tag(target_collection, 'NONE')

        if sc.fbp_gen_camera:
            if fbp_scene_orientation_is_horizontal(sc):
                bpy.ops.object.camera_add(location=cam_loc, rotation=(0, 0, 0))
            else:
                bpy.ops.object.camera_add(
                    location=cam_loc, rotation=(math.radians(90), 0, 0))
            sc.camera = context.active_object
            created_camera = sc.camera
            try:
                created_camera['fbp_generated_multiplane_camera'] = True
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
                pass
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
            f_list = [f for f in p_item.files_str.split("|") if f]
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

            source_durations = []
            for value in str(getattr(p_item, 'source_durations_str', '') or '').split('|'):
                if not value:
                    continue
                try:
                    source_durations.append(max(1, int(value)))
                except (TypeError, ValueError):
                    source_durations = []
                    break
            if len(source_durations) != len(f_list):
                source_durations = []
            source_frame_numbers = []
            for value in str(getattr(p_item, 'source_frame_numbers_str', '') or '').split('|'):
                if not value:
                    continue
                try:
                    source_frame_numbers.append(int(value))
                except (TypeError, ValueError):
                    source_frame_numbers = []
                    break
            if len(source_frame_numbers) != len(f_list):
                source_frame_numbers = []

            try:
                rig = build_fbp_rig(
                    context, p_item.name, p_item.directory, f_list, rig_loc,
                    p_item.fbp_color_tag,
                    target_collection=layer_collection,
                    color_variant_index=variant_index,
                    follow_collection_color=follows_collection,
                    item_durations=source_durations or None,
                    source_frame_numbers=source_frame_numbers or None,
                    source_preset=str(getattr(p_item, 'source_preset', '') or ''),
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

            if bool(getattr(p_item, "source_from_layered", False)):
                source_opacity = max(0.0, min(1.0, float(getattr(p_item, "source_layer_opacity", 1.0))))
                source_visible = bool(getattr(p_item, "source_layer_visible", True))
                try:
                    rig["fbp_layered_source_document"] = str(getattr(p_item, "source_document", "") or "")
                    rig["fbp_layered_source_layer_path"] = str(getattr(p_item, "source_layer_path", "") or "")
                    rig["fbp_layered_source_kind"] = str(getattr(p_item, "source_layer_kind", "") or "")
                    rig["fbp_layered_source_blend_mode"] = str(getattr(p_item, "source_blend_mode", "NORMAL") or "NORMAL")
                    rig["fbp_layered_source_cache_key"] = str(getattr(p_item, "source_cache_key", "") or "")
                    rig["fbp_layered_flattened_group"] = bool(getattr(p_item, "source_flattened_group", False))
                    rig["fbp_layered_source_warnings"] = str(getattr(p_item, "source_warnings", "") or "")
                    rig["fbp_layered_source_opacity"] = source_opacity
                except FBP_DATA_ERRORS:
                    pass
                try:
                    rig.fbp_opacity = source_opacity
                except FBP_DATA_ERRORS:
                    pass
                try:
                    rig.fbp_is_visible = source_visible
                    update_rig_visibility(rig, context=context)
                except FBP_DATA_ERRORS:
                    pass

                source_blend_mode = str(getattr(p_item, "source_blend_mode", "NORMAL") or "NORMAL").upper()
                blender_blend_mode = fbp_layered_blend_mode_for_blender(source_blend_mode)
                source_mask_file = str(getattr(p_item, "source_mask_file", "") or "")
                source_is_clipping = bool(getattr(p_item, "source_is_clipping", False))
                source_blend_supported = bool(getattr(p_item, "source_blend_supported", False))
                try:
                    rig["fbp_layered_source_is_clipping"] = source_is_clipping
                    rig["fbp_layered_source_mask_file"] = source_mask_file
                    rig["fbp_layered_source_blend_supported"] = source_blend_supported
                except FBP_DATA_ERRORS:
                    pass
                if source_mask_file and os.path.isfile(source_mask_file):
                    try:
                        rig.fbp_imported_mask_path = source_mask_file
                        fbp_add_effect(
                            rig, FBP_EFFECT_IMPORTED_MASK,
                            inherit_active_group=False, sync_items=False,
                        )
                        fbp_update_shader_effect(
                            rig, FBP_EFFECT_IMPORTED_MASK,
                            property_names={"fbp_imported_mask_path"},
                        )
                    except FBP_DATA_ERRORS:
                        pass
                if source_is_clipping:
                    try:
                        # Layered imports are exported on one common canvas, so
                        # normalized UV clipping preserves the source document.
                        rig.fbp_clipping_mask_use_source_transform = False
                        rig.fbp_clipping_mask_use_camera_projection = False
                        rig["fbp_clipping_projection_version"] = 3
                        fbp_add_effect(
                            rig, FBP_EFFECT_CLIPPING_MASK,
                            inherit_active_group=False, sync_items=False,
                        )
                    except FBP_DATA_ERRORS:
                        pass
                if source_blend_supported and blender_blend_mode not in {"NORMAL", "PASS_THROUGH"}:
                    try:
                        rig.fbp_layer_blend_mode = blender_blend_mode
                        fbp_add_effect(
                            rig, FBP_EFFECT_LAYER_BLEND,
                            inherit_active_group=False, sync_items=False,
                        )
                        fbp_update_shader_effect(
                            rig, FBP_EFFECT_LAYER_BLEND,
                            property_names={"fbp_layer_blend_mode"},
                        )
                    except FBP_DATA_ERRORS:
                        pass

            if sc.fbp_auto_scale and cam and not fbp_fast_import_is_active():
                context.view_layer.update()
                context.evaluated_depsgraph_get().update()
                apply_fit_to_camera(context, rig, cam)

            if not fbp_fast_import_is_active():
                rig.select_set(True)
            generated_rigs.append(rig)
            last_rig = rig

        if generated_rigs:
            try:
                fbp_sync_clipping_masks(context)
            except FBP_DATA_ERRORS:
                pass

        if not generated_rigs:
            # A failed Multiplane build must not leave a camera, cursor/pivot
            # mutation, or empty collections behind.  This is especially
            # important when every pending layer points at missing/corrupt media.
            try:
                sc.camera = previous_camera
            except FBP_DATA_ERRORS:
                pass
            try:
                sc.cursor.location = previous_cursor
                sc.tool_settings.transform_pivot_point = previous_pivot
            except FBP_DATA_ERRORS:
                pass
            if created_camera:
                try:
                    camera_data = getattr(created_camera, "data", None)
                    if bpy.data.objects.get(created_camera.name) == created_camera:
                        bpy.data.objects.remove(created_camera, do_unlink=True)
                    if camera_data and getattr(camera_data, "users", 0) == 0:
                        bpy.data.cameras.remove(camera_data)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
                    pass

            # Remove only collections created by this failed operation and only
            # while they are empty.  Pre-existing project collections are never
            # touched.
            for collection in reversed(list(bpy.data.collections)):
                try:
                    pointer = collection.as_pointer()
                    created_here = pointer not in collections_before
                    is_empty = not collection.objects and not collection.children
                    if created_here and is_empty:
                        bpy.data.collections.remove(collection)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
                    continue
            if not target_preexisting:
                try:
                    target = bpy.data.collections.get(target_name)
                    if target and not target.objects and not target.children:
                        bpy.data.collections.remove(target)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
                    pass

            report = _fbp_store_generation_report(
                context,
                mode="Multiplane",
                generated_rigs=[],
                extra_issues=generation_issues,
                cancelled=True,
                message="No Multiplane layers could be generated.",
            )
            _fbp_finish_generation_ui(context, report)
            self.report({'ERROR'}, f"No layers generated; {len(generation_issues)} layer(s) failed")
            return {'CANCELLED'}

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
            else:
                _fbp_note_successful_import(context, multiplane=False)
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
            filenames = fbp_folder_direct_images(bpy.path.abspath(self.directory))
        filenames = [f for f in filenames if is_supported_media_file(f) and (is_supported_video_file(f) or not is_technical_map_file(f))]
        if not filenames:
            self.report({'WARNING'}, "SELECT AT LEAST ONE IMAGE or choose a folder containing supported media")
            return {'CANCELLED'}
        context.scene.fbp_last_directory = self.directory
        f_list = fbp_order_sequence_files(
            filenames,
            reverse=False,
        )
        video_files = [name for name in f_list if is_supported_video_file(name)]
        if video_files and len(f_list) != 1:
            self.report({'WARNING'}, "Import one video at a time; videos cannot be mixed with image sequences")
            return {'CANCELLED'}
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
        if fbp_layer_backend_type(rig) not in {'NATIVE_IMAGE', 'NATIVE_SEQUENCE', 'NATIVE_MOVIE'}:
            self.report({'WARNING'}, "Replace Sequence is available only for native image and movie planes")
            return {'CANCELLED'}

        sorted_files = fbp_order_sequence_files(
            [f.name for f in self.files],
            reverse=bool(getattr(rig, 'fbp_sequence_reversed', False)),
        )
        video_files = [name for name in sorted_files if is_supported_video_file(name)]
        if video_files and len(sorted_files) != 1:
            self.report({'WARNING'}, "Video planes support one source file. Import videos separately.")
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

            if fbp_replace_sequence_backend(rig, self.directory, sorted_files):
                return {'FINISHED'}
        except Exception as exc:
            fbp_warn("Could not replace image sequence backend", exc)

        if created_plane:
            try:
                rig.fbp_plane_target = original_plane
            except FBP_DATA_IO_ERRORS:
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
        description="Minimum digit count used for generated frame numbers. Existing larger numbers are preserved, while shorter values receive leading zeroes.",
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
        value = _FBP_SAFE_SEQUENCE_PREFIX_RE.sub("_", value).strip("._- ")
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
                except FBP_DATA_IO_ERRORS:
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
                except FBP_DATA_IO_ERRORS:
                    pass
            for tmp, src in reversed(moved_to_temp):
                try:
                    if os.path.exists(tmp) and not os.path.exists(src):
                        os.rename(tmp, src)
                except FBP_DATA_IO_ERRORS:
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
        if status == "SUCCESS":
            _fbp_clear_generation_report(context)
            return {'CANCELLED'}
        width = 580
        title = {
            "WARNING": "Import Completed with Warnings",
            "CANCELLED": "Generation Cancelled",
        }.get(status, "Frame by Plane Generation Report")
        return context.window_manager.invoke_props_dialog(
            self,
            width=width,
            title=title,
            confirm_text="Close",
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

def _fbp_execute_single_plane_import(operator, context, directory, filenames):
    """Build one FBP rig from already resolved media filenames."""
    directory = bpy.path.abspath(str(directory or ""))
    filenames = [
        str(name) for name in (filenames or ())
        if name and is_supported_media_file(name)
        and (is_supported_video_file(name) or not is_technical_map_file(name))
    ]
    if not directory or not os.path.isdir(directory) or not filenames:
        operator.report({'WARNING'}, "SELECT AT LEAST ONE IMAGE or choose a folder containing supported media")
        return {'CANCELLED'}

    context.scene.fbp_last_directory = directory
    sorted_files = fbp_order_sequence_files(filenames, reverse=False)
    video_files = [name for name in sorted_files if is_supported_video_file(name)]
    if video_files and len(sorted_files) != 1:
        operator.report({'WARNING'}, "Import one video at a time; videos cannot be mixed with image sequences")
        return {'CANCELLED'}

    if len(sorted_files) == 1:
        rig_name = clean_layer_name_from_path(sorted_files[0])
    else:
        rig_name = (
            clean_layer_name_from_path(os.path.basename(os.path.normpath(directory)))
            or clean_layer_name_from_path(sorted_files[0])
            or "Sequence_Rig"
        )

    target_collection = context.collection if context.collection else context.scene.collection
    try:
        rig = build_fbp_rig(
            context,
            rig_name,
            directory,
            sorted_files,
            context.scene.cursor.location.copy(),
            target_collection=target_collection,
        )
    except Exception as exc:
        issue = _fbp_build_issue(
            rig_name,
            directory,
            sorted_files,
            f"Could not generate this layer: {exc}",
        )
        _fbp_store_generation_report(
            context,
            mode="Single Plane",
            generated_rigs=[],
            cancelled=True,
            message="Single plane generation failed.",
            extra_issues=[issue],
        )
        _fbp_finish_generation_ui(context)
        operator.report({'ERROR'}, f"Single plane import failed: {exc}")
        return {'CANCELLED'}

    bpy.ops.object.select_all(action='DESELECT')
    if object_in_view_layer(rig, context):
        rig.select_set(True)
        context.view_layer.objects.active = rig
    set_viewport_object_color(context)
    if len(sorted_files) > 1:
        operator.report({'INFO'}, f"Imported {len(sorted_files)} images as one animated plane")
    report = _fbp_store_generation_report(context, mode="Single Plane", generated_rigs=[rig])
    _fbp_finish_generation_ui(context, report)
    _fbp_note_successful_import(context, multiplane=False)
    return {'FINISHED'}


class FBP_OT_ImportSingleImage(Operator):
    bl_idname = "fbp.import_single_image"
    bl_label = "Single Plane"
    bl_description = "Create one Frame by Plane layer from one image/video, or one animated plane from multiple selected images"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(description="Selected media file path returned by Blender's file browser.", subtype='FILE_PATH')
    directory: StringProperty(description="Folder currently selected in Blender's file browser.", subtype='DIR_PATH')
    files: CollectionProperty(description="Files selected in Blender's file browser for this import or replacement action.", type=bpy.types.OperatorFileListElement)

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
            filenames = fbp_folder_direct_images(bpy.path.abspath(self.directory))
        return _fbp_execute_single_plane_import(self, context, self.directory, filenames)

class FBP_OT_ImportFolderMultiplane(Operator):
    bl_idname = "fbp.import_folder_multiplane"
    bl_label = "Import Folder"
    bl_description = (
        "Choose a folder, or read a copied folder path, then preview and automatically import it "
        "as one Single Plane or as a Multiplane according to its detected contents"
    )
    bl_options = {'REGISTER', 'UNDO'}

    animation: BoolProperty(
        name="Group Numbered Image Sequences",
        description=(
            "Group matching numbered images into animated planes. Videos remain video layers; "
            "disable this option to use only the first image of each detected image sequence"
        ),
        default=True,
        update=_fbp_reset_folder_import_confirmations,
    )
    filter_folder: BoolProperty(
        default=True,
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    use_last_folder: BoolProperty(
        name="Use Last Import Folder",
        description="Reuse the most recent valid Frame By Plane import folder without opening the file browser",
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    preflight_ready: BoolProperty(
        description="Internal state indicating that the chosen folder has been scanned and is ready for confirmation",
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    allow_very_large_import: BoolProperty(
        name="Import This Very Large Folder",
        description=(
            "Explicitly confirm generation of a very large number of layers or source files. "
            "Large imports can take time and consume substantial memory"
        ),
        default=False,
        options={'SKIP_SAVE'},
    )
    confirm_single_root_only: BoolProperty(
        name="Import Only the Root-Level Source",
        description=(
            "Confirm that only the single logical source stored directly in the selected folder "
            "will be imported, while nested and additional detected layers are intentionally ignored"
        ),
        default=False,
        options={'SKIP_SAVE'},
    )
    detected_layers: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_files: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_collections: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_sequences: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_stills: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_videos: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_direct_layers: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_preview: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})
    detected_snapshot_token: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})
    detected_animation_state: BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})
    detected_base_path: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})
    directory: StringProperty(
        description="Folder selected in Blender's file browser",
        subtype='DIR_PATH',
        options={'SKIP_SAVE'},
    )
    from_clipboard: BoolProperty(
        name="Read Folder Path from Clipboard",
        description=(
            "Read a folder path copied as text from Explorer, Finder or another file manager. "
            "On Windows use Copy as path"
        ),
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    synchronous_generation: BoolProperty(
        name="Synchronous Generation",
        description="Internal regression option that completes Multiplane generation before returning",
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    import_mode: EnumProperty(
        name="Import As",
        description="Automatically detect the folder structure or force one import type",
        items=(
            ('AUTO', "Auto Detect", "One logical layer becomes one plane; multiple logical layers become a Multiplane"),
            ('SINGLE', "Single Plane", "Use the folder root only when it contains exactly one logical still, video or numbered image sequence"),
            ('MULTI', "Multiplane", "Create one layer for each detected still, sequence, video or nested folder source"),
        ),
        default='AUTO',
        options={'SKIP_SAVE'},
        update=_fbp_reset_folder_import_confirmations,
    )

    def _resolve_base(self, context):
        if self.from_clipboard:
            base = _fbp_resolve_selected_folder("", self.directory)
            if not base:
                base = _fbp_folder_path_from_clipboard(context)
            return base
        return _fbp_resolve_selected_folder("", self.directory)

    def _refresh_detection(self, base, *, consume=False):
        rows = _fbp_scan_folder_rows_cached(base, animation=self.animation, consume=consume)
        summary = _fbp_folder_rows_summary(rows)
        self.detected_layers = summary['layers']
        self.detected_files = summary['files']
        self.detected_collections = summary['collections']
        self.detected_sequences = summary['sequences']
        self.detected_stills = summary['stills']
        self.detected_videos = summary['videos']
        self.detected_preview = _fbp_folder_rows_preview_text(rows)
        self.detected_snapshot_token = _fbp_folder_rows_token(base, rows)
        self.detected_animation_state = bool(self.animation)
        self.detected_base_path = os.path.normcase(
            os.path.realpath(os.path.abspath(os.path.normpath(str(base or ""))))
        )

        self.detected_direct_layers = len(_fbp_folder_rows_direct(base, rows))
        return rows

    def _open_preflight(self, context, base):
        if not base or not os.path.isdir(base):
            self.report({'WARNING'}, "Choose a valid folder")
            return {'CANCELLED'}
        self.directory = base
        rows = self._refresh_detection(base, consume=False)
        if not rows:
            _fbp_discard_folder_scan_cache(base)
            self.report({'WARNING'}, "No supported images, sequences, or videos found")
            return {'CANCELLED'}
        self.preflight_ready = True
        self.allow_very_large_import = False
        self.confirm_single_root_only = False
        return context.window_manager.invoke_props_dialog(self, width=500)

    def invoke(self, context, event):
        base = ""
        if self.from_clipboard:
            base = _fbp_folder_path_from_clipboard(context)
            if not base:
                self.report({'WARNING'}, "Clipboard does not contain a valid folder path. Use Copy as path first")
                return {'CANCELLED'}
        elif self.use_last_folder:
            for raw in (context.scene.fbp_last_directory, context.scene.fbp_project_path):
                candidate = bpy.path.abspath(str(raw or ""))
                if candidate and os.path.isdir(candidate):
                    base = os.path.abspath(os.path.normpath(candidate))
                    break
            if not base:
                self.report({'WARNING'}, "No valid previous import folder is available")
                return {'CANCELLED'}

        if base:
            return self._open_preflight(context, base)

        path = context.scene.fbp_last_directory or context.scene.fbp_project_path
        if path and os.path.isdir(bpy.path.abspath(path)):
            self.directory = path
        self.preflight_ready = False
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def check(self, context):
        """Refresh the preflight only when its source-defining options change.

        Blender calls ``check`` for every edited dialog property. Revalidating
        thousands of directories and source files when the user merely ticks a
        confirmation checkbox caused avoidable stalls on large or networked
        projects. The exact snapshot is still revalidated in ``execute``.
        """
        if not self.preflight_ready:
            return False
        base = self._resolve_base(context)
        if not base or not os.path.isdir(base):
            return False
        normalized_base = os.path.normcase(
            os.path.realpath(os.path.abspath(os.path.normpath(base)))
        )
        source_options_changed = (
            bool(self.detected_animation_state) != bool(self.animation)
            or str(self.detected_base_path or "") != normalized_base
        )
        if not source_options_changed:
            return False

        previous = (
            self.detected_layers,
            self.detected_files,
            self.detected_collections,
            self.detected_sequences,
            self.detected_stills,
            self.detected_videos,
            self.detected_direct_layers,
            self.detected_preview,
            self.detected_snapshot_token,
        )
        self._refresh_detection(base, consume=False)
        current = (
            self.detected_layers,
            self.detected_files,
            self.detected_collections,
            self.detected_sequences,
            self.detected_stills,
            self.detected_videos,
            self.detected_direct_layers,
            self.detected_preview,
            self.detected_snapshot_token,
        )
        self.allow_very_large_import = False
        self.confirm_single_root_only = False
        return current != previous

    def draw(self, context):
        layout = self.layout
        base = self._resolve_base(context)
        layout.label(text="Folder Import", icon=fbp_icon("FILE_FOLDER"))

        if not self.preflight_ready:
            layout.label(text="Choose the source folder, then confirm the detected structure.", icon=fbp_icon("INFO"))
            layout.prop(self, "import_mode", expand=True)
            layout.prop(self, "animation")
            _fbp_draw_import_alpha_crop_options(layout, context.scene)
            return

        if base:
            layout.label(text=os.path.basename(os.path.normpath(base)) or base)

        summary = layout.box()
        summary.label(
            text=f"Detected: {self.detected_layers} layer(s) from {self.detected_files} media file(s)",
            icon=fbp_icon("FILE_IMAGE"),
        )
        detail = summary.row(align=False)
        detail.label(text=f"Still layers: {self.detected_stills}")
        detail.label(text=f"Sequences: {self.detected_sequences}")
        detail.label(text=f"Videos: {self.detected_videos}")
        summary.label(text=f"Collection paths: {self.detected_collections}", icon=fbp_icon("FILE_FOLDER"))

        if self.detected_preview:
            preview = layout.box()
            preview.label(text="Detected Layers", icon=fbp_icon("OUTLINER_COLLECTION"))
            for line in self.detected_preview.splitlines():
                preview.label(text=line)
            remaining = max(0, self.detected_layers - _FBP_FOLDER_PREVIEW_LIMIT)
            if remaining:
                preview.label(text=f"… and {remaining} more layer(s)", icon=fbp_icon("DOT"))

        resolved_mode = _fbp_resolved_folder_import_mode(self.import_mode, self.detected_layers)
        summary.label(
            text=("Result: Single Plane" if resolved_mode == 'SINGLE' else "Result: Multiplane"),
            icon=fbp_icon("IMAGE_DATA") if resolved_mode == 'SINGLE' else fbp_icon("OUTLINER_COLLECTION"),
        )

        layout.prop(self, "import_mode", expand=True)
        layout.prop(self, "animation")
        _fbp_draw_import_alpha_crop_options(layout, context.scene)

        if self.import_mode == 'SINGLE' and self.detected_layers > 1:
            single_box = layout.box()
            if self.detected_direct_layers == 1:
                ignored = max(0, self.detected_layers - 1)
                single_box.label(text="Single Plane will use the only root-level source.", icon=fbp_icon("INFO"))
                single_box.label(text=f"{ignored} nested or additional layer(s) will be ignored.")
                single_box.prop(self, "confirm_single_root_only")
            else:
                single_box.alert = True
                single_box.label(text="Single Plane is unavailable for this folder.", icon=fbp_icon("ERROR"))
                single_box.label(text="Choose Auto Detect/Multiplane, or use a folder with one root-level source.")

        warning, confirmation = _fbp_folder_import_size_flags(
            {'layers': self.detected_layers, 'files': self.detected_files}
        )
        if warning:
            box = layout.box()
            box.alert = True
            box.label(text="Large folder import", icon=fbp_icon("ERROR"))
            box.label(text="Generation may take time and create many Blender datablocks.")
            if confirmation:
                box.prop(self, "allow_very_large_import")

        layout.separator()
        layout.label(text="Review the detection above before generating the planes.", icon=fbp_icon("INFO"))
        layout.label(text="The source snapshot is checked again when you confirm the import.", icon=fbp_icon("LOCKED"))

    def cancel(self, context):
        base = self._resolve_base(context)
        if base:
            _fbp_discard_folder_scan_cache(base)

    def execute(self, context):
        base = self._resolve_base(context)
        if not base or not os.path.isdir(base):
            message = (
                "Clipboard does not contain a valid folder path. Use Copy as path first"
                if self.from_clipboard else "Choose a valid folder"
            )
            self.report({'WARNING'}, message)
            return {'CANCELLED'}

        # The directory picker cannot display a reliable recursive summary while
        # browsing. After the folder is chosen, pause once for a dedicated,
        # consistent confirmation dialog instead of importing immediately.
        if not self.preflight_ready:
            return self._open_preflight(context, base)

        if (
            self.import_mode == 'SINGLE'
            and self.detected_layers > 1
            and self.detected_direct_layers == 1
            and not self.confirm_single_root_only
        ):
            _fbp_discard_folder_scan_cache(base)
            self.report({'ERROR'}, "Confirm that only the root-level source should be imported")
            return {'CANCELLED'}

        confirmed_snapshot_token = self.detected_snapshot_token

        # Consume one exact scan snapshot and use the same rows for the final
        # confirmation and generation. This avoids a race where the directory
        # changes between two scans and the warning no longer describes what is
        # actually imported.
        rows = self._refresh_detection(base, consume=True)
        if not rows:
            self.report({'WARNING'}, "No supported images, sequences, or videos found")
            return {'CANCELLED'}
        if confirmed_snapshot_token and self.detected_snapshot_token != confirmed_snapshot_token:
            self.allow_very_large_import = False
            self.confirm_single_root_only = False
            self.report({'ERROR'}, "Folder sources changed after preview; review the import again")
            return {'CANCELLED'}
        if (
            self.import_mode == 'SINGLE'
            and self.detected_layers > 1
            and self.detected_direct_layers == 1
            and not self.confirm_single_root_only
        ):
            self.report({'ERROR'}, "Folder sources changed; confirm the root-only Single Plane import again")
            return {'CANCELLED'}

        _warning, confirmation = _fbp_folder_import_size_flags(
            {'layers': self.detected_layers, 'files': self.detected_files}
        )
        if confirmation and not self.allow_very_large_import:
            self.report({'ERROR'}, "Confirm the very large folder import before continuing")
            return {'CANCELLED'}

        return _fbp_execute_detected_folder_import(
            self,
            context,
            base,
            rows,
            import_mode=self.import_mode,
            synchronous_generation=self.synchronous_generation,
        )


def _fbp_resolve_selected_folder(filepath, directory):
    """Return a valid absolute folder from Blender file-selector properties."""
    candidates = [directory, filepath]
    for raw in candidates:
        path = bpy.path.abspath(str(raw or "")).strip()
        if not path:
            continue
        path = os.path.abspath(os.path.normpath(path))
        if os.path.isdir(path):
            return path
        if os.path.isfile(path):
            return os.path.dirname(path)
    return ""


def _fbp_clipboard_text_paths(raw_text):
    """Yield normalized path candidates from copied text or file:// URIs."""
    raw_text = str(raw_text or "").replace("\x00", "").strip()
    if not raw_text:
        return []

    candidates = []
    # Copy-as-path commonly produces one quoted path per line when multiple
    # filesystem items are selected. Keep line boundaries instead of splitting
    # on spaces, which are valid inside paths.
    for raw_line in raw_text.splitlines() or [raw_text]:
        value = raw_line.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1].strip()
        if not value:
            continue

        if value.lower().startswith("file://"):
            parsed = urlparse(value)
            decoded = unquote(parsed.path or "")
            if parsed.netloc:
                decoded = f"//{parsed.netloc}{decoded}"
            # file:///C:/Folder becomes /C:/Folder after URL parsing.
            if os.name == 'nt' and len(decoded) >= 3 and decoded[0] == '/' and decoded[2] == ':':
                decoded = decoded[1:]
            value = decoded

        value = os.path.expandvars(os.path.expanduser(value))
        if value:
            candidates.append(os.path.abspath(os.path.normpath(value)))
    return candidates


def _fbp_folder_path_from_clipboard(context):
    """Return the first existing folder represented by Blender's text clipboard."""
    raw = getattr(context.window_manager, 'clipboard', '') or ''
    for path in _fbp_clipboard_text_paths(raw):
        if os.path.isdir(path):
            return path
        if os.path.isfile(path):
            return os.path.dirname(path)
    return ""


def _fbp_clone_folder_rows(rows):
    """Return mutable copies so callers cannot alter the runtime scan cache."""
    cloned = []
    for row in rows or ():
        if len(row) < 5:
            continue
        name, collection_name, directory, files, follow = row[:5]
        cloned.append((str(name), str(collection_name), str(directory), list(files or ()), bool(follow)))
    return cloned


def _fbp_folder_rows_token(base, rows):
    """Return a stable fingerprint for one reviewed folder snapshot.

    The token includes source identity and lightweight file metadata. This keeps
    a preview honest when a frame is replaced or edited in place without being
    renamed, even when the parent directory timestamp does not change.
    """
    digest = hashlib.sha256()
    raw_base = bpy.path.abspath(str(base or "")).strip()
    normalized_base = ""
    if raw_base:
        normalized_base = os.path.normcase(
            os.path.realpath(os.path.abspath(os.path.normpath(raw_base)))
        )
    digest.update(normalized_base.encode("utf-8", "surrogatepass"))
    digest.update(b"\0")

    for row in rows or ():
        if len(row) < 4 or not row[3]:
            continue
        name, collection_name, directory, files = row[:4]
        raw_directory = str(directory or "").strip()
        normalized_directory = ""
        if raw_directory:
            normalized_directory = os.path.normcase(
                os.path.realpath(os.path.abspath(os.path.normpath(raw_directory)))
            )

        for value in (str(name), str(collection_name), normalized_directory):
            digest.update(value.encode("utf-8", "surrogatepass"))
            digest.update(b"\0")

        for filename in files or ():
            raw_filename = str(filename or "")
            source_path = (
                raw_filename
                if os.path.isabs(raw_filename)
                else os.path.join(normalized_directory, raw_filename)
            )
            normalized_source = os.path.normcase(
                os.path.realpath(os.path.abspath(os.path.normpath(source_path)))
            )
            digest.update(normalized_source.encode("utf-8", "surrogatepass"))
            digest.update(b"\0")
            try:
                stat = os.stat(source_path)
                metadata = (
                    int(getattr(stat, 'st_size', 0)),
                    int(getattr(stat, 'st_mtime_ns', int(stat.st_mtime * 1_000_000_000))),
                    int(getattr(stat, 'st_ctime_ns', int(stat.st_ctime * 1_000_000_000))),
                    int(getattr(stat, 'st_dev', 0)),
                    int(getattr(stat, 'st_ino', 0)),
                )
                digest.update("|".join(str(value) for value in metadata).encode("ascii"))
            except (OSError, PermissionError, ValueError):
                digest.update(b"MISSING")
            digest.update(b"\0")

        if len(row) > 4:
            digest.update(b"1" if bool(row[4]) else b"0")
        digest.update(b"\n")
    return digest.hexdigest()


def _fbp_folder_rows_direct(base, rows):
    """Return root-level rows from the exact preflight snapshot."""
    raw_base = bpy.path.abspath(str(base or "")).strip()
    if not raw_base:
        return []
    base_key = os.path.normcase(os.path.realpath(os.path.abspath(os.path.normpath(raw_base))))
    direct = []
    for row in rows or ():
        if len(row) < 4 or not row[3]:
            continue
        raw_directory = str(row[2] or "").strip()
        if not raw_directory:
            continue
        directory = os.path.abspath(os.path.normpath(raw_directory))
        if os.path.normcase(os.path.realpath(directory)) == base_key:
            direct.append(row)
    return direct


def _fbp_folder_rows_summary(rows):
    """Return compact counts used by reports and confirmation UI."""
    valid = [row for row in (rows or ()) if len(row) >= 4 and row[3]]
    collections = {str(row[1]).strip() for row in valid if str(row[1]).strip()}
    sequences = 0
    stills = 0
    videos = 0
    for row in valid:
        files = list(row[3] or ())
        if any(is_supported_video_file(name) for name in files):
            videos += 1
        elif len(files) > 1:
            sequences += 1
        else:
            stills += 1
    return {
        'layers': len(valid),
        'files': sum(len(row[3]) for row in valid),
        'collections': len(collections),
        'sequences': sequences,
        'stills': stills,
        'videos': videos,
    }


def _fbp_folder_rows_preview_text(rows, limit=_FBP_FOLDER_PREVIEW_LIMIT):
    """Return a compact, filesystem-free preview for an operator dialog."""
    lines = []
    for row in rows or ():
        if len(row) < 4 or not row[3]:
            continue
        name, collection_name, _directory, files = row[:4]
        files = list(files or ())
        if any(is_supported_video_file(filename) for filename in files):
            kind = "Video"
        elif len(files) > 1:
            kind = f"Sequence · {len(files)} frames"
        else:
            kind = "Still"
        prefix = f"{collection_name} / " if str(collection_name or '').strip() else ""
        label = f"{prefix}{name}".replace("\n", " ").replace("\r", " ")
        if len(label) > 72:
            label = f"{label[:34]}…{label[-34:]}"
        lines.append(f"{label} — {kind}")
        if len(lines) >= max(1, int(limit or 1)):
            break
    return "\n".join(lines)


def _fbp_resolved_folder_import_mode(import_mode, layer_count):
    """Return the effective Single/Multiplane choice shown by preflight UI."""
    mode = str(import_mode or 'AUTO')
    if mode == 'AUTO':
        return 'SINGLE' if int(layer_count or 0) == 1 else 'MULTI'
    return 'SINGLE' if mode == 'SINGLE' else 'MULTI'


def _fbp_folder_import_size_flags(summary):
    """Return (warning, explicit_confirmation_required) for one scan summary."""
    layers = max(0, int((summary or {}).get('layers', 0) or 0))
    files = max(0, int((summary or {}).get('files', 0) or 0))
    warning = (
        layers >= _FBP_FOLDER_IMPORT_WARNING_LAYERS
        or files >= _FBP_FOLDER_IMPORT_WARNING_FILES
    )
    confirmation = (
        layers >= _FBP_FOLDER_IMPORT_CONFIRM_LAYERS
        or files >= _FBP_FOLDER_IMPORT_CONFIRM_FILES
    )
    return warning, confirmation


def _fbp_folder_scan_signature(base, rows, *, scanned_directories=None):
    """Capture state for every directory visited by the project scanner.

    Tracking only folders that produced layers misses a later media file added
    inside a previously empty nested directory. The optional collector supplied
    by the one-pass scanner closes that cache invalidation gap.
    """
    base = os.path.abspath(os.path.normpath(str(base or "")))
    directories = {base}
    base_key = os.path.normcase(os.path.realpath(base))

    for raw_directory in scanned_directories or ():
        current = os.path.abspath(os.path.normpath(str(raw_directory or "")))
        if current:
            directories.add(current)

    # Backward-compatible fallback for callers that do not provide the complete
    # scanner directory list. Include row directories and all ancestors.
    for row in rows or ():
        if len(row) < 3:
            continue
        current = os.path.abspath(os.path.normpath(str(row[2] or "")))
        while current:
            try:
                common = os.path.normcase(os.path.realpath(os.path.commonpath((base, current))))
            except (OSError, ValueError):
                break
            if common != base_key:
                break
            directories.add(current)
            if os.path.normcase(os.path.realpath(current)) == base_key:
                break
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent

    signature = []
    for directory in sorted(directories, key=lambda value: os.path.normcase(value)):
        normalized = os.path.normcase(os.path.realpath(directory))
        try:
            stat = os.stat(directory)
            metadata = (
                int(getattr(stat, 'st_mtime_ns', int(stat.st_mtime * 1_000_000_000))),
                int(getattr(stat, 'st_ctime_ns', int(stat.st_ctime * 1_000_000_000))),
                int(getattr(stat, 'st_size', 0)),
                1 if os.access(directory, os.R_OK) else 0,
            )
        except (OSError, PermissionError, ValueError):
            metadata = (-1, -1, -1, 0)
        signature.append((normalized, *metadata))
    return tuple(signature)


def _fbp_folder_scan_signature_is_current(signature):
    """Return False when any previously scanned directory changed."""
    if not signature:
        return False
    for item in signature:
        if len(item) != 5:
            return False
        directory, previous_mtime, previous_ctime, previous_size, previous_access = item
        try:
            stat = os.stat(directory)
            current = (
                int(getattr(stat, 'st_mtime_ns', int(stat.st_mtime * 1_000_000_000))),
                int(getattr(stat, 'st_ctime_ns', int(stat.st_ctime * 1_000_000_000))),
                int(getattr(stat, 'st_size', 0)),
                1 if os.access(directory, os.R_OK) else 0,
            )
        except (OSError, PermissionError, ValueError):
            return False
        if current != (
            int(previous_mtime),
            int(previous_ctime),
            int(previous_size),
            int(previous_access),
        ):
            return False
    return True


def _fbp_discard_folder_scan_cache(base=None):
    """Release cached folder rows after cancellation or an aborted import."""
    if not base:
        _FBP_FOLDER_SCAN_CACHE.clear()
        return
    raw_base = bpy.path.abspath(str(base or "")).strip()
    if not raw_base:
        return
    key_path = os.path.normcase(os.path.realpath(os.path.abspath(os.path.normpath(raw_base))))
    for key in tuple(_FBP_FOLDER_SCAN_CACHE):
        if key and key[0] == key_path:
            _FBP_FOLDER_SCAN_CACHE.pop(key, None)


def _fbp_scan_folder_rows_cached(base, *, animation=True, consume=False):
    """Scan one folder with a bounded, short-lived runtime-only cache."""
    raw_base = bpy.path.abspath(str(base or "")).strip()
    if not raw_base:
        return []
    base = os.path.abspath(os.path.normpath(raw_base))
    if not os.path.isdir(base):
        return []

    now = time.monotonic()
    key = (os.path.normcase(os.path.realpath(base)), bool(animation))
    entry = _FBP_FOLDER_SCAN_CACHE.get(key)
    entry_is_fresh = bool(
        entry
        and int(entry.get('schema', 0) or 0) == _FBP_FOLDER_SCAN_CACHE_SCHEMA
        and now - float(entry.get('time', 0.0)) <= _FBP_FOLDER_SCAN_CACHE_TTL
        and _fbp_folder_scan_signature_is_current(entry.get('signature', ()))
    )
    if entry_is_fresh:
        rows = _fbp_clone_folder_rows(entry.get('rows', ()))
        if consume:
            _FBP_FOLDER_SCAN_CACHE.pop(key, None)
        return rows
    if entry:
        _FBP_FOLDER_SCAN_CACHE.pop(key, None)

    scanned_directories = []
    rows = fbp_scan_project_layers_for_setup(
        base,
        separate_sequences=False,
        reverse_sequences=False,
        scanned_directories=scanned_directories,
    )
    if not animation:
        rows = [
            (name, coll, directory, files[:1], follow)
            for name, coll, directory, files, follow in rows
            if files
        ]

    _FBP_FOLDER_SCAN_CACHE[key] = {
        'schema': _FBP_FOLDER_SCAN_CACHE_SCHEMA,
        'time': now,
        'rows': _fbp_clone_folder_rows(rows),
        'signature': _fbp_folder_scan_signature(
            base,
            rows,
            scanned_directories=scanned_directories,
        ),
    }
    # Prune expired entries first, then cap the cache deterministically.
    for cache_key, cached in tuple(_FBP_FOLDER_SCAN_CACHE.items()):
        if now - float(cached.get('time', 0.0)) > _FBP_FOLDER_SCAN_CACHE_TTL:
            _FBP_FOLDER_SCAN_CACHE.pop(cache_key, None)
    if len(_FBP_FOLDER_SCAN_CACHE) > _FBP_FOLDER_SCAN_CACHE_MAX:
        oldest = sorted(
            _FBP_FOLDER_SCAN_CACHE.items(),
            key=lambda item: float(item[1].get('time', 0.0)),
        )
        for cache_key, _cached in oldest[:-_FBP_FOLDER_SCAN_CACHE_MAX]:
            _FBP_FOLDER_SCAN_CACHE.pop(cache_key, None)

    result = _fbp_clone_folder_rows(rows)
    if consume:
        _FBP_FOLDER_SCAN_CACHE.pop(key, None)
    return result


def _fbp_single_plane_source_from_rows(base, rows):
    """Resolve one safe Single Plane source without merging unrelated media."""
    valid = [row for row in (rows or ()) if len(row) >= 4 and row[3]]
    if len(valid) == 1:
        _name, _collection, directory, filenames = valid[0][:4]
        return str(directory), list(filenames or ()), ""

    direct_rows = _fbp_folder_rows_direct(base, valid)
    if len(direct_rows) != 1:
        return "", [], "Single Plane requires exactly one logical source in the selected folder root"
    _name, _collection, directory, filenames = direct_rows[0][:4]
    return str(directory), list(filenames or ()), ""


def _fbp_single_plane_source_from_paths(paths):
    """Resolve dropped paths only when they form one logical media source."""
    files = _fbp_drop_importable_files(paths)
    directories = {
        os.path.normcase(os.path.realpath(os.path.dirname(path))): os.path.dirname(path)
        for path in files
    }
    if len(directories) != 1:
        return "", [], "Single Plane requires media from one folder"
    directory = next(iter(directories.values()))
    grouped = fbp_group_direct_media_into_layers(
        [os.path.basename(path) for path in files],
        clean_layer_name_from_path(directory),
    )
    if len(grouped) != 1:
        return "", [], "Single Plane requires one still, one video, or one numbered image sequence"
    _layer_name, filenames, _is_sequence = grouped[0]
    return directory, list(filenames or ()), ""


def _fbp_execute_detected_folder_import(
    operator, context, base, rows, *, import_mode='AUTO', synchronous_generation=False
):
    """Import already detected folder rows through one shared safe decision path."""
    rows = [row for row in (rows or ()) if len(row) >= 4 and row[3]]
    summary = _fbp_folder_rows_summary(rows)
    if not rows:
        operator.report({'WARNING'}, "No supported images, sequences, or videos found")
        return {'CANCELLED'}

    context.scene.fbp_last_directory = base
    context.scene.fbp_parent_import_path = base
    resolved_mode = str(import_mode or 'AUTO')
    if resolved_mode == 'AUTO':
        resolved_mode = 'SINGLE' if len(rows) == 1 else 'MULTI'

    if resolved_mode == 'SINGLE':
        directory, filenames, error = _fbp_single_plane_source_from_rows(base, rows)
        if error:
            operator.report({'WARNING'}, error)
            return {'CANCELLED'}
        if not filenames:
            operator.report({'WARNING'}, "Single Plane requires supported media directly inside the selected folder")
            return {'CANCELLED'}
        result = _fbp_execute_single_plane_import(operator, context, directory, filenames)
        if result == {'FINISHED'}:
            operator.report(
                {'INFO'},
                f"Imported folder as one plane from {len(filenames)} media file(s)",
            )
        return result

    if _fbp_prepare_pending_rows(context, base, rows) <= 0:
        operator.report({'WARNING'}, "No Multiplane layers could be prepared")
        return {'CANCELLED'}
    operator.report(
        {'INFO'},
        f"Detected {summary['layers']} layer(s) from {summary['files']} media file(s); generating Multiplane",
    )
    if synchronous_generation:
        # The normal UI stays deferred so its progress popup can draw first. The
        # autonomous developer test needs a deterministic result before it counts
        # created layers, so it executes the same generator body synchronously.
        return bpy.ops.fbp.generate_multiplane(
            "EXEC_DEFAULT", False, synchronous=True
        )
    return bpy.ops.fbp.generate_multiplane()


def _fbp_resolve_dropped_paths(filepath, directory, files):
    """Resolve FileHandler properties into unique absolute filesystem paths."""
    base_directory = bpy.path.abspath(str(directory or ""))
    candidates = []

    for item in files or ():
        name = str(getattr(item, "name", "") or "")
        if not name:
            continue
        path = name if os.path.isabs(name) else os.path.join(base_directory, name)
        candidates.append(path)

    raw_filepath = bpy.path.abspath(str(filepath or ""))
    if raw_filepath:
        candidates.append(raw_filepath)

    resolved = []
    seen = set()
    for path in candidates:
        absolute = os.path.abspath(os.path.normpath(path))
        key = os.path.normcase(os.path.realpath(absolute))
        if key in seen or not os.path.exists(absolute):
            continue
        seen.add(key)
        resolved.append(absolute)
    return resolved


def _fbp_drop_importable_files(paths):
    """Return supported, non-technical media files from a drop payload."""
    result = []
    for path in paths or ():
        if not os.path.isfile(path):
            continue
        if not is_supported_media_file(path):
            continue
        if not is_supported_video_file(path) and is_technical_map_file(path):
            continue
        result.append(path)
    return result


def _fbp_drop_rows_from_files(paths):
    """Build Multiplane setup rows from exactly the media files that were dropped."""
    files = _fbp_drop_importable_files(paths)
    if not files:
        return "", []

    by_directory = {}
    directory_order = []
    for path in files:
        directory = os.path.dirname(path)
        key = os.path.normcase(directory)
        if key not in by_directory:
            by_directory[key] = [directory, []]
            directory_order.append(key)
        by_directory[key][1].append(os.path.basename(path))

    directories = [by_directory[key][0] for key in directory_order]
    try:
        common_root = os.path.commonpath(directories)
    except (ValueError, OSError):
        common_root = directories[0]

    multiple_directories = len(directories) > 1
    rows = []
    for key in directory_order:
        directory, filenames = by_directory[key]
        folder_name = clean_layer_name_from_path(directory)
        grouped = fbp_group_direct_media_into_layers(filenames, folder_name)

        collection_name = ""
        if multiple_directories:
            try:
                relative = os.path.relpath(directory, common_root)
            except (ValueError, OSError):
                relative = folder_name
            if relative not in {"", "."}:
                parts = [
                    clean_layer_name_from_path(part)
                    for part in relative.split(os.sep)
                    if part not in {"", ".", ".."}
                ]
                collection_name = " / ".join(part for part in parts if part)

        for layer_name, layer_files, _is_sequence in grouped:
            rows.append((
                layer_name,
                collection_name,
                directory,
                fbp_order_sequence_files(layer_files, reverse=False),
                bool(collection_name),
            ))
    return common_root, rows


def _fbp_prepare_pending_rows(context, base, rows):
    """Populate the existing Multiplane Setup using pre-resolved rows."""
    scene = context.scene
    _fbp_clear_layered_import_report(scene)
    scene.fbp_creation_mode = 'MULTI'
    scene.fbp_parent_import_path = base
    scene.fbp_project_path = base
    scene.fbp_last_directory = base
    scene.fbp_pending_planes.clear()

    color_map = {}
    for name, collection_name, directory, files, follow_collection_color in rows:
        if not files:
            continue
        item = scene.fbp_pending_planes.add()
        item.name = name
        item.collection_name = collection_name
        item.directory = directory
        item.files_str = "|".join(files)
        item.follow_collection_color = bool(follow_collection_color)
        color_key = (
            collection_name
            if item.follow_collection_color and collection_name
            else f"{os.path.normcase(os.path.abspath(directory or base))}::{name}"
        )
        item.fbp_color_tag = _fbp_color_tag_for_group(color_key, color_map)
    scene.fbp_pending_open_collections = ""
    return len(scene.fbp_pending_planes)


def _fbp_prepare_toon_boom_pending_rows(context, base, rows, *, preserve_exposure_gaps=True):
    """Populate Multiplane Setup from a Toon Boom Harmony image export."""
    scene = context.scene
    _fbp_clear_layered_import_report(scene)
    scene.fbp_creation_mode = 'MULTI'
    scene.fbp_parent_import_path = base
    scene.fbp_project_path = base
    scene.fbp_last_directory = base
    scene.fbp_pending_planes.clear()

    color_map = {}
    total_exposure_frames = 0
    preserved_hold_frames = 0
    timed_sequences = 0
    for name, collection_name, directory, files, follow_collection_color in rows:
        ordered_files = fbp_order_sequence_files(files, reverse=False)
        if not ordered_files:
            continue
        durations, frame_numbers = fbp_sequence_exposure_durations(
            ordered_files,
            clean_layer_name_from_path(directory),
            preserve_gaps=bool(preserve_exposure_gaps),
        )
        if len(frame_numbers) == len(ordered_files):
            timed_sequences += 1
        if len(durations) != len(ordered_files):
            durations = [1] * len(ordered_files)
        total_exposure_frames += sum(durations)
        preserved_hold_frames += sum(max(0, value - 1) for value in durations)

        item = scene.fbp_pending_planes.add()
        item.name = name
        item.collection_name = collection_name
        item.directory = directory
        item.files_str = '|'.join(ordered_files)
        item.follow_collection_color = bool(follow_collection_color)
        item.source_preset = 'TOON_BOOM_EXPORT'
        item.source_frame_numbers_str = '|'.join(str(value) for value in frame_numbers)
        item.source_durations_str = '|'.join(str(value) for value in durations)
        color_key = (
            collection_name
            if item.follow_collection_color and collection_name
            else f"{os.path.normcase(os.path.abspath(directory or base))}::{name}"
        )
        item.fbp_color_tag = _fbp_color_tag_for_group(color_key, color_map)

    scene.fbp_pending_open_collections = ''
    _fbp_refresh_pending_tree(context)
    return {
        'layers': len(scene.fbp_pending_planes),
        'timed_sequences': timed_sequences,
        'exposure_frames': total_exposure_frames,
        'hold_frames': preserved_hold_frames,
    }


class FBP_OT_ImportToonBoomExport(Operator):
    bl_idname = 'fbp.import_toon_boom_export'
    bl_label = 'Import Toon Boom Export'
    bl_description = (
        'Read a Toon Boom Harmony image export as collapsed Multiplane Setup collections, '
        'group numbered drawings into sequences and optionally preserve numbered exposure gaps'
    )
    bl_options = {'REGISTER', 'UNDO'}

    filter_folder: BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})
    directory: StringProperty(
        name='Export Folder',
        description='Root folder containing Toon Boom Harmony PNG/image sequences',
        subtype='DIR_PATH',
        options={'SKIP_SAVE'},
    )
    preflight_ready: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})
    preserve_exposure_gaps: BoolProperty(
        name='Preserve Numbered Exposure Gaps',
        description=(
            'Use gaps between drawing numbers as hold durations: for example Drawing_0001 and '
            'Drawing_0004 keep the first drawing visible for three timeline frames'
        ),
        default=True,
        options={'SKIP_SAVE'},
    )
    detected_layers: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_files: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_collections: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_sequences: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_exposure_frames: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_hold_frames: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_preview: StringProperty(default='', options={'HIDDEN', 'SKIP_SAVE'})
    detected_snapshot_token: StringProperty(default='', options={'HIDDEN', 'SKIP_SAVE'})
    detected_gap_state: BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})
    allow_very_large_import: BoolProperty(
        name='Prepare This Very Large Export',
        description='Confirm preparing a very large Toon Boom export in Multiplane Setup',
        default=False,
        options={'SKIP_SAVE'},
    )

    def _base(self):
        return _fbp_resolve_selected_folder('', self.directory)

    def _size_flags(self):
        warning, confirmation = _fbp_folder_import_size_flags({
            'layers': self.detected_layers,
            'files': self.detected_files,
        })
        if self.detected_exposure_frames >= _FBP_TOON_BOOM_WARNING_TIMELINE_FRAMES:
            warning = True
        if self.detected_exposure_frames >= _FBP_TOON_BOOM_CONFIRM_TIMELINE_FRAMES:
            confirmation = True
        return warning, confirmation

    def _refresh(self, base, *, consume=False):
        rows = _fbp_scan_folder_rows_cached(base, animation=True, consume=consume)
        summary = _fbp_folder_rows_summary(rows)
        exposure_frames = 0
        hold_frames = 0
        sequence_count = 0
        for _name, _collection, directory, files, _follow in rows:
            durations, frame_numbers = fbp_sequence_exposure_durations(
                files,
                clean_layer_name_from_path(directory),
                preserve_gaps=bool(self.preserve_exposure_gaps),
            )
            if len(frame_numbers) == len(files) and len(files) > 1:
                sequence_count += 1
            exposure_frames += sum(durations)
            hold_frames += sum(max(0, value - 1) for value in durations)
        self.detected_layers = summary['layers']
        self.detected_files = summary['files']
        self.detected_collections = summary['collections']
        self.detected_sequences = sequence_count
        self.detected_exposure_frames = exposure_frames
        self.detected_hold_frames = hold_frames
        self.detected_preview = _fbp_folder_rows_preview_text(rows)
        self.detected_snapshot_token = _fbp_folder_rows_token(base, rows)
        self.detected_gap_state = bool(self.preserve_exposure_gaps)
        return rows

    def _open_preflight(self, context, base):
        if not base or not os.path.isdir(base):
            self.report({'WARNING'}, 'Choose a valid Toon Boom export folder')
            return {'CANCELLED'}
        self.directory = base
        rows = self._refresh(base, consume=False)
        if not rows:
            _fbp_discard_folder_scan_cache(base)
            self.report({'WARNING'}, 'No supported image sequences or media found')
            return {'CANCELLED'}
        self.preflight_ready = True
        self.allow_very_large_import = False
        return context.window_manager.invoke_props_dialog(self, width=520)

    def invoke(self, context, event):
        path = context.scene.fbp_last_directory or context.scene.fbp_project_path
        if path and os.path.isdir(bpy.path.abspath(path)):
            self.directory = path
        self.preflight_ready = False
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def check(self, context):
        if not self.preflight_ready:
            return False
        base = self._base()
        if not base or not os.path.isdir(base):
            return False
        if bool(self.detected_gap_state) == bool(self.preserve_exposure_gaps):
            return False
        previous = (self.detected_exposure_frames, self.detected_hold_frames)
        self._refresh(base, consume=False)
        self.allow_very_large_import = False
        return previous != (self.detected_exposure_frames, self.detected_hold_frames)

    def draw(self, context):
        layout = self.layout
        base = self._base()
        layout.label(text='Toon Boom Harmony Export', icon=fbp_icon('RENDER_ANIMATION'))
        if base:
            layout.label(text=os.path.basename(os.path.normpath(base)) or base, icon=fbp_icon('FILE_FOLDER'))
        if not self.preflight_ready:
            layout.label(text='Choose the root folder produced by your Harmony export.', icon=fbp_icon('INFO'))
            return

        summary = layout.box()
        summary.label(
            text=f"Detected: {self.detected_layers} layer(s) from {self.detected_files} media file(s)",
            icon=fbp_icon('OUTLINER_COLLECTION'),
        )
        row = summary.row(align=False)
        row.label(text=f"Sequences: {self.detected_sequences}")
        row.label(text=f"Collections: {self.detected_collections}")
        summary.label(text=f"Prepared timeline frames: {self.detected_exposure_frames}")
        if self.detected_hold_frames:
            summary.label(text=f"Numbered gaps preserved as {self.detected_hold_frames} hold frame(s)", icon=fbp_icon('FORWARD'))

        layout.prop(self, 'preserve_exposure_gaps')
        if self.detected_preview:
            preview = layout.box()
            preview.label(text='Detected Layers', icon=fbp_icon('OUTLINER_COLLECTION'))
            for line in self.detected_preview.splitlines():
                preview.label(text=line)
            remaining = max(0, self.detected_layers - _FBP_FOLDER_PREVIEW_LIMIT)
            if remaining:
                preview.label(text=f"… and {remaining} more layer(s)", icon=fbp_icon('DOT'))

        warning, confirmation = self._size_flags()
        if warning:
            box = layout.box()
            box.alert = True
            box.label(text='Large Toon Boom export', icon=fbp_icon('ERROR'))
            box.label(text='The setup may contain many layers, linked images or timeline frames.')
            if self.detected_exposure_frames >= _FBP_TOON_BOOM_WARNING_TIMELINE_FRAMES:
                box.label(text=f"Prepared timeline length: {self.detected_exposure_frames} frames")
            if confirmation:
                box.prop(self, 'allow_very_large_import')

        footer = layout.box()
        footer.label(text='The export is sent to Multiplane Setup before generation.', icon=fbp_icon('INFO'))
        footer.label(text='PNG alpha is preserved; unsupported and technical-map files are ignored.')
        footer.label(text='Collections start collapsed for faster review.')

    def cancel(self, context):
        base = self._base()
        if base:
            _fbp_discard_folder_scan_cache(base)

    def execute(self, context):
        base = self._base()
        if not base or not os.path.isdir(base):
            self.report({'WARNING'}, 'Choose a valid Toon Boom export folder')
            return {'CANCELLED'}
        if not self.preflight_ready:
            return self._open_preflight(context, base)

        confirmed_token = self.detected_snapshot_token
        rows = self._refresh(base, consume=True)
        if not rows:
            self.report({'WARNING'}, 'No supported image sequences or media found')
            return {'CANCELLED'}
        if confirmed_token and self.detected_snapshot_token != confirmed_token:
            self.allow_very_large_import = False
            self.report({'ERROR'}, 'Export sources changed after preview; review the import again')
            return {'CANCELLED'}

        _warning, confirmation = self._size_flags()
        if confirmation and not self.allow_very_large_import:
            self.report({'ERROR'}, 'Confirm the very large export before continuing')
            return {'CANCELLED'}

        stats = _fbp_prepare_toon_boom_pending_rows(
            context,
            base,
            rows,
            preserve_exposure_gaps=bool(self.preserve_exposure_gaps),
        )
        if not stats['layers']:
            self.report({'WARNING'}, 'No Toon Boom layers could be prepared')
            return {'CANCELLED'}
        self.report(
            {'INFO'},
            f"Toon Boom: {stats['layers']} layer(s) sent to Multiplane Setup; "
            f"{stats['hold_frames']} hold frame(s) preserved",
        )
        return {'FINISHED'}


def _fbp_layered_cache_root(context, source_path):
    """Prefer a persistent cache beside the layered source, then Blender data."""
    extension = os.path.splitext(str(source_path or ""))[1].lower()
    preferred = (
        fbp_default_procreate_cache_root(source_path)
        if extension == '.procreate'
        else fbp_default_psd_cache_root(source_path)
    )
    try:
        os.makedirs(preferred, exist_ok=True)
        return preferred
    except OSError:
        pass
    try:
        fallback = bpy.utils.user_resource(
            'DATAFILES', path=os.path.join('frame_by_plane', 'layered_cache'), create=True,
        )
    except FBP_DATA_ERRORS:
        fallback = ""
    if fallback:
        os.makedirs(fallback, exist_ok=True)
        return fallback
    raise OSError("No writable persistent folder is available for extracted layered-document images")


def _fbp_prepare_layered_pending_rows(context, source_path, extraction):
    scene = context.scene
    scene.fbp_creation_mode = 'MULTI'
    scene.fbp_parent_import_path = source_path
    scene.fbp_project_path = os.path.dirname(source_path)
    scene.fbp_last_directory = os.path.dirname(source_path)
    scene.fbp_pending_planes.clear()
    color_map = {}
    for record in extraction.records:
        item = scene.fbp_pending_planes.add()
        item.name = record.name
        item.collection_name = record.collection_path
        item.directory = extraction.output_directory
        item.files_str = record.relative_file
        item.follow_collection_color = bool(record.collection_path)
        color_key = record.collection_path or f"{extraction.output_directory}::{record.name}"
        item.fbp_color_tag = _fbp_color_tag_for_group(color_key, color_map)
        item.source_from_layered = True
        item.source_document = source_path
        item.source_layer_path = record.source_layer_path
        item.source_layer_kind = record.kind
        item.source_layer_visible = bool(record.visible)
        item.source_layer_opacity = max(0.0, min(1.0, float(record.opacity)))
        item.source_blend_mode = record.blend_mode
        item.source_is_clipping = bool(getattr(record, "is_clipping", False))
        mask_relative_file = str(getattr(record, "mask_relative_file", "") or "")
        item.source_mask_file = (
            os.path.join(extraction.output_directory, mask_relative_file)
            if mask_relative_file else ""
        )
        item.source_blend_supported = bool(getattr(record, "blend_supported", False))
        item.source_cache_key = extraction.cache_key
        item.source_preset = str(getattr(extraction, "source_format", "") or "LAYERED")
        item.source_flattened_group = bool(record.flattened_group)
        item.source_warnings = "\n".join(
            str(value) for value in getattr(record, "warnings", ()) if str(value).strip()
        )
    scene.fbp_pending_open_collections = ""
    _fbp_store_layered_import_report(scene, source_path, extraction)
    _fbp_refresh_pending_tree(context)
    return len(scene.fbp_pending_planes)


class FBP_OT_LayeredImportReport(Operator):
    bl_idname = "fbp.layered_import_report"
    bl_label = "Layered Import Report"
    bl_description = "Inspect transferred, flattened, skipped and unsupported properties from the current PSD, PSB or Procreate setup"

    @classmethod
    def poll(cls, context):
        scene = getattr(context, 'scene', None)
        if scene is None:
            return False
        return any(
            bool(getattr(item, 'source_from_layered', False))
            for item in getattr(scene, 'fbp_pending_planes', ())
        )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=650)

    def draw(self, context):
        scene = context.scene
        layout = self.layout
        source = str(getattr(scene, 'fbp_layered_report_source', '') or '')
        source_name = os.path.basename(source) if source else 'Current Multiplane Setup'
        source_format = str(getattr(scene, 'fbp_layered_report_format', '') or 'Layered')

        header = layout.column(align=False)
        header.label(text=source_name, icon=fbp_icon('RENDERLAYERS'))
        details = header.row(align=False)
        details.label(text=f"Format: {source_format}")
        backend = str(getattr(scene, 'fbp_layered_report_backend', '') or '')
        if backend:
            details.label(text=f"Decoder: {backend}")
        details.label(
            text='Cache reused'
            if bool(getattr(scene, 'fbp_layered_report_cache_reused', False))
            else 'Fresh extraction'
        )

        layered_items = [
            item for item in getattr(scene, 'fbp_pending_planes', ())
            if bool(getattr(item, 'source_from_layered', False))
        ]
        selected_items = [item for item in layered_items if bool(getattr(item, 'is_selected', False))]
        hidden = sum(not bool(getattr(item, 'source_layer_visible', True)) for item in layered_items)
        reduced_opacity = sum(
            float(getattr(item, 'source_layer_opacity', 1.0) or 0.0) < 0.999
            for item in layered_items
        )
        editable_blends = sum(
            bool(getattr(item, 'source_blend_supported', False))
            and str(getattr(item, 'source_blend_mode', 'NORMAL') or 'NORMAL').upper()
            not in {'NORMAL', 'PASS_THROUGH'}
            for item in layered_items
        )
        flattened = sum(bool(getattr(item, 'source_flattened_group', False)) for item in layered_items)

        stats = layout.box()
        stats.label(text='Prepared Setup', icon=fbp_icon('INFO'))
        grid = stats.grid_flow(columns=2, even_columns=True, even_rows=False, align=False)
        grid.label(text=f"Prepared layers: {len(layered_items)}")
        grid.label(text=f"Checked layers: {len(selected_items)}")
        grid.label(text=f"Hidden layers: {hidden}")
        grid.label(text=f"Reduced opacity: {reduced_opacity}")
        grid.label(text=f"Editable blend modes: {editable_blends}")
        grid.label(text=f"Flattened groups: {flattened}")

        transfer = layout.box()
        transfer.label(text='Transferred Source Data', icon=fbp_icon('NODE_MATERIAL'))
        grid = transfer.grid_flow(columns=2, even_columns=True, even_rows=False, align=False)
        grid.label(text=f"Blend modes: {int(getattr(scene, 'fbp_layered_report_transferred_blends', 0) or 0)}")
        grid.label(text=f"Layer masks: {int(getattr(scene, 'fbp_layered_report_transferred_masks', 0) or 0)}")
        grid.label(text=f"Clipping layers: {int(getattr(scene, 'fbp_layered_report_transferred_clipping', 0) or 0)}")
        grid.label(text=f"Decoded layers: {int(getattr(scene, 'fbp_layered_report_decoded_layers', 0) or 0)}")

        compatibility = layout.box()
        compatibility.label(text='Original Extraction Compatibility', icon=fbp_icon('MOD_MASK'))
        grid = compatibility.grid_flow(columns=2, even_columns=True, even_rows=False, align=False)
        grid.label(text=f"Skipped layers: {int(getattr(scene, 'fbp_layered_report_skipped_layers', 0) or 0)}")
        grid.label(text=f"Unsupported blends: {int(getattr(scene, 'fbp_layered_report_unsupported_blends', 0) or 0)}")
        grid.label(text=f"Baked clipping: {int(getattr(scene, 'fbp_layered_report_merged_clipping', 0) or 0)}")
        grid.label(text=f"Flattened source groups: {int(getattr(scene, 'fbp_layered_report_flattened_groups', 0) or 0)}")
        if bool(getattr(scene, 'fbp_layered_report_fallback_preview', False)):
            fallback = compatibility.row(align=False)
            fallback.alert = True
            fallback.label(text='The document used a flattened preview fallback.', icon=fbp_icon('ERROR'))

        warnings = []
        document_warnings = str(getattr(scene, 'fbp_layered_report_warnings', '') or '')
        warnings.extend(line.strip() for line in document_warnings.splitlines() if line.strip())
        for item in layered_items:
            layer_path = str(
                getattr(item, 'source_layer_path', '')
                or getattr(item, 'name', '')
                or 'Layer'
            )
            for line in str(getattr(item, 'source_warnings', '') or '').splitlines():
                line = line.strip()
                if line:
                    warnings.append(f"{layer_path}: {line}")

        if warnings:
            warning_box = layout.box()
            warning_box.label(text=f"Warnings ({len(warnings)})", icon=fbp_icon('ERROR'))
            for line in warnings[:20]:
                warning_box.label(text=line[:180])
            if len(warnings) > 20:
                warning_box.label(text=f"…and {len(warnings) - 20} more warning(s)")
        else:
            ok = layout.box()
            ok.label(text='No compatibility warnings were recorded.', icon=fbp_icon('CHECKMARK'))

    def execute(self, context):
        return {'FINISHED'}


FBP_PSD_WARN_LAYERS = 256
FBP_PSD_CONFIRM_LAYERS = 1000
FBP_PSD_WARN_PIXEL_LAYERS = 500_000_000
FBP_PSD_CONFIRM_PIXEL_LAYERS = 2_000_000_000


class FBP_OT_ImportPSD(Operator):
    bl_idname = "fbp.import_psd"
    bl_label = "Import PSD / PSB"
    bl_description = "Import Photoshop layers as a Frame By Plane Multiplane while preserving groups as Blender collections"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.psd;*.psb", options={'HIDDEN'})
    preserve_groups: BoolProperty(
        name="Preserve Groups as Collections",
        description="Convert Photoshop groups into nested Blender collections",
        default=True,
    )
    include_hidden: BoolProperty(
        name="Import Hidden Layers",
        description="Extract hidden PSD layers too and import them disabled in Blender",
        default=False,
    )
    flatten_complex_groups: BoolProperty(
        name="Flatten Complex Groups",
        description="Flatten groups with group opacity or non-pass-through blending so their appearance is not silently misrepresented",
        default=True,
    )
    reuse_cache: BoolProperty(
        name="Reuse Extracted Layers",
        description="Reuse persistent PNG layers when the PSD revision and import options have not changed",
        default=True,
    )
    import_action: EnumProperty(
        name="After Extraction",
        description="Review extracted layers in Multiplane Setup or generate the complete rig immediately",
        items=(
            ('SETUP', "Send to Multiplane Setup", "Extract layers and open them for review in the N-panel"),
            ('GENERATE', "Generate Multiplane", "Extract layers and immediately generate the Multiplane rig"),
        ),
        default='SETUP',
    )
    preflight_ready: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})
    detected_width: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_height: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_bit_depth: IntProperty(default=8, min=1, options={'HIDDEN', 'SKIP_SAVE'})
    detected_layers: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_groups: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_hidden: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_clipping: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_masks: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_complex_groups: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_blend_modes: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    backend_version: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})
    confirm_large_import: BoolProperty(
        name="I Understand — Continue Import",
        description="Confirm extraction of a very large PSD/PSB that may require substantial time, memory and cache storage",
        default=False,
        options={'SKIP_SAVE'},
    )

    def _pixel_layer_estimate(self):
        return int(self.detected_width) * int(self.detected_height) * max(1, int(self.detected_layers))

    def _is_large_document(self):
        estimate = self._pixel_layer_estimate()
        return bool(
            int(self.detected_layers) > FBP_PSD_WARN_LAYERS
            or estimate > FBP_PSD_WARN_PIXEL_LAYERS
        )

    def _requires_large_confirmation(self):
        estimate = self._pixel_layer_estimate()
        return bool(
            int(self.detected_layers) > FBP_PSD_CONFIRM_LAYERS
            or estimate > FBP_PSD_CONFIRM_PIXEL_LAYERS
        )

    def _absolute_path(self):
        return os.path.abspath(bpy.path.abspath(self.filepath or ""))

    def _prepare_preflight(self):
        path = self._absolute_path()
        if not os.path.isfile(path) or os.path.splitext(path)[1].lower() not in {'.psd', '.psb'}:
            raise ValueError("Choose a valid PSD or PSB document")
        probe = fbp_probe_layered_document(path)
        if not probe.valid:
            raise ValueError("; ".join(probe.warnings) or "Invalid PSD/PSB document")
        status = fbp_layered_backend_status()[0]
        if not status.available:
            raise RuntimeError(status.detail)
        summary = fbp_inspect_psd_layers(path)
        self.detected_width = int(summary['width'])
        self.detected_height = int(summary['height'])
        self.detected_bit_depth = int(probe.bit_depth or 8)
        self.detected_layers = int(summary['layers'])
        self.detected_groups = int(summary['groups'])
        self.detected_hidden = int(summary['hidden_layers'])
        self.detected_clipping = int(summary['clipping_layers'])
        self.detected_masks = int(summary.get('mask_layers', 0))
        self.detected_complex_groups = int(summary['complex_groups'])
        self.detected_blend_modes = int(summary['non_normal_blend_layers'])
        self.backend_version = str(summary['backend_version'])
        self.preflight_ready = True

    def invoke(self, context, event):
        path = self._absolute_path()
        if path and os.path.isfile(path):
            try:
                self._prepare_preflight()
            except (OSError, ValueError, RuntimeError) as exc:
                self.report({'ERROR'}, str(exc))
                return {'CANCELLED'}
            return context.window_manager.invoke_props_dialog(self, width=560)
        start = context.scene.fbp_project_path or context.scene.fbp_last_directory
        if start:
            self.filepath = os.path.join(bpy.path.abspath(start), "")
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def draw(self, context):
        layout = self.layout
        title = os.path.basename(self._absolute_path()) or "PSD / PSB"
        layout.label(text=title, icon=fbp_icon('FILE_IMAGE'))
        info = layout.box()
        row = info.row(align=False)
        row.label(text=f"Canvas: {self.detected_width} × {self.detected_height}")
        row.label(text=f"Layers: {self.detected_layers}")
        row.label(text=f"Groups: {self.detected_groups}")
        info.label(text=f"Source depth: {self.detected_bit_depth}-bit")
        if self.detected_bit_depth > 8:
            depth_warning = info.row()
            depth_warning.alert = True
            depth_warning.label(text="Layer cache is converted to standard 8-bit RGBA PNG", icon=fbp_icon('INFO'))
        if self.detected_hidden:
            info.label(text=f"Hidden layers: {self.detected_hidden}", icon=fbp_icon('HIDE_ON'))
        if self.detected_clipping:
            info.label(text=f"{self.detected_clipping} clipping layer(s) will become editable Clipping Masks", icon=fbp_icon('MOD_MASK'))
        if self.detected_masks:
            info.label(text=f"{self.detected_masks} raster/vector mask(s) will become editable Imported Layer Masks", icon=fbp_icon('IMAGE_ALPHA'))
        if self.detected_complex_groups:
            info.label(text=f"{self.detected_complex_groups} complex group(s) can be flattened for safer rendering", icon=fbp_icon('INFO'))
        if self.detected_blend_modes:
            info.label(text=f"{self.detected_blend_modes} non-normal blend mode(s): principal modes will transfer to Layer Blend", icon=fbp_icon('NODE_MATERIAL'))
        if self._is_large_document():
            large = layout.box()
            large.alert = True
            large.label(text="Large layered document", icon=fbp_icon('ERROR'))
            large.label(text=f"Estimated full-canvas workload: {self._pixel_layer_estimate():,} layer-pixels")
            if self._requires_large_confirmation():
                large.prop(self, "confirm_large_import")
        layout.prop(self, "preserve_groups")
        layout.prop(self, "include_hidden")
        layout.prop(self, "flatten_complex_groups")
        layout.prop(self, "reuse_cache")
        _fbp_draw_import_alpha_crop_options(layout, context.scene)
        layout.separator()
        layout.prop(self, "import_action", expand=True)
        footer = layout.row()
        footer.enabled = False
        footer.label(text=f"PSD decoder: psd-tools {self.backend_version}")

    def execute(self, context):
        if not self.preflight_ready:
            try:
                self._prepare_preflight()
            except (OSError, ValueError, RuntimeError) as exc:
                self.report({'ERROR'}, str(exc))
                return {'CANCELLED'}
            return context.window_manager.invoke_props_dialog(self, width=560)

        if self._requires_large_confirmation() and not self.confirm_large_import:
            self.report({'WARNING'}, "Confirm the large PSD/PSB import before extraction")
            return {'CANCELLED'}

        path = self._absolute_path()
        try:
            extraction = fbp_extract_psd_layers(
                path,
                cache_root=_fbp_layered_cache_root(context, path),
                preserve_groups=self.preserve_groups,
                include_hidden=self.include_hidden,
                flatten_complex_groups=self.flatten_complex_groups,
                reuse_cache=self.reuse_cache,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            self.report({'ERROR'}, f"PSD import failed: {exc}")
            return {'CANCELLED'}

        prepared = _fbp_prepare_layered_pending_rows(context, path, extraction)
        if prepared <= 0:
            self.report({'WARNING'}, "The PSD did not produce any importable layers")
            return {'CANCELLED'}

        details = []
        if extraction.flattened_groups:
            details.append(f"{extraction.flattened_groups} flattened group(s)")
        if extraction.transferred_clipping_layers:
            details.append(f"{extraction.transferred_clipping_layers} clipping mask(s)")
        if extraction.transferred_masks:
            details.append(f"{extraction.transferred_masks} imported layer mask(s)")
        if extraction.transferred_blend_modes:
            details.append(f"{extraction.transferred_blend_modes} transferred blend mode(s)")
        if extraction.unsupported_blend_modes:
            details.append(f"{extraction.unsupported_blend_modes} unsupported blend mode(s)")
        if extraction.skipped_layers:
            details.append(f"{extraction.skipped_layers} skipped layer(s)")
        if extraction.warnings:
            details.append(f"{len(extraction.warnings)} compatibility warning(s)")
        suffix = f"; {', '.join(details)}" if details else ""
        cache_note = "reused cache" if extraction.reused_cache else "extracted PNG cache"

        if self.import_action == 'SETUP':
            context.scene.fbp_show_create_tools = True
            self.report({'INFO'}, f"PSD: {prepared} layer(s) sent to Multiplane Setup ({cache_note}){suffix}")
            return {'FINISHED'}

        self.report({'INFO'}, f"PSD: generating {prepared} layer(s) ({cache_note}){suffix}")
        return bpy.ops.fbp.generate_multiplane()


FBP_PROCREATE_WARN_LAYERS = 256
FBP_PROCREATE_CONFIRM_LAYERS = 1000
FBP_PROCREATE_WARN_PIXEL_LAYERS = 500_000_000
FBP_PROCREATE_CONFIRM_PIXEL_LAYERS = 2_000_000_000


class FBP_OT_ImportProcreate(Operator):
    bl_idname = "fbp.import_procreate"
    bl_label = "Import Procreate"
    bl_description = "Import common Procreate layer tiles as a Frame By Plane Multiplane, with a safe flattened-preview fallback"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.procreate", options={'HIDDEN'})
    preserve_groups: BoolProperty(
        name="Preserve Groups as Collections",
        description="Convert recognized Procreate groups into nested Blender collections",
        default=True,
    )
    include_hidden: BoolProperty(
        name="Import Hidden Layers",
        description="Extract hidden Procreate layers too and import them disabled in Blender",
        default=False,
    )
    fallback_to_preview: BoolProperty(
        name="Fallback to Composite Preview",
        description="Import the embedded QuickLook preview as one plane when individual layer tiles cannot be decoded",
        default=True,
    )
    reuse_cache: BoolProperty(
        name="Reuse Extracted Layers",
        description="Reuse persistent PNG layers when the Procreate revision and import options have not changed",
        default=True,
    )
    import_action: EnumProperty(
        name="After Extraction",
        description="Review extracted layers in Multiplane Setup or generate the complete rig immediately",
        items=(
            ('SETUP', "Send to Multiplane Setup", "Extract layers and open them for review in the N-panel"),
            ('GENERATE', "Generate Multiplane", "Extract layers and immediately generate the Multiplane rig"),
        ),
        default='SETUP',
    )
    preflight_ready: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})
    detected_width: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_height: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_layers: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_groups: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_hidden: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_clipping: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_masks: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_blend_modes: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_candidates: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_entries: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_has_preview: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})
    detected_video: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})
    backend_version: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})
    confirm_large_import: BoolProperty(
        name="I Understand — Continue Import",
        description="Confirm extraction of a very large Procreate document that may require substantial time, memory and cache storage",
        default=False,
        options={'SKIP_SAVE'},
    )

    def _pixel_layer_estimate(self):
        return int(self.detected_width) * int(self.detected_height) * max(1, int(self.detected_layers))

    def _is_large_document(self):
        estimate = self._pixel_layer_estimate()
        return bool(
            int(self.detected_layers) > FBP_PROCREATE_WARN_LAYERS
            or estimate > FBP_PROCREATE_WARN_PIXEL_LAYERS
        )

    def _requires_large_confirmation(self):
        estimate = self._pixel_layer_estimate()
        return bool(
            int(self.detected_layers) > FBP_PROCREATE_CONFIRM_LAYERS
            or estimate > FBP_PROCREATE_CONFIRM_PIXEL_LAYERS
        )

    def _absolute_path(self):
        return os.path.abspath(bpy.path.abspath(self.filepath or ""))

    def _prepare_preflight(self):
        path = self._absolute_path()
        if not os.path.isfile(path) or os.path.splitext(path)[1].lower() != '.procreate':
            raise ValueError("Choose a valid .procreate document")
        probe = fbp_probe_layered_document(path)
        if not probe.valid or probe.format != 'PROCREATE':
            raise ValueError("; ".join(probe.warnings) or "Invalid Procreate document")
        status = next(
            (item for item in fbp_layered_backend_status() if item.format == 'PROCREATE'),
            None,
        )
        if status is None or not status.available:
            raise RuntimeError(status.detail if status is not None else "Procreate decoder is unavailable")
        summary = fbp_inspect_procreate_layers(path)
        self.detected_width = int(summary['width'])
        self.detected_height = int(summary['height'])
        self.detected_layers = int(summary['layers'])
        self.detected_groups = int(summary['groups'])
        self.detected_hidden = int(summary['hidden_layers'])
        self.detected_clipping = int(summary.get('clipping_layers', 0))
        self.detected_masks = int(summary.get('mask_layers', 0))
        self.detected_blend_modes = int(summary['non_normal_blend_layers'])
        self.detected_candidates = int(summary['decodable_layer_candidates'])
        self.detected_entries = int(summary['archive_entries'])
        self.detected_has_preview = bool(summary['has_preview'])
        self.detected_video = bool(summary['video_enabled'])
        self.backend_version = str(summary['backend_version'])
        self.preflight_ready = True

    def invoke(self, context, event):
        path = self._absolute_path()
        if path and os.path.isfile(path):
            try:
                self._prepare_preflight()
            except (OSError, ValueError, RuntimeError) as exc:
                self.report({'ERROR'}, str(exc))
                return {'CANCELLED'}
            return context.window_manager.invoke_props_dialog(self, width=580)
        start = context.scene.fbp_project_path or context.scene.fbp_last_directory
        if start:
            self.filepath = os.path.join(bpy.path.abspath(start), "")
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def draw(self, context):
        layout = self.layout
        title = os.path.basename(self._absolute_path()) or "Procreate"
        layout.label(text=title, icon=fbp_icon('FILE_IMAGE'))
        info = layout.box()
        row = info.row(align=False)
        row.label(text=f"Canvas: {self.detected_width} × {self.detected_height}")
        row.label(text=f"Layers: {self.detected_layers}")
        row.label(text=f"Groups: {self.detected_groups}")
        info.label(text=f"Tile-backed layer candidates: {self.detected_candidates}")
        info.label(text=f"Archive entries: {self.detected_entries:,}")
        if self.detected_hidden:
            info.label(text=f"Hidden layers: {self.detected_hidden}", icon=fbp_icon('HIDE_ON'))
        if self.detected_clipping:
            info.label(text=f"{self.detected_clipping} clipping layer(s) will become editable Clipping Masks", icon=fbp_icon('MOD_MASK'))
        if self.detected_masks:
            info.label(text=f"{self.detected_masks} Layer Mask(s) will become editable Imported Layer Masks", icon=fbp_icon('IMAGE_ALPHA'))
        if self.detected_blend_modes:
            info.label(text=f"{self.detected_blend_modes} non-normal blend mode(s): principal modes will transfer to Layer Blend", icon=fbp_icon('NODE_MATERIAL'))
        if self.detected_video:
            info.label(text="The Procreate time-lapse video is not imported", icon=fbp_icon('INFO'))
        if not self.detected_candidates:
            fallback = info.row()
            fallback.alert = True
            if self.detected_has_preview:
                fallback.label(text="No decodable layer tile folders detected; the QuickLook preview can be used", icon=fbp_icon('INFO'))
            else:
                fallback.label(text="No decodable layer tiles or QuickLook preview detected", icon=fbp_icon('ERROR'))
        notice = layout.box()
        notice.label(text="Experimental proprietary-format decoder", icon=fbp_icon('INFO'))
        notice.label(text="Review the extracted hierarchy in Multiplane Setup before generation.")
        if self._is_large_document():
            large = layout.box()
            large.alert = True
            large.label(text="Large layered document", icon=fbp_icon('ERROR'))
            large.label(text=f"Estimated full-canvas workload: {self._pixel_layer_estimate():,} layer-pixels")
            if self._requires_large_confirmation():
                large.prop(self, "confirm_large_import")
        layout.prop(self, "preserve_groups")
        layout.prop(self, "include_hidden")
        layout.prop(self, "fallback_to_preview")
        layout.prop(self, "reuse_cache")
        _fbp_draw_import_alpha_crop_options(layout, context.scene)
        layout.separator()
        layout.prop(self, "import_action", expand=True)
        footer = layout.row()
        footer.enabled = False
        footer.label(text=f"Local Procreate decoder: {self.backend_version}")

    def execute(self, context):
        if not self.preflight_ready:
            try:
                self._prepare_preflight()
            except (OSError, ValueError, RuntimeError) as exc:
                self.report({'ERROR'}, str(exc))
                return {'CANCELLED'}
            return context.window_manager.invoke_props_dialog(self, width=580)
        if self._requires_large_confirmation() and not self.confirm_large_import:
            self.report({'WARNING'}, "Confirm the large Procreate import before extraction")
            return {'CANCELLED'}
        path = self._absolute_path()
        try:
            extraction = fbp_extract_procreate_layers(
                path,
                cache_root=_fbp_layered_cache_root(context, path),
                preserve_groups=self.preserve_groups,
                include_hidden=self.include_hidden,
                fallback_to_preview=self.fallback_to_preview,
                reuse_cache=self.reuse_cache,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            self.report({'ERROR'}, f"Procreate import failed: {exc}")
            return {'CANCELLED'}
        prepared = _fbp_prepare_layered_pending_rows(context, path, extraction)
        if prepared <= 0:
            self.report({'WARNING'}, "The Procreate document did not produce any importable layers")
            return {'CANCELLED'}
        details = []
        if extraction.fallback_preview:
            details.append("flattened QuickLook fallback")
        if extraction.transferred_clipping_layers:
            details.append(f"{extraction.transferred_clipping_layers} clipping mask(s)")
        if extraction.transferred_blend_modes:
            details.append(f"{extraction.transferred_blend_modes} transferred blend mode(s)")
        if extraction.unsupported_blend_modes:
            details.append(f"{extraction.unsupported_blend_modes} unsupported blend mode(s)")
        if extraction.skipped_layers:
            details.append(f"{extraction.skipped_layers} undecoded layer(s)")
        if extraction.warnings:
            details.append(f"{len(extraction.warnings)} compatibility warning(s)")
        suffix = f"; {', '.join(details)}" if details else ""
        cache_note = "reused cache" if extraction.reused_cache else "extracted PNG cache"
        if self.import_action == 'SETUP':
            context.scene.fbp_show_create_tools = True
            self.report({'INFO'}, f"Procreate: {prepared} layer(s) sent to Multiplane Setup ({cache_note}){suffix}")
            return {'FINISHED'}
        self.report({'INFO'}, f"Procreate: generating {prepared} layer(s) ({cache_note}){suffix}")
        return bpy.ops.fbp.generate_multiplane()


class FBP_FH_ProcreateDrop(bpy.types.FileHandler):
    bl_idname = "FBP_FH_procreate_drop"
    bl_label = "Frame By Plane Procreate"
    bl_import_operator = FBP_OT_ImportProcreate.bl_idname
    bl_file_extensions = ".procreate"

    @classmethod
    def poll_drop(cls, context):
        area = getattr(context, "area", None)
        return bool(area and area.type == 'VIEW_3D')


class FBP_FH_LayeredDrop(bpy.types.FileHandler):
    bl_idname = "FBP_FH_layered_drop"
    bl_label = "Frame By Plane PSD / PSB"
    bl_import_operator = FBP_OT_ImportPSD.bl_idname
    bl_file_extensions = ";".join(sorted(ext for ext in FBP_LAYERED_EXTENSIONS if ext in {'.psd', '.psb'}))

    @classmethod
    def poll_drop(cls, context):
        area = getattr(context, "area", None)
        return bool(area and area.type == 'VIEW_3D')


class FBP_OT_DropMedia(Operator):
    """Native FileHandler target for media dragged from the operating system."""

    bl_idname = "fbp.drop_media"
    bl_label = "Import with Frame By Plane"
    bl_description = "Import dropped media; one dropped file can also scan and import its complete parent folder"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(
        description="Primary media path supplied by Blender's drag-and-drop FileHandler",
        subtype='FILE_PATH',
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    directory: StringProperty(
        description="Base folder supplied by Blender's drag-and-drop FileHandler",
        subtype='DIR_PATH',
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    files: CollectionProperty(
        description="Media files supplied by Blender's drag-and-drop FileHandler",
        type=bpy.types.OperatorFileListElement,
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    source_mode: EnumProperty(
        name="Source",
        description="Choose whether to import only the dropped media or scan its entire parent folder",
        items=(
            ('DROPPED', "Dropped Media", "Use only the files dragged into Blender"),
            ('FOLDER', "Parent Folder", "Scan the complete parent folder and its subfolders"),
        ),
        default='DROPPED',
        options={'SKIP_SAVE'},
        update=_fbp_reset_folder_import_confirmations,
    )
    import_mode: EnumProperty(
        name="Import As",
        description="Let Frame By Plane detect the correct structure or force one import type",
        items=(
            ('AUTO', "Auto", "One detected layer becomes a Single Plane; multiple layers become a Multiplane"),
            ('SINGLE', "Single Plane", "Import only when the chosen media forms one still, one video or one numbered image sequence"),
            ('MULTI', "Multiplane", "Create one plane per detected still, sequence, video, and folder layer"),
        ),
        default='AUTO',
        options={'SKIP_SAVE'},
        update=_fbp_reset_folder_import_confirmations,
    )
    confirm_large_folder: BoolProperty(
        name="Import This Very Large Folder",
        description=(
            "Explicitly confirm importing the complete parent folder when it contains a very large "
            "number of detected layers or source files"
        ),
        default=False,
        options={'SKIP_SAVE'},
    )
    confirm_single_root_only: BoolProperty(
        name="Import Only the Root-Level Source",
        description=(
            "Confirm that Parent Folder should import only its single root-level source and "
            "intentionally ignore all nested or additional detected layers"
        ),
        default=False,
        options={'SKIP_SAVE'},
    )
    detected_folder_layers: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_folder_files: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_folder_collections: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_folder_sequences: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_folder_stills: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_folder_videos: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_folder_direct_layers: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    detected_folder_preview: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})
    detected_folder_snapshot_token: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})

    def _resolved_paths(self):
        return _fbp_resolve_dropped_paths(self.filepath, self.directory, self.files)

    def _parent_folder(self, paths):
        files = _fbp_drop_importable_files(paths)
        if not files:
            directories = [path for path in paths if os.path.isdir(path)]
            return directories[0] if len(directories) == 1 else ""
        parents = {os.path.normcase(os.path.dirname(path)): os.path.dirname(path) for path in files}
        return next(iter(parents.values())) if len(parents) == 1 else ""

    def _folder_rows(self, folder, *, consume=False):
        if not folder or not os.path.isdir(folder):
            return []
        return _fbp_scan_folder_rows_cached(folder, animation=True, consume=consume)

    def _update_folder_summary(self, rows):
        summary = _fbp_folder_rows_summary(rows)
        self.detected_folder_layers = summary['layers']
        self.detected_folder_files = summary['files']
        self.detected_folder_collections = summary['collections']
        self.detected_folder_sequences = summary['sequences']
        self.detected_folder_stills = summary['stills']
        self.detected_folder_videos = summary['videos']
        self.detected_folder_preview = _fbp_folder_rows_preview_text(rows)
        base = self._parent_folder(self._resolved_paths())
        self.detected_folder_snapshot_token = _fbp_folder_rows_token(base, rows)
        self.detected_folder_direct_layers = len(_fbp_folder_rows_direct(base, rows))
        return summary

    def _folder_size_flags(self):
        return _fbp_folder_import_size_flags({
            'layers': self.detected_folder_layers,
            'files': self.detected_folder_files,
        })

    def _invoke_folder_confirmation_if_required(self, context, rows):
        self._update_folder_summary(rows)
        _warning, confirmation = self._folder_size_flags()
        if confirmation:
            self.confirm_large_folder = False
            return context.window_manager.invoke_props_dialog(self, width=480)
        return self.execute(context)

    def invoke(self, context, event):
        paths = self._resolved_paths()
        if not paths:
            self.report({'WARNING'}, "No supported dropped media found")
            return {'CANCELLED'}

        directory_paths = [path for path in paths if os.path.isdir(path)]
        if directory_paths:
            self.source_mode = 'FOLDER'
            return self._invoke_folder_confirmation_if_required(
                context, self._folder_rows(directory_paths[0], consume=False)
            )

        parent = self._parent_folder(paths)
        if bool(getattr(event, "alt", False)) and parent:
            self.source_mode = 'FOLDER'
            return self._invoke_folder_confirmation_if_required(
                context, self._folder_rows(parent, consume=False)
            )

        # Multiple selected files already express the intended source clearly
        # and can be classified without interrupting the drop workflow.
        dropped_files = _fbp_drop_importable_files(paths)
        if len(dropped_files) != 1 or not parent:
            return self.execute(context)

        # For one dropped file, offer the whole-folder workflow only when the
        # parent contains additional importable media or nested layers.
        folder_rows = self._folder_rows(parent)
        summary = self._update_folder_summary(folder_rows)
        if summary['files'] <= 1 and summary['layers'] <= 1:
            return self.execute(context)

        # Blender filters external drops by file extension before invoking a
        # Python FileHandler. Ordinary folder paths therefore never reach this
        # operator. Keep the exact dropped file as the safe default and expose
        # Parent Folder explicitly in the confirmation dialog.
        self.source_mode = 'DROPPED'
        return context.window_manager.invoke_props_dialog(self, width=480)

    def draw(self, context):
        layout = self.layout
        paths = self._resolved_paths()
        dropped_files = _fbp_drop_importable_files(paths)
        parent = self._parent_folder(paths)

        layout.label(text="Frame By Plane Drop", icon=fbp_icon("IMPORT"))
        layout.label(text=f"Dropped: {len(dropped_files)} supported file(s)")
        if parent and self.detected_folder_layers:
            summary = layout.box()
            summary.label(
                text=(
                    f"Parent folder: {self.detected_folder_layers} layer(s) from "
                    f"{self.detected_folder_files} file(s)"
                ),
                icon=fbp_icon("FILE_FOLDER"),
            )
            detail = summary.row(align=False)
            detail.label(text=f"Stills: {self.detected_folder_stills}")
            detail.label(text=f"Sequences: {self.detected_folder_sequences}")
            detail.label(text=f"Videos: {self.detected_folder_videos}")
            summary.label(text=f"Collection paths: {self.detected_folder_collections}")
            if self.detected_folder_preview:
                summary.separator()
                for line in self.detected_folder_preview.splitlines():
                    summary.label(text=line)
                remaining = max(0, self.detected_folder_layers - _FBP_FOLDER_PREVIEW_LIMIT)
                if remaining:
                    summary.label(text=f"… and {remaining} more layer(s)")

        layout.separator()
        layout.prop(self, "source_mode", expand=True)
        layout.prop(self, "import_mode", expand=True)

        if self.source_mode == 'FOLDER':
            resolved = _fbp_resolved_folder_import_mode(
                self.import_mode, self.detected_folder_layers
            )
            layout.label(
                text=("Result: Single Plane" if resolved == 'SINGLE' else "Result: Multiplane"),
                icon=fbp_icon("IMAGE_DATA") if resolved == 'SINGLE' else fbp_icon("OUTLINER_COLLECTION"),
            )
            if self.import_mode == 'SINGLE' and self.detected_folder_layers > 1:
                single_box = layout.box()
                if self.detected_folder_direct_layers == 1:
                    ignored = max(0, self.detected_folder_layers - 1)
                    single_box.label(text="Single Plane will use the only root-level source.", icon=fbp_icon("INFO"))
                    single_box.label(text=f"{ignored} nested or additional layer(s) will be ignored.")
                    single_box.prop(self, "confirm_single_root_only")
                else:
                    single_box.alert = True
                    single_box.label(text="Single Plane is unavailable for this parent folder.", icon=fbp_icon("ERROR"))
                    single_box.label(text="Choose Auto/Multiplane, or import one logical source.")
            warning, confirmation = self._folder_size_flags()
            if warning:
                box = layout.box()
                box.alert = True
                box.label(text="Large parent-folder import", icon=fbp_icon("ERROR"))
                box.label(text="Generation may take time and consume substantial memory.")
                if confirmation:
                    box.prop(self, "confirm_large_folder")
            layout.separator()
            layout.label(text="The complete parent-folder hierarchy will be scanned.", icon=fbp_icon("INFO"))
            layout.label(text="Direct folder drop is unavailable in Blender 5.1; use Import Folder instead.", icon=fbp_icon("INFO"))
        elif len(dropped_files) == 1 and parent and self.detected_folder_files > 1:
            layout.separator()
            layout.label(text="Dropped Media is the safe default; choose Parent Folder explicitly when needed.", icon=fbp_icon("INFO"))
        elif len(dropped_files) > 1:
            layout.separator()
            layout.label(text="Only the selected dropped files will be imported.", icon=fbp_icon("INFO"))

        if self.source_mode == 'DROPPED' and self.import_mode == 'SINGLE' and len(dropped_files) > 1:
            directories = {os.path.normcase(os.path.dirname(path)) for path in dropped_files}
            grouped = []
            if len(directories) == 1:
                grouped = fbp_group_direct_media_into_layers(
                    [os.path.basename(path) for path in dropped_files],
                    clean_layer_name_from_path(os.path.dirname(dropped_files[0])),
                )
            if len(grouped) != 1:
                box = layout.box()
                box.alert = True
                box.label(text="These files do not form one logical Single Plane source.", icon=fbp_icon("ERROR"))
                box.label(text="Use Auto/Multiplane or drop one numbered sequence.")

    def cancel(self, context):
        paths = self._resolved_paths()
        parent = self._parent_folder(paths)
        if parent:
            _fbp_discard_folder_scan_cache(parent)

    def execute(self, context):
        paths = self._resolved_paths()
        dropped_files = _fbp_drop_importable_files(paths)
        parent = self._parent_folder(paths)

        if self.source_mode == 'FOLDER':
            base = parent
            if not base:
                directories = [path for path in paths if os.path.isdir(path)]
                base = directories[0] if len(directories) == 1 else ""
            if not base or not os.path.isdir(base):
                self.report({'WARNING'}, "The dropped media does not share one parent folder")
                return {'CANCELLED'}

            if (
                self.import_mode == 'SINGLE'
                and self.detected_folder_layers > 1
                and self.detected_folder_direct_layers == 1
                and not self.confirm_single_root_only
            ):
                _fbp_discard_folder_scan_cache(base)
                self.report({'ERROR'}, "Confirm that only the root-level source should be imported")
                return {'CANCELLED'}

            confirmed_snapshot_token = self.detected_folder_snapshot_token
            rows = self._folder_rows(base, consume=True)
            self._update_folder_summary(rows)
            if confirmed_snapshot_token and self.detected_folder_snapshot_token != confirmed_snapshot_token:
                self.confirm_large_folder = False
                self.confirm_single_root_only = False
                self.report({'ERROR'}, "Parent-folder sources changed after preview; review the import again")
                return {'CANCELLED'}
            if (
                self.import_mode == 'SINGLE'
                and self.detected_folder_layers > 1
                and self.detected_folder_direct_layers == 1
                and not self.confirm_single_root_only
            ):
                self.report({'ERROR'}, "Folder sources changed; confirm the root-only Single Plane import again")
                return {'CANCELLED'}
            _warning, confirmation = self._folder_size_flags()
            if confirmation and not self.confirm_large_folder:
                self.report({'ERROR'}, "Confirm the very large parent-folder import before continuing")
                return {'CANCELLED'}
        else:
            base, rows = _fbp_drop_rows_from_files(dropped_files)

        if not rows:
            self.report({'WARNING'}, "No supported images, sequences, or videos found")
            return {'CANCELLED'}

        if self.source_mode == 'FOLDER':
            return _fbp_execute_detected_folder_import(
                self,
                context,
                base,
                rows,
                import_mode=self.import_mode,
            )

        resolved_mode = _fbp_resolved_folder_import_mode(self.import_mode, len(rows))
        if resolved_mode == 'SINGLE':
            if len(rows) == 1:
                _name, _collection, directory, filenames, _follow = rows[0]
                return _fbp_execute_single_plane_import(self, context, directory, filenames)

            # A forced Single Plane must still represent one real logical
            # source. Do not reinterpret unrelated dropped stills or videos as
            # frames of an image sequence merely because they share a folder.
            directory, filenames, error = _fbp_single_plane_source_from_paths(dropped_files)
            if error:
                self.report({'WARNING'}, error)
                return {'CANCELLED'}
            return _fbp_execute_single_plane_import(self, context, directory, filenames)

        if _fbp_prepare_pending_rows(context, base, rows) <= 0:
            self.report({'WARNING'}, "No Multiplane layers could be prepared")
            return {'CANCELLED'}
        summary = _fbp_folder_rows_summary(rows)
        self.report(
            {'INFO'},
            f"Detected {summary['layers']} layer(s) from {summary['files']} media file(s); generating Multiplane",
        )
        return bpy.ops.fbp.generate_multiplane()


class FBP_FH_MediaDrop(bpy.types.FileHandler):
    """Associate supported media drops in the 3D View with Frame By Plane."""

    bl_idname = "FBP_FH_media_drop"
    bl_label = "Frame By Plane"
    bl_import_operator = FBP_OT_DropMedia.bl_idname
    bl_file_extensions = ";".join(sorted(FBP_SUPPORTED_MEDIA_EXT))

    @classmethod
    def poll_drop(cls, context):
        area = getattr(context, "area", None)
        return bool(area and area.type == 'VIEW_3D')

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
        _fbp_draw_import_alpha_crop_options(layout, sc)

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
        _fbp_draw_import_alpha_crop_options(layout, sc)

    def execute(self, context):
        return bpy.ops.fbp.import_sequence('INVOKE_DEFAULT')

class FBP_OT_PopupMultiplane(Operator):
    bl_idname = "fbp.popup_multiplane"
    bl_label = "Multiplane"
    bl_description = "Quick multiplane setup. Use Send To N-Panel for advanced setup review"
    bl_options = {'REGISTER', 'UNDO'}

    animation: BoolProperty(description="Enable animated-media behavior for this import or Multiplane setup instead of a single static image workflow.", default=True)
    send_to_panel: BoolProperty(description="Transfer the current compact Multiplane setup to the Frame By Plane N-panel for detailed review and editing.", name="Send To N-Panel", default=False)
    folder: StringProperty(description="Folder selected for the compact Multiplane import workflow.", name="Folder", subtype='DIR_PATH', default="")

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
        _fbp_draw_import_alpha_crop_options(layout, sc)
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
        rows = fbp_scan_project_layers_for_setup(
            base,
            separate_sequences=False,
            reverse_sequences=False,
        )
        if not self.animation:
            rows = [(name, coll, directory, files[:1], follow) for name, coll, directory, files, follow in rows if files]
        sc.fbp_pending_planes.clear()
        color_map = {}
        for name, collection_name, directory, files, follow_collection_color in rows:
            item = sc.fbp_pending_planes.add()
            item.name = name
            item.collection_name = collection_name
            item.directory = directory
            item.files_str = "|".join(files)
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

    preset_type: StringProperty(description="Procedural plane type requested by the compact creation popup.", default="")

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
        except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
            pasted = None
        finally:
            try:
                area.type = original_type
            except FBP_DATA_ERRORS:
                pass

    if pasted is not None:
        return pasted

    # Defensive fallback in case Blender created the datablock without making
    # it the active Image Editor image.
    for image in reversed(list(bpy.data.images)):
        try:
            if image.as_pointer() not in before:
                return image
        except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
        return ''

    directory = _fbp_clipboard_storage_directory(context)
    raw_name = str(getattr(image, 'name', '') or 'Clipboard Image')
    safe_name = _FBP_SAFE_CLIPBOARD_NAME_RE.sub('_', raw_name).strip('._-') or 'Clipboard_Image'
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
        except FBP_DATA_ERRORS:
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
            _fbp_note_successful_import(context, multiplane=False)
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
            except FBP_DATA_ERRORS:
                pass

        self.report({'INFO'}, "Created Frame by Plane rig from clipboard image")
        _fbp_note_successful_import(context, multiplane=False)
        return {'FINISHED'}
