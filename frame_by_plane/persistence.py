"""Save/reopen persistence diagnostics for Frame By Plane.

The baseline is stored inside the current .blend as a Text datablock. It is
semantic rather than byte-based: native frames, transforms, animation, complete
effect state, mask ownership and planar Lattice point deformation are compared
after Blender has actually replaced Main.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime

import bpy
from bpy.props import BoolProperty
from bpy.types import Operator

from .constants import FBP_VERSION_STRING
from .diagnostics import write_diagnostic_report
from .geometry_nodes import (
    fbp_capture_effect_state_snapshot,
    fbp_effect_ids_for_rig,
    fbp_effect_instance_id_for_rig,
    fbp_effect_mask_raw_target,
    fbp_lattice_contract_report,
)
from .layers import fbp_layer_backend_type, is_fbp_layer_object
from .object_masks import (
    FBP_OBJECT_MASK_SHAPES,
    KEY_IMAGE_NAME as FBP_OBJECT_MASK_IMAGE_NAME_KEY,
    object_mask_contract,
    object_mask_pointer_property,
)
from .runtime import FBP_DATA_ERRORS
from .scene_sync import sync_layer_collection


# SECTION - Persistence / save-reopen contract #
_FBP_PERSISTENCE_SCHEMA = 1
_FBP_PERSISTENCE_BASELINE_TEXT = "FBP_Persistence_Baseline"
_FBP_PERSISTENCE_SCENE_ID_KEY = "fbp_persistence_scene_id"
_FBP_PERSISTENCE_TEXT_KEY = "fbp_persistence_text"
_FBP_PERSISTENCE_RIG_ID_KEY = "fbp_persistence_id"
_FBP_PERSISTENCE_LOAD_GENERATION_KEY = "fbp_persistence_load_generation"
_FBP_PERSISTENCE_STATUS_KEY = "fbp_persistence_status"
_FBP_PERSISTENCE_HASH_KEY = "fbp_persistence_hash"
_FBP_PERSISTENCE_VERIFIED_AT_KEY = "fbp_persistence_verified_at"
_FBP_PERSISTENCE_SESSION_TOKEN = globals().get(
    "_FBP_PERSISTENCE_SESSION_TOKEN", uuid.uuid4().hex
)

_FBP_PERSISTENCE_LAYER_PROPERTIES = (
    "fbp_collection_name",
    "fbp_follow_collection_color",
    "fbp_color_variant_index",
    "fbp_base_scale_vec",
    "fbp_is_vertical",
    "fbp_sequence_reversed",
    "fbp_color_tag",
    "fbp_depth_order",
    "fbp_loop_mode",
    "fbp_use_emission",
    "fbp_interpolation",
    "fbp_global_duration",
    "fbp_start_frame",
    "fbp_opacity",
    "fbp_track_cam",
    "fbp_is_visible",
    "fbp_is_color_plane",
    "fbp_color_plane_mode",
    "fbp_color_plane_color",
    "fbp_color_plane_emission",
    "fbp_gradient_mode",
    "fbp_gradient_kind",
    "fbp_gradient_color_a",
    "fbp_gradient_color_b",
    "fbp_gradient_reverse",
    "fbp_gradient_offset_x",
    "fbp_gradient_offset_y",
    "fbp_gradient_scale_x",
    "fbp_gradient_scale_y",
    "fbp_gradient_rotation",
    "fbp_extend_mode",
    "fbp_extend_left",
    "fbp_extend_right",
    "fbp_extend_top",
    "fbp_extend_bottom",
    "fbp_crop_left",
    "fbp_crop_right",
    "fbp_crop_top",
    "fbp_crop_bottom",
)


def _fbp_persistence_json_value(value):
    """Convert RNA values to deterministic JSON without retaining pointers."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return round(value, 7)
    try:
        if hasattr(value, "bl_rna") and hasattr(value, "name"):
            return {
                "datablock": str(getattr(value, "name", "") or ""),
                "type": str(
                    getattr(getattr(value, "bl_rna", None), "identifier", "") or ""
                ),
            }
    except FBP_DATA_ERRORS:
        return None
    if isinstance(value, dict):
        return {
            str(key): _fbp_persistence_json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    try:
        return [_fbp_persistence_json_value(item) for item in value]
    except TypeError:
        return str(value)


def _fbp_persistence_transform(obj):
    if obj is None:
        return None
    try:
        matrix = tuple(
            round(float(value), 7)
            for row in obj.matrix_world
            for value in row
        )
        return {
            "matrix_world": matrix,
            "rotation_mode": str(getattr(obj, "rotation_mode", "") or ""),
        }
    except FBP_DATA_ERRORS:
        return None


def _fbp_persistence_point_hash(points, *attributes):
    digest = hashlib.sha256()
    count = 0
    for point in tuple(points or ()):
        coordinate = None
        for attribute in attributes:
            try:
                coordinate = getattr(point, attribute, None)
            except FBP_DATA_ERRORS:
                coordinate = None
            if coordinate is not None:
                break
        if coordinate is None:
            continue
        try:
            values = tuple(round(float(value), 7) for value in coordinate)
        except (TypeError, ValueError):
            continue
        digest.update((",".join(f"{value:.7f}" for value in values) + ";").encode("ascii"))
        count += 1
    return {"count": count, "sha256": digest.hexdigest() if count else ""}


def _fbp_persistence_scene_id(scene, *, ensure=False):
    if scene is None:
        return ""
    try:
        current = str(scene.get(_FBP_PERSISTENCE_SCENE_ID_KEY, "") or "")
        if not current and ensure:
            current = uuid.uuid4().hex
            scene[_FBP_PERSISTENCE_SCENE_ID_KEY] = current
        return current
    except FBP_DATA_ERRORS:
        return ""


def _fbp_persistence_text_name(scene, *, ensure=False):
    if scene is None:
        return _FBP_PERSISTENCE_BASELINE_TEXT
    try:
        stored = str(scene.get(_FBP_PERSISTENCE_TEXT_KEY, "") or "")
    except FBP_DATA_ERRORS:
        stored = ""
    if stored:
        return stored
    scene_id = _fbp_persistence_scene_id(scene, ensure=ensure)
    name = (
        f"{_FBP_PERSISTENCE_BASELINE_TEXT}_{scene_id[:12]}"
        if scene_id else _FBP_PERSISTENCE_BASELINE_TEXT
    )
    if ensure:
        try:
            scene[_FBP_PERSISTENCE_TEXT_KEY] = name
        except FBP_DATA_ERRORS:
            pass
    return name

def _fbp_persistence_rig_id(rig):
    try:
        return str(rig.get(_FBP_PERSISTENCE_RIG_ID_KEY, "") or "")
    except FBP_DATA_ERRORS:
        return ""


def _fbp_prepare_persistence_ids(rigs):
    """Assign unique persistent IDs only during an explicit baseline capture."""
    seen = set()
    repaired = 0
    for rig in rigs:
        current = _fbp_persistence_rig_id(rig)
        if not current or current in seen:
            current = uuid.uuid4().hex
            try:
                rig[_FBP_PERSISTENCE_RIG_ID_KEY] = current
                repaired += 1
            except FBP_DATA_ERRORS:
                current = f"UNASSIGNED:{getattr(rig, 'name', '<rig>')}"
        seen.add(current)
    return repaired


def _fbp_persistence_fcurve_contract(curve):
    keyframes = []
    for point in tuple(getattr(curve, "keyframe_points", ()) or ()):
        try:
            keyframes.append(
                {
                    "co": tuple(round(float(value), 7) for value in point.co),
                    "interpolation": str(getattr(point, "interpolation", "") or ""),
                    "easing": str(getattr(point, "easing", "") or ""),
                    "handle_left": tuple(
                        round(float(value), 7) for value in point.handle_left
                    ),
                    "handle_right": tuple(
                        round(float(value), 7) for value in point.handle_right
                    ),
                }
            )
        except FBP_DATA_ERRORS:
            keyframes.append({"unavailable": True})
    driver = getattr(curve, "driver", None)
    driver_contract = None
    if driver is not None:
        variables = []
        for variable in tuple(getattr(driver, "variables", ()) or ()):
            targets = []
            for target in tuple(getattr(variable, "targets", ()) or ()):
                targets.append(
                    {
                        "id": str(getattr(getattr(target, "id", None), "name", "") or ""),
                        "data_path": str(getattr(target, "data_path", "") or ""),
                        "bone_target": str(getattr(target, "bone_target", "") or ""),
                        "transform_type": str(getattr(target, "transform_type", "") or ""),
                        "transform_space": str(getattr(target, "transform_space", "") or ""),
                    }
                )
            variables.append(
                {
                    "name": str(getattr(variable, "name", "") or ""),
                    "type": str(getattr(variable, "type", "") or ""),
                    "targets": targets,
                }
            )
        driver_contract = {
            "type": str(getattr(driver, "type", "") or ""),
            "expression": str(getattr(driver, "expression", "") or ""),
            "use_self": bool(getattr(driver, "use_self", False)),
            "variables": variables,
        }
    return {
        "data_path": str(getattr(curve, "data_path", "") or ""),
        "array_index": int(getattr(curve, "array_index", 0) or 0),
        "extrapolation": str(getattr(curve, "extrapolation", "") or ""),
        "mute": bool(getattr(curve, "mute", False)),
        "keyframes": keyframes,
        "driver": driver_contract,
    }


def _fbp_persistence_animation_contract(owner):
    animation_data = getattr(owner, "animation_data", None) if owner is not None else None
    if animation_data is None:
        return None
    action = getattr(animation_data, "action", None)
    action_curves = []
    try:
        action_curves = [
            _fbp_persistence_fcurve_contract(curve)
            for curve in tuple(getattr(action, "fcurves", ()) or ())
        ] if action is not None else []
    except FBP_DATA_ERRORS:
        action_curves = []
    drivers = []
    try:
        drivers = [
            _fbp_persistence_fcurve_contract(curve)
            for curve in tuple(getattr(animation_data, "drivers", ()) or ())
        ]
    except FBP_DATA_ERRORS:
        drivers = []
    nla_tracks = []
    for track in tuple(getattr(animation_data, "nla_tracks", ()) or ()):
        strips = []
        for strip in tuple(getattr(track, "strips", ()) or ()):
            strips.append(
                {
                    "name": str(getattr(strip, "name", "") or ""),
                    "type": str(getattr(strip, "type", "") or ""),
                    "action": str(getattr(getattr(strip, "action", None), "name", "") or ""),
                    "frame_start": round(float(getattr(strip, "frame_start", 0.0) or 0.0), 7),
                    "frame_end": round(float(getattr(strip, "frame_end", 0.0) or 0.0), 7),
                    "action_frame_start": round(float(getattr(strip, "action_frame_start", 0.0) or 0.0), 7),
                    "action_frame_end": round(float(getattr(strip, "action_frame_end", 0.0) or 0.0), 7),
                    "scale": round(float(getattr(strip, "scale", 1.0) or 1.0), 7),
                    "repeat": round(float(getattr(strip, "repeat", 1.0) or 1.0), 7),
                    "blend_type": str(getattr(strip, "blend_type", "") or ""),
                    "extrapolation": str(getattr(strip, "extrapolation", "") or ""),
                    "mute": bool(getattr(strip, "mute", False)),
                }
            )
        nla_tracks.append(
            {
                "name": str(getattr(track, "name", "") or ""),
                "mute": bool(getattr(track, "mute", False)),
                "solo": bool(getattr(track, "is_solo", False)),
                "strips": strips,
            }
        )
    return {
        "action": str(getattr(action, "name", "") or ""),
        "action_curves": action_curves,
        "drivers": drivers,
        "nla_tracks": nla_tracks,
        "use_nla": bool(getattr(animation_data, "use_nla", False)),
    }


def _fbp_persistence_constraints(owner):
    result = []
    for constraint in tuple(getattr(owner, "constraints", ()) or ()) if owner is not None else ():
        try:
            result.append(
                {
                    "name": str(getattr(constraint, "name", "") or ""),
                    "type": str(getattr(constraint, "type", "") or ""),
                    "mute": bool(getattr(constraint, "mute", False)),
                    "influence": round(float(getattr(constraint, "influence", 1.0) or 0.0), 7),
                    "target": str(getattr(getattr(constraint, "target", None), "name", "") or ""),
                    "subtarget": str(getattr(constraint, "subtarget", "") or ""),
                }
            )
        except FBP_DATA_ERRORS:
            result.append({"unavailable": True})
    return result

def _fbp_persistence_frame_contract(rig):
    result = []
    try:
        rows = tuple(getattr(rig, "fbp_images", ()) or ())
    except FBP_DATA_ERRORS:
        rows = ()
    for item in rows:
        try:
            result.append(
                {
                    "name": str(getattr(item, "name", "") or ""),
                    "duration": int(getattr(item, "duration", 1) or 1),
                    "empty": bool(getattr(item, "is_empty", False)),
                    "filepath": str(getattr(item, "filepath", "") or ""),
                    "image": str(getattr(getattr(item, "image", None), "name", "") or ""),
                    "image_name": str(getattr(item, "image_name", "") or ""),
                    "stable_id": str(getattr(item, "stable_id", "") or ""),
                    "procedural_kind": str(getattr(item, "procedural_kind", "AUTO") or "AUTO"),
                    "color_a": _fbp_persistence_json_value(
                        getattr(item, "preview_color_a", ())
                    ),
                    "color_b": _fbp_persistence_json_value(
                        getattr(item, "preview_color_b", ())
                    ),
                }
            )
        except FBP_DATA_ERRORS:
            result.append({"unavailable": True})
    return result


def _fbp_persistence_shape_masks(rig):
    masks = []
    for shape in sorted(FBP_OBJECT_MASK_SHAPES):
        helper = None
        try:
            helper = getattr(rig, object_mask_pointer_property(shape), None)
        except FBP_DATA_ERRORS:
            helper = None
        if helper is None:
            continue
        contract = object_mask_contract(helper) or {}
        mesh = getattr(helper, "data", None)
        image_name = ""
        try:
            image_name = str(helper.get(FBP_OBJECT_MASK_IMAGE_NAME_KEY, "") or "")
        except FBP_DATA_ERRORS:
            pass
        masks.append(
            {
                "shape": shape,
                "helper": str(getattr(helper, "name", "") or ""),
                "parent": str(getattr(getattr(helper, "parent", None), "name", "") or ""),
                "contract": _fbp_persistence_json_value(contract),
                "transform": _fbp_persistence_transform(helper),
                "geometry": _fbp_persistence_point_hash(
                    getattr(mesh, "vertices", ()) if mesh is not None else (), "co"
                ),
                "image": image_name,
            }
        )
    return masks


def _fbp_persistence_lattice(rig, plane):
    report = fbp_lattice_contract_report(rig, repair=False)
    if not bool(report.get("active", False)):
        return {"active": False}
    helper = None
    try:
        helper = getattr(rig, "fbp_lattice_object", None)
    except FBP_DATA_ERRORS:
        helper = None
    data = getattr(helper, "data", None) if helper is not None else None
    dimensions = None
    interpolation = None
    if data is not None:
        try:
            dimensions = (
                int(getattr(data, "points_u", 0) or 0),
                int(getattr(data, "points_v", 0) or 0),
                int(getattr(data, "points_w", 0) or 0),
            )
            interpolation = (
                str(getattr(data, "interpolation_type_u", "") or ""),
                str(getattr(data, "interpolation_type_v", "") or ""),
                str(getattr(data, "interpolation_type_w", "") or ""),
            )
        except FBP_DATA_ERRORS:
            pass
    modifier_names = []
    try:
        modifier_names = [
            {"name": str(modifier.name), "type": str(modifier.type)}
            for modifier in tuple(getattr(plane, "modifiers", ()) or ())
            if str(getattr(modifier, "type", "") or "") in {"LATTICE", "SUBSURF"}
        ]
    except FBP_DATA_ERRORS:
        modifier_names = []
    return {
        "active": True,
        "valid": bool(report.get("valid", False)),
        "helper": str(getattr(helper, "name", "") or ""),
        "parent": str(getattr(getattr(helper, "parent", None), "name", "") or ""),
        "transform": _fbp_persistence_transform(helper),
        "dimensions": dimensions,
        "interpolation": interpolation,
        "points": _fbp_persistence_point_hash(
            getattr(data, "points", ()) if data is not None else (),
            "co_deform", "co",
        ),
        "modifiers": modifier_names,
    }


def _fbp_persistence_relation(rig, property_name):
    try:
        source = getattr(rig, property_name, None)
    except FBP_DATA_ERRORS:
        source = None
    if source is None:
        return None
    return {
        "id": _fbp_persistence_rig_id(source),
        "name": str(getattr(source, "name", "") or ""),
    }


def _fbp_persistence_rig_contract(rig):
    plane = None
    try:
        plane = getattr(rig, "fbp_plane_target", None)
    except FBP_DATA_ERRORS:
        plane = None

    properties = {}
    for property_name in _FBP_PERSISTENCE_LAYER_PROPERTIES:
        try:
            properties[property_name] = _fbp_persistence_json_value(
                getattr(rig, property_name)
            )
        except FBP_DATA_ERRORS:
            properties[property_name] = None

    effects = []
    for effect_id in tuple(fbp_effect_ids_for_rig(rig)):
        try:
            state = fbp_capture_effect_state_snapshot(rig, effect_id)
        except FBP_DATA_ERRORS:
            state = {"effect_id": effect_id, "unavailable": True}
        state = _fbp_persistence_json_value(state)
        state["instance_id"] = str(
            fbp_effect_instance_id_for_rig(rig, effect_id, ensure=False) or ""
        )
        state["raw_mask_target"] = str(
            fbp_effect_mask_raw_target(rig, effect_id) or "LAYER"
        )
        effects.append(state)

    try:
        imported_mask = str(getattr(rig, "fbp_imported_mask_path", "") or "")
    except FBP_DATA_ERRORS:
        imported_mask = ""

    return {
        "id": _fbp_persistence_rig_id(rig),
        "name": str(getattr(rig, "name", "") or ""),
        "backend": str(fbp_layer_backend_type(rig) or ""),
        "transform": _fbp_persistence_transform(rig),
        "animation": _fbp_persistence_animation_contract(rig),
        "constraints": _fbp_persistence_constraints(rig),
        "properties": properties,
        "frames": _fbp_persistence_frame_contract(rig),
        "plane": {
            "name": str(getattr(plane, "name", "") or ""),
            "type": str(getattr(plane, "type", "") or ""),
            "parent": str(getattr(getattr(plane, "parent", None), "name", "") or ""),
            "transform": _fbp_persistence_transform(plane),
            "animation": _fbp_persistence_animation_contract(plane),
            "constraints": _fbp_persistence_constraints(plane),
            "hide_render": bool(getattr(plane, "hide_render", False)) if plane else None,
        },
        "effects": effects,
        "relations": {
            "clipping": _fbp_persistence_relation(rig, "fbp_clipping_mask_source"),
            "alpha_matte": _fbp_persistence_relation(rig, "fbp_alpha_matte_source"),
            "luma_matte": _fbp_persistence_relation(rig, "fbp_luma_matte_source"),
            "imported_mask": imported_mask,
        },
        "shape_masks": _fbp_persistence_shape_masks(rig),
        "lattice": _fbp_persistence_lattice(rig, plane),
    }


def _fbp_build_persistence_contract(scene, *, prepare_ids=False):
    rigs = [obj for obj in scene.objects if is_fbp_layer_object(obj)]
    rigs.sort(key=lambda item: str(getattr(item, "name", "") or ""))
    assigned_ids = _fbp_prepare_persistence_ids(rigs) if prepare_ids else 0
    # Persistent IDs keep the comparison stable when a layer is renamed; a
    # rename is then reported on that exact layer instead of shifting every
    # subsequent list index in the diagnostic diff.
    rigs.sort(
        key=lambda item: (
            _fbp_persistence_rig_id(item),
            str(getattr(item, "name", "") or ""),
        )
    )
    contracts = [_fbp_persistence_rig_contract(rig) for rig in rigs]
    duplicate_ids = {}
    for item in contracts:
        duplicate_ids.setdefault(str(item.get("id", "") or ""), []).append(item.get("name", ""))
    duplicate_ids = {
        key: names for key, names in duplicate_ids.items()
        if not key or len(names) > 1
    }
    camera = getattr(scene, "camera", None)
    payload = {
        "schema": _FBP_PERSISTENCE_SCHEMA,
        "scene": str(getattr(scene, "name", "") or ""),
        "scene_contract": {
            "frame_start": int(getattr(scene, "frame_start", 1) or 1),
            "frame_end": int(getattr(scene, "frame_end", 250) or 250),
            "frame_current": int(getattr(scene, "frame_current", 1) or 1),
            "fps": int(getattr(getattr(scene, "render", None), "fps", 24) or 24),
            "resolution_x": int(getattr(getattr(scene, "render", None), "resolution_x", 0) or 0),
            "resolution_y": int(getattr(getattr(scene, "render", None), "resolution_y", 0) or 0),
            "camera": str(getattr(camera, "name", "") or ""),
        },
        "rigs": contracts,
    }
    return payload, assigned_ids, duplicate_ids


def _fbp_persistence_digest(contract):
    encoded = json.dumps(
        contract, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf8")
    return hashlib.sha256(encoded).hexdigest()


def _fbp_persistence_diff(expected, current, path="contract", output=None, limit=250):
    if output is None:
        output = []
    if len(output) >= limit:
        return output
    if isinstance(expected, (list, tuple)) and isinstance(current, (list, tuple)):
        if len(expected) != len(current):
            output.append(f"{path}: length changed from {len(expected)} to {len(current)}")
        for index, (left, right) in enumerate(zip(expected, current)):
            _fbp_persistence_diff(left, right, f"{path}[{index}]", output, limit)
            if len(output) >= limit:
                return output
        return output
    if type(expected) is not type(current):
        output.append(f"{path}: type changed from {type(expected).__name__} to {type(current).__name__}")
        return output
    if isinstance(expected, dict):
        expected_keys = set(expected)
        current_keys = set(current)
        for key in sorted(expected_keys - current_keys):
            output.append(f"{path}.{key}: missing after reopen")
            if len(output) >= limit:
                return output
        for key in sorted(current_keys - expected_keys):
            output.append(f"{path}.{key}: appeared after reopen")
            if len(output) >= limit:
                return output
        for key in sorted(expected_keys & current_keys):
            _fbp_persistence_diff(
                expected[key], current[key], f"{path}.{key}", output, limit
            )
            if len(output) >= limit:
                return output
        return output
    if expected != current:
        output.append(f"{path}: {expected!r} -> {current!r}")
    return output


def _fbp_load_persistence_baseline(scene):
    text = bpy.data.texts.get(_fbp_persistence_text_name(scene, ensure=False))
    if text is None:
        return None, "Persistence baseline is missing"
    try:
        payload = json.loads(text.as_string())
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return None, f"Persistence baseline is unreadable: {exc}"
    if int(payload.get("schema", 0) or 0) != _FBP_PERSISTENCE_SCHEMA:
        return None, "Persistence baseline uses an unsupported schema"
    if not isinstance(payload.get("contract"), dict):
        return None, "Persistence baseline contains no scene contract"
    return payload, ""


class FBP_OT_RunPersistenceAudit(Operator):
    bl_idname = "fbp.run_persistence_audit"
    bl_label = "Persistence Audit"
    bl_description = "Capture or verify a semantic save-and-reopen baseline for layers, effects, masks, Lattice deformation and native frame data"

    action: bpy.props.EnumProperty(
        name="Action",
        description="Capture a baseline before saving, verify it after reopening the file, or clear the stored baseline",
        items=(
            ("CAPTURE", "Capture Baseline", "Store the current semantic project contract inside this .blend before saving"),
            ("VERIFY", "Verify Reopened File", "Compare the reopened file against its stored baseline"),
            ("CLEAR", "Clear Baseline", "Remove the stored persistence baseline and verification state"),
        ),
        default="VERIFY",
    )
    require_reopen: BoolProperty(
        name="Require Reopen",
        description="Fail verification until the .blend has passed through load_post or a new Blender session since capture",
        default=True,
    )

    def execute(self, context):
        scene = context.scene
        if self.action == "CLEAR":
            text = bpy.data.texts.get(
                _fbp_persistence_text_name(scene, ensure=False)
            )
            if text is not None:
                try:
                    bpy.data.texts.remove(text)
                except FBP_DATA_ERRORS:
                    pass
            for key in (
                _FBP_PERSISTENCE_STATUS_KEY,
                _FBP_PERSISTENCE_HASH_KEY,
                _FBP_PERSISTENCE_VERIFIED_AT_KEY,
                _FBP_PERSISTENCE_TEXT_KEY,
                _FBP_PERSISTENCE_SCENE_ID_KEY,
            ):
                try:
                    if key in scene:
                        del scene[key]
                except FBP_DATA_ERRORS:
                    pass
            self.report({'INFO'}, "Persistence baseline cleared")
            return {'FINISHED'}

        sync_layer_collection(context)
        if self.action == "CAPTURE":
            contract, assigned_ids, duplicate_ids = _fbp_build_persistence_contract(
                scene, prepare_ids=True
            )
            digest = _fbp_persistence_digest(contract)
            payload = {
                "schema": _FBP_PERSISTENCE_SCHEMA,
                "addon_version": FBP_VERSION_STRING,
                "captured_at": datetime.now().isoformat(timespec="seconds"),
                "session_token": _FBP_PERSISTENCE_SESSION_TOKEN,
                "load_generation": int(
                    scene.get(_FBP_PERSISTENCE_LOAD_GENERATION_KEY, 0) or 0
                ),
                "hash": digest,
                "contract": contract,
            }
            text_name = _fbp_persistence_text_name(scene, ensure=True)
            text = bpy.data.texts.get(text_name)
            if text is None:
                text = bpy.data.texts.new(text_name)
            try:
                text.use_fake_user = True
            except FBP_DATA_ERRORS:
                pass
            text.clear()
            text.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
            scene[_FBP_PERSISTENCE_STATUS_KEY] = "CAPTURED"
            scene[_FBP_PERSISTENCE_HASH_KEY] = digest
            lines = [
                "Frame By Plane — Persistence Baseline",
                "=====================================",
                f"Generated: {payload['captured_at']}",
                f"Scene: {scene.name}",
                f"Layers captured: {len(contract.get('rigs', ())) }",
                f"Persistent IDs assigned: {assigned_ids}",
                f"Hash: {digest}",
                "",
                "Next step",
                "---------",
                "1. Save this .blend.",
                "2. Reopen it in Blender.",
                "3. Run Verify Reopened File.",
            ]
            if duplicate_ids:
                lines.extend(("", "Warnings", "--------"))
                lines.extend(
                    f"- Duplicate or missing ID {key!r}: {', '.join(names)}"
                    for key, names in sorted(duplicate_ids.items())
                )
            write_diagnostic_report(
                scene,
                "FBP_Persistence_Audit",
                lines,
                summary=f"Persistence · baseline captured · {len(contract.get('rigs', ())) } layer(s)",
                status="INFO",
            )
            self.report({'INFO'}, "Persistence baseline captured; save and reopen the file")
            return {'FINISHED'}

        baseline, error = _fbp_load_persistence_baseline(scene)
        issues = []
        warnings = []
        if baseline is None:
            issues.append(error)
            contract = {}
            current_hash = ""
            differences = []
            reopened = False
            duplicate_ids = {}
        else:
            contract, _assigned_ids, duplicate_ids = _fbp_build_persistence_contract(
                scene, prepare_ids=False
            )
            current_hash = _fbp_persistence_digest(contract)
            differences = _fbp_persistence_diff(
                baseline.get("contract", {}), contract
            )
            issues.extend(differences)
            captured_generation = int(baseline.get("load_generation", 0) or 0)
            current_generation = int(
                scene.get(_FBP_PERSISTENCE_LOAD_GENERATION_KEY, 0) or 0
            )
            reopened = bool(
                str(baseline.get("session_token", "") or "")
                != _FBP_PERSISTENCE_SESSION_TOKEN
                or current_generation > captured_generation
            )
            if self.require_reopen and not reopened:
                issues.append(
                    "The baseline has not passed through a file reopen or a new Blender session"
                )
            if duplicate_ids:
                for key, names in sorted(duplicate_ids.items()):
                    issues.append(
                        f"Duplicate or missing persistence ID {key!r}: {', '.join(names)}"
                    )
            baseline_version = str(baseline.get("addon_version", "") or "")
            if baseline_version != FBP_VERSION_STRING:
                issues.append(
                    f"Baseline was captured with Frame By Plane {baseline_version or '<unknown>'}; recapture it with {FBP_VERSION_STRING}"
                )
            baseline_hash = str(baseline.get("hash", "") or "")
            if baseline_hash and baseline_hash != _fbp_persistence_digest(
                baseline.get("contract", {})
            ):
                issues.append("The stored baseline hash does not match its contract")

        scene[_FBP_PERSISTENCE_STATUS_KEY] = "PASS" if not issues else "FAIL"
        scene[_FBP_PERSISTENCE_HASH_KEY] = current_hash
        scene[_FBP_PERSISTENCE_VERIFIED_AT_KEY] = datetime.now().isoformat(
            timespec="seconds"
        )
        lines = [
            "Frame By Plane — Persistence Audit",
            "==================================",
            f"Generated: {datetime.now().isoformat(timespec='seconds')}",
            f"Scene: {scene.name}",
            f"Baseline add-on version: {baseline.get('addon_version', '<missing>') if baseline else '<missing>'}",
            f"Current add-on version: {FBP_VERSION_STRING}",
            f"Reopen confirmed: {'Yes' if reopened else 'No'}",
            f"Layers verified: {len(contract.get('rigs', ())) if contract else 0}",
            f"Current hash: {current_hash or '<unavailable>'}",
            "",
            "Structural issues",
            "-----------------",
        ]
        lines.extend(f"- {item}" for item in issues) if issues else lines.append("- None")
        if len(differences) >= 250:
            warnings.append("Difference report was limited to the first 250 changes")
        lines.extend(("", "Warnings", "--------"))
        lines.extend(f"- {item}" for item in warnings) if warnings else lines.append("- None")
        lines.extend(("", "Validation totals", "-----------------"))
        lines.append(f"Structural issues: {len(issues)}")
        lines.append(f"Warnings: {len(warnings)}")
        lines.extend(("", "Result", "------", "PASS" if not issues else "REVIEW REQUIRED"))
        summary = f"Persistence · {len(issues)} issue(s) · reopen {'confirmed' if reopened else 'not confirmed'}"
        write_diagnostic_report(
            scene,
            "FBP_Persistence_Audit",
            lines,
            summary=summary,
            status="PASS" if not issues else "WARNING",
        )
        self.report({'INFO'} if not issues else {'WARNING'}, summary)
        return {'FINISHED'}


__all__ = ("FBP_OT_RunPersistenceAudit",)
