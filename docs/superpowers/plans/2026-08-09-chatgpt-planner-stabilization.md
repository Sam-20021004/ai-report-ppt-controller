# ChatGPT Planner Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize the August 9 ChatGPT planner so it produces a validated plan, falls back transparently to Hermes, exposes safe configuration and health checks, and remains fully testable without a live ChatGPT session.

**Architecture:** Add strict planner contracts and a single planner service between the adapters and `task_runner.py`. Keep browser interaction inside `ChatGPTAdapter`, make Hermes the bounded fallback, persist a redacted planner trace, and expose the same settings through FastAPI and the static development server.

**Tech Stack:** Python 3.11+, Pydantic 2, pytest, Playwright sync API, FastAPI, browser-free Node test runner, HTML/CSS/vanilla JavaScript.

## Global Constraints

- Preserve all existing uncommitted changes as the implementation baseline.
- Do not modify the root `server.js` file.
- Do not introduce LangGraph in this implementation.
- ChatGPT only plans; Hermes and Codex retain their existing downstream responsibilities.
- `planner_mode=chatgpt` means ChatGPT first with one Hermes fallback; `planner_mode=hermes` means Hermes only.
- Never persist cookies, tokens, authorization headers, browser profile data, full page HTML, or absolute task-workspace paths.
- Use test-first red-green-refactor for every behavior change.
- Run pytest with a new repository-local `--basetemp` and `-p no:cacheprovider` because the host user temp directory is not accessible in this environment.
- Use `C:\Users\27235\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe` for JavaScript checks because `node` is not on `PATH`.

---

## File Structure

- Create `ai-report-ppt-controller/backend/services/planner_contracts.py`: strict plan, attempt, trace, and outcome contracts.
- Create `ai-report-ppt-controller/backend/services/planner_service.py`: planner selection, validation, fallback, audit hashing, and trace writing.
- Modify `ai-report-ppt-controller/backend/services/chatgpt_adapter.py`: deterministic new-message detection, configured timeout/new-chat behavior, and stable errors.
- Modify `ai-report-ppt-controller/backend/services/task_runner.py`: call the planner service and consume one normalized outcome.
- Modify `ai-report-ppt-controller/backend/config.py`: bounded ChatGPT settings.
- Modify `ai-report-ppt-controller/backend/routers/check.py`: ChatGPT health route.
- Modify `ai-report-ppt-controller/backend/dev_server.py`: matching config defaults, validation, and health route.
- Modify `ai-report-ppt-controller/frontend/static/index.html`: planner settings panel.
- Modify `ai-report-ppt-controller/frontend/static/app.js`: load/save/check planner settings.
- Modify `ai-report-ppt-controller/frontend/static/styles.css`: restrained settings styles.
- Modify `ai-report-ppt-controller/.env.example`: document environment defaults.
- Modify `ai-report-ppt-controller/docs/usage.md`: operator setup, fallback, and privacy notice.
- Create focused tests under `ai-report-ppt-controller/backend/tests/` and extend `frontend/static/app.restore.test.js`.

### Task 1: Add Strict Planner Contracts

**Files:**
- Create: `ai-report-ppt-controller/backend/services/planner_contracts.py`
- Create: `ai-report-ppt-controller/backend/tests/test_planner_contracts.py`

**Interfaces:**
- Produces: `validate_plan(payload: Any) -> dict[str, Any]`
- Produces: `PlannerContractError.issues: list[dict[str, str]]`
- Produces: `PlannerAttempt`, `PlannerTrace`, and `PlannerOutcome` Pydantic models.
- Consumes: Pydantic 2 already declared by the project.

- [ ] **Step 1: Write failing contract tests**

```python
from pathlib import Path

import pytest

from backend.services.planner_contracts import PlannerContractError, PlannerTrace, validate_plan


def valid_plan() -> dict:
    return {
        "task_understanding": "Assess the technology and evidence.",
        "outline": [
            {"section": "Context", "goal": "Define scope"},
            {"section": "Evidence", "goal": "Assess sources"},
            {"section": "Risk", "goal": "Identify uncertainty"},
        ],
        "search_questions": ["current technology", "competitive landscape", "technical risk"],
        "figures_needed": [],
        "risks": ["source lag"],
        "success_criteria": ["traceable evidence"],
        "language": "English",
        "ignored": "drop me",
    }


def test_validate_plan_normalizes_and_drops_unknown_fields():
    result = validate_plan(valid_plan())
    assert result["outline"][0] == {"section": "Context", "goal": "Define scope"}
    assert "ignored" not in result


def test_validate_plan_reports_stable_issue_codes():
    payload = valid_plan()
    payload["outline"] = payload["outline"][:2]
    with pytest.raises(PlannerContractError) as exc_info:
        validate_plan(payload)
    assert {issue["code"] for issue in exc_info.value.issues} == {"outline.too_short"}


def test_planner_trace_rejects_absolute_log_paths():
    with pytest.raises(ValueError):
        PlannerTrace(
            requested_mode="chatgpt",
            primary_planner="chatgpt",
            selected_planner="chatgpt",
            fallback_used=False,
            attempts=[{"planner": "chatgpt", "status": "success", "elapsed_ms": 1, "log_file": str(Path.cwd())}],
            plan_sha256="0" * 64,
        )
```

- [ ] **Step 2: Run tests and verify RED**

Run from `ai-report-ppt-controller`:

```powershell
python -m pytest backend/tests/test_planner_contracts.py -q -p no:cacheprovider --basetemp=D:\codex-project\APP\tmp\pytest-planner-contracts-red
```

Expected: collection fails because `backend.services.planner_contracts` does not exist.

- [ ] **Step 3: Implement strict models and stable validation mapping**

Implement Pydantic models with `extra="ignore"`, stripped non-empty strings, outline length 3–6, search question minimum 3, and success criteria minimum 1. Convert `ValidationError.errors()` into sorted dictionaries containing `path`, `code`, and `message`; map list-length errors to `outline.too_short`, `outline.too_long`, `search_questions.too_short`, or `success_criteria.too_short`. Reject absolute or parent-traversing attempt log paths.

- [ ] **Step 4: Run tests and verify GREEN**

Run the same command with `--basetemp=D:\codex-project\APP\tmp\pytest-planner-contracts-green`.

Expected: all contract tests pass.

- [ ] **Step 5: Commit**

```powershell
git add -- ai-report-ppt-controller/backend/services/planner_contracts.py ai-report-ppt-controller/backend/tests/test_planner_contracts.py
git commit -m "feat: add planner contracts"
```

### Task 2: Add the Planner Service and Bounded Hermes Fallback

**Files:**
- Create: `ai-report-ppt-controller/backend/services/planner_service.py`
- Create: `ai-report-ppt-controller/backend/tests/test_planner_service.py`

**Interfaces:**
- Consumes: `AgentAdapter.run_task(task_name, prompt, workspace, extra_context)`.
- Consumes: `validate_plan`, `PlannerAttempt`, `PlannerTrace`, and `PlannerOutcome`.
- Produces: `run_planner(*, requested_mode, chatgpt, hermes, chatgpt_prompt, hermes_prompt, workspace, context) -> PlannerOutcome`.
- Produces: `PlannerExecutionError.trace` when no planner returns a valid plan.

- [ ] **Step 1: Write failing selection and fallback tests**

Create a small recording adapter returning configured dictionaries. Test these exact paths:

```python
def test_hermes_mode_never_calls_chatgpt(tmp_path):
    chatgpt = RecordingAdapter(success_result(valid_plan()))
    hermes = RecordingAdapter(success_result(valid_plan()))
    outcome = run_planner(
        requested_mode="hermes",
        chatgpt=chatgpt,
        hermes=hermes,
        chatgpt_prompt="chatgpt prompt",
        hermes_prompt="hermes prompt",
        workspace=tmp_path,
        context={},
    )
    assert chatgpt.calls == []
    assert outcome.trace.selected_planner == "hermes"


def test_invalid_chatgpt_plan_falls_back_and_records_reason(tmp_path):
    chatgpt = RecordingAdapter(success_result({"outline": []}, parsed=True))
    hermes = RecordingAdapter(success_result(valid_plan()))
    outcome = run_planner(
        requested_mode="chatgpt",
        chatgpt=chatgpt,
        hermes=hermes,
        chatgpt_prompt="chatgpt prompt",
        hermes_prompt="hermes prompt",
        workspace=tmp_path,
        context={},
    )
    assert outcome.trace.fallback_used is True
    assert outcome.trace.selected_planner == "hermes"
    assert outcome.trace.fallback_reason_code == "invalid_plan"
    assert (tmp_path / "review" / "planner_trace.json").exists()


def test_both_planners_failing_raises_with_two_attempts(tmp_path):
    with pytest.raises(PlannerExecutionError) as exc_info:
        run_planner(
            requested_mode="chatgpt",
            chatgpt=RecordingAdapter(failed_result("reply_timeout")),
            hermes=RecordingAdapter(failed_result("hermes_unavailable")),
            chatgpt_prompt="chatgpt prompt",
            hermes_prompt="hermes prompt",
            workspace=tmp_path,
            context={},
        )
    assert [item.planner for item in exc_info.value.trace.attempts] == ["chatgpt", "hermes"]
```

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
python -m pytest backend/tests/test_planner_service.py -q -p no:cacheprovider --basetemp=D:\codex-project\APP\tmp\pytest-planner-service-red
```

Expected: collection fails because `planner_service` does not exist.

- [ ] **Step 3: Implement planner extraction, validation, hashing, and trace persistence**

Normalize both existing adapter shapes:

```python
def _adapter_payload(response: dict[str, Any]) -> Any:
    value = response.get("result")
    if isinstance(value, dict) and "parsed" in value and "result" in value:
        return value["result"]
    return value
```

Write `review/planner_trace.json` atomically through a temporary sibling file and `Path.replace()`. Store adapter-provided log files only after resolving them inside the workspace and converting them to POSIX-style relative paths. Hash canonical UTF-8 JSON with sorted keys.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Task 2 command with `--basetemp=D:\codex-project\APP\tmp\pytest-planner-service-green`.

Expected: all planner service tests pass.

- [ ] **Step 5: Commit**

```powershell
git add -- ai-report-ppt-controller/backend/services/planner_service.py ai-report-ppt-controller/backend/tests/test_planner_service.py
git commit -m "feat: add planner fallback service"
```

### Task 3: Harden the ChatGPT Browser Adapter

**Files:**
- Modify: `ai-report-ppt-controller/backend/services/chatgpt_adapter.py`
- Create: `ai-report-ppt-controller/backend/tests/test_chatgpt_adapter.py`

**Interfaces:**
- Produces: `ask_chatgpt(prompt, settings, use_new_chat, timeout_s) -> dict[str, Any]` with stable `error_code` on failure.
- Produces: adapter failure dictionaries with `error_code`, redacted `error`, elapsed time, and relative-capable `log_file`.
- Consumes: `AppConfig.chatgpt_use_new_chat` and `AppConfig.chatgpt_reply_timeout_s`.

- [ ] **Step 1: Write failing parser, configuration, and reply identity tests**

Test `_extract_json_blocks` with pure JSON, fenced JSON, balanced JSON, and invalid JSON. Monkeypatch `ask_chatgpt` in `ChatGPTAdapter.run_task` to capture `use_new_chat` and `timeout_s` and assert they equal the settings. Use a fake assistant locator to verify the reply helper requires a message count greater than the pre-send count and returns `reply_not_started` when no new message appears.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
python -m pytest backend/tests/test_chatgpt_adapter.py -q -p no:cacheprovider --basetemp=D:\codex-project\APP\tmp\pytest-chatgpt-adapter-red
```

Expected: configured timeout/new-chat assertions and new-message assertions fail against the current adapter.

- [ ] **Step 3: Implement condition-based reply tracking and structured failures**

Before sending, capture the assistant message count. After sending, poll until the count increases, then poll the new message text until it is non-empty, generation controls are absent, and the text is stable across two polls. Support both Chinese and English stop-button labels and the stable `data-testid` where available. Return an error dictionary instead of swallowing page-navigation errors.

Pass settings explicitly:

```python
result = ask_chatgpt(
    prompt,
    self.settings,
    use_new_chat=self.settings.chatgpt_use_new_chat,
    timeout_s=self.settings.chatgpt_reply_timeout_s,
)
```

When parsed JSON is absent, return adapter status `failed` with `error_code="invalid_json"`; do not fabricate an empty successful plan.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Task 3 command with `--basetemp=D:\codex-project\APP\tmp\pytest-chatgpt-adapter-green`.

Expected: all ChatGPT adapter tests pass.

- [ ] **Step 5: Commit**

```powershell
git add -- ai-report-ppt-controller/backend/services/chatgpt_adapter.py ai-report-ppt-controller/backend/tests/test_chatgpt_adapter.py
git commit -m "fix: harden ChatGPT planner adapter"
```

### Task 4: Integrate the Planner Service into the Existing Workflow

**Files:**
- Modify: `ai-report-ppt-controller/backend/services/task_runner.py`
- Create: `ai-report-ppt-controller/backend/tests/test_chatgpt_planner_workflow.py`

**Interfaces:**
- Consumes: `run_planner(...) -> PlannerOutcome`.
- Produces: existing `draft/outline.json`, `research/search_queries.json`, and new `review/planner_trace.json`.
- Preserves: existing Phase 2 contract generation and task step numbering.

- [ ] **Step 1: Write failing mock workflow tests**

Patch adapter factories in `task_runner` and assert:

```python
def test_chatgpt_failure_falls_back_and_workflow_writes_trace(configured_task, monkeypatch):
    monkeypatch.setattr(task_runner, "make_chatgpt_adapter", lambda settings: FailedChatGPT("invalid_json"))
    monkeypatch.setattr(task_runner, "make_hermes_adapter", lambda settings: ValidHermes(valid_plan()))
    record = task_runner.run_workflow(configured_task.task_id)
    trace = json.loads((task_runner.task_dir(record.task_id) / "review" / "planner_trace.json").read_text("utf-8"))
    assert trace["fallback_used"] is True
    assert trace["selected_planner"] == "hermes"
    assert record.steps[1].output["planner_trace"]["fallback_reason_code"] == "invalid_json"
```

Also assert Hermes mode never instantiates ChatGPT and both-planner failure marks the planning step and task failed.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
python -m pytest backend/tests/test_chatgpt_planner_workflow.py -q -p no:cacheprovider --basetemp=D:\codex-project\APP\tmp\pytest-planner-workflow-red
```

Expected: the current `task_runner` does not write a validated planner trace or fallback.

- [ ] **Step 3: Replace planner branching with one service call**

Remove `_resolve_planner_result`. Build both prompts, instantiate ChatGPT only when requested, call `run_planner`, write the normalized plan through the existing artifact helper, and store `outcome.trace.model_dump()` under `record.steps[1].output["planner_trace"]`.

- [ ] **Step 4: Run focused and existing workflow tests**

```powershell
python -m pytest backend/tests/test_chatgpt_planner_workflow.py backend/tests/test_phase3_report_outline.py backend/tests/test_phase3_report_draft.py -q -p no:cacheprovider --basetemp=D:\codex-project\APP\tmp\pytest-planner-workflow-green
```

Expected: focused workflow tests and existing Phase 3 tests pass.

- [ ] **Step 5: Commit**

```powershell
git add -- ai-report-ppt-controller/backend/services/task_runner.py ai-report-ppt-controller/backend/tests/test_chatgpt_planner_workflow.py
git commit -m "feat: integrate resilient planner workflow"
```

### Task 5: Validate Configuration and Add ChatGPT Health Checks

**Files:**
- Modify: `ai-report-ppt-controller/backend/config.py`
- Modify: `ai-report-ppt-controller/backend/routers/check.py`
- Modify: `ai-report-ppt-controller/backend/dev_server.py`
- Create: `ai-report-ppt-controller/backend/tests/test_chatgpt_config_and_health.py`

**Interfaces:**
- Produces: bounded `chatgpt_reply_timeout_s` from 30 through 1800.
- Produces: `POST /api/check/chatgpt` from both service entry points.
- Consumes: `make_chatgpt_adapter(settings).health_check()`.

- [ ] **Step 1: Write failing config and FastAPI route tests**

Use Pydantic assertions for accepted boundaries and rejected values. Use FastAPI `TestClient` with the ChatGPT adapter factory patched to return a deterministic health dictionary. For the static server, call a new pure `validate_config_patch` helper and verify it rejects invalid enum and timeout values.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
python -m pytest backend/tests/test_chatgpt_config_and_health.py -q -p no:cacheprovider --basetemp=D:\codex-project\APP\tmp\pytest-chatgpt-config-red
```

Expected: timeout bounds and the ChatGPT check route are missing.

- [ ] **Step 3: Implement matching config semantics and health route**

Use `Field(default=..., ge=30, le=1800)` for timeout. Add the four ChatGPT settings to the development server `DEFAULT_CONFIG`. Validate enum, boolean, and integer fields before writing `config.json`; return HTTP 422 for invalid updates. Add `/api/check/chatgpt` to both routers without sending a prompt.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Task 5 command with `--basetemp=D:\codex-project\APP\tmp\pytest-chatgpt-config-green`.

Expected: all config and health tests pass.

- [ ] **Step 5: Commit**

```powershell
git add -- ai-report-ppt-controller/backend/config.py ai-report-ppt-controller/backend/routers/check.py ai-report-ppt-controller/backend/dev_server.py ai-report-ppt-controller/backend/tests/test_chatgpt_config_and_health.py
git commit -m "feat: configure and check ChatGPT planner"
```

### Task 6: Add Static Planner Settings UI

**Files:**
- Modify: `ai-report-ppt-controller/frontend/static/index.html`
- Modify: `ai-report-ppt-controller/frontend/static/app.js`
- Modify: `ai-report-ppt-controller/frontend/static/styles.css`
- Modify: `ai-report-ppt-controller/frontend/static/app.restore.test.js`

**Interfaces:**
- Consumes: `GET /api/config`, `POST /api/config/update`, and `POST /api/check/chatgpt`.
- Produces: DOM controls `#planner-mode`, `#chatgpt-mode`, `#chatgpt-use-new-chat`, `#chatgpt-reply-timeout`, `#save-planner-config`, and `#check-chatgpt`.

- [ ] **Step 1: Add failing browser-free settings tests**

Extend the fake DOM with the six controls. Add a test where `GET /api/config` returns ChatGPT settings, click the settings button, assert the controls are populated, change them, click save, and assert the exact update body:

```javascript
assert.deepEqual(JSON.parse(updateCall.options.body), {
  planner_mode: "chatgpt",
  chatgpt_mode: "cdp",
  chatgpt_use_new_chat: true,
  chatgpt_reply_timeout_s: 600,
});
```

Add a second test asserting the ChatGPT health response is rendered and stored under `state.checks.chatgpt`.

- [ ] **Step 2: Run the static test and verify RED**

```powershell
& 'C:\Users\27235\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' --test ai-report-ppt-controller/frontend/static/app.restore.test.js
```

Run from the repository root. Expected: settings-control and ChatGPT-check assertions fail.

- [ ] **Step 3: Implement the static settings panel**

Add a compact settings card in the system tab. Change `loadConfig()` to populate controls instead of only logging. Add `savePlannerConfig()` and `checkChatGPT()`. Include ChatGPT in `checkAll()`, connection status, and the tool registry. Disable the ChatGPT-specific controls visually when planner mode is Hermes while preserving their values.

- [ ] **Step 4: Add restrained styles**

Reuse existing `.field`, `.grid-2`, `.button-row`, `.badge`, and panel styles. Add only selectors needed for disabled planner controls and the health summary; keep the existing visual language and responsive behavior.

- [ ] **Step 5: Run static tests and syntax check**

```powershell
& 'C:\Users\27235\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' --test ai-report-ppt-controller/frontend/static/app.restore.test.js
& 'C:\Users\27235\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' --check ai-report-ppt-controller/frontend/static/app.js
```

Expected: all Node tests pass and syntax check exits 0.

- [ ] **Step 6: Commit**

```powershell
git add -- ai-report-ppt-controller/frontend/static/index.html ai-report-ppt-controller/frontend/static/app.js ai-report-ppt-controller/frontend/static/styles.css ai-report-ppt-controller/frontend/static/app.restore.test.js
git commit -m "feat: add planner settings UI"
```

### Task 7: Document Operation and Run Complete Verification

**Files:**
- Modify: `ai-report-ppt-controller/.env.example`
- Modify: `ai-report-ppt-controller/docs/usage.md`

**Interfaces:**
- Documents: mock and CDP configuration, Chrome launch requirements, fallback semantics, health checks, test command, and privacy boundary.

- [ ] **Step 1: Write documentation assertions before editing docs**

Run a PowerShell check that fails until both files contain `PLANNER_MODE`, `CHATGPT_MODE`, `CHATGPT_USE_NEW_CHAT`, `CHATGPT_REPLY_TIMEOUT_S`, `/api/check/chatgpt`, and a warning that task content is sent to ChatGPT when enabled.

- [ ] **Step 2: Verify the documentation check fails**

Expected: at least one required term is absent from `.env.example` or `docs/usage.md`.

- [ ] **Step 3: Update environment example and operator documentation**

Add exact defaults and explain that `PLANNER_MODE=chatgpt` enables Hermes fallback, `CHATGPT_MODE=cdp` requires an already logged-in debugging Chrome, health check does not send a message, and sensitive task content must not be submitted to external services without authorization.

- [ ] **Step 4: Re-run the documentation assertions**

Expected: every required term is present and the script exits 0.

- [ ] **Step 5: Run the complete backend suite**

```powershell
python -m pytest backend/tests -q -p no:cacheprovider --basetemp=D:\codex-project\APP\tmp\pytest-chatgpt-planner-full
```

Run from `ai-report-ppt-controller`. Expected: zero failures and zero errors.

- [ ] **Step 6: Run static UI tests and syntax checks**

```powershell
& 'C:\Users\27235\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' --test ai-report-ppt-controller/frontend/static/app.restore.test.js
& 'C:\Users\27235\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' --check ai-report-ppt-controller/frontend/static/app.js
```

Expected: Node tests pass and syntax check exits 0.

- [ ] **Step 7: Run Python syntax checks without writing bytecode**

```powershell
python -c "import ast, pathlib; files=['backend/config.py','backend/routers/check.py','backend/services/chatgpt_adapter.py','backend/services/planner_contracts.py','backend/services/planner_service.py','backend/services/task_runner.py']; [ast.parse(pathlib.Path(f).read_text(encoding='utf-8')) for f in files]"
```

Expected: exit 0 with no output.

- [ ] **Step 8: Verify scope and diff hygiene**

```powershell
git diff --check
git diff --name-only -- server.js
git status --short
```

Expected: diff check is clean; `server.js` still shows only the pre-existing user changes and is absent from every feature commit.

- [ ] **Step 9: Commit documentation**

```powershell
git add -- ai-report-ppt-controller/.env.example ai-report-ppt-controller/docs/usage.md
git commit -m "docs: explain ChatGPT planner operation"
```

## Final Verification Checklist

- [ ] Existing uncommitted August 9 work was preserved and incorporated deliberately.
- [ ] The root `server.js` was not edited or staged.
- [ ] A valid ChatGPT plan reaches the existing Phase 2 pipeline without Hermes execution.
- [ ] CDP, login, composer, send, reply-start, timeout, empty reply, JSON, and contract failures cause one Hermes fallback.
- [ ] A failed Hermes fallback marks the planning step and task failed.
- [ ] New-chat and timeout settings are honored by the real adapter call.
- [ ] FastAPI and the static development server expose matching config and health semantics.
- [ ] Planner trace paths are relative, plan hashes are recorded, and sensitive browser material is absent.
- [ ] Static settings load, save, disable, and health-check behaviors are covered by Node tests.
- [ ] Real browser smoke testing remains opt-in.
- [ ] Full pytest suite reports zero failures and zero errors.
- [ ] Static Node tests and JavaScript syntax checks pass.
- [ ] Python AST parsing succeeds for every changed backend module.
- [ ] `git diff --check` is clean.
