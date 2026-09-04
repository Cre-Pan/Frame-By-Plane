#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path(__file__).resolve().with_name("blender_lts_suite.py")
from runner_process import run_logged_process

_BLENDER_VERSION_RE = re.compile(r"^Blender\s+(\d+)\.(\d+)\.(\d+)(?:\D|$)")


def blender_version(binary: Path):
    try:
        run = subprocess.run(
            [str(binary), "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", (), str(exc)
    text = run.stdout or run.stderr or ""
    first = text.splitlines()[0].strip() if text else ""
    match = _BLENDER_VERSION_RE.match(first)
    parsed = tuple(int(value) for value in match.groups()) if match else ()
    return run.returncode, first, parsed, ""


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    temp.replace(path)


def _load_report(path: Path):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"Invalid or unreadable report: {exc}"
    if not isinstance(payload, dict):
        return None, "Report root is not a JSON object"
    return payload, ""


def _interactive_prefix():
    if os.name == "nt" or os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return []
    xvfb = shutil.which("xvfb-run")
    if xvfb:
        return [xvfb, "-a", "-s", "-screen 0 1280x800x24"]
    return None


def run_suite(binary: Path, suite: str, output: Path, *, timeout_seconds: int):
    # Never accept a stale PASS report after a native Blender crash that occurs
    # before the current process can write a new result.
    try:
        output.unlink()
    except FileNotFoundError:
        pass
    run_id = uuid.uuid4().hex
    artifacts = output.with_name(f"{output.stem}_artifacts_{run_id[:12]}")
    artifacts.mkdir(parents=True, exist_ok=False)

    user_root = artifacts / "blender_user"
    workdir = artifacts / "work"
    workdir.mkdir(parents=True, exist_ok=True)
    stdout_path = artifacts / "stdout.log"
    stderr_path = artifacts / "stderr.log"

    env = os.environ.copy()
    env.update({
        "FBP_TEST_RUN_ID": run_id,
        "BLENDER_USER_CONFIG": str(user_root / "config"),
        "BLENDER_USER_SCRIPTS": str(user_root / "scripts"),
        "BLENDER_USER_DATAFILES": str(user_root / "datafiles"),
        "FBP_TEST_SOURCE": str(ROOT),
        "FBP_TEST_REPORT": str(output),
        "FBP_TEST_SUITE": suite,
        "FBP_TEST_WORKDIR": str(workdir),
        "TMPDIR": str(workdir),
        "TMP": str(workdir),
        "TEMP": str(workdir),
    })

    command = [str(binary), "--factory-startup"]
    if suite == "background":
        command.append("--background")
    elif suite == "interactive":
        prefix = _interactive_prefix()
        if prefix is None:
            payload = {
                "suite": suite,
                "passed": False,
                "fatal": "Interactive suite requires DISPLAY/WAYLAND_DISPLAY or xvfb-run on Linux.",
                "exit_code": None,
                "artifacts": str(artifacts),
            }
            _write_json(output, payload)
            return payload
        command = prefix + command
    command += ["--python", str(RUNNER)]

    timed_out = False
    exit_code = None
    try:
        with stdout_path.open("w", encoding="utf-8", errors="replace") as stdout, stderr_path.open(
            "w", encoding="utf-8", errors="replace"
        ) as stderr:
            exit_code, timed_out, launch_error, termination = run_logged_process(
                command,
                env=env,
                cwd=ROOT,
                stdout=stdout,
                stderr=stderr,
                timeout_seconds=timeout_seconds,
            )
        if launch_error:
            payload = {
                "suite": suite,
                "passed": False,
                "fatal": f"Could not launch Blender: {launch_error}",
                "exit_code": None,
                "artifacts": str(artifacts),
            }
            _write_json(output, payload)
            return payload
    except OSError as exc:
        payload = {
            "suite": suite,
            "passed": False,
            "fatal": f"Could not prepare Blender logs: {exc}",
            "exit_code": None,
            "artifacts": str(artifacts),
        }
        _write_json(output, payload)
        return payload

    report, report_error = _load_report(output) if output.exists() else (None, "Blender exited before writing the report")
    if report is None:
        report = {
            "suite": suite,
            "passed": False,
            "fatal": (
                f"Suite timed out after {timeout_seconds} seconds"
                if timed_out
                else report_error
            ),
        }
    elif str(report.get("run_id", "") or "") != run_id:
        report = {
            "suite": suite,
            "passed": False,
            "fatal": "The Blender suite report did not match the current run id",
            "reported_run_id": str(report.get("run_id", "") or ""),
        }
    report["run_id"] = run_id
    report["exit_code"] = exit_code
    report["timed_out"] = timed_out
    report["timeout_termination"] = termination if timed_out else ""
    report["command"] = command
    report["artifacts"] = str(artifacts)
    report["stdout_log"] = str(stdout_path)
    report["stderr_log"] = str(stderr_path)
    report["passed"] = bool(report.get("passed", False)) and not timed_out and exit_code == 0
    _write_json(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description="Run Frame By Plane Blender 5.2 LTS regression suites")
    parser.add_argument("--blender", required=True, type=Path)
    parser.add_argument("--all", action="store_true", help="Run background and interactive suites")
    parser.add_argument("--interactive", action="store_true", help="Run only the interactive UI suite")
    parser.add_argument("--output", type=Path, default=ROOT / "tests" / "lts_test_report.json")
    parser.add_argument("--background-timeout", type=int, default=900)
    parser.add_argument("--interactive-timeout", type=int, default=1200)
    ns = parser.parse_args()

    binary = ns.blender.expanduser().resolve()
    if not binary.is_file():
        raise SystemExit(f"Blender executable not found: {binary}")
    code, version, parsed_version, probe_error = blender_version(binary)
    if code or parsed_version[:2] != (5, 2):
        detail = probe_error or version or "unavailable"
        raise SystemExit(f"Expected Blender 5.2.x, got: {detail}")

    output = ns.output.expanduser().resolve()
    suites = ["background", "interactive"] if ns.all else (["interactive"] if ns.interactive else ["background"])
    runs = []
    for suite in suites:
        path = output.with_name(f"{output.stem}_{suite}{output.suffix}")
        timeout_seconds = ns.interactive_timeout if suite == "interactive" else ns.background_timeout
        report = run_suite(binary, suite, path, timeout_seconds=timeout_seconds)
        runs.append({
            "suite": suite,
            "passed": bool(report.get("passed", False)),
            "exit_code": report.get("exit_code"),
            "report": str(path),
            "artifacts": report.get("artifacts", ""),
        })

    combined = {
        "blender": version,
        "binary": str(binary),
        "source": str(ROOT),
        "passed": all(item["passed"] for item in runs),
        "runs": runs,
    }
    _write_json(output, combined)
    for item in runs:
        state = "PASS" if item["passed"] else "FAIL"
        print(f"[{state}] {item['suite']}: {item['report']}")
    return 0 if combined["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
