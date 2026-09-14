"""Unit tests for the json-key-count source resolver (ING-04 T-07).

Per PRD FR-3: `json-key-count` counts top-level object keys in the JSON file
at `path`, skipping any key listed in `exclude`.
"""

from __future__ import annotations

import json

import pytest

from agentrise_mcp.core.allowlist import AllowlistError
from agentrise_mcp.core.profile import ArtifactSource
from agentrise_mcp.sources.json_key_count import SourceError, resolve


def test_counts_top_level_keys(tmp_path):
    target = tmp_path / "x.json"
    target.write_text(json.dumps({"a": 1, "b": 2, "c": 3}))

    source = ArtifactSource(kind="json-key-count", path="x.json")
    assert resolve(source, tmp_path) == 3


def test_excludes_listed_keys(tmp_path):
    target = tmp_path / "x.json"
    target.write_text(json.dumps({"a": 1, "b": 2, "c": 3}))

    source = ArtifactSource(
        kind="json-key-count",
        path="x.json",
        exclude=("b",),
    )
    assert resolve(source, tmp_path) == 2


def test_missing_file_raises(tmp_path):
    source = ArtifactSource(kind="json-key-count", path="missing.json")
    with pytest.raises(SourceError, match="not found"):
        resolve(source, tmp_path)


def test_invalid_json_raises(tmp_path):
    target = tmp_path / "bad.json"
    target.write_text("{not: json")

    source = ArtifactSource(kind="json-key-count", path="bad.json")
    with pytest.raises(SourceError, match="invalid JSON"):
        resolve(source, tmp_path)


def test_non_object_json_raises(tmp_path):
    target = tmp_path / "arr.json"
    target.write_text(json.dumps([1, 2, 3]))

    source = ArtifactSource(kind="json-key-count", path="arr.json")
    with pytest.raises(SourceError, match="top-level object"):
        resolve(source, tmp_path)


def test_rejects_bad_exclude_key(tmp_path):
    target = tmp_path / "x.json"
    target.write_text(json.dumps({"a": 1}))

    source = ArtifactSource(
        kind="json-key-count",
        path="x.json",
        exclude=("$.evil",),
    )
    with pytest.raises(AllowlistError):
        resolve(source, tmp_path)
