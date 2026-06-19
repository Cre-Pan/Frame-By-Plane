"""Layer synchronization, native delete/duplicate repair and orphan cleanup."""

import bpy
import time

from . import safe_tasks as fbp_safe_tasks
from .runtime import (
    fbp_runtime_get,
    fbp_runtime_set,
    fbp_undo_guard_active,
    fbp_render_mutation_blocked,
    fbp_warn,
    fbp_obj_runtime_token,
    fbp_normalize_obj_runtime_token,
)
from .layers import (
    object_in_scene,
    is_fbp_layer_object,
    fbp_rebuild_layer_view_cache,
)

from .materials import (
    fbp_remove_unused_materials_and_images,
    fbp_copy_material_slots_unique,
    do_update_emission,
    do_update_opacity,
)


FBP_FALLBACK_TIMER_INTERVAL = 10.0
FBP_FALLBACK_DUPLICATE_SCAN_INTERVAL = 45.0
FBP_FALLBACK_ORPHAN_SCAN_INTERVAL = 30.0

# Per-scene object totals let the depsgraph listener avoid checking every known
# rig/plane link during ordinary transforms, shading changes and UI redraws.
# Deletion, duplication and collection unlinking change this total and still
# trigger the complete safety check immediately.
_FBP_SCENE_OBJECT_COUNT_CACHE = globals().get("_FBP_SCENE_OBJECT_COUNT_CACHE", {})
if not isinstance(_FBP_SCENE_OBJECT_COUNT_CACHE, dict):
    _FBP_SCENE_OBJECT_COUNT_CACHE = {}
_FBP_FALLBACK_SCAN_CLOCKS = globals().get("_FBP_FALLBACK_SCAN_CLOCKS", {})
if not isinstance(_FBP_FALLBACK_SCAN_CLOCKS, dict):
    _FBP_FALLBACK_SCAN_CLOCKS = {}


def _fbp_scene_cache_key(scene):
    if scene is None:
        return None
    try:
        return (
            int(scene.as_pointer()),
            str(getattr(scene, "name_full", getattr(scene, "name", "")) or ""),
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None


def _fbp_scene_object_count_changed(scene, *, update=True):
    key = _fbp_scene_cache_key(scene)
    if key is None:
        return True
    try:
        count = len(scene.objects)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return True
    previous = _FBP_SCENE_OBJECT_COUNT_CACHE.get(key)
    if update:
        if len(_FBP_SCENE_OBJECT_COUNT_CACHE) >= 64 and key not in _FBP_SCENE_OBJECT_COUNT_CACHE:
            _FBP_SCENE_OBJECT_COUNT_CACHE.clear()
        _FBP_SCENE_OBJECT_COUNT_CACHE[key] = count
    return previous is None or previous != count


def _core():
    from . import core as _core_mod
    return _core_mod



def fbp_fast_import_is_active():
    from .importer import fbp_fast_import_is_active as _is_active
    return _is_active()


def fbp_undo_is_active(*, release_expired=False):
    return fbp_undo_guard_active(release_expired=release_expired)


def fbp_animation_playback_active(context=None):
    """Return True when any visible Blender window is playing animation."""
    context = context or getattr(bpy, 'context', None)
    checked = set()
    try:
        wm = getattr(context, 'window_manager', None)
        for window in list(getattr(wm, 'windows', []) or []):
            screen = getattr(window, 'screen', None)
            if not screen:
                continue
            key = int(screen.as_pointer()) if hasattr(screen, 'as_pointer') else id(screen)
            checked.add(key)
            if bool(getattr(screen, 'is_animation_playing', False)):
                return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        screen = getattr(context, 'screen', None)
        if screen:
            key = int(screen.as_pointer()) if hasattr(screen, 'as_pointer') else id(screen)
            if key not in checked and bool(getattr(screen, 'is_animation_playing', False)):
                return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return False



def fbp_render_job_active():
    """Return True unless Blender confirms that no render job is active."""
    return fbp_render_mutation_blocked(include_guard=False)


def fbp_background_sync_should_pause(context=None):
    """Pause non-urgent fallback scans during playback, render, undo or import."""
    if fbp_undo_is_active():
        return True
    try:
        if fbp_fast_import_is_active():
            return True
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        pass
    return fbp_animation_playback_active(context) or fbp_render_job_active()


def fbp_scene_fallback_candidates(scene):
    """Return cached/tagged FBP objects without scanning every Scene object.

    The depsgraph handler is the primary native-operation detector. This helper is
    only a low-frequency safety net, so it uses the layer cache, remembered links,
    active objects and cached/tagged FBP collections instead of traversing ``scene.objects``.
    """
    if not scene:
        return []

    result = []
    seen = set()

    def add(obj):
        if not obj:
            return
        try:
            key = int(obj.as_pointer())
            if key in seen or not object_in_scene(obj, scene):
                return
            seen.add(key)
            result.append(obj)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return

    # Prioritize objects the user is actively touching. This catches manual
    # duplicates/moves even when the collection cache has not been rebuilt yet.
    try:
        context = getattr(bpy, "context", None)
        add(getattr(context, "active_object", None))
        for obj in list(getattr(context, "selected_objects", ()) or ()):
            add(obj)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    for item in list(getattr(scene, "fbp_layers", ()) or ()):
        try:
            rig = getattr(item, "obj", None)
            add(rig)
            add(getattr(rig, "fbp_plane_target", None) if rig else None)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue

    links = _fbp_get_known_links(scene)
    for rig_name, plane_names in links.items():
        add(bpy.data.objects.get(str(rig_name)))
        for plane_name in list(plane_names or ()):
            add(bpy.data.objects.get(str(plane_name)))

    root = getattr(scene, "collection", None)

    def collection_may_contain_fbp(collection, *, recursive=True):
        if not collection:
            return False
        try:
            if bool(getattr(collection, "is_fbp_collection", False)):
                return True
            key = "fbp_has_fbp_content_recursive" if recursive else "fbp_has_fbp_content"
            return bool(collection.get(key, False))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return False

    stack = [
        child for child in list(getattr(root, "children", ()) or ())
        if collection_may_contain_fbp(child, recursive=True)
    ] if root else []
    visited_collections = set()
    while stack:
        collection = stack.pop()
        try:
            key = int(collection.as_pointer())
            if key in visited_collections:
                continue
            visited_collections.add(key)
            stack.extend(
                child for child in list(getattr(collection, "children", ()) or ())
                if collection_may_contain_fbp(child, recursive=True)
            )
            if not collection_may_contain_fbp(collection, recursive=False):
                continue
            for obj in list(getattr(collection, "objects", ()) or ()):
                add(obj)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return result

def fbp_stop_playback_for_datablock_cleanup(context=None):
    """Stop playback before deleting Object, Mesh or Material datablocks.

    Returns False when playback is still active so callers can defer the
    destructive operation instead of touching data used by viewport evaluation.
    """
    context = context or getattr(bpy, 'context', None)
    windows = []
    try:
        wm = getattr(context, 'window_manager', None)
        windows.extend(list(getattr(wm, 'windows', []) or []))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        current_window = getattr(context, 'window', None)
        if current_window and current_window not in windows:
            windows.append(current_window)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    for window in windows:
        try:
            screen = getattr(window, 'screen', None)
            if not screen or not getattr(screen, 'is_animation_playing', False):
                continue
            with bpy.context.temp_override(window=window, screen=screen):
                bpy.ops.screen.animation_cancel(restore_frame=False)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not stop playback before Frame by Plane cleanup", exc)

    return not fbp_animation_playback_active(context)


def do_update_animation(obj, context=None):
    return _core().do_update_animation(obj)


def fbp_ensure_plane_render_safe(rig, frame=None):
    return _core().fbp_ensure_plane_render_safe(rig, frame)


# SECTION 01 - Layer Collection Sync #

def _fbp_object_identity(obj):
    """Return a runtime identity that survives renames and resists name reuse."""
    if obj is None:
        return None
    try:
        session_uid = int(getattr(obj, "session_uid", 0) or 0)
        if session_uid > 0:
            return ("UID", session_uid)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        return ("PTR", int(obj.as_pointer()))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        try:
            return ("NAME", str(obj.name_full))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return None




_FBP_KNOWN_LINKS_STATE_KEY = "fbp_known_rig_plane_links_by_scene"


def _fbp_scene_runtime_identity(scene):
    """Return a runtime-only identity for a Scene datablock."""
    if scene is None:
        return None
    try:
        return int(scene.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None


def _fbp_get_known_links(scene):
    """Return the remembered rig/plane map belonging only to ``scene``.

    The old single global map could make cleanup in Scene B interpret every rig
    from Scene A as deleted. Keep independent in-memory snapshots instead.
    """
    scene_key = _fbp_scene_runtime_identity(scene)
    if scene_key is None:
        return {}
    store = fbp_runtime_get(_FBP_KNOWN_LINKS_STATE_KEY, {}) or {}
    if not isinstance(store, dict):
        return {}
    entry = store.get(scene_key)
    if not isinstance(entry, dict):
        return {}
    stored_scene = entry.get("scene_ref")
    if stored_scene is not None:
        try:
            if int(stored_scene.as_pointer()) != scene_key:
                return {}
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return {}
    links = entry.get("links", {})
    if not isinstance(links, dict):
        return {}
    result = {}
    for rig_name, plane_names in links.items():
        name = str(rig_name or "")
        if not name:
            continue
        result[name] = [str(item) for item in list(plane_names or ()) if item]
    return result


def _fbp_normalize_identity(value):
    if isinstance(value, (tuple, list)) and len(value) == 2:
        kind = str(value[0] or "")
        if kind in {"UID", "PTR", "NAME"}:
            return (kind, value[1])
    return None


def _fbp_identity_matches(obj, identity):
    normalized = _fbp_normalize_identity(identity)
    return bool(normalized is not None and _fbp_object_identity(obj) == normalized)


def _fbp_find_scene_object_by_identity(scene, identity):
    normalized = _fbp_normalize_identity(identity)
    if scene is None or normalized is None:
        return None
    kind, value = normalized
    if kind == "NAME":
        obj = bpy.data.objects.get(str(value or ""))
        try:
            return obj if obj and object_in_scene(obj, scene) else None
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return None
    try:
        for obj in scene.objects:
            if _fbp_object_identity(obj) == normalized:
                return obj
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None
    return None


def _fbp_get_known_link_identities(scene):
    """Return runtime identities paired with the remembered name snapshot."""
    scene_key = _fbp_scene_runtime_identity(scene)
    if scene_key is None:
        return {}
    store = fbp_runtime_get(_FBP_KNOWN_LINKS_STATE_KEY, {}) or {}
    if not isinstance(store, dict):
        return {}
    entry = store.get(scene_key)
    if not isinstance(entry, dict):
        return {}
    raw = entry.get("identities", {})
    if not isinstance(raw, dict):
        return {}
    result = {}
    for rig_name, record in raw.items():
        if not isinstance(record, dict):
            continue
        planes = record.get("planes", {})
        result[str(rig_name or "")] = {
            "rig_key": _fbp_normalize_identity(record.get("rig_key")),
            "planes": {
                str(name): _fbp_normalize_identity(identity)
                for name, identity in dict(planes or {}).items()
                if name and _fbp_normalize_identity(identity) is not None
            },
        }
    return result


def _fbp_set_known_links(scene, links, identities=None):
    """Store a Scene-bound name map plus rename-safe object identities."""
    scene_key = _fbp_scene_runtime_identity(scene)
    if scene_key is None:
        return False
    store = fbp_runtime_get(_FBP_KNOWN_LINKS_STATE_KEY, {}) or {}
    store = dict(store) if isinstance(store, dict) else {}

    live_scene_keys = set()
    try:
        live_scene_keys = {int(item.as_pointer()) for item in bpy.data.scenes}
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    if live_scene_keys:
        store = {key: value for key, value in store.items() if key in live_scene_keys}

    normalized = {}
    normalized_identities = {}
    supplied_identities = dict(identities or {}) if isinstance(identities, dict) else {}
    for rig_name, plane_names in dict(links or {}).items():
        name = str(rig_name or "")
        if not name:
            continue
        names = [str(item) for item in list(plane_names or ()) if item]
        normalized[name] = names

        supplied = supplied_identities.get(name, {})
        rig = bpy.data.objects.get(name)
        rig_key = _fbp_normalize_identity(
            supplied.get("rig_key") if isinstance(supplied, dict) else None
        ) or _fbp_object_identity(rig)
        supplied_planes = supplied.get("planes", {}) if isinstance(supplied, dict) else {}
        plane_identities = {}
        for plane_name in names:
            identity = _fbp_normalize_identity(dict(supplied_planes or {}).get(plane_name))
            if identity is None:
                identity = _fbp_object_identity(bpy.data.objects.get(plane_name))
            if identity is not None:
                plane_identities[plane_name] = identity
        normalized_identities[name] = {
            "rig_key": rig_key,
            "planes": plane_identities,
        }

    store[scene_key] = {
        "scene_ref": scene,
        "scene_name": str(getattr(scene, "name", "") or ""),
        "links": normalized,
        "identities": normalized_identities,
    }
    return fbp_runtime_set(_FBP_KNOWN_LINKS_STATE_KEY, store)


def fbp_clear_known_link_snapshots():
    """Forget all Scene-bound delete snapshots during file load/unregister."""
    return fbp_runtime_set(_FBP_KNOWN_LINKS_STATE_KEY, {})


def _fbp_retarget_runtime_layer_name(rig, old_rig_name, new_rig_name, old_plane_name="", new_plane_name=""):
    """Retarget runtime-only UI rows and delete snapshots after an Object rename.

    ``Scene.fbp_layers`` deliberately stores object names rather than live Object
    pointers because the latter proved unsafe around Blender 5.1 Undo. Renaming
    the Object therefore has to update those strings before any UI rebuild tries
    to resolve them. Keeping this operation explicit also preserves per-row
    selection, solo, mute and lock state instead of deleting/recreating the row.
    """
    if not rig or not old_rig_name or not new_rig_name:
        return False
    changed = False
    rig_runtime_key = fbp_obj_runtime_token(rig)
    for scene in list(getattr(bpy.data, "scenes", ()) or ()):
        try:
            scene_contains_rig = object_in_scene(rig, scene)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            scene_contains_rig = False
        if not scene_contains_rig:
            continue

        scene_changed = False
        for item in list(getattr(scene, "fbp_layers", ()) or ()):
            try:
                item_name = str(getattr(item, "obj_name", "") or "")
                item_runtime_key = fbp_normalize_obj_runtime_token(
                    getattr(item, "obj_runtime_key", "")
                )
                runtime_matches = bool(
                    item_runtime_key
                    and rig_runtime_key
                    and item_runtime_key == rig_runtime_key
                )
                if item_name != old_rig_name and not runtime_matches:
                    continue
                item.obj_name = new_rig_name
                if rig_runtime_key:
                    item.obj_runtime_key = rig_runtime_key
                scene_changed = True
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue

        for row in list(getattr(scene, "fbp_layer_tree_rows", ()) or ()):
            try:
                if str(getattr(row, "rig_name", "") or "") != old_rig_name:
                    continue
                row.rig_name = new_rig_name
                row.name = new_rig_name
                scene_changed = True
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue

        links = _fbp_get_known_links(scene)
        identities = _fbp_get_known_link_identities(scene)
        if old_rig_name in links:
            plane_names = list(links.pop(old_rig_name, ()) or ())
            identity_record = identities.pop(old_rig_name, {})
            plane_identities = dict(identity_record.get("planes", {}) or {}) if isinstance(identity_record, dict) else {}
            if old_plane_name and new_plane_name and old_plane_name != new_plane_name:
                plane_names = [
                    new_plane_name if name == old_plane_name else name
                    for name in plane_names
                ]
                if old_plane_name in plane_identities:
                    plane_identities[new_plane_name] = plane_identities.pop(old_plane_name)
            links[new_rig_name] = list(dict.fromkeys(plane_names))
            identities[new_rig_name] = {
                "rig_key": _fbp_object_identity(rig),
                "planes": plane_identities,
            }
            _fbp_set_known_links(scene, links, identities)
            scene_changed = True

        if scene_changed:
            # A linked rig can appear in more than one Scene. Mark every cached
            # tree signature dirty; the active Scene is recomputed immediately
            # by ``fbp_rename_layer_rig`` below.
            try:
                scene.fbp_layer_tree_signature = ""
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
            changed = True
    return changed


def fbp_rename_layer_rig(rig, new_name, context=None):
    """Rename one FBP layer and refresh every current ownership reference.

    Blender keeps real pointers valid across object renames, while Frame by
    Plane intentionally stores several runtime fallback names for Undo-safe UI,
    orphan cleanup and effect repair. This helper updates those names as one
    operation so the layer never disappears from the panel after a rename.
    """
    if not rig or not getattr(rig, "is_fbp_control", False):
        return ""
    requested = str(new_name or "").strip()
    if not requested:
        return ""

    old_rig_name = str(getattr(rig, "name", "") or "")
    if not old_rig_name:
        return ""
    try:
        if bpy.data.objects.get(old_rig_name) != rig:
            return ""
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return ""

    try:
        plane = getattr(rig, "fbp_plane_target", None)
    except ReferenceError:
        plane = None
    old_plane_name = str(getattr(plane, "name", "") or "") if plane else ""

    # Preserve custom hidden-plane names. Only follow the rig rename when the
    # plane still uses Frame by Plane's generated naming convention.
    auto_plane_name = bool(
        plane
        and old_plane_name in {f"Plane_{old_rig_name}", f"{old_rig_name}_Plane"}
    )
    old_rig_mesh_name = str(getattr(getattr(rig, "data", None), "name", "") or "")
    old_plane_mesh_name = str(getattr(getattr(plane, "data", None), "name", "") or "") if plane else ""

    try:
        rig.name = requested
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not rename Frame by Plane layer", exc)
        return ""
    actual_rig_name = str(getattr(rig, "name", "") or requested)

    if old_rig_mesh_name == f"Mesh_{old_rig_name}_Rig":
        try:
            rig.data.name = f"Mesh_{actual_rig_name}_Rig"
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass

    if plane:
        if auto_plane_name:
            try:
                plane.name = f"Plane_{actual_rig_name}"
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        if old_plane_mesh_name == f"Mesh_Plane_{old_rig_name}":
            try:
                plane.data.name = f"Mesh_Plane_{actual_rig_name}"
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        try:
            plane["fbp_parent_rig_name"] = actual_rig_name
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
            pass

    new_plane_name = str(getattr(plane, "name", "") or "") if plane else ""
    _fbp_retarget_runtime_layer_name(
        rig,
        old_rig_name,
        actual_rig_name,
        old_plane_name=old_plane_name,
        new_plane_name=new_plane_name,
    )

    try:
        from .geometry_nodes import fbp_retag_effect_owners_after_layer_rename
        fbp_retag_effect_owners_after_layer_rename(
            rig, old_plane_name=old_plane_name
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not retag effect owners after layer rename", exc)

    context = context or getattr(bpy, "context", None)
    if context and getattr(context, "scene", None):
        # The runtime rows were already retargeted above. Avoid a complete scene
        # rescan here: direct text-field renames used to expose the old row name
        # for one or more redraws, briefly showing a missing-layer error.
        try:
            from .ui_layout import fbp_layer_tree_signature
            context.scene.fbp_layer_tree_signature = fbp_layer_tree_signature(context)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            context.scene.fbp_layer_tree_signature = ""
        try:
            _core().fbp_tag_view3d_ui_redraw()
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    return actual_rig_name


def sync_layer_collection(context):
    if fbp_undo_is_active():
        return
    sc = context.scene
    for i in range(len(sc.fbp_layers) - 1, -1, -1):
        try:
            item = sc.fbp_layers[i]
            rig = item.obj
            if not rig or not object_in_scene(rig, sc):
                sc.fbp_layers.remove(i)
        except ReferenceError:
            sc.fbp_layers.remove(i)

    existing_keys = set()
    for item in sc.fbp_layers:
        try:
            rig = item.obj
            if not rig or not object_in_scene(rig, sc):
                continue
            key = _fbp_object_identity(rig)
            if key is not None:
                existing_keys.add(key)
                runtime_key = fbp_obj_runtime_token(rig)
                raw_runtime_key = str(
                    getattr(item, "obj_runtime_key", "") or ""
                )
                stored_runtime_key = fbp_normalize_obj_runtime_token(raw_runtime_key)
                if stored_runtime_key != runtime_key or raw_runtime_key != runtime_key:
                    item.obj_runtime_key = runtime_key
            if str(getattr(item, "obj_name", "") or "") != str(getattr(rig, "name", "") or ""):
                item.obj_name = str(getattr(rig, "name", "") or "")
            plane = getattr(rig, "fbp_plane_target", None)
            if plane and object_in_scene(plane, sc):
                plane.is_fbp_plane = True
        except ReferenceError:
            pass

    for obj in sc.objects:
        key = _fbp_object_identity(obj)
        if is_fbp_layer_object(obj) and key not in existing_keys:
            item = sc.fbp_layers.add()
            item.obj = obj
            if key is not None:
                existing_keys.add(key)
            plane = getattr(obj, "fbp_plane_target", None)
            if plane and object_in_scene(plane, sc):
                plane.is_fbp_plane = True
            sc.fbp_layers.move(len(sc.fbp_layers) - 1, 0)

    fbp_rebuild_layer_view_cache(context)
    try:
        fbp_snapshot_layer_plane_links(context)
    except NameError:
        pass
    except Exception as exc:
        fbp_warn("Could not update FBP delete safety snapshot", exc)

    # Keep the Layers UIList tree in sync when operators/import/undo change layers.
    from .ui_layout import fbp_refresh_layer_tree_rows
    if fbp_refresh_layer_tree_rows:
        try:
            fbp_refresh_layer_tree_rows(context)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    try:
        _core().fbp_invalidate_procedural_scene_cache(sc)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    _fbp_scene_object_count_changed(sc, update=True)

# SECTION 02 - Rig / Plane Link Helpers #

def fbp_linked_planes_for_rig(rig, scene=None):
    """Find planes owned by ``rig`` without adopting another live rig's plane."""
    planes = []
    seen = set()
    if not rig:
        return planes

    try:
        objects = list(scene.objects if scene else bpy.data.objects)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        objects = []
    rig_identity = _fbp_object_identity(rig)

    def is_claimed_by_other(obj):
        try:
            parent = getattr(obj, "parent", None)
            if (
                parent
                and _fbp_object_identity(parent) != rig_identity
                and getattr(parent, "is_fbp_control", False)
            ):
                if scene is None or object_in_scene(parent, scene):
                    return True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return True
        for candidate in objects:
            try:
                if (
                    _fbp_object_identity(candidate) == rig_identity
                    or not getattr(candidate, "is_fbp_control", False)
                ):
                    continue
                if getattr(candidate, "fbp_plane_target", None) == obj:
                    return True
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
        return False

    def add_plane(obj, *, fallback=False):
        try:
            key = _fbp_object_identity(obj)
            if (
                key is None
                or key in seen
                or not getattr(obj, "is_fbp_plane", False)
                or bpy.data.objects.get(obj.name) != obj
                or (fallback and is_claimed_by_other(obj))
            ):
                return
            seen.add(key)
            planes.append(obj)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return

    try:
        explicit_target = getattr(rig, "fbp_plane_target", None)
        if (
            explicit_target is not None
            and _fbp_object_identity(getattr(explicit_target, "parent", None)) == rig_identity
        ):
            add_plane(explicit_target)
        else:
            add_plane(explicit_target, fallback=True)
    except ReferenceError:
        pass

    rig_name = str(getattr(rig, "name", "") or "")
    for obj in objects:
        try:
            if not getattr(obj, "is_fbp_plane", False):
                continue
            if _fbp_object_identity(getattr(obj, "parent", None)) == rig_identity:
                add_plane(obj)
                continue
            if getattr(obj, "name", "") == "Plane_" + rig_name:
                add_plane(obj, fallback=True)
                continue
            if str(obj.get("fbp_parent_rig_name", "") or "") == rig_name:
                add_plane(obj, fallback=True)
        except ReferenceError:
            continue
    return planes


# SECTION 03 - Safe Object / Data-block Removal #

def fbp_remove_plane_datablock(plane):
    """Remove a linked FBP plane plus private mesh/material datablocks.

    Never deletes files from disk.

    Important Blender API safety rule: this function must not remove Object,
    Mesh or Material datablocks while a depsgraph_update_post callback is
    running. If a depsgraph handler reaches this function, defer the cleanup to
    a timer and exit without touching bpy.data.*.remove().
    """
    if not plane:
        return False

    if fbp_animation_playback_active():
        fbp_schedule_deferred_orphan_cleanup(
            "fbp_remove_plane_datablock postponed during animation playback",
            first_interval=0.25,
        )
        return False

    try:
        if FBP_DEPSGRAPH_HANDLER_ACTIVE:
            fbp_schedule_deferred_orphan_cleanup("fbp_remove_plane_datablock called from depsgraph")
            return False
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False

    try:
        if bpy.data.objects.get(plane.name) != plane:
            return False
        mesh = getattr(plane, 'data', None)
        mats_to_remove = [mat for mat in mesh.materials if mat] if mesh else []
        bpy.data.objects.remove(plane, do_unlink=True)
        if mesh and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        fbp_remove_unused_materials_and_images(mats_to_remove)
        return True
    except ReferenceError:
        return False
    except Exception as exc:
        fbp_warn("Could not remove linked plane", exc)
        return False

def fbp_snapshot_layer_plane_links(context):
    """Remember one authoritative plane owner for native Delete cleanup.

    A broken Shift+D duplicate may temporarily point at the source rig's plane.
    The previous snapshot assigned that same plane to both rigs and whichever rig
    was visited last overwrote ``fbp_parent_rig_name``. Ownership now follows a
    strict precedence and each plane can appear under only one rig.
    """
    scene = getattr(context, "scene", None) if context else None
    if not scene:
        return

    links = {}
    identities = {}
    try:
        rigs = []
        rig_by_key = {}
        rig_by_name = {}
        target_claimants = {}
        for obj in scene.objects:
            try:
                if not bool(getattr(obj, "is_fbp_control", False)):
                    continue
                rig_key = _fbp_object_identity(obj)
                if rig_key is None:
                    continue
                rigs.append(obj)
                rig_by_key[rig_key] = obj
                rig_by_name[str(getattr(obj, "name", "") or "")] = obj
                target = getattr(obj, "fbp_plane_target", None)
                target_key = _fbp_object_identity(target)
                if (
                    target_key is not None
                    and bool(getattr(target, "is_fbp_plane", False))
                    and object_in_scene(target, scene)
                ):
                    target_claimants.setdefault(target_key, []).append(obj)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue

        owned = {key: [] for key in rig_by_key}
        used_plane_keys = set()
        for plane in scene.objects:
            try:
                if not bool(getattr(plane, "is_fbp_plane", False)):
                    continue
                plane_key = _fbp_object_identity(plane)
                if plane_key is None or plane_key in used_plane_keys:
                    continue

                owner = None
                parent = getattr(plane, "parent", None)
                parent_key = _fbp_object_identity(parent)
                if parent_key in rig_by_key:
                    owner = rig_by_key[parent_key]

                if owner is None:
                    stored_name = str(plane.get("fbp_parent_rig_name", "") or "")
                    owner = rig_by_name.get(stored_name)

                if owner is None:
                    plane_name = str(getattr(plane, "name", "") or "")
                    if plane_name.startswith("Plane_"):
                        owner = rig_by_name.get(plane_name[6:])

                if owner is None:
                    claimants = target_claimants.get(plane_key, ())
                    if len(claimants) == 1:
                        owner = claimants[0]

                owner_key = _fbp_object_identity(owner)
                if owner_key not in owned:
                    continue
                used_plane_keys.add(plane_key)
                owned[owner_key].append(plane)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
                continue

        for rig in rigs:
            rig_key = _fbp_object_identity(rig)
            planes = owned.get(rig_key, ())
            if not planes:
                continue
            rig_name = str(getattr(rig, "name", "") or "")
            plane_names = [str(getattr(plane, "name", "") or "") for plane in planes]
            links[rig_name] = plane_names
            identities[rig_name] = {
                "rig_key": rig_key,
                "planes": {
                    str(getattr(plane, "name", "") or ""): _fbp_object_identity(plane)
                    for plane in planes
                },
            }
            for plane in planes:
                try:
                    plane["fbp_parent_rig_name"] = rig_name
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
                    pass
    except Exception as exc:
        fbp_warn("Could not snapshot FBP rig/plane links", exc)
        return

    try:
        _fbp_set_known_links(scene, links, identities)
    except Exception as exc:
        fbp_warn("Could not store FBP rig/plane links", exc)



# SECTION 04 - Native Delete Cleanup #

def fbp_cleanup_planes_for_deleted_rigs(context):
    """Repair renamed rig links or remove only identity-matched orphan planes."""
    if not context:
        return 0
    scene = getattr(context, "scene", None)
    if not scene:
        return 0
    links = _fbp_get_known_links(scene)
    identities = _fbp_get_known_link_identities(scene)
    removed = 0
    repaired = 0
    changed = False

    try:
        live_rigs = [obj for obj in scene.objects if getattr(obj, "is_fbp_control", False)]
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        live_rigs = []

    def other_live_rig_claims(plane, excluded_identity=None):
        for candidate in live_rigs:
            try:
                candidate_key = _fbp_object_identity(candidate)
                if excluded_identity is not None and candidate_key == excluded_identity:
                    continue
                if getattr(candidate, "fbp_plane_target", None) == plane:
                    return True
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
        try:
            parent = getattr(plane, "parent", None)
            parent_key = _fbp_object_identity(parent)
            if parent and getattr(parent, "is_fbp_control", False):
                if excluded_identity is None or parent_key != excluded_identity:
                    return True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return True
        return False

    for rig_name, plane_names in list(links.items()):
        record = identities.get(rig_name, {})
        stored_rig_key = _fbp_normalize_identity(record.get("rig_key")) if isinstance(record, dict) else None
        stored_plane_keys = dict(record.get("planes", {}) or {}) if isinstance(record, dict) else {}

        rig = bpy.data.objects.get(rig_name)
        rig_alive = False
        try:
            rig_alive = bool(
                rig
                and getattr(rig, "is_fbp_control", False)
                and object_in_scene(rig, scene)
                and (stored_rig_key is None or _fbp_identity_matches(rig, stored_rig_key))
            )
        except ReferenceError:
            rig_alive = False
        if rig_alive:
            continue

        # Identity lookup distinguishes a real rename from a replacement object
        # that merely inherited the old name.
        renamed_rig = _fbp_find_scene_object_by_identity(scene, stored_rig_key)
        try:
            renamed_rig_valid = bool(
                renamed_rig and getattr(renamed_rig, "is_fbp_control", False)
            )
        except ReferenceError:
            renamed_rig_valid = False
        if renamed_rig_valid:
            new_rig_name = str(getattr(renamed_rig, "name", "") or "")
            candidate_planes = []
            for plane_name in plane_names or ():
                plane = _fbp_find_scene_object_by_identity(
                    scene, stored_plane_keys.get(plane_name)
                )
                if plane and getattr(plane, "is_fbp_plane", False):
                    candidate_planes.append(plane)
            if not candidate_planes:
                try:
                    target = getattr(renamed_rig, "fbp_plane_target", None)
                    if target and object_in_scene(target, scene):
                        candidate_planes.append(target)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
            old_plane_name = str(plane_names[0] if plane_names else "")
            new_plane_name = str(getattr(candidate_planes[0], "name", "") or "") if candidate_planes else old_plane_name
            for plane in candidate_planes:
                try:
                    plane["fbp_parent_rig_name"] = new_rig_name
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
                    pass
            _fbp_retarget_runtime_layer_name(
                renamed_rig,
                rig_name,
                new_rig_name,
                old_plane_name=old_plane_name,
                new_plane_name=new_plane_name,
            )
            # Keep this function's local snapshot aligned as well; otherwise a
            # later changed entry could overwrite the retargeted runtime state.
            links.pop(rig_name, None)
            links[new_rig_name] = [
                str(getattr(plane, "name", "") or "") for plane in candidate_planes
            ] or list(plane_names or ())
            identities.pop(rig_name, None)
            identities[new_rig_name] = {
                "rig_key": _fbp_object_identity(renamed_rig),
                "planes": {
                    str(getattr(plane, "name", "") or ""): _fbp_object_identity(plane)
                    for plane in candidate_planes
                },
            }
            try:
                from .geometry_nodes import fbp_retag_effect_owners_after_layer_rename
                fbp_retag_effect_owners_after_layer_rename(
                    renamed_rig,
                    old_plane_name=old_plane_name,
                )
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
                fbp_warn("Could not repair effect owners after a recovered rig rename", exc)
            repaired += 1
            changed = True
            continue

        candidate_planes = []
        seen_plane_keys = set()
        for plane_name in plane_names or ():
            identity = stored_plane_keys.get(plane_name)
            plane = _fbp_find_scene_object_by_identity(scene, identity)
            # Runtime snapshots created before this revision did not include
            # identities. Name fallback is allowed only for those old entries.
            if plane is None and identity is None:
                by_name = bpy.data.objects.get(plane_name)
                if by_name and object_in_scene(by_name, scene):
                    plane = by_name
            key = _fbp_object_identity(plane)
            if key is not None and key not in seen_plane_keys:
                seen_plane_keys.add(key)
                candidate_planes.append(plane)

        changed = True
        for plane in candidate_planes:
            try:
                if not plane or not getattr(plane, "is_fbp_plane", False):
                    continue
                if other_live_rig_claims(plane, stored_rig_key):
                    continue
                used_elsewhere = any(
                    other_scene != scene and object_in_scene(plane, other_scene)
                    for other_scene in bpy.data.scenes
                )
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
            if used_elsewhere:
                continue
            removed += 1 if fbp_remove_plane_datablock(plane) else 0
        links.pop(rig_name, None)
        identities.pop(rig_name, None)

    if changed:
        try:
            _fbp_set_known_links(scene, links, identities)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    if removed:
        cleanup_orphan_fbp_planes(context, force=True)
        sync_layer_collection(context)
    return removed + repaired


def schedule_delete_fbp_rigs(rig_names, *, first_interval=0.35, scene=None):
    """Delete rigs after the current popup/UI event has fully returned.

    Names are paired with the current object pointer so a rename remains valid
    and a new object reusing the old name is never deleted accidentally. The
    task is also bound to its originating Scene.
    """
    names = tuple(dict.fromkeys(str(name) for name in (rig_names or []) if name))
    if not names:
        return False

    scene = scene or getattr(getattr(bpy, "context", None), "scene", None)
    scene_pointer = _fbp_scene_runtime_identity(scene)
    if scene_pointer is None:
        return False
    scene_name = str(getattr(scene, "name", "") or "")
    identities = []
    for name in names:
        rig = bpy.data.objects.get(name)
        key = _fbp_object_identity(rig) if rig and object_in_scene(rig, scene) else None
        identities.append((name, key))
    deadline = time.monotonic() + 30.0

    def _delete_task():
        context = bpy.context
        active_scene = getattr(context, "scene", None) if context else None
        if _fbp_scene_runtime_identity(active_scene) != scene_pointer:
            if time.monotonic() < deadline:
                return 0.5
            fbp_warn(
                f"Deferred rig deletion for Scene '{scene_name}' expired after a Scene switch"
            )
            return None
        if not fbp_stop_playback_for_datablock_cleanup(context):
            return 0.5
        rigs = []
        scene_objects = list(getattr(active_scene, "objects", ()) or ())
        for original_name, expected_key in identities:
            rig = bpy.data.objects.get(original_name)
            if expected_key is not None and _fbp_object_identity(rig) != expected_key:
                rig = next(
                    (obj for obj in scene_objects if _fbp_object_identity(obj) == expected_key),
                    None,
                )
            if expected_key is None:
                # The source object no longer existed when scheduling; never
                # delete a later object merely because it inherited the name.
                continue
            if rig and is_fbp_layer_object(rig) and object_in_scene(rig, active_scene):
                rigs.append(rig)
        if rigs:
            delete_fbp_rigs(context, rigs, defer_if_playing=False)
        return None

    task_token = "|".join(
        f"{name}:{key!r}" for name, key in identities
    )
    return fbp_safe_tasks.schedule_once(
        f'scene.remove_corrupted_generated_planes.{scene_pointer}.{task_token}',
        _delete_task,
        first_interval=max(0.1, float(first_interval)),
    )


def delete_fbp_rigs(context, rigs, *, defer_if_playing=True):
    unique_layers = []
    seen_rig_keys = set()
    for rig in rigs:
        rig_key = _fbp_object_identity(rig)
        if (
            rig_key is not None
            and rig_key not in seen_rig_keys
            and is_fbp_layer_object(rig)
        ):
            seen_rig_keys.add(rig_key)
            unique_layers.append(rig)

    if not unique_layers:
        return 0

    if not fbp_stop_playback_for_datablock_cleanup(context):
        if defer_if_playing:
            schedule_delete_fbp_rigs(
                [getattr(rig, 'name', '') for rig in unique_layers],
                first_interval=0.25,
                scene=getattr(context, "scene", None) if context else None,
            )
        return 0

    deleted = 0
    scene = context.scene if context else None
    for rig in unique_layers:
        try:
            planes = fbp_linked_planes_for_rig(rig, scene)
            for plane in planes:
                fbp_remove_plane_datablock(plane)

            rig_mesh = getattr(rig, 'data', None)
            if bpy.data.objects.get(rig.name) == rig:
                bpy.data.objects.remove(rig, do_unlink=True)
                if rig_mesh and rig_mesh.users == 0:
                    bpy.data.meshes.remove(rig_mesh)
                deleted += 1
        except ReferenceError:
            pass
        except (AttributeError, RuntimeError, TypeError, ValueError, KeyError, IndexError) as exc:
            fbp_warn("Could not delete Frame by Plane rig", exc)

    # Plane removal already cleans FBP-owned unused mesh/material datablocks.
    # Image datablocks remain owned by Blender and are left for explicit Orphan Purge.

    if context:
        cleanup_orphan_fbp_planes(context, force=True)
        sync_layer_collection(context)
    return deleted

# SECTION 05 - Native Shift+D Repair #

def fbp_repair_default_duplicate_rig(rig, context=None):
    """Repair rigs duplicated by Blender's native Shift+D.

    Native Object Duplicate copies the rig object but not its hidden/locked linked
    image plane. The copied rig can therefore keep pointing to the original plane.
    When that stale pointer is detected, create a real plane copy, parent it to the
    duplicated rig and copy the material slots/image material data.
    """
    if not rig or not getattr(rig, "is_fbp_control", False):
        return False
    try:
        plane = getattr(rig, "fbp_plane_target", None)
    except ReferenceError:
        return False
    if not plane or not getattr(plane, "is_fbp_plane", False):
        return False
    try:
        if getattr(plane, "parent", None) == rig:
            # Valid rig/plane pair. Repair readable ownership markers only when
            # the user renamed the rig directly in Blender. Avoid effect scans
            # on ordinary depsgraph updates.
            try:
                old_rig_name = str(plane.get("fbp_parent_rig_name", "") or "")
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
                old_rig_name = ""
            current_name = str(getattr(rig, "name", "") or "")
            name_repaired = old_rig_name != current_name
            if name_repaired:
                plane_name = str(getattr(plane, "name", "") or "")
                try:
                    plane["fbp_parent_rig_name"] = current_name
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
                    pass
                _fbp_retarget_runtime_layer_name(
                    rig,
                    old_rig_name,
                    current_name,
                    old_plane_name=plane_name,
                    new_plane_name=plane_name,
                )
                try:
                    from .geometry_nodes import fbp_retag_effect_owners_after_layer_rename
                    fbp_retag_effect_owners_after_layer_rename(
                        rig,
                        old_plane_name=plane_name,
                    )
                except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
                    fbp_warn("Could not repair effect owners after a manual rig rename", exc)
            return name_repaired
    except ReferenceError:
        return False

    source_plane = plane
    context = context or bpy.context
    target_collections = list(getattr(rig, "users_collection", []) or [])
    if not target_collections and context:
        target_collections = [getattr(context, "collection", None) or context.scene.collection]
    target_collections = [coll for coll in target_collections if coll]
    if not target_collections:
        return False

    new_plane = None
    try:
        new_plane = source_plane.copy()
        if getattr(source_plane, "data", None):
            new_plane.data = source_plane.data.copy()
        new_plane.name = "Plane_" + rig.name
        new_plane.is_fbp_plane = True
        new_plane["fbp_parent_rig_name"] = rig.name
        new_plane.fbp_collection_name = getattr(rig, "fbp_collection_name", "")
        new_plane.hide_select = getattr(source_plane, "hide_select", True)

        for coll in target_collections:
            if not any(existing == new_plane for existing in coll.objects):
                coll.objects.link(new_plane)

        # Keep the same local offset/mesh state, but parent it to the duplicated rig.
        try:
            source_basis = source_plane.matrix_basis.copy()
        except Exception:
            source_basis = None
        new_plane.parent = rig
        if source_basis is not None:
            new_plane.matrix_basis = source_basis
        else:
            new_plane.location = getattr(source_plane, "location", (0, 0, 0))
            new_plane.rotation_euler = getattr(source_plane, "rotation_euler", (0, 0, 0))
            new_plane.scale = getattr(source_plane, "scale", (1, 1, 1))

        fbp_copy_material_slots_unique(source_plane, new_plane)
        rig.fbp_plane_target = new_plane
        rig.fbp_preview_path = getattr(rig, "fbp_preview_path", "") or getattr(getattr(source_plane, "active_material", None), "get", lambda *_: "")("fbp_image_path", "")

        # A duplicated rig must receive fresh persistent effect seeds. Blender
        # copies custom properties during Shift+D, so without this refresh the
        # source and duplicate would remain visually identical when
        # "Unique per Layer" is enabled.
        try:
            from .geometry_nodes import (
                fbp_assign_effect_layer_seed,
                fbp_assign_mesh_wiggle_layer_seed,
                fbp_effect_ids_for_rig,
                fbp_reapply_all_effects,
                fbp_refresh_effect_instance_ids,
                fbp_sync_effect_items,
                fbp_update_mesh_wiggle_modifier,
            )
            # Blender copies modifier/node ID properties during duplication.
            # Refresh the logical stack owner before any effect rebuild so the
            # duplicate never shares persistent instance IDs with its source.
            fbp_refresh_effect_instance_ids(
                rig, force=True, refresh_stack_owner=True
            )
            fbp_assign_mesh_wiggle_layer_seed(rig, force=True)
            for effect_id in fbp_effect_ids_for_rig(rig):
                fbp_assign_effect_layer_seed(rig, effect_id, force=True)
            fbp_update_mesh_wiggle_modifier(rig)
            fbp_reapply_all_effects(rig)
            fbp_sync_effect_items(rig)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass

        fbp_ensure_plane_render_safe(rig, getattr(getattr(context, "scene", None), "frame_current", None))
        do_update_animation(rig)
        do_update_emission(rig)
        do_update_opacity(rig)
        return True
    except Exception as exc:
        try:
            if getattr(rig, 'fbp_plane_target', None) == new_plane:
                rig.fbp_plane_target = source_plane
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        if new_plane:
            try:
                fbp_remove_plane_datablock(new_plane)
            except Exception as cleanup_exc:
                fbp_warn("Could not remove partial duplicated plane", cleanup_exc)
        fbp_warn("Could not repair duplicated rig plane", exc)
        return False

def fbp_repair_default_duplicates(context, candidates=None):
    """Fix selected/new FBP rigs produced by Blender's native duplicate operator."""
    if not context:
        return 0
    repaired = 0
    source = candidates if candidates is not None else list(getattr(context.scene, "objects", []))
    for obj in list(source):
        try:
            if getattr(obj, "is_fbp_control", False):
                repaired += 1 if fbp_repair_default_duplicate_rig(obj, context) else 0
        except ReferenceError:
            continue
    return repaired

# SECTION 06 - Orphan Plane Cleanup #

def cleanup_orphan_fbp_planes(context, force=False):
    if not context:
        return 0
    scene = getattr(context, "scene", None)
    if not scene:
        return 0

    # Never remove Blender ID datablocks synchronously from depsgraph handlers.
    # Schedule the operation and let bpy.app.timers run it when Blender is idle.
    try:
        if FBP_DEPSGRAPH_HANDLER_ACTIVE:
            fbp_schedule_deferred_orphan_cleanup("cleanup_orphan_fbp_planes called from depsgraph")
            return 0
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return 0

    if not force and not getattr(context.scene, 'fbp_auto_clean_orphans', False):
        return 0
    if fbp_animation_playback_active(context):
        fbp_schedule_deferred_orphan_cleanup(
            "cleanup_orphan_fbp_planes postponed during animation playback",
            first_interval=0.25,
        )
        return 0
    removed = 0
    for obj in list(context.scene.objects):
        try:
            if not getattr(obj, "is_fbp_plane", False):
                continue

            keep = False
            parent = getattr(obj, "parent", None)
            if parent:
                try:
                    keep = bool(getattr(parent, "is_fbp_control", False) and object_in_scene(parent, scene))
                except ReferenceError:
                    keep = False

            # Fallback for normal Blender delete: the parent pointer can be cleared,
            # but the plane keeps the original rig name as an ID property.
            rig_name = obj.get("fbp_parent_rig_name", "")
            if not keep and rig_name:
                rig = bpy.data.objects.get(rig_name)
                keep = bool(rig and getattr(rig, "is_fbp_control", False) and object_in_scene(rig, scene))

            if keep:
                continue

            removed += 1 if fbp_remove_plane_datablock(obj) else 0
        except ReferenceError:
            pass
        except Exception as exc:
            fbp_warn("Orphan cleanup skipped object", exc)
    # FBP-owned image/material datablocks are removed by fbp_remove_plane_datablock().
    # Avoid a global purge here so unrelated unused images in the user's .blend are preserved.
    return removed

# SECTION 07 - Timers / Native Operation Sync #

def fbp_initial_sync_timer():
    """One-shot sync after registration. Not a recurring 0.05s poll."""
    if fbp_background_sync_should_pause(getattr(bpy, "context", None)):
        return 0.50
    if bpy.context:
        sync_layer_collection(bpy.context)
    return None

def fbp_known_links_have_deleted_rig(scene):
    """Detect deletion, replacement or rename using the stored rig identity."""
    links = _fbp_get_known_links(scene)
    if not links:
        return False
    identities = _fbp_get_known_link_identities(scene)
    for rig_name in list(links.keys()):
        record = identities.get(rig_name, {})
        expected = _fbp_normalize_identity(record.get("rig_key")) if isinstance(record, dict) else None
        rig = bpy.data.objects.get(rig_name)
        try:
            if (
                not rig
                or not getattr(rig, "is_fbp_control", False)
                or not object_in_scene(rig, scene)
                or (expected is not None and not _fbp_identity_matches(rig, expected))
            ):
                return True
        except ReferenceError:
            return True
    return False


def fbp_depsgraph_updated_fbp_rigs(depsgraph, scene=None):
    """Return only FBP rig candidates touched by the current depsgraph update."""
    candidates = []
    seen = set()
    if not depsgraph:
        return candidates
    try:
        updates = depsgraph.updates
    except (AttributeError, ReferenceError, RuntimeError):
        return candidates

    for update in updates:
        try:
            data = getattr(update, "id", None)
            if not isinstance(data, bpy.types.Object):
                continue
            obj = data
            rig = None
            if getattr(obj, "is_fbp_control", False):
                rig = obj
            elif getattr(obj, "is_fbp_plane", False):
                parent = getattr(obj, "parent", None)
                if parent and getattr(parent, "is_fbp_control", False):
                    rig = parent
            if not rig:
                continue
            if scene and not object_in_scene(rig, scene):
                continue
            key = rig.as_pointer()
            if key in seen:
                continue
            seen.add(key)
            candidates.append(rig)
        except ReferenceError:
            continue
        except (AttributeError, TypeError, RuntimeError) as exc:
            fbp_warn("Could not inspect depsgraph update", exc)
    return candidates


def fbp_depsgraph_has_orphan_fbp_plane(depsgraph, scene=None):
    """Fast native-delete hint: detect touched FBP planes whose rig vanished.

    This covers the case where the rig/plane snapshot is stale or empty, so the
    normal Blender X delete would otherwise wait for the slow cleanup timer.
    """
    if not depsgraph:
        return False
    try:
        updates = depsgraph.updates
    except (AttributeError, ReferenceError, RuntimeError):
        return False
    for update in updates:
        try:
            obj = getattr(update, "id", None)
            if not isinstance(obj, bpy.types.Object):
                continue
            if not getattr(obj, "is_fbp_plane", False):
                continue
            if scene and not object_in_scene(obj, scene):
                continue
            parent = getattr(obj, "parent", None)
            if not parent or not getattr(parent, "is_fbp_control", False) or (scene and not object_in_scene(parent, scene)):
                return True
        except ReferenceError:
            return True
        except (AttributeError, TypeError, RuntimeError) as exc:
            fbp_warn("Could not inspect possible orphan FBP plane", exc)
    return False

def fbp_scene_has_broken_native_duplicate(scene=None, *, depsgraph=None, candidates=None):
    """Detect native Shift+D copies where the copied rig still points to the source plane.

    In depsgraph handlers this stays O(K): only the updated objects are checked.
    The older O(N) full-scene scan remains available for explicit repair tools and
    the slow safety timer.
    """
    if candidates is None and depsgraph is not None:
        candidates = fbp_depsgraph_updated_fbp_rigs(depsgraph, scene)
    if candidates is None:
        if not scene:
            return False
        candidates = fbp_scene_fallback_candidates(scene)

    for obj in candidates:
        try:
            if not getattr(obj, "is_fbp_control", False):
                continue
            if scene and not object_in_scene(obj, scene):
                continue
            plane = getattr(obj, "fbp_plane_target", None)
            if plane and getattr(plane, "is_fbp_plane", False):
                if getattr(plane, "parent", None) != obj:
                    return True
                try:
                    stored_name = str(plane.get("fbp_parent_rig_name", "") or "")
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
                    stored_name = ""
                if stored_name != str(getattr(obj, "name", "") or ""):
                    # The rig was renamed directly in Blender. Reuse the same
                    # deferred repair path so ownership markers are never
                    # mutated from depsgraph_update_post.
                    return True
        except ReferenceError:
            return True
        except (AttributeError, TypeError, RuntimeError) as exc:
            fbp_warn("Could not check duplicated FBP rig", exc)
    return False

def fbp_run_native_ops_sync(
    context,
    scene=None,
    *,
    force=False,
    depsgraph=None,
    candidate_rigs=None,
    delete_hint=None,
    duplicate_hint=None,
    refresh_layers=True,
):
    """Repair native Delete/Shift+D side effects with minimal scene scans.

    Explicit hints let callers reuse checks they already performed instead of
    repeating an O(scene size) fallback scan immediately before the repair.
    """
    if not context:
        return 0
    scene = scene or getattr(context, "scene", None)
    if not scene:
        return 0

    needs_delete_cleanup = bool(force) or (
        bool(delete_hint)
        if delete_hint is not None
        else fbp_known_links_have_deleted_rig(scene)
    )
    needs_duplicate_repair = bool(force) or (
        bool(duplicate_hint)
        if duplicate_hint is not None
        else fbp_scene_has_broken_native_duplicate(
            scene, depsgraph=depsgraph, candidates=candidate_rigs
        )
    )
    if not needs_delete_cleanup and not needs_duplicate_repair:
        return 0

    changed = 0
    try:
        if needs_delete_cleanup:
            changed += int(fbp_cleanup_planes_for_deleted_rigs(context) or 0)
        if needs_duplicate_repair:
            changed += int(fbp_repair_default_duplicates(context, candidates=candidate_rigs) or 0)
        if (changed or force) and refresh_layers:
            sync_layer_collection(context)
    except Exception as exc:
        fbp_warn("Native delete/duplicate sync failed", exc)
    return changed

FBP_NATIVE_OPS_SYNC_RUNNING = False
FBP_DEPSGRAPH_HANDLER_ACTIVE = False


def _fbp_fallback_scan_clock(scene, now):
    """Return a bounded per-Scene safety-scan clock.

    A single global timestamp allowed activity in one Scene to postpone orphan
    and duplicate checks in every other Scene. Keeping small name/pointer keys
    makes scene switching deterministic without retaining Blender RNA objects.
    """
    key = _fbp_scene_cache_key(scene)
    if key is None:
        return None, {"duplicate": 0.0, "orphan": 0.0, "seen": now}
    clock = _FBP_FALLBACK_SCAN_CLOCKS.get(key)
    if not isinstance(clock, dict):
        clock = {"duplicate": 0.0, "orphan": 0.0, "seen": now}
        if len(_FBP_FALLBACK_SCAN_CLOCKS) >= 32 and key not in _FBP_FALLBACK_SCAN_CLOCKS:
            oldest_key = min(
                _FBP_FALLBACK_SCAN_CLOCKS,
                key=lambda item: float(
                    _FBP_FALLBACK_SCAN_CLOCKS[item].get("seen", 0.0) or 0.0
                ),
            )
            _FBP_FALLBACK_SCAN_CLOCKS.pop(oldest_key, None)
        _FBP_FALLBACK_SCAN_CLOCKS[key] = clock
    clock["seen"] = now
    return key, clock


def fbp_reset_deferred_sync_state():
    """Release local dedupe guards and fallback scan clocks."""
    global FBP_NATIVE_OPS_SYNC_RUNNING
    global FBP_DEPSGRAPH_HANDLER_ACTIVE
    FBP_NATIVE_OPS_SYNC_RUNNING = False
    FBP_DEPSGRAPH_HANDLER_ACTIVE = False
    _FBP_SCENE_OBJECT_COUNT_CACHE.clear()
    _FBP_FALLBACK_SCAN_CLOCKS.clear()
    fbp_clear_known_link_snapshots()
    try:
        from .drawing_plane import clear_drawing_runtime_cache
        clear_drawing_runtime_cache()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


def fbp_deferred_orphan_cleanup_timer(scene_pointer=None):
    """Run one Scene-bound orphan/delete cleanup outside depsgraph evaluation.

    If the user switches Scenes before the timer fires, exit instead of mutating
    the wrong Scene. Native depsgraph and fallback checks will reschedule the task
    when the original Scene becomes active again.
    """
    global FBP_NATIVE_OPS_SYNC_RUNNING

    try:
        if FBP_DEPSGRAPH_HANDLER_ACTIVE:
            return 0.03
    except NameError:
        pass

    if fbp_undo_is_active():
        return 0.5

    context = bpy.context
    if fbp_background_sync_should_pause(context):
        return 0.5
    scene = getattr(context, "scene", None) if context else None
    if not context or not scene:
        return None
    if scene_pointer is not None:
        try:
            if int(scene.as_pointer()) != int(scene_pointer):
                return None
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return None

    changed = 0
    try:
        FBP_NATIVE_OPS_SYNC_RUNNING = True

        candidates = fbp_scene_fallback_candidates(scene)
        has_deleted_rig = fbp_known_links_have_deleted_rig(scene)
        has_broken_duplicate = fbp_scene_has_broken_native_duplicate(
            scene, candidates=candidates
        )
        if has_deleted_rig or has_broken_duplicate:
            changed += int(
                fbp_run_native_ops_sync(
                    context,
                    scene,
                    force=False,
                    delete_hint=has_deleted_rig,
                    duplicate_hint=has_broken_duplicate,
                    refresh_layers=False,
                ) or 0
            )

        if bool(getattr(scene, 'fbp_auto_clean_orphans', False)) and fbp_scene_has_orphan_fbp_plane_light(scene, candidates=candidates):
            changed += int(cleanup_orphan_fbp_planes(context, force=False) or 0)

        if changed:
            sync_layer_collection(context)
    except Exception as exc:
        fbp_warn("Deferred orphan cleanup timer skipped", exc)
    finally:
        FBP_NATIVE_OPS_SYNC_RUNNING = False

    return None


def fbp_schedule_deferred_orphan_cleanup(reason="", first_interval=0.03):
    """Schedule one Scene-bound cleanup outside depsgraph evaluation."""
    del reason  # Kept in the public call signature for readable call sites.
    scene = getattr(getattr(bpy, "context", None), "scene", None)
    if not scene:
        return False
    try:
        scene_pointer = int(scene.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False

    def _timer():
        return fbp_deferred_orphan_cleanup_timer(scene_pointer)

    return fbp_safe_tasks.schedule_once(
        f"scene_sync.deferred_orphan_cleanup.{scene_pointer}",
        _timer,
        first_interval=first_interval,
    )


# SECTION 08 - Depsgraph Native Ops Handler #

@bpy.app.handlers.persistent
def fbp_depsgraph_native_ops_handler(scene, depsgraph):
    """Observe native X/Delete and Shift+D, then defer every mutation.

    Blender 5.1+ must not create, link or remove ID datablocks while the
    depsgraph is evaluating. This handler therefore only inspects state and
    schedules fbp_deferred_orphan_cleanup_timer(). Object removal, mesh/image/
    material removal and duplicate-plane repair all run from the timer.
    """
    # Render depsgraph updates are not native edit operations. Inspecting every
    # evaluated frame wastes time and can queue repairs while render workers are
    # reading image/material data. The render-session guard owns this period.
    if bool(fbp_runtime_get("fbp_render_guard_active", False)) or fbp_render_job_active():
        return
    if fbp_undo_is_active():
        return

    global FBP_DEPSGRAPH_HANDLER_ACTIVE

    if FBP_NATIVE_OPS_SYNC_RUNNING:
        return

    context = bpy.context
    if not context or not scene or getattr(context, "scene", None) != scene:
        return

    FBP_DEPSGRAPH_HANDLER_ACTIVE = True
    try:
        candidate_rigs = fbp_depsgraph_updated_fbp_rigs(depsgraph, scene)
        try:
            from .drawing_plane import fbp_depsgraph_schedule_drawing_updates
            fbp_depsgraph_schedule_drawing_updates(scene, candidate_rigs)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        topology_changed = _fbp_scene_object_count_changed(scene, update=True)
        has_deleted_rig = (
            topology_changed and fbp_known_links_have_deleted_rig(scene)
        )
        auto_clean = bool(getattr(scene, 'fbp_auto_clean_orphans', False))
        has_orphan_plane = auto_clean and fbp_depsgraph_has_orphan_fbp_plane(depsgraph, scene)
        has_broken_duplicate = fbp_scene_has_broken_native_duplicate(scene, candidates=candidate_rigs)

        if not has_deleted_rig and not has_orphan_plane and not has_broken_duplicate:
            return

        # Definitive safety rule:
        # whether this is X/Delete cleanup or Shift+D duplicate repair, do not
        # touch Blender ID memory from depsgraph_update_post. The timer will run
        # immediately after Blender returns to an idle/safe state.
        fbp_schedule_deferred_orphan_cleanup("depsgraph native ops repair", first_interval=0.03)

    except Exception as exc:
        fbp_warn("Depsgraph native operation handler skipped", exc)
    finally:
        FBP_DEPSGRAPH_HANDLER_ACTIVE = False

def fbp_scene_has_orphan_fbp_plane_light(scene=None, *, candidates=None):
    """Cheap safety-net check used by the slow cleanup timer.

    The timer should not rebuild the whole Layer UI every few seconds. It first
    checks whether at least one FBP plane actually looks orphaned; only then it
    runs the heavier cleanup/sync path.
    """
    scene = scene or getattr(bpy.context, "scene", None)
    if not scene:
        return False
    if candidates is None:
        candidates = fbp_scene_fallback_candidates(scene)
    try:
        for obj in list(candidates or ()):
            if not getattr(obj, "is_fbp_plane", False):
                continue
            parent = getattr(obj, "parent", None)
            if parent and getattr(parent, "is_fbp_control", False) and object_in_scene(parent, scene):
                continue
            rig_name = ""
            try:
                rig_name = obj.get("fbp_parent_rig_name", "")
            except Exception:
                rig_name = ""
            if rig_name:
                rig = bpy.data.objects.get(rig_name)
                if rig and getattr(rig, "is_fbp_control", False) and object_in_scene(rig, scene):
                    continue
            return True
    except Exception as exc:
        fbp_warn("Could not inspect possible orphan FBP planes", exc)
    return False


def cleanup_orphan_fbp_planes_timer():
    """Low-frequency safety net for changes missed by depsgraph notifications."""
    interval = FBP_FALLBACK_TIMER_INTERVAL

    context = bpy.context
    # This callback runs from Blender's idle timer and is therefore a safe backup
    # if the dedicated persistent watchdog was lost during a reload.
    fbp_undo_is_active(release_expired=True)
    if fbp_background_sync_should_pause(context):
        return interval
    scene = getattr(context, "scene", None) if context else None
    if not context or not scene:
        return interval

    changed = 0
    try:
        now = time.monotonic()
        _clock_key, scan_clock = _fbp_fallback_scan_clock(scene, now)
        known_links = _fbp_get_known_links(scene)
        has_deleted_rig = bool(known_links) and fbp_known_links_have_deleted_rig(scene)
        duplicate_scan_due = (
            now - float(scan_clock.get("duplicate", 0.0) or 0.0)
            >= FBP_FALLBACK_DUPLICATE_SCAN_INTERVAL
        )
        auto_clean = bool(getattr(scene, 'fbp_auto_clean_orphans', False))
        orphan_scan_due = (
            auto_clean
            and now - float(scan_clock.get("orphan", 0.0) or 0.0)
            >= FBP_FALLBACK_ORPHAN_SCAN_INTERVAL
        )
        if not has_deleted_rig and not duplicate_scan_due and not orphan_scan_due:
            return interval

        # Build the cached/tagged candidate set only when a safety scan is due.
        # The common 10-second timer pulse otherwise performs no collection walk.
        candidates = (
            fbp_scene_fallback_candidates(scene)
            if duplicate_scan_due or orphan_scan_due
            else []
        )
        # Record completed empty scans as well; otherwise an empty project would
        # repeat the collection-cache walk on every 10-second timer pulse.
        if duplicate_scan_due:
            scan_clock["duplicate"] = now
        if orphan_scan_due:
            scan_clock["orphan"] = now
        if not candidates and not known_links:
            return interval

        # Shift+D is normally caught from touched depsgraph objects. Keep a
        # much slower cached/tagged-object scan only as a safety net.
        has_broken_duplicate = False
        if duplicate_scan_due:
            has_broken_duplicate = fbp_scene_has_broken_native_duplicate(
                scene, candidates=candidates
            )

        if has_deleted_rig or has_broken_duplicate:
            changed += int(
                fbp_run_native_ops_sync(
                    context,
                    scene,
                    force=False,
                    delete_hint=has_deleted_rig,
                    duplicate_hint=has_broken_duplicate,
                    refresh_layers=False,
                ) or 0
            )

        if orphan_scan_due:
            if fbp_scene_has_orphan_fbp_plane_light(scene, candidates=candidates):
                changed += int(cleanup_orphan_fbp_planes(context, force=False) or 0)

        if changed:
            sync_layer_collection(context)
    except Exception as exc:
        fbp_warn("Slow orphan cleanup timer skipped", exc)
    return interval
