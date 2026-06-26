"""Shared diagnostic-report storage and lightweight UI state.

All maintenance tools write their human-readable report through this module.
The Text datablock remains the complete source of truth, while the Scene keeps
only a small pointer and summary for the N-panel. No report content is stored
outside the current .blend file.
"""

from __future__ import annotations

import time

import bpy

from .runtime import FBP_DATA_ERRORS, fbp_warn

LAST_REPORT_NAME_KEY = "fbp_last_diagnostic_report"
LAST_REPORT_SUMMARY_KEY = "fbp_last_diagnostic_summary"
LAST_REPORT_STATUS_KEY = "fbp_last_diagnostic_status"
LAST_REPORT_TIME_KEY = "fbp_last_diagnostic_time"

_VALID_STATUS = {"INFO", "WARNING", "ERROR", "PASS"}


def _normalized_lines(lines):
    if isinstance(lines, str):
        return lines.splitlines()
    try:
        return [str(line) for line in lines]
    except TypeError:
        return [str(lines)]


def write_diagnostic_report(scene, name, lines, *, summary="", status="INFO"):
    """Create/update a Text report and expose a compact last-report summary.

    The helper deliberately stores only strings and a timestamp on the Scene;
    it never keeps Python references to RNA datablocks across rebuilds.
    """
    report_name = str(name or "FBP_Diagnostic_Report").strip() or "FBP_Diagnostic_Report"
    report_lines = _normalized_lines(lines)
    status_key = str(status or "INFO").upper()
    if status_key not in _VALID_STATUS:
        status_key = "INFO"
    try:
        text = bpy.data.texts.get(report_name) or bpy.data.texts.new(report_name)
        text.clear()
        text.write("\n".join(report_lines))
    except FBP_DATA_ERRORS as exc:
        fbp_warn(f"Could not write diagnostic report {report_name}", exc)
        return None

    if scene is not None:
        try:
            scene[LAST_REPORT_NAME_KEY] = report_name
            scene[LAST_REPORT_SUMMARY_KEY] = str(summary or report_name)
            scene[LAST_REPORT_STATUS_KEY] = status_key
            scene[LAST_REPORT_TIME_KEY] = float(time.time())
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
    deliberately lightweight so the Developer UI can enable Copy buttons
    without running any audit again.
    """
    if text is None:
        return ()
    try:
        content = text.as_string() if hasattr(text, "as_string") else str(text or "")
    except FBP_DATA_ERRORS:
        return ()
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


def diagnostic_report_status(text):
    """Return NOT_RUN, PASS, WARNING or FAIL for a named report."""
    if text is None:
        return "NOT_RUN"
    try:
        content = text.as_string() if hasattr(text, "as_string") else str(text or "")
    except FBP_DATA_ERRORS:
        return "NOT_RUN"
    messages = diagnostic_report_messages(text)
    if messages:
        if "REVIEW REQUIRED" in content or ": FAIL" in content or ": ERROR" in content:
            return "FAIL"
        return "WARNING"
    if "REVIEW REQUIRED" in content:
        return "FAIL"
    if "Result\n------\nPASS" in content or "Result\r\n------\r\nPASS" in content:
        return "PASS"
    if "Structural issues: 0" in content or "Failures: 0" in content:
        return "PASS"
    if content.strip():
        return "INFO"
    return "NOT_RUN"
