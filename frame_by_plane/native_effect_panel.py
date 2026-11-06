"""Frame By Plane controls inside Blender's own modifier panels.

Every image effect, mask and mesh effect is a Geometry Nodes modifier on the
layer plane, and its settings are inputs of that modifier. What an input
cannot be (buttons such as Select Rig, Reset or Crop Alpha, colour ramps and
curves, lists such as Lattice poses and pins, the effect's own mask) is drawn
by a header-less child panel of Blender's Geometry Nodes modifier panel, so it
sits right under the inputs of the effect it belongs to. There is no separate
Frame By Plane section in the Modifiers tab any more.

The child panel reuses the regular effect drawing code. It records that
drawing first and replays only what the modifier does not show already: a
setting that is a modifier input is left out, and so is a row or a section
that is left empty by it.
"""

from __future__ import annotations

import time

import bpy
from bpy.types import Panel

from .registration import register_classes, unregister_classes
from .runtime import FBP_DATA_ERRORS, fbp_warn


# Blender's panel for every Geometry Nodes modifier ("MOD_PT_" + type name).
NODES_MODIFIER_PANEL = "MOD_PT_GeometryNodes"

_CONTAINERS = frozenset({"row", "column", "box", "split", "grid_flow", "column_flow"})
_PANELS = frozenset({"panel", "panel_prop"})
_PROPS = frozenset({
    "prop", "prop_enum", "props_enum", "prop_menu_enum", "prop_search",
    "prop_tabs_enum", "prop_with_popover", "prop_with_menu",
})
_OPERATORS = frozenset({"operator", "operator_menu_enum", "operator_menu_hold"})
# Calls that draw nothing to click: a container holding only these is a hint.
_PASSIVE = frozenset({"label", "separator", "separator_spacer", "context_pointer_set", "context_string_set"})
_ATTRIBUTE_DEFAULTS = {
    "enabled": True, "active": True, "alert": False, "active_default": False,
    "activate_init": False, "scale_x": 1.0, "scale_y": 1.0, "ui_units_x": 0.0,
    "ui_units_y": 0.0, "alignment": "EXPAND", "use_property_split": False,
    "use_property_decorate": False, "operator_context": "INVOKE_DEFAULT",
    "emboss": "NORMAL",
}
# Panel controls that are menu inputs of the modifier ("@" keys of its
# layer mapping), by the operator or menu the Frame By Plane panel draws.
_VIRTUAL_CONTROLS = {
    "@VARIANT": ("menu", "FBP_MT_effect_family_variants"),
    "@SOURCE": ("operator", "fbp.set_effect_input_source"),
    "@DEBUG": ("operator", "fbp.set_effect_debug_mode"),
    "@MASKOP": ("operator", "fbp.set_mask_stack_operation"),
}


def _geo():
    from . import geometry_nodes
    return geometry_nodes


class _OperatorStub:
    """Collects the properties set on an operator button while recording."""

    def __init__(self):
        object.__setattr__(self, "_values", {})

    def __setattr__(self, name, value):
        self._values[name] = value

    def __getattr__(self, name):
        try:
            return self._values[name]
        except KeyError:
            raise AttributeError(name) from None


class _Recorder:
    """Stands in for a ``UILayout`` and records what is drawn on it.

    ``hidden(method, args)`` tells which calls the modifier already covers;
    they are dropped and the container remembers that something was.
    """

    def __init__(self, hidden):
        object.__setattr__(self, "_hidden", hidden)
        object.__setattr__(self, "_ops", [])
        object.__setattr__(self, "_attrs", {})
        object.__setattr__(self, "_dropped", False)

    def __setattr__(self, name, value):
        self._attrs[name] = value
        self._ops.append(("attr", name, value))

    def __getattr__(self, name):
        attrs = self._attrs
        if name in attrs:
            return attrs[name]
        if name in _ATTRIBUTE_DEFAULTS:
            return _ATTRIBUTE_DEFAULTS[name]
        if name == "fbp_mark_section":
            return self._mark_section
        if name in _CONTAINERS:
            return lambda *args, **kwargs: self._container(name, args, kwargs)
        if name in _PANELS:
            return lambda *args, **kwargs: self._panel(name, args, kwargs)
        return lambda *args, **kwargs: self._call(name, args, kwargs)

    def _mark_section(self):
        self._ops.append(("section",))

    def _container(self, name, args, kwargs):
        child = _Recorder(self._hidden)
        self._ops.append(("layout", name, args, kwargs, child))
        return child

    def _panel(self, name, args, kwargs):
        header, body = _Recorder(self._hidden), _Recorder(self._hidden)
        self._ops.append(("panel", name, args, kwargs, header, body))
        return header, body

    def _call(self, name, args, kwargs):
        stub = _OperatorStub() if name in _OPERATORS else None
        if self._hidden(name, args):
            object.__setattr__(self, "_dropped", True)
            return stub
        self._ops.append(("call", name, args, kwargs, stub))
        return stub


def _prune(recorder):
    """Return ``(ops, has_content, drop)`` for one recorded layout.

    A section (from ``section_header``) stays only when something clickable
    is left in it. A container with only labels stays as a hint, unless a
    setting was taken out of it: then the labels described that setting.
    """
    segments = [[]]
    for op in recorder._ops:
        if op[0] == "section":
            segments.append([])
        segments[-1].append(op)
    result, has_content, dropped = [], False, recorder._dropped
    for index, segment in enumerate(segments):
        kept, segment_content = [], False
        for op in segment:
            kind = op[0]
            if kind == "call":
                kept.append(op)
                segment_content = segment_content or op[1] not in _PASSIVE
            elif kind == "layout":
                ops, content, drop = _prune(op[4])
                if drop:
                    dropped = True
                    continue
                kept.append(op[:4] + (ops,))
                segment_content = segment_content or content
            elif kind == "panel":
                header, header_content, header_drop = _prune(op[4])
                body, body_content, _body_drop = _prune(op[5])
                if not (header_content or body_content):
                    dropped = dropped or header_drop or _body_drop
                    continue
                kept.append(op[:4] + (header, body))
                segment_content = True
            else:
                kept.append(op)
        if index == 0 or segment_content:
            result.extend(kept)
            has_content = has_content or segment_content
    return result, has_content, (not has_content and dropped)


def _replay(layout, ops):
    for op in ops:
        kind = op[0]
        if kind == "attr":
            try:
                setattr(layout, op[1], op[2])
            except (AttributeError, TypeError, ValueError):
                pass
        elif kind == "layout":
            _replay(getattr(layout, op[1])(*op[2], **op[3]), op[4])
        elif kind == "panel":
            header, body = getattr(layout, op[1])(*op[2], **op[3])
            _replay(header, op[4])
            if body is not None:
                _replay(body, op[5])
        elif kind == "call":
            result = getattr(layout, op[1])(*op[2], **op[3])
            stub = op[4]
            if stub is not None and result is not None:
                for name, value in stub._values.items():
                    setattr(result, name, value)


def _covered_settings(modifier, effect_id):
    """Layer settings and panel controls the modifier shows as inputs."""
    group = getattr(modifier, "node_group", None)
    if group is None:
        return frozenset()
    from .effect_shells import fbp_shell_covered_settings
    covered = set(fbp_shell_covered_settings(group))
    definition = _geo().fbp_effect_definition(effect_id) or {}
    if str(definition.get("kind", "") or "") == "GEOMETRY":
        covered.update((definition.get("property_map", {}) or {}).keys())
    return frozenset(covered)


def _hidden_test(rig, effect_id, instance_id, covered):
    geo = _geo()
    hidden_calls = {
        _VIRTUAL_CONTROLS[key] for key in covered if key in _VIRTUAL_CONTROLS
    }
    channel_key = (effect_id, str(instance_id or ""))

    def is_covered(owner, prop_name):
        prop_name = str(prop_name or "")
        if owner is rig:
            return prop_name in covered
        try:
            identity = geo._fbp_effect_instance_channel_identity(owner)[:2]
        except (AttributeError, *FBP_DATA_ERRORS):
            return False
        if identity != channel_key:
            return False
        mapped = str(getattr(owner, "property_name", "") or "")
        return mapped in covered and prop_name == geo._fbp_instance_channel_value_attr(owner)

    def hidden(name, args):
        if name in _PROPS:
            return len(args) >= 2 and is_covered(args[0], args[1])
        if name in _OPERATORS:
            return bool(args) and ("operator", str(args[0])) in hidden_calls
        if name == "menu":
            return bool(args) and ("menu", str(args[0])) in hidden_calls
        return False

    return hidden


def _modifier_effect(context, modifier):
    """Return ``(rig, effect_id, instance_id)`` for a Frame By Plane modifier."""
    from .native_modifiers import _layer_plane, fbp_native_modifier_token
    rig, plane = _layer_plane(getattr(context, "object", None))
    if rig is None or plane is None or getattr(modifier, "id_data", None) != plane:
        return None, "", ""
    geo = _geo()
    if geo._fbp_mixed_shader_stage_token(modifier):
        # Internal material stage: its effect has its own shell row.
        return None, "", ""
    token = fbp_native_modifier_token(rig, modifier)
    if not token:
        return None, "", ""
    effect_id, instance_id = geo._fbp_effect_ref_parts(token)
    if not geo.fbp_effect_definition(effect_id):
        return None, "", ""
    return rig, effect_id, instance_id


_ITEMS_SYNCED = {}
_ITEMS_SYNC_INTERVAL = 0.25


def _sync_effect_items(geo, rig):
    """Keep the layer's effect list in step, once per redraw for all panels.

    The Frame By Plane section used to schedule this while drawing; every
    modifier panel draws now, so one call per layer and redraw is enough.
    """
    key = str(getattr(rig, "name_full", "") or "")
    now = time.monotonic()
    if now - _ITEMS_SYNCED.get(key, -1.0) < _ITEMS_SYNC_INTERVAL:
        return
    _ITEMS_SYNCED[key] = now
    geo.fbp_schedule_effect_items_sync(rig, [rig])


def fbp_draw_native_effect_controls(layout, context, modifier):
    """Draw what a Frame By Plane modifier cannot show as an input."""
    rig, effect_id, instance_id = _modifier_effect(context, modifier)
    if rig is None:
        return False
    geo = _geo()
    _sync_effect_items(geo, rig)
    recorder = _Recorder(_hidden_test(rig, effect_id, instance_id, _covered_settings(modifier, effect_id)))
    geo.fbp_draw_effect_settings(
        recorder, rig, effect_id, context=context, instance_id=instance_id, native=True,
    )
    geo.fbp_draw_effect_mask_panel(recorder, context, (rig,), rig, effect_id, instance_id)
    definition = geo.fbp_effect_definition(effect_id) or {}
    if str(definition.get("category", "") or "") == "MASK":
        from .mask_stack import draw_mask_source_library_ui
        draw_mask_source_library_ui(recorder, context, [rig])
    ops, has_content, _drop = _prune(recorder)
    if not has_content:
        return False
    column = layout.column(align=False)
    column.use_property_split = False
    column.use_property_decorate = False
    _replay(column, ops)
    return True


class FBP_PT_NativeEffectControls(Panel):
    """Frame By Plane buttons and editors under one effect's modifier inputs."""

    bl_label = "Frame By Plane"
    bl_idname = "FBP_PT_native_effect_controls"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "modifier"
    bl_parent_id = NODES_MODIFIER_PANEL
    # Without a header the panel cannot be collapsed: its controls read as
    # the last rows of the modifier itself.
    bl_options = {"HIDE_HEADER"}

    @classmethod
    def poll(cls, context):
        # The modifier is only known in draw(): poll filters by object.
        from .native_modifiers import _layer_plane
        _rig, plane = _layer_plane(getattr(context, "object", None))
        return plane is not None and plane == getattr(context, "object", None)

    def draw(self, context):
        modifier = getattr(self, "custom_data", None)
        if modifier is None or getattr(modifier, "type", "") != "NODES":
            return
        try:
            fbp_draw_native_effect_controls(self.layout, context, modifier)
        except (ImportError, *FBP_DATA_ERRORS) as exc:
            fbp_warn("Could not draw Frame By Plane controls in a modifier panel", exc)


classes = (FBP_PT_NativeEffectControls,)


def register():
    if bool(getattr(bpy.app, "background", False)):
        return
    try:
        register_classes(classes)
    except (RuntimeError, ValueError) as exc:
        # A Blender without the Geometry Nodes modifier panel keeps working;
        # the effects just have no extra buttons.
        fbp_warn("Could not add Frame By Plane controls to modifier panels", exc)


def unregister():
    if bool(getattr(bpy.app, "background", False)):
        return
    unregister_classes(classes)
