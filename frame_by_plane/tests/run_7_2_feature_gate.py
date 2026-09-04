#!/usr/bin/env python3
"""Run the focused Frame By Plane 7.2 feature regressions in Blender 5.2."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


TEST_ROOT = Path(__file__).resolve().parent
TESTS = (
    "gp_vertex_colors_regression.py",
    "gp_vertex_color_undo_regression.py",
    "gp_paint_undo_regression.py",
    "compositor_opt_in_regression.py",
    "image_properties_regression.py",
    "addon_lifecycle_regression.py",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", required=True, type=Path)
    parser.add_argument("--installed", action="store_true")
    parser.add_argument("--package", default="bl_ext.fbp_audit.frame_by_plane")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    blender = args.blender.expanduser().resolve()
    if not blender.is_file():
        raise SystemExit(f"Blender executable not found: {blender}")

    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if args.installed:
        environment["FBP_TEST_INSTALLED"] = "1"
        environment["FBP_TEST_PACKAGE"] = args.package
    else:
        environment.pop("FBP_TEST_INSTALLED", None)
        environment["FBP_TEST_PACKAGE"] = "frame_by_plane"

    failed = []
    selected_tests = tuple(
        name for name in TESTS
        if not (args.installed and name == "addon_lifecycle_regression.py")
    )
    for name in selected_tests:
        test = TEST_ROOT / name
        command = [str(blender), "--background"]
        if not args.installed:
            command.append("--factory-startup")
        command += ["--python-exit-code", "1", "--python", str(test)]
        print(f"[RUN] {name}", flush=True)
        try:
            result = subprocess.run(
                command,
                cwd=str(TEST_ROOT.parents[1]),
                env=environment,
                timeout=max(30, args.timeout),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"[FAIL] {name}: {exc}", file=sys.stderr, flush=True)
            failed.append(name)
            continue
        if result.returncode:
            print(f"[FAIL] {name}: Blender exit {result.returncode}", file=sys.stderr, flush=True)
            failed.append(name)
        else:
            print(f"[PASS] {name}", flush=True)

    if failed:
        print("7.2 feature gate failed: " + ", ".join(failed), file=sys.stderr)
        return 1
    print(f"7.2 feature gate passed: {len(selected_tests)} scripts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
