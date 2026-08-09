from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

from backend.config import AppConfig
from backend.models.agent import AgentCheckResult
from backend.services import chatgpt_adapter
from backend.services.chatgpt_adapter import (
    ChatGPTAdapter,
    _extract_json_blocks,
    _wait_for_new_assistant_reply,
)


def plan_payload() -> dict[str, Any]:
    return {
        "task_understanding": "Test planning",
        "outline": [
            {"section": "One", "goal": "One"},
            {"section": "Two", "goal": "Two"},
            {"section": "Three", "goal": "Three"},
        ],
        "search_questions": ["technology", "competition", "risk"],
        "figures_needed": [],
        "risks": [],
        "success_criteria": ["traceable"],
        "language": "English",
    }


def test_extract_json_blocks_supports_pure_fenced_and_balanced_json():
    raw = '{"task_understanding":"x","outline":[]}'

    assert _extract_json_blocks(raw)[0]["task_understanding"] == "x"
    assert _extract_json_blocks(f"```json\n{raw}\n```")[0]["task_understanding"] == "x"
    assert _extract_json_blocks(f"Planning result:\n{raw}\nEnd.")[0]["task_understanding"] == "x"
    assert _extract_json_blocks("not a JSON response") == []


def test_adapter_passes_new_chat_and_timeout_settings(tmp_path, monkeypatch):
    captured: dict[str, Any] = {}
    settings = AppConfig(chatgpt_use_new_chat=False, chatgpt_reply_timeout_s=321)

    def fake_ask(prompt, received_settings, *, use_new_chat, timeout_s):
        captured.update(
            {
                "prompt": prompt,
                "settings": received_settings,
                "use_new_chat": use_new_chat,
                "timeout_s": timeout_s,
            }
        )
        return {"status": "success", "reply": __import__("json").dumps(plan_payload()), "elapsed_ms": 4}

    monkeypatch.setattr(chatgpt_adapter, "ask_chatgpt", fake_ask)

    response = ChatGPTAdapter(settings).run_task("planner", "prompt", tmp_path, {})

    assert response["status"] == "success"
    assert captured == {
        "prompt": "prompt",
        "settings": settings,
        "use_new_chat": False,
        "timeout_s": 321,
    }


def test_adapter_marks_invalid_json_as_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(
        chatgpt_adapter,
        "ask_chatgpt",
        lambda *args, **kwargs: {"status": "success", "reply": "not json", "elapsed_ms": 3},
    )

    response = ChatGPTAdapter(AppConfig()).run_task("planner", "prompt", tmp_path, {})

    assert response["status"] == "failed"
    assert response["error_code"] == "invalid_json"
    assert response["log_file"] == str(tmp_path / "logs" / "chatgpt_planner.log")


def test_adapter_preserves_structured_browser_error(tmp_path, monkeypatch):
    monkeypatch.setattr(
        chatgpt_adapter,
        "ask_chatgpt",
        lambda *args, **kwargs: {
            "status": "failed",
            "error_code": "reply_timeout",
            "error": "timed out",
            "reply": "partial",
            "elapsed_ms": 10,
        },
    )

    response = ChatGPTAdapter(AppConfig()).run_task("planner", "prompt", tmp_path, {})

    assert response["status"] == "failed"
    assert response["error_code"] == "reply_timeout"
    assert response["error"] == "timed out"


def test_health_check_reports_page_readiness_instead_of_only_cdp(monkeypatch):
    from backend.services import chrome_client

    monkeypatch.setattr(
        chrome_client,
        "check_chrome",
        lambda settings: AgentCheckResult(
            name="chrome_cdp",
            ok=True,
            status="success",
            detail="connected",
            elapsed_ms=2,
            metadata={"pages": []},
        ),
    )
    monkeypatch.setattr(
        chatgpt_adapter,
        "_inspect_chatgpt_session",
        lambda settings: {
            "name": "chatgpt",
            "ok": False,
            "status": "login_required",
            "detail": "ChatGPT login is required.",
            "elapsed_ms": 3,
        },
        raising=False,
    )

    result = ChatGPTAdapter(AppConfig(chatgpt_mode="cdp")).health_check()

    assert result["ok"] is False
    assert result["status"] == "login_required"


class FakeMessageLocator:
    def __init__(self, page: "FakePage"):
        self.page = page

    def count(self) -> int:
        if len(self.page.counts) > 1:
            return self.page.counts.popleft()
        return self.page.counts[0]

    def nth(self, index: int) -> "FakeMessageLocator":
        self.page.requested_indices.append(index)
        return self

    def inner_text(self) -> str:
        if len(self.page.texts) > 1:
            return self.page.texts.popleft()
        return self.page.texts[0] if self.page.texts else ""


class FakeStopLocator:
    def __init__(self, page: "FakePage"):
        self.page = page

    def count(self) -> int:
        if len(self.page.generating) > 1:
            return int(self.page.generating.popleft())
        return int(self.page.generating[0]) if self.page.generating else 0


class FakePage:
    def __init__(self, counts, texts=(), generating=()):
        self.counts = deque(counts)
        self.texts = deque(texts)
        self.generating = deque(generating)
        self.requested_indices: list[int] = []

    def locator(self, selector: str):
        if selector == '[data-message-author-role="assistant"]':
            return FakeMessageLocator(self)
        return FakeStopLocator(self)


def test_wait_for_new_reply_uses_only_post_send_message():
    page = FakePage(
        counts=[1, 2, 2, 2],
        texts=["new answer", "new answer", "new answer"],
        generating=[False, False, False],
    )

    result = _wait_for_new_assistant_reply(page, previous_count=1, timeout_s=0.1, poll_interval_s=0)

    assert result == {"status": "success", "reply": "new answer"}
    assert page.requested_indices and set(page.requested_indices) == {1}


def test_wait_for_new_reply_reports_not_started_when_count_never_increases():
    page = FakePage(counts=[1])

    result = _wait_for_new_assistant_reply(page, previous_count=1, timeout_s=0.001, poll_interval_s=0)

    assert result["status"] == "failed"
    assert result["error_code"] == "reply_not_started"


def test_wait_for_new_reply_reports_timeout_after_partial_generation():
    page = FakePage(counts=[2], texts=["partial", "still partial"], generating=[True])

    result = _wait_for_new_assistant_reply(page, previous_count=1, timeout_s=0.001, poll_interval_s=0)

    assert result["status"] == "failed"
    assert result["error_code"] == "reply_timeout"
    assert result["reply"] in {"partial", "still partial"}
