"""Image cache check and frame preload for smooth image sequence playback.

Blender keeps decoded image sequence frames in its Memory Cache (Preferences >
System > Memory & Limits, 4 GB by default). When the frames a scene shows do
not fit, playback reaches the frame where the cache is full and from there
decodes every image again from disk on each frame: a few layers of HD PNGs then
drop to 8-10 fps. This module estimates the memory the visible sequences need
for the playback range, offers to raise the limit to fit, and can decode every
frame up front so even the first playback runs from the cache.

Nothing here changes the scene or the render: only the user preference (on an
explicit click) and Blender's in-memory image cache.
"""

from __future__ import annotations

import math
import os
import time

import bpy
from bpy.types import Operator

from .registration import register_classes, unregister_classes
from .runtime import FBP_DATA_ERRORS, fbp_render_mutation_blocked, fbp_undo_guard_active


_MIB = 1024 * 1024
_ESTIMATE_TTL_SECONDS = 2.0
_ESTIMATE_CACHE = {}
_PRELOAD_TICK_SECONDS = 0.04
# Headroom on top of the estimate: Blender stores a little more than the pixels
# and other images (UI, Grease Pencil, compositor) share the same cache.
_CACHE_HEADROOM = 1.15
_CACHE_EXTRA_MB = 512
_CACHE_STEP_MB = 512
# Never suggest more than this share of the computer's memory.
_RAM_SHARE = 0.75

_registered_classes = []


def fbp_physical_memory_mb():
    """Return the computer's physical memory in MB, or 0 when unknown."""
    try:
        if os.name == "nt":
            import ctypes

            class _MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemoryStatus()
            status.dwLength = ctypes.sizeof(_MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys // _MIB)
            return 0
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        if pages > 0 and page_size > 0:
            return int(pages * page_size // _MIB)
    except (AttributeError, OSError, ValueError, ImportError):
        pass
    return 0


def _memory_cache_limit_mb(context=None):
    try:
        preferences = getattr(context or bpy.context, "preferences", None)
        return int(preferences.system.memory_cache_limit)
    except FBP_DATA_ERRORS:
        return 0


def _playback_range(scene):
    try:
        if bool(getattr(scene, "use_preview_range", False)):
            start, end = int(scene.frame_preview_start), int(scene.frame_preview_end)
        else:
            start, end = int(scene.frame_start), int(scene.frame_end)
    except FBP_DATA_ERRORS:
        return 1, 0
    return start, max(start, end)


def _offset_curve(tree, node):
    """Return the F-Curve that animates the node's Image Offset, if any."""
    try:
        animation_data = getattr(tree, "animation_data", None)
        action = getattr(animation_data, "action", None) if animation_data else None
        if action is None:
            return None
        from bpy_extras import anim_utils
        channelbag = anim_utils.action_get_channelbag_for_slot(action, animation_data.action_slot)
        if channelbag is None:
            return None
        path = f'nodes["{node.name}"].image_user.frame_offset'
        for curve in channelbag.fcurves:
            if curve.data_path == path and not bool(curve.mute):
                return curve
    except (ImportError, AttributeError, *FBP_DATA_ERRORS):
        return None
    return None


def _image_frame_number(image_user, scene_frame, offset):
    """Blender's image sequence frame for ``scene_frame`` (image_user frame calc)."""
    length = int(image_user.frame_duration)
    if length <= 0:
        return 0
    frame = int(scene_frame) - int(image_user.frame_start) + 1
    if bool(image_user.use_cyclic):
        frame %= length
        if frame < 0:
            frame += length
        if frame == 0:
            frame = length
    frame = max(0, min(length, frame))
    return frame + int(offset)


def _scene_sequence_textures(scene):
    """Yield (image, image_user, offset_curve) for sequences visible in ``scene``."""
    seen_nodes = set()
    for obj in tuple(getattr(scene, "objects", ()) or ()):
        try:
            if getattr(obj, "type", "") != "MESH" or not obj.visible_get():
                continue
            materials = [slot.material for slot in obj.material_slots if slot.material]
        except FBP_DATA_ERRORS:
            continue
        for material in materials:
            tree = getattr(material, "node_tree", None)
            if tree is None:
                continue
            try:
                nodes = tuple(tree.nodes)
            except FBP_DATA_ERRORS:
                continue
            for node in nodes:
                try:
                    if node.type != "TEX_IMAGE" or bool(node.mute):
                        continue
                    image = node.image
                    if image is None or image.source not in {"SEQUENCE", "MOVIE"}:
                        continue
                    key = (material.name, node.name)
                    if key in seen_nodes:
                        continue
                    seen_nodes.add(key)
                    yield image, node.image_user, _offset_curve(tree, node)
                except FBP_DATA_ERRORS:
                    continue


def _png_header_size(image):
    """Return (width, height, bytes_per_pixel) from a PNG file header.

    Blender reads a sequence's size only once a frame is decoded; the header
    gives it before the viewport has drawn the layer. 16-bit PNGs decode to
    float pixels (16 bytes each).
    """
    try:
        path = bpy.path.abspath(str(image.filepath or ""), library=image.library)
        with open(path, "rb") as handle:
            header = handle.read(26)
    except (OSError, ValueError, *FBP_DATA_ERRORS):
        return 0, 0, 4
    if len(header) < 26 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        return 0, 0, 4
    width = int.from_bytes(header[16:20], "big")
    height = int.from_bytes(header[20:24], "big")
    bytes_per_pixel = 16 if header[24] == 16 else 4
    return width, height, bytes_per_pixel


def _scene_key(scene):
    try:
        return (int(scene.as_pointer()), str(scene.name_full))
    except FBP_DATA_ERRORS:
        return (0, "")


def fbp_playback_frame_plan(scene):
    """Return ``{image_name: sorted frame numbers}`` the playback range shows."""
    start, end = _playback_range(scene)
    plan = {}
    for image, image_user, curve in _scene_sequence_textures(scene):
        frames = plan.setdefault(image.name, set())
        try:
            constant = int(image_user.frame_offset)
            for scene_frame in range(start, end + 1):
                offset = int(round(curve.evaluate(scene_frame))) if curve is not None else constant
                number = _image_frame_number(image_user, scene_frame, offset)
                if number > 0:
                    frames.add(number)
        except FBP_DATA_ERRORS:
            continue
    return {name: tuple(sorted(frames)) for name, frames in plan.items() if frames}


def fbp_playback_cache_estimate(scene, context=None, *, use_cache=True):
    """Estimate the decoded memory the visible sequences need for playback.

    Returns a dict with ``images``, ``frames``, ``needed_mb``, ``limit_mb``,
    ``target_mb``, ``ram_mb``, ``fits`` and ``unknown_size`` (sequences whose
    size Blender has not read yet).
    """
    key = _scene_key(scene)
    start, end = _playback_range(scene)
    limit_mb = _memory_cache_limit_mb(context)
    now = time.monotonic()
    cached = _ESTIMATE_CACHE.get(key) if use_cache else None
    if (
        cached is not None
        and cached.get("range") == (start, end)
        and cached.get("limit_mb") == limit_mb
        and now - float(cached.get("at", 0.0)) <= _ESTIMATE_TTL_SECONDS
    ):
        return cached

    plan = fbp_playback_frame_plan(scene)
    total_bytes = 0
    frame_count = 0
    unknown = 0
    for name, frames in plan.items():
        image = bpy.data.images.get(name)
        try:
            width, height = (int(value) for value in tuple(image.size)[:2])
            bytes_per_pixel = 16 if bool(image.is_float) else 4
        except (TypeError, ValueError, *FBP_DATA_ERRORS):
            width = height = 0
            bytes_per_pixel = 4
        frame_count += len(frames)
        if (width <= 0 or height <= 0) and image is not None:
            width, height, bytes_per_pixel = _png_header_size(image)
        if width <= 0 or height <= 0:
            unknown += 1
            continue
        total_bytes += width * height * bytes_per_pixel * len(frames)

    needed_mb = int(math.ceil(total_bytes * _CACHE_HEADROOM / _MIB)) if total_bytes else 0
    ram_mb = fbp_physical_memory_mb()
    target_mb = 0
    if needed_mb:
        target_mb = int(math.ceil((needed_mb + _CACHE_EXTRA_MB) / _CACHE_STEP_MB) * _CACHE_STEP_MB)
        if ram_mb:
            cap = int(ram_mb * _RAM_SHARE) // _CACHE_STEP_MB * _CACHE_STEP_MB
            target_mb = min(target_mb, max(cap, limit_mb))
    estimate = {
        "range": (start, end),
        "at": now,
        "images": len(plan),
        "frames": frame_count,
        "needed_mb": needed_mb,
        "limit_mb": limit_mb,
        "target_mb": target_mb,
        "ram_mb": ram_mb,
        # A limit of 0 means no limit in Blender.
        "fits": bool(limit_mb == 0 or needed_mb <= limit_mb),
        "can_fit": bool(target_mb >= needed_mb),
        "unknown_size": unknown,
    }
    if len(_ESTIMATE_CACHE) > 16:
        _ESTIMATE_CACHE.clear()
    _ESTIMATE_CACHE[key] = estimate
    return estimate


def _format_gb(megabytes):
    return f"{float(megabytes) / 1024.0:.1f} GB"


def fbp_draw_playback_cache(layout, context):
    """Rows for the Timeline's Playback popover."""
    scene = getattr(context, "scene", None)
    if scene is None:
        return
    try:
        estimate = fbp_playback_cache_estimate(scene, context)
    except FBP_DATA_ERRORS:
        return
    if not estimate.get("images"):
        return
    layout.separator()
    column = layout.column(align=True)
    needed = int(estimate["needed_mb"])
    limit = int(estimate["limit_mb"])
    row = column.row()
    if not estimate["fits"]:
        row.alert = True
        row.label(
            text=f"Image Cache: needs {_format_gb(needed)}, limit {_format_gb(limit)}",
            icon="ERROR",
        )
        target = int(estimate["target_mb"])
        if target > limit:
            column.operator(
                "fbp.playback_cache_raise",
                text=f"Raise Cache to {_format_gb(target)}",
                icon="MEMORY",
            )
    else:
        row.label(
            text=f"Image Cache: {_format_gb(needed)} of {_format_gb(limit) if limit else 'no limit'}",
            icon="CHECKMARK",
        )
    column.operator("fbp.playback_preload", text="Preload Frames", icon="IMPORT")


class FBP_OT_PlaybackCacheRaise(Operator):
    bl_idname = "fbp.playback_cache_raise"
    bl_label = "Raise Image Cache"
    bl_description = (
        "Raise Blender's Memory Cache Limit so every image sequence frame the "
        "playback range shows stays decoded in memory. Without it, playback "
        "slows down from the frame where the cache is full"
    )
    bl_options = {"REGISTER"}

    def execute(self, context):
        estimate = fbp_playback_cache_estimate(context.scene, context, use_cache=False)
        target = int(estimate.get("target_mb", 0) or 0)
        limit = int(estimate.get("limit_mb", 0) or 0)
        if target <= limit:
            self.report({"INFO"}, "The image cache is already large enough")
            return {"CANCELLED"}
        try:
            context.preferences.system.memory_cache_limit = target
            context.preferences.is_dirty = True
        except FBP_DATA_ERRORS as exc:
            self.report({"ERROR"}, f"Could not change the Memory Cache Limit: {exc}")
            return {"CANCELLED"}
        _ESTIMATE_CACHE.clear()
        if estimate.get("can_fit"):
            self.report({"INFO"}, f"Memory Cache Limit set to {_format_gb(target)}")
        else:
            self.report(
                {"WARNING"},
                (
                    f"Memory Cache Limit set to {_format_gb(target)}, 75% of this "
                    f"computer's memory; the sequences need {_format_gb(estimate['needed_mb'])}, "
                    "so the last frames will still load from disk"
                ),
            )
        return {"FINISHED"}


class FBP_OT_PlaybackPreload(Operator):
    bl_idname = "fbp.playback_preload"
    bl_label = "Preload Frames"
    bl_description = (
        "Decode every image sequence frame the playback range shows into "
        "Blender's image cache, so even the first playback does not wait for "
        "the disk. Esc stops it"
    )
    bl_options = {"REGISTER"}

    _timer = None
    _queue = ()
    _index = 0
    _started = 0.0

    @classmethod
    def poll(cls, context):
        if getattr(context, "scene", None) is None or getattr(context, "window", None) is None:
            return False
        if bool(getattr(bpy.app, "background", False)):
            cls.poll_message_set("Preloading needs the viewport")
            return False
        screen = getattr(context, "screen", None)
        if screen is not None and bool(getattr(screen, "is_animation_playing", False)):
            cls.poll_message_set("Stop playback first")
            return False
        return True

    def invoke(self, context, _event):
        if fbp_undo_guard_active() or fbp_render_mutation_blocked():
            self.report({"WARNING"}, "Wait until the render or Undo has finished")
            return {"CANCELLED"}
        plan = fbp_playback_frame_plan(context.scene)
        self._queue = tuple(
            (name, number) for name, numbers in plan.items() for number in numbers
        )
        if not self._queue:
            self.report({"INFO"}, "No visible image sequence to preload")
            return {"CANCELLED"}
        estimate = fbp_playback_cache_estimate(context.scene, context, use_cache=False)
        if not estimate.get("fits"):
            self.report(
                {"WARNING"},
                "The image cache is smaller than these frames: raise it first or only part will stay loaded",
            )
        self._index = 0
        self._started = time.monotonic()
        wm = context.window_manager
        wm.progress_begin(0, len(self._queue))
        self._timer = wm.event_timer_add(0.001, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _finish(self, context, cancelled=False):
        wm = context.window_manager
        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None
        wm.progress_end()
        try:
            context.workspace.status_text_set(None)
        except FBP_DATA_ERRORS:
            pass
        _ESTIMATE_CACHE.clear()
        seconds = time.monotonic() - self._started
        if cancelled:
            self.report({"INFO"}, f"Preload stopped after {self._index} of {len(self._queue)} frames")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Preloaded {len(self._queue)} frames in {seconds:.1f} s")
        return {"FINISHED"}

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"}:
            return self._finish(context, cancelled=True)
        if event.type != "TIMER":
            return {"RUNNING_MODAL"}
        if fbp_undo_guard_active() or fbp_render_mutation_blocked():
            return self._finish(context, cancelled=True)
        deadline = time.perf_counter() + _PRELOAD_TICK_SECONDS
        images = bpy.data.images
        while self._index < len(self._queue) and time.perf_counter() < deadline:
            name, number = self._queue[self._index]
            self._index += 1
            image = images.get(name)
            if image is None:
                continue
            try:
                # Loading the GPU texture decodes the frame through Blender's
                # image cache; the texture itself is freed straight away.
                image.gl_load(frame=int(number))
                image.gl_free()
            except FBP_DATA_ERRORS:
                continue
        context.window_manager.progress_update(self._index)
        try:
            context.workspace.status_text_set(
                f"Preloading frames {self._index} / {len(self._queue)} (Esc to stop)"
            )
        except FBP_DATA_ERRORS:
            pass
        if self._index >= len(self._queue):
            return self._finish(context)
        return {"RUNNING_MODAL"}


_classes = (FBP_OT_PlaybackCacheRaise, FBP_OT_PlaybackPreload)


def register():
    _ESTIMATE_CACHE.clear()
    _registered_classes.clear()
    _registered_classes.extend(register_classes(_classes))


def unregister():
    _ESTIMATE_CACHE.clear()
    unregister_classes(tuple(_registered_classes))
    _registered_classes.clear()


__all__ = (
    "FBP_OT_PlaybackCacheRaise",
    "FBP_OT_PlaybackPreload",
    "fbp_draw_playback_cache",
    "fbp_physical_memory_mb",
    "fbp_playback_cache_estimate",
    "fbp_playback_frame_plan",
    "register",
    "unregister",
)
