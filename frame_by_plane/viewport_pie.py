"""Frame By Plane viewport Pie Menu.

The menu replaces Blender's default Z shading pie while the extension is
active. It keeps the core viewport shading controls and adds compact actions
that work with both ordinary Blender objects and Frame By Plane layers.
"""

import time

import bpy
from bpy.props import BoolProperty, EnumProperty
from bpy.types import Menu, Operator

from .runtime import fbp_warn, FBP_DATA_ERRORS, FBP_DATA_IO_ERRORS


_FBP_VIEWPORT_PIE_KEYMAPS = globals().get("_FBP_VIEWPORT_PIE_KEYMAPS", [])
_QUICK_EFFECT_PREF_NAMES = tuple(f"pie_quick_effect_{index}" for index in range(1, 6))
_QUICK_EFFECT_FALLBACK = (
    ('NONE', "Empty Slot", "Do not show an effect in this quick slot", 'ADD', 0),
)
_QUICK_EFFECT_ENUM_CACHE = globals().get("_QUICK_EFFECT_ENUM_CACHE", [])
_QUICK_EFFECT_ENUM_SIGNATURE = globals().get("_QUICK_EFFECT_ENUM_SIGNATURE", None)
_QUICK_EFFECT_ENUM_REFRESH_TIME = float(globals().get("_QUICK_EFFECT_ENUM_REFRESH_TIME", 0.0) or 0.0)
_QUICK_EFFECT_ENUM_REFRESH_SECONDS = 2.0
_FBP_LAST_LOCKED_RIG_NAMES = globals().get("_FBP_LAST_LOCKED_RIG_NAMES", [])
_FBP_LAST_SELECTABILITY_NAMES = globals().get("_FBP_LAST_SELECTABILITY_NAMES", [])
_FBP_LAST_HIDDEN_OBJECT_NAMES = globals().get("_FBP_LAST_HIDDEN_OBJECT_NAMES", [])

_PIE_ICON_SCALE_X = 1.25
_PIE_ICON_SCALE_Y = 1.25
_PIE_BUTTON_SCALE_Y = 1.25
_PIE_PRIMARY_BUTTON_WIDTH = 6.5


def _pie_icon_cell(layout, *, enabled=True):
    """Create one compact icon cell without adding extra internal spacing."""
    cell = layout.row(align=True)
    cell.scale_x = _PIE_ICON_SCALE_X
    cell.scale_y = _PIE_ICON_SCALE_Y
    cell.enabled = bool(enabled)
    return cell


def _view3d_space(context):
    space = getattr(context, "space_data", None)
    return space if getattr(space, "type", None) == 'VIEW_3D' else None


def _selected_fbp_rigs(context):
    try:
        from .layers import get_selected_fbp_roots
        return list(get_selected_fbp_roots(context))
    except FBP_DATA_ERRORS:
        return []


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
        "holdout_rigs": holdout_rigs,
        "generic_holdout": generic_holdout,
        "holdout_enabled": bool(holdout_rigs or generic_holdout),
        "holdout_active": bool(holdout_states) and all(holdout_states),
    }


def _addon_preferences(context=None):
    try:
        from .properties import fbp_get_addon_preferences
        return fbp_get_addon_preferences(context)
    except FBP_DATA_ERRORS:
        return None


def _quick_effect_enum_items(_self=None, _context=None):
    global _QUICK_EFFECT_ENUM_CACHE
    global _QUICK_EFFECT_ENUM_SIGNATURE
    global _QUICK_EFFECT_ENUM_REFRESH_TIME

    fallback = list(_QUICK_EFFECT_FALLBACK)
    now = time.monotonic()
    if (
        _QUICK_EFFECT_ENUM_CACHE
        and now - _QUICK_EFFECT_ENUM_REFRESH_TIME < _QUICK_EFFECT_ENUM_REFRESH_SECONDS
    ):
        return _QUICK_EFFECT_ENUM_CACHE

    try:
        from .effects_registry import (
            FBP_EFFECT_CROP,
            FBP_EFFECT_EXTEND,
            FBP_EFFECT_REGISTRY,
            fbp_refresh_custom_effect_registry,
        )

        fbp_refresh_custom_effect_registry(force=False)
        category_order = {"MASK": 0, "2D": 1, "BASE": 1, "3D": 2}
        rows = []
        for effect_id, definition in FBP_EFFECT_REGISTRY.items():
            if effect_id in {FBP_EFFECT_CROP, FBP_EFFECT_EXTEND}:
                continue
            if not definition or bool(definition.get("custom_invalid", False)):
                continue
            label = str(definition.get("label", effect_id) or effect_id)
            category = str(definition.get("category", "2D") or "2D").upper()
            if category not in {"MASK", "2D", "BASE", "3D"}:
                continue
            display_category = "2D" if category == "BASE" else category.title()
            icon = str(definition.get("icon", "MODIFIER") or "MODIFIER")
            rows.append(
                (
                    category_order.get(category, 9),
                    label.casefold(),
                    effect_id,
                    display_category,
                    label,
                    icon,
                )
            )
        rows.sort()
        signature = tuple(
            (effect_id, display_category, label, icon)
            for _order, _sort_label, effect_id, display_category, label, icon in rows
        )
        if not _QUICK_EFFECT_ENUM_CACHE or signature != _QUICK_EFFECT_ENUM_SIGNATURE:
            items = list(fallback)
            for enum_index, (
                _order,
                _sort_label,
                effect_id,
                display_category,
                label,
                icon,
            ) in enumerate(rows, start=1):
                items.append(
                    (
                        effect_id,
                        f"{display_category} · {label}",
                        f"Use {label} in this quick slot",
                        icon,
                        enum_index,
                    )
                )
            _QUICK_EFFECT_ENUM_CACHE = items
            _QUICK_EFFECT_ENUM_SIGNATURE = signature
    except FBP_DATA_ERRORS:
        if not _QUICK_EFFECT_ENUM_CACHE:
            _QUICK_EFFECT_ENUM_CACHE = fallback
            _QUICK_EFFECT_ENUM_SIGNATURE = ()

    _QUICK_EFFECT_ENUM_REFRESH_TIME = now
    return _QUICK_EFFECT_ENUM_CACHE


def _store_quick_effect_slot(owner, context, index):
    prefs = _addon_preferences(context)
    if prefs is None:
        return
    attr = f"slot_{index}"
    pref_name = _QUICK_EFFECT_PREF_NAMES[index - 1]
    value = str(getattr(owner, attr, 'NONE') or 'NONE')
    try:
        setattr(prefs, pref_name, "" if value == 'NONE' else value)
    except FBP_DATA_IO_ERRORS:
        pass


def _reset_quick_effect_slots(owner, _context):
    """Clear staged quick slots; saved preferences change only after Apply."""
    if not bool(getattr(owner, "reset_slots", False)):
        return
    for index in range(1, 6):
        setattr(owner, f"slot_{index}", 'NONE')
    owner.reset_slots = False


class FBP_OT_SetViewportShading(Operator):
    bl_idname = "fbp.set_viewport_shading"
    bl_label = "Set Viewport Shading"
    bl_description = "Change the active 3D View shading mode"

    mode: EnumProperty(
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
            if self.mode == 'SOLID':
                shading.color_type = 'MATERIAL'
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


class FBP_OT_QuickEffectsPopup(Operator):
    bl_idname = "fbp.quick_effects_popup"
    bl_label = "Quick Effects"
    bl_description = "Choose up to five favorite Frame By Plane masks or 2D/3D effects"

    slot_1: EnumProperty(
        name="Slot 1",
        items=_quick_effect_enum_items,
        options={'SKIP_SAVE'},
    )
    slot_2: EnumProperty(
        name="Slot 2",
        items=_quick_effect_enum_items,
        options={'SKIP_SAVE'},
    )
    slot_3: EnumProperty(
        name="Slot 3",
        items=_quick_effect_enum_items,
        options={'SKIP_SAVE'},
    )
    slot_4: EnumProperty(
        name="Slot 4",
        items=_quick_effect_enum_items,
        options={'SKIP_SAVE'},
    )
    slot_5: EnumProperty(
        name="Slot 5",
        items=_quick_effect_enum_items,
        options={'SKIP_SAVE'},
    )
    reset_slots: BoolProperty(
        name="Reset",
        description="Clear all five staged quick-effect slots",
        default=False,
        update=_reset_quick_effect_slots,
        options={'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        return _view3d_space(context) is not None

    def invoke(self, context, _event):
        valid_ids = {item[0] for item in _quick_effect_enum_items(self, context)}
        prefs = _addon_preferences(context)
        for index, pref_name in enumerate(_QUICK_EFFECT_PREF_NAMES, start=1):
            stored = str(getattr(prefs, pref_name, "") or "") if prefs is not None else ""
            setattr(self, f"slot_{index}", stored if stored in valid_ids else 'NONE')
        return context.window_manager.invoke_props_dialog(
            self,
            width=520,
            confirm_text="Apply",
        )

    def draw(self, _context):
        layout = self.layout

        slots = layout.column(align=False)
        slots.scale_y = 1.12
        for index in range(1, 6):
            slots.prop(
                self,
                f"slot_{index}",
                text=f"Quick Effect {index}",
            )

        layout.separator()
        footer = layout.row(align=False)
        footer.alignment = 'LEFT'
        footer.prop(
            self,
            "reset_slots",
            text="Reset",
            icon='LOOP_BACK',
            toggle=True,
        )

    def execute(self, context):
        for index in range(1, 6):
            _store_quick_effect_slot(self, context, index)
        return {'FINISHED'}


def _configured_quick_effect_ids(context):
    """Return unique saved quick-effect IDs in stable slot order."""
    prefs = _addon_preferences(context)
    if prefs is None:
        return ()
    effect_ids = []
    seen = set()
    for pref_name in _QUICK_EFFECT_PREF_NAMES:
        effect_id = str(getattr(prefs, pref_name, "") or "").strip()
        if not effect_id or effect_id == 'NONE' or effect_id in seen:
            continue
        seen.add(effect_id)
        effect_ids.append(effect_id)
    return tuple(effect_ids)


class FBP_MT_ViewportPie(Menu):
    bl_idname = "FBP_MT_viewport_pie"
    bl_label = "Viewport"

    def draw(self, context):
        layout = self.layout
        space = _view3d_space(context)
        if space is None:
            layout.label(text="Open this menu from a 3D View")
            return

        pie = layout.menu_pie()
        shading = space.shading
        state = _pie_selection_state(context)
        rigs = state["rigs"]

        # 1 — WEST: Wireframe
        split = pie.split()
        wire_wrap = split.row(align=False)
        wire_wrap.alignment = 'CENTER'
        wire = wire_wrap.row(align=False)
        wire.emboss = 'PIE_MENU'
        wire.scale_y = _PIE_BUTTON_SCALE_Y
        wire.ui_units_x = _PIE_PRIMARY_BUTTON_WIDTH
        op = wire.operator(
            "fbp.set_viewport_shading",
            text="Wireframe",
            icon='SHADING_WIRE',
            depress=shading.type == 'WIREFRAME',
        )
        op.mode = 'WIREFRAME'

        # 2 — EAST: Material Preview
        split = pie.split()
        material_wrap = split.row(align=False)
        material_wrap.alignment = 'CENTER'
        material = material_wrap.row(align=False)
        material.emboss = 'PIE_MENU'
        material.scale_y = _PIE_BUTTON_SCALE_Y
        material.ui_units_x = _PIE_PRIMARY_BUTTON_WIDTH
        op = material.operator(
            "fbp.set_viewport_shading",
            text="Material",
            icon='SHADING_TEXTURE',
            depress=shading.type == 'MATERIAL',
        )
        op.mode = 'MATERIAL'

        # 3 — SOUTH: Hide, Solo, Lock / Selectability, Holdout
        split = pie.split()
        action_col = split.column(align=False)
        action_col.alignment = 'CENTER'

        first_row = action_col.row(align=True)
        first_row.alignment = 'CENTER'
        first_row.emboss = 'NORMAL'

        hide_active = state["hide_active"]
        cell = _pie_icon_cell(first_row, enabled=state["hide_enabled"])
        cell.operator(
            "fbp.toggle_selected_visibility",
            text="",
            icon='HIDE_ON' if hide_active else 'HIDE_OFF',
            depress=hide_active,
        )

        solo_active = space.local_view is not None
        cell = _pie_icon_cell(
            first_row,
            enabled=bool(solo_active or getattr(context, "selected_objects", None)),
        )
        cell.operator(
            "fbp.toggle_local_view_with_lights",
            text="",
            icon='OUTLINER_OB_LIGHT' if solo_active else 'LIGHT',
            depress=solo_active,
        )

        lock_active = state["lock_active"]
        cell = _pie_icon_cell(first_row, enabled=state["lock_enabled"])
        cell.operator(
            "fbp.toggle_selected_lock",
            text="",
            icon='DECORATE_LOCKED' if lock_active else 'DECORATE_UNLOCKED',
            depress=lock_active,
        )

        second_row = action_col.row(align=True)
        second_row.alignment = 'CENTER'
        second_row.emboss = 'NORMAL'

        selectability_locked = state["selectability_locked"]
        cell = _pie_icon_cell(second_row, enabled=state["selectability_enabled"])
        cell.operator(
            "fbp.toggle_selected_selectability",
            text="",
            icon='RESTRICT_SELECT_ON' if selectability_locked else 'RESTRICT_SELECT_OFF',
            depress=selectability_locked,
        )

        holdout_active = state["holdout_active"]
        cell = _pie_icon_cell(second_row, enabled=state["holdout_enabled"])
        cell.operator(
            "fbp.toggle_selected_holdout",
            text="",
            icon='CLIPUV_HLT' if holdout_active else 'CLIPUV_DEHLT',
            depress=holdout_active,
        )

        # 4 — NORTH: Pivot Point icons
        split = pie.split()
        pivot_row = split.row(align=True)
        pivot_row.emboss = 'NORMAL'
        pivot_row.alignment = 'CENTER'
        pivot_row.scale_x = _PIE_ICON_SCALE_X
        pivot_row.scale_y = _PIE_ICON_SCALE_Y
        tool_settings = context.tool_settings
        pivot_row.prop_enum(
            tool_settings,
            "transform_pivot_point",
            'CURSOR',
            text="",
            icon='PIVOT_CURSOR',
        )
        pivot_row.prop_enum(
            tool_settings,
            "transform_pivot_point",
            'MEDIAN_POINT',
            text="",
            icon='PIVOT_MEDIAN',
        )
        pivot_row.prop_enum(
            tool_settings,
            "transform_pivot_point",
            'INDIVIDUAL_ORIGINS',
            text="",
            icon='PIVOT_INDIVIDUAL',
        )

        # 5 — NORTH-WEST: Flat, Random + Texture, and Solid
        split = pie.split()
        col = split.column(align=False)

        flat_active = shading.type == 'SOLID' and shading.light == 'FLAT'
        flat_wrap = col.row(align=False)
        flat_wrap.alignment = 'CENTER'
        flat = flat_wrap.row(align=False)
        flat.emboss = 'NORMAL'
        flat.scale_y = _PIE_BUTTON_SCALE_Y
        flat.operator(
            "fbp.toggle_flat_viewport_lighting",
            text="Flat",
            icon='AREA_DOCK',
            depress=flat_active,
        )

        texture_active = shading.type == 'SOLID' and shading.color_type == 'TEXTURE'
        random_active = shading.type == 'SOLID' and shading.color_type == 'RANDOM'

        tex_rand_row = col.row(align=True)
        tex_rand_row.emboss = 'NORMAL'
        tex_rand_row.alignment = 'CENTER'
        tex_rand_row.scale_y = _PIE_BUTTON_SCALE_Y
        tex_rand_row.operator(
            "fbp.toggle_random_viewport_color",
            text="Random",
            icon='GEOMETRY_SET',
            depress=random_active,
        )
        tex_rand_row.operator(
            "fbp.set_texture_viewport_shading",
            text="Texture",
            icon='FILE_IMAGE' if texture_active else 'SEQ_PREVIEW',
            depress=texture_active,
        )

        solid_wrap = col.row(align=False)
        solid_wrap.alignment = 'CENTER'
        solid = solid_wrap.row(align=False)
        solid.emboss = 'PIE_MENU'
        solid.scale_y = _PIE_BUTTON_SCALE_Y
        solid.ui_units_x = _PIE_PRIMARY_BUTTON_WIDTH
        op = solid.operator(
            "fbp.set_viewport_shading",
            text="Solid",
            icon='SHADING_SOLID',
            depress=shading.type == 'SOLID' and shading.color_type == 'MATERIAL',
        )
        op.mode = 'SOLID'

        # 6 — NORTH-EAST: Transparent above Rendered + Viewport Compositor
        split = pie.split()
        render_col = split.column(align=False)
        render_col.alignment = 'CENTER'

        render = getattr(context.scene, "render", None)
        transparent_enabled = bool(
            render is not None
            and hasattr(render, "film_transparent")
            and render.film_transparent
        )
        transparent_wrap = render_col.row(align=False)
        transparent_wrap.alignment = 'CENTER'
        transparent = transparent_wrap.row(align=False)
        transparent.emboss = 'NORMAL'
        transparent.scale_y = _PIE_BUTTON_SCALE_Y
        transparent.enabled = bool(render and hasattr(render, "film_transparent"))
        transparent.operator(
            "fbp.toggle_render_transparency",
            text="Transparent",
            icon='TEXTURE',
            depress=transparent_enabled,
        )

        main_row = render_col.row(align=False)
        main_row.alignment = 'CENTER'

        rendered = main_row.row(align=False)
        rendered.emboss = 'PIE_MENU'
        rendered.scale_y = _PIE_BUTTON_SCALE_Y
        rendered.ui_units_x = _PIE_PRIMARY_BUTTON_WIDTH
        op = rendered.operator(
            "fbp.set_viewport_shading",
            text="Rendered",
            icon='SHADING_RENDERED',
            depress=shading.type == 'RENDERED',
        )
        op.mode = 'RENDERED'

        compositor_enabled = bool(
            hasattr(shading, "use_compositor")
            and shading.use_compositor == 'ALWAYS'
        )
        cell = _pie_icon_cell(
            main_row,
            enabled=hasattr(shading, "use_compositor"),
        )
        cell.emboss = 'NORMAL'
        cell.operator(
            "fbp.toggle_viewport_compositor",
            text="",
            icon='CAMERA_STEREO',
            depress=compositor_enabled,
        )

        # 7 — SOUTH-WEST: Mask library
        split = pie.split()
        mask_wrap = split.row(align=False)
        mask_wrap.alignment = 'CENTER'
        mask = mask_wrap.row(align=False)
        mask.emboss = 'NORMAL'
        mask.scale_y = _PIE_BUTTON_SCALE_Y
        mask.enabled = bool(rigs)
        op = mask.operator(
            "wm.call_menu",
            text="Mask",
            icon='SURFACE_NCURVE',
        )
        op.name = "FBP_MT_object_masks"

        # 8 — SOUTH-EAST: Crop, Expand and Quick Effects
        split = pie.split()
        col = split.column(align=False)
        col.emboss = 'NORMAL'

        try:
            from .effects_registry import (
                fbp_effect_definition,
                fbp_effect_supported_for_rig,
            )
        except FBP_DATA_ERRORS:
            fbp_effect_definition = None
            fbp_effect_supported_for_rig = None

        quick_effects = []
        if fbp_effect_definition is not None:
            for effect_id in _configured_quick_effect_ids(context):
                definition = fbp_effect_definition(effect_id) or {}
                if not definition or bool(definition.get("custom_invalid", False)):
                    continue
                quick_effects.append((effect_id, definition))

        # Pie sectors expand around their anchor. Reserving one invisible row above
        # for every configured effect keeps Crop/Expand fixed and makes the visible
        # list grow downward instead of climbing upward.
        for _effect_id, _definition in quick_effects:
            spacer = col.row(align=False)
            spacer.scale_y = _PIE_BUTTON_SCALE_Y
            spacer.label(text="")

        effects_col = col.column(align=False)
        effects_col.scale_y = _PIE_BUTTON_SCALE_Y
        effects_col.enabled = bool(rigs)
        effects_col.operator(
            "fbp.popup_crop",
            text="Crop",
            icon='FULLSCREEN_EXIT',
        )
        effects_col.operator(
            "fbp.popup_extend",
            text="Expand",
            icon='FULLSCREEN_ENTER',
        )

        for effect_id, definition in quick_effects:
            label = str(definition.get("label", effect_id) or effect_id)
            icon = str(definition.get("icon", "MODIFIER") or "MODIFIER")
            effect_row = effects_col.row(align=False)
            effect_row.enabled = bool(
                rigs
                and fbp_effect_supported_for_rig is not None
                and any(
                    fbp_effect_supported_for_rig(rig, effect_id)
                    for rig in rigs
                )
            )
            op = effect_row.operator(
                "fbp.add_effect",
                text=label,
                icon=icon,
            )
            op.effect_id = effect_id

        quick_row = col.row(align=False)
        quick_row.alignment = 'CENTER'
        cell = _pie_icon_cell(quick_row)
        cell.emboss = 'NORMAL'
        cell.operator(
            "fbp.quick_effects_popup",
            text="",
            icon='COLLAPSEMENU',
        )

_CLASSES = (
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
    FBP_OT_QuickEffectsPopup,
    FBP_MT_ViewportPie,
)


def _unregister_keymaps():
    while _FBP_VIEWPORT_PIE_KEYMAPS:
        km, kmi = _FBP_VIEWPORT_PIE_KEYMAPS.pop()
        try:
            km.keymap_items.remove(kmi)
        except FBP_DATA_IO_ERRORS:
            pass


def _remove_stale_pie_keymaps(keymap):
    """Remove exact stale addon entries left by an interrupted hot reload."""
    for item in tuple(getattr(keymap, "keymap_items", ()) or ()):
        try:
            if item.idname != 'wm.call_menu_pie':
                continue
            if str(getattr(item.properties, "name", "") or "") != FBP_MT_ViewportPie.bl_idname:
                continue
            keymap.keymap_items.remove(item)
        except FBP_DATA_IO_ERRORS:
            continue


def _register_keymaps():
    _unregister_keymaps()
    wm = getattr(bpy.context, "window_manager", None)
    keyconfigs = getattr(wm, "keyconfigs", None) if wm else None
    addon_config = getattr(keyconfigs, "addon", None) if keyconfigs else None
    if addon_config is None:
        return
    default_config = getattr(keyconfigs, "default", None)
    for keymap_name in ('3D View', 'Mesh', 'Sculpt', 'Vertex Paint', 'Image Paint'):
        try:
            reference = default_config.keymaps.get(keymap_name) if default_config else None
            space_type = getattr(reference, "space_type", 'VIEW_3D') or 'VIEW_3D'
            region_type = getattr(reference, "region_type", 'WINDOW') or 'WINDOW'
            km = addon_config.keymaps.new(
                name=keymap_name,
                space_type=space_type,
                region_type=region_type,
            )
            _remove_stale_pie_keymaps(km)
            kmi = km.keymap_items.new('wm.call_menu_pie', type='Z', value='PRESS')
            kmi.properties.name = FBP_MT_ViewportPie.bl_idname
            _FBP_VIEWPORT_PIE_KEYMAPS.append((km, kmi))
        except FBP_DATA_ERRORS as exc:
            fbp_warn(
                f"Could not register the Frame By Plane Z Pie Menu in {keymap_name}",
                exc,
            )


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    _register_keymaps()


def unregister():
    _unregister_keymaps()
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except FBP_DATA_IO_ERRORS:
            pass