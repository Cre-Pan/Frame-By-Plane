"""Procreate archive metadata and tile decoder for Frame By Plane.

The .procreate format is proprietary and undocumented. This implementation is
an independently integrated, defensive adaptation of the MIT-licensed
ProcreateViewer reader by NothingData. It reads Document.archive metadata and
common Procreate 4/5 tile encodings without modifying the source archive.

No Blender dependency is used here so the decoder can be tested independently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import io
import os
import plistlib
import struct
from typing import Any, Iterable
import uuid as uuid_module
import zipfile
import zlib


FBP_PROCREATE_DECODER_VERSION = "1.3"

# Hard safety limits for malformed or hostile archives. These values are high
# enough for normal illustration documents while preventing unbounded plist
# recursion and multi-gigabyte single-member allocations.
FBP_PROCREATE_MAX_ARCHIVE_OBJECTS = 250_000
FBP_PROCREATE_MAX_HIERARCHY_DEPTH = 256
FBP_PROCREATE_MAX_DOCUMENT_ARCHIVE_BYTES = 128 * 1024 * 1024
FBP_PROCREATE_MAX_PREVIEW_BYTES = 256 * 1024 * 1024
FBP_PROCREATE_MAX_CANVAS_PIXELS = 300_000_000


FBP_PROCREATE_BLEND_MODES = {
    0: "NORMAL",
    1: "MULTIPLY",
    2: "SCREEN",
    3: "OVERLAY",
    4: "DARKEN",
    5: "LIGHTEN",
    6: "COLOR_DODGE",
    7: "COLOR_BURN",
    8: "SOFT_LIGHT",
    9: "HARD_LIGHT",
    10: "DIFFERENCE",
    11: "EXCLUSION",
    12: "HUE",
    13: "SATURATION",
    14: "COLOR",
    15: "LUMINOSITY",
    16: "ADD",
    17: "LINEAR_BURN",
    18: "VIVID_LIGHT",
    19: "LINEAR_LIGHT",
    20: "PIN_LIGHT",
    21: "HARD_MIX",
    22: "SUBTRACT",
    23: "DIVIDE",
}


@dataclass
class FBP_ProcreateLayer:
    name: str
    uuid: str
    opacity: float = 1.0
    visible: bool = True
    blend_mode: str = "NORMAL"
    kind: str = "pixel"
    is_clipping: bool = False
    mask_uuid: str = ""
    mask_visible: bool = True
    mask_opacity: float = 1.0
    source_index: int = 0
    children: list["FBP_ProcreateLayer"] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_group(self) -> bool:
        return self.kind == "group" or bool(self.children)


@dataclass
class FBP_ProcreateInspection:
    width: int = 0
    height: int = 0
    dpi: int = 132
    tile_size: int = 256
    layers: int = 0
    groups: int = 0
    visible_layers: int = 0
    hidden_layers: int = 0
    non_normal_blend_layers: int = 0
    clipping_layers: int = 0
    mask_layers: int = 0
    decodable_layer_candidates: int = 0
    archive_entries: int = 0
    has_preview: bool = False
    video_enabled: bool = False
    warnings: list[str] = field(default_factory=list)


class FBP_ProcreateDocument:
    """Read metadata and raster layer tiles from a .procreate ZIP archive."""

    _ROOT_LAYER_KEYS = (
        "SilicaDocumentArchiveLayers",
        "layers",
        "layerList",
        "children",
    )
    _CHILD_LAYER_KEYS = (
        "children",
        "layers",
        "sublayers",
        "NS.objects",
        "SilicaGroupArchiveChildren",
        "SilicaLayerArchiveChildren",
    )
    _NAME_KEYS = ("name", "SilicaLayerArchiveName", "title")
    _UUID_KEYS = ("UUID", "uuid", "SilicaLayerArchiveUUID", "identifier")
    _OPACITY_KEYS = ("contentsOpacity", "opacity", "SilicaLayerArchiveOpacity")
    _HIDDEN_KEYS = ("hidden", "SilicaLayerArchiveHidden", "isHidden")
    _BLEND_KEYS = ("extendedBlend", "blend", "blendMode", "SilicaLayerArchiveBlend")
    _MASK_KEYS = ("mask", "layerMask", "SilicaLayerArchiveMask")
    _CLIPPING_KEYS = (
        "clippingMask", "isClippingMask", "clipped", "isClipped",
        "SilicaLayerArchiveClippingMask", "SilicaLayerArchiveIsClippingMask",
    )

    def __init__(self, filepath: str):
        self.filepath = os.path.abspath(os.fspath(filepath))
        self.width = 0
        self.height = 0
        self.dpi = 132
        self.tile_size = 256
        self.video_enabled = False
        self.layers: list[FBP_ProcreateLayer] = []
        self.warnings: list[str] = []
        self._zip: zipfile.ZipFile | None = None
        self._archive: dict[str, Any] = {}
        self._objects: list[Any] = []
        self._names: tuple[str, ...] = ()
        self._name_lookup: dict[str, str] = {}
        self._members_by_prefix: dict[str, tuple[str, ...]] = {}
        self._quicklook_name = ""
        self._source_counter = 0
        self._warning_set: set[str] = set()
        self._preview_name = ""
        try:
            self._load()
        except Exception:
            self.close()
            raise

    def _load(self) -> None:
        if not os.path.isfile(self.filepath):
            raise FileNotFoundError(self.filepath)
        if not zipfile.is_zipfile(self.filepath):
            raise ValueError("Procreate document is not a valid ZIP archive")
        self._zip = zipfile.ZipFile(self.filepath, "r")
        self._names = tuple(self._zip.namelist())
        self._name_lookup = {name.casefold(): name for name in self._names}
        prefix_members: dict[str, list[str]] = {}
        for name in self._names:
            normalized = name.replace("\\", "/").lstrip("/")
            if "/" not in normalized:
                continue
            prefix = normalized.split("/", 1)[0].casefold()
            prefix_members.setdefault(prefix, []).append(name)
        self._members_by_prefix = {
            prefix: tuple(members)
            for prefix, members in prefix_members.items()
        }
        self._quicklook_name = self._find_member(
            "QuickLook/Thumbnail.png", "QuickLook/thumbnail.png", "Thumbnail.png"
        )
        self._preview_name = self._find_member(
            "QuickLook/Preview.png", "QuickLook/preview.png", "composite.png"
        )
        archive_name = self._find_member("Document.archive", "document.archive")
        if not archive_name:
            raise ValueError("Document.archive is missing")
        try:
            archive_info = self._zip.getinfo(archive_name)
            if int(archive_info.file_size) > FBP_PROCREATE_MAX_DOCUMENT_ARCHIVE_BYTES:
                raise ValueError("Document.archive exceeds the safe metadata size limit")
            payload = self._zip.read(archive_name)
            decoded = plistlib.loads(payload)
        except (KeyError, OSError, ValueError, TypeError, plistlib.InvalidFileException) as exc:
            raise ValueError(f"Document.archive could not be decoded: {exc}") from exc
        if not isinstance(decoded, dict):
            raise ValueError("Document.archive does not contain a keyed archive")
        self._archive = decoded
        objects = decoded.get("$objects", [])
        self._objects = list(objects) if isinstance(objects, (list, tuple)) else []
        if len(self._objects) > FBP_PROCREATE_MAX_ARCHIVE_OBJECTS:
            raise ValueError(
                f"Document.archive contains too many objects: {len(self._objects):,}"
            )
        self._parse_metadata()
        self._parse_layers()

    def _warn_once(self, message: str) -> None:
        text = str(message or "").strip()
        if text and text not in self._warning_set:
            self._warning_set.add(text)
            self.warnings.append(text)

    def _find_member(self, *candidates: str) -> str:
        for candidate in candidates:
            found = self._name_lookup.get(candidate.casefold())
            if found:
                return found
        return ""

    def _uid_index(self, value: Any) -> int | None:
        if isinstance(value, plistlib.UID):
            try:
                return int(value.data)
            except (TypeError, ValueError, AttributeError):
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None
        # plistlib preserves NSKeyedArchiver references as plistlib.UID.
        # Plain integers are document values (dimensions, blend modes, etc.)
        # and must never be interpreted as object references.
        return None

    def _resolve(self, value: Any) -> Any:
        index = self._uid_index(value)
        if index is None:
            return value
        if 0 <= index < len(self._objects):
            return self._objects[index]
        return None

    def _root_object(self) -> dict[str, Any] | None:
        top = self._archive.get("$top", {})
        if isinstance(top, dict):
            for key in ("root", "document", "NSKeyedArchiveRootObjectKey"):
                root = self._resolve(top.get(key))
                if isinstance(root, dict):
                    return root
        if len(self._objects) > 1 and isinstance(self._objects[1], dict):
            return self._objects[1]
        return None

    def _resolve_scalar(self, value: Any) -> Any:
        resolved = self._resolve(value)
        if isinstance(resolved, dict):
            if "NS.string" in resolved:
                return self._resolve_scalar(resolved.get("NS.string"))
            if "NS.data" in resolved:
                return self._resolve_scalar(resolved.get("NS.data"))
            if "NS.objects" in resolved:
                return self._resolve_array(resolved)
        return resolved

    def _resolve_array(
        self,
        value: Any,
        *,
        depth: int = 0,
        visited: set[int] | None = None,
    ) -> list[Any]:
        if depth > FBP_PROCREATE_MAX_HIERARCHY_DEPTH:
            self._warn_once("Layer archive nesting exceeded the safe depth limit")
            return []
        resolved = self._resolve(value)
        visited = visited if visited is not None else set()
        if isinstance(resolved, (dict, list, tuple)):
            pointer = id(resolved)
            if pointer in visited:
                self._warn_once("A cyclic layer archive reference was ignored")
                return []
            visited.add(pointer)
        if isinstance(resolved, dict):
            for key in ("NS.objects", "objects", "children", "layers"):
                nested = resolved.get(key)
                if nested is None:
                    continue
                if nested is value or nested is resolved:
                    self._warn_once("A cyclic layer archive reference was ignored")
                    return []
                return self._resolve_array(
                    nested, depth=depth + 1, visited=visited
                )
            return []
        if isinstance(resolved, (list, tuple)):
            return [self._resolve(item) for item in resolved]
        return []

    def _first_value(self, mapping: dict[str, Any], keys: Iterable[str], default=None):
        for key in keys:
            if key in mapping:
                value = self._resolve_scalar(mapping.get(key))
                if value is not None and value != "$null":
                    return value
        return default

    @staticmethod
    def _number(value: Any, default: float = 0.0) -> float:
        if isinstance(value, bool):
            return float(int(value))
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, (bytes, bytearray)):
            data = bytes(value)
            for fmt in (">d", "<d", ">f", "<f", ">i", "<i"):
                size = struct.calcsize(fmt)
                if len(data) >= size:
                    try:
                        return float(struct.unpack(fmt, data[:size])[0])
                    except struct.error:
                        continue
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def _integer(self, mapping: dict[str, Any], keys: Iterable[str], default=0) -> int:
        return int(round(self._number(self._first_value(mapping, keys, default), default)))

    def _class_name(self, mapping: dict[str, Any]) -> str:
        class_obj = self._resolve(mapping.get("$class"))
        if isinstance(class_obj, dict):
            name = class_obj.get("$classname") or class_obj.get("NS.name")
            if isinstance(name, str):
                return name
        return ""

    def _parse_metadata(self) -> None:
        root = self._root_object()
        if not root:
            self.warnings.append("Root document object was not found")
            return
        self.width = self._integer(root, (
            "SilicaDocumentArchiveDimensionWidth", "canvasWidth", "width",
        ))
        self.height = self._integer(root, (
            "SilicaDocumentArchiveDimensionHeight", "canvasHeight", "height",
        ))
        self.dpi = max(1, self._integer(root, ("SilicaDocumentArchiveDPI", "dpi"), 132))
        self.tile_size = max(16, self._integer(root, (
            "SilicaDocumentArchiveTileSize", "tileSize",
        ), 256))
        video_value = self._first_value(root, ("SilicaDocumentVideoSegmentInfoKey", "videoEnabled"), False)
        self.video_enabled = video_value not in (False, None, 0, "$null")
        if self.width <= 0 or self.height <= 0:
            image = self.load_preview_image()
            if image is not None:
                self.width, self.height = image.size
                self.warnings.append("Canvas size was inferred from the QuickLook image")

    def _child_refs(self, mapping: dict[str, Any]) -> list[Any]:
        for key in self._CHILD_LAYER_KEYS:
            if key in mapping:
                values = self._resolve_array(mapping.get(key))
                if values:
                    return values
        return []

    def _layer_uuid(self, mapping: dict[str, Any]) -> str:
        value = self._first_value(mapping, self._UUID_KEYS, "")
        if isinstance(value, bytes):
            try:
                if len(value) == 16:
                    return str(uuid_module.UUID(bytes=value))
                return value.decode("utf-8", "replace")
            except (ValueError, UnicodeError):
                return value.hex()
        return str(value or "").strip()

    def _layer_name(self, mapping: dict[str, Any], fallback: str) -> str:
        value = self._first_value(mapping, self._NAME_KEYS, fallback)
        return str(value or fallback)

    def _layer_opacity(self, mapping: dict[str, Any]) -> float:
        value = self._number(self._first_value(mapping, self._OPACITY_KEYS, 1.0), 1.0)
        if value > 1.0:
            value /= 255.0
        return max(0.0, min(1.0, value))

    def _layer_visible(self, mapping: dict[str, Any]) -> bool:
        hidden = self._first_value(mapping, self._HIDDEN_KEYS, False)
        return not bool(hidden)

    def _layer_blend(self, mapping: dict[str, Any]) -> str:
        value = self._first_value(mapping, self._BLEND_KEYS, 0)
        try:
            number = int(value)
        except (TypeError, ValueError):
            text = str(value or "NORMAL").strip().upper().replace(" ", "_")
            return text or "NORMAL"
        return FBP_PROCREATE_BLEND_MODES.get(number, f"UNKNOWN_{number}")

    def _layer_is_clipping(self, mapping: dict[str, Any]) -> bool:
        value = self._first_value(mapping, self._CLIPPING_KEYS, False)
        if isinstance(value, str):
            return value.strip().casefold() in {"1", "true", "yes", "on"}
        return bool(value)

    def _is_group_object(self, mapping: dict[str, Any], children: list[Any]) -> bool:
        class_name = self._class_name(mapping).casefold()
        if "group" in class_name:
            return True
        if children:
            return True
        return any(key in mapping for key in self._CHILD_LAYER_KEYS if key != "NS.objects")

    def _parse_layer_object(
        self,
        mapping: dict[str, Any],
        visited: set[int],
        *,
        depth: int = 0,
    ) -> FBP_ProcreateLayer | None:
        if depth > FBP_PROCREATE_MAX_HIERARCHY_DEPTH:
            self._warn_once("Layer hierarchy exceeded the safe depth limit")
            return None
        pointer = id(mapping)
        if pointer in visited:
            self._warn_once("A cyclic layer hierarchy reference was ignored")
            return None
        visited.add(pointer)
        source_index = self._source_counter
        self._source_counter += 1
        children_raw = self._child_refs(mapping)
        is_group = self._is_group_object(mapping, children_raw)
        mask_mapping = None
        if not is_group:
            for mask_key in self._MASK_KEYS:
                if mask_key not in mapping:
                    continue
                resolved_mask = self._resolve(mapping.get(mask_key))
                if isinstance(resolved_mask, dict):
                    mask_mapping = resolved_mask
                    # Attached masks are not independent hierarchy layers. Mark
                    # the archive object as consumed so compatibility scanning
                    # cannot import it a second time as ordinary artwork.
                    visited.add(id(resolved_mask))
                    break
        node = FBP_ProcreateLayer(
            name=self._layer_name(mapping, f"Layer {source_index + 1}"),
            uuid=self._layer_uuid(mapping),
            opacity=self._layer_opacity(mapping),
            visible=self._layer_visible(mapping),
            blend_mode=self._layer_blend(mapping),
            kind="group" if is_group else "pixel",
            is_clipping=False if is_group else self._layer_is_clipping(mapping),
            mask_uuid=self._layer_uuid(mask_mapping) if mask_mapping else "",
            mask_visible=self._layer_visible(mask_mapping) if mask_mapping else True,
            mask_opacity=self._layer_opacity(mask_mapping) if mask_mapping else 1.0,
            source_index=source_index,
        )
        for child in children_raw:
            if not isinstance(child, dict):
                continue
            parsed = self._parse_layer_object(
                child, visited, depth=depth + 1
            )
            if parsed is not None:
                node.children.append(parsed)
        return node

    def _parse_layers(self) -> None:
        root = self._root_object()
        if not root:
            return
        root_values: list[Any] = []
        for key in self._ROOT_LAYER_KEYS:
            if key in root:
                root_values = self._resolve_array(root.get(key))
                if root_values:
                    break
        visited: set[int] = set()
        self._source_counter = 0
        for value in root_values:
            if not isinstance(value, dict):
                continue
            node = self._parse_layer_object(value, visited)
            if node is not None:
                self.layers.append(node)
        if self.layers:
            return
        # Conservative fallback for archive revisions where the root layer array
        # is wrapped differently. Only class-marked layer objects are included.
        for value in self._objects:
            if not isinstance(value, dict):
                continue
            class_name = self._class_name(value)
            if "SilicaLayer" not in class_name and "SilicaGroup" not in class_name:
                continue
            node = self._parse_layer_object(value, visited)
            if node is not None:
                self.layers.append(node)
        if self.layers:
            self.warnings.append("Layer hierarchy used the compatibility archive scan")

    def iter_layers(self, *, include_groups: bool = False):
        # Iterative traversal avoids Python recursion failures on deeply nested
        # (or malicious) documents while preserving archive order.
        stack = [
            (node, ())
            for node in reversed(self.layers)
        ]
        while stack:
            node, parents = stack.pop()
            if include_groups or not node.is_group:
                yield node, parents
            if node.children:
                child_parents = parents + (node,)
                stack.extend(
                    (child, child_parents)
                    for child in reversed(node.children)
                )

    def _member_for_prefix(self, prefix: str) -> tuple[str, ...]:
        return self._members_by_prefix.get(str(prefix or "").casefold().rstrip("/"), ())

    def layer_has_tiles(self, layer: FBP_ProcreateLayer) -> bool:
        if not layer.uuid:
            return False
        return any(
            name.lower().endswith((".chunk", ".lz4"))
            for name in self._member_for_prefix(layer.uuid)
        )

    @staticmethod
    def _decode_lz4_block(
        payload: bytes,
        *,
        expected_size: int,
        dictionary: bytes = b"",
    ) -> bytes:
        """Decode a raw LZ4 block, including optional external dictionary."""
        source = memoryview(payload)
        cursor = 0
        history = bytearray(dictionary[-65536:])
        output_start = len(history)
        source_length = len(source)
        output_limit = output_start + max(0, int(expected_size))

        def extended_length(value: int) -> int:
            nonlocal cursor
            if value != 15:
                return value
            total = value
            while True:
                if cursor >= source_length:
                    raise ValueError("Truncated LZ4 length")
                amount = int(source[cursor])
                cursor += 1
                total += amount
                if amount != 255:
                    return total

        while cursor < source_length:
            token = int(source[cursor])
            cursor += 1
            literal_length = extended_length(token >> 4)
            if cursor + literal_length > source_length:
                raise ValueError("Truncated LZ4 literals")
            if len(history) + literal_length > output_limit:
                raise ValueError("LZ4 output exceeds expected tile size")
            history.extend(source[cursor:cursor + literal_length])
            cursor += literal_length
            if cursor >= source_length:
                break
            if cursor + 2 > source_length:
                raise ValueError("Truncated LZ4 match offset")
            offset = int(source[cursor]) | (int(source[cursor + 1]) << 8)
            cursor += 2
            if offset <= 0 or offset > len(history):
                raise ValueError("Invalid LZ4 match offset")
            match_length = extended_length(token & 0x0F) + 4
            if len(history) + match_length > output_limit:
                raise ValueError("LZ4 match exceeds expected tile size")
            source_position = len(history) - offset
            remaining = match_length
            while remaining:
                available = len(history) - source_position
                if available <= 0:
                    raise ValueError("Invalid overlapping LZ4 match")
                amount = min(remaining, available)
                history.extend(history[source_position:source_position + amount])
                source_position += amount
                remaining -= amount
        decoded = bytes(history[output_start:])
        if expected_size and len(decoded) != expected_size:
            raise ValueError(f"Unexpected LZ4 output size: {len(decoded)} != {expected_size}")
        return decoded

    @classmethod
    def _decode_bv41(cls, payload: bytes, expected_size: int) -> bytes:
        cursor = 0
        parts: list[bytes] = []
        previous = b""
        total_size = 0
        while cursor < len(payload):
            magic = payload[cursor:cursor + 4]
            if magic == b"bv4$":
                cursor += 4
                break
            if magic != b"bv41" or cursor + 12 > len(payload):
                raise ValueError("Invalid bv41 stream")
            cursor += 4
            uncompressed_size, compressed_size = struct.unpack_from("<II", payload, cursor)
            cursor += 8
            if compressed_size < 0 or cursor + compressed_size > len(payload):
                raise ValueError("Truncated bv41 block")
            block = payload[cursor:cursor + compressed_size]
            cursor += compressed_size
            decoded = cls._decode_lz4_block(
                block,
                expected_size=int(uncompressed_size),
                dictionary=previous,
            )
            parts.append(decoded)
            previous = decoded
            total_size += len(decoded)
            if total_size > expected_size:
                raise ValueError("bv41 output exceeds expected tile size")
        result = b"".join(parts)
        if len(result) != expected_size:
            raise ValueError(f"Unexpected bv41 output size: {len(result)} != {expected_size}")
        return result

    @classmethod
    def decode_tile_bytes(cls, payload: bytes, expected_size: int) -> bytes | None:
        expected_size = int(expected_size)
        if expected_size <= 0 or expected_size > 512 * 1024 * 1024:
            return None
        if len(payload) == expected_size:
            return payload
        if payload[:4] == b"bv41":
            try:
                return cls._decode_bv41(payload, expected_size)
            except (ValueError, struct.error):
                pass
        candidates = [payload]
        if len(payload) >= 4 and struct.unpack_from("<I", payload, 0)[0] == expected_size:
            candidates.insert(0, payload[4:])
        for candidate in candidates:
            try:
                return cls._decode_lz4_block(candidate, expected_size=expected_size)
            except ValueError:
                continue
        try:
            decoded = zlib.decompress(payload)
            if len(decoded) == expected_size:
                return decoded
        except (ValueError, zlib.error):
            pass
        return None

    @staticmethod
    def _tile_coordinates(member_name: str) -> tuple[int, int] | None:
        basename = member_name.rsplit("/", 1)[-1]
        stem = basename.rsplit(".", 1)[0]
        for separator in ("~", "_"):
            if separator not in stem:
                continue
            parts = stem.split(separator)
            if len(parts) != 2:
                continue
            try:
                return int(parts[0]), int(parts[1])
            except ValueError:
                continue
        return None

    def _load_tiled_image(self, layer_uuid: str, *, grayscale: bool = False):
        from PIL import Image

        if self._zip is None or not layer_uuid or self.width <= 0 or self.height <= 0:
            return None
        if int(self.width) * int(self.height) > FBP_PROCREATE_MAX_CANVAS_PIXELS:
            self._warn_once(
                "Canvas exceeds the safe in-memory Procreate layer limit"
            )
            return None
        members = [
            name for name in self._member_for_prefix(layer_uuid)
            if name.lower().endswith((".chunk", ".lz4"))
        ]
        if not members:
            return None
        tile_size = max(16, int(self.tile_size or 256))
        columns = max(1, (self.width + tile_size - 1) // tile_size)
        rows = max(1, (self.height + tile_size - 1) // tile_size)
        mode = "L" if grayscale else "RGBA"
        fill = 255 if grayscale else (0, 0, 0, 0)
        canvas = Image.new(mode, (columns * tile_size, rows * tile_size), fill)
        rgba_size = tile_size * tile_size * 4
        gray_size = tile_size * tile_size
        loaded = 0
        for member in members:
            coordinates = self._tile_coordinates(member)
            if coordinates is None:
                continue
            column, row = coordinates
            if column < 0 or row < 0 or column >= columns or row >= rows:
                continue
            try:
                info = self._zip.getinfo(member)
                largest_expected = rgba_size
                member_limit = max(largest_expected * 8, largest_expected + 1024 * 1024)
                if int(info.file_size) > member_limit:
                    continue
                payload = self._zip.read(member)
            except (KeyError, OSError, RuntimeError, zipfile.BadZipFile):
                continue
            tile = None
            if grayscale:
                gray_pixels = self.decode_tile_bytes(payload, gray_size)
                if gray_pixels is not None:
                    try:
                        tile = Image.frombytes("L", (tile_size, tile_size), gray_pixels)
                    except (ValueError, TypeError):
                        tile = None
                if tile is None:
                    rgba_pixels = self.decode_tile_bytes(payload, rgba_size)
                    if rgba_pixels is not None:
                        try:
                            rgba_tile = Image.frombytes(
                                "RGBA", (tile_size, tile_size), rgba_pixels, "raw", "BGRA"
                            )
                            luminance = rgba_tile.convert("L")
                            alpha = rgba_tile.getchannel("A")
                            tile = (
                                alpha
                                if luminance.getextrema() == (0, 0) and alpha.getextrema() != (255, 255)
                                else luminance
                            )
                        except (ValueError, TypeError):
                            tile = None
            else:
                pixels = self.decode_tile_bytes(payload, rgba_size)
                if pixels is not None:
                    try:
                        tile = Image.frombytes(
                            "RGBA", (tile_size, tile_size), pixels, "raw", "BGRA"
                        )
                    except (ValueError, TypeError):
                        tile = None
            if tile is None:
                continue
            canvas.paste(tile, (column * tile_size, row * tile_size))
            loaded += 1
        if not loaded:
            return None
        if canvas.size != (self.width, self.height):
            canvas = canvas.crop((0, 0, self.width, self.height))
        return canvas

    def load_layer_image(self, layer: FBP_ProcreateLayer):
        return self._load_tiled_image(layer.uuid, grayscale=False)

    def load_layer_mask(self, layer: FBP_ProcreateLayer):
        """Decode an attached Procreate Layer Mask as one full-canvas L image."""
        if not layer.mask_uuid or not layer.mask_visible:
            return None
        image = self._load_tiled_image(layer.mask_uuid, grayscale=True)
        if image is None:
            return None
        opacity = max(0.0, min(1.0, float(layer.mask_opacity)))
        if opacity < 0.999999:
            from PIL import Image
            image = Image.blend(Image.new("L", image.size, 255), image, opacity)
        return image

    def load_preview_image(self):
        from PIL import Image

        if self._zip is None:
            return None
        for name in (self._preview_name, self._quicklook_name):
            if not name:
                continue
            try:
                info = self._zip.getinfo(name)
                if int(info.file_size) > FBP_PROCREATE_MAX_PREVIEW_BYTES:
                    self._warn_once("QuickLook preview exceeds the safe size limit")
                    continue
                payload = self._zip.read(name)
                image = Image.open(io.BytesIO(payload))
                image.load()
                return image.convert("RGBA")
            except (KeyError, OSError, RuntimeError, ValueError, zipfile.BadZipFile):
                continue
        return None

    def inspect(self) -> FBP_ProcreateInspection:
        summary = FBP_ProcreateInspection(
            width=int(self.width),
            height=int(self.height),
            dpi=int(self.dpi),
            tile_size=int(self.tile_size),
            archive_entries=len(self._names),
            has_preview=bool(self._preview_name or self._quicklook_name),
            video_enabled=bool(self.video_enabled),
            warnings=list(self.warnings),
        )
        for node, _parents in self.iter_layers(include_groups=True):
            if node.is_group:
                summary.groups += 1
                continue
            summary.layers += 1
            if node.visible:
                summary.visible_layers += 1
            else:
                summary.hidden_layers += 1
            if node.blend_mode != "NORMAL":
                summary.non_normal_blend_layers += 1
            if node.is_clipping:
                summary.clipping_layers += 1
            if node.mask_uuid and node.mask_visible:
                summary.mask_layers += 1
            if self.layer_has_tiles(node):
                summary.decodable_layer_candidates += 1
        return summary

    def close(self) -> None:
        archive = self._zip
        self._zip = None
        if archive is not None:
            archive.close()

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self.close()
        return False
