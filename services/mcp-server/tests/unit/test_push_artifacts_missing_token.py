"""Missing-token fail-fast test for `push_artifacts` (ING-04 · T-09 · FR-6).

When `AGENTRISE_INGEST_TOKEN` is unset, `push_artifacts` MUST return an error
envelope BEFORE any HTTP attempt. `assert_all_called=False` lets us prove no
route was ever hit.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import respx

from agentrise_mcp.tools.push_artifacts import push_artifacts


def test_missing_token_returns_error_no_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AGENTRISE_INGEST_TOKEN", raising=False)
    monkeypatch.delenv("AGENTRISE_INGEST_BASE_URL", raising=False)

    with respx.mock(assert_all_called=False) as respx_mock:
        respx_mock.post("http://127.0.0.1:8000/api/ingest/artifacts")
        result = push_artifacts(workspace_root=str(tmp_path))
        assert respx_mock.calls.call_count == 0

    assert result["success"] is False
    assert result["error"] == "missing_ingest_token"
    assert result["message"] == "Set AGENTRISE_INGEST_TOKEN before invoking this tool."
