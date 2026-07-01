from __future__ import annotations

from backend.models.agent import AgentCheckResult
from backend.services.agent_adapters import make_hermes_adapter


def check_hermes() -> AgentCheckResult:
    result = make_hermes_adapter().health_check()
    return AgentCheckResult(**result)
