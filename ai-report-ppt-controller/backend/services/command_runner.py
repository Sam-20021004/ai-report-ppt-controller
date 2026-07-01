from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from backend.services.security import command_is_allowed, mask_sensitive


class CommandBlockedError(RuntimeError):
    pass


def resolve_command(command: str) -> str | None:
    if not command:
        return None
    if Path(command).exists():
        return command
    return shutil.which(command)


def run_whitelisted(command: str, args: list[str], allowed: list[str], timeout: int = 12) -> dict:
    if not command_is_allowed(command, allowed):
        raise CommandBlockedError(f"Command is not whitelisted: {Path(command).name}")

    resolved = resolve_command(command)
    if not resolved:
        return {
            "ok": False,
            "status": "missing",
            "command": command,
            "raw_output": "",
            "detail": "Command was not found on PATH.",
            "elapsed_ms": 0,
        }

    started = time.perf_counter()
    try:
        completed = subprocess.run(
            [resolved, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            encoding="utf-8",
            errors="replace",
        )
        elapsed = int((time.perf_counter() - started) * 1000)
        output = mask_sensitive((completed.stdout or "") + (completed.stderr or ""))
        return {
            "ok": completed.returncode == 0,
            "status": "success" if completed.returncode == 0 else "failed",
            "command": resolved,
            "raw_output": output.strip(),
            "detail": f"exit_code={completed.returncode}",
            "elapsed_ms": elapsed,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "status": "timeout",
            "command": resolved,
            "raw_output": "",
            "detail": f"Command timed out after {timeout}s.",
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
    except OSError as exc:
        return {
            "ok": False,
            "status": "blocked",
            "command": resolved,
            "raw_output": "",
            "detail": str(exc),
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
