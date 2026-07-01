from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request

from backend.config import STORAGE_DIR, get_settings
from backend.services.loop_manager import phase1_loop_contract
from backend.services.ppt_builder import phase1_ppt_contract
from backend.services.security import require_api_token
from backend.services.word_builder import phase1_word_contract

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", dependencies=[Depends(require_api_token)])
def health(request: Request) -> dict:
    settings = get_settings()
    return {
        "ok": True,
        "app": settings.app_name,
        "phase": "Phase 1",
        "client": request.client.host if request.client else "",
        "access_mode": settings.access_mode,
        "storage": {
            "root": str(STORAGE_DIR),
            "writable": Path(settings.output_dir).parent.exists(),
        },
        "capabilities": {
            "task_create": True,
            "task_logs": True,
            "chrome_cdp_check": True,
            "codex_check": True,
            "hermes_check": True,
            "agent_loop": phase1_loop_contract(),
            "ppt_builder": phase1_ppt_contract(),
            "word_builder": phase1_word_contract(),
        },
    }
