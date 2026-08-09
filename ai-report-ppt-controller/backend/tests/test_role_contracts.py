from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.role_contracts import (
    RoleContractError,
    validate_chatgpt_review,
    validate_codex_finalization,
    validate_hermes_execution,
    validate_role_baseline_trace,
    validate_role_plan,
)


def valid_plan() -> dict:
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


def test_role_plan_accepts_the_documented_contract() -> None:
    result = validate_role_plan(valid_plan())

    assert result["tasks"][0]["task_id"] == "task-001"


@pytest.mark.parametrize("path", ["../escape.json", r"C:\outside.json", "/tmp/outside.json"])
def test_role_plan_rejects_unsafe_artifact_paths(path: str) -> None:
    payload = valid_plan()
    payload["tasks"][0]["expected_outputs"] = [path]

    with pytest.raises(RoleContractError) as exc_info:
        validate_role_plan(payload)

    assert any(issue["code"] == "artifact_path.unsafe" for issue in exc_info.value.issues)


def test_role_plan_rejects_duplicate_task_ids() -> None:
    payload = valid_plan()
    payload["tasks"].append(dict(payload["tasks"][0]))

    with pytest.raises(RoleContractError) as exc_info:
        validate_role_plan(payload)

    assert any(issue["code"] == "tasks.invalid" for issue in exc_info.value.issues)


def test_role_plan_rejects_unknown_dependency() -> None:
    payload = valid_plan()
    payload["tasks"][0]["dependencies"] = ["task-404"]

    with pytest.raises(RoleContractError) as exc_info:
        validate_role_plan(payload)

    assert any(issue["code"] == "tasks.invalid" for issue in exc_info.value.issues)


def test_hermes_success_requires_summary() -> None:
    with pytest.raises(RoleContractError) as exc_info:
        validate_hermes_execution(
            {
                "schema_version": "role.execution.v1",
                "task_id": "task-001",
                "status": "success",
                "summary": "",
                "sources": [],
                "artifact_paths": ["hermes_execution.json"],
                "errors": [],
            }
        )

    assert any(issue["code"] == "summary.invalid" for issue in exc_info.value.issues)


def test_codex_finalization_accepts_markdown_artifact() -> None:
    result = validate_codex_finalization(
        {
            "schema_version": "role.finalization.v1",
            "status": "success",
            "summary": "Diagnostic finalization complete.",
            "artifact_paths": ["diagnostic_final.md"],
            "errors": [],
        }
    )

    assert result["artifact_paths"] == ["diagnostic_final.md"]


def test_chatgpt_review_requires_numeric_score_and_boolean_pass() -> None:
    with pytest.raises(RoleContractError):
        validate_chatgpt_review(
            {
                "schema_version": "role.review.v1",
                "score": "85",
                "pass": "yes",
                "blocking_issues": [],
                "minor_issues": [],
                "revision_instruction": "",
            }
        )


def test_chatgpt_review_preserves_pass_alias() -> None:
    result = validate_chatgpt_review(
        {
            "schema_version": "role.review.v1",
            "score": 90,
            "pass": True,
            "blocking_issues": [],
            "minor_issues": [],
            "revision_instruction": "No revision required.",
        }
    )

    assert result["pass"] is True
    assert "passed" not in result


def test_success_trace_rejects_non_real_attempt() -> None:
    with pytest.raises(RoleContractError):
        validate_role_baseline_trace(
            {
                "schema_version": "role.baseline.trace.v1",
                "run_id": "run-001",
                "status": "success",
                "error_code": None,
                "started_at": "2026-08-10T10:00:00+00:00",
                "completed_at": "2026-08-10T10:00:01+00:00",
                "attempts": [
                    {
                        "agent": "codex",
                        "operation": "readiness",
                        "status": "mock",
                        "error_code": None,
                        "elapsed_ms": 1,
                        "artifact_paths": [],
                    }
                ],
                "artifacts": [],
            }
        )
