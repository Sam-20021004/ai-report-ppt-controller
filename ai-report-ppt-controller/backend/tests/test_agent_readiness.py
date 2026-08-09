from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.agent_readiness import normalize_real_readiness


@pytest.mark.parametrize("status", ["mock", "fallback", "missing", "failed"])
def test_non_real_status_never_passes(status: str) -> None:
    result = normalize_real_readiness("hermes", {"ok": True, "status": status})

    assert result["ok"] is False
    assert result["status"] == status


def test_success_requires_ok_true() -> None:
    result = normalize_real_readiness(
        "chatgpt", {"ok": False, "status": "success"}
    )

    assert result["ok"] is False
    assert result["error_code"] == "chatgpt_not_ready"


def test_real_success_is_preserved() -> None:
    result = normalize_real_readiness(
        "hermes", {"ok": True, "status": "success", "version": "0.20.0"}
    )

    assert result["ok"] is True
    assert result["status"] == "success"
    assert result["version"] == "0.20.0"


@pytest.mark.parametrize(
    ("status", "error_code"),
    [
        ("cdp_unavailable", "chatgpt_cdp_unavailable"),
        ("login_required", "chatgpt_login_required"),
        ("page_changed", "chatgpt_page_changed"),
    ],
)
def test_chatgpt_readiness_preserves_actionable_failures(
    status: str, error_code: str
) -> None:
    result = normalize_real_readiness("chatgpt", {"ok": False, "status": status})

    assert result["error_code"] == error_code
