"""Safe discovery layer for future PSD and Procreate document import.

This module deliberately has no Blender dependency. It validates source files,
reports optional backend availability, and supplies stable cache keys so the
actual Blender operators can remain thin when layered import is enabled.

Full layer decoding is intentionally not performed here:
- PSD/PSB decoding will use a packaged, version-pinned psd-tools backend.
- Procreate decoding requires an independent NSKeyedArchive/tile decoder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import importlib.util
import os
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
            available=False,
            state="PROBE_ONLY",
            detail="Archive validation is ready; layer/tile decoding is not enabled yet.",
        ),
    )


def fbp_layered_cache_key(path: str) -> str:
    """Return a stable source revision key without reading the whole document."""
    absolute = os.path.abspath(os.fspath(path))
    try:
        stat = os.stat(absolute)
        payload = f"{absolute}\0{stat.st_size}\0{stat.st_mtime_ns}".encode("utf-8", "surrogatepass")
    except OSError:
        payload = absolute.encode("utf-8", "surrogatepass")
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
            has_document_archive = "Document.archive" in names
            thumbnail_name = next(
                (name for name in ("QuickLook/Thumbnail.png", "QuickLook/Preview.png") if name in names),
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
