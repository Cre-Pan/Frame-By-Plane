"""Runtime-only state and diagnostics shared across Frame by Plane modules.

This module intentionally does not import other add-on modules. Keeping it at the
bottom of the dependency graph prevents circular imports during registration.
"""

from collections import deque
import json
import random
import time
import traceback

FBP_DATA_ERRORS = (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError)
FBP_DATA_IO_ERRORS = FBP_DATA_ERRORS + (KeyError, IndexError, OSError)

_FBP_REGISTRATION_STATES = frozenset({
    "INACTIVE",
    "REGISTERING",
    "ACTIVE",
    "TEARDOWN",
    "FAILED",
    "FAILED_UNSAFE",
})


def fbp_set_registration_state(value):
    """Store the volatile add-on lifecycle state outside saved Blender data."""
    state = str(value or "INACTIVE").strip().upper()
    if state not in _FBP_REGISTRATION_STATES:
        state = "FAILED_UNSAFE"
    try:
        import bpy
        namespace = getattr(getattr(bpy, "app", None), "driver_namespace", None)
        if namespace is None:
            return False
        namespace["frame_by_plane.registration_state"] = state
        return True
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def fbp_registration_state():
    """Return the current volatile add-on lifecycle state."""
    try:
        import bpy
        namespace = getattr(getattr(bpy, "app", None), "driver_namespace", None)
        state = str(
            namespace.get("frame_by_plane.registration_state", "INACTIVE")
            if namespace is not None
            else "INACTIVE"
        ).strip().upper()
        return state if state in _FBP_REGISTRATION_STATES else "FAILED_UNSAFE"
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return "FAILED_UNSAFE"


def fbp_set_registration_busy(value):
    """Expose extension RNA teardown/rebuild state without retaining RNA wrappers."""
    try:
        import bpy
        namespace = getattr(getattr(bpy, "app", None), "driver_namespace", None)
        if namespace is None:
            return False
        namespace["frame_by_plane.registration_busy"] = bool(value)
        return True
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def fbp_registration_busy():
    """Return True while Frame By Plane is changing registered RNA state."""
    try:
        import bpy
        namespace = getattr(getattr(bpy, "app", None), "driver_namespace", None)
        return bool(namespace and namespace.get("frame_by_plane.registration_busy", False))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return True


# Selection is queried by multiple high-frequency depsgraph observers. Keep one
# short-lived primitive snapshot so Motion and Viewport Controls do not each
# traverse ``context.selected_objects`` during the same interaction burst.
# No Blender RNA object is retained in this cache.
_FBP_SELECTION_SNAPSHOT = {
    "time": 0.0,
    "context_key": (),
    "value": (0, 0, frozenset()),
}
_FBP_SELECTION_SNAPSHOT_MAX_AGE = 0.05

# Grease Pencil brush/edit modes emit dense depsgraph traffic. Observer-only
# systems such as Motion-helper visibility and effect-control selection do not
# need to rescan selection while the artist remains inside one of these modes.
_FBP_GREASE_PENCIL_INTERACTION_MODES = frozenset({
    "PAINT_GREASE_PENCIL",
    "EDIT_GREASE_PENCIL",
    "SCULPT_GREASE_PENCIL",
    "WEIGHT_GREASE_PENCIL",
    "VERTEX_GREASE_PENCIL",
})


def fbp_is_grease_pencil_interaction_mode(value=None):
    """Return whether *value* or its ``mode`` is an interactive GP mode.

    Accepting either a mode string or a context-like object keeps the hot-path
    check Blender-light and makes the contract directly testable.
    """
    try:
        mode = value if isinstance(value, str) else getattr(value, "mode", "")
        return str(mode or "").strip().upper() in _FBP_GREASE_PENCIL_INTERACTION_MODES
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def fbp_selection_snapshot(context=None, *, max_age=_FBP_SELECTION_SNAPSHOT_MAX_AGE):
    """Return ``(scene_key, active_key, selected_keys)`` without RNA retention.

    Blender has no dedicated selection-change handler usable by both systems,
    so Motion helpers and effect controls observe selection from depsgraph
    traffic. A 50 ms shared snapshot matches the fastest existing observer
    cadence and removes the duplicate selected-object traversal when both are
    active. Explicit callers can pass ``max_age=0`` to force a fresh sample.
    """
    try:
        import bpy
        context = context or getattr(bpy, "context", None)
    except (ImportError, AttributeError, ReferenceError, RuntimeError):
        context = None
    if context is None:
        return (0, 0, frozenset())

    try:
        scene = getattr(context, "scene", None)
        view_layer = getattr(context, "view_layer", None)
        window = getattr(context, "window", None)
        context_key = (
            int(fbp_obj_runtime_key(scene) or 0),
            int(fbp_obj_runtime_key(view_layer) or 0),
            int(fbp_obj_runtime_key(window) or 0),
        )
    except FBP_DATA_ERRORS:
        context_key = (0, 0, 0)

    try:
        now = time.monotonic()
        age_limit = max(0.0, float(max_age))
    except (RuntimeError, TypeError, ValueError):
        now = 0.0
        age_limit = 0.0
    cached_time = float(_FBP_SELECTION_SNAPSHOT.get("time", 0.0) or 0.0)
    if (
        age_limit > 0.0
        and context_key == _FBP_SELECTION_SNAPSHOT.get("context_key")
        and now - cached_time <= age_limit
    ):
        return _FBP_SELECTION_SNAPSHOT.get("value", (0, 0, frozenset()))

    try:
        selected_keys = frozenset(
            int(key)
            for obj in (getattr(context, "selected_objects", ()) or ())
            for key in (fbp_obj_runtime_key(obj),)
            if key is not None
        )
    except FBP_DATA_ERRORS:
        selected_keys = frozenset()
    try:
        active = getattr(context, "active_object", None) or getattr(context, "object", None)
        active_key = (
            int(fbp_obj_runtime_key(active) or 0)
            if active is not None and bool(active.select_get())
            else 0
        )
    except FBP_DATA_ERRORS:
        active_key = 0
    value = (int(context_key[0]), active_key, selected_keys)
    _FBP_SELECTION_SNAPSHOT["time"] = now
    _FBP_SELECTION_SNAPSHOT["context_key"] = context_key
    _FBP_SELECTION_SNAPSHOT["value"] = value
    return value


def fbp_invalidate_selection_snapshot():
    """Clear the primitive selection cache after reload or explicit mutation."""
    _FBP_SELECTION_SNAPSHOT["time"] = 0.0
    _FBP_SELECTION_SNAPSHOT["context_key"] = ()
    _FBP_SELECTION_SNAPSHOT["value"] = (0, 0, frozenset())


def fbp_object_name(obj) -> str:
    """Return a stable Blender ID name without leaking stale-RNA errors."""
    try:
        return str(getattr(obj, "name", "") or "")
    except FBP_DATA_ERRORS:
        return ""


_DATA_UNAVAILABLE = object()


def fbp_main_data_collection(name, default=None):
    """Return one Blender Main collection without raising during restricted startup.

    Blender temporarily replaces ``bpy.data`` with an internal ``_RestrictData``
    proxy while extensions are imported/registered and while Main is replaced.
    Accessing attributes such as ``scenes`` on that proxy raises AttributeError.
    Centralizing the check prevents every timer and startup callback from needing
    its own fragile try/except block.
    """
    try:
        import bpy
        data = getattr(bpy, "data", None)
        if data is None:
            return default
        value = getattr(data, str(name), _DATA_UNAVAILABLE)
        return default if value is _DATA_UNAVAILABLE else value
    except FBP_DATA_ERRORS:
        return default


def fbp_main_data_ready(*collection_names):
    """Return True only when Blender exposes the requested Main collections."""
    names = collection_names or ("scenes",)
    for name in names:
        if fbp_main_data_collection(name, _DATA_UNAVAILABLE) is _DATA_UNAVAILABLE:
            return False
    return True


def fbp_creation_start_frame(scene, context=None):
    """Resolve the start frame for newly generated planes.

    The preference is intentionally read only at creation time. Existing rigs
    keep their authored start frame, while changing the preference immediately
    affects the next image, video, procedural or Cutout Plane.
    """
    if scene is None:
        return 1
    try:
        current = int(getattr(scene, "frame_current", 1))
    except FBP_DATA_ERRORS:
        current = 1
    try:
        context = context or getattr(__import__("bpy"), "context", None)
        preferences = getattr(context, "preferences", None) if context else None
        addons = getattr(preferences, "addons", None) if preferences else None
        prefs = None
        if addons is not None:
            for key in (__package__.split(".")[0] if __package__ else "frame_by_plane", "frame_by_plane"):
                addon = addons.get(key)
                prefs = getattr(addon, "preferences", None) if addon else None
                if prefs is not None:
                    break
            if prefs is None:
                for key, addon in addons.items():
                    if str(key).endswith(".frame_by_plane") or str(key) == "frame_by_plane":
                        prefs = getattr(addon, "preferences", None)
                        if prefs is not None:
                            break
        mode = str(getattr(prefs, "default_plane_start_frame_mode", "PLAYHEAD") or "PLAYHEAD").upper()
        if mode == "TIMELINE_START":
            return int(getattr(scene, "frame_start", current))
    except FBP_DATA_ERRORS:
        pass
    return current


_FBP_LAST_DEPSGRAPH_ACTIVITY = float(
    globals().get("_FBP_LAST_DEPSGRAPH_ACTIVITY", 0.0) or 0.0
)


def fbp_note_depsgraph_activity():
    """Record one evaluation tick without retaining RNA references."""
    global _FBP_LAST_DEPSGRAPH_ACTIVITY
    _FBP_LAST_DEPSGRAPH_ACTIVITY = time.monotonic()
    return _FBP_LAST_DEPSGRAPH_ACTIVITY


def fbp_depsgraph_quiet_for(seconds=0.25):
    """Return whether Blender evaluation has been quiet for *seconds*.

    Generated-image publication uses this as a conservative viewport barrier.
    It does not block native drivers or constraints; only deferred Python image
    and material maintenance waits for a short idle window.
    """
    try:
        required = max(0.0, float(seconds))
    except (TypeError, ValueError):
        required = 0.25
    last = float(_FBP_LAST_DEPSGRAPH_ACTIVITY or 0.0)
    return last <= 0.0 or (time.monotonic() - last) >= required


# One process-local generator is seeded once by Python and then reused for
# persistent internal identifiers. These tokens are not security credentials;
# avoiding one operating-system entropy read per effect materially reduces the
# cost of generating large Multiplane/effects projects while retaining a
# 128-bit collision space.
_FBP_TOKEN_RANDOM = random.Random()


def fbp_unique_token_hex():
    """Return a compact 128-bit token for persistent internal identities."""
    return f"{_FBP_TOKEN_RANDOM.getrandbits(128):032x}"


# Structured runtime diagnostics. Records retain primitives only: never RNA,
# callbacks or exception objects. This makes the ring buffer safe across
# Undo/Redo, file loads and add-on reloads while still preserving enough context
# to diagnose failures that would otherwise disappear in Blender's console.
_FBP_DIAGNOSTIC_LIMIT = 256
_FBP_DIAGNOSTICS = deque(maxlen=_FBP_DIAGNOSTIC_LIMIT)
_FBP_DIAGNOSTIC_SEQUENCE = int(globals().get("_FBP_DIAGNOSTIC_SEQUENCE", 0) or 0)
_FBP_WARNED_KEYS = set()
_FBP_DIAGNOSTIC_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


def _fbp_diagnostic_value(value, *, depth=0):
    """Convert diagnostic context to bounded JSON-safe primitives."""
    if depth > 2:
        return "<max-depth>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:512]
    if isinstance(value, (tuple, list, set, frozenset)):
        return tuple(_fbp_diagnostic_value(item, depth=depth + 1) for item in tuple(value)[:16])
    if isinstance(value, dict):
        result = {}
        for index, (key, item) in enumerate(tuple(value.items())):
            if index >= 16:
                break
            result[str(key)[:96]] = _fbp_diagnostic_value(item, depth=depth + 1)
        return result
    try:
        name = str(getattr(value, "name_full", getattr(value, "name", "")) or "")
        type_name = type(value).__name__
        if name:
            return f"<{type_name} {name[:160]}>"
        return f"<{type_name}>"
    except FBP_DATA_ERRORS:
        return f"<{type(value).__name__}>"


def fbp_log(message, level="INFO", exc=None, *, event="", context=None, capture_traceback=None):
    """Store and print one structured runtime diagnostic.

    ``context`` is sanitized immediately and may safely contain temporary RNA
    values. Tracebacks are opt-in for warnings and automatic for errors when the
    runtime ``fbp_diagnostic_tracebacks`` flag is enabled.
    """
    global _FBP_DIAGNOSTIC_SEQUENCE
    normalized_level = str(level or "INFO").upper()
    if normalized_level == "WARN":
        normalized_level = "WARNING"
    if normalized_level not in _FBP_DIAGNOSTIC_LEVELS:
        normalized_level = "INFO"
    message_text = str(message or "")[:2048]
    event_text = str(event or "")[:160]
    exception_type = type(exc).__name__ if exc is not None else ""
    exception_text = str(exc)[:1024] if exc is not None else ""
    if capture_traceback is None:
        capture_traceback = bool(
            exc is not None
            and _FBP_DIAGNOSTIC_LEVELS[normalized_level] >= _FBP_DIAGNOSTIC_LEVELS["ERROR"]
            and bool(globals().get("_FBP_RUNTIME_STATE", {}).get("fbp_diagnostic_tracebacks", False))
        )
    trace_text = ""
    if capture_traceback and exc is not None:
        try:
            trace_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__, limit=12))[-8192:]
        except (AttributeError, TypeError, ValueError):
            trace_text = ""
    _FBP_DIAGNOSTIC_SEQUENCE += 1
    record = {
        "sequence": _FBP_DIAGNOSTIC_SEQUENCE,
        "time": round(time.time(), 6),
        "level": normalized_level,
        "event": event_text,
        "message": message_text,
        "exception_type": exception_type,
        "exception": exception_text,
        "context": _fbp_diagnostic_value(context or {}),
        "traceback": trace_text,
    }
    try:
        _FBP_DIAGNOSTICS.append(record)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    try:
        label = f"[{event_text}] " if event_text else ""
        suffix = f": {exception_type}: {exception_text}" if exc is not None else ""
        print(f"[FBP {normalized_level}] {label}{message_text}{suffix}", flush=normalized_level in {"ERROR", "CRITICAL"})
    except FBP_DATA_IO_ERRORS:
        pass
    return dict(record)


def fbp_warn(message, exc=None, *, event="", context=None):
    return fbp_log(message, "WARNING", exc, event=event, context=context)


def fbp_error(message, exc=None, *, event="", context=None, capture_traceback=None):
    return fbp_log(
        message,
        "ERROR",
        exc,
        event=event,
        context=context,
        capture_traceback=capture_traceback,
    )


def fbp_warn_once(key, message, exc=None, *, event="", context=None):
    """Log a warning once per add-on module lifetime."""
    token = str(key or message)
    if token in _FBP_WARNED_KEYS:
        return False
    _FBP_WARNED_KEYS.add(token)
    fbp_warn(message, exc, event=event or token, context=context)
    return True


def fbp_recent_diagnostics(limit=50, *, minimum_level="DEBUG"):
    """Return detached diagnostic records, newest last."""
    try:
        count = max(0, min(int(limit), _FBP_DIAGNOSTIC_LIMIT))
    except (TypeError, ValueError):
        count = 50
    threshold = _FBP_DIAGNOSTIC_LEVELS.get(str(minimum_level or "DEBUG").upper(), 10)
    records = [
        dict(record)
        for record in tuple(_FBP_DIAGNOSTICS)
        if _FBP_DIAGNOSTIC_LEVELS.get(str(record.get("level", "INFO")), 20) >= threshold
    ]
    return tuple(records[-count:] if count else ())


def fbp_diagnostics_summary():
    """Return exact counts for Project Health reports."""
    counts = {level.lower(): 0 for level in _FBP_DIAGNOSTIC_LEVELS}
    for record in tuple(_FBP_DIAGNOSTICS):
        level = str(record.get("level", "INFO") or "INFO").lower()
        counts[level] = int(counts.get(level, 0)) + 1
    counts["total"] = len(_FBP_DIAGNOSTICS)
    counts["capacity"] = _FBP_DIAGNOSTIC_LIMIT
    counts["dropped"] = max(0, _FBP_DIAGNOSTIC_SEQUENCE - len(_FBP_DIAGNOSTICS))
    return counts


def fbp_clear_diagnostics():
    """Clear runtime diagnostics without touching other transient state."""
    global _FBP_DIAGNOSTIC_SEQUENCE
    _FBP_DIAGNOSTICS.clear()
    _FBP_WARNED_KEYS.clear()
    _FBP_DIAGNOSTIC_SEQUENCE = 0


# Coalesced editor redraw requests. Property updates can fire several callbacks
# in one UI event; scheduling one zero-delay flush prevents every callback from
# walking every open Window/Screen independently. Only primitive strings are
# retained, never Blender RNA objects.
_FBP_REDRAW_AREA_TYPES = set()
_FBP_REDRAW_REGION_TYPES = set()
_FBP_REDRAW_ALL_AREAS = False
_FBP_REDRAW_ALL_REGIONS = False
_FBP_REDRAW_ALL_WINDOWS = False
_REDRAW_TASK_KEY = "runtime.redraw.flush"
_PREVIOUS_REDRAW_TIMER = globals().get("_fbp_flush_redraw_requests")
# Runtime UI callbacks are disabled during import and explicit teardown. They
# become live only from register(), after the former timer generation is gone.
_RUNTIME_CALLBACKS_ENABLED = False


def _retire_reloaded_redraw_timer_early(callback):
    """Remove a former direct redraw callback during module import.

    This closes the reload window before RNA properties/classes are registered
    again. The callback retains no RNA itself, but it traverses current Screens
    and must not execute while Blender is tearing editor data down.
    """
    if callback is None:
        return False
    try:
        import bpy
        if bpy.app.timers.is_registered(callback):
            bpy.app.timers.unregister(callback)
            return True
    except FBP_DATA_ERRORS:
        pass
    return False


_retire_reloaded_redraw_timer_early(_PREVIOUS_REDRAW_TIMER)




def fbp_runtime_callbacks_enabled():
    """Return whether deferred UI/runtime callbacks may be created."""
    return bool(_RUNTIME_CALLBACKS_ENABLED)


def fbp_begin_addon_startup():
    """Open the runtime callback gate for the current registration generation."""
    global _RUNTIME_CALLBACKS_ENABLED
    _RUNTIME_CALLBACKS_ENABLED = True
    return True


def fbp_quiesce_runtime_callbacks():
    """Retire direct callbacks before Blender starts deleting RNA definitions."""
    global _RUNTIME_CALLBACKS_ENABLED
    global _FBP_REDRAW_ALL_AREAS, _FBP_REDRAW_ALL_REGIONS, _FBP_REDRAW_ALL_WINDOWS
    _RUNTIME_CALLBACKS_ENABLED = False
    _fbp_cancel_redraw_flush_task()
    _unregister_redraw_timer(_fbp_flush_redraw_requests)
    _FBP_REDRAW_AREA_TYPES.clear()
    _FBP_REDRAW_REGION_TYPES.clear()
    _FBP_REDRAW_ALL_AREAS = False
    _FBP_REDRAW_ALL_REGIONS = False
    _FBP_REDRAW_ALL_WINDOWS = False
    return True


def _fbp_iter_screens(context=None, *, all_windows=False):
    """Yield unique open Screens without retaining Blender RNA references."""
    try:
        import bpy
        context = context or getattr(bpy, "context", None)
    except (ImportError, AttributeError, ReferenceError, RuntimeError):
        return
    seen = set()
    if not all_windows:
        try:
            screen = getattr(context, "screen", None)
            if screen is None:
                window = getattr(context, "window", None)
                screen = getattr(window, "screen", None) if window is not None else None
            if screen is not None:
                key = fbp_obj_runtime_key(screen)
                if key is not None:
                    seen.add(key)
                yield screen
                return
        except FBP_DATA_ERRORS:
            pass
    try:
        wm = getattr(context, "window_manager", None) or getattr(bpy.context, "window_manager", None)
        for window in tuple(getattr(wm, "windows", ()) or ()):
            screen = getattr(window, "screen", None)
            if screen is None:
                continue
            key = fbp_obj_runtime_key(screen)
            if key is not None and key in seen:
                continue
            if key is not None:
                seen.add(key)
            yield screen
    except FBP_DATA_ERRORS:
        return


def fbp_tag_redraw(
    context=None, *, area_types=(), region_types=(), all_windows=False
):
    """Redraw matching editors only while Blender is safely idle.

    Final render completion can report the render job as finished before the
    worker thread and its notifier payloads are fully drained. Never touch
    editor regions while a Blender render or the FBP render guard is active.
    """
    if fbp_render_mutation_blocked():
        return 0
    area_filter = {str(value) for value in tuple(area_types or ()) if str(value or "")}
    region_filter = {str(value) for value in tuple(region_types or ()) if str(value or "")}
    tagged = 0
    for screen in _fbp_iter_screens(context, all_windows=all_windows) or ():
        try:
            areas = tuple(getattr(screen, "areas", ()) or ())
        except FBP_DATA_ERRORS:
            continue
        for area in areas:
            try:
                if area_filter and str(getattr(area, "type", "") or "") not in area_filter:
                    continue
                if not region_filter:
                    area.tag_redraw()
                    tagged += 1
                    continue
                region_tagged = False
                for region in tuple(getattr(area, "regions", ()) or ()):
                    if str(getattr(region, "type", "") or "") in region_filter:
                        region.tag_redraw()
                        tagged += 1
                        region_tagged = True
                if not region_tagged:
                    area.tag_redraw()
                    tagged += 1
            except FBP_DATA_ERRORS:
                continue
    return tagged


def _fbp_flush_redraw_requests():
    global _FBP_REDRAW_ALL_AREAS, _FBP_REDRAW_ALL_REGIONS, _FBP_REDRAW_ALL_WINDOWS
    # A redraw queued immediately before Ctrl+Z can otherwise wake Eevee while
    # Blender is replacing Image/Material IDs. Keep the request intact and let
    # Blender call this timer again after the shared history guard releases.
    if fbp_undo_guard_active():
        return 0.10
    if fbp_render_mutation_blocked():
        return 0.25
    try:
        resume_after = float(
            fbp_runtime_get("fbp_managed_timers_resume_after", 0.0) or 0.0
        )
    except (TypeError, ValueError):
        resume_after = 0.0
    now = time.monotonic()
    if resume_after > now:
        return max(0.05, min(0.25, resume_after - now))
    area_types = tuple(_FBP_REDRAW_AREA_TYPES)
    region_types = tuple(_FBP_REDRAW_REGION_TYPES)
    all_areas = bool(_FBP_REDRAW_ALL_AREAS)
    all_regions = bool(_FBP_REDRAW_ALL_REGIONS)
    all_windows = bool(_FBP_REDRAW_ALL_WINDOWS)
    _FBP_REDRAW_AREA_TYPES.clear()
    _FBP_REDRAW_REGION_TYPES.clear()
    _FBP_REDRAW_ALL_AREAS = False
    _FBP_REDRAW_ALL_REGIONS = False
    _FBP_REDRAW_ALL_WINDOWS = False
    try:
        fbp_tag_redraw(
            area_types=() if all_areas else area_types,
            region_types=() if all_regions else region_types,
            all_windows=all_windows,
        )
    except FBP_DATA_ERRORS:
        pass
    return None


def _fbp_schedule_redraw_flush(delay, *, restart=False):
    """Queue one redraw and fall back only when the shared dispatcher rejects it."""
    if not _RUNTIME_CALLBACKS_ENABLED:
        return False
    try:
        from .runtime_scheduler import scheduler_accepting_tasks
        if not scheduler_accepting_tasks():
            return False
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False
    try:
        from .runtime_scheduler import (
            PRIORITY_INTERACTIVE,
            schedule_task,
            task_is_scheduled,
        )
        accepted = schedule_task(
            _REDRAW_TASK_KEY,
            _fbp_flush_redraw_requests,
            delay=max(0.0, float(delay)),
            priority=PRIORITY_INTERACTIVE,
            category="runtime",
            persistent=False,
            restart=bool(restart),
        )
        scheduled = bool(accepted or task_is_scheduled(_REDRAW_TASK_KEY))
        if scheduled:
            # Retire any direct callback left by an interrupted registration;
            # the shared dispatcher is authoritative.
            _unregister_redraw_timer(_fbp_flush_redraw_requests)
            return True
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    # Never create a second timer when the central scheduler is unavailable.
    # Blender will redraw on the next ordinary notifier.
    return False


def _fbp_cancel_redraw_flush_task():
    try:
        from .runtime_scheduler import cancel_task
        cancel_task(_REDRAW_TASK_KEY)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    _unregister_redraw_timer(_fbp_flush_redraw_requests)


def fbp_request_redraw(
    context=None, *, area_types=(), region_types=(), all_windows=False
):
    """Coalesce redraw bursts without waking editors during history restore.

    Blender 5.2 may still be synchronizing Eevee image materials while Undo or
    Redo replaces Main. Requests are retained as primitive strings, but no timer
    is registered until the shared history guard has fully released.
    """
    global _FBP_REDRAW_ALL_AREAS, _FBP_REDRAW_ALL_REGIONS, _FBP_REDRAW_ALL_WINDOWS
    requested_areas = {str(value) for value in tuple(area_types or ()) if str(value or "")}
    requested_regions = {str(value) for value in tuple(region_types or ()) if str(value or "")}
    if requested_areas:
        _FBP_REDRAW_AREA_TYPES.update(requested_areas)
    else:
        _FBP_REDRAW_ALL_AREAS = True
    if requested_regions:
        _FBP_REDRAW_REGION_TYPES.update(requested_regions)
    else:
        _FBP_REDRAW_ALL_REGIONS = True
    _FBP_REDRAW_ALL_WINDOWS = bool(_FBP_REDRAW_ALL_WINDOWS or all_windows)
    # Do not register, unregister or directly tag editors from a property callback
    # that fires while Blender is replacing Main. The pending primitive request is
    # resumed explicitly by the history watchdog.
    if fbp_undo_guard_active():
        return False
    if fbp_render_mutation_blocked():
        return False
    try:
        resume_after = float(fbp_runtime_get("fbp_managed_timers_resume_after", 0.0) or 0.0)
    except (TypeError, ValueError):
        resume_after = 0.0
    if resume_after > time.monotonic():
        return False
    # Keep the request queued. A later safe operation or the persistent
    # watchdog can retry if Blender temporarily rejects timer ownership.
    return _fbp_schedule_redraw_flush(0.02)


def fbp_resume_pending_redraw_requests(*, first_interval=0.25):
    """Resume one queued redraw only after Undo/Redo and Main replacement."""
    if not (
        _FBP_REDRAW_AREA_TYPES
        or _FBP_REDRAW_REGION_TYPES
        or _FBP_REDRAW_ALL_AREAS
        or _FBP_REDRAW_ALL_REGIONS
        or _FBP_REDRAW_ALL_WINDOWS
    ):
        return False
    if fbp_undo_guard_active():
        return False
    if fbp_render_mutation_blocked():
        return False
    return _fbp_schedule_redraw_flush(
        max(0.02, float(first_interval)),
        restart=False,
    )


FBP_RENDER_IDLE = "IDLE"
FBP_RENDER_BUSY = "BUSY"
FBP_RENDER_UNKNOWN = "UNKNOWN"


def fbp_render_state(*, include_guard=True):
    """Return the canonical Blender render state.

    ``include_guard`` also treats the Frame by Plane render-session guard as
    busy. Callers that intentionally run managed per-frame render updates may
    pass ``False`` and inspect the session flags separately.

    Unknown state is kept distinct from idle so mutation-sensitive paths can
    fail closed instead of writing Blender IDs while a render may be active.
    """
    if include_guard:
        try:
            if bool(_FBP_RUNTIME_STATE.get("fbp_render_guard_active", False)):
                return FBP_RENDER_BUSY
        except Exception as exc:
            fbp_warn_once(
                "render_guard_state_query_failed",
                "Could not read the Frame by Plane render guard",
                exc,
            )
            return FBP_RENDER_UNKNOWN

    try:
        import bpy

        is_job_running = getattr(bpy.app, "is_job_running", None)
        if not callable(is_job_running):
            fbp_warn_once(
                "render_job_api_unavailable",
                "Blender render-job state is unavailable; unsafe updates are paused",
            )
            return FBP_RENDER_UNKNOWN
        return FBP_RENDER_BUSY if bool(is_job_running("RENDER")) else FBP_RENDER_IDLE
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn_once(
            "render_job_state_query_failed",
            "Could not confirm Blender render-job state; unsafe updates are paused",
            exc,
        )
        return FBP_RENDER_UNKNOWN


def fbp_render_mutation_blocked(*, include_guard=True):
    """Return True unless Blender is confirmed idle for ID-datablock writes."""
    return fbp_render_state(include_guard=include_guard) != FBP_RENDER_IDLE


# Runtime-only state.
# Do NOT store transient flags in WindowManager/Object ID properties: Blender 5.2
# can crash while freeing IDProperties during undo/depsgraph rebuilds.
_FBP_RUNTIME_STATE = {}
_FBP_SILENT_OBJECT_POINTERS = {}


def fbp_runtime_get(key, default=None, context=None):
    try:
        return _FBP_RUNTIME_STATE.get(str(key), default)
    except (TypeError, ValueError):
        return default


def fbp_undo_guard_active(*, release_expired=False):
    """Return the transient Undo/load guard.

    ``release_expired`` must be used only from an idle Blender timer. Property,
    frame and depsgraph callbacks keep the guard strict because they can execute
    while Main is still being replaced. The persistent watchdog and the slow
    safety timer use the opt-in release path after Blender returns to its event
    loop, preventing a missed ``undo_post``/``load_post`` from freezing FBP.
    """
    try:
        active = bool(_FBP_RUNTIME_STATE.get("fbp_undo_in_progress", False))
    except (TypeError, ValueError):
        return False
    if not active or not release_expired:
        return active

    try:
        deadline = float(_FBP_RUNTIME_STATE.get("fbp_undo_guard_deadline", 0.0) or 0.0)
    except (TypeError, ValueError):
        deadline = 0.0
    if deadline <= 0.0 or time.monotonic() < deadline:
        return True

    _FBP_RUNTIME_STATE["fbp_undo_in_progress"] = False
    _FBP_RUNTIME_STATE["fbp_undo_guard_deadline"] = 0.0
    fbp_warn_once(
        "undo_guard_runtime_failsafe",
        "Undo/load guard exceeded its safety deadline and was released automatically",
    )
    return False

def fbp_runtime_set(key, value, context=None):
    try:
        _FBP_RUNTIME_STATE[str(key)] = value
        return True
    except Exception as exc:
        fbp_warn(f"Could not store runtime state {key}", exc)
        return False


def fbp_rna_runtime_key(value):
    """Return a plain Blender 5.2 runtime identity without retaining RNA.

    ID datablocks use ``session_uid`` and keep the historical negative-integer
    representation used by FBP runtime state. Modifiers use ``persistent_uid``
    together with their owner identity. Other RNA values fall back to pointers.
    """
    if value is None:
        return None
    try:
        session_uid = int(getattr(value, "session_uid", 0) or 0)
        if session_uid > 0:
            return -session_uid
    except FBP_DATA_ERRORS:
        pass
    try:
        persistent_uid = int(getattr(value, "persistent_uid", 0) or 0)
        if persistent_uid > 0:
            owner = getattr(value, "id_data", None)
            owner_key = fbp_obj_runtime_key(owner) if owner is not None else None
            return ("MOD", owner_key, persistent_uid)
    except FBP_DATA_ERRORS:
        pass
    try:
        return int(value.as_pointer())
    except FBP_DATA_ERRORS:
        try:
            return str(getattr(value, "name_full", getattr(value, "name", "")) or "")
        except FBP_DATA_ERRORS:
            return None


def fbp_obj_runtime_key(obj):
    """Return a transient ID identity resistant to pointer reuse after deletion."""
    if obj is None:
        return None
    try:
        session_uid = int(getattr(obj, "session_uid", 0) or 0)
        if session_uid > 0:
            return -session_uid
    except FBP_DATA_ERRORS:
        pass
    try:
        return int(obj.as_pointer())
    except FBP_DATA_ERRORS:
        try:
            return str(getattr(obj, "name_full", getattr(obj, "name", "")) or "")
        except FBP_DATA_ERRORS:
            return None


def fbp_modifier_runtime_key(modifier):
    """Return the Blender 5.2 persistent identity of a modifier."""
    return fbp_rna_runtime_key(modifier)


def fbp_runtime_key_from_token(value):
    """Return the runtime-key type represented by a transient RNA token.

    Blender operator StringProperties cannot retain integer ``session_uid`` or
    pointer keys.  Several long-lived operators therefore serialize the key as
    text while a file browser or dialog is open.  Comparing that text directly
    with the integer returned by :func:`fbp_obj_runtime_key` silently breaks
    rename-safe target resolution.  Normalize signed integer tokens back to
    integers while preserving genuine name fallbacks.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = fbp_normalize_obj_runtime_token(value)
    if not text:
        return None
    try:
        # ``session_uid`` keys are negative and pointer fallbacks are positive.
        # Reject whitespace/decimal variants so object names such as ``001``
        # remain readable name fallbacks rather than accidental pointers.
        if text == str(int(text)):
            return int(text)
    except (TypeError, ValueError, OverflowError):
        pass
    return text


def fbp_obj_matches_runtime_key(obj, key):
    """Return True when an RNA value still represents one runtime identity."""
    if obj is None or key is None:
        return False
    try:
        return fbp_obj_runtime_key(obj) == fbp_runtime_key_from_token(key)
    except FBP_DATA_ERRORS:
        return False


def fbp_find_id_by_runtime_key(collection, key, name=""):
    """Resolve a Blender ID by stable runtime identity with a fast name path.

    Names are checked first because that is O(1) for bpy.data collections. A
    linear fallback handles user renames without accepting a newly
    created datablock that merely reused the old name or memory address.
    """
    if collection is None or key is None:
        return None
    candidate = None
    if name:
        try:
            getter = getattr(collection, "get", None)
            candidate = getter(str(name)) if callable(getter) else None
        except Exception:
            candidate = None
        if fbp_obj_matches_runtime_key(candidate, key):
            return candidate
    try:
        for item in collection:
            if fbp_obj_matches_runtime_key(item, key):
                return item
    except FBP_DATA_IO_ERRORS:
        return None
    return None


def fbp_add_transform_driver_variable(driver, name, obj, transform_type):
    """Add one world-space transform variable to a Blender driver."""
    variable = driver.variables.new()
    variable.name = str(name)
    variable.type = "TRANSFORMS"
    target = variable.targets[0]
    target.id = obj
    target.transform_type = str(transform_type)
    target.transform_space = "WORLD_SPACE"
    if str(transform_type).startswith("ROT_") and hasattr(target, "rotation_mode"):
        target.rotation_mode = "XYZ"
    return variable


def fbp_capture_runtime_targets(targets) -> str:
    """Serialize Blender ID identities for deferred work across RNA rebuilds."""
    payload = []
    for target in targets or ():
        token = fbp_obj_runtime_token(target)
        if not token:
            continue
        payload.append({
            "name": fbp_object_name(target),
            "key": token,
        })
    return json.dumps(payload, separators=(",", ":"))


def fbp_obj_runtime_token(obj):
    """Return the canonical string token stored by transient UI rows.

    Runtime caches may keep integer pointer keys, but RNA StringProperties must
    always use this plain representation. Keeping the conversion in one place
    prevents tuple/debug representations from leaking into the layer resolver.
    """
    key = fbp_obj_runtime_key(obj)
    return "" if key is None else str(key)


def fbp_normalize_obj_runtime_token(value):
    """Normalize runtime tokens written by current or briefly broken builds."""
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith(("PTR:", "NAME:")):
        return text.split(":", 1)[1].strip()
    return text


def fbp_obj_matches_runtime_token(obj, token):
    if obj is None:
        return False
    expected = fbp_normalize_obj_runtime_token(token)
    return bool(expected and fbp_obj_runtime_token(obj) == expected)


def fbp_is_silent_property_update(obj):
    key = fbp_obj_runtime_key(obj)
    return bool(key is not None and _FBP_SILENT_OBJECT_POINTERS.get(key, 0) > 0)


def _fbp_runtime_values_equal(current, value, tolerance=1.0e-9):
    if current is value:
        return True
    try:
        if isinstance(current, (int, float, bool)) and isinstance(value, (int, float, bool)):
            return abs(float(current) - float(value)) <= tolerance
        if isinstance(current, str) or isinstance(value, str):
            return current == value
        return tuple(current) == tuple(value)
    except (TypeError, ValueError, OverflowError):
        try:
            return bool(current == value)
        except (ReferenceError, RuntimeError, TypeError, ValueError):
            return False


def fbp_set_rna_property_silent(obj, prop_name, value):
    """Set changed RNA only, while suppressing its update callback."""
    if obj is None:
        return False
    try:
        if _fbp_runtime_values_equal(getattr(obj, prop_name), value):
            return False
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    key = fbp_obj_runtime_key(obj)
    try:
        if key is not None:
            _FBP_SILENT_OBJECT_POINTERS[key] = _FBP_SILENT_OBJECT_POINTERS.get(key, 0) + 1
        setattr(obj, prop_name, value)
        return True
    except ReferenceError:
        return False
    except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
        fbp_warn(f"Could not set registered property {prop_name}", exc)
        return False
    finally:
        if key is not None:
            remaining = _FBP_SILENT_OBJECT_POINTERS.get(key, 0) - 1
            if remaining > 0:
                _FBP_SILENT_OBJECT_POINTERS[key] = remaining
            else:
                _FBP_SILENT_OBJECT_POINTERS.pop(key, None)


def fbp_action_fcurves(id_block):
    """Return Action F-Curves across Blender 5.2 action slots."""
    animation_data = getattr(id_block, "animation_data", None) if id_block else None
    action = getattr(animation_data, "action", None) if animation_data else None
    slot = getattr(animation_data, "action_slot", None) if animation_data else None
    if not action:
        return None
    if slot is not None:
        try:
            from bpy_extras import anim_utils

            channelbag = anim_utils.action_get_channelbag_for_slot(action, slot)
            curves = getattr(channelbag, "fcurves", None) if channelbag else None
            if curves is not None:
                return curves
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    # Some programmatically
    # created Actions can temporarily lack a resolved slot. Keep their curves
    # visible to the effect runtime instead of silently disabling animation.
    try:
        return getattr(action, "fcurves", None)
    except (AttributeError, ReferenceError, RuntimeError):
        return None

def fbp_find_action_fcurve(id_block, data_path, array_index=None):
    curves = fbp_action_fcurves(id_block)
    if curves is None:
        return None
    for curve in curves:
        if curve.data_path != data_path:
            continue
        if array_index is None or int(getattr(curve, "array_index", 0)) == int(array_index):
            return curve
    return None


def fbp_remove_action_fcurves(id_block, data_path):
    curves = fbp_action_fcurves(id_block)
    if curves is None:
        return 0
    removed = 0
    for curve in list(curves):
        if curve.data_path != data_path:
            continue
        try:
            curves.remove(curve)
            removed += 1
        except FBP_DATA_ERRORS:
            pass
    return removed

def fbp_runtime_clear():
    """Clear every transient add-on flag during unregister/reload."""
    global _FBP_REDRAW_ALL_AREAS, _FBP_REDRAW_ALL_REGIONS, _FBP_REDRAW_ALL_WINDOWS
    _FBP_RUNTIME_STATE.clear()
    _FBP_SILENT_OBJECT_POINTERS.clear()
    fbp_invalidate_selection_snapshot()
    fbp_clear_diagnostics()
    _FBP_REDRAW_AREA_TYPES.clear()
    _FBP_REDRAW_REGION_TYPES.clear()
    _FBP_REDRAW_ALL_AREAS = False
    _FBP_REDRAW_ALL_REGIONS = False
    _FBP_REDRAW_ALL_WINDOWS = False


def _unregister_redraw_timer(callback):
    if callback is None:
        return
    try:
        import bpy
        if bpy.app.timers.is_registered(callback):
            bpy.app.timers.unregister(callback)
    except FBP_DATA_ERRORS:
        pass


def register():
    # An in-place extension reload can leave either the former direct timer or
    # its dispatcher task alive. Retire both before accepting new requests.
    if _PREVIOUS_REDRAW_TIMER is not _fbp_flush_redraw_requests:
        _unregister_redraw_timer(_PREVIOUS_REDRAW_TIMER)
    _unregister_redraw_timer(_fbp_flush_redraw_requests)
    _fbp_cancel_redraw_flush_task()
    fbp_runtime_clear()
    fbp_begin_addon_startup()


def unregister():
    fbp_quiesce_runtime_callbacks()
    fbp_runtime_clear()
