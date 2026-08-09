from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.config import STORAGE_DIR, get_settings
from backend.services.role_baseline_service import run_role_baseline
from backend.services.security import require_api_token


router = APIRouter(prefix="/api/check", tags=["check"])


@router.post("/role-baseline", dependencies=[Depends(require_api_token)])
def role_baseline() -> dict:
    settings = get_settings()
    diagnostics_root = STORAGE_DIR / "workspace" / "diagnostics"
    return run_role_baseline(settings, diagnostics_root)
