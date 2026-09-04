"""Compatibility facade for deferred one-shot Frame By Plane work.

Feature modules keep using ``schedule_once`` while the actual lifecycle,
coalescing, priority ordering and Blender timer ownership live in
:mod:`runtime_scheduler`.
"""

from __future__ import annotations

from .runtime import fbp_runtime_get, fbp_undo_guard_active
from .runtime_scheduler import (
    PRIORITY_IDLE,
    PRIORITY_INTERACTIVE,
    PRIORITY_MAINTENANCE,
    PRIORITY_NORMAL,
    cancel_task_prefixes,
    clear_tasks,
    normalize_task_counter,
    normalize_task_delay,
    normalize_task_key,
    schedule_task,
    scheduler_accepting_tasks,
    scheduler_callback_is_safe,
    scheduler_dispatcher_callback,
    normalize_task_interval,
    task_is_scheduled,
)

# Deferred callback closures are tied to one Python/RNA generation. Reusing the
# old facade dictionaries during an in-place extension reload can keep stale
# Object/Scene wrappers alive even after the scheduler timer was retired.
_SCHEDULED_KEYS = set()
_SCHEDULED_RUNNERS = {}
_SCHEDULED_CALLBACKS = {}
_SCHEDULED_GENERATIONS = {}
_SCHEDULED_TASK_EPOCHS = {}
_TASK_EPOCH = normalize_task_counter(globals().get("_TASK_EPOCH", 0)) + 1


def _priority_for_key(key):
    name = normalize_task_key(key).lower()
    if any(token in name for token in ("dirty.flush", "preview.queue", "mask_live", "selection")):
        return PRIORITY_INTERACTIVE
    if any(token in name for token in ("cleanup", "orphan", "diagnostic", "audit")):
        return PRIORITY_IDLE
    if any(token in name for token in ("sync", "rebuild", "refresh", "repair")):
        return PRIORITY_MAINTENANCE
    return PRIORITY_NORMAL


def _drop_key(key):
    _SCHEDULED_KEYS.discard(key)
    _SCHEDULED_RUNNERS.pop(key, None)
    _SCHEDULED_CALLBACKS.pop(key, None)
    _SCHEDULED_GENERATIONS.pop(key, None)
    _SCHEDULED_TASK_EPOCHS.pop(key, None)


def _prune_scheduled_registry():
    """Drop wrapper metadata for tasks no longer owned by the scheduler.

    Low-level cancellation is used by lifecycle repair and diagnostics. Without
    reconciliation, the compatibility registry could keep reporting pending
    work after the dispatcher task had already been removed.
    """
    stale = tuple(key for key in _SCHEDULED_KEYS if not task_is_scheduled(key))
    for key in stale:
        _drop_key(key)
    return len(stale)


def invalidate_task_epoch():
    """Invalidate captured one-shot payloads without clearing timer ownership.

    This variant is safe for Blender ``undo_pre`` and ``load_pre`` callbacks.
    Stale facade metadata is reconciled later from the ordinary idle loop.
    """
    global _TASK_EPOCH
    _TASK_EPOCH += 1
    return _TASK_EPOCH


def bump_task_epoch():
    """Eagerly retire deferred mutations from a safe idle context."""
    global _TASK_EPOCH
    _TASK_EPOCH += 1
    clear_scheduled()
    return _TASK_EPOCH


def schedule_once(name, callback, *, first_interval=0.03):
    """Schedule one deduplicated safe task through the shared dispatcher.

    Repeated calls keep only the latest callback payload and never postpone an
    earlier due time. A positive numeric return value reschedules the same key.
    The return value is idempotent: ``True`` means the request is active, while
    ``False`` is reserved for a real scheduling rejection.
    """
    if not callable(callback) or not scheduler_accepting_tasks():
        return False
    if not scheduler_callback_is_safe(name, callback):
        return False
    normalized_delay = normalize_task_delay(first_interval)
    if normalized_delay is None:
        return False
    try:
        if fbp_undo_guard_active() or bool(fbp_runtime_get("fbp_pause_managed_timers", False)):
            return False
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False

    key = normalize_task_key(name)
    if not key:
        key = normalize_task_key(getattr(callback, "__name__", "fbp_safe_task"))
    if not key:
        key = "fbp_safe_task"
    epoch = _TASK_EPOCH
    _SCHEDULED_CALLBACKS[key] = callback

    runner = _SCHEDULED_RUNNERS.get(key)
    if runner is None or _SCHEDULED_TASK_EPOCHS.get(key) != epoch:
        def runner():
            keep = False
            run_generation = normalize_task_counter(_SCHEDULED_GENERATIONS.get(key, 0))
            try:
                if _SCHEDULED_TASK_EPOCHS.get(key) != epoch:
                    return None
                current = _SCHEDULED_CALLBACKS.get(key)
                if not callable(current):
                    return None
                # The scheduler owns only this facade runner. The actual payload
                # lives in our registry and may acquire RNA through a mutable
                # closure after it was queued, so validate it again immediately
                # before execution.
                if not scheduler_callback_is_safe(key, current):
                    return None
                repeat_interval = normalize_task_interval(current())
                keep = repeat_interval is not None
                return repeat_interval
            finally:
                # A callback may schedule a newer payload for this same key while
                # it is executing.  Do not let the older invocation erase that
                # payload merely because the older callback returned ``None``.
                if (
                    not keep
                    and normalize_task_counter(_SCHEDULED_GENERATIONS.get(key, 0))
                    == run_generation
                ):
                    _drop_key(key)

        runner.__name__ = f"fbp_safe_task_{abs(hash(key))}"
        runner.__module__ = __name__
        _SCHEDULED_RUNNERS[key] = runner

    _SCHEDULED_KEYS.add(key)
    _SCHEDULED_GENERATIONS[key] = normalize_task_counter(
        _SCHEDULED_GENERATIONS.get(key, 0)
    ) + 1
    _SCHEDULED_TASK_EPOCHS[key] = epoch
    accepted = schedule_task(
        key,
        _SCHEDULED_RUNNERS[key],
        delay=normalized_delay,
        priority=_priority_for_key(key),
        category="safe",
        persistent=False,
        restart=False,
    )
    if not accepted and not task_is_scheduled(key):
        _drop_key(key)
        return False
    return True


def cancel_scheduled_prefixes(*prefixes):
    normalized = tuple(
        value for value in (normalize_task_key(prefix) for prefix in prefixes) if value
    )
    if not normalized:
        return 0
    keys = tuple(key for key in _SCHEDULED_KEYS if key.startswith(normalized))
    removed = cancel_task_prefixes(*normalized, category="safe")
    for key in keys:
        _drop_key(key)
    return removed


def clear_scheduled():
    keys = tuple(_SCHEDULED_KEYS)
    removed = clear_tasks(category="safe")
    for key in keys:
        _drop_key(key)
    return max(removed, len(keys))


def scheduled_task_count():
    _prune_scheduled_registry()
    return len(_SCHEDULED_KEYS)


def scheduled_task_pending(name):
    key = normalize_task_key(name)
    if not key:
        return False
    pending = task_is_scheduled(key)
    if not pending and key in _SCHEDULED_KEYS:
        _drop_key(key)
    return pending


def scheduled_dispatcher_callback():
    """Expose the single Blender timer callback for lifecycle diagnostics."""
    return scheduler_dispatcher_callback()


def _reset_task_epoch():
    global _TASK_EPOCH
    _TASK_EPOCH += 1
    clear_scheduled()


def register():
    _reset_task_epoch()


def unregister():
    _reset_task_epoch()


__all__ = (
    "bump_task_epoch",
    "invalidate_task_epoch",
    "cancel_scheduled_prefixes",
    "clear_scheduled",
    "register",
    "schedule_once",
    "scheduled_dispatcher_callback",
    "scheduled_task_count",
    "scheduled_task_pending",
    "unregister",
)
