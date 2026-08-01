#!/usr/bin/env python3
"""Build deterministic Frame By Plane release archives without Blender."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sys
import tomllib
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

PLATFORMS = {
    "windows-x64": ("windows_x64", ("-win_amd64.whl",)),
    "windows-arm64": ("windows_arm64", ("-win_arm64.whl",)),
    "macos-x64": ("macos_x64", ("macosx_", "_x86_64.whl")),
    "macos-arm64": ("macos_arm64", ("macosx_", "_arm64.whl")),
    "linux-x64": ("linux_x64", ("manylinux_", "_x86_64.whl")),
}
COMMON_WHEEL = "-py3-none-any.whl"
GENERATED_BEGIN = "# BEGIN GENERATED CONTENT."
GENERATED_END = "# END GENERATED CONTENT."


class BuildError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise BuildError(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=Path("frame_by_plane"))
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    parser.add_argument("--tag", default="")
    return parser.parse_args()


def read_manifest(source: Path) -> tuple[dict, str]:
    path = source / "blender_manifest.toml"
    text = path.read_text(encoding="utf-8")
    if GENERATED_BEGIN in text or "[build.generated]" in text:
        fail("Source manifest contains generated build metadata")
    data = tomllib.loads(text)
    version = str(data.get("version", ""))
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        fail(f"Invalid version: {version!r}")
    if set(data.get("platforms", ())) != set(PLATFORMS):
        fail("Manifest platform set is incomplete")
    return data, text.rstrip() + "\n"


def wheel_path(value: object) -> str:
    value = str(value).removeprefix("./")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or not value.startswith("wheels/"):
        fail(f"Unsafe wheel path: {value!r}")
    return value


def selected_wheels(wheels: list[str], platform: str) -> tuple[str, ...]:
    markers = PLATFORMS[platform][1]
    selected = tuple(
        item
        for item in wheels
        if item.endswith(COMMON_WHEEL) or all(marker in PurePosixPath(item).name for marker in markers)
    )
    native = [item for item in selected if not item.endswith(COMMON_WHEEL)]
    if len(native) != 2:
        fail(f"{platform} must resolve exactly two native wheels: {native!r}")
    return selected


def excluded(relative: PurePosixPath, installable: bool, version: str) -> bool:
    if any(part.startswith(".") for part in relative.parts):
        return True
    if "__pycache__" in relative.parts or "_fbp_update_backups" in relative.parts:
        return True
    if relative.suffix.lower() in {".pyc", ".zip", ".bak", ".log", ".diff"}:
        return True
    if relative.name.startswith(("FRAME_BY_PLANE_", "STATIC_AUDIT_", "PACKAGE_VALIDATION_")):
        return True
    if relative.name == "SHA256SUMS.txt":
        return True
    if relative.name.startswith("RELEASE_NOTES_") and relative.name != f"RELEASE_NOTES_{version}.md":
        return True
    if installable and (relative.parts[:1] == ("tests",) or relative.name.startswith("RELEASE_NOTES_")):
        return True
    return False


def source_files(source: Path, installable: bool, version: str) -> list[tuple[PurePosixPath, Path]]:
    files = []
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        relative = PurePosixPath(path.relative_to(source).as_posix())
        if not excluded(relative, installable, version):
            files.append((relative, path))
    return sorted(files, key=lambda item: item[0].as_posix())


def timestamp() -> tuple[int, int, int, int, int, int]:
    try:
        epoch = max(315532800, int(os.environ.get("SOURCE_DATE_EPOCH", "315532800")))
    except ValueError as exc:
        raise BuildError("SOURCE_DATE_EPOCH must be an integer") from exc
    value = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return value.year, value.month, value.day, value.hour, value.minute, value.second - value.second % 2


def write_entry(archive: zipfile.ZipFile, name: str, data: bytes, stamp: tuple[int, ...]) -> None:
    info = zipfile.ZipInfo(name, stamp)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def generated_manifest(text: str, platform: str, wheels: tuple[str, ...]) -> bytes:
    wheel_list = ", ".join(f'"./{item}"' for item in wheels)
    generated = (
        f"\n{GENERATED_BEGIN}\n"
        "# This must not be included in source manifests.\n"
        "[build.generated]\n"
        f'platforms = ["{platform}"]\n'
        f"wheels = [{wheel_list}]\n"
        f"{GENERATED_END}\n"
    )
    return (text.rstrip() + generated).encode("utf-8")


def write_zip(
    destination: Path,
    files: list[tuple[PurePosixPath, Path]],
    stamp: tuple[int, ...],
    manifest: bytes | None = None,
) -> None:
    temporary = destination.with_suffix(".zip.tmp")
    temporary.unlink(missing_ok=True)
    with zipfile.ZipFile(temporary, "w", allowZip64=True) as archive:
        for relative, path in files:
            data = manifest if manifest is not None and relative.as_posix() == "blender_manifest.toml" else path.read_bytes()
            write_entry(archive, relative.as_posix(), data, stamp)
    temporary.replace(destination)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def validate(path: Path, version: str, expected_wheels: set[str] | None) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad:
            fail(f"CRC failure in {path.name}: {bad}")
        names = archive.namelist()
        if len(names) != len(set(names)):
            fail(f"Duplicate paths in {path.name}")
        manifest = tomllib.loads(archive.read("blender_manifest.toml").decode("utf-8"))
        if str(manifest.get("version")) != version:
            fail(f"Version mismatch in {path.name}")
        if expected_wheels is not None:
            actual = {name for name in names if name.startswith("wheels/") and name.endswith(".whl")}
            if actual != expected_wheels:
                fail(f"Wheel isolation mismatch in {path.name}")
            if any(name.startswith("tests/") for name in names):
                fail(f"Tests leaked into {path.name}")
        return {
            name: archive.read(name)
            for name in names
            if name != "blender_manifest.toml" and not name.startswith("wheels/")
        }


def build(source: Path, output: Path, tag: str) -> list[Path]:
    source = source.resolve()
    output = output.resolve()
    data, manifest_text = read_manifest(source)
    version = str(data["version"])
    extension_id = str(data["id"])
    if tag and tag != f"v{version}":
        fail(f"Tag/version mismatch: {tag!r} != v{version}")
    if not (source / f"RELEASE_NOTES_{version}.md").is_file():
        fail(f"RELEASE_NOTES_{version}.md is missing")
    wheels = [wheel_path(item) for item in data.get("wheels", ())]
    for item in wheels:
        if not (source / item).is_file():
            fail(f"Declared wheel is missing: {item}")

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    stamp = timestamp()
    installable_files = source_files(source, True, version)
    source_archive_files = source_files(source, False, version)

    outputs: list[Path] = []
    common_payload: dict[str, bytes] | None = None
    for platform in data["platforms"]:
        selected = selected_wheels(wheels, platform)
        platform_files = [
            item for item in installable_files
            if not item[0].as_posix().startswith("wheels/") or item[0].as_posix() in selected
        ]
        destination = output / f"{extension_id}-{version}-{PLATFORMS[platform][0]}.zip"
        write_zip(destination, platform_files, stamp, generated_manifest(manifest_text, platform, selected))
        payload = validate(destination, version, set(selected))
        if common_payload is None:
            common_payload = payload
        elif payload != common_payload:
            fail(f"Common payload differs in {destination.name}")
        outputs.append(destination)

    source_archive = output / f"{extension_id}-{version}-source.zip"
    write_zip(source_archive, source_archive_files, stamp)
    validate(source_archive, version, None)
    outputs.append(source_archive)

    checksums = output / "SHA256SUMS.txt"
    checksums.write_text(
        "".join(f"{digest(path)}  {path.name}\n" for path in sorted(outputs, key=lambda item: item.name)),
        encoding="utf-8",
        newline="\n",
    )
    outputs.append(checksums)
    return outputs


def main() -> int:
    args = parse_args()
    try:
        outputs = build(args.source_dir, args.output_dir, args.tag)
    except (BuildError, OSError, KeyError, tomllib.TOMLDecodeError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print("Release artifacts created:")
    for path in outputs:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
