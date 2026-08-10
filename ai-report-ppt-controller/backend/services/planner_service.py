from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from backend.services.agent_adapters import AgentAdapter
from backend.services.planner_contracts import (
    PlannerAttempt,
    PlannerContractError,
    PlannerOutcome,
    PlannerTrace,
    validate_plan,
)
from backend.services.security import mask_sensitive


PlannerMode = Literal["chatgpt", "hermes"]


class PlannerExecutionError(RuntimeError):
    def __init__(self, trace: PlannerTrace):
        self.trace = trace
        super().__init__("No planner returned a valid plan.")


def run_planner(
    *,
    requested_mode: PlannerMode,
    chatgpt: AgentAdapter,
    hermes: AgentAdapter,
    chatgpt_prompt: str,
    hermes_prompt: str,
    workspace: Path,
    context: dict[str, Any],
) -> PlannerOutcome:
    started_at = _now()
    attempts: list[PlannerAttempt] = []
    fallback_reason_code: str | None = None
    fallback_reason: str | None = None

    if requested_mode == "chatgpt":
        plan, attempt = _run_attempt(
            planner="chatgpt",
            adapter=chatgpt,
            prompt=chatgpt_prompt,
            workspace=workspace,
            context=context,
        )
        attempts.append(attempt)
        if plan is not None:
            return _successful_outcome(
                requested_mode=requested_mode,
                selected_planner="chatgpt",
                plan=plan,
                attempts=attempts,
                started_at=started_at,
                workspace=workspace,
            )
        fallback_reason_code = attempt.error_code or "chatgpt_failed"
        fallback_reason = attempt.error or "ChatGPT planner failed."

    plan, hermes_attempt = _run_attempt(
        planner="hermes",
        adapter=hermes,
        prompt=hermes_prompt,
        workspace=workspace,
        context=context,
    )
    attempts.append(hermes_attempt)
    if plan is not None:
        return _successful_outcome(
            requested_mode=requested_mode,
            selected_planner="hermes",
            plan=plan,
            attempts=attempts,
            started_at=started_at,
            workspace=workspace,
            fallback_reason_code=fallback_reason_code,
            fallback_reason=fallback_reason,
        )

    fallback_used = requested_mode == "chatgpt"
    trace = PlannerTrace(
        requested_mode=requested_mode,
        primary_planner=requested_mode,
        selected_planner=None,
        fallback_used=fallback_used,
        fallback_reason_code=fallback_reason_code if fallback_used else None,
        fallback_reason=fallback_reason if fallback_used else None,
        attempts=attempts,
        started_at=started_at,
        completed_at=_now(),
        plan_sha256=None,
    )
    _write_trace(workspace, trace)
    raise PlannerExecutionError(trace)


def _run_attempt(
    *,
    planner: Literal["chatgpt", "hermes"],
    adapter: AgentAdapter,
    prompt: str,
    workspace: Path,
    context: dict[str, Any],
) -> tuple[dict[str, Any] | None, PlannerAttempt]:
    started_at = _now()
    started = perf_counter()
    try:
        response = adapter.run_task("planner", prompt, workspace, context)
    except Exception as exc:
        return None, PlannerAttempt(
            planner=planner,
            status="failed",
            error_code="adapter_exception",
            error=_safe_error(str(exc), workspace),
            elapsed_ms=_elapsed_ms(started),
            started_at=started_at,
            completed_at=_now(),
        )

    log_file = _relative_log_file(response, workspace)
    if response.get("status") != "success":
        return None, PlannerAttempt(
            planner=planner,
            status="failed",
            error_code=str(response.get("error_code") or f"{planner}_failed"),
            error=_safe_error(str(response.get("error") or f"{planner} planner failed."), workspace),
            elapsed_ms=_elapsed_ms(started),
            log_file=log_file,
            started_at=started_at,
            completed_at=_now(),
        )

    try:
        plan = validate_plan(_adapter_payload(response))
    except PlannerContractError as exc:
        return None, PlannerAttempt(
            planner=planner,
            status="failed",
            error_code="invalid_plan",
            error=json.dumps(exc.issues, ensure_ascii=False, separators=(",", ":"))[:500],
            elapsed_ms=_elapsed_ms(started),
            log_file=log_file,
            started_at=started_at,
            completed_at=_now(),
        )

    return plan, PlannerAttempt(
        planner=planner,
        status="success",
        elapsed_ms=_elapsed_ms(started),
        log_file=log_file,
        started_at=started_at,
        completed_at=_now(),
    )


def _successful_outcome(
    *,
    requested_mode: PlannerMode,
    selected_planner: Literal["chatgpt", "hermes"],
    plan: dict[str, Any],
    attempts: list[PlannerAttempt],
    started_at: str,
    workspace: Path,
    fallback_reason_code: str | None = None,
    fallback_reason: str | None = None,
) -> PlannerOutcome:
    fallback_used = requested_mode == "chatgpt" and selected_planner == "hermes"
    trace = PlannerTrace(
        requested_mode=requested_mode,
        primary_planner=requested_mode,
        selected_planner=selected_planner,
        fallback_used=fallback_used,
        fallback_reason_code=fallback_reason_code if fallback_used else None,
        fallback_reason=fallback_reason if fallback_used else None,
        attempts=attempts,
        started_at=started_at,
        completed_at=_now(),
        plan_sha256=_plan_sha256(plan),
    )
    _write_trace(workspace, trace)
    return PlannerOutcome(plan=plan, trace=trace)


def _adapter_payload(response: dict[str, Any]) -> Any:
    value = response.get("result")
    if isinstance(value, dict) and "parsed" in value and "result" in value:
        return value.get("result")
    return value


def _relative_log_file(response: dict[str, Any], workspace: Path) -> str | None:
    value = response.get("log_file")
    nested = response.get("result")
    if not value and isinstance(nested, dict):
        value = nested.get("log_file")
    if not value:
        return None
    try:
        resolved_workspace = workspace.resolve()
        resolved_log = Path(str(value)).resolve()
        if resolved_workspace != resolved_log and resolved_workspace not in resolved_log.parents:
            return None
        return resolved_log.relative_to(resolved_workspace).as_posix()
    except (OSError, ValueError):
        return None


def _write_trace(workspace: Path, trace: PlannerTrace) -> None:
    trace_path = workspace / "review" / "planner_trace.json"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = trace_path.with_suffix(".json.tmp")
    temporary.write_text(trace.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(trace_path)


def _plan_sha256(plan: dict[str, Any]) -> str:
    canonical = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_error(value: str, workspace: Path) -> str:
    redacted = mask_sensitive(value)
    for candidate in {str(workspace), str(workspace.resolve())}:
        redacted = redacted.replace(candidate, "[workspace]")
    return redacted[:500]


def _elapsed_ms(started: float) -> int:
    return max(0, int((perf_counter() - started) * 1000))


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
