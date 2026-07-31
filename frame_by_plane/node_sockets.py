"""Blender node-socket helpers shared by procedural builders.

Nodes such as Compare and Random Value expose duplicate display labels for
multiple data types. Blender 5.2 also changed several socket identifiers, so
callers should resolve the active RNA socket instead of relying on collection
order or ``collection.get()`` alone.
"""

from __future__ import annotations


_SOCKET_ACCESS_ERRORS = (
    AttributeError,
    IndexError,
    ReferenceError,
    RuntimeError,
    TypeError,
    ValueError,
)


def socket_is_available(socket) -> bool:
    """Return whether *socket* is active and usable by the current node mode."""
    if socket is None:
        return False
    try:
        if bool(getattr(socket, "is_unavailable", False)):
            return False
        if hasattr(socket, "enabled") and not bool(getattr(socket, "enabled", True)):
            return False
    except _SOCKET_ACCESS_ERRORS:
        return False
    return True


def named_socket(sockets, name, fallback=None, *, identifier=""):
    """Resolve an active socket by RNA identifier, display name or index.

    Blender nodes can expose several same-name sockets for different data types.
    Returning an unavailable candidate silently connects the wrong data type, so
    this helper now returns only sockets that Blender marks as active.
    """
    expected_identifier = str(identifier or "")
    expected_name = str(name or "")
    try:
        if expected_identifier:
            for socket in sockets:
                if (
                    str(getattr(socket, "identifier", "") or "") == expected_identifier
                    and socket_is_available(socket)
                ):
                    return socket
        for socket in sockets:
            if (
                str(getattr(socket, "name", "") or "") == expected_name
                and socket_is_available(socket)
            ):
                return socket
    except _SOCKET_ACCESS_ERRORS:
        pass

    if fallback is not None:
        try:
            socket = sockets[fallback]
            if socket_is_available(socket):
                return socket
        except _SOCKET_ACCESS_ERRORS:
            pass
    return None


def node_input(node, name, fallback=None, *, identifier=""):
    """Resolve an input socket without propagating stale-RNA access errors."""
    try:
        return named_socket(node.inputs, name, fallback, identifier=identifier)
    except _SOCKET_ACCESS_ERRORS:
        return None


def node_output(node, name, fallback=None, *, identifier=""):
    """Resolve an output socket without propagating stale-RNA access errors."""
    try:
        return named_socket(node.outputs, name, fallback, identifier=identifier)
    except _SOCKET_ACCESS_ERRORS:
        return None


__all__ = (
    "named_socket",
    "node_input",
    "node_output",
    "socket_is_available",
)
