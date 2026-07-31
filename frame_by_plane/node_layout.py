"""Deterministic, editor-only layout for generated Frame By Plane node trees.

Frames and reroutes have no evaluation cost.  Keeping this pass separate from
effect construction lets builders focus on data flow while every generated
tree gets the same readable left-to-right structure.
"""

from __future__ import annotations

from collections import defaultdict, deque
import time


_LAYOUT_VERSION = 1
_FRAME_TAG = "fbp_layout_frame"
_REROUTE_TAG = "fbp_layout_reroute"
_SECTION_LABELS = (
    "01  INPUT & SAMPLING",
    "02  FIELDS & MASKS",
    "03  EFFECT / GEOMETRY",
    "04  MATERIAL & OUTPUT",
)
_SECTION_COLORS = (
    (0.18, 0.24, 0.32),
    (0.20, 0.30, 0.24),
    (0.32, 0.24, 0.16),
    (0.30, 0.20, 0.28),
)

_LAYOUT_METRICS = {
    "calls": 0,
    "applied": 0,
    "skipped_existing": 0,
    "skipped_small": 0,
    "failed": 0,
    "total_seconds": 0.0,
    "max_seconds": 0.0,
    "max_nodes": 0,
    "max_links": 0,
}


def _record_layout(started, status, *, node_count=0, link_count=0):
    elapsed = max(0.0, time.perf_counter() - started)
    _LAYOUT_METRICS["calls"] += 1
    _LAYOUT_METRICS[status] = int(_LAYOUT_METRICS.get(status, 0)) + 1
    _LAYOUT_METRICS["total_seconds"] += elapsed
    _LAYOUT_METRICS["max_seconds"] = max(float(_LAYOUT_METRICS["max_seconds"]), elapsed)
    _LAYOUT_METRICS["max_nodes"] = max(int(_LAYOUT_METRICS["max_nodes"]), int(node_count))
    _LAYOUT_METRICS["max_links"] = max(int(_LAYOUT_METRICS["max_links"]), int(link_count))


def node_layout_metrics(*, reset=False):
    payload = {
        **_LAYOUT_METRICS,
        "total_milliseconds": float(_LAYOUT_METRICS["total_seconds"]) * 1000.0,
        "max_milliseconds": float(_LAYOUT_METRICS["max_seconds"]) * 1000.0,
    }
    if reset:
        for key in tuple(_LAYOUT_METRICS):
            _LAYOUT_METRICS[key] = 0.0 if "seconds" in key else 0
    return payload


def _is_layout_node(node):
    try:
        return bool(node.get(_FRAME_TAG, False) or node.get(_REROUTE_TAG, False))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _clear_previous_layout(node_tree):
    """Remove an older FBP layout without losing routed data-flow links."""
    try:
        reroutes = tuple(node for node in node_tree.nodes if bool(node.get(_REROUTE_TAG, False)))
        for route in reroutes:
            incoming = tuple(route.inputs[0].links)
            outgoing = tuple(route.outputs[0].links)
            source = incoming[0].from_socket if incoming else None
            targets = tuple(link.to_socket for link in outgoing)
            node_tree.nodes.remove(route)
            if source is not None:
                for target in targets:
                    node_tree.links.new(source, target)
        frames = tuple(node for node in node_tree.nodes if bool(node.get(_FRAME_TAG, False)))
        for frame in frames:
            for child in tuple(node for node in node_tree.nodes if node.parent is frame):
                absolute = frame.location + child.location
                child.parent = None
                child.location = absolute
            node_tree.nodes.remove(frame)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False
    return True


def _socket_key(socket):
    """Return a stable runtime key without retaining RNA socket wrappers."""
    try:
        return int(socket.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return id(socket)


def _fanout_reroutes(node_tree, nodes, *, minimum_links=3):
    """Collapse long one-to-many wires behind a named reroute node.

    Blender resolves ``socket.links`` by searching the complete node-tree link
    collection. Reading it for every output therefore becomes expensive on
    large generated effects. Index the links once and reuse that snapshot.
    """
    links = node_tree.links
    node_set = set(nodes)
    outgoing_by_socket = defaultdict(list)
    for link in tuple(links):
        try:
            if link.from_node in node_set:
                outgoing_by_socket[_socket_key(link.from_socket)].append(link)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue

    created = []
    minimum_links = max(2, int(minimum_links))
    for source in tuple(nodes):
        if source.bl_idname in {"NodeFrame", "NodeReroute", "NodeGroupOutput"}:
            continue
        for socket in tuple(source.outputs):
            outgoing = tuple(outgoing_by_socket.get(_socket_key(socket), ()))
            if len(outgoing) < minimum_links:
                continue
            try:
                span = max(float(link.to_node.location.x) for link in outgoing) - float(source.location.x)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                span = 0.0
            if span < 480.0:
                continue
            route = node_tree.nodes.new("NodeReroute")
            route.name = f"Route · {source.label or source.name} · {socket.name}"
            route.label = socket.name
            route[_REROUTE_TAG] = True
            route.location = (
                float(source.location.x) + 220.0,
                sum(float(link.to_node.location.y) for link in outgoing) / len(outgoing),
            )
            targets = tuple(link.to_socket for link in outgoing)
            for link in outgoing:
                links.remove(link)
            links.new(socket, route.inputs[0])
            for target in targets:
                links.new(route.outputs[0], target)
            created.append(route)
    return tuple(created)


def _topological_depths(node_tree, nodes):
    """Return stable longest-path columns for an acyclic shader/GN graph."""
    node_set = set(nodes)
    parents = {node: set() for node in nodes}
    children = {node: set() for node in nodes}
    for link in tuple(node_tree.links):
        source = link.from_node
        target = link.to_node
        if source in node_set and target in node_set and source is not target:
            parents[target].add(source)
            children[source].add(target)

    indegree = {node: len(parents[node]) for node in nodes}
    ordered = sorted(nodes, key=lambda item: (float(item.location.x), -float(item.location.y), item.name))
    queue = deque(node for node in ordered if indegree[node] == 0)
    depth = dict.fromkeys(nodes, 0)
    visited = set()
    while queue:
        node = queue.popleft()
        visited.add(node)
        for child in sorted(children[node], key=lambda item: item.name):
            depth[child] = max(depth[child], depth[node] + 1)
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)

    # Generated trees should be acyclic.  If a future simulation tree contains
    # a feedback cycle, keep those nodes after their known parents instead of
    # failing the entire effect build for an editor-only concern.
    for node in ordered:
        if node in visited:
            continue
        depth[node] = max((depth[parent] + 1 for parent in parents[node]), default=0)

    outputs = [node for node in nodes if node.bl_idname == "NodeGroupOutput"]
    if outputs:
        last = max(depth.values(), default=0) + 1
        for node in outputs:
            depth[node] = last
    return depth


def _estimated_height(node):
    try:
        socket_height = 26.0 * max(len(node.inputs), len(node.outputs), 1) + 58.0
        explicit = float(getattr(node, "height", 0.0) or 0.0)
        return max(130.0, min(520.0, socket_height), explicit)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return 160.0


def organize_node_tree(node_tree, *, minimum_nodes=8, add_reroutes=True):
    """Lay out a generated node tree with frames, lanes and fan-out routes.

    Returns ``True`` when a layout was applied.  The operation is intended for
    freshly generated/private trees and deliberately never runs every frame.
    """
    started = time.perf_counter()
    if node_tree is None:
        _record_layout(started, "failed")
        return False
    try:
        if (
            int(node_tree.get("fbp_node_layout_version", 0) or 0) == _LAYOUT_VERSION
            and any(_is_layout_node(node) for node in node_tree.nodes)
        ):
            _record_layout(
                started,
                "skipped_existing",
                node_count=len(node_tree.nodes),
                link_count=len(node_tree.links),
            )
            return True
        _clear_previous_layout(node_tree)
        nodes = tuple(node for node in node_tree.nodes if node.bl_idname != "NodeFrame")
        link_count = len(node_tree.links)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        _record_layout(started, "failed")
        return False
    if len(nodes) < int(minimum_nodes):
        _record_layout(started, "skipped_small", node_count=len(nodes), link_count=link_count)
        return False

    if add_reroutes:
        nodes = nodes + _fanout_reroutes(node_tree, nodes)
    depths = _topological_depths(node_tree, nodes)
    by_depth = defaultdict(list)
    for node in nodes:
        by_depth[int(depths.get(node, 0))].append(node)
    max_depth = max(by_depth, default=0)
    x_origin = -0.5 * max_depth * 300.0
    absolute_locations = {}
    for column in sorted(by_depth):
        column_nodes = sorted(
            by_depth[column],
            key=lambda item: (-float(item.location.y), float(item.location.x), item.name),
        )
        cursor_y = 0.0
        for node in column_nodes:
            absolute_locations[node] = (x_origin + column * 300.0, -cursor_y)
            cursor_y += _estimated_height(node) + 90.0

    section_count = min(len(_SECTION_LABELS), max(2, min(4, max_depth + 1)))
    section_nodes = defaultdict(list)
    for node in nodes:
        depth = int(depths.get(node, 0))
        section = min(section_count - 1, int(depth * section_count / max(1, max_depth + 1)))
        if node.bl_idname == "NodeGroupOutput":
            section = section_count - 1
        section_nodes[section].append(node)

    for section in range(section_count):
        children = section_nodes.get(section, ())
        if not children:
            continue
        frame = node_tree.nodes.new("NodeFrame")
        frame.name = f"FBP Layout · {_SECTION_LABELS[section]}"
        frame.label = _SECTION_LABELS[section]
        frame.label_size = 24
        frame.use_custom_color = True
        frame.color = _SECTION_COLORS[section]
        frame[_FRAME_TAG] = True
        min_x = min(absolute_locations[node][0] for node in children)
        max_y = max(absolute_locations[node][1] for node in children)
        frame.location = (min_x - 80.0, max_y + 100.0)
        for node in children:
            absolute = absolute_locations[node]
            node.parent = frame
            node.location = (absolute[0] - frame.location.x, absolute[1] - frame.location.y)

    try:
        node_tree["fbp_node_layout_version"] = _LAYOUT_VERSION
        node_tree["fbp_node_layout_sections"] = int(section_count)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    _record_layout(
        started,
        "applied",
        node_count=len(nodes),
        link_count=len(node_tree.links),
    )
    return True


__all__ = ["node_layout_metrics", "organize_node_tree"]
