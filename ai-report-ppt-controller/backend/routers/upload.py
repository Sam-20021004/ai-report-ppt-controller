from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile

from backend.services.security import require_api_token
from backend.services.template_manager import save_upload

router = APIRouter(prefix="/api/upload", tags=["upload"])


@router.post("/template/ppt", dependencies=[Depends(require_api_token)])
async def upload_ppt_template(file: UploadFile = File(...)) -> dict:
    return {"ok": True, "file": await save_upload(file, "ppt_template")}


@router.post("/template/word", dependencies=[Depends(require_api_token)])
async def upload_word_template(file: UploadFile = File(...)) -> dict:
    return {"ok": True, "file": await save_upload(file, "word_template")}


@router.post("/material", dependencies=[Depends(require_api_token)])
async def upload_material(task_id: str | None = Form(default=None), file: UploadFile = File(...)) -> dict:
    return {"ok": True, "file": await save_upload(file, "materials", task_id)}
