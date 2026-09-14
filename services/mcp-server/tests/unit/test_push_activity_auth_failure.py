"""Auth-failure surfacing tests for `push_activity` (ING-04 · T-08 · FR-5).

Covers TC-09, TC-22 — a 401 mid-run must stop further batches and surface
`{success: false, http_status: 401, error: "authentication failed"}`.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import respx
import yaml

from agentrise_mcp.tools.push_activity import push_activity

BASE_URL = "http://api.test"
INGEST_URL = f"{BASE_URL}/api/ingest/activity"
PROGRAM_ID = "test-program"


def _write_program_yaml(workspace_root: Path, files: list[dict]) -> None:
    harness_dir = workspace_root / ".harness"
    harness_dir.mkdir(exist_ok=True)
    doc = {
        "programId": PROGRAM_ID,
        "team": [{"email": "dev@example.test"}],
        "files": files,
        "artifacts": {
            "prd": {"kind": "constant", "value": 0},
            "user_story": {"kind": "constant", "value": 0},
            "test_case": {"kind": "constant", "value": 0},
            "arch_diagram": {"kind": "constant", "value": 0},
            "api_spec": {"kind": "constant", "value": 0},
        },
    }
    (harness_dir / "program.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))


def _write_ndjson(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


@respx.mock
def test_401_surfaced_no_further_batches(
    tmp_path: Path, mocked_ingest_env: None
) -> None:
    _write_program_yaml(tmp_path, files=[{"path": "docs/activity/big.jsonl"}])
    _write_ndjson(
        tmp_path / "docs/activity/big.jsonl", [{"i": i} for i in range(1500)]
    )

    route = respx.post(INGEST_URL).mock(
        return_value=httpx.Response(401, json={"detail": "unauthorized"})
    )

    result = push_activity(workspace_root=str(tmp_path))

    assert result["success"] is False
    assert result["http_status"] == 401
    assert result["error"] == "unauthorized"
    # Would have been 3 batches; must halt after the first.
    assert route.call_count == 1


@respx.mock
def test_401_after_successful_batches(
    tmp_path: Path, mocked_ingest_env: None
) -> None:
    _write_program_yaml(tmp_path, files=[{"path": "docs/activity/big.jsonl"}])
    _write_ndjson(
        tmp_path / "docs/activity/big.jsonl", [{"i": i} for i in range(1500)]
    )

    ok = httpx.Response(
        200,
        json={
            "received": 500,
            "valid": 500,
            "inserted": 500,
            "updated": 0,
            "rejected": [],
            "rollup_summaries": {},
        },
    )
    unauth = httpx.Response(401, json={"detail": "unauthorized"})
    route = respx.post(INGEST_URL).mock(side_effect=[ok, ok, unauth])

    result = push_activity(workspace_root=str(tmp_path))

    assert result["success"] is False
    assert result["http_status"] == 401
    assert result["error"] == "unauthorized"
    # Auth failed mid-stream — the third POST was made, then the run stopped.
    assert route.call_count == 3
