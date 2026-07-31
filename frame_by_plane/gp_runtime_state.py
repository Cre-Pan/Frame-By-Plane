"""Grease Pencil runtime lifecycle policy for Frame By Plane.

This module is Blender-light. It centralizes transient cache groups and task
namespaces so the large Grease Pencil bridge does not duplicate shutdown,
Undo/load invalidation, and reload policy.
"""
from __future__ import annotations

from collections.abc import MutableMapping

GP_TASK_PREFIXES = (
    "fbp_gp_startup_bootstrap",
    "fbp_gp_history_reindex",
    "gp.cycles.proxy_sync.",
    "grease_pencil.",
)

# Attribute names are kept as data so lifecycle policy can be audited without
# importing Blender or the full bridge module.
GP_RUNTIME_MAPPING_NAMES = (
    "_GP_CANVAS_REGISTRY",
    "_GP_PENDING_DEPSGRAPH_EVENTS",
    "_GP_DATA_CANVAS_INDEX",
    "_GP_CANVAS_DATA_POINTERS",
    "_FRAME_SENSITIVE_MASKS",
    "_GP_FRAME_SENSITIVITY_CACHE",
    "_GP_CANVAS_ID_INDEX",
    "_GP_DEPENDENCY_CANVAS_INDEX",
    "_GP_CANVAS_DEPENDENCY_POINTERS",
    "_GP_SCENE_CAMERA_STATE",
    "_GP_FRAME_STATE",
    "_GP_GEOMETRY_GENERATION",
    "_GP_MASK_DIRTY_TIME",
    "_GP_MASK_FIRST_DIRTY_TIME",
    "_GP_MASK_STROKE_COUNT_SIGNATURE",
    "_GP_MASK_MODE_TRANSITION_GUARD",
    "_GP_MASK_STRUCTURAL_EDIT_LAST",
    "_GP_MASK_LIVE_FINALIZE_KEYS",
    "_GP_MASK_LIVE_POLL_KEYS",
    "_GP_MASK_LIVE_POLL_SIGNATURES",
    "_GP_MASK_GEOMETRY_STATE",
    "_GP_MASK_DEBUG_STATE",
)

GP_RUNTIME_SET_NAMES = (
    "_GP_MASK_IMMEDIATE_KEYS",
    "_GP_MASK_STRUCTURAL_EDIT_PENDING",
)


def clear_runtime_collections(namespace: MutableMapping[str, object]) -> tuple[str, ...]:
    """Clear known transient GP containers and report missing/invalid entries."""
    errors: list[str] = []
    for name in GP_RUNTIME_MAPPING_NAMES:
        value = namespace.get(name)
        if value is None:
            errors.append(f"missing:{name}")
            continue
        try:
            value.clear()  # type: ignore[attr-defined]
        except (AttributeError, RuntimeError, TypeError, ValueError):
            errors.append(f"invalid:{name}")
    for name in GP_RUNTIME_SET_NAMES:
        value = namespace.get(name)
        if value is None:
            errors.append(f"missing:{name}")
            continue
        try:
            value.clear()  # type: ignore[attr-defined]
        except (AttributeError, RuntimeError, TypeError, ValueError):
            errors.append(f"invalid:{name}")
    return tuple(errors)


def runtime_contract() -> dict[str, object]:
    return {
        "schema": 1,
        "task_prefixes": GP_TASK_PREFIXES,
        "mapping_names": GP_RUNTIME_MAPPING_NAMES,
        "set_names": GP_RUNTIME_SET_NAMES,
    }


__all__ = (
    "GP_TASK_PREFIXES",
    "GP_RUNTIME_MAPPING_NAMES",
    "GP_RUNTIME_SET_NAMES",
    "clear_runtime_collections",
    "runtime_contract",
)
