"""Core sequence, procedural material and shared UI operations."""

import time
from bisect import bisect_right

import bpy

from .constants import STRIP_COLORS_DICT, fbp_icon
from .path_utils import natural_sort_key
from .materials import (
    safe_get_socket,
    fbp_remove_unused_materials_and_images,
    do_update_emission,
    do_update_opacity,
    configure_fbp_material_surface,
    fbp_rebuild_color_plane_material,
    get_fbp_gradient_material_from_rig,
    find_fbp_gradient_ramp_node,
    update_fbp_gradient_viewport_color,
    apply_fbp_gradient_mapping_to_material,
    get_fbp_gradient_preview_material,
    fbp_schedule_gradient_preview_material_sync,
    fbp_get_active_frame_material,
    fbp_material_color_value,
    fbp_duplicate_procedural_material_for_frame,
    ensure_fbp_plane_material_integrity,
)
from .builder import set_plane_mesh_extension
from .runtime import (
    FBP_DATA_ERRORS,
    FBP_DATA_IO_ERRORS,
    fbp_warn,
    fbp_warn_once,
    fbp_runtime_get,
    fbp_runtime_set,
    fbp_render_mutation_blocked,
    fbp_obj_runtime_key,
    fbp_find_id_by_runtime_key,
    fbp_is_silent_property_update,
    fbp_set_rna_property_silent,
    fbp_action_fcurves,
)
from .layers import (
    _FBP_SYNCING_PROCEDURAL_PREVIEW_ITEMS,
    apply_collection_color_to_layer,
    fbp_clear_collection_ui_state_cache,
    fbp_cache_procedural_preview_on_item,
    fbp_procedural_kind_for_item,
    fbp_procedural_kind_from_material,
    fbp_resolve_rig_from_any_object,
    fbp_set_procedural_metadata,
    fbp_layer_backend_type,
    get_primary_fbp_collection,
    is_fbp_layer_object,
    iter_fbp_rigs_in_collection,
    iter_scene_fbp_rigs,
    update_rig_visibility,
)

_FBP_SYNCING_FRAME_MATERIAL_POINTERS = set()
_FBP_SUPPRESS_IMAGE_DURATION_CB = False
_FBP_PROCEDURAL_SCENE_CACHE_SECONDS = 1.0
_FBP_PROCEDURAL_SCENE_CACHE_LIMIT = 16
_FBP_PROCEDURAL_TIMING_CACHE = globals().get("_FBP_PROCEDURAL_TIMING_CACHE", {})
if not isinstance(_FBP_PROCEDURAL_TIMING_CACHE, dict):
    _FBP_PROCEDURAL_TIMING_CACHE = {}
_FBP_NATIVE_SCENE_RANGE_CACHE = globals().get("_FBP_NATIVE_SCENE_RANGE_CACHE", {})
if not isinstance(_FBP_NATIVE_SCENE_RANGE_CACHE, dict):
    _FBP_NATIVE_SCENE_RANGE_CACHE = {}


def _fbp_procedural_rig_cache_key(rig):
    """Return a runtime-only sequence-timing key without retaining RNA objects.

    The logical row count is part of the key so an added or removed frame can
    never reuse a cumulative timing table created for the previous list size.
    Explicit invalidation still handles duration edits and arbitrary reorders.
    """
    try:
        return (
            int(rig.as_pointer()),
            str(getattr(rig, "name_full", getattr(rig, "name", "")) or ""),
            len(getattr(rig, "fbp_images", ()) or ()),
        )
    except FBP_DATA_ERRORS:
        return (0, "", 0)


def fbp_invalidate_procedural_rig_cache(rig=None):
    """Invalidate cached cumulative sequence timing for one rig or all rigs.

    The historical function name is retained for internal compatibility, but
    this cache is also used by native image-sequence REC indicators. Remove all
    row-count variants for the same RNA object so structural edits cannot leave
    stale entries behind.
    """
    if rig is None:
        _FBP_PROCEDURAL_TIMING_CACHE.clear()
        return
    key = _fbp_procedural_rig_cache_key(rig)
    if not key or not key[0]:
        return
    identity = key[:2]
    for cached_key in tuple(_FBP_PROCEDURAL_TIMING_CACHE):
        try:
            if tuple(cached_key[:2]) == identity:
                _FBP_PROCEDURAL_TIMING_CACHE.pop(cached_key, None)
        except (TypeError, IndexError):
            _FBP_PROCEDURAL_TIMING_CACHE.pop(cached_key, None)


def fbp_clear_procedural_runtime_caches():
    """Drop pure-Python sequence caches before Undo, load or module teardown."""
    _FBP_PROCEDURAL_TIMING_CACHE.clear()
    _FBP_NATIVE_SCENE_RANGE_CACHE.clear()
    fbp_invalidate_procedural_scene_cache()


def _fbp_procedural_timing_is_dynamic(rig):
    """Return True only when duration values themselves are animated.

    Transform animation is common on FBP rigs and must not disable the timing
    cache. Only F-Curves/drivers targeting row durations or the global fallback
    duration require rebuilding the cumulative table every frame.
    """
    def affects_timing(curve):
        data_path = str(getattr(curve, "data_path", "") or "")
        return (
            data_path == "fbp_global_duration"
            or (data_path.startswith("fbp_images[") and data_path.endswith("].duration"))
        )

    try:
        animation_data = getattr(rig, "animation_data", None)
        if animation_data is None:
            return False
        curves = fbp_action_fcurves(rig)
        if curves is not None and any(affects_timing(curve) for curve in curves):
            return True
        if curves is None and getattr(animation_data, "action", None) is not None:
            # Unknown/unsupported Action layout: preserve correctness.
            return True
        return any(affects_timing(curve) for curve in (getattr(animation_data, "drivers", ()) or ()))
    except FBP_DATA_ERRORS:
        return True


def _fbp_build_procedural_timing(rig):
    items = getattr(rig, "fbp_images", ()) or ()
    count = len(items)
    if count <= 0:
        return None
    default_duration = max(1, int(getattr(rig, "fbp_global_duration", 1) or 1))
    durations = tuple(
        max(1, int(getattr(item, "duration", default_duration) or default_duration))
        for item in items
    )
    cumulative = []
    total = 0
    for duration in durations:
        total += duration
        cumulative.append(total)

    ping_indices = ()
    ping_cumulative = ()
    ping_total = total
    if count > 1:
        order = tuple(range(count)) + tuple(range(count - 2, 0, -1))
        ping_indices_list = []
        ping_cumulative_list = []
        ping_total = 0
        for index in order:
            ping_total += durations[index]
            ping_indices_list.append(index)
            ping_cumulative_list.append(ping_total)
        ping_indices = tuple(ping_indices_list)
        ping_cumulative = tuple(ping_cumulative_list)

    return {
        "count": count,
        "durations": durations,
        "cumulative": tuple(cumulative),
        "total": max(1, total),
        "ping_indices": ping_indices,
        "ping_cumulative": ping_cumulative,
        "ping_total": max(1, ping_total),
    }


def _fbp_procedural_timing(rig):
    """Return cumulative logical-row timing used by playback and REC UI."""
    if _fbp_procedural_timing_is_dynamic(rig):
        return _fbp_build_procedural_timing(rig)
    key = _fbp_procedural_rig_cache_key(rig)
    if not key or not key[0]:
        return _fbp_build_procedural_timing(rig)
    cached = _FBP_PROCEDURAL_TIMING_CACHE.get(key)
    if cached is not None:
        return cached
    timing = _fbp_build_procedural_timing(rig)
    if len(_FBP_PROCEDURAL_TIMING_CACHE) >= 512 and key not in _FBP_PROCEDURAL_TIMING_CACHE:
        _FBP_PROCEDURAL_TIMING_CACHE.clear()
    _FBP_PROCEDURAL_TIMING_CACHE[key] = timing
    return timing


def fbp_invalidate_procedural_scene_cache(scene=None):
    """Invalidate cached frame-handler state for one Scene or the whole Main."""
    cache = dict(fbp_runtime_get("fbp_procedural_scene_cache", {}) or {})
    if scene is None:
        cache.clear()
    else:
        scene_key = fbp_obj_runtime_key(scene)
        if scene_key is None:
            cache.clear()
        else:
            cache.pop(scene_key, None)
    fbp_runtime_set("fbp_procedural_scene_cache", cache)


def _fbp_scene_frame_state_cached(scene):
    """Cache the frame-handler state without retaining Blender RNA objects.

    Native ImageUser sequences do not need Python playback writes, but their
    moving REC marker still needs a Sidebar redraw. Keeping both flags in the
    existing short-lived scene cache avoids a full Scene scan on every frame.
    """
    if not scene:
        return False, False
    try:
        scene_key = fbp_obj_runtime_key(scene)
        object_count = len(scene.objects)
    except FBP_DATA_ERRORS:
        # A conservative result keeps playback/UI responsive while Blender is
        # replacing data during load or Undo.
        return True, True
    if scene_key is None:
        return True, True

    now = time.monotonic()
    cache = dict(fbp_runtime_get("fbp_procedural_scene_cache", {}) or {})
    entry = cache.get(scene_key, {})
    try:
        if (
            int(entry.get("object_count", -1)) == object_count
            and "rig_names" in entry
            and "has_frame_rows" in entry
            and now - float(entry.get("checked_at", 0.0) or 0.0)
            <= _FBP_PROCEDURAL_SCENE_CACHE_SECONDS
        ):
            return (
                bool(entry.get("has_procedural", False)),
                bool(entry.get("has_frame_rows", False)),
            )
    except (AttributeError, TypeError, ValueError):
        pass

    rig_names = []
    has_frame_rows = False
    for rig in iter_scene_fbp_rigs(scene):
        try:
            row_count = len(getattr(rig, "fbp_images", ()))
            if row_count > 1:
                has_frame_rows = True
            if fbp_rig_uses_procedural_color(rig) and row_count > 0:
                rig_names.append(str(getattr(rig, "name", "") or ""))
        except FBP_DATA_ERRORS:
            continue
    rig_names = tuple(name for name in rig_names if name)
    has_procedural = bool(rig_names)
    cache[scene_key] = {
        "object_count": object_count,
        "checked_at": now,
        "has_procedural": has_procedural,
        "has_frame_rows": has_frame_rows,
        "rig_names": rig_names,
    }
    # Bound cache growth across temporary Scenes without retaining RNA objects.
    if len(cache) > _FBP_PROCEDURAL_SCENE_CACHE_LIMIT:
        cache = dict(
            sorted(
                cache.items(),
                key=lambda item: item[1].get("checked_at", 0.0),
                reverse=True,
            )[:_FBP_PROCEDURAL_SCENE_CACHE_LIMIT]
        )
    fbp_runtime_set("fbp_procedural_scene_cache", cache)
    return has_procedural, has_frame_rows


def _fbp_scene_has_procedural_rows_cached(scene):
    """Return whether procedural rows require Python frame synchronization."""
    return _fbp_scene_frame_state_cached(scene)[0]


def _fbp_cached_procedural_scene_rigs(scene):
    """Resolve only procedural sequence rigs after the scene index is validated."""
    if not scene or not _fbp_scene_has_procedural_rows_cached(scene):
        return ()
    try:
        scene_key = fbp_obj_runtime_key(scene)
        cache = fbp_runtime_get("fbp_procedural_scene_cache", {}) or {}
        entry = cache.get(scene_key, {})
        names = tuple(entry.get("rig_names", ()) or ())
    except FBP_DATA_ERRORS:
        names = ()
    if not names:
        return ()
    rigs = []
    try:
        for name in names:
            rig = scene.objects.get(name)
            if rig is not None:
                rigs.append(rig)
    except FBP_DATA_ERRORS:
        fbp_invalidate_procedural_scene_cache(scene)
        return ()
    if len(rigs) != len(names):
        # A rig was renamed/deleted without changing Scene object count. Rebuild
        # once immediately so playback never skips another valid procedural rig.
        fbp_invalidate_procedural_scene_cache(scene)
        return tuple(
            rig for rig in iter_scene_fbp_rigs(scene)
            if fbp_rig_uses_procedural_color(rig)
            and len(getattr(rig, "fbp_images", ())) > 0
        )
    return tuple(rigs)


# ── CORE OPERATIONS ───────────────────────────────────────────────────────────


def fbp_rig_uses_procedural_color(rig):
    """Return whether the rig uses the current procedural color-plane workflow."""
    try:
        return bool(rig and getattr(rig, 'fbp_is_color_plane', False))
    except FBP_DATA_ERRORS:
        return False


def fbp_sequence_index_at_frame(rig, frame=None):
    """Evaluate the visible logical row using cumulative cached timing.

    The same evaluator drives procedural playback and the native-sequence REC
    marker. Static timing uses ``bisect`` over a precomputed cumulative table;
    duration edits and row mutations explicitly invalidate that table.
    """
    if frame is None:
        scene = _fbp_scene_for_rig(rig)
        frame = getattr(scene, "frame_current", 1)
    try:
        start = int(getattr(rig, "fbp_start_frame", 1))
        rel = int(frame) - start
    except FBP_DATA_ERRORS:
        rel = 0
    if rel < 0:
        return -1

    timing = _fbp_procedural_timing(rig)
    if not timing:
        return -1
    count = int(timing.get("count", 0) or 0)
    if count <= 0:
        return -1

    mode = str(getattr(rig, "fbp_loop_mode", "NONE") or "NONE")
    if mode == "PINGPONG" and count > 1:
        total = int(timing.get("ping_total", 1) or 1)
        local = rel % max(1, total)
        cumulative = timing.get("ping_cumulative", ()) or ()
        indices = timing.get("ping_indices", ()) or ()
        position = bisect_right(cumulative, local)
        if position >= len(indices):
            position = len(indices) - 1
        return int(indices[position]) if position >= 0 else 0

    total = int(timing.get("total", 1) or 1)
    local = rel % max(1, total) if mode == "REPEAT" else min(rel, total - 1)
    cumulative = timing.get("cumulative", ()) or ()
    index = bisect_right(cumulative, local)
    return max(0, min(index, count - 1))


def fbp_apply_procedural_color_frame(rig, frame=None):
    """Apply a procedural Color/Gradient frame material safely.

    A color plane without frame rows is a static procedural plane and must stay
    visible with material slot 0. A color/gradient/holdout plane with rows uses
    per-frame procedural material slots. Image layers stay native-only.
    """
    if not rig or not getattr(rig, 'fbp_is_color_plane', False):
        return False
    plane = getattr(rig, 'fbp_plane_target', None)
    if not plane or not getattr(plane, 'data', None):
        return False
    mesh = plane.data

    try:
        if not mesh.uv_layers:
            mesh.uv_layers.new(name='UVMap')
    except ReferenceError:
        return False
    except (AttributeError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError) as exc:
        fbp_warn_once(
            f"procedural_uv_setup:{getattr(rig, 'name', '<unknown>')}",
            "Could not create the procedural plane UV map",
            exc,
        )

    try:
        if len(mesh.materials) == 0 or mesh.materials[0] is None:
            fbp_rebuild_color_plane_material(rig)
    except ReferenceError:
        return False
    except (AttributeError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError) as exc:
        fbp_warn_once(
            f"procedural_material_rebuild:{getattr(rig, 'name', '<unknown>')}",
            "Could not rebuild the procedural plane material",
            exc,
        )

    try:
        if len(mesh.materials) == 0:
            return False
    except Exception:
        return False

    # Static Color / Gradient / Holdout plane: keep the single procedural material.
    if len(getattr(rig, 'fbp_images', [])) == 0:
        try:
            for poly in mesh.polygons:
                poly.material_index = 0
            mesh.update()
        except FBP_DATA_IO_ERRORS:
            pass
        visible = bool(getattr(rig, 'fbp_is_visible', True))
        try:
            hidden = not visible
            if not fbp_is_rendering_now() and bool(getattr(plane, "hide_viewport", False)) != hidden:
                plane.hide_viewport = hidden
        except FBP_DATA_IO_ERRORS:
            pass
        try:
            hidden = not visible
            if bool(getattr(plane, "hide_render", False)) != hidden:
                plane.hide_render = hidden
        except FBP_DATA_IO_ERRORS:
            pass
        return True

    idx = fbp_sequence_index_at_frame(rig, frame)
    visible = bool(getattr(rig, 'fbp_is_visible', True)) and idx >= 0
    try:
        hidden = not visible
        if not fbp_is_rendering_now() and bool(getattr(plane, "hide_viewport", False)) != hidden:
            plane.hide_viewport = hidden
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        hidden = not visible
        if bool(getattr(plane, "hide_render", False)) != hidden:
            plane.hide_render = hidden
    except FBP_DATA_IO_ERRORS:
        pass
    if idx < 0:
        return True

    try:
        idx = max(0, min(int(idx), len(mesh.materials) - 1))
        changed = False
        for poly in mesh.polygons:
            if poly.material_index != idx:
                poly.material_index = idx
                changed = True
        if changed:
            mesh.update()
        return True
    except Exception as exc:
        fbp_warn('Procedural Color Plane frame update skipped', exc)
        return False


def fbp_tag_view3d_ui_redraw():
    """Refresh Frame by Plane UI indicators that depend on the current frame."""
    try:
        wm = bpy.context.window_manager
        for window in getattr(wm, 'windows', []) or []:
            screen = getattr(window, 'screen', None)
            for area in getattr(screen, 'areas', []) or []:
                # Frame by Plane panels and current-frame indicators live in
                # the 3D View. Redrawing Timeline/Dopesheet areas every frame
                # adds work without updating any FBP-owned interface.
                if getattr(area, 'type', '') != 'VIEW_3D':
                    continue
                # Updating only the Sidebar avoids forcing a full 3D viewport
                # redraw on every frame while keeping FBP frame indicators live.
                ui_regions = [
                    region for region in (getattr(area, 'regions', ()) or ())
                    if getattr(region, 'type', '') == 'UI'
                ]
                if ui_regions:
                    for region in ui_regions:
                        region.tag_redraw()
                else:
                    # Defensive fallback for unusual/headless area layouts.
                    area.tag_redraw()
    except FBP_DATA_IO_ERRORS:
        pass


def fbp_update_sequence_scene(scene=None, frame=None):
    """Refresh procedural rows and report whether any require frame UI redraw."""
    scene = scene or getattr(bpy.context, 'scene', None)
    if not scene:
        return 0, False
    if frame is None:
        frame = getattr(scene, 'frame_current', 1)
    updated = 0
    procedural_rigs = _fbp_cached_procedural_scene_rigs(scene)
    has_procedural_rigs = bool(procedural_rigs)
    for obj in procedural_rigs:
        try:
            if not getattr(obj, 'is_fbp_control', False):
                continue
            if fbp_rig_uses_procedural_color(obj) and len(getattr(obj, 'fbp_images', [])) > 0:
                if fbp_apply_procedural_color_frame(obj, frame):
                    updated += 1
        except ReferenceError:
            continue
        except Exception as exc:
            fbp_warn_once(
                f"procedural_sequence_frame:{getattr(obj, 'name', 'unknown')}",
                "Sequence scene update skipped",
                exc,
            )
    try:
        scene_key = fbp_obj_runtime_key(scene)
        if scene_key is None:
            raise ValueError("Scene has no runtime identity")
        cache = dict(fbp_runtime_get("fbp_procedural_scene_cache", {}) or {})
        # Preserve the native-sequence REC/UI flag written by
        # ``_fbp_scene_frame_state_cached``. Replacing the entry without this
        # field made the next frame miss the cache and rescan every FBP rig.
        previous_entry = cache.get(scene_key, {})
        try:
            has_frame_rows_is_cached = "has_frame_rows" in previous_entry
            has_frame_rows = bool(previous_entry.get("has_frame_rows", False))
        except (AttributeError, TypeError, ValueError):
            has_frame_rows_is_cached = False
            has_frame_rows = False
        if not has_frame_rows_is_cached:
            # Direct callers may reach this updater before the frame-state
            # reader. Compute the flag once so the newly written entry never
            # suppresses REC redraw for native sequences.
            for rig in iter_scene_fbp_rigs(scene):
                try:
                    if len(getattr(rig, "fbp_images", ())) > 1:
                        has_frame_rows = True
                        break
                except FBP_DATA_ERRORS:
                    continue
        cache[scene_key] = {
            "object_count": len(scene.objects),
            "checked_at": time.monotonic(),
            "has_procedural": has_procedural_rigs,
            "has_frame_rows": has_frame_rows,
            "rig_names": tuple(
                str(getattr(rig, "name", "") or "")
                for rig in procedural_rigs
                if rig is not None
            ),
        }
        if len(cache) > _FBP_PROCEDURAL_SCENE_CACHE_LIMIT:
            cache = dict(
                sorted(
                    cache.items(),
                    key=lambda item: item[1].get("checked_at", 0.0),
                    reverse=True,
                )[:_FBP_PROCEDURAL_SCENE_CACHE_LIMIT]
            )
        fbp_runtime_set("fbp_procedural_scene_cache", cache)
    except FBP_DATA_ERRORS:
        pass
    return updated, has_procedural_rigs


def _fbp_scene_for_rig(rig, preferred=None):
    """Resolve the scene that owns a rig without relying on active context.

    ``Object.users_scene`` is the normal O(1)-sized ownership path. A complete
    ``bpy.data.scenes`` scan is retained only as a compatibility fallback for
    transient or older Blender states where ``users_scene`` is unavailable.
    """
    if rig is None:
        return preferred
    if preferred is not None:
        try:
            if preferred.objects.get(getattr(rig, 'name', '')) is rig:
                return preferred
        except FBP_DATA_ERRORS:
            pass
    try:
        owner_scenes = tuple(getattr(rig, 'users_scene', ()) or ())
    except FBP_DATA_ERRORS:
        owner_scenes = ()
    if owner_scenes:
        try:
            active = getattr(bpy.context, 'scene', None)
            if active is not None and any(scene == active for scene in owner_scenes):
                return active
        except FBP_DATA_ERRORS:
            pass
        return owner_scenes[0]
    try:
        for scene in bpy.data.scenes:
            if scene.objects.get(getattr(rig, 'name', '')) is rig:
                return scene
    except FBP_DATA_ERRORS:
        pass
    return preferred or getattr(bpy.context, 'scene', None)


def fbp_rebuild_sequence_backend_from_rig(rig):
    # Rebuild entry points are structural timing boundaries for every backend,
    # including native sequences whose REC marker is evaluated in Python.
    fbp_invalidate_procedural_rig_cache(rig)
    fbp_invalidate_procedural_scene_cache(_fbp_scene_for_rig(rig))
    if bool(getattr(rig, "fbp_is_drawing_plane", False)):
        try:
            from .drawing_plane import fbp_ensure_drawing_material, fbp_apply_drawing_index
            if not fbp_ensure_drawing_material(rig):
                return False
            return bool(
                fbp_apply_drawing_index(
                    rig,
                    _fbp_scene_for_rig(rig),
                    force=True,
                )
            )
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not rebuild Cutout Plane", exc)
            return False
    if fbp_rig_uses_procedural_color(rig):
        # Rebuild/refresh entry points are structural mutation boundaries, never
        # the per-frame hot path.
        scene = _fbp_scene_for_rig(rig)
        return fbp_apply_procedural_color_frame(rig, getattr(scene, 'frame_current', 1) if scene else 1)
    try:
        from . import native_backend
        return bool(native_backend.rebuild_native_sequence_from_rig(rig))
    except Exception as exc:
        fbp_warn("Could not rebuild Native Image Sequence", exc)
        return False


def fbp_refresh_sequence_backend_from_rig(rig):
    # Fast refreshes may follow duration edits, reorder operations or restored
    # snapshots. Discard stale logical timing before validating the backend.
    fbp_invalidate_procedural_rig_cache(rig)
    fbp_invalidate_procedural_scene_cache(_fbp_scene_for_rig(rig))
    if bool(getattr(rig, "fbp_is_drawing_plane", False)):
        try:
            from .drawing_plane import fbp_ensure_drawing_material, fbp_apply_drawing_index
            if not fbp_ensure_drawing_material(rig):
                return False
            fbp_apply_drawing_index(
                rig,
                _fbp_scene_for_rig(rig),
                force=True,
            )
            return True
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Cutout Plane refresh skipped", exc)
            return False
    if fbp_rig_uses_procedural_color(rig):
        scene = _fbp_scene_for_rig(rig)
        return fbp_apply_procedural_color_frame(rig, getattr(scene, 'frame_current', 1) if scene else 1)
    try:
        from . import native_backend
        if native_backend.fbp_refresh_native_sequence_from_rig(rig):
            return True
        return bool(native_backend.rebuild_native_sequence_from_rig(rig))
    except Exception as exc:
        fbp_warn("Native sequence refresh skipped", exc)
        return False


def fbp_replace_sequence_backend(rig, directory, files):
    if not rig or fbp_layer_backend_type(rig) not in {
        'NATIVE_IMAGE', 'NATIVE_SEQUENCE', 'NATIVE_MOVIE'
    }:
        return False
    files = [str(f) for f in (files or []) if f]
    if not files:
        return False
    try:
        from . import native_backend
        fbp_invalidate_procedural_rig_cache(rig)
        fbp_invalidate_procedural_scene_cache(_fbp_scene_for_rig(rig))
        replaced = bool(native_backend.replace_native_sequence(rig, directory, files))
        if replaced:
            fbp_invalidate_procedural_rig_cache(rig)
            fbp_invalidate_procedural_scene_cache(_fbp_scene_for_rig(rig))
            fbp_tag_view3d_ui_redraw()
        return replaced
    except Exception as exc:
        fbp_warn("Could not replace Native Image Sequence", exc)
        return False


def fbp_native_sequence_files_from_rig(rig):
    """Return the immutable source sequence used by a native image rig."""
    if (
        not rig
        or getattr(rig, "fbp_is_color_plane", False)
        or getattr(rig, "fbp_is_drawing_plane", False)
    ):
        return "", []
    try:
        from . import native_backend
        directory, files = native_backend.fbp_native_source_sequence_from_rig(rig)
        return (directory, list(files)) if directory and files else ("", [])
    except Exception as exc:
        fbp_warn("Could not read native source sequence metadata", exc)
        return "", []


def fbp_rig_native_sequence_needs_rename(rig):
    """True if the selected rig uses filenames that may fail as a native Image Sequence."""
    directory, files = fbp_native_sequence_files_from_rig(rig)
    if not directory or len(files) <= 1:
        return False
    try:
        from . import native_backend
        return bool(native_backend.fbp_rig_native_sequence_needs_rename(rig))
    except Exception as exc:
        fbp_warn("Could not check native sequence filenames", exc)
        return False


def do_update_animation(rig):
    """Refresh only the animation backend owned by this layer type."""
    if not rig or not getattr(rig, "is_fbp_control", False):
        return False

    # REC and frame-list indicators use the same logical timing table for every
    # sequence backend. Invalidate before backend-specific work so Duration,
    # Start, Playback and multi-edit changes are visible in the same UI beat.
    fbp_invalidate_procedural_rig_cache(rig)
    scene = _fbp_scene_for_rig(rig)
    fbp_invalidate_procedural_scene_cache(scene)
    backend = fbp_layer_backend_type(rig)

    if backend == 'CUTOUT':
        try:
            from .drawing_plane import fbp_update_drawing_index_ui, fbp_apply_drawing_index
            fbp_update_drawing_index_ui(rig)
            return bool(fbp_apply_drawing_index(rig, _fbp_scene_for_rig(rig), force=True))
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not refresh Cutout Plane", exc)
            return False

    if backend.startswith('PROCEDURAL_'):
        # Procedural planes use a small cumulative-duration cache and a material
        # slot switch. Native media and Cutout caches must remain untouched.
        frame = getattr(scene, 'frame_current', 1) if scene else 1
        return bool(fbp_apply_procedural_color_frame(rig, frame))

    if backend == 'NATIVE_IMAGE':
        # A still image has no timeline timing to rebuild. Keep texture settings
        # synchronized without touching media IDs, F-Curves or filesystem state.
        try:
            from .native_backend import fbp_sync_native_texture_settings
            return bool(fbp_sync_native_texture_settings(rig))
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not refresh Image Plane settings", exc)
            return False

    # Native image sequences and movies own their timing in ImageUser/F-Curves.
    # Unknown older layers retain the compatibility fallback through the same
    # strict backend bridge.
    return bool(fbp_refresh_sequence_backend_from_rig(rig))


def do_update_track(rig, context):
    cam = context.scene.camera
    if rig.fbp_track_cam and cam:
        cons = rig.constraints.get("FBP_Track")
        if not cons:
            cons = rig.constraints.new(type='DAMPED_TRACK')
            cons.name = "FBP_Track"
        cons.target = cam
        cons.track_axis = 'TRACK_Z'
    else:
        cons = rig.constraints.get("FBP_Track")
        if cons:
            rig.constraints.remove(cons)


# ── CAMERA DEPTH GETTER/SETTER ────────────────────────────────────────────────

def fbp_edit_targets(context, source_rig, *, same_type=False):
    """Return active + selected FBP rigs for live multi-edit callbacks."""
    if not source_rig or not is_fbp_layer_object(source_rig):
        return []
    targets = []
    seen = set()

    def add(rig):
        if not rig or not is_fbp_layer_object(rig):
            return
        if same_type and bool(getattr(rig, 'fbp_is_color_plane', False)) != bool(getattr(source_rig, 'fbp_is_color_plane', False)):
            return
        key = fbp_obj_runtime_key(rig) or getattr(rig, 'name', '')
        if key in seen:
            return
        seen.add(key)
        targets.append(rig)

    add(source_rig)
    try:
        if context:
            active_rig = fbp_resolve_rig_from_any_object(getattr(context, 'active_object', None), context)
            active_key = fbp_obj_runtime_key(active_rig) or getattr(active_rig, 'name', '')
            source_key = fbp_obj_runtime_key(source_rig) or getattr(source_rig, 'name', '')
            if active_key == source_key:
                for obj in getattr(context, 'selected_objects', []) or []:
                    add(fbp_resolve_rig_from_any_object(obj, context))
    except FBP_DATA_IO_ERRORS:
        pass
    return targets or [source_rig]


def _fbp_timing_family(rig):
    backend = fbp_layer_backend_type(rig)
    if backend == 'NATIVE_IMAGE':
        return 'STATIC_IMAGE'
    if backend == 'NATIVE_SEQUENCE':
        return 'IMAGE_SEQUENCE'
    if backend == 'NATIVE_MOVIE':
        return 'MOVIE'
    if backend in {'PROCEDURAL_COLOR', 'PROCEDURAL_GRADIENT'}:
        return 'PROCEDURAL_SEQUENCE'
    if backend == 'PROCEDURAL_HOLDOUT':
        return 'HOLDOUT'
    if backend == 'CUTOUT':
        return 'CUTOUT'
    return backend


def fbp_timing_edit_targets(context, source_rig):
    """Limit multi-edit timing changes to layers with compatible playback contracts."""
    family = _fbp_timing_family(source_rig)
    return [
        rig for rig in fbp_edit_targets(context, source_rig)
        if _fbp_timing_family(rig) == family
    ] or [source_rig]


def fbp_copy_registered_props_silent(target, source, prop_names):
    for prop_name in prop_names:
        try:
            fbp_set_rna_property_silent(target, prop_name, getattr(source, prop_name))
        except FBP_DATA_IO_ERRORS:
            pass


def fbp_refresh_active_procedural_preview(rig):
    """Refresh per-frame procedural metadata after a Color/Gradient/Holdout edit."""
    if not rig or not getattr(rig, 'fbp_is_color_plane', False):
        return False
    plane = getattr(rig, 'fbp_plane_target', None)
    if not plane or not getattr(plane, 'data', None) or not getattr(plane.data, 'materials', None):
        return False
    try:
        idx = int(getattr(rig, 'fbp_images_index', 0)) if len(getattr(rig, 'fbp_images', [])) else 0
        idx = max(0, min(idx, len(plane.data.materials) - 1))
    except Exception:
        idx = 0
    try:
        mat = plane.data.materials[idx]
    except Exception:
        mat = None
    if not mat:
        return False
    kind = fbp_procedural_kind_from_material(mat, getattr(rig, 'fbp_color_plane_mode', 'SOLID'))
    try:
        fbp_set_procedural_metadata(mat, kind)
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        if len(getattr(rig, 'fbp_images', [])) and 0 <= idx < len(rig.fbp_images):
            fbp_cache_procedural_preview_on_item(rig.fbp_images[idx], mat, kind)
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        if kind == 'GRADIENT':
            update_fbp_gradient_viewport_color(rig, mat)
    except FBP_DATA_IO_ERRORS:
        pass
    return True


def fbp_collection_item_owner_rig(item, procedural_only=False):
    """Return the Object ID that owns an Object.fbp_images row.

    CollectionProperty items inherit bpy_struct.id_data, so normal UI callbacks
    can resolve their parent rig directly instead of scanning every scene object.
    """
    if not item:
        return None
    try:
        rig = getattr(item, 'id_data', None)
    except ReferenceError:
        return None
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None
    if not rig or not getattr(rig, 'is_fbp_control', False):
        return None
    if procedural_only and not getattr(rig, 'fbp_is_color_plane', False):
        return None
    return rig


def fbp_collection_item_index(rig, item):
    """Return an item's index without scanning a large animation library."""
    if not rig or not item:
        return -1
    try:
        # Blender exposes the owning collection path directly for callbacks,
        # e.g. ``fbp_images[248]``. Parse and validate that fast path first.
        path = str(item.path_from_id() or '')
        marker = 'fbp_images['
        start = path.rfind(marker)
        if start >= 0:
            start += len(marker)
            end = path.find(']', start)
            if end > start:
                index = int(path[start:end])
                rows = getattr(rig, 'fbp_images', [])
                if 0 <= index < len(rows) and rows[index].as_pointer() == item.as_pointer():
                    return index

        # Older Blender/runtime edge cases may not expose path_from_id while an
        # item is being moved. Keep the pointer scan as a correctness fallback.
        target_ptr = item.as_pointer()
        for index, row in enumerate(getattr(rig, 'fbp_images', [])):
            if row.as_pointer() == target_ptr:
                return index
    except ReferenceError:
        return -1
    except (AttributeError, RuntimeError, TypeError, ValueError, IndexError):
        return -1
    return -1


def fbp_find_rig_for_procedural_frame_item(item, context=None):
    """Return ``(rig, index)`` for a procedural frame UIList item."""
    if not item:
        return None, -1
    owner = fbp_collection_item_owner_rig(item, procedural_only=True)
    owner_index = fbp_collection_item_index(owner, item)
    return (owner, owner_index) if owner and owner_index >= 0 else (None, -1)


def fbp_set_solid_material_color(mat, color):
    """Update a procedural solid material in-place from a UIList color edit."""
    if not mat:
        return False
    color = tuple(float(v) for v in color[:4])
    try:
        mat.diffuse_color = color
        mat['fbp_color_value'] = color
        mat['fbp_procedural_kind'] = 'SOLID'
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        if getattr(mat, 'use_nodes', False) and getattr(mat, 'node_tree', None):
            for node in mat.node_tree.nodes:
                if getattr(node, 'type', None) == 'EMISSION':
                    sock = safe_get_socket(node, ['color']) or node.inputs[0]
                    sock.default_value = color
                elif getattr(node, 'type', None) == 'BSDF_PRINCIPLED':
                    base = safe_get_socket(node, ['base', 'color']) or node.inputs[0]
                    base.default_value = color
                    alpha = safe_get_socket(node, ['alpha'])
                    if alpha:
                        alpha.default_value = color[3]
                elif getattr(node, 'type', None) == 'MIX_SHADER':
                    try:
                        node.inputs[0].default_value = color[3]
                    except FBP_DATA_IO_ERRORS:
                        pass
        configure_fbp_material_surface(mat, color[3], has_alpha=color[3] < 0.999)
    except Exception as exc:
        fbp_warn('Could not update procedural color material from UIList', exc)
    return True


def update_frame_preview_color_cb(self, context):
    """Write UIList color edits back to the owning procedural frame material."""
    try:
        ptr = self.as_pointer()
    except Exception:
        ptr = None
    if ptr is not None and ptr in _FBP_SYNCING_PROCEDURAL_PREVIEW_ITEMS:
        return
    try:
        rig, index = fbp_find_rig_for_procedural_frame_item(self, context)
        if not rig or index < 0:
            return
        plane = getattr(rig, 'fbp_plane_target', None)
        if not plane or not getattr(plane, 'data', None) or index >= len(plane.data.materials):
            return
        mat = plane.data.materials[index]
        if not mat:
            return
        kind = fbp_procedural_kind_for_item(rig, index, getattr(self, 'procedural_kind', 'SOLID'))
        if kind == 'GRADIENT':
            color_a = tuple(getattr(self, 'preview_color_a', (1.0, 1.0, 1.0, 1.0)))
            color_b = tuple(getattr(self, 'preview_color_b', (1.0, 1.0, 1.0, 1.0)))
            ramp = find_fbp_gradient_ramp_node(mat)
            elems = list(getattr(getattr(ramp, 'color_ramp', None), 'elements', [])) if ramp else []
            if elems:
                elems[0].color = color_a
                elems[-1].color = color_b
            try:
                mat.diffuse_color = color_b
                mat['fbp_procedural_kind'] = 'GRADIENT'
            except FBP_DATA_IO_ERRORS:
                pass
            update_fbp_gradient_viewport_color(rig, mat)
            if int(getattr(rig, 'fbp_images_index', -1)) == index:
                fbp_set_rna_property_silent(rig, 'fbp_gradient_color_a', color_a)
                fbp_set_rna_property_silent(rig, 'fbp_gradient_color_b', color_b)
        elif kind == 'SOLID':
            color = tuple(getattr(self, 'preview_color_a', (1.0, 1.0, 1.0, 1.0)))
            fbp_set_solid_material_color(mat, color)
            if int(getattr(rig, 'fbp_images_index', -1)) == index:
                fbp_set_rna_property_silent(rig, 'fbp_color_plane_color', color)
        if int(getattr(rig, 'fbp_images_index', -1)) == index:
            fbp_apply_procedural_color_frame(rig, getattr(_fbp_scene_for_rig(rig), 'frame_current', None))
    except ReferenceError:
        return
    except Exception as exc:
        fbp_warn('Could not apply UIList color edit', exc)


# ── UPDATE CALLBACKS ──────────────────────────────────────────────────────────

def update_object_padding_cb(self, context):
    # Live-update Crop / Extend on the active rig, and copy to selected rigs.
    if not is_fbp_layer_object(self):
        return
    props = (
        'fbp_extend_left', 'fbp_extend_right', 'fbp_extend_bottom', 'fbp_extend_top',
        'fbp_crop_left', 'fbp_crop_right', 'fbp_crop_bottom', 'fbp_crop_top',
    )
    try:
        for rig in fbp_edit_targets(context, self):
            if rig != self:
                fbp_copy_registered_props_silent(rig, self, props)
            set_plane_mesh_extension(
                rig,
                getattr(rig, 'fbp_extend_left', 0.0), getattr(rig, 'fbp_extend_right', 0.0),
                getattr(rig, 'fbp_extend_bottom', 0.0), getattr(rig, 'fbp_extend_top', 0.0),
                getattr(rig, 'fbp_extend_mode', 'EDGE'),
                getattr(rig, 'fbp_crop_left', 0.0), getattr(rig, 'fbp_crop_right', 0.0),
                getattr(rig, 'fbp_crop_bottom', 0.0), getattr(rig, 'fbp_crop_top', 0.0),
            )
            try:
                from .object_masks import sync_owner_object_mask_helpers
                sync_owner_object_mask_helpers(rig)
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
            try:
                from .geometry_nodes import fbp_refresh_aspect_dependent_effect_grids
                fbp_refresh_aspect_dependent_effect_grids(rig)
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
            try:
                from .effect_controls import schedule_active_effect_controls, sync_crop_extend_bounds_guide
                sync_crop_extend_bounds_guide(rig)
                schedule_active_effect_controls(context)
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
            try:
                from .geometry_nodes import fbp_sync_mattes_for_source_bounds
                fbp_sync_mattes_for_source_bounds(
                    rig,
                    scene=_fbp_scene_for_rig(
                        rig, preferred=getattr(context, 'scene', None)
                    ),
                )
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
    except Exception as exc:
        fbp_warn("Plane Crop / Extend update skipped", exc)


def update_extend_mode_cb(self, context):
    """Update geometry plus texture wrapping only when the mode changes."""
    if fbp_is_silent_property_update(self) or not is_fbp_layer_object(self):
        return
    update_object_padding_cb(self, context)
    value = str(getattr(self, 'fbp_extend_mode', 'EDGE') or 'EDGE')
    for rig in fbp_edit_targets(context, self):
        backend = fbp_layer_backend_type(rig)
        if backend not in {'NATIVE_IMAGE', 'NATIVE_SEQUENCE', 'NATIVE_MOVIE', 'CUTOUT'}:
            continue
        if rig != self:
            fbp_set_rna_property_silent(rig, 'fbp_extend_mode', value)
        try:
            if backend.startswith('NATIVE_'):
                from .native_backend import fbp_sync_native_texture_settings
                if not fbp_sync_native_texture_settings(rig):
                    fbp_refresh_sequence_backend_from_rig(rig)
            elif backend == 'CUTOUT':
                from .drawing_plane import fbp_sync_drawing_texture_settings
                fbp_sync_drawing_texture_settings(rig)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Plane texture extension update skipped", exc)


def update_loop_mode_cb(self, context):
    if fbp_is_silent_property_update(self):
        return
    targets = fbp_timing_edit_targets(context, self)
    value = str(getattr(self, "fbp_loop_mode", 'NONE'))
    for rig in targets:
        if rig != self:
            fbp_set_rna_property_silent(rig, "fbp_loop_mode", value)
    for rig in targets:
        do_update_animation(rig)
    fbp_tag_view3d_ui_redraw()


def update_start_frame_cb(self, context):
    if fbp_is_silent_property_update(self):
        return
    targets = fbp_timing_edit_targets(context, self)
    value = int(getattr(self, "fbp_start_frame", 1))
    for rig in targets:
        if rig != self:
            fbp_set_rna_property_silent(rig, "fbp_start_frame", value)
    for rig in targets:
        do_update_animation(rig)
    fbp_tag_view3d_ui_redraw()

def update_emission_cb(self, context):
    if fbp_is_silent_property_update(self):
        return
    targets = fbp_edit_targets(context, self)
    value = bool(getattr(self, "fbp_use_emission", False))
    for rig in targets:
        if rig != self:
            fbp_set_rna_property_silent(rig, "fbp_use_emission", value)
    for rig in targets:
        do_update_emission(rig)


def update_opacity_cb(self, context):
    if fbp_is_silent_property_update(self):
        return
    targets = fbp_edit_targets(context, self)
    value = float(getattr(self, "fbp_opacity", 1.0))
    for rig in targets:
        if rig != self:
            fbp_set_rna_property_silent(rig, "fbp_opacity", value)
    for rig in targets:
        do_update_opacity(rig)


def update_track_cb(self, context):
    if fbp_is_silent_property_update(self):
        return
    targets = fbp_edit_targets(context, self)
    value = bool(getattr(self, "fbp_track_cam", False))
    for rig in targets:
        if rig != self:
            fbp_set_rna_property_silent(rig, "fbp_track_cam", value)
    for rig in targets:
        do_update_track(rig, context)

def update_global_duration_cb(self, context):
    if fbp_is_silent_property_update(self):
        return

    global _FBP_SUPPRESS_IMAGE_DURATION_CB
    previous_suppression = _FBP_SUPPRESS_IMAGE_DURATION_CB
    target_value = max(1, int(getattr(self, "fbp_global_duration", 1)))
    targets = fbp_timing_edit_targets(context, self)
    multi_rig = len(targets) > 1
    eligible_targets = []
    changed_rigs = []

    try:
        _FBP_SUPPRESS_IMAGE_DURATION_CB = True
        for rig in targets:
            backend_type = fbp_layer_backend_type(rig)
            if backend_type in {'NATIVE_MOVIE', 'CUTOUT', 'PROCEDURAL_HOLDOUT'}:
                continue
            eligible_targets.append(rig)
            if rig != self:
                fbp_set_rna_property_silent(rig, "fbp_global_duration", target_value)

            items = list(getattr(rig, "fbp_images", []) or [])
            if multi_rig:
                edit_items = items
            else:
                checked = [item for item in items if bool(getattr(item, "is_selected", False))]
                edit_items = checked or items

            changed = False
            for item in edit_items:
                try:
                    if int(getattr(item, "duration", 1)) != target_value:
                        item.duration = target_value
                        changed = True
                except FBP_DATA_IO_ERRORS:
                    pass
            if changed or rig == self or multi_rig:
                changed_rigs.append(rig)
    except Exception as exc:
        fbp_warn("Could not apply frame duration to selected layers", exc)
    finally:
        _FBP_SUPPRESS_IMAGE_DURATION_CB = previous_suppression

    for rig in changed_rigs or eligible_targets:
        do_update_animation(rig)
    if changed_rigs or eligible_targets:
        fbp_tag_view3d_ui_redraw()


def fbp_find_rig_for_image_item(image_item, context=None):
    """Return the owning FBP rig for a current ``Object.fbp_images`` row."""
    if image_item is None:
        return None
    owner = fbp_collection_item_owner_rig(image_item)
    return owner if owner and fbp_collection_item_index(owner, image_item) >= 0 else None


def update_image_duration_cb(self, context):
    """Live-update only backends whose rows own timeline durations."""
    if _FBP_SUPPRESS_IMAGE_DURATION_CB or fbp_is_silent_property_update(self):
        return
    try:
        rig = fbp_find_rig_for_image_item(self, context)
        if not rig:
            return
        backend = fbp_layer_backend_type(rig)
        if backend not in {'NATIVE_SEQUENCE', 'PROCEDURAL_COLOR', 'PROCEDURAL_GRADIENT'}:
            return
        do_update_animation(rig)
        fbp_tag_view3d_ui_redraw()
    except Exception as exc:
        fbp_warn("Image row duration update skipped", exc)


def update_visibility_cb(self, context):
    if fbp_is_silent_property_update(self):
        return
    targets = fbp_edit_targets(context, self)
    value = bool(getattr(self, "fbp_is_visible", True))
    for rig in targets:
        if rig != self:
            fbp_set_rna_property_silent(rig, "fbp_is_visible", value)
    # Visibility edits affect only the selected targets. Avoid walking every
    # Scene layer for a single eye click; collection/solo tools still use the
    # explicit global refresh path when their state spans the whole project.
    for rig in targets:
        update_rig_visibility(rig, context=context)
    fbp_clear_collection_ui_state_cache()

def fbp_color_targets_for_update(context, source_rig):
    """Return rigs that should receive a layer color change from the N-Panel.

    Color changes respect the current Layer Stack selection.
    If a collection row was selected, its recursive layer selection is already
    represented by Scene.fbp_layers[*].selected, so this also colors all layers
    inside the selected collection instead of only the active/first rig.
    """
    if not context or not source_rig or not is_fbp_layer_object(source_rig):
        return []
    scene = getattr(context, 'scene', None)
    if not scene:
        return [source_rig]

    targets = []
    seen = set()

    def add_rig(rig):
        if not rig or not is_fbp_layer_object(rig):
            return
        name = getattr(rig, 'name', '')
        if not name or name in seen:
            return
        seen.add(name)
        targets.append(rig)

    # Main path: selected layer rows in the UIList / Layer Stack.
    try:
        for item in scene.fbp_layers:
            if bool(getattr(item, 'selected', False)):
                add_rig(getattr(item, 'obj', None))
    except FBP_DATA_IO_ERRORS:
        pass

    # If the active rig is part of a fully selected collection, force-recursive
    # targets. This covers the user workflow: select collection -> change color
    # from the selected layer/N-Panel.
    try:
        coll = get_primary_fbp_collection(source_rig)
        if coll and bool(getattr(coll, 'fbp_collection_selected', False)):
            for rig in iter_fbp_rigs_in_collection(coll, True):
                add_rig(rig)
    except FBP_DATA_IO_ERRORS:
        pass

    # Fallback: selected Blender objects, useful when the user selected layers in
    # the viewport/Outliner rather than the UIList.
    try:
        for obj in getattr(context, 'selected_objects', []):
            add_rig(fbp_resolve_rig_from_any_object(obj, context))
    except FBP_DATA_IO_ERRORS:
        pass

    if not targets:
        add_rig(source_rig)
    elif source_rig not in targets:
        # Keep source first for predictable collection push behavior.
        targets.insert(0, source_rig)
    return targets


def fbp_apply_color_tag_to_targets(context, source_rig, color_tag):
    """Apply a color tag to selected layer targets without recursive callbacks."""
    if color_tag not in STRIP_COLORS_DICT:
        return False
    targets = fbp_color_targets_for_update(context, source_rig)
    if not targets:
        return False

    # Count variants per collection so sibling layers remain visually readable.
    counters = {}
    for rig in targets:
        try:
            coll = get_primary_fbp_collection(rig)
            key = getattr(coll, 'name', '') if coll else '__scene__'
            idx = counters.get(key, 0)
            counters[key] = idx + 1
            fbp_set_rna_property_silent(rig, 'fbp_color_tag', color_tag)
            fbp_set_rna_property_silent(rig, 'fbp_color_variant_index', idx)
            apply_collection_color_to_layer(
                rig,
                color_tag,
                idx,
                push_collection=bool(coll and getattr(rig, 'fbp_follow_collection_color', True))
            )
        except ReferenceError:
            pass
        except Exception as exc:
            fbp_warn('Could not apply bulk layer color tag', exc)
    return True


def update_color_tag_cb(self, context):
    if fbp_is_silent_property_update(self):
        return
    if is_fbp_layer_object(self):
        # Apply selected layer color changes to all selected layers or the selected collection.
        if fbp_apply_color_tag_to_targets(context, self, self.fbp_color_tag):
            return
        apply_collection_color_to_layer(
            self,
            self.fbp_color_tag,
            getattr(self, "fbp_color_variant_index", 0),
            push_collection=getattr(self, "fbp_follow_collection_color", True)
        )

def update_interpolation_cb(self, context):
    """Update image filtering without rebuilding timing or media datablocks."""
    if fbp_is_silent_property_update(self) or not is_fbp_layer_object(self):
        return
    value = str(getattr(self, 'fbp_interpolation', 'Closest') or 'Closest')
    try:
        for rig in fbp_edit_targets(context, self):
            backend = fbp_layer_backend_type(rig)
            if backend not in {'NATIVE_IMAGE', 'NATIVE_SEQUENCE', 'NATIVE_MOVIE', 'CUTOUT'}:
                continue
            if rig != self:
                fbp_set_rna_property_silent(rig, 'fbp_interpolation', value)
            if backend.startswith('NATIVE_'):
                from .native_backend import fbp_sync_native_texture_settings
                if not fbp_sync_native_texture_settings(rig):
                    fbp_refresh_sequence_backend_from_rig(rig)
            elif backend == 'CUTOUT':
                from .drawing_plane import fbp_sync_drawing_texture_settings
                fbp_sync_drawing_texture_settings(rig)
    except Exception as exc:
        fbp_warn('Image interpolation update skipped', exc)


def update_image_index_cb(self, context):
    if fbp_is_silent_property_update(self):
        return
    if not getattr(self, "is_fbp_control", False):
        return
    backend = fbp_layer_backend_type(self)
    if backend == 'CUTOUT':
        try:
            from .drawing_plane import fbp_select_drawing_from_list
            fbp_select_drawing_from_list(self, context)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not select Cutout Plane entry", exc)
        return
    if backend.startswith('PROCEDURAL_'):
        # Selecting a procedural row changes the editable UI controls only. The
        # visible material remains driven by timeline timing.
        fbp_load_active_procedural_frame_to_rig(self)
        return
    # Native sequence row selection is UI-only. Rebuilding ImageUser timing here
    # made list navigation perform filesystem checks and F-Curve validation.

def update_layer_stack_index_cb(self, context):
    try:
        idx = self.fbp_layer_stack_index
        if 0 <= idx < len(self.fbp_layers):
            obj = self.fbp_layers[idx].obj
            if obj and is_fbp_layer_object(obj):
                if context.view_layer.objects.active != obj:
                    # Keep previous selections alive so the layer list can support multi-select painting.
                    obj.select_set(True)
                    context.view_layer.objects.active = obj
    except Exception as exc:
        fbp_warn("Layer stack selection update skipped", exc)

def apply_camera_ratio_settings(scene):
    # Apply selected output ratio before camera or camera-ratio plane creation.
    if not scene:
        return
    ratio = getattr(scene, 'fbp_cam_ratio', '4_3')
    presets = {
        'HD_16_9': (1920, 1080), 'UHD_4K': (3840, 2160), '16_9': (1920, 1080),
        'STORY_9_16': (1080, 1920), '9_16': (1080, 1920), '4_3': (1920, 1440),
        '3_4': (1440, 1920), '1_1': (2000, 2000), '5_4': (2000, 1600),
        '16_10': (1920, 1200), 'PHOTO_3_2': (3000, 2000), 'PHOTO_2_3': (2000, 3000),
        'CINEMA_185': (1850, 1000), 'CINEMA_239': (2390, 1000), 'TWO_1': (2000, 1000),
        'ULTRAWIDE_21_9': (2520, 1080), 'A4_LANDSCAPE': (2480, 1754), 'A4_PORTRAIT': (1754, 2480),
    }
    if ratio in presets:
        scene.render.resolution_x, scene.render.resolution_y = presets[ratio]


# ── RENDER STABILITY HELPERS ─────────────────────────────────────────────────

def fbp_is_rendering_now():
    """Return True unless Blender is confirmed idle for datablock mutation."""
    return fbp_render_mutation_blocked()


def _fbp_scene_is_native_render_passthrough(scene):
    """Return True when Blender can render FBP planes without add-on writes.

    A scene containing only native Image/Sequence planes and no active effects
    should follow the same render path as Blender's Images as Planes workflow.
    Keep the render guard active only as a pause flag for timers/handlers, but do
    not touch visibility, node trees, modifiers, images or RenderSettings.
    """
    if not scene:
        return True
    try:
        from .geometry_nodes import fbp_effect_ids_for_rig
        from .native_backend import fbp_native_rig_render_ready
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        fbp_effect_ids_for_rig = None
        fbp_native_rig_render_ready = None

    for rig in iter_scene_fbp_rigs(scene):
        try:
            if not bool(getattr(rig, "is_fbp_control", False)):
                continue
            if fbp_rig_uses_procedural_color(rig):
                return False
            if bool(getattr(rig, "fbp_is_drawing_plane", False)):
                return False
            plane = getattr(rig, "fbp_plane_target", None)
            if not plane or not getattr(plane, "data", None):
                return False
            if fbp_effect_ids_for_rig is None or fbp_native_rig_render_ready is None:
                return False
            if tuple(fbp_effect_ids_for_rig(rig) or ()):
                return False
            # Render pass-through is allowed only for the exact current native
            # contract. This is a structural check: it avoids full disk scans in
            # render_init while still rejecting stale node/F-Curve/material state.
            if not fbp_native_rig_render_ready(rig, check_files=False):
                return False
        except FBP_DATA_ERRORS:
            return False
    return True


def _fbp_clear_render_runtime_state():
    """Clear render-session flags without dereferencing Blender datablocks."""
    for key, value in (
        ("fbp_render_guard_active", False),
        ("fbp_render_end_requested", False),
        ("fbp_render_end_requested_at", 0.0),
        ("fbp_render_session_mode", ""),
        ("fbp_render_needs_procedural_frame_sync", False),
        ("fbp_render_needs_drawing_frame_sync", False),
        ("fbp_render_needs_effect_frame_sync", False),
        ("fbp_render_lock_interface_previous", None),
        ("fbp_render_scene_name", ""),
        ("fbp_render_scene_key", None),
        ("fbp_render_scene_pointer", None),
        ("fbp_render_started_at", 0.0),
        ("fbp_render_restore_failures", 0),
        ("fbp_render_viewport_hidden_planes", {}),
        ("fbp_effect_render_backup", []),
    ):
        fbp_runtime_set(key, value)

def _fbp_scene_needs_procedural_render_sync(scene):
    """Return whether render frames must swap procedural Color/Gradient rows."""
    for rig in iter_scene_fbp_rigs(scene):
        try:
            if (
                bool(getattr(rig, "is_fbp_control", False))
                and fbp_rig_uses_procedural_color(rig)
                and len(getattr(rig, "fbp_images", ())) > 0
            ):
                return True
        except FBP_DATA_ERRORS:
            # Unknown procedural state must keep the managed render path active.
            # A false negative here disables the only per-frame material swap.
            return True
    return False


def _fbp_scene_needs_drawing_render_sync(scene):
    """Return whether Cutout Plane images must be swapped for render frames."""
    try:
        from .drawing_plane import fbp_scene_has_drawing_planes
        return bool(fbp_scene_has_drawing_planes(scene))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        # Unknown state must keep the managed render path active. A false
        # negative would render the image left over from the viewport frame.
        return True


def _fbp_scene_needs_effect_render_sync(scene):
    """Ask the effect system whether any active stack needs Python per frame."""
    try:
        from .geometry_nodes import fbp_scene_requires_effect_frame_sync
        return bool(fbp_scene_requires_effect_frame_sync(scene))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        # Prefer a harmless managed/locked render over silently skipping effect
        # synchronization when the preflight cannot prove that no writes occur.
        return True


def fbp_ensure_plane_render_safe(rig, frame=None):
    """Validate render state for the selected sequence backend."""
    if not rig or not getattr(rig, "is_fbp_control", False):
        return False
    plane = getattr(rig, "fbp_plane_target", None)
    if not plane or not getattr(plane, "data", None):
        return False
    mesh = plane.data

    if fbp_rig_uses_procedural_color(rig):
        return fbp_apply_procedural_color_frame(rig, frame)

    if bool(getattr(rig, "fbp_is_drawing_plane", False)):
        try:
            from .drawing_plane import (
                fbp_apply_drawing_index,
                fbp_drawing_render_ready,
                fbp_ensure_drawing_material,
            )
            if not fbp_drawing_render_ready(rig):
                if fbp_is_rendering_now() or not fbp_ensure_drawing_material(rig):
                    return False
            if not fbp_drawing_render_ready(rig):
                return False
            fbp_apply_drawing_index(rig, getattr(bpy.context, "scene", None), force=True)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return False
        try:
            return bool(len(mesh.materials) > 0 and ensure_fbp_plane_material_integrity(rig))
        except FBP_DATA_ERRORS:
            return False

    try:
        from .native_backend import fbp_native_rig_contract_issues
        native_issues = fbp_native_rig_contract_issues(rig)
        if native_issues and not fbp_is_rendering_now():
            # Repair before a render job starts, never from an active render
            # callback or dependency-graph evaluation.
            if fbp_refresh_sequence_backend_from_rig(rig):
                native_issues = fbp_native_rig_contract_issues(rig)
        if native_issues:
            fbp_warn_once(
                f"native_render_contract:{getattr(rig, 'name', 'unknown')}",
                "Native render contract is not ready: " + "; ".join(native_issues[:3]),
            )
            return False
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not validate native render contract", exc)
        return False

    try:
        if len(mesh.materials) == 0:
            return False
        if not ensure_fbp_plane_material_integrity(rig):
            return False
    except FBP_DATA_ERRORS:
        return False

    try:
        if not mesh.uv_layers:
            mesh.uv_layers.new(name="UVMap")
    except FBP_DATA_IO_ERRORS:
        pass

    try:
        plane.hide_render = not bool(getattr(rig, "fbp_is_visible", True))
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        from .geometry_nodes import fbp_apply_matte_source_visibility
        fbp_apply_matte_source_visibility(
            rig, scene=getattr(bpy.context, "scene", None), restore_normal=False
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    return True


def fbp_repair_all_render_state(scene=None, frame=None):
    scene = scene or bpy.context.scene
    fixed = 0
    for obj in iter_scene_fbp_rigs(scene):
        try:
            if getattr(obj, "is_fbp_control", False):
                if fbp_ensure_plane_render_safe(obj, frame):
                    fixed += 1
                try:
                    obj.hide_render = True
                except (ReferenceError, RuntimeError):
                    pass
        except ReferenceError:
            pass
    return fixed


def fbp_render_visibility_guard(scene):
    """Apply render visibility once for the whole render job.

    The old implementation restored this state from ``render_post`` after every
    animation frame, forcing repeated depsgraph rebuilds while the next frame was
    already being prepared. The session guard now mutates it only at job start.
    """
    if not scene:
        return 0
    changed = 0
    viewport_backup = {}
    for obj in iter_scene_fbp_rigs(scene):
        try:
            if not getattr(obj, "is_fbp_control", False):
                continue
            if not obj.hide_render:
                obj.hide_render = True
                changed += 1
            plane = getattr(obj, "fbp_plane_target", None)
            if plane and getattr(plane, "is_fbp_plane", False):
                target_hide = not bool(getattr(obj, "fbp_is_visible", True))
                if plane.hide_render != target_hide:
                    plane.hide_render = target_hide
                    changed += 1
                try:
                    from .geometry_nodes import fbp_apply_matte_source_visibility
                    changed += int(bool(fbp_apply_matte_source_visibility(
                        obj, scene=scene, restore_normal=False
                    )))
                except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
                if getattr(obj, "fbp_is_color_plane", False):
                    viewport_backup[plane.name] = {
                        "object_key": fbp_obj_runtime_key(plane),
                        "hide_viewport": bool(getattr(plane, "hide_viewport", False)),
                    }
                    if not plane.hide_viewport:
                        plane.hide_viewport = True
                        changed += 1
        except ReferenceError:
            continue
        except (AttributeError, TypeError, RuntimeError) as exc:
            fbp_warn("Render visibility guard skipped object", exc)
    fbp_runtime_set("fbp_render_viewport_hidden_planes", viewport_backup)
    return changed


def _fbp_render_session_scene(scene=None):
    """Resolve the Scene that owned the active render session without stale RNA."""
    stored_name = str(fbp_runtime_get("fbp_render_scene_name", "") or "")
    stored_key = fbp_runtime_get("fbp_render_scene_key", None)
    if stored_key is not None:
        if scene is not None and fbp_obj_runtime_key(scene) == stored_key:
            return scene
        return fbp_find_id_by_runtime_key(
            bpy.data.scenes, stored_key, stored_name
        )

    # Compatibility with a render session started before a live add-on reload.
    legacy_pointer = fbp_runtime_get("fbp_render_scene_pointer", None)
    if legacy_pointer is None:
        return scene or (bpy.data.scenes.get(stored_name) if stored_name else None)
    candidate = scene or (bpy.data.scenes.get(stored_name) if stored_name else None)
    try:
        if candidate is not None and int(candidate.as_pointer()) == int(legacy_pointer):
            return candidate
        return next(
            (item for item in bpy.data.scenes
             if int(item.as_pointer()) == int(legacy_pointer)),
            None,
        )
    except FBP_DATA_ERRORS:
        return None


def _fbp_restore_render_session_state(scene=None):
    """Restore one completed/cancelled render session from Blender's idle loop.

    Temporary RuntimeError failures remain queued so the watchdog can retry after
    Blender fully releases render-owned node/modifier data. Invalid or deleted
    datablocks are discarded because they can no longer be restored safely.
    """
    if not bool(fbp_runtime_get("fbp_render_guard_active", False)):
        return False
    mode = str(fbp_runtime_get("fbp_render_session_mode", "") or "")
    if mode == "NATIVE_PASSTHROUGH":
        # Native sessions never changed Blender data. Keep the guard alive until
        # Blender's render job is genuinely idle, then clear only Python state.
        _fbp_clear_render_runtime_state()
        return True

    scene = _fbp_render_session_scene(scene)
    restore_pending = False

    backup = fbp_runtime_get("fbp_render_viewport_hidden_planes", {}) or {}
    remaining_viewport = {}
    for name, stored in list(backup.items()):
        try:
            obj = bpy.data.objects.get(name)
            if not obj:
                continue
            if isinstance(stored, dict):
                if fbp_obj_runtime_key(obj) != stored.get("object_key"):
                    continue
                was_hidden = bool(stored.get("hide_viewport", False))
            else:
                was_hidden = bool(stored)
            obj.hide_viewport = was_hidden
        except RuntimeError:
            remaining_viewport[name] = stored
            restore_pending = True
        except (AttributeError, ReferenceError, TypeError, ValueError):
            continue
    fbp_runtime_set("fbp_render_viewport_hidden_planes", remaining_viewport)

    effect_backup = fbp_runtime_get("fbp_effect_render_backup", []) or []
    remaining_effects = []
    if effect_backup:
        try:
            from .geometry_nodes import fbp_effect_render_guard_post
            remaining_effects = list(
                fbp_effect_render_guard_post(effect_backup) or ()
            )
        except RuntimeError:
            remaining_effects = list(effect_backup)
        except (ImportError, AttributeError, ReferenceError, TypeError, ValueError) as exc:
            # Module reload can briefly make the restore helper unavailable.
            # Keep the backup for a later idle retry instead of losing it.
            fbp_warn("Could not restore effect state after render", exc)
            remaining_effects = list(effect_backup)
    if remaining_effects:
        restore_pending = True
    fbp_runtime_set("fbp_effect_render_backup", remaining_effects)

    render = getattr(scene, "render", None) if scene else None
    previous_lock = fbp_runtime_get("fbp_render_lock_interface_previous", None)
    if render is not None and previous_lock is not None:
        try:
            render.use_lock_interface = bool(previous_lock)
            fbp_runtime_set("fbp_render_lock_interface_previous", None)
        except RuntimeError:
            restore_pending = True
        except (AttributeError, ReferenceError, TypeError, ValueError):
            fbp_runtime_set("fbp_render_lock_interface_previous", None)
    elif render is None:
        # The owning Scene was removed; there is no remaining datablock to restore.
        fbp_runtime_set("fbp_render_lock_interface_previous", None)

    if restore_pending:
        return False

    _fbp_clear_render_runtime_state()
    return True


@bpy.app.handlers.persistent
def fbp_render_guard_pre(scene):
    """Enter one render session from ``render_init``.

    Pure native image/sequence scenes use a strict pass-through mode: FBP only
    raises its runtime pause flag so background timers and frame handlers stay
    idle. No Blender datablock is modified before, during or after that render.
    """
    if bool(fbp_runtime_get("fbp_render_guard_active", False)):
        return

    generation = int(fbp_runtime_get("fbp_render_generation", 0) or 0) + 1
    fbp_runtime_set("fbp_render_generation", generation)
    fbp_runtime_set("fbp_render_guard_active", True)
    try:
        fbp_runtime_set("fbp_render_scene_name", str(getattr(scene, "name", "") or ""))
        fbp_runtime_set("fbp_render_scene_key", fbp_obj_runtime_key(scene) if scene else None)
        fbp_runtime_set("fbp_render_scene_pointer", None)
    except FBP_DATA_ERRORS:
        fbp_runtime_set("fbp_render_scene_name", "")
        fbp_runtime_set("fbp_render_scene_key", None)
        fbp_runtime_set("fbp_render_scene_pointer", None)
    fbp_runtime_set("fbp_render_viewport_hidden_planes", {})
    fbp_runtime_set("fbp_effect_render_backup", [])
    fbp_runtime_set("fbp_render_end_requested", False)
    fbp_runtime_set("fbp_render_end_requested_at", 0.0)
    fbp_runtime_set("fbp_render_lock_interface_previous", None)
    fbp_runtime_set("fbp_render_started_at", time.monotonic())
    fbp_runtime_set("fbp_render_restore_failures", 0)

    try:
        native_passthrough = _fbp_scene_is_native_render_passthrough(scene)
    except Exception as exc:
        # A failed preflight must choose the conservative managed path rather
        # than leaving an active guard with an undefined session contract.
        fbp_warn("Native render pass-through preflight failed", exc)
        native_passthrough = False

    if native_passthrough:
        fbp_runtime_set("fbp_render_session_mode", "NATIVE_PASSTHROUGH")
        fbp_runtime_set("fbp_render_needs_procedural_frame_sync", False)
        fbp_runtime_set("fbp_render_needs_drawing_frame_sync", False)
        fbp_runtime_set("fbp_render_needs_effect_frame_sync", False)
        return

    fbp_runtime_set("fbp_render_session_mode", "MANAGED")
    needs_procedural = _fbp_scene_needs_procedural_render_sync(scene)
    needs_drawing = _fbp_scene_needs_drawing_render_sync(scene)
    needs_effects = _fbp_scene_needs_effect_render_sync(scene)
    fbp_runtime_set("fbp_render_needs_procedural_frame_sync", needs_procedural)
    fbp_runtime_set("fbp_render_needs_drawing_frame_sync", needs_drawing)
    fbp_runtime_set("fbp_render_needs_effect_frame_sync", needs_effects)

    # Blender warns that frame handlers can run concurrently with viewport
    # evaluation. Managed FBP renders lock the interface whenever per-frame
    # datablock writes are unavoidable.
    render = getattr(scene, "render", None) if scene else None
    if render is not None:
        try:
            previous_lock = bool(getattr(render, "use_lock_interface", False))
            fbp_runtime_set("fbp_render_lock_interface_previous", previous_lock)
            if (needs_procedural or needs_drawing or needs_effects) and not previous_lock:
                render.use_lock_interface = True
        except FBP_DATA_ERRORS:
            pass

    try:
        from .geometry_nodes import fbp_effect_render_guard_pre
        fbp_runtime_set(
            "fbp_effect_render_backup",
            fbp_effect_render_guard_pre(scene=scene),
        )
    except Exception as exc:
        fbp_warn("Effect render guard failed", exc)
    try:
        fbp_render_visibility_guard(scene)
    except Exception as exc:
        fbp_warn("Render visibility guard failed", exc)


@bpy.app.handlers.persistent
def fbp_render_guard_complete(scene):
    """Record render completion without mutating managed Blender datablocks."""
    if not bool(fbp_runtime_get("fbp_render_guard_active", False)):
        return
    # Never release the pause guard from Blender's completion callback. Even a
    # pure native render can still be finalizing image buffers/depsgraph state at
    # this point. The watchdog clears or restores state only after the render job
    # is no longer active.
    fbp_runtime_set("fbp_render_end_requested", True)
    fbp_runtime_set("fbp_render_end_requested_at", time.monotonic())
    # Wake the persistent watchdog immediately. Without this nudge, its idle
    # two-second cadence left a window where a second render could start before
    # the first session's temporary effect/visibility state was restored.
    try:
        from . import handlers as _handlers
        _handlers.fbp_register_timer_once(
            _handlers.fbp_render_guard_watchdog,
            0.05,
            persistent=True,
            restart=True,
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


def fbp_render_guard_idle_restore(scene=None):
    """Restore a managed render after Blender has returned to its idle loop."""
    if not bool(fbp_runtime_get("fbp_render_guard_active", False)):
        return False
    return _fbp_restore_render_session_state(scene)


def fbp_render_guard_force_restore(scene=None):
    """Immediate best-effort restore used only during explicit unregister."""
    return _fbp_restore_render_session_state(scene or getattr(bpy.context, "scene", None))


def fbp_render_guard_abandon():
    """Forget transient references before Blender replaces the current Main."""
    _fbp_clear_render_runtime_state()


# ── HANDLERS ─────────────────────────────────────────────────────────────────


def _fbp_native_scene_range_key(scene):
    try:
        identity = fbp_obj_runtime_key(scene)
        if identity is None:
            return 0, ''
        return identity, str(getattr(scene, 'name_full', scene.name) or '')
    except FBP_DATA_ERRORS:
        return 0, ''


def _fbp_schedule_native_coverage_refresh_if_scene_range_changed(scene):
    """Refresh sequence F-Curve coverage only after the Scene range changes.

    Native image sequences normally require no Python frame handler. Their baked
    F-Curves do, however, cover the Scene range that existed when timing was last
    built. Watching only the two range integers keeps the normal frame path O(1)
    and schedules a safe rebuild once when users extend or shorten the timeline.
    """
    if scene is None:
        return False
    key = _fbp_native_scene_range_key(scene)
    if not key[0]:
        return False
    try:
        signature = (int(scene.frame_start), int(scene.frame_end))
    except FBP_DATA_ERRORS:
        return False
    previous = _FBP_NATIVE_SCENE_RANGE_CACHE.get(key)
    _FBP_NATIVE_SCENE_RANGE_CACHE[key] = signature
    if len(_FBP_NATIVE_SCENE_RANGE_CACHE) > 32:
        for stale_key in tuple(_FBP_NATIVE_SCENE_RANGE_CACHE)[:-32]:
            _FBP_NATIVE_SCENE_RANGE_CACHE.pop(stale_key, None)
    if previous == signature:
        return False

    if previous is None:
        # The cache can be initialized after a user has already extended the
        # Scene range. Validate once so the first frame change still repairs an
        # insufficient native coverage contract instead of silently accepting it.
        try:
            from .native_backend import fbp_native_rig_contract_issues
            requires_refresh = any(
                fbp_layer_backend_type(rig) == 'NATIVE_SEQUENCE'
                and "native Image/ImageUser/F-Curve contract is invalid"
                in fbp_native_rig_contract_issues(rig, check_files=False)
                for rig in iter_scene_fbp_rigs(scene)
            )
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            requires_refresh = False
        if not requires_refresh:
            return False
    else:
        previous_start, previous_end = previous
        range_expanded = (
            int(signature[0]) < int(previous_start)
            or int(signature[1]) > int(previous_end)
        )
        # A narrower Scene range is already covered by the existing F-Curves.
        # Skipping the rebuild avoids needless material/keyframe churn.
        if not range_expanded:
            return False

    scene_key, scene_name = key

    def _refresh_native_coverage():
        target_scene = fbp_find_id_by_runtime_key(
            bpy.data.scenes, scene_key, scene_name
        )
        if target_scene is None:
            return None
        changed = False
        for rig in iter_scene_fbp_rigs(target_scene):
            try:
                if fbp_layer_backend_type(rig) != 'NATIVE_SEQUENCE':
                    continue
                changed = bool(fbp_refresh_sequence_backend_from_rig(rig)) or changed
            except FBP_DATA_ERRORS as exc:
                fbp_warn('Native sequence range refresh skipped', exc)
        if changed:
            try:
                fbp_tag_view3d_ui_redraw()
            except FBP_DATA_ERRORS:
                pass
        return None

    try:
        from .safe_tasks import schedule_once
        return bool(schedule_once(
            f'native.sequence.range.{scene_key}',
            _refresh_native_coverage,
            first_interval=0.03,
        ))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


@bpy.app.handlers.persistent
def fbp_frame_change_handler(scene):
    """Synchronize only FBP backends that require Python on frame changes."""
    render_guard_active = bool(fbp_runtime_get("fbp_render_guard_active", False))
    if not render_guard_active:
        _fbp_schedule_native_coverage_refresh_if_scene_range_changed(scene)
    if render_guard_active:
        needs_procedural = bool(
            fbp_runtime_get("fbp_render_needs_procedural_frame_sync", False)
        )
        needs_frame_ui = False
    else:
        needs_procedural, needs_frame_ui = _fbp_scene_frame_state_cached(scene)
    needs_drawing = bool(
        fbp_runtime_get("fbp_render_needs_drawing_frame_sync", False)
    ) if render_guard_active else False

    if not render_guard_active:
        if fbp_render_mutation_blocked(include_guard=False):
            # External renders and unknown render state must never trigger image
            # or material writes from a frame handler.
            return
        try:
            from .drawing_plane import fbp_scene_has_drawing_planes
            needs_drawing = bool(fbp_scene_has_drawing_planes(scene))
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            needs_drawing = False

    if not needs_procedural and not needs_drawing:
        if needs_frame_ui and not fbp_is_rendering_now():
            fbp_tag_view3d_ui_redraw()
        return

    changed = False
    has_procedural_rigs = False
    if needs_drawing:
        try:
            from .drawing_plane import fbp_sync_drawing_scene
            changed = bool(fbp_sync_drawing_scene(scene)) or changed
        except Exception as exc:
            fbp_warn_once(
                "drawing_plane_frame_handler",
                "Cutout Plane frame handler skipped",
                exc,
            )

    if needs_procedural:
        try:
            _updated, has_procedural_rigs = fbp_update_sequence_scene(
                scene, getattr(scene, "frame_current", None)
            )
            changed = bool(_updated) or changed
        except Exception as exc:
            fbp_warn_once(
                "procedural_sequence_frame_handler",
                "Procedural sequence frame handler skipped",
                exc,
            )

    if (changed or has_procedural_rigs or needs_frame_ui) and not fbp_is_rendering_now():
        fbp_tag_view3d_ui_redraw()
    return

FBP_COLOR_PLANE_PRESETS = {
    'CUSTOM': ((1.0, 1.0, 1.0, 1.0), 'Custom'),
    'BLACK': ((0.0, 0.0, 0.0, 1.0), 'Black'),
    'WHITE': ((1.0, 1.0, 1.0, 1.0), 'White'),
    'MIDDLE_GREY': ((0.5, 0.5, 0.5, 1.0), 'Middle Grey'),
    'GREENSCREEN': ((0.0, 1.0, 0.0, 1.0), 'Greenscreen'),
    'BLUE': ((0.4, 0.592156862745098, 1.0, 1.0), 'Blue'),
    'PURPLE': ((0.5803921568627451, 0.3137254901960784, 0.9529411764705882, 1.0), 'Purple'),
    'ROSE': ((1.0, 0.25, 0.55, 1.0), 'Rose'),
    'YELLOW': ((1.0, 0.7019607843137254, 0.0, 1.0), 'Yellow'),
    'ORANGE': ((1.0, 0.4745098039215686, 0.0, 1.0), 'Orange'),
    'RED': ((1.0, 0.0, 0.0, 1.0), 'Red'),
}


def update_color_plane_preset_cb(self, context):
    try:
        preset = getattr(self, 'fbp_color_plane_preset', 'CUSTOM')
        if preset == 'CUSTOM':
            return
        color = FBP_COLOR_PLANE_PRESETS.get(preset, FBP_COLOR_PLANE_PRESETS['CUSTOM'])[0]
        self['_fbp_applying_color_preset'] = True
        self.fbp_color_plane_color = color
    except Exception as exc:
        fbp_warn("Could not apply color plane preset", exc)
    finally:
        try:
            self['_fbp_applying_color_preset'] = False
        except FBP_DATA_IO_ERRORS:
            pass


def update_color_plane_color_cb(self, context):
    try:
        if bool(self.get('_fbp_applying_color_preset', False)):
            return
        if getattr(self, 'fbp_color_plane_preset', 'CUSTOM') != 'CUSTOM':
            self.fbp_color_plane_preset = 'CUSTOM'
    except Exception as exc:
        fbp_warn("Could not switch color plane preset to Custom", exc)


def update_scene_gradient_preview_cb(self, context):
    """Queue preview-node updates outside RNA callbacks and Undo teardown."""
    del context
    try:
        fbp_schedule_gradient_preview_material_sync(self)
    except ReferenceError:
        return
    except Exception as exc:
        fbp_warn("Could not schedule gradient preview update", exc)


# ── PROPERTY REGISTRATION MOVED TO properties.py ───────────────────────────────

# ── MATERIAL CREATION ─────────────────────────────────────────────────────────


# ── COLOR / MASK PLANE HELPERS ───────────────────────────────────────────────


def update_object_color_plane_cb(self, context):
    try:
        if fbp_is_silent_property_update(self) or (fbp_obj_runtime_key(self) in _FBP_SYNCING_FRAME_MATERIAL_POINTERS):
            return
        mode = getattr(self, 'fbp_color_plane_mode', 'SOLID')
        if mode != 'GRADIENT':
            # Close gradient foldouts when the active frame/layer is not a gradient.
            try:
                self.fbp_show_gradient_ramp = False
                self.fbp_show_gradient_transform = False
            except FBP_DATA_IO_ERRORS:
                pass
        elif mode == 'GRADIENT':
            try:
                self.fbp_show_gradient_ramp = True
            except FBP_DATA_IO_ERRORS:
                pass

        props = (
            'fbp_color_plane_mode', 'fbp_color_plane_color', 'fbp_color_plane_emission',
            'fbp_gradient_mode', 'fbp_gradient_kind', 'fbp_gradient_color_a', 'fbp_gradient_color_b',
            'fbp_gradient_reverse', 'fbp_show_gradient_ramp', 'fbp_show_gradient_transform',
        )
        for rig in fbp_edit_targets(context, self, same_type=True):
            if rig != self:
                fbp_copy_registered_props_silent(rig, self, props)
            if fbp_rebuild_color_plane_material(rig):
                fbp_refresh_active_procedural_preview(rig)
                fbp_apply_procedural_color_frame(rig, getattr(_fbp_scene_for_rig(rig), 'frame_current', None))
    except ReferenceError:
        return
    except Exception as exc:
        fbp_warn("Could not update color/gradient plane material", exc)


# ── FIT TO CAMERA ─────────────────────────────────────────────────────────────


# ── BUILDER MOVED TO builder.py ───────────────────────────────────────────────
# Mesh creation, rig building, fit-to-camera and plane extension helpers
# are imported from builder.py.

# ── UI MOVED TO ui.py ──────────────────────────────────────────────────────────
# Panels, UILists, menu injection and UI draw helpers live in ui.py.


# ── UI HELPERS ────────────────────────────────────────────────────────────────


def update_gradient_mapping_cb(self, context):
    try:
        if fbp_obj_runtime_key(self) in _FBP_SYNCING_FRAME_MATERIAL_POINTERS:
            return
        props = ('fbp_gradient_offset_x', 'fbp_gradient_offset_y', 'fbp_gradient_scale_x', 'fbp_gradient_scale_y', 'fbp_gradient_rotation')
        for rig in fbp_edit_targets(context, self, same_type=True):
            if rig != self:
                fbp_copy_registered_props_silent(rig, self, props)
            apply_fbp_gradient_mapping_to_material(rig)
            fbp_refresh_active_procedural_preview(rig)
    except Exception as exc:
        fbp_warn("Could not update gradient transform", exc)


def draw_scene_fbp_color_ramp(layout, scene):
    """Draw the native ColorRamp in creation UI by editing a preview material node.

    This function is draw-safe: it never creates or mutates ID data-blocks.
    """
    box = layout.box()
    is_open = bool(getattr(scene, 'fbp_show_gradient_ramp', True))
    row = box.row(align=True)
    row.prop(scene, 'fbp_show_gradient_ramp', text='Color Ramp', icon=(fbp_icon('DOWNARROW_HLT') if is_open else fbp_icon('RIGHTARROW')), emboss=False)
    if not is_open:
        return
    mat = get_fbp_gradient_preview_material(scene)
    if mat is None:
        # Panel drawing must be read-only. The timer resolves the Scene again and
        # creates the preview material after Blender returns to its idle loop.
        fbp_schedule_gradient_preview_material_sync(scene)
    ramp_node = find_fbp_gradient_ramp_node(mat) if mat else None
    if not ramp_node:
        box.label(text='Preparing ColorRamp…', icon=fbp_icon('TIME'))
        return
    box.template_color_ramp(ramp_node, 'color_ramp', expand=True)


def draw_native_fbp_color_ramp(layout, rig):
    """Draw Blender's native ColorRamp widget for already-created gradient planes.

    This edits the actual shader node, so colors, stops, interpolation and keyframes
    remain stored directly in the material.
    """
    box = layout.box()
    is_open = bool(getattr(rig, 'fbp_show_gradient_ramp', True))
    row = box.row(align=True)
    row.prop(rig, 'fbp_show_gradient_ramp', text='Color Ramp', icon=(fbp_icon('DOWNARROW_HLT') if is_open else fbp_icon('RIGHTARROW')), emboss=False)
    if not is_open:
        return
    mat = get_fbp_gradient_material_from_rig(rig)
    ramp_node = find_fbp_gradient_ramp_node(mat) if mat else None
    if not ramp_node:
        box.label(text='No editable ColorRamp found on this gradient material.', icon=fbp_icon('ERROR'))
        return
    box.template_color_ramp(ramp_node, 'color_ramp', expand=True)


def fbp_draw_gradient_choice_rows(layout, owner):
    """Draw gradient choices as two compact dropdowns on one stable row."""
    row = layout.row(align=True)
    row.prop(owner, "fbp_gradient_mode", text="")
    row.prop(owner, "fbp_gradient_kind", text="")


def fbp_draw_color_plane_color_row(layout, scene):
    row = layout.row(align=False)
    split = row.split(factor=0.62, align=False)
    color_col = split.row(align=True)
    color_col.prop(scene, "fbp_color_plane_color", text="Color")
    preset_col = split.row(align=True)
    preset_col.prop(scene, "fbp_color_plane_preset", text="")


# SECTION 04B - Multiplane Setup helpers #
def _fbp_pending_open_collection_set(scene):
    try:
        raw = str(getattr(scene, "fbp_pending_open_collections", "") or "")
    except Exception:
        raw = ""
    return {name for name in raw.split("|") if name}


def pending_collection_is_open(scene, collection_name):
    """Return whether a Multiplane Setup collection is expanded in the UI."""
    name = collection_name or "Unsorted"
    return name in _fbp_pending_open_collection_set(scene)


def set_pending_collection_open(scene, collection_name, is_open=True):
    """Persist expanded/collapsed state for the Multiplane Setup collection UI."""
    name = collection_name or "Unsorted"
    values = _fbp_pending_open_collection_set(scene)
    if is_open:
        values.add(name)
    else:
        values.discard(name)
    try:
        scene.fbp_pending_open_collections = "|".join(sorted(values, key=natural_sort_key))
    except FBP_DATA_IO_ERRORS:
        pass


# ── PANELS ────────────────────────────────────────────────────────────────────


# ── OPERATORS ─────────────────────────────────────────────────────────────────


# ── PROCEDURAL SEQUENCE HELPERS ──────────────────────────────────────────────

def fbp_color_plane_can_have_frames(rig):
    return bool(getattr(rig, "fbp_is_color_plane", False) and getattr(rig, "fbp_color_plane_mode", "SOLID") != 'HOLDOUT')


def fbp_load_active_procedural_frame_to_rig(rig):
    """Load the active color/gradient frame material into the rig UI controls.

    Each procedural frame owns its own material. Selecting a frame updates the
    editable color/gradient controls, while the update callbacks are suppressed
    so selecting does not accidentally overwrite that material.
    """
    if not rig or not getattr(rig, 'fbp_is_color_plane', False):
        return False
    mat = fbp_get_active_frame_material(rig)
    if not mat:
        return False
    key = fbp_obj_runtime_key(rig)
    try:
        if key is not None:
            _FBP_SYNCING_FRAME_MATERIAL_POINTERS.add(key)
        idx = max(0, min(int(getattr(rig, 'fbp_images_index', 0)), len(getattr(rig, 'fbp_images', [])) - 1)) if len(getattr(rig, 'fbp_images', [])) else 0
        kind = fbp_procedural_kind_for_item(rig, idx, fbp_procedural_kind_from_material(mat, getattr(rig, 'fbp_color_plane_mode', 'SOLID')))
        if kind == 'GRADIENT':
            rig.fbp_color_plane_mode = 'GRADIENT'
            rig.fbp_gradient_mode = str(mat.get('fbp_gradient_mode', getattr(rig, 'fbp_gradient_mode', 'LINEAR')))
            rig.fbp_gradient_kind = str(mat.get('fbp_gradient_kind', getattr(rig, 'fbp_gradient_kind', 'COLOR')))
            rig.fbp_gradient_reverse = bool(mat.get('fbp_gradient_reverse', getattr(rig, 'fbp_gradient_reverse', False)))
            ramp = find_fbp_gradient_ramp_node(mat)
            if ramp and len(ramp.color_ramp.elements) >= 2:
                elems = ramp.color_ramp.elements
                rig.fbp_gradient_color_a = tuple(elems[0].color)
                rig.fbp_gradient_color_b = tuple(elems[-1].color)
        elif kind == 'HOLDOUT':
            rig.fbp_color_plane_mode = 'HOLDOUT'
        else:
            rig.fbp_color_plane_mode = 'SOLID'
            rig.fbp_color_plane_color = fbp_material_color_value(mat, tuple(getattr(rig, 'fbp_color_plane_color', (1.0, 1.0, 1.0, 1.0))))
        return True
    except Exception as exc:
        fbp_warn('Could not load active procedural frame settings', exc)
        return False
    finally:
        try:
            if key is not None:
                _FBP_SYNCING_FRAME_MATERIAL_POINTERS.discard(key)
        except FBP_DATA_IO_ERRORS:
            pass


def fbp_normalize_sequence_entry(entry, rig=None):
    """Validate and normalize one current dictionary-based sequence entry."""
    if not isinstance(entry, dict):
        raise TypeError("Sequence entries must use the current dictionary format")
    data = dict(entry)
    try:
        fallback_duration = getattr(rig, "fbp_global_duration", 1) if rig else 1
        data["duration"] = max(1, int(data.get("duration", fallback_duration) or 1))
    except FBP_DATA_ERRORS:
        data["duration"] = 1
    data["name"] = str(data.get("name", "Frame") or "Frame")
    data["is_selected"] = bool(data.get("is_selected", True))
    data["is_empty"] = bool(data.get("is_empty", False))
    data["filepath"] = str(data.get("filepath", "") or "")
    data["procedural_kind"] = str(data.get("procedural_kind", "AUTO") or "AUTO")
    return data


def fbp_insert_sequence_entry(rig, entry, material, insert_at=None):
    """Insert one normalized sequence entry and rebuild through the shared path."""
    plane = getattr(rig, 'fbp_plane_target', None)
    if not plane:
        return -1

    backend_type = fbp_layer_backend_type(rig)
    is_color_plane = bool(getattr(rig, "fbp_is_color_plane", False))
    if backend_type in {'CUTOUT', 'NATIVE_MOVIE'}:
        return -1
    if not is_color_plane and backend_type not in {'NATIVE_IMAGE', 'NATIVE_SEQUENCE'}:
        return -1
    if is_color_plane and not fbp_color_plane_can_have_frames(rig):
        return -1

    entry_data = fbp_normalize_sequence_entry(entry, rig)
    # Native image planes keep transparent rows inside the same Image Sequence
    # material. The native backend drives an alpha visibility mask for those
    # logical frames, so no generated image file or extra material is required.
    entry_data["material"] = material if is_color_plane else None

    entries = fbp_sequence_entries_from_rig(rig)
    if is_color_plane and not entries:
        # Promote a static Color/Gradient plane to a one-frame procedural sequence
        # before inserting the requested row.
        source_mat = plane.data.materials[0] if len(plane.data.materials) else None
        if not source_mat:
            fbp_rebuild_color_plane_material(rig)
            source_mat = plane.data.materials[0] if len(plane.data.materials) else None
        label = "Gradient" if getattr(rig, "fbp_color_plane_mode", "SOLID") == 'GRADIENT' else "Color"
        kind = fbp_procedural_kind_from_material(
            source_mat,
            getattr(rig, "fbp_color_plane_mode", "SOLID"),
        )
        entries = [{
            "name": label,
            "duration": max(1, int(getattr(rig, 'fbp_global_duration', 1) or 1)),
            "is_selected": True,
            "is_empty": False,
            "filepath": "",
            "procedural_kind": kind,
            "material": source_mat,
        }]

    if insert_at is None:
        checked = [i for i, data in enumerate(entries) if bool(data.get("is_selected", False))]
        if checked:
            insert_at = checked[-1] + 1
        else:
            current = int(getattr(rig, 'fbp_images_index', 0) or 0)
            insert_at = min(max(current, 0), len(entries) - 1) + 1 if entries else 0
    insert_at = max(0, min(int(insert_at), len(entries)))
    entries.insert(insert_at, entry_data)

    try:
        if not fbp_apply_sequence_entries_to_rig(rig, entries):
            return -1
        rig.fbp_images_index = max(0, min(insert_at, len(rig.fbp_images) - 1)) if rig.fbp_images else 0
        if is_color_plane:
            fbp_load_active_procedural_frame_to_rig(rig)
        return insert_at
    except Exception as exc:
        fbp_warn("Could not update sequence after inserting row", exc)
        return -1


def fbp_sequence_entries_from_rig(rig):
    entries = []
    plane = getattr(rig, "fbp_plane_target", None)
    is_color_plane = getattr(rig, "fbp_is_color_plane", False)
    for i, item in enumerate(rig.fbp_images):
        mat = plane.data.materials[i] if is_color_plane and plane and i < len(plane.data.materials) else None
        entries.append({
            "name": item.name,
            "duration": item.duration,
            "is_selected": item.is_selected,
            "is_empty": getattr(item, "is_empty", False),
            "filepath": getattr(item, "filepath", ""),
            "procedural_kind": fbp_procedural_kind_for_item(rig, i, getattr(rig, 'fbp_color_plane_mode', 'SOLID')) if is_color_plane else getattr(item, 'procedural_kind', 'AUTO'),
            "material": mat,
        })
    return entries


def fbp_clone_sequence_entry_material(entry, rig=None, suffix="Copy"):
    """Clone a procedural Color/Gradient entry without sharing material data."""
    cloned = dict(entry)
    mat = entry.get("material")
    if mat:
        new_mat = fbp_duplicate_procedural_material_for_frame(mat, rig, suffix)
        if new_mat:
            cloned["material"] = new_mat
    # After duplication, only the newly-created rows should remain checked.
    cloned["is_selected"] = True
    return cloned


def fbp_apply_sequence_entries_to_rig(rig, entries):
    """Apply logical sequence rows without leaving UI/backend state half-updated."""
    plane = getattr(rig, "fbp_plane_target", None)
    if not plane:
        return False
    backend_type = fbp_layer_backend_type(rig)
    is_color_plane = getattr(rig, "fbp_is_color_plane", False)
    if backend_type in {'CUTOUT', 'NATIVE_MOVIE'}:
        return False
    if not is_color_plane and backend_type not in {'NATIVE_IMAGE', 'NATIVE_SEQUENCE'}:
        return False
    normalized_entries = []
    try:
        for raw_entry in entries:
            data = fbp_normalize_sequence_entry(raw_entry, rig)
            data["material"] = raw_entry.get("material")
            normalized_entries.append(data)
    except (TypeError, ValueError) as exc:
        fbp_warn("Rejected invalid sequence entry", exc)
        return False
    if is_color_plane and any(entry.get("material") is None for entry in normalized_entries):
        fbp_warn("Rejected procedural sequence with missing frame material")
        return False

    old_entries = fbp_sequence_entries_from_rig(rig)
    old_index = int(getattr(rig, 'fbp_images_index', 0) or 0)
    old_preview = str(getattr(rig, 'fbp_preview_path', '') or '')
    old_material_slots = list(getattr(plane.data, 'materials', [])) if is_color_plane else []
    candidate_materials = [
        entry.get("material") for entry in normalized_entries
        if entry.get("material") is not None
    ]

    def populate_state(values):
        rig.fbp_images.clear()
        if is_color_plane:
            plane.data.materials.clear()
        for entry in values:
            material = entry.get("material")
            if is_color_plane and material:
                fbp_set_procedural_metadata(
                    material,
                    entry.get(
                        "procedural_kind",
                        fbp_procedural_kind_from_material(
                            material,
                            getattr(rig, 'fbp_color_plane_mode', 'SOLID'),
                        ),
                    ),
                )
                plane.data.materials.append(material)

            item = rig.fbp_images.add()
            item.name = entry.get("name", "Image")
            fbp_set_rna_property_silent(
                item,
                "duration",
                max(
                    1,
                    int(entry.get("duration", getattr(rig, "fbp_global_duration", 1)) or 1),
                ),
            )
            item.is_selected = bool(entry.get("is_selected", True))
            item.is_empty = bool(entry.get("is_empty", False))
            item.filepath = str(entry.get("filepath", "") or "")
            try:
                item.procedural_kind = entry.get("procedural_kind", 'AUTO')
            except FBP_DATA_IO_ERRORS:
                pass
            if is_color_plane:
                try:
                    fbp_cache_procedural_preview_on_item(
                        item,
                        material,
                        getattr(item, 'procedural_kind', 'SOLID'),
                    )
                except FBP_DATA_IO_ERRORS:
                    pass

        # CollectionProperty add/remove/move operations do not emit a parent
        # Object update callback. Explicitly invalidate the shared timing cache
        # so REC reflects the new list immediately, even when the backend itself
        # was refreshed successfully.
        fbp_invalidate_procedural_rig_cache(rig)
        fbp_invalidate_procedural_scene_cache(_fbp_scene_for_rig(rig))

    def restore_previous_state():
        populate_state(old_entries)
        rig.fbp_images_index = max(
            0,
            min(old_index, max(0, len(rig.fbp_images) - 1)),
        )
        try:
            rig.fbp_preview_path = old_preview
        except FBP_DATA_IO_ERRORS:
            pass
        if is_color_plane:
            try:
                plane.data.materials.clear()
                for material in old_material_slots:
                    if material:
                        plane.data.materials.append(material)
            except Exception as exc:
                fbp_warn("Could not restore procedural material slots", exc)
            try:
                fbp_refresh_sequence_backend_from_rig(rig)
            except Exception as exc:
                fbp_warn("Could not refresh restored procedural sequence", exc)
            try:
                old_materials = [material for material in old_material_slots if material]
                fbp_remove_unused_materials_and_images([
                    mat for mat in candidate_materials
                    if mat
                    and not any(mat == old for old in old_materials)
                    and getattr(mat, 'users', 0) == 0
                ])
            except Exception as exc:
                fbp_warn("Could not clean rolled-back procedural materials", exc)
        else:
            # A failed fast refresh may already have touched ImageUser defaults,
            # extensions or F-Curves before detecting the broken source. After
            # restoring the logical rows, explicitly restore the native backend
            # too; otherwise the UI list and rendered material can diverge.
            try:
                if not (
                    fbp_refresh_sequence_backend_from_rig(rig)
                    or fbp_rebuild_sequence_backend_from_rig(rig)
                ):
                    fbp_warn("Could not restore native sequence backend after rollback")
            except Exception as exc:
                fbp_warn("Could not restore native sequence backend after rollback", exc)

    populate_state(normalized_entries)
    rig.fbp_images_index = min(
        max(0, int(getattr(rig, 'fbp_images_index', 0) or 0)),
        max(0, len(rig.fbp_images) - 1),
    )
    if normalized_entries:
        first_path = next(
            (entry.get("filepath", "") for entry in normalized_entries if entry.get("filepath", "")),
            "",
        )
        if first_path:
            rig.fbp_preview_path = first_path
    try:
        if is_color_plane and not str(rig.get('fbp_procedural_layer_type', '') or ''):
            rig['fbp_procedural_layer_type'] = str(
                getattr(rig, 'fbp_color_plane_mode', 'SOLID') or 'SOLID'
            )
    except FBP_DATA_IO_ERRORS:
        pass

    try:
        if is_color_plane:
            rebuilt = fbp_refresh_sequence_backend_from_rig(rig)
        else:
            # Reorder, duplicate, duration and transparent-row edits can usually
            # update only logical metadata/F-Curves. Rebuild the material only
            # when the media contract changes (new source, Image↔Sequence, etc.).
            rebuilt = (
                fbp_refresh_sequence_backend_from_rig(rig)
                or fbp_rebuild_sequence_backend_from_rig(rig)
            )
        if not rebuilt:
            restore_previous_state()
            return False
    except Exception as exc:
        restore_previous_state()
        fbp_warn("Could not apply sequence entries", exc)
        return False

    # Keep the icon state synchronized with the actual list operation. Timing or
    # selection-only edits preserve the state; a complete reversal toggles it;
    # arbitrary reorders clear it so the side icon never displays stale status.
    def order_signature(values):
        return [
            (
                str(entry.get("filepath", "") or ""),
                bool(entry.get("is_empty", False)),
                str(entry.get("name", "") or ""),
            )
            for entry in values
        ]

    old_order = order_signature(old_entries)
    new_order = order_signature(normalized_entries)
    previous_reversed = bool(getattr(rig, "fbp_sequence_reversed", False))
    if new_order == old_order:
        pass
    elif len(old_order) > 1 and new_order == list(reversed(old_order)):
        fbp_set_rna_property_silent(
            rig, "fbp_sequence_reversed", not previous_reversed
        )
    else:
        fbp_set_rna_property_silent(rig, "fbp_sequence_reversed", False)

    # Procedural rows reuse existing materials and still need their current-frame
    # appearance synchronized. Native rows were already rebuilt transactionally
    # with timing, opacity, emission and effects, so a second full refresh would
    # only repeat file validation and F-Curve work.
    if is_color_plane:
        do_update_animation(rig)
        do_update_emission(rig)
        do_update_opacity(rig)
        try:
            current_materials = [material for material in plane.data.materials if material]
            fbp_remove_unused_materials_and_images([
                material for material in old_material_slots
                if material
                and not any(material == current for current in current_materials)
                and getattr(material, 'users', 0) == 0
            ])
        except Exception as exc:
            fbp_warn("Could not clean replaced procedural materials", exc)
    try:
        fbp_tag_view3d_ui_redraw()
    except FBP_DATA_ERRORS:
        pass
    return True


# Fast Import is invoked directly inside the operator execute methods.
# Avoid monkey-patching operator methods at module load.
