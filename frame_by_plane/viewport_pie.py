"""Native Blender Frame By Plane viewport radial menu."""

import time

import bpy
from bpy.app.handlers import persistent
from bpy.props import EnumProperty, IntProperty, StringProperty
from bpy.types import Menu, Operator

from .managed_timers import fbp_register_timer_once, fbp_unregister_managed_timer
from .runtime import (
    fbp_warn, FBP_DATA_ERRORS, FBP_DATA_IO_ERRORS,
    fbp_render_mutation_blocked, fbp_undo_guard_active,
    fbp_depsgraph_quiet_for,
)
from .registration import (
    append_handler_once,
    register_classes,
    remove_handlers_by_name,
    unregister_classes,
)
from .shortcut_runtime import (
    addon_keymap,
    refresh_keymap_registration,
    remove_matching_keymap_items,
    shortcut_enabled,
    unregister_keymap_items,
)
from .ui_style import configure_layout, hint_row, section_gap, section_header
from .ui_icons import effect_enum_icon, effect_icon_kwargs, ui_icon_kwargs


_FBP_VIEWPORT_PIE_KEYMAPS = globals().get("_FBP_VIEWPORT_PIE_KEYMAPS", [])
_QUICK_EFFECT_PREF_NAMES = tuple(f"pie_quick_effect_{index}" for index in range(1, 6))
_QUICK_MASK_PREF_NAMES = tuple(f"pie_quick_mask_{index}" for index in range(1, 6))
_QUICK_MASK_DEFAULTS = (
    "SHAPE_MASK",
    "GREASE_PENCIL_MASK",
    "COLOR_MASK",
    "",
    "",
)
_QUICK_EFFECT_FALLBACK = (
    ('NONE', "Empty Slot", "Do not show an effect in this quick slot", 'ADD', 0),
)
_QUICK_EFFECT_ENUM_CACHE = globals().get("_QUICK_EFFECT_ENUM_CACHE", {})
if not isinstance(_QUICK_EFFECT_ENUM_CACHE, dict):
    _QUICK_EFFECT_ENUM_CACHE = {}
_QUICK_EFFECT_ENUM_SIGNATURE = globals().get("_QUICK_EFFECT_ENUM_SIGNATURE", {})
if not isinstance(_QUICK_EFFECT_ENUM_SIGNATURE, dict):
    _QUICK_EFFECT_ENUM_SIGNATURE = {}
_QUICK_EFFECT_ENUM_REFRESH_TIME = float(globals().get("_QUICK_EFFECT_ENUM_REFRESH_TIME", 0.0) or 0.0)
_QUICK_EFFECT_ENUM_REFRESH_SECONDS = 2.0
_QUICK_MASK_ENUM_CACHE = globals().get("_QUICK_MASK_ENUM_CACHE", [])
_QUICK_MASK_ENUM_SIGNATURE = globals().get("_QUICK_MASK_ENUM_SIGNATURE", None)
_FBP_LAST_LOCKED_RIG_NAMES = globals().get("_FBP_LAST_LOCKED_RIG_NAMES", [])
_FBP_LAST_SELECTABILITY_NAMES = globals().get("_FBP_LAST_SELECTABILITY_NAMES", [])
_FBP_LAST_HIDDEN_OBJECT_NAMES = globals().get("_FBP_LAST_HIDDEN_OBJECT_NAMES", [])
_PIE_ICON_SCALE_X = 1.25
_PIE_ICON_SCALE_Y = 1.25
_PIE_BUTTON_SCALE_Y = 1.25
_PIE_BRANCH_GAP_FACTOR = 0.6
_PIE_OVERFLOW_UI_UNITS = 5.5
_PIE_OVERFLOW_SCALE_X = 4.25
_PIE_SOUTH_LIST_UI_UNITS = 9.0
_PIE_SOUTH_LIST_ROWS = 8
_PIE_SOUTH_TOP_PAD_ROWS = 6
_PIE_SOUTH_SCALE_Y = 1.0


def _pie_text_width(label, *, minimum=5.5, maximum=12.5):
    """Return a compact native Blender UI width for one Pie button."""
    text = str(label or "")
    return max(float(minimum), min(float(maximum), 2.05 + len(text) * 0.32))


def _pie_icon_cell(layout, *, enabled=True):
    cell = layout.row(align=True)
    cell.scale_x = _PIE_ICON_SCALE_X
    cell.scale_y = _PIE_ICON_SCALE_Y
    cell.enabled = bool(enabled)
    return cell


def _pie_fixed_button_row(layout, label, *, enabled=True):
    wrapper = layout.row(align=False)
    wrapper.alignment = "CENTER"
    button = wrapper.row(align=False)
    button.alignment = "CENTER"
    button.ui_units_x = _pie_text_width(
        label,
        minimum=6.0,
        maximum=_PIE_SOUTH_LIST_UI_UNITS,
    )
    button.scale_y = _PIE_BUTTON_SCALE_Y
    button.enabled = bool(enabled)
    return button


def _pie_pad_south_list(layout, used_rows):
    """Keep the two south branches top-aligned while content grows downward."""
    for _index in range(max(0, _PIE_SOUTH_LIST_ROWS - int(used_rows or 0))):
        spacer = layout.row(align=False)
        # Real action/icon rows use the native 1.25 control height. Matching
        # that height here keeps the branch footprint identical when a spacer
        # is replaced by a configured quick effect.
        spacer.scale_y = _PIE_BUTTON_SCALE_Y
        spacer.label(text="")


def _pie_start_south_list(layout, title, icon):
    """Lower a fixed-height south list without changing its growth direction.

    Pie sectors are vertically centred by Blender. Tail padding alone therefore
    pins the visible title too close to the radial centre. A matching fixed
    spacer before both lists moves their visible top down while the constant
    content-plus-tail footprint still makes entries grow only downward.
    """
    # Six leading rows keep the visible content below the radial controls.
    # Blender centres the complete pie sector, so every two fixed spacers move
    # the visible top by roughly one native row. Compacting the
    # entire fixed-height branch keeps the maximum eight-row configuration
    # inside the viewport without changing the alignment between both sides.
    layout.scale_y = _PIE_SOUTH_SCALE_Y
    for _index in range(_PIE_SOUTH_TOP_PAD_ROWS):
        spacer = layout.row(align=False)
        spacer.label(text="")
    title_row = layout.row(align=True)
    title_row.alignment = "CENTER"
    title_row.label(text=str(title or ""), icon=str(icon or "NONE"))
    return title_row


def _pie_mask_label(label):
    """Remove the redundant Mask suffix inside the titled Masks sector."""
    value = str(label or "").strip()
    if value.casefold().endswith(" mask"):
        value = value[:-5].rstrip()
    return value


_CURSOR_ON_CAMERA_ENABLED_KEY = "fbp_cursor_on_camera_enabled"
_CURSOR_ON_CAMERA_LAST_CURSOR_KEY = "fbp_cursor_on_camera_last_cursor"
_CURSOR_ON_CAMERA_CAMERA_KEY = "fbp_cursor_on_camera_camera_pointer"
_CURSOR_ON_CAMERA_EPSILON = 1.0e-6
_CURSOR_ON_CAMERA_TIMER_INTERVAL = 0.12


def _vector_triplet(value):
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except (AttributeError, IndexError, TypeError, ValueError):
        return (0.0, 0.0, 0.0)


def _triplet_distance_sq(a, b):
    ax, ay, az = _vector_triplet(a)
    bx, by, bz = _vector_triplet(b)
    return (ax - bx) ** 2 + (ay - by) ** 2 + (az - bz) ** 2


def _cursor_on_camera_is_enabled(scene):
    try:
        return bool(scene.get(_CURSOR_ON_CAMERA_ENABLED_KEY, False))
    except FBP_DATA_ERRORS:
        return False


def _cursor_on_camera_set_enabled(scene, enabled):
    if scene is None:
        return False
    try:
        scene[_CURSOR_ON_CAMERA_ENABLED_KEY] = bool(enabled)
        if not enabled:
            scene.pop(_CURSOR_ON_CAMERA_LAST_CURSOR_KEY, None)
            scene.pop(_CURSOR_ON_CAMERA_CAMERA_KEY, None)
        return True
    except FBP_DATA_ERRORS:
        return False


def _active_camera_location(scene):
    camera = getattr(scene, "camera", None)
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        return None, None
    try:
        return camera, camera.matrix_world.translation.copy()
    except FBP_DATA_ERRORS:
        return camera, None


def _cursor_on_camera_pointer_token(camera):
    """Return a stable IDProperty-safe token for the active camera.

    RNA pointers are pointer-sized integers. On Windows 64-bit they can exceed
    Blender IDProperty's C-int storage range when assigned as plain ints to a
    Scene custom property. Store them as strings to avoid OverflowError while
    still keeping a useful debug/repair token.
    """
    if camera is None:
        return ""
    try:
        return str(int(camera.as_pointer()))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OverflowError):
        return str(getattr(camera, "name", "") or "")


def _write_cursor_on_camera_state(scene, camera, location):
    try:
        scene.cursor.location = location
        scene[_CURSOR_ON_CAMERA_LAST_CURSOR_KEY] = list(_vector_triplet(location))
        scene[_CURSOR_ON_CAMERA_CAMERA_KEY] = _cursor_on_camera_pointer_token(camera)
        return True
    except FBP_DATA_ERRORS + (OverflowError,):
        return False


def _sync_cursor_on_camera_scene(scene, *, force=False):
    """Keep Scene.cursor locked to the active camera until the user moves it.

    Blender does not expose a dedicated 3D-cursor moved callback. A lightweight
    timer polls only while the feature is enabled. If the current cursor no
    longer matches the last position written by Frame By Plane, the user has
    moved it manually and the link is disabled immediately.
    """
    if scene is None or not _cursor_on_camera_is_enabled(scene):
        return False
    camera, target = _active_camera_location(scene)
    if camera is None or target is None:
        _cursor_on_camera_set_enabled(scene, False)
        return False
    try:
        cursor_location = scene.cursor.location.copy()
    except FBP_DATA_ERRORS:
        _cursor_on_camera_set_enabled(scene, False)
        return False
    try:
        last_cursor = scene.get(_CURSOR_ON_CAMERA_LAST_CURSOR_KEY, None)
    except FBP_DATA_ERRORS:
        last_cursor = None
    if last_cursor is not None and _triplet_distance_sq(cursor_location, last_cursor) > _CURSOR_ON_CAMERA_EPSILON:
        _cursor_on_camera_set_enabled(scene, False)
        return False
    if force or last_cursor is None or _triplet_distance_sq(target, last_cursor) > _CURSOR_ON_CAMERA_EPSILON:
        return _write_cursor_on_camera_state(scene, camera, target)
    return True


def _cursor_on_camera_any_enabled():
    try:
        return any(_cursor_on_camera_is_enabled(scene) for scene in bpy.data.scenes)
    except FBP_DATA_ERRORS:
        return False


def _cursor_on_camera_timer():
    if fbp_undo_guard_active() or fbp_render_mutation_blocked():
        return _CURSOR_ON_CAMERA_TIMER_INTERVAL if _cursor_on_camera_any_enabled() else None
    if not fbp_depsgraph_quiet_for(0.12):
        return _CURSOR_ON_CAMERA_TIMER_INTERVAL if _cursor_on_camera_any_enabled() else None
    any_enabled = False
    try:
        scenes = tuple(bpy.data.scenes)
    except FBP_DATA_ERRORS:
        scenes = ()
    for scene in scenes:
        if _cursor_on_camera_is_enabled(scene):
            any_enabled = True
            _sync_cursor_on_camera_scene(scene)
    return _CURSOR_ON_CAMERA_TIMER_INTERVAL if any_enabled else None


def _ensure_cursor_on_camera_timer():
    try:
        fbp_register_timer_once(
            _cursor_on_camera_timer, 0.05, persistent=True
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


@persistent
def _cursor_on_camera_frame_handler(scene, *args):
    del args
    if fbp_undo_guard_active() or fbp_render_mutation_blocked():
        return
    if _cursor_on_camera_is_enabled(scene):
        _ensure_cursor_on_camera_timer()


def _register_cursor_on_camera_runtime():
    if not append_handler_once(
        bpy.app.handlers.frame_change_post,
        _cursor_on_camera_frame_handler,
        module_suffix="viewport_pie",
    ):
        raise RuntimeError("Could not register the Cursor on Camera frame handler")
    if _cursor_on_camera_any_enabled():
        _ensure_cursor_on_camera_timer()


def _unregister_cursor_on_camera_runtime():
    remove_handlers_by_name(
        bpy.app.handlers.frame_change_post,
        "_cursor_on_camera_frame_handler",
        module_suffix="viewport_pie",
    )
    try:
        fbp_unregister_managed_timer(_cursor_on_camera_timer)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


def _view3d_space(context):
    space = getattr(context, "space_data", None)
    return space if getattr(space, "type", None) == 'VIEW_3D' else None


def _selected_fbp_rigs(context):
    try:
        from .layers import get_selected_fbp_roots
        return list(get_selected_fbp_roots(context))
    except FBP_DATA_ERRORS:
        return []


def _object_is_explicitly_selected(context, obj):
    """Reject Blender's stale active object after Select None."""
    if obj is None:
        return False
    selected = tuple(getattr(context, "selected_objects", ()) or ())
    if obj not in selected:
        return False
    try:
        return bool(obj.select_get())
    except FBP_DATA_ERRORS:
        return True


def _active_gp_drawing_canvas(context):
    """Return the selected FBP Grease Pencil drawing canvas, if any.

    Grease Pencil canvases can resolve back to their owner rig.  The Pie Menu
    must nevertheless treat the canvas as the active artistic target so image
    masks/effects are not offered against its owner by accident.
    """
    canvas = getattr(context, "active_object", None)
    if canvas is None:
        canvas = getattr(context, "object", None)
    if not _object_is_explicitly_selected(context, canvas):
        return None
    if str(getattr(canvas, "type", "") or "").upper() != "GREASEPENCIL":
        return None
    try:
        from .grease_pencil_bridge import is_gp_drawing_canvas
        return canvas if is_gp_drawing_canvas(canvas) else None
    except FBP_DATA_ERRORS:
        return None


def _resolve_fbp_rig(obj, context=None):
    try:
        from .layers import fbp_resolve_rig_from_any_object
        return fbp_resolve_rig_from_any_object(obj, context)
    except FBP_DATA_ERRORS:
        return None


def _object_runtime_key(obj):
    """Return a cheap process-local identity for one Blender object wrapper."""
    try:
        return int(obj.as_pointer())
    except FBP_DATA_ERRORS:
        return id(obj)


def _append_unique_object(items, keys, obj):
    if obj is None:
        return False
    key = _object_runtime_key(obj)
    if key in keys:
        return False
    keys.add(key)
    items.append(obj)
    return True


def _rig_related_objects(rigs):
    """Collect each rig hierarchy once and return (all objects, image planes)."""
    objects = []
    planes = []
    object_keys = set()
    plane_keys = set()

    for rig in rigs:
        _append_unique_object(objects, object_keys, rig)
        try:
            plane = getattr(rig, "fbp_plane_target", None)
            if plane is not None:
                _append_unique_object(objects, object_keys, plane)
                _append_unique_object(planes, plane_keys, plane)

            descendants = tuple(getattr(rig, "children_recursive", ()) or ())
            if not descendants:
                descendants = tuple(getattr(rig, "children", ()) or ())
            for child in descendants:
                _append_unique_object(objects, object_keys, child)
                if (
                    getattr(child, "type", None) == 'MESH'
                    and (
                        bool(getattr(child, "is_fbp_plane", False))
                        or getattr(child, "parent", None) == rig
                    )
                ):
                    _append_unique_object(planes, plane_keys, child)
        except FBP_DATA_IO_ERRORS:
            continue
    return objects, planes


def _fbp_objects_for_rigs(rigs):
    return _rig_related_objects(rigs)[0]


def _selected_generic_objects(context):
    objects = []
    keys = set()
    for obj in tuple(getattr(context, "selected_objects", ()) or ()):
        if obj is None or _resolve_fbp_rig(obj, context) is not None:
            continue
        _append_unique_object(objects, keys, obj)
    return objects


def _object_hidden_in_view(obj):
    try:
        return bool(obj.hide_get())
    except FBP_DATA_IO_ERRORS:
        return bool(getattr(obj, "hide_viewport", False))


def _selected_hide_targets(
    context,
    *,
    rigs=None,
    generic=None,
    related_objects=None,
):
    rigs = _selected_fbp_rigs(context) if rigs is None else rigs
    generic = _selected_generic_objects(context) if generic is None else generic
    if related_objects is None:
        related_objects = _fbp_objects_for_rigs(rigs)

    targets = []
    keys = set()
    for obj in related_objects:
        _append_unique_object(targets, keys, obj)
    for obj in generic:
        _append_unique_object(targets, keys, obj)
    if targets:
        return targets
    return _objects_from_names(_FBP_LAST_HIDDEN_OBJECT_NAMES, context)


def _object_transform_locked(obj):
    try:
        return bool(
            all(bool(value) for value in obj.lock_location)
            and all(bool(value) for value in obj.lock_rotation)
            and all(bool(value) for value in obj.lock_scale)
        )
    except FBP_DATA_IO_ERRORS:
        return False


def _objects_from_names(names, context):
    objects = []
    keys = set()
    view_objects = getattr(getattr(context, "view_layer", None), "objects", None)
    for name in tuple(names):
        try:
            name = str(name or "")
            if not name:
                continue
            obj = bpy.data.objects.get(name)
            if obj is None:
                continue
            if view_objects is not None and obj.name not in view_objects:
                continue
            _append_unique_object(objects, keys, obj)
        except FBP_DATA_IO_ERRORS:
            continue
    return objects


def _selected_lock_targets(context):
    rigs = _selected_fbp_rigs(context)
    generic = _selected_generic_objects(context)
    last_rigs = [
        obj for obj in _objects_from_names(_FBP_LAST_LOCKED_RIG_NAMES, context)
        if bool(getattr(obj, "is_fbp_control", False))
        and bool(getattr(obj, "hide_select", False))
    ]
    for rig in last_rigs:
        if rig not in rigs:
            rigs.append(rig)
    return rigs, generic


def _selected_selectability_targets(context):
    rigs = _selected_fbp_rigs(context)
    _related, planes = _rig_related_objects(rigs)
    generic = _selected_generic_objects(context)
    last_generic = [
        obj for obj in _objects_from_names(_FBP_LAST_SELECTABILITY_NAMES, context)
        if bool(getattr(obj, "hide_select", False))
    ]
    for obj in last_generic:
        if obj not in generic:
            generic.append(obj)
    return rigs, planes, generic


def _generic_holdout_objects(context):
    return [
        obj for obj in _selected_generic_objects(context)
        if hasattr(obj, "is_holdout")
    ]


def _toggleable_fbp_holdout_rigs(context):
    rigs = _selected_fbp_rigs(context)
    try:
        from .materials import fbp_is_native_holdout_plane
        return [rig for rig in rigs if not fbp_is_native_holdout_plane(rig)]
    except FBP_DATA_ERRORS:
        return rigs


def _rig_holdout_state(rig):
    try:
        from .materials import fbp_is_native_holdout_plane, rig_holdout_is_active
        return bool(fbp_is_native_holdout_plane(rig) or rig_holdout_is_active(rig))
    except FBP_DATA_ERRORS:
        return False


def _pie_selection_state(context):
    """Build the complete Pie state with one selected-rig hierarchy scan."""
    rigs = _selected_fbp_rigs(context)
    generic = _selected_generic_objects(context)
    related_objects, planes = _rig_related_objects(rigs)

    lock_rigs = list(rigs)
    for rig in _objects_from_names(_FBP_LAST_LOCKED_RIG_NAMES, context):
        if (
            bool(getattr(rig, "is_fbp_control", False))
            and bool(getattr(rig, "hide_select", False))
            and rig not in lock_rigs
        ):
            lock_rigs.append(rig)
    lock_states = [bool(getattr(rig, "hide_select", False)) for rig in lock_rigs]
    lock_states.extend(_object_transform_locked(obj) for obj in generic)

    selectable_generic = list(generic)
    selectable_keys = {_object_runtime_key(obj) for obj in selectable_generic}
    for obj in _objects_from_names(_FBP_LAST_SELECTABILITY_NAMES, context):
        if bool(getattr(obj, "hide_select", False)):
            _append_unique_object(selectable_generic, selectable_keys, obj)
    selectability_states = [bool(getattr(plane, "hide_select", False)) for plane in planes]
    selectability_states.extend(
        bool(getattr(obj, "hide_select", False)) for obj in selectable_generic
    )

    generic_holdout = [obj for obj in generic if hasattr(obj, "is_holdout")]
    holdout_rigs = []
    holdout_states = []
    try:
        from .materials import fbp_is_native_holdout_plane, rig_holdout_is_active

        for rig in rigs:
            is_native = bool(fbp_is_native_holdout_plane(rig))
            if not is_native:
                holdout_rigs.append(rig)
            holdout_states.append(is_native or bool(rig_holdout_is_active(rig)))
    except FBP_DATA_ERRORS:
        holdout_rigs = list(rigs)
        holdout_states = [False for _rig in rigs]
    holdout_states.extend(bool(getattr(obj, "is_holdout", False)) for obj in generic_holdout)

    hide_targets = _selected_hide_targets(
        context,
        rigs=rigs,
        generic=generic,
        related_objects=related_objects,
    )
    hide_states = [_object_hidden_in_view(obj) for obj in hide_targets]

    return {
        "rigs": rigs,
        "generic": generic,
        "hide_targets": hide_targets,
        "hide_enabled": bool(hide_targets),
        "hide_active": bool(hide_states) and all(hide_states),
        "lock_rigs": lock_rigs,
        "lock_enabled": bool(lock_rigs or generic),
        "lock_active": bool(lock_states) and all(lock_states),
        "planes": planes,
        "selectable_generic": selectable_generic,
        "selectability_enabled": bool(planes or selectable_generic),
        "selectability_locked": bool(selectability_states) and all(selectability_states),
        "selectability_active": (
            bool(selectability_states)
            and all(not state for state in selectability_states)
        ),
        "holdout_rigs": holdout_rigs,
        "generic_holdout": generic_holdout,
        "holdout_enabled": bool(holdout_rigs or generic_holdout),
        "holdout_active": bool(holdout_states) and all(holdout_states),
    }


def _addon_preferences(context=None):
    try:
        from .interface_preferences import fbp_get_addon_preferences
        return fbp_get_addon_preferences(context)
    except FBP_DATA_ERRORS:
        return None


def _curated_quick_effect_rows(category):
    """Return one category in the add-menu's curated section order."""
    from .effects_registry import (
        FBP_EFFECT_CROP,
        FBP_EFFECT_EXTEND,
        FBP_EFFECT_REGISTRY,
        FBP_IMAGE_EFFECT_MENU_SECTIONS,
        FBP_MESH_EFFECT_MENU_SECTIONS,
        fbp_effect_family_definition,
        fbp_refresh_custom_effect_registry,
    )

    category = str(category or "2D").upper()
    fbp_refresh_custom_effect_registry(force=False)
    sections = (
        FBP_MESH_EFFECT_MENU_SECTIONS
        if category == "3D"
        else FBP_IMAGE_EFFECT_MENU_SECTIONS
    )
    rows = []
    seen = set()

    def append_effect(section_label, effect_id):
        effect_id = str(effect_id or "")
        definition = FBP_EFFECT_REGISTRY.get(effect_id, {}) or {}
        actual_category = str(definition.get("category", "2D") or "2D").upper()
        normalized_category = "2D" if actual_category == "BASE" else actual_category
        if (
            not effect_id
            or effect_id in seen
            or effect_id in {FBP_EFFECT_CROP, FBP_EFFECT_EXTEND}
            or normalized_category != category
            or bool(definition.get("custom_invalid", False))
            or bool(definition.get("custom_hidden", False))
        ):
            return
        seen.add(effect_id)
        label = str(definition.get("label", effect_id) or effect_id)
        icon = str(definition.get("icon", "SHADERFX") or "SHADERFX")
        rows.append((section_label, effect_id, label, icon))

    for section_label, _section_icon, tokens in sections:
        for token in tokens:
            token = str(token or "")
            if token.startswith("FAMILY:"):
                family = fbp_effect_family_definition(token.split(":", 1)[1])
                for effect_id, _variant_label in tuple(family.get("variants", ()) or ()):
                    append_effect(section_label, effect_id)
            else:
                append_effect(section_label, token)

    # User effects and future registry additions remain available after the
    # built-in sections instead of being lost when the curated menu evolves.
    tail = []
    for effect_id, definition in FBP_EFFECT_REGISTRY.items():
        actual_category = str(definition.get("category", "2D") or "2D").upper()
        normalized_category = "2D" if actual_category == "BASE" else actual_category
        if effect_id in seen or normalized_category != category:
            continue
        if bool(definition.get("custom_invalid", False)) or bool(definition.get("custom_hidden", False)):
            continue
        tail.append((str(definition.get("label", effect_id) or effect_id).casefold(), effect_id))
    for _sort_label, effect_id in sorted(tail):
        append_effect("User Effects", effect_id)
    return rows


def _quick_effect_enum_items_for_category(category):
    global _QUICK_EFFECT_ENUM_REFRESH_TIME
    category = str(category or "2D").upper()
    now = time.monotonic()
    cached = _QUICK_EFFECT_ENUM_CACHE.get(category)
    if cached and now - _QUICK_EFFECT_ENUM_REFRESH_TIME < _QUICK_EFFECT_ENUM_REFRESH_SECONDS:
        return cached
    try:
        rows = _curated_quick_effect_rows(category)
        signature = tuple(rows)
        if not cached or signature != _QUICK_EFFECT_ENUM_SIGNATURE.get(category):
            items = list(_QUICK_EFFECT_FALLBACK)
            for enum_index, (section, effect_id, label, icon) in enumerate(rows, start=1):
                items.append((
                    effect_id,
                    f"{section} · {label}",
                    f"Use {label} in this quick slot",
                    icon,
                    enum_index,
                ))
            _QUICK_EFFECT_ENUM_CACHE[category] = items
            _QUICK_EFFECT_ENUM_SIGNATURE[category] = signature
    except FBP_DATA_ERRORS:
        _QUICK_EFFECT_ENUM_CACHE.setdefault(category, list(_QUICK_EFFECT_FALLBACK))
        _QUICK_EFFECT_ENUM_SIGNATURE.setdefault(category, ())
    _QUICK_EFFECT_ENUM_REFRESH_TIME = now
    return _QUICK_EFFECT_ENUM_CACHE[category]


def _quick_effect_2d_enum_items(_self=None, _context=None):
    return _quick_effect_enum_items_for_category("2D")


def _quick_effect_3d_enum_items(_self=None, _context=None):
    return _quick_effect_enum_items_for_category("3D")


def _quick_mask_enum_items(_self=None, _context=None):
    global _QUICK_MASK_ENUM_SIGNATURE
    from .effects_registry import (
        FBP_EFFECT_COLOR_MASK,
        FBP_EFFECT_REGISTRY,
        FBP_MASK_EFFECT_MENU_SECTIONS,
    )

    essentials = (
        ("CLIPPING_MASK", "Clipping", "Clip to the nearest compatible layer below", effect_enum_icon("CLIPPING_MASK", "MOD_MASK")),
        ("SHAPE_MASK", "Shapes", "Choose Square, Circle or Triangle when used", effect_enum_icon("SHAPE_MASK", "SURFACE_NCURVE")),
        ("GREASE_PENCIL_MASK", "Grease Pencil", "Draw an editable Grease Pencil mask", effect_enum_icon("GREASE_PENCIL_MASK", "OUTLINER_OB_GREASEPENCIL")),
        (FBP_EFFECT_COLOR_MASK, "Color", "Mask pixels around a sampled color", effect_enum_icon(FBP_EFFECT_COLOR_MASK, FBP_EFFECT_REGISTRY.get(FBP_EFFECT_COLOR_MASK, {}).get("icon", "COLOR"))),
    )
    rows = [("Essential", *row) for row in essentials]
    seen = {row[0] for row in essentials}
    skip_tokens = {"GREASE_PENCIL_MASK_CONTROL", "SQUARE_MASK", "CIRCLE_MASK", "TRIANGLE_MASK"}
    for section, _icon, tokens in FBP_MASK_EFFECT_MENU_SECTIONS:
        for effect_id in tokens:
            effect_id = str(effect_id or "")
            if effect_id in skip_tokens or effect_id in seen or effect_id.startswith("FAMILY:"):
                continue
            definition = FBP_EFFECT_REGISTRY.get(effect_id, {}) or {}
            if not definition or bool(definition.get("custom_invalid", False)):
                continue
            seen.add(effect_id)
            rows.append((
                section,
                effect_id,
                _pie_mask_label(
                    definition.get("label", effect_id) or effect_id
                ),
                f"Use {definition.get('label', effect_id)} in this quick mask slot",
                effect_enum_icon(effect_id, definition.get("icon", "MOD_MASK")),
            ))
    signature = tuple(rows)
    if not _QUICK_MASK_ENUM_CACHE or signature != _QUICK_MASK_ENUM_SIGNATURE:
        _QUICK_MASK_ENUM_CACHE[:] = list(_QUICK_EFFECT_FALLBACK)
        for enum_index, (section, effect_id, label, description, icon) in enumerate(rows, start=1):
            _QUICK_MASK_ENUM_CACHE.append((
                effect_id,
                f"{section} · {label}",
                description,
                icon,
                enum_index,
            ))
        _QUICK_MASK_ENUM_SIGNATURE = signature
    return _QUICK_MASK_ENUM_CACHE


def _store_quick_effect_preference(context, index, effect_id):
    """Persist one quick-effect slot without staging ten temporary enums."""
    prefs = _addon_preferences(context)
    if prefs is None or not 1 <= int(index) <= len(_QUICK_EFFECT_PREF_NAMES):
        return False
    value = str(effect_id or "").strip()
    if value == "NONE":
        value = ""
    try:
        setattr(prefs, _QUICK_EFFECT_PREF_NAMES[int(index) - 1], value)
        return True
    except FBP_DATA_IO_ERRORS:
        return False


def _clear_all_quick_effect_preferences(context):
    changed = False
    for index in range(1, 6):
        changed = _store_quick_effect_preference(context, index, "") or changed
    return changed


def _store_quick_mask_preference(context, index, mask_id):
    prefs = _addon_preferences(context)
    if prefs is None or not 1 <= int(index) <= len(_QUICK_MASK_PREF_NAMES):
        return False
    value = str(mask_id or "").strip()
    if value == "NONE":
        value = ""
    try:
        setattr(prefs, _QUICK_MASK_PREF_NAMES[int(index) - 1], value)
        return True
    except FBP_DATA_IO_ERRORS:
        return False


class FBP_OT_SetViewportShading(Operator):
    bl_idname = "fbp.set_viewport_shading"
    bl_label = "Set Viewport Shading"
    bl_description = "Change the active 3D View shading mode"

    mode: EnumProperty(description='Operation mode for this viewport quick tool. Example: choose whether the command adds, removes, previews, repairs or applies settings.', 
        name="Shading",
        items=(
            ('WIREFRAME', "Wireframe", "Display scene geometry as wireframes"),
            ('SOLID', "Solid", "Display solid viewport shading"),
            ('MATERIAL', "Material Preview", "Preview materials and textures"),
            ('RENDERED', "Rendered", "Display the active render engine result"),
        ),
        default='SOLID',
    )

    @classmethod
    def poll(cls, context):
        return _view3d_space(context) is not None

    def execute(self, context):
        space = _view3d_space(context)
        if space is None:
            return {'CANCELLED'}
        try:
            shading = space.shading
            shading.type = self.mode
            # ``color_type`` and the other per-mode settings belong to the
            # viewport, not to this mode switch. Keeping them untouched makes
            # Solid return to the previous Textured/Random configuration after
            # a trip through Material Preview or Rendered.
            return {'FINISHED'}
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not change viewport shading", exc)
            return {'CANCELLED'}


class FBP_OT_ToggleRandomViewportColor(Operator):
    bl_idname = "fbp.toggle_random_viewport_color"
    bl_label = "Toggle Random Colors"
    bl_description = "Switch Solid shading between random object colors and material colors"

    @classmethod
    def poll(cls, context):
        return _view3d_space(context) is not None

    def execute(self, context):
        space = _view3d_space(context)
        if space is None:
            return {'CANCELLED'}
        try:
            shading = space.shading
            shading.type = 'SOLID'
            shading.color_type = 'MATERIAL' if shading.color_type == 'RANDOM' else 'RANDOM'
            return {'FINISHED'}
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not toggle random viewport colors", exc)
            return {'CANCELLED'}


class FBP_OT_ToggleTextureViewportShading(Operator):
    bl_idname = "fbp.set_texture_viewport_shading"
    bl_label = "Texture Viewport Shading"
    bl_description = "Toggle image textures in Solid viewport shading"

    @classmethod
    def poll(cls, context):
        return _view3d_space(context) is not None

    def execute(self, context):
        space = _view3d_space(context)
        if space is None:
            return {'CANCELLED'}
        try:
            shading = space.shading
            was_active = shading.type == 'SOLID' and shading.color_type == 'TEXTURE'
            shading.type = 'SOLID'
            shading.color_type = 'MATERIAL' if was_active else 'TEXTURE'
            return {'FINISHED'}
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not toggle texture viewport shading", exc)
            return {'CANCELLED'}


class FBP_OT_ToggleFlatViewportLighting(Operator):
    bl_idname = "fbp.toggle_flat_viewport_lighting"
    bl_label = "Toggle Flat Viewport Lighting"
    bl_description = "Toggle Flat lighting in Solid viewport shading"

    @classmethod
    def poll(cls, context):
        return _view3d_space(context) is not None

    def execute(self, context):
        space = _view3d_space(context)
        if space is None:
            return {'CANCELLED'}
        try:
            shading = space.shading
            shading.type = 'SOLID'
            shading.light = 'STUDIO' if shading.light == 'FLAT' else 'FLAT'
            return {'FINISHED'}
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not toggle flat viewport lighting", exc)
            return {'CANCELLED'}


class FBP_OT_ToggleViewportCompositor(Operator):
    bl_idname = "fbp.toggle_viewport_compositor"
    bl_label = "Toggle Viewport Compositor"
    bl_description = "Toggle the scene compositor in the viewport using Always mode"

    @classmethod
    def poll(cls, context):
        space = _view3d_space(context)
        return bool(space and hasattr(space.shading, "use_compositor"))

    def execute(self, context):
        space = _view3d_space(context)
        if space is None or not hasattr(space.shading, "use_compositor"):
            return {'CANCELLED'}
        try:
            shading = space.shading
            enable = shading.use_compositor != 'ALWAYS'
            shading.use_compositor = 'ALWAYS' if enable else 'DISABLED'
            if enable:
                shading.type = 'RENDERED'
            return {'FINISHED'}
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not toggle the viewport compositor", exc)
            return {'CANCELLED'}


class FBP_OT_ToggleRenderTransparency(Operator):
    bl_idname = "fbp.toggle_render_transparency"
    bl_label = "Toggle Render Transparency"
    bl_description = "Toggle a transparent render background for Eevee and Cycles"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        render = getattr(getattr(context, "scene", None), "render", None)
        return bool(render and hasattr(render, "film_transparent"))

    def execute(self, context):
        render = getattr(getattr(context, "scene", None), "render", None)
        if render is None or not hasattr(render, "film_transparent"):
            return {'CANCELLED'}
        try:
            render.film_transparent = not bool(render.film_transparent)
            # The transparent film is only visible in Rendered shading. Match
            # every other effect-facing Pie action by revealing its result once,
            # while leaving subsequent manual shading changes untouched.
            space = _view3d_space(context)
            if space is not None:
                space.shading.type = 'RENDERED'
            return {'FINISHED'}
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not toggle render transparency", exc)
            return {'CANCELLED'}


class FBP_OT_ToggleSelectedVisibility(Operator):
    bl_idname = "fbp.toggle_selected_visibility"
    bl_label = "Hide Selected"
    bl_description = "Hide selected Frame By Plane layers or Blender objects, or show the last hidden selection"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(_selected_hide_targets(context))

    def execute(self, context):
        targets = _selected_hide_targets(context)
        if not targets:
            return {'CANCELLED'}

        hidden_states = [_object_hidden_in_view(obj) for obj in targets]
        hide = not all(hidden_states)
        changed = 0

        if hide:
            _FBP_LAST_HIDDEN_OBJECT_NAMES[:] = [
                obj.name for obj in targets if obj is not None
            ]
        else:
            _FBP_LAST_HIDDEN_OBJECT_NAMES.clear()

        for obj in targets:
            try:
                if _object_hidden_in_view(obj) == hide:
                    continue
                obj.hide_set(hide)
                changed += 1
            except FBP_DATA_IO_ERRORS:
                try:
                    if bool(getattr(obj, "hide_viewport", False)) == hide:
                        continue
                    obj.hide_viewport = hide
                    changed += 1
                except FBP_DATA_IO_ERRORS:
                    continue

        if not hide:
            selectable = [
                obj for obj in targets
                if obj is not None and not bool(getattr(obj, "hide_select", False))
            ]
            for obj in selectable:
                try:
                    obj.select_set(True)
                except FBP_DATA_IO_ERRORS:
                    continue
            active = next(
                (obj for obj in selectable if bool(getattr(obj, "is_fbp_control", False))),
                selectable[0] if selectable else None,
            )
            if active is not None:
                try:
                    context.view_layer.objects.active = active
                except FBP_DATA_IO_ERRORS:
                    pass

        return {'FINISHED'} if changed else {'CANCELLED'}


class FBP_OT_ToggleLocalViewWithLights(Operator):
    bl_idname = "fbp.toggle_local_view_with_lights"
    bl_label = "Solo Selection"
    bl_description = "Show only selected Frame By Plane layers or Blender objects while keeping lights available"

    @classmethod
    def poll(cls, context):
        space = _view3d_space(context)
        return bool(space and (space.local_view is not None or getattr(context, "selected_objects", None)))

    def execute(self, context):
        space = _view3d_space(context)
        if space is None:
            return {'CANCELLED'}
        if space.local_view is not None:
            try:
                result = bpy.ops.view3d.localview(frame_selected=False)
                return {'FINISHED'} if 'FINISHED' in result else {'CANCELLED'}
            except FBP_DATA_ERRORS as exc:
                fbp_warn("Could not leave selection solo", exc)
                return {'CANCELLED'}

        selected = list(getattr(context, "selected_objects", ()) or ())
        rigs = _selected_fbp_rigs(context)
        targets = []
        target_keys = set()
        for obj in selected:
            _append_unique_object(targets, target_keys, obj)
        for obj in _fbp_objects_for_rigs(rigs):
            _append_unique_object(targets, target_keys, obj)
        if not targets:
            return {'CANCELLED'}

        active = getattr(context.view_layer.objects, "active", None)
        original_hide_select = {}
        temporary_selection = []
        temporary_keys = set()
        result = {'CANCELLED'}
        try:
            for obj in selected:
                try:
                    obj.select_set(False)
                except FBP_DATA_IO_ERRORS:
                    continue

            for obj in targets:
                try:
                    original_hide_select[_object_runtime_key(obj)] = (
                        obj,
                        bool(getattr(obj, "hide_select", False)),
                    )
                    if bool(getattr(obj, "hide_select", False)):
                        obj.hide_select = False
                    obj.select_set(True)
                    _append_unique_object(temporary_selection, temporary_keys, obj)
                except FBP_DATA_IO_ERRORS:
                    continue

            # Local View excludes unselected lights, so add only visible lights.
            for obj in context.view_layer.objects:
                try:
                    if getattr(obj, "type", None) != 'LIGHT' or obj.hide_get():
                        continue
                    obj.select_set(True)
                    _append_unique_object(temporary_selection, temporary_keys, obj)
                except FBP_DATA_IO_ERRORS:
                    continue

            operator_result = bpy.ops.view3d.localview(frame_selected=False)
            result = {'FINISHED'} if 'FINISHED' in operator_result else {'CANCELLED'}
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not toggle selection solo", exc)
        finally:
            for obj, was_hidden in original_hide_select.values():
                try:
                    obj.hide_select = was_hidden
                except FBP_DATA_IO_ERRORS:
                    continue
            for obj in temporary_selection:
                try:
                    obj.select_set(False)
                except FBP_DATA_IO_ERRORS:
                    continue
            for obj in selected:
                try:
                    obj.select_set(True)
                except FBP_DATA_IO_ERRORS:
                    continue
            if active is not None:
                try:
                    context.view_layer.objects.active = active
                except FBP_DATA_IO_ERRORS:
                    pass
        return result


class FBP_OT_ToggleSelectedLock(Operator):
    bl_idname = "fbp.toggle_selected_lock"
    bl_label = "Lock Selected"
    bl_description = "Lock Frame By Plane layer controls or all transforms of selected Blender objects"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        rigs, generic = _selected_lock_targets(context)
        return bool(rigs or generic)

    def execute(self, context):
        rigs, generic = _selected_lock_targets(context)
        states = [bool(getattr(rig, "hide_select", False)) for rig in rigs]
        states.extend(_object_transform_locked(obj) for obj in generic)
        if not states:
            return {'CANCELLED'}
        lock = not all(states)
        changed = 0
        if rigs:
            if lock:
                _FBP_LAST_LOCKED_RIG_NAMES[:] = [rig.name for rig in rigs if rig is not None]
            else:
                _FBP_LAST_LOCKED_RIG_NAMES.clear()
        for rig in rigs:
            try:
                if bool(getattr(rig, "hide_select", False)) != lock:
                    rig.hide_select = lock
                    changed += 1
            except FBP_DATA_IO_ERRORS:
                continue
        value = (lock, lock, lock)
        for obj in generic:
            try:
                if _object_transform_locked(obj) == lock:
                    continue
                obj.lock_location = value
                obj.lock_rotation = value
                obj.lock_scale = value
                changed += 1
            except FBP_DATA_IO_ERRORS:
                continue
        return {'FINISHED'} if changed else {'CANCELLED'}


class FBP_OT_ToggleSelectedSelectability(Operator):
    bl_idname = "fbp.toggle_selected_selectability"
    bl_label = "Toggle Selectability"
    bl_description = "Switch Frame By Plane selection between rig and plane, or allow/prevent direct selection of ordinary Blender objects"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        _rigs, planes, generic = _selected_selectability_targets(context)
        return bool(planes or generic)

    def execute(self, context):
        rigs, planes, generic = _selected_selectability_targets(context)
        states = [bool(getattr(plane, "hide_select", False)) for plane in planes]
        states.extend(bool(getattr(obj, "hide_select", False)) for obj in generic)
        if not states:
            return {'CANCELLED'}
        make_selectable = all(states)
        changed = 0
        active_plane = None
        if generic:
            if make_selectable:
                _FBP_LAST_SELECTABILITY_NAMES.clear()
            else:
                _FBP_LAST_SELECTABILITY_NAMES[:] = [obj.name for obj in generic if obj is not None]

        target_hide_select = not make_selectable
        for plane in planes:
            try:
                if bool(getattr(plane, "hide_select", False)) != target_hide_select:
                    plane.hide_select = target_hide_select
                    changed += 1
                if make_selectable:
                    plane.select_set(True)
                    active_plane = active_plane or plane
                else:
                    plane.select_set(False)
            except FBP_DATA_IO_ERRORS:
                continue
        for rig in rigs:
            try:
                if make_selectable:
                    rig.select_set(False)
                else:
                    if bool(getattr(rig, "hide_select", False)):
                        rig.hide_select = False
                        changed += 1
                    rig.select_set(True)
                    context.view_layer.objects.active = rig
            except FBP_DATA_IO_ERRORS:
                continue
        for obj in generic:
            try:
                if bool(getattr(obj, "hide_select", False)) == target_hide_select:
                    continue
                obj.hide_select = target_hide_select
                changed += 1
            except FBP_DATA_IO_ERRORS:
                continue
        if active_plane is not None:
            try:
                context.view_layer.objects.active = active_plane
            except FBP_DATA_IO_ERRORS:
                pass
        return {'FINISHED'} if changed else {'CANCELLED'}


class FBP_OT_ToggleSelectedHoldout(Operator):
    bl_idname = "fbp.toggle_selected_holdout"
    bl_label = "Toggle Selected Holdout"
    bl_description = "Toggle holdout on selected Frame By Plane layers or compatible Blender objects"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(_toggleable_fbp_holdout_rigs(context) or _generic_holdout_objects(context))

    def execute(self, context):
        rigs = _toggleable_fbp_holdout_rigs(context)
        generic = _generic_holdout_objects(context)
        states = [_rig_holdout_state(rig) for rig in rigs]
        states.extend(bool(getattr(obj, "is_holdout", False)) for obj in generic)
        if not states:
            return {'CANCELLED'}
        enable = not all(states)
        changed = 0
        try:
            from .materials import (
                fbp_apply_holdout_materials_to_rig,
                fbp_is_native_holdout_plane,
                restore_original_materials_from_holdout,
            )
            for rig in rigs:
                if fbp_is_native_holdout_plane(rig):
                    continue
                result = (
                    fbp_apply_holdout_materials_to_rig(rig)
                    if enable
                    else restore_original_materials_from_holdout(rig)
                )
                changed += int(bool(result))
            for obj in generic:
                if bool(getattr(obj, "is_holdout", False)) == enable:
                    continue
                obj.is_holdout = enable
                changed += 1
            return {'FINISHED'} if changed else {'CANCELLED'}
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not toggle selected holdout objects", exc)
            return {'CANCELLED'}


class FBP_OT_ToggleCursorOnCamera(Operator):
    bl_idname = "fbp.toggle_cursor_on_camera"
    bl_label = "Cursor On Camera"
    bl_description = "Attach the 3D cursor to the active camera until the cursor is moved manually"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        camera = getattr(scene, "camera", None) if scene else None
        return bool(scene and camera and getattr(camera, "type", None) == 'CAMERA')

    def execute(self, context):
        scene = getattr(context, "scene", None)
        if scene is None:
            return {'CANCELLED'}
        try:
            if _cursor_on_camera_is_enabled(scene):
                _cursor_on_camera_set_enabled(scene, False)
                self.report({'INFO'}, "Cursor On Camera disabled")
                return {'FINISHED'}
            camera, target = _active_camera_location(scene)
            if camera is None or target is None:
                self.report({'WARNING'}, "No active camera available")
                return {'CANCELLED'}
            _cursor_on_camera_set_enabled(scene, True)
            if not _write_cursor_on_camera_state(scene, camera, target):
                _cursor_on_camera_set_enabled(scene, False)
                self.report({'WARNING'}, "Could not attach cursor to camera")
                return {'CANCELLED'}
            _ensure_cursor_on_camera_timer()
            self.report({'INFO'}, "Cursor On Camera enabled")
            return {'FINISHED'}
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not toggle Cursor On Camera", exc)
            return {'CANCELLED'}


class FBP_OT_SetQuickImageEffectSlot(Operator):
    bl_idname = "fbp.set_quick_image_effect_slot"
    bl_label = "Set Image Effect Slot"
    bl_description = "Assign an Image effect to this Z Pie Menu slot"
    bl_options = {'INTERNAL'}

    slot_index: IntProperty(default=1, min=1, max=5, options={'SKIP_SAVE'})
    effect_id: EnumProperty(
        name="Image Effect",
        items=_quick_effect_2d_enum_items,
        options={'SKIP_SAVE'},
    )

    def execute(self, context):
        return (
            {'FINISHED'}
            if _store_quick_effect_preference(context, self.slot_index, self.effect_id)
            else {'CANCELLED'}
        )


class FBP_OT_SetQuickMeshEffectSlot(Operator):
    bl_idname = "fbp.set_quick_mesh_effect_slot"
    bl_label = "Set Mesh Effect Slot"
    bl_description = "Assign a Mesh effect to this Z Pie Menu slot"
    bl_options = {'INTERNAL'}

    slot_index: IntProperty(default=1, min=1, max=5, options={'SKIP_SAVE'})
    effect_id: EnumProperty(
        name="Mesh Effect",
        items=_quick_effect_3d_enum_items,
        options={'SKIP_SAVE'},
    )

    def execute(self, context):
        return (
            {'FINISHED'}
            if _store_quick_effect_preference(context, self.slot_index, self.effect_id)
            else {'CANCELLED'}
        )


class FBP_OT_ClearQuickEffectSlot(Operator):
    bl_idname = "fbp.clear_quick_effect_slot"
    bl_label = "Clear Slot"
    bl_description = "Remove the effect assigned to this quick slot"
    bl_options = {'INTERNAL'}

    slot_index: IntProperty(default=1, min=1, max=5, options={'SKIP_SAVE'})

    def execute(self, context):
        return (
            {'FINISHED'}
            if _store_quick_effect_preference(context, self.slot_index, "")
            else {'CANCELLED'}
        )


class FBP_OT_ResetQuickEffectSlots(Operator):
    bl_idname = "fbp.reset_quick_effect_slots"
    bl_label = "Reset Quick Effect Slots"
    bl_description = "Clear all five quick-effect slots"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        return {'FINISHED'} if _clear_all_quick_effect_preferences(context) else {'CANCELLED'}


class FBP_OT_SetQuickMaskSlot(Operator):
    bl_idname = "fbp.set_quick_mask_slot"
    bl_label = "Set Favourite Mask"
    bl_options = {'INTERNAL'}

    slot_index: IntProperty(default=1, min=1, max=5, options={'SKIP_SAVE'})
    mask_id: StringProperty(default="", options={'SKIP_SAVE'})

    def execute(self, context):
        return (
            {'FINISHED'}
            if _store_quick_mask_preference(
                context, self.slot_index, self.mask_id
            )
            else {'CANCELLED'}
        )


class FBP_OT_ResetQuickMaskSlots(Operator):
    bl_idname = "fbp.reset_quick_mask_slots"
    bl_label = "Reset Favourite Masks"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        changed = False
        for index in range(1, 6):
            changed = _store_quick_mask_preference(context, index, "") or changed
        return {'FINISHED'} if changed else {'CANCELLED'}


class FBP_OT_QuickMaskLibraryPopup(Operator):
    bl_idname = "fbp.quick_mask_library_popup"
    bl_label = "Choose Favourite Mask"
    bl_options = {'INTERNAL'}

    slot_index: IntProperty(default=1, min=1, max=5, options={'SKIP_SAVE'})

    def invoke(self, context, _event):
        return context.window_manager.invoke_popup(self, width=620)

    def draw(self, context):
        layout = configure_layout(self.layout)
        from .geometry_nodes import _fbp_draw_effect_add_columns
        _fbp_draw_effect_add_columns(
            layout,
            context,
            "MASK",
            max_columns=2,
            quick_slot_index=self.slot_index,
            quick_kind="MASK",
        )
        layer = layout.column(align=False)
        layer.label(text="Layer", icon="RENDERLAYERS")
        clipping = layer.operator(
            FBP_OT_SetQuickMaskSlot.bl_idname,
            text="Clipping",
            **effect_icon_kwargs("CLIPPING_MASK", "MOD_MASK"),
        )
        clipping.slot_index = self.slot_index
        clipping.mask_id = "CLIPPING_MASK"
        clear = layout.operator(
            FBP_OT_SetQuickMaskSlot.bl_idname,
            text="Clear Slot",
            icon="X",
        )
        clear.slot_index = self.slot_index
        clear.mask_id = ""

    def execute(self, _context):
        return {'FINISHED'}


class FBP_OT_QuickMasksPopup(Operator):
    bl_idname = "fbp.quick_masks_popup"
    bl_label = "Favourite Masks"
    bl_description = "Choose up to five masks shown in the south-west Z Pie Menu sector"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return _view3d_space(context) is not None

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(
            self,
            width=460,
            confirm_text="Done",
        )

    def draw(self, context):
        layout = configure_layout(self.layout)
        section_header(layout, "Favourite Masks", icon="MOD_MASK")
        hint_row(
            layout,
            "Choose each slot from the same compact library used by Add Mask.",
            icon="INFO",
        )
        prefs = _addon_preferences(context)
        slots = layout.grid_flow(
            row_major=True, columns=2, even_columns=True, even_rows=True,
            align=True,
        )
        for index in range(1, 6):
            mask_id = (
                str(
                    getattr(
                        prefs,
                        _QUICK_MASK_PREF_NAMES[index - 1],
                        _QUICK_MASK_DEFAULTS[index - 1],
                    )
                    or ""
                )
                if prefs is not None else ""
            )
            label = "Empty Slot"
            icon = "ADD"
            icon_value = 0
            for item in _quick_mask_enum_items(self, context):
                if item[0] == mask_id:
                    label = (
                        str(item[1])
                        .replace("Â·", "·")
                        .rsplit("·", 1)[-1]
                        .strip()
                    )
                    enum_icon = item[3] or "MOD_MASK"
                    if isinstance(enum_icon, int):
                        icon_value = int(enum_icon)
                    else:
                        icon = str(enum_icon)
                    break
            op = slots.operator(
                FBP_OT_QuickMaskLibraryPopup.bl_idname,
                text=f"{index}. {label}",
                **({"icon_value": icon_value} if icon_value else {"icon": icon}),
            )
            op.slot_index = index
        section_gap(layout)
        layout.operator(
            FBP_OT_ResetQuickMaskSlots.bl_idname,
            text="Reset Slots",
            icon='FILE_REFRESH',
        )

    def execute(self, _context):
        return {'FINISHED'}


class FBP_OT_QuickEffectsPopup(Operator):
    bl_idname = "fbp.quick_effects_popup"
    bl_label = "Favourite Effects"
    bl_description = "Choose up to five effects shown in the south-east Z Pie Menu sector"
    bl_options = {'INTERNAL'}

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(
            self,
            width=520,
            confirm_text="Done",
        )

    def draw(self, context):
        layout = configure_layout(self.layout)
        section_header(layout, "Favourite Effects", icon="SHADERFX")
        hint_row(
            layout,
            "Choose Image or Mesh, then pick from the normal Add Effect library.",
            icon="INFO",
        )
        prefs = _addon_preferences(context)
        for index in range(1, 6):
            effect_id, label, icon = _quick_effect_slot_presentation(
                context,
                index,
                prefs=prefs,
            )
            row = layout.row(align=True)
            row.label(text=f"{index}. {label}", icon=icon)
            image = row.operator(
                FBP_OT_QuickEffectLibraryPopup.bl_idname,
                text="Image",
                icon="IMAGE_BACKGROUND",
            )
            image.slot_index = index
            image.category = "2D"
            mesh = row.operator(
                FBP_OT_QuickEffectLibraryPopup.bl_idname,
                text="Mesh",
                icon="MESH_DATA",
            )
            mesh.slot_index = index
            mesh.category = "3D"
            clear = row.row(align=True)
            clear.enabled = bool(effect_id)
            clear_op = clear.operator(
                FBP_OT_ClearQuickEffectSlot.bl_idname,
                text="",
                icon="X",
            )
            clear_op.slot_index = index
        section_gap(layout)
        layout.operator(
            FBP_OT_ResetQuickEffectSlots.bl_idname,
            text="Reset Slots",
            icon="FILE_REFRESH",
        )

    def execute(self, _context):
        return {'FINISHED'}


class FBP_OT_QuickEffectLibraryPopup(Operator):
    bl_idname = "fbp.quick_effect_library_popup"
    bl_label = "Choose Quick Effect"
    bl_options = {'INTERNAL'}

    slot_index: IntProperty(default=1, min=1, max=5, options={'SKIP_SAVE'})
    category: EnumProperty(
        items=(
            ("2D", "Image", "Image and shader effects"),
            ("3D", "Mesh", "Geometry Nodes effects"),
        ),
        default="2D",
        options={'SKIP_SAVE'},
    )

    def invoke(self, context, _event):
        return context.window_manager.invoke_popup(self, width=680)

    def draw(self, context):
        layout = configure_layout(self.layout)
        from .geometry_nodes import _fbp_draw_effect_add_columns
        _fbp_draw_effect_add_columns(
            layout,
            context,
            self.category,
            max_columns=2,
            quick_slot_index=self.slot_index,
            quick_kind="EFFECT",
        )

    def execute(self, _context):
        return {'FINISHED'}


def _quick_effect_slot_presentation(context, index, *, prefs=None):
    if prefs is None:
        prefs = _addon_preferences(context)
    try:
        effect_id = str(
            getattr(prefs, _QUICK_EFFECT_PREF_NAMES[int(index) - 1], "") or ""
        ).strip()
    except (AttributeError, IndexError, TypeError, ValueError):
        effect_id = ""
    if not effect_id:
        return "", "Empty Slot", "ADD"
    try:
        from .effects_registry import fbp_effect_definition
        definition = fbp_effect_definition(effect_id) or {}
    except FBP_DATA_ERRORS:
        definition = {}
    return (
        effect_id,
        str(definition.get("label", effect_id) or effect_id),
        str(definition.get("icon", "MODIFIER") or "MODIFIER"),
    )


def _draw_quick_effect_slot_menu(menu, context, index):
    layout = configure_layout(menu.layout)
    effect_id, label, icon = _quick_effect_slot_presentation(context, index)
    layout.label(text=label, icon=icon)
    layout.separator()
    image = layout.operator(
        FBP_OT_QuickEffectLibraryPopup.bl_idname,
        text="Image",
        icon="IMAGE_BACKGROUND",
    )
    image.slot_index = index
    image.category = "2D"
    mesh = layout.operator(
        FBP_OT_QuickEffectLibraryPopup.bl_idname,
        text="Mesh",
        icon="MESH_DATA",
    )
    mesh.slot_index = index
    mesh.category = "3D"
    if effect_id:
        layout.separator()
        clear = layout.operator(
            FBP_OT_ClearQuickEffectSlot.bl_idname,
            text="Clear Slot",
            icon="X",
        )
        clear.slot_index = index


class FBP_MT_QuickEffectSlot1(Menu):
    bl_idname = "FBP_MT_quick_effect_slot_1"
    bl_label = "Slot 1"

    def draw(self, context):
        _draw_quick_effect_slot_menu(self, context, 1)


class FBP_MT_QuickEffectSlot2(Menu):
    bl_idname = "FBP_MT_quick_effect_slot_2"
    bl_label = "Slot 2"

    def draw(self, context):
        _draw_quick_effect_slot_menu(self, context, 2)


class FBP_MT_QuickEffectSlot3(Menu):
    bl_idname = "FBP_MT_quick_effect_slot_3"
    bl_label = "Slot 3"

    def draw(self, context):
        _draw_quick_effect_slot_menu(self, context, 3)


class FBP_MT_QuickEffectSlot4(Menu):
    bl_idname = "FBP_MT_quick_effect_slot_4"
    bl_label = "Slot 4"

    def draw(self, context):
        _draw_quick_effect_slot_menu(self, context, 4)


class FBP_MT_QuickEffectSlot5(Menu):
    bl_idname = "FBP_MT_quick_effect_slot_5"
    bl_label = "Slot 5"

    def draw(self, context):
        _draw_quick_effect_slot_menu(self, context, 5)


_QUICK_EFFECT_SLOT_MENUS = (
    FBP_MT_QuickEffectSlot1,
    FBP_MT_QuickEffectSlot2,
    FBP_MT_QuickEffectSlot3,
    FBP_MT_QuickEffectSlot4,
    FBP_MT_QuickEffectSlot5,
)


class FBP_MT_QuickEffectSlots(Menu):
    bl_idname = "FBP_MT_quick_effect_slots"
    bl_label = "Quick Effects"

    def draw(self, context):
        layout = configure_layout(self.layout)
        prefs = _addon_preferences(context)
        slots = layout.grid_flow(
            row_major=True, columns=2, even_columns=True, even_rows=True,
            align=True,
        )
        for index, menu_class in enumerate(_QUICK_EFFECT_SLOT_MENUS, start=1):
            _effect_id, _label, icon = _quick_effect_slot_presentation(
                context,
                index,
                prefs=prefs,
            )
            slots.menu(menu_class.bl_idname, text=f"Slot {index}", icon=icon)
        layout.separator()
        layout.operator(
            FBP_OT_ResetQuickEffectSlots.bl_idname,
            text="Reset Slots",
            icon="FILE_REFRESH",
        )


def _configured_quick_effect_ids(context):
    """Return unique saved quick-effect IDs in stable slot order."""
    prefs = _addon_preferences(context)
    if prefs is None:
        return ()
    try:
        from .effects_registry import fbp_effect_definition
    except (ImportError, AttributeError):
        fbp_effect_definition = None
    effect_ids = []
    seen = set()
    for pref_name in _QUICK_EFFECT_PREF_NAMES:
        effect_id = str(getattr(prefs, pref_name, "") or "").strip()
        if not effect_id or effect_id == 'NONE' or effect_id in seen:
            continue
        if fbp_effect_definition is not None:
            category = str((fbp_effect_definition(effect_id) or {}).get("category", "") or "").upper()
            if category not in {"BASE", "2D", "3D"}:
                continue
        seen.add(effect_id)
        effect_ids.append(effect_id)
    return tuple(effect_ids)


def _configured_quick_mask_ids(context):
    """Return unique saved mask tokens, preserving the requested defaults."""
    prefs = _addon_preferences(context)
    mask_ids = []
    seen = set()
    for index, pref_name in enumerate(_QUICK_MASK_PREF_NAMES):
        fallback = _QUICK_MASK_DEFAULTS[index]
        mask_id = str(getattr(prefs, pref_name, fallback) or "").strip() if prefs is not None else fallback
        if not mask_id or mask_id == 'NONE' or mask_id in seen:
            continue
        seen.add(mask_id)
        mask_ids.append(mask_id)
    return tuple(mask_ids)


def _pie_operation_finished(result):
    return bool({"FINISHED", "RUNNING_MODAL"}.intersection(set(result or ())))


def _pie_reveal_effects(context, view, *, material_preview=False, preserve_active=False):
    view = str(view or "2D").upper()
    if view not in {"2D", "MASK", "3D"}:
        view = "2D"
    try:
        context.scene.fbp_effects_view = view
    except FBP_DATA_ERRORS:
        pass
    if material_preview:
        space = _view3d_space(context)
        shading = getattr(space, "shading", None) if space is not None else None
        try:
            shading_type = str(getattr(shading, "type", "SOLID") or "SOLID") if shading is not None else ""
            if shading is not None and shading_type not in {"MATERIAL", "RENDERED"}:
                shading.type = "MATERIAL"
        except FBP_DATA_ERRORS:
            pass
    if preserve_active:
        # Grease Pencil Mask enters native Paint Mode.  Calling the regular
        # panel-opening operator here would immediately switch back to Object
        # Mode and reselect the FBP rig, which made Z > Grease Pencil Mask look
        # as if Draw Mode had failed whenever Crop/Expand controls were active.
        for area in tuple(getattr(getattr(context, "screen", None), "areas", ()) or ()):
            if str(getattr(area, "type", "") or "") != "PROPERTIES":
                continue
            try:
                area.spaces.active.context = "MODIFIER"
                area.tag_redraw()
            except FBP_DATA_ERRORS:
                continue
        return
    try:
        bpy.ops.fbp.open_effects_masks(view=view)
    except FBP_DATA_ERRORS:
        pass


class FBP_OT_PieAddEffect(Operator):
    bl_idname = "fbp.pie_add_effect"
    bl_label = "Add Favourite Effect"
    bl_description = "Add this favourite and reveal its Image, Mask or Mesh panel"
    bl_options = {'REGISTER'}

    effect_id: StringProperty(
        name="Effect ID",
        description="Stable effect identifier selected from the Z Pie Menu",
        default="",
        options={'SKIP_SAVE'},
    )

    @classmethod
    def description(cls, _context, properties):
        try:
            from .effects_registry import fbp_effect_definition
            effect_id = str(getattr(properties, "effect_id", "") or "")
            definition = fbp_effect_definition(effect_id) or {}
            label = str(definition.get("label", effect_id) or effect_id)
            detail = str(definition.get("description", "") or "").strip()
            return f"Add {label}" + (f"\n{detail}" if detail else "")
        except FBP_DATA_ERRORS:
            return cls.bl_description

    @classmethod
    def poll(cls, context):
        return bool(_selected_fbp_rigs(context))

    def execute(self, context):
        try:
            from .effects_registry import fbp_effect_definition, fbp_normalize_effect_id
            effect_id = fbp_normalize_effect_id(self.effect_id)
            definition = fbp_effect_definition(effect_id) or {}
            if not definition:
                return {'CANCELLED'}
            result = bpy.ops.fbp.add_effect(effect_id=effect_id)
            if not _pie_operation_finished(result):
                return {'CANCELLED'}
            category = str(definition.get("category", "2D") or "2D").upper()
            view = "3D" if category == "3D" else ("MASK" if category == "MASK" else "2D")
            _pie_reveal_effects(
                context,
                view,
                material_preview=category in {"BASE", "2D", "MASK"},
            )
            return {'FINISHED'}
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not add favourite effect from the viewport Pie", exc)
            return {'CANCELLED'}


class FBP_OT_PieAddGreasePencilMask(Operator):
    bl_idname = "fbp.pie_add_grease_pencil_mask"
    bl_label = "Grease Pencil Mask"
    bl_description = "Create an editable Grease Pencil mask and reveal the Mask panel"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return bool(_selected_fbp_rigs(context))

    def execute(self, context):
        try:
            result = bpy.ops.fbp.add_grease_pencil_mask()
            if not _pie_operation_finished(result):
                return {'CANCELLED'}
            _pie_reveal_effects(
                context, "MASK", material_preview=True, preserve_active=True,
            )
            return {'FINISHED'}
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not add Grease Pencil Mask from the viewport Pie", exc)
            return {'CANCELLED'}


class FBP_OT_PieToggleClippingMask(Operator):
    bl_idname = "fbp.pie_toggle_clipping_mask"
    bl_label = "Clipping Mask"
    bl_description = "Toggle Clipping Mask consistently across selected layers and reveal Masks"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return bool(_selected_fbp_rigs(context))

    def execute(self, context):
        rigs = _selected_fbp_rigs(context)
        if not rigs:
            return {'CANCELLED'}
        try:
            from .layers import fbp_layer_clipping_active_hint
            states = {
                rig: bool(fbp_layer_clipping_active_hint(rig))
                for rig in rigs
            }
            enable = not all(states.values())
            changed = 0
            for rig, active in states.items():
                if active == enable:
                    continue
                result = bpy.ops.fbp.toggle_clipping_mask(rig_name=rig.name)
                changed += int(_pie_operation_finished(result))
            if not changed:
                return {'CANCELLED'}
            _pie_reveal_effects(context, "MASK", material_preview=True)
            return {'FINISHED'}
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not toggle Clipping Mask from the viewport Pie", exc)
            return {'CANCELLED'}


def _pie_shape_mask_ids():
    """Return the compact default shape-mask set."""
    from .effects_registry import (
        FBP_EFFECT_CIRCLE_MASK,
        FBP_EFFECT_SQUARE_MASK,
    )
    return (
        FBP_EFFECT_CIRCLE_MASK,
        FBP_EFFECT_SQUARE_MASK,
    )


def _draw_pie_mask_action(layout, context, mask_id, rigs):
    mask_id = str(mask_id or "").upper()
    if mask_id == "CLIPPING_MASK":
        try:
            from .layers import fbp_layer_clipping_active_hint
            from .ui_icons import clipping_mask_icon_kwargs

            active = bool(rigs) and all(
                fbp_layer_clipping_active_hint(rig) for rig in rigs
            )
            row = _pie_fixed_button_row(
                layout,
                "Clipping",
                enabled=bool(rigs),
            )
            row.operator(
                "fbp.pie_toggle_clipping_mask",
                text="Clipping",
                **clipping_mask_icon_kwargs(active),
            )
        except (ImportError,) + FBP_DATA_ERRORS:
            layout.label(text="Clipping", icon="MOD_MASK")
        return
    if mask_id == "SHAPE_MASK":
        row = layout.row(align=True)
        row.enabled = bool(rigs)
        row.alignment = "CENTER"
        row.scale_x = _PIE_ICON_SCALE_X
        row.scale_y = _PIE_ICON_SCALE_Y
        try:
            from .effects_registry import fbp_effect_definition

            for effect_id in _pie_shape_mask_ids():
                definition = fbp_effect_definition(effect_id) or {}
                op = row.operator(
                    "fbp.pie_add_effect",
                    text="",
                    **effect_icon_kwargs(effect_id, definition.get("icon", "MOD_MASK")),
                )
                op.effect_id = effect_id
        except (ImportError,) + FBP_DATA_ERRORS:
            row.label(text="", icon="SURFACE_NCURVE")
        return
    if mask_id == "GREASE_PENCIL_MASK":
        row = _pie_icon_cell(layout, enabled=bool(rigs))
        row.operator(
            "fbp.pie_add_grease_pencil_mask",
            text="",
            **effect_icon_kwargs("GREASE_PENCIL_MASK", "OUTLINER_OB_GREASEPENCIL"),
        )
        return
    try:
        from .effects_registry import (
            fbp_effect_definition,
            fbp_effect_supported_for_rig,
        )
        from .geometry_nodes import fbp_effect_is_active

        definition = fbp_effect_definition(mask_id) or {}
        if not definition:
            return
        label = _pie_mask_label(
            definition.get("label", mask_id) or mask_id
        )
        row = _pie_fixed_button_row(
            layout,
            label,
            enabled=bool(
                rigs
                and all(
                    fbp_effect_supported_for_rig(rig, mask_id)
                    for rig in rigs
                )
                and not all(
                    fbp_effect_is_active(rig, mask_id) for rig in rigs
                )
            ),
        )
        op = row.operator(
            "fbp.pie_add_effect",
            text=label,
            **effect_icon_kwargs(mask_id, definition.get("icon", "MOD_MASK")),
        )
        op.effect_id = mask_id
    except (ImportError,) + FBP_DATA_ERRORS:
        pass


class FBP_OT_CallViewportPie(Operator):
    """Open the native Blender Frame By Plane viewport Pie."""

    bl_idname = "fbp.call_viewport_pie"
    bl_label = "Viewport Pie"
    bl_description = "Open the native Frame By Plane viewport Pie Menu"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return bool(
            _view3d_space(context) is not None
            and str(getattr(getattr(context, "region", None), "type", "") or "")
            == "WINDOW"
        )

    def _open(self):
        try:
            menu_result = bpy.ops.wm.call_menu_pie(
                name=FBP_MT_ViewportPie.bl_idname
            )
            if (
                "CANCELLED" in menu_result
                and not {"FINISHED", "RUNNING_MODAL"}.intersection(menu_result)
            ):
                return {"CANCELLED"}
            return {"FINISHED"}
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not open the native viewport Pie Menu", exc)
            return {"CANCELLED"}

    def invoke(self, _context, _event):
        return self._open()

    def execute(self, _context):
        return self._open()


class FBP_MT_ViewportPie(Menu):
    """Native Blender viewport Pie."""

    bl_idname = "FBP_MT_viewport_pie"
    bl_label = "Viewport"

    def draw(self, context):
        layout = configure_layout(self.layout)
        space = _view3d_space(context)
        if space is None:
            layout.label(text="Open this menu from a 3D View")
            return

        pie = layout.menu_pie()
        shading = space.shading
        state = _pie_selection_state(context)
        gp_canvas = _active_gp_drawing_canvas(context)
        plane_rigs = () if gp_canvas is not None else state["rigs"]
        prefs = _addon_preferences(context)
        north_content = str(
            getattr(prefs, "pie_north_content", "CURSOR_PIVOT")
            or "CURSOR_PIVOT"
        )
        show_south_actions = bool(
            getattr(prefs, "pie_show_south_actions", True)
        )
        show_masks = bool(getattr(prefs, "pie_show_masks", True))
        show_effects = bool(getattr(prefs, "pie_show_effects", True))

        # WEST — Wireframe
        split = pie.split()
        wire = split.row(align=False)
        wire.alignment = "CENTER"
        button = wire.row(align=False)
        button.emboss = "PIE_MENU"
        button.scale_y = _PIE_BUTTON_SCALE_Y
        button.ui_units_x = _pie_text_width("Wireframe")
        op = button.operator(
            FBP_OT_SetViewportShading.bl_idname,
            text="Wireframe",
            icon="SHADING_WIRE",
            depress=shading.type == "WIREFRAME",
        )
        op.mode = "WIREFRAME"

        # EAST — Material Preview. Keep the four principal shading modes in
        # separate native Pie sectors so Blender preserves their radial spacing.
        split = pie.split()
        material = split.row(align=False)
        material.alignment = "CENTER"
        button = material.row(align=False)
        button.emboss = "PIE_MENU"
        button.scale_y = _PIE_BUTTON_SCALE_Y
        button.ui_units_x = _pie_text_width("Material")
        op = button.operator(
            FBP_OT_SetViewportShading.bl_idname,
            text="Material",
            icon="MATERIAL",
            depress=shading.type == "MATERIAL",
        )
        op.mode = "MATERIAL"

        # SOUTH — Hide, Solo, Lock / Selectability, Holdout
        split = pie.split()
        solo_active = space.local_view is not None
        solo_enabled = bool(
            solo_active or tuple(getattr(context, "selected_objects", ()) or ())
        )
        if not show_south_actions:
            split.separator()
        else:
            actions = split.column(align=False)
            actions.alignment = "CENTER"
            first = actions.row(align=True)
            first.alignment = "CENTER"
            first.emboss = "NORMAL"

            hide_active = state["hide_active"]
            cell = _pie_icon_cell(first, enabled=state["hide_enabled"])
            cell.operator(
                FBP_OT_ToggleSelectedVisibility.bl_idname,
                text="",
                icon="HIDE_ON" if hide_active else "HIDE_OFF",
                depress=hide_active,
            )
            cell = _pie_icon_cell(first, enabled=solo_enabled)
            cell.operator(
                FBP_OT_ToggleLocalViewWithLights.bl_idname,
                text="",
                icon="OUTLINER_OB_LIGHT" if solo_active else "LIGHT",
                depress=solo_active,
            )
            lock_active = state["lock_active"]
            cell = _pie_icon_cell(first, enabled=state["lock_enabled"])
            cell.operator(
                FBP_OT_ToggleSelectedLock.bl_idname,
                text="",
                icon=(
                    "DECORATE_LOCKED"
                    if lock_active
                    else "DECORATE_UNLOCKED"
                ),
                depress=lock_active,
            )

            second = actions.row(align=True)
            second.alignment = "CENTER"
            second.emboss = "NORMAL"
            selectability_active = state["selectability_active"]
            cell = _pie_icon_cell(
                second,
                enabled=state["selectability_enabled"],
            )
            cell.operator(
                FBP_OT_ToggleSelectedSelectability.bl_idname,
                text="",
                icon=(
                    "RESTRICT_SELECT_OFF"
                    if selectability_active
                    else "RESTRICT_SELECT_ON"
                ),
                depress=selectability_active,
            )
            holdout_active = state["holdout_active"]
            cell = _pie_icon_cell(second, enabled=state["holdout_enabled"])
            cell.operator(
                FBP_OT_ToggleSelectedHoldout.bl_idname,
                text="",
                depress=holdout_active,
                **ui_icon_kwargs("menu.holdout_plane", fallback="CLIPUV_HLT"),
            )

        # NORTH — configurable Cursor, Pivot or Orientation controls
        split = pie.split()
        if north_content == "HIDDEN":
            split.separator()
        else:
            north = split.column(align=False)
            north.alignment = "CENTER"
            if (
                north_content == "CURSOR_PIVOT"
                and getattr(context.scene, "camera", None) is not None
            ):
                cursor = north.row(align=False)
                cursor.alignment = "CENTER"
                button = cursor.row(align=False)
                button.emboss = "NORMAL"
                button.scale_y = _PIE_BUTTON_SCALE_Y
                button.ui_units_x = _pie_text_width("Cursor On Camera")
                button.operator(
                    FBP_OT_ToggleCursorOnCamera.bl_idname,
                    text="Cursor On Camera",
                    icon="PIVOT_CURSOR",
                    depress=_cursor_on_camera_is_enabled(context.scene),
                )
            if north_content in {"CURSOR_PIVOT", "PIVOT"}:
                pivot = north.row(align=True)
                pivot.emboss = "NORMAL"
                pivot.alignment = "CENTER"
                pivot.scale_x = _PIE_ICON_SCALE_X
                pivot.scale_y = _PIE_ICON_SCALE_Y
                for value, icon in (
                    ("CURSOR", "PIVOT_CURSOR"),
                    ("MEDIAN_POINT", "PIVOT_MEDIAN"),
                    ("INDIVIDUAL_ORIGINS", "PIVOT_INDIVIDUAL"),
                ):
                    pivot.prop_enum(
                        context.tool_settings,
                        "transform_pivot_point",
                        value,
                        text="",
                        icon=icon,
                    )
            elif north_content == "ORIENTATION":
                orientation = north.row(align=False)
                orientation.alignment = "CENTER"
                button = orientation.row(align=False)
                button.emboss = "NORMAL"
                button.scale_y = _PIE_BUTTON_SCALE_Y
                button.ui_units_x = _pie_text_width("Orientation")
                button.prop(
                    context.scene.transform_orientation_slots[0],
                    "type",
                    text="Orientation",
                    icon="ORIENTATION_GLOBAL",
                )

        # NORTH-WEST — compact display helpers above; Flat sits beside Solid.
        split = pie.split()
        solid_branch = split.column(align=False)
        solid_branch.alignment = "CENTER"

        display = solid_branch.row(align=True)
        display.alignment = "CENTER"
        random_cell = _pie_icon_cell(display)
        random_cell.operator(
            FBP_OT_ToggleRandomViewportColor.bl_idname,
            text="",
            icon="GEOMETRY_SET",
            depress=(shading.type == "SOLID" and shading.color_type == "RANDOM"),
        )
        textured_cell = _pie_icon_cell(display)
        textured_cell.operator(
            FBP_OT_ToggleTextureViewportShading.bl_idname,
            text="",
            icon="NODE_TEXTURE",
            depress=(shading.type == "SOLID" and shading.color_type == "TEXTURE"),
        )

        solid_branch.separator(factor=_PIE_BRANCH_GAP_FACTOR)
        solid = solid_branch.row(align=False)
        solid.alignment = "CENTER"
        flat_cell = _pie_icon_cell(solid)
        flat_cell.operator(
            FBP_OT_ToggleFlatViewportLighting.bl_idname,
            text="",
            icon="IMAGE_RGB",
            depress=(shading.type == "SOLID" and shading.light == "FLAT"),
        )
        button = solid.row(align=False)
        button.emboss = "PIE_MENU"
        button.scale_y = _PIE_BUTTON_SCALE_Y
        button.ui_units_x = _pie_text_width("Solid")
        op = button.operator(
            FBP_OT_SetViewportShading.bl_idname,
            text="Solid",
            icon="SHADING_SOLID",
            depress=shading.type == "SOLID",
        )
        op.mode = "SOLID"

        # NORTH-EAST — two equal square helpers, separated from Rendered.
        split = pie.split()
        rendered = split.column(align=False)
        rendered.alignment = "CENTER"
        rendered_tools = rendered.row(align=False)
        rendered_tools.alignment = "CENTER"
        render = getattr(context.scene, "render", None)
        transparency_active = bool(
            render and hasattr(render, "film_transparent") and render.film_transparent
        )
        transparency = _pie_icon_cell(
            rendered_tools,
            enabled=bool(render and hasattr(render, "film_transparent")),
        )
        transparency.operator(
            FBP_OT_ToggleRenderTransparency.bl_idname,
            text="",
            icon="TEXTURE",
            depress=transparency_active,
        )
        compositor_active = bool(
            hasattr(shading, "use_compositor") and shading.use_compositor == "ALWAYS"
        )
        compositor = _pie_icon_cell(
            rendered_tools,
            enabled=hasattr(shading, "use_compositor"),
        )
        compositor.operator(
            FBP_OT_ToggleViewportCompositor.bl_idname,
            text="",
            icon="CAMERA_STEREO",
            depress=compositor_active,
        )

        rendered.separator(factor=_PIE_BRANCH_GAP_FACTOR)
        rendered_main = rendered.row(align=False)
        rendered_main.alignment = "CENTER"
        button = rendered_main.row(align=False)
        button.emboss = "PIE_MENU"
        button.scale_y = _PIE_BUTTON_SCALE_Y
        button.ui_units_x = _pie_text_width("Rendered")
        op = button.operator(
            FBP_OT_SetViewportShading.bl_idname,
            text="Rendered",
            icon="SHADING_RENDERED",
            depress=shading.type == "RENDERED",
        )
        op.mode = "RENDERED"

        # SOUTH-WEST — compact mask tools; shape and GP masks share one row.
        split = pie.split()
        if not show_masks or not plane_rigs:
            split.separator()
        else:
            mask_column = split.column(align=False)
            mask_column.alignment = "CENTER"
            _pie_start_south_list(mask_column, "Masks", "MOD_MASK")
            used_mask_rows = 0
            quick_masks = _configured_quick_mask_ids(context)
            compact_tokens = {"SHAPE_MASK", "GREASE_PENCIL_MASK"}
            compact = mask_column.row(align=False)
            compact.alignment = "CENTER"
            try:
                from .effects_registry import fbp_effect_definition
                for effect_id in _pie_shape_mask_ids():
                    definition = fbp_effect_definition(effect_id) or {}
                    cell = _pie_icon_cell(compact, enabled=bool(plane_rigs))
                    op = cell.operator(
                        FBP_OT_PieAddEffect.bl_idname,
                        text="",
                        **effect_icon_kwargs(effect_id, definition.get("icon", "MOD_MASK")),
                    )
                    op.effect_id = effect_id
            except (ImportError,) + FBP_DATA_ERRORS:
                pass
            gp_cell = _pie_icon_cell(compact, enabled=bool(plane_rigs))
            gp_cell.operator(
                FBP_OT_PieAddGreasePencilMask.bl_idname,
                text="",
                **effect_icon_kwargs("GREASE_PENCIL_MASK", "OUTLINER_OB_GREASEPENCIL"),
            )
            used_mask_rows += 1

            for mask_id in quick_masks:
                if mask_id in compact_tokens:
                    continue
                _draw_pie_mask_action(mask_column, context, mask_id, plane_rigs)
                used_mask_rows += 1

            overflow = mask_column.row(align=False)
            overflow.alignment = "CENTER"
            button = _pie_icon_cell(overflow)
            button.menu(
                "FBP_MT_object_masks",
                text="",
                icon="COLLAPSEMENU",
            )
            used_mask_rows += 1
            # Tail padding, after the overflow button, fixes the title at the
            # same height as Effects and lets entries grow downward.
            _pie_pad_south_list(mask_column, used_mask_rows)

        # SOUTH-EAST — fixed-width effect actions followed by favourite slots.
        split = pie.split()
        if not show_effects:
            split.separator()
            return
        if gp_canvas is not None:
            effects = split.column(align=False)
            effects.alignment = "CENTER"
            _pie_start_south_list(effects, "Effects", "SHADERFX")
            gp_row = _pie_fixed_button_row(
                effects, "Grease Pencil Effects"
            )
            gp_row.menu(
                "FBP_MT_gp_native_effects",
                text="Grease Pencil Effects",
                icon="OUTLINER_OB_GREASEPENCIL",
            )
            overflow = effects.row(align=False)
            overflow.alignment = "CENTER"
            _pie_icon_cell(overflow).menu(
                "FBP_MT_pie_effect_domains",
                text="",
                icon="COLLAPSEMENU",
            )
            _pie_pad_south_list(effects, 2)
            return
        if not plane_rigs:
            split.separator()
            return

        column = split.column(align=False)
        column.alignment = "CENTER"
        _pie_start_south_list(column, "Effects", "SHADERFX")
        try:
            from .effects_registry import (
                fbp_effect_definition,
                fbp_effect_supported_for_rig,
            )
        except (ImportError,) + FBP_DATA_ERRORS:
            fbp_effect_definition = None
            fbp_effect_supported_for_rig = None

        quick_effects = []
        if fbp_effect_definition is not None:
            for effect_id in _configured_quick_effect_ids(context):
                definition = fbp_effect_definition(effect_id) or {}
                if not definition or bool(definition.get("custom_invalid", False)):
                    continue
                quick_effects.append((effect_id, definition))

        used_effect_rows = 0
        action_row = _pie_fixed_button_row(column, "Crop")
        op = action_row.operator(
            "fbp.focus_crop_extend",
            text="Crop",
            icon="FULLSCREEN_EXIT",
        )
        op.mode = "CROP"
        used_effect_rows += 1

        action_row = _pie_fixed_button_row(column, "Expand")
        op = action_row.operator(
            "fbp.focus_crop_extend",
            text="Expand",
            icon="FULLSCREEN_ENTER",
        )
        op.mode = "EXTEND"
        used_effect_rows += 1

        for effect_id, definition in quick_effects:
            label = str(definition.get("label", effect_id) or effect_id)
            icon = str(definition.get("icon", "SHADERFX") or "SHADERFX")
            effect_row = _pie_fixed_button_row(
                column,
                label,
                enabled=bool(
                    fbp_effect_supported_for_rig is not None
                    and any(
                        fbp_effect_supported_for_rig(rig, effect_id)
                        for rig in plane_rigs
                    )
                ),
            )
            op = effect_row.operator(
                FBP_OT_PieAddEffect.bl_idname,
                text=label,
                icon=icon,
            )
            op.effect_id = effect_id
            used_effect_rows += 1
        overflow = column.row(align=False)
        overflow.alignment = "CENTER"
        button = _pie_icon_cell(overflow)
        button.menu(
            "FBP_MT_pie_effect_domains",
            text="",
            icon="COLLAPSEMENU",
        )
        used_effect_rows += 1
        _pie_pad_south_list(column, used_effect_rows)


class FBP_OT_ToggleLayerEditMode(Operator):
    """Tab workflow for FBP rigs: expose only the useful Object/Edit toggle."""

    bl_idname = "fbp.toggle_layer_edit_mode"
    bl_label = "Edit Frame By Plane"
    bl_description = "Edit the mesh card owned by the selected Frame By Plane rig"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        try:
            return str(getattr(getattr(context, "area", None), "type", "") or "") == "VIEW_3D"
        except FBP_DATA_ERRORS:
            return False

    def execute(self, context):
        active = getattr(context, "active_object", None)
        if active is None:
            return {"PASS_THROUGH"}
        try:
            if bool(getattr(active, "is_fbp_plane", False)):
                plane = active
            elif bool(getattr(active, "is_fbp_control", False)):
                plane = getattr(active, "fbp_plane_target", None)
            else:
                return {"PASS_THROUGH"}
            if plane is None or str(getattr(plane, "type", "") or "") != "MESH":
                return {"PASS_THROUGH"}
            if str(getattr(plane, "mode", "OBJECT") or "OBJECT").upper() == "EDIT":
                if bpy.ops.object.mode_set.poll():
                    bpy.ops.object.mode_set(mode="OBJECT")
                    return {"FINISHED"}
                return {"CANCELLED"}
            if str(getattr(active, "mode", "OBJECT") or "OBJECT").upper() != "OBJECT" and bpy.ops.object.mode_set.poll():
                bpy.ops.object.mode_set(mode="OBJECT")
            for obj in tuple(getattr(context, "selected_objects", ()) or ()):
                try:
                    obj.select_set(False)
                except FBP_DATA_ERRORS:
                    pass
            plane.hide_set(False)
            plane.hide_viewport = False
            plane.select_set(True)
            context.view_layer.objects.active = plane
            if bpy.ops.object.mode_set.poll():
                bpy.ops.object.mode_set(mode="EDIT")
                return {"FINISHED"}
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not toggle Frame By Plane Edit Mode", exc)
        return {"PASS_THROUGH"}

_CLASSES = (
    FBP_OT_ToggleLayerEditMode,
    FBP_OT_CallViewportPie,
    FBP_MT_ViewportPie,
    FBP_OT_SetViewportShading,
    FBP_OT_ToggleRandomViewportColor,
    FBP_OT_ToggleTextureViewportShading,
    FBP_OT_ToggleFlatViewportLighting,
    FBP_OT_ToggleViewportCompositor,
    FBP_OT_ToggleRenderTransparency,
    FBP_OT_ToggleSelectedVisibility,
    FBP_OT_ToggleLocalViewWithLights,
    FBP_OT_ToggleSelectedLock,
    FBP_OT_ToggleSelectedSelectability,
    FBP_OT_ToggleSelectedHoldout,
    FBP_OT_ToggleCursorOnCamera,
    FBP_OT_PieAddEffect,
    FBP_OT_PieAddGreasePencilMask,
    FBP_OT_PieToggleClippingMask,
    FBP_OT_SetQuickImageEffectSlot,
    FBP_OT_SetQuickMeshEffectSlot,
    FBP_OT_QuickEffectLibraryPopup,
    FBP_OT_ClearQuickEffectSlot,
    FBP_OT_ResetQuickEffectSlots,
    FBP_OT_SetQuickMaskSlot,
    FBP_OT_ResetQuickMaskSlots,
    FBP_OT_QuickMaskLibraryPopup,
    FBP_OT_QuickMasksPopup,
    FBP_OT_QuickEffectsPopup,
    *_QUICK_EFFECT_SLOT_MENUS,
    FBP_MT_QuickEffectSlots,
)


def _unregister_keymaps():
    unregister_keymap_items(_FBP_VIEWPORT_PIE_KEYMAPS)


def _is_owned_pie_item(item):
    try:
        identifier = str(getattr(item, 'idname', '') or '')
        return identifier == FBP_OT_CallViewportPie.bl_idname
    except FBP_DATA_IO_ERRORS:
        return False


def _register_keymaps():
    _unregister_keymaps()

    if shortcut_enabled('shortcut_tab_layer_edit'):
        # The operator consumes Tab only for an FBP rig/card and returns
        # PASS_THROUGH for ordinary Blender objects.
        for keymap_name in ('Object Mode', 'Mesh'):
            keymap = addon_keymap(
                keymap_name,
                fallback_space_type='VIEW_3D',
                fallback_region_type='WINDOW',
            )
            if keymap is None:
                continue
            remove_matching_keymap_items(
                keymap,
                lambda item: str(getattr(item, 'idname', '') or '')
                == FBP_OT_ToggleLayerEditMode.bl_idname,
            )
            try:
                item = keymap.keymap_items.new(
                    FBP_OT_ToggleLayerEditMode.bl_idname,
                    type='TAB',
                    value='PRESS',
                )
                _FBP_VIEWPORT_PIE_KEYMAPS.append((keymap, item))
            except FBP_DATA_ERRORS as exc:
                fbp_warn(f'Could not register Frame By Plane Tab shortcut in {keymap_name}', exc)

    if shortcut_enabled('shortcut_viewport_pie'):
        for keymap_name in (
            '3D View',
            'Mesh',
            'Sculpt',
            'Vertex Paint',
            'Image Paint',
            'Grease Pencil',
            'Grease Pencil Edit Mode',
            'Grease Pencil Draw Mode',
            'Grease Pencil Sculpt Mode',
            'Grease Pencil Weight Paint',
            'Grease Pencil Vertex Paint',
        ):
            keymap = addon_keymap(
                keymap_name,
                fallback_space_type='VIEW_3D',
                fallback_region_type='WINDOW',
            )
            if keymap is None:
                continue
            remove_matching_keymap_items(keymap, _is_owned_pie_item)
            try:
                item = keymap.keymap_items.new(
                    FBP_OT_CallViewportPie.bl_idname,
                    type='Z',
                    value='PRESS',
                )
                _FBP_VIEWPORT_PIE_KEYMAPS.append((keymap, item))
            except FBP_DATA_ERRORS as exc:
                fbp_warn(f'Could not register the Frame By Plane Z Pie Menu in {keymap_name}', exc)


def refresh_keymaps():
    """Public hook used by Add-on Preferences after a shortcut toggle changes."""
    return refresh_keymap_registration(_register_keymaps)


def register():
    if bool(getattr(bpy.app, "background", False)):
        return
    register_classes(_CLASSES)
    try:
        _register_cursor_on_camera_runtime()
        _register_keymaps()
    except Exception:
        _unregister_keymaps()
        _unregister_cursor_on_camera_runtime()
        unregister_classes(_CLASSES)
        raise


def unregister():
    _unregister_keymaps()
    _unregister_cursor_on_camera_runtime()
    unregister_classes(_CLASSES)
