"""Viewport badge shown while Solo isolates Frame By Plane layers."""

import math

import bpy
import blf
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils.geometry import tessellate_polygon

from .grease_pencil_bridge import any_gp_canvas_solo, gp_canvas_solo_active
from .fbp_index import iter_scene_gp_canvases
from .runtime import FBP_DATA_ERRORS


_DRAW_HANDLE = None
_SHADER = None

_BADGE_FILL = (0.96, 0.70, 0.16, 1.0)
_BADGE_TEXT = (0.08, 0.06, 0.02, 1.0)
_BADGE_SHADOW = (0.0, 0.0, 0.0, 0.28)

# Blender's light bulb Solo icon, normalized to a 14 x 17 box (y up).
_BULB_OUTLINE = (
    (
        (0.5, 0.9412), (0.4731, 0.9405), (0.4467, 0.9387), (0.4207, 0.9356), (0.3952, 0.9314),
        (0.3703, 0.926), (0.346, 0.9196), (0.3224, 0.912), (0.2995, 0.9035), (0.2774, 0.894),
        (0.2561, 0.8835), (0.2357, 0.8722), (0.2162, 0.86), (0.1978, 0.8469), (0.1803, 0.833),
        (0.164, 0.8184), (0.1488, 0.803), (0.1348, 0.787), (0.1221, 0.7703), (0.1106, 0.753),
        (0.1006, 0.7351), (0.0919, 0.7167), (0.0847, 0.6977), (0.079, 0.6783), (0.0748, 0.6585),
        (0.0723, 0.6382), (0.0714, 0.6176), (0.0723, 0.5978), (0.0748, 0.5783),
        (0.0789, 0.5593), (0.0845, 0.5407), (0.0915, 0.5224), (0.0999, 0.5046),
        (0.1096, 0.4871), (0.1205, 0.4701), (0.1326, 0.4534), (0.1457, 0.4371),
        (0.1599, 0.4212), (0.175, 0.4057), (0.1909, 0.3905), (0.2077, 0.3757), (0.2252, 0.3612),
        (0.2962, 0.3027), (0.3061, 0.2968), (0.3178, 0.294), (0.298, 0.2871), (0.2865, 0.2721),
        (0.2876, 0.2544), (0.3008, 0.2405), (0.3214, 0.2353), (0.6786, 0.2353), (0.699, 0.2406),
        (0.7121, 0.2546), (0.7131, 0.2723), (0.7016, 0.2872), (0.6818, 0.294), (0.6938, 0.2968),
        (0.7039, 0.3027), (0.7751, 0.3614), (0.7922, 0.3757), (0.8086, 0.3904),
        (0.8243, 0.4055), (0.8393, 0.421), (0.8534, 0.4369), (0.8665, 0.4532), (0.8786, 0.4699),
        (0.8896, 0.487), (0.8994, 0.5044), (0.908, 0.5223), (0.9151, 0.5406), (0.9208, 0.5592),
        (0.925, 0.5783), (0.9276, 0.5977), (0.9285, 0.6175), (0.9276, 0.6381), (0.9251, 0.6584),
        (0.9209, 0.6782), (0.9152, 0.6976), (0.908, 0.7165), (0.8993, 0.735), (0.8893, 0.7529),
        (0.8778, 0.7702), (0.8651, 0.7869), (0.8511, 0.8029), (0.8359, 0.8183),
        (0.8196, 0.8329), (0.8021, 0.8468), (0.7837, 0.8598), (0.7642, 0.8721),
        (0.7438, 0.8834), (0.7225, 0.8939), (0.7004, 0.9034), (0.6775, 0.9119),
        (0.6539, 0.9194), (0.6296, 0.9259), (0.6047, 0.9313), (0.5792, 0.9355),
        (0.5532, 0.9386), (0.5268, 0.9404), (0.4999, 0.9411),
    ),
    (
        (0.5, 0.8824), (0.5269, 0.8816), (0.5533, 0.8795), (0.579, 0.8759), (0.6039, 0.871),
        (0.6282, 0.8649), (0.6515, 0.8575), (0.674, 0.849), (0.6954, 0.8394), (0.7159, 0.8287),
        (0.7352, 0.817), (0.7534, 0.8044), (0.7703, 0.7908), (0.7859, 0.7764), (0.8002, 0.7612),
        (0.813, 0.7453), (0.8243, 0.7287), (0.8341, 0.7115), (0.8422, 0.6936), (0.8486, 0.6753),
        (0.8533, 0.6565), (0.8562, 0.6372), (0.8571, 0.6176), (0.8561, 0.5982), (0.8529, 0.579),
        (0.8476, 0.5601), (0.8405, 0.5415), (0.8315, 0.5232), (0.8207, 0.5052),
        (0.8083, 0.4875), (0.7944, 0.4701), (0.779, 0.4529), (0.7622, 0.4361), (0.7441, 0.4195),
        (0.7249, 0.4033), (0.6535, 0.3444), (0.6437, 0.3304), (0.6444, 0.3142),
        (0.6555, 0.3008), (0.6734, 0.2942), (0.3263, 0.2942), (0.3445, 0.3007), (0.3557, 0.314),
        (0.3566, 0.3303), (0.3468, 0.3444), (0.2754, 0.4033), (0.275, 0.4036), (0.2747, 0.4039),
        (0.255, 0.4202), (0.2366, 0.4368), (0.2197, 0.4536), (0.2043, 0.4706), (0.1904, 0.4879),
        (0.1782, 0.5055), (0.1676, 0.5234), (0.1588, 0.5416), (0.1519, 0.5601), (0.1468, 0.579),
        (0.1437, 0.5983), (0.1427, 0.618), (0.1437, 0.6376), (0.1465, 0.6568), (0.1512, 0.6757),
        (0.1576, 0.694), (0.1658, 0.7118), (0.1755, 0.7291), (0.1869, 0.7457), (0.1997, 0.7616),
        (0.2139, 0.7768), (0.2296, 0.7912), (0.2465, 0.8047), (0.2646, 0.8174), (0.284, 0.8291),
        (0.3044, 0.8398), (0.3259, 0.8494), (0.3483, 0.8579), (0.3717, 0.8653),
        (0.3959, 0.8714), (0.4209, 0.8763), (0.4466, 0.8798), (0.4729, 0.882), (0.4998, 0.8827),
    ),
    (
        (0.3214, 0.1765), (0.3002, 0.171), (0.287, 0.1562), (0.287, 0.1379), (0.3002, 0.1231),
        (0.3214, 0.1176), (0.4286, 0.1176), (0.4286, 0.0882), (0.4334, 0.0735),
        (0.4464, 0.0628), (0.4643, 0.0588), (0.5357, 0.0588), (0.5536, 0.0628),
        (0.5666, 0.0735), (0.5714, 0.0882), (0.5714, 0.1176), (0.6786, 0.1176),
        (0.6998, 0.1231), (0.713, 0.1379), (0.713, 0.1562), (0.6998, 0.171), (0.6786, 0.1765),
    ),
)
_BULB_FILAMENT = (
    (
        (0.3207, 0.6467), (0.3014, 0.6414), (0.2887, 0.6284), (0.2868, 0.6117),
        (0.2962, 0.5969), (0.3571, 0.5466), (0.3571, 0.4559), (0.3638, 0.4384),
        (0.3817, 0.4275), (0.404, 0.4275), (0.4219, 0.4384), (0.4286, 0.4559), (0.4286, 0.5294),
        (0.5714, 0.5294), (0.5714, 0.4559), (0.5781, 0.4384), (0.596, 0.4275), (0.6183, 0.4275),
        (0.6362, 0.4384), (0.6429, 0.4559), (0.6429, 0.5466), (0.7038, 0.5969), (0.7134, 0.613),
        (0.7098, 0.6307), (0.6944, 0.6433), (0.6729, 0.6463), (0.6533, 0.6384),
        (0.5924, 0.5882), (0.4076, 0.5882), (0.3467, 0.6384), (0.3347, 0.6447),
    ),
)
_BULB_ASPECT = 14.0 / 17.0
_BULB_TRIANGLES = {}


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


def _loop_triangles(key, loop):
    triangles = _BULB_TRIANGLES.get(key)
    if triangles is None:
        triangles = tuple(
            tuple(loop[index] for index in triangle)
            for triangle in tessellate_polygon([list(loop)])
        )
        _BULB_TRIANGLES[key] = triangles
    return triangles


def _bulb(x, y, h, color, background):
    w = h * _BULB_ASPECT
    outer, hole, base = _BULB_OUTLINE
    # Each loop is filled on its own: the glass outline is drawn solid, then
    # its inside is painted with the badge color again.
    layers = (
        ("outer", outer, color),
        ("hole", hole, (*background[:3], 1.0)),
        ("base", base, color),
        ("filament", _BULB_FILAMENT[0], (*color[:3], color[3] * 0.6)),
    )
    for key, loop, fill in layers:
        vertices = [
            (x + px * w, y + py * h)
            for triangle in _loop_triangles(key, loop)
            for px, py in triangle
        ]
        _fill(vertices, fill, "TRIS")


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
    icon_h = 15.0 * scale
    icon_w = icon_h * _BULB_ASPECT
    pad = 10.0 * scale
    gap = 5.0 * scale
    w = pad + icon_w + gap + text_w + pad + 1.0 * scale
    x = round((region.width - w) * 0.5)
    y = round(region.height - _top_inset(area, region) - 10.0 * scale - h)
    if y < 0 or w > region.width:
        return
    gpu.state.blend_set("ALPHA")
    try:
        _pill(x, y - 1.5 * scale, w, h, _BADGE_SHADOW)
        _pill(x, y, w, h, _BADGE_FILL)
        _bulb(x + pad, y + (h - icon_h) * 0.5, icon_h, _BADGE_TEXT, _BADGE_FILL)
        blf.color(font_id, *_BADGE_TEXT)
        blf.position(font_id, x + pad + icon_w + gap, y + (h - cap_h) * 0.5, 0)
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
