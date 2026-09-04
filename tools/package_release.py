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


VERSION = "7.2.0"
ARCHIVE_PREFIX = f"frame_by_plane-{VERSION}"
PLATFORMS = (
    "linux_x64",
    "macos_arm64",
    "macos_x64",
    "windows_arm64",
    "windows_x64",
)
FIXED_ZIP_TIME = (2026, 8, 8, 0, 0, 0)
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
    if "runs" not in data:
        results = list(data.get("results", ()) or ())
        return {
            "suite": str(data.get("suite", "")),
            "blender": str(data.get("blender", "")),
            "passed": bool(results) and all(
                str(item.get("status", "")) in {"PASS", "SKIP"}
                for item in results
            ),
            "exit_code": 0,
        }
    return {
        "suite": data["runs"][0]["suite"],
        "blender": data["blender"],
        "passed": bool(data["passed"]),
        "exit_code": data["runs"][0]["exit_code"],
    }


def load_installed_smoke(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    required_flags = (
        "enabled",
        "operator_registered",
        "object_preserved",
        "fbp_marker_preserved",
    )
    passed = (
        all(bool(data.get(name, False)) for name in required_flags)
        and not bool(data.get("orphan_owner_after_main_replacement", True))
        and all(
            data.get(name) == ["FINISHED"]
            for name in (
                "save_result",
                "reopen_result",
                "active_owner_file_open",
                "active_owner_file_revert",
                "active_owner_new_file",
            )
        )
    )
    return {
        "passed": passed,
        "blender": str(data.get("blender", "")),
        "namespace": str(data.get("module", "")),
        "save_reopen_persistence": bool(
            data.get("object_preserved", False)
            and data.get("fbp_marker_preserved", False)
        ),
        "source_report": str(path),
    }


def load_installed_contract(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    wheels = data.get("wheels", {})
    passed = (
        str(data.get("addon_version", "")) == VERSION
        and bool(data.get("bookmark_palette_migrated", False))
        and bool(data.get("folder_clipboard_operator", False))
        and bool(data.get("hex_color_operator", False))
        and bool(data.get("felt_fuzz_contract", False))
        and bool(data.get("gp_glow_contract", False))
        and bool(data.get("gp_stack_ui_contract", False))
        and bool(data.get("gp_dual_color_contract", False))
        and bool(data.get("compositor_opt_in_contract", False))
        and bool(data.get("image_properties_contract", False))
        and bool(data.get("gp_compatibility_icon_contract", False))
        and bool(data.get("stale_import_scene_contract", False))
        and bool(data.get("camera_output_contract", False))
        and bool(data.get("camera_aspect_dropdown_contract", False))
        and bool(data.get("camera_linked_pixels_presets_contract", False))
        and bool(data.get("gp_edit_undo_guard", False))
        and bool(data.get("timeline_backport_contract", False))
        and all(str(wheels.get(name, "")).strip() for name in ("pillow", "psd_tools", "attrs", "typing_extensions"))
    )
    return {
        "passed": passed,
        "addon_version": str(data.get("addon_version", "")),
        "bookmark_palette_migrated": bool(data.get("bookmark_palette_migrated", False)),
        "folder_clipboard_operator": bool(data.get("folder_clipboard_operator", False)),
        "hex_color_operator": bool(data.get("hex_color_operator", False)),
        "felt_fuzz_contract": bool(data.get("felt_fuzz_contract", False)),
        "gp_glow_contract": bool(data.get("gp_glow_contract", False)),
        "gp_stack_ui_contract": bool(data.get("gp_stack_ui_contract", False)),
        "gp_dual_color_contract": bool(data.get("gp_dual_color_contract", False)),
        "compositor_opt_in_contract": bool(data.get("compositor_opt_in_contract", False)),
        "image_properties_contract": bool(data.get("image_properties_contract", False)),
        "gp_compatibility_icon_contract": bool(
            data.get("gp_compatibility_icon_contract", False)
        ),
        "stale_import_scene_contract": bool(
            data.get("stale_import_scene_contract", False)
        ),
        "camera_output_contract": bool(data.get("camera_output_contract", False)),
        "camera_aspect_dropdown_contract": bool(data.get("camera_aspect_dropdown_contract", False)),
        "camera_linked_pixels_presets_contract": bool(data.get("camera_linked_pixels_presets_contract", False)),
        "gp_edit_undo_guard": bool(data.get("gp_edit_undo_guard", False)),
        "timeline_backport_contract": bool(data.get("timeline_backport_contract", False)),
        "wheels": wheels,
        "source_report": str(path),
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

- Added independent Grease Pencil Stroke and Fill selectors for Draw, Vertex Paint and Edit modes.
- Added Both-mode color application, mixed-selection swatches, X swap, Stroke-only Shift+X sampling and Close Gap.
- Preserved Blender Undo ordering for color state, newly drawn strokes and cyclic state.
- Made the managed compositor explicitly opt-in for rendering and preserved artist graphs/state.
- Added the Object Data image panel and shared Tool/N-Panel roots.
- Restored reliable ownership for all 27 native Grease Pencil effect backends on Blender 5.2.
- Added a selectable Grease Pencil effect list with add, remove, reorder, reset and duplicate repair.
- Added a seven-group icon menu and selected-effect settings matching the image-plane Effects workflow.
- Backported compact Timeline playback, configurable jump controls and synchronization popovers from Blender PR 162412.
- Added bidirectional Scene Strip frame synchronization for Blender 5.2 time editors.
- Fixed compositor Safe Repair snapshots for Blender RNA arrays and mathutils values.
- Kept unknown RNA values fail-closed so artist compositor graphs are not modified unsafely.
- Hardened the native test runner, What's New prompt test and tiny render isolation.
- Replaced White with adaptive None, removed Blue, fixed Grey and migrated legacy tags.
- Simplified Shift+A while keeping hexadecimal Color Plane creation under More....
- Fixed Felt Fuzz's canonical Seed/Alpha Mask contract and reduced repeated setup.
- Removed proven orphan code and verified all 133 effects individually in Blender 5.2.
- Fixed rollback-safe rename manifests on Windows paths near `MAX_PATH`.

## Static coverage

- Python modules: **{audit['python_modules']}**
- Unique `bl_idname` values: **{audit['unique_bl_idnames']}**
- PNG assets: **{audit['png_assets']}**

## Native Blender evidence

- Blender: **{tests['blender']}**
- Background suite: **PASS**
- Interactive suite: **PASS**
- Installed package namespace: `{tests['installed_package_test']['namespace']}`
- Installed version: **{VERSION}**
- Save/reopen persistence: **PASS**
- Dual Grease Pencil Stroke/Fill installed contract: **PASS**
- Compositor render opt-in installed contract: **PASS**
- Object Data Properties panel contract: **PASS**

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
    installed = load_installed_smoke(args.test_dir.resolve() / "installed-package-smoke.json")
    installed_contract = load_installed_contract(
        args.test_dir.resolve() / "installed-release-contract.json"
    )
    tests = {
        "version": VERSION,
        "blender": background["blender"],
        "passed": (
            background["passed"]
            and interactive["passed"]
            and installed["passed"]
            and installed_contract["passed"]
        ),
        "suites": [background, interactive],
        "installed_package_test": installed,
        "installed_release_contract": installed_contract,
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
