"""Alpha-driven outlines for the Frame By Plane control rig and Crop Alpha.

The helpers here are Blender-independent: they work on an occupancy mask (a
NumPy boolean array, row 0 at the top of the image) so they can be tested
without ``bpy``. ``builder`` decides where the alpha comes from (source files
on disk through Pillow, or the pixels of a packed/generated Blender image)
and maps the returned outline into rig space.

Two outline styles are produced:

* ``PIXEL`` follows the edges of the occupied cells, giving a stepped,
  pixel-art friendly silhouette.
* ``SMOOTH`` runs marching squares on a softened mask and rounds the result
  with Chaikin subdivision, giving a curve-like silhouette.
"""

from __future__ import annotations

import os
from typing import Iterable, Sequence

try:  # NumPy ships with Blender; keep import errors explicit for tests.
    import numpy as np
except ImportError:  # pragma: no cover - Blender always provides NumPy.
    np = None


# Long side of the cached full-canvas alpha union. Large enough for a precise
# Crop Alpha and outline, small enough to keep memory and drag updates cheap.
FBP_ALPHA_UNION_MAX_SIDE = 1024
# Default outline resolution (cells on the long side of the visible region).
FBP_ALPHA_OUTLINE_CELLS = 64
# Sequences are sampled evenly beyond this many frames.
FBP_ALPHA_MAX_FRAMES = 96
_VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".mpeg", ".mpg", ".mxf", ".ogv",
}
_UNION_CACHE_LIMIT = 16
_UNION_CACHE = globals().get("_UNION_CACHE", {})
if not isinstance(_UNION_CACHE, dict):
    _UNION_CACHE = {}


class AlphaUnion:
    """Union of visible alpha over one or more frames.

    ``mask`` is a boolean array (rows top-down) of at most
    ``FBP_ALPHA_UNION_MAX_SIDE`` on its long side. ``width``/``height`` are the
    real source dimensions in pixels. ``exact_bbox`` is the union bounding box
    in real pixels (left, top, right, bottom; right/bottom exclusive) measured
    on the full-resolution alpha, or ``None`` when every frame is empty.
    """

    __slots__ = ("mask", "width", "height", "exact_bbox", "has_alpha")

    def __init__(self, mask, width, height, exact_bbox, has_alpha=True):
        self.mask = mask
        self.width = int(width)
        self.height = int(height)
        self.exact_bbox = tuple(int(v) for v in exact_bbox) if exact_bbox else None
        self.has_alpha = bool(has_alpha)


def _require_numpy():
    if np is None:
        raise ImportError("NumPy is required for alpha outlines")


def _sample_paths(paths: Sequence[str], limit: int = FBP_ALPHA_MAX_FRAMES) -> list[str]:
    paths = list(paths)
    if len(paths) <= limit:
        return paths
    step = (len(paths) - 1) / float(limit - 1)
    picked = []
    for index in range(limit):
        path = paths[int(round(index * step))]
        if not picked or picked[-1] != path:
            picked.append(path)
    return picked


def _downsample_any(mask, max_side: int):
    """Shrink a boolean mask so a cell is True when any covered pixel is."""
    _require_numpy()
    height, width = mask.shape
    longest = max(width, height)
    if longest <= max_side:
        return mask.copy()
    factor = int(-(-longest // max_side))
    out_h = int(-(-height // factor))
    out_w = int(-(-width // factor))
    padded = np.zeros((out_h * factor, out_w * factor), dtype=bool)
    padded[:height, :width] = mask
    return padded.reshape(out_h, factor, out_w, factor).any(axis=(1, 3))


def _bbox_of(mask):
    rows = np.flatnonzero(mask.any(axis=1))
    if rows.size == 0:
        return None
    cols = np.flatnonzero(mask.any(axis=0))
    return (int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1)


def alpha_union_from_masks(masks: Iterable, *, max_side: int = FBP_ALPHA_UNION_MAX_SIDE):
    """Combine full-resolution boolean masks (rows top-down) of one size."""
    _require_numpy()
    union = None
    for mask in masks:
        mask = np.asarray(mask, dtype=bool)
        if union is None:
            union = mask.copy()
        elif union.shape != mask.shape:
            raise ValueError("Frames do not share one canvas size")
        else:
            union |= mask
    if union is None:
        return None
    height, width = union.shape
    return AlphaUnion(_downsample_any(union, max_side), width, height, _bbox_of(union))


def alpha_union_from_rgba(pixels, width: int, height: int, *, threshold: float = 0.0,
                          max_side: int = FBP_ALPHA_UNION_MAX_SIDE):
    """Build a union from Blender ``Image.pixels`` (RGBA floats, rows bottom-up)."""
    _require_numpy()
    width = int(width)
    height = int(height)
    data = np.asarray(pixels, dtype=np.float32)
    if width <= 0 or height <= 0 or data.size < width * height * 4:
        return None
    alpha = data[: width * height * 4].reshape(height, width, 4)[:, :, 3]
    mask = np.flipud(alpha > float(threshold))
    return alpha_union_from_masks((mask,), max_side=max_side)


def _file_mask(path: str):
    from PIL import Image

    with Image.open(path) as image:
        bands = tuple(str(band).upper() for band in image.getbands())
        width, height = int(image.size[0]), int(image.size[1])
        if "A" in bands:
            alpha = image.getchannel("A")
        elif "transparency" in image.info:
            alpha = image.convert("RGBA").getchannel("A")
        else:
            return width, height, None
        return width, height, np.asarray(alpha, dtype=np.uint8) > 0


def alpha_union_from_paths(paths: Sequence[str], *, max_side: int = FBP_ALPHA_UNION_MAX_SIDE):
    """Union of alpha > 0 over image files. Returns ``None`` when unreadable.

    A frame without an alpha channel makes the whole canvas visible, matching
    the import-time Crop Transparent Borders rule.
    """
    _require_numpy()
    paths = [os.path.abspath(str(path)) for path in paths if str(path or "")]
    if not paths or any(os.path.splitext(path)[1].lower() in _VIDEO_EXTENSIONS for path in paths):
        return None
    sampled = _sample_paths(paths)
    key = []
    for path in sampled:
        try:
            stat = os.stat(path)
        except OSError:
            return None
        key.append((os.path.normcase(path), int(stat.st_mtime_ns), int(stat.st_size)))
    key = (tuple(key), int(max_side))
    cached = _UNION_CACHE.get(key)
    if cached is not None:
        return cached

    union = None
    size = None
    has_alpha = True
    for path in sampled:
        width, height, mask = _file_mask(path)
        if size is None:
            size = (width, height)
        elif size != (width, height):
            return None
        if mask is None:
            has_alpha = False
            mask = np.ones((height, width), dtype=bool)
        union = mask if union is None else (union | mask)
    if union is None:
        return None
    result = AlphaUnion(
        _downsample_any(union, max_side), size[0], size[1], _bbox_of(union), has_alpha
    )
    if len(_UNION_CACHE) >= _UNION_CACHE_LIMIT:
        _UNION_CACHE.pop(next(iter(_UNION_CACHE)))
    _UNION_CACHE[key] = result
    return result


def crop_fractions_for_union(union: AlphaUnion, padding: int = 0):
    """Return Crop values (left, right, bottom, top in the 0..2 range).

    ``None`` means there is nothing visible to crop to.
    """
    if union is None or union.exact_bbox is None:
        return None
    left, top, right, bottom = union.exact_bbox
    padding = max(0, int(padding))
    left = max(0, left - padding)
    top = max(0, top - padding)
    right = min(union.width, right + padding)
    bottom = min(union.height, bottom + padding)
    width = float(max(1, union.width))
    height = float(max(1, union.height))
    return (
        2.0 * left / width,
        2.0 * (union.width - right) / width,
        2.0 * (union.height - bottom) / height,
        2.0 * top / height,
    )


# ---------------------------------------------------------------------------
# Outline extraction
# ---------------------------------------------------------------------------

def region_grid(union: AlphaUnion, uv_rect, cells: int = FBP_ALPHA_OUTLINE_CELLS):
    """Resample the visible UV rectangle of the union to an outline grid.

    ``uv_rect`` is (u0, u1, v0, v1) with v measured bottom-up like Blender UVs.
    Returns a boolean grid (rows top-down) or ``None`` when nothing is visible.
    """
    _require_numpy()
    mask = union.mask
    mh, mw = mask.shape
    u0, u1, v0, v1 = (float(value) for value in uv_rect)
    c0 = max(0, min(mw, int(np.floor(u0 * mw))))
    c1 = max(c0 + 1, min(mw, int(np.ceil(u1 * mw))))
    r0 = max(0, min(mh, int(np.floor((1.0 - v1) * mh))))
    r1 = max(r0 + 1, min(mh, int(np.ceil((1.0 - v0) * mh))))
    region = mask[r0:r1, c0:c1]
    if region.size == 0 or not region.any():
        return None
    rh, rw = region.shape
    longest = max(rw, rh)
    cells = max(4, int(cells))
    if longest <= cells:
        return region.copy()
    gw = max(1, int(round(rw * cells / float(longest))))
    gh = max(1, int(round(rh * cells / float(longest))))
    col_edges = np.linspace(0, rw, gw + 1).astype(int)
    row_edges = np.linspace(0, rh, gh + 1).astype(int)
    grid = np.zeros((gh, gw), dtype=bool)
    for gy in range(gh):
        ra, rb = row_edges[gy], max(row_edges[gy] + 1, row_edges[gy + 1])
        band = region[ra:rb]
        if not band.any():
            continue
        for gx in range(gw):
            ca, cb = col_edges[gx], max(col_edges[gx] + 1, col_edges[gx + 1])
            grid[gy, gx] = bool(band[:, ca:cb].any())
    return grid


def dilate(grid, steps: int):
    """Grow a boolean grid by ``steps`` cells (round neighbourhood), padding it."""
    _require_numpy()
    steps = max(0, int(steps))
    padded = np.pad(grid, steps, mode="constant", constant_values=False)
    if steps == 0:
        return padded
    out = padded.copy()
    height, width = padded.shape
    for dy in range(-steps, steps + 1):
        for dx in range(-steps, steps + 1):
            if (dx == 0 and dy == 0) or dx * dx + dy * dy > steps * steps + steps:
                continue
            shifted = np.zeros_like(padded)
            ys = slice(max(0, dy), height + min(0, dy))
            yd = slice(max(0, -dy), height + min(0, -dy))
            xs = slice(max(0, dx), width + min(0, dx))
            xd = slice(max(0, -dx), width + min(0, -dx))
            shifted[ys, xs] = padded[yd, xd]
            out |= shifted
    return out


def _merge_collinear(points, edges):
    """Collapse straight runs of degree-2 vertices in an axis-aligned wire."""
    neighbours = {index: [] for index in range(len(points))}
    for a, b in edges:
        neighbours[a].append(b)
        neighbours[b].append(a)

    def straight(index):
        links = neighbours[index]
        if len(links) != 2:
            return False
        (ax, ay), (px, py), (bx, by) = points[links[0]], points[index], points[links[1]]
        return abs((px - ax) * (by - py) - (py - ay) * (bx - px)) < 1e-9

    keep = [not straight(index) for index in range(len(points))]
    # A loop made only of collinear points cannot exist; still guard it.
    if not any(keep):
        return points, edges
    new_index = {}
    out_points = []
    for index, flag in enumerate(keep):
        if flag:
            new_index[index] = len(out_points)
            out_points.append(points[index])
    out_edges = set()
    visited = set()
    for start in range(len(points)):
        if not keep[start]:
            continue
        for first in neighbours[start]:
            if (start, first) in visited:
                continue
            prev, current = start, first
            visited.add((start, first))
            while not keep[current]:
                links = neighbours[current]
                nxt = links[0] if links[0] != prev else links[1]
                visited.add((current, nxt))
                prev, current = current, nxt
            visited.add((current, prev))
            a, b = new_index[start], new_index[current]
            if a != b:
                out_edges.add((min(a, b), max(a, b)))
    return out_points, sorted(out_edges)


def pixel_outline(grid):
    """Return (points, edges) along the borders of occupied cells.

    Points are lattice coordinates (x right, y down) on the grid corners.
    """
    _require_numpy()
    height, width = grid.shape
    padded = np.pad(grid, 1, mode="constant", constant_values=False)
    index = {}
    points = []
    edges = []

    def vid(x, y):
        key = (x, y)
        found = index.get(key)
        if found is None:
            found = index[key] = len(points)
            points.append((float(x), float(y)))
        return found

    # Horizontal edges: between row y-1 and row y.
    horizontal = padded[1:, 1:-1] != padded[:-1, 1:-1]
    for y, x in zip(*np.nonzero(horizontal)):
        edges.append((vid(int(x), int(y)), vid(int(x) + 1, int(y))))
    # Vertical edges: between column x-1 and column x.
    vertical = padded[1:-1, 1:] != padded[1:-1, :-1]
    for y, x in zip(*np.nonzero(vertical)):
        edges.append((vid(int(x), int(y)), vid(int(x), int(y) + 1)))
    if not edges:
        return [], []
    return _merge_collinear(points, edges)


def _soften(grid):
    """3x3 box blur of a boolean grid as floats, preserving the padded border."""
    field = np.pad(grid.astype(np.float32), 1, mode="constant", constant_values=0.0)
    acc = np.zeros_like(field)
    height, width = field.shape
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            shifted = np.zeros_like(field)
            ys = slice(max(0, dy), height + min(0, dy))
            yd = slice(max(0, -dy), height + min(0, -dy))
            xs = slice(max(0, dx), width + min(0, dx))
            xd = slice(max(0, -dx), width + min(0, -dx))
            shifted[ys, xs] = field[yd, xd]
            acc += shifted
    # Weight the centre so single cells survive the 0.5 iso line.
    return (acc / 9.0) * 0.5 + field * 0.5


def _marching_squares_loops(field, iso=0.5):
    """Closed contour loops of ``field`` at ``iso``; field border must be below iso.

    Sample (row r, column c) sits at the centre of cell (c + 0.5, r + 0.5) in
    lattice coordinates of the unpadded grid shifted by the padding of one.
    """
    height, width = field.shape
    inside = field >= iso

    def crossing(edge):
        kind, r, c = edge
        if kind == "h":  # between (r, c) and (r, c + 1)
            a, b = field[r, c], field[r, c + 1]
            t = 0.5 if a == b else (iso - a) / (b - a)
            return (c + t, float(r))
        a, b = field[r, c], field[r + 1, c]  # between (r, c) and (r + 1, c)
        t = 0.5 if a == b else (iso - a) / (b - a)
        return (float(c), r + t)

    links = {}

    def link(a, b):
        links.setdefault(a, []).append(b)
        links.setdefault(b, []).append(a)

    for r in range(height - 1):
        for c in range(width - 1):
            tl, tr = inside[r, c], inside[r, c + 1]
            bl, br = inside[r + 1, c], inside[r + 1, c + 1]
            code = (tl << 3) | (tr << 2) | (br << 1) | int(bl)
            if code in (0, 15):
                continue
            top = ("h", r, c)
            bottom = ("h", r + 1, c)
            left = ("v", r, c)
            right = ("v", r, c + 1)
            if code in (5, 10):
                centre = (field[r, c] + field[r, c + 1] + field[r + 1, c] + field[r + 1, c + 1]) / 4.0
                joined = centre >= iso
                if code == 5:  # tr and bl inside
                    if joined:
                        link(top, left)
                        link(bottom, right)
                    else:
                        link(top, right)
                        link(bottom, left)
                else:  # tl and br inside
                    if joined:
                        link(top, right)
                        link(bottom, left)
                    else:
                        link(top, left)
                        link(bottom, right)
                continue
            crossed = []
            if tl != tr:
                crossed.append(top)
            if tr != br:
                crossed.append(right)
            if bl != br:
                crossed.append(bottom)
            if tl != bl:
                crossed.append(left)
            if len(crossed) == 2:
                link(crossed[0], crossed[1])

    loops = []
    seen = set()
    for start in links:
        if start in seen:
            continue
        loop = [start]
        seen.add(start)
        prev, current = None, start
        while True:
            options = [item for item in links[current] if item != prev]
            nxt = None
            for option in options:
                if option not in seen:
                    nxt = option
                    break
            if nxt is None:
                break
            seen.add(nxt)
            loop.append(nxt)
            prev, current = current, nxt
        if len(loop) >= 3:
            loops.append([crossing(edge) for edge in loop])
    return loops


def _chaikin(loop, iterations=2):
    for _ in range(max(0, int(iterations))):
        out = []
        count = len(loop)
        for index in range(count):
            (ax, ay), (bx, by) = loop[index], loop[(index + 1) % count]
            out.append((ax * 0.75 + bx * 0.25, ay * 0.75 + by * 0.25))
            out.append((ax * 0.25 + bx * 0.75, ay * 0.25 + by * 0.75))
        loop = out
    return loop


def _simplify_loop(loop, tolerance):
    """Drop points that sit almost on the line between their neighbours."""
    if len(loop) <= 8:
        return loop
    out = list(loop)
    changed = True
    while changed and len(out) > 8:
        changed = False
        result = []
        count = len(out)
        index = 0
        while index < count:
            prev = result[-1] if result else out[-1]
            point = out[index]
            nxt = out[(index + 1) % count]
            dx, dy = nxt[0] - prev[0], nxt[1] - prev[1]
            length = (dx * dx + dy * dy) ** 0.5
            if length > 1e-12:
                distance = abs(dx * (prev[1] - point[1]) - dy * (prev[0] - point[0])) / length
                if distance < tolerance and index % 2 == 1:
                    changed = True
                    index += 1
                    continue
            result.append(point)
            index += 1
        out = result
    return out


def smooth_outline(grid, *, smoothing=2):
    """Return (points, edges) of rounded closed loops around occupied cells."""
    _require_numpy()
    field = _soften(grid)
    loops = _marching_squares_loops(field)
    points = []
    edges = []
    for loop in loops:
        # Field sample (r, c) is the centre of padded cell c; lattice x = c - 1 + 0.5.
        loop = [(x - 0.5, y - 0.5) for x, y in loop]
        loop = _simplify_loop(_chaikin(loop, smoothing), 0.02)
        start = len(points)
        points.extend(loop)
        count = len(loop)
        edges.extend((start + i, start + (i + 1) % count) for i in range(count))
    return points, edges


def outline_for_union(union: AlphaUnion, uv_rect, bounds, *, style="PIXEL",
                      margin=0.0, cells=FBP_ALPHA_OUTLINE_CELLS):
    """Return plane-local (x, y) points and edges outlining the visible alpha.

    ``bounds`` is the plane-local (x0, x1, y0, y1) rectangle showing ``uv_rect``.
    ``margin`` grows the silhouette in plane-local units, like Rig Shape Expand.
    Returns ``None`` when there is nothing visible.
    """
    grid = region_grid(union, uv_rect, cells=cells)
    if grid is None:
        return None
    x0, x1, y0, y1 = (float(value) for value in bounds)
    gh, gw = grid.shape
    cell_w = (x1 - x0) / float(gw)
    cell_h = (y1 - y0) / float(gh)
    cell = max(1e-9, min(abs(cell_w), abs(cell_h)))
    steps = int(round(max(0.0, float(margin)) / cell)) if margin else 0
    grown = dilate(grid, steps)
    if str(style or "PIXEL").upper() == "SMOOTH":
        points, edges = smooth_outline(grown)
    else:
        points, edges = pixel_outline(grown)
    if not points or not edges:
        return None
    mapped = [
        (x0 + (px - steps) * cell_w, y1 - (py - steps) * cell_h)
        for px, py in points
    ]
    return mapped, list(edges)
