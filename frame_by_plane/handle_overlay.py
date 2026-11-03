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
    PART_SWATCH,
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


def _handle_hover_color(context):
    """The handle under the cursor: halfway to the selected gizmo yellow."""
    selected = handle_selected_color(context)
    return (*(0.5 * (white + accent) for white, accent in zip(HANDLE_COLOR[:3], selected[:3])), 1.0)


def _swatch_color(obj):
    try:
        from .effect_controls import control_swatch_color
        return control_swatch_color(obj)
    except (ImportError, AttributeError):
        return None


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
    if not handles and not mask_guides and not lattice_guides:
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
    try:
        from .layer_cage import hovered_handle_name
        hovered = hovered_handle_name(region)
    except ImportError:
        hovered = ""
    shapes = []
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
        guides.extend(handle_guides)
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
        if PART_SWATCH in triangles:
            swatch = _swatch_color(obj)
            if swatch is not None:
                fills.append((triangles[PART_SWATCH], swatch))
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
    if not shapes and not guides:
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


# --- Intermediate gradient stops -------------------------------------------
#
# The first and last Gradient Light stops are the IN/OUT handle objects. The
# stops a user adds in between in the Color Ramp are gizmos on the line between
# them: they show their colour and slide along the line, like Figma's stops.

_STOP_EPSILON = 0.001


def _evaluated_center(obj, depsgraph):
    evaluated = obj.evaluated_get(depsgraph)
    corners = [Vector(corner) for corner in evaluated.bound_box]
    return evaluated.matrix_world @ (sum(corners, Vector()) / 8.0)


def _gradient_stop_targets(context):
    """Yield ``(rig, ramp, start, end, basis, radius)`` per visible Gradient Light."""
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
            if (
                str(control.get(controls.KEY_EFFECT_ID, "") or "") != "GRADIENT_LIGHT"
                or str(control.get(controls.KEY_ROLE, "") or "") != "IN"
            ):
                continue
            rig = controls.effect_control_owner(control)
            out_control = controls.find_effect_control(rig, "GRADIENT_LIGHT", "OUT") if rig else None
            ramp = controls.gradient_light_ramp(rig) if rig else None
            if out_control is None or ramp is None or len(ramp.elements) < 3:
                continue
            start = _evaluated_center(control, depsgraph)
            end = _evaluated_center(out_control, depsgraph)
            basis = control.matrix_world.to_3x3().normalized()
            radius = controls._control_display_size(rig) * 0.5
        except FBP_DATA_ERRORS:
            continue
        yield rig, ramp, start, end, basis, radius


def _ring_triangles(outer, inner, segments=32):
    triangles = []
    for index in range(segments):
        a0 = math.tau * index / segments
        a1 = math.tau * (index + 1) / segments
        p0o = (math.cos(a0) * outer, math.sin(a0) * outer, 0.0)
        p1o = (math.cos(a1) * outer, math.sin(a1) * outer, 0.0)
        p0i = (math.cos(a0) * inner, math.sin(a0) * inner, 0.0)
        p1i = (math.cos(a1) * inner, math.sin(a1) * inner, 0.0)
        triangles.extend((p0o, p1o, p1i, p0o, p1i, p0i))
    return triangles


def _disc_triangles(radius, segments=32):
    triangles = []
    for index in range(segments):
        a0 = math.tau * index / segments
        a1 = math.tau * (index + 1) / segments
        triangles.extend((
            (0.0, 0.0, 0.0),
            (math.cos(a0) * radius, math.sin(a0) * radius, 0.0),
            (math.cos(a1) * radius, math.sin(a1) * radius, 0.0),
        ))
    return triangles


class FBP_GT_gradient_stop(bpy.types.Gizmo):
    """One intermediate Color Ramp stop, dragged along the gradient line."""

    bl_idname = "FBP_GT_gradient_stop"
    __slots__ = (
        "fbp_rim", "fbp_ring", "fbp_disc", "fbp_rig_name", "fbp_index",
        "fbp_start", "fbp_end", "fbp_swatch", "fbp_initial",
    )

    def setup(self):
        # Same proportions as the IN/OUT stop meshes (gradient_stop_geometry).
        self.fbp_rim = self.new_custom_shape("TRIS", _ring_triangles(1.1, 0.95))
        self.fbp_ring = self.new_custom_shape("TRIS", _ring_triangles(1.0, 0.78))
        self.fbp_disc = self.new_custom_shape("TRIS", _disc_triangles(0.8))
        self.fbp_swatch = (1.0, 1.0, 1.0)
        self.fbp_initial = None
        # A fixed size on screen, like the IN/OUT stops (see draw_prepare).
        self.use_draw_scale = True

    def _draw_part(self, shape, color, alpha=1.0):
        self.color = color
        self.color_highlight = color
        self.alpha = alpha
        self.alpha_highlight = alpha
        self.draw_custom_shape(shape)

    def draw(self, context):
        self._draw_part(self.fbp_rim, (0.0, 0.0, 0.0), 0.45)
        active = self.is_highlight or self.is_modal
        ring = handle_selected_color(context)[:3] if active else STOP_RING_COLOR[:3]
        self._draw_part(self.fbp_ring, ring)
        self._draw_part(self.fbp_disc, tuple(self.fbp_swatch))

    def draw_select(self, context, select_id):
        del context
        self.draw_custom_shape(self.fbp_ring, select_id=select_id)
        self.draw_custom_shape(self.fbp_disc, select_id=select_id)

    def _element(self):
        rig = bpy.data.objects.get(self.fbp_rig_name or "")
        try:
            from .effect_controls import gradient_light_ramp
            ramp = gradient_light_ramp(rig) if rig else None
            return ramp, ramp.elements[self.fbp_index]
        except (ImportError, IndexError, TypeError) + FBP_DATA_ERRORS:
            return None, None

    def invoke(self, context, event):
        del context, event
        _ramp, element = self._element()
        if element is None:
            return {"CANCELLED"}
        self.fbp_initial = float(element.position)
        return {"RUNNING_MODAL"}

    def modal(self, context, event, tweak):
        del tweak
        ramp, element = self._element()
        if element is None:
            return {"CANCELLED"}
        region, view = context.region, context.region_data
        start = location_3d_to_region_2d(region, view, Vector(self.fbp_start))
        end = location_3d_to_region_2d(region, view, Vector(self.fbp_end))
        if start is None or end is None:
            return {"RUNNING_MODAL"}
        axis = end - start
        length_sq = axis.length_squared
        if length_sq <= 1.0e-6:
            return {"RUNNING_MODAL"}
        mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        t = (mouse - start).dot(axis) / length_sq
        elements = ramp.elements
        first, last = float(elements[0].position), float(elements[-1].position)
        index = self.fbp_index
        # Stay between the neighbours: Blender keeps ramp stops sorted.
        low = float(elements[index - 1].position) + _STOP_EPSILON
        high = float(elements[index + 1].position) - _STOP_EPSILON
        position = max(low, min(high, first + t * (last - first)))
        if abs(float(element.position) - position) > 1.0e-6:
            element.position = position
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def exit(self, context, cancel):
        _ramp, element = self._element()
        if element is not None and cancel and self.fbp_initial is not None:
            element.position = self.fbp_initial
        elif element is not None and not cancel:
            try:
                bpy.ops.ed.undo_push(message="Move Gradient Stop")
            except RuntimeError:
                pass
        context.area.tag_redraw()


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
        try:
            from .effect_controls import _display_color
        except ImportError:
            return
        stops = []
        for rig, ramp, start, end, basis, radius in _gradient_stop_targets(context):
            elements = ramp.elements
            first, last = float(elements[0].position), float(elements[-1].position)
            span = last - first
            for index in range(1, len(elements) - 1):
                element = elements[index]
                t = (float(element.position) - first) / span if abs(span) > 1.0e-9 else 0.5
                stops.append((rig.name, index, start, end, start.lerp(end, t), basis, radius, _display_color(element.color)))
        try:
            gizmo_size = max(float(context.preferences.view.gizmo_size), 1.0)
        except FBP_DATA_ERRORS:
            gizmo_size = 75.0
        gizmos = self.gizmos
        while len(gizmos) > len(stops):
            gizmos.remove(gizmos[-1])
        while len(gizmos) < len(stops):
            gizmos.new(FBP_GT_gradient_stop.bl_idname)
        for gizmo, (rig_name, index, start, end, location, basis, radius, color) in zip(gizmos, stops):
            if gizmo.is_modal:
                continue
            gizmo.fbp_rig_name = rig_name
            gizmo.fbp_index = index
            gizmo.fbp_start = tuple(start)
            gizmo.fbp_end = tuple(end)
            gizmo.fbp_swatch = color[:3]
            del radius
            gizmo.matrix_basis = Matrix.Translation(location) @ basis.to_4x4()
            # Blender multiplies a scaled gizmo by the Gizmo Size preference
            # (and the UI scale), so this gives HANDLE_SCREEN_SIZE_PX / 2.
            gizmo.scale_basis = HANDLE_SCREEN_SIZE_PX * 0.5 / gizmo_size


_GIZMO_CLASSES = (FBP_GT_gradient_stop, FBP_GGT_gradient_stops)


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
