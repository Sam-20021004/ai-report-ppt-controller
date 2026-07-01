from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from backend.config import STORAGE_DIR
from backend.services.security import require_api_token, safe_join

router = APIRouter(prefix="/api/download", tags=["download"])


@router.get("/{file_id:path}", dependencies=[Depends(require_api_token)])
def download(file_id: str):
    path = safe_join(STORAGE_DIR, file_id)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(path, filename=Path(path).name)
