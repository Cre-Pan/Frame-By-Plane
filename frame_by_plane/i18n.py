"""Interface translations for Frame By Plane.

Blender translates interface text at draw time by looking the English string up
in the dictionaries registered with ``bpy.app.translations``. The catalogs in
``translations/<language>.json`` map each English string to its translation.

* **Automatic** (default): the catalog for Blender's current language is
  registered, and re-registered when that language changes, so the add-on
  follows Blender's Preferences. English users load no catalog at all.
* **English**: nothing is registered.
* **A specific language**: that catalog is registered under every Blender
  locale, so the add-on uses it whatever language Blender is set to.
"""

from __future__ import annotations

import json
from pathlib import Path

import bpy


_TRANSLATIONS_DIR = Path(__file__).resolve().parent / "translations"
_REGISTRATION_KEY = __package__ or "frame_by_plane"

# (preference id, catalog file stem, display name, Blender locales served)
FBP_LANGUAGES = (
    ("it", "Italiano", ("it_IT", "it")),
    ("es", "Español", ("es", "es_ES")),
    ("fr", "Français", ("fr_FR", "fr")),
    ("de", "Deutsch", ("de_DE", "de")),
    ("zh_hans", "简体中文", ("zh_HANS", "zh_CN")),
    ("ja", "日本語", ("ja_JP", "ja")),
)

# Blender translates operator button text in the "Operator" context and most
# other text in the default context, so each string is registered in both.
_CONTEXTS = ("*", "Operator")

FBP_LANGUAGE_ITEMS = (
    ("AUTO", "Automatic", "Follow the language set in Blender's Preferences"),
    ("EN", "English", "Always show Frame By Plane in English"),
) + tuple((code.upper(), name, "") for code, name, _locales in FBP_LANGUAGES)

_catalog_cache: dict[str, dict] = {}
_registered = False


def _catalog(code):
    """Return {(context, English): translation} for one language."""
    cached = _catalog_cache.get(code)
    if cached is not None:
        return cached
    entries = {}
    try:
        data = json.loads((_TRANSLATIONS_DIR / f"{code}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if isinstance(data, dict):
        for english, translated in data.items():
            if isinstance(english, str) and isinstance(translated, str) and translated and translated != english:
                for context in _CONTEXTS:
                    entries[(context, english)] = translated
    _catalog_cache[code] = entries
    return entries


def _current_locale():
    try:
        return str(bpy.app.translations.locale or "")
    except (AttributeError, RuntimeError):
        return ""


def _all_blender_locales():
    try:
        locales = tuple(bpy.app.translations.locales)
    except (AttributeError, RuntimeError):
        locales = ()
    served = {locale for _code, _name, extra in FBP_LANGUAGES for locale in extra}
    return tuple(sorted(set(locales) | served | {"en_US", "en_GB"}))


def _build(choice):
    choice = str(choice or "AUTO").upper()
    if choice == "EN":
        return {}
    if choice == "AUTO":
        # Load only the catalog for Blender's current language; a language
        # change in Preferences re-applies through the msgbus subscription.
        current = _current_locale()
        for code, _name, locales in FBP_LANGUAGES:
            if current in locales or current.split("_")[0] in locales:
                catalog = _catalog(code)
                return {current: catalog} if catalog else {}
        return {}
    for code, _name, _locales in FBP_LANGUAGES:
        if code.upper() == choice:
            catalog = _catalog(code)
            return {locale: catalog for locale in _all_blender_locales()} if catalog else {}
    return {}


def _unregister_translations():
    global _registered
    if not _registered:
        return
    try:
        bpy.app.translations.unregister(_REGISTRATION_KEY)
    except (AttributeError, RuntimeError, ValueError):
        pass
    _registered = False


def fbp_apply_interface_language(choice=None):
    """(Re)register the translation tables for the chosen language."""
    global _registered
    if choice is None:
        choice = _preference_choice()
    _unregister_translations()
    table = _build(choice)
    if not table:
        return False
    try:
        bpy.app.translations.register(_REGISTRATION_KEY, table)
        _registered = True
    except (AttributeError, RuntimeError, ValueError):
        _registered = False
    return _registered


def _preference_choice():
    try:
        addon = bpy.context.preferences.addons.get(_REGISTRATION_KEY)
        return str(getattr(getattr(addon, "preferences", None), "interface_language", "AUTO") or "AUTO")
    except (AttributeError, ReferenceError, RuntimeError):
        return "AUTO"


def update_interface_language_cb(self, context):
    fbp_apply_interface_language(getattr(self, "interface_language", "AUTO"))
    try:
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except (AttributeError, ReferenceError, RuntimeError):
        pass


_MSGBUS_OWNER = object()


def _on_blender_language_changed():
    if _preference_choice().upper() == "AUTO":
        fbp_apply_interface_language("AUTO")


def register():
    # Registered after the add-on preferences, so their saved value applies.
    fbp_apply_interface_language()
    try:
        bpy.msgbus.subscribe_rna(
            key=(bpy.types.PreferencesView, "language"),
            owner=_MSGBUS_OWNER,
            args=(),
            notify=_on_blender_language_changed,
            options={"PERSISTENT"},
        )
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass


def unregister():
    try:
        bpy.msgbus.clear_by_owner(_MSGBUS_OWNER)
    except (AttributeError, RuntimeError):
        pass
    _unregister_translations()
    _catalog_cache.clear()


__all__ = (
    "FBP_LANGUAGE_ITEMS",
    "FBP_LANGUAGES",
    "fbp_apply_interface_language",
    "update_interface_language_cb",
)
