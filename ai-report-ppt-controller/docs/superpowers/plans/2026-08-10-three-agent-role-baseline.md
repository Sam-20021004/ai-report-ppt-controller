# Three-Agent Role Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove a real, auditable handoff from Windows Codex planning to WSL Hermes execution and back to Windows Codex finalization, while verifying that the browser ChatGPT reviewer is ready without sending it a message.

**Architecture:** Add strict role contracts, workspace artifact guards, a Windows-only Codex adapter, readiness normalization, and a focused `RoleBaselineService` outside the existing `task_runner.py`. Expose the diagnostic through matching FastAPI and static-development-server endpoints, then add a fixed-role UI card and an opt-in live smoke test.

**Tech Stack:** Python 3.11+, Pydantic 2, pytest, FastAPI, Python `subprocess` and `urllib`, Chrome CDP through the existing ChatGPT adapter, browser-free Node test runner, HTML/CSS/vanilla JavaScript.

## Global Constraints

- Execute this plan in a new isolated worktree and branch created from the clean commit containing this plan, which must descend from `b4a1257`; do not implement inside the dirty `codex/chatgpt-planner-stabilization` worktree.
- Preserve the existing dirty worktree unchanged. It contains experimental Hermes recovery work that is evidence, not the implementation baseline.
- Windows Codex is the planner, finalizer, and later report builder/reviser. Production baseline checks must reject `codex_command` values beginning with `wsl:`.
- WSL Hermes is the task executor and is reached only through the configured HTTP bridge, normally `http://127.0.0.1:7788`.
- Browser ChatGPT is the reviewer. Its readiness check must not send a message.
- `mock`, `fallback`, `missing`, and `failed` never count as a successful real baseline.
- Diagnostic prompts use only repository-owned nonsensitive text. Never persist cookies, tokens, authorization headers, full browser HTML, or paths outside the diagnostic workspace.
- Every accepted artifact path is relative, remains inside the diagnostic workspace after resolution, was created or changed during the current call, and has a recorded SHA-256.
- This milestone does not implement production PPTX/DOCX generation, real ChatGPT review, search-provider work, or the complete one-click workflow.
- Use test-first red-green-refactor for every behavior change.
- Run pytest with `-p no:cacheprovider` and a new repository-local `--basetemp` path.
- Use `C:\Users\27235\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe` for static JavaScript tests.
- Do not modify the repository-root `server.js`.

## File Structure

- Create `backend/services/role_contracts.py`: Pydantic contracts for Codex plans, Hermes results, Codex finalization, ChatGPT reviews, attempts, traces, and service results.
- Create `backend/services/role_artifacts.py`: relative-path validation, safe workspace resolution, fingerprints, changed-artifact loading, and SHA-256 manifest entries.
- Create `backend/services/windows_codex_adapter.py`: Windows-native command resolution, version readiness, inference execution, stable error codes, JSON parsing, and redacted logs.
- Create `backend/services/agent_readiness.py`: normalize Codex, Hermes, and ChatGPT checks and reject non-real modes.
- Create `backend/services/role_baseline_service.py`: diagnostic workspace creation, ordered three-step handoff, contract checks, trace persistence, and public service result.
- Create `backend/routers/role_baseline.py`: FastAPI endpoint for an explicitly requested baseline run.
- Modify `backend/config.py`: add the `three_agent_v2` workflow profile and a bounded Codex diagnostic timeout.
- Modify `backend/app.py`: register the role-baseline router.
- Modify `backend/dev_server.py`: mirror config validation and the role-baseline endpoint.
- Modify `frontend/static/index.html`, `app.js`, and `styles.css`: fixed-role display, explicit run button, results, and remediation text.
- Modify `frontend/static/app.restore.test.js`: browser-free coverage for profile loading and baseline execution.
- Modify `.env.example` and `docs/usage.md`: exact Windows Codex, WSL Hermes, ChatGPT CDP, privacy, and live-smoke instructions.
- Create focused tests under `backend/tests/` for each new module plus an opt-in real smoke test.

---

### Task 1: Add Strict Role Contracts and Workspace Artifact Guards

**Files:**
- Create: `ai-report-ppt-controller/backend/services/role_contracts.py`
- Create: `ai-report-ppt-controller/backend/services/role_artifacts.py`
- Create: `ai-report-ppt-controller/backend/tests/test_role_contracts.py`
- Create: `ai-report-ppt-controller/backend/tests/test_role_artifacts.py`

**Interfaces:**
- Produces: `validate_role_plan(payload) -> dict`, `validate_hermes_execution(payload) -> dict`, `validate_codex_finalization(payload) -> dict`, and `validate_chatgpt_review(payload) -> dict`.
- Produces: `safe_artifact_path(workspace, relative_path) -> Path`, `fingerprint(path) -> str | None`, `load_changed_json(path, before_hash) -> dict`, and `artifact_manifest_entry(workspace, path) -> dict`.
- Consumed by: Tasks 2, 4, 5, and 7.

- [ ] **Step 1: Write failing role-contract tests**

Add tests that exercise real Pydantic validation rather than mocks:

```python
def valid_plan() -> dict:
    return {
        "schema_version": "role.plan.v1",
        "objective": "Validate the handoff",
        "tasks": [{
            "task_id": "task-001",
            "instruction": "Summarize the diagnostic source",
            "inputs": ["input/diagnostic_source.md"],
            "dependencies": [],
            "expected_outputs": ["hermes_execution.json"],
            "acceptance_criteria": ["Return a non-empty summary"],
        }],
        "final_outputs": ["diagnostic_final.md"],
    }


def test_role_plan_accepts_the_documented_contract():
    assert validate_role_plan(valid_plan())["tasks"][0]["task_id"] == "task-001"


@pytest.mark.parametrize("path", ["../escape.json", "C:\\outside.json", "/tmp/outside.json"])
def test_role_plan_rejects_unsafe_artifact_paths(path):
    payload = valid_plan()
    payload["tasks"][0]["expected_outputs"] = [path]
    with pytest.raises(RoleContractError) as exc_info:
        validate_role_plan(payload)
    assert exc_info.value.issues[0]["code"] == "artifact_path.unsafe"


def test_hermes_success_requires_summary():
    with pytest.raises(RoleContractError):
        validate_hermes_execution({
            "schema_version": "role.execution.v1",
            "task_id": "task-001",
            "status": "success",
            "summary": "",
            "sources": [],
            "artifact_paths": ["hermes_execution.json"],
            "errors": [],
        })


def test_chatgpt_review_requires_numeric_score_and_boolean_pass():
    with pytest.raises(RoleContractError):
        validate_chatgpt_review({
            "schema_version": "role.review.v1",
            "score": "85",
            "pass": "yes",
            "blocking_issues": [],
            "minor_issues": [],
            "revision_instruction": "",
        })
```

- [ ] **Step 2: Run the contract tests and verify RED**

Run from `ai-report-ppt-controller`:

```powershell
python -m pytest backend/tests/test_role_contracts.py -q -p no:cacheprovider --basetemp=D:\codex-project\APP\tmp\pytest-role-contracts-red
```

Expected: collection fails because `backend.services.role_contracts` does not exist.

- [ ] **Step 3: Implement the contracts**

Implement exact schema names and a stable error wrapper:

```python
def _safe_relative_path(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    path = PurePosixPath(text)
    if not text or path.is_absolute() or PureWindowsPath(str(value or "")).is_absolute() or ".." in path.parts:
        raise PydanticCustomError("artifact_path.unsafe", "Artifact path must be relative to the diagnostic workspace")
    return path.as_posix()


NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
SafeRelativePath = Annotated[str, BeforeValidator(_safe_relative_path)]


class RoleTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: NonEmptyText
    instruction: NonEmptyText
    inputs: list[SafeRelativePath]
    dependencies: list[NonEmptyText]
    expected_outputs: list[SafeRelativePath] = Field(min_length=1)
    acceptance_criteria: list[NonEmptyText] = Field(min_length=1)


class RolePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["role.plan.v1"]
    objective: NonEmptyText
    tasks: list[RoleTask] = Field(min_length=1)
    final_outputs: list[SafeRelativePath] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_task_ids(self) -> "RolePlan":
        ids = [task.task_id for task in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("task_id values must be unique")
        known = set(ids)
        if any(dep not in known for task in self.tasks for dep in task.dependencies):
            raise ValueError("dependencies must reference task_id values in the same plan")
        return self


class HermesExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["role.execution.v1"]
    task_id: NonEmptyText
    status: Literal["success", "failed"]
    summary: str
    sources: list[dict[str, Any]]
    artifact_paths: list[SafeRelativePath]
    errors: list[dict[str, Any]]

    @model_validator(mode="after")
    def success_has_summary(self) -> "HermesExecutionResult":
        if self.status == "success" and not self.summary.strip():
            raise ValueError("summary is required when status is success")
        return self


class CodexFinalizationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["role.finalization.v1"]
    status: Literal["success", "failed"]
    summary: str
    artifact_paths: list[SafeRelativePath]
    errors: list[dict[str, Any]]


class ChatGPTReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["role.review.v1"]
    score: float = Field(ge=0, le=100)
    passed: bool = Field(alias="pass")
    blocking_issues: list[dict[str, Any]]
    minor_issues: list[dict[str, Any]]
    revision_instruction: str


class RoleAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent: Literal["codex", "hermes", "chatgpt"]
    operation: NonEmptyText
    status: Literal["success", "failed", "mock", "fallback", "missing"]
    error_code: str | None = None
    elapsed_ms: int = Field(ge=0)
    artifact_paths: list[SafeRelativePath]


class RoleBaselineTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["role.baseline.trace.v1"]
    run_id: NonEmptyText
    status: Literal["success", "failed"]
    error_code: str | None = None
    started_at: NonEmptyText
    completed_at: NonEmptyText
    attempts: list[RoleAttempt]
    artifacts: list[dict[str, Any]]
```

Catch `ValidationError` in each public validator and raise `RoleContractError(issues)` with path, code, and message. Each public validator returns `model_dump(by_alias=True)` so the serialized ChatGPT field remains exactly `pass`, not `passed`. Preserve `artifact_path.unsafe` from `PydanticCustomError`; map other errors to `<field>.required`, `<field>.type_error`, or `<field>.invalid`.

- [ ] **Step 4: Write failing workspace-artifact tests**

```python
def test_safe_artifact_path_stays_inside_workspace(tmp_path):
    assert safe_artifact_path(tmp_path, "execution/result.json") == tmp_path / "execution" / "result.json"


@pytest.mark.parametrize("value", ["../escape.json", "C:\\escape.json", "/escape.json"])
def test_safe_artifact_path_rejects_escape(tmp_path, value):
    with pytest.raises(ArtifactBoundaryError):
        safe_artifact_path(tmp_path, value)


def test_load_changed_json_rejects_an_unchanged_file(tmp_path):
    path = tmp_path / "result.json"
    path.write_text('{"status":"success"}', encoding="utf-8")
    before = fingerprint(path)
    with pytest.raises(ArtifactNotChangedError):
        load_changed_json(path, before)


def test_manifest_entry_uses_relative_path_and_sha256(tmp_path):
    path = tmp_path / "result.json"
    path.write_text("{}", encoding="utf-8")
    entry = artifact_manifest_entry(tmp_path, path)
    assert entry == {
        "path": "result.json",
        "sha256": hashlib.sha256(b"{}").hexdigest(),
        "size": 2,
    }
```

- [ ] **Step 5: Run artifact tests and verify RED**

```powershell
python -m pytest backend/tests/test_role_artifacts.py -q -p no:cacheprovider --basetemp=D:\codex-project\APP\tmp\pytest-role-artifacts-red
```

Expected: collection fails because `backend.services.role_artifacts` does not exist.

- [ ] **Step 6: Implement workspace guards and verify GREEN**

Implement `safe_artifact_path` with `Path.resolve(strict=False)` plus `candidate.relative_to(workspace.resolve())`; implement `fingerprint` with SHA-256; require a changed fingerprint before JSON loading; and return only POSIX relative paths from `artifact_manifest_entry`.

Run:

```powershell
python -m pytest backend/tests/test_role_contracts.py backend/tests/test_role_artifacts.py -q -p no:cacheprovider --basetemp=D:\codex-project\APP\tmp\pytest-role-foundation-green
```

Expected: all role contract and artifact tests pass.

- [ ] **Step 7: Commit Task 1**

```powershell
git add -- ai-report-ppt-controller/backend/services/role_contracts.py ai-report-ppt-controller/backend/services/role_artifacts.py ai-report-ppt-controller/backend/tests/test_role_contracts.py ai-report-ppt-controller/backend/tests/test_role_artifacts.py
git commit -m "feat: add three-agent role contracts"
```

### Task 2: Add a Windows-Native Codex Diagnostic Adapter

**Files:**
- Create: `ai-report-ppt-controller/backend/services/windows_codex_adapter.py`
- Create: `ai-report-ppt-controller/backend/tests/test_windows_codex_adapter.py`
- Modify: `ai-report-ppt-controller/backend/config.py`

**Interfaces:**
- Consumes: `AppConfig.codex_command`, `AppConfig.codex_exec_args`, and `AppConfig.codex_diagnostic_timeout_s`.
- Produces: `resolve_windows_codex(command) -> str | None`, `WindowsCodexAdapter.health_check() -> dict`, `WindowsCodexAdapter.run_task(...) -> dict`, and `make_windows_codex_adapter(settings) -> AgentAdapter`.
- `run_task` returns `status`, `task_name`, `result`, `error_code`, `error`, `elapsed_ms`, and relative `log_file`.

- [ ] **Step 1: Write failing command-resolution and error tests**

```python
def test_windows_codex_rejects_wsl_prefix():
    assert resolve_windows_codex("wsl:/home/cincin/codex.sh") is None


def test_health_check_maps_permission_error(monkeypatch):
    monkeypatch.setattr(windows_codex_adapter, "resolve_command", lambda value: r"C:\\Codex\\codex.exe")
    monkeypatch.setattr(windows_codex_adapter.subprocess, "run", Mock(side_effect=PermissionError("denied")))
    result = WindowsCodexAdapter(AppConfig(codex_mode="cli")).health_check()
    assert result["status"] == "failed"
    assert result["error_code"] == "codex_access_denied"


def test_run_task_maps_login_failure(monkeypatch, tmp_path):
    completed = subprocess.CompletedProcess(["codex", "exec"], 1, "", "Not logged in. Run codex login.")
    monkeypatch.setattr(windows_codex_adapter, "resolve_command", lambda value: "codex.exe")
    monkeypatch.setattr(windows_codex_adapter.subprocess, "run", lambda *args, **kwargs: completed)
    result = WindowsCodexAdapter(AppConfig(codex_mode="cli")).run_task("role_planner", "prompt", tmp_path)
    assert result["status"] == "failed"
    assert result["error_code"] == "codex_login_required"


def test_run_task_parses_a_json_object_and_uses_shell_false(monkeypatch, tmp_path):
    captured = {}
    completed = subprocess.CompletedProcess(["codex", "exec"], 0, '{"schema_version":"role.plan.v1"}', "")
    monkeypatch.setattr(windows_codex_adapter, "resolve_command", lambda value: "codex.exe")
    monkeypatch.setattr(windows_codex_adapter.subprocess, "run", lambda command, **kwargs: captured.update(command=command, kwargs=kwargs) or completed)
    result = WindowsCodexAdapter(AppConfig(codex_mode="cli")).run_task("role_planner", "prompt", tmp_path)
    assert result["result"]["schema_version"] == "role.plan.v1"
    assert captured["kwargs"]["shell"] is False
    assert captured["kwargs"]["cwd"] == str(tmp_path)
```

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
python -m pytest backend/tests/test_windows_codex_adapter.py -q -p no:cacheprovider --basetemp=D:\codex-project\APP\tmp\pytest-windows-codex-red
```

Expected: collection fails because `windows_codex_adapter` does not exist.

- [ ] **Step 3: Add bounded configuration**

Add to `AppConfig`:

```python
codex_diagnostic_timeout_s: int = Field(
    default_factory=lambda: int(os.getenv("CODEX_DIAGNOSTIC_TIMEOUT_S", "300")),
    ge=30,
    le=900,
)
workflow_profile: Literal["legacy", "three_agent_v2"] = Field(
    default_factory=lambda: os.getenv("WORKFLOW_PROFILE", "three_agent_v2")
)
```

The profile is descriptive in this milestone; it does not silently replace the existing production `task_runner` flow.

- [ ] **Step 4: Implement the adapter**

Use `resolve_command` from `command_runner.py`, reject `wsl:` before resolution, and call subprocess with:

```python
completed = subprocess.run(
    [resolved, *shlex.split(self.settings.codex_exec_args)],
    input=prompt,
    cwd=str(workspace),
    capture_output=True,
    text=True,
    timeout=self.settings.codex_diagnostic_timeout_s,
    shell=False,
    encoding="utf-8",
    errors="replace",
)
```

Map `FileNotFoundError` to `codex_missing`, `PermissionError` to `codex_access_denied`, `TimeoutExpired` to `codex_timeout`, authentication text to `codex_login_required`, nonzero exits to `codex_failed`, and unparseable output to `codex_invalid_result`. Store a redacted log under `logs/codex_<task_name>.log`, but return only its workspace-relative path.

Parse JSON by first trying the entire stdout, then fenced JSON blocks, then balanced top-level objects. Do not parse stderr as a successful result.

- [ ] **Step 5: Verify GREEN and existing adapter compatibility**

```powershell
python -m pytest backend/tests/test_windows_codex_adapter.py -q -p no:cacheprovider --basetemp=D:\codex-project\APP\tmp\pytest-windows-codex-green
```

Expected: all Windows Codex adapter tests pass. Task 3 adds committed Hermes integration coverage.

- [ ] **Step 6: Commit Task 2**

```powershell
git add -- ai-report-ppt-controller/backend/config.py ai-report-ppt-controller/backend/services/windows_codex_adapter.py ai-report-ppt-controller/backend/tests/test_windows_codex_adapter.py
git commit -m "feat: add Windows Codex diagnostic adapter"
```

### Task 3: Normalize Real-Agent Readiness and Verify the Hermes Bridge

**Files:**
- Create: `ai-report-ppt-controller/backend/services/agent_readiness.py`
- Create: `ai-report-ppt-controller/backend/tests/test_agent_readiness.py`
- Create: `ai-report-ppt-controller/backend/tests/test_hermes_role_executor.py`
- Modify: `ai-report-ppt-controller/backend/services/agent_adapters.py`

**Interfaces:**
- Produces: `normalize_real_readiness(name, payload) -> dict`.
- Produces: stable Hermes errors `hermes_bridge_unavailable`, `hermes_auth_failed`, `hermes_timeout`, `hermes_invalid_result`, and `hermes_failed`.
- Consumed by: Task 4.

- [ ] **Step 1: Write failing readiness tests**

```python
@pytest.mark.parametrize("status", ["mock", "fallback", "missing", "failed"])
def test_non_real_status_never_passes(status):
    result = normalize_real_readiness("hermes", {"ok": True, "status": status})
    assert result["ok"] is False
    assert result["status"] == status


def test_success_requires_ok_true():
    result = normalize_real_readiness("chatgpt", {"ok": False, "status": "success"})
    assert result["ok"] is False
    assert result["error_code"] == "chatgpt_not_ready"


def test_real_success_is_preserved():
    result = normalize_real_readiness("hermes", {"ok": True, "status": "success", "version": "0.20.0"})
    assert result["ok"] is True
    assert result["status"] == "success"


@pytest.mark.parametrize(
    ("status", "error_code"),
    [
        ("cdp_unavailable", "chatgpt_cdp_unavailable"),
        ("login_required", "chatgpt_login_required"),
        ("page_changed", "chatgpt_page_changed"),
    ],
)
def test_chatgpt_readiness_preserves_actionable_page_failures(status, error_code):
    result = normalize_real_readiness("chatgpt", {"ok": False, "status": status})
    assert result["error_code"] == error_code
```

- [ ] **Step 2: Write a failing local HTTP bridge test**

Use `ThreadingHTTPServer` to expose `/health` and `/run`, record the request, and assert:

```python
assert received == {
    "task_name": "role_executor",
    "prompt": "execute task",
    "workspace": str(tmp_path),
    "extra_context": {"task_id": "task-001"},
}
assert result["status"] == "success"
assert result["result"]["schema_version"] == "role.execution.v1"
```

Add cases for HTTP 401, timeout, 502, and a non-object JSON response.

- [ ] **Step 3: Run focused tests and verify RED**

```powershell
python -m pytest backend/tests/test_agent_readiness.py backend/tests/test_hermes_role_executor.py -q -p no:cacheprovider --basetemp=D:\codex-project\APP\tmp\pytest-agent-readiness-red
```

Expected: readiness module collection fails and at least one Hermes stable-error assertion fails.

- [ ] **Step 4: Implement readiness normalization and Hermes error mapping**

Implement:

```python
REAL_SUCCESS = {"ok": True, "status": "success"}


def normalize_real_readiness(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    status = str(payload.get("status") or "failed")
    ok = bool(payload.get("ok")) and status == "success"
    result = {**payload, "name": name, "ok": ok, "status": status}
    if not ok and not result.get("error_code"):
        result["error_code"] = (
            f"{name}_{status}"
            if status not in {"success", "failed", "mock", "fallback", "missing"}
            else f"{name}_not_ready"
        )
    return result
```

In `HermesAPIAdapter`, catch `HTTPError` separately so 401/403 map to `hermes_auth_failed`, catch `TimeoutError`/`socket.timeout` as `hermes_timeout`, connection failures as `hermes_bridge_unavailable`, invalid JSON/object responses as `hermes_invalid_result`, and other non-2xx responses as `hermes_failed`. Preserve the existing request body and `shell=False` boundary.

- [ ] **Step 5: Verify GREEN**

```powershell
python -m pytest backend/tests/test_agent_readiness.py backend/tests/test_hermes_role_executor.py -q -p no:cacheprovider --basetemp=D:\codex-project\APP\tmp\pytest-agent-readiness-green
```

Expected: all readiness and Hermes integration tests pass, and the local server is closed by each test.

- [ ] **Step 6: Commit Task 3**

```powershell
git add -- ai-report-ppt-controller/backend/services/agent_readiness.py ai-report-ppt-controller/backend/services/agent_adapters.py ai-report-ppt-controller/backend/tests/test_agent_readiness.py ai-report-ppt-controller/backend/tests/test_hermes_role_executor.py
git commit -m "feat: verify real Hermes and ChatGPT readiness"
```

### Task 4: Build the Role Baseline Service

**Files:**
- Create: `ai-report-ppt-controller/backend/services/role_baseline_service.py`
- Create: `ai-report-ppt-controller/backend/tests/test_role_baseline_service.py`

**Interfaces:**
- Consumes: `WindowsCodexAdapter`, `HermesAPIAdapter`, `ChatGPTAdapter`, Task 1 validators, and Task 1 artifact guards.
- Produces: `run_role_baseline(settings, diagnostics_root, *, codex=None, hermes=None, chatgpt=None, run_id=None) -> dict`.
- Persists: `diagnostic_plan.json`, `hermes_execution.json`, `diagnostic_final.md`, and `role_baseline_trace.json` under `diagnostics/{run_id}/`.

- [ ] **Step 1: Write failing successful-flow test**

Create a `WritingAdapter` test double that writes only the file for its current task and returns a structured response. Assert exact call order and artifacts:

```python
result = run_role_baseline(
    settings,
    tmp_path / "diagnostics",
    codex=codex,
    hermes=hermes,
    chatgpt=chatgpt,
    run_id="run-001",
)

assert [call[0] for call in codex.calls] == ["role_planner", "role_finalizer"]
assert [call[0] for call in hermes.calls] == ["role_executor"]
assert chatgpt.health_calls == 1
assert chatgpt.run_calls == 0
assert result["status"] == "success"
assert result["artifacts"] == [
    "diagnostic_plan.json",
    "hermes_execution.json",
    "diagnostic_final.md",
    "role_baseline_trace.json",
]
```

- [ ] **Step 2: Write failing stop-and-audit tests**

Add parameterized cases asserting no downstream call after each failure:

```python
@pytest.mark.parametrize("failed_agent", ["chatgpt", "codex_planner", "hermes", "codex_finalizer"])
def test_baseline_stops_at_first_failure(failed_agent, tmp_path):
    result, adapters = run_failure_case(failed_agent, tmp_path)
    assert result["status"] == "failed"
    assert result["error_code"]
    assert (tmp_path / "diagnostics" / "run-001" / "role_baseline_trace.json").exists()
    assert adapters.calls_after_failure == []
```

Add explicit tests for mock readiness, unchanged files, invalid JSON, mismatched structured/file results, artifact escape attempts, and trace redaction.

- [ ] **Step 3: Run service tests and verify RED**

```powershell
python -m pytest backend/tests/test_role_baseline_service.py -q -p no:cacheprovider --basetemp=D:\codex-project\APP\tmp\pytest-role-service-red
```

Expected: collection fails because `role_baseline_service` does not exist.

- [ ] **Step 4: Implement the ordered service**

Use this public flow:

```python
def run_role_baseline(
    settings: AppConfig,
    diagnostics_root: Path,
    *,
    codex: AgentAdapter | None = None,
    hermes: AgentAdapter | None = None,
    chatgpt: AgentAdapter | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    run_id = run_id or uuid4().hex
    workspace = safe_artifact_path(diagnostics_root, run_id)
    workspace.mkdir(parents=True, exist_ok=False)
    adapters = {
        "codex": codex or make_windows_codex_adapter(settings),
        "hermes": hermes or make_hermes_adapter(settings),
        "chatgpt": chatgpt or make_chatgpt_adapter(settings),
    }
    # Readiness -> Codex plan -> Hermes execution -> Codex finalization -> trace.
```

Use fixed repository-owned diagnostic content and prompts:

```python
DIAGNOSTIC_SOURCE = "Silicon has atomic number 14. This sentence is repository-owned diagnostic text.\n"

CODEX_PLAN_PROMPT = """Create role.plan.v1 JSON for one Hermes task that summarizes input/diagnostic_source.md.
Write the same JSON to diagnostic_plan.json and return JSON only.
The task output must be hermes_execution.json and the final output must be diagnostic_final.md.
"""

HERMES_EXECUTION_PROMPT = """Execute task-001 from diagnostic_plan.json.
Read input/diagnostic_source.md, write role.execution.v1 JSON to hermes_execution.json, and return the same JSON.
Use no network access and report an empty sources array.
"""

CODEX_FINAL_PROMPT = """Read diagnostic_plan.json and hermes_execution.json.
Write a short Markdown summary to diagnostic_final.md.
Return role.finalization.v1 JSON whose artifact_paths contains diagnostic_final.md.
"""
```

For every agent call:

1. Fingerprint the expected artifact before the call.
2. Call the adapter.
3. Require `status=success` and the expected structured payload.
4. Require the expected file to be new or changed.
5. Load and validate the file through Task 1 guards.
6. Require the normalized structured response and normalized file payload to match for JSON artifacts.
7. Record a redacted attempt and artifact manifest entry.

Write the diagnostic source before any agent call. Write the trace in a `finally` block so every failure remains auditable. Return paths relative to `diagnostics_root.parent`; never return the absolute workspace.

- [ ] **Step 5: Verify service GREEN**

```powershell
python -m pytest backend/tests/test_role_baseline_service.py backend/tests/test_role_contracts.py backend/tests/test_role_artifacts.py -q -p no:cacheprovider --basetemp=D:\codex-project\APP\tmp\pytest-role-service-green
```

Expected: all service, contract, and artifact tests pass.

- [ ] **Step 6: Commit Task 4**

```powershell
git add -- ai-report-ppt-controller/backend/services/role_baseline_service.py ai-report-ppt-controller/backend/tests/test_role_baseline_service.py
git commit -m "feat: add three-agent baseline service"
```

### Task 5: Expose Matching Configuration and API Endpoints

**Files:**
- Create: `ai-report-ppt-controller/backend/routers/role_baseline.py`
- Create: `ai-report-ppt-controller/backend/tests/test_role_baseline_api.py`
- Modify: `ai-report-ppt-controller/backend/app.py`
- Modify: `ai-report-ppt-controller/backend/dev_server.py`
- Modify: `ai-report-ppt-controller/backend/config.py`

**Interfaces:**
- Produces: `POST /api/check/role-baseline` in both FastAPI and the static development server.
- Consumes: no user task content; the request body is empty or `{}`.
- Returns: service result with `run_id`, `status`, `error_code`, `agents`, `artifacts`, and relative `trace_file`.

- [ ] **Step 1: Write failing FastAPI and dev-server tests**

```python
def test_fastapi_role_baseline_endpoint_calls_service(monkeypatch):
    monkeypatch.setattr(role_baseline, "run_role_baseline", lambda *args, **kwargs: {
        "run_id": "run-001", "status": "success", "error_code": None,
        "agents": {}, "artifacts": [], "trace_file": "diagnostics/run-001/role_baseline_trace.json",
    })
    response = TestClient(create_app()).post("/api/check/role-baseline", json={})
    assert response.status_code == 200
    assert response.json()["run_id"] == "run-001"


def test_dev_server_config_accepts_three_agent_profile():
    assert dev_server.validate_config_patch({"workflow_profile": "three_agent_v2"}) == {
        "workflow_profile": "three_agent_v2"
    }


@pytest.mark.parametrize("value", ["", "agents", "v3"])
def test_dev_server_config_rejects_unknown_profile(value):
    with pytest.raises(ValueError):
        dev_server.validate_config_patch({"workflow_profile": value})
```

Also test `codex_diagnostic_timeout_s` boundaries 30, 300, and 900, and rejection at 29 and 901.

- [ ] **Step 2: Run API tests and verify RED**

```powershell
python -m pytest backend/tests/test_role_baseline_api.py -q -p no:cacheprovider --basetemp=D:\codex-project\APP\tmp\pytest-role-api-red
```

Expected: router import or route assertion fails.

- [ ] **Step 3: Implement FastAPI endpoint**

Create a router with prefix `/api/check` and token dependency:

```python
@router.post("/role-baseline", dependencies=[Depends(require_api_token)])
def role_baseline() -> dict:
    settings = get_settings()
    diagnostics_root = STORAGE_DIR / "workspace" / "diagnostics"
    return run_role_baseline(settings, diagnostics_root)
```

Register the router in `backend/app.py`.

- [ ] **Step 4: Mirror the endpoint and config in `dev_server.py`**

Add `workflow_profile="three_agent_v2"` and `codex_diagnostic_timeout_s=300` to `DEFAULT_CONFIG`, validate them in `validate_config_patch`, and add the endpoint before `/api/check/codex`:

```python
if path == "/api/check/role-baseline":
    settings = AppConfig(**load_config())
    return json_response(
        self,
        200,
        run_role_baseline(settings, STORAGE_ROOT / "workspace" / "diagnostics"),
    )
```

Do not run the diagnostic during ordinary `/api/check/codex`, `/api/check/hermes`, `/api/check/chatgpt`, page load, or `checkAll()`.

- [ ] **Step 5: Verify API GREEN**

```powershell
python -m pytest backend/tests/test_role_baseline_api.py backend/tests/test_chatgpt_config_and_health.py -q -p no:cacheprovider --basetemp=D:\codex-project\APP\tmp\pytest-role-api-green
```

Expected: both suites pass and configuration defaults match between Pydantic and the static server.

- [ ] **Step 6: Commit Task 5**

```powershell
git add -- ai-report-ppt-controller/backend/config.py ai-report-ppt-controller/backend/app.py ai-report-ppt-controller/backend/routers/role_baseline.py ai-report-ppt-controller/backend/dev_server.py ai-report-ppt-controller/backend/tests/test_role_baseline_api.py
git commit -m "feat: expose three-agent baseline diagnostics"
```

### Task 6: Add the Fixed-Role Baseline UI

**Files:**
- Modify: `ai-report-ppt-controller/frontend/static/index.html`
- Modify: `ai-report-ppt-controller/frontend/static/app.js`
- Modify: `ai-report-ppt-controller/frontend/static/styles.css`
- Modify: `ai-report-ppt-controller/frontend/static/app.restore.test.js`

**Interfaces:**
- Consumes: `GET /api/config`, existing individual health endpoints, and explicit `POST /api/check/role-baseline`.
- Produces DOM IDs: `#workflow-profile`, `#role-baseline-run`, `#role-baseline-status`, `#role-baseline-agents`, and `#role-baseline-artifacts`.

- [ ] **Step 1: Add failing browser-free UI tests**

Extend the fake DOM and add:

```javascript
test("three-agent profile renders fixed responsibilities", async () => {
  responses.config = { workflow_profile: "three_agent_v2" };
  await initialize();
  assert.equal(elements["workflow-profile"].textContent, "三代理 V2");
  assert.match(elements["role-baseline-agents"].textContent, /Codex.*规划.*最终生成/);
  assert.match(elements["role-baseline-agents"].textContent, /Hermes.*任务执行/);
  assert.match(elements["role-baseline-agents"].textContent, /ChatGPT.*审核.*终审/);
});


test("baseline runs only after an explicit click", async () => {
  await initialize();
  assert.equal(calls.filter(call => call.url === "/api/check/role-baseline").length, 0);
  elements["role-baseline-run"].click();
  await flushPromises();
  assert.equal(calls.filter(call => call.url === "/api/check/role-baseline").length, 1);
  assert.match(elements["role-baseline-status"].textContent, /success/);
});


test("mock agent status is not rendered as a passing baseline", async () => {
  responses.roleBaseline = { status: "failed", error_code: "codex_not_ready", agents: { codex: { status: "mock" } } };
  elements["role-baseline-run"].click();
  await flushPromises();
  assert.match(elements["role-baseline-status"].textContent, /失败/);
  assert.doesNotMatch(elements["role-baseline-status"].className, /success/);
});
```

- [ ] **Step 2: Run static tests and verify RED**

```powershell
& 'C:\Users\27235\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' --test ai-report-ppt-controller/frontend/static/app.restore.test.js
```

Expected: missing DOM IDs and baseline-call assertions fail.

- [ ] **Step 3: Implement the baseline card**

Add a system-tab card that always displays:

```text
Codex（Windows）：规划、最终生成、修订
Hermes（WSL）：任务执行
ChatGPT（网页）：审核、终审
```

Add the explicit button and results sections. In `app.js`, implement:

```javascript
async function runRoleBaseline() {
  setBusy("#role-baseline-run", true);
  try {
    const result = await api("/api/check/role-baseline", { method: "POST", body: "{}" });
    state.roleBaseline = result;
    renderRoleBaseline(result);
    logSystem("三代理连接基线", result);
  } catch (error) {
    renderRoleBaseline({ status: "failed", error_code: "request_failed", detail: String(error) });
  } finally {
    setBusy("#role-baseline-run", false);
  }
}
```

Render status, per-agent status/elapsed time/error code, artifact links, and remediation text. Never render raw stdout, stderr, prompts, tokens, cookies, or absolute paths.

When `workflow_profile=three_agent_v2`, label the existing `main_agent` and `review_agent` controls as legacy compatibility settings and disable them for the baseline. Do not remove them until the production three-agent workflow replaces the legacy task flow.

- [ ] **Step 4: Add restrained styles and cache version**

Reuse existing cards, badges, grids, and buttons. Add only `.role-baseline-card`, `.role-grid`, `.role-result`, `.role-result.failed`, and `.legacy-controls[disabled]`. Update the static cache query in both HTML and its test from `phase16-chatgpt-planner` to `phase17-role-baseline`.

- [ ] **Step 5: Verify UI GREEN**

```powershell
& 'C:\Users\27235\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' --test ai-report-ppt-controller/frontend/static/app.restore.test.js
& 'C:\Users\27235\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' --check ai-report-ppt-controller/frontend/static/app.js
```

Expected: all Node tests pass and syntax check exits 0.

- [ ] **Step 6: Commit Task 6**

```powershell
git add -- ai-report-ppt-controller/frontend/static/index.html ai-report-ppt-controller/frontend/static/app.js ai-report-ppt-controller/frontend/static/styles.css ai-report-ppt-controller/frontend/static/app.restore.test.js
git commit -m "feat: add three-agent baseline UI"
```

### Task 7: Document Operation, Add Opt-In Live Smoke, and Verify the Milestone

**Files:**
- Create: `ai-report-ppt-controller/backend/tests/test_role_baseline_live.py`
- Modify: `ai-report-ppt-controller/.env.example`
- Modify: `ai-report-ppt-controller/docs/usage.md`

**Interfaces:**
- Documents exact Windows Codex, WSL Hermes, ChatGPT CDP, endpoint, diagnostic workspace, privacy, and troubleshooting behavior.
- Produces an opt-in test enabled only by `ROLE_BASELINE_LIVE=1`.

- [ ] **Step 1: Write the skipped-by-default live test**

```python
pytestmark = pytest.mark.skipif(
    os.getenv("ROLE_BASELINE_LIVE") != "1",
    reason="Set ROLE_BASELINE_LIVE=1 to run the real three-agent diagnostic.",
)


def test_real_three_agent_role_baseline(tmp_path):
    settings = get_settings()
    assert settings.codex_mode == "cli"
    assert not settings.codex_command.startswith("wsl:")
    assert settings.hermes_mode == "api"
    assert settings.chatgpt_mode == "cdp"
    result = run_role_baseline(settings, tmp_path / "diagnostics", run_id="live-smoke")
    assert result["status"] == "success", result
    assert all(result["agents"][name]["status"] == "success" for name in ("codex", "hermes", "chatgpt"))
    assert set(result["artifacts"]) == {
        "diagnostic_plan.json",
        "hermes_execution.json",
        "diagnostic_final.md",
        "role_baseline_trace.json",
    }
```

- [ ] **Step 2: Verify the live test skips safely**

```powershell
python -m pytest backend/tests/test_role_baseline_live.py -q -p no:cacheprovider --basetemp=D:\codex-project\APP\tmp\pytest-role-live-skipped
```

Expected: one skipped test and no external request.

- [ ] **Step 3: Update configuration and usage docs**

Add exact examples:

```env
WORKFLOW_PROFILE=three_agent_v2
CODEX_MODE=cli
CODEX_COMMAND=codex
CODEX_EXEC_ARGS=exec
CODEX_DIAGNOSTIC_TIMEOUT_S=300
HERMES_MODE=api
HERMES_ENDPOINT=http://127.0.0.1:7788
CHATGPT_MODE=cdp
CHROME_CDP_HOST=127.0.0.1
CHROME_CDP_PORT=9222
```

Document that `CODEX_COMMAND` must identify Windows Codex and must not use `wsl:` for this profile; Hermes remains in WSL behind the bridge; `/api/check/chatgpt` and baseline readiness do not send ChatGPT a message; `/api/check/role-baseline` sends only repository-owned diagnostic text to Codex and Hermes; and real user content is not used in this milestone.

- [ ] **Step 4: Run complete automated verification**

```powershell
python -m pytest backend/tests -q -p no:cacheprovider --basetemp=D:\codex-project\APP\tmp\pytest-role-baseline-full
& 'C:\Users\27235\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' --test ai-report-ppt-controller/frontend/static/app.restore.test.js
& 'C:\Users\27235\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' --check ai-report-ppt-controller/frontend/static/app.js
python -c "import ast, pathlib; files=['backend/config.py','backend/app.py','backend/dev_server.py','backend/routers/role_baseline.py','backend/services/role_contracts.py','backend/services/role_artifacts.py','backend/services/windows_codex_adapter.py','backend/services/agent_readiness.py','backend/services/role_baseline_service.py']; [ast.parse(pathlib.Path(f).read_text(encoding='utf-8')) for f in files]"
git diff --check
git diff --name-only -- server.js
```

Expected: all backend and Node tests pass; JavaScript and Python syntax checks succeed; `git diff --check` is clean; and the final command prints nothing.

- [ ] **Step 5: Run the real smoke test only after configuration is ready**

From `ai-report-ppt-controller`:

```powershell
$env:ROLE_BASELINE_LIVE='1'
python -m pytest backend/tests/test_role_baseline_live.py -v -p no:cacheprovider --basetemp=D:\codex-project\APP\tmp\pytest-role-live-real
Remove-Item Env:ROLE_BASELINE_LIVE
```

Expected: one passed test. If Windows blocks the packaged `codex.exe`, the result must fail with `codex_access_denied` and a remediation path; do not report the baseline as complete until a Windows Codex executable runs successfully.

- [ ] **Step 6: Verify scope and commit Task 7**

```powershell
git status --short
git add -- ai-report-ppt-controller/.env.example ai-report-ppt-controller/docs/usage.md ai-report-ppt-controller/backend/tests/test_role_baseline_live.py
git commit -m "docs: explain three-agent baseline operation"
```

Do not stage pytest temp directories, the dirty source worktree, runtime diagnostic outputs, or any credentials.

## Final Verification Checklist

- [ ] Work was performed in a new clean worktree created from the commit containing this plan, descended from `b4a1257`.
- [ ] The old dirty worktree and its experimental Hermes changes remain untouched.
- [ ] Windows Codex rejects `wsl:` and performs version plus real inference/file-write validation.
- [ ] WSL Hermes is reached through the HTTP bridge and returns a valid execution artifact.
- [ ] ChatGPT readiness sends no message and real review remains outside this milestone.
- [ ] Codex plan, Hermes execution, Codex finalization, ChatGPT review, attempt, trace, and artifact contracts are tested.
- [ ] Mock, fallback, missing, and failed states cannot pass the real baseline.
- [ ] The diagnostic stops after the first failure and still writes a redacted trace.
- [ ] All paths are relative and bounded to the diagnostic workspace; SHA-256 is recorded.
- [ ] FastAPI and static development server expose matching baseline and configuration behavior.
- [ ] The UI shows fixed roles and runs the diagnostic only after an explicit click.
- [ ] The live smoke test skips by default and passes only with real Windows Codex, WSL Hermes, and browser ChatGPT readiness.
- [ ] Full backend tests, Node tests, JavaScript syntax, Python AST parsing, and `git diff --check` pass.
- [ ] The repository-root `server.js` remains unchanged.
