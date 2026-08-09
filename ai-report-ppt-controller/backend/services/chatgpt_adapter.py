from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.config import AppConfig, get_settings
from backend.services.agent_adapters import AgentAdapter

CHATGPT_URL = "https://chatgpt.com/"
POLL_INTERVAL_S = 2.0
REPLY_TIMEOUT_S = 600
PLAN_JSON_KEY = "plan"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _extract_json_blocks(text: str) -> list[dict]:
    """从 ChatGPT 回复中提取 JSON 块。"""
    blocks: list[dict] = []
    fence_pattern = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
    for match in fence_pattern.finditer(text):
        try:
            blocks.append(json.loads(match.group(1)))
        except json.JSONDecodeError:
            continue

    if not blocks:
        parsed = _json_loads_tolerant(text)
        if isinstance(parsed, dict):
            blocks.append(parsed)
        elif isinstance(parsed, list):
            blocks.append({"outline": parsed})

    if not blocks:
        for candidate in _balanced_json_candidates(text):
            parsed = _json_loads_tolerant(candidate)
            if isinstance(parsed, dict):
                blocks.append(parsed)
                break

    if not blocks:
        return []

    plan_keys = {"outline", "search_questions", "task_understanding", "figures_needed"}
    for block in blocks:
        if plan_keys & set(block.keys()):
            return [block]
    return [blocks[0]]


def _json_loads_tolerant(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fixed = _fix_unquoted_quotes(text)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        return None


def _fix_unquoted_quotes(text: str) -> str:
    n = len(text)
    out: list[str] = []
    in_string = False
    escape = False
    i = 0
    while i < n:
        ch = text[i]
        if escape:
            out.append(ch)
            escape = False
            i += 1
            continue
        if ch == "\\":
            out.append(ch)
            escape = True
            i += 1
            continue
        if ch == '"':
            if in_string:
                j = i + 1
                while j < n and text[j] in " \t\r\n":
                    j += 1
                nxt = text[j] if j < n else ""
                if nxt in ",}]:":
                    in_string = False
                    out.append(ch)
                else:
                    out.append('\\"')
            else:
                in_string = True
                out.append(ch)
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _balanced_json_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for idx, ch in enumerate(text):
        if ch != "{":
            continue
        depth = 0
        in_string = False
        escape = False
        for jdx in range(idx, len(text)):
            c = text[jdx]
            if in_string:
                if escape:
                    escape = False
                elif c == "\\":
                    escape = True
                elif c == '"':
                    in_string = False
                continue
            if c == '"':
                in_string = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[idx : jdx + 1])
                    break
    return candidates


def _wait_for_reply_complete(page: Any, timeout_s: float = REPLY_TIMEOUT_S) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            stop_visible = page.locator('[aria-label="停止回答"]').count() > 0
            if not stop_visible:
                return True
        except Exception:
            pass
        time.sleep(POLL_INTERVAL_S)
    return False


def _extract_last_assistant_text(page: Any) -> str:
    locator = page.locator('[data-message-author-role="assistant"]')
    count = locator.count()
    if count == 0:
        return ""
    return locator.nth(count - 1).inner_text()


def _send_prompt(page: Any, prompt: str) -> None:
    composer = page.locator(
        '#prompt-textarea, textarea[data-id], textarea[id*="prompt"], '
        'div[contenteditable="true"]'
    ).first
    composer.click()
    composer.fill(prompt)

    send_button = page.locator(
        'button[data-testid="send-button"], '
        'button[aria-label*="发送"], '
        'button[aria-label*="Send"]'
    ).first
    if send_button.count() > 0 and send_button.is_enabled():
        send_button.click()
        return
    composer.press("Enter")


def ask_chatgpt(
    prompt: str,
    settings: AppConfig | None = None,
    use_new_chat: bool = True,
    timeout_s: float = REPLY_TIMEOUT_S,
) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    settings = settings or get_settings()
    cdp_url = f"http://{settings.chrome_host}:{settings.chrome_port}"
    started = time.perf_counter()

    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = None
            for existing in context.pages:
                if existing.url.startswith(CHATGPT_URL):
                    page = existing
                    break
            if page is None:
                page = context.new_page()
                page.goto(CHATGPT_URL, wait_until="domcontentloaded", timeout=60_000)

            page.bring_to_front()
            if use_new_chat:
                new_chat = page.locator(
                    'a[href="/"], button[aria-label*="新聊天"], '
                    'button[aria-label*="New chat"], nav a:has-text("新聊天")'
                ).first
                try:
                    if new_chat.count() > 0:
                        new_chat.click()
                        time.sleep(1.5)
                except Exception:
                    pass

            _send_prompt(page, prompt)
            completed = _wait_for_reply_complete(page, timeout_s=timeout_s)
            reply = _extract_last_assistant_text(page)

            if not completed:
                return {
                    "status": "failed",
                    "error": f"ChatGPT 回复超时（>{timeout_s}s），已提取部分内容。",
                    "reply": reply,
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "url": page.url,
                }
            if not reply.strip():
                return {
                    "status": "failed",
                    "error": "ChatGPT 返回空回复。",
                    "reply": "",
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "url": page.url,
                }
            return {
                "status": "success",
                "reply": reply,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "url": page.url,
            }
    except Exception as exc:
        return {
            "status": "failed",
            "error": f"ChatGPT CDP 交互失败: {exc}",
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }


class ChatGPTAdapter(AgentAdapter):
    def __init__(self, settings: AppConfig | None = None):
        self.settings = settings or get_settings()

    def health_check(self) -> dict[str, Any]:
        from backend.services.chrome_client import check_chrome

        result = check_chrome(self.settings)
        if not result.ok:
            return {
                "name": "chatgpt",
                "ok": False,
                "status": "failed",
                "detail": f"Chrome CDP 不可用（{result.detail}）。ChatGPT 规划需要已登录的 chrome-debug-profile。",
                "elapsed_ms": result.elapsed_ms,
            }
        try:
            pages = result.metadata.get("pages") or []
            chatgpt_pages = [pg for pg in pages if "chatgpt.com" in (pg.get("url") or "")]
            return {
                "name": "chatgpt",
                "ok": True,
                "status": "success",
                "detail": f"Chrome CDP 已连接，{len(pages)} 个页面，{len(chatgpt_pages)} 个 chatgpt.com 页面。",
                "elapsed_ms": result.elapsed_ms,
                "metadata": {"chatgpt_pages": len(chatgpt_pages)},
            }
        except Exception as exc:
            return {
                "name": "chatgpt",
                "ok": False,
                "status": "failed",
                "detail": f"ChatGPT 检查失败: {exc}",
                "elapsed_ms": result.elapsed_ms,
            }

    def run_task(
        self,
        task_name: str,
        prompt: str,
        workspace: Path,
        extra_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = ask_chatgpt(prompt, self.settings)
        log_path = workspace / "logs" / f"chatgpt_{task_name}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(result.get("reply", ""), encoding="utf-8")

        if result.get("status") != "success":
            return {
                "status": "failed",
                "task_name": task_name,
                "error": result.get("error", "ChatGPT 交互失败"),
                "elapsed_ms": result.get("elapsed_ms", 0),
                "log_file": str(log_path),
            }

        reply = result["reply"]
        blocks = _extract_json_blocks(reply)
        parsed = blocks[0] if blocks else None
        payload: dict[str, Any] = {
            "raw_reply": reply,
            "reply_excerpt": reply[:2000],
            "elapsed_ms": result.get("elapsed_ms", 0),
            "log_file": str(log_path),
            "url": result.get("url", ""),
        }
        if parsed is not None:
            payload["result"] = parsed
            payload["parsed"] = True
        else:
            payload["result"] = {
                "task_understanding": reply[:500],
                "outline": [],
                "search_questions": [],
                "figures_needed": [],
                "risks": [],
                "success_criteria": [],
                "parse_failed": True,
            }
            payload["parsed"] = False
        return {"status": "success", "task_name": task_name, "result": payload}


class MockChatGPTAdapter(AgentAdapter):
    def __init__(self, settings: AppConfig | None = None):
        self.settings = settings or get_settings()

    def health_check(self) -> dict[str, Any]:
        return {
            "name": "chatgpt",
            "ok": True,
            "status": "mock",
            "detail": "ChatGPT 适配器处于 mock 模式（CHATGPT_MODE=mock）。",
        }

    def run_task(
        self,
        task_name: str,
        prompt: str,
        workspace: Path,
        extra_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = extra_context or {}
        request = context.get("request", {})
        title = request.get("title") or "未命名报告"
        domain = request.get("domain") or "通用"
        audience = request.get("audience") or "专业读者"
        language = request.get("language") or "中文"
        result = {
            "task_understanding": f"（Mock ChatGPT）围绕《{title}》生成面向{audience}的{domain}报告规划。",
            "outline": [
                {"section": "背景与问题定义", "goal": "界定主题、应用场景和报告边界"},
                {"section": "关键事实与证据", "goal": "整理公开资料、专利、论文和产业信息"},
                {"section": "竞争格局与风险", "goal": "归纳技术路线、主要参与方和不确定性"},
                {"section": "结论与建议", "goal": "形成可汇报的判断和行动建议"},
            ],
            "search_questions": [
                f"{title} 最新产业进展",
                f"{title} 专利 布局 竞争",
                f"{title} 技术路线 风险",
            ],
            "figures_needed": ["技术路线对比表", "主要机构/企业矩阵", "风险与建议优先级图"],
            "risks": ["公开资料时间滞后", "专利族口径不一致", "行业宣传材料可能带有偏向"],
            "success_criteria": ["结构完整", "事实有来源", "PPT可汇报", "Word可追溯"],
            "language": language,
        }
        return {
            "status": "success",
            "task_name": task_name,
            "result": {"result": result, "parsed": True, "raw_reply": json.dumps(result, ensure_ascii=False)},
        }
