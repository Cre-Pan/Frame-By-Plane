"""Frame Stack runtime: the frame atlas and timing table of every layer.

The Frame Stack group (``builtin_effects._create_frame_stack``) draws every
slice as an instance of the plane. For image sequences it only needs two
small things from Python:

* an **atlas** image, owned by the layer's Frame Stack material, holding a
  reduced copy of the drawings the stack shows. The material samples it per
  pixel, so slices stay sharp without any mesh detail;
* a **timing table**, one pixel per playback position: the atlas cell that
  holds the drawing of that position, and whether it is there yet.

Cells belong to drawings (files), not to slices: when the playhead moves, the
slices just read other cells and nothing is written, unless a drawing that
was never seen comes into view. Drawings are read with OpenImageIO on worker
threads while the viewport keeps running; a slice appears as soon as its
drawing has arrived. When every drawing of the layer fits, all of them are
read once in the background and later playback writes nothing at all.
Renders and background processes read what they need before returning.

Videos cannot be read here; the group samples their frames itself.
"""

from __future__ import annotations

import math
import os
import threading
from collections import OrderedDict

import bpy

from .runtime import FBP_DATA_ERRORS, fbp_warn


FBP_FRAME_STACK_EFFECT_ID = "FRAME_STACK"
FBP_FRAME_STACK_MATERIAL_VERSION = 3
# Pixels of one atlas; larger stacks get smaller cells. Renders may use more.
_ATLAS_PIXEL_BUDGET = 8 * 1024 * 1024
_RENDER_ATLAS_PIXEL_BUDGET = 16 * 1024 * 1024
_ATLAS_MAX_SIDE = 16384
# Decoded drawings kept outside the atlases (re-layout, other layers).
_THUMB_BUDGET = 256 * 1024 * 1024
_MAX_WORKERS = max(1, min(4, (os.cpu_count() or 2) - 1))

_THUMBS = OrderedDict()          # (path, mtime, size, factor) -> (array, is_float)
_THUMB_BYTES = [0]
_FAILED = {}                     # path -> file key
_SIZES = {}                      # file key -> (width, height, is_float)
_PENDING = {}                    # thumb key -> Future
_STACKS = {}                     # atlas key -> _Atlas
_IMAGE_NAMES = {}                # (tag, owner) -> image name
_LOCK = threading.Lock()
_EXECUTOR = [None]
_POLL_REGISTERED = [False]
_WAITING = {}                    # (rig name, modifier name) -> True
_SIGNATURES = {}                 # modifier pointer -> input signature


def _geo():
    from . import geometry_nodes
    return geometry_nodes


def _table_width():
    from .builtin_effects import FBP_FRAME_STACK_TABLE_WIDTH
    return int(FBP_FRAME_STACK_TABLE_WIDTH)


# --------------------------------------------------------------------------
# Decoding (worker threads: OpenImageIO and numpy only, no bpy)
# --------------------------------------------------------------------------

def _file_key(path):
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return (path, int(stat.st_mtime_ns), int(stat.st_size))


def _source_size(path):
    """``(width, height, is_float)`` of a file from its header, cached."""
    key = _file_key(path)
    if key is None:
        return None
    if key in _SIZES:
        return _SIZES[key]
    size = None
    try:
        import OpenImageIO as oiio
        source = oiio.ImageInput.open(path)
        if source:
            try:
                spec = source.spec()
                if spec.width > 0 and spec.height > 0:
                    is_float = str(spec.format).lower() in {"float", "half", "double"}
                    size = (int(spec.width), int(spec.height), bool(is_float))
            finally:
                source.close()
    except Exception:  # OIIO raises its own error types.
        size = None
    if len(_SIZES) >= 4096:
        _SIZES.clear()
    _SIZES[key] = size
    return size


def _decode(path, factor, cell_w, cell_h, is_float):
    """Read one drawing and shrink it by ``factor`` to fit ``cell_w x cell_h``.

    Returns a bottom-up RGBA array: uint8 straight alpha for 8/16-bit files
    (the atlas gets the source colour space, so Blender converts it exactly
    like the plane), float32 premultiplied for float files. OpenImageIO
    reads with associated alpha, so the box filter never darkens the edges
    of a drawing, and does the filtering on its own threads.
    """
    import numpy as np
    import OpenImageIO as oiio
    pixel_type = oiio.FLOAT if is_float else oiio.UINT8
    source = oiio.ImageBuf(path)
    if not source.read(0, 0, True, pixel_type) or source.has_error:
        raise ValueError(source.geterror() or "unreadable image")
    spec = source.spec()
    channels = max(1, min(4, int(spec.nchannels)))
    width = max(1, min(cell_w, spec.width // factor))
    height = max(1, min(cell_h, spec.height // factor))
    if (width, height) != (spec.width, spec.height):
        small = oiio.ImageBufAlgo.resize(
            source, filtername="box", roi=oiio.ROI(0, width, 0, height, 0, 1, 0, channels),
        )
        if small.has_error:
            raise ValueError(small.geterror())
    else:
        small = source
    has_alpha = channels in (2, 4)
    if has_alpha and not is_float:
        small = oiio.ImageBufAlgo.unpremult(small)
    pixels = np.asarray(small.get_pixels(pixel_type, oiio.ROI(0, width, 0, height, 0, 1, 0, channels)))
    pixels = pixels.reshape(height, width, channels)
    out = np.zeros((cell_h, cell_w, 4), dtype=np.float32 if is_float else np.uint8)
    if channels >= 3:
        out[:height, :width, :3] = pixels[..., :3]
    else:
        out[:height, :width, :3] = pixels[..., :1]
    out[:height, :width, 3] = pixels[..., channels - 1] if has_alpha else (1.0 if is_float else 255)
    return np.ascontiguousarray(out[::-1])


def _thumb_key(path, factor):
    key = _file_key(path)
    return None if key is None else (*key, int(factor))


def _store_thumb(key, data):
    with _LOCK:
        if key in _THUMBS:
            return
        _THUMBS[key] = data
        _THUMB_BYTES[0] += int(data.nbytes)
        while _THUMB_BYTES[0] > _THUMB_BUDGET and len(_THUMBS) > 1:
            _old, old = _THUMBS.popitem(last=False)
            _THUMB_BYTES[0] -= int(old.nbytes)


def _cached_thumb(key):
    with _LOCK:
        data = _THUMBS.get(key)
        if data is not None:
            _THUMBS.move_to_end(key)
        return data


def _decode_job(path, key, factor, cell_w, cell_h, is_float):
    try:
        data = _decode(path, factor, cell_w, cell_h, is_float)
    except Exception as exc:  # OIIO raises its own error types.
        return ("failed", path, key, exc)
    _store_thumb(key, data)
    return ("ok", path, key, None)


def _executor():
    if _EXECUTOR[0] is None:
        from concurrent.futures import ThreadPoolExecutor
        _EXECUTOR[0] = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="fbp_frame_stack")
    return _EXECUTOR[0]


def _note_failure(path, key, exc):
    if not _FAILED:
        fbp_warn("Frame Stack could not read a drawing", exc)
    if len(_FAILED) > 4096:
        _FAILED.clear()
    _FAILED[path] = key[:3] if key else None


def _request(path, factor, cell_w, cell_h, is_float, blocking):
    """Return the decoded drawing now, or ``None`` and decode it later."""
    key = _thumb_key(path, factor)
    if key is None:
        return None
    if _FAILED.get(path) == key[:3]:
        return None
    data = _cached_thumb(key)
    if data is not None:
        return data
    future = _PENDING.get(key)
    if blocking:
        if future is None:
            status = _decode_job(path, key, factor, cell_w, cell_h, is_float)
        else:
            status = future.result()
            _PENDING.pop(key, None)
        if status[0] != "ok":
            _note_failure(path, key, status[3])
            return None
        return _cached_thumb(key)
    if future is None:
        _PENDING[key] = _executor().submit(_decode_job, path, key, factor, cell_w, cell_h, is_float)
    return None


def _prefetch_many(jobs, blocking):
    """Decode several drawings at once; with ``blocking`` wait for all."""
    futures = []
    for path, factor, cell_w, cell_h, is_float in jobs:
        key = _thumb_key(path, factor)
        if key is None or _FAILED.get(path) == key[:3] or _cached_thumb(key) is not None:
            continue
        future = _PENDING.get(key)
        if future is None:
            future = _executor().submit(_decode_job, path, key, factor, cell_w, cell_h, is_float)
            _PENDING[key] = future
        futures.append((key, future))
    if blocking:
        for key, future in futures:
            status = future.result()
            _PENDING.pop(key, None)
            if status[0] != "ok":
                _note_failure(status[1], key, status[3])


def _poll():
    """Main-thread timer: finish decoded drawings and refresh their stacks."""
    finished = [key for key, future in _PENDING.items() if future.done()]
    for key in finished:
        future = _PENDING.pop(key)
        try:
            status = future.result()
        except Exception as exc:  # A worker raised outside _decode_job.
            status = ("failed", key[0], key, exc)
        if status[0] != "ok":
            _note_failure(status[1], key, status[3])
    if finished and _WAITING:
        waiting = tuple(_WAITING)
        _WAITING.clear()
        for rig_name, modifier_name in waiting:
            rig = bpy.data.objects.get(rig_name)
            plane = _geo()._fbp_plane(rig) if rig is not None else None
            modifier = plane.modifiers.get(modifier_name) if plane is not None else None
            if modifier is None:
                continue
            try:
                if fbp_frame_stack_sync(rig, modifier):
                    plane.update_tag()
            except FBP_DATA_ERRORS as exc:
                fbp_warn("Could not refresh Frame Stack", exc)
    if _PENDING:
        return 0.05
    _POLL_REGISTERED[0] = False
    return None


def _ensure_poll():
    if _POLL_REGISTERED[0] or bool(getattr(bpy.app, "background", False)):
        return
    try:
        bpy.app.timers.register(_poll, first_interval=0.05)
        _POLL_REGISTERED[0] = True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass


# --------------------------------------------------------------------------
# Atlas
# --------------------------------------------------------------------------

class _Atlas:
    """Cells of one layer's atlas, assigned to drawings."""

    __slots__ = (
        "layout", "cell_w", "cell_h", "columns", "rows", "factor", "is_float",
        "canvas", "cells", "lru", "free", "dirty", "table_signature", "image_name",
    )

    def __init__(self, layout, cell_w, cell_h, columns, rows, factor, is_float, capacity):
        import numpy as np
        self.layout = layout
        self.cell_w, self.cell_h = cell_w, cell_h
        self.columns, self.rows = columns, rows
        self.factor, self.is_float = factor, is_float
        self.canvas = np.zeros(
            (rows * cell_h, columns * cell_w, 4), dtype=np.float32 if is_float else np.uint8,
        )
        self.cells = {}                    # path -> cell
        self.lru = OrderedDict()           # path -> None, oldest first
        self.free = list(range(capacity - 1, -1, -1))
        self.dirty = True
        self.table_signature = None
        self.image_name = ""

    def place(self, path, data, protected):
        cell = self.cells.get(path)
        if cell is not None:
            self.lru.move_to_end(path)
            return cell
        if self.free:
            cell = self.free.pop()
        else:
            victim = next((item for item in self.lru if item not in protected), None)
            if victim is None:
                return None
            cell = self.cells.pop(victim)
            del self.lru[victim]
        row, column = divmod(cell, self.columns)
        y, x = row * self.cell_h, column * self.cell_w
        self.canvas[y:y + self.cell_h, x:x + self.cell_w] = data
        self.cells[path] = cell
        self.lru[path] = None
        self.dirty = True
        return cell


def _owner(plane):
    return str(getattr(plane, "name", "") or "")


def _find_image(tag, owner):
    key = (tag, owner)
    name = _IMAGE_NAMES.get(key)
    if name is not None:
        candidate = bpy.data.images.get(name)
        try:
            if (
                candidate is not None
                and bool(candidate.get(tag, False))
                and str(candidate.get("fbp_effect_material_owner", "") or "") == owner
            ):
                return candidate
        except FBP_DATA_ERRORS:
            pass
        _IMAGE_NAMES.pop(key, None)
    for candidate in bpy.data.images:
        try:
            if (
                bool(candidate.get(tag, False))
                and str(candidate.get("fbp_effect_material_owner", "") or "") == owner
            ):
                _IMAGE_NAMES[key] = candidate.name
                return candidate
        except FBP_DATA_ERRORS:
            continue
    return None


def _new_image(tag, owner, label, width, height, *, is_float, is_data):
    image = bpy.data.images.new(
        f"FBP Frame Stack {label} • {owner}", width, height,
        alpha=True, float_buffer=bool(is_float), is_data=bool(is_data),
    )
    image.use_fake_user = False
    image[tag] = True
    image["fbp_owned"] = True
    image["fbp_effect_material_owner"] = owner
    _IMAGE_NAMES[(tag, owner)] = image.name
    return image


def _atlas_image(owner, atlas, colorspace, alpha_mode):
    """The layer's atlas datablock, matching the atlas size and pixel type."""
    width, height = atlas.columns * atlas.cell_w, atlas.rows * atlas.cell_h
    image = _find_image("fbp_frame_stack_atlas", owner)
    if image is not None and bool(image.is_float) != bool(atlas.is_float):
        # Never delete datablocks from here: retire it for orphan cleanup.
        try:
            image["fbp_frame_stack_atlas"] = False
            image.name = f"{image.name} (retired)"
        except FBP_DATA_ERRORS:
            pass
        _IMAGE_NAMES.pop(("fbp_frame_stack_atlas", owner), None)
        image = None
    if image is None:
        image = _new_image(
            "fbp_frame_stack_atlas", owner, "Atlas", width, height,
            is_float=atlas.is_float, is_data=False,
        )
    elif tuple(image.size) != (width, height):
        image.scale(width, height)
    try:
        if colorspace and image.colorspace_settings.name != colorspace:
            image.colorspace_settings.name = colorspace
    except FBP_DATA_ERRORS:
        pass
    try:
        if image.alpha_mode != alpha_mode:
            image.alpha_mode = alpha_mode
    except FBP_DATA_ERRORS:
        pass
    return image


def _write_atlas(image, atlas):
    import numpy as np
    if atlas.is_float:
        pixels = atlas.canvas.reshape(-1)
    else:
        pixels = atlas.canvas.reshape(-1).astype(np.float32)
        pixels *= 1.0 / 255.0
    image.pixels.foreach_set(pixels)
    image.update()
    atlas.dirty = False


def _write_table(owner, atlas, positions, visible, cells_by_path):
    """One pixel per playback position: R = cell, G = 1 when it is ready."""
    import numpy as np
    width = _table_width()
    count = len(positions)
    rows = max(1, -(-count // width))
    cell = np.zeros(count, dtype=np.float32)
    ready = np.zeros(count, dtype=np.float32)
    for index, (path, shown) in enumerate(zip(positions, visible)):
        if not shown or path is None:
            continue
        value = cells_by_path.get(path)
        if value is not None:
            cell[index] = float(value)
            ready[index] = 1.0
    signature = (rows, cell.tobytes(), ready.tobytes())
    image = _find_image("fbp_frame_stack_timing", owner)
    if image is None:
        image = _new_image("fbp_frame_stack_timing", owner, "Timing", width, rows, is_float=True, is_data=True)
        atlas.table_signature = None
    elif tuple(image.size) != (width, rows):
        image.scale(width, rows)
        atlas.table_signature = None
    if atlas.table_signature != signature:
        pixels = np.zeros((rows * width, 4), dtype=np.float32)
        pixels[:count, 0] = cell
        pixels[:count, 1] = ready
        pixels[:, 3] = 1.0
        image.pixels.foreach_set(pixels.reshape(-1))
        image.update()
        atlas.table_signature = signature
    return image, rows


def _detail_side(detail):
    """Longest side of a drawing in the atlas: 256 px at Detail 5, 1024 at 7."""
    return 8 << max(0, min(8, int(detail)))


def _layout(width, height, detail, needed, wanted, budget):
    """Cell size, shrink factor and grid for ``wanted`` cells (at least ``needed``)."""
    target = _detail_side(detail)
    factor = max(1, int(math.ceil(max(width, height) / float(target))))
    while True:
        cell_w, cell_h = max(1, width // factor), max(1, height // factor)
        area = cell_w * cell_h
        capacity = max(needed, min(wanted, budget // max(1, area)))
        columns = max(1, int(math.ceil(math.sqrt(capacity * cell_h / float(cell_w)))))
        rows = max(1, int(math.ceil(capacity / float(columns))))
        fits = (
            capacity * area <= budget
            and columns * cell_w <= _ATLAS_MAX_SIDE
            and rows * cell_h <= _ATLAS_MAX_SIDE
        )
        if fits or cell_w <= 2 or cell_h <= 2:
            return cell_w, cell_h, factor, columns, rows, columns * rows
        factor += 1


# --------------------------------------------------------------------------
# Material
# --------------------------------------------------------------------------

def fbp_frame_stack_material(rig):
    """The layer's shadeless slice material, built once per version.

    Atlas slices carry their cell rectangle (``fbp_frame_stack_cell``) and
    the plane's UVs; the material samples the atlas per pixel, applies the
    plane's extension mode and the luminance key. Video slices and the
    outline carry a vertex colour instead (``fbp_frame_stack_atlas`` = 0).
    Glow adds the emission over a transparent surface, which does not depend
    on draw order and stays noise-free in Eevee.
    """
    geo = _geo()
    plane = geo._fbp_plane(rig)
    if not plane:
        return None
    owner = _owner(plane)
    role = "Frame Stack"
    material = geo._fbp_find_owned_effect_material(rig, FBP_FRAME_STACK_EFFECT_ID, role)
    if material is None:
        try:
            material = bpy.data.materials.new(name=f"FBP {role} • {owner}")
            material.use_fake_user = False
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not create Frame Stack material", exc)
            return None
    try:
        geo._fbp_set_idprop_if_changed(material, "fbp_owned", True)
        geo._fbp_set_idprop_if_changed(material, "fbp_effect_material_owner", owner)
        geo._fbp_set_idprop_if_changed(material, "fbp_effect_material_id", FBP_FRAME_STACK_EFFECT_ID)
        geo._fbp_set_idprop_if_changed(material, "fbp_effect_material_role", role)
        if int(material.get("fbp_frame_stack_material_version", 0) or 0) != FBP_FRAME_STACK_MATERIAL_VERSION:
            _build_material(material)
            material["fbp_frame_stack_material_version"] = FBP_FRAME_STACK_MATERIAL_VERSION
        geo._fbp_set_attr_if_changed(material, "surface_render_method", "DITHERED")
        geo._fbp_set_attr_if_changed(material, "use_transparency_overlap", False)
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not update Frame Stack material", exc)
    return material


def _build_material(material):
    material.use_nodes = True
    tree = material.node_tree
    nodes, links = tree.nodes, tree.links
    nodes.clear()
    x = -1800.0

    def node(kind, label, location, **settings):
        item = nodes.new(kind)
        item.name = label
        item.label = label
        item.location = location
        for key, value in settings.items():
            setattr(item, key, value)
        return item

    def attribute(name, label, y):
        return node("ShaderNodeAttribute", label, (x, y), attribute_type="GEOMETRY", attribute_name=name)

    def math_node(operation, label, location, a=None, b=None, clamp=False):
        item = node("ShaderNodeMath", label, location, operation=operation, use_clamp=clamp)
        if a is not None:
            item.inputs[0].default_value = a
        if b is not None:
            item.inputs[1].default_value = b
        return item

    uv = attribute("fbp_frame_stack_uv", "FBP Frame Stack UV", 400.0)
    rect = attribute("fbp_frame_stack_cell", "FBP Frame Stack Cell", 100.0)
    color_attr = attribute("fbp_frame_stack_color", "FBP Frame Stack Color", -200.0)
    alpha_attr = attribute("fbp_frame_stack_alpha", "FBP Frame Stack Alpha", -400.0)
    atlas_attr = attribute("fbp_frame_stack_atlas", "FBP Frame Stack Atlas Flag", -600.0)
    glow_attr = attribute("fbp_frame_stack_glow", "FBP Frame Stack Glow", -800.0)
    key_attr = attribute("fbp_frame_stack_key", "FBP Frame Stack Key", -1000.0)
    wrap = node("ShaderNodeValue", "FBP Frame Stack Wrap", (x, 700.0))
    wrap["fbp_frame_stack_wrap_node"] = True
    wrap.outputs[0].default_value = 0.0

    split_uv = node("ShaderNodeSeparateXYZ", "UV Parts", (x + 220, 400.0))
    links.new(uv.outputs["Vector"], split_uv.inputs[0])
    split_rect = node("ShaderNodeSeparateColor", "Cell Parts", (x + 220, 100.0))
    links.new(rect.outputs["Color"], split_rect.inputs[0])
    # Wrap modes: 0 Extend (clamp), 1 Clip, 2 Repeat, 3 Mirror.
    is_repeat = math_node("COMPARE", "Is Repeat", (x + 220, 900.0), b=2.0)
    is_repeat.inputs[2].default_value = 0.1
    links.new(wrap.outputs[0], is_repeat.inputs[0])
    is_mirror = math_node("COMPARE", "Is Mirror", (x + 220, 1100.0), b=3.0)
    is_mirror.inputs[2].default_value = 0.1
    links.new(wrap.outputs[0], is_mirror.inputs[0])
    is_clip = math_node("COMPARE", "Is Clip", (x + 220, 1300.0), b=1.0)
    is_clip.inputs[2].default_value = 0.1
    links.new(wrap.outputs[0], is_clip.inputs[0])

    def axis(component, origin, span, label, y):
        clamped = math_node("MINIMUM", f"{label} Clamp", (x + 440, y), b=1.0)
        links.new(component, clamped.inputs[0])
        clamped_low = math_node("MAXIMUM", f"{label} Clamp Low", (x + 660, y), b=0.0)
        links.new(clamped.outputs[0], clamped_low.inputs[0])
        repeated = math_node("FRACT", f"{label} Repeat", (x + 440, y - 120))
        links.new(component, repeated.inputs[0])
        mirrored = math_node("PINGPONG", f"{label} Mirror", (x + 440, y - 240), b=1.0)
        links.new(component, mirrored.inputs[0])
        pick_repeat = node("ShaderNodeMix", f"{label} Pick Repeat", (x + 880, y), data_type="FLOAT")
        links.new(is_repeat.outputs[0], pick_repeat.inputs["Factor"])
        links.new(clamped_low.outputs[0], pick_repeat.inputs["A"])
        links.new(repeated.outputs[0], pick_repeat.inputs["B"])
        pick_mirror = node("ShaderNodeMix", f"{label} Pick Mirror", (x + 1100, y), data_type="FLOAT")
        links.new(is_mirror.outputs[0], pick_mirror.inputs["Factor"])
        links.new(pick_repeat.outputs["Result"], pick_mirror.inputs["A"])
        links.new(mirrored.outputs[0], pick_mirror.inputs["B"])
        mapped = math_node("MULTIPLY_ADD", f"{label} Atlas", (x + 1320, y))
        links.new(pick_mirror.outputs["Result"], mapped.inputs[0])
        links.new(span, mapped.inputs[1])
        links.new(origin, mapped.inputs[2])
        # Clip: 1 inside 0..1, 0 outside.
        above = math_node("GREATER_THAN", f"{label} Above", (x + 660, y - 360), b=-0.000001)
        links.new(component, above.inputs[0])
        below = math_node("LESS_THAN", f"{label} Below", (x + 660, y - 480), b=1.000001)
        links.new(component, below.inputs[0])
        inside = math_node("MULTIPLY", f"{label} Inside", (x + 880, y - 420))
        links.new(above.outputs[0], inside.inputs[0])
        links.new(below.outputs[0], inside.inputs[1])
        return mapped.outputs[0], inside.outputs[0]

    atlas_u, inside_u = axis(split_uv.outputs["X"], split_rect.outputs["Red"], split_rect.outputs["Blue"], "U", 400.0)
    atlas_v, inside_v = axis(split_uv.outputs["Y"], split_rect.outputs["Green"], rect.outputs["Alpha"], "V", -100.0)
    atlas_uv = node("ShaderNodeCombineXYZ", "Atlas UV", (x + 1540, 200.0))
    links.new(atlas_u, atlas_uv.inputs["X"])
    links.new(atlas_v, atlas_uv.inputs["Y"])
    texture = node("ShaderNodeTexImage", "FBP Frame Stack Atlas", (x + 1760, 200.0))
    texture["fbp_frame_stack_atlas_node"] = True
    texture.extension = "EXTEND"
    texture.interpolation = "Linear"
    links.new(atlas_uv.outputs[0], texture.inputs["Vector"])

    inside = math_node("MULTIPLY", "Inside", (x + 1320, -700.0))
    links.new(inside_u, inside.inputs[0])
    links.new(inside_v, inside.inputs[1])
    clip_loss = math_node("MULTIPLY_ADD", "Clip Keep", (x + 1540, -700.0))
    # keep = 1 - clip * (1 - inside) = clip * (inside - 1) + 1
    inside_minus = math_node("SUBTRACT", "Outside", (x + 1320, -900.0), b=1.0)
    links.new(inside.outputs[0], inside_minus.inputs[0])
    links.new(is_clip.outputs[0], clip_loss.inputs[0])
    links.new(inside_minus.outputs[0], clip_loss.inputs[1])
    clip_loss.inputs[2].default_value = 1.0

    # Luminance key: positive keys dark areas out, negative bright ones.
    luminance = node("ShaderNodeVectorMath", "Luminance", (x + 1980, -300.0), operation="DOT_PRODUCT")
    luminance.inputs[1].default_value = (0.2126, 0.7152, 0.0722)
    links.new(texture.outputs["Color"], luminance.inputs[0])
    dark = math_node("SUBTRACT", "Dark Key", (x + 2200, -200.0), a=1.0)
    links.new(luminance.outputs["Value"], dark.inputs[1])
    bright = math_node("GREATER_THAN", "Bright Key", (x + 2200, -400.0), b=0.0)
    links.new(key_attr.outputs["Fac"], bright.inputs[0])
    key = node("ShaderNodeMix", "Key", (x + 2420, -300.0), data_type="FLOAT")
    links.new(bright.outputs[0], key.inputs["Factor"])
    links.new(dark.outputs[0], key.inputs["A"])
    links.new(luminance.outputs["Value"], key.inputs["B"])
    amount = math_node("ABSOLUTE", "Key Amount", (x + 2420, -500.0))
    links.new(key_attr.outputs["Fac"], amount.inputs[0])
    key_minus = math_node("SUBTRACT", "Key Offset", (x + 2640, -300.0), b=1.0)
    links.new(key.outputs["Result"], key_minus.inputs[0])
    factor = math_node("MULTIPLY_ADD", "Key Factor", (x + 2860, -300.0))
    links.new(key_minus.outputs[0], factor.inputs[0])
    links.new(amount.outputs[0], factor.inputs[1])
    factor.inputs[2].default_value = 1.0

    atlas_alpha = math_node("MULTIPLY", "Atlas Alpha", (x + 2640, 0.0))
    links.new(texture.outputs["Alpha"], atlas_alpha.inputs[0])
    links.new(alpha_attr.outputs["Fac"], atlas_alpha.inputs[1])
    keyed = math_node("MULTIPLY", "Keyed Alpha", (x + 3080, 0.0), clamp=True)
    links.new(atlas_alpha.outputs[0], keyed.inputs[0])
    links.new(factor.outputs[0], keyed.inputs[1])
    clipped = math_node("MULTIPLY", "Clipped Alpha", (x + 3300, 0.0))
    links.new(keyed.outputs[0], clipped.inputs[0])
    links.new(clip_loss.outputs[0], clipped.inputs[1])

    alpha = node("ShaderNodeMix", "Alpha", (x + 3520, -200.0), data_type="FLOAT")
    links.new(atlas_attr.outputs["Fac"], alpha.inputs["Factor"])
    links.new(alpha_attr.outputs["Fac"], alpha.inputs["A"])
    links.new(clipped.outputs[0], alpha.inputs["B"])
    color = node("ShaderNodeMix", "Color", (x + 3520, 200.0), data_type="RGBA")
    links.new(atlas_attr.outputs["Fac"], color.inputs["Factor"])
    links.new(color_attr.outputs["Color"], color.inputs["A"])
    links.new(texture.outputs["Color"], color.inputs["B"])

    emission = node("ShaderNodeEmission", "Emission", (x + 3800, 300.0))
    links.new(color.outputs["Result"], emission.inputs["Color"])
    glow_emission = node("ShaderNodeEmission", "Glow Emission", (x + 3800, 60.0))
    links.new(color.outputs["Result"], glow_emission.inputs["Color"])
    links.new(alpha.outputs["Result"], glow_emission.inputs["Strength"])
    transparent = node("ShaderNodeBsdfTransparent", "Transparent", (x + 3800, -180.0))
    over = node("ShaderNodeMixShader", "Over", (x + 4060, 200.0))
    links.new(alpha.outputs["Result"], over.inputs["Fac"])
    links.new(transparent.outputs["BSDF"], over.inputs[1])
    links.new(emission.outputs["Emission"], over.inputs[2])
    add = node("ShaderNodeAddShader", "Add", (x + 4060, -60.0))
    links.new(transparent.outputs["BSDF"], add.inputs[0])
    links.new(glow_emission.outputs["Emission"], add.inputs[1])
    result = node("ShaderNodeMixShader", "Glow Mix", (x + 4300, 80.0))
    links.new(glow_attr.outputs["Fac"], result.inputs["Fac"])
    links.new(over.outputs["Shader"], result.inputs[1])
    links.new(add.outputs["Shader"], result.inputs[2])
    output = node("ShaderNodeOutputMaterial", "Material Output", (x + 4540, 80.0))
    links.new(result.outputs["Shader"], output.inputs["Surface"])


def _material_node(material, tag):
    try:
        return next((item for item in material.node_tree.nodes if bool(item.get(tag, False))), None)
    except FBP_DATA_ERRORS:
        return None


# --------------------------------------------------------------------------
# Sync
# --------------------------------------------------------------------------

_TIMING_CACHE = {}
_PATHS_CACHE = {}


def _native_timing(material):
    try:
        key = (
            int(material.as_pointer()),
            str(material.get("fbp_native_playback_signature", "") or ""),
            int(material.get("fbp_native_frame_start", 1) or 1),
            str(material.get("fbp_native_loop_mode", "") or ""),
            str(material.get("fbp_native_source_indices_json", "") or ""),
            int(material.get("fbp_native_frame_number_base", 1) or 1),
        )
    except FBP_DATA_ERRORS:
        return None
    if key not in _TIMING_CACHE:
        try:
            from .native_backend import fbp_native_playback_timing
            timing = fbp_native_playback_timing(material)
        except (ImportError, *FBP_DATA_ERRORS):
            timing = None
        if len(_TIMING_CACHE) >= 256:
            _TIMING_CACHE.clear()
        _TIMING_CACHE[key] = timing
    return _TIMING_CACHE[key]


def _source_paths(material):
    """``(frame_number_base, paths)`` of a native sequence, cached."""
    try:
        key = (
            int(material.as_pointer()),
            str(material.get("fbp_native_source_sequence_json", "") or ""),
            int(material.get("fbp_native_frame_number_base", 1) or 1),
        )
    except FBP_DATA_ERRORS:
        return None
    if key not in _PATHS_CACHE:
        result = None
        try:
            from . import native_backend as native
            directory, files = native._source_sequence_from_material(material)
            if directory and files:
                base = int(native._material_frame_number_base(material))
                result = (base, tuple(
                    os.path.abspath(str(native._media_path(directory, name))) for name in files
                ))
        except (ImportError, AttributeError, OSError, *FBP_DATA_ERRORS):
            result = None
        if len(_PATHS_CACHE) >= 256:
            _PATHS_CACHE.clear()
        _PATHS_CACHE[key] = result
    return _PATHS_CACHE[key]


def _rendering():
    try:
        return bool(bpy.app.is_job_running("RENDER"))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def _input(modifier, node_group, name, default):
    geo = _geo()
    identifier = geo._fbp_interface_input_identifier(node_group, name)
    value = geo._fbp_modifier_input_get(modifier, identifier, None) if identifier else None
    return default if value is None else value


def _settings(modifier, node_group):
    return (
        max(1, min(512, int(_input(modifier, node_group, "Slices", 1)))),
        int(_input(modifier, node_group, "Frame Step", 1)),
        bool(_input(modifier, node_group, "Fixed Start", False)),
        int(_input(modifier, node_group, "Start Frame", 1)),
        max(0, min(8, int(_input(modifier, node_group, "Detail", 5)))),
        bool(_input(modifier, node_group, "Show Plane", True)),
    )


def _positions(base, cycle, loop, step, first, count):
    result = []
    for index in range(first, count):
        q = int(base) - index * int(step)
        if loop and cycle > 0:
            q %= cycle
        if q < 0 or (cycle > 0 and q >= cycle):
            continue
        result.append(q)
    return result


def _wrap_mode(source_node):
    extension = str(getattr(source_node, "extension", "EXTEND") or "EXTEND").upper()
    return {"EXTEND": 0.0, "CLIP": 1.0, "REPEAT": 2.0, "MIRROR": 3.0}.get(extension, 0.0)


def fbp_frame_stack_sync(rig, modifier, scene=None, *, blocking=None):
    """Point Frame Stack at the playback position of the layer's source.

    Slices step through what the plane plays, not through file numbers: an
    image sequence follows its timing order (reordered and repeated rows,
    loops, blank frames), a video steps through its frames. Fixed Start reads
    the position shown at Start Frame. Returns True when an input changed.
    """
    geo = _geo()
    node_group = getattr(modifier, "node_group", None) if modifier else None
    if not node_group:
        return False
    interface_inputs = geo._fbp_interface_inputs(node_group)
    if "Use Atlas" not in interface_inputs:
        return False
    plane = geo._fbp_plane(rig)
    if not plane:
        return False
    if blocking is None:
        blocking = bool(getattr(bpy.app, "background", False)) or _rendering()
    scene = scene or getattr(bpy.context, "scene", None)
    slices, step, fixed, start_frame, detail, show_plane = _settings(modifier, node_group)
    _SIGNATURES[int(modifier.as_pointer())] = (slices, step, fixed, start_frame, detail, show_plane)
    try:
        timeline_frame = int(getattr(scene, "frame_current", 1))
    except FBP_DATA_ERRORS:
        timeline_frame = 1

    material, source_node = geo._fbp_material_image_node(rig)
    try:
        source_image = getattr(source_node, "image", None) if source_node else None
        source_kind = str(getattr(source_image, "source", "") or "").upper()
        src_user = getattr(source_node, "image_user", None) if source_node else None
    except FBP_DATA_ERRORS:
        source_image, source_kind, src_user = None, "", None
    timing = _native_timing(material) if source_kind == "SEQUENCE" and material is not None else None

    if timing:
        from .native_backend import fbp_native_playback_position
        position = fbp_native_playback_position(timing, timeline_frame)
        start_position = fbp_native_playback_position(timing, start_frame)
        cycle = len(timing["files"])
        loop = timing["loop_mode"] in {"REPEAT", "PINGPONG"}
    elif source_kind == "MOVIE" and src_user is not None:
        try:
            cycle = max(1, int(getattr(source_image, "frame_duration", 0) or 0))
            loop = bool(getattr(src_user, "use_cyclic", False))
        except FBP_DATA_ERRORS:
            cycle, loop = 0, False

        def movie_position(frame):
            value = geo._fbp_geometry_image_frame(src_user, frame) - 1
            if cycle:
                value = value % cycle if loop else max(0, min(cycle - 1, value))
            return value

        position, start_position = movie_position(timeline_frame), movie_position(start_frame)
    elif source_kind == "SEQUENCE" and src_user is not None:
        # A sequence without native timing steps through file numbers.
        position = geo._fbp_geometry_image_frame(src_user, timeline_frame) - 1
        start_position = geo._fbp_geometry_image_frame(src_user, start_frame) - 1
        cycle, loop = 0, False
    else:
        position, start_position, cycle, loop = 0, 0, 1, False

    values = {
        "Stack Position": int(position),
        "Start Position": int(start_position),
        "Cycle Length": int(cycle),
        "Loop": bool(loop),
    }
    atlas_state = None
    if timing:
        atlas_state = _sync_atlas(
            rig, modifier, plane, material, source_node, source_image, timing,
            start_position if fixed else position, cycle, loop,
            slices, step, detail, show_plane, blocking,
        )
    if atlas_state is not None:
        atlas, table_image, table_rows, wrote = atlas_state
        values.update({
            "Use Atlas": True,
            "Atlas Columns": atlas.columns,
            "Atlas Rows": atlas.rows,
            "Atlas Width": atlas.columns * atlas.cell_w,
            "Atlas Height": atlas.rows * atlas.cell_h,
            "Cell Width": atlas.cell_w,
            "Cell Height": atlas.cell_h,
            "Table Rows": int(table_rows),
        })
    else:
        table_image, wrote = None, False
        values["Use Atlas"] = False

    # New pixels in the timing table change which slices exist.
    changed = bool(wrote)
    table_node = None
    try:
        table_node = next(
            (item for item in node_group.nodes if bool(item.get("fbp_frame_stack_table_node", False))), None,
        )
    except FBP_DATA_ERRORS:
        table_node = None
    if table_node is not None:
        image_input = geo._fbp_node_socket(getattr(table_node, "inputs", ()), "Image")
        try:
            if image_input is not None and getattr(image_input, "default_value", None) is not table_image:
                image_input.default_value = table_image
                changed = True
        except FBP_DATA_ERRORS:
            pass
    for socket_name, value in values.items():
        changed = geo._fbp_set_modifier_input(
            modifier, node_group, socket_name, value, interface_inputs,
        ) or changed
    if changed:
        try:
            node_group.update_tag()
        except FBP_DATA_ERRORS:
            pass
    return changed


def _sync_atlas(rig, modifier, plane, material, source_node, source_image, timing,
                base, cycle, loop, slices, step, detail, show_plane, blocking):
    """Bring the layer's atlas and timing table up to date; ``None`` if unusable."""
    paths = _source_paths(material)
    if not paths:
        return None
    frame_base, files = paths

    def path_at(position):
        index = int(timing["files"][position]) - int(frame_base)
        return files[index] if 0 <= index < len(files) else None

    by_position = [path_at(q) for q in range(cycle)]
    visible = timing["visible"]
    first = 1 if show_plane else 0
    needed = []
    for q in _positions(base, cycle, loop, step, first, slices):
        path = by_position[q]
        if path is not None and visible[q] and path not in needed:
            needed.append(path)
    distinct = []
    seen = set()
    for q, path in enumerate(by_position):
        if path is not None and visible[q] and path not in seen:
            seen.add(path)
            distinct.append(path)
    reference = needed[0] if needed else (distinct[0] if distinct else None)
    size = _source_size(reference) if reference else None
    if size is None:
        return None
    width, height, is_float = size
    budget = _RENDER_ATLAS_PIXEL_BUDGET if _rendering() else _ATLAS_PIXEL_BUDGET
    try:
        settings = source_image.colorspace_settings if source_image else None
        colorspace = str(settings.name) if settings else "sRGB"
        if settings is not None and bool(getattr(settings, "is_data", False)):
            colorspace = "Non-Color"
        alpha_mode = str(getattr(source_image, "alpha_mode", "STRAIGHT") or "STRAIGHT")
    except FBP_DATA_ERRORS:
        colorspace, alpha_mode = "sRGB", "STRAIGHT"
    if is_float:
        alpha_mode = "PREMUL"
    elif alpha_mode not in {"STRAIGHT", "NONE", "CHANNEL_PACKED"}:
        alpha_mode = "STRAIGHT"

    owner = _owner(plane)
    key = (owner, int(plane.as_pointer()))
    atlas = _STACKS.get(key)
    source_signature = (files, width, height, is_float)
    # A one level lower Detail (Playback quality) keeps the current cells.
    reuse = (
        atlas is not None
        and atlas.layout[0] == source_signature
        and atlas.layout[1] - 1 <= detail <= atlas.layout[1]
        and atlas.columns * atlas.rows >= len(needed)
    )
    if not reuse:
        # Renders and background runs read only what the frame shows.
        wanted = len(needed) if blocking else len(distinct)
        cell_w, cell_h, factor, columns, rows, capacity = _layout(
            width, height, detail, len(needed), wanted, budget,
        )
        atlas = _Atlas(
            (source_signature, detail, capacity), cell_w, cell_h, columns, rows,
            factor, is_float, capacity,
        )
        _STACKS[key] = atlas
    capacity = atlas.columns * atlas.rows

    try:
        image = _atlas_image(owner, atlas, colorspace, alpha_mode)
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not create the Frame Stack atlas", exc)
        return None
    if atlas.image_name != image.name:
        atlas.image_name = image.name
        atlas.dirty = True

    job = (atlas.factor, atlas.cell_w, atlas.cell_h, is_float)
    if blocking:
        _prefetch_many([(path, *job) for path in needed if path not in atlas.cells], True)
    protected = set(needed)
    waiting = False
    for path in needed:
        if path in atlas.cells:
            atlas.lru.move_to_end(path)
            continue
        data = _request(path, *job, blocking)
        if data is None:
            waiting = waiting or not blocking and _FAILED.get(path) is None
            continue
        atlas.place(path, data, protected)
    if not blocking and len(distinct) <= capacity:
        # Everything fits: read the rest in the background, so later
        # playback only moves the slices.
        rest = [path for path in distinct if path not in atlas.cells]
        for path in rest:
            data = _cached_thumb(_thumb_key(path, atlas.factor))
            if data is not None:
                atlas.place(path, data, protected)
        rest = [path for path in rest if path not in atlas.cells]
        if rest:
            _prefetch_many([(path, *job) for path in rest], False)
            waiting = True
    if waiting:
        _WAITING[(rig.name, modifier.name)] = True
        _ensure_poll()
    try:
        wrote = bool(atlas.dirty)
        if atlas.dirty:
            _write_atlas(image, atlas)
        previous_table = atlas.table_signature
        table_image, table_rows = _write_table(owner, atlas, by_position, visible, atlas.cells)
        wrote = wrote or atlas.table_signature != previous_table
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not write the Frame Stack atlas", exc)
        return None

    frame_material = fbp_frame_stack_material(rig)
    if frame_material is not None:
        texture = _material_node(frame_material, "fbp_frame_stack_atlas_node")
        if texture is not None and texture.image is not image:
            texture.image = image
        # Pixel art stays crisp: Closest sources sample the atlas the same way.
        interpolation = "Closest" if str(getattr(source_node, "interpolation", "")) == "Closest" else "Linear"
        if texture is not None and texture.interpolation != interpolation:
            texture.interpolation = interpolation
        wrap = _material_node(frame_material, "fbp_frame_stack_wrap_node")
        mode = _wrap_mode(source_node)
        if wrap is not None and abs(float(wrap.outputs[0].default_value) - mode) > 1e-6:
            wrap.outputs[0].default_value = mode
    return atlas, table_image, table_rows, wrote


def fbp_frame_stack_reset():
    """Forget every atlas (after Undo or file load: generated pixels are gone)."""
    _STACKS.clear()
    _IMAGE_NAMES.clear()
    _SIGNATURES.clear()
    _WAITING.clear()
    _TIMING_CACHE.clear()
    _PATHS_CACHE.clear()


def fbp_frame_stack_shutdown():
    fbp_frame_stack_reset()
    for future in tuple(_PENDING.values()):
        future.cancel()
    _PENDING.clear()
    executor = _EXECUTOR[0]
    _EXECUTOR[0] = None
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)
    if _POLL_REGISTERED[0]:
        try:
            if bpy.app.timers.is_registered(_poll):
                bpy.app.timers.unregister(_poll)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        _POLL_REGISTERED[0] = False
    with _LOCK:
        _THUMBS.clear()
        _THUMB_BYTES[0] = 0


def fbp_frame_stack_inputs_changed(modifier):
    """True when the inputs the runtime reads differ from the last sync."""
    node_group = getattr(modifier, "node_group", None)
    if node_group is None:
        return False
    try:
        current = _settings(modifier, node_group)
    except FBP_DATA_ERRORS:
        return False
    return _SIGNATURES.get(int(modifier.as_pointer())) != current
