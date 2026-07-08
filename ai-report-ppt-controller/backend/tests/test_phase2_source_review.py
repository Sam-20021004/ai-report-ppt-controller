from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.phase2_artifacts import load_source_review, save_source_review_updates


def _write_sources(task_root: Path, items: list[dict]) -> None:
    research_dir = task_root / "research"
    research_dir.mkdir(parents=True, exist_ok=True)
    (research_dir / "sources.json").write_text(
        json.dumps({"schema_version": "phase2.sources.v1", "items": items}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_source_review_is_created_from_sources_with_unreviewed_defaults(tmp_path: Path) -> None:
    task_root = tmp_path / "task-001"
    _write_sources(
        task_root,
        [
            {"title": "Alpha", "url": "https://example.com/a"},
            {"title": "No URL source"},
        ],
    )

    review = load_source_review("task-001", task_root)

    assert review["summary"] == {
        "total": 2,
        "unreviewed": 2,
        "approved": 0,
        "rejected": 0,
        "needs_followup": 0,
    }
    assert [item["review_status"] for item in review["items"]] == ["unreviewed", "unreviewed"]
    assert all(item["source_key"] for item in review["items"])
    assert (task_root / "research" / "source_review.json").exists()


def test_source_review_updates_are_saved_and_reloaded(tmp_path: Path) -> None:
    task_root = tmp_path / "task-002"
    _write_sources(task_root, [{"title": "Alpha", "url": "https://example.com/a"}])
    source_key = load_source_review("task-002", task_root)["items"][0]["source_key"]

    updated = save_source_review_updates(
        "task-002",
        task_root,
        [{"source_key": source_key, "review_status": "approved", "review_note": "Checked against original."}],
    )
    reloaded = load_source_review("task-002", task_root)

    assert updated["summary"]["approved"] == 1
    assert reloaded["items"][0]["review_status"] == "approved"
    assert reloaded["items"][0]["review_note"] == "Checked against original."
    assert reloaded["items"][0]["reviewed_at"]
    assert reloaded["items"][0]["reviewer"] == "local-user"


def test_source_review_merge_preserves_existing_url_status_and_adds_new_sources(tmp_path: Path) -> None:
    task_root = tmp_path / "task-003"
    _write_sources(task_root, [{"title": "Alpha", "url": "https://example.com/a"}])
    source_key = load_source_review("task-003", task_root)["items"][0]["source_key"]
    save_source_review_updates(
        "task-003",
        task_root,
        [{"source_key": source_key, "review_status": "needs_followup", "review_note": "Need date check."}],
    )

    _write_sources(
        task_root,
        [
            {"title": "Alpha updated", "url": "https://example.com/a"},
            {"title": "Beta", "url": "https://example.com/b"},
        ],
    )
    review = load_source_review("task-003", task_root)

    by_url = {item["url"]: item for item in review["items"]}
    assert by_url["https://example.com/a"]["review_status"] == "needs_followup"
    assert by_url["https://example.com/a"]["review_note"] == "Need date check."
    assert by_url["https://example.com/b"]["review_status"] == "unreviewed"
    assert review["summary"]["total"] == 2
    assert review["summary"]["needs_followup"] == 1
    assert review["summary"]["unreviewed"] == 1


def test_invalid_review_status_is_rejected(tmp_path: Path) -> None:
    task_root = tmp_path / "task-004"
    _write_sources(task_root, [{"title": "Alpha", "url": "https://example.com/a"}])
    source_key = load_source_review("task-004", task_root)["items"][0]["source_key"]

    try:
        save_source_review_updates(
            "task-004",
            task_root,
            [{"source_key": source_key, "review_status": "maybe", "review_note": ""}],
        )
    except ValueError as exc:
        assert "review_status" in str(exc)
    else:
        raise AssertionError("invalid review_status should raise ValueError")
