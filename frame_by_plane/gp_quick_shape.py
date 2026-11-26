"""Quick Shape for the Grease Pencil Draw brush.

Draw a roughly straight stroke and keep the pen still at its end: the stroke
turns into a straight line from its first point to the cursor. While the
button is still held the end of the line follows the cursor; Shift slows the
end down for precise placement and Ctrl snaps the angle on screen. Releasing
the button finishes an ordinary Blender stroke.

Blender's own ``grease_pencil.brush_stroke`` keeps drawing the stroke. This
operator starts it, then sits in front of it in the window's modal handlers:
it watches the events and passes them through while the stroke is free, and
once Quick Shape starts it keeps the mouse moves for itself and rewrites the
points of the stroke being drawn as a line. The release reaches the brush,
which finishes the stroke as usual (smoothing, simplify, undo step).
"""

from __future__ import annotations

import math
import time

import bpy
from bpy.types import Operator
from bpy_extras import view3d_utils
from mathutils import Vector

from .interface_preferences import fbp_get_addon_preferences
from .registration import register_classes, unregister_classes
from .runtime import FBP_DATA_ERRORS, FBP_DATA_IO_ERRORS, fbp_warn_once


# Quick Shape can start only in the first seconds of a stroke; later the
# stroke stays free hand however long the pen rests.
DETECTION_WINDOW_SECONDS = 10.0
# Pixels the cursor may drift while it counts as still.
HOLD_TOLERANCE_PX = 6.0
# Shortest stroke, in pixels, that can become a line.
MIN_LENGTH_PX = 20.0
# Largest distance of the drawn path from the start-to-end chord, as a share
# of the chord length, with a floor in pixels for short strokes.
STRAIGHT_DEVIATION_RATIO = 0.1
STRAIGHT_DEVIATION_MIN_PX = 8.0
# The drawn path may be at most this much longer than the chord (rules out
# strokes that go back and forth on the same line).
STRAIGHT_PATH_RATIO = 1.25
TIMER_STEP_SECONDS = 0.02

_MOVE_EVENTS = frozenset({"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"})
_SHIFT_KEYS = frozenset({"LEFT_SHIFT", "RIGHT_SHIFT"})
_CTRL_KEYS = frozenset({"LEFT_CTRL", "RIGHT_CTRL", "OSKEY"})
_BRUSH_STROKE_ID = "GREASE_PENCIL_OT_brush_stroke"

_ADDON_KEYMAPS = []


def quick_shape_settings(context=None):
    """Validated Quick Shape preferences: (enabled, hold, snap, precision)."""
    preferences = fbp_get_addon_preferences(context)
    enabled = bool(getattr(preferences, "gp_quick_shape_enabled", True))
    try:
        hold = float(getattr(preferences, "gp_quick_shape_hold_time", 0.4))
    except (TypeError, ValueError):
        hold = 0.4
    try:
        snap = float(str(getattr(preferences, "gp_quick_shape_snap_angle", "15") or "15"))
    except (TypeError, ValueError):
        snap = 15.0
    try:
        precision = float(getattr(preferences, "gp_quick_shape_precision", 0.25))
    except (TypeError, ValueError):
        precision = 0.25
    return (
        enabled,
        min(max(hold, 0.1), 3.0),
        min(max(snap, 1.0), 90.0),
        min(max(precision, 0.02), 1.0),
    )


def is_straight_path(points, tolerance_ratio=STRAIGHT_DEVIATION_RATIO):
    """Whether a screen path (sequence of (x, y)) is close to a straight line."""
    if len(points) < 2:
        return False
    sx, sy = points[0]
    ex, ey = points[-1]
    dx, dy = ex - sx, ey - sy
    chord = math.hypot(dx, dy)
    if chord < MIN_LENGTH_PX:
        return False
    limit = max(STRAIGHT_DEVIATION_MIN_PX, chord * tolerance_ratio)
    path_length = 0.0
    previous = points[0]
    for x, y in points:
        # Distance from the chord line; the chord is long enough to divide.
        if abs((x - sx) * dy - (y - sy) * dx) / chord > limit:
            return False
        path_length += math.hypot(x - previous[0], y - previous[1])
        previous = (x, y)
    # Points past either end of the chord make the stroke a hook, not a line.
    for x, y in points:
        along = ((x - sx) * dx + (y - sy) * dy) / chord
        if along < -limit or along > chord + limit:
            return False
    return path_length <= chord * STRAIGHT_PATH_RATIO + STRAIGHT_DEVIATION_MIN_PX


def snap_screen_angle(start, end, step_degrees):
    """End point with the start-to-end angle rounded to ``step_degrees``."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length < 1.0e-6 or step_degrees <= 0.0:
        return end
    step = math.radians(step_degrees)
    angle = round(math.atan2(dy, dx) / step) * step
    return (start[0] + math.cos(angle) * length, start[1] + math.sin(angle) * length)


def _layer_to_world(obj, layer):
    """Matrix from the layer's point space to world space."""
    local = layer.matrix_local.copy()
    parent = getattr(layer, "parent", None)
    if parent is None:
        return obj.matrix_world @ local
    parent_matrix = parent.matrix_world.copy()
    bone_name = str(getattr(layer, "parent_bone", "") or "")
    if bone_name and getattr(parent, "type", "") == "ARMATURE":
        pose_bone = parent.pose.bones.get(bone_name) if parent.pose else None
        if pose_bone is not None:
            parent_matrix = parent_matrix @ pose_bone.matrix
    return parent_matrix @ layer.matrix_parent_inverse @ local


def _active_target(context):
    obj = getattr(context, "active_object", None)
    if obj is None or getattr(obj, "type", "") != "GREASEPENCIL":
        return None, None, None
    layer = obj.data.layers.active
    if layer is None:
        return obj, None, None
    frame = layer.current_frame()
    drawing = frame.drawing if frame is not None else None
    return obj, layer, drawing


def _curve_point_range(drawing, curve_index):
    offsets = drawing.curve_offsets
    return int(offsets[curve_index].value), int(offsets[curve_index + 1].value)


class FBP_OT_GPQuickShapeStroke(Operator):
    """Draw with the brush; rest the pen at the end of a straight stroke to turn it into a line (Shift: precise, Ctrl: snap angle)"""

    bl_idname = "fbp.gp_quick_shape_stroke"
    bl_label = "Draw with Quick Shape"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        if str(getattr(context, "mode", "") or "") != "PAINT_GREASE_PENCIL":
            return False
        area = getattr(context, "area", None)
        region = getattr(context, "region", None)
        if area is None or area.type != "VIEW_3D" or region is None or region.type != "WINDOW":
            return False
        if not quick_shape_settings(context)[0]:
            return False
        try:
            brush = context.tool_settings.gpencil_paint.brush
            return brush is not None and brush.gpencil_brush_type == "DRAW"
        except FBP_DATA_ERRORS:
            return False

    # -- lifecycle ---------------------------------------------------------

    def invoke(self, context, event):
        _enabled, self._hold, self._snap, self._precision = quick_shape_settings(context)
        self._area = context.area
        self._region = context.region
        self._rv3d = context.region_data
        self._window = context.window
        self._button = event.type
        self._started = time.monotonic()
        start = (float(event.mouse_region_x), float(event.mouse_region_y))
        self._path = [start]
        self._rest_anchor = start
        self._rest_since = self._started
        self._state = "WATCH"
        self._timer = None

        obj, _layer, drawing = _active_target(context)
        try:
            self._baseline = (
                int(drawing.as_pointer()) if drawing is not None else 0,
                len(drawing.strokes) if drawing is not None else 0,
            )
        except FBP_DATA_ERRORS:
            self._baseline = (0, 0)
        del obj

        result = bpy.ops.grease_pencil.brush_stroke("INVOKE_DEFAULT")
        if "RUNNING_MODAL" not in result:
            return {"FINISHED"} if "FINISHED" in result else {"CANCELLED"}
        try:
            self._timer = context.window_manager.event_timer_add(TIMER_STEP_SECONDS, window=context.window)
        except FBP_DATA_ERRORS:
            self._timer = None
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _finish(self, context):
        if self._timer is not None:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except FBP_DATA_ERRORS:
                pass
            self._timer = None

    def _brush_running(self):
        try:
            return any(
                str(getattr(op, "bl_idname", "") or "") == _BRUSH_STROKE_ID
                for op in self._window.modal_operators
            )
        except FBP_DATA_ERRORS:
            return False

    # -- events ------------------------------------------------------------

    def modal(self, context, event):
        try:
            return self._modal(context, event)
        except FBP_DATA_IO_ERRORS as exc:
            fbp_warn_once("gp_quick_shape.modal", "Quick Shape stopped", exc)
            self._finish(context)
            return {"FINISHED", "PASS_THROUGH"}

    def _modal(self, context, event):
        released = event.type == self._button and event.value == "RELEASE"
        if self._state == "WATCH":
            if released:
                self._finish(context)
                return {"FINISHED", "PASS_THROUGH"}
            now = time.monotonic()
            if now - self._started > DETECTION_WINDOW_SECONDS or (
                event.type == "TIMER" and not self._brush_running()
            ):
                # Past the detection window the stroke stays free hand.
                self._finish(context)
                return {"FINISHED", "PASS_THROUGH"}
            if event.type in _MOVE_EVENTS:
                point = (float(event.mouse_region_x), float(event.mouse_region_y))
                if math.hypot(point[0] - self._path[-1][0], point[1] - self._path[-1][1]) >= 1.0:
                    self._path.append(point)
                if math.hypot(point[0] - self._rest_anchor[0], point[1] - self._rest_anchor[1]) > HOLD_TOLERANCE_PX:
                    self._rest_anchor = point
                    self._rest_since = now
            elif event.type == "TIMER" and now - self._rest_since >= self._hold:
                if self._path_is_straight() and self._begin_line(context, event):
                    self._state = "LINE"
                    return {"PASS_THROUGH"}
                # Not a line: wait for the cursor to move and rest again.
                self._rest_since = now
            return {"PASS_THROUGH"}

        # LINE: the end of the line follows the cursor.
        if released:
            self._update_line(event)
            self._finish(context)
            return {"FINISHED", "PASS_THROUGH"}
        if event.type == "TIMER":
            if not self._brush_running():
                self._finish(context)
                return {"FINISHED", "PASS_THROUGH"}
            return {"PASS_THROUGH"}
        if event.type in _MOVE_EVENTS:
            mouse = (float(event.mouse_region_x), float(event.mouse_region_y))
            factor = self._precision if event.shift else 1.0
            self._target = (
                self._target[0] + (mouse[0] - self._last_mouse[0]) * factor,
                self._target[1] + (mouse[1] - self._last_mouse[1]) * factor,
            )
            self._last_mouse = mouse
            self._update_line(event)
            # The brush must not extend the stroke any more.
            return {"RUNNING_MODAL"}
        if event.type in _SHIFT_KEYS or event.type in _CTRL_KEYS:
            self._update_line(event)
            return {"RUNNING_MODAL"}
        return {"PASS_THROUGH"}

    def _path_is_straight(self):
        # Only the path up to where the cursor came to rest counts.
        anchor = self._rest_anchor
        path = list(self._path)
        while len(path) > 2 and math.hypot(path[-1][0] - anchor[0], path[-1][1] - anchor[1]) <= HOLD_TOLERANCE_PX:
            path.pop()
        path.append(anchor)
        return is_straight_path(path)

    # -- geometry ----------------------------------------------------------

    def _begin_line(self, context, event):
        obj, layer, drawing = _active_target(context)
        if drawing is None:
            return False
        count = len(drawing.strokes)
        if count == 0:
            return False
        pointer = int(drawing.as_pointer())
        if pointer == self._baseline[0] and count != self._baseline[1] + 1:
            return False
        try:
            on_back = bool(context.scene.tool_settings.use_gpencil_draw_onback)
        except FBP_DATA_ERRORS:
            on_back = False
        curve_index = 0 if on_back else count - 1
        first, last = _curve_point_range(drawing, curve_index)
        if last - first < 2:
            return False

        positions = drawing.attributes["position"].data
        layer_points = [Vector(positions[i].vector) for i in range(first, last)]
        to_world = _layer_to_world(obj, layer)
        world_points = [to_world @ point for point in layer_points]
        start_world = world_points[0]
        start_screen = view3d_utils.location_3d_to_region_2d(self._region, self._rv3d, start_world)
        if start_screen is None:
            return False

        self._drawing_pointer = pointer
        self._obj_name = obj.name
        self._curve_index = curve_index
        self._point_count = last - first
        self._to_layer = to_world.inverted_safe()
        self._start_world = start_world
        self._start_screen = (float(start_screen.x), float(start_screen.y))
        self._plane_normal = self._placement_normal(context, world_points)
        self._target = self._rest_anchor
        self._last_mouse = (float(event.mouse_region_x), float(event.mouse_region_y))
        self._end_world = world_points[-1]
        self._update_line(event)
        return True

    def _placement_normal(self, context, world_points):
        """Normal of the plane the stroke was drawn on, in world space."""
        view_normal = (self._rv3d.view_rotation @ Vector((0.0, 0.0, 1.0))).normalized()
        candidates = []
        try:
            lock = str(context.scene.tool_settings.gpencil_sculpt.lock_axis)
        except FBP_DATA_ERRORS:
            lock = "VIEW"
        preferred = {
            "AXIS_X": Vector((1.0, 0.0, 0.0)),
            "AXIS_Y": Vector((0.0, 1.0, 0.0)),
            "AXIS_Z": Vector((0.0, 0.0, 1.0)),
        }.get(lock)
        if lock == "CURSOR":
            try:
                preferred = (context.scene.cursor.matrix.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()
            except FBP_DATA_ERRORS:
                preferred = None
        if preferred is not None:
            candidates.append(preferred)
        candidates.append(view_normal)
        obj = context.active_object
        rotation = obj.matrix_world.to_3x3().normalized()
        for axis in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)):
            candidates.append(Vector(axis))
            candidates.append((rotation @ Vector(axis)).normalized())

        origin = world_points[0]
        extent = max(((point - origin).length for point in world_points), default=0.0)
        tolerance = max(extent * 0.02, 1.0e-6)

        def residual(normal):
            return max(abs((point - origin).dot(normal)) for point in world_points)

        # The plane must also face the view, or the line end cannot be
        # placed under the cursor.
        usable = [n for n in candidates if abs(n.dot(view_normal)) > 0.05]
        for normal in usable:
            if residual(normal) <= tolerance:
                return normal
        if usable:
            best = min(usable, key=residual)
            if residual(best) <= extent * 0.15:
                return best
        return view_normal

    def _screen_to_world(self, screen):
        origin = view3d_utils.region_2d_to_origin_3d(self._region, self._rv3d, screen)
        direction = view3d_utils.region_2d_to_vector_3d(self._region, self._rv3d, screen)
        normal = self._plane_normal
        denominator = direction.dot(normal)
        if abs(denominator) < 1.0e-6:
            return None
        distance = (self._start_world - origin).dot(normal) / denominator
        return origin + direction * distance

    def _update_line(self, event):
        end = self._target
        if event.ctrl or event.oskey:
            end = snap_screen_angle(self._start_screen, end, self._snap)
        end_world = self._screen_to_world(end)
        if end_world is not None:
            self._end_world = end_world
        obj = bpy.data.objects.get(self._obj_name)
        if obj is None:
            return
        layer = obj.data.layers.active
        frame = layer.current_frame() if layer is not None else None
        drawing = frame.drawing if frame is not None else None
        if drawing is None or int(drawing.as_pointer()) != self._drawing_pointer:
            return
        if self._curve_index >= len(drawing.strokes):
            return
        first, last = _curve_point_range(drawing, self._curve_index)
        if last - first != self._point_count:
            return
        start = self._to_layer @ self._start_world
        stop = self._to_layer @ self._end_world
        positions = drawing.attributes["position"].data
        steps = max(1, self._point_count - 1)
        for offset in range(self._point_count):
            positions[first + offset].vector = start.lerp(stop, offset / steps)
        drawing.tag_positions_changed()
        if self._area is not None:
            self._area.tag_redraw()


classes = (FBP_OT_GPQuickShapeStroke,)


def _register_keymaps():
    _unregister_keymaps()
    window_manager = getattr(bpy.context, "window_manager", None)
    keyconfig = getattr(getattr(window_manager, "keyconfigs", None), "addon", None)
    if keyconfig is None:
        return False
    try:
        keymap = keyconfig.keymaps.new(name="Grease Pencil Brush Stroke", space_type="EMPTY", region_type="WINDOW")
        item = keymap.keymap_items.new(FBP_OT_GPQuickShapeStroke.bl_idname, "LEFTMOUSE", "PRESS", head=True)
        _ADDON_KEYMAPS.append((keymap, item))
        return True
    except FBP_DATA_ERRORS as exc:
        _unregister_keymaps()
        fbp_warn_once("gp_quick_shape.keymap", "Could not register the Grease Pencil Quick Shape shortcut", exc)
        return False


def _unregister_keymaps():
    while _ADDON_KEYMAPS:
        keymap, item = _ADDON_KEYMAPS.pop()
        try:
            keymap.keymap_items.remove(item)
        except FBP_DATA_ERRORS:
            pass


def register():
    register_classes(classes)
    _register_keymaps()


def unregister():
    _unregister_keymaps()
    unregister_classes(classes)
