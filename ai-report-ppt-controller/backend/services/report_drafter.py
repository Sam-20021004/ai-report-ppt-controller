from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.services.phase2_artifacts import source_review_key


REPORT_DRAFT_SCHEMA = "phase3.report_draft.v1"
REPORT_OUTLINE_SCHEMA = "phase3.report_outline.v1"
BODY_REVIEW_STATUSES = {"approved", "unreviewed"}
KNOWN_REVIEW_STATUSES = {*BODY_REVIEW_STATUSES, "rejected", "needs_followup"}


def report_draft_path(workspace: Path) -> Path:
    return workspace / "draft" / "report_draft.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _warning(
    code: str,
    artifact: str,
    message: str,
    *,
    section_id: str = "",
    source_key: str = "",
) -> dict[str, str]:
    item = {"code": code, "artifact": artifact, "message": message}
    if section_id:
        item["section_id"] = section_id
    if source_key:
        item["source_key"] = source_key
    return item


def _read_object(path: Path, artifact: str, warnings: list[dict[str, str]]) -> dict[str, Any]:
    if not path.exists():
        warnings.append(_warning("missing_input", artifact, f"{artifact} is missing; empty fallback data was used."))
        return {}
    try:
        raw = path.read_text(encoding="utf-8-sig")
        if not raw.strip():
            raise ValueError("file is empty")
        payload = json.loads(raw)
    except (OSError, ValueError, json.JSONDecodeError):
        warnings.append(_warning("invalid_input", artifact, f"{artifact} could not be read as a JSON object."))
        return {}
    if not isinstance(payload, dict):
        warnings.append(_warning("invalid_input_type", artifact, f"{artifact} is not a JSON object; empty fallback data was used."))
        return {}
    return payload


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _clean_text(value: Any, limit: int = 4000) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _source_id(source: dict[str, Any]) -> str:
    return _clean_text(source.get("source_id") or source.get("id"), 120)


def _review_status(review: dict[str, Any] | None) -> str:
    status = _clean_text((review or {}).get("review_status"), 80) or "unreviewed"
    return status if status in KNOWN_REVIEW_STATUSES else "unreviewed"


def _stable_append(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _source_indexes(sources: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_key: dict[str, dict[str, Any]] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for index, source in enumerate(_list_of_dicts(sources.get("items")), start=1):
        source_id = _source_id(source)
        key = source_review_key(source, index)
        if key and key not in by_key:
            by_key[key] = source
        if source_id and source_id not in by_id:
            by_id[source_id] = source
    return by_key, by_id


def _review_indexes(reviews: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    active = [item for item in _list_of_dicts(reviews.get("items")) if not item.get("stale")]
    by_key = {
        _clean_text(item.get("source_key"), 160): item
        for item in active
        if _clean_text(item.get("source_key"), 160)
    }
    by_id = {
        _clean_text(item.get("source_id"), 120): item
        for item in active
        if _clean_text(item.get("source_id"), 120)
    }
    return by_key, by_id


def _note_index(notes: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for group in _list_of_dicts(notes.get("source_groups")):
        for source in _list_of_dicts(group.get("sources")):
            source_id = _source_id(source)
            if source_id and source_id not in result:
                result[source_id] = source
    return result


def _select_text(
    source: dict[str, Any],
    note: dict[str, Any] | None,
) -> tuple[str, dict[str, str] | None]:
    candidates = (
        (note or {}, "research/research_notes.json", "preliminary_note"),
        (note or {}, "research/research_notes.json", "snippet"),
        (note or {}, "research/research_notes.json", "claim_supported"),
        (source, "research/sources.json", "snippet"),
        (source, "research/sources.json", "claim_supported"),
    )
    for payload, artifact, field in candidates:
        text = _clean_text(payload.get(field))
        if text:
            return text, {"artifact": artifact, "field": field, "record_id": _source_id(source)}
    return "", None


def _supporting_source(
    source_key: str,
    source: dict[str, Any],
    status: str,
    text_provenance: dict[str, str],
) -> dict[str, Any]:
    return {
        "source_key": source_key,
        "source_id": _source_id(source),
        "title": _clean_text(source.get("title"), 500),
        "url": _clean_text(source.get("url"), 1200),
        "review_status": status,
        "text_provenance": text_provenance,
    }


def _build_draft(
    record: Any,
    outline: dict[str, Any],
    sources: dict[str, Any],
    notes: dict[str, Any],
    reviews: dict[str, Any],
    input_warnings: list[dict[str, str]],
) -> dict[str, Any]:
    sources_by_key, sources_by_id = _source_indexes(sources)
    reviews_by_key, reviews_by_id = _review_indexes(reviews)
    notes_by_id = _note_index(notes)
    sections: list[dict[str, Any]] = []
    source_index_by_key: dict[str, dict[str, Any]] = {}
    included_source_keys: list[str] = []
    excluded_source_keys: list[str] = []
    all_warnings: list[dict[str, str]] = list(input_warnings)

    if isinstance(outline.get("sections"), list):
        raw_sections = outline["sections"]
    else:
        item = _warning(
            "invalid_outline_sections",
            "draft/report_outline.json",
            "Outline sections is missing or is not an array; an empty draft was generated.",
        )
        input_warnings.append(item)
        all_warnings.append(item)
        raw_sections = []
    for raw_position, outline_section in enumerate(raw_sections, start=1):
        if not isinstance(outline_section, dict):
            all_warnings.append(
                _warning(
                    "invalid_outline_section",
                    "draft/report_outline.json",
                    f"Outline section at position {raw_position} is not an object and was skipped.",
                )
            )
            continue
        section_order = len(sections) + 1
        section_id = f"section-{section_order:03d}"
        outline_section_id = _clean_text(outline_section.get("section_id"), 120) or str(raw_position)
        section_warnings: list[dict[str, str]] = []
        blocks: list[dict[str, Any]] = []
        section_sources: list[dict[str, Any]] = []
        section_source_keys: list[str] = []
        seen_section_keys: set[str] = set()

        raw_outline_sources = outline_section.get("supporting_sources")
        if isinstance(raw_outline_sources, list):
            outline_sources = raw_outline_sources
        else:
            item = _warning(
                "invalid_outline_sources",
                "draft/report_outline.json",
                "Section supporting_sources is missing or is not an array.",
                section_id=outline_section_id,
            )
            section_warnings.append(item)
            all_warnings.append(item)
            outline_sources = []
        for source_position, outline_source in enumerate(outline_sources, start=1):
            if not isinstance(outline_source, dict):
                item = _warning(
                    "invalid_outline_source",
                    "draft/report_outline.json",
                    f"Outline source at position {source_position} is not an object and was skipped.",
                    section_id=outline_section_id,
                )
                section_warnings.append(item)
                all_warnings.append(item)
                continue
            source_key = _clean_text(outline_source.get("source_key"), 160)
            outline_source_id = _source_id(outline_source)
            if not source_key:
                item = _warning(
                    "missing_source_key",
                    "draft/report_outline.json",
                    "Outline source has no stable source_key and was skipped.",
                    section_id=outline_section_id,
                )
                section_warnings.append(item)
                all_warnings.append(item)
                continue
            if source_key in seen_section_keys:
                continue
            seen_section_keys.add(source_key)
            source = sources_by_key.get(source_key) or sources_by_id.get(outline_source_id)
            review = reviews_by_key.get(source_key) or reviews_by_id.get(outline_source_id, {})
            status = _review_status(review)
            if status not in BODY_REVIEW_STATUSES:
                _stable_append(excluded_source_keys, source_key)
                item = _warning(
                    "source_excluded_by_review",
                    "research/source_review.json",
                    f"Source was excluded because its current review status is {status}.",
                    section_id=outline_section_id,
                    source_key=source_key,
                )
                section_warnings.append(item)
                all_warnings.append(item)
                continue
            if not source:
                item = _warning(
                    "missing_source_reference",
                    "draft/report_outline.json",
                    "Outline source could not be matched to current research evidence.",
                    section_id=outline_section_id,
                    source_key=source_key,
                )
                section_warnings.append(item)
                all_warnings.append(item)
                continue
            source_id = _source_id(source)
            text, text_provenance = _select_text(source, notes_by_id.get(source_id))
            if not text or text_provenance is None:
                item = _warning(
                    "source_without_usable_text",
                    "research/sources.json",
                    "Source has no usable research-note, snippet, or claim text.",
                    section_id=outline_section_id,
                    source_key=source_key,
                )
                section_warnings.append(item)
                all_warnings.append(item)
                continue

            support = _supporting_source(source_key, source, status, text_provenance)
            block_order = len(blocks) + 1
            block_id = f"{section_id}-block-{block_order:03d}"
            block = {
                "block_id": block_id,
                "order": block_order,
                "block_type": "paragraph",
                "text": text,
                "claim_type": "factual" if status == "approved" else "candidate",
                "supporting_sources": [support],
                "source_keys": [source_key],
                "needs_manual_review": status != "approved",
            }
            blocks.append(block)
            section_sources.append(support)
            section_source_keys.append(source_key)
            _stable_append(included_source_keys, source_key)

            index_item = source_index_by_key.get(source_key)
            if index_item is None:
                index_item = {
                    **support,
                    "used_by_sections": [],
                    "used_by_blocks": [],
                }
                source_index_by_key[source_key] = index_item
            _stable_append(index_item["used_by_sections"], section_id)
            _stable_append(index_item["used_by_blocks"], block_id)

        if not blocks:
            item = _warning(
                "section_without_usable_sources",
                "draft/report_outline.json",
                "Section has no currently eligible source with usable text.",
                section_id=outline_section_id,
            )
            section_warnings.append(item)
            all_warnings.append(item)
        sections.append(
            {
                "section_id": section_id,
                "outline_section_id": outline_section_id,
                "order": section_order,
                "title": _clean_text(outline_section.get("title"), 500),
                "purpose": _clean_text(outline_section.get("purpose"), 500),
                "status": "draft",
                "content_blocks": blocks,
                "supporting_sources": section_sources,
                "source_keys": section_source_keys,
                "needs_manual_review": not blocks or any(block["needs_manual_review"] for block in blocks),
                "warnings": section_warnings,
            }
        )

    request = record.request
    return {
        "schema": REPORT_DRAFT_SCHEMA,
        "task_id": _clean_text(getattr(record, "task_id", ""), 120),
        "title": _clean_text(outline.get("title") or getattr(request, "title", ""), 500),
        "status": "draft",
        "outline_schema": _clean_text(outline.get("schema_version") or outline.get("schema"), 120),
        "sections": sections,
        "source_index": list(source_index_by_key.values()),
        "provenance": {
            "outline_path": "draft/report_outline.json",
            "research_inputs": [
                "research/sources.json",
                "research/research_notes.json",
                "research/source_review.json",
            ],
            "included_source_keys": included_source_keys,
            "excluded_source_keys": excluded_source_keys,
            "input_warnings": input_warnings,
            "generation_mode": "deterministic",
            "generated_at": _now(),
        },
        "warnings": all_warnings,
    }


def _validate_draft(draft: dict[str, Any]) -> None:
    if draft.get("schema") != REPORT_DRAFT_SCHEMA:
        raise ValueError("report_draft.json has an invalid schema.")
    if draft.get("status") != "draft":
        raise ValueError("report_draft.json must have draft status.")
    for section in _list_of_dicts(draft.get("sections")):
        for block in _list_of_dicts(section.get("content_blocks")):
            if not _clean_text(block.get("text")):
                raise ValueError(f"Block {block.get('block_id')} has no text.")
            if not block.get("source_keys") or not block.get("supporting_sources"):
                raise ValueError(f"Block {block.get('block_id')} has no source provenance.")


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


def generate_report_draft(record: Any, workspace: Path) -> dict[str, Any]:
    input_warnings: list[dict[str, str]] = []
    outline = _read_object(workspace / "draft" / "report_outline.json", "draft/report_outline.json", input_warnings)
    sources = _read_object(workspace / "research" / "sources.json", "research/sources.json", input_warnings)
    notes = _read_object(workspace / "research" / "research_notes.json", "research/research_notes.json", input_warnings)
    reviews = _read_object(workspace / "research" / "source_review.json", "research/source_review.json", input_warnings)
    draft = _build_draft(record, outline, sources, notes, reviews, input_warnings)
    _validate_draft(draft)
    _atomic_write_json(report_draft_path(workspace), draft)
    return draft
