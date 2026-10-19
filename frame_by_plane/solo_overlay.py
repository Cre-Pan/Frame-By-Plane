"""Viewport badge shown while Solo isolates Frame By Plane layers."""

import math

import bpy
import blf
import gpu
from gpu_extras.batch import batch_for_shader

from .grease_pencil_bridge import any_gp_canvas_solo, gp_canvas_solo_active
from .fbp_index import iter_scene_gp_canvases
from .runtime import FBP_DATA_ERRORS


_DRAW_HANDLE = None
_SHADER = None

_BADGE_FILL = (0.96, 0.70, 0.16, 0.94)
_BADGE_TEXT = (0.08, 0.06, 0.02, 1.0)
_BADGE_SHADOW = (0.0, 0.0, 0.0, 0.28)


def solo_layer_count(scene):
    """Return how many layers and Drawing Planes are soloed in ``scene``."""
    if scene is None:
        return 0
    count = 0
    try:
        count += sum(1 for item in getattr(scene, "fbp_layers", ()) or () if bool(getattr(item, "solo", False)))
    except FBP_DATA_ERRORS:
        pass
    try:
        if any_gp_canvas_solo(scene):
            count += sum(
                1 for canvas in iter_scene_gp_canvases(scene, kind="DRAWING", fallback=True)
                if gp_canvas_solo_active(canvas)
            )
    except FBP_DATA_ERRORS:
        pass
    return count


def _shader():
    global _SHADER
    if _SHADER is None:
        _SHADER = gpu.shader.from_builtin("UNIFORM_COLOR")
    return _SHADER


def _fill(vertices, color, kind="TRI_FAN"):
    shader = _shader()
    batch = batch_for_shader(shader, kind, {"pos": vertices})
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _pill(x, y, w, h, color):
    radius = h * 0.5
    points = []
    for cx, start in ((x + w - radius, -math.pi * 0.5), (x + radius, math.pi * 0.5)):
        for index in range(13):
            angle = start + math.pi * index / 12
            points.append((cx + math.cos(angle) * radius, y + radius + math.sin(angle) * radius))
    _fill(((x + w * 0.5, y + radius), *points, points[0]), color)


def _star(cx, cy, outer, color):
    inner = outer * 0.45
    points = []
    for index in range(10):
        radius = outer if index % 2 == 0 else inner
        angle = math.pi * 0.5 + math.pi * index / 5
        points.append((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
    _fill(((cx, cy), *points, points[0]), color)


def _top_inset(area, region):
    """Height of header regions drawn on top of the viewport region."""
    top = region.y + region.height
    inset = 0
    for other in getattr(area, "regions", ()) or ():
        if other.type not in {"HEADER", "TOOL_HEADER"} or other.height <= 1:
            continue
        if other.y < top and other.y + other.height >= top - 1:
            inset = max(inset, top - other.y)
    return inset


def _draw_badge():
    context = bpy.context
    space = getattr(context, "space_data", None)
    region = getattr(context, "region", None)
    area = getattr(context, "area", None)
    if space is None or region is None or area is None:
        return
    try:
        if not bool(space.overlay.show_overlays):
            return
        count = solo_layer_count(context.scene)
    except FBP_DATA_ERRORS:
        return
    if count <= 0:
        return
    try:
        scale = float(context.preferences.system.ui_scale) or 1.0
    except FBP_DATA_ERRORS:
        scale = 1.0
    text = "SOLO" if count == 1 else f"SOLO  {count}"
    font_id = 0
    blf.size(font_id, 12.0 * scale)
    text_w, _text_h = blf.dimensions(font_id, text)
    cap_h = blf.dimensions(font_id, "S")[1]
    h = 24.0 * scale
    star = 6.5 * scale
    pad = 11.0 * scale
    gap = 6.0 * scale
    w = pad + star * 2.0 + gap + text_w + pad
    x = round((region.width - w) * 0.5)
    y = round(region.height - _top_inset(area, region) - 10.0 * scale - h)
    if y < 0 or w > region.width:
        return
    gpu.state.blend_set("ALPHA")
    try:
        _pill(x, y - 1.5 * scale, w, h, _BADGE_SHADOW)
        _pill(x, y, w, h, _BADGE_FILL)
        _star(x + pad + star, y + h * 0.5, star, _BADGE_TEXT)
        blf.color(font_id, *_BADGE_TEXT)
        blf.position(font_id, x + pad + star * 2.0 + gap, y + (h - cap_h) * 0.5, 0)
        blf.draw(font_id, text)
    finally:
        gpu.state.blend_set("NONE")


def _tag_viewports():
    window_manager = getattr(bpy.context, "window_manager", None)
    for window in getattr(window_manager, "windows", ()) or ():
        for area in getattr(window.screen, "areas", ()) or ():
            if area.type == "VIEW_3D":
                area.tag_redraw()


def register():
    global _DRAW_HANDLE
    if bpy.app.background or _DRAW_HANDLE is not None:
        return
    _DRAW_HANDLE = bpy.types.SpaceView3D.draw_handler_add(_draw_badge, (), "WINDOW", "POST_PIXEL")


def unregister():
    global _DRAW_HANDLE, _SHADER
    handle = _DRAW_HANDLE
    _DRAW_HANDLE = None
    _SHADER = None
    if handle is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
        except (ValueError, RuntimeError):
            pass
        try:
            _tag_viewports()
        except FBP_DATA_ERRORS:
            pass
