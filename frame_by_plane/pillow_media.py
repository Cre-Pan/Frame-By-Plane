"""Pillow-backed media conversion and non-destructive sequence analysis."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import re
from typing import Callable


FBP_PILLOW_CONVERT_EXTENSIONS = frozenset({".avif"})
FBP_PILLOW_ANIMATED_EXTENSIONS = frozenset({".avif", ".gif", ".png", ".webp"})
_CACHE_SCHEMA = 1
_SAFE_STEM_RE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_ANIMATION_FRAMES = 4096
_MAX_FRAME_PIXELS = 268_435_456
_MAX_TOTAL_FRAME_PIXELS = 536_870_912


@dataclass(frozen=True, slots=True)
class FBPPreparedMedia:
    output_directory: str
    files: tuple[str, ...]
    durations: tuple[int, ...]
    source_path: str
    source_format: str
    cache_key: str
    animated: bool
    reused_cache: bool
    source_durations_ms: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class FBPSequenceOptimizationStats:
    source_rows: int
    output_rows: int
    analyzed_rows: int
    collapsed_rows: int
    transparent_rows: int
    unreadable_paths: tuple[str, ...]


def fbp_default_pillow_cache_root(source_path: str) -> str:
    source_path = os.path.abspath(os.fspath(source_path))
    return os.path.join(os.path.dirname(source_path), ".fbp_media_cache")


def fbp_quantize_frame_durations(durations_ms, fps: float) -> tuple[int, ...]:
    """Convert millisecond timings to integer scene frames without cumulative drift."""
    rate = max(0.001, float(fps or 0.0))
    cumulative_ms = 0.0
    emitted_frames = 0
    result = []
    for raw_duration in durations_ms:
        duration_ms = max(1.0, float(raw_duration or 0.0))
        cumulative_ms += duration_ms
        target_end = max(
            emitted_frames + 1,
            int(round((cumulative_ms * rate) / 1000.0)),
        )
        result.append(target_end - emitted_frames)
        emitted_frames = target_end
    return tuple(result)


def _source_digest(path: str) -> str:
    real_path = os.path.realpath(path)
    stat = os.stat(real_path)
    payload = "\0".join(
        (
            os.path.normcase(real_path),
            str(int(stat.st_size)),
            str(int(getattr(stat, "st_mtime_ns", 0))),
            str(int(getattr(stat, "st_ctime_ns", 0))),
            str(int(getattr(stat, "st_dev", 0))),
            str(int(getattr(stat, "st_ino", 0))),
        )
    ).encode("utf-8", "surrogatepass")
    return hashlib.sha256(payload).hexdigest()


def _safe_stem(path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    return _SAFE_STEM_RE.sub("_", stem).strip("._") or "Media"


def _load_prepared_cache(
    manifest_path: str,
    *,
    source_path: str,
    source_digest: str,
    fps: float,
) -> FBPPreparedMedia | None:
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if int(payload.get("schema", 0)) != _CACHE_SCHEMA:
            return None
        if os.path.normcase(str(payload.get("source_path", ""))) != os.path.normcase(source_path):
            return None
        if str(payload.get("source_digest", "")) != source_digest:
            return None
        if abs(float(payload.get("fps", 0.0)) - float(fps)) > 1e-6:
            return None
        output_directory = os.path.dirname(manifest_path)
        files = tuple(str(value) for value in payload.get("files", ()))
        durations = tuple(max(1, int(value)) for value in payload.get("durations", ()))
        source_durations = tuple(float(value) for value in payload.get("source_durations_ms", ()))
        if not files or len(files) != len(durations):
            return None
        if not all(os.path.isfile(os.path.join(output_directory, name)) for name in files):
            return None
        return FBPPreparedMedia(
            output_directory=output_directory,
            files=files,
            durations=durations,
            source_path=source_path,
            source_format=str(payload.get("source_format", "IMAGE") or "IMAGE"),
            cache_key=str(payload.get("cache_key", "") or ""),
            animated=bool(payload.get("animated", False)),
            reused_cache=True,
            source_durations_ms=source_durations,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def fbp_prepare_pillow_media(
    source_path: str,
    *,
    cache_root: str | None = None,
    fps: float = 24.0,
) -> FBPPreparedMedia | None:
    """Extract animated GIF/WebP/AVIF or convert static AVIF to cached PNG files.

    ``None`` means the source can continue through Blender's native image loader.
    The original file is never modified.
    """
    source_path = os.path.abspath(os.fspath(source_path))
    extension = os.path.splitext(source_path)[1].lower()
    if extension not in FBP_PILLOW_ANIMATED_EXTENSIONS | FBP_PILLOW_CONVERT_EXTENSIONS:
        return None
    if not os.path.isfile(source_path):
        raise FileNotFoundError(source_path)

    from PIL import Image

    with Image.open(source_path) as source:
        frame_count = max(1, int(getattr(source, "n_frames", 1) or 1))
        animated = frame_count > 1 and extension in FBP_PILLOW_ANIMATED_EXTENSIONS
        if not animated and extension not in FBP_PILLOW_CONVERT_EXTENSIONS:
            return None
        width, height = (max(1, int(value)) for value in source.size)
        frame_pixels = width * height
        if frame_count > _MAX_ANIMATION_FRAMES:
            raise ValueError(f"Animation has {frame_count} frames; limit is {_MAX_ANIMATION_FRAMES}")
        if frame_pixels > _MAX_FRAME_PIXELS:
            raise ValueError(f"Image has {frame_pixels:,} pixels; limit is {_MAX_FRAME_PIXELS:,}")
        if frame_pixels * frame_count > _MAX_TOTAL_FRAME_PIXELS:
            raise ValueError("Decoded animation would exceed the Frame By Plane safety limit")
        source_format = str(getattr(source, "format", "") or extension.lstrip(".")).upper()

    fps = max(0.001, float(fps or 0.0))
    cache_fps = fps if animated else 0.0
    source_digest = _source_digest(source_path)
    cache_key = hashlib.sha256(
        f"{source_digest}|{cache_fps:.8f}|{_CACHE_SCHEMA}".encode("ascii")
    ).hexdigest()[:20]
    cache_root = os.path.abspath(cache_root or fbp_default_pillow_cache_root(source_path))
    output_directory = os.path.join(cache_root, f"{_safe_stem(source_path)}_{cache_key}")
    manifest_path = os.path.join(output_directory, "manifest.json")
    cached = _load_prepared_cache(
        manifest_path,
        source_path=source_path,
        source_digest=source_digest,
        fps=cache_fps,
    )
    if cached is not None:
        return cached

    os.makedirs(output_directory, exist_ok=True)
    files = []
    durations_ms = []
    with Image.open(source_path) as source:
        frame_total = max(1, int(getattr(source, "n_frames", 1) or 1)) if animated else 1
        fallback_ms = 1000.0 / fps
        icc_profile = source.info.get("icc_profile")
        for index in range(frame_total):
            source.seek(index)
            frame = source.convert("RGBA")
            duration_ms = float(source.info.get("duration", fallback_ms) or fallback_ms)
            durations_ms.append(max(1.0, duration_ms))
            filename = f"{_safe_stem(source_path)}_{index + 1:06d}.png"
            output_path = os.path.join(output_directory, filename)
            save_options = {"compress_level": 6}
            if icc_profile:
                save_options["icc_profile"] = icc_profile
            try:
                frame.save(output_path, format="PNG", **save_options)
            finally:
                frame.close()
            files.append(filename)

    durations = fbp_quantize_frame_durations(durations_ms, fps) if animated else (1,)
    payload = {
        "schema": _CACHE_SCHEMA,
        "source_path": source_path,
        "source_digest": source_digest,
        "source_format": source_format,
        "cache_key": cache_key,
        "fps": cache_fps,
        "animated": animated,
        "files": files,
        "durations": list(durations),
        "source_durations_ms": durations_ms,
    }
    temporary_manifest = manifest_path + ".tmp"
    with open(temporary_manifest, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary_manifest, manifest_path)
    return FBPPreparedMedia(
        output_directory=output_directory,
        files=tuple(files),
        durations=tuple(durations),
        source_path=source_path,
        source_format=source_format,
        cache_key=cache_key,
        animated=animated,
        reused_cache=False,
        source_durations_ms=tuple(durations_ms),
    )


def _load_rgba(path: str):
    from PIL import Image

    with Image.open(path) as source:
        source.seek(0)
        image = source.convert("RGBA")
        icc_profile = source.info.get("icc_profile") or b""
        if isinstance(icc_profile, str):
            icc_profile = icc_profile.encode("utf-8", "surrogatepass")
        try:
            orientation = int(source.getexif().get(274, 1) or 1)
        except (AttributeError, TypeError, ValueError):
            orientation = 1
        image.info["_fbp_visual_metadata"] = (
            hashlib.sha256(bytes(icc_profile)).digest() if icc_profile else b"",
            source.info.get("gamma"),
            source.info.get("srgb"),
            orientation,
        )
        return image


def _image_is_transparent(image, alpha_threshold: int) -> bool:
    from PIL import ImageStat

    alpha = image.getchannel("A")
    try:
        extrema = ImageStat.Stat(alpha).extrema
        return bool(extrema and int(extrema[0][1]) <= int(alpha_threshold))
    finally:
        alpha.close()


def _images_are_equal(left, right) -> bool:
    if left is None or right is None or left.size != right.size:
        return False
    if left.info.get("_fbp_visual_metadata") != right.info.get("_fbp_visual_metadata"):
        return False
    from PIL import ImageChops, ImageStat

    difference = ImageChops.difference(left, right)
    try:
        return all(int(maximum) == 0 for _minimum, maximum in ImageStat.Stat(difference).extrema)
    finally:
        difference.close()


def fbp_optimize_sequence_entries(
    entries,
    *,
    collapse_duplicates: bool = True,
    replace_transparent: bool = True,
    alpha_threshold: int = 0,
    path_resolver: Callable[[str], str] = os.path.abspath,
) -> tuple[list[dict], FBPSequenceOptimizationStats]:
    """Collapse consecutive visual duplicates and replace empty-alpha files logically."""
    alpha_threshold = max(0, min(255, int(alpha_threshold)))
    output = []
    unreadable = []
    analyzed_rows = 0
    collapsed_rows = 0
    transparent_rows = 0
    previous_image = None
    previous_empty = False

    try:
        for raw_entry in entries:
            entry = dict(raw_entry)
            entry["duration"] = max(1, int(entry.get("duration", 1) or 1))
            filepath = str(entry.get("filepath", "") or "")
            current_empty = bool(entry.get("is_empty", False)) or not filepath
            current_image = None
            decode_failed = False

            if not current_empty:
                resolved = path_resolver(filepath)
                try:
                    current_image = _load_rgba(resolved)
                    analyzed_rows += 1
                    if replace_transparent and _image_is_transparent(current_image, alpha_threshold):
                        current_empty = True
                        entry["is_empty"] = True
                        entry["filepath"] = ""
                        entry["name"] = "Alpha"
                        transparent_rows += 1
                        current_image.close()
                        current_image = None
                except (OSError, ValueError, SyntaxError):
                    unreadable.append(resolved)
                    decode_failed = True
                    if current_image is not None:
                        current_image.close()
                        current_image = None

            is_duplicate = False
            if collapse_duplicates and output and not decode_failed:
                if current_empty and previous_empty:
                    is_duplicate = True
                elif not current_empty and not previous_empty:
                    is_duplicate = _images_are_equal(previous_image, current_image)

            if is_duplicate:
                output[-1]["duration"] = max(1, int(output[-1].get("duration", 1) or 1)) + entry["duration"]
                collapsed_rows += 1
                if current_image is not None:
                    current_image.close()
                continue

            output.append(entry)
            if previous_image is not None:
                previous_image.close()
            previous_image = current_image
            previous_empty = current_empty and not decode_failed
    finally:
        if previous_image is not None:
            previous_image.close()

    stats = FBPSequenceOptimizationStats(
        source_rows=len(entries),
        output_rows=len(output),
        analyzed_rows=analyzed_rows,
        collapsed_rows=collapsed_rows,
        transparent_rows=transparent_rows,
        unreadable_paths=tuple(unreadable),
    )
    return output, stats
