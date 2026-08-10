from __future__ import annotations

from pathlib import Path

import pytest

from backend.services.planner_contracts import (
    PlannerAttempt,
    PlannerContractError,
    PlannerTrace,
    validate_plan,
)


def valid_plan() -> dict:
    return {
        "task_understanding": "  Assess the technology and evidence.  ",
        "outline": [
            {"section": " Context ", "goal": " Define scope "},
            {"section": "Evidence", "goal": "Assess sources"},
            {"section": "Risk", "goal": "Identify uncertainty"},
        ],
        "search_questions": [
            " current technology ",
            "competitive landscape",
            "technical risk",
        ],
        "figures_needed": [],
        "risks": [" source lag "],
        "success_criteria": [" traceable evidence "],
        "language": " English ",
        "ignored": "drop me",
    }


def test_validate_plan_normalizes_strings_and_drops_unknown_fields():
    result = validate_plan(valid_plan())

    assert result["task_understanding"] == "Assess the technology and evidence."
    assert result["outline"][0] == {"section": "Context", "goal": "Define scope"}
    assert result["search_questions"][0] == "current technology"
    assert result["risks"] == ["source lag"]
    assert result["success_criteria"] == ["traceable evidence"]
    assert result["language"] == "English"
    assert "ignored" not in result


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (lambda payload: payload.update(outline=payload["outline"][:2]), "outline.too_short"),
        (
            lambda payload: payload.update(
                outline=payload["outline"]
                + [
                    {"section": "Four", "goal": "Four"},
                    {"section": "Five", "goal": "Five"},
                    {"section": "Six", "goal": "Six"},
                    {"section": "Seven", "goal": "Seven"},
                ]
            ),
            "outline.too_long",
        ),
        (lambda payload: payload.update(search_questions=["one", "two"]), "search_questions.too_short"),
        (lambda payload: payload.update(success_criteria=[]), "success_criteria.too_short"),
        (lambda payload: payload["outline"][0].update(goal="  "), "outline.0.goal.required"),
    ],
)
def test_validate_plan_reports_stable_issue_codes(mutate, expected_code):
    payload = valid_plan()
    mutate(payload)

    with pytest.raises(PlannerContractError) as exc_info:
        validate_plan(payload)

    assert expected_code in {issue["code"] for issue in exc_info.value.issues}


def test_validate_plan_rejects_non_object_payload():
    with pytest.raises(PlannerContractError) as exc_info:
        validate_plan(["not", "an", "object"])

    assert exc_info.value.issues == [
        {
            "path": "$",
            "code": "plan.type_error",
            "message": "Plan must be a JSON object.",
        }
    ]


def test_planner_attempt_accepts_relative_log_path():
    attempt = PlannerAttempt(
        planner="chatgpt",
        status="success",
        elapsed_ms=12,
        log_file="logs/chatgpt_planner.log",
    )

    assert attempt.log_file == "logs/chatgpt_planner.log"


@pytest.mark.parametrize("path", [str(Path.cwd()), "../outside.log", "logs/../../outside.log"])
def test_planner_attempt_rejects_unsafe_log_paths(path):
    with pytest.raises(ValueError):
        PlannerAttempt(
            planner="chatgpt",
            status="success",
            elapsed_ms=1,
            log_file=path,
        )


def test_planner_trace_requires_sha256_and_consistent_fallback():
    with pytest.raises(ValueError):
        PlannerTrace(
            requested_mode="chatgpt",
            primary_planner="chatgpt",
            selected_planner="hermes",
            fallback_used=False,
            attempts=[
                PlannerAttempt(
                    planner="chatgpt",
                    status="failed",
                    error_code="reply_timeout",
                    elapsed_ms=1,
                )
            ],
            plan_sha256="not-a-sha",
        )
