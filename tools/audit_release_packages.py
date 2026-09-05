#!/usr/bin/env python3
"""Fail closed on dirty, incomplete or source-mismatched release packages."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
TAGS = {
    "windows_x64": "win_amd64",
    "windows_arm64": "win_arm64",
    "macos_x64": "macosx_10_13_x86_64",
    "macos_arm64": "macosx_11_0_arm64",
    "linux_x64": "manylinux",
}


def runtime_files(source: Path) -> set[str]:
    """Explicit runtime inventory; developer artifacts never belong in a ZIP."""
    names = {path.name for path in source.glob("*.py")}
    names.update({"LICENSE.txt", "THIRD_PARTY_NOTICES.md", "blender_manifest.toml"})
    for directory, suffixes in (("assets", {".png", ".jpg", ".blend"}),
                                ("licenses", {".txt"})):
        names.update(path.relative_to(source).as_posix()
                     for path in (source / directory).rglob("*")
                     if path.is_file() and path.suffix.lower() in suffixes)
    return names


def audit_package(path: Path, source: Path, platform: str) -> dict:
    source_manifest = tomllib.loads((source / "blender_manifest.toml").read_text("utf-8"))
    expected_wheels = {name.removeprefix("./") for name in source_manifest["wheels"]
                       if "py3-none-any" in name or TAGS[platform] in name}
    if len(expected_wheels) != 4:
        raise ValueError(f"Unexpected wheel inventory for {platform}")
    expected = runtime_files(source) | expected_wheels
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate archive entries")
        for name in names:
            parts = PurePosixPath(name).parts
            if "\\" in name or ":" in name or name.startswith("/") or ".." in parts:
                raise ValueError(f"Unsafe archive path: {name}")
        if set(names) != expected:
            raise ValueError(f"Unexpected entries: {sorted(set(names) - expected)}; "
                             f"missing entries: {sorted(expected - set(names))}")
        if archive.testzip() is not None:
            raise ValueError("ZIP CRC validation failed")
        manifest = tomllib.loads(archive.read("blender_manifest.toml").decode("utf-8"))
        generated = manifest.get("build", {}).get("generated", {})
        effective_wheels = generated.get("wheels", manifest["wheels"])
        effective_platforms = generated.get("platforms", manifest["platforms"])
        if set(name.removeprefix("./") for name in effective_wheels) != expected_wheels:
            raise ValueError("Manifest wheel inventory differs from archive")
        if effective_platforms != [platform.replace("_", "-")]:
            raise ValueError("Split package must target exactly one platform")
        # Blender may retain the full platform list or narrow it for a split ZIP.
        if platform.replace("_", "-") not in manifest["platforms"]:
            raise ValueError("Manifest does not support target platform")
        if not set(manifest["platforms"]) <= set(source_manifest["platforms"]):
            raise ValueError("Unexpected supported platform")
        for key in source_manifest.keys() | manifest.keys():
            if key not in {"build", "wheels", "platforms"}:
                if source_manifest.get(key) != manifest.get(key):
                    raise ValueError(f"Manifest mismatch: {key}")
        python_count = 0
        for name in sorted(expected - {"blender_manifest.toml"}):
            data = archive.read(name)
            if data != (source / name).read_bytes():
                raise ValueError(f"Source mismatch: {name}")
            if name.endswith(".py"):
                ast.parse(data, filename=name)
                python_count += 1
    return {"file": path.name, "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "entries": len(expected), "python_modules": python_count,
            "wheels": len(expected_wheels), "source_matches": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--source", type=Path, default=ROOT / "frame_by_plane")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None)
    version = tomllib.loads((args.source / "blender_manifest.toml").read_text("utf-8"))["version"]
    rows = []
    for platform in sorted(TAGS):
        path = args.directory / f"frame_by_plane-{version}-{platform}.zip"
        rows.append(audit_package(path, args.source, platform))
        print(f"PASS: {path.name}")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({"version": version, "passed": True,
                                          "packages": rows}, indent=2) + "\n", "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
