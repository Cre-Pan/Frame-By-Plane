"""Box and lasso selection for layers whose rig wire is hidden (Use Rig off).

Blender's box and lasso select only see what an object draws, and a layer
without a rig draws nothing (its image plane is never selectable). When such
layers are on screen, these operators take over the gesture: they draw the
box or lasso, hand the exact same gesture to Blender's own operator so every
other object is selected as usual, then add the rig-less layers whose solid
pixels fall inside it. With no rig-less layer in view they step aside and
Blender's gesture runs untouched.
"""

from __future__ import annotations

import bpy
import gpu
from bpy.props import EnumProperty
from bpy.types import Operator
from gpu_extras.batch import batch_for_shader

from .runtime import FBP_DATA_ERRORS

try:
    import numpy as np
except ImportError:  # pragma: no cover - Blender ships NumPy.
    np = None


_MODE_ITEMS = (
    ('TOOL', "Tool", "Use the mode set on the active selection tool"),
    ('SET', "Set", "Select only what is inside"),
    ('ADD', "Extend", "Add what is inside to the selection"),
    ('SUB', "Subtract", "Remove what is inside from the selection"),
    ('XOR', "Difference", "Toggle what is inside"),
    ('AND', "Intersect", "Keep only selected layers that are inside"),
)
_MODES = {item[0] for item in _MODE_ITEMS if item[0] != 'TOOL'}
_MIN_DRAG = 3.0
_MAX_SAMPLES = 96
_SAMPLE_SPACING_PX = 6.0
_SOLID_SHARE = 0.25


def fbp_rigless_layers(context):
    """Visible, selectable layers that do not draw a rig wire."""
    from .builder import fbp_rig_wire_visible

    layers = []
    for obj in tuple(getattr(context, "visible_objects", ()) or ()):
        try:
            if (
                bool(getattr(obj, "is_fbp_control", False))
                and not bool(getattr(obj, "hide_select", False))
                and getattr(obj, "fbp_plane_target", None) is not None
                and not fbp_rig_wire_visible(obj)
            ):
                layers.append(obj)
        except FBP_DATA_ERRORS:
            continue
    return layers


def _wrap(values, mode):
    """Vectorised Extend-mode UV wrap; NaN marks samples outside the image."""
    inside = (values >= 0.0) & (values <= 1.0)
    if mode == "REPEAT":
        wrapped = np.mod(values, 1.0)
    elif mode == "MIRROR":
        period = np.mod(values, 2.0)
        wrapped = np.where(period <= 1.0, period, 2.0 - period)
    elif mode == "EDGE":
        wrapped = np.clip(values, 0.0, 1.0)
    else:
        wrapped = np.where(inside, values, np.nan)
    return np.where(inside, values, wrapped)


def _solid_samples(union, mode, uvs):
    """Boolean per UV sample: True where the shown frame has solid pixels."""
    if union is None:
        return np.ones(len(uvs), dtype=bool)
    u = _wrap(uvs[:, 0], mode)
    v = _wrap(uvs[:, 1], mode)
    valid = ~(np.isnan(u) | np.isnan(v))
    grid = getattr(union, "solid", None)
    threshold = _SOLID_SHARE * 255.0
    if grid is None:
        grid = union.mask
        threshold = 0.5
    rows, cols = grid.shape
    col = np.clip((np.nan_to_num(u) * cols).astype(np.int64), 0, cols - 1)
    row = np.clip(((1.0 - np.nan_to_num(v)) * rows).astype(np.int64), 0, rows - 1)
    return valid & (grid[row, col].astype(np.float32) >= threshold)


def _project(points, perspective, width, height):
    """World points (N, 3) to region pixels (N, 2); NaN behind the view."""
    homogeneous = np.c_[points, np.ones(len(points))] @ perspective.T
    w = homogeneous[:, 3]
    ahead = w > 1e-6
    safe = np.where(ahead, w, 1.0)
    x = (homogeneous[:, 0] / safe + 1.0) * 0.5 * width
    y = (homogeneous[:, 1] / safe + 1.0) * 0.5 * height
    x[~ahead] = np.nan
    y[~ahead] = np.nan
    return np.c_[x, y]


def _plane_samples(plane_eval, matrix, perspective, width, height):
    """World-projected pixels and UVs sampled over the evaluated plane.

    Works on the mesh's loop triangles in bulk: Mesh effects (Broken Glass,
    Crystal, remeshed reliefs) give planes thousands of faces, and walking them
    one polygon at a time took seconds per gesture. Each triangle gets a
    sample grid sized to its on-screen footprint.
    """
    mesh = plane_eval.data
    uv_layer = mesh.uv_layers.get("UVMap") or mesh.uv_layers.active
    if uv_layer is None:
        return None, None
    mesh.calc_loop_triangles()
    count = len(mesh.loop_triangles)
    if not count:
        return None, None
    loops = np.empty(count * 3, dtype=np.int64)
    mesh.loop_triangles.foreach_get("loops", loops)
    vertex_of_loop = np.empty(len(mesh.loops), dtype=np.int64)
    mesh.loops.foreach_get("vertex_index", vertex_of_loop)
    positions = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", positions)
    loop_uvs = np.empty(len(mesh.loops) * 2, dtype=np.float64)
    uv_layer.data.foreach_get("uv", loop_uvs)
    world = np.array(matrix, dtype=np.float64)
    positions = positions.reshape(-1, 3)
    positions_world = (np.c_[positions, np.ones(len(positions))] @ world.T)[:, :3]
    corners = positions_world[vertex_of_loop[loops]].reshape(count, 3, 3)
    corner_uvs = loop_uvs.reshape(-1, 2)[loops].reshape(count, 3, 2)

    projected = _project(corners.reshape(-1, 3), perspective, width, height).reshape(count, 3, 2)
    with np.errstate(invalid="ignore"):
        span = np.nanmax(projected, axis=1) - np.nanmin(projected, axis=1)
        size = np.nanmax(span, axis=1)
    size = np.where(np.isfinite(size), size, 64.0)
    steps_per_tri = np.clip((size / _SAMPLE_SPACING_PX).astype(np.int64), 2, _MAX_SAMPLES)

    pixels_out = []
    uvs_out = []
    for steps in np.unique(steps_per_tri):
        chosen = steps_per_tri == steps
        grid = (np.arange(steps) + 0.5) / steps
        s, t = np.meshgrid(grid, grid)
        s = s.ravel()
        t = t.ravel()
        # Fold the square grid into the triangle (reflect s + t > 1).
        fold = s + t > 1.0
        a = np.where(fold, 1.0 - s, s)
        b = np.where(fold, 1.0 - t, t)
        weights = np.stack((1.0 - a - b, a, b), axis=1)  # (samples, 3)
        points = np.einsum("sk,tkd->tsd", weights, corners[chosen]).reshape(-1, 3)
        uv = np.einsum("sk,tkd->tsd", weights, corner_uvs[chosen]).reshape(-1, 2)
        pixels_out.append(_project(points, perspective, width, height))
        uvs_out.append(uv)
    return np.vstack(pixels_out), np.vstack(uvs_out)


def _inside_box(pixels, box):
    xmin, xmax, ymin, ymax = box
    x = pixels[:, 0]
    y = pixels[:, 1]
    with np.errstate(invalid="ignore"):
        return (x >= xmin) & (x <= xmax) & (y >= ymin) & (y <= ymax)


def _inside_lasso(pixels, path):
    """Even-odd point-in-polygon test for every pixel against the lasso."""
    x = pixels[:, 0]
    y = pixels[:, 1]
    inside = np.zeros(len(pixels), dtype=bool)
    count = len(path)
    with np.errstate(invalid="ignore", divide="ignore"):
        for index in range(count):
            x1, y1 = path[index]
            x2, y2 = path[(index + 1) % count]
            if y1 == y2:
                continue
            crosses = (y1 > y) != (y2 > y)
            at_x = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            inside ^= crosses & (x < at_x)
    return inside & np.isfinite(x) & np.isfinite(y)


def fbp_rigless_layers_in_gesture(context, region, region_data, *, box=None, lasso=None, layers=None):
    """Rig-less layers whose solid pixels fall inside a box or lasso.

    ``box`` is (xmin, xmax, ymin, ymax) and ``lasso`` a list of (x, y), both
    in region pixels.
    """
    from .builder import fbp_rig_shown_alpha

    if np is None or (box is None and not lasso):
        return []
    depsgraph = context.evaluated_depsgraph_get()
    perspective = np.array(region_data.perspective_matrix, dtype=np.float64)
    width = float(region.width)
    height = float(region.height)
    hits = []
    for rig in tuple(layers if layers is not None else fbp_rigless_layers(context)):
        try:
            plane = rig.fbp_plane_target
            visible, union, mode = fbp_rig_shown_alpha(rig, context.scene)
            if not visible:
                continue
            plane_eval = plane.evaluated_get(depsgraph)
            pixels, uvs = _plane_samples(plane_eval, plane_eval.matrix_world, perspective, width, height)
            if pixels is None:
                continue
            inside = _inside_box(pixels, box) if box is not None else _inside_lasso(pixels, lasso)
            if not inside.any():
                continue
            if _solid_samples(union, mode, uvs[inside]).any():
                hits.append(rig)
        except (*FBP_DATA_ERRORS, IndexError):
            continue
    return hits


def fbp_apply_gesture_mode(layers, before, hits, mode):
    """Set the selection of rig-less ``layers`` from their state ``before``."""
    hit = {layer.as_pointer() for layer in hits}
    for layer in layers:
        key = layer.as_pointer()
        was = key in before
        inside = key in hit
        if mode == 'SET':
            state = inside
        elif mode == 'ADD':
            state = was or inside
        elif mode == 'SUB':
            state = was and not inside
        elif mode == 'XOR':
            state = was != inside
        else:  # AND
            state = was and inside
        try:
            layer.select_set(state)
        except FBP_DATA_ERRORS:
            continue


def _tool_mode(context, idname):
    try:
        tool = context.workspace.tools.from_space_view3d_mode(context.mode, create=False)
        props = tool.operator_properties(idname) if tool else None
        mode = str(getattr(props, "mode", "SET") or "SET")
        return mode if mode in _MODES else 'SET'
    except FBP_DATA_ERRORS:
        return 'SET'


_SHADER = None


def _shader():
    global _SHADER
    if _SHADER is None:
        _SHADER = gpu.shader.from_builtin("UNIFORM_COLOR")
    return _SHADER


def _draw_gesture(operator):
    points = operator.feedback_points()
    if len(points) < 2:
        return
    shader = _shader()
    gpu.state.blend_set("ALPHA")
    gpu.state.line_width_set(1.0)
    try:
        shader.bind()
        loop = points + [points[0]]
        shader.uniform_float("color", (0.0, 0.0, 0.0, 0.55))
        batch_for_shader(shader, "LINE_STRIP", {"pos": [(x + 1.0, y - 1.0) for x, y in loop]}).draw(shader)
        shader.uniform_float("color", (1.0, 1.0, 1.0, 0.9))
        batch_for_shader(shader, "LINE_STRIP", {"pos": loop}).draw(shader)
    finally:
        gpu.state.blend_set("NONE")


class FBP_OT_GestureSelect(Operator):
    """Box or lasso select that also picks layers without a visible rig."""

    bl_idname = "fbp.gesture_select"
    bl_label = "Select Layers (Box / Lasso)"
    bl_description = "Box or lasso select that also selects layers without a visible rig by their image"
    bl_options = {'REGISTER', 'UNDO'}

    gesture: EnumProperty(
        name="Gesture",
        items=(('BOX', "Box", "Rectangle selection"), ('LASSO', "Lasso", "Free-hand selection")),
        default='BOX',
        options={'SKIP_SAVE'},
    )
    mode: EnumProperty(name="Mode", items=_MODE_ITEMS, default='TOOL', options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return (
            getattr(context, "mode", "") == 'OBJECT'
            and getattr(getattr(context, "area", None), "type", "") == 'VIEW_3D'
            and getattr(context, "region_data", None) is not None
        )

    def feedback_points(self):
        if self.gesture == 'BOX':
            if self._start is None or self._end is None:
                return []
            (x1, y1), (x2, y2) = self._start, self._end
            return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
        return list(self._path)

    def invoke(self, context, event):
        self._layers = fbp_rigless_layers(context)
        if not self._layers:
            return {'PASS_THROUGH'}
        idname = "view3d.select_box" if self.gesture == 'BOX' else "view3d.select_lasso"
        self._mode = self.mode if self.mode in _MODES else _tool_mode(context, idname)
        self._wait = event.type not in {'LEFTMOUSE', 'RIGHTMOUSE', 'MIDDLEMOUSE'}
        self._button = None if self._wait else event.type
        start = (float(event.mouse_region_x), float(event.mouse_region_y))
        if not self._wait and event.value == 'CLICK_DRAG':
            # The drag began where the button went down, not where it was detected.
            start = (
                float(event.mouse_prev_press_x - context.region.x),
                float(event.mouse_prev_press_y - context.region.y),
            )
        self._start = None if self._wait else start
        self._end = self._start
        self._path = [] if self._wait else [start]
        self._handle = bpy.types.SpaceView3D.draw_handler_add(_draw_gesture, (self,), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _finish(self, context):
        self._remove_handle()
        context.area.tag_redraw()

    def _remove_handle(self):
        handle = getattr(self, "_handle", None)
        if handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(handle, 'WINDOW')
            self._handle = None

    def modal(self, context, event):
        point = (float(event.mouse_region_x), float(event.mouse_region_y))
        if event.type in {'ESC'} or (self._wait and event.type == 'RIGHTMOUSE' and event.value == 'PRESS'):
            self._finish(context)
            return {'CANCELLED'}
        if self._wait:
            if event.type in {'LEFTMOUSE', 'MIDDLEMOUSE'} and event.value == 'PRESS':
                self._wait = False
                self._button = event.type
                if event.type == 'MIDDLEMOUSE':
                    self._mode = 'SUB'
                self._start = self._end = point
                self._path = [point]
            return {'RUNNING_MODAL'}
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            self._end = point
            if self.gesture == 'LASSO':
                last = self._path[-1]
                if abs(point[0] - last[0]) + abs(point[1] - last[1]) >= 2.0:
                    self._path.append(point)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type == self._button and event.value == 'RELEASE':
            self._end = point
            self._finish(context)
            return self._apply(context)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        self._remove_handle()

    def _apply(self, context):
        region = context.region
        region_data = context.region_data
        before = {layer.as_pointer() for layer in self._layers if layer.select_get()}
        if self.gesture == 'BOX':
            (x1, y1), (x2, y2) = self._start, self._end
            if abs(x2 - x1) < _MIN_DRAG and abs(y2 - y1) < _MIN_DRAG:
                return {'CANCELLED'}
            box = (min(x1, x2), max(x1, x2), min(y1, y2), max(y1, y2))
            bpy.ops.view3d.select_box(
                'EXEC_DEFAULT', xmin=int(box[0]), xmax=int(box[1]), ymin=int(box[2]), ymax=int(box[3]),
                wait_for_input=False, mode=self._mode,
            )
            hits = fbp_rigless_layers_in_gesture(context, region, region_data, box=box, layers=self._layers)
        else:
            if len(self._path) < 3:
                return {'CANCELLED'}
            bpy.ops.view3d.select_lasso(
                'EXEC_DEFAULT',
                path=[{"name": "", "loc": point, "time": 0.0} for point in self._path],
                mode=self._mode,
            )
            hits = fbp_rigless_layers_in_gesture(context, region, region_data, lasso=self._path, layers=self._layers)
        fbp_apply_gesture_mode(self._layers, before, hits, self._mode)
        active = context.view_layer.objects.active
        if hits and (active is None or not active.select_get()):
            context.view_layer.objects.active = hits[0]
        return {'FINISHED'}


# Default gesture bindings this operator mirrors: (keymap, gesture, type,
# value, shift, ctrl, mode). Tool keymaps follow the active tool's mode.
FBP_GESTURE_BINDINGS = (
    ('3D View Tool: Select Box', 'BOX', 'LEFTMOUSE', 'CLICK_DRAG', False, False, 'TOOL'),
    ('3D View Tool: Select Box', 'BOX', 'LEFTMOUSE', 'CLICK_DRAG', True, False, 'ADD'),
    ('3D View Tool: Select Box', 'BOX', 'LEFTMOUSE', 'CLICK_DRAG', False, True, 'SUB'),
    ('3D View Tool: Select Box', 'BOX', 'LEFTMOUSE', 'CLICK_DRAG', True, True, 'AND'),
    ('3D View Tool: Select Box (fallback)', 'BOX', 'LEFTMOUSE', 'CLICK_DRAG', False, False, 'TOOL'),
    ('3D View Tool: Select Box (fallback)', 'BOX', 'LEFTMOUSE', 'CLICK_DRAG', True, False, 'ADD'),
    ('3D View Tool: Select Box (fallback)', 'BOX', 'LEFTMOUSE', 'CLICK_DRAG', False, True, 'SUB'),
    ('3D View Tool: Select Box (fallback)', 'BOX', 'LEFTMOUSE', 'CLICK_DRAG', True, True, 'AND'),
    ('3D View Tool: Select Lasso', 'LASSO', 'LEFTMOUSE', 'CLICK_DRAG', False, False, 'TOOL'),
    ('3D View Tool: Select Lasso', 'LASSO', 'LEFTMOUSE', 'CLICK_DRAG', True, False, 'ADD'),
    ('3D View Tool: Select Lasso', 'LASSO', 'LEFTMOUSE', 'CLICK_DRAG', False, True, 'SUB'),
    ('3D View Tool: Select Lasso', 'LASSO', 'LEFTMOUSE', 'CLICK_DRAG', True, True, 'AND'),
    ('3D View Tool: Select Lasso (fallback)', 'LASSO', 'LEFTMOUSE', 'CLICK_DRAG', False, False, 'TOOL'),
    ('3D View Tool: Select Lasso (fallback)', 'LASSO', 'LEFTMOUSE', 'CLICK_DRAG', True, False, 'ADD'),
    ('3D View Tool: Select Lasso (fallback)', 'LASSO', 'LEFTMOUSE', 'CLICK_DRAG', False, True, 'SUB'),
    ('3D View Tool: Select Lasso (fallback)', 'LASSO', 'LEFTMOUSE', 'CLICK_DRAG', True, True, 'AND'),
    ('Object Mode', 'BOX', 'B', 'PRESS', False, False, 'SET'),
    ('Object Mode', 'LASSO', 'RIGHTMOUSE', 'CLICK_DRAG', False, True, 'ADD'),
    ('Object Mode', 'LASSO', 'RIGHTMOUSE', 'CLICK_DRAG', True, True, 'SUB'),
)
