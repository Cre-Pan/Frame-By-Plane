"""Shared transactional registration helpers for Frame By Plane.

Blender keeps RNA classes, handlers and timers alive independently from Python
module reloads. A failed or interrupted add-on enable can therefore leave a
partially registered generation behind. These helpers keep ownership checks
strict, replace only Frame By Plane generations and roll back partial batches.
"""

from __future__ import annotations

from collections.abc import Iterable

import bpy

from .runtime import FBP_DATA_IO_ERRORS, fbp_error, fbp_warn


def _module_belongs_to_frame_by_plane(module_name: str) -> bool:
    """Return whether a Python module is owned by the current Frame By Plane package."""
    module_name = str(module_name or "").strip(".")
    if not module_name:
        return False
    package_name = str(__package__ or "frame_by_plane").strip(".")
    return bool(
        module_name == package_name
        or module_name.startswith(f"{package_name}.")
        or module_name == "frame_by_plane"
        or module_name.startswith("frame_by_plane.")
        or module_name.endswith(".frame_by_plane")
        or ".frame_by_plane." in module_name
    )


def _registered_class_for(cls):
    """Return Blender's currently registered class with the same Python name."""
    try:
        return getattr(bpy.types, str(getattr(cls, "__name__", "") or ""), None)
    except FBP_DATA_IO_ERRORS:
        return None


def _class_registration_identity(cls):
    return (
        str(getattr(cls, "__module__", "") or ""),
        str(getattr(cls, "__name__", "") or ""),
        str(getattr(cls, "bl_idname", "") or ""),
    )


def _is_frame_by_plane_class(cls) -> bool:
    """Use the module namespace as ownership authority.

    Class-name and ``bl_idname`` prefixes are intentionally not sufficient:
    another extension may legitimately choose the same short prefix.
    """
    if cls is None:
        return False
    module_name, class_name, bl_idname = _class_registration_identity(cls)
    if module_name:
        return _module_belongs_to_frame_by_plane(module_name)
    # Extremely old/stale Blender class wrappers can lose ``__module__``.
    # Require both independent FBP markers before treating such an anonymous
    # class as ours; this fallback is never used for normally imported classes.
    return bool(
        class_name.startswith("FBP_")
        and bl_idname.startswith(("fbp.", "FBP_", "FBP"))
    )


def _stale_class_matches(current, expected) -> bool:
    if current is expected:
        return True
    if not _is_frame_by_plane_class(current):
        return False
    current_module, current_name, current_id = _class_registration_identity(current)
    expected_module, expected_name, expected_id = _class_registration_identity(expected)
    if current_name != expected_name:
        return False
    if current_id and expected_id and current_id != expected_id:
        return False
    if not expected_module:
        return True
    return bool(
        current_module == expected_module
        or (
            _module_belongs_to_frame_by_plane(current_module)
            and _module_belongs_to_frame_by_plane(expected_module)
            and current_module.rsplit(".", 1)[-1]
            == expected_module.rsplit(".", 1)[-1]
        )
    )


def _register_class_exact(cls) -> bool:
    try:
        bpy.utils.register_class(cls)
        return True
    except FBP_DATA_IO_ERRORS:
        return False


def _unregister_class_exact(cls) -> bool:
    try:
        bpy.utils.unregister_class(cls)
        return True
    except FBP_DATA_IO_ERRORS:
        return False


def register_classes(classes: Iterable[type]) -> tuple[type, ...]:
    """Register classes in order and restore the previous generation on failure."""
    active: list[type] = []
    newly_registered: list[type] = []
    replaced: list[type] = []
    try:
        for cls in tuple(classes or ()):
            try:
                if issubclass(cls, bpy.types.UIList):
                    from .ui_list_state import harden_ui_list_class
                    cls = harden_ui_list_class(cls)
            except (AttributeError, TypeError, RuntimeError):
                pass
            existing = _registered_class_for(cls)
            if existing is cls:
                active.append(cls)
                continue
            if existing is not None:
                if not _stale_class_matches(existing, cls):
                    existing_identity = ".".join(
                        part for part in _class_registration_identity(existing)[:2] if part
                    ) or repr(existing)
                    raise RuntimeError(
                        f"Refusing to replace foreign Blender class {existing_identity} "
                        f"while registering {cls.__module__}.{cls.__name__}"
                    )
                if not _unregister_class_exact(existing):
                    raise RuntimeError(
                        f"Could not unregister stale class "
                        f"{existing.__module__}.{existing.__name__}"
                    )
                replaced.append(existing)
            bpy.utils.register_class(cls)
            active.append(cls)
            newly_registered.append(cls)
    except Exception as exc:
        failed_name = str(getattr(locals().get("cls"), "__name__", "<unknown>") or "<unknown>")
        for registered in reversed(newly_registered):
            _unregister_class_exact(registered)
        restored = 0
        for previous in replaced:
            if _registered_class_for(previous) is not None:
                continue
            restored += int(_register_class_exact(previous))
        fbp_error(
            "Class registration transaction failed",
            exc,
            event="registration.class_batch",
            context={
                "class": failed_name,
                "registered_before_failure": len(newly_registered),
                "restored_previous_generation": restored,
            },
        )
        raise
    return tuple(active)


def unregister_classes(classes: Iterable[type]) -> int:
    """Unregister current or stale owned generations without aborting teardown."""
    removed = 0
    for cls in reversed(tuple(classes or ())):
        existing = _registered_class_for(cls)
        if existing is not None and not _stale_class_matches(existing, cls):
            continue
        candidate = existing if existing is not None else cls
        removed += int(_unregister_class_exact(candidate))
    return removed


def register_interactive_classes(classes: Iterable[type]) -> tuple[type, ...]:
    """Register UI-only RNA classes outside Blender background processes."""
    if bool(getattr(getattr(bpy, "app", None), "background", False)):
        return ()
    return register_classes(classes)


def unregister_type_properties(owner, names: Iterable[str]) -> int:
    """Remove RNA properties from one Blender type without aborting teardown."""
    if owner is None:
        return 0
    removed = 0
    for raw_name in reversed(tuple(names or ())):
        try:
            name = "" if raw_name is None else str(raw_name).strip()
        except FBP_DATA_IO_ERRORS:
            continue
        if not name:
            continue
        try:
            delattr(owner, name)
            removed += 1
        except FBP_DATA_IO_ERRORS:
            # A missing property is already in the requested teardown state.
            continue
    return removed


def _handler_module_matches(module_name: str, module_suffix: str) -> bool:
    """Return whether a callback module belongs to this add-on generation."""
    module_name = str(module_name or "")
    suffix = str(module_suffix or "").strip(".")
    if not _module_belongs_to_frame_by_plane(module_name):
        return False
    return not suffix or module_name == suffix or module_name.endswith(f".{suffix}")


def _handler_suffix(callback, module_suffix: str) -> str:
    suffix = str(module_suffix or "").strip(".")
    if suffix:
        return suffix
    module_name = str(getattr(callback, "__module__", "") or "")
    return module_name.rsplit(".", 1)[-1] if module_name else ""


def _restore_handler_entries(handler_list, entries) -> None:
    for index, callback in sorted(tuple(entries or ()), key=lambda item: item[0]):
        try:
            handler_list.insert(min(max(0, int(index)), len(handler_list)), callback)
        except FBP_DATA_IO_ERRORS:
            try:
                handler_list.append(callback)
            except FBP_DATA_IO_ERRORS:
                pass


def _remove_handler_at(handler_list, index, callback) -> bool:
    try:
        del handler_list[index]
        return True
    except FBP_DATA_IO_ERRORS:
        try:
            handler_list.remove(callback)
            return True
        except FBP_DATA_IO_ERRORS:
            return False


def remove_handlers_by_name(handler_list, *names: str, module_suffix: str = "") -> int:
    """Remove only owned callbacks with the requested names.

    Unknown or foreign module namespaces are preserved even when their callback
    names match. This avoids deleting startup-script or third-party handlers.
    """
    wanted = {str(name or "") for name in names if str(name or "")}
    if not wanted or handler_list is None:
        return 0
    suffix = str(module_suffix or "")
    try:
        callbacks = tuple(handler_list)
    except FBP_DATA_IO_ERRORS:
        return 0
    indices = [
        index
        for index, callback in enumerate(callbacks)
        if str(getattr(callback, "__name__", "") or "") in wanted
        and _handler_module_matches(
            str(getattr(callback, "__module__", "") or ""), suffix
        )
    ]
    removed = 0
    for index in reversed(indices):
        removed += int(_remove_handler_at(handler_list, index, callbacks[index]))
    return removed


def _ensure_handler_once(handler_list, callback, *, module_suffix: str = ""):
    """Return ``(success, added, removed_entries)`` for one handler callback."""
    if handler_list is None or callback is None:
        return False, False, ()
    name = str(getattr(callback, "__name__", "") or "")
    if not name:
        return False, False, ()
    suffix = _handler_suffix(callback, module_suffix)
    try:
        callbacks = tuple(handler_list)
    except FBP_DATA_IO_ERRORS:
        return False, False, ()

    current_indices = [index for index, item in enumerate(callbacks) if item is callback]
    keep_index = current_indices[0] if current_indices else -1
    remove_indices = []
    for index, item in enumerate(callbacks):
        if index == keep_index:
            continue
        if item is callback:
            remove_indices.append(index)
            continue
        if str(getattr(item, "__name__", "") or "") != name:
            continue
        if _handler_module_matches(
            str(getattr(item, "__module__", "") or ""), suffix
        ):
            remove_indices.append(index)

    removed_entries = []
    for index in reversed(remove_indices):
        item = callbacks[index]
        if _remove_handler_at(handler_list, index, item):
            removed_entries.append((index, item))
    removed_entries.reverse()

    if keep_index >= 0:
        return True, False, tuple(removed_entries)
    try:
        handler_list.append(callback)
        return True, True, tuple(removed_entries)
    except FBP_DATA_IO_ERRORS as exc:
        _restore_handler_entries(handler_list, removed_entries)
        fbp_warn(f"Could not register handler {name}", exc)
        return False, False, ()


def append_handler_once(handler_list, callback, *, module_suffix: str = "") -> bool:
    """Replace stale owned generations while preserving an existing current one."""
    success, _added, _removed = _ensure_handler_once(
        handler_list, callback, module_suffix=module_suffix
    )
    return success


def register_handlers(specs) -> int:
    """Register handler specifications and restore the prior state on failure."""
    changes = []
    try:
        for handler_list, callback, module_suffix in tuple(specs or ()):
            suffix = _handler_suffix(callback, str(module_suffix or ""))
            success, added, removed = _ensure_handler_once(
                handler_list, callback, module_suffix=suffix
            )
            if not success:
                name = str(getattr(callback, "__name__", "") or "<unknown>")
                raise RuntimeError(f"Could not register Blender handler {name}")
            changes.append((handler_list, callback, added, removed))
    except Exception as exc:
        for handler_list, callback, added, removed in reversed(changes):
            if added:
                try:
                    callbacks = tuple(handler_list)
                except FBP_DATA_IO_ERRORS:
                    callbacks = ()
                for index in range(len(callbacks) - 1, -1, -1):
                    if callbacks[index] is callback:
                        _remove_handler_at(handler_list, index, callback)
                        break
            _restore_handler_entries(handler_list, removed)
        fbp_error(
            "Handler registration transaction failed",
            exc,
            event="registration.handler_batch",
            context={"registered_before_failure": len(changes)},
        )
        raise
    return len(changes)


def unregister_timer(callback) -> bool:
    """Unregister one timer when present and tolerate stale callback objects."""
    if callback is None:
        return False
    try:
        if not bpy.app.timers.is_registered(callback):
            return False
        bpy.app.timers.unregister(callback)
        return True
    except FBP_DATA_IO_ERRORS:
        return False


__all__ = (
    "append_handler_once",
    "register_classes",
    "register_handlers",
    "register_interactive_classes",
    "remove_handlers_by_name",
    "unregister_classes",
    "unregister_type_properties",
    "unregister_timer",
)
