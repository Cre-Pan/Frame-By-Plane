"""Geometry, rig-building, fit-to-camera and extension helpers."""

import bpy
import math
import mathutils
import os

from .path_utils import natural_sort_key
from .pillow_media import (
    FBP_PILLOW_CONVERT_EXTENSIONS,
    fbp_default_pillow_cache_root,
    fbp_prepare_pillow_media,
)
from .materials import (
    fbp_rebuild_color_plane_material,
)


# SECTION 01 - Shared runtime helpers #
from .runtime import fbp_warn as _fbp_warn, fbp_set_rna_property_silent, fbp_creation_start_frame, FBP_DATA_ERRORS, FBP_DATA_IO_ERRORS


FBP_CROP_EXTEND_CONTRACT_VERSION = 3


# SECTION 02 - Mesh / Object creation #


def fbp_scene_orientation_is_horizontal(scene):
    """Return True only for the explicit Horizontal creation preset.

    Only the current enum token is accepted; unknown values fall back to Vertical.
    """
    value = str(getattr(scene, 'fbp_pre_orientation', 'VERT') or 'VERT').upper()
    return value == 'HORIZ'


def fbp_apply_creation_orientation(rig, scene):
    """Apply the requested creation orientation to a newly created rig."""
    if not rig:
        return False
    if fbp_scene_orientation_is_horizontal(scene):
        rig.rotation_euler = (0.0, 0.0, 0.0)
        rig.fbp_is_vertical = False
    else:
        rig.rotation_euler = (math.radians(90), 0.0, 0.0)
        rig.fbp_is_vertical = True
    return True

def camera_ratio_scale(context):
    """Return local XY scale matching the active render/camera ratio."""
    sc = context.scene if context else bpy.context.scene
    rx = max(1, int(getattr(sc.render, "resolution_x", 1920)))
    ry = max(1, int(getattr(sc.render, "resolution_y", 1080)))
    aspect = rx / ry
    if aspect >= 1.0:
        return (aspect, 1.0, 1.0)
    return (1.0, 1.0 / aspect, 1.0)

def fbp_link_object(obj, context, target_collection=None):
    """Link an object without bpy.ops so import also works outside a 3D View context."""
    collection = target_collection or getattr(context, "collection", None) or context.scene.collection
    collection.objects.link(obj)
    return obj

def fbp_ensure_render_uv_map(mesh, name="UVMap"):
    """Return the named UV map and make it Blender 5.2's render UV map.

    Blender 5.2 exposes an explicit render-active UV pointer/index on the
    collection. Keeping it aligned prevents Crop/Extend from looking correct in
    the viewport while shaders or render jobs sample a different UV layer.
    """
    if mesh is None:
        return None
    try:
        layers = mesh.uv_layers
        uv_name = str(name or "UVMap")
        layer = layers.get(uv_name)
        if layer is None:
            layer = layers.new(name=uv_name)
        if layer is None:
            return None
        try:
            layers.active = layer
        except FBP_DATA_IO_ERRORS:
            pass
        try:
            index = int(layers.find(layer.name))
        except FBP_DATA_IO_ERRORS:
            index = -1
        if index >= 0:
            try:
                layers.active_index = index
            except FBP_DATA_IO_ERRORS:
                pass
            try:
                layers.active_render_index = index
            except FBP_DATA_IO_ERRORS:
                pass
        try:
            layers.active_render = layer
        except FBP_DATA_IO_ERRORS:
            pass
        try:
            layer.active_render = True
        except FBP_DATA_IO_ERRORS:
            pass
        return layer
    except FBP_DATA_IO_ERRORS:
        return None


def fbp_create_rect_mesh(name, size=2.0, with_face=True):
    """Create a rectangular FBP mesh through the Data API.

    with_face=False is used for the control rig wire rectangle.
    with_face=True is used for the renderable plane and receives a UV map.
    """
    half = float(size) * 0.5
    verts = [(-half, -half, 0.0), (half, -half, 0.0), (half, half, 0.0), (-half, half, 0.0)]
    edges = [] if with_face else [(0, 1), (1, 2), (2, 3), (3, 0)]
    faces = [(0, 1, 2, 3)] if with_face else []
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, edges, faces)
    mesh.update()
    if with_face:
        uv_layer = fbp_ensure_render_uv_map(mesh, "UVMap")
        coords = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
        if mesh.polygons:
            for loop_index, uv in zip(mesh.polygons[0].loop_indices, coords, strict=True):
                uv_layer.data[loop_index].uv = uv
    return mesh


def _fbp_rig_shape_geometry(shape, size=2.1, *, half_extents=None, center=(0.0, 0.0)):
    """Return local XY wire geometry for a non-rendering FBP control rig."""
    shape = str(shape or "DEFAULT").upper()
    if shape == "DEFAULT":
        shape = "RECTANGLE"
    radius = max(0.0001, float(size) * 0.5)
    if shape == "CIRCLE":
        count = 32
        verts = [
            (math.cos((math.tau * index) / count) * radius,
             math.sin((math.tau * index) / count) * radius,
             0.0)
            for index in range(count)
        ]
    elif shape == "DIAMOND":
        verts = [(0.0, radius, 0.0), (radius, 0.0, 0.0), (0.0, -radius, 0.0), (-radius, 0.0, 0.0)]
    elif shape == "HEXAGON":
        count = 6
        verts = [
            (math.cos((math.tau * index) / count) * radius,
             math.sin((math.tau * index) / count) * radius,
             0.0)
            for index in range(count)
        ]
    elif shape == "OCTAGON":
        count = 8
        verts = [
            (math.cos((math.tau * index) / count + math.pi / 8.0) * radius,
             math.sin((math.tau * index) / count + math.pi / 8.0) * radius,
             0.0)
            for index in range(count)
        ]
    else:
        verts = [(-radius, -radius, 0.0), (radius, -radius, 0.0), (radius, radius, 0.0), (-radius, radius, 0.0)]
    if half_extents is not None:
        hx, hy = half_extents
        hx = max(0.0001, float(hx))
        hy = max(0.0001, float(hy))
        verts = [(x / radius * hx, y / radius * hy, z) for x, y, z in verts]
    cx, cy = center
    if cx or cy:
        verts = [(x + float(cx), y + float(cy), z) for x, y, z in verts]
    edges = [(index, (index + 1) % len(verts)) for index in range(len(verts))]
    return verts, edges



def fbp_rig_shape_margin(rig):
    """Return the controller border in plane-local units."""
    try:
        expand = max(0.0, min(2.0, float(getattr(rig, "fbp_rig_shape_expand", 1.0) or 0.0)))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        expand = 1.0
    return 0.05 * expand

def fbp_apply_rig_shape(rig, shape=None, *, size=2.1):
    """Replace only the control-rig wire mesh, preserving plane/media/effects."""
    if rig is None or not bool(getattr(rig, "is_fbp_control", False)):
        return False
    shape = str(shape or getattr(rig, "fbp_rig_shape", "DEFAULT") or "DEFAULT").upper()
    if shape == "CUSTOM":
        return False
    mesh = getattr(rig, "data", None)
    if mesh is None or not isinstance(mesh, bpy.types.Mesh):
        return False
    try:
        # Editing the wire manually remains valid. Presets are applied only when
        # the user explicitly chooses one from the rig panel in Object Mode.
        if str(getattr(rig, "mode", "OBJECT") or "OBJECT") != "OBJECT":
            return False
        fit_mode = str(getattr(rig, "fbp_rig_shape_fit_mode", "FIT_PLANE") or "FIT_PLANE").upper()
        half_extents = None
        center = (0.0, 0.0)
        margin = fbp_rig_shape_margin(rig)
        if fit_mode == "FIT_PLANE" or shape == "DEFAULT":
            plane = getattr(rig, "fbp_plane_target", None)
            coords = tuple(getattr(getattr(plane, "data", None), "vertices", ()) or ())
            if coords:
                xs = [float(vertex.co.x) for vertex in coords]
                ys = [float(vertex.co.y) for vertex in coords]
                half_extents = (
                    max(0.0001, (max(xs) - min(xs)) * 0.5 + margin),
                    max(0.0001, (max(ys) - min(ys)) * 0.5 + margin),
                )
                center = ((max(xs) + min(xs)) * 0.5, (max(ys) + min(ys)) * 0.5)
            else:
                aspect_x, aspect_y = fbp_native_aspect_half_extents(rig)
                half_extents = (
                    max(0.0001, aspect_x + margin),
                    max(0.0001, aspect_y + margin),
                )
        shape_size = max(0.0002, 2.0 + margin * 2.0)
        verts, edges = _fbp_rig_shape_geometry(shape, size=shape_size, half_extents=half_extents, center=center)
        mesh.clear_geometry()
        mesh.from_pydata(verts, edges, [])
        mesh.update()
        mesh["fbp_rig_shape"] = shape
        mesh["fbp_rig_shape_fit_mode"] = fit_mode
        rig.update_tag()
        return True
    except Exception as exc:
        _fbp_warn("Could not apply Frame By Plane rig shape", exc)
        return False

def _fbp_aspect_from_plane_image(rig):
    plane = getattr(rig, "fbp_plane_target", None) if rig else None
    if not plane or not getattr(plane, "data", None):
        return None
    try:
        for mat in plane.data.materials:
            if not mat:
                continue
            try:
                width = float(mat.get("fbp_source_width", 0.0))
                height = float(mat.get("fbp_source_height", 0.0))
                if width > 0.0 and height > 0.0:
                    if width >= height:
                        return 1.0, max(height / width, 0.0001), int(width), int(height)
                    return max(width / height, 0.0001), 1.0, int(width), int(height)
            except FBP_DATA_IO_ERRORS:
                pass
            if not getattr(mat, "node_tree", None):
                continue
            for node in mat.node_tree.nodes:
                if getattr(node, "type", None) != 'TEX_IMAGE':
                    continue
                img = getattr(node, "image", None)
                if not img:
                    continue
                width, height = img.size
                width = float(width)
                height = float(height)
                if width > 0.0 and height > 0.0:
                    if width >= height:
                        return 1.0, max(height / width, 0.0001), int(width), int(height)
                    return max(width / height, 0.0001), 1.0, int(width), int(height)
    except FBP_DATA_IO_ERRORS:
        pass
    return None

def fbp_native_aspect_half_extents(rig):
    """Return normalized half-extents for native image planes.

    Procedural FBP layers keep their image aspect in the rig scale. Native layers
    bake the aspect into the generated plane/frame mesh instead, so crop and
    extend operate on the real visible rectangle and the controller does not
    appear square while the material is correct.
    """
    if not rig:
        return 1.0, 1.0
    try:
        if not bool(rig.get("fbp_native_backend", False)):
            return 1.0, 1.0
    except FBP_DATA_ERRORS:
        return 1.0, 1.0
    material_aspect = _fbp_aspect_from_plane_image(rig)
    try:
        ax = float(rig.get("fbp_native_aspect_x", 0.0))
        ay = float(rig.get("fbp_native_aspect_y", 0.0))
        src_w = float(rig.get("fbp_source_width", 0.0))
        src_h = float(rig.get("fbp_source_height", 0.0))
        # Keep cached dimensions consistent with the current source image.
        # Comparing the actual aspect avoids rewriting valid square-image data
        # every time Crop, Extend or Fit queries the plane bounds.
        if material_aspect:
            real_ax, real_ay, width, height = material_aspect
            cache_mismatch = (
                src_w <= 0.0
                or src_h <= 0.0
                or ax <= 0.0
                or ay <= 0.0
                or abs(ax - real_ax) > 1e-6
                or abs(ay - real_ay) > 1e-6
                or abs(src_w - float(width)) > 0.5
                or abs(src_h - float(height)) > 0.5
            )
            if cache_mismatch:
                ax, ay = real_ax, real_ay
                try:
                    rig["fbp_source_width"] = int(width)
                    rig["fbp_source_height"] = int(height)
                    rig["fbp_native_aspect_x"] = float(ax)
                    rig["fbp_native_aspect_y"] = float(ay)
                except FBP_DATA_IO_ERRORS:
                    pass
                return ax, ay
        if ax > 0.0 and ay > 0.0:
            return ax, ay
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        width = float(rig.get("fbp_source_width", 0.0))
        height = float(rig.get("fbp_source_height", 0.0))
        if width > 0.0 and height > 0.0:
            if width >= height:
                return 1.0, max(height / width, 0.0001)
            return max(width / height, 0.0001), 1.0
    except FBP_DATA_IO_ERRORS:
        pass
    if material_aspect:
        return material_aspect[0], material_aspect[1]
    return 1.0, 1.0

def fbp_plane_reference_bounds(rig):
    """Return source, cropped and extended plane bounds in local XY space.

    Crop is expressed in the add-on's historical 0..2 range.  The helper uses
    the same one-pixel safety clamp as ``set_plane_mesh_extension`` so viewport
    controls, Crop/Extend guides and the rendered mesh agree exactly.
    """
    base_x, base_y = fbp_native_aspect_half_extents(rig)
    try:
        left = max(0.0, float(getattr(rig, "fbp_extend_left", 0.0)))
        right = max(0.0, float(getattr(rig, "fbp_extend_right", 0.0)))
        bottom = max(0.0, float(getattr(rig, "fbp_extend_bottom", 0.0)))
        top = max(0.0, float(getattr(rig, "fbp_extend_top", 0.0)))
        crop_left = max(0.0, min(1.999999, float(getattr(rig, "fbp_crop_left", 0.0))))
        crop_right = max(0.0, min(1.999999, float(getattr(rig, "fbp_crop_right", 0.0))))
        crop_bottom = max(0.0, min(1.999999, float(getattr(rig, "fbp_crop_bottom", 0.0))))
        crop_top = max(0.0, min(1.999999, float(getattr(rig, "fbp_crop_top", 0.0))))
        source_width = int(rig.get("fbp_source_width", 0) or 0)
        source_height = int(rig.get("fbp_source_height", 0) or 0)
    except FBP_DATA_IO_ERRORS:
        left = right = bottom = top = 0.0
        crop_left = crop_right = crop_bottom = crop_top = 0.0
        source_width = source_height = 0

    max_horizontal_crop = (2.0 - (2.0 / max(1, source_width))) if source_width > 0 else 1.999998
    max_vertical_crop = (2.0 - (2.0 / max(1, source_height))) if source_height > 0 else 1.999998
    max_horizontal_crop = max(0.0, min(1.999998, max_horizontal_crop))
    max_vertical_crop = max(0.0, min(1.999998, max_vertical_crop))
    if crop_left + crop_right > max_horizontal_crop:
        factor = max_horizontal_crop / max(crop_left + crop_right, 1.0e-12)
        crop_left *= factor
        crop_right *= factor
    if crop_bottom + crop_top > max_vertical_crop:
        factor = max_vertical_crop / max(crop_bottom + crop_top, 1.0e-12)
        crop_bottom *= factor
        crop_top *= factor

    x0 = -base_x + crop_left * base_x
    x1 = base_x - crop_right * base_x
    y0 = -base_y + crop_bottom * base_y
    y1 = base_y - crop_top * base_y
    source = (-base_x, base_x, -base_y, base_y)
    cropped = (x0, x1, y0, y1)
    extended = (
        x0 - left * base_x, x1 + right * base_x,
        y0 - bottom * base_y, y1 + top * base_y,
    )
    uv = (
        crop_left * 0.5, 1.0 - crop_right * 0.5,
        crop_bottom * 0.5, 1.0 - crop_top * 0.5,
    )
    return source, cropped, extended, uv


def fbp_update_rig_frame_mesh_to_bounds(rig, min_x, max_x, min_y, max_y, margin=None):
    """Keep the wire rig rectangle aligned with the cropped/extended plane bounds."""
    if not rig or not getattr(rig, 'data', None):
        return False
    try:
        shape = str(getattr(rig, "fbp_rig_shape", "DEFAULT") or "DEFAULT").upper()
        if shape == 'CUSTOM':
            return True
        margin = fbp_rig_shape_margin(rig) if margin is None else max(0.0, float(margin))
        min_x, max_x = float(min_x) - margin, float(max_x) + margin
        min_y, max_y = float(min_y) - margin, float(max_y) + margin
        mesh = rig.data
        mesh.clear_geometry()
        fit_mode = str(getattr(rig, "fbp_rig_shape_fit_mode", "FIT_PLANE") or "FIT_PLANE").upper()
        half_extents = None
        center = (0.0, 0.0)
        if fit_mode == 'FIT_PLANE' or shape == 'DEFAULT':
            half_extents = ((max_x - min_x) * 0.5, (max_y - min_y) * 0.5)
            center = ((max_x + min_x) * 0.5, (max_y + min_y) * 0.5)
        shape_size = max(0.0002, 2.0 + margin * 2.0)
        verts, edges = _fbp_rig_shape_geometry(
            shape, size=shape_size, half_extents=half_extents, center=center
        )
        mesh.from_pydata(verts, edges, [])
        mesh.update()
        return True
    except Exception as exc:
        _fbp_warn("Could not update rig frame mesh bounds", exc)
        return False

def fbp_create_mesh_object(name, mesh, context, location=None, target_collection=None):
    obj = bpy.data.objects.new(name, mesh)
    if location is not None:
        obj.location = location
    fbp_link_object(obj, context, target_collection)
    return obj

# SECTION 03 - Color / Gradient / Holdout Rig Builder #
def build_fbp_color_rig(context, name, color, use_emission=True, holdout=False, location=None, target_collection=None, gradient_settings=None):
    sc = context.scene
    location = location or sc.cursor.location.copy()
    target_collection = target_collection or getattr(context, 'collection', None) or sc.collection

    rig_mesh = fbp_create_rect_mesh("Mesh_" + (name or "Color_Plane") + "_Rig", size=2.1, with_face=False)
    rig = fbp_create_mesh_object(name or "Color Plane", rig_mesh, context, location=location, target_collection=target_collection)
    rig.display_type = 'WIRE'
    rig.is_fbp_control = True
    rig.hide_render = True
    fbp_set_rna_property_silent(rig, 'fbp_use_emission', bool(use_emission))
    fbp_set_rna_property_silent(rig, 'fbp_color_plane_emission', bool(use_emission))
    rig.fbp_loop_mode = 'NONE'
    rig.fbp_global_duration = 1
    rig.fbp_start_frame = fbp_creation_start_frame(sc, context)
    rig.fbp_track_cam = bool(getattr(sc, 'fbp_pre_track_cam', False))
    rig.scale = camera_ratio_scale(context)
    rig.fbp_base_scale_vec = rig.scale
    # Creation-time initialization must not invoke the interactive bulk-color callback.
    fbp_set_rna_property_silent(rig, 'fbp_color_tag', 'NONE')
    rig.fbp_is_color_plane = True
    try:
        rig["fbp_auto_color_plane_name"] = str(rig.name)
    except FBP_DATA_IO_ERRORS:
        pass
    rig.fbp_color_plane_color = color
    rig.fbp_color_plane_mode = 'GRADIENT' if gradient_settings else ('HOLDOUT' if holdout else 'SOLID')
    try:
        rig['fbp_procedural_layer_type'] = rig.fbp_color_plane_mode
        rig['fbp_backend_type'] = {
            'GRADIENT': 'PROCEDURAL_GRADIENT',
            'HOLDOUT': 'PROCEDURAL_HOLDOUT',
        }.get(rig.fbp_color_plane_mode, 'PROCEDURAL_COLOR')
        rig.color = tuple(color)
    except FBP_DATA_IO_ERRORS:
        pass
    if gradient_settings:
        rig.fbp_gradient_mode = gradient_settings.get('mode', 'LINEAR')
        rig.fbp_gradient_kind = gradient_settings.get('kind', 'COLOR')
        rig.fbp_gradient_color_a = gradient_settings.get('color_a', (0, 0, 0, 0))
        rig.fbp_gradient_color_b = gradient_settings.get('color_b', color)
        rig.fbp_gradient_reverse = bool(gradient_settings.get('reverse', False))
        rig.fbp_gradient_offset_x = float(gradient_settings.get('offset_x', 0.0))
        rig.fbp_gradient_offset_y = float(gradient_settings.get('offset_y', 0.0))
        rig.fbp_gradient_scale_x = float(gradient_settings.get('scale_x', 1.0))
        rig.fbp_gradient_scale_y = float(gradient_settings.get('scale_y', 1.0))
        rig.fbp_gradient_rotation = float(gradient_settings.get('rotation', 0.0))
    fbp_apply_creation_orientation(rig, sc)

    plane_mesh = fbp_create_rect_mesh("Mesh_Plane_" + (name or "Color_Plane"), size=2.0, with_face=True)
    plane = fbp_create_mesh_object("Plane_" + rig.name, plane_mesh, context, location=location, target_collection=target_collection)
    plane.is_fbp_plane = True
    try:
        if getattr(plane, "data", None) is not None:
            plane.data["fbp_plane_mesh"] = True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    plane["fbp_parent_rig_name"] = rig.name
    plane['fbp_backend_type'] = rig.get('fbp_backend_type', 'PROCEDURAL_COLOR')
    plane.parent = rig
    try:
        plane.matrix_parent_inverse.identity()
    except FBP_DATA_IO_ERRORS:
        pass
    plane.location = (0, 0, 0)
    plane.rotation_euler = (0, 0, 0)
    plane.hide_select = True
    rig.fbp_plane_target = plane

    fbp_rebuild_color_plane_material(rig)
    try:
        plane.hide_render = not bool(getattr(rig, 'fbp_is_visible', True))
        for poly in plane.data.polygons:
            poly.material_index = 0
    except (AttributeError, ReferenceError, RuntimeError) as exc:
        _fbp_warn('Could not finalize procedural plane render state', exc)

    # New Color and Gradient planes are genuinely static. The Frames panel owns
    # the explicit conversion to a two-row procedural animation, so creation
    # never presents a simple plane as an already animated Multi Color Plane.
    if not holdout:
        fbp_set_rna_property_silent(rig, 'fbp_sequence_show_frames', True)
    if target_collection:
        rig.fbp_collection_name = target_collection.name
        plane.fbp_collection_name = target_collection.name
    try:
        from .ownership import tag_layer_contract
        tag_layer_contract(rig)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return rig

# SECTION 04 - Plane Extension / Crop Geometry #
def set_plane_mesh_extension(rig, left=0.0, right=0.0, bottom=0.0, top=0.0, mode='MIRROR', crop_left=0.0, crop_right=0.0, crop_bottom=0.0, crop_top=0.0):
    """Extend plane borders without scaling/deforming the center image.

    Rebuilds only the child plane mesh. Object transforms are explicitly preserved
    so opening/changing Crop / Extend never moves the rig or the image plane.
    """
    plane = getattr(rig, "fbp_plane_target", None)
    if not plane or not getattr(plane, "data", None):
        return False

    # Preserve transforms as explicit local components.
    # Do not cache/restore rig.matrix_world here: during freshly-created native
    # layers Blender can still have a stale world matrix, and restoring it may
    # undo the just-applied Vertical orientation/depth offset.
    try:
        rig_location = rig.location.copy()
        rig_rotation = rig.rotation_euler.copy()
        rig_scale = rig.scale.copy()
    except Exception:
        rig_location = rig_rotation = rig_scale = None
    try:
        plane_location = plane.location.copy()
        plane_rotation = plane.rotation_euler.copy()
        plane_scale = plane.scale.copy()
        plane_parent_inverse = plane.matrix_parent_inverse.copy()
    except Exception:
        plane_location = plane_rotation = plane_scale = plane_parent_inverse = None

    left = max(0.0, float(left))
    right = max(0.0, float(right))
    bottom = max(0.0, float(bottom))
    top = max(0.0, float(top))
    crop_left = max(0.0, min(1.999999, float(crop_left)))
    crop_right = max(0.0, min(1.999999, float(crop_right)))
    crop_bottom = max(0.0, min(1.999999, float(crop_bottom)))
    crop_top = max(0.0, min(1.999999, float(crop_top)))

    # Keep at least one source pixel on each axis when dimensions are known.
    # The older fixed 1.98 limit was exact only for 100-pixel images and left
    # large transparent borders around tiny artwork on high-resolution canvases.
    try:
        raw_source_width = int(rig.get("fbp_source_width", 0) or 0)
        raw_source_height = int(rig.get("fbp_source_height", 0) or 0)
        source_width = max(1, raw_source_width) if raw_source_width > 0 else 0
        source_height = max(1, raw_source_height) if raw_source_height > 0 else 0
    except FBP_DATA_IO_ERRORS:
        source_width = source_height = 0
    max_horizontal_crop = (2.0 - (2.0 / source_width)) if source_width > 0 else 1.999998
    max_vertical_crop = (2.0 - (2.0 / source_height)) if source_height > 0 else 1.999998
    max_horizontal_crop = max(0.0, min(1.999998, max_horizontal_crop))
    max_vertical_crop = max(0.0, min(1.999998, max_vertical_crop))
    if crop_left + crop_right > max_horizontal_crop:
        scale = max_horizontal_crop / max(crop_left + crop_right, 1e-12)
        crop_left *= scale
        crop_right *= scale
    if crop_bottom + crop_top > max_vertical_crop:
        scale = max_vertical_crop / max(crop_bottom + crop_top, 1e-12)
        crop_bottom *= scale
        crop_top *= scale
    mode = (mode or 'MIRROR').upper()

    base_x, base_y = fbp_native_aspect_half_extents(rig)
    no_extension = left <= 1e-8 and right <= 1e-8 and bottom <= 1e-8 and top <= 1e-8
    expected_polygon_count = 1 if no_extension else 9
    mesh = plane.data
    signature = "|".join((
        str(FBP_CROP_EXTEND_CONTRACT_VERSION),
        mode,
        f"{base_x:.9f}", f"{base_y:.9f}",
        f"{left:.9f}", f"{right:.9f}", f"{bottom:.9f}", f"{top:.9f}",
        f"{crop_left:.9f}", f"{crop_right:.9f}", f"{crop_bottom:.9f}", f"{crop_top:.9f}",
        str(source_width), str(source_height), str(expected_polygon_count),
    ))
    try:
        if (
            int(plane.get("fbp_crop_extend_contract_version", 0) or 0) == FBP_CROP_EXTEND_CONTRACT_VERSION
            and str(plane.get("fbp_crop_extend_mesh_signature", "") or "") == signature
            and len(getattr(mesh, "polygons", ()) or ()) == expected_polygon_count
            and bool(getattr(mesh, "uv_layers", None))
        ):
            return False
    except FBP_DATA_IO_ERRORS:
        pass

    mats = list(mesh.materials)
    try:
        current_material_index = int(mesh.polygons[0].material_index) if mesh.polygons else 0
    except Exception:
        current_material_index = 0
    if mats:
        current_material_index = max(0, min(current_material_index, len(mats) - 1))
    else:
        current_material_index = 0

    # Crop values use the current 0..2 range, corresponding to 0..100% of
    # the local width/height. Native layers apply that percentage to the real
    # image-aspect half extents instead of rebuilding a square plane.
    x0 = -base_x + (crop_left * base_x)
    x1 = base_x - (crop_right * base_x)
    y0 = -base_y + (crop_bottom * base_y)
    y1 = base_y - (crop_top * base_y)
    no_extension = left <= 1e-8 and right <= 1e-8 and bottom <= 1e-8 and top <= 1e-8

    mesh.clear_geometry()
    if no_extension:
        # Crop-only planes need one real quad. The previous 4x4 grid produced
        # eight zero-area border faces whenever extension values were zero.
        verts = [(x0, y0, 0.0), (x1, y0, 0.0), (x1, y1, 0.0), (x0, y1, 0.0)]
        faces = [(0, 1, 2, 3)]
        mesh.from_pydata(verts, [], faces)
        mesh.update()

        mesh.materials.clear()
        for mat in mats:
            if mat:
                mesh.materials.append(mat)

        uv_layer = fbp_ensure_render_uv_map(mesh, "UVMap")
        if mesh.polygons:
            u0 = crop_left / 2.0
            u1 = 1.0 - (crop_right / 2.0)
            v0 = crop_bottom / 2.0
            v1 = 1.0 - (crop_top / 2.0)
            coords = ((u0, v0), (u1, v0), (u1, v1), (u0, v1))
            for loop_index, uv in zip(mesh.polygons[0].loop_indices, coords, strict=True):
                uv_layer.data[loop_index].uv = uv
            mesh.polygons[0].material_index = current_material_index

        fbp_update_rig_frame_mesh_to_bounds(rig, x0, x1, y0, y1)
    else:
        xs = [x0 - (left * base_x), x0, x1, x1 + (right * base_x)]
        ys = [y0 - (bottom * base_y), y0, y1, y1 + (top * base_y)]
        verts = [(x, y, 0.0) for y in ys for x in xs]

        def vid(ix, iy):
            return iy * 4 + ix

        faces = []
        face_cells = []
        for iy in range(3):
            for ix in range(3):
                faces.append((vid(ix, iy), vid(ix + 1, iy), vid(ix + 1, iy + 1), vid(ix, iy + 1)))
                face_cells.append((ix, iy))

        mesh.from_pydata(verts, [], faces)
        mesh.update()

        mesh.materials.clear()
        for mat in mats:
            if mat:
                mesh.materials.append(mat)

        uv_layer = fbp_ensure_render_uv_map(mesh, "UVMap")

        u0 = crop_left / 2.0
        u1 = 1.0 - (crop_right / 2.0)
        v0 = crop_bottom / 2.0
        v1 = 1.0 - (crop_top / 2.0)
        if mode in {'REPEAT', 'MIRROR', 'TRANSPARENT'}:
            ux = [u0 - left / 2.0, u0, u1, u1 + right / 2.0]
            uy = [v0 - bottom / 2.0, v0, v1, v1 + top / 2.0]
        else:
            ux = [u0, u0, u1, u1]
            uy = [v0, v0, v1, v1]

        # Blender's primitive plane UV orientation is local XY. Assign per face loop.
        for poly, (ix, iy) in zip(mesh.polygons, face_cells, strict=True):
            coords = ((ux[ix], uy[iy]), (ux[ix + 1], uy[iy]), (ux[ix + 1], uy[iy + 1]), (ux[ix], uy[iy + 1]))
            for loop_index, uv in zip(poly.loop_indices, coords, strict=True):
                uv_layer.data[loop_index].uv = uv
            poly.material_index = current_material_index

        fbp_update_rig_frame_mesh_to_bounds(rig, xs[0], xs[-1], ys[0], ys[-1])

    rig["fbp_extend_left"] = left
    rig["fbp_extend_right"] = right
    rig["fbp_extend_bottom"] = bottom
    rig["fbp_extend_top"] = top
    rig["fbp_extend_mode"] = mode
    rig["fbp_crop_left"] = crop_left
    rig["fbp_crop_right"] = crop_right
    rig["fbp_crop_bottom"] = crop_bottom
    rig["fbp_crop_top"] = crop_top
    try:
        plane["fbp_crop_extend_mesh_signature"] = signature
        plane["fbp_crop_extend_contract_version"] = FBP_CROP_EXTEND_CONTRACT_VERSION
    except FBP_DATA_IO_ERRORS:
        pass

    # Rebuilding mesh data must never change user transforms.
    try:
        if rig_location is not None:
            rig.location = rig_location
        if rig_rotation is not None:
            rig.rotation_euler = rig_rotation
        if rig_scale is not None:
            rig.scale = rig_scale
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        if plane_location is not None:
            plane.location = plane_location
        if plane_rotation is not None:
            plane.rotation_euler = plane_rotation
        if plane_scale is not None:
            plane.scale = plane_scale
        if plane_parent_inverse is not None:
            plane.matrix_parent_inverse = plane_parent_inverse
    except FBP_DATA_IO_ERRORS:
        pass
    return True

# SECTION 05 - Fit to Camera #
def fbp_rig_base_image_size(rig):
    """Return local image dimensions for fit-to-camera, ignoring extensions."""
    try:
        if bool(rig.get("fbp_native_backend", False)):
            base_x, base_y = fbp_native_aspect_half_extents(rig)
            return 2.0 * max(base_x, 0.0001), 2.0 * max(base_y, 0.0001)
    except FBP_DATA_IO_ERRORS:
        pass
    base_x = max(float(getattr(rig, "fbp_base_scale_vec", (1.0, 1.0, 1.0))[0]), 0.0001)
    base_y = max(float(getattr(rig, "fbp_base_scale_vec", (1.0, 1.0, 1.0))[1]), 0.0001)
    return 2.0 * base_x, 2.0 * base_y

def apply_fit_to_camera(context, rig, cam):
    """Uniformly fit the real image rectangle inside the active camera.

    There is intentionally only one mode: the first image side that touches the
    camera border stops the scale. Crop / Extend and the wire rig are ignored.
    """
    if not rig or not cam:
        return
    cam_z = cam.matrix_world.to_3x3() @ mathutils.Vector((0.0, 0.0, -1.0))
    vec = rig.matrix_world.translation - cam.matrix_world.translation
    dist = abs(vec.dot(cam_z))
    if dist < 0.001 and getattr(cam.data, 'type', '') != 'ORTHO':
        return

    frame = cam.data.view_frame(scene=context.scene)
    min_x = min(v.x for v in frame)
    max_x = max(v.x for v in frame)
    min_y = min(v.y for v in frame)
    max_y = max(v.y for v in frame)
    if getattr(cam.data, 'type', '') == 'ORTHO':
        projection_scale = 1.0
    else:
        frame_z = abs(frame[0].z) if abs(frame[0].z) > 1e-6 else 1.0
        projection_scale = dist / frame_z
    frame_width = abs(max_x - min_x) * projection_scale
    frame_height = abs(max_y - min_y) * projection_scale

    base_vec = getattr(rig, "fbp_base_scale_vec", (1.0, 1.0, 1.0))
    try:
        native_geometry = bool(rig.get("fbp_native_backend", False))
    except Exception:
        native_geometry = False
    if native_geometry:
        # Native planes carry image aspect in mesh geometry, so fit-to-camera
        # must scale uniformly. Procedural layers carry aspect in rig.scale.
        base_x = base_y = base_z = 1.0
    else:
        base_x = max(float(base_vec[0]), 0.0001)
        base_y = max(float(base_vec[1]), 0.0001)
        base_z = max(float(base_vec[2]), 0.0001)
    img_width, img_height = fbp_rig_base_image_size(rig)
    if img_width <= 0 or img_height <= 0:
        return

    factor = min(frame_width / img_width, frame_height / img_height)
    rig.scale = (base_x * factor, base_y * factor, base_z * factor)

# SECTION 06 - Image Sequence Rig Builder #
def fbp_prepare_media_source(context, directory, files_list, item_durations=None):
    """Resolve one Pillow-backed source to Blender-readable cached PNG frames."""
    files_list = [str(f) for f in (files_list or []) if f]
    original_durations = list(item_durations) if item_durations is not None else None
    if not files_list:
        return directory, [], original_durations, None

    render = getattr(getattr(context, "scene", None), "render", None)
    fps = float(getattr(render, "fps", 24) or 24) / max(
        0.001, float(getattr(render, "fps_base", 1.0) or 1.0)
    )

    def prepare_one(source_path, extension):
        try:
            return fbp_prepare_pillow_media(
                source_path,
                cache_root=fbp_default_pillow_cache_root(source_path),
                fps=fps,
            )
        except OSError:
            try:
                fallback_root = bpy.utils.user_resource(
                    "DATAFILES",
                    path=os.path.join("frame_by_plane", "media_cache"),
                    create=True,
                )
                if not fallback_root:
                    raise OSError("Blender did not provide a writable media cache")
                return fbp_prepare_pillow_media(
                    source_path,
                    cache_root=fallback_root,
                    fps=fps,
                )
            except Exception as exc:
                if extension in FBP_PILLOW_CONVERT_EXTENSIONS:
                    raise RuntimeError(f"Could not convert {extension.lstrip('.').upper()} media: {exc}") from exc
                _fbp_warn("Animated image extraction skipped", exc)
                return None
        except Exception as exc:
            if extension in FBP_PILLOW_CONVERT_EXTENSIONS:
                raise RuntimeError(f"Could not decode {extension.lstrip('.').upper()} media: {exc}") from exc
            _fbp_warn("Animated image extraction skipped", exc)
            return None

    expanded_files = []
    expanded_durations = []
    prepared_sources = []
    for index, filename in enumerate(files_list):
        source_path = filename
        if not os.path.isabs(source_path):
            source_path = os.path.join(str(directory or ""), source_path)
        source_path = os.path.abspath(source_path)
        extension = os.path.splitext(source_path)[1].lower()
        # A normal numbered PNG/GIF/WebP sequence is already native and must
        # not be opened once per row merely to look for embedded animation.
        should_prepare = len(files_list) == 1 or extension in FBP_PILLOW_CONVERT_EXTENSIONS
        prepared = prepare_one(source_path, extension) if should_prepare else None
        try:
            original_duration = (
                max(1, int(original_durations[index]))
                if original_durations is not None and index < len(original_durations)
                else 1
            )
        except (TypeError, ValueError):
            original_duration = 1
        if prepared is None:
            expanded_files.append(filename)
            expanded_durations.append(original_duration)
            continue

        prepared_sources.append(prepared)
        for frame_index, frame_name in enumerate(prepared.files):
            expanded_files.append(os.path.join(prepared.output_directory, frame_name))
            if prepared.animated:
                expanded_durations.append(prepared.durations[frame_index])
            else:
                expanded_durations.append(original_duration)

    if not prepared_sources:
        return directory, files_list, original_durations, None

    prepared_media = prepared_sources[0] if len(files_list) == 1 else None
    if prepared_media is not None:
        directory = prepared_media.output_directory
        expanded_files = [os.path.basename(path) for path in expanded_files]
    return directory, expanded_files, expanded_durations, prepared_media


def fbp_store_prepared_media_metadata(rig, prepared_media) -> None:
    keys = (
        "fbp_pillow_source_path",
        "fbp_pillow_source_format",
        "fbp_pillow_source_cache_key",
        "fbp_pillow_source_animated",
        "fbp_pillow_source_cache_reused",
        "fbp_pillow_source_durations_ms",
    )
    if prepared_media is None:
        for key in keys:
            try:
                if key in rig:
                    del rig[key]
            except FBP_DATA_IO_ERRORS:
                pass
        return
    try:
        rig["fbp_pillow_source_path"] = prepared_media.source_path
        rig["fbp_pillow_source_format"] = prepared_media.source_format
        rig["fbp_pillow_source_cache_key"] = prepared_media.cache_key
        rig["fbp_pillow_source_animated"] = bool(prepared_media.animated)
        rig["fbp_pillow_source_cache_reused"] = bool(prepared_media.reused_cache)
        rig["fbp_pillow_source_durations_ms"] = "|".join(
            f"{value:.6f}" for value in prepared_media.source_durations_ms
        )
    except FBP_DATA_IO_ERRORS:
        pass


def build_fbp_rig(
    context, rig_name, directory, files_list, location, color_tag='NONE',
    target_collection=None, color_variant_index=0, follow_collection_color=True,
    item_durations=None, source_frame_numbers=None, source_preset="",
):
    """Create an FBP image layer using Blender's native Image Sequence backend only."""
    directory, files_list, item_durations, prepared_media = fbp_prepare_media_source(
        context, directory, files_list, item_durations,
    )

    from .native_backend import build_native_fbp_rig
    try:
        rig = build_native_fbp_rig(
            context, rig_name, directory, files_list, location,
            color_tag=color_tag,
            target_collection=target_collection,
            color_variant_index=color_variant_index,
            follow_collection_color=follow_collection_color,
            item_durations=item_durations,
        )
        if source_preset:
            try:
                rig["fbp_import_preset"] = str(source_preset)
                rig["fbp_source_frame_numbers"] = "|".join(
                    str(int(value)) for value in (source_frame_numbers or ())
                )
            except FBP_DATA_IO_ERRORS:
                pass
        if prepared_media is not None:
            fbp_store_prepared_media_metadata(rig, prepared_media)
        fbp_set_rna_property_silent(rig, "fbp_sequence_show_frames", len(files_list) > 1)
        if len(files_list) > 1:
            natural_order = sorted(files_list, key=natural_sort_key)
            is_reversed = files_list == list(reversed(natural_order)) and files_list != natural_order
            fbp_set_rna_property_silent(rig, "fbp_sequence_reversed", is_reversed)
        return rig
    except Exception as exc:
        _fbp_warn("Native Image Sequence import failed", exc)
        raise RuntimeError(f"Frame by Plane native Image Sequence import failed: {exc}") from exc
