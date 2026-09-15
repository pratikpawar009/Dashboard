"""Unit tests for the json-field-sum source resolver (ING-04 T-07).

Per PRD FR-3: for every JSON file matching `glob` under `path` (a directory
under `workspace_root`), add the length of the array at literal key `field`
in the file's top-level object. Missing key or non-list value → 0.
"""

from __future__ import annotations

import json

import pytest

from agentrise_mcp.core.allowlist import AllowlistError
from agentrise_mcp.core.profile import ArtifactSource
from agentrise_mcp.sources.json_field_sum import resolve


def test_sums_array_lengths_across_files(tmp_path):
    scan_dir = tmp_path / "dir"
    scan_dir.mkdir()
    (scan_dir / "a.json").write_text(json.dumps({"items": [1, 2, 3]}))
    (scan_dir / "b.json").write_text(json.dumps({"items": [4, 5]}))

    source = ArtifactSource(
        kind="json-field-sum",
        path="dir",
        glob="*.json",
        field="items",
    )
    assert resolve(source, tmp_path) == 5


def test_missing_field_treated_as_zero(tmp_path):
    scan_dir = tmp_path / "dir"
    scan_dir.mkdir()
    (scan_dir / "a.json").write_text(json.dumps({"items": [1, 2, 3]}))
    (scan_dir / "b.json").write_text(json.dumps({"other": [4]}))

    source = ArtifactSource(
        kind="json-field-sum",
        path="dir",
        glob="*.json",
        field="items",
    )
    assert resolve(source, tmp_path) == 3


def test_non_array_field_treated_as_zero(tmp_path):
    scan_dir = tmp_path / "dir"
    scan_dir.mkdir()
    (scan_dir / "a.json").write_text(json.dumps({"items": 42}))
    (scan_dir / "b.json").write_text(json.dumps({"items": [1, 2]}))

    source = ArtifactSource(
        kind="json-field-sum",
        path="dir",
        glob="*.json",
        field="items",
    )
    assert resolve(source, tmp_path) == 2


def test_no_matching_files_returns_zero(tmp_path):
    scan_dir = tmp_path / "dir"
    scan_dir.mkdir()

    source = ArtifactSource(
        kind="json-field-sum",
        path="dir",
        glob="*.json",
        field="items",
    )
    assert resolve(source, tmp_path) == 0


def test_rejects_bad_field(tmp_path):
    scan_dir = tmp_path / "dir"
    scan_dir.mkdir()
    (scan_dir / "a.json").write_text(json.dumps({"items": [1]}))

    source = ArtifactSource(
        kind="json-field-sum",
        path="dir",
        glob="*.json",
        field="$.evil",
    )
    with pytest.raises(AllowlistError):
        resolve(source, tmp_path)


def test_rejects_traversal_glob(tmp_path):
    source = ArtifactSource(
        kind="json-field-sum",
        path="dir",
        glob="../*.json",
        field="items",
    )
    with pytest.raises(AllowlistError):
        resolve(source, tmp_path)
