# Frame by Plane - Safe Task Scheduler
# Beta 2: one tiny, centralized wrapper for deferred Blender mutations.
#
# Blender 5.1+ can crash if add-ons create/link/remove ID datablocks from
# depsgraph handlers, undo callbacks or UI draw code. This module gives the rest
# of Frame by Plane one place to schedule those mutations for Blender timers.

import bpy

_SCHEDULED_KEYS = globals().get("_SCHEDULED_KEYS", set())
_SCHEDULED_RUNNERS = globals().get("_SCHEDULED_RUNNERS", {})


def _task_key(name, callback):
    return str(name or getattr(callback, "__name__", "fbp_safe_task"))


def schedule_once(name, callback, *, first_interval=0.03):
    """Run callback once from bpy.app.timers, deduplicated by name.

    The callback may return a number to reschedule itself, or None to finish.
    The scheduler clears its dedupe key only when the task actually finishes.
    """
    if not callable(callback):
        return False

    key = _task_key(name, callback)
    if key in _SCHEDULED_KEYS:
        return False

    _SCHEDULED_KEYS.add(key)

    def _runner():
        try:
            result = callback()
            if not isinstance(result, bool) and isinstance(result, (int, float)) and result > 0:
                return float(result)
            return None
        except ReferenceError:
            return None
        except Exception as exc:
            try:
                print(f"[FBP Safe Task] {key} failed: {exc}")
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
            return None
        finally:
            # If the callback requested a retry, Blender calls this same runner
            # again and the key must stay locked. Otherwise unlock it.
            try:
                repeats = (
                    not isinstance(locals().get('result', None), bool)
                    and isinstance(locals().get('result', None), (int, float))
                    and locals().get('result', 0) > 0
                )
                if not repeats:
                    _SCHEDULED_KEYS.discard(key)
                    _SCHEDULED_RUNNERS.pop(key, None)
            except Exception:
                _SCHEDULED_KEYS.discard(key)
                _SCHEDULED_RUNNERS.pop(key, None)

    try:
        _SCHEDULED_RUNNERS[key] = _runner
        bpy.app.timers.register(_runner, first_interval=max(0.0, float(first_interval)))
        return True
    except ValueError:
        _SCHEDULED_KEYS.discard(key)
        _SCHEDULED_RUNNERS.pop(key, None)
        return False
    except Exception as exc:
        _SCHEDULED_KEYS.discard(key)
        _SCHEDULED_RUNNERS.pop(key, None)
        try:
            print(f"[FBP Safe Task] Could not schedule {key}: {exc}")
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        return False


def clear_scheduled():
    """Unregister pending timer closures and clear all scheduler state."""
    for runner in list(_SCHEDULED_RUNNERS.values()):
        try:
            if bpy.app.timers.is_registered(runner):
                bpy.app.timers.unregister(runner)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    _SCHEDULED_RUNNERS.clear()
    _SCHEDULED_KEYS.clear()
