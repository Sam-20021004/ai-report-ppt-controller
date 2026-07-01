from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import get_settings
from backend.routers import check, config, download, health, task, upload


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0-phase1",
        description="Controller backend for Codex, Hermes, Chrome CLI, PPT and Word generation workflows.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(config.router)
    app.include_router(check.router)
    app.include_router(task.router)
    app.include_router(upload.router)
    app.include_router(download.router)
    return app


app = create_app()
