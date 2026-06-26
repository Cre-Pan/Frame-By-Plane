"""Low-resolution rendered-image parity checks for Frame By Plane.

The audit is deliberately explicit and user-triggered.  It renders the active
Scene with Eevee and Cycles at a compact diagnostic resolution, compares the
resulting premultiplied RGBA buffers and verifies that real renders did not
change the viewport/effect state.  No timer, frame handler or depsgraph callback
is introduced by this module.
"""

from __future__ import annotations

from array import array
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import math
import os
import shutil
import tempfile
import time

import bpy
from bpy.props import BoolProperty, IntProperty
from bpy.types import Operator

from .diagnostics import write_diagnostic_report
from .geometry_nodes import (
    fbp_effect_ids_for_rig,
    fbp_effect_render_visible_state,
    fbp_effect_visible_state,
    fbp_find_effect_modifier,
)
from .layers import is_fbp_layer_object, iter_scene_fbp_rigs
from .runtime import (
    FBP_DATA_ERRORS,
    FBP_RENDER_IDLE,
    fbp_render_state,
    fbp_warn,
)

_STATUS_KEY = "fbp_render_parity_status"
_SIGNATURE_KEY = "fbp_render_parity_signature"
_TIME_KEY = "fbp_render_parity_time"
_FRAME_KEY = "fbp_render_parity_frame"
_ENGINES_KEY = "fbp_render_parity_engines"

_IMAGE_PREFIX = "FBP Render Parity"


def _safe_name(value):
    return str(getattr(value, "name_full", getattr(value, "name", "")) or "")


def _rounded_sequence(values, digits=6):
    result = []
    try:
        iterator = tuple(values)
    except (TypeError, ReferenceError):
        return result
    for value in iterator:
        try:
            result.append(round(float(value), digits))
        except (TypeError, ValueError, ReferenceError):
            result.append(0.0)
    return result


def _scene_signature_payload(scene):
    """Return a stable, intentionally compact signature of render-relevant state."""
    rigs = []
    try:
        scene_rigs = tuple(iter_scene_fbp_rigs(scene))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        scene_rigs = ()
    for rig in sorted(scene_rigs, key=lambda item: _safe_name(item).casefold()):
        if not is_fbp_layer_object(rig):
            continue
        plane = None
        try:
            plane = getattr(rig, "fbp_plane_target", None)
        except FBP_DATA_ERRORS:
            plane = None
        effects = []
        try:
            effect_ids = tuple(fbp_effect_ids_for_rig(rig))
        except FBP_DATA_ERRORS:
            effect_ids = ()
        for effect_id in effect_ids:
            try:
                effects.append(
                    (
                        str(effect_id),
                        bool(fbp_effect_visible_state(rig, effect_id)),
                        bool(fbp_effect_render_visible_state(rig, effect_id)),
                    )
                )
            except FBP_DATA_ERRORS:
                effects.append((str(effect_id), False, False))
        try:
            matrix = _rounded_sequence(tuple(value for row in rig.matrix_world for value in row))
        except FBP_DATA_ERRORS:
            matrix = []
        rigs.append(
            {
                "name": _safe_name(rig),
                "plane": _safe_name(plane),
                "matrix": matrix,
                "effects": effects,
                "visible": bool(getattr(rig, "fbp_is_visible", True)),
            }
        )

    camera = getattr(scene, "camera", None)
    try:
        camera_matrix = _rounded_sequence(
            tuple(value for row in camera.matrix_world for value in row)
        ) if camera is not None else []
    except FBP_DATA_ERRORS:
        camera_matrix = []
    camera_data = getattr(camera, "data", None) if camera is not None else None
    payload = {
        "scene": _safe_name(scene),
        "frame": int(getattr(scene, "frame_current", 0) or 0),
        "camera": _safe_name(camera),
        "camera_matrix": camera_matrix,
        "camera_type": str(getattr(camera_data, "type", "") or ""),
        "lens": round(float(getattr(camera_data, "lens", 0.0) or 0.0), 5),
        "ortho_scale": round(float(getattr(camera_data, "ortho_scale", 0.0) or 0.0), 5),
        "rigs": rigs,
    }
    return payload


def fbp_render_parity_signature(scene):
    payload = _scene_signature_payload(scene)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf8")
    return hashlib.sha256(encoded).hexdigest()


def fbp_render_parity_status(scene, *, check_stale=True):
    """Return the stored result; deep staleness checks run only on explicit audits."""
    if scene is None:
        return {
            "status": "NOT_RUN",
            "stale": False,
            "frame": 0,
            "engines": "",
            "timestamp": 0.0,
        }
    try:
        status = str(scene.get(_STATUS_KEY, "NOT_RUN") or "NOT_RUN").upper()
        stored_signature = str(scene.get(_SIGNATURE_KEY, "") or "")
        timestamp = float(scene.get(_TIME_KEY, 0.0) or 0.0)
        frame = int(scene.get(_FRAME_KEY, 0) or 0)
        engines = str(scene.get(_ENGINES_KEY, "") or "")
    except FBP_DATA_ERRORS:
        status = "NOT_RUN"
        stored_signature = ""
        timestamp = 0.0
        frame = 0
        engines = ""
    stale = bool(stored_signature and frame != int(getattr(scene, "frame_current", 0) or 0))
    if stored_signature and check_stale and not stale:
        try:
            stale = stored_signature != fbp_render_parity_signature(scene)
        except FBP_DATA_ERRORS:
            stale = True
    return {
        "status": status,
        "stale": bool(stale),
        "frame": frame,
        "engines": engines,
        "timestamp": timestamp,
    }


def _engine_identifiers(scene):
    """Return RNA-visible engine identifiers.

    Render engines registered from Python (notably Cycles in some Blender builds)
    are not guaranteed to appear in ``bl_rna.properties["engine"].enum_items``.
    This list is therefore only a source of candidates; availability is verified
    by a reversible assignment probe in :func:`_find_engine`.
    """
    identifiers = []
    try:
        prop = scene.render.bl_rna.properties["engine"]
        for collection_name in ("enum_items", "enum_items_static"):
            try:
                items = getattr(prop, collection_name, ())
                identifiers.extend(str(item.identifier) for item in items)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
    except (AttributeError, KeyError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    result = []
    seen = set()
    for identifier in identifiers:
        key = str(identifier or "").upper()
        if key and key not in seen:
            seen.add(key)
            result.append(str(identifier))
    return tuple(result)


def _engine_assignment_supported(scene, identifier):
    """Return whether Blender accepts an engine identifier, restoring state."""
    render = getattr(scene, "render", None)
    if render is None:
        return False
    try:
        original = str(getattr(render, "engine", "") or "")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        original = ""
    accepted = False
    try:
        render.engine = str(identifier)
        accepted = str(getattr(render, "engine", "") or "").upper() == str(identifier).upper()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        accepted = False
    finally:
        if original:
            try:
                render.engine = original
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
    return bool(accepted)


def _find_engine(scene, token):
    """Resolve an available render engine through a real assignment probe.

    Cycles can be present and selectable even when it is omitted from RNA enum
    introspection. Testing assignment is the authoritative availability check.
    """
    token = str(token or "").upper()
    identifiers = list(_engine_identifiers(scene))
    try:
        current = str(getattr(scene.render, "engine", "") or "")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        current = ""

    if token == "EEVEE":
        candidates = [
            current if "EEVEE" in current.upper() else "",
            *(identifier for identifier in identifiers if "EEVEE" in identifier.upper()),
            "BLENDER_EEVEE_NEXT",
            "BLENDER_EEVEE",
        ]
    else:
        candidates = [
            current if current.upper() == token else "",
            *(identifier for identifier in identifiers if identifier.upper() == token),
            token,
        ]

    seen = set()
    for candidate in candidates:
        candidate = str(candidate or "")
        key = candidate.upper()
        if not key or key in seen:
            continue
        seen.add(key)
        if _engine_assignment_supported(scene, candidate):
            return candidate
    return ""


def _snapshot_viewport_contract(scene):
    """Capture visible/render states touched by the managed render guard."""
    snapshot = {}
    try:
        rigs = tuple(iter_scene_fbp_rigs(scene))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        rigs = ()
    for rig in rigs:
        if not is_fbp_layer_object(rig):
            continue
        rig_name = _safe_name(rig)
        objects = [rig]
        try:
            plane = getattr(rig, "fbp_plane_target", None)
        except FBP_DATA_ERRORS:
            plane = None
        if plane is not None:
            objects.append(plane)
        for obj in objects:
            key = f"OBJECT::{rig_name}::{_safe_name(obj)}"
            try:
                snapshot[key] = (
                    bool(getattr(obj, "hide_viewport", False)),
                    bool(getattr(obj, "hide_render", False)),
                )
            except FBP_DATA_ERRORS:
                snapshot[key] = (False, False)

        try:
            effect_ids = tuple(fbp_effect_ids_for_rig(rig))
        except FBP_DATA_ERRORS:
            effect_ids = ()
        for effect_id in effect_ids:
            try:
                snapshot[f"EFFECT::{rig_name}::{effect_id}"] = (
                    bool(fbp_effect_visible_state(rig, effect_id)),
                    bool(fbp_effect_render_visible_state(rig, effect_id)),
                )
            except FBP_DATA_ERRORS:
                snapshot[f"EFFECT::{rig_name}::{effect_id}"] = (False, False)
            try:
                modifier = fbp_find_effect_modifier(rig, effect_id)
            except FBP_DATA_ERRORS:
                modifier = None
            if modifier is not None:
                try:
                    snapshot[f"MODIFIER::{rig_name}::{effect_id}"] = (
                        bool(getattr(modifier, "show_viewport", True)),
                        bool(getattr(modifier, "show_render", True)),
                    )
                except FBP_DATA_ERRORS:
                    pass

        if plane is not None:
            try:
                materials = tuple(
                    material for material in tuple(getattr(plane.data, "materials", ()) or ())
                    if material is not None
                )
            except FBP_DATA_ERRORS:
                materials = ()
            for material in materials:
                node_tree = getattr(material, "node_tree", None)
                if node_tree is None:
                    continue
                try:
                    nodes = tuple(node_tree.nodes)
                except FBP_DATA_ERRORS:
                    nodes = ()
                mute_by_effect = {}
                for node in nodes:
                    try:
                        effect_id = str(node.get("fbp_shader_effect_id", "") or "")
                    except FBP_DATA_ERRORS:
                        effect_id = ""
                    if not effect_id:
                        continue
                    try:
                        mute_by_effect.setdefault(effect_id, []).append(
                            bool(getattr(node, "mute", False))
                        )
                    except FBP_DATA_ERRORS:
                        pass
                for effect_id, mute_values in mute_by_effect.items():
                    snapshot[
                        f"NODES::{rig_name}::{_safe_name(material)}::{effect_id}"
                    ] = tuple(sorted(mute_values))
    return snapshot


def _compare_snapshots(before, after):
    issues = []
    for key in sorted(set(before) | set(after)):
        if key not in after:
            issues.append(f"Render removed viewport-state target: {key}")
        elif key not in before:
            issues.append(f"Render created unexpected viewport-state target: {key}")
        elif before[key] != after[key]:
            issues.append(f"Render did not restore viewport state: {key}")
    return issues


def _capture_image_pixels(image, *, label):
    if image is None:
        raise RuntimeError(f"Blender did not create {label}")
    try:
        image.update()
    except FBP_DATA_ERRORS:
        pass
    try:
        width = int(image.size[0])
        height = int(image.size[1])
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        width = height = 0
    if width <= 0 or height <= 0:
        raise RuntimeError(f"{label} has no pixel dimensions")
    values = array("f", [0.0]) * (width * height * 4)
    image.pixels.foreach_get(values)
    return width, height, values


def _capture_render_result():
    return _capture_image_pixels(
        bpy.data.images.get("Render Result"), label="Render Result image"
    )


def _capture_saved_render(filepath):
    candidates = [str(filepath or "")]
    if filepath and not str(filepath).lower().endswith(".png"):
        candidates.append(str(filepath) + ".png")
    path = next((item for item in candidates if item and os.path.isfile(item)), "")
    if not path:
        raise RuntimeError("Blender did not write the diagnostic render file")
    image = None
    try:
        image = bpy.data.images.load(path, check_existing=False)
        return _capture_image_pixels(image, label="Saved diagnostic render")
    finally:
        if image is not None:
            try:
                bpy.data.images.remove(image)
            except FBP_DATA_ERRORS:
                pass


def _store_image(name, width, height, pixels, *, engine, frame):
    image = bpy.data.images.get(name)
    if image is not None:
        try:
            incompatible = (
                int(image.size[0]) != int(width)
                or int(image.size[1]) != int(height)
                or str(getattr(image, "source", "GENERATED") or "GENERATED") != "GENERATED"
            )
        except FBP_DATA_ERRORS:
            incompatible = True
        if incompatible:
            try:
                bpy.data.images.remove(image)
            except FBP_DATA_ERRORS:
                pass
            image = None
    if image is None:
        image = bpy.data.images.new(
            name,
            width=int(width),
            height=int(height),
            alpha=True,
            float_buffer=True,
        )
    image.pixels.foreach_set(pixels)
    image.update()
    try:
        image.alpha_mode = "STRAIGHT"
        image.use_fake_user = True
        image["fbp_render_parity"] = True
        image["fbp_render_parity_engine"] = str(engine)
        image["fbp_render_parity_frame"] = int(frame)
    except FBP_DATA_ERRORS:
        pass
    return image


def _compare_rgba(reference, candidate):
    width_a, height_a, pixels_a = reference
    width_b, height_b, pixels_b = candidate
    if width_a != width_b or height_a != height_b:
        return {
            "compatible": False,
            "width_a": width_a,
            "height_a": height_a,
            "width_b": width_b,
            "height_b": height_b,
        }

    pixel_count = max(1, width_a * height_a)
    alpha_abs = 0.0
    alpha_max = 0.0
    rgb_abs = 0.0
    rgb_sq = 0.0
    coverage_a = 0.0
    coverage_b = 0.0
    visible_pixels = 0

    for index in range(0, pixel_count * 4, 4):
        a_alpha = float(pixels_a[index + 3])
        b_alpha = float(pixels_b[index + 3])
        delta_alpha = abs(a_alpha - b_alpha)
        alpha_abs += delta_alpha
        alpha_max = max(alpha_max, delta_alpha)
        coverage_a += max(0.0, min(1.0, a_alpha))
        coverage_b += max(0.0, min(1.0, b_alpha))
        if max(a_alpha, b_alpha) > 0.002:
            visible_pixels += 1
        for channel in range(3):
            # Compare premultiplied color so transparent RGB garbage does not
            # produce false engine differences around antialiased silhouettes.
            value_a = float(pixels_a[index + channel]) * a_alpha
            value_b = float(pixels_b[index + channel]) * b_alpha
            delta = abs(value_a - value_b)
            rgb_abs += delta
            rgb_sq += delta * delta

    color_samples = max(1, pixel_count * 3)
    return {
        "compatible": True,
        "width": width_a,
        "height": height_a,
        "alpha_mae": alpha_abs / pixel_count,
        "alpha_max": alpha_max,
        "coverage_a": coverage_a / pixel_count,
        "coverage_b": coverage_b / pixel_count,
        "coverage_delta": abs(coverage_a - coverage_b) / pixel_count,
        "premul_rgb_mae": rgb_abs / color_samples,
        "premul_rgb_rms": math.sqrt(rgb_sq / color_samples),
        "visible_pixels": visible_pixels,
    }


def _metric_level(metrics, *, strict=False):
    if not metrics.get("compatible", False):
        return "FAIL"
    alpha_mae = float(metrics.get("alpha_mae", 0.0) or 0.0)
    coverage_delta = float(metrics.get("coverage_delta", 0.0) or 0.0)
    rgb_mae = float(metrics.get("premul_rgb_mae", 0.0) or 0.0)
    if alpha_mae > 0.03 or coverage_delta > 0.03 or rgb_mae > 0.08:
        return "FAIL"
    warning_limits = (0.004, 0.004, 0.012) if strict else (0.012, 0.012, 0.035)
    if (
        alpha_mae > warning_limits[0]
        or coverage_delta > warning_limits[1]
        or rgb_mae > warning_limits[2]
    ):
        return "WARNING"
    return "PASS"


def _remember_attr(target, name, backup):
    if target is None or not hasattr(target, name):
        return
    try:
        backup.append((target, name, getattr(target, name)))
    except FBP_DATA_ERRORS:
        pass


def _restore_attrs(backup):
    for target, name, value in reversed(tuple(backup or ())):
        try:
            setattr(target, name, value)
        except FBP_DATA_ERRORS as exc:
            fbp_warn(f"Could not restore render parity setting {name}", exc)


@contextmanager
def _temporary_render_settings(scene, *, resolution, include_compositor, cycles_samples):
    backup = []
    render = scene.render
    for name in (
        "engine",
        "resolution_x",
        "resolution_y",
        "resolution_percentage",
        "film_transparent",
        "use_compositing",
        "use_sequencer",
        "use_border",
        "use_crop_to_border",
        "use_file_extension",
        "filepath",
    ):
        _remember_attr(render, name, backup)
    image_settings = getattr(render, "image_settings", None)
    for name in ("file_format", "color_mode", "color_depth"):
        _remember_attr(image_settings, name, backup)

    original_x = max(1, int(getattr(render, "resolution_x", 1920) or 1920))
    original_y = max(1, int(getattr(render, "resolution_y", 1080) or 1080))
    maximum = max(original_x, original_y)
    scale = max(32, int(resolution)) / maximum
    render.resolution_x = max(32, int(round(original_x * scale)))
    render.resolution_y = max(32, int(round(original_y * scale)))
    render.resolution_percentage = 100
    render.film_transparent = True
    if hasattr(render, "use_compositing"):
        render.use_compositing = bool(include_compositor)
    if hasattr(render, "use_sequencer"):
        render.use_sequencer = False
    if hasattr(render, "use_border"):
        render.use_border = False
    if hasattr(render, "use_crop_to_border"):
        render.use_crop_to_border = False
    if hasattr(render, "use_file_extension"):
        render.use_file_extension = False
    render.filepath = ""
    if image_settings is not None:
        try:
            image_settings.file_format = 'PNG'
            image_settings.color_mode = 'RGBA'
            image_settings.color_depth = '16'
        except FBP_DATA_ERRORS:
            pass

    cycles = getattr(scene, "cycles", None)
    for name in ("samples", "use_denoising", "use_adaptive_sampling"):
        _remember_attr(cycles, name, backup)
    if cycles is not None:
        try:
            if hasattr(cycles, "samples"):
                cycles.samples = max(1, int(cycles_samples))
            if hasattr(cycles, "use_denoising"):
                cycles.use_denoising = False
            if hasattr(cycles, "use_adaptive_sampling"):
                cycles.use_adaptive_sampling = False
        except FBP_DATA_ERRORS:
            pass

    try:
        yield
    finally:
        _restore_attrs(backup)


def _settle_render_guard(scene, *, attempts=8):
    """Synchronously retire the managed guard between diagnostic renders."""
    try:
        from .core import fbp_render_guard_idle_restore
    except (ImportError, AttributeError):
        return fbp_render_state(include_guard=True) == FBP_RENDER_IDLE
    for _index in range(max(1, int(attempts))):
        if fbp_render_state(include_guard=False) != FBP_RENDER_IDLE:
            time.sleep(0.02)
            continue
        try:
            fbp_render_guard_idle_restore(scene)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        if fbp_render_state(include_guard=True) == FBP_RENDER_IDLE:
            return True
        try:
            for view_layer in tuple(getattr(scene, "view_layers", ()) or ()):
                view_layer.update()
        except FBP_DATA_ERRORS:
            pass
        time.sleep(0.02)
    return fbp_render_state(include_guard=True) == FBP_RENDER_IDLE

def _render_engine(scene, engine, *, keep_image):
    scene.render.engine = str(engine)
    temp_root = tempfile.mkdtemp(prefix="fbp_render_parity_")
    render_path = os.path.join(temp_root, "render.png")
    scene.render.filepath = render_path
    started = time.perf_counter()
    render_error = None
    try:
        try:
            bpy.ops.render.render("EXEC_DEFAULT", write_still=True, use_viewport=False)
        except TypeError:
            # The operator signature can differ slightly between Blender builds.
            bpy.ops.render.render("EXEC_DEFAULT", write_still=True)
    except Exception as exc:
        render_error = exc
    elapsed = time.perf_counter() - started
    result = None
    stored_name = ""
    try:
        if render_error is None:
            try:
                result = _capture_render_result()
            except RuntimeError as render_result_error:
                # Blender 5.1 can finish a valid render while the Render Result
                # datablock still reports 0 x 0. The written diagnostic image is
                # an equivalent, deterministic source for the pixel comparison.
                try:
                    result = _capture_saved_render(render_path)
                except Exception as saved_error:
                    raise RuntimeError(
                        f"{render_result_error}; saved-render fallback failed: {saved_error}"
                    ) from saved_error
            if keep_image:
                label = "Eevee" if "EEVEE" in str(engine).upper() else str(engine).title()
                stored_name = f"{_IMAGE_PREFIX} — {label}"
                _store_image(
                    stored_name,
                    result[0],
                    result[1],
                    result[2],
                    engine=engine,
                    frame=int(getattr(scene, "frame_current", 0) or 0),
                )
    finally:
        guard_restored = _settle_render_guard(scene)
        shutil.rmtree(temp_root, ignore_errors=True)
    if render_error is not None:
        raise render_error
    if not guard_restored:
        raise RuntimeError("Frame By Plane render guard did not return to idle")
    return result, elapsed, stored_name


class FBP_OT_RunRenderParityAudit(Operator):
    bl_idname = "fbp.run_render_parity_audit"
    bl_label = "Run Viewport / Render Parity"
    bl_description = (
        "Render the active frame at diagnostic resolution in Eevee and Cycles, "
        "compare premultiplied RGBA output and verify that viewport/effect states "
        "are restored after real renders"
    )

    resolution: IntProperty(
        name="Maximum Resolution",
        description="Longest image edge used by each diagnostic render. The Scene aspect ratio is preserved",
        default=192,
        min=64,
        soft_max=512,
        max=1024,
    )
    cycles_samples: IntProperty(
        name="Cycles Samples",
        description="Temporary sample count used only by the diagnostic Cycles render",
        default=8,
        min=1,
        soft_max=64,
        max=256,
    )
    include_compositor: BoolProperty(
        name="Include Compositor",
        description="Include the current Scene compositor in both renders. Disable this to isolate Frame By Plane materials and geometry",
        default=False,
    )
    keep_images: BoolProperty(
        name="Keep Comparison Images",
        description="Store reusable Eevee and Cycles result images inside the .blend for visual inspection",
        default=True,
    )
    strict: BoolProperty(
        name="Strict Thresholds",
        description="Use tighter warning thresholds intended for shadeless and emission-only regression scenes",
        default=False,
    )
    require_both_engines: BoolProperty(
        name="Require Eevee and Cycles",
        description="Fail when either render engine is unavailable instead of recording an incomplete non-blocking diagnostic",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        return bool(
            scene
            and getattr(scene, "camera", None) is not None
            and fbp_render_state(include_guard=False) == FBP_RENDER_IDLE
        )

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self, width=500)

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "resolution")
        layout.prop(self, "cycles_samples")
        layout.prop(self, "include_compositor")
        layout.prop(self, "keep_images")
        layout.prop(self, "strict")
        layout.prop(self, "require_both_engines")
        info = layout.box()
        info.label(text="Runs two real renders of the current frame.", icon="INFO")
        info.label(text="Scene engine, resolution, compositor and Cycles settings are restored.")

    def execute(self, context):
        scene = context.scene
        if getattr(scene, "camera", None) is None:
            self.report({'ERROR'}, "A Scene Camera is required")
            return {'CANCELLED'}
        if fbp_render_state(include_guard=False) != FBP_RENDER_IDLE:
            self.report({'WARNING'}, "Another render is already running")
            return {'CANCELLED'}

        try:
            rig_count = sum(1 for rig in iter_scene_fbp_rigs(scene) if is_fbp_layer_object(rig))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            rig_count = 0
        if rig_count <= 0:
            self.report({'ERROR'}, "The active Scene contains no Frame By Plane layers")
            return {'CANCELLED'}

        eevee_engine = _find_engine(scene, "EEVEE")
        cycles_engine = _find_engine(scene, "CYCLES")
        issues = []
        warnings = []
        results = {}
        durations = {}
        stored_images = {}
        before = _snapshot_viewport_contract(scene)
        signature = fbp_render_parity_signature(scene)

        if not eevee_engine:
            issues.append("Eevee could not be selected by the render-engine probe")
        if not cycles_engine:
            message = "Cycles could not be selected by the render-engine probe"
            if self.require_both_engines:
                issues.append(message)
            else:
                warnings.append(message + "; cross-engine comparison was skipped")

        with _temporary_render_settings(
            scene,
            resolution=self.resolution,
            include_compositor=self.include_compositor,
            cycles_samples=self.cycles_samples,
        ):
            for label, engine in (("Eevee", eevee_engine), ("Cycles", cycles_engine)):
                if not engine:
                    continue
                try:
                    result, elapsed, stored_name = _render_engine(
                        scene, engine, keep_image=self.keep_images
                    )
                    results[label] = result
                    durations[label] = elapsed
                    if stored_name:
                        stored_images[label] = stored_name
                except Exception as exc:
                    issues.append(f"{label} render failed: {exc}")

        after = _snapshot_viewport_contract(scene)
        viewport_issues = _compare_snapshots(before, after)
        issues.extend(viewport_issues)

        metrics = None
        metric_level = "FAIL"
        if "Eevee" in results and "Cycles" in results:
            metrics = _compare_rgba(results["Eevee"], results["Cycles"])
            metric_level = _metric_level(metrics, strict=self.strict)
            if metric_level == "FAIL":
                issues.append("Eevee and Cycles output differ beyond the parity threshold")
            elif metric_level == "WARNING":
                warnings.append("Eevee and Cycles output differ beyond the preferred threshold")
        elif results and not self.require_both_engines:
            warnings.append("Only one render engine was available; its render completed but parity could not be compared")

        status = "PASS"
        if issues:
            status = "FAIL"
        elif warnings:
            status = "WARNING"
        try:
            scene[_STATUS_KEY] = status
            scene[_SIGNATURE_KEY] = signature
            scene[_TIME_KEY] = float(time.time())
            scene[_FRAME_KEY] = int(getattr(scene, "frame_current", 0) or 0)
            scene[_ENGINES_KEY] = "Eevee + Cycles" if metrics is not None else "Incomplete"
        except FBP_DATA_ERRORS:
            pass

        lines = [
            "Frame By Plane — Viewport / Render Parity",
            "==========================================",
            f"Generated: {datetime.now().isoformat(timespec='seconds')}",
            f"Scene: {_safe_name(scene)}",
            f"Frame: {int(getattr(scene, 'frame_current', 0) or 0)}",
            f"Frame By Plane layers: {rig_count}",
            f"Maximum diagnostic resolution: {int(self.resolution)} px",
            f"Cycles samples: {int(self.cycles_samples)}",
            f"Compositor included: {'Yes' if self.include_compositor else 'No'}",
            f"Strict thresholds: {'Yes' if self.strict else 'No'}",
            f"Both engines required: {'Yes' if self.require_both_engines else 'No'}",
            f"RNA-visible engines: {', '.join(_engine_identifiers(scene)) or 'None'}",
            f"Resolved Eevee engine: {eevee_engine or 'Not selectable'}",
            f"Resolved Cycles engine: {cycles_engine or 'Not selectable'}",
            "",
            "Engine renders",
            "--------------",
        ]
        for label in ("Eevee", "Cycles"):
            if label in results:
                width, height, _pixels = results[label]
                lines.append(
                    f"- {label}: PASS · {width} × {height} · {durations.get(label, 0.0):.3f} s"
                )
                if label in stored_images:
                    lines.append(f"  Stored image: {stored_images[label]}")
            else:
                lines.append(f"- {label}: NOT AVAILABLE")

        lines.extend(("", "Pixel comparison", "----------------"))
        if metrics is None:
            lines.append("- Comparison unavailable")
        elif not metrics.get("compatible", False):
            lines.append(
                "- FAIL · image dimensions differ: "
                f"{metrics.get('width_a', 0)}×{metrics.get('height_a', 0)} vs "
                f"{metrics.get('width_b', 0)}×{metrics.get('height_b', 0)}"
            )
        else:
            lines.extend(
                (
                    f"- Result: {metric_level}",
                    f"- Alpha MAE: {float(metrics.get('alpha_mae', 0.0)):.6f}",
                    f"- Maximum alpha delta: {float(metrics.get('alpha_max', 0.0)):.6f}",
                    f"- Alpha coverage delta: {float(metrics.get('coverage_delta', 0.0)):.6f}",
                    f"- Premultiplied RGB MAE: {float(metrics.get('premul_rgb_mae', 0.0)):.6f}",
                    f"- Premultiplied RGB RMS: {float(metrics.get('premul_rgb_rms', 0.0)):.6f}",
                    f"- Visible pixels: {int(metrics.get('visible_pixels', 0) or 0)}",
                )
            )

        lines.extend(("", "Viewport restoration", "--------------------"))
        lines.append(
            f"- {'PASS' if not viewport_issues else 'FAIL'} · "
            f"{len(before)} tracked state value(s), {len(viewport_issues)} mismatch(es)"
        )
        lines.extend(("", "Structural issues", "-----------------"))
        lines.extend(f"- {item}" for item in issues) if issues else lines.append("- None")
        lines.extend(("", "Warnings", "--------"))
        lines.extend(f"- {item}" for item in warnings) if warnings else lines.append("- None")
        lines.extend(("", "Validation totals", "-----------------"))
        lines.append(f"Structural issues: {len(issues)}")
        lines.append(f"Warnings: {len(warnings)}")
        lines.extend(("", "Result", "------", status if status != "FAIL" else "REVIEW REQUIRED"))

        summary = f"Render Parity · {status}"
        write_diagnostic_report(
            scene,
            "FBP_Render_Parity_Audit",
            lines,
            summary=summary,
            status="PASS" if status == "PASS" else ("WARNING" if status == "WARNING" else "ERROR"),
        )
        self.report(
            {'INFO'} if status == "PASS" else {'WARNING'},
            summary,
        )
        return {'FINISHED'}
