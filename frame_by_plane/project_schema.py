"""Persistent project contract for the Frame By Plane 7.1 LTS baseline.

Frame By Plane 7.1 is the first supported project baseline. This module records
that contract and validates loaded Scenes without attempting historic upgrades.
"""

from __future__ import annotations

from datetime import datetime, timezone

import bpy

from .constants import FBP_PUBLIC_VERSION_STRING
from .runtime import FBP_DATA_ERRORS


FBP_PROJECT_SCHEMA_VERSION = 3
FBP_PROJECT_SCHEMA_KEY = "fbp_project_schema"
FBP_PROJECT_VERSION_KEY = "fbp_project_version"
FBP_PROJECT_CONTRACT_AT_KEY = "fbp_project_contract_at"


def _scene_schema(scene):
    if scene is None:
        return 0
    try:
        return max(0, int(scene.get(FBP_PROJECT_SCHEMA_KEY, 0) or 0))
    except FBP_DATA_ERRORS:
        return 0


def scene_has_fbp_data(scene):
    if scene is None:
        return False
    try:
        if FBP_PROJECT_SCHEMA_KEY in scene or "fbp_layered_report_format" in scene:
            return True
    except FBP_DATA_ERRORS:
        pass
    try:
        for obj in tuple(getattr(scene, "objects", ()) or ()):
            if bool(getattr(obj, "is_fbp_control", False)) or bool(getattr(obj, "is_fbp_plane", False)):
                return True
            if bool(obj.get("fbp_native_backend", False)) or bool(obj.get("fbp_backend_type", "")):
                return True
    except FBP_DATA_ERRORS:
        return False
    return False


def mark_scene_current(scene):
    """Mark a Scene when current Frame By Plane data is first created in it."""
    if scene is None:
        return False
    try:
        stored = _scene_schema(scene)
        if stored > FBP_PROJECT_SCHEMA_VERSION:
            return False
        scene[FBP_PROJECT_SCHEMA_KEY] = FBP_PROJECT_SCHEMA_VERSION
        scene[FBP_PROJECT_VERSION_KEY] = FBP_PUBLIC_VERSION_STRING
        scene[FBP_PROJECT_CONTRACT_AT_KEY] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return True
    except FBP_DATA_ERRORS:
        return False


def project_schema_status(scene):
    """Return a read-only status for Project Doctor and diagnostics."""
    source = _scene_schema(scene)
    has_data = scene_has_fbp_data(scene)
    return {
        "has_fbp_data": has_data,
        "source_schema": source,
        "target_schema": FBP_PROJECT_SCHEMA_VERSION,
        "current": bool(not has_data or source == FBP_PROJECT_SCHEMA_VERSION),
        "missing_baseline": bool(has_data and source == 0),
        "unsupported_older": bool(has_data and 0 < source < FBP_PROJECT_SCHEMA_VERSION),
        "unsupported_future": bool(source > FBP_PROJECT_SCHEMA_VERSION),
    }


def project_schema_snapshot():
    results = []
    try:
        scenes = tuple(getattr(bpy.data, "scenes", ()) or ())
    except FBP_DATA_ERRORS:
        scenes = ()
    for scene in scenes:
        status = project_schema_status(scene)
        status["scene"] = str(getattr(scene, "name", "") or "")
        results.append(status)
    return {"schema": FBP_PROJECT_SCHEMA_VERSION, "scenes": results}

