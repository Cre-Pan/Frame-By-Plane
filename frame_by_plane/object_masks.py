"""Editable object-backed Shape Masks for Frame By Plane.

Each mask owns a lightweight editable wire cage plus eight flat side/corner
handles parented to the generated image plane. The cage transform drives
placement while its mesh is rasterized into an in-memory signed-distance image.
Shader nodes sample that image in cage-local space, so Edit Mode vertex changes
affect the real mask rather than only the viewport outline.

Runtime work is deliberately demand-driven:
- transforms require no Python updates;
- geometry is rasterized only when its local mesh signature changes;
- visibility checks iterate only registered helpers;
- depsgraph callbacks schedule safe timer work instead of mutating datablocks.
"""

from __future__ import annotations

from array import array
import math
import time
import uuid

import bpy
from mathutils import Euler, Matrix, Vector

try:
    import bmesh
except ImportError:  # Blender always provides bmesh; keep import-time resilience.
    bmesh = None

from .math_utils import point_inside_polygon_unchecked as _point_inside_polygon
from .runtime import (
    FBP_DATA_ERRORS,
    FBP_DATA_IO_ERRORS,
    fbp_render_mutation_blocked,
    fbp_runtime_get,
    fbp_depsgraph_quiet_for,
    fbp_set_rna_property_silent,
    fbp_undo_guard_active,
    fbp_warn,
    fbp_add_transform_driver_variable as _add_transform_driver_variable
)
from .transactions import FBPTransaction

FBP_OBJECT_MASK_SCHEMA_VERSION = 7
FBP_OBJECT_MASK_SHAPES = frozenset({"SQUARE", "CIRCLE", "TRIANGLE"})
FBP_OBJECT_MASK_RESOLUTION = 256
FBP_OBJECT_MASK_FALLBACK_RESOLUTION = 128

KEY_IS_HELPER = "fbp_is_object_mask_helper"
KEY_IS_HELPER_MESH = "fbp_is_object_mask_helper_mesh"
KEY_HELPER_NAME = "fbp_object_mask_helper_name"
KEY_SCHEMA = "fbp_object_mask_schema"
KEY_SHAPE = "fbp_object_mask_shape"
KEY_OWNER_NAME = "fbp_object_mask_owner_name"
KEY_OWNER_ID = "fbp_object_mask_owner_id"
KEY_OWNER_RIG_ID = "fbp_object_mask_rig_id"
KEY_BOUNDS = "fbp_object_mask_last_bounds"
KEY_IMAGE_NAME = "fbp_object_mask_image_name"
KEY_IMAGE_BOUNDS = "fbp_object_mask_image_bounds"
KEY_GEOMETRY_SIGNATURE = "fbp_object_mask_geometry_signature"
KEY_IS_MASK_IMAGE = "fbp_is_object_mask_image"
KEY_IMAGE_RETIRE_SESSION = "fbp_object_mask_retire_session"
KEY_IS_BOUNDS_HANDLE = "fbp_is_object_mask_bounds_handle"
KEY_HANDLE_ROLE = "fbp_object_mask_handle_role"
KEY_HANDLE_HELPER_NAME = "fbp_object_mask_handle_helper"
KEY_HANDLE_SIGNATURE = "fbp_object_mask_handle_signature"
KEY_EXTERNAL_DRIVER_SIGNATURE = "fbp_shape_mask_external_driver_signature"

_POINTER_PROPERTIES = {
    "SQUARE": "fbp_square_mask_object",
    "CIRCLE": "fbp_circle_mask_object",
    "TRIANGLE": "fbp_triangle_mask_object",
}
_FOLLOW_PROPERTIES = {
    "SQUARE": "fbp_square_mask_follow_bounds",
    "CIRCLE": "fbp_circle_mask_follow_bounds",
    "TRIANGLE": "fbp_triangle_mask_follow_bounds",
}
_SHOW_PROPERTIES = {
    "SQUARE": "fbp_square_mask_show_helper",
    "CIRCLE": "fbp_circle_mask_show_helper",
    "TRIANGLE": "fbp_triangle_mask_show_helper",
}
_LOCK_PROPERTIES = {
    "SQUARE": "fbp_square_mask_lock_to_plane",
    "CIRCLE": "fbp_circle_mask_lock_to_plane",
    "TRIANGLE": "fbp_triangle_mask_lock_to_plane",
}
_EXTERNAL_NULL_PROPERTIES = {
    "SQUARE": "fbp_square_mask_external_null",
    "CIRCLE": "fbp_circle_mask_external_null",
    "TRIANGLE": "fbp_triangle_mask_external_null",
}
_EFFECT_IDS = {
    "SQUARE": "SQUARE_MASK",
    "CIRCLE": "CIRCLE_MASK",
    "TRIANGLE": "TRIANGLE_MASK",
}

# Runtime registries use RNA pointers/wrappers instead of names. Renaming a
# Shape Mask helper or its owner must not pause visibility, geometry refresh or
# cleanup until the next global discovery pass.
_HELPER_REGISTRY = {}
_HELPER_MESH_INDEX = {}
_HELPER_MESH_POINTERS = {}
_PENDING_GEOMETRY_HELPERS = {}
_OBJECT_MASK_IMAGE_RETIRED_AT = globals().get("_OBJECT_MASK_IMAGE_RETIRED_AT", {})
if not isinstance(_OBJECT_MASK_IMAGE_RETIRED_AT, dict):
    _OBJECT_MASK_IMAGE_RETIRED_AT = {}
_OBJECT_MASK_IMAGE_RETIRED_POINTERS = globals().get(
    "_OBJECT_MASK_IMAGE_RETIRED_POINTERS", {}
)
if not isinstance(_OBJECT_MASK_IMAGE_RETIRED_POINTERS, dict):
    _OBJECT_MASK_IMAGE_RETIRED_POINTERS = {}
_OBJECT_MASK_IMAGE_SESSION_ID = str(
    globals().get("_OBJECT_MASK_IMAGE_SESSION_ID", "") or uuid.uuid4().hex
)
_OBJECT_MASK_IMAGE_REUSE_DELAY = 4.0
_MASK_OWNER_INDEX = {}
_MASK_OWNER_DUPLICATE_IDS = set()
_MASK_OWNER_INDEX_OBJECT_COUNT = -1
_MASK_OWNER_INDEX_COMPLETE = False
_LAST_HELPER_DISCOVERY = 0.0
_NUMPY = globals().get("_NUMPY", None)
_NUMPY_CHECKED = bool(globals().get("_NUMPY_CHECKED", False))
_LAST_GEOMETRY_FALLBACK_CHECK = {}
_HELPER_RUNTIME_SIGNATURES = globals().get("_HELPER_RUNTIME_SIGNATURES", {})
if not isinstance(_HELPER_RUNTIME_SIGNATURES, dict):
    _HELPER_RUNTIME_SIGNATURES = {}
_LAST_HELPER_MAINTENANCE = globals().get("_LAST_HELPER_MAINTENANCE", 0.0)
_EMPTY_HELPER_DISCOVERY_SECONDS = 12.0
_ACTIVE_HELPER_DISCOVERY_SECONDS = 30.0
_HELPER_MAINTENANCE_SECONDS = 5.0
_ACTIVE_HELPER_TIMER_SECONDS = 0.16
_IDLE_HELPER_TIMER_SECONDS = 0.60
_OBJECT_MASK_TIMER_RUNNING = False


def _runtime_pointer(value):
    try:
        return int(value.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return id(value) if value is not None else 0


def _object_record(obj):
    """Return a primitive ``(pointer, name)`` record for a Blender Object."""
    if obj is None:
        return (0, "")
    try:
        return (_runtime_pointer(obj), str(getattr(obj, "name", "") or ""))
    except FBP_DATA_ERRORS:
        return (0, "")


def _record_pointer(record):
    try:
        return int(record[0]) if isinstance(record, (tuple, list)) else 0
    except (IndexError, TypeError, ValueError, OverflowError):
        return 0


def _resolve_object_record(record):
    """Resolve one live Object without retaining its RNA wrapper in caches."""
    pointer = _record_pointer(record)
    try:
        name = str(record[1] or "") if isinstance(record, (tuple, list)) else ""
    except (IndexError, TypeError, ValueError):
        name = ""
    try:
        candidate = bpy.data.objects.get(name) if name else None
        if candidate is not None and (not pointer or _runtime_pointer(candidate) == pointer):
            return candidate
        if pointer:
            for candidate in tuple(getattr(bpy.data, "objects", ()) or ()):
                if _runtime_pointer(candidate) == pointer:
                    return candidate
    except FBP_DATA_ERRORS:
        pass
    return None


def object_mask_runtime_service_required():
    """Return whether the Shape Mask runtime currently has live helpers."""
    return bool(_HELPER_REGISTRY)


def _ensure_object_mask_runtime_timer(*, first_interval=0.05):
    """Start the runtime service lazily when the first helper is registered."""
    if _OBJECT_MASK_TIMER_RUNNING:
        return True
    try:
        from .managed_timers import fbp_register_timer_once, fbp_timer_is_registered
        if fbp_timer_is_registered(object_mask_runtime_timer):
            return True
        return bool(
            fbp_register_timer_once(
                object_mask_runtime_timer,
                max(0.0, float(first_interval)),
                persistent=True,
            )
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not start Shape Mask runtime service", exc)
        return False


def _refresh_mask_owner_index(*, force=False, objects=None):
    """Rebuild the owner UUID table using primitive Object records only."""
    global _MASK_OWNER_INDEX_OBJECT_COUNT, _MASK_OWNER_INDEX_COMPLETE
    try:
        source = tuple(objects) if objects is not None else tuple(getattr(bpy.data, "objects", ()) or ())
        object_count = len(source)
    except FBP_DATA_ERRORS:
        return False
    if (
        not force
        and _MASK_OWNER_INDEX_COMPLETE
        and object_count == _MASK_OWNER_INDEX_OBJECT_COUNT
    ):
        return True
    owners = {}
    duplicates = set()
    for candidate in source:
        try:
            if not bool(getattr(candidate, "is_fbp_control", False)):
                continue
            owner_id = str(candidate.get(KEY_OWNER_RIG_ID, "") or "")
            if not owner_id:
                continue
            record = _object_record(candidate)
            previous = owners.get(owner_id)
            if previous is not None and _record_pointer(previous) != _record_pointer(record):
                duplicates.add(owner_id)
                continue
            owners[owner_id] = record
        except FBP_DATA_ERRORS:
            continue
    _MASK_OWNER_INDEX.clear()
    _MASK_OWNER_INDEX.update(owners)
    _MASK_OWNER_DUPLICATE_IDS.clear()
    _MASK_OWNER_DUPLICATE_IDS.update(duplicates)
    _MASK_OWNER_INDEX_OBJECT_COUNT = object_count
    _MASK_OWNER_INDEX_COMPLETE = True
    return True


def _register_helper_runtime(helper, owner=None):
    if not is_object_mask_helper(helper):
        return False
    pointer = _runtime_pointer(helper)
    if not pointer:
        return False
    was_empty = not _HELPER_REGISTRY
    helper_record = _object_record(helper)
    _HELPER_REGISTRY[pointer] = helper_record
    mesh = getattr(helper, "data", None)
    mesh_pointer = _runtime_pointer(mesh)
    previous_mesh_pointer = _HELPER_MESH_POINTERS.get(pointer, 0)
    if previous_mesh_pointer and previous_mesh_pointer != mesh_pointer:
        current = _HELPER_MESH_INDEX.get(previous_mesh_pointer)
        if _record_pointer(current) == pointer:
            _HELPER_MESH_INDEX.pop(previous_mesh_pointer, None)
    if mesh_pointer:
        _HELPER_MESH_POINTERS[pointer] = mesh_pointer
        _HELPER_MESH_INDEX[mesh_pointer] = helper_record
    if owner is not None:
        try:
            owner_id = str(owner.get(KEY_OWNER_RIG_ID, "") or "")
        except FBP_DATA_ERRORS:
            owner_id = ""
        if owner_id:
            _MASK_OWNER_INDEX[owner_id] = _object_record(owner)
    if was_empty and not _OBJECT_MASK_TIMER_RUNNING:
        _ensure_object_mask_runtime_timer()
    return True


def _unregister_helper_runtime(helper=None, *, pointer=0):
    pointer = int(pointer or _runtime_pointer(helper) or 0)
    mesh_pointer = _HELPER_MESH_POINTERS.pop(pointer, 0)
    if not mesh_pointer and helper is not None:
        try:
            mesh_pointer = _runtime_pointer(getattr(helper, "data", None))
        except FBP_DATA_ERRORS:
            mesh_pointer = 0
    _HELPER_REGISTRY.pop(pointer, None)
    _PENDING_GEOMETRY_HELPERS.pop(pointer, None)
    _LAST_GEOMETRY_FALLBACK_CHECK.pop(pointer, None)
    _HELPER_RUNTIME_SIGNATURES.pop(pointer, None)
    if mesh_pointer and _record_pointer(_HELPER_MESH_INDEX.get(mesh_pointer)) == pointer:
        _HELPER_MESH_INDEX.pop(mesh_pointer, None)


def normalize_object_mask_shape(shape):
    value = str(shape or "SQUARE").strip().upper()
    return value if value in FBP_OBJECT_MASK_SHAPES else "SQUARE"


def object_mask_label(shape):
    return {
        "SQUARE": "Square",
        "CIRCLE": "Circle",
        "TRIANGLE": "Triangle",
    }[normalize_object_mask_shape(shape)]


def object_mask_effect_id(shape):
    return _EFFECT_IDS[normalize_object_mask_shape(shape)]


def object_mask_pointer_property(shape):
    return _POINTER_PROPERTIES[normalize_object_mask_shape(shape)]


def object_mask_follow_property(shape):
    return _FOLLOW_PROPERTIES[normalize_object_mask_shape(shape)]


def object_mask_show_property(shape):
    return _SHOW_PROPERTIES[normalize_object_mask_shape(shape)]


def object_mask_lock_property(shape):
    return _LOCK_PROPERTIES[normalize_object_mask_shape(shape)]


def object_mask_external_null_property(shape):
    return _EXTERNAL_NULL_PROPERTIES[normalize_object_mask_shape(shape)]


def ensure_object_mask_owner_id(owner):
    """Return a unique persistent UUID stored on the owning FBP rig.

    The uniqueness check uses the runtime owner index. A full ``bpy.data`` scan
    now happens only when the object structure changes, not from every helper
    lookup, panel draw or visibility tick.
    """
    if not owner:
        return ""
    try:
        _refresh_mask_owner_index()
        owner_id = str(owner.get(KEY_OWNER_RIG_ID, "") or "")
        if owner_id:
            indexed = _resolve_object_record(_MASK_OWNER_INDEX.get(owner_id))
            conflict = bool(owner_id in _MASK_OWNER_DUPLICATE_IDS)
            if indexed is not None and _runtime_pointer(indexed) != _runtime_pointer(owner):
                conflict = True
            if conflict:
                owner_id = ""
        if not owner_id:
            owner_id = uuid.uuid4().hex
            while owner_id in _MASK_OWNER_INDEX:
                owner_id = uuid.uuid4().hex
            owner[KEY_OWNER_RIG_ID] = owner_id
        _MASK_OWNER_INDEX[owner_id] = _object_record(owner)
        _MASK_OWNER_DUPLICATE_IDS.discard(owner_id)
        return owner_id
    except FBP_DATA_ERRORS:
        return ""


def is_object_mask_helper(obj):
    if not obj:
        return False
    try:
        return bool(obj.get(KEY_IS_HELPER, False))
    except FBP_DATA_ERRORS:
        return False


def is_object_mask_bounds_handle(obj):
    try:
        return bool(obj and obj.get(KEY_IS_BOUNDS_HANDLE, False))
    except FBP_DATA_ERRORS:
        return False


def is_object_mask_controller(obj):
    return is_object_mask_helper(obj) or is_object_mask_bounds_handle(obj)


def object_mask_controller_shape(obj):
    if not is_object_mask_controller(obj):
        return ""
    try:
        return normalize_object_mask_shape(obj.get(KEY_SHAPE, "SQUARE"))
    except FBP_DATA_ERRORS:
        return ""


def find_object_mask_controller_owner(obj):
    """Resolve a mask cage or one of its bounds handles to the owning rig."""
    if is_object_mask_helper(obj):
        return find_object_mask_owner(obj)
    if not is_object_mask_bounds_handle(obj):
        return None
    try:
        plane = getattr(obj, "parent", None)
        owner = getattr(plane, "parent", None) if plane else None
        if owner and bool(getattr(owner, "is_fbp_control", False)):
            return owner
        owner_id = str(obj.get(KEY_OWNER_ID, "") or "")
        _refresh_mask_owner_index()
        owner = _resolve_object_record(_MASK_OWNER_INDEX.get(owner_id)) if owner_id else None
        return owner if owner and bool(getattr(owner, "is_fbp_control", False)) else None
    except FBP_DATA_ERRORS:
        return None


def find_object_mask_controller_helper(obj):
    if is_object_mask_helper(obj):
        return obj
    owner = find_object_mask_controller_owner(obj)
    shape = object_mask_controller_shape(obj)
    return find_object_mask_helper(owner, shape) if owner and shape else None


def _set_idprop_if_changed(data, key, value):
    """Write an IDProperty only when its stored value is actually different."""
    if data is None:
        return False
    try:
        if data.get(key, None) == value:
            return False
        data[key] = value
        return True
    except FBP_DATA_ERRORS:
        return False


def tag_object_mask_helper(obj, owner, shape):
    if not obj or not owner:
        return False
    owner_id = ensure_object_mask_owner_id(owner)
    if not owner_id:
        return False
    shape = normalize_object_mask_shape(shape)
    changed = False
    try:
        changed = _set_idprop_if_changed(obj, KEY_IS_HELPER, True) or changed
        changed = _set_idprop_if_changed(
            obj, KEY_SCHEMA, FBP_OBJECT_MASK_SCHEMA_VERSION
        ) or changed
        changed = _set_idprop_if_changed(obj, KEY_SHAPE, shape) or changed
        changed = _set_idprop_if_changed(
            obj, KEY_OWNER_NAME, str(getattr(owner, "name", "") or "")
        ) or changed
        changed = _set_idprop_if_changed(obj, KEY_OWNER_ID, owner_id) or changed
        mesh = getattr(obj, "data", None)
        if mesh is not None:
            changed = _set_idprop_if_changed(mesh, KEY_IS_HELPER_MESH, True) or changed
            changed = _set_idprop_if_changed(mesh, KEY_HELPER_NAME, obj.name) or changed
            changed = _set_idprop_if_changed(
                mesh, KEY_SCHEMA, FBP_OBJECT_MASK_SCHEMA_VERSION
            ) or changed
        _register_helper_runtime(obj, owner)
        return changed
    except FBP_DATA_ERRORS:
        return False


def clear_object_mask_helper_tag(obj):
    if not obj:
        return False
    changed = False
    _unregister_helper_runtime(obj)
    for owner in (obj, getattr(obj, "data", None)):
        if owner is None:
            continue
        for key in (
            KEY_IS_HELPER, KEY_IS_HELPER_MESH, KEY_HELPER_NAME, KEY_SCHEMA,
            KEY_SHAPE, KEY_OWNER_NAME, KEY_OWNER_ID, KEY_BOUNDS,
            KEY_IMAGE_NAME, KEY_IMAGE_BOUNDS, KEY_GEOMETRY_SIGNATURE,
        ):
            try:
                if key in owner:
                    del owner[key]
                    changed = True
            except (AttributeError, KeyError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
    return changed


def object_mask_contract(obj):
    if not is_object_mask_helper(obj):
        return None
    try:
        return {
            "schema": int(obj.get(KEY_SCHEMA, 0) or 0),
            "shape": normalize_object_mask_shape(obj.get(KEY_SHAPE, "SQUARE")),
            "owner_name": str(obj.get(KEY_OWNER_NAME, "") or ""),
            "owner_id": str(obj.get(KEY_OWNER_ID, "") or ""),
        }
    except FBP_DATA_ERRORS:
        return None


def _plane_bounds(owner):
    plane = getattr(owner, "fbp_plane_target", None) if owner else None
    if not plane:
        return None, (-1.0, 1.0, -1.0, 1.0)
    points = []
    try:
        points = [
            (float(point[0]), float(point[1]))
            for point in tuple(getattr(plane, "bound_box", ()) or ())
        ]
    except FBP_DATA_ERRORS:
        points = []
    if not points:
        try:
            points = [
                (float(vertex.co.x), float(vertex.co.y))
                for vertex in getattr(getattr(plane, "data", None), "vertices", ())
            ]
        except FBP_DATA_ERRORS:
            points = []
    if not points:
        return plane, (-1.0, 1.0, -1.0, 1.0)
    xs = [item[0] for item in points]
    ys = [item[1] for item in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    if abs(max_x - min_x) < 1.0e-8:
        min_x, max_x = -1.0, 1.0
    if abs(max_y - min_y) < 1.0e-8:
        min_y, max_y = -1.0, 1.0
    return plane, (min_x, max_x, min_y, max_y)


def _helper_matches_owner(helper, owner, shape):
    if not is_object_mask_helper(helper) or not owner:
        return False
    contract = object_mask_contract(helper) or {}
    return bool(
        contract.get("shape") == normalize_object_mask_shape(shape)
        and contract.get("owner_id") == ensure_object_mask_owner_id(owner)
    )


def _helper_is_direct_plane_child(helper, owner, shape):
    """Recognize a duplicated helper before its copied owner UUID is repaired."""
    if not is_object_mask_helper(helper) or not owner:
        return False
    plane = getattr(owner, "fbp_plane_target", None)
    if plane is None:
        return False
    contract = object_mask_contract(helper) or {}
    try:
        return bool(
            getattr(helper, "parent", None) is plane
            and contract.get("shape") == normalize_object_mask_shape(shape)
        )
    except FBP_DATA_ERRORS:
        return False


def _adopt_direct_object_mask_helper(owner, helper, shape, prop_name):
    """Retag a copied helper for its duplicated rig without creating a second cage."""
    if not _helper_is_direct_plane_child(helper, owner, shape):
        return None
    tag_object_mask_helper(helper, owner, shape)
    fbp_set_rna_property_silent(owner, prop_name, helper)
    _register_helper_runtime(helper, owner)
    # A duplicated helper may still reference the source rig's private SDF
    # image. Reconcile image ownership immediately so editing the copy cannot
    # alter the original mask, then refresh any active shader binding.
    try:
        ensure_object_mask_image(helper, force=True)
        from .geometry_nodes import fbp_refresh_object_mask_binding
        fbp_refresh_object_mask_binding(owner, object_mask_effect_id(shape))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return helper


def find_object_mask_owner(helper):
    contract = object_mask_contract(helper) or {}
    owner_id = str(contract.get("owner_id", "") or "")
    owner_name = str(contract.get("owner_name", "") or "")

    # Resolve through fresh name/index lookups rather than helper.parent.parent.
    # This avoids retaining stale RNA wrappers across Undo and file replacement.
    _refresh_mask_owner_index()
    candidate = bpy.data.objects.get(owner_name) if owner_name else None
    if candidate is None and owner_id and owner_id not in _MASK_OWNER_DUPLICATE_IDS:
        candidate = _resolve_object_record(_MASK_OWNER_INDEX.get(owner_id))
    try:
        if candidate and bool(getattr(candidate, "is_fbp_control", False)):
            candidate_id = str(candidate.get(KEY_OWNER_RIG_ID, "") or "")
            if not owner_id or candidate_id == owner_id:
                if owner_id:
                    _MASK_OWNER_INDEX[owner_id] = _object_record(candidate)
                return candidate
    except FBP_DATA_ERRORS:
        pass
    if not owner_id:
        return None
    # A rename or Undo can invalidate a name while preserving the UUID. Rebuild
    # once from current Main, then resolve from the fresh table without an O(n)
    # scan for every helper.
    _refresh_mask_owner_index(force=True)
    if owner_id in _MASK_OWNER_DUPLICATE_IDS:
        return None
    candidate = _resolve_object_record(_MASK_OWNER_INDEX.get(owner_id))
    try:
        if candidate and bool(getattr(candidate, "is_fbp_control", False)):
            return candidate
    except FBP_DATA_ERRORS:
        pass
    return None


def find_object_mask_helper(owner, shape):
    shape = normalize_object_mask_shape(shape)
    if not owner:
        return None
    prop_name = object_mask_pointer_property(shape)
    try:
        helper = getattr(owner, prop_name, None)
    except FBP_DATA_ERRORS:
        helper = None
    if _helper_matches_owner(helper, owner, shape):
        _register_helper_runtime(helper, owner)
        return helper

    plane = getattr(owner, "fbp_plane_target", None)
    try:
        candidates = tuple(getattr(plane, "children", ()) or ()) if plane else ()
    except FBP_DATA_ERRORS:
        candidates = ()

    # Prefer an already-valid helper. This preserves an explicitly repaired
    # contract when a stale copied cage also remains under the same plane.
    for candidate in candidates:
        if _helper_matches_owner(candidate, owner, shape):
            fbp_set_rna_property_silent(owner, prop_name, candidate)
            _register_helper_runtime(candidate, owner)
            return candidate

    # Blender hierarchy duplication copies custom properties before the new
    # rig receives a unique owner UUID. Adopt the helper that was duplicated
    # with the plane rather than generating a second Shape Mask cage.
    adopted = _adopt_direct_object_mask_helper(owner, helper, shape, prop_name)
    if adopted is not None:
        return adopted
    for candidate in candidates:
        adopted = _adopt_direct_object_mask_helper(
            owner, candidate, shape, prop_name
        )
        if adopted is not None:
            return adopted
    return None


def _shape_mesh(shape, name):
    shape = normalize_object_mask_shape(shape)
    mesh = bpy.data.meshes.new(name)
    if shape == "CIRCLE":
        count = 64
        vertices = [
            (math.cos((index / count) * math.tau), math.sin((index / count) * math.tau), 0.0)
            for index in range(count)
        ]
    elif shape == "TRIANGLE":
        vertices = [
            (0.0, 1.0, 0.0),
            (-0.8660254, -0.5, 0.0),
            (0.8660254, -0.5, 0.0),
        ]
    else:
        vertices = [
            (-1.0, -1.0, 0.0), (1.0, -1.0, 0.0),
            (1.0, 1.0, 0.0), (-1.0, 1.0, 0.0),
        ]
    count = len(vertices)
    edges = [(index, (index + 1) % count) for index in range(count)]
    # Shape Mask helpers are control cages, not renderable surfaces. Keeping
    # them edge-only prevents Blender from drawing an opaque/black edit face
    # over the image plane while preserving the exact polygon boundary used by
    # the signed-distance rasterizer.
    mesh.from_pydata(vertices, edges, [])
    mesh.update()
    return mesh


def _ensure_helper_wire_topology(helper):
    """Remove helper faces while preserving the editable boundary cage.

    Incomplete helpers can contain one polygon face. Blender displays that face
    in Edit Mode even when the object display type is Wire, making the helper
    appear black and hiding the plane underneath. This repair is safe for
    existing files because Shape Masks derive their silhouette from vertices
    and boundary edges, never from polygon faces.
    """
    if not is_object_mask_helper(helper):
        return False
    mesh = getattr(helper, "data", None)
    if mesh is None or getattr(helper, "type", "") != "MESH":
        return False
    changed = False
    try:
        editmode = bool(getattr(mesh, "is_editmode", False))
        if not editmode:
            schema_ready = bool(
                int(helper.get(KEY_SCHEMA, 0) or 0) == FBP_OBJECT_MASK_SCHEMA_VERSION
                and int(mesh.get(KEY_SCHEMA, 0) or 0) == FBP_OBJECT_MASK_SCHEMA_VERSION
                and len(getattr(mesh, "polygons", ())) == 0
                and str(getattr(helper, "display_type", "")) == "WIRE"
                and bool(getattr(helper, "show_in_front", False))
                and bool(getattr(helper, "hide_render", False))
            )
            if schema_ready:
                return False
        if bmesh is not None and editmode:
            bm = bmesh.from_edit_mesh(mesh)
            if bm.faces:
                bmesh.ops.delete(bm, geom=list(bm.faces), context='FACES_ONLY')
                bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=True)
                changed = True
        elif len(getattr(mesh, "polygons", ())) > 0 and bmesh is not None:
            bm = bmesh.new()
            try:
                bm.from_mesh(mesh)
                if bm.faces:
                    bmesh.ops.delete(bm, geom=list(bm.faces), context='FACES_ONLY')
                    bm.to_mesh(mesh)
                    mesh.update()
                    changed = True
            finally:
                bm.free()

        # Keep the helper readable but completely non-occluding in every
        # viewport shading mode. These flags are cheap to repair after user
        # edits, Undo or partial helper reconstruction.
        if str(getattr(helper, "display_type", "")) != "WIRE":
            helper.display_type = "WIRE"
            changed = True
        if not bool(getattr(helper, "show_in_front", False)):
            helper.show_in_front = True
            changed = True
        if hasattr(helper, "show_wire") and not bool(helper.show_wire):
            helper.show_wire = True
            changed = True
        if hasattr(helper, "show_all_edges") and not bool(helper.show_all_edges):
            helper.show_all_edges = True
            changed = True
        if not bool(getattr(helper, "hide_render", False)):
            helper.hide_render = True
            changed = True
        if int(helper.get(KEY_SCHEMA, 0) or 0) != FBP_OBJECT_MASK_SCHEMA_VERSION:
            helper[KEY_SCHEMA] = FBP_OBJECT_MASK_SCHEMA_VERSION
            changed = True
        if int(mesh.get(KEY_SCHEMA, 0) or 0) != FBP_OBJECT_MASK_SCHEMA_VERSION:
            mesh[KEY_SCHEMA] = FBP_OBJECT_MASK_SCHEMA_VERSION
            changed = True
    except FBP_DATA_ERRORS:
        return changed
    return changed

def _link_helper(helper, plane, context=None):
    collections = tuple(getattr(plane, "users_collection", ()) or ()) if plane else ()
    collection = collections[0] if collections else getattr(context, "collection", None)
    if collection is None:
        scene = getattr(context, "scene", None) or getattr(bpy.context, "scene", None)
        collection = getattr(scene, "collection", None)
    if collection:
        try:
            linked = collection.objects.get(helper.name) is helper
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            linked = any(existing is helper for existing in tuple(getattr(collection, "objects", ()) or ()))
        if not linked:
            collection.objects.link(helper)


def _object_mask_local_mesh_bounds(helper):
    mesh = getattr(helper, "data", None) if helper else None
    try:
        points = tuple((float(vertex.co.x), float(vertex.co.y)) for vertex in mesh.vertices)
    except FBP_DATA_ERRORS:
        points = ()
    if not points:
        return (-1.0, 1.0, -1.0, 1.0)
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    if max_x - min_x < 1.0e-6:
        min_x, max_x = -1.0, 1.0
    if max_y - min_y < 1.0e-6:
        min_y, max_y = -1.0, 1.0
    return min_x, max_x, min_y, max_y


def _object_mask_handle_size(owner, role):
    _plane, bounds = _plane_bounds(owner)
    width = max(abs(bounds[1] - bounds[0]), 1.0e-6)
    height = max(abs(bounds[3] - bounds[2]), 1.0e-6)
    size = max(0.035, min(0.32, min(width, height) * 0.075))
    return size * (0.62 if "_" in str(role or "") else 0.78)


def _object_mask_handle_signature(handle):
    try:
        return tuple(round(float(value), 7) for value in (
            handle.location.x, handle.location.y, handle.location.z,
            handle.rotation_euler.z,
        ))
    except FBP_DATA_ERRORS:
        return ()


def _store_object_mask_handle_signature(handle):
    signature = _object_mask_handle_signature(handle)
    try:
        if tuple(handle.get(KEY_HANDLE_SIGNATURE, ()) or ()) != signature:
            handle[KEY_HANDLE_SIGNATURE] = list(signature)
    except FBP_DATA_ERRORS:
        pass
    return signature


def object_mask_bounds_handles(helper):
    if not is_object_mask_helper(helper):
        return ()
    owner = find_object_mask_owner(helper)
    plane = getattr(owner, "fbp_plane_target", None) if owner else getattr(helper, "parent", None)
    shape = object_mask_controller_shape(helper)
    owner_id = ensure_object_mask_owner_id(owner) if owner else ""
    result = []
    for candidate in tuple(getattr(plane, "children", ()) or ()):
        try:
            if (
                is_object_mask_bounds_handle(candidate)
                and str(candidate.get(KEY_OWNER_ID, "") or "") == owner_id
                and object_mask_controller_shape(candidate) == shape
            ):
                result.append(candidate)
        except FBP_DATA_ERRORS:
            continue
    return tuple(result)


def _object_mask_values_equal(current, expected, tolerance=1.0e-7):
    if current is expected:
        return True
    try:
        if isinstance(current, (int, float, bool)) and isinstance(expected, (int, float, bool)):
            return abs(float(current) - float(expected)) <= tolerance
        if isinstance(current, str) or isinstance(expected, str):
            return current == expected
        current_values = tuple(current)
        expected_values = tuple(expected)
        if len(current_values) != len(expected_values):
            return False
        for left, right in zip(current_values, expected_values, strict=False):
            if isinstance(left, (int, float, bool)) and isinstance(right, (int, float, bool)):
                if abs(float(left) - float(right)) > tolerance:
                    return False
            elif left != right:
                return False
        return True
    except (ReferenceError, RuntimeError, TypeError, ValueError, OverflowError):
        try:
            return bool(current == expected)
        except (ReferenceError, RuntimeError, TypeError, ValueError):
            return False


def _set_object_mask_id_property(id_block, key, value):
    """Write an ID property only when its serialized value really changed."""
    if id_block is None:
        return False
    try:
        if _object_mask_values_equal(id_block.get(key, None), value):
            return False
        id_block[key] = value
        return True
    except FBP_DATA_ERRORS + (OverflowError,):
        return False


def _set_object_mask_rna_property(id_block, prop_name, value):
    """Set changed RNA with tolerant vector/color comparison."""
    if id_block is None:
        return False
    try:
        if _object_mask_values_equal(getattr(id_block, prop_name), value):
            return False
    except FBP_DATA_ERRORS + (OverflowError,):
        pass
    return bool(fbp_set_rna_property_silent(id_block, prop_name, value))


def _object_mask_bounds_handles_need_repair(helper, owner=None):
    """Read-only contract audit used by the low-frequency maintenance timer."""
    if not is_object_mask_helper(helper):
        return False
    from .viewport_handles import BOUNDS_HANDLE_ROLES

    owner = owner or find_object_mask_owner(helper)
    plane = getattr(owner, "fbp_plane_target", None) if owner else None
    if owner is None or plane is None:
        return False
    try:
        owner_id = str(owner.get(KEY_OWNER_RIG_ID, "") or "")
    except FBP_DATA_ERRORS:
        owner_id = ""
    if not owner_id:
        return True
    shape = object_mask_controller_shape(helper)
    handles = []
    try:
        for candidate in tuple(getattr(plane, "children", ()) or ()):
            if (
                is_object_mask_bounds_handle(candidate)
                and str(candidate.get(KEY_OWNER_ID, "") or "") == owner_id
                and object_mask_controller_shape(candidate) == shape
            ):
                handles.append(candidate)
    except FBP_DATA_ERRORS:
        return True
    if len(handles) != len(BOUNDS_HANDLE_ROLES):
        return True
    by_role = {}
    try:
        for handle in handles:
            role = str(handle.get(KEY_HANDLE_ROLE, "") or "").upper()
            if role in by_role or role not in BOUNDS_HANDLE_ROLES:
                return True
            by_role[role] = handle
    except FBP_DATA_ERRORS:
        return True
    if set(by_role) != set(BOUNDS_HANDLE_ROLES):
        return True

    material = bpy.data.materials.get("FBP Viewport Control Handle")
    target_color = (1.0, 0.55, 0.05, 1.0)
    target_material_color = (1.0, 0.55, 0.05, 0.9)
    if material is None or not _object_mask_values_equal(
        getattr(material, "diffuse_color", ()), target_material_color
    ):
        return True

    for role, handle in by_role.items():
        mesh = getattr(handle, "data", None)
        size = _object_mask_handle_size(owner, role)
        mesh_signature = f"shape_mask_bounds_v2:{role}:{size:.6f}"
        try:
            if getattr(handle, "parent", None) is not plane:
                return True
            expected_props = (
                (KEY_IS_BOUNDS_HANDLE, True),
                (KEY_SCHEMA, FBP_OBJECT_MASK_SCHEMA_VERSION),
                (KEY_HANDLE_ROLE, role),
                (KEY_HANDLE_HELPER_NAME, helper.name),
                (KEY_SHAPE, shape),
                (KEY_OWNER_ID, owner_id),
                (KEY_OWNER_NAME, owner.name),
            )
            if any(
                not _object_mask_values_equal(handle.get(key, None), value)
                for key, value in expected_props
            ):
                return True
            if mesh is None or str(mesh.get("fbp_object_mask_handle_mesh", "") or "") != mesh_signature:
                return True
            if not mesh.materials or mesh.materials[0] is not material:
                return True
            if not bool(getattr(handle, "show_in_front", False)):
                return True
            if not bool(getattr(handle, "hide_render", False)):
                return True
            if bool(getattr(handle, "hide_select", False)):
                return True
            if str(getattr(handle, "display_type", "")) != "SOLID":
                return True
            if not _object_mask_values_equal(getattr(handle, "color", ()), target_color):
                return True
            if not _object_mask_values_equal(getattr(handle, "lock_location", ()), (False, False, True)):
                return True
            if not _object_mask_values_equal(getattr(handle, "lock_rotation", ()), (True, True, True)):
                return True
            if not _object_mask_values_equal(getattr(handle, "lock_scale", ()), (True, True, True)):
                return True
        except FBP_DATA_ERRORS:
            return True
    return False


def _configure_object_mask_handle(handle, helper, owner, role):
    from .viewport_handles import bounds_handle_geometry, ensure_viewport_handle_material

    role = str(role or "").upper()
    shape = object_mask_controller_shape(helper)
    owner_id = ensure_object_mask_owner_id(owner)
    size = _object_mask_handle_size(owner, role)
    signature = f"shape_mask_bounds_v1:{role}:{size:.6f}"
    changed = False
    mesh = getattr(handle, "data", None)
    plane = getattr(owner, "fbp_plane_target", None)
    try:
        for key, value in (
            (KEY_IS_BOUNDS_HANDLE, True),
            (KEY_SCHEMA, FBP_OBJECT_MASK_SCHEMA_VERSION),
            (KEY_HANDLE_ROLE, role),
            (KEY_HANDLE_HELPER_NAME, helper.name),
            (KEY_SHAPE, shape),
            (KEY_OWNER_ID, owner_id),
            (KEY_OWNER_NAME, owner.name),
        ):
            changed = _set_object_mask_id_property(handle, key, value) or changed
        if plane is not None and getattr(handle, "parent", None) is not plane:
            handle.parent = plane
            handle.matrix_parent_inverse = Matrix.Identity(4)
            changed = True
        if mesh is not None and str(mesh.get("fbp_object_mask_handle_mesh", "") or "") != signature:
            verts, faces = bounds_handle_geometry(size, role)
            mesh.clear_geometry()
            mesh.from_pydata(verts, [], faces)
            mesh.update()
            mesh["fbp_object_mask_handle_mesh"] = signature
            changed = True
        material = ensure_viewport_handle_material()
        if mesh is not None and (not mesh.materials or mesh.materials[0] is not material):
            mesh.materials.clear()
            mesh.materials.append(material)
            changed = True
        for prop_name, value in (
            ("show_in_front", True),
            ("hide_render", True),
            ("hide_select", False),
            ("display_type", "SOLID"),
            ("color", (1.0, 0.55, 0.05, 1.0)),
            ("lock_location", (False, False, True)),
            ("lock_rotation", (True, True, True)),
            ("lock_scale", (True, True, True)),
        ):
            changed = _set_object_mask_rna_property(handle, prop_name, value) or changed
    except FBP_DATA_ERRORS:
        pass
    return changed


def ensure_object_mask_bounds_handles(helper, *, select=False, context=None):
    """Ensure eight Crop/Extend-style bounds handles around a Shape Mask cage."""
    if not is_object_mask_helper(helper):
        return ()
    from .viewport_handles import BOUNDS_HANDLE_ROLES

    owner = find_object_mask_owner(helper)
    plane = getattr(owner, "fbp_plane_target", None) if owner else None
    if owner is None or plane is None:
        return ()
    existing = {
        str(handle.get(KEY_HANDLE_ROLE, "") or "").upper(): handle
        for handle in object_mask_bounds_handles(helper)
    }
    handles = []
    for role in BOUNDS_HANDLE_ROLES:
        handle = existing.pop(role, None)
        if handle is None:
            mesh = bpy.data.meshes.new(f"FBP Shape Mask Handle Mesh • {role}")
            handle = bpy.data.objects.new(
                f"FBP {object_mask_label(object_mask_controller_shape(helper))} Mask {role.replace('_', ' ').title()} • {owner.name}",
                mesh,
            )
            _link_helper(handle, plane, context=context)
            handle.parent = plane
            handle.matrix_parent_inverse = Matrix.Identity(4)
        _configure_object_mask_handle(handle, helper, owner, role)
        handles.append(handle)
    for duplicate in existing.values():
        _remove_object_mask_bounds_handle(duplicate)
    sync_object_mask_bounds_handles(helper, handles=handles)
    if select:
        target = next((item for item in handles if item.get(KEY_HANDLE_ROLE) == "TOP_RIGHT"), handles[0])
        _select_object_mask_controller_preserving_layer(context, owner, target)
    return tuple(handles)


def _object_mask_handle_target(helper, role):
    min_x, max_x, min_y, max_y = _object_mask_local_mesh_bounds(helper)
    role = str(role or "").upper()
    x = min_x if "LEFT" in role else max_x if "RIGHT" in role else (min_x + max_x) * 0.5
    y = max_y if "TOP" in role else min_y if "BOTTOM" in role else (min_y + max_y) * 0.5
    # Read transform channels directly: immediately after object creation
    # Blender can expose a one-update-old matrix_local, which used to place all
    # handles at stale coordinates until the next depsgraph tick.
    angle = float(helper.rotation_euler.z)
    scaled_x = x * float(helper.scale.x)
    scaled_y = y * float(helper.scale.y)
    cos_angle, sin_angle = math.cos(angle), math.sin(angle)
    return (
        float(helper.location.x) + scaled_x * cos_angle - scaled_y * sin_angle,
        float(helper.location.y) + scaled_x * sin_angle + scaled_y * cos_angle,
    )


def sync_object_mask_bounds_handles(helper, *, handles=None):
    if not is_object_mask_helper(helper):
        return False
    handles = tuple(handles) if handles is not None else object_mask_bounds_handles(helper)
    changed = False
    try:
        angle = float(helper.rotation_euler.z)
    except FBP_DATA_ERRORS:
        angle = 0.0
    for handle in handles:
        try:
            role = str(handle.get(KEY_HANDLE_ROLE, "") or "").upper()
            x, y = _object_mask_handle_target(helper, role)
            if abs(float(handle.location.x) - x) > 1.0e-7:
                handle.location.x = x; changed = True
            if abs(float(handle.location.y) - y) > 1.0e-7:
                handle.location.y = y; changed = True
            if abs(float(handle.location.z) - 0.006) > 1.0e-7:
                handle.location.z = 0.006; changed = True
            if abs(float(handle.rotation_euler.z) - angle) > 1.0e-7:
                handle.rotation_euler.z = angle; changed = True
            _store_object_mask_handle_signature(handle)
        except FBP_DATA_ERRORS:
            continue
    return changed


def apply_object_mask_bounds_handles(handles):
    """Resize one Shape Mask from one or more moved bounds handles.

    When opposite handles are selected, Blender's S transform moves both around
    their median. Reading them as one transaction makes the sides converge or
    diverge symmetrically instead of letting two deferred single-handle updates
    overwrite each other.
    """
    handles = tuple(handle for handle in tuple(handles or ()) if is_object_mask_bounds_handle(handle))
    if not handles:
        return False
    helper = find_object_mask_controller_helper(handles[0])
    if helper is None:
        return False
    handles = tuple(
        handle for handle in handles
        if find_object_mask_controller_helper(handle) is helper
    )
    if not handles:
        return False
    try:
        angle = float(helper.rotation_euler.z)
        ux = Vector((math.cos(angle), math.sin(angle)))
        uy = Vector((-math.sin(angle), math.cos(angle)))
        center = Vector((float(helper.location.x), float(helper.location.y)))
        center_x, center_y = center.dot(ux), center.dot(uy)
        min_x, max_x, min_y, max_y = _object_mask_local_mesh_bounds(helper)
        scale_x = max(abs(float(helper.scale.x)), 1.0e-6)
        scale_y = max(abs(float(helper.scale.y)), 1.0e-6)
        left, right = center_x + min_x * scale_x, center_x + max_x * scale_x
        bottom, top = center_y + min_y * scale_y, center_y + max_y * scale_y
        edge_values = {"LEFT": [], "RIGHT": [], "BOTTOM": [], "TOP": []}
        for handle in handles:
            role = str(handle.get(KEY_HANDLE_ROLE, "") or "").upper()
            point = Vector((float(handle.location.x), float(handle.location.y)))
            point_x, point_y = point.dot(ux), point.dot(uy)
            if "LEFT" in role:
                edge_values["LEFT"].append(point_x)
            if "RIGHT" in role:
                edge_values["RIGHT"].append(point_x)
            if "BOTTOM" in role:
                edge_values["BOTTOM"].append(point_y)
            if "TOP" in role:
                edge_values["TOP"].append(point_y)
        def _average(values):
            return sum(values) / len(values)

        if edge_values["LEFT"]:
            left = _average(edge_values["LEFT"])
        if edge_values["RIGHT"]:
            right = _average(edge_values["RIGHT"])
        if edge_values["BOTTOM"]:
            bottom = _average(edge_values["BOTTOM"])
        if edge_values["TOP"]:
            top = _average(edge_values["TOP"])
        minimum = 1.0e-5
        if right - left < minimum:
            midpoint = (left + right) * 0.5
            left, right = midpoint - minimum * 0.5, midpoint + minimum * 0.5
        if top - bottom < minimum:
            midpoint = (bottom + top) * 0.5
            bottom, top = midpoint - minimum * 0.5, midpoint + minimum * 0.5
        new_scale_x = max((right - left) / max(max_x - min_x, minimum), minimum)
        new_scale_y = max((top - bottom) / max(max_y - min_y, minimum), minimum)
        new_center_x = left - min_x * new_scale_x
        new_center_y = bottom - min_y * new_scale_y
        new_center = ux * new_center_x + uy * new_center_y
        helper.location.x = float(new_center.x)
        helper.location.y = float(new_center.y)
        helper.scale.x = new_scale_x
        helper.scale.y = new_scale_y
        helper.update_tag(refresh={'OBJECT'})
        sync_object_mask_bounds_handles(helper)
        return True
    except FBP_DATA_ERRORS:
        return False


def apply_object_mask_bounds_handle(handle):
    return apply_object_mask_bounds_handles((handle,))


def schedule_object_mask_bounds_handle_update(handle):
    if not is_object_mask_bounds_handle(handle):
        return False
    helper = find_object_mask_controller_helper(handle)
    if helper is None:
        return False
    try:
        helper_name = str(helper.name)
        handle_record = _object_record(handle)
    except FBP_DATA_ERRORS:
        return False

    def _apply():
        current_helper = bpy.data.objects.get(helper_name)
        if not is_object_mask_helper(current_helper):
            return None
        try:
            selected = tuple(
                candidate for candidate in (getattr(bpy.context, "selected_objects", ()) or ())
                if is_object_mask_bounds_handle(candidate)
                and find_object_mask_controller_helper(candidate) is current_helper
            )
        except FBP_DATA_ERRORS:
            selected = ()
        if not selected:
            selected = tuple(
                candidate for candidate in object_mask_bounds_handles(current_helper)
                if _object_mask_handle_signature(candidate)
                != tuple(candidate.get(KEY_HANDLE_SIGNATURE, ()) or ())
            )
        if not selected:
            fallback = _resolve_object_record(handle_record)
            if (
                is_object_mask_bounds_handle(fallback)
                and find_object_mask_controller_helper(fallback) is current_helper
            ):
                selected = (fallback,)
        if selected:
            apply_object_mask_bounds_handles(selected)
        return None

    try:
        from .safe_tasks import schedule_once
        return bool(schedule_once(
            f"object_masks.bounds_handles.{helper_name}", _apply, first_interval=0.0
        ))
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        return apply_object_mask_bounds_handles((handle,))


def schedule_object_mask_helper_transform_update(helper):
    """Keep all bounds handles attached when the cage itself is moved/rotated/scaled."""
    if not is_object_mask_helper(helper):
        return False
    try:
        helper_name = str(helper.name)
    except FBP_DATA_ERRORS:
        return False

    def _apply():
        current = bpy.data.objects.get(helper_name)
        if is_object_mask_helper(current):
            sync_object_mask_bounds_handles(current)
        return None

    try:
        from .safe_tasks import schedule_once
        return bool(schedule_once(
            f"object_masks.helper_transform.{helper_name}", _apply, first_interval=0.0
        ))
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        return sync_object_mask_bounds_handles(helper)


def _remove_object_mask_bounds_handle(handle):
    if not is_object_mask_bounds_handle(handle):
        return False
    try:
        mesh = getattr(handle, "data", None)
        bpy.data.objects.remove(handle, do_unlink=True)
        if mesh is not None and int(getattr(mesh, "users", 0) or 0) == 0:
            bpy.data.meshes.remove(mesh)
        return True
    except FBP_DATA_ERRORS:
        return False


def _store_bounds(helper, bounds):
    try:
        helper[KEY_BOUNDS] = [float(value) for value in bounds]
    except FBP_DATA_ERRORS:
        pass


def _read_bounds(helper, fallback):
    try:
        values = tuple(float(value) for value in helper.get(KEY_BOUNDS, ()) or ())
        return values if len(values) == 4 else tuple(fallback)
    except FBP_DATA_ERRORS:
        return tuple(fallback)


def _apply_helper_lock(owner, helper, shape):
    if not helper:
        return False
    try:
        locked = bool(getattr(owner, object_mask_lock_property(shape), True)) if owner else True
        desired_location = (False, False, locked)
        desired_rotation = (locked, locked, False)
        desired_scale = (False, False, locked)
        changed = False
        if tuple(helper.lock_location) != desired_location:
            helper.lock_location = desired_location
            changed = True
        if tuple(helper.lock_rotation) != desired_rotation:
            helper.lock_rotation = desired_rotation
            changed = True
        if tuple(helper.lock_scale) != desired_scale:
            helper.lock_scale = desired_scale
            changed = True
        return changed
    except FBP_DATA_ERRORS:
        return False


def _apply_helper_mesh_plane_lock(owner, helper, shape):
    """Keep editable vertices on the helper plane while the default lock is active."""
    if not helper:
        return False
    try:
        if not bool(getattr(owner, object_mask_lock_property(shape), True)):
            return False
    except FBP_DATA_ERRORS:
        return False
    mesh = getattr(helper, "data", None)
    if mesh is None:
        return False
    changed = False
    if bmesh is not None and bool(getattr(mesh, "is_editmode", False)):
        try:
            bm = bmesh.from_edit_mesh(mesh)
            for vertex in bm.verts:
                if abs(float(vertex.co.z)) > 1.0e-8:
                    vertex.co.z = 0.0
                    changed = True
            if changed:
                bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
            return changed
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return False
    try:
        for vertex in mesh.vertices:
            if abs(float(vertex.co.z)) > 1.0e-8:
                vertex.co.z = 0.0
                changed = True
        if changed:
            mesh.update()
        return changed
    except FBP_DATA_ERRORS:
        return False


def _select_object_mask_controller_preserving_layer(context, owner, controller):
    """Activate only the Shape Mask controller in the 3D View.

    Frame By Plane keeps layer selection in its own Layer List. Selecting the
    rig and plane together with a mask cage made G/S transform the layer as well,
    and prevented selecting two opposite handles for symmetric scaling.
    """
    if not owner or not controller:
        return False
    context = context or bpy.context
    try:
        selected_objects = tuple(getattr(context, "selected_objects", ()) or ())
    except FBP_DATA_ERRORS:
        selected_objects = ()
    changed = False
    for candidate in selected_objects:
        if candidate is controller:
            continue
        try:
            if candidate.select_get():
                candidate.select_set(False)
                changed = True
        except FBP_DATA_ERRORS:
            continue
    try:
        if controller.hide_get():
            controller.hide_set(False)
            changed = True
        if not controller.select_get():
            controller.select_set(True)
            changed = True
        view_layer = getattr(context, "view_layer", None)
        if view_layer and view_layer.objects.active is not controller:
            view_layer.objects.active = controller
            changed = True
    except FBP_DATA_ERRORS:
        pass
    return changed



def _rollback_created_object_mask(owner, shape, helper, mesh):
    """Remove every generated datablock created by a failed Shape Mask setup."""
    prop_name = object_mask_pointer_property(shape)
    try:
        if getattr(owner, prop_name, None) is helper:
            fbp_set_rna_property_silent(owner, prop_name, None)
    except FBP_DATA_ERRORS:
        pass
    image = object_mask_image(helper) if helper is not None else None
    for handle in tuple(object_mask_bounds_handles(helper) if helper is not None else ()):
        _remove_object_mask_bounds_handle(handle)
    if helper is not None:
        clear_object_mask_helper_tag(helper)
        try:
            if bpy.data.objects.get(helper.name) is helper:
                bpy.data.objects.remove(helper, do_unlink=True)
        except FBP_DATA_IO_ERRORS:
            pass
    try:
        if mesh is not None and getattr(mesh, "users", 0) == 0:
            bpy.data.meshes.remove(mesh)
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        if (
            image is not None
            and bool(image.get(KEY_IS_MASK_IMAGE, False))
            and getattr(image, "users", 0) == 0
        ):
            bpy.data.images.remove(image)
    except FBP_DATA_IO_ERRORS:
        pass
    return True


def create_object_mask_helper(owner, shape, context=None, *, select=True):
    shape = normalize_object_mask_shape(shape)
    existing = find_object_mask_helper(owner, shape)
    if existing:
        if select:
            ensure_object_mask_bounds_handles(existing, select=True, context=context)
        else:
            ensure_object_mask_bounds_handles(existing, context=context)
        sync_object_mask_helper_visibility(existing, owner=owner)
        return existing
    plane, bounds = _plane_bounds(owner)
    if not plane:
        return None
    label = object_mask_label(shape)
    mesh = None
    helper = None
    try:
        with FBPTransaction(
            f"Create {label} Mask",
            kind="MASK_CREATE",
            journal_owner=owner,
            context={"shape": shape},
        ) as transaction:
            mesh = _shape_mesh(shape, f"FBP {label} Mask Mesh • {owner.name}")
            helper = bpy.data.objects.new(f"FBP {label} Mask • {owner.name}", mesh)
            transaction.defer_rollback(
                _rollback_created_object_mask,
                owner, shape, helper, mesh,
                label="remove incomplete Shape Mask",
            )
            transaction.checkpoint("LINK_HELPER")
            _link_helper(helper, plane, context=context)
            helper.parent = plane
            helper.matrix_parent_inverse = Matrix.Identity(4)
            min_x, max_x, min_y, max_y = bounds
            center_x = (min_x + max_x) * 0.5
            center_y = (min_y + max_y) * 0.5
            half_x = max((max_x - min_x) * 0.5, 1.0e-5)
            half_y = max((max_y - min_y) * 0.5, 1.0e-5)
            helper.location = (center_x, center_y, 0.002)
            helper.rotation_euler = (0.0, 0.0, 0.0)
            helper.scale = (half_x * 0.8, half_y * 0.8, 1.0)
            helper.display_type = "WIRE"
            helper.show_in_front = True
            helper.hide_render = True
            helper.hide_select = False
            helper.color = (1.0, 0.35, 0.05, 1.0)
            tag_object_mask_helper(helper, owner, shape)
            try:
                from .ownership import tag_mask_helper_contract
                tag_mask_helper_contract(helper, owner)
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
            _ensure_helper_wire_topology(helper)
            _store_bounds(helper, bounds)
            _apply_helper_lock(owner, helper, shape)
            fbp_set_rna_property_silent(owner, object_mask_pointer_property(shape), helper)

            transaction.checkpoint("CREATE_SDF")
            image = ensure_object_mask_image(helper, force=True)
            if image is None:
                raise RuntimeError("Shape Mask SDF image was not created")
            handles = ensure_object_mask_bounds_handles(
                helper, select=select, context=context
            )
            if len(handles) != 8:
                raise RuntimeError(
                    f"Shape Mask created {len(handles)} of 8 required bounds handles"
                )
            sync_object_mask_helper_visibility(helper, owner=owner)
            transaction.checkpoint("VALIDATED")
            transaction.commit()
            return helper
    except FBP_DATA_IO_ERRORS as exc:
        fbp_warn(
            "Could not create editable Shape Mask",
            exc,
            event="mask.create.transaction",
            context={"shape": shape, "owner": getattr(owner, "name", "")},
        )
        return None


def ensure_object_mask_helper(owner, shape, context=None, *, select=False):
    helper = find_object_mask_helper(owner, shape)
    if helper is None:
        return create_object_mask_helper(owner, shape, context=context, select=select)
    contract_changed = tag_object_mask_helper(helper, owner, shape)
    try:
        from .ownership import tag_mask_helper_contract
        contract_changed = bool(tag_mask_helper_contract(helper, owner)) or contract_changed
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    topology_changed = _ensure_helper_wire_topology(helper)
    _apply_helper_lock(owner, helper, shape)
    try:
        ensure_object_mask_image(
            helper, force=bool(contract_changed or topology_changed)
        )
    except FBP_DATA_ERRORS:
        pass
    ensure_object_mask_bounds_handles(helper, select=select, context=context)
    sync_object_mask_helper_visibility(helper, owner=owner)
    return helper


def sync_object_mask_helper_to_bounds(owner, shape, *, force=False):
    shape = normalize_object_mask_shape(shape)
    helper = find_object_mask_helper(owner, shape)
    if not helper:
        return False
    try:
        if not force and not bool(getattr(owner, object_mask_follow_property(shape), True)):
            return False
    except FBP_DATA_ERRORS:
        return False
    plane, new_bounds = _plane_bounds(owner)
    if not plane:
        return False
    old_bounds = _read_bounds(helper, new_bounds)
    old_min_x, old_max_x, old_min_y, old_max_y = old_bounds
    new_min_x, new_max_x, new_min_y, new_max_y = new_bounds
    old_center_x = (old_min_x + old_max_x) * 0.5
    old_center_y = (old_min_y + old_max_y) * 0.5
    new_center_x = (new_min_x + new_max_x) * 0.5
    new_center_y = (new_min_y + new_max_y) * 0.5
    old_half_x = max((old_max_x - old_min_x) * 0.5, 1.0e-8)
    old_half_y = max((old_max_y - old_min_y) * 0.5, 1.0e-8)
    new_half_x = max((new_max_x - new_min_x) * 0.5, 1.0e-8)
    new_half_y = max((new_max_y - new_min_y) * 0.5, 1.0e-8)
    try:
        normalized_x = (float(helper.location.x) - old_center_x) / old_half_x
        normalized_y = (float(helper.location.y) - old_center_y) / old_half_y
        normalized_scale_x = float(helper.scale.x) / old_half_x
        normalized_scale_y = float(helper.scale.y) / old_half_y
        desired_location = (
            new_center_x + normalized_x * new_half_x,
            new_center_y + normalized_y * new_half_y,
        )
        desired_scale = (
            normalized_scale_x * new_half_x,
            normalized_scale_y * new_half_y,
        )
        changed = False
        if abs(float(helper.location.x) - desired_location[0]) > 1.0e-8:
            helper.location.x = desired_location[0]
            changed = True
        if abs(float(helper.location.y) - desired_location[1]) > 1.0e-8:
            helper.location.y = desired_location[1]
            changed = True
        if abs(float(helper.scale.x) - desired_scale[0]) > 1.0e-8:
            helper.scale.x = desired_scale[0]
            changed = True
        if abs(float(helper.scale.y) - desired_scale[1]) > 1.0e-8:
            helper.scale.y = desired_scale[1]
            changed = True
        _store_bounds(helper, new_bounds)
        if changed:
            helper.update_tag()
        return changed
    except FBP_DATA_ERRORS:
        return False


def make_object_mask_shape_perfect(owner, shape):
    """Reset the cage to a perfect square, circle or equilateral triangle."""
    shape = normalize_object_mask_shape(shape)
    helper = ensure_object_mask_helper(owner, shape, select=False)
    if helper is None:
        return False
    try:
        old_min_x, old_max_x, old_min_y, old_max_y = _object_mask_local_mesh_bounds(helper)
        rendered_width = max((old_max_x - old_min_x) * abs(float(helper.scale.x)), 1.0e-6)
        rendered_height = max((old_max_y - old_min_y) * abs(float(helper.scale.y)), 1.0e-6)
        if shape == "TRIANGLE":
            vertices = ((0.0, 1.0, 0.0), (-0.8660254, -0.5, 0.0), (0.8660254, -0.5, 0.0))
        elif shape == "CIRCLE":
            count = 64
            vertices = tuple(
                (math.cos((index / count) * math.tau), math.sin((index / count) * math.tau), 0.0)
                for index in range(count)
            )
        else:
            vertices = ((-1.0, -1.0, 0.0), (1.0, -1.0, 0.0), (1.0, 1.0, 0.0), (-1.0, 1.0, 0.0))
        xs = [value[0] for value in vertices]
        ys = [value[1] for value in vertices]
        canonical_width = max(max(xs) - min(xs), 1.0e-6)
        canonical_height = max(max(ys) - min(ys), 1.0e-6)
        uniform_scale = max(rendered_width / canonical_width, rendered_height / canonical_height)
        edges = tuple((index, (index + 1) % len(vertices)) for index in range(len(vertices)))
        mesh = helper.data
        mesh.clear_geometry()
        mesh.from_pydata(vertices, edges, [])
        mesh.update()
        sign_x = -1.0 if float(helper.scale.x) < 0.0 else 1.0
        sign_y = -1.0 if float(helper.scale.y) < 0.0 else 1.0
        helper.scale.x = sign_x * uniform_scale
        helper.scale.y = sign_y * uniform_scale
        refresh_object_mask_geometry(helper, force=True)
        sync_object_mask_bounds_handles(helper)
        return True
    except FBP_DATA_ERRORS:
        return False


def clone_object_mask_helpers(source_owner, destination_owner, *, context=None):
    """Clone editable Shape Mask cages without resetting their dimensions."""
    if source_owner is None or destination_owner is None:
        return 0
    ensure_object_mask_owner_id(destination_owner)
    copied = 0
    for shape in ("SQUARE", "CIRCLE", "TRIANGLE"):
        source = find_object_mask_helper(source_owner, shape)
        if source is None:
            continue
        prop_name = object_mask_pointer_property(shape)
        fbp_set_rna_property_silent(destination_owner, prop_name, None)
        destination = create_object_mask_helper(
            destination_owner, shape, context=context, select=False
        )
        if destination is None:
            continue
        try:
            source_mesh = getattr(source, "data", None)
            vertices = tuple(tuple(float(value) for value in vertex.co) for vertex in source_mesh.vertices)
            edges = tuple(tuple(int(value) for value in edge.vertices) for edge in source_mesh.edges)
            destination.data.clear_geometry()
            destination.data.from_pydata(vertices, edges, [])
            destination.data.update()
            destination.location = source.location.copy()
            destination.rotation_mode = source.rotation_mode
            destination.rotation_euler = source.rotation_euler.copy()
            destination.scale = source.scale.copy()
            _store_bounds(destination, _read_bounds(source, _plane_bounds(destination_owner)[1]))
            tag_object_mask_helper(destination, destination_owner, shape)
            ensure_object_mask_image(destination, force=True)
            ensure_object_mask_bounds_handles(destination, context=context)
            sync_object_mask_bounds_handles(destination)
            from .geometry_nodes import fbp_refresh_object_mask_binding
            fbp_refresh_object_mask_binding(destination_owner, object_mask_effect_id(shape))
            copied += 1
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return copied


def sync_owner_object_mask_helpers(owner, *, force=False):
    """Synchronize every helper without short-circuiting after the first change."""
    changed = False
    for shape in ("SQUARE", "CIRCLE", "TRIANGLE"):
        changed = sync_object_mask_helper_to_bounds(owner, shape, force=force) or changed
    return changed


def _mesh_boundary_data(helper):
    mesh = getattr(helper, "data", None)
    if mesh is None:
        return {}, []

    if bmesh is not None and bool(getattr(mesh, "is_editmode", False)):
        try:
            bm = bmesh.from_edit_mesh(mesh)
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            coords = {
                int(vertex.index): (float(vertex.co.x), float(vertex.co.y))
                for vertex in bm.verts
            }
            edges = [
                (int(edge.verts[0].index), int(edge.verts[1].index))
                for edge in bm.edges
                if len(edge.link_faces) <= 1
            ]
            return coords, edges
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass

    try:
        coords = {
            int(vertex.index): (float(vertex.co.x), float(vertex.co.y))
            for vertex in mesh.vertices
        }
        edge_counts = {tuple(sorted(edge.vertices)): 0 for edge in mesh.edges}
        for polygon in mesh.polygons:
            vertices = tuple(int(index) for index in polygon.vertices)
            for index, first in enumerate(vertices):
                second = vertices[(index + 1) % len(vertices)]
                key = tuple(sorted((first, second)))
                edge_counts[key] = edge_counts.get(key, 0) + 1
        edges = [key for key, count in edge_counts.items() if count <= 1]
        return coords, edges
    except FBP_DATA_ERRORS:
        return {}, []


def _ordered_polygon_points(helper):
    coords, edges = _mesh_boundary_data(helper)
    if len(coords) < 3:
        return []

    adjacency = {index: [] for index in coords}
    for first, second in edges:
        if first in adjacency and second in adjacency and first != second:
            adjacency[first].append(second)
            adjacency[second].append(first)

    usable = [index for index, neighbours in adjacency.items() if len(neighbours) == 2]
    if len(usable) >= 3 and len(usable) == len([index for index in adjacency if adjacency[index]]):
        start = min(usable)
        ordered = [start]
        previous = None
        current = start
        for _ in range(len(usable) + 1):
            neighbours = adjacency.get(current, ())
            next_index = neighbours[0] if neighbours and neighbours[0] != previous else (neighbours[1] if len(neighbours) > 1 else None)
            if next_index is None:
                break
            if next_index == start:
                if len(ordered) >= 3:
                    return [coords[index] for index in ordered]
                break
            if next_index in ordered:
                break
            ordered.append(next_index)
            previous, current = current, next_index

    # Conservative fallback for malformed helper topology. Angle ordering keeps
    # the mask usable after accidental face deletion and works for the intended
    # convex Square/Circle/Triangle workflows.
    points = list(coords.values())
    center_x = sum(point[0] for point in points) / len(points)
    center_y = sum(point[1] for point in points) / len(points)
    points.sort(key=lambda point: math.atan2(point[1] - center_y, point[0] - center_x))
    return points


def _geometry_signature(points):
    return "|".join(f"{x:.6f},{y:.6f}" for x, y in points)


def _numpy_module():
    global _NUMPY, _NUMPY_CHECKED
    if _NUMPY_CHECKED:
        return _NUMPY
    _NUMPY_CHECKED = True
    try:
        import numpy as np
        _NUMPY = np
    except ImportError:
        _NUMPY = None
    return _NUMPY


def _polygon_raster_bounds(points):
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 1.0e-5)
    span_y = max(max_y - min_y, 1.0e-5)
    padding = max(span_x, span_y) * 0.08
    return (
        min_x - padding, max_x + padding,
        min_y - padding, max_y + padding,
    )


def _rasterize_sdf_numpy(points, bounds, resolution, np):
    min_x, max_x, min_y, max_y = bounds
    xs = np.linspace(min_x, max_x, resolution, dtype=np.float32)
    ys = np.linspace(min_y, max_y, resolution, dtype=np.float32)
    grid_x, grid_y = np.meshgrid(xs, ys)
    inside = np.zeros((resolution, resolution), dtype=np.bool_)
    min_distance_sq = np.full((resolution, resolution), np.inf, dtype=np.float32)
    epsilon = np.float32(1.0e-12)

    for index, first in enumerate(points):
        second = points[(index + 1) % len(points)]
        x1, y1 = np.float32(first[0]), np.float32(first[1])
        x2, y2 = np.float32(second[0]), np.float32(second[1])
        dy = y2 - y1
        safe_dy = dy if abs(float(dy)) > 1.0e-12 else np.float32(1.0e-12)
        crosses = ((y1 > grid_y) != (y2 > grid_y)) & (
            grid_x < ((x2 - x1) * (grid_y - y1) / safe_dy + x1)
        )
        inside ^= crosses

        edge_x = x2 - x1
        edge_y = y2 - y1
        length_sq = edge_x * edge_x + edge_y * edge_y
        if float(length_sq) <= 1.0e-12:
            continue
        projection = ((grid_x - x1) * edge_x + (grid_y - y1) * edge_y) / max(length_sq, epsilon)
        projection = np.clip(projection, 0.0, 1.0)
        closest_x = x1 + projection * edge_x
        closest_y = y1 + projection * edge_y
        distance_sq = (grid_x - closest_x) ** 2 + (grid_y - closest_y) ** 2
        min_distance_sq = np.minimum(min_distance_sq, distance_sq)

    distance = np.sqrt(min_distance_sq)
    scale = np.float32(max(max_x - min_x, max_y - min_y, 1.0e-5))
    # Normalize the positive half of the SDF by the deepest interior sample.
    # This makes Feather=1.0 span the full usable radius for every editable
    # polygon (especially triangles), while the shader still clamps all
    # exterior samples to zero before feathering.
    interior_distance = np.where(inside, distance, np.float32(0.0))
    max_interior = np.float32(max(float(np.max(interior_distance)), 1.0e-5))
    encoded_inside = np.float32(0.5) + np.float32(0.5) * (distance / max_interior)
    encoded_outside = np.float32(0.5) - (distance / scale)
    encoded = np.where(inside, encoded_inside, encoded_outside)
    encoded = np.clip(encoded, 0.0, 1.0).astype(np.float32)
    rgba = np.repeat(encoded[:, :, np.newaxis], 4, axis=2)
    return rgba.reshape(-1)


def _distance_to_segments(x, y, points):
    best = float("inf")
    previous = points[-1]
    for current in points:
        x1, y1 = previous
        x2, y2 = current
        edge_x = x2 - x1
        edge_y = y2 - y1
        length_sq = edge_x * edge_x + edge_y * edge_y
        if length_sq <= 1.0e-12:
            previous = current
            continue
        projection = ((x - x1) * edge_x + (y - y1) * edge_y) / length_sq
        projection = max(0.0, min(1.0, projection))
        closest_x = x1 + projection * edge_x
        closest_y = y1 + projection * edge_y
        distance = math.hypot(x - closest_x, y - closest_y)
        best = min(best, distance)
        previous = current
    return 0.0 if best == float("inf") else best


def _rasterize_sdf_fallback(points, bounds, resolution):
    min_x, max_x, min_y, max_y = bounds
    scale = max(max_x - min_x, max_y - min_y, 1.0e-5)
    samples = []
    max_interior = 1.0e-5
    for row in range(resolution):
        y = min_y + (max_y - min_y) * (row / max(1, resolution - 1))
        for column in range(resolution):
            x = min_x + (max_x - min_x) * (column / max(1, resolution - 1))
            inside = _point_inside_polygon(x, y, points)
            distance = _distance_to_segments(x, y, points)
            samples.append((inside, distance))
            if inside:
                max_interior = max(max_interior, distance)

    pixels = array('f')
    for inside, distance in samples:
        if inside:
            encoded = 0.5 + 0.5 * (distance / max_interior)
        else:
            encoded = 0.5 - distance / scale
        encoded = max(0.0, min(1.0, encoded))
        pixels.extend((encoded, encoded, encoded, encoded))
    return pixels


def _validated_object_mask_image(helper):
    """Return the currently published private image when its ownership matches."""
    contract = object_mask_contract(helper) or {}
    owner_id = str(contract.get("owner_id", "") or "")
    shape = normalize_object_mask_shape(contract.get("shape", "SQUARE"))
    try:
        image_name = str(helper.get(KEY_IMAGE_NAME, "") or "")
    except FBP_DATA_ERRORS:
        image_name = ""
    image = bpy.data.images.get(image_name) if image_name else None
    if image is None:
        return None
    try:
        if str(image.get(KEY_OWNER_ID, "") or "") != owner_id:
            return None
        if normalize_object_mask_shape(image.get(KEY_SHAPE, shape)) != shape:
            return None
    except FBP_DATA_ERRORS:
        return None
    return image


def _retire_object_mask_image(image, *, now=None):
    """Quarantine a generated SDF buffer without racing viewport workers."""
    if image is None:
        return False
    try:
        image_name = str(image.name)
        image["fbp_orphan_candidate"] = True
        image[KEY_IMAGE_RETIRE_SESSION] = _OBJECT_MASK_IMAGE_SESSION_ID
        _OBJECT_MASK_IMAGE_RETIRED_AT[image_name] = (
            time.monotonic() if now is None else float(now)
        )
        _OBJECT_MASK_IMAGE_RETIRED_POINTERS[image_name] = _runtime_pointer(image)
        return True
    except FBP_DATA_ERRORS + (TypeError, ValueError):
        return False


def _forget_object_mask_image_retirement(image_name):
    image_name = str(image_name or "")
    _OBJECT_MASK_IMAGE_RETIRED_AT.pop(image_name, None)
    _OBJECT_MASK_IMAGE_RETIRED_POINTERS.pop(image_name, None)


def _activate_object_mask_image(image):
    """Publish a quarantined SDF buffer and clear runtime retirement state."""
    if image is None:
        return False
    try:
        image_name = str(image.name)
        image["fbp_orphan_candidate"] = False
        if KEY_IMAGE_RETIRE_SESSION in image:
            del image[KEY_IMAGE_RETIRE_SESSION]
        _forget_object_mask_image_retirement(image_name)
        return True
    except FBP_DATA_ERRORS:
        return False


def _object_mask_image_reloaded_since_retirement(image):
    """Return whether a persisted orphan belongs to a different Blender Main.

    Runtime pointers change after ``open_mainfile`` and the session token changes
    after a full Blender restart. In either case no worker can still reference
    the old Image ID, so the usual short Eevee grace period is unnecessary.
    """
    if image is None:
        return False
    try:
        image_name = str(image.name)
        current_pointer = _runtime_pointer(image)
        retired_pointer = int(
            _OBJECT_MASK_IMAGE_RETIRED_POINTERS.get(image_name, 0) or 0
        )
        retired_session = str(image.get(KEY_IMAGE_RETIRE_SESSION, "") or "")
        if retired_session and retired_session != _OBJECT_MASK_IMAGE_SESSION_ID:
            return True
        if retired_pointer and retired_pointer != current_pointer:
            return True
        # Unscoped buffers without session tagging can only be
        # unknown when first discovered in a newly loaded Main. Treat them as
        # reload-safe; current-session retirement always records both fields.
        return bool(
            not retired_session
            and not retired_pointer
            and image_name not in _OBJECT_MASK_IMAGE_RETIRED_AT
        )
    except FBP_DATA_ERRORS + (TypeError, ValueError):
        return False


def _object_mask_image_has_active_private_group_user(image):
    """Return whether the image's sole user is one active FBP private group.

    Shape Mask removal quarantines the private shader group for Undo safety. If
    that exact group is re-adopted, its SDF image remains a valid managed user
    and can be published by the recreated helper without allocating a new image.
    """
    if image is None:
        return False
    try:
        if int(getattr(image, "users", 0) or 0) != 1:
            return False
    except FBP_DATA_ERRORS:
        return False
    matches = 0
    try:
        for node_group in tuple(bpy.data.node_groups):
            if not bool(node_group.get("fbp_private_effect_group", False)):
                continue
            if bool(node_group.get("fbp_quarantined", False)):
                continue
            for node in tuple(getattr(node_group, "nodes", ()) or ()):
                if getattr(node, "image", None) is image:
                    matches += 1
                    if matches > 1:
                        return False
    except FBP_DATA_ERRORS:
        return False
    return matches == 1


def _mask_image_for_helper(helper, resolution):
    """Return a safely retired SDF buffer and the published image.

    A zero-user Image can still be referenced transiently by Eevee workers.
    Reuse is therefore allowed only after a process-local retirement delay and
    only at the exact existing resolution; generated Images are never scaled.
    """
    contract = object_mask_contract(helper) or {}
    owner_id = str(contract.get("owner_id", "") or "")
    shape = normalize_object_mask_shape(contract.get("shape", "SQUARE"))
    current = _validated_object_mask_image(helper)
    owner_token = str(owner_id or uuid.uuid4().hex)[:12]
    base_name = f"FBP {object_mask_label(shape)} Mask SDF • {owner_token} • Buffer"
    image = None
    now = time.monotonic()

    # Persisted orphan candidates can survive while process-local timestamps do
    # not. Discover them without erasing whether they came from another Main;
    # that distinction allows immediate, safe reuse after file load.
    candidate_names = set(_OBJECT_MASK_IMAGE_RETIRED_AT)
    try:
        for candidate in tuple(bpy.data.images):
            if not str(getattr(candidate, "name", "") or "").startswith(base_name):
                continue
            if not bool(candidate.get("fbp_orphan_candidate", False)):
                continue
            candidate_names.add(str(candidate.name))
    except FBP_DATA_ERRORS:
        pass

    for candidate_name in tuple(candidate_names):
        retired_at_value = _OBJECT_MASK_IMAGE_RETIRED_AT.get(str(candidate_name), 0.0)
        candidate = bpy.data.images.get(str(candidate_name))
        if candidate is None:
            _forget_object_mask_image_retirement(candidate_name)
            continue
        try:
            if candidate is current or not str(candidate.name or "").startswith(base_name):
                continue
            if str(candidate.get(KEY_OWNER_ID, "") or "") not in {"", owner_id}:
                continue
            if normalize_object_mask_shape(candidate.get(KEY_SHAPE, shape)) != shape:
                continue
            candidate_users = int(getattr(candidate, "users", 0) or 0)
            managed_live_user = _object_mask_image_has_active_private_group_user(candidate)
            if candidate_users > 0 and not managed_live_user:
                continue
            reloaded_candidate = _object_mask_image_reloaded_since_retirement(candidate)
            retired_at = float(retired_at_value or 0.0)
            if not managed_live_user and not reloaded_candidate:
                if retired_at <= 0.0:
                    _retire_object_mask_image(candidate, now=now)
                    continue
                if now - retired_at < _OBJECT_MASK_IMAGE_REUSE_DELAY:
                    continue
            if tuple(int(value) for value in candidate.size[:2]) != (resolution, resolution):
                continue
            image = candidate
            break
        except FBP_DATA_ERRORS:
            continue

    if image is None:
        image = bpy.data.images.new(
            base_name,
            width=resolution,
            height=resolution,
            alpha=True,
            float_buffer=False,
        )

    try:
        _set_idprop_if_changed(image, KEY_IS_MASK_IMAGE, True)
        _set_idprop_if_changed(image, KEY_OWNER_ID, owner_id)
        _set_idprop_if_changed(image, KEY_SHAPE, shape)
        _set_idprop_if_changed(image, "fbp_generated_buffer", True)
        if image.colorspace_settings.name != "Non-Color":
            image.colorspace_settings.name = "Non-Color"
    except FBP_DATA_ERRORS:
        pass
    return image, current


def _object_mask_image_is_retired_candidate(image):
    """Return whether *image* is a generated, detached Shape Mask buffer."""
    if image is None:
        return False
    try:
        return bool(
            int(getattr(image, "users", 0) or 0) == 0
            and image.get(KEY_IS_MASK_IMAGE, False)
            and image.get("fbp_generated_buffer", False)
            and image.get("fbp_orphan_candidate", False)
        )
    except FBP_DATA_ERRORS:
        return False


def _purge_retired_object_mask_images(*, now=None):
    """Remove expired zero-user Shape Mask buffers after the Eevee grace period.

    Helpers publish images by name while shader nodes hold the actual user
    reference. Deleting immediately can race viewport workers, so removal is
    delayed and limited to generated orphan candidates with no live users.
    Persisted candidates are adopted after file load because the process-local
    retirement timestamps are intentionally not stored in the blend file.
    """
    current_time = time.monotonic() if now is None else float(now)
    for image in tuple(bpy.data.images):
        if not _object_mask_image_is_retired_candidate(image):
            continue
        try:
            _OBJECT_MASK_IMAGE_RETIRED_AT.setdefault(str(image.name), current_time)
        except FBP_DATA_ERRORS:
            continue

    removed = 0
    for image_name, retired_at_value in tuple(_OBJECT_MASK_IMAGE_RETIRED_AT.items()):
        image_name = str(image_name or "")
        image = bpy.data.images.get(image_name) if image_name else None
        if image is None:
            _forget_object_mask_image_retirement(image_name)
            continue
        try:
            retired_at = float(retired_at_value or 0.0)
            if retired_at <= 0.0 or current_time - retired_at < _OBJECT_MASK_IMAGE_REUSE_DELAY:
                continue
            if int(getattr(image, "users", 0) or 0) > 0:
                continue
            if not bool(image.get(KEY_IS_MASK_IMAGE, False)):
                _forget_object_mask_image_retirement(image_name)
                continue
            if not bool(image.get("fbp_generated_buffer", False)):
                _forget_object_mask_image_retirement(image_name)
                continue
            if not bool(image.get("fbp_orphan_candidate", False)):
                _forget_object_mask_image_retirement(image_name)
                continue
            bpy.data.images.remove(image)
            _forget_object_mask_image_retirement(image_name)
            removed += 1
        except FBP_DATA_ERRORS:
            continue
    return removed


def _object_mask_image_is_retiring(image, *, now=None):
    """Return whether an orphan buffer is inside managed retirement."""
    if not _object_mask_image_is_retired_candidate(image):
        return False
    try:
        current_time = time.monotonic() if now is None else float(now)
        image_name = str(image.name)
        retired_at = float(_OBJECT_MASK_IMAGE_RETIRED_AT.get(image_name, 0.0) or 0.0)
        if retired_at <= 0.0:
            # On file load, process-local timestamps are empty while tagged
            # zero-user buffers persist. Adopt them now and grant the same
            # Eevee-safe delay used by buffers retired in the current session.
            _OBJECT_MASK_IMAGE_RETIRED_AT[image_name] = current_time
            return True
        return current_time - retired_at < _OBJECT_MASK_IMAGE_REUSE_DELAY
    except FBP_DATA_ERRORS + (TypeError, ValueError):
        return False


def object_mask_image(helper):
    if not helper:
        return None
    try:
        name = str(helper.get(KEY_IMAGE_NAME, "") or "")
    except FBP_DATA_ERRORS:
        name = ""
    return bpy.data.images.get(name) if name else None


def object_mask_image_bounds(helper, fallback=(-1.0, 1.0, -1.0, 1.0)):
    if not helper:
        return tuple(fallback)
    try:
        values = tuple(float(value) for value in helper.get(KEY_IMAGE_BOUNDS, ()) or ())
        return values if len(values) == 4 else tuple(fallback)
    except FBP_DATA_ERRORS:
        return tuple(fallback)


def ensure_object_mask_image(helper, *, force=False):
    """Create/update the helper SDF image and return ``(image, bounds, changed)``."""
    if not is_object_mask_helper(helper):
        return None, (-1.0, 1.0, -1.0, 1.0), False
    points = _ordered_polygon_points(helper)
    if len(points) < 3:
        try:
            old_signature = str(helper.get(KEY_GEOMETRY_SIGNATURE, "") or "")
            helper[KEY_GEOMETRY_SIGNATURE] = "INVALID"
        except FBP_DATA_ERRORS:
            old_signature = ""
        return None, object_mask_image_bounds(helper), old_signature != "INVALID"
    signature = f"v{FBP_OBJECT_MASK_SCHEMA_VERSION}|{_geometry_signature(points)}"
    try:
        old_signature = str(helper.get(KEY_GEOMETRY_SIGNATURE, "") or "")
    except FBP_DATA_ERRORS:
        old_signature = ""
    np = _numpy_module()
    resolution = FBP_OBJECT_MASK_RESOLUTION if np is not None else FBP_OBJECT_MASK_FALLBACK_RESOLUTION
    current_image = _validated_object_mask_image(helper)
    bounds = _polygon_raster_bounds(points)
    current_size_matches = False
    if current_image is not None:
        try:
            current_size_matches = tuple(int(value) for value in current_image.size[:2]) == (resolution, resolution)
        except FBP_DATA_ERRORS:
            current_size_matches = False
    if not force and current_size_matches and signature == old_signature:
        return current_image, object_mask_image_bounds(helper, bounds), False

    image, previous_image = _mask_image_for_helper(helper, resolution)
    pixels = (
        _rasterize_sdf_numpy(points, bounds, resolution, np)
        if np is not None
        else _rasterize_sdf_fallback(points, bounds, resolution)
    )
    try:
        image.pixels.foreach_set(pixels)
        image.update()
        image[KEY_IMAGE_BOUNDS] = [float(value) for value in bounds]
        helper[KEY_IMAGE_NAME] = image.name
        helper[KEY_IMAGE_BOUNDS] = [float(value) for value in bounds]
        helper[KEY_GEOMETRY_SIGNATURE] = signature
        helper[KEY_SCHEMA] = FBP_OBJECT_MASK_SCHEMA_VERSION
        _activate_object_mask_image(image)
        if previous_image is not None and previous_image is not image:
            _retire_object_mask_image(previous_image)
        return image, bounds, True
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not update editable Shape Mask image", exc)
        return image, bounds, False


def refresh_object_mask_geometry(helper, *, force=False):
    owner = find_object_mask_owner(helper)
    shape = normalize_object_mask_shape(
        (object_mask_contract(helper) or {}).get("shape", "SQUARE")
    )
    plane_lock_changed = (
        _apply_helper_mesh_plane_lock(owner, helper, shape)
        if owner is not None else False
    )
    topology_changed = _ensure_helper_wire_topology(helper)
    _image, _bounds, changed = ensure_object_mask_image(
        helper, force=force or topology_changed or plane_lock_changed
    )
    if owner is None:
        return plane_lock_changed or topology_changed or changed
    try:
        from .geometry_nodes import fbp_refresh_object_mask_binding
        binding_changed = bool(
            fbp_refresh_object_mask_binding(owner, object_mask_effect_id(shape))
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        binding_changed = False
    return plane_lock_changed or topology_changed or changed or binding_changed




def fbp_shape_mask_project_v1(
    axis, mode,
    tx, ty, tz,
    px, py, pz, prx, pry, prz, psx, psy, psz,
    cx, cy, cz, crx, cry, crz,
):
    """Pure driver function: project a Null onto a layer plane.

    It receives only numeric driver variables and performs no RNA access or
    datablock mutation. Blender can therefore evaluate it inside the render
    depsgraph without racing viewport iteration.
    """
    try:
        plane_rotation = Euler((float(prx), float(pry), float(prz)), 'XYZ')
        plane_scale = Vector((
            float(psx) if abs(float(psx)) > 1.0e-12 else 1.0e-12,
            float(psy) if abs(float(psy)) > 1.0e-12 else 1.0e-12,
            float(psz) if abs(float(psz)) > 1.0e-12 else 1.0e-12,
        ))
        plane_matrix = Matrix.LocRotScale(
            Vector((float(px), float(py), float(pz))),
            plane_rotation.to_quaternion(),
            plane_scale,
        )
        point_world = Vector((float(tx), float(ty), float(tz)))
        mode = int(mode)
        if mode < 0:
            hit = point_world
        else:
            plane_normal = plane_rotation.to_quaternion() @ Vector((0.0, 0.0, 1.0))
            camera_rotation = Euler((float(crx), float(cry), float(crz)), 'XYZ')
            if mode == 0:  # Orthographic camera.
                ray_origin = point_world
                ray_direction = camera_rotation.to_quaternion() @ Vector((0.0, 0.0, -1.0))
            else:  # Perspective camera.
                ray_origin = Vector((float(cx), float(cy), float(cz)))
                ray_direction = point_world - ray_origin
            denominator = ray_direction.dot(plane_normal)
            if ray_direction.length_squared <= 1.0e-12 or abs(float(denominator)) <= 1.0e-10:
                hit = point_world
            else:
                distance = (
                    Vector((float(px), float(py), float(pz))) - ray_origin
                ).dot(plane_normal) / denominator
                hit = ray_origin + ray_direction * distance
        local = plane_matrix.inverted_safe() @ hit
        return float(local[0 if int(axis) == 0 else 1])
    except (IndexError, TypeError, ValueError, OverflowError):
        return 0.0


def register_shape_mask_driver_namespace():
    try:
        bpy.app.driver_namespace['fbp_shape_mask_project_v1'] = fbp_shape_mask_project_v1
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def unregister_shape_mask_driver_namespace():
    try:
        current = bpy.app.driver_namespace.get('fbp_shape_mask_project_v1')
        if current is fbp_shape_mask_project_v1:
            bpy.app.driver_namespace.pop('fbp_shape_mask_project_v1', None)
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _shape_mask_driver_scene(owner, scene=None):
    plane = getattr(owner, 'fbp_plane_target', None) if owner else None
    scene = scene or getattr(bpy.context, 'scene', None)
    try:
        if scene is not None and plane is not None and scene.objects.get(plane.name) is plane:
            return scene
    except FBP_DATA_ERRORS:
        pass
    if plane is not None:
        for candidate in tuple(getattr(bpy.data, 'scenes', ()) or ()):
            try:
                if candidate.objects.get(plane.name) is plane:
                    return candidate
            except FBP_DATA_ERRORS:
                continue
    return scene


def _shape_mask_driver_fcurve(helper, axis):
    try:
        animation_data = getattr(helper, 'animation_data', None)
        for fcurve in tuple(getattr(animation_data, 'drivers', ()) or ()):
            if fcurve.data_path == 'location' and int(fcurve.array_index) == int(axis):
                return fcurve
    except FBP_DATA_ERRORS:
        pass
    return None


def _remove_shape_mask_external_drivers(helper, *, preserve=True):
    if helper is None:
        return False
    try:
        current = helper.location.copy() if preserve else None
    except FBP_DATA_ERRORS:
        current = None
    changed = False
    for axis in (0, 1):
        if _shape_mask_driver_fcurve(helper, axis) is None:
            continue
        try:
            helper.driver_remove('location', axis)
            changed = True
        except FBP_DATA_ERRORS:
            pass
    if current is not None and changed:
        try:
            helper.location.x = float(current.x)
            helper.location.y = float(current.y)
        except FBP_DATA_ERRORS:
            pass
    try:
        if KEY_EXTERNAL_DRIVER_SIGNATURE in helper:
            del helper[KEY_EXTERNAL_DRIVER_SIGNATURE]
            changed = True
    except FBP_DATA_ERRORS:
        pass
    return changed


def _shape_mask_driver_signature(target, plane, camera, mode):
    def _name(value):
        try:
            return str(getattr(value, 'name_full', value.name) or '')
        except FBP_DATA_ERRORS:
            return ''
    return f"v1|{_name(target)}|{_name(plane)}|{_name(camera)}|{int(mode)}"


def ensure_shape_mask_external_null_drivers(owner, shape, helper=None, *, scene=None):
    """Install native transform drivers for a linked Shape Mask controller."""
    if owner is None or fbp_undo_guard_active() or fbp_render_mutation_blocked():
        return False
    shape = normalize_object_mask_shape(shape)
    try:
        target = getattr(owner, object_mask_external_null_property(shape), None)
        plane = getattr(owner, 'fbp_plane_target', None)
    except FBP_DATA_ERRORS:
        return False
    helper = helper or find_object_mask_helper(owner, shape)
    if helper is None:
        return False
    if target is None or plane is None or getattr(target, 'type', '') != 'EMPTY':
        return _remove_shape_mask_external_drivers(helper, preserve=True)

    scene = _shape_mask_driver_scene(owner, scene)
    camera = getattr(scene, 'camera', None) if scene is not None else None
    camera_type = str(getattr(getattr(camera, 'data', None), 'type', '') or '') if camera else ''
    mode = -1 if camera is None else (0 if camera_type == 'ORTHO' else 1)
    signature = _shape_mask_driver_signature(target, plane, camera, mode)
    try:
        current_signature = str(helper.get(KEY_EXTERNAL_DRIVER_SIGNATURE, '') or '')
    except FBP_DATA_ERRORS:
        current_signature = ''
    existing = tuple(_shape_mask_driver_fcurve(helper, axis) for axis in (0, 1))
    if current_signature == signature and all(
        fcurve is not None
        and str(getattr(getattr(fcurve, 'driver', None), 'expression', '') or '').startswith(
            'fbp_shape_mask_project_v1('
        )
        for fcurve in existing
    ):
        return False

    register_shape_mask_driver_namespace()
    _remove_shape_mask_external_drivers(helper, preserve=False)
    transform_specs = (
        ('tx', target, 'LOC_X'), ('ty', target, 'LOC_Y'), ('tz', target, 'LOC_Z'),
        ('px', plane, 'LOC_X'), ('py', plane, 'LOC_Y'), ('pz', plane, 'LOC_Z'),
        ('prx', plane, 'ROT_X'), ('pry', plane, 'ROT_Y'), ('prz', plane, 'ROT_Z'),
        ('psx', plane, 'SCALE_X'), ('psy', plane, 'SCALE_Y'), ('psz', plane, 'SCALE_Z'),
    )
    camera_specs = (
        ('cx', camera, 'LOC_X'), ('cy', camera, 'LOC_Y'), ('cz', camera, 'LOC_Z'),
        ('crx', camera, 'ROT_X'), ('cry', camera, 'ROT_Y'), ('crz', camera, 'ROT_Z'),
    ) if camera is not None else ()
    variable_names = [spec[0] for spec in transform_specs]
    camera_names = [spec[0] for spec in camera_specs] if camera_specs else ['0.0'] * 6
    for axis in (0, 1):
        try:
            fcurve = helper.driver_add('location', axis)
            driver = fcurve.driver
            driver.type = 'SCRIPTED'
            while driver.variables:
                driver.variables.remove(driver.variables[0])
            for spec in transform_specs + camera_specs:
                _add_transform_driver_variable(driver, *spec)
            args = ','.join(variable_names + camera_names)
            driver.expression = f'fbp_shape_mask_project_v1({axis},{mode},{args})'
        except FBP_DATA_ERRORS as exc:
            _remove_shape_mask_external_drivers(helper, preserve=True)
            fbp_warn('Could not create native Shape Mask driver', exc)
            return False
    try:
        helper[KEY_EXTERNAL_DRIVER_SIGNATURE] = signature
        helper.update_tag(refresh={'OBJECT'})
    except FBP_DATA_ERRORS:
        pass
    return True




def sync_shape_mask_external_null(
    owner, shape, helper=None, *, scene=None, depsgraph=None, sync_handles=True
):
    """Ensure a linked Shape Mask follows its Null through native drivers."""
    del depsgraph, sync_handles
    return ensure_shape_mask_external_null_drivers(
        owner, shape, helper=helper, scene=scene
    )


def sync_circle_mask_external_null(
    owner, helper=None, *, scene=None, depsgraph=None, sync_handles=True
):
    return sync_shape_mask_external_null(
        owner,
        'CIRCLE',
        helper=helper,
        scene=scene,
        depsgraph=depsgraph,
        sync_handles=sync_handles,
    )


def sync_external_shape_mask_targets(scene=None, *, depsgraph=None, render_safe=False):
    """Repair native external-Null drivers while Blender is idle."""
    del depsgraph, render_safe
    if fbp_undo_guard_active() or fbp_render_mutation_blocked():
        return False
    changed = False
    if scene is not None:
        try:
            from .layers import iter_scene_fbp_rigs
            owners = tuple(iter_scene_fbp_rigs(scene))
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            owners = ()
        for owner in owners:
            for shape in ('SQUARE', 'CIRCLE', 'TRIANGLE'):
                changed = ensure_shape_mask_external_null_drivers(
                    owner, shape, scene=scene
                ) or changed
        return changed

    _discover_object_mask_helpers()
    visited = set()
    for record in tuple(_HELPER_REGISTRY.values()):
        helper = _resolve_object_record(record)
        if not is_object_mask_helper(helper):
            continue
        contract = object_mask_contract(helper) or {}
        shape = normalize_object_mask_shape(contract.get('shape', 'SQUARE'))
        owner = find_object_mask_owner(helper)
        visit_key = (_runtime_pointer(owner), shape)
        if owner is None or visit_key in visited:
            continue
        visited.add(visit_key)
        changed = ensure_shape_mask_external_null_drivers(
            owner, shape, helper=helper
        ) or changed
    return changed


def sync_external_circle_mask_targets(scene=None, *, depsgraph=None, render_safe=False):
    return sync_external_shape_mask_targets(
        scene=scene, depsgraph=depsgraph, render_safe=render_safe
    )

def sync_object_mask_helper_visibility(helper, *, owner=None):
    if not is_object_mask_helper(helper):
        return False
    owner = owner or find_object_mask_owner(helper)
    contract = object_mask_contract(helper) or {}
    shape = normalize_object_mask_shape(contract.get("shape", "SQUARE"))
    # Never fall back to helper.parent here: a helper may survive one event-loop
    # tick after its generated parent was removed during regression cleanup.
    plane = getattr(owner, "fbp_plane_target", None) if owner else None
    try:
        show_preference = bool(getattr(owner, object_mask_show_property(shape), True)) if owner else True
        if owner is not None:
            sync_shape_mask_external_null(owner, shape, helper=helper)
        handles = object_mask_bounds_handles(helper)
        handle_selected = any(bool(handle.select_get()) for handle in handles)
        edit_mode = bool(getattr(getattr(helper, "data", None), "is_editmode", False))
        selected = bool(
            (owner and owner.select_get())
            or (plane and plane.select_get())
            or helper.select_get()
            or handle_selected
            or edit_mode
        )
        should_hide = not (show_preference and selected)
        # Hiding the object while Blender owns an Edit Mesh can invalidate the
        # current tool state. Defer the hide until Edit Mode exits.
        if edit_mode:
            should_hide = False
        hidden_now = bool(helper.hide_get())
        changed = False
        if hidden_now != should_hide:
            helper.hide_set(should_hide)
            changed = True
        for handle in handles:
            handle_should_hide = bool(should_hide or edit_mode)
            if bool(handle.hide_get()) != handle_should_hide:
                handle.hide_set(handle_should_hide)
                changed = True
        if not edit_mode:
            changed = sync_object_mask_bounds_handles(helper, handles=handles) or changed
        changed = _apply_helper_lock(owner, helper, shape) or changed
        # Vertex depth only needs policing while the cage is being edited.
        # Object-mode/scripted mesh changes are handled once by the geometry
        # refresh path, avoiding a full vertex loop for every hidden helper on
        # every visibility-timer tick.
        if edit_mode:
            changed = _apply_helper_mesh_plane_lock(owner, helper, shape) or changed
        return changed
    except FBP_DATA_ERRORS:
        return False


def sync_owner_object_mask_runtime(owner):
    changed = False
    for shape in ("SQUARE", "CIRCLE", "TRIANGLE"):
        helper = find_object_mask_helper(owner, shape)
        if helper:
            changed = sync_object_mask_helper_visibility(helper, owner=owner) or changed
    return changed


def _discover_object_mask_helpers(force=False):
    global _LAST_HELPER_DISCOVERY
    now = time.monotonic()
    if not force and _HELPER_REGISTRY and now - _LAST_HELPER_DISCOVERY < _ACTIVE_HELPER_DISCOVERY_SECONDS:
        return
    if not force and not _HELPER_REGISTRY and now - _LAST_HELPER_DISCOVERY < _EMPTY_HELPER_DISCOVERY_SECONDS:
        return
    _LAST_HELPER_DISCOVERY = now
    stale = set(_HELPER_REGISTRY)
    objects = tuple(getattr(bpy.data, "objects", ()) or ())

    # Build the owner table once so every helper does not fall back to its own
    # O(n) scan when a rig has been renamed since the file was saved.
    _refresh_mask_owner_index(force=True, objects=objects)

    for candidate in objects:
        if not is_object_mask_helper(candidate):
            continue
        contract = object_mask_contract(candidate) or {}
        owner = _resolve_object_record(_MASK_OWNER_INDEX.get(str(contract.get("owner_id", "") or "")))
        _register_helper_runtime(candidate, owner)
        _ensure_helper_wire_topology(candidate)
        stale.discard(_runtime_pointer(candidate))
    for pointer in stale:
        helper = _resolve_object_record(_HELPER_REGISTRY.get(pointer))
        if helper is None or not is_object_mask_helper(helper):
            _unregister_helper_runtime(helper, pointer=pointer)


def _helper_runtime_signature(helper, owner=None):
    """Return state that can affect cage visibility or plane-lock repair."""
    if not is_object_mask_helper(helper):
        return ()
    owner = owner or find_object_mask_owner(helper)
    contract = object_mask_contract(helper) or {}
    shape = normalize_object_mask_shape(contract.get("shape", "SQUARE"))
    plane = getattr(owner, "fbp_plane_target", None) if owner else None
    try:
        mesh = getattr(helper, "data", None)
        editmode = bool(getattr(mesh, "is_editmode", False))
        external_target = (
            getattr(owner, object_mask_external_null_property(shape), None)
            if owner else None
        )
        target_signature = ()
        plane_signature = ()
        camera_signature = ()
        if external_target is not None:
            target_signature = (
                _runtime_pointer(external_target),
                str(getattr(external_target, "name_full", external_target.name) or ""),
            )
            plane_signature = (
                _runtime_pointer(plane),
                str(getattr(plane, "name_full", plane.name) or ""),
            ) if plane else ()
            scene = _shape_mask_driver_scene(owner)
            camera = getattr(scene, "camera", None) if scene is not None else None
            if camera is not None:
                camera_signature = (
                    _runtime_pointer(camera),
                    str(getattr(camera, "name_full", camera.name) or ""),
                    str(getattr(getattr(camera, "data", None), "type", "") or ""),
                )
        return (
            _runtime_pointer(owner),
            bool(getattr(owner, object_mask_show_property(shape), True)) if owner else True,
            bool(getattr(owner, object_mask_lock_property(shape), True)) if owner else True,
            bool(owner and owner.select_get()),
            bool(plane and plane.select_get()),
            bool(helper.select_get()),
            editmode,
            bool(helper.hide_get()),
            tuple(bool(value) for value in getattr(helper, "lock_location", ())),
            tuple(bool(value) for value in getattr(helper, "lock_rotation", ())),
            tuple(round(float(value), 7) for value in (
                *((helper.location.x, helper.location.y) if external_target is None else (0.0, 0.0)),
                helper.location.z, helper.rotation_euler.z, helper.scale.x, helper.scale.y,
            )),
            target_signature,
            plane_signature,
            camera_signature,
        )
    except FBP_DATA_ERRORS:
        return ()


def _helper_runtime_sync_needed(pointer, helper, owner=None):
    signature = _helper_runtime_signature(helper, owner)
    if not signature or _HELPER_RUNTIME_SIGNATURES.get(pointer) != signature:
        return True
    return bool(signature[6])  # Edit Mode keeps depth locking responsive.


def _store_helper_runtime_signature(pointer, helper, owner=None):
    signature = _helper_runtime_signature(helper, owner)
    if signature:
        _HELPER_RUNTIME_SIGNATURES[pointer] = signature
    else:
        _HELPER_RUNTIME_SIGNATURES.pop(pointer, None)


def sync_all_object_mask_runtime(*, discover=True):
    """Synchronize every registered Shape Mask helper through one owner index.

    Effect-controller selection updates call this entry point instead of keeping
    a second helper-name cache and a second scene-scan implementation. The Shape
    Mask module remains the single source of truth for visibility, lock state and
    owner repair.
    """
    if discover:
        _discover_object_mask_helpers()
    changed = False
    for pointer, record in tuple(_HELPER_REGISTRY.items()):
        helper = _resolve_object_record(record)
        if not is_object_mask_helper(helper):
            _unregister_helper_runtime(helper, pointer=pointer)
            continue
        owner = find_object_mask_owner(helper)
        if owner is not None:
            _register_helper_runtime(helper, owner)
        try:
            changed = bool(sync_object_mask_helper_visibility(helper, owner=owner)) or changed
        except FBP_DATA_ERRORS:
            continue
        _store_helper_runtime_signature(pointer, helper, owner)
    return changed


def object_mask_runtime_timer():
    """Keep helper visibility/locks responsive and refresh edited geometry.

    The service stops completely when no Shape Mask helper exists. Registering
    the first helper starts it again, so empty projects no longer wake a timer
    every few seconds.
    """
    global _LAST_HELPER_MAINTENANCE, _OBJECT_MASK_TIMER_RUNNING
    _OBJECT_MASK_TIMER_RUNNING = True
    try:
        now = time.monotonic()
        if bool(fbp_runtime_get("fbp_pause_managed_timers", False)):
            return 0.5
        try:
            resume_after = float(fbp_runtime_get("fbp_managed_timers_resume_after", 0.0) or 0.0)
        except (TypeError, ValueError):
            resume_after = 0.0
        if resume_after > now:
            return max(0.05, min(0.5, resume_after - now))
        if fbp_undo_guard_active() or fbp_render_mutation_blocked():
            return 0.5

        maintenance_due = now - float(_LAST_HELPER_MAINTENANCE or 0.0) >= _HELPER_MAINTENANCE_SECONDS
        if maintenance_due or not _HELPER_REGISTRY:
            _discover_object_mask_helpers()
        has_helpers = False
        has_active_helper = False
        if maintenance_due:
            _LAST_HELPER_MAINTENANCE = now
            _purge_retired_object_mask_images(now=now)
        for pointer, record in tuple(_HELPER_REGISTRY.items()):
            helper = _resolve_object_record(record)
            if not is_object_mask_helper(helper):
                _unregister_helper_runtime(helper, pointer=pointer)
                continue
            has_helpers = True
            owner = find_object_mask_owner(helper)
            if owner is not None:
                _register_helper_runtime(helper, owner)
            try:
                selected_helper = bool(helper.select_get())
                edit_geometry = bool(getattr(getattr(helper, "data", None), "is_editmode", False))
                plane = getattr(owner, "fbp_plane_target", None) if owner else None
                owner_selected = bool(owner and owner.select_get())
                plane_selected = bool(plane and plane.select_get())
            except FBP_DATA_ERRORS:
                selected_helper = edit_geometry = owner_selected = plane_selected = False
            has_active_helper = bool(
                has_active_helper or selected_helper or edit_geometry
                or owner_selected or plane_selected
            )

            if maintenance_due:
                _ensure_helper_wire_topology(helper)
                if owner is not None and _object_mask_bounds_handles_need_repair(helper, owner):
                    ensure_object_mask_bounds_handles(helper)
            if _helper_runtime_sync_needed(pointer, helper, owner):
                sync_object_mask_helper_visibility(helper, owner=owner)
                _store_helper_runtime_signature(pointer, helper, owner)

            # Mesh depsgraph updates are the primary refresh path. Keep only a
            # throttled Edit Mode fallback for unusual tools that emit no mesh
            # update. Object transforms remain shader-driven and raster-free.
            if edit_geometry:
                last_check = float(_LAST_GEOMETRY_FALLBACK_CHECK.get(pointer, 0.0) or 0.0)
                if now - last_check >= 0.5:
                    _LAST_GEOMETRY_FALLBACK_CHECK[pointer] = now
                    _PENDING_GEOMETRY_HELPERS[pointer] = _object_record(helper)
                    try:
                        from .safe_tasks import schedule_once
                        schedule_once(
                            "object_masks.geometry_refresh",
                            _process_pending_geometry_updates,
                            first_interval=0.08,
                        )
                    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                        pass

        if not has_helpers:
            return None
        return _ACTIVE_HELPER_TIMER_SECONDS if has_active_helper else _IDLE_HELPER_TIMER_SECONDS
    except Exception as exc:
        fbp_warn("Shape Mask runtime refresh skipped", exc)
        return 0.5
    finally:
        _OBJECT_MASK_TIMER_RUNNING = False


def _process_pending_geometry_updates():
    if fbp_undo_guard_active() or fbp_render_mutation_blocked():
        return 0.20
    if not fbp_depsgraph_quiet_for(0.20):
        return 0.08
    records = tuple(_PENDING_GEOMETRY_HELPERS.values())
    _PENDING_GEOMETRY_HELPERS.clear()
    for record in records:
        helper = _resolve_object_record(record)
        if is_object_mask_helper(helper):
            refresh_object_mask_geometry(helper)
    return None


def schedule_object_mask_geometry_updates(
    scene, depsgraph=None, *, updated_meshes=None
):
    """Defer Shape Mask rasterization for meshes touched by the depsgraph.

    The main scene handler passes its already-collected mesh updates, avoiding a
    second traversal of ``depsgraph.updates``. Direct callers may still provide
    the depsgraph and use the compatibility fallback.
    """
    del scene
    if updated_meshes is None:
        try:
            updated_meshes = (
                getattr(update, "id", None)
                for update in (getattr(depsgraph, "updates", ()) or ())
            )
        except FBP_DATA_ERRORS:
            return False

    touched = False
    try:
        for datablock in updated_meshes:
            if not isinstance(datablock, bpy.types.Mesh):
                continue
            mesh_pointer = _runtime_pointer(datablock)
            helper = _resolve_object_record(_HELPER_MESH_INDEX.get(mesh_pointer))
            if helper is None:
                try:
                    if bool(datablock.get(KEY_IS_HELPER_MESH, False)):
                        helper_name = str(datablock.get(KEY_HELPER_NAME, "") or "")
                        candidate = (
                            bpy.data.objects.get(helper_name) if helper_name else None
                        )
                        if is_object_mask_helper(candidate):
                            helper = candidate
                            _register_helper_runtime(helper)
                except FBP_DATA_ERRORS:
                    helper = None
            if is_object_mask_helper(helper):
                pointer = _runtime_pointer(helper)
                _PENDING_GEOMETRY_HELPERS[pointer] = _object_record(helper)
                touched = True
    except FBP_DATA_ERRORS:
        return False
    if not touched:
        return False
    try:
        from .safe_tasks import schedule_once
        return bool(
            schedule_once(
                "object_masks.geometry_refresh",
                _process_pending_geometry_updates,
                first_interval=0.03,
            )
        )
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        return False


def remove_object_mask_helper(owner, shape, *, delete_object=True):
    shape = normalize_object_mask_shape(shape)
    helper = find_object_mask_helper(owner, shape)
    prop_name = object_mask_pointer_property(shape)
    fbp_set_rna_property_silent(owner, prop_name, None)
    if not helper:
        return False
    image = object_mask_image(helper)
    handles = object_mask_bounds_handles(helper)
    clear_object_mask_helper_tag(helper)
    if not delete_object:
        return True
    try:
        for handle in handles:
            _remove_object_mask_bounds_handle(handle)
        mesh = getattr(helper, "data", None)
        if bpy.data.objects.get(helper.name) is helper:
            bpy.data.objects.remove(helper, do_unlink=True)
        if mesh and getattr(mesh, "users", 0) == 0:
            bpy.data.meshes.remove(mesh)
        if image and bool(image.get(KEY_IS_MASK_IMAGE, False)):
            _retire_object_mask_image(image)
        return True
    except FBP_DATA_ERRORS:
        return False


def remove_object_mask_helpers_for_owner(owner):
    """Remove every helper; do not stop after deleting the first shape."""
    removed = False
    for shape in ("SQUARE", "CIRCLE", "TRIANGLE"):
        removed = remove_object_mask_helper(owner, shape) or removed
    return removed


def clear_object_mask_runtime_cache():
    global _LAST_HELPER_DISCOVERY, _LAST_HELPER_MAINTENANCE
    global _MASK_OWNER_INDEX_OBJECT_COUNT, _MASK_OWNER_INDEX_COMPLETE
    _HELPER_REGISTRY.clear()
    _HELPER_MESH_INDEX.clear()
    _HELPER_MESH_POINTERS.clear()
    _PENDING_GEOMETRY_HELPERS.clear()
    _MASK_OWNER_INDEX.clear()
    _MASK_OWNER_DUPLICATE_IDS.clear()
    _MASK_OWNER_INDEX_OBJECT_COUNT = -1
    _MASK_OWNER_INDEX_COMPLETE = False
    _LAST_GEOMETRY_FALLBACK_CHECK.clear()
    _HELPER_RUNTIME_SIGNATURES.clear()
    _LAST_HELPER_DISCOVERY = 0.0
    _LAST_HELPER_MAINTENANCE = 0.0


def audit_object_masks(rigs, *, repair=False, context=None):
    """Validate editable Shape Mask helpers and their private SDF images.

    The audit is intentionally conservative. Repair mode may recreate missing
    generated helpers, restore ownership tags, pointer properties, wire display
    state and shader bindings. It never removes duplicate helpers or orphan SDF
    images automatically because either datablock may contain user edits worth
    recovering manually.
    """
    try:
        from .geometry_nodes import (
            fbp_effect_ids_for_rig,
            fbp_object_mask_binding_issues,
            fbp_refresh_object_mask_binding,
        )
    except (ImportError, AttributeError):
        fbp_effect_ids_for_rig = None
        fbp_object_mask_binding_issues = None
        fbp_refresh_object_mask_binding = None

    rig_list = []
    seen_rigs = set()
    for rig in tuple(rigs or ()):
        if rig is None:
            continue
        try:
            key = int(rig.as_pointer())
        except FBP_DATA_ERRORS:
            key = id(rig)
        if key in seen_rigs:
            continue
        seen_rigs.add(key)
        rig_list.append(rig)
    stats = {
        "mask_effects": 0,
        "mask_helpers": 0,
        "mask_images": 0,
        "mask_handles": 0,
        "mask_orphan_handles": 0,
        "mask_missing_helpers": 0,
        "mask_orphan_helpers": 0,
        "mask_duplicate_helpers": 0,
        "mask_invalid_helpers": 0,
        "mask_missing_images": 0,
        "mask_orphan_images": 0,
        "mask_retired_images": 0,
        "mask_shared_images": 0,
        "mask_repairs": 0,
    }
    issues = []
    warnings = []

    def _object_key(obj):
        if obj is None:
            return None
        try:
            return int(obj.as_pointer())
        except FBP_DATA_ERRORS:
            return id(obj)

    def _safe_owner_id(owner):
        try:
            return str(owner.get(KEY_OWNER_RIG_ID, "") or "")
        except FBP_DATA_ERRORS:
            return ""

    def _direct_owner(helper):
        try:
            plane = getattr(helper, "parent", None)
            owner = getattr(plane, "parent", None) if plane else None
            if (
                owner
                and bool(getattr(owner, "is_fbp_control", False))
                and getattr(owner, "fbp_plane_target", None) is plane
            ):
                return owner
        except FBP_DATA_ERRORS:
            pass
        return None

    # Persistent owner IDs are the contract used to reconnect renamed rigs.
    # Check the entire .blend, not only the active scene, because duplicated IDs
    # in another scene can still make global helper discovery resolve the wrong
    # owner after a file reload.
    owners_by_id = {}
    for owner in tuple(bpy.data.objects):
        try:
            is_control = bool(getattr(owner, "is_fbp_control", False))
        except FBP_DATA_ERRORS:
            is_control = False
        if not is_control:
            continue
        owner_id = _safe_owner_id(owner)
        if owner_id:
            owners_by_id.setdefault(owner_id, []).append(owner)
    for owner_id, owners in owners_by_id.items():
        if len(owners) <= 1:
            continue
        names = ", ".join(str(getattr(owner, "name", "<rig>")) for owner in owners)
        issues.append(f"Duplicate Shape Mask owner id {owner_id}: {names}")
        if repair:
            # Keep the first owner stable and regenerate IDs for the duplicates.
            for owner in owners[1:]:
                try:
                    owner[KEY_OWNER_RIG_ID] = ""
                    if ensure_object_mask_owner_id(owner):
                        stats["mask_repairs"] += 1
                except FBP_DATA_ERRORS:
                    continue

    helpers = [
        candidate
        for candidate in tuple(bpy.data.objects)
        if is_object_mask_helper(candidate)
    ]
    stats["mask_helpers"] = len(helpers)

    handles = [
        candidate for candidate in tuple(bpy.data.objects)
        if is_object_mask_bounds_handle(candidate)
    ]
    stats["mask_handles"] = len(handles)
    for handle in handles:
        helper = find_object_mask_controller_helper(handle)
        owner = find_object_mask_controller_owner(handle)
        if helper is not None and owner is not None:
            continue
        stats["mask_orphan_handles"] += 1
        issues.append(
            f"{getattr(handle, 'name', '<handle>')}: Shape Mask bounds handle has no valid cage"
        )
        if repair and _remove_object_mask_bounds_handle(handle):
            stats["mask_repairs"] += 1

    helper_records = []
    helpers_by_owner_shape = {}
    for helper in helpers:
        helper_name = str(getattr(helper, "name", "<helper>") or "<helper>")
        contract = object_mask_contract(helper) or {}
        try:
            raw_shape = str(helper.get(KEY_SHAPE, "") or "").upper()
            raw_schema = int(helper.get(KEY_SCHEMA, 0) or 0)
        except FBP_DATA_ERRORS:
            raw_shape = ""
            raw_schema = 0
        shape = normalize_object_mask_shape(raw_shape)
        inferred = _direct_owner(helper)
        resolved_owner = find_object_mask_owner(helper)
        # Parenting is the strongest local ownership signal. Prefer it over a
        # stale duplicated UUID so repair can never move a helper onto the
        # wrong rig after duplicated controls receive fresh owner IDs.
        owner = inferred or resolved_owner
        owner_resolution_mismatch = bool(
            inferred is not None
            and resolved_owner is not None
            and inferred is not resolved_owner
        )
        if owner is None and repair:
            inferred = _direct_owner(helper)
            if inferred is not None and tag_object_mask_helper(helper, inferred, shape):
                owner = inferred
                fbp_set_rna_property_silent(
                    inferred, object_mask_pointer_property(shape), helper
                )
                stats["mask_repairs"] += 1

        if owner is None:
            stats["mask_orphan_helpers"] += 1
            issues.append(f"{helper_name}: Shape Mask helper has no valid owner")
        else:
            owner_name = str(getattr(owner, "name", "<rig>") or "<rig>")
            owner_id = _safe_owner_id(owner)
            stored_owner_id = str(contract.get("owner_id", "") or "")
            stored_owner_name = str(contract.get("owner_name", "") or "")
            if (
                owner_resolution_mismatch
                or raw_schema != FBP_OBJECT_MASK_SCHEMA_VERSION
                or raw_shape not in FBP_OBJECT_MASK_SHAPES
                or stored_owner_id != owner_id
                or stored_owner_name != owner_name
            ):
                stats["mask_invalid_helpers"] += 1
                issues.append(f"{helper_name}: stale or invalid Shape Mask ownership contract")
                if repair and tag_object_mask_helper(helper, owner, shape):
                    stats["mask_repairs"] += 1

            plane = getattr(owner, "fbp_plane_target", None)
            if plane is None:
                issues.append(f"{helper_name}: owner {owner_name} has no linked plane")
            elif getattr(helper, "parent", None) is not plane:
                issues.append(f"{helper_name}: helper is not parented to {owner_name}'s plane")
                if repair:
                    try:
                        world_matrix = helper.matrix_world.copy()
                        helper.parent = plane
                        helper.matrix_parent_inverse = plane.matrix_world.inverted_safe()
                        helper.matrix_world = world_matrix
                        stats["mask_repairs"] += 1
                    except FBP_DATA_ERRORS:
                        pass

            pointer_prop = object_mask_pointer_property(shape)
            try:
                pointer = getattr(owner, pointer_prop, None)
            except FBP_DATA_ERRORS:
                pointer = None
            if pointer is not helper:
                issues.append(f"{owner_name}: {object_mask_label(shape)} Mask pointer is not linked to {helper_name}")
                if repair:
                    if fbp_set_rna_property_silent(owner, pointer_prop, helper):
                        stats["mask_repairs"] += 1

            owner_key = _object_key(owner)
            helpers_by_owner_shape.setdefault((owner_key, shape), []).append(helper)

        mesh = getattr(helper, "data", None)
        if getattr(helper, "type", "") != "MESH" or mesh is None:
            stats["mask_invalid_helpers"] += 1
            issues.append(f"{helper_name}: Shape Mask helper is not a mesh")
        else:
            try:
                vertex_count = len(mesh.vertices)
                face_count = len(mesh.polygons)
                mesh_tagged = bool(mesh.get(KEY_IS_HELPER_MESH, False))
                mesh_helper_name = str(mesh.get(KEY_HELPER_NAME, "") or "")
                mesh_schema = int(mesh.get(KEY_SCHEMA, 0) or 0)
            except FBP_DATA_ERRORS:
                vertex_count = 0
                face_count = 0
                mesh_tagged = False
                mesh_helper_name = ""
                mesh_schema = 0
            if vertex_count < 3:
                stats["mask_invalid_helpers"] += 1
                issues.append(f"{helper_name}: Shape Mask mesh has fewer than three vertices")
            if face_count:
                stats["mask_invalid_helpers"] += 1
                issues.append(f"{helper_name}: Shape Mask control cage contains {face_count} face(s)")
            if (
                not mesh_tagged
                or mesh_helper_name != helper.name
                or mesh_schema != FBP_OBJECT_MASK_SCHEMA_VERSION
            ):
                stats["mask_invalid_helpers"] += 1
                issues.append(f"{helper_name}: Shape Mask mesh contract is stale")
            if repair and _ensure_helper_wire_topology(helper):
                stats["mask_repairs"] += 1
            if repair and owner is not None and tag_object_mask_helper(helper, owner, shape):
                # tag_object_mask_helper is idempotent; count only if the audit
                # found a stale mesh/helper contract above.
                if (
                    raw_schema != FBP_OBJECT_MASK_SCHEMA_VERSION
                    or not mesh_tagged
                    or mesh_helper_name != helper.name
                    or mesh_schema != FBP_OBJECT_MASK_SCHEMA_VERSION
                ):
                    stats["mask_repairs"] += 1

        if repair and owner is not None:
            before_handles = len(object_mask_bounds_handles(helper))
            after_handles = len(ensure_object_mask_bounds_handles(helper))
            if after_handles > before_handles:
                stats["mask_repairs"] += after_handles - before_handles

        image = object_mask_image(helper)
        if image is None:
            stats["mask_missing_images"] += 1
            issues.append(f"{helper_name}: private Shape Mask SDF image is missing")
            if repair:
                try:
                    image, _bounds, changed = ensure_object_mask_image(helper, force=True)
                    if image is not None:
                        stats["mask_repairs"] += 1 + int(bool(changed))
                except FBP_DATA_ERRORS:
                    image = None
        else:
            try:
                image_owner_id = str(image.get(KEY_OWNER_ID, "") or "")
                image_shape = str(image.get(KEY_SHAPE, "") or "").upper()
                image_tagged = bool(image.get(KEY_IS_MASK_IMAGE, False))
                image_size = tuple(int(value) for value in image.size[:2])
                helper_bounds = tuple(
                    float(value) for value in helper.get(KEY_IMAGE_BOUNDS, ()) or ()
                )
                image_bounds = tuple(
                    float(value) for value in image.get(KEY_IMAGE_BOUNDS, ()) or ()
                )
                geometry_signature = str(
                    helper.get(KEY_GEOMETRY_SIGNATURE, "") or ""
                )
            except FBP_DATA_ERRORS:
                image_owner_id = ""
                image_shape = ""
                image_tagged = False
                image_size = (0, 0)
                helper_bounds = ()
                image_bounds = ()
                geometry_signature = ""
            expected_owner_id = _safe_owner_id(owner) if owner is not None else str(contract.get("owner_id", "") or "")
            bounds_valid = bool(
                len(helper_bounds) == 4
                and len(image_bounds) == 4
                and all(math.isfinite(value) for value in helper_bounds + image_bounds)
                and all(
                    abs(first - second) <= 1.0e-7
                    for first, second in zip(helper_bounds, image_bounds, strict=True)
                )
            )
            if (
                not image_tagged
                or image_owner_id != expected_owner_id
                or image_shape != shape
                or min(image_size or (0, 0)) <= 0
                or not bounds_valid
                or geometry_signature in {"", "INVALID"}
            ):
                issues.append(f"{helper_name}: private Shape Mask SDF image contract is stale")
                if repair:
                    try:
                        image[KEY_IS_MASK_IMAGE] = True
                        image[KEY_OWNER_ID] = expected_owner_id
                        image[KEY_SHAPE] = shape
                        image.colorspace_settings.name = 'Non-Color'
                        ensure_object_mask_image(helper, force=True)
                        stats["mask_repairs"] += 1
                    except FBP_DATA_ERRORS:
                        pass

        helper_records.append((helper, owner, shape, image))

    for (owner_key, shape), matches in helpers_by_owner_shape.items():
        if len(matches) <= 1:
            continue
        stats["mask_duplicate_helpers"] += len(matches) - 1
        owner = next((record[1] for record in helper_records if _object_key(record[1]) == owner_key), None)
        owner_name = str(getattr(owner, "name", "<rig>") or "<rig>")
        names = ", ".join(str(getattr(item, "name", "<helper>")) for item in matches)
        issues.append(f"{owner_name}: duplicate {object_mask_label(shape)} Mask helpers: {names}")

    # Every active Shape Mask effect must own exactly one helper. Missing
    # generated state can be recreated safely without altering effect values.
    for rig in rig_list:
        try:
            active_effects = set(fbp_effect_ids_for_rig(rig)) if fbp_effect_ids_for_rig else set()
        except FBP_DATA_ERRORS:
            active_effects = set()
        rig_name = str(getattr(rig, "name", "<rig>") or "<rig>")
        rig_key = _object_key(rig)
        for shape in sorted(FBP_OBJECT_MASK_SHAPES):
            effect_id = object_mask_effect_id(shape)
            matches = helpers_by_owner_shape.get((rig_key, shape), [])
            if effect_id not in active_effects:
                if matches:
                    warnings.append(
                        f"{rig_name}: {object_mask_label(shape)} Mask helper remains while the effect is inactive"
                    )
                continue
            stats["mask_effects"] += 1
            if not matches:
                stats["mask_missing_helpers"] += 1
                issues.append(f"{rig_name}: active {object_mask_label(shape)} Mask has no helper")
                if repair:
                    try:
                        helper = ensure_object_mask_helper(
                            rig, shape, context=context or bpy.context, select=False
                        )
                        if helper is not None:
                            matches = [helper]
                            helpers_by_owner_shape[(rig_key, shape)] = matches
                            stats["mask_repairs"] += 1
                            refresh_object_mask_geometry(helper, force=True)
                    except FBP_DATA_ERRORS:
                        helper = None
            if repair and fbp_refresh_object_mask_binding is not None:
                try:
                    if fbp_refresh_object_mask_binding(rig, effect_id):
                        stats["mask_repairs"] += 1
                except FBP_DATA_ERRORS:
                    pass
            if fbp_object_mask_binding_issues is not None:
                try:
                    audit_helper = matches[0] if len(matches) == 1 else None
                    binding_issues = fbp_object_mask_binding_issues(
                        rig,
                        effect_id,
                        helper=audit_helper,
                        mask_image=object_mask_image(audit_helper),
                        bounds=object_mask_image_bounds(audit_helper),
                    )
                except FBP_DATA_ERRORS:
                    binding_issues = ()
                issues.extend(
                    f"{rig_name}: {object_mask_label(shape)} Mask {message}"
                    for message in binding_issues
                )

    # Zero-user quarantined private groups are deliberately retained for
    # Blender 5.2 Undo safety. Their image-node references keep retired SDF
    # buffers alive until the user runs Blender's native Orphan Purge; classify
    # those buffers as managed retirement state rather than project warnings.
    quarantined_image_keys = set()
    for node_group in tuple(bpy.data.node_groups):
        try:
            if int(getattr(node_group, "users", 0) or 0) > 0:
                continue
            if not bool(node_group.get("fbp_quarantined", False)):
                continue
            for node in tuple(getattr(node_group, "nodes", ()) or ()):
                image = getattr(node, "image", None)
                if image is not None and bool(image.get(KEY_IS_MASK_IMAGE, False)):
                    key = _object_key(image)
                    if key is not None:
                        quarantined_image_keys.add(key)
        except FBP_DATA_ERRORS:
            continue

    linked_image_keys = set()
    helpers_by_image = {}
    for helper, _owner, _shape, image in helper_records:
        key = _object_key(image)
        if key is not None:
            linked_image_keys.add(key)
            helpers_by_image.setdefault(key, []).append(helper)
    for _image_key, linked_helpers in helpers_by_image.items():
        if len(linked_helpers) <= 1:
            continue
        stats["mask_shared_images"] += 1
        names = ", ".join(
            str(getattr(helper, "name", "<helper>"))
            for helper in linked_helpers
        )
        issues.append(
            f"Private Shape Mask SDF image is shared by multiple helpers: {names}"
        )
    for image in tuple(bpy.data.images):
        try:
            is_mask_image = bool(image.get(KEY_IS_MASK_IMAGE, False))
        except FBP_DATA_ERRORS:
            is_mask_image = False
        if not is_mask_image:
            continue
        stats["mask_images"] += 1
        image_key = _object_key(image)
        if image_key not in linked_image_keys:
            stats["mask_orphan_images"] += 1
            if image_key in quarantined_image_keys or _object_mask_image_is_retiring(image):
                stats["mask_retired_images"] += 1
                continue
            warnings.append(
                f"Unused or detached Shape Mask SDF image: {getattr(image, 'name', '<image>')}"
            )

    # Keep the runtime cache in sync after repair so the next UI draw or timer
    # does not need a global discovery pass.
    if repair:
        _discover_object_mask_helpers(force=True)

    return {
        "stats": stats,
        "issues": issues,
        "warnings": warnings,
        "repaired": int(stats["mask_repairs"]),
    }


def register():
    register_shape_mask_driver_namespace()


def unregister():
    unregister_shape_mask_driver_namespace()


__all__ = [
    "FBP_OBJECT_MASK_SCHEMA_VERSION",
    "FBP_OBJECT_MASK_SHAPES",
    "normalize_object_mask_shape",
    "object_mask_label",
    "object_mask_effect_id",
    "object_mask_pointer_property",
    "object_mask_follow_property",
    "object_mask_show_property",
    "object_mask_lock_property",
    "object_mask_external_null_property",
    "ensure_object_mask_owner_id",
    "is_object_mask_helper",
    "is_object_mask_bounds_handle",
    "is_object_mask_controller",
    "object_mask_controller_shape",
    "find_object_mask_controller_owner",
    "find_object_mask_controller_helper",
    "tag_object_mask_helper",
    "clear_object_mask_helper_tag",
    "object_mask_contract",
    "find_object_mask_owner",
    "find_object_mask_helper",
    "create_object_mask_helper",
    "ensure_object_mask_helper",
    "object_mask_bounds_handles",
    "ensure_object_mask_bounds_handles",
    "sync_object_mask_bounds_handles",
    "apply_object_mask_bounds_handle",
    "apply_object_mask_bounds_handles",
    "schedule_object_mask_bounds_handle_update",
    "schedule_object_mask_helper_transform_update",
    "sync_object_mask_helper_to_bounds",
    "sync_owner_object_mask_helpers",
    "sync_object_mask_helper_visibility",
    "register_shape_mask_driver_namespace",
    "unregister_shape_mask_driver_namespace",
    "ensure_shape_mask_external_null_drivers",
    "sync_shape_mask_external_null",
    "sync_circle_mask_external_null",
    "sync_external_shape_mask_targets",
    "sync_external_circle_mask_targets",
    "make_object_mask_shape_perfect",
    "clone_object_mask_helpers",
    "sync_owner_object_mask_runtime",
    "object_mask_image",
    "object_mask_image_bounds",
    "ensure_object_mask_image",
    "refresh_object_mask_geometry",
    "schedule_object_mask_geometry_updates",
    "object_mask_runtime_timer",
    "object_mask_runtime_service_required",
    "sync_all_object_mask_runtime",
    "remove_object_mask_helper",
    "remove_object_mask_helpers_for_owner",
    "clear_object_mask_runtime_cache",
    "audit_object_masks",
]
