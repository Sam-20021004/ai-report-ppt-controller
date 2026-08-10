from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.config import AppConfig
from backend.services.role_baseline_service import (
    CODEX_FINAL_PROMPT,
    CODEX_PLAN_PROMPT,
    HERMES_EXECUTION_PROMPT,
    run_role_baseline,
)


def plan_payload() -> dict[str, Any]:
    return {
        "schema_version": "role.plan.v1",
        "objective": "Validate the handoff",
        "tasks": [
            {
                "task_id": "task-001",
                "instruction": "Summarize the diagnostic source",
                "inputs": ["input/diagnostic_source.md"],
                "dependencies": [],
                "expected_outputs": ["hermes_execution.json"],
                "acceptance_criteria": ["Return a non-empty summary"],
            }
        ],
        "final_outputs": ["diagnostic_final.md"],
    }


def execution_payload() -> dict[str, Any]:
    return {
        "schema_version": "role.execution.v1",
        "task_id": "task-001",
        "status": "success",
        "summary": "Silicon has atomic number 14.",
        "sources": [],
        "artifact_paths": ["hermes_execution.json"],
        "errors": [],
    }


def finalization_payload() -> dict[str, Any]:
    return {
        "schema_version": "role.finalization.v1",
        "status": "success",
        "summary": "Diagnostic finalization complete.",
        "artifact_paths": ["diagnostic_final.md"],
        "errors": [],
    }


class WritingAdapter:
    def __init__(
        self,
        name: str,
        *,
        health_status: str = "success",
        fail_tasks: set[str] | None = None,
        skip_write_tasks: set[str] | None = None,
        mismatch_tasks: set[str] | None = None,
    ) -> None:
        self.name = name
        self.health_status = health_status
        self.fail_tasks = fail_tasks or set()
        self.skip_write_tasks = skip_write_tasks or set()
        self.mismatch_tasks = mismatch_tasks or set()
        self.calls: list[tuple[str, str, Path, dict[str, Any]]] = []
        self.health_calls = 0

    def health_check(self) -> dict[str, Any]:
        self.health_calls += 1
        return {
            "name": self.name,
            "ok": self.health_status in {"success", "mock"},
            "status": self.health_status,
            "elapsed_ms": 1,
        }

    def run_task(
        self,
        task_name: str,
        prompt: str,
        workspace: Path,
        extra_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append((task_name, prompt, workspace, extra_context or {}))
        if task_name in self.fail_tasks:
            return {
                "status": "failed",
                "task_name": task_name,
                "error_code": f"{self.name}_failed",
                "elapsed_ms": 2,
            }

        if task_name == "role_planner":
            payload = plan_payload()
            if task_name not in self.skip_write_tasks:
                file_payload = (
                    {**payload, "objective": "mismatched"}
                    if task_name in self.mismatch_tasks
                    else payload
                )
                (workspace / "diagnostic_plan.json").write_text(
                    json.dumps(file_payload), encoding="utf-8"
                )
        elif task_name == "role_executor":
            payload = execution_payload()
            if task_name not in self.skip_write_tasks:
                file_payload = (
                    {**payload, "summary": "mismatched"}
                    if task_name in self.mismatch_tasks
                    else payload
                )
                (workspace / "hermes_execution.json").write_text(
                    json.dumps(file_payload), encoding="utf-8"
                )
        elif task_name == "role_finalizer":
            payload = finalization_payload()
            if task_name not in self.skip_write_tasks:
                (workspace / "diagnostic_final.md").write_text(
                    "# Diagnostic final\n\nSilicon has atomic number 14.\n",
                    encoding="utf-8",
                )
        else:
            raise AssertionError(f"Unexpected task: {task_name}")

        return {
            "status": "success",
            "task_name": task_name,
            "result": payload,
            "error_code": None,
            "elapsed_ms": 2,
        }


class ReadinessOnlyAdapter(WritingAdapter):
    def __init__(self, health_status: str = "success") -> None:
        super().__init__("chatgpt", health_status=health_status)
        self.run_calls = 0

    def run_task(self, *args, **kwargs):
        self.run_calls += 1
        raise AssertionError("The baseline must not send a ChatGPT message.")


def configured_settings() -> AppConfig:
    return AppConfig(
        codex_mode="cli",
        hermes_mode="api",
        hermes_endpoint="http://127.0.0.1:7788",
        chatgpt_mode="cdp",
    )


def run_case(tmp_path, *, codex=None, hermes=None, chatgpt=None):
    codex = codex or WritingAdapter("codex")
    hermes = hermes or WritingAdapter("hermes")
    chatgpt = chatgpt or ReadinessOnlyAdapter()
    result = run_role_baseline(
        configured_settings(),
        tmp_path / "diagnostics",
        codex=codex,
        hermes=hermes,
        chatgpt=chatgpt,
        run_id="run-001",
    )
    return result, codex, hermes, chatgpt


def test_successful_baseline_uses_fixed_role_order_and_artifacts(tmp_path) -> None:
    result, codex, hermes, chatgpt = run_case(tmp_path)

    assert [call[0] for call in codex.calls] == ["role_planner", "role_finalizer"]
    assert [call[0] for call in hermes.calls] == ["role_executor"]
    assert chatgpt.health_calls == 1
    assert chatgpt.run_calls == 0
    assert result["status"] == "success"
    assert result["artifacts"] == [
        "diagnostic_plan.json",
        "hermes_execution.json",
        "diagnostic_final.md",
        "role_baseline_trace.json",
    ]
    assert result["trace_file"] == "diagnostics/run-001/role_baseline_trace.json"
    trace = json.loads(
        (tmp_path / "diagnostics" / "run-001" / "role_baseline_trace.json").read_text(
            encoding="utf-8"
        )
    )
    assert trace["status"] == "success"
    assert all("sha256" in artifact for artifact in trace["artifacts"])


@pytest.mark.parametrize(
    ("failed_stage", "expected_code"),
    [
        ("chatgpt", "chatgpt_not_ready"),
        ("codex_planner", "codex_failed"),
        ("hermes", "hermes_failed"),
        ("codex_finalizer", "codex_failed"),
    ],
)
def test_baseline_stops_at_first_failure(
    tmp_path, failed_stage: str, expected_code: str
) -> None:
    codex_failures = {
        "role_planner" if failed_stage == "codex_planner" else "",
        "role_finalizer" if failed_stage == "codex_finalizer" else "",
    } - {""}
    hermes_failures = {"role_executor"} if failed_stage == "hermes" else set()
    result, codex, hermes, _ = run_case(
        tmp_path,
        codex=WritingAdapter("codex", fail_tasks=codex_failures),
        hermes=WritingAdapter("hermes", fail_tasks=hermes_failures),
        chatgpt=ReadinessOnlyAdapter(
            health_status="failed" if failed_stage == "chatgpt" else "success"
        ),
    )

    assert result["status"] == "failed"
    assert result["error_code"] == expected_code
    assert (tmp_path / "diagnostics/run-001/role_baseline_trace.json").exists()
    if failed_stage in {"chatgpt", "codex_planner"}:
        assert hermes.calls == []
    if failed_stage in {"chatgpt", "codex_planner", "hermes"}:
        assert all(call[0] != "role_finalizer" for call in codex.calls)


def test_mock_readiness_cannot_pass(tmp_path) -> None:
    result, codex, hermes, _ = run_case(
        tmp_path, chatgpt=ReadinessOnlyAdapter(health_status="mock")
    )

    assert result["status"] == "failed"
    assert result["agents"]["chatgpt"]["ok"] is False
    assert codex.calls == []
    assert hermes.calls == []


def test_unchanged_artifact_fails_closed(tmp_path) -> None:
    result, _, hermes, _ = run_case(
        tmp_path,
        codex=WritingAdapter("codex", skip_write_tasks={"role_planner"}),
    )

    assert result["status"] == "failed"
    assert result["error_code"] == "artifact_not_changed"
    assert hermes.calls == []


def test_structured_and_file_payloads_must_match(tmp_path) -> None:
    result, _, hermes, _ = run_case(
        tmp_path,
        codex=WritingAdapter("codex", mismatch_tasks={"role_planner"}),
    )

    assert result["status"] == "failed"
    assert result["error_code"] == "artifact_result_mismatch"
    assert hermes.calls == []


def test_trace_does_not_persist_prompts_or_absolute_workspace(tmp_path) -> None:
    result, _, _, _ = run_case(tmp_path)
    trace_text = (
        tmp_path / "diagnostics/run-001/role_baseline_trace.json"
    ).read_text(encoding="utf-8")

    assert result["status"] == "success"
    assert "Create role.plan.v1" not in trace_text
    assert str(tmp_path) not in trace_text


def test_diagnostic_prompts_define_exact_strict_contracts() -> None:
    assert '"schema_version": "role.plan.v1"' in CODEX_PLAN_PROMPT
    assert '"expected_outputs": ["hermes_execution.json"]' in CODEX_PLAN_PROMPT
    assert '"status": "success"' in HERMES_EXECUTION_PROMPT
    assert '"artifact_paths": ["hermes_execution.json"]' in HERMES_EXECUTION_PROMPT
    assert '"errors": []' in HERMES_EXECUTION_PROMPT
    assert '"schema_version": "role.finalization.v1"' in CODEX_FINAL_PROMPT
    assert '"artifact_paths": ["diagnostic_final.md"]' in CODEX_FINAL_PROMPT
