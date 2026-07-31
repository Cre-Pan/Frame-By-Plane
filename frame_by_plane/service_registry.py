"""Small late-bound service registry used to keep feature modules decoupled.

The registry deliberately has no Blender or add-on imports.  Modules that own
interactive services register callbacks during their normal ``register()``
phase; lower-level modules can request those services without importing the UI
or another high-level subsystem.  Missing services are a valid state during
background execution, partial registration and teardown.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


_SERVICES: dict[str, tuple[Callable[..., Any], str]] = {}


def service_descriptor(
    service_id: str,
    api_version: int,
    capabilities,
    *,
    stage: str = "ALPHA",
) -> dict[str, object]:
    """Build the primitive-only descriptor shared by optional services."""
    return {
        "id": str(service_id or ""),
        "api_version": int(api_version),
        "stage": str(stage or "ALPHA").upper(),
        "capabilities": tuple(str(item) for item in tuple(capabilities or ())),
    }


def register_service(name: str, callback: Callable[..., Any], *, owner: str = "") -> bool:
    """Register or replace one named callback.

    Replacing a stale callback is intentional during in-place extension reloads.
    The optional owner is used only for deterministic batch teardown.
    """
    key = str(name or "").strip()
    if not key or not callable(callback):
        return False
    _SERVICES[key] = (callback, str(owner or ""))
    return True


def unregister_service(name: str, callback: Callable[..., Any] | None = None) -> bool:
    """Remove one service, optionally only when the callback still matches."""
    key = str(name or "").strip()
    current = _SERVICES.get(key)
    if current is None:
        return False
    if callback is not None and current[0] is not callback:
        return False
    del _SERVICES[key]
    return True


def clear_services(*, owner: str = "") -> int:
    """Remove all services or only services registered by ``owner``."""
    owner = str(owner or "")
    keys = tuple(
        key for key, (_callback, registered_owner) in _SERVICES.items()
        if not owner or registered_owner == owner
    )
    for key in keys:
        _SERVICES.pop(key, None)
    return len(keys)


def get_service(name: str) -> Callable[..., Any] | None:
    """Return a registered callback without invoking it."""
    entry = _SERVICES.get(str(name or "").strip())
    return entry[0] if entry is not None else None


def call_service(name: str, *args, default=None, **kwargs):
    """Invoke a service when available and otherwise return ``default``.

    Exceptions intentionally propagate.  The caller owns the diagnostic context
    and can decide whether an unavailable/failed optional service is recoverable.
    """
    callback = get_service(name)
    if callback is None:
        return default
    return callback(*args, **kwargs)


def service_snapshot() -> dict[str, str]:
    """Return a primitive-only diagnostic snapshot of active services."""
    return {
        key: owner
        for key, (_callback, owner) in sorted(_SERVICES.items())
    }


def register():
    """Reset stale services before a new add-on registration generation."""
    clear_services()


def unregister():
    """Release any service left by a partially torn-down feature module."""
    clear_services()


__all__ = (
    "call_service",
    "clear_services",
    "get_service",
    "register",
    "register_service",
    "service_descriptor",
    "service_snapshot",
    "unregister",
    "unregister_service",
)
