"""Layer synchronization, native delete/duplicate repair and orphan cleanup."""

import bpy
import json
import time

try:
    from . import safe_tasks as fbp_safe_tasks
except ImportError:
    import safe_tasks as fbp_safe_tasks

try:
    from .materials import (
        fbp_remove_unused_materials_and_images,
        fbp_copy_material_slots_unique,
        do_update_emission,
        do_update_opacity,
    )
except ImportError:
    from materials import (
        fbp_remove_unused_materials_and_images,
        fbp_copy_material_slots_unique,
        do_update_emission,
        do_update_opacity,
    )


def _core():
    try:
        from . import core as _core_mod
    except ImportError:
        import core as _core_mod
    return _core_mod


def fbp_warn(message, exc=None):
    return _core().fbp_warn(message, exc)


def object_in_scene(obj, scene=None):
    return _core().object_in_scene(obj, scene)


def is_fbp_layer_object(obj):
    return _core().is_fbp_layer_object(obj)


def fbp_rebuild_layer_view_cache(context=None):
    return _core().fbp_rebuild_layer_view_cache(context)


def fbp_runtime_get(key, default=None):
    return _core().fbp_runtime_get(key, default)


def fbp_runtime_set(key, value):
    return _core().fbp_runtime_set(key, value)


def fbp_fast_import_is_active():
    return _core().fbp_fast_import_is_active()


def fbp_undo_is_active():
    try:
        return bool(fbp_runtime_get("fbp_undo_in_progress", False))
    except Exception:
        return False


def do_update_animation(obj, context=None):
    return _core().do_update_animation(obj)


def fbp_ensure_plane_render_safe(rig):
    return _core().fbp_ensure_plane_render_safe(rig)


# SECTION 01 - Layer Collection Sync #

def sync_layer_collection(context):
    if fbp_undo_is_active():
        return
    sc = context.scene
    for i in range(len(sc.fbp_layers) - 1, -1, -1):
        try:
            item = sc.fbp_layers[i]
            if not item.obj or not object_in_scene(item.obj, sc):
                sc.fbp_layers.remove(i)
        except ReferenceError:
            sc.fbp_layers.remove(i)

    existing_objs = []
    for item in sc.fbp_layers:
        try:
            if item.obj and object_in_scene(item.obj, sc):
                existing_objs.append(item.obj)
                plane = getattr(item.obj, "fbp_plane_target", None)
                if plane and object_in_scene(plane, sc):
                    plane.is_fbp_plane = True
        except ReferenceError:
            pass

    for obj in sc.objects:
        if is_fbp_layer_object(obj) and obj not in existing_objs:
            item = sc.fbp_layers.add()
            item.obj = obj
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
    try:
        from .ui_layout import fbp_refresh_layer_tree_rows
    except ImportError:
        try:
            from ui_layout import fbp_refresh_layer_tree_rows
        except ImportError:
            fbp_refresh_layer_tree_rows = None
    if fbp_refresh_layer_tree_rows:
        try:
            fbp_refresh_layer_tree_rows(context)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass

# SECTION 02 - Rig / Plane Link Helpers #

def fbp_linked_planes_for_rig(rig, scene=None):
    """Find every render plane that belongs to a rig, even if the pointer is stale."""
    planes = []
    if not rig:
        return planes

    def add_plane(obj):
        try:
            if obj and getattr(obj, "is_fbp_plane", False) and bpy.data.objects.get(obj.name) == obj and obj not in planes:
                planes.append(obj)
        except ReferenceError:
            pass

    try:
        add_plane(getattr(rig, "fbp_plane_target", None))
    except ReferenceError:
        pass

    objects = list(scene.objects) if scene else list(bpy.data.objects)
    for obj in objects:
        try:
            if not getattr(obj, "is_fbp_plane", False):
                continue
            if getattr(obj, "parent", None) == rig:
                add_plane(obj)
                continue
            if getattr(obj, "name", "") == "Plane_" + getattr(rig, "name", ""):
                add_plane(obj)
                continue
            if obj.get("fbp_parent_rig_name", "") == getattr(rig, "name", ""):
                add_plane(obj)
        except ReferenceError:
            continue
    return planes

# SECTION 03 - Safe Object / Data-block Removal #

def fbp_remove_plane_datablock(plane):
    """Remove a linked FBP plane plus private mesh/material/image datablocks.

    Never deletes files from disk.

    Important Blender API safety rule: this function must not remove Object,
    Mesh, Material or Image datablocks while a depsgraph_update_post callback is
    running. If a depsgraph handler reaches this function, defer the cleanup to
    a timer and exit without touching bpy.data.*.remove().
    """
    if not plane:
        return False

    try:
        if FBP_DEPSGRAPH_HANDLER_ACTIVE:
            fbp_schedule_deferred_orphan_cleanup("fbp_remove_plane_datablock called from depsgraph")
            return False
    except NameError:
        # Module is still initializing: fall through to the old behavior only
        # outside handler execution.
        pass
    except Exception:
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
        print(f"[FBP] Could not remove linked plane: {exc}")
        return False

def fbp_snapshot_layer_plane_links(context):
    """Remember valid rig -> plane links so a normal Blender X delete can be cleaned later."""
    if not context:
        return
    links = {}
    try:
        for rig in list(context.scene.objects):
            if not getattr(rig, "is_fbp_control", False):
                continue
            planes = fbp_linked_planes_for_rig(rig, context.scene)
            if planes:
                links[rig.name] = [plane.name for plane in planes if plane and bpy.data.objects.get(plane.name) == plane]
                for plane in planes:
                    try:
                        plane["fbp_parent_rig_name"] = rig.name
                    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                        pass
    except Exception as exc:
        fbp_warn("Could not snapshot FBP rig/plane links", exc)
        return
    try:
        fbp_runtime_set("fbp_known_rig_plane_links", json.dumps(links), context)
    except Exception as exc:
        fbp_warn("Could not serialize FBP rig/plane links", exc)

# SECTION 04 - Native Delete Cleanup #

def fbp_cleanup_planes_for_deleted_rigs(context):
    """After native X/Delete removes only a rig, remove its remembered image plane too."""
    if not context:
        return 0
    raw = fbp_runtime_get("fbp_known_rig_plane_links", "{}", context) or "{}"
    try:
        links = json.loads(raw) if isinstance(raw, str) else {}
    except Exception:
        links = {}
    removed = 0
    changed = False
    for rig_name, plane_names in list(links.items()):
        rig = bpy.data.objects.get(rig_name)
        rig_alive = bool(rig and getattr(rig, "is_fbp_control", False) and object_in_scene(rig, context.scene))
        if rig_alive:
            continue

        # If the rig was only renamed in Blender, the remembered name disappears
        # but the plane still has a live FBP parent. Update the snapshot instead
        # of treating the layer as deleted.
        live_parent = None
        live_plane_names = []
        for plane_name in plane_names or []:
            plane = bpy.data.objects.get(plane_name)
            try:
                parent = getattr(plane, "parent", None) if plane else None
                if plane and parent and getattr(parent, "is_fbp_control", False) and object_in_scene(parent, context.scene):
                    live_parent = parent
                    live_plane_names.append(plane.name)
            except ReferenceError:
                continue
        if live_parent:
            links.pop(rig_name, None)
            links[live_parent.name] = live_plane_names
            for plane_name in live_plane_names:
                plane = bpy.data.objects.get(plane_name)
                if plane:
                    try:
                        plane["fbp_parent_rig_name"] = live_parent.name
                    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                        pass
            changed = True
            continue

        changed = True
        for plane_name in plane_names or []:
            plane = bpy.data.objects.get(plane_name)
            if plane and getattr(plane, "is_fbp_plane", False):
                removed += 1 if fbp_remove_plane_datablock(plane) else 0
        links.pop(rig_name, None)
    if changed:
        try:
            fbp_runtime_set("fbp_known_rig_plane_links", json.dumps(links), context)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    if removed:
        cleanup_orphan_fbp_planes(context, force=True)
        sync_layer_collection(context)
    return removed

def schedule_delete_fbp_rigs(rig_names, *, first_interval=0.35):
    """Delete named rigs after the current popup/UI event has fully returned."""
    names = tuple(dict.fromkeys(str(name) for name in (rig_names or []) if name))
    if not names:
        return False

    def _delete_task():
        context = bpy.context
        rigs = []
        for name in names:
            rig = bpy.data.objects.get(name)
            if rig and is_fbp_layer_object(rig):
                rigs.append(rig)
        if rigs:
            delete_fbp_rigs(context, rigs)
        return None

    return fbp_safe_tasks.schedule_once(
        'scene.remove_corrupted_generated_planes',
        _delete_task,
        first_interval=max(0.1, float(first_interval)),
    )


def delete_fbp_rigs(context, rigs):
    unique_layers = []
    for rig in rigs:
        if rig and is_fbp_layer_object(rig) and rig not in unique_layers:
            unique_layers.append(rig)

    if not unique_layers:
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

    # Plane removal already cleans the FBP-owned unused mesh/material/image datablocks.
    # Do not purge every unused image in the file: users may keep unrelated images as references.

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
            # Valid rig/plane pair. Keep the fallback name marker fresh after renames.
            try:
                plane["fbp_parent_rig_name"] = rig.name
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
            return False
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

        fbp_ensure_plane_render_safe(rig, getattr(getattr(context, "scene", None), "frame_current", None))
        do_update_animation(rig)
        do_update_emission(rig)
        do_update_opacity(rig)
        return True
    except Exception as exc:
        print(f"[FBP] Could not repair duplicated rig plane: {exc}")
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

    # Never remove Blender ID datablocks synchronously from depsgraph handlers.
    # Schedule the operation and let bpy.app.timers run it when Blender is idle.
    try:
        if FBP_DEPSGRAPH_HANDLER_ACTIVE:
            fbp_schedule_deferred_orphan_cleanup("cleanup_orphan_fbp_planes called from depsgraph")
            return 0
    except NameError:
        pass

    if not force and not getattr(context.scene, 'fbp_auto_clean_orphans', False):
        return 0
    removed = 0
    removed_meshes = []
    for obj in list(context.scene.objects):
        try:
            if not getattr(obj, "is_fbp_plane", False):
                continue

            keep = False
            parent = getattr(obj, "parent", None)
            if parent:
                try:
                    keep = bool(getattr(parent, "is_fbp_control", False) and object_in_scene(parent, context.scene))
                except ReferenceError:
                    keep = False

            # Fallback for normal Blender delete: the parent pointer can be cleared,
            # but the plane keeps the original rig name as an ID property.
            rig_name = obj.get("fbp_parent_rig_name", "")
            if not keep and rig_name:
                rig = bpy.data.objects.get(rig_name)
                keep = bool(rig and getattr(rig, "is_fbp_control", False) and object_in_scene(rig, context.scene))

            if keep:
                continue

            removed += 1 if fbp_remove_plane_datablock(obj) else 0
        except ReferenceError:
            pass
        except Exception as exc:
            print(f"[FBP] Orphan cleanup skipped object: {exc}")
    for mesh in removed_meshes:
        try:
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    # FBP-owned image/material datablocks are removed by fbp_remove_plane_datablock().
    # Avoid a global purge here so unrelated unused images in the user's .blend are preserved.
    return removed

# SECTION 07 - Timers / Native Operation Sync #

def fbp_initial_sync_timer():
    """One-shot sync after registration. Not a recurring 0.05s poll."""
    if bpy.context:
        sync_layer_collection(bpy.context)
    return None

def fbp_known_links_have_deleted_rig(scene):
    """Fast check used by the depsgraph handler before running any cleanup."""
    raw = fbp_runtime_get("fbp_known_rig_plane_links", "{}") or "{}"
    try:
        links = json.loads(raw) if isinstance(raw, str) else {}
    except Exception:
        return False
    if not links:
        return False
    for rig_name in list(links.keys()):
        rig = bpy.data.objects.get(rig_name)
        try:
            if not rig or not getattr(rig, "is_fbp_control", False) or not object_in_scene(rig, scene):
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
        candidates = list(scene.objects)

    for obj in candidates:
        try:
            if not getattr(obj, "is_fbp_control", False):
                continue
            if scene and not object_in_scene(obj, scene):
                continue
            plane = getattr(obj, "fbp_plane_target", None)
            if plane and getattr(plane, "is_fbp_plane", False) and getattr(plane, "parent", None) != obj:
                return True
        except ReferenceError:
            return True
        except (AttributeError, TypeError, RuntimeError) as exc:
            fbp_warn("Could not check duplicated FBP rig", exc)
    return False

def fbp_run_native_ops_sync(context, scene=None, *, force=False, depsgraph=None, candidate_rigs=None):
    """Repair native Delete/Shift+D side effects with minimal scene scans."""
    if not context:
        return 0
    scene = scene or getattr(context, "scene", None)
    if not scene:
        return 0

    needs_delete_cleanup = force or fbp_known_links_have_deleted_rig(scene)
    needs_duplicate_repair = force or fbp_scene_has_broken_native_duplicate(scene, depsgraph=depsgraph, candidates=candidate_rigs)
    if not needs_delete_cleanup and not needs_duplicate_repair:
        return 0

    changed = 0
    try:
        if needs_delete_cleanup:
            changed += int(fbp_cleanup_planes_for_deleted_rigs(context) or 0)
        if needs_duplicate_repair:
            changed += int(fbp_repair_default_duplicates(context, candidates=candidate_rigs) or 0)
        if changed or force:
            sync_layer_collection(context)
            fbp_snapshot_layer_plane_links(context)
    except Exception as exc:
        fbp_warn("Native delete/duplicate sync failed", exc)
    return changed

FBP_NATIVE_OPS_SYNC_RUNNING = False
FBP_LAST_ORPHAN_LIGHT_SCAN = 0.0
FBP_DEPSGRAPH_HANDLER_ACTIVE = False
FBP_DEFERRED_ORPHAN_CLEANUP_SCHEDULED = False


def fbp_reset_deferred_sync_state():
    """Release local dedupe guards when pending timers are cancelled."""
    global FBP_DEFERRED_ORPHAN_CLEANUP_SCHEDULED
    global FBP_NATIVE_OPS_SYNC_RUNNING
    global FBP_DEPSGRAPH_HANDLER_ACTIVE
    FBP_DEFERRED_ORPHAN_CLEANUP_SCHEDULED = False
    FBP_NATIVE_OPS_SYNC_RUNNING = False
    FBP_DEPSGRAPH_HANDLER_ACTIVE = False


def fbp_deferred_orphan_cleanup_timer():
    """Run orphan/delete cleanup outside depsgraph evaluation.

    This is the only place scheduled by fbp_depsgraph_native_ops_handler where
    destructive datablock removal is allowed. It executes from Blender's timer
    system, after the depsgraph callback has returned.
    """
    global FBP_DEFERRED_ORPHAN_CLEANUP_SCHEDULED
    global FBP_NATIVE_OPS_SYNC_RUNNING

    FBP_DEFERRED_ORPHAN_CLEANUP_SCHEDULED = False

    # Extra guard: if Blender ever runs this timer while our depsgraph handler
    # is still active, wait one more tick instead of touching ID datablocks.
    try:
        if FBP_DEPSGRAPH_HANDLER_ACTIVE:
            FBP_DEFERRED_ORPHAN_CLEANUP_SCHEDULED = True
            return 0.03
    except NameError:
        pass

    if fbp_undo_is_active():
        FBP_DEFERRED_ORPHAN_CLEANUP_SCHEDULED = True
        return 0.25

    context = bpy.context
    scene = getattr(context, "scene", None) if context else None
    if not context or not scene:
        return None

    changed = 0
    try:
        FBP_NATIVE_OPS_SYNC_RUNNING = True

        # Handle remembered rig -> plane links and duplicate repair here, not in
        # depsgraph_update_post. This may call fbp_remove_plane_datablock(), so it
        # must stay outside depsgraph evaluation.
        if fbp_known_links_have_deleted_rig(scene) or fbp_scene_has_broken_native_duplicate(scene):
            changed += int(fbp_run_native_ops_sync(context, scene, force=False) or 0)

        # Handle stale or snapshot-less orphan planes here as well.
        if fbp_scene_has_orphan_fbp_plane_light(scene):
            changed += int(cleanup_orphan_fbp_planes(context, force=True) or 0)

        if changed:
            sync_layer_collection(context)
            fbp_snapshot_layer_plane_links(context)
    except Exception as exc:
        fbp_warn("Deferred orphan cleanup timer skipped", exc)
    finally:
        FBP_NATIVE_OPS_SYNC_RUNNING = False

    return None


def fbp_schedule_deferred_orphan_cleanup(reason="", first_interval=0.03):
    """Schedule orphan cleanup once, outside depsgraph evaluation."""
    del reason  # Kept in the public call signature for readable call sites.
    global FBP_DEFERRED_ORPHAN_CLEANUP_SCHEDULED

    if FBP_DEFERRED_ORPHAN_CLEANUP_SCHEDULED:
        return False

    FBP_DEFERRED_ORPHAN_CLEANUP_SCHEDULED = True
    scheduled = fbp_safe_tasks.schedule_once(
        "scene_sync.deferred_orphan_cleanup",
        fbp_deferred_orphan_cleanup_timer,
        first_interval=first_interval,
    )
    if scheduled:
        return True
    # Do not leave the local dedupe flag stuck when the central scheduler
    # rejects/fails the request. A later depsgraph pulse can safely retry.
    FBP_DEFERRED_ORPHAN_CLEANUP_SCHEDULED = False
    return False


# SECTION 08 - Depsgraph Native Ops Handler #

@bpy.app.handlers.persistent
def fbp_depsgraph_native_ops_handler(scene, depsgraph):
    """Observe native X/Delete and Shift+D, then defer every mutation.

    Blender 5.1+ must not create, link or remove ID datablocks while the
    depsgraph is evaluating. This handler therefore only inspects state and
    schedules fbp_deferred_orphan_cleanup_timer(). Object removal, mesh/image/
    material removal and duplicate-plane repair all run from the timer.
    """
    if fbp_undo_is_active():
        return

    global FBP_LAST_ORPHAN_LIGHT_SCAN
    global FBP_DEPSGRAPH_HANDLER_ACTIVE

    if FBP_NATIVE_OPS_SYNC_RUNNING:
        return

    context = bpy.context
    if not context or not scene or getattr(context, "scene", None) != scene:
        return

    FBP_DEPSGRAPH_HANDLER_ACTIVE = True
    try:
        candidate_rigs = fbp_depsgraph_updated_fbp_rigs(depsgraph, scene)
        has_deleted_rig = fbp_known_links_have_deleted_rig(scene)
        has_orphan_plane = fbp_depsgraph_has_orphan_fbp_plane(depsgraph, scene)
        has_broken_duplicate = fbp_scene_has_broken_native_duplicate(scene, candidates=candidate_rigs)

        now = time.monotonic()
        if not has_deleted_rig and not has_orphan_plane and (now - FBP_LAST_ORPHAN_LIGHT_SCAN) > 0.25:
            FBP_LAST_ORPHAN_LIGHT_SCAN = now
            has_orphan_plane = fbp_scene_has_orphan_fbp_plane_light(scene)

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

def fbp_scene_has_orphan_fbp_plane_light(scene=None):
    """Cheap safety-net check used by the slow cleanup timer.

    The timer should not rebuild the whole Layer UI every few seconds. It first
    checks whether at least one FBP plane actually looks orphaned; only then it
    runs the heavier cleanup/sync path.
    """
    scene = scene or getattr(bpy.context, "scene", None)
    if not scene:
        return False
    try:
        for obj in list(getattr(scene, "objects", [])):
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
    if fbp_undo_is_active():
        return 2.0

    context = bpy.context
    scene = getattr(context, "scene", None) if context else None
    if not context or not scene:
        return 2.0

    changed = 0
    try:
        # Native X/Delete and Shift+D are normally handled instantly by the
        # depsgraph handler. This slow timer is now only a fallback and does no
        # full sync unless it detects a real issue.
        if fbp_known_links_have_deleted_rig(scene) or fbp_scene_has_broken_native_duplicate(scene):
            changed += int(fbp_run_native_ops_sync(context, scene, force=False) or 0)

        if fbp_scene_has_orphan_fbp_plane_light(scene):
            changed += int(cleanup_orphan_fbp_planes(context, force=True) or 0)

        if changed:
            sync_layer_collection(context)
            fbp_snapshot_layer_plane_links(context)
    except Exception as exc:
        fbp_warn("Slow orphan cleanup timer skipped", exc)
    return 2.0
