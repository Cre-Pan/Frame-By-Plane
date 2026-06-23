"""Editable object-backed Shape Masks for Frame By Plane.

Each mask owns a lightweight wire helper parented to the generated image plane.
The helper transform drives placement while its editable mesh is rasterized into
an in-memory signed-distance image. Shader nodes sample that image in helper
local space, so Edit Mode vertex changes affect the real mask rather than only
the viewport outline.

Runtime work is deliberately demand-driven:
- transforms require no Python updates;
- geometry is rasterized only when its local mesh signature changes;
- visibility checks iterate only known helper names;
- depsgraph callbacks schedule safe timer work instead of mutating datablocks.
"""

from __future__ import annotations

from array import array
import math
import time
import uuid

import bpy
from mathutils import Matrix

try:
    import bmesh
except ImportError:  # Blender always provides bmesh; keep import-time resilience.
    bmesh = None

from .runtime import (
    FBP_DATA_ERRORS,
    fbp_render_mutation_blocked,
    fbp_set_rna_property_silent,
    fbp_undo_guard_active,
    fbp_warn,
)

FBP_OBJECT_MASK_SCHEMA_VERSION = 4
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
_EFFECT_IDS = {
    "SQUARE": "SQUARE_MASK",
    "CIRCLE": "CIRCLE_MASK",
    "TRIANGLE": "TRIANGLE_MASK",
}

_HELPER_NAMES = globals().get("_HELPER_NAMES", set())
_PENDING_GEOMETRY_HELPERS = globals().get("_PENDING_GEOMETRY_HELPERS", set())
_LAST_HELPER_DISCOVERY = float(globals().get("_LAST_HELPER_DISCOVERY", 0.0) or 0.0)
_NUMPY = globals().get("_NUMPY", None)
_NUMPY_CHECKED = bool(globals().get("_NUMPY_CHECKED", False))
_LAST_GEOMETRY_FALLBACK_CHECK = globals().get("_LAST_GEOMETRY_FALLBACK_CHECK", {})
if not isinstance(_LAST_GEOMETRY_FALLBACK_CHECK, dict):
    _LAST_GEOMETRY_FALLBACK_CHECK = {}


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


def ensure_object_mask_owner_id(owner):
    """Return a unique persistent UUID stored on the owning FBP rig."""
    if not owner:
        return ""
    try:
        owner_id = str(owner.get(KEY_OWNER_RIG_ID, "") or "")
        if owner_id:
            for candidate in bpy.data.objects:
                if candidate is owner:
                    continue
                try:
                    if (
                        bool(getattr(candidate, "is_fbp_control", False))
                        and str(candidate.get(KEY_OWNER_RIG_ID, "") or "") == owner_id
                    ):
                        owner_id = ""
                        break
                except FBP_DATA_ERRORS:
                    continue
        if not owner_id:
            owner_id = uuid.uuid4().hex
            owner[KEY_OWNER_RIG_ID] = owner_id
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


def tag_object_mask_helper(obj, owner, shape):
    if not obj or not owner:
        return False
    owner_id = ensure_object_mask_owner_id(owner)
    if not owner_id:
        return False
    shape = normalize_object_mask_shape(shape)
    try:
        obj[KEY_IS_HELPER] = True
        obj[KEY_SCHEMA] = FBP_OBJECT_MASK_SCHEMA_VERSION
        obj[KEY_SHAPE] = shape
        obj[KEY_OWNER_NAME] = str(getattr(owner, "name", "") or "")
        obj[KEY_OWNER_ID] = owner_id
        mesh = getattr(obj, "data", None)
        if mesh is not None:
            mesh[KEY_IS_HELPER_MESH] = True
            mesh[KEY_HELPER_NAME] = obj.name
            mesh[KEY_SCHEMA] = FBP_OBJECT_MASK_SCHEMA_VERSION
        _HELPER_NAMES.add(obj.name)
        return True
    except FBP_DATA_ERRORS:
        return False


def clear_object_mask_helper_tag(obj):
    if not obj:
        return False
    changed = False
    helper_name = str(getattr(obj, "name", "") or "")
    _HELPER_NAMES.discard(helper_name)
    _LAST_GEOMETRY_FALLBACK_CHECK.pop(helper_name, None)
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
        for point in tuple(getattr(plane, "bound_box", ()) or ()):
            points.append((float(point[0]), float(point[1])))
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


def find_object_mask_owner(helper):
    contract = object_mask_contract(helper) or {}
    owner_id = str(contract.get("owner_id", "") or "")
    owner_name = str(contract.get("owner_name", "") or "")

    # The helper is parented to the plane, which is parented to the rig. Resolve
    # that direct relationship first: it is O(1), survives rig renames and
    # avoids a global bpy.data.objects scan in the visibility timer.
    try:
        plane = getattr(helper, "parent", None)
        direct_owner = getattr(plane, "parent", None) if plane else None
        if direct_owner and bool(getattr(direct_owner, "is_fbp_control", False)):
            if not owner_id or str(direct_owner.get(KEY_OWNER_RIG_ID, "") or "") == owner_id:
                return direct_owner
    except FBP_DATA_ERRORS:
        pass

    candidate = bpy.data.objects.get(owner_name) if owner_name else None
    try:
        if candidate and bool(getattr(candidate, "is_fbp_control", False)):
            if str(candidate.get(KEY_OWNER_RIG_ID, "") or "") == owner_id:
                return candidate
    except FBP_DATA_ERRORS:
        pass
    if not owner_id:
        return None
    for candidate in bpy.data.objects:
        try:
            if (
                bool(getattr(candidate, "is_fbp_control", False))
                and str(candidate.get(KEY_OWNER_RIG_ID, "") or "") == owner_id
            ):
                return candidate
        except FBP_DATA_ERRORS:
            continue
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
        _HELPER_NAMES.add(helper.name)
        return helper
    plane = getattr(owner, "fbp_plane_target", None)
    try:
        candidates = tuple(getattr(plane, "children", ()) or ()) if plane else ()
    except FBP_DATA_ERRORS:
        candidates = ()
    for candidate in candidates:
        if _helper_matches_owner(candidate, owner, shape):
            fbp_set_rna_property_silent(owner, prop_name, candidate)
            _HELPER_NAMES.add(candidate.name)
            return candidate
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

    Versions up to 5.5.10 created one polygon face. Blender displays that face
    in Edit Mode even when the object display type is Wire, making the helper
    appear black and hiding the plane underneath. This migration is safe for
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
        # viewport shading mode. These flags are cheap to repair and can be
        # changed accidentally by users or older files.
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


def create_object_mask_helper(owner, shape, context=None, *, select=True):
    shape = normalize_object_mask_shape(shape)
    existing = find_object_mask_helper(owner, shape)
    if existing:
        return existing
    plane, bounds = _plane_bounds(owner)
    if not plane:
        return None
    label = object_mask_label(shape)
    mesh = _shape_mesh(shape, f"FBP {label} Mask Mesh • {owner.name}")
    helper = bpy.data.objects.new(f"FBP {label} Mask • {owner.name}", mesh)
    _link_helper(helper, plane, context=context)
    try:
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
    except FBP_DATA_ERRORS:
        pass
    tag_object_mask_helper(helper, owner, shape)
    _ensure_helper_wire_topology(helper)
    _store_bounds(helper, bounds)
    _apply_helper_lock(owner, helper, shape)
    fbp_set_rna_property_silent(owner, object_mask_pointer_property(shape), helper)
    try:
        ensure_object_mask_image(helper, force=True)
    except Exception as exc:
        fbp_warn("Could not initialize editable Shape Mask image", exc)
    if select:
        try:
            bpy.ops.object.select_all(action='DESELECT')
        except FBP_DATA_ERRORS:
            pass
        try:
            owner.select_set(True)
            helper.select_set(True)
            view_layer = getattr(context, "view_layer", None) if context else getattr(bpy.context, "view_layer", None)
            if view_layer:
                view_layer.objects.active = helper
        except FBP_DATA_ERRORS:
            pass
    sync_object_mask_helper_visibility(helper, owner=owner)
    return helper


def ensure_object_mask_helper(owner, shape, context=None, *, select=False):
    helper = find_object_mask_helper(owner, shape)
    if helper is None:
        return create_object_mask_helper(owner, shape, context=context, select=select)
    tag_object_mask_helper(helper, owner, shape)
    _ensure_helper_wire_topology(helper)
    _apply_helper_lock(owner, helper, shape)
    if select:
        try:
            bpy.ops.object.select_all(action='DESELECT')
        except FBP_DATA_ERRORS:
            pass
        try:
            owner.select_set(True)
            helper.select_set(True)
            view_layer = getattr(context, "view_layer", None) if context else getattr(bpy.context, "view_layer", None)
            if view_layer:
                view_layer.objects.active = helper
        except FBP_DATA_ERRORS:
            pass
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
    signed = np.where(inside, distance, -distance)
    encoded = np.clip(0.5 + signed / scale, 0.0, 1.0).astype(np.float32)
    rgba = np.repeat(encoded[:, :, np.newaxis], 4, axis=2)
    return rgba.reshape(-1)


def _point_inside_polygon(x, y, points):
    inside = False
    previous = points[-1]
    for current in points:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            intersection = (x2 - x1) * (y - y1) / ((y2 - y1) or 1.0e-12) + x1
            if x < intersection:
                inside = not inside
        previous = current
    return inside


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
    pixels = array('f')
    for row in range(resolution):
        y = min_y + (max_y - min_y) * (row / max(1, resolution - 1))
        for column in range(resolution):
            x = min_x + (max_x - min_x) * (column / max(1, resolution - 1))
            distance = _distance_to_segments(x, y, points)
            signed = distance if _point_inside_polygon(x, y, points) else -distance
            encoded = max(0.0, min(1.0, 0.5 + signed / scale))
            pixels.extend((encoded, encoded, encoded, encoded))
    return pixels


def _mask_image_for_helper(helper, resolution):
    """Return ``(image, needs_pixels)`` for this helper's private SDF image."""
    needs_pixels = False
    try:
        image_name = str(helper.get(KEY_IMAGE_NAME, "") or "")
    except FBP_DATA_ERRORS:
        image_name = ""
    image = bpy.data.images.get(image_name) if image_name else None
    if image is not None:
        try:
            if tuple(int(value) for value in image.size[:2]) != (resolution, resolution):
                image.scale(resolution, resolution)
                needs_pixels = True
        except FBP_DATA_ERRORS:
            image = None
    if image is None:
        contract = object_mask_contract(helper) or {}
        owner_token = str(contract.get("owner_id", "") or uuid.uuid4().hex)[:12]
        shape = normalize_object_mask_shape(contract.get("shape", "SQUARE"))
        image_name = f"FBP {object_mask_label(shape)} Mask SDF • {owner_token}"
        image = bpy.data.images.get(image_name)
        if image is None:
            image = bpy.data.images.new(
                image_name,
                width=resolution,
                height=resolution,
                alpha=True,
                float_buffer=False,
            )
            needs_pixels = True
        else:
            try:
                if tuple(int(value) for value in image.size[:2]) != (resolution, resolution):
                    image.scale(resolution, resolution)
                    needs_pixels = True
            except FBP_DATA_ERRORS:
                pass
        try:
            image[KEY_IS_MASK_IMAGE] = True
            image[KEY_OWNER_ID] = str(contract.get("owner_id", "") or "")
            image[KEY_SHAPE] = shape
            image.colorspace_settings.name = 'Non-Color'
        except FBP_DATA_ERRORS:
            pass
        try:
            helper[KEY_IMAGE_NAME] = image.name
        except FBP_DATA_ERRORS:
            pass
    return image, needs_pixels


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
    signature = _geometry_signature(points)
    try:
        old_signature = str(helper.get(KEY_GEOMETRY_SIGNATURE, "") or "")
    except FBP_DATA_ERRORS:
        old_signature = ""
    np = _numpy_module()
    resolution = FBP_OBJECT_MASK_RESOLUTION if np is not None else FBP_OBJECT_MASK_FALLBACK_RESOLUTION
    image, needs_pixels = _mask_image_for_helper(helper, resolution)
    bounds = _polygon_raster_bounds(points)
    if not force and not needs_pixels and signature == old_signature and image is not None:
        return image, object_mask_image_bounds(helper, bounds), False

    pixels = (
        _rasterize_sdf_numpy(points, bounds, resolution, np)
        if np is not None
        else _rasterize_sdf_fallback(points, bounds, resolution)
    )
    try:
        image.pixels.foreach_set(pixels)
        image.update()
        image[KEY_IMAGE_BOUNDS] = [float(value) for value in bounds]
        helper[KEY_IMAGE_BOUNDS] = [float(value) for value in bounds]
        helper[KEY_GEOMETRY_SIGNATURE] = signature
        helper[KEY_SCHEMA] = FBP_OBJECT_MASK_SCHEMA_VERSION
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


def sync_object_mask_helper_visibility(helper, *, owner=None):
    if not is_object_mask_helper(helper):
        return False
    owner = owner or find_object_mask_owner(helper)
    contract = object_mask_contract(helper) or {}
    shape = normalize_object_mask_shape(contract.get("shape", "SQUARE"))
    plane = getattr(owner, "fbp_plane_target", None) if owner else getattr(helper, "parent", None)
    try:
        show_preference = bool(getattr(owner, object_mask_show_property(shape), True)) if owner else True
        selected = bool(
            (owner and owner.select_get())
            or (plane and plane.select_get())
            or helper.select_get()
            or bool(getattr(getattr(helper, "data", None), "is_editmode", False))
        )
        should_hide = not (show_preference and selected)
        # Hiding the object while Blender owns an Edit Mesh can invalidate the
        # current tool state. Defer the hide until Edit Mode exits.
        if bool(getattr(getattr(helper, "data", None), "is_editmode", False)):
            should_hide = False
        hidden_now = bool(helper.hide_get())
        changed = False
        if hidden_now != should_hide:
            helper.hide_set(should_hide)
            changed = True
        changed = _apply_helper_lock(owner, helper, shape) or changed
        # Vertex depth only needs policing while the cage is being edited.
        # Object-mode/scripted mesh changes are handled once by the geometry
        # refresh path, avoiding a full vertex loop for every hidden helper on
        # every visibility-timer tick.
        mesh = getattr(helper, "data", None)
        if bool(getattr(mesh, "is_editmode", False)):
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
    if not force and _HELPER_NAMES and now - _LAST_HELPER_DISCOVERY < 15.0:
        return
    if not force and not _HELPER_NAMES and now - _LAST_HELPER_DISCOVERY < 2.0:
        return
    _LAST_HELPER_DISCOVERY = now
    stale = set(_HELPER_NAMES)
    for candidate in bpy.data.objects:
        if is_object_mask_helper(candidate):
            _HELPER_NAMES.add(candidate.name)
            stale.discard(candidate.name)
    for name in stale:
        if bpy.data.objects.get(name) is None:
            _HELPER_NAMES.discard(name)
            _LAST_GEOMETRY_FALLBACK_CHECK.pop(name, None)


def object_mask_runtime_timer():
    """Keep helper visibility/locks responsive and refresh edited geometry."""
    if fbp_undo_guard_active() or fbp_render_mutation_blocked():
        return 0.5
    try:
        _discover_object_mask_helpers()
        has_helpers = False
        has_active_helper = False
        for name in tuple(_HELPER_NAMES):
            helper = bpy.data.objects.get(name)
            if helper is None or not is_object_mask_helper(helper):
                _HELPER_NAMES.discard(name)
                _LAST_GEOMETRY_FALLBACK_CHECK.pop(name, None)
                continue
            has_helpers = True
            # Perform legacy face removal and display repair from the runtime
            # service rather than from UI lookup functions. Blender panel draw
            # callbacks must stay read-only.
            _ensure_helper_wire_topology(helper)
            owner = find_object_mask_owner(helper)
            sync_object_mask_helper_visibility(helper, owner=owner)
            try:
                selected_helper = bool(helper.select_get())
                edit_geometry = bool(getattr(getattr(helper, "data", None), "is_editmode", False))
            except FBP_DATA_ERRORS:
                selected_helper = False
                edit_geometry = False
            if selected_helper or edit_geometry:
                has_active_helper = True
            # Mesh depsgraph updates are the primary refresh path. Keep only a
            # throttled Edit Mode fallback for unusual tool operations that do
            # not emit a mesh update, instead of rerasterizing every selected
            # helper eight times per second. Object Mode transforms need no
            # rasterization because the shader samples helper object space.
            if edit_geometry:
                now = time.monotonic()
                helper_key = str(getattr(helper, "name", "") or "")
                last_check = float(_LAST_GEOMETRY_FALLBACK_CHECK.get(helper_key, 0.0) or 0.0)
                if now - last_check >= 0.5:
                    _LAST_GEOMETRY_FALLBACK_CHECK[helper_key] = now
                    refresh_object_mask_geometry(helper)
            elif owner is not None:
                try:
                    plane = getattr(owner, "fbp_plane_target", None)
                    has_active_helper = bool(owner.select_get() or (plane and plane.select_get())) or has_active_helper
                except FBP_DATA_ERRORS:
                    pass
        if not has_helpers:
            return 1.0
        return 0.12 if has_active_helper else 0.4
    except Exception as exc:
        fbp_warn("Shape Mask runtime refresh skipped", exc)
        return 0.5


def _process_pending_geometry_updates():
    names = tuple(_PENDING_GEOMETRY_HELPERS)
    _PENDING_GEOMETRY_HELPERS.clear()
    for name in names:
        helper = bpy.data.objects.get(name)
        if helper and is_object_mask_helper(helper):
            refresh_object_mask_geometry(helper)
    return None


def schedule_object_mask_geometry_updates(scene, depsgraph):
    """Inspect depsgraph updates and defer helper rasterization to a safe timer."""
    del scene
    touched = False
    try:
        for update in tuple(getattr(depsgraph, "updates", ()) or ()):
            datablock = getattr(update, "id", None)
            helper_name = ""
            # Helper object transforms are consumed directly by shader Object
            # coordinates and must not trigger an SDF rebuild. Only mesh edits
            # change the silhouette and therefore enter the deferred queue.
            if isinstance(datablock, bpy.types.Mesh):
                try:
                    if bool(datablock.get(KEY_IS_HELPER_MESH, False)):
                        helper_name = str(datablock.get(KEY_HELPER_NAME, "") or "")
                except FBP_DATA_ERRORS:
                    helper_name = ""
            if helper_name and bpy.data.objects.get(helper_name):
                _PENDING_GEOMETRY_HELPERS.add(helper_name)
                touched = True
    except FBP_DATA_ERRORS:
        return False
    if not touched:
        return False
    try:
        from .safe_tasks import schedule_once
        return bool(schedule_once(
            "object_masks.geometry_refresh",
            _process_pending_geometry_updates,
            first_interval=0.03,
        ))
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
    clear_object_mask_helper_tag(helper)
    if not delete_object:
        return True
    try:
        mesh = getattr(helper, "data", None)
        if bpy.data.objects.get(helper.name) is helper:
            bpy.data.objects.remove(helper, do_unlink=True)
        if mesh and getattr(mesh, "users", 0) == 0:
            bpy.data.meshes.remove(mesh)
        if image and getattr(image, "users", 0) == 0 and bool(image.get(KEY_IS_MASK_IMAGE, False)):
            bpy.data.images.remove(image)
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
    global _LAST_HELPER_DISCOVERY
    _HELPER_NAMES.clear()
    _PENDING_GEOMETRY_HELPERS.clear()
    _LAST_GEOMETRY_FALLBACK_CHECK.clear()
    _LAST_HELPER_DISCOVERY = 0.0


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
        "mask_missing_helpers": 0,
        "mask_orphan_helpers": 0,
        "mask_duplicate_helpers": 0,
        "mask_invalid_helpers": 0,
        "mask_missing_images": 0,
        "mask_orphan_images": 0,
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

    helpers = []
    for candidate in tuple(bpy.data.objects):
        if is_object_mask_helper(candidate):
            helpers.append(candidate)
    stats["mask_helpers"] = len(helpers)

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

    linked_image_keys = set()
    helpers_by_image = {}
    for helper, _owner, _shape, image in helper_records:
        key = _object_key(image)
        if key is not None:
            linked_image_keys.add(key)
            helpers_by_image.setdefault(key, []).append(helper)
    for image_key, linked_helpers in helpers_by_image.items():
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
        if _object_key(image) not in linked_image_keys:
            stats["mask_orphan_images"] += 1
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
    "ensure_object_mask_owner_id",
    "is_object_mask_helper",
    "tag_object_mask_helper",
    "clear_object_mask_helper_tag",
    "object_mask_contract",
    "find_object_mask_owner",
    "find_object_mask_helper",
    "create_object_mask_helper",
    "ensure_object_mask_helper",
    "sync_object_mask_helper_to_bounds",
    "sync_owner_object_mask_helpers",
    "sync_object_mask_helper_visibility",
    "sync_owner_object_mask_runtime",
    "object_mask_image",
    "object_mask_image_bounds",
    "ensure_object_mask_image",
    "refresh_object_mask_geometry",
    "schedule_object_mask_geometry_updates",
    "object_mask_runtime_timer",
    "remove_object_mask_helper",
    "remove_object_mask_helpers_for_owner",
    "clear_object_mask_runtime_cache",
    "audit_object_masks",
]
