"""Shared diagnostic-report storage and lightweight UI state.

All maintenance tools write their human-readable report through this module.
The Text datablock remains the complete source of truth, while the Scene keeps
only a small pointer and summary for the maintenance UI. No report content is
stored outside the current .blend file.
"""

from __future__ import annotations

import os
import time

import bpy

from .constants import FBP_PUBLIC_VERSION_STRING
from .runtime import FBP_DATA_ERRORS, fbp_warn

LAST_REPORT_NAME_KEY = "fbp_last_diagnostic_report"
LAST_REPORT_SUMMARY_KEY = "fbp_last_diagnostic_summary"
LAST_REPORT_STATUS_KEY = "fbp_last_diagnostic_status"
LAST_REPORT_TIME_KEY = "fbp_last_diagnostic_time"

REPORT_SCHEMA_KEY = "fbp_diagnostic_schema"
REPORT_STATUS_KEY = "fbp_diagnostic_status"
REPORT_SUMMARY_KEY = "fbp_diagnostic_summary"
REPORT_TIME_KEY = "fbp_diagnostic_time"
REPORT_VERSION_KEY = "fbp_diagnostic_version"
REPORT_RUN_ID_KEY = "fbp_diagnostic_run_id"
REPORT_BLEND_FILE_KEY = "fbp_diagnostic_blend_file"
REPORT_BLENDER_VERSION_KEY = "fbp_diagnostic_blender_version"
REPORT_SCHEMA_VERSION = 3

RELEASE_SESSION_ID_KEY = "fbp_rc_session_id"
RELEASE_SESSION_TIME_KEY = "fbp_rc_session_time"
RELEASE_SESSION_FILE_KEY = "fbp_rc_session_file"
RELEASE_SESSION_BLENDER_KEY = "fbp_rc_session_blender"

_VALID_STATUS = {"INFO", "WARNING", "ERROR", "PASS"}


def _normalized_blend_filepath(filepath=None):
    """Return a stable absolute .blend path for diagnostic provenance checks."""
    if filepath is None:
        try:
            filepath = str(getattr(bpy.data, "filepath", "") or "")
        except FBP_DATA_ERRORS:
            filepath = ""
    value = str(filepath or "").strip()
    if not value:
        return ""
    try:
        value = bpy.path.abspath(value)
    except FBP_DATA_ERRORS:
        pass
    try:
        return os.path.normcase(os.path.normpath(os.path.abspath(value)))
    except (OSError, TypeError, ValueError):
        return value


def _current_blender_version():
    try:
        return ".".join(str(int(value)) for value in tuple(bpy.app.version)[:3])
    except (AttributeError, TypeError, ValueError):
        return ""


def release_session_metadata(scene):
    """Return immutable provenance for the active diagnostic session."""
    if scene is None:
        return {
            "run_id": "",
            "timestamp": 0.0,
            "filepath": "",
            "blender_version": "",
        }
    try:
        run_id = str(scene.get(RELEASE_SESSION_ID_KEY, "") or "")
        timestamp = float(scene.get(RELEASE_SESSION_TIME_KEY, 0.0) or 0.0)
        filepath = str(scene.get(RELEASE_SESSION_FILE_KEY, "") or "")
        blender_version = str(scene.get(RELEASE_SESSION_BLENDER_KEY, "") or "")
    except (ReferenceError, RuntimeError, TypeError, ValueError):
        return {
            "run_id": "",
            "timestamp": 0.0,
            "filepath": "",
            "blender_version": "",
        }
    return {
        "run_id": run_id,
        "timestamp": timestamp,
        "filepath": _normalized_blend_filepath(filepath),
        "blender_version": blender_version,
    }


def _normalized_lines(lines):
    if isinstance(lines, str):
        return lines.splitlines()
    try:
        return [str(line) for line in lines]
    except TypeError:
        return [str(lines)]


def _report_content(text):
    if text is None:
        return ""
    try:
        return text.as_string() if hasattr(text, "as_string") else str(text or "")
    except FBP_DATA_ERRORS:
        return ""


def write_diagnostic_report(scene, name, lines, *, summary="", status="INFO"):
    """Create/update a Text report and expose a compact last-report summary.

    Every report also receives machine-readable Text ID metadata. Diagnostic tools
    can therefore consume exact statuses without depending on fragile substring
    matches in the human-readable body. The Scene still stores only the latest
    report pointer and summary.
    """
    report_name = str(name or "FBP_Diagnostic_Report").strip() or "FBP_Diagnostic_Report"
    report_lines = _normalized_lines(lines)
    status_key = str(status or "INFO").upper()
    if status_key not in _VALID_STATUS:
        status_key = "INFO"
    timestamp = float(time.time())
    summary_text = str(summary or report_name)
    session = release_session_metadata(scene)
    blend_file = _normalized_blend_filepath()
    blender_version = _current_blender_version()
    try:
        text = bpy.data.texts.get(report_name) or bpy.data.texts.new(report_name)
        text.clear()
        text.write("\n".join(report_lines))
    except FBP_DATA_ERRORS as exc:
        fbp_warn(f"Could not write diagnostic report {report_name}", exc)
        return None

    # Text datablocks are Blender IDs and support custom properties in Blender 5.2.
    # Keep this metadata best-effort so a restricted startup state can never
    # prevent the human-readable report from being written.
    try:
        text[REPORT_SCHEMA_KEY] = int(REPORT_SCHEMA_VERSION)
        text[REPORT_STATUS_KEY] = status_key
        text[REPORT_SUMMARY_KEY] = summary_text
        text[REPORT_TIME_KEY] = timestamp
        text[REPORT_VERSION_KEY] = str(FBP_PUBLIC_VERSION_STRING)
        text[REPORT_RUN_ID_KEY] = str(session.get("run_id", "") or "")
        text[REPORT_BLEND_FILE_KEY] = blend_file
        text[REPORT_BLENDER_VERSION_KEY] = blender_version
    except FBP_DATA_ERRORS as exc:
        fbp_warn(f"Could not attach diagnostic metadata to {report_name}", exc)

    if scene is not None:
        try:
            scene[LAST_REPORT_NAME_KEY] = report_name
            scene[LAST_REPORT_SUMMARY_KEY] = summary_text
            scene[LAST_REPORT_STATUS_KEY] = status_key
            scene[LAST_REPORT_TIME_KEY] = timestamp
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not update diagnostic report state", exc)
    return text


def last_diagnostic_report(scene):
    """Return ``(Text, summary, status, timestamp)`` for the current Scene."""
    if scene is None:
        return None, "", "INFO", 0.0
    try:
        name = str(scene.get(LAST_REPORT_NAME_KEY, "") or "")
        summary = str(scene.get(LAST_REPORT_SUMMARY_KEY, "") or "")
        status = str(scene.get(LAST_REPORT_STATUS_KEY, "INFO") or "INFO").upper()
        timestamp = float(scene.get(LAST_REPORT_TIME_KEY, 0.0) or 0.0)
    except FBP_DATA_ERRORS:
        return None, "", "INFO", 0.0
    text = bpy.data.texts.get(name) if name else None
    if text is None:
        return None, "", "INFO", timestamp
    return text, summary or name, status if status in _VALID_STATUS else "INFO", timestamp


def diagnostic_report_messages(text):
    """Return concise actionable messages from a diagnostic Text datablock.

    The extractor understands the section headings used by Frame By Plane
    reports and also catches explicit FAIL / ERROR result lines. It is kept
    deliberately lightweight so the maintenance UI can enable Copy buttons
    without running any audit again.
    """
    content = _report_content(text)
    if not content:
        return ()

    interesting = {
        "failures",
        "errors / structural issues",
        "errors",
        "structural issues",
        "issues",
        "warnings",
    }
    lines = content.splitlines()
    collected = []
    in_section = False

    for index, raw in enumerate(lines):
        line = str(raw or "").strip()
        lower = line.lower()
        next_line = str(lines[index + 1] or "").strip() if index + 1 < len(lines) else ""

        if line and next_line and set(next_line) <= {"-", "="}:
            in_section = lower in interesting
            continue
        if in_section and line and set(line) <= {"-", "="}:
            continue
        if in_section and not line:
            in_section = False
            continue

        candidate = ""
        if in_section and line:
            candidate = line[2:].strip() if line.startswith("- ") else line
        elif line == "REVIEW REQUIRED":
            candidate = line
        elif ": FAIL" in line or ": ERROR" in line:
            candidate = line

        if not candidate:
            continue
        if candidate.lower() in {"none", "- none", "pass", "warnings: 0", "structural issues: 0"}:
            continue
        if candidate not in collected:
            collected.append(candidate)
    if len(collected) > 1 and "REVIEW REQUIRED" in collected:
        collected.remove("REVIEW REQUIRED")
    return tuple(collected)

