from __future__ import annotations

import os
import signal
import subprocess
import time


def _terminate_process_tree(process, *, grace_seconds=5.0):
    if process is None or process.poll() is not None:
        return "already-exited"
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True, text=True, timeout=15, check=False,
            )
            try:
                process.wait(timeout=max(1.0, float(grace_seconds)))
            except subprocess.TimeoutExpired:
                process.kill()
            return f"taskkill:{result.returncode}"
        except (OSError, subprocess.SubprocessError):
            process.kill()
            return "kill"
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        try:
            process.terminate()
        except OSError:
            return "missing"
    deadline = time.monotonic() + max(0.5, float(grace_seconds))
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            try:
                process.kill()
            except OSError:
                pass
        return "sigkill"
    return "sigterm"


def run_logged_process(command, *, cwd, env, stdout, stderr, timeout_seconds):
    kwargs = {
        "cwd": str(cwd),
        "env": env,
        "stdout": stdout,
        "stderr": stderr,
        "text": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    process = None
    try:
        process = subprocess.Popen(command, **kwargs)
        exit_code = process.wait(timeout=max(1, int(timeout_seconds)))
        return exit_code, False, "", ""
    except subprocess.TimeoutExpired:
        termination = _terminate_process_tree(process)
        return process.poll() if process is not None else None, True, "", termination
    except OSError as exc:
        if process is not None:
            _terminate_process_tree(process)
        return None, False, str(exc), ""
