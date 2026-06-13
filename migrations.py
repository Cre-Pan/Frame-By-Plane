"""One-shot migrations and cleanup for data created by older releases."""

import bpy

try:
    from .runtime import fbp_warn
except ImportError:
    from runtime import fbp_warn


def legacy_action_fcurves(obj):
    """Return F-Curves only for removing obsolete FBP_Wiggle modifiers."""
    ad = getattr(obj, 'animation_data', None)
    action = getattr(ad, 'action', None) if ad else None
    if not action:
        return []
    try:
        if hasattr(action, 'fcurves'):
            return list(action.fcurves)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        from bpy_extras import anim_utils
        slot = getattr(ad, 'action_slot', None)
        if slot:
            bag = anim_utils.action_get_channelbag_for_slot(action, slot)
            if bag and hasattr(bag, 'fcurves'):
                return list(bag.fcurves)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    return []


def cleanup_legacy_wiggle_modifiers():
    """Remove noise modifiers created by the retired Wiggle feature."""
    removed = 0
    try:
        objects = list(bpy.data.objects)
    except Exception:
        return 0
    for obj in objects:
        try:
            if not getattr(obj, 'is_fbp_control', False):
                continue
            for fcurve in legacy_action_fcurves(obj):
                for modifier in list(getattr(fcurve, 'modifiers', [])):
                    if getattr(modifier, 'name', '') == 'FBP_Wiggle':
                        fcurve.modifiers.remove(modifier)
                        removed += 1
        except (ReferenceError, RuntimeError, AttributeError):
            continue
    return removed


def deferred_legacy_wiggle_cleanup():
    """Compatibility timer entry point for all safe post-load migrations."""
    try:
        run_load_migrations()
    except (AttributeError, ReferenceError, RuntimeError, TypeError) as exc:
        fbp_warn('Could not run Frame by Plane load migrations', exc)
    return None


def remove_legacy_prestart_visibility(mat):
    """Remove the old pre-start alpha gate so the first sequence frame is held."""
    if not mat or not getattr(mat, 'use_nodes', False) or not getattr(mat, 'node_tree', None):
        return False
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    gate = nodes.get('FBP_PreStart_Alpha')
    visibility = nodes.get('FBP_PreStart_Visibility')
    changed = False
    if gate:
        source_socket = None
        try:
            if gate.inputs and gate.inputs[0].links:
                source_socket = gate.inputs[0].links[0].from_socket
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            source_socket = None
        targets = []
        try:
            targets = [link.to_socket for link in list(gate.outputs[0].links)]
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            targets = []
        if source_socket:
            for target in targets:
                try:
                    links.new(source_socket, target)
                except (AttributeError, ReferenceError, RuntimeError, TypeError):
                    pass
        try:
            nodes.remove(gate)
            changed = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
    if visibility:
        try:
            nodes.remove(visibility)
            changed = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
    return changed



def run_load_migrations():
    """Run safe, idempotent migrations after loading a .blend file."""
    return {"wiggle_modifiers_removed": cleanup_legacy_wiggle_modifiers()}


__all__ = [
    "legacy_action_fcurves", "cleanup_legacy_wiggle_modifiers",
    "deferred_legacy_wiggle_cleanup", "remove_legacy_prestart_visibility",
    "run_load_migrations",
]
