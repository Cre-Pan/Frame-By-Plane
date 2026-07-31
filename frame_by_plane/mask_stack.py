"""Ordered Mask Stack operations and reusable mask-source presets."""

from __future__ import annotations

import json

import bpy
from bpy.props import (
    CollectionProperty,
    EnumProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Menu, Operator, PropertyGroup, UIList

from .effects_registry import (
    fbp_effect_definition,
    fbp_normalize_effect_id,
)
from .geometry_nodes import (
    FBP_MASK_STACK_OPERATIONS,
    fbp_active_effect_id,
    fbp_apply_effect_stack_snapshot,
    fbp_apply_effect_state_snapshot,
    fbp_capture_effect_stack_snapshot,
    fbp_capture_effect_state_snapshot,
    fbp_effect_ids_for_rig,
    fbp_effect_supported_for_rig,
    fbp_mask_stack_operation,
    fbp_set_mask_stack_operation,
)
from .layers import fbp_set_ui_units_x, get_selected_or_active_rigs
from .registration import (
    register_classes,
    register_interactive_classes,
    unregister_classes,
    unregister_type_properties,
)
from .runtime import FBP_DATA_ERRORS
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


FBP_MASK_SOURCE_SCHEMA_VERSION = 1
FBP_MASK_SOURCE_MAX_BYTES = 512 * 1024
_OPERATION_IDS = frozenset(item[0] for item in FBP_MASK_STACK_OPERATIONS)


def _safe_text(value):
    try:
        return str(value or "").strip()
    except FBP_DATA_ERRORS:
        return ""


def _canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _active_source(scene):
    try:
        sources = scene.fbp_mask_sources
        if not sources:
            return None, -1
        index = max(
            0,
            min(int(scene.fbp_mask_sources_index), len(sources) - 1),
        )
        return sources[index], index
    except FBP_DATA_ERRORS:
        return None, -1


def _unique_name(scene, base="Mask Source"):
    base = _safe_text(base) or "Mask Source"
    try:
        names = {
            _safe_text(item.name).casefold()
            for item in scene.fbp_mask_sources
        }
    except FBP_DATA_ERRORS:
        names = set()
    if base.casefold() not in names:
        return base
    number = 2
    while f"{base} {number}".casefold() in names:
        number += 1
    return f"{base} {number}"


def _mask_definition(effect_id):
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    return (
        effect_id,
        definition,
        bool(
            effect_id
            and definition.get("kind") == "SHADER"
            and str(definition.get("stage", "") or "") == "MASK"
        ),
    )


def _sanitize_mask_state(state):
    state = dict(state or {})
    effect_id, definition, valid = _mask_definition(
        state.get("effect_id", "")
    )
    if not valid:
        return None
    state["effect_id"] = effect_id
    state["mask_target"] = "LAYER"
    state["group_id"] = ""
    state["group_name"] = ""
    state["group_collapsed"] = False
    state["group_color_tag"] = "NONE"
    properties = dict(state.get("properties", {}) or {})
    pointer_property = str(
        definition.get("object_mask_pointer_property", "") or ""
    )
    if pointer_property:
        properties.pop(pointer_property, None)
    # Shape helpers are private per layer. Never turn one preset into a shared
    # pointer to the source layer's editable mesh/null.
    if bool(definition.get("object_mask_aware", False)):
        for key in tuple(properties):
            if key.endswith("_object") or key.endswith("_external_null"):
                properties.pop(key, None)
    state["properties"] = properties
    operation = str(
        state.get("mask_operation", "INTERSECT") or "INTERSECT"
    ).upper()
    state["mask_operation"] = (
        operation if operation in _OPERATION_IDS else "INTERSECT"
    )
    return state


def _capture_source(rig, effect_id):
    state = _sanitize_mask_state(
        fbp_capture_effect_state_snapshot(rig, effect_id)
    )
    if state is None:
        raise ValueError("The active effect is not a reusable mask")
    state["mask_operation"] = fbp_mask_stack_operation(rig, effect_id)
    return {
        "schema": FBP_MASK_SOURCE_SCHEMA_VERSION,
        "effect": state,
    }


def _decode_source(raw):
    text = _safe_text(raw)
    if not text:
        return None, "Mask Source has no payload"
    if len(text.encode("utf-8")) > FBP_MASK_SOURCE_MAX_BYTES:
        return None, "Mask Source exceeds the 512 KB safety limit"
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None, "Mask Source is not valid JSON"
    if not isinstance(payload, dict):
        return None, "Mask Source root must be an object"
    try:
        schema = int(payload.get("schema", 0) or 0)
    except (TypeError, ValueError):
        schema = 0
    if schema != FBP_MASK_SOURCE_SCHEMA_VERSION:
        return None, f"Mask Source schema {schema} is not supported"
    state = _sanitize_mask_state(payload.get("effect"))
    if state is None:
        return None, "Mask Source effect is unavailable or is not a mask"
    return {
        "schema": FBP_MASK_SOURCE_SCHEMA_VERSION,
        "effect": state,
    }, ""


def _store_source(source, payload):
    encoded = _canonical_json(payload)
    if len(encoded.encode("utf-8")) > FBP_MASK_SOURCE_MAX_BYTES:
        raise ValueError("Mask Source exceeds the 512 KB safety limit")
    source.schema_version = FBP_MASK_SOURCE_SCHEMA_VERSION
    source.effect_id = fbp_normalize_effect_id(
        payload["effect"]["effect_id"]
    )
    source.payload_json = encoded


class FBP_MaskSourcePreset(PropertyGroup):
    name: StringProperty(
        name="Name",
        description="Reusable mask-source name",
        default="Mask Source",
    )
    description: StringProperty(
        name="Description",
        default="",
    )
    schema_version: IntProperty(
        default=FBP_MASK_SOURCE_SCHEMA_VERSION,
        min=1,
        options={"HIDDEN"},
    )
    effect_id: StringProperty(
        default="",
        options={"HIDDEN"},
    )
    payload_json: StringProperty(
        default="",
        options={"HIDDEN"},
    )


def audit_mask_sources(scene, *, repair=False):
    issues = []
    warnings = []
    repaired = 0
    seen = set()
    try:
        sources = tuple(scene.fbp_mask_sources)
    except FBP_DATA_ERRORS:
        sources = ()
    for source in sources:
        name = _safe_text(source.name)
        base = name or "Mask Source"
        candidate = base
        number = 2
        while candidate.casefold() in seen:
            candidate = f"{base} {number}"
            number += 1
        if candidate != name:
            warnings.append(
                f'Mask Source "{name or "<unnamed>"}" has an empty or duplicate name'
            )
            if repair:
                source.name = candidate
                name = candidate
                repaired += 1
        seen.add(candidate.casefold())
        try:
            schema = int(source.schema_version)
        except (TypeError, ValueError):
            schema = 0
        if schema > FBP_MASK_SOURCE_SCHEMA_VERSION:
            issues.append(f"{name or 'Mask Source'} uses newer schema {schema}")
            continue
        payload, error = _decode_source(source.payload_json)
        if payload is None:
            issues.append(f"{name or 'Mask Source'}: {error}")
            continue
        effect_id = payload["effect"]["effect_id"]
        if repair:
            canonical = _canonical_json(payload)
            if source.payload_json != canonical:
                source.payload_json = canonical
                repaired += 1
            if source.effect_id != effect_id:
                source.effect_id = effect_id
                repaired += 1
            if source.schema_version != FBP_MASK_SOURCE_SCHEMA_VERSION:
                source.schema_version = FBP_MASK_SOURCE_SCHEMA_VERSION
                repaired += 1
    return {
        "issues": tuple(dict.fromkeys(issues)),
        "warnings": tuple(dict.fromkeys(warnings)),
        "repaired": repaired,
        "stats": {
            "mask_source_issues": len(issues),
            "mask_source_warnings": len(warnings),
        },
    }


def _apply_source_to_rigs(rigs, source):
    payload, error = _decode_source(source.payload_json)
    if payload is None:
        return False, error, 0
    state = payload["effect"]
    effect_id = state["effect_id"]
    incompatible = [
        getattr(rig, "name", "Layer")
        for rig in rigs
        if not fbp_effect_supported_for_rig(rig, effect_id)
    ]
    if incompatible:
        return (
            False,
            f"{effect_id} is incompatible with: "
            + ", ".join(incompatible[:8]),
            0,
        )
    backups = [
        (rig, fbp_capture_effect_stack_snapshot(rig))
        for rig in rigs
    ]
    applied = 0
    for rig in rigs:
        if not fbp_apply_effect_state_snapshot(
            rig,
            state,
            sync_items=True,
        ):
            for restore_rig, backup in backups:
                fbp_apply_effect_stack_snapshot(
                    restore_rig,
                    backup,
                    mode="REPLACE",
                )
            return False, f"Could not apply {effect_id}", applied
        fbp_set_mask_stack_operation(
            rig,
            effect_id,
            state.get("mask_operation", "INTERSECT"),
            rebuild=True,
        )
        applied += 1
    return True, "", applied


class FBP_OT_SetMaskStackOperation(Operator):
    bl_idname = "fbp.set_mask_stack_operation"
    bl_label = "Set Mask Operation"
    bl_description = "Choose how this ordered mask combines with masks above it"
    bl_options = {"REGISTER", "UNDO"}

    mask_effect_id: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    operation: EnumProperty(
        name="Operation",
        items=FBP_MASK_STACK_OPERATIONS,
        default="INTERSECT",
        options={"SKIP_SAVE"},
    )

    def execute(self, context):
        rigs = get_selected_or_active_rigs(context)
        effect_id = fbp_normalize_effect_id(self.mask_effect_id)
        changed = 0
        for rig in rigs:
            if effect_id not in set(fbp_effect_ids_for_rig(rig)):
                continue
            if fbp_set_mask_stack_operation(
                rig,
                effect_id,
                self.operation,
                rebuild=True,
            ):
                changed += 1
        if not rigs:
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"{self.operation.title()} set on {changed or len(rigs)} layer(s)",
        )
        return {"FINISHED"}


class FBP_OT_AddMaskSource(Operator):
    bl_idname = "fbp.add_mask_source"
    bl_label = "Save Mask Source"
    bl_description = "Save the active mask as a reusable source in this blend file"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        rigs = get_selected_or_active_rigs(context)
        if not rigs:
            self.report({"WARNING"}, "Select a Frame By Plane layer")
            return {"CANCELLED"}
        effect_id = fbp_active_effect_id(rigs[0])
        _effect_id, definition, valid = _mask_definition(effect_id)
        if not valid:
            self.report({"WARNING"}, "Select a mask in the Mask Stack")
            return {"CANCELLED"}
        try:
            payload = _capture_source(rigs[0], effect_id)
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        scene = context.scene
        name = _unique_name(
            scene,
            str(definition.get("label", "Mask Source") or "Mask Source"),
        )
        source = scene.fbp_mask_sources.add()
        source.name = name
        _store_source(source, payload)
        scene.fbp_mask_sources_index = len(scene.fbp_mask_sources) - 1
        self.report({"INFO"}, f'Saved reusable mask "{name}"')
        return {"FINISHED"}


class FBP_OT_UpdateMaskSource(Operator):
    bl_idname = "fbp.update_mask_source"
    bl_label = "Update Mask Source"
    bl_description = "Update the selected reusable source from the active mask"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        source, _index = _active_source(context.scene)
        rigs = get_selected_or_active_rigs(context)
        if source is None or not rigs:
            return {"CANCELLED"}
        effect_id = fbp_active_effect_id(rigs[0])
        try:
            payload = _capture_source(rigs[0], effect_id)
            _store_source(source, payload)
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f'Updated "{source.name}"')
        return {"FINISHED"}


class FBP_OT_ApplyMaskSource(Operator):
    bl_idname = "fbp.apply_mask_source"
    bl_label = "Apply Mask Source"
    bl_description = "Add or update this reusable mask on compatible selected layers"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(default=-1, options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        scene = context.scene
        index = int(self.index)
        if index < 0:
            _source, index = _active_source(scene)
        rigs = get_selected_or_active_rigs(context)
        if not (0 <= index < len(scene.fbp_mask_sources)) or not rigs:
            return {"CANCELLED"}
        scene.fbp_mask_sources_index = index
        success, error, applied = _apply_source_to_rigs(
            rigs,
            scene.fbp_mask_sources[index],
        )
        if not success:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"Applied reusable mask to {applied} layer(s)",
        )
        return {"FINISHED"}


class FBP_OT_RemoveMaskSource(Operator):
    bl_idname = "fbp.remove_mask_source"
    bl_label = "Remove Mask Source"
    bl_description = "Remove the reusable source without changing any layer"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        source, index = _active_source(scene)
        if source is None:
            return {"CANCELLED"}
        scene.fbp_mask_sources.remove(index)
        scene.fbp_mask_sources_index = min(
            index,
            max(0, len(scene.fbp_mask_sources) - 1),
        )
        return {"FINISHED"}


class FBP_MT_MaskSourceListActions(Menu):
    bl_idname = "FBP_MT_mask_source_list_actions"
    bl_label = "Mask Source Actions"

    def draw(self, _context):
        layout = configure_layout(self.layout)
        layout.operator("fbp.update_mask_source", text="Update from Active Mask", icon="FILE_REFRESH")
        layout.separator()
        layout.operator("fbp.remove_mask_source", text="Remove Mask Source", icon="TRASH")


class FBP_UL_MaskSources(UIList):
    _PROFILE = "MASK_SOURCES"

    def filter_items(self, context, data, propname):
        return fbp_filter_uilist_items(
            context, getattr(data, propname, ()), self._PROFILE,
            self.bitflag_filter_item,
            attributes=("name", "effect_id", "description"),
        )

    def draw_item(
        self, context, layout, data, item, icon,
        active_data, active_propname, index,
    ):
        mark_ui_list_draw()
        _effect_id, definition, _valid = _mask_definition(item.effect_id)
        row = layout.row(align=True)
        visible = set(fbp_uilist_visible_columns(context, self._PROFILE))
        for key in fbp_uilist_icon_order(context, self._PROFILE):
            if key not in visible:
                continue
            if fbp_uilist_is_spacer(key):
                fbp_draw_uilist_spacer(row)
                continue
            if key == "preview":
                row.label(text="", icon=str(definition.get("icon", "MOD_MASK") or "MOD_MASK"))
            elif key == "label":
                row.prop(item, "name", text="", emboss=False)
            elif key == "apply":
                apply = row.operator(
                    "fbp.apply_mask_source", text="", icon="CHECKMARK", emboss=False
                )
                apply.index = index


def draw_mask_source_library_ui(layout, context, selected_rigs):
    scene = getattr(context, "scene", None)
    if scene is None or not hasattr(scene, "fbp_mask_sources"):
        return
    box = layout.box()
    configure_layout(box)
    sources = scene.fbp_mask_sources
    section_header(
        box,
        "Reusable Mask Sources",
        icon="ASSET_MANAGER",
        count=len(sources),
    )
    if not sources:
        row = box.row(align=True)
        row.enabled = bool(selected_rigs)
        row.operator(
            "fbp.add_mask_source",
            text="Save Active Mask",
            icon="ADD",
        )
        hint_row(
            box,
            "Select a mask to reuse its type and settings on other layers.",
            icon="INFO",
        )
        return
    list_box = fbp_draw_uilist_header(box, context, "MASK_SOURCES")
    row = list_box.row(align=False)
    row.template_list(
        "FBP_UL_MaskSources",
        "",
        scene,
        "fbp_mask_sources",
        scene,
        "fbp_mask_sources_index",
        rows=min(4, max(2, len(sources))),
    )
    tools = row.column(align=True)
    fbp_set_ui_units_x(tools, 1.0)
    tools.menu(
        "FBP_MT_mask_source_list_actions",
        text="",
        icon="COLLAPSEMENU",
    )
    tools.separator()
    tools.operator("fbp.add_mask_source", text="", icon="ADD")
    box.operator(
        "fbp.apply_mask_source",
        text="Apply to Selected Layers",
        icon="PASTEDOWN",
    )
    source, _index = _active_source(scene)
    if source is not None:
        box.prop(source, "description", text="Note")


_model_classes = (FBP_MaskSourcePreset,)
_interactive_classes = (
    FBP_OT_SetMaskStackOperation,
    FBP_OT_AddMaskSource,
    FBP_OT_UpdateMaskSource,
    FBP_OT_ApplyMaskSource,
    FBP_OT_RemoveMaskSource,
    FBP_MT_MaskSourceListActions,
    FBP_UL_MaskSources,
)
_registered_classes = globals().get("_registered_classes", [])
if not isinstance(_registered_classes, list):
    _registered_classes = []


def _register_scene_properties():
    bpy.types.Scene.fbp_mask_sources = CollectionProperty(
        type=FBP_MaskSourcePreset,
        name="Reusable Mask Sources",
        description="Reusable mask types and settings stored in this file",
    )
    bpy.types.Scene.fbp_mask_sources_index = IntProperty(
        default=0,
        min=0,
    )


def register():
    unregister_type_properties(
        bpy.types.Scene,
        ("fbp_mask_sources", "fbp_mask_sources_index"),
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
            ("fbp_mask_sources", "fbp_mask_sources_index"),
        )
        unregister_classes(tuple(_registered_classes))
        _registered_classes.clear()
        raise


def unregister():
    unregister_type_properties(
        bpy.types.Scene,
        ("fbp_mask_sources", "fbp_mask_sources_index"),
    )
    unregister_classes(tuple(_registered_classes))
    _registered_classes.clear()


__all__ = (
    "FBP_MASK_SOURCE_SCHEMA_VERSION",
    "audit_mask_sources",
    "draw_mask_source_library_ui",
)
