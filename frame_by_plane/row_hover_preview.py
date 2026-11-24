"""Large thumbnail shown while the mouse rests on a Layer or Frame list row.

Blender's Python API cannot put an image inside a native tooltip (5.2 and 5.3
only add images for Image/Movie/Font search items in C). The name button of
every Frame By Plane list row is ``fbp.ui_list_name_action``, whose dynamic
``description()`` runs exactly when Blender opens the tooltip for that row.
That call returns a short text tooltip (row name, frame number) and schedules
a tiny pass-through modal operator that draws a larger thumbnail beside the
list. The preview disappears as soon as the mouse moves or any key/button is
pressed, mirroring the native tooltip lifetime. Nothing is written to scene
data and no undo step is created.
"""

from __future__ import annotations

import os

import bpy
from bpy.types import Operator

from .runtime import FBP_DATA_ERRORS, FBP_DATA_IO_ERRORS


_SIZE_PIXELS = {'SMALL': 160, 'MEDIUM': 256, 'LARGE': 384}
_PREVIEW_TARGETS = {'LAYER', 'FRAME', 'PENDING'}
_MOVE_THRESHOLD_PX = 6
_EDGE_GAP_PX = 10
_PADDING_PX = 8

# Process-local, never saved. ``payload`` is what the draw callback shows.
_STATE = {
    "running": False,
    "payload": None,
    "anchor": None,
    "last_mouse": None,
    "pending": None,
    "texture": None,
    "texture_key": None,
    "texture_size": (0, 0),
    "handle": None,
}


# ---------------------------------------------------------------------------
# Text tooltip
# ---------------------------------------------------------------------------

def _rig(properties):
    try:
        name = str(getattr(properties, "rig_name", "") or "")
        return bpy.data.objects.get(name) if name else None
    except FBP_DATA_ERRORS:
        return None


def _frame_rows(rig):
    try:
        return getattr(rig, "fbp_images", None) or ()
    except FBP_DATA_ERRORS:
        return ()


def _current_row_index(rig, scene):
    try:
        from .core import fbp_sequence_index_at_frame
        return int(fbp_sequence_index_at_frame(rig, getattr(scene, "frame_current", None)))
    except (ImportError,) + FBP_DATA_ERRORS:
        return -1


def _frame_info(rig, index):
    """Return (row name, 1-based row, row count, first scene frame, duration)."""
    rows = _frame_rows(rig)
    count = len(rows)
    if not (0 <= index < count):
        return None
    item = rows[index]
    name = "Alpha" if bool(getattr(item, "is_empty", False)) else str(getattr(item, "name", "") or "")
    try:
        from .operator_common import fbp_sequence_row_start_frame
        start = fbp_sequence_row_start_frame(rig, index)
    except (ImportError,) + FBP_DATA_ERRORS:
        start = None
    duration = max(1, int(getattr(item, "duration", 1) or 1))
    return name, index + 1, count, start, duration


def _frame_detail(start, duration):
    if start is None:
        return ""
    if duration <= 1:
        return f"Scene frame {start}"
    return f"Scene frames {start}-{start + duration - 1}"


def row_tooltip_lines(context, properties):
    """Return ``(title, detail)`` for one list row, or ``None`` when unknown."""
    target = str(getattr(properties, "target_type", "") or "")
    index = int(getattr(properties, "index", -1))
    if target == 'FRAME':
        rig = _rig(properties)
        info = _frame_info(rig, index) if rig else None
        if not info:
            return None
        name, row, count, start, duration = info
        detail = f"Frame {row} of {count}"
        scene_detail = _frame_detail(start, duration)
        if scene_detail:
            detail = f"{detail} · {scene_detail}"
        return name, detail
    if target in {'LAYER', 'GP_CANVAS'}:
        rig = _rig(properties)
        if rig is None:
            return None
        name = str(getattr(rig, "name", "") or "")
        rows = _frame_rows(rig)
        count = len(rows)
        if target == 'GP_CANVAS' or count == 0:
            return name, ""
        current = _current_row_index(rig, getattr(context, "scene", None))
        if 0 <= current < count:
            return name, f"Frame {current + 1} of {count} at the current scene frame"
        return name, f"{count} frames"
    if target == 'PENDING':
        try:
            item = context.scene.fbp_pending_planes[index]
        except (AttributeError, IndexError, KeyError, TypeError):
            return None
        files = [value for value in str(getattr(item, "files_str", "") or "").split("|") if value]
        detail = f"{len(files)} images" if len(files) > 1 else ""
        return str(getattr(item, "name", "") or ""), detail
    if target == 'COLLECTION':
        return str(getattr(properties, "collection_name", "") or ""), ""
    if target == 'PENDING_GROUP':
        return str(getattr(properties, "collection_name", "") or "").rsplit(" / ", 1)[-1], ""
    return None


def row_tooltip_text(context, properties):
    """Dynamic tooltip for ``fbp.ui_list_name_action`` and preview trigger."""
    hint = "Click to select. Double-click to rename."
    try:
        lines = row_tooltip_lines(context, properties)
    except FBP_DATA_IO_ERRORS:
        lines = None
    try:
        _request_preview(context, properties, lines)
    except FBP_DATA_IO_ERRORS:
        pass
    if not lines:
        return hint
    title, detail = lines
    parts = [part for part in (title, detail) if part]
    parts.append(hint)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Thumbnail source
# ---------------------------------------------------------------------------

def _preview_size_setting(context):
    try:
        from .interface_preferences import fbp_get_addon_preferences
        prefs = fbp_get_addon_preferences(context)
    except (ImportError,) + FBP_DATA_ERRORS:
        prefs = None
    value = str(getattr(prefs, "row_hover_preview_size", "MEDIUM") or "MEDIUM") if prefs else "MEDIUM"
    return value if value in _SIZE_PIXELS or value == 'OFF' else 'MEDIUM'


def _thumbnail_path_or_preview(context, properties):
    """Return ``(cache_key, preview)`` for the row, or ``(None, None)``."""
    from .layers import get_layer_thumbnail, load_preview
    scene = getattr(context, "scene", None)
    target = str(getattr(properties, "target_type", "") or "")
    index = int(getattr(properties, "index", -1))
    if target == 'FRAME':
        rig = _rig(properties)
        rows = _frame_rows(rig) if rig else ()
        if not (0 <= index < len(rows)):
            return None, None
        item = rows[index]
        if bool(getattr(item, "is_empty", False)) or bool(getattr(rig, "fbp_is_color_plane", False)):
            return None, None
        path = str(getattr(item, "filepath", "") or "")
        if not path:
            return None, None
        return f"F|{path}", load_preview(path, scene=scene)
    if target == 'LAYER':
        rig = _rig(properties)
        if rig is None or bool(getattr(rig, "fbp_is_color_plane", False)):
            return None, None
        preview = get_layer_thumbnail(rig, scene=scene)
        return f"L|{getattr(rig, 'name', '')}|{getattr(preview, 'icon_id', 0)}", preview
    if target == 'PENDING':
        try:
            item = scene.fbp_pending_planes[index]
        except (AttributeError, IndexError, KeyError, TypeError):
            return None, None
        files = [value for value in str(getattr(item, "files_str", "") or "").split("|") if value]
        directory = str(getattr(item, "directory", "") or "")
        if not files:
            return None, None
        path = os.path.join(bpy.path.abspath(directory), files[0]) if directory else files[0]
        return f"P|{path}", load_preview(path, scene=scene)
    return None, None


def _texture_from_preview(preview):
    """Upload Blender's preview buffer (at most 256 px) as a GPU texture."""
    if preview is None:
        return None, (0, 0)
    try:
        width, height = (int(value) for value in preview.image_size)
    except FBP_DATA_ERRORS:
        return None, (0, 0)
    if width <= 0 or height <= 0:
        return None, (0, 0)
    try:
        import gpu
        import numpy as np
        pixels = np.empty(width * height * 4, dtype=np.float32)
        preview.image_pixels_float.foreach_get(pixels)
        buffer = gpu.types.Buffer('FLOAT', width * height * 4, pixels)
        texture = gpu.types.GPUTexture((width, height), format='RGBA16F', data=buffer)
        return texture, (width, height)
    except (ImportError,) + FBP_DATA_ERRORS:
        return None, (0, 0)


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------

def _request_preview(context, properties, lines):
    if bpy.app.background:
        return
    target = str(getattr(properties, "target_type", "") or "")
    if target not in _PREVIEW_TARGETS:
        return
    size_setting = _preview_size_setting(context)
    if size_setting == 'OFF':
        return
    window = getattr(context, "window", None)
    area = getattr(context, "area", None)
    region = getattr(context, "region", None)
    if window is None or area is None or region is None:
        return
    key, preview = _thumbnail_path_or_preview(context, properties)
    if not key or preview is None:
        return
    title, detail = lines if lines else ("", "")
    payload = {
        "key": key,
        "preview": preview,
        "title": str(title or ""),
        "detail": str(detail or ""),
        "size": _SIZE_PIXELS.get(size_setting, 256),
        "tooltip_lines": tuple(part for part in (title, detail, "Click to select. Double-click to rename.") if part),
        "area_ptr": area.as_pointer(),
        "region_ptr": region.as_pointer(),
        "region_rect": (int(region.x), int(region.y), int(region.width), int(region.height)),
        "region_alignment": str(getattr(region, "alignment", "") or ""),
        "region_type": str(getattr(region, "type", "") or ""),
    }
    if _STATE["running"]:
        # A new tooltip opened before the mouse moved past the threshold
        # (e.g. onto the next row). Swap content and re-anchor in place.
        _STATE["payload"] = payload
        _STATE["anchor"] = _STATE.get("last_mouse")
        _tag_area(_STATE.get("draw_area") or area)
        return
    _STATE["pending"] = {
        "payload": payload,
        "window_ptr": window.as_pointer(),
        "area_ptr": payload["area_ptr"],
        "region_ptr": payload["region_ptr"],
    }
    if not bpy.app.timers.is_registered(_start_preview_operator):
        bpy.app.timers.register(_start_preview_operator, first_interval=0.0)


def _find_window_area_region(window_ptr, area_ptr, region_ptr):
    wm = getattr(bpy.context, "window_manager", None)
    for window in getattr(wm, "windows", ()):
        if window.as_pointer() != window_ptr:
            continue
        screen = window.screen
        for area in getattr(screen, "areas", ()):
            if area.as_pointer() != area_ptr:
                continue
            for region in area.regions:
                if region.as_pointer() == region_ptr:
                    return window, area, region
    return None


def _start_preview_operator():
    pending = _STATE.get("pending")
    _STATE["pending"] = None
    if not pending or _STATE["running"]:
        return None
    try:
        found = _find_window_area_region(
            pending["window_ptr"], pending["area_ptr"], pending["region_ptr"],
        )
        if not found:
            return None
        window, area, region = found
        _STATE["payload"] = pending["payload"]
        with bpy.context.temp_override(window=window, area=area, region=region):
            bpy.ops.fbp.row_hover_preview('INVOKE_DEFAULT')
    except FBP_DATA_IO_ERRORS:
        _STATE["payload"] = None
    return None


def _tag_area(area):
    try:
        area.tag_redraw()
    except FBP_DATA_ERRORS:
        pass


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def _ui_scale():
    try:
        return float(bpy.context.preferences.system.ui_scale or 1.0)
    except FBP_DATA_ERRORS:
        return 1.0


def _tooltip_theme():
    try:
        wcol = bpy.context.preferences.themes[0].user_interface.wcol_tooltip
        inner = tuple(wcol.inner)
        text = tuple(wcol.text)
        line = tuple(wcol.outline)
        return (
            (inner[0], inner[1], inner[2], max(0.95, inner[3])),
            (text[0], text[1], text[2], 1.0),
            (line[0], line[1], line[2], 1.0),
        )
    except (AttributeError, IndexError, TypeError):
        return (0.1, 0.1, 0.1, 0.95), (0.9, 0.9, 0.9, 1.0), (0.3, 0.3, 0.3, 1.0)


def _texture_for_payload(payload):
    key = payload.get("key")
    if _STATE.get("texture_key") == key and _STATE.get("texture") is not None:
        return _STATE["texture"], _STATE["texture_size"]
    texture, size = _texture_from_preview(payload.get("preview"))
    if texture is not None:
        _STATE["texture"] = texture
        _STATE["texture_key"] = key
        _STATE["texture_size"] = size
    return texture, size


_TOOLTIP_MAX_WIDTH = 600  # TIP_MAXWIDTH in Blender's interface_region_tooltip.cc


def _estimated_tooltip_left(payload, window_width):
    """Left edge (window px) of Blender's own tooltip for this row.

    Blender opens it at the cursor, below the row, and pushes it left so it
    fits in the window; near the bottom of the window it jumps above the row.
    Keeping the preview left of this edge means the tooltip never covers it,
    whichever way Blender flips it.
    """
    scale = _ui_scale()
    mouse_x = (_STATE.get("anchor") or (0, 0))[0]
    width = payload.get("tooltip_width") or 0
    try:
        if not width:
            import blf
            blf.size(0, 11.0 * scale)
            lines = list(payload.get("tooltip_lines") or ())
            width = max((blf.dimensions(0, line)[0] for line in lines), default=0.0)
            if bool(getattr(bpy.context.preferences.view, "show_tooltips_python", False)):
                # The "Python: bpy.ops..." line almost always reaches the wrap width.
                width = _TOOLTIP_MAX_WIDTH * scale
            width = min(width, _TOOLTIP_MAX_WIDTH * scale) + 24.0 * scale
            payload["tooltip_width"] = width
    except (ImportError,) + FBP_DATA_ERRORS:
        width = (_TOOLTIP_MAX_WIDTH + 24.0) * scale
    left = min(mouse_x - 12.0 * scale, window_width - 8.0 * scale - width)
    return left


def _placement(payload, region, box_w, box_h):
    """Return the box origin in ``region`` pixel space."""
    anchor = _STATE.get("anchor") or (region.x + region.width // 2, region.y + region.height // 2)
    mouse_x, mouse_y = anchor
    scale = _ui_scale()
    gap = int(_EDGE_GAP_PX * scale)
    try:
        window_width = int(bpy.context.window.width)
    except FBP_DATA_ERRORS:
        window_width = region.x + region.width
    side, edge_x = _STATE.get("dock") or ('SELF', 0)
    if side == 'RIGHT':
        # The list is left of the drawing area: Blender's tooltip grows to the
        # right of the cursor, so stay right of its maximum width.
        x = max(edge_x, mouse_x + (_TOOLTIP_MAX_WIDTH + 24) * scale) + gap
    else:
        right_edge = _estimated_tooltip_left(payload, window_width)
        if side == 'LEFT':
            right_edge = min(right_edge, edge_x)
        x = right_edge - gap - box_w
    # Vertically centred on the hovered row.
    y = mouse_y - box_h * 0.5
    x = max(region.x + gap, min(x, region.x + region.width - gap - box_w))
    y = max(region.y + gap, min(y, region.y + region.height - gap - box_h))
    return x - region.x, y - region.y


# Rounded, anti-aliased card and image: one small shader, a signed distance
# to a rounded rectangle in pixel space, so corners stay smooth at any size.
_ROUNDED_SHADER = None


def _rounded_shader():
    global _ROUNDED_SHADER
    if _ROUNDED_SHADER is not None:
        return _ROUNDED_SHADER
    import gpu
    info = gpu.types.GPUShaderCreateInfo()
    info.push_constant('MAT4', "ModelViewProjectionMatrix")
    info.push_constant('VEC4', "rect")
    info.push_constant('VEC4', "color")
    info.push_constant('FLOAT', "radius")
    info.push_constant('INT', "use_image")
    # Bound automatically by Blender on every draw: true when the target
    # framebuffer is sRGB (the 3D viewport overlay), as in its own 2D shaders.
    info.push_constant('BOOL', "srgbTarget")
    info.sampler(0, 'FLOAT_2D', "image")
    interface = gpu.types.GPUStageInterfaceInfo("fbp_row_hover_preview")
    interface.smooth('VEC2', "local_px")
    interface.smooth('VEC2', "uv")
    info.vertex_in(0, 'VEC2', "pos")
    info.vertex_out(interface)
    info.fragment_out(0, 'VEC4', "FragColor")
    info.vertex_source(
        "void main()"
        "{"
        "  local_px = pos - rect.xy;"
        "  uv = (pos - rect.xy) / rect.zw;"
        "  gl_Position = ModelViewProjectionMatrix * vec4(pos, 0.0, 1.0);"
        "}"
    )
    info.fragment_source(
        "vec4 fbp_to_framebuffer(vec4 c)"
        "{"
        "  if (srgbTarget) {"
        "    vec3 lo = c.rgb / 12.92;"
        "    vec3 hi = pow((c.rgb + 0.055) / 1.055, vec3(2.4));"
        "    c.rgb = mix(lo, hi, step(vec3(0.04045), c.rgb));"
        "  }"
        "  return c;"
        "}"
        "void main()"
        "{"
        "  vec2 half_size = rect.zw * 0.5;"
        "  vec2 q = abs(local_px - half_size) - (half_size - vec2(radius));"
        "  float dist = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - radius;"
        "  float coverage = clamp(0.5 - dist, 0.0, 1.0);"
        "  vec4 base = (use_image != 0) ? texture(image, uv) : color;"
        "  FragColor = fbp_to_framebuffer(vec4(base.rgb, base.a * coverage));"
        "}"
    )
    _ROUNDED_SHADER = gpu.shader.create_from_info(info)
    return _ROUNDED_SHADER


def _draw_rounded(texture, x, y, width, height, radius, color=(0.0, 0.0, 0.0, 0.0)):
    import gpu
    from gpu_extras.batch import batch_for_shader
    shader = _rounded_shader()
    coords = ((x, y), (x + width, y), (x, y + height), (x + width, y + height))
    batch = batch_for_shader(shader, 'TRI_STRIP', {"pos": coords})
    shader.bind()
    matrix = gpu.matrix.get_projection_matrix() @ gpu.matrix.get_model_view_matrix()
    shader.uniform_float("ModelViewProjectionMatrix", matrix)
    shader.uniform_float("rect", (float(x), float(y), float(width), float(height)))
    shader.uniform_float("color", tuple(color))
    shader.uniform_float("radius", float(min(radius, width * 0.5, height * 0.5)))
    shader.uniform_int("use_image", 1 if texture is not None else 0)
    shader.uniform_sampler("image", texture if texture is not None else _STATE["texture"])
    batch.draw(shader)


def _draw_callback():
    payload = _STATE.get("payload")
    if not payload or not _STATE["running"]:
        return
    context = bpy.context
    area = getattr(context, "area", None)
    region = getattr(context, "region", None)
    if area is None or region is None or area.as_pointer() != _STATE.get("draw_area_ptr"):
        return
    try:
        import gpu
        from .feedback import _fbp_import_blf, _gpu_text
    except ImportError:
        return
    texture, (tex_w, tex_h) = _texture_for_payload(payload)
    if texture is None or tex_w <= 0 or tex_h <= 0:
        return
    scale = _ui_scale()
    longest = payload["size"] * scale
    factor = longest / float(max(tex_w, tex_h))
    img_w, img_h = tex_w * factor, tex_h * factor
    pad = _PADDING_PX * scale
    text_size = 11.0 * scale
    line_h = text_size * 1.5
    lines = [line for line in (payload["title"], payload["detail"]) if line]
    box_w = max(img_w, 160.0 * scale) + pad * 2
    box_h = img_h + pad * 2 + line_h * len(lines) + (pad * 0.25 if lines else 0.0)
    x, y = _placement(payload, region, box_w, box_h)
    background, text_color, outline = _tooltip_theme()
    gpu.state.blend_set('ALPHA')
    try:
        card_radius = 7.0 * scale
        _draw_rounded(None, x, y, box_w, box_h, card_radius, outline)
        _draw_rounded(None, x + 1, y + 1, box_w - 2, box_h - 2, card_radius - 1, background)
        image_x = x + (box_w - img_w) * 0.5
        image_y = y + pad
        _draw_rounded(texture, image_x, image_y, img_w, img_h, 4.0 * scale)
        blf_module = _fbp_import_blf(gpu)
        if blf_module is not None and lines:
            dim = (text_color[0], text_color[1], text_color[2], 0.72)
            text_y = image_y + img_h + pad * 0.5
            for offset, line in enumerate(reversed(lines)):
                color = text_color if offset == len(lines) - 1 else dim
                _gpu_text(blf_module, _clip_text(blf_module, line, box_w - pad * 2, text_size),
                          x + pad, text_y + offset * line_h + line_h * 0.25, text_size, color)
    except FBP_DATA_ERRORS:
        pass
    finally:
        gpu.state.blend_set('NONE')


def _clip_text(blf_module, text, max_width, size):
    try:
        blf_module.size(0, int(size))
        if blf_module.dimensions(0, text)[0] <= max_width:
            return text
        while text and blf_module.dimensions(0, text + "…")[0] > max_width:
            text = text[:-1]
        return text + "…"
    except FBP_DATA_ERRORS:
        return text


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------

def _space_class_for(area):
    try:
        return type(area.spaces.active)
    except (AttributeError, TypeError):
        return None


def _main_region(area):
    for region in area.regions:
        if region.type == 'WINDOW' and region.width > 1 and region.height > 1:
            return region
    return None


def _overlaps_y(area, mouse_y):
    return area.y <= mouse_y <= area.y + area.height


def _draw_target(context, mouse_x, mouse_y):
    """Pick the area/region that will show the preview and where to dock it.

    * Sidebar of a 3D View (or any editor): the editor's own main region,
      just outside the sidebar edge.
    * A list in a narrow editor such as Properties > Tool: the neighbouring
      editor (usually the 3D View) on the left, or on the right when the
      list is on the left of the screen, right against the shared border.
    * Otherwise the hovered region itself, beside the cursor.
    Returns ``(area, region, (side, edge_x))`` in window pixels.
    """
    area = context.area
    hovered = context.region
    if hovered is not None and hovered.type == 'UI':
        main = _main_region(area)
        if main is not None:
            if str(getattr(hovered, "alignment", "") or "") == 'LEFT':
                return area, main, ('RIGHT', hovered.x + hovered.width)
            return area, main, ('LEFT', hovered.x)
    screen = getattr(context, "screen", None) or getattr(context.window, "screen", None)
    left, right = [], []
    for other in getattr(screen, "areas", ()):
        if other.as_pointer() == area.as_pointer():
            continue
        main = _main_region(other)
        if main is None:
            continue
        # Prefer an editor that shares the border with the list, then one
        # level with the cursor, then the largest (a 3D View rather than the
        # thin Timeline under it): the preview is clamped inside it anyway.
        if other.x + other.width <= area.x + 2:
            touching = abs(other.x + other.width - area.x) <= 2
        elif other.x >= area.x + area.width - 2:
            touching = abs(other.x - (area.x + area.width)) <= 2
        else:
            continue
        score = (touching, main.height >= 200, _overlaps_y(other, mouse_y), main.width * main.height)
        (left if other.x < area.x else right).append((score, other, main))
    if left:
        _score, other, main = max(left, key=lambda item: item[0])
        return other, main, ('LEFT', area.x)
    if right:
        _score, other, main = max(right, key=lambda item: item[0])
        return other, main, ('RIGHT', area.x + area.width)
    return area, (_main_region(area) or hovered), ('SELF', 0)


class FBP_OT_RowHoverPreview(Operator):
    bl_idname = "fbp.row_hover_preview"
    bl_label = "Row Hover Preview"
    bl_description = "Show a larger thumbnail while the mouse rests on a list row"
    bl_options = {'INTERNAL'}

    _handle = None
    _space = None
    _draw_area = None

    def invoke(self, context, event):
        payload = _STATE.get("payload")
        area = getattr(context, "area", None)
        if not payload or area is None:
            return {'CANCELLED'}
        try:
            target_area, draw_region, dock = _draw_target(context, event.mouse_x, event.mouse_y)
        except FBP_DATA_ERRORS:
            return {'CANCELLED'}
        space_cls = _space_class_for(target_area)
        if draw_region is None or space_cls is None or not hasattr(space_cls, "draw_handler_add"):
            return {'CANCELLED'}
        try:
            self._handle = space_cls.draw_handler_add(_draw_callback, (), draw_region.type, 'POST_PIXEL')
        except FBP_DATA_ERRORS:
            return {'CANCELLED'}
        self._space = space_cls
        self._region_type = draw_region.type
        _STATE["handle"] = (space_cls, self._handle, draw_region.type)
        _STATE["draw_area_ptr"] = target_area.as_pointer()
        _STATE["dock"] = dock
        _STATE["draw_area"] = target_area
        self._draw_area = target_area
        _STATE["running"] = True
        _STATE["anchor"] = (event.mouse_x, event.mouse_y)
        _STATE["last_mouse"] = (event.mouse_x, event.mouse_y)
        context.window_manager.modal_handler_add(self)
        _tag_area(target_area)
        return {'RUNNING_MODAL'}

    def _finish(self):
        _STATE["running"] = False
        _STATE["payload"] = None
        _STATE["anchor"] = None
        _STATE["texture"] = None
        _STATE["texture_key"] = None
        _STATE["draw_area"] = None
        _STATE["draw_area_ptr"] = None
        _STATE["dock"] = None
        _remove_draw_handler()
        self._handle = None
        if self._draw_area is not None:
            _tag_area(self._draw_area)
        self._draw_area = None

    def modal(self, context, event):
        if not _STATE["running"] or _STATE.get("payload") is None:
            self._finish()
            return {'CANCELLED', 'PASS_THROUGH'}
        if event.type in {'TIMER', 'TIMER_REPORT', 'NONE'} or event.type.startswith('TIMER'):
            return {'PASS_THROUGH'}
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            _STATE["last_mouse"] = (event.mouse_x, event.mouse_y)
            anchor = _STATE.get("anchor") or (event.mouse_x, event.mouse_y)
            limit = _MOVE_THRESHOLD_PX * _ui_scale()
            if abs(event.mouse_x - anchor[0]) > limit or abs(event.mouse_y - anchor[1]) > limit:
                self._finish()
                return {'CANCELLED', 'PASS_THROUGH'}
            return {'PASS_THROUGH'}
        # Any click, wheel, key or window change closes it like a tooltip.
        self._finish()
        return {'CANCELLED', 'PASS_THROUGH'}

    def cancel(self, _context):
        self._finish()


def _remove_draw_handler():
    record = _STATE.get("handle")
    _STATE["handle"] = None
    if not record:
        return
    space_cls, handle, region_type = record
    try:
        space_cls.draw_handler_remove(handle, region_type)
    except FBP_DATA_ERRORS:
        pass


classes = (FBP_OT_RowHoverPreview,)


def register():
    from .registration import register_classes
    register_classes(classes)


def unregister():
    from .registration import unregister_classes
    _STATE["running"] = False
    _STATE["payload"] = None
    _STATE["texture"] = None
    _STATE["pending"] = None
    _remove_draw_handler()
    try:
        if bpy.app.timers.is_registered(_start_preview_operator):
            bpy.app.timers.unregister(_start_preview_operator)
    except FBP_DATA_ERRORS:
        pass
    unregister_classes(classes)
