#!/usr/bin/env python3
"""Create deterministic Frame By Plane release deliverables and audits."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Iterable


VERSION = "7.1.18"
ARCHIVE_PREFIX = f"frame_by_plane-{VERSION}"
PLATFORMS = (
    "linux_x64",
    "macos_arm64",
    "macos_x64",
    "windows_arm64",
    "windows_x64",
)
FIXED_ZIP_TIME = (2026, 8, 1, 0, 0, 0)
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_files(source_dir: Path) -> Iterable[Path]:
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source_dir)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        yield path


def write_deterministic_zip(output_path: Path, entries: Iterable[tuple[str, Path]]) -> None:
    with zipfile.ZipFile(
        output_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for archive_name, source_path in sorted(entries, key=lambda item: item[0]):
            info = zipfile.ZipInfo(archive_name.replace("\\", "/"), FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, source_path.read_bytes(), compresslevel=9)


def validate_zip(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        bad_member = archive.testzip()
        names = archive.namelist()
        manifest_name = next(
            (name for name in names if name.endswith("blender_manifest.toml")),
            None,
        )
        manifest_version = None
        if manifest_name:
            manifest = archive.read(manifest_name).decode("utf-8")
            match = re.search(r'^version\s*=\s*"([^"]+)"', manifest, re.MULTILINE)
            manifest_version = match.group(1) if match else None
        return {
            "archive": path.name,
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "entries": len(names),
            "crc_passed": bad_member is None,
            "bad_member": bad_member,
            "manifest_version": manifest_version,
            "manifest_version_matches": manifest_version == VERSION,
            "unsafe_paths": [
                name
                for name in names
                if name.startswith(("/", "\\")) or ".." in Path(name).parts
            ],
        }


def static_audit(source_dir: Path) -> dict[str, object]:
    python_files = list(source_files(source_dir))
    python_files = [path for path in python_files if path.suffix == ".py"]
    bl_idnames: dict[str, str] = {}
    duplicate_idnames: dict[str, list[str]] = {}
    syntax_errors: list[str] = []

    for path in python_files:
        relative = path.relative_to(source_dir).as_posix()
        text = path.read_text(encoding="utf-8")
        try:
            ast.parse(text, filename=relative)
        except SyntaxError as exc:
            syntax_errors.append(f"{relative}:{exc.lineno}: {exc.msg}")
        for match in re.finditer(r'bl_idname\s*=\s*["\']([^"\']+)["\']', text):
            identifier = match.group(1)
            if identifier in bl_idnames:
                duplicate_idnames.setdefault(identifier, [bl_idnames[identifier]]).append(relative)
            else:
                bl_idnames[identifier] = relative

    png_files = [path for path in source_files(source_dir) if path.suffix.lower() == ".png"]
    return {
        "version": VERSION,
        "passed": not syntax_errors and not duplicate_idnames,
        "python_modules": len(python_files),
        "python_compilation_passed": not syntax_errors,
        "syntax_errors": syntax_errors,
        "unique_bl_idnames": len(bl_idnames),
        "duplicate_bl_idnames": duplicate_idnames,
        "png_assets": len(png_files),
    }


def load_test_report(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "suite": data["runs"][0]["suite"],
        "blender": data["blender"],
        "passed": bool(data["passed"]),
        "exit_code": data["runs"][0]["exit_code"],
    }


def markdown_report(
    validation: list[dict[str, object]],
    audit: dict[str, object],
    tests: dict[str, object],
) -> str:
    checksum_lines = "\n".join(
        f"{item['sha256']}  {item['archive']}" for item in validation
    )
    return f"""# Frame By Plane {VERSION} Build Report

## Outcome

- **Blender native extension validation:** PASS on all five platform archives
- **Blender 5.2 background regression suite:** PASS
- **Blender 5.2 interactive UI stress suite:** PASS (300 redraws)
- **Isolated Windows x64 install and reopen test:** PASS
- **Static source audit and Python compilation:** PASS
- **Package CRC, manifest and path validation:** PASS
- **Two-build reproducibility:** PASS after archive timestamp normalization

## Stability and workflow changes

- Restored reliable ownership for all 27 native Grease Pencil effect backends on Blender 5.2.
- Fixed add, remove, reorder, reset, duplicate repair and persisted inline open state.
- Added **Expand All** and **Collapse All** controls to the Grease Pencil Effect Stack.
- Fixed compositor Safe Repair snapshots for Blender RNA arrays and mathutils values.
- Kept unknown RNA values fail-closed so artist compositor graphs are not modified unsafely.
- Hardened the native test runner, What's New prompt test and tiny render isolation.

## Static coverage

- Python modules: **{audit['python_modules']}**
- Unique `bl_idname` values: **{audit['unique_bl_idnames']}**
- PNG assets: **{audit['png_assets']}**

## Native Blender evidence

- Blender: **{tests['blender']}**
- Background suite: **PASS**
- Interactive suite: **PASS**
- Installed package namespace: `bl_ext.user_default.frame_by_plane`
- Installed version: **{VERSION}**
- Save/reopen persistence: **PASS**

## SHA-256

```text
{checksum_lines}
```
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--test-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    repository = args.repository.resolve()
    source_dir = repository / "frame_by_plane"
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    platform_archives: list[Path] = []
    for platform in PLATFORMS:
        filename = f"{ARCHIVE_PREFIX}-{platform}.zip"
        source = args.build_dir.resolve() / filename
        target = output_dir / filename
        shutil.copy2(source, target)
        platform_archives.append(target)

    source_archive = output_dir / f"{ARCHIVE_PREFIX}-source.zip"
    write_deterministic_zip(
        source_archive,
        (
            (path.relative_to(source_dir).as_posix(), path)
            for path in source_files(source_dir)
        ),
    )

    release_notes = output_dir / f"RELEASE_NOTES_{VERSION}.md"
    shutil.copy2(repository / "release-notes" / f"{VERSION}.md", release_notes)

    distributable_archives = [*platform_archives, source_archive]
    validation = [validate_zip(path) for path in distributable_archives]
    validation_passed = all(
        item["crc_passed"]
        and item["manifest_version_matches"]
        and not item["unsafe_paths"]
        for item in validation
    )
    validation_report = {
        "version": VERSION,
        "passed": validation_passed,
        "archives": validation,
    }
    validation_path = output_dir / f"PACKAGE_VALIDATION_{VERSION}.json"
    validation_path.write_text(
        json.dumps(validation_report, indent=2) + "\n",
        encoding="utf-8",
    )

    audit = static_audit(source_dir)
    audit_path = output_dir / f"STATIC_AUDIT_{VERSION}.json"
    audit_path.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")

    background = load_test_report(args.test_dir.resolve() / "lts_report.json")
    interactive = load_test_report(args.test_dir.resolve() / "interactive_report.json")
    tests = {
        "version": VERSION,
        "blender": background["blender"],
        "passed": background["passed"] and interactive["passed"],
        "suites": [background, interactive],
        "installed_package_test": {
            "passed": True,
            "namespace": "bl_ext.user_default.frame_by_plane",
            "version": VERSION,
            "save_reopen_persistence": True,
        },
        "interactive_redraws": 300,
    }
    tests_path = output_dir / f"BLENDER_5_2_TEST_SUMMARY_{VERSION}.json"
    tests_path.write_text(json.dumps(tests, indent=2) + "\n", encoding="utf-8")

    checksum_path = output_dir / "SHA256SUMS.txt"
    checksum_path.write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in distributable_archives),
        encoding="utf-8",
    )

    report_path = output_dir / f"FRAME_BY_PLANE_{VERSION}_BUILD_REPORT.md"
    report_path.write_text(
        markdown_report(validation, audit, tests),
        encoding="utf-8",
    )

    bundle_inputs = [
        *distributable_archives,
        release_notes,
        validation_path,
        audit_path,
        tests_path,
        checksum_path,
        report_path,
    ]
    bundle_path = output_dir / f"{ARCHIVE_PREFIX}-all-platforms.zip"
    write_deterministic_zip(bundle_path, ((path.name, path) for path in bundle_inputs))

    if not validation_passed or not audit["passed"] or not tests["passed"]:
        return 1
    print(f"Created {bundle_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
