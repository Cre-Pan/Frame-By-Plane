"""Centralized dirty queue for Frame By Plane runtime updates.

Aggressive performance path: RNA callbacks should mark work as dirty and let a
single safe timer apply the final state once per UI tick. This keeps slider
drags, multi-edit property mirroring and viewport helper sync from causing a
full material/modifier update for every intermediate value.
"""

from __future__ import annotations

import time

import bpy

from .service_registry import register_service, unregister_service
from .safe_tasks import schedule_once

from .runtime import (
    FBP_DATA_ERRORS,
    fbp_is_silent_property_update,
    fbp_set_rna_property_silent,
    fbp_undo_guard_active,
    fbp_render_mutation_blocked,
    fbp_obj_runtime_key,
    fbp_find_id_by_runtime_key,
    fbp_selection_snapshot,
    fbp_error,
    fbp_warn_once,
    fbp_object_name as _object_name
)

# Deferred mutations belong to one registered RNA generation. The shared
# scheduler drops old callbacks on reload, so drop their payload queues too.
_DIRTY_EFFECT_SETTINGS = {}
_DIRTY_EFFECT_ANIMATION = {}
_DIRTY_GEOMETRY_CALLBACKS = {}
_DIRTY_TIMER_KEY = "fbp.dirty.flush"

_STORAGE_KEY_FN = None
_SYNC_CONTROLS_FN = None
_GET_SELECTED_RIGS_FN = None
_EFFECT_IS_ACTIVE_FN = None
_EFFECT_INSTANCE_SUPPORT_CACHE = {}
_ANIM_STORAGE_PROP_CACHE = globals().get("_ANIM_STORAGE_PROP_CACHE", {})
if not isinstance(_ANIM_STORAGE_PROP_CACHE, dict):
    _ANIM_STORAGE_PROP_CACHE = {}
_ANIM_STORAGE_PROP_CACHE_LIMIT = 1024
_TARGET_NAMES_CACHE = globals().get("_TARGET_NAMES_CACHE", {})
_TARGET_NAMES_CACHE_SECONDS = 0.08
_TARGET_NAMES_CACHE_LIMIT = 128
_DIRTY_FLUSH_PENDING = False
_DIRTY_FLUSH_PENDING_AT = 0.0
_DIRTY_FLUSH_BATCH_LIMIT = 64
_DIRTY_FLUSH_TIME_BUDGET_SECONDS = 0.004
_DIRTY_METRICS = globals().get("_DIRTY_METRICS", {})
if not isinstance(_DIRTY_METRICS, dict):
    _DIRTY_METRICS = {}
for _metric, _default in {
    "marks": 0,
    "coalesced": 0,
    "flushes": 0,
    "processed": 0,
    "deferred": 0,
    "budget_yields": 0,
    "max_pending": 0,
    "last_duration_ms": 0.0,
    "max_duration_ms": 0.0,
}.items():
    _DIRTY_METRICS.setdefault(_metric, _default)


def _prune_timed_cache(cache, *, now=0.0, max_age=0.50, limit=128):
    """Keep short-lived UI-drag caches bounded without dropping fresh entries.

    Clearing the whole cache during slider drags defeats the coalescing path and
    can reintroduce repeated multi-selection scans.  Prefer retiring only old
    items, then fall back to a half-size trim if a burst still grows too large.
    """
    if not isinstance(cache, dict) or len(cache) < limit:
        return
    try:
        cutoff = float(now) - float(max_age)
        for key, value in tuple(cache.items()):
            checked_at = float((value or (0.0,))[0] or 0.0) if isinstance(value, tuple) else 0.0
            if checked_at < cutoff:
                cache.pop(key, None)
        if len(cache) < limit:
            return
        ordered = sorted(
            cache.items(),
            key=lambda item: float((item[1] or (0.0,))[0] or 0.0) if isinstance(item[1], tuple) else 0.0,
        )
        for key, _value in ordered[: max(1, len(ordered) - (limit // 2))]:
            cache.pop(key, None)
    except Exception as exc:
        fbp_warn_once(
            "dirty_cache_prune_failed",
            "Dirty-update cache pruning failed; the cache was reset",
            exc,
            event="dirty.cache_prune",
            context={"size": len(cache), "limit": limit},
        )
        cache.clear()


def _storage_key_fn():
    global _STORAGE_KEY_FN
    if _STORAGE_KEY_FN is None:
        from .storage_keys import fbp_effect_storage_key
        _STORAGE_KEY_FN = fbp_effect_storage_key
    return _STORAGE_KEY_FN


def _sync_controls_fn():
    global _SYNC_CONTROLS_FN
    if _SYNC_CONTROLS_FN is None:
        from .effect_controls import schedule_sync_controls_from_properties
        _SYNC_CONTROLS_FN = schedule_sync_controls_from_properties
    return _SYNC_CONTROLS_FN


def _get_selected_rigs_fn():
    global _GET_SELECTED_RIGS_FN
    if _GET_SELECTED_RIGS_FN is None:
        from .layers import get_selected_rigs
        _GET_SELECTED_RIGS_FN = get_selected_rigs
    return _GET_SELECTED_RIGS_FN


def _effect_is_active_fn():
    global _EFFECT_IS_ACTIVE_FN
    if _EFFECT_IS_ACTIVE_FN is None:
        from . import geometry_nodes
        _EFFECT_IS_ACTIVE_FN = geometry_nodes.fbp_effect_is_active
    return _EFFECT_IS_ACTIVE_FN


def _effect_instance_setting_supported(effect_id):
    """Return whether *effect_id* owns editable per-instance shader channels."""
    effect_id = str(effect_id or "").upper()
    cached = _EFFECT_INSTANCE_SUPPORT_CACHE.get(effect_id)
    if cached is not None:
        return bool(cached)
    try:
        from .effects_registry import (
            fbp_effect_definition,
            fbp_effect_multi_instance_enabled,
        )
        definition = fbp_effect_definition(effect_id)
        supported = bool(
            fbp_effect_multi_instance_enabled(effect_id)
            and str(definition.get("kind", "") or "").upper() == "SHADER"
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        supported = False
    _EFFECT_INSTANCE_SUPPORT_CACHE[effect_id] = supported
    return supported


def _animation_storage_prop(effect_id, suffix):
    key = (str(effect_id or "").upper(), str(suffix or ""))
    cached = _ANIM_STORAGE_PROP_CACHE.get(key)
    if cached is not None:
        return cached
    prop = _storage_key_fn()("fbp_anim_", key[0], f"_{key[1]}")
    if len(_ANIM_STORAGE_PROP_CACHE) >= _ANIM_STORAGE_PROP_CACHE_LIMIT and key not in _ANIM_STORAGE_PROP_CACHE:
        _ANIM_STORAGE_PROP_CACHE.clear()
    _ANIM_STORAGE_PROP_CACHE[key] = prop
    return prop


def _context_selection_signature(rig, context):
    """Return a stable multi-edit cache key without repeating selection scans."""
    try:
        scene_key, _selected_active_key, selected_keys = fbp_selection_snapshot(context)
        active = getattr(context, "active_object", None) if context is not None else None
        return (
            scene_key,
            fbp_obj_runtime_key(active),
            fbp_obj_runtime_key(rig),
            selected_keys,
        )
    except FBP_DATA_ERRORS:
        return (0, 0, _object_pointer(rig), frozenset())


def _object_pointer(obj):
    try:
        return fbp_obj_runtime_key(obj)
    except FBP_DATA_ERRORS:
        return None


def _object_locator(obj):
    """Return a primitive locator safe across deferred RNA updates."""
    if obj is None:
        return (None, "")
    try:
        return (
            fbp_obj_runtime_key(obj),
            str(getattr(obj, "name_full", getattr(obj, "name", "")) or ""),
        )
    except FBP_DATA_ERRORS:
        return (None, "")


def _resolve_object_locator(locator):
    try:
        runtime_key, name = tuple(locator or (None, ""))[:2]
    except (TypeError, ValueError):
        runtime_key, name = None, str(locator or "")
    return fbp_find_id_by_runtime_key(
        getattr(bpy.data, "objects", ()), runtime_key, str(name or "")
    )


_DEFERRED_ID_MARKER = "__FBP_DEFERRED_ID_V1__"
_DEFERRED_ID_COLLECTIONS = {
    "OBJECT": "objects",
    "IMAGE": "images",
    "MATERIAL": "materials",
    "COLLECTION": "collections",
    "VECTORFONT": "fonts",
    "FONT": "fonts",
    "NODETREE": "node_groups",
    "CAMERA": "cameras",
    "LIGHT": "lights",
    "WORLD": "worlds",
    "TEXTURE": "textures",
    "MOVIECLIP": "movieclips",
    "MASK": "masks",
    "SOUND": "sounds",
}


def _deferred_id_collection_name(value):
    try:
        identifier = str(getattr(getattr(value, "bl_rna", None), "identifier", "") or "").upper()
    except FBP_DATA_ERRORS:
        identifier = ""
    if not identifier:
        try:
            identifier = type(value).__name__.upper()
        except (AttributeError, TypeError, ValueError):
            identifier = ""
    return _DEFERRED_ID_COLLECTIONS.get(identifier, "")


def _capture_deferred_value(value):
    """Capture values without retaining live Blender ID/RNA wrappers."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    collection_name = _deferred_id_collection_name(value)
    if collection_name:
        try:
            return (
                _DEFERRED_ID_MARKER,
                collection_name,
                fbp_obj_runtime_key(value),
                str(getattr(value, "name_full", getattr(value, "name", "")) or ""),
            )
        except FBP_DATA_ERRORS:
            return (_DEFERRED_ID_MARKER, collection_name, None, "")
    if isinstance(value, (tuple, list)):
        return tuple(_capture_deferred_value(item) for item in value)
    try:
        # bpy_prop_array and mathutils vectors are safe as primitive tuples.
        return tuple(value)
    except (TypeError, ValueError):
        # Unknown RNA values fail closed instead of surviving in a timer queue.
        return None


def _resolve_deferred_value(value):
    if (
        isinstance(value, tuple)
        and len(value) == 4
        and value[0] == _DEFERRED_ID_MARKER
    ):
        _marker, collection_name, runtime_key, name = value
        collection = getattr(bpy.data, str(collection_name or ""), None)
        if collection is None:
            return None
        return fbp_find_id_by_runtime_key(collection, runtime_key, str(name or ""))
    if isinstance(value, tuple):
        return tuple(_resolve_deferred_value(item) for item in value)
    return value


def _resolve_selected_targets(rig, context, effect_id):
    """Resolve multi-edit targets once, while the UI context is still valid.

    RNA sliders can emit dozens of update callbacks per second.  The selected
    layer set normally stays identical throughout that drag, so cache the
    expensive selection/effect-active resolution for one UI tick.
    """
    effect_id = str(effect_id or "").upper()
    cache_key = (_object_name(rig), effect_id, _context_selection_signature(rig, context))
    try:
        now = time.monotonic()
    except (RuntimeError, TypeError, ValueError):
        now = 0.0
    cached = _TARGET_NAMES_CACHE.get(cache_key)
    if cached is not None:
        try:
            checked_at, names = cached
            if now - float(checked_at or 0.0) <= _TARGET_NAMES_CACHE_SECONDS:
                return tuple(names)
        except (TypeError, ValueError):
            pass

    targets = [rig] if rig is not None else []
    try:
        selected = list(_get_selected_rigs_fn()(context) or []) if context is not None else []
    except FBP_DATA_ERRORS:
        selected = []
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        selected = []
    try:
        if selected and rig in selected:
            targets = selected
    except FBP_DATA_ERRORS:
        targets = [rig] if rig is not None else []

    if effect_id:
        try:
            is_active = _effect_is_active_fn()
            targets = [target for target in targets if is_active(target, effect_id)]
        except FBP_DATA_ERRORS:
            targets = []
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    result = []
    seen = set()
    for target in targets:
        locator = _object_locator(target)
        if not locator[1] or locator in seen:
            continue
        seen.add(locator)
        result.append(locator)
    names = tuple(result)
    if len(_TARGET_NAMES_CACHE) >= _TARGET_NAMES_CACHE_LIMIT and cache_key not in _TARGET_NAMES_CACHE:
        _prune_timed_cache(
            _TARGET_NAMES_CACHE,
            now=now,
            max_age=max(0.25, _TARGET_NAMES_CACHE_SECONDS * 4.0),
            limit=_TARGET_NAMES_CACHE_LIMIT,
        )
    _TARGET_NAMES_CACHE[cache_key] = (now, names)
    return names


def mark_effect_setting(
    rig, effect_id, prop_name, *, context=None, controls=True, instance_id=""
):
    """Queue an effect-property update for the next safe timer tick.

    Returns True when the dirty queue accepted the update. The caller can fall
    back to the old immediate path if this returns False.
    """
    if (
        rig is None
        or not effect_id
        or not prop_name
        or fbp_undo_guard_active()
        or fbp_is_silent_property_update(rig)
    ):
        return False
    source_name = _object_name(rig)
    if not source_name:
        return False
    effect_id = str(effect_id or "").upper()
    prop_name = str(prop_name or "")
    instance_id = str(instance_id or "")
    if instance_id and not _effect_instance_setting_supported(effect_id):
        # Persistent stack identities exist for every effect row. Only a small
        # supported subset owns per-instance shader channels; all other edits
        # must continue through the ordinary Object-property update path.
        instance_id = ""
    source_locator = _object_locator(rig)
    target_names = (
        (source_locator,)
        if instance_id
        else _resolve_selected_targets(rig, context, effect_id)
    )
    if not target_names:
        target_names = (source_locator,)
    try:
        captured_value = _capture_deferred_value(getattr(rig, prop_name))
    except FBP_DATA_ERRORS:
        captured_value = None
    key = (source_locator[0], source_name, effect_id, instance_id)
    existed = key in _DIRTY_EFFECT_SETTINGS
    entry = _DIRTY_EFFECT_SETTINGS.setdefault(
        key,
        {
            "source": source_locator,
            "source_pointer": source_locator[0],
            "effect_id": effect_id,
            "instance_id": instance_id,
            "props": set(),
            "values": {},
            "targets": set(),
            "controls": False,
        },
    )
    entry["props"].add(prop_name)
    entry["values"][prop_name] = captured_value
    entry["targets"].update(target_names)
    entry["controls"] = bool(entry.get("controls", False) or controls)
    _DIRTY_METRICS["marks"] += 1
    _DIRTY_METRICS["coalesced"] += int(existed)
    _DIRTY_METRICS["max_pending"] = max(_DIRTY_METRICS["max_pending"], _dirty_pending_count())
    scheduled = _schedule_flush()
    if not scheduled:
        _DIRTY_EFFECT_SETTINGS.pop(key, None)
    return scheduled


def mark_effect_animation_setting(rig, effect_id, suffix, *, context=None):
    """Queue effect animation/evolve setting updates through the dirty timer."""
    if (
        rig is None
        or not effect_id
        or not suffix
        or fbp_undo_guard_active()
        or fbp_is_silent_property_update(rig)
    ):
        return False
    source_name = _object_name(rig)
    if not source_name:
        return False
    effect_id = str(effect_id or "").upper()
    suffix = str(suffix or "")
    source_locator = _object_locator(rig)
    target_names = _resolve_selected_targets(rig, context, effect_id)
    if not target_names:
        target_names = (source_locator,)
    key = (source_locator[0], source_name, effect_id)
    existed = key in _DIRTY_EFFECT_ANIMATION
    entry = _DIRTY_EFFECT_ANIMATION.setdefault(
        key,
        {
            "source": source_locator,
            "source_pointer": source_locator[0],
            "effect_id": effect_id,
            "suffixes": set(),
            "targets": set(),
        },
    )
    entry["suffixes"].add(suffix)
    entry["targets"].update(target_names)
    _DIRTY_METRICS["marks"] += 1
    _DIRTY_METRICS["coalesced"] += int(existed)
    _DIRTY_METRICS["max_pending"] = max(_DIRTY_METRICS["max_pending"], _dirty_pending_count())
    scheduled = _schedule_flush()
    if not scheduled:
        _DIRTY_EFFECT_ANIMATION.pop(key, None)
    return scheduled


def mark_geometry_callback(rig, callback_name, *callback_args, context=None, effect_id="", controls=False):
    """Queue a Geometry Nodes callback by object name.

    This is intentionally coarse-grained: repeated RNA updates for the same rig
    and callback collapse into one timer pass that runs with the latest RNA
    values already stored on the object. It is used for expensive effect helper
    callbacks that do not need every intermediate slider sample.
    """
    if (
        rig is None
        or not callback_name
        or fbp_undo_guard_active()
        or fbp_is_silent_property_update(rig)
    ):
        return False
    source_name = _object_name(rig)
    if not source_name:
        return False
    effect_id = str(effect_id or "").upper()
    source_locator = _object_locator(rig)
    target_names = _resolve_selected_targets(rig, context, effect_id) if effect_id else (source_locator,)
    if not target_names:
        target_names = (source_locator,)
    callback_name = str(callback_name or "")
    callback_args = tuple(callback_args or ())
    coalesced = 0
    queued_keys = []
    for target_name in target_names:
        key = (target_name, callback_name, callback_args)
        queued_keys.append(key)
        coalesced += int(key in _DIRTY_GEOMETRY_CALLBACKS)
        _DIRTY_GEOMETRY_CALLBACKS[key] = {
            "target": target_name,
            "callback": callback_name,
            "args": callback_args,
            "controls": bool(controls),
            "effect_id": effect_id,
        }
    _DIRTY_METRICS["marks"] += max(1, len(target_names))
    _DIRTY_METRICS["coalesced"] += coalesced
    _DIRTY_METRICS["max_pending"] = max(_DIRTY_METRICS["max_pending"], _dirty_pending_count())
    scheduled = _schedule_flush()
    if not scheduled:
        for queued_key in queued_keys:
            _DIRTY_GEOMETRY_CALLBACKS.pop(queued_key, None)
    return scheduled

def _dirty_pending_count():
    return (
        len(_DIRTY_EFFECT_SETTINGS)
        + len(_DIRTY_EFFECT_ANIMATION)
        + len(_DIRTY_GEOMETRY_CALLBACKS)
    )


def dirty_queue_snapshot():
    """Return primitive-only queue and budget metrics for diagnostics."""
    result = dict(_DIRTY_METRICS)
    result.update({
        "pending": _dirty_pending_count(),
        "effect_settings": len(_DIRTY_EFFECT_SETTINGS),
        "effect_animation": len(_DIRTY_EFFECT_ANIMATION),
        "geometry_callbacks": len(_DIRTY_GEOMETRY_CALLBACKS),
        "batch_limit": _DIRTY_FLUSH_BATCH_LIMIT,
        "time_budget_ms": round(_DIRTY_FLUSH_TIME_BUDGET_SECONDS * 1000.0, 3),
        "flush_pending": bool(_DIRTY_FLUSH_PENDING),
    })
    return result


def _schedule_flush():
    global _DIRTY_FLUSH_PENDING, _DIRTY_FLUSH_PENDING_AT
    try:
        now = time.monotonic()
    except (RuntimeError, TypeError, ValueError):
        now = 0.0
    # Always touch the shared scheduler. Undo/load can invalidate the facade
    # epoch while this local flag still says a timer is active; an early return
    # here stranded the first post-Undo slider edit with no consumer.
    try:
        if not schedule_once(_DIRTY_TIMER_KEY, flush_dirty, first_interval=0.0):
            _DIRTY_FLUSH_PENDING = False
            _DIRTY_FLUSH_PENDING_AT = 0.0
            return False
        _DIRTY_FLUSH_PENDING = True
        _DIRTY_FLUSH_PENDING_AT = now
        return True
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        _DIRTY_FLUSH_PENDING = False
        _DIRTY_FLUSH_PENDING_AT = 0.0
        return False


def _sorted_props(props):
    try:
        return tuple(sorted(str(prop) for prop in props if prop))
    except (TypeError, ValueError):
        return tuple(str(prop) for prop in tuple(props or ()) if prop)


def _rna_values_equal(left, right):
    """Cheap equality guard for dirty multi-edit mirroring.

    Avoids writing Blender RNA when the selected targets already carry the final
    slider value. This prevents duplicate update callbacks during multi-layer
    drags and lowers controller sync churn.
    """
    try:
        if isinstance(left, float) or isinstance(right, float):
            return abs(float(left) - float(right)) <= 1.0e-9
        if isinstance(left, (tuple, list)) or isinstance(right, (tuple, list)):
            return tuple(left) == tuple(right)
        return left == right
    except Exception as exc:
        fbp_warn_once(
            "dirty_rna_compare_failed",
            "Could not compare two dirty-queue RNA values",
            exc,
            event="dirty.value_compare",
            context={"left_type": type(left).__name__, "right_type": type(right).__name__},
        )
        return False


def _target_objects(entry):
    source = _resolve_object_locator(entry.get("source"))
    source_value_by_prop = {
        prop: _resolve_deferred_value(value)
        for prop, value in dict(entry.get("values", {}) or {}).items()
    }
    props = _sorted_props(entry.get("props", ()))
    for prop in props:
        if prop in source_value_by_prop:
            continue
        try:
            source_value_by_prop[prop] = (
                _resolve_deferred_value(_capture_deferred_value(getattr(source, prop)))
                if source is not None else None
            )
        except FBP_DATA_ERRORS:
            source_value_by_prop[prop] = None
    result = []
    for name in tuple(entry.get("targets", ()) or ()):
        target = _resolve_object_locator(name)
        if target is None:
            continue
        result.append((target, source, source_value_by_prop))
    return result


def _pop_next_dirty_entry(mapping):
    """Pop one insertion-ordered entry without copying the complete queue."""
    if not mapping:
        return None
    try:
        key = next(iter(mapping))
    except (StopIteration, RuntimeError, TypeError):
        return None
    return mapping.pop(key, None)


def _process_effect_entry(entry, geometry_nodes):
    effect_id = str(entry.get("effect_id", "") or "").upper()
    props = _sorted_props(entry.get("props", ()))
    if not effect_id or not props:
        return
    sync_controls = bool(entry.get("controls", False))
    instance_id = str(entry.get("instance_id", "") or "")
    for target, source, source_value_by_prop in _target_objects(entry):
        for prop in props:
            if instance_id:
                try:
                    geometry_nodes.fbp_update_effect_instance_setting_value(
                        target, effect_id, instance_id, prop,
                        source_value_by_prop.get(prop),
                    )
                except FBP_DATA_ERRORS:
                    pass
                except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
                    fbp_error(
                        f"Dirty instance update failed for {effect_id}.{prop}",
                        exc,
                        event="dirty.effect_instance_update",
                        context={
                            "effect": effect_id,
                            "instance": instance_id,
                            "property": prop,
                            "target": getattr(target, "name", ""),
                        },
                    )
                continue
            if source is not None and target is not source and prop in source_value_by_prop:
                try:
                    if hasattr(target, prop):
                        desired_value = source_value_by_prop[prop]
                        if not _rna_values_equal(getattr(target, prop), desired_value):
                            fbp_set_rna_property_silent(target, prop, desired_value)
                except FBP_DATA_ERRORS:
                    pass
            try:
                geometry_nodes.update_effect_setting_cb(target, None, effect_id, prop)
            except FBP_DATA_ERRORS:
                pass
            except Exception as exc:
                fbp_error(
                    f"Dirty effect update failed for {effect_id}.{prop}",
                    exc,
                    event="dirty.effect_update",
                    context={"effect": effect_id, "property": prop, "target": getattr(target, "name", "")},
                )
        if sync_controls:
            try:
                _sync_controls_fn()(target, effect_id, create=False)
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass


def _process_animation_entry(entry, geometry_nodes, objects):
    effect_id = str(entry.get("effect_id", "") or "").upper()
    suffixes = _sorted_props(entry.get("suffixes", ()))
    if not effect_id or not suffixes:
        return
    source = _resolve_object_locator(entry.get("source"))
    for target_name in tuple(entry.get("targets", ()) or ()):
        target = _resolve_object_locator(target_name)
        if target is None:
            continue
        for suffix in suffixes:
            try:
                prop = _animation_storage_prop(effect_id, suffix)
                if source is not None and target is not source and hasattr(source, prop) and hasattr(target, prop):
                    desired_value = getattr(source, prop)
                    if not _rna_values_equal(getattr(target, prop), desired_value):
                        fbp_set_rna_property_silent(target, prop, desired_value)
            except FBP_DATA_ERRORS:
                pass
            except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
                pass
            try:
                geometry_nodes.update_effect_animation_setting_cb(target, None, effect_id, suffix)
            except FBP_DATA_ERRORS:
                pass
            except Exception as exc:
                fbp_error(
                    f"Dirty animation update failed for {effect_id}.{suffix}",
                    exc,
                    event="dirty.animation_update",
                    context={"effect": effect_id, "suffix": suffix, "target": getattr(target, "name", "")},
                )


def _process_geometry_callback_entry(entry, geometry_nodes, objects):
    del objects
    target = _resolve_object_locator(entry.get("target"))
    callback_name = str(entry.get("callback", "") or "")
    if target is None or not callback_name:
        return
    try:
        callback = getattr(geometry_nodes, callback_name)
    except (AttributeError, ReferenceError):
        return
    try:
        callback(target, None, *tuple(entry.get("args", ()) or ()))
    except FBP_DATA_ERRORS:
        pass
    except Exception as exc:
        fbp_error(
            f"Dirty geometry callback failed for {callback_name}",
            exc,
            event="dirty.geometry_callback",
            context={"callback": callback_name, "target": getattr(target, "name", "")},
        )
    if bool(entry.get("controls", False)):
        try:
            effect_id = str(entry.get("effect_id", "") or "").upper()
            if effect_id:
                _sync_controls_fn()(target, effect_id, create=False)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass


def flush_dirty():
    """Apply coalesced interactive writes in bounded main-thread slices.

    The entry limit bounds large queues; the wall-clock budget also prevents a
    single UI tick from spending tens of milliseconds on expensive effects.
    Unprocessed entries stay in their insertion-ordered mappings for the next
    timer tick, so no values are dropped or reconstructed.

    Effect sliders already run through Blender's timer/main-thread boundary.
    Waiting for an additional depsgraph-idle window made continuous drags look
    inert and could starve the final value in scenes that evaluate every tick.
    Undo and render mutations remain guarded; generated-image publication keeps
    its separate conservative depsgraph barrier.
    """
    global _DIRTY_FLUSH_PENDING, _DIRTY_FLUSH_PENDING_AT
    if fbp_undo_guard_active() or fbp_render_mutation_blocked():
        _DIRTY_METRICS["deferred"] += 1
        _DIRTY_FLUSH_PENDING = True
        try:
            _DIRTY_FLUSH_PENDING_AT = time.monotonic()
        except (RuntimeError, TypeError, ValueError):
            _DIRTY_FLUSH_PENDING_AT = 0.0
        return 0.06
    _DIRTY_FLUSH_PENDING = False
    _DIRTY_FLUSH_PENDING_AT = 0.0
    if not _DIRTY_EFFECT_SETTINGS and not _DIRTY_EFFECT_ANIMATION and not _DIRTY_GEOMETRY_CALLBACKS:
        return None
    try:
        from . import geometry_nodes
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        _DIRTY_FLUSH_PENDING = True
        return 0.10

    try:
        started = time.perf_counter()
    except (AttributeError, RuntimeError):
        started = 0.0
    processed = 0
    _DIRTY_METRICS["flushes"] += 1
    objects = bpy.data.objects
    queues = (
        (_DIRTY_EFFECT_SETTINGS, lambda entry: _process_effect_entry(entry, geometry_nodes)),
        (_DIRTY_EFFECT_ANIMATION, lambda entry: _process_animation_entry(entry, geometry_nodes, objects)),
        (_DIRTY_GEOMETRY_CALLBACKS, lambda entry: _process_geometry_callback_entry(entry, geometry_nodes, objects)),
    )
    stop = False
    for mapping, processor in queues:
        while mapping and processed < _DIRTY_FLUSH_BATCH_LIMIT:
            entry = _pop_next_dirty_entry(mapping)
            if entry is None:
                break
            processor(entry)
            processed += 1
            if started:
                try:
                    if time.perf_counter() - started >= _DIRTY_FLUSH_TIME_BUDGET_SECONDS:
                        stop = True
                        break
                except (AttributeError, RuntimeError):
                    started = 0.0
        if stop or processed >= _DIRTY_FLUSH_BATCH_LIMIT:
            break

    duration_ms = 0.0
    if started:
        try:
            duration_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
        except (AttributeError, RuntimeError):
            duration_ms = 0.0
    _DIRTY_METRICS["processed"] += processed
    _DIRTY_METRICS["last_duration_ms"] = round(duration_ms, 4)
    _DIRTY_METRICS["max_duration_ms"] = max(float(_DIRTY_METRICS["max_duration_ms"]), duration_ms)
    if _DIRTY_EFFECT_SETTINGS or _DIRTY_EFFECT_ANIMATION or _DIRTY_GEOMETRY_CALLBACKS:
        _DIRTY_METRICS["budget_yields"] += int(stop or processed >= _DIRTY_FLUSH_BATCH_LIMIT)
        _DIRTY_FLUSH_PENDING = True
        try:
            _DIRTY_FLUSH_PENDING_AT = time.monotonic()
        except (RuntimeError, TypeError, ValueError):
            _DIRTY_FLUSH_PENDING_AT = 0.0
        return 0.005
    return None


def clear_dirty():
    global _DIRTY_FLUSH_PENDING, _DIRTY_FLUSH_PENDING_AT
    _DIRTY_EFFECT_SETTINGS.clear()
    _DIRTY_EFFECT_ANIMATION.clear()
    _DIRTY_GEOMETRY_CALLBACKS.clear()
    _TARGET_NAMES_CACHE.clear()
    _ANIM_STORAGE_PROP_CACHE.clear()
    _EFFECT_INSTANCE_SUPPORT_CACHE.clear()
    _DIRTY_FLUSH_PENDING = False
    _DIRTY_FLUSH_PENDING_AT = 0.0
    return True


def register():
    clear_dirty()
    for key, value in tuple(_DIRTY_METRICS.items()):
        _DIRTY_METRICS[key] = 0.0 if isinstance(value, float) else 0
    register_service("dirty.clear", clear_dirty, owner=__name__)
    register_service("dirty.snapshot", dirty_queue_snapshot, owner=__name__)


def unregister():
    global _STORAGE_KEY_FN, _SYNC_CONTROLS_FN, _GET_SELECTED_RIGS_FN, _EFFECT_IS_ACTIVE_FN
    unregister_service("dirty.clear")
    unregister_service("dirty.snapshot")
    clear_dirty()
    _STORAGE_KEY_FN = None
    _SYNC_CONTROLS_FN = None
    _GET_SELECTED_RIGS_FN = None
    _EFFECT_IS_ACTIVE_FN = None
