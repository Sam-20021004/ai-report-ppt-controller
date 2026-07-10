from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.services.phase2_artifacts import source_review_key


REPORT_OUTLINE_SCHEMA_VERSION = "phase3.report_outline.v1"
ELIGIBLE_REVIEW_STATUSES = {"approved", "unreviewed"}
KNOWN_REVIEW_STATUSES = {*ELIGIBLE_REVIEW_STATUSES, "rejected", "needs_followup"}

PURPOSE_TITLES = {
    "background": "Background and Scope",
    "recent_progress": "Recent Progress",
    "technical_detail": "Technical Details",
    "benchmark": "Benchmarks and Comparisons",
    "market": "Market and Industry Context",
    "policy": "Policy and Regional Context",
    "patent": "Patent Landscape",
    "evidence": "Source Evidence",
}


def report_outline_path(workspace: Path) -> Path:
    return workspace / "draft" / "report_outline.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_input_object(path: Path, warnings: list[str]) -> dict[str, Any]:
    if not path.exists():
        warnings.append(f"{path.name} is missing; conservative fallback data was used.")
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(f"{path.name} could not be read; conservative fallback data was used: {exc}")
        return {}
    if not isinstance(payload, dict):
        warnings.append(f"{path.name} is not a JSON object; conservative fallback data was used.")
        return {}
    return payload


def _source_id(source: dict[str, Any]) -> str:
    return str(source.get("source_id") or source.get("id") or "").strip()


def _dedupe_key(source: dict[str, Any]) -> str:
    url = str(source.get("normalized_url") or source.get("url") or "").strip().lower().rstrip("/")
    if url:
        return f"url:{url}"
    title = " ".join(str(source.get("title") or "").split()).strip().lower()
    if title:
        return f"title:{title}"
    source_id = _source_id(source)
    return f"source_id:{source_id}" if source_id else ""


def _review_status(review: dict[str, Any] | None) -> str:
    status = str((review or {}).get("review_status") or "unreviewed").strip()
    return status if status in KNOWN_REVIEW_STATUSES else "unreviewed"


def _purpose_title(purpose: str) -> str:
    normalized = purpose.strip().lower() or "evidence"
    return PURPOSE_TITLES.get(normalized, normalized.replace("_", " ").title())


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _note_sources(research_notes: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for group in _list_of_dicts(research_notes.get("source_groups")):
        for source in _list_of_dicts(group.get("sources")):
            source_id = _source_id(source)
            if source_id and source_id not in indexed:
                indexed[source_id] = source
    return indexed


def _source_text(
    source: dict[str, Any],
    note_source: dict[str, Any] | None,
) -> tuple[str, str, str, bool]:
    candidates = (
        (note_source or {}, "research/research_notes.json", "preliminary_note"),
        (note_source or {}, "research/research_notes.json", "snippet"),
        (note_source or {}, "research/research_notes.json", "claim_supported"),
        (source, "research/sources.json", "snippet"),
        (source, "research/sources.json", "claim_supported"),
        (source, "research/sources.json", "title"),
    )
    for payload, artifact, field in candidates:
        text = str(payload.get(field) or "").strip()
        if text:
            return text, artifact, field, True
    return f"Source {_source_id(source)} requires content review.", "research/sources.json", "source_id", False


def _unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _figure_needs(search_plan: dict[str, Any], research_notes: dict[str, Any]) -> list[str]:
    candidates: list[Any] = []
    for payload in (search_plan, research_notes):
        value = payload.get("figures_needed")
        if isinstance(value, list):
            candidates.extend(value)
    return _unique_strings(candidates)


def _provenance(
    source_id: str,
    review: dict[str, Any],
    text_artifact: str,
    text_field: str,
) -> list[dict[str, str]]:
    entries = [{"artifact": "research/sources.json", "record_id": source_id, "field": "source_id"}]
    if review:
        entries.append(
            {
            "artifact": "research/source_review.json",
            "record_id": str(review.get("source_key") or source_id),
            "field": "review_status",
            }
        )
    text_entry = {"artifact": text_artifact, "record_id": source_id, "field": text_field}
    if text_entry not in entries:
        entries.append(text_entry)
    return entries


def _build_outline(
    record: Any,
    search_plan: dict[str, Any],
    sources: dict[str, Any],
    research_notes: dict[str, Any],
    source_review: dict[str, Any],
    input_warnings: list[str],
) -> dict[str, Any]:
    request = record.request
    active_reviews = [
        item
        for item in _list_of_dicts(source_review.get("items"))
        if not item.get("stale")
    ]
    reviews_by_source_id = {
        str(item.get("source_id")): item
        for item in active_reviews
        if item.get("source_id")
    }
    reviews_by_source_key = {
        str(item.get("source_key")): item
        for item in active_reviews
        if item.get("source_key")
    }
    note_sources = _note_sources(research_notes)
    queries = _list_of_dicts(search_plan.get("queries"))
    query_by_id = {str(query.get("id")): query for query in queries if query.get("id")}
    query_order = {query_id: index for index, query_id in enumerate(query_by_id)}

    evidence: list[dict[str, Any]] = []
    unusable_sources: list[dict[str, Any]] = []
    seen_source_keys: set[str] = set()
    for source_index, source in enumerate(_list_of_dicts(sources.get("items")), start=1):
        source_id = _source_id(source)
        if not source_id:
            continue
        dedupe_key = _dedupe_key(source)
        if dedupe_key and dedupe_key in seen_source_keys:
            continue
        if dedupe_key:
            seen_source_keys.add(dedupe_key)
        stable_source_key = source_review_key(source, source_index)
        review = reviews_by_source_key.get(stable_source_key) or reviews_by_source_id.get(source_id, {})
        status = _review_status(review)
        if status not in ELIGIBLE_REVIEW_STATUSES:
            continue
        text, text_artifact, text_field, has_usable_text = _source_text(source, note_sources.get(source_id))
        if not has_usable_text:
            unusable_sources.append(
                {
                    "reason": "source_without_usable_text",
                    "source_id": source_id,
                    "source_key": str(review.get("source_key") or stable_source_key),
                    "title": str(source.get("title") or "").strip(),
                    "review_status": status,
                    "provenance": _provenance(source_id, review, text_artifact, text_field),
                }
            )
            continue
        query_id = str(source.get("query_id") or (note_sources.get(source_id) or {}).get("query_id") or "")
        query = query_by_id.get(query_id, {})
        purpose = str(query.get("purpose") or "evidence").strip() or "evidence"
        evidence.append(
            {
                "source": source,
                "source_id": source_id,
                "source_key": str(review.get("source_key") or stable_source_key),
                "review_status": status,
                "query_id": query_id,
                "purpose": purpose,
                "query_order": query_order.get(query_id, len(query_order)),
                "key_point_text": text,
                "has_usable_text": has_usable_text,
                "provenance": _provenance(source_id, review, text_artifact, text_field),
            }
        )
    evidence.sort(
        key=lambda item: (
            item["query_order"],
            0 if item["review_status"] == "approved" else 1,
            item["source_id"],
        )
    )

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in evidence:
        grouped.setdefault(item["purpose"], []).append(item)

    sections: list[dict[str, Any]] = []
    for section_index, (purpose, items) in enumerate(grouped.items(), start=1):
        items.sort(
            key=lambda item: (
                0 if item["review_status"] == "approved" else 1,
                item["query_order"],
                item["source_id"],
            )
        )
        statuses = {item["review_status"] for item in items}
        all_have_usable_text = all(item["has_usable_text"] for item in items)
        if statuses == {"approved"} and all_have_usable_text:
            confidence, section_review = "high", "approved"
        elif "approved" in statuses and all_have_usable_text:
            confidence, section_review = "medium", "needs_review"
        else:
            confidence, section_review = "low", "needs_review"
        supporting_sources = [
            {
                "source_id": item["source_id"],
                "source_key": item["source_key"],
                "title": str(item["source"].get("title") or "").strip(),
                "url": str(item["source"].get("url") or "").strip(),
                "review_status": item["review_status"],
                "provenance": item["provenance"],
            }
            for item in items
        ]
        sections.append(
            {
                "section_id": str(section_index),
                "title": _purpose_title(purpose),
                "purpose": purpose,
                "key_points": _unique_strings([item["key_point_text"] for item in items]),
                "supporting_sources": supporting_sources,
                "figures_needed": [],
                "confidence": confidence,
                "review_status": section_review,
            }
        )

    missing_information = [
        {
            "reason": "needs_followup",
            "source_id": source_id,
            "source_key": str(review.get("source_key") or ""),
            "title": str(review.get("title") or "").strip(),
            "review_note": str(review.get("review_note") or "").strip(),
            "provenance": {
                "artifact": "research/source_review.json",
                "record_id": str(review.get("source_key") or source_id),
                "field": "review_status",
            },
        }
        for source_id, review in reviews_by_source_id.items()
        if _review_status(review) == "needs_followup"
    ]
    missing_information.extend(unusable_sources)
    if not sections:
        missing_information.append(
            {
                "reason": "no_eligible_sources",
                "detail": "No active approved or unreviewed source is available for a traceable report section.",
            }
        )

    title = str(request.title or "").strip()
    audience = str(request.audience or "").strip()
    domain = str(request.domain or "").strip()
    objective = f"Plan a traceable {domain or 'research'} report on {title} for {audience or 'the intended audience'}."
    figures = _figure_needs(search_plan, research_notes)
    return {
        "schema_version": REPORT_OUTLINE_SCHEMA_VERSION,
        "task_id": str(record.task_id),
        "generated_at": _now(),
        "title": title,
        "objective": objective,
        "audience": audience,
        "sections": sections,
        "recommended_figures": figures,
        "missing_information": missing_information,
        "generation_notes": (
            "Generated deterministically from existing Phase 2 artifacts. Approved sources are prioritized; "
            "unreviewed sources remain explicitly marked for review."
        ),
        "provenance": {
            "inputs": [
                "research/search_plan.json",
                "research/sources.json",
                "research/research_notes.json",
                "research/source_review.json",
                "state/status.json",
            ],
            "schema_versions": {
                "search_plan": search_plan.get("schema_version"),
                "sources": sources.get("schema_version"),
                "research_notes": research_notes.get("schema_version"),
                "source_review": source_review.get("version"),
            },
            "input_warnings": input_warnings,
        },
    }


def _validate_outline(outline: dict[str, Any]) -> None:
    if outline.get("schema_version") != REPORT_OUTLINE_SCHEMA_VERSION:
        raise ValueError("report_outline.json has an invalid schema version.")
    for section in _list_of_dicts(outline.get("sections")):
        supporting_sources = _list_of_dicts(section.get("supporting_sources"))
        if not supporting_sources:
            raise ValueError(f"Section {section.get('section_id')} has no supporting sources.")
        for source in supporting_sources:
            if source.get("review_status") not in ELIGIBLE_REVIEW_STATUSES:
                raise ValueError(f"Section {section.get('section_id')} contains an ineligible source.")
            if not source.get("provenance"):
                raise ValueError(f"Source {source.get('source_id')} has no provenance.")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def generate_report_outline(record: Any, workspace: Path) -> dict[str, Any]:
    research_dir = workspace / "research"
    input_warnings: list[str] = []
    search_plan = _read_input_object(research_dir / "search_plan.json", input_warnings)
    sources = _read_input_object(research_dir / "sources.json", input_warnings)
    research_notes = _read_input_object(research_dir / "research_notes.json", input_warnings)
    source_review = _read_input_object(research_dir / "source_review.json", input_warnings)
    outline = _build_outline(record, search_plan, sources, research_notes, source_review, input_warnings)
    _validate_outline(outline)
    _atomic_write_json(report_outline_path(workspace), outline)
    return outline
