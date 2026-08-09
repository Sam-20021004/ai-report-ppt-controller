from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator, model_validator


NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
PlannerName = Literal["chatgpt", "hermes"]


class PlanSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    section: NonEmptyText
    goal: NonEmptyText


class PlannerPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    task_understanding: NonEmptyText
    outline: list[PlanSection] = Field(min_length=3, max_length=6)
    search_questions: list[NonEmptyText] = Field(min_length=3)
    figures_needed: list[NonEmptyText]
    risks: list[NonEmptyText]
    success_criteria: list[NonEmptyText] = Field(min_length=1)
    language: NonEmptyText


class PlannerContractError(ValueError):
    def __init__(self, issues: list[dict[str, str]]):
        self.issues = issues
        super().__init__("Planner result failed contract validation.")


class PlannerAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planner: PlannerName
    status: Literal["success", "failed"]
    error_code: str | None = None
    error: str | None = None
    elapsed_ms: int = Field(default=0, ge=0)
    log_file: str | None = None
    started_at: str | None = None
    completed_at: str | None = None

    @field_validator("log_file")
    @classmethod
    def validate_log_file(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        normalized = value.replace("\\", "/")
        posix_path = PurePosixPath(normalized)
        if posix_path.is_absolute() or PureWindowsPath(value).is_absolute() or ".." in posix_path.parts:
            raise ValueError("Planner log path must be relative to the task workspace.")
        return posix_path.as_posix()


class PlannerTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "planner.trace.v1"
    requested_mode: Literal["chatgpt", "hermes"]
    primary_planner: PlannerName
    selected_planner: PlannerName | None
    fallback_used: bool
    fallback_reason_code: str | None = None
    fallback_reason: str | None = None
    attempts: list[PlannerAttempt] = Field(min_length=1, max_length=2)
    started_at: str | None = None
    completed_at: str | None = None
    plan_sha256: str | None

    @field_validator("plan_sha256")
    @classmethod
    def validate_sha256(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.lower()
        if re.fullmatch(r"[0-9a-f]{64}", normalized) is None:
            raise ValueError("plan_sha256 must be a 64-character hexadecimal SHA-256 value.")
        return normalized

    @model_validator(mode="after")
    def validate_fallback_state(self) -> "PlannerTrace":
        if self.selected_planner is None:
            if self.plan_sha256 is not None:
                raise ValueError("plan_sha256 must be empty when no planner succeeded.")
            expected_fallback = self.requested_mode == "chatgpt" and any(
                attempt.planner == "hermes" for attempt in self.attempts
            )
        else:
            if self.plan_sha256 is None:
                raise ValueError("plan_sha256 is required when a planner succeeded.")
            expected_fallback = self.requested_mode == "chatgpt" and self.selected_planner == "hermes"
        if self.fallback_used != expected_fallback:
            raise ValueError("fallback_used does not match the requested and selected planners.")
        if self.fallback_used and not self.fallback_reason_code:
            raise ValueError("fallback_reason_code is required when fallback is used.")
        return self


class PlannerOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: dict[str, Any]
    trace: PlannerTrace


def validate_plan(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PlannerContractError(
            [
                {
                    "path": "$",
                    "code": "plan.type_error",
                    "message": "Plan must be a JSON object.",
                }
            ]
        )
    try:
        return PlannerPlan.model_validate(payload).model_dump()
    except ValidationError as exc:
        issues = [_validation_issue(error) for error in exc.errors()]
        issues.sort(key=lambda item: (item["path"], item["code"]))
        raise PlannerContractError(issues) from exc


def _validation_issue(error: dict[str, Any]) -> dict[str, str]:
    location = tuple(str(part) for part in error.get("loc", ()))
    path = ".".join(location) or "$"
    error_type = str(error.get("type", "validation_error"))

    list_codes = {
        ("outline", "too_short"): "outline.too_short",
        ("outline", "too_long"): "outline.too_long",
        ("search_questions", "too_short"): "search_questions.too_short",
        ("success_criteria", "too_short"): "success_criteria.too_short",
    }
    code = list_codes.get((path, error_type))
    if code is None and error_type in {"missing", "string_too_short"}:
        code = f"{path}.required"
    if code is None:
        code = f"{path}.type_error"

    return {
        "path": path,
        "code": code,
        "message": str(error.get("msg", "Invalid value.")),
    }
