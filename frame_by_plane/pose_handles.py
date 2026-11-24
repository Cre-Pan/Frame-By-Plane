"""Drag effect handles while a layer is in Pose Mode.

Ctrl+T puts a layer in Pose Mode on its Controls armature, where the Lattice
handles are bones. Effect handles (Crop, Extend, Gradient, Shape Mask...) are
separate mesh objects, and Blender's Pose Mode tools only move bones, so this
gizmo takes a drag that starts on one of the posed layer's handles and moves
the handle in its plane, as Blender's G does in Object Mode. The armature stays
in Pose Mode, so bones and effect handles can be edited together.

Gradient ends and lines are left to the gradient gizmos, which work in Pose
Mode too.
"""

from __future__ import annotations

import math

import bpy
from mathutils import Matrix, Vector

from .runtime import FBP_DATA_ERRORS
from .common import (
    view_plane_hit as _plane_hit,
    ui_scale as _ui_scale,
    undo_push as _undo_push,
)


_CLICK_PX = 4.0
_PICK_PX = 4.0
_GRADIENT_LINE_EFFECTS = ("GRADIENT_LIGHT", "GRADIENT_MASK", "TILT_SHIFT")


def _posed_rigs(context):
    try:
        from .lattice_bones import posed_layer_rigs
        return posed_layer_rigs(context)
    except (ImportError, *FBP_DATA_ERRORS):
        return []


def _owned_by_gradient_gizmos(handle):
    """Gradient ends and base lines have their own drag (handle_overlay)."""
    try:
        from .effect_controls import KEY_EFFECT_ID, KEY_MODE, KEY_ROLE
        effect_id = str(handle.get(KEY_EFFECT_ID, "") or "").upper()
        if effect_id not in _GRADIENT_LINE_EFFECTS:
            return False
        role = str(handle.get(KEY_ROLE, "") or "").upper()
        mode = str(handle.get(KEY_MODE, "") or "").upper()
        return role in {"IN", "OUT"} or mode == "RANGE_CENTER"
    except (ImportError, *FBP_DATA_ERRORS):
        return False


def _handle_layer(handle):
    """The layer rig a viewport handle belongs to, or None."""
    try:
        from .effect_controls import effect_control_owner, is_effect_control
        if is_effect_control(handle):
            return effect_control_owner(handle)
    except (ImportError, *FBP_DATA_ERRORS):
        return None
    try:
        from .layers import fbp_resolve_rig_from_any_object
        return fbp_resolve_rig_from_any_object(handle, bpy.context)
    except (ImportError, *FBP_DATA_ERRORS):
        return None


def posed_handle_under_cursor(context, coord):
    """The posed layer's handle under ``coord`` that this gizmo drags, or None."""
    rigs = _posed_rigs(context)
    if not rigs:
        return None
    try:
        from .alpha_pick import fbp_handle_under_cursor
        handle = fbp_handle_under_cursor(context, coord, _PICK_PX * _ui_scale(context))
    except (ImportError, *FBP_DATA_ERRORS, ValueError):
        return None
    if handle is None or _owned_by_gradient_gizmos(handle):
        return None
    return handle if _handle_layer(handle) in rigs else None


def _clamped(handle, target):
    """``target`` held inside the handle's own Limit Location constraints.

    Blender's G respects them ("Affect Transform"); setting the location
    directly does not, so Crop and Extend bars would leave the image.
    """
    try:
        constraints = tuple(handle.constraints)
    except FBP_DATA_ERRORS:
        return target
    for constraint in constraints:
        try:
            if (
                constraint.type != "LIMIT_LOCATION" or constraint.mute
                or not bool(getattr(constraint, "use_transform_limit", False))
                or str(constraint.owner_space) != "LOCAL"
            ):
                continue
            for axis, name in ((0, "x"), (1, "y")):
                if getattr(constraint, f"use_min_{name}"):
                    target[axis] = max(target[axis], float(getattr(constraint, f"min_{name}")))
                if getattr(constraint, f"use_max_{name}"):
                    target[axis] = min(target[axis], float(getattr(constraint, f"max_{name}")))
        except FBP_DATA_ERRORS:
            continue
    return target


def _sync_handle(handle):
    """Push the handle's new place into its effect right away."""
    try:
        from .effect_controls import is_effect_control, sync_properties_from_control
        if is_effect_control(handle):
            sync_properties_from_control(handle)
    except (ImportError, *FBP_DATA_ERRORS):
        pass


class FBP_GT_pose_handle(bpy.types.Gizmo):
    """Invisible grip over the posed layer's effect handles (the overlay draws them)."""

    bl_idname = "FBP_GT_pose_handle"
    __slots__ = (
        "fbp_hover", "fbp_handle", "fbp_initial", "fbp_press", "fbp_moved",
        "fbp_hit", "fbp_normal", "fbp_space", "fbp_rotate",
    )

    def setup(self):
        self.fbp_hover = ""
        self.fbp_handle = ""
        self.fbp_initial = None
        self.fbp_press = None
        self.fbp_moved = False
        self.use_draw_hover = False

    def draw(self, context):
        del context

    def test_select(self, context, location):
        handle = posed_handle_under_cursor(context, location)
        name = str(handle.name) if handle is not None else ""
        bpy.types.bpy_struct.__setattr__(self, "fbp_hover", name)
        if not name:
            return -1
        try:
            from .layer_cage import set_hovered_handle
            set_hovered_handle(context, name)
        except ImportError:
            pass
        return 0

    def _handle(self):
        return bpy.data.objects.get(self.fbp_handle or "")

    def invoke(self, context, event):
        handle = bpy.data.objects.get(self.fbp_hover or "")
        if handle is None:
            return {"CANCELLED"}
        self.fbp_handle = handle.name
        self.fbp_press = (event.mouse_region_x, event.mouse_region_y)
        self.fbp_moved = False
        normal = handle.matrix_world.col[2].xyz
        if normal.length <= 1.0e-9:
            return {"CANCELLED"}
        normal = normal.normalized()
        self.fbp_normal = tuple(normal)
        origin = handle.matrix_world.translation.copy()
        hit = _plane_hit(context.region, context.region_data, self.fbp_press, origin, normal)
        if hit is None:
            return {"CANCELLED"}
        self.fbp_hit = tuple(hit)
        # The handle's location lives in the space its parent (and Child Of)
        # give it: world = space @ basis.
        space = handle.matrix_world @ handle.matrix_basis.inverted_safe()
        self.fbp_space = [tuple(row) for row in space.inverted_safe()]
        self.fbp_initial = (tuple(handle.location), tuple(handle.rotation_euler))
        # A handle that cannot move in its plane but can turn (angle dials,
        # wind arrows) turns around its origin instead.
        locks = tuple(bool(value) for value in handle.lock_location)
        self.fbp_rotate = bool(locks[0] and locks[1] and not bool(handle.lock_rotation[2]))
        return {"RUNNING_MODAL"}

    def modal(self, context, event, tweak):
        handle = self._handle()
        if handle is None or self.fbp_initial is None:
            return {"RUNNING_MODAL"}
        if not self.fbp_moved:
            dx = event.mouse_region_x - self.fbp_press[0]
            dy = event.mouse_region_y - self.fbp_press[1]
            if dx * dx + dy * dy < _CLICK_PX * _CLICK_PX:
                return {"RUNNING_MODAL"}
            self.fbp_moved = True
        normal = Vector(self.fbp_normal)
        hit = _plane_hit(
            context.region, context.region_data, (event.mouse_region_x, event.mouse_region_y),
            Vector(self.fbp_hit), normal,
        )
        if hit is None:
            return {"RUNNING_MODAL"}
        to_local = Matrix(self.fbp_space)
        location, rotation = Vector(self.fbp_initial[0]), Vector(self.fbp_initial[1])
        try:
            if self.fbp_rotate:
                pivot = to_local @ handle.matrix_world.translation
                start = to_local @ Vector(self.fbp_hit) - pivot
                end = to_local @ hit - pivot
                if start.xy.length <= 1.0e-9 or end.xy.length <= 1.0e-9:
                    return {"RUNNING_MODAL"}
                delta = math.atan2(end.y, end.x) - math.atan2(start.y, start.x)
                if "SNAP" in tweak or event.ctrl:
                    step = math.radians(15.0)
                    delta = round(delta / step) * step
                rotation.z += delta
                handle.rotation_euler.z = rotation.z
                context.area.header_text_set(f"Rotate Handle: {math.degrees(delta):.1f}°   Ctrl: 15° steps")
            else:
                delta = to_local.to_3x3() @ (hit - Vector(self.fbp_hit))
                target = location.copy()
                for axis in (0, 1):
                    if not bool(handle.lock_location[axis]):
                        target[axis] += delta[axis]
                target = _clamped(handle, target)
                if (Vector(handle.location) - target).length > 1.0e-7:
                    handle.location = target
                context.area.header_text_set("Move Handle")
        except FBP_DATA_ERRORS:
            return {"RUNNING_MODAL"}
        _sync_handle(handle)
        context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def exit(self, context, cancel):
        handle = self._handle()
        try:
            context.area.header_text_set(None)
        except FBP_DATA_ERRORS:
            pass
        initial, self.fbp_initial = self.fbp_initial, None
        if handle is not None and initial is not None:
            try:
                if cancel:
                    handle.location = initial[0]
                    handle.rotation_euler = initial[1]
                    _sync_handle(handle)
                elif self.fbp_moved:
                    _undo_push("Rotate Handle" if self.fbp_rotate else "Move Handle")
            except FBP_DATA_ERRORS:
                pass
        self.fbp_handle = ""
        self.fbp_moved = False
        try:
            context.area.tag_redraw()
        except FBP_DATA_ERRORS:
            pass


class FBP_GGT_pose_handles(bpy.types.GizmoGroup):
    bl_idname = "FBP_GGT_pose_handles"
    bl_label = "Frame By Plane Pose Mode Handles"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}

    @classmethod
    def poll(cls, context):
        try:
            if context.mode != "POSE":
                return False
            space = context.space_data
            if not space.overlay.show_overlays or not space.show_gizmo:
                return False
        except FBP_DATA_ERRORS:
            return False
        return bool(_posed_rigs(context))

    @classmethod
    def setup_keymap(cls, keyconfig):
        # Drag only: a plain click still selects bones.
        return keyconfig.keymaps.new(
            name="Generic Gizmo Maybe Drag", space_type="EMPTY", region_type="WINDOW",
        )

    def setup(self, context):
        del context
        self.gizmos.new(FBP_GT_pose_handle.bl_idname)


# --- Lattice handles seen edge-on --------------------------------------------
#
# Lattice handles are pose bones whose shapes lie flat on the drawing. On a
# layer seen edge-on (a front-facing layer in Top or Side view) Blender draws
# them as one line and its click picks almost at random, so the overlay draws
# them facing the view (handle_overlay) and this gizmo takes the click there:
# a click selects the handle (Shift adds or removes it), a drag moves it in the
# layer's plane, following the line the layer draws on screen. Handles that
# sit on the same spot of the line (a column of Grid points seen from above)
# cannot be told apart there, so they are selected and moved together.

_STACK_PX = 1.5


def _stacked_bones(context, armature, pose_bone):
    """Handles of ``armature`` drawn on the same spot as ``pose_bone``."""
    from bpy_extras.view3d_utils import location_3d_to_region_2d
    region, view = context.region, context.region_data
    world = armature.matrix_world
    spot = location_3d_to_region_2d(region, view, world @ pose_bone.head)
    if spot is None:
        return [pose_bone]
    stack = [pose_bone]
    for other in armature.pose.bones:
        if other == pose_bone or other.custom_shape is None or other.bone.hide:
            continue
        point = location_3d_to_region_2d(region, view, world @ other.head)
        if point is not None and (point - spot).length <= _STACK_PX * _ui_scale(context):
            stack.append(other)
    return stack


def _edge_on_bone_under_cursor(context, coord):
    """``(armature, pose_bone)`` of the edge-on Lattice handle under ``coord``."""
    try:
        from .handle_overlay import LATTICE_HOVER_PREFIX, lattice_handle_under_cursor
        key = lattice_handle_under_cursor(
            context, coord, _PICK_PX * _ui_scale(context), posed_only=True,
        )
    except (ImportError, *FBP_DATA_ERRORS, ValueError):
        return None
    if not key:
        return None
    armature_name, _tab, bone_name = key[len(LATTICE_HOVER_PREFIX):].partition("\t")
    armature = bpy.data.objects.get(armature_name)
    try:
        pose_bone = armature.pose.bones.get(bone_name) if armature is not None else None
    except FBP_DATA_ERRORS:
        return None
    return (armature, pose_bone) if pose_bone is not None else None


def _any_posed_edge_on(context):
    """Any Lattice handles in Pose Mode: the overlay draws them all at one
    size on screen, so this gizmo picks and drags them in every view."""
    try:
        from .lattice_bones import is_bones_object
        for armature in tuple(getattr(context, "objects_in_mode", ()) or ()):
            if is_bones_object(armature):
                return True
    except (ImportError, *FBP_DATA_ERRORS):
        return False
    return False


class FBP_GT_pose_lattice_edge_on(bpy.types.Gizmo):
    """Invisible grip over the Lattice handles the overlay draws."""

    bl_idname = "FBP_GT_pose_lattice_edge_on"
    __slots__ = (
        "fbp_hover", "fbp_target", "fbp_press", "fbp_moved", "fbp_hit",
        "fbp_normal", "fbp_initial", "fbp_location", "fbp_stack",
    )

    def setup(self):
        self.fbp_hover = ("", "")
        self.fbp_target = ("", "")
        self.fbp_press = None
        self.fbp_moved = False
        self.fbp_initial = None
        self.fbp_stack = []
        self.use_draw_hover = False

    def draw(self, context):
        del context

    def test_select(self, context, location):
        found = _edge_on_bone_under_cursor(context, location)
        if found is None:
            bpy.types.bpy_struct.__setattr__(self, "fbp_hover", ("", ""))
            return -1
        armature, pose_bone = found
        bpy.types.bpy_struct.__setattr__(self, "fbp_hover", (armature.name, pose_bone.name))
        try:
            from .handle_overlay import LATTICE_HOVER_PREFIX
            from .layer_cage import set_hovered_handle
            set_hovered_handle(context, f"{LATTICE_HOVER_PREFIX}{armature.name}\t{pose_bone.name}")
        except ImportError:
            pass
        return 0

    def _target(self):
        armature = bpy.data.objects.get(self.fbp_target[0] or "")
        try:
            pose_bone = armature.pose.bones.get(self.fbp_target[1]) if armature is not None else None
        except FBP_DATA_ERRORS:
            return None, None
        return armature, pose_bone

    def _stack(self, armature):
        """``(pose_bone, initial matrix, initial location)`` of every moved handle."""
        items = []
        for name, matrix, location in self.fbp_stack or ():
            try:
                pose_bone = armature.pose.bones.get(name)
            except FBP_DATA_ERRORS:
                pose_bone = None
            if pose_bone is not None:
                items.append((pose_bone, Matrix(matrix), Vector(location)))
        return items

    def invoke(self, context, event):
        armature = bpy.data.objects.get(self.fbp_hover[0] or "")
        try:
            pose_bone = armature.pose.bones.get(self.fbp_hover[1]) if armature is not None else None
        except FBP_DATA_ERRORS:
            pose_bone = None
        if pose_bone is None:
            return {"CANCELLED"}
        self.fbp_target = (armature.name, pose_bone.name)
        self.fbp_press = (event.mouse_region_x, event.mouse_region_y)
        self.fbp_moved = False
        try:
            stack = _stacked_bones(context, armature, pose_bone)
            # Select as a click on the handle would, Shift adding or removing it.
            if event.shift:
                state = not bool(pose_bone.select)
                for item in stack:
                    item.select = state
            else:
                for other in armature.pose.bones:
                    other.select = other in stack
            if bool(pose_bone.select):
                armature.data.bones.active = pose_bone.bone
            self.fbp_stack = [
                (item.name, [tuple(row) for row in item.matrix], tuple(item.location))
                for item in stack
            ]
            world = armature.matrix_world
            normal = world.col[2].xyz
            if normal.length <= 1.0e-9:
                return {"CANCELLED"}
            normal = normal.normalized()
            head = world @ pose_bone.head
            hit = _plane_hit(context.region, context.region_data, self.fbp_press, head, normal)
            self.fbp_normal = tuple(normal)
            self.fbp_hit = tuple(hit) if hit is not None else None
            self.fbp_initial = [tuple(row) for row in pose_bone.matrix]
            self.fbp_location = tuple(pose_bone.location)
        except FBP_DATA_ERRORS:
            return {"CANCELLED"}
        context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def modal(self, context, event, tweak):
        del tweak
        armature, pose_bone = self._target()
        if pose_bone is None or self.fbp_initial is None or self.fbp_hit is None:
            return {"RUNNING_MODAL"}
        if not self.fbp_moved:
            dx = event.mouse_region_x - self.fbp_press[0]
            dy = event.mouse_region_y - self.fbp_press[1]
            if dx * dx + dy * dy < _CLICK_PX * _CLICK_PX:
                return {"RUNNING_MODAL"}
            self.fbp_moved = True
        hit = _plane_hit(
            context.region, context.region_data, (event.mouse_region_x, event.mouse_region_y),
            Vector(self.fbp_hit), Vector(self.fbp_normal),
        )
        if hit is None:
            return {"RUNNING_MODAL"}
        try:
            to_armature = armature.matrix_world.inverted_safe().to_3x3()
            offset = to_armature @ (hit - Vector(self.fbp_hit))
            for item, initial, location in self._stack(armature):
                matrix = initial.copy()
                matrix.translation = matrix.translation + offset
                item.matrix = matrix
                # Locked channels stay where they were, as with G.
                for axis in range(3):
                    if bool(item.lock_location[axis]):
                        item.location[axis] = location[axis]
            context.area.header_text_set("Move Handle")
        except FBP_DATA_ERRORS:
            return {"RUNNING_MODAL"}
        context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def exit(self, context, cancel):
        armature, pose_bone = self._target()
        try:
            context.area.header_text_set(None)
        except FBP_DATA_ERRORS:
            pass
        self.fbp_initial = None
        stack = self._stack(armature) if armature is not None else []
        if pose_bone is not None:
            try:
                if cancel and self.fbp_moved:
                    for item, _matrix, location in stack:
                        item.location = location
                elif self.fbp_moved:
                    for item, _matrix, _location in stack:
                        _autokey(context, item)
                    _undo_push("Move Handle")
                else:
                    _undo_push("Select")
            except FBP_DATA_ERRORS:
                pass
        self.fbp_target = ("", "")
        self.fbp_stack = []
        self.fbp_moved = False
        try:
            context.area.tag_redraw()
        except FBP_DATA_ERRORS:
            pass


def _autokey(context, pose_bone):
    """Key the moved handle when Auto Keying is on, as G does."""
    try:
        if not bool(context.scene.tool_settings.use_keyframe_insert_auto):
            return
        pose_bone.keyframe_insert("location", group=pose_bone.name)
    except FBP_DATA_ERRORS:
        pass


class FBP_GGT_pose_lattice_edge_on(bpy.types.GizmoGroup):
    bl_idname = "FBP_GGT_pose_lattice_edge_on"
    bl_label = "Frame By Plane Lattice Handles Seen Edge-On"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}

    @classmethod
    def poll(cls, context):
        try:
            if context.mode != "POSE":
                return False
            space = context.space_data
            if not space.overlay.show_overlays or not space.show_gizmo:
                return False
        except FBP_DATA_ERRORS:
            return False
        return _any_posed_edge_on(context)

    @classmethod
    def setup_keymap(cls, keyconfig):
        # Click too: Blender's own shapes are only specks at the points.
        return keyconfig.keymaps.new(
            name="Generic Gizmo", space_type="EMPTY", region_type="WINDOW",
        )

    def setup(self, context):
        del context
        self.gizmos.new(FBP_GT_pose_lattice_edge_on.bl_idname)


_CLASSES = (
    FBP_GT_pose_handle, FBP_GGT_pose_handles,
    FBP_GT_pose_lattice_edge_on, FBP_GGT_pose_lattice_edge_on,
)


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
