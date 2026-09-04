"""Run a one-by-one Frame By Plane effect audit inside Blender 5.2.

Environment variables:
    FBP_AUDIT_SOURCE   Path to the add-on source directory.
    FBP_AUDIT_REPORT   Destination JSON report.
    FBP_AUDIT_KIND     BASE, SHADER, GEOMETRY or ALL (default: ALL).
    FBP_AUDIT_IDS      Optional comma-separated effect IDs to audit.
    FBP_AUDIT_REPEATS  Optional repeat count for cold/warm profiling.
    FBP_AUDIT_PACKAGE  Installed package namespace (optional; uses enabled add-on).
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
import time
import traceback
from pathlib import Path

import bpy


sys.dont_write_bytecode = True
PACKAGE = os.environ.get("FBP_AUDIT_PACKAGE", "frame_by_plane")
SOURCE = Path(os.environ["FBP_AUDIT_SOURCE"]).resolve()
REPORT = Path(os.environ["FBP_AUDIT_REPORT"]).resolve()
KIND = str(os.environ.get("FBP_AUDIT_KIND", "ALL") or "ALL").upper()
EFFECT_IDS = {
    value.strip().upper()
    for value in str(os.environ.get("FBP_AUDIT_IDS", "") or "").split(",")
    if value.strip()
}
try:
    REPEATS = max(1, int(os.environ.get("FBP_AUDIT_REPEATS", "1") or 1))
except (TypeError, ValueError):
    REPEATS = 1


def write_report(payload):
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    temporary = REPORT.with_suffix(REPORT.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    temporary.replace(REPORT)


def load_addon():
    if PACKAGE != "frame_by_plane":
        module = importlib.import_module(PACKAGE)
        if Path(module.__file__).resolve().parent != SOURCE:
            raise RuntimeError("Installed effect-audit package does not match FBP_AUDIT_SOURCE")
        if PACKAGE not in {item.module for item in bpy.context.preferences.addons}:
            raise RuntimeError("Installed effect-audit package is not enabled")
        return module
    spec = importlib.util.spec_from_file_location(
        PACKAGE,
        SOURCE / "__init__.py",
        submodule_search_locations=[str(SOURCE)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not create the Frame By Plane package spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    spec.loader.exec_module(module)
    module.register()
    return module


def make_fixture(builder, name, location):
    fixture = REPORT.parent / "effect-audit-fixture.png"
    if not fixture.is_file():
        image = bpy.data.images.new("FBP Effect Audit Fixture", width=32, height=24, alpha=True)
        try:
            image.generated_color = (0.18, 0.42, 0.82, 0.86)
            image.filepath_raw = str(fixture)
            image.file_format = "PNG"
            image.save()
        finally:
            bpy.data.images.remove(image)
    return builder.build_fbp_rig(
        bpy.context,
        name,
        str(fixture.parent),
        [fixture.name],
        location,
        target_collection=bpy.context.scene.collection,
    )


def ensure_camera():
    data = bpy.data.cameras.new("FBP Effect Audit Camera")
    camera = bpy.data.objects.new("FBP Effect Audit Camera", data)
    bpy.context.scene.collection.objects.link(camera)
    camera.location = (0.0, -8.0, 0.0)
    camera.rotation_euler = (1.57079632679, 0.0, 0.0)
    bpy.context.scene.camera = camera
    return camera


def group_socket_names(group, in_out):
    names = set()
    for item in tuple(getattr(getattr(group, "interface", None), "items_tree", ()) or ()):
        if getattr(item, "item_type", "") == "SOCKET" and getattr(item, "in_out", "") == in_out:
            names.add(str(getattr(item, "name", "") or ""))
    return sorted(names)


def json_safe_value(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    try:
        return [json_safe_value(item) for item in tuple(value)]
    except (TypeError, ValueError):
        return str(value)


def gp_native_property_snapshot(bridge, item, effect_id):
    result = {}
    for row in bridge._GP_NATIVE_EFFECT_UI_PROPS.get(str(effect_id).upper(), ()):
        for attr_name, label, slider in row:
            resolved = bridge._gp_resolve_native_attr(item, attr_name)
            if not resolved or resolved in result:
                continue
            try:
                value = getattr(item, resolved)
            except Exception:
                continue
            metadata = {
                "logical_name": attr_name,
                "label": label,
                "slider": bool(slider),
                "value": json_safe_value(value),
            }
            try:
                prop = item.bl_rna.properties.get(resolved)
                metadata.update({
                    "type": str(getattr(prop, "type", "") or ""),
                    "subtype": str(getattr(prop, "subtype", "") or ""),
                    "array_length": int(getattr(prop, "array_length", 0) or 0),
                    "hard_min": json_safe_value(getattr(prop, "hard_min", None)),
                    "hard_max": json_safe_value(getattr(prop, "hard_max", None)),
                    "default": json_safe_value(
                        getattr(prop, "default_array", ())
                        if int(getattr(prop, "array_length", 0) or 0)
                        else getattr(prop, "default", None)
                    ),
                })
            except Exception:
                pass
            result[resolved] = metadata
    return result


def gp_native_rna_snapshot(item):
    result = {}
    try:
        properties = tuple(item.bl_rna.properties)
    except Exception:
        return result
    for prop in properties:
        identifier = str(getattr(prop, "identifier", "") or "")
        if not identifier or identifier == "rna_type":
            continue
        try:
            if bool(getattr(prop, "is_readonly", False)):
                continue
            value = getattr(item, identifier)
        except Exception:
            continue
        result[identifier] = {
            "name": str(getattr(prop, "name", identifier) or identifier),
            "description": str(getattr(prop, "description", "") or ""),
            "type": str(getattr(prop, "type", "") or ""),
            "subtype": str(getattr(prop, "subtype", "") or ""),
            "array_length": int(getattr(prop, "array_length", 0) or 0),
            "value": json_safe_value(value),
        }
    return result


def evaluate_rig(geometry, rig):
    started = time.perf_counter()
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    plane = geometry._fbp_plane(rig, repair=False)
    if plane is None:
        raise RuntimeError("Generated rig has no plane")
    evaluated = plane.evaluated_get(depsgraph)
    data = getattr(evaluated, "data", None)
    detail = {
        "object_type": str(getattr(evaluated, "type", "")),
        "vertices": len(getattr(data, "vertices", ()) or ()) if data is not None else 0,
        "polygons": len(getattr(data, "polygons", ()) or ()) if data is not None else 0,
    }
    detail["seconds"] = time.perf_counter() - started
    return detail


def clean_effect(geometry, rig, effect_id):
    if geometry.fbp_effect_is_active(rig, effect_id):
        geometry.fbp_remove_effect(rig, effect_id)
    return not geometry.fbp_effect_is_active(rig, effect_id)


def audit_effect(geometry, builtin, rig, effect_id, definition):
    record = {
        "effect_id": effect_id,
        "label": str(definition.get("label", effect_id)),
        "kind": str(definition.get("kind", "")),
        "category": str(definition.get("category", "")),
        "stage": str(definition.get("stage", "")),
        "performance": str(definition.get("performance", "")),
        "status": "FAIL",
        "issues": [],
    }
    before_objects = {obj.as_pointer(): obj.name for obj in bpy.data.objects}
    try:
        if not clean_effect(geometry, rig, effect_id):
            record["issues"].append("effect was active before its isolated test")

        group = None
        if definition.get("kind") in {"SHADER", "GEOMETRY"}:
            started = time.perf_counter()
            group = (
                geometry.fbp_load_mesh_wiggle_group()
                if effect_id == geometry.FBP_EFFECT_MESH_WIGGLE
                else geometry._fbp_load_effect_group(effect_id)
            )
            record["group_build_seconds"] = time.perf_counter() - started
            if group is None:
                record["issues"].append("node group could not be loaded or built")
            else:
                record["group"] = {
                    "name": str(group.name),
                    "nodes": len(group.nodes),
                    "links": len(group.links),
                    "inputs": group_socket_names(group, "INPUT"),
                    "outputs": group_socket_names(group, "OUTPUT"),
                    "complete": bool(builtin._builtin_group_is_complete(group, definition)),
                }
                if not record["group"]["complete"]:
                    record["issues"].append("generated node group failed its complete contract")

        property_names = sorted(
            set((definition.get("property_map", {}) or {}).keys())
            | set(definition.get("extra_properties", ()) or ())
        )
        missing_properties = [name for name in property_names if not hasattr(rig, name)]
        record["property_count"] = len(property_names)
        record["missing_properties"] = missing_properties
        if missing_properties:
            record["issues"].append("missing registered properties: " + ", ".join(missing_properties))

        supported = bool(geometry.fbp_effect_supported_for_rig(rig, effect_id))
        record["supported_for_fixture"] = supported
        started = time.perf_counter()
        added = bool(
            geometry.fbp_add_effect(
                rig,
                effect_id,
                select_object_mask_helper=False,
                inherit_active_group=False,
            )
        )
        record["add_seconds"] = time.perf_counter() - started
        active_after_add = bool(geometry.fbp_effect_is_active(rig, effect_id))
        record["added"] = added
        record["active_after_add"] = active_after_add
        if supported and (not added or not active_after_add):
            record["issues"].append("supported effect did not become active")
        elif not supported and added:
            record["issues"].append("unsupported effect was unexpectedly added")

        if active_after_add:
            record["evaluation"] = evaluate_rig(geometry, rig)
            started = time.perf_counter()
            removed = bool(geometry.fbp_remove_effect(rig, effect_id))
            record["remove_seconds"] = time.perf_counter() - started
            record["removed"] = removed
            record["active_after_remove"] = bool(geometry.fbp_effect_is_active(rig, effect_id))
            if not removed or record["active_after_remove"]:
                record["issues"].append("effect did not cleanly deactivate")
        else:
            record["removed"] = False
            record["active_after_remove"] = False

        after_objects = {obj.as_pointer(): obj.name for obj in bpy.data.objects}
        record["residual_objects"] = [
            name for pointer, name in after_objects.items() if pointer not in before_objects
        ]
        if record["residual_objects"]:
            record["issues"].append(
                "objects remained after removal: " + ", ".join(record["residual_objects"])
            )
        record["status"] = "PASS" if not record["issues"] else "FAIL"
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["traceback"] = traceback.format_exc()
        try:
            clean_effect(geometry, rig, effect_id)
        except Exception:
            pass
    return record


def audit_gp_native_effect(bridge, canvas, definition):
    effect_id, label, _icon, backend, native_types = definition
    record = {
        "effect_id": effect_id,
        "label": label,
        "kind": "GP_NATIVE",
        "backend": backend,
        "native_types": list(native_types),
        "status": "FAIL",
        "issues": [],
    }
    try:
        supported = bool(bridge._gp_native_effect_supported(canvas, definition))
        record["supported_for_fixture"] = supported
        record["resolved_native_type"] = str(
            bridge._gp_supported_native_type(canvas, definition) or ""
        )
        started = time.perf_counter()
        item = bridge._gp_add_native_effect(canvas, effect_id) if supported else None
        record["add_seconds"] = time.perf_counter() - started
        record["added"] = item is not None
        active = bridge._gp_native_effect_instances(canvas).get(effect_id)
        record["active_after_add"] = active is not None
        if active is not None:
            record["properties"] = gp_native_property_snapshot(
                bridge, active, effect_id
            )
            record["rna_properties"] = gp_native_rna_snapshot(active)
        if supported and (item is None or active is None):
            record["issues"].append("supported native effect did not become active")
        if not supported and item is not None:
            record["issues"].append("unsupported native effect was unexpectedly added")
        if item is not None:
            bpy.context.view_layer.update()
            started = time.perf_counter()
            removed = bool(bridge._gp_remove_native_effect(canvas, effect_id))
            record["remove_seconds"] = time.perf_counter() - started
            record["removed"] = removed
            record["active_after_remove"] = (
                bridge._gp_native_effect_instances(canvas).get(effect_id) is not None
            )
            if not removed or record["active_after_remove"]:
                record["issues"].append("native effect did not cleanly deactivate")
        else:
            record["removed"] = False
            record["active_after_remove"] = False
        record["status"] = "PASS" if not record["issues"] else "FAIL"
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["traceback"] = traceback.format_exc()
        try:
            bridge._gp_remove_native_effect(canvas, effect_id)
        except Exception:
            pass
    return record


def audit_gp_native(payload):
    bridge = importlib.import_module(f"{PACKAGE}.grease_pencil_bridge")
    result = bpy.ops.fbp.add_grease_pencil_canvas(
        "EXEC_DEFAULT",
        canvas_name="FBP GP Native Effect Audit",
        owner_name="__FREE__",
        enter_draw_mode=False,
    )
    if "FINISHED" not in result:
        raise RuntimeError(f"Could not create Grease Pencil audit canvas: {result}")
    canvas = bpy.context.object
    definitions = [
        definition for definition in bridge.GP_NATIVE_EFFECTS
        if not EFFECT_IDS or str(definition[0]).upper() in EFFECT_IDS
    ] * REPEATS
    payload["expected"] = len(definitions)
    for definition in definitions:
        payload["effects"].append(
            audit_gp_native_effect(bridge, canvas, definition)
        )
        write_report(payload)


def main():
    started = time.perf_counter()
    payload = {
        "blender": bpy.app.version_string,
        "source": str(SOURCE),
        "kind_filter": KIND,
        "effect_ids_filter": sorted(EFFECT_IDS),
        "repeats": REPEATS,
        "registry_issues": [],
        "effects": [],
        "status": "RUNNING",
    }
    write_report(payload)
    addon = None
    try:
        addon = load_addon()
        registry = importlib.import_module(f"{PACKAGE}.effects_registry")
        geometry = importlib.import_module(f"{PACKAGE}.geometry_nodes")
        builtin = importlib.import_module(f"{PACKAGE}.builtin_effects")
        builder = importlib.import_module(f"{PACKAGE}.builder")
        payload["registry_issues"] = list(registry.FBP_EFFECT_REGISTRY_ISSUES)
        if KIND == "GP_NATIVE":
            audit_gp_native(payload)
        else:
            ensure_camera()
            make_fixture(builder, "FBP Effect Audit Source", (0.0, 0.0, -0.1))
            rig = make_fixture(builder, "FBP Effect Audit Target", (0.0, 0.0, 0.0))
            bpy.context.view_layer.objects.active = rig
            rig.select_set(True)

            definitions = [
                (effect_id, definition)
                for effect_id, definition in registry.FBP_EFFECT_REGISTRY.items()
                if (KIND == "ALL" or str(definition.get("kind", "")).upper() == KIND)
                and (not EFFECT_IDS or str(effect_id).upper() in EFFECT_IDS)
            ] * REPEATS
            payload["expected"] = len(definitions)
            for effect_id, definition in definitions:
                payload["effects"].append(
                    audit_effect(geometry, builtin, rig, effect_id, definition)
                )
                write_report(payload)
        failed = [item["effect_id"] for item in payload["effects"] if item["status"] != "PASS"]
        payload["failed"] = failed
        payload["passed"] = len(payload["effects"]) - len(failed)
        payload["status"] = "PASS" if not failed and not payload["registry_issues"] else "FAIL"
    except Exception as exc:
        payload["status"] = "ERROR"
        payload["fatal_error"] = f"{type(exc).__name__}: {exc}"
        payload["fatal_traceback"] = traceback.format_exc()
    finally:
        payload["seconds"] = time.perf_counter() - started
        write_report(payload)
        if addon is not None:
            try:
                addon.unregister()
            except Exception:
                payload["unregister_error"] = traceback.format_exc()
                write_report(payload)
    if payload["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
