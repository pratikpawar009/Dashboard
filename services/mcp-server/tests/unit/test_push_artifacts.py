"""Happy-path tests for `push_artifacts` (ING-04 · T-09).

Covers TC-11..TC-16, TC-20..TC-21 — FR-3 (endpoint + envelope + resolver
dispatch + partial-payload resilience).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import httpx
import respx
import yaml

from agentrise_mcp.tools.push_artifacts import push_artifacts

BASE_URL = "http://api.test"
INGEST_URL = f"{BASE_URL}/api/ingest/artifacts"
PROGRAM_ID = "test-program"


def _write_program_yaml(workspace_root: Path, artifacts: dict) -> None:
    harness_dir = workspace_root / ".harness"
    harness_dir.mkdir(exist_ok=True)
    doc = {
        "programId": PROGRAM_ID,
        "team": [{"email": "dev@example.test"}],
        "files": [],
        "artifacts": artifacts,
    }
    (harness_dir / "program.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))


def _all_five_canonical(workspace_root: Path) -> None:
    """Write program.yaml with one entry per canonical type covering all 4 resolver kinds.

    - prd:          glob-count   (2 markdown files under docs/prd)
    - user_story:   json-key-count (3 top-level keys in stories.json)
    - test_case:    json-field-sum (len(items) summed across docs/tests/*.json = 5)
    - arch_diagram: constant (value 1)
    - api_spec:     constant (value 7)
    """
    (workspace_root / "docs/prd").mkdir(parents=True)
    (workspace_root / "docs/prd/a.md").write_text("a")
    (workspace_root / "docs/prd/b.md").write_text("b")

    (workspace_root / "docs/stories").mkdir(parents=True)
    (workspace_root / "docs/stories/stories.json").write_text(
        json.dumps({"S-1": {}, "S-2": {}, "S-3": {}})
    )

    (workspace_root / "docs/tests").mkdir(parents=True)
    (workspace_root / "docs/tests/tc.json").write_text(
        json.dumps({"items": [1, 2, 3, 4, 5]})
    )

    _write_program_yaml(
        workspace_root,
        artifacts={
            "prd": {"kind": "glob-count", "path": "docs/prd", "glob": "*.md"},
            "user_story": {
                "kind": "json-key-count",
                "path": "docs/stories/stories.json",
            },
            "test_case": {
                "kind": "json-field-sum",
                "path": "docs/tests",
                "glob": "*.json",
                "field": "items",
            },
            "arch_diagram": {"kind": "constant", "value": 1},
            "api_spec": {"kind": "constant", "value": 7},
        },
    )


@respx.mock
def test_happy_path_single_post(tmp_path: Path, mocked_ingest_env: None) -> None:
    _all_five_canonical(tmp_path)
    route = respx.post(INGEST_URL).mock(
        return_value=httpx.Response(
            200,
            json={"rows_received": 5, "rows_upserted": 5, "rejections": []},
        )
    )

    result = push_artifacts(workspace_root=str(tmp_path))

    assert result == {
        "success": True,
        "rows_received": 5,
        "rows_upserted": 5,
        "rejections": [],
    }
    assert route.call_count == 1

    body = json.loads(route.calls[0].request.content)
    assert body["program_id"] == PROGRAM_ID
    assert body["kind"] == "artifacts"
    assert body["counts"] == {
        "prd": 2,
        "user_story": 3,
        "test_case": 5,
        "arch_diagram": 1,
        "api_spec": 7,
    }
    assert isinstance(body["as_of"], str)


@respx.mock
def test_bearer_header_sent(tmp_path: Path, mocked_ingest_env: None) -> None:
    _all_five_canonical(tmp_path)
    respx.post(INGEST_URL).mock(
        return_value=httpx.Response(
            200,
            json={"rows_received": 5, "rows_upserted": 5, "rejections": []},
        )
    )

    push_artifacts(workspace_root=str(tmp_path))

    assert respx.calls[0].request.headers["Authorization"] == "Bearer test-token"


@respx.mock
def test_envelope_kind_artifacts(tmp_path: Path, mocked_ingest_env: None) -> None:
    _all_five_canonical(tmp_path)
    route = respx.post(INGEST_URL).mock(
        return_value=httpx.Response(
            200,
            json={"rows_received": 5, "rows_upserted": 5, "rejections": []},
        )
    )

    push_artifacts(workspace_root=str(tmp_path))

    body = json.loads(route.calls[0].request.content)
    assert body["kind"] == "artifacts"


@respx.mock
def test_as_of_is_iso_utc(tmp_path: Path, mocked_ingest_env: None) -> None:
    _all_five_canonical(tmp_path)
    route = respx.post(INGEST_URL).mock(
        return_value=httpx.Response(
            200,
            json={"rows_received": 5, "rows_upserted": 5, "rejections": []},
        )
    )

    push_artifacts(workspace_root=str(tmp_path))

    body = json.loads(route.calls[0].request.content)
    as_of_raw = body["as_of"]
    assert isinstance(as_of_raw, str)
    # Must be a timezone-aware UTC ISO-8601 string.
    assert as_of_raw.endswith("+00:00") or as_of_raw.endswith("Z")
    parsed = datetime.fromisoformat(as_of_raw.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() is not None
    assert parsed.utcoffset().total_seconds() == 0


@respx.mock
def test_partial_payload_still_succeeds(
    tmp_path: Path, mocked_ingest_env: None
) -> None:
    _write_program_yaml(
        tmp_path,
        artifacts={
            "arch_diagram": {"kind": "constant", "value": 4},
            "api_spec": {"kind": "constant", "value": 9},
        },
    )
    route = respx.post(INGEST_URL).mock(
        return_value=httpx.Response(
            200,
            json={"rows_received": 2, "rows_upserted": 2, "rejections": []},
        )
    )

    result = push_artifacts(workspace_root=str(tmp_path))

    assert result["success"] is True
    assert route.call_count == 1
    body = json.loads(route.calls[0].request.content)
    assert body["counts"] == {"arch_diagram": 4, "api_spec": 9}
    assert set(body["counts"].keys()) == {"arch_diagram", "api_spec"}


@respx.mock
def test_resolver_error_included_not_aborting(
    tmp_path: Path, mocked_ingest_env: None
) -> None:
    # 4 constants that succeed + 1 json-key-count pointing at a missing file.
    _write_program_yaml(
        tmp_path,
        artifacts={
            "prd": {"kind": "constant", "value": 2},
            "user_story": {
                "kind": "json-key-count",
                "path": "docs/does_not_exist.json",
            },
            "test_case": {"kind": "constant", "value": 3},
            "arch_diagram": {"kind": "constant", "value": 1},
            "api_spec": {"kind": "constant", "value": 7},
        },
    )
    route = respx.post(INGEST_URL).mock(
        return_value=httpx.Response(
            200,
            json={"rows_received": 4, "rows_upserted": 4, "rejections": []},
        )
    )

    result = push_artifacts(workspace_root=str(tmp_path))

    assert result["success"] is True
    assert route.call_count == 1

    body = json.loads(route.calls[0].request.content)
    # The 4 successful canonical types are present; the failing one is not.
    assert set(body["counts"].keys()) == {
        "prd",
        "test_case",
        "arch_diagram",
        "api_spec",
    }
    assert "user_story" not in body["counts"]

    assert "resolver_errors" in result
    errors = result["resolver_errors"]
    assert len(errors) == 1
    entry = errors[0]
    assert entry["canonical_type"] == "user_story"
    assert entry["kind"] == "json-key-count"
    assert "error" in entry


def test_all_resolvers_fail_returns_error_envelope_no_http(
    tmp_path: Path, mocked_ingest_env: None
) -> None:
    _write_program_yaml(
        tmp_path,
        artifacts={
            "prd": {"kind": "json-key-count", "path": "missing/a.json"},
            "user_story": {"kind": "json-key-count", "path": "missing/b.json"},
            "test_case": {"kind": "json-key-count", "path": "missing/c.json"},
            "arch_diagram": {"kind": "json-key-count", "path": "missing/d.json"},
            "api_spec": {"kind": "json-key-count", "path": "missing/e.json"},
        },
    )

    with respx.mock(assert_all_called=False) as respx_mock:
        respx_mock.post(INGEST_URL)
        result = push_artifacts(workspace_root=str(tmp_path))
        assert respx_mock.calls.call_count == 0

    assert result["success"] is False
    assert result["error"] == "no artifact counts resolved"
    assert len(result["resolver_errors"]) == 5
