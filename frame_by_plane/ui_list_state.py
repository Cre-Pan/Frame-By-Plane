"""Transient identity and selection state for Frame By Plane UI lists.

Blender UIList active rows are integer indices, but indices become stale after
filtering, reordering or a structural rebuild.  The state in this module is UI
session data, not project data, so it deliberately lives outside Blender
IDProperties.  Keeping only primitive owner tokens prevents redraws and deferred
callbacks from retaining RNA wrappers that may be invalidated by Undo, file
loads, object deletion or extension reloads.
"""

from __future__ import annotations

from collections import OrderedDict
from functools import wraps
import time
import uuid

from .shortcut_runtime import primary_modifier_pressed

_UI_STATE_ERRORS = (
    AttributeError,
    KeyError,
    ReferenceError,
    RuntimeError,
    TypeError,
    ValueError,
)
_TRANSIENT_MAX_ENTRIES = 1024
_TRANSIENT_STATE: "OrderedDict[tuple[tuple[object, ...], str], object]" = OrderedDict()

# UIList rows are backed by Blender RNA collections. A deferred rebuild that
# clears/repopulates one of those collections immediately after draw_item() can
# leave Blender's current notifier pass holding wrappers for rows that no longer
# exist. Keep only primitive monotonic timestamps and delay structural mutations
# for a fraction of one event-loop turn. This is intentionally process-local and
# never touches project data.
_UI_LIST_LAST_DRAW_AT = 0.0
_UI_LIST_DRAW_MARKS = 0
_UI_LIST_MUTATION_DEFERRALS = 0
_UI_LIST_MUTATION_GRACE_SECONDS = 0.035
_UI_LIST_MUTATION_MAX_DELAY_SECONDS = 0.050
_UI_LIST_RUNTIME_ERRORS = 0
_UI_LIST_FILTER_REPAIRS = 0


def new_row_id() -> str:
    return uuid.uuid4().hex




def _monotonic() -> float:
    try:
        return float(time.monotonic())
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return 0.0


def mark_ui_list_draw() -> float:
    """Record one UIList draw without retaining context, data or row wrappers."""
    global _UI_LIST_LAST_DRAW_AT, _UI_LIST_DRAW_MARKS
    _UI_LIST_LAST_DRAW_AT = _monotonic()
    _UI_LIST_DRAW_MARKS += 1
    return _UI_LIST_LAST_DRAW_AT


def ui_list_mutation_delay(
    *,
    grace: float = _UI_LIST_MUTATION_GRACE_SECONDS,
    max_delay: float = _UI_LIST_MUTATION_MAX_DELAY_SECONDS,
) -> float:
    """Return a short retry interval while a recent UIList draw may be in flight."""
    global _UI_LIST_MUTATION_DEFERRALS
    now = _monotonic()
    if now <= 0.0 or _UI_LIST_LAST_DRAW_AT <= 0.0:
        return 0.0
    try:
        grace_value = max(0.0, float(grace))
        max_value = max(0.0, float(max_delay))
    except (TypeError, ValueError, OverflowError):
        return 0.0
    remaining = grace_value - max(0.0, now - _UI_LIST_LAST_DRAW_AT)
    if remaining <= 0.0:
        return 0.0
    _UI_LIST_MUTATION_DEFERRALS += 1
    return min(max_value, max(0.001, remaining))


def reset_ui_list_draw_guard() -> None:
    global _UI_LIST_LAST_DRAW_AT, _UI_LIST_DRAW_MARKS, _UI_LIST_MUTATION_DEFERRALS
    global _UI_LIST_RUNTIME_ERRORS, _UI_LIST_FILTER_REPAIRS
    _UI_LIST_LAST_DRAW_AT = 0.0
    _UI_LIST_DRAW_MARKS = 0
    _UI_LIST_MUTATION_DEFERRALS = 0
    _UI_LIST_RUNTIME_ERRORS = 0
    _UI_LIST_FILTER_REPAIRS = 0


def invoke_with_selection_modifiers(operator, context, event):
    """Capture Shift/Ctrl once for row-selection operators, then execute."""
    operator.use_shift = bool(getattr(event, "shift", False))
    operator.use_ctrl = primary_modifier_pressed(event)
    return operator.execute(context)


def _safe_pointer(value) -> int:
    if value is None:
        return 0
    try:
        pointer = int(value.as_pointer())
    except _UI_STATE_ERRORS:
        pointer = 0
    return max(0, pointer)


def _safe_runtime_identity(value):
    """Prefer Blender session_uid so deleted pointer addresses cannot collide."""
    if value is None:
        return 0
    try:
        session_uid = int(getattr(value, "session_uid", 0) or 0)
        if session_uid > 0:
            return -session_uid
    except _UI_STATE_ERRORS:
        pass
    return _safe_pointer(value)


def _owner_token(owner) -> tuple[object, ...] | None:
    """Return a primitive token without keeping the Blender wrapper alive."""
    if owner is None:
        return None
    try:
        identifier = str(getattr(getattr(owner, "bl_rna", None), "identifier", "") or "")
    except _UI_STATE_ERRORS:
        identifier = type(owner).__name__
    owner_identity = _safe_runtime_identity(owner)
    try:
        id_data = getattr(owner, "id_data", None)
    except _UI_STATE_ERRORS:
        id_data = None
    id_identity = _safe_runtime_identity(id_data)
    try:
        path = str(owner.path_from_id() or "") if id_data is not None and owner is not id_data else ""
    except _UI_STATE_ERRORS:
        path = ""
    if id_data is not None and owner is not id_data and id_identity:
        # PropertyGroup wrappers can be rebuilt while their path and owning ID
        # remain stable. Excluding their temporary pointer keeps selection state
        # stable without risking pointer reuse across deleted collection rows.
        return (identifier, id_identity, path)
    if not owner_identity and not id_identity:
        # Pure Python test doubles have no RNA identity. id() is process-local
        # and sufficient for transient state without storing the object itself.
        owner_identity = id(owner)
    return (identifier, id_identity or owner_identity, path)


def _state_key(owner, key: str):
    token = _owner_token(owner)
    name = str(key or "")
    if token is None or not name:
        return None
    return token, name


def _trim_transient_state() -> None:
    while len(_TRANSIENT_STATE) > _TRANSIENT_MAX_ENTRIES:
        _TRANSIENT_STATE.popitem(last=False)


def transient_get(owner, key: str, default=None):
    state_key = _state_key(owner, key)
    if state_key is None:
        return default
    try:
        value = _TRANSIENT_STATE[state_key]
    except KeyError:
        return default
    _TRANSIENT_STATE.move_to_end(state_key)
    return value


def transient_set(owner, key: str, value) -> bool:
    state_key = _state_key(owner, key)
    if state_key is None:
        return False
    _TRANSIENT_STATE[state_key] = value
    _TRANSIENT_STATE.move_to_end(state_key)
    _trim_transient_state()
    return True


def transient_pop(owner, key: str) -> bool:
    state_key = _state_key(owner, key)
    if state_key is None:
        return False
    missing = object()
    return _TRANSIENT_STATE.pop(state_key, missing) is not missing


def clear_transient_owner(owner) -> int:
    token = _owner_token(owner)
    if token is None:
        return 0
    keys = tuple(key for key in _TRANSIENT_STATE if key[0] == token)
    for key in keys:
        _TRANSIENT_STATE.pop(key, None)
    return len(keys)


def clear_transient_state() -> int:
    count = len(_TRANSIENT_STATE)
    _TRANSIENT_STATE.clear()
    return count


def transient_state_snapshot() -> dict[str, int | float]:
    return {
        "entries": len(_TRANSIENT_STATE),
        "limit": _TRANSIENT_MAX_ENTRIES,
        "draw_marks": int(_UI_LIST_DRAW_MARKS),
        "mutation_deferrals": int(_UI_LIST_MUTATION_DEFERRALS),
        "last_draw_at": float(_UI_LIST_LAST_DRAW_AT),
        "runtime_errors": int(_UI_LIST_RUNTIME_ERRORS),
        "filter_repairs": int(_UI_LIST_FILTER_REPAIRS),
    }


def item_identity(item, attr: str) -> str:
    try:
        return str(getattr(item, attr, "") or "")
    except _UI_STATE_ERRORS:
        return ""


def ensure_item_identity(item, attr: str, factory=new_row_id) -> str:
    value = item_identity(item, attr)
    if value:
        return value
    value = str(factory())
    try:
        setattr(item, attr, value)
    except _UI_STATE_ERRORS:
        return ""
    return value


def ensure_unique_item_identities(items, attr: str, factory=new_row_id) -> int:
    """Assign missing/duplicate identities in-place and return change count."""
    seen: set[str] = set()
    changed = 0
    for item in items or ():
        value = item_identity(item, attr)
        if not value or value in seen:
            value = str(factory())
            try:
                setattr(item, attr, value)
            except _UI_STATE_ERRORS:
                continue
            changed += 1
        seen.add(value)
    return changed


def index_for_identity(items, attr: str, identity: str, default: int = -1) -> int:
    identity = str(identity or "")
    if not identity:
        return int(default)
    for index, item in enumerate(items or ()):
        if item_identity(item, attr) == identity:
            return index
    return int(default)


def clamp_index(index: int, count: int, empty: int = 0) -> int:
    try:
        count = max(0, int(count))
    except (*_UI_STATE_ERRORS, OverflowError):
        count = 0
    if count == 0:
        try:
            return int(empty)
        except (*_UI_STATE_ERRORS, OverflowError):
            return 0
    try:
        index = int(index)
    except (*_UI_STATE_ERRORS, OverflowError):
        index = 0
    return max(0, min(index, count - 1))


def identity_at(items, attr: str, index: int) -> str:
    try:
        if 0 <= int(index) < len(items):
            return item_identity(items[int(index)], attr)
    except _UI_STATE_ERRORS:
        pass
    return ""


def resolve_anchor_index(
    owner,
    index_key: str,
    identity_key: str,
    items,
    identity_attr: str,
    fallback: int = 0,
) -> int:
    """Resolve a UI range anchor by identity, falling back to a clamped index."""
    count = len(items or ())
    if count == 0:
        return 0
    identity = str(transient_get(owner, identity_key, "") or "")
    found = index_for_identity(items, identity_attr, identity, default=-1)
    if found >= 0:
        return found
    raw_index = transient_get(owner, index_key, fallback)
    return clamp_index(raw_index, count)


def store_anchor(
    owner,
    index_key: str,
    identity_key: str,
    items,
    identity_attr: str,
    index: int,
) -> int:
    index = clamp_index(index, len(items or ()))
    transient_set(owner, index_key, index)
    identity = identity_at(items, identity_attr, index)
    if identity:
        transient_set(owner, identity_key, identity)
    else:
        transient_pop(owner, identity_key)
    return index


def clear_anchor(owner, index_key: str, identity_key: str) -> None:
    transient_pop(owner, index_key)
    transient_pop(owner, identity_key)


def restore_active_index(items, identity_attr: str, identity: str, fallback: int = 0) -> int:
    found = index_for_identity(items, identity_attr, identity, default=-1)
    if found >= 0:
        return found
    return clamp_index(fallback, len(items or ()))




def _safe_ui_list_count(data, propname: str) -> int:
    """Return the current RNA collection length without retaining its wrapper."""
    try:
        items = getattr(data, str(propname or ""), ())
        return max(0, int(len(items)))
    except _UI_STATE_ERRORS:
        return 0


def _safe_ui_list_fallback_flags(instance, count: int):
    try:
        visible_flag = int(getattr(instance, "bitflag_filter_item", 0))
    except (*_UI_STATE_ERRORS, OverflowError):
        visible_flag = 0
    try:
        safe_count = max(0, int(count))
    except (*_UI_STATE_ERRORS, OverflowError):
        safe_count = 0
    return [visible_flag] * safe_count


def _normalize_ui_list_filter_result(instance, data, propname, result):
    """Repair malformed filter output before Blender consumes it.

    A wrong flag/new-order length can make Blender read beyond Python-owned
    arrays. Treat invalid output as an unfiltered list rather than allowing one
    broken add-on row to destabilize the complete editor.
    """
    global _UI_LIST_FILTER_REPAIRS
    count = _safe_ui_list_count(data, propname)
    try:
        flags, new_order = result
        flags = list(flags or ())
        new_order = list(new_order or ())
    except (*_UI_STATE_ERRORS, OverflowError):
        _UI_LIST_FILTER_REPAIRS += 1
        return _safe_ui_list_fallback_flags(instance, count), []

    repaired = False
    if len(flags) != count:
        fallback = _safe_ui_list_fallback_flags(instance, count)
        flags = (flags[:count] + fallback[len(flags):]) if count else []
        repaired = True

    # Blender consumes these values as C integers. Coerce every element before
    # returning so a stray None/string/custom numeric object cannot cross the
    # Python/RNA boundary during redraw. Invalid flags fall back to visible.
    fallback_flag = _safe_ui_list_fallback_flags(instance, 1)[0] if count else 0
    normalized_flags = []
    for value in flags:
        try:
            normalized_flags.append(int(value))
        except (*_UI_STATE_ERRORS, OverflowError):
            normalized_flags.append(fallback_flag)
            repaired = True
    flags = normalized_flags

    if new_order:
        try:
            normalized = [int(value) for value in new_order]
            if len(normalized) != count or sorted(normalized) != list(range(count)):
                normalized = []
                repaired = True
            new_order = normalized
        except (*_UI_STATE_ERRORS, OverflowError):
            new_order = []
            repaired = True

    if repaired:
        _UI_LIST_FILTER_REPAIRS += 1
    return flags, new_order


def harden_ui_list_class(cls):
    """Wrap one UIList class with fail-closed draw and filter boundaries.

    The wrapper is installed before RNA registration and is idempotent across
    extension reloads. It deliberately keeps no context/data/item references
    after the callback returns.
    """
    if cls is None or bool(getattr(cls, "__dict__", {}).get("_fbp_ui_list_hardened", False)):
        return cls

    draw_item = getattr(cls, "draw_item", None)
    if callable(draw_item):
        @wraps(draw_item)
        def guarded_draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
            global _UI_LIST_RUNTIME_ERRORS
            mark_ui_list_draw()
            try:
                return draw_item(self, context, layout, data, item, icon, active_data, active_propname, index)
            except Exception:
                _UI_LIST_RUNTIME_ERRORS += 1
                try:
                    layout.label(text="Unavailable", icon="ERROR")
                except Exception:
                    pass
                return None
        setattr(cls, "draw_item", guarded_draw_item)

    draw_filter = getattr(cls, "draw_filter", None)
    if callable(draw_filter):
        @wraps(draw_filter)
        def guarded_draw_filter(self, context, layout):
            global _UI_LIST_RUNTIME_ERRORS
            mark_ui_list_draw()
            try:
                return draw_filter(self, context, layout)
            except Exception:
                _UI_LIST_RUNTIME_ERRORS += 1
                # A broken search/sort header must not suppress the complete
                # list or abort the containing panel. The row callbacks remain
                # available and Blender can redraw normally on the next event.
                return None
        setattr(cls, "draw_filter", guarded_draw_filter)

    filter_items = getattr(cls, "filter_items", None)
    if callable(filter_items):
        @wraps(filter_items)
        def guarded_filter_items(self, context, data, propname):
            global _UI_LIST_RUNTIME_ERRORS
            mark_ui_list_draw()
            try:
                result = filter_items(self, context, data, propname)
            except Exception:
                _UI_LIST_RUNTIME_ERRORS += 1
                count = _safe_ui_list_count(data, propname)
                return _safe_ui_list_fallback_flags(self, count), []
            try:
                return _normalize_ui_list_filter_result(self, data, propname, result)
            except Exception:
                # Normalization itself must remain a hard boundary: custom
                # sequences and stale RNA wrappers can fail while being
                # iterated, converted or measured after filter_items returns.
                _UI_LIST_RUNTIME_ERRORS += 1
                count = _safe_ui_list_count(data, propname)
                return _safe_ui_list_fallback_flags(self, count), []
        setattr(cls, "filter_items", guarded_filter_items)

    try:
        setattr(cls, "_fbp_ui_list_hardened", True)
    except Exception:
        pass
    return cls


def register():
    clear_transient_state()
    reset_ui_list_draw_guard()


def unregister():
    clear_transient_state()
    reset_ui_list_draw_guard()


__all__ = (
    "clamp_index",
    "clear_anchor",
    "clear_transient_owner",
    "clear_transient_state",
    "ensure_item_identity",
    "ensure_unique_item_identities",
    "harden_ui_list_class",
    "identity_at",
    "index_for_identity",
    "invoke_with_selection_modifiers",
    "mark_ui_list_draw",
    "item_identity",
    "new_row_id",
    "resolve_anchor_index",
    "reset_ui_list_draw_guard",
    "restore_active_index",
    "store_anchor",
    "transient_get",
    "transient_pop",
    "transient_set",
    "transient_state_snapshot",
    "ui_list_mutation_delay",
)
