"""Runtime-only state and diagnostics shared across Frame by Plane modules.

This module intentionally does not import other add-on modules. Keeping it at the
bottom of the dependency graph prevents circular imports during registration.
"""

import random
import time

FBP_DATA_ERRORS = (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError)
FBP_DATA_IO_ERRORS = FBP_DATA_ERRORS + (KeyError, IndexError, OSError)


# One process-local generator is seeded once by Python and then reused for
# persistent internal identifiers. These tokens are not security credentials;
# avoiding one operating-system entropy read per effect materially reduces the
# cost of generating large Multiplane/effects projects while retaining a
# 128-bit collision space.
_FBP_TOKEN_RANDOM = random.Random()


def fbp_unique_token_hex():
    """Return a compact 128-bit token for persistent internal identities."""
    return f"{_FBP_TOKEN_RANDOM.getrandbits(128):032x}"


def fbp_log(message, level="INFO", exc=None):
    """Small addon logger used instead of silently swallowing unexpected errors."""
    try:
        suffix = f": {exc}" if exc else ""
        print(f"[FBP {level}] {message}{suffix}")
    except FBP_DATA_IO_ERRORS:
        pass


def fbp_warn(message, exc=None):
    fbp_log(message, "Warning", exc)


_FBP_WARNED_KEYS = set()


def fbp_warn_once(key, message, exc=None):
    """Log a warning once per add-on module lifetime.

    Property callbacks can run many times during playback and UI edits. This
    keeps diagnostics visible without flooding Blender's console repeatedly.
    """
    token = str(key or message)
    if token in _FBP_WARNED_KEYS:
        return False
    _FBP_WARNED_KEYS.add(token)
    fbp_warn(message, exc)
    return True


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
# Do NOT store transient flags in WindowManager/Object ID properties: Blender 5.1
# can crash while freeing IDProperties during undo/depsgraph rebuilds.
_FBP_RUNTIME_STATE = {}
_FBP_SILENT_OBJECT_POINTERS = {}


def fbp_runtime_get(key, default=None, context=None):
    try:
        return _FBP_RUNTIME_STATE.get(str(key), default)
    except Exception:
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
    except Exception:
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


def fbp_obj_runtime_key(obj):
    """Return a transient identity resistant to pointer reuse after deletion.

    Blender 5.1 exposes ``ID.session_uid`` for runtime identity. Store it as a
    negative integer so it cannot alias an ordinary positive memory pointer.
    Older or non-ID RNA values keep the pointer/name fallback.
    """
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
            return str(getattr(obj, "name", ""))
        except FBP_DATA_ERRORS:
            return None


def fbp_obj_matches_runtime_key(obj, key):
    """Return True when an RNA value still represents one runtime identity."""
    if obj is None or key is None:
        return False
    try:
        return fbp_obj_runtime_key(obj) == key
    except Exception:
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
    except Exception:
        return None
    return None


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
    if text.startswith("PTR:") or text.startswith("NAME:"):
        return text.split(":", 1)[1].strip()
    # 4.9.14 accidentally stored ``str(("PTR", pointer))`` in UI rows.
    # Accept that transient representation so an open session can self-repair.
    if text.startswith("(") and text.endswith(")"):
        inner = text[1:-1].strip()
        if "," in inner:
            prefix, payload = inner.split(",", 1)
            if prefix.strip().strip("'\"") in {"PTR", "NAME"}:
                payload = payload.strip()
                if payload.endswith(","):
                    payload = payload[:-1].rstrip()
                return payload.strip().strip("'\"")
    return text


def fbp_obj_matches_runtime_token(obj, token):
    if obj is None:
        return False
    expected = fbp_normalize_obj_runtime_token(token)
    return bool(expected and fbp_obj_runtime_token(obj) == expected)


def fbp_is_silent_property_update(obj):
    key = fbp_obj_runtime_key(obj)
    return bool(key is not None and _FBP_SILENT_OBJECT_POINTERS.get(key, 0) > 0)


def fbp_set_rna_property_silent(obj, prop_name, value):
    """Set an RNA property while suppressing its update callback."""
    if obj is None:
        return False
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
    """Return the Blender 5.1 Action Channelbag F-Curve collection."""
    animation_data = getattr(id_block, "animation_data", None) if id_block else None
    action = getattr(animation_data, "action", None) if animation_data else None
    slot = getattr(animation_data, "action_slot", None) if animation_data else None
    if not action or not slot:
        return None
    try:
        from bpy_extras import anim_utils

        channelbag = anim_utils.action_get_channelbag_for_slot(action, slot)
        return getattr(channelbag, "fcurves", None) if channelbag else None
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
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
    _FBP_RUNTIME_STATE.clear()
    _FBP_SILENT_OBJECT_POINTERS.clear()
    _FBP_WARNED_KEYS.clear()


def unregister():
    fbp_runtime_clear()

