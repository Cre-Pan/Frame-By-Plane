"""Fast, persistent search and filters for the managed Layer Tree."""

from __future__ import annotations

import bpy
from bpy.props import (
    CollectionProperty,
    EnumProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Menu, Operator, Panel, PropertyGroup, UIList

from .grease_pencil_bridge import (
    gp_canvas_owner,
    gp_canvas_solo_active,
    is_gp_drawing_canvas,
)
from .layers import (
    fbp_layer_backend_type,
    fbp_layer_clipping_active_hint,
    fbp_set_ui_units_x,
)
from .registration import (
    register_classes,
    register_interactive_classes,
    unregister_classes,
    unregister_type_properties,
)
from .runtime import FBP_DATA_ERRORS, fbp_request_redraw
from .ui_style import configure_layout, hint_row, section_header
from .ui_list_state import mark_ui_list_draw
from .interface_preferences import (
    fbp_draw_uilist_spacer,
    fbp_draw_uilist_header,
    fbp_filter_uilist_items,
    fbp_uilist_icon_order,
    fbp_uilist_is_spacer,
    fbp_uilist_visible_columns,
)


LAYER_FILTER_SCHEMA_VERSION = 1

LAYER_FILTER_TYPE_ITEMS = (
    ("ALL", "All Types", "Show every managed layer type"),
    ("PLANE", "All Plane Layers", "Show image, sequence, video and procedural planes"),
    ("IMAGE", "Image", "Show static image and cutout planes"),
    ("SEQUENCE", "Sequence", "Show native image sequence planes"),
    ("VIDEO", "Video", "Show native movie planes"),
    ("COLOR", "Color", "Show solid procedural color planes"),
    ("GRADIENT", "Gradient", "Show procedural gradient planes"),
    ("HOLDOUT", "Holdout", "Show procedural holdout planes"),
    ("GP", "Grease Pencil", "Show Grease Pencil canvases and their internal layers"),
)

LAYER_FILTER_COLOR_ITEMS = (
    ("ALL", "All Colors", "Do not filter by color tag"),
    ("NONE", "No Color", "Show layers without a color tag"),
    ("COLOR_01", "Red", "Show red-tagged layers"),
    ("COLOR_02", "Orange", "Show orange-tagged layers"),
    ("COLOR_03", "Yellow", "Show yellow-tagged layers"),
    ("COLOR_04", "Green", "Show green-tagged layers"),
    ("COLOR_05", "Cyan", "Show cyan-tagged layers"),
    ("COLOR_06", "Purple", "Show purple-tagged layers"),
    ("COLOR_07", "Magenta", "Show magenta-tagged layers"),
)

LAYER_FILTER_STATE_ITEMS = (
    ("ALL", "All States", "Do not filter by layer state"),
    ("VISIBLE", "Visible", "Show layers visible in the viewport"),
    ("HIDDEN", "Hidden", "Show layers hidden in the viewport"),
    ("SELECTED", "Selected", "Show selected layers"),
    ("LOCKED", "Locked", "Show layers locked against selection"),
    ("UNLOCKED", "Unlocked", "Show layers that are not locked"),
    ("SOLO", "Solo", "Show soloed layers"),
    ("RENDER_DISABLED", "Render Disabled", "Show layers disabled for render"),
)

LAYER_FILTER_PRESENCE_ITEMS = (
    ("ALL", "Any", "Do not filter this capability"),
    ("WITH", "With", "Show layers that use this capability"),
    ("WITHOUT", "Without", "Show layers that do not use this capability"),
)

_FILTER_PROPERTY_NAMES = (
    "fbp_layer_filter_search",
    "fbp_layer_filter_type",
    "fbp_layer_filter_color",
    "fbp_layer_filter_state",
    "fbp_layer_filter_effect",
    "fbp_layer_filter_mask",
    "fbp_layer_filter_motion",
)

def _safe_text(value):
    try:
        return str(value or "").strip()
    except FBP_DATA_ERRORS:
        return ""


def layer_filter_is_active(scene):
    if scene is None:
        return False
    try:
        return bool(
            _safe_text(scene.fbp_layer_filter_search)
            or scene.fbp_layer_filter_type != "ALL"
            or scene.fbp_layer_filter_color != "ALL"
            or scene.fbp_layer_filter_state != "ALL"
            or scene.fbp_layer_filter_effect != "ALL"
            or scene.fbp_layer_filter_mask != "ALL"
            or scene.fbp_layer_filter_motion != "ALL"
        )
    except FBP_DATA_ERRORS:
        return False


def _filter_update(_owner, context):
    scene = getattr(context, "scene", None)
    if scene is None:
        return
    try:
        scene.fbp_layer_tree_signature = ""
    except FBP_DATA_ERRORS:
        pass
    try:
        from .ui_layout import fbp_invalidate_layer_tree_snapshot

        fbp_invalidate_layer_tree_snapshot(scene)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError):
        pass
    fbp_request_redraw(context, area_types=("VIEW_3D",))


class FBP_LayerFilterPreset(PropertyGroup):
    name: StringProperty(
        name="Name",
        description="Name of this reusable Layer List filter",
        default="Layer Filter",
    )
    schema_version: IntProperty(
        default=LAYER_FILTER_SCHEMA_VERSION,
        min=1,
        options={"HIDDEN"},
    )
    search: StringProperty(name="Search", default="")
    layer_type: EnumProperty(
        name="Type",
        items=LAYER_FILTER_TYPE_ITEMS,
        default="ALL",
    )
    color: EnumProperty(
        name="Color",
        items=LAYER_FILTER_COLOR_ITEMS,
        default="ALL",
    )
    state: EnumProperty(
        name="State",
        items=LAYER_FILTER_STATE_ITEMS,
        default="ALL",
    )
    effect: EnumProperty(
        name="Effects",
        items=LAYER_FILTER_PRESENCE_ITEMS,
        default="ALL",
    )
    mask: EnumProperty(
        name="Masks",
        items=LAYER_FILTER_PRESENCE_ITEMS,
        default="ALL",
    )
    motion: EnumProperty(
        name="Motion",
        items=LAYER_FILTER_PRESENCE_ITEMS,
        default="ALL",
    )


def _active_preset(scene):
    try:
        presets = scene.fbp_layer_filter_presets
        if not presets:
            return None, -1
        index = max(
            0,
            min(int(scene.fbp_layer_filter_presets_index), len(presets) - 1),
        )
        return presets[index], index
    except FBP_DATA_ERRORS:
        return None, -1


def _unique_preset_name(scene, base="Layer Filter"):
    base = _safe_text(base) or "Layer Filter"
    try:
        existing = {
            _safe_text(preset.name).casefold()
            for preset in scene.fbp_layer_filter_presets
        }
    except FBP_DATA_ERRORS:
        existing = set()
    if base.casefold() not in existing:
        return base
    number = 2
    while f"{base} {number}".casefold() in existing:
        number += 1
    return f"{base} {number}"


def _capture_filter(scene, preset):
    preset.schema_version = LAYER_FILTER_SCHEMA_VERSION
    preset.search = _safe_text(scene.fbp_layer_filter_search)
    preset.layer_type = scene.fbp_layer_filter_type
    preset.color = scene.fbp_layer_filter_color
    preset.state = scene.fbp_layer_filter_state
    preset.effect = scene.fbp_layer_filter_effect
    preset.mask = scene.fbp_layer_filter_mask
    preset.motion = scene.fbp_layer_filter_motion


def _apply_filter(scene, preset):
    scene.fbp_layer_filter_search = _safe_text(preset.search)
    scene.fbp_layer_filter_type = preset.layer_type
    scene.fbp_layer_filter_color = preset.color
    scene.fbp_layer_filter_state = preset.state
    scene.fbp_layer_filter_effect = preset.effect
    scene.fbp_layer_filter_mask = preset.mask
    scene.fbp_layer_filter_motion = preset.motion


def reset_layer_filter(scene):
    if scene is None:
        return False
    scene.fbp_layer_filter_search = ""
    scene.fbp_layer_filter_type = "ALL"
    scene.fbp_layer_filter_color = "ALL"
    scene.fbp_layer_filter_state = "ALL"
    scene.fbp_layer_filter_effect = "ALL"
    scene.fbp_layer_filter_mask = "ALL"
    scene.fbp_layer_filter_motion = "ALL"
    return True


def _row_target(scene, row):
    row_type = _safe_text(getattr(row, "row_type", "")).upper()
    if row_type == "LAYER":
        name = _safe_text(getattr(row, "rig_name", ""))
        rig = bpy.data.objects.get(name) if name else None
        if rig is None:
            try:
                index = int(getattr(row, "layer_index", -1))
                if 0 <= index < len(scene.fbp_layers):
                    rig = scene.fbp_layers[index].obj
            except FBP_DATA_ERRORS:
                rig = None
        return rig, rig, row_type
    if row_type in {"GP_CANVAS", "GP_LAYER"}:
        name = _safe_text(getattr(row, "canvas_name", ""))
        canvas = bpy.data.objects.get(name) if name else None
        if canvas is not None and not is_gp_drawing_canvas(canvas):
            canvas = None
        owner = gp_canvas_owner(canvas) if canvas is not None else None
        return canvas, owner or canvas, row_type
    return None, None, row_type


def _layer_item(scene, row, rig):
    try:
        index = int(getattr(row, "layer_index", -1))
        if 0 <= index < len(scene.fbp_layers):
            item = scene.fbp_layers[index]
            if item.obj == rig:
                return item
    except FBP_DATA_ERRORS:
        pass
    return None


def _target_type(target, row_type):
    if row_type in {"GP_CANVAS", "GP_LAYER"}:
        return "GP"
    backend = fbp_layer_backend_type(target)
    return {
        "NATIVE_IMAGE": "IMAGE",
        "CUTOUT": "IMAGE",
        "NATIVE_SEQUENCE": "SEQUENCE",
        "NATIVE_MOVIE": "VIDEO",
        "PROCEDURAL_COLOR": "COLOR",
        "PROCEDURAL_GRADIENT": "GRADIENT",
        "PROCEDURAL_HOLDOUT": "HOLDOUT",
    }.get(_safe_text(backend).upper(), "PLANE")


def _effect_capabilities(owner, cache):
    if owner is None:
        return False, False
    try:
        key = int(owner.as_pointer())
    except FBP_DATA_ERRORS:
        key = id(owner)
    cached = cache.get(key)
    if cached is not None:
        return cached
    has_effect = False
    has_mask = False
    try:
        from .effects_registry import fbp_effect_definition

        for item in tuple(getattr(owner, "fbp_effects", ()) or ()):
            effect_id = _safe_text(getattr(item, "effect_id", "")).upper()
            if not effect_id:
                continue
            definition = fbp_effect_definition(effect_id) or {}
            if _safe_text(definition.get("kind", "")).upper() == "BASE":
                continue
            category = _safe_text(definition.get("category", "")).upper()
            if category == "MASK" or "MASK" in effect_id:
                has_mask = True
            else:
                has_effect = True
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError):
        pass
    try:
        has_mask = has_mask or bool(fbp_layer_clipping_active_hint(owner))
    except FBP_DATA_ERRORS:
        pass
    cached = (has_effect, has_mask)
    cache[key] = cached
    return cached


def _has_motion(owner):
    if owner is None:
        return False
    try:
        return bool(
            len(getattr(owner, "fbp_motions", ()) or ())
            or owner.get("fbp_motion_effect_container", False)
        )
    except FBP_DATA_ERRORS:
        return False


def _presence_matches(mode, present):
    mode = _safe_text(mode).upper() or "ALL"
    if mode == "WITH":
        return bool(present)
    if mode == "WITHOUT":
        return not bool(present)
    return True


def _row_matches(context, row, effect_cache):
    scene = context.scene
    target, capability_owner, row_type = _row_target(scene, row)
    if target is None:
        return False

    query = _safe_text(scene.fbp_layer_filter_search).casefold()
    if query:
        names = (
            _safe_text(getattr(row, "name", "")),
            _safe_text(getattr(row, "rig_name", "")),
            _safe_text(getattr(row, "canvas_name", "")),
            _safe_text(getattr(row, "gp_layer_name", "")),
            _safe_text(getattr(row, "collection_name", "")),
        )
        if not any(query in name.casefold() for name in names if name):
            return False

    wanted_type = _safe_text(scene.fbp_layer_filter_type).upper() or "ALL"
    actual_type = _target_type(target, row_type)
    if wanted_type == "PLANE":
        if row_type != "LAYER":
            return False
    elif wanted_type != "ALL" and actual_type != wanted_type:
        return False

    wanted_color = _safe_text(scene.fbp_layer_filter_color).upper() or "ALL"
    if wanted_color != "ALL":
        actual_color = _safe_text(
            getattr(target, "fbp_color_tag", "NONE")
            or getattr(capability_owner, "fbp_color_tag", "NONE")
        ).upper() or "NONE"
        if actual_color != wanted_color:
            return False

    item = _layer_item(scene, row, target) if row_type == "LAYER" else None
    wanted_state = _safe_text(scene.fbp_layer_filter_state).upper() or "ALL"
    if row_type == "LAYER":
        visible = bool(getattr(target, "fbp_is_visible", True))
        locked = bool(
            getattr(item, "rig_locked", False)
            if item is not None
            else getattr(target, "hide_select", False)
        )
        solo = bool(
            getattr(item, "solo_view", False)
            if item is not None
            else False
        )
        plane = getattr(target, "fbp_plane_target", None)
        render_visible = not bool(
            getattr(plane if plane is not None else target, "hide_render", False)
        )
    else:
        visible = bool(getattr(target, "fbp_gp_canvas_visible", True))
        locked = bool(getattr(target, "hide_select", False))
        solo = bool(gp_canvas_solo_active(target))
        render_visible = bool(getattr(target, "fbp_gp_canvas_render", True))
    try:
        selected = bool(target.select_get())
    except FBP_DATA_ERRORS:
        selected = False
    state_matches = {
        "ALL": True,
        "VISIBLE": visible,
        "HIDDEN": not visible,
        "SELECTED": selected,
        "LOCKED": locked,
        "UNLOCKED": not locked,
        "SOLO": solo,
        "RENDER_DISABLED": not render_visible,
    }
    if not state_matches.get(wanted_state, True):
        return False

    has_effect, has_mask = _effect_capabilities(capability_owner, effect_cache)
    if not _presence_matches(scene.fbp_layer_filter_effect, has_effect):
        return False
    if not _presence_matches(scene.fbp_layer_filter_mask, has_mask):
        return False
    if not _presence_matches(
        scene.fbp_layer_filter_motion,
        _has_motion(capability_owner),
    ):
        return False
    return True


def filter_layer_tree_items(context, items, mode, bitflag):
    """Return Blender UIList flags with parent groups preserved."""
    rows = tuple(items or ())
    if not rows:
        return []
    from .ui_layout import fbp_layer_tree_row_visible_for_mode

    base = [
        bool(fbp_layer_tree_row_visible_for_mode(row, mode))
        for row in rows
    ]
    scene = getattr(context, "scene", None)
    if scene is None or not layer_filter_is_active(scene):
        return [bitflag if visible else 0 for visible in base]

    matches = [False] * len(rows)
    effect_cache = {}
    query = _safe_text(scene.fbp_layer_filter_search).casefold()
    non_text_filters = bool(
        scene.fbp_layer_filter_type != "ALL"
        or scene.fbp_layer_filter_color != "ALL"
        or scene.fbp_layer_filter_state != "ALL"
        or scene.fbp_layer_filter_effect != "ALL"
        or scene.fbp_layer_filter_mask != "ALL"
        or scene.fbp_layer_filter_motion != "ALL"
    )
    for index, row in enumerate(rows):
        if not base[index]:
            continue
        row_type = _safe_text(getattr(row, "row_type", "")).upper()
        if row_type == "GROUP":
            if (
                query
                and not non_text_filters
                and query in _safe_text(getattr(row, "name", "")).casefold()
            ):
                matches[index] = True
            continue
        matches[index] = _row_matches(context, row, effect_cache)

    # The flattened tree is preorder. Propagate every matching descendant to
    # its visible parent chain in one reverse pass.
    group_stack = []
    for index, row in enumerate(rows):
        depth = max(0, int(getattr(row, "depth", 0) or 0))
        while group_stack and group_stack[-1][0] >= depth:
            group_stack.pop()
        if matches[index]:
            for _ancestor_depth, ancestor_index in group_stack:
                if base[ancestor_index]:
                    matches[ancestor_index] = True
        if _safe_text(getattr(row, "row_type", "")).upper() == "GROUP":
            group_stack.append((depth, index))
    return [
        bitflag if base[index] and matches[index] else 0
        for index in range(len(rows))
    ]


def audit_layer_filter_presets(scene):
    issues = []
    seen = set()
    try:
        presets = tuple(scene.fbp_layer_filter_presets)
    except FBP_DATA_ERRORS:
        return ()
    for index, preset in enumerate(presets):
        name = _safe_text(preset.name)
        if not name:
            issues.append(
                {
                    "index": index,
                    "severity": "WARNING",
                    "message": "A saved Layer Filter has no name",
                }
            )
        key = name.casefold()
        if key and key in seen:
            issues.append(
                {
                    "index": index,
                    "severity": "WARNING",
                    "message": f'Duplicate Layer Filter name "{name}"',
                }
            )
        if key:
            seen.add(key)
        if int(getattr(preset, "schema_version", 1) or 1) > LAYER_FILTER_SCHEMA_VERSION:
            issues.append(
                {
                    "index": index,
                    "severity": "WARNING",
                    "message": f'{name or "Layer Filter"} uses a newer schema',
                }
            )
    return tuple(issues)


def repair_layer_filter_presets(scene):
    """Repair only empty/duplicate names; never discard saved criteria."""
    renamed = 0
    used = set()
    try:
        presets = tuple(scene.fbp_layer_filter_presets)
    except FBP_DATA_ERRORS:
        return 0
    for preset in presets:
        original = _safe_text(preset.name)
        base = original or "Layer Filter"
        candidate = base
        number = 2
        while candidate.casefold() in used:
            candidate = f"{base} {number}"
            number += 1
        used.add(candidate.casefold())
        if candidate != original:
            preset.name = candidate
            renamed += 1
    return renamed


class FBP_OT_ResetLayerFilter(Operator):
    bl_idname = "fbp.reset_layer_filter"
    bl_label = "Clear Layer Filters"
    bl_description = "Clear Layer List search and every active filter"

    def execute(self, context):
        reset_layer_filter(context.scene)
        return {"FINISHED"}


class FBP_OT_AddLayerFilterPreset(Operator):
    bl_idname = "fbp.add_layer_filter_preset"
    bl_label = "Save Layer Filter"
    bl_description = "Save the current Layer List search and filters in this blend file"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        name = _unique_preset_name(scene)
        preset = scene.fbp_layer_filter_presets.add()
        preset.name = name
        _capture_filter(scene, preset)
        scene.fbp_layer_filter_presets_index = len(scene.fbp_layer_filter_presets) - 1
        self.report({"INFO"}, f'Saved Layer Filter "{name}"')
        return {"FINISHED"}


class FBP_OT_UpdateLayerFilterPreset(Operator):
    bl_idname = "fbp.update_layer_filter_preset"
    bl_label = "Update Layer Filter"
    bl_description = "Replace the selected preset with the current Layer List filters"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        preset, _index = _active_preset(context.scene)
        if preset is None:
            return {"CANCELLED"}
        _capture_filter(context.scene, preset)
        self.report({"INFO"}, f'Updated Layer Filter "{preset.name}"')
        return {"FINISHED"}


class FBP_OT_ApplyLayerFilterPreset(Operator):
    bl_idname = "fbp.apply_layer_filter_preset"
    bl_label = "Apply Layer Filter"
    bl_description = "Use the selected saved Layer List filter"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(default=-1, options={"HIDDEN"})

    def execute(self, context):
        scene = context.scene
        index = int(self.index)
        if index < 0:
            _preset, index = _active_preset(scene)
        if not (0 <= index < len(scene.fbp_layer_filter_presets)):
            return {"CANCELLED"}
        scene.fbp_layer_filter_presets_index = index
        _apply_filter(scene, scene.fbp_layer_filter_presets[index])
        return {"FINISHED"}


class FBP_OT_RemoveLayerFilterPreset(Operator):
    bl_idname = "fbp.remove_layer_filter_preset"
    bl_label = "Remove Layer Filter"
    bl_description = "Remove the selected saved filter without changing any layer"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        preset, index = _active_preset(scene)
        if preset is None:
            return {"CANCELLED"}
        name = _safe_text(preset.name) or "Layer Filter"
        scene.fbp_layer_filter_presets.remove(index)
        scene.fbp_layer_filter_presets_index = min(
            index,
            max(0, len(scene.fbp_layer_filter_presets) - 1),
        )
        self.report({"INFO"}, f'Removed Layer Filter "{name}"')
        return {"FINISHED"}


class FBP_OT_MoveLayerFilterPreset(Operator):
    bl_idname = "fbp.move_layer_filter_preset"
    bl_label = "Move Layer Filter"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        items=(("UP", "Up", ""), ("DOWN", "Down", "")),
        default="UP",
        options={"HIDDEN"},
    )

    def execute(self, context):
        scene = context.scene
        _preset, index = _active_preset(scene)
        target = index - 1 if self.direction == "UP" else index + 1
        if not (0 <= index < len(scene.fbp_layer_filter_presets)) or not (
            0 <= target < len(scene.fbp_layer_filter_presets)
        ):
            return {"CANCELLED"}
        scene.fbp_layer_filter_presets.move(index, target)
        scene.fbp_layer_filter_presets_index = target
        return {"FINISHED"}


class FBP_MT_LayerFilterPresetActions(Menu):
    bl_idname = "FBP_MT_layer_filter_preset_actions"
    bl_label = "Layer Filter Preset Actions"

    def draw(self, context):
        layout = configure_layout(self.layout)
        preset, _index = _active_preset(context.scene)
        update = layout.row(align=True)
        update.enabled = preset is not None
        update.operator("fbp.update_layer_filter_preset", text="Update Preset", icon="FILE_REFRESH")
        remove = layout.row(align=True)
        remove.enabled = preset is not None
        remove.operator("fbp.remove_layer_filter_preset", text="Remove Preset", icon="TRASH")


class FBP_UL_LayerFilterPresets(UIList):
    _PROFILE = "LAYER_FILTER_PRESETS"

    def filter_items(self, context, data, propname):
        return fbp_filter_uilist_items(
            context, getattr(data, propname, ()), self._PROFILE,
            self.bitflag_filter_item, attributes=("name", "search"),
        )

    def draw_item(
        self, context, layout, data, item, icon,
        active_data, active_propname, index,
    ):
        mark_ui_list_draw()
        row = layout.row(align=True)
        visible = set(fbp_uilist_visible_columns(context, self._PROFILE))
        for key in fbp_uilist_icon_order(context, self._PROFILE):
            if key not in visible:
                continue
            if fbp_uilist_is_spacer(key):
                fbp_draw_uilist_spacer(row)
                continue
            if key == "preview":
                row.label(text="", icon="FILTER")
            elif key == "label":
                row.prop(item, "name", text="", emboss=False)
            elif key == "apply":
                apply = row.operator(
                    "fbp.apply_layer_filter_preset", text="", icon="CHECKMARK", emboss=False
                )
                apply.index = index


class FBP_PT_LayerFiltersPopover(Panel):
    bl_label = "Layer List Search and Filters"
    bl_idname = "FBP_PT_layer_filters_popover"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"

    def draw(self, context):
        scene = context.scene
        layout = configure_layout(self.layout)
        layout.prop(scene, "fbp_layer_filter_search", text="Search", icon="VIEWZOOM")
        grid = layout.grid_flow(columns=1, align=True)
        grid.prop(scene, "fbp_layer_filter_type", text="Type")
        grid.prop(scene, "fbp_layer_filter_color", text="Color")
        grid.prop(scene, "fbp_layer_filter_state", text="State")
        capabilities = layout.box()
        capabilities.label(text="Capabilities", icon="MODIFIER")
        capabilities.prop(scene, "fbp_layer_filter_effect", text="Effects")
        capabilities.prop(scene, "fbp_layer_filter_mask", text="Masks")
        capabilities.prop(scene, "fbp_layer_filter_motion", text="Motion")
        actions = layout.row(align=True)
        actions.operator("fbp.reset_layer_filter", text="Clear", icon="X")
        actions.operator(
            "fbp.add_layer_filter_preset",
            text="Save Current",
            icon="ADD",
        )
        presets = scene.fbp_layer_filter_presets
        if not presets:
            hint_row(
                layout,
                "Saved filters are stored in this .blend file.",
                icon="INFO",
            )
            return
        section_header(
            layout,
            "Saved Filters",
            icon="FILTER",
            count=len(presets),
        )
        list_box = fbp_draw_uilist_header(
            layout, context, "LAYER_FILTER_PRESETS"
        )
        row = list_box.row(align=False)
        row.template_list(
            "FBP_UL_LayerFilterPresets",
            "",
            scene,
            "fbp_layer_filter_presets",
            scene,
            "fbp_layer_filter_presets_index",
            rows=min(4, max(2, len(presets))),
        )
        tools = row.column(align=True)
        fbp_set_ui_units_x(tools, 1.0)
        tools.menu("FBP_MT_layer_filter_preset_actions", text="", icon="COLLAPSEMENU")
        tools.separator()
        movement = tools.column(align=True)
        active_index = int(getattr(scene, "fbp_layer_filter_presets_index", -1))
        up = movement.row(align=True)
        up.enabled = active_index > 0
        operator = up.operator("fbp.move_layer_filter_preset", text="", icon="SORT_DESC")
        operator.direction = "UP"
        down = movement.row(align=True)
        down.enabled = 0 <= active_index < len(presets) - 1
        operator = down.operator("fbp.move_layer_filter_preset", text="", icon="SORT_ASC")
        operator.direction = "DOWN"
        tools.separator()
        tools.operator("fbp.add_layer_filter_preset", text="", icon="ADD")


def draw_layer_filter_bar(layout, context):
    scene = getattr(context, "scene", None)
    if scene is None or not hasattr(scene, "fbp_layer_filter_search"):
        return
    row = layout.row(align=True)
    row.prop(
        scene,
        "fbp_layer_filter_search",
        text="",
        icon="VIEWZOOM",
    )
    row.popover(
        panel="FBP_PT_layer_filters_popover",
        text="",
        icon="FILTER",
    )
    if layer_filter_is_active(scene):
        row.operator("fbp.reset_layer_filter", text="", icon="X")


_model_classes = (FBP_LayerFilterPreset,)
_interactive_classes = (
    FBP_OT_ResetLayerFilter,
    FBP_OT_AddLayerFilterPreset,
    FBP_OT_UpdateLayerFilterPreset,
    FBP_OT_ApplyLayerFilterPreset,
    FBP_OT_RemoveLayerFilterPreset,
    FBP_OT_MoveLayerFilterPreset,
    FBP_MT_LayerFilterPresetActions,
    FBP_UL_LayerFilterPresets,
    FBP_PT_LayerFiltersPopover,
)
_registered_classes = globals().get("_registered_classes", [])
if not isinstance(_registered_classes, list):
    _registered_classes = []


def _register_scene_properties():
    bpy.types.Scene.fbp_layer_filter_search = StringProperty(
        name="Search Layers",
        description="Filter managed layers and collections by name",
        default="",
        update=_filter_update,
    )
    bpy.types.Scene.fbp_layer_filter_type = EnumProperty(
        name="Type",
        items=LAYER_FILTER_TYPE_ITEMS,
        default="ALL",
        update=_filter_update,
    )
    bpy.types.Scene.fbp_layer_filter_color = EnumProperty(
        name="Color",
        items=LAYER_FILTER_COLOR_ITEMS,
        default="ALL",
        update=_filter_update,
    )
    bpy.types.Scene.fbp_layer_filter_state = EnumProperty(
        name="State",
        items=LAYER_FILTER_STATE_ITEMS,
        default="ALL",
        update=_filter_update,
    )
    bpy.types.Scene.fbp_layer_filter_effect = EnumProperty(
        name="Effects",
        items=LAYER_FILTER_PRESENCE_ITEMS,
        default="ALL",
        update=_filter_update,
    )
    bpy.types.Scene.fbp_layer_filter_mask = EnumProperty(
        name="Masks",
        items=LAYER_FILTER_PRESENCE_ITEMS,
        default="ALL",
        update=_filter_update,
    )
    bpy.types.Scene.fbp_layer_filter_motion = EnumProperty(
        name="Motion",
        items=LAYER_FILTER_PRESENCE_ITEMS,
        default="ALL",
        update=_filter_update,
    )
    bpy.types.Scene.fbp_layer_filter_presets = CollectionProperty(
        type=FBP_LayerFilterPreset,
        name="Saved Layer Filters",
        description="Reusable Layer List searches and filters stored in this file",
    )
    bpy.types.Scene.fbp_layer_filter_presets_index = IntProperty(
        name="Saved Layer Filter",
        default=0,
        min=0,
    )


def register():
    unregister_type_properties(
        bpy.types.Scene,
        _FILTER_PROPERTY_NAMES
        + (
            "fbp_layer_filter_presets",
            "fbp_layer_filter_presets_index",
        ),
    )
    _registered_classes.clear()
    try:
        _registered_classes.extend(register_classes(_model_classes))
        _register_scene_properties()
        _registered_classes.extend(
            register_interactive_classes(_interactive_classes)
        )
    except Exception:
        unregister_type_properties(
            bpy.types.Scene,
            _FILTER_PROPERTY_NAMES
            + (
                "fbp_layer_filter_presets",
                "fbp_layer_filter_presets_index",
            ),
        )
        unregister_classes(tuple(_registered_classes))
        _registered_classes.clear()
        raise


def unregister():
    unregister_type_properties(
        bpy.types.Scene,
        _FILTER_PROPERTY_NAMES
        + (
            "fbp_layer_filter_presets",
            "fbp_layer_filter_presets_index",
        ),
    )
    unregister_classes(tuple(_registered_classes))
    _registered_classes.clear()


__all__ = (
    "LAYER_FILTER_SCHEMA_VERSION",
    "layer_filter_is_active",
    "filter_layer_tree_items",
    "reset_layer_filter",
    "audit_layer_filter_presets",
    "repair_layer_filter_presets",
    "draw_layer_filter_bar",
)
