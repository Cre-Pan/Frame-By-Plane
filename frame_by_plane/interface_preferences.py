"""Read-only accessors and caches for interface preferences.

This module is intentionally independent from ``properties.py``.  UI lists,
effect drawing and lightweight interactive modules can read preferences without
pulling the complete RNA property schema into their import graph.
"""

from __future__ import annotations

import bpy

from .runtime import FBP_DATA_ERRORS


_ADDON_PREFERENCES_KEY = ""
_UILIST_ICON_FLAGS_CACHE: dict[tuple[object, ...], dict[str, bool]] = {}
_UILIST_DRAG_PREVIEW_ORDERS: dict[str, tuple[str, ...]] = {}



UILIST_COLUMN_DEFINITIONS = {
    "label": ("Label / Name", "FONT_DATA"),
    "blank_1": ("Blank Space 1", "KEY_EMPTY1"),
    "blank_2": ("Blank Space 2", "KEY_EMPTY1"),
    "blank_3": ("Blank Space 3", "KEY_EMPTY1"),
    "preview": ("Type / Preview", "IMAGE_DATA"),
    "clipping": ("Clipping Mask", "MOD_MASK"),
    "visibility": ("Visibility", "HIDE_OFF"),
    "solo": ("Solo", "LIGHT"),
    "holdout": ("Holdout", "CLIPUV_HLT"),
    "motion": ("Motion", "TIME"),
    "plane": ("Select Plane", "RESTRICT_SELECT_OFF"),
    "lock": ("Lock", "LOCKED"),
    "select": ("Select Rig", "CHECKBOX_DEHLT"),
    "effect_type": ("Effect Type", "SHADERFX"),
    "effect_select": ("Selection Checkbox", "CHECKBOX_DEHLT"),
    "effect_solo": ("Effect Solo", "LIGHT"),
    "effect_viewport": ("Hide", "HIDE_OFF"),
    "effect_mask": ("Mask", "MOD_MASK"),
    "pending_grip": ("Reorder Grip", "GRIP_V"),
    "pending_color": ("Color Tag", "COLOR"),
    "pending_status": ("Media Status", "FILE_IMAGE"),
    "pending_reverse": ("Reverse Sequence", "ARROW_LEFTRIGHT"),
    "pending_select": ("Selection", "RESTRICT_SELECT_OFF"),
    "pending_edit": ("Edit", "GREASEPENCIL"),
    "pending_delete": ("Delete", "TRASH"),
    "status": ("Status", "INFO"),
    "count": ("Count", "LINENUMBERS_ON"),
    "apply": ("Apply", "CHECKMARK"),
    "remove": ("Delete", "TRASH"),
    "enabled": ("Enabled", "HIDE_OFF"),
    "selected": ("Selected", "RESTRICT_SELECT_OFF"),
    "link": ("Link", "LINKED"),
    "metric_primary": ("Primary Metric", "TIME"),
    "metric_secondary": ("Secondary Metric", "MODIFIER"),
    "current": ("Current Item", "RADIOBUT_ON"),
    "slot": ("Slot / Link State", "LINKED"),
    "compositor_visibility": ("Visibility", "HIDE_OFF"),
    "compositor_holdout": ("Holdout", "CLIPUV_HLT"),
    "compositor_indirect": ("Indirect Only", "INDIRECT_ONLY_ON"),
    "compositor_enabled": ("Enabled", "CHECKBOX_HLT"),
    "compositor_mix": ("Mix", "NODE_MATERIAL"),
    "doctor_severity": ("Severity", "ERROR"),
    "doctor_fix": ("Safe Fix", "TOOL_SETTINGS"),
    "doctor_select": ("Navigate", "RESTRICT_SELECT_OFF"),
    "package_select": ("Selection", "RESTRICT_SELECT_OFF"),
    "package_type": ("Source Type", "RENDERLAYERS"),
    "package_visibility": ("Visibility", "HIDE_OFF"),
    "package_output": ("Output", "OUTPUT"),
    "set_source": ("Source Status", "RENDERLAYERS"),
    "set_visibility": ("Visibility", "HIDE_OFF"),
    "set_select": ("Selection", "RESTRICT_SELECT_OFF"),
    "set_pin": ("Pin", "PINNED"),
    "output_enabled": ("Enabled", "CHECKBOX_HLT"),
    "output_link": ("Linked", "LINKED"),
    "output_format": ("Output Settings", "IMAGE_DATA"),
    "stack_enabled": ("Enabled", "CHECKBOX_HLT"),
    "stack_link": ("Connection", "LINKED"),
}

UILIST_PROFILES = {
    "LAYER_PLANES": {
        "fixed_grip": True,
        "label": "Plane Layer List", "icon": "RENDERLAYERS",
        "preview_label": "Layer Name",
        "columns": ("preview", "clipping", "label", "visibility", "solo", "holdout", "plane", "lock", "select"),
    },
    "LAYER_GP": {
        "fixed_grip": True,
        "label": "Grease Pencil Layer List", "icon": "OUTLINER_OB_GREASEPENCIL",
        "preview_label": "Grease Pencil Layer",
        "columns": ("preview", "label", "visibility", "solo", "plane", "lock", "select"),
    },
    "EFFECT_IMAGE": {
        "fixed_grip": True,
        "label": "Effect Stack", "icon": "SHADERFX",
        "preview_label": "Effect Name",
        "columns": ("effect_select", "effect_type", "label", "effect_solo", "effect_viewport", "effect_mask"),
    },
    "PENDING_SETUP": {
        "fixed_grip": True,
        "label": "Multiplane Setup List", "icon": "OUTLINER_COLLECTION",
        "preview_label": "Layer Name",
        "columns": ("pending_color", "pending_status", "label", "pending_reverse", "pending_select", "pending_edit", "pending_delete"),
    },
    "LAYER_SETS": {
        "label": "Layer Set List", "icon": "GROUP",
        "preview_label": "Layer Set Name",
        "columns": ("label", "count", "apply"),
    },
    "VISIBILITY_SNAPSHOTS": {
        "label": "Visibility Snapshot List", "icon": "RESTRICT_VIEW_OFF",
        "preview_label": "Snapshot Name",
        "columns": ("label", "count", "apply"),
    },
    "MASK_SOURCES": {
        "label": "Reusable Mask Source List", "icon": "ASSET_MANAGER",
        "preview_label": "Mask Source Name",
        "columns": ("preview", "label", "apply"),
    },
    "EFFECT_STACK_PRESETS": {
        "label": "Effect Stack Preset List", "icon": "SHADERFX",
        "preview_label": "Effect Preset Name",
        "columns": ("preview", "label", "count", "apply"),
    },
    "LAYER_FILTER_PRESETS": {
        "label": "Layer Filter Preset List", "icon": "FILTER",
        "preview_label": "Filter Preset Name",
        "columns": ("preview", "label", "apply"),
    },
    "DRAWINGS": {
        "label": "Drawing List", "icon": "IMAGE_DATA",
        "preview_label": "Drawing Name",
        "columns": ("current", "preview", "label", "remove"),
    },
    "MOTION_ITEMS": {
        "label": "Motion List", "icon": "FORCE_HARMONIC",
        "preview_label": "Motion Name",
        "columns": ("enabled", "preview", "selected", "label", "slot", "link", "remove"),
    },
    "GENERATION_RENAME": {
        "label": "Generation Report List", "icon": "FILE_REFRESH",
        "preview_label": "Generated Item",
        "columns": ("status", "label"),
    },
    "PERFORMANCE_ROWS": {
        "label": "Performance Dashboard List", "icon": "TIME",
        "preview_label": "Performance Item",
        "columns": ("status", "label", "metric_primary", "metric_secondary"),
    },
    "COMPOSITOR_LAYERS": {
        "label": "Compositor Layer List", "icon": "RENDERLAYERS",
        "preview_label": "Compositor Layer",
        "columns": ("label", "compositor_visibility", "compositor_holdout", "compositor_indirect"),
    },
    "COMPOSITOR_EFFECTS": {
        "label": "Compositor Effect List", "icon": "SHADERFX",
        "preview_label": "Compositor Effect",
        "columns": ("label", "compositor_enabled", "compositor_mix"),
    },
    "PROJECT_DOCTOR": {
        "label": "Project Doctor List", "icon": "TOOL_SETTINGS",
        "preview_label": "Project Issue",
        "columns": ("doctor_severity", "label", "doctor_fix", "doctor_select"),
    },
    "COMPOSITOR_PACKAGES": {
        "label": "Compositor Package List", "icon": "NODETREE",
        "preview_label": "Package Name",
        "columns": ("package_select", "package_type", "label", "package_visibility", "package_output"),
    },
    "LAYER_SET_ROWS": {
        "label": "Layer Set Source List", "icon": "RENDERLAYERS",
        "preview_label": "Source Layer",
        "columns": ("set_source", "label", "set_visibility", "set_select", "set_pin"),
    },
    "OUTPUT_PASSES": {
        "label": "Output Pass List", "icon": "OUTPUT",
        "preview_label": "Output Pass",
        "columns": ("label", "output_enabled", "output_link", "output_format"),
    },
    "COMPOSITOR_STACK": {
        "label": "Composite Stack List", "icon": "SHADERFX",
        "preview_label": "Stack Effect",
        "columns": ("label", "stack_enabled", "stack_link"),
    },
}

_UILIST_SPACER_COLUMNS = ("blank_1", "blank_2", "blank_3")
for _uilist_profile in UILIST_PROFILES.values():
    # Spacers are real optional row items: they can be shown, hidden and dragged
    # like icons, but stay hidden in every factory/default layout.
    _uilist_profile.setdefault("spacer_columns", _UILIST_SPACER_COLUMNS)

_UILIST_HEADER_LABELS = {
    "LAYER_PLANES": "Layers",
    "LAYER_GP": "Grease Pencil Layers",
    "EFFECT_IMAGE": "Effect Stack",
    "PENDING_SETUP": "Multiplane Setup",
    "LAYER_SETS": "Layer Sets",
    "VISIBILITY_SNAPSHOTS": "Visibility Snapshots",
    "MASK_SOURCES": "Mask Sources",
    "EFFECT_STACK_PRESETS": "Effect Stack Presets",
    "LAYER_FILTER_PRESETS": "Layer Filter Presets",
    "DRAWINGS": "Drawings",
    "MOTION_ITEMS": "Motion",
    "GENERATION_RENAME": "Generation Report",
    "PERFORMANCE_ROWS": "Performance",
    "COMPOSITOR_LAYERS": "Compositor Layers",
    "COMPOSITOR_EFFECTS": "Compositor Effects",
    "PROJECT_DOCTOR": "Project Doctor",
    "COMPOSITOR_PACKAGES": "Compositor Packages",
    "LAYER_SET_ROWS": "Layer Set Sources",
    "OUTPUT_PASSES": "Output Passes",
    "COMPOSITOR_STACK": "Composite Stack",
}


def _profile_suffix(profile_id: str) -> str:
    return str(profile_id or "").strip().lower()


def fbp_uilist_profile_definition(profile_id: str):
    return UILIST_PROFILES.get(str(profile_id or "").upper())


def fbp_uilist_profile_columns(profile_id, *, include_spacers=True):
    profile = fbp_uilist_profile_definition(profile_id) or {}
    columns = tuple(profile.get("columns", ()))
    if include_spacers:
        columns += tuple(
            key for key in profile.get("spacer_columns", ())
            if key not in columns
        )
    return columns


def fbp_uilist_is_spacer(column_key):
    return str(column_key or "") in _UILIST_SPACER_COLUMNS


def fbp_draw_uilist_spacer(layout):
    """Consume one normal icon cell without drawing interactive chrome."""
    cell = layout.row(align=True)
    cell.ui_units_x = 1.0
    cell.label(text="", icon="BLANK1")


def _normalized_profile_keys(raw_value, defaults):
    defaults = tuple(str(value) for value in defaults if value)
    raw = tuple(
        part.strip() for part in str(raw_value or "").split(",") if part.strip()
    )
    ordered = []
    for key in raw + defaults:
        if key in defaults and key not in ordered:
            ordered.append(key)
    return tuple(ordered)


def fbp_uilist_icon_order(context=None, profile_id="LAYER_PLANES"):
    profile = fbp_uilist_profile_definition(profile_id)
    if not profile:
        return ()
    defaults = fbp_uilist_profile_columns(profile_id)
    profile_key = str(profile_id or "").upper()
    preview = _UILIST_DRAG_PREVIEW_ORDERS.get(profile_key)
    if preview is not None:
        return _normalized_profile_keys(",".join(preview), defaults)
    prefs = fbp_get_addon_preferences(context)
    if prefs is None:
        return defaults
    raw = getattr(prefs, f"uilist_order_{_profile_suffix(profile_id)}", "")
    return _normalized_profile_keys(raw, defaults)


def fbp_set_uilist_drag_preview(profile_id, keys):
    profile = fbp_uilist_profile_definition(profile_id)
    if not profile:
        return False
    normalized = _normalized_profile_keys(
        ",".join(keys or ()),
        fbp_uilist_profile_columns(profile_id),
    )
    _UILIST_DRAG_PREVIEW_ORDERS[str(profile_id or "").upper()] = normalized
    _UILIST_ICON_FLAGS_CACHE.clear()
    return True


def fbp_clear_uilist_drag_preview(profile_id=None):
    if profile_id:
        _UILIST_DRAG_PREVIEW_ORDERS.pop(str(profile_id or "").upper(), None)
    else:
        _UILIST_DRAG_PREVIEW_ORDERS.clear()
    _UILIST_ICON_FLAGS_CACHE.clear()


def fbp_uilist_column_icon_kwargs(column_key, *, active=True, profile_id=""):
    """Return semantic icon kwargs, including custom PNGs where available."""
    key = str(column_key or "")
    profile_id = str(profile_id or "").upper()
    if key == "select" and profile_id in {"LAYER_PLANES", "LAYER_GP"}:
        return {"icon": "CHECKBOX_HLT" if active else "CHECKBOX_DEHLT"}
    if key == "plane" and profile_id == "LAYER_PLANES":
        return {"icon": "RESTRICT_SELECT_OFF"}
    if key in {
        "selected",
        "pending_select",
        "doctor_select",
        "package_select",
        "set_select",
    }:
        # Custom preview controls must only use icons guaranteed by Blender's
        # UILayout enum. Selection state remains dynamic in the real list row.
        return {"icon": "RESTRICT_SELECT_OFF"}
    try:
        from .ui_icons import clipping_mask_icon_kwargs, ui_label_icon_kwargs
        if key == "clipping":
            return clipping_mask_icon_kwargs(bool(active))
        if key in {"holdout", "compositor_holdout"}:
            return ui_label_icon_kwargs("menu.holdout_plane", fallback="CLIPUV_HLT")
        preview_semantic = {
            ("LAYER_PLANES", "preview"): ("menu.image_plane", "IMAGE_DATA"),
            ("LAYER_GP", "preview"): ("menu.gp_layer", "OUTLINER_OB_GREASEPENCIL"),
        }.get((profile_id, key))
        if preview_semantic:
            semantic_name, fallback = preview_semantic
            return ui_label_icon_kwargs(semantic_name, fallback=fallback)
        semantic = {
            "visibility": "layer.visible_on" if active else "layer.visible_off",
            "solo": "layer.solo_on" if active else "layer.solo_off",
            "lock": "layer.lock_on" if active else "layer.lock_off",
        }.get(key)
        if semantic:
            return ui_label_icon_kwargs(semantic, fallback=UILIST_COLUMN_DEFINITIONS[key][1])
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError, KeyError):
        pass
    _label, icon = UILIST_COLUMN_DEFINITIONS.get(key, (key, "DOT"))
    return {"icon": str(icon or "DOT")}


def fbp_uilist_label_alignment(context=None):
    prefs = fbp_get_addon_preferences(context)
    value = str(getattr(prefs, "uilist_label_alignment", "LEFT") or "LEFT").upper()
    return value if value in {"LEFT", "CENTER", "RIGHT"} else "LEFT"


def _fbp_uilist_available_units(context):
    """Estimate the usable width of a UIList row in Blender UI units.

    ``context.region.width`` includes the list box padding and, in most panels,
    the list-side toolbar.  Reserving those units here keeps fixed icon strips
    fixed until the flexible name cell has genuinely run out of room.
    """
    try:
        region_pixels = max(
            20.0,
            float(getattr(context.region, "width", 0) or 0),
        )
        ui_scale = max(
            0.5,
            float(getattr(context.preferences.system, "ui_scale", 1.0) or 1.0),
        )
        return max(1.0, (region_pixels / (20.0 * ui_scale)) - 4.0)
    except (AttributeError, ReferenceError, TypeError, ValueError):
        return 18.0


def fbp_uilist_fixed_row_layouts(
    layout,
    context,
    *,
    left_units=0,
    right_units=0,
    label_alignment=None,
):
    """Return fixed-left, elastic-name and fixed-right UIList row zones."""
    left_units = max(0.0, float(left_units or 0.0))
    right_units = max(0.0, float(right_units or 0.0))
    available_units = _fbp_uilist_available_units(context)

    row = layout.row(align=True)
    row.alignment = "EXPAND"

    if right_units > 0.0:
        # Do not impose an artificial 20% minimum on the text side.  At narrow
        # widths the name must be clipped first; fixed icons may meet only once
        # virtually all text space has disappeared.
        main_fraction = max(
            0.01,
            min(0.999, (available_units - right_units) / available_units),
        )
        outer = row.split(factor=main_fraction, align=True)
        main = outer.row(align=True)
        right = outer.row(align=True)
    else:
        main = row
        right = row.row(align=True)

    main_units = max(0.05, available_units - right_units)
    if left_units > 0.0:
        left_fraction = max(
            0.01,
            min(0.995, left_units / main_units),
        )
        center_split = main.split(factor=left_fraction, align=True)
        left = center_split.row(align=True)
        name = center_split.row(align=True)
    else:
        left = main.row(align=True)
        name = main

    left.alignment = "LEFT"
    left.ui_units_x = max(0.01, left_units)
    name.alignment = str(
        label_alignment or fbp_uilist_label_alignment(context)
    ).upper()
    right.ui_units_x = max(0.01, right_units)
    right.alignment = "RIGHT"
    return {
        "row": row,
        "left": left,
        "name": name,
        "right": right,
    }


def fbp_uilist_row_layouts(
    layout,
    context,
    profile_id,
    *,
    order=None,
    leading_units=0,
    trailing_units=0,
):
    """Return stable left/name/right targets for one customizable UIList row.

    Icons before ``label`` are packed left, icons after it are packed right.
    Dragging an icon across the name therefore changes sides without a second
    preference. The name owns the flexible center cell and is never hidden.
    """
    profile_id = str(profile_id or "").upper()
    order = tuple(order or fbp_uilist_icon_order(context, profile_id))
    visible = set(fbp_uilist_visible_columns(context, profile_id))
    ordered_visible = tuple(key for key in order if key in visible or key == "label")
    try:
        label_index = ordered_visible.index("label")
    except ValueError:
        ordered_visible = ("label",) + ordered_visible
        label_index = 0

    profile = fbp_uilist_profile_definition(profile_id) or {}
    structural_units = 1 if bool(profile.get("fixed_grip", False)) else 0
    left_count = (
        sum(1 for key in ordered_visible[:label_index] if key != "label")
        + structural_units
        + max(0, int(leading_units or 0))
    )
    right_count = (
        sum(1 for key in ordered_visible[label_index + 1:] if key != "label")
        + max(0, int(trailing_units or 0))
    )
    zones = fbp_uilist_fixed_row_layouts(
        layout,
        context,
        left_units=left_count,
        right_units=right_count,
    )
    row = zones["row"]
    left = zones["left"]
    name_cell = zones["name"]
    right = zones["right"]
    targets = {}
    for index, key in enumerate(ordered_visible):
        targets[key] = left if index < label_index else (name_cell if key == "label" else right)
    return {
        "row": row,
        "left": left,
        "name": name_cell,
        "right": right,
        "targets": targets,
        "order": ordered_visible,
    }


def fbp_draw_uilist_profile_preview(layout, context, profile_id, *, draggable=True):
    """Draw the real, shared row preview used by Preferences and list popups."""
    profile = fbp_uilist_profile_definition(profile_id) or {}
    preview_box = layout.box()
    hint = preview_box.row(align=True)
    hint.label(
        text="Row Preview · drag items left or right"
        if draggable
        else "Row Preview",
        icon="MOUSE_LMB" if draggable else "HIDE_OFF",
    )
    zones = fbp_uilist_row_layouts(preview_box, context, profile_id)
    zones["row"].scale_y = 1.15
    if bool(profile.get("fixed_grip", False)):
        # The structural reorder grip is not customizable. It is always the
        # absolute first control on the left.
        zones["left"].label(text="", icon="GRIP_V")
    flags = fbp_uilist_icon_flags(context, profile_id)
    sample_label = str(profile.get("preview_label", "Layer Name") or "Layer Name")
    for key in zones["order"]:
        if key != "label" and not bool(flags.get(key, True)):
            continue
        target = zones["targets"].get(key, zones["right"])
        if draggable:
            control = target.operator(
                "fbp.uilist_column_drag",
                text=sample_label if key == "label" else "",
                emboss=False,
                **(
                    {}
                    if key == "label"
                    else fbp_uilist_column_icon_kwargs(
                        key, active=True, profile_id=profile_id
                    )
                ),
            )
            control.profile = str(profile_id or "")
            control.column_key = key
        elif key == "label":
            target.label(text=sample_label)
        else:
            target.label(
                text="",
                **fbp_uilist_column_icon_kwargs(
                    key, active=True, profile_id=profile_id
                ),
            )
    return preview_box


def fbp_draw_uilist_header(
    layout,
    context,
    profile_id,
    *,
    title="",
    icon="",
    native_layer_filter=False,
):
    """Draw the common title / Filter / row-customization header."""
    profile_id = str(profile_id or "").upper()
    profile = fbp_uilist_profile_definition(profile_id) or {}
    title = str(
        title
        or _UILIST_HEADER_LABELS.get(profile_id)
        or profile.get("label", "List")
    )
    icon = str(icon or profile.get("icon", "PRESET") or "PRESET")
    container = layout.box()
    header = container.split(factor=0.52, align=True)
    left = header.row(align=True)
    left.alignment = "LEFT"
    left.label(text=title, icon=icon)
    right = header.row(align=True)
    right.alignment = "RIGHT"
    filter_cell = right.row(align=True)
    filter_cell.ui_units_x = 5.75
    if native_layer_filter:
        filter_cell.popover(
            panel="FBP_PT_layer_filters_popover",
            text="Filter",
            icon="FILTER",
        )
    else:
        filter_op = filter_cell.operator(
            "fbp.uilist_filter_popup",
            text="Filter",
            icon="FILTER",
        )
        filter_op.profile = profile_id
    columns = right.operator(
        "fbp.uilist_columns_popup",
        text="",
        icon="THREE_DOTS",
    )
    columns.profile = profile_id
    return container


def fbp_filter_uilist_items(
    context,
    items,
    profile_id,
    bitflag_filter_item,
    *,
    attributes=("name", "label", "filepath", "effect_id"),
):
    """Apply the shared header search/sort state to a conventional UIList."""
    items = tuple(items or ())
    profile_key = _profile_suffix(profile_id)
    scene = getattr(context, "scene", None) if context is not None else None
    try:
        query = str(
            scene.get(f"fbp_uilist_filter_{profile_key}", "") or ""
        ).strip().casefold() if scene is not None else ""
        alphabetical = bool(
            scene.get(f"fbp_uilist_sort_{profile_key}", False)
        ) if scene is not None else False
        reverse = bool(
            scene.get(f"fbp_uilist_reverse_{profile_key}", False)
        ) if scene is not None else False
    except FBP_DATA_ERRORS:
        query, alphabetical, reverse = "", False, False

    def item_text(item):
        values = []
        for attribute in tuple(attributes or ()):
            try:
                value = getattr(item, attribute, "")
            except FBP_DATA_ERRORS:
                value = ""
            if value not in {None, ""}:
                values.append(str(value))
        return " ".join(values).casefold()

    searchable = [item_text(item) for item in items]
    flags = [
        bitflag_filter_item
        if not query or query in searchable[index]
        else 0
        for index in range(len(items))
    ]
    order = list(range(len(items)))
    if alphabetical:
        order.sort(key=lambda index: (searchable[index], index))
    if reverse:
        order.reverse()
    native = list(range(len(items)))
    return flags, order if order != native else []


def fbp_uilist_visible_columns(context=None, profile_id="LAYER_PLANES"):
    profile = fbp_uilist_profile_definition(profile_id)
    if not profile:
        return frozenset()
    defaults = tuple(profile.get("columns", ()))
    allowed = fbp_uilist_profile_columns(profile_id)
    prefs = fbp_get_addon_preferences(context)
    if prefs is None:
        return frozenset(defaults)
    attr = f"uilist_visible_{_profile_suffix(profile_id)}"
    raw = str(getattr(prefs, attr, "") or "")
    if not raw:
        return frozenset(defaults)
    visible = {key for key in raw.split(",") if key in allowed}
    # Preference strings survive 7.1.x updates. Columns introduced after
    # the stored order was written should appear once by default, while columns
    # explicitly hidden in a current order must remain hidden.
    order_attr = f"uilist_order_{_profile_suffix(profile_id)}"
    stored_order = {
        key for key in str(getattr(prefs, order_attr, "") or "").split(",")
        if key in allowed
    }
    visible.update(
        key
        for key in defaults
        if key not in stored_order and not fbp_uilist_is_spacer(key)
    )
    if "label" in defaults:
        visible.add("label")
    return frozenset(visible)


def fbp_set_uilist_profile_order(prefs, profile_id, keys):
    profile = fbp_uilist_profile_definition(profile_id)
    if prefs is None or not profile:
        return False
    normalized = _normalized_profile_keys(
        ",".join(keys or ()),
        fbp_uilist_profile_columns(profile_id),
    )
    setattr(prefs, f"uilist_order_{_profile_suffix(profile_id)}", ",".join(normalized))
    clear_interface_preferences_cache()
    return True


def fbp_set_uilist_profile_visibility(prefs, profile_id, keys):
    profile = fbp_uilist_profile_definition(profile_id)
    if prefs is None or not profile:
        return False
    defaults = fbp_uilist_profile_columns(profile_id)
    requested = set(keys or ())
    if "label" in defaults:
        requested.add("label")
    visible = tuple(key for key in defaults if key in requested)
    # Persist the normalized current order together with visibility. This marks
    # newly introduced columns as known, so hiding one does not make the update
    # branch above reveal it again.
    order_attr = f"uilist_order_{_profile_suffix(profile_id)}"
    current_order = _normalized_profile_keys(
        str(getattr(prefs, order_attr, "") or ""),
        defaults,
    )
    setattr(
        prefs,
        order_attr,
        ",".join(_normalized_profile_keys(",".join(current_order), defaults)),
    )
    setattr(prefs, f"uilist_visible_{_profile_suffix(profile_id)}", ",".join(visible))
    try:
        prefs.uilist_icon_preset = "CUSTOM"
    except FBP_DATA_ERRORS:
        pass
    clear_interface_preferences_cache()
    return True


_UILIST_FLAGS_FULL = {
    "preview": True, "clipping": True, "visibility": True,
    "solo": True, "holdout": True, "motion": True, "plane": True,
    "lock": True, "select": True,
    "effect_type": True, "effect_select": True, "effect_solo": True,
    "effect_viewport": True, "effect_mask": True,
}
_UILIST_FLAGS_ESSENTIAL = {
    "preview": True, "clipping": True, "visibility": True,
    "solo": False, "holdout": False, "motion": False, "plane": False,
    "lock": True, "select": True,
    "effect_type": True, "effect_select": True, "effect_solo": False,
    "effect_viewport": True, "effect_mask": True,
}
_UILIST_FLAGS_MINIMAL = {
    "preview": False, "clipping": False, "visibility": True,
    "solo": False, "holdout": False, "motion": False, "plane": False,
    "lock": False, "select": True,
    "effect_type": False, "effect_select": True, "effect_solo": False,
    "effect_viewport": True, "effect_mask": False,
}


def clear_interface_preferences_cache() -> None:
    """Invalidate lightweight preference caches after RNA or UI changes."""
    global _ADDON_PREFERENCES_KEY
    _ADDON_PREFERENCES_KEY = ""
    _UILIST_ICON_FLAGS_CACHE.clear()


def fbp_get_addon_preferences(context=None):
    """Return a freshly resolved Frame By Plane preferences object.

    Only the add-on key is cached. Keeping the AddonPreferences RNA wrapper
    globally made hot UI paths vulnerable to stale data after extension reload,
    factory preference resets or workspace replacement.
    """
    global _ADDON_PREFERENCES_KEY
    context = context or getattr(bpy, "context", None)
    preferences = getattr(context, "preferences", None) if context else None
    addons = getattr(preferences, "addons", None) if preferences else None
    if addons is None:
        return None

    package = str(__package__ or "frame_by_plane")
    candidate_keys = []
    for key in (_ADDON_PREFERENCES_KEY, package, "frame_by_plane"):
        key = str(key or "")
        if key and key not in candidate_keys:
            candidate_keys.append(key)
    for key in candidate_keys:
        try:
            addon = addons.get(key)
            prefs = getattr(addon, "preferences", None) if addon else None
            if prefs is not None:
                _ADDON_PREFERENCES_KEY = key
                return prefs
        except FBP_DATA_ERRORS:
            continue
    try:
        for key, addon in addons.items():
            key = str(key or "")
            if key.endswith(".frame_by_plane") or key == "frame_by_plane":
                prefs = getattr(addon, "preferences", None)
                if prefs is not None:
                    _ADDON_PREFERENCES_KEY = key
                    return prefs
    except FBP_DATA_ERRORS:
        pass
    _ADDON_PREFERENCES_KEY = ""
    return None


def fbp_uilist_icon_flags(context=None, profile_id=None):
    """Return cached visibility flags, optionally scoped to one UIList profile."""
    prefs = fbp_get_addon_preferences(context)
    preset = str(getattr(prefs, "uilist_icon_preset", "FULL") or "FULL").upper() if prefs else "FULL"
    if preset == "ESSENTIAL":
        base = _UILIST_FLAGS_ESSENTIAL
    elif preset == "MINIMAL":
        base = _UILIST_FLAGS_MINIMAL
    elif preset != "CUSTOM" or prefs is None:
        base = _UILIST_FLAGS_FULL
    else:
        signature = (
            bool(getattr(prefs, "uilist_show_preview", True)),
            bool(getattr(prefs, "uilist_show_clipping", True)),
            bool(getattr(prefs, "uilist_show_visibility", True)),
            bool(getattr(prefs, "uilist_show_solo", True)),
            bool(getattr(prefs, "uilist_show_holdout", True)),
            bool(getattr(prefs, "uilist_show_motion", True)),
            bool(getattr(prefs, "uilist_show_plane", True)),
            bool(getattr(prefs, "uilist_show_lock", True)),
            bool(getattr(prefs, "uilist_show_select", True)),
            bool(getattr(prefs, "uilist_show_effect_type", True)),
            bool(getattr(prefs, "uilist_show_effect_viewport", True)),
            bool(getattr(prefs, "uilist_show_effect_mask", True)),
        )
        cache_key = ("BASE",) + signature
        base = _UILIST_ICON_FLAGS_CACHE.get(cache_key)
        if base is None:
            (
                preview, clipping, visibility, solo, holdout, motion, plane, lock,
                select, effect_type, effect_viewport, effect_mask,
            ) = signature
            base = {
                "preview": preview, "clipping": clipping, "visibility": visibility,
                "solo": solo, "holdout": holdout, "motion": motion, "plane": plane,
                "lock": lock, "select": select,
                "effect_type": effect_type, "effect_solo": solo,
                "effect_viewport": effect_viewport,
                "effect_mask": effect_mask,
            }
            _UILIST_ICON_FLAGS_CACHE[cache_key] = base

    if not profile_id:
        return base
    visible = fbp_uilist_visible_columns(context, profile_id)
    # Named presets are complete visual modes. Per-list visibility becomes the
    # authority only in Custom mode, avoiding a stale hidden-column preference
    # silently weakening Full/Essential/Minimal previews.
    profile_base = _UILIST_FLAGS_FULL if preset == "CUSTOM" else base
    cache_key = (
        "PROFILE", str(profile_id).upper(), preset, tuple(sorted(visible)),
        tuple(sorted(profile_base.items())),
    )
    cached = _UILIST_ICON_FLAGS_CACHE.get(cache_key)
    if cached is not None:
        return cached
    scoped = dict(profile_base)
    profile = fbp_uilist_profile_definition(profile_id) or {}
    for key in fbp_uilist_profile_columns(profile_id):
        if fbp_uilist_is_spacer(key):
            scoped[key] = bool(preset == "CUSTOM" and key in visible)
            continue
        default_enabled = not fbp_uilist_is_spacer(key)
        scoped[key] = bool(
            profile_base.get(key, default_enabled)
            and (preset != "CUSTOM" or key in visible)
        )
    if len(_UILIST_ICON_FLAGS_CACHE) >= 64:
        _UILIST_ICON_FLAGS_CACHE.clear()
    _UILIST_ICON_FLAGS_CACHE[cache_key] = scoped
    return scoped


__all__ = (
    "clear_interface_preferences_cache",
    "fbp_get_addon_preferences",
    "fbp_uilist_icon_flags",
    "fbp_uilist_icon_order",
    "fbp_set_uilist_drag_preview",
    "fbp_clear_uilist_drag_preview",
    "fbp_uilist_column_icon_kwargs",
    "fbp_uilist_fixed_row_layouts",
    "fbp_draw_uilist_profile_preview",
    "fbp_draw_uilist_header",
    "fbp_filter_uilist_items",
    "fbp_uilist_visible_columns",
    "fbp_uilist_profile_definition",
    "fbp_uilist_profile_columns",
    "fbp_uilist_is_spacer",
    "fbp_draw_uilist_spacer",
    "fbp_set_uilist_profile_order",
    "fbp_set_uilist_profile_visibility",
    "UILIST_COLUMN_DEFINITIONS",
    "UILIST_PROFILES",
)
