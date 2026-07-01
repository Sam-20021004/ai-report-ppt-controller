from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from backend.config import STORAGE_DIR, get_settings
from backend.services.security import assert_safe_upload


TEMPLATE_ROOT = STORAGE_DIR / "templates"
MATERIAL_ROOT = STORAGE_DIR / "tasks"


async def save_upload(file: UploadFile, category: str, task_id: str | None = None) -> dict:
    content = await file.read()
    assert_safe_upload(file.filename or "upload.bin", len(content), get_settings())

    safe_name = Path(file.filename or "upload.bin").name
    file_id = uuid4().hex
    if task_id:
        target_dir = MATERIAL_ROOT / task_id / "inputs" / category
    else:
        target_dir = TEMPLATE_ROOT / category
    target_dir.mkdir(parents=True, exist_ok=True)

    stored_name = f"{file_id}-{safe_name}"
    target = target_dir / stored_name
    target.write_bytes(content)
    return {
        "file_id": file_id,
        "file_name": safe_name,
        "stored_name": stored_name,
        "category": category,
        "path": str(target),
        "size": len(content),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
