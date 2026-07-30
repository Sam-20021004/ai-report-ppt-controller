# Hermes Codex LangGraph MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hand-written Hermes/Codex sequence with a durable fixed LangGraph workflow in which Codex performs analysis and report production, Hermes performs public-source research and parsing, and users approve the search plan and final export.

**Architecture:** Add a small `backend/workflows` package containing strict Pydantic boundary contracts, safe artifact access, fixed research/report nodes, graph assembly, and a SQLite-backed runtime. Keep the existing Hermes HTTP and Codex CLI adapters behind one structured-output interface, project graph state into the existing `TaskRecord`, and expose explicit resume endpoints to the currently served static UI.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic 2.8+, LangGraph 1.x, `langgraph-checkpoint-sqlite` 3.x, SQLite, pytest, python-docx, python-pptx, browser-native JavaScript and Node's built-in test runner.

## Global Constraints

- The node-to-executor map is fixed in code; neither Codex, Hermes, nor the user can reorder the graph.
- Codex owns request analysis, evidence audit, the Markdown master report, Word/PPT derivation instructions, revision, and quality analysis.
- Hermes owns public-source search, download, PDF/web parsing, OCR metadata, evidence location, and preliminary summaries.
- Public sources are the only automated research sources in this MVP.
- Hermes must respect source access controls and site terms, must not bypass paywalls, CAPTCHAs, robots restrictions, or authentication, and must record inaccessible items as failures.
- Commercial-database browser sessions, Codex App Server, PostgreSQL, multi-tenancy, and autonomous agent routing are outside this plan.
- The MVP Hermes HTTP service is co-located with the controller or mounts the same task workspace; a remote artifact-upload protocol is outside this plan.
- The Markdown master report is the sole content source for both DOCX and PPTX.
- Search and automatic revision are limited to two rounds each.
- SQLite checkpoint data contains only JSON-serializable state, relative paths, metadata, and hashes; full documents remain in the task workspace.
- Set `LANGGRAPH_STRICT_MSGPACK=true` for every runtime so a compromised checkpoint cannot deserialize arbitrary modules.
- Credentials, cookies, authorization headers, and browser-session material must never enter prompts, graph state, artifacts, or ordinary logs.
- Hermes may write only under `research/` and its own log directory; Codex may not modify `research/raw/`; only deterministic finalization may write `output/final/`.
- Preserve both FastAPI routes and the zero-dependency `backend/dev_server.py` route surface.
- Preserve existing Phase 2/3 artifact behavior unless a task explicitly replaces it with the new contract.
- Use raw `StateGraph`; do not add the deprecated `langgraph-supervisor` package.
- Approval nodes perform no side effects before `interrupt()`; LangGraph restarts the interrupted node from its beginning when resumed.
- Use TDD and commit after every independently testable task.

Run every command below from `D:\codex-project\APP\ai-report-ppt-controller`
after the first `cd ai-report-ppt-controller`.

## Scope Decomposition

This plan implements only Phase 1 from the approved design:

1. LangGraph plus the existing Codex CLI and Hermes HTTP adapters.
2. Mock-mode end-to-end execution, approvals, recovery, and export.
3. A minimal static UI for both approval points and exceptional blockers.

Create separate design/plan cycles before implementing:

- Codex App Server JSON-RPC streaming and thread management.
- Hermes logged-in browser adapters for Black Horse, PatSnap, or other commercial databases.

## File Structure

Create or modify the following focused units:

| File | Responsibility |
|---|---|
| `ai-report-ppt-controller/backend/models/workflow.py` | Pydantic contracts and JSON-serializable LangGraph state |
| `ai-report-ppt-controller/backend/workflows/artifacts.py` | Workspace permissions, atomic writes, hashes, finalization |
| `ai-report-ppt-controller/backend/workflows/dependencies.py` | Adapter bundle and test dependency injection |
| `ai-report-ppt-controller/backend/workflows/research_nodes.py` | Request analysis, search approval, Hermes collection, evidence audit |
| `ai-report-ppt-controller/backend/workflows/report_nodes.py` | Master report rendering, DOCX/PPTX derivation, QA, revision, export approval |
| `ai-report-ppt-controller/backend/workflows/graph.py` | Stable node names, conditional edges, graph compilation |
| `ai-report-ppt-controller/backend/workflows/runtime.py` | SQLite checkpointer, start/resume/state inspection |
| `ai-report-ppt-controller/backend/services/agent_adapters.py` | Structured Codex/Hermes output boundary |
| `ai-report-ppt-controller/backend/services/task_runner.py` | Existing task/file APIs plus LangGraph compatibility projection |
| `ai-report-ppt-controller/backend/models/task.py` | New fixed workflow steps and visible pending-approval fields |
| `ai-report-ppt-controller/backend/routers/task.py` | FastAPI start/resume/state endpoints |
| `ai-report-ppt-controller/backend/dev_server.py` | Matching local-server start/resume/state endpoints |
| `ai-report-ppt-controller/frontend/static/index.html` | Approval and blocker controls on the served UI |
| `ai-report-ppt-controller/frontend/static/app.js` | Render/resume behavior and polling |
| `ai-report-ppt-controller/frontend/static/styles.css` | Approval-state presentation |

---

### Task 1: Add LangGraph Dependencies and Boundary Contracts

**Files:**
- Modify: `ai-report-ppt-controller/pyproject.toml`
- Modify: `ai-report-ppt-controller/requirements.txt`
- Create: `ai-report-ppt-controller/backend/models/workflow.py`
- Modify: `ai-report-ppt-controller/backend/models/__init__.py`
- Create: `ai-report-ppt-controller/backend/tests/test_workflow_contracts.py`

**Interfaces:**
- Consumes: existing `TaskRequest.model_dump(mode="json")`
- Produces: `SearchPlan`, `ResearchPackage`, `EvidenceAudit`, `MasterReport`, `ReportManifest`, `QualityDecision`, `ApprovalDecision`, `ExportDecision`, and `WorkflowState`

- [ ] **Step 1: Write failing contract tests**

```python
from __future__ import annotations

from typing import get_type_hints

import pytest
from pydantic import ValidationError

from backend.models.workflow import (
    ApprovalDecision,
    EvidenceAudit,
    ResearchPackage,
    SearchPlan,
    WorkflowState,
)


def test_contracts_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SearchPlan.model_validate(
            {
                "schema": "search.plan.v1",
                "task_understanding": "research",
                "exclusions": [],
                "queries": [],
                "source_requirements": [],
                "success_criteria": [],
                "risks": [],
                "unknown": True,
            }
        )


def test_research_package_serializes_schema_alias() -> None:
    package = ResearchPackage.model_validate(
        {
            "schema": "research.package.v1",
            "task_id": "task-1",
            "research_round": 1,
            "queries": [],
            "sources": [],
            "evidence": [],
            "coverage_gaps": [],
            "failed_items": [],
            "created_at": "2026-07-30T12:00:00+08:00",
        }
    )
    assert package.model_dump(mode="json", by_alias=True)["schema"] == "research.package.v1"


def test_evidence_audit_status_is_closed_enum() -> None:
    with pytest.raises(ValidationError):
        EvidenceAudit.model_validate(
            {
                "schema": "evidence.audit.v1",
                "status": "maybe",
                "coverage": [],
                "source_quality_issues": [],
                "conflicts": [],
                "missing_items": [],
                "supplementary_queries": [],
                "blocking_reasons": [],
            }
        )


def test_search_approval_requires_edited_plan_for_edit_action() -> None:
    with pytest.raises(ValidationError):
        ApprovalDecision(action="edit_and_approve")


def test_workflow_state_stores_paths_not_document_bytes() -> None:
    annotations = get_type_hints(WorkflowState)
    assert annotations["research_package_path"] == str
    assert "raw_pdf" not in annotations
```

- [ ] **Step 2: Run the tests and verify import failure**

Run:

```powershell
cd ai-report-ppt-controller
python -m pytest backend/tests/test_workflow_contracts.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'backend.models.workflow'`.

- [ ] **Step 3: Add dependency floors**

Add to both dependency manifests:

```toml
"langgraph>=1.2,<2",
"langgraph-checkpoint-sqlite>=3,<4",
```

The corresponding `requirements.txt` lines are:

```text
langgraph>=1.2,<2
langgraph-checkpoint-sqlite>=3,<4
```

- [ ] **Step 4: Implement strict workflow contracts**

Create `backend/models/workflow.py` with this model pattern and all fields listed below:

```python
from __future__ import annotations

from operator import add
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    def as_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


def merge_mappings(
    left: dict[str, int],
    right: dict[str, int],
) -> dict[str, int]:
    return {**left, **right}


class SearchQuery(ContractModel):
    query_id: str
    query: str
    purpose: str
    keywords: list[str] = Field(default_factory=list)
    synonyms: list[str] = Field(default_factory=list)
    broader_terms: list[str] = Field(default_factory=list)
    narrower_terms: list[str] = Field(default_factory=list)
    source_types: list[str] = Field(default_factory=list)
    time_range: str = ""
    languages: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    required_files: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)


class PatentSearchScope(ContractModel):
    applicants: list[str] = Field(default_factory=list)
    inventors: list[str] = Field(default_factory=list)
    ipc_cpc: list[str] = Field(default_factory=list)
    publication_numbers: list[str] = Field(default_factory=list)
    date_constraints: dict[str, str] = Field(default_factory=dict)


class SearchPlan(ContractModel):
    schema_id: Literal["search.plan.v1"] = Field(default="search.plan.v1", alias="schema")
    task_understanding: str
    exclusions: list[str] = Field(default_factory=list)
    queries: list[SearchQuery] = Field(default_factory=list)
    source_requirements: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    patent_scope: PatentSearchScope = Field(default_factory=PatentSearchScope)


class SearchExecution(ContractModel):
    query_id: str
    database: str
    executed_query: str
    filters: dict[str, Any] = Field(default_factory=dict)
    executed_at: str
    hit_count: int | None = Field(default=None, ge=0)


class SourceRecord(ContractModel):
    source_id: str
    title: str
    source_type: str
    publisher: str = ""
    authors: list[str] = Field(default_factory=list)
    publication_date: str = ""
    url: str = ""
    retrieved_at: str
    language: str = ""
    local_file: str = ""
    sha256: str = ""
    parse_status: Literal["success", "partial", "failed", "pending"]
    parser: str = ""
    publication_number: str = ""
    application_number: str = ""
    priority_date: str = ""
    applicant: str = ""
    jurisdiction: str = ""
    legal_status: str = ""
    legal_status_source: str = ""
    legal_status_checked_at: str = ""
    metadata_verification_status: Literal["verified", "pending"] = "pending"

    @model_validator(mode="after")
    def validate_traceability(self) -> "SourceRecord":
        if self.local_file:
            normalized = self.local_file.replace("\\", "/").lstrip("/")
            parts = PurePosixPath(normalized).parts
            if ".." in parts or not normalized.startswith("research/raw/"):
                raise ValueError("local_file must be under research/raw")
            if not self.sha256:
                raise ValueError("downloaded sources require sha256")
        if self.legal_status and (
            not self.legal_status_source or not self.legal_status_checked_at
        ):
            raise ValueError(
                "legal status requires source and checked_at date"
            )
        return self


class EvidenceLocation(ContractModel):
    page: int | None = None
    section: str = ""
    paragraph: int | None = None
    figure: str = ""
    table: str = ""
    claim_number: str = ""


class EvidenceRecord(ContractModel):
    evidence_id: str
    source_id: str
    claim_supported: str
    excerpt: str = ""
    location: EvidenceLocation = Field(default_factory=EvidenceLocation)
    verification_status: Literal[
        "primary_source_verified",
        "secondary_source",
        "pending",
        "failed",
    ]
    limitations: list[str] = Field(default_factory=list)


class ResearchPackage(ContractModel):
    schema_id: Literal["research.package.v1"] = Field(default="research.package.v1", alias="schema")
    task_id: str
    research_round: int = Field(ge=1, le=2)
    queries: list[SearchQuery] = Field(default_factory=list)
    executions: list[SearchExecution] = Field(default_factory=list)
    sources: list[SourceRecord] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    coverage_gaps: list[str] = Field(default_factory=list)
    failed_items: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str


class EvidenceAudit(ContractModel):
    schema_id: Literal["evidence.audit.v1"] = Field(default="evidence.audit.v1", alias="schema")
    status: Literal["sufficient", "insufficient", "conflicting", "invalid_package"]
    coverage: list[dict[str, Any]] = Field(default_factory=list)
    source_quality_issues: list[dict[str, Any]] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    missing_items: list[str] = Field(default_factory=list)
    supplementary_queries: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)


class ReportClaim(ContractModel):
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    claim_type: Literal["fact", "analysis", "assumption", "pending"]

    @model_validator(mode="after")
    def require_evidence_for_fact(self) -> "ReportClaim":
        if self.claim_type == "fact" and not self.evidence_ids:
            raise ValueError("factual claims require at least one evidence_id")
        return self


class ReportSection(ContractModel):
    section_id: str
    title: str
    conclusion: ReportClaim
    claims: list[ReportClaim] = Field(default_factory=list)


class MasterReport(ContractModel):
    schema_id: Literal["master.report.v1"] = Field(default="master.report.v1", alias="schema")
    title: str
    executive_summary: list[ReportClaim] = Field(default_factory=list)
    sections: list[ReportSection] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    recommendations: list[ReportClaim] = Field(default_factory=list)


class ArtifactRef(ContractModel):
    relative_path: str
    sha256: str
    size: int = Field(ge=0)
    status: Literal["draft", "final", "evidence"]


class ReportManifest(ContractModel):
    schema_id: Literal["report.manifest.v1"] = Field(default="report.manifest.v1", alias="schema")
    master_report: ArtifactRef
    word: ArtifactRef | None = None
    powerpoint: ArtifactRef | None = None
    word_source_sha256: str = ""
    powerpoint_source_sha256: str = ""
    source_register: ArtifactRef
    citation_index: ArtifactRef
    evidence_audit: ArtifactRef
    generated_at: str
    version: int = Field(ge=1)


class QualityIssue(ContractModel):
    issue_type: str
    location: str
    evidence: str
    instruction: str


class QualityDecision(ContractModel):
    schema_id: Literal["quality.decision.v1"] = Field(default="quality.decision.v1", alias="schema")
    passed: bool = Field(alias="pass")
    blocking_issues: list[QualityIssue] = Field(default_factory=list)
    minor_issues: list[QualityIssue] = Field(default_factory=list)
    citation_coverage: Literal["complete", "incomplete"]
    word_ppt_consistency: Literal["consistent", "inconsistent", "not_applicable"]
    artifact_validation: Literal["passed", "failed"]
    revision_instruction: str = ""


class ApprovalDecision(ContractModel):
    action: Literal["approve", "edit_and_approve", "regenerate", "cancel"]
    feedback: str = ""
    edited_search_plan: SearchPlan | None = None

    @model_validator(mode="after")
    def require_edited_plan(self) -> "ApprovalDecision":
        if self.action == "edit_and_approve" and self.edited_search_plan is None:
            raise ValueError("edited_search_plan is required for edit_and_approve")
        return self


class ExportDecision(ContractModel):
    action: Literal[
        "approve_all",
        "approve_word_only",
        "approve_ppt_only",
        "request_revision",
        "cancel_publication",
    ]
    feedback: str = ""


class HumanResolution(ContractModel):
    action: Literal["continue_with_limitations", "revise", "cancel"]
    feedback: str = ""


class WorkflowError(ContractModel):
    node: str
    category: Literal["transient", "contract", "artifact", "security", "fatal"]
    message: str
    retryable: bool
    attempt: int = Field(ge=1)


class WorkflowState(TypedDict, total=False):
    schema_version: str
    task_id: str
    request: dict[str, Any]
    current_node: str
    status: str
    search_plan: dict[str, Any]
    search_plan_version: int
    search_approval: dict[str, Any]
    search_approval_record_path: str
    research_round: int
    research_package_path: str
    evidence_audit: dict[str, Any]
    master_report_path: str
    report_manifest: dict[str, Any]
    qa_result: dict[str, Any]
    revision_round: int
    quality_issue_history: Annotated[list[str], add]
    export_approval: dict[str, Any]
    export_approval_record_path: str
    human_action: dict[str, Any]
    retry_counters: Annotated[dict[str, int], merge_mappings]
    errors: Annotated[list[dict[str, Any]], add]
    audit_events: Annotated[list[dict[str, Any]], add]
```

- [ ] **Step 5: Export the contracts**

Add explicit imports to `backend/models/__init__.py`:

```python
from backend.models.workflow import (
    ApprovalDecision,
    EvidenceAudit,
    ExportDecision,
    MasterReport,
    QualityDecision,
    ReportManifest,
    ResearchPackage,
    SearchPlan,
    WorkflowState,
)

__all__ = [
    "ApprovalDecision",
    "EvidenceAudit",
    "ExportDecision",
    "MasterReport",
    "QualityDecision",
    "ReportManifest",
    "ResearchPackage",
    "SearchPlan",
    "WorkflowState",
]
```

- [ ] **Step 6: Run focused and existing model tests**

Run:

```powershell
python -m pytest backend/tests/test_workflow_contracts.py backend/tests/test_task_history.py -v
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

```powershell
git add pyproject.toml requirements.txt backend/models backend/tests/test_workflow_contracts.py
git commit -m "feat: add LangGraph workflow contracts"
```

---

### Task 2: Enforce Artifact Permissions, Atomic Writes, and Evidence Hashes

**Files:**
- Create: `ai-report-ppt-controller/backend/workflows/__init__.py`
- Create: `ai-report-ppt-controller/backend/workflows/artifacts.py`
- Modify: `ai-report-ppt-controller/backend/services/phase2_records.py`
- Create: `ai-report-ppt-controller/backend/tests/test_workflow_artifacts.py`

**Interfaces:**
- Consumes: `workspace: Path`, task-relative POSIX paths
- Produces: `ArtifactStore.write_json`, `write_json_once`, `write_text`, `write_text_once`, `register_evidence_file`, `snapshot_raw_hashes`, `assert_raw_unchanged`, `artifact_ref`, and `finalize`

- [ ] **Step 1: Write failing permission and hashing tests**

```python
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from backend.workflows.artifacts import ArtifactStore, ArtifactViolation


def test_hermes_cannot_write_report_files(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    with pytest.raises(ArtifactViolation):
        store.write_text("hermes", "draft/master_report.md", "forbidden")
    with pytest.raises(ArtifactViolation):
        store.write_text(
            "hermes",
            "research/../draft/master_report.md",
            "traversal",
        )


def test_codex_cannot_modify_raw_evidence(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    raw = tmp_path / "research" / "raw" / "source.pdf"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"source")
    with pytest.raises(ArtifactViolation):
        store.write_text("codex", "research/raw/source.pdf", "changed")


def test_register_evidence_returns_stable_hash(tmp_path: Path) -> None:
    source = tmp_path / "research" / "raw" / "source.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source")
    ref = ArtifactStore(tmp_path).register_evidence_file("research/raw/source.pdf")
    assert ref.sha256 == "41cf6794ba4200b839c53531555f0f3998df4cbb01a4d5cb0b94e3ca5e23947d"
    assert ref.relative_path == "research/raw/source.pdf"


def test_atomic_json_write_leaves_no_temp_file(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_json("system", "state/example.json", {"ok": True})
    assert json.loads((tmp_path / "state" / "example.json").read_text(encoding="utf-8")) == {"ok": True}
    assert list((tmp_path / "state").glob("*.tmp")) == []


def test_existing_raw_evidence_is_immutable(tmp_path: Path) -> None:
    raw = tmp_path / "research" / "raw" / "source.pdf"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"original")
    store = ArtifactStore(tmp_path)
    before = store.snapshot_raw_hashes()
    raw.write_bytes(b"modified")
    with pytest.raises(ArtifactViolation, match="raw evidence hash changed"):
        store.assert_raw_unchanged(before)


def test_write_json_once_accepts_same_replay_and_rejects_change(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    path = "research/approvals/decision.json"
    store.write_json_once("system", path, {"action": "approve"})
    store.write_json_once("system", path, {"action": "approve"})
    with pytest.raises(ArtifactViolation, match="different content"):
        store.write_json_once("system", path, {"action": "cancel"})
```

- [ ] **Step 2: Verify the tests fail**

Run:

```powershell
python -m pytest backend/tests/test_workflow_artifacts.py -v
```

Expected: collection fails because `backend.workflows.artifacts` does not exist.

- [ ] **Step 3: Implement the artifact store**

Create `backend/workflows/artifacts.py`:

```python
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from uuid import uuid4

from backend.models.workflow import ArtifactRef
from backend.services.security import safe_join


WRITE_ROOTS = {
    "hermes": ("research", "logs/agents/hermes"),
    "codex": ("draft", "build", "review", "output/draft", "logs/agents/codex"),
    "system": ("state", "research", "draft", "build", "review", "output", "logs"),
}

FINALIZABLE_PATHS = {
    "draft/master_report.md",
    "draft/source_register.json",
    "draft/citation_index.json",
    "review/evidence_audit.json",
    "review/workflow_audit.json",
    "output/draft/final_report.docx",
    "output/draft/final_presentation.pptx",
}

IMMUTABLE_PREFIXES = (
    "research/raw",
    "research/search_plan_versions",
    "research/approvals",
    "draft/versions",
    "review/approvals",
)


class ArtifactViolation(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class ArtifactStore:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()

    def resolve(self, relative_path: str) -> Path:
        if Path(relative_path).is_absolute():
            raise ArtifactViolation("absolute artifact paths are forbidden")
        try:
            target = safe_join(self.workspace, *Path(relative_path).parts)
        except Exception as exc:
            raise ArtifactViolation("artifact path escaped the task workspace") from exc
        resolved = target.resolve()
        if self.workspace != resolved and self.workspace not in resolved.parents:
            raise ArtifactViolation("artifact path escaped the task workspace")
        return resolved

    def assert_write_allowed(self, actor: str, relative_path: str) -> None:
        roots = WRITE_ROOTS.get(actor)
        if roots is None:
            raise ArtifactViolation(f"unknown artifact actor: {actor}")
        target = self.resolve(relative_path)
        allowed_roots = [self.resolve(root) for root in roots]
        if actor == "codex":
            raw_root = self.resolve("research/raw")
            if target == raw_root or raw_root in target.parents:
                raise ArtifactViolation("Codex cannot modify raw evidence")
        if not any(
            target == root or root in target.parents
            for root in allowed_roots
        ):
            normalized = Path(relative_path).as_posix()
            raise ArtifactViolation(f"{actor} cannot write {normalized}")

    def write_text(self, actor: str, relative_path: str, content: str) -> Path:
        self.assert_write_allowed(actor, relative_path)
        target = self.resolve(relative_path)
        immutable_roots = [self.resolve(root) for root in IMMUTABLE_PREFIXES]
        if target.exists() and any(
            target == root or root in target.parents
            for root in immutable_roots
        ):
            raise ArtifactViolation(
                f"immutable artifact already exists: {relative_path}"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
        return target

    def write_json(self, actor: str, relative_path: str, payload: object) -> Path:
        return self.write_text(
            actor,
            relative_path,
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )

    def write_text_once(
        self,
        actor: str,
        relative_path: str,
        content: str,
    ) -> Path:
        target = self.resolve(relative_path)
        if target.exists():
            if target.read_text(encoding="utf-8") != content:
                raise ArtifactViolation(
                    f"immutable artifact has different content: {relative_path}"
                )
            return target
        return self.write_text(actor, relative_path, content)

    def write_json_once(
        self,
        actor: str,
        relative_path: str,
        payload: object,
    ) -> Path:
        content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        return self.write_text_once(actor, relative_path, content)

    def artifact_ref(self, relative_path: str, status: str) -> ArtifactRef:
        path = self.resolve(relative_path)
        return ArtifactRef(
            relative_path=Path(relative_path).as_posix(),
            sha256=sha256_file(path),
            size=path.stat().st_size,
            status=status,
        )

    def register_evidence_file(self, relative_path: str) -> ArtifactRef:
        normalized = Path(relative_path).as_posix()
        path = self.resolve(normalized)
        raw_root = self.resolve("research/raw")
        if raw_root not in path.parents:
            raise ArtifactViolation("evidence must be stored under research/raw")
        return self.artifact_ref(normalized, "evidence")

    def snapshot_raw_hashes(self) -> dict[str, str]:
        raw_root = self.resolve("research/raw")
        if not raw_root.exists():
            return {}
        hashes = {}
        for path in raw_root.rglob("*"):
            if path.is_symlink():
                raise ArtifactViolation(
                    f"symlink is forbidden in raw evidence: {path.name}"
                )
            if path.is_file():
                hashes[path.relative_to(self.workspace).as_posix()] = (
                    sha256_file(path)
                )
        return hashes

    def assert_raw_unchanged(self, before: dict[str, str]) -> None:
        for relative_path, expected_hash in before.items():
            path = self.resolve(relative_path)
            if not path.exists() or sha256_file(path) != expected_hash:
                raise ArtifactViolation(
                    f"raw evidence hash changed: {relative_path}"
                )

    def finalize(self, approved_paths: list[str]) -> list[ArtifactRef]:
        final_refs: list[ArtifactRef] = []
        for relative_path in approved_paths:
            normalized = Path(relative_path).as_posix()
            if normalized not in FINALIZABLE_PATHS:
                raise ArtifactViolation(
                    f"artifact is not finalizable: {normalized}"
                )
            source = self.resolve(relative_path)
            target_relative = f"output/final/{source.name}"
            target = self.resolve(target_relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            final_refs.append(self.artifact_ref(target_relative, "final"))
        return final_refs
```

- [ ] **Step 4: Register new workflow artifacts in file metadata**

Extend `PHASE3_DRAFT_ARTIFACTS` in `backend/services/phase2_records.py` with:

```python
"draft/master_report.md": {
    "file_type": "master_report",
    "category": "workflow_draft",
    "description": "Canonical Markdown report derived from validated evidence",
},
"draft/report_outline.json": {
    "file_type": "report_outline",
    "category": "workflow_draft",
    "description": "Structured validation and revision aid; not a document-generation source",
},
"draft/report_manifest.json": {
    "file_type": "report_manifest",
    "category": "workflow_draft",
    "description": "Manifest for the canonical report and derived artifacts",
},
"draft/source_register.json": {
    "file_type": "source_register",
    "category": "workflow_draft",
    "description": "Source list derived from the validated research package",
},
"draft/citation_index.json": {
    "file_type": "citation_index",
    "category": "workflow_draft",
    "description": "Evidence IDs mapped to source and location",
},
"review/evidence_audit.json": {
    "file_type": "evidence_audit",
    "category": "workflow_review",
    "description": "Structured Codex evidence completeness decision",
},
"review/quality_decision.json": {
    "file_type": "quality_decision",
    "category": "workflow_review",
    "description": "Structured final quality decision",
},
"review/workflow_audit.json": {
    "file_type": "workflow_audit",
    "category": "workflow_review",
    "description": "Node, actor, decision, round, and approval event history",
},
```

- [ ] **Step 5: Run tests**

```powershell
python -m pytest backend/tests/test_workflow_artifacts.py backend/tests/test_phase2_source_review.py -v
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```powershell
git add backend/workflows backend/services/phase2_records.py backend/tests/test_workflow_artifacts.py
git commit -m "feat: enforce workflow artifact boundaries"
```

---

### Task 3: Add Structured Codex and Hermes Adapter Calls

**Files:**
- Modify: `ai-report-ppt-controller/backend/services/agent_adapters.py`
- Modify: `ai-report-ppt-controller/backend/config.py`
- Modify: `ai-report-ppt-controller/.env.example`
- Create: `ai-report-ppt-controller/backend/workflows/execution.py`
- Create: `ai-report-ppt-controller/backend/tests/test_structured_agent_adapters.py`

**Interfaces:**
- Consumes: `task_name`, `prompt`, `workspace`, a `ContractModel` subclass, sandbox mode, and a deterministic idempotency key
- Produces: `AgentAdapter.run_structured_task(task_name, prompt, workspace, output_model, idempotency_key, extra_context, sandbox) -> ContractModel`

- [ ] **Step 1: Write failing adapter tests**

```python
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from backend.config import AppConfig
from backend.models.workflow import SearchPlan
from backend.services.agent_adapters import CodexCLIAdapter, MockHermesAdapter
from backend.workflows.execution import execute_structured_with_retry, make_idempotency_key


def test_codex_structured_call_uses_schema_and_output_file(tmp_path: Path) -> None:
    settings = AppConfig(codex_mode="cli", codex_command="codex", codex_exec_args="exec")
    adapter = CodexCLIAdapter(settings)
    payload = {
        "schema": "search.plan.v1",
        "task_understanding": "test",
        "exclusions": [],
        "queries": [],
        "source_requirements": [],
        "success_criteria": [],
        "risks": [],
    }

    def fake_run(command, **kwargs):
        output_index = command.index("-o") + 1
        Path(command[output_index]).write_text(json.dumps(payload), encoding="utf-8")
        return type("Completed", (), {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""})()

    with patch("backend.services.agent_adapters.resolve_command", return_value="codex"), patch(
        "backend.services.agent_adapters.subprocess.run", side_effect=fake_run
    ) as run:
        result = adapter.run_structured_task(
            "analyze_request",
            "analyze",
            tmp_path,
            SearchPlan,
            idempotency_key="task-1-analyze-v1",
            sandbox="read-only",
        )

    command = run.call_args.args[0]
    assert "--output-schema" in command
    assert "--sandbox" in command
    assert result.task_understanding == "test"


def test_mock_hermes_structured_output_is_validated(tmp_path: Path) -> None:
    adapter = MockHermesAdapter()
    result = adapter.run_structured_task(
        "collect_sources",
        "collect",
        tmp_path,
        SearchPlan,
        idempotency_key="task-1-collect-r1-v1",
        extra_context={"structured_result": {
            "schema": "search.plan.v1",
            "task_understanding": "mock",
            "exclusions": [],
            "queries": [],
            "source_requirements": [],
            "success_criteria": [],
            "risks": [],
        }},
    )
    assert isinstance(result, SearchPlan)


def test_retry_policy_is_bounded_and_cached(tmp_path: Path) -> None:
    calls = []
    delays = []
    payload = {
        "schema": "search.plan.v1",
        "task_understanding": "retry",
    }

    def transient_then_success(validation_feedback: str):
        calls.append(validation_feedback)
        if len(calls) < 3:
            raise TimeoutError("temporary")
        return payload

    cache_path = tmp_path / "state" / "agent_results" / "stable-key.json"
    first = execute_structured_with_retry(
        transient_then_success,
        SearchPlan,
        cache_path,
        sleep=delays.append,
    )
    second = execute_structured_with_retry(
        lambda feedback: (_ for _ in ()).throw(AssertionError("cache miss")),
        SearchPlan,
        cache_path,
        sleep=delays.append,
    )
    assert first == second
    assert len(calls) == 3
    assert delays == [1, 2]


def test_invalid_contract_retries_once(tmp_path: Path) -> None:
    calls = []

    def invalid_then_valid(validation_feedback: str):
        calls.append(validation_feedback)
        if len(calls) == 1:
            return {"schema": "search.plan.v1"}
        assert "task_understanding" in validation_feedback
        return {
            "schema": "search.plan.v1",
            "task_understanding": "corrected",
        }

    result = execute_structured_with_retry(
        invalid_then_valid,
        SearchPlan,
        tmp_path / "state" / "agent_results" / "contract-key.json",
        sleep=lambda delay: None,
    )
    assert result.task_understanding == "corrected"
    assert len(calls) == 2


def test_idempotency_key_changes_with_input_version() -> None:
    first = make_idempotency_key("t1", "collect_sources", 1, {"query": "GaN"})
    same = make_idempotency_key("t1", "collect_sources", 1, {"query": "GaN"})
    changed = make_idempotency_key("t1", "collect_sources", 1, {"query": "SiC"})
    assert first == same
    assert first != changed
```

- [ ] **Step 2: Run tests to verify missing method failure**

```powershell
python -m pytest backend/tests/test_structured_agent_adapters.py -v
```

Expected: failures state that `run_structured_task` does not exist.

- [ ] **Step 3: Add bounded retries, idempotency, and the generic interface**

Create `backend/workflows/execution.py`:

```python
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Callable, TypeVar
from uuid import uuid4

from pydantic import ValidationError

from backend.models.workflow import ContractModel

ContractT = TypeVar("ContractT", bound=ContractModel)


class TransientAgentError(ConnectionError):
    pass


class AgentExecutionError(RuntimeError):
    def __init__(self, category: str, attempts: int, message: str):
        super().__init__(message)
        self.category = category
        self.attempts = attempts


TRANSIENT_ERRORS = (
    TimeoutError,
    ConnectionError,
    subprocess.TimeoutExpired,
    TransientAgentError,
)


def make_idempotency_key(
    task_id: str,
    node_name: str,
    round_number: int,
    input_payload: dict,
) -> str:
    input_version = hashlib.sha256(
        json.dumps(
            input_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    raw = f"{task_id}:{node_name}:{round_number}:{input_version}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def execution_metadata_path(cache_path: Path) -> Path:
    return cache_path.with_name(f"{cache_path.stem}.meta.json")


def retry_count_for(workspace: Path, idempotency_key: str) -> int:
    path = execution_metadata_path(
        workspace / "state" / "agent_results" / f"{idempotency_key}.json"
    )
    if not path.exists():
        return 0
    return int(json.loads(path.read_text(encoding="utf-8")).get("retry_count", 0))


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def execute_structured_with_retry(
    operation: Callable[[str], dict],
    output_model: type[ContractT],
    cache_path: Path,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> ContractT:
    if cache_path.exists():
        return output_model.model_validate_json(cache_path.read_text(encoding="utf-8"))

    transient_retries = 0
    contract_retries = 0
    validation_feedback = ""
    while True:
        try:
            payload = operation(validation_feedback)
        except TRANSIENT_ERRORS as exc:
            if transient_retries >= 2:
                _atomic_json(
                    execution_metadata_path(cache_path),
                    {
                        "status": "failed",
                        "retry_count": transient_retries,
                        "category": "transient",
                    },
                )
                raise AgentExecutionError("transient", 3, str(exc)) from exc
            sleep(2**transient_retries)
            transient_retries += 1
            continue

        try:
            result = output_model.model_validate(payload)
        except ValidationError as exc:
            if contract_retries >= 1:
                _atomic_json(
                    execution_metadata_path(cache_path),
                    {
                        "status": "failed",
                        "retry_count": contract_retries,
                        "category": "contract",
                    },
                )
                raise AgentExecutionError("contract", 2, str(exc)) from exc
            contract_retries += 1
            validation_feedback = json.dumps(
                exc.errors(include_input=False),
                ensure_ascii=False,
            )
            continue

        _atomic_json(cache_path, result.as_payload())
        _atomic_json(
            execution_metadata_path(cache_path),
            {
                "status": "success",
                "retry_count": transient_retries + contract_retries,
                "category": "",
            },
        )
        return result
```

The adapter method is now:

```python
def run_structured_task(
    self,
    task_name: str,
    prompt: str,
    workspace: Path,
    output_model: type[ContractT],
    *,
    idempotency_key: str,
    extra_context: dict[str, Any] | None = None,
    sandbox: Literal["read-only", "workspace-write"] = "read-only",
) -> ContractT
```

Every adapter must call `execute_structured_with_retry` with
`workspace / "state" / "agent_results" / f"{idempotency_key}.json"`. Convert
Hermes HTTP 429 and 5xx responses plus connection timeouts into
`TransientAgentError`, a subclass of `ConnectionError`. Pass the key in the
Hermes `Idempotency-Key` header and request body. The second contract attempt
must receive `validation_feedback`; never include it in the cache key.

The base implementation wraps the existing `run_task`:

```python
def operation(validation_feedback: str) -> dict:
    context = dict(extra_context or {})
    context.update({
        "output_schema": output_model.model_json_schema(by_alias=True),
        "idempotency_key": idempotency_key,
        "validation_feedback": validation_feedback,
    })
    result = self.run_task(task_name, prompt, workspace, context)
    if result.get("status") != "success":
        if result.get("category") == "transient":
            raise TransientAgentError(result.get("error") or "transient agent failure")
        raise RuntimeError(result.get("error") or f"{task_name} failed")
    return result["result"]


return execute_structured_with_retry(
    operation,
    output_model,
    workspace / "state" / "agent_results" / f"{idempotency_key}.json",
)
```

For mocks, return `context["structured_result"]` when supplied. Otherwise use
the mock's task-name-specific valid payloads completed in Task 10.

For `HermesAPIAdapter`, send only `task_name`, prompt, JSON Schema,
idempotency key, task workspace path, and the allowed write roots
`research/` and `logs/agents/hermes/`. Expect
`{"status": "success", "result": <ResearchPackage>}`. After validation,
resolve every non-empty `SourceRecord.local_file` through `ArtifactStore`,
require it to be under `research/raw/`, and verify its SHA-256 before the node
accepts the package. The API key is read from the configured environment
variable and used only in the HTTP header; it is never added to the request
body, context, checkpoint, or log.

- [ ] **Step 4: Override the Codex CLI structured method**

Add a Codex-specific implementation that writes a JSON Schema and final output file:

```python
def run_structured_task(
    self,
    task_name: str,
    prompt: str,
    workspace: Path,
    output_model: type[ContractT],
    *,
    idempotency_key: str,
    extra_context: dict[str, Any] | None = None,
    sandbox: Literal["read-only", "workspace-write"] = "read-only",
) -> ContractT:
    resolved = resolve_command(self.settings.codex_command)
    if not resolved:
        raise RuntimeError("Codex command was not found on PATH.")

    schema_path = workspace / "prompts" / "schemas" / f"{idempotency_key}.schema.json"
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path.write_text(
        json.dumps(output_model.model_json_schema(by_alias=True), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    attempt = 0

    def operation(validation_feedback: str) -> dict:
        nonlocal attempt
        attempt += 1
        output_path = (
            workspace / "prompts" / "results" / f"{idempotency_key}.{attempt}.json"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            resolved,
            *shlex.split(self.settings.codex_exec_args),
            "--sandbox",
            sandbox,
            "--output-schema",
            str(schema_path),
            "-o",
            str(output_path),
        ]
        correction = (
            f"\n\nVALIDATION ERRORS FROM THE PREVIOUS ATTEMPT\n{validation_feedback}"
            if validation_feedback
            else ""
        )
        completed = subprocess.run(
            command,
            input=prompt + correction,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=self.settings.agent_timeout_seconds,
            shell=False,
            encoding="utf-8",
            errors="replace",
        )
        log_path = (
            workspace / "logs" / "agents" / "codex" / f"{task_name}.{attempt}.log"
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            mask_sensitive((completed.stderr or "") + "\n" + (completed.stdout or "")),
            encoding="utf-8",
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"Codex structured task failed with exit code {completed.returncode}"
            )
        return json.loads(output_path.read_text(encoding="utf-8"))

    return execute_structured_with_retry(
        operation,
        output_model,
        workspace / "state" / "agent_results" / f"{idempotency_key}.json",
    )
```

- [ ] **Step 5: Add bounded agent timeout configuration**

Add to `AppConfig`:

```python
agent_timeout_seconds: int = Field(
    default_factory=lambda: int(os.getenv("AGENT_TIMEOUT_SECONDS", "1800")),
    ge=30,
    le=7200,
)
```

Add to `.env.example`:

```text
AGENT_TIMEOUT_SECONDS=1800
```

- [ ] **Step 6: Run adapter tests and compilation**

```powershell
python -m pytest backend/tests/test_structured_agent_adapters.py -v
python -m compileall backend
```

Expected: tests pass and compilation exits with code 0.

- [ ] **Step 7: Commit**

```powershell
git add backend/services/agent_adapters.py backend/workflows/execution.py backend/config.py .env.example backend/tests/test_structured_agent_adapters.py
git commit -m "feat: add structured agent adapter calls"
```

---

### Task 4: Implement Fixed Research Nodes and Search Approval

**Files:**
- Create: `ai-report-ppt-controller/backend/workflows/dependencies.py`
- Create: `ai-report-ppt-controller/backend/workflows/research_nodes.py`
- Create: `ai-report-ppt-controller/backend/prompts/codex_search_plan.txt`
- Create: `ai-report-ppt-controller/backend/prompts/hermes_collect_sources.txt`
- Create: `ai-report-ppt-controller/backend/prompts/codex_evidence_audit.txt`
- Create: `ai-report-ppt-controller/backend/tests/test_research_nodes.py`

**Interfaces:**
- Consumes: `WorkflowState`, `AgentAdapter`, `ArtifactStore`
- Produces: node updates plus `route_search_approval(state)` and `route_evidence(state)`

- [ ] **Step 1: Write failing node and routing tests**

```python
from __future__ import annotations

from pathlib import Path

from backend.models.workflow import ApprovalDecision, EvidenceAudit, ResearchPackage, SearchPlan
from backend.workflows.dependencies import WorkflowDependencies
from backend.workflows.research_nodes import (
    analyze_request,
    audit_evidence,
    collect_sources,
    route_evidence,
)


class StubAdapter:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def run_structured_task(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


def test_analyze_request_always_uses_codex(tmp_path: Path) -> None:
    plan = SearchPlan(
        task_understanding="test",
        queries=[],
        source_requirements=[],
        success_criteria=[],
        exclusions=[],
        risks=[],
    )
    codex = StubAdapter(plan)
    hermes = StubAdapter(plan)
    deps = WorkflowDependencies.for_test(tmp_path, codex=codex, hermes=hermes)
    update = analyze_request({"task_id": "t1", "request": {"title": "GaN"}}, deps)
    assert len(codex.calls) == 1
    assert hermes.calls == []
    assert update["search_plan"]["schema"] == "search.plan.v1"


def test_collect_sources_always_uses_hermes(tmp_path: Path) -> None:
    package = ResearchPackage(
        task_id="t1",
        research_round=1,
        queries=[],
        sources=[],
        evidence=[],
        coverage_gaps=[],
        failed_items=[],
        created_at="2026-07-30T12:00:00+08:00",
    )
    codex = StubAdapter(package)
    hermes = StubAdapter(package)
    deps = WorkflowDependencies.for_test(tmp_path, codex=codex, hermes=hermes)
    update = collect_sources(
        {"task_id": "t1", "research_round": 0, "search_plan": {}},
        deps,
    )
    assert codex.calls == []
    assert len(hermes.calls) == 1
    assert update["research_round"] == 1


def test_insufficient_evidence_routes_to_second_research_round() -> None:
    state = {
        "research_round": 1,
        "evidence_audit": EvidenceAudit(
            status="insufficient",
            coverage=[],
            source_quality_issues=[],
            conflicts=[],
            missing_items=["missing"],
            supplementary_queries=["query"],
            blocking_reasons=[],
        ).as_payload(),
    }
    assert route_evidence(state) == "collect_sources"


def test_second_insufficient_round_routes_to_human() -> None:
    state = {
        "research_round": 2,
        "evidence_audit": EvidenceAudit(
            status="insufficient",
            coverage=[],
            source_quality_issues=[],
            conflicts=[],
            missing_items=["missing"],
            supplementary_queries=[],
            blocking_reasons=[],
        ).as_payload(),
    }
    assert route_evidence(state) == "human_evidence_review"
```

- [ ] **Step 2: Verify tests fail**

```powershell
python -m pytest backend/tests/test_research_nodes.py -v
```

Expected: imports fail because the workflow node modules do not exist.

- [ ] **Step 3: Add dependency injection**

Create `backend/workflows/dependencies.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from backend.services.agent_adapters import AgentAdapter
from backend.workflows.artifacts import ArtifactStore


ProgressCallback = Callable[[str, str, dict], None]


def no_progress(node: str, status: str, payload: dict) -> None:
    return None


@dataclass
class WorkflowDependencies:
    codex: AgentAdapter
    hermes: AgentAdapter
    artifacts: ArtifactStore
    progress: ProgressCallback = no_progress

    @classmethod
    def for_test(
        cls,
        workspace: Path,
        *,
        codex: AgentAdapter,
        hermes: AgentAdapter,
    ) -> "WorkflowDependencies":
        return cls(codex=codex, hermes=hermes, artifacts=ArtifactStore(workspace))
```

- [ ] **Step 4: Write role-specific prompt templates**

`backend/prompts/codex_search_plan.txt`:

```text
You are the fixed Codex analysis node. Analyze the supplied task request and return only the SearchPlan structure required by the provided JSON Schema.
Use public sources only. Preserve the requested region and time boundary. Include patent-compatible fields when patent searching is enabled.
Do not search, download files, call Hermes, change workflow order, or generate the final report.
```

`backend/prompts/hermes_collect_sources.txt`:

```text
You are the fixed Hermes research node. Execute only the approved queries and supplementary queries supplied by LangGraph.
Search public sources, download allowed files, parse PDF/web content, record OCR/parser status, and return the required ResearchPackage.
For every executed query, record the database, exact query, filters, execution time, and hit count when available.
Every evidence item must reference a source_id and an explicit page, section, paragraph, figure, or table when available.
Leave unavailable patent metadata or legal status blank and mark metadata verification pending; never infer it.
Do not write or revise the final report. Do not invent unavailable metadata.
```

`backend/prompts/codex_evidence_audit.txt`:

```text
You are the fixed Codex evidence-audit node. Compare the ResearchPackage with the approved SearchPlan success criteria.
Return only the EvidenceAudit structure. Use status sufficient only when the evidence meets the stated criteria and key claims are traceable.
Use insufficient for fixable gaps, conflicting for material source conflicts, and invalid_package for malformed or unusable evidence.
Do not call Hermes or change the workflow.
```

- [ ] **Step 5: Implement research nodes and pure routes**

Create `backend/workflows/research_nodes.py` with:

```python
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from langgraph.types import interrupt

from backend.models.workflow import (
    ApprovalDecision,
    EvidenceAudit,
    HumanResolution,
    ResearchPackage,
    SearchPlan,
    WorkflowState,
)
from backend.services.security import mask_sensitive
from backend.workflows.artifacts import ArtifactViolation
from backend.workflows.dependencies import WorkflowDependencies
from backend.workflows.execution import make_idempotency_key, retry_count_for


PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"


def _prompt(name: str, payload: dict) -> str:
    instruction = (PROMPT_DIR / name).read_text(encoding="utf-8")
    return f"{instruction}\n\nINPUT\n{json.dumps(payload, ensure_ascii=False, indent=2)}"


def _payload_hash(payload: dict) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _audit_event(
    node: str,
    actor: str,
    status: str,
    *,
    round_number: int = 0,
    decision: str = "",
    retry_count: int = 0,
    idempotency_key: str = "",
    artifacts: list[dict] | None = None,
) -> dict:
    return {
        "at": datetime.now().astimezone().isoformat(),
        "node": node,
        "actor": actor,
        "status": status,
        "round": round_number,
        "decision": decision,
        "schema_version": "workflow.audit.v1",
        "retry_count": retry_count,
        "idempotency_key": idempotency_key,
        "artifacts": artifacts or [],
    }


def initialize_task(state: WorkflowState, deps: WorkflowDependencies) -> dict:
    deps.progress("initialize_task", "running", {})
    update = {
        "schema_version": "workflow.state.v1",
        "current_node": "initialize_task",
        "status": "running",
        "search_plan_version": 0,
        "research_round": 0,
        "revision_round": 0,
        "quality_issue_history": [],
        "retry_counters": {},
        "errors": [],
        "audit_events": [],
    }
    deps.progress("initialize_task", "success", update)
    return update


def analyze_request(state: WorkflowState, deps: WorkflowDependencies) -> dict:
    deps.progress("analyze_request", "running", {})
    next_version = int(state.get("search_plan_version", 0)) + 1
    plan_input = {
        "request": state["request"],
        "prior_plan": state.get("search_plan", {}),
        "review_feedback": state.get("search_approval", {}).get("feedback", ""),
        "target_version": next_version,
    }
    key = make_idempotency_key(
        state["task_id"],
        "analyze_request",
        next_version,
        plan_input,
    )
    plan = deps.codex.run_structured_task(
        "analyze_request",
        _prompt("codex_search_plan.txt", plan_input),
        deps.artifacts.workspace,
        SearchPlan,
        idempotency_key=key,
        sandbox="read-only",
    )
    deps.artifacts.write_json_once(
        "system",
        f"research/search_plan_versions/v{next_version}.json",
        plan.as_payload(),
    )
    update = {
        "current_node": "analyze_request",
        "search_plan": plan.as_payload(),
        "search_plan_version": next_version,
        "status": "running",
        "retry_counters": {
            "analyze_request": retry_count_for(deps.artifacts.workspace, key)
        },
    }
    deps.progress("analyze_request", "success", update)
    return update


def approve_search_plan(
    state: WorkflowState,
    deps: WorkflowDependencies,
) -> dict:
    decision = ApprovalDecision.model_validate(
        interrupt(
            {
                "kind": "search_plan",
                "task_id": state["task_id"],
                "search_plan": state["search_plan"],
                "allowed_actions": ["approve", "edit_and_approve", "regenerate", "cancel"],
            }
        )
    )
    original = SearchPlan.model_validate(state["search_plan"]).as_payload()
    approved = original
    version = int(state["search_plan_version"])
    if decision.edited_search_plan is not None:
        approved = decision.edited_search_plan.as_payload()
        version += 1
        deps.artifacts.write_json_once(
            "system",
            f"research/search_plan_versions/v{version}.json",
            approved,
        )
    changed_fields = sorted(
        key
        for key in set(original) | set(approved)
        if original.get(key) != approved.get(key)
    )
    decision_payload = decision.as_payload()
    decision_payload["feedback"] = mask_sensitive(decision.feedback)
    decision_id = _payload_hash({
        "task_id": state["task_id"],
        "plan_version": version,
        "decision": decision_payload,
    })[:16]
    record_path = (
        f"research/approvals/search_plan_v{version}_{decision_id}.json"
    )
    record_target = deps.artifacts.resolve(record_path)
    if not record_target.exists():
        approval_record = {
            "schema": "search.approval.v1",
            "task_id": state["task_id"],
            "plan_version": version,
            "action": decision.action,
            "recorded_at": datetime.now().astimezone().isoformat(),
            "prior_sha256": _payload_hash(original),
            "approved_sha256": _payload_hash(approved),
            "changed_fields": changed_fields,
            "feedback": decision_payload["feedback"],
        }
        deps.artifacts.write_json_once("system", record_path, approval_record)
    if decision.action in {"approve", "edit_and_approve"}:
        deps.artifacts.write_json(
            "system",
            "research/search_plan.json",
            approved,
        )
    update = {
        "search_approval": decision_payload,
        "search_plan": approved,
        "search_plan_version": version,
        "search_approval_record_path": record_path,
    }
    return update


def route_search_approval(state: WorkflowState) -> Literal["collect_sources", "analyze_request", "cancelled"]:
    action = ApprovalDecision.model_validate(state["search_approval"]).action
    if action in {"approve", "edit_and_approve"}:
        return "collect_sources"
    if action == "regenerate":
        return "analyze_request"
    return "cancelled"


def collect_sources(state: WorkflowState, deps: WorkflowDependencies) -> dict:
    next_round = int(state.get("research_round", 0)) + 1
    deps.progress("collect_sources", "running", {"research_round": next_round})
    audit = state.get("evidence_audit", {})
    key = make_idempotency_key(
        state["task_id"],
        "collect_sources",
        next_round,
        {
            "search_plan": state["search_plan"],
            "supplementary_queries": audit.get("supplementary_queries", []),
        },
    )
    raw_before = deps.artifacts.snapshot_raw_hashes()
    package = deps.hermes.run_structured_task(
        f"collect_sources_r{next_round}",
        _prompt(
            "hermes_collect_sources.txt",
            {
                "task_id": state["task_id"],
                "research_round": next_round,
                "search_plan": state["search_plan"],
                "supplementary_queries": audit.get("supplementary_queries", []),
            },
        ),
        deps.artifacts.workspace,
        ResearchPackage,
        idempotency_key=key,
        extra_context={"research_round": next_round},
        sandbox="workspace-write",
    )
    deps.artifacts.assert_raw_unchanged(raw_before)
    for source in package.sources:
        if source.local_file:
            ref = deps.artifacts.register_evidence_file(source.local_file)
            if source.sha256 != ref.sha256:
                raise ArtifactViolation(
                    f"source hash mismatch: {source.source_id}"
                )
    path = f"research/research_package_round_{next_round}.json"
    deps.artifacts.write_json("hermes", path, package.as_payload())
    update = {
        "current_node": "collect_sources",
        "research_round": next_round,
        "research_package_path": path,
        "status": "running",
        "retry_counters": {
            "collect_sources": retry_count_for(deps.artifacts.workspace, key)
        },
    }
    deps.progress("collect_sources", "success", update)
    return update


def audit_evidence(state: WorkflowState, deps: WorkflowDependencies) -> dict:
    package = json.loads(
        deps.artifacts.resolve(state["research_package_path"]).read_text(encoding="utf-8")
    )
    deps.progress("audit_evidence", "running", {"research_round": state["research_round"]})
    key = make_idempotency_key(
        state["task_id"],
        "audit_evidence",
        state["research_round"],
        {
            "search_plan": state["search_plan"],
            "research_package_path": state["research_package_path"],
            "research_package_sha256": deps.artifacts.artifact_ref(
                state["research_package_path"],
                "evidence",
            ).sha256,
        },
    )
    audit = deps.codex.run_structured_task(
        f"audit_evidence_r{state['research_round']}",
        _prompt(
            "codex_evidence_audit.txt",
            {"search_plan": state["search_plan"], "research_package": package},
        ),
        deps.artifacts.workspace,
        EvidenceAudit,
        idempotency_key=key,
        sandbox="read-only",
    )
    deps.artifacts.write_json("codex", "review/evidence_audit.json", audit.as_payload())
    update = {
        "current_node": "audit_evidence",
        "evidence_audit": audit.as_payload(),
        "status": "running",
        "retry_counters": {
            "audit_evidence": retry_count_for(deps.artifacts.workspace, key)
        },
    }
    deps.progress("audit_evidence", "success", update)
    return update


def route_evidence(
    state: WorkflowState,
) -> Literal["draft_master_report", "collect_sources", "human_evidence_review"]:
    audit = EvidenceAudit.model_validate(state["evidence_audit"])
    if audit.status == "sufficient":
        return "draft_master_report"
    if audit.status == "insufficient" and int(state.get("research_round", 0)) < 2:
        return "collect_sources"
    return "human_evidence_review"


def human_evidence_review(state: WorkflowState) -> dict:
    resolution = HumanResolution.model_validate(
        interrupt(
            {
                "kind": "evidence_blocker",
                "task_id": state["task_id"],
                "audit": state["evidence_audit"],
                "allowed_actions": ["continue_with_limitations", "cancel"],
            }
        )
    )
    return {"human_action": resolution.as_payload()}


def route_human_evidence(
    state: WorkflowState,
) -> Literal["draft_master_report", "cancelled"]:
    action = HumanResolution.model_validate(state["human_action"]).action
    if action == "continue_with_limitations":
        return "draft_master_report"
    return "cancelled"
```

Every research and approval node must append exactly one sanitized event through
the additive `audit_events` state field. Record node, fixed actor, outcome,
schema version, round, retry count, idempotency key, artifact relative
paths/hashes, and approval action; do not record prompts, credentials, cookies,
raw documents, or free-form secrets. Report nodes in Task 5 follow the same
rule.

- [ ] **Step 6: Run tests**

```powershell
python -m pytest backend/tests/test_research_nodes.py backend/tests/test_structured_agent_adapters.py -v
```

Expected: all selected tests pass and adapter call counts prove the fixed mapping.

- [ ] **Step 7: Commit**

```powershell
git add backend/workflows backend/prompts backend/tests/test_research_nodes.py
git commit -m "feat: add fixed research workflow nodes"
```

---

### Task 5: Build the Canonical Report, Derived DOCX/PPTX, QA, and Finalization

**Files:**
- Create: `ai-report-ppt-controller/backend/workflows/report_nodes.py`
- Create: `ai-report-ppt-controller/backend/prompts/codex_master_report.txt`
- Create: `ai-report-ppt-controller/backend/prompts/codex_quality_check.txt`
- Create: `ai-report-ppt-controller/backend/tests/test_report_nodes.py`

**Interfaces:**
- Consumes: validated `ResearchPackage`, `EvidenceAudit`, and `MasterReport`
- Produces: `draft/master_report.md`, `draft/source_register.json`, `draft/citation_index.json`, `output/draft/final_report.docx`, `output/draft/final_presentation.pptx`, `draft/report_manifest.json`, `review/quality_decision.json`, `review/workflow_audit.json`, and final approved files

- [ ] **Step 1: Write failing canonical-source tests**

```python
from __future__ import annotations

import json
from pathlib import Path

from backend.models.workflow import MasterReport, QualityDecision, ReportManifest
from backend.workflows.dependencies import WorkflowDependencies
from backend.workflows.report_nodes import build_ppt, build_word, draft_master_report, finalize


class StubAdapter:
    def __init__(self, results):
        self.results = iter(results)

    def run_structured_task(self, *args, **kwargs):
        return next(self.results)


def sample_report() -> MasterReport:
    return MasterReport(
        title="GaN report",
        executive_summary=[
            {"text": "Finding", "evidence_ids": ["EV-001"], "claim_type": "fact"}
        ],
        sections=[
            {
                "section_id": "section-001",
                "title": "Evidence",
                "conclusion": {
                    "text": "Conclusion",
                    "evidence_ids": ["EV-001"],
                    "claim_type": "fact",
                },
                "claims": [
                    {"text": "Claim", "evidence_ids": ["EV-001"], "claim_type": "fact"}
                ],
            }
        ],
        limitations=[],
        recommendations=[],
    )


def test_markdown_contains_evidence_ids(tmp_path: Path) -> None:
    package_path = tmp_path / "research" / "research_package_round_1.json"
    package_path.parent.mkdir(parents=True)
    package_path.write_text(
        json.dumps(
            {
                "schema": "research.package.v1",
                "task_id": "t1",
                "research_round": 1,
                "queries": [],
                "sources": [
                    {
                        "source_id": "SRC-001",
                        "title": "Source",
                        "source_type": "paper",
                        "retrieved_at": "2026-07-30T12:00:00+08:00",
                        "parse_status": "success",
                    }
                ],
                "evidence": [
                    {
                        "evidence_id": "EV-001",
                        "source_id": "SRC-001",
                        "claim_supported": "Finding",
                        "verification_status": "primary_source_verified",
                    }
                ],
                "coverage_gaps": [],
                "failed_items": [],
                "created_at": "2026-07-30T12:00:00+08:00",
            }
        ),
        encoding="utf-8",
    )
    deps = WorkflowDependencies.for_test(
        tmp_path,
        codex=StubAdapter([sample_report()]),
        hermes=StubAdapter([]),
    )
    update = draft_master_report(
        {
            "task_id": "t1",
            "request": {"task_type": "ppt_word"},
            "research_package_path": "research/research_package_round_1.json",
            "evidence_audit": {
                "schema": "evidence.audit.v1",
                "status": "sufficient",
                "coverage": [],
                "source_quality_issues": [],
                "conflicts": [],
                "missing_items": [],
                "supplementary_queries": [],
                "blocking_reasons": [],
            },
        },
        deps,
    )
    markdown = (tmp_path / "draft" / "master_report.md").read_text(encoding="utf-8")
    assert "[EV-001]" in markdown
    assert update["current_node"] == "draft_master_report"


def test_docx_and_pptx_are_derived_from_same_markdown_master(tmp_path: Path) -> None:
    report_path = tmp_path / "draft" / "master_report.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        "# GaN report\n\n## 执行摘要\n\n- Finding [EV-001]\n",
        encoding="utf-8",
    )
    deps = WorkflowDependencies.for_test(tmp_path, codex=StubAdapter([]), hermes=StubAdapter([]))
    word_update = build_word(
        {
            "request": {"task_type": "ppt_word"},
            "master_report_path": "draft/master_report.md",
        },
        deps,
    )
    ppt_update = build_ppt(
        {
            "request": {"task_type": "ppt_word"},
            "master_report_path": "draft/master_report.md",
            "report_manifest": word_update["report_manifest"],
        },
        deps,
    )
    manifest = ppt_update["report_manifest"]
    assert manifest["word"]["relative_path"].endswith(".docx")
    assert manifest["powerpoint"]["relative_path"].endswith(".pptx")


def test_finalize_copies_only_approved_artifacts(tmp_path: Path) -> None:
    draft = tmp_path / "output" / "draft" / "final_report.docx"
    draft.parent.mkdir(parents=True)
    draft.write_bytes(b"word")
    deps = WorkflowDependencies.for_test(tmp_path, codex=StubAdapter([]), hermes=StubAdapter([]))
    supporting_paths = [
        "draft/master_report.md",
        "draft/source_register.json",
        "draft/citation_index.json",
        "review/evidence_audit.json",
    ]
    for relative_path in supporting_paths:
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}\n", encoding="utf-8")
    manifest = ReportManifest(
        master_report=deps.artifacts.artifact_ref("draft/master_report.md", "draft"),
        word=deps.artifacts.artifact_ref("output/draft/final_report.docx", "draft"),
        powerpoint=None,
        source_register=deps.artifacts.artifact_ref("draft/source_register.json", "draft"),
        citation_index=deps.artifacts.artifact_ref("draft/citation_index.json", "draft"),
        evidence_audit=deps.artifacts.artifact_ref("review/evidence_audit.json", "draft"),
        generated_at="2026-07-30T12:00:00+08:00",
        version=1,
    )
    update = finalize(
        {
            "export_approval": {"action": "approve_word_only", "feedback": ""},
            "report_manifest": manifest.as_payload(),
            "audit_events": [],
        },
        deps,
    )
    assert update["status"] == "done"
    assert (tmp_path / "output" / "final" / "final_report.docx").exists()
    assert not (tmp_path / "output" / "final" / "final_presentation.pptx").exists()
    assert (tmp_path / "output" / "final" / "workflow_audit.json").exists()
```

- [ ] **Step 2: Verify tests fail**

```powershell
python -m pytest backend/tests/test_report_nodes.py -v
```

Expected: import failure for `backend.workflows.report_nodes`.

- [ ] **Step 3: Add report and QA prompts**

`backend/prompts/codex_master_report.txt`:

```text
You are the fixed Codex report node. Produce only the MasterReport structure required by the schema.
Use the supplied evidence package and audit. Every factual claim must list one or more existing evidence_ids.
Mark unsupported interpretation as analysis, assumption, or pending. Keep one conclusion per section and include limitations.
Do not add sources, change raw evidence, or control the workflow.
```

`backend/prompts/codex_quality_check.txt`:

```text
You are the fixed Codex quality node. Review the canonical Markdown master report, citation index, and derived artifact metadata.
Return only the QualityDecision structure. Fail the review when a factual claim lacks evidence, an evidence_id is unknown, a requested artifact is missing, or Word and PPT do not derive from the same report version.
Give every blocking issue a location, evidence, and executable revision instruction.
```

- [ ] **Step 4: Implement deterministic rendering and builders**

In `backend/workflows/report_nodes.py`, implement these exact public functions:

```python
def render_markdown(report: MasterReport) -> str
def render_citation_index(report: MasterReport, package: ResearchPackage) -> dict
def parse_master_markdown(markdown: str) -> list[MarkdownSection]
def write_word(markdown: str, target: Path) -> None
def write_powerpoint(markdown: str, target: Path) -> None
def deterministic_quality_issues(report: MasterReport, package: ResearchPackage) -> list[QualityIssue]
def quality_issue_fingerprint(decision: QualityDecision) -> str
```

Use this rendering rule:

```python
def _claim_line(claim: ReportClaim) -> str:
    citations = " ".join(f"[{evidence_id}]" for evidence_id in claim.evidence_ids)
    label = "" if claim.claim_type == "fact" else f" ({claim.claim_type})"
    return f"- {claim.text}{label} {citations}".rstrip()


def _conclusion_line(claim: ReportClaim) -> str:
    citations = " ".join(f"[{evidence_id}]" for evidence_id in claim.evidence_ids)
    label = "" if claim.claim_type == "fact" else f" ({claim.claim_type})"
    return f"**结论：** {claim.text}{label} {citations}".rstrip()


def render_markdown(report: MasterReport) -> str:
    lines = [f"# {report.title}", "", "## 执行摘要", ""]
    lines.extend(_claim_line(claim) for claim in report.executive_summary)
    for section in report.sections:
        lines.extend([
            "",
            f"## {section.title}",
            "",
            _conclusion_line(section.conclusion),
            "",
        ])
        lines.extend(_claim_line(claim) for claim in section.claims)
    if report.limitations:
        lines.extend(["", "## 局限性", ""])
        lines.extend(f"- {item}" for item in report.limitations)
    if report.recommendations:
        lines.extend(["", "## 建议", ""])
        lines.extend(_claim_line(claim) for claim in report.recommendations)
    return "\n".join(lines).rstrip() + "\n"
```

Define `MarkdownSection` as a small dataclass containing `level`, `title`, and
`body_lines`. `parse_master_markdown` must recognize `#`/`##` headings and
preserve all non-heading lines in order. The Word builder creates headings and
paragraphs from the parsed Markdown; the PowerPoint builder creates a cover,
one executive-summary slide, one slide per level-two section, and a final
limitations/recommendations slide when those sections exist. Both builders
receive the exact text read from `master_report_path`; neither may load
`report_outline.json` or synthesize new prose.

- [ ] **Step 5: Implement report workflow nodes**

Add:

```python
def draft_master_report(state: WorkflowState, deps: WorkflowDependencies) -> dict
def build_word(state: WorkflowState, deps: WorkflowDependencies) -> dict
def build_ppt(state: WorkflowState, deps: WorkflowDependencies) -> dict
def quality_check(state: WorkflowState, deps: WorkflowDependencies) -> dict
def route_quality(state: WorkflowState) -> Literal["approve_export", "revise_outputs", "human_quality_review"]
def revise_outputs(state: WorkflowState, deps: WorkflowDependencies) -> dict
def human_quality_review(state: WorkflowState) -> dict
def route_human_quality(state: WorkflowState) -> Literal["revise_outputs", "approve_export", "cancelled"]
def approve_export(state: WorkflowState, deps: WorkflowDependencies) -> dict
def route_export(state: WorkflowState) -> Literal["finalize", "revise_outputs", "cancelled"]
def finalize(state: WorkflowState, deps: WorkflowDependencies) -> dict
def cancelled(state: WorkflowState) -> dict
```

Apply these routing rules exactly:

```python
def route_quality(state: WorkflowState) -> str:
    decision = QualityDecision.model_validate(state["qa_result"])
    if decision.passed:
        return "approve_export"
    current_fingerprint = state.get("quality_issue_history", [""])[-1]
    repeated = state.get("quality_issue_history", []).count(current_fingerprint) >= 2
    if int(state.get("revision_round", 0)) < 2 and not repeated:
        return "revise_outputs"
    return "human_quality_review"


def route_export(state: WorkflowState) -> str:
    action = ExportDecision.model_validate(state["export_approval"]).action
    if action in {"approve_all", "approve_word_only", "approve_ppt_only"}:
        return "finalize"
    if action == "request_revision":
        return "revise_outputs"
    return "cancelled"
```

`draft_master_report` also derives `draft/source_register.json` directly from
the selected `ResearchPackage.sources` and `draft/citation_index.json` from
`render_citation_index`. Store references to both files and
`review/evidence_audit.json` in `ReportManifest`.

`quality_check` must merge deterministic issues with Codex issues and force
`pass=false` when deterministic issues exist. It must append the SHA-256 of the
sorted blocking issue type, location, and revision instruction tuples to
`quality_issue_history`; `route_quality` sends the second occurrence of the
same fingerprint to human review even when the numeric revision limit has not
otherwise been reached. `finalize` must first write
`review/workflow_audit.json` from the sanitized additive `audit_events` plus
the finalization event it is about to return, so both the export approval and
successful finalization appear exactly once. For
every successful export, always copy the Markdown master, source register,
citation index, evidence audit, and workflow audit as mandatory supporting
files; add DOCX and/or PPTX according to the selected export action. Then write
`output/final/final_manifest.json` with separate `supporting_files` and
`approved_deliverables` arrays. The export interrupt must display both groups
before approval, and `finalize` must never copy an unlisted file.
For `research_only` and `outline_only`, classify the Markdown master under
`approved_deliverables` and the remaining four JSON audit/evidence files under
`supporting_files`; do not duplicate the Markdown entry.

`draft_master_report` must write the model payload as the non-authoritative
`draft/report_outline.json`, render and write the authoritative
`draft/master_report.md`, then return
`{"master_report_path": "draft/master_report.md", "current_node": "draft_master_report"}`.
It also writes immutable snapshots
`draft/versions/report_outline_v1.json` and
`draft/versions/master_report_v1.md` using `write_json_once` and
`write_text_once`. Each `revise_outputs` call increments the
manifest version, writes matching versioned snapshots before replacing the
current aliases, and records the prior/new Markdown hashes in its audit event.
`build_word` and `build_ppt` must each read only that Markdown file and pass its
identical string to `write_word` or `write_powerpoint`. Each node updates the
same `ReportManifest` without discarding the preceding node's artifact
reference. Each node records the SHA-256 of its exact input string in
`word_source_sha256` or `powerpoint_source_sha256`;
`deterministic_quality_issues` fails any non-empty source hash that differs from
`ReportManifest.master_report.sha256`. The outline JSON supports validation and
targeted revision, but it is never an input to DOCX or PPTX generation. Add a
test that changes a line in `master_report.md` after outline creation and proves
both generated artifacts contain the changed line and record the new Markdown
hash.

For `task_type="ppt"`, `build_word` creates the manifest and supporting
references but leaves `word=None`; for `task_type="word"`, `build_ppt` preserves
the manifest and leaves `powerpoint=None`; `task_type="ppt_word"` runs both
builders. For `research_only` and `outline_only`, both build nodes are recorded
as successful no-ops and the canonical Markdown is the only deliverable;
`draft_master_report` tells Codex to produce an evidence research brief or an
outline respectively. Both graph nodes always complete so the fixed graph shape
never changes by task type. Reject `approve_word_only` or `approve_ppt_only`
with HTTP 409 when that artifact is absent from the manifest.

Every Codex call in `draft_master_report`, `quality_check`, and
`revise_outputs` must use `make_idempotency_key`. Hash the research package and
evidence audit for drafting, the Markdown plus manifest for quality review, and
the Markdown plus quality decision plus revision round for revision. A
human-requested revision increments the existing counter and records a new
approval event; it never resets automatic round or retry counters.
Before storing `HumanResolution.feedback` or `ExportDecision.feedback` in graph
state or approval artifacts, pass it through `mask_sensitive`.
`approve_export` derives a deterministic decision ID from task ID, manifest
version, artifact hashes, action, and masked feedback, then uses
`write_json_once` for
`review/approvals/export_<decision_id>.json`. The record contains those fields
plus its first-write time; a replay loads the existing record instead of
creating a duplicate. Return its relative path as
`export_approval_record_path`.

- [ ] **Step 6: Run focused tests**

```powershell
python -m pytest backend/tests/test_report_nodes.py backend/tests/test_workflow_artifacts.py -v
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

```powershell
git add backend/workflows/report_nodes.py backend/prompts backend/tests/test_report_nodes.py
git commit -m "feat: build reports from one canonical source"
```

---

### Task 6: Assemble the Stable Graph and SQLite Runtime

**Files:**
- Create: `ai-report-ppt-controller/backend/workflows/graph.py`
- Create: `ai-report-ppt-controller/backend/workflows/runtime.py`
- Modify: `ai-report-ppt-controller/backend/config.py`
- Create: `ai-report-ppt-controller/backend/tests/test_workflow_graph.py`
- Create: `ai-report-ppt-controller/backend/tests/test_workflow_resume.py`

**Interfaces:**
- Consumes: `WorkflowDependencies`, task ID, initial request, or resume payload
- Produces: `build_workflow_graph(deps, checkpointer)`, `WorkflowRuntime.start`, `resume`, `snapshot`

- [ ] **Step 1: Write failing graph-shape and recovery tests**

```python
from __future__ import annotations

from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from backend.workflows.dependencies import WorkflowDependencies
from backend.workflows.graph import FIXED_NODE_EXECUTORS, build_workflow_graph


class NoCallAdapter:
    def run_structured_task(self, *args, **kwargs):
        raise AssertionError("graph compilation must not call an agent")


def test_fixed_node_executor_map() -> None:
    assert FIXED_NODE_EXECUTORS == {
        "initialize_task": "system",
        "analyze_request": "codex",
        "approve_search_plan": "human",
        "collect_sources": "hermes",
        "audit_evidence": "codex",
        "human_evidence_review": "human",
        "draft_master_report": "codex",
        "build_word": "codex_tools",
        "build_ppt": "codex_tools",
        "quality_check": "codex",
        "revise_outputs": "codex",
        "human_quality_review": "human",
        "approve_export": "human",
        "finalize": "system",
        "cancelled": "system",
    }


def test_graph_compiles_with_checkpointer(tmp_path: Path) -> None:
    adapter = NoCallAdapter()
    deps = WorkflowDependencies.for_test(
        tmp_path,
        codex=adapter,
        hermes=adapter,
    )
    graph = build_workflow_graph(deps, InMemorySaver())
    assert graph is not None
```

In `test_workflow_resume.py`, define the deterministic adapter and runtime factory in
the same file so the test has no hidden fixture dependency:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from backend.models.workflow import (
    EvidenceAudit,
    MasterReport,
    QualityDecision,
    ResearchPackage,
    SearchPlan,
)
from backend.workflows.dependencies import WorkflowDependencies
from backend.workflows.execution import AgentExecutionError
from backend.workflows.graph import build_workflow_graph
from backend.workflows.runtime import WorkflowRuntime, create_sqlite_saver


class DeterministicAdapter:
    def run_structured_task(
        self,
        task_name,
        prompt,
        workspace,
        output_model,
        *,
        idempotency_key,
        extra_context=None,
        sandbox="read-only",
    ):
        payloads = {
            SearchPlan: {
                "schema": "search.plan.v1",
                "task_understanding": "GaN public-source review",
                "queries": [],
                "success_criteria": ["one traceable primary source"],
            },
            ResearchPackage: {
                "schema": "research.package.v1",
                "task_id": "task-1",
                "research_round": 1,
                "queries": [],
                "sources": [{
                    "source_id": "SRC-001",
                    "title": "Primary source",
                    "source_type": "paper",
                    "retrieved_at": "2026-07-30T12:00:00+08:00",
                    "parse_status": "success",
                }],
                "evidence": [{
                    "evidence_id": "EV-001",
                    "source_id": "SRC-001",
                    "claim_supported": "GaN finding",
                    "verification_status": "primary_source_verified",
                }],
                "created_at": "2026-07-30T12:00:00+08:00",
            },
            EvidenceAudit: {
                "schema": "evidence.audit.v1",
                "status": "sufficient",
            },
            MasterReport: {
                "schema": "master.report.v1",
                "title": "GaN report",
                "executive_summary": [{
                    "text": "GaN finding",
                    "evidence_ids": ["EV-001"],
                    "claim_type": "fact",
                }],
            },
            QualityDecision: {
                "schema": "quality.decision.v1",
                "pass": True,
                "citation_coverage": "complete",
                "word_ppt_consistency": "consistent",
                "artifact_validation": "passed",
            },
        }
        return output_model.model_validate(payloads[output_model])


def make_test_runtime(root: Path) -> WorkflowRuntime:
    adapter = DeterministicAdapter()
    deps = WorkflowDependencies.for_test(root, codex=adapter, hermes=adapter)
    saver = create_sqlite_saver(root / "checkpoints.sqlite3")
    graph = build_workflow_graph(deps, saver)
    return WorkflowRuntime(graph, lambda snapshot: None)


def test_search_approval_interrupt_survives_runtime_recreation(tmp_path: Path) -> None:
    runtime = make_test_runtime(tmp_path)
    runtime.start("task-1", {"title": "GaN", "task_type": "ppt_word"})
    first = runtime.snapshot("task-1")
    assert first.pending["kind"] == "search_plan"
    repeated = runtime.start("task-1", {"title": "GaN", "task_type": "ppt_word"})
    assert repeated.pending["kind"] == "search_plan"
    with pytest.raises(ValueError):
        runtime.start("task-1", {"title": "SiC", "task_type": "ppt_word"})

    recreated = make_test_runtime(tmp_path)
    recreated.resume("task-1", {"action": "approve", "feedback": ""})
    second = recreated.snapshot("task-1")
    assert second.state["research_round"] == 1
    assert second.pending["kind"] == "export"


def test_exhausted_agent_failure_is_recorded_in_checkpoint(tmp_path: Path) -> None:
    class FailingAdapter:
        def run_structured_task(self, *args, **kwargs):
            raise AgentExecutionError("transient", 3, "agent timeout")

    deps = WorkflowDependencies.for_test(
        tmp_path,
        codex=FailingAdapter(),
        hermes=DeterministicAdapter(),
    )
    runtime = WorkflowRuntime(
        build_workflow_graph(
            deps,
            create_sqlite_saver(tmp_path / "failure.sqlite3"),
        ),
        lambda snapshot: None,
    )
    result = runtime.start("task-failure", {"title": "GaN", "task_type": "ppt_word"})
    assert result.state["status"] == "failed"
    assert result.state["errors"][-1]["category"] == "transient"
    assert result.state["retry_counters"]["analyze_request"] == 2
```

- [ ] **Step 2: Verify tests fail**

```powershell
python -m pytest backend/tests/test_workflow_graph.py backend/tests/test_workflow_resume.py -v
```

Expected: missing graph/runtime modules.

- [ ] **Step 3: Assemble graph with stable node names**

Create `backend/workflows/graph.py`:

```python
from functools import partial

from langgraph.graph import END, START, StateGraph

from backend.models.workflow import WorkflowState
from backend.workflows.research_nodes import (
    analyze_request,
    approve_search_plan,
    audit_evidence,
    collect_sources,
    human_evidence_review,
    initialize_task,
    route_evidence,
    route_human_evidence,
    route_search_approval,
)
from backend.workflows.report_nodes import (
    approve_export,
    build_ppt,
    build_word,
    cancelled,
    draft_master_report,
    finalize,
    human_quality_review,
    quality_check,
    revise_outputs,
    route_export,
    route_human_quality,
    route_quality,
)


FIXED_NODE_EXECUTORS = {
    "initialize_task": "system",
    "analyze_request": "codex",
    "approve_search_plan": "human",
    "collect_sources": "hermes",
    "audit_evidence": "codex",
    "human_evidence_review": "human",
    "draft_master_report": "codex",
    "build_word": "codex_tools",
    "build_ppt": "codex_tools",
    "quality_check": "codex",
    "revise_outputs": "codex",
    "human_quality_review": "human",
    "approve_export": "human",
    "finalize": "system",
    "cancelled": "system",
}


def build_workflow_graph(deps, checkpointer):
    builder = StateGraph(WorkflowState)
    builder.add_node("initialize_task", partial(initialize_task, deps=deps))
    builder.add_node("analyze_request", partial(analyze_request, deps=deps))
    builder.add_node("approve_search_plan", partial(approve_search_plan, deps=deps))
    builder.add_node("collect_sources", partial(collect_sources, deps=deps))
    builder.add_node("audit_evidence", partial(audit_evidence, deps=deps))
    builder.add_node("human_evidence_review", human_evidence_review)
    builder.add_node("draft_master_report", partial(draft_master_report, deps=deps))
    builder.add_node("build_word", partial(build_word, deps=deps))
    builder.add_node("build_ppt", partial(build_ppt, deps=deps))
    builder.add_node("quality_check", partial(quality_check, deps=deps))
    builder.add_node("revise_outputs", partial(revise_outputs, deps=deps))
    builder.add_node("human_quality_review", human_quality_review)
    builder.add_node("approve_export", partial(approve_export, deps=deps))
    builder.add_node("finalize", partial(finalize, deps=deps))
    builder.add_node("cancelled", cancelled)

    builder.add_edge(START, "initialize_task")
    builder.add_edge("initialize_task", "analyze_request")
    builder.add_edge("analyze_request", "approve_search_plan")
    builder.add_conditional_edges("approve_search_plan", route_search_approval)
    builder.add_edge("collect_sources", "audit_evidence")
    builder.add_conditional_edges("audit_evidence", route_evidence)
    builder.add_conditional_edges("human_evidence_review", route_human_evidence)
    builder.add_edge("draft_master_report", "build_word")
    builder.add_edge("build_word", "build_ppt")
    builder.add_edge("build_ppt", "quality_check")
    builder.add_conditional_edges("quality_check", route_quality)
    builder.add_edge("revise_outputs", "build_word")
    builder.add_conditional_edges("human_quality_review", route_human_quality)
    builder.add_conditional_edges("approve_export", route_export)
    builder.add_edge("finalize", END)
    builder.add_edge("cancelled", END)
    return builder.compile(checkpointer=checkpointer)
```

Do not rename these nodes after tasks have begun; paused checkpoints store node names.

- [ ] **Step 4: Add SQLite path configuration**

Add to `backend/config.py`:

```python
checkpoint_db_path: str = Field(
    default_factory=lambda: os.getenv(
        "LANGGRAPH_CHECKPOINT_DB",
        str(STORAGE_DIR / "workflow_checkpoints.sqlite3"),
    )
)
max_research_rounds: int = Field(default=2, ge=1, le=2)
max_revision_rounds: int = Field(default=2, ge=1, le=2)
```

- [ ] **Step 5: Implement runtime start, resume, and snapshot**

Create `backend/workflows/runtime.py` around one shared `SqliteSaver` connection:

```python
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Callable

os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from backend.models.workflow import WorkflowError
from backend.services.security import mask_sensitive
from backend.workflows.artifacts import ArtifactViolation
from backend.workflows.execution import AgentExecutionError


@dataclass
class WorkflowSnapshot:
    state: dict[str, Any]
    next_nodes: tuple[str, ...]
    pending: dict[str, Any] | None


class WorkflowRuntime:
    def __init__(self, graph, projector: Callable[[WorkflowSnapshot], None]):
        self.graph = graph
        self.projector = projector
        self._lock = RLock()

    @staticmethod
    def config(task_id: str) -> dict:
        return {"configurable": {"thread_id": task_id}}

    def _snapshot(self, task_id: str) -> WorkflowSnapshot:
        snapshot = self.graph.get_state(self.config(task_id))
        pending = None
        for task in snapshot.tasks:
            if task.interrupts:
                pending = task.interrupts[0].value
                break
        return WorkflowSnapshot(
            state=dict(snapshot.values),
            next_nodes=tuple(snapshot.next),
            pending=pending,
        )

    def _drive(self, task_id: str, value: dict | Command) -> WorkflowSnapshot:
        try:
            for _ in self.graph.stream(value, self.config(task_id), stream_mode="values"):
                self.projector(self._snapshot(task_id))
        except Exception as exc:
            before = self._snapshot(task_id)
            node = before.next_nodes[0] if before.next_nodes else "runtime"
            if isinstance(exc, AgentExecutionError):
                category = exc.category
                attempts = exc.attempts
            elif isinstance(exc, ArtifactViolation):
                category = "security"
                attempts = 1
            else:
                category = "fatal"
                attempts = 1
            counters = dict(before.state.get("retry_counters", {}))
            counters[node] = max(int(counters.get(node, 0)), attempts - 1)
            message = mask_sensitive(str(exc))[:1000]
            error = WorkflowError(
                node=node,
                category=category,
                message=message,
                retryable=False,
                attempt=attempts,
            )
            self.graph.update_state(
                self.config(task_id),
                {
                    "status": "failed",
                    "retry_counters": counters,
                    "errors": [error.as_payload()],
                    "audit_events": [{
                        "at": datetime.now().astimezone().isoformat(),
                        "node": node,
                        "actor": "system",
                        "status": "failed",
                        "round": 0,
                        "decision": category,
                        "schema_version": "workflow.audit.v1",
                        "retry_count": attempts - 1,
                        "idempotency_key": "",
                        "artifacts": [],
                    }],
                },
            )
        result = self._snapshot(task_id)
        self.projector(result)
        return result

    def start(self, task_id: str, request: dict[str, Any]) -> WorkflowSnapshot:
        with self._lock:
            existing = self._snapshot(task_id)
            if existing.state:
                if existing.state.get("request") != request:
                    raise ValueError(
                        f"task {task_id} already exists with a different request"
                    )
                return existing
            return self._drive(
                task_id,
                {"task_id": task_id, "request": request, "status": "running"},
            )

    def resume(self, task_id: str, payload: dict[str, Any]) -> WorkflowSnapshot:
        with self._lock:
            if self._snapshot(task_id).pending is None:
                raise ValueError(f"task {task_id} has no pending interrupt")
            return self._drive(task_id, Command(resume=payload))

    def snapshot(self, task_id: str) -> WorkflowSnapshot:
        return self._snapshot(task_id)


def create_sqlite_saver(path: Path) -> SqliteSaver:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), check_same_thread=False)
    return SqliteSaver(connection)
```

- [ ] **Step 6: Run graph and recovery tests**

```powershell
python -m pytest backend/tests/test_workflow_graph.py backend/tests/test_workflow_resume.py -v
```

Expected: graph compiles, pauses at search approval, resumes with the same
SQLite checkpoint after runtime recreation, and stores exhausted failures as
sanitized structured state without deleting prior artifacts.

- [ ] **Step 7: Commit**

```powershell
git add backend/workflows/graph.py backend/workflows/runtime.py backend/config.py backend/tests/test_workflow_graph.py backend/tests/test_workflow_resume.py
git commit -m "feat: add durable fixed LangGraph runtime"
```

---

### Task 7: Project Graph State into Existing Task Records

**Files:**
- Modify: `ai-report-ppt-controller/backend/models/task.py`
- Modify: `ai-report-ppt-controller/backend/services/task_runner.py`
- Create: `ai-report-ppt-controller/backend/services/workflow_projection.py`
- Modify: `ai-report-ppt-controller/backend/tests/test_task_history.py`
- Create: `ai-report-ppt-controller/backend/tests/test_workflow_projection.py`

**Interfaces:**
- Consumes: `WorkflowSnapshot`
- Produces: backward-compatible `TaskRecord`, fixed visible steps, `run_workflow`, `resume_workflow`, `workflow_snapshot`

- [ ] **Step 1: Write failing projection tests**

```python
from backend.models.task import TaskRecord, TaskRequest, default_steps
from backend.services.workflow_projection import project_snapshot
from backend.workflows.runtime import WorkflowSnapshot


def test_default_steps_show_fixed_assignments() -> None:
    pairs = [(step.step_name, step.agent) for step in default_steps()]
    assert ("ANALYZE_REQUEST", "codex") in pairs
    assert ("COLLECT_SOURCES", "hermes") in pairs
    assert ("APPROVE_SEARCH_PLAN", "human") in pairs


def test_pending_interrupt_projects_waiting_approval(tmp_path, monkeypatch) -> None:
    record = TaskRecord(
        task_id="t1",
        request=TaskRequest(title="GaN", task_id="t1"),
        steps=default_steps(),
    )
    snapshot = WorkflowSnapshot(
        state={"task_id": "t1", "current_node": "analyze_request", "research_round": 0},
        next_nodes=("approve_search_plan",),
        pending={"kind": "search_plan", "search_plan": {}},
    )
    projected = project_snapshot(record, snapshot)
    assert projected.status == "waiting_approval"
    assert projected.pending_interrupt["kind"] == "search_plan"
```

- [ ] **Step 2: Verify tests fail**

```powershell
python -m pytest backend/tests/test_workflow_projection.py -v
```

Expected: import or enum failures.

- [ ] **Step 3: Replace visible workflow steps**

Extend `StepStatus` with `"waiting_approval"` and replace `WORKFLOW_STEPS`:

```python
WORKFLOW_STEPS = [
    ("INITIALIZE_TASK", "system"),
    ("ANALYZE_REQUEST", "codex"),
    ("APPROVE_SEARCH_PLAN", "human"),
    ("COLLECT_SOURCES", "hermes"),
    ("AUDIT_EVIDENCE", "codex"),
    ("DRAFT_MASTER_REPORT", "codex"),
    ("BUILD_WORD", "codex_tools"),
    ("BUILD_PPT", "codex_tools"),
    ("QUALITY_CHECK", "codex"),
    ("APPROVE_EXPORT", "human"),
    ("FINALIZE", "system"),
]
```

Add to `TaskRecord`:

```python
current_node: str = ""
pending_interrupt: dict[str, Any] = Field(default_factory=dict)
search_plan_version: int = 0
research_round: int = 0
revision_round: int = 0
workflow_schema_version: str = "workflow.state.v1"
```

- [ ] **Step 4: Implement projection**

Create `backend/services/workflow_projection.py`:

```python
NODE_TO_STEP = {
    "initialize_task": 1,
    "analyze_request": 2,
    "approve_search_plan": 3,
    "collect_sources": 4,
    "audit_evidence": 5,
    "human_evidence_review": 5,
    "draft_master_report": 6,
    "build_word": 7,
    "build_ppt": 8,
    "quality_check": 9,
    "revise_outputs": 9,
    "human_quality_review": 9,
    "approve_export": 10,
    "finalize": 11,
    "cancelled": 11,
}


def project_snapshot(record: TaskRecord, snapshot: WorkflowSnapshot) -> TaskRecord:
    state = snapshot.state
    current = str(state.get("current_node") or "")
    record.current_node = current
    record.pending_interrupt = snapshot.pending or {}
    record.search_plan_version = int(state.get("search_plan_version", 0))
    record.research_round = int(state.get("research_round", 0))
    record.revision_round = int(state.get("revision_round", 0))
    record.workspace_dir = record.workspace_dir

    current_index = NODE_TO_STEP.get(current, 1)
    for step in record.steps:
        if step.index < current_index and step.status in {"waiting", "running"}:
            step.status = "success"
        elif step.index == current_index and step.status == "waiting":
            step.status = "running"

    if snapshot.pending:
        record.status = "waiting_approval"
        pending_kind = snapshot.pending.get("kind")
        pending_node = {
            "search_plan": "approve_search_plan",
            "evidence_blocker": "human_evidence_review",
            "quality_blocker": "human_quality_review",
            "export": "approve_export",
        }.get(pending_kind, current)
        pending_index = NODE_TO_STEP.get(pending_node)
        if pending_index:
            record.steps[pending_index - 1].status = "waiting_approval"
    elif state.get("status") == "done":
        record.status = "done"
        record.steps[-1].status = "done"
    elif state.get("status") in {"cancelled", "cancelled_draft"}:
        record.status = "cancelled"
    elif state.get("status") == "failed":
        record.status = "failed"
    else:
        record.status = "running"
    return record
```

- [ ] **Step 5: Replace only the orchestration entry points in task_runner**

Keep workspace creation, task CRUD, file listing, and history functions. Replace `run_workflow` internals with:

```python
def run_workflow(task_id: str) -> TaskRecord:
    record = load_record(task_id)
    runtime = get_workflow_runtime(task_id)
    runtime.start(task_id, record.request.model_dump(mode="json"))
    return load_record(task_id)


def resume_workflow(task_id: str, payload: dict[str, Any]) -> TaskRecord:
    runtime = get_workflow_runtime(task_id)
    runtime.resume(task_id, payload)
    return load_record(task_id)


def workflow_snapshot(task_id: str) -> dict[str, Any]:
    snapshot = get_workflow_runtime(task_id).snapshot(task_id)
    return {
        "state": snapshot.state,
        "next_nodes": list(snapshot.next_nodes),
        "pending": snapshot.pending,
    }
```

Wrap runtime construction, start, and resume in
`except sqlite3.DatabaseError`. In that branch, load the existing
`TaskRecord`, set its status and current step to `failed`, store only
`mask_sensitive(str(exc))[:1000]` in the step error, and save the record without
deleting or rewriting any workspace artifact. Add a test that supplies an
invalid checkpoint file, observes a failed task record, and verifies a
pre-existing evidence file keeps the same SHA-256.

Construct the cached runtime and shared SQLite saver explicitly:

```python
from functools import lru_cache

from backend.config import get_settings
from backend.services.agent_adapters import make_codex_adapter, make_hermes_adapter
from backend.services.workflow_projection import project_snapshot
from backend.workflows.dependencies import WorkflowDependencies
from backend.workflows.graph import build_workflow_graph
from backend.workflows.runtime import WorkflowRuntime, create_sqlite_saver


@lru_cache(maxsize=1)
def get_checkpoint_saver():
    path = Path(get_settings().checkpoint_db_path)
    return create_sqlite_saver(path)


@lru_cache(maxsize=32)
def get_workflow_runtime(task_id: str) -> WorkflowRuntime:
    workspace = task_dir(task_id)

    def projector(snapshot) -> None:
        record = load_record(task_id)
        save_record(project_snapshot(record, snapshot))

    deps = WorkflowDependencies.for_test(
        workspace,
        codex=make_codex_adapter(get_settings()),
        hermes=make_hermes_adapter(get_settings()),
    )
    graph = build_workflow_graph(deps, get_checkpoint_saver())
    return WorkflowRuntime(graph, projector)


def reset_workflow_runtime_cache() -> None:
    get_workflow_runtime.cache_clear()
    get_checkpoint_saver.cache_clear()
```

Use `reset_workflow_runtime_cache()` only in isolated tests or controlled
configuration reloads; an in-flight production task must retain its runtime.

- [ ] **Step 6: Update task history expectations**

Preserve existing history fields and add no required keys to the list response. Add one test proving a `waiting_approval` task is included and sorted normally.

- [ ] **Step 7: Run focused regression tests**

```powershell
python -m pytest backend/tests/test_workflow_projection.py backend/tests/test_task_history.py -v
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit**

```powershell
git add backend/models/task.py backend/services/task_runner.py backend/services/workflow_projection.py backend/tests
git commit -m "feat: project LangGraph state into task records"
```

---

### Task 8: Add FastAPI and Local-Server Resume Endpoints

**Files:**
- Modify: `ai-report-ppt-controller/backend/routers/task.py`
- Modify: `ai-report-ppt-controller/backend/dev_server.py`
- Create: `ai-report-ppt-controller/backend/tests/test_workflow_api.py`

**Interfaces:**
- Consumes: validated approval/resolution payloads
- Produces: `/run`, `/workflow-state`, `/approve-search-plan`, `/resolve-blocker`, `/approve-export`

- [ ] **Step 1: Write failing FastAPI route tests**

```python
from fastapi.testclient import TestClient

from backend.app import create_app


def test_search_plan_approval_endpoint_resumes_matching_interrupt(monkeypatch) -> None:
    captured = {}

    def fake_resume(task_id, payload):
        captured.update({"task_id": task_id, "payload": payload})
        return type("Record", (), {"model_dump": lambda self: {"task_id": task_id, "status": "running"}})()

    monkeypatch.setattr("backend.routers.task.resume_workflow", fake_resume)
    response = TestClient(create_app()).post(
        "/api/task/task-1/approve-search-plan",
        json={"action": "approve", "feedback": ""},
    )
    assert response.status_code == 200
    assert captured["payload"]["action"] == "approve"


def test_invalid_export_action_returns_422() -> None:
    response = TestClient(create_app()).post(
        "/api/task/task-1/approve-export",
        json={"action": "publish_everything"},
    )
    assert response.status_code == 422
```

- [ ] **Step 2: Verify route tests fail**

```powershell
python -m pytest backend/tests/test_workflow_api.py -v
```

Expected: endpoint 404 or missing import errors.

- [ ] **Step 3: Add typed FastAPI endpoints**

Import `BackgroundTasks`, the approval models, and workflow functions. Add:

```python
@router.get("/{task_id}/workflow-state", dependencies=[Depends(require_api_token)])
def workflow_state(task_id: str) -> dict:
    return workflow_snapshot(task_id)


@router.post("/{task_id}/approve-search-plan", dependencies=[Depends(require_api_token)])
def approve_search_plan(task_id: str, payload: ApprovalDecision) -> dict:
    return resume_workflow(task_id, payload.as_payload()).model_dump()


@router.post("/{task_id}/resolve-blocker", dependencies=[Depends(require_api_token)])
def resolve_blocker(task_id: str, payload: HumanResolution) -> dict:
    return resume_workflow(task_id, payload.as_payload()).model_dump()


@router.post("/{task_id}/approve-export", dependencies=[Depends(require_api_token)])
def approve_export(task_id: str, payload: ExportDecision) -> dict:
    return resume_workflow(task_id, payload.as_payload()).model_dump()
```

Before resuming, compare `workflow_snapshot(task_id)["pending"]["kind"]` with the endpoint's allowed kind and return HTTP 409 for mismatches.

- [ ] **Step 4: Mirror endpoints in dev_server**

In `route_get`, add `workflow-state`. In `route_post`, validate
`approve-search-plan` with `ApprovalDecision`, `resolve-blocker` with
`HumanResolution`, and `approve-export` with `ExportDecision` before calling
`resume_workflow`. Return:

- HTTP 400 for invalid JSON or validation.
- HTTP 409 for wrong pending-interrupt kind.
- HTTP 404 for unknown task.
- HTTP 200 with the projected `TaskRecord` after a valid resume.

Use the same background-thread registry as `/run` so long agent calls do not block the HTTP handler.

- [ ] **Step 5: Run API and compile tests**

```powershell
python -m pytest backend/tests/test_workflow_api.py -v
python -m compileall backend
```

Expected: route tests pass and Python compilation succeeds.

- [ ] **Step 6: Commit**

```powershell
git add backend/routers/task.py backend/dev_server.py backend/tests/test_workflow_api.py
git commit -m "feat: expose workflow approval endpoints"
```

---

### Task 9: Add Approval and Blocker Controls to the Served Static UI

**Files:**
- Modify: `ai-report-ppt-controller/frontend/static/index.html`
- Modify: `ai-report-ppt-controller/frontend/static/app.js`
- Modify: `ai-report-ppt-controller/frontend/static/styles.css`
- Modify: `ai-report-ppt-controller/frontend/static/app.restore.test.js`

**Interfaces:**
- Consumes: `TaskRecord.pending_interrupt` and approval endpoints
- Produces: searchable plan review, blocker resolution, export selection, and automatic polling restart

- [ ] **Step 1: Write failing browser-free UI tests**

Append the following helper and tests to `frontend/static/app.restore.test.js` so
they reuse the file's existing `createFakeDocument`, `createStorage`,
`jsonResponse`, and `waitFor` helpers:

```javascript
function searchPlanRecord() {
  return {
    task_id: "task-approval-1",
    status: "waiting_approval",
    request: { title: "GaN" },
    steps: [],
    pending_interrupt: {
      kind: "search_plan",
      search_plan: { task_understanding: "GaN public-source review", queries: [] },
      allowed_actions: ["approve", "edit_and_approve", "regenerate", "cancel"],
    },
  };
}


function createApprovalHarness(record, calls = []) {
  const document = createFakeDocument();
  const localStorage = createStorage({
    ai_report_current_task_id: record.task_id,
  });
  const context = vm.createContext({
    console,
    document,
    FormData: FakeFormData,
    localStorage,
    setTimeout,
    clearTimeout,
    fetch: async (path, options = {}) => {
      calls.push({ path, options });
      if (path === "/api/health") {
        return jsonResponse({ ok: true, phase: "test", storage: { writable: true } });
      }
      if (path === "/api/tasks") {
        return jsonResponse({ tasks: [] });
      }
      if (path === `/api/task/${record.task_id}`) {
        return jsonResponse(record);
      }
      if (path === `/api/task/${record.task_id}/files`) {
        return jsonResponse({ task_id: record.task_id, files: [] });
      }
      if (path === `/api/task/${record.task_id}/phase2/audit`) {
        return jsonResponse({ available: false, sources: [] });
      }
      if (
        path === `/api/task/${record.task_id}/approve-search-plan`
        || path === `/api/task/${record.task_id}/approve-export`
        || path === `/api/task/${record.task_id}/resolve-blocker`
      ) {
        return jsonResponse({ ...record, status: "running", pending_interrupt: {} });
      }
      return jsonResponse({ error: `unexpected ${path}` }, false);
    },
    window: {
      setInterval: () => 1,
      clearInterval: () => {},
    },
  });
  context.window.window = context.window;
  context.window.document = document;
  context.window.localStorage = localStorage;
  return {
    calls,
    document,
    initialize: async () => {
      vm.runInContext(readFileSync(APP_JS, "utf8"), context);
      await waitFor(() => {
        assert.equal(
          document.querySelector("#current-task").textContent,
          `GaN (${record.task_id})`,
        );
      });
    },
  };
}


test("search plan interrupt renders approval controls", async () => {
  const { document, initialize } = createApprovalHarness(searchPlanRecord());
  await initialize();
  assert.equal(document.querySelector("#approval-panel").classList.contains("hidden"), false);
  assert.match(document.querySelector("#approval-content").textContent, /GaN public-source review/);
});


test("approve button posts to search approval endpoint", async () => {
  const calls = [];
  const { document, initialize } = createApprovalHarness(searchPlanRecord(), calls);
  await initialize();
  document.querySelector("#approval-approve").click();
  await waitFor(() => assert.equal(calls.at(-1).path, "/api/task/task-approval-1/approve-search-plan"));
  assert.equal(JSON.parse(calls.at(-1).options.body).action, "approve");
});


test("edited search plan is validated and approved in one action", async () => {
  const calls = [];
  const { document, initialize } = createApprovalHarness(searchPlanRecord(), calls);
  await initialize();
  document.querySelector("#search-task-understanding").value = "Edited GaN scope";
  document.querySelector("#approval-edit-approve").click();
  await waitFor(() => {
    assert.equal(
      calls.at(-1).path,
      "/api/task/task-approval-1/approve-search-plan",
    );
  });
  const body = JSON.parse(calls.at(-1).options.body);
  assert.equal(body.action, "edit_and_approve");
  assert.equal(body.edited_search_plan.task_understanding, "Edited GaN scope");
});


test("export approval can publish Word only", async () => {
  const calls = [];
  const record = {
    ...searchPlanRecord(),
    pending_interrupt: {
      kind: "export",
      manifest: { supporting_files: [], approved_deliverables: [] },
      allowed_actions: [
        "approve_all",
        "approve_word_only",
        "approve_ppt_only",
        "request_revision",
        "cancel_publication",
      ],
    },
  };
  const { document, initialize } = createApprovalHarness(record, calls);
  await initialize();
  document.querySelector("#approval-export-scope").value = "approve_word_only";
  document.querySelector("#approval-approve").click();
  await waitFor(() => {
    assert.equal(
      calls.at(-1).path,
      "/api/task/task-approval-1/approve-export",
    );
  });
  assert.equal(
    JSON.parse(calls.at(-1).options.body).action,
    "approve_word_only",
  );
});
```

- [ ] **Step 2: Run the tests and verify failure**

```powershell
node --test frontend/static/app.restore.test.js
```

Expected: the new approval assertions fail because the panel content and handlers
do not exist; the existing restoration tests still pass.

- [ ] **Step 3: Add one approval panel**

Add below the workflow timeline:

```html
<section id="approval-panel" class="approval-panel hidden" aria-live="polite">
  <div class="panel-head">
    <div>
      <p class="eyebrow">需要人工确认</p>
      <h3 id="approval-title">审批</h3>
    </div>
    <span id="approval-kind" class="badge needs_review"></span>
  </div>
  <pre id="approval-content" class="approval-content"></pre>
  <div id="search-plan-editor" class="hidden">
    <label>
      <span>任务理解</span>
      <textarea id="search-task-understanding" rows="3"></textarea>
    </label>
    <div id="search-query-editor"></div>
    <label>
      <span>成功标准（每行一项）</span>
      <textarea id="search-success-criteria" rows="4"></textarea>
    </label>
  </div>
  <label>
    <span>意见或修订要求</span>
    <textarea id="approval-feedback" rows="4"></textarea>
  </label>
  <label id="export-scope-row" class="hidden">
    <span>导出范围</span>
    <select id="approval-export-scope">
      <option value="approve_all">Word 与 PowerPoint</option>
      <option value="approve_word_only">仅 Word</option>
      <option value="approve_ppt_only">仅 PowerPoint</option>
    </select>
  </label>
  <div id="approval-actions" class="button-row left">
    <button id="approval-approve" class="primary" type="button">批准</button>
    <button id="approval-edit-approve" class="secondary hidden" type="button">应用修改并批准</button>
    <button id="approval-revise" class="secondary" type="button">要求修订</button>
    <button id="approval-cancel" class="danger" type="button">取消</button>
  </div>
</section>
```

- [ ] **Step 4: Render interrupt-specific actions**

Add to `app.js`:

```javascript
function renderPendingInterrupt(record) {
  const panel = document.querySelector("#approval-panel");
  const pending = record.pending_interrupt || {};
  if (!pending.kind) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  document.querySelector("#approval-kind").textContent = pending.kind;
  document.querySelector("#approval-content").textContent = JSON.stringify(
    pending.search_plan || pending.audit || pending.quality || pending.manifest || pending,
    null,
    2
  );
  if (pending.kind === "search_plan") {
    renderSearchPlanEditor(pending.search_plan);
  }
  configureApprovalActions(record.task_id, pending.kind);
}


function approvalEndpoint(taskId, kind) {
  if (kind === "search_plan") return `/api/task/${taskId}/approve-search-plan`;
  if (kind === "export") return `/api/task/${taskId}/approve-export`;
  return `/api/task/${taskId}/resolve-blocker`;
}


async function submitApproval(taskId, kind, action) {
  const feedback = document.querySelector("#approval-feedback").value.trim();
  const body = { action, feedback };
  if (action === "edit_and_approve") {
    body.edited_search_plan = collectEditedSearchPlan();
  }
  const record = await api(approvalEndpoint(taskId, kind), {
    method: "POST",
    body: JSON.stringify(body),
  });
  renderTask(record);
  rememberTask(record);
  startTaskPolling();
}
```

`renderSearchPlanEditor` must populate editable task understanding, query text,
query purpose, and success criteria while retaining the untouched fields from
the original `SearchPlan`. `collectEditedSearchPlan` reconstructs the complete
schema, splitting success criteria on non-empty lines. Show
`#approval-edit-approve` only for `search_plan`; it submits
`edit_and_approve`. Keep the ordinary approve action for accepting the plan
unchanged.

Map buttons as follows:

| Interrupt kind | Approve | Revise | Cancel |
|---|---|---|---|
| `search_plan` | `approve` | `regenerate` | `cancel` |
| `evidence_blocker` | `continue_with_limitations` | hidden | `cancel` |
| `quality_blocker` | `continue_with_limitations` | `revise` | `cancel` |
| `export` | value selected in `#approval-export-scope` | `request_revision` | `cancel_publication` |

At `evidence_blocker`, two research rounds have already been consumed, so the
UI must not offer another automatic supplement action. The user may continue
with explicit limitations or cancel; manual source upload is a separate future
workflow.

Show `#export-scope-row` only for the export interrupt. The approve handler must
read the select value at click time. Disable `approve_word_only` or
`approve_ppt_only` when the manifest has no matching artifact; for
`research_only` and `outline_only`, show a single `approve_all` option labelled
“批准 Markdown 与证据包”. Call `renderPendingInterrupt(record)` from
`renderTask`.

- [ ] **Step 5: Keep polling stopped while waiting for approval**

Update:

```javascript
function isRunningStatus(status) {
  return status === "running";
}
```

Do not treat `waiting_approval` as running. A valid approval submission explicitly restarts polling.

- [ ] **Step 6: Add restrained approval styling**

Add styles for `.approval-panel`, `.approval-content`, `.danger`, and the waiting-approval badge. Reuse current colors and spacing; do not redesign unrelated screens.

- [ ] **Step 7: Run UI tests and syntax check**

```powershell
node --test frontend/static/app.restore.test.js
node --check frontend/static/app.js
```

Expected: all Node tests pass and syntax check exits with code 0.

- [ ] **Step 8: Commit**

```powershell
git add frontend/static
git commit -m "feat: add workflow approval controls"
```

---

### Task 10: Complete Mock End-to-End Coverage, Documentation, and Regression Verification

**Files:**
- Create: `ai-report-ppt-controller/backend/tests/test_langgraph_workflow_e2e.py`
- Create: `ai-report-ppt-controller/backend/tests/test_live_agent_smoke.py`
- Modify: `ai-report-ppt-controller/backend/services/agent_adapters.py`
- Modify: `ai-report-ppt-controller/README.md`
- Modify: `ai-report-ppt-controller/docs/agent_loop.md`
- Modify: `ai-report-ppt-controller/.env.example`

**Interfaces:**
- Consumes: complete mock workflow and public configuration
- Produces: reproducible acceptance evidence and operator documentation

- [ ] **Step 1: Write the full mock acceptance test**

```python
from __future__ import annotations

import json
from pathlib import Path

from backend import config
from backend.models.task import TaskRequest
from backend.services import task_runner as runner


def test_mock_workflow_requires_two_approvals_and_exports_traceable_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    storage = tmp_path / "runtime"
    monkeypatch.setattr(config, "STORAGE_DIR", storage)
    monkeypatch.setattr(config, "CONFIG_PATH", storage / "config.json")
    monkeypatch.setattr(runner, "STORAGE_DIR", storage)
    monkeypatch.setattr(runner, "JOB_ROOT", storage / "workspace" / "jobs")
    monkeypatch.setenv(
        "LANGGRAPH_CHECKPOINT_DB",
        str(storage / "workflow_checkpoints.sqlite3"),
    )
    monkeypatch.setenv("CODEX_MODE", "mock")
    monkeypatch.setenv("HERMES_MODE", "mock")
    config.get_settings.cache_clear()
    runner.reset_workflow_runtime_cache()

    try:
        record = runner.create_task(
            TaskRequest(
                title="GaN public research",
                task_type="ppt_word",
                output_dir=str(storage / "outputs"),
                enable_web_search=True,
                enable_patent_search=True,
            )
        )

        runner.run_workflow(record.task_id)
        first = runner.load_record(record.task_id)
        assert first.status == "waiting_approval"
        assert first.pending_interrupt["kind"] == "search_plan"

        runner.resume_workflow(record.task_id, {"action": "approve", "feedback": ""})
        second = runner.load_record(record.task_id)
        assert second.status == "waiting_approval"
        assert second.pending_interrupt["kind"] == "export"

        runner.resume_workflow(record.task_id, {"action": "approve_all", "feedback": ""})
        final = runner.load_record(record.task_id)
        workspace = runner.task_dir(record.task_id)
        assert final.status == "done"
        assert (workspace / "draft" / "master_report.md").exists()
        assert (workspace / "output" / "final" / "master_report.md").exists()
        assert (workspace / "output" / "final" / "final_report.docx").exists()
        assert (workspace / "output" / "final" / "final_presentation.pptx").exists()
        for support_name in (
            "source_register.json",
            "citation_index.json",
            "evidence_audit.json",
            "workflow_audit.json",
        ):
            assert (workspace / "output" / "final" / support_name).exists()
        manifest = json.loads(
            (workspace / "output" / "final" / "final_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        assert manifest["approved_deliverables"]
        assert len(manifest["supporting_files"]) == 5
        assert "[EV-001]" in (
            workspace / "draft" / "master_report.md"
        ).read_text(encoding="utf-8")
    finally:
        runner.reset_workflow_runtime_cache()
        config.get_settings.cache_clear()
```

Add tests for:

- two insufficient research rounds routing to `evidence_blocker`;
- a partial Hermes package retaining successful evidence while recording individual PDF/OCR failures in `failed_items`;
- two failed revisions routing to `quality_blocker`;
- the same quality blocker fingerprint appearing twice routing immediately to `quality_blocker`;
- edited search-plan approval replacing the plan before Hermes runs;
- cancel at search approval;
- final export `request_revision` returning through revision and both build nodes;
- partial Word-only export;
- recreation of the runtime between approvals;
- replay of the same node input reusing one idempotent agent result instead of calling the adapter again;
- no credential-like keys in checkpoint-projected state or logs;
- unchanged SHA-256 for files under `research/raw/`.

- [ ] **Step 2: Verify the acceptance test exposes missing mock behavior**

```powershell
python -m pytest backend/tests/test_langgraph_workflow_e2e.py -v
```

Expected: failures identify missing structured mock results or missing final artifacts.

- [ ] **Step 3: Complete structured mock outputs**

Update `MockCodexAdapter` and `MockHermesAdapter` so these task names return valid contracts:

| Task name prefix | Model |
|---|---|
| `analyze_request` | `SearchPlan` |
| `collect_sources_r` | `ResearchPackage` with `SRC-001` and `EV-001` |
| `audit_evidence_r` | `EvidenceAudit(status="sufficient")` |
| `draft_master_report` | `MasterReport` referencing `EV-001` |
| `quality_check_r` | `QualityDecision(pass=true)` |
| `revise_report_r` | corrected `MasterReport` |

Mocks must write no files outside the paths used by production nodes. Keep existing legacy mock branches only if older regression tests still call them directly.

- [ ] **Step 4: Update operator documentation**

Document:

- fixed executor table;
- public-source-only MVP boundary;
- two approval endpoints and UI behavior;
- checkpoint file location and restart behavior;
- maximum two research and revision rounds;
- `CODEX_MODE=cli`, `HERMES_MODE=api`, and mock defaults;
- Codex CLI requirement for `--output-schema`;
- commercial database and App Server exclusions;
- credential and browser-session handling rules.

Add to `.env.example`:

```text
LANGGRAPH_CHECKPOINT_DB=
LANGGRAPH_STRICT_MSGPACK=true
AGENT_TIMEOUT_SECONDS=1800
CODEX_MODE=mock
HERMES_MODE=mock
RUN_LIVE_AGENT_SMOKE=0
LIVE_PUBLIC_SOURCE_URL=
```

- [ ] **Step 5: Add an opt-in real public-source smoke test**

Create `backend/tests/test_live_agent_smoke.py`. Reuse the isolated storage
setup from the mock acceptance test, then:

```python
import json
import os
from pathlib import Path

import pytest

from backend import config
from backend.models.task import TaskRequest
from backend.models.workflow import ResearchPackage
from backend.services import task_runner as runner


def configure_isolated_storage(tmp_path: Path, monkeypatch) -> None:
    storage = tmp_path / "runtime"
    monkeypatch.setattr(config, "STORAGE_DIR", storage)
    monkeypatch.setattr(config, "CONFIG_PATH", storage / "config.json")
    monkeypatch.setattr(runner, "STORAGE_DIR", storage)
    monkeypatch.setattr(runner, "JOB_ROOT", storage / "workspace" / "jobs")
    monkeypatch.setenv(
        "LANGGRAPH_CHECKPOINT_DB",
        str(storage / "workflow_checkpoints.sqlite3"),
    )
    config.get_settings.cache_clear()
    runner.reset_workflow_runtime_cache()


def test_live_codex_and_hermes_public_source(tmp_path, monkeypatch) -> None:
    if os.getenv("RUN_LIVE_AGENT_SMOKE") != "1":
        pytest.skip("set RUN_LIVE_AGENT_SMOKE=1 to run live agents")
    public_url = os.environ["LIVE_PUBLIC_SOURCE_URL"]
    if os.getenv("CODEX_MODE") != "cli" or os.getenv("HERMES_MODE") != "api":
        pytest.skip("live smoke requires CODEX_MODE=cli and HERMES_MODE=api")

    configure_isolated_storage(tmp_path, monkeypatch)
    record = runner.create_task(
        TaskRequest(
            title="One-source public semiconductor evidence smoke test",
            task_type="word",
            search_boundary=f"Use only this public URL: {public_url}",
            enable_web_search=True,
            enable_patent_search=False,
        )
    )
    runner.run_workflow(record.task_id)
    assert runner.load_record(record.task_id).pending_interrupt["kind"] == "search_plan"
    runner.resume_workflow(record.task_id, {"action": "approve", "feedback": ""})

    snapshot = runner.workflow_snapshot(record.task_id)
    assert snapshot["pending"]["kind"] == "export"
    package = ResearchPackage.model_validate_json(
        (
            runner.task_dir(record.task_id)
            / snapshot["state"]["research_package_path"]
        ).read_text(encoding="utf-8")
    )
    assert package.sources
    assert package.evidence
    assert any(source.url == public_url for source in package.sources)
    serialized = json.dumps(snapshot, ensure_ascii=False).lower()
    assert "authorization" not in serialized
    assert "cookie" not in serialized
    assert "api_key" not in serialized
```

Wrap the live test body in `try/finally` and clear both caches in `finally`.
Extend the test to verify every downloaded `research/raw/` file has the
recorded SHA-256.
The supplied URL must be a public, stable, non-login PDF or HTML page that the
user is authorized to retrieve.

Run only when the live adapters and URL are configured:

```powershell
$env:RUN_LIVE_AGENT_SMOKE="1"
python -m pytest backend/tests/test_live_agent_smoke.py -v
```

Expected: real Codex produces a valid plan, real Hermes retrieves and parses the
specified public source, evidence remains traceable, and the workflow pauses at
export approval. A missing live configuration skips the test rather than
failing the normal suite.

- [ ] **Step 6: Run the complete backend suite**

```powershell
python -m pytest backend/tests -v
```

Expected: all backend tests pass.

- [ ] **Step 7: Run frontend tests and static verification**

```powershell
node --test frontend/static/app.restore.test.js
node --check frontend/static/app.js
```

Expected: all tests pass and JavaScript syntax is valid.

- [ ] **Step 8: Run compilation and manifest checks**

```powershell
python -m compileall backend
git diff --check
```

Expected: both commands exit with code 0 and `git diff --check` prints nothing.

- [ ] **Step 9: Run a local HTTP smoke test**

Start the zero-dependency server on a temporary loopback port:

```powershell
$env:APP_PORT="7861"
python backend/dev_server.py
```

In a second terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:7861/api/health
```

Expected: HTTP 200 with `ok: true` and workflow capabilities. Create a mock
task, start it, approve both checkpoints, then confirm
`/api/task/{task_id}/files` lists the final Markdown, DOCX, PPTX, source
register, citation index, evidence audit, workflow audit, and final manifest.

- [ ] **Step 10: Commit**

```powershell
git add backend/tests/test_langgraph_workflow_e2e.py backend/tests/test_live_agent_smoke.py backend/services/agent_adapters.py README.md docs/agent_loop.md .env.example
git commit -m "test: verify LangGraph report workflow end to end"
```

## Final Verification Checklist

- [ ] `python -m pytest backend/tests -v` passes.
- [ ] Static UI Node tests pass.
- [ ] Python and JavaScript compile/syntax checks pass.
- [ ] A task pauses exactly at search-plan approval and final export approval.
- [ ] The fixed executor map is covered by a test.
- [ ] Restarting the runtime preserves the pending approval and round counters.
- [ ] Research and revision loops never exceed two automatic rounds.
- [ ] Every factual claim in the master report references a known evidence ID.
- [ ] Word and PowerPoint derive from the exact same Markdown text and recorded hash.
- [ ] Hermes cannot write report files and Codex cannot modify raw evidence.
- [ ] Final output contains only user-approved artifacts.
- [ ] Every successful export includes the Markdown master, source register, citation index, evidence audit, and workflow audit.
- [ ] Logs and checkpoint projections contain no credentials or browser-session material.
- [ ] `git diff --check` is clean.

## Primary References

- Approved design: `docs/superpowers/specs/2026-07-30-hermes-codex-langgraph-design.md`
- LangGraph package releases: https://pypi.org/project/langgraph/
- LangGraph SQLite checkpoint releases: https://pypi.org/project/langgraph-checkpoint-sqlite/
- LangGraph persistence: https://docs.langchain.com/oss/python/langgraph/persistence
- LangGraph interrupts: https://docs.langchain.com/oss/python/langgraph/interrupts
- Codex non-interactive structured output: https://learn.chatgpt.com/docs/non-interactive-mode
- Codex App Server, explicitly outside this MVP: https://developers.openai.com/codex/app-server
