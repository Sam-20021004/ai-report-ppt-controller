from __future__ import annotations

import json
import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from backend.config import AppConfig, get_settings
from backend.services.agent_adapters import AgentAdapter, MockCodexAdapter
from backend.services.command_runner import resolve_command
from backend.services.security import mask_sensitive


_AUTH_FAILURE_MARKERS = (
    "not logged in",
    "codex login",
    "login required",
    "authentication required",
    "unauthorized",
)


def resolve_windows_codex(command: str) -> str | None:
    text = str(command or "").strip()
    if not text or text.lower() == "wsl" or text.lower().startswith("wsl:"):
        return None
    return resolve_command(text)


def _parse_json_object(stdout: str) -> dict[str, Any] | None:
    text = stdout.strip()
    if not text:
        return None

    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        pass

    for match in re.finditer(r"```(?:json)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL):
        try:
            payload = json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload

    for start, character in enumerate(text):
        if character != "{":
            continue
        depth = 0
        in_string = False
        escaped = False
        for end in range(start, len(text)):
            current = text[end]
            if in_string:
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    in_string = False
                continue
            if current == '"':
                in_string = True
            elif current == "{":
                depth += 1
            elif current == "}":
                depth -= 1
                if depth == 0:
                    try:
                        payload = json.loads(text[start : end + 1])
                    except json.JSONDecodeError:
                        break
                    if isinstance(payload, dict):
                        return payload
                    break
    return None


def _safe_task_name(task_name: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", task_name).strip("._")
    return normalized or "task"


class WindowsCodexAdapter(AgentAdapter):
    def __init__(self, settings: AppConfig | None = None) -> None:
        self.settings = settings or get_settings()

    def health_check(self) -> dict[str, Any]:
        if str(self.settings.codex_command).strip().lower().startswith("wsl:"):
            return {
                "name": "codex",
                "ok": False,
                "status": "missing",
                "error_code": "codex_windows_required",
                "detail": "The three-agent profile requires Windows-native Codex.",
            }

        resolved = resolve_windows_codex(self.settings.codex_command)
        if not resolved:
            return {
                "name": "codex",
                "ok": False,
                "status": "missing",
                "error_code": "codex_missing",
                "detail": "Windows Codex command was not found on PATH.",
            }

        started = time.perf_counter()
        try:
            completed = subprocess.run(
                [resolved, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                shell=False,
                encoding="utf-8",
                errors="replace",
            )
        except PermissionError:
            return self._health_failure("codex_access_denied", started)
        except FileNotFoundError:
            return self._health_failure("codex_missing", started)
        except subprocess.TimeoutExpired:
            return self._health_failure("codex_timeout", started)
        except OSError:
            return self._health_failure("codex_failed", started)

        raw = mask_sensitive((completed.stdout or "") + (completed.stderr or "")).strip()
        if completed.returncode != 0:
            error_code = (
                "codex_login_required"
                if self._is_auth_failure(raw)
                else "codex_failed"
            )
            return {
                "name": "codex",
                "ok": False,
                "status": "failed",
                "error_code": error_code,
                "detail": f"Windows Codex version check exited with code {completed.returncode}.",
                "elapsed_ms": self._elapsed_ms(started),
            }
        return {
            "name": "codex",
            "ok": True,
            "status": "success",
            "error_code": None,
            "version": raw.splitlines()[0] if raw else None,
            "detail": "Windows Codex version check passed.",
            "elapsed_ms": self._elapsed_ms(started),
        }

    def run_task(
        self,
        task_name: str,
        prompt: str,
        workspace: Path,
        extra_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del extra_context
        started = time.perf_counter()
        resolved = resolve_windows_codex(self.settings.codex_command)
        if not resolved:
            error_code = (
                "codex_windows_required"
                if str(self.settings.codex_command).strip().lower().startswith("wsl:")
                else "codex_missing"
            )
            return self._task_failure(task_name, error_code, started)

        workspace.mkdir(parents=True, exist_ok=True)
        safe_task_name = _safe_task_name(task_name)
        log_path = workspace / "logs" / f"codex_{safe_task_name}.log"
        command = [resolved, *shlex.split(self.settings.codex_exec_args)]
        try:
            completed = subprocess.run(
                command,
                input=prompt,
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=self.settings.codex_diagnostic_timeout_s,
                shell=False,
                encoding="utf-8",
                errors="replace",
            )
        except PermissionError:
            return self._task_failure(task_name, "codex_access_denied", started)
        except FileNotFoundError:
            return self._task_failure(task_name, "codex_missing", started)
        except subprocess.TimeoutExpired:
            return self._task_failure(task_name, "codex_timeout", started)
        except OSError:
            return self._task_failure(task_name, "codex_failed", started)

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        self._write_log(log_path, stdout, stderr, completed.returncode)
        combined = f"{stdout}\n{stderr}"
        if self._is_auth_failure(combined):
            return self._task_failure(
                task_name,
                "codex_login_required",
                started,
                log_path=log_path,
            )
        if completed.returncode != 0:
            return self._task_failure(
                task_name,
                "codex_failed",
                started,
                log_path=log_path,
            )

        payload = _parse_json_object(stdout)
        if payload is None:
            return self._task_failure(
                task_name,
                "codex_invalid_result",
                started,
                log_path=log_path,
            )
        return {
            "status": "success",
            "task_name": task_name,
            "result": payload,
            "error_code": None,
            "error": None,
            "elapsed_ms": self._elapsed_ms(started),
            "log_file": log_path.relative_to(workspace).as_posix(),
        }

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)

    @staticmethod
    def _is_auth_failure(value: str) -> bool:
        lowered = value.lower()
        return any(marker in lowered for marker in _AUTH_FAILURE_MARKERS)

    def _health_failure(self, error_code: str, started: float) -> dict[str, Any]:
        return {
            "name": "codex",
            "ok": False,
            "status": "failed" if error_code != "codex_missing" else "missing",
            "error_code": error_code,
            "detail": "Windows Codex readiness check failed.",
            "elapsed_ms": self._elapsed_ms(started),
        }

    def _task_failure(
        self,
        task_name: str,
        error_code: str,
        started: float,
        *,
        log_path: Path | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": "failed",
            "task_name": task_name,
            "result": None,
            "error_code": error_code,
            "error": "Windows Codex task failed.",
            "elapsed_ms": self._elapsed_ms(started),
            "log_file": None,
        }
        if log_path is not None:
            result["log_file"] = log_path.parent.name + "/" + log_path.name
        return result

    @staticmethod
    def _write_log(log_path: Path, stdout: str, stderr: str, returncode: int) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        redacted = mask_sensitive(
            f"returncode={returncode}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
        )
        log_path.write_text(redacted, encoding="utf-8")


def make_windows_codex_adapter(settings: AppConfig | None = None) -> AgentAdapter:
    config = settings or get_settings()
    if config.codex_mode == "cli":
        return WindowsCodexAdapter(config)
    return MockCodexAdapter()
