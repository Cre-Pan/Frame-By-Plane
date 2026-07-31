"""Persistent viewport, solo, lock and render states for managed layers."""

from __future__ import annotations

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Menu, Operator, PropertyGroup, UIList

from .fbp_index import iter_scene_fbp_rigs, iter_scene_gp_canvases
from .grease_pencil_bridge import (
    KEY_CANVAS_SOLO,
    gp_canvas_solo_active,
    is_gp_drawing_canvas,
)
from .identifiers import ensure_layer_identity, ensure_mask_identity, stable_id
from .layers import fbp_set_ui_units_x, get_layer_item_for_rig, update_global_visibility
from .registration import (
    register_classes,
    register_interactive_classes,
    unregister_classes,
    unregister_type_properties,
)
from .runtime import (
    FBP_DATA_ERRORS,
    fbp_request_redraw,
    fbp_set_rna_property_silent,
)
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


VISIBILITY_SNAPSHOT_SCHEMA_VERSION = 1

_SNAPSHOT_KINDS = (
    ("LAYER", "Layer", "Frame By Plane plane layer"),
    ("GP", "Grease Pencil", "Frame By Plane Grease Pencil Drawing Plane"),
)


class FBP_VisibilitySnapshotState(PropertyGroup):
    kind: EnumProperty(
        name="Type",
        items=_SNAPSHOT_KINDS,
        default="LAYER",
    )
    stable_id: StringProperty(
        name="Stable ID",
        description="Persistent identity used across rename and layer reorder",
        default="",
    )
    object_name: StringProperty(
        name="Fallback Name",
        description="Readable fallback used when a project needs repair",
        default="",
    )
    visible: BoolProperty(name="Viewport", default=True)
    solo: BoolProperty(name="Solo", default=False)
    locked: BoolProperty(name="Locked", default=False)
    plane_locked: BoolProperty(name="Plane Locked", default=False)
    render_visible: BoolProperty(name="Render", default=True)


class FBP_VisibilitySnapshot(PropertyGroup):
    name: StringProperty(
        name="Name",
        description="Name of this reusable visibility, solo, lock and render state",
        default="Visibility Snapshot",
    )
    schema_version: IntProperty(
        default=VISIBILITY_SNAPSHOT_SCHEMA_VERSION,
        min=1,
        options={"HIDDEN"},
    )
    states: CollectionProperty(type=FBP_VisibilitySnapshotState)


def _safe_text(value):
    try:
        return str(value or "").strip()
    except FBP_DATA_ERRORS:
        return ""


def _active_snapshot(scene):
    if scene is None:
        return None, -1
    try:
        snapshots = scene.fbp_visibility_snapshots
        if not snapshots:
            return None, -1
        index = max(
            0,
            min(
                int(scene.fbp_visibility_snapshots_index),
                len(snapshots) - 1,
            ),
        )
        return snapshots[index], index
    except FBP_DATA_ERRORS:
        return None, -1


def _unique_snapshot_name(scene, base="Visibility Snapshot"):
    base = _safe_text(base) or "Visibility Snapshot"
    try:
        existing = {
            _safe_text(item.name).casefold()
            for item in scene.fbp_visibility_snapshots
        }
    except FBP_DATA_ERRORS:
        existing = set()
    if base.casefold() not in existing:
        return base
    number = 2
    while f"{base} {number}".casefold() in existing:
        number += 1
    return f"{base} {number}"


def _layer_render_visible(rig):
    try:
        plane = getattr(rig, "fbp_plane_target", None)
        target = plane if plane is not None else rig
        return not bool(getattr(target, "hide_render", False))
    except FBP_DATA_ERRORS:
        return True


def capture_visibility_state(context):
    """Return stable state records for every managed layer in the scene."""
    scene = getattr(context, "scene", None)
    if scene is None:
        return ()
    records = []
    seen = set()
    for rig in tuple(iter_scene_fbp_rigs(scene, fallback=True) or ()):
        try:
            identifier = stable_id(rig, "LAYER") or ensure_layer_identity(rig)
            name = _safe_text(getattr(rig, "name", ""))
            key = ("LAYER", identifier or name.casefold())
            if not key[1] or key in seen:
                continue
            seen.add(key)
            layer_item = get_layer_item_for_rig(context, rig)
            plane = getattr(rig, "fbp_plane_target", None)
            records.append(
                (
                    "LAYER",
                    identifier,
                    name,
                    bool(getattr(rig, "fbp_is_visible", True)),
                    bool(layer_item and getattr(layer_item, "solo", False)),
                    bool(getattr(rig, "hide_select", False)),
                    bool(plane and getattr(plane, "hide_select", False)),
                    _layer_render_visible(rig),
                )
            )
        except FBP_DATA_ERRORS:
            continue
    for canvas in tuple(
        iter_scene_gp_canvases(scene, kind="DRAWING", fallback=True) or ()
    ):
        try:
            if not is_gp_drawing_canvas(canvas):
                continue
            identifier = stable_id(canvas, "MASK") or ensure_mask_identity(canvas)
            name = _safe_text(getattr(canvas, "name", ""))
            key = ("GP", identifier or name.casefold())
            if not key[1] or key in seen:
                continue
            seen.add(key)
            records.append(
                (
                    "GP",
                    identifier,
                    name,
                    bool(getattr(canvas, "fbp_gp_canvas_visible", True)),
                    bool(gp_canvas_solo_active(canvas)),
                    bool(getattr(canvas, "hide_select", False)),
                    False,
                    bool(getattr(canvas, "fbp_gp_canvas_render", True)),
                )
            )
        except FBP_DATA_ERRORS:
            continue
    return tuple(records)


def _replace_snapshot_states(snapshot, records):
    snapshot.states.clear()
    for (
        kind,
        identifier,
        name,
        visible,
        solo,
        locked,
        plane_locked,
        render_visible,
    ) in records:
        state = snapshot.states.add()
        state.kind = kind
        state.stable_id = identifier
        state.object_name = name
        state.visible = bool(visible)
        state.solo = bool(solo)
        state.locked = bool(locked)
        state.plane_locked = bool(plane_locked)
        state.render_visible = bool(render_visible)
    snapshot.schema_version = VISIBILITY_SNAPSHOT_SCHEMA_VERSION
    return len(records)


def _resolution_maps(scene):
    layer_ids = {}
    layer_names = {}
    gp_ids = {}
    gp_names = {}
    for rig in tuple(iter_scene_fbp_rigs(scene, fallback=True) or ()):
        try:
            identifier = stable_id(rig, "LAYER")
            name = _safe_text(getattr(rig, "name", ""))
            if identifier:
                layer_ids.setdefault(identifier, rig)
            if name:
                layer_names.setdefault(name, rig)
        except FBP_DATA_ERRORS:
            continue
    for canvas in tuple(
        iter_scene_gp_canvases(scene, kind="DRAWING", fallback=True) or ()
    ):
        try:
            if not is_gp_drawing_canvas(canvas):
                continue
            identifier = stable_id(canvas, "MASK")
            name = _safe_text(getattr(canvas, "name", ""))
            if identifier:
                gp_ids.setdefault(identifier, canvas)
            if name:
                gp_names.setdefault(name, canvas)
        except FBP_DATA_ERRORS:
            continue
    return layer_ids, layer_names, gp_ids, gp_names


def resolve_visibility_state(state, maps):
    layer_ids, layer_names, gp_ids, gp_names = maps
    kind = _safe_text(getattr(state, "kind", "LAYER")).upper() or "LAYER"
    identifier = _safe_text(getattr(state, "stable_id", ""))
    name = _safe_text(getattr(state, "object_name", ""))
    if kind == "GP":
        return gp_ids.get(identifier) if identifier else gp_names.get(name)
    return layer_ids.get(identifier) if identifier else layer_names.get(name)


def resolve_visibility_snapshot(scene, snapshot):
    maps = _resolution_maps(scene)
    resolved = []
    missing = []
    for state in tuple(getattr(snapshot, "states", ()) or ()):
        target = resolve_visibility_state(state, maps)
        if target is None:
            missing.append(state)
        else:
            resolved.append((state, target))
    return tuple(resolved), tuple(missing)


def apply_visibility_snapshot(context, snapshot):
    """Apply one snapshot and return ``(applied, missing)`` counts."""
    scene = getattr(context, "scene", None)
    if scene is None or snapshot is None:
        return 0, 0
    resolved, missing = resolve_visibility_snapshot(scene, snapshot)
    render_overrides = []
    applied = 0
    for state, target in resolved:
        try:
            kind = _safe_text(getattr(state, "kind", "LAYER")).upper()
            if kind == "GP":
                fbp_set_rna_property_silent(
                    target,
                    "fbp_gp_canvas_visible",
                    bool(state.visible),
                )
                fbp_set_rna_property_silent(
                    target,
                    "fbp_gp_canvas_render",
                    bool(state.render_visible),
                )
                target[KEY_CANVAS_SOLO] = bool(state.solo)
                target.hide_select = bool(state.locked)
                if bool(state.locked) and bool(target.select_get()):
                    target.select_set(False)
            else:
                layer_item = get_layer_item_for_rig(context, target)
                if layer_item is not None:
                    layer_item.solo = bool(state.solo)
                fbp_set_rna_property_silent(
                    target,
                    "fbp_is_visible",
                    bool(state.visible),
                )
                target.hide_select = bool(state.locked)
                if bool(state.locked) and bool(target.select_get()):
                    target.select_set(False)
                plane = getattr(target, "fbp_plane_target", None)
                if plane is not None:
                    plane.hide_select = bool(state.plane_locked)
                    if bool(state.plane_locked) and bool(plane.select_get()):
                        plane.select_set(False)
                    render_overrides.append(
                        (plane, bool(state.render_visible))
                    )
                else:
                    render_overrides.append(
                        (target, bool(state.render_visible))
                    )
            applied += 1
        except FBP_DATA_ERRORS:
            continue
    update_global_visibility(context)
    for target, render_visible in render_overrides:
        try:
            target.hide_render = not bool(render_visible)
        except FBP_DATA_ERRORS:
            pass
    fbp_request_redraw(
        context,
        area_types={"VIEW_3D", "PROPERTIES", "OUTLINER"},
        all_windows=True,
    )
    return applied, len(missing)


def audit_visibility_snapshots(scene, *, repair=False):
    stats = {
        "visibility_snapshots": 0,
        "visibility_snapshot_states": 0,
        "visibility_snapshot_missing_states": 0,
        "visibility_snapshot_duplicate_states": 0,
        "visibility_snapshot_empty": 0,
    }
    issues = []
    warnings = []
    repaired = 0
    if scene is None or not hasattr(scene, "fbp_visibility_snapshots"):
        return {
            "stats": stats,
            "issues": (),
            "warnings": (),
            "repaired": 0,
        }
    maps = _resolution_maps(scene)
    for snapshot in tuple(scene.fbp_visibility_snapshots):
        stats["visibility_snapshots"] += 1
        name = _safe_text(snapshot.name) or "Visibility Snapshot"
        schema = int(getattr(snapshot, "schema_version", 1) or 1)
        if schema > VISIBILITY_SNAPSHOT_SCHEMA_VERSION:
            issues.append(
                f"{name}: schema {schema} is newer than supported schema "
                f"{VISIBILITY_SNAPSHOT_SCHEMA_VERSION}"
            )
            continue
        states = tuple(snapshot.states)
        stats["visibility_snapshot_states"] += len(states)
        seen = set()
        remove_indices = []
        missing_indices = set()
        for index, state in enumerate(states):
            kind = _safe_text(state.kind).upper() or "LAYER"
            identifier = _safe_text(state.stable_id)
            fallback = _safe_text(state.object_name)
            key = (kind, identifier or fallback.casefold())
            if not key[1] or key in seen:
                stats["visibility_snapshot_duplicate_states"] += 1
                remove_indices.append(index)
                continue
            seen.add(key)
            if resolve_visibility_state(state, maps) is None:
                stats["visibility_snapshot_missing_states"] += 1
                remove_indices.append(index)
                missing_indices.add(index)
        if remove_indices:
            missing_count = len(missing_indices)
            duplicate_count = len(set(remove_indices)) - missing_count
            details = []
            if missing_count:
                details.append(f"{missing_count} missing")
            if duplicate_count:
                details.append(f"{duplicate_count} duplicate")
            if repair:
                for index in reversed(sorted(set(remove_indices))):
                    snapshot.states.remove(index)
                    repaired += 1
                snapshot.schema_version = VISIBILITY_SNAPSHOT_SCHEMA_VERSION
            else:
                warnings.append(
                    f"{name}: {', '.join(details)} state reference(s)"
                )
        remaining = (
            len(snapshot.states)
            if repair
            else len(states) - len(set(remove_indices))
        )
        if remaining <= 0:
            stats["visibility_snapshot_empty"] += 1
            warnings.append(f"{name}: the Visibility Snapshot is empty")
    return {
        "stats": stats,
        "issues": tuple(issues),
        "warnings": tuple(warnings),
        "repaired": repaired,
    }


class FBP_OT_AddVisibilitySnapshot(Operator):
    bl_idname = "fbp.add_visibility_snapshot"
    bl_label = "Save Visibility Snapshot"
    bl_description = (
        "Save viewport, solo, lock and render states for every managed layer"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        records = capture_visibility_state(context)
        if not records:
            self.report({"WARNING"}, "No Frame By Plane layers are available")
            return {"CANCELLED"}
        scene = context.scene
        name = _unique_snapshot_name(scene)
        snapshot = scene.fbp_visibility_snapshots.add()
        snapshot.name = name
        count = _replace_snapshot_states(snapshot, records)
        scene.fbp_visibility_snapshots_index = (
            len(scene.fbp_visibility_snapshots) - 1
        )
        fbp_request_redraw()
        self.report(
            {"INFO"},
            f"Saved {count} layer state(s) in {snapshot.name}",
        )
        return {"FINISHED"}


class FBP_OT_UpdateVisibilitySnapshot(Operator):
    bl_idname = "fbp.update_visibility_snapshot"
    bl_label = "Update Visibility Snapshot"
    bl_description = "Replace the active snapshot with the current layer states"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        snapshot, _index = _active_snapshot(context.scene)
        if snapshot is None:
            return {"CANCELLED"}
        records = capture_visibility_state(context)
        if not records:
            return {"CANCELLED"}
        count = _replace_snapshot_states(snapshot, records)
        fbp_request_redraw()
        self.report(
            {"INFO"},
            f"Updated {snapshot.name} with {count} layer state(s)",
        )
        return {"FINISHED"}


class FBP_OT_ApplyVisibilitySnapshot(Operator):
    bl_idname = "fbp.apply_visibility_snapshot"
    bl_label = "Apply Visibility Snapshot"
    bl_description = "Restore viewport, solo, lock and render states"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(default=-1, options={"SKIP_SAVE"})

    def execute(self, context):
        scene = context.scene
        index = int(self.index)
        if index < 0:
            index = int(scene.fbp_visibility_snapshots_index)
        if index < 0 or index >= len(scene.fbp_visibility_snapshots):
            return {"CANCELLED"}
        scene.fbp_visibility_snapshots_index = index
        snapshot = scene.fbp_visibility_snapshots[index]
        applied, missing = apply_visibility_snapshot(context, snapshot)
        if not applied:
            self.report(
                {"WARNING"},
                f"{snapshot.name} has no available layer states",
            )
            return {"CANCELLED"}
        suffix = f" ({missing} missing)" if missing else ""
        self.report(
            {"INFO"},
            f"Applied {applied} layer state(s) from {snapshot.name}{suffix}",
        )
        return {"FINISHED"}


class FBP_OT_RemoveVisibilitySnapshot(Operator):
    bl_idname = "fbp.remove_visibility_snapshot"
    bl_label = "Remove Visibility Snapshot"
    bl_description = "Delete the snapshot without changing scene objects"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        snapshot, index = _active_snapshot(context.scene)
        if snapshot is None:
            return {"CANCELLED"}
        name = _safe_text(snapshot.name) or "Visibility Snapshot"
        context.scene.fbp_visibility_snapshots.remove(index)
        context.scene.fbp_visibility_snapshots_index = min(
            index,
            max(0, len(context.scene.fbp_visibility_snapshots) - 1),
        )
        fbp_request_redraw()
        self.report({"INFO"}, f"Removed {name}")
        return {"FINISHED"}


class FBP_OT_MoveVisibilitySnapshot(Operator):
    bl_idname = "fbp.move_visibility_snapshot"
    bl_label = "Move Visibility Snapshot"
    bl_description = "Move the active snapshot in the saved list"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        items=(
            ("UP", "Up", "Move the snapshot up"),
            ("DOWN", "Down", "Move the snapshot down"),
        ),
        default="UP",
        options={"SKIP_SAVE"},
    )

    def execute(self, context):
        snapshot, index = _active_snapshot(context.scene)
        if snapshot is None:
            return {"CANCELLED"}
        target = index - 1 if self.direction == "UP" else index + 1
        snapshots = context.scene.fbp_visibility_snapshots
        if target < 0 or target >= len(snapshots):
            return {"CANCELLED"}
        snapshots.move(index, target)
        context.scene.fbp_visibility_snapshots_index = target
        fbp_request_redraw()
        return {"FINISHED"}


class FBP_OT_CleanVisibilitySnapshot(Operator):
    bl_idname = "fbp.clean_visibility_snapshot"
    bl_label = "Remove Missing Snapshot States"
    bl_description = "Remove missing references from the active snapshot"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        snapshot, _index = _active_snapshot(context.scene)
        if snapshot is None:
            return {"CANCELLED"}
        maps = _resolution_maps(context.scene)
        missing = [
            index
            for index, state in enumerate(snapshot.states)
            if resolve_visibility_state(state, maps) is None
        ]
        for index in reversed(missing):
            snapshot.states.remove(index)
        fbp_request_redraw()
        if not missing:
            self.report({"INFO"}, "No missing states in the active snapshot")
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"Removed {len(missing)} missing layer state(s)",
        )
        return {"FINISHED"}


class FBP_MT_VisibilitySnapshotListActions(Menu):
    bl_idname = "FBP_MT_visibility_snapshot_list_actions"
    bl_label = "Visibility Snapshot Actions"

    def draw(self, _context):
        layout = configure_layout(self.layout)
        layout.operator("fbp.update_visibility_snapshot", text="Update from Current State", icon="FILE_REFRESH")
        layout.operator("fbp.clean_visibility_snapshot", text="Clean Missing Layers", icon="BRUSH_DATA")
        layout.separator()
        layout.operator("fbp.remove_visibility_snapshot", text="Remove Snapshot", icon="TRASH")


class FBP_UL_VisibilitySnapshots(UIList):
    _PROFILE = "VISIBILITY_SNAPSHOTS"

    def filter_items(self, context, data, propname):
        return fbp_filter_uilist_items(
            context, getattr(data, propname, ()), self._PROFILE,
            self.bitflag_filter_item, attributes=("name",),
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
            if key == "label":
                row.prop(item, "name", text="", emboss=False)
            elif key == "count":
                row.label(text=str(len(getattr(item, "states", ()) or ())), icon="LINENUMBERS_ON")
            elif key == "apply":
                operator = row.operator(
                    "fbp.apply_visibility_snapshot", text="", icon="CHECKMARK", emboss=False
                )
                operator.index = index


def draw_visibility_snapshots_ui(layout, context):
    scene = getattr(context, "scene", None)
    if scene is None or not hasattr(scene, "fbp_visibility_snapshots"):
        return
    box = layout.box()
    configure_layout(box)
    count = len(scene.fbp_visibility_snapshots)
    section_header(
        box,
        "Visibility Snapshots",
        icon="RESTRICT_VIEW_OFF",
        count=count,
    )
    if not count:
        box.operator(
            "fbp.add_visibility_snapshot",
            text="Save Current Layer States",
            icon="ADD",
        )
        hint_row(
            box,
            "Save viewport, solo, lock and render states for all managed layers.",
            icon="INFO",
        )
        return
    list_box = fbp_draw_uilist_header(
        box, context, "VISIBILITY_SNAPSHOTS"
    )
    row = list_box.row(align=False)
    row.template_list(
        "FBP_UL_VisibilitySnapshots",
        "",
        scene,
        "fbp_visibility_snapshots",
        scene,
        "fbp_visibility_snapshots_index",
        rows=min(5, max(2, count)),
    )
    tools = row.column(align=True)
    fbp_set_ui_units_x(tools, 1.0)
    tools.menu(
        "FBP_MT_visibility_snapshot_list_actions",
        text="",
        icon="COLLAPSEMENU",
    )
    tools.separator()
    move = tools.column(align=True)
    active_index = int(getattr(scene, "fbp_visibility_snapshots_index", -1))
    up_row = move.row(align=True)
    up_row.enabled = active_index > 0
    up = up_row.operator(
        "fbp.move_visibility_snapshot",
        text="",
        icon="SORT_DESC",
    )
    up.direction = "UP"
    down_row = move.row(align=True)
    down_row.enabled = 0 <= active_index < count - 1
    down = down_row.operator(
        "fbp.move_visibility_snapshot",
        text="",
        icon="SORT_ASC",
    )
    down.direction = "DOWN"
    tools.separator()
    tools.operator("fbp.add_visibility_snapshot", text="", icon="ADD")
    snapshot, _index = _active_snapshot(scene)
    if snapshot is None:
        return
    resolved, missing = resolve_visibility_snapshot(scene, snapshot)
    actions = box.row(align=True)
    actions.operator(
        "fbp.apply_visibility_snapshot",
        text="Apply",
        icon="CHECKMARK",
    )
    status = box.row(align=True)
    status.label(
        text=f"{len(resolved)} available / {len(snapshot.states)} saved",
        icon="INFO",
    )
    if missing:
        status.alert = True
        status.operator(
            "fbp.clean_visibility_snapshot",
            text=f"Clean {len(missing)}",
            icon="ERROR",
        )


_model_classes = (
    FBP_VisibilitySnapshotState,
    FBP_VisibilitySnapshot,
)
_interactive_classes = (
    FBP_OT_AddVisibilitySnapshot,
    FBP_OT_UpdateVisibilitySnapshot,
    FBP_OT_ApplyVisibilitySnapshot,
    FBP_OT_RemoveVisibilitySnapshot,
    FBP_OT_MoveVisibilitySnapshot,
    FBP_OT_CleanVisibilitySnapshot,
    FBP_MT_VisibilitySnapshotListActions,
    FBP_UL_VisibilitySnapshots,
)
_registered_classes = globals().get("_registered_classes", [])
if not isinstance(_registered_classes, list):
    _registered_classes = []


def _register_scene_properties():
    bpy.types.Scene.fbp_visibility_snapshots = CollectionProperty(
        type=FBP_VisibilitySnapshot,
        name="Visibility Snapshots",
        description="Named viewport, solo, lock and render states",
    )
    bpy.types.Scene.fbp_visibility_snapshots_index = IntProperty(
        name="Visibility Snapshot",
        default=0,
        min=0,
    )


def register():
    unregister_type_properties(
        bpy.types.Scene,
        (
            "fbp_visibility_snapshots",
            "fbp_visibility_snapshots_index",
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
            (
                "fbp_visibility_snapshots",
                "fbp_visibility_snapshots_index",
            ),
        )
        unregister_classes(tuple(_registered_classes))
        _registered_classes.clear()
        raise


def unregister():
    unregister_type_properties(
        bpy.types.Scene,
        (
            "fbp_visibility_snapshots",
            "fbp_visibility_snapshots_index",
        ),
    )
    unregister_classes(tuple(_registered_classes))
    _registered_classes.clear()


__all__ = (
    "VISIBILITY_SNAPSHOT_SCHEMA_VERSION",
    "capture_visibility_state",
    "resolve_visibility_snapshot",
    "apply_visibility_snapshot",
    "audit_visibility_snapshots",
    "draw_visibility_snapshots_ui",
)
