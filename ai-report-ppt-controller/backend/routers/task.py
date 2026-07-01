from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.models.task import TaskRequest
from backend.services.security import require_api_token
from backend.services.task_runner import (
    create_task,
    list_task_files,
    load_record,
    run_phase1,
    save_record,
    update_task_status,
)

router = APIRouter(prefix="/api/task", tags=["task"])


@router.post("/create", dependencies=[Depends(require_api_token)])
def create(payload: TaskRequest) -> dict:
    return create_task(payload).model_dump()


@router.get("/{task_id}", dependencies=[Depends(require_api_token)])
def get_task(task_id: str) -> dict:
    return load_record(task_id).model_dump()


@router.post("/{task_id}/run", dependencies=[Depends(require_api_token)])
def run_task(task_id: str) -> dict:
    return run_phase1(task_id).model_dump()


@router.post("/{task_id}/pause", dependencies=[Depends(require_api_token)])
def pause_task(task_id: str) -> dict:
    return update_task_status(task_id, "paused").model_dump()


@router.post("/{task_id}/cancel", dependencies=[Depends(require_api_token)])
def cancel_task(task_id: str) -> dict:
    return update_task_status(task_id, "cancelled").model_dump()


@router.post("/{task_id}/rerun-step", dependencies=[Depends(require_api_token)])
def rerun_step(task_id: str, payload: dict) -> dict:
    record = load_record(task_id)
    step_index = int(payload.get("step_index", 1))
    if 1 <= step_index <= len(record.steps):
        step = record.steps[step_index - 1]
        step.status = "waiting"
        step.started_at = None
        step.ended_at = None
        step.elapsed_ms = None
        step.error = ""
        step.output_summary = "已标记为待重跑。"
    save_record(record)
    return record.model_dump()


@router.get("/{task_id}/logs", dependencies=[Depends(require_api_token)])
def logs(task_id: str) -> dict:
    record = load_record(task_id)
    return {
        "task_id": record.task_id,
        "status": record.status,
        "steps": [step.model_dump() for step in record.steps],
    }


@router.get("/{task_id}/files", dependencies=[Depends(require_api_token)])
def files(task_id: str) -> dict:
    return {
        "task_id": task_id,
        "files": list_task_files(task_id),
    }
