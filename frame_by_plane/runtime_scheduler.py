"""Single-dispatcher runtime scheduler for Frame By Plane.

Every deferred add-on task is coalesced by key and executed through one Blender
``bpy.app.timers`` callback.  The dispatcher exists only while work is pending,
orders due tasks by priority, and yields once its per-tick time budget is spent.
This replaces dozens of independent timer closures without changing the public
``safe_tasks`` or ``managed_timers`` APIs used by feature modules.
"""

from __future__ import annotations

import math
from numbers import Real
import time
import types
import weakref

import bpy

from .runtime import (
    FBP_DATA_ERRORS,
    FBP_DATA_IO_ERRORS,
    fbp_error,
    fbp_main_data_ready,
    fbp_registration_busy,
    fbp_render_mutation_blocked,
    fbp_runtime_get,
    fbp_runtime_set,
    fbp_undo_guard_active,
    fbp_warn,
    fbp_warn_once,
)
from .service_registry import register_service, unregister_service


_PREVIOUS_DISPATCHER_CALLBACK = globals().get("_dispatch")
_PREVIOUS_TASKS = globals().get("_TASKS", {})
# Never inherit an accepting lifecycle state across an in-place reload. The
# current generation becomes live only from register(), after the former
# dispatcher and callback payloads have been retired.
_ACCEPTING_TASKS = False


def _retire_reloaded_dispatcher_early(callback):
    """Stop the former generation before any new module can schedule work.

    Extension reinstall/reload unregisters RNA classes and properties while the
    Python package is imported again. A persistent timer from the former module
    generation must not run in that interval: its callback may still retain
    Object, Scene or PropertyGroup wrappers whose C-side data is being freed.
    """
    if callback is None:
        return False
    try:
        if bpy.app.timers.is_registered(callback):
            bpy.app.timers.unregister(callback)
            return True
    except FBP_DATA_IO_ERRORS:
        pass
    return False


_PREVIOUS_DISPATCHER_RETIRED_EARLY = _retire_reloaded_dispatcher_early(
    _PREVIOUS_DISPATCHER_CALLBACK
)

PRIORITY_CRITICAL = 0
PRIORITY_INTERACTIVE = 20
PRIORITY_NORMAL = 50
PRIORITY_MAINTENANCE = 80
PRIORITY_IDLE = 100

_DISPATCH_TIME_BUDGET_SECONDS = 0.006
_DISPATCH_TASK_LIMIT = 48
_MIN_WAKE_SECONDS = 0.001
_MAX_WAKE_SECONDS = 5.0
_WAKE_RESTART_EPSILON_SECONDS = 0.004
_REGISTRY_VALIDATE_SECONDS = 0.25
_RNA_CAPTURE_MAX_DEPTH = 7
_RNA_CAPTURE_MAX_ITEMS = 64
_RNA_CAPTURE_MAX_NODES = 768
_RNA_CAPTURE_INCONCLUSIVE_MARKER = "<scan-inconclusive>"

def _coerce_int(value, default=0):
    if isinstance(value, bool):
        value = default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        try:
            return int(default)
        except (TypeError, ValueError, OverflowError):
            return 0


def _coerce_nonnegative_int(value, default=0):
    return max(0, _coerce_int(value, default))


def _coerce_nonnegative_float(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        try:
            number = float(default or 0.0)
        except (TypeError, ValueError, OverflowError):
            number = 0.0
    if not math.isfinite(number):
        try:
            number = float(default or 0.0)
        except (TypeError, ValueError, OverflowError):
            number = 0.0
    return max(0.0, number)


def _coerce_text(value, default=""):
    if isinstance(value, str):
        return value
    return default if isinstance(default, str) else ""


def _safe_stripped_text(value, default=""):
    """Return stripped text without invoking fragile truthiness or ``__str__``."""
    try:
        text = "" if value is None else str(value).strip()
    except FBP_DATA_ERRORS:
        text = ""
    if text:
        return text
    try:
        return "" if default is None else str(default).strip()
    except FBP_DATA_ERRORS:
        return ""


def normalize_task_key(value):
    """Return the canonical scheduler key used by every public operation."""
    return _safe_stripped_text(value)


def normalize_task_category(value, default=""):
    """Return one canonical category for scheduling and lifecycle cleanup."""
    return _safe_stripped_text(value, default)


def _normalize_reloaded_tasks(value):
    """Keep only canonical dictionary records after a partial module reload."""
    if not isinstance(value, dict):
        return {}
    normalized = {}
    for raw_key, record in tuple(value.items()):
        if not isinstance(record, dict):
            continue
        key = normalize_task_key(raw_key)
        if key:
            normalized[key] = record
    return normalized


# Never inherit callback payloads across an in-place module reload. Even when a
# record is structurally valid, its closure belongs to the previous Python/RNA
# generation and is unsafe after properties or datablocks are replaced.
_RELOADED_TASKS_DROPPED = len(_normalize_reloaded_tasks(_PREVIOUS_TASKS))
_TASKS = {}
_SCHEDULER_EPOCH = _coerce_nonnegative_int(globals().get("_SCHEDULER_EPOCH", 0)) + 1
_SEQUENCE = _coerce_nonnegative_int(globals().get("_SEQUENCE", 0))
_DISPATCHER_ACTIVE = False
_ACTIVE_TASK_KEY = ""
_ACTIVE_TASK_GENERATION = 0
_NEXT_WAKE_AT = 0.0
_DISPATCHER_REGISTERED_HINT = bool(globals().get("_DISPATCHER_REGISTERED_HINT", False))
_DISPATCHER_LAST_VALIDATED = _coerce_nonnegative_float(
    globals().get("_DISPATCHER_LAST_VALIDATED", 0.0)
)

_METRIC_DEFAULTS = {
    "scheduled": 0,
    "coalesced": 0,
    "cancelled": 0,
    "executed": 0,
    "rescheduled": 0,
    "failed": 0,
    "dispatches": 0,
    "budget_yields": 0,
    "wake_restarts": 0,
    "wake_restores": 0,
    "wake_restore_failures": 0,
    "orphaned_tasks_dropped": 0,
    "idle_stops": 0,
    "max_queue": 0,
    "last_duration_ms": 0.0,
    "max_duration_ms": 0.0,
    "last_executed": 0,
    "slow_tasks": 0,
    "max_task_duration_ms": 0.0,
    "slowest_task": "",
    "registry_checks": 0,
    "registry_recoveries": 0,
    "rejected_delays": 0,
    "history_invalidations": 0,
    "invalid_records_dropped": 0,
    "reload_tasks_dropped": 0,
    "reload_dispatchers_retired": 0,
    "teardown_rejections": 0,
    "rna_callbacks_rejected": 0,
    "rna_callbacks_dropped_at_dispatch": 0,
    "rna_scans_inconclusive": 0,
    "reference_errors": 0,
}
_METRICS = globals().get("_METRICS", {})
if not isinstance(_METRICS, dict):
    _METRICS = {}
for _key, _default in _METRIC_DEFAULTS.items():
    _value = _METRICS.get(_key, _default)
    if isinstance(_default, float):
        _METRICS[_key] = _coerce_nonnegative_float(_value, _default)
    elif isinstance(_default, int):
        _METRICS[_key] = _coerce_nonnegative_int(_value, _default)
    else:
        _METRICS[_key] = _coerce_text(_value, _default)
_METRICS["reload_tasks_dropped"] += _RELOADED_TASKS_DROPPED
_METRICS["reload_dispatchers_retired"] += int(_PREVIOUS_DISPATCHER_RETIRED_EARLY)


def _prune_invalid_task_records():
    """Discard non-dictionary queue entries left by interrupted reloads.

    The scheduler stores only plain dictionaries.  A malformed entry must never
    reach guard, sorting or diagnostics code where ``record.get`` would stop the
    single dispatcher and strand every otherwise valid task.
    """
    removed = 0
    for key, record in tuple(_TASKS.items()):
        if isinstance(record, dict):
            continue
        _TASKS.pop(key, None)
        removed += 1
    if removed:
        _METRICS["invalid_records_dropped"] += removed
        _METRICS["failed"] += removed
    return removed



def scheduler_accepting_tasks():
    """Return whether this module generation may accept deferred work."""
    return bool(_ACCEPTING_TASKS)


def _is_blender_rna_instance(value):
    """Identify Blender RNA wrappers without reading any RNA property."""
    if value is None or isinstance(
        value, (str, bytes, bytearray, int, float, complex, bool, type(None))
    ):
        return False
    try:
        rna_base = getattr(getattr(bpy, "types", None), "bpy_struct", None)
        if rna_base is not None and isinstance(value, rna_base):
            return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        value_type = type(value)
        module_name = str(getattr(value_type, "__module__", "") or "")
        type_name = str(getattr(value_type, "__name__", "") or "")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False
    return bool(
        module_name in {"bpy", "bpy_types"}
        or type_name in {"bpy_prop_collection", "bpy_prop_array"}
    )


def _slot_payload_items(value):
    """Return bounded slot values plus whether any payload was truncated."""
    yielded = 0
    truncated = False
    try:
        full_mro = tuple(getattr(type(value), "__mro__", ()) or ())
        if len(full_mro) > 12:
            truncated = True
        mro = full_mro[:12]
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return (), True
    items = []
    for cls in mro:
        try:
            slots = getattr(cls, "__slots__", ())
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            truncated = True
            continue
        if isinstance(slots, str):
            slots = (slots,)
        try:
            slots = tuple(slots or ())
        except (ReferenceError, RuntimeError, TypeError, ValueError):
            truncated = True
            continue
        for slot in slots:
            name = str(slot or "")
            if not name or name in {"__dict__", "__weakref__"}:
                continue
            if yielded >= _RNA_CAPTURE_MAX_ITEMS:
                truncated = True
                continue
            try:
                item = getattr(value, name)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                truncated = True
                continue
            items.append((f"__slots__.{name}", item))
            yielded += 1
    return tuple(items), truncated


def _retained_rna_path(value, path, *, depth=_RNA_CAPTURE_MAX_DEPTH, seen=None, budget=None):
    """Return the first RNA capture path in a bounded callback payload graph.

    The scanner is deliberately deeper than ordinary closure inspection and
    understands partials, bound methods, weak references, ``__dict__`` and
    slotted callable objects.  It is still bounded by a shared node budget so a
    pathological user payload cannot stall Blender while scheduling work.
    """
    if budget is None:
        budget = [int(_RNA_CAPTURE_MAX_NODES)]
    if not budget or budget[0] <= 0:
        return f"{path}.{_RNA_CAPTURE_INCONCLUSIVE_MARKER}:budget"
    budget[0] -= 1
    if _is_blender_rna_instance(value):
        return str(path)
    if depth <= 0:
        try:
            if isinstance(value, dict) and not value:
                return ""
            if isinstance(value, (tuple, list, set, frozenset)) and not value:
                return ""
        except (ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        return f"{path}.{_RNA_CAPTURE_INCONCLUSIVE_MARKER}:depth"
    if value is None or isinstance(
        value, (str, bytes, bytearray, int, float, complex, bool, type, range, types.ModuleType)
    ):
        return ""
    if seen is None:
        seen = set()
    identity = id(value)
    if identity in seen:
        return ""
    seen.add(identity)

    if isinstance(value, weakref.ReferenceType):
        try:
            target = value()
        except (ReferenceError, RuntimeError, TypeError, ValueError):
            target = None
        return _retained_rna_path(
            target, f"{path}.__weakref__", depth=depth - 1, seen=seen, budget=budget
        ) if target is not None else ""

    nested = []
    truncated = False
    if callable(value) and not isinstance(value, type):
        for label, attr in (("__self__", "__self__"), ("__func__", "__func__"), ("func", "func")):
            try:
                item = getattr(value, attr, None)
                if item is not None and item is not value:
                    nested.append((label, item))
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        for attr, label in (("__defaults__", "__defaults__"), ("args", "args")):
            try:
                raw_values = tuple(getattr(value, attr, ()) or ())
                if len(raw_values) > _RNA_CAPTURE_MAX_ITEMS:
                    truncated = True
                values = raw_values[:_RNA_CAPTURE_MAX_ITEMS]
                nested.extend((f"{label}[{index}]", item) for index, item in enumerate(values))
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        for attr, label in (("__kwdefaults__", "__kwdefaults__"), ("keywords", "keywords")):
            try:
                raw_values = tuple(dict(getattr(value, attr, {}) or {}).items())
                if len(raw_values) > _RNA_CAPTURE_MAX_ITEMS:
                    truncated = True
                values = raw_values[:_RNA_CAPTURE_MAX_ITEMS]
                nested.extend((f"{label}.{key}", item) for key, item in values)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        try:
            closure = tuple(getattr(value, "__closure__", ()) or ())
            if len(closure) > _RNA_CAPTURE_MAX_ITEMS:
                truncated = True
            for index, cell in enumerate(closure[:_RNA_CAPTURE_MAX_ITEMS]):
                try:
                    nested.append((f"__closure__[{index}]", cell.cell_contents))
                except (ValueError, ReferenceError, RuntimeError):
                    truncated = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            truncated = True

    try:
        namespace_items = tuple(vars(value).items())
        if len(namespace_items) > _RNA_CAPTURE_MAX_ITEMS:
            truncated = True
        nested.extend(
            (f"__dict__.{key}", item)
            for key, item in namespace_items[:_RNA_CAPTURE_MAX_ITEMS]
        )
    except TypeError:
        pass
    except (AttributeError, ReferenceError, RuntimeError, ValueError):
        truncated = True
    slot_items, slots_truncated = _slot_payload_items(value)
    nested.extend(slot_items)
    truncated = truncated or slots_truncated

    for label, item in nested[:_RNA_CAPTURE_MAX_ITEMS]:
        found = _retained_rna_path(
            item, f"{path}.{label}", depth=depth - 1, seen=seen, budget=budget
        )
        if found:
            return found

    try:
        if isinstance(value, dict):
            container_items = tuple(value.items())
            if len(container_items) > _RNA_CAPTURE_MAX_ITEMS:
                truncated = True
            for index, (key, item) in enumerate(container_items[:_RNA_CAPTURE_MAX_ITEMS]):
                found = _retained_rna_path(
                    key, f"{path}.key[{index}]", depth=depth - 1, seen=seen, budget=budget
                )
                if found:
                    return found
                found = _retained_rna_path(
                    item, f"{path}[{index}]", depth=depth - 1, seen=seen, budget=budget
                )
                if found:
                    return found
        elif isinstance(value, (tuple, list, set, frozenset)):
            container_items = tuple(value)
            if len(container_items) > _RNA_CAPTURE_MAX_ITEMS:
                truncated = True
            for index, item in enumerate(container_items[:_RNA_CAPTURE_MAX_ITEMS]):
                found = _retained_rna_path(
                    item, f"{path}[{index}]", depth=depth - 1, seen=seen, budget=budget
                )
                if found:
                    return found
    except (ReferenceError, RuntimeError, TypeError, ValueError):
        return f"{path}.{_RNA_CAPTURE_INCONCLUSIVE_MARKER}:container"
    if truncated:
        return f"{path}.{_RNA_CAPTURE_INCONCLUSIVE_MARKER}:items"
    return ""


def scheduler_callback_rna_capture(callback):
    """Return a path when a deferred callback retains Blender RNA.

    Deferred work must retain primitive runtime keys and resolve current
    datablocks at execution time. Holding an Object, Scene, PropertyGroup,
    Operator or RNA collection in a closure can outlive Undo, deletion, file
    load or extension reload and is a native-crash risk.
    """
    if not callable(callback):
        return ""
    direct = _retained_rna_path(callback, "callback", depth=_RNA_CAPTURE_MAX_DEPTH)
    if direct:
        return direct
    candidates = []
    try:
        owner = getattr(callback, "__self__", None)
        if owner is not None:
            candidates.append(("callback.__self__", owner))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        defaults = tuple(getattr(callback, "__defaults__", ()) or ())
        candidates.extend(
            (f"callback.__defaults__[{index}]", value)
            for index, value in enumerate(defaults)
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        kwdefaults = dict(getattr(callback, "__kwdefaults__", {}) or {})
        candidates.extend(
            (f"callback.__kwdefaults__.{key}", value)
            for key, value in tuple(kwdefaults.items())
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        closure = tuple(getattr(callback, "__closure__", ()) or ())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        closure = ()
    for index, cell in enumerate(closure):
        try:
            value = cell.cell_contents
        except (ValueError, ReferenceError, RuntimeError):
            continue
        candidates.append((f"callback.__closure__[{index}]", value))
    # functools.partial is detected structurally to keep the hot path lean.
    try:
        partial_args = tuple(getattr(callback, "args", ()) or ())
        partial_keywords = dict(getattr(callback, "keywords", {}) or {})
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        partial_args = ()
        partial_keywords = {}
    candidates.extend(
        (f"callback.args[{index}]", value)
        for index, value in enumerate(partial_args)
    )
    candidates.extend(
        (f"callback.keywords.{key}", value)
        for key, value in tuple(partial_keywords.items())
    )
    for label, value in candidates:
        found = _retained_rna_path(value, label)
        if found:
            return found
    return ""


def scheduler_callback_is_safe(name, callback):
    """Validate one payload before any facade or scheduler registry retains it."""
    if not callable(callback):
        return False
    retained_rna = scheduler_callback_rna_capture(callback)
    if not retained_rna:
        return True
    _METRICS["rna_callbacks_rejected"] += 1
    inconclusive = _RNA_CAPTURE_INCONCLUSIVE_MARKER in retained_rna
    if inconclusive:
        _METRICS["rna_scans_inconclusive"] += 1
    fbp_warn_once(
        f"scheduler.rna_capture:{normalize_task_key(name)}",
        (
            "Rejected deferred work because its payload exceeded the bounded RNA safety scan"
            if inconclusive else
            "Rejected deferred work that retained a Blender RNA wrapper"
        ),
        event="scheduler.rna_capture_inconclusive" if inconclusive else "scheduler.rna_capture",
        context={
            "task": normalize_task_key(name),
            "capture": retained_rna,
        },
    )
    return False


def _now():
    try:
        return time.monotonic()
    except (RuntimeError, TypeError, ValueError):
        return 0.0


def _perf_counter():
    try:
        return time.perf_counter()
    except (AttributeError, RuntimeError):
        return 0.0


def normalize_task_counter(value, default=0):
    """Return a non-negative integer for reload-safe scheduler bookkeeping."""
    return _coerce_nonnegative_int(value, default)


def normalize_task_interval(value):
    """Return a finite positive repeat interval, otherwise ``None``.

    ``bool`` is deliberately rejected even though it subclasses ``int``.  A
    non-finite value would otherwise keep the dispatcher polling forever or be
    passed to Blender's timer API as an invalid delay.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        interval = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return interval if math.isfinite(interval) and interval > 0.0 else None


def normalize_task_delay(value):
    """Return a finite non-negative one-shot delay, otherwise ``None``.

    Delay validation is deliberately separate from repeat-interval validation:
    zero is valid for immediate deferred work, but booleans, strings, negative
    values and non-finite numbers are rejected before they can replace an
    already scheduled payload.
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    try:
        delay = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return delay if math.isfinite(delay) and delay >= 0.0 else None


def _nonnegative_finite_delay(value, default=0.0):
    try:
        delay = float(value)
    except (TypeError, ValueError, OverflowError):
        delay = float(default or 0.0)
    if not math.isfinite(delay):
        delay = float(default or 0.0)
    return max(0.0, delay)


def _finite_due_at(value, fallback):
    try:
        due_at = float(value)
    except (TypeError, ValueError, OverflowError):
        return float(fallback)
    return due_at if math.isfinite(due_at) else float(fallback)



def _normalize_priority(priority):
    if isinstance(priority, bool):
        return PRIORITY_NORMAL
    try:
        return max(PRIORITY_CRITICAL, min(PRIORITY_IDLE, int(priority)))
    except (TypeError, ValueError, OverflowError):
        return PRIORITY_NORMAL


def _nonnegative_int(value, default=0):
    return normalize_task_counter(value, default)


def _dispatcher_registered(*, force=False):
    global _DISPATCHER_REGISTERED_HINT, _DISPATCHER_LAST_VALIDATED
    now = _now()
    if (
        not force
        and _DISPATCHER_REGISTERED_HINT
        and now - _DISPATCHER_LAST_VALIDATED <= _REGISTRY_VALIDATE_SECONDS
    ):
        return True
    _METRICS["registry_checks"] += 1
    try:
        registered = bool(bpy.app.timers.is_registered(_dispatch))
    except FBP_DATA_ERRORS:
        registered = False
    _DISPATCHER_REGISTERED_HINT = registered
    _DISPATCHER_LAST_VALIDATED = now
    return registered


def _unregister_dispatcher():
    global _NEXT_WAKE_AT, _DISPATCHER_REGISTERED_HINT, _DISPATCHER_LAST_VALIDATED
    try:
        if bpy.app.timers.is_registered(_dispatch):
            bpy.app.timers.unregister(_dispatch)
    except FBP_DATA_IO_ERRORS:
        pass
    _NEXT_WAKE_AT = 0.0
    _DISPATCHER_REGISTERED_HINT = False
    _DISPATCHER_LAST_VALIDATED = _now()


def _set_dispatcher_registration_state(registered, wake_at=0.0):
    """Update the timer hint atomically after one Blender registry operation."""
    global _NEXT_WAKE_AT, _DISPATCHER_REGISTERED_HINT, _DISPATCHER_LAST_VALIDATED
    _NEXT_WAKE_AT = _coerce_nonnegative_float(wake_at) if registered else 0.0
    _DISPATCHER_REGISTERED_HINT = bool(registered)
    _DISPATCHER_LAST_VALIDATED = _now()


def _register_dispatcher_callback(delay, wake_at):
    """Register the shared callback and publish its state only on success."""
    try:
        bpy.app.timers.register(_dispatch, first_interval=delay, persistent=True)
    except FBP_DATA_IO_ERRORS:
        return False
    _set_dispatcher_registration_state(True, wake_at)
    return True


def _register_dispatcher(delay, *, restart=False):
    """Register or transactionally restart the shared Blender timer.

    Restarting is the only way to move a Blender app timer to an earlier wake.
    Keep the previous deadline before unregistering it: if Blender rejects the
    replacement, restoring the former wake prevents unrelated queued work from
    becoming permanently stranded.
    """
    delay = _nonnegative_finite_delay(delay)
    now = _now()
    target = now + delay
    registered = _dispatcher_registered()
    if registered and not restart:
        return True

    previous_wake_at = _finite_due_at(_NEXT_WAKE_AT, 0.0) if registered else 0.0
    if registered:
        _unregister_dispatcher()
        _METRICS["wake_restarts"] += 1

    if _register_dispatcher_callback(delay, target):
        return True

    # A failed restart must not take the complete scheduler down with it. The
    # old timer has already been removed, so make one best-effort restoration at
    # its former deadline. Treat that restored service as an accepted request:
    # the new task may run later than requested, but no queued mutation is lost.
    if registered:
        restore_now = _now()
        restore_delay = max(
            _MIN_WAKE_SECONDS,
            min(
                _MAX_WAKE_SECONDS,
                previous_wake_at - restore_now
                if previous_wake_at > 0.0
                else _MAX_WAKE_SECONDS,
            ),
        )
        if _register_dispatcher_callback(restore_delay, restore_now + restore_delay):
            _METRICS["wake_restores"] += 1
            fbp_warn_once(
                "scheduler.wake_restore",
                "The runtime scheduler kept its previous wake after Blender rejected an earlier restart",
                event="scheduler.wake_restore",
            )
            return True
        _METRICS["wake_restore_failures"] += 1

    _set_dispatcher_registration_state(False)
    fbp_warn("Could not register the Frame By Plane runtime scheduler")
    return False


def _drop_orphaned_tasks():
    """Remove records that cannot run because Blender owns no dispatcher."""
    if _dispatcher_registered(force=True):
        return 0
    removed = len(_TASKS)
    if removed:
        _TASKS.clear()
        _METRICS["orphaned_tasks_dropped"] += removed
        _METRICS["failed"] += removed
        fbp_warn_once(
            "scheduler.orphaned_queue",
            f"Dropped {removed} deferred task(s) after Blender rejected the scheduler timer",
            event="scheduler.orphaned_queue",
            context={"dropped": removed},
        )
    return removed


def _ensure_dispatcher(due_at):
    global _NEXT_WAKE_AT
    now = _now()
    due_at = _finite_due_at(due_at, now)
    delay = max(0.0, due_at - now)
    if _DISPATCHER_ACTIVE:
        if _NEXT_WAKE_AT <= 0.0 or due_at < _NEXT_WAKE_AT:
            _NEXT_WAKE_AT = due_at
        return True
    # Scheduling is a lifecycle boundary rather than a redraw hot path. Always
    # verify Blender's real timer registry here: another add-on reload, a failed
    # partial teardown or an external script can unregister the dispatcher while
    # our short-lived hint still says it is active, otherwise queued work can be
    # stranded indefinitely.
    hinted_registered = bool(_DISPATCHER_REGISTERED_HINT)
    registered = _dispatcher_registered(force=True)
    if hinted_registered and not registered:
        _METRICS["registry_recoveries"] += 1
    if not registered:
        return _register_dispatcher(delay)
    if _NEXT_WAKE_AT <= 0.0 or due_at + _WAKE_RESTART_EPSILON_SECONDS < _NEXT_WAKE_AT:
        return _register_dispatcher(delay, restart=True)
    return True


def schedule_task(
    name,
    callback,
    *,
    delay=0.03,
    priority=PRIORITY_NORMAL,
    category="runtime",
    persistent=False,
    restart=False,
    allow_during_undo=False,
    allow_during_render=False,
):
    """Schedule or replace one coalesced task.

    The newest callback wins for a repeated key.  Unless ``restart`` is true,
    coalescing never postpones an earlier wake-up, which keeps slider feedback
    responsive while still collapsing intermediate samples.
    """
    global _SEQUENCE
    if not callable(callback):
        return False
    if not _ACCEPTING_TASKS:
        _METRICS["teardown_rejections"] += 1
        return False
    if not scheduler_callback_is_safe(name, callback):
        return False
    key = normalize_task_key(name)
    if not key:
        key = normalize_task_key(getattr(callback, "__name__", "fbp.runtime.task"))
    if not key:
        return False
    normalized_delay = normalize_task_delay(delay)
    if normalized_delay is None:
        _METRICS["rejected_delays"] += 1
        return False
    now = _now()
    due_at = now + normalized_delay
    existing = _TASKS.get(key)
    if existing is not None and not isinstance(existing, dict):
        _TASKS.pop(key, None)
        _METRICS["invalid_records_dropped"] += 1
        _METRICS["failed"] += 1
        existing = None
    if existing is not None:
        previous_generation = _nonnegative_int(existing.get("generation", 0))
        reentrant_replacement = bool(
            _DISPATCHER_ACTIVE
            and key == _ACTIVE_TASK_KEY
            and previous_generation == _ACTIVE_TASK_GENERATION
        )
        existing["callback"] = callback
        existing["generation"] = previous_generation + 1
        existing["priority"] = min(
            _normalize_priority(priority),
            _normalize_priority(existing.get("priority", PRIORITY_NORMAL)),
        )
        existing["category"] = normalize_task_category(
            category,
            existing.get("category", "runtime"),
        )
        # The newest payload owns execution permissions.  Keeping these flags
        # sticky after a coalesced request could make a later one-shot task
        # survive file loads or run during Undo/Render only because an older
        # request used broader permissions.
        existing["persistent"] = bool(persistent)
        existing["allow_undo"] = bool(allow_during_undo)
        existing["allow_render"] = bool(allow_during_render)
        previous_due_at = _finite_due_at(existing.get("due_at", due_at), due_at)
        # The active generation has already consumed its deadline. A callback
        # that schedules a successor for the same key must start from the new
        # requested delay; only later requests for that successor may coalesce
        # without postponing its earliest wake-up.
        existing["due_at"] = (
            due_at
            if restart or reentrant_replacement
            else min(previous_due_at, due_at)
        )
        existing["epoch"] = _SCHEDULER_EPOCH
        _METRICS["coalesced"] += 1
        if not _ensure_dispatcher(_finite_due_at(existing.get("due_at"), due_at)):
            # Never leave older queue entries reporting as pending without an
            # actual Blender timer capable of consuming them.
            _drop_orphaned_tasks()
            return False
        # Coalescing is an accepted service state.  Returning False here made
        # direct callers unable to distinguish a healthy replacement from a real
        # timer-registration failure and encouraged duplicate fallback work.
        return True

    _SEQUENCE += 1
    _TASKS[key] = {
        "key": key,
        "callback": callback,
        "due_at": due_at,
        "priority": _normalize_priority(priority),
        "category": normalize_task_category(category, "runtime"),
        "persistent": bool(persistent),
        "allow_undo": bool(allow_during_undo),
        "allow_render": bool(allow_during_render),
        "epoch": _SCHEDULER_EPOCH,
        "generation": 1,
        "sequence": _SEQUENCE,
        "runs": 0,
    }
    _METRICS["scheduled"] += 1
    _METRICS["max_queue"] = max(
        _nonnegative_int(_METRICS.get("max_queue", 0)),
        len(_TASKS),
    )
    if not _ensure_dispatcher(due_at):
        _drop_orphaned_tasks()
        return False
    return True


def cancel_task(name):
    key = normalize_task_key(name)
    if not key or _TASKS.pop(key, None) is None:
        return False
    _METRICS["cancelled"] += 1
    if not _TASKS and not _DISPATCHER_ACTIVE:
        _unregister_dispatcher()
    return True


def cancel_task_prefixes(*prefixes, category=""):
    _prune_invalid_task_records()
    normalized = tuple(
        value for value in (normalize_task_key(prefix) for prefix in prefixes) if value
    )
    wanted_category = normalize_task_category(category)
    keys = tuple(
        key for key, record in _TASKS.items()
        if (not normalized or key.startswith(normalized))
        and (not wanted_category or normalize_task_category(record.get("category", "")) == wanted_category)
    )
    for key in keys:
        _TASKS.pop(key, None)
    if keys:
        _METRICS["cancelled"] += len(keys)
    if not _TASKS and not _DISPATCHER_ACTIVE:
        _unregister_dispatcher()
    return len(keys)


def clear_tasks(*, category=""):
    _prune_invalid_task_records()
    wanted_category = normalize_task_category(category)
    if wanted_category:
        keys = tuple(
            key for key, record in _TASKS.items()
            if normalize_task_category(record.get("category", "")) == wanted_category
        )
        for key in keys:
            _TASKS.pop(key, None)
        removed = len(keys)
    else:
        removed = len(_TASKS)
        _TASKS.clear()
    if removed:
        _METRICS["cancelled"] += removed
    if not _TASKS and not _DISPATCHER_ACTIVE:
        _unregister_dispatcher()
    return removed


def _advance_scheduler_epoch(*, cleanup_stale):
    """Advance the lifecycle epoch with optional idle-context cleanup.

    ``undo_pre`` and ``load_pre`` run while Blender may still be replacing Main
    or while viewport workers hold Image/Material resources.  Those callbacks
    must invalidate captured work without touching Blender timer ownership.  The
    ordinary idle path can request eager cleanup and retire an empty dispatcher.
    """
    global _SCHEDULER_EPOCH
    _SCHEDULER_EPOCH += 1
    removed = 0
    for key, record in tuple(_TASKS.items()):
        if not isinstance(record, dict):
            _TASKS.pop(key, None)
            _METRICS["invalid_records_dropped"] += 1
            _METRICS["failed"] += 1
            continue
        try:
            persistent = bool(record.get("persistent", False))
        except FBP_DATA_ERRORS:
            persistent = False
        if persistent:
            record["epoch"] = _SCHEDULER_EPOCH
            continue
        if cleanup_stale:
            _TASKS.pop(key, None)
            removed += 1
    if removed:
        _METRICS["cancelled"] += removed
    if cleanup_stale and not _TASKS and not _DISPATCHER_ACTIVE:
        _unregister_dispatcher()
    return _SCHEDULER_EPOCH


def invalidate_scheduler_epoch():
    """Invalidate pre-history work without calling Blender's timer API.

    Stale non-persistent records remain inert until the already-owned dispatcher
    returns from Blender's event loop.  Persistent watchdogs are moved to the new
    epoch so they can safely finalize Undo/Redo or file-load recovery.
    """
    epoch = _advance_scheduler_epoch(cleanup_stale=False)
    _METRICS["history_invalidations"] += 1
    return epoch


def bump_scheduler_epoch():
    """Invalidate and eagerly remove stale work from a safe idle context."""
    return _advance_scheduler_epoch(cleanup_stale=True)


def task_is_scheduled(name):
    _prune_invalid_task_records()
    return normalize_task_key(name) in _TASKS


def task_callback(name):
    _prune_invalid_task_records()
    record = _TASKS.get(normalize_task_key(name))
    return record.get("callback") if record is not None else None


def task_keys(*, category=""):
    _prune_invalid_task_records()
    wanted_category = normalize_task_category(category)
    return tuple(
        key for key, record in _TASKS.items()
        if not wanted_category or normalize_task_category(record.get("category", "")) == wanted_category
    )


def task_count(*, category=""):
    return len(task_keys(category=category))


def scheduler_dispatcher_callback():
    return _dispatch


def scheduler_snapshot(*, exact=True):
    _prune_invalid_task_records()
    now = _now()
    return {
        "epoch": _SCHEDULER_EPOCH,
        "accepting_tasks": bool(_ACCEPTING_TASKS),
        "dispatcher_registered": _dispatcher_registered(force=bool(exact)),
        "pending": len(_TASKS),
        "tasks": tuple(
            {
                "key": key,
                "category": normalize_task_category(record.get("category", "")),
                "priority": _normalize_priority(record.get("priority", PRIORITY_NORMAL)),
                "due_in_ms": round(
                    max(0.0, _finite_due_at(record.get("due_at", now), now) - now)
                    * 1000.0,
                    3,
                ),
                "persistent": bool(record.get("persistent", False)),
                "runs": _nonnegative_int(record.get("runs", 0)),
            }
            for key, record in sorted(
                _TASKS.items(),
                key=lambda item: (
                    _normalize_priority(item[1].get("priority", PRIORITY_NORMAL)),
                    _finite_due_at(item[1].get("due_at", now), now),
                    _nonnegative_int(item[1].get("sequence", 0)),
                ),
            )
        ),
    }


def scheduler_metrics(*, reset=False):
    _prune_invalid_task_records()
    result = dict(_METRICS)
    result["pending"] = len(_TASKS)
    result["epoch"] = _SCHEDULER_EPOCH
    result["accepting_tasks"] = bool(_ACCEPTING_TASKS)
    result["dispatcher_registered"] = _dispatcher_registered()
    if reset:
        _METRICS.clear()
        _METRICS.update(_METRIC_DEFAULTS)
    return result


def _task_guard_delay(record):
    # Extension update/reload replaces RNA classes and properties in-place.
    # Keep every deferred callback dormant until the new generation has fully
    # registered, and while unregister is dismantling the former generation.
    if fbp_registration_busy():
        return 0.20
    if not fbp_main_data_ready("scenes"):
        return 0.10
    now = _now()
    try:
        modal_depth = max(0, int(fbp_runtime_get("fbp_ui_modal_mutation_depth", 0) or 0))
        modal_deadline = float(fbp_runtime_get("fbp_ui_modal_mutation_deadline", 0.0) or 0.0)
    except (TypeError, ValueError, OverflowError):
        modal_depth = 0
        modal_deadline = 0.0
    if modal_depth > 0:
        if modal_deadline <= 0.0 or now <= modal_deadline:
            return 0.10
        # Fail-safe for a modal operator lost during workspace/window teardown.
        fbp_runtime_set("fbp_ui_modal_mutation_depth", 0)
        fbp_runtime_set("fbp_ui_modal_mutation_deadline", 0.0)
    if bool(fbp_runtime_get("fbp_pause_managed_timers", False)):
        return 0.25
    try:
        resume_after = float(fbp_runtime_get("fbp_managed_timers_resume_after", 0.0) or 0.0)
    except (TypeError, ValueError, OverflowError):
        resume_after = 0.0
    if resume_after > now:
        return max(0.05, min(0.5, resume_after - now))
    if fbp_undo_guard_active() and not bool(record.get("allow_undo", False)):
        return 0.10
    if fbp_render_mutation_blocked() and not bool(record.get("allow_render", False)):
        return 0.25
    return 0.0


def _next_interval(now):
    if not _ACCEPTING_TASKS:
        return None
    _prune_invalid_task_records()
    if not _TASKS:
        return None
    waits = []
    for record in _TASKS.values():
        guard_delay = _task_guard_delay(record)
        if guard_delay > 0.0:
            waits.append(guard_delay)
            continue
        waits.append(
            max(
                _MIN_WAKE_SECONDS,
                _finite_due_at(record.get("due_at", now), now) - now,
            )
        )
    if not waits:
        return None
    return max(_MIN_WAKE_SECONDS, min(_MAX_WAKE_SECONDS, min(waits)))


def _dispatch():
    global _DISPATCHER_ACTIVE, _ACTIVE_TASK_KEY, _ACTIVE_TASK_GENERATION
    global _NEXT_WAKE_AT, _DISPATCHER_REGISTERED_HINT, _DISPATCHER_LAST_VALIDATED
    if not _ACCEPTING_TASKS:
        removed = len(_TASKS)
        _TASKS.clear()
        if removed:
            _METRICS["cancelled"] += removed
        _NEXT_WAKE_AT = 0.0
        _DISPATCHER_REGISTERED_HINT = False
        _DISPATCHER_LAST_VALIDATED = _now()
        return None
    _prune_invalid_task_records()
    _DISPATCHER_ACTIVE = True
    _DISPATCHER_REGISTERED_HINT = True
    _DISPATCHER_LAST_VALIDATED = _now()
    _NEXT_WAKE_AT = 0.0
    _METRICS["dispatches"] += 1
    started = _perf_counter()
    executed = 0
    try:
        now = _now()
        due = []
        for key, record in tuple(_TASKS.items()):
            if (
                not bool(record.get("persistent", False))
                and _coerce_int(record.get("epoch", -1), -1) != _SCHEDULER_EPOCH
            ):
                _TASKS.pop(key, None)
                _METRICS["cancelled"] += 1
                continue
            record_due_at = _finite_due_at(record.get("due_at", now), now)
            if record_due_at > now:
                continue
            if _task_guard_delay(record) > 0.0:
                continue
            due.append((
                _normalize_priority(record.get("priority", PRIORITY_NORMAL)),
                record_due_at,
                _nonnegative_int(record.get("sequence", 0)),
                key,
                record,
            ))
        due.sort(key=lambda item: item[:3])

        for _priority, _due_at, _sequence, key, record in due:
            if executed >= _DISPATCH_TASK_LIMIT:
                _METRICS["budget_yields"] += 1
                break
            if started and _perf_counter() - started >= _DISPATCH_TIME_BUDGET_SECONDS:
                _METRICS["budget_yields"] += 1
                break
            current = _TASKS.get(key)
            if current is not record:
                continue
            generation = _nonnegative_int(record.get("generation", 0))
            callback = record.get("callback")
            if not callable(callback):
                _TASKS.pop(key, None)
                continue
            # A callback can be safe when queued and later acquire an RNA value
            # through a mutable closure/default container. Revalidate immediately
            # before execution so a deleted Object/Scene/PropertyGroup wrapper
            # never reaches Python from Blender's timer callback.
            if not scheduler_callback_is_safe(key, callback):
                _TASKS.pop(key, None)
                _METRICS["rna_callbacks_dropped_at_dispatch"] += 1
                _METRICS["cancelled"] += 1
                continue
            task_started = _perf_counter()
            _ACTIVE_TASK_KEY = key
            _ACTIVE_TASK_GENERATION = generation
            try:
                try:
                    result = callback()
                except ReferenceError as exc:
                    _METRICS["reference_errors"] += 1
                    fbp_warn_once(
                        f"scheduler.reference_error:{key}",
                        f"Deferred task '{key}' lost its Blender data target and was cancelled",
                        event="scheduler.reference_error",
                        context={"task": key, "error": str(exc)},
                    )
                    result = None
                except Exception as exc:
                    _METRICS["failed"] += 1
                    fbp_error(
                        f"Scheduled runtime task '{key}' failed",
                        exc,
                        event="scheduler.task",
                        context={
                            "task": key,
                            "category": normalize_task_category(record.get("category", "")),
                            "priority": _normalize_priority(record.get("priority", PRIORITY_NORMAL)),
                        },
                    )
                    result = None
            finally:
                if _ACTIVE_TASK_KEY == key and _ACTIVE_TASK_GENERATION == generation:
                    _ACTIVE_TASK_KEY = ""
                    _ACTIVE_TASK_GENERATION = 0
            task_duration_ms = (
                max(0.0, (_perf_counter() - task_started) * 1000.0)
                if task_started else 0.0
            )
            if task_duration_ms > _coerce_nonnegative_float(
                _METRICS.get("max_task_duration_ms", 0.0)
            ):
                _METRICS["max_task_duration_ms"] = task_duration_ms
                _METRICS["slowest_task"] = key
            if task_duration_ms >= 25.0:
                _METRICS["slow_tasks"] += 1
                fbp_warn_once(
                    f"scheduler.slow_task:{key}",
                    f"Deferred task '{key}' took {task_duration_ms:.1f} ms",
                    event="scheduler.slow_task",
                    context={"task": key, "duration_ms": round(task_duration_ms, 3)},
                )
            executed += 1
            _METRICS["executed"] += 1
            current = _TASKS.get(key)
            if (
                current is not record
                or _nonnegative_int(current.get("generation", 0)) != generation
            ):
                continue
            current["runs"] = _nonnegative_int(current.get("runs", 0)) + 1
            repeat_interval = normalize_task_interval(result)
            if repeat_interval is not None:
                current["due_at"] = _now() + repeat_interval
                _METRICS["rescheduled"] += 1
            else:
                _TASKS.pop(key, None)
    finally:
        duration_ms = max(0.0, (_perf_counter() - started) * 1000.0) if started else 0.0
        _METRICS["last_duration_ms"] = round(duration_ms, 4)
        _METRICS["max_duration_ms"] = max(
            _coerce_nonnegative_float(_METRICS.get("max_duration_ms", 0.0)),
            duration_ms,
        )
        _METRICS["last_executed"] = executed
        _ACTIVE_TASK_KEY = ""
        _ACTIVE_TASK_GENERATION = 0
        _DISPATCHER_ACTIVE = False

    interval = _next_interval(_now())
    if interval is None:
        _METRICS["idle_stops"] += 1
        _NEXT_WAKE_AT = 0.0
        _DISPATCHER_REGISTERED_HINT = False
        _DISPATCHER_LAST_VALIDATED = _now()
        return None
    _NEXT_WAKE_AT = _now() + interval
    _DISPATCHER_REGISTERED_HINT = True
    _DISPATCHER_LAST_VALIDATED = _now()
    return interval


def _retire_previous_dispatcher():
    previous = _PREVIOUS_DISPATCHER_CALLBACK
    if previous is None or previous is _dispatch:
        return False
    try:
        if bpy.app.timers.is_registered(previous):
            bpy.app.timers.unregister(previous)
            return True
    except FBP_DATA_IO_ERRORS:
        return False
    return False


def quiesce_scheduler():
    """Stop accepting work before Blender RNA classes/properties are removed."""
    global _ACCEPTING_TASKS
    _ACCEPTING_TASKS = False
    bump_scheduler_epoch()
    clear_tasks()
    if not _DISPATCHER_ACTIVE:
        _unregister_dispatcher()
    return True


def register():
    global _ACCEPTING_TASKS
    _ACCEPTING_TASKS = False
    _retire_previous_dispatcher()
    bump_scheduler_epoch()
    clear_tasks()
    _ACCEPTING_TASKS = True
    register_service("scheduler.snapshot", scheduler_snapshot, owner=__name__)
    register_service("scheduler.metrics", scheduler_metrics, owner=__name__)


def unregister():
    unregister_service("scheduler.snapshot")
    unregister_service("scheduler.metrics")
    quiesce_scheduler()


__all__ = (
    "PRIORITY_CRITICAL",
    "PRIORITY_IDLE",
    "PRIORITY_INTERACTIVE",
    "PRIORITY_MAINTENANCE",
    "PRIORITY_NORMAL",
    "bump_scheduler_epoch",
    "invalidate_scheduler_epoch",
    "normalize_task_counter",
    "normalize_task_delay",
    "normalize_task_interval",
    "quiesce_scheduler",
    "scheduler_accepting_tasks",
    "scheduler_callback_rna_capture",
    "scheduler_callback_is_safe",
    "cancel_task",
    "cancel_task_prefixes",
    "clear_tasks",
    "register",
    "schedule_task",
    "scheduler_dispatcher_callback",
    "scheduler_metrics",
    "scheduler_snapshot",
    "task_callback",
    "task_count",
    "task_is_scheduled",
    "task_keys",
    "unregister",
)
