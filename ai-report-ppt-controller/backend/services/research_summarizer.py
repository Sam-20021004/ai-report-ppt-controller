from __future__ import annotations

import json
import re
import urllib.parse
from collections import Counter
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


def _normalize_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(str(url or "").strip())
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    path = parsed.path or "/"
    return urllib.parse.urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), path.rstrip("/") or "/", parsed.query, "")
    )


def _audit_source_type(item: dict[str, Any]) -> str:
    source_type = _clean_text(item.get("source_type"), limit=120).lower()
    domain = _clean_text(item.get("domain"), limit=200).lower() or _domain_from_url(str(item.get("url") or ""))
    text = f"{domain} {item.get('title') or ''} {item.get('snippet') or ''}".lower()
    if source_type in {"official", "official_site"} or any(marker in domain for marker in (".gov", ".gov.cn", "iso.org", "iec.ch")):
        return "official_site"
    if source_type in {"paper", "academic"} or any(
        marker in domain
        for marker in (
            ".edu",
            "arxiv.org",
            "doi.org",
            "nature.com",
            "ieee.org",
            "sciencedirect.com",
            "springer.com",
            "pubmed.ncbi.nlm.nih.gov",
        )
    ):
        return "academic"
    if source_type == "news" or any(marker in domain for marker in ("reuters.com", "bloomberg.com", "apnews.com", "bbc.com", "cnbc.com")):
        return "news"
    if source_type == "patent" or any(marker in domain for marker in ("patents.google.com", "wipo.int", "uspto.gov", "cnipa.gov.cn", "lens.org")):
        return "database"
    if source_type in {"industry_report", "company"} or any(marker in text for marker in ("company", "official website", "annual report")):
        return "company"
    return "unknown"


def _audit_flags(item: dict[str, Any], domain_counts: Counter[str]) -> list[str]:
    flags: list[str] = []
    title = _clean_text(item.get("title"), limit=300)
    snippet = _clean_text(item.get("snippet"), limit=1000)
    url = _clean_text(item.get("url"), limit=1000)
    normalized_url = _normalize_url(url)
    domain = _clean_text(item.get("domain"), limit=200) or _domain_from_url(url)
    if not title:
        flags.append("missing_title")
    if not snippet:
        flags.append("missing_snippet")
    elif len(snippet) < 80:
        flags.append("weak_snippet")
    if url and not normalized_url:
        flags.append("non_http_url")
    if url and ("bing.com/ck/" in url.lower() or len(url) > 700):
        flags.append("suspicious_url")
    if domain and domain_counts.get(domain, 0) > 1:
        flags.append("duplicate_domain")
    return flags


def _manual_review_suggestion(item: dict[str, Any]) -> str:
    flags = item.get("audit_flags") or []
    if not item.get("url"):
        return "No usable URL was captured; replace or discard before relying on this source."
    if item.get("needs_manual_review"):
        return "Open the original URL, confirm the page content, publication date, source authority, and whether the snippet supports any later claim."
    if "duplicate_domain" in flags:
        return "Check whether this is an independent source or same-domain repetition before counting evidence weight."
    return "Open the original URL before using any title or snippet as evidence."


def enhance_sources_audit(search_plan: dict[str, Any], sources: dict[str, Any]) -> dict[str, Any]:
    """Add metadata-only audit fields without changing search execution results."""
    enhanced = dict(sources or {})
    raw_items = enhanced.get("items") if isinstance(enhanced.get("items"), list) else []
    domain_counts: Counter[str] = Counter()
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        domain = _clean_text(raw.get("domain"), limit=200) or _domain_from_url(str(raw.get("url") or ""))
        if domain:
            domain_counts[domain] += 1

    items: list[dict[str, Any]] = []
    normalized_urls: set[str] = set()
    flag_counts: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()
    manual_review_count = 0
    provider = (enhanced.get("diagnostics") or {}).get("provider")
    for index, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        source_id = _clean_text(item.get("source_id") or item.get("id"), limit=60) or f"s{index:03d}"
        url = _clean_text(item.get("url"), limit=1000)
        normalized_url = _normalize_url(url)
        domain = _clean_text(item.get("domain"), limit=200) or _domain_from_url(url)
        audit_type = _audit_source_type({**item, "domain": domain})
        flags = _audit_flags({**item, "domain": domain}, domain_counts)
        needs_manual_review = bool(flags) or audit_type == "unknown" or _clean_text(item.get("confidence"), limit=80).lower() == "low"

        item.setdefault("id", source_id)
        item["source_id"] = source_id
        item["normalized_url"] = normalized_url
        item["domain"] = domain
        item.setdefault("source_type", item.get("source_type") or audit_type)
        item["audit_source_type"] = audit_type
        item["audit_flags"] = flags
        item["needs_manual_review"] = needs_manual_review
        item["manual_review_suggestion"] = _manual_review_suggestion(item)
        item["provenance"] = {
            "query_id": item.get("query_id") or "",
            "query": item.get("query") or "",
            "rank": item.get("rank"),
            "retrieved_at": item.get("retrieved_at") or enhanced.get("created_at"),
            "search_provider": provider,
        }
        item["quality"] = {
            "audit_source_type": audit_type,
            "needs_manual_review": needs_manual_review,
            "audit_flags": flags,
        }
        items.append(item)
        if normalized_url:
            normalized_urls.add(normalized_url)
        flag_counts.update(flags)
        type_counts.update([audit_type])
        if needs_manual_review:
            manual_review_count += 1

    queries = search_plan.get("queries") if isinstance(search_plan, dict) else []
    if not isinstance(queries, list):
        queries = []
    source_counts_by_query: Counter[str] = Counter(_clean_text(item.get("query_id"), limit=60) for item in items)
    source_counts_by_query.pop("", None)
    failed_queries = []
    for query in queries:
        if not isinstance(query, dict):
            continue
        query_id = _clean_text(query.get("id"), limit=60)
        if query_id and source_counts_by_query.get(query_id, 0) == 0:
            failed_queries.append(
                {
                    "query_id": query_id,
                    "query": _clean_text(query.get("query"), limit=300),
                    "reason": "No candidate source was captured for this query.",
                }
            )
    for error in enhanced.get("errors") or []:
        if isinstance(error, dict) and error.get("query_id"):
            failed_queries.append(
                {
                    "query_id": error.get("query_id"),
                    "query": error.get("query"),
                    "reason": error.get("message"),
                }
            )

    warnings = []
    diagnostics = enhanced.get("diagnostics") if isinstance(enhanced.get("diagnostics"), dict) else {}
    if isinstance(diagnostics.get("warnings"), list):
        warnings.extend(str(item) for item in diagnostics.get("warnings") if item)
    if manual_review_count:
        warnings.append(f"{manual_review_count} candidate sources require manual review before use as evidence.")

    total_sources = len(items)
    domains_summary = {
        "unique_domain_count": len(domain_counts),
        "top_domains": [
            {"domain": domain, "count": count}
            for domain, count in domain_counts.most_common(10)
        ],
    }
    source_quality_summary = {
        "source_type_counts": dict(type_counts),
        "audit_flag_counts": dict(flag_counts),
        "missing_snippet_count": flag_counts.get("missing_snippet", 0),
        "weak_snippet_count": flag_counts.get("weak_snippet", 0),
        "manual_review_required_count": manual_review_count,
    }
    dedup_summary = {
        **(enhanced.get("deduplication") if isinstance(enhanced.get("deduplication"), dict) else {}),
        "unique_url_count": len(normalized_urls),
        "unique_domain_count": len(domain_counts),
        "duplicate_domain_count": sum(1 for count in domain_counts.values() if count > 1),
    }
    search_fallback_used = bool((enhanced.get("fallback") or {}).get("used"))
    source_execution = {
        "executor": diagnostics.get("executor"),
        "provider": diagnostics.get("provider"),
        "network_enabled": diagnostics.get("network_enabled"),
        "fallback_used": search_fallback_used,
    }

    enhanced["items"] = items
    enhanced["generated_at"] = _now()
    enhanced["source_execution"] = source_execution
    enhanced["search_fallback_used"] = search_fallback_used
    enhanced["total_sources"] = total_sources
    enhanced["unique_url_count"] = len(normalized_urls)
    enhanced["query_count"] = int(enhanced.get("query_count") or len(queries))
    enhanced["executed_query_count"] = int(enhanced.get("executed_query_count") or 0)
    enhanced["domains_summary"] = domains_summary
    enhanced["dedup_summary"] = dedup_summary
    enhanced["failed_queries"] = failed_queries
    enhanced["warnings"] = warnings
    enhanced["source_quality_summary"] = source_quality_summary
    enhanced["audit"] = {
        "method": "metadata_only",
        "disclaimer": "Audit flags are derived from search result metadata only; page bodies were not verified.",
        "flags": dict(flag_counts),
        "failed_queries": failed_queries,
    }
    enhanced["quality"] = source_quality_summary
    enhanced["provenance"] = {
        "search_plan_schema_version": enhanced.get("search_plan_schema_version"),
        "source_schema_version": enhanced.get("schema_version"),
        "generated_from": "search_plan.json and search result metadata",
    }
    return enhanced


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
        "source_id": _clean_text(raw.get("source_id") or raw.get("id"), limit=60) or f"s{index:03d}",
        "query_id": _clean_text(raw.get("query_id"), limit=60),
        "query": _clean_text(raw.get("query"), limit=300),
        "rank": raw.get("rank"),
        "title": title,
        "domain": domain,
        "url": url,
        "normalized_url": _clean_text(raw.get("normalized_url"), limit=1000) or _normalize_url(url),
        "snippet": snippet,
        "source_type": _clean_text(raw.get("source_type") or raw.get("status"), limit=120),
        "audit_source_type": _clean_text(raw.get("audit_source_type"), limit=120),
        "audit_flags": raw.get("audit_flags") if isinstance(raw.get("audit_flags"), list) else [],
        "needs_manual_review": bool(raw.get("needs_manual_review")),
        "manual_review_suggestion": _clean_text(raw.get("manual_review_suggestion"), limit=500),
        "retrieved_at": retrieved_at,
        "language": _clean_text(raw.get("language"), limit=40),
        "confidence": _clean_text(raw.get("confidence"), limit=80),
        "preliminary_note": _preliminary_note(snippet),
    }
    if not item["audit_source_type"]:
        item["audit_source_type"] = _audit_source_type(item)
    if "needs_manual_review" not in raw:
        item["needs_manual_review"] = bool(item["audit_flags"]) or item["audit_source_type"] == "unknown"
    if not item["manual_review_suggestion"]:
        item["manual_review_suggestion"] = _manual_review_suggestion(item)
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


def _coverage_entries(
    queries: list[dict[str, Any]],
    grouped: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_counts = {
        (group.get("query") or {}).get("id") or "unknown": len(group.get("sources") or [])
        for group in grouped
    }
    error_counts: Counter[str] = Counter(
        _clean_text(item.get("query_id"), limit=60)
        for item in errors
        if isinstance(item, dict) and item.get("query_id")
    )
    coverage = []
    for query in queries:
        query_id = query.get("id") or "unknown"
        count = source_counts.get(query_id, 0)
        coverage.append(
            {
                "query_id": query_id,
                "query": query.get("query") or "",
                "purpose": query.get("purpose") or "",
                "candidate_source_count": count,
                "has_candidate_sources": count > 0,
                "failed": error_counts.get(query_id, 0) > 0 or count == 0,
                "error_count": error_counts.get(query_id, 0),
            }
        )
    if not coverage and grouped:
        for group in grouped:
            query = group.get("query") or {}
            count = len(group.get("sources") or [])
            coverage.append(
                {
                    "query_id": query.get("id") or "unknown",
                    "query": query.get("query") or "",
                    "purpose": query.get("purpose") or "",
                    "candidate_source_count": count,
                    "has_candidate_sources": count > 0,
                    "failed": count == 0,
                    "error_count": 0,
                }
            )
    return coverage


def _manual_review_checklist() -> list[str]:
    return [
        "Open each original URL and verify the page body before using it as evidence.",
        "Confirm publication or retrieval date and whether the page is current enough for the task.",
        "Confirm that organization, product, material, device, or process names match the target topic.",
        "Assess source authority and whether the source is official, academic, database, company, news, or unknown.",
        "Check whether multiple results are same-domain reposts or derivative copies.",
        "Decide whether patent, paper, standards, or paid database searches are still needed.",
    ]


def _audit_summary_from_sources(sources: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    quality = sources.get("source_quality_summary") if isinstance(sources.get("source_quality_summary"), dict) else {}
    domains_summary = sources.get("domains_summary") if isinstance(sources.get("domains_summary"), dict) else {}
    return {
        "source_count": len(items),
        "unique_url_count": sources.get("unique_url_count", 0),
        "unique_domain_count": domains_summary.get("unique_domain_count", 0),
        "source_type_counts": quality.get("source_type_counts") or {},
        "audit_flag_counts": quality.get("audit_flag_counts") or {},
        "missing_snippet_count": quality.get("missing_snippet_count", 0),
        "weak_snippet_count": quality.get("weak_snippet_count", 0),
        "manual_review_required_count": quality.get("manual_review_required_count", 0),
        "failed_query_count": len(sources.get("failed_queries") or []),
        "fallback_used": bool((sources.get("fallback") or {}).get("used")),
    }


def _source_quality_notes(audit_summary: dict[str, Any]) -> list[str]:
    source_type_counts = audit_summary.get("source_type_counts") or {}
    return [
        f"Official sources: {source_type_counts.get('official_site', 0)}",
        f"Academic sources: {source_type_counts.get('academic', 0)}",
        f"News sources: {source_type_counts.get('news', 0)}",
        f"Database sources: {source_type_counts.get('database', 0)}",
        f"Company sources: {source_type_counts.get('company', 0)}",
        f"Unknown sources: {source_type_counts.get('unknown', 0)}",
        f"Missing snippet sources: {audit_summary.get('missing_snippet_count', 0)}",
        f"Sources requiring manual review: {audit_summary.get('manual_review_required_count', 0)}",
        f"Queries without candidate sources or with errors: {audit_summary.get('failed_query_count', 0)}",
    ]


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
    coverage = _coverage_entries(queries, grouped, errors)
    audit_summary = _audit_summary_from_sources(sources, items)
    warnings = []
    for item in sources.get("warnings") or []:
        if item:
            warnings.append(_clean_text(item, limit=500))
    diagnostics = sources.get("diagnostics") or {}
    for item in diagnostics.get("warnings") or []:
        cleaned = _clean_text(item, limit=500)
        if cleaned and cleaned not in warnings:
            warnings.append(cleaned)

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
        "summary": {
            "topic": inputs.get("topic") or inputs.get("title") or metadata.get("title") or "",
            "generated_at": generated_at,
            "query_count": len(queries),
            "source_count": len(items),
            "executed_query_count": int(sources.get("executed_query_count") or 0),
            "fallback_used": bool((sources.get("fallback") or {}).get("used")),
            "manual_review_required_count": audit_summary.get("manual_review_required_count", 0),
        },
        "source_count": len(items),
        "executed_query_count": int(sources.get("executed_query_count") or 0),
        "query_count": len(queries),
        "retrieved_at": retrieved_at,
        "coverage": coverage,
        "source_groups": grouped,
        "audit_summary": audit_summary,
        "source_quality_notes": _source_quality_notes(audit_summary),
        "manual_review_checklist": _manual_review_checklist(),
        "warnings": warnings,
        "preliminary_note_count": sum(1 for item in items if item.get("preliminary_note")),
        "fallback": sources.get("fallback") or {},
        "diagnostics": diagnostics,
        "errors": errors,
    }


def _render_markdown(notes: dict[str, Any]) -> str:
    task = notes.get("task") or {}
    summary = notes.get("summary") or {}
    fallback = notes.get("fallback") or {}
    diagnostics = notes.get("diagnostics") or {}
    lines: list[str] = [
        "# Phase 2 Research Notes",
        "",
        "## Disclaimer",
        "",
        "The following notes are based on search result metadata, candidate URLs, titles, and snippets only.",
        "They are not fact verification conclusions and must not be treated as confirmed technical, legal, market, or patent findings until a human reviewer opens and checks the original sources.",
        "",
        "## Task Summary",
        "",
        f"* Task ID: {task.get('task_id') or ''}",
        f"* Topic: {summary.get('topic') or task.get('user_topic') or task.get('title') or ''}",
        f"* Domain: {task.get('domain') or ''}",
        f"* Audience: {task.get('audience') or ''}",
        f"* Task type: {task.get('task_type') or ''}",
        f"* Query count: {summary.get('query_count', notes.get('query_count', 0))}",
        f"* Executed query count: {summary.get('executed_query_count', notes.get('executed_query_count', 0))}",
        f"* Source count: {summary.get('source_count', notes.get('source_count', 0))}",
        f"* Fallback used: {summary.get('fallback_used', fallback.get('used'))}",
        f"* Manual review required count: {summary.get('manual_review_required_count', 0)}",
        f"* retrieved_at: {notes.get('retrieved_at') or ''}",
        f"* generated_at: {summary.get('generated_at') or notes.get('generated_at') or ''}",
        "",
        "## Search Plan Coverage",
        "",
    ]

    coverage = notes.get("coverage") or []
    if not coverage:
        lines.extend(["No query coverage metadata was available.", ""])
    else:
        for item in coverage:
            found = "yes" if item.get("has_candidate_sources") else "no"
            failed = "yes" if item.get("failed") else "no"
            lines.append(
                f"* {item.get('query_id') or 'unknown'} | found: {found} | source_count: {item.get('candidate_source_count', 0)} | failed: {failed} | query: {item.get('query') or ''}"
            )
        lines.append("")

    lines.extend(
        [
            "## Candidate Sources",
            "",
            "Each entry below is a candidate source only. Open the URL and verify page content before using it as evidence.",
            "",
        ]
    )

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
            flags = ", ".join(source.get("audit_flags") or []) or "none"
            lines.extend(
                [
                    f"#### {source.get('source_id') or source.get('id') or ''}: {source.get('title') or '(missing title)'}",
                    "",
                    f"* Domain: {source.get('domain') or ''}",
                    f"* URL: {source.get('url') or ''}",
                    f"* Normalized URL: {source.get('normalized_url') or ''}",
                    f"* Retrieved at: {source.get('retrieved_at') or ''}",
                    f"* Source type: {source.get('audit_source_type') or source.get('source_type') or ''}",
                    f"* Rank: {source.get('rank')}",
                    f"* Audit flags: {flags}",
                    f"* Needs manual review: {source.get('needs_manual_review')}",
                    f"* Manual review suggestion: {source.get('manual_review_suggestion') or ''}",
                    f"* Snippet: {source.get('snippet') or ''}",
                    f"* Preliminary note: {source.get('preliminary_note') or ''}",
                    "",
                ]
            )

    lines.extend(["## Source Quality Notes", ""])
    source_quality_notes = notes.get("source_quality_notes") or []
    if source_quality_notes:
        for item in source_quality_notes:
            lines.append(f"* {item}")
    else:
        lines.append("* No source quality summary was available.")

    lines.extend(["", "## Human Review Checklist", ""])
    for item in notes.get("manual_review_checklist") or []:
        lines.append(f"* {item}")

    lines.extend(["", "## Warnings", ""])
    warnings = notes.get("warnings") or []
    if warnings:
        for item in warnings:
            lines.append(f"* {item}")
    else:
        lines.append("* No warnings recorded.")

    lines.extend(
        [
            "",
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
