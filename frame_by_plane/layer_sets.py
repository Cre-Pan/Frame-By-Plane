"""Persistent named selections for Frame By Plane layers and GP canvases."""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Menu, Operator, PropertyGroup, UIList

from .fbp_index import iter_scene_fbp_rigs, iter_scene_gp_canvases
from .grease_pencil_bridge import is_gp_drawing_canvas
from .identifiers import ensure_layer_identity, ensure_mask_identity, stable_id
from .layers import (
    fbp_resolve_rig_from_any_object,
    is_fbp_layer_object,
    object_in_view_layer,
    fbp_set_ui_units_x,
)
from .registration import (
    register_classes,
    register_interactive_classes,
    unregister_classes,
    unregister_type_properties,
)
from .runtime import FBP_DATA_ERRORS, fbp_request_redraw
from .shortcut_runtime import primary_modifier_name, primary_modifier_pressed
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


LAYER_SET_SCHEMA_VERSION = 1
_LAYER_SET_KINDS = (
    ('LAYER', 'Layer', 'Frame By Plane image, video, color or gradient layer'),
    ('GP', 'Grease Pencil', 'Frame By Plane Grease Pencil drawing canvas'),
)
_APPLY_MODES = (
    ('REPLACE', 'Replace', 'Replace the current Blender selection with this Layer Set'),
    ('ADD', 'Add', 'Add this Layer Set to the current Blender selection'),
    ('SUBTRACT', 'Subtract', 'Remove this Layer Set from the current Blender selection'),
)


class FBP_SavedLayerSetMember(PropertyGroup):
    kind: EnumProperty(name="Type", items=_LAYER_SET_KINDS, default='LAYER')
    stable_id: StringProperty(
        name="Stable ID",
        description="Persistent Frame By Plane identity used across rename, reorder and file reload",
        default="",
    )
    object_name: StringProperty(
        name="Fallback Name",
        description="Readable name used when a referenced layer is temporarily unavailable",
        default="",
    )
    was_active: BoolProperty(
        name="Active",
        description="This member was the active object when the Layer Set was saved",
        default=False,
    )


class FBP_SavedLayerSet(PropertyGroup):
    name: StringProperty(
        name="Name",
        description="Reusable name for this saved layer selection",
        default="Layer Set",
    )
    schema_version: IntProperty(default=LAYER_SET_SCHEMA_VERSION, min=1, options={'HIDDEN'})
    members: CollectionProperty(type=FBP_SavedLayerSetMember)


def _safe_text(value):
    try:
        return str(value or "").strip()
    except FBP_DATA_ERRORS:
        return ""


def _active_layer_set(scene):
    if scene is None:
        return None, -1
    try:
        items = scene.fbp_saved_layer_sets
        if not items:
            return None, -1
        index = max(0, min(int(scene.fbp_saved_layer_sets_index), len(items) - 1))
        return items[index], index
    except FBP_DATA_ERRORS:
        return None, -1


def _unique_layer_set_name(scene, base="Layer Set"):
    base = _safe_text(base) or "Layer Set"
    try:
        existing = {
            _safe_text(item.name).casefold()
            for item in scene.fbp_saved_layer_sets
        }
    except FBP_DATA_ERRORS:
        existing = set()
    if base.casefold() not in existing:
        return base
    number = 2
    while f"{base} {number}".casefold() in existing:
        number += 1
    return f"{base} {number}"


def _target_record(obj, active, context):
    if obj is None:
        return None
    try:
        if is_gp_drawing_canvas(obj):
            identifier = stable_id(obj, "MASK") or ensure_mask_identity(obj)
            kind = 'GP'
            target = obj
        else:
            target = fbp_resolve_rig_from_any_object(obj, context)
            if target is None or not is_fbp_layer_object(target):
                return None
            identifier = stable_id(target, "LAYER") or ensure_layer_identity(target)
            kind = 'LAYER'
        name = _safe_text(getattr(target, "name", ""))
        if not identifier and not name:
            return None
        return kind, _safe_text(identifier), name, bool(target == active or obj == active)
    except FBP_DATA_ERRORS:
        return None


def capture_layer_selection(context):
    """Return stable, deduplicated records for the current FBP/GP selection."""
    active = getattr(getattr(context, "view_layer", None), "objects", None)
    active = getattr(active, "active", None)
    selected = tuple(getattr(context, "selected_objects", ()) or ())
    selected_ids = {id(obj) for obj in selected}
    ordered = ((active,) if active is not None and id(active) in selected_ids else ()) + tuple(
        obj for obj in selected if obj is not active
    )
    records = []
    seen = set()
    for obj in ordered:
        record = _target_record(obj, active, context)
        if record is None:
            continue
        kind, identifier, name, was_active = record
        key = (kind, identifier or name.casefold())
        if key in seen:
            continue
        seen.add(key)
        records.append((kind, identifier, name, was_active))
    return tuple(records)


def _replace_layer_set_members(layer_set, records):
    layer_set.members.clear()
    for kind, identifier, name, was_active in records:
        member = layer_set.members.add()
        member.kind = kind
        member.stable_id = identifier
        member.object_name = name
        member.was_active = bool(was_active)
    layer_set.schema_version = LAYER_SET_SCHEMA_VERSION
    return len(records)


def _resolution_maps(scene):
    layer_ids = {}
    layer_names = {}
    gp_ids = {}
    gp_names = {}
    try:
        for rig in iter_scene_fbp_rigs(scene, fallback=True):
            name = _safe_text(getattr(rig, "name", ""))
            identifier = stable_id(rig, "LAYER")
            if identifier:
                layer_ids.setdefault(identifier, rig)
            if name:
                layer_names.setdefault(name, rig)
    except FBP_DATA_ERRORS:
        pass
    try:
        for canvas in iter_scene_gp_canvases(scene, kind="DRAWING", fallback=True):
            name = _safe_text(getattr(canvas, "name", ""))
            identifier = stable_id(canvas, "MASK")
            if identifier:
                gp_ids.setdefault(identifier, canvas)
            if name:
                gp_names.setdefault(name, canvas)
    except FBP_DATA_ERRORS:
        pass
    return layer_ids, layer_names, gp_ids, gp_names


def resolve_layer_set_member(member, maps):
    layer_ids, layer_names, gp_ids, gp_names = maps
    kind = _safe_text(getattr(member, "kind", "LAYER")).upper()
    identifier = _safe_text(getattr(member, "stable_id", ""))
    name = _safe_text(getattr(member, "object_name", ""))
    if kind == 'GP':
        return gp_ids.get(identifier) if identifier else gp_names.get(name)
    return layer_ids.get(identifier) if identifier else layer_names.get(name)


def resolve_layer_set(scene, layer_set):
    maps = _resolution_maps(scene)
    resolved = []
    missing = []
    for member in tuple(getattr(layer_set, "members", ()) or ()):
        target = resolve_layer_set_member(member, maps)
        if target is None:
            missing.append(member)
        else:
            resolved.append((member, target))
    return tuple(resolved), tuple(missing)


def active_layer_set_objects(scene):
    """Public API for effects/tools that want the active reusable selection."""
    layer_set, _index = _active_layer_set(scene)
    if layer_set is None:
        return ()
    resolved, _missing = resolve_layer_set(scene, layer_set)
    return tuple(target for _member, target in resolved)


def audit_layer_sets(scene, *, repair=False):
    """Validate saved selections without deleting any scene object."""
    stats = {
        "layer_sets": 0,
        "layer_set_members": 0,
        "layer_set_missing_members": 0,
        "layer_set_duplicate_members": 0,
        "layer_set_empty": 0,
    }
    issues = []
    warnings = []
    repaired = 0
    if scene is None or not hasattr(scene, "fbp_saved_layer_sets"):
        return {"stats": stats, "issues": (), "warnings": (), "repaired": 0}
    maps = _resolution_maps(scene)
    for layer_set in tuple(scene.fbp_saved_layer_sets):
        stats["layer_sets"] += 1
        name = _safe_text(getattr(layer_set, "name", "")) or "Layer Set"
        try:
            schema = int(getattr(layer_set, "schema_version", 1) or 1)
        except (TypeError, ValueError):
            schema = 0
        if schema > LAYER_SET_SCHEMA_VERSION:
            issues.append(
                f"{name}: schema {schema} is newer than supported schema {LAYER_SET_SCHEMA_VERSION}"
            )
            continue

        remove_indices = []
        seen = set()
        members = tuple(getattr(layer_set, "members", ()) or ())
        stats["layer_set_members"] += len(members)
        for index, member in enumerate(members):
            kind = _safe_text(getattr(member, "kind", "LAYER")).upper() or "LAYER"
            identifier = _safe_text(getattr(member, "stable_id", ""))
            fallback = _safe_text(getattr(member, "object_name", ""))
            key = (kind, identifier or fallback.casefold())
            if not key[1] or key in seen:
                stats["layer_set_duplicate_members"] += 1
                remove_indices.append(index)
                continue
            seen.add(key)
            if resolve_layer_set_member(member, maps) is None:
                stats["layer_set_missing_members"] += 1
                remove_indices.append(index)

        if remove_indices:
            missing_count = sum(
                1 for index in remove_indices
                if index < len(members) and resolve_layer_set_member(members[index], maps) is None
            )
            duplicate_count = len(remove_indices) - missing_count
            details = []
            if missing_count:
                details.append(f"{missing_count} missing")
            if duplicate_count:
                details.append(f"{duplicate_count} duplicate")
            if repair:
                for index in reversed(sorted(set(remove_indices))):
                    layer_set.members.remove(index)
                    repaired += 1
                layer_set.schema_version = LAYER_SET_SCHEMA_VERSION
            else:
                warnings.append(f"{name}: {', '.join(details)} member reference(s)")

        remaining = len(layer_set.members) if repair else len(members) - len(set(remove_indices))
        if remaining <= 0:
            stats["layer_set_empty"] += 1
            warnings.append(f"{name}: the Layer Set is empty")

    return {
        "stats": stats,
        "issues": tuple(issues),
        "warnings": tuple(warnings),
        "repaired": repaired,
    }


class FBP_OT_AddLayerSet(Operator):
    bl_idname = "fbp.add_layer_set"
    bl_label = "Save Layer Set"
    bl_description = "Save the current Frame By Plane and Grease Pencil layer selection"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        records = capture_layer_selection(context)
        if not records:
            self.report({'WARNING'}, "Select at least one Frame By Plane or Grease Pencil layer")
            return {'CANCELLED'}
        scene = context.scene
        name = _unique_layer_set_name(scene)
        item = scene.fbp_saved_layer_sets.add()
        item.name = name
        count = _replace_layer_set_members(item, records)
        scene.fbp_saved_layer_sets_index = len(scene.fbp_saved_layer_sets) - 1
        fbp_request_redraw()
        self.report({'INFO'}, f"Saved {count} layer(s) in {item.name}")
        return {'FINISHED'}


class FBP_OT_UpdateLayerSet(Operator):
    bl_idname = "fbp.update_layer_set"
    bl_label = "Update Layer Set"
    bl_description = "Replace the active Layer Set with the current layer selection"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        item, _index = _active_layer_set(context.scene)
        if item is None:
            return {'CANCELLED'}
        records = capture_layer_selection(context)
        if not records:
            self.report({'WARNING'}, "The current layer selection is empty")
            return {'CANCELLED'}
        count = _replace_layer_set_members(item, records)
        fbp_request_redraw()
        self.report({'INFO'}, f"Updated {item.name} with {count} layer(s)")
        return {'FINISHED'}


class FBP_OT_ApplyLayerSet(Operator):
    bl_idname = "fbp.apply_layer_set"
    bl_label = "Select Layer Set"
    bl_description = f"Select the saved layers. Shift-click adds; {primary_modifier_name()}-click subtracts"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1, options={'SKIP_SAVE'})
    mode: EnumProperty(items=_APPLY_MODES, default='REPLACE', options={'SKIP_SAVE'})

    def invoke(self, context, event):
        if primary_modifier_pressed(event):
            self.mode = 'SUBTRACT'
        elif bool(getattr(event, "shift", False)):
            self.mode = 'ADD'
        return self.execute(context)

    def execute(self, context):
        scene = context.scene
        try:
            index = int(self.index)
            if index < 0:
                index = int(scene.fbp_saved_layer_sets_index)
            if index < 0 or index >= len(scene.fbp_saved_layer_sets):
                return {'CANCELLED'}
            scene.fbp_saved_layer_sets_index = index
            item = scene.fbp_saved_layer_sets[index]
        except FBP_DATA_ERRORS:
            return {'CANCELLED'}

        resolved, missing = resolve_layer_set(scene, item)
        if not resolved:
            self.report({'WARNING'}, f"{item.name} has no available layers")
            return {'CANCELLED'}

        mode = _safe_text(self.mode).upper() or 'REPLACE'
        if mode == 'REPLACE':
            for obj in tuple(getattr(context, "selected_objects", ()) or ()):
                try:
                    obj.select_set(False)
                except FBP_DATA_ERRORS:
                    pass

        selectable = []
        preferred_active = None
        skipped = 0
        changed_count = 0
        for member, target in resolved:
            if not object_in_view_layer(target, context):
                skipped += 1
                continue
            try:
                if bool(getattr(target, "hide_select", False)):
                    skipped += 1
                    continue
                desired = mode != 'SUBTRACT'
                previous = bool(target.select_get())
                target.select_set(desired)
                changed_count += int(previous != desired)
                if desired:
                    selectable.append(target)
                    if bool(getattr(member, "was_active", False)):
                        preferred_active = target
            except FBP_DATA_ERRORS:
                skipped += 1

        if mode != 'SUBTRACT' and selectable:
            try:
                context.view_layer.objects.active = preferred_active or selectable[0]
            except FBP_DATA_ERRORS:
                pass

        fbp_request_redraw()
        selected_count = len(selectable) if mode == 'REPLACE' else changed_count
        details = []
        if missing:
            details.append(f"{len(missing)} missing")
        if skipped:
            details.append(f"{skipped} unavailable")
        suffix = f" ({', '.join(details)})" if details else ""
        verb = "Selected" if mode == 'REPLACE' else ("Added" if mode == 'ADD' else "Removed")
        self.report({'INFO'}, f"{verb} {selected_count} layer(s) from {item.name}{suffix}")
        return {'FINISHED'}


class FBP_OT_RemoveLayerSet(Operator):
    bl_idname = "fbp.remove_layer_set"
    bl_label = "Remove Layer Set"
    bl_description = "Delete the active Layer Set without deleting any scene objects"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        item, index = _active_layer_set(scene)
        if item is None:
            return {'CANCELLED'}
        name = _safe_text(item.name) or "Layer Set"
        scene.fbp_saved_layer_sets.remove(index)
        scene.fbp_saved_layer_sets_index = min(
            index,
            max(0, len(scene.fbp_saved_layer_sets) - 1),
        )
        fbp_request_redraw()
        self.report({'INFO'}, f"Removed {name}")
        return {'FINISHED'}


class FBP_OT_MoveLayerSet(Operator):
    bl_idname = "fbp.move_layer_set"
    bl_label = "Move Layer Set"
    bl_description = "Move the active Layer Set in the saved list"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(
        items=(('UP', 'Up', 'Move the Layer Set up'), ('DOWN', 'Down', 'Move the Layer Set down')),
        default='UP',
        options={'SKIP_SAVE'},
    )

    def execute(self, context):
        scene = context.scene
        item, index = _active_layer_set(scene)
        if item is None:
            return {'CANCELLED'}
        target = index - 1 if self.direction == 'UP' else index + 1
        if target < 0 or target >= len(scene.fbp_saved_layer_sets):
            return {'CANCELLED'}
        scene.fbp_saved_layer_sets.move(index, target)
        scene.fbp_saved_layer_sets_index = target
        fbp_request_redraw()
        return {'FINISHED'}


class FBP_OT_CleanLayerSet(Operator):
    bl_idname = "fbp.clean_layer_set"
    bl_label = "Remove Missing Layers"
    bl_description = "Remove missing references from the active Layer Set"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        item, _index = _active_layer_set(context.scene)
        if item is None:
            return {'CANCELLED'}
        maps = _resolution_maps(context.scene)
        missing_indices = [
            index for index, member in enumerate(item.members)
            if resolve_layer_set_member(member, maps) is None
        ]
        for index in reversed(missing_indices):
            item.members.remove(index)
        fbp_request_redraw()
        if not missing_indices:
            self.report({'INFO'}, "No missing layers in the active Layer Set")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Removed {len(missing_indices)} missing layer reference(s)")
        return {'FINISHED'}


class FBP_MT_LayerSetListActions(Menu):
    bl_idname = "FBP_MT_layer_set_list_actions"
    bl_label = "Layer Set Actions"

    def draw(self, _context):
        layout = configure_layout(self.layout)
        layout.operator("fbp.update_layer_set", text="Update from Selection", icon="FILE_REFRESH")
        layout.operator("fbp.clean_layer_set", text="Clean Missing Members", icon="BRUSH_DATA")
        layout.separator()
        layout.operator("fbp.remove_layer_set", text="Remove Layer Set", icon="TRASH")


class FBP_UL_LayerSets(UIList):
    _PROFILE = "LAYER_SETS"

    def filter_items(self, context, data, propname):
        return fbp_filter_uilist_items(
            context, getattr(data, propname, ()), self._PROFILE,
            self.bitflag_filter_item, attributes=("name",),
        )

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
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
                row.label(text=str(len(getattr(item, "members", ()) or ())), icon="LINENUMBERS_ON")
            elif key == "apply":
                op = row.operator("fbp.apply_layer_set", text="", icon="CHECKMARK", emboss=False)
                op.index = index
                op.mode = "REPLACE"


def draw_layer_sets_ui(layout, context):
    scene = getattr(context, "scene", None)
    if scene is None:
        return
    box = layout.box()
    configure_layout(box)
    count = len(getattr(scene, "fbp_saved_layer_sets", ()) or ())
    section_header(box, "Layer Sets", icon='GROUP', count=count)

    if not count:
        box.operator("fbp.add_layer_set", text="Save Current Selection", icon='ADD')
        hint_row(box, "Save reusable plane and Grease Pencil selections.", icon='INFO')
        return

    list_box = fbp_draw_uilist_header(box, context, "LAYER_SETS")
    row = list_box.row(align=False)
    row.template_list(
        "FBP_UL_LayerSets", "",
        scene, "fbp_saved_layer_sets",
        scene, "fbp_saved_layer_sets_index",
        rows=min(5, max(2, count)),
    )
    tools = row.column(align=True)
    fbp_set_ui_units_x(tools, 1.0)
    tools.menu("FBP_MT_layer_set_list_actions", text="", icon="COLLAPSEMENU")
    tools.separator()
    move = tools.column(align=True)
    active_index = int(getattr(scene, "fbp_saved_layer_sets_index", -1))
    up_row = move.row(align=True)
    up_row.enabled = active_index > 0
    up = up_row.operator("fbp.move_layer_set", text="", icon="SORT_DESC")
    up.direction = 'UP'
    down_row = move.row(align=True)
    down_row.enabled = 0 <= active_index < count - 1
    down = down_row.operator("fbp.move_layer_set", text="", icon="SORT_ASC")
    down.direction = 'DOWN'
    tools.separator()
    tools.operator("fbp.add_layer_set", text="", icon="ADD")

    item, _index = _active_layer_set(scene)
    if item is None:
        return
    resolved, missing = resolve_layer_set(scene, item)
    actions = box.row(align=True)
    replace = actions.operator("fbp.apply_layer_set", text="Select", icon='RESTRICT_SELECT_OFF')
    replace.mode = 'REPLACE'
    add = actions.operator("fbp.apply_layer_set", text="Add", icon='ADD')
    add.mode = 'ADD'
    subtract = actions.operator("fbp.apply_layer_set", text="Subtract", icon='REMOVE')
    subtract.mode = 'SUBTRACT'
    status = box.row(align=True)
    status.label(text=f"{len(resolved)} available / {len(item.members)} saved", icon='INFO')
    if missing:
        status.alert = True
        status.operator("fbp.clean_layer_set", text=f"Clean {len(missing)}", icon='ERROR')


_model_classes = (
    FBP_SavedLayerSetMember,
    FBP_SavedLayerSet,
)
_interactive_classes = (
    FBP_OT_AddLayerSet,
    FBP_OT_UpdateLayerSet,
    FBP_OT_ApplyLayerSet,
    FBP_OT_RemoveLayerSet,
    FBP_OT_MoveLayerSet,
    FBP_OT_CleanLayerSet,
    FBP_MT_LayerSetListActions,
    FBP_UL_LayerSets,
)
_registered_classes = globals().get("_registered_classes", [])
if not isinstance(_registered_classes, list):
    _registered_classes = []


def _register_scene_properties(layer_set_type):
    bpy.types.Scene.fbp_saved_layer_sets = CollectionProperty(
        type=layer_set_type,
        name="Layer Sets",
        description="Named reusable selections of Frame By Plane and Grease Pencil layers",
    )
    bpy.types.Scene.fbp_saved_layer_sets_index = IntProperty(
        name="Layer Set",
        description="Active saved Layer Set",
        default=0,
        min=0,
    )


def register():
    previous_member_type = getattr(bpy.types, "FBP_SavedLayerSetMember", None)
    previous_set_type = getattr(bpy.types, "FBP_SavedLayerSet", None)
    unregister_type_properties(
        bpy.types.Scene,
        ("fbp_saved_layer_sets", "fbp_saved_layer_sets_index"),
    )
    _registered_classes.clear()
    try:
        _registered_classes.extend(register_classes(_model_classes))
        _register_scene_properties(FBP_SavedLayerSet)
        _registered_classes.extend(register_interactive_classes(_interactive_classes))
    except Exception:
        unregister_type_properties(
            bpy.types.Scene,
            ("fbp_saved_layer_sets", "fbp_saved_layer_sets_index"),
        )
        unregister_classes(tuple(_registered_classes))
        _registered_classes.clear()
        if previous_member_type is not None and previous_set_type is not None:
            try:
                register_classes((previous_member_type, previous_set_type))
                _register_scene_properties(previous_set_type)
            except Exception:
                pass
        raise


def unregister():
    unregister_type_properties(
        bpy.types.Scene,
        ("fbp_saved_layer_sets", "fbp_saved_layer_sets_index"),
    )
    unregister_classes(tuple(_registered_classes))
    _registered_classes.clear()
