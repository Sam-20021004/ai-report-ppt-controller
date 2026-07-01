from __future__ import annotations

import uvicorn

from backend.app import app
from backend.config import get_settings


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(app, host=settings.bind_host, port=settings.port)
