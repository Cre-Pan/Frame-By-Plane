"""Pure validation helpers for the Frame By Plane compositor.

The functions in this module deliberately avoid Blender imports so path,
format, graph and depth-split contracts can be tested outside Blender.
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Iterable, Mapping, Sequence

_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
_INVALID_PATH_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')




def safe_path_component(value: object, fallback: str = "Pass", limit: int = 63) -> str:
    """Return a cross-platform output name safe on Windows and POSIX.

    Blender File Output nodes may accept names that the destination filesystem
    rejects later during render.  Normalize once before nodes are mutated so a
    render cannot fail merely because a pass was named ``CON`` or ended in a dot.
    """
    text = re.sub(r"[^\w .-]+", "_", str(value or "").strip(), flags=re.UNICODE)
    text = text.rstrip(" .")[:max(1, int(limit))]
    if not text:
        text = str(fallback or "Pass").strip().rstrip(" .") or "Pass"
    stem = text.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED_NAMES:
        text = f"_{text}"[:max(1, int(limit))]
    return text

def path_component_issues(value: object) -> tuple[str, ...]:
    """Return stable cross-platform warnings for one path component."""
    text = str(value or "").strip()
    issues: list[str] = []
    if not text:
        issues.append("empty")
        return tuple(issues)
    if text in {".", ".."}:
        issues.append("relative-navigation")
    if _INVALID_PATH_CHARS.search(text):
        issues.append("invalid-character")
    stem = text.rstrip(" .").split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED_NAMES:
        issues.append("reserved-name")
    if text.endswith((" ", ".")):
        issues.append("trailing-space-or-dot")
    return tuple(issues)


def split_path_components(value: object) -> tuple[str, ...]:
    return tuple(part for part in re.split(r"[\\/]+", str(value or "")) if part)


def output_format_issues(file_format: object, color_depth: object, color_mode: object) -> tuple[str, ...]:
    """Validate the format subset exposed by FBP Output."""
    fmt = str(file_format or "").upper()
    depth = str(color_depth or "")
    mode = str(color_mode or "").upper()
    issues: list[str] = []
    allowed_depths = {
        "PNG": {"8", "16"},
        "TIFF": {"8", "16"},
        "OPEN_EXR": {"16", "32"},
        "OPEN_EXR_MULTILAYER": {"16", "32"},
    }
    if fmt not in allowed_depths:
        issues.append("unsupported-format")
    elif depth not in allowed_depths[fmt]:
        issues.append("unsupported-depth")
    if mode not in {"RGB", "RGBA"}:
        issues.append("unsupported-color-mode")
    return tuple(issues)


def nearest_existing_parent(path: object) -> str:
    """Return the closest existing directory without creating anything."""
    candidate = os.path.abspath(os.fspath(path or os.curdir))
    while candidate and not os.path.isdir(candidate):
        parent = os.path.dirname(candidate)
        if parent == candidate:
            return ""
        candidate = parent
    return candidate


def normalized_destination(subfolder: object, prefix: object) -> str:
    components = [
        safe_path_component(part, "", 63).casefold()
        for part in split_path_components(subfolder)
        if str(part or "").strip() not in {"", ".", ".."}
    ]
    components.append(safe_path_component(prefix, "Pass", 63).casefold())
    return "/".join(components)


def directed_cycles(graph: Mapping[object, Iterable[object]]) -> tuple[tuple[object, ...], ...]:
    """Return deterministic simple back-edge cycles from a directed graph."""
    visited: set[object] = set()
    active: set[object] = set()
    stack: list[object] = []
    cycles: set[tuple[object, ...]] = set()

    def canonical(nodes: Sequence[object]) -> tuple[object, ...]:
        values = tuple(nodes)
        if not values:
            return values
        rotations = [values[index:] + values[:index] for index in range(len(values))]
        return min(rotations, key=lambda item: tuple(map(str, item)))

    def visit(node: object) -> None:
        if node in active:
            try:
                start = stack.index(node)
            except ValueError:
                return
            cycles.add(canonical(tuple(stack[start:])))
            return
        if node in visited:
            return
        visited.add(node)
        active.add(node)
        stack.append(node)
        for target in graph.get(node, ()):  # deterministic at caller level
            visit(target)
        stack.pop()
        active.remove(node)

    for node in sorted(graph, key=str):
        visit(node)
    return tuple(sorted(cycles, key=lambda item: tuple(map(str, item))))



def combine_uuid_sets(operation: object, left: Iterable[object], right: Iterable[object]) -> frozenset[str]:
    """Combine two persistent UUID selections with deterministic set semantics.

    Values are normalized to non-empty strings so malformed saved data cannot
    leak ``None`` or blank identifiers into derived Layer Sets.
    """
    lhs = frozenset(str(value) for value in left if str(value or ""))
    rhs = frozenset(str(value) for value in right if str(value or ""))
    mode = str(operation or "UNION").upper()
    if mode == "DIFFERENCE":
        return lhs - rhs
    if mode == "INTERSECTION":
        return lhs & rhs
    if mode == "XOR":
        return lhs ^ rhs
    return lhs | rhs

def resolve_uuid_set_memberships(
    base_memberships: Mapping[object, Iterable[object]],
    derived_specs: Mapping[object, Sequence[object]],
    valid_source_ids: Iterable[object],
    unassigned_set_ids: Iterable[object] = (),
) -> dict[str, frozenset[str]]:
    """Resolve normal, derived and Unassigned Layer Sets by persistent UUID.

    ``derived_specs`` values are ``(operation, operand_a_uuid, operand_b_uuid)``.
    Invalid references and circular dependencies resolve to an empty operand;
    callers can report those configuration errors separately without risking
    recursion during compositor synchronization.
    """
    base = {
        str(set_uuid): frozenset(str(value) for value in values if str(value or ""))
        for set_uuid, values in base_memberships.items()
        if str(set_uuid or "")
    }
    derived = {
        str(set_uuid): tuple(spec)
        for set_uuid, spec in derived_specs.items()
        if str(set_uuid or "")
    }
    valid = frozenset(str(value) for value in valid_source_ids if str(value or ""))
    unassigned = frozenset(str(value) for value in unassigned_set_ids if str(value or ""))
    all_ids = set(base) | set(derived) | set(unassigned)
    dependency_graph = {
        set_uuid: tuple(
            str(value)
            for value in spec[1:3]
            if str(value or "") in derived
        )
        for set_uuid, spec in derived.items()
    }
    cyclic_ids = frozenset(
        value
        for cycle in directed_cycles(dependency_graph)
        for value in cycle
    )
    cache: dict[str, frozenset[str]] = {}
    active: set[str] = set()

    def evaluate(set_uuid: object) -> frozenset[str]:
        key = str(set_uuid or "")
        if not key:
            return frozenset()
        if key in cache:
            return cache[key]
        if key in active:
            return frozenset()
        active.add(key)
        try:
            if key in cyclic_ids:
                result = frozenset()
            elif key in derived:
                spec = derived[key]
                operation = spec[0] if len(spec) > 0 else "UNION"
                left = spec[1] if len(spec) > 1 else ""
                right = spec[2] if len(spec) > 2 else ""
                result = combine_uuid_sets(operation, evaluate(left), evaluate(right))
            elif key in unassigned:
                assigned = frozenset()
                for other in sorted(all_ids - unassigned - set(derived), key=str):
                    assigned = assigned | evaluate(other)
                result = valid - assigned
            else:
                result = base.get(key, frozenset()) & valid
        finally:
            active.discard(key)
        cache[key] = frozenset(result)
        return cache[key]

    for set_uuid in sorted(all_ids, key=str):
        evaluate(set_uuid)
    return cache


def depth_split_thresholds(values: Iterable[object]) -> tuple[float, float] | None:
    """Return deterministic near/mid/far boundaries from distinct depths.

    Camera-space depth must increase away from the camera.  At least three
    distinct finite values are required; otherwise an automatic split would be
    arbitrary and is deliberately rejected.
    """
    finite_depths = set()
    for value in values:
        try:
            depth = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(depth):
            finite_depths.add(depth)
    depths = sorted(finite_depths)
    if len(depths) < 3:
        return None
    first_index = max(1, len(depths) // 3)
    second_index = min(len(depths) - 1, max(first_index + 1, (2 * len(depths)) // 3))
    first = (depths[first_index - 1] + depths[first_index]) * 0.5
    second = (depths[second_index - 1] + depths[second_index]) * 0.5
    if not first < second:
        return None
    return first, second
