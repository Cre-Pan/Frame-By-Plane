"""Alpha-driven outlines for the Frame By Plane control rig and Crop Alpha.

The helpers here are Blender-independent: they work on an occupancy mask (a
NumPy boolean array, row 0 at the top of the image) so they can be tested
without ``bpy``. ``builder`` decides where the alpha comes from (source files
on disk through Pillow, or the pixels of a packed/generated Blender image)
and maps the returned outline into rig space.

Two outline styles are produced:

* ``PIXEL`` follows the edges of the occupied cells, giving a stepped,
  pixel-art friendly silhouette.
* ``SMOOTH`` runs marching squares on a softened mask and smooths the
  contour into continuous curves; straight runs stay straight, pixel steps
  become curves and real corners stay sharp.
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
# Long side of single-frame masks used by Follow Frame (cheaper, cached more).
FBP_ALPHA_FRAME_MAX_SIDE = 512
# Default outline resolution (cells on the long side of the visible region).
FBP_ALPHA_OUTLINE_CELLS = 64
# Sequences are sampled evenly beyond this many frames.
FBP_ALPHA_MAX_FRAMES = 96
_VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".mpeg", ".mpg", ".mxf", ".ogv",
}
# Click selection ignores faint pixels and specks: a pixel counts as solid at
# this opacity, and a click needs solid coverage around it (see ``solid_at``).
FBP_ALPHA_PICK_MIN_OPACITY = 0.15
FBP_ALPHA_PICK_MAX_SIDE = 512
# Pick window radius as a fraction of the image long side, and the share of
# it (and of the clicked cell) that must be solid.
FBP_ALPHA_PICK_WINDOW = 0.006
FBP_ALPHA_PICK_WINDOW_SHARE = 0.2
FBP_ALPHA_PICK_CELL_SHARE = 0.25
_UNION_CACHE_LIMIT = 160
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

    __slots__ = ("mask", "width", "height", "exact_bbox", "has_alpha", "solid")

    def __init__(self, mask, width, height, exact_bbox, has_alpha=True, solid=None):
        self.mask = mask
        # Share of solid pixels per cell (uint8 0..255, rows top-down) at
        # most FBP_ALPHA_PICK_MAX_SIDE on its long side; used by click picks.
        self.solid = solid
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


def _coverage(mask, max_side: int = FBP_ALPHA_PICK_MAX_SIDE):
    """Share of True pixels per cell as uint8 (0..255)."""
    _require_numpy()
    height, width = mask.shape
    factor = max(1, int(-(-max(width, height) // max_side)))
    out_h = int(-(-height // factor))
    out_w = int(-(-width // factor))
    padded = np.zeros((out_h * factor, out_w * factor), dtype=np.uint16)
    padded[:height, :width] = mask
    total = padded.reshape(out_h, factor, out_w, factor).sum(axis=(1, 3), dtype=np.uint32)
    return np.minimum(255, (total * 255) // (factor * factor)).astype(np.uint8)


def _merge_solid(current, frame):
    if current is None:
        return frame
    if current.shape != frame.shape:
        return current
    return np.maximum(current, frame)


def solid_at(union: AlphaUnion, u: float, v: float):
    """True when a click at UV (u, v) lands on a solid mass of pixels.

    Faint pixels (below FBP_ALPHA_PICK_MIN_OPACITY) never count, and a click
    on a few scattered or very thin pixels is rejected so it reaches the
    layer behind. ``None`` when the union carries no solid coverage.
    """
    solid = getattr(union, "solid", None)
    if solid is None:
        return None
    rows, cols = solid.shape
    col = min(cols - 1, max(0, int(float(u) * cols)))
    row = min(rows - 1, max(0, int((1.0 - float(v)) * rows)))
    if int(solid[row, col]) < FBP_ALPHA_PICK_CELL_SHARE * 255.0:
        return False
    radius = max(1, int(round(max(rows, cols) * FBP_ALPHA_PICK_WINDOW)))
    window = solid[max(0, row - radius): row + radius + 1, max(0, col - radius): col + radius + 1]
    return float(window.mean()) >= FBP_ALPHA_PICK_WINDOW_SHARE * 255.0


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
    solid = None
    for mask in masks:
        mask = np.asarray(mask, dtype=bool)
        if union is None:
            union = mask.copy()
        elif union.shape != mask.shape:
            raise ValueError("Frames do not share one canvas size")
        else:
            union |= mask
        solid = _merge_solid(solid, _coverage(mask))
    if union is None:
        return None
    height, width = union.shape
    return AlphaUnion(_downsample_any(union, max_side), width, height, _bbox_of(union), True, solid)


def alpha_union_from_rgba(pixels, width: int, height: int, *, threshold: float = 0.0,
                          max_side: int = FBP_ALPHA_UNION_MAX_SIDE):
    """Build a union from Blender ``Image.pixels`` (RGBA floats, rows bottom-up)."""
    _require_numpy()
    width = int(width)
    height = int(height)
    data = np.asarray(pixels, dtype=np.float32)
    if width <= 0 or height <= 0 or data.size < width * height * 4:
        return None
    alpha = np.flipud(data[: width * height * 4].reshape(height, width, 4)[:, :, 3])
    union = alpha_union_from_masks((alpha > float(threshold),), max_side=max_side)
    if union is not None:
        union.solid = _coverage(alpha >= FBP_ALPHA_PICK_MIN_OPACITY)
    return union


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
            return width, height, None, None
        values = np.asarray(alpha, dtype=np.uint8)
        return width, height, values > 0, values >= int(round(FBP_ALPHA_PICK_MIN_OPACITY * 255.0))


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
    solid = None
    size = None
    has_alpha = True
    for path in sampled:
        width, height, mask, solid_mask = _file_mask(path)
        if size is None:
            size = (width, height)
        elif size != (width, height):
            return None
        if mask is None:
            has_alpha = False
            mask = np.ones((height, width), dtype=bool)
            solid_mask = mask
        union = mask if union is None else (union | mask)
        solid = _merge_solid(solid, _coverage(solid_mask))
    if union is None:
        return None
    result = AlphaUnion(
        _downsample_any(union, max_side), size[0], size[1], _bbox_of(union), has_alpha, solid
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

    codes = (
        (inside[:-1, :-1].astype(np.int8) << 3)
        | (inside[:-1, 1:].astype(np.int8) << 2)
        | (inside[1:, 1:].astype(np.int8) << 1)
        | inside[1:, :-1].astype(np.int8)
    )
    # Only cells the contour crosses need work; skip the solid and empty ones.
    for r, c in zip(*np.nonzero((codes != 0) & (codes != 15))):
        r = int(r)
        c = int(c)
        code = int(codes[r, c])
        tl, tr = bool(code & 8), bool(code & 4)
        br, bl = bool(code & 2), bool(code & 1)
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


def _douglas_peucker(points, tolerance):
    """Simplify an open polyline, keeping both ends."""
    if len(points) <= 2:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        (ax, ay), (bx, by) = points[first], points[last]
        dx, dy = bx - ax, by - ay
        length = (dx * dx + dy * dy) ** 0.5
        best, best_index = -1.0, -1
        for index in range(first + 1, last):
            px, py = points[index]
            if length > 1e-12:
                distance = abs(dx * (ay - py) - dy * (ax - px)) / length
            else:
                distance = ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
            if distance > best:
                best, best_index = distance, index
        if best_index >= 0 and best > tolerance:
            keep[best_index] = True
            stack.append((first, best_index))
            stack.append((best_index, last))
    return [point for point, flag in zip(points, keep) if flag]


def _simplify_closed(loop, tolerance):
    """Douglas-Peucker for a closed loop, split at the two farthest points."""
    if len(loop) <= 4:
        return list(loop)
    x0, y0 = loop[0]
    far = max(range(len(loop)), key=lambda i: (loop[i][0] - x0) ** 2 + (loop[i][1] - y0) ** 2)
    first = _douglas_peucker(loop[: far + 1], tolerance)
    second = _douglas_peucker(loop[far:] + [loop[0]], tolerance)
    out = first[:-1] + second[:-1]
    return out if len(out) >= 4 else list(loop)


def _resample_closed(loop, step):
    """Resample a closed polyline at an even arc-length spacing."""
    pts = np.asarray(loop + [loop[0]], dtype=np.float64)
    seg = np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))
    total = float(seg.sum())
    if total <= 1e-9:
        return np.asarray(loop, dtype=np.float64)
    count = max(8, int(round(total / max(1e-6, step))))
    dist = np.concatenate(([0.0], np.cumsum(seg)))
    targets = np.linspace(0.0, total, count, endpoint=False)
    xs = np.interp(targets, dist, pts[:, 0])
    ys = np.interp(targets, dist, pts[:, 1])
    return np.stack((xs, ys), axis=1)


def _gaussian_closed(points, sigma):
    """Circular Gaussian smoothing of a closed contour (keeps straight runs straight)."""
    count = len(points)
    radius = int(max(1, round(sigma * 3.0)))
    if count <= radius * 2 + 1:
        radius = max(1, (count - 1) // 2)
    offsets = np.arange(-radius, radius + 1)
    weights = np.exp(-0.5 * (offsets / max(1e-6, sigma)) ** 2)
    weights /= weights.sum()
    out = np.zeros_like(points)
    for offset, weight in zip(offsets, weights):
        out += weight * np.roll(points, -int(offset), axis=0)
    return out


def _turning_angles(points, window):
    """Turn (radians) at each sample, measured between chords ``window`` apart.

    Measuring across a window ignores pixel stair steps (they alternate and
    cancel) and keeps real corners, which turn in one direction.
    """
    before = points - np.roll(points, window, axis=0)
    after = np.roll(points, -window, axis=0) - points
    cross = before[:, 0] * after[:, 1] - before[:, 1] * after[:, 0]
    dot = (before * after).sum(axis=1)
    return np.abs(np.arctan2(cross, dot))


def _find_corners(points, window, threshold):
    """Indices of corner samples: local maxima of the turn above ``threshold``."""
    angles = _turning_angles(points, window)
    count = len(points)
    flagged = angles > threshold
    if not flagged.any():
        return []
    if flagged.all():
        return []
    corners = []
    start = int(np.flatnonzero(~flagged)[0])
    index = 0
    while index < count:
        position = (start + index) % count
        if flagged[position]:
            run = []
            while index < count and flagged[(start + index) % count]:
                run.append((start + index) % count)
                index += 1
            corners.append(max(run, key=lambda item: angles[item]))
        else:
            index += 1
    return sorted(corners)


def _corner_point(points, index, window):
    """Sharp corner where the straight runs on both sides of ``index`` meet."""
    count = len(points)
    a0 = points[(index - 2 * window) % count]
    a1 = points[(index - window) % count]
    b0 = points[(index + window) % count]
    b1 = points[(index + 2 * window) % count]
    da = a1 - a0
    db = b1 - b0
    denom = da[0] * db[1] - da[1] * db[0]
    if abs(denom) < 1e-9:
        return points[index]
    t = ((b0[0] - a0[0]) * db[1] - (b0[1] - a0[1]) * db[0]) / denom
    hit = a0 + da * t
    reach = float(np.hypot(*(b0 - a1))) + float(np.hypot(*da))
    if float(np.hypot(*(hit - points[index]))) > reach:
        return points[index]
    return hit


def _gaussian_open(points, sigma):
    """Gaussian smoothing of an open run with its two ends held in place."""
    count = len(points)
    if count < 3:
        return points
    radius = int(max(1, round(sigma * 3.0)))
    offsets = np.arange(-radius, radius + 1)
    weights = np.exp(-0.5 * (offsets / max(1e-6, sigma)) ** 2)
    weights /= weights.sum()
    padded = np.concatenate((
        np.repeat(points[:1], radius, axis=0), points, np.repeat(points[-1:], radius, axis=0),
    ))
    out = np.zeros_like(points)
    for offset, weight in zip(offsets, weights):
        out += weight * padded[radius + offset: radius + offset + count]
    out[0] = points[0]
    out[-1] = points[-1]
    return out


def _smooth_with_corners(dense, step, sigma_cells, corners, window):
    """Smooth a closed contour, keeping the given corner samples sharp."""
    if not corners or len(dense) < window * 6:
        return _gaussian_closed(dense, sigma_cells / step)
    count = len(dense)
    corners = sorted(set(int(index) % count for index in corners))
    sharp = {index: _corner_point(dense, index, window) for index in corners}
    result = []
    for position, corner in enumerate(corners):
        nxt = corners[(position + 1) % len(corners)]
        span = (nxt - corner) % count or count
        # Skip the rounded transition right next to each corner: the run goes
        # straight from the sharp corner into the smoothed edge.
        trim = min(window, max(0, span // 2 - 1))
        run = [dense[(corner + offset) % count] for offset in range(trim, span - trim + 1)]
        if len(run) >= 2:
            run = _gaussian_open(np.asarray(run, dtype=np.float64), sigma_cells / step)
        result.append(sharp[corner])
        result.extend(run)
    return np.asarray(result, dtype=np.float64)


def _dense_loops(grid, step):
    loops = _marching_squares_loops(_soften(grid))
    # Field sample (r, c) is the centre of padded cell c; lattice x = c - 1 + 0.5.
    return [_resample_closed([(x - 0.5, y - 0.5) for x, y in loop], step) for loop in loops]


def smooth_outline(grid, *, grow=0, step=0.5, sigma_cells=2.2, tolerance=0.015,
                   corner_window_cells=2.5, corner_angle=0.95):
    """Return (points, edges) of smooth closed curves around occupied cells.

    Marching squares gives the iso contour; it is resampled evenly and
    smoothed: straight runs stay straight, pixel steps and soft bends become
    curves, and real corners (a sustained turn, like a box corner) stay sharp.
    Corners are found on the silhouette itself and carried onto the outline
    grown by ``grow`` cells, so Expand does not round them off.
    """
    _require_numpy()
    grow = max(0, int(grow))
    base_window = max(2, int(round(corner_window_cells / step)))
    corner_points = []
    for dense in _dense_loops(grid, step):
        if len(dense) < base_window * 6:
            continue
        for index in _find_corners(dense, base_window, corner_angle):
            corner_points.append(_corner_point(dense, index, base_window) + grow)
    target = dilate(grid, grow) if grow else grid
    window = max(base_window, int(np.ceil((grow * 1.2 + 1.0) / step))) if grow else base_window
    reach = grow * 1.6 + 1.5
    points = []
    edges = []
    for dense in (_dense_loops(target, step) if grow else _dense_loops(grid, step)):
        corners = []
        turns = _turning_angles(dense, window) if len(dense) > window * 2 else None
        for corner in corner_points:
            distances = np.hypot(dense[:, 0] - corner[0], dense[:, 1] - corner[1])
            nearest = int(np.argmin(distances))
            if float(distances[nearest]) > reach or turns is None:
                continue
            # Keep only corners the grown outline still turns at; corners
            # swallowed by Expand (e.g. where two shapes merge) stay smooth.
            if float(turns[nearest]) < corner_angle * 0.8:
                continue
            corners.append(nearest)
        if corners and turns is not None:
            # Two corners closer than the tangent window would fight each
            # other: keep the sharper one.
            corners = sorted(set(corners), key=lambda index: -float(turns[index]))
            kept = []
            count = len(dense)
            for index in corners:
                if all(min((index - other) % count, (other - index) % count) >= window for other in kept):  # noqa: E501
                    kept.append(index)
            corners = kept
        curve = _smooth_with_corners(dense, step, sigma_cells, corners, window)
        curve = _simplify_closed([(float(x), float(y)) for x, y in curve], tolerance)
        start = len(points)
        points.extend(curve)
        count = len(curve)
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
    if str(style or "PIXEL").upper() == "SMOOTH":
        points, edges = smooth_outline(grid, grow=steps)
    else:
        points, edges = pixel_outline(dilate(grid, steps))
    if not points or not edges:
        return None
    mapped = [
        (x0 + (px - steps) * cell_w, y1 - (py - steps) * cell_h)
        for px, py in points
    ]
    return mapped, list(edges)
