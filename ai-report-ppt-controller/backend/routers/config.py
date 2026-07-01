from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.config import get_settings, update_settings
from backend.services.security import require_api_token

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("", dependencies=[Depends(require_api_token)])
def read_config() -> dict:
    settings = get_settings().model_dump()
    settings["api_token"] = "***" if settings.get("api_token") else ""
    return settings


@router.post("/update", dependencies=[Depends(require_api_token)])
def update_config(payload: dict) -> dict:
    settings = update_settings(payload)
    data = settings.model_dump()
    data["api_token"] = "***" if data.get("api_token") else ""
    return data
