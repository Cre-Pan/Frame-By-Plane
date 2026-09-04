"""Dual Stroke/Fill vertex-color workflow for Blender 5.2 Grease Pencil.

Blender 5.2 stores point vertex colors and curve fill colors separately, but
its Draw and Vertex Paint brushes expose one active paint color. This module
gives the native primary/secondary colors stable Stroke/Fill meanings in the
Tool Header, preserves Blender's X shortcut, provides a live Shift+X sampler,
and adds selection-aware RGBA editing.
"""

from __future__ import annotations

from array import array
import time

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, FloatVectorProperty, IntProperty, PointerProperty
from bpy.types import Operator, Panel, PropertyGroup

from .registration import (
    append_handler_once,
    register_classes,
    remove_handlers_by_name,
    unregister_classes,
    unregister_type_properties,
)
from .runtime import FBP_DATA_ERRORS, fbp_warn_once


_STATE_PROPERTY = "fbp_gp_vertex_color_state"
_STATE_GUARD = 0
_HEADER_REGISTERED = False
_NATIVE_UI_PATCHED = False
_MISSING = object()
_NATIVE_UI = {}
_ADDON_KEYMAPS = []
_EDIT_UNDO_PENDING = False
_EDIT_UNDO_DELAY = 0.35
_EDIT_SYNC_INTERVAL = 0.05
_EDIT_SYNC_DEBOUNCE = 0.06
_SAMPLE_INTERVAL = 1.0 / 60.0
_COLOR_DECODE_CACHE_LIMIT = 256
_RUNTIME = {
    "target": 0,
    "owner": 0,
    "context_mode": "",
    "brush_kind": "",
    "target_mode": "",
    "expected_primary": None,
    "expected_secondary": None,
    "edit_signature": None,
    "edit_dirty": True,
    "edit_last_sync": 0.0,
    "edit_last_dirty": 0.0,
    "edit_suppress_dirty_until": 0.0,
    "edit_point_targets": (),
    "edit_point_count": 0,
    "edit_fill_targets": (),
    "edit_fill_count": 0,
    "stroke_swatches": (),
    "fill_swatches": (),
    "stroke_unique": 0,
    "fill_unique": 0,
    "draw_watch_initialized": False,
    "draw_watch_object": 0,
    "draw_drawing_pointer": 0,
    "draw_curve_count": 0,
    "edit_undo_label": "Grease Pencil Color",
}


def _rgba(value, default=(0.0, 0.0, 0.0, 1.0)):
    try:
        values = tuple(float(component) for component in value)
    except FBP_DATA_ERRORS:
        values = ()
    if len(values) < 3:
        return tuple(default)
    alpha = values[3] if len(values) > 3 else 1.0
    return (
        min(1.0, max(0.0, values[0])),
        min(1.0, max(0.0, values[1])),
        min(1.0, max(0.0, values[2])),
        min(1.0, max(0.0, alpha)),
    )


def _color_key(value):
    return tuple(round(component, 5) for component in _rgba(value))


_COLOR_FINGERPRINT_MASK = (1 << 64) - 1


def _color_token(key):
    """Return a stable compact token for a normalized RGBA key."""
    token = 1469598103934665603
    for component in key:
        token ^= int(round(float(component) * 100000.0))
        token = (token * 1099511628211) & _COLOR_FINGERPRINT_MASK
    return token


def _fingerprint_add(first, second, key):
    token = _color_token(key)
    return (
        (first + token) & _COLOR_FINGERPRINT_MASK,
        (second + ((token * token) & _COLOR_FINGERPRINT_MASK)) & _COLOR_FINGERPRINT_MASK,
    )


def _colors_close(first, second, epsilon=1.0e-5):
    if first is None or second is None:
        return False
    try:
        return all(abs(float(a) - float(b)) <= epsilon for a, b in zip(first, second))
    except FBP_DATA_ERRORS:
        return False


def _active_gp_object(context=None):
    context = context or getattr(bpy, "context", None)
    obj = getattr(context, "object", None) if context is not None else None
    try:
        return obj if obj is not None and obj.type == "GREASEPENCIL" else None
    except FBP_DATA_ERRORS:
        return None


def _context_mode(context=None):
    context = context or getattr(bpy, "context", None)
    try:
        return str(getattr(context, "mode", "") or "")
    except FBP_DATA_ERRORS:
        return ""


def _state(context=None):
    obj = _active_gp_object(context)
    return getattr(obj, _STATE_PROPERTY, None) if obj is not None else None


def _brush_context(context=None):
    context = context or getattr(bpy, "context", None)
    try:
        tool_settings = context.scene.tool_settings
        paint = tool_settings.gpencil_vertex_paint
        brush = paint.brush
        if brush is None:
            return None, None, None, None
        unified = paint.unified_paint_settings
        owner = unified if bool(getattr(unified, "use_unified_color", False)) else brush
        gp_settings = getattr(brush, "gpencil_settings", None)
        return paint, brush, owner, gp_settings
    except FBP_DATA_ERRORS:
        return None, None, None, None


def _draw_brush_context(context=None):
    context = context or getattr(bpy, "context", None)
    try:
        paint = context.scene.tool_settings.gpencil_paint
        brush = paint.brush
        if brush is None:
            return None, None, None, None
        gp_settings = getattr(brush, "gpencil_settings", None)
        return paint, brush, brush, gp_settings
    except FBP_DATA_ERRORS:
        return None, None, None, None


def _set_state_value(state, name, value):
    global _STATE_GUARD
    if state is None:
        return False
    clean = _rgba(value)
    incremented = False
    try:
        current = _rgba(getattr(state, name))
        if _colors_close(current, clean):
            return False
        _STATE_GUARD += 1
        incremented = True
        setattr(state, name, clean)
        return True
    except FBP_DATA_ERRORS:
        return False
    finally:
        if incremented:
            _STATE_GUARD = max(0, _STATE_GUARD - 1)


def _set_state_scalar(state, name, value):
    global _STATE_GUARD
    if state is None:
        return False
    incremented = False
    try:
        if getattr(state, name) == value:
            return False
        _STATE_GUARD += 1
        incremented = True
        setattr(state, name, value)
        return True
    except FBP_DATA_ERRORS:
        return False
    finally:
        if incremented:
            _STATE_GUARD = max(0, _STATE_GUARD - 1)


def _assign_brush_color(owner, name, color):
    if owner is None:
        return False
    try:
        rgb = tuple(_rgba(color)[:3])
        current = tuple(float(component) for component in getattr(owner, name))
        if _colors_close(current, rgb):
            return False
        setattr(owner, name, rgb)
        return True
    except FBP_DATA_ERRORS:
        return False


def _target_mode(gp_settings, property_name):
    try:
        value = str(getattr(gp_settings, property_name, "STROKE") or "STROKE").upper()
    except FBP_DATA_ERRORS:
        value = "STROKE"
    return value if value in {"STROKE", "FILL", "BOTH"} else "STROKE"


def _vertex_mode(gp_settings):
    return _target_mode(gp_settings, "vertex_mode")


def _draw_mode(gp_settings):
    return _target_mode(gp_settings, "stroke_type")


def _semantic_brush_context(context=None):
    context = context or getattr(bpy, "context", None)
    context_mode = _context_mode(context)
    if context_mode == "VERTEX_GREASE_PENCIL":
        paint, brush, owner, gp_settings = _brush_context(context)
        return "VERTEX", paint, brush, owner, gp_settings, _vertex_mode(gp_settings)
    if context_mode == "PAINT_GREASE_PENCIL":
        paint, brush, owner, gp_settings = _draw_brush_context(context)
        return "DRAW", paint, brush, owner, gp_settings, _draw_mode(gp_settings)
    return "", None, None, None, None, "STROKE"


def _canonical_brush_colors(state, owner, mode):
    stroke = _rgba(getattr(state, "stroke_color", (0.0, 0.0, 0.0, 1.0)))
    fill = _rgba(getattr(state, "fill_color", (1.0, 1.0, 1.0, 1.0)))
    if mode == "FILL":
        primary, secondary = fill, stroke
    else:
        primary, secondary = stroke, fill
    _assign_brush_color(owner, "color", primary)
    _assign_brush_color(owner, "secondary_color", secondary)
    _RUNTIME["expected_primary"] = tuple(primary[:3])
    _RUNTIME["expected_secondary"] = tuple(secondary[:3])


def _initialize_paint_state(context, state, obj, owner, mode, brush_kind):
    try:
        primary = _rgba(tuple(owner.color) + (1.0,))
    except FBP_DATA_ERRORS:
        primary = (0.0, 0.0, 0.0, 1.0)
    try:
        secondary = _rgba(tuple(owner.secondary_color) + (1.0,))
    except FBP_DATA_ERRORS:
        secondary = (1.0, 1.0, 1.0, 1.0)
    if mode == "FILL":
        stroke, fill = secondary, primary
    else:
        stroke, fill = primary, secondary
    _set_state_value(state, "stroke_color", stroke)
    _set_state_value(state, "fill_color", fill)
    _set_state_scalar(state, "stroke_available", True)
    _set_state_scalar(state, "fill_available", True)
    _set_state_scalar(state, "stroke_mixed", False)
    _set_state_scalar(state, "fill_mixed", False)
    _RUNTIME.update(
        target=int(obj.as_pointer()),
        owner=int(owner.as_pointer()),
        context_mode=_context_mode(context),
        brush_kind=str(brush_kind or ""),
        target_mode=mode,
        edit_signature=None,
        stroke_swatches=(),
        fill_swatches=(),
        stroke_unique=0,
        fill_unique=0,
    )
    _canonical_brush_colors(state, owner, mode)


def _sync_paint_state(context, brush_kind, owner, gp_settings, mode, *, force=False):
    """Synchronize native primary/secondary colors with Stroke/Fill semantics.

    Blender's native X shortcut swaps both brush colors.  Shift+X changes only
    the primary color; a non-swap primary change is therefore always captured
    into Stroke, exactly as requested, even while the Fill mode is active.
    """
    obj = _active_gp_object(context)
    state = _state(context)
    if obj is None or state is None or owner is None or gp_settings is None:
        return False
    pointer = int(obj.as_pointer())
    try:
        owner_pointer = int(owner.as_pointer())
    except FBP_DATA_ERRORS:
        owner_pointer = id(owner)
    context_mode = _context_mode(context)
    if _RUNTIME["target"] != pointer:
        _initialize_paint_state(context, state, obj, owner, mode, brush_kind)
        return True

    if _RUNTIME["context_mode"] != context_mode:
        _RUNTIME["context_mode"] = context_mode
        _RUNTIME["owner"] = owner_pointer
        _RUNTIME["brush_kind"] = brush_kind
        _RUNTIME["target_mode"] = mode
        _canonical_brush_colors(state, owner, mode)
        return True

    if _RUNTIME["owner"] != owner_pointer or _RUNTIME["brush_kind"] != brush_kind:
        _initialize_paint_state(context, state, obj, owner, mode, brush_kind)
        return True

    if _RUNTIME["target_mode"] != mode:
        _RUNTIME["target_mode"] = mode
        _canonical_brush_colors(state, owner, mode)
        return True

    try:
        primary = tuple(float(component) for component in owner.color)
        secondary = tuple(float(component) for component in owner.secondary_color)
    except FBP_DATA_ERRORS:
        return False
    expected_primary = _RUNTIME.get("expected_primary")
    expected_secondary = _RUNTIME.get("expected_secondary")
    primary_changed = not _colors_close(primary, expected_primary)
    secondary_changed = not _colors_close(secondary, expected_secondary)

    if primary_changed or secondary_changed or force:
        is_native_swap = bool(
            primary_changed
            and secondary_changed
            and _colors_close(primary, expected_secondary)
            and _colors_close(secondary, expected_primary)
        )
        if is_native_swap:
            old_stroke = _rgba(state.stroke_color)
            old_fill = _rgba(state.fill_color)
            _set_state_value(state, "stroke_color", old_fill)
            _set_state_value(state, "fill_color", old_stroke)
        else:
            # Native sample_color modifies primary only. It is intentionally
            # assigned to Stroke regardless of the active target mode.
            if primary_changed:
                _set_state_value(state, "stroke_color", tuple(primary) + (state.stroke_color[3],))
            if secondary_changed:
                target = "stroke_color" if mode == "FILL" else "fill_color"
                alpha = getattr(state, target)[3]
                _set_state_value(state, target, tuple(secondary) + (alpha,))
        _canonical_brush_colors(state, owner, mode)
        if is_native_swap:
            # Brush colors are not a reliable part of Grease Pencil's stroke
            # undo snapshot. Store the synchronized semantic state as its own
            # step, so Undo Stroke does not also undo the visible swap.
            _push_edit_color_undo("Swap Grease Pencil Stroke / Fill Colors")
        return True
    return False


def _sync_vertex_state(context=None, *, force=False):
    context = context or getattr(bpy, "context", None)
    _paint, _brush, owner, gp_settings = _brush_context(context)
    return _sync_paint_state(
        context,
        "VERTEX",
        owner,
        gp_settings,
        _vertex_mode(gp_settings),
        force=force,
    )


def _sync_draw_state(context=None, *, force=False):
    context = context or getattr(bpy, "context", None)
    _paint, _brush, owner, gp_settings = _draw_brush_context(context)
    return _sync_paint_state(
        context,
        "DRAW",
        owner,
        gp_settings,
        _draw_mode(gp_settings),
        force=force,
    )


def _draw_uses_vertex_color(context, gp_settings):
    try:
        paint = context.scene.tool_settings.gpencil_paint
        if bool(gp_settings.pin_draw_mode):
            return str(gp_settings.brush_draw_mode) == "VERTEXCOLOR"
        return str(paint.color_mode) == "VERTEXCOLOR"
    except FBP_DATA_ERRORS:
        return False


def _reset_draw_both_tracking():
    _RUNTIME.update(
        draw_watch_initialized=False,
        draw_watch_object=0,
        draw_drawing_pointer=0,
        draw_curve_count=0,
    )


def _active_draw_drawing(obj):
    try:
        layer = obj.data.layers.active
        frame = layer.current_frame() if layer is not None else None
        return frame.drawing if frame is not None else None
    except FBP_DATA_ERRORS:
        return None


def _new_draw_curve_indices(previous_count, curve_count, draw_on_back):
    added = max(0, int(curve_count) - int(previous_count))
    if not added:
        return range(0)
    if draw_on_back:
        return range(added)
    return range(int(previous_count), int(curve_count))


def _sync_draw_both_fill(context=None):
    """Apply Frame By Plane settings to newly drawn curves.

    Blender 5.2 initializes both point and curve colors from ``brush.color``.
    The native stroke stays untouched; only the fill attribute of newly added
    Both curves is replaced. The explicit Close Gap toggle independently
    owns the native ``cyclic`` flag for every draw mode.
    """
    context = context or getattr(bpy, "context", None)
    if _context_mode(context) != "PAINT_GREASE_PENCIL":
        _reset_draw_both_tracking()
        return 0
    obj = _active_gp_object(context)
    state = _state(context)
    _paint, brush, _owner, gp_settings = _draw_brush_context(context)
    if (
        obj is None
        or state is None
        or brush is None
        or gp_settings is None
    ):
        _reset_draw_both_tracking()
        return 0
    use_dual_fill = bool(
        _draw_mode(gp_settings) == "BOTH"
        and _draw_uses_vertex_color(context, gp_settings)
    )

    object_pointer = int(obj.as_pointer())
    drawing = _active_draw_drawing(obj)
    try:
        drawing_pointer = int(drawing.as_pointer()) if drawing is not None else 0
        curve_count = len(drawing.strokes) if drawing is not None else 0
    except FBP_DATA_ERRORS:
        return 0

    if (
        not _RUNTIME.get("draw_watch_initialized")
        or _RUNTIME.get("draw_watch_object") != object_pointer
    ):
        _RUNTIME.update(
            draw_watch_initialized=True,
            draw_watch_object=object_pointer,
            draw_drawing_pointer=drawing_pointer,
            draw_curve_count=curve_count,
        )
        return 0

    previous_pointer = int(_RUNTIME.get("draw_drawing_pointer", 0) or 0)
    previous_count = int(_RUNTIME.get("draw_curve_count", 0) or 0)
    if drawing_pointer != previous_pointer:
        # A zero pointer becoming a real drawing means the native operator just
        # created the first frame. Other pointer changes are ordinary frame or
        # layer switches and must not recolor existing curves.
        created_first_drawing = previous_pointer == 0 and previous_count == 0
        previous_count = 0 if created_first_drawing else curve_count

    _RUNTIME["draw_drawing_pointer"] = drawing_pointer
    _RUNTIME["draw_curve_count"] = curve_count
    if drawing is None or curve_count <= previous_count:
        return 0

    try:
        draw_on_back = bool(context.scene.tool_settings.use_gpencil_draw_onback)
    except FBP_DATA_ERRORS:
        draw_on_back = False
    indices = tuple(_new_draw_curve_indices(previous_count, curve_count, draw_on_back))
    clean_fill = _rgba(state.fill_color)
    close_stroke = bool(state.close_strokes)
    changed = 0
    for curve_index in indices:
        try:
            stroke = drawing.strokes[curve_index]
            curve_changed = False
            if bool(stroke.cyclic) != close_stroke:
                stroke.cyclic = close_stroke
                curve_changed = True
            if use_dual_fill and not _colors_close(stroke.fill_color, clean_fill):
                stroke.fill_color = clean_fill
                curve_changed = True
            if curve_changed:
                changed += 1
        except FBP_DATA_ERRORS + (IndexError,):
            continue
    if changed:
        _tag_gp_color_update(obj)
    return changed


def _tag_view3d_redraw():
    screen = getattr(getattr(bpy, "context", None), "screen", None)
    for area in tuple(getattr(screen, "areas", ()) or ()):
        try:
            if area.type == "VIEW_3D":
                area.tag_redraw()
        except FBP_DATA_ERRORS:
            continue


def fbp_gp_brush_color_timer():
    """Keep the custom swatches in step with Blender's native X/Shift+X tools.

    Native brush-color swaps do not consistently publish an RNA message-bus
    notification in Grease Pencil paint modes.  Polling only the two tiny RGB
    vectors is both reliable and cheap: 30 Hz while a relevant paint mode is
    active, throttled to 0.75 s everywhere else.
    """
    context = getattr(bpy, "context", None)
    mode = _context_mode(context)
    changed = False
    if mode == "PAINT_GREASE_PENCIL":
        changed = _sync_draw_state(context)
        changed = bool(_sync_draw_both_fill(context)) or changed
    elif mode == "VERTEX_GREASE_PENCIL":
        changed = _sync_vertex_state(context)
    elif mode == "EDIT_GREASE_PENCIL":
        changed = _sync_edit_state(context)
    if changed:
        _tag_view3d_redraw()
    if mode in {"PAINT_GREASE_PENCIL", "VERTEX_GREASE_PENCIL"}:
        return 1.0 / 30.0
    if mode == "EDIT_GREASE_PENCIL":
        return _EDIT_SYNC_INTERVAL
    return 0.75


def _register_brush_color_timer():
    try:
        if not bpy.app.timers.is_registered(fbp_gp_brush_color_timer):
            bpy.app.timers.register(
                fbp_gp_brush_color_timer,
                first_interval=0.0,
                persistent=True,
            )
        return True
    except FBP_DATA_ERRORS as exc:
        fbp_warn_once(
            "gp_vertex_colors.timer",
            "Could not start Grease Pencil brush color synchronization",
            exc,
        )
        return False


def _unregister_brush_color_timer():
    try:
        if bpy.app.timers.is_registered(fbp_gp_brush_color_timer):
            bpy.app.timers.unregister(fbp_gp_brush_color_timer)
    except FBP_DATA_ERRORS:
        pass


def _iter_edit_drawings(context, obj):
    data = getattr(obj, "data", None)
    layers = getattr(data, "layers", ()) if data is not None else ()
    try:
        multi_frame = bool(context.scene.tool_settings.use_grease_pencil_multi_frame_editing)
    except FBP_DATA_ERRORS:
        multi_frame = False
    seen = set()
    for layer in layers:
        try:
            if bool(layer.hide) or bool(layer.lock):
                continue
        except FBP_DATA_ERRORS:
            pass
        frames = []
        try:
            current = layer.current_frame()
        except FBP_DATA_ERRORS:
            current = None
        if current is not None:
            frames.append(current)
        if multi_frame:
            try:
                frames.extend(frame for frame in layer.frames if bool(getattr(frame, "select", False)))
            except FBP_DATA_ERRORS:
                pass
        for frame in frames:
            drawing = getattr(frame, "drawing", None)
            if drawing is None:
                continue
            try:
                key = int(drawing.as_pointer())
            except FBP_DATA_ERRORS:
                key = id(drawing)
            if key in seen:
                continue
            seen.add(key)
            yield drawing


def _drawing_color_attribute(drawing, name):
    """Read a POINT/CURVE color attribute in one RNA transfer.

    Grease Pencil omits default-zero color attributes until a non-default
    value exists. ``None`` therefore represents an all-transparent-black span.
    """
    try:
        attribute = drawing.attributes.get(name)
        if attribute is None or str(attribute.data_type) != "FLOAT_COLOR":
            return None
        values = array("f", [0.0]) * (len(attribute.data) * 4)
        attribute.data.foreach_get("color", values)
        return values
    except FBP_DATA_ERRORS:
        return _MISSING


def _attribute_color_summary(values, index, cache):
    if values is None:
        return (0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0)
    offset = int(index) * 4
    try:
        raw = (
            values[offset],
            values[offset + 1],
            values[offset + 2],
            values[offset + 3],
        )
    except (IndexError, OverflowError):
        return (0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0)
    summary = cache.get(raw)
    if summary is None:
        color = _rgba(raw)
        summary = (color, _color_key(color))
        if len(cache) < _COLOR_DECODE_CACHE_LIMIT:
            cache[raw] = summary
    return summary


def _record_color(color, key, unique_keys, swatches, fingerprint):
    if key in unique_keys:
        return fingerprint
    unique_keys.add(key)
    if len(swatches) < 8:
        swatches.append((color, 1))
    return _fingerprint_add(fingerprint[0], fingerprint[1], key)


def _edit_select_mode(context):
    try:
        return str(context.scene.tool_settings.gpencil_selectmode_edit)
    except FBP_DATA_ERRORS:
        return "POINT"


def _drawing_selection_values(drawing, domain):
    """Read Blender's hidden Edit selection attribute in one native call.

    An absent ``.selection`` attribute is Blender's compact representation for
    a fully selected drawing. Unexpected layouts use the safe RNA fallback.
    """
    try:
        attribute = drawing.attributes.get(".selection")
        if attribute is None:
            return None
        if str(attribute.data_type) != "BOOLEAN" or str(attribute.domain) != domain:
            return _MISSING
        values = array("b", [0]) * len(attribute.data)
        attribute.data.foreach_get("value", values)
        return values
    except FBP_DATA_ERRORS:
        return _MISSING


def _selected_color_snapshot(context, obj):
    stroke_keys = set()
    fill_keys = set()
    stroke_values = []
    fill_values = []
    stroke_fingerprint = (0, 0)
    fill_fingerprint = (0, 0)
    point_targets = []
    fill_targets = []
    point_count = 0
    curve_count = 0
    whole_stroke_selection = _edit_select_mode(context) == "STROKE"
    for drawing in _iter_edit_drawings(context, obj):
        try:
            strokes = drawing.strokes
            drawing_curve_count = len(strokes)
        except FBP_DATA_ERRORS:
            continue
        drawing_targets = []
        drawing_point_count = 0
        point_offset = 0
        selection_values = _drawing_selection_values(
            drawing,
            "CURVE" if whole_stroke_selection else "POINT",
        )
        for curve_index, stroke in enumerate(strokes):
            try:
                points = stroke.points
                stroke_point_count = len(points)
            except FBP_DATA_ERRORS:
                continue
            stroke_offset = point_offset
            point_offset += stroke_point_count
            if whole_stroke_selection:
                if selection_values is None:
                    selected_count = stroke_point_count
                elif selection_values is not _MISSING:
                    try:
                        selected_count = stroke_point_count if selection_values[curve_index] else 0
                    except (IndexError, OverflowError):
                        selected_count = 0
                else:
                    try:
                        selected_count = (
                            stroke_point_count if stroke_point_count and points[0].select else 0
                        )
                    except FBP_DATA_ERRORS:
                        selected_count = 0
                if not selected_count:
                    continue
                selector = None
            else:
                if selection_values is None:
                    selector = None
                    selected_count = stroke_point_count
                else:
                    if selection_values is _MISSING:
                        selected_indices = []
                        for local_index, point in enumerate(points):
                            try:
                                if bool(point.select):
                                    selected_indices.append(local_index)
                            except FBP_DATA_ERRORS:
                                continue
                    else:
                        selected_indices = [
                            local_index
                            for local_index in range(stroke_point_count)
                            if selection_values[stroke_offset + local_index]
                        ]
                    if not selected_indices:
                        continue
                    selector = (
                        None if len(selected_indices) == stroke_point_count else tuple(selected_indices)
                    )
                    selected_count = len(selected_indices)
            if not selected_count:
                continue
            drawing_targets.append(
                (stroke, selector, stroke_offset, curve_index, selected_count)
            )
            drawing_point_count += selected_count

        if not drawing_targets:
            continue
        use_point_bulk = point_offset <= 4096 or drawing_point_count * 8 >= point_offset
        use_curve_bulk = drawing_curve_count <= 4096 or len(drawing_targets) * 8 >= drawing_curve_count
        point_colors = (
            _drawing_color_attribute(drawing, "vertex_color") if use_point_bulk else _MISSING
        )
        curve_colors = (
            _drawing_color_attribute(drawing, "fill_color") if use_curve_bulk else _MISSING
        )
        point_color_cache = {}
        curve_color_cache = {}

        for stroke, selector, stroke_offset, curve_index, selected_count in drawing_targets:
            curve_count += 1
            point_count += selected_count
            try:
                if point_colors is _MISSING:
                    points = stroke.points
                    indices = range(len(points)) if selector is None else selector
                else:
                    points = None
                    indices = range(selected_count) if selector is None else selector
                for local_index in indices:
                    if point_colors is _MISSING:
                        color = _rgba(points[local_index].vertex_color)
                        key = _color_key(color)
                    else:
                        color, key = _attribute_color_summary(
                            point_colors,
                            stroke_offset + local_index,
                            point_color_cache,
                        )
                    stroke_fingerprint = _record_color(
                        color,
                        key,
                        stroke_keys,
                        stroke_values,
                        stroke_fingerprint,
                    )
            except FBP_DATA_ERRORS + (IndexError,):
                continue
            if curve_colors is _MISSING:
                try:
                    color = _rgba(stroke.fill_color)
                    key = _color_key(color)
                except FBP_DATA_ERRORS:
                    continue
            else:
                color, key = _attribute_color_summary(curve_colors, curve_index, curve_color_cache)
            fill_fingerprint = _record_color(
                color,
                key,
                fill_keys,
                fill_values,
                fill_fingerprint,
            )
        point_targets.append(
            (
                drawing,
                point_offset,
                drawing_point_count,
                tuple(
                    (stroke, selector, stroke_offset, selected_count)
                    for stroke, selector, stroke_offset, _curve_index, selected_count in drawing_targets
                ),
            )
        )
        fill_targets.append(
            (
                drawing,
                drawing_curve_count,
                len(drawing_targets),
                tuple(
                    (stroke, curve_index)
                    for stroke, _selector, _offset, curve_index, _count in drawing_targets
                ),
            )
        )

    signature = (
        int(obj.as_pointer()),
        point_count,
        curve_count,
        len(stroke_keys),
        stroke_fingerprint,
        tuple(_color_key(color) for color, _count in stroke_values),
        len(fill_keys),
        fill_fingerprint,
        tuple(_color_key(color) for color, _count in fill_values),
    )
    return (
        signature,
        tuple(stroke_values),
        tuple(fill_values),
        len(stroke_keys),
        len(fill_keys),
        point_count,
        curve_count,
        tuple(point_targets),
        tuple(fill_targets),
    )


def _sync_edit_state(context=None, *, force=False):
    context = context or getattr(bpy, "context", None)
    obj = _active_gp_object(context)
    state = _state(context)
    if obj is None or state is None:
        return False
    now = time.perf_counter()
    if not force:
        if not bool(_RUNTIME.get("edit_dirty", True)):
            return False
        last_sync = float(_RUNTIME.get("edit_last_sync", 0.0) or 0.0)
        if now - last_sync < _EDIT_SYNC_INTERVAL:
            return False
        last_dirty = float(_RUNTIME.get("edit_last_dirty", 0.0) or 0.0)
        if now - last_dirty < _EDIT_SYNC_DEBOUNCE:
            return False
    pointer = int(obj.as_pointer())
    if _RUNTIME["target"] != pointer:
        _RUNTIME.update(
            target=pointer,
            owner=0,
            context_mode=_context_mode(context),
            brush_kind="",
            target_mode="",
            expected_primary=None,
            expected_secondary=None,
            edit_signature=None,
            edit_dirty=True,
            edit_point_targets=(),
            edit_point_count=0,
            edit_fill_targets=(),
            edit_fill_count=0,
        )
    snapshot = _selected_color_snapshot(context, obj)
    (
        signature,
        stroke_values,
        fill_values,
        stroke_unique,
        fill_unique,
        point_count,
        curve_count,
        point_targets,
        fill_targets,
    ) = snapshot
    _RUNTIME["edit_last_sync"] = now
    _RUNTIME["edit_dirty"] = False
    _RUNTIME["edit_point_targets"] = point_targets
    _RUNTIME["edit_point_count"] = point_count
    _RUNTIME["edit_fill_targets"] = fill_targets
    _RUNTIME["edit_fill_count"] = curve_count
    if not force and signature == _RUNTIME.get("edit_signature"):
        return False
    _RUNTIME["edit_signature"] = signature
    _RUNTIME["context_mode"] = _context_mode(context)
    _RUNTIME["stroke_swatches"] = stroke_values
    _RUNTIME["fill_swatches"] = fill_values
    _RUNTIME["stroke_unique"] = stroke_unique
    _RUNTIME["fill_unique"] = fill_unique
    _set_state_scalar(state, "selected_points", point_count)
    _set_state_scalar(state, "selected_curves", curve_count)
    _set_state_scalar(state, "stroke_available", bool(stroke_values))
    _set_state_scalar(state, "fill_available", bool(fill_values))
    _set_state_scalar(state, "stroke_mixed", stroke_unique > 1)
    _set_state_scalar(state, "fill_mixed", fill_unique > 1)
    if stroke_values:
        _set_state_value(state, "stroke_color", stroke_values[0][0])
    if fill_values:
        _set_state_value(state, "fill_color", fill_values[0][0])
    return True


def _tag_gp_color_update(obj):
    try:
        obj.data.update_tag()
    except FBP_DATA_ERRORS:
        pass
    try:
        obj.update_tag(refresh={"DATA"})
    except FBP_DATA_ERRORS:
        pass
    screen = getattr(getattr(bpy, "context", None), "screen", None)
    for area in tuple(getattr(screen, "areas", ()) or ()):
        try:
            if area.type == "VIEW_3D":
                area.tag_redraw()
        except FBP_DATA_ERRORS:
            continue


def _push_edit_color_undo(message):
    try:
        if bpy.ops.ed.undo_push.poll():
            return bpy.ops.ed.undo_push(message=message) == {"FINISHED"}
    except FBP_DATA_ERRORS:
        pass
    return False


def _commit_edit_color_undo():
    global _EDIT_UNDO_PENDING
    if not _EDIT_UNDO_PENDING:
        return None
    label = str(_RUNTIME.get("edit_undo_label") or "Grease Pencil Color")
    _push_edit_color_undo(label)
    _EDIT_UNDO_PENDING = False
    _RUNTIME["edit_dirty"] = True
    return None


def _cancel_edit_color_undo(*, keep_baseline=False):
    global _EDIT_UNDO_PENDING
    try:
        if bpy.app.timers.is_registered(_commit_edit_color_undo):
            bpy.app.timers.unregister(_commit_edit_color_undo)
    except FBP_DATA_ERRORS:
        pass
    if not keep_baseline:
        _EDIT_UNDO_PENDING = False


def _begin_edit_color_undo(target):
    global _EDIT_UNDO_PENDING
    if _EDIT_UNDO_PENDING:
        return True
    label = {
        "FILL": "Change Grease Pencil Fill Color",
        "CLOSE": "Change Grease Pencil Stroke Closure",
    }.get(target, "Change Grease Pencil Stroke Color")
    if not _push_edit_color_undo(f"Before {label}"):
        return False
    _RUNTIME["edit_undo_label"] = label
    _EDIT_UNDO_PENDING = True
    return True


def _schedule_edit_color_undo_commit():
    if not _EDIT_UNDO_PENDING:
        return
    try:
        if bpy.app.timers.is_registered(_commit_edit_color_undo):
            bpy.app.timers.unregister(_commit_edit_color_undo)
        bpy.app.timers.register(_commit_edit_color_undo, first_interval=_EDIT_UNDO_DELAY)
    except FBP_DATA_ERRORS:
        _commit_edit_color_undo()


def _ensure_drawing_color_attribute(drawing, name, domain):
    try:
        attribute = drawing.attributes.get(name)
        if attribute is None:
            attribute = drawing.attributes.new(name, "FLOAT_COLOR", domain)
        if str(attribute.data_type) != "FLOAT_COLOR" or str(attribute.domain) != domain:
            return None
        return attribute
    except FBP_DATA_ERRORS:
        return None


def _write_point_group_color(group, clean):
    """Bulk-write a dense point selection; return None for sparse fallback."""
    drawing, total_points, selected_count, batches = group
    if total_points > 4096 and selected_count * 8 < total_points:
        return None
    attribute = _ensure_drawing_color_attribute(drawing, "vertex_color", "POINT")
    if attribute is None:
        return None
    if selected_count == total_points:
        values = array("f", clean) * total_points
    else:
        values = _drawing_color_attribute(drawing, "vertex_color")
        if values is _MISSING:
            return None
        if values is None:
            values = array("f", [0.0]) * (total_points * 4)
        clean_values = array("f", clean)
        for _stroke, selector, stroke_offset, stroke_selected_count in batches:
            indices = range(stroke_selected_count) if selector is None else selector
            for local_index in indices:
                offset = (stroke_offset + local_index) * 4
                values[offset : offset + 4] = clean_values
    try:
        attribute.data.foreach_set("color", values)
        return selected_count
    except FBP_DATA_ERRORS:
        return None


def _write_fill_group_color(group, clean):
    """Bulk-write a dense curve selection; return None for sparse fallback."""
    drawing, total_curves, selected_count, batches = group
    if total_curves > 4096 and selected_count * 8 < total_curves:
        return None
    attribute = _ensure_drawing_color_attribute(drawing, "fill_color", "CURVE")
    if attribute is None:
        return None
    if selected_count == total_curves:
        values = array("f", clean) * total_curves
    else:
        values = _drawing_color_attribute(drawing, "fill_color")
        if values is _MISSING:
            return None
        if values is None:
            values = array("f", [0.0]) * (total_curves * 4)
        clean_values = array("f", clean)
        for _stroke, curve_index in batches:
            offset = curve_index * 4
            values[offset : offset + 4] = clean_values
    try:
        attribute.data.foreach_set("color", values)
        return selected_count
    except FBP_DATA_ERRORS:
        return None


def _apply_selected_color(context, target, color, *, record_undo=False):
    obj = _active_gp_object(context)
    if obj is None or _context_mode(context) != "EDIT_GREASE_PENCIL":
        return 0
    clean = _rgba(color)
    changed = 0
    undo_started = False
    undo_attempted = False
    now = time.perf_counter()
    pointer = int(obj.as_pointer())
    suppress_until = float(_RUNTIME.get("edit_suppress_dirty_until", 0.0) or 0.0)
    last_dirty = float(_RUNTIME.get("edit_last_dirty", 0.0) or 0.0)
    dirty_ready = bool(
        _RUNTIME.get("edit_dirty", True)
        and now >= suppress_until
        and now - last_dirty >= _EDIT_SYNC_DEBOUNCE
    )
    needs_refresh = bool(
        _RUNTIME.get("target") != pointer
        or _RUNTIME.get("context_mode") != "EDIT_GREASE_PENCIL"
        or _RUNTIME.get("edit_signature") is None
        or dirty_ready
    )
    if needs_refresh:
        _sync_edit_state(context, force=True)

    if target == "STROKE":
        swatches = tuple(_RUNTIME.get("stroke_swatches", ()) or ())
        if (
            int(_RUNTIME.get("stroke_unique", 0) or 0) == 1
            and swatches
            and _colors_close(swatches[0][0], clean)
        ):
            return 0
    else:
        swatches = tuple(_RUNTIME.get("fill_swatches", ()) or ())
        if (
            int(_RUNTIME.get("fill_unique", 0) or 0) == 1
            and swatches
            and _colors_close(swatches[0][0], clean)
        ):
            return 0

    def prepare_change():
        nonlocal undo_attempted, undo_started
        if not record_undo or undo_attempted:
            return
        undo_attempted = True
        undo_started = _begin_edit_color_undo(target)

    if target == "FILL":
        for group in tuple(_RUNTIME.get("edit_fill_targets", ()) or ()):
            prepare_change()
            bulk_changed = _write_fill_group_color(group, clean)
            if bulk_changed is not None:
                changed += bulk_changed
                continue
            _drawing, _total_curves, _selected_count, batches = group
            for stroke, _curve_index in batches:
                try:
                    if not _colors_close(stroke.fill_color, clean):
                        stroke.fill_color = clean
                        changed += 1
                except FBP_DATA_ERRORS:
                    continue
    else:
        for group in tuple(_RUNTIME.get("edit_point_targets", ()) or ()):
            prepare_change()
            bulk_changed = _write_point_group_color(group, clean)
            if bulk_changed is not None:
                changed += bulk_changed
                continue
            _drawing, _total_points, _selected_count, batches = group
            for stroke, selector, _stroke_offset, _stroke_selected_count in batches:
                try:
                    points = stroke.points
                except FBP_DATA_ERRORS:
                    continue
                if selector is None:
                    selected_points = points
                else:
                    selected_points = (points[index] for index in selector)
                for point in selected_points:
                    try:
                        if not _colors_close(point.vertex_color, clean):
                            point.vertex_color = clean
                            changed += 1
                    except FBP_DATA_ERRORS + (IndexError,):
                        continue
    if changed:
        _RUNTIME["edit_dirty"] = False
        _RUNTIME["edit_suppress_dirty_until"] = time.perf_counter() + _EDIT_SYNC_INTERVAL
        if target == "FILL":
            target_count = int(_RUNTIME.get("edit_fill_count", 0) or 0)
            _RUNTIME["fill_swatches"] = ((clean, target_count),) if target_count else ()
            _RUNTIME["fill_unique"] = 1 if target_count else 0
            _set_state_scalar(_state(context), "fill_mixed", False)
        else:
            target_count = int(_RUNTIME.get("edit_point_count", 0) or 0)
            _RUNTIME["stroke_swatches"] = ((clean, target_count),) if target_count else ()
            _RUNTIME["stroke_unique"] = 1 if target_count else 0
            _set_state_scalar(_state(context), "stroke_mixed", False)
        _tag_gp_color_update(obj)
        if record_undo and undo_started:
            _schedule_edit_color_undo_commit()
    return changed


def _apply_selected_cyclic(context, close_stroke, *, record_undo=False):
    """Open or close every selected Edit curve using Blender's cyclic flag."""
    obj = _active_gp_object(context)
    if obj is None or _context_mode(context) != "EDIT_GREASE_PENCIL":
        return 0
    now = time.perf_counter()
    pointer = int(obj.as_pointer())
    suppress_until = float(_RUNTIME.get("edit_suppress_dirty_until", 0.0) or 0.0)
    last_dirty = float(_RUNTIME.get("edit_last_dirty", 0.0) or 0.0)
    dirty_ready = bool(
        _RUNTIME.get("edit_dirty", True)
        and now >= suppress_until
        and now - last_dirty >= _EDIT_SYNC_DEBOUNCE
    )
    if (
        _RUNTIME.get("target") != pointer
        or _RUNTIME.get("context_mode") != "EDIT_GREASE_PENCIL"
        or _RUNTIME.get("edit_signature") is None
        or dirty_ready
    ):
        _sync_edit_state(context, force=True)

    changed = 0
    undo_started = False
    undo_attempted = False
    expected = bool(close_stroke)
    for group in tuple(_RUNTIME.get("edit_fill_targets", ()) or ()):
        _drawing, _total_curves, _selected_count, batches = group
        for stroke, _curve_index in batches:
            try:
                if bool(stroke.cyclic) == expected:
                    continue
                if record_undo and not undo_attempted:
                    undo_attempted = True
                    undo_started = _begin_edit_color_undo("CLOSE")
                stroke.cyclic = expected
                changed += 1
            except FBP_DATA_ERRORS:
                continue
    if changed:
        _RUNTIME["edit_dirty"] = False
        _RUNTIME["edit_suppress_dirty_until"] = time.perf_counter() + _EDIT_SYNC_INTERVAL
        _tag_gp_color_update(obj)
        if record_undo and undo_started:
            _schedule_edit_color_undo_commit()
    return changed


def _state_color_changed(state, context, target):
    if _STATE_GUARD:
        return
    color = _rgba(state.stroke_color if target == "STROKE" else state.fill_color)
    mode = _context_mode(context)
    if mode == "EDIT_GREASE_PENCIL":
        _apply_selected_color(context, target, color, record_undo=True)
    _kind, _paint, _brush, owner, gp_settings, target_mode = _semantic_brush_context(context)
    if owner is not None and gp_settings is not None:
        _canonical_brush_colors(state, owner, target_mode)


def _close_strokes_changed(state, context):
    if _STATE_GUARD:
        return
    if _context_mode(context) == "EDIT_GREASE_PENCIL":
        _apply_selected_cyclic(
            context,
            bool(state.close_strokes),
            record_undo=True,
        )


def _depsgraph_touches_active_gp(depsgraph, obj):
    """Return whether this depsgraph batch updates the active GP object/data."""
    if depsgraph is None or obj is None:
        return True
    try:
        targets = {int(obj.as_pointer()), int(obj.data.as_pointer())}
        updates = depsgraph.updates
    except FBP_DATA_ERRORS:
        return True
    try:
        for update in updates:
            datablock = getattr(update, "id", None)
            original = getattr(datablock, "original", None) or datablock
            try:
                if int(original.as_pointer()) in targets:
                    geometry_changed = getattr(update, "is_updated_geometry", None)
                    if geometry_changed is not False:
                        return True
            except FBP_DATA_ERRORS:
                continue
    except FBP_DATA_ERRORS:
        return True
    return False


@persistent
def fbp_gp_vertex_brush_color_sync(_scene, depsgraph):
    """Synchronize paint colors and invalidate Edit caches only when needed."""
    context = getattr(bpy, "context", None)
    mode = _context_mode(context)
    if mode == "VERTEX_GREASE_PENCIL":
        _sync_vertex_state(context)
    elif mode == "PAINT_GREASE_PENCIL":
        _sync_draw_state(context)
        obj = _active_gp_object(context)
        if _depsgraph_touches_active_gp(depsgraph, obj):
            _sync_draw_both_fill(context)
    elif mode == "EDIT_GREASE_PENCIL":
        now = time.perf_counter()
        obj = _active_gp_object(context)
        if _depsgraph_touches_active_gp(depsgraph, obj):
            _RUNTIME["edit_dirty"] = True
            _RUNTIME["edit_last_dirty"] = now


@persistent
def fbp_gp_vertex_color_undo_pre(_scene):
    _cancel_edit_color_undo()
    _reset_draw_both_tracking()
    _RUNTIME.update(
        edit_signature=None,
        edit_dirty=True,
        edit_point_targets=(),
        edit_point_count=0,
        edit_fill_targets=(),
        edit_fill_count=0,
    )


@persistent
def fbp_gp_vertex_color_undo_post(_scene):
    _RUNTIME.update(
        edit_signature=None,
        edit_dirty=True,
        edit_point_targets=(),
        edit_point_count=0,
        edit_fill_targets=(),
        edit_fill_count=0,
    )
    context = getattr(bpy, "context", None)
    mode = _context_mode(context)
    if mode == "EDIT_GREASE_PENCIL":
        _sync_edit_state(context, force=True)
    elif mode in {"PAINT_GREASE_PENCIL", "VERTEX_GREASE_PENCIL"}:
        # Undo restores the Object-owned semantic colors, while native brush
        # colors may remain outside the geometry undo snapshot. The semantic
        # state is authoritative and is copied back to the live brush.
        kind, _paint, _brush, owner, gp_settings, target_mode = _semantic_brush_context(context)
        state = _state(context)
        obj = _active_gp_object(context)
        if state is not None and obj is not None and owner is not None and gp_settings is not None:
            try:
                owner_pointer = int(owner.as_pointer())
            except FBP_DATA_ERRORS:
                owner_pointer = id(owner)
            _RUNTIME.update(
                target=int(obj.as_pointer()),
                owner=owner_pointer,
                context_mode=mode,
                brush_kind=kind,
                target_mode=target_mode,
            )
            _canonical_brush_colors(state, owner, target_mode)
        _reset_draw_both_tracking()
    _tag_view3d_redraw()


def _stroke_color_changed(state, context):
    _state_color_changed(state, context, "STROKE")


def _fill_color_changed(state, context):
    _state_color_changed(state, context, "FILL")


class FBP_GPVertexColorState(PropertyGroup):
    stroke_color: FloatVectorProperty(
        name="Stroke",
        description="Stroke vertex color; Shift+X samples only this color",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.0, 0.0, 0.0, 1.0),
        options={"SKIP_SAVE"},
        update=_stroke_color_changed,
    )
    fill_color: FloatVectorProperty(
        name="Fill",
        description="Curve fill vertex color",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(1.0, 1.0, 1.0, 1.0),
        options={"SKIP_SAVE"},
        update=_fill_color_changed,
    )
    close_strokes: BoolProperty(
        name="Close Gap",
        description="Connect the final point to the first point with a straight segment",
        default=False,
        update=_close_strokes_changed,
    )
    stroke_available: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})
    fill_available: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})
    stroke_mixed: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})
    fill_mixed: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})
    selected_points: IntProperty(default=0, min=0, options={"HIDDEN", "SKIP_SAVE"})
    selected_curves: IntProperty(default=0, min=0, options={"HIDDEN", "SKIP_SAVE"})


class FBP_OT_SampleGPStrokeColor(Operator):
    bl_idname = "fbp.sample_gp_stroke_color"
    bl_label = "Sample Grease Pencil Stroke Color"
    bl_description = "Continuously sample the color under the cursor into Stroke while Shift+X is held"
    bl_options = {"INTERNAL"}

    _timer = None
    _location = (0, 0)
    _last_sample = 0.0
    _initial_stroke = None
    _launch_key = "X"

    @classmethod
    def poll(cls, context):
        return (
            _active_gp_object(context) is not None
            and _context_mode(context) in {"PAINT_GREASE_PENCIL", "VERTEX_GREASE_PENCIL"}
            and getattr(getattr(context, "area", None), "type", "") == "VIEW_3D"
            and getattr(getattr(context, "region", None), "type", "") == "WINDOW"
        )

    def _finish(self, context):
        timer = self._timer
        self._timer = None
        if timer is not None:
            try:
                context.window_manager.event_timer_remove(timer)
            except FBP_DATA_ERRORS:
                pass
        try:
            context.window.cursor_modal_restore()
        except FBP_DATA_ERRORS:
            pass

    def _sample(self, context, *, force=False):
        now = time.perf_counter()
        if not force and now - self._last_sample < _SAMPLE_INTERVAL:
            return False
        self._last_sample = now
        region = getattr(context, "region", None)
        x, y = self._location
        if region is None or x < 0 or y < 0 or x >= region.width or y >= region.height:
            return False
        try:
            result = bpy.ops.paint.sample_color("EXEC_DEFAULT", location=(int(x), int(y)))
        except FBP_DATA_ERRORS:
            return False
        if result != {"FINISHED"}:
            return False
        if _context_mode(context) == "PAINT_GREASE_PENCIL":
            _sync_draw_state(context)
        else:
            _sync_vertex_state(context)
        try:
            context.area.tag_redraw()
        except FBP_DATA_ERRORS:
            pass
        return True

    def invoke(self, context, event):
        if not self.poll(context):
            return {"CANCELLED"}
        state = _state(context)
        if state is None:
            return {"CANCELLED"}
        if _context_mode(context) == "PAINT_GREASE_PENCIL":
            _sync_draw_state(context)
        else:
            _sync_vertex_state(context)
        self._initial_stroke = _rgba(state.stroke_color)
        self._launch_key = str(event.type or "X")
        self._location = (int(event.mouse_region_x), int(event.mouse_region_y))
        self._last_sample = 0.0
        try:
            context.window.cursor_modal_set("EYEDROPPER")
        except FBP_DATA_ERRORS:
            pass
        try:
            self._timer = context.window_manager.event_timer_add(
                _SAMPLE_INTERVAL,
                window=context.window,
            )
            context.window_manager.modal_handler_add(self)
        except FBP_DATA_ERRORS:
            self._finish(context)
            return {"CANCELLED"}
        self._sample(context, force=True)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == self._launch_key and event.value == "RELEASE":
            state = _state(context)
            sampled = bool(
                state is not None
                and self._initial_stroke is not None
                and not _colors_close(state.stroke_color, self._initial_stroke)
            )
            self._finish(context)
            if sampled:
                _push_edit_color_undo("Sample Grease Pencil Stroke Color")
            return {"FINISHED"}
        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            state = _state(context)
            if state is not None and self._initial_stroke is not None:
                _set_state_value(state, "stroke_color", self._initial_stroke)
                _kind, _paint, _brush, owner, _gp_settings, mode = _semantic_brush_context(context)
                if owner is not None:
                    _canonical_brush_colors(state, owner, mode)
            self._finish(context)
            return {"CANCELLED"}
        if event.type == "MOUSEMOVE":
            self._location = (int(event.mouse_region_x), int(event.mouse_region_y))
            self._sample(context)
        elif event.type == "TIMER":
            # Blender 5.2's Event RNA does not consistently expose ``timer``
            # to Python. Accept an untagged TIMER event while this operator
            # owns a timer; keep filtering when the identity is available.
            event_timer = getattr(event, "timer", None)
            if event_timer is None or event_timer == self._timer:
                self._sample(context)
        return {"RUNNING_MODAL"}


class FBP_OT_SwapGPVertexColors(Operator):
    bl_idname = "fbp.swap_gp_vertex_colors"
    bl_label = "Swap Stroke and Fill Colors"
    bl_description = "Swap the semantic Stroke and Fill vertex colors"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return _active_gp_object(context) is not None and _context_mode(context) in {
            "EDIT_GREASE_PENCIL",
            "PAINT_GREASE_PENCIL",
            "VERTEX_GREASE_PENCIL",
        }

    def execute(self, context):
        state = _state(context)
        if state is None:
            return {"CANCELLED"}
        old_stroke = _rgba(state.stroke_color)
        old_fill = _rgba(state.fill_color)
        if _context_mode(context) == "EDIT_GREASE_PENCIL":
            _commit_edit_color_undo()
            _begin_edit_color_undo("STROKE")
        _set_state_value(state, "stroke_color", old_fill)
        _set_state_value(state, "fill_color", old_stroke)
        if _context_mode(context) == "EDIT_GREASE_PENCIL":
            _apply_selected_color(context, "STROKE", old_fill)
            _apply_selected_color(context, "FILL", old_stroke)
            _sync_edit_state(context, force=True)
            _RUNTIME["edit_undo_label"] = "Swap Grease Pencil Stroke / Fill Colors"
            _commit_edit_color_undo()
        else:
            _kind, _paint, _brush, owner, gp_settings, target_mode = _semantic_brush_context(context)
            if owner is not None and gp_settings is not None:
                _canonical_brush_colors(state, owner, target_mode)
                _push_edit_color_undo("Swap Grease Pencil Stroke / Fill Colors")
        return {"FINISHED"}


class FBP_OT_ToggleGPCloseGap(Operator):
    bl_idname = "fbp.toggle_gp_close_gap"
    bl_label = "Toggle Grease Pencil Close Gap"
    bl_description = "Open or close strokes by connecting the final point to the first point"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return _active_gp_object(context) is not None and _context_mode(context) in {
            "EDIT_GREASE_PENCIL",
            "PAINT_GREASE_PENCIL",
            "VERTEX_GREASE_PENCIL",
        }

    def execute(self, context):
        state = _state(context)
        if state is None:
            return {"CANCELLED"}
        edit_mode = _context_mode(context) == "EDIT_GREASE_PENCIL"
        state.close_strokes = not bool(state.close_strokes)
        if not edit_mode:
            _push_edit_color_undo("Toggle Grease Pencil Close Gap")
        return {"FINISHED"}


class FBP_OT_RefreshGPVertexColors(Operator):
    bl_idname = "fbp.refresh_gp_vertex_colors"
    bl_label = "Refresh Selected Vertex Colors"
    bl_description = "Read Stroke and Fill colors again from the current Grease Pencil selection"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return _active_gp_object(context) is not None and _context_mode(context) == "EDIT_GREASE_PENCIL"

    def execute(self, context):
        _sync_edit_state(context, force=True)
        return {"FINISHED"}


def _draw_mixed_swatches(layout, target):
    values = _RUNTIME.get("stroke_swatches" if target == "STROKE" else "fill_swatches", ())
    unique_count = int(_RUNTIME.get("stroke_unique" if target == "STROKE" else "fill_unique", 0) or 0)
    if unique_count <= 1:
        return
    row = layout.row(align=True)
    row.label(text=f"Mixed · {unique_count} colors")
    chips = row.row(align=True)
    for color, _count in values:
        try:
            chips.template_node_socket(color=_rgba(color))
        except FBP_DATA_ERRORS:
            break
    if unique_count > len(values):
        chips.label(text=f"+{unique_count - len(values)}")


def _draw_paint_color_controls(layout, context, state):
    context_mode = _context_mode(context)
    if context_mode == "VERTEX_GREASE_PENCIL":
        _sync_vertex_state(context)
        _paint, brush, _owner, gp_settings = _brush_context(context)
        mode_property = "vertex_mode"
        mode = _vertex_mode(gp_settings)
        label = "Vertex Paint"
    else:
        _sync_draw_state(context)
        _paint, brush, _owner, gp_settings = _draw_brush_context(context)
        mode_property = "stroke_type"
        mode = _draw_mode(gp_settings)
        label = "Draw"
    if brush is None or gp_settings is None:
        layout.label(text=f"Choose a {label} brush", icon="INFO")
        return
    if hasattr(gp_settings, mode_property):
        row = layout.row(align=True)
        row.prop_enum(gp_settings, mode_property, "STROKE", text="Stroke", icon="GP_DRAW_STROKE")
        row.prop_enum(gp_settings, mode_property, "FILL", text="Fill", icon="GP_DRAW_FILL")
        row.prop_enum(gp_settings, mode_property, "BOTH", text="Both", icon="GP_DRAW_BOTH")
    layout.prop(state, "stroke_color", text="Stroke")
    layout.prop(state, "fill_color", text="Fill")
    layout.prop(state, "close_strokes", text="Close Gap", toggle=True, icon="LOOP_BACK")
    row = layout.row(align=True)
    row.operator("fbp.swap_gp_vertex_colors", text="Swap", icon="ARROW_LEFTRIGHT")
    row.label(text="X · Shift+X samples Stroke")
    if mode == "BOTH":
        layout.label(text="Both applies the separate Stroke and Fill colors", icon="CHECKMARK")


class FBP_PT_GPVertexColors(Panel):
    bl_idname = "FBP_PT_gp_vertex_colors"
    bl_label = "Stroke / Fill Vertex Colors"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Frame By Plane"

    @classmethod
    def poll(cls, context):
        return _active_gp_object(context) is not None and _context_mode(context) in {
            "EDIT_GREASE_PENCIL",
            "PAINT_GREASE_PENCIL",
            "VERTEX_GREASE_PENCIL",
        }

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        state = _state(context)
        if state is None:
            layout.label(text="Color state unavailable", icon="ERROR")
            return
        mode = _context_mode(context)
        if mode in {"PAINT_GREASE_PENCIL", "VERTEX_GREASE_PENCIL"}:
            _draw_paint_color_controls(layout, context, state)
            return

        _sync_edit_state(context)
        if state.selected_points <= 0:
            row = layout.row(align=True)
            row.label(text="Select points or strokes to edit their colors", icon="INFO")
            row.operator("fbp.refresh_gp_vertex_colors", text="", icon="FILE_REFRESH")
            return
        summary = layout.row(align=True)
        summary.label(text=f"{state.selected_points} points · {state.selected_curves} strokes")
        summary.operator("fbp.refresh_gp_vertex_colors", text="", icon="FILE_REFRESH")
        stroke_col = layout.column()
        stroke_col.enabled = bool(state.stroke_available)
        stroke_col.prop(state, "stroke_color", text="Stroke")
        _draw_mixed_swatches(layout, "STROKE")
        fill_col = layout.column()
        fill_col.enabled = bool(state.fill_available)
        fill_col.prop(state, "fill_color", text="Fill")
        _draw_mixed_swatches(layout, "FILL")
        layout.prop(
            state,
            "close_strokes",
            text="Close Selected Gaps",
            toggle=True,
            icon="LOOP_BACK",
        )
        layout.operator("fbp.swap_gp_vertex_colors", text="Swap Stroke / Fill", icon="ARROW_LEFTRIGHT")


def _sync_color_state_for_ui(context):
    mode = _context_mode(context)
    if mode == "EDIT_GREASE_PENCIL":
        _sync_edit_state(context)
    elif mode == "PAINT_GREASE_PENCIL":
        _sync_draw_state(context)
    elif mode == "VERTEX_GREASE_PENCIL":
        _sync_vertex_state(context)


def _draw_color_popover(layout, context, property_name):
    _sync_color_state_for_ui(context)
    state = _state(context)
    if state is None:
        layout.label(text="Color state unavailable", icon="ERROR")
        return
    layout.template_color_picker(state, property_name, value_slider=True)
    row = layout.row(align=True)
    row.prop(state, property_name, text="")

    mode = _context_mode(context)
    paint = None
    try:
        if mode == "PAINT_GREASE_PENCIL":
            paint = context.scene.tool_settings.gpencil_paint
        elif mode == "VERTEX_GREASE_PENCIL":
            paint = context.scene.tool_settings.gpencil_vertex_paint
    except FBP_DATA_ERRORS:
        paint = None
    if paint is not None:
        palette_row = layout.row(align=True)
        palette_row.template_ID(paint, "palette", new="palette.new")
        if paint.palette:
            layout.template_palette(paint, "palette")


class FBP_PT_GPStrokeColorPopover(Panel):
    bl_idname = "FBP_PT_gp_stroke_color_popover"
    bl_label = "Stroke Color"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 10

    @classmethod
    def poll(cls, context):
        return _active_gp_object(context) is not None and _context_mode(context) in {
            "EDIT_GREASE_PENCIL",
            "PAINT_GREASE_PENCIL",
            "VERTEX_GREASE_PENCIL",
        }

    def draw(self, context):
        _draw_color_popover(self.layout, context, "stroke_color")


class FBP_PT_GPFillColorPopover(Panel):
    bl_idname = "FBP_PT_gp_fill_color_popover"
    bl_label = "Fill Color"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 10

    @classmethod
    def poll(cls, context):
        return FBP_PT_GPStrokeColorPopover.poll(context)

    def draw(self, context):
        _draw_color_popover(self.layout, context, "fill_color")


def _draw_header_color_pair(layout, context, *, enabled=True, owner=None, include_close=True):
    """Draw the semantic pair in the native brush-color footprint."""
    state = _state(context)
    if state is None:
        return False
    row = layout.row(align=True)
    row.ui_units_x = 7.75 if include_close else 6.25
    stroke = row.row(align=True)
    stroke.ui_units_x = 2.5
    stroke.enabled = bool(enabled)
    stroke.prop_with_popover(
        state,
        "stroke_color",
        text="",
        panel="FBP_PT_gp_stroke_color_popover",
    )
    swap = row.row(align=True)
    swap.ui_units_x = 1.25
    swap.scale_x = 1.0
    swap.enabled = bool(enabled)
    swap.operator(
        "fbp.swap_gp_vertex_colors" if owner is None else "paint.brush_colors_flip",
        text="",
        icon="ARROW_LEFTRIGHT",
        emboss=False,
    )
    fill = row.row(align=True)
    fill.ui_units_x = 2.5
    fill.enabled = bool(enabled)
    fill.prop_with_popover(
        state,
        "fill_color",
        text="",
        panel="FBP_PT_gp_fill_color_popover",
    )
    if include_close:
        close = row.row(align=True)
        close.ui_units_x = 1.5
        close.enabled = bool(enabled)
        close.operator(
            "fbp.toggle_gp_close_gap",
            text="",
            icon="LOOP_BACK",
            depress=bool(state.close_strokes),
        )
    return True


def _draw_header_close_stroke(layout, context, *, enabled=True):
    state = _state(context)
    if state is None:
        return False
    close = layout.row(align=True)
    close.ui_units_x = 1.5
    close.enabled = bool(enabled)
    close.operator(
        "fbp.toggle_gp_close_gap",
        text="",
        icon="LOOP_BACK",
        depress=bool(state.close_strokes),
    )
    return True


class _FBPStrokeTypeRowProxy:
    """Detect Blender's native Stroke/Fill/Both row without redrawing it."""

    __slots__ = ("_layout", "_root")

    def __init__(self, layout, root):
        object.__setattr__(self, "_layout", layout)
        object.__setattr__(self, "_root", root)

    def __getattr__(self, name):
        return getattr(self._layout, name)

    def __setattr__(self, name, value):
        if name in self.__slots__:
            object.__setattr__(self, name, value)
        else:
            setattr(self._layout, name, value)

    def prop_enum(self, data, property_name, value, **kwargs):
        result = self._layout.prop_enum(data, property_name, value, **kwargs)
        if property_name == "stroke_type":
            self._root._close_gap_pending = True
        return result

    def prop(self, data, property_name, **kwargs):
        result = self._layout.prop(data, property_name, **kwargs)
        if property_name == "stroke_type":
            self._root._close_gap_pending = True
        return result


class _FBPCloseGapLayoutProxy:
    """Insert Close Gap between native stroke type and Caps Type rows."""

    __slots__ = ("_layout", "_context", "_close_gap_pending")

    def __init__(self, layout, context):
        object.__setattr__(self, "_layout", layout)
        object.__setattr__(self, "_context", context)
        object.__setattr__(self, "_close_gap_pending", False)

    def __getattr__(self, name):
        return getattr(self._layout, name)

    def __setattr__(self, name, value):
        if name in self.__slots__:
            object.__setattr__(self, name, value)
        else:
            setattr(self._layout, name, value)

    def row(self, **kwargs):
        if self._close_gap_pending:
            self._close_gap_pending = False
            state = _state(self._context)
            if state is not None:
                close = self._layout.row(align=False)
                close.operator(
                    "fbp.toggle_gp_close_gap",
                    text="",
                    icon="LOOP_BACK",
                    depress=bool(state.close_strokes),
                )
        return _FBPStrokeTypeRowProxy(self._layout.row(**kwargs), self)


def _draw_native_gp_paint_settings(layout, context, brush, props, *, compact=False):
    original = _NATIVE_UI.get("paint_settings")
    if original is None or original is _MISSING:
        return None
    return original(
        _FBPCloseGapLayoutProxy(layout, context),
        context,
        brush,
        props,
        compact=compact,
    )


def _draw_native_draw_color_selector(context, layout, brush, gp_settings):
    """Blender 5.2 native Draw selector with the dual color pair in-place."""
    settings = context.scene.tool_settings.gpencil_paint
    material = gp_settings.material
    row = layout.row(align=True)
    if not gp_settings.use_material_pin:
        material = context.object.active_material
    icon_id = 0
    material_name = ""
    if material:
        material.id_data.preview_ensure()
        if material.id_data.preview:
            icon_id = material.id_data.preview.icon_id
            material_name = material.name
            max_width = 25
            if len(material_name) > max_width:
                material_name = material_name[:max_width - 5] + ".." + material_name[-3:]

    material_row = row.row(align=True)
    material_row.enabled = not gp_settings.use_material_pin
    material_row.ui_units_x = 8
    material_row.popover(
        panel="TOPBAR_PT_grease_pencil_materials",
        text=material_name,
        translate=False,
        icon_value=icon_id,
    )
    row.prop(gp_settings, "use_material_pin", text="")

    if brush.gpencil_brush_type in {"DRAW", "FILL"}:
        row.separator(factor=1.0)
        mode_row = row.row(align=True)
        pin_draw_mode = gp_settings.pin_draw_mode
        mode_row.enabled = not pin_draw_mode
        if pin_draw_mode:
            mode_row.prop_enum(gp_settings, "brush_draw_mode", "MATERIAL", text="", icon="MATERIAL")
            mode_row.prop_enum(gp_settings, "brush_draw_mode", "VERTEXCOLOR", text="", icon="VPAINT_HLT")
        else:
            mode_row.prop_enum(settings, "color_mode", "MATERIAL", text="", icon="MATERIAL")
            mode_row.prop_enum(settings, "color_mode", "VERTEXCOLOR", text="", icon="VPAINT_HLT")
        # Keep Pin Mode attached to the Material / Color Attribute choice.
        row.prop(gp_settings, "pin_draw_mode", text="")

        show_vertex_color = (
            ((not pin_draw_mode) and settings.color_mode == "VERTEXCOLOR")
            or (pin_draw_mode and gp_settings.brush_draw_mode == "VERTEXCOLOR")
        )
        if show_vertex_color:
            _sync_draw_state(context)
            color_row = row.row(align=True)
            color_row.enabled = True
            _paint, _brush, owner, _settings = _draw_brush_context(context)
            _draw_header_color_pair(
                color_row,
                context,
                owner=owner,
                include_close=False,
            )


def _draw_native_vertex_tool_settings(context, layout, tool):
    """Blender 5.2 native Vertex Paint row with the dual pair in-place."""
    if (tool is None) or (not tool.use_brushes):
        return False
    from bl_ui.properties_paint_common import (
        BrushAssetShelf,
        brush_basic_grease_pencil_vertex_settings,
    )

    paint = context.tool_settings.gpencil_vertex_paint
    brush = paint.brush
    BrushAssetShelf.draw_popup_selector(layout, context, brush)
    if brush is None:
        return False
    drew_color_pair = False
    if brush.gpencil_vertex_brush_type not in {"BLUR", "AVERAGE", "SMEAR"}:
        layout.separator(factor=0.4)
        _sync_vertex_state(context)
        _paint, _brush, owner, _gp_settings = _brush_context(context)
        _draw_header_color_pair(
            layout,
            context,
            owner=owner,
        )
        drew_color_pair = True
    if not drew_color_pair:
        _draw_header_close_stroke(layout, context)
    brush_basic_grease_pencil_vertex_settings(layout, context, brush, compact=True)
    return True


def _draw_native_edit_tool_settings(context, layout, _tool):
    """Place Edit colors where paint modes expose their native brush color."""
    state = _state(context)
    if state is None:
        return False
    obj = _active_gp_object(context)
    pointer = int(obj.as_pointer()) if obj is not None else 0
    needs_initial_sync = bool(
        _RUNTIME.get("target") != pointer
        or _RUNTIME.get("context_mode") != "EDIT_GREASE_PENCIL"
        or _RUNTIME.get("edit_signature") is None
    )
    if needs_initial_sync:
        _sync_edit_state(context, force=True)
    layout.separator(factor=0.4)
    _draw_header_color_pair(layout, context, enabled=True)
    return True


def _restore_native_color_header():
    global _HEADER_REGISTERED, _NATIVE_UI_PATCHED
    try:
        import bl_ui.properties_paint_common as paint_common
        import bl_ui.space_view3d as space_view3d

        if "draw_color_selector" in _NATIVE_UI:
            paint_common.brush_basic__draw_color_selector = _NATIVE_UI["draw_color_selector"]
        if "paint_settings" in _NATIVE_UI:
            paint_common.brush_basic_grease_pencil_paint_settings = _NATIVE_UI["paint_settings"]
        mode_class = space_view3d._draw_tool_settings_context_mode
        for key, attribute in (
            ("vertex_tool_settings", "VERTEX_GREASE_PENCIL"),
            ("edit_tool_settings", "EDIT_GREASE_PENCIL"),
        ):
            if key not in _NATIVE_UI:
                continue
            original = _NATIVE_UI[key]
            if original is _MISSING:
                try:
                    delattr(mode_class, attribute)
                except AttributeError:
                    pass
            else:
                setattr(mode_class, attribute, original)
    except FBP_DATA_ERRORS as exc:
        fbp_warn_once(
            "gp_vertex_colors.native_header_restore",
            "Could not restore Blender's native Grease Pencil color header",
            exc,
        )
    _NATIVE_UI.clear()
    _NATIVE_UI_PATCHED = False
    _HEADER_REGISTERED = False


def _register_tool_header():
    global _HEADER_REGISTERED, _NATIVE_UI_PATCHED
    if _NATIVE_UI_PATCHED:
        return True
    try:
        import bl_ui.properties_paint_common as paint_common
        import bl_ui.space_view3d as space_view3d

        mode_class = space_view3d._draw_tool_settings_context_mode
        _NATIVE_UI["draw_color_selector"] = paint_common.brush_basic__draw_color_selector
        _NATIVE_UI["paint_settings"] = paint_common.brush_basic_grease_pencil_paint_settings
        _NATIVE_UI["vertex_tool_settings"] = vars(mode_class).get("VERTEX_GREASE_PENCIL", _MISSING)
        _NATIVE_UI["edit_tool_settings"] = vars(mode_class).get("EDIT_GREASE_PENCIL", _MISSING)
        paint_common.brush_basic__draw_color_selector = _draw_native_draw_color_selector
        paint_common.brush_basic_grease_pencil_paint_settings = _draw_native_gp_paint_settings
        mode_class.VERTEX_GREASE_PENCIL = staticmethod(_draw_native_vertex_tool_settings)
        mode_class.EDIT_GREASE_PENCIL = staticmethod(_draw_native_edit_tool_settings)
        _NATIVE_UI_PATCHED = True
        _HEADER_REGISTERED = True
        return True
    except FBP_DATA_ERRORS as exc:
        _restore_native_color_header()
        fbp_warn_once(
            "gp_vertex_colors.tool_header_register",
            "Could not integrate Stroke/Fill into Blender's native Tool Header",
            exc,
        )
        return False


def _unregister_tool_header():
    _restore_native_color_header()


def _register_sample_color_keymaps():
    _unregister_sample_color_keymaps()
    keyconfig = getattr(getattr(bpy.context, "window_manager", None), "keyconfigs", None)
    addon = getattr(keyconfig, "addon", None) if keyconfig is not None else None
    if addon is None:
        return False
    try:
        for name in ("Grease Pencil Draw Mode", "Grease Pencil Vertex Paint"):
            keymap = addon.keymaps.new(name=name, space_type="EMPTY")
            item = keymap.keymap_items.new(
                FBP_OT_SampleGPStrokeColor.bl_idname,
                "X",
                "PRESS",
                shift=True,
                head=True,
            )
            _ADDON_KEYMAPS.append((keymap, item))
        # G is scoped to Draw Mode. Edit Mode keeps Blender's fundamental
        # Grab/Move shortcut; Close Gap remains available there as a button.
        keymap = addon.keymaps.new(name="Grease Pencil Draw Mode", space_type="EMPTY")
        item = keymap.keymap_items.new(
            FBP_OT_ToggleGPCloseGap.bl_idname,
            "G",
            "PRESS",
            head=True,
        )
        _ADDON_KEYMAPS.append((keymap, item))
        return True
    except FBP_DATA_ERRORS as exc:
        _unregister_sample_color_keymaps()
        fbp_warn_once(
            "gp_vertex_colors.sample_keymap",
            "Could not register the Grease Pencil color and Close Gap shortcuts",
            exc,
        )
        return False


def _unregister_sample_color_keymaps():
    while _ADDON_KEYMAPS:
        keymap, item = _ADDON_KEYMAPS.pop()
        try:
            keymap.keymap_items.remove(item)
        except FBP_DATA_ERRORS:
            pass


property_classes = (FBP_GPVertexColorState,)
classes = (
    FBP_OT_SampleGPStrokeColor,
    FBP_OT_SwapGPVertexColors,
    FBP_OT_ToggleGPCloseGap,
    FBP_OT_RefreshGPVertexColors,
    FBP_PT_GPVertexColors,
    FBP_PT_GPStrokeColorPopover,
    FBP_PT_GPFillColorPopover,
)


def register():
    global _STATE_GUARD
    _STATE_GUARD = 0
    registered_properties = False
    register_classes(property_classes)
    try:
        setattr(
            bpy.types.Object,
            _STATE_PROPERTY,
            PointerProperty(type=FBP_GPVertexColorState, options={"SKIP_SAVE"}),
        )
        registered_properties = True
        register_classes(classes)
        _register_tool_header()
        _register_sample_color_keymaps()
        _register_brush_color_timer()
        append_handler_once(
            bpy.app.handlers.depsgraph_update_post,
            fbp_gp_vertex_brush_color_sync,
            module_suffix="gp_vertex_colors",
        )
        append_handler_once(
            bpy.app.handlers.undo_pre,
            fbp_gp_vertex_color_undo_pre,
            module_suffix="gp_vertex_colors",
        )
        append_handler_once(
            bpy.app.handlers.undo_post,
            fbp_gp_vertex_color_undo_post,
            module_suffix="gp_vertex_colors",
        )
    except FBP_DATA_ERRORS:
        _unregister_brush_color_timer()
        _cancel_edit_color_undo()
        _unregister_tool_header()
        _unregister_sample_color_keymaps()
        remove_handlers_by_name(
            bpy.app.handlers.depsgraph_update_post,
            "fbp_gp_vertex_brush_color_sync",
            module_suffix="gp_vertex_colors",
        )
        remove_handlers_by_name(
            bpy.app.handlers.undo_pre,
            "fbp_gp_vertex_color_undo_pre",
            module_suffix="gp_vertex_colors",
        )
        remove_handlers_by_name(
            bpy.app.handlers.undo_post,
            "fbp_gp_vertex_color_undo_post",
            module_suffix="gp_vertex_colors",
        )
        if registered_properties:
            unregister_type_properties(bpy.types.Object, (_STATE_PROPERTY,))
        unregister_classes(property_classes)
        raise


def unregister():
    global _STATE_GUARD
    _unregister_brush_color_timer()
    _cancel_edit_color_undo()
    _unregister_tool_header()
    _unregister_sample_color_keymaps()
    remove_handlers_by_name(
        bpy.app.handlers.depsgraph_update_post,
        "fbp_gp_vertex_brush_color_sync",
        module_suffix="gp_vertex_colors",
    )
    remove_handlers_by_name(
        bpy.app.handlers.undo_pre,
        "fbp_gp_vertex_color_undo_pre",
        module_suffix="gp_vertex_colors",
    )
    remove_handlers_by_name(
        bpy.app.handlers.undo_post,
        "fbp_gp_vertex_color_undo_post",
        module_suffix="gp_vertex_colors",
    )
    unregister_classes(classes)
    unregister_type_properties(bpy.types.Object, (_STATE_PROPERTY,))
    unregister_classes(property_classes)
    _STATE_GUARD = 0
    _RUNTIME.update(
        target=0,
        owner=0,
        context_mode="",
        brush_kind="",
        target_mode="",
        expected_primary=None,
        expected_secondary=None,
        edit_signature=None,
        edit_dirty=True,
        edit_last_sync=0.0,
        edit_last_dirty=0.0,
        edit_suppress_dirty_until=0.0,
        edit_point_targets=(),
        edit_point_count=0,
        edit_fill_targets=(),
        edit_fill_count=0,
        stroke_swatches=(),
        fill_swatches=(),
        stroke_unique=0,
        fill_unique=0,
        draw_watch_initialized=False,
        draw_watch_object=0,
        draw_drawing_pointer=0,
        draw_curve_count=0,
        edit_undo_label="Grease Pencil Color",
    )
