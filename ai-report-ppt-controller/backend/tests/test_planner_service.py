from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from backend.services.agent_adapters import AgentAdapter
from backend.services.planner_service import PlannerExecutionError, run_planner


def valid_plan() -> dict[str, Any]:
    return {
        "task_understanding": "Assess the technology and evidence.",
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


class RecordingAdapter(AgentAdapter):
    def __init__(self, response: dict[str, Any], log_name: str):
        self.response = response
        self.log_name = log_name
        self.calls: list[dict[str, Any]] = []

    def health_check(self) -> dict[str, Any]:
        return {"ok": True}

    def run_task(
        self,
        task_name: str,
        prompt: str,
        workspace: Path,
        extra_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "task_name": task_name,
                "prompt": prompt,
                "workspace": workspace,
                "extra_context": extra_context,
            }
        )
        log_path = workspace / "logs" / self.log_name
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("adapter log", encoding="utf-8")
        return {**self.response, "log_file": str(log_path)}


def hermes_success(plan: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"status": "success", "task_name": "planner", "result": plan or valid_plan()}


def chatgpt_success(plan: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "status": "success",
        "task_name": "planner",
        "result": {"result": plan or valid_plan(), "parsed": True},
    }


def failed(error_code: str, error: str = "planner failed") -> dict[str, Any]:
    return {
        "status": "failed",
        "task_name": "planner",
        "error_code": error_code,
        "error": error,
        "elapsed_ms": 8,
    }


def run_with(
    tmp_path: Path,
    *,
    requested_mode: str,
    chatgpt: RecordingAdapter,
    hermes: RecordingAdapter,
):
    return run_planner(
        requested_mode=requested_mode,
        chatgpt=chatgpt,
        hermes=hermes,
        chatgpt_prompt="chatgpt prompt",
        hermes_prompt="hermes prompt",
        workspace=tmp_path,
        context={"request": {"title": "Test"}},
    )


def test_hermes_mode_never_calls_chatgpt(tmp_path):
    chatgpt = RecordingAdapter(chatgpt_success(), "chatgpt.log")
    hermes = RecordingAdapter(hermes_success(), "hermes.log")

    outcome = run_with(tmp_path, requested_mode="hermes", chatgpt=chatgpt, hermes=hermes)

    assert chatgpt.calls == []
    assert len(hermes.calls) == 1
    assert outcome.trace.selected_planner == "hermes"
    assert outcome.trace.fallback_used is False


def test_valid_chatgpt_plan_does_not_call_hermes(tmp_path):
    chatgpt = RecordingAdapter(chatgpt_success(), "chatgpt.log")
    hermes = RecordingAdapter(hermes_success(), "hermes.log")

    outcome = run_with(tmp_path, requested_mode="chatgpt", chatgpt=chatgpt, hermes=hermes)

    assert len(chatgpt.calls) == 1
    assert hermes.calls == []
    assert outcome.trace.selected_planner == "chatgpt"
    assert outcome.trace.fallback_used is False


@pytest.mark.parametrize(
    ("chatgpt_response", "reason_code"),
    [
        (failed("reply_timeout"), "reply_timeout"),
        (chatgpt_success({"outline": []}), "invalid_plan"),
    ],
)
def test_chatgpt_failure_falls_back_and_records_trace(tmp_path, chatgpt_response, reason_code):
    chatgpt = RecordingAdapter(chatgpt_response, "chatgpt.log")
    hermes = RecordingAdapter(hermes_success(), "hermes.log")

    outcome = run_with(tmp_path, requested_mode="chatgpt", chatgpt=chatgpt, hermes=hermes)

    assert len(chatgpt.calls) == 1
    assert len(hermes.calls) == 1
    assert outcome.trace.fallback_used is True
    assert outcome.trace.selected_planner == "hermes"
    assert outcome.trace.fallback_reason_code == reason_code
    assert [attempt.log_file for attempt in outcome.trace.attempts] == [
        "logs/chatgpt.log",
        "logs/hermes.log",
    ]

    trace_path = tmp_path / "review" / "planner_trace.json"
    persisted = json.loads(trace_path.read_text(encoding="utf-8"))
    assert persisted["fallback_reason_code"] == reason_code
    expected_sha = hashlib.sha256(
        json.dumps(outcome.plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert persisted["plan_sha256"] == expected_sha
    assert list(trace_path.parent.glob("*.tmp")) == []


def test_both_planners_failing_raises_with_two_attempts_and_persists_trace(tmp_path):
    chatgpt = RecordingAdapter(failed("reply_timeout"), "chatgpt.log")
    hermes = RecordingAdapter(failed("hermes_unavailable"), "hermes.log")

    with pytest.raises(PlannerExecutionError) as exc_info:
        run_with(tmp_path, requested_mode="chatgpt", chatgpt=chatgpt, hermes=hermes)

    trace = exc_info.value.trace
    assert trace.selected_planner is None
    assert trace.plan_sha256 is None
    assert [attempt.planner for attempt in trace.attempts] == ["chatgpt", "hermes"]
    persisted = json.loads((tmp_path / "review" / "planner_trace.json").read_text(encoding="utf-8"))
    assert persisted["selected_planner"] is None


def test_invalid_hermes_fallback_raises_instead_of_returning_empty_plan(tmp_path):
    chatgpt = RecordingAdapter(failed("invalid_json"), "chatgpt.log")
    hermes = RecordingAdapter(hermes_success({"outline": []}), "hermes.log")

    with pytest.raises(PlannerExecutionError) as exc_info:
        run_with(tmp_path, requested_mode="chatgpt", chatgpt=chatgpt, hermes=hermes)

    assert exc_info.value.trace.attempts[-1].error_code == "invalid_plan"
