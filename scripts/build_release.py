#!/usr/bin/env python3
"""Build or validate an installable Frame By Plane extension ZIP."""

from __future__ import annotations

import argparse
import compileall
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "frame_by_plane"
DIST = ROOT / "dist"
MANIFEST = SOURCE / "blender_manifest.toml"

EXCLUDED_PARTS = {"__pycache__", ".git", "_fbp_update_backups"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".blend1", ".bak", ".log", ".diff", ".sha256"}


def manifest_version() -> str:
    text = MANIFEST.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise RuntimeError("Could not read version from blender_manifest.toml")
    return match.group(1)


def iter_source_files():
    for path in sorted(SOURCE.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(SOURCE)
        if any(part in EXCLUDED_PARTS or part.startswith(".") for part in relative.parts):
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES or path.name.endswith("~"):
            continue
        yield path, relative


def validate() -> None:
    required = [SOURCE / "__init__.py", MANIFEST, SOURCE / "LICENSE.txt"]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(f"Missing required files: {', '.join(missing)}")
    if not compileall.compile_dir(str(SOURCE), quiet=1, force=True):
        raise RuntimeError("Python compilation failed")


def build() -> Path:
    validate()
    version = manifest_version()
    DIST.mkdir(exist_ok=True)
    output = DIST / f"frame_by_plane-{version}.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, relative in iter_source_files():
            archive.write(path, relative.as_posix())
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Validate without creating a ZIP")
    args = parser.parse_args()
    try:
        validate()
        if args.check:
            print(f"Frame By Plane {manifest_version()} validation passed")
        else:
            output = build()
            print(output.relative_to(ROOT))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
