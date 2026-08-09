from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, StrictInt


ROOT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = ROOT_DIR.parent
WORKSPACE_DIR = PROJECT_DIR.parent
STORAGE_DIR = Path(
    os.getenv("APP_STORAGE_DIR", str(WORKSPACE_DIR / "outputs" / "ai-report-ppt-controller-runtime"))
)
CONFIG_PATH = STORAGE_DIR / "config.json"


class AppConfig(BaseModel):
    app_name: str = "AI Report & PPT Agent Controller"
    access_mode: Literal["local", "lan", "public"] = "local"
    bind_host: str = "127.0.0.1"
    port: int = 7860
    api_token: str = Field(default_factory=lambda: os.getenv("APP_API_TOKEN", ""))
    codex_command: str = Field(default_factory=lambda: os.getenv("CODEX_COMMAND", "codex"))
    codex_mode: Literal["mock", "cli"] = Field(default_factory=lambda: os.getenv("CODEX_MODE", "mock"))
    codex_exec_args: str = Field(default_factory=lambda: os.getenv("CODEX_EXEC_ARGS", "exec"))
    codex_diagnostic_timeout_s: StrictInt = Field(
        default_factory=lambda: int(os.getenv("CODEX_DIAGNOSTIC_TIMEOUT_S", "300")),
        ge=30,
        le=900,
    )
    workflow_profile: Literal["legacy", "three_agent_v2"] = Field(
        default_factory=lambda: os.getenv("WORKFLOW_PROFILE", "three_agent_v2")
    )
    codex_test_prompt: str = "Return OK only."
    hermes_command: str = Field(default_factory=lambda: os.getenv("HERMES_COMMAND", "hermes"))
    hermes_endpoint: str = Field(default_factory=lambda: os.getenv("HERMES_ENDPOINT", ""))
    hermes_api_key_env: str = Field(default_factory=lambda: os.getenv("HERMES_API_KEY_ENV", "HERMES_API_KEY"))
    hermes_health_path: str = Field(default_factory=lambda: os.getenv("HERMES_HEALTH_PATH", "/health"))
    hermes_run_path: str = Field(default_factory=lambda: os.getenv("HERMES_RUN_PATH", "/run"))
    hermes_mode: Literal["mock", "api"] = Field(default_factory=lambda: os.getenv("HERMES_MODE", "mock"))
    hermes_test_prompt: str = "Return OK only."
    chatgpt_mode: Literal["mock", "cdp"] = Field(default_factory=lambda: os.getenv("CHATGPT_MODE", "mock"))
    chatgpt_use_new_chat: bool = Field(default_factory=lambda: os.getenv("CHATGPT_USE_NEW_CHAT", "1") == "1")
    chatgpt_reply_timeout_s: int = Field(
        default_factory=lambda: int(os.getenv("CHATGPT_REPLY_TIMEOUT_S", "600")),
        ge=30,
        le=1800,
    )
    planner_mode: Literal["hermes", "chatgpt"] = Field(default_factory=lambda: os.getenv("PLANNER_MODE", "hermes"))
    chrome_host: str = Field(default_factory=lambda: os.getenv("CHROME_CDP_HOST", "127.0.0.1"))
    chrome_port: int = Field(default_factory=lambda: int(os.getenv("CHROME_CDP_PORT", "9222")))
    pass_score: int = Field(default_factory=lambda: int(os.getenv("PASS_SCORE", "85")))
    max_review_rounds: int = Field(default_factory=lambda: int(os.getenv("MAX_REVIEW_ROUNDS", "3")))
    max_upload_mb: int = 50
    output_dir: str = str(STORAGE_DIR / "outputs")
    allow_remote_shell: bool = False


def _ensure_storage() -> None:
    for name in ("tasks", "templates", "outputs", "logs", "workspace", "workspace/jobs"):
        (STORAGE_DIR / name).mkdir(parents=True, exist_ok=True)


def _read_config_file() -> dict:
    _ensure_storage()
    if not CONFIG_PATH.exists():
        config = AppConfig()
        CONFIG_PATH.write_text(config.model_dump_json(indent=2), encoding="utf-8")
        return config.model_dump()
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        config = AppConfig()
        CONFIG_PATH.write_text(config.model_dump_json(indent=2), encoding="utf-8")
        return config.model_dump()


@lru_cache(maxsize=1)
def get_settings() -> AppConfig:
    data = _read_config_file()
    if os.getenv("APP_API_TOKEN"):
        data["api_token"] = os.getenv("APP_API_TOKEN")
    return AppConfig(**data)


def update_settings(patch: dict) -> AppConfig:
    current = get_settings().model_dump()
    allowed = set(AppConfig.model_fields)
    for key, value in patch.items():
        if key in allowed:
            current[key] = value
    updated = AppConfig(**current)
    _ensure_storage()
    CONFIG_PATH.write_text(updated.model_dump_json(indent=2), encoding="utf-8")
    get_settings.cache_clear()
    return updated
