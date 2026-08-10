from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.config import AppConfig
from backend.models.task import TaskRequest
from backend.services import task_runner
from backend.services.agent_adapters import AgentAdapter
from backend.services.planner_service import PlannerExecutionError


def valid_plan() -> dict[str, Any]:
    return {
        "task_understanding": "Plan a traceable report.",
        "outline": [
            {"section": "Context", "goal": "Define scope"},
            {"section": "Evidence", "goal": "Assess sources"},
            {"section": "Risk", "goal": "Identify uncertainty"},
        ],
        "search_questions": ["current technology", "competitive landscape", "technical risk"],
        "figures_needed": [],
        "risks": ["source lag"],
        "success_criteria": ["traceable evidence"],
        "language": "English",
    }


class WorkflowAdapter(AgentAdapter):
    def __init__(self, response: dict[str, Any], name: str):
        self.response = response
        self.name = name
        self.calls: list[str] = []

    def health_check(self) -> dict[str, Any]:
        return {"ok": True}

    def run_task(
        self,
        task_name: str,
        prompt: str,
        workspace: Path,
        extra_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(task_name)
        log_path = workspace / "logs" / f"{self.name}_{task_name}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("planner log", encoding="utf-8")
        return {**self.response, "log_file": str(log_path)}


def chatgpt_success() -> dict[str, Any]:
    return {
        "status": "success",
        "task_name": "planner",
        "result": {"result": valid_plan(), "parsed": True},
    }


def hermes_success() -> dict[str, Any]:
    return {"status": "success", "task_name": "planner", "result": valid_plan()}


def failed(code: str) -> dict[str, Any]:
    return {"status": "failed", "task_name": "planner", "error_code": code, "error": code}


def configure_storage(tmp_path: Path, monkeypatch, planner_mode: str) -> AppConfig:
    storage = tmp_path / "runtime"
    settings = AppConfig(
        planner_mode=planner_mode,
        chatgpt_mode="mock",
        output_dir=str(storage / "outputs"),
    )
    monkeypatch.setattr(task_runner, "STORAGE_DIR", storage)
    monkeypatch.setattr(task_runner, "JOB_ROOT", storage / "workspace" / "jobs")
    monkeypatch.setattr(task_runner, "get_settings", lambda: settings)
    return settings


def create_outline_task() -> Any:
    return task_runner.create_task(
        TaskRequest(
            title="Planner workflow",
            task_type="outline_only",
            enable_web_search=False,
            language="English",
        )
    )


def test_chatgpt_failure_falls_back_and_workflow_writes_trace(tmp_path, monkeypatch):
    configure_storage(tmp_path, monkeypatch, "chatgpt")
    chatgpt = WorkflowAdapter(failed("invalid_json"), "chatgpt")
    hermes = WorkflowAdapter(hermes_success(), "hermes")
    monkeypatch.setattr(task_runner, "make_chatgpt_adapter", lambda settings: chatgpt)
    monkeypatch.setattr(task_runner, "make_hermes_adapter", lambda settings: hermes)
    record = create_outline_task()

    completed = task_runner.run_workflow(record.task_id)

    workspace = task_runner.task_dir(record.task_id)
    trace = json.loads((workspace / "review" / "planner_trace.json").read_text(encoding="utf-8"))
    assert completed.status == "done"
    assert trace["fallback_used"] is True
    assert trace["selected_planner"] == "hermes"
    assert completed.steps[1].output["planner_trace"]["fallback_reason_code"] == "invalid_json"
    assert json.loads((workspace / "draft" / "outline.json").read_text(encoding="utf-8")) == valid_plan()


def test_valid_chatgpt_plan_skips_hermes_planning(tmp_path, monkeypatch):
    configure_storage(tmp_path, monkeypatch, "chatgpt")
    chatgpt = WorkflowAdapter(chatgpt_success(), "chatgpt")
    hermes = WorkflowAdapter(hermes_success(), "hermes")
    monkeypatch.setattr(task_runner, "make_chatgpt_adapter", lambda settings: chatgpt)
    monkeypatch.setattr(task_runner, "make_hermes_adapter", lambda settings: hermes)
    record = create_outline_task()

    completed = task_runner.run_workflow(record.task_id)

    assert completed.steps[1].output["planner_trace"]["selected_planner"] == "chatgpt"
    assert chatgpt.calls == ["planner"]
    assert hermes.calls == []


def test_hermes_mode_does_not_create_chatgpt_adapter(tmp_path, monkeypatch):
    configure_storage(tmp_path, monkeypatch, "hermes")
    hermes = WorkflowAdapter(hermes_success(), "hermes")
    monkeypatch.setattr(task_runner, "make_hermes_adapter", lambda settings: hermes)
    monkeypatch.setattr(
        task_runner,
        "make_chatgpt_adapter",
        lambda settings: (_ for _ in ()).throw(AssertionError("ChatGPT adapter must not be created")),
    )
    record = create_outline_task()

    completed = task_runner.run_workflow(record.task_id)

    assert completed.steps[1].output["planner_trace"]["selected_planner"] == "hermes"
    assert hermes.calls == ["planner"]


def test_both_planners_failing_marks_task_and_planning_step_failed(tmp_path, monkeypatch):
    configure_storage(tmp_path, monkeypatch, "chatgpt")
    monkeypatch.setattr(
        task_runner,
        "make_chatgpt_adapter",
        lambda settings: WorkflowAdapter(failed("reply_timeout"), "chatgpt"),
    )
    monkeypatch.setattr(
        task_runner,
        "make_hermes_adapter",
        lambda settings: WorkflowAdapter(failed("hermes_unavailable"), "hermes"),
    )
    record = create_outline_task()

    with pytest.raises(PlannerExecutionError):
        task_runner.run_workflow(record.task_id)

    failed_record = task_runner.load_record(record.task_id)
    assert failed_record.status == "failed"
    assert failed_record.steps[1].status == "failed"
    assert (task_runner.task_dir(record.task_id) / "review" / "planner_trace.json").exists()
