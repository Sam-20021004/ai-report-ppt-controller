from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.config import get_settings
from backend.services.role_baseline_service import run_role_baseline


pytestmark = pytest.mark.skipif(
    os.getenv("ROLE_BASELINE_LIVE") != "1",
    reason="Set ROLE_BASELINE_LIVE=1 to run the real three-agent diagnostic.",
)


def test_real_three_agent_role_baseline(tmp_path) -> None:
    settings = get_settings()
    assert settings.codex_mode == "cli"
    assert not settings.codex_command.lower().startswith("wsl:")
    assert settings.hermes_mode == "api"
    assert settings.chatgpt_mode == "cdp"

    result = run_role_baseline(
        settings,
        tmp_path / "diagnostics",
        run_id="live-smoke",
    )

    assert result["status"] == "success", result
    assert all(
        result["agents"][name]["status"] == "success"
        for name in ("codex", "hermes", "chatgpt")
    )
    assert set(result["artifacts"]) == {
        "diagnostic_plan.json",
        "hermes_execution.json",
        "diagnostic_final.md",
        "role_baseline_trace.json",
    }
