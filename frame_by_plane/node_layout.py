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


# ---------------------------------------------------------------------------
# Readable node views
#
# The passes below only move nodes, set display labels, collapse small reader
# nodes and add frames. Frames have no evaluation cost and no node is renamed
# or relinked, so lookups by name and the evaluated result are unchanged.
# ---------------------------------------------------------------------------

NODE_VIEW_VERSION = 2
NODE_VIEW_VERSION_KEY = "fbp_node_view_version"
NODE_VIEW_SIGNATURE_KEY = "fbp_node_view_signature"
_VIEW_FRAME_TAG = "fbp_node_view_frame"
_VIEW_NOTE_TAG = "fbp_node_view_note"
_DATA_ERRORS = (AttributeError, KeyError, ReferenceError, RuntimeError, TypeError, ValueError)

_COLUMN_GAP = 70.0
_ROW_GAP = 34.0
_FRAME_PAD = 46.0
_SECTION_GAP = 150.0
_NOTE_LINE_HEIGHT = 30.0
_NOTE_CHARS = 58

_VIEW_METRICS = {"layouts": 0, "skipped": 0, "failed": 0, "total_seconds": 0.0, "max_seconds": 0.0}


def node_view_metrics(*, reset=False):
    payload = dict(_VIEW_METRICS)
    payload["total_milliseconds"] = float(payload["total_seconds"]) * 1000.0
    payload["max_milliseconds"] = float(payload["max_seconds"]) * 1000.0
    if reset:
        for key in tuple(_VIEW_METRICS):
            _VIEW_METRICS[key] = 0.0 if "seconds" in key else 0
    return payload


def _record_view(started, status):
    elapsed = max(0.0, time.perf_counter() - started)
    _VIEW_METRICS[status] = int(_VIEW_METRICS.get(status, 0)) + 1
    _VIEW_METRICS["total_seconds"] += elapsed
    _VIEW_METRICS["max_seconds"] = max(float(_VIEW_METRICS["max_seconds"]), elapsed)


def node_view_annotations_enabled(context=None):
    """Return the preference that adds note frames to generated node views."""
    try:
        from .interface_preferences import fbp_get_addon_preferences
        prefs = fbp_get_addon_preferences(context)
    except (ImportError, *_DATA_ERRORS):
        prefs = None
    return bool(getattr(prefs, "node_view_annotations", True)) if prefs is not None else True


# Node-view helpers: frames and the Markdown Comment notes (Blender 5.3).
_VIEW_HELPER_TYPES = frozenset({"NodeFrame", "NodeComment"})


def is_node_view_helper(node):
    """True for frames and notes added by a node-view pass (never evaluated)."""
    try:
        return node.bl_idname in _VIEW_HELPER_TYPES and bool(
            node.get(_VIEW_FRAME_TAG, False) or node.get(_VIEW_NOTE_TAG, False)
        )
    except _DATA_ERRORS:
        return False


_VIEW_KEY = "fbp_node_view_key"
# Frames of the previous pass, reused by key: creating, naming and removing
# frames each runs an RNA update, so a relayout that changes nothing visible
# should not churn them.
_FRAME_POOL = {}
_FRAME_KEYS_USED = set()


def _remove_view_frames(tree):
    """Collect earlier node-view frames for reuse.

    Frames of the older section layout (``organize_node_tree``, also saved in
    the bundled effect library) are removed. Its reroutes stay: removing them
    would relink the tree.
    """
    _FRAME_POOL.clear()
    _FRAME_KEYS_USED.clear()
    for node in tuple(tree.nodes):
        try:
            if node.bl_idname not in _VIEW_HELPER_TYPES:
                continue
            if is_node_view_helper(node):
                key = str(node.get(_VIEW_KEY, "") or "")
                if key and key not in _FRAME_POOL:
                    _FRAME_POOL[key] = node
                    continue
                tree.nodes.remove(node)
            elif bool(node.get(_FRAME_TAG, False)):
                tree.nodes.remove(node)
        except _DATA_ERRORS:
            continue


def _drop_unused_frames(tree):
    """Remove pooled frames this pass did not reuse."""
    for key, frame in tuple(_FRAME_POOL.items()):
        if key in _FRAME_KEYS_USED:
            continue
        try:
            tree.nodes.remove(frame)
        except _DATA_ERRORS:
            pass
    _FRAME_POOL.clear()
    _FRAME_KEYS_USED.clear()


def _set_if_changed(owner, attribute, value):
    try:
        current = getattr(owner, attribute)
        if hasattr(current, "__len__") and not isinstance(current, str):
            if all(abs(float(a) - float(b)) < 1.0e-6 for a, b in zip(current, value)):
                return
        elif current == value:
            return
        setattr(owner, attribute, value)
    except _DATA_ERRORS:
        pass


def _wrap(text, width=_NOTE_CHARS):
    words = str(text or "").split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _new_view_frame(tree, label, color, *, label_size=16, note=False, parent=None):
    text = str(label or "")[:63]
    parent_key = str(parent.get(_VIEW_KEY, "") or "") if parent is not None else ""
    base = f"{'N' if note else 'V'}|{parent_key}|{text}"
    key = base
    duplicate = 1
    while key in _FRAME_KEYS_USED:
        duplicate += 1
        key = f"{base}|{duplicate}"
    _FRAME_KEYS_USED.add(key)
    frame = _FRAME_POOL.get(key)
    if frame is None:
        frame = tree.nodes.new("NodeFrame")
        frame.name = ("FBP Note · " if note else "FBP View · ") + text[:48]
        frame[_VIEW_NOTE_TAG if note else _VIEW_FRAME_TAG] = True
        frame[_VIEW_KEY] = key
        frame.use_custom_color = True
    _set_if_changed(frame, "label", text)
    _set_if_changed(frame, "label_size", int(label_size))
    _set_if_changed(frame, "color", tuple(color))
    try:
        if frame.parent != parent:
            frame.parent = parent
    except _DATA_ERRORS:
        pass
    return frame


def _new_view_comment(tree, key_text, text, width, *, parent=None):
    """Return a pooled Comment node showing ``text`` as Markdown."""
    parent_key = str(parent.get(_VIEW_KEY, "") or "") if parent is not None else ""
    base = f"C|{parent_key}|{str(key_text or '')[:63]}"
    key = base
    duplicate = 1
    while key in _FRAME_KEYS_USED:
        duplicate += 1
        key = f"{base}|{duplicate}"
    _FRAME_KEYS_USED.add(key)
    comment = _FRAME_POOL.get(key)
    if comment is not None and comment.bl_idname != "NodeComment":
        try:
            tree.nodes.remove(comment)
        except _DATA_ERRORS:
            pass
        comment = None
    if comment is None:
        comment = tree.nodes.new("NodeComment")
        comment.name = "FBP Note · " + str(key_text or "")[:48]
        comment[_VIEW_NOTE_TAG] = True
        comment[_VIEW_KEY] = key
    _set_if_changed(comment, "text", str(text or ""))
    _set_if_changed(comment, "width", float(width))
    try:
        if comment.parent != parent:
            comment.parent = parent
    except _DATA_ERRORS:
        pass
    return comment


def _add_note(tree, title, lines, x, y, width, *, parent=None, bottom=None):
    """Add a note: one Markdown Comment node with a bold title.

    Returns the height the note takes. Comment nodes hold no data-block and
    are never evaluated, so notes cost nothing at render time.
    """
    paragraphs = [str(text).strip() for text in lines if str(text or "").strip()]
    if not paragraphs:
        return 0.0
    rows = [line for text in paragraphs for line in _wrap(text, max(24, min(60, int(width / 8.0))))]
    if bottom is not None:
        # Sit just above ``bottom`` whatever the number of lines.
        y = float(bottom) + 36.0 + _NOTE_LINE_HEIGHT * len(rows) + 60.0
    text = f"**{title}**\n\n" + "\n\n".join(paragraphs)
    note = _new_view_comment(tree, title, text, width, parent=parent)
    _PLACEMENTS.append((note, x, y))
    return 36.0 + _NOTE_LINE_HEIGHT * len(rows) + _FRAME_PAD


def _visible_socket_count(sockets):
    count = 0
    for socket in sockets:
        try:
            if socket.enabled and not socket.hide:
                count += 1
        except _DATA_ERRORS:
            count += 1
    return count


_TALL_NODE_EXTRA = {
    "ShaderNodeTexImage": 170.0,
    "ShaderNodeValToRGB": 170.0,
    "ShaderNodeRGBCurve": 230.0,
    "ShaderNodeFloatCurve": 230.0,
    "ShaderNodeVectorCurve": 230.0,
    "ShaderNodeRGB": 150.0,
    "ShaderNodeAttribute": 50.0,
    "GeometryNodeStoreNamedAttribute": 40.0,
    "ShaderNodeBsdfPrincipled": 120.0,
}


def node_height(node):
    """Best estimate of a node's drawn height (dimensions are 0 in background)."""
    try:
        if node.bl_idname == "NodeReroute":
            return 20.0
        if node.hide:
            return 32.0
        sockets = _visible_socket_count(node.inputs) + _visible_socket_count(node.outputs)
        extra = _TALL_NODE_EXTRA.get(node.bl_idname, 0.0)
        if node.bl_idname in {"ShaderNodeMath", "ShaderNodeVectorMath", "FunctionNodeCompare",
                              "ShaderNodeMix", "ShaderNodeMixRGB", "FunctionNodeBooleanMath",
                              "GeometryNodeSwitch", "ShaderNodeMapRange", "ShaderNodeClamp"}:
            extra += 26.0
        return max(70.0, 44.0 + 22.0 * sockets + extra)
    except _DATA_ERRORS:
        return 160.0


def _node_width(node):
    try:
        return max(60.0, float(node.width))
    except _DATA_ERRORS:
        return 140.0


def _link_pairs(tree, members):
    """Return node links among ``members`` as (from, to) pairs, read once."""
    pairs = []
    for link in tuple(tree.links):
        try:
            source, target = link.from_node, link.to_node
        except _DATA_ERRORS:
            continue
        if source in members and target in members and source is not target:
            pairs.append((source, target))
    return pairs


def _longest_path_columns(nodes, pairs):
    """Columns from the longest path; sources sit right before their consumer."""
    parents = {node: set() for node in nodes}
    children = {node: set() for node in nodes}
    for source, target in pairs:
        if source in parents and target in parents:
            parents[target].add(source)
            children[source].add(target)
    indegree = {node: len(parents[node]) for node in nodes}
    queue = deque(sorted((node for node in nodes if not indegree[node]), key=lambda n: n.name))
    depth = dict.fromkeys(nodes, 0)
    order = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for child in sorted(children[node], key=lambda n: n.name):
            depth[child] = max(depth[child], depth[node] + 1)
            indegree[child] -= 1
            if not indegree[child]:
                queue.append(child)
    # Feedback loops (none are generated today) keep a column after a parent.
    for node in nodes:
        if node not in depth or node in order:
            continue
        depth[node] = max((depth[parent] + 1 for parent in parents[node]), default=0)
    # Pull pure inputs (values, attributes, coordinates) next to their first
    # consumer instead of leaving them all in the first column.
    for node in reversed(order):
        if parents[node] or not children[node]:
            continue
        depth[node] = max(0, min(depth[child] for child in children[node]) - 1)
    return depth, parents, children


def _place_columns(nodes, depth, parents, children, x0, y0):
    """Place nodes column by column; each column follows its parents' height.

    Returns absolute positions and the bounding box (x0, y_top, x1, y_bottom).
    """
    if not nodes:
        return {}, (x0, y0, x0, y0)
    columns = defaultdict(list)
    for node in nodes:
        columns[depth.get(node, 0)].append(node)
    positions = {}
    centers = {}
    x = x0
    bottom = y0
    for column in sorted(columns):
        members = columns[column]

        def wanted(node):
            above = [centers[parent] for parent in parents.get(node, ()) if parent in centers]
            if not above:
                return None
            return sum(above) / len(above)

        members.sort(key=lambda node: (
            wanted(node) is None,
            -(wanted(node) or 0.0),
            node.name,
        ))
        width = max(_node_width(node) for node in members)
        cursor = y0
        for node in members:
            height = node_height(node)
            target = wanted(node)
            top = cursor if target is None else min(cursor, target + 0.5 * height)
            positions[node] = (x, top)
            centers[node] = top - 0.5 * height
            cursor = top - height - _ROW_GAP
        bottom = min(bottom, cursor)
        x += width + _COLUMN_GAP
    # Second pass: pure inputs follow the consumer they feed.
    for node in nodes:
        if parents.get(node) or not children.get(node):
            continue
        consumers = [centers[child] for child in children[node] if child in centers]
        if not consumers:
            continue
        column = [other for other in nodes if positions[other][0] == positions[node][0]]
        if len(column) == 1:
            height = node_height(node)
            top = sum(consumers) / len(consumers) + 0.5 * height
            positions[node] = (positions[node][0], min(y0, top))
    top_y = max((pos[1] for pos in positions.values()), default=y0)
    low_y = min((pos[1] - node_height(node) for node, pos in positions.items()), default=y0)
    return positions, (x0, top_y, x - _COLUMN_GAP, low_y)


# Absolute positions waiting for one batched write. Setting ``location`` node
# by node runs an RNA update each time (about 0.3 ms per node in Blender 5.2);
# ``foreach_set`` writes the whole tree at once.
_PLACEMENTS = []


def _apply_positions(positions, frame=None):
    for node, (x, y) in positions.items():
        try:
            if frame is not None:
                if node.parent != frame:
                    node.parent = frame
            elif node.parent is not None and is_node_view_helper(node.parent):
                node.parent = None
        except _DATA_ERRORS:
            continue
        _PLACEMENTS.append((node, float(x), float(y)))


def _flush_positions(tree):
    """Write every pending absolute position of ``tree`` in one call."""
    pending = list(_PLACEMENTS)
    _PLACEMENTS.clear()
    if not pending:
        return
    nodes = tree.nodes
    count = len(nodes)
    buffer = [0.0] * (2 * count)
    nodes.foreach_get("location", buffer)
    index = {node: position for position, node in enumerate(nodes)}
    parent_origin = {}
    for node, x, y in pending:
        position = index.get(node)
        if position is None:
            continue
        parent = node.parent
        if parent is None:
            origin = (0.0, 0.0)
        else:
            origin = parent_origin.get(parent)
            if origin is None:
                origin = tuple(parent.location_absolute)
                parent_origin[parent] = origin
        buffer[2 * position] = x - origin[0]
        buffer[2 * position + 1] = y - origin[1]
    nodes.foreach_set("location", buffer)
    try:
        tree.update_tag()
    except _DATA_ERRORS:
        pass


def _tree_signature(tree):
    """Cheap structural signature: node names, parents and link endpoints."""
    try:
        names = sorted(
            f"{node.name}\x1f{getattr(node.parent, 'name', '')}"
            for node in tree.nodes
        )
        links = sorted(
            f"{link.from_node.name}\x1f{link.from_socket.identifier}\x1e{link.to_node.name}\x1f{link.to_socket.identifier}"
            for link in tree.links
        )
    except _DATA_ERRORS:
        return ""
    return str(hash((NODE_VIEW_VERSION, tuple(names), tuple(links))))


def node_view_is_current(tree, *, annotate=None):
    """True when ``tree`` already carries the current node view."""
    try:
        if int(tree.get(NODE_VIEW_VERSION_KEY, 0) or 0) != NODE_VIEW_VERSION:
            return False
        if annotate is not None and bool(tree.get("fbp_node_view_annotated", True)) != bool(annotate):
            return False
        return str(tree.get(NODE_VIEW_SIGNATURE_KEY, "") or "") == _tree_signature(tree)
    except _DATA_ERRORS:
        return False


def _stamp_view(tree, annotate):
    try:
        tree[NODE_VIEW_VERSION_KEY] = NODE_VIEW_VERSION
        tree["fbp_node_view_annotated"] = bool(annotate)
        tree[NODE_VIEW_SIGNATURE_KEY] = _tree_signature(tree)
    except _DATA_ERRORS:
        pass


# -- Effect groups -----------------------------------------------------------

_STOP_WORDS = {
    "a", "and", "of", "the", "to", "in", "by", "for", "is", "or", "on", "at",
    "fbp", "x", "y", "z", "uv", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
    "math", "value", "result", "factor", "node", "safe", "use", "group", "input",
    "output", "mix", "combine", "separate", "multiply", "add", "subtract", "divide",
    "minimum", "maximum", "clamp", "switch",
}
_GROUP_COLORS = (
    (0.17, 0.22, 0.30),
    (0.17, 0.26, 0.21),
    (0.29, 0.23, 0.16),
    (0.27, 0.19, 0.27),
    (0.18, 0.25, 0.27),
    (0.26, 0.21, 0.19),
)
_IO_COLOR = (0.22, 0.22, 0.22)


def _band_label(nodes, skip_words):
    counts = defaultdict(int)
    for node in nodes:
        text = str(getattr(node, "label", "") or getattr(node, "name", "") or "")
        seen = set()
        for word in text.replace("·", " ").replace("•", " ").replace("_", " ").split():
            key = word.strip("()[]:,.-").lower()
            if not key or key in _STOP_WORDS or key in skip_words or key.isdigit() or key in seen:
                continue
            seen.add(key)
            counts[word.strip("()[]:,.-").capitalize()] += 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    words = [word for word, count in ranked[:3] if count > 1] or [word for word, _count in ranked[:2]]
    return " · ".join(words)


def _socket_names(tree, in_out):
    try:
        return [
            str(item.name)
            for item in tree.interface.items_tree
            if getattr(item, "item_type", "") == "SOCKET" and item.in_out == in_out
        ]
    except _DATA_ERRORS:
        return []


def _label_input_keepers(tree, nodes):
    """Name the nodes that keep modifier inputs active by what they do."""
    usage = [node for node in nodes if bool(node.get("fbp_shell_usage_node", False))]
    if not usage:
        return
    usage_set = set(usage)
    for link in tuple(tree.links):
        try:
            node = link.to_node
            if node in usage_set and link.from_node.bl_idname == "NodeGroupInput":
                kind = "Choice" if node.bl_idname == "GeometryNodeMenuSwitch" else "Read"
                if node.bl_idname != "ShaderNodeMath":
                    node.label = f"{kind} · {link.from_socket.name}"[:63]
        except _DATA_ERRORS:
            continue
    for node in usage:
        if node.bl_idname == "ShaderNodeMath":
            node.label = "Keep input active"
        elif node.bl_idname == "GeometryNodeStoreNamedAttribute":
            node.label = "Mark inputs as used"
        elif node.bl_idname == "GeometryNodeRemoveAttribute":
            node.label = "Remove the marker"


def tidy_effect_group(tree, *, title="", description="", annotate=None, force=False, minimum_nodes=4):
    """Lay out one generated effect group from its inputs to its outputs.

    Group Input sits in an "Inputs" frame on the left, Group Output in a
    "Result" frame on the right, and the work in between is split into
    labelled steps that follow the data flow. An optional note explains
    what the group does. Nested groups owned by Frame By Plane are tidied too.
    """
    started = time.perf_counter()
    if tree is None:
        return False
    if annotate is None:
        annotate = node_view_annotations_enabled()
    try:
        if getattr(tree, "library", None) is not None:
            return False
        if not force and node_view_is_current(tree, annotate=annotate):
            _record_view(started, "skipped")
            return True
        _PLACEMENTS.clear()
        _remove_view_frames(tree)
        nodes = [
            node for node in tree.nodes
            if node.bl_idname != "NodeFrame"
            and not is_node_view_helper(node)
            and (node.parent is None or is_node_view_helper(node.parent))
        ]
        if len(nodes) < int(minimum_nodes):
            _stamp_view(tree, annotate)
            _record_view(started, "skipped")
            return False
        members = set(nodes)
        pairs = _link_pairs(tree, members)
        depth, parents, children = _longest_path_columns(nodes, pairs)
        inputs = [node for node in nodes if node.bl_idname == "NodeGroupInput"]
        outputs = [node for node in nodes if node.bl_idname == "NodeGroupOutput"]
        # Readers that only keep modifier inputs active (see effect_shells)
        # get one compact column instead of spreading through the steps.
        keepers = [
            node for node in nodes
            if bool(node.get("fbp_shell_usage_node", False))
            and node.bl_idname not in {"GeometryNodeStoreNamedAttribute", "GeometryNodeRemoveAttribute"}
        ]
        keeper_set = set(keepers)
        _label_input_keepers(tree, nodes)
        body = [
            node for node in nodes
            if node not in inputs and node not in outputs and node not in keeper_set
        ]
        title = str(title or tree.get("fbp_effect_label", "") or tree.name).strip()
        skip_words = {word.lower() for word in title.split()}

        # Columns are relative to the body only, so the IO frames stay apart.
        if body:
            minimum = min(depth[node] for node in body)
            for node in body:
                depth[node] -= minimum
        columns = max((depth[node] for node in body), default=0) + 1
        band_size = 4 if columns <= 12 else max(4, (columns + 5) // 6)
        bands = defaultdict(list)
        for node in body:
            bands[depth[node] // band_size].append(node)

        x = 0.0
        y_top = 0.0
        if annotate:
            note_lines = []
            if description:
                note_lines.append(str(description))
            ins = [name for name in _socket_names(tree, "INPUT") if name]
            outs = [name for name in _socket_names(tree, "OUTPUT") if name]
            if ins or outs:
                note_lines.append("In: " + ", ".join(ins[:8]) + (" …" if len(ins) > 8 else ""))
                note_lines.append("Out: " + ", ".join(outs[:6]))
            note_lines.append("Flow: Inputs → numbered steps (left to right) → Result.")
            _add_note(tree, f"Note · {title}"[:63], note_lines, 0.0, 0.0, 640.0, bottom=y_top + 90.0)

        if inputs:
            frame = _new_view_frame(tree, "Inputs", _IO_COLOR, label_size=18)
            positions = {}
            cursor = y_top
            for node in inputs:
                positions[node] = (x, cursor)
                cursor -= node_height(node) + _ROW_GAP
            _apply_positions(positions, frame)
            if keepers:
                keep_frame = _new_view_frame(tree, "Keep inputs active", _IO_COLOR, label_size=14)
                keep_positions = {}
                keep_y = cursor - 60.0
                for node in sorted(keepers, key=lambda item: (item.bl_idname, item.name)):
                    keep_positions[node] = (x, keep_y)
                    keep_y -= node_height(node) + 8.0
                _apply_positions(keep_positions, keep_frame)
            x += max(_node_width(node) for node in inputs) + _SECTION_GAP

        for index, band in enumerate(sorted(bands)):
            band_nodes = bands[band]
            label_words = _band_label(band_nodes, skip_words)
            label = f"{index + 1} · {label_words}" if label_words else f"Step {index + 1}"
            frame = _new_view_frame(tree, label, _GROUP_COLORS[index % len(_GROUP_COLORS)], label_size=18)
            local = {node: depth[node] - band * band_size for node in band_nodes}
            positions, box = _place_columns(band_nodes, local, parents, children, x, y_top)
            _apply_positions(positions, frame)
            x = box[2] + _SECTION_GAP

        if outputs:
            frame = _new_view_frame(tree, "Result", _IO_COLOR, label_size=18)
            positions = {}
            cursor = y_top
            for node in outputs:
                positions[node] = (x, cursor)
                cursor -= node_height(node) + _ROW_GAP
            _apply_positions(positions, frame)
        _flush_positions(tree)
        _drop_unused_frames(tree)

        for node in body:
            nested = getattr(node, "node_tree", None)
            if nested is None or nested is tree:
                continue
            try:
                owned = bool(nested.get("fbp_owned", False)) or str(nested.name).startswith("FBP")
            except _DATA_ERRORS:
                owned = False
            if owned and not bool(nested.get("fbp_user_editable_effect_group", False)):
                tidy_effect_group(nested, annotate=annotate)
        _stamp_view(tree, annotate)
    except _DATA_ERRORS:
        _PLACEMENTS.clear()
        _record_view(started, "failed")
        return False
    _record_view(started, "layouts")
    return True


# -- Layer materials ---------------------------------------------------------

SECTION_STYLE = {
    "SOURCE": ("Source", (0.20, 0.20, 0.24),
               "Texture coordinates and layer inputs the effects start from."),
    "UV": ("UV effects", (0.16, 0.23, 0.32),
           "Distort the coordinates before the image is read, in stack order."),
    "IMAGE": ("Layer image", (0.30, 0.22, 0.14),
              "The layer's picture, read at the coordinates on its left."),
    "COLOR": ("Color effects", (0.16, 0.28, 0.20),
              "Change the picture's color one effect after the other."),
    "MASK": ("Masks & alpha", (0.29, 0.18, 0.26),
             "Masks combine into the layer's transparency."),
    "OUTPUT": ("Output", (0.24, 0.17, 0.17),
               "Emission, transparency and the material output."),
}
_BLOCK_COLOR_SHIFT = 0.06


def _block_color(section_color):
    return tuple(min(1.0, channel + _BLOCK_COLOR_SHIFT) for channel in section_color)


def _layout_block(tree, block_nodes, pairs_all, x, y):
    members = set(block_nodes)
    pairs = [pair for pair in pairs_all if pair[0] in members and pair[1] in members]
    depth, parents, children = _longest_path_columns(list(block_nodes), pairs)
    return _place_columns(list(block_nodes), depth, parents, children, x, y)


def layout_layer_material(tree, sections, *, title="", annotate=None, force=False):
    """Arrange a layer material as a left-to-right pipeline of sections.

    ``sections`` maps a key of :data:`SECTION_STYLE` to a list of blocks; a
    block is ``(label, nodes)``. Blocks of the UV and Color sections are the
    effects in stack order, each in its own numbered frame with the nodes that
    feed it. Masks are drawn under the Color effects. Nodes that are not
    listed (for example nodes an artist added) are left where they are.
    """
    started = time.perf_counter()
    if tree is None:
        return False
    if annotate is None:
        annotate = node_view_annotations_enabled()
    try:
        if not force and node_view_is_current(tree, annotate=annotate):
            _record_view(started, "skipped")
            return True
        _PLACEMENTS.clear()
        _remove_view_frames(tree)
        listed = set()
        for blocks in sections.values():
            for _label, block_nodes in blocks:
                listed.update(block_nodes)
        if not listed:
            _stamp_view(tree, annotate)
            _record_view(started, "skipped")
            return False
        pairs_all = _link_pairs(tree, listed)

        y_top = 0.0
        x = 0.0
        if annotate:
            flow = [SECTION_STYLE[key][0] for key in ("SOURCE", "UV", "IMAGE", "COLOR", "MASK", "OUTPUT") if sections.get(key)]
            lines = [
                "Flow: " + " → ".join(flow) + ".",
                "Each numbered frame is one effect, in stack order, with its settings on its left.",
                "Frames and notes are display only. Turn notes off in the add-on preferences.",
            ]
            _add_note(tree, f"Note · {title or 'Frame By Plane layer material'}"[:63], lines, 0.0, 0.0, 760.0, bottom=y_top + 90.0)

        def section(key, x0, y0):
            blocks = [block for block in sections.get(key, ()) if block[1]]
            if not blocks:
                return None
            label, color, hint = SECTION_STYLE[key]
            frame = _new_view_frame(tree, label, color, label_size=20)
            cursor_x = x0
            top = y0
            bottom = y0
            notes_offset = 0.0
            hint_width = 400.0
            if annotate:
                hint_rows = _wrap(hint, 50)
                hint_note = _new_view_comment(tree, f"{label} hint", hint, hint_width, parent=frame)
                _PLACEMENTS.append((hint_note, x0, y0))
                notes_offset = _NOTE_LINE_HEIGHT * len(hint_rows) + 24.0
            stacked = key in {"SOURCE", "IMAGE", "OUTPUT"} and len(blocks) > 1 and all(len(b[1]) == 1 for b in blocks)
            for label_text, block_nodes in blocks:
                block_y = y0 - notes_offset
                if len(blocks) == 1 and key in {"SOURCE", "IMAGE", "OUTPUT"} or stacked:
                    if stacked:
                        block_y = bottom - (notes_offset if bottom == y0 else _ROW_GAP)
                        positions, box = _layout_block(tree, block_nodes, pairs_all, x0, block_y)
                    else:
                        positions, box = _layout_block(tree, block_nodes, pairs_all, cursor_x, block_y)
                    _apply_positions(positions, frame)
                else:
                    sub = _new_view_frame(tree, label_text, _block_color(color), label_size=15, parent=frame)
                    positions, box = _layout_block(tree, block_nodes, pairs_all, cursor_x + 20.0, block_y - 46.0)
                    _apply_positions(positions, sub)
                    box = (box[0] - 20.0, box[1] + 46.0, box[2] + 20.0, box[3] - 20.0)
                if not stacked:
                    cursor_x = box[2] + _FRAME_PAD + 30.0
                bottom = min(bottom, box[3])
                top = max(top, box[1])
                if stacked:
                    cursor_x = max(cursor_x, box[2] + _FRAME_PAD + 30.0)
            right = cursor_x - _FRAME_PAD - 30.0
            if annotate:
                right = max(right, x0 + hint_width)
            return (x0, top, right, bottom)

        for key in ("SOURCE", "UV", "IMAGE"):
            box = section(key, x, y_top)
            if box is not None:
                x = box[2] + _SECTION_GAP
        color_x = x
        color_box = section("COLOR", color_x, y_top)
        right = color_x
        if color_box is not None:
            right = color_box[2] + _SECTION_GAP
        mask_y = (color_box[3] - _SECTION_GAP) if color_box is not None else y_top
        mask_box = section("MASK", color_x, mask_y)
        if mask_box is not None:
            right = max(right, mask_box[2] + _SECTION_GAP)
        section("OUTPUT", right, y_top)
        _flush_positions(tree)
        _drop_unused_frames(tree)
        _stamp_view(tree, annotate)
    except _DATA_ERRORS:
        _PLACEMENTS.clear()
        _record_view(started, "failed")
        return False
    _record_view(started, "layouts")
    return True


__all__ = [
    "NODE_VIEW_VERSION",
    "is_node_view_helper",
    "layout_layer_material",
    "node_height",
    "node_layout_metrics",
    "node_view_annotations_enabled",
    "node_view_is_current",
    "node_view_metrics",
    "organize_node_tree",
    "tidy_effect_group",
]
