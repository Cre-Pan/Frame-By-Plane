"""Persistent and shareable complete Effect Stack presets."""

from __future__ import annotations

import json
from pathlib import Path

import bpy
from bpy.props import (
    CollectionProperty,
    EnumProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Menu, Operator, PropertyGroup, UIList
from bpy_extras.io_utils import ExportHelper, ImportHelper

from .constants import FBP_PUBLIC_VERSION_STRING
from .geometry_nodes import (
    FBP_EFFECT_STACK_PRESET_SCHEMA_VERSION,
    fbp_apply_effect_stack_snapshot,
    fbp_capture_effect_stack_snapshot,
    fbp_effect_definition,
    fbp_effect_supported_for_rig,
    fbp_normalize_effect_id,
)
from .layers import fbp_set_ui_units_x, get_selected_or_active_rigs
from .registration import (
    register_classes,
    register_interactive_classes,
    unregister_classes,
    unregister_type_properties,
)
from .runtime import FBP_DATA_ERRORS
from .ui_style import configure_layout, hint_row
from .ui_list_state import mark_ui_list_draw
from .interface_preferences import (
    fbp_draw_uilist_spacer,
    fbp_draw_uilist_header,
    fbp_filter_uilist_items,
    fbp_uilist_icon_order,
    fbp_uilist_is_spacer,
    fbp_uilist_visible_columns,
)


EFFECT_STACK_PRESET_FORMAT = "FRAME_BY_PLANE_EFFECT_STACK_PRESET"
EFFECT_STACK_PRESET_MAX_BYTES = 2 * 1024 * 1024

_CATEGORY_ITEMS = (
    ("GENERAL", "General", "General-purpose stack preset"),
    ("LOOK", "Look", "Color, texture and stylization stack"),
    ("MOTION", "Motion", "Animated or geometry-driven stack"),
    ("MASK", "Mask", "Mask-focused stack"),
    ("CUSTOM", "Custom", "User-defined category"),
)


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


def _decode_stack(raw):
    text = _safe_text(raw)
    if not text:
        return None, "Preset has no stack payload"
    if len(text.encode("utf-8")) > EFFECT_STACK_PRESET_MAX_BYTES:
        return None, "Preset exceeds the 2 MB safety limit"
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None, "Preset stack is not valid JSON"
    if not isinstance(payload, dict):
        return None, "Preset stack root must be an object"
    try:
        schema = int(payload.get("schema", 0) or 0)
    except (TypeError, ValueError):
        schema = 0
    if schema != FBP_EFFECT_STACK_PRESET_SCHEMA_VERSION:
        return (
            None,
            f"Preset stack schema {schema} is not supported by this version",
        )
    effects = payload.get("effects", ())
    if not isinstance(effects, list):
        return None, "Preset effects must be an array"
    if len(effects) > 512:
        return None, "Preset contains more than 512 effects"
    for index, state in enumerate(effects):
        if not isinstance(state, dict):
            return None, f"Preset effect row {index + 1} is invalid"
        effect_id = fbp_normalize_effect_id(state.get("effect_id", ""))
        if not effect_id or not fbp_effect_definition(effect_id):
            return None, f"Preset effect row {index + 1} is unavailable"
    return payload, ""


def _active_preset(scene):
    try:
        presets = scene.fbp_effect_stack_presets
        if not presets:
            return None, -1
        index = max(
            0,
            min(int(scene.fbp_effect_stack_presets_index), len(presets) - 1),
        )
        return presets[index], index
    except FBP_DATA_ERRORS:
        return None, -1


def _unique_name(scene, base="Effect Stack Preset"):
    base = _safe_text(base) or "Effect Stack Preset"
    try:
        existing = {
            _safe_text(item.name).casefold()
            for item in scene.fbp_effect_stack_presets
        }
    except FBP_DATA_ERRORS:
        existing = set()
    if base.casefold() not in existing:
        return base
    number = 2
    while f"{base} {number}".casefold() in existing:
        number += 1
    return f"{base} {number}"


def _store_stack(preset, stack, *, source_name=""):
    encoded = _canonical_json(stack)
    if len(encoded.encode("utf-8")) > EFFECT_STACK_PRESET_MAX_BYTES:
        raise ValueError("Effect Stack Preset exceeds the 2 MB safety limit")
    preset.schema_version = FBP_EFFECT_STACK_PRESET_SCHEMA_VERSION
    preset.payload_json = encoded
    preset.effect_count = len(stack.get("effects", ()) or ())
    preset.source_layer_name = _safe_text(source_name)


def _preset_package(preset):
    stack, error = _decode_stack(preset.payload_json)
    if stack is None:
        raise ValueError(error)
    return {
        "format": EFFECT_STACK_PRESET_FORMAT,
        "schema": FBP_EFFECT_STACK_PRESET_SCHEMA_VERSION,
        "addon_version": FBP_PUBLIC_VERSION_STRING,
        "name": _safe_text(preset.name) or "Effect Stack Preset",
        "description": _safe_text(preset.description),
        "category": _safe_text(preset.category) or "GENERAL",
        "stack": stack,
    }


def _validate_package(package):
    if not isinstance(package, dict):
        return None, "Package root must be an object"
    if _safe_text(package.get("format")) != EFFECT_STACK_PRESET_FORMAT:
        return None, "File is not a Frame By Plane Effect Stack Preset"
    try:
        schema = int(package.get("schema", 0) or 0)
    except (TypeError, ValueError):
        schema = 0
    if schema != FBP_EFFECT_STACK_PRESET_SCHEMA_VERSION:
        return None, f"Unsupported package schema {schema}"
    stack = package.get("stack")
    try:
        encoded = _canonical_json(stack)
    except (TypeError, ValueError):
        return None, "Package stack is not JSON-safe"
    decoded, error = _decode_stack(encoded)
    if decoded is None:
        return None, error
    result = dict(package)
    result["stack"] = decoded
    return result, ""


class FBP_EffectStackPreset(PropertyGroup):
    name: StringProperty(
        name="Name",
        description="Name of this complete reusable Effect Stack",
        default="Effect Stack Preset",
    )
    description: StringProperty(
        name="Description",
        description="Optional note about the intended look or workflow",
        default="",
    )
    category: EnumProperty(
        name="Category",
        items=_CATEGORY_ITEMS,
        default="GENERAL",
    )
    schema_version: IntProperty(
        default=FBP_EFFECT_STACK_PRESET_SCHEMA_VERSION,
        min=1,
        options={"HIDDEN"},
    )
    source_layer_name: StringProperty(
        name="Source Layer",
        default="",
        options={"HIDDEN"},
    )
    payload_json: StringProperty(
        name="Stack Data",
        default="",
        options={"HIDDEN"},
    )
    effect_count: IntProperty(
        name="Effects",
        default=0,
        min=0,
        options={"HIDDEN"},
    )


def audit_effect_stack_presets(scene, *, repair=False):
    issues = []
    warnings = []
    repaired = 0
    seen = set()
    try:
        presets = tuple(scene.fbp_effect_stack_presets)
    except FBP_DATA_ERRORS:
        presets = ()
    for index, preset in enumerate(presets):
        name = _safe_text(preset.name)
        base = name or "Effect Stack Preset"
        candidate = base
        number = 2
        while candidate.casefold() in seen:
            candidate = f"{base} {number}"
            number += 1
        if candidate != name:
            warnings.append(
                (
                    f'Effect Stack Preset "{name or "<unnamed>"}" has an '
                    "empty or duplicate name"
                )
            )
            if repair:
                preset.name = candidate
                repaired += 1
                name = candidate
        seen.add(candidate.casefold())
        try:
            schema = int(preset.schema_version)
        except (TypeError, ValueError):
            schema = 0
        if schema > FBP_EFFECT_STACK_PRESET_SCHEMA_VERSION:
            issues.append(
                f'{name or "Effect Stack Preset"} uses newer schema {schema}'
            )
            continue
        stack, error = _decode_stack(preset.payload_json)
        if stack is None:
            issues.append(f'{name or "Effect Stack Preset"}: {error}')
            continue
        count = len(stack.get("effects", ()) or ())
        if count == 0:
            warnings.append(f'{name or "Effect Stack Preset"} is empty')
        if repair:
            canonical = _canonical_json(stack)
            if preset.payload_json != canonical:
                preset.payload_json = canonical
                repaired += 1
            if preset.effect_count != count:
                preset.effect_count = count
                repaired += 1
    return {
        "issues": tuple(dict.fromkeys(issues)),
        "warnings": tuple(dict.fromkeys(warnings)),
        "repaired": repaired,
        "stats": {
            "effect_stack_preset_issues": len(issues),
            "effect_stack_preset_warnings": len(warnings),
        },
    }


def _apply_preset_to_rigs(rigs, preset, mode):
    stack, error = _decode_stack(preset.payload_json)
    if stack is None:
        return False, error, 0
    states = list(stack.get("effects", ()) or ())
    incompatible = []
    for rig in rigs:
        for state in states:
            effect_id = fbp_normalize_effect_id(state.get("effect_id", ""))
            if not fbp_effect_supported_for_rig(rig, effect_id):
                incompatible.append(
                    f"{getattr(rig, 'name', 'Layer')}: {effect_id}"
                )
    if incompatible:
        return (
            False,
            "Incompatible preset effects: " + ", ".join(incompatible[:8]),
            0,
        )
    backups = [
        (rig, fbp_capture_effect_stack_snapshot(rig))
        for rig in rigs
    ]
    applied = 0
    for rig in rigs:
        result = fbp_apply_effect_stack_snapshot(rig, stack, mode=mode)
        if not result.get("success", False):
            for restored_rig, backup in backups:
                fbp_apply_effect_stack_snapshot(
                    restored_rig,
                    backup,
                    mode="REPLACE",
                )
            return (
                False,
                result.get("error", "Could not apply Effect Stack Preset"),
                applied,
            )
        applied += int(result.get("applied", 0) or 0)
    return True, "", applied


class FBP_OT_AddEffectStackPreset(Operator):
    bl_idname = "fbp.add_effect_stack_preset"
    bl_label = "Save Effect Stack Preset"
    bl_description = "Save the active layer's complete Effect Stack in this blend file"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        rigs = get_selected_or_active_rigs(context)
        if not rigs:
            self.report({"WARNING"}, "Select a Frame By Plane layer")
            return {"CANCELLED"}
        stack = fbp_capture_effect_stack_snapshot(rigs[0])
        scene = context.scene
        preset_name = _unique_name(scene)
        preset = scene.fbp_effect_stack_presets.add()
        preset.name = preset_name
        try:
            _store_stack(
                preset,
                stack,
                source_name=getattr(rigs[0], "name", ""),
            )
        except ValueError as exc:
            scene.fbp_effect_stack_presets.remove(
                len(scene.fbp_effect_stack_presets) - 1
            )
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        scene.fbp_effect_stack_presets_index = (
            len(scene.fbp_effect_stack_presets) - 1
        )
        self.report(
            {"INFO"},
            f"Saved {preset.effect_count} effect(s) in {preset.name}",
        )
        return {"FINISHED"}


class FBP_OT_UpdateEffectStackPreset(Operator):
    bl_idname = "fbp.update_effect_stack_preset"
    bl_label = "Update Effect Stack Preset"
    bl_description = "Replace the selected preset with the active layer's current stack"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        preset, _index = _active_preset(context.scene)
        rigs = get_selected_or_active_rigs(context)
        if preset is None or not rigs:
            return {"CANCELLED"}
        try:
            _store_stack(
                preset,
                fbp_capture_effect_stack_snapshot(rigs[0]),
                source_name=getattr(rigs[0], "name", ""),
            )
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f'Updated "{preset.name}"')
        return {"FINISHED"}


class FBP_OT_ApplyEffectStackPreset(Operator):
    bl_idname = "fbp.apply_effect_stack_preset"
    bl_label = "Apply Effect Stack Preset"
    bl_description = "Apply the selected complete stack to compatible selected layers"
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(
        name="Mode",
        items=(
            ("REPLACE", "Replace", "Replace the complete target stack"),
            ("MERGE", "Merge", "Keep unrelated target effects and merge matching ones"),
        ),
        default="REPLACE",
        options={"SKIP_SAVE"},
    )
    index: IntProperty(default=-1, options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        scene = context.scene
        index = int(self.index)
        if index < 0:
            _preset, index = _active_preset(scene)
        rigs = get_selected_or_active_rigs(context)
        if not (0 <= index < len(scene.fbp_effect_stack_presets)) or not rigs:
            return {"CANCELLED"}
        scene.fbp_effect_stack_presets_index = index
        preset = scene.fbp_effect_stack_presets[index]
        success, error, applied = _apply_preset_to_rigs(
            rigs,
            preset,
            self.mode,
        )
        if not success:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"{self.mode.title()} applied {applied} effect state(s) "
            f"to {len(rigs)} layer(s)",
        )
        return {"FINISHED"}


class FBP_OT_RemoveEffectStackPreset(Operator):
    bl_idname = "fbp.remove_effect_stack_preset"
    bl_label = "Remove Effect Stack Preset"
    bl_description = "Remove the selected preset without changing any layer"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        preset, index = _active_preset(scene)
        if preset is None:
            return {"CANCELLED"}
        name = _safe_text(preset.name)
        scene.fbp_effect_stack_presets.remove(index)
        scene.fbp_effect_stack_presets_index = min(
            index,
            max(0, len(scene.fbp_effect_stack_presets) - 1),
        )
        self.report({"INFO"}, f'Removed "{name}"')
        return {"FINISHED"}


class FBP_OT_MoveEffectStackPreset(Operator):
    bl_idname = "fbp.move_effect_stack_preset"
    bl_label = "Move Effect Stack Preset"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        items=(
            ("UP", "Up", "Move earlier"),
            ("DOWN", "Down", "Move later"),
        ),
        default="UP",
        options={"HIDDEN", "SKIP_SAVE"},
    )

    def execute(self, context):
        scene = context.scene
        _preset, index = _active_preset(scene)
        target = index - 1 if self.direction == "UP" else index + 1
        if not (0 <= index < len(scene.fbp_effect_stack_presets)):
            return {"CANCELLED"}
        if not (0 <= target < len(scene.fbp_effect_stack_presets)):
            return {"CANCELLED"}
        scene.fbp_effect_stack_presets.move(index, target)
        scene.fbp_effect_stack_presets_index = target
        return {"FINISHED"}


class FBP_OT_ExportEffectStackPreset(Operator, ExportHelper):
    bl_idname = "fbp.export_effect_stack_preset"
    bl_label = "Export Effect Stack Preset"
    bl_description = "Share the selected complete stack as a portable .fbpack file"

    filename_ext = ".fbpack"
    filter_glob: StringProperty(default="*.fbpack", options={"HIDDEN"})

    def execute(self, context):
        preset, _index = _active_preset(context.scene)
        if preset is None:
            return {"CANCELLED"}
        try:
            package = _preset_package(preset)
            encoded = json.dumps(
                package,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            if len(encoded.encode("utf-8")) > EFFECT_STACK_PRESET_MAX_BYTES:
                raise ValueError("Preset package exceeds the 2 MB safety limit")
            path = Path(self.filepath)
            temporary = path.with_name(f".{path.name}.tmp")
            temporary.write_text(encoded, encoding="utf-8")
            temporary.replace(path)
        except (OSError, TypeError, ValueError) as exc:
            self.report({"ERROR"}, f"Could not export preset: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Exported {path.name}")
        return {"FINISHED"}


class FBP_OT_ImportEffectStackPreset(Operator, ImportHelper):
    bl_idname = "fbp.import_effect_stack_preset"
    bl_label = "Import Effect Stack Preset"
    bl_description = "Import a validated Frame By Plane .fbpack stack preset"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".fbpack"
    filter_glob: StringProperty(default="*.fbpack", options={"HIDDEN"})

    def execute(self, context):
        path = Path(self.filepath)
        try:
            if path.stat().st_size > EFFECT_STACK_PRESET_MAX_BYTES:
                raise ValueError("Preset package exceeds the 2 MB safety limit")
            package = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            self.report({"ERROR"}, f"Could not read preset: {exc}")
            return {"CANCELLED"}
        package, error = _validate_package(package)
        if package is None:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        scene = context.scene
        preset_name = _unique_name(
            scene,
            _safe_text(package.get("name")) or path.stem,
        )
        preset = scene.fbp_effect_stack_presets.add()
        preset.name = preset_name
        preset.description = _safe_text(package.get("description"))
        category = _safe_text(package.get("category")).upper()
        preset.category = (
            category
            if category in {item[0] for item in _CATEGORY_ITEMS}
            else "CUSTOM"
        )
        try:
            _store_stack(preset, package["stack"])
        except ValueError as exc:
            scene.fbp_effect_stack_presets.remove(
                len(scene.fbp_effect_stack_presets) - 1
            )
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        scene.fbp_effect_stack_presets_index = (
            len(scene.fbp_effect_stack_presets) - 1
        )
        self.report({"INFO"}, f'Imported "{preset.name}"')
        return {"FINISHED"}


class FBP_MT_EffectStackPresetListActions(Menu):
    bl_idname = "FBP_MT_effect_stack_preset_list_actions"
    bl_label = "Effect Stack Preset Actions"

    def draw(self, _context):
        layout = configure_layout(self.layout)
        layout.operator("fbp.update_effect_stack_preset", text="Update from Current Stack", icon="FILE_REFRESH")
        layout.operator("fbp.export_effect_stack_preset", text="Export", icon="EXPORT")
        layout.operator("fbp.import_effect_stack_preset", text="Import", icon="IMPORT")
        layout.separator()
        layout.operator("fbp.remove_effect_stack_preset", text="Remove Preset", icon="TRASH")


class FBP_UL_EffectStackPresets(UIList):
    _PROFILE = "EFFECT_STACK_PRESETS"

    def filter_items(self, context, data, propname):
        return fbp_filter_uilist_items(
            context, getattr(data, propname, ()), self._PROFILE,
            self.bitflag_filter_item, attributes=("name", "description"),
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
                row.label(text="", icon="PRESET")
            elif key == "label":
                row.prop(item, "name", text="", emboss=False)
            elif key == "count":
                row.label(text=str(int(getattr(item, "effect_count", 0) or 0)), icon="LINENUMBERS_ON")
            elif key == "apply":
                apply = row.operator(
                    "fbp.apply_effect_stack_preset", text="", icon="CHECKMARK", emboss=False
                )
                apply.index = index
                apply.mode = "REPLACE"


def draw_effect_stack_presets_ui(layout, context, selected_rigs):
    scene = getattr(context, "scene", None)
    if scene is None or not hasattr(scene, "fbp_effect_stack_presets"):
        return
    presets = scene.fbp_effect_stack_presets
    try:
        header, body = layout.panel(
            "FBP_effect_stack_presets_section",
            default_closed=True,
        )
    except (AttributeError, RuntimeError, TypeError, ValueError):
        header = layout.row(align=False)
        body = layout.column(align=False)
    header.label(
        text=f"Effect Stack Presets · {len(presets)}",
        icon="PRESET",
    )
    if body is None:
        return
    box = body.box()
    configure_layout(box)
    if not presets:
        row = box.row(align=True)
        row.enabled = bool(selected_rigs)
        row.operator(
            "fbp.add_effect_stack_preset",
            text="Save Current Stack",
            icon="ADD",
        )
        box.operator(
            "fbp.import_effect_stack_preset",
            text="Import .fbpack",
            icon="IMPORT",
        )
        hint_row(
            box,
            "Save complete settings, order, visibility, groups and multi-instances.",
            icon="INFO",
        )
        return
    list_box = fbp_draw_uilist_header(
        box, context, "EFFECT_STACK_PRESETS"
    )
    row = list_box.row(align=False)
    row.template_list(
        "FBP_UL_EffectStackPresets",
        "",
        scene,
        "fbp_effect_stack_presets",
        scene,
        "fbp_effect_stack_presets_index",
        rows=min(4, max(2, len(presets))),
    )
    tools = row.column(align=True)
    fbp_set_ui_units_x(tools, 1.0)
    tools.menu(
        "FBP_MT_effect_stack_preset_list_actions",
        text="",
        icon="COLLAPSEMENU",
    )
    tools.separator()
    move = tools.column(align=True)
    _active, active_index = _active_preset(scene)
    up_row = move.row(align=True)
    up_row.enabled = active_index > 0
    up = up_row.operator(
        "fbp.move_effect_stack_preset", text="", icon="SORT_DESC"
    )
    up.direction = "UP"
    down_row = move.row(align=True)
    down_row.enabled = 0 <= active_index < len(presets) - 1
    down = down_row.operator(
        "fbp.move_effect_stack_preset", text="", icon="SORT_ASC"
    )
    down.direction = "DOWN"
    tools.separator()
    tools.operator("fbp.add_effect_stack_preset", text="", icon="ADD")
    apply = box.row(align=True)
    replace = apply.operator(
        "fbp.apply_effect_stack_preset",
        text="Replace",
        icon="CHECKMARK",
    )
    replace.mode = "REPLACE"
    merge = apply.operator(
        "fbp.apply_effect_stack_preset",
        text="Merge",
        icon="ADD",
    )
    merge.mode = "MERGE"
    share = box.row(align=True)
    share.operator(
        "fbp.export_effect_stack_preset",
        text="Export",
        icon="EXPORT",
    )
    share.operator(
        "fbp.import_effect_stack_preset",
        text="Import",
        icon="IMPORT",
    )
    preset, _index = _active_preset(scene)
    if preset is not None:
        details = box.row(align=True)
        details.prop(preset, "category", text="")
        details.prop(preset, "description", text="Note")


_model_classes = (FBP_EffectStackPreset,)
_interactive_classes = (
    FBP_OT_AddEffectStackPreset,
    FBP_OT_UpdateEffectStackPreset,
    FBP_OT_ApplyEffectStackPreset,
    FBP_OT_RemoveEffectStackPreset,
    FBP_OT_MoveEffectStackPreset,
    FBP_OT_ExportEffectStackPreset,
    FBP_OT_ImportEffectStackPreset,
    FBP_MT_EffectStackPresetListActions,
    FBP_UL_EffectStackPresets,
)
_registered_classes = globals().get("_registered_classes", [])
if not isinstance(_registered_classes, list):
    _registered_classes = []


def _register_scene_properties():
    bpy.types.Scene.fbp_effect_stack_presets = CollectionProperty(
        type=FBP_EffectStackPreset,
        name="Effect Stack Presets",
        description="Complete reusable Effect Stacks stored in this file",
    )
    bpy.types.Scene.fbp_effect_stack_presets_index = IntProperty(
        name="Effect Stack Preset",
        default=0,
        min=0,
    )


def register():
    unregister_type_properties(
        bpy.types.Scene,
        (
            "fbp_effect_stack_presets",
            "fbp_effect_stack_presets_index",
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
                "fbp_effect_stack_presets",
                "fbp_effect_stack_presets_index",
            ),
        )
        unregister_classes(tuple(_registered_classes))
        _registered_classes.clear()
        raise


def unregister():
    unregister_type_properties(
        bpy.types.Scene,
        (
            "fbp_effect_stack_presets",
            "fbp_effect_stack_presets_index",
        ),
    )
    unregister_classes(tuple(_registered_classes))
    _registered_classes.clear()


__all__ = (
    "EFFECT_STACK_PRESET_FORMAT",
    "EFFECT_STACK_PRESET_MAX_BYTES",
    "audit_effect_stack_presets",
    "draw_effect_stack_presets_ui",
)
