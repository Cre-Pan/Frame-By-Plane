"""Cutout Plane workflow for pose/expression replacement animation.

A Cutout Plane owns one renderable plane and a library of independent image
files.  The custom integer property ``[\"fbp_drawing_index\"]`` selects which
image is bound to the material: zero is a shared transparent image and 1..N map
onto ``Object.fbp_images``.  The property is keyframed on the rig with Constant
interpolation, while the material image is swapped only when the evaluated value
actually changes.
"""


import os
import time
import uuid
from collections import deque
from pathlib import Path

import bpy
import bpy.utils.previews
from bpy.props import CollectionProperty, EnumProperty, StringProperty
from bpy.types import Operator, UIList
from bpy_extras.io_utils import ImportHelper

from .constants import preview_collections
from .layers import (
    load_preview, get_selected_rigs, sync_layer_collection,
    thumbnail_background_state, invalidate_preview_path,
)
from .path_utils import natural_sort_key, is_supported_media_file, is_supported_video_file, is_technical_map_file
from .runtime import (
    fbp_find_action_fcurve,
    fbp_obj_runtime_key,
    fbp_set_rna_property_silent,
    fbp_render_mutation_blocked,
    fbp_warn,
)


DRAWING_INDEX_KEY = "fbp_drawing_index"
DRAWING_EMPTY_IMAGE = "FBP_Drawing_Empty"
DRAWING_TEXTURE_NODE = "FBP_Native_Media_Texture"
DRAWING_PREVIEW_COLLECTION = "fbp_drawing_previews"
DRAWING_MANAGED_IMAGE_KEY = "fbp_cutout_buffer_managed"
_DRAWING_SYNC_STATES: dict[object, tuple[int, int]] = {}
_DRAWING_KEY_DEADLINES: dict[object, float] = {}
_DRAWING_KEY_REQUESTS: dict[object, tuple[int, int]] = {}
_DRAWING_SCENE_RIG_CACHE: dict[object, tuple[int, int, float, tuple[str, ...]]] = {}
_DRAWING_IMAGE_PATH_CACHE = globals().get("_DRAWING_IMAGE_PATH_CACHE", {})
if not isinstance(_DRAWING_IMAGE_PATH_CACHE, dict):
    _DRAWING_IMAGE_PATH_CACHE = {}
_DRAWING_IMAGE_PATH_CACHE_INDEXED = bool(
    globals().get("_DRAWING_IMAGE_PATH_CACHE_INDEXED", False)
)
_DRAWING_IMAGE_PATH_COUNT = int(
    globals().get("_DRAWING_IMAGE_PATH_COUNT", -1) or -1
)
_DRAWING_PREVIEW_CACHE_LIMIT = 256
_DRAWING_PREVIEW_KEYS = deque()
_DRAWING_SCENE_CACHE_SECONDS = 1.5
_DRAWING_PREVIEW_QUEUE = deque()
_DRAWING_PREVIEW_QUEUED: set[tuple[str, str]] = set()
_DRAWING_PREVIEW_READY: set[tuple[str, str]] = set()
_DRAWING_PREVIEW_READY_ORDER = deque()
_DRAWING_IMAGE_HOT = deque(maxlen=24)
_DRAWING_BUFFER_TRIM_DELAY = 1.5
_DRAWING_PREVIEW_BATCH = 3
_DRAWING_PREVIEW_QUEUE_LIMIT = 128
_DRAWING_PREVIEW_READY_LIMIT = 512
_DRAWING_PREVIEW_REDRAW_INTERVAL = 0.08
_DRAWING_PREVIEW_LAST_REDRAW = 0.0


def fbp_is_drawing_rig(rig) -> bool:
    try:
        return bool(rig and getattr(rig, "is_fbp_control", False) and getattr(rig, "fbp_is_drawing_plane", False))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _drawing_key(rig):
    return fbp_obj_runtime_key(rig) or str(getattr(rig, "name", "") or "")


def clear_drawing_runtime_cache():
    global _DRAWING_IMAGE_PATH_CACHE_INDEXED, _DRAWING_IMAGE_PATH_COUNT
    _DRAWING_SYNC_STATES.clear()
    _DRAWING_KEY_DEADLINES.clear()
    _DRAWING_KEY_REQUESTS.clear()
    _DRAWING_SCENE_RIG_CACHE.clear()
    _DRAWING_IMAGE_PATH_CACHE.clear()
    _DRAWING_IMAGE_PATH_CACHE_INDEXED = False
    _DRAWING_IMAGE_PATH_COUNT = -1
    _DRAWING_IMAGE_HOT.clear()
    _DRAWING_PREVIEW_QUEUE.clear()
    _DRAWING_PREVIEW_QUEUED.clear()


def clear_drawing_preview_runtime_state():
    _DRAWING_PREVIEW_KEYS.clear()
    _DRAWING_PREVIEW_QUEUE.clear()
    _DRAWING_PREVIEW_QUEUED.clear()
    _DRAWING_PREVIEW_READY.clear()
    _DRAWING_PREVIEW_READY_ORDER.clear()


def _drawing_playback_active():
    """Return True while any visible Blender screen is playing animation.

    Buffer eviction touches native image/GPU caches and can be noticeably more
    expensive than the actual Cutout Plane frame swap. Keep the trim timer
    pending during playback instead of repeatedly freeing images that the next
    frame may need again.
    """
    try:
        window_manager = getattr(getattr(bpy, "context", None), "window_manager", None)
        for window in getattr(window_manager, "windows", ()) or ():
            screen = getattr(window, "screen", None)
            if screen and bool(getattr(screen, "is_animation_playing", False)):
                return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return False


def clear_drawing_composite_previews():
    clear_drawing_preview_runtime_state()
    pcoll = preview_collections.pop(DRAWING_PREVIEW_COLLECTION, None)
    if pcoll is not None:
        try:
            bpy.utils.previews.remove(pcoll)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass


def _drawing_preview_collection():
    pcoll = preview_collections.get(DRAWING_PREVIEW_COLLECTION)
    if pcoll is None:
        pcoll = bpy.utils.previews.new()
        preview_collections[DRAWING_PREVIEW_COLLECTION] = pcoll
    return pcoll


def _remember_drawing_preview(pcoll, cache_key):
    """Keep composited previews bounded without invalidating the whole cache."""
    _DRAWING_PREVIEW_KEYS.append(cache_key)
    while len(_DRAWING_PREVIEW_KEYS) > _DRAWING_PREVIEW_CACHE_LIMIT:
        oldest = _DRAWING_PREVIEW_KEYS.popleft()
        if oldest == cache_key:
            continue
        try:
            del pcoll[oldest]
        except (KeyError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass


def _checker_color(x, y, width, height):
    cell = max(4, min(width, height) // 8)
    light = 0.68
    dark = 0.38
    value = light if ((x // cell) + (y // cell)) % 2 == 0 else dark
    return value, value, value


def load_empty_drawing_preview(rig, scene=None):
    """Return a lightweight Empty preview using the global thumbnail setting."""
    del rig
    enabled, background = thumbnail_background_state(scene)
    color_key = tuple(round(value, 4) for value in background[:3])
    cache_key = f"__EMPTY__|bg{int(enabled)}|{color_key}|v3"
    pcoll = _drawing_preview_collection()
    if cache_key in pcoll:
        return pcoll[cache_key]
    width = height = 64
    output = [0.0] * (width * height * 4)
    try:
        for y in range(height):
            for x in range(width):
                offset = (y * width + x) * 4
                if enabled:
                    red, green, blue = background[:3]
                else:
                    red, green, blue = _checker_color(x, y, width, height)
                output[offset:offset + 4] = (red, green, blue, 1.0)
        preview = pcoll.new(cache_key)
        preview.image_size = (width, height)
        preview.image_pixels_float = output
        _remember_drawing_preview(pcoll, cache_key)
        return preview
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError):
        try:
            del pcoll[cache_key]
        except (KeyError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        return None


def _drawing_preview_key(image_path, scene=None):
    try:
        absolute = os.path.normcase(os.path.abspath(bpy.path.abspath(image_path)))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OSError):
        absolute = str(image_path or "")
    scene_name = str(getattr(scene, "name", "") or "") if scene else ""
    return absolute, scene_name


def _tag_drawing_preview_redraw(*, force=False):
    """Refresh Cutout thumbnail UI at a bounded rate while queues are busy."""
    global _DRAWING_PREVIEW_LAST_REDRAW
    now = time.monotonic()
    if not force and now - _DRAWING_PREVIEW_LAST_REDRAW < _DRAWING_PREVIEW_REDRAW_INTERVAL:
        return False
    _DRAWING_PREVIEW_LAST_REDRAW = now
    try:
        window_manager = getattr(bpy.context, "window_manager", None)
        for window in getattr(window_manager, "windows", ()) or ():
            screen = getattr(window, "screen", None)
            for area in getattr(screen, "areas", ()) or ():
                if getattr(area, "type", "") != "VIEW_3D":
                    continue
                ui_regions = [
                    region for region in (getattr(area, "regions", ()) or ())
                    if getattr(region, "type", "") == "UI"
                ]
                if ui_regions:
                    for region in ui_regions:
                        region.tag_redraw()
                else:
                    area.tag_redraw()
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _mark_drawing_preview_ready(key):
    if key in _DRAWING_PREVIEW_READY:
        try:
            _DRAWING_PREVIEW_READY_ORDER.remove(key)
        except ValueError:
            pass
    _DRAWING_PREVIEW_READY.add(key)
    _DRAWING_PREVIEW_READY_ORDER.append(key)
    while len(_DRAWING_PREVIEW_READY_ORDER) > _DRAWING_PREVIEW_READY_LIMIT:
        oldest = _DRAWING_PREVIEW_READY_ORDER.popleft()
        _DRAWING_PREVIEW_READY.discard(oldest)


def _drawing_preview_queue_timer():
    processed = 0
    while _DRAWING_PREVIEW_QUEUE and processed < _DRAWING_PREVIEW_BATCH:
        image_path, scene_name = _DRAWING_PREVIEW_QUEUE.popleft()
        key = (image_path, scene_name)
        _DRAWING_PREVIEW_QUEUED.discard(key)
        scene = bpy.data.scenes.get(scene_name) if scene_name else getattr(bpy.context, "scene", None)
        try:
            load_preview(image_path, scene=scene, force_square=True)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OSError):
            pass
        # Mark the request as attempted even when Blender cannot build the
        # thumbnail. Missing files are already throttled by layers.load_preview;
        # keeping the key ready avoids spawning a new timer on every UI redraw.
        _mark_drawing_preview_ready(key)
        processed += 1
    if processed:
        _tag_drawing_preview_redraw(force=not _DRAWING_PREVIEW_QUEUE)
    return 0.03 if _DRAWING_PREVIEW_QUEUE else None


def _queue_drawing_preview(image_path, scene=None):
    if not image_path:
        return False
    key = _drawing_preview_key(image_path, scene)
    if key in _DRAWING_PREVIEW_READY or key in _DRAWING_PREVIEW_QUEUED:
        return False
    if len(_DRAWING_PREVIEW_QUEUE) >= _DRAWING_PREVIEW_QUEUE_LIMIT:
        return False
    _DRAWING_PREVIEW_QUEUED.add(key)
    _DRAWING_PREVIEW_QUEUE.append((key[0], key[1]))
    try:
        from .safe_tasks import schedule_once
        schedule_once("drawing.preview.queue", _drawing_preview_queue_timer, first_interval=0.0)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        # Do not strand a key in the queued set when timer registration fails.
        _DRAWING_PREVIEW_QUEUED.discard(key)
        try:
            _DRAWING_PREVIEW_QUEUE.remove((key[0], key[1]))
        except ValueError:
            pass
        return False
    return True


def invalidate_drawing_preview_path(image_path):
    key_path = _drawing_preview_key(image_path, None)[0]
    stale = {key for key in _DRAWING_PREVIEW_READY if key[0] == key_path}
    _DRAWING_PREVIEW_READY.difference_update(stale)
    if stale:
        retained_ready = [key for key in _DRAWING_PREVIEW_READY_ORDER if key not in stale]
        _DRAWING_PREVIEW_READY_ORDER.clear()
        _DRAWING_PREVIEW_READY_ORDER.extend(retained_ready)
    queued = {key for key in _DRAWING_PREVIEW_QUEUED if key[0] == key_path}
    _DRAWING_PREVIEW_QUEUED.difference_update(queued)
    if stale or queued:
        retained = [entry for entry in _DRAWING_PREVIEW_QUEUE if entry[0] != key_path]
        _DRAWING_PREVIEW_QUEUE.clear()
        _DRAWING_PREVIEW_QUEUE.extend(retained)
    return invalidate_preview_path(image_path)


def load_drawing_preview(rig, image_path, scene=None, *, deferred=False):
    """Return an aspect-correct preview, optionally loading it progressively."""
    del rig
    if not image_path:
        return None
    key = _drawing_preview_key(image_path, scene)
    if deferred and key not in _DRAWING_PREVIEW_READY:
        _queue_drawing_preview(image_path, scene)
        return None
    preview = load_preview(image_path, scene=scene, force_square=True)
    if preview is not None:
        _mark_drawing_preview_ready(key)
    return preview


def _find_empty_image():
    """Return only an image explicitly owned as the shared Drawing empty state."""
    try:
        image = bpy.data.images.get(DRAWING_EMPTY_IMAGE)
        if image is not None and bool(image.get("fbp_drawing_empty", False)):
            return image
        for candidate in bpy.data.images:
            if bool(candidate.get("fbp_drawing_empty", False)):
                return candidate
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
        return None
    return None


def _ensure_empty_image():
    image = _find_empty_image()
    if image is not None:
        # This function is reached on every frame that evaluates drawing 0.
        # Never rewrite pixels or ID properties after the image is initialized.
        return image
    if fbp_render_mutation_blocked():
        return None
    image = bpy.data.images.new(DRAWING_EMPTY_IMAGE, width=1, height=1, alpha=True)
    try:
        image.generated_color = (0.0, 0.0, 0.0, 0.0)
        if len(image.pixels) >= 4:
            image.pixels[0:4] = (0.0, 0.0, 0.0, 0.0)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        image.use_fake_user = True
        image["fbp_owned"] = True
        image["fbp_drawing_empty"] = True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
        pass
    return image


def _safe_socket(node, names):
    lowered = tuple(str(name).lower() for name in names)
    for socket in getattr(node, "inputs", ()):
        text = f"{getattr(socket, 'name', '')} {getattr(socket, 'identifier', '')}".lower()
        if all(name in text for name in lowered):
            return socket
    return None


def fbp_build_drawing_material(mat, image, *, interpolation="Closest", use_emission=True, opacity=1.0):
    from .materials import configure_fbp_material_surface

    if mat is None:
        mat = bpy.data.materials.new("FBP_Cutout")
    mat["fbp_owned"] = True
    mat["fbp_drawing_material"] = True
    mat["fbp_use_emission"] = bool(use_emission)
    mat["fbp_opacity"] = max(0.0, min(1.0, float(opacity)))
    mat.use_nodes = True
    configure_fbp_material_surface(mat, opacity, has_alpha=True)

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output = nodes.new(type="ShaderNodeOutputMaterial")
    output.name = "FBP_Native_Output"
    output.label = "Frame by Plane Output"
    output.location = (560, 0)

    uv_map = nodes.new(type="ShaderNodeUVMap")
    uv_map.name = "FBP_Drawing_UV"
    uv_map.label = "Drawing UV"
    uv_map.location = (-660, 80)
    uv_map.uv_map = "UVMap"

    texture = nodes.new(type="ShaderNodeTexImage")
    texture.name = DRAWING_TEXTURE_NODE
    texture.label = "Frame by Plane Cutout"
    texture.location = (-440, 80)
    texture["fbp_native_sequence_node"] = True
    texture["fbp_drawing_image_node"] = True
    texture.image = image or _ensure_empty_image()
    try:
        texture.interpolation = interpolation
        texture.extension = "EXTEND"
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    links.new(uv_map.outputs.get("UV") or uv_map.outputs[0], texture.inputs.get("Vector") or texture.inputs[0])
    color_source = texture.outputs.get("Color") or texture.outputs[0]
    alpha_source = texture.outputs.get("Alpha") or texture.outputs[-1]
    opacity = max(0.0, min(1.0, float(opacity)))
    if opacity < 0.999:
        multiply = nodes.new(type="ShaderNodeMath")
        multiply.name = "FBP_Opacity"
        multiply.label = "Opacity"
        multiply["fbp_internal_opacity_node"] = True
        multiply.operation = "MULTIPLY"
        multiply.location = (-130, -165)
        multiply.inputs[1].default_value = opacity
        links.new(alpha_source, multiply.inputs[0])
        alpha_source = multiply.outputs[0]

    if use_emission:
        shader = nodes.new(type="ShaderNodeEmission")
        shader.name = "FBP_Native_Emission"
        shader.location = (120, 90)
        color_socket = _safe_socket(shader, ("color",)) or shader.inputs[0]
        links.new(color_source, color_socket)
        transparent = nodes.new(type="ShaderNodeBsdfTransparent")
        transparent.name = "FBP_Native_Transparent"
        transparent.location = (110, -160)
        mix = nodes.new(type="ShaderNodeMixShader")
        mix.name = "FBP_Native_Alpha_Mix"
        mix.location = (340, 0)
        links.new(alpha_source, mix.inputs[0])
        links.new(transparent.outputs[0], mix.inputs[1])
        links.new(shader.outputs[0], mix.inputs[2])
        links.new(mix.outputs[0], output.inputs[0])
    else:
        shader = nodes.new(type="ShaderNodeBsdfPrincipled")
        shader.name = "FBP_Native_Principled"
        shader.location = (120, 90)
        base = _safe_socket(shader, ("base", "color")) or shader.inputs[0]
        links.new(color_source, base)
        alpha_socket = _safe_socket(shader, ("alpha",))
        if alpha_socket:
            links.new(alpha_source, alpha_socket)
        roughness = _safe_socket(shader, ("roughness",))
        if roughness:
            roughness.default_value = 1.0
        specular = _safe_socket(shader, ("specular",)) or _safe_socket(shader, ("specular", "ior", "level"))
        if specular:
            specular.default_value = 0.0
        links.new(shader.outputs[0], output.inputs[0])
    return mat


def fbp_rebuild_drawing_material(mat, *, use_emission=None, opacity=None):
    if not mat or not bool(mat.get("fbp_drawing_material", False)):
        return None
    texture = mat.node_tree.nodes.get(DRAWING_TEXTURE_NODE) if mat.node_tree else None
    image = getattr(texture, "image", None) or _ensure_empty_image()
    interpolation = getattr(texture, "interpolation", "Closest") if texture else "Closest"
    if use_emission is None:
        use_emission = bool(mat.get("fbp_use_emission", True))
    if opacity is None:
        opacity = float(mat.get("fbp_opacity", 1.0))
    return fbp_build_drawing_material(
        mat,
        image,
        interpolation=interpolation,
        use_emission=use_emission,
        opacity=opacity,
    )


def _drawing_material(rig):
    plane = getattr(rig, "fbp_plane_target", None) if rig else None
    if not plane or not getattr(plane, "data", None):
        return None
    for material in getattr(plane.data, "materials", ()):
        try:
            if material and bool(material.get("fbp_drawing_material", False)):
                return material
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return None


def fbp_ensure_drawing_material(rig):
    """Repair the owned Cutout Plane material outside render/depsgraph work."""
    if not fbp_is_drawing_rig(rig) or fbp_render_mutation_blocked():
        return False
    plane = getattr(rig, "fbp_plane_target", None)
    if not plane or not getattr(plane, "data", None):
        return False
    material = _drawing_material(rig)
    texture = None
    if material and getattr(material, "node_tree", None):
        texture = material.node_tree.nodes.get(DRAWING_TEXTURE_NODE)
    if texture and getattr(texture, "type", "") == "TEX_IMAGE":
        return True

    index = fbp_drawing_index(rig)
    item = rig.fbp_images[index - 1] if 0 < index <= len(rig.fbp_images) else None
    image = _image_for_item(item) if item else _ensure_empty_image()
    material = fbp_build_drawing_material(
        material,
        image or _ensure_empty_image(),
        interpolation=getattr(rig, "fbp_interpolation", "Closest"),
        use_emission=bool(getattr(rig, "fbp_use_emission", True)),
        opacity=float(getattr(rig, "fbp_opacity", 1.0)),
    )
    if not any(slot is material for slot in plane.data.materials):
        plane.data.materials.append(material)
    try:
        from .geometry_nodes import fbp_reapply_all_effects
        fbp_reapply_all_effects(rig)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return True


def _drawing_texture(rig):
    material = _drawing_material(rig)
    if not material or not material.node_tree:
        return None
    node = material.node_tree.nodes.get(DRAWING_TEXTURE_NODE)
    return node if node and getattr(node, "type", "") == "TEX_IMAGE" else None


def _normalized_image_path(image_path):
    if not image_path:
        return ""
    try:
        return os.path.normcase(os.path.abspath(bpy.path.abspath(image_path)))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OSError):
        return ""


def _remember_loaded_image_path(image_path, image):
    """Store a name-only Cutout image lookup without retaining RNA pointers."""
    global _DRAWING_IMAGE_PATH_COUNT
    key = _normalized_image_path(image_path)
    try:
        image_name = str(getattr(image, "name", "") or "")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        image_name = ""
    if not key or not image_name:
        return False
    _DRAWING_IMAGE_PATH_CACHE[key] = image_name
    try:
        _DRAWING_IMAGE_PATH_COUNT = len(bpy.data.images)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return True


def _ensure_loaded_image_path_index():
    """Index loaded image paths once and rebuild only when the ID count changes."""
    global _DRAWING_IMAGE_PATH_CACHE_INDEXED, _DRAWING_IMAGE_PATH_COUNT
    try:
        image_count = len(bpy.data.images)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False
    if _DRAWING_IMAGE_PATH_CACHE_INDEXED and image_count == _DRAWING_IMAGE_PATH_COUNT:
        return True

    _DRAWING_IMAGE_PATH_CACHE.clear()
    for image in getattr(bpy.data, "images", ()):
        try:
            key = _normalized_image_path(str(getattr(image, "filepath", "") or ""))
            image_name = str(getattr(image, "name", "") or "")
            if key and image_name and key not in _DRAWING_IMAGE_PATH_CACHE:
                _DRAWING_IMAGE_PATH_CACHE[key] = image_name
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    _DRAWING_IMAGE_PATH_COUNT = image_count
    _DRAWING_IMAGE_PATH_CACHE_INDEXED = True
    return True


def _loaded_images_by_path():
    """Resolve the cached name index once for batch imports."""
    _ensure_loaded_image_path_index()
    indexed = {}
    for key, image_name in tuple(_DRAWING_IMAGE_PATH_CACHE.items()):
        image = bpy.data.images.get(str(image_name or ""))
        try:
            if image is not None and _normalized_image_path(getattr(image, "filepath", "")) == key:
                indexed[key] = image
            else:
                _DRAWING_IMAGE_PATH_CACHE.pop(key, None)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            _DRAWING_IMAGE_PATH_CACHE.pop(key, None)
    return indexed


def _loaded_image_for_path(image_path):
    key = _normalized_image_path(image_path)
    if not key:
        return None
    _ensure_loaded_image_path_index()
    image_name = str(_DRAWING_IMAGE_PATH_CACHE.get(key, "") or "")
    image = bpy.data.images.get(image_name) if image_name else None
    try:
        if image is not None and _normalized_image_path(getattr(image, "filepath", "")) == key:
            return image
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    _DRAWING_IMAGE_PATH_CACHE.pop(key, None)

    # Image paths can be edited without changing the number of Image IDs. A
    # targeted fallback scan self-heals that rare case without rebuilding the
    # complete index for every Cutout frame or library entry.
    for candidate in getattr(bpy.data, "images", ()):
        try:
            if _normalized_image_path(getattr(candidate, "filepath", "")) == key:
                _remember_loaded_image_path(key, candidate)
                return candidate
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return None


def _drawing_active_image_names():
    active = set()
    try:
        for scene in bpy.data.scenes:
            for rig in _drawing_rigs_for_scene(scene):
                texture = _drawing_texture(rig)
                image = getattr(texture, "image", None) if texture else None
                if image is not None:
                    active.add(str(getattr(image, "name", "") or ""))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return active


def _touch_drawing_image(image):
    name = str(getattr(image, "name", "") or "") if image else ""
    if not name:
        return
    try:
        _DRAWING_IMAGE_HOT.remove(name)
    except ValueError:
        pass
    _DRAWING_IMAGE_HOT.append(name)


def _free_managed_cutout_buffer(image, image_path=""):
    """Drop CPU/GPU buffers while retaining the persistent Image datablock."""
    if image is None or fbp_render_mutation_blocked():
        return False
    try:
        if not bool(image.get(DRAWING_MANAGED_IMAGE_KEY, False)):
            return False
        if bool(getattr(image, "packed_file", None)) or bool(getattr(image, "is_dirty", False)):
            return False
        if str(getattr(image, "source", "") or "") == "GENERATED":
            return False
        absolute = os.path.abspath(bpy.path.abspath(image_path)) if image_path else ""
        if not absolute or not os.path.isfile(absolute):
            return False
        try:
            image.gl_free()
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        if bool(getattr(image, "has_data", False)):
            try:
                image.buffers_free()
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, OSError):
        return False


def _release_cutout_image_if_unused(image, image_path="", *, managed=False):
    """Release an unused Cutout image buffer without deleting its datablock.

    Blender 5.1 can become unstable when an add-on removes Image datablocks
    around Undo, file replacement or native cache teardown. Match the native
    sequence backend safety policy: detach the library slot, release only the
    managed buffers while Blender is confirmed idle, and leave the zero-user
    Image to Blender's explicit orphan purge.
    """
    if image is None or not managed or fbp_render_mutation_blocked():
        return False
    try:
        if bool(getattr(image, "packed_file", None)) or bool(getattr(image, "is_dirty", False)):
            return False
        if str(getattr(image, "source", "") or "") == "GENERATED":
            return False
        absolute = os.path.abspath(bpy.path.abspath(image_path)) if image_path else ""
        if not absolute or not os.path.isfile(absolute):
            return False
        external_users = int(getattr(image, "users", 0) or 0) - int(bool(getattr(image, "use_fake_user", False)))
        if external_users > 0:
            return False
        try:
            image.gl_free()
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        if bool(getattr(image, "has_data", False)):
            try:
                image.buffers_free()
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OSError):
        return False


def _drawing_buffer_trim_timer():
    if fbp_render_mutation_blocked() or _drawing_playback_active():
        # Returning a positive interval keeps schedule_once's deduplication key
        # alive and prevents one new global scan from being queued each frame.
        # Native image buffers must also remain untouched while Blender renders.
        return 0.75
    active = _drawing_active_image_names()
    hot = set(_DRAWING_IMAGE_HOT)
    candidates = {}
    expected_users = {}
    for scene in getattr(bpy.data, "scenes", ()):
        for rig in _drawing_rigs_for_scene(scene):
            texture = _drawing_texture(rig)
            texture_image = getattr(texture, "image", None) if texture else None
            texture_name = str(getattr(texture_image, "name", "") or "") if texture_image else ""
            if texture_name:
                expected_users[texture_name] = expected_users.get(texture_name, 0) + 1
            for item in getattr(rig, "fbp_images", ()):
                try:
                    image = getattr(item, "image", None)
                    if image is None:
                        continue
                    name = str(getattr(image, "name", "") or "")
                    if not name:
                        continue
                    expected_users[name] = expected_users.get(name, 0) + 1
                    if bool(getattr(item, "managed_image", False)):
                        candidates[name] = (image, item)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    continue
    for name, (image, item) in candidates.items():
        try:
            if name in active or name in hot:
                continue
            if bool(getattr(image, "packed_file", None)) or bool(getattr(image, "is_dirty", False)):
                continue
            if str(getattr(image, "source", "") or "") == "GENERATED":
                continue
            allowed_users = int(expected_users.get(name, 0)) + int(bool(getattr(image, "use_fake_user", False)))
            if int(getattr(image, "users", allowed_users) or 0) > allowed_users:
                # The Image is also used outside Cutout Plane; do not evict a
                # buffer that another material/editor may need immediately.
                continue
            path = str(getattr(item, "filepath", "") or "")
            absolute = os.path.abspath(bpy.path.abspath(path)) if path else ""
            if not absolute or not os.path.isfile(absolute):
                continue
            try:
                image.gl_free()
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
            if bool(getattr(image, "has_data", False)):
                try:
                    image.buffers_free()
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OSError):
            continue
    return None


def _schedule_drawing_buffer_trim():
    try:
        from .safe_tasks import schedule_once
        return bool(schedule_once(
            "drawing.buffer.trim",
            _drawing_buffer_trim_timer,
            first_interval=_DRAWING_BUFFER_TRIM_DELAY,
        ))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _image_for_item(item, *, allow_load=None):
    if item is None:
        return None
    try:
        image = getattr(item, "image", None)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        image = None
    if image is not None:
        return image
    image_name = str(getattr(item, "image_name", "") or "")
    image = bpy.data.images.get(image_name) if image_name else None
    if image is None:
        image = _loaded_image_for_path(str(getattr(item, "filepath", "") or ""))
    if image is not None:
        try:
            item.image = image
            item.image_name = image.name
            width, height = (int(value) for value in image.size)
            item.source_width = max(0, width)
            item.source_height = max(0, height)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        _touch_drawing_image(image)
        return image
    if allow_load is None:
        allow_load = not fbp_render_mutation_blocked()
    if not allow_load:
        return None
    path = str(getattr(item, "filepath", "") or "")
    absolute = os.path.abspath(bpy.path.abspath(path)) if path else ""
    if not absolute or not os.path.isfile(absolute):
        return None
    try:
        existing = _loaded_image_for_path(absolute)
        image = existing or bpy.data.images.load(absolute, check_existing=True)
        _remember_loaded_image_path(absolute, image)
        item.image = image
        item.image_name = image.name
        if existing is None:
            item.managed_image = True
        try:
            width, height = (int(value) for value in image.size)
            item.source_width = max(0, width)
            item.source_height = max(0, height)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        _touch_drawing_image(image)
        _schedule_drawing_buffer_trim()
        return image
    except (RuntimeError, OSError, AttributeError, ReferenceError, TypeError, ValueError) as exc:
        fbp_warn(f"Could not load Cutout Plane image: {absolute}", exc)
        return None


def fbp_refresh_drawing_aspect_warning(rig):
    """Recompute the fixed-plane aspect warning from cached dimensions."""
    if not fbp_is_drawing_rig(rig):
        return False
    try:
        source_width = int(rig.get("fbp_source_width", 0) or 0)
        source_height = int(rig.get("fbp_source_height", 0) or 0)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
        source_width = source_height = 0
    reference = (source_width / source_height) if source_width > 0 and source_height > 0 else None
    first_size = None
    mixed = False
    for item in getattr(rig, "fbp_images", ()):
        try:
            width = int(getattr(item, "source_width", 0) or 0)
            height = int(getattr(item, "source_height", 0) or 0)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            width = height = 0
        if width <= 0 or height <= 0:
            image = getattr(item, "image", None)
            if image is not None:
                try:
                    width, height = (int(value) for value in image.size)
                    item.source_width = max(0, width)
                    item.source_height = max(0, height)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    width = height = 0
        if width <= 0 or height <= 0:
            continue
        if first_size is None:
            first_size = (width, height)
        if reference is not None and abs((width / height) - reference) > 1e-4:
            mixed = True
            break
    if reference is None and first_size:
        try:
            from .native_backend import _store_native_aspect_on_rig, _refresh_native_geometry
            _store_native_aspect_on_rig(rig, first_size[0], first_size[1], getattr(rig, "fbp_preview_path", ""))
            _refresh_native_geometry(rig)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, ZeroDivisionError):
            pass
    try:
        previous = bool(rig.get("fbp_drawing_mixed_aspect", False))
        rig["fbp_drawing_mixed_aspect"] = bool(mixed)
        return previous != bool(mixed)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
        return False


def fbp_drawing_count(rig):
    try:
        return len(rig.fbp_images) if fbp_is_drawing_rig(rig) else 0
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return 0


def fbp_drawing_index(rig):
    count = fbp_drawing_count(rig)
    try:
        value = int(rig.get(DRAWING_INDEX_KEY, 0) or 0)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        value = 0
    return max(0, min(count, value))


def fbp_update_drawing_index_ui(rig):
    if not fbp_is_drawing_rig(rig):
        return False
    count = fbp_drawing_count(rig)
    try:
        if DRAWING_INDEX_KEY not in rig:
            rig[DRAWING_INDEX_KEY] = 0
        metadata = rig.id_properties_ui(DRAWING_INDEX_KEY)
        metadata.update(
            min=0,
            max=max(0, count),
            soft_min=0,
            soft_max=max(0, count),
            step=1,
            description="Drawing shown by this plane. 0 is Empty; 1..N select library images.",
        )
        clamped = fbp_drawing_index(rig)
        if int(rig[DRAWING_INDEX_KEY]) != clamped:
            rig[DRAWING_INDEX_KEY] = clamped
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
        return False


def _set_constant_interpolation(rig, frame=None):
    curve = fbp_find_action_fcurve(rig, f'["{DRAWING_INDEX_KEY}"]')
    if curve is None:
        return False
    try:
        changed = False
        for point in curve.keyframe_points:
            if frame is not None and abs(float(point.co[0]) - float(frame)) > 1e-4:
                continue
            if getattr(point, "interpolation", "") != "CONSTANT":
                point.interpolation = "CONSTANT"
            changed = True
        return changed
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError):
        return False


def fbp_keyframe_drawing_index(rig, scene=None):
    if not fbp_is_drawing_rig(rig):
        return False
    scene = scene or getattr(bpy.context, "scene", None)
    frame = int(getattr(scene, "frame_current", 1) or 1)
    try:
        rig.keyframe_insert(
            data_path=f'["{DRAWING_INDEX_KEY}"]',
            frame=frame,
            group="Frame by Plane Drawings",
        )
        _set_constant_interpolation(rig, frame)
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not keyframe Cutout Plane", exc)
        return False


def _drawing_has_driver(rig):
    animation_data = getattr(rig, "animation_data", None) if rig else None
    drivers = getattr(animation_data, "drivers", None) if animation_data else None
    if not drivers:
        return False
    data_path = f'["{DRAWING_INDEX_KEY}"]'
    try:
        return any(
            getattr(curve, "data_path", "") == data_path
            and not bool(getattr(curve, "mute", False))
            for curve in drivers
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return True


def _drawing_animation_fcurves(rig):
    """Return all active Action and NLA F-Curves plus a safety flag."""
    data_path = f'["{DRAWING_INDEX_KEY}"]'
    curves = []
    seen = set()
    safe = True

    def append_curve(curve):
        if curve is None or getattr(curve, "data_path", "") != data_path:
            return
        try:
            key = int(curve.as_pointer())
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            key = id(curve)
        if key not in seen:
            seen.add(key)
            curves.append(curve)

    append_curve(fbp_find_action_fcurve(rig, data_path))
    animation_data = getattr(rig, "animation_data", None) if rig else None
    tracks = getattr(animation_data, "nla_tracks", None) if animation_data else None
    if not tracks:
        return curves, safe
    try:
        from bpy_extras import anim_utils
        for track in tracks:
            for strip in getattr(track, "strips", ()) or ():
                action = getattr(strip, "action", None)
                slot = getattr(strip, "action_slot", None)
                if action is None:
                    continue
                if slot is None:
                    safe = False
                    continue
                channelbag = anim_utils.action_get_channelbag_for_slot(action, slot)
                if channelbag is None:
                    safe = False
                    continue
                for curve in getattr(channelbag, "fcurves", ()) or ():
                    append_curve(curve)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        safe = False
    return curves, safe


def _remap_drawing_keyframes(rig, mapping):
    """Transactionally remap the active Action and every compatible NLA strip."""
    curves, safe = _drawing_animation_fcurves(rig)
    if not safe:
        return False
    snapshots = []
    try:
        for curve in curves:
            for point in curve.keyframe_points:
                snapshots.append((point, float(point.co[1]), str(getattr(point, "interpolation", "CONSTANT"))))
        for curve in curves:
            for point in curve.keyframe_points:
                old_value = int(round(float(point.co[1])))
                point.co[1] = float(int(mapping(old_value)))
                point.interpolation = "CONSTANT"
            curve.update()
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError):
        for point, old_value, interpolation in snapshots:
            try:
                point.co[1] = old_value
                point.interpolation = interpolation
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError):
                pass
        # Re-evaluate every curve after restoring its points. Without this, an
        # exception half-way through a transaction could leave stale handles.
        for curve in curves:
            try:
                curve.update()
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        return False


def _remap_current_drawing(rig, mapping):
    old_value = fbp_drawing_index(rig)
    new_value = max(0, min(fbp_drawing_count(rig), int(mapping(old_value))))
    try:
        rig[DRAWING_INDEX_KEY] = new_value
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
        return False


def fbp_apply_drawing_index(rig, scene=None, *, force=False):
    if not fbp_is_drawing_rig(rig):
        return False
    index = fbp_drawing_index(rig)
    texture = _drawing_texture(rig)
    if texture is None:
        if not fbp_ensure_drawing_material(rig):
            return False
        texture = _drawing_texture(rig)
        if texture is None:
            return False
    item = rig.fbp_images[index - 1] if index > 0 and index <= len(rig.fbp_images) else None
    image = (
        _ensure_empty_image()
        if item is None or bool(getattr(item, "is_empty", False))
        else _image_for_item(item)
    )
    if image is None:
        return False
    changed = False
    try:
        image_changed = getattr(texture, "image", None) is not image
        if force or image_changed:
            texture.image = image
            changed = True
        _touch_drawing_image(image)
        # Scheduling this on every frame caused a full Cutout library scan to
        # repeat throughout playback. A trim is needed only after the bound
        # image actually changes; the timer itself waits until playback stops.
        if image_changed:
            _schedule_drawing_buffer_trim()
        interpolation = getattr(rig, "fbp_interpolation", "Closest")
        if getattr(texture, "interpolation", None) != interpolation:
            texture.interpolation = interpolation
            changed = True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False
    # Selection rows and preview metadata are UI state. During a managed render
    # only the texture image must change; avoiding these extra RNA/ID writes keeps
    # frame callbacks smaller and reduces depsgraph churn.
    if not fbp_render_mutation_blocked():
        try:
            image_path = str(getattr(item, "filepath", "") or "") if item else ""
            if index > 0 and int(getattr(rig, "fbp_images_index", -1)) != index - 1:
                fbp_set_rna_property_silent(rig, "fbp_images_index", index - 1)
            if str(getattr(rig, "fbp_preview_path", "") or "") != image_path:
                rig.fbp_preview_path = image_path
            material = _drawing_material(rig)
            if material and str(material.get("fbp_image_path", "") or "") != image_path:
                material["fbp_image_path"] = image_path
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
            pass
    frame = int(getattr(scene, "frame_current", 1) or 1) if scene else 1
    _DRAWING_SYNC_STATES[_drawing_key(rig)] = (frame, index)
    return changed


def fbp_set_drawing_index(
    rig,
    index,
    *,
    scene=None,
    keyframe=True,
    force=False,
    keyframe_unchanged=False,
):
    if not fbp_is_drawing_rig(rig):
        return False
    fbp_update_drawing_index_ui(rig)
    count = fbp_drawing_count(rig)
    value = max(0, min(count, int(index)))
    previous = fbp_drawing_index(rig)
    try:
        rig[DRAWING_INDEX_KEY] = value
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
        return False
    changed = fbp_apply_drawing_index(rig, scene, force=force)
    keyed = False
    if (
        (previous != value or keyframe_unchanged)
        and keyframe
        and bool(getattr(rig, "fbp_drawing_auto_key", True))
    ):
        keyed = bool(fbp_keyframe_drawing_index(rig, scene))
    return changed or previous != value or keyed


def fbp_select_drawing_from_list(rig, context=None):
    if not fbp_is_drawing_rig(rig):
        return False
    index = int(getattr(rig, "fbp_images_index", 0) or 0) + 1
    return fbp_set_drawing_index(rig, index, scene=getattr(context, "scene", None), keyframe=True)


def _resolve_scheduled_drawing(scene_name, rig_name, rig_key):
    scene = bpy.data.scenes.get(scene_name) if scene_name else getattr(bpy.context, "scene", None)
    rig = bpy.data.objects.get(rig_name) if rig_name else None
    if not scene or not rig or not fbp_is_drawing_rig(rig):
        return None, None
    if rig_key and _drawing_key(rig) != rig_key:
        return None, None
    return scene, rig


def _drawing_apply_timer(scene_name, rig_name, rig_key):
    scene, rig = _resolve_scheduled_drawing(scene_name, rig_name, rig_key)
    if scene is None or rig is None:
        return None
    fbp_apply_drawing_index(rig, scene)
    return None


def _drawing_key_timer(scene_name, rig_name, rig_key):
    key = rig_key or rig_name
    deadline = float(_DRAWING_KEY_DEADLINES.get(key, 0.0) or 0.0)
    remaining = deadline - time.monotonic()
    if remaining > 0.001:
        return max(0.001, remaining)

    _DRAWING_KEY_DEADLINES.pop(key, None)
    request = _DRAWING_KEY_REQUESTS.pop(key, None)
    if request is None:
        return None
    scene, rig = _resolve_scheduled_drawing(scene_name, rig_name, key)
    if scene is None or rig is None:
        return None
    request_frame, request_index = request
    # Never insert a key at the wrong frame or with a later evaluated value.
    # A new slider edit will create a fresh request automatically.
    if int(getattr(scene, "frame_current", 1) or 1) != request_frame:
        return None
    if fbp_drawing_index(rig) != request_index:
        return None
    if bool(getattr(rig, "fbp_drawing_auto_key", True)):
        fbp_keyframe_drawing_index(rig, scene)
    return None


def fbp_schedule_drawing_sync(rig, scene=None, *, key_delay=0.075):
    """Apply slider previews promptly and debounce only the keyframe write."""
    if not fbp_is_drawing_rig(rig):
        return False
    scene = scene or getattr(bpy.context, "scene", None)
    if scene is None:
        return False
    key = _drawing_key(rig)
    scene_name = str(getattr(scene, "name", "") or "")
    rig_name = str(getattr(rig, "name", "") or "")
    frame = int(getattr(scene, "frame_current", 1) or 1)
    index = fbp_drawing_index(rig)
    previous = _DRAWING_SYNC_STATES.get(key)
    user_edit = bool(previous and previous[0] == frame and previous[1] != index)

    def apply_timer():
        return _drawing_apply_timer(scene_name, rig_name, key)

    try:
        from .safe_tasks import schedule_once
        apply_scheduled = bool(
            schedule_once(
                f"drawing.apply.{key}",
                apply_timer,
                first_interval=0.0,
            )
        )
        if (
            user_edit
            and bool(getattr(rig, "fbp_drawing_auto_key", True))
            and not _drawing_has_driver(rig)
        ):
            delay = max(0.0, float(key_delay))
            _DRAWING_KEY_REQUESTS[key] = (frame, index)
            _DRAWING_KEY_DEADLINES[key] = time.monotonic() + delay

            def key_timer():
                return _drawing_key_timer(scene_name, rig_name, key)

            key_scheduled = bool(
                schedule_once(
                    f"drawing.key.{key}",
                    key_timer,
                    first_interval=delay,
                )
            )
            return apply_scheduled or key_scheduled or key in _DRAWING_KEY_DEADLINES
        return apply_scheduled
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        _DRAWING_KEY_DEADLINES.pop(key, None)
        _DRAWING_KEY_REQUESTS.pop(key, None)
        return False


def _scene_cache_key(scene):
    try:
        return int(scene.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return str(getattr(scene, "name", "") or "")


def _drawing_rigs_for_scene(scene):
    if not scene:
        return ()
    try:
        layer_count = len(getattr(scene, "fbp_layers", ()))
        object_count = len(getattr(scene, "objects", ()))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return ()
    now = time.monotonic()
    key = _scene_cache_key(scene)
    cached = _DRAWING_SCENE_RIG_CACHE.get(key)
    if (
        cached
        and len(cached) >= 4
        and cached[0] == layer_count
        and cached[1] == object_count
        and (now - cached[2]) < _DRAWING_SCENE_CACHE_SECONDS
    ):
        resolved = []
        stale = False
        for name in cached[3]:
            rig = scene.objects.get(name)
            if rig is None or not fbp_is_drawing_rig(rig):
                stale = True
                break
            resolved.append(rig)
        if not stale:
            return tuple(resolved)

    rigs = []
    try:
        # The scene layer cache already contains only Frame By Plane roots, so
        # this scales with FBP layers rather than every object in a large scene.
        for item in getattr(scene, "fbp_layers", ()):
            rig = getattr(item, "obj", None)
            if rig is not None and fbp_is_drawing_rig(rig):
                try:
                    if scene.objects.get(str(getattr(rig, "name", "") or "")) == rig:
                        rigs.append(rig)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    continue
        # During the first sync tick the layer cache may still be empty. Keep a
        # self-healing fallback so old files and freshly duplicated rigs work.
        if not rigs and layer_count == 0:
            rigs = [obj for obj in scene.objects if fbp_is_drawing_rig(obj)]
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return ()
    rigs = tuple(rigs)
    if len(_DRAWING_SCENE_RIG_CACHE) >= 32 and key not in _DRAWING_SCENE_RIG_CACHE:
        oldest_key = min(
            _DRAWING_SCENE_RIG_CACHE,
            key=lambda cache_key: (
                _DRAWING_SCENE_RIG_CACHE[cache_key][2]
                if len(_DRAWING_SCENE_RIG_CACHE[cache_key]) >= 4 else 0.0
            ),
        )
        _DRAWING_SCENE_RIG_CACHE.pop(oldest_key, None)
    _DRAWING_SCENE_RIG_CACHE[key] = (
        layer_count,
        object_count,
        now,
        tuple(str(getattr(rig, "name", "") or "") for rig in rigs),
    )
    return rigs


def fbp_sync_drawing_scene(scene, *, force=False):
    changed = False
    if not scene:
        return False
    for rig in _drawing_rigs_for_scene(scene):
        try:
            changed = fbp_apply_drawing_index(rig, scene, force=force) or changed
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Cutout Plane frame update skipped", exc)
    return changed


def _mark_managed_cutout_item_if_safe(rig, item):
    """Upgrade legacy 5.1.2 entries only when the Image has no external users."""
    try:
        if bool(getattr(item, "managed_image", False)):
            return False
        image = getattr(item, "image", None)
        if image is None:
            return False
        if bool(getattr(image, "packed_file", None)) or bool(getattr(image, "is_dirty", False)):
            return False
        if str(getattr(image, "source", "") or "") == "GENERATED":
            return False
        path = str(getattr(item, "filepath", "") or "")
        absolute = os.path.abspath(bpy.path.abspath(path)) if path else ""
        if not absolute or not os.path.isfile(absolute):
            return False
        expected_users = 1  # the persistent item.image pointer
        texture = _drawing_texture(rig)
        if texture is not None and getattr(texture, "image", None) is image:
            expected_users += 1
        if int(getattr(image, "users", expected_users) or 0) > expected_users:
            return False
        item.managed_image = True
        try:
            image[DRAWING_MANAGED_IMAGE_KEY] = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
            pass
        try:
            item.source_width = max(0, int(image.size[0]))
            item.source_height = max(0, int(image.size[1]))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, IndexError):
            pass
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OSError):
        return False


def fbp_refresh_drawing_scene(scene):
    """Refresh ranges and safely migrate legacy Cutout buffer ownership."""
    changed = False
    migrated = False
    for rig in _drawing_rigs_for_scene(scene):
        for item in getattr(rig, "fbp_images", ()):
            migrated = _mark_managed_cutout_item_if_safe(rig, item) or migrated
        changed = fbp_update_drawing_index_ui(rig) or changed
        changed = fbp_apply_drawing_index(rig, scene, force=True) or changed
    if migrated:
        _schedule_drawing_buffer_trim()
    return changed or migrated


def fbp_depsgraph_schedule_drawing_updates(scene, candidate_rigs):
    scheduled = False
    for rig in candidate_rigs or ():
        if fbp_is_drawing_rig(rig):
            scheduled = fbp_schedule_drawing_sync(rig, scene) or scheduled
    return scheduled


def fbp_scene_has_drawing_planes(scene):
    if not scene:
        return False
    try:
        return bool(_drawing_rigs_for_scene(scene))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return True


def _drawing_required_render_indices(rig):
    """Return the smallest conservative set of library slots needed by render."""
    count = fbp_drawing_count(rig)
    if count <= 0:
        return ()
    if _drawing_has_driver(rig):
        return tuple(range(1, count + 1))
    animation_data = getattr(rig, "animation_data", None) if rig else None
    tracks = getattr(animation_data, "nla_tracks", None) if animation_data else None
    try:
        if tracks and any(bool(getattr(track, "strips", None)) for track in tracks):
            # NLA blending/influence can generate values not present verbatim in
            # action keys, so file validation remains conservative here.
            return tuple(range(1, count + 1))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return tuple(range(1, count + 1))
    curve = fbp_find_action_fcurve(rig, f'["{DRAWING_INDEX_KEY}"]')
    required = {fbp_drawing_index(rig)}
    if curve is None:
        return tuple(sorted(index for index in required if 0 < index <= count))
    try:
        if bool(getattr(curve, "modifiers", None)):
            return tuple(range(1, count + 1))
        for point in curve.keyframe_points:
            if str(getattr(point, "interpolation", "CONSTANT")) != "CONSTANT":
                return tuple(range(1, count + 1))
            required.add(int(round(float(point.co[1]))))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError):
        return tuple(range(1, count + 1))
    return tuple(sorted(index for index in required if 0 < index <= count))


def fbp_drawing_render_ready(rig):
    if not fbp_is_drawing_rig(rig):
        return False
    plane = getattr(rig, "fbp_plane_target", None)
    material = _drawing_material(rig)
    texture = _drawing_texture(rig)
    if not plane or not getattr(plane, "data", None) or not material or not texture:
        return False
    try:
        if _find_empty_image() is None:
            return False
        for index in _drawing_required_render_indices(rig):
            item = rig.fbp_images[index - 1]
            if bool(getattr(item, "is_empty", False)):
                continue
            image = getattr(item, "image", None)
            if image is None:
                image_name = str(getattr(item, "image_name", "") or "")
                image = bpy.data.images.get(image_name) if image_name else None
            if image is None:
                return False
            packed = bool(getattr(image, "packed_file", None))
            generated = str(getattr(image, "source", "") or "") == "GENERATED"
            path = os.path.abspath(bpy.path.abspath(str(getattr(item, "filepath", "") or "")))
            if not packed and not generated and (not path or not os.path.isfile(path)):
                return False
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OSError):
        return False


def _load_library_image(path, image_index=None):
    absolute = os.path.abspath(bpy.path.abspath(path))
    key = _normalized_image_path(absolute)
    existing = image_index.get(key) if image_index is not None and key else _loaded_image_for_path(absolute)
    image = existing or bpy.data.images.load(absolute, check_existing=True)
    _remember_loaded_image_path(absolute, image)
    managed = existing is None
    if image_index is not None and key:
        image_index[key] = image
    try:
        if managed:
            image[DRAWING_MANAGED_IMAGE_KEY] = True
        else:
            managed = bool(image.get(DRAWING_MANAGED_IMAGE_KEY, False))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
        pass
    return image, managed


def _drawing_library_warning(rig):
    """Warn only when buffers that cannot be safely evicted are extreme."""
    count = fbp_drawing_count(rig)
    active = _drawing_active_image_names()
    hot = set(_DRAWING_IMAGE_HOT)
    resident_pixels = 0
    resident_images = 0
    for item in getattr(rig, "fbp_images", ()):
        image = getattr(item, "image", None)
        if image is None or not bool(getattr(image, "has_data", False)):
            continue
        name = str(getattr(image, "name", "") or "")
        if bool(getattr(item, "managed_image", False)) and name not in active and name not in hot:
            # This buffer is scheduled for eviction and should not trigger a
            # warning immediately after importing a large library.
            continue
        try:
            width, height = (int(value) for value in image.size)
            if width > 0 and height > 0:
                resident_pixels += width * height
                resident_images += 1
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    if resident_pixels >= 500_000_000:
        megapixels = resident_pixels / 1_000_000.0
        return f"Cutout buffers are unusually large: {resident_images} resident images / {megapixels:.0f} MP"
    if count >= 2048:
        return f"Very large Cutout library: {count} entries; previews will load progressively"
    return ""


def _drawing_name_from_files(files):
    if not files:
        return "Cutout Plane"
    stems = [Path(name).stem for name in files]
    prefix = os.path.commonprefix(stems).rstrip(" _-.0123456789")
    return prefix or stems[0] or "Cutout Plane"


def build_drawing_plane(context, directory, files, *, name=None, interpolation="Closest"):
    from .builder import fbp_create_rect_mesh, fbp_create_mesh_object, fbp_apply_creation_orientation
    from .native_backend import _assign_layer_props, _store_native_aspect_on_rig, _refresh_native_geometry

    scene = context.scene
    target_collection = getattr(context, "collection", None) or scene.collection
    directory = os.path.abspath(bpy.path.abspath(directory))
    names = [str(file) for file in files]
    names = [
        file for file in names
        if is_supported_media_file(file)
        and not is_supported_video_file(file)
        and not is_technical_map_file(file)
        and os.path.isfile(os.path.join(directory, file))
    ]
    names.sort(key=natural_sort_key)
    if not names:
        raise FileNotFoundError("No supported image files selected")

    rig = plane = material = None
    rig_mesh = plane_mesh = None
    managed_loaded_images = []
    try:
        rig_name = name or _drawing_name_from_files(names)
        location = scene.cursor.location.copy()
        rig_mesh = fbp_create_rect_mesh(f"Mesh_{rig_name}_Rig", size=2.1, with_face=False)
        rig = fbp_create_mesh_object(rig_name, rig_mesh, context, location=location, target_collection=target_collection)
        _assign_layer_props(rig, scene, target_collection=target_collection)
        rig.fbp_loop_mode = "NONE"
        rig.fbp_global_duration = 1
        rig.fbp_start_frame = int(scene.frame_current)
        # Set filtering before enabling the Cutout flag so its update callback
        # cannot try to rebuild a material that does not exist yet.
        rig.fbp_interpolation = interpolation if interpolation in {"Closest", "Linear"} else "Closest"
        rig.fbp_is_drawing_plane = True
        rig.fbp_drawing_auto_key = True
        rig["fbp_native_backend"] = True
        rig["fbp_backend_type"] = "DRAWING"
        rig[DRAWING_INDEX_KEY] = 0
        rig["fbp_drawing_uuid"] = uuid.uuid4().hex
        fbp_apply_creation_orientation(rig, scene)

        plane_mesh = fbp_create_rect_mesh(f"Mesh_Plane_{rig_name}", size=2.0, with_face=True)
        plane = fbp_create_mesh_object(f"Plane_{rig_name}", plane_mesh, context, location=location, target_collection=target_collection)
        plane.is_fbp_plane = True
        plane["fbp_parent_rig_name"] = rig.name
        plane["fbp_native_backend"] = True
        plane.parent = rig
        plane.matrix_parent_inverse.identity()
        plane.location = (0.0, 0.0, 0.0)
        plane.rotation_euler = (0.0, 0.0, 0.0)
        plane.hide_select = True
        rig.fbp_plane_target = plane
        plane.fbp_collection_name = target_collection.name

        first_image = None
        first_path = ""
        source_size = None
        reference_aspect = None
        mixed_aspect = False
        image_index = _loaded_images_by_path()
        for file_name in names:
            path = os.path.join(directory, file_name)
            image, managed_image = _load_library_image(path, image_index=image_index)
            if managed_image:
                managed_loaded_images.append((image, path))
            try:
                image_size = tuple(int(value) for value in image.size)
                image_aspect = (image_size[0] / image_size[1]) if image_size[0] > 0 and image_size[1] > 0 else None
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, ZeroDivisionError):
                image_size = None
                image_aspect = None
            if first_image is None:
                first_image = image
                first_path = path
                source_size = image_size
                reference_aspect = image_aspect
            elif reference_aspect and image_aspect and abs(reference_aspect - image_aspect) > 1e-4:
                mixed_aspect = True
            item = rig.fbp_images.add()
            item.name = Path(file_name).stem
            item.filepath = path
            item.image = image
            item.image_name = image.name
            item.managed_image = bool(managed_image)
            item.source_width = int(image_size[0]) if image_size else 0
            item.source_height = int(image_size[1]) if image_size else 0
            item.stable_id = uuid.uuid4().hex
            item.is_empty = False
            item.is_selected = False
            fbp_set_rna_property_silent(item, "duration", 1)
            if managed_image:
                _free_managed_cutout_buffer(image, path)

        rig["fbp_drawing_mixed_aspect"] = bool(mixed_aspect)

        material = fbp_build_drawing_material(
            None,
            _ensure_empty_image(),
            interpolation=rig.fbp_interpolation,
            use_emission=rig.fbp_use_emission,
            opacity=rig.fbp_opacity,
        )
        material.name = f"FBP_Cutout_{rig.name}"
        material["fbp_image_path"] = first_path
        if source_size and source_size[0] > 0 and source_size[1] > 0:
            material["fbp_source_width"] = source_size[0]
            material["fbp_source_height"] = source_size[1]
            _store_native_aspect_on_rig(rig, source_size[0], source_size[1], first_path)
        plane.data.materials.append(material)
        if source_size:
            _refresh_native_geometry(rig)

        clear_drawing_runtime_cache()
        fbp_update_drawing_index_ui(rig)
        fbp_apply_drawing_index(rig, scene, force=True)
        _schedule_drawing_buffer_trim()
        sync_layer_collection(context)
        for selected in tuple(getattr(context, "selected_objects", ()) or ()):
            try:
                selected.select_set(False)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
        rig.select_set(True)
        context.view_layer.objects.active = rig
        return rig
    except Exception:
        for datablock, collection in (
            (plane, bpy.data.objects),
            (rig, bpy.data.objects),
            (plane_mesh, bpy.data.meshes),
            (rig_mesh, bpy.data.meshes),
            (material, bpy.data.materials),
        ):
            if datablock is None:
                continue
            try:
                if getattr(datablock, "users", 0) == 0 or collection is bpy.data.objects:
                    collection.remove(datablock, do_unlink=True) if collection is bpy.data.objects else collection.remove(datablock)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        for image, image_path in managed_loaded_images:
            _release_cutout_image_if_unused(image, image_path, managed=True)
        raise


def _selected_drawing_rig(context):
    active = getattr(context, "active_object", None) if context else None
    if fbp_is_drawing_rig(active):
        return active
    for rig in get_selected_rigs(context):
        if fbp_is_drawing_rig(rig):
            return rig
    return None


class FBP_OT_ImportDrawingPlane(Operator, ImportHelper):
    bl_idname = "fbp.import_drawing_plane"
    bl_label = "Cutout Plane"
    bl_description = "Create an empty Cutout Plane and load selected images into its pose library"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ""
    filter_glob: StringProperty(default="*.png;*.jpg;*.jpeg;*.tif;*.tiff;*.tga;*.bmp;*.webp;*.exr", options={"HIDDEN"})
    files: CollectionProperty(type=bpy.types.OperatorFileListElement)
    directory: StringProperty(subtype="DIR_PATH")
    interpolation: EnumProperty(
        name="Filter",
        description="Texture filtering used by the generated Cutout Plane",
        items=(
            ('Closest', "Pixel", "Sharp edges and pixel-art filtering"),
            ('Linear', "Smooth", "Bilinear image filtering"),
        ),
        default='Closest',
    )

    def invoke(self, context, event):
        path = context.scene.fbp_last_directory or context.scene.fbp_project_path
        if path:
            self.directory = path
        scene_default = str(getattr(context.scene, "fbp_pre_interpolation", "Closest") or "Closest")
        self.interpolation = scene_default if scene_default in {'Closest', 'Linear'} else 'Closest'
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context):
        layout = self.layout
        layout.label(text="Cutout Plane Setup", icon='OUTLINER_OB_ARMATURE')
        row = layout.row(align=True)
        row.prop_enum(self, "interpolation", 'Closest', text="Pixel", icon='ALIASED')
        row.prop_enum(self, "interpolation", 'Linear', text="Smooth", icon='ANTIALIASED')

    def execute(self, context):
        directory = os.path.abspath(bpy.path.abspath(self.directory or ""))
        files = [item.name for item in self.files]
        if not files and getattr(self, "filepath", ""):
            directory = os.path.dirname(self.filepath)
            files = [os.path.basename(self.filepath)]
        try:
            rig = build_drawing_plane(context, directory, files, interpolation=self.interpolation)
            context.scene.fbp_last_directory = directory
            warnings = []
            if bool(rig.get("fbp_drawing_mixed_aspect", False)):
                warnings.append("some images have different aspect ratios")
            memory_warning = _drawing_library_warning(rig)
            if memory_warning:
                warnings.append(memory_warning)
            if warnings:
                self.report({"WARNING"}, "Cutout Plane created; " + "; ".join(warnings))
            else:
                self.report({"INFO"}, f"Created Cutout Plane with {len(rig.fbp_images)} drawing(s)")
            return {"FINISHED"}
        except Exception as exc:
            fbp_warn("Could not create Cutout Plane", exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class FBP_OT_AddDrawingImages(Operator, ImportHelper):
    bl_idname = "fbp.add_drawing_images"
    bl_label = "Add Drawings"
    bl_description = "Add selected image files to the active Cutout Plane library"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ""
    filter_glob: StringProperty(default="*.png;*.jpg;*.jpeg;*.tif;*.tiff;*.tga;*.bmp;*.webp;*.exr", options={"HIDDEN"})
    files: CollectionProperty(type=bpy.types.OperatorFileListElement)
    directory: StringProperty(subtype="DIR_PATH")

    @classmethod
    def poll(cls, context):
        return _selected_drawing_rig(context) is not None

    def execute(self, context):
        rig = _selected_drawing_rig(context)
        if rig is None:
            return {"CANCELLED"}
        directory = os.path.abspath(bpy.path.abspath(self.directory or ""))
        names = [item.name for item in self.files]
        if not names and getattr(self, "filepath", ""):
            directory = os.path.dirname(os.path.abspath(bpy.path.abspath(self.filepath)))
            names = [os.path.basename(self.filepath)]
        names.sort(key=natural_sort_key)
        added = 0
        existing = {
            key
            for item in rig.fbp_images
            if (key := _normalized_image_path(str(getattr(item, "filepath", "") or "")))
        }
        image_index = _loaded_images_by_path()
        for file_name in names:
            path = os.path.abspath(os.path.join(directory, file_name))
            path_key = _normalized_image_path(path)
            if (
                not path_key
                or not os.path.isfile(path)
                or not is_supported_media_file(file_name)
                or is_supported_video_file(file_name)
                or is_technical_map_file(file_name)
                or path_key in existing
            ):
                continue
            image = None
            managed_image = False
            item_added = False
            try:
                image, managed_image = _load_library_image(path, image_index=image_index)
                try:
                    width, height = (int(value) for value in image.size)
                    source_width = int(rig.get("fbp_source_width", 0) or 0)
                    source_height = int(rig.get("fbp_source_height", 0) or 0)
                    if width > 0 and height > 0 and source_width > 0 and source_height > 0:
                        if abs((width / height) - (source_width / source_height)) > 1e-4:
                            rig["fbp_drawing_mixed_aspect"] = True
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, ZeroDivisionError, KeyError):
                    pass
                item = rig.fbp_images.add()
                item_added = True
                item.name = Path(file_name).stem
                item.filepath = path
                item.image = image
                item.image_name = image.name
                item.managed_image = bool(managed_image)
                try:
                    item.source_width = max(0, int(image.size[0]))
                    item.source_height = max(0, int(image.size[1]))
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, IndexError):
                    item.source_width = 0
                    item.source_height = 0
                item.stable_id = uuid.uuid4().hex
                item.is_selected = False
                item.is_empty = False
                fbp_set_rna_property_silent(item, "duration", 1)
                if managed_image:
                    _free_managed_cutout_buffer(image, path)
                existing.add(path_key)
                added += 1
            except (RuntimeError, OSError, AttributeError, ReferenceError, TypeError, ValueError) as exc:
                if item_added and len(rig.fbp_images):
                    try:
                        rig.fbp_images.remove(len(rig.fbp_images) - 1)
                    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, IndexError):
                        pass
                if managed_image:
                    _release_cutout_image_if_unused(image, path, managed=True)
                    image_index.pop(path_key, None)
                fbp_warn(f"Could not add drawing: {path}", exc)
        if added:
            fbp_refresh_drawing_aspect_warning(rig)
            fbp_update_drawing_index_ui(rig)
            _schedule_drawing_buffer_trim()
            context.scene.fbp_last_directory = directory
            memory_warning = _drawing_library_warning(rig)
            if memory_warning:
                self.report({"WARNING"}, memory_warning)
            else:
                self.report({"INFO"}, f"Added {added} drawing(s)")
            return {"FINISHED"}
        self.report({"WARNING"}, "No new supported images were added")
        return {"CANCELLED"}


class FBP_OT_ReplaceDrawingImage(Operator, ImportHelper):
    bl_idname = "fbp.replace_drawing_image"
    bl_label = "Replace Drawing"
    bl_description = "Replace the selected Cutout Plane library entry while keeping its index and keyframes"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ""
    filter_glob: StringProperty(default="*.png;*.jpg;*.jpeg;*.tif;*.tiff;*.tga;*.bmp;*.webp;*.exr", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        rig = _selected_drawing_rig(context)
        return bool(rig and len(rig.fbp_images) > 0)

    def execute(self, context):
        rig = _selected_drawing_rig(context)
        index = int(getattr(rig, "fbp_images_index", 0) or 0) if rig else -1
        if not rig or not (0 <= index < len(rig.fbp_images)):
            return {"CANCELLED"}
        path = os.path.abspath(bpy.path.abspath(self.filepath or ""))
        if (
            not os.path.isfile(path)
            or is_supported_video_file(path)
            or not is_supported_media_file(path)
            or is_technical_map_file(path)
        ):
            self.report({"WARNING"}, "Choose a supported image file")
            return {"CANCELLED"}

        item = rig.fbp_images[index]
        old_state = {
            "name": str(getattr(item, "name", "") or ""),
            "filepath": str(getattr(item, "filepath", "") or ""),
            "image": getattr(item, "image", None),
            "image_name": str(getattr(item, "image_name", "") or ""),
            "managed_image": bool(getattr(item, "managed_image", False)),
            "source_width": int(getattr(item, "source_width", 0) or 0),
            "source_height": int(getattr(item, "source_height", 0) or 0),
            "is_empty": bool(getattr(item, "is_empty", False)),
        }
        image = None
        managed_image = False
        try:
            invalidate_drawing_preview_path(old_state["filepath"])
            invalidate_drawing_preview_path(path)
            image, managed_image = _load_library_image(path)
            try:
                image.reload()
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OSError):
                pass
            item.filepath = path
            item.image = image
            item.image_name = image.name
            item.managed_image = bool(managed_image)
            try:
                item.source_width = max(0, int(image.size[0]))
                item.source_height = max(0, int(image.size[1]))
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, IndexError):
                item.source_width = 0
                item.source_height = 0
            item.is_empty = False
            item.name = Path(path).stem
            fbp_refresh_drawing_aspect_warning(rig)
            if fbp_drawing_index(rig) == index + 1:
                fbp_apply_drawing_index(rig, context.scene, force=True)
            invalidate_drawing_preview_path(path)
            if image is not old_state["image"]:
                _release_cutout_image_if_unused(
                    old_state["image"],
                    old_state["filepath"],
                    managed=old_state["managed_image"],
                )
            _schedule_drawing_buffer_trim()
            return {"FINISHED"}
        except Exception as exc:
            try:
                item.name = old_state["name"]
                item.filepath = old_state["filepath"]
                item.image = old_state["image"]
                item.image_name = old_state["image_name"]
                item.managed_image = old_state["managed_image"]
                item.source_width = old_state["source_width"]
                item.source_height = old_state["source_height"]
                item.is_empty = old_state["is_empty"]
                fbp_refresh_drawing_aspect_warning(rig)
                if fbp_drawing_index(rig) == index + 1:
                    fbp_apply_drawing_index(rig, context.scene, force=True)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
            if managed_image and image is not old_state["image"]:
                _release_cutout_image_if_unused(image, path, managed=True)
            fbp_warn("Could not replace Cutout Plane image", exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}



class FBP_OT_DrawingIndexStep(Operator):
    bl_idname = "fbp.drawing_index_step"
    bl_label = "Change Drawing"
    bl_options = {"REGISTER", "UNDO"}

    direction: StringProperty(default="NEXT")

    @classmethod
    def poll(cls, context):
        return _selected_drawing_rig(context) is not None

    def execute(self, context):
        rig = _selected_drawing_rig(context)
        current = fbp_drawing_index(rig)
        value = current - 1 if self.direction == "PREV" else current + 1
        fbp_set_drawing_index(rig, value, scene=context.scene, keyframe=True)
        return {"FINISHED"}


class FBP_OT_SetDrawingIndex(Operator):
    bl_idname = "fbp.set_drawing_index"
    bl_label = "Set Drawing"
    bl_options = {"REGISTER", "UNDO"}

    index: bpy.props.IntProperty(default=0, min=0)

    def execute(self, context):
        rig = _selected_drawing_rig(context)
        if not rig:
            return {"CANCELLED"}
        fbp_set_drawing_index(
            rig,
            self.index,
            scene=context.scene,
            keyframe=True,
            keyframe_unchanged=True,
        )
        return {"FINISHED"}


def _clear_drawing_slot(rig, index, scene=None):
    if not rig or not (0 <= index < len(rig.fbp_images)):
        return False
    item = rig.fbp_images[index]
    old_path = str(getattr(item, "filepath", "") or "")
    old_image = getattr(item, "image", None)
    old_managed = bool(getattr(item, "managed_image", False))
    if old_path:
        invalidate_drawing_preview_path(old_path)
    try:
        item.image = None
        item.image_name = ""
        item.filepath = ""
        item.name = f"Empty Slot {index + 1}"
        item.is_empty = True
        item.managed_image = False
        item.source_width = 0
        item.source_height = 0
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False
    if fbp_drawing_index(rig) == index + 1:
        fbp_apply_drawing_index(rig, scene, force=True)
    _release_cutout_image_if_unused(old_image, old_path, managed=old_managed)
    _schedule_drawing_buffer_trim()
    return True


class FBP_OT_RemoveDrawing(Operator):
    bl_idname = "fbp.remove_drawing"
    bl_label = "Remove Drawing"
    bl_description = "Remove and remap the selected drawing; driven libraries preserve the numeric slot as Empty"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        rig = _selected_drawing_rig(context)
        return bool(rig and len(rig.fbp_images) > 0)

    def execute(self, context):
        rig = _selected_drawing_rig(context)
        index = int(getattr(rig, "fbp_images_index", 0) or 0)
        if not rig or not (0 <= index < len(rig.fbp_images)):
            return {"CANCELLED"}
        if _drawing_has_driver(rig):
            if _clear_drawing_slot(rig, index, context.scene):
                self.report({"INFO"}, "Drawing slot cleared; driver values were preserved")
                return {"FINISHED"}
            self.report({"ERROR"}, "Could not clear the driven Drawing slot")
            return {"CANCELLED"}

        removed_item = rig.fbp_images[index]
        removed_path = str(getattr(removed_item, "filepath", "") or "")
        removed_image = getattr(removed_item, "image", None)
        removed_managed = bool(getattr(removed_item, "managed_image", False))
        removed_value = index + 1
        def remap(value):
            if value == removed_value:
                return 0
            return value - 1 if value > removed_value else value

        if not _remap_drawing_keyframes(rig, remap):
            self.report({"ERROR"}, "Could not safely remap Action or NLA drawing keys")
            return {"CANCELLED"}
        _remap_current_drawing(rig, remap)
        rig.fbp_images.remove(index)
        fbp_refresh_drawing_aspect_warning(rig)
        fbp_set_rna_property_silent(
            rig, "fbp_images_index", min(index, max(0, len(rig.fbp_images) - 1))
        )
        fbp_update_drawing_index_ui(rig)
        fbp_apply_drawing_index(rig, context.scene, force=True)
        _release_cutout_image_if_unused(removed_image, removed_path, managed=removed_managed)
        _schedule_drawing_buffer_trim()
        return {"FINISHED"}


class FBP_OT_MoveDrawing(Operator):
    bl_idname = "fbp.move_drawing"
    bl_label = "Move Drawing"
    bl_description = "Reorder the drawing and preserve existing animation"
    bl_options = {"REGISTER", "UNDO"}

    direction: StringProperty(default="UP")

    @classmethod
    def poll(cls, context):
        rig = _selected_drawing_rig(context)
        return bool(rig and len(rig.fbp_images) > 1)

    def execute(self, context):
        rig = _selected_drawing_rig(context)
        index = int(getattr(rig, "fbp_images_index", 0) or 0)
        target = index - 1 if self.direction == "UP" else index + 1
        if not rig or not (0 <= index < len(rig.fbp_images)) or not (0 <= target < len(rig.fbp_images)):
            return {"CANCELLED"}
        if _drawing_has_driver(rig):
            self.report({"WARNING"}, "Remove the Drawing driver before changing the library order")
            return {"CANCELLED"}

        source_value = index + 1
        target_value = target + 1
        def remap(value):
            if value == source_value:
                return target_value
            if value == target_value:
                return source_value
            return value

        if not _remap_drawing_keyframes(rig, remap):
            self.report({"ERROR"}, "Could not safely remap Action or NLA drawing keys")
            return {"CANCELLED"}
        _remap_current_drawing(rig, remap)
        rig.fbp_images.move(index, target)
        fbp_set_rna_property_silent(rig, "fbp_images_index", target)
        fbp_update_drawing_index_ui(rig)
        fbp_apply_drawing_index(rig, context.scene, force=True)
        return {"FINISHED"}


class FBP_UL_DrawingList(UIList):
    bl_idname = "FBP_UL_DrawingList"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        del active_data, active_propname
        rig = data
        row = layout.row(align=True)
        path = str(getattr(item, "filepath", "") or "")
        is_empty = bool(getattr(item, "is_empty", False))
        preview = (
            load_empty_drawing_preview(rig, scene=context.scene)
            if is_empty
            else load_drawing_preview(
                rig,
                path,
                scene=context.scene,
                deferred=fbp_drawing_index(rig) != index + 1,
            ) if path else None
        )
        op = row.operator("fbp.set_drawing_index", text="", icon="RADIOBUT_ON" if fbp_drawing_index(rig) == index + 1 else "RADIOBUT_OFF", emboss=False)
        op.index = index + 1
        if preview:
            row.label(text="", icon_value=preview.icon_id)
        else:
            row.label(text="", icon="TIME" if path and not is_empty else "IMAGE_DATA")
        row.prop(item, "name", text=f"{index + 1}", emboss=False)


def _current_preview(rig, scene=None):
    index = fbp_drawing_index(rig)
    if index <= 0 or index > len(rig.fbp_images):
        return load_empty_drawing_preview(rig, scene=scene), "Empty"
    item = rig.fbp_images[index - 1]
    if bool(getattr(item, "is_empty", False)):
        return load_empty_drawing_preview(rig, scene=scene), str(getattr(item, "name", "") or f"Empty Slot {index}")
    return load_drawing_preview(rig, getattr(item, "filepath", ""), scene=scene), str(getattr(item, "name", "") or f"Drawing {index}")


def draw_drawing_plane_ui(layout, context, rig):
    frame = int(getattr(context.scene, "frame_current", 1) or 1)
    state = _DRAWING_SYNC_STATES.get(_drawing_key(rig))
    if state != (frame, fbp_drawing_index(rig)):
        fbp_schedule_drawing_sync(rig, context.scene, key_delay=0.075)
    box = layout.box()
    row = box.row(align=False)
    row.prop(rig, "fbp_color_tag", text="")
    row.prop(rig, "fbp_layer_name", text="", icon="OUTLINER_OB_ARMATURE")
    row.operator("fbp.add_drawing_images", text="", icon="ADD")

    row = box.row(align=True)
    row.prop(rig, "fbp_is_visible", text="", icon="HIDE_OFF" if rig.fbp_is_visible else "HIDE_ON")
    row.prop(rig, "fbp_opacity", text="Opacity", slider=True)
    row.prop(rig, "fbp_use_emission", text="", icon="LIGHT_SUN", toggle=True)
    row.prop(rig, "fbp_track_cam", text="", icon="CON_TRACKTO", toggle=True)
    row.operator("fbp.fit_camera", text="", icon="FULLSCREEN_ENTER")
    row.operator("fbp.popup_transform", text="", icon="ORIENTATION_GLOBAL")

    preview_box = layout.box()
    preview, name = _current_preview(rig, scene=context.scene)
    preview_column = preview_box.column(align=True)
    preview_column.alignment = "CENTER"
    if preview:
        preview_column.template_icon(icon_value=preview.icon_id, scale=8.0)
    else:
        empty = preview_column.row(align=True)
        empty.alignment = "CENTER"
        empty.scale_y = 4.0
        empty.label(text="Empty", icon="IMAGE_ALPHA")
    label_row = preview_column.row(align=True)
    label_row.alignment = "CENTER"
    label_row.label(text=f"{fbp_drawing_index(rig)} / {fbp_drawing_count(rig)} — {name}")

    slider = preview_box.row(align=True)
    previous = slider.operator("fbp.drawing_index_step", text="", icon="TRIA_LEFT")
    previous.direction = "PREV"
    slider.prop(rig, f'["{DRAWING_INDEX_KEY}"]', text="Drawing", slider=True)
    next_op = slider.operator("fbp.drawing_index_step", text="", icon="TRIA_RIGHT")
    next_op.direction = "NEXT"
    slider.prop(rig, "fbp_drawing_auto_key", text="", icon="RECORD_ON", toggle=True)

    library = layout.box()
    library.label(text="Cutout Library", icon="FILE_IMAGE")
    if bool(rig.get("fbp_drawing_mixed_aspect", False)):
        warning = library.row()
        warning.alert = True
        warning.label(text="Different aspect ratios will stretch to the first drawing", icon="ERROR")
    row = library.row()
    row.template_list("FBP_UL_DrawingList", "", rig, "fbp_images", rig, "fbp_images_index", rows=5)
    controls = row.column(align=True)
    controls.operator("fbp.add_drawing_images", text="", icon="ADD")
    controls.operator("fbp.replace_drawing_image", text="", icon="FILE_REFRESH")
    controls.separator()
    up = controls.operator("fbp.move_drawing", text="", icon="TRIA_UP")
    up.direction = "UP"
    down = controls.operator("fbp.move_drawing", text="", icon="TRIA_DOWN")
    down.direction = "DOWN"
    controls.separator()
    controls.operator("fbp.remove_drawing", text="", icon="TRASH")


classes = (
    FBP_OT_ImportDrawingPlane,
    FBP_OT_AddDrawingImages,
    FBP_OT_ReplaceDrawingImage,
    FBP_OT_DrawingIndexStep,
    FBP_OT_SetDrawingIndex,
    FBP_OT_RemoveDrawing,
    FBP_OT_MoveDrawing,
    FBP_UL_DrawingList,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    clear_drawing_runtime_cache()
    clear_drawing_composite_previews()
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
            pass
