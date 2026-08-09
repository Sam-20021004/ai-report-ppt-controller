from __future__ import annotations

import json
import mimetypes
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
STATIC_ROOT = PROJECT_ROOT / "frontend" / "static"
STORAGE_ROOT = Path(os.getenv("APP_STORAGE_DIR", str(PROJECT_ROOT.parent / "outputs" / "ai-report-ppt-controller-runtime")))
CONFIG_PATH = STORAGE_ROOT / "config.json"
DEFAULT_PORT = int(os.getenv("APP_PORT", "7860"))

sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import AppConfig
from backend.models.task import TaskRequest
from backend.services.agent_adapters import make_chatgpt_adapter
from backend.services.phase2_artifacts import build_phase2_audit_review, load_source_review, save_source_review_updates
from backend.services.task_runner import (
    create_task as workflow_create_task,
    list_task_summaries as workflow_list_task_summaries,
    list_task_files as workflow_list_task_files,
    load_record as workflow_load_record,
    run_workflow as workflow_run_workflow,
    save_record as workflow_save_record,
    task_dir as workflow_task_dir,
    update_task_status as workflow_update_task_status,
)

RUNNING_TASKS: dict[str, threading.Thread] = {}
RUNNING_TASKS_LOCK = threading.Lock()

WORKFLOW_STEPS = [
    ("连接检测", "system"),
    ("任务解析", "system"),
    ("生成检索式", "hermes"),
    ("联网搜索", "chrome"),
    ("资料归纳", "hermes"),
    ("生成大纲", "codex"),
    ("Hermes 初稿", "hermes"),
    ("Codex 格式化", "codex"),
    ("Hermes 审核", "hermes"),
    ("Codex 修改", "codex"),
    ("生成 PPT", "codex"),
    ("生成 Word", "codex"),
    ("最终质检", "system"),
    ("导出文件", "system"),
]

DEFAULT_CONFIG = {
    "app_name": "AI Report & PPT Agent Controller",
    "access_mode": "local",
    "bind_host": "127.0.0.1",
    "port": DEFAULT_PORT,
    "api_token": os.getenv("APP_API_TOKEN", ""),
    "codex_command": os.getenv("CODEX_COMMAND", "codex"),
    "codex_mode": os.getenv("CODEX_MODE", "mock"),
    "codex_exec_args": os.getenv("CODEX_EXEC_ARGS", "exec"),
    "codex_test_prompt": "Return OK only.",
    "hermes_command": os.getenv("HERMES_COMMAND", "hermes"),
    "hermes_endpoint": os.getenv("HERMES_ENDPOINT", ""),
    "hermes_api_key_env": os.getenv("HERMES_API_KEY_ENV", "HERMES_API_KEY"),
    "hermes_health_path": os.getenv("HERMES_HEALTH_PATH", "/health"),
    "hermes_run_path": os.getenv("HERMES_RUN_PATH", "/run"),
    "hermes_mode": os.getenv("HERMES_MODE", "mock"),
    "hermes_test_prompt": "Return OK only.",
    "chatgpt_mode": os.getenv("CHATGPT_MODE", "mock"),
    "chatgpt_use_new_chat": os.getenv("CHATGPT_USE_NEW_CHAT", "1") == "1",
    "chatgpt_reply_timeout_s": int(os.getenv("CHATGPT_REPLY_TIMEOUT_S", "600")),
    "planner_mode": os.getenv("PLANNER_MODE", "hermes"),
    "chrome_host": os.getenv("CHROME_CDP_HOST", "127.0.0.1"),
    "chrome_port": int(os.getenv("CHROME_CDP_PORT", "9222")),
    "pass_score": int(os.getenv("PASS_SCORE", "85")),
    "max_review_rounds": int(os.getenv("MAX_REVIEW_ROUNDS", "3")),
    "max_upload_mb": 50,
    "output_dir": str(STORAGE_ROOT / "outputs"),
    "allow_remote_shell": False,
}

ALLOWED_UPLOAD_EXTENSIONS = {".ppt", ".pptx", ".doc", ".docx", ".pdf", ".txt", ".md", ".csv", ".xlsx", ".xls"}


def ensure_storage() -> None:
    for folder in ["tasks", "templates", "outputs", "logs"]:
        (STORAGE_ROOT / folder).mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config() -> dict:
    ensure_storage()
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
        data = dict(DEFAULT_CONFIG)
    if os.getenv("APP_API_TOKEN"):
        data["api_token"] = os.getenv("APP_API_TOKEN")
    return {**DEFAULT_CONFIG, **data}


def validate_config_patch(patch: dict) -> dict:
    normalized = {key: value for key, value in patch.items() if key in DEFAULT_CONFIG}
    planner_mode = normalized.get("planner_mode")
    if planner_mode is not None and planner_mode not in {"hermes", "chatgpt"}:
        raise ValueError("planner_mode must be 'hermes' or 'chatgpt'.")
    chatgpt_mode = normalized.get("chatgpt_mode")
    if chatgpt_mode is not None and chatgpt_mode not in {"mock", "cdp"}:
        raise ValueError("chatgpt_mode must be 'mock' or 'cdp'.")
    use_new_chat = normalized.get("chatgpt_use_new_chat")
    if use_new_chat is not None and type(use_new_chat) is not bool:
        raise ValueError("chatgpt_use_new_chat must be a boolean.")
    timeout = normalized.get("chatgpt_reply_timeout_s")
    if timeout is not None and (type(timeout) is not int or not 30 <= timeout <= 1800):
        raise ValueError("chatgpt_reply_timeout_s must be an integer from 30 through 1800.")
    return normalized


def save_config(patch: dict) -> dict:
    data = load_config()
    data.update(validate_config_patch(patch))
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    redacted = dict(data)
    redacted["api_token"] = "***" if redacted.get("api_token") else ""
    return redacted


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    try:
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError) as exc:
        print(f"warning: client disconnected before response was sent: {handler.path} ({exc.__class__.__name__})")


def read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    if length == 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8", errors="replace"))


def source_review_response(task_id: str, review: dict) -> dict:
    return {
        "ok": True,
        "task_id": task_id,
        "items": review.get("items") or [],
        "summary": review.get("summary") or {},
        "updated_at": review.get("updated_at") or "",
        "warnings": review.get("warnings") or [],
    }


def _mark_background_failure(task_id: str, exc: Exception) -> None:
    try:
        record = workflow_load_record(task_id)
        record.status = "failed"
        if not any(step.status == "failed" for step in record.steps):
            for step in record.steps:
                if step.status in {"running", "waiting"}:
                    step.status = "failed"
                    step.ended_at = datetime.now().isoformat(timespec="seconds")
                    step.output_summary = "Background workflow failed."
                    step.error = str(exc)
                    break
        workflow_save_record(record)
    except Exception as mark_exc:
        print(f"warning: failed to persist background failure for task {task_id}: {mark_exc}")


def _run_workflow_background(task_id: str) -> None:
    try:
        workflow_run_workflow(task_id)
    except Exception as exc:
        _mark_background_failure(task_id, exc)
        print(f"warning: background workflow failed for task {task_id}: {exc}")
    finally:
        with RUNNING_TASKS_LOCK:
            if RUNNING_TASKS.get(task_id) is threading.current_thread():
                RUNNING_TASKS.pop(task_id, None)


def start_workflow_background(task_id: str):
    with RUNNING_TASKS_LOCK:
        existing = RUNNING_TASKS.get(task_id)
        if existing and existing.is_alive():
            return workflow_load_record(task_id)
        RUNNING_TASKS.pop(task_id, None)

        record = workflow_load_record(task_id)
        record.status = "running"
        workflow_save_record(record)

        thread = threading.Thread(target=_run_workflow_background, args=(task_id,), daemon=True, name=f"task-{task_id[:8]}")
        RUNNING_TASKS[task_id] = thread
        thread.start()
        return record


def safe_join(base: Path, relative: str) -> Path:
    root = base.resolve()
    target = root.joinpath(relative).resolve()
    if root != target and root not in target.parents:
        raise PermissionError("Path escapes storage root.")
    return target


def default_steps() -> list[dict]:
    return [
        {
            "index": index + 1,
            "step_name": name,
            "agent": agent,
            "status": "waiting",
            "started_at": None,
            "ended_at": None,
            "elapsed_ms": None,
            "input": None,
            "output": None,
            "output_summary": "",
            "error": "",
        }
        for index, (name, agent) in enumerate(WORKFLOW_STEPS)
    ]


def task_dir(task_id: str) -> Path:
    return safe_join(STORAGE_ROOT / "tasks", task_id)


def task_request_file(task_id: str) -> Path:
    return safe_join(STORAGE_ROOT / "tasks", f"{task_id}.request.json")


def task_log_file(task_id: str) -> Path:
    return safe_join(STORAGE_ROOT / "tasks", f"{task_id}.task_log.json")


def load_task(task_id: str) -> dict:
    path = task_log_file(task_id)
    if not path.exists():
        raise FileNotFoundError("Task not found.")
    return json.loads(path.read_text(encoding="utf-8"))


def save_task(record: dict) -> None:
    record["updated_at"] = datetime.now().isoformat(timespec="seconds")
    task_log_file(record["task_id"]).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


def create_task(payload: dict) -> dict:
    task_id = payload.get("task_id") or uuid4().hex
    payload["task_id"] = task_id
    payload.setdefault("task_type", "ppt")
    payload.setdefault("domain", "AI")
    payload.setdefault("audience", "企业技术部门")
    payload.setdefault("language", "中文")
    payload.setdefault("main_agent", "auto")
    payload.setdefault("review_agent", "auto")
    payload.setdefault("loop_rounds", 1)
    payload.setdefault("enable_web_search", True)
    payload.setdefault("enable_patent_search", False)
    payload.setdefault("enable_paper_search", False)
    payload.setdefault("enable_industry_search", True)
    payload.setdefault("output_dir", str(STORAGE_ROOT / "outputs" / task_id))

    task_request_file(task_id).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    now = datetime.now().isoformat(timespec="seconds")
    record = {
        "task_id": task_id,
        "created_at": now,
        "updated_at": now,
        "status": "waiting",
        "request": payload,
        "steps": default_steps(),
        "generated_files": [],
        "final_quality_check": {},
    }
    save_task(record)
    return record


def mark_step(step: dict, status: str, summary: str, output=None, error: str = "") -> None:
    started = time.perf_counter()
    step["started_at"] = step["started_at"] or datetime.now().isoformat(timespec="seconds")
    step["status"] = status
    step["output_summary"] = summary
    step["output"] = output
    step["error"] = error
    step["ended_at"] = datetime.now().isoformat(timespec="seconds")
    step["elapsed_ms"] = int((time.perf_counter() - started) * 1000)


def run_phase1(task_id: str) -> dict:
    record = load_task(task_id)
    request = record["request"]
    record["status"] = "needs_review"
    mark_step(record["steps"][0], "success", "连接检测入口已初始化，可分别检测 Codex、Hermes 和 Chrome CDP。")
    mark_step(record["steps"][1], "success", f"任务类型：{request.get('task_type')}；领域：{request.get('domain')}；语言：{request.get('language')}。", request)
    mark_step(record["steps"][2], "success", "已生成占位检索计划；Phase 2 将交由 Hermes 生成标准 JSON。", {
        "keywords": request.get("keywords"),
        "search_boundary": request.get("search_boundary"),
        "enable_patent_search": request.get("enable_patent_search"),
        "enable_paper_search": request.get("enable_paper_search"),
        "enable_industry_search": request.get("enable_industry_search"),
    })
    mark_step(record["steps"][3], "needs_review", "联网搜索执行器留待 Phase 2/Chrome CLI 集成。")
    mark_step(record["steps"][5], "success", "已保存用户输入框架，可用于后续 PPT/Word 生成。", request.get("user_outline"))
    save_task(record)
    return record


def check_command(name: str, command: str, allowed: set[str]) -> dict:
    started = time.perf_counter()
    if Path(command).name.lower() not in allowed:
        return {"name": name, "ok": False, "status": "blocked", "detail": "Command is not whitelisted.", "elapsed_ms": 0}
    resolved = shutil.which(command) or (command if Path(command).exists() else None)
    if not resolved:
        return {"name": name, "ok": False, "status": "missing", "command": command, "detail": "Command was not found on PATH.", "elapsed_ms": 0}
    try:
        completed = subprocess.run([resolved, "--version"], capture_output=True, text=True, timeout=10, shell=False, encoding="utf-8", errors="replace")
        raw = (completed.stdout + completed.stderr).strip()
        return {
            "name": name,
            "ok": completed.returncode == 0,
            "status": "success" if completed.returncode == 0 else "failed",
            "command": resolved,
            "version": raw.splitlines()[0] if raw else None,
            "raw_output": raw,
            "detail": f"exit_code={completed.returncode}",
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
    except subprocess.TimeoutExpired:
        return {"name": name, "ok": False, "status": "timeout", "command": resolved, "detail": "Command timed out.", "elapsed_ms": int((time.perf_counter() - started) * 1000)}
    except OSError as exc:
        return {"name": name, "ok": False, "status": "blocked", "command": resolved, "detail": str(exc), "elapsed_ms": int((time.perf_counter() - started) * 1000)}


def chrome_launch_commands(port: int) -> dict:
    return {
        "windows": f'"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port={port} --remote-allow-origins=* --user-data-dir="D:\\chrome-debug-profile"',
        "wsl": f"/mnt/c/Program\\ Files/Google/Chrome/Application/chrome.exe --remote-debugging-port={port} --remote-allow-origins=* --user-data-dir=/mnt/d/chrome-debug-profile",
    }


def check_chrome() -> dict:
    config = load_config()
    started = time.perf_counter()
    url = f"http://{config['chrome_host']}:{config['chrome_port']}/json"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            pages = json.loads(response.read().decode("utf-8", errors="replace"))
        return {
            "name": "chrome_cdp",
            "ok": True,
            "status": "success",
            "detail": f"Connected to {url}",
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "metadata": {"page_count": len(pages), "pages": pages, "launch_commands": chrome_launch_commands(config["chrome_port"])},
        }
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return {
            "name": "chrome_cdp",
            "ok": False,
            "status": "failed",
            "detail": f"Cannot connect to {url}: {exc}",
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "metadata": {"launch_commands": chrome_launch_commands(config["chrome_port"])},
        }


def parse_multipart_files(handler: BaseHTTPRequestHandler) -> list[dict]:
    content_type = handler.headers.get("Content-Type", "")
    marker = "boundary="
    if marker not in content_type:
        raise ValueError("Upload boundary is missing.")
    boundary = content_type.split(marker, 1)[1].strip().strip('"')
    length = int(handler.headers.get("Content-Length", "0"))
    config = load_config()
    if length > int(config["max_upload_mb"]) * 1024 * 1024:
        raise ValueError("Upload exceeds size limit.")

    body = handler.rfile.read(length)
    delimiter = b"--" + boundary.encode()
    files = []
    for part in body.split(delimiter):
        if b"\r\n\r\n" not in part or b'filename="' not in part:
            continue
        header, content = part.split(b"\r\n\r\n", 1)
        if content.endswith(b"\r\n"):
            content = content[:-2]
        header_text = header.decode("utf-8", errors="replace")
        filename = header_text.split('filename="', 1)[1].split('"', 1)[0]
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
            raise ValueError(f"Unsupported file type: {suffix}")
        files.append({"filename": Path(filename).name, "content": content})
    return files


class Handler(BaseHTTPRequestHandler):
    server_version = "AIReportPPTDevServer/0.1"

    def do_GET(self) -> None:
        try:
            self.route_get()
        except Exception as exc:
            json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Request failed", "detail": str(exc)})

    def do_POST(self) -> None:
        try:
            self.route_post()
        except Exception as exc:
            json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Request failed", "detail": str(exc)})

    def route_get(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in {"/api/health", "/health"}:
            config = load_config()
            return json_response(self, 200, {
                "ok": True,
                "app": config["app_name"],
                "phase": "MVP workflow",
                "access_mode": config["access_mode"],
                "storage": {"root": str(STORAGE_ROOT), "writable": os.access(STORAGE_ROOT, os.W_OK)},
                "capabilities": {
                    "task_create": True,
                    "task_run": True,
                    "mock_hermes": True,
                    "mock_codex": True,
                    "task_logs": True,
                    "chrome_cdp_check": True,
                    "codex_check": True,
                    "hermes_check": True,
                },
            })
        if path == "/favicon.ico":
            self.send_response(204)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        if path == "/api/config":
            config = load_config()
            config["api_token"] = "***" if config.get("api_token") else ""
            return json_response(self, 200, config)
        if path == "/api/tasks":
            return json_response(self, 200, {"tasks": workflow_list_task_summaries()})
        if path.startswith("/api/tasks/"):
            parts = path.strip("/").split("/")
            task_id = parts[2] if len(parts) > 2 else ""
            if len(parts) >= 5 and parts[3] == "phase2" and parts[4] == "source-review":
                task_root = workflow_task_dir(task_id)
                if not task_root.exists():
                    return json_response(self, 404, {"ok": False, "error": "Task not found."})
                review = load_source_review(task_id, task_root)
                return json_response(self, 200, source_review_response(task_id, review))
        if path.startswith("/api/task/"):
            parts = path.strip("/").split("/")
            task_id = parts[2]
            record = workflow_load_record(task_id).model_dump()
            if len(parts) == 3:
                return json_response(self, 200, record)
            if parts[3] == "logs":
                return json_response(self, 200, {"task_id": task_id, "status": record["status"], "steps": record["steps"]})
            if parts[3] == "files":
                files = workflow_list_task_files(task_id)
                return json_response(self, 200, {"task_id": task_id, "files": files})
            if len(parts) >= 5 and parts[3] == "phase2" and parts[4] == "audit":
                return json_response(self, 200, build_phase2_audit_review(task_id, workflow_task_dir(task_id)))
        if path.startswith("/api/download/"):
            file_id = urllib.parse.unquote(path.replace("/api/download/", "", 1))
            target = safe_join(STORAGE_ROOT, file_id)
            if not target.exists() or not target.is_file():
                return json_response(self, 404, {"error": "File not found."})
            mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Disposition", f'attachment; filename="{target.name}"')
            self.send_header("Content-Length", str(target.stat().st_size))
            self.end_headers()
            self.wfile.write(target.read_bytes())
            return
        return self.serve_static(path)

    def route_post(self) -> None:
        path = self.path.split("?", 1)[0]
        config = load_config()
        if path == "/api/config/update":
            try:
                return json_response(self, 200, save_config(read_json(self)))
            except ValueError as exc:
                return json_response(self, 422, {"error": "Invalid config", "detail": str(exc)})
        if path == "/api/check/codex":
            return json_response(self, 200, check_command("codex", config["codex_command"], {"codex"}))
        if path == "/api/check/hermes":
            return json_response(self, 200, check_command("hermes", config["hermes_command"], {"hermes"}))
        if path == "/api/check/chrome":
            return json_response(self, 200, check_chrome())
        if path == "/api/check/chatgpt":
            settings = AppConfig(**load_config())
            return json_response(self, 200, make_chatgpt_adapter(settings).health_check())
        if path == "/api/task/create":
            return json_response(self, 200, workflow_create_task(TaskRequest(**read_json(self))).model_dump())
        if path.startswith("/api/tasks/"):
            parts = path.strip("/").split("/")
            task_id = parts[2] if len(parts) > 2 else ""
            if len(parts) >= 5 and parts[3] == "phase2" and parts[4] == "source-review":
                task_root = workflow_task_dir(task_id)
                if not task_root.exists():
                    return json_response(self, 404, {"ok": False, "error": "Task not found."})
                payload = read_json(self)
                try:
                    review = save_source_review_updates(task_id, task_root, payload.get("items") or [])
                except ValueError as exc:
                    return json_response(self, 400, {"ok": False, "error": "Invalid source review payload.", "detail": str(exc)})
                return json_response(self, 200, source_review_response(task_id, review))
        if path.startswith("/api/task/"):
            parts = path.strip("/").split("/")
            task_id = parts[2]
            action = parts[3] if len(parts) > 3 else ""
            if action == "run":
                return json_response(self, 200, start_workflow_background(task_id).model_dump())
            record = workflow_load_record(task_id)
            if action == "pause":
                return json_response(self, 200, workflow_update_task_status(task_id, "paused").model_dump())
            elif action == "cancel":
                return json_response(self, 200, workflow_update_task_status(task_id, "cancelled").model_dump())
            elif action == "rerun-step":
                payload = read_json(self)
                index = max(1, int(payload.get("step_index", 1))) - 1
                if index < len(record.steps):
                    record.steps[index].status = "waiting"
                    record.steps[index].started_at = None
                    record.steps[index].ended_at = None
                    record.steps[index].elapsed_ms = None
                    record.steps[index].output_summary = "已标记为待重跑。"
                    record.steps[index].error = ""
                workflow_save_record(record)
            return json_response(self, 200, record.model_dump())
        if path.startswith("/api/upload/"):
            files = parse_multipart_files(self)
            category = path.replace("/api/upload/", "").replace("/", "_")
            target_dir = STORAGE_ROOT / "templates"
            saved = []
            for item in files:
                file_id = uuid4().hex
                stored_name = f"{category}-{file_id}-{item['filename']}"
                target = target_dir / stored_name
                target.write_bytes(item["content"])
                saved.append({"file_id": file_id, "file_name": item["filename"], "stored_name": stored_name, "category": category, "path": str(target), "size": len(item["content"])})
            return json_response(self, 200, {"ok": True, "files": saved})
        return json_response(self, 404, {"error": "Not found."})

    def serve_static(self, path: str) -> None:
        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        if relative.startswith("static/"):
            relative = relative.removeprefix("static/")
        target = safe_join(STATIC_ROOT, relative)
        if not target.exists() or not target.is_file():
            return json_response(self, 404, {"error": "Not found."})
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".css":
            mime = "text/css; charset=utf-8"
        elif target.suffix == ".js":
            mime = "application/javascript; charset=utf-8"
        elif target.suffix == ".html":
            mime = "text/html; charset=utf-8"
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")


def main() -> None:
    ensure_storage()
    config = load_config()
    host = config.get("bind_host") or "127.0.0.1"
    port = int(config.get("port") or DEFAULT_PORT)
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"AI Report & PPT Agent Controller MVP workflow running at http://{host}:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
