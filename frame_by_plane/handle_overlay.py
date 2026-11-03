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


_DRAW_HANDLE = None
_FILL_SHADER = None
_LINE_SHADER = None
_OUTLINE_WIDTH = 1.5
_GUIDE_WIDTH = 1.4
_GUIDE_OUTLINE_WIDTH = 3.4


def _shaders():
    global _FILL_SHADER, _LINE_SHADER
    if _FILL_SHADER is None:
        _FILL_SHADER = gpu.shader.from_builtin("UNIFORM_COLOR")
    if _LINE_SHADER is None:
        _LINE_SHADER = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    return _FILL_SHADER, _LINE_SHADER


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
            if not is_bones_object(armature):
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
        # A selected handle already shows the selection yellow in Pose Mode.
        if str(armature.mode) == "POSE" and bool(getattr(pose_bone, "select", False)):
            return []
        return _lattice_shape_triangles(armature, pose_bone)
    except (*FBP_DATA_ERRORS, IndexError):
        return []


def _handle_hover_color(context):
    """The handle under the cursor: most of the way to the selected gizmo yellow."""
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
        if nominal <= 0.0 or str(obj.get(KEY_MODE, "") or "").upper() in _UNSCALED_MODES:
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
    return anchor, HANDLE_SCREEN_SIZE_PX * float(ui_scale) / pixels


def _scaled(points, anchor, factor):
    return [anchor + (point - anchor) * factor for point in points]


def _handle_geometry(obj, depsgraph):
    """World-space triangles per part, rim segments and guide segments of one handle."""
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        matrix = evaluated.matrix_world
        points = [matrix @ vertex.co for vertex in mesh.vertices]
        parts = None
        attribute = mesh.attributes.get(PART_ATTRIBUTE)
        if attribute is not None and attribute.domain == "FACE" and len(attribute.data) == len(mesh.polygons):
            parts = [0] * len(mesh.polygons)
            attribute.data.foreach_get("value", parts)
        mesh.calc_loop_triangles()
        triangles = {}
        for tri in mesh.loop_triangles:
            part = parts[tri.polygon_index] if parts else PART_HANDLE
            triangles.setdefault(part, []).extend(points[index] for index in tri.vertices)
        edge_users = {}
        for polygon in mesh.polygons:
            for key in polygon.edge_keys:
                edge_users[key] = edge_users.get(key, 0) + 1
        rim = [points[index] for key, users in edge_users.items() if users == 1 for index in key]
        guides = [
            points[index]
            for edge in mesh.edges
            if tuple(sorted(edge.vertices)) not in edge_users
            for index in edge.vertices
        ]
    finally:
        evaluated.to_mesh_clear()
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
    handles = _visible_handles(context)
    mask_guides = _mask_guides(context)
    lattice_guides = _lattice_guides(context)
    try:
        from .layer_cage import hovered_handle_name
        hovered = hovered_handle_name(region)
    except ImportError:
        hovered = ""
    hovered_bone = _hovered_lattice_triangles(hovered)
    if not handles and not mask_guides and not lattice_guides and not hovered_bone:
        return
    try:
        depsgraph = context.evaluated_depsgraph_get()
    except FBP_DATA_ERRORS:
        return
    fill_shader, line_shader = _shaders()
    try:
        scale = float(context.preferences.system.ui_scale) or 1.0
    except FBP_DATA_ERRORS:
        scale = 1.0
    guides = list(lattice_guides)
    for solid, _dashed in mask_guides:
        guides.extend(solid)
    for _solid, dashed in mask_guides:
        guides.extend(dashed)
    selected_color = handle_selected_color(context)
    hover_color = _handle_hover_color(context)
    shapes = []
    if hovered_bone:
        shapes.append(([(hovered_bone, hover_color)], []))
    hover_guides = []
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
_GRADIENT_EFFECTS = ("GRADIENT_LIGHT", "GRADIENT_MASK")


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
        first, last = float(elements[0].position), float(elements[-1].position)
        # Stay between the neighbours: Blender keeps ramp stops sorted.
        low = float(elements[index - 1].position) + _STOP_EPSILON
        high = float(elements[index + 1].position) - _STOP_EPSILON
        position = max(low, min(high, first + t * (last - first)))
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
        try:
            with context.temp_override(window=context.window, area=context.area, region=context.region):
                bpy.ops.fbp.gradient_stop_color("INVOKE_DEFAULT", rig_name=rig.name, index=index)
        except (RuntimeError, TypeError, AttributeError):
            pass


def _undo_push(message):
    try:
        bpy.ops.ed.undo_push(message=message)
    except RuntimeError:
        pass


class FBP_OT_gradient_stop_color(bpy.types.Operator):
    """Change the colour of a Gradient Light stop"""

    bl_idname = "fbp.gradient_stop_color"
    bl_label = "Gradient Stop Color"
    bl_description = "Change the colour of this Gradient Light stop"
    bl_options = {"REGISTER", "UNDO"}

    rig_name: bpy.props.StringProperty(options={"HIDDEN"})
    index: bpy.props.IntProperty(default=0, options={"HIDDEN"})

    def _target(self, context):
        """``(owner, property)`` that holds the stop's colour."""
        del context
        rig = bpy.data.objects.get(self.rig_name or "")
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


# --- Gradient base line ----------------------------------------------------
#
# The end dots and the line itself are dragged directly, whatever the active
# tool: an end dot turns and stretches the gradient around the other end, the
# line moves it. A click without a drag selects the handle, as before.

_DRAG_DOT_PX = 7.0
_DRAG_LINE_PX = 4.0
_LINE_EFFECTS = _GRADIENT_EFFECTS + ("TILT_SHIFT",)


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


def _plane_hit(region, view, coord, point, normal):
    try:
        from .alpha_pick import fbp_view_ray
        origin, direction = fbp_view_ray(region, view, coord)
    except (ImportError,) + FBP_DATA_ERRORS:
        return None
    denominator = direction.dot(normal)
    if abs(denominator) <= 1.0e-9:
        return None
    return origin + direction * ((point - origin).dot(normal) / denominator)


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
        try:
            scale = float(context.preferences.system.ui_scale) or 1.0
        except FBP_DATA_ERRORS:
            scale = 1.0
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
            if context.mode != "OBJECT" or not context.space_data.overlay.show_overlays:
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
        while len(gizmos) > len(grips):
            gizmos.remove(gizmos[-1])
        while len(gizmos) < len(grips):
            gizmos.new(FBP_GT_gradient_drag.bl_idname)
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
            if context.mode != "OBJECT" or not context.space_data.overlay.show_overlays:
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
        while len(gizmos) > len(stops):
            gizmos.remove(gizmos[-1])
        while len(gizmos) < len(stops):
            gizmos.new(FBP_GT_gradient_stop.bl_idname)
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


_GIZMO_CLASSES = (
    FBP_GT_gradient_stop, FBP_OT_gradient_stop_color, FBP_GGT_gradient_stops,
    FBP_GT_gradient_drag, FBP_GGT_gradient_lines,
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
    global _DRAW_HANDLE, _FILL_SHADER, _LINE_SHADER
    handle = _DRAW_HANDLE
    _DRAW_HANDLE = None
    _FILL_SHADER = None
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
