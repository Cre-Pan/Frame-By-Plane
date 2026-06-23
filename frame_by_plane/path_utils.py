"""Path and import-name helpers for Frame by Plane."""

import os
import re
import time

from .constants import FBP_SUPPORTED_VIDEO_EXT, FBP_SUPPORTED_MEDIA_EXT, FBP_TECHNICAL_MAP_SUFFIXES

_NATURAL_NUMBER_SPLIT_RE = re.compile(r'(\d+)')


_UI_FILE_EXISTS_CACHE = {}
_UI_FILE_EXISTS_TTL = 2.0
_UI_FILE_EXISTS_LIMIT = 2048


def cached_file_exists(path, *, ttl=_UI_FILE_EXISTS_TTL):
    """Return file existence through a short bounded cache for UI redraws.

    UILists can redraw many times per second. Calling ``os.path.exists`` for
    every visible frame is especially expensive on network or cloud-synced
    folders, so cache the result briefly while still detecting changes quickly.
    """
    absolute = os.path.abspath(str(path or ""))
    if not absolute:
        return False
    key = os.path.normcase(absolute)
    now = time.monotonic()
    cached = _UI_FILE_EXISTS_CACHE.get(key)
    if cached and (now - float(cached[0])) < max(0.0, float(ttl)):
        return bool(cached[1])
    exists = os.path.isfile(absolute)
    if len(_UI_FILE_EXISTS_CACHE) >= _UI_FILE_EXISTS_LIMIT and key not in _UI_FILE_EXISTS_CACHE:
        oldest = min(_UI_FILE_EXISTS_CACHE, key=lambda item: _UI_FILE_EXISTS_CACHE[item][0])
        _UI_FILE_EXISTS_CACHE.pop(oldest, None)
    _UI_FILE_EXISTS_CACHE[key] = (now, bool(exists))
    return bool(exists)


def invalidate_file_exists_cache(path=None):
    """Invalidate one cached path, or every path when no value is supplied."""
    if path is None:
        _UI_FILE_EXISTS_CACHE.clear()
        return
    absolute = os.path.abspath(str(path or ""))
    if absolute:
        _UI_FILE_EXISTS_CACHE.pop(os.path.normcase(absolute), None)


def clear_file_exists_cache():
    """Clear cached UI file-status results after explicit relink/import work."""
    invalidate_file_exists_cache()




def natural_sort_key(s):
    """Human sorting for filenames: A1, A2, A12 instead of A1, A12, A2."""
    name = os.path.basename(str(s))
    stem, ext = os.path.splitext(name)
    parts = _NATURAL_NUMBER_SPLIT_RE.split(stem.lower())
    key = [int(part) if part.isdigit() else part for part in parts]
    key.append(ext.lower())
    return key


def is_supported_video_file(name):
    return os.path.splitext(str(name))[1].lower() in FBP_SUPPORTED_VIDEO_EXT


def is_supported_media_file(name):
    return os.path.splitext(str(name))[1].lower() in FBP_SUPPORTED_MEDIA_EXT


def is_hidden_import_name(name):
    """Ignore private/export-helper entries before project scanning.

    Underscore-prefixed folders are intentionally skipped by Frame by Plane.
    Dot-prefixed files also include macOS ``._`` resource forks and common
    hidden project folders, which must never become image layers.
    """
    base = os.path.basename(str(name))
    return base.startswith(('_', '.'))


def is_technical_map_file(name):
    stem = os.path.splitext(os.path.basename(str(name)))[0].lower()
    return any(stem.endswith(suffix) for suffix in FBP_TECHNICAL_MAP_SUFFIXES)


def clean_layer_name_from_path(path):
    base = os.path.basename(str(path).rstrip(os.sep))
    stem, ext = os.path.splitext(base)
    return stem if ext else base


