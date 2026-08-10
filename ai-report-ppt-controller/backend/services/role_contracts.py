from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StringConstraints,
    ValidationError,
    model_validator,
)
from pydantic_core import PydanticCustomError


class RoleContractError(ValueError):
    def __init__(self, issues: list[dict[str, str]]) -> None:
        super().__init__("Role contract validation failed.")
        self.issues = issues


def _safe_relative_path(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    normalized = value.replace("\\", "/").strip()
    posix_path = PurePosixPath(normalized)
    windows_path = PureWindowsPath(value)
    if (
        not normalized
        or posix_path.is_absolute()
        or windows_path.is_absolute()
        or ".." in posix_path.parts
        or normalized in {".", "./"}
    ):
        raise PydanticCustomError(
            "artifact_path.unsafe",
            "Artifact path must be a safe workspace-relative path.",
        )
    return normalized


NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
SafeRelativePath = Annotated[
    NonEmptyText,
    BeforeValidator(_safe_relative_path),
]


class RoleTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: NonEmptyText
    instruction: NonEmptyText
    inputs: list[SafeRelativePath] = Field(default_factory=list)
    dependencies: list[NonEmptyText] = Field(default_factory=list)
    expected_outputs: list[SafeRelativePath] = Field(min_length=1)
    acceptance_criteria: list[NonEmptyText] = Field(min_length=1)


class RolePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["role.plan.v1"]
    objective: NonEmptyText
    tasks: list[RoleTask] = Field(min_length=1)
    final_outputs: list[SafeRelativePath] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_tasks(self) -> "RolePlan":
        task_ids = [task.task_id for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("tasks contain duplicate task_id values")

        known_ids = set(task_ids)
        for task in self.tasks:
            unknown = set(task.dependencies) - known_ids
            if unknown:
                raise ValueError(
                    f"tasks contain unknown dependencies for {task.task_id}: "
                    f"{', '.join(sorted(unknown))}"
                )
        return self


class HermesExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["role.execution.v1"]
    task_id: NonEmptyText
    status: Literal["success", "failed"]
    summary: str
    sources: list[dict[str, Any]] = Field(default_factory=list)
    artifact_paths: list[SafeRelativePath] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_success_summary(self) -> "HermesExecutionResult":
        if self.status == "success" and not self.summary.strip():
            raise ValueError("summary must be non-empty when status is success")
        return self


class CodexFinalizationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["role.finalization.v1"]
    status: Literal["success", "failed"]
    summary: str
    artifact_paths: list[SafeRelativePath] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_success(self) -> "CodexFinalizationResult":
        if self.status == "success" and not self.summary.strip():
            raise ValueError("summary must be non-empty when status is success")
        if self.status == "success" and not self.artifact_paths:
            raise ValueError("artifact_paths must be non-empty when status is success")
        return self


class ChatGPTReview(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=False)

    schema_version: Literal["role.review.v1"]
    score: StrictInt | StrictFloat = Field(ge=0, le=100)
    passed: StrictBool = Field(alias="pass")
    blocking_issues: list[dict[str, Any]] = Field(default_factory=list)
    minor_issues: list[dict[str, Any]] = Field(default_factory=list)
    revision_instruction: str = ""


class RoleAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: Literal["codex", "hermes", "chatgpt"]
    operation: NonEmptyText
    status: Literal["success", "failed", "mock", "fallback", "missing"]
    error_code: str | None = None
    elapsed_ms: int = Field(ge=0)
    artifact_paths: list[SafeRelativePath] = Field(default_factory=list)


class ArtifactManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: SafeRelativePath
    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    size: int = Field(ge=0)


class RoleBaselineTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["role.baseline.trace.v1"]
    run_id: NonEmptyText
    status: Literal["success", "failed"]
    error_code: str | None = None
    started_at: NonEmptyText
    completed_at: NonEmptyText
    attempts: list[RoleAttempt]
    artifacts: list[ArtifactManifestEntry]

    @model_validator(mode="after")
    def success_requires_real_attempts(self) -> "RoleBaselineTrace":
        if self.status == "success" and any(
            attempt.status != "success" for attempt in self.attempts
        ):
            raise ValueError("successful trace requires every attempt to be successful")
        if self.status == "success" and self.error_code is not None:
            raise ValueError("successful trace cannot contain an error_code")
        if self.status == "failed" and not self.error_code:
            raise ValueError("failed trace requires an error_code")
        return self


def _error_path(location: tuple[Any, ...]) -> str:
    return ".".join(str(part) for part in location if part != "__root__") or "contract"


def _stable_issue(error: dict[str, Any]) -> dict[str, str]:
    error_type = str(error.get("type", "invalid"))
    message = str(error.get("msg", "Invalid value."))
    location = tuple(error.get("loc", ()))
    path = _error_path(location)

    if error_type == "artifact_path.unsafe":
        code = error_type
    elif "tasks contain" in message:
        path = "tasks"
        code = "tasks.invalid"
    elif "summary must" in message:
        path = "summary"
        code = "summary.invalid"
    elif "artifact_paths must" in message:
        path = "artifact_paths"
        code = "artifact_paths.invalid"
    elif error_type == "missing":
        code = f"{path}.required"
    else:
        code = f"{path}.invalid"

    return {"path": path, "code": code, "message": message}


def _validate(model: type[BaseModel], payload: Any) -> dict[str, Any]:
    try:
        validated = model.model_validate(payload)
    except ValidationError as exc:
        raise RoleContractError([_stable_issue(error) for error in exc.errors()]) from exc
    return validated.model_dump(by_alias=True)


def validate_role_plan(payload: Any) -> dict[str, Any]:
    return _validate(RolePlan, payload)


def validate_hermes_execution(payload: Any) -> dict[str, Any]:
    return _validate(HermesExecutionResult, payload)


def validate_codex_finalization(payload: Any) -> dict[str, Any]:
    return _validate(CodexFinalizationResult, payload)


def validate_chatgpt_review(payload: Any) -> dict[str, Any]:
    return _validate(ChatGPTReview, payload)


def validate_role_baseline_trace(payload: Any) -> dict[str, Any]:
    return _validate(RoleBaselineTrace, payload)
