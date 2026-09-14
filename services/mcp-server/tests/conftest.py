"""Shared fixtures for the agentrise-mcp test suite."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_PROGRAM_YAML_FIXTURE: dict = {
    "programId": "test-program",
    "program": {
        "name": "Test Program",
        "type": "Greenfield",
        "description": "Fixture program for agentrise-mcp tests.",
    },
    "team": [
        {"email": "dev@example.test", "name": "Test Dev", "role": "dev"},
    ],
    "files": [
        {"path": "docs/activity/activity.jsonl", "kind": "activity", "mode": "append"},
    ],
    "artifacts": {
        "prd": {"kind": "glob-count", "path": "docs/prd", "glob": "*.md"},
        "user_story": {"kind": "constant", "value": 0},
        "test_case": {"kind": "constant", "value": 0},
        "arch_diagram": {"kind": "constant", "value": 0},
        "api_spec": {"kind": "constant", "value": 0},
    },
}


@pytest.fixture
def tmp_program_yaml(tmp_path: Path) -> Path:
    """Write a minimal valid `.harness/program.yaml` under `tmp_path` and return its path."""
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    program_yaml = harness_dir / "program.yaml"
    program_yaml.write_text(yaml.safe_dump(_PROGRAM_YAML_FIXTURE, sort_keys=False))
    return program_yaml


@pytest.fixture
def mocked_ingest_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set the ingest env vars (token + base URL) with test sentinels."""
    monkeypatch.setenv("AGENTRISE_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("AGENTRISE_INGEST_BASE_URL", "http://api.test")
