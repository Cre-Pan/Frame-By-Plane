"""Draw Frame By Plane viewport handles on top of everything.

Handle meshes stay ordinary selectable objects, but Blender only keeps a
solid mesh "In Front" in Solid shading: in Material Preview and Rendered they
sink behind the image plane. This overlay redraws every visible handle from its
evaluated (Lattice-deformed) mesh without depth test, with a thin dark rim so
it reads on light and dark artwork alike.
"""

from __future__ import annotations

import bpy
import gpu
from gpu_extras.batch import batch_for_shader

from .runtime import FBP_DATA_ERRORS
from .viewport_handles import (
    HANDLE_COLOR,
    HANDLE_OUTLINE_COLOR,
    HANDLE_SELECTED_COLOR,
    KEY_OVERLAY_HANDLE,
)


_DRAW_HANDLE = None
_FILL_SHADER = None
_LINE_SHADER = None
_OUTLINE_WIDTH = 1.5


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


def _handle_geometry(obj, depsgraph):
    """World-space triangles and rim segments of one evaluated handle mesh."""
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        matrix = evaluated.matrix_world
        points = [matrix @ vertex.co for vertex in mesh.vertices]
        mesh.calc_loop_triangles()
        triangles = [points[index] for tri in mesh.loop_triangles for index in tri.vertices]
        edge_users = {}
        for polygon in mesh.polygons:
            for key in polygon.edge_keys:
                edge_users[key] = edge_users.get(key, 0) + 1
        rim = [points[index] for key, users in edge_users.items() if users == 1 for index in key]
    finally:
        evaluated.to_mesh_clear()
    return triangles, rim


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
    if not handles:
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
    shapes = []
    for obj in handles:
        try:
            triangles, rim = _handle_geometry(obj, depsgraph)
            selected = bool(obj.select_get())
        except FBP_DATA_ERRORS:
            continue
        if triangles:
            shapes.append((triangles, rim, HANDLE_SELECTED_COLOR if selected else HANDLE_COLOR))
    if not shapes:
        return
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE")
    gpu.state.depth_mask_set(False)
    try:
        # Rims first: the fills cover their inner half, leaving a thin edge.
        line_shader.bind()
        line_shader.uniform_float("viewportSize", (region.width, region.height))
        line_shader.uniform_float("lineWidth", _OUTLINE_WIDTH * scale)
        line_shader.uniform_float("color", HANDLE_OUTLINE_COLOR)
        for _triangles, rim, _color in shapes:
            if rim:
                batch_for_shader(line_shader, "LINES", {"pos": rim}).draw(line_shader)
        fill_shader.bind()
        for triangles, _rim, color in shapes:
            fill_shader.uniform_float("color", color)
            batch_for_shader(fill_shader, "TRIS", {"pos": triangles}).draw(fill_shader)
    finally:
        gpu.state.depth_mask_set(True)
        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.blend_set("NONE")


def is_overlay_handle(obj):
    try:
        return bool(obj.get(KEY_OVERLAY_HANDLE, False))
    except FBP_DATA_ERRORS:
        return False


def register():
    global _DRAW_HANDLE
    if bpy.app.background or _DRAW_HANDLE is not None:
        return
    _DRAW_HANDLE = bpy.types.SpaceView3D.draw_handler_add(_draw_handles, (), "WINDOW", "POST_VIEW")


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
