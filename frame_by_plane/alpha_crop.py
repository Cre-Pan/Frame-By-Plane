"""Alpha-bound scanning helpers for import-time plane cropping.

The scanner is Blender-independent so it can be tested without importing bpy.
It never rewrites source media: it only returns the union of non-zero alpha
pixels that the native backend may map onto the existing Crop geometry.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Iterable


_VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".mpeg", ".mpg", ".mxf", ".ogv",
}
_CACHE_LIMIT = 512
_ALPHA_BOUNDS_CACHE = globals().get("_ALPHA_BOUNDS_CACHE", {})
if not isinstance(_ALPHA_BOUNDS_CACHE, dict):
    _ALPHA_BOUNDS_CACHE = {}


@dataclass(frozen=True)
class AlphaCropResult:
    """Union alpha bounds in top-left pixel coordinates.

    ``right`` and ``bottom`` are exclusive, matching Pillow's bounding boxes.
    ``applied`` is false for opaque/no-alpha, empty, invalid, video, or
    dimension-mismatched inputs.
    """

    width: int = 0
    height: int = 0
    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0
    padding: int = 0
    files_scanned: int = 0
    alpha_files: int = 0
    status: str = "DISABLED"
    detail: str = ""

    @property
    def applied(self) -> bool:
        return self.status == "APPLIED" and self.width > 0 and self.height > 0

    @property
    def crop_fractions(self) -> tuple[float, float, float, float]:
        """Return builder Crop values: left, right, bottom, top in the 0..2 range."""
        if not self.applied:
            return (0.0, 0.0, 0.0, 0.0)
        width = float(max(1, self.width))
        height = float(max(1, self.height))
        crop_left = 2.0 * float(self.left) / width
        crop_right = 2.0 * float(max(0, self.width - self.right)) / width
        crop_top = 2.0 * float(self.top) / height
        crop_bottom = 2.0 * float(max(0, self.height - self.bottom)) / height
        return (crop_left, crop_right, crop_bottom, crop_top)

    @property
    def visible_size(self) -> tuple[int, int]:
        if not self.applied:
            return (self.width, self.height)
        return (max(0, self.right - self.left), max(0, self.bottom - self.top))


def clear_alpha_crop_cache() -> None:
    _ALPHA_BOUNDS_CACHE.clear()


def _cache_key(path: str):
    try:
        stat = os.stat(path)
        return (
            os.path.normcase(os.path.realpath(os.path.abspath(path))),
            int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))),
            int(stat.st_size),
        )
    except OSError:
        return None


def _remember(key, value) -> None:
    if key is None:
        return
    if len(_ALPHA_BOUNDS_CACHE) >= _CACHE_LIMIT and key not in _ALPHA_BOUNDS_CACHE:
        try:
            _ALPHA_BOUNDS_CACHE.pop(next(iter(_ALPHA_BOUNDS_CACHE)))
        except (KeyError, StopIteration):
            _ALPHA_BOUNDS_CACHE.clear()
    _ALPHA_BOUNDS_CACHE[key] = value


def _single_file_alpha_bounds(path: str):
    """Return (width, height, has_alpha, bbox) for one raster image."""
    key = _cache_key(path)
    if key is not None and key in _ALPHA_BOUNDS_CACHE:
        return _ALPHA_BOUNDS_CACHE[key]

    from PIL import Image

    with Image.open(path) as image:
        width, height = (int(image.size[0]), int(image.size[1]))
        bands = tuple(str(band).upper() for band in image.getbands())
        has_alpha = "A" in bands or "transparency" in image.info
        if not has_alpha:
            result = (width, height, False, (0, 0, width, height))
            _remember(key, result)
            return result

        if "A" in bands:
            alpha = image.getchannel("A")
        else:
            # Palette/grayscale transparency is normalized only for the alpha
            # channel. RGB pixels are never converted or written back to disk.
            alpha = image.convert("RGBA").getchannel("A")
        bbox = alpha.getbbox()
        result = (width, height, True, tuple(int(v) for v in bbox) if bbox else None)
        _remember(key, result)
        return result


def scan_alpha_crop_bounds(
    directory: str,
    files: Iterable[str],
    *,
    padding: int = 1,
) -> AlphaCropResult:
    """Scan raster files and return the union of pixels with alpha greater than zero.

    One opaque/no-alpha frame expands the result to the full canvas, which is
    required for an animated sequence that becomes fully visible on that frame.
    Fully transparent frames do not expand the union. Mixed dimensions are not
    cropped because one stable mesh/UV mapping cannot represent them safely.
    """
    padding = max(0, int(padding))
    paths = []
    for value in files or ():
        raw = str(value or "")
        if not raw:
            continue
        path = raw if os.path.isabs(raw) else os.path.join(str(directory or ""), raw)
        path = os.path.abspath(os.path.normpath(path))
        if path not in paths:
            paths.append(path)

    if not paths:
        return AlphaCropResult(status="NO_FILES", padding=padding, detail="No source images were supplied")
    if any(os.path.splitext(path)[1].lower() in _VIDEO_EXTENSIONS for path in paths):
        return AlphaCropResult(status="VIDEO", padding=padding, detail="Video alpha bounds are not scanned")

    expected_size = None
    union = None
    files_scanned = 0
    alpha_files = 0
    try:
        for path in paths:
            if not os.path.isfile(path):
                return AlphaCropResult(
                    status="MISSING", padding=padding, files_scanned=files_scanned,
                    alpha_files=alpha_files, detail=f"Missing source: {path}",
                )
            width, height, has_alpha, bbox = _single_file_alpha_bounds(path)
            files_scanned += 1
            if width <= 0 or height <= 0:
                return AlphaCropResult(
                    status="INVALID_SIZE", padding=padding, files_scanned=files_scanned,
                    alpha_files=alpha_files, detail=f"Invalid image dimensions: {path}",
                )
            if expected_size is None:
                expected_size = (width, height)
            elif expected_size != (width, height):
                return AlphaCropResult(
                    width=expected_size[0], height=expected_size[1], status="MIXED_SIZE",
                    padding=padding, files_scanned=files_scanned, alpha_files=alpha_files,
                    detail="Sequence frames do not share one canvas size",
                )

            if not has_alpha:
                return AlphaCropResult(
                    width=width, height=height, left=0, top=0, right=width, bottom=height,
                    padding=padding, files_scanned=files_scanned, alpha_files=alpha_files,
                    status="FULL_CANVAS", detail="At least one frame has no alpha channel",
                )
            alpha_files += 1
            if bbox is None:
                continue
            if union is None:
                union = list(bbox)
            else:
                union[0] = min(union[0], bbox[0])
                union[1] = min(union[1], bbox[1])
                union[2] = max(union[2], bbox[2])
                union[3] = max(union[3], bbox[3])
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        width, height = expected_size or (0, 0)
        return AlphaCropResult(
            width=width, height=height, padding=padding, files_scanned=files_scanned,
            alpha_files=alpha_files, status="ERROR", detail=str(exc),
        )

    width, height = expected_size or (0, 0)
    if union is None:
        return AlphaCropResult(
            width=width, height=height, padding=padding, files_scanned=files_scanned,
            alpha_files=alpha_files, status="EMPTY_ALPHA",
            detail="All scanned frames are fully transparent",
        )

    left = max(0, int(union[0]) - padding)
    top = max(0, int(union[1]) - padding)
    right = min(width, int(union[2]) + padding)
    bottom = min(height, int(union[3]) + padding)
    if left <= 0 and top <= 0 and right >= width and bottom >= height:
        return AlphaCropResult(
            width=width, height=height, left=0, top=0, right=width, bottom=height,
            padding=padding, files_scanned=files_scanned, alpha_files=alpha_files,
            status="FULL_CANVAS", detail="Visible pixels already reach the canvas border",
        )

    return AlphaCropResult(
        width=width, height=height, left=left, top=top, right=right, bottom=bottom,
        padding=padding, files_scanned=files_scanned, alpha_files=alpha_files,
        status="APPLIED", detail="Transparent outer borders can be cropped safely",
    )
