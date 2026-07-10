from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.models.task import TaskRecord, TaskRequest, default_steps
from backend.services import task_runner
from backend.services.phase2_artifacts import source_review_key
from backend.services.phase2_records import build_file_metadata
from backend.services.report_planner import generate_report_outline
from backend.services.task_runner import create_task, list_task_files, run_workflow


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _workspace_with_sources(
    tmp_path: Path,
    review_states: dict[str, str],
) -> tuple[Path, TaskRecord]:
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

    source_definitions = {
        "s-approved": {
            "query_id": "q001",
            "title": "Approved evidence",
            "url": "https://example.com/approved",
            "snippet": "Approved source text describing the established technical background.",
        },
        "s-unreviewed": {
            "query_id": "q001",
            "title": "Unreviewed evidence",
            "url": "https://example.com/unreviewed",
            "snippet": "Candidate source text that still requires human verification.",
        },
        "s-rejected": {
            "query_id": "q001",
            "title": "Rejected evidence",
            "url": "https://example.com/rejected",
            "snippet": "This rejected text must never enter the outline.",
        },
        "s-followup": {
            "query_id": "q002",
            "title": "Follow-up evidence",
            "url": "https://example.com/followup",
            "snippet": "This item needs follow-up and must not enter a body section.",
        },
    }
    sources = []
    note_sources = []
    reviews = []
    for source_id, review_status in review_states.items():
        definition = source_definitions[source_id]
        source = {"id": source_id, "source_id": source_id, **definition}
        sources.append(source)
        note_sources.append(
            {
                **source,
                "preliminary_note": f"Snippet-derived candidate note, not verified: {definition['snippet']}",
            }
        )
        reviews.append(
            {
                "source_key": f"key:{source_id}",
                "source_id": source_id,
                "title": definition["title"],
                "url": definition["url"],
                "review_status": review_status,
                "review_note": "Open and verify the original source." if review_status == "needs_followup" else "",
                "stale": False,
            }
        )

    research_dir = workspace / "research"
    _write_json(
        research_dir / "search_plan.json",
        {
            "schema_version": "phase2.search_plan.v1",
            "task_id": request.task_id,
            "inputs": {"topic": request.title, "audience": request.audience},
            "queries": [
                {"id": "q001", "purpose": "background", "query": "semiconductor technical background"},
                {"id": "q002", "purpose": "technical_detail", "query": "semiconductor technical detail"},
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
            "task": {"task_id": request.task_id, "title": request.title},
            "source_groups": [
                {
                    "query": {"id": "q001", "purpose": "background"},
                    "sources": [item for item in note_sources if item["query_id"] == "q001"],
                },
                {
                    "query": {"id": "q002", "purpose": "technical_detail"},
                    "sources": [item for item in note_sources if item["query_id"] == "q002"],
                },
            ],
        },
    )
    _write_json(
        research_dir / "source_review.json",
        {"task_id": request.task_id, "version": 1, "items": reviews},
    )
    return workspace, record


def test_generate_report_outline_filters_review_states_and_preserves_provenance(tmp_path: Path) -> None:
    workspace, record = _workspace_with_sources(
        tmp_path,
        review_states={
            "s-approved": "approved",
            "s-unreviewed": "unreviewed",
            "s-rejected": "rejected",
            "s-followup": "needs_followup",
        },
    )

    outline = generate_report_outline(record, workspace)

    supported = [source for section in outline["sections"] for source in section["supporting_sources"]]
    assert [source["source_id"] for source in supported] == ["s-approved", "s-unreviewed"]
    assert all(source["source_id"] != "s-rejected" for source in supported)
    assert outline["sections"][0]["supporting_sources"][0]["review_status"] == "approved"
    assert outline["sections"][0]["review_status"] == "needs_review"
    assert outline["sections"][0]["confidence"] == "medium"
    assert all(source["provenance"] for source in supported)
    assert any(item["source_id"] == "s-followup" for item in outline["missing_information"])
    assert not any(item.get("source_id") == "s-rejected" for item in outline["missing_information"])
    assert (workspace / "draft" / "report_outline.json").exists()


def test_generate_report_outline_allows_no_sections_when_no_sources_are_eligible(tmp_path: Path) -> None:
    workspace, record = _workspace_with_sources(
        tmp_path,
        review_states={"s-rejected": "rejected", "s-followup": "needs_followup"},
    )

    outline = generate_report_outline(record, workspace)

    assert outline["sections"] == []
    assert any(item["reason"] == "no_eligible_sources" for item in outline["missing_information"])


def test_report_outline_rerun_replaces_file_and_leaves_no_temp_files(tmp_path: Path) -> None:
    workspace, record = _workspace_with_sources(tmp_path, review_states={"s-approved": "approved"})
    first = generate_report_outline(record, workspace)
    record.request.title = "Updated traceable report"

    second = generate_report_outline(record, workspace)

    stored = json.loads((workspace / "draft" / "report_outline.json").read_text(encoding="utf-8"))
    assert first["title"] != second["title"]
    assert stored == second
    assert list((workspace / "draft").glob(".report_outline.json.*.tmp")) == []


def test_report_outline_metadata_uses_single_stable_file_type(tmp_path: Path) -> None:
    task_root = tmp_path / "jobs" / "task-001"
    path = task_root / "draft" / "report_outline.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")

    metadata = build_file_metadata("task-001", path, tmp_path, task_root)

    assert metadata["relative_path"] == "draft/report_outline.json"
    assert metadata["file_type"] == "report_outline"
    assert metadata["category"] == "phase3_draft"
    assert metadata["is_phase2_artifact"] is False


def _configure_task_storage(tmp_path: Path, monkeypatch) -> Path:
    storage_dir = tmp_path / "runtime"
    job_root = storage_dir / "workspace" / "jobs"
    monkeypatch.setattr(task_runner, "STORAGE_DIR", storage_dir)
    monkeypatch.setattr(task_runner, "JOB_ROOT", job_root)
    return storage_dir


def test_research_only_workflow_creates_report_outline_without_future_drafts(tmp_path: Path, monkeypatch) -> None:
    _configure_task_storage(tmp_path, monkeypatch)
    record = create_task(
        TaskRequest(
            title="Phase 3 outline",
            task_type="research_only",
            enable_web_search=False,
        )
    )

    completed = run_workflow(record.task_id)
    draft_dir = Path(completed.workspace_dir) / "draft"
    draft_files = sorted(path.name for path in draft_dir.glob("*"))

    assert "report_outline.json" in draft_files
    assert "report_draft.md" not in draft_files
    assert "slide_plan.json" not in draft_files
    assert "figure_plan.json" not in draft_files
    json.loads((draft_dir / "report_outline.json").read_text(encoding="utf-8"))


def test_task_file_list_exposes_report_outline_for_download(tmp_path: Path, monkeypatch) -> None:
    storage_dir = _configure_task_storage(tmp_path, monkeypatch)
    record = create_task(
        TaskRequest(
            title="Phase 3 file list",
            task_type="research_only",
            enable_web_search=False,
        )
    )
    run_workflow(record.task_id)

    outline_file = next(
        item for item in list_task_files(record.task_id) if item["relative_path"] == "draft/report_outline.json"
    )

    assert outline_file["file_type"] == "report_outline"
    assert Path(outline_file["path"]).read_bytes()
    assert Path(outline_file["path"]).resolve().is_relative_to(storage_dir.resolve())


def test_stable_source_key_preserves_rejected_status_when_source_id_changes(tmp_path: Path) -> None:
    workspace, record = _workspace_with_sources(tmp_path, review_states={"s-rejected": "rejected"})
    sources_path = workspace / "research" / "sources.json"
    review_path = workspace / "research" / "source_review.json"
    sources_payload = json.loads(sources_path.read_text(encoding="utf-8"))
    review_payload = json.loads(review_path.read_text(encoding="utf-8"))
    review_payload["items"][0]["source_id"] = "legacy-source-id"
    review_payload["items"][0]["source_key"] = source_review_key(sources_payload["items"][0], 1)
    _write_json(review_path, review_payload)

    outline = generate_report_outline(record, workspace)

    assert outline["sections"] == []
    assert all(item.get("source_id") != "s-rejected" for item in outline["missing_information"])


def test_queries_with_the_same_purpose_are_consolidated_into_one_section(tmp_path: Path) -> None:
    workspace, record = _workspace_with_sources(
        tmp_path,
        review_states={"s-approved": "approved", "s-unreviewed": "unreviewed"},
    )
    search_plan_path = workspace / "research" / "search_plan.json"
    sources_path = workspace / "research" / "sources.json"
    notes_path = workspace / "research" / "research_notes.json"
    search_plan = json.loads(search_plan_path.read_text(encoding="utf-8"))
    search_plan["queries"][1]["purpose"] = "background"
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    sources["items"][1]["query_id"] = "q002"
    notes = json.loads(notes_path.read_text(encoding="utf-8"))
    moved_source = notes["source_groups"][0]["sources"].pop(1)
    moved_source["query_id"] = "q002"
    notes["source_groups"][1]["sources"].append(moved_source)
    _write_json(search_plan_path, search_plan)
    _write_json(sources_path, sources)
    _write_json(notes_path, notes)

    outline = generate_report_outline(record, workspace)

    assert len(outline["sections"]) == 1
    assert [item["source_id"] for item in outline["sections"][0]["supporting_sources"]] == [
        "s-approved",
        "s-unreviewed",
    ]


def test_approved_source_without_usable_text_does_not_create_placeholder_section(tmp_path: Path) -> None:
    workspace, record = _workspace_with_sources(tmp_path, review_states={"s-approved": "approved"})
    sources_path = workspace / "research" / "sources.json"
    notes_path = workspace / "research" / "research_notes.json"
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    sources["items"][0]["title"] = ""
    sources["items"][0]["snippet"] = ""
    notes = json.loads(notes_path.read_text(encoding="utf-8"))
    note_source = notes["source_groups"][0]["sources"][0]
    for field in ("preliminary_note", "snippet", "claim_supported", "title"):
        note_source[field] = ""
    _write_json(sources_path, sources)
    _write_json(notes_path, notes)

    outline = generate_report_outline(record, workspace)

    assert outline["sections"] == []
    assert any(item["reason"] == "source_without_usable_text" for item in outline["missing_information"])


def test_missing_sources_file_produces_valid_empty_outline(tmp_path: Path) -> None:
    workspace, record = _workspace_with_sources(tmp_path, review_states={"s-approved": "approved"})
    (workspace / "research" / "sources.json").unlink()

    outline = generate_report_outline(record, workspace)

    assert outline["schema_version"] == "phase3.report_outline.v1"
    assert outline["sections"] == []
    assert any("sources.json is missing" in warning for warning in outline["provenance"]["input_warnings"])


def test_malformed_sources_file_produces_valid_empty_outline(tmp_path: Path) -> None:
    workspace, record = _workspace_with_sources(tmp_path, review_states={"s-approved": "approved"})
    (workspace / "research" / "sources.json").write_text("{broken", encoding="utf-8")

    outline = generate_report_outline(record, workspace)

    assert outline["sections"] == []
    assert any("sources.json could not be read" in warning for warning in outline["provenance"]["input_warnings"])


def test_missing_notes_and_review_files_degrade_without_crashing(tmp_path: Path) -> None:
    workspace, record = _workspace_with_sources(tmp_path, review_states={"s-approved": "approved"})
    (workspace / "research" / "research_notes.json").unlink()
    (workspace / "research" / "source_review.json").unlink()

    outline = generate_report_outline(record, workspace)

    assert len(outline["sections"]) == 1
    assert outline["sections"][0]["review_status"] == "needs_review"
    assert outline["sections"][0]["supporting_sources"][0]["review_status"] == "unreviewed"
    assert len(outline["provenance"]["input_warnings"]) == 2


def test_duplicate_sources_are_not_repeated_in_supporting_sources(tmp_path: Path) -> None:
    workspace, record = _workspace_with_sources(tmp_path, review_states={"s-approved": "approved"})
    sources_path = workspace / "research" / "sources.json"
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    duplicate = {**sources["items"][0], "id": "s-duplicate", "source_id": "s-duplicate"}
    sources["items"].append(duplicate)
    _write_json(sources_path, sources)

    outline = generate_report_outline(record, workspace)

    assert len(outline["sections"]) == 1
    assert [item["source_id"] for item in outline["sections"][0]["supporting_sources"]] == ["s-approved"]
