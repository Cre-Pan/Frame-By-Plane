"""Shared visual language for Frame By Plane user interfaces.

The add-on is exposed in several Blender regions (3D View, Tool Properties,
Modifiers, Output, Camera Data and Preferences).  These helpers keep spacing,
empty states, section headers and list heights consistent without coupling UI
code to operators or scene logic.
"""

FBP_UI_GAP_SECTION = 0.35
FBP_UI_ROW_SCALE = 1.0
FBP_UI_ROW_SCALE_PRIMARY = 1.06
FBP_UI_LIST_MIN_ROWS = 7
FBP_UI_EFFECT_MIN_ROWS = 10
FBP_UI_EFFECT_MAX_ROWS = 14
FBP_UI_COMPACT_WIDTH = 360.0
FBP_UI_NARROW_WIDTH = 300.0
_UI_METRIC_CACHE = globals().get("_UI_METRIC_CACHE", {})
if not isinstance(_UI_METRIC_CACHE, dict):
    _UI_METRIC_CACHE = {}
_UI_METRIC_CACHE_LIMIT = 64


def configure_layout(layout, *, property_split=False, decorate=False):
    """Apply the common Frame By Plane layout policy and return *layout*."""
    try:
        layout.use_property_split = bool(property_split)
    except (AttributeError, TypeError):
        pass
    try:
        layout.use_property_decorate = bool(decorate)
    except (AttributeError, TypeError):
        pass
    return layout


def section_gap(layout, factor=FBP_UI_GAP_SECTION):
    """Insert the standard vertical gap between logical sections."""
    layout.separator(factor=float(factor))


def section_header(
    layout,
    title,
    *,
    icon="NONE",
    icon_value=0,
    count=None,
    suffix="",
    scale=FBP_UI_ROW_SCALE,
    align=False,
):
    """Draw a lightweight, non-boxed section header with optional count."""
    row = layout.row(align=bool(align))
    row.scale_y = float(scale)
    label = str(title or "Settings")
    if count is not None:
        label = f"{label} · {int(count)}"
    if suffix:
        label = f"{label} {suffix}"
    if int(icon_value or 0) > 0:
        row.label(text=label, icon_value=int(icon_value))
    else:
        row.label(text=label, icon=str(icon or "NONE"))
    return row


def hint_row(layout, text, *, icon="INFO", alert=False, disabled=True):
    """Draw a consistent one-line hint/status row."""
    row = layout.row(align=False)
    row.alert = bool(alert)
    if disabled and not alert:
        row.enabled = False
    row.label(text=str(text or ""), icon=str(icon or "BLANK1"))
    return row


def empty_state(layout, title, detail="", *, icon="INFO", boxed=True):
    """Draw the same compact empty-state treatment in every editor."""
    target = layout.box() if boxed else layout.column(align=False)
    configure_layout(target)
    row = target.row(align=False)
    row.label(text=str(title or "Nothing to show"), icon=str(icon or "INFO"))
    if detail:
        hint_row(target, detail, icon="BLANK1", disabled=True)
    return target


def list_rows(item_count, *, minimum=FBP_UI_LIST_MIN_ROWS, maximum=14):
    """Return a stable UIList height bounded by the shared style constants."""
    return max(int(minimum), min(int(maximum), max(int(item_count or 0), 1)))


def _ui_metrics(context, default=420.0):
    """Return cached ``(scale, logical width)`` for one editor region."""
    try:
        preferences = getattr(context, "preferences", None)
        system = getattr(preferences, "system", None)
        scale_value = float(getattr(system, "ui_scale", 1.0) or 1.0)
        pixel_size = float(getattr(system, "pixel_size", 1.0) or 1.0)
        scale = max(0.5, scale_value * pixel_size)
        region = getattr(context, "region", None)
        width = float(getattr(region, "width", 0.0) or 0.0)
        if width <= 0.0:
            width = float(default)
        try:
            region_key = int(region.as_pointer()) if region is not None else 0
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            region_key = 0
        key = (region_key, width, scale_value, pixel_size, float(default))
        cached = _UI_METRIC_CACHE.get(key)
        if cached is not None:
            return cached
        metrics = (scale, width / scale)
        if len(_UI_METRIC_CACHE) >= _UI_METRIC_CACHE_LIMIT:
            _UI_METRIC_CACHE.clear()
        _UI_METRIC_CACHE[key] = metrics
        return metrics
    except (AttributeError, TypeError, ValueError, ZeroDivisionError):
        return (1.0, float(default))


def ui_scale(context):
    """Return Blender's effective interface scale without assuming a UI region."""
    return _ui_metrics(context)[0]


def logical_region_width(context, default=420.0):
    """Return region width normalized for UI scale and high-DPI pixel size."""
    return _ui_metrics(context, default)[1]


# Frame By Plane intentionally uses one Comfortable UI density.  Keeping this
# as constants avoids evaluating dead Compact/Automatic branches on every draw.
FBP_UI_COMFORTABLE_THRESHOLD_SCALE = 1.18
FBP_UI_COMFORTABLE_ROW_SCALE = 1.08


def _density_threshold(_context, threshold):
    return float(threshold) * FBP_UI_COMFORTABLE_THRESHOLD_SCALE


def _density_row_scale(_context):
    return FBP_UI_COMFORTABLE_ROW_SCALE


def is_compact(context, threshold=FBP_UI_COMPACT_WIDTH):
    """True when the current editor region should use vertically stacked controls."""
    return logical_region_width(context) < _density_threshold(context, threshold)


def is_narrow(context, threshold=FBP_UI_NARROW_WIDTH):
    """True for exceptionally narrow sidebars where labels must be abbreviated."""
    return logical_region_width(context) < float(threshold)


def adaptive_row(
    layout,
    context,
    *,
    align=False,
    scale=FBP_UI_ROW_SCALE,
    threshold=FBP_UI_COMPACT_WIDTH,
):
    """Return a row in normal regions and a column in compact regions.

    Blender layouts expose the same ``prop``/``operator`` methods on rows and
    columns, so callers can keep one code path while avoiding clipped labels.
    """
    target = (
        layout.column(align=bool(align))
        if is_compact(context, threshold=threshold)
        else layout.row(align=bool(align))
    )
    target.scale_y = float(scale) * _density_row_scale(context)
    return target


def selection_status(layout, selected, *, noun="layer", icon="RESTRICT_SELECT_OFF"):
    """Show a compact, shared multi-selection status only when it adds context."""
    count = int(selected or 0)
    if count <= 1:
        return None
    suffix = noun if count == 1 else f"{noun}s"
    return hint_row(
        layout,
        f"Editing {count} selected {suffix}",
        icon=icon,
        disabled=True,
    )
