"""Runtime indexes for hot Frame By Plane scene lookups.

This module stays deliberately dependency-light: it must not import UI, builder
or effect modules. Hot paths can ask for FBP rigs and FBP plane meshes without
repeatedly rebuilding the same lists from UI mirrors or full scene scans.
"""

from __future__ import annotations

import time

from .runtime import FBP_DATA_ERRORS, fbp_obj_runtime_key


_SCENE_RIG_CACHE = globals().get("_SCENE_RIG_CACHE", {})
_MESH_PLANE_CACHE = globals().get("_MESH_PLANE_CACHE", {})
_MESH_PLANE_NEGATIVE_CACHE = globals().get("_MESH_PLANE_NEGATIVE_CACHE", {})
_SCENE_PLANE_CACHE = globals().get("_SCENE_PLANE_CACHE", {})
_SCENE_GP_CANVAS_CACHE = globals().get("_SCENE_GP_CANVAS_CACHE", {})
_SCENE_SIGNATURE_CACHE = globals().get("_SCENE_SIGNATURE_CACHE", {})
_MAX_SCENE_CACHE_ENTRIES = 64
_MAX_MESH_CACHE_ENTRIES = 4096
_SCENE_CACHE_TTL_SECONDS = 30.0
_SCENE_NEGATIVE_CACHE_TTL_SECONDS = 1.0
_MESH_CACHE_TTL_SECONDS = 30.0
_SCENE_SIGNATURE_CACHE_TTL_SECONDS = 0.35


def _pointer_key(datablock):
    """Return Blender's stable session identity for ID datablocks.

    ``as_pointer()`` is fast but addresses can be recycled after Undo, reload or
    datablock replacement. Blender 5.2 exposes ``session_uid`` for this exact
    runtime-index use case; the shared helper falls back safely for non-ID RNA.
    """
    try:
        return int(fbp_obj_runtime_key(datablock) or 0)
    except FBP_DATA_ERRORS:
        return 0


def _name_key(datablock):
    try:
        return str(getattr(datablock, "name_full", getattr(datablock, "name", "")) or "")
    except FBP_DATA_ERRORS:
        return ""


def _scene_key(scene):
    if scene is None:
        return (0, "")
    return (_pointer_key(scene), _name_key(scene))


def _scene_signature(scene):
    """Return a cached signature that also detects same-size layer reorders.

    The layer mirror can be queried several times in one UI/depsgraph tick.
    Build the pointer/name tuple once for a tiny time window; structural edits
    already call ``invalidate_scene_index`` and clear this cache immediately.
    """
    try:
        scene_key = _scene_key(scene)
        object_count = len(getattr(scene, "objects", ()) or ())
        layer_count = len(getattr(scene, "fbp_layers", ()) or ())
    except FBP_DATA_ERRORS:
        return (-1, -1, ())
    now = time.monotonic()
    cached = _SCENE_SIGNATURE_CACHE.get(scene_key) if scene_key[0] else None
    if cached is not None:
        try:
            if (
                int(cached.get("object_count", -2)) == object_count
                and int(cached.get("layer_count", -2)) == layer_count
                and now - float(cached.get("checked_at", 0.0) or 0.0) <= _SCENE_SIGNATURE_CACHE_TTL_SECONDS
            ):
                return cached.get("signature", (-1, -1, ()))
        except (TypeError, ValueError):
            pass
    try:
        layer_sig = []
        for item in getattr(scene, "fbp_layers", ()) or ():
            rig = getattr(item, "obj", None)
            layer_sig.append((_pointer_key(rig), _name_key(rig)))
        signature = (object_count, len(layer_sig), tuple(layer_sig))
    except FBP_DATA_ERRORS:
        signature = (-1, -1, ())
    if scene_key[0]:
        if len(_SCENE_SIGNATURE_CACHE) >= _MAX_SCENE_CACHE_ENTRIES and scene_key not in _SCENE_SIGNATURE_CACHE:
            _SCENE_SIGNATURE_CACHE.clear()
        _SCENE_SIGNATURE_CACHE[scene_key] = {
            "object_count": object_count,
            "layer_count": layer_count,
            "checked_at": now,
            "signature": signature,
        }
    return signature


def _mesh_key(mesh):
    if mesh is None:
        return (0, "")
    return (_pointer_key(mesh), _name_key(mesh))


def is_fbp_rig(obj):
    try:
        return bool(obj is not None and getattr(obj, "is_fbp_control", False))
    except FBP_DATA_ERRORS:
        return False


def is_fbp_plane(obj):
    try:
        return bool(obj is not None and getattr(obj, "is_fbp_plane", False))
    except FBP_DATA_ERRORS:
        return False


def _is_gp_canvas_lightweight(obj):
    """Return whether *obj* is an FBP Grease Pencil canvas without imports.

    This intentionally mirrors only the stable ownership tag used by the
    Grease Pencil bridge. Keeping the runtime index dependency-light avoids a
    circular import between scene/UI services and the GP implementation.
    """
    if obj is None:
        return False
    try:
        if not bool(obj.get("fbp_is_gp_canvas", False)):
            return False
        object_type = str(getattr(obj, "type", "") or "").upper()
        if object_type == "GREASEPENCIL":
            return True
        data = getattr(obj, "data", None)
        return bool(data is not None and hasattr(data, "layers") and hasattr(data, "materials"))
    except FBP_DATA_ERRORS:
        return False


def _gp_canvas_kind_lightweight(obj):
    if not _is_gp_canvas_lightweight(obj):
        return ""
    try:
        value = str(obj.get("fbp_gp_canvas_kind", "") or "").upper()
        if value not in {"DRAWING", "MASK"}:
            value = str(getattr(obj, "fbp_gp_canvas_kind", "DRAWING") or "DRAWING").upper()
        return value if value in {"DRAWING", "MASK"} else "DRAWING"
    except FBP_DATA_ERRORS:
        return "DRAWING"


def object_in_scene(obj, scene):
    if obj is None or scene is None:
        return False
    try:
        return getattr(scene, "objects", None).get(str(obj.name)) == obj
    except FBP_DATA_ERRORS:
        return False


def _resolve_cached_names(scene, names):
    resolved = []
    objects = getattr(scene, "objects", None) if scene else None
    if objects is None:
        return ()
    for name in tuple(names or ()):
        try:
            rig = objects.get(str(name))
            if rig is not None and is_fbp_rig(rig):
                resolved.append(rig)
            else:
                return ()
        except FBP_DATA_ERRORS:
            return ()
    return tuple(resolved)


def _cache_scene_rigs(scene_key, signature, rigs, *, complete=False):
    if not scene_key or not scene_key[0]:
        return
    if len(_SCENE_RIG_CACHE) >= _MAX_SCENE_CACHE_ENTRIES and scene_key not in _SCENE_RIG_CACHE:
        _SCENE_RIG_CACHE.clear()
    _SCENE_RIG_CACHE[scene_key] = {
        "signature": signature,
        "checked_at": time.monotonic(),
        "rig_names": tuple(str(getattr(rig, "name", "") or "") for rig in rigs),
        "complete": bool(complete),
    }


def iter_scene_fbp_rigs(scene, *, fallback=False):
    """Yield valid FBP layer rigs for *scene* using a bounded runtime index.

    The synchronized ``scene.fbp_layers`` UI mirror remains the preferred source.
    A full Scene scan is used only before that mirror has been populated or when
    Undo temporarily leaves it empty.
    """
    if scene is None:
        return
    scene_key = _scene_key(scene)
    signature = _scene_signature(scene)
    now = time.monotonic()
    cached = _SCENE_RIG_CACHE.get(scene_key) if scene_key[0] else None
    if cached is not None:
        try:
            names = tuple(cached.get("rig_names", ()) or ())
            ttl = _SCENE_CACHE_TTL_SECONDS if names else _SCENE_NEGATIVE_CACHE_TTL_SECONDS
            if (
                cached.get("signature") == signature
                and now - float(cached.get("checked_at", 0.0) or 0.0) <= ttl
                and (not fallback or bool(cached.get("complete", False)))
            ):
                if names:
                    resolved = _resolve_cached_names(scene, names)
                    if len(resolved) == len(names):
                        for rig in resolved:
                            yield rig
                        return
                else:
                    # Reuse a negative result only if it met the requested
                    # completeness. An empty mirror is not a Scene scan.
                    return
        except FBP_DATA_ERRORS:
            pass

    seen = set()
    rigs = []
    try:
        for item in getattr(scene, "fbp_layers", ()) or ():
            rig = getattr(item, "obj", None)
            if not is_fbp_rig(rig) or not object_in_scene(rig, scene):
                continue
            key = _pointer_key(rig) or str(getattr(rig, "name", "") or "")
            if key in seen:
                continue
            seen.add(key)
            rigs.append(rig)
    except FBP_DATA_ERRORS:
        rigs = []

    scan_complete = False
    if fallback:
        # Repair/load fallback: Undo or a just-completed rename can
        # leave one or more transient mirror rows stale while other rows are
        # still valid. Explicit recovery callers need a complete Scene result,
        # not only the valid subset returned by the mirror.
        try:
            for rig in tuple(getattr(scene, "objects", ()) or ()):  # scene-local only
                if not is_fbp_rig(rig):
                    continue
                key = _pointer_key(rig) or str(getattr(rig, "name", "") or "")
                if key in seen:
                    continue
                seen.add(key)
                rigs.append(rig)
            scan_complete = True
        except FBP_DATA_ERRORS:
            pass

    _cache_scene_rigs(scene_key, signature, rigs, complete=scan_complete)
    for rig in rigs:
        yield rig


def _cache_scene_planes(scene_key, signature, planes, *, complete=False):
    if not scene_key or not scene_key[0]:
        return
    if len(_SCENE_PLANE_CACHE) >= _MAX_SCENE_CACHE_ENTRIES and scene_key not in _SCENE_PLANE_CACHE:
        _SCENE_PLANE_CACHE.clear()
    _SCENE_PLANE_CACHE[scene_key] = {
        "signature": signature,
        "checked_at": time.monotonic(),
        "plane_names": tuple(str(getattr(plane, "name", "") or "") for plane in planes),
        "complete": bool(complete),
    }


def _resolve_cached_planes(scene, names):
    resolved = []
    objects = getattr(scene, "objects", None) if scene else None
    if objects is None:
        return ()
    for name in tuple(names or ()):
        try:
            plane = objects.get(str(name))
            if plane is not None and is_fbp_plane(plane):
                resolved.append(plane)
            else:
                return ()
        except FBP_DATA_ERRORS:
            return ()
    return tuple(resolved)


def iter_scene_fbp_planes(scene, *, fallback=False):
    """Yield FBP-owned layer planes for *scene* using the runtime index."""
    if scene is None:
        return
    scene_key = _scene_key(scene)
    signature = _scene_signature(scene)
    now = time.monotonic()
    cached = _SCENE_PLANE_CACHE.get(scene_key) if scene_key[0] else None
    if cached is not None:
        try:
            names = tuple(cached.get("plane_names", ()) or ())
            ttl = _SCENE_CACHE_TTL_SECONDS if names else _SCENE_NEGATIVE_CACHE_TTL_SECONDS
            if (
                cached.get("signature") == signature
                and now - float(cached.get("checked_at", 0.0) or 0.0) <= ttl
                and (not fallback or bool(cached.get("complete", False)))
            ):
                resolved = _resolve_cached_planes(scene, names)
                if len(resolved) == len(names):
                    for plane in resolved:
                        yield plane
                    return
        except FBP_DATA_ERRORS:
            pass

    seen = set()
    planes = []
    try:
        for rig in iter_scene_fbp_rigs(scene, fallback=fallback):
            plane = getattr(rig, "fbp_plane_target", None)
            if not is_fbp_plane(plane) or not object_in_scene(plane, scene):
                continue
            key = _pointer_key(plane) or str(getattr(plane, "name", "") or "")
            if key in seen:
                continue
            seen.add(key)
            planes.append(plane)
    except FBP_DATA_ERRORS:
        planes = []

    scan_complete = False
    if fallback:
        # A partly restored rig mirror can contain some, but not all planes.
        # Merge every scene-owned plane before marking this cache complete.
        try:
            for plane in tuple(getattr(scene, "objects", ()) or ()):  # scene-local only
                if not is_fbp_plane(plane) or not object_in_scene(plane, scene):
                    continue
                key = _pointer_key(plane) or str(getattr(plane, "name", "") or "")
                if key in seen:
                    continue
                seen.add(key)
                planes.append(plane)
            scan_complete = True
        except FBP_DATA_ERRORS:
            pass

    _cache_scene_planes(scene_key, signature, planes, complete=scan_complete)
    for plane in planes:
        yield plane


def _cache_scene_gp_canvases(scene_key, signature, canvases):
    if not scene_key or not scene_key[0]:
        return
    if len(_SCENE_GP_CANVAS_CACHE) >= _MAX_SCENE_CACHE_ENTRIES and scene_key not in _SCENE_GP_CANVAS_CACHE:
        _SCENE_GP_CANVAS_CACHE.clear()
    checked_at = time.monotonic()
    # A full scene scan proves both the positive and negative state of each
    # canvas kind.  Keep primitive timestamps so an absent DRAWING panel does
    # not trigger another scene.objects walk on every UI redraw while MASK
    # canvases exist.
    _SCENE_GP_CANVAS_CACHE[scene_key] = {
        "signature": signature,
        "checked_at": checked_at,
        "kind_checked_at": {
            "DRAWING": checked_at,
            "MASK": checked_at,
        },
        "canvas_names": tuple(str(getattr(canvas, "name", "") or "") for canvas in canvases),
    }


def _resolve_cached_gp_canvases(scene, names):
    resolved = []
    objects = getattr(scene, "objects", None) if scene else None
    if objects is None:
        return ()
    for name in tuple(names or ()):
        try:
            canvas = objects.get(str(name))
            if canvas is not None and _is_gp_canvas_lightweight(canvas):
                resolved.append(canvas)
            else:
                return ()
        except FBP_DATA_ERRORS:
            return ()
    return tuple(resolved)


def iter_scene_gp_canvases(scene, *, kind="", fallback=True):
    """Yield tagged FBP Grease Pencil canvases through a bounded scene index.

    ``kind`` may be ``DRAWING`` or ``MASK``. The cache stores names only, so it
    never retains stale RNA wrappers across Undo or file loading.
    """
    if scene is None:
        return
    requested_kind = str(kind or "").upper()
    if requested_kind not in {"", "DRAWING", "MASK"}:
        requested_kind = ""
    scene_key = _scene_key(scene)
    signature = _scene_signature(scene)
    now = time.monotonic()
    cached = _SCENE_GP_CANVAS_CACHE.get(scene_key) if scene_key[0] else None
    canvases = ()
    cache_valid = False
    if cached is not None:
        try:
            names = tuple(cached.get("canvas_names", ()) or ())
            ttl = _SCENE_CACHE_TTL_SECONDS if names else _SCENE_NEGATIVE_CACHE_TTL_SECONDS
            if (
                cached.get("signature") == signature
                and now - float(cached.get("checked_at", 0.0) or 0.0) <= ttl
            ):
                canvases = _resolve_cached_gp_canvases(scene, names)
                cache_valid = len(canvases) == len(names)
        except FBP_DATA_ERRORS:
            canvases = ()
            cache_valid = False
    # A valid cache may contain only MASK canvases while an existing object is
    # newly promoted to DRAWING without changing Scene object counts. In that
    # case the generic Scene signature remains unchanged and the requested panel
    # could stay hidden until the long positive-cache TTL expires. Re-scan only
    # when the requested kind is absent from an otherwise valid cache; common
    # hits remain allocation-free and cached.
    requested_kind_missing = False
    if cache_valid and requested_kind:
        kind_present = any(
            _gp_canvas_kind_lightweight(canvas) == requested_kind
            for canvas in canvases
        )
        if not kind_present:
            try:
                kind_checked_at = float(
                    (cached.get("kind_checked_at", {}) or {}).get(requested_kind, 0.0) or 0.0
                )
            except (AttributeError, TypeError, ValueError):
                kind_checked_at = 0.0
            requested_kind_missing = (
                not kind_checked_at
                or now - kind_checked_at > _SCENE_NEGATIVE_CACHE_TTL_SECONDS
            )
    if (not cache_valid and (fallback or cached is None)) or requested_kind_missing:
        found = []
        seen = set()
        try:
            for candidate in tuple(getattr(scene, "objects", ()) or ()):
                if not _is_gp_canvas_lightweight(candidate):
                    continue
                key = _pointer_key(candidate) or str(getattr(candidate, "name", "") or "")
                if key in seen:
                    continue
                seen.add(key)
                found.append(candidate)
        except FBP_DATA_ERRORS:
            found = []
        canvases = tuple(found)
        _cache_scene_gp_canvases(scene_key, signature, canvases)
    for canvas in canvases:
        if requested_kind and _gp_canvas_kind_lightweight(canvas) != requested_kind:
            continue
        yield canvas


def scene_has_gp_canvas(scene, *, kind=""):
    try:
        return next(iter_scene_gp_canvases(scene, kind=kind, fallback=True), None) is not None
    except (ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def is_scene_fbp_plane_mesh(scene, mesh):
    """Return whether *mesh* belongs to an FBP plane in *scene*.

    Depsgraph Mesh updates are very noisy in complex files. This helper avoids
    repeatedly walking ``scene.objects`` for unrelated meshes while still falling
    back to a real ownership check when the answer is not cached.
    """
    if scene is None or mesh is None:
        return False
    scene_key = _scene_key(scene)
    mesh_key = _mesh_key(mesh)
    if not scene_key[0] or not mesh_key[0]:
        return False
    cache_key = (scene_key, mesh_key)
    now = time.monotonic()

    try:
        if bool(mesh.get("fbp_plane_mesh", False)):
            if len(_MESH_PLANE_CACHE) >= _MAX_MESH_CACHE_ENTRIES and cache_key not in _MESH_PLANE_CACHE:
                _MESH_PLANE_CACHE.clear()
            _MESH_PLANE_CACHE[cache_key] = now
            _MESH_PLANE_NEGATIVE_CACHE.pop(cache_key, None)
            return True
    except FBP_DATA_ERRORS:
        pass

    checked_at = float(_MESH_PLANE_CACHE.get(cache_key, 0.0) or 0.0)
    if checked_at and now - checked_at <= _MESH_CACHE_TTL_SECONDS:
        return True

    negative_checked_at = float(_MESH_PLANE_NEGATIVE_CACHE.get(cache_key, 0.0) or 0.0)
    if negative_checked_at and now - negative_checked_at <= _MESH_CACHE_TTL_SECONDS:
        return False

    # Aggressive branch: do not walk scene.objects from depsgraph mesh updates.
    # New/current FBP planes tag their Mesh datablock at creation/sync time.
    if len(_MESH_PLANE_NEGATIVE_CACHE) >= _MAX_MESH_CACHE_ENTRIES and cache_key not in _MESH_PLANE_NEGATIVE_CACHE:
        _MESH_PLANE_NEGATIVE_CACHE.clear()
    _MESH_PLANE_NEGATIVE_CACHE[cache_key] = now
    return False


def invalidate_scene_index(scene=None):
    """Clear cached rig and mesh ownership lists after structural edits."""
    if scene is None:
        _SCENE_RIG_CACHE.clear()
        _SCENE_PLANE_CACHE.clear()
        _SCENE_GP_CANVAS_CACHE.clear()
        _SCENE_SIGNATURE_CACHE.clear()
        _MESH_PLANE_CACHE.clear()
        _MESH_PLANE_NEGATIVE_CACHE.clear()
        return True
    key = _scene_key(scene)
    if key[0]:
        _SCENE_RIG_CACHE.pop(key, None)
        _SCENE_PLANE_CACHE.pop(key, None)
        _SCENE_GP_CANVAS_CACHE.pop(key, None)
        _SCENE_SIGNATURE_CACHE.pop(key, None)
        for cache in (_MESH_PLANE_CACHE, _MESH_PLANE_NEGATIVE_CACHE):
            for cache_key in tuple(cache.keys()):
                try:
                    if cache_key[0] == key:
                        cache.pop(cache_key, None)
                except FBP_DATA_ERRORS:
                    cache.pop(cache_key, None)
    return True


def register():
    invalidate_scene_index()


def unregister():
    invalidate_scene_index()
