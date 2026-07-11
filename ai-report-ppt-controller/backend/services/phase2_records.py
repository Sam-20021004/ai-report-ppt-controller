from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from backend.services.phase2_utils import now
from backend.services.research_summarizer import SCHEMA_VERSION as RESEARCH_NOTES_SCHEMA_VERSION


PHASE2_RESEARCH_ARTIFACTS = {
    "research/search_plan.json": "检索计划",
    "research/sources.json": "真实搜索候选来源与审计信息",
    "research/source_review.json": "Phase 2 人工来源复核状态",
    "research/research_notes.md": "人工核查用资料整理",
    "research/research_notes.json": "结构化研究备注与质量摘要",
}

PHASE3_DRAFT_ARTIFACTS = {
    "draft/report_outline.json": {
        "file_type": "report_outline",
        "category": "phase3_draft",
        "description": "Structured report outline derived from reviewed research artifacts",
    },
    "draft/report_draft.json": {
        "file_type": "report_draft",
        "category": "phase3_draft",
        "description": "Structured report section draft derived from reviewed research artifacts",
    },
}


def relative_to_storage(path: Path, storage_dir: Path) -> str:
    return path.resolve().relative_to(storage_dir.resolve()).as_posix()


def build_file_metadata(task_id: str, file_path: Path, storage_dir: Path, task_root: Path) -> dict[str, Any]:
    stat = file_path.stat()
    try:
        relative_path = file_path.resolve().relative_to(task_root.resolve()).as_posix()
    except ValueError:
        relative_path = file_path.name
    is_phase2_artifact = relative_path in PHASE2_RESEARCH_ARTIFACTS
    phase3_metadata = PHASE3_DRAFT_ARTIFACTS.get(relative_path, {})
    return {
        "file_id": relative_to_storage(file_path, storage_dir),
        "task_id": task_id,
        "file_name": file_path.name,
        "file_type": phase3_metadata.get("file_type") or file_path.suffix.lstrip(".") or "file",
        "relative_path": relative_path,
        "path": str(file_path),
        "size": stat.st_size,
        "created_at": now(),
        "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "category": phase3_metadata.get("category")
        or ("phase2_research" if is_phase2_artifact else relative_path.split("/", 1)[0]),
        "description": phase3_metadata.get("description") or PHASE2_RESEARCH_ARTIFACTS.get(relative_path, ""),
        "is_phase2_artifact": is_phase2_artifact,
    }


def collect_phase2_files(task_id: str, research_dir: Path, storage_dir: Path, task_root: Path) -> list[dict[str, Any]]:
    files = []
    for name in ("search_plan.json", "sources.json", "source_review.json", "research_notes.md", "research_notes.json"):
        path = research_dir / name
        if path.exists() and path.is_file():
            files.append(build_file_metadata(task_id, path, storage_dir, task_root))
    return files


def sort_task_files(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    phase2_order = {name: index for index, name in enumerate(PHASE2_RESEARCH_ARTIFACTS)}
    return sorted(
        files,
        key=lambda item: (
            0 if item.get("is_phase2_artifact") else 1,
            phase2_order.get(item.get("relative_path"), 999),
            item.get("relative_path") or item.get("file_name") or "",
        ),
    )


def _dedupe_phase2_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, Any, str]] = set()
    unique = []
    for item in errors:
        if not isinstance(item, dict):
            continue
        key = (str(item.get("stage") or ""), item.get("query_id"), str(item.get("message") or ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def update_phase2_record(
    record: Any,
    search_plan: dict[str, Any],
    sources: dict[str, Any],
    phase2_files: list[dict[str, Any]],
    planner_errors: list[dict[str, Any]] | None = None,
    research_summary: dict[str, Any] | None = None,
) -> None:
    planner_diagnostics = search_plan.get("diagnostics") or {}
    source_diagnostics = sources.get("diagnostics") or {}
    source_fallback = sources.get("fallback") or {}
    source_errors = sources.get("errors") or []
    source_quality = sources.get("source_quality_summary") or {}
    domains_summary = sources.get("domains_summary") or {}
    summary_payload = (research_summary or {}).get("research_notes") or {}
    audit_summary = summary_payload.get("audit_summary") or {}
    summary_errors = (research_summary or {}).get("errors") or []
    planner_fallback_used = bool(planner_diagnostics.get("fallback_used"))
    search_fallback_used = bool(source_fallback.get("used"))
    source_executor = source_diagnostics.get("executor") or "not_started"
    if source_executor == "not_started":
        source_status = "planned" if not planner_fallback_used else "fallback_planned"
    elif search_fallback_used:
        source_status = "search_fallback"
    else:
        source_status = "searched"

    phase2_errors = _dedupe_phase2_errors([*(planner_errors or []), *source_errors, *summary_errors])
    if research_summary:
        if summary_payload.get("source_count", 0) == 0:
            status = "summarized_no_sources"
        elif phase2_errors:
            status = "summarized_with_errors"
        else:
            status = "summarized"
    else:
        status = source_status

    record.phase2_inputs = search_plan.get("inputs") or {}
    record.phase2_outputs_summary = {
        "status": status,
        "source_status": source_status,
        "schema_versions": {
            "search_plan": search_plan.get("schema_version"),
            "sources": sources.get("schema_version"),
            "research_notes": summary_payload.get("schema_version")
            or (RESEARCH_NOTES_SCHEMA_VERSION if research_summary else None),
        },
        "query_count": len(search_plan.get("queries") or []),
        "executed_query_count": sources.get("executed_query_count", 0),
        "source_count": len(sources.get("items") or []),
        "error_count": len(phase2_errors),
        "planner": planner_diagnostics.get("planner", "local_rule_based"),
        "planner_fallback_used": planner_fallback_used,
        "search_fallback_used": search_fallback_used,
        "fallback_used": planner_fallback_used or search_fallback_used,
        "source_execution": source_executor,
        "quality_summary": {
            "sources_count": len(sources.get("items") or []),
            "unique_domains": domains_summary.get("unique_domain_count", audit_summary.get("unique_domain_count", 0)),
            "failed_queries": len(sources.get("failed_queries") or []),
            "manual_review_required_count": source_quality.get(
                "manual_review_required_count",
                audit_summary.get("manual_review_required_count", 0),
            ),
            "fallback_used": planner_fallback_used or search_fallback_used,
        },
        "research_notes": {
            "status": (research_summary or {}).get("status"),
            "file": (research_summary or {}).get("research_notes_file"),
            "json_file": (research_summary or {}).get("research_notes_json_file"),
            "source_count": summary_payload.get("source_count"),
            "executed_query_count": summary_payload.get("executed_query_count"),
            "preliminary_note_count": summary_payload.get("preliminary_note_count"),
            "manual_review_required_count": audit_summary.get("manual_review_required_count"),
            "retrieved_at": summary_payload.get("retrieved_at"),
            "generated_at": summary_payload.get("generated_at"),
        }
        if research_summary
        else {},
        "files": [item["file_name"] for item in phase2_files],
    }
    record.phase2_errors = phase2_errors
    record.phase2_files = phase2_files
