from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.task_runner import list_task_summaries


def _write_status(job_root: Path, task_id: str, payload: dict) -> None:
    state_dir = job_root / task_id / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "status.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_list_task_summaries_returns_empty_list_for_empty_storage(tmp_path: Path) -> None:
    assert list_task_summaries(job_root=tmp_path / "jobs") == []


def test_list_task_summaries_returns_recent_task_metadata(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    _write_status(
        job_root,
        "task-001",
        {
            "task_id": "task-001",
            "created_at": "2026-07-08T10:00:00",
            "updated_at": "2026-07-08T10:15:00",
            "status": "done",
            "request": {"title": "History task", "task_type": "research_only"},
            "phase2_files": [
                {"file_name": "search_plan.json", "is_phase2_artifact": True},
                {"file_name": "sources.json", "is_phase2_artifact": True},
            ],
        },
    )

    summaries = list_task_summaries(job_root=job_root)

    assert summaries == [
        {
            "task_id": "task-001",
            "short_task_id": "task-001",
            "title": "History task",
            "task_type": "research_only",
            "status": "done",
            "created_at": "2026-07-08T10:00:00",
            "updated_at": "2026-07-08T10:15:00",
            "phase2_artifact_count": 2,
            "has_phase2_artifacts": True,
        }
    ]


def test_list_task_summaries_skips_corrupt_task_records(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    _write_status(
        job_root,
        "task-good",
        {
            "task_id": "task-good",
            "created_at": "2026-07-08T10:00:00",
            "updated_at": "2026-07-08T10:20:00",
            "status": "done",
            "request": {"title": "Good task"},
            "phase2_files": [],
        },
    )
    broken_state = job_root / "task-broken" / "state"
    broken_state.mkdir(parents=True, exist_ok=True)
    (broken_state / "status.json").write_text("{broken", encoding="utf-8")

    summaries = list_task_summaries(job_root=job_root)

    assert [item["task_id"] for item in summaries] == ["task-good"]
