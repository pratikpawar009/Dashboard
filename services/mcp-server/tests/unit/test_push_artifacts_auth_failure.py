"""Auth-failure + 5xx surfacing tests for `push_artifacts` (ING-04 · T-09 · FR-5).

Covers TC-22 — 401 is surfaced as `{success: false, http_status: 401, ...}`,
and non-401 error statuses are surfaced with the same envelope shape.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import respx
import yaml

from agentrise_mcp.tools.push_artifacts import push_artifacts

BASE_URL = "http://api.test"
INGEST_URL = f"{BASE_URL}/api/ingest/artifacts"
PROGRAM_ID = "test-program"


def _write_minimal_program_yaml(workspace_root: Path) -> None:
    harness_dir = workspace_root / ".harness"
    harness_dir.mkdir(exist_ok=True)
    doc = {
        "programId": PROGRAM_ID,
        "team": [{"email": "dev@example.test"}],
        "files": [],
        "artifacts": {
            "prd": {"kind": "constant", "value": 1},
            "user_story": {"kind": "constant", "value": 2},
            "test_case": {"kind": "constant", "value": 3},
            "arch_diagram": {"kind": "constant", "value": 4},
            "api_spec": {"kind": "constant", "value": 5},
        },
    }
    (harness_dir / "program.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))


@respx.mock
def test_401_surfaced(tmp_path: Path, mocked_ingest_env: None) -> None:
    _write_minimal_program_yaml(tmp_path)
    route = respx.post(INGEST_URL).mock(
        return_value=httpx.Response(401, json={"detail": "unauthorized"})
    )

    result = push_artifacts(workspace_root=str(tmp_path))

    assert result["success"] is False
    assert result["http_status"] == 401
    assert result["error"] == "unauthorized"
    assert route.call_count == 1


@respx.mock
def test_5xx_surfaced_with_status(tmp_path: Path, mocked_ingest_env: None) -> None:
    _write_minimal_program_yaml(tmp_path)
    route = respx.post(INGEST_URL).mock(
        return_value=httpx.Response(500, json={"detail": "boom"})
    )

    result = push_artifacts(workspace_root=str(tmp_path))

    assert result["success"] is False
    assert result["http_status"] == 500
    assert "error" in result
    assert "500" in result["error"]
    assert route.call_count == 1
