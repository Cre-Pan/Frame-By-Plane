"""Object-owned metadata for Blender 5.2 Generic Mesh modifiers.

Modifiers no longer accept custom properties, and Blender reuses persistent UIDs
after removal. A hidden, unused string input stores a per-instance ownership token;
its default is empty so manually sharing the node group never confers ownership.
This module deliberately has no bpy dependency so scope diagnostics can use it.
"""

import json
import uuid

_KEY = "fbp_generic_mesh_modifiers_v1"
_SOCKET = "FBP Generic Mesh Owner"


def _handle(modifier, *, create=False):
    group = modifier.node_group
    if group is None:
        return None
    socket = next((item for item in group.interface.items_tree
                   if getattr(item, "item_type", "") == "SOCKET"
                   and item.in_out == "INPUT" and item.name == _SOCKET), None)
    if socket is None and create:
        socket = group.interface.new_socket(name=_SOCKET, in_out='INPUT', socket_type='NodeSocketString')
        socket.default_value = ""
        socket.hide_in_modifier = True
    if socket is None:
        return None
    return getattr(modifier.properties.inputs, socket.identifier, None)


def _token(modifier):
    if modifier.type != "NODES":
        return ""
    handle = _handle(modifier)
    return str(handle.value) if handle is not None else ""


def _registry(modifier):
    owner = modifier.id_data
    raw = owner.get(_KEY, "")
    try:
        records = json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        records = {}
    return owner, records if isinstance(records, dict) else {}


def mesh_modifier_metadata(modifier):
    """Read ownership without mutating the file or retaining RNA wrappers."""
    try:
        if modifier.type != "NODES":
            return {}
        _owner, records = _registry(modifier)
        record = records.get(_token(modifier), {})
        return dict(record) if isinstance(record, dict) else {}
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return {}


def set_mesh_modifier_metadata(modifier, metadata):
    """Persist ownership only after writing a Blender-native instance token."""
    owner, records = _registry(modifier)
    handle = _handle(modifier, create=bool(metadata))
    if metadata:
        if handle is None:
            raise RuntimeError("Generic Mesh ownership input is unavailable")
        token = str(handle.value) or uuid.uuid4().hex
        handle.value = token
        records[token] = dict(metadata)
    elif handle is not None:
        handle.value = ""
    live = {_token(item) for item in owner.modifiers}
    records = {key: value for key, value in records.items() if key and key in live}
    if records:
        owner[_KEY] = json.dumps(records, sort_keys=True, separators=(",", ":"))
    elif _KEY in owner:
        del owner[_KEY]


def remove_mesh_modifier(modifier):
    """Remove an explicitly selected modifier and its owner-side metadata."""
    owner = modifier.id_data
    set_mesh_modifier_metadata(modifier, {})
    owner.modifiers.remove(modifier)
