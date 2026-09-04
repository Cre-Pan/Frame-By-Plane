"""Compatibility facade for recurring and lifecycle timers.

All callbacks are now tasks in the shared :mod:`runtime_scheduler`; Blender owns
one dispatcher timer instead of one closure per subsystem.
"""

from __future__ import annotations

from .runtime_scheduler import (
    PRIORITY_CRITICAL,
    PRIORITY_IDLE,
    PRIORITY_MAINTENANCE,
    PRIORITY_NORMAL,
    bump_scheduler_epoch,
    invalidate_scheduler_epoch,
    cancel_task,
    clear_tasks,
    normalize_task_counter,
    normalize_task_delay,
    normalize_task_interval,
    schedule_task,
    scheduler_accepting_tasks,
    scheduler_callback_is_safe,
    task_is_scheduled,
)

# Managed callbacks from a former module generation must never be retained.
# The shared scheduler retires its persistent dispatcher at import time; reset
# this compatibility facade at the same boundary so no stale bound method or
# local closure survives until register().
_FBP_REGISTERED_TIMERS = {}
_FBP_TIMER_PERSISTENT = {}
_FBP_TIMER_RUNNERS = {}
_FBP_TIMER_GENERATIONS = {}
_FBP_TIMER_EPOCH = normalize_task_counter(globals().get("_FBP_TIMER_EPOCH", 0)) + 1


def _fbp_timer_registry_key(callback):
    """Return a stable key without merging unrelated local callbacks.

    Top-level functions intentionally keep a reload-stable ``module.qualname``
    identity so a new add-on generation replaces the previous callback. Local
    closures and bound methods, however, need an instance component: two modal
    operators can otherwise expose the same ``__name__`` and silently steal one
    another's managed timer slot.
    """
    callback_module = str(getattr(callback, "__module__", "") or "")
    callback_qualname = str(
        getattr(callback, "__qualname__", "")
        or getattr(callback, "__name__", "")
        or type(callback).__qualname__
    )
    owner = getattr(callback, "__self__", None)
    if owner is not None:
        function = getattr(callback, "__func__", callback)
        return (
            f"{callback_module}.{callback_qualname}"
            f"@{id(owner):x}:{id(function):x}"
        )
    if "<locals>" in callback_qualname:
        return f"{callback_module}.{callback_qualname}@{id(callback):x}"
    return f"{callback_module}.{callback_qualname}"


def _scheduler_key(callback):
    return f"managed:{_fbp_timer_registry_key(callback)}"


def _priority_for_callback(callback):
    name = str(getattr(callback, "__name__", "") or "").lower()
    if "watchdog" in name:
        return PRIORITY_CRITICAL
    if any(token in name for token in ("cleanup", "orphan")):
        return PRIORITY_IDLE
    if any(token in name for token in ("sync", "rebuild", "refresh")):
        return PRIORITY_MAINTENANCE
    return PRIORITY_NORMAL


def fbp_invalidate_timer_epoch():
    """Invalidate pre-history managed work without unregistering Blender timers.

    The persistent scheduler watchdog remains alive and performs actual cleanup
    only after Blender returns to its idle event loop.
    """
    global _FBP_TIMER_EPOCH
    _FBP_TIMER_EPOCH += 1
    invalidate_scheduler_epoch()
    return _FBP_TIMER_EPOCH


def fbp_bump_timer_epoch():
    """Eagerly retire non-persistent work from a safe idle context."""
    global _FBP_TIMER_EPOCH
    _FBP_TIMER_EPOCH += 1
    bump_scheduler_epoch()
    for key in tuple(_FBP_REGISTERED_TIMERS):
        if not bool(_FBP_TIMER_PERSISTENT.get(key, False)):
            _FBP_REGISTERED_TIMERS.pop(key, None)
            _FBP_TIMER_PERSISTENT.pop(key, None)
            _FBP_TIMER_RUNNERS.pop(key, None)
            _FBP_TIMER_GENERATIONS.pop(key, None)
    return _FBP_TIMER_EPOCH


def fbp_timer_is_registered(callback):
    if callback is None:
        return False
    return task_is_scheduled(_scheduler_key(callback))


def fbp_unregister_managed_timer(callback):
    if callback is None:
        return False
    key = _fbp_timer_registry_key(callback)
    removed = cancel_task(_scheduler_key(callback))
    _FBP_REGISTERED_TIMERS.pop(key, None)
    _FBP_TIMER_PERSISTENT.pop(key, None)
    _FBP_TIMER_RUNNERS.pop(key, None)
    _FBP_TIMER_GENERATIONS.pop(key, None)
    return removed


def fbp_prune_timer_registry():
    removed = 0
    for key, callback in tuple(_FBP_REGISTERED_TIMERS.items()):
        if fbp_timer_is_registered(callback):
            continue
        _FBP_REGISTERED_TIMERS.pop(key, None)
        _FBP_TIMER_PERSISTENT.pop(key, None)
        _FBP_TIMER_RUNNERS.pop(key, None)
        _FBP_TIMER_GENERATIONS.pop(key, None)
        removed += 1
    return removed


def fbp_register_timer_once(callback, first_interval, *, persistent=False, restart=False):
    if not callable(callback) or not scheduler_accepting_tasks():
        return False
    if not scheduler_callback_is_safe(_scheduler_key(callback), callback):
        return False
    normalized_delay = normalize_task_delay(first_interval)
    if normalized_delay is None:
        return False
    key = _fbp_timer_registry_key(callback)
    name = str(getattr(callback, "__name__", "") or "")
    already = task_is_scheduled(_scheduler_key(callback))
    _FBP_REGISTERED_TIMERS[key] = callback
    _FBP_TIMER_PERSISTENT[key] = bool(persistent)
    _FBP_TIMER_GENERATIONS[key] = normalize_task_counter(
        _FBP_TIMER_GENERATIONS.get(key, 0)
    ) + 1
    runner = _FBP_TIMER_RUNNERS.get(key)
    if runner is None:
        def runner():
            keep = False
            run_generation = normalize_task_counter(_FBP_TIMER_GENERATIONS.get(key, 0))
            try:
                current = _FBP_REGISTERED_TIMERS.get(key)
                if not callable(current):
                    return None
                # The shared scheduler can inspect only this facade runner.
                # Revalidate the real managed callback at dispatch time because
                # mutable defaults/closures may have gained Blender RNA since
                # registration.
                if not scheduler_callback_is_safe(_scheduler_key(current), current):
                    return None
                repeat_interval = normalize_task_interval(current())
                keep = repeat_interval is not None
                return repeat_interval
            finally:
                # Re-registering the timer from inside its own callback creates a
                # newer request.  Preserve it instead of letting the older run's
                # cleanup orphan the still-scheduled dispatcher record.
                if (
                    not keep
                    and normalize_task_counter(_FBP_TIMER_GENERATIONS.get(key, 0))
                    == run_generation
                ):
                    _FBP_REGISTERED_TIMERS.pop(key, None)
                    _FBP_TIMER_PERSISTENT.pop(key, None)
                    _FBP_TIMER_RUNNERS.pop(key, None)
                    _FBP_TIMER_GENERATIONS.pop(key, None)

        runner.__name__ = f"fbp_managed_{abs(hash(key))}"
        runner.__module__ = __name__
        _FBP_TIMER_RUNNERS[key] = runner
    accepted = schedule_task(
        _scheduler_key(callback),
        _FBP_TIMER_RUNNERS[key],
        delay=normalized_delay,
        priority=_priority_for_callback(callback),
        category="managed",
        persistent=bool(persistent),
        restart=bool(restart),
        allow_during_undo=name == "fbp_undo_guard_watchdog",
        allow_during_render=name == "fbp_render_guard_watchdog",
    )
    scheduled = task_is_scheduled(_scheduler_key(callback))
    if not accepted and not scheduled:
        _FBP_REGISTERED_TIMERS.pop(key, None)
        _FBP_TIMER_PERSISTENT.pop(key, None)
        _FBP_TIMER_RUNNERS.pop(key, None)
        _FBP_TIMER_GENERATIONS.pop(key, None)
        return False
    # "Register once" is idempotent: an already-running task is a successful
    # service state, not a registration failure. Callers use this result for
    # Project Health and runtime-service status reporting.
    return bool(accepted or scheduled or (restart and already))


def fbp_managed_timer_callbacks():
    fbp_prune_timer_registry()
    return tuple(_FBP_REGISTERED_TIMERS.values())


def fbp_managed_timer_registry_snapshot():
    fbp_prune_timer_registry()
    return dict(_FBP_REGISTERED_TIMERS)


def fbp_clear_managed_timers():
    removed = clear_tasks(category="managed")
    count = max(removed, len(_FBP_REGISTERED_TIMERS))
    _FBP_REGISTERED_TIMERS.clear()
    _FBP_TIMER_PERSISTENT.clear()
    _FBP_TIMER_RUNNERS.clear()
    _FBP_TIMER_GENERATIONS.clear()
    return count


def register():
    fbp_bump_timer_epoch()
    fbp_clear_managed_timers()


def unregister():
    fbp_bump_timer_epoch()
    fbp_clear_managed_timers()


__all__ = (
    "fbp_bump_timer_epoch",
    "fbp_invalidate_timer_epoch",
    "fbp_clear_managed_timers",
    "fbp_managed_timer_callbacks",
    "fbp_managed_timer_registry_snapshot",
    "fbp_prune_timer_registry",
    "fbp_register_timer_once",
    "fbp_timer_is_registered",
    "fbp_unregister_managed_timer",
)
