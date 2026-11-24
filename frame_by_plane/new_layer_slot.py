"""Where a new plane goes: its collection and its depth.

The Layer List shows the layers of a collection sorted by camera depth, so a
plane only lands where the artist expects when both its collection and its
depth are right:

* Inside an entered plane group (double click) the new plane goes into that
  group.
* When the 3D cursor lies between two planes, the new plane goes into the
  innermost collection holding both of them, so it shows between them in the
  Layer List too.
* When the 3D cursor is aligned with a plane, the new plane is placed just in
  front of it (halfway to the next plane in front), instead of overlapping
  it at the same depth, and shows right above it in the Layer List.

Anywhere else the caller's usual collection and the cursor depth are kept.
"""

from __future__ import annotations

from mathutils import Vector

from .runtime import FBP_DATA_ERRORS, fbp_warn


def _depth_frame(context):
    """``(depth_of(location), axis)``: the Layer List depth and its direction."""
    from .layers import fbp_make_depth_context_cache
    from .builder import fbp_scene_orientation_is_horizontal

    cache = fbp_make_depth_context_cache(context)
    if cache.get("has_camera"):
        origin = cache["camera_location"]
        forward = cache["camera_forward"]
        return cache, (lambda location: float((Vector(location) - origin).dot(forward))), forward.copy()
    vertical = not fbp_scene_orientation_is_horizontal(context.scene)
    axis = Vector((0.0, 1.0, 0.0)) if vertical else Vector((0.0, 0.0, 1.0))
    index = 1 if vertical else 2
    return cache, (lambda location: float(Vector(location)[index])), axis


def _layer_collection(rig, scene):
    from .layers import get_primary_fbp_collection
    collection = get_primary_fbp_collection(rig)
    return collection if collection is not None else scene.collection


def _ancestors(collection, scene, parent_map):
    """``collection`` and its parents up to the scene collection."""
    chain = []
    root = scene.collection
    current = collection
    seen = set()
    while current is not None and current != root:
        try:
            key = int(current.as_pointer())
        except FBP_DATA_ERRORS:
            break
        if key in seen or key not in parent_map:
            break
        seen.add(key)
        chain.append(current)
        current = parent_map.get(key)
    chain.append(root)
    return chain


def _common_collection(rig_a, rig_b, scene):
    """The innermost collection holding both layers."""
    from .plane_groups import _parent_map
    parent_map = _parent_map(scene)
    chain_b = _ancestors(_layer_collection(rig_b, scene), scene, parent_map)
    for collection in _ancestors(_layer_collection(rig_a, scene), scene, parent_map):
        if collection in chain_b:
            return collection
    return scene.collection


def _candidate_rigs(scene, group):
    from .layers import is_fbp_layer_object, iter_scene_fbp_rigs
    if group is not None:
        from .plane_groups import group_rigs
        return list(group_rigs(group, scene))
    return [
        rig for rig in iter_scene_fbp_rigs(scene, fallback=True)
        if is_fbp_layer_object(rig) and getattr(rig, "fbp_plane_target", None) is not None
    ]


def fbp_new_layer_slot(context, location=None):
    """Return ``(collection, location)`` for a plane about to be created.

    ``collection`` is ``None`` when the caller's usual collection is right.
    ``location`` is the cursor location, moved along the depth axis only when
    the cursor is aligned with an existing plane.
    """
    scene = getattr(context, "scene", None)
    if location is None:
        location = scene.cursor.location.copy() if scene is not None else Vector()
    location = Vector(location)
    if scene is None:
        return None, location
    try:
        from .plane_groups import entered_group
        group = entered_group(scene)
    except ImportError:
        group = None
    try:
        return _slot(context, scene, group, location)
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not resolve where the new plane goes", exc)
        return group, location


def _slot(context, scene, group, location):
    from .layers import fbp_layer_depth_value_from_cache

    cache, depth_of, axis = _depth_frame(context)
    cursor_depth = depth_of(location)
    if cache.get("has_camera"):
        camera = scene.camera
        clip_start = float(getattr(getattr(camera, "data", None), "clip_start", 0.1) or 0.1)
        if cursor_depth <= clip_start * 1.5:
            # The cursor is behind or at the camera: new planes use the
            # default depth, so the cursor says nothing about the stack.
            return group, location

    stack = []
    for rig in _candidate_rigs(scene, group):
        stack.append((fbp_layer_depth_value_from_cache(rig, cache), rig))
    if not stack:
        return group, location
    stack.sort(key=lambda item: item[0])

    tolerance = max(1.0e-4, abs(cursor_depth) * 1.0e-5)
    aligned = [item for item in stack if abs(item[0] - cursor_depth) <= tolerance]
    target_depth = cursor_depth
    if aligned:
        back_depth, back = aligned[0]
        front = [item for item in stack if item[0] < back_depth - tolerance]
        if front:
            front_depth, front_rig = front[-1]
            target_depth = (front_depth + back_depth) * 0.5
        else:
            front_rig = None
            step = max(tolerance * 10.0, abs(back_depth) * 0.01, 0.05)
            target_depth = back_depth - step
            if cache.get("has_camera") and target_depth <= back_depth * 0.5:
                target_depth = back_depth * 0.5
    else:
        front = [item for item in stack if item[0] < cursor_depth]
        behind = [item for item in stack if item[0] > cursor_depth]
        front_rig = front[-1][1] if front else None
        back = behind[0][1] if behind else None

    collection = group
    if front_rig is not None and back is not None:
        collection = _common_collection(front_rig, back, scene)
        if group is not None and collection == scene.collection:
            collection = group
    location = location + axis * (target_depth - cursor_depth)
    return collection, location


def fbp_adopt_new_layer(context, rig):
    """Parent a new layer to the controller of the group it was created in,
    so moving or fading the group moves and fades it too."""
    if rig is None or getattr(rig, "parent", None) is not None:
        return False
    try:
        from .group_controller import _refresh_layer_opacity, _set_parent_keep_world, group_controller
        from .plane_groups import _parent_map
    except ImportError:
        return False
    scene = context.scene
    try:
        controller = None
        for collection in _ancestors(_layer_collection(rig, scene), scene, _parent_map(scene)):
            controller = group_controller(collection)
            if controller is not None:
                break
        if controller is None:
            return False
        context.view_layer.update()
        _set_parent_keep_world(rig, controller)
        _refresh_layer_opacity([rig])
        return True
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not add the new plane to the group controller", exc)
        return False
