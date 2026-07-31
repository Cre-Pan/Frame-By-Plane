"""Short-lived, primitive-keyed cache for Layer Tree snapshots.

Layer Tree structures are rebuilt only from Blender's idle timer. The cache
interface remains for primitive metrics and mode counts, but production keeps a
zero-second TTL so Blender RNA wrappers never survive between calls.

The module deliberately has no Blender dependency so cache behavior and
performance budgets can be tested outside Blender.
"""

from __future__ import annotations

from collections import OrderedDict
import time
from typing import Any, Callable


SNAPSHOT_TTL_SECONDS = 0.0
SNAPSHOT_MAX_SCENES = 4

_SNAPSHOTS: "OrderedDict[object, dict[str, Any]]" = OrderedDict()
_MODE_COUNTS: dict[object, dict[str, Any]] = {}
_METRICS = {
    "requests": 0,
    "hits": 0,
    "misses": 0,
    "invalidations": 0,
    "build_seconds": 0.0,
    "max_build_seconds": 0.0,
    "max_snapshot_items": 0,
}


def _now() -> float:
    return time.monotonic()


def _snapshot_item_count(snapshot: Any) -> int:
    if not isinstance(snapshot, dict):
        return 0
    try:
        return int(len(snapshot.get("rigs", ())) + len(snapshot.get("collections", ())))
    except (AttributeError, TypeError, ValueError):
        return 0


def get_or_build_snapshot(
    scene_key: object,
    fingerprint: object,
    builder: Callable[[], Any],
    *,
    force: bool = False,
    now: float | None = None,
    ttl_seconds: float = SNAPSHOT_TTL_SECONDS,
):
    """Return a recent matching snapshot or call ``builder`` exactly once.

    ``scene_key`` and ``fingerprint`` must contain only primitive/hashable data.
    The returned snapshot can contain Blender RNA references because entries are
    intentionally short-lived and invalidated before Main replacement.
    """
    _METRICS["requests"] += 1
    current_time = _now() if now is None else float(now)
    entry = _SNAPSHOTS.get(scene_key)
    if not force and entry is not None:
        age = current_time - float(entry.get("created_at", 0.0) or 0.0)
        if entry.get("fingerprint") == fingerprint and age <= max(0.0, float(ttl_seconds)):
            _METRICS["hits"] += 1
            _SNAPSHOTS.move_to_end(scene_key)
            return entry.get("snapshot")

    _METRICS["misses"] += 1
    started = time.perf_counter()
    snapshot = builder()
    elapsed = max(0.0, time.perf_counter() - started)
    _METRICS["build_seconds"] += elapsed
    _METRICS["max_build_seconds"] = max(float(_METRICS["max_build_seconds"]), elapsed)
    _METRICS["max_snapshot_items"] = max(
        int(_METRICS["max_snapshot_items"]),
        _snapshot_item_count(snapshot),
    )
    if max(0.0, float(ttl_seconds)) > 0.0:
        _SNAPSHOTS[scene_key] = {
            "fingerprint": fingerprint,
            "created_at": current_time,
            "snapshot": snapshot,
        }
        _SNAPSHOTS.move_to_end(scene_key)
        while len(_SNAPSHOTS) > SNAPSHOT_MAX_SCENES:
            oldest_key, _entry = _SNAPSHOTS.popitem(last=False)
            _MODE_COUNTS.pop(oldest_key, None)
    else:
        _SNAPSHOTS.pop(scene_key, None)
    return snapshot


def invalidate_snapshot(scene_key: object | None = None) -> int:
    """Discard one scene snapshot or every cached scene."""
    if scene_key is None:
        removed = len(_SNAPSHOTS)
        _SNAPSHOTS.clear()
        _MODE_COUNTS.clear()
    else:
        removed = int(scene_key in _SNAPSHOTS)
        _SNAPSHOTS.pop(scene_key, None)
        _MODE_COUNTS.pop(scene_key, None)
    if removed:
        _METRICS["invalidations"] += removed
    return removed


def set_mode_counts(
    scene_key: object,
    signature: str,
    *,
    total: int,
    planes: int,
    grease_pencil: int,
) -> None:
    """Store visible row totals produced by the structural rebuild."""
    _MODE_COUNTS[scene_key] = {
        "signature": str(signature or ""),
        "total": max(0, int(total)),
        "planes": max(0, int(planes)),
        "gp": max(0, int(grease_pencil)),
    }


def mode_counts(scene_key: object, signature: str = "") -> dict[str, int] | None:
    """Return cached mode counts when they still match the row signature."""
    entry = _MODE_COUNTS.get(scene_key)
    if entry is None:
        return None
    expected = str(signature or "")
    if expected and str(entry.get("signature", "") or "") != expected:
        return None
    return {
        "total": int(entry.get("total", 0) or 0),
        "planes": int(entry.get("planes", 0) or 0),
        "gp": int(entry.get("gp", 0) or 0),
    }


def snapshot_metrics(*, reset: bool = False) -> dict[str, Any]:
    """Return primitive-only cache metrics for diagnostics."""
    requests = int(_METRICS["requests"])
    hits = int(_METRICS["hits"])
    payload = {
        **_METRICS,
        "active_scenes": len(_SNAPSHOTS),
        "hit_ratio": (float(hits) / requests) if requests else 0.0,
        "build_milliseconds": float(_METRICS["build_seconds"]) * 1000.0,
        "max_build_milliseconds": float(_METRICS["max_build_seconds"]) * 1000.0,
        "ttl_milliseconds": SNAPSHOT_TTL_SECONDS * 1000.0,
    }
    if reset:
        _SNAPSHOTS.clear()
        _MODE_COUNTS.clear()
        for key in tuple(_METRICS):
            _METRICS[key] = 0.0 if "seconds" in key else 0
    return payload


__all__ = (
    "SNAPSHOT_MAX_SCENES",
    "SNAPSHOT_TTL_SECONDS",
    "get_or_build_snapshot",
    "invalidate_snapshot",
    "mode_counts",
    "set_mode_counts",
    "snapshot_metrics",
)
