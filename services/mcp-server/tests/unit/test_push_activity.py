"""Happy-path + batching tests for `push_activity` (ING-04 · FR-2).

Covers TC-04..TC-08, TC-20..TC-21 — FR-2 (endpoint + envelope + batching) plus
regression coverage for AF-02 (backend key drift: reads `IngestFilesResponse`
shape `{received, valid, inserted, updated, rejected, rollup_summaries}` and
aggregates across batches).
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


def _backend_ok(inserted: int, updated: int = 0, **extra: object) -> dict:
    """Return an `IngestFilesResponse`-shaped dict (AF-02 regression)."""
    doc: dict = {
        "received": inserted + updated,
        "valid": inserted + updated,
        "inserted": inserted,
        "updated": updated,
        "rejected": [],
        "rollup_summaries": {},
    }
    doc.update(extra)
    return doc


@respx.mock
def test_happy_path_single_batch(
    tmp_path: Path, mocked_ingest_env: None
) -> None:
    _write_program_yaml(
        tmp_path,
        files=[{"path": "docs/activity/a1.jsonl"}, {"path": "docs/activity/a2.jsonl"}],
    )
    _write_ndjson(tmp_path / "docs/activity/a1.jsonl", [{"i": i} for i in range(6)])
    _write_ndjson(tmp_path / "docs/activity/a2.jsonl", [{"i": i} for i in range(6, 10)])

    route = respx.post(INGEST_URL).mock(
        return_value=httpx.Response(200, json=_backend_ok(inserted=10))
    )

    result = push_activity(workspace_root=str(tmp_path))

    assert result["success"] is True
    assert result["batches"] == 1
    assert result["files_read"] == 2
    assert result["rows_read"] == 10
    assert result["inserted"] == 10
    assert result["updated"] == 0
    assert result["rejected"] == []
    assert result["rollups"] == {}
    assert route.call_count == 1
    body = json.loads(route.calls[0].request.content)
    assert len(body["rows"]) == 10


@respx.mock
def test_batches_at_500(tmp_path: Path, mocked_ingest_env: None) -> None:
    _write_program_yaml(tmp_path, files=[{"path": "docs/activity/big.jsonl"}])
    _write_ndjson(
        tmp_path / "docs/activity/big.jsonl", [{"i": i} for i in range(1250)]
    )

    # Each mocked POST reports the same batch size back as received/inserted.
    def _handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        n = len(payload["rows"])
        return httpx.Response(200, json=_backend_ok(inserted=n))

    route = respx.post(INGEST_URL).mock(side_effect=_handler)

    result = push_activity(workspace_root=str(tmp_path))

    assert result["success"] is True
    assert result["batches"] == 3
    assert route.call_count == 3
    sizes = [len(json.loads(c.request.content)["rows"]) for c in route.calls]
    assert sizes == [500, 500, 250]
    assert result["rows_read"] == 1250
    assert result["inserted"] == 1250


@respx.mock
def test_aggregates_backend_keys_across_batches(
    tmp_path: Path, mocked_ingest_env: None
) -> None:
    """Regression AF-02: aggregate `inserted` / `updated` / `rejected` /
    `rollup_summaries` from the backend's `IngestFilesResponse` shape across
    multiple batches (NOT `rows_received` / `rows_upserted` / `rejections`)."""
    _write_program_yaml(tmp_path, files=[{"path": "docs/activity/big.jsonl"}])
    _write_ndjson(
        tmp_path / "docs/activity/big.jsonl", [{"i": i} for i in range(1100)]
    )

    responses = [
        httpx.Response(
            200,
            json={
                "received": 500,
                "valid": 500,
                "inserted": 400,
                "updated": 90,
                "rejected": [{"index": 5, "reason": "malformed_iso_date"}],
                "rollup_summaries": {"a": 1, "b": 2},
            },
        ),
        httpx.Response(
            200,
            json={
                "received": 500,
                "valid": 500,
                "inserted": 300,
                "updated": 190,
                "rejected": [{"index": 12, "reason": "intra_batch_duplicate"}],
                "rollup_summaries": {"b": 20, "c": 3},
            },
        ),
        httpx.Response(
            200,
            json={
                "received": 100,
                "valid": 100,
                "inserted": 50,
                "updated": 45,
                "rejected": [],
                "rollup_summaries": {"d": 4},
            },
        ),
    ]
    route = respx.post(INGEST_URL).mock(side_effect=responses)

    result = push_activity(workspace_root=str(tmp_path))

    assert result["success"] is True
    assert result["batches"] == 3
    assert result["inserted"] == 400 + 300 + 50
    assert result["updated"] == 90 + 190 + 45
    assert len(result["rejected"]) == 2
    assert {r["reason"] for r in result["rejected"]} == {
        "malformed_iso_date",
        "intra_batch_duplicate",
    }
    # Last-write-wins on key collision (`b`).
    assert result["rollups"] == {"a": 1, "b": 20, "c": 3, "d": 4}
    assert route.call_count == 3


@respx.mock
def test_skips_blank_and_comment_lines(
    tmp_path: Path, mocked_ingest_env: None
) -> None:
    _write_program_yaml(tmp_path, files=[{"path": "docs/activity/mixed.jsonl"}])
    f = tmp_path / "docs/activity/mixed.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(
        "\n"
        + json.dumps({"i": 1})
        + "\n"
        + "# comment line\n"
        + "\n"
        + json.dumps({"i": 2})
        + "\n"
        + json.dumps({"i": 3})
        + "\n"
        + "   \n"
    )

    route = respx.post(INGEST_URL).mock(
        return_value=httpx.Response(200, json=_backend_ok(inserted=3))
    )

    result = push_activity(workspace_root=str(tmp_path))

    assert result["success"] is True
    assert result["rows_read"] == 3
    assert result["inserted"] == 3
    body = json.loads(route.calls[0].request.content)
    assert len(body["rows"]) == 3


@respx.mock
def test_malformed_json_line_is_rejected_not_crashed(
    tmp_path: Path, mocked_ingest_env: None
) -> None:
    _write_program_yaml(tmp_path, files=[{"path": "docs/activity/bad.jsonl"}])
    f = tmp_path / "docs/activity/bad.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(
        json.dumps({"i": 1})
        + "\n"
        + json.dumps({"i": 2})
        + "\n"
        + "{not-json,,,\n"
        + json.dumps({"i": 3})
        + "\n"
    )

    route = respx.post(INGEST_URL).mock(
        return_value=httpx.Response(200, json=_backend_ok(inserted=3))
    )

    result = push_activity(workspace_root=str(tmp_path))

    assert result["success"] is True
    # 3 valid rows still POSTed.
    body = json.loads(route.calls[0].request.content)
    assert len(body["rows"]) == 3
    # Parse errors count toward rows_read per PRD FR-2.
    assert result["rows_read"] == 4
    # Malformed line surfaces in `rejected` with reason `malformed_ndjson_line`.
    parse_errors = [r for r in result["rejected"] if r["reason"] == "malformed_ndjson_line"]
    assert len(parse_errors) == 1
    assert "index" in parse_errors[0]
    assert route.call_count == 1


@respx.mock
def test_bearer_header_sent(tmp_path: Path, mocked_ingest_env: None) -> None:
    _write_program_yaml(tmp_path, files=[{"path": "docs/activity/a.jsonl"}])
    _write_ndjson(tmp_path / "docs/activity/a.jsonl", [{"i": 1}])
    route = respx.post(INGEST_URL).mock(
        return_value=httpx.Response(200, json=_backend_ok(inserted=1))
    )

    push_activity(workspace_root=str(tmp_path))

    assert route.call_count == 1
    assert respx.calls[0].request.headers["Authorization"] == "Bearer test-token"


@respx.mock
def test_envelope_kind_activity(tmp_path: Path, mocked_ingest_env: None) -> None:
    _write_program_yaml(tmp_path, files=[{"path": "docs/activity/a.jsonl"}])
    _write_ndjson(tmp_path / "docs/activity/a.jsonl", [{"i": 1}, {"i": 2}])
    route = respx.post(INGEST_URL).mock(
        return_value=httpx.Response(200, json=_backend_ok(inserted=2))
    )

    push_activity(workspace_root=str(tmp_path))

    assert route.call_count == 1
    body = json.loads(route.calls[0].request.content)
    assert body["kind"] == "activity"
    assert body["program_id"] == PROGRAM_ID
    assert isinstance(body["rows"], list)


@respx.mock
def test_program_id_override_used_in_envelope(
    tmp_path: Path, mocked_ingest_env: None
) -> None:
    """Regression F-2: explicit `program_id` argument overrides YAML value in POST body."""
    _write_program_yaml(tmp_path, files=[{"path": "docs/activity/a.jsonl"}])
    _write_ndjson(tmp_path / "docs/activity/a.jsonl", [{"i": 1}])
    route = respx.post(INGEST_URL).mock(
        return_value=httpx.Response(200, json=_backend_ok(inserted=1))
    )

    push_activity(program_id="prog-override", workspace_root=str(tmp_path))

    assert route.call_count == 1
    body = json.loads(route.calls[0].request.content)
    assert body["program_id"] == "prog-override"
    assert body["program_id"] != PROGRAM_ID
