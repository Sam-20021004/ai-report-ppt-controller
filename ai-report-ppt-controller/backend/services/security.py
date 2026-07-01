from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

try:
    from fastapi import Header, HTTPException, Request
except ModuleNotFoundError:  # Allows workflow smoke tests in the zero-dependency runtime.
    def Header(default=None):
        return default

    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: str):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class Request:  # pragma: no cover - used only when FastAPI is not installed.
        client = None

from backend.config import AppConfig, get_settings


SENSITIVE_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|cookie|authorization)\s*[:=]\s*['\"]?[^'\"\s]+"),
    re.compile(r"(?i)bearer\s+[a-z0-9._\-]+"),
]

ALLOWED_UPLOAD_EXTENSIONS = {
    ".ppt",
    ".pptx",
    ".doc",
    ".docx",
    ".pdf",
    ".txt",
    ".md",
    ".csv",
    ".xlsx",
    ".xls",
}


def mask_sensitive(value: str) -> str:
    text = str(value)
    for pattern in SENSITIVE_PATTERNS:
        text = pattern.sub(lambda m: m.group(0).split("=")[0].split(":")[0] + "=***", text)
    return text


def assert_safe_upload(filename: str, size: int, config: AppConfig | None = None) -> None:
    settings = config or get_settings()
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")
    if size > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Upload exceeds size limit.")


def safe_join(base: Path, *parts: str) -> Path:
    root = base.resolve()
    target = root.joinpath(*parts).resolve()
    if root != target and root not in target.parents:
        raise HTTPException(status_code=403, detail="Path escapes task storage.")
    return target


def is_loopback_host(host: str) -> bool:
    return host.startswith("127.") or host in {"localhost", "::1"}


def require_api_token(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
) -> None:
    settings = get_settings()
    client_host = request.client.host if request.client else ""
    if settings.access_mode == "local" and is_loopback_host(client_host):
        return

    expected = settings.api_token
    if not expected:
        raise HTTPException(status_code=403, detail="Remote access token is not configured.")

    supplied = x_api_token or ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if supplied != expected:
        raise HTTPException(status_code=401, detail="Invalid API token.")


def command_is_allowed(command: str, allowed: Iterable[str]) -> bool:
    return Path(command).name.lower() in {Path(item).name.lower() for item in allowed}
