from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from backend.config import AppConfig, get_settings
from backend.models.agent import AgentCheckResult


def chrome_launch_commands(config: AppConfig | None = None) -> dict:
    settings = config or get_settings()
    port = settings.chrome_port
    return {
        "windows": (
            '"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" '
            f"--remote-debugging-port={port} --remote-allow-origins=* "
            '--user-data-dir="D:\\chrome-debug-profile"'
        ),
        "wsl": (
            "/mnt/c/Program\\ Files/Google/Chrome/Application/chrome.exe "
            f"--remote-debugging-port={port} --remote-allow-origins=* "
            "--user-data-dir=/mnt/d/chrome-debug-profile"
        ),
    }


def get_pages(config: AppConfig | None = None) -> list[dict]:
    settings = config or get_settings()
    url = f"http://{settings.chrome_host}:{settings.chrome_port}/json"
    with urllib.request.urlopen(url, timeout=5) as response:
        body = response.read().decode("utf-8", errors="replace")
    data = json.loads(body)
    return data if isinstance(data, list) else []


def check_chrome(config: AppConfig | None = None) -> AgentCheckResult:
    settings = config or get_settings()
    started = time.perf_counter()
    try:
        pages = get_pages(settings)
        elapsed = int((time.perf_counter() - started) * 1000)
        return AgentCheckResult(
            name="chrome_cdp",
            ok=True,
            status="success",
            detail=f"Connected to {settings.chrome_host}:{settings.chrome_port}.",
            elapsed_ms=elapsed,
            metadata={
                "page_count": len(pages),
                "pages": pages,
                "launch_commands": chrome_launch_commands(settings),
            },
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        return AgentCheckResult(
            name="chrome_cdp",
            ok=False,
            status="failed",
            detail=f"Cannot connect to {settings.chrome_host}:{settings.chrome_port}: {exc}",
            elapsed_ms=elapsed,
            metadata={"launch_commands": chrome_launch_commands(settings)},
        )
