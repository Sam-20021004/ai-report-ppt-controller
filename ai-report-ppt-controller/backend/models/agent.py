from __future__ import annotations

from pydantic import BaseModel, Field


class AgentCheckResult(BaseModel):
    name: str
    ok: bool
    status: str
    command: str | None = None
    version: str | None = None
    detail: str = ""
    raw_output: str = ""
    elapsed_ms: int | None = None
    metadata: dict = Field(default_factory=dict)
