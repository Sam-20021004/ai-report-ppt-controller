from __future__ import annotations

import sys
import types

import pytest
from pydantic import ValidationError

from backend import dev_server
from backend.config import AppConfig


try:
    import fastapi  # noqa: F401
except ModuleNotFoundError:
    class FakeRouter:
        def __init__(self, *args, **kwargs):
            self.routes = []

        def post(self, path, **kwargs):
            def decorator(function):
                self.routes.append(("POST", path, function))
                return function

            return decorator

    fake_fastapi = types.ModuleType("fastapi")
    fake_fastapi.APIRouter = FakeRouter
    fake_fastapi.Depends = lambda dependency: dependency
    sys.modules["fastapi"] = fake_fastapi

from backend.routers import check


@pytest.mark.parametrize("timeout", [30, 600, 1800])
def test_chatgpt_timeout_accepts_documented_range(timeout):
    assert AppConfig(chatgpt_reply_timeout_s=timeout).chatgpt_reply_timeout_s == timeout


@pytest.mark.parametrize("timeout", [0, 29, 1801, 99999])
def test_chatgpt_timeout_rejects_out_of_range_values(timeout):
    with pytest.raises(ValidationError):
        AppConfig(chatgpt_reply_timeout_s=timeout)


@pytest.mark.parametrize(
    "patch",
    [
        {"planner_mode": "unknown"},
        {"chatgpt_mode": "browser"},
        {"chatgpt_use_new_chat": "yes"},
        {"chatgpt_reply_timeout_s": 29},
        {"chatgpt_reply_timeout_s": 1801},
        {"chatgpt_reply_timeout_s": True},
    ],
)
def test_dev_server_rejects_invalid_chatgpt_config_patch(patch):
    with pytest.raises(ValueError):
        dev_server.validate_config_patch(patch)


def test_dev_server_normalizes_valid_chatgpt_config_patch():
    assert dev_server.validate_config_patch(
        {
            "planner_mode": "chatgpt",
            "chatgpt_mode": "cdp",
            "chatgpt_use_new_chat": False,
            "chatgpt_reply_timeout_s": 720,
            "unknown": "ignored",
        }
    ) == {
        "planner_mode": "chatgpt",
        "chatgpt_mode": "cdp",
        "chatgpt_use_new_chat": False,
        "chatgpt_reply_timeout_s": 720,
    }


def test_fastapi_chatgpt_check_uses_configured_adapter(monkeypatch):
    expected = {
        "name": "chatgpt",
        "ok": False,
        "status": "login_required",
        "detail": "Login required.",
        "elapsed_ms": 2,
    }

    class Adapter:
        def health_check(self):
            return expected

    monkeypatch.setattr(check, "make_chatgpt_adapter", lambda: Adapter())

    assert check.chatgpt() == expected


def test_dev_server_defaults_match_app_config():
    settings = AppConfig()

    assert dev_server.DEFAULT_CONFIG["planner_mode"] == settings.planner_mode
    assert dev_server.DEFAULT_CONFIG["chatgpt_mode"] == settings.chatgpt_mode
    assert dev_server.DEFAULT_CONFIG["chatgpt_use_new_chat"] == settings.chatgpt_use_new_chat
    assert dev_server.DEFAULT_CONFIG["chatgpt_reply_timeout_s"] == settings.chatgpt_reply_timeout_s
