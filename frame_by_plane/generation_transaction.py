"""Process-wide lifecycle for incremental Frame By Plane generation.

Blender exposes one shared Main database, one Global Undo preference and one
window-manager progress channel per process.  Incremental import therefore uses
one owner token for the complete process.  Every resource that may be removed
on cancellation is explicitly tagged and journalled; unrelated data is never
inferred from a before/after scan of ``bpy.data``.
"""

from __future__ import annotations

import json
import time
import uuid

import bpy

from .runtime import FBP_DATA_ERRORS, FBP_DATA_IO_ERRORS, fbp_error, fbp_warn


GENERATION_JOURNAL_KEY = "fbp_incremental_generation_journal"
GENERATION_OWNER_KEY = "fbp_generation_owner_token"
GENERATION_JOURNAL_SCHEMA = 1


_PREVIOUS_ACTIVE_GENERATION = globals().get("_ACTIVE_GENERATION")


def _retire_previous_generation_early():
    """Fail closed before a reloaded module accepts another generation."""
    previous = _PREVIOUS_ACTIVE_GENERATION
    if previous is None:
        return {"retired": 0, "failures": 0}
    try:
        previous.retire(
            getattr(bpy, "context", None),
            reason="Reload Scripts",
            rollback=True,
        )
        return {"retired": 1, "failures": 0}
    except Exception as exc:
        fbp_error(
            "Could not retire incremental generation during module reload",
            exc,
            event="generation.reload_teardown",
        )
        return {"retired": 0, "failures": 1}


_RELOAD_RETIRE_RESULT = _retire_previous_generation_early()
_ACTIVE_GENERATION = None
_LAST_RETIRE_RESULT = {}
_METRICS = {
    "acquired": 0,
    "refused": 0,
    "committed": 0,
    "rolled_back": 0,
    "rollback_failed": 0,
    "progress_begin": 0,
    "progress_update": 0,
    "progress_end": 0,
    "last_refusal": "",
}
_FAILPOINTS = {}


def _pointer(value):
    try:
        return int(value.as_pointer()) if value is not None else 0
    except FBP_DATA_ERRORS:
        return 0


def _safe_name(value):
    try:
        return str(getattr(value, "name_full", None) or getattr(value, "name", "") or "")
    except FBP_DATA_ERRORS:
        return ""


def _alive(value):
    if value is None:
        return False
    try:
        value.as_pointer()
        return True
    except FBP_DATA_ERRORS:
        return False


def _tag_owner(value, token):
    try:
        value[GENERATION_OWNER_KEY] = str(token)
        return True
    except FBP_DATA_IO_ERRORS:
        return False


def _owner_token(value):
    try:
        return str(value.get(GENERATION_OWNER_KEY, "") or "")
    except FBP_DATA_IO_ERRORS:
        return ""


def _clear_owner_tag(value, token):
    try:
        if str(value.get(GENERATION_OWNER_KEY, "") or "") != str(token):
            return False
        del value[GENERATION_OWNER_KEY]
        return True
    except FBP_DATA_IO_ERRORS:
        return False


def _object_mode(context):
    try:
        return str(getattr(context, "mode", "OBJECT") or "OBJECT")
    except FBP_DATA_ERRORS:
        return "OBJECT"


def _capture_user_state(context):
    scene = getattr(context, "scene", None) if context is not None else None
    view_layer = getattr(context, "view_layer", None) if context is not None else None
    selected = []
    try:
        selected = [_safe_name(obj) for obj in context.selected_objects if _safe_name(obj)]
    except FBP_DATA_ERRORS:
        pass
    active = None
    try:
        active = getattr(getattr(view_layer, "objects", None), "active", None)
    except FBP_DATA_ERRORS:
        active = None
    state = {
        "scene_name": _safe_name(scene),
        "scene_pointer": _pointer(scene),
        "selected_names": tuple(selected),
        "active_name": _safe_name(active),
        "mode": _object_mode(context),
        "camera_name": "",
        "cursor": None,
        "pivot": "",
        "resolution_x": None,
        "resolution_y": None,
        "pixel_aspect_x": None,
        "pixel_aspect_y": None,
        "fbp_last_directory": None,
        "fbp_show_create_tools": None,
        "global_undo": None,
    }
    if scene is not None:
        try:
            state["camera_name"] = _safe_name(scene.camera)
            state["cursor"] = tuple(float(value) for value in scene.cursor.location)
            state["pivot"] = str(scene.tool_settings.transform_pivot_point)
            state["resolution_x"] = int(scene.render.resolution_x)
            state["resolution_y"] = int(scene.render.resolution_y)
            state["pixel_aspect_x"] = float(scene.render.pixel_aspect_x)
            state["pixel_aspect_y"] = float(scene.render.pixel_aspect_y)
            state["fbp_last_directory"] = str(getattr(scene, "fbp_last_directory", "") or "")
            state["fbp_show_create_tools"] = bool(getattr(scene, "fbp_show_create_tools", False))
        except FBP_DATA_ERRORS:
            pass
    try:
        state["global_undo"] = bool(context.preferences.edit.use_global_undo)
    except FBP_DATA_ERRORS:
        pass
    return state


def _restore_user_state(context, state):
    restored = []
    failed = []
    scene = getattr(context, "scene", None) if context is not None else None
    if scene is None:
        return restored, ["scene unavailable"]

    def restore(label, callback):
        try:
            callback()
            restored.append(label)
        except Exception as exc:
            failed.append(f"{label}: {type(exc).__name__}: {exc}")

    camera_name = str(state.get("camera_name", "") or "")
    restore("camera", lambda: setattr(scene, "camera", bpy.data.objects.get(camera_name) if camera_name else None))
    cursor = state.get("cursor")
    if cursor is not None:
        restore("cursor", lambda: setattr(scene.cursor, "location", cursor))
    if state.get("pivot"):
        restore("pivot", lambda: setattr(scene.tool_settings, "transform_pivot_point", state["pivot"]))
    for key in ("resolution_x", "resolution_y", "pixel_aspect_x", "pixel_aspect_y"):
        if state.get(key) is not None:
            restore(key, lambda key=key: setattr(scene.render, key, state[key]))
    for key in ("fbp_last_directory", "fbp_show_create_tools"):
        if state.get(key) is not None and hasattr(scene, key):
            restore(key, lambda key=key: setattr(scene, key, state[key]))
    if state.get("global_undo") is not None:
        restore(
            "global_undo",
            lambda: setattr(context.preferences.edit, "use_global_undo", bool(state["global_undo"])),
        )

    def restore_selection():
        if getattr(context, "mode", "OBJECT") != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except FBP_DATA_ERRORS:
                pass
        for obj in tuple(getattr(context, "selected_objects", ()) or ()):
            obj.select_set(False)
        active = bpy.data.objects.get(str(state.get("active_name", "") or ""))
        for name in tuple(state.get("selected_names", ()) or ()):
            obj = bpy.data.objects.get(name)
            if obj is not None and obj.name in scene.objects:
                obj.select_set(True)
        if active is not None and active.name in scene.objects:
            context.view_layer.objects.active = active
        mode = str(state.get("mode", "OBJECT") or "OBJECT")
        if mode != 'OBJECT' and active is not None:
            bpy.ops.object.mode_set(mode=mode)

    restore("selection_active_mode", restore_selection)
    return restored, failed


class GenerationProgressOwner:
    """Idempotent wrapper around Blender's process-global progress API."""

    def __init__(self, window_manager, *, token):
        self.window_manager = window_manager
        self.token = str(token or "")
        self.started = False
        self.ended = False
        self.value = 0.0
        self.phase = "WAITING"
        self.begin_calls = 0
        self.update_calls = 0
        self.end_calls = 0

    def begin(self):
        if self.started or self.ended or self.window_manager is None:
            return False
        self.window_manager.progress_begin(0.0, 100.0)
        self.started = True
        self.begin_calls += 1
        _METRICS["progress_begin"] += 1
        return True

    def update(self, fraction, *, phase=""):
        if self.ended or self.window_manager is None:
            return False
        if not self.started:
            self.begin()
        try:
            value = max(self.value, min(100.0, max(0.0, float(fraction)) * 100.0))
        except (TypeError, ValueError, OverflowError):
            value = self.value
        self.value = value
        self.phase = str(phase or self.phase or "WORK")[:128]
        self.window_manager.progress_update(value)
        self.update_calls += 1
        _METRICS["progress_update"] += 1
        return True

    def end(self):
        if self.ended or self.window_manager is None:
            return False
        if self.started:
            self.window_manager.progress_end()
            self.end_calls += 1
            _METRICS["progress_end"] += 1
        self.ended = True
        return True

    def snapshot(self):
        return {
            "token": self.token,
            "started": bool(self.started),
            "ended": bool(self.ended),
            "value": float(self.value),
            "phase": self.phase,
            "begin_calls": int(self.begin_calls),
            "update_calls": int(self.update_calls),
            "end_calls": int(self.end_calls),
        }


class IncrementalGenerationOwner:
    """One process-wide generation owner with an explicit rollback journal."""

    def __init__(self, context, *, operator_id, mode):
        self.token = uuid.uuid4().hex
        self.operator_id = str(operator_id or "unknown")
        self.mode = str(mode or "Frame By Plane generation")
        self.scene_pointer = _pointer(getattr(context, "scene", None))
        self.scene_name = _safe_name(getattr(context, "scene", None))
        self.window_pointer = _pointer(getattr(context, "window", None))
        self.started_monotonic = time.monotonic()
        self.started_wall = time.time()
        self.phase = "ACQUIRED"
        self.cancel_state = "NONE"
        self.state = "ACTIVE"
        self.completed_steps = 0
        self.total_steps = 0
        self.percent = 0.0
        self.current_step = "Waiting"
        self.journal = []
        self.disk_changes = []
        self._journal_keys = set()
        self._user_state = _capture_user_state(context)
        self._retire_callback = None
        self._last_result = None
        self.progress = GenerationProgressOwner(
            getattr(context, "window_manager", None),
            token=self.token,
        )
        self.progress.begin()
        self._persist(context)

    def _payload(self):
        return {
            "schema": GENERATION_JOURNAL_SCHEMA,
            "token": self.token,
            "operator_id": self.operator_id,
            "mode": self.mode,
            "scene_pointer": self.scene_pointer,
            "scene_name": self.scene_name,
            "window_pointer": self.window_pointer,
            "started_at": round(self.started_wall, 6),
            "phase": self.phase,
            "cancel_state": self.cancel_state,
            "state": self.state,
            "completed_steps": self.completed_steps,
            "total_steps": self.total_steps,
            "percent": round(self.percent, 6),
            "journal": tuple(
                {"kind": entry["kind"], "name": entry["name"]}
                for entry in self.journal
            ),
            "disk_changes": tuple(dict(change) for change in self.disk_changes),
        }

    def _persist(self, context=None):
        scene = getattr(context, "scene", None) if context is not None else None
        if scene is None or _pointer(scene) != self.scene_pointer:
            scene = bpy.data.scenes.get(self.scene_name)
        if scene is None:
            return False
        try:
            scene[GENERATION_JOURNAL_KEY] = json.dumps(
                self._payload(),
                sort_keys=True,
                separators=(",", ":"),
            )
            return True
        except FBP_DATA_IO_ERRORS:
            return False

    def _clear_persisted(self, context=None):
        scene = getattr(context, "scene", None) if context is not None else None
        candidates = [scene, bpy.data.scenes.get(self.scene_name)]
        cleared = False
        for candidate in candidates:
            if candidate is None:
                continue
            try:
                if GENERATION_JOURNAL_KEY in candidate:
                    del candidate[GENERATION_JOURNAL_KEY]
                    cleared = True
            except FBP_DATA_IO_ERRORS:
                continue
        return cleared

    def set_retire_callback(self, callback):
        self._retire_callback = callback if callable(callback) else None

    def checkpoint(self, phase, *, completed_steps=None, total_steps=None, percent=None, current_step=""):
        if self.state != "ACTIVE":
            return False
        self.phase = str(phase or "WORK")[:128]
        if completed_steps is not None:
            self.completed_steps = max(self.completed_steps, max(0, int(completed_steps)))
        if total_steps is not None:
            self.total_steps = max(0, int(total_steps))
        if percent is not None:
            self.percent = max(self.percent, min(1.0, max(0.0, float(percent))))
        elif self.total_steps > 0:
            self.percent = max(self.percent, min(1.0, self.completed_steps / self.total_steps))
        if current_step:
            self.current_step = str(current_step)[:256]
        self.progress.update(self.percent, phase=self.phase)
        self._persist()
        if _consume_failpoint(self.phase):
            raise RuntimeError(f"Injected incremental generation failpoint: {self.phase}")
        return True

    def record_datablock(self, datablock, *, kind="DATABLOCK"):
        if self.state != "ACTIVE" or datablock is None:
            return False
        key = (str(kind or "DATABLOCK").upper(), _pointer(datablock))
        if key[1] <= 0 or key in self._journal_keys:
            return False
        if not _tag_owner(datablock, self.token):
            return False
        self._journal_keys.add(key)
        self.journal.append({
            "kind": key[0],
            "name": _safe_name(datablock),
            "pointer": key[1],
            "ref": datablock,
        })
        self._persist()
        return True

    def record_collection(self, collection):
        return self.record_datablock(collection, kind="COLLECTION")

    def record_camera(self, camera_object):
        changed = self.record_datablock(camera_object, kind="OBJECT")
        data = getattr(camera_object, "data", None) if camera_object is not None else None
        return self.record_datablock(data, kind="CAMERA") or changed

    def record_rig(self, rig):
        if rig is None:
            return False
        changed = False
        plane = getattr(rig, "fbp_plane_target", None)
        for obj in (rig, plane):
            if obj is None:
                continue
            changed = self.record_datablock(obj, kind="OBJECT") or changed
            data = getattr(obj, "data", None)
            if data is not None:
                changed = self.record_datablock(data, kind="MESH") or changed
                try:
                    materials = tuple(getattr(data, "materials", ()) or ())
                except FBP_DATA_ERRORS:
                    materials = ()
                for material in materials:
                    changed = self.record_datablock(material, kind="MATERIAL") or changed
                    try:
                        nodes = tuple(getattr(getattr(material, "node_tree", None), "nodes", ()) or ())
                    except FBP_DATA_ERRORS:
                        nodes = ()
                    for node in nodes:
                        image = getattr(node, "image", None)
                        if image is not None:
                            changed = self.record_datablock(image, kind="IMAGE") or changed
        return changed

    def record_disk_change(self, path, *, action="CREATE"):
        path = str(path or "")
        if not path:
            return False
        self.disk_changes.append({"path": path, "action": str(action or "CREATE").upper()})
        self._persist()
        return True

    def _remove_entry(self, entry):
        datablock = entry.get("ref")
        if not _alive(datablock):
            return True, "already absent"
        if _owner_token(datablock) != self.token:
            return False, "owner token changed"
        kind = str(entry.get("kind", "") or "").upper()
        try:
            if kind == "OBJECT":
                bpy.data.objects.remove(datablock, do_unlink=True)
            elif kind == "COLLECTION":
                if datablock.objects or datablock.children:
                    return False, "collection is not empty"
                bpy.data.collections.remove(datablock)
            elif kind == "MESH":
                if datablock.users:
                    return False, f"mesh has {datablock.users} user(s)"
                bpy.data.meshes.remove(datablock)
            elif kind == "CAMERA":
                if datablock.users:
                    return False, f"camera has {datablock.users} user(s)"
                bpy.data.cameras.remove(datablock)
            elif kind == "MATERIAL":
                if datablock.users:
                    return False, f"material has {datablock.users} user(s)"
                bpy.data.materials.remove(datablock)
            elif kind == "IMAGE":
                if datablock.users:
                    return False, f"image has {datablock.users} user(s)"
                bpy.data.images.remove(datablock)
            elif kind == "NODE_GROUP":
                if datablock.users:
                    return False, f"node group has {datablock.users} user(s)"
                bpy.data.node_groups.remove(datablock)
            else:
                return False, f"unsupported journal kind {kind or 'UNKNOWN'}"
            return True, "removed"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    def _clear_committed_tags(self):
        for entry in tuple(self.journal):
            datablock = entry.get("ref")
            if _alive(datablock):
                _clear_owner_tag(datablock, self.token)

    def commit(self, context=None):
        global _ACTIVE_GENERATION
        if self.state == "COMMITTED":
            return True
        if self.state != "ACTIVE":
            return False
        self.phase = "COMMIT"
        self.completed_steps = max(self.completed_steps, self.total_steps)
        self.percent = 1.0
        self.progress.update(1.0, phase="COMMIT")
        self._clear_committed_tags()
        self.state = "COMMITTED"
        self._clear_persisted(context)
        self.progress.end()
        if _ACTIVE_GENERATION is self:
            _ACTIVE_GENERATION = None
        _METRICS["committed"] += 1
        self._last_result = True
        return True

    def rollback(self, context=None, *, reason="cancelled"):
        global _ACTIVE_GENERATION, _LAST_RETIRE_RESULT
        if isinstance(self._last_result, dict):
            return dict(self._last_result)
        self.cancel_state = str(reason or "cancelled")[:256]
        self.phase = "ROLLBACK"
        self.state = "ROLLING_BACK"
        self._persist(context)
        removed = []
        restored = []
        failed = []
        remaining = []

        order = ("OBJECT", "MESH", "CAMERA", "MATERIAL", "IMAGE", "NODE_GROUP", "COLLECTION")
        for kind in order:
            entries = [entry for entry in reversed(self.journal) if entry["kind"] == kind]
            pending = list(entries)
            while pending:
                progress = False
                next_pending = []
                for entry in pending:
                    ok, detail = self._remove_entry(entry)
                    label = f"{entry['kind']}:{entry['name']}"
                    if ok:
                        removed.append(label)
                        progress = True
                    else:
                        next_pending.append((entry, detail))
                if not next_pending or not progress:
                    for entry, detail in next_pending:
                        failed.append(f"{entry['kind']}:{entry['name']}: {detail}")
                    break
                pending = [entry for entry, _detail in next_pending]

        restored_state, restore_failures = _restore_user_state(context, self._user_state)
        restored.extend(restored_state)
        failed.extend(restore_failures)
        for entry in self.journal:
            datablock = entry.get("ref")
            if _alive(datablock) and _owner_token(datablock) == self.token:
                remaining.append(f"{entry['kind']}:{entry['name']}")
        verified = not failed and not remaining
        self.state = "ROLLED_BACK" if verified else "ROLLBACK_FAILED"
        if verified:
            self._clear_persisted(context)
            _METRICS["rolled_back"] += 1
        else:
            self._persist(context)
            _METRICS["rollback_failed"] += 1
        self.progress.end()
        if _ACTIVE_GENERATION is self:
            _ACTIVE_GENERATION = None
        result = {
            "token": self.token,
            "reason": self.cancel_state,
            "removed": tuple(removed),
            "restored": tuple(restored),
            "failed": tuple(failed),
            "remaining": tuple(remaining),
            "disk_changes": tuple(dict(change) for change in self.disk_changes),
            "verified": bool(verified),
        }
        self._last_result = dict(result)
        _LAST_RETIRE_RESULT = dict(result)
        return result

    def retire(self, context=None, *, reason="add-on teardown", rollback=True):
        if callable(self._retire_callback):
            try:
                self._retire_callback(str(reason or "add-on teardown"))
            except Exception as exc:
                fbp_warn(
                    "Could not close incremental generation runtime before retirement",
                    exc,
                    event="generation.retire_callback",
                )
            finally:
                self._retire_callback = None
        if rollback:
            return self.rollback(context, reason=reason)
        return self.commit(context)

    def snapshot(self):
        payload = self._payload()
        payload["progress"] = self.progress.snapshot()
        payload["age_seconds"] = max(0.0, time.monotonic() - self.started_monotonic)
        return payload


def acquire_generation(context, *, operator_id, mode):
    """Atomically claim the single process-wide generation slot."""
    global _ACTIVE_GENERATION
    active = _ACTIVE_GENERATION
    if active is not None and getattr(active, "state", "ACTIVE") == "ACTIVE":
        _METRICS["refused"] += 1
        reason = (
            f"{active.mode} is already active in this Blender process "
            f"(operator {active.operator_id}, phase {active.phase})."
        )
        _METRICS["last_refusal"] = reason
        return None, reason
    if active is not None:
        try:
            active.retire(context, reason="stale generation owner", rollback=True)
        except Exception as exc:
            reason = f"A stale Frame By Plane generation owner could not be retired: {exc}"
            _METRICS["refused"] += 1
            _METRICS["last_refusal"] = reason
            return None, reason
    owner = IncrementalGenerationOwner(context, operator_id=operator_id, mode=mode)
    _ACTIVE_GENERATION = owner
    _METRICS["acquired"] += 1
    return owner, ""


def active_generation_owner():
    active = _ACTIVE_GENERATION
    return active if active is not None and getattr(active, "state", "") == "ACTIVE" else None


def active_generation_snapshot():
    active = active_generation_owner()
    return active.snapshot() if active is not None else {}


def commit_active_generation(context=None, *, token=""):
    active = active_generation_owner()
    if active is None or (token and active.token != str(token)):
        return False
    return active.commit(context)


def retire_active_generation(context=None, *, reason="add-on teardown", rollback=True, token=""):
    active = _ACTIVE_GENERATION
    if active is None:
        return dict(_LAST_RETIRE_RESULT) if _LAST_RETIRE_RESULT else {
            "removed": (), "restored": (), "failed": (), "remaining": (),
            "disk_changes": (), "verified": True,
        }
    if token and active.token != str(token):
        return {
            "removed": (), "restored": (),
            "failed": ("owner token mismatch",),
            "remaining": (active.token,), "disk_changes": (), "verified": False,
        }
    return active.retire(context, reason=reason, rollback=rollback)


def persisted_generation_journal(scene):
    try:
        raw = str(scene.get(GENERATION_JOURNAL_KEY, "") or "") if scene is not None else ""
        return json.loads(raw) if raw else {}
    except FBP_DATA_IO_ERRORS + (json.JSONDecodeError,):
        return {}


def generation_journal_is_orphaned(scene):
    journal = persisted_generation_journal(scene)
    if not journal:
        return False
    active = active_generation_owner()
    return active is None or str(journal.get("token", "") or "") != active.token


def generation_metrics(*, reset=False):
    snapshot = dict(_METRICS)
    snapshot["active"] = bool(active_generation_owner())
    snapshot["owner"] = active_generation_snapshot()
    snapshot["reload_retire"] = dict(_RELOAD_RETIRE_RESULT)
    if reset:
        for key, value in tuple(_METRICS.items()):
            _METRICS[key] = "" if isinstance(value, str) else 0
    return snapshot


def arm_generation_failpoint(phase, *, count=1):
    key = str(phase or "*").upper()
    _FAILPOINTS[key] = max(1, int(count or 1))
    return key


def clear_generation_failpoints():
    count = len(_FAILPOINTS)
    _FAILPOINTS.clear()
    return count


def _consume_failpoint(phase):
    for key in (str(phase or "").upper(), "*"):
        remaining = int(_FAILPOINTS.get(key, 0) or 0)
        if remaining <= 0:
            continue
        if remaining == 1:
            _FAILPOINTS.pop(key, None)
        else:
            _FAILPOINTS[key] = remaining - 1
        return True
    return False


def register():
    try:
        from .service_registry import register_service
        register_service("generation.active", active_generation_snapshot, owner=__name__)
        register_service("generation.metrics", generation_metrics, owner=__name__)
        register_service("generation.retire", retire_active_generation, owner=__name__)
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        pass


def unregister():
    clear_generation_failpoints()
    retire_active_generation(
        getattr(bpy, "context", None),
        reason="add-on unregister",
        rollback=True,
    )
    try:
        from .service_registry import unregister_service
        unregister_service("generation.active")
        unregister_service("generation.metrics")
        unregister_service("generation.retire")
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        pass


__all__ = [
    "GENERATION_JOURNAL_KEY",
    "GENERATION_OWNER_KEY",
    "GenerationProgressOwner",
    "IncrementalGenerationOwner",
    "acquire_generation",
    "active_generation_owner",
    "active_generation_snapshot",
    "commit_active_generation",
    "retire_active_generation",
    "persisted_generation_journal",
    "generation_journal_is_orphaned",
    "generation_metrics",
    "arm_generation_failpoint",
    "clear_generation_failpoints",
]
