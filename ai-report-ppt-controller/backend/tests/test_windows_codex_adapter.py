from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.config import AppConfig
from backend.services import windows_codex_adapter
from backend.services.windows_codex_adapter import (
    WindowsCodexAdapter,
    resolve_windows_codex,
)


def cli_settings(**overrides) -> AppConfig:
    return AppConfig(codex_mode="cli", **overrides)


def test_windows_codex_rejects_wsl_prefix() -> None:
    assert resolve_windows_codex("wsl:/home/cincin/codex.sh") is None


def test_health_check_maps_permission_error(monkeypatch) -> None:
    monkeypatch.setattr(
        windows_codex_adapter,
        "resolve_command",
        lambda value: r"C:\Codex\codex.exe",
    )
    monkeypatch.setattr(
        windows_codex_adapter.subprocess,
        "run",
        Mock(side_effect=PermissionError("denied")),
    )

    result = WindowsCodexAdapter(cli_settings()).health_check()

    assert result["status"] == "failed"
    assert result["error_code"] == "codex_access_denied"


def test_health_check_rejects_wsl_command() -> None:
    result = WindowsCodexAdapter(
        cli_settings(codex_command="wsl:/home/cincin/codex.sh")
    ).health_check()

    assert result["status"] == "missing"
    assert result["error_code"] == "codex_windows_required"


def test_run_task_maps_login_failure(monkeypatch, tmp_path) -> None:
    completed = subprocess.CompletedProcess(
        ["codex", "exec"],
        1,
        "",
        "Not logged in. Run codex login.",
    )
    monkeypatch.setattr(windows_codex_adapter, "resolve_command", lambda value: "codex.exe")
    monkeypatch.setattr(
        windows_codex_adapter.subprocess,
        "run",
        lambda *args, **kwargs: completed,
    )

    result = WindowsCodexAdapter(cli_settings()).run_task(
        "role_planner", "prompt", tmp_path
    )

    assert result["status"] == "failed"
    assert result["error_code"] == "codex_login_required"


def test_run_task_parses_json_and_uses_shell_false(monkeypatch, tmp_path) -> None:
    captured = {}
    completed = subprocess.CompletedProcess(
        ["codex", "exec"],
        0,
        '{"schema_version":"role.plan.v1"}',
        "",
    )
    monkeypatch.setattr(windows_codex_adapter, "resolve_command", lambda value: "codex.exe")
    monkeypatch.setattr(
        windows_codex_adapter.subprocess,
        "run",
        lambda command, **kwargs: captured.update(command=command, kwargs=kwargs)
        or completed,
    )

    result = WindowsCodexAdapter(cli_settings()).run_task(
        "role_planner", "prompt", tmp_path
    )

    assert result["result"]["schema_version"] == "role.plan.v1"
    assert captured["kwargs"]["shell"] is False
    assert captured["kwargs"]["cwd"] == str(tmp_path)
    assert result["log_file"] == "logs/codex_role_planner.log"


def test_run_task_parses_fenced_json(monkeypatch, tmp_path) -> None:
    completed = subprocess.CompletedProcess(
        ["codex", "exec"],
        0,
        'Completed.\n```json\n{"status":"success"}\n```',
        "",
    )
    monkeypatch.setattr(windows_codex_adapter, "resolve_command", lambda value: "codex.exe")
    monkeypatch.setattr(
        windows_codex_adapter.subprocess,
        "run",
        lambda *args, **kwargs: completed,
    )

    result = WindowsCodexAdapter(cli_settings()).run_task("role_planner", "prompt", tmp_path)

    assert result["result"] == {"status": "success"}


def test_run_task_rejects_unparseable_success(monkeypatch, tmp_path) -> None:
    completed = subprocess.CompletedProcess(["codex", "exec"], 0, "done", "")
    monkeypatch.setattr(windows_codex_adapter, "resolve_command", lambda value: "codex.exe")
    monkeypatch.setattr(
        windows_codex_adapter.subprocess,
        "run",
        lambda *args, **kwargs: completed,
    )

    result = WindowsCodexAdapter(cli_settings()).run_task("role_planner", "prompt", tmp_path)

    assert result["status"] == "failed"
    assert result["error_code"] == "codex_invalid_result"
