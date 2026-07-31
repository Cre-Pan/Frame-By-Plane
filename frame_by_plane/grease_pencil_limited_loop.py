"""Finite Grease Pencil loop blocks for Frame By Plane.

One Grease Pencil canvas can own multiple independent Limited Loop blocks.
Each block inserts native ``GENERATED`` Grease Pencil keyframes into real
Timeline space, optionally adds a hold after every cycle and preserves later
loop blocks when earlier timing is inserted or removed.

The implementation targets the current collection-based loop-block schema used
by Frame By Plane on Blender 5.2 LTS.
"""

from __future__ import annotations

from dataclasses import dataclass
import json

import bpy
from bpy.app.handlers import persistent
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Operator, Panel, PropertyGroup

from .runtime import (
    FBP_DATA_ERRORS, fbp_unique_token_hex, fbp_warn_once,
    fbp_render_mutation_blocked, fbp_undo_guard_active,
    fbp_obj_runtime_key, fbp_find_id_by_runtime_key,
    fbp_depsgraph_quiet_for,
)
from .grease_pencil_bridge import is_gp_canvas, mark_gp_mask_dirty
from .grease_pencil_workflow import _active_canvas, _find_frame, _move_frame, gp_frame_numbers
from .fbp_index import iter_scene_gp_canvases
from .registration import (
    append_handler_once,
    register_classes,
    remove_handlers_by_name,
    unregister_classes,
    unregister_type_properties,
)
from .service_registry import service_descriptor
from .ui_style import configure_layout, empty_state, hint_row, section_gap, section_header


SERVICE_ID = "grease_pencil_limited_loop"
SERVICE_API_VERSION = 3
CAPABILITIES = (
    "FINITE_LOOP",
    "GENERATED_KEYFRAMES",
    "TIMELINE_INSERT",
    "PROTECTED_RANGE",
    "REVERSIBLE",
    "CYCLE_HOLD",
    "SOURCE_MAPPING",
    "MULTIPLE_LOOP_BLOCKS",
    "EXPLICIT_LAYER_TARGET",
)
FBP_GP_LIMITED_LOOP_SCHEMA_VERSION = 3
FBP_GP_FRAME_MIN = -1048574
FBP_GP_FRAME_MAX = 1048574

PLAYBACK_ITEMS = (
    ("FORWARD", "Forward", "Repeat the source drawings in their original order", "PLAY", 0),
    ("PINGPONG", "Ping-Pong", "Alternate forward and reversed cycles", "UV_SYNC_SELECT", 1),
)

KEY_SCHEMA = "fbp_gp_limited_loop_schema"
KEY_LAYER_LOCKS = "fbp_gp_limited_loop_layer_locks"
KEY_GUARD_MESSAGE = "fbp_gp_limited_loop_guard_message"
_RNA_PROPERTIES = (
    "fbp_gp_loop_blocks",
    "fbp_gp_loop_active_index",
    "fbp_gp_loop_blocks_schema",
    "fbp_gp_loop_guard_active",
)


@dataclass(frozen=True)
class LimitedLoopTiming:
    start: int
    end: int
    cycles: int
    playback: str
    duration: int
    hold: int
    cycle_span: int
    inserted_duration: int
    generated_start: int
    generated_end: int
    continuation_start: int


@dataclass(frozen=True)
class LimitedLoopPlan(LimitedLoopTiming):
    source_frames: tuple[int, ...]
    generated_pairs: tuple[tuple[int, int], ...]


def service_status():
    return service_descriptor(SERVICE_ID, SERVICE_API_VERSION, CAPABILITIES)


def limited_loop_timing(start, end, cycles, playback="FORWARD", hold=0):
    """Return validated loop timing without scanning Grease Pencil frames."""
    start = int(start)
    end = int(end)
    cycles = max(1, int(cycles))
    playback = str(playback or "FORWARD").upper()
    hold = int(hold)
    if start < FBP_GP_FRAME_MIN or end > FBP_GP_FRAME_MAX:
        raise ValueError("Limited Loop range is outside Blender's supported timeline")
    if end < start:
        raise ValueError("Loop End must be greater than or equal to Loop Start")
    if cycles < 2:
        raise ValueError("Limited Loop needs at least two total cycles")
    if hold < 0:
        raise ValueError("Cycle Hold cannot be negative")
    if playback not in {"FORWARD", "PINGPONG"}:
        raise ValueError(f"Unsupported Limited Loop playback: {playback}")

    duration = end - start + 1
    cycle_span = duration + hold
    inserted_duration = duration * (cycles - 1) + hold * cycles
    generated_end = end + inserted_duration
    continuation_start = generated_end + 1
    if continuation_start > FBP_GP_FRAME_MAX:
        raise ValueError("Limited Loop exceeds Blender's maximum timeline frame")
    return LimitedLoopTiming(
        start=start,
        end=end,
        cycles=cycles,
        playback=playback,
        duration=duration,
        hold=hold,
        cycle_span=cycle_span,
        inserted_duration=inserted_duration,
        generated_start=end + 1,
        generated_end=generated_end,
        continuation_start=continuation_start,
    )


def limited_loop_plan(explicit_frames, start, end, cycles, playback="FORWARD", hold=0):
    """Return a deterministic finite-loop plan without touching Blender data."""
    timing = limited_loop_timing(start, end, cycles, playback, hold)
    source_frames = tuple(sorted({
        int(value) for value in explicit_frames
        if timing.start <= int(value) <= timing.end
    }))
    if not source_frames:
        raise ValueError("The selected range contains no Grease Pencil keyframes")
    if source_frames[0] != timing.start:
        raise ValueError("Loop Start must contain an explicit Grease Pencil keyframe")
    if timing.playback == "PINGPONG" and source_frames[-1] != timing.end:
        raise ValueError("Ping-Pong requires an explicit keyframe on Loop End")

    generated_pairs = []
    for cycle_index in range(1, timing.cycles):
        reverse = timing.playback == "PINGPONG" and bool(cycle_index % 2)
        block_start = timing.start + cycle_index * timing.cycle_span
        for source in source_frames:
            relative = (timing.end - source) if reverse else (source - timing.start)
            generated_pairs.append((source, block_start + relative))

    return LimitedLoopPlan(
        start=timing.start,
        end=timing.end,
        cycles=timing.cycles,
        playback=timing.playback,
        duration=timing.duration,
        hold=timing.hold,
        cycle_span=timing.cycle_span,
        inserted_duration=timing.inserted_duration,
        generated_start=timing.generated_start,
        generated_end=timing.generated_end,
        continuation_start=timing.continuation_start,
        source_frames=source_frames,
        generated_pairs=tuple(sorted(generated_pairs, key=lambda pair: pair[1])),
    )


def limited_loop_source_frame(plan, frame):
    """Map one automatic loop/hold frame back to its editable source frame."""
    frame = int(frame)
    if frame < plan.start or frame > plan.generated_end:
        raise ValueError("Frame is outside the Limited Loop timeline")
    offset = frame - plan.start
    cycle_index = min(plan.cycles - 1, offset // max(1, plan.cycle_span))
    local = offset % max(1, plan.cycle_span)
    reverse = plan.playback == "PINGPONG" and bool(cycle_index % 2)
    if local >= plan.duration:
        return plan.start if reverse else plan.end
    return plan.end - local if reverse else plan.start + local


def loop_intervals_overlap(start_a, end_a, start_b, end_b):
    """Return True when two inclusive timeline intervals overlap."""
    return int(start_a) <= int(end_b) and int(start_b) <= int(end_a)


def shifted_loop_values(start, end, generated_start, generated_end, frames, *, after, delta):
    """Pure metadata shift used by runtime code and regression tests."""
    after = int(after)
    delta = int(delta)
    start = int(start)
    end = int(end)
    generated_start = int(generated_start)
    generated_end = int(generated_end)
    values = tuple(sorted({int(value) for value in frames}))
    if not delta or start <= after:
        return start, end, generated_start, generated_end, values
    return (
        start + delta,
        end + delta,
        generated_start + delta,
        generated_end + delta,
        tuple(value + delta if value > after else value for value in values),
    )


def _json_frames(value):
    try:
        values = json.loads(str(value or "[]"))
        return tuple(sorted({int(item) for item in values}))
    except (TypeError, ValueError, json.JSONDecodeError):
        return ()


def _json_lock_states(value):
    try:
        payload = json.loads(str(value or "{}"))
        if not isinstance(payload, dict):
            return {}
        return {str(name): bool(locked) for name, locked in payload.items() if str(name)}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _store_generated_frames(owner, frames):
    owner.generated_frames = json.dumps(tuple(sorted({int(value) for value in frames})))


def _new_block_uid():
    return f"gploop:{fbp_unique_token_hex()}"


def _loop_blocks(canvas):
    if canvas is None:
        return ()
    try:
        return getattr(canvas, "fbp_gp_loop_blocks", ()) or ()
    except FBP_DATA_ERRORS:
        return ()


def _block_at(canvas, index):
    blocks = _loop_blocks(canvas)
    try:
        index = int(index)
        return blocks[index] if 0 <= index < len(blocks) else None
    except (IndexError, TypeError, ValueError):
        return None


def _active_block(canvas):
    """Return the effective active block without mutating RNA from draw/poll."""
    blocks = _loop_blocks(canvas)
    if not blocks:
        return None
    try:
        index = max(0, min(int(getattr(canvas, "fbp_gp_loop_active_index", 0) or 0), len(blocks) - 1))
        return blocks[index]
    except FBP_DATA_ERRORS:
        try:
            return blocks[0]
        except (IndexError, TypeError):
            return None


def _block_index(canvas, target):
    for index, block in enumerate(_loop_blocks(canvas)):
        if block is target:
            return index
        try:
            if str(getattr(block, "uid", "")) and str(block.uid) == str(getattr(target, "uid", "")):
                return index
        except FBP_DATA_ERRORS:
            pass
    return -1


def _unique_block_name(canvas, base="Loop"):
    names = {str(getattr(block, "name", "") or "") for block in _loop_blocks(canvas)}
    if base not in names:
        return base
    index = 2
    while f"{base} {index}" in names:
        index += 1
    return f"{base} {index}"


def _ensure_block_identity(block):
    try:
        if not str(getattr(block, "uid", "") or ""):
            block.uid = _new_block_uid()
        return str(block.uid)
    except FBP_DATA_ERRORS:
        return ""


def _add_loop_block(canvas, *, copy_from=None, current_frame=None):
    if canvas is None:
        return None
    block_name = _unique_block_name(canvas, "Loop")
    try:
        block = canvas.fbp_gp_loop_blocks.add()
    except FBP_DATA_ERRORS:
        return None
    block.uid = _new_block_uid()
    block.name = block_name
    target_layer = _default_loop_layer(canvas)
    if target_layer is not None:
        block.layer_name = str(getattr(target_layer, "name", "") or "")
    if copy_from is not None:
        block.start = int(copy_from.start)
        block.end = int(copy_from.end)
        block.cycles = int(copy_from.cycles)
        block.hold = int(copy_from.hold)
        block.playback = str(copy_from.playback)
        block.instance_drawings = bool(copy_from.instance_drawings)
        block.protect_generated = bool(copy_from.protect_generated)
        block.layer_name = str(getattr(copy_from, "layer_name", "") or block.layer_name)
    elif current_frame is not None:
        start = max(FBP_GP_FRAME_MIN, min(FBP_GP_FRAME_MAX, int(current_frame)))
        block.start = start
        block.end = min(FBP_GP_FRAME_MAX, start + 9)
    try:
        canvas.fbp_gp_loop_active_index = len(canvas.fbp_gp_loop_blocks) - 1
        canvas.fbp_gp_loop_blocks_schema = FBP_GP_LIMITED_LOOP_SCHEMA_VERSION
        canvas[KEY_SCHEMA] = FBP_GP_LIMITED_LOOP_SCHEMA_VERSION
    except FBP_DATA_ERRORS:
        pass
    return block


def _remove_loop_block_entry(canvas, index):
    block = _block_at(canvas, index)
    if block is None:
        raise ValueError("Limited Loop block no longer exists")
    if bool(getattr(block, "applied", False)):
        raise ValueError("Remove the generated loop before deleting this block")
    try:
        canvas.fbp_gp_loop_blocks.remove(int(index))
        count = len(canvas.fbp_gp_loop_blocks)
        canvas.fbp_gp_loop_active_index = max(0, min(int(index), count - 1)) if count else 0
    except FBP_DATA_ERRORS as exc:
        raise RuntimeError("Could not delete the Limited Loop block") from exc


def _default_loop_layer(canvas):
    if canvas is None:
        return None
    data = getattr(canvas, "data", None)
    if data is None:
        return None
    name = str(getattr(canvas, "fbp_gp_timing_layer_name", "") or "")
    try:
        if name:
            layer = data.layers.get(name)
            if layer is not None:
                return layer
        return data.layers.active or next(iter(data.layers), None)
    except FBP_DATA_ERRORS:
        return None


def _block_layer(canvas, block, *, applied=False):
    """Resolve the block's stable target layer without silently changing it."""
    if canvas is None or block is None:
        return None
    data = getattr(canvas, "data", None)
    if data is None:
        return None
    try:
        name = str(getattr(block, "layer_name", "") or "")
        if name:
            return data.layers.get(name)
        # Draft blocks may not have a target yet. Resolve once, store it,
        # and never follow later active-layer changes implicitly.
        fallback_name = str(getattr(canvas, "fbp_gp_timing_layer_name", "") or "")
        layer = data.layers.get(fallback_name) if fallback_name else None
        if layer is None:
            layer = data.layers.active or next(iter(data.layers), None)
        if layer is not None:
            block.layer_name = str(layer.name)
        return layer
    except FBP_DATA_ERRORS:
        return None


def _copy_generated_frame(layer, source_number, destination_number, *, instance_drawing=True):
    if _find_frame(layer, destination_number) is not None:
        return None
    try:
        copied = layer.frames.copy(
            from_frame_number=int(source_number),
            to_frame_number=int(destination_number),
            instance_drawing=bool(instance_drawing),
        )
    except TypeError:
        try:
            copied = layer.frames.copy(int(source_number), int(destination_number), bool(instance_drawing))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return None
    except (AttributeError, ReferenceError, RuntimeError, ValueError):
        return None
    frame = _find_frame(layer, destination_number) or copied
    try:
        frame.keyframe_type = "GENERATED"
        frame.select = False
    except FBP_DATA_ERRORS:
        pass
    return frame


def _shift_frames(layer, *, after, delta):
    """Shift every keyframe strictly after *after* by *delta* safely."""
    delta = int(delta)
    if not delta:
        return 0, 0
    numbers = [number for number in gp_frame_numbers(layer) if number > int(after)]
    numbers.sort(reverse=delta > 0)
    moved = failed = 0
    for source in numbers:
        if _move_frame(layer, source, source + delta):
            moved += 1
        else:
            failed += 1
    return moved, failed


def _mark_canvas_dirty(canvas):
    try:
        canvas.data.update_tag()
        mark_gp_mask_dirty(canvas, schedule=True)
    except FBP_DATA_ERRORS:
        pass


def _clear_block_applied_metadata(block):
    block.applied = False
    # Preserve the target layer so Rebuild and later edits cannot jump to a
    # different active GP layer after generated timing is removed.
    _store_generated_frames(block, ())
    block.applied_start = 0
    block.applied_end = 0
    block.applied_cycles = 0
    block.applied_hold = 0
    block.applied_playback = ""
    block.inserted_duration = 0
    block.generated_start = 0
    block.generated_end = 0
    block.guard_active = False


def _block_interval(block):
    if block is None or not bool(getattr(block, "applied", False)):
        return None
    start = int(getattr(block, "applied_start", 0) or 0)
    end = int(getattr(block, "generated_end", 0) or 0)
    return (start, end) if end >= start else None


def _applied_blocks(canvas, *, layer_name=""):
    result = []
    for block in _loop_blocks(canvas):
        if not bool(getattr(block, "applied", False)):
            continue
        if layer_name and str(getattr(block, "layer_name", "") or "") != str(layer_name):
            continue
        result.append(block)
    return tuple(result)


def _validate_block_conflicts(canvas, block, plan, layer_name):
    for other in _applied_blocks(canvas, layer_name=layer_name):
        if other is block:
            continue
        interval = _block_interval(other)
        if interval is None:
            continue
        if loop_intervals_overlap(plan.start, plan.end, interval[0], interval[1]):
            other_name = str(getattr(other, "name", "Loop") or "Loop")
            raise ValueError(
                f"Source range {plan.start}–{plan.end} overlaps applied block '{other_name}' "
                f"({interval[0]}–{interval[1]})"
            )


def _shift_block_metadata(block, *, after, delta):
    if block is None or not bool(getattr(block, "applied", False)):
        return False
    values = shifted_loop_values(
        block.applied_start,
        block.applied_end,
        block.generated_start,
        block.generated_end,
        _json_frames(block.generated_frames),
        after=after,
        delta=delta,
    )
    if values[0] == int(block.applied_start):
        return False
    block.applied_start, block.applied_end, block.generated_start, block.generated_end = values[:4]
    _store_generated_frames(block, values[4])
    # The editable source settings follow their drawings so a later Rebuild
    # remains attached to the same source section.
    block.start = int(block.start) + int(delta)
    block.end = int(block.end) + int(delta)
    return True


def _shift_later_block_metadata(canvas, *, layer_name, after, delta, exclude=None):
    """Move applied metadata and later draft ranges with their GP keyframes."""
    shifted = 0
    for other in _loop_blocks(canvas):
        if other is exclude:
            continue
        if str(getattr(other, "layer_name", "") or "") != str(layer_name):
            continue
        if bool(getattr(other, "applied", False)):
            if _shift_block_metadata(other, after=after, delta=delta):
                shifted += 1
            continue
        try:
            if int(other.start) > int(after):
                other.start = int(other.start) + int(delta)
                other.end = int(other.end) + int(delta)
                shifted += 1
        except FBP_DATA_ERRORS:
            pass
    return shifted


def _unexpected_generated_range_frames(block, layer):
    generated = set(_json_frames(getattr(block, "generated_frames", "")))
    start = int(getattr(block, "generated_start", 0) or 0)
    end = int(getattr(block, "generated_end", 0) or 0)
    if end < start:
        return ()
    return tuple(number for number in gp_frame_numbers(layer) if start <= number <= end and number not in generated)


def _ensure_runtime_block(canvas, block=None):
    if block is not None:
        _ensure_block_identity(block)
        return block
    block = _active_block(canvas)
    if block is None:
        block = _add_loop_block(canvas)
    return block


def build_limited_loop(canvas, scene=None, block=None):
    if not is_gp_canvas(canvas):
        raise ValueError("Select a Frame By Plane Grease Pencil canvas")
    block = _ensure_runtime_block(canvas, block)
    if block is None:
        raise RuntimeError("Could not create a Limited Loop block")
    if bool(getattr(block, "applied", False)):
        raise ValueError("This Limited Loop block is already applied; use Rebuild or Remove first")
    layer = _block_layer(canvas, block)
    if layer is None:
        raise ValueError("Choose a valid Target Layer before building this Loop Block")
    layer_name = str(getattr(layer, "name", "") or "")

    plan = limited_loop_plan(
        gp_frame_numbers(layer),
        block.start,
        block.end,
        block.cycles,
        block.playback,
        block.hold,
    )
    _validate_block_conflicts(canvas, block, plan, layer_name)
    tail_frames = tuple(number for number in gp_frame_numbers(layer) if number > plan.end)
    if tail_frames and max(tail_frames) + plan.inserted_duration > FBP_GP_FRAME_MAX:
        raise ValueError("Limited Loop would push later Grease Pencil timing beyond Blender's maximum timeline frame")

    # A different block may currently own the layer lock. Direct data edits are
    # safer with managed locks temporarily restored; the guard is reapplied at
    # the end of the operation or after rollback.
    _restore_all_managed_locks(canvas)
    moved, failed = _shift_frames(layer, after=plan.end, delta=plan.inserted_duration)
    if failed:
        _shift_frames(layer, after=plan.generated_end, delta=-plan.inserted_duration)
        update_limited_loop_guard(scene)
        raise RuntimeError(f"Could not shift {failed} continuation keyframe(s)")

    generated = []
    for source, destination in plan.generated_pairs:
        frame = _copy_generated_frame(
            layer,
            source,
            destination,
            instance_drawing=bool(block.instance_drawings),
        )
        if frame is None:
            for number in generated:
                try:
                    layer.frames.remove(int(number))
                except TypeError:
                    existing = _find_frame(layer, number)
                    if existing is not None:
                        layer.frames.remove(existing)
                except FBP_DATA_ERRORS:
                    pass
            _shift_frames(layer, after=plan.generated_end, delta=-plan.inserted_duration)
            update_limited_loop_guard(scene)
            raise RuntimeError(f"Could not generate Limited Loop keyframe at {destination}")
        generated.append(destination)

    shifted_blocks = _shift_later_block_metadata(
        canvas,
        layer_name=layer_name,
        after=plan.end,
        delta=plan.inserted_duration,
        exclude=block,
    )

    block.applied = True
    block.layer_name = layer_name
    block.applied_start = plan.start
    block.applied_end = plan.end
    block.applied_cycles = plan.cycles
    block.applied_hold = plan.hold
    block.applied_playback = plan.playback
    block.inserted_duration = plan.inserted_duration
    block.generated_start = plan.generated_start
    block.generated_end = plan.generated_end
    _store_generated_frames(block, generated)
    _ensure_block_identity(block)
    try:
        canvas[KEY_SCHEMA] = FBP_GP_LIMITED_LOOP_SCHEMA_VERSION
        canvas.fbp_gp_loop_blocks_schema = FBP_GP_LIMITED_LOOP_SCHEMA_VERSION
    except FBP_DATA_ERRORS:
        pass

    if scene is not None:
        try:
            scene.frame_end = max(int(scene.frame_end), plan.generated_end, max(gp_frame_numbers(layer), default=plan.generated_end))
        except FBP_DATA_ERRORS:
            pass
    hold_report = f" · {plan.hold} hold frame(s) per cycle" if plan.hold else ""
    shifted_report = f" · moved {shifted_blocks} later loop block(s)" if shifted_blocks else ""
    block.last_report = (
        f"Generated {len(generated)} automatic keyframe(s){hold_report} · "
        f"shifted {moved} continuation keyframe(s){shifted_report} · continue at {plan.continuation_start}"
    )
    _mark_canvas_dirty(canvas)
    update_limited_loop_guard(scene)
    return {
        "plan": plan,
        "generated": len(generated),
        "shifted": moved,
        "shifted_blocks": shifted_blocks,
        "block": block,
    }


def remove_limited_loop(canvas, scene=None, block=None):
    block = block or _active_block(canvas)
    if block is None or not bool(getattr(block, "applied", False)):
        return {"removed": 0, "shifted": 0, "shifted_blocks": 0}
    layer = _block_layer(canvas, block, applied=True)
    if layer is None:
        raise ValueError("The Grease Pencil layer used by this Limited Loop block no longer exists")

    unexpected = _unexpected_generated_range_frames(block, layer)
    if unexpected:
        preview = ", ".join(str(value) for value in unexpected[:8])
        raise ValueError(
            f"Protected loop range contains non-generated keyframes ({preview}). Move or delete them before removing the loop"
        )

    _restore_all_managed_locks(canvas)
    generated = _json_frames(block.generated_frames)
    removed = 0
    for number in sorted(generated, reverse=True):
        frame = _find_frame(layer, number)
        if frame is None:
            continue
        try:
            try:
                layer.frames.remove(int(number))
            except TypeError:
                layer.frames.remove(frame)
            removed += 1
        except FBP_DATA_ERRORS:
            pass

    generated_end = int(block.generated_end)
    inserted = int(block.inserted_duration)
    layer_name = str(block.layer_name)
    shifted, failed = _shift_frames(layer, after=generated_end, delta=-inserted)
    if failed:
        update_limited_loop_guard(scene)
        raise RuntimeError(f"Removed the loop but could not collapse {failed} continuation keyframe(s)")

    shifted_blocks = _shift_later_block_metadata(
        canvas,
        layer_name=layer_name,
        after=generated_end,
        delta=-inserted,
        exclude=block,
    )
    _clear_block_applied_metadata(block)
    block.last_report = (
        f"Removed {removed} automatic keyframe(s) · restored {shifted} continuation keyframe(s)"
        f"{f' · moved {shifted_blocks} later loop block(s)' if shifted_blocks else ''}"
    )
    _mark_canvas_dirty(canvas)
    update_limited_loop_guard(scene)
    return {"removed": removed, "shifted": shifted, "shifted_blocks": shifted_blocks}


def rebuild_limited_loop(canvas, scene=None, block=None):
    block = block or _active_block(canvas)
    if block is None:
        block = _ensure_runtime_block(canvas)
    if bool(getattr(block, "applied", False)):
        remove_limited_loop(canvas, scene, block)
    return build_limited_loop(canvas, scene, block)


def _block_guard_state(block, frame):
    if block is None or not bool(getattr(block, "applied", False)):
        return False
    if not bool(getattr(block, "protect_generated", True)):
        return False
    start = int(getattr(block, "generated_start", 0) or 0)
    end = int(getattr(block, "generated_end", 0) or 0)
    return start <= int(frame) <= end if end >= start else False


def matching_limited_loop_block(canvas, frame, *, prefer_active=True):
    if canvas is None:
        return None
    active = _active_block(canvas) if prefer_active else None
    if active is not None and _block_guard_state(active, frame):
        return active
    for block in _loop_blocks(canvas):
        if _block_guard_state(block, frame):
            return block
    return None

def limited_loop_guard_state(canvas, frame):
    return matching_limited_loop_block(canvas, frame) is not None


def limited_loop_guard_info(canvas, frame):
    block = matching_limited_loop_block(canvas, frame)
    if block is None:
        return None
    return {
        "name": str(getattr(block, "name", "Loop") or "Loop"),
        "start": int(getattr(block, "applied_start", 0) or 0),
        "end": int(getattr(block, "applied_end", 0) or 0),
        "layer_name": str(getattr(block, "layer_name", "") or ""),
    }

def _restore_all_managed_locks(canvas):
    if canvas is None:
        return
    try:
        states = _json_lock_states(canvas.get(KEY_LAYER_LOCKS, "{}"))
    except FBP_DATA_ERRORS:
        states = {}
    data = getattr(canvas, "data", None)
    layers = getattr(data, "layers", None) if data is not None else None
    for layer_name, previous_lock in states.items():
        try:
            layer = layers.get(layer_name) if layers is not None else None
            if layer is not None:
                layer.lock = bool(previous_lock)
        except FBP_DATA_ERRORS:
            pass
    try:
        canvas.pop(KEY_LAYER_LOCKS, None)
        canvas.pop(KEY_GUARD_MESSAGE, None)
        canvas.fbp_gp_loop_guard_active = False
    except FBP_DATA_ERRORS:
        pass
    for block in _loop_blocks(canvas):
        try:
            block.guard_active = False
        except FBP_DATA_ERRORS:
            pass


def update_limited_loop_guard(scene=None):
    scene = scene or getattr(bpy.context, "scene", None)
    if scene is None:
        return 0
    current = int(getattr(scene, "frame_current", 1) or 1)
    guarded = 0
    try:
        objects = iter_scene_gp_canvases(scene, fallback=True)
    except FBP_DATA_ERRORS:
        objects = ()
    for canvas in objects:
        if not _loop_blocks(canvas):
            continue
        if not is_gp_canvas(canvas):
            continue
        desired = {}
        active_blocks = []
        for block in _applied_blocks(canvas):
            try:
                block.guard_active = False
            except FBP_DATA_ERRORS:
                pass
            if not _block_guard_state(block, current):
                continue
            layer = _block_layer(canvas, block, applied=True)
            if layer is None:
                continue
            layer_name = str(getattr(layer, "name", "") or "")
            desired[layer_name] = layer
            active_blocks.append(block)
            try:
                block.guard_active = True
            except FBP_DATA_ERRORS:
                pass

        try:
            saved = _json_lock_states(canvas.get(KEY_LAYER_LOCKS, "{}"))
        except FBP_DATA_ERRORS:
            saved = {}
        changed = False
        for layer_name, layer in desired.items():
            if layer_name not in saved:
                try:
                    saved[layer_name] = bool(getattr(layer, "lock", False))
                    changed = True
                except FBP_DATA_ERRORS:
                    continue
            try:
                if not bool(getattr(layer, "lock", False)):
                    layer.lock = True
            except FBP_DATA_ERRORS:
                pass
        for layer_name in tuple(saved):
            if layer_name in desired:
                continue
            try:
                layer = canvas.data.layers.get(layer_name)
                if layer is not None:
                    layer.lock = bool(saved[layer_name])
            except FBP_DATA_ERRORS:
                pass
            saved.pop(layer_name, None)
            changed = True

        guarded += len(active_blocks)
        guard_active = bool(active_blocks)
        if guard_active:
            source_text = ", ".join(
                f"{str(getattr(block, 'name', 'Loop') or 'Loop')} {int(block.applied_start)}–{int(block.applied_end)}"
                for block in active_blocks[:3]
            )
            if len(active_blocks) > 3:
                source_text += f" +{len(active_blocks) - 3}"
            message = f"Generated Limited Loop frames are protected. Edit source: {source_text}."
        else:
            message = ""
        try:
            if changed:
                if saved:
                    canvas[KEY_LAYER_LOCKS] = json.dumps(saved, sort_keys=True)
                else:
                    canvas.pop(KEY_LAYER_LOCKS, None)
            if bool(getattr(canvas, "fbp_gp_loop_guard_active", False)) != guard_active:
                canvas.fbp_gp_loop_guard_active = guard_active
            if message:
                if str(canvas.get(KEY_GUARD_MESSAGE, "") or "") != message:
                    canvas[KEY_GUARD_MESSAGE] = message
            else:
                canvas.pop(KEY_GUARD_MESSAGE, None)
        except FBP_DATA_ERRORS:
            pass
    return guarded


def _refresh_all_limited_loops():
    """Refresh current loop-block guards after Blender exposes Main data."""
    try:
        scenes = tuple(getattr(bpy.data, "scenes"))
    except FBP_DATA_ERRORS:
        return 0.10
    for scene in scenes:
        try:
            for canvas in iter_scene_gp_canvases(scene, fallback=True):
                if _loop_blocks(canvas):
                    for block in _loop_blocks(canvas):
                        _ensure_block_identity(block)
            update_limited_loop_guard(scene)
        except Exception as exc:
            fbp_warn_once(
                "limited_loop_scene_guard_refresh",
                "Could not refresh one Grease Pencil Limited Loop scene",
                exc,
            )
    return None


def _schedule_limited_loop_guard(scene, *, first_interval=0.04):
    if scene is None or fbp_undo_guard_active() or fbp_render_mutation_blocked():
        return False
    scene_key = fbp_obj_runtime_key(scene)
    if scene_key is None:
        return False
    try:
        scene_name = str(getattr(scene, "name_full", getattr(scene, "name", "")) or "")
    except FBP_DATA_ERRORS:
        scene_name = ""

    def _publish():
        if fbp_undo_guard_active() or fbp_render_mutation_blocked():
            return 0.20
        if not fbp_depsgraph_quiet_for(0.15):
            return 0.06
        target_scene = fbp_find_id_by_runtime_key(
            getattr(bpy.data, "scenes", ()), scene_key, scene_name
        )
        if target_scene is None:
            return None
        try:
            update_limited_loop_guard(target_scene)
        except Exception as exc:
            fbp_warn_once(
                "limited_loop_frame_guard",
                "Could not update Grease Pencil Limited Loop guard",
                exc,
            )
        return None

    try:
        from .safe_tasks import schedule_once
        return bool(schedule_once(
            f"gp_limited_loop.guard:{scene_key}",
            _publish,
            first_interval=first_interval,
        ))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


@persistent
def _frame_change_guard(scene, _depsgraph=None):
    del _depsgraph
    _schedule_limited_loop_guard(scene)


@persistent
def _load_post_guard(_unused):
    try:
        from .safe_tasks import schedule_once
        schedule_once(
            "gp_limited_loop.refresh_guards",
            _refresh_all_limited_loops,
            first_interval=0.08,
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn_once(
            "limited_loop_load_restricted_data",
            "Grease Pencil Limited Loop refresh could not be deferred",
            exc,
        )


def _guard_property_update(_self, context):
    if fbp_undo_guard_active() or fbp_render_mutation_blocked():
        return
    _schedule_limited_loop_guard(getattr(context, "scene", None), first_interval=0.03)


class FBP_PG_GPLimitedLoopBlock(PropertyGroup):
    uid: StringProperty(description='Uid value used by the current Grease Pencil workflow. Changes are applied only to compatible Frame By Plane data.', default="", options={"HIDDEN"})
    name: StringProperty(
        name="Block Name",
        description="Readable name for this independent Limited Loop block",
        default="Loop",
    )
    start: IntProperty(
        name="Loop Start",
        description="First editable Grease Pencil frame included in this finite loop block",
        default=1,
        min=FBP_GP_FRAME_MIN,
        max=FBP_GP_FRAME_MAX,
    )
    end: IntProperty(
        name="Loop End",
        description="Last timeline frame included in one cycle of this loop block",
        default=10,
        min=FBP_GP_FRAME_MIN,
        max=FBP_GP_FRAME_MAX,
    )
    cycles: IntProperty(
        name="Cycles",
        description="Total number of cycles including the original editable cycle",
        default=4,
        min=2,
        max=100,
        soft_max=12,
    )
    hold: IntProperty(
        name="Cycle Hold",
        description="Extra timeline frames that hold the final drawing after every cycle, including the last",
        default=0,
        min=0,
        max=10000,
        soft_max=24,
    )
    playback: EnumProperty(
        name="Playback",
        description="Order used by generated cycles in this block",
        items=PLAYBACK_ITEMS,
        default="FORWARD",
    )
    instance_drawings: BoolProperty(
        name="Linked Drawings",
        description="Instance generated frames from source drawings so source edits update every cycle",
        default=True,
    )
    protect_generated: BoolProperty(
        name="Protect Generated Frames",
        description="Lock the target GP layer while the playhead is inside this generated block",
        default=True,
        update=_guard_property_update,
    )
    applied: BoolProperty(description='Toggle this option for the current Grease Pencil workflow. Disabled keeps the data available but prevents this behavior from being applied.', default=False, options={"HIDDEN"})
    layer_name: StringProperty(
        name="Target Layer",
        description="Grease Pencil layer owned by this Loop Block; choose it before Build",
        default="",
    )
    generated_frames: StringProperty(description='Timeline frame or frame-count value used by the selected animation, sequence or loop operation.', default="[]", options={"HIDDEN"})
    applied_start: IntProperty(description='Start value for this operation. Example: beginning of a loop, range, exposure or generated sequence.', default=0, options={"HIDDEN"})
    applied_end: IntProperty(description='End value for this operation. Example: final frame, loop boundary, exposure end or generated range limit.', default=0, options={"HIDDEN"})
    applied_cycles: IntProperty(description='Applied Cycles value used by the current Grease Pencil workflow. Changes are applied only to compatible Frame By Plane data.', default=0, options={"HIDDEN"})
    applied_hold: IntProperty(description='Number of frames to hold this state before the next drawing, image or procedural step is evaluated.', default=0, options={"HIDDEN"})
    applied_playback: StringProperty(description='Applied Playback value used by the current Grease Pencil workflow. Changes are applied only to compatible Frame By Plane data.', default="", options={"HIDDEN"})
    inserted_duration: IntProperty(description='Number of frames to hold this state before the next drawing, image or procedural step is evaluated.', default=0, options={"HIDDEN"})
    generated_start: IntProperty(description='Start value for this operation. Example: beginning of a loop, range, exposure or generated sequence.', default=0, options={"HIDDEN"})
    generated_end: IntProperty(description='End value for this operation. Example: final frame, loop boundary, exposure end or generated range limit.', default=0, options={"HIDDEN"})
    guard_active: BoolProperty(description='Toggle this option for the current Grease Pencil workflow. Disabled keeps the data available but prevents this behavior from being applied.', default=False, options={"SKIP_SAVE", "HIDDEN"})
    last_report: StringProperty(description='Last Report value used by the current Grease Pencil workflow. Changes are applied only to compatible Frame By Plane data.', default="")


class FBP_OT_GPAddLoopBlock(Operator):
    bl_idname = "fbp.gp_add_loop_block"
    bl_label = "Add Limited Loop Block"
    bl_description = "Add an independent Limited Loop block to this Grease Pencil canvas"
    bl_options = {"REGISTER", "UNDO"}

    duplicate_active: BoolProperty(description='Toggle this option for the current Grease Pencil workflow. Disabled keeps the data available but prevents this behavior from being applied.', default=False, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return _active_canvas(context) is not None

    def execute(self, context):
        canvas = _active_canvas(context)
        source = _active_block(canvas) if self.duplicate_active else None
        block = _add_loop_block(canvas, copy_from=source, current_frame=context.scene.frame_current)
        if block is None:
            self.report({"ERROR"}, "Could not add a Limited Loop block")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Added {block.name}")
        return {"FINISHED"}


class FBP_OT_GPSelectLoopBlock(Operator):
    bl_idname = "fbp.gp_select_loop_block"
    bl_label = "Select Limited Loop Block"
    bl_description = "Make this Limited Loop block active for editing"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(description='Zero-based item index used internally to target the selected row, frame, effect, preset or setup entry.', default=0, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return _active_canvas(context) is not None

    def execute(self, context):
        canvas = _active_canvas(context)
        block = _block_at(canvas, self.index)
        if block is None:
            return {"CANCELLED"}
        canvas.fbp_gp_loop_active_index = int(self.index)
        return {"FINISHED"}


class FBP_OT_GPDeleteLoopBlock(Operator):
    bl_idname = "fbp.gp_delete_loop_block"
    bl_label = "Delete Limited Loop Block"
    bl_description = "Delete this block after its generated timing has been removed"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(description='Zero-based item index used internally to target the selected row, frame, effect, preset or setup entry.', default=-1, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return _active_canvas(context) is not None

    def execute(self, context):
        canvas = _active_canvas(context)
        index = int(self.index)
        if index < 0:
            index = int(getattr(canvas, "fbp_gp_loop_active_index", 0) or 0)
        try:
            _remove_loop_block_entry(canvas, index)
        except (ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, "Limited Loop block deleted")
        return {"FINISHED"}


class FBP_OT_GPUseActiveLoopLayer(Operator):
    bl_idname = "fbp.gp_use_active_loop_layer"
    bl_label = "Use Active Grease Pencil Layer"
    bl_description = "Assign the currently active Grease Pencil layer to this Loop Block"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        canvas = _active_canvas(context)
        block = _active_block(canvas) if canvas else None
        return bool(canvas and block and not bool(getattr(block, "applied", False)))

    def execute(self, context):
        canvas = _active_canvas(context)
        block = _active_block(canvas)
        try:
            layer = canvas.data.layers.active
        except FBP_DATA_ERRORS:
            layer = None
        if layer is None:
            self.report({"ERROR"}, "No active Grease Pencil layer is available")
            return {"CANCELLED"}
        block.layer_name = str(layer.name)
        canvas.fbp_gp_timing_layer_name = str(layer.name)
        self.report({"INFO"}, f"{block.name}: target layer set to {layer.name}")
        return {"FINISHED"}


class FBP_OT_GPBuildLimitedLoop(Operator):
    bl_idname = "fbp.gp_build_limited_loop"
    bl_label = "Build Limited Loop"
    bl_description = "Insert generated Grease Pencil cycles and slide later keyframes and loop blocks forward"
    bl_options = {"REGISTER", "UNDO"}

    rebuild: BoolProperty(description='Toggle this option for the current Grease Pencil workflow. Disabled keeps the data available but prevents this behavior from being applied.', name="Rebuild", default=False, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return _active_canvas(context) is not None

    def execute(self, context):
        canvas = _active_canvas(context)
        block = _ensure_runtime_block(canvas)
        try:
            result = rebuild_limited_loop(canvas, context.scene, block) if self.rebuild else build_limited_loop(canvas, context.scene, block)
        except (ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        plan = result["plan"]
        hold_text = f" + {plan.hold}f hold" if plan.hold else ""
        self.report(
            {"INFO"},
            f"{block.name}: {plan.start}–{plan.end} × {plan.cycles}{hold_text}; continuation starts at {plan.continuation_start}",
        )
        return {"FINISHED"}


class FBP_OT_GPRemoveLimitedLoop(Operator):
    bl_idname = "fbp.gp_remove_limited_loop"
    bl_label = "Remove Limited Loop"
    bl_description = "Delete the active block's generated keyframes and restore later timing"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        canvas = _active_canvas(context)
        block = _active_block(canvas) if canvas else None
        return bool(block is not None and getattr(block, "applied", False))

    def execute(self, context):
        canvas = _active_canvas(context)
        block = _ensure_runtime_block(canvas)
        try:
            result = remove_limited_loop(canvas, context.scene, block)
        except (ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Removed {result['removed']} generated keyframe(s)")
        return {"FINISHED"}


class FBP_OT_GPJumpToLoopSource(Operator):
    bl_idname = "fbp.gp_jump_to_loop_source"
    bl_label = "Go to Editable Source"
    bl_description = "Jump from a protected generated block to its corresponding editable source frame"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        canvas = _active_canvas(context)
        return bool(canvas and matching_limited_loop_block(canvas, context.scene.frame_current))

    def execute(self, context):
        canvas = _active_canvas(context)
        block = matching_limited_loop_block(canvas, context.scene.frame_current)
        if block is None:
            self.report({"WARNING"}, "Current frame is not inside a protected Limited Loop block")
            return {"CANCELLED"}
        start = int(block.applied_start)
        end = int(block.applied_end)
        playback = str(block.applied_playback or "FORWARD")
        hold = max(0, int(block.applied_hold))
        cycles = max(2, int(block.applied_cycles))
        name = str(block.name or "Loop")
        index = _block_index(canvas, block)
        if index >= 0:
            canvas.fbp_gp_loop_active_index = index
        plan = limited_loop_timing(start, end, cycles, playback, hold)
        current = int(context.scene.frame_current)
        try:
            source = limited_loop_source_frame(plan, current)
        except ValueError as exc:
            self.report({"WARNING"}, str(exc))
            return {"CANCELLED"}
        context.scene.frame_set(source)
        self.report({"INFO"}, f"{name}: editable source frame {source}")
        return {"FINISHED"}


def _preview_block(canvas, block):
    if block is None:
        raise ValueError("Add a Limited Loop block")
    layer = _block_layer(canvas, block, applied=bool(block.applied))
    if layer is None:
        raise ValueError("No Grease Pencil layer is available")
    timing = limited_loop_timing(block.start, block.end, block.cycles, block.playback, block.hold)
    if block.applied:
        return timing, layer
    if _find_frame(layer, timing.start) is None:
        raise ValueError("Loop Start must contain an explicit Grease Pencil keyframe")
    if timing.playback == "PINGPONG" and _find_frame(layer, timing.end) is None:
        raise ValueError("Ping-Pong requires an explicit keyframe on Loop End")
    _validate_block_conflicts(canvas, block, timing, str(getattr(layer, "name", "") or ""))
    return timing, layer


class FBP_PT_GreasePencilLimitedLoop(Panel):
    bl_label = "Limited Loop Blocks"
    bl_description = "Build finite protected Grease Pencil loop sections in normal Timeline space"
    bl_idname = "FBP_PT_grease_pencil_limited_loop"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Frame By Plane"
    bl_parent_id = "FBP_PT_grease_pencil_canvas"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 3

    @classmethod
    def poll(cls, context):
        return _active_canvas(context) is not None

    def draw(self, context):
        layout = configure_layout(self.layout)
        canvas = _active_canvas(context)
        blocks = _loop_blocks(canvas)
        active_index = int(getattr(canvas, "fbp_gp_loop_active_index", 0) or 0)
        block = _active_block(canvas)

        header = section_header(layout, "Loop Blocks", icon="PREVIEW_RANGE", count=len(blocks), align=True)
        add = header.operator("fbp.gp_add_loop_block", text="", icon="ADD")
        add.duplicate_active = False
        duplicate = header.operator("fbp.gp_add_loop_block", text="", icon="DUPLICATE")
        duplicate.duplicate_active = True

        if not blocks:
            box = empty_state(
                layout,
                "No Limited Loop Blocks",
                "Add one block for each independent loop section.",
                icon="PREVIEW_RANGE",
            )
            add = box.operator("fbp.gp_add_loop_block", text="Add First Loop Block", icon="ADD")
            add.duplicate_active = False
            return

        list_box = layout.box()
        configure_layout(list_box)
        for index, item in enumerate(blocks):
            row = list_box.row(align=True)
            select = row.operator(
                "fbp.gp_select_loop_block",
                text=str(getattr(item, "name", "Loop") or "Loop"),
                icon="RADIOBUT_ON" if index == active_index else "RADIOBUT_OFF",
                depress=index == active_index,
            )
            select.index = index
            if bool(getattr(item, "applied", False)):
                row.label(text=f"{int(item.applied_start)}–{int(item.generated_end)}", icon="KEYFRAME")
            else:
                row.label(text="Draft", icon="DOT")
            delete_row = row.row(align=True)
            delete_row.enabled = not bool(getattr(item, "applied", False))
            delete = delete_row.operator("fbp.gp_delete_loop_block", text="", icon="TRASH")
            delete.index = index

        block = _active_block(canvas)
        if block is None:
            return

        section_gap(layout)
        details = layout.box()
        configure_layout(details)
        title = details.row(align=True)
        title.prop(block, "name", text="")
        if block.applied:
            title.label(text="Applied", icon="CHECKMARK")
        else:
            title.label(text="Draft", icon="GREASEPENCIL")

        settings_enabled = not bool(block.applied)
        target = details.row(align=True)
        target.enabled = settings_enabled
        try:
            target.prop_search(block, "layer_name", canvas.data, "layers", text="Layer", icon="GREASEPENCIL")
        except (AttributeError, TypeError):
            target.prop(block, "layer_name", text="Layer")
        target.operator("fbp.gp_use_active_loop_layer", text="", icon="EYEDROPPER")

        row = details.row(align=True)
        row.enabled = settings_enabled
        row.prop(block, "start", text="Start")
        row.prop(block, "end", text="End")
        row.prop(block, "cycles", text="Cycles")

        row = details.row(align=True)
        row.enabled = settings_enabled
        row.prop(block, "playback", text="")
        row.prop(block, "hold", text="Hold")
        row.prop(block, "instance_drawings", text="Linked", toggle=True, icon="LINKED")
        row.prop(block, "protect_generated", text="Protect", toggle=True, icon="LOCKED")

        try:
            plan, layer = _preview_block(canvas, block)
            preview = details.row(align=False)
            if block.applied:
                preview.label(
                    text=(
                        f"{block.layer_name}: source {block.applied_start}–{block.applied_end} · "
                        f"protected to {block.generated_end}"
                    ),
                    icon="KEYFRAME",
                )
            else:
                preview.label(
                    text=(
                        f"{getattr(layer, 'name', 'Layer')}: {plan.start}–{plan.end} × {plan.cycles}"
                        f"{f' + {plan.hold}f hold' if plan.hold else ''} → protected to {plan.generated_end} · "
                        f"continue at {plan.continuation_start}"
                    ),
                    icon="TIME",
                )
        except (ValueError, TypeError) as exc:
            preview = details.row(align=False)
            preview.alert = True
            preview.label(text=str(exc), icon="ERROR")

        actions = details.row(align=False)
        if not block.applied:
            actions.operator("fbp.gp_build_limited_loop", text="Build Block", icon="FILE_REFRESH")
        else:
            rebuild = actions.operator("fbp.gp_build_limited_loop", text="Rebuild", icon="FILE_REFRESH")
            rebuild.rebuild = True
            actions.operator("fbp.gp_remove_limited_loop", text="Remove Timing", icon="TRASH")

        current_match = matching_limited_loop_block(canvas, context.scene.frame_current)
        if current_match is not None:
            protected = layout.row(align=False)
            protected.alert = True
            protected.label(text=str(canvas.get(KEY_GUARD_MESSAGE, "Generated loop frames are protected")), icon="LOCKED")
            protected.operator("fbp.gp_jump_to_loop_source", text="Edit Source", icon="BACK")

        report = str(getattr(block, "last_report", "") or "")
        if report:
            hint_row(layout, report, icon="CHECKMARK", disabled=False)


def audit_limited_loops(scene, *, repair=False):
    stats = {
        "gp_limited_loops": 0,
        "gp_loop_canvases": 0,
        "gp_generated_loop_frames": 0,
        "gp_protected_loop_frames": 0,
        "gp_loop_hold_frames": 0,
        "gp_loop_repairs": 0,
    }
    issues = []
    warnings = []
    if scene is None:
        return {"stats": stats, "issues": ("No Scene for Limited Loop audit",), "warnings": (), "repaired": 0}
    seen_block_uids = {}
    for canvas in tuple(scene.objects):
        if not is_gp_canvas(canvas):
            continue
        blocks = _applied_blocks(canvas)
        if not blocks:
            continue
        stats["gp_loop_canvases"] += 1
        intervals_by_layer = {}
        for block in blocks:
            stats["gp_limited_loops"] += 1
            uid = _ensure_block_identity(block)
            previous_owner = seen_block_uids.get(uid)
            if previous_owner is not None and previous_owner != (canvas.name, block.name):
                warnings.append(
                    f"{canvas.name}/{block.name}: duplicates the Limited Loop ID of "
                    f"{previous_owner[0]}/{previous_owner[1]}"
                )
                if repair:
                    block.uid = _new_block_uid()
                    uid = str(block.uid)
                    stats["gp_loop_repairs"] += 1
            seen_block_uids[uid] = (str(canvas.name), str(block.name))
            layer = _block_layer(canvas, block, applied=True)
            generated = _json_frames(block.generated_frames)
            stats["gp_generated_loop_frames"] += len(generated)
            stats["gp_loop_hold_frames"] += max(0, int(block.applied_hold)) * max(0, int(block.applied_cycles))
            stats["gp_protected_loop_frames"] += max(0, int(block.generated_end) - int(block.generated_start) + 1)
            if layer is None:
                issues.append(f"{canvas.name}/{block.name}: Limited Loop layer is missing")
                continue
            interval = _block_interval(block)
            layer_intervals = intervals_by_layer.setdefault(str(block.layer_name), [])
            if interval is not None:
                for other_name, other_interval in layer_intervals:
                    if loop_intervals_overlap(interval[0], interval[1], other_interval[0], other_interval[1]):
                        issues.append(
                            f"{canvas.name}: loop blocks '{other_name}' and '{block.name}' overlap on {block.layer_name}"
                        )
                layer_intervals.append((str(block.name), interval))
            actual = set(gp_frame_numbers(layer))
            missing = tuple(number for number in generated if number not in actual)
            if missing:
                issues.append(f"{canvas.name}/{block.name}: {len(missing)} generated keyframe(s) are missing")
            unexpected = _unexpected_generated_range_frames(block, layer)
            if unexpected:
                warnings.append(f"{canvas.name}/{block.name}: protected range contains {len(unexpected)} non-generated keyframe(s)")
            for number in generated:
                frame = _find_frame(layer, number)
                if frame is None:
                    continue
                try:
                    if str(getattr(frame, "keyframe_type", "")) != "GENERATED":
                        warnings.append(f"{canvas.name}/{block.name}: frame {number} is not marked Generated")
                        if repair:
                            frame.keyframe_type = "GENERATED"
                            stats["gp_loop_repairs"] += 1
                except FBP_DATA_ERRORS:
                    pass
        if repair:
            try:
                canvas[KEY_SCHEMA] = FBP_GP_LIMITED_LOOP_SCHEMA_VERSION
                canvas.fbp_gp_loop_blocks_schema = FBP_GP_LIMITED_LOOP_SCHEMA_VERSION
            except FBP_DATA_ERRORS:
                pass
    if repair:
        update_limited_loop_guard(scene)
    return {
        "stats": stats,
        "issues": tuple(dict.fromkeys(issues)),
        "warnings": tuple(dict.fromkeys(warnings)),
        "repaired": stats["gp_loop_repairs"],
    }


def _register_properties():
    bpy.types.Object.fbp_gp_loop_blocks = CollectionProperty(
        description="Limited Loop blocks managed by Frame By Plane",
        type=FBP_PG_GPLimitedLoopBlock,
    )
    bpy.types.Object.fbp_gp_loop_active_index = IntProperty(
        description="Active Limited Loop block index",
        default=0,
        min=0,
        options={"HIDDEN"},
    )
    bpy.types.Object.fbp_gp_loop_blocks_schema = IntProperty(
        description="Limited Loop block schema",
        default=FBP_GP_LIMITED_LOOP_SCHEMA_VERSION,
        options={"HIDDEN"},
    )
    bpy.types.Object.fbp_gp_loop_guard_active = BoolProperty(
        description="Whether the current frame is protected by a Limited Loop block",
        default=False,
        options={"SKIP_SAVE", "HIDDEN"},
    )

def _unregister_properties():
    return unregister_type_properties(bpy.types.Object, _RNA_PROPERTIES)


def _remove_limited_loop_handler(handler_list, callback_name):
    """Remove current and stale reload copies of one Limited Loop handler."""
    return remove_handlers_by_name(
        handler_list,
        callback_name,
        module_suffix="grease_pencil_limited_loop",
    )


_operator_classes = (
    FBP_OT_GPAddLoopBlock,
    FBP_OT_GPSelectLoopBlock,
    FBP_OT_GPDeleteLoopBlock,
    FBP_OT_GPUseActiveLoopLayer,
    FBP_OT_GPBuildLimitedLoop,
    FBP_OT_GPRemoveLimitedLoop,
    FBP_OT_GPJumpToLoopSource,
)


def register():
    operator_classes_registered = False
    register_classes((FBP_PG_GPLimitedLoopBlock,))
    try:
        _register_properties()
        is_background = bool(getattr(bpy.app, "background", False))
        if not is_background:
            register_classes(_operator_classes)
            operator_classes_registered = True
        _remove_limited_loop_handler(bpy.app.handlers.frame_change_post, "_frame_change_guard")
        _remove_limited_loop_handler(bpy.app.handlers.load_post, "_load_post_guard")
        # Limited Loop frame protection only locks authoring layers. It has no
        # render contribution, so do not run this handler for background jobs.
        if not is_background:
            if not append_handler_once(
                bpy.app.handlers.frame_change_post,
                _frame_change_guard,
                module_suffix="grease_pencil_limited_loop",
            ):
                raise RuntimeError("Could not register the Limited Loop frame guard")
            if not append_handler_once(
                bpy.app.handlers.load_post,
                _load_post_guard,
                module_suffix="grease_pencil_limited_loop",
            ):
                raise RuntimeError("Could not register the Limited Loop load guard")
            from .safe_tasks import schedule_once
            schedule_once(
                "gp_limited_loop.refresh_guards",
                _refresh_all_limited_loops,
                first_interval=0.05,
            )
    except Exception:
        _remove_limited_loop_handler(bpy.app.handlers.frame_change_post, "_frame_change_guard")
        _remove_limited_loop_handler(bpy.app.handlers.load_post, "_load_post_guard")
        if operator_classes_registered:
            unregister_classes(_operator_classes)
        _unregister_properties()
        unregister_classes((FBP_PG_GPLimitedLoopBlock,))
        raise


def unregister():
    try:
        from .safe_tasks import cancel_scheduled_prefixes
        cancel_scheduled_prefixes("gp_limited_loop.refresh_guards")
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        scenes = tuple(getattr(bpy.data, "scenes"))
    except FBP_DATA_ERRORS:
        scenes = ()
    for scene in scenes:
        for canvas in iter_scene_gp_canvases(scene, fallback=True):
            if _loop_blocks(canvas):
                _restore_all_managed_locks(canvas)
    _remove_limited_loop_handler(bpy.app.handlers.frame_change_post, "_frame_change_guard")
    _remove_limited_loop_handler(bpy.app.handlers.load_post, "_load_post_guard")
    unregister_classes(_operator_classes)
    _unregister_properties()
    unregister_classes((FBP_PG_GPLimitedLoopBlock,))


__all__ = (
    "SERVICE_ID",
    "SERVICE_API_VERSION",
    "CAPABILITIES",
    "LimitedLoopTiming",
    "LimitedLoopPlan",
    "service_status",
    "limited_loop_timing",
    "limited_loop_plan",
    "limited_loop_source_frame",
    "loop_intervals_overlap",
    "shifted_loop_values",
    "matching_limited_loop_block",
    "limited_loop_guard_info",
    "build_limited_loop",
    "remove_limited_loop",
    "rebuild_limited_loop",
    "limited_loop_guard_state",
    "update_limited_loop_guard",
    "audit_limited_loops",
)
