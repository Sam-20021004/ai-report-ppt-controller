from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from backend.config import AppConfig
from backend.services.agent_adapters import (
    AgentAdapter,
    make_chatgpt_adapter,
    make_hermes_adapter,
)
from backend.services.agent_readiness import normalize_real_readiness
from backend.services.role_artifacts import (
    ArtifactBoundaryError,
    ArtifactNotChangedError,
    artifact_manifest_entry,
    fingerprint,
    load_changed_json,
    safe_artifact_path,
)
from backend.services.role_contracts import (
    RoleContractError,
    validate_codex_finalization,
    validate_hermes_execution,
    validate_role_baseline_trace,
    validate_role_plan,
)
from backend.services.windows_codex_adapter import make_windows_codex_adapter


DIAGNOSTIC_SOURCE = (
    "Silicon has atomic number 14. This sentence is repository-owned diagnostic text.\n"
)

CODEX_PLAN_PROMPT = """Create exactly the JSON object below, with no extra keys and no Markdown fence.
Write the identical JSON object to diagnostic_plan.json and return the identical JSON object only.
{
  "schema_version": "role.plan.v1",
  "objective": "Validate the Windows Codex to WSL Hermes handoff",
  "tasks": [
    {
      "task_id": "task-001",
      "instruction": "Summarize input/diagnostic_source.md in one factual sentence",
      "inputs": ["input/diagnostic_source.md"],
      "dependencies": [],
      "expected_outputs": ["hermes_execution.json"],
      "acceptance_criteria": ["Return a non-empty summary grounded only in the input file"]
    }
  ],
  "final_outputs": ["diagnostic_final.md"]
}
"""

HERMES_EXECUTION_PROMPT = """Execute task-001 from diagnostic_plan.json without network access.
Read input/diagnostic_source.md. Replace SUMMARY_FROM_INPUT below with one non-empty factual sentence.
Write exactly this JSON shape to hermes_execution.json and return the identical JSON object only.
Do not add keys, change status, or wrap the JSON in Markdown.
{
  "schema_version": "role.execution.v1",
  "task_id": "task-001",
  "status": "success",
  "summary": "SUMMARY_FROM_INPUT",
  "sources": [],
  "artifact_paths": ["hermes_execution.json"],
  "errors": []
}
"""

CODEX_FINAL_PROMPT = """Read diagnostic_plan.json and hermes_execution.json.
Write a short factual Markdown summary to diagnostic_final.md.
Then return exactly the JSON object below, with no extra keys and no Markdown fence.
{
  "schema_version": "role.finalization.v1",
  "status": "success",
  "summary": "Diagnostic finalization complete.",
  "artifact_paths": ["diagnostic_final.md"],
  "errors": []
}
"""


class _BaselineFailure(RuntimeError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _readiness_view(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: result.get(key)
        for key in ("name", "ok", "status", "error_code", "version", "elapsed_ms")
        if key in result
    }


def _attempt(
    agent: str,
    operation: str,
    status: str,
    elapsed_ms: int,
    *,
    error_code: str | None = None,
    artifact_paths: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "agent": agent,
        "operation": operation,
        "status": status,
        "error_code": error_code,
        "elapsed_ms": max(0, int(elapsed_ms or 0)),
        "artifact_paths": artifact_paths or [],
    }


def run_role_baseline(
    settings: AppConfig,
    diagnostics_root: Path,
    *,
    codex: AgentAdapter | None = None,
    hermes: AgentAdapter | None = None,
    chatgpt: AgentAdapter | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    current_run_id = run_id or uuid4().hex
    started_at = _now()
    attempts: list[dict[str, Any]] = []
    manifests: list[dict[str, Any]] = []
    agents: dict[str, dict[str, Any]] = {}
    status = "failed"
    error_code: str | None = None

    diagnostics_root.mkdir(parents=True, exist_ok=True)
    workspace = safe_artifact_path(diagnostics_root, current_run_id)
    workspace.mkdir(parents=True, exist_ok=False)
    (workspace / "input").mkdir(parents=True, exist_ok=True)
    (workspace / "input" / "diagnostic_source.md").write_text(
        DIAGNOSTIC_SOURCE, encoding="utf-8"
    )

    adapters: dict[str, AgentAdapter] = {
        "codex": codex or make_windows_codex_adapter(settings),
        "hermes": hermes or make_hermes_adapter(settings),
        "chatgpt": chatgpt or make_chatgpt_adapter(settings),
    }

    def check_readiness(name: str) -> None:
        check_started = time.perf_counter()
        try:
            raw = adapters[name].health_check()
        except Exception:
            raw = {"ok": False, "status": "failed", "error_code": f"{name}_not_ready"}
        normalized = normalize_real_readiness(name, raw)
        agents[name] = _readiness_view(normalized)
        elapsed = int(normalized.get("elapsed_ms") or _elapsed_ms(check_started))
        attempts.append(
            _attempt(
                name,
                "readiness",
                (
                    "success"
                    if normalized["ok"]
                    else normalized["status"]
                    if normalized["status"] in {"failed", "mock", "fallback", "missing"}
                    else "failed"
                ),
                elapsed,
                error_code=normalized.get("error_code"),
            )
        )
        if not normalized["ok"]:
            raise _BaselineFailure(str(normalized.get("error_code") or f"{name}_not_ready"))

    def run_json_step(
        *,
        agent_name: str,
        task_name: str,
        prompt: str,
        artifact_name: str,
        validator: Callable[[Any], dict[str, Any]],
        extra_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        artifact_path = safe_artifact_path(workspace, artifact_name)
        before = fingerprint(artifact_path)
        call_started = time.perf_counter()
        try:
            response = adapters[agent_name].run_task(
                task_name, prompt, workspace, extra_context
            )
        except Exception:
            attempts.append(
                _attempt(
                    agent_name,
                    task_name,
                    "failed",
                    _elapsed_ms(call_started),
                    error_code=f"{agent_name}_failed",
                )
            )
            raise _BaselineFailure(f"{agent_name}_failed")

        elapsed = int(response.get("elapsed_ms") or _elapsed_ms(call_started))
        if response.get("status") != "success":
            step_error = str(response.get("error_code") or f"{agent_name}_failed")
            attempts.append(
                _attempt(
                    agent_name,
                    task_name,
                    "failed",
                    elapsed,
                    error_code=step_error,
                )
            )
            raise _BaselineFailure(step_error)

        try:
            structured = validator(response.get("result"))
            file_payload = validator(load_changed_json(artifact_path, before))
        except ArtifactNotChangedError:
            attempts.append(
                _attempt(
                    agent_name,
                    task_name,
                    "failed",
                    elapsed,
                    error_code="artifact_not_changed",
                )
            )
            raise _BaselineFailure("artifact_not_changed")
        except (RoleContractError, ValueError, json.JSONDecodeError):
            attempts.append(
                _attempt(
                    agent_name,
                    task_name,
                    "failed",
                    elapsed,
                    error_code="artifact_invalid",
                )
            )
            raise _BaselineFailure("artifact_invalid")

        if structured != file_payload:
            attempts.append(
                _attempt(
                    agent_name,
                    task_name,
                    "failed",
                    elapsed,
                    error_code="artifact_result_mismatch",
                )
            )
            raise _BaselineFailure("artifact_result_mismatch")

        manifests.append(artifact_manifest_entry(workspace, artifact_path))
        attempts.append(
            _attempt(
                agent_name,
                task_name,
                "success",
                elapsed,
                artifact_paths=[artifact_name],
            )
        )
        return structured

    try:
        for agent_name in ("codex", "hermes", "chatgpt"):
            check_readiness(agent_name)

        plan = run_json_step(
            agent_name="codex",
            task_name="role_planner",
            prompt=CODEX_PLAN_PROMPT,
            artifact_name="diagnostic_plan.json",
            validator=validate_role_plan,
        )
        execution = run_json_step(
            agent_name="hermes",
            task_name="role_executor",
            prompt=HERMES_EXECUTION_PROMPT,
            artifact_name="hermes_execution.json",
            validator=validate_hermes_execution,
            extra_context={"task_id": plan["tasks"][0]["task_id"]},
        )

        final_path = safe_artifact_path(workspace, "diagnostic_final.md")
        final_before = fingerprint(final_path)
        final_started = time.perf_counter()
        final_response = adapters["codex"].run_task(
            "role_finalizer",
            CODEX_FINAL_PROMPT,
            workspace,
            {"task_id": execution["task_id"]},
        )
        final_elapsed = int(
            final_response.get("elapsed_ms") or _elapsed_ms(final_started)
        )
        if final_response.get("status") != "success":
            final_error = str(final_response.get("error_code") or "codex_failed")
            attempts.append(
                _attempt(
                    "codex",
                    "role_finalizer",
                    "failed",
                    final_elapsed,
                    error_code=final_error,
                )
            )
            raise _BaselineFailure(final_error)

        try:
            finalization = validate_codex_finalization(final_response.get("result"))
        except RoleContractError:
            attempts.append(
                _attempt(
                    "codex",
                    "role_finalizer",
                    "failed",
                    final_elapsed,
                    error_code="artifact_invalid",
                )
            )
            raise _BaselineFailure("artifact_invalid")
        final_after = fingerprint(final_path)
        if final_after is None or final_after == final_before:
            attempts.append(
                _attempt(
                    "codex",
                    "role_finalizer",
                    "failed",
                    final_elapsed,
                    error_code="artifact_not_changed",
                )
            )
            raise _BaselineFailure("artifact_not_changed")
        if "diagnostic_final.md" not in finalization["artifact_paths"]:
            attempts.append(
                _attempt(
                    "codex",
                    "role_finalizer",
                    "failed",
                    final_elapsed,
                    error_code="artifact_invalid",
                )
            )
            raise _BaselineFailure("artifact_invalid")
        if not final_path.read_text(encoding="utf-8-sig").strip():
            raise _BaselineFailure("artifact_invalid")

        manifests.append(artifact_manifest_entry(workspace, final_path))
        attempts.append(
            _attempt(
                "codex",
                "role_finalizer",
                "success",
                final_elapsed,
                artifact_paths=["diagnostic_final.md"],
            )
        )
        status = "success"
    except _BaselineFailure as exc:
        error_code = exc.error_code
    except (ArtifactBoundaryError, FileExistsError):
        error_code = "artifact_boundary_error"
    except Exception:
        error_code = "baseline_failed"
    finally:
        completed_at = _now()
        trace = {
            "schema_version": "role.baseline.trace.v1",
            "run_id": current_run_id,
            "status": status,
            "error_code": error_code,
            "started_at": started_at,
            "completed_at": completed_at,
            "attempts": attempts,
            "artifacts": manifests,
        }
        trace = validate_role_baseline_trace(trace)
        trace_path = workspace / "role_baseline_trace.json"
        trace_path.write_text(
            json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    relative_workspace = workspace.relative_to(diagnostics_root.parent).as_posix()
    produced_artifacts = [str(item["path"]) for item in manifests]
    produced_artifacts.append("role_baseline_trace.json")
    return {
        "run_id": current_run_id,
        "status": status,
        "error_code": error_code,
        "agents": agents,
        "artifacts": produced_artifacts,
        "trace_file": f"{relative_workspace}/role_baseline_trace.json",
    }
