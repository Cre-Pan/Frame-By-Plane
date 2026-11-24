"""Choose which transport buttons the timeline headers show.

Blender draws the playback row of the Timeline, Dope Sheet, Graph Editor, NLA
and Sequencer through one shared ``bl_ui.space_time.playback_controls``
function. This module wraps that function instead of copying it: Blender's own
drawing runs unchanged and only the jump buttons the artist switched off are
skipped. The switches live in the add-on preferences, so the choice holds in
every file, and they are drawn at the bottom of Blender's Playback Options
popover (the small arrow beside the transport buttons; Time Jump on 5.2).
"""

from __future__ import annotations

import bpy

from .interface_preferences import fbp_get_addon_preferences


# Preference name -> operator idname whose buttons it hides.
FBP_PLAYBACK_BUTTON_PREFS = (
    ("playback_show_jump_endpoints", "screen.frame_jump"),
    ("playback_show_jump_keyframes", "screen.keyframe_jump"),
    ("playback_show_jump_delta", "screen.time_jump"),
)
_PLAY_REVERSE_PREF = "playback_show_play_reverse"

_PLAYBACK_MODULES = ("space_time", "space_dopesheet", "space_graph", "space_nla", "space_sequencer")
_OPTIONS_PANELS = ("TIME_PT_playback_options", "TIME_PT_jump", "TIME_PT_playback")

_PATCHED_MODULES = {}
_OPTIONS_PANEL = []


class _HiddenOperator:
    """Stand-in for the operator properties of a button that is not drawn."""

    __slots__ = ()

    def __setattr__(self, _name, _value):
        pass

    def __getattr__(self, _name):
        return None


_HIDDEN_OPERATOR = _HiddenOperator()


class _FilteredLayout:
    """UILayout proxy that skips the operator buttons listed in ``hidden``."""

    __slots__ = ("_layout", "_hidden", "_hide_reverse")

    def __init__(self, layout, hidden, hide_reverse):
        object.__setattr__(self, "_layout", layout)
        object.__setattr__(self, "_hidden", hidden)
        object.__setattr__(self, "_hide_reverse", hide_reverse)

    def _wrap(self, value):
        # Sub-layouts (row, column, split...) keep the filter.
        if callable(getattr(value, "operator", None)) and callable(getattr(value, "row", None)):
            return _FilteredLayout(value, self._hidden, self._hide_reverse)
        return value

    def operator(self, operator, *args, **kwargs):
        if operator in self._hidden:
            return _HIDDEN_OPERATOR
        if (
            self._hide_reverse
            and operator == "screen.animation_play"
            and kwargs.get("icon") == "PLAY_REVERSE"
        ):
            return _HIDDEN_OPERATOR
        return self._layout.operator(operator, *args, **kwargs)

    def __getattr__(self, name):
        value = getattr(self._layout, name)
        if not callable(value):
            return value

        def call(*args, **kwargs):
            return self._wrap(value(*args, **kwargs))

        return call

    def __setattr__(self, name, value):
        setattr(self._layout, name, value)


def fbp_hidden_playback_operators(context=None):
    """Return the operator idnames whose header buttons are switched off."""
    prefs = fbp_get_addon_preferences(context)
    if prefs is None:
        return frozenset(), False
    hidden = frozenset(
        idname for prop, idname in FBP_PLAYBACK_BUTTON_PREFS
        if not bool(getattr(prefs, prop, True))
    )
    return hidden, not bool(getattr(prefs, _PLAY_REVERSE_PREF, True))


def _make_wrapper(original):
    def playback_controls(layout, context):
        try:
            hidden, hide_reverse = fbp_hidden_playback_operators(context)
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            hidden, hide_reverse = frozenset(), False
        if hidden or hide_reverse:
            layout = _FilteredLayout(layout, hidden, hide_reverse)
        return original(layout, context)

    playback_controls._fbp_original = original
    return playback_controls


def fbp_draw_playback_button_options(self, context):
    """Show-button checkboxes at the bottom of the Playback Options popover."""
    prefs = fbp_get_addon_preferences(context)
    if prefs is None:
        return
    layout = self.layout
    layout.separator()
    col = layout.column(align=True)
    col.use_property_split = False
    col.use_property_decorate = False
    col.label(text="Show Buttons")
    col.prop(prefs, "playback_show_jump_endpoints", text="Jump to Start/End")
    col.prop(prefs, "playback_show_jump_keyframes", text="Jump to Prev/Next Keyframe")
    col.prop(prefs, "playback_show_jump_delta", text="Jump Time by Delta")
    col.prop(prefs, _PLAY_REVERSE_PREF, text="Play Reverse")


def _patch_playback_controls():
    import importlib

    original = None
    for name in _PLAYBACK_MODULES:
        try:
            module = importlib.import_module(f"bl_ui.{name}")
        except ImportError:
            continue
        current = getattr(module, "playback_controls", None)
        if not callable(current):
            continue
        base = getattr(current, "_fbp_original", current)
        if original is None:
            original = _make_wrapper(base)
        _PATCHED_MODULES[name] = (module, base)
        module.playback_controls = original


def _restore_playback_controls():
    for module, base in _PATCHED_MODULES.values():
        current = getattr(module, "playback_controls", None)
        if getattr(current, "_fbp_original", None) is not None:
            module.playback_controls = base
    _PATCHED_MODULES.clear()


def _append_options():
    for name in _OPTIONS_PANELS:
        panel = getattr(bpy.types, name, None)
        if panel is None:
            continue
        try:
            panel.remove(fbp_draw_playback_button_options)
        except (ValueError, RuntimeError):
            pass
        panel.append(fbp_draw_playback_button_options)
        _OPTIONS_PANEL.append(panel)
        return


def _remove_options():
    for panel in _OPTIONS_PANEL:
        try:
            panel.remove(fbp_draw_playback_button_options)
        except (ValueError, RuntimeError):
            pass
    _OPTIONS_PANEL.clear()


def _redraw_time_headers():
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in {"DOPESHEET_EDITOR", "GRAPH_EDITOR", "NLA_EDITOR", "SEQUENCE_EDITOR"}:
                    area.tag_redraw()
    except (AttributeError, ReferenceError, RuntimeError):
        pass


def register():
    _patch_playback_controls()
    _append_options()
    _redraw_time_headers()


def unregister():
    _remove_options()
    _restore_playback_controls()
    _redraw_time_headers()


__all__ = (
    "FBP_PLAYBACK_BUTTON_PREFS",
    "fbp_draw_playback_button_options",
    "fbp_hidden_playback_operators",
)
