#!/usr/bin/env python3
"""Static repository checks that do not require Blender."""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "frame_by_plane"
MANIFEST = ADDON / "blender_manifest.toml"
CONSTANTS = ADDON / "constants.py"
EXPECTED_PLATFORMS = {
    "windows-x64",
    "windows-arm64",
    "macos-x64",
    "macos-arm64",
    "linux-x64",
}


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_constant_version() -> tuple[int, int, int]:
    module = ast.parse(CONSTANTS.read_text(encoding="utf-8"))
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "FBP_VERSION" for target in node.targets):
            continue
        value = ast.literal_eval(node.value)
        if isinstance(value, tuple) and len(value) == 3 and all(isinstance(part, int) for part in value):
            return value
    fail("FBP_VERSION was not found in constants.py")


def main() -> None:
    required = [
        ROOT / "README.md",
        ROOT / "CHANGELOG.md",
        ROOT / "LICENSE",
        ROOT / "THIRD_PARTY_NOTICES.md",
        ADDON / "__init__.py",
        MANIFEST,
        CONSTANTS,
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        fail("Missing required files: " + ", ".join(missing))

    data = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest_version = data.get("version")
    source_version = ".".join(str(part) for part in read_constant_version())
    if manifest_version != source_version:
        fail(f"Version mismatch: manifest={manifest_version!r}, constants={source_version!r}")

    platforms = set(data.get("platforms", []))
    if platforms != EXPECTED_PLATFORMS:
        fail(f"Unexpected platform set: {sorted(platforms)}")

    wheels = data.get("wheels", [])
    if not wheels:
        fail("Manifest does not declare bundled wheels")
    missing_wheels = []
    for wheel in wheels:
        wheel_path = ADDON / str(wheel).removeprefix("./")
        if not wheel_path.is_file():
            missing_wheels.append(str(wheel_path.relative_to(ROOT)))
    if missing_wheels:
        fail("Missing declared wheels: " + ", ".join(missing_wheels))

    forbidden = []
    for path in ADDON.rglob("*"):
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".zip", ".bak"}:
            forbidden.append(str(path.relative_to(ROOT)))
    if forbidden:
        fail("Generated or forbidden files found: " + ", ".join(forbidden[:20]))

    print(f"Frame By Plane {manifest_version}: repository checks passed")
    print(f"Declared platforms: {', '.join(sorted(platforms))}")
    print(f"Bundled wheels: {len(wheels)}")


if __name__ == "__main__":
    main()
