from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


class ArtifactBoundaryError(ValueError):
    pass


class ArtifactNotChangedError(ValueError):
    pass


def safe_artifact_path(workspace: Path, relative_path: str) -> Path:
    if not isinstance(relative_path, str):
        raise ArtifactBoundaryError("Artifact path must be a string.")

    normalized = relative_path.replace("\\", "/").strip()
    posix_path = PurePosixPath(normalized)
    windows_path = PureWindowsPath(relative_path)
    if (
        not normalized
        or posix_path.is_absolute()
        or windows_path.is_absolute()
        or ".." in posix_path.parts
        or normalized in {".", "./"}
    ):
        raise ArtifactBoundaryError("Artifact path must remain inside the workspace.")

    workspace_path = workspace.resolve()
    candidate = workspace_path.joinpath(*posix_path.parts).resolve()
    try:
        candidate.relative_to(workspace_path)
    except ValueError as exc:
        raise ArtifactBoundaryError("Artifact path must remain inside the workspace.") from exc
    return candidate


def fingerprint(path: Path) -> str | None:
    try:
        content = path.read_bytes()
    except OSError:
        return None
    return hashlib.sha256(content).hexdigest()


def load_changed_json(path: Path, before_fingerprint: str | None) -> dict[str, Any]:
    after_fingerprint = fingerprint(path)
    if after_fingerprint is None or after_fingerprint == before_fingerprint:
        raise ArtifactNotChangedError(f"Artifact was not created or changed: {path.name}")

    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("Artifact must contain a JSON object.")
    return payload


def artifact_manifest_entry(workspace: Path, path: Path) -> dict[str, str | int]:
    workspace_path = workspace.resolve()
    resolved_path = path.resolve()
    try:
        relative_path = resolved_path.relative_to(workspace_path)
    except ValueError as exc:
        raise ArtifactBoundaryError("Artifact path must remain inside the workspace.") from exc

    content = resolved_path.read_bytes()
    return {
        "path": relative_path.as_posix(),
        "sha256": hashlib.sha256(content).hexdigest(),
        "size": len(content),
    }
