"""Auth-failure surfacing tests for `push_activity` (ING-04 · T-08 · FR-5).

Covers TC-09, TC-22 — a 401 or 403 mid-run must stop further batches and
surface the FR-5 aggregate envelope with EVERY documented key populated. F-10
(round-2 review MEDIUM) called out that earlier assertions only spot-checked
`success/http_status/error`, so the contract for `batches_sent`,
`batches_failed`, `files_read`, `rows_read`, `inserted`, `updated`,
`rejected`, `rollups` was not test-locked. This module now locks it.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
import yaml

from agentrise_mcp.tools.push_activity import push_activity

BASE_URL = "http://api.test"
INGEST_URL = f"{BASE_URL}/api/ingest/activity"
PROGRAM_ID = "test-program"

_FR5_ENVELOPE_KEYS = {
    "success",
    "error",
    "http_status",
    "batches_sent",
    "batches_failed",
    "files_read",
    "rows_read",
    "inserted",
    "updated",
    "rejected",
    "rollups",
}


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


def _assert_full_fr5_envelope(
    result: dict,
    *,
    expected_error: str,
    expected_http_status: int,
    expected_batches_sent: int,
    expected_files_read: int,
    expected_rows_read: int,
    expected_inserted: int,
    expected_updated: int,
    expected_rejected_len: int,
    expected_rollups: dict,
) -> None:
    """Assert every FR-5 envelope key is present and carries the expected value."""
    assert set(result.keys()) >= _FR5_ENVELOPE_KEYS, (
        f"missing FR-5 keys: {_FR5_ENVELOPE_KEYS - set(result.keys())}"
    )
    assert result["success"] is False
    assert result["error"] == expected_error
    assert result["http_status"] == expected_http_status
    assert result["batches_sent"] == expected_batches_sent
    assert result["batches_failed"] == 1
    assert result["files_read"] == expected_files_read
    assert result["rows_read"] == expected_rows_read
    assert result["inserted"] == expected_inserted
    assert result["updated"] == expected_updated
    assert isinstance(result["rejected"], list)
    assert len(result["rejected"]) == expected_rejected_len
    assert result["rollups"] == expected_rollups


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

    _assert_full_fr5_envelope(
        result,
        expected_error="unauthorized",
        expected_http_status=401,
        expected_batches_sent=1,
        expected_files_read=1,
        expected_rows_read=1500,
        expected_inserted=0,
        expected_updated=0,
        expected_rejected_len=0,
        expected_rollups={},
    )
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
            "rollup_summaries": {"month_2026_09": 500},
        },
    )
    unauth = httpx.Response(401, json={"detail": "unauthorized"})
    route = respx.post(INGEST_URL).mock(side_effect=[ok, ok, unauth])

    result = push_activity(workspace_root=str(tmp_path))

    _assert_full_fr5_envelope(
        result,
        expected_error="unauthorized",
        expected_http_status=401,
        expected_batches_sent=3,
        expected_files_read=1,
        expected_rows_read=1500,
        expected_inserted=1000,
        expected_updated=0,
        expected_rejected_len=0,
        # Both OK batches wrote the same rollup key; last-write-wins keeps the value.
        expected_rollups={"month_2026_09": 500},
    )
    # Auth failed mid-stream — the third POST was made, then the run stopped.
    assert route.call_count == 3


@respx.mock
@pytest.mark.parametrize(
    "http_status,expected_error",
    [(401, "unauthorized"), (403, "forbidden")],
)
def test_auth_failure_surfaces_expected_label(
    tmp_path: Path,
    mocked_ingest_env: None,
    http_status: int,
    expected_error: str,
) -> None:
    """FR-5: 401 → 'unauthorized'; 403 → 'forbidden'. Both share the same envelope."""
    _write_program_yaml(tmp_path, files=[{"path": "docs/activity/small.jsonl"}])
    _write_ndjson(
        tmp_path / "docs/activity/small.jsonl", [{"i": i} for i in range(10)]
    )

    respx.post(INGEST_URL).mock(
        return_value=httpx.Response(http_status, json={"detail": "denied"})
    )

    result = push_activity(workspace_root=str(tmp_path))

    _assert_full_fr5_envelope(
        result,
        expected_error=expected_error,
        expected_http_status=http_status,
        expected_batches_sent=1,
        expected_files_read=1,
        expected_rows_read=10,
        expected_inserted=0,
        expected_updated=0,
        expected_rejected_len=0,
        expected_rollups={},
    )
