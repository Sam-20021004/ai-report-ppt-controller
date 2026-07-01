from __future__ import annotations

from backend.models.agent import AgentCheckResult
from backend.services.agent_adapters import make_codex_adapter


def check_codex() -> AgentCheckResult:
    result = make_codex_adapter().health_check()
    return AgentCheckResult(**result)
