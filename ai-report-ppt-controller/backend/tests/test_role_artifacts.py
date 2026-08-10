from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.role_artifacts import (
    ArtifactBoundaryError,
    ArtifactNotChangedError,
    artifact_manifest_entry,
    fingerprint,
    load_changed_json,
    safe_artifact_path,
)


def test_safe_artifact_path_stays_inside_workspace(tmp_path: Path) -> None:
    assert safe_artifact_path(tmp_path, "execution/result.json") == tmp_path / "execution" / "result.json"


@pytest.mark.parametrize("value", ["../escape.json", r"C:\escape.json", "/escape.json"])
def test_safe_artifact_path_rejects_escape(tmp_path: Path, value: str) -> None:
    with pytest.raises(ArtifactBoundaryError):
        safe_artifact_path(tmp_path, value)


def test_load_changed_json_rejects_an_unchanged_file(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    path.write_text('{"status":"success"}', encoding="utf-8")
    before = fingerprint(path)

    with pytest.raises(ArtifactNotChangedError):
        load_changed_json(path, before)


def test_load_changed_json_returns_a_changed_object(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    path.write_text('{"status":"before"}', encoding="utf-8")
    before = fingerprint(path)
    path.write_text('{"status":"after"}', encoding="utf-8")

    assert load_changed_json(path, before) == {"status": "after"}


def test_load_changed_json_rejects_non_object_json(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    before = fingerprint(path)
    path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    with pytest.raises(ValueError, match="JSON object"):
        load_changed_json(path, before)


def test_manifest_entry_uses_relative_path_and_sha256(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    path.write_text("{}", encoding="utf-8")

    entry = artifact_manifest_entry(tmp_path, path)

    assert entry == {
        "path": "result.json",
        "sha256": hashlib.sha256(b"{}").hexdigest(),
        "size": 2,
    }
