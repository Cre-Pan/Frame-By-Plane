"""Path and import-name helpers for Frame by Plane."""

import os
import re
import time

from .constants import FBP_SUPPORTED_VIDEO_EXT, FBP_SUPPORTED_MEDIA_EXT, FBP_TECHNICAL_MAP_SUFFIXES

_NATURAL_NUMBER_SPLIT_RE = re.compile(r'(\d+)')


_UI_FILE_EXISTS_CACHE = {}
_UI_FILE_EXISTS_TTL = 2.0
_UI_FILE_EXISTS_LIMIT = 2048
_NATURAL_SORT_KEY_CACHE = globals().get("_NATURAL_SORT_KEY_CACHE", {})
if not isinstance(_NATURAL_SORT_KEY_CACHE, dict):
    _NATURAL_SORT_KEY_CACHE = {}
_NATURAL_SORT_KEY_SCHEMA = 2
if int(globals().get("_NATURAL_SORT_KEY_CACHE_SCHEMA", 0) or 0) != _NATURAL_SORT_KEY_SCHEMA:
    _NATURAL_SORT_KEY_CACHE.clear()
_NATURAL_SORT_KEY_CACHE_SCHEMA = _NATURAL_SORT_KEY_SCHEMA
_NATURAL_SORT_KEY_LIMIT = 8192
_EXT_LOWER_CACHE = globals().get("_EXT_LOWER_CACHE", {})
if not isinstance(_EXT_LOWER_CACHE, dict):
    _EXT_LOWER_CACHE = {}
_EXT_LOWER_CACHE_LIMIT = 8192
_HIDDEN_IMPORT_NAME_CACHE = globals().get("_HIDDEN_IMPORT_NAME_CACHE", {})
if not isinstance(_HIDDEN_IMPORT_NAME_CACHE, dict):
    _HIDDEN_IMPORT_NAME_CACHE = {}
_HIDDEN_IMPORT_NAME_CACHE_LIMIT = 8192
_TECHNICAL_MAP_CACHE = globals().get("_TECHNICAL_MAP_CACHE", {})
if not isinstance(_TECHNICAL_MAP_CACHE, dict):
    _TECHNICAL_MAP_CACHE = {}
_TECHNICAL_MAP_CACHE_LIMIT = 8192
_CLEAN_LAYER_NAME_CACHE = globals().get("_CLEAN_LAYER_NAME_CACHE", {})
if not isinstance(_CLEAN_LAYER_NAME_CACHE, dict):
    _CLEAN_LAYER_NAME_CACHE = {}
_CLEAN_LAYER_NAME_CACHE_LIMIT = 8192


def _bounded_cache_set(cache, key, value, limit):
    if len(cache) >= int(limit) and key not in cache:
        cache.clear()
    cache[key] = value
    return value


def cached_file_exists(path, *, ttl=_UI_FILE_EXISTS_TTL):
    """Return file existence through a short bounded cache for UI redraws.

    UILists can redraw many times per second. Calling ``os.path.exists`` for
    every visible frame is especially expensive on network or cloud-synced
    folders, so cache the result briefly while still detecting changes quickly.
    """
    if not path:
        return False
    absolute = os.path.abspath(str(path))
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


def natural_sort_key(s):
    """Human sorting for filenames: A1, A2, A12 instead of A1, A12, A2.

    Import folders and Layer Lists sort the same names repeatedly while the UI
    redraws. The key is deterministic, so keep a bounded cache of immutable
    tuples. Tagged tokens guarantee that Python never compares an integer with
    a string when one name ends where another continues (for example A/A1).
    """
    name = os.path.basename(str(s))
    cached = _NATURAL_SORT_KEY_CACHE.get(name)
    if cached is not None:
        return cached
    stem, ext = os.path.splitext(name)
    parts = _NATURAL_NUMBER_SPLIT_RE.split(stem.lower())
    tokens = tuple(
        (1, int(part)) if part.isdigit() else (0, part)
        for part in parts
    )
    # Keep the extension outside the token tuple: when one stem is an exact
    # prefix of another, tuple prefix ordering correctly places A before A1.
    key = (tokens, ext.lower(), name.casefold())
    if len(_NATURAL_SORT_KEY_CACHE) >= _NATURAL_SORT_KEY_LIMIT and name not in _NATURAL_SORT_KEY_CACHE:
        _NATURAL_SORT_KEY_CACHE.clear()
    _NATURAL_SORT_KEY_CACHE[name] = key
    # Always return the cached immutable type.  Returning a list only on the
    # first lookup made one directory scan compare ``list`` and ``tuple`` keys
    # as soon as a repeated filename hit the cache, which aborts Multiplane
    # discovery on Python 3 with ``TypeError: '<' not supported``.
    return key


def _lower_ext(name):
    key = str(name or "")
    cached = _EXT_LOWER_CACHE.get(key)
    if cached is not None:
        return cached
    ext = os.path.splitext(key)[1].lower()
    if len(_EXT_LOWER_CACHE) >= _EXT_LOWER_CACHE_LIMIT and key not in _EXT_LOWER_CACHE:
        _EXT_LOWER_CACHE.clear()
    _EXT_LOWER_CACHE[key] = ext
    return ext


def is_supported_video_file(name):
    return _lower_ext(name) in FBP_SUPPORTED_VIDEO_EXT


def is_supported_media_file(name):
    return _lower_ext(name) in FBP_SUPPORTED_MEDIA_EXT


def is_hidden_import_name(name):
    """Ignore private/export-helper entries before project scanning.

    Underscore-prefixed folders are intentionally skipped by Frame by Plane.
    Dot-prefixed files also include macOS ``._`` resource forks and common
    hidden project folders, which must never become image layers. Folder scans
    hit this helper for every directory entry, so keep a deterministic cache.
    """
    key = str(name or "")
    cached = _HIDDEN_IMPORT_NAME_CACHE.get(key)
    if cached is not None:
        return bool(cached)
    base = os.path.basename(key)
    return _bounded_cache_set(
        _HIDDEN_IMPORT_NAME_CACHE, key, base.startswith(('_', '.')), _HIDDEN_IMPORT_NAME_CACHE_LIMIT
    )


def is_technical_map_file(name):
    key = str(name or "")
    cached = _TECHNICAL_MAP_CACHE.get(key)
    if cached is not None:
        return bool(cached)
    stem = os.path.splitext(os.path.basename(key))[0].lower()
    result = any(stem.endswith(suffix) for suffix in FBP_TECHNICAL_MAP_SUFFIXES)
    return _bounded_cache_set(_TECHNICAL_MAP_CACHE, key, bool(result), _TECHNICAL_MAP_CACHE_LIMIT)


def clean_layer_name_from_path(path):
    key = str(path or "")
    cached = _CLEAN_LAYER_NAME_CACHE.get(key)
    if cached is not None:
        return cached
    base = os.path.basename(key.rstrip(os.sep))
    stem, ext = os.path.splitext(base)
    result = stem if ext else base
    return _bounded_cache_set(_CLEAN_LAYER_NAME_CACHE, key, result, _CLEAN_LAYER_NAME_CACHE_LIMIT)


def clear_path_runtime_caches():
    """Clear bounded deterministic/UI path caches during reload tests."""
    _UI_FILE_EXISTS_CACHE.clear()
    _NATURAL_SORT_KEY_CACHE.clear()
    _EXT_LOWER_CACHE.clear()
    _HIDDEN_IMPORT_NAME_CACHE.clear()
    _TECHNICAL_MAP_CACHE.clear()
    _CLEAN_LAYER_NAME_CACHE.clear()
    return True
