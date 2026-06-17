"""Runtime-only state and diagnostics shared across Frame by Plane modules.

This module intentionally does not import other add-on modules. Keeping it at the
bottom of the dependency graph prevents circular imports during registration.
"""

import time

def fbp_log(message, level="INFO", exc=None):
    """Small addon logger used instead of silently swallowing unexpected errors."""
    try:
        suffix = f": {exc}" if exc else ""
        print(f"[FBP {level}] {message}{suffix}")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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
    try:
        return int(obj.as_pointer())
    except Exception:
        try:
            return str(getattr(obj, 'name', ''))
        except Exception:
            return None



def fbp_is_silent_property_update(obj):
    key = fbp_obj_runtime_key(obj)
    return bool(key is not None and _FBP_SILENT_OBJECT_POINTERS.get(key, 0) > 0)


def fbp_set_rna_property_silent(obj, prop_name, value):
    """Set an RNA property while suppressing its update callback."""
    if not obj:
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
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    return removed

def fbp_runtime_clear():
    """Clear every transient add-on flag during unregister/reload."""
    _FBP_RUNTIME_STATE.clear()
    _FBP_SILENT_OBJECT_POINTERS.clear()
    _FBP_WARNED_KEYS.clear()


def unregister():
    fbp_runtime_clear()

