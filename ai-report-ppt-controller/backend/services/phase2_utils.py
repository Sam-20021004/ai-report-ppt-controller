from __future__ import annotations

import re
from datetime import datetime
from typing import Any


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def split_terms(value: str | None) -> list[str]:
    if not value:
        return []
    normalized = str(value)
    for separator in ("\u3001", "\uff0c", "\uff1b", "\n"):
        normalized = normalized.replace(separator, ",")
    return [item.strip() for item in re.split(r"[,;]+", normalized) if item.strip()]


def clean_text(value: Any, fallback: str = "", limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text).strip()
    if not text:
        text = fallback
    return text[:limit]


def language_code(value: str | None) -> str:
    text = (value or "").lower()
    if "en" in text or "english" in text:
        return "en"
    return "zh"


def output_type(request: Any) -> str:
    return {
        "ppt": "ppt",
        "word": "report",
        "ppt_word": "ppt_and_report",
        "research_only": "research_notes",
        "outline_only": "outline",
    }.get(request.task_type, request.task_type)


def unique_items(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        normalized = clean_text(value)
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result
