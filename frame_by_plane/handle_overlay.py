"""Draw Frame By Plane viewport handles on top of everything.

Handle meshes stay ordinary selectable objects, but Blender only keeps a
solid mesh "In Front" in Solid shading: in Material Preview and Rendered they
sink behind the image plane. This overlay redraws every visible handle from its
evaluated (Lattice-deformed) mesh without depth test, with a thin dark rim so
it reads on light and dark artwork alike.

Faces are coloured by their part (accent, colour swatch, stop ring) and loose
edges are drawn as thin guide lines with a constant width on screen: the line
between gradient stops, dashed radius circles and the Shape Mask outlines.
"""

from __future__ import annotations

import math

import bpy
import gpu
from bpy_extras.view3d_utils import location_3d_to_region_2d
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector

from .runtime import FBP_DATA_ERRORS
from .viewport_handles import (
    GUIDE_COLOR,
    GUIDE_OUTLINE_COLOR,
    HANDLE_COLOR,
    HANDLE_OUTLINE_COLOR,
    PART_ATTRIBUTE,
    PART_HANDLE,
    PART_STOP_RING,
    STOP_RING_COLOR,
    handle_selected_color,
)
from .common import (
    ui_scale as _ui_scale,
    uniform_color_shader as _fill_shader,
    undo_push as _undo_push,
    view_plane_hit as _plane_hit,
)


_DRAW_HANDLE = None
_LINE_SHADER = None
_OUTLINE_WIDTH = 1.5
_GUIDE_WIDTH = 1.4
_GUIDE_OUTLINE_WIDTH = 3.4


def _shaders():
    global _LINE_SHADER
    if _LINE_SHADER is None:
        _LINE_SHADER = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    return _fill_shader(), _LINE_SHADER


def _visible_handles(context):
    try:
        from .effect_controls import iter_visible_effect_controls
        handles = list(iter_visible_effect_controls(context))
    except (ImportError, AttributeError):
        handles = []
    try:
        from .object_masks import iter_visible_object_mask_handles
        handles.extend(iter_visible_object_mask_handles(context))
    except (ImportError, AttributeError):
        pass
    return handles


def _mask_guides(context):
    try:
        from .object_masks import iter_object_mask_guides
        return list(iter_object_mask_guides(context))
    except (ImportError, AttributeError):
        return []


def _ring_radius(world, pose_bone):
    """World radius of a Grid point's ring: its shape's outer edge, as drawn."""
    try:
        from .lattice_bones import SHAPE_KEY
        kind = str(pose_bone.custom_shape[SHAPE_KEY]) if pose_bone.custom_shape is not None else ""
    except (ImportError, KeyError, *FBP_DATA_ERRORS):
        return 0.0
    outer = {"POINT": 0.97, "GRID_CORNER": 1.2}.get(kind, 0.0)
    try:
        scale = float(pose_bone.custom_shape_scale_xyz[0])
        if pose_bone.use_custom_shape_bone_size:
            scale *= float(pose_bone.bone.length)
        return outer * scale * float(world.to_scale()[0])
    except FBP_DATA_ERRORS:
        return 0.0


def _lattice_guides(context):
    """Thin lines between Lattice handles, as in Grease Pencil's deform box.

    Corner Pin: the quad through its four corners (Perspective mode). Point
    handles: dashed lines along the grid rows and columns (Grid mode).
    """
    try:
        from .lattice_bones import is_bones_object
        from .lattice_corner_pin import CORNER_ROLE_KEY
        from .lattice_pins import PIN_GRID_KEY, PIN_POINT_KEY
        from .viewport_handles import dashed_pieces
    except ImportError:
        return []
    # Lattice handles are armatures: a file without any skips the scan of
    # every visible object on each redraw.
    if not len(bpy.data.armatures):
        return []
    segments = []
    for armature in tuple(getattr(context, "visible_objects", ()) or ()):
        if not is_bones_object(armature):
            continue
        try:
            world = armature.matrix_world
            corners, points, grid = {}, {}, None
            for bone in armature.pose.bones:
                if bone.bone.hide:
                    continue
                role = str(bone.get(CORNER_ROLE_KEY, "") or "")
                if role:
                    corners[role] = world @ bone.head
                    continue
                index = bone.get(PIN_POINT_KEY)
                if index is not None and bone.get(PIN_GRID_KEY):
                    points[int(index)] = (world @ bone.head, _ring_radius(world, bone))
                    grid = str(bone.get(PIN_GRID_KEY))
        except (*FBP_DATA_ERRORS, IndexError):
            continue
        quad = [corners.get(role) for role in ("BL", "BR", "TR", "TL")]
        if all(point is not None for point in quad):
            for index in range(4):
                segments.extend((quad[index], quad[(index + 1) % 4]))
        if grid and points:
            try:
                count_u, count_v = (int(value) for value in grid.split("x"))
            except ValueError:
                continue
            lines = []
            for v in range(count_v):
                lines.append([points.get(v * count_u + u) for u in range(count_u)])
            for u in range(count_u):
                lines.append([points.get(v * count_u + u) for v in range(count_v)])
            for line in lines:
                for first, second in zip(line, line[1:]):
                    if first is None or second is None:
                        continue
                    # Stop at the rings, so no line runs over a handle.
                    full = (second[0] - first[0]).length
                    if full <= first[1] + second[1] + 1.0e-9:
                        continue
                    direction = (second[0] - first[0]) / full
                    start = first[0] + direction * first[1]
                    end = second[0] - direction * second[1]
                    length = (end - start).length
                    # Dashes in a 2D frame along the segment, then back to 3D.
                    dash = length / 9.0
                    for piece in dashed_pieces([(0.0, 0.0), (length, 0.0)], dash, dash * 0.8):
                        segments.extend((start + direction * piece[0][0], start + direction * piece[-1][0]))
    return segments


# --- Lattice handles under the cursor ---------------------------------------
#
# Lattice handles are pose bones with custom shapes, which Blender draws. The
# overlay only adds the hover state the other handles have: the shape under
# the cursor is drawn again on top in the hover colour.

LATTICE_HOVER_PREFIX = "BONE:"


def _lattice_shape_triangles(armature, pose_bone):
    """World triangles of one Lattice handle's custom shape, as Blender draws it."""
    shape = pose_bone.custom_shape
    mesh = getattr(shape, "data", None)
    if mesh is None or not mesh.polygons:
        return []
    scale = Vector(pose_bone.custom_shape_scale_xyz)
    if pose_bone.use_custom_shape_bone_size:
        scale *= float(pose_bone.bone.length)
    matrix = (
        armature.matrix_world @ pose_bone.matrix
        @ Matrix.LocRotScale(
            Vector(pose_bone.custom_shape_translation),
            pose_bone.custom_shape_rotation_euler,
            scale,
        )
    )
    mesh.calc_loop_triangles()
    vertices = [matrix @ vertex.co for vertex in mesh.vertices]
    return [vertices[index] for tri in mesh.loop_triangles for index in tri.vertices]


def _visible_lattice_handles(context):
    try:
        from .lattice_bones import is_bones_object
    except ImportError:
        return
    for armature in tuple(getattr(context, "visible_objects", ()) or ()):
        try:
            # Cheap type test first: this runs on every cursor move.
            if armature.type != "ARMATURE" or not is_bones_object(armature):
                continue
            for pose_bone in armature.pose.bones:
                if not pose_bone.bone.hide and pose_bone.custom_shape is not None:
                    yield armature, pose_bone
        except FBP_DATA_ERRORS:
            continue


def lattice_handle_under_cursor(context, coord, radius):
    """Hover key (``LATTICE_HOVER_PREFIX`` + armature and bone) of the Lattice
    handle under ``coord``, or ""."""
    try:
        from .alpha_pick import _screen_distance_to_triangle_sq
    except ImportError:
        return ""
    region, view = context.region, context.region_data
    point = (float(coord[0]), float(coord[1]))
    limit = float(radius) * float(radius)
    best = None
    for armature, pose_bone in _visible_lattice_handles(context):
        try:
            triangles = _lattice_shape_triangles(armature, pose_bone)
        except (*FBP_DATA_ERRORS, IndexError):
            continue
        projected = [location_3d_to_region_2d(region, view, corner) for corner in triangles]
        for index in range(0, len(projected) - 2, 3):
            corners = projected[index:index + 3]
            if any(corner is None for corner in corners):
                continue
            distance = _screen_distance_to_triangle_sq(point, *corners)
            if distance <= limit and (best is None or distance < best[0]):
                best = (distance, f"{LATTICE_HOVER_PREFIX}{armature.name}\t{pose_bone.name}")
    return "" if best is None else best[1]


def _hovered_lattice_triangles(hovered):
    if not hovered.startswith(LATTICE_HOVER_PREFIX):
        return []
    armature_name, _tab, bone_name = hovered[len(LATTICE_HOVER_PREFIX):].partition("\t")
    armature = bpy.data.objects.get(armature_name)
    try:
        pose_bone = armature.pose.bones.get(bone_name) if armature is not None else None
        if pose_bone is None:
            return []
        # A selected handle already shows the selection colour in Pose Mode.
        if str(armature.mode) == "POSE" and bool(getattr(pose_bone, "select", False)):
            return []
        return _lattice_shape_triangles(armature, pose_bone)
    except (*FBP_DATA_ERRORS, IndexError):
        return []


def _handle_hover_color(context):
    """The handle under the cursor: most of the way to the selected colour."""
    selected = handle_selected_color(context)
    return (*(0.3 * white + 0.7 * accent for white, accent in zip(HANDLE_COLOR[:3], selected[:3])), 1.0)


# Effect handles keep one size on screen, as Blender's gizmos do: the mesh is
# built at a plane-relative size and drawn scaled about its origin so that
# size reads as this many pixels. Guides (radius circles, gradient lines)
# keep their real size. Direction arrows are not scaled: their length is the
# effect distance.
HANDLE_SCREEN_SIZE_PX = 15.0
_UNSCALED_MODES = {"DIRECTION"}


def handle_screen_scale(obj, region, region_data, ui_scale=1.0):
    """``(anchor, factor)`` that brings ``obj``'s knob to its screen size, or None."""
    try:
        from .effect_controls import KEY_MODE
        from .viewport_handles import KEY_HANDLE_NOMINAL_SIZE, LATTICE_FOLLOW_MODIFIER
    except ImportError:
        return None
    try:
        nominal = float(obj.get(KEY_HANDLE_NOMINAL_SIZE, 0.0) or 0.0)
        mode = str(obj.get(KEY_MODE, "") or "").upper()
        if nominal <= 0.0 or mode in _UNSCALED_MODES:
            return None
        modifier = obj.modifiers.get(LATTICE_FOLLOW_MODIFIER)
        if modifier is not None and modifier.show_viewport and modifier.object is not None:
            # A deformed handle no longer sits on its origin.
            return None
        matrix = obj.matrix_world
        anchor = matrix.translation.copy()
        world = nominal * matrix.col[1].xyz.length
        right = region_data.view_matrix.inverted().col[0].xyz.normalized()
        start = location_3d_to_region_2d(region, region_data, anchor)
        end = location_3d_to_region_2d(region, region_data, anchor + right * world)
    except (*FBP_DATA_ERRORS, ZeroDivisionError):
        return None
    if start is None or end is None:
        return None
    pixels = (end - start).length
    if pixels <= 1.0e-6:
        return None
    factor = HANDLE_SCREEN_SIZE_PX * float(ui_scale) / pixels
    if mode == "CROP_EXTEND":
        # Blender also draws the handle mesh itself in Solid shading. The L
        # corners and side bars do not sit on their centre like a dot, so
        # never draw them smaller than that mesh: it stays hidden under them.
        factor = max(factor, 1.0)
    return anchor, factor


def _scaled(points, anchor, factor):
    return [anchor + (point - anchor) * factor for point in points]


# Local-space topology of each handle mesh, keyed by the mesh and a digest of
# its coordinates and face parts. Handles are redrawn on every viewport redraw
# and picked on every cursor move; building a temporary evaluated mesh for
# each of them every time cost about 0.3 ms per handle. Only plain meshes are
# cached: a handle with an active modifier (Lattice Follow) or shape keys is
# read from its evaluated mesh as before.
_MESH_CACHE = {}
_MESH_CACHE_LIMIT = 256


def _mesh_topology(mesh):
    """Local vertices, triangles with their part, rim, guide and loose X edges."""
    vertices = [vertex.co.copy() for vertex in mesh.vertices]
    parts = None
    attribute = mesh.attributes.get(PART_ATTRIBUTE)
    if attribute is not None and attribute.domain == "FACE" and len(attribute.data) == len(mesh.polygons):
        parts = [0] * len(mesh.polygons)
        attribute.data.foreach_get("value", parts)
    mesh.calc_loop_triangles()
    triangles = [
        (parts[tri.polygon_index] if parts else PART_HANDLE, tuple(tri.vertices))
        for tri in mesh.loop_triangles
    ]
    edge_users = {}
    for polygon in mesh.polygons:
        for key in polygon.edge_keys:
            edge_users[key] = edge_users.get(key, 0) + 1
    rim = tuple(key for key, users in edge_users.items() if users == 1)
    guides = tuple(
        tuple(edge.vertices)
        for edge in mesh.edges
        if tuple(sorted(edge.vertices)) not in edge_users
    )
    loose_x = tuple(
        tuple(edge.vertices)
        for edge in mesh.edges
        if edge.is_loose
        and abs(vertices[edge.vertices[0]].y) <= 1.0e-6
        and abs(vertices[edge.vertices[1]].y) <= 1.0e-6
    )
    return {
        "vertices": vertices,
        "triangles": triangles,
        "triangle_vertices": tuple(sorted({index for _part, indices in triangles for index in indices})),
        "rim": rim,
        "guides": guides,
        "loose_x": loose_x,
    }


def _mesh_digest(mesh):
    from array import array

    coords = array("f", [0.0]) * (len(mesh.vertices) * 3)
    mesh.vertices.foreach_get("co", coords)
    digest = [len(mesh.vertices), len(mesh.edges), len(mesh.polygons), hash(coords.tobytes())]
    attribute = mesh.attributes.get(PART_ATTRIBUTE)
    if attribute is not None and attribute.domain == "FACE":
        values = array("i", [0]) * len(attribute.data)
        attribute.data.foreach_get("value", values)
        digest.append(hash(values.tobytes()))
    return tuple(digest)


def _plain_mesh(obj):
    """The handle's own mesh when nothing deforms it, else None."""
    mesh = getattr(obj, "data", None)
    if mesh is None or getattr(obj, "type", "") != "MESH":
        return None
    if getattr(mesh, "shape_keys", None) is not None:
        return None
    if obj.parent is not None and obj.parent_type in {"LATTICE", "ARMATURE"}:
        return None
    for modifier in obj.modifiers:
        if modifier.show_viewport:
            return None
    return mesh


def handle_mesh(obj, depsgraph):
    """``(matrix_world, topology)`` of a handle as the viewport shows it."""
    evaluated = obj.evaluated_get(depsgraph)
    matrix = evaluated.matrix_world.copy()
    mesh = _plain_mesh(obj)
    if mesh is not None:
        key = (int(getattr(mesh, "session_uid", 0) or 0) or mesh.as_pointer(), mesh.name_full)
        digest = _mesh_digest(mesh)
        cached = _MESH_CACHE.get(key)
        if cached is not None and cached[0] == digest:
            return matrix, cached[1]
        topology = _mesh_topology(mesh)
        if len(_MESH_CACHE) >= _MESH_CACHE_LIMIT:
            _MESH_CACHE.clear()
        _MESH_CACHE[key] = (digest, topology)
        return matrix, topology
    evaluated_mesh = evaluated.to_mesh()
    try:
        return matrix, _mesh_topology(evaluated_mesh)
    finally:
        evaluated.to_mesh_clear()


def _handle_geometry(obj, depsgraph):
    """World-space triangles per part, rim segments and guide segments of one handle."""
    matrix, topology = handle_mesh(obj, depsgraph)
    points = [matrix @ vertex for vertex in topology["vertices"]]
    triangles = {}
    for part, indices in topology["triangles"]:
        triangles.setdefault(part, []).extend(points[index] for index in indices)
    rim = [points[index] for key in topology["rim"] for index in key]
    guides = [points[index] for edge in topology["guides"] for index in edge]
    return triangles, rim, guides


_BOUNDS_CORNERS = ("TOP_LEFT", "TOP_RIGHT", "BOTTOM_RIGHT", "BOTTOM_LEFT")


def _bounds_role(obj):
    """``(frame key, role)`` of a Crop/Extend or Shape Mask bounds handle."""
    try:
        from .effect_controls import KEY_EFFECT_ID, KEY_MODE, KEY_ROLE
        mode = str(obj.get(KEY_MODE, "") or "").upper()
        if mode == "CROP_EXTEND":
            from .viewport_handles import attached_plane
            role = str(obj.get(KEY_ROLE, "") or "").upper()
            owner = attached_plane(obj)
            return (("CROP", getattr(owner, "name", ""), str(obj.get(KEY_EFFECT_ID, "") or "")), role)
        from .object_masks import KEY_HANDLE_HELPER_NAME, KEY_HANDLE_ROLE, is_object_mask_bounds_handle
        if is_object_mask_bounds_handle(obj):
            role = str(obj.get(KEY_HANDLE_ROLE, "") or "").upper()
            return (("MASK", str(obj.get(KEY_HANDLE_HELPER_NAME, "") or "")), role)
    except (ImportError, *FBP_DATA_ERRORS):
        return None
    return None


def _triangles_center(triangles):
    points = [point for part in triangles.values() for point in part]
    if not points:
        return None
    total = Vector((0.0, 0.0, 0.0))
    for point in points:
        total += point
    return total / len(points)


def _draw_lines(shader, segments, width, color):
    if not segments:
        return
    shader.uniform_float("lineWidth", width)
    shader.uniform_float("color", color)
    batch_for_shader(shader, "LINES", {"pos": segments}).draw(shader)


_THEME_ACCENT = {"value": None}


def _follow_theme(context):
    """Recolour the Lattice handles once the theme's accent changes."""
    accent = tuple(round(value, 4) for value in handle_selected_color(context)[:3])
    if _THEME_ACCENT["value"] == accent:
        return
    _THEME_ACCENT["value"] = accent

    def refresh():
        try:
            from .lattice_bones import refresh_theme_colors
            refresh_theme_colors()
        except (ImportError,) + FBP_DATA_ERRORS:
            pass
        return None

    # Drawing must not edit data: recolour right after this redraw.
    bpy.app.timers.register(refresh, first_interval=0.0)


def _draw_handles():
    context = bpy.context
    space = getattr(context, "space_data", None)
    region = getattr(context, "region", None)
    if space is None or region is None:
        return
    try:
        if not bool(space.overlay.show_overlays):
            return
    except FBP_DATA_ERRORS:
        return
    _follow_theme(context)
    handles = _visible_handles(context)
    mask_guides = _mask_guides(context)
    lattice_guides = _lattice_guides(context)
    plane_guides, plane_hover_guides = _color_plane_guides(context)
    try:
        from .layer_cage import hovered_handle_name
        hovered = hovered_handle_name(region)
    except ImportError:
        hovered = ""
    hovered_bone = _hovered_lattice_triangles(hovered)
    if not handles and not mask_guides and not lattice_guides and not hovered_bone and not plane_guides and not plane_hover_guides:
        return
    try:
        depsgraph = context.evaluated_depsgraph_get()
    except FBP_DATA_ERRORS:
        return
    fill_shader, line_shader = _shaders()
    scale = _ui_scale(context)
    guides = list(lattice_guides) + plane_guides
    for solid, _dashed in mask_guides:
        guides.extend(solid)
    for _solid, dashed in mask_guides:
        guides.extend(dashed)
    selected_color = handle_selected_color(context)
    hover_color = _handle_hover_color(context)
    shapes = []
    if hovered_bone:
        shapes.append(([(hovered_bone, hover_color)], []))
    hover_guides = list(plane_hover_guides)
    frames = {}
    for obj in handles:
        try:
            triangles, rim, handle_guides = _handle_geometry(obj, depsgraph)
            fixed = handle_screen_scale(obj, region, context.region_data, scale)
            if fixed is not None:
                triangles = {part: _scaled(points, *fixed) for part, points in triangles.items()}
                rim = _scaled(rim, *fixed)
            selected = bool(obj.select_get())
            hover = bool(hovered) and not selected and obj.name == hovered
        except FBP_DATA_ERRORS:
            continue
        # A hovered gradient line lights up with its grip.
        (hover_guides if hover else guides).extend(handle_guides)
        if not triangles:
            continue
        bounds = _bounds_role(obj)
        if bounds is not None and bounds[0][0] == "CROP":
            # Crop/Expand draw their own L corners and side bars, all shown.
            bounds = None
        if bounds is not None:
            frame = frames.setdefault(bounds[0], {"corners": {}, "sides": []})
            center = _triangles_center(triangles)
            if bounds[1] in _BOUNDS_CORNERS and center is not None:
                frame["corners"][bounds[1]] = center
            elif not selected and not hover:
                # Edge dots appear when the cursor comes near the frame.
                frame["sides"].append((triangles, rim, center))
                continue
        fills = []
        accent = selected_color if selected else hover_color if hover else HANDLE_COLOR
        if PART_HANDLE in triangles:
            fills.append((triangles[PART_HANDLE], accent))
        if PART_STOP_RING in triangles:
            ring = selected_color if selected else hover_color if hover else STOP_RING_COLOR
            fills.append((triangles[PART_STOP_RING], ring))
        shapes.append((fills, rim))
    for key, frame in frames.items():
        corners = [frame["corners"].get(role) for role in _BOUNDS_CORNERS]
        if all(corner is not None for corner in corners):
            # The frame is a thin line between the corner dots.
            for index in range(4):
                guides.extend((corners[index], corners[(index + 1) % 4]))
        try:
            from .layer_cage import proximity_near
            screen = [
                location_3d_to_region_2d(region, context.region_data, point)
                for point in [*frame["corners"].values(), *(center for _t, _r, center in frame["sides"])]
                if point is not None
            ]
            near = proximity_near(("bounds", key), region, screen)
        except (ImportError, *FBP_DATA_ERRORS):
            near = True
        if near:
            for triangles, rim, _center in frame["sides"]:
                shapes.append(([(triangles[part], HANDLE_COLOR) for part in triangles], rim))
    if not shapes and not guides and not hover_guides:
        return
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE")
    gpu.state.depth_mask_set(False)
    try:
        line_shader.bind()
        line_shader.uniform_float("viewportSize", (region.width, region.height))
        # Guides sit under the handles: a dark halo, then the light line.
        _draw_lines(line_shader, guides, _GUIDE_OUTLINE_WIDTH * scale, GUIDE_OUTLINE_COLOR)
        _draw_lines(line_shader, guides, _GUIDE_WIDTH * scale, GUIDE_COLOR)
        _draw_lines(line_shader, hover_guides, _GUIDE_OUTLINE_WIDTH * scale, GUIDE_OUTLINE_COLOR)
        _draw_lines(line_shader, hover_guides, _GUIDE_WIDTH * scale, hover_color)
        # Rims next: the fills cover their inner half, leaving a thin edge.
        _draw_lines(
            line_shader,
            [point for _fills, rim in shapes for point in rim],
            _OUTLINE_WIDTH * scale,
            HANDLE_OUTLINE_COLOR,
        )
        fill_shader.bind()
        for fills, _rim in shapes:
            for triangles, color in fills:
                fill_shader.uniform_float("color", color)
                batch_for_shader(fill_shader, "TRIS", {"pos": triangles}).draw(fill_shader)
    finally:
        gpu.state.depth_mask_set(True)
        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.blend_set("NONE")


# --- Gradient colour stops --------------------------------------------------
#
# Gradient Light and Gradient Mask draw a base line from IN to OUT: its end
# dots (the IN/OUT handle objects) set the direction and the in-out span, and
# the line itself moves the gradient. The colours sit beside the line, as
# small circles on a short stem, so they never cover it: drag one along the
# line to move that colour, click it to change the colour. A radial gradient
# does the same along its radius.

_STOP_EPSILON = 0.001
_STOP_OFFSET = 2.6          # Circle centre above the line, in circle radii.
_STOP_CLICK_PX = 4.0        # Less movement than this is a click.
_STOP_MIN_SPAN = 0.02       # The end stops never meet (fraction of the line).
_GRADIENT_EFFECTS = ("GRADIENT_LIGHT", "GRADIENT_MASK", "COLOR_PLANE")


def _evaluated_center(obj, depsgraph):
    evaluated = obj.evaluated_get(depsgraph)
    corners = [Vector(corner) for corner in evaluated.bound_box]
    return evaluated.matrix_world @ (sum(corners, Vector()) / 8.0)


def _gradient_stop_targets(context, effects=_GRADIENT_EFFECTS):
    """Yield ``(rig, effect_id, in_control, out_control, start, end, normal)``
    for every visible gradient line of ``effects``."""
    try:
        from . import effect_controls as controls
    except ImportError:
        return
    try:
        depsgraph = context.evaluated_depsgraph_get()
    except FBP_DATA_ERRORS:
        return
    if "COLOR_PLANE" in effects:
        # Gradient Color Planes have no handle objects: their line comes
        # from the material's mapping.
        for rig, _frame, _radial, start, end, normal in color_plane_gradient_targets(context):
            yield rig, COLOR_PLANE_ID, None, None, start, end, normal
    for control in controls.iter_visible_effect_controls(context):
        try:
            effect_id = str(control.get(controls.KEY_EFFECT_ID, "") or "")
            if effect_id not in effects or str(control.get(controls.KEY_ROLE, "") or "") != "IN":
                continue
            rig = controls.effect_control_owner(control)
            out_control = controls.find_effect_control(rig, effect_id, "OUT") if rig else None
            if out_control is None or not out_control.visible_get():
                continue
            if effect_id == "GRADIENT_LIGHT" and controls.gradient_light_ramp(rig) is None:
                continue
            start = _evaluated_center(control, depsgraph)
            end = _evaluated_center(out_control, depsgraph)
            normal = control.matrix_world.col[2].xyz.normalized()
        except FBP_DATA_ERRORS:
            continue
        if (end - start).length <= 1.0e-6 or normal.length <= 1.0e-6:
            continue
        yield rig, effect_id, control, out_control, start, end, normal


def _gradient_stops(rig, effect_id, in_control, out_control):
    """``(key, t, colour)`` per stop: ``t`` runs 0 at IN to 1 at OUT.

    ``key`` is "IN" or "OUT" for the stops on the line's ends (dragging them
    moves that end), or the Color Ramp index of a stop in between.
    """
    from . import effect_controls as controls
    if effect_id == "COLOR_PLANE":
        # The line runs from the ramp's 0 to its 1: every stop sits at its
        # own position, and each one, the end ones too, slides on its own.
        elements = tuple(getattr(color_plane_ramp(rig), "elements", ()) or ())
        return [
            (index, float(element.position), controls._display_color(element.color))
            for index, element in enumerate(elements)
        ]
    if effect_id == "GRADIENT_MASK":
        return [
            ("IN", 0.0, controls.control_swatch_color(in_control) or (1.0, 1.0, 1.0, 1.0)),
            ("OUT", 1.0, controls.control_swatch_color(out_control) or (0.0, 0.0, 0.0, 1.0)),
        ]
    ramp = controls.gradient_light_ramp(rig)
    elements = tuple(getattr(ramp, "elements", ()) or ())
    if len(elements) < 2:
        return []
    first, last = float(elements[0].position), float(elements[-1].position)
    span = last - first
    stops = []
    for index, element in enumerate(elements):
        if index == 0:
            key, t = "IN", 0.0
        elif index == len(elements) - 1:
            key, t = "OUT", 1.0
        else:
            key = index
            t = (float(element.position) - first) / span if abs(span) > 1.0e-9 else 0.5
        stops.append((key, t, controls._display_color(element.color)))
    return stops


def _fit_gizmos(gizmos, count, idname):
    """Give a gizmo group exactly ``count`` usable gizmos.

    A gizmo being dragged is never removed: Blender's modal handler still
    points at it, and freeing it mid-drag (an end dot dropped on the other
    end, a layer deselected by a script) crashes Blender. Spare gizmos are
    hidden until the drag ends and the next redraw trims them.
    """
    while len(gizmos) < count:
        gizmos.new(idname)
    if any(gizmo.is_modal for gizmo in gizmos):
        for index, gizmo in enumerate(gizmos):
            if not gizmo.is_modal:
                gizmo.hide = index >= count
        return
    while len(gizmos) > count:
        gizmos.remove(gizmos[-1])
    for gizmo in gizmos:
        if gizmo.hide:
            gizmo.hide = False


def _ring_triangles(outer, inner, segments=32, center=(0.0, 0.0)):
    cx, cy = center
    triangles = []
    for index in range(segments):
        a0 = math.tau * index / segments
        a1 = math.tau * (index + 1) / segments
        p0o = (cx + math.cos(a0) * outer, cy + math.sin(a0) * outer, 0.0)
        p1o = (cx + math.cos(a1) * outer, cy + math.sin(a1) * outer, 0.0)
        p0i = (cx + math.cos(a0) * inner, cy + math.sin(a0) * inner, 0.0)
        p1i = (cx + math.cos(a1) * inner, cy + math.sin(a1) * inner, 0.0)
        triangles.extend((p0o, p1o, p1i, p0o, p1i, p0i))
    return triangles


def _disc_triangles(radius, segments=32, center=(0.0, 0.0)):
    cx, cy = center
    triangles = []
    for index in range(segments):
        a0 = math.tau * index / segments
        a1 = math.tau * (index + 1) / segments
        triangles.extend((
            (cx, cy, 0.0),
            (cx + math.cos(a0) * radius, cy + math.sin(a0) * radius, 0.0),
            (cx + math.cos(a1) * radius, cy + math.sin(a1) * radius, 0.0),
        ))
    return triangles


def _rect_triangles(x0, y0, x1, y1):
    return [(x0, y0, 0.0), (x1, y0, 0.0), (x1, y1, 0.0), (x0, y0, 0.0), (x1, y1, 0.0), (x0, y1, 0.0)]


class FBP_GT_gradient_stop(bpy.types.Gizmo):
    """One colour stop beside a gradient line: drag along the line, click to edit."""

    bl_idname = "FBP_GT_gradient_stop"
    __slots__ = (
        "fbp_rim", "fbp_ring", "fbp_disc", "fbp_stem", "fbp_stem_rim",
        "fbp_rig_name", "fbp_effect_id", "fbp_key", "fbp_start", "fbp_end",
        "fbp_swatch", "fbp_initial", "fbp_press", "fbp_moved",
    )

    def setup(self):
        # Local units: the circle's radius is 1, its centre _STOP_OFFSET
        # above the line; the stem joins it to the line at the origin.
        centre = (0.0, _STOP_OFFSET)
        self.fbp_rim = self.new_custom_shape("TRIS", _ring_triangles(1.1, 0.95, center=centre))
        self.fbp_ring = self.new_custom_shape("TRIS", _ring_triangles(1.0, 0.78, center=centre))
        self.fbp_disc = self.new_custom_shape("TRIS", _disc_triangles(0.8, center=centre))
        stem_top = _STOP_OFFSET - 0.98
        self.fbp_stem = self.new_custom_shape("TRIS", _rect_triangles(-0.07, 0.0, 0.07, stem_top))
        self.fbp_stem_rim = self.new_custom_shape("TRIS", _rect_triangles(-0.2, -0.12, 0.2, stem_top))
        self.fbp_swatch = (1.0, 1.0, 1.0)
        self.fbp_key = ""
        self.fbp_effect_id = ""
        self.fbp_initial = None
        self.fbp_press = None
        self.fbp_moved = False
        # A fixed size on screen, like the other handles (see draw_prepare).
        self.use_draw_scale = True

    def _draw_part(self, shape, color, alpha=1.0):
        self.color = color
        self.color_highlight = color
        self.alpha = alpha
        self.alpha_highlight = alpha
        self.draw_custom_shape(shape)

    def draw(self, context):
        active = self.is_highlight or self.is_modal
        accent = handle_selected_color(context)[:3] if active else STOP_RING_COLOR[:3]
        self._draw_part(self.fbp_stem_rim, (0.0, 0.0, 0.0), 0.45)
        self._draw_part(self.fbp_stem, accent)
        self._draw_part(self.fbp_rim, (0.0, 0.0, 0.0), 0.45)
        self._draw_part(self.fbp_ring, accent)
        self._draw_part(self.fbp_disc, tuple(self.fbp_swatch))

    def draw_select(self, context, select_id):
        del context
        self.draw_custom_shape(self.fbp_ring, select_id=select_id)
        self.draw_custom_shape(self.fbp_disc, select_id=select_id)

    # --- Data ---------------------------------------------------------------

    def _rig(self):
        return bpy.data.objects.get(self.fbp_rig_name or "")

    def _ramp_element(self):
        try:
            if self.fbp_effect_id == COLOR_PLANE_ID:
                ramp = color_plane_ramp(self._rig())
            else:
                from .effect_controls import gradient_light_ramp
                ramp = gradient_light_ramp(self._rig())
            return ramp, ramp.elements[int(self.fbp_key)]
        except (ImportError, IndexError, TypeError, ValueError) + FBP_DATA_ERRORS:
            return None, None

    def _end_controls(self):
        try:
            from .effect_controls import find_effect_control
            rig = self._rig()
            return (
                find_effect_control(rig, self.fbp_effect_id, "IN"),
                find_effect_control(rig, self.fbp_effect_id, "OUT"),
            )
        except (ImportError,) + FBP_DATA_ERRORS:
            return None, None

    def _is_end(self):
        return self.fbp_key in {"IN", "OUT"}

    # --- Interaction --------------------------------------------------------

    def invoke(self, context, event):
        del context
        self.fbp_press = (event.mouse_region_x, event.mouse_region_y)
        self.fbp_moved = False
        if self._is_end():
            in_control, out_control = self._end_controls()
            if in_control is None or out_control is None:
                return {"CANCELLED"}
            self.fbp_initial = (tuple(in_control.location), tuple(out_control.location))
        else:
            _ramp, element = self._ramp_element()
            if element is None:
                return {"CANCELLED"}
            self.fbp_initial = float(element.position)
        return {"RUNNING_MODAL"}

    def _line_parameter(self, context, event):
        region, view = context.region, context.region_data
        start = location_3d_to_region_2d(region, view, Vector(self.fbp_start))
        end = location_3d_to_region_2d(region, view, Vector(self.fbp_end))
        if start is None or end is None:
            return None
        axis = end - start
        length_sq = axis.length_squared
        if length_sq <= 1.0e-6:
            return None
        mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        return (mouse - start).dot(axis) / length_sq

    def modal(self, context, event, tweak):
        del tweak
        if not self.fbp_moved and self.fbp_press is not None:
            dx = event.mouse_region_x - self.fbp_press[0]
            dy = event.mouse_region_y - self.fbp_press[1]
            if dx * dx + dy * dy < _STOP_CLICK_PX * _STOP_CLICK_PX:
                return {"RUNNING_MODAL"}
            self.fbp_moved = True
        t = self._line_parameter(context, event)
        if t is None:
            return {"RUNNING_MODAL"}
        if self._is_end():
            self._move_end(t)
        else:
            self._move_stop(t)
        context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def _move_stop(self, t):
        ramp, element = self._ramp_element()
        if element is None:
            return
        elements = ramp.elements
        index = int(self.fbp_key)
        if self.fbp_effect_id == COLOR_PLANE_ID:
            # A Color Plane's line spans the whole ramp, 0 to 1, so every
            # stop moves, the end ones included.
            position = t
        else:
            first, last = float(elements[0].position), float(elements[-1].position)
            position = first + t * (last - first)
        # Stay between the neighbours: Blender keeps ramp stops sorted.
        low = float(elements[index - 1].position) + _STOP_EPSILON if index > 0 else 0.0
        high = float(elements[index + 1].position) - _STOP_EPSILON if index < len(elements) - 1 else 1.0
        position = max(low, min(high, position))
        if abs(float(element.position) - position) > 1.0e-6:
            element.position = position

    def _move_end(self, t):
        """Slide IN or OUT along the line, as if its end dot had been dragged there."""
        in_control, out_control = self._end_controls()
        if in_control is None or out_control is None or self.fbp_initial is None:
            return
        in0, out0 = (Vector(value) for value in self.fbp_initial)
        if self.fbp_key == "IN":
            control, t = in_control, min(t, 1.0 - _STOP_MIN_SPAN)
        else:
            control, t = out_control, max(t, _STOP_MIN_SPAN)
        target = in0.lerp(out0, t)
        if (Vector(control.location) - target).length <= 1.0e-7:
            return
        control.location = target
        _sync_control(control)

    def exit(self, context, cancel):
        if cancel:
            self._restore()
        elif self.fbp_moved:
            _undo_push("Move Gradient Stop")
        else:
            self._click(context)
        context.area.tag_redraw()

    def _restore(self):
        if self.fbp_initial is None:
            return
        if self._is_end():
            in_control, out_control = self._end_controls()
            for control, location in zip((in_control, out_control), self.fbp_initial):
                if control is not None and tuple(control.location) != tuple(location):
                    control.location = location
                    _sync_control(control)
        else:
            _ramp, element = self._ramp_element()
            if element is not None:
                element.position = self.fbp_initial

    def _click(self, context):
        rig = self._rig()
        if rig is None:
            return
        if self.fbp_effect_id == "GRADIENT_MASK":
            # A mask has no colours to pick: clicking a stop swaps them.
            try:
                rig.fbp_gradient_mask_invert = not bool(rig.fbp_gradient_mask_invert)
            except FBP_DATA_ERRORS:
                return
            _undo_push("Invert Gradient Mask")
            return
        if self.fbp_key == "IN":
            index = 0
        elif self.fbp_key == "OUT":
            index = -1
        else:
            index = int(self.fbp_key)
        source = "COLOR_PLANE" if self.fbp_effect_id == COLOR_PLANE_ID else "GRADIENT_LIGHT"
        try:
            with context.temp_override(window=context.window, area=context.area, region=context.region):
                bpy.ops.fbp.gradient_stop_color("INVOKE_DEFAULT", rig_name=rig.name, index=index, source=source)
        except (RuntimeError, TypeError, AttributeError):
            pass


class FBP_OT_gradient_stop_color(bpy.types.Operator):
    """Change the colour of a gradient stop"""

    bl_idname = "fbp.gradient_stop_color"
    bl_label = "Gradient Stop Color"
    bl_description = "Change the colour of this gradient stop"
    bl_options = {"REGISTER", "UNDO"}

    rig_name: bpy.props.StringProperty(options={"HIDDEN"})
    index: bpy.props.IntProperty(default=0, options={"HIDDEN"})
    source: bpy.props.StringProperty(default="GRADIENT_LIGHT", options={"HIDDEN"})

    def _target(self, context):
        """``(owner, property)`` that holds the stop's colour."""
        del context
        rig = bpy.data.objects.get(self.rig_name or "")
        if self.source == "COLOR_PLANE":
            return _color_plane_stop_target(rig, self.index)
        try:
            from .effect_controls import gradient_light_ramp
            ramp = gradient_light_ramp(rig)
            elements = ramp.elements
            index = self.index if self.index >= 0 else len(elements) + self.index
            if index == 0 and hasattr(rig, "fbp_gradient_shadow_color"):
                # The first stop follows the effect's Shadow Color.
                return rig, "fbp_gradient_shadow_color"
            return elements[index], "color"
        except (ImportError, IndexError, TypeError) + FBP_DATA_ERRORS:
            return None, ""

    def invoke(self, context, event):
        del event
        owner, _name = self._target(context)
        if owner is None:
            return {"CANCELLED"}
        return context.window_manager.invoke_popup(self, width=220)

    def draw(self, context):
        owner, name = self._target(context)
        if owner is None:
            return
        layout = self.layout
        layout.template_color_picker(owner, name, value_slider=True)
        layout.prop(owner, name, text="")

    def execute(self, context):
        del context
        return {"FINISHED"}


# --- Color Plane gradients --------------------------------------------------
#
# A Gradient Color Plane has no handle objects: its line, end dots and stops
# are all gizmos. The shader works in the plane's UVs: the ramp runs from 0
# to 1 along Gradient Rotation, centred on 0.5 + Offset, over Scale (linear),
# or from 1 at the centre to 0 on an ellipse of radius Scale / 2 (radial).
# The line goes from the ramp's 0 to its 1; dragging its ends rewrites
# Offset, Rotation and Scale, keeping the Scale X/Y ratio.

COLOR_PLANE_ID = "COLOR_PLANE"


def _is_gradient_color_plane(rig):
    try:
        return bool(
            getattr(rig, "fbp_is_color_plane", False)
            and str(getattr(rig, "fbp_color_plane_mode", "") or "") == "GRADIENT"
        )
    except FBP_DATA_ERRORS:
        return False


def color_plane_ramp(rig):
    try:
        from .materials import find_fbp_gradient_ramp_node, get_fbp_gradient_material_from_rig
        node = find_fbp_gradient_ramp_node(get_fbp_gradient_material_from_rig(rig))
        return getattr(node, "color_ramp", None)
    except (ImportError,) + FBP_DATA_ERRORS:
        return None


def _color_plane_frame(rig):
    """``(plane, min_x, min_y, width, height)``: how UVs sit on the plane."""
    plane = getattr(rig, "fbp_plane_target", None)
    vertices = tuple(getattr(getattr(plane, "data", None), "vertices", ()) or ())
    if plane is None or not vertices:
        return None
    xs = [float(vertex.co.x) for vertex in vertices]
    ys = [float(vertex.co.y) for vertex in vertices]
    width, height = max(xs) - min(xs), max(ys) - min(ys)
    if width <= 1.0e-9 or height <= 1.0e-9:
        return None
    return plane, min(xs), min(ys), width, height


def _uv_to_world(frame, uv):
    plane, min_x, min_y, width, height = frame
    return plane.matrix_world @ Vector((min_x + uv[0] * width, min_y + uv[1] * height, 0.0))


def _world_to_uv(frame, world):
    plane, min_x, min_y, width, height = frame
    local = plane.matrix_world.inverted_safe() @ world
    return Vector(((local.x - min_x) / width, (local.y - min_y) / height))


def color_plane_endpoints(rig):
    """``(radial, uv_0, uv_1)``: where the ramp's 0 and 1 sit, in UVs."""
    radial = str(getattr(rig, "fbp_gradient_mode", "LINEAR") or "LINEAR") == "CENTER"
    centre = Vector((0.5 + float(rig.fbp_gradient_offset_x), 0.5 + float(rig.fbp_gradient_offset_y)))
    angle = math.radians(float(rig.fbp_gradient_rotation))
    scale_x = max(0.001, float(rig.fbp_gradient_scale_x))
    scale_y = max(0.001, float(rig.fbp_gradient_scale_y))
    if radial:
        edge = centre + Vector((0.5 * scale_x * math.cos(angle), -0.5 * scale_y * math.sin(angle)))
        return True, edge, centre
    # fac = 0.5 + d . (uv - centre), d = (cos a / Sx, -sin a / Sy).
    d = Vector((math.cos(angle) / scale_x, -math.sin(angle) / scale_y))
    span = d / max(d.length_squared, 1.0e-12)
    return False, centre - span * 0.5, centre + span * 0.5


def apply_color_plane_endpoints(rig, uv_0, uv_1):
    """Rewrite Offset, Rotation and Scale so the ramp runs from ``uv_0`` to ``uv_1``."""
    radial = str(getattr(rig, "fbp_gradient_mode", "LINEAR") or "LINEAR") == "CENTER"
    ratio = max(0.001, float(rig.fbp_gradient_scale_y)) / max(0.001, float(rig.fbp_gradient_scale_x))
    if radial:
        centre = Vector(uv_1)
        v = Vector(uv_0) - centre
        if v.length <= 1.0e-6:
            return False
        angle = math.atan2(-v.y / ratio, v.x)
        scale_x = 2.0 * math.hypot(v.x, v.y / ratio)
    else:
        span = Vector(uv_1) - Vector(uv_0)
        if span.length <= 1.0e-6:
            return False
        d = span / span.length_squared
        angle = math.atan2(-d.y * ratio, d.x)
        scale_x = 1.0 / max(math.hypot(d.x, d.y * ratio), 1.0e-9)
        centre = (Vector(uv_0) + Vector(uv_1)) * 0.5
    values = {
        "fbp_gradient_rotation": math.degrees(angle),
        "fbp_gradient_scale_x": max(0.001, scale_x),
        "fbp_gradient_scale_y": max(0.001, scale_x * ratio),
    }
    offset = (float(centre.x) - 0.5, float(centre.y) - 0.5)
    controller = getattr(rig, "fbp_gradient_controller", None)
    frame = _color_plane_frame(rig)
    if controller is not None and frame is not None:
        # The offset is driven by the Gradient Controller: move it instead.
        controller.location.x = offset[0] * frame[3]
        controller.location.y = offset[1] * frame[4]
    else:
        values["fbp_gradient_offset_x"] = offset[0]
        values["fbp_gradient_offset_y"] = offset[1]
    for name, value in values.items():
        if abs(float(getattr(rig, name)) - value) > 1.0e-7:
            setattr(rig, name, value)
    return True


def _color_plane_stop_target(rig, index):
    """``(owner, property)`` of a Color Plane stop's colour. The ramp is the
    source of truth: a material rebuild restores it, From/To only seed it."""
    ramp = color_plane_ramp(rig)
    try:
        return ramp.elements[index], "color"
    except (IndexError, TypeError, AttributeError) + FBP_DATA_ERRORS:
        return None, ""


def color_plane_gradient_targets(context):
    """Yield ``(rig, frame, radial, world_0, world_1, normal)`` for each
    selected Gradient Color Plane."""
    for rig in tuple(getattr(context, "selected_objects", ()) or ()):
        if not _is_gradient_color_plane(rig):
            continue
        try:
            plane = getattr(rig, "fbp_plane_target", None)
            if plane is None or not plane.visible_get() or color_plane_ramp(rig) is None:
                continue
            frame = _color_plane_frame(rig)
            if frame is None:
                continue
            radial, uv_0, uv_1 = color_plane_endpoints(rig)
            world_0, world_1 = _uv_to_world(frame, uv_0), _uv_to_world(frame, uv_1)
            normal = plane.matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0))
        except (ZeroDivisionError,) + FBP_DATA_ERRORS:
            continue
        if (world_1 - world_0).length <= 1.0e-6 or normal.length <= 1.0e-9:
            continue
        yield rig, frame, radial, world_0, world_1, normal.normalized()


def color_plane_gradient_shown(context, rig):
    return any(item[0] == rig for item in color_plane_gradient_targets(context))


_CP_DOT_RADIUS = 0.42      # End dots, in HANDLE_SCREEN_SIZE_PX units.


class FBP_GT_color_plane_grip(bpy.types.Gizmo):
    """A Color Plane gradient's end dot ("0"/"1") or its line ("LINE")."""

    bl_idname = "FBP_GT_color_plane_grip"
    __slots__ = (
        "fbp_rig_name", "fbp_kind", "fbp_a", "fbp_b", "fbp_dot", "fbp_dot_rim",
        "fbp_initial", "fbp_press", "fbp_moved", "fbp_hit",
    )

    def setup(self):
        self.fbp_dot = self.new_custom_shape("TRIS", _disc_triangles(1.0))
        self.fbp_dot_rim = self.new_custom_shape("TRIS", _disc_triangles(1.35))
        self.fbp_kind = ""
        self.fbp_initial = None
        self.fbp_press = None
        self.fbp_moved = False
        self.use_draw_scale = True

    def draw(self, context):
        if self.fbp_kind == "LINE":
            return  # The overlay draws the line.
        active = self.is_highlight or self.is_modal
        color = _handle_hover_color(context)[:3] if active else HANDLE_COLOR[:3]
        for shape, tint, alpha in ((self.fbp_dot_rim, (0.0, 0.0, 0.0), 0.45), (self.fbp_dot, color, 1.0)):
            self.color = tint
            self.color_highlight = tint
            self.alpha = alpha
            self.alpha_highlight = alpha
            self.draw_custom_shape(shape)

    def test_select(self, context, location):
        region, view = context.region, context.region_data
        scale = _ui_scale(context)
        a = location_3d_to_region_2d(region, view, Vector(self.fbp_a))
        if a is None:
            return -1
        mouse = Vector(location)
        dot = _DRAG_DOT_PX * scale
        if self.fbp_kind != "LINE":
            hit = (mouse - a).length <= dot
        else:
            b = location_3d_to_region_2d(region, view, Vector(self.fbp_b))
            hit = False
            if b is not None and (b - a).length_squared > 1.0e-6:
                axis = b - a
                t = (mouse - a).dot(axis) / axis.length_squared
                hit = (
                    0.0 <= t <= 1.0
                    and (mouse - a).length > dot and (mouse - b).length > dot
                    and (mouse - (a + axis * t)).length <= _DRAG_LINE_PX * scale
                )
        if hit:
            try:
                from .layer_cage import set_hovered_handle
                set_hovered_handle(context, f"{COLOR_PLANE_ID}:{self.fbp_rig_name}:{self.fbp_kind}")
            except ImportError:
                pass
        return 0 if hit else -1

    def invoke(self, context, event):
        rig = bpy.data.objects.get(self.fbp_rig_name or "")
        frame = _color_plane_frame(rig) if rig is not None else None
        if frame is None:
            return {"CANCELLED"}
        self.fbp_press = (event.mouse_region_x, event.mouse_region_y)
        self.fbp_moved = False
        normal = (frame[0].matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()
        hit = _plane_hit(context.region, context.region_data, self.fbp_press, frame[0].matrix_world.translation, normal)
        if hit is None:
            return {"CANCELLED"}
        _radial, uv_0, uv_1 = color_plane_endpoints(rig)
        controller = getattr(rig, "fbp_gradient_controller", None)
        self.fbp_hit = tuple(_world_to_uv(frame, hit))
        self.fbp_initial = {
            "uv": (tuple(uv_0), tuple(uv_1)),
            "props": {
                name: float(getattr(rig, name)) for name in (
                    "fbp_gradient_rotation", "fbp_gradient_scale_x", "fbp_gradient_scale_y",
                    "fbp_gradient_offset_x", "fbp_gradient_offset_y",
                )
            },
            "controller": tuple(controller.location) if controller is not None else None,
            "normal": tuple(normal),
        }
        return {"RUNNING_MODAL"}

    def modal(self, context, event, tweak):
        del tweak
        if not self.fbp_moved:
            dx = event.mouse_region_x - self.fbp_press[0]
            dy = event.mouse_region_y - self.fbp_press[1]
            if dx * dx + dy * dy < _STOP_CLICK_PX * _STOP_CLICK_PX:
                return {"RUNNING_MODAL"}
            self.fbp_moved = True
        rig = bpy.data.objects.get(self.fbp_rig_name or "")
        frame = _color_plane_frame(rig) if rig is not None else None
        if frame is None:
            return {"RUNNING_MODAL"}
        hit = _plane_hit(
            context.region, context.region_data, (event.mouse_region_x, event.mouse_region_y),
            frame[0].matrix_world.translation, Vector(self.fbp_initial["normal"]),
        )
        if hit is None:
            return {"RUNNING_MODAL"}
        delta = _world_to_uv(frame, hit) - Vector(self.fbp_hit)
        uv_0, uv_1 = (Vector(value) for value in self.fbp_initial["uv"])
        radial = str(getattr(rig, "fbp_gradient_mode", "LINEAR") or "LINEAR") == "CENTER"
        if self.fbp_kind == "LINE" or (radial and self.fbp_kind == "1"):
            # The line, or a radial gradient's centre, moves the whole gradient.
            uv_0, uv_1 = uv_0 + delta, uv_1 + delta
        elif self.fbp_kind == "0":
            uv_0 = uv_0 + delta
        else:
            uv_1 = uv_1 + delta
        _apply_color_plane(rig, uv_0, uv_1)
        context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def exit(self, context, cancel):
        rig = bpy.data.objects.get(self.fbp_rig_name or "")
        if cancel and rig is not None and self.fbp_initial is not None:
            for name, value in self.fbp_initial["props"].items():
                if abs(float(getattr(rig, name)) - value) > 1.0e-9:
                    setattr(rig, name, value)
            controller = getattr(rig, "fbp_gradient_controller", None)
            if controller is not None and self.fbp_initial["controller"] is not None:
                controller.location = self.fbp_initial["controller"]
        elif self.fbp_moved:
            _undo_push("Move Gradient")
        elif rig is not None:
            # A click on the line or a dot selects the plane, nothing else.
            for obj in tuple(context.selected_objects):
                if obj != rig:
                    obj.select_set(False)
            rig.select_set(True)
            context.view_layer.objects.active = rig
            _undo_push("Select")
        context.area.tag_redraw()


def _apply_color_plane(rig, uv_0, uv_1):
    try:
        apply_color_plane_endpoints(rig, uv_0, uv_1)
    except (ZeroDivisionError,) + FBP_DATA_ERRORS:
        pass


class FBP_GGT_color_plane_gradient(bpy.types.GizmoGroup):
    bl_idname = "FBP_GGT_color_plane_gradient"
    bl_label = "Frame By Plane Color Plane Gradient"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}

    @classmethod
    def poll(cls, context):
        try:
            if context.mode != "OBJECT" or not context.space_data.overlay.show_overlays:
                return False
        except FBP_DATA_ERRORS:
            return False
        return next(color_plane_gradient_targets(context), None) is not None

    def setup(self, context):
        self.draw_prepare(context)

    def draw_prepare(self, context):
        grips = []
        for rig, _frame, radial, world_0, world_1, _normal in color_plane_gradient_targets(context):
            grips.append((rig.name, "LINE", world_0, world_1))
            grips.append((rig.name, "0", world_0, world_0))
            grips.append((rig.name, "1", world_1, world_1))
        try:
            gizmo_size = max(float(context.preferences.view.gizmo_size), 1.0)
        except FBP_DATA_ERRORS:
            gizmo_size = 75.0
        gizmos = self.gizmos
        _fit_gizmos(gizmos, len(grips), FBP_GT_color_plane_grip.bl_idname)
        for gizmo, (rig_name, kind, a, b) in zip(gizmos, grips):
            if gizmo.is_modal:
                continue
            gizmo.fbp_rig_name = rig_name
            gizmo.fbp_kind = kind
            gizmo.fbp_a = tuple(a)
            gizmo.fbp_b = tuple(b)
            view_rotation = context.region_data.view_rotation.to_matrix().to_4x4()
            gizmo.matrix_basis = Matrix.Translation(a) @ view_rotation
            gizmo.scale_basis = HANDLE_SCREEN_SIZE_PX * _CP_DOT_RADIUS * 0.5 / gizmo_size


def _color_plane_guides(context):
    """``(normal, hovered)`` line segments of the selected Gradient Color Planes."""
    try:
        from .layer_cage import hovered_handle_name
        hovered = hovered_handle_name(context.region)
    except ImportError:
        hovered = ""
    normal, lit = [], []
    for rig, _frame, _radial, world_0, world_1, _normal in color_plane_gradient_targets(context):
        target = lit if hovered == f"{COLOR_PLANE_ID}:{rig.name}:LINE" else normal
        target.extend((world_0, world_1))
    return normal, lit


# --- Gradient base line ----------------------------------------------------
#
# The end dots and the line itself are dragged directly, whatever the active
# tool: an end dot turns and stretches the gradient around the other end, the
# line moves it. A click without a drag selects the handle, as before.

_DRAG_DOT_PX = 7.0
_DRAG_LINE_PX = 4.0
_LINE_EFFECTS = ("GRADIENT_LIGHT", "GRADIENT_MASK", "TILT_SHIFT")


def _line_segment(rig, effect_id, in_control, out_control, start, end):
    """World ends of the draggable line: IN to OUT, or centre to OUT if radial."""
    try:
        from . import effect_controls as controls
        if effect_id == "GRADIENT_MASK" and controls._gradient_is_radial(rig):
            centre = controls.find_effect_control(rig, effect_id, "CENTER")
            if centre is not None:
                return centre.matrix_world.translation.copy(), end
    except (ImportError,) + FBP_DATA_ERRORS:
        pass
    del in_control, out_control
    return start, end


class FBP_GT_gradient_drag(bpy.types.Gizmo):
    """Invisible grip over a gradient's end dot or base line (the overlay draws them)."""

    bl_idname = "FBP_GT_gradient_drag"
    __slots__ = (
        "fbp_rig_name", "fbp_effect_id", "fbp_kind", "fbp_a", "fbp_b",
        "fbp_initial", "fbp_press", "fbp_moved", "fbp_hit", "fbp_normal",
    )

    def setup(self):
        self.fbp_kind = ""
        self.fbp_initial = None
        self.fbp_press = None
        self.fbp_moved = False
        self.use_draw_hover = False

    def draw(self, context):
        del context

    def test_select(self, context, location):
        hit = self._hit(context, location)
        if hit == 0:
            # This grip takes the event before the cursor probe sees it, so
            # it tells the overlay which handle to light up.
            control = self._moved_control()
            try:
                from .layer_cage import set_hovered_handle
                set_hovered_handle(context, control.name if control is not None else "")
            except ImportError:
                pass
        return hit

    def _hit(self, context, location):
        region, view = context.region, context.region_data
        scale = _ui_scale(context)
        a = location_3d_to_region_2d(region, view, Vector(self.fbp_a))
        if a is None:
            return -1
        mouse = Vector(location)
        if self.fbp_kind in {"IN", "OUT"}:
            return 0 if (mouse - a).length <= _DRAG_DOT_PX * scale else -1
        b = location_3d_to_region_2d(region, view, Vector(self.fbp_b))
        if b is None:
            return -1
        axis = b - a
        length_sq = axis.length_squared
        if length_sq <= 1.0e-6:
            return -1
        t = (mouse - a).dot(axis) / length_sq
        if not 0.0 <= t <= 1.0:
            return -1
        # Leave the ends to the end dots.
        dot = _DRAG_DOT_PX * scale
        if (mouse - a).length <= dot or (mouse - b).length <= dot:
            return -1
        return 0 if (mouse - (a + axis * t)).length <= _DRAG_LINE_PX * scale else -1

    def _controls(self):
        try:
            from .effect_controls import find_effect_control
            rig = bpy.data.objects.get(self.fbp_rig_name or "")
            return {
                role: find_effect_control(rig, self.fbp_effect_id, role)
                for role in ("IN", "OUT", "CENTER")
            }
        except (ImportError,) + FBP_DATA_ERRORS:
            return {}

    def _moved_control(self):
        return self._controls().get("CENTER" if self.fbp_kind == "LINE" else self.fbp_kind)

    def invoke(self, context, event):
        control = self._moved_control()
        if control is None:
            return {"CANCELLED"}
        self.fbp_press = (event.mouse_region_x, event.mouse_region_y)
        self.fbp_moved = False
        self.fbp_normal = tuple(control.matrix_world.col[2].xyz.normalized())
        hit = _plane_hit(
            context.region, context.region_data, self.fbp_press,
            Vector(self.fbp_a), Vector(self.fbp_normal),
        )
        if hit is None:
            return {"CANCELLED"}
        self.fbp_hit = tuple(hit)
        # The control's location lives in the space its Child Of gives it.
        space = control.matrix_world @ control.matrix_basis.inverted_safe()
        self.fbp_initial = {
            role: tuple(item.location) for role, item in self._controls().items() if item is not None
        }
        self.fbp_initial["__space__"] = [tuple(row) for row in space.inverted_safe()]
        return {"RUNNING_MODAL"}

    def modal(self, context, event, tweak):
        del tweak
        if not self.fbp_moved:
            dx = event.mouse_region_x - self.fbp_press[0]
            dy = event.mouse_region_y - self.fbp_press[1]
            if dx * dx + dy * dy < _STOP_CLICK_PX * _STOP_CLICK_PX:
                return {"RUNNING_MODAL"}
            self.fbp_moved = True
        hit = _plane_hit(
            context.region, context.region_data, (event.mouse_region_x, event.mouse_region_y),
            Vector(self.fbp_hit), Vector(self.fbp_normal),
        )
        control = self._moved_control()
        if hit is None or control is None:
            return {"RUNNING_MODAL"}
        to_local = Matrix(self.fbp_initial["__space__"])
        delta = to_local.to_3x3() @ (hit - Vector(self.fbp_hit))
        start = Vector(self.fbp_initial[self.fbp_kind if self.fbp_kind != "LINE" else "CENTER"])
        target = start + Vector((delta.x, delta.y, 0.0))
        if (Vector(control.location) - target).length > 1.0e-7:
            control.location = target
            _sync_control(control)
        context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def exit(self, context, cancel):
        if cancel:
            controls = self._controls()
            for role in ("CENTER", "IN", "OUT"):
                control = controls.get(role)
                initial = (self.fbp_initial or {}).get(role)
                if control is not None and initial is not None and tuple(control.location) != initial:
                    control.location = initial
                    _sync_control(control)
        elif self.fbp_moved:
            _undo_push("Move Gradient" if self.fbp_kind == "LINE" else "Move Gradient End")
        elif context.mode == "POSE":
            # Selecting the handle would take the layer out of Pose Mode.
            pass
        else:
            # A plain click selects the handle, as before the line was draggable.
            control = self._moved_control()
            if control is not None:
                for obj in tuple(context.selected_objects):
                    if obj != control:
                        obj.select_set(False)
                control.select_set(True)
                context.view_layer.objects.active = control
                _undo_push("Select")
        context.area.tag_redraw()


def _sync_control(control):
    try:
        from .effect_controls import sync_properties_from_control
        sync_properties_from_control(control)
    except (ImportError,) + FBP_DATA_ERRORS:
        pass


class FBP_GGT_gradient_lines(bpy.types.GizmoGroup):
    bl_idname = "FBP_GGT_gradient_lines"
    bl_label = "Frame By Plane Gradient Lines"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}

    @classmethod
    def poll(cls, context):
        try:
            # Pose Mode too: a posed layer shows its gradient handles.
            if context.mode not in {"OBJECT", "POSE"} or not context.space_data.overlay.show_overlays:
                return False
        except FBP_DATA_ERRORS:
            return False
        return next(_gradient_stop_targets(context, _LINE_EFFECTS), None) is not None

    def setup(self, context):
        self.draw_prepare(context)

    def draw_prepare(self, context):
        grips = []
        for rig, effect_id, in_control, out_control, start, end, _normal in _gradient_stop_targets(context, _LINE_EFFECTS):
            line_a, line_b = _line_segment(rig, effect_id, in_control, out_control, start, end)
            grips.append((rig.name, effect_id, "LINE", line_a, line_b))
            grips.append((rig.name, effect_id, "IN", start, start))
            grips.append((rig.name, effect_id, "OUT", end, end))
        gizmos = self.gizmos
        _fit_gizmos(gizmos, len(grips), FBP_GT_gradient_drag.bl_idname)
        for gizmo, (rig_name, effect_id, kind, a, b) in zip(gizmos, grips):
            if gizmo.is_modal:
                continue
            gizmo.fbp_rig_name = rig_name
            gizmo.fbp_effect_id = effect_id
            gizmo.fbp_kind = kind
            gizmo.fbp_a = tuple(a)
            gizmo.fbp_b = tuple(b)


class FBP_GGT_gradient_stops(bpy.types.GizmoGroup):
    bl_idname = "FBP_GGT_gradient_stops"
    bl_label = "Frame By Plane Gradient Stops"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}

    @classmethod
    def poll(cls, context):
        try:
            # Pose Mode too: a posed layer shows its gradient handles.
            if context.mode not in {"OBJECT", "POSE"} or not context.space_data.overlay.show_overlays:
                return False
        except FBP_DATA_ERRORS:
            return False
        return next(_gradient_stop_targets(context), None) is not None

    def setup(self, context):
        self.draw_prepare(context)

    def draw_prepare(self, context):
        region, view = context.region, context.region_data
        stops = []
        for rig, effect_id, in_control, out_control, start, end, normal in _gradient_stop_targets(context):
            try:
                items = _gradient_stops(rig, effect_id, in_control, out_control)
            except (ImportError,) + FBP_DATA_ERRORS:
                continue
            axis = (end - start).normalized()
            side = normal.cross(axis)
            if side.length <= 1.0e-6:
                continue
            side.normalize()
            # The circles go on the side of the line that is up on screen.
            foot = location_3d_to_region_2d(region, view, start)
            tip = location_3d_to_region_2d(region, view, start + side * (end - start).length * 0.25)
            if foot is not None and tip is not None and (tip - foot).y < 0.0:
                side, normal = -side, -normal
            basis = Matrix((axis, side, normal)).transposed().to_4x4()
            for key, t, color in items:
                stops.append((rig.name, effect_id, str(key), start, end, start.lerp(end, t), basis, color))
        try:
            gizmo_size = max(float(context.preferences.view.gizmo_size), 1.0)
        except FBP_DATA_ERRORS:
            gizmo_size = 75.0
        gizmos = self.gizmos
        _fit_gizmos(gizmos, len(stops), FBP_GT_gradient_stop.bl_idname)
        for gizmo, (rig_name, effect_id, key, start, end, location, basis, color) in zip(gizmos, stops):
            if gizmo.is_modal:
                continue
            gizmo.fbp_rig_name = rig_name
            gizmo.fbp_effect_id = effect_id
            gizmo.fbp_key = key
            gizmo.fbp_start = tuple(start)
            gizmo.fbp_end = tuple(end)
            gizmo.fbp_swatch = tuple(color)[:3]
            gizmo.matrix_basis = Matrix.Translation(location) @ basis
            # Blender multiplies a scaled gizmo by the Gizmo Size preference
            # (and the UI scale), so this gives HANDLE_SCREEN_SIZE_PX / 2.
            gizmo.scale_basis = HANDLE_SCREEN_SIZE_PX * 0.5 / gizmo_size


# --- Crop / Expand bounds -----------------------------------------------------
#
# The bounds handles are drawn by the overlay as dots on a thin frame. Without
# a grip of their own a click-drag on a dot reached the active tool, so the
# Select Box tool started a box select instead of moving the dot. This grip
# takes the press over any visible Crop/Expand dot: a drag moves that bound
# (one undo step, Esc or right click restores it), a plain click selects the
# handle so G, the sidebar and the Modifiers panel still work as before.

def _bounds_handle(obj):
    try:
        from .effect_controls import KEY_MODE
        return obj is not None and str(obj.get(KEY_MODE, "") or "").upper() == "CROP_EXTEND"
    except (ImportError,) + FBP_DATA_ERRORS:
        return False


def _bounds_handles_shown(context):
    return any(_bounds_handle(obj) for obj in _visible_handles(context))


def _bounds_handle_under_cursor(context, location):
    if not _bounds_handles_shown(context):
        return None
    try:
        from .alpha_pick import fbp_handle_under_cursor
        handle = fbp_handle_under_cursor(context, location, _DRAG_DOT_PX * _ui_scale(context))
    except (ImportError,) + FBP_DATA_ERRORS + (IndexError, ValueError):
        return None
    return handle if _bounds_handle(handle) else None


class FBP_GT_bounds_drag(bpy.types.Gizmo):
    """Invisible grip over the Crop/Expand dots (the overlay draws them)."""

    bl_idname = "FBP_GT_bounds_drag"
    __slots__ = (
        "fbp_handle_name", "fbp_initial", "fbp_press", "fbp_moved",
        "fbp_hit", "fbp_normal", "fbp_to_local",
    )

    def setup(self):
        self.fbp_handle_name = ""
        self.fbp_initial = None
        self.fbp_press = None
        self.fbp_moved = False
        self.use_draw_hover = False

    def draw(self, context):
        del context

    def test_select(self, context, location):
        if self.is_modal:
            return 0
        handle = _bounds_handle_under_cursor(context, location)
        self.fbp_handle_name = handle.name if handle is not None else ""
        if handle is None:
            return -1
        try:
            from .layer_cage import set_hovered_handle
            set_hovered_handle(context, handle.name)
        except ImportError:
            pass
        return 0

    def _handle(self):
        obj = bpy.data.objects.get(self.fbp_handle_name or "")
        return obj if _bounds_handle(obj) else None

    def invoke(self, context, event):
        control = self._handle()
        if control is None:
            return {"CANCELLED"}
        self.fbp_press = (event.mouse_region_x, event.mouse_region_y)
        self.fbp_moved = False
        world = control.matrix_world
        self.fbp_normal = tuple(world.col[2].xyz.normalized())
        hit = _plane_hit(
            context.region, context.region_data, self.fbp_press,
            world.translation.copy(), Vector(self.fbp_normal),
        )
        if hit is None:
            return {"CANCELLED"}
        self.fbp_hit = tuple(hit)
        # The location lives in the space the plane binding gives it.
        space = world @ control.matrix_basis.inverted_safe()
        self.fbp_to_local = [tuple(row) for row in space.inverted_safe()]
        self.fbp_initial = tuple(control.location)
        return {"RUNNING_MODAL"}

    def modal(self, context, event, tweak):
        del tweak
        if not self.fbp_moved:
            dx = event.mouse_region_x - self.fbp_press[0]
            dy = event.mouse_region_y - self.fbp_press[1]
            if dx * dx + dy * dy < _STOP_CLICK_PX * _STOP_CLICK_PX:
                return {"RUNNING_MODAL"}
            self.fbp_moved = True
            control = self._handle()
            if control is not None:
                _select_only(context, control)
        hit = _plane_hit(
            context.region, context.region_data, (event.mouse_region_x, event.mouse_region_y),
            Vector(self.fbp_hit), Vector(self.fbp_normal),
        )
        control = self._handle()
        if hit is None or control is None:
            return {"RUNNING_MODAL"}
        delta = Matrix(self.fbp_to_local).to_3x3() @ (hit - Vector(self.fbp_hit))
        start = Vector(self.fbp_initial)
        target = Vector((start.x + delta.x, start.y + delta.y, start.z))
        if (Vector(control.location) - target).length > 1.0e-7:
            control.location = target
            _sync_control(control)
        context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def exit(self, context, cancel):
        control = self._handle()
        if cancel:
            if control is not None and self.fbp_initial is not None and tuple(control.location) != self.fbp_initial:
                control.location = self.fbp_initial
                _sync_control(control)
        elif self.fbp_moved:
            _undo_push("Move Crop Bound")
        elif control is not None and context.mode != "POSE":
            # A plain click selects the handle: G, the sidebar and the
            # Modifiers panel keep working on it.
            _select_only(context, control)
            _undo_push("Select")
        context.area.tag_redraw()


def _select_only(context, obj):
    try:
        for other in tuple(context.selected_objects):
            if other != obj:
                other.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
    except FBP_DATA_ERRORS:
        pass


class FBP_GGT_bounds_drag(bpy.types.GizmoGroup):
    bl_idname = "FBP_GGT_bounds_drag"
    bl_label = "Frame By Plane Crop Bounds"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}

    @classmethod
    def poll(cls, context):
        try:
            if context.mode != "OBJECT" or not context.space_data.overlay.show_overlays:
                return False
        except FBP_DATA_ERRORS:
            return False
        return _bounds_handles_shown(context)

    def setup(self, context):
        del context
        if not self.gizmos:
            self.gizmos.new(FBP_GT_bounds_drag.bl_idname)


_GIZMO_CLASSES = (
    FBP_GT_gradient_stop, FBP_OT_gradient_stop_color, FBP_GGT_gradient_stops,
    FBP_GT_gradient_drag, FBP_GGT_gradient_lines,
    FBP_GT_color_plane_grip, FBP_GGT_color_plane_gradient,
    FBP_GT_bounds_drag, FBP_GGT_bounds_drag,
)


def register():
    global _DRAW_HANDLE
    if bpy.app.background or _DRAW_HANDLE is not None:
        return
    _DRAW_HANDLE = bpy.types.SpaceView3D.draw_handler_add(_draw_handles, (), "WINDOW", "POST_VIEW")
    for cls in _GIZMO_CLASSES:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass


def unregister():
    global _DRAW_HANDLE, _LINE_SHADER
    handle = _DRAW_HANDLE
    _DRAW_HANDLE = None
    _LINE_SHADER = None
    if handle is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
        except (ValueError, RuntimeError):
            pass
    for cls in reversed(_GIZMO_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except (ValueError, RuntimeError):
            pass
