"""Centralized, preference-aware shortcut registration helpers.

Frame By Plane registers shortcuts from multiple feature modules. Keeping the
shared lifecycle here prevents duplicate keymap entries after hot reloads and
lets Add-on Preferences update every shortcut without restarting Blender.
"""

from __future__ import annotations

import importlib
import sys

import bpy

from .runtime import FBP_DATA_ERRORS, fbp_warn


IS_MACOS = sys.platform == "darwin"


def primary_modifier_name() -> str:
    """Return Blender's user-facing primary command modifier."""
    return "Cmd" if IS_MACOS else "Ctrl"


def alt_modifier_name() -> str:
    """Return the platform-native label for Blender's Alt/Option modifier."""
    return "Option" if IS_MACOS else "Alt"


def primary_modifier_kwargs(*, shift: bool = False) -> dict[str, bool]:
    """Return keymap kwargs using Command on macOS and Control elsewhere."""
    values = {"shift": bool(shift)} if shift else {}
    values["oskey" if IS_MACOS else "ctrl"] = True
    return values


def primary_modifier_pressed(event) -> bool:
    """Read the platform-native primary modifier from one Blender event."""
    attribute = "oskey" if IS_MACOS else "ctrl"
    return bool(getattr(event, attribute, False))


def primary_shortcut_label(key: str, *, shift: bool = False) -> str:
    """Return labels such as Ctrl+G or Cmd+Shift+G."""
    parts = [primary_modifier_name()]
    if shift:
        parts.append("Shift")
    parts.append(str(key or "").strip())
    return "+".join(part for part in parts if part)


def alt_shortcut_label(key: str) -> str:
    """Return labels such as Alt+S or Option+S."""
    return f"{alt_modifier_name()}+{str(key or '').strip()}"


SHORTCUT_PREFERENCE_DEFAULTS = {
    "shortcut_duplicate_layer": True,
    "shortcut_group_layers": True,
    "shortcut_viewport_pie": True,
    "shortcut_tab_layer_edit": True,
    "shortcut_gp_alt_s_guard": True,
    "shortcut_gp_frame_scrub": True,
}


def shortcut_enabled(preference_name: str, default: bool | None = None) -> bool:
    """Return one shortcut preference without making registration depend on UI state."""
    if bool(getattr(bpy.app, "background", False)):
        return False
    fallback = SHORTCUT_PREFERENCE_DEFAULTS.get(preference_name, True) if default is None else bool(default)
    try:
        from .interface_preferences import fbp_get_addon_preferences

        preferences = fbp_get_addon_preferences()
        if preferences is None:
            return bool(fallback)
        return bool(getattr(preferences, preference_name, fallback))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return bool(fallback)


def keyconfig_triplet():
    """Return WindowManager, add-on keyconfig and default keyconfig when available."""
    window_manager = getattr(getattr(bpy, "context", None), "window_manager", None)
    keyconfigs = getattr(window_manager, "keyconfigs", None) if window_manager else None
    addon_config = getattr(keyconfigs, "addon", None) if keyconfigs else None
    default_config = getattr(keyconfigs, "default", None) if keyconfigs else None
    return window_manager, addon_config, default_config


def addon_keymap(
    name: str,
    *,
    fallback_space_type: str = "EMPTY",
    fallback_region_type: str = "WINDOW",
):
    """Create/reuse an add-on keymap using Blender's native keymap metadata.

    Hard-coding ``space_type='EMPTY'`` for mode-specific keymaps can make an
    item appear in Preferences yet never receive events. Mirroring Blender's
    default keymap keeps the shortcut in the correct editor and region.
    """
    _window_manager, addon_config, default_config = keyconfig_triplet()
    if addon_config is None:
        return None
    reference = None
    try:
        reference = default_config.keymaps.get(name) if default_config else None
    except FBP_DATA_ERRORS:
        reference = None
    space_type = str(getattr(reference, "space_type", fallback_space_type) or fallback_space_type)
    region_type = str(getattr(reference, "region_type", fallback_region_type) or fallback_region_type)
    try:
        return addon_config.keymaps.new(name=name, space_type=space_type, region_type=region_type)
    except FBP_DATA_ERRORS as exc:
        fbp_warn(f"Could not create Frame By Plane keymap {name}", exc)
        return None


def remove_matching_keymap_items(keymap, predicate) -> int:
    """Remove stale owned items and return how many entries were removed."""
    removed = 0
    if keymap is None:
        return removed
    for item in tuple(getattr(keymap, "keymap_items", ()) or ()):
        try:
            if not predicate(item):
                continue
            keymap.keymap_items.remove(item)
            removed += 1
        except FBP_DATA_ERRORS:
            continue
    return removed


def unregister_keymap_items(storage) -> None:
    """Remove every ``(keymap, item)`` pair and empty the caller-owned storage."""
    while storage:
        keymap, item = storage.pop()
        try:
            keymap.keymap_items.remove(item)
        except FBP_DATA_ERRORS:
            pass


def native_keymap_names(candidates: tuple[str, ...]) -> tuple[str, ...]:
    """Return only candidate names that exist in Blender's active default config."""
    _window_manager, _addon_config, default_config = keyconfig_triplet()
    if default_config is None:
        return ()
    available = []
    for name in candidates:
        try:
            if default_config.keymaps.get(name) is not None:
                available.append(name)
        except FBP_DATA_ERRORS:
            continue
    return tuple(available)


def refresh_keymap_registration(register_callback) -> bool:
    """Rebuild one shortcut family only in interactive Blender sessions."""
    if bool(getattr(bpy.app, "background", False)) or not callable(register_callback):
        return False
    return bool(register_callback())


def refresh_all_shortcuts() -> None:
    """Rebuild every interactive Frame By Plane shortcut from current preferences."""
    if bool(getattr(bpy.app, "background", False)):
        return
    package = __package__ or "frame_by_plane"
    for module_name in ("operators", "viewport_pie", "grease_pencil_scrub", "grease_pencil_bridge"):
        try:
            module = importlib.import_module(f".{module_name}", package)
            refresh = getattr(module, "refresh_keymaps", None)
            if callable(refresh):
                refresh()
        except Exception as exc:
            fbp_warn(f"Could not refresh Frame By Plane shortcuts in {module_name}", exc)
