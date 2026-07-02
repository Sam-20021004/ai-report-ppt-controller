from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


TaskType = Literal["ppt", "word", "ppt_word", "research_only", "outline_only"]
AgentName = Literal["hermes", "codex", "auto"]
StepStatus = Literal["waiting", "running", "success", "failed", "needs_review", "paused", "cancelled", "done", "skipped"]


class TaskRequest(BaseModel):
    task_id: str = Field(default_factory=lambda: uuid4().hex)
    title: str
    task_type: TaskType = "ppt"
    domain: str = "AI"
    audience: str = "企业技术部门"
    language: str = "中文"
    ppt_topic: str | None = None
    ppt_pages: int | None = 10
    word_topic: str | None = None
    word_target_words: int | None = 6000
    search_boundary: str | None = None
    keywords: str | None = None
    region: str | None = None
    time_range: str | None = None
    database_scope: str | None = None
    user_outline: str | None = None
    ppt_template_path: str | None = None
    word_template_path: str | None = None
    output_dir: str = ""
    main_agent: AgentName = "auto"
    review_agent: AgentName = "auto"
    loop_rounds: int = 1
    enable_web_search: bool = True
    enable_patent_search: bool = False
    enable_paper_search: bool = False
    enable_industry_search: bool = True
    use_uploaded_material_only: bool = False
    enable_cross_review: bool = True
    enable_fact_check: bool = True
    enable_format_check: bool = True
    enable_professional_review: bool = True


class TaskStep(BaseModel):
    index: int
    step_name: str
    agent: str = "system"
    status: StepStatus = "waiting"
    started_at: str | None = None
    ended_at: str | None = None
    elapsed_ms: int | None = None
    input: Any = None
    output: Any = None
    output_summary: str = ""
    error: str = ""


class TaskRecord(BaseModel):
    task_id: str
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    status: StepStatus = "waiting"
    request: TaskRequest
    steps: list[TaskStep]
    workspace_dir: str = ""
    review_round: int = 0
    generated_files: list[dict] = Field(default_factory=list)
    final_quality_check: dict = Field(default_factory=dict)
    phase2_inputs: dict = Field(default_factory=dict)
    phase2_outputs_summary: dict = Field(default_factory=dict)
    phase2_errors: list[dict] = Field(default_factory=list)
    phase2_files: list[dict] = Field(default_factory=list)


WORKFLOW_STEPS = [
    ("CREATED", "orchestrator"),
    ("PLANNING", "hermes"),
    ("RESEARCHING", "chrome"),
    ("DRAFTING", "hermes"),
    ("BUILDING", "codex"),
    ("REVIEWING", "hermes"),
    ("REVISING", "codex"),
    ("FINALIZING", "orchestrator"),
    ("DONE", "orchestrator"),
]


def default_steps() -> list[TaskStep]:
    return [
        TaskStep(index=index + 1, step_name=name, agent=agent)
        for index, (name, agent) in enumerate(WORKFLOW_STEPS)
    ]
