"""Auth-failure + 5xx surfacing tests for `push_artifacts` (ING-04 · T-09 · FR-5).

Covers TC-22 — 401 and 403 are surfaced with the FR-5 auth-failure envelope
(label mapping locked); non-auth 5xx failures return the non-auth envelope
shape.  F-10 (round-2 review MEDIUM) called out the 403 branch and the
`batches_sent`/`batches_failed`/`inserted` aggregate keys were not
test-locked — this module now locks them.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
import yaml

from agentrise_mcp.tools.push_artifacts import push_artifacts

BASE_URL = "http://api.test"
INGEST_URL = f"{BASE_URL}/api/ingest/artifacts"
PROGRAM_ID = "test-program"

_FR5_AUTH_ENVELOPE_KEYS = {
    "success",
    "error",
    "http_status",
    "batches_sent",
    "batches_failed",
    "inserted",
}


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


def _assert_full_auth_envelope(
    result: dict, *, expected_error: str, expected_http_status: int
) -> None:
    """Assert the FR-5 auth-failure envelope is complete for push_artifacts.

    push_artifacts sends exactly one POST (no batching), so the aggregate
    fields have fixed values: batches_sent=1, batches_failed=1, inserted=0.
    """
    assert set(result.keys()) >= _FR5_AUTH_ENVELOPE_KEYS, (
        f"missing FR-5 keys: {_FR5_AUTH_ENVELOPE_KEYS - set(result.keys())}"
    )
    assert result["success"] is False
    assert result["error"] == expected_error
    assert result["http_status"] == expected_http_status
    assert result["batches_sent"] == 1
    assert result["batches_failed"] == 1
    assert result["inserted"] == 0


@respx.mock
@pytest.mark.parametrize(
    "http_status,expected_error",
    [(401, "unauthorized"), (403, "forbidden")],
)
def test_auth_failure_surfaced(
    tmp_path: Path,
    mocked_ingest_env: None,
    http_status: int,
    expected_error: str,
) -> None:
    """FR-5: 401 → 'unauthorized'; 403 → 'forbidden'. Both share the aggregate envelope."""
    _write_minimal_program_yaml(tmp_path)
    route = respx.post(INGEST_URL).mock(
        return_value=httpx.Response(http_status, json={"detail": "denied"})
    )

    result = push_artifacts(workspace_root=str(tmp_path))

    _assert_full_auth_envelope(
        result,
        expected_error=expected_error,
        expected_http_status=http_status,
    )
    assert route.call_count == 1


@respx.mock
def test_5xx_surfaced_with_status(tmp_path: Path, mocked_ingest_env: None) -> None:
    """Non-auth 5xx uses the non-auth envelope shape (no aggregate keys)."""
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
