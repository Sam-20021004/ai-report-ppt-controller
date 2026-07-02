from __future__ import annotations

import json
import re
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "phase2.research_notes.v1"
SOURCES_SCHEMA_UNAVAILABLE = "phase2.sources.unavailable"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _clean_text(value: Any, limit: int = 1000) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text).strip()
    return text[:limit]


def _domain_from_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return ""
    return (parsed.hostname or "").lower().removeprefix("www.")


def _error(stage: str, message: str, detail: str | None = None, query_id: str | None = None) -> dict[str, Any]:
    payload = {
        "query_id": query_id,
        "query": None,
        "stage": stage,
        "message": _clean_text(message, limit=500),
        "recoverable": True,
    }
    if detail:
        payload["detail"] = _clean_text(detail, limit=1000)
    return payload


def _load_json_file(path: Path, label: str) -> tuple[Any, list[dict[str, Any]]]:
    if not path.exists():
        return None, [_error("research_summarizer", f"{label} is missing.", str(path))]
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")), []
    except json.JSONDecodeError as exc:
        return None, [_error("research_summarizer", f"{label} is not valid JSON.", str(exc))]
    except OSError as exc:
        return None, [_error("research_summarizer", f"{label} could not be read.", str(exc))]


def _query_entries(search_plan: dict[str, Any], sources: dict[str, Any]) -> list[dict[str, Any]]:
    raw_queries = search_plan.get("queries") if isinstance(search_plan, dict) else []
    queries: list[dict[str, Any]] = []
    if isinstance(raw_queries, list):
        for index, item in enumerate(raw_queries, start=1):
            if not isinstance(item, dict):
                continue
            query_id = _clean_text(item.get("id"), limit=60) or f"q{index:03d}"
            queries.append(
                {
                    "id": query_id,
                    "query": _clean_text(item.get("query"), limit=300),
                    "purpose": _clean_text(item.get("purpose"), limit=120),
                    "language": _clean_text(item.get("language"), limit=40),
                    "priority": item.get("priority"),
                }
            )

    if queries:
        return queries

    seen: set[str] = set()
    raw_items = sources.get("items") if isinstance(sources, dict) else []
    if isinstance(raw_items, list):
        for index, item in enumerate(raw_items, start=1):
            if not isinstance(item, dict):
                continue
            query_id = _clean_text(item.get("query_id"), limit=60) or f"q{index:03d}"
            if query_id in seen:
                continue
            seen.add(query_id)
            queries.append(
                {
                    "id": query_id,
                    "query": _clean_text(item.get("query"), limit=300),
                    "purpose": "",
                    "language": _clean_text(item.get("language"), limit=40),
                    "priority": None,
                }
            )
    return queries


def _normalize_source_item(
    raw: Any,
    index: int,
    default_retrieved_at: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not isinstance(raw, dict):
        return None, _error("research_summarizer", f"Source item #{index} is not an object.")
    if not raw:
        return None, _error("research_summarizer", f"Source item #{index} is empty.")

    title = _clean_text(raw.get("title"), limit=300)
    url = _clean_text(raw.get("url"), limit=1000)
    snippet = _clean_text(raw.get("snippet") or raw.get("claim_supported"), limit=1000)
    if not title and not url and not snippet:
        return None, _error("research_summarizer", f"Source item #{index} has no title, URL, or snippet.")

    domain = _clean_text(raw.get("domain"), limit=200) or _domain_from_url(url)
    retrieved_at = _clean_text(raw.get("retrieved_at") or default_retrieved_at, limit=80)
    item = {
        "id": _clean_text(raw.get("id"), limit=60) or f"s{index:03d}",
        "query_id": _clean_text(raw.get("query_id"), limit=60),
        "query": _clean_text(raw.get("query"), limit=300),
        "rank": raw.get("rank"),
        "title": title,
        "domain": domain,
        "url": url,
        "snippet": snippet,
        "source_type": _clean_text(raw.get("source_type") or raw.get("status"), limit=120),
        "retrieved_at": retrieved_at,
        "language": _clean_text(raw.get("language"), limit=40),
        "confidence": _clean_text(raw.get("confidence"), limit=80),
        "preliminary_note": _preliminary_note(snippet),
    }
    return item, None


def _preliminary_note(snippet: str) -> str:
    if not snippet:
        return "No snippet was captured; the source must be opened before any fact claim is made."
    return f"Snippet-derived candidate note, not verified: {snippet}"


def _normalize_sources(raw_sources: Any, task_id: str, load_errors: list[dict[str, Any]]) -> dict[str, Any]:
    if isinstance(raw_sources, dict):
        sources = dict(raw_sources)
        raw_items = sources.get("items")
        if raw_items is None and isinstance(sources.get("sources"), list):
            raw_items = sources.get("sources")
        if not isinstance(raw_items, list):
            raw_items = []
            load_errors.append(_error("research_summarizer", "sources.json does not contain an items list."))
    elif isinstance(raw_sources, list):
        sources = {
            "schema_version": "legacy.sources.list",
            "task_id": task_id,
            "created_at": _now(),
            "query_count": 0,
            "executed_query_count": 0,
            "items": raw_sources,
            "errors": [],
            "fallback": {"used": False, "reason": None},
            "diagnostics": {"executor": "legacy_list", "warnings": []},
        }
        raw_items = raw_sources
    else:
        sources = {
            "schema_version": SOURCES_SCHEMA_UNAVAILABLE,
            "task_id": task_id,
            "created_at": _now(),
            "query_count": 0,
            "executed_query_count": 0,
            "items": [],
            "errors": [],
            "fallback": {"used": True, "reason": "sources.json was missing or unreadable."},
            "diagnostics": {
                "executor": "unavailable",
                "provider": None,
                "network_enabled": False,
                "warnings": ["sources.json was missing or unreadable."],
            },
        }
        raw_items = []

    default_retrieved_at = _clean_text(sources.get("created_at"), limit=80) or _now()
    normalized_items: list[dict[str, Any]] = []
    item_errors: list[dict[str, Any]] = []
    for index, raw_item in enumerate(raw_items, start=1):
        item, error = _normalize_source_item(raw_item, index, default_retrieved_at)
        if item:
            normalized_items.append(item)
        if error:
            item_errors.append(error)

    source_errors = sources.get("errors") if isinstance(sources.get("errors"), list) else []
    errors = [*load_errors, *source_errors, *item_errors]
    if not normalized_items:
        errors.append(_error("research_summarizer", "sources.json has no usable source items to summarize."))

    normalized = dict(sources)
    normalized["items"] = normalized_items
    normalized["errors"] = errors
    normalized["source_count"] = len(normalized_items)
    normalized.setdefault("fallback", {"used": False, "reason": None})
    normalized.setdefault("diagnostics", {})
    return normalized


def _normalize_search_plan(raw_plan: Any, load_errors: list[dict[str, Any]]) -> dict[str, Any]:
    if isinstance(raw_plan, dict):
        plan = dict(raw_plan)
    else:
        plan = {
            "schema_version": "phase2.search_plan.unavailable",
            "created_at": _now(),
            "inputs": {},
            "queries": [],
            "diagnostics": {
                "planner": "unavailable",
                "warnings": ["search_plan.json was missing or unreadable."],
            },
        }
        if load_errors:
            plan["errors"] = load_errors
    plan.setdefault("inputs", {})
    plan.setdefault("queries", [])
    plan.setdefault("diagnostics", {})
    return plan


def _group_sources_by_query(
    queries: list[dict[str, Any]],
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    query_ids = {query["id"] for query in queries}
    grouped = {query["id"]: [] for query in queries}
    unknown: list[dict[str, Any]] = []
    for item in items:
        query_id = item.get("query_id") or ""
        if query_id in grouped:
            grouped[query_id].append(item)
        else:
            unknown.append(item)

    result = [
        {
            "query": query,
            "sources": grouped.get(query["id"], []),
        }
        for query in queries
    ]
    if unknown:
        result.append(
            {
                "query": {
                    "id": "unknown",
                    "query": "Sources without a matching query_id",
                    "purpose": "",
                    "language": "",
                    "priority": None,
                },
                "sources": unknown,
            }
        )
    if not result and items:
        result.append(
            {
                "query": {
                    "id": "unknown",
                    "query": "No query metadata was available",
                    "purpose": "",
                    "language": "",
                    "priority": None,
                },
                "sources": items,
            }
        )
    elif not result and not query_ids:
        result.append(
            {
                "query": {
                    "id": "none",
                    "query": "No executable queries were available",
                    "purpose": "",
                    "language": "",
                    "priority": None,
                },
                "sources": [],
            }
        )
    return result


def _dedupe_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str | None, str]] = set()
    unique: list[dict[str, Any]] = []
    for item in errors:
        if not isinstance(item, dict):
            continue
        key = (
            _clean_text(item.get("stage"), limit=120),
            item.get("query_id"),
            _clean_text(item.get("message"), limit=500),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def build_research_notes(
    search_plan: dict[str, Any],
    sources: dict[str, Any],
    task_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = task_metadata or {}
    inputs = search_plan.get("inputs") if isinstance(search_plan, dict) else {}
    if not isinstance(inputs, dict):
        inputs = {}
    items = sources.get("items") if isinstance(sources, dict) else []
    if not isinstance(items, list):
        items = []
    queries = _query_entries(search_plan, sources)
    grouped = _group_sources_by_query(queries, items)
    errors = _dedupe_errors(sources.get("errors") if isinstance(sources.get("errors"), list) else [])
    generated_at = _now()
    retrieved_values = [_clean_text(item.get("retrieved_at"), limit=80) for item in items if item.get("retrieved_at")]
    retrieved_at = max(retrieved_values) if retrieved_values else _clean_text(sources.get("created_at"), limit=80)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "task": {
            "task_id": metadata.get("task_id") or sources.get("task_id") or search_plan.get("task_id") or "",
            "title": inputs.get("topic") or inputs.get("title") or metadata.get("title") or "",
            "domain": inputs.get("domain") or metadata.get("domain") or "",
            "audience": inputs.get("audience") or metadata.get("audience") or "",
            "task_type": inputs.get("task_type") or metadata.get("task_type") or "",
            "user_topic": metadata.get("title") or inputs.get("topic") or "",
        },
        "disclaimer": "This is candidate-source summarization only. Search results and snippets are not fact verification.",
        "source_count": len(items),
        "executed_query_count": int(sources.get("executed_query_count") or 0),
        "query_count": len(queries),
        "retrieved_at": retrieved_at,
        "source_groups": grouped,
        "preliminary_note_count": sum(1 for item in items if item.get("preliminary_note")),
        "fallback": sources.get("fallback") or {},
        "diagnostics": sources.get("diagnostics") or {},
        "errors": errors,
    }


def _render_markdown(notes: dict[str, Any]) -> str:
    task = notes.get("task") or {}
    lines: list[str] = [
        "# Phase 2 Research Notes",
        "",
        "> Candidate-source summarization only. Search result titles and snippets are not fact verification.",
        "",
        "## Task",
        "",
        f"* Task ID: {task.get('task_id') or ''}",
        f"* User topic: {task.get('user_topic') or task.get('title') or ''}",
        f"* Domain: {task.get('domain') or ''}",
        f"* Audience: {task.get('audience') or ''}",
        f"* Task type: {task.get('task_type') or ''}",
        "",
        "## Summary",
        "",
        f"* Source count: {notes.get('source_count', 0)}",
        f"* Executed query count: {notes.get('executed_query_count', 0)}",
        f"* Query count: {notes.get('query_count', 0)}",
        f"* Preliminary note count: {notes.get('preliminary_note_count', 0)}",
        f"* retrieved_at: {notes.get('retrieved_at') or ''}",
        f"* generated_at: {notes.get('generated_at') or ''}",
        "",
        "## Query Candidate Sources",
        "",
    ]

    for group in notes.get("source_groups") or []:
        query = group.get("query") or {}
        sources = group.get("sources") or []
        lines.extend(
            [
                f"### {query.get('id') or 'unknown'}",
                "",
                f"* Query: {query.get('query') or ''}",
                f"* Purpose: {query.get('purpose') or ''}",
                f"* Candidate source count: {len(sources)}",
                "",
            ]
        )
        if not sources:
            lines.extend(["No candidate sources were captured for this query.", ""])
            continue
        for source in sources:
            lines.extend(
                [
                    f"#### {source.get('id') or ''}: {source.get('title') or ''}",
                    "",
                    f"* Domain: {source.get('domain') or ''}",
                    f"* URL: {source.get('url') or ''}",
                    f"* retrieved_at: {source.get('retrieved_at') or ''}",
                    f"* Source type: {source.get('source_type') or ''}",
                    f"* Snippet: {source.get('snippet') or ''}",
                    f"* Preliminary notes: {source.get('preliminary_note') or ''}",
                    "",
                ]
            )

    fallback = notes.get("fallback") or {}
    diagnostics = notes.get("diagnostics") or {}
    lines.extend(
        [
            "## Fallback And Diagnostics",
            "",
            f"* Fallback used: {fallback.get('used')}",
            f"* Fallback reason: {fallback.get('reason') or ''}",
            f"* Search executor: {diagnostics.get('executor') or ''}",
            f"* Search provider: {diagnostics.get('provider') or ''}",
            f"* Network enabled: {diagnostics.get('network_enabled')}",
            "",
            "## Errors",
            "",
        ]
    )
    errors = notes.get("errors") or []
    if not errors:
        lines.append("* No recoverable errors recorded.")
    else:
        for item in errors:
            lines.append(
                f"* {item.get('stage') or 'unknown'}: {item.get('query_id') or 'general'} - {item.get('message') or ''}"
            )
            if item.get("detail"):
                lines.append(f"  * Detail: {item.get('detail')}")
    lines.append("")
    return "\n".join(lines)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def summarize_research_sources(
    research_dir: Path,
    task_id: str = "",
    task_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    research_dir.mkdir(parents=True, exist_ok=True)
    search_plan_path = research_dir / "search_plan.json"
    sources_path = research_dir / "sources.json"
    notes_path = research_dir / "research_notes.md"
    notes_json_path = research_dir / "research_notes.json"

    raw_plan, plan_load_errors = _load_json_file(search_plan_path, "search_plan.json")
    raw_sources, source_load_errors = _load_json_file(sources_path, "sources.json")
    search_plan = _normalize_search_plan(raw_plan, plan_load_errors)
    sources = _normalize_sources(raw_sources, task_id, source_load_errors)
    if plan_load_errors:
        sources["errors"] = _dedupe_errors([*plan_load_errors, *(sources.get("errors") or [])])

    notes = build_research_notes(search_plan, sources, task_metadata)
    markdown = _render_markdown(notes)

    notes_path.write_text(markdown, encoding="utf-8")
    _write_json(notes_json_path, notes)

    status = "success"
    if notes.get("errors"):
        status = "completed_with_errors"
    if notes.get("source_count", 0) == 0:
        status = "no_sources"

    return {
        "status": status,
        "search_plan": search_plan,
        "sources": sources,
        "research_notes": notes,
        "research_notes_file": str(notes_path),
        "research_notes_json_file": str(notes_json_path),
        "errors": notes.get("errors") or [],
    }
