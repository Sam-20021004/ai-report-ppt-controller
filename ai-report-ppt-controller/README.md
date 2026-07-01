# ReportAgent Studio

Windows/local controller for a Hermes + Codex + browser workflow that generates PPT/Word report artifacts inside isolated job workspaces.

## Implemented MVP

- Per-task workspace at `workspace/jobs/{task_id}/` with `input`, `state`, `prompts`, `research`, `draft`, `build`, `review`, `output`, and `logs`.
- Finite workflow states: `CREATED -> PLANNING -> RESEARCHING -> DRAFTING -> BUILDING -> REVIEWING -> REVISING -> FINALIZING -> DONE`.
- Adapter layer:
  - `HermesAPIAdapter` for HTTP/API Hermes calls.
  - `CodexCLIAdapter` for local GPT-login Codex CLI calls.
  - Mock Hermes/Codex/Chrome adapters so the full workflow can run before external tools are configured.
- Structured artifacts: `task.yaml`, `outline.json`, `search_queries.json`, `sources.json`, `content.md`, `slides_storyboard.json`, `review_round_*.json`, `final_manifest.json`.
- Mock builder creates downloadable `final_presentation.pptx` and `final_report.docx`.
- FastAPI routes and zero-dependency dev server both expose task create/run/status/files endpoints.

## Run

If dependencies are installed:

```powershell
cd D:\codex-project\APP\ai-report-ppt-controller
python -m backend.main
```

Open:

```text
http://127.0.0.1:7860
```

Zero-dependency development server:

```powershell
cd D:\codex-project\APP\ai-report-ppt-controller
python backend\dev_server.py
```

If the default runtime folder is not writable in your environment, set:

```powershell
$env:APP_STORAGE_DIR="D:\codex-project\APP\tmp-workflow-check"
```

## Adapter Configuration

Default mode is mock, which runs the full workflow without calling external agents.

```env
CODEX_MODE=mock
HERMES_MODE=mock
```

To call local Codex CLI:

```env
CODEX_MODE=cli
CODEX_COMMAND=codex
CODEX_EXEC_ARGS=exec
```

To call Hermes API:

```env
HERMES_MODE=api
HERMES_ENDPOINT=http://localhost:7788
HERMES_HEALTH_PATH=/health
HERMES_RUN_PATH=/run
HERMES_API_KEY_ENV=HERMES_API_KEY
```

Review loop:

```env
PASS_SCORE=85
MAX_REVIEW_ROUNDS=3
```

## Chrome CDP

```powershell
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir="D:\chrome-debug-profile"
```

The current workflow uses a mock browser adapter for `sources.json`; CDP health checks remain available at `/api/check/chrome`.
