from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend import dev_server
from backend.app import create_app
from backend.config import AppConfig
from backend.routers import role_baseline
from backend.services.security import require_api_token


def baseline_result() -> dict:
    return {
        "run_id": "run-001",
        "status": "success",
        "error_code": None,
        "agents": {},
        "artifacts": [],
        "trace_file": "diagnostics/run-001/role_baseline_trace.json",
    }


def test_fastapi_role_baseline_endpoint_calls_service(monkeypatch, tmp_path) -> None:
    calls = []
    monkeypatch.setattr(role_baseline, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(
        role_baseline,
        "run_role_baseline",
        lambda *args, **kwargs: calls.append((args, kwargs)) or baseline_result(),
    )
    app = create_app()
    app.dependency_overrides[require_api_token] = lambda: None

    response = TestClient(app).post("/api/check/role-baseline", json={})

    assert response.status_code == 200
    assert response.json()["run_id"] == "run-001"
    assert calls[0][1] == {}


def test_dev_server_role_baseline_endpoint_calls_service(monkeypatch, tmp_path) -> None:
    captured = {}
    monkeypatch.setattr(dev_server, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(dev_server, "load_config", lambda: AppConfig().model_dump())
    monkeypatch.setattr(
        dev_server,
        "run_role_baseline",
        lambda *args, **kwargs: baseline_result(),
    )
    monkeypatch.setattr(
        dev_server,
        "json_response",
        lambda handler, status, payload: captured.update(status=status, payload=payload),
    )

    dev_server.Handler.route_post(SimpleNamespace(path="/api/check/role-baseline"))

    assert captured["status"] == 200
    assert captured["payload"]["run_id"] == "run-001"


def test_dev_server_config_accepts_three_agent_profile() -> None:
    assert dev_server.validate_config_patch({"workflow_profile": "three_agent_v2"}) == {
        "workflow_profile": "three_agent_v2"
    }


@pytest.mark.parametrize("value", ["", "agents", "v3"])
def test_dev_server_config_rejects_unknown_profile(value: str) -> None:
    with pytest.raises(ValueError):
        dev_server.validate_config_patch({"workflow_profile": value})


@pytest.mark.parametrize("value", [30, 300, 900])
def test_codex_diagnostic_timeout_accepts_bounds(value: int) -> None:
    assert AppConfig(codex_diagnostic_timeout_s=value).codex_diagnostic_timeout_s == value
    assert dev_server.validate_config_patch({"codex_diagnostic_timeout_s": value}) == {
        "codex_diagnostic_timeout_s": value
    }


@pytest.mark.parametrize("value", [29, 901, "300", True])
def test_codex_diagnostic_timeout_rejects_invalid_values(value) -> None:
    with pytest.raises((ValidationError, ValueError)):
        AppConfig(codex_diagnostic_timeout_s=value)
    with pytest.raises(ValueError):
        dev_server.validate_config_patch({"codex_diagnostic_timeout_s": value})


def test_fastapi_and_dev_server_defaults_match() -> None:
    settings = AppConfig()

    assert dev_server.DEFAULT_CONFIG["workflow_profile"] == settings.workflow_profile
    assert (
        dev_server.DEFAULT_CONFIG["codex_diagnostic_timeout_s"]
        == settings.codex_diagnostic_timeout_s
    )
