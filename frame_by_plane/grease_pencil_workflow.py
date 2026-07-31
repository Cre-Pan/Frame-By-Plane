"""Ink Over Image and Grease Pencil timing workflow for Frame By Plane.

This module deliberately builds on Blender's native Grease Pencil frames.  It
never replaces artist-authored drawings and keeps destructive retiming behind
explicit operators with Undo support.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import time

import bpy
try:
    from bpy.app.handlers import persistent
except (ImportError, AttributeError):
    def persistent(callback):
        return callback
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator, Panel

from .runtime import (
    FBP_DATA_ERRORS,
    fbp_obj_runtime_key,
    fbp_render_mutation_blocked,
    fbp_set_rna_property_silent,
    fbp_undo_guard_active,
    fbp_warn,
)
from .fbp_index import iter_scene_gp_canvases
from .registration import (
    register_classes,
    remove_handlers_by_name,
    unregister_classes,
    unregister_type_properties,
)
from .service_registry import service_descriptor
from .layers import get_selected_fbp_roots
from .ui_style import configure_layout, hint_row, section_gap, section_header
from .grease_pencil_bridge import (
    KEY_REFERENCE_OPACITY,
    gp_canvas_for_rig,
    gp_canvas_owner,
    is_gp_canvas,
    mark_gp_mask_dirty,
)


SERVICE_ID = "grease_pencil_workflow"
SERVICE_API_VERSION = 1
CAPABILITIES = ("INK_OVER_IMAGE", "TIMING_SYNC", "MISSING_DRAWINGS", "REFERENCE_STATES", "AUTO_SOURCE_SYNC", "FPS_CHANGE_DETECTION")
FBP_GP_WORKFLOW_SCHEMA_VERSION = 2

KEY_WORKFLOW_SCHEMA = "fbp_gp_workflow_schema"
KEY_REFERENCE_HIDDEN = "fbp_gp_workflow_reference_hidden"
KEY_LAST_STATE = "fbp_gp_workflow_last_state"

WORKFLOW_STATE_ITEMS = (
    ("REFERENCE", "Reference", "Show the source image at its original opacity while keeping the linked drawing available", "IMAGE_BACKGROUND", 0),
    ("INK", "Ink", "Dim the source image and draw on the linked Grease Pencil canvas", "GREASEPENCIL", 1),
    ("FINAL", "Final", "Hide the source image in the viewport and inspect the Grease Pencil result", "RESTRICT_VIEW_ON", 2),
)
MISSING_DRAWING_ITEMS = (
    ("BLANK", "Blank", "Create empty Grease Pencil drawings at missing source exposures"),
    ("DUPLICATE_PREVIOUS", "Duplicate Previous", "Copy the nearest previous explicit Grease Pencil drawing into each missing exposure"),
)

_RNA_PROPERTIES = (
    "fbp_gp_workflow_state",
    "fbp_gp_reference_visible",
    "fbp_gp_timing_offset",
    "fbp_gp_missing_drawing_mode",
    "fbp_gp_timing_layer_name",
    "fbp_gp_last_timing_report",
    "fbp_gp_auto_sync_timing",
    "fbp_gp_timing_fingerprint",
)


_AUTO_TIMING_CANVAS_CACHE = {}
_AUTO_TIMING_CANVAS_CACHE_TTL = 8.0


def _auto_timing_scene_key(scene):
    try:
        return (
            int(fbp_obj_runtime_key(scene) or 0),
            str(getattr(scene, "name_full", getattr(scene, "name", "")) or ""),
        )
    except FBP_DATA_ERRORS:
        return (0, "")


def _clear_auto_timing_canvas_cache(scene=None):
    if scene is None:
        _AUTO_TIMING_CANVAS_CACHE.clear()
        return
    key = _auto_timing_scene_key(scene)
    if key[0]:
        _AUTO_TIMING_CANVAS_CACHE.pop(key, None)


def _iter_auto_timing_canvases(scene):
    """Return enabled timing canvases without rescanning the Scene each tick."""
    if scene is None:
        return ()
    try:
        object_count = len(scene.objects)
    except FBP_DATA_ERRORS:
        return ()
    key = _auto_timing_scene_key(scene)
    now = time.monotonic()
    cached = _AUTO_TIMING_CANVAS_CACHE.get(key) if key[0] else None
    if cached is not None:
        try:
            if (
                int(cached.get("object_count", -1)) == object_count
                and now - float(cached.get("checked_at", 0.0) or 0.0)
                <= _AUTO_TIMING_CANVAS_CACHE_TTL
            ):
                names = tuple(cached.get("names", ()) or ())
                resolved = tuple(
                    canvas for name in names
                    for canvas in (scene.objects.get(str(name)),)
                    if canvas is not None
                    and is_gp_canvas(canvas)
                    and bool(getattr(canvas, "fbp_gp_auto_sync_timing", False))
                )
                if len(resolved) == len(names):
                    return resolved
        except FBP_DATA_ERRORS:
            pass
    try:
        canvases = tuple(
            canvas for canvas in iter_scene_gp_canvases(scene, fallback=True)
            if is_gp_canvas(canvas)
            and bool(getattr(canvas, "fbp_gp_auto_sync_timing", False))
        )
    except FBP_DATA_ERRORS:
        canvases = ()
    if key[0]:
        if len(_AUTO_TIMING_CANVAS_CACHE) >= 32 and key not in _AUTO_TIMING_CANVAS_CACHE:
            _AUTO_TIMING_CANVAS_CACHE.clear()
        _AUTO_TIMING_CANVAS_CACHE[key] = {
            "object_count": object_count,
            "checked_at": now,
            "names": tuple(str(getattr(canvas, "name", "") or "") for canvas in canvases),
        }
    return canvases


@dataclass(frozen=True)
class Exposure:
    index: int
    frame: int
    duration: int
    name: str


def service_status():
    return service_descriptor(SERVICE_ID, SERVICE_API_VERSION, CAPABILITIES)


def _active_canvas(context):
    obj = getattr(context, "object", None) if context else None
    if is_gp_canvas(obj):
        return obj
    for rig in get_selected_fbp_roots(context) if context else ():
        canvas = gp_canvas_for_rig(rig)
        if canvas is not None:
            return canvas
    return None


def _active_layer(canvas, *, remember=True):
    data = getattr(canvas, "data", None) if canvas is not None else None
    if data is None:
        return None
    preferred_name = str(getattr(canvas, "fbp_gp_timing_layer_name", "") or "")
    try:
        if preferred_name:
            preferred = data.layers.get(preferred_name)
            if preferred is not None:
                return preferred
        active = data.layers.active
        if active is not None:
            if remember and getattr(canvas, "fbp_gp_timing_layer_name", "") != active.name:
                canvas.fbp_gp_timing_layer_name = active.name
            return active
        for layer in data.layers:
            if remember:
                canvas.fbp_gp_timing_layer_name = layer.name
            return layer
    except FBP_DATA_ERRORS:
        return None
    return None


def plane_exposures(rig):
    """Return logical source exposure starts without evaluating playback loops."""
    if rig is None:
        return ()
    try:
        items = tuple(getattr(rig, "fbp_images", ()) or ())
        start = int(getattr(rig, "fbp_start_frame", 1) or 1)
        fallback = max(1, int(getattr(rig, "fbp_global_duration", 1) or 1))
    except FBP_DATA_ERRORS:
        return ()
    exposures = []
    cursor = start
    for index, item in enumerate(items):
        try:
            duration = max(1, int(getattr(item, "duration", fallback) or fallback))
            name = str(getattr(item, "name", "") or f"Frame {index + 1}")
        except FBP_DATA_ERRORS:
            duration = fallback
            name = f"Frame {index + 1}"
        exposures.append(Exposure(index=index, frame=cursor, duration=duration, name=name))
        cursor += duration
    return tuple(exposures)


def target_exposure_frames(canvas):
    rig = gp_canvas_owner(canvas)
    if rig is None:
        return ()
    try:
        offset = int(getattr(canvas, "fbp_gp_timing_offset", 0) or 0)
    except FBP_DATA_ERRORS:
        offset = 0
    return tuple(exposure.frame + offset for exposure in plane_exposures(rig))


def gp_frame_numbers(layer):
    if layer is None:
        return ()
    try:
        return tuple(sorted({int(frame.frame_number) for frame in layer.frames}))
    except FBP_DATA_ERRORS:
        return ()


def timing_status(canvas, *, remember_layer=True):
    layer = _active_layer(canvas, remember=remember_layer)
    targets = target_exposure_frames(canvas)
    explicit = gp_frame_numbers(layer)
    target_set = set(targets)
    explicit_set = set(explicit)
    missing = tuple(frame for frame in targets if frame not in explicit_set)
    extra = tuple(frame for frame in explicit if frame not in target_set)
    return {
        "layer": layer,
        "targets": targets,
        "explicit": explicit,
        "missing": missing,
        "extra": extra,
        "matched": len(target_set & explicit_set),
    }


def timing_source_fingerprint(canvas, scene=None):
    """Return a compact stable signature for source timing and scene FPS."""
    rig = gp_canvas_owner(canvas)
    scene = scene or getattr(bpy.context, "scene", None)
    if rig is None:
        return ""
    try:
        render = getattr(scene, "render", None)
        fps = int(getattr(render, "fps", 24) or 24) if render is not None else 24
        fps_base = float(getattr(render, "fps_base", 1.0) or 1.0) if render is not None else 1.0
        items = tuple(getattr(rig, "fbp_images", ()) or ())
        item_data = tuple(
            (
                str(getattr(item, "name", "") or ""),
                max(1, int(getattr(item, "duration", 1) or 1)),
            )
            for item in items
        )
        playback = tuple(
            (name, repr(getattr(rig, name, None)))
            for name in (
                "fbp_playback_mode",
                "fbp_loop_mode",
                "fbp_ping_pong",
                "fbp_speed",
                "fbp_frame_offset",
            )
            if hasattr(rig, name)
        )
        payload = (
            str(getattr(rig, "name", "") or ""),
            int(getattr(rig, "fbp_start_frame", 1) or 1),
            max(1, int(getattr(rig, "fbp_global_duration", 1) or 1)),
            int(getattr(canvas, "fbp_gp_timing_offset", 0) or 0),
            str(getattr(canvas, "fbp_gp_timing_layer_name", "") or ""),
            fps,
            round(fps_base, 6),
            item_data,
            playback,
        )
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    except FBP_DATA_ERRORS:
        return ""


def _timing_layer_has_applied_loop(canvas):
    layer_name = str(getattr(canvas, "fbp_gp_timing_layer_name", "") or "")
    try:
        for block in tuple(getattr(canvas, "fbp_gp_loop_blocks", ()) or ()):
            if bool(getattr(block, "applied", False)) and (
                not layer_name or str(getattr(block, "layer_name", "") or "") == layer_name
            ):
                return True
        return False
    except FBP_DATA_ERRORS:
        return True


def _run_auto_timing_sync(canvas_name):
    try:
        canvas = bpy.data.objects.get(str(canvas_name))
    except FBP_DATA_ERRORS:
        return 0.10
    if not is_gp_canvas(canvas) or not bool(getattr(canvas, "fbp_gp_auto_sync_timing", False)):
        return None
    fingerprint = timing_source_fingerprint(canvas)
    if not fingerprint:
        return None
    if _timing_layer_has_applied_loop(canvas):
        canvas.fbp_gp_last_timing_report = "Auto Sync paused: remove or rebuild Limited Loop timing first"
        canvas.fbp_gp_timing_fingerprint = fingerprint
        return None
    result = align_drawings_to_plane(canvas)
    canvas.fbp_gp_timing_fingerprint = fingerprint
    canvas.fbp_gp_last_timing_report = (
        f"Auto Sync: aligned {result['moved']} drawing(s) · "
        f"{result['missing']} missing · {result['extra']} extra"
    )
    return None


def _schedule_auto_timing_sync(canvas, *, first_interval=0.08):
    if canvas is None:
        return False
    try:
        name = str(canvas.name)
    except FBP_DATA_ERRORS:
        return False
    from .safe_tasks import schedule_once
    return schedule_once(
        f"gp_timing.auto_sync:{name}",
        lambda: _run_auto_timing_sync(name),
        first_interval=first_interval,
    )


@persistent
def _depsgraph_auto_timing_sync(scene, _depsgraph=None, *, updates=None):
    if scene is None or fbp_undo_guard_active() or fbp_render_mutation_blocked():
        return
    objects = _iter_auto_timing_canvases(scene)
    if not objects:
        return
    if updates is None:
        try:
            updates = tuple(getattr(_depsgraph, "updates", ()) or ())
        except FBP_DATA_ERRORS:
            return
    if not updates:
        return

    # Auto Sync depends only on Scene timing or the linked canvas/rig objects.
    # Most depsgraph traffic comes from materials, images, meshes and evaluated
    # viewport data; reject those updates before walking canvases or serializing
    # complete exposure fingerprints.
    scene_changed = False
    updated_object_keys = set()
    try:
        scene_key = fbp_obj_runtime_key(scene)
    except FBP_DATA_ERRORS:
        scene_key = None
    for update in updates:
        try:
            datablock = getattr(update, "id", None)
            original = getattr(datablock, "original", None)
            if original is not None:
                datablock = original
            if isinstance(datablock, bpy.types.Scene):
                if scene_key is None or fbp_obj_runtime_key(datablock) == scene_key:
                    scene_changed = True
            elif isinstance(datablock, bpy.types.Object):
                if not (
                    is_gp_canvas(datablock)
                    or bool(getattr(datablock, "is_fbp_control", False))
                    or bool(getattr(datablock, "is_fbp_plane", False))
                ):
                    continue
                key = fbp_obj_runtime_key(datablock)
                if key is not None:
                    updated_object_keys.add(key)
        except FBP_DATA_ERRORS:
            continue
    if not scene_changed and not updated_object_keys:
        return

    for canvas in objects:
        if not scene_changed:
            try:
                rig = gp_canvas_owner(canvas)
                plane = getattr(rig, "fbp_plane_target", None) if rig is not None else None
                dependency_keys = {
                    key for datablock in (canvas, rig, plane)
                    for key in (fbp_obj_runtime_key(datablock),)
                    if key is not None
                }
            except FBP_DATA_ERRORS:
                dependency_keys = set()
            if not dependency_keys.intersection(updated_object_keys):
                continue
        current = timing_source_fingerprint(canvas, scene)
        if current and current != str(getattr(canvas, "fbp_gp_timing_fingerprint", "") or ""):
            _schedule_auto_timing_sync(canvas)


def _remove_workflow_handler(handler_list, callback_name):
    return remove_handlers_by_name(
        handler_list,
        callback_name,
        module_suffix="grease_pencil_workflow",
    )


def _find_frame(layer, frame_number):
    try:
        return next((frame for frame in layer.frames if int(frame.frame_number) == int(frame_number)), None)
    except FBP_DATA_ERRORS:
        return None


def _new_frame(layer, frame_number):
    existing = _find_frame(layer, frame_number)
    if existing is not None:
        return existing, False
    try:
        try:
            frame = layer.frames.new(int(frame_number), active=True)
        except TypeError:
            frame = layer.frames.new(int(frame_number))
        return frame, True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None, False


def _move_frame(layer, source_number, destination_number):
    source_number = int(source_number)
    destination_number = int(destination_number)
    if source_number == destination_number:
        return _find_frame(layer, source_number) is not None
    if _find_frame(layer, destination_number) is not None:
        return False
    try:
        try:
            layer.frames.move(from_frame_number=source_number, to_frame_number=destination_number)
        except TypeError:
            layer.frames.move(source_number, destination_number)
        return _find_frame(layer, destination_number) is not None
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _copy_frame(layer, source_number, destination_number):
    source = _find_frame(layer, source_number)
    if source is None:
        return _new_frame(layer, destination_number)
    existing = _find_frame(layer, destination_number)
    if existing is not None:
        return existing, False
    frames = layer.frames
    try:
        try:
            copied = frames.copy(int(source_number), int(destination_number), instance_drawing=False)
        except TypeError:
            try:
                copied = frames.copy(int(source_number), int(destination_number))
            except TypeError:
                copied = frames.copy(source)
                copied_number = int(getattr(copied, "frame_number", destination_number))
                if copied_number != int(destination_number):
                    if not _move_frame(layer, copied_number, destination_number):
                        try:
                            copied.frame_number = int(destination_number)
                        except FBP_DATA_ERRORS:
                            pass
        result = _find_frame(layer, destination_number) or copied
        return result, result is not None
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        # A blank drawing is safer than failing the full synchronization. The
        # operator reports how many drawings were copied versus created blank.
        return _new_frame(layer, destination_number)


def create_missing_drawings(canvas, *, duplicate_previous=False):
    status = timing_status(canvas)
    layer = status["layer"]
    if layer is None:
        return {"created": 0, "copied": 0, "failed": len(status["missing"]), "missing": status["missing"]}
    created = copied = failed = 0
    for target in status["missing"]:
        previous = max((number for number in gp_frame_numbers(layer) if number < target), default=None)
        if duplicate_previous and previous is not None:
            _frame, changed = _copy_frame(layer, previous, target)
            if changed:
                copied += 1
            else:
                failed += 1
        else:
            _frame, changed = _new_frame(layer, target)
            if changed:
                created += 1
            else:
                failed += 1
    try:
        canvas.data.update_tag()
        mark_gp_mask_dirty(canvas, schedule=True)
    except FBP_DATA_ERRORS:
        pass
    return {"created": created, "copied": copied, "failed": failed, "missing": timing_status(canvas)["missing"]}


def align_drawings_to_plane(canvas):
    """Align explicit GP drawings by order to source exposure starts.

    All frames are moved through a temporary range first so destinations never
    overwrite another artist-authored drawing. Extra GP drawings keep their
    original frame when possible and are moved just after the source range only
    when their original position conflicts with a source exposure.
    """
    status = timing_status(canvas)
    layer = status["layer"]
    targets = status["targets"]
    originals = status["explicit"]
    if layer is None or not targets or not originals:
        return {"moved": 0, "failed": 0, "extra": len(originals), "missing": len(targets)}

    high = max((*targets, *originals, int(getattr(bpy.context.scene, "frame_end", 250) or 250))) + 10000
    temporary = []
    failed = 0
    for index, source in enumerate(originals):
        destination = high + index
        if _move_frame(layer, source, destination):
            temporary.append((source, destination))
        else:
            failed += 1

    used = set()
    moved = 0
    extra_count = 0
    target_set = set(targets)
    exposures = plane_exposures(gp_canvas_owner(canvas))
    tail = targets[-1] + max(1, exposures[-1].duration) if targets and exposures else high
    for index, (original, temp) in enumerate(temporary):
        if index < len(targets):
            destination = targets[index]
        else:
            destination = original
            if destination in target_set or destination in used:
                while tail in target_set or tail in used:
                    tail += 1
                destination = tail
                tail += 1
            extra_count += 1
        if _move_frame(layer, temp, destination):
            used.add(destination)
            moved += int(destination != original)
        else:
            failed += 1
    try:
        canvas.data.update_tag()
        mark_gp_mask_dirty(canvas, schedule=True)
    except FBP_DATA_ERRORS:
        pass
    current = timing_status(canvas)
    return {"moved": moved, "failed": failed, "extra": extra_count, "missing": len(current["missing"])}


def apply_gp_timing_to_plane(canvas):
    rig = gp_canvas_owner(canvas)
    layer = _active_layer(canvas)
    exposures = plane_exposures(rig)
    numbers = gp_frame_numbers(layer)
    if rig is None or not exposures or not numbers:
        return {"updated": 0, "available": len(numbers), "source": len(exposures)}
    try:
        offset = int(getattr(canvas, "fbp_gp_timing_offset", 0) or 0)
    except FBP_DATA_ERRORS:
        offset = 0
    logical = tuple(number - offset for number in numbers)
    fbp_set_rna_property_silent(rig, "fbp_start_frame", logical[0])
    items = tuple(getattr(rig, "fbp_images", ()) or ())
    updated = 0
    limit = min(len(items), len(logical))
    for index in range(limit):
        if index + 1 < len(logical):
            duration = max(1, logical[index + 1] - logical[index])
        else:
            duration = max(1, int(getattr(items[index], "duration", getattr(rig, "fbp_global_duration", 1)) or 1))
        if fbp_set_rna_property_silent(items[index], "duration", duration):
            updated += 1
    if limit and all(int(getattr(items[index], "duration", 1) or 1) == int(getattr(items[0], "duration", 1) or 1) for index in range(limit)):
        fbp_set_rna_property_silent(rig, "fbp_global_duration", int(getattr(items[0], "duration", 1) or 1))
    try:
        from .core import do_update_animation
        do_update_animation(rig)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not rebuild image timing after Grease Pencil sync", exc)
    return {"updated": updated, "available": len(numbers), "source": len(exposures)}


def current_source_exposure(canvas, scene_frame=None):
    targets = target_exposure_frames(canvas)
    if not targets:
        return None
    frame = int(scene_frame if scene_frame is not None else getattr(bpy.context.scene, "frame_current", 1) or 1)
    eligible = tuple(target for target in targets if target <= frame)
    return eligible[-1] if eligible else targets[0]


def _set_reference_hidden(rig, hidden):
    plane = getattr(rig, "fbp_plane_target", None) if rig else None
    if plane is None:
        return
    try:
        plane.hide_set(bool(hidden))
    except FBP_DATA_ERRORS:
        pass


def _set_rig_opacity(rig, value):
    """Update one rig without invoking multi-edit selection callbacks."""
    if rig is None or not fbp_set_rna_property_silent(rig, "fbp_opacity", float(value)):
        return False
    try:
        from .materials import do_update_opacity
        do_update_opacity(rig)
        return True
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not update Ink workflow reference opacity", exc)
        return False


def restore_workflow_reference(canvas):
    """Restore the source layer's pre-workflow viewport state and opacity."""
    if not is_gp_canvas(canvas):
        return False
    rig = gp_canvas_owner(canvas)
    if rig is None:
        return False
    try:
        original_opacity = float(canvas.get(KEY_REFERENCE_OPACITY, 1.0) or 1.0)
        original_hidden = bool(canvas.get(KEY_REFERENCE_HIDDEN, False))
    except FBP_DATA_ERRORS:
        return False
    _set_reference_hidden(rig, original_hidden)
    return _set_rig_opacity(rig, original_opacity)


def apply_workflow_state(canvas):
    if not is_gp_canvas(canvas):
        return False
    rig = gp_canvas_owner(canvas)
    if rig is None:
        return False
    try:
        state = str(getattr(canvas, "fbp_gp_workflow_state", "INK") or "INK")
        reference_visible = bool(getattr(canvas, "fbp_gp_reference_visible", True))
        original_opacity = float(canvas.get(KEY_REFERENCE_OPACITY, 1.0) or 1.0)
        ink_opacity = float(getattr(canvas, "fbp_gp_reference_opacity", 0.35) or 0.0)
        plane = getattr(rig, "fbp_plane_target", None)
        if plane is not None and KEY_REFERENCE_HIDDEN not in canvas:
            canvas[KEY_REFERENCE_HIDDEN] = bool(plane.hide_get())
        canvas[KEY_WORKFLOW_SCHEMA] = FBP_GP_WORKFLOW_SCHEMA_VERSION
        canvas[KEY_LAST_STATE] = state
        canvas.hide_set(False)
        if state == "REFERENCE":
            _set_reference_hidden(rig, not reference_visible)
            _set_rig_opacity(rig, original_opacity)
        elif state == "INK":
            _set_reference_hidden(rig, not reference_visible)
            _set_rig_opacity(rig, ink_opacity)
        else:  # FINAL
            _set_reference_hidden(rig, True)
        return True
    except FBP_DATA_ERRORS:
        return False


def _workflow_state_update(self, _context):
    apply_workflow_state(self)


def _timing_offset_update(self, _context):
    try:
        if bool(getattr(self, "fbp_gp_auto_sync_timing", False)):
            self.fbp_gp_last_timing_report = "Timing offset changed; Auto Sync scheduled"
            _schedule_auto_timing_sync(self)
        else:
            self.fbp_gp_last_timing_report = "Timing offset changed; synchronize drawings when ready"
    except FBP_DATA_ERRORS:
        pass


def _auto_sync_update(self, context):
    try:
        # The canvas may be linked to several scenes; membership changes are
        # rare, so invalidate the small cache globally for correctness.
        _clear_auto_timing_canvas_cache()
        if bool(self.fbp_gp_auto_sync_timing):
            self.fbp_gp_timing_fingerprint = ""
            self.fbp_gp_last_timing_report = "Auto Sync enabled"
            _schedule_auto_timing_sync(self, first_interval=0.03)
        else:
            self.fbp_gp_last_timing_report = "Auto Sync disabled"
    except FBP_DATA_ERRORS:
        pass


class FBP_OT_GPSetWorkflowState(Operator):
    bl_idname = "fbp.gp_set_workflow_state"
    bl_label = "Set Ink Workflow State"
    bl_description = 'Switch the linked source and drawing visibility between Reference, Ink and Final states'
    bl_options = {"REGISTER", "UNDO"}

    state: EnumProperty(description='Choose the State option for this Grease Pencil workflow. Hover each entry for the specific mode when Blender exposes enum item help.', name="State", items=WORKFLOW_STATE_ITEMS, default="INK", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return _active_canvas(context) is not None

    def execute(self, context):
        canvas = _active_canvas(context)
        canvas.fbp_gp_workflow_state = self.state
        apply_workflow_state(canvas)
        return {"FINISHED"}


class FBP_OT_GPMatchPlaneTiming(Operator):
    bl_idname = "fbp.gp_match_plane_timing"
    bl_label = "Match Plane Timing"
    bl_description = "Align existing Grease Pencil drawings by order to the source image exposure starts"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        canvas = _active_canvas(context)
        return canvas is not None and bool(target_exposure_frames(canvas))

    def execute(self, context):
        canvas = _active_canvas(context)
        result = align_drawings_to_plane(canvas)
        canvas.fbp_gp_last_timing_report = (
            f"Aligned {result['moved']} drawing(s) · {result['missing']} missing · {result['extra']} extra"
        )
        if result["failed"]:
            self.report({"WARNING"}, f"Timing aligned with {result['failed']} frame move failure(s)")
        else:
            self.report({"INFO"}, canvas.fbp_gp_last_timing_report)
        return {"FINISHED"}


class FBP_OT_GPMatchDrawingTiming(Operator):
    bl_idname = "fbp.gp_match_drawing_timing"
    bl_label = "Match GP Timing"
    bl_description = "Apply explicit Grease Pencil drawing positions to the source image sequence durations"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        canvas = _active_canvas(context)
        status = timing_status(canvas, remember_layer=False) if canvas else {}
        return bool(status.get("explicit")) and bool(plane_exposures(gp_canvas_owner(canvas)))

    def execute(self, context):
        canvas = _active_canvas(context)
        result = apply_gp_timing_to_plane(canvas)
        canvas.fbp_gp_last_timing_report = (
            f"Updated {result['updated']} source exposure(s) from {result['available']} GP drawing(s)"
        )
        self.report({"INFO"}, canvas.fbp_gp_last_timing_report)
        return {"FINISHED"}


class FBP_OT_GPCreateMissingDrawings(Operator):
    bl_idname = "fbp.gp_create_missing_drawings"
    bl_label = "Create Missing GP Drawings"
    bl_description = "Create explicit Grease Pencil drawings for source exposures that do not yet have a keyframe"
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(description='Operation mode for this Grease Pencil workflow. Example: choose whether the command adds, removes, previews, repairs or applies settings.', name="Creation Mode", items=MISSING_DRAWING_ITEMS, default="BLANK", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        canvas = _active_canvas(context)
        return bool(canvas and timing_status(canvas, remember_layer=False)["missing"])

    def execute(self, context):
        canvas = _active_canvas(context)
        mode = self.mode or str(getattr(canvas, "fbp_gp_missing_drawing_mode", "BLANK") or "BLANK")
        result = create_missing_drawings(canvas, duplicate_previous=mode == "DUPLICATE_PREVIOUS")
        canvas.fbp_gp_last_timing_report = (
            f"Created {result['created']} blank · copied {result['copied']} · {len(result['missing'])} still missing"
        )
        if result["failed"]:
            self.report({"WARNING"}, canvas.fbp_gp_last_timing_report)
        else:
            self.report({"INFO"}, canvas.fbp_gp_last_timing_report)
        return {"FINISHED"}


class FBP_OT_GPCreateCurrentExposure(Operator):
    bl_idname = "fbp.gp_create_current_exposure"
    bl_label = "Create Current GP Exposure"
    bl_description = "Create a drawing at the source exposure active under the current timeline frame"
    bl_options = {"REGISTER", "UNDO"}

    duplicate_previous: BoolProperty(description='Toggle this option for the current Grease Pencil workflow. Disabled keeps the data available but prevents this behavior from being applied.', name="Duplicate Previous", default=True, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return _active_canvas(context) is not None

    def execute(self, context):
        canvas = _active_canvas(context)
        try:
            from .grease_pencil_limited_loop import limited_loop_guard_info
            guard = limited_loop_guard_info(canvas, context.scene.frame_current)
            if guard:
                self.report(
                    {"ERROR"},
                    f"Generated frames from {guard['name']} are protected. "
                    f"Draw in source frames {guard['start']}–{guard['end']}",
                )
                return {"CANCELLED"}
        except (ImportError, AttributeError, KeyError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        layer = _active_layer(canvas)
        target = current_source_exposure(canvas)
        if layer is None or target is None:
            self.report({"WARNING"}, "No source exposure or active Grease Pencil layer")
            return {"CANCELLED"}
        existing = _find_frame(layer, target)
        if existing is not None:
            context.scene.frame_set(target)
            self.report({"INFO"}, f"Drawing already exists at frame {target}")
            return {"FINISHED"}
        previous = max((number for number in gp_frame_numbers(layer) if number < target), default=None)
        if self.duplicate_previous and previous is not None:
            _frame, changed = _copy_frame(layer, previous, target)
            action = "Duplicated previous drawing"
        else:
            _frame, changed = _new_frame(layer, target)
            action = "Created blank drawing"
        if not changed:
            self.report({"ERROR"}, f"Could not create a drawing at frame {target}")
            return {"CANCELLED"}
        context.scene.frame_set(target)
        try:
            canvas.data.update_tag()
            mark_gp_mask_dirty(canvas, schedule=True)
        except FBP_DATA_ERRORS:
            pass
        self.report({"INFO"}, f"{action} at frame {target}")
        return {"FINISHED"}


class FBP_PT_GreasePencilInkWorkflow(Panel):
    bl_label = "Ink Over Image"
    bl_description = "Switch between reference, drawing and final visibility while inking over a linked layer"
    bl_idname = "FBP_PT_grease_pencil_ink_workflow"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Frame By Plane"
    bl_parent_id = "FBP_PT_grease_pencil_canvas"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 1

    @classmethod
    def poll(cls, context):
        return _active_canvas(context) is not None

    def draw(self, context):
        layout = configure_layout(self.layout)
        canvas = _active_canvas(context)
        rig = gp_canvas_owner(canvas)
        section_header(layout, "Workflow State", icon="GREASEPENCIL")

        states = layout.row(align=True)
        for identifier, label, _description, icon, _index in WORKFLOW_STATE_ITEMS:
            op = states.operator(
                "fbp.gp_set_workflow_state",
                text=label,
                icon=icon,
                depress=str(getattr(canvas, "fbp_gp_workflow_state", "INK")) == identifier,
            )
            op.state = identifier

        reference = layout.row(align=True)
        reference.prop(canvas, "fbp_gp_reference_visible", text="Reference", toggle=True, icon="IMAGE_BACKGROUND")
        reference.prop(canvas, "fbp_gp_reference_opacity", text="Opacity", slider=True)
        if rig is not None:
            reference.label(text=getattr(rig, "name", "Layer"), icon="IMAGE_DATA")

        section_gap(layout, 0.2)
        current = current_source_exposure(canvas, context.scene.frame_current)
        current_row = layout.row(align=True)
        current_row.label(text=f"Current source exposure: {current if current is not None else '—'}", icon="TIME")
        op = current_row.operator("fbp.gp_create_current_exposure", text="New Drawing", icon="ADD")
        op.duplicate_previous = str(getattr(canvas, "fbp_gp_missing_drawing_mode", "BLANK")) == "DUPLICATE_PREVIOUS"


class FBP_PT_GreasePencilTiming(Panel):
    bl_label = "Drawing Timing"
    bl_description = "Synchronize Grease Pencil drawings with the linked Frame By Plane source timing"
    bl_idname = "FBP_PT_grease_pencil_timing"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Frame By Plane"
    bl_parent_id = "FBP_PT_grease_pencil_canvas"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 2

    @classmethod
    def poll(cls, context):
        return _active_canvas(context) is not None

    def draw(self, context):
        layout = configure_layout(self.layout)
        canvas = _active_canvas(context)
        status = timing_status(canvas, remember_layer=False)
        section_header(layout, "Source Synchronization", icon="TIME")

        header = layout.row(align=False)
        header.prop(canvas, "fbp_gp_timing_offset", text="Offset")
        header.label(text=f"{len(status['explicit'])} GP / {len(status['targets'])} source", icon="KEYFRAME")

        auto = layout.row(align=True)
        auto.prop(canvas, "fbp_gp_auto_sync_timing", text="Auto Sync Source Timing", toggle=True, icon="FILE_REFRESH")
        if bool(getattr(canvas, "fbp_gp_auto_sync_timing", False)) and _timing_layer_has_applied_loop(canvas):
            auto.alert = True
            auto.label(text="Paused by Limited Loop", icon="LOCKED")

        sync = layout.row(align=False)
        sync.operator("fbp.gp_match_plane_timing", text="Plane → GP", icon="FORWARD")
        sync.operator("fbp.gp_match_drawing_timing", text="GP → Plane", icon="BACK")

        missing = layout.row(align=True)
        missing.prop(canvas, "fbp_gp_missing_drawing_mode", text="Missing")
        create = missing.operator("fbp.gp_create_missing_drawings", text="Create", icon="ADD")
        create.mode = str(getattr(canvas, "fbp_gp_missing_drawing_mode", "BLANK") or "BLANK")
        missing.enabled = bool(status["missing"])

        summary = layout.row(align=False)
        summary.alert = bool(status["missing"])
        summary.label(
            text=f"Matched {status['matched']} · Missing {len(status['missing'])} · Extra {len(status['extra'])}",
            icon="ERROR" if status["missing"] else "CHECKMARK",
        )
        if getattr(canvas, "fbp_gp_last_timing_report", ""):
            hint_row(layout, canvas.fbp_gp_last_timing_report, icon="CHECKMARK", disabled=False)


def audit_gp_workflow(scene, *, repair=False):
    stats = {
        "gp_workflows": 0,
        "gp_timing_targets": 0,
        "gp_explicit_drawings": 0,
        "gp_missing_drawings": 0,
        "gp_extra_drawings": 0,
        "gp_workflow_repairs": 0,
    }
    issues = []
    warnings = []
    if scene is None:
        return {"stats": stats, "issues": ("No Scene for Grease Pencil workflow audit",), "warnings": (), "repaired": 0}
    for canvas in iter_scene_gp_canvases(scene, fallback=True):
        if not is_gp_canvas(canvas):
            continue
        stats["gp_workflows"] += 1
        status = timing_status(canvas, remember_layer=repair)
        stats["gp_timing_targets"] += len(status["targets"])
        stats["gp_explicit_drawings"] += len(status["explicit"])
        stats["gp_missing_drawings"] += len(status["missing"])
        stats["gp_extra_drawings"] += len(status["extra"])
        if status["targets"] and status["layer"] is None:
            issues.append(f"{canvas.name}: no active Grease Pencil layer is available for timing")
        elif status["missing"]:
            preview = ", ".join(str(value) for value in status["missing"][:6])
            suffix = "…" if len(status["missing"]) > 6 else ""
            warnings.append(f"{canvas.name}: missing explicit GP drawings at {preview}{suffix}")
        if repair:
            try:
                canvas[KEY_WORKFLOW_SCHEMA] = FBP_GP_WORKFLOW_SCHEMA_VERSION
                apply_workflow_state(canvas)
                stats["gp_workflow_repairs"] += 1
            except FBP_DATA_ERRORS:
                pass
    return {
        "stats": stats,
        "issues": tuple(dict.fromkeys(issues)),
        "warnings": tuple(dict.fromkeys(warnings)),
        "repaired": stats["gp_workflow_repairs"],
    }


def _register_properties():
    bpy.types.Object.fbp_gp_workflow_state = EnumProperty(
        name="Ink Workflow",
        description="Switch quickly between source reference, drawing and final inspection states",
        items=WORKFLOW_STATE_ITEMS,
        default="INK",
        update=_workflow_state_update,
    )
    bpy.types.Object.fbp_gp_reference_visible = BoolProperty(
        name="Reference",
        description="Show the linked Frame By Plane source in Reference and Ink states",
        default=True,
        update=_workflow_state_update,
    )
    bpy.types.Object.fbp_gp_timing_offset = IntProperty(
        name="GP Timing Offset",
        description="Offset Grease Pencil exposure starts relative to the source image sequence",
        default=0,
        soft_min=-250,
        soft_max=250,
        update=_timing_offset_update,
    )
    bpy.types.Object.fbp_gp_missing_drawing_mode = EnumProperty(
        name="Missing Drawing",
        description="How missing Grease Pencil exposures should be created",
        items=MISSING_DRAWING_ITEMS,
        default="DUPLICATE_PREVIOUS",
    )
    bpy.types.Object.fbp_gp_timing_layer_name = StringProperty(
        name="Timing Layer",
        description="Grease Pencil layer used by Frame By Plane timing tools",
        default="",
    )
    bpy.types.Object.fbp_gp_last_timing_report = StringProperty(
        name="Timing Report",
        description="Last Grease Pencil timing synchronization summary",
        default="",
    )
    bpy.types.Object.fbp_gp_auto_sync_timing = BoolProperty(
        name="Auto Sync Source Timing",
        description="Automatically realign GP drawings when source exposure timing, offset or scene FPS changes",
        default=False,
        update=_auto_sync_update,
    )
    bpy.types.Object.fbp_gp_timing_fingerprint = StringProperty(description='Grease Pencil Timing Fingerprint value used by the current Grease Pencil workflow. Changes are applied only to compatible Frame By Plane data.',
        default="",
        options={"HIDDEN"},
    )


def _unregister_properties():
    return unregister_type_properties(bpy.types.Object, _RNA_PROPERTIES)


classes = (
    FBP_OT_GPSetWorkflowState,
    FBP_OT_GPMatchPlaneTiming,
    FBP_OT_GPMatchDrawingTiming,
    FBP_OT_GPCreateMissingDrawings,
    FBP_OT_GPCreateCurrentExposure,
)


def register():
    classes_registered = False
    _clear_auto_timing_canvas_cache()
    try:
        _register_properties()
        if not bool(getattr(bpy.app, "background", False)):
            register_classes(classes)
            classes_registered = True
        _remove_workflow_handler(bpy.app.handlers.depsgraph_update_post, "_depsgraph_auto_timing_sync")
        # Scene Sync dispatches Auto Timing from the shared depsgraph snapshot.
        # Removing the stale handler above keeps in-place upgrades idempotent.
    except Exception:
        _remove_workflow_handler(bpy.app.handlers.depsgraph_update_post, "_depsgraph_auto_timing_sync")
        if classes_registered:
            unregister_classes(classes)
        _unregister_properties()
        raise


def unregister():
    _clear_auto_timing_canvas_cache()
    _remove_workflow_handler(bpy.app.handlers.depsgraph_update_post, "_depsgraph_auto_timing_sync")
    unregister_classes(classes)
    _unregister_properties()


__all__ = (
    "SERVICE_ID",
    "SERVICE_API_VERSION",
    "CAPABILITIES",
    "service_status",
    "Exposure",
    "plane_exposures",
    "target_exposure_frames",
    "gp_frame_numbers",
    "timing_status",
    "timing_source_fingerprint",
    "create_missing_drawings",
    "align_drawings_to_plane",
    "apply_gp_timing_to_plane",
    "current_source_exposure",
    "apply_workflow_state",
    "restore_workflow_reference",
    "audit_gp_workflow",
)
