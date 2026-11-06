"""Blender Modifiers panel integration for Frame By Plane effects.

Mesh effects are real Geometry Nodes modifiers on the layer plane. This module
makes Blender's own Modifiers panel a first-class editor for them:

* ``Add Modifier > Mesh`` lists the Frame By Plane mesh effects;
* the Properties editor follows the selected layer onto its plane, because the
  plane itself is not selectable and Blender only lists the active object;
* native reorder, eye/camera toggles and delete are mirrored back into the
  Frame By Plane stack, so both editors always show the same order.

Frame By Plane rows are layers (top = evaluated last) while Blender modifiers
evaluate top to bottom, so the native list is the reversed Frame By Plane stack.
"""

from __future__ import annotations

import bpy
from bpy.types import Menu

from .runtime import FBP_DATA_ERRORS, fbp_undo_guard_active, fbp_warn
from .registration import (
    append_handler_once,
    register_classes,
    remove_handlers_by_name,
    unregister_classes,
)


_MODULE_SUFFIX = "native_modifiers"
_MESH_MENU_LABEL = "Mesh"
_MESH_MENU_ICON = "MESH_MONKEY"
_MASK_MENU_LABEL = "Mask"
_MASK_MENU_ICON = "MOD_MASK"
_IMAGE_MENU_LABEL = "Image"
_IMAGE_MENU_ICON = "IMAGE_DATA"

# rig pointer -> {token: (modifier pointer, viewport, render)}
_SNAPSHOTS = {}
# rig pointer -> shell tokens, and -> plane modifier signature
_SHELL_SNAPSHOTS = {}
_SIGNATURES = {}
# Properties spaces pinned by Frame By Plane, by space pointer, and spaces
# whose pin the artist turned off (kept until another layer is selected).
_AUTO_PINNED = {}
_RELEASED = {}
_SYNCING = False
_MSGBUS_OWNER = object()


def _geo():
    from . import geometry_nodes
    return geometry_nodes


# --------------------------------------------------------------------------
# Modifier <-> stack token mapping
# --------------------------------------------------------------------------

def fbp_native_modifier_token(rig, modifier):
    """Return the Frame By Plane stack token represented by one modifier."""
    geo = _geo()
    if modifier is None or getattr(modifier, "type", "") != "NODES":
        return ""
    try:
        from .effect_shells import fbp_shell_token
        shell = fbp_shell_token(modifier)
        if shell:
            return shell
    except ImportError:
        pass
    stage = geo._fbp_mixed_shader_stage_token(modifier)
    if stage:
        return "" if stage == geo._FBP_MIXED_SHADER_STAGE_BASE else stage
    effect_id = geo._fbp_geometry_effect_id_for_modifier(modifier)
    if not effect_id:
        return ""
    instance_id = ""
    if geo._fbp_effect_uses_multi_instances(effect_id):
        try:
            from .effect_schema import effect_instance_id
            instance_id = str(effect_instance_id(modifier) or "")
        except (ImportError, *FBP_DATA_ERRORS):
            instance_id = ""
    return geo._fbp_effect_ref(effect_id, instance_id)


def fbp_native_modifier_entries(rig):
    """Return ``(token, modifier)`` pairs in Blender's modifier order.

    When a token is represented twice (a shell and a mixed-stack stage), the
    shell wins: it is the row the artist edits.
    """
    geo = _geo()
    plane = geo._fbp_plane(rig, repair=False)
    if plane is None:
        return ()
    entries = []
    try:
        modifiers = tuple(plane.modifiers)
    except FBP_DATA_ERRORS:
        return ()
    shell_tokens = set()
    try:
        from .effect_shells import fbp_shell_token
        shell_tokens = {fbp_shell_token(item) for item in modifiers} - {""}
    except ImportError:
        pass
    for modifier in modifiers:
        token = fbp_native_modifier_token(rig, modifier)
        if not token:
            continue
        is_stage = bool(geo._fbp_mixed_shader_stage_token(modifier))
        if is_stage and token in shell_tokens:
            continue
        entries.append((token, modifier))
    return tuple(entries)


def fbp_native_ui_order(rig):
    """Return represented tokens in Frame By Plane UI order (top first)."""
    seen = []
    for token, _modifier in reversed(fbp_native_modifier_entries(rig)):
        if token not in seen:
            seen.append(token)
    return seen


def _rig_key(rig):
    try:
        return int(rig.as_pointer())
    except FBP_DATA_ERRORS:
        return 0


def _modifier_state(modifier):
    try:
        return (
            int(modifier.as_pointer()),
            bool(modifier.show_viewport),
            bool(modifier.show_render),
        )
    except FBP_DATA_ERRORS:
        return (0, True, True)


def fbp_native_snapshot(rig):
    """Return ``{token: (pointer, viewport, render)}`` of the native rows."""
    snapshot = {}
    for token, modifier in fbp_native_modifier_entries(rig):
        snapshot.setdefault(token, _modifier_state(modifier))
    return snapshot


def fbp_native_hide_inputs(rig):
    """Hide the inputs of the internal mixed-stack stage rows.

    Stages only carry the material an image effect hands to the next mesh
    effect; nothing in them is meant to be edited. Effect rows keep every
    input: they are the effect's controls.
    """
    changed = False
    geo = _geo()
    plane = geo._fbp_plane(rig, repair=False)
    if plane is None:
        return False
    try:
        stages = tuple(geo._fbp_mixed_shader_stage_modifiers(plane))
    except FBP_DATA_ERRORS:
        return False
    for modifier in stages:
        group = getattr(modifier, "node_group", None)
        if group is None:
            continue
        try:
            for item in group.interface.items_tree:
                if (
                    getattr(item, "item_type", "") == "SOCKET"
                    and getattr(item, "in_out", "") == "INPUT"
                    and getattr(item, "socket_type", "") != "NodeSocketGeometry"
                    and not bool(getattr(item, "hide_in_modifier", True))
                ):
                    item.hide_in_modifier = True
                    changed = True
        except FBP_DATA_ERRORS:
            continue
    # A short-lived build hid the effect rows' inputs too: show them again.
    stage_pointers = {int(item.as_pointer()) for item in stages}
    for _token, modifier in fbp_native_modifier_entries(rig):
        if int(modifier.as_pointer()) in stage_pointers:
            continue
        group = getattr(modifier, "node_group", None)
        try:
            for item in (group.interface.items_tree if group is not None else ()):
                if (
                    getattr(item, "item_type", "") == "SOCKET"
                    and getattr(item, "in_out", "") == "INPUT"
                    and bool(getattr(item, "hide_in_modifier", False))
                ):
                    item.hide_in_modifier = False
                    changed = True
        except FBP_DATA_ERRORS:
            continue
    return changed


def fbp_native_remember(rig):
    key = _rig_key(rig)
    if not key:
        return
    try:
        fbp_native_hide_inputs(rig)
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not hide effect inputs in the Modifiers panel", exc)
    _SNAPSHOTS[key] = fbp_native_snapshot(rig)
    try:
        from .effect_shells import fbp_shell_modifiers
        _SHELL_SNAPSHOTS[key] = tuple(token for token, _modifier in fbp_shell_modifiers(rig))
    except ImportError:
        _SHELL_SNAPSHOTS[key] = ()
    plane = _geo()._fbp_plane(rig, repair=False)
    if plane is not None:
        _SIGNATURES[key] = _plane_signature(plane)


def fbp_native_forget_all():
    _SNAPSHOTS.clear()
    _SHELL_SNAPSHOTS.clear()
    _SIGNATURES.clear()


# --------------------------------------------------------------------------
# Native -> Frame By Plane synchronization
# --------------------------------------------------------------------------

def _visibility_is_perf_gated(geo, rig, effect_id):
    """Heavy inert modifiers are muted by Frame By Plane, not by the artist."""
    try:
        return not geo._fbp_geometry_effect_has_visible_work(rig, effect_id)
    except FBP_DATA_ERRORS:
        return False


def _fbp_state_flags(geo, rig, token):
    effect_id, instance_id = geo._fbp_effect_ref_parts(token)
    try:
        viewport = bool(geo.fbp_effect_visible_state(rig, effect_id, instance_id))
    except FBP_DATA_ERRORS:
        viewport = True
    try:
        render = bool(geo.fbp_effect_render_visible_state(rig, effect_id, instance_id))
    except FBP_DATA_ERRORS:
        render = True
    return viewport, render


def _remove_token(geo, rig, token):
    effect_id, instance_id = geo._fbp_effect_ref_parts(token)
    if instance_id and geo._fbp_effect_uses_multi_instances(effect_id):
        return bool(geo.fbp_remove_effect_instance(rig, effect_id, instance_id, sync_items=False))
    return bool(geo.fbp_remove_effect(rig, effect_id, sync_items=False))


def _is_shader(geo, token):
    """True for rows that only represent an effect: image effects, masks and
    the layer effects (Crop, Emission...) that have no modifier of their own."""
    effect_id = geo._fbp_effect_ref_effect_id(token)
    return geo.fbp_effect_definition(effect_id).get("kind") in {"SHADER", "BASE"}


def fbp_sync_native_modifiers(rig):
    """Mirror artist edits made in Blender's Modifiers panel into the stack.

    Frame By Plane keeps its modifiers consistent with the stack, so whatever
    disagrees with the stack was done natively: an order that differs, a mesh
    effect whose eye differs from its stored visibility, a duplicated or
    missing row. Image-effect rows (mixed-stack stages and shells) only
    *represent* a shader effect, so their eye/camera icons are compared with
    the last snapshot to tell an artist click from a Frame By Plane change.
    """
    global _SYNCING
    geo = _geo()
    report = {"removed": [], "reordered": False, "visibility": [], "duplicates": 0}
    if rig is None or _SYNCING:
        return report
    key = _rig_key(rig)
    previous = _SNAPSHOTS.get(key, {})
    plane = geo._fbp_plane(rig, repair=False)
    if plane is None:
        return report
    _SYNCING = True
    try:
        # 1. Native duplicates of an owned effect break the one-modifier
        # contract. Keep the row Frame By Plane knew, drop the copy.
        by_token = {}
        for token, modifier in fbp_native_modifier_entries(rig):
            by_token.setdefault(token, []).append(modifier)
        for token, modifiers in by_token.items():
            if len(modifiers) < 2:
                continue
            known = previous.get(token, (0, True, True))[0]
            keep = next(
                (item for item in modifiers if int(item.as_pointer()) == known),
                modifiers[0],
            )
            for modifier in modifiers:
                if modifier == keep:
                    continue
                try:
                    plane.modifiers.remove(modifier)
                    report["duplicates"] += 1
                except FBP_DATA_ERRORS:
                    pass
        if report["duplicates"]:
            _notify(
                "Frame By Plane effects are duplicated from the Frame By Plane "
                "stack; the native copy was removed"
            )

        # 2. Native delete: a row seen before, still in the stack, now gone.
        # Image rows only count while the stack keeps its mixed pipeline,
        # because Frame By Plane drops every stage when it stops being mixed.
        persisted_set = set(geo._fbp_mixed_effect_tokens(rig))
        represented = {token for token, _modifier in fbp_native_modifier_entries(rig)}
        shells = set()
        try:
            from .effect_shells import fbp_shell_modifiers
            shells = {token for token, _modifier in fbp_shell_modifiers(rig)}
        except ImportError:
            pass
        mixed_active = any(
            geo._fbp_mixed_shader_stage_token(item) for item in plane.modifiers
        )
        previous_shells = set(_SHELL_SNAPSHOTS.get(key, ()))
        applied = _applied_image_modifier(plane)
        if applied and any(
            token not in shells and token in persisted_set and _is_shader(geo, token)
            for token in previous_shells
        ):
            # Apply on an image-effect row would just drop the effect: the
            # row carries no geometry. Undo it and open Apply Effects instead.
            _redirect_apply_to_bake(rig.name)
            return report
        for token in previous:
            if token in represented:
                continue
            if not _is_shader(geo, token):
                # The stack already dropped the missing mesh effect from its
                # live order. Still enabled = deleted natively, not by the
                # stack: removing it also clears its stored settings.
                effect_id = geo._fbp_effect_ref_effect_id(token)
                if token in persisted_set or geo._fbp_is_enabled(rig, effect_id):
                    _remove_token(geo, rig, token)
                    report["removed"].append(token)
                continue
            if token in persisted_set and (token in previous_shells or mixed_active):
                if _remove_token(geo, rig, token):
                    report["removed"].append(token)
        if report["removed"]:
            geo._fbp_sync_mixed_effect_pipeline(rig)

        # 3. Native reorder: place the represented rows, in their native
        # order, into the slots they occupy in the stack.
        # The stack already adopts the live order of mesh modifiers, so the
        # native order is compared with the previous snapshot instead.
        persisted = list(geo._fbp_mixed_effect_tokens(rig))
        native = fbp_native_ui_order(rig)
        native_set = set(native)
        before = [token for token in reversed(tuple(previous)) if token in native_set]
        after = [token for token in native if token in set(before)]
        slots = [index for index, token in enumerate(persisted) if token in native_set]
        if (
            before != after
            and len(slots) == len(native)
            and {persisted[index] for index in slots} == native_set
        ):
            desired = list(persisted)
            for slot, token in zip(slots, native):
                desired[slot] = token
            if geo._fbp_apply_mixed_effect_order(rig, desired):
                report["reordered"] = True

        # 4. Native eye / camera toggles.
        for token, modifier in fbp_native_modifier_entries(rig):
            pointer, viewport, render = _modifier_state(modifier)
            effect_id, instance_id = geo._fbp_effect_ref_parts(token)
            if _is_shader(geo, token):
                old = previous.get(token)
                if old is None or old[0] != pointer:
                    continue
                changes = (
                    ("VIEWPORT", viewport, old[1], geo.fbp_set_effect_visible),
                    ("RENDER", render, old[2], geo.fbp_set_effect_render_visible),
                )
                for label, value, old_value, setter in changes:
                    if value != old_value:
                        setter(rig, effect_id, value, instance_id)
                        report["visibility"].append((token, label, value))
                continue
            gated = _visibility_is_perf_gated(geo, rig, effect_id)
            stored_viewport = bool(geo._fbp_stored_effect_visibility(rig, effect_id, True))
            stored_render = bool(geo._fbp_stored_effect_render_visibility(rig, effect_id, True))
            if viewport != stored_viewport and not (gated and not viewport):
                geo.fbp_set_effect_visible(rig, effect_id, viewport, instance_id)
                report["visibility"].append((token, "VIEWPORT", viewport))
            if render != stored_render and not (gated and not render):
                geo.fbp_set_effect_render_visible(rig, effect_id, render, instance_id)
                report["visibility"].append((token, "RENDER", render))

        try:
            from .effect_shells import fbp_shell_ensure, fbp_shell_maintain
            # Every image effect and mask lives in Modifiers: new ones from
            # any Add path (menus, pie, presets, paste) get their row here.
            fbp_shell_ensure(rig)
            fbp_shell_maintain(rig)
        except ImportError:
            pass
        _mirror_stack_flags(geo, rig)
        if report["removed"] or report["reordered"] or report["visibility"] or report["duplicates"]:
            try:
                geo.fbp_sync_effect_items(rig)
            except FBP_DATA_ERRORS as exc:
                fbp_warn("Could not refresh the effect stack after a Modifiers edit", exc)
    finally:
        _SYNCING = False
        fbp_native_remember(rig)
    return report


_HANDLED_APPLY = set()


def _applied_image_modifier(plane):
    """Name of the modifier the last operator applied on ``plane``, if any."""
    try:
        operators = bpy.context.window_manager.operators
        last = operators[-1] if len(operators) else None
    except (AttributeError, IndexError, *FBP_DATA_ERRORS):
        return ""
    if last is None or str(getattr(last, "bl_idname", "")) != "OBJECT_OT_modifier_apply":
        return ""
    try:
        pointer = int(last.as_pointer())
    except FBP_DATA_ERRORS:
        return ""
    if pointer in _HANDLED_APPLY:
        return ""
    _HANDLED_APPLY.add(pointer)
    try:
        return str(last.properties.modifier or "") or "?"
    except (AttributeError, *FBP_DATA_ERRORS):
        return "?"


def _redirect_apply_to_bake(rig_name):
    def _run():
        context = bpy.context
        window = getattr(context, "window", None) or next(
            iter(getattr(context.window_manager, "windows", ()) or ()), None
        )
        if window is None:
            return None
        try:
            with context.temp_override(window=window):
                bpy.ops.ed.undo()
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not undo Apply on an image effect", exc)
            return None
        rig = bpy.data.objects.get(rig_name)
        if rig is None:
            return None
        try:
            area = next(
                (item for item in window.screen.areas if item.type in {"PROPERTIES", "VIEW_3D"}),
                None,
            )
            override = {"window": window}
            if area is not None:
                override["area"] = area
                override["region"] = next(
                    (region for region in area.regions if region.type == "WINDOW"), None
                )
            with context.temp_override(**override):
                bpy.ops.fbp.apply_image_effects("INVOKE_DEFAULT", rig_name=rig_name)
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not open Apply Effects", exc)
        return None

    try:
        from .safe_tasks import schedule_once
        schedule_once("native_modifiers.apply_redirect", _run, first_interval=0.0)
    except (ImportError, *FBP_DATA_ERRORS):
        bpy.app.timers.register(_run, first_interval=0.0)


def _mirror_stack_flags(geo, rig):
    """Show Frame By Plane image-effect visibility on stage and shell rows."""
    changed = False
    for token, modifier in fbp_native_modifier_entries(rig):
        if not _is_shader(geo, token):
            continue
        viewport, render = _fbp_state_flags(geo, rig, token)
        try:
            if bool(modifier.show_viewport) != viewport:
                modifier.show_viewport = viewport
                changed = True
            if bool(modifier.show_render) != render:
                modifier.show_render = render
                changed = True
        except FBP_DATA_ERRORS:
            continue
    return changed


def fbp_native_after_stack_change(rig):
    """Called after Frame By Plane changed a stack from its own panel."""
    if _SYNCING or rig is None or _playing_or_rendering():
        return
    fbp_sync_native_modifiers(rig)


def _plane_signature(plane):
    try:
        return tuple(
            (int(item.as_pointer()), item.name, bool(item.show_viewport), bool(item.show_render))
            for item in plane.modifiers
        )
    except FBP_DATA_ERRORS:
        return ()


def _notify(message):
    fbp_warn(message)
    if bool(getattr(bpy.app, "background", False)):
        return

    def draw(menu, _context):
        menu.layout.label(text=message, icon="INFO")
    try:
        wm = bpy.context.window_manager
        wm.popup_menu(draw, title="Frame By Plane", icon="MODIFIER")
    except FBP_DATA_ERRORS:
        pass


def _playing_or_rendering():
    try:
        if bpy.app.is_job_running("RENDER"):
            return True
    except FBP_DATA_ERRORS:
        pass
    try:
        screen = getattr(bpy.context, "screen", None)
        return bool(screen and screen.is_animation_playing)
    except FBP_DATA_ERRORS:
        return False


_PENDING_RIGS = set()
# Layers whose plane geometry changed: their modifier inputs and layer
# settings are compared (and written) from the deferred task, never from the
# depsgraph callback itself.
_PENDING_VALUE_RIGS = set()


def _sync_modifier_values(rig):
    try:
        from .effect_shells import fbp_shell_sync_values
        from .geometry_nodes import fbp_pull_geometry_modifier_edits
        fbp_shell_sync_values(rig)
        # Mesh effects: inputs edited in the Modifiers panel.
        fbp_pull_geometry_modifier_edits(rig)
    except (ImportError, *FBP_DATA_ERRORS) as exc:
        fbp_warn("Could not sync an effect modifier with its layer", exc)


def _run_pending_sync():
    value_names = tuple(_PENDING_VALUE_RIGS)
    _PENDING_VALUE_RIGS.clear()
    names = tuple(_PENDING_RIGS)
    _PENDING_RIGS.clear()
    if fbp_undo_guard_active():
        return None
    for name in value_names:
        rig = bpy.data.objects.get(name)
        if rig is not None:
            _sync_modifier_values(rig)
    for name in names:
        rig = bpy.data.objects.get(name)
        if rig is None:
            continue
        try:
            fbp_sync_native_modifiers(rig)
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not apply a Modifiers panel edit to the effect stack", exc)
    return None


@bpy.app.handlers.persistent
def fbp_native_modifiers_depsgraph_post(_scene, depsgraph):
    """Note which layers changed; every write runs later from a safe task.

    Writing layer settings here runs their RNA update callbacks inside
    depsgraph_update_post. Those callbacks can rebuild cages, node groups and
    helper objects, which leaves the same update list pointing at freed data
    for every handler that runs after this one (another add-on reading
    ``update.id`` then crashes Blender). So this callback only reads.
    """
    if _SYNCING or _playing_or_rendering() or fbp_undo_guard_active():
        return
    try:
        updates = tuple(depsgraph.updates)
    except FBP_DATA_ERRORS:
        return
    found = False
    for update in updates:
        obj = getattr(update, "id", None)
        if not isinstance(obj, bpy.types.Object):
            continue
        # Modifier input edits and stack changes tag geometry; a plain move
        # or a material edit does not, so it has nothing to sync here.
        if not bool(getattr(update, "is_updated_geometry", True)):
            continue
        obj = getattr(obj, "original", obj)
        if not bool(getattr(obj, "is_fbp_plane", False)):
            continue
        from .layers import fbp_resolve_rig_from_any_object
        rig = fbp_resolve_rig_from_any_object(obj)
        if rig is None:
            continue
        _PENDING_VALUE_RIGS.add(rig.name)
        found = True
        if _SIGNATURES.get(_rig_key(rig)) != _plane_signature(obj):
            _PENDING_RIGS.add(rig.name)
    if found:
        # If the task cannot be scheduled now (Undo, paused timers) the names
        # stay pending and the next update schedules them; never run inline.
        try:
            from .safe_tasks import schedule_once
            schedule_once("native_modifiers.sync", _run_pending_sync, first_interval=0.0)
        except (ImportError, *FBP_DATA_ERRORS) as exc:
            fbp_warn("Could not schedule a Modifiers panel sync", exc)


@bpy.app.handlers.persistent
def fbp_native_modifiers_reset(*_args):
    """Undo, redo and file loads restore a consistent state: re-snapshot."""
    fbp_native_forget_all()
    _PENDING_RIGS.clear()
    _PENDING_VALUE_RIGS.clear()
    _AUTO_PINNED.clear()
    _RELEASED.clear()
    _subscribe_msgbus()
    # A loaded file keeps its active layer: nothing else asks the Modifiers
    # tab to show its plane (the Frame By Plane section used to, when drawn).
    if not bool(getattr(bpy.app, "background", False)):
        _deferred_follow()


# --------------------------------------------------------------------------
# Properties editor follows the selected layer onto its plane
# --------------------------------------------------------------------------

def _follow_enabled(context=None):
    context = context or bpy.context
    try:
        from .interface_preferences import fbp_get_addon_preferences
        prefs = fbp_get_addon_preferences(context)
    except (ImportError, *FBP_DATA_ERRORS):
        prefs = None
    return bool(getattr(prefs, "modifiers_follow_layer", True)) if prefs else True


def _layer_plane(obj):
    if obj is None:
        return None, None
    try:
        from .layers import fbp_resolve_rig_from_any_object
        rig = fbp_resolve_rig_from_any_object(obj)
    except (ImportError, *FBP_DATA_ERRORS):
        return None, None
    if rig is None:
        return None, None
    plane = _geo()._fbp_plane(rig, repair=False)
    return rig, plane


def fbp_follow_properties_pins(context=None):
    """Pin Modifiers tabs to the active layer's plane and release our pins."""
    context = context or bpy.context
    wm = getattr(context, "window_manager", None)
    if wm is None:
        return False
    enabled = _follow_enabled(context)
    changed = False
    for window in tuple(getattr(wm, "windows", ()) or ()):
        try:
            view_layer = window.view_layer
            active = view_layer.objects.active if view_layer else None
            screen = window.screen
        except FBP_DATA_ERRORS:
            continue
        rig, plane = _layer_plane(active)
        for area in tuple(getattr(screen, "areas", ()) or ()):
            if area.type != "PROPERTIES":
                continue
            space = area.spaces.active
            key = int(space.as_pointer())
            ours = key in _AUTO_PINNED
            if ours and not space.use_pin_id:
                # The artist clicked the pin off: respect it for this layer.
                _RELEASED[key] = _AUTO_PINNED.pop(key)
                ours = False
            if _RELEASED.get(key) and _RELEASED[key] != getattr(plane, "name", ""):
                _RELEASED.pop(key, None)
            wants = bool(
                enabled and plane is not None and space.context == "MODIFIER"
                and _RELEASED.get(key) != plane.name
            )
            try:
                if wants and (ours or not space.use_pin_id):
                    if space.pin_id != plane or not space.use_pin_id:
                        space.pin_id = plane
                        space.use_pin_id = True
                        area.tag_redraw()
                        changed = True
                    _AUTO_PINNED[key] = plane.name
                elif ours and not wants:
                    # Leave an artist pin alone: only release the one we set.
                    if space.use_pin_id and getattr(space.pin_id, "name", "") == _AUTO_PINNED[key]:
                        space.use_pin_id = False
                        space.pin_id = None
                        area.tag_redraw()
                        changed = True
                    _AUTO_PINNED.pop(key, None)
            except FBP_DATA_ERRORS:
                _AUTO_PINNED.pop(key, None)
    return changed


def _deferred_follow(*_args):
    def run():
        try:
            fbp_follow_properties_pins()
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not update the Modifiers tab for the selected layer", exc)
        return None
    try:
        bpy.app.timers.register(run, first_interval=0.0)
    except FBP_DATA_ERRORS:
        pass


def fbp_request_properties_follow():
    """Called from panel drawing: a pin cannot change inside ``draw()``."""
    if _follow_enabled():
        _deferred_follow()


def _subscribe_msgbus():
    try:
        bpy.msgbus.clear_by_owner(_MSGBUS_OWNER)
        bpy.msgbus.subscribe_rna(
            key=(bpy.types.LayerObjects, "active"),
            owner=_MSGBUS_OWNER, args=(), notify=_deferred_follow,
        )
        bpy.msgbus.subscribe_rna(
            key=(bpy.types.SpaceProperties, "context"),
            owner=_MSGBUS_OWNER, args=(), notify=_deferred_follow,
        )
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not watch layer selection for the Modifiers tab", exc)


def _release_all_pins():
    try:
        wm = bpy.context.window_manager
    except FBP_DATA_ERRORS:
        return
    for window in tuple(getattr(wm, "windows", ()) or ()):
        for area in tuple(getattr(window.screen, "areas", ()) or ()):
            if area.type != "PROPERTIES":
                continue
            space = area.spaces.active
            key = int(space.as_pointer())
            if key in _AUTO_PINNED:
                try:
                    space.use_pin_id = False
                    space.pin_id = None
                except FBP_DATA_ERRORS:
                    pass
    _AUTO_PINNED.clear()


# --------------------------------------------------------------------------
# Add Modifier > Mesh
# --------------------------------------------------------------------------

def _context_layer(context):
    rig, plane = _layer_plane(getattr(context, "object", None))
    return rig, plane


def _item_icon_kwargs(effect_id, fallback="MODIFIER"):
    """Frame By Plane effect artwork when there is one, else its Blender icon."""
    from .ui_icons import effect_icon_kwargs
    definition = _geo().fbp_effect_definition(effect_id) or {}
    return effect_icon_kwargs(effect_id, str(definition.get("icon", fallback) or fallback))


def _draw_native_items(layout, context, tokens, only=None):
    """Draw the add entries of one menu section, one per row."""
    geo = _geo()
    rigs, active_effects = geo._fbp_effect_add_menu_state(context)
    layout.operator_context = "INVOKE_REGION_WIN"

    def on_every_rig(effect_id):
        return bool(rigs) and all(
            effect_id in active_effects.get(geo._fbp_effect_ids_cache_key(rig), set())
            for rig in rigs
        )

    for token in tokens:
        token = str(token or "")
        if token == "GREASE_PENCIL_MASK_CONTROL":
            row = layout.row()
            row.enabled = bool(rigs) and not on_every_rig("GREASE_PENCIL_MASK")
            row.operator(
                "fbp.add_grease_pencil_mask", text="Grease Pencil Mask",
                **_item_icon_kwargs("GREASE_PENCIL_MASK", "OUTLINER_OB_GREASEPENCIL"),
            )
            continue
        if token == "LAYER_BLEND_CONTROL":
            token = geo.FBP_EFFECT_LAYER_BLEND
        if token.startswith("FAMILY:"):
            # One entry per family: the variant is chosen afterwards from the
            # dropdown at the top of the effect's settings.
            family_id = token.split(":", 1)[1].upper()
            family = geo.fbp_effect_family_definition(family_id)
            label = str(family.get("label", family_id.title()) or family_id.title())
            variants = [
                variant for variant, _label in family.get("variants", ())
                if only is None or variant in only
            ]
            default = str(family.get("default", "") or "")
            ordered = ([default] if default in variants else []) + [
                variant for variant in variants if variant != default
            ]
            target = next((
                variant for variant in ordered
                if not rigs or all(geo.fbp_effect_supported_for_rig(rig, variant) for rig in rigs)
            ), "")
            row = layout.row()
            row.enabled = bool(target) and not (bool(rigs) and all(
                any(
                    variant in active_effects.get(geo._fbp_effect_ids_cache_key(rig), set())
                    for variant in variants
                )
                for rig in rigs
            ))
            op = row.operator(
                FBP_OT_AddEffectModifier.bl_idname, text=label,
                **_item_icon_kwargs(
                    f"FAMILY_{family_id}", str(family.get("icon", "MODIFIER") or "MODIFIER"),
                ),
            )
            op.effect_id = target or default
            continue
        effect_id = geo.fbp_normalize_effect_id(token)
        definition = geo.fbp_effect_definition(effect_id)
        if not definition:
            continue
        row = layout.row()
        row.enabled = (
            not rigs or all(geo.fbp_effect_supported_for_rig(rig, effect_id) for rig in rigs)
        ) and not on_every_rig(effect_id)
        op = row.operator(
            FBP_OT_AddEffectModifier.bl_idname,
            text=str(definition.get("label", "") or geo._fbp_effect_display_label(effect_id, definition)),
            **_item_icon_kwargs(effect_id),
        )
        op.effect_id = effect_id


def _section_title(title):
    title = str(title or "")
    return title.title() if title.isupper() else title


def _draw_native_columns(layout, context, sections, column_groups, only=None):
    """Draw sections as divided columns, like Blender's classic Add Modifier.

    Each column carries one or more titled sections under a separator line.
    ``only`` keeps just the effects that already work as native modifiers;
    sections left empty disappear and the remaining ones fill the columns.
    """
    geo = _geo()
    kept, placed = [], set()
    for title, _icon, tokens in sections:
        if only is not None:
            kept_tokens = []
            for token in tokens:
                token = str(token or "")
                if token.startswith("FAMILY:"):
                    # A family stays one entry while any of its variants works
                    # as a modifier.
                    family = geo.fbp_effect_family_definition(token.split(":", 1)[1].upper())
                    members = [
                        variant for variant, _label in family.get("variants", ())
                        if variant in only
                    ]
                    if members:
                        kept_tokens.append(token)
                        placed.update(members)
                elif token.upper() in only:
                    kept_tokens.append(token)
                    placed.add(token.upper())
            tokens = tuple(kept_tokens)
        kept.append((title, tuple(tokens)))
    if only is not None:
        # Modifier-ready effects that the curated library reaches another way
        # (Posterize lives outside its sections) join the first shown section.
        view_ids = {
            str(token).upper()
            for _title, _icon, tokens in sections for token in tokens
            if not str(token).startswith("FAMILY:")
        }
        categories = {
            str((geo.fbp_effect_definition(token) or {}).get("category", "") or "")
            for token in view_ids
        }
        # Hidden legacy effects (Chroma Key) and effects the Mesh menu already
        # lists (Motion, Track to Camera) do not belong in this menu.
        mesh_ids = {
            str(token).upper()
            for _title, _icon, tokens in geo.FBP_MESH_EFFECT_MENU_SECTIONS for token in tokens
        }
        missing = tuple(
            effect_id for effect_id in only
            if effect_id not in placed and not geo.fbp_effect_family_id(effect_id)
            and effect_id not in mesh_ids
            and not bool((geo.fbp_effect_definition(effect_id) or {}).get("hidden", False))
            and str((geo.fbp_effect_definition(effect_id) or {}).get("category", "") or "") in categories
        )
        first = next((index for index, (_t, tokens) in enumerate(kept) if tokens), None)
        if missing and first is not None:
            kept[first] = (kept[first][0], kept[first][1] + missing)
    groups = [
        [index for index in group if kept[index][1]]
        for group in column_groups
    ]
    groups = [group for group in groups if group]
    if not groups:
        layout.label(text="No effects available", icon="INFO")
        return
    layout.operator_context = "INVOKE_REGION_WIN"
    columns = layout.row(align=False)
    for group in groups:
        column = columns.column(align=False)
        for local_index, index in enumerate(group):
            if local_index:
                column.separator()
            title, tokens = kept[index]
            column.label(text=_section_title(title))
            column.separator(type="LINE")
            _draw_native_items(column, context, tokens, only)


class FBP_OT_AddEffectModifier(bpy.types.Operator):
    bl_idname = "fbp.add_effect_modifier"
    bl_label = "Add Frame By Plane Modifier"
    bl_description = "Add the effect to the selected layers as a modifier"
    bl_options = {"REGISTER", "UNDO"}

    effect_id: bpy.props.StringProperty(name="Effect ID", default="", options={"SKIP_SAVE"})

    @classmethod
    def description(cls, _context, properties):
        return _geo().fbp_effect_tooltip(getattr(properties, "effect_id", ""))

    @classmethod
    def poll(cls, context):
        return bool(_geo()._fbp_selected_rigs(context))

    def execute(self, context):
        geo = _geo()
        from . import effect_shells
        effect_id = geo.fbp_normalize_effect_id(self.effect_id)
        rigs = tuple(geo._fbp_selected_rigs(context))
        before = {rig: frozenset(geo._fbp_mixed_effect_tokens(rig)) for rig in rigs}
        # Same Add as the Frame By Plane menu (this operator carries the same
        # effect_id and report), inside this operator's single Undo step.
        result = geo.FBP_OT_AddEffect.execute(self, context)
        if "FINISHED" not in result:
            return {"CANCELLED"}
        # Image effects and masks have no Blender modifier of their own: the
        # shell lands the entry in the Modifiers panel it was added from.
        if effect_shells.fbp_shell_supported(effect_id):
            for rig in rigs:
                added = [
                    token for token in geo._fbp_mixed_effect_tokens(rig)
                    if token not in before.get(rig, ())
                    and geo._fbp_effect_ref_effect_id(token) == effect_id
                ]
                for token in added or [""]:
                    instance_id = geo._fbp_effect_ref_instance_id(token) if token else ""
                    effect_shells.fbp_shell_create(rig, effect_id, instance_id)
                fbp_native_remember(rig)
        for rig in rigs:
            try:
                fbp_native_hide_inputs(rig)
            except FBP_DATA_ERRORS as exc:
                fbp_warn("Could not hide effect inputs in the Modifiers panel", exc)
        return {"FINISHED"}


class FBP_MT_ModifierAddMesh(Menu):
    bl_idname = "FBP_MT_modifier_add_mesh"
    bl_label = _MESH_MENU_LABEL
    bl_description = "Frame By Plane mesh effects for the selected layer"
    bl_options = {"SEARCH_ON_KEY_PRESS"}

    def draw(self, context):
        geo = _geo()
        _draw_native_columns(
            self.layout, context,
            geo.FBP_MESH_EFFECT_MENU_SECTIONS, geo.FBP_MESH_EFFECT_MENU_COLUMNS,
        )


class FBP_MT_ModifierAddImage(Menu):
    bl_idname = "FBP_MT_modifier_add_image"
    bl_label = _IMAGE_MENU_LABEL
    bl_description = "Frame By Plane image effects that work as modifiers"
    bl_options = {"SEARCH_ON_KEY_PRESS"}

    def draw(self, context):
        from .effect_shells import fbp_shell_effects
        geo = _geo()
        _draw_native_columns(
            self.layout, context,
            geo.FBP_IMAGE_EFFECT_MENU_SECTIONS, geo.FBP_IMAGE_EFFECT_MENU_COLUMNS,
            only=fbp_shell_effects(),
        )


class FBP_MT_ModifierAddMask(Menu):
    bl_idname = "FBP_MT_modifier_add_mask"
    bl_label = _MASK_MENU_LABEL
    bl_description = "Frame By Plane masks for the whole layer that work as modifiers"
    bl_options = {"SEARCH_ON_KEY_PRESS"}

    def draw(self, context):
        from .effect_shells import fbp_shell_effects
        geo = _geo()
        _draw_native_columns(
            self.layout, context,
            geo.FBP_MASK_EFFECT_MENU_SECTIONS, geo.FBP_MASK_EFFECT_MENU_COLUMNS,
            only=fbp_shell_effects(),
        )


class FBP_OT_EffectStackPresetsPopup(bpy.types.Operator):
    bl_idname = "fbp.effect_stack_presets_popup"
    bl_label = "Effect Stack Presets"
    bl_description = "Save the layer's whole effect stack as a preset, or apply, import and export one"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return bool(_geo()._fbp_selected_rigs(context))

    def invoke(self, context, _event):
        return context.window_manager.invoke_popup(self, width=380)

    def draw(self, context):
        from .effect_stack_presets import draw_effect_stack_presets_ui
        draw_effect_stack_presets_ui(
            self.layout, context, list(_geo()._fbp_selected_rigs(context)), collapsible=False,
        )

    def execute(self, _context):
        return {"FINISHED"}


def draw_modifier_add_mesh(self, context):
    rig, _plane = _context_layer(context)
    if rig is None:
        return
    layout = self.layout
    layout.separator()
    layout.menu(FBP_MT_ModifierAddMesh.bl_idname, text=_MESH_MENU_LABEL, icon=_MESH_MENU_ICON)
    layout.menu(FBP_MT_ModifierAddImage.bl_idname, text=_IMAGE_MENU_LABEL, icon=_IMAGE_MENU_ICON)
    layout.menu(FBP_MT_ModifierAddMask.bl_idname, text=_MASK_MENU_LABEL, icon=_MASK_MENU_ICON)
    # The whole stack at once: what used to sit under the Frame By Plane
    # section of this tab.
    layout.operator_context = "INVOKE_DEFAULT"
    layout.operator(FBP_OT_EffectStackPresetsPopup.bl_idname, text="Stack Presets…", icon="PRESET")


classes = (
    FBP_OT_EffectStackPresetsPopup,
    FBP_OT_AddEffectModifier,
    FBP_MT_ModifierAddMesh,
    FBP_MT_ModifierAddMask,
    FBP_MT_ModifierAddImage,
)


def register():
    if bool(getattr(bpy.app, "background", False)):
        return
    register_classes(classes)
    menu = getattr(bpy.types, "OBJECT_MT_modifier_add", None)
    if menu is not None:
        try:
            menu.remove(draw_modifier_add_mesh)
        except FBP_DATA_ERRORS:
            pass
        menu.append(draw_modifier_add_mesh)
    append_handler_once(
        bpy.app.handlers.depsgraph_update_post,
        fbp_native_modifiers_depsgraph_post,
        module_suffix=_MODULE_SUFFIX,
    )
    for handler_list in (
        bpy.app.handlers.undo_post,
        bpy.app.handlers.redo_post,
        bpy.app.handlers.load_post,
    ):
        append_handler_once(handler_list, fbp_native_modifiers_reset, module_suffix=_MODULE_SUFFIX)
    _subscribe_msgbus()
    _deferred_follow()


def unregister():
    if bool(getattr(bpy.app, "background", False)):
        fbp_native_forget_all()
        return
    try:
        bpy.msgbus.clear_by_owner(_MSGBUS_OWNER)
    except FBP_DATA_ERRORS:
        pass
    _release_all_pins()
    for handler_list in (
        bpy.app.handlers.depsgraph_update_post,
        bpy.app.handlers.undo_post,
        bpy.app.handlers.redo_post,
        bpy.app.handlers.load_post,
    ):
        remove_handlers_by_name(
            handler_list,
            "fbp_native_modifiers_depsgraph_post",
            "fbp_native_modifiers_reset",
            module_suffix=_MODULE_SUFFIX,
        )
    menu = getattr(bpy.types, "OBJECT_MT_modifier_add", None)
    if menu is not None:
        try:
            menu.remove(draw_modifier_add_mesh)
        except FBP_DATA_ERRORS:
            pass
    unregister_classes(classes)
    fbp_native_forget_all()
