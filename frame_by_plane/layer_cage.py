"""Transform cage around the selected layers, in the style of Blender's
Grease Pencil transform box.

Only selected layers show it, so a layer without a rig wire still shows how
much of the scene it covers, and unselected layers stay clean. The cage is
Blender's own 2D cage gizmo laid on the image plane:

* drag inside the box to move the layer;
* drag an edge to stretch it, a corner to scale it (Shift keeps proportions,
  Alt scales from the centre, as in Blender);
* drag the round handle above the box to rotate it around its centre
  (Ctrl snaps to 15 degrees).

A plain click is never taken by the cage: it goes on to Blender and to
Select Through Transparency, so clicking a layer behind still works. A layer
that shows effect handles (Crop, Gradient, Shape Mask...) shows those instead
of the box, so they stay the ones that receive the drag.

As in Grease Pencil's box, the edge and corner dots appear only when the
cursor comes near; the knob on top and the pivot cross stay visible.
"""

from __future__ import annotations

import bpy
import gpu
from mathutils import Matrix, Vector

from .runtime import FBP_DATA_ERRORS
from .viewport_handles import handle_selected_color


_MAX_CAGES = 32
_ACTIVE_COLOR = (1.0, 1.0, 1.0)
_SELECTED_COLOR = (0.72, 0.72, 0.72)


def cage_enabled(context=None):
    try:
        from .interface_preferences import fbp_get_addon_preferences
        preferences = fbp_get_addon_preferences()
        return bool(getattr(preferences, "show_layer_cage", True)) if preferences else True
    except (ImportError, *FBP_DATA_ERRORS):
        return True


def _cage_layers(context):
    """Selected, visible, selectable layers (rigs with an image plane)."""
    layers = []
    for obj in tuple(getattr(context, "selected_objects", ()) or ()):
        try:
            if not bool(getattr(obj, "is_fbp_control", False)):
                continue
            if getattr(obj, "fbp_plane_target", None) is None:
                continue
            if bool(getattr(obj, "hide_select", False)) or not obj.visible_get():
                continue
        except FBP_DATA_ERRORS:
            continue
        layers.append(obj)
        if len(layers) >= _MAX_CAGES:
            break
    return layers


def layer_cage_rect(rig, depsgraph=None):
    """``(center, size)`` of the layer's visible plane in rig space (XY).

    Uses the evaluated plane, so Crop, Extend and mesh effects are included.
    """
    plane = getattr(rig, "fbp_plane_target", None)
    if plane is None:
        return None
    try:
        source = plane.evaluated_get(depsgraph) if depsgraph is not None else plane
        relation = rig.matrix_world.inverted_safe() @ source.matrix_world
        corners = [relation @ Vector(corner) for corner in source.bound_box]
    except (*FBP_DATA_ERRORS, IndexError):
        return None
    xs = [corner.x for corner in corners]
    ys = [corner.y for corner in corners]
    size = Vector((max(xs) - min(xs), max(ys) - min(ys)))
    if size.x <= 1.0e-6 or size.y <= 1.0e-6:
        return None
    center = Vector(((max(xs) + min(xs)) * 0.5, (max(ys) + min(ys)) * 0.5, 0.0))
    return center, size


def _rigs_with_handles(context):
    """Pointers of the layers that currently show effect handles."""
    try:
        from .handle_overlay import _visible_handles
        from .viewport_handles import attached_plane
    except ImportError:
        return set()
    pointers = set()
    for handle in _visible_handles(context):
        try:
            plane = attached_plane(handle)
            if plane is not None:
                pointers.add(plane.as_pointer())
        except FBP_DATA_ERRORS:
            continue
    return pointers


def _shows_color_plane_gradient(context, rig):
    """True while a Gradient Color Plane shows its gradient line and dots,
    which sit on the box's side handles by default."""
    try:
        from .handle_overlay import color_plane_gradient_shown
        return color_plane_gradient_shown(context, rig)
    except ImportError:
        return False


def _shows_lattice_handles(rig):
    """True while the layer's Lattice shows Corner Pin or Grid point handles.

    Those draw their own Perspective quad or Grid lines on the layer's edges,
    so the transform box steps aside as it does for Crop.
    """
    try:
        from .lattice_bones import bones_object
        from .lattice_corner_pin import CORNER_ROLE_KEY
        from .lattice_pins import PIN_POINT_KEY
    except ImportError:
        return False
    try:
        armature = bones_object(rig)
        if armature is None or not armature.visible_get():
            return False
        return any(
            not bone.bone.hide and (bone.get(CORNER_ROLE_KEY) or bone.get(PIN_POINT_KEY) is not None)
            for bone in armature.pose.bones
        )
    except FBP_DATA_ERRORS:
        return False


def _flatten(matrix):
    """Column-major floats, the layout gizmo matrix targets use."""
    return [matrix[row][column] for column in range(4) for row in range(4)]


def _unflatten(values):
    values = list(values)
    return Matrix([[values[column * 4 + row] for column in range(4)] for row in range(4)])


def _rigid_basis(matrix_world):
    location, rotation, _scale = matrix_world.decompose()
    return Matrix.Translation(location) @ rotation.to_matrix().to_4x4()


class _CageBinding:
    """Maps the cage's offset matrix to the rig's world transform.

    The gizmo's basis is the rig's world location and rotation; the offset
    matrix maps the unit cage to the plane rectangle, scaled by the rig's
    scale. The cage writes a new offset matrix while it drags and the rig's
    world matrix follows: ``basis @ offset @ unit_to_rig^-1``.
    """

    def __init__(self, rig_name):
        self.rig_name = rig_name
        self.basis = Matrix.Identity(4)
        self.unit = Matrix.Identity(4)
        self.style = None

    def rig(self):
        return bpy.data.objects.get(self.rig_name)

    def refresh(self, rig, center, size):
        self.basis = _rigid_basis(rig.matrix_world)
        self.unit = Matrix.Translation(center) @ Matrix.Diagonal((size.x, size.y, 1.0, 1.0))

    def get(self):
        rig = self.rig()
        if rig is None:
            return _flatten(Matrix.Identity(4))
        try:
            relative = self.basis.inverted_safe() @ rig.matrix_world
        except FBP_DATA_ERRORS:
            return _flatten(Matrix.Identity(4))
        return _flatten(relative @ self.unit)

    def set(self, values):
        rig = self.rig()
        if rig is None:
            return
        try:
            world = self.basis @ _unflatten(values) @ self.unit.inverted_safe()
            before = (rig.location.copy(), _rotation_copy(rig), rig.scale.copy())
            rig.matrix_world = world
            _restore_locked(rig, before)
            _auto_key(rig)
        except FBP_DATA_ERRORS:
            return


def _rotation_copy(rig):
    mode = str(getattr(rig, "rotation_mode", "XYZ") or "XYZ")
    if mode == "QUATERNION":
        return rig.rotation_quaternion.copy()
    if mode == "AXIS_ANGLE":
        return tuple(rig.rotation_axis_angle)
    return rig.rotation_euler.copy()


def _restore_locked(rig, before):
    location, rotation, scale = before
    for axis in range(3):
        if rig.lock_location[axis]:
            rig.location[axis] = location[axis]
        if rig.lock_scale[axis]:
            rig.scale[axis] = scale[axis]
    if any(rig.lock_rotation):
        mode = str(getattr(rig, "rotation_mode", "XYZ") or "XYZ")
        if mode == "QUATERNION":
            rig.rotation_quaternion = rotation
        elif mode == "AXIS_ANGLE":
            rig.rotation_axis_angle = rotation
        else:
            for axis in range(3):
                if rig.lock_rotation[axis]:
                    rig.rotation_euler[axis] = rotation[axis]


def _auto_key(rig):
    try:
        scene = bpy.context.scene
        if not bool(scene.tool_settings.use_keyframe_insert_auto):
            return
        frame = scene.frame_current
        for path in ("location", "rotation_euler", "scale"):
            if path == "rotation_euler" and rig.rotation_mode in {"QUATERNION", "AXIS_ANGLE"}:
                path = "rotation_quaternion" if rig.rotation_mode == "QUATERNION" else "rotation_axis_angle"
            rig.keyframe_insert(path, frame=frame, group="Object Transforms")
    except FBP_DATA_ERRORS:
        return


# --- Cursor proximity -------------------------------------------------------
#
# Like Grease Pencil's transform box, secondary handles (edge squares, the
# rotation knob, the side handles of Crop) appear only when the cursor comes
# near. Drawing code registers screen-space zones; an invisible probe gizmo
# sees every mouse move in the viewport and asks for a redraw only when the
# cursor enters or leaves a zone.

PROXIMITY_MARGIN_PX = 48.0
_CURSOR = {"region": 0, "xy": None}
_ZONES = {}


def _region_key(region):
    try:
        return int(region.as_pointer())
    except FBP_DATA_ERRORS:
        return 0


def _zone_near(rect, xy, margin):
    if xy is None or rect is None:
        return False
    min_x, min_y, max_x, max_y = rect
    x, y = xy
    return (min_x - margin) <= x <= (max_x + margin) and (min_y - margin) <= y <= (max_y + margin)


def proximity_near(key, region, points, margin=PROXIMITY_MARGIN_PX):
    """True when the cursor is within ``margin`` px of the screen ``points``.

    Also records the zone, so the probe redraws the view when the cursor
    crosses its border.
    """
    points = [point for point in points if point is not None]
    region_key = _region_key(region)
    if not points or not region_key:
        return False
    rect = (
        min(point[0] for point in points), min(point[1] for point in points),
        max(point[0] for point in points), max(point[1] for point in points),
    )
    xy = _CURSOR["xy"] if _CURSOR["region"] == region_key else None
    near = _zone_near(rect, xy, margin)
    _ZONES[(region_key, key)] = (rect, margin, near)
    return near


def _cursor_moved(region, xy):
    region_key = _region_key(region)
    _CURSOR["region"] = region_key
    _CURSOR["xy"] = (float(xy[0]), float(xy[1]))
    changed = False
    for (zone_region, _key), (rect, margin, near) in tuple(_ZONES.items()):
        if zone_region == region_key and _zone_near(rect, _CURSOR["xy"], margin) != near:
            changed = True
            break
    if changed:
        try:
            region.tag_redraw()
        except FBP_DATA_ERRORS:
            pass


_HOVER = {"region": 0, "name": ""}


def hovered_handle_name(region):
    """Name of the viewport handle under the cursor in ``region``, or ""."""
    return _HOVER["name"] if _HOVER["region"] == _region_key(region) else ""


def _update_hover(context, xy):
    """Track the handle under the cursor; redraw only when it changes."""
    name = ""
    try:
        from .alpha_pick import fbp_handle_under_cursor
        scale = float(context.preferences.system.ui_scale) or 1.0
        handle = fbp_handle_under_cursor(context, xy, 4.0 * scale)
        name = str(handle.name) if handle is not None else ""
        if not name:
            from .handle_overlay import lattice_handle_under_cursor
            name = lattice_handle_under_cursor(context, xy, 4.0 * scale)
    except (ImportError, *FBP_DATA_ERRORS):
        name = ""
    set_hovered_handle(context, name)


def set_hovered_handle(context, name):
    """Light up the handle called ``name`` (or none); redraw when it changes."""
    region_key = _region_key(context.region)
    if (_HOVER["region"], _HOVER["name"]) != (region_key, name):
        _HOVER["region"], _HOVER["name"] = region_key, name
        try:
            context.region.tag_redraw()
        except FBP_DATA_ERRORS:
            pass


class FBP_GT_cursor_probe(bpy.types.Gizmo):
    """Invisible gizmo that only watches the cursor; it never takes a click."""

    bl_idname = "FBP_GT_cursor_probe"

    def draw(self, context):
        del context

    def test_select(self, context, location):
        try:
            _cursor_moved(context.region, location)
        except FBP_DATA_ERRORS:
            pass
        # Handles light up under the cursor, as Blender's gizmos do.
        _update_hover(context, location)
        return -1


def _proximity_wanted(context):
    if _cage_layers(context):
        return True
    try:
        from .handle_overlay import _visible_lattice_handles
        if next(_visible_lattice_handles(context), None) is not None:
            return True
    except ImportError:
        pass
    try:
        from .handle_overlay import _visible_handles
        return bool(_visible_handles(context))
    except ImportError:
        return False


class FBP_GGT_cursor_probe(bpy.types.GizmoGroup):
    bl_idname = "FBP_GGT_cursor_probe"
    bl_label = "Frame By Plane Cursor Probe"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}

    @classmethod
    def poll(cls, context):
        try:
            # Pose Mode too: Lattice handles are edited there.
            if context.mode not in {"OBJECT", "POSE"} or not context.space_data.overlay.show_overlays:
                return False
        except FBP_DATA_ERRORS:
            return False
        if _proximity_wanted(context):
            return True
        _ZONES.clear()
        _HOVER["name"] = ""
        return False

    def setup(self, context):
        del context
        self.gizmos.new(FBP_GT_cursor_probe.bl_idname)


_ROTATE_OFFSET_PX = 18.0
_ROTATE_RADIUS_PX = 3.5


def _pixels_per_unit(region, region_data, origin, direction):
    """Screen pixels covered by one world unit along ``direction`` at ``origin``."""
    from bpy_extras.view3d_utils import location_3d_to_region_2d

    start = location_3d_to_region_2d(region, region_data, origin)
    end = location_3d_to_region_2d(region, region_data, origin + direction)
    if start is None or end is None:
        return None
    length = (end - start).length
    return length if length > 1.0e-6 else None


_MARK_RADIUS_PX = 3.0
_CROSS_HALF_PX = 5.0


def _cross_triangles(half, width=0.6):
    """A small X, the pivot marker at the centre of Grease Pencil's box."""
    import math

    triangles = []
    for angle in (math.radians(45.0), math.radians(-45.0)):
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        for x, y in ((-half, -width), (half, -width), (half, width), (-half, -width), (half, width), (-half, width)):
            triangles.append((x * cos_a - y * sin_a, x * sin_a + y * cos_a, 0.0))
    return triangles


def _stem_triangles(bottom, top, half_width=0.6):
    return [
        (-half_width, bottom, 0.0), (half_width, bottom, 0.0), (half_width, top, 0.0),
        (-half_width, bottom, 0.0), (half_width, top, 0.0), (-half_width, top, 0.0),
    ]


# Python gizmos route every attribute through ``Gizmo.__getattribute__`` /
# ``__setattr__``, which first look the name up among the gizmo's operator-
# style ``properties`` (a path lookup per access). The base Gizmo RNA values
# (hide, matrices, is_modal) and our own slots are never there, so the redraw
# loop reads and writes them directly.
_RNA_SET = bpy.types.bpy_struct.__setattr__
_RNA_GET = bpy.types.bpy_struct.__getattribute__


class FBP_GT_layer_rotate(bpy.types.Gizmo):
    """Round handle above the transform box: drag it to rotate the layer.

    The layer turns around the box centre, about its own normal; Ctrl snaps
    to 15 degree steps, Esc or right click cancels.
    """

    bl_idname = "FBP_GT_layer_rotate"
    __slots__ = (
        "fbp_rim", "fbp_disc", "fbp_stem", "fbp_rig_name", "fbp_center",
        "fbp_initial", "fbp_start_angle", "fbp_color", "fbp_dot", "fbp_dot_rim",
        "fbp_cross", "fbp_cross_rim", "fbp_center_matrix", "fbp_marks", "fbp_near",
    )

    def setup(self):
        from .handle_overlay import _disc_triangles, _ring_triangles

        radius = _ROTATE_RADIUS_PX
        self.fbp_rim = self.new_custom_shape("TRIS", _ring_triangles(radius + 1.4, radius - 0.2))
        self.fbp_disc = self.new_custom_shape("TRIS", _disc_triangles(radius))
        self.fbp_stem = self.new_custom_shape("TRIS", _stem_triangles(-_ROTATE_OFFSET_PX, -radius))
        self.fbp_dot = self.new_custom_shape("TRIS", _disc_triangles(_MARK_RADIUS_PX))
        self.fbp_dot_rim = self.new_custom_shape("TRIS", _disc_triangles(_MARK_RADIUS_PX + 1.2))
        self.fbp_cross = self.new_custom_shape("TRIS", _cross_triangles(_CROSS_HALF_PX))
        self.fbp_cross_rim = self.new_custom_shape("TRIS", _cross_triangles(_CROSS_HALF_PX + 0.8, 1.4))
        self.fbp_center_matrix = None
        self.fbp_marks = ()
        self.fbp_near = False
        self.fbp_rig_name = ""
        self.fbp_center = (0.0, 0.0, 0.0)
        self.fbp_initial = None
        self.fbp_start_angle = 0.0
        self.fbp_color = (1.0, 1.0, 1.0)
        self.use_draw_scale = False

    @staticmethod
    def _draw_shape(shape, color, alpha, matrix):
        # Same as Gizmo.draw_custom_shape with color == color_highlight, but
        # without its per-shape property writes and reads: every attribute
        # of a Python gizmo goes through a slow RNA path lookup.
        batch, shader = shape
        shader.uniform_float("color", (*color, alpha))
        use_blend = alpha < 1.0
        if use_blend:
            gpu.state.blend_set("ALPHA")
        with gpu.matrix.push_pop():
            gpu.matrix.multiply_matrix(matrix)
            batch.draw(shader)
        if use_blend:
            gpu.state.blend_set("NONE")

    def draw(self, context):
        draw_shape = self._draw_shape
        get = _RNA_GET
        color = tuple(get(self, "fbp_color"))
        world = get(self, "matrix_world")
        modal = bool(get(self, "is_modal"))
        # Like Grease Pencil's box: a pivot cross in the middle, the knob on
        # top, and dots on the corners and edges only while the cursor is
        # near. The dots are drawn, never picked: the cage under them takes
        # the drag.
        center_matrix = get(self, "fbp_center_matrix")
        if center_matrix is not None:
            draw_shape(get(self, "fbp_cross_rim"), (0.0, 0.0, 0.0), 0.45, center_matrix)
            draw_shape(get(self, "fbp_cross"), color, 0.9, center_matrix)
        if get(self, "fbp_near") and not modal:
            dot_rim, dot = get(self, "fbp_dot_rim"), get(self, "fbp_dot")
            for matrix in get(self, "fbp_marks"):
                draw_shape(dot_rim, (0.0, 0.0, 0.0), 0.5, matrix)
                draw_shape(dot, color, 1.0, matrix)
        knob = handle_selected_color(context)[:3] if (modal or get(self, "is_highlight")) else color
        draw_shape(get(self, "fbp_stem"), color, 0.8, world)
        draw_shape(get(self, "fbp_rim"), (0.0, 0.0, 0.0), 0.5, world)
        draw_shape(get(self, "fbp_disc"), knob, 1.0, world)

    def draw_select(self, context, select_id):
        del context
        self.draw_custom_shape(self.fbp_rim, select_id=select_id)
        self.draw_custom_shape(self.fbp_disc, select_id=select_id)

    def _rig(self):
        return bpy.data.objects.get(self.fbp_rig_name or "")

    def _screen_angle(self, context, event):
        import math
        from bpy_extras.view3d_utils import location_3d_to_region_2d

        center = location_3d_to_region_2d(context.region, context.region_data, Vector(self.fbp_center))
        if center is None:
            return None
        return math.atan2(event.mouse_region_y - center.y, event.mouse_region_x - center.x)

    def invoke(self, context, event):
        rig = self._rig()
        angle = self._screen_angle(context, event)
        if rig is None or angle is None:
            return {"CANCELLED"}
        self.fbp_initial = rig.matrix_world.copy()
        self.fbp_start_angle = angle
        return {"RUNNING_MODAL"}

    def modal(self, context, event, tweak):
        import math

        rig = self._rig()
        angle = self._screen_angle(context, event)
        if rig is None or angle is None or self.fbp_initial is None:
            return {"RUNNING_MODAL"}
        delta = angle - self.fbp_start_angle
        delta = math.atan2(math.sin(delta), math.cos(delta))
        if "SNAP" in tweak or event.ctrl:
            step = math.radians(15.0)
            delta = round(delta / step) * step
        initial = self.fbp_initial
        normal = (initial.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()
        view = context.region_data.view_matrix.inverted().to_3x3() @ Vector((0.0, 0.0, 1.0))
        # Counter-clockwise on screen, whichever side of the plane faces us.
        if normal.dot(view) < 0.0:
            delta = -delta
        center = Vector(self.fbp_center)
        turn = Matrix.Translation(center) @ Matrix.Rotation(delta, 4, normal) @ Matrix.Translation(-center)
        before = (rig.location.copy(), _rotation_copy(rig), rig.scale.copy())
        try:
            rig.matrix_world = turn @ initial
            _restore_locked(rig, before)
        except FBP_DATA_ERRORS:
            return {"RUNNING_MODAL"}
        context.area.header_text_set(f"Rotate Layer: {math.degrees(delta):.1f}\u00b0")
        context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def exit(self, context, cancel):
        rig = self._rig()
        try:
            context.area.header_text_set(None)
        except FBP_DATA_ERRORS:
            pass
        if rig is not None and self.fbp_initial is not None:
            if cancel:
                rig.matrix_world = self.fbp_initial
            else:
                _auto_key(rig)
                try:
                    bpy.ops.ed.undo_push(message="Rotate Layer")
                except RuntimeError:
                    pass
        self.fbp_initial = None
        context.area.tag_redraw()


class FBP_GGT_layer_cage(bpy.types.GizmoGroup):
    bl_idname = "FBP_GGT_layer_cage"
    bl_label = "Frame By Plane Layer Cage"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}

    @classmethod
    def poll(cls, context):
        try:
            if context.mode != "OBJECT":
                return False
            space = context.space_data
            if not space.overlay.show_overlays or not space.show_gizmo:
                return False
        except FBP_DATA_ERRORS:
            return False
        if not cage_enabled(context):
            return False
        return bool(_cage_layers(context))

    @classmethod
    def setup_keymap(cls, keyconfig):
        # Drag only: a plain click goes on to the selection operators.
        return keyconfig.keymaps.new(
            name="Generic Gizmo Maybe Drag", space_type="EMPTY", region_type="WINDOW",
        )

    def setup(self, context):
        self.bindings = {}
        self.draw_prepare(context)

    def _new_cage(self, binding):
        gizmo = self.gizmos.new("GIZMO_GT_cage_2d")
        gizmo.draw_style = "BOX_TRANSFORM"
        # Rotation has its own handle (FBP_GT_layer_rotate): the cage's
        # built-in one cannot be picked in a 3D gizmo group.
        gizmo.transform = {"TRANSLATE", "SCALE"}
        gizmo.draw_options = set()
        gizmo.dimensions = (1.0, 1.0)
        gizmo.use_draw_modal = True
        gizmo.use_draw_hover = False
        gizmo.use_undo = True
        gizmo.target_set_handler("matrix", get=binding.get, set=binding.set)
        return gizmo

    def _new_rotator(self, rig_name):
        gizmo = self.gizmos.new(FBP_GT_layer_rotate.bl_idname)
        gizmo.fbp_rig_name = rig_name
        return gizmo

    def _remove(self, gizmo):
        try:
            self.gizmos.remove(gizmo)
        except FBP_DATA_ERRORS:
            pass

    def draw_prepare(self, context):
        bindings = getattr(self, "bindings", None)
        if bindings is None:
            bindings = self.bindings = {}
        layers = _cage_layers(context)
        try:
            depsgraph = context.evaluated_depsgraph_get()
        except FBP_DATA_ERRORS:
            depsgraph = None
        names = {rig.name for rig in layers}
        for name, (_binding, cage, rotator) in tuple(bindings.items()):
            if name not in names and not cage.is_modal and not rotator.is_modal:
                del bindings[name]
                self._remove(cage)
                self._remove(rotator)
        active = getattr(context, "active_object", None)
        with_handles = _rigs_with_handles(context) if layers else set()
        region = getattr(context, "region", None)
        region_data = getattr(context, "region_data", None)
        for rig in layers:
            entry = bindings.get(rig.name)
            if entry is None:
                binding = _CageBinding(rig.name)
                # Created first so it draws last: Blender draws a group's
                # gizmos in reverse order, and the squares go over the lines.
                rotator = self._new_rotator(rig.name)
                entry = bindings[rig.name] = (binding, self._new_cage(binding), rotator)
            binding, cage, rotator = entry
            if _RNA_GET(cage, "is_modal") or _RNA_GET(rotator, "is_modal"):
                continue
            rect = layer_cage_rect(rig, depsgraph)
            if rect is None:
                _RNA_SET(cage, "hide", True)
                _RNA_SET(rotator, "hide", True)
                continue
            center, size = rect
            binding.refresh(rig, center, size)
            _RNA_SET(cage, "matrix_basis", binding.basis)
            _RNA_SET(cage, "matrix_offset", _unflatten(binding.get()))
            try:
                plane = rig.fbp_plane_target
                draw_only = (
                    (plane is not None and plane.as_pointer() in with_handles)
                    or _shows_lattice_handles(rig)
                    or _shows_color_plane_gradient(context, rig)
                )
            except FBP_DATA_ERRORS:
                draw_only = False
            # Effect handles (Crop, Gradient, Lattice Corner Pin and Grid...)
            # take over: they sit on the same edges and draw their own frame.
            _RNA_SET(cage, "hide", bool(draw_only))
            # Thin white lines as in Grease Pencil; other selected layers
            # are a dimmer grey so the active one stands out.
            color = _ACTIVE_COLOR if rig == active else _SELECTED_COLOR
            style = (tuple(color), 0.9 if rig == active else 0.6)
            if binding.style != style:
                # Gizmo property writes are slow; the style changes only when
                # the active layer does.
                cage.color = style[0]
                cage.alpha = style[1]
                cage.color_highlight = (1.0, 1.0, 1.0)
                cage.alpha_highlight = 1.0
                cage.line_width = 1.0
                binding.style = style
            self._place_rotator(rotator, rig, center, size, region, region_data, draw_only, color)

    @staticmethod
    def _place_rotator(rotator, rig, center, size, region, region_data, draw_only, color):
        from bpy_extras.view3d_utils import location_3d_to_region_2d

        if draw_only or region is None or region_data is None:
            _RNA_SET(rotator, "hide", True)
            return
        try:
            world = rig.matrix_world
            rotation = world.to_quaternion().to_matrix().to_4x4()
            up = (world.to_3x3() @ Vector((0.0, 1.0, 0.0))).normalized()
            top = world @ Vector((center.x, center.y + size.y * 0.5, center.z))
            per_unit = _pixels_per_unit(region, region_data, top, up)
            if per_unit is None:
                _RNA_SET(rotator, "hide", True)
                return
            unit = 1.0 / per_unit
            location = top + up * (_ROTATE_OFFSET_PX * unit)
            basis = Matrix.Translation(location) @ rotation @ Matrix.Scale(unit, 4)
            middle = world @ center
            middle_scale = _pixels_per_unit(region, region_data, middle, up)
            center_matrix = (
                Matrix.Translation(middle) @ rotation @ Matrix.Scale(1.0 / middle_scale, 4)
                if middle_scale else None
            )
            points = []
            screen = []
            hx, hy = size.x * 0.5, size.y * 0.5
            for dx, dy in ((-1, -1), (0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0)):
                point = world @ Vector((center.x + dx * hx, center.y + dy * hy, center.z))
                points.append(point)
                screen.append(location_3d_to_region_2d(region, region_data, point))
            screen.append(location_3d_to_region_2d(region, region_data, location))
            near = proximity_near(("cage", rig.name), region, screen)
            marks = []
            if near:
                # The dots only show while the cursor is near the box.
                for point in points:
                    scale = _pixels_per_unit(region, region_data, point, up)
                    if scale is not None:
                        marks.append(Matrix.Translation(point) @ rotation @ Matrix.Scale(1.0 / scale, 4))
            _RNA_SET(rotator, "matrix_basis", basis)
            _RNA_SET(rotator, "fbp_center", tuple(middle))
            _RNA_SET(rotator, "fbp_center_matrix", center_matrix)
            _RNA_SET(rotator, "fbp_near", near)
            _RNA_SET(rotator, "fbp_marks", tuple(marks))
            _RNA_SET(rotator, "fbp_color", tuple(color)[:3])
            _RNA_SET(rotator, "hide", False)
        except FBP_DATA_ERRORS:
            _RNA_SET(rotator, "hide", True)
            return


_CLASSES = (FBP_GT_cursor_probe, FBP_GGT_cursor_probe, FBP_GT_layer_rotate, FBP_GGT_layer_cage)


def register():
    if bpy.app.background:
        return
    for cls in _CLASSES:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass


def unregister():
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except (ValueError, RuntimeError):
            pass
