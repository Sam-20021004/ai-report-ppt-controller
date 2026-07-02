from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.services.agent_adapters import read_json, write_json
from backend.services.phase2_records import collect_phase2_files, update_phase2_record
from backend.services.phase2_utils import clean_text, language_code, now, output_type, split_terms, unique_items
from backend.services.research_summarizer import summarize_research_sources
from backend.services.web_search import execute_search_plan as execute_web_search_plan
from backend.services.web_search import fallback_sources


def _strategy_flags(request: Any, source_scope: list[str]) -> dict[str, Any]:
    return {
        "web_search": bool(request.enable_web_search),
        "paper_search": bool(request.enable_paper_search),
        "patent_search": bool(request.enable_patent_search),
        "industry_search": bool(request.enable_industry_search),
        "fact_check": bool(request.enable_fact_check),
        "source_scope": source_scope,
        "search_boundary": request.search_boundary or None,
        "use_uploaded_material_only": bool(request.use_uploaded_material_only),
    }


def phase2_inputs(request: Any) -> dict[str, Any]:
    source_scope = split_terms(request.database_scope)
    if not source_scope:
        source_scope = [
            name
            for enabled, name in (
                (request.enable_web_search, "web"),
                (request.enable_paper_search, "paper"),
                (request.enable_patent_search, "patent"),
                (request.enable_industry_search, "industry"),
            )
            if enabled
        ]
    strategy = _strategy_flags(request, source_scope)
    topic = clean_text(request.title, fallback=clean_text(request.domain, fallback="general research topic"))
    return {
        "topic": topic,
        "title": request.title,
        "output_type": output_type(request),
        "task_type": request.task_type,
        "audience": request.audience or None,
        "domain": request.domain or None,
        "keywords": split_terms(request.keywords),
        "regions": split_terms(request.region),
        "time_range": {
            "start": None,
            "end": None,
            "label": request.time_range or None,
        },
        "source_scope": source_scope,
        "language": request.language or None,
        "strategy": strategy,
        "search_boundary": request.search_boundary or None,
        "user_outline_present": bool(request.user_outline),
    }


def _looks_academic(inputs: dict[str, Any]) -> bool:
    text = " ".join(
        [
            inputs.get("topic") or "",
            inputs.get("domain") or "",
            " ".join(inputs.get("keywords") or []),
            inputs.get("search_boundary") or "",
        ]
    ).lower()
    markers = (
        "ai",
        "algorithm",
        "model",
        "research",
        "paper",
        "academic",
        "\u8bba\u6587",
        "\u7b97\u6cd5",
        "\u6a21\u578b",
        "\u6280\u672f",
        "\u673a\u5236",
    )
    return any(marker in text for marker in markers)


def _requires_recent_sources(inputs: dict[str, Any]) -> bool:
    text = " ".join(
        [
            inputs.get("time_range", {}).get("label") or "",
            inputs.get("search_boundary") or "",
            " ".join(inputs.get("keywords") or []),
        ]
    ).lower()
    markers = ("latest", "recent", "trend", "2024", "2025", "2026", "\u6700\u65b0", "\u8fd1\u671f", "\u8d8b\u52bf", "\u8fdb\u5c55")
    return bool(text) and any(marker in text for marker in markers)


def _preferred_source_types(source_scope: list[str], requires_authoritative: bool) -> list[str]:
    source_types: list[str] = []
    scope_text = " ".join(source_scope).lower()
    if requires_authoritative or "web" in scope_text:
        source_types.extend(["official", "industry_report"])
    if "paper" in scope_text or "\u8bba\u6587" in scope_text:
        source_types.append("paper")
    if "patent" in scope_text or "\u4e13\u5229" in scope_text:
        source_types.append("patent")
    if "industry" in scope_text or "market" in scope_text or "\u4ea7\u4e1a" in scope_text:
        source_types.extend(["industry_report", "news"])
    if not source_types:
        source_types.extend(["official", "industry_report", "news"])
    return unique_items(source_types)


def _query_text(language: str, topic: str, domain: str, keywords: list[str], terms: list[str]) -> str:
    parts = [topic]
    if domain and domain.lower() not in topic.lower():
        parts.append(domain)
    parts.extend(keywords[:3])
    parts.extend(terms)
    return " ".join(unique_items(parts))


def _make_query(
    index: int,
    query: str,
    language: str,
    purpose: str,
    priority: int,
    expected_source_types: list[str],
    freshness: str,
    notes: str,
    derived_from: list[str],
) -> dict[str, Any]:
    return {
        "id": f"q{index:03d}",
        "query": query,
        "language": language,
        "purpose": purpose,
        "priority": priority,
        "expected_source_types": unique_items(expected_source_types),
        "freshness": freshness,
        "notes": notes,
        "derived_from": derived_from,
    }


def _build_search_queries(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    language = language_code(inputs.get("language"))
    topic = clean_text(inputs.get("topic"), fallback="general research topic")
    domain = clean_text(inputs.get("domain"))
    keywords = inputs.get("keywords") or []
    regions = inputs.get("regions") or []
    source_scope = inputs.get("source_scope") or []
    requires_recent = _requires_recent_sources(inputs)
    academic = _looks_academic(inputs)
    preferred = _preferred_source_types(source_scope, True)

    zh = language == "zh"
    candidates = [
        {
            "terms": ["\u80cc\u666f", "\u5b9a\u4e49", "\u6982\u5ff5"] if zh else ["background", "definition", "overview"],
            "purpose": "background",
            "priority": 1,
            "source_types": ["official", "industry_report"],
            "freshness": "stable",
            "notes": "Establish baseline concepts and scope.",
            "derived_from": ["topic", "domain"],
        },
        {
            "terms": ["\u6700\u65b0\u8fdb\u5c55", "\u8d8b\u52bf", "2024", "2025", "2026"] if zh else ["latest progress", "trend", "2024", "2025", "2026"],
            "purpose": "recent_progress",
            "priority": 2,
            "source_types": ["news", "industry_report", "official"],
            "freshness": "recent" if requires_recent else "stable",
            "notes": "Capture recent movement without treating results as verified sources.",
            "derived_from": ["topic", "time_range", "keywords"],
        },
        {
            "terms": ["\u6280\u672f\u7ec6\u8282", "\u673a\u5236", "\u65b9\u6cd5"] if zh else ["technical detail", "mechanism", "method"],
            "purpose": "technical_detail",
            "priority": 3,
            "source_types": ["paper", "official"],
            "freshness": "stable",
            "notes": "Collect technical mechanism and implementation detail candidates.",
            "derived_from": ["topic", "domain", "keywords"],
        },
        {
            "terms": ["\u6848\u4f8b", "\u5bf9\u6807", "\u7ade\u54c1", "benchmark"] if zh else ["case study", "competitor", "benchmark"],
            "purpose": "benchmark",
            "priority": 4,
            "source_types": ["industry_report", "official", "news"],
            "freshness": "stable",
            "notes": "Identify comparable cases and benchmark references.",
            "derived_from": ["topic", "audience", "output_type"],
        },
        {
            "terms": ["\u653f\u7b56", "\u5e02\u573a", "\u4ea7\u4e1a"] if zh else ["policy", "market", "industry"],
            "purpose": "market",
            "priority": 5,
            "source_types": ["official", "industry_report", "news"],
            "freshness": "recent" if requires_recent else "stable",
            "notes": "Check policy, market, and industry context when relevant.",
            "derived_from": ["topic", "source_scope", "strategy"],
        },
    ]

    if academic or "paper" in " ".join(source_scope).lower():
        candidates.append(
            {
                "terms": ["survey", "review", "paper", "research"],
                "purpose": "technical_detail",
                "priority": 6,
                "source_types": ["paper"],
                "freshness": "recent" if requires_recent else "stable",
                "notes": "English paper-oriented query for academic or technical tasks.",
                "derived_from": ["topic", "domain", "keywords", "strategy.paper_search"],
                "language": "en",
            }
        )

    if "patent" in " ".join(source_scope).lower() or "\u4e13\u5229" in " ".join(source_scope):
        candidates.append(
            {
                "terms": ["\u4e13\u5229", "\u5e03\u5c40", "\u7533\u8bf7\u4eba"] if zh else ["patent", "assignee", "landscape"],
                "purpose": "patent",
                "priority": 7,
                "source_types": ["patent"],
                "freshness": "stable",
                "notes": "Patent-specific planning query enabled by source scope.",
                "derived_from": ["topic", "strategy.patent_search", "source_scope"],
            }
        )

    if regions:
        region_terms = regions[:2] + (["\u5730\u533a", "\u653f\u7b56", "\u5e02\u573a"] if zh else ["regional", "policy", "market"])
        candidates.append(
            {
                "terms": region_terms,
                "purpose": "policy",
                "priority": 8,
                "source_types": ["official", "industry_report", "news"],
                "freshness": "recent" if requires_recent else "stable",
                "notes": "Region-specific query derived from task region input.",
                "derived_from": ["topic", "regions"],
            }
        )

    queries = []
    seen = set()
    for candidate in candidates:
        query_language = candidate.get("language") or language
        query = _query_text(query_language, topic, domain, keywords, candidate["terms"])
        key = (query.lower(), candidate["purpose"])
        if key in seen:
            continue
        seen.add(key)
        source_types = candidate["source_types"] or preferred
        queries.append(
            _make_query(
                len(queries) + 1,
                query,
                query_language,
                candidate["purpose"],
                candidate["priority"],
                source_types,
                candidate["freshness"],
                candidate["notes"],
                candidate["derived_from"],
            )
        )
    return queries[:8]


def build_search_plan(record: Any, created_at: str) -> dict[str, Any]:
    inputs = phase2_inputs(record.request)
    queries = _build_search_queries(inputs)
    if len(queries) < 5:
        raise ValueError("Search planner generated fewer than 5 queries.")
    source_scope = inputs.get("source_scope") or []
    requires_authoritative = bool(inputs.get("strategy", {}).get("fact_check", True))
    requires_recent = _requires_recent_sources(inputs)
    preferred_source_types = _preferred_source_types(source_scope, requires_authoritative)
    warnings = []
    if not clean_text(inputs.get("title")):
        warnings.append("Task title is empty; planner used a conservative fallback topic.")
    return {
        "schema_version": "phase2.search_plan.v1",
        "task_id": record.task_id,
        "created_at": created_at,
        "inputs": inputs,
        "plan_summary": {
            "goal": f"Plan auditable research for {inputs.get('output_type')} output.",
            "language": language_code(inputs.get("language")),
            "estimated_query_count": len(queries),
            "requires_recent_sources": requires_recent,
            "requires_authoritative_sources": requires_authoritative,
        },
        "queries": queries,
        "source_selection_policy": {
            "preferred_source_types": preferred_source_types,
            "avoid_source_types": ["content_farm", "unsourced_social_post", "advertorial"],
            "min_source_count": max(5, len(queries)),
            "deduplication": True,
        },
        "assumptions": [
            "This is a local rule-based search plan; no external API, web search, or crawler was used.",
            "sources.json remains empty until Phase 2 task 3 executes search.",
        ],
        "fallback": {
            "used": False,
            "reason": None,
        },
        "diagnostics": {
            "planner": "local_rule_based",
            "fallback_used": False,
            "warnings": warnings,
        },
    }


def fallback_search_plan(record: Any, created_at: str, exc: Exception) -> dict[str, Any]:
    inputs = {
        "topic": clean_text(getattr(record.request, "title", None), fallback="general research topic"),
        "title": getattr(record.request, "title", "") or "",
        "output_type": output_type(record.request),
        "task_type": getattr(record.request, "task_type", "ppt"),
        "audience": getattr(record.request, "audience", None),
        "domain": getattr(record.request, "domain", None),
        "keywords": [],
        "regions": [],
        "time_range": {"start": None, "end": None, "label": None},
        "source_scope": ["web"],
        "language": getattr(record.request, "language", None),
        "strategy": {},
    }
    language = language_code(inputs.get("language"))
    topic = inputs["topic"]
    purposes = ["background", "recent_progress", "technical_detail", "benchmark", "market"]
    terms = [
        ["background", "definition"],
        ["latest", "progress"],
        ["technical", "method"],
        ["case", "benchmark"],
        ["market", "policy"],
    ]
    queries = [
        _make_query(
            index + 1,
            " ".join([topic, *term]),
            language,
            purpose,
            index + 1,
            ["official", "industry_report"],
            "stable",
            "Fallback query generated after local planner failure.",
            ["fallback_topic"],
        )
        for index, (purpose, term) in enumerate(zip(purposes, terms))
    ]
    return {
        "schema_version": "phase2.search_plan.v1",
        "task_id": record.task_id,
        "created_at": created_at,
        "inputs": inputs,
        "plan_summary": {
            "goal": "Fallback auditable search plan.",
            "language": language,
            "estimated_query_count": len(queries),
            "requires_recent_sources": False,
            "requires_authoritative_sources": True,
        },
        "queries": queries,
        "source_selection_policy": {
            "preferred_source_types": ["official", "industry_report"],
            "avoid_source_types": ["content_farm", "unsourced_social_post", "advertorial"],
            "min_source_count": len(queries),
            "deduplication": True,
        },
        "assumptions": [
            "Planner failed and generated a conservative fallback plan.",
        ],
        "fallback": {
            "used": True,
            "reason": str(exc),
        },
        "diagnostics": {
            "planner": "local_rule_based",
            "fallback_used": True,
            "warnings": [str(exc)],
        },
    }


def write_phase2_contract_artifacts(record: Any, workspace: Path, storage_dir: Path, task_root: Path) -> dict[str, Any]:
    created_at = now()
    planner_errors: list[dict[str, Any]] = []
    try:
        search_plan = build_search_plan(record, created_at)
    except Exception as exc:
        search_plan = fallback_search_plan(record, created_at, exc)
        planner_errors.append(
            {
                "stage": "search_plan",
                "message": "Local rule-based search planning failed; fallback plan was generated.",
                "detail": str(exc),
                "recoverable": True,
            }
        )

    search_notice = {
        "stage": "web_search",
        "message": "Real web search is not executed in Phase 2 task 2.",
        "detail": "sources.json intentionally contains no real sources; search execution is reserved for Phase 2 task 3.",
        "recoverable": True,
    }
    sources = {
        "schema_version": "phase2.sources.v1",
        "task_id": record.task_id,
        "created_at": created_at,
        "search_plan_schema_version": search_plan.get("schema_version"),
        "query_count": len(search_plan.get("queries") or []),
        "executed_query_count": 0,
        "items": [],
        "deduplication": {
            "enabled": True,
            "input_count": 0,
            "output_count": 0,
            "removed_count": 0,
        },
        "errors": [search_notice],
        "fallback": {
            "used": True,
            "reason": "Search execution has not started; no real sources are fabricated.",
        },
        "diagnostics": {
            "executor": "not_started",
            "provider": None,
            "network_enabled": False,
            "max_results_per_query": 0,
            "max_total_results": 0,
            "total_results": 0,
            "warnings": ["Search execution has not started."],
        },
    }

    research_dir = workspace / "research"
    search_plan_path = research_dir / "search_plan.json"
    sources_path = research_dir / "sources.json"
    write_json(search_plan_path, search_plan)
    write_json(sources_path, sources)

    phase2_files = collect_phase2_files(record.task_id, research_dir, storage_dir, task_root)
    update_phase2_record(record, search_plan, sources, phase2_files, planner_errors)
    return {
        "search_plan": search_plan,
        "sources": sources,
        "phase2_files": phase2_files,
        "planner_errors": planner_errors,
    }


def load_or_rebuild_search_plan(record: Any, search_plan_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    created_at = now()
    planner_errors: list[dict[str, Any]] = []
    warning = ""
    if search_plan_path.exists():
        try:
            search_plan = read_json(search_plan_path, {})
            if not isinstance(search_plan, dict):
                raise ValueError("search_plan.json is not an object.")
            if not isinstance(search_plan.get("queries"), list) or not search_plan.get("queries"):
                raise ValueError("search_plan.json does not contain executable queries.")
            return search_plan, planner_errors
        except Exception as exc:
            warning = f"Existing search_plan.json could not be read; regenerated from task input: {exc}"
    else:
        warning = "search_plan.json was missing; regenerated from task input before search execution."

    planner_errors.append(
        {
            "query_id": None,
            "query": None,
            "stage": "search_plan",
            "message": warning,
            "recoverable": True,
        }
    )
    try:
        search_plan = build_search_plan(record, created_at)
        search_plan.setdefault("diagnostics", {}).setdefault("warnings", []).append(warning)
    except Exception as exc:
        search_plan = fallback_search_plan(record, created_at, exc)
        planner_errors.append(
            {
                "query_id": None,
                "query": None,
                "stage": "search_plan",
                "message": "Search plan regeneration failed; fallback search plan was generated.",
                "detail": str(exc),
                "recoverable": True,
            }
        )
    return search_plan, planner_errors


def execute_phase2_search_plan(record: Any, workspace: Path, settings: Any, storage_dir: Path, task_root: Path) -> dict[str, Any]:
    research_dir = workspace / "research"
    search_plan_path = research_dir / "search_plan.json"
    sources_path = research_dir / "sources.json"

    search_plan, planner_errors = load_or_rebuild_search_plan(record, search_plan_path)
    write_json(search_plan_path, search_plan)
    try:
        sources = execute_web_search_plan(
            search_plan,
            task_id=record.task_id,
            chrome_host=settings.chrome_host,
            chrome_port=settings.chrome_port,
        )
    except Exception as exc:
        sources = fallback_sources(search_plan, record.task_id, f"Unexpected web search executor failure: {exc}")

    if planner_errors:
        sources["errors"] = [*planner_errors, *(sources.get("errors") or [])]
        warnings = sources.setdefault("diagnostics", {}).setdefault("warnings", [])
        warnings.extend(item["message"] for item in planner_errors)

    write_json(sources_path, sources)

    phase2_files = collect_phase2_files(record.task_id, research_dir, storage_dir, task_root)
    update_phase2_record(record, search_plan, sources, phase2_files, planner_errors)
    return {
        "search_plan": search_plan,
        "sources": sources,
        "phase2_files": phase2_files,
        "planner_errors": planner_errors,
    }


def phase2_task_metadata(record: Any) -> dict[str, Any]:
    request = record.request
    return {
        "task_id": record.task_id,
        "title": request.title,
        "domain": request.domain,
        "audience": request.audience,
        "task_type": request.task_type,
    }


def summarize_phase2_research(
    record: Any,
    workspace: Path,
    storage_dir: Path,
    task_root: Path,
    planner_errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    research_dir = workspace / "research"
    result = summarize_research_sources(
        research_dir,
        task_id=record.task_id,
        task_metadata=phase2_task_metadata(record),
    )
    phase2_files = collect_phase2_files(record.task_id, research_dir, storage_dir, task_root)
    update_phase2_record(
        record,
        result.get("search_plan") or {},
        result.get("sources") or {},
        phase2_files,
        planner_errors,
        result,
    )
    return {
        "status": result.get("status"),
        "research_notes_file": result.get("research_notes_file"),
        "research_notes_json_file": result.get("research_notes_json_file"),
        "source_count": (result.get("research_notes") or {}).get("source_count", 0),
        "executed_query_count": (result.get("research_notes") or {}).get("executed_query_count", 0),
        "preliminary_note_count": (result.get("research_notes") or {}).get("preliminary_note_count", 0),
        "error_count": len(result.get("errors") or []),
        "phase2_files": phase2_files,
    }
