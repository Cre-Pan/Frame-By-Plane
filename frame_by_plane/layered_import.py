"""Layered-document probing and PSD/PSB extraction for Frame By Plane.

The module deliberately has no Blender dependency. PSD and PSB files are
decoded through the packaged ``psd-tools`` backend. Procreate documents use a
defensive local archive/tile decoder. Both workflows rasterize non-destructive
full-canvas PNG sources for the shared Multiplane Setup pipeline.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import importlib.util
import json
import os
import re
from pathlib import PurePosixPath
import struct
from typing import Any
import zipfile


FBP_LAYERED_EXTENSIONS = frozenset({".psd", ".psb", ".procreate"})
FBP_MAX_ARCHIVE_ENTRIES = 100_000
FBP_MAX_ARCHIVE_UNCOMPRESSED_BYTES = 8 * 1024 * 1024 * 1024
FBP_MAX_ARCHIVE_RATIO = 2_000


@dataclass(frozen=True)
class FBP_LayeredBackendStatus:
    format: str
    available: bool
    state: str
    detail: str


@dataclass
class FBP_LayeredDocumentProbe:
    path: str
    format: str
    valid: bool = False
    width: int = 0
    height: int = 0
    bit_depth: int = 0
    channel_count: int = 0
    archive_entry_count: int = 0
    archive_uncompressed_bytes: int = 0
    cache_key: str = ""
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def fbp_layered_backend_status() -> tuple[FBP_LayeredBackendStatus, ...]:
    """Return capability status without importing heavyweight dependencies."""
    psd_tools = _module_available("psd_tools")
    pillow = _module_available("PIL")
    numpy = _module_available("numpy")
    psd_ready = psd_tools and pillow and numpy
    procreate_ready = pillow
    missing = [
        name
        for name, present in (("psd-tools", psd_tools), ("Pillow", pillow), ("NumPy", numpy))
        if not present
    ]
    psd_detail = (
        "Layer decoder available."
        if psd_ready
        else "Missing packaged dependency: " + ", ".join(missing) + "."
    )
    return (
        FBP_LayeredBackendStatus(
            format="PSD/PSB",
            available=psd_ready,
            state="READY" if psd_ready else "DEPENDENCY_REQUIRED",
            detail=psd_detail,
        ),
        FBP_LayeredBackendStatus(
            format="PROCREATE",
            available=procreate_ready,
            state="READY" if procreate_ready else "DEPENDENCY_REQUIRED",
            detail=(
                "Local archive and tile decoder available."
                if procreate_ready
                else "Missing packaged dependency: Pillow."
            ),
        ),
    )


def fbp_layered_cache_key(path: str) -> str:
    """Return a strong source-revision key without hashing the whole document."""
    absolute = os.path.abspath(os.fspath(path))
    try:
        real_path = os.path.realpath(absolute)
        stat = os.stat(real_path)
        payload = "\0".join((
            os.path.normcase(real_path),
            str(int(stat.st_size)),
            str(int(getattr(stat, "st_mtime_ns", 0))),
            str(int(getattr(stat, "st_ctime_ns", 0))),
            str(int(getattr(stat, "st_dev", 0))),
            str(int(getattr(stat, "st_ino", 0))),
        )).encode("utf-8", "surrogatepass")
    except OSError:
        payload = os.path.normcase(absolute).encode("utf-8", "surrogatepass")
    return hashlib.sha256(payload).hexdigest()[:24]


def _probe_psd(path: str) -> FBP_LayeredDocumentProbe:
    probe = FBP_LayeredDocumentProbe(
        path=path,
        format="PSD",
        cache_key=fbp_layered_cache_key(path),
    )
    try:
        with open(path, "rb") as handle:
            header = handle.read(26)
    except OSError as exc:
        probe.warnings.append(f"Could not read document: {exc}")
        return probe

    if len(header) != 26:
        probe.warnings.append("PSD header is incomplete.")
        return probe

    try:
        signature, version, reserved, channels, height, width, depth, color_mode = struct.unpack(
            ">4sH6sHIIHH", header
        )
    except struct.error:
        probe.warnings.append("PSD header could not be decoded.")
        return probe

    if signature != b"8BPS" or version not in {1, 2} or reserved != b"\0" * 6:
        probe.warnings.append("File does not contain a valid PSD/PSB header.")
        return probe
    if not (1 <= channels <= 56 and 1 <= width <= 300_000 and 1 <= height <= 300_000):
        probe.warnings.append("PSD dimensions or channel count are outside supported limits.")
        return probe
    if depth not in {1, 8, 16, 32}:
        probe.warnings.append(f"Unsupported PSD bit depth: {depth}.")
        return probe

    probe.valid = True
    probe.format = "PSB" if version == 2 else "PSD"
    probe.width = int(width)
    probe.height = int(height)
    probe.bit_depth = int(depth)
    probe.channel_count = int(channels)
    probe.metadata.update({
        "psd_version": int(version),
        "color_mode": int(color_mode),
    })
    return probe


def _archive_member_is_safe(name: str) -> bool:
    normalized = str(name or "").replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or normalized.startswith("/") or path.is_absolute():
        return False
    return all(part not in {"", ".", ".."} for part in path.parts)


def _png_size(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return 0, 0
    try:
        return struct.unpack(">II", data[16:24])
    except struct.error:
        return 0, 0


def _probe_procreate(path: str) -> FBP_LayeredDocumentProbe:
    probe = FBP_LayeredDocumentProbe(
        path=path,
        format="PROCREATE",
        cache_key=fbp_layered_cache_key(path),
    )
    if not zipfile.is_zipfile(path):
        probe.warnings.append("Procreate document is not a valid ZIP archive.")
        return probe

    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
            probe.archive_entry_count = len(infos)
            if len(infos) > FBP_MAX_ARCHIVE_ENTRIES:
                probe.warnings.append("Archive contains too many entries.")
                return probe

            total = 0
            names = set()
            for info in infos:
                if not _archive_member_is_safe(info.filename):
                    probe.warnings.append(f"Unsafe archive path: {info.filename!r}.")
                    return probe
                total += max(0, int(info.file_size))
                if total > FBP_MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                    probe.warnings.append("Archive expands beyond the safe size limit.")
                    return probe
                compressed = max(1, int(info.compress_size))
                if int(info.file_size) > 64 * 1024 * 1024 and int(info.file_size) / compressed > FBP_MAX_ARCHIVE_RATIO:
                    probe.warnings.append(f"Suspicious compression ratio: {info.filename!r}.")
                    return probe
                names.add(info.filename.replace("\\", "/"))

            probe.archive_uncompressed_bytes = total
            name_lookup = {name.casefold(): name for name in names}
            has_document_archive = "document.archive" in name_lookup
            thumbnail_name = next(
                (
                    name_lookup[candidate.casefold()]
                    for candidate in ("QuickLook/Thumbnail.png", "QuickLook/Preview.png")
                    if candidate.casefold() in name_lookup
                ),
                "",
            )
            if not has_document_archive:
                probe.warnings.append("Document.archive is missing.")
                return probe

            if thumbnail_name:
                try:
                    with archive.open(thumbnail_name, "r") as thumbnail:
                        width, height = _png_size(thumbnail.read(24))
                    probe.width = int(width)
                    probe.height = int(height)
                except (KeyError, OSError, RuntimeError, zipfile.BadZipFile):
                    probe.warnings.append("QuickLook thumbnail could not be read.")
            else:
                probe.warnings.append("QuickLook thumbnail is missing; canvas size is not available during probing.")

            probe.valid = True
            probe.metadata.update({
                "has_document_archive": has_document_archive,
                "quicklook_thumbnail": thumbnail_name,
            })
            return probe
    except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        probe.warnings.append(f"Could not inspect Procreate archive: {exc}")
        return probe


def fbp_probe_layered_document(path: str) -> FBP_LayeredDocumentProbe:
    """Validate a PSD/PSB/Procreate source without extracting any files."""
    absolute = os.path.abspath(os.fspath(path))
    extension = os.path.splitext(absolute)[1].lower()
    if extension in {".psd", ".psb"}:
        return _probe_psd(absolute)
    if extension == ".procreate":
        return _probe_procreate(absolute)
    return FBP_LayeredDocumentProbe(
        path=absolute,
        format="UNKNOWN",
        valid=False,
        cache_key=fbp_layered_cache_key(absolute),
        warnings=["Unsupported layered-document extension."],
    )

# -----------------------------------------------------------------------------
# PSD / PSB extraction backend

FBP_LAYERED_CACHE_SCHEMA = 4
_FBP_SAFE_LAYER_NAME_RE = re.compile(r"[^0-9A-Za-z._ -]+")
FBP_LAYER_BLEND_MODE_ALIASES = {
    "LINEAR_DODGE": "ADD",
    "VALUE": "LUMINOSITY",
}
FBP_TRANSFERABLE_BLEND_MODES = {
    "MULTIPLY", "SCREEN", "OVERLAY", "SOFT_LIGHT", "HARD_LIGHT",
    "DARKEN", "LIGHTEN", "COLOR_DODGE", "COLOR_BURN", "DIFFERENCE",
    "EXCLUSION", "ADD", "SUBTRACT", "DIVIDE", "HUE", "SATURATION",
    "COLOR", "LUMINOSITY", "LINEAR_LIGHT",
}


def fbp_layered_blend_mode_for_blender(mode: str) -> str:
    """Return the canonical Layer Blend enum while preserving source metadata elsewhere."""
    normalized = str(mode or "NORMAL").upper()
    return FBP_LAYER_BLEND_MODE_ALIASES.get(normalized, normalized)


def fbp_layered_blend_mode_supported(mode: str) -> bool:
    return fbp_layered_blend_mode_for_blender(mode) in FBP_TRANSFERABLE_BLEND_MODES


@dataclass
class FBP_LayeredLayerRecord:
    name: str
    collection_path: str
    relative_file: str
    kind: str
    visible: bool
    opacity: float
    blend_mode: str
    source_layer_path: str
    source_index: int
    flattened_group: bool = False
    is_clipping: bool = False
    mask_relative_file: str = ""
    blend_supported: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class FBP_LayeredExtractionResult:
    source_path: str
    output_directory: str
    cache_key: str
    width: int = 0
    height: int = 0
    records: list[FBP_LayeredLayerRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped_layers: int = 0
    merged_clipping_layers: int = 0
    flattened_groups: int = 0
    reused_cache: bool = False
    backend_version: str = ""
    source_format: str = "PSD"
    fallback_preview: bool = False
    decoded_layers: int = 0
    transferred_blend_modes: int = 0
    transferred_masks: int = 0
    transferred_clipping_layers: int = 0
    unsupported_blend_modes: int = 0


def _safe_layer_component(value: str, fallback: str = "Layer") -> str:
    """Return an ASCII-safe filename component for extracted PNG files."""
    value = str(value or "").replace("/", "_").replace("\\", "_")
    value = _FBP_SAFE_LAYER_NAME_RE.sub("_", value).strip(" ._-")
    return value[:96] or fallback


def _safe_collection_component(value: str, fallback: str = "Group") -> str:
    """Preserve Unicode group names while removing path/control separators."""
    cleaned = []
    for character in str(value or ""):
        codepoint = ord(character)
        if character in {"/", "\\"} or codepoint < 32 or codepoint == 127:
            cleaned.append("_")
        else:
            cleaned.append(character)
    return "".join(cleaned).strip(" ._-")[:128] or fallback


def _blend_mode_name(layer) -> str:
    value = getattr(layer, "blend_mode", "NORMAL")
    name = getattr(value, "name", None) or str(value)
    if "." in name:
        name = name.rsplit(".", 1)[-1]
    return str(name or "NORMAL").upper()


def _layer_kind(layer) -> str:
    try:
        return str(getattr(layer, "kind", "layer") or "layer").lower()
    except Exception:
        return "layer"


def _layer_own_visible(layer) -> bool:
    try:
        return bool(getattr(layer, "visible", True))
    except Exception:
        return True


def _effective_layer_opacity(layer) -> float:
    value = 1.0
    current = layer
    visited = set()
    while current is not None:
        pointer = id(current)
        if pointer in visited:
            break
        visited.add(pointer)
        try:
            value *= max(0.0, min(1.0, float(getattr(current, "opacity", 255)) / 255.0))
        except Exception:
            pass
        current = getattr(current, "parent", None)
        if current is not None and _layer_kind(current) == "psdimage":
            break
    return max(0.0, min(1.0, value))


def _group_needs_flattening(layer) -> bool:
    try:
        opacity = int(getattr(layer, "opacity", 255))
    except Exception:
        opacity = 255
    blend = _blend_mode_name(layer)
    return opacity != 255 or blend not in {"PASS_THROUGH", "NORMAL"}


@contextmanager
def _temporary_render_state(layer):
    """Render raw layer pixels while keeping editable opacity in metadata."""
    old_opacity = None
    old_blend = None
    blend_enum = None
    try:
        old_opacity = getattr(layer, "opacity", None)
        if old_opacity is not None:
            layer.opacity = 255
    except Exception:
        old_opacity = None
    try:
        old_blend = getattr(layer, "blend_mode", None)
        if old_blend is not None:
            try:
                from psd_tools.constants import BlendMode
                blend_enum = BlendMode.NORMAL
            except Exception:
                blend_enum = None
            if blend_enum is not None:
                layer.blend_mode = blend_enum
    except Exception:
        old_blend = None
    try:
        yield
    finally:
        if old_blend is not None:
            try:
                layer.blend_mode = old_blend
            except Exception:
                pass
        if old_opacity is not None:
            try:
                layer.opacity = old_opacity
            except Exception:
                pass


def _render_layer_to_canvas(layer, document):
    from PIL import Image

    canvas_size = (int(document.width), int(document.height))

    def render_filter(candidate):
        # The selected root must render even when it is imported as a hidden
        # Blender layer. Descendants and clipping layers keep their own PSD
        # visibility so a flattened group never reveals hidden artwork.
        if candidate is layer:
            return True
        try:
            return bool(candidate.is_visible())
        except (AttributeError, TypeError, ValueError):
            return _layer_own_visible(candidate)

    with _temporary_render_state(layer):
        try:
            image = layer.composite(
                viewport=document.viewbox,
                color=0.0,
                alpha=0.0,
                layer_filter=render_filter,
                apply_icc=True,
            )
        except (ImportError, NotImplementedError, ValueError, RuntimeError, OSError):
            image = None

        if image is None:
            try:
                raw = layer.topil()
            except (AttributeError, ImportError, NotImplementedError, ValueError, RuntimeError, OSError):
                raw = None
            if raw is None:
                return None
            raw = raw.convert("RGBA")
            canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
            try:
                left = int(getattr(layer, "left", 0))
                top = int(getattr(layer, "top", 0))
            except Exception:
                left = top = 0
            canvas.alpha_composite(raw, (left, top))
            image = canvas

    image = image.convert("RGBA")
    if image.size != canvas_size:
        canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
        try:
            left = int(getattr(layer, "left", 0))
            top = int(getattr(layer, "top", 0))
        except Exception:
            left = top = 0
        canvas.alpha_composite(image, (left, top))
        image = canvas
    return image


def _render_raw_layer_to_canvas(layer, document):
    """Return unmasked layer pixels on the full PSD canvas when available."""
    from PIL import Image
    try:
        raw = layer.topil()
    except (AttributeError, ImportError, NotImplementedError, ValueError, RuntimeError, OSError):
        raw = None
    if raw is None:
        return None
    raw = raw.convert("RGBA")
    canvas = Image.new("RGBA", (int(document.width), int(document.height)), (0, 0, 0, 0))
    try:
        left = int(getattr(layer, "left", 0))
        top = int(getattr(layer, "top", 0))
    except (AttributeError, TypeError, ValueError):
        left = top = 0
    try:
        canvas.alpha_composite(raw, (left, top))
    except ValueError:
        return None
    return canvas


def _psd_vector_point_xy(point, width: int, height: int) -> tuple[float, float]:
    """Convert one PSD path point from normalized (y, x) coordinates to pixels."""
    try:
        return float(point[1]) * width, float(point[0]) * height
    except (IndexError, TypeError, ValueError):
        return 0.0, 0.0


def _psd_cubic_points(p0, p1, p2, p3, *, width: int, height: int):
    """Flatten one cubic segment with bounded, resolution-aware sampling."""
    import math
    xy0 = _psd_vector_point_xy(p0, width, height)
    xy1 = _psd_vector_point_xy(p1, width, height)
    xy2 = _psd_vector_point_xy(p2, width, height)
    xy3 = _psd_vector_point_xy(p3, width, height)
    control_length = sum(math.dist(a, b) for a, b in ((xy0, xy1), (xy1, xy2), (xy2, xy3)))
    steps = max(4, min(96, int(control_length / 8.0) + 1))
    points = []
    for step in range(1, steps + 1):
        t = step / steps
        u = 1.0 - t
        points.append((
            u * u * u * xy0[0] + 3.0 * u * u * t * xy1[0] + 3.0 * u * t * t * xy2[0] + t * t * t * xy3[0],
            u * u * u * xy0[1] + 3.0 * u * u * t * xy1[1] + 3.0 * u * t * t * xy2[1] + t * t * t * xy3[1],
        ))
    return points


def _rasterize_psd_vector_mask(layer, document, warnings=None):
    """Rasterize a PSD vector mask with bounded pure-Python Bézier flattening."""
    from PIL import Image, ImageChops, ImageDraw
    vector_mask = getattr(layer, "vector_mask", None)
    if vector_mask is None:
        return None
    try:
        if bool(getattr(vector_mask, "disabled", False)):
            return None
    except (AttributeError, TypeError, ValueError):
        pass
    width, height = int(document.width), int(document.height)
    paths = list(getattr(vector_mask, "paths", ()) or ())
    knot_count = sum(len(path) for path in paths)
    if knot_count > 100_000:
        if warnings is not None:
            warnings.append("PSD vector mask exceeds the safe 100,000-knot rasterization limit.")
        return None
    grouped_paths = []
    for subpath in paths:
        try:
            operation = int(getattr(subpath, "operation", 1))
        except (TypeError, ValueError):
            operation = 1
        if operation == -1 and grouped_paths:
            grouped_paths[-1][1].append(subpath)
        else:
            grouped_paths.append([operation, [subpath]])
    initial_fill = bool(getattr(vector_mask, "initial_fill_rule", 0)) and not grouped_paths
    mask = Image.new("L", (width, height), 255 if initial_fill else 0)
    first = True
    for operation, subpaths in grouped_paths:
        plane = Image.new("L", (width, height), 0)
        for subpath in subpaths:
            knots = list(subpath or ())
            if len(knots) < 2:
                continue
            try:
                closed = bool(subpath.is_closed())
            except (AttributeError, TypeError, ValueError):
                closed = True
            if not closed:
                continue
            polygon = [_psd_vector_point_xy(getattr(knots[0], "anchor", (0.0, 0.0)), width, height)]
            segment_count = len(knots)
            for index in range(segment_count):
                current = knots[index]
                following = knots[(index + 1) % segment_count]
                polygon.extend(_psd_cubic_points(
                    getattr(current, "anchor", (0.0, 0.0)),
                    getattr(current, "leaving", getattr(current, "anchor", (0.0, 0.0))),
                    getattr(following, "preceding", getattr(following, "anchor", (0.0, 0.0))),
                    getattr(following, "anchor", (0.0, 0.0)),
                    width=width,
                    height=height,
                ))
            component = Image.new("L", (width, height), 0)
            ImageDraw.Draw(component).polygon(polygon, fill=255)
            # PSD paths use the even-odd fill rule inside one path component.
            plane = ImageChops.difference(plane, component)
        if operation == 0:  # Exclude / XOR.
            mask = ImageChops.difference(mask, plane)
        elif operation == 2:  # Subtract.
            if first:
                mask = ImageChops.invert(mask)
            mask = ImageChops.subtract(mask, plane)
        elif operation == 3:  # Intersect.
            if first:
                mask = ImageChops.invert(mask)
            mask = ImageChops.multiply(mask, plane)
        else:  # Union / combine.
            mask = ImageChops.lighter(mask, plane)
        first = False
    try:
        if bool(getattr(vector_mask, "inverted", False)):
            mask = ImageChops.invert(mask)
    except (AttributeError, TypeError, ValueError):
        pass
    return mask


def _render_psd_mask_to_canvas(layer, document, warnings=None):
    """Return combined PSD pixel/vector masks as one full-canvas L image."""
    from PIL import Image, ImageChops
    canvas_size = (int(document.width), int(document.height))
    pixel_canvas = None
    real_mask_includes_vector = False
    mask = getattr(layer, "mask", None)
    if mask is not None:
        try:
            mask_disabled = bool(getattr(mask, "disabled", False))
        except (AttributeError, TypeError, ValueError):
            mask_disabled = False
        if not mask_disabled:
            try:
                real_mask_includes_vector = bool(mask.has_real())
            except (AttributeError, TypeError, ValueError):
                real_mask_includes_vector = False
            try:
                image = mask.topil(real=True, layer_sized=True)
            except (AttributeError, ImportError, NotImplementedError, ValueError, RuntimeError, OSError):
                image = None
            if image is not None:
                image = image.convert("L")
                if image.size == canvas_size:
                    pixel_canvas = image
                else:
                    pixel_canvas = Image.new("L", canvas_size, 255)
                    try:
                        left = int(getattr(layer, "left", 0))
                        top = int(getattr(layer, "top", 0))
                        pixel_canvas.paste(image, (left, top))
                    except (AttributeError, TypeError, ValueError):
                        pixel_canvas = None
    vector_canvas = None
    if not real_mask_includes_vector:
        try:
            vector_canvas = _rasterize_psd_vector_mask(layer, document, warnings=warnings)
        except (AttributeError, ImportError, RuntimeError, TypeError, ValueError, OSError) as exc:
            if warnings is not None:
                warnings.append(f"PSD vector mask rasterization failed: {exc}")
    if pixel_canvas is not None and vector_canvas is not None:
        return ImageChops.multiply(pixel_canvas, vector_canvas)
    return pixel_canvas or vector_canvas


def _layer_record_from_json(payload: dict[str, Any]) -> FBP_LayeredLayerRecord:
    return FBP_LayeredLayerRecord(
        name=str(payload.get("name", "Layer")),
        collection_path=str(payload.get("collection_path", "")),
        relative_file=str(payload.get("relative_file", "")),
        kind=str(payload.get("kind", "layer")),
        visible=bool(payload.get("visible", True)),
        opacity=max(0.0, min(1.0, float(payload.get("opacity", 1.0)))),
        blend_mode=str(payload.get("blend_mode", "NORMAL")),
        source_layer_path=str(payload.get("source_layer_path", "")),
        source_index=int(payload.get("source_index", 0)),
        flattened_group=bool(payload.get("flattened_group", False)),
        is_clipping=bool(payload.get("is_clipping", False)),
        mask_relative_file=str(payload.get("mask_relative_file", "")),
        blend_supported=bool(payload.get("blend_supported", False)),
        warnings=[str(item) for item in payload.get("warnings", ())],
    )


def _layer_record_to_json(record: FBP_LayeredLayerRecord) -> dict[str, Any]:
    return {
        "name": record.name,
        "collection_path": record.collection_path,
        "relative_file": record.relative_file,
        "kind": record.kind,
        "visible": record.visible,
        "opacity": record.opacity,
        "blend_mode": record.blend_mode,
        "source_layer_path": record.source_layer_path,
        "source_index": record.source_index,
        "flattened_group": record.flattened_group,
        "is_clipping": record.is_clipping,
        "mask_relative_file": record.mask_relative_file,
        "blend_supported": record.blend_supported,
        "warnings": list(record.warnings),
    }


def _load_layered_cache(manifest_path: str, source_path: str, source_key: str, option_key: str):
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError):
        return None
    if int(payload.get("schema", 0)) != FBP_LAYERED_CACHE_SCHEMA:
        return None
    if str(payload.get("source_path", "")) != os.path.abspath(source_path):
        return None
    if str(payload.get("source_key", "")) != source_key:
        return None
    if str(payload.get("option_key", "")) != option_key:
        return None
    output_directory = os.path.dirname(manifest_path)
    records = [_layer_record_from_json(item) for item in payload.get("records", ())]
    if not records:
        return None
    for record in records:
        if not record.relative_file or not os.path.isfile(os.path.join(output_directory, record.relative_file)):
            return None
        if record.mask_relative_file and not os.path.isfile(os.path.join(output_directory, record.mask_relative_file)):
            return None
    return FBP_LayeredExtractionResult(
        source_path=os.path.abspath(source_path),
        output_directory=output_directory,
        cache_key=source_key,
        width=int(payload.get("width", 0)),
        height=int(payload.get("height", 0)),
        records=records,
        warnings=[str(item) for item in payload.get("warnings", ())],
        skipped_layers=int(payload.get("skipped_layers", 0)),
        merged_clipping_layers=int(payload.get("merged_clipping_layers", 0)),
        flattened_groups=int(payload.get("flattened_groups", 0)),
        reused_cache=True,
        backend_version=str(payload.get("backend_version", "")),
        source_format=str(payload.get("source_format", "PSD")),
        fallback_preview=bool(payload.get("fallback_preview", False)),
        decoded_layers=int(payload.get("decoded_layers", len(records))),
        transferred_blend_modes=int(payload.get("transferred_blend_modes", 0)),
        transferred_masks=int(payload.get("transferred_masks", 0)),
        transferred_clipping_layers=int(payload.get("transferred_clipping_layers", 0)),
        unsupported_blend_modes=int(payload.get("unsupported_blend_modes", 0)),
    )


def fbp_default_psd_cache_root(source_path: str) -> str:
    """Return the persistent, non-destructive cache folder beside a PSD."""
    source_path = os.path.abspath(os.fspath(source_path))
    return os.path.join(os.path.dirname(source_path), ".fbp_psd_cache")


def fbp_extract_psd_layers(
    source_path: str,
    *,
    cache_root: str | None = None,
    preserve_groups: bool = True,
    include_hidden: bool = False,
    flatten_complex_groups: bool = True,
    reuse_cache: bool = True,
) -> FBP_LayeredExtractionResult:
    """Rasterize a PSD/PSB into persistent full-canvas PNG layer sources.

    The original document is never changed. Groups are represented as collection
    paths. Complex groups with non-pass-through blending or group opacity can be
    flattened to one plane to avoid silently misrepresenting their hierarchy.
    """
    source_path = os.path.abspath(os.fspath(source_path))
    probe = fbp_probe_layered_document(source_path)
    if not probe.valid or probe.format not in {"PSD", "PSB"}:
        detail = "; ".join(probe.warnings) or "Invalid PSD/PSB document."
        raise ValueError(detail)

    try:
        from psd_tools import PSDImage, __version__ as backend_version
    except ImportError as exc:
        raise RuntimeError("PSD support is unavailable because the packaged psd-tools backend could not be loaded.") from exc

    option_payload = (
        f"backend={backend_version};schema={FBP_LAYERED_CACHE_SCHEMA};"
        f"groups={int(preserve_groups)};hidden={int(include_hidden)};"
        f"flatten={int(flatten_complex_groups)}"
    )
    option_key = hashlib.sha256(option_payload.encode("ascii")).hexdigest()[:10]
    source_key = probe.cache_key
    cache_root = os.path.abspath(cache_root or fbp_default_psd_cache_root(source_path))
    stem = _safe_layer_component(os.path.splitext(os.path.basename(source_path))[0], "PSD")
    output_directory = os.path.join(cache_root, f"{stem}_{source_key}_{option_key}")
    manifest_path = os.path.join(output_directory, "fbp_psd_manifest.json")

    if reuse_cache:
        cached = _load_layered_cache(manifest_path, source_path, source_key, option_key)
        if cached is not None:
            return cached

    os.makedirs(output_directory, exist_ok=True)
    document = PSDImage.open(source_path)
    result = FBP_LayeredExtractionResult(
        source_path=source_path,
        output_directory=output_directory,
        cache_key=source_key,
        width=int(document.width),
        height=int(document.height),
        backend_version=str(backend_version),
        source_format=probe.format,
    )
    counter = [0]

    def export_layer(
        layer, group_parts: list[str], *, flattened_group: bool = False,
        display_name: str | None = None, source_parts: list[str] | None = None,
        is_clipping: bool = False,
    ):
        counter[0] += 1
        index = counter[0]
        original_name = str(getattr(layer, "name", "") or f"Layer {index}")
        raw_name = str(display_name or original_name)
        safe_name = _safe_layer_component(raw_name, f"Layer_{index}")
        relative_file = f"{index:04d}_{safe_name}.png"
        target_path = os.path.join(output_directory, relative_file)
        layer_warnings = []
        blend_mode = _blend_mode_name(layer)
        blend_supported = fbp_layered_blend_mode_supported(blend_mode)
        if blend_mode not in {"NORMAL", "PASS_THROUGH"}:
            if blend_supported:
                result.transferred_blend_modes += 1
            else:
                result.unsupported_blend_modes += 1
                layer_warnings.append(
                    f"Photoshop blend mode {blend_mode} has no reliable pairwise Blender mapping and remains stored as metadata."
                )
        mask_relative_file = ""
        mask_baked = bool(flattened_group)
        try:
            image = None if flattened_group else _render_raw_layer_to_canvas(layer, document)
            if image is None:
                image = _render_layer_to_canvas(layer, document)
                mask_baked = True
        except Exception as exc:
            image = None
            layer_warnings.append(f"Layer rasterization failed: {exc}")
        clipping_transfer = bool(is_clipping and not mask_baked)
        if mask_baked and blend_supported and blend_mode not in {"NORMAL", "PASS_THROUGH"}:
            blend_supported = False
            result.transferred_blend_modes = max(0, result.transferred_blend_modes - 1)
            layer_warnings.append(
                f"Photoshop blend mode {blend_mode} was baked into the raster fallback because raw layer pixels were unavailable."
            )
        if is_clipping:
            if clipping_transfer:
                result.transferred_clipping_layers += 1
            else:
                result.merged_clipping_layers += 1
                layer_warnings.append("Clipping was baked into the raster fallback because raw layer pixels were unavailable.")
        if image is None or image.getbbox() is None:
            result.skipped_layers += 1
            result.warnings.append(f"Skipped empty or unsupported layer: {' / '.join(group_parts + [raw_name])}")
            return
        try:
            image.save(target_path, format="PNG", compress_level=3)
        except OSError as exc:
            raise OSError(f"Could not write extracted PSD layer {target_path!r}: {exc}") from exc

        if not mask_baked:
            try:
                mask_image = _render_psd_mask_to_canvas(layer, document, warnings=layer_warnings)
            except Exception as exc:
                mask_image = None
                layer_warnings.append(f"Layer mask extraction failed: {exc}")
            if mask_image is not None and mask_image.getextrema() != (255, 255):
                mask_relative_file = f"{index:04d}_{safe_name}_mask.png"
                mask_path = os.path.join(output_directory, mask_relative_file)
                try:
                    mask_image.save(mask_path, format="PNG", compress_level=3)
                    result.transferred_masks += 1
                except OSError as exc:
                    mask_relative_file = ""
                    layer_warnings.append(f"Could not write imported layer mask: {exc}")

        source_layer_path = " / ".join(source_parts or (group_parts + [original_name]))
        collection_path = " / ".join(group_parts) if preserve_groups else ""
        record = FBP_LayeredLayerRecord(
            name=raw_name,
            collection_path=collection_path,
            relative_file=relative_file,
            kind=_layer_kind(layer),
            visible=_layer_own_visible(layer) and all(_layer_own_visible(parent) for parent in _iter_layer_parents(layer)),
            opacity=_effective_layer_opacity(layer),
            blend_mode=blend_mode,
            source_layer_path=source_layer_path,
            source_index=index,
            flattened_group=flattened_group,
            is_clipping=clipping_transfer,
            mask_relative_file=mask_relative_file,
            blend_supported=blend_supported,
            warnings=layer_warnings,
        )
        result.records.append(record)
        result.decoded_layers += 1
        result.warnings.extend(layer_warnings)
        if flattened_group:
            result.flattened_groups += 1

    def walk(container, group_parts: list[str], inherited_visible: bool = True):
        for layer in container:
            own_visible = _layer_own_visible(layer)
            effective_visible = inherited_visible and own_visible
            if not include_hidden and not effective_visible:
                continue
            try:
                is_group = bool(layer.is_group())
            except Exception:
                is_group = False

            if is_group:
                group_name = str(getattr(layer, "name", "") or "Group")
                if flatten_complex_groups and _group_needs_flattening(layer):
                    flattened_parts = (
                        group_parts + [_safe_collection_component(group_name, "Group")]
                        if preserve_groups else group_parts
                    )
                    export_layer(
                        layer, flattened_parts, flattened_group=True,
                        display_name="Group Composite", source_parts=group_parts + [group_name],
                    )
                else:
                    next_parts = group_parts + [_safe_collection_component(group_name, "Group")] if preserve_groups else group_parts
                    walk(layer, next_parts, effective_visible)
                continue

            try:
                is_clipping = bool(getattr(layer, "clipping", False))
            except Exception:
                is_clipping = False
            export_layer(layer, group_parts, is_clipping=is_clipping)

    def _write_manifest():
        payload = {
            "schema": FBP_LAYERED_CACHE_SCHEMA,
            "source_path": source_path,
            "source_key": source_key,
            "option_key": option_key,
            "width": result.width,
            "height": result.height,
            "backend_version": result.backend_version,
            "source_format": result.source_format,
            "fallback_preview": result.fallback_preview,
            "decoded_layers": result.decoded_layers,
            "records": [_layer_record_to_json(record) for record in result.records],
            "warnings": list(dict.fromkeys(result.warnings)),
            "skipped_layers": result.skipped_layers,
            "merged_clipping_layers": result.merged_clipping_layers,
            "flattened_groups": result.flattened_groups,
            "transferred_blend_modes": result.transferred_blend_modes,
            "transferred_masks": result.transferred_masks,
            "transferred_clipping_layers": result.transferred_clipping_layers,
            "unsupported_blend_modes": result.unsupported_blend_modes,
        }
        temp_path = manifest_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        os.replace(temp_path, manifest_path)

    walk(document, [])
    result.warnings = list(dict.fromkeys(result.warnings))
    if not result.records:
        raise RuntimeError("The PSD/PSB did not contain any rasterizable layers.")
    _write_manifest()
    return result


def _iter_layer_parents(layer):
    current = getattr(layer, "parent", None)
    visited = set()
    while current is not None and _layer_kind(current) != "psdimage":
        pointer = id(current)
        if pointer in visited:
            break
        visited.add(pointer)
        yield current
        current = getattr(current, "parent", None)


def fbp_inspect_psd_layers(source_path: str) -> dict[str, Any]:
    """Return a lightweight hierarchy summary without rasterizing layer pixels."""
    source_path = os.path.abspath(os.fspath(source_path))
    probe = fbp_probe_layered_document(source_path)
    if not probe.valid or probe.format not in {"PSD", "PSB"}:
        detail = "; ".join(probe.warnings) or "Invalid PSD/PSB document."
        raise ValueError(detail)
    try:
        from psd_tools import PSDImage, __version__ as backend_version
    except ImportError as exc:
        raise RuntimeError("The packaged psd-tools backend could not be loaded.") from exc
    document = PSDImage.open(source_path)
    summary = {
        "width": int(document.width),
        "height": int(document.height),
        "layers": 0,
        "groups": 0,
        "visible_layers": 0,
        "hidden_layers": 0,
        "clipping_layers": 0,
        "mask_layers": 0,
        "complex_groups": 0,
        "non_normal_blend_layers": 0,
        "kinds": {},
        "backend_version": str(backend_version),
    }

    def walk(container, inherited_visible=True):
        for layer in container:
            own_visible = _layer_own_visible(layer)
            visible = inherited_visible and own_visible
            try:
                is_group = bool(layer.is_group())
            except Exception:
                is_group = False
            if is_group:
                summary["groups"] += 1
                if _group_needs_flattening(layer):
                    summary["complex_groups"] += 1
                walk(layer, visible)
                continue
            summary["layers"] += 1
            if visible:
                summary["visible_layers"] += 1
            else:
                summary["hidden_layers"] += 1
            kind = _layer_kind(layer)
            summary["kinds"][kind] = int(summary["kinds"].get(kind, 0)) + 1
            if bool(getattr(layer, "clipping", False)):
                summary["clipping_layers"] += 1
            try:
                pixel_mask = getattr(layer, "mask", None)
                vector_mask = getattr(layer, "vector_mask", None)
                has_pixel_mask = pixel_mask is not None and not bool(getattr(pixel_mask, "disabled", False))
                has_vector_mask = vector_mask is not None and not bool(getattr(vector_mask, "disabled", False))
                if has_pixel_mask or has_vector_mask:
                    summary["mask_layers"] += 1
            except (AttributeError, TypeError, ValueError):
                pass
            if _blend_mode_name(layer) not in {"NORMAL", "PASS_THROUGH"}:
                summary["non_normal_blend_layers"] += 1

    walk(document)
    return summary

# -----------------------------------------------------------------------------
# Procreate extraction backend


def fbp_default_procreate_cache_root(source_path: str) -> str:
    """Return the persistent, non-destructive cache folder beside Procreate."""
    source_path = os.path.abspath(os.fspath(source_path))
    return os.path.join(os.path.dirname(source_path), ".fbp_procreate_cache")


def fbp_inspect_procreate_layers(source_path: str) -> dict[str, Any]:
    """Return a lightweight Procreate hierarchy/tile summary."""
    source_path = os.path.abspath(os.fspath(source_path))
    probe = fbp_probe_layered_document(source_path)
    if not probe.valid or probe.format != "PROCREATE":
        detail = "; ".join(probe.warnings) or "Invalid Procreate document."
        raise ValueError(detail)
    try:
        from .procreate_import import FBP_ProcreateDocument, FBP_PROCREATE_DECODER_VERSION
    except ImportError:
        # Allow direct module tests outside the package.
        from procreate_import import FBP_ProcreateDocument, FBP_PROCREATE_DECODER_VERSION
    with FBP_ProcreateDocument(source_path) as document:
        inspection = document.inspect()
    return {
        "width": int(inspection.width or probe.width),
        "height": int(inspection.height or probe.height),
        "dpi": int(inspection.dpi),
        "tile_size": int(inspection.tile_size),
        "layers": int(inspection.layers),
        "groups": int(inspection.groups),
        "visible_layers": int(inspection.visible_layers),
        "hidden_layers": int(inspection.hidden_layers),
        "non_normal_blend_layers": int(inspection.non_normal_blend_layers),
        "clipping_layers": int(getattr(inspection, "clipping_layers", 0)),
        "mask_layers": int(getattr(inspection, "mask_layers", 0)),
        "decodable_layer_candidates": int(inspection.decodable_layer_candidates),
        "archive_entries": int(inspection.archive_entries),
        "has_preview": bool(inspection.has_preview),
        "video_enabled": bool(inspection.video_enabled),
        "warnings": list(inspection.warnings),
        "backend_version": FBP_PROCREATE_DECODER_VERSION,
    }


def fbp_extract_procreate_layers(
    source_path: str,
    *,
    cache_root: str | None = None,
    preserve_groups: bool = True,
    include_hidden: bool = False,
    fallback_to_preview: bool = True,
    reuse_cache: bool = True,
) -> FBP_LayeredExtractionResult:
    """Extract common Procreate layer tiles into full-canvas PNG sources.

    The source archive remains read-only. Unsupported archive revisions or tile
    encodings can fall back to the QuickLook preview as one flattened plane.
    """
    source_path = os.path.abspath(os.fspath(source_path))
    probe = fbp_probe_layered_document(source_path)
    if not probe.valid or probe.format != "PROCREATE":
        detail = "; ".join(probe.warnings) or "Invalid Procreate document."
        raise ValueError(detail)
    try:
        from .procreate_import import FBP_ProcreateDocument, FBP_PROCREATE_DECODER_VERSION
    except ImportError:
        from procreate_import import FBP_ProcreateDocument, FBP_PROCREATE_DECODER_VERSION

    option_payload = (
        f"backend={FBP_PROCREATE_DECODER_VERSION};schema={FBP_LAYERED_CACHE_SCHEMA};"
        f"groups={int(preserve_groups)};hidden={int(include_hidden)};"
        f"preview={int(fallback_to_preview)}"
    )
    option_key = hashlib.sha256(option_payload.encode("ascii")).hexdigest()[:10]
    source_key = probe.cache_key
    cache_root = os.path.abspath(cache_root or fbp_default_procreate_cache_root(source_path))
    stem = _safe_layer_component(os.path.splitext(os.path.basename(source_path))[0], "Procreate")
    output_directory = os.path.join(cache_root, f"{stem}_{source_key}_{option_key}")
    manifest_path = os.path.join(output_directory, "fbp_procreate_manifest.json")

    if reuse_cache:
        cached = _load_layered_cache(manifest_path, source_path, source_key, option_key)
        if cached is not None:
            return cached

    os.makedirs(output_directory, exist_ok=True)
    result = FBP_LayeredExtractionResult(
        source_path=source_path,
        output_directory=output_directory,
        cache_key=source_key,
        backend_version=FBP_PROCREATE_DECODER_VERSION,
        source_format="PROCREATE",
    )
    counter = 0

    with FBP_ProcreateDocument(source_path) as document:
        result.width = int(document.width or probe.width)
        result.height = int(document.height or probe.height)
        result.warnings.extend(document.warnings)

        for layer, parents in document.iter_layers(include_groups=False):
            effective_visible = bool(layer.visible and all(parent.visible for parent in parents))
            if not include_hidden and not effective_visible:
                continue
            counter += 1
            layer_name = str(layer.name or f"Layer {counter}")
            group_parts = [
                _safe_collection_component(parent.name, "Group")
                for parent in parents
            ] if preserve_groups else []
            source_parts = [str(parent.name or "Group") for parent in parents] + [layer_name]
            image = document.load_layer_image(layer)
            layer_warnings: list[str] = []
            if image is None or image.getbbox() is None:
                result.skipped_layers += 1
                result.warnings.append(
                    f"Could not decode Procreate layer tiles: {' / '.join(source_parts)}"
                )
                continue
            safe_name = _safe_layer_component(layer_name, f"Layer_{counter}")
            relative_file = f"{counter:04d}_{safe_name}.png"
            target_path = os.path.join(output_directory, relative_file)
            try:
                image.save(target_path, format="PNG", compress_level=3)
            except OSError as exc:
                raise OSError(f"Could not write extracted Procreate layer {target_path!r}: {exc}") from exc
            mask_relative_file = ""
            if bool(getattr(layer, "mask_uuid", "")) and bool(getattr(layer, "mask_visible", True)):
                try:
                    mask_image = document.load_layer_mask(layer)
                except Exception as exc:
                    mask_image = None
                    layer_warnings.append(f"Procreate Layer Mask extraction failed: {exc}")
                if mask_image is not None and mask_image.getextrema() != (255, 255):
                    mask_relative_file = f"{counter:04d}_{safe_name}_mask.png"
                    mask_path = os.path.join(output_directory, mask_relative_file)
                    try:
                        mask_image.save(mask_path, format="PNG", compress_level=3)
                        result.transferred_masks += 1
                    except OSError as exc:
                        mask_relative_file = ""
                        layer_warnings.append(f"Could not write Procreate Layer Mask: {exc}")
                elif mask_image is None:
                    layer_warnings.append("Attached Procreate Layer Mask could not be decoded and remains diagnostic metadata.")
            effective_opacity = max(0.0, min(1.0, float(layer.opacity)))
            for parent in parents:
                effective_opacity *= max(0.0, min(1.0, float(parent.opacity)))
            blend_supported = fbp_layered_blend_mode_supported(layer.blend_mode)
            if layer.blend_mode != "NORMAL":
                if blend_supported:
                    result.transferred_blend_modes += 1
                else:
                    result.unsupported_blend_modes += 1
                    layer_warnings.append(
                        f"Procreate blend mode {layer.blend_mode} has no reliable pairwise Blender mapping and remains stored as metadata."
                    )
            for parent in parents:
                if parent.blend_mode != "NORMAL":
                    warning = (
                        f"Parent group blend mode {parent.blend_mode} is stored as metadata and may differ in Blender."
                    )
                    if warning not in layer_warnings:
                        layer_warnings.append(warning)
            result.records.append(FBP_LayeredLayerRecord(
                name=layer_name,
                collection_path=" / ".join(group_parts),
                relative_file=relative_file,
                kind="procreate_pixel",
                visible=effective_visible,
                opacity=max(0.0, min(1.0, effective_opacity)),
                blend_mode=str(layer.blend_mode or "NORMAL"),
                source_layer_path=" / ".join(source_parts),
                source_index=int(layer.source_index or counter),
                is_clipping=bool(getattr(layer, "is_clipping", False)),
                mask_relative_file=mask_relative_file,
                blend_supported=blend_supported,
                warnings=layer_warnings,
            ))
            result.decoded_layers += 1
            if bool(getattr(layer, "is_clipping", False)):
                result.transferred_clipping_layers += 1
            result.warnings.extend(layer_warnings)

        if not result.records and fallback_to_preview:
            preview = document.load_preview_image()
            if preview is not None and preview.getbbox() is not None:
                relative_file = "0001_Composite_Preview.png"
                target_path = os.path.join(output_directory, relative_file)
                try:
                    preview.save(target_path, format="PNG", compress_level=3)
                except OSError as exc:
                    raise OSError(f"Could not write Procreate preview {target_path!r}: {exc}") from exc
                result.records.append(FBP_LayeredLayerRecord(
                    name="Composite Preview",
                    collection_path="",
                    relative_file=relative_file,
                    kind="procreate_preview",
                    visible=True,
                    opacity=1.0,
                    blend_mode="NORMAL",
                    source_layer_path="QuickLook / Composite Preview",
                    source_index=0,
                    warnings=[
                        "The individual Procreate layer tiles could not be decoded; the QuickLook preview was imported as one flattened plane."
                    ],
                ))
                result.fallback_preview = True
                result.warnings.extend(result.records[-1].warnings)

    result.warnings = list(dict.fromkeys(result.warnings))
    if not result.records:
        raise RuntimeError(
            "No Procreate layers could be decoded and no usable QuickLook preview was found."
        )

    payload = {
        "schema": FBP_LAYERED_CACHE_SCHEMA,
        "source_path": source_path,
        "source_key": source_key,
        "option_key": option_key,
        "width": result.width,
        "height": result.height,
        "backend_version": result.backend_version,
        "source_format": result.source_format,
        "fallback_preview": result.fallback_preview,
        "decoded_layers": result.decoded_layers,
        "records": [_layer_record_to_json(record) for record in result.records],
        "warnings": list(result.warnings),
        "skipped_layers": result.skipped_layers,
        "merged_clipping_layers": 0,
        "flattened_groups": 0,
        "transferred_blend_modes": result.transferred_blend_modes,
        "transferred_masks": result.transferred_masks,
        "transferred_clipping_layers": result.transferred_clipping_layers,
        "unsupported_blend_modes": result.unsupported_blend_modes,
    }
    temp_path = manifest_path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    os.replace(temp_path, manifest_path)
    return result
