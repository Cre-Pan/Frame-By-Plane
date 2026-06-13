"""Geometry, rig-building, fit-to-camera and extension helpers."""

import bpy
import math
import mathutils

try:
    from .materials import (
        fbp_rebuild_color_plane_material,
    )
except ImportError:
    from materials import (
        fbp_rebuild_color_plane_material,
    )


# SECTION 01 - Shared runtime helpers #
try:
    from .runtime import fbp_warn as _fbp_warn, fbp_set_rna_property_silent
except ImportError:
    from runtime import fbp_warn as _fbp_warn, fbp_set_rna_property_silent


# SECTION 02 - Mesh / Object creation #


def fbp_scene_orientation_is_horizontal(scene):
    """Return True only for the explicit Horizontal creation preset.

    Older test files or UI states may carry slightly different string values,
    so anything that is not clearly Horizontal falls back to Vertical.
    """
    value = str(getattr(scene, 'fbp_pre_orientation', 'VERT') or 'VERT').upper()
    return value in {'HORIZ', 'HORIZONTAL'}


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
        uv_layer = mesh.uv_layers.new(name="UVMap")
        coords = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
        if mesh.polygons:
            for loop_index, uv in zip(mesh.polygons[0].loop_indices, coords):
                uv_layer.data[loop_index].uv = uv
    return mesh


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
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
            if not getattr(mat, "use_nodes", False) or not getattr(mat, "node_tree", None):
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
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    return None

def fbp_native_aspect_half_extents(rig):
    """Return normalized half-extents for native image planes.

    Legacy FBP layers keep their image aspect in the rig scale. Native layers
    bake the aspect into the generated plane/frame mesh instead, so crop and
    extend operate on the real visible rectangle and the controller does not
    appear square while the material is correct.
    """
    if not rig:
        return 1.0, 1.0
    try:
        if not bool(rig.get("fbp_native_backend", False)):
            return 1.0, 1.0
    except Exception:
        return 1.0, 1.0
    material_aspect = _fbp_aspect_from_plane_image(rig)
    try:
        ax = float(rig.get("fbp_native_aspect_x", 0.0))
        ay = float(rig.get("fbp_native_aspect_y", 0.0))
        src_w = float(rig.get("fbp_source_width", 0.0))
        src_h = float(rig.get("fbp_source_height", 0.0))
        # Prefer the real image datablock when available. This repairs old Alpha
        # rigs that accidentally baked 1:1 before the image dimensions were ready.
        if material_aspect and (src_w <= 0.0 or src_h <= 0.0 or abs(ax - ay) < 1e-6):
            ax, ay, width, height = material_aspect
            try:
                rig["fbp_source_width"] = int(width)
                rig["fbp_source_height"] = int(height)
                rig["fbp_native_aspect_x"] = float(ax)
                rig["fbp_native_aspect_y"] = float(ay)
                rig["fbp_native_aspect_baked"] = True
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
            return ax, ay
        if ax > 0.0 and ay > 0.0:
            return ax, ay
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        width = float(rig.get("fbp_source_width", 0.0))
        height = float(rig.get("fbp_source_height", 0.0))
        if width > 0.0 and height > 0.0:
            if width >= height:
                return 1.0, max(height / width, 0.0001)
            return max(width / height, 0.0001), 1.0
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    if material_aspect:
        return material_aspect[0], material_aspect[1]
    return 1.0, 1.0

def fbp_update_rig_frame_mesh_to_bounds(rig, min_x, max_x, min_y, max_y, margin=0.05):
    """Keep the wire rig rectangle aligned with the cropped/extended plane bounds."""
    if not rig or not getattr(rig, 'data', None):
        return False
    try:
        min_x, max_x = float(min_x) - margin, float(max_x) + margin
        min_y, max_y = float(min_y) - margin, float(max_y) + margin
        mesh = rig.data
        mesh.clear_geometry()
        verts = [(min_x, min_y, 0.0), (max_x, min_y, 0.0), (max_x, max_y, 0.0), (min_x, max_y, 0.0)]
        edges = [(0, 1), (1, 2), (2, 3), (3, 0)]
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
    rig.fbp_start_frame = sc.frame_current
    rig.scale = camera_ratio_scale(context)
    rig.fbp_base_scale_vec = rig.scale
    rig.fbp_color_tag = 'COLOR_01'
    rig.fbp_is_color_plane = True
    rig.fbp_color_plane_color = color
    rig.fbp_color_plane_mode = 'GRADIENT' if gradient_settings else ('HOLDOUT' if holdout else 'SOLID')
    try:
        rig['fbp_procedural_layer_type'] = rig.fbp_color_plane_mode
        rig.color = tuple(color)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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
    plane["fbp_parent_rig_name"] = rig.name
    plane.parent = rig
    try:
        plane.matrix_parent_inverse.identity()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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

    # Static procedural planes start without frame rows.
    # The image/frame list appears only after the user explicitly adds/imports a frame.
    if target_collection:
        rig.fbp_collection_name = target_collection.name
        plane.fbp_collection_name = target_collection.name
    return rig

# SECTION 04 - Plane Extension / Crop Geometry #
def set_plane_mesh_extension(rig, left=0.0, right=0.0, bottom=0.0, top=0.0, mode='EDGE', crop_left=0.0, crop_right=0.0, crop_bottom=0.0, crop_top=0.0):
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
    crop_left = max(0.0, min(1.95, float(crop_left)))
    crop_right = max(0.0, min(1.95, float(crop_right)))
    crop_bottom = max(0.0, min(1.95, float(crop_bottom)))
    crop_top = max(0.0, min(1.95, float(crop_top)))
    if crop_left + crop_right > 1.98:
        scale = 1.98 / (crop_left + crop_right)
        crop_left *= scale
        crop_right *= scale
    if crop_bottom + crop_top > 1.98:
        scale = 1.98 / (crop_bottom + crop_top)
        crop_bottom *= scale
        crop_top *= scale
    mode = (mode or 'EDGE').upper()

    mesh = plane.data
    mats = [mat for mat in mesh.materials]
    try:
        current_material_index = int(mesh.polygons[0].material_index) if mesh.polygons else 0
    except Exception:
        current_material_index = 0
    if mats:
        current_material_index = max(0, min(current_material_index, len(mats) - 1))
    else:
        current_material_index = 0

    base_x, base_y = fbp_native_aspect_half_extents(rig)
    # Crop values remain compatible with the old UI: 0..2 means 0..100% of
    # the local width/height. Native layers apply that percentage to the real
    # image-aspect half extents instead of rebuilding a square plane.
    x0 = -base_x + (crop_left * base_x)
    x1 = base_x - (crop_right * base_x)
    y0 = -base_y + (crop_bottom * base_y)
    y1 = base_y - (crop_top * base_y)
    simple_quad = (left <= 1e-8 and right <= 1e-8 and bottom <= 1e-8 and top <= 1e-8 and crop_left <= 1e-8 and crop_right <= 1e-8 and crop_bottom <= 1e-8 and crop_top <= 1e-8)

    mesh.clear_geometry()
    if simple_quad:
        verts = [(-base_x, -base_y, 0.0), (base_x, -base_y, 0.0), (base_x, base_y, 0.0), (-base_x, base_y, 0.0)]
        faces = [(0, 1, 2, 3)]
        mesh.from_pydata(verts, [], faces)
        mesh.update()

        mesh.materials.clear()
        for mat in mats:
            if mat:
                mesh.materials.append(mat)

        uv_layer = mesh.uv_layers.new(name="UVMap") if not mesh.uv_layers else mesh.uv_layers.active
        if mesh.polygons:
            coords = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
            for loop_index, uv in zip(mesh.polygons[0].loop_indices, coords):
                uv_layer.data[loop_index].uv = uv
            mesh.polygons[0].material_index = current_material_index

        fbp_update_rig_frame_mesh_to_bounds(rig, -base_x, base_x, -base_y, base_y)
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

        uv_layer = mesh.uv_layers.new(name="UVMap") if not mesh.uv_layers else mesh.uv_layers.active

        u0 = crop_left / 2.0
        u1 = 1.0 - (crop_right / 2.0)
        v0 = crop_bottom / 2.0
        v1 = 1.0 - (crop_top / 2.0)
        if mode == 'REPEAT':
            ux = [u0 - left / 2.0, u0, u1, u1 + right / 2.0]
            uy = [v0 - bottom / 2.0, v0, v1, v1 + top / 2.0]
        else:
            ux = [u0, u0, u1, u1]
            uy = [v0, v0, v1, v1]

        # Blender's primitive plane UV orientation is local XY. Assign per face loop.
        for poly, (ix, iy) in zip(mesh.polygons, face_cells):
            coords = ((ux[ix], uy[iy]), (ux[ix + 1], uy[iy]), (ux[ix + 1], uy[iy + 1]), (ux[ix], uy[iy + 1]))
            for loop_index, uv in zip(poly.loop_indices, coords):
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

    # Rebuilding mesh data must never change user transforms.
    try:
        if rig_location is not None:
            rig.location = rig_location
        if rig_rotation is not None:
            rig.rotation_euler = rig_rotation
        if rig_scale is not None:
            rig.scale = rig_scale
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    return True

# SECTION 05 - Fit to Camera #
def fbp_rig_base_image_size(rig):
    """Return local image dimensions for fit-to-camera, ignoring extensions."""
    try:
        if bool(rig.get("fbp_native_backend", False)):
            base_x, base_y = fbp_native_aspect_half_extents(rig)
            return 2.0 * max(base_x, 0.0001), 2.0 * max(base_y, 0.0001)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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
        # must scale uniformly. Legacy layers still carry aspect in rig.scale.
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
def build_fbp_rig(context, rig_name, directory, files_list, location, color_tag='COLOR_01', target_collection=None, color_variant_index=0, follow_collection_color=True):
    """Create an FBP image layer using Blender's native Image Sequence backend only."""
    files_list = [str(f) for f in (files_list or []) if f]
    try:
        from .native_backend import build_native_fbp_rig
    except ImportError:
        from native_backend import build_native_fbp_rig
    try:
        return build_native_fbp_rig(
            context, rig_name, directory, files_list, location,
            color_tag=color_tag,
            target_collection=target_collection,
            color_variant_index=color_variant_index,
            follow_collection_color=follow_collection_color,
        )
    except Exception as exc:
        _fbp_warn("Native Image Sequence import failed", exc)
        raise RuntimeError(f"Frame by Plane native Image Sequence import failed: {exc}") from exc

# SECTION 99 - Register hooks #
def register():
    return None


def unregister():
    return None
