#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITE = Path(__file__).resolve().with_name("blender_lts_suite.py")
from runner_process import run_logged_process


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


def _bpy_version(python: Path):
    code = (
        "import bpy,json; "
        "print(json.dumps({'version': list(bpy.app.version), "
        "'version_string': bpy.app.version_string, "
        "'binary': bpy.app.binary_path or '<bpy-module>'}))"
    )
    try:
        probe = subprocess.run(
            [str(python), "-c", code],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, (), "", "", str(exc)
    payload = None
    for line in reversed((probe.stdout or "").splitlines()):
        try:
            candidate = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(candidate, dict) and isinstance(candidate.get("version"), list):
            payload = candidate
            break
    if payload is None:
        return probe.returncode or 1, (), "", "", (probe.stderr or probe.stdout or "").strip()
    parsed = tuple(int(value) for value in payload.get("version", ())[:3])
    return probe.returncode, parsed, str(payload.get("version_string", "")), str(payload.get("binary", "")), ""


def run(python: Path, output: Path, *, timeout_seconds: int):
    try:
        output.unlink()
    except FileNotFoundError:
        pass
    run_id = uuid.uuid4().hex
    artifacts = output.with_name(f"{output.stem}_artifacts_{run_id[:12]}")
    artifacts.mkdir(parents=True, exist_ok=False)
    workdir = artifacts / "work"
    workdir.mkdir(parents=True, exist_ok=True)
    stdout_path = artifacts / "stdout.log"
    stderr_path = artifacts / "stderr.log"

    env = os.environ.copy()
    env.update({
        "FBP_TEST_RUN_ID": run_id,
        "FBP_TEST_SOURCE": str(ROOT),
        "FBP_TEST_REPORT": str(output),
        "FBP_TEST_SUITE": "background",
        "FBP_TEST_WORKDIR": str(workdir),
        "FBP_TEST_NO_QUIT": "1",
        "TMPDIR": str(workdir),
        "TMP": str(workdir),
        "TEMP": str(workdir),
    })
    command = [str(python), str(SUITE)]
    timed_out = False
    exit_code = None
    try:
        with stdout_path.open("w", encoding="utf-8", errors="replace") as stdout, stderr_path.open(
            "w", encoding="utf-8", errors="replace"
        ) as stderr:
            exit_code, timed_out, launch_error, termination = run_logged_process(
                command, cwd=ROOT, env=env, stdout=stdout, stderr=stderr,
                timeout_seconds=timeout_seconds,
            )
        if launch_error:
            payload = {
                "suite": "background-bpy-module",
                "passed": False,
                "fatal": f"Could not launch Python: {launch_error}",
                "exit_code": None,
                "artifacts": str(artifacts),
            }
            _write_json(output, payload)
            return payload
    except OSError as exc:
        payload = {
            "suite": "background-bpy-module",
            "passed": False,
            "fatal": f"Could not prepare Python logs: {exc}",
            "exit_code": None,
            "artifacts": str(artifacts),
        }
        _write_json(output, payload)
        return payload

    report, error = _load_report(output) if output.exists() else (None, "bpy exited before writing the report")
    if report is None:
        report = {
            "suite": "background-bpy-module",
            "passed": False,
            "fatal": f"Suite timed out after {timeout_seconds} seconds" if timed_out else error,
        }
    elif str(report.get("run_id", "") or "") != run_id:
        report = {
            "suite": "background-bpy-module",
            "passed": False,
            "fatal": "The bpy suite report did not match the current run id",
            "reported_run_id": str(report.get("run_id", "") or ""),
        }
    report.update({
        "run_id": run_id,
        "runner": "bpy-module",
        "exit_code": exit_code,
        "timed_out": timed_out,
        "timeout_termination": termination if timed_out else "",
        "command": command,
        "artifacts": str(artifacts),
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
    })
    report["passed"] = bool(report.get("passed", False)) and not timed_out and exit_code == 0
    _write_json(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description="Run Frame By Plane background tests with the official bpy 5.2 module")
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--output", type=Path, default=ROOT / "tests" / "bpy_lts_test_report.json")
    parser.add_argument("--timeout", type=int, default=1200)
    ns = parser.parse_args()

    python = ns.python.expanduser().resolve()
    if not python.is_file():
        raise SystemExit(f"Python executable not found: {python}")
    code, parsed_version, version, binary, probe_error = _bpy_version(python)
    if code or parsed_version[:2] != (5, 2):
        detail = probe_error or version or "unavailable"
        raise SystemExit(f"Expected the official bpy 5.2.x module, got: {detail}")

    report = run(python, ns.output.resolve(), timeout_seconds=ns.timeout)
    state = "PASS" if report.get("passed", False) else "FAIL"
    print(f"[{state}] bpy {version} ({binary or 'module'}) — {ns.output}")
    return 0 if report.get("passed", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
