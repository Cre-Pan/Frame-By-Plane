#!/usr/bin/env python3
"""Static repository checks that do not require Blender."""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "frame_by_plane"
MANIFEST = ADDON / "blender_manifest.toml"
CONSTANTS = ADDON / "constants.py"
SUPPORT_POLICY = ADDON / "support_policy.py"
EXPECTED_PLATFORMS = {
    "windows-x64",
    "windows-arm64",
    "macos-x64",
    "macos-arm64",
    "linux-x64",
}
REQUIRED_BUILD_EXCLUDES = {
    "__pycache__/",
    ".*",
    "*.zip",
    "tests/",
    "FRAME_BY_PLANE_*_BUILD_REPORT.md",
    "FRAME_BY_PLANE_*_ROADMAP_STATUS.md",
    "STATIC_AUDIT_*.json",
    "PACKAGE_VALIDATION_*.json",
}


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_assignment(path: Path, name: str) -> object:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in module.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == name for target in targets):
            continue
        value_node = node.value
        if value_node is None:
            break
        return ast.literal_eval(value_node)
    fail(f"{name} was not found in {path.relative_to(ROOT)}")


def _assigned_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    for target in targets:
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            names.update(item.id for item in target.elts if isinstance(item, ast.Name))
    return names


def undefined_rna_update_callbacks(path: Path) -> list[str]:
    """Find update callbacks unavailable when a class body is executed."""
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    defined: set[str] = set()
    missing: list[str] = []
    for node in module.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                defined.add(alias.asname or alias.name.split(".", 1)[0])
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            defined.update(_assigned_names(node))
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined.add(node.name)
            continue
        if not isinstance(node, ast.ClassDef):
            continue
        for statement in node.body:
            value = getattr(statement, "value", None)
            if value is None:
                continue
            for call in (item for item in ast.walk(value) if isinstance(item, ast.Call)):
                for keyword in call.keywords:
                    if keyword.arg != "update" or not isinstance(keyword.value, ast.Name):
                        continue
                    callback = keyword.value.id
                    if callback not in defined:
                        missing.append(f"{path.relative_to(ROOT)}:{call.lineno}: {callback}")
        defined.add(node.name)
    return missing


def wheel_platform(filename: str) -> str | None:
    if filename.endswith("-py3-none-any.whl"):
        return None
    if filename.endswith("-win_amd64.whl"):
        return "windows-x64"
    if filename.endswith("-win_arm64.whl"):
        return "windows-arm64"
    if "macosx_" in filename and filename.endswith("_x86_64.whl"):
        return "macos-x64"
    if "macosx_" in filename and filename.endswith("_arm64.whl"):
        return "macos-arm64"
    if "manylinux_" in filename and filename.endswith("_x86_64.whl"):
        return "linux-x64"
    fail(f"Wheel platform cannot be classified: {filename}")


def read_string_assignment(path: Path, name: str) -> str:
    module = ast.parse(path.read_text(encoding="utf-8"))
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        value = ast.literal_eval(node.value)
        if isinstance(value, str) and value:
            return value
    fail(f"{name} was not found in {path.name}")


def main() -> None:
    required = [
        ROOT / "README.md",
        ROOT / "CHANGELOG.md",
        ROOT / "LICENSE",
        ROOT / "THIRD_PARTY_NOTICES.md",
        ROOT / ".github" / "workflows" / "validate.yml",
        ROOT / ".github" / "workflows" / "release.yml",
        ROOT / "tools" / "build_release.py",
        ADDON / "__init__.py",
        MANIFEST,
        CONSTANTS,
        SUPPORT_POLICY,
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        fail("Missing required files: " + ", ".join(missing))

    manifest_text = MANIFEST.read_text(encoding="utf-8")
    if "[build.generated]" in manifest_text or "# BEGIN GENERATED CONTENT." in manifest_text:
        fail("Source manifest contains reserved generated build metadata")
    data = tomllib.loads(manifest_text)
    manifest_version = str(data.get("version", ""))
    if not re.fullmatch(r"\d+\.\d+\.\d+", manifest_version):
        fail(f"Invalid manifest version: {manifest_version!r}")

    constant_version = read_assignment(CONSTANTS, "FBP_VERSION")
    if not (isinstance(constant_version, tuple) and len(constant_version) == 3):
        fail("FBP_VERSION must be a three-part tuple")
    source_version = ".".join(str(part) for part in constant_version)
    if manifest_version != source_version:
        fail(f"Version mismatch: manifest={manifest_version!r}, constants={source_version!r}")
    policy_version = read_string_assignment(SUPPORT_POLICY, "FBP_LTS_TARGET_VERSION")
    if manifest_version != policy_version:
        fail(f"Version mismatch: manifest={manifest_version!r}, support_policy={policy_version!r}")

    expected_release_files = [
        ADDON / f"RELEASE_NOTES_{manifest_version}.md",
        ROOT / "release-notes" / f"{manifest_version}.md",
    ]
    missing_release_files = [
        str(path.relative_to(ROOT)) for path in expected_release_files if not path.is_file()
    ]
    if missing_release_files:
        fail("Missing current release notes: " + ", ".join(missing_release_files))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if manifest_version not in readme or "Blender 5.2" not in readme:
        fail("README does not advertise the current release and Blender 5.2 support")

    support_version = read_assignment(SUPPORT_POLICY, "FBP_LTS_TARGET_VERSION")
    if support_version != manifest_version:
        fail(f"Support-policy mismatch: {support_version!r} != {manifest_version!r}")

    release_notes = [
        ROOT / "release-notes" / f"{manifest_version}.md",
        ADDON / f"RELEASE_NOTES_{manifest_version}.md",
    ]
    missing_notes = [str(path.relative_to(ROOT)) for path in release_notes if not path.is_file()]
    if missing_notes:
        fail("Missing release notes: " + ", ".join(missing_notes))

    platforms = set(data.get("platforms", []))
    if platforms != EXPECTED_PLATFORMS:
        fail(f"Unexpected platform set: {sorted(platforms)}")

    build_excludes = set(data.get("build", {}).get("paths_exclude_pattern", []))
    missing_excludes = REQUIRED_BUILD_EXCLUDES - build_excludes
    if missing_excludes:
        fail(f"Build exclusions are incomplete: {sorted(missing_excludes)}")

    wheels = [str(item).removeprefix("./") for item in data.get("wheels", [])]
    if not wheels:
        fail("Manifest does not declare bundled wheels")
    common_count = 0
    native_counts = {platform: 0 for platform in EXPECTED_PLATFORMS}
    missing_wheels = []
    for wheel in wheels:
        wheel_path = ADDON / wheel
        if not wheel_path.is_file():
            missing_wheels.append(str(wheel_path.relative_to(ROOT)))
            continue
        platform = wheel_platform(wheel_path.name)
        if platform is None:
            common_count += 1
        else:
            native_counts[platform] += 1
    if missing_wheels:
        fail("Missing declared wheels: " + ", ".join(missing_wheels))
    if common_count < 1:
        fail("No platform-independent wheel is declared")
    unexpected_counts = {key: value for key, value in native_counts.items() if value != 2}
    if unexpected_counts:
        fail(f"Each platform must declare exactly two native wheels: {unexpected_counts}")

    missing_callbacks = []
    for python_path in sorted(ADDON.rglob("*.py")):
        missing_callbacks.extend(undefined_rna_update_callbacks(python_path))
    if missing_callbacks:
        fail("RNA update callbacks are undefined at class creation: " + "; ".join(missing_callbacks[:20]))

    stale_notes = sorted(
        path.name
        for path in ADDON.glob("RELEASE_NOTES_*.md")
        if path.name != f"RELEASE_NOTES_{manifest_version}.md"
    )
    if stale_notes:
        fail("Stale extension release notes found: " + ", ".join(stale_notes))

    forbidden = []
    for path in ADDON.rglob("*"):
        if (
            "__pycache__" in path.parts
            or path.suffix in {".pyc", ".zip", ".bak", ".log"}
            or "lts_test_report" in path.name
            or any("_artifacts_" in part for part in path.parts)
        ):
            forbidden.append(str(path.relative_to(ROOT)))
    if forbidden:
        fail("Generated or forbidden files found: " + ", ".join(forbidden[:20]))

    print(f"Frame By Plane {manifest_version}: repository checks passed")
    print(f"Declared platforms: {', '.join(sorted(platforms))}")
    print(f"Bundled wheels: {len(wheels)} ({common_count} common, 2 per platform)")


if __name__ == "__main__":
    main()
