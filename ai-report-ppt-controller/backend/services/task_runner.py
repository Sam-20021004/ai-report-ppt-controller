from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from backend.config import STORAGE_DIR, get_settings
from backend.models.task import TaskRecord, TaskRequest, default_steps
from backend.services.agent_adapters import make_codex_adapter, make_hermes_adapter, write_json
from backend.services.phase2_artifacts import execute_phase2_search_plan, summarize_phase2_research, write_phase2_contract_artifacts
from backend.services.phase2_records import build_file_metadata, sort_task_files
from backend.services.security import HTTPException, safe_join


JOB_ROOT = STORAGE_DIR / "workspace" / "jobs"
WORKSPACE_SUBDIRS = ("input", "state", "prompts", "research", "draft", "build", "review", "output", "logs")


def task_dir(task_id: str) -> Path:
    return safe_join(JOB_ROOT, task_id)


def task_log_path(task_id: str) -> Path:
    return task_dir(task_id) / "state" / "status.json"


def task_request_path(task_id: str) -> Path:
    return task_dir(task_id) / "state" / "request.json"


def task_yaml_path(task_id: str) -> Path:
    return task_dir(task_id) / "state" / "task.yaml"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _render_user_request(request: TaskRequest) -> str:
    return "\n".join(
        [
            f"# {request.title}",
            "",
            f"- Task type: {request.task_type}",
            f"- Domain: {request.domain}",
            f"- Audience: {request.audience}",
            f"- Language: {request.language}",
            f"- PPT pages: {request.ppt_pages}",
            f"- Word target words: {request.word_target_words}",
            f"- Web search: {request.enable_web_search}",
            f"- Fact check: {request.enable_fact_check}",
            "",
            "## Search Boundary",
            request.search_boundary or "",
            "",
            "## Keywords",
            request.keywords or "",
            "",
            "## User Outline",
            request.user_outline or "",
        ]
    )


def _render_task_yaml(request: TaskRequest) -> str:
    output = ["pptx"] if request.task_type == "ppt" else ["docx"] if request.task_type == "word" else ["pptx", "docx"]
    if request.task_type in {"research_only", "outline_only"}:
        output = [request.task_type]
    lines = [
        f'task_id: "{request.task_id}"',
        f'task_type: "{request.task_type}"',
        f'topic: "{request.title}"',
        "output:",
        *[f"  - {item}" for item in output],
        "requirements:",
        f'  language: "{request.language}"',
        f'  style: "{request.domain}"',
        f'  audience: "{request.audience}"',
        f"  citation_required: {str(request.enable_fact_check).lower()}",
        "loop:",
        f"  max_rounds: {max(1, min(request.loop_rounds or 1, get_settings().max_review_rounds))}",
        f"  pass_score: {get_settings().pass_score}",
    ]
    return "\n".join(lines) + "\n"


def _ensure_workspace(request: TaskRequest) -> Path:
    workspace = task_dir(request.task_id)
    for subdir in WORKSPACE_SUBDIRS:
        (workspace / subdir).mkdir(parents=True, exist_ok=True)
    _write_text(workspace / "input" / "user_request.md", _render_user_request(request))
    _write_text(task_yaml_path(request.task_id), _render_task_yaml(request))
    write_json(task_request_path(request.task_id), request.model_dump())
    return workspace


def create_task(request: TaskRequest) -> TaskRecord:
    settings = get_settings()
    if not request.output_dir:
        request.output_dir = str(Path(settings.output_dir) / request.task_id)

    workspace = _ensure_workspace(request)
    record = TaskRecord(
        task_id=request.task_id,
        request=request,
        steps=default_steps(),
        workspace_dir=str(workspace),
    )
    save_record(record)
    return record


def save_record(record: TaskRecord) -> None:
    record.updated_at = _now()
    workspace = task_dir(record.task_id)
    (workspace / "state").mkdir(parents=True, exist_ok=True)
    task_log_path(record.task_id).write_text(record.model_dump_json(indent=2), encoding="utf-8")


def load_record(task_id: str) -> TaskRecord:
    path = task_log_path(task_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Task not found.")
    return TaskRecord(**json.loads(path.read_text(encoding="utf-8-sig")))


def _phase2_artifact_count(record: dict[str, Any], workspace: Path) -> int:
    phase2_files = record.get("phase2_files")
    if isinstance(phase2_files, list):
        return sum(1 for item in phase2_files if isinstance(item, dict) and item.get("is_phase2_artifact"))

    research_dir = workspace / "research"
    known_files = [
        "search_plan.json",
        "sources.json",
        "source_review.json",
        "research_notes.md",
        "research_notes.json",
    ]
    return sum(1 for name in known_files if (research_dir / name).exists())


def _task_summary_from_status(path: Path) -> dict[str, Any] | None:
    try:
        record = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(record, dict):
        return None

    workspace = path.parents[1]
    task_id = str(record.get("task_id") or workspace.name)
    request = record.get("request") if isinstance(record.get("request"), dict) else {}
    phase2_artifact_count = _phase2_artifact_count(record, workspace)
    return {
        "task_id": task_id,
        "short_task_id": task_id[:8],
        "title": str(request.get("title") or task_id),
        "task_type": str(request.get("task_type") or ""),
        "status": str(record.get("status") or "unknown"),
        "created_at": str(record.get("created_at") or ""),
        "updated_at": str(record.get("updated_at") or record.get("created_at") or ""),
        "phase2_artifact_count": phase2_artifact_count,
        "has_phase2_artifacts": phase2_artifact_count > 0,
    }


def list_task_summaries(limit: int = 20, job_root: Path = JOB_ROOT) -> list[dict[str, Any]]:
    if not job_root.exists():
        return []

    summaries: list[dict[str, Any]] = []
    for task_root in job_root.iterdir():
        if not task_root.is_dir():
            continue
        summary = _task_summary_from_status(task_root / "state" / "status.json")
        if summary:
            summaries.append(summary)

    summaries.sort(key=lambda item: item.get("updated_at") or item.get("created_at") or "", reverse=True)
    return summaries[: max(1, limit)]


def list_task_files(task_id: str) -> list[dict]:
    directory = task_dir(task_id)
    if not directory.exists():
        raise HTTPException(status_code=404, detail="Task not found.")
    files = []
    for file_path in directory.rglob("*"):
        if file_path.is_file():
            files.append(build_file_metadata(task_id, file_path, STORAGE_DIR, directory))
    return sort_task_files(files)


def _generated_output_files(task_id: str) -> list[dict]:
    workspace = task_dir(task_id)
    files = []
    for file_path in (workspace / "output").glob("*"):
        if file_path.is_file():
            files.append(build_file_metadata(task_id, file_path, STORAGE_DIR, workspace))
    return files


def _mark_step(
    record: TaskRecord,
    index: int,
    status: str,
    output_summary: str,
    input_value: Any = None,
    output_value: Any = None,
    error: str = "",
    started_at: str | None = None,
    elapsed_ms: int | None = None,
) -> None:
    step = record.steps[index - 1]
    step.status = status
    step.started_at = started_at or step.started_at or _now()
    step.ended_at = _now()
    step.elapsed_ms = elapsed_ms
    step.input = input_value
    step.output = output_value
    step.output_summary = output_summary
    step.error = error
    save_record(record)


def _run_step(
    record: TaskRecord,
    index: int,
    fn,
    success_summary: str,
    input_value: Any = None,
) -> Any:
    step = record.steps[index - 1]
    started_at = _now()
    started = perf_counter()
    step.status = "running"
    step.started_at = started_at
    step.input = input_value
    save_record(record)
    try:
        output = fn()
        if isinstance(output, dict) and output.get("status") == "failed":
            raise RuntimeError(output.get("error") or f"{step.step_name} returned failed status.")
        elapsed = int((perf_counter() - started) * 1000)
        _mark_step(record, index, "success", success_summary, input_value, output, started_at=started_at, elapsed_ms=elapsed)
        return output
    except Exception as exc:
        elapsed = int((perf_counter() - started) * 1000)
        _mark_step(record, index, "failed", "步骤失败。", input_value, None, str(exc), started_at=started_at, elapsed_ms=elapsed)
        record.status = "failed"
        save_record(record)
        raise


def _skip_step(record: TaskRecord, index: int, summary: str) -> None:
    _mark_step(record, index, "skipped", summary)


def _prompt_header(request: TaskRequest, role: str) -> str:
    return (
        f"Role: {role}\n"
        f"Task ID: {request.task_id}\n"
        f"Title: {request.title}\n"
        f"Task type: {request.task_type}\n"
        f"Domain: {request.domain}\n"
        f"Audience: {request.audience}\n"
        f"Language: {request.language}\n\n"
        "All outputs must be structured and written into the workspace files requested by the orchestrator.\n"
    )


def _planner_prompt(request: TaskRequest) -> str:
    return _prompt_header(request, "Hermes Planner") + (
        "Generate a JSON research and document-production plan with outline, search_questions, figures_needed, risks, and success_criteria.\n"
        "Do not edit PPT or Word files directly.\n"
    )


def _writer_prompt(request: TaskRequest) -> str:
    return _prompt_header(request, "Hermes Writer") + (
        "Read draft/outline.json and research/sources.json, then generate content.md and slides_storyboard.json.\n"
        "Separate verified facts from assumptions.\n"
    )


def _reviewer_prompt(request: TaskRequest, round_id: int) -> str:
    return _prompt_header(request, f"Hermes Reviewer Round {round_id}") + (
        "Review output files. Return JSON with score, pass, blocking_issues, minor_issues, and revision_instruction.\n"
        "Hermes may only write review JSON. Codex is responsible for modifying generated files.\n"
    )


def _codex_builder_prompt(request: TaskRequest) -> str:
    return _prompt_header(request, "Codex Builder") + (
        "Read draft/content.md and draft/slides_storyboard.json. Generate requested PPT/Word files in output/.\n"
        "Place scripts in build/ and output agent result JSON.\n"
    )


def _codex_fixer_prompt(request: TaskRequest, review_file: str) -> str:
    return _prompt_header(request, "Codex Fixer") + (
        f"Read {review_file}, then fix generated output files and update agent result JSON.\n"
        "Do not modify input templates.\n"
    )


def _issue_signature(review: dict[str, Any]) -> str:
    blocking = review.get("blocking_issues") or []
    if not blocking:
        return ""
    return "|".join(f"{item.get('type')}:{item.get('location')}" for item in blocking)


def _write_planner_artifacts(workspace: Path, planner: dict[str, Any]) -> None:
    write_json(workspace / "draft" / "outline.json", planner)
    write_json(workspace / "research" / "search_queries.json", planner.get("search_questions", []))


def _write_writer_artifacts(workspace: Path, writer: dict[str, Any]) -> None:
    _write_text(workspace / "draft" / "content.md", writer.get("content_markdown", ""))
    write_json(workspace / "draft" / "slides_storyboard.json", writer.get("slides_storyboard", []))
    write_json(
        workspace / "draft" / "report_structure.json",
        {
            "content_file": "draft/content.md",
            "storyboard_file": "draft/slides_storyboard.json",
            "created_at": _now(),
        },
    )


def _copy_outputs_to_export_dir(record: TaskRecord) -> None:
    output_dir = Path(record.request.output_dir or "")
    try:
        storage_root = STORAGE_DIR.resolve()
        resolved = output_dir.resolve()
        if storage_root != resolved and storage_root not in resolved.parents:
            output_dir = STORAGE_DIR / "outputs" / record.task_id
    except OSError:
        output_dir = STORAGE_DIR / "outputs" / record.task_id

    output_dir.mkdir(parents=True, exist_ok=True)
    for item in _generated_output_files(record.task_id):
        source = Path(item["path"])
        if source.name == "manifest.json":
            continue
        shutil.copy2(source, output_dir / source.name)


def run_workflow(task_id: str) -> TaskRecord:
    record = load_record(task_id)
    request = record.request
    settings = get_settings()
    workspace = _ensure_workspace(request)
    record.workspace_dir = str(workspace)
    record.status = "running"
    save_record(record)

    hermes = make_hermes_adapter(settings)
    codex = make_codex_adapter(settings)
    base_context = {"request": request.model_dump()}

    _mark_step(
        record,
        1,
        "success",
        "已创建独立 job workspace，并写入 input/user_request.md、state/task.yaml 和 state/status.json。",
        output_value={"workspace": str(workspace)},
    )

    planner_prompt = _planner_prompt(request)
    _write_text(workspace / "prompts" / "hermes_planner.md", planner_prompt)

    planner_result = _run_step(
        record,
        2,
        lambda: hermes.run_task("planner", planner_prompt, workspace, base_context),
        "Hermes Planner 已生成 outline.json 和 search_queries.json。",
    )
    if planner_result.get("status") != "success":
        raise RuntimeError(planner_result.get("error") or "Hermes planner failed.")
    planner = planner_result.get("result", {})
    _write_planner_artifacts(workspace, planner)
    phase2_contract = write_phase2_contract_artifacts(record, workspace, STORAGE_DIR, task_dir(record.task_id))
    record.steps[1].output_summary = "Planner artifacts and structured Phase 2 search plan generated."
    record.steps[1].output = {
        "planner_result": planner_result,
        "phase2_contract": {
            "files": [item["file_name"] for item in phase2_contract["phase2_files"]],
            "query_count": len(phase2_contract["search_plan"].get("queries") or []),
            "source_count": len(phase2_contract["sources"].get("items") or []),
            "fallback_used": bool(phase2_contract["search_plan"].get("diagnostics", {}).get("fallback_used")),
        },
    }
    save_record(record)

    if request.task_type == "outline_only":
        for index in range(3, 9):
            _skip_step(record, index, "仅生成大纲任务已跳过后续步骤。")
        record.status = "done"
        record.generated_files = _generated_output_files(record.task_id)
        save_record(record)
        return record

    if request.enable_web_search:
        research_result = _run_step(
            record,
            3,
            lambda: execute_phase2_search_plan(record, workspace, settings, STORAGE_DIR, task_dir(record.task_id)),
            "Phase 2 web search executed; sources.json was updated with results or fallback diagnostics.",
        )
    else:
        research_result = write_phase2_contract_artifacts(record, workspace, STORAGE_DIR, task_dir(record.task_id))
        _skip_step(record, 3, "Web search disabled; structured Phase 2 search plan files were generated.")

    planner_errors = research_result.get("planner_errors") or []
    if request.task_type == "research_only":
        _run_step(
            record,
            4,
            lambda: summarize_phase2_research(record, workspace, STORAGE_DIR, task_dir(record.task_id), planner_errors),
            "Phase 2 research notes generated from sources.json.",
        )
        for index in range(5, 10):
            _skip_step(record, index, "仅资料检索任务已跳过文档生成步骤。")
        record.status = "done"
        record.generated_files = _generated_output_files(record.task_id)
        save_record(record)
        return record

    writer_prompt = _writer_prompt(request)
    _write_text(workspace / "prompts" / "hermes_writer.md", writer_prompt)

    def _summarize_and_write() -> dict[str, Any]:
        research_summary = summarize_phase2_research(record, workspace, STORAGE_DIR, task_dir(record.task_id), planner_errors)
        writer = hermes.run_task("writer", writer_prompt, workspace, base_context)
        if writer.get("status") != "success":
            return writer
        _write_writer_artifacts(workspace, writer.get("result", {}))
        return {
            "status": "success",
            "research_summary": research_summary,
            "writer_result": writer,
        }

    writer_output = _run_step(
        record,
        4,
        _summarize_and_write,
        "Hermes Writer 已生成 content.md、slides_storyboard.json 和 report_structure.json。",
    )
    writer_result = writer_output.get("writer_result", {})
    if writer_result.get("status") != "success":
        raise RuntimeError(writer_result.get("error") or "Hermes writer failed.")
    builder_prompt = _codex_builder_prompt(request)
    _write_text(workspace / "prompts" / "codex_builder.md", builder_prompt)
    builder_result = _run_step(
        record,
        5,
        lambda: codex.run_task("builder", builder_prompt, workspace, base_context),
        "Codex Builder 已生成 build 脚本、agent result 和输出文件。",
    )
    if builder_result.get("status") != "success":
        raise RuntimeError(builder_result.get("error") or "Codex builder failed.")

    max_rounds = max(1, min(request.loop_rounds or settings.max_review_rounds, settings.max_review_rounds))
    pass_score = settings.pass_score
    review_outputs: list[dict[str, Any]] = []
    revision_outputs: list[dict[str, Any]] = []
    review_passed = False
    last_signature = ""
    repeated_issue_count = 0

    for round_id in range(1, max_rounds + 1):
        record.review_round = round_id
        review_prompt = _reviewer_prompt(request, round_id)
        _write_text(workspace / "prompts" / "hermes_reviewer.md", review_prompt)
        review_result = _run_step(
            record,
            6,
            lambda rid=round_id: hermes.run_task("reviewer", review_prompt, workspace, {**base_context, "round_id": rid}),
            f"Hermes Reviewer 已完成第 {round_id} 轮审核。",
        )
        if review_result.get("status") != "success":
            raise RuntimeError(review_result.get("error") or "Hermes reviewer failed.")
        review = review_result.get("result", {})
        review_file = workspace / "review" / f"review_round_{round_id}.json"
        write_json(review_file, review)
        review_outputs.append({"round": round_id, "review_file": str(review_file), "review": review})
        record.steps[5].output = review_outputs
        save_record(record)

        signature = _issue_signature(review)
        repeated_issue_count = repeated_issue_count + 1 if signature and signature == last_signature else 1
        last_signature = signature

        if bool(review.get("pass")) and int(review.get("score", 0)) >= pass_score:
            review_passed = True
            break

        if repeated_issue_count >= 2:
            record.status = "needs_review"
            _mark_step(record, 7, "needs_review", "连续两轮出现同类阻塞问题，已停止自动修复并等待人工介入。")
            break

        if round_id >= max_rounds:
            record.status = "needs_review"
            _mark_step(record, 7, "needs_review", "已达到最大审核轮次，等待人工确认。")
            break

        review_relative = f"review/review_round_{round_id}.json"
        fixer_prompt = _codex_fixer_prompt(request, review_relative)
        _write_text(workspace / "prompts" / "codex_fixer.md", fixer_prompt)
        fixer_result = _run_step(
            record,
            7,
            lambda review_path=review_relative: codex.run_task(
                "fixer",
                fixer_prompt,
                workspace,
                {**base_context, "review_file": review_path},
            ),
            f"Codex Fixer 已根据第 {round_id} 轮 review.json 修改输出。",
        )
        if fixer_result.get("status") != "success":
            raise RuntimeError(fixer_result.get("error") or "Codex fixer failed.")
        revision_outputs.append({"round": round_id, "result": fixer_result})
        record.steps[6].output = revision_outputs
        save_record(record)

    if not revision_outputs and record.steps[6].status == "waiting":
        _skip_step(record, 7, "审核已通过或无需自动修复。")

    final_review = {}
    if review_passed:
        final_prompt = _reviewer_prompt(request, record.review_round or 1)
        final_result = hermes.run_task("final_reviewer", final_prompt, workspace, base_context)
        if final_result.get("status") == "success":
            final_review = final_result.get("result", {})
            write_json(workspace / "review" / "final_review.json", final_review)

    record.final_quality_check = final_review or (review_outputs[-1]["review"] if review_outputs else {})
    record.generated_files = _generated_output_files(record.task_id)
    _copy_outputs_to_export_dir(record)
    write_json(
        workspace / "output" / "final_manifest.json",
        {
            "task_id": record.task_id,
            "workspace": str(workspace),
            "review_passed": review_passed,
            "final_quality_check": record.final_quality_check,
            "generated_files": record.generated_files,
            "finished_at": _now(),
        },
    )
    record.generated_files = _generated_output_files(record.task_id)

    _mark_step(
        record,
        8,
        "success" if review_passed else "needs_review",
        "已生成 final_manifest.json，并同步输出文件到导出目录。" if review_passed else "已生成 final_manifest.json，但质量审核未通过。",
        output_value={"final_quality_check": record.final_quality_check, "generated_files": record.generated_files},
    )
    _mark_step(
        record,
        9,
        "done" if review_passed else "needs_review",
        "工作流已完成。" if review_passed else "工作流已停止在人工确认状态。",
    )
    record.status = "done" if review_passed else "needs_review"
    save_record(record)
    return record


def run_phase1(task_id: str) -> TaskRecord:
    return run_workflow(task_id)


def update_task_status(task_id: str, status: str) -> TaskRecord:
    record = load_record(task_id)
    record.status = status
    save_record(record)
    return record
