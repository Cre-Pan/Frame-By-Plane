"""Selection outline for layers whose rig wire is hidden (Show Rig off).

Without a visible wire Blender has nothing to highlight when such a layer is
selected, so this overlay draws the layer's outline (the same Alpha Outline or
preset shape the wire would use) in the theme's selection colours, on top of
the image, only while the layer is selected.
"""

from __future__ import annotations

import bpy
import gpu
from gpu_extras.batch import batch_for_shader

from .runtime import FBP_DATA_ERRORS


_DRAW_HANDLE = None
_SHADER = None
_WIDTH = 1.6


def _shader():
    global _SHADER
    if _SHADER is None:
        _SHADER = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    return _SHADER


def _theme_colors(context):
    try:
        theme = context.preferences.themes[0].view_3d
        active = tuple(theme.object_active) + (1.0,)
        selected = tuple(theme.object_selected) + (1.0,)
        return active[:4], selected[:4]
    except (*FBP_DATA_ERRORS, IndexError):
        return (1.0, 0.63, 0.16, 1.0), (0.93, 0.34, 0.0, 1.0)


def _hidden_rig_outlines(context):
    from .builder import fbp_rig_outline_geometry, fbp_rig_wire_visible

    active = getattr(context.view_layer.objects, "active", None)
    for obj in tuple(getattr(context, "selected_objects", ()) or ()):
        try:
            if not bool(getattr(obj, "is_fbp_control", False)) or fbp_rig_wire_visible(obj):
                continue
            if not obj.visible_get():
                continue
            geometry = fbp_rig_outline_geometry(obj)
        except FBP_DATA_ERRORS:
            continue
        if not geometry:
            continue
        verts, edges = geometry
        matrix = obj.matrix_world
        world = [matrix @ _vector(vert) for vert in verts]
        segments = []
        for a, b in edges:
            if a < len(world) and b < len(world):
                segments.append(world[a][:])
                segments.append(world[b][:])
        if segments:
            yield obj == active, segments


def _vector(values):
    from mathutils import Vector
    return Vector((float(values[0]), float(values[1]), float(values[2]) if len(values) > 2 else 0.0))


def _draw():
    context = bpy.context
    space = getattr(context, "space_data", None)
    region = getattr(context, "region", None)
    if space is None or region is None or getattr(context, "mode", "") != 'OBJECT':
        return
    try:
        if not bool(space.overlay.show_overlays):
            return
    except FBP_DATA_ERRORS:
        return
    outlines = list(_hidden_rig_outlines(context))
    if not outlines:
        return
    active_color, selected_color = _theme_colors(context)
    try:
        scale = float(context.preferences.system.ui_scale) or 1.0
    except FBP_DATA_ERRORS:
        scale = 1.0
    shader = _shader()
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE")
    gpu.state.depth_mask_set(False)
    try:
        shader.bind()
        shader.uniform_float("viewportSize", (region.width, region.height))
        shader.uniform_float("lineWidth", _WIDTH * scale)
        for is_active, segments in outlines:
            shader.uniform_float("color", active_color if is_active else selected_color)
            batch_for_shader(shader, "LINES", {"pos": segments}).draw(shader)
    finally:
        gpu.state.blend_set("NONE")
        gpu.state.depth_mask_set(True)
        gpu.state.depth_test_set("LESS_EQUAL")


def register():
    global _DRAW_HANDLE
    if bool(getattr(bpy.app, "background", False)) or _DRAW_HANDLE is not None:
        return
    _DRAW_HANDLE = bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_VIEW")


def unregister():
    global _DRAW_HANDLE
    if _DRAW_HANDLE is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_DRAW_HANDLE, "WINDOW")
        except (ValueError, RuntimeError):
            pass
        _DRAW_HANDLE = None
