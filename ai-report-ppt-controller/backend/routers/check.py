from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.services.chrome_client import check_chrome
from backend.services.codex_client import check_codex
from backend.services.hermes_client import check_hermes
from backend.services.security import require_api_token

router = APIRouter(prefix="/api/check", tags=["check"])


@router.post("/codex", dependencies=[Depends(require_api_token)])
def codex() -> dict:
    return check_codex().model_dump()


@router.post("/hermes", dependencies=[Depends(require_api_token)])
def hermes() -> dict:
    return check_hermes().model_dump()


@router.post("/chrome", dependencies=[Depends(require_api_token)])
def chrome() -> dict:
    return check_chrome().model_dump()
