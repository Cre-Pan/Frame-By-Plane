"""Plane group controller: move, rotate, scale and fade a whole plane group.

A plane group (see ``plane_groups``) is a collection, and Blender cannot
keyframe a collection. The controller is an Empty in the group that its
layers are parented to, keeping where they are:

* moving, rotating or scaling the controller moves the whole group, and its
  keyframes show in the Dope Sheet and Graph Editor like any object's;
* its **Group Opacity** (``fbp_group_opacity``, keyable) multiplies the
  Opacity of every layer in the group, through drivers on their materials,
  so it plays back and renders without Python;
* a click on a plane of the group selects the controller, so G, R, S and I
  act on the group as one object.

Nested groups: a child group with its own controller is parented as a unit
(its controller), otherwise its layers are parented directly. Removing the
controller puts every layer back under the controller's own parent, still
where it was.
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, FloatProperty, PointerProperty, StringProperty
from bpy.types import Operator
from mathutils import Matrix, Vector

from .runtime import FBP_DATA_ERRORS, fbp_warn
from .registration import register_interactive_classes, unregister_classes


CONTROLLER_SUFFIX = " Controller"


# -- Lookup -----------------------------------------------------------------

def is_group_controller(obj) -> bool:
    try:
        return obj is not None and bool(getattr(obj, "fbp_is_group_controller", False))
    except FBP_DATA_ERRORS:
        return False


def group_controller(collection):
    """The controller of ``collection``, or ``None``."""
    if collection is None:
        return None
    try:
        controller = getattr(collection, "fbp_group_controller", None)
    except FBP_DATA_ERRORS:
        return None
    if not is_group_controller(controller):
        return None
    try:
        if controller.name not in collection.objects:
            return None
    except FBP_DATA_ERRORS:
        return None
    return controller


def controlled_group(controller, scene=None):
    """The plane group ``controller`` belongs to, or ``None``."""
    if not is_group_controller(controller):
        return None
    for collection in tuple(getattr(controller, "users_collection", ()) or ()):
        if group_controller(collection) == controller:
            return collection
    return None


def _is_layer(obj) -> bool:
    try:
        return bool(getattr(obj, "is_fbp_control", False)) and getattr(obj, "fbp_plane_target", None) is not None
    except FBP_DATA_ERRORS:
        return False


def controlled_members(collection):
    """Objects the controller of ``collection`` parents: its layers, and for
    each child collection its controller or, without one, its members."""
    members = []
    seen = set()

    def visit(current):
        try:
            key = int(current.as_pointer())
        except FBP_DATA_ERRORS:
            return
        if key in seen:
            return
        seen.add(key)
        for obj in tuple(getattr(current, "objects", ()) or ()):
            if _is_layer(obj) and obj not in members:
                members.append(obj)
        for child in tuple(getattr(current, "children", ()) or ()):
            child_controller = group_controller(child)
            if child_controller is not None:
                if child_controller not in members:
                    members.append(child_controller)
            else:
                visit(child)

    visit(collection)
    return members


def _group_layers(collection, scene=None):
    try:
        from .plane_groups import group_rigs
        return group_rigs(collection, scene)
    except ImportError:
        return []


def _refresh_layer_opacity(rigs):
    """Rebind each layer's Opacity drivers (group factor added or removed)."""
    try:
        from .materials import do_update_opacity
    except ImportError:
        return
    for rig in rigs:
        try:
            do_update_opacity(rig)
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not refresh the layer opacity for the group controller", exc)


def _tag_viewports():
    window_manager = getattr(bpy.context, "window_manager", None)
    for window in tuple(getattr(window_manager, "windows", ()) or ()):
        for area in tuple(getattr(getattr(window, "screen", None), "areas", ()) or ()):
            if area.type in {"VIEW_3D", "PROPERTIES", "DOPESHEET_EDITOR", "GRAPH_EDITOR"}:
                area.tag_redraw()


def _group_opacity_update(self, _context):
    # Layer materials read the value through drivers: only redraw.
    _tag_viewports()


# -- Parenting --------------------------------------------------------------

def _set_parent_keep_world(obj, parent):
    """Parent ``obj`` to ``parent`` (or clear it) without moving it.

    With a parent, only the parent inverse changes: the layer's own Location,
    Rotation and Scale (and their keyframes) keep their values. Without one
    Blender has no parent inverse, so the world matrix is written back."""
    world = obj.matrix_world.copy()
    basis = obj.matrix_basis.copy()
    obj.parent = parent
    if parent is not None:
        obj.matrix_parent_inverse = parent.matrix_world.inverted_safe() @ world @ basis.inverted_safe()
    else:
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj.matrix_world = world


def create_group_controller(context, collection):
    """Add a controller to ``collection``; returns ``(controller, skipped)``.

    ``skipped`` lists layers left alone because their parent is outside the
    group and differs from the other layers' parent."""
    scene = context.scene
    members = controlled_members(collection)
    if not members:
        return None, []
    outside = {}
    for member in members:
        parent = member.parent
        key = parent.name if parent is not None else ""
        outside.setdefault(key, []).append(member)
    if len(outside) == 1:
        common_name = next(iter(outside))
    else:
        # Different parents: follow the most common one (the camera of a
        # Multiplane setup, usually); the others stay as they are.
        common_name = max(outside, key=lambda name: (len(outside[name]), name == ""))
    common = bpy.data.objects.get(common_name) if common_name else None
    adopted = outside[common_name]
    skipped = [member for name, items in outside.items() if name != common_name for member in items]

    center = Vector((0.0, 0.0, 0.0))
    for member in adopted:
        center += member.matrix_world.translation
    center /= max(1, len(adopted))

    controller = bpy.data.objects.new(f"{collection.name}{CONTROLLER_SUFFIX}", None)
    controller.empty_display_type = 'PLAIN_AXES'
    controller.empty_display_size = 0.35
    controller.fbp_is_group_controller = True
    controller.show_in_front = True
    collection.objects.link(controller)
    if common is not None:
        controller.parent = common
        controller.matrix_parent_inverse = common.matrix_world.inverted_safe()
    controller.matrix_world = Matrix.Translation(center)
    context.view_layer.update()
    for member in adopted:
        _set_parent_keep_world(member, controller)
    collection.fbp_group_controller = controller
    context.view_layer.update()
    _refresh_layer_opacity(_group_layers(collection, scene))
    return controller, skipped


def remove_group_controller(context, collection):
    """Remove the controller of ``collection``; its layers stay in place."""
    controller = group_controller(collection)
    if controller is None:
        return False
    parent = controller.parent
    for child in tuple(controller.children):
        _set_parent_keep_world(child, parent)
    rigs = _group_layers(collection, context.scene)
    collection.fbp_group_controller = None
    try:
        bpy.data.objects.remove(controller, do_unlink=True)
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not delete the group controller", exc)
    context.view_layer.update()
    _refresh_layer_opacity(rigs)
    return True


# -- Target group ------------------------------------------------------------

def _active_layer(context):
    obj = getattr(context, "active_object", None)
    if obj is None:
        return None
    if _is_layer(obj) or is_group_controller(obj):
        return obj
    for candidate in tuple(getattr(context, "selected_objects", ()) or ()):
        if _is_layer(candidate) and getattr(candidate, "fbp_plane_target", None) == obj:
            return candidate
    try:
        from .layer_transform_panel import layer_rig_for_plane
        return layer_rig_for_plane(obj)
    except ImportError:
        return None


def target_group(context, name=""):
    """The plane group an operator acts on: ``name``, the group of the
    selected controller, the entered group, or the selected layer's group."""
    try:
        from .plane_groups import entered_group, group_chain, is_plane_group, selection_group
    except ImportError:
        return None
    if name:
        collection = bpy.data.collections.get(name)
        return collection if is_plane_group(collection) else None
    scene = context.scene
    active = _active_layer(context)
    if is_group_controller(active):
        return controlled_group(active, scene)
    if active is not None:
        group = selection_group(active, scene)
        if group is not None:
            return group
        chain = group_chain(active, scene)
        if chain:
            return chain[-1]
    return entered_group(scene)


# -- Operators ----------------------------------------------------------------

class FBP_OT_AddGroupController(Operator):
    bl_idname = "fbp.add_group_controller"
    bl_label = "Add Group Controller"
    bl_description = (
        "Add an Empty that moves, rotates, scales and fades the whole plane group. "
        "Its transform and Group Opacity can be keyframed"
    )
    bl_options = {'REGISTER', 'UNDO'}

    group_name: StringProperty(name="Group", default="", options={'SKIP_SAVE', 'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return getattr(context, "mode", "OBJECT") == 'OBJECT' and getattr(context, "scene", None) is not None

    def execute(self, context):
        collection = target_group(context, self.group_name)
        if collection is None:
            self.report({'WARNING'}, "Select a plane group first (Ctrl+G makes one)")
            return {'CANCELLED'}
        existing = group_controller(collection)
        if existing is not None:
            self.report({'INFO'}, f"{collection.name} already has a controller: {existing.name}")
            return {'CANCELLED'}
        controller, skipped = create_group_controller(context, collection)
        if controller is None:
            self.report({'WARNING'}, f"{collection.name} has no layers to control")
            return {'CANCELLED'}
        for obj in tuple(getattr(context, "selected_objects", ()) or ()):
            obj.select_set(False)
        controller.select_set(True)
        context.view_layer.objects.active = controller
        if skipped:
            self.report(
                {'WARNING'},
                f"Added {controller.name}; {len(skipped)} layer(s) keep their own parent and do not follow it",
            )
        else:
            self.report({'INFO'}, f"Added {controller.name}")
        return {'FINISHED'}


class FBP_OT_RemoveGroupController(Operator):
    bl_idname = "fbp.remove_group_controller"
    bl_label = "Remove Group Controller"
    bl_description = "Delete the group controller. Every layer stays where it is now"
    bl_options = {'REGISTER', 'UNDO'}

    group_name: StringProperty(name="Group", default="", options={'SKIP_SAVE', 'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return getattr(context, "mode", "OBJECT") == 'OBJECT' and getattr(context, "scene", None) is not None

    def execute(self, context):
        collection = target_group(context, self.group_name)
        if collection is None or not remove_group_controller(context, collection):
            self.report({'INFO'}, "This group has no controller")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Removed the controller of {collection.name}")
        return {'FINISHED'}


def dissolve_plane_group(context, collection):
    """Ungroup: every layer and child collection moves to the group's parent
    collection, still where it is, and the empty group is deleted."""
    scene = context.scene
    try:
        from .operator_common import _fbp_refresh_layer_tree
        from .operator_layers import _fbp_canonical_collection_parent, _fbp_move_stack_object_to_collection
    except ImportError:
        return 0
    remove_group_controller(context, collection)
    parent = _fbp_canonical_collection_parent(scene, collection) or scene.collection
    moved = 0
    for obj in tuple(collection.objects):
        if _is_layer(obj):
            if _fbp_move_stack_object_to_collection(scene, obj, parent, 'PLANES'):
                moved += 1
            continue
        try:
            if obj.name not in parent.objects:
                parent.objects.link(obj)
            collection.objects.unlink(obj)
        except FBP_DATA_ERRORS:
            continue
    for child in tuple(collection.children):
        try:
            if child.name not in parent.children:
                parent.children.link(child)
            collection.children.unlink(child)
        except FBP_DATA_ERRORS:
            continue
    if not collection.objects and not collection.children:
        try:
            bpy.data.collections.remove(collection)
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not delete the empty plane group", exc)
    _fbp_refresh_layer_tree(context)
    return moved


class FBP_OT_DissolvePlaneGroup(Operator):
    bl_idname = "fbp.dissolve_plane_group"
    bl_label = "Ungroup"
    bl_description = (
        "Dissolve the selected plane group: its layers move to the parent collection, "
        "nothing moves in the viewport, and the empty group is deleted"
    )
    bl_options = {'REGISTER', 'UNDO'}

    group_name: StringProperty(name="Group", default="", options={'SKIP_SAVE', 'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return getattr(context, "mode", "OBJECT") == 'OBJECT' and getattr(context, "scene", None) is not None

    def execute(self, context):
        collection = target_group(context, self.group_name)
        if collection is None:
            self.report({'INFO'}, "Select a plane group first")
            return {'CANCELLED'}
        name = collection.name
        moved = dissolve_plane_group(context, collection)
        self.report({'INFO'}, f"Ungrouped {name}: {moved} layer(s) moved out")
        return {'FINISHED'}


def whole_group_selected(context):
    """The plane group selected as a whole (its controller, or all of its
    layers and nothing else of it), or ``None``."""
    try:
        from .plane_groups import group_rigs, group_selected
    except ImportError:
        return None
    scene = context.scene
    active = _active_layer(context)
    if is_group_controller(active):
        return controlled_group(active, scene) if active.select_get() else None
    group = target_group(context)
    if group is None or not group_selected(group, scene):
        return None
    selected = {obj for obj in tuple(getattr(context, "selected_objects", ()) or ()) if _is_layer(obj)}
    return group if selected <= set(group_rigs(group, scene)) else None


def draw_group_controller(layout, collection):
    """Controller row for a plane group (Layer List, sidebar)."""
    controller = group_controller(collection)
    if controller is None:
        op = layout.operator("fbp.add_group_controller", text="Add Group Controller", icon='EMPTY_AXIS')
        op.group_name = collection.name
    else:
        row = layout.row(align=True)
        row.prop(controller, "fbp_group_opacity", text="Group Opacity", slider=True)
        op = row.operator("fbp.remove_group_controller", text="", icon='X')
        op.group_name = collection.name
    op = layout.operator("fbp.dissolve_plane_group", text="Ungroup", icon='UNLINKED')
    op.group_name = collection.name


_CLASSES = (FBP_OT_AddGroupController, FBP_OT_RemoveGroupController, FBP_OT_DissolvePlaneGroup)


def register():
    bpy.types.Object.fbp_is_group_controller = BoolProperty(
        name="Group Controller",
        description="Internal: this Empty moves and fades a Frame By Plane plane group",
        default=False,
        options={'HIDDEN'},
    )
    bpy.types.Object.fbp_group_opacity = FloatProperty(
        name="Group Opacity",
        description=(
            "Opacity of the whole plane group, multiplied with each layer's own Opacity. "
            "Keyframe it with I or the dot next to the slider"
        ),
        default=1.0,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
        options={'ANIMATABLE'},
        update=_group_opacity_update,
    )
    bpy.types.Collection.fbp_group_controller = PointerProperty(
        name="Group Controller",
        description="Empty that moves and fades this plane group",
        type=bpy.types.Object,
    )
    register_interactive_classes(_CLASSES)


def unregister():
    unregister_classes(_CLASSES)
    for owner, name in (
        (bpy.types.Collection, "fbp_group_controller"),
        (bpy.types.Object, "fbp_group_opacity"),
        (bpy.types.Object, "fbp_is_group_controller"),
    ):
        try:
            delattr(owner, name)
        except (AttributeError, RuntimeError):
            pass
