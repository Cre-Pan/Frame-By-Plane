"""Experimental, non-destructive Frame By Plane compositor integration.

Blender 5.x stores the active compositor as a reusable ``CompositorNodeTree``
assigned through ``Scene.compositing_node_group``. Frame By Plane therefore
creates its own clearly marked tree, remembers the previous scene tree and
never clears or deletes a compositor created by the user.
"""

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
)
from bpy.types import Operator

from .runtime import FBP_DATA_ERRORS, FBP_DATA_IO_ERRORS, fbp_warn


_FBP_COMP_OWNED_KEY = "fbp_compositor_owned"
_FBP_COMP_CONTRACT_KEY = "fbp_compositor_contract"
_FBP_COMP_CONTRACT = 1
_FBP_COMP_PREVIOUS_NAME_KEY = "fbp_compositor_previous_group_name"
_FBP_COMP_GROUP_NAME_KEY = "fbp_compositor_group_name"
_FBP_COMP_BATCH_KEY = "fbp_compositor_batch_update"

_NODE_RENDER = "FBP Render Layers"
_NODE_EXPOSURE = "FBP Exposure"
_NODE_GRADE = "FBP Hue Saturation Value"
_NODE_BLUR = "FBP Global Blur"
_NODE_GLARE = "FBP Bloom Glare"
_NODE_LENS = "FBP Lens Distortion"
_NODE_OUTPUT = "FBP Output"


FBP_COMPOSITOR_PRESET_ITEMS = (
    ('CLEAN', "Clean", "Neutral compositor settings with every optional pass disabled"),
    ('FILM', "Film", "Subtle desaturation, softened highlights and restrained lens character"),
    ('DREAM', "Dream", "Soft global blur with gentle bloom and slightly lifted exposure"),
    ('ANIME', "Anime Background", "Light saturation and value lift with restrained highlight bloom"),
    ('VHS', "VHS", "Mild horizontal softness, desaturation and chromatic dispersion"),
)


def _active_compositor_group(scene):
    try:
        return getattr(scene, "compositing_node_group", None)
    except FBP_DATA_ERRORS:
        return None


def fbp_is_owned_compositor(tree):
    """Return True only for compositor node trees created by Frame By Plane."""
    if tree is None:
        return False
    try:
        return bool(tree.get(_FBP_COMP_OWNED_KEY, False))
    except FBP_DATA_ERRORS:
        return False


def _node_tree_by_name(name):
    if not name:
        return None
    try:
        tree = bpy.data.node_groups.get(str(name))
        if tree is not None and getattr(tree, "bl_idname", "") == 'CompositorNodeTree':
            return tree
    except FBP_DATA_ERRORS:
        pass
    return None


def _owned_group_for_scene(scene, *, cache=True):
    try:
        tree = getattr(scene, "fbp_compositor_group", None)
        if fbp_is_owned_compositor(tree):
            return tree
    except FBP_DATA_ERRORS:
        pass

    tree = _active_compositor_group(scene)
    if fbp_is_owned_compositor(tree):
        return tree

    try:
        tree = _node_tree_by_name(scene.get(_FBP_COMP_GROUP_NAME_KEY, ""))
        if fbp_is_owned_compositor(tree):
            if cache:
                scene.fbp_compositor_group = tree
            return tree
    except FBP_DATA_ERRORS:
        pass
    return None


def _previous_group_for_scene(scene):
    try:
        tree = getattr(scene, "fbp_compositor_previous_group", None)
        if tree is not None and not fbp_is_owned_compositor(tree):
            return tree
    except FBP_DATA_ERRORS:
        pass
    try:
        tree = _node_tree_by_name(scene.get(_FBP_COMP_PREVIOUS_NAME_KEY, ""))
        if tree is not None and not fbp_is_owned_compositor(tree):
            scene.fbp_compositor_previous_group = tree
            return tree
    except FBP_DATA_ERRORS:
        pass
    return None


def fbp_scene_compositor_state(scene):
    """Return ``ACTIVE``, ``AVAILABLE`` or ``DISABLED`` for lightweight UI use."""
    active = _active_compositor_group(scene)
    if fbp_is_owned_compositor(active):
        return 'ACTIVE'
    return 'AVAILABLE' if _owned_group_for_scene(scene, cache=False) else 'DISABLED'


def _interface_clear(tree):
    interface = getattr(tree, "interface", None)
    if interface is None:
        raise RuntimeError("Compositor node-tree interface is unavailable")
    clear = getattr(interface, "clear", None)
    if callable(clear):
        clear()
        return
    for item in tuple(getattr(interface, "items_tree", ()) or ()):
        try:
            interface.remove(item)
        except FBP_DATA_ERRORS:
            continue


def _new_node(tree, node_type, name, location):
    try:
        node = tree.nodes.new(node_type)
    except FBP_DATA_ERRORS as exc:
        raise RuntimeError(f"Required compositor node is unavailable: {node_type}") from exc
    node.name = name
    node.label = name.removeprefix("FBP ")
    node.location = location
    return node


def _socket(sockets, *names, fallback=None):
    for name in names:
        try:
            value = sockets.get(name)
        except FBP_DATA_ERRORS:
            value = None
        if value is not None:
            return value
    if fallback is not None:
        try:
            return sockets[fallback]
        except FBP_DATA_ERRORS:
            pass
    return None


def _link_image(tree, source_node, target_node):
    output = _socket(source_node.outputs, "Image", fallback=0)
    input_socket = _socket(target_node.inputs, "Image", fallback=0)
    if output is None or input_socket is None:
        raise RuntimeError(
            f"Could not connect compositor nodes {source_node.name!r} and {target_node.name!r}"
        )
    tree.links.new(output, input_socket)


def _set_input(node, names, value, fallback=None):
    socket = _socket(node.inputs, *names, fallback=fallback)
    if socket is None:
        return False
    try:
        socket.default_value = value
        return True
    except FBP_DATA_ERRORS:
        return False


def _set_node_attr(node, name, value):
    if not hasattr(node, name):
        return False
    try:
        setattr(node, name, value)
        return True
    except FBP_DATA_ERRORS:
        return False


def _tree_contract_is_current(tree):
    if not fbp_is_owned_compositor(tree):
        return False
    try:
        if int(tree.get(_FBP_COMP_CONTRACT_KEY, 0) or 0) != _FBP_COMP_CONTRACT:
            return False
        return all(tree.nodes.get(name) is not None for name in (
            _NODE_RENDER,
            _NODE_EXPOSURE,
            _NODE_GRADE,
            _NODE_BLUR,
            _NODE_GLARE,
            _NODE_LENS,
            _NODE_OUTPUT,
        ))
    except FBP_DATA_ERRORS:
        return False


def _build_compositor_tree(tree, scene):
    """Build only inside an FBP-owned compositor tree."""
    if not fbp_is_owned_compositor(tree):
        raise RuntimeError("Refusing to rebuild a compositor not owned by Frame By Plane")

    tree.nodes.clear()
    _interface_clear(tree)
    tree.interface.new_socket(
        name="Image",
        in_out='OUTPUT',
        socket_type='NodeSocketColor',
    )

    render = _new_node(tree, "CompositorNodeRLayers", _NODE_RENDER, (-900, 80))
    if hasattr(render, "scene"):
        try:
            render.scene = scene
        except FBP_DATA_ERRORS:
            pass

    exposure = _new_node(tree, "CompositorNodeExposure", _NODE_EXPOSURE, (-680, 80))
    grade = _new_node(tree, "CompositorNodeHueSat", _NODE_GRADE, (-460, 80))
    blur = _new_node(tree, "CompositorNodeBlur", _NODE_BLUR, (-220, 80))
    glare = _new_node(tree, "CompositorNodeGlare", _NODE_GLARE, (20, 80))
    lens = _new_node(tree, "CompositorNodeLensdist", _NODE_LENS, (260, 80))
    output = _new_node(tree, "NodeGroupOutput", _NODE_OUTPUT, (510, 80))
    if hasattr(output, "is_active_output"):
        try:
            output.is_active_output = True
        except FBP_DATA_ERRORS:
            pass

    _set_node_attr(blur, "filter_type", 'GAUSS')
    _set_node_attr(glare, "glare_type", 'FOG_GLOW')
    _set_node_attr(glare, "quality", 'HIGH')

    _link_image(tree, render, exposure)
    _link_image(tree, exposure, grade)
    _link_image(tree, grade, blur)
    _link_image(tree, blur, glare)
    _link_image(tree, glare, lens)
    _link_image(tree, lens, output)

    tree[_FBP_COMP_OWNED_KEY] = True
    tree[_FBP_COMP_CONTRACT_KEY] = _FBP_COMP_CONTRACT
    tree["fbp_compositor_scene"] = str(getattr(scene, "name", "") or "")
    fbp_sync_compositor_settings(scene, tree=tree)
    return tree


def _new_compositor_tree(scene):
    base = f"FBP Compositor · {getattr(scene, 'name', 'Scene')}"
    tree = bpy.data.node_groups.new(name=base, type='CompositorNodeTree')
    tree[_FBP_COMP_OWNED_KEY] = True
    tree[_FBP_COMP_CONTRACT_KEY] = 0
    _build_compositor_tree(tree, scene)
    return tree


def fbp_sync_compositor_settings(scene, *, tree=None):
    """Update existing FBP nodes without rebuilding the compositor graph."""
    if scene is None:
        return False
    tree = tree or _owned_group_for_scene(scene)
    if not _tree_contract_is_current(tree):
        return False

    try:
        exposure = tree.nodes.get(_NODE_EXPOSURE)
        grade = tree.nodes.get(_NODE_GRADE)
        blur = tree.nodes.get(_NODE_BLUR)
        glare = tree.nodes.get(_NODE_GLARE)
        lens = tree.nodes.get(_NODE_LENS)

        exposure_value = float(scene.fbp_compositor_exposure)
        saturation = float(scene.fbp_compositor_saturation)
        value = float(scene.fbp_compositor_value)
        blur_x = max(0, int(scene.fbp_compositor_blur_x))
        blur_y = max(0, int(scene.fbp_compositor_blur_y))
        glare_enabled = bool(scene.fbp_compositor_glare_enabled)
        glare_threshold = float(scene.fbp_compositor_glare_threshold)
        glare_strength = float(scene.fbp_compositor_glare_strength)
        distortion = float(scene.fbp_compositor_lens_distortion)
        dispersion = float(scene.fbp_compositor_dispersion)

        _set_input(exposure, ("Exposure",), exposure_value, fallback=1)
        exposure.mute = abs(exposure_value) <= 1.0e-6

        _set_input(grade, ("Fac", "Factor"), 1.0, fallback=0)
        _set_input(grade, ("Hue",), 0.5, fallback=2)
        _set_input(grade, ("Saturation",), saturation, fallback=3)
        _set_input(grade, ("Value",), value, fallback=4)
        grade.mute = abs(saturation - 1.0) <= 1.0e-6 and abs(value - 1.0) <= 1.0e-6

        _set_node_attr(blur, "size_x", blur_x)
        _set_node_attr(blur, "size_y", blur_y)
        blur.mute = blur_x <= 0 and blur_y <= 0

        _set_node_attr(glare, "threshold", glare_threshold)
        _set_node_attr(glare, "mix", max(-1.0, min(0.0, -1.0 + glare_strength)))
        glare.mute = not glare_enabled or glare_strength <= 1.0e-6

        _set_input(lens, ("Distortion",), distortion, fallback=1)
        _set_input(lens, ("Dispersion",), dispersion, fallback=2)
        lens.mute = abs(distortion) <= 1.0e-6 and abs(dispersion) <= 1.0e-6
        return True
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not synchronize the Frame By Plane compositor", exc)
        return False


def _update_compositor_setting(scene, _context):
    try:
        if bool(scene.get(_FBP_COMP_BATCH_KEY, False)):
            return
    except FBP_DATA_ERRORS:
        pass
    fbp_sync_compositor_settings(scene)


def _store_previous_group(scene, tree):
    if fbp_is_owned_compositor(tree):
        return
    try:
        scene.fbp_compositor_previous_group = tree
        scene[_FBP_COMP_PREVIOUS_NAME_KEY] = str(getattr(tree, "name", "") or "")
    except FBP_DATA_ERRORS:
        pass


def _store_owned_group(scene, tree):
    try:
        scene.fbp_compositor_group = tree
        scene[_FBP_COMP_GROUP_NAME_KEY] = str(getattr(tree, "name", "") or "")
    except FBP_DATA_ERRORS:
        pass


def _assign_compositor(scene, tree):
    if not hasattr(scene, "compositing_node_group"):
        raise RuntimeError("Blender 5 compositor assignment API is unavailable")
    scene.compositing_node_group = tree


def _apply_preset(scene, preset):
    values = {
        'CLEAN': dict(exposure=0.0, saturation=1.0, value=1.0, blur_x=0, blur_y=0,
                      glare=False, threshold=1.0, strength=0.35, distortion=0.0, dispersion=0.0),
        'FILM': dict(exposure=-0.05, saturation=0.90, value=0.98, blur_x=0, blur_y=0,
                     glare=True, threshold=1.2, strength=0.16, distortion=0.008, dispersion=0.002),
        'DREAM': dict(exposure=0.20, saturation=0.92, value=1.04, blur_x=3, blur_y=3,
                      glare=True, threshold=0.75, strength=0.30, distortion=0.0, dispersion=0.0),
        'ANIME': dict(exposure=0.05, saturation=1.10, value=1.03, blur_x=0, blur_y=0,
                      glare=True, threshold=1.15, strength=0.12, distortion=0.0, dispersion=0.0),
        'VHS': dict(exposure=-0.08, saturation=0.82, value=0.96, blur_x=2, blur_y=0,
                    glare=False, threshold=1.0, strength=0.25, distortion=0.012, dispersion=0.018),
    }.get(str(preset or 'CLEAN').upper())
    if values is None:
        return False

    scene[_FBP_COMP_BATCH_KEY] = True
    try:
        scene.fbp_compositor_exposure = values['exposure']
        scene.fbp_compositor_saturation = values['saturation']
        scene.fbp_compositor_value = values['value']
        scene.fbp_compositor_blur_x = values['blur_x']
        scene.fbp_compositor_blur_y = values['blur_y']
        scene.fbp_compositor_glare_enabled = values['glare']
        scene.fbp_compositor_glare_threshold = values['threshold']
        scene.fbp_compositor_glare_strength = values['strength']
        scene.fbp_compositor_lens_distortion = values['distortion']
        scene.fbp_compositor_dispersion = values['dispersion']
    finally:
        try:
            del scene[_FBP_COMP_BATCH_KEY]
        except FBP_DATA_ERRORS:
            pass
    fbp_sync_compositor_settings(scene)
    return True


class FBP_OT_EnableCompositor(Operator):
    bl_idname = "fbp.enable_compositor"
    bl_label = "Enable FBP Compositor"
    bl_description = "Assign a dedicated Frame By Plane compositor while preserving the scene's current compositor for restoration"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        active = _active_compositor_group(scene)
        if fbp_is_owned_compositor(active):
            fbp_sync_compositor_settings(scene, tree=active)
            self.report({'INFO'}, "Frame By Plane Compositor is already active")
            return {'FINISHED'}

        _store_previous_group(scene, active)
        tree = _owned_group_for_scene(scene)
        try:
            if tree is None:
                tree = _new_compositor_tree(scene)
            elif not _tree_contract_is_current(tree):
                _build_compositor_tree(tree, scene)
            _store_owned_group(scene, tree)
            _assign_compositor(scene, tree)
            fbp_sync_compositor_settings(scene, tree=tree)
        except Exception as exc:
            fbp_warn("Could not enable the Frame By Plane compositor", exc)
            self.report({'ERROR'}, f"Could not enable compositor: {exc}")
            return {'CANCELLED'}

        self.report({'INFO'}, "Frame By Plane Compositor enabled; the previous compositor was preserved")
        return {'FINISHED'}


class FBP_OT_RestoreCompositor(Operator):
    bl_idname = "fbp.restore_compositor"
    bl_label = "Restore Previous Compositor"
    bl_description = "Restore the compositor that was active before Frame By Plane without deleting the FBP node tree"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        active = _active_compositor_group(scene)
        if not fbp_is_owned_compositor(active):
            self.report({'INFO'}, "The Frame By Plane Compositor is not active")
            return {'CANCELLED'}
        previous = _previous_group_for_scene(scene)
        try:
            _assign_compositor(scene, previous)
        except Exception as exc:
            fbp_warn("Could not restore the previous compositor", exc)
            self.report({'ERROR'}, f"Could not restore compositor: {exc}")
            return {'CANCELLED'}
        if previous is not None:
            self.report({'INFO'}, f"Restored compositor: {previous.name}")
        else:
            self.report({'INFO'}, "Frame By Plane Compositor disabled; the scene now has no compositor tree")
        return {'FINISHED'}


class FBP_OT_RebuildCompositor(Operator):
    bl_idname = "fbp.rebuild_compositor"
    bl_label = "Rebuild FBP Compositor"
    bl_description = "Recreate only the dedicated Frame By Plane compositor nodes; user compositor trees are never modified"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        tree = _owned_group_for_scene(scene)
        if tree is None:
            self.report({'WARNING'}, "Enable the Frame By Plane Compositor first")
            return {'CANCELLED'}
        try:
            _build_compositor_tree(tree, scene)
            _store_owned_group(scene, tree)
            if fbp_is_owned_compositor(_active_compositor_group(scene)):
                _assign_compositor(scene, tree)
        except Exception as exc:
            fbp_warn("Could not rebuild the Frame By Plane compositor", exc)
            self.report({'ERROR'}, f"Could not rebuild compositor: {exc}")
            return {'CANCELLED'}
        self.report({'INFO'}, "Frame By Plane Compositor rebuilt")
        return {'FINISHED'}


class FBP_OT_ApplyCompositorPreset(Operator):
    bl_idname = "fbp.apply_compositor_preset"
    bl_label = "Apply Compositor Preset"
    bl_description = "Apply the selected global compositor preset without rebuilding the node tree"
    bl_options = {'REGISTER', 'UNDO'}

    preset: EnumProperty(name="Preset", items=FBP_COMPOSITOR_PRESET_ITEMS, default='CLEAN')

    def execute(self, context):
        scene = context.scene
        if not _apply_preset(scene, self.preset):
            self.report({'ERROR'}, "Unknown compositor preset")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Applied compositor preset: {self.preset.replace('_', ' ').title()}")
        return {'FINISHED'}


_CLASSES = (
    FBP_OT_EnableCompositor,
    FBP_OT_RestoreCompositor,
    FBP_OT_RebuildCompositor,
    FBP_OT_ApplyCompositorPreset,
)


def _register_properties():
    bpy.types.Scene.fbp_compositor_group = PointerProperty(
        name="FBP Compositor Tree",
        description="Dedicated compositor node tree generated by Frame By Plane",
        type=bpy.types.NodeTree,
    )
    bpy.types.Scene.fbp_compositor_previous_group = PointerProperty(
        name="Previous Compositor Tree",
        description="Compositor tree that was active before enabling the Frame By Plane compositor",
        type=bpy.types.NodeTree,
    )
    bpy.types.Scene.fbp_compositor_preset = EnumProperty(
        name="Preset",
        description="Global Frame By Plane compositor preset",
        items=FBP_COMPOSITOR_PRESET_ITEMS,
        default='CLEAN',
    )
    bpy.types.Scene.fbp_compositor_exposure = FloatProperty(
        name="Exposure",
        description="Global exposure adjustment applied after the Render Layers source",
        default=0.0,
        min=-10.0,
        max=10.0,
        soft_min=-3.0,
        soft_max=3.0,
        update=_update_compositor_setting,
    )
    bpy.types.Scene.fbp_compositor_saturation = FloatProperty(
        name="Saturation",
        description="Global compositor saturation; 1.0 preserves the rendered colors",
        default=1.0,
        min=0.0,
        max=4.0,
        soft_max=2.0,
        update=_update_compositor_setting,
    )
    bpy.types.Scene.fbp_compositor_value = FloatProperty(
        name="Value",
        description="Global value multiplier; 1.0 preserves the rendered brightness",
        default=1.0,
        min=0.0,
        max=4.0,
        soft_max=2.0,
        update=_update_compositor_setting,
    )
    bpy.types.Scene.fbp_compositor_blur_x = IntProperty(
        name="Blur X",
        description="Horizontal Gaussian blur radius in output pixels; zero disables the horizontal blur",
        default=0,
        min=0,
        max=2048,
        soft_max=128,
        update=_update_compositor_setting,
    )
    bpy.types.Scene.fbp_compositor_blur_y = IntProperty(
        name="Blur Y",
        description="Vertical Gaussian blur radius in output pixels; zero disables the vertical blur",
        default=0,
        min=0,
        max=2048,
        soft_max=128,
        update=_update_compositor_setting,
    )
    bpy.types.Scene.fbp_compositor_glare_enabled = BoolProperty(
        name="Bloom",
        description="Enable the global Fog Glow compositor pass",
        default=False,
        update=_update_compositor_setting,
    )
    bpy.types.Scene.fbp_compositor_glare_threshold = FloatProperty(
        name="Threshold",
        description="Minimum brightness that contributes to compositor bloom",
        default=1.0,
        min=0.0,
        max=1000.0,
        soft_max=10.0,
        update=_update_compositor_setting,
    )
    bpy.types.Scene.fbp_compositor_glare_strength = FloatProperty(
        name="Strength",
        description="Amount of bloom blended with the original render",
        default=0.35,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
        update=_update_compositor_setting,
    )
    bpy.types.Scene.fbp_compositor_lens_distortion = FloatProperty(
        name="Distortion",
        description="Global lens barrel or pincushion distortion",
        default=0.0,
        min=-1.0,
        max=1.0,
        soft_min=-0.25,
        soft_max=0.25,
        update=_update_compositor_setting,
    )
    bpy.types.Scene.fbp_compositor_dispersion = FloatProperty(
        name="Dispersion",
        description="Global chromatic dispersion applied by the compositor lens-distortion pass",
        default=0.0,
        min=0.0,
        max=1.0,
        soft_max=0.25,
        update=_update_compositor_setting,
    )


def _unregister_properties():
    names = (
        "fbp_compositor_group",
        "fbp_compositor_previous_group",
        "fbp_compositor_preset",
        "fbp_compositor_exposure",
        "fbp_compositor_saturation",
        "fbp_compositor_value",
        "fbp_compositor_blur_x",
        "fbp_compositor_blur_y",
        "fbp_compositor_glare_enabled",
        "fbp_compositor_glare_threshold",
        "fbp_compositor_glare_strength",
        "fbp_compositor_lens_distortion",
        "fbp_compositor_dispersion",
    )
    for name in names:
        try:
            delattr(bpy.types.Scene, name)
        except FBP_DATA_IO_ERRORS:
            pass


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    _register_properties()


def unregister():
    _unregister_properties()
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except FBP_DATA_IO_ERRORS:
            pass
