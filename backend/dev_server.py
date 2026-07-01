from __future__ import annotations

import runpy
from pathlib import Path


PROJECT_DEV_SERVER = (
    Path(__file__).resolve().parents[1]
    / "ai-report-ppt-controller"
    / "backend"
    / "dev_server.py"
)


if __name__ == "__main__":
    if not PROJECT_DEV_SERVER.exists():
        raise FileNotFoundError(f"Cannot find dev server: {PROJECT_DEV_SERVER}")
    runpy.run_path(str(PROJECT_DEV_SERVER), run_name="__main__")
