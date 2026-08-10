from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.config import AppConfig
from backend.models.task import TaskRecord, TaskRequest, default_steps
from backend.services import task_runner
from backend.services.phase2_artifacts import source_review_key
from backend.services.phase2_records import build_file_metadata
from backend.services.report_drafter import _read_object, generate_report_draft
from backend.services.task_runner import create_task, list_task_files, run_workflow


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _workspace_with_report_inputs(tmp_path: Path) -> tuple[Path, TaskRecord, dict[str, str]]:
    workspace = tmp_path / "task-001"
    request = TaskRequest(
        task_id="task-001",
        title="Traceable semiconductor report",
        task_type="research_only",
        domain="Semiconductor IP",
        audience="R&D leadership",
        language="en",
    )
    record = TaskRecord(task_id=request.task_id, request=request, steps=default_steps(), workspace_dir=str(workspace))
    sources = [
        {
            "id": "s-approved",
            "source_id": "s-approved",
            "query_id": "q001",
            "title": "Approved technical evidence",
            "url": "https://example.com/approved",
            "normalized_url": "https://example.com/approved",
            "snippet": "Approved evidence describes the established device structure.",
        },
        {
            "id": "s-unreviewed",
            "source_id": "s-unreviewed",
            "query_id": "q002",
            "title": "Candidate process evidence",
            "url": "https://example.com/unreviewed",
            "normalized_url": "https://example.com/unreviewed",
            "snippet": "Candidate evidence describes a process option that still requires review.",
        },
        {
            "id": "s-rejected",
            "source_id": "s-rejected",
            "query_id": "q001",
            "title": "Rejected evidence",
            "url": "https://example.com/rejected",
            "normalized_url": "https://example.com/rejected",
            "snippet": "Rejected evidence must not appear in the report draft.",
        },
    ]
    keys = {
        source["source_id"]: source_review_key(source, index)
        for index, source in enumerate(sources, start=1)
    }
    research_dir = workspace / "research"
    _write_json(
        research_dir / "search_plan.json",
        {
            "schema_version": "phase2.search_plan.v1",
            "queries": [
                {"id": "q001", "purpose": "background"},
                {"id": "q002", "purpose": "technical_detail"},
            ],
        },
    )
    _write_json(
        research_dir / "sources.json",
        {"schema_version": "phase2.sources.v1", "task_id": request.task_id, "items": sources},
    )
    _write_json(
        research_dir / "research_notes.json",
        {
            "schema_version": "phase2.research_notes.v1",
            "source_groups": [
                {
                    "query": {"id": "q001", "purpose": "background"},
                    "sources": [
                        {
                            **sources[0],
                            "preliminary_note": "The reviewed source records the established device structure.",
                        },
                        {
                            **sources[2],
                            "preliminary_note": "This rejected note must not appear in the report draft.",
                        },
                    ],
                },
                {
                    "query": {"id": "q002", "purpose": "technical_detail"},
                    "sources": [
                        {
                            **sources[1],
                            "preliminary_note": "The candidate source records a process option requiring review.",
                        }
                    ],
                },
            ],
        },
    )
    _write_json(
        research_dir / "source_review.json",
        {
            "task_id": request.task_id,
            "version": 1,
            "items": [
                {
                    "source_key": keys["s-approved"],
                    "source_id": "s-approved",
                    "review_status": "approved",
                    "stale": False,
                },
                {
                    "source_key": keys["s-unreviewed"],
                    "source_id": "s-unreviewed",
                    "review_status": "unreviewed",
                    "stale": False,
                },
                {
                    "source_key": keys["s-rejected"],
                    "source_id": "s-rejected",
                    "review_status": "rejected",
                    "stale": False,
                },
            ],
        },
    )
    _write_json(
        workspace / "draft" / "report_outline.json",
        {
            "schema_version": "phase3.report_outline.v1",
            "task_id": request.task_id,
            "title": request.title,
            "sections": [
                {
                    "section_id": "1",
                    "title": "Background and Scope",
                    "purpose": "background",
                    "supporting_sources": [
                        {
                            "source_id": "s-approved",
                            "source_key": keys["s-approved"],
                            "title": sources[0]["title"],
                            "url": sources[0]["url"],
                            "review_status": "approved",
                        },
                        {
                            "source_id": "s-rejected",
                            "source_key": keys["s-rejected"],
                            "title": sources[2]["title"],
                            "url": sources[2]["url"],
                            "review_status": "unreviewed",
                        },
                    ],
                },
                {
                    "section_id": "2",
                    "title": "Technical Details",
                    "purpose": "technical_detail",
                    "supporting_sources": [
                        {
                            "source_id": "s-unreviewed",
                            "source_key": keys["s-unreviewed"],
                            "title": sources[1]["title"],
                            "url": sources[1]["url"],
                            "review_status": "unreviewed",
                        }
                    ],
                },
            ],
        },
    )
    return workspace, record, keys


def _set_review_status(workspace: Path, source_key: str, status: str) -> None:
    path = workspace / "research" / "source_review.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    item = next(item for item in payload["items"] if item["source_key"] == source_key)
    item["review_status"] = status
    _write_json(path, payload)


def _upstream_hashes(workspace: Path) -> dict[str, str]:
    paths = [
        workspace / "draft" / "report_outline.json",
        workspace / "research" / "search_plan.json",
        workspace / "research" / "sources.json",
        workspace / "research" / "research_notes.json",
        workspace / "research" / "source_review.json",
    ]
    return {path.relative_to(workspace).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def test_report_draft_preserves_outline_and_builds_auditable_blocks(tmp_path: Path) -> None:
    workspace, record, keys = _workspace_with_report_inputs(tmp_path)

    draft = generate_report_draft(record, workspace)

    assert draft["schema"] == "phase3.report_draft.v1"
    assert draft["status"] == "draft"
    assert [section["outline_section_id"] for section in draft["sections"]] == ["1", "2"]
    first, second = draft["sections"]
    assert first["content_blocks"][0]["claim_type"] == "factual"
    assert first["content_blocks"][0]["needs_manual_review"] is False
    assert second["content_blocks"][0]["claim_type"] == "candidate"
    assert second["content_blocks"][0]["needs_manual_review"] is True
    assert all(block["source_keys"] for section in draft["sections"] for block in section["content_blocks"])
    assert [item["source_key"] for item in draft["source_index"]] == [
        keys["s-approved"],
        keys["s-unreviewed"],
    ]
    assert keys["s-rejected"] in draft["provenance"]["excluded_source_keys"]
    assert (workspace / "draft" / "report_draft.json").exists()


def test_current_rejected_review_removes_stale_outline_source(tmp_path: Path) -> None:
    workspace, record, keys = _workspace_with_report_inputs(tmp_path)
    _set_review_status(workspace, keys["s-approved"], "rejected")

    draft = generate_report_draft(record, workspace)

    assert keys["s-approved"] not in draft["provenance"]["included_source_keys"]
    assert keys["s-approved"] in draft["provenance"]["excluded_source_keys"]
    assert all(keys["s-approved"] not in section["source_keys"] for section in draft["sections"])
    assert all(item["source_key"] != keys["s-approved"] for item in draft["source_index"])


def test_empty_outline_produces_empty_draft_without_placeholder_sections(tmp_path: Path) -> None:
    workspace, record, _ = _workspace_with_report_inputs(tmp_path)
    outline_path = workspace / "draft" / "report_outline.json"
    outline = json.loads(outline_path.read_text(encoding="utf-8"))
    outline["sections"] = []
    _write_json(outline_path, outline)

    draft = generate_report_draft(record, workspace)

    assert draft["sections"] == []
    assert draft["source_index"] == []


@pytest.mark.parametrize("payload", [None, [], "invalid", 42])
def test_non_object_outline_degrades_to_empty_draft(tmp_path: Path, payload: Any) -> None:
    workspace, record, _ = _workspace_with_report_inputs(tmp_path)
    _write_json(workspace / "draft" / "report_outline.json", payload)

    draft = generate_report_draft(record, workspace)

    assert draft["sections"] == []
    assert draft["source_index"] == []
    assert draft["provenance"]["input_warnings"]


def test_missing_sections_array_records_warning(tmp_path: Path) -> None:
    workspace, record, _ = _workspace_with_report_inputs(tmp_path)
    _write_json(workspace / "draft" / "report_outline.json", {"schema_version": "phase3.report_outline.v1"})

    draft = generate_report_draft(record, workspace)

    assert draft["sections"] == []
    assert any(item["code"] == "invalid_outline_sections" for item in draft["provenance"]["input_warnings"])


def test_invalid_section_does_not_discard_other_outline_sections(tmp_path: Path) -> None:
    workspace, record, _ = _workspace_with_report_inputs(tmp_path)
    outline_path = workspace / "draft" / "report_outline.json"
    outline = json.loads(outline_path.read_text(encoding="utf-8"))
    outline["sections"].insert(1, "broken section")
    _write_json(outline_path, outline)

    draft = generate_report_draft(record, workspace)

    assert [section["outline_section_id"] for section in draft["sections"]] == ["1", "2"]
    assert any(item["code"] == "invalid_outline_section" for item in draft["provenance"]["input_warnings"])
    assert any(item["code"] == "invalid_outline_section" for item in draft["warnings"])


def test_source_without_usable_text_keeps_empty_review_section(tmp_path: Path) -> None:
    workspace, record, keys = _workspace_with_report_inputs(tmp_path)
    sources_path = workspace / "research" / "sources.json"
    notes_path = workspace / "research" / "research_notes.json"
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    approved = next(item for item in sources["items"] if item["source_id"] == "s-approved")
    approved["snippet"] = ""
    approved["claim_supported"] = ""
    notes = json.loads(notes_path.read_text(encoding="utf-8"))
    note = next(
        item
        for group in notes["source_groups"]
        for item in group["sources"]
        if item["source_id"] == "s-approved"
    )
    for field in ("preliminary_note", "snippet", "claim_supported"):
        note[field] = ""
    _write_json(sources_path, sources)
    _write_json(notes_path, notes)

    draft = generate_report_draft(record, workspace)

    first = draft["sections"][0]
    assert first["content_blocks"] == []
    assert first["needs_manual_review"] is True
    assert keys["s-approved"] not in first["source_keys"]
    assert any(item["code"] == "source_without_usable_text" for item in first["warnings"])


def test_duplicate_outline_source_key_produces_one_block_and_one_index_entry(tmp_path: Path) -> None:
    workspace, record, keys = _workspace_with_report_inputs(tmp_path)
    outline_path = workspace / "draft" / "report_outline.json"
    outline = json.loads(outline_path.read_text(encoding="utf-8"))
    outline["sections"][0]["supporting_sources"].append(
        dict(outline["sections"][0]["supporting_sources"][0])
    )
    _write_json(outline_path, outline)

    draft = generate_report_draft(record, workspace)

    assert len(draft["sections"][0]["content_blocks"]) == 1
    assert [item["source_key"] for item in draft["source_index"]].count(keys["s-approved"]) == 1


def test_outline_reference_to_missing_source_generates_warning_not_content(tmp_path: Path) -> None:
    workspace, record, _ = _workspace_with_report_inputs(tmp_path)
    outline_path = workspace / "draft" / "report_outline.json"
    outline = json.loads(outline_path.read_text(encoding="utf-8"))
    outline["sections"][0]["supporting_sources"][0]["source_key"] = "url:missing"
    outline["sections"][0]["supporting_sources"][0]["source_id"] = "missing"
    _write_json(outline_path, outline)

    draft = generate_report_draft(record, workspace)

    assert all("url:missing" not in section["source_keys"] for section in draft["sections"])
    assert any(item["code"] == "missing_source_reference" for item in draft["warnings"])


def test_rerun_is_stable_atomic_and_does_not_modify_upstream(tmp_path: Path) -> None:
    workspace, record, _ = _workspace_with_report_inputs(tmp_path)
    upstream = _upstream_hashes(workspace)

    first = generate_report_draft(record, workspace)
    second = generate_report_draft(record, workspace)

    first["provenance"].pop("generated_at")
    second["provenance"].pop("generated_at")
    assert first == second
    assert _upstream_hashes(workspace) == upstream
    assert list((workspace / "draft").glob(".report_draft.json.*.tmp")) == []


def test_report_draft_metadata_uses_stable_type(tmp_path: Path) -> None:
    storage_root = tmp_path / "runtime"
    task_root = storage_root / "workspace" / "jobs" / "task-001"
    path = task_root / "draft" / "report_draft.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")

    metadata = build_file_metadata("task-001", path, storage_root, task_root)

    assert metadata["relative_path"] == "draft/report_draft.json"
    assert metadata["file_type"] == "report_draft"
    assert metadata["category"] == "phase3_draft"
    assert metadata["description"]
    assert metadata["is_phase2_artifact"] is False


def _configure_task_storage(tmp_path: Path, monkeypatch) -> Path:
    storage_dir = tmp_path / "runtime"
    settings = AppConfig(
        planner_mode="hermes",
        hermes_mode="mock",
        codex_mode="mock",
        output_dir=str(storage_dir / "outputs"),
    )
    monkeypatch.setattr(task_runner, "STORAGE_DIR", storage_dir)
    monkeypatch.setattr(task_runner, "JOB_ROOT", storage_dir / "workspace" / "jobs")
    monkeypatch.setattr(task_runner, "get_settings", lambda: settings)
    return storage_dir


def test_research_only_workflow_creates_outline_and_report_draft(tmp_path: Path, monkeypatch) -> None:
    storage_dir = _configure_task_storage(tmp_path, monkeypatch)
    record = create_task(
        TaskRequest(
            title="Phase 3.2 workflow",
            task_type="research_only",
            enable_web_search=False,
            enable_industry_search=False,
        )
    )

    completed = run_workflow(record.task_id)
    workspace = Path(completed.workspace_dir)
    draft = json.loads((workspace / "draft" / "report_draft.json").read_text(encoding="utf-8"))
    listed = next(
        item for item in list_task_files(record.task_id) if item["relative_path"] == "draft/report_draft.json"
    )

    assert (workspace / "draft" / "report_outline.json").exists()
    assert draft["schema"] == "phase3.report_draft.v1"
    assert draft["sections"] == []
    assert listed["file_type"] == "report_draft"
    assert Path(listed["path"]).resolve().is_relative_to(storage_dir.resolve())
    assert not (workspace / "draft" / "report_draft.md").exists()
    assert not (workspace / "draft" / "slide_plan.json").exists()
    assert not (workspace / "draft" / "figure_plan.json").exists()


def test_source_order_is_driven_by_outline_not_physical_source_order(tmp_path: Path) -> None:
    workspace, record, keys = _workspace_with_report_inputs(tmp_path)
    sources_path = workspace / "research" / "sources.json"
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    sources["items"].reverse()
    _write_json(sources_path, sources)

    draft = generate_report_draft(record, workspace)

    assert [item["source_key"] for item in draft["source_index"]] == [
        keys["s-approved"],
        keys["s-unreviewed"],
    ]


def test_source_index_deduplicates_reverse_links_across_sections(tmp_path: Path) -> None:
    workspace, record, keys = _workspace_with_report_inputs(tmp_path)
    outline_path = workspace / "draft" / "report_outline.json"
    outline = json.loads(outline_path.read_text(encoding="utf-8"))
    outline["sections"][1]["supporting_sources"].append(
        dict(outline["sections"][0]["supporting_sources"][0])
    )
    _write_json(outline_path, outline)

    draft = generate_report_draft(record, workspace)
    approved = next(item for item in draft["source_index"] if item["source_key"] == keys["s-approved"])

    assert approved["used_by_sections"] == ["section-001", "section-002"]
    assert approved["used_by_blocks"] == ["section-001-block-001", "section-002-block-002"]


def test_missing_review_state_inherits_unreviewed_semantics(tmp_path: Path) -> None:
    workspace, record, keys = _workspace_with_report_inputs(tmp_path)
    review_path = workspace / "research" / "source_review.json"
    reviews = json.loads(review_path.read_text(encoding="utf-8"))
    reviews["items"] = [item for item in reviews["items"] if item["source_key"] != keys["s-approved"]]
    _write_json(review_path, reviews)

    draft = generate_report_draft(record, workspace)
    block = draft["sections"][0]["content_blocks"][0]

    assert block["claim_type"] == "candidate"
    assert block["needs_manual_review"] is True


def test_corrupt_sources_file_produces_legal_partial_draft(tmp_path: Path) -> None:
    workspace, record, _ = _workspace_with_report_inputs(tmp_path)
    (workspace / "research" / "sources.json").write_text("{broken", encoding="utf-8")

    draft = generate_report_draft(record, workspace)

    assert draft["schema"] == "phase3.report_draft.v1"
    assert all(section["content_blocks"] == [] for section in draft["sections"])
    assert draft["source_index"] == []
    assert any(item["artifact"] == "research/sources.json" for item in draft["provenance"]["input_warnings"])


def test_malformed_outline_source_entry_records_warning(tmp_path: Path) -> None:
    workspace, record, _ = _workspace_with_report_inputs(tmp_path)
    outline_path = workspace / "draft" / "report_outline.json"
    outline = json.loads(outline_path.read_text(encoding="utf-8"))
    outline["sections"][0]["supporting_sources"].insert(0, "broken source")
    _write_json(outline_path, outline)

    draft = generate_report_draft(record, workspace)

    assert draft["sections"][0]["content_blocks"]
    assert any(item["code"] == "invalid_outline_source" for item in draft["sections"][0]["warnings"])


def test_input_warning_does_not_expose_absolute_local_path(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "private" / "report_outline.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    original_read_text = Path.read_text

    def _raise_for_target(self: Path, *args, **kwargs):
        if self == path:
            raise OSError(f"access denied: {path.resolve()}")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _raise_for_target)
    warnings: list[dict[str, str]] = []

    assert _read_object(path, "draft/report_outline.json", warnings) == {}
    assert "private" not in json.dumps(warnings)


@pytest.mark.parametrize("reverse_records", [False, True])
def test_conflicting_duplicate_reviews_use_restrictive_status_regardless_of_order(
    tmp_path: Path,
    reverse_records: bool,
) -> None:
    workspace, record, keys = _workspace_with_report_inputs(tmp_path)
    review_path = workspace / "research" / "source_review.json"
    reviews = json.loads(review_path.read_text(encoding="utf-8"))
    approved = next(item for item in reviews["items"] if item["source_key"] == keys["s-approved"])
    conflict = {**approved, "review_status": "rejected", "review_note": "Conflicting rejection."}
    reviews["items"].append(conflict)
    if reverse_records:
        reviews["items"].reverse()
    _write_json(review_path, reviews)

    draft = generate_report_draft(record, workspace)

    assert keys["s-approved"] not in draft["provenance"]["included_source_keys"]
    assert keys["s-approved"] in draft["provenance"]["excluded_source_keys"]
    assert any(item["code"] == "conflicting_review_status" for item in draft["provenance"]["input_warnings"])


def test_duplicate_review_id_warning_uses_deterministic_source_key(tmp_path: Path) -> None:
    workspace, record, keys = _workspace_with_report_inputs(tmp_path)
    review_path = workspace / "research" / "source_review.json"
    reviews = json.loads(review_path.read_text(encoding="utf-8"))
    approved = next(item for item in reviews["items"] if item["source_key"] == keys["s-approved"])
    reviews["items"].extend(
        [
            {**approved, "source_key": "z-key", "review_status": "approved"},
            {**approved, "source_key": "a-key", "review_status": "rejected"},
        ]
    )
    _write_json(review_path, reviews)

    draft = generate_report_draft(record, workspace)

    warnings = [
        item
        for item in draft["provenance"]["input_warnings"]
        if item["code"] == "conflicting_review_status" and item.get("source_key") == "a-key"
    ]
    assert warnings


def test_notes_with_duplicate_source_id_match_by_stable_key_not_physical_order(tmp_path: Path) -> None:
    workspace, record, _ = _workspace_with_report_inputs(tmp_path)
    notes_path = workspace / "research" / "research_notes.json"
    notes = json.loads(notes_path.read_text(encoding="utf-8"))
    candidate_note = notes["source_groups"][1]["sources"][0]
    candidate_note["source_id"] = "s-approved"
    candidate_note["id"] = "s-approved"
    notes["source_groups"].reverse()
    _write_json(notes_path, notes)

    draft = generate_report_draft(record, workspace)

    approved_block = draft["sections"][0]["content_blocks"][0]
    assert approved_block["text"] == "The reviewed source records the established device structure."
    assert approved_block["supporting_sources"][0]["text_provenance"]["record_id"] == "s-approved"


def test_outline_section_without_identity_is_skipped_not_invented(tmp_path: Path) -> None:
    workspace, record, _ = _workspace_with_report_inputs(tmp_path)
    outline_path = workspace / "draft" / "report_outline.json"
    outline = json.loads(outline_path.read_text(encoding="utf-8"))
    outline["sections"][0].pop("section_id")
    _write_json(outline_path, outline)

    draft = generate_report_draft(record, workspace)

    assert [section["outline_section_id"] for section in draft["sections"]] == ["2"]
    assert any(item["code"] == "missing_outline_section_id" for item in draft["provenance"]["input_warnings"])


def test_duplicate_source_id_does_not_borrow_approved_review_from_another_stable_key(tmp_path: Path) -> None:
    workspace, record, _ = _workspace_with_report_inputs(tmp_path)
    sources_path = workspace / "research" / "sources.json"
    outline_path = workspace / "draft" / "report_outline.json"
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    duplicate = {
        **sources["items"][0],
        "title": "Distinct source sharing an identifier",
        "url": "https://example.com/distinct-duplicate-id",
        "normalized_url": "https://example.com/distinct-duplicate-id",
        "snippet": "This distinct source has no review record and must remain a candidate.",
    }
    sources["items"].append(duplicate)
    duplicate_key = source_review_key(duplicate, len(sources["items"]))
    _write_json(sources_path, sources)

    outline = json.loads(outline_path.read_text(encoding="utf-8"))
    outline["sections"][0]["supporting_sources"] = [
        {
            "source_id": duplicate["source_id"],
            "source_key": duplicate_key,
            "title": duplicate["title"],
            "url": duplicate["url"],
            "review_status": "unreviewed",
        }
    ]
    _write_json(outline_path, outline)

    draft = generate_report_draft(record, workspace)

    block = draft["sections"][0]["content_blocks"][0]
    assert block["text"] == duplicate["snippet"]
    assert block["claim_type"] == "candidate"
    assert block["needs_manual_review"] is True


def test_unknown_review_status_is_excluded_instead_of_treated_as_unreviewed(tmp_path: Path) -> None:
    workspace, record, keys = _workspace_with_report_inputs(tmp_path)
    _set_review_status(workspace, keys["s-approved"], "unexpected_status")

    draft = generate_report_draft(record, workspace)

    assert keys["s-approved"] not in draft["provenance"]["included_source_keys"]
    assert keys["s-approved"] in draft["provenance"]["excluded_source_keys"]
    assert all(keys["s-approved"] not in section["source_keys"] for section in draft["sections"])
