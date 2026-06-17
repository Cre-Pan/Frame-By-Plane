"""Shared imports, state and helper functions for Frame by Plane operators.

Operator classes live in focused modules and depend on this module only.
"""


import bpy
import json
import os
import shutil


from . import safe_tasks as _safe_tasks

from .core import (
    fbp_native_sequence_files_from_rig,
    fbp_rig_native_sequence_needs_rename,
)
from .layers import (
    get_or_create_child_collection,
    is_fbp_layer_object,
    set_collection_color_tag,
)
from .runtime import fbp_warn




def fbp_sequence_row_start_frame(rig, index):
    """Return the first scene frame occupied by a logical sequence row.

    The Frames UIList stores per-row durations. Timeline navigation always uses
    the first forward occurrence, including when playback is set to Ping-Pong.
    """
    if not rig:
        return None
    try:
        items = list(getattr(rig, "fbp_images", []))
        index = int(index)
        if not (0 <= index < len(items)):
            return None
        frame = int(getattr(rig, "fbp_start_frame", 1))
        for item in items[:index]:
            frame += max(1, int(getattr(item, "duration", 1) or 1))
        return frame
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        return None


def fbp_jump_timeline_to_sequence_row(context, rig, index):
    """Move the current scene timeline to the selected logical frame row."""
    target = fbp_sequence_row_start_frame(rig, index)
    if target is None:
        return False
    scene = getattr(context, "scene", None) if context else None
    if scene is None:
        scene = getattr(bpy.context, "scene", None)
    if scene is None:
        return False
    try:
        scene.frame_set(int(target))
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        try:
            scene.frame_current = int(target)
            return True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return False



def _fbp_refresh_pending_tree(context):
    """Refresh virtual Multiplane Setup UIList rows after operators change setup data."""
    from .ui_layout import fbp_refresh_pending_tree_rows
    if fbp_refresh_pending_tree_rows:
        try:
            fbp_refresh_pending_tree_rows(context)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass

def _fbp_active_pending_tree_row(scene):
    """Return the selected virtual setup tree row, or None."""
    try:
        idx = int(getattr(scene, 'fbp_pending_tree_rows_idx', 0))
        rows = getattr(scene, 'fbp_pending_tree_rows', [])
        if 0 <= idx < len(rows):
            return rows[idx]
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    return None

def _fbp_active_pending_index_and_collection(scene):
    """Return (pending_index, collection_path, row_type) from the setup tree selection."""
    row = _fbp_active_pending_tree_row(scene)
    if row is not None:
        row_type = getattr(row, 'row_type', 'LAYER')
        if row_type == 'GROUP':
            return -1, (getattr(row, 'collection_path', '') or ''), 'GROUP'
        try:
            pending_index = int(getattr(row, 'pending_index', -1))
        except Exception:
            pending_index = -1
        if 0 <= pending_index < len(scene.fbp_pending_planes):
            return pending_index, getattr(scene.fbp_pending_planes[pending_index], 'collection_name', '') or '', 'LAYER'
    idx = int(getattr(scene, 'fbp_pending_planes_idx', 0))
    if 0 <= idx < len(scene.fbp_pending_planes):
        return idx, getattr(scene.fbp_pending_planes[idx], 'collection_name', '') or '', 'LAYER'
    return -1, '', 'NONE'

def _fbp_find_insert_index_for_pending(scene, active_index, collection_name):
    """Insert below the active layer, or at the end of the selected collection."""
    count = len(scene.fbp_pending_planes)
    collection_name = collection_name or ''
    if 0 <= active_index < count:
        return active_index + 1
    if collection_name:
        last = -1
        for i, item in enumerate(scene.fbp_pending_planes):
            if (getattr(item, 'collection_name', '') or '') == collection_name:
                last = i
        if last >= 0:
            return last + 1
    return count

FBP_GENERATION_OVERLAY = globals().get("FBP_GENERATION_OVERLAY", {})
FBP_GENERATION_OVERLAY.setdefault("handle", None)
FBP_GENERATION_OVERLAY.setdefault("active", False)
FBP_GENERATION_OVERLAY.setdefault("text", "⌛  Generating Frame By Plane Sequence...")
_FBP_GENERATION_TIMERS = globals().get("_FBP_GENERATION_TIMERS", [])

def _fbp_tag_view3d_redraw():
    try:
        wm = bpy.context.window_manager
        for window in wm.windows:
            screen = getattr(window, 'screen', None)
            if not screen:
                continue
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

def _fbp_draw_generation_overlay():
    if not FBP_GENERATION_OVERLAY.get("active"):
        return
    try:
        import blf
        import gpu
        from gpu_extras.batch import batch_for_shader

        region = bpy.context.region
        if not region:
            return

        font_id = 0
        font_size = 14
        try:
            blf.size(font_id, font_size)
        except TypeError:
            blf.size(font_id, font_size, 72)

        text_value = str(FBP_GENERATION_OVERLAY.get("text") or "Generating Frame By Plane Sequence...")
        text_w, text_h = blf.dimensions(font_id, text_value)
        pad_x = 18.0
        pad_y = 11.0
        box_w = text_w + pad_x * 2.0
        box_h = text_h + pad_y * 2.0
        x = max(16.0, (float(region.width) - box_w) * 0.5)
        y = max(16.0, float(region.height) - box_h - 42.0)

        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        batch = batch_for_shader(
            shader,
            'TRIS',
            {
                "pos": (
                    (x, y),
                    (x + box_w, y),
                    (x + box_w, y + box_h),
                    (x, y + box_h),
                )
            },
            indices=((0, 1, 2), (0, 2, 3)),
        )
        gpu.state.blend_set('ALPHA')
        shader.bind()
        shader.uniform_float("color", (0.045, 0.045, 0.045, 0.94))
        batch.draw(shader)

        blf.color(font_id, 0.95, 0.95, 0.95, 1.0)
        blf.position(font_id, x + pad_x, y + pad_y, 0)
        blf.draw(font_id, text_value)
        gpu.state.blend_set('NONE')
    except Exception:
        try:
            gpu.state.blend_set('NONE')
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass

def _fbp_hide_generation_overlay(context=None):
    handle = FBP_GENERATION_OVERLAY.get("handle")
    FBP_GENERATION_OVERLAY["active"] = False
    FBP_GENERATION_OVERLAY["handle"] = None
    if handle is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handle, 'WINDOW')
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    try:
        target_context = context or bpy.context
        target_context.workspace.status_text_set(None)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    _fbp_tag_view3d_redraw()

def _fbp_show_generation_start_popup(context, title="Generating Frame By Plane Sequence"):
    """Show a temporary viewport overlay that can be removed programmatically."""
    _fbp_hide_generation_overlay(context)
    FBP_GENERATION_OVERLAY["text"] = f"⌛  {str(title or 'Generating Frame By Plane Sequence').rstrip('.')}..."
    FBP_GENERATION_OVERLAY["active"] = True
    try:
        FBP_GENERATION_OVERLAY["handle"] = bpy.types.SpaceView3D.draw_handler_add(
            _fbp_draw_generation_overlay, (), 'WINDOW', 'POST_PIXEL'
        )
        _fbp_tag_view3d_redraw()
    except Exception:
        FBP_GENERATION_OVERLAY["active"] = False
        try:
            context.workspace.status_text_set("Generating Frame By Plane Sequence...")
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass

def _fbp_add_generation_timer(context, operator, delay=0.20):
    """Defer heavy generation by one UI tick so the start popup can draw first."""
    try:
        operator._fbp_generation_timer = context.window_manager.event_timer_add(delay, window=context.window)
        if operator._fbp_generation_timer not in _FBP_GENERATION_TIMERS:
            _FBP_GENERATION_TIMERS.append(operator._fbp_generation_timer)
        context.window_manager.modal_handler_add(operator)
        return {'RUNNING_MODAL'}
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        # event_timer_add() may succeed before modal_handler_add() fails. Remove
        # that partially-created timer or it remains attached to the window.
        _fbp_remove_generation_timer(context, operator)
        fbp_warn('Could not defer Frame by Plane generation', exc)
        return None

def _fbp_remove_generation_timer(context, operator):
    try:
        timer = getattr(operator, '_fbp_generation_timer', None)
        if timer is not None:
            context.window_manager.event_timer_remove(timer)
            try:
                _FBP_GENERATION_TIMERS.remove(timer)
            except ValueError:
                pass
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        operator._fbp_generation_timer = None
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

def _fbp_generation_rig_issue(rig):
    """Return a small issue dictionary for rigs that need attention after generation."""
    if not rig or getattr(rig, 'fbp_is_color_plane', False):
        return None

    name = getattr(rig, 'name', 'Frame by Plane Layer')
    directory, files = fbp_native_sequence_files_from_rig(rig)
    files = list(files or [])

    if directory and files:
        missing = []
        for file_name in files:
            try:
                path = os.path.join(directory, file_name)
                if not os.path.isfile(path):
                    missing.append(file_name)
            except Exception:
                missing.append(str(file_name))
        if missing:
            return {
                "rig": name,
                "kind": "MISSING_FILES",
                "message": f"{len(missing)} source file(s) are missing",
                "files": missing[:6],
            }

        try:
            if len(files) > 1 and fbp_rig_native_sequence_needs_rename(rig):
                return {
                    "rig": name,
                    "kind": "RENAME_SEQUENCE",
                    "message": "Native sequence filenames may be unsafe for Blender",
                    "files": files[:6],
                }
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass

    plane = getattr(rig, 'fbp_plane_target', None)
    if plane and getattr(plane, 'type', None) == 'MESH':
        try:
            for slot in getattr(plane, 'material_slots', []):
                mat = getattr(slot, 'material', None)
                if not mat or not getattr(mat, 'use_nodes', False):
                    continue
                for node in getattr(mat.node_tree, 'nodes', []):
                    if getattr(node, 'type', None) != 'TEX_IMAGE':
                        continue
                    image = getattr(node, 'image', None)
                    if image is None:
                        return {"rig": name, "kind": "MISSING_IMAGE", "message": "Image Texture node has no image", "files": []}
                    filepath = bpy.path.abspath(getattr(image, 'filepath', '') or '')
                    if filepath and not os.path.exists(filepath) and getattr(image, 'source', '') != 'SEQUENCE':
                        return {"rig": name, "kind": "MISSING_IMAGE", "message": "Image file could not be found", "files": [os.path.basename(filepath)]}
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass

    return None

def _fbp_build_issue(name, directory, files, message, kind="BUILD_FAILED"):
    """Create a generation-report issue for a layer that failed before a rig existed."""
    return {
        "rig": str(name or "Layer"),
        "kind": str(kind or "BUILD_FAILED"),
        "message": str(message or "Could not generate this layer"),
        "directory": str(directory or ""),
        "files": [str(f) for f in (files or []) if f][:6],
    }

def _fbp_store_generation_report(context, *, mode="Sequence", generated_rigs=None, cancelled=False, message="", extra_issues=None):
    """Store the last generation result as scene custom properties for the popup actions."""
    sc = context.scene
    generated_rigs = [rig for rig in (generated_rigs or []) if rig]
    issues = list(extra_issues or [])
    for rig in generated_rigs:
        issue = _fbp_generation_rig_issue(rig)
        if issue:
            issues.append(issue)

    status = "CANCELLED" if cancelled else ("WARNING" if issues else "SUCCESS")
    report = {
        "mode": str(mode or "Sequence"),
        "status": status,
        "message": str(message or ""),
        "planes_created": len(generated_rigs),
        "issues_count": len(issues),
        "issues": issues,
        "problem_rigs": [issue.get("rig", "") for issue in issues if issue.get("rig")],
        "rename_rigs": [issue.get("rig", "") for issue in issues if issue.get("kind") == "RENAME_SEQUENCE" and issue.get("rig")],
    }
    try:
        sc["fbp_generation_report_json"] = json.dumps(report)
    except Exception:
        sc["fbp_generation_report_json"] = "{}"
    return report

def _fbp_generation_report(context):
    try:
        raw = context.scene.get("fbp_generation_report_json", "{}")
        data = json.loads(raw) if raw else {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _fbp_clear_generation_report(context):
    try:
        if "fbp_generation_report_json" in context.scene:
            del context.scene["fbp_generation_report_json"]
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        context.scene.fbp_generation_rename_items.clear()
        context.scene.fbp_generation_rename_index = 0
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

def _fbp_finish_generation_ui(context, report=None, *, show_popup=True):
    _fbp_hide_generation_overlay(context)
    try:
        context.window_manager.progress_end()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    if show_popup:
        # Bind the delayed dialog to the Scene that owns the report. A rapid
        # Scene switch must not open Scene A's result popup over Scene B.
        scene = getattr(context, "scene", None) if context else None
        try:
            scene_pointer = int(scene.as_pointer()) if scene else None
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            scene_pointer = None
        if scene_pointer is None:
            return

        # Allow one redraw after removing the temporary overlay, then open the
        # native result dialog. This guarantees the two windows never overlap.
        def _show_report():
            try:
                wm = bpy.context.window_manager
                for window in wm.windows:
                    target_scene = getattr(window, "scene", None)
                    try:
                        if not target_scene or int(target_scene.as_pointer()) != scene_pointer:
                            continue
                    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                        continue
                    screen = getattr(window, 'screen', None)
                    if not screen:
                        continue
                    for area in screen.areas:
                        if area.type != 'VIEW_3D':
                            continue
                        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                        if region is None:
                            continue
                        with bpy.context.temp_override(
                            window=window, screen=screen, area=area, region=region, scene=target_scene
                        ):
                            bpy.ops.fbp.generation_report_popup('INVOKE_DEFAULT')
                        return None
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
            return None
        if not _safe_tasks.schedule_once(
            f'operators.generation_report_popup.{scene_pointer}',
            _show_report,
            first_interval=0.12,
        ):
            # A report popup is already pending or the timer system is not
            # available. Avoid opening a second overlapping dialog.
            return

def _fbp_rigs_from_report(context, key="problem_rigs"):
    report = _fbp_generation_report(context)
    names = [str(name) for name in report.get(key, []) if name]
    rigs = []
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj and is_fbp_layer_object(obj):
            rigs.append(obj)
    return rigs

def _fbp_sync_generation_rename_items(context):
    """Populate the scene-side rename UIList from the current generation report."""
    scene = context.scene
    try:
        items = scene.fbp_generation_rename_items
        items.clear()
    except Exception:
        return []

    report = _fbp_generation_report(context)
    issues = list(report.get("issues", []) or [])
    created = []
    for issue in issues:
        kind = str(issue.get("kind", "") or "")
        if kind not in {"RENAME_SEQUENCE", "RENAMED_SEQUENCE"}:
            continue
        rig_name = str(issue.get("rig", "") or "")
        if not rig_name:
            continue
        item = items.add()
        item.rig_name = rig_name
        item.display_name = rig_name
        item.is_renamed = bool(issue.get("renamed", False) or kind == "RENAMED_SEQUENCE")
        item.message = str(issue.get("message", "Renamed successfully" if item.is_renamed else "Needs rename") or "")
        files = list(issue.get("files", []) or [])
        item.preview_files = ", ".join(str(f) for f in files[:3])
        created.append(rig_name)

    try:
        scene.fbp_generation_rename_index = min(max(int(getattr(scene, 'fbp_generation_rename_index', 0)), 0), max(len(items) - 1, 0))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    return created

def _fbp_mark_generation_sequence_renamed(context, rig_name, files=None):
    """Mark one generation-report sequence as renamed, so the UIList shows a checkmark."""
    rig_name = str(rig_name or "")
    if not rig_name:
        return False
    report = _fbp_generation_report(context)
    if not report:
        return False

    changed = False
    issues = list(report.get("issues", []) or [])
    display_files = [str(f) for f in (files or []) if f]
    for issue in issues:
        if str(issue.get("rig", "") or "") != rig_name:
            continue
        if str(issue.get("kind", "") or "") not in {"RENAME_SEQUENCE", "RENAMED_SEQUENCE"}:
            continue
        issue["kind"] = "RENAMED_SEQUENCE"
        issue["renamed"] = True
        issue["message"] = "Renamed successfully"
        if display_files:
            issue["files"] = display_files[:6]
        changed = True
        break

    if not changed:
        return False

    renamed = set(str(name) for name in (report.get("renamed_rigs", []) or []) if name)
    renamed.add(rig_name)
    report["renamed_rigs"] = sorted(renamed)
    report["rename_rigs"] = [
        str(issue.get("rig", "") or "")
        for issue in issues
        if str(issue.get("kind", "") or "") == "RENAME_SEQUENCE" and issue.get("rig")
    ]
    report["issues"] = issues
    try:
        context.scene["fbp_generation_report_json"] = json.dumps(report)
    except Exception:
        return False
    _fbp_sync_generation_rename_items(context)
    return True

def _fbp_active_generation_rename_item(context):
    try:
        items = context.scene.fbp_generation_rename_items
        if not items:
            return None
        idx = int(getattr(context.scene, 'fbp_generation_rename_index', 0))
        idx = min(max(idx, 0), len(items) - 1)
        return items[idx]
    except Exception:
        return None

FBP_BG_RENDER_STATE = globals().get("FBP_BG_RENDER_STATE", {})
for _key, _default in {
    "process": None,
    "log_handle": None,
    "log_path": "",
    "temp_dir": "",
    "out_dir": "",
    "prefix": "",
    "start": 0,
    "end": 0,
    "total": 0,
    "started_at": 0.0,
    "session_token": "",
}.items():
    FBP_BG_RENDER_STATE.setdefault(_key, _default)
del _key, _default

def _fbp_bg_clear_runtime_state(scene=None):
    """Clear stale background-render process/log state after finish or unload."""
    _fbp_bg_cleanup_temp_files()
    FBP_BG_RENDER_STATE.update({
        "process": None,
        "log_handle": None,
        "log_path": "",
        "temp_dir": "",
        "out_dir": "",
        "prefix": "",
        "start": 0,
        "end": 0,
        "total": 0,
        "started_at": 0.0,
        "session_token": "",
    })
    if scene:
        try:
            scene.fbp_background_render_running = False
            scene.fbp_background_render_progress = 0
            scene.fbp_background_render_total = 0
            scene.fbp_background_render_output_dir = ""
            scene.fbp_background_render_status = "Idle"
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass

def _fbp_bg_process_running():
    proc = FBP_BG_RENDER_STATE.get("process")
    try:
        return bool(proc and proc.poll() is None)
    except Exception:
        return False

def _fbp_bg_close_log_handle():
    handle = FBP_BG_RENDER_STATE.get("log_handle")
    if handle:
        try:
            handle.close()
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    FBP_BG_RENDER_STATE["log_handle"] = None

def _fbp_bg_cleanup_temp_files():
    """Close the background log and remove the temporary script directory."""
    _fbp_bg_close_log_handle()
    temp_dir = str(FBP_BG_RENDER_STATE.get("temp_dir", "") or "")
    if temp_dir:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except (OSError, RuntimeError, TypeError, ValueError):
            pass
    FBP_BG_RENDER_STATE["temp_dir"] = ""
    FBP_BG_RENDER_STATE["log_path"] = ""

def _fbp_bg_count_rendered_frames(out_dir, prefix):
    try:
        names = os.listdir(out_dir) if out_dir and os.path.isdir(out_dir) else []
    except Exception:
        return 0
    prefix = str(prefix or "")
    count = 0
    started_at = float(FBP_BG_RENDER_STATE.get("started_at", 0.0) or 0.0)
    for name in names:
        low = str(name).lower()
        if not (name.startswith(prefix) and low.endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr"))):
            continue
        if started_at > 0.0:
            try:
                if os.path.getmtime(os.path.join(out_dir, name)) < started_at - 1.0:
                    continue
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
        count += 1
    return count

def _fbp_bg_update_scene_status(scene, message=None):
    if not scene:
        return
    total = int(FBP_BG_RENDER_STATE.get("total", 0) or 0)
    progress = _fbp_bg_count_rendered_frames(
        FBP_BG_RENDER_STATE.get("out_dir", ""),
        FBP_BG_RENDER_STATE.get("prefix", ""),
    )
    progress = max(0, min(progress, total)) if total else progress
    remaining = max(0, total - progress)
    current = int(FBP_BG_RENDER_STATE.get("start", 0) or 0) + max(0, progress - 1)
    running = _fbp_bg_process_running()
    if message is None:
        if running:
            if progress > 0:
                next_frame = min(int(FBP_BG_RENDER_STATE.get("end", current) or current), current + 1)
                message = f"Rendered {progress}/{total} · Next Frame {next_frame} · {remaining} remaining"
            else:
                message = f"Rendering starting · {total} frames total"
        else:
            message = "Idle"
    try:
        scene.fbp_background_render_running = bool(running)
        scene.fbp_background_render_progress = int(progress)
        scene.fbp_background_render_total = int(total)
        scene.fbp_background_render_output_dir = FBP_BG_RENDER_STATE.get("out_dir", "")
        scene.fbp_background_render_status = str(message)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

def _fbp_bg_terminate_process(scene=None):
    proc = FBP_BG_RENDER_STATE.get("process")
    if not proc:
        _fbp_bg_update_scene_status(scene, "No background render is running")
        return False
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                    pass
        _fbp_bg_update_scene_status(scene, "Background render stopped")
        return True
    except Exception:
        _fbp_bg_update_scene_status(scene, "Could not stop background render")
        return False
    finally:
        FBP_BG_RENDER_STATE["process"] = None
        FBP_BG_RENDER_STATE["session_token"] = ""
        _fbp_bg_cleanup_temp_files()

def _fbp_select_pending_index(context, pending_index):
    scene = context.scene
    try:
        scene.fbp_pending_planes_idx = max(0, min(int(pending_index), max(0, len(scene.fbp_pending_planes) - 1)))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    _fbp_refresh_pending_tree(context)
    # Move the virtual tree selection to the matching layer row when possible.
    try:
        for row_index, row in enumerate(scene.fbp_pending_tree_rows):
            if getattr(row, 'row_type', 'LAYER') == 'LAYER' and int(getattr(row, 'pending_index', -1)) == pending_index:
                scene.fbp_pending_tree_rows_idx = row_index
                break
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

def _fbp_refresh_layer_tree(context):
    """Refresh virtual Layers UIList rows after operators change layer/collection state."""
    from .ui_layout import fbp_refresh_layer_tree_rows
    if fbp_refresh_layer_tree_rows:
        try:
            fbp_refresh_layer_tree_rows(context)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass

def _fbp_color_tag_for_group(key, color_map):
    key = str(key or "Root")
    if key not in color_map:
        # Blender Collections expose eight actual color tags. COLOR_09 remains
        # available for neutral Frame by Plane layer rows, but not collections.
        color_map[key] = f"COLOR_{(len(color_map) % 8) + 1:02d}"
    return color_map[key]

def _fbp_get_or_create_collection_path(parent_collection, collection_path, color_tag=None):
    """Create nested collections, keeping parent folders colorless."""
    current = parent_collection
    parts = [part.strip() for part in str(collection_path or '').split(' / ') if part.strip()]
    for index, part in enumerate(parts):
        is_leaf = index == len(parts) - 1
        current = get_or_create_child_collection(current, part)
        # Reapplying NONE is intentional: a collection may first be created as
        # a leaf and later become a parent when another setup row is processed.
        set_collection_color_tag(current, color_tag if is_leaf and color_tag else 'NONE')
    return current

def fbp_hex_name_from_color(color):
    try:
        r = int(max(0.0, min(1.0, float(color[0]))) * 255 + 0.5)
        g = int(max(0.0, min(1.0, float(color[1]))) * 255 + 0.5)
        b = int(max(0.0, min(1.0, float(color[2]))) * 255 + 0.5)
        return f"#{r:02X}{g:02X}{b:02X}"
    except Exception:
        return "Color"

def fbp_default_color_plane_name(kind, color):
    if kind == 'GRADIENT':
        return "Gradient Plane"
    if kind == 'HOLDOUT':
        return "Holdout Plane"
    return f"Color Plane {fbp_hex_name_from_color(color)}"


def unregister():
    """Remove transient overlays/timers when the extension is disabled or reloaded."""
    _fbp_hide_generation_overlay(getattr(bpy, "context", None))
    try:
        wm = getattr(bpy.context, "window_manager", None)
        for timer in list(_FBP_GENERATION_TIMERS):
            try:
                if wm is not None:
                    wm.event_timer_remove(timer)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        _FBP_GENERATION_TIMERS.clear()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        _FBP_GENERATION_TIMERS.clear()
