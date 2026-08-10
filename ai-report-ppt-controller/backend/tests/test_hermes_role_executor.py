from __future__ import annotations

import json
import socket
import sys
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.config import AppConfig
from backend.services import agent_adapters
from backend.services.agent_adapters import HermesAPIAdapter


@contextmanager
def bridge_server(response_payload, *, status: int = 200):
    received: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            received.append(json.loads(self.rfile.read(length).decode("utf-8")))
            body = json.dumps(response_payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def settings(endpoint: str) -> AppConfig:
    return AppConfig(hermes_mode="api", hermes_endpoint=endpoint)


def execution_result() -> dict:
    return {
        "schema_version": "role.execution.v1",
        "task_id": "task-001",
        "status": "success",
        "summary": "Silicon has atomic number 14.",
        "sources": [],
        "artifact_paths": ["hermes_execution.json"],
        "errors": [],
    }


def test_hermes_bridge_receives_role_execution_request(tmp_path) -> None:
    with bridge_server(execution_result()) as (endpoint, received):
        result = HermesAPIAdapter(settings(endpoint)).run_task(
            "role_executor",
            "execute task",
            tmp_path,
            {"task_id": "task-001"},
        )

    assert received == [
        {
            "task_name": "role_executor",
            "prompt": "execute task",
            "workspace": str(tmp_path),
            "extra_context": {"task_id": "task-001"},
        }
    ]
    assert result["status"] == "success"
    assert result["result"]["schema_version"] == "role.execution.v1"
    assert result["log_file"] == "logs/hermes_role_executor.log"


@pytest.mark.parametrize(
    ("status", "error_code"),
    [(401, "hermes_auth_failed"), (403, "hermes_auth_failed"), (502, "hermes_failed")],
)
def test_hermes_maps_http_errors(tmp_path, status: int, error_code: str) -> None:
    with bridge_server({"error": "bridge error"}, status=status) as (endpoint, _):
        result = HermesAPIAdapter(settings(endpoint)).run_task(
            "role_executor", "execute task", tmp_path
        )

    assert result["status"] == "failed"
    assert result["error_code"] == error_code


def test_hermes_maps_timeout(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        agent_adapters.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(socket.timeout("timed out")),
    )

    result = HermesAPIAdapter(settings("http://127.0.0.1:7788")).run_task(
        "role_executor", "execute task", tmp_path
    )

    assert result["error_code"] == "hermes_timeout"


def test_hermes_rejects_non_object_json(tmp_path) -> None:
    with bridge_server([execution_result()]) as (endpoint, _):
        result = HermesAPIAdapter(settings(endpoint)).run_task(
            "role_executor", "execute task", tmp_path
        )

    assert result["status"] == "failed"
    assert result["error_code"] == "hermes_invalid_result"
