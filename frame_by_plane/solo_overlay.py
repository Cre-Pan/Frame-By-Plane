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

# Same translucent look as the navigation buttons on the viewport's right side.
_BADGE_FILL = (0.0, 0.0, 0.0, 0.24)
_BADGE_TEXT = (1.0, 1.0, 1.0, 0.9)

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
# Triangles (indices into outer + inner loop) filling the glass outline.
_BULB_RING_TRIANGLES = (
    (26, 159, 160), (26, 160, 161), (26, 161, 162), (26, 162, 163), (26, 163, 164),
    (26, 164, 165), (26, 165, 166), (26, 166, 167), (181, 100, 101), (134, 135, 136),
    (134, 136, 137), (134, 137, 138), (134, 138, 139), (140, 141, 142), (140, 142, 143),
    (140, 143, 144), (140, 144, 145), (140, 145, 146), (140, 146, 147), (140, 147, 148),
    (140, 148, 149), (140, 149, 150), (140, 150, 151), (140, 151, 152), (158, 159, 26),
    (158, 26, 27), (158, 27, 28), (158, 28, 29), (158, 29, 30), (158, 30, 31), (158, 31, 32),
    (158, 32, 33), (158, 33, 34), (158, 34, 35), (158, 35, 36), (158, 36, 37), (37, 38, 39),
    (37, 39, 40), (37, 40, 41), (37, 41, 42), (37, 42, 43), (37, 43, 44), (44, 45, 46),
    (44, 46, 47), (44, 47, 48), (44, 48, 49), (44, 49, 50), (44, 50, 51), (44, 51, 52),
    (44, 52, 53), (44, 53, 54), (44, 54, 55), (55, 56, 57), (55, 57, 58), (55, 58, 59),
    (55, 59, 60), (55, 60, 61), (55, 61, 62), (55, 62, 63), (55, 63, 64), (55, 64, 65),
    (55, 65, 66), (55, 66, 67), (55, 67, 68), (55, 68, 69), (55, 69, 70), (55, 70, 71),
    (55, 71, 72), (55, 72, 73), (55, 73, 74), (55, 74, 75), (75, 76, 77), (75, 77, 78),
    (75, 78, 79), (75, 79, 80), (75, 80, 81), (75, 81, 82), (75, 82, 83), (75, 83, 84),
    (75, 84, 85), (75, 85, 86), (75, 86, 87), (75, 87, 88), (75, 88, 89), (75, 89, 90),
    (75, 90, 91), (75, 91, 92), (75, 92, 93), (75, 93, 94), (94, 95, 96), (94, 96, 97),
    (94, 97, 98), (94, 98, 99), (99, 0, 1), (99, 1, 2), (99, 2, 3), (99, 3, 4), (99, 4, 5),
    (99, 5, 6), (99, 6, 7), (99, 7, 8), (99, 8, 9), (99, 9, 10), (99, 10, 11), (99, 11, 12),
    (99, 12, 13), (99, 13, 14), (99, 14, 15), (99, 15, 16), (99, 16, 17), (99, 17, 18),
    (99, 18, 19), (99, 19, 20), (20, 21, 22), (20, 22, 23), (20, 23, 24), (20, 24, 25),
    (20, 25, 26), (20, 26, 167), (20, 167, 168), (20, 168, 169), (20, 169, 170), (20, 170, 171),
    (20, 171, 172), (20, 172, 173), (133, 134, 139), (157, 158, 37), (99, 20, 173),
    (99, 173, 174), (99, 174, 175), (99, 175, 176), (99, 176, 177), (99, 177, 178),
    (99, 178, 179), (99, 179, 180), (99, 180, 181), (99, 181, 101), (99, 101, 102),
    (99, 102, 103), (99, 103, 104), (99, 104, 105), (99, 105, 106), (99, 106, 107),
    (99, 107, 108), (132, 133, 139), (156, 157, 37), (94, 99, 108), (94, 108, 109),
    (94, 109, 110), (94, 110, 111), (94, 111, 112), (94, 112, 113), (131, 132, 139),
    (155, 156, 37), (75, 94, 113), (75, 113, 114), (75, 114, 115), (75, 115, 116),
    (75, 116, 117), (75, 117, 118), (75, 118, 119), (75, 119, 120), (75, 120, 121),
    (75, 121, 122), (75, 122, 123), (75, 123, 124), (75, 124, 125), (75, 125, 126),
    (75, 126, 127), (75, 127, 128), (130, 131, 139), (154, 155, 37), (55, 75, 128),
    (55, 128, 129), (55, 129, 130), (55, 130, 139), (55, 139, 140), (153, 154, 37),
    (153, 37, 44), (44, 55, 140), (44, 140, 152), (44, 152, 153),
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


def _bulb(x, y, h, color):
    w = h * _BULB_ASPECT
    outer, hole, base = _BULB_OUTLINE
    ring = outer + hole
    shapes = (
        ("ring", tuple(tuple(ring[index] for index in triangle) for triangle in _BULB_RING_TRIANGLES), color),
        ("base", _loop_triangles("base", base), color),
        ("filament", _loop_triangles("filament", _BULB_FILAMENT[0]), (*color[:3], color[3] * 0.6)),
    )
    for _key, triangles, fill in shapes:
        vertices = [(x + px * w, y + py * h) for triangle in triangles for px, py in triangle]
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
        # The Z pie's Solo uses Blender's Local View in this viewport only.
        local_view = getattr(space, "local_view", None) is not None
    except FBP_DATA_ERRORS:
        return
    if count <= 0 and not local_view:
        return
    try:
        scale = float(context.preferences.system.ui_scale) or 1.0
    except FBP_DATA_ERRORS:
        scale = 1.0
    text = f"SOLO  {count}" if count > 1 else "SOLO"
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
        _pill(x, y, w, h, _BADGE_FILL)
        _bulb(x + pad, y + (h - icon_h) * 0.5, icon_h, _BADGE_TEXT)
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
