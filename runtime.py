"""Runtime-only state and diagnostics shared across Frame by Plane modules.

This module intentionally does not import other add-on modules. Keeping it at the
bottom of the dependency graph prevents circular imports during registration.
"""

def fbp_log(message, level="INFO", exc=None):
    """Small addon logger used instead of silently swallowing unexpected errors."""
    try:
        suffix = f": {exc}" if exc else ""
        print(f"[FBP {level}] {message}{suffix}")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass


def fbp_warn(message, exc=None):
    fbp_log(message, "Warning", exc)


# Runtime-only state.
# Do NOT store transient flags in WindowManager/Object ID properties: Blender 5.1
# can crash while freeing IDProperties during undo/depsgraph rebuilds.
_FBP_RUNTIME_STATE = {}
_FBP_SILENT_OBJECT_POINTERS = set()


def fbp_runtime_get(key, default=None, context=None):
    try:
        return _FBP_RUNTIME_STATE.get(str(key), default)
    except Exception:
        return default


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
    return bool(key is not None and key in _FBP_SILENT_OBJECT_POINTERS)


def fbp_set_rna_property_silent(obj, prop_name, value):
    """Set an RNA property while suppressing its update callback."""
    if not obj:
        return False
    key = fbp_obj_runtime_key(obj)
    try:
        if key is not None:
            _FBP_SILENT_OBJECT_POINTERS.add(key)
        setattr(obj, prop_name, value)
        return True
    except ReferenceError:
        return False
    except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
        fbp_warn(f"Could not set registered property {prop_name}", exc)
        return False
    finally:
        if key is not None:
            _FBP_SILENT_OBJECT_POINTERS.discard(key)
