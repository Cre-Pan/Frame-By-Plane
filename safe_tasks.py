# Frame by Plane - Safe Task Scheduler
# Blender 5.1+ can crash if add-ons create/link/remove ID datablocks from
# depsgraph handlers, undo callbacks or UI draw code. This module gives the rest
# of Frame by Plane one place to schedule those mutations for Blender timers.

import time

import bpy

_SCHEDULED_KEYS = globals().get("_SCHEDULED_KEYS", set())
_SCHEDULED_RUNNERS = globals().get("_SCHEDULED_RUNNERS", {})
_SCHEDULED_GENERATIONS = globals().get("_SCHEDULED_GENERATIONS", {})
_PREVIOUS_SCHEDULER_GENERATION = int(globals().get("_SCHEDULER_GENERATION", 0) or 0)

# importlib.reload() reuses the module dictionary. Retire closures from the old
# code generation immediately instead of waiting for another task with the same
# key to replace them. This prevents stale callbacks from executing after reload.
if _PREVIOUS_SCHEDULER_GENERATION > 0:
    for _old_runner in list(_SCHEDULED_RUNNERS.values()):
        try:
            if bpy.app.timers.is_registered(_old_runner):
                bpy.app.timers.unregister(_old_runner)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    _SCHEDULED_KEYS.clear()
    _SCHEDULED_RUNNERS.clear()
    _SCHEDULED_GENERATIONS.clear()

_SCHEDULER_GENERATION = _PREVIOUS_SCHEDULER_GENERATION + 1
_UNKNOWN_GUARD_RETRY_SECONDS = 15.0
_UNKNOWN_GUARD_RETRY_INTERVAL = 0.25


def _task_key(name, callback):
    return str(name or getattr(callback, "__name__", "fbp_safe_task"))


def schedule_once(name, callback, *, first_interval=0.03):
    """Run callback once from bpy.app.timers, deduplicated by name.

    The callback may return a number to reschedule itself, or None to finish.
    The scheduler clears its dedupe key only when the task actually finishes.
    Datablock tasks pause for the complete render session and resume only after
    Blender and the Frame by Plane render guard both report an idle state.
    """
    if not callable(callback):
        return False

    key = _task_key(name, callback)
    if key in _SCHEDULED_KEYS:
        # Blender can silently discard timers during file loads. A Python module
        # reload is different: an old registered closure must be unregistered so
        # it cannot call stale code or clear a new generation's dedupe entry.
        runner = _SCHEDULED_RUNNERS.get(key)
        same_generation = _SCHEDULED_GENERATIONS.get(key) == _SCHEDULER_GENERATION
        try:
            is_registered = bool(runner is not None and bpy.app.timers.is_registered(runner))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            is_registered = False
        if same_generation and is_registered:
            return False
        if is_registered:
            try:
                bpy.app.timers.unregister(runner)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        _SCHEDULED_KEYS.discard(key)
        _SCHEDULED_RUNNERS.pop(key, None)
        _SCHEDULED_GENERATIONS.pop(key, None)

    _SCHEDULED_KEYS.add(key)
    runner_generation = _SCHEDULER_GENERATION
    unknown_guard_since = 0.0

    def _runner():
        nonlocal unknown_guard_since
        repeat_interval = None
        try:
            # A timer queued before Ctrl+Z or file loading must not mutate Blender
            # datablocks while Main is being decoded/replaced. Keep the same
            # deduplicated task pending and retry after the runtime guard releases.
            try:
                from .runtime import (
                    FBP_RENDER_BUSY,
                    FBP_RENDER_UNKNOWN,
                    fbp_render_state,
                    fbp_undo_guard_active,
                )
                if fbp_undo_guard_active():
                    unknown_guard_since = 0.0
                    repeat_interval = 0.10
                    return repeat_interval
                render_state = fbp_render_state()
                if render_state == FBP_RENDER_BUSY:
                    unknown_guard_since = 0.0
                    repeat_interval = 0.10
                    return repeat_interval
                if render_state == FBP_RENDER_UNKNOWN:
                    # A transient UNKNOWN sample can occur while Blender is
                    # replacing Main or reloading modules. Never mutate IDs, but
                    # keep the deduplicated task alive briefly instead of losing
                    # a required repair forever. Unregister/load cleanup still
                    # retires this closure immediately.
                    now = time.monotonic()
                    if unknown_guard_since <= 0.0:
                        unknown_guard_since = now
                    if now - unknown_guard_since < _UNKNOWN_GUARD_RETRY_SECONDS:
                        repeat_interval = _UNKNOWN_GUARD_RETRY_INTERVAL
                        return repeat_interval
                    try:
                        from .runtime import fbp_warn_once
                        fbp_warn_once(
                            f"safe_task_unknown_guard:{key}",
                            f"Deferred task '{key}' was cancelled because Blender's render state stayed unknown",
                        )
                    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                        pass
                    return None
                unknown_guard_since = 0.0
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                # Treat guard-query failures like UNKNOWN: wait for a bounded
                # period, but never guess that Blender is idle.
                now = time.monotonic()
                if unknown_guard_since <= 0.0:
                    unknown_guard_since = now
                if now - unknown_guard_since < _UNKNOWN_GUARD_RETRY_SECONDS:
                    repeat_interval = _UNKNOWN_GUARD_RETRY_INTERVAL
                    return repeat_interval
                return None

            result = callback()
            if (
                not isinstance(result, bool)
                and isinstance(result, (int, float))
                and result > 0
            ):
                repeat_interval = float(result)
                return repeat_interval
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
            # Keep the dedupe lock only while Blender will call this runner again.
            if (
                repeat_interval is None
                and _SCHEDULED_RUNNERS.get(key) is _runner
                and _SCHEDULED_GENERATIONS.get(key) == runner_generation
            ):
                _SCHEDULED_KEYS.discard(key)
                _SCHEDULED_RUNNERS.pop(key, None)
                _SCHEDULED_GENERATIONS.pop(key, None)

    try:
        _SCHEDULED_RUNNERS[key] = _runner
        _SCHEDULED_GENERATIONS[key] = runner_generation
        bpy.app.timers.register(_runner, first_interval=max(0.0, float(first_interval)))
        return True
    except ValueError:
        _SCHEDULED_KEYS.discard(key)
        _SCHEDULED_RUNNERS.pop(key, None)
        _SCHEDULED_GENERATIONS.pop(key, None)
        return False
    except Exception as exc:
        _SCHEDULED_KEYS.discard(key)
        _SCHEDULED_RUNNERS.pop(key, None)
        _SCHEDULED_GENERATIONS.pop(key, None)
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
    _SCHEDULED_GENERATIONS.clear()
