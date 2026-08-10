from __future__ import annotations

from typing import Any


_GENERIC_FAILURE_STATUSES = {
    "success",
    "failed",
    "mock",
    "fallback",
    "missing",
}


def normalize_real_readiness(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    status = str(payload.get("status") or "failed")
    ok = bool(payload.get("ok")) and status == "success"
    result = {**payload, "name": name, "ok": ok, "status": status}
    if not ok and not result.get("error_code"):
        result["error_code"] = (
            f"{name}_{status}"
            if status not in _GENERIC_FAILURE_STATUSES
            else f"{name}_not_ready"
        )
    return result
