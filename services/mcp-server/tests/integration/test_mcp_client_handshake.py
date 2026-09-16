"""Live MCP client handshake test (ING-04 · TC-45 · FR-1).

Uses `fastmcp.Client` against `build_server()` in-memory (no subprocess, no
port bind — the Client's in-memory transport calls the registered `@server.
tool()` handlers directly). This is what a real MCP client (Claude Desktop,
Copilot Chat, MCP Inspector) will experience end-to-end: `list_tools()` must
enumerate BOTH `push_activity` + `push_artifacts` with the two-parameter
signature, and calling either tool must invoke the underlying tool body and
return its dict envelope.

Closes carry-forward TC-45 (manual → automated) from the round-2 validation
report. `respx` mocks the outbound ingest API so this test does not require
the FastAPI backend to be running.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
import yaml
from fastmcp import Client

from agentrise_mcp.server import build_server

BASE_URL = "http://api.test"
ACTIVITY_URL = f"{BASE_URL}/api/ingest/activity"
ARTIFACTS_URL = f"{BASE_URL}/api/ingest/artifacts"
PROGRAM_ID = "test-program"


def _write_program_yaml(workspace_root: Path) -> None:
    harness_dir = workspace_root / ".harness"
    harness_dir.mkdir(exist_ok=True)
    doc = {
        "programId": PROGRAM_ID,
        "team": [{"email": "dev@example.test"}],
        "files": [{"path": "docs/activity/activity.jsonl"}],
        "artifacts": {
            "prd": {"kind": "constant", "value": 7},
            "user_story": {"kind": "constant", "value": 11},
            "test_case": {"kind": "constant", "value": 13},
            "arch_diagram": {"kind": "constant", "value": 2},
            "api_spec": {"kind": "constant", "value": 3},
        },
    }
    (harness_dir / "program.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))


def _write_activity(workspace_root: Path, rows: list[dict]) -> None:
    p = workspace_root / "docs" / "activity" / "activity.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def _tool_result_to_dict(result: object) -> dict:
    """Extract the tool's return dict from a fastmcp CallToolResult.

    fastmcp v2's Client returns a `CallToolResult` whose `.data` or
    `.structured_content` (depending on minor version) carries the raw dict
    returned by the `@server.tool()` handler. This helper is robust to both.
    """
    # v2.x recent: `.data` is the parsed structured payload.
    data = getattr(result, "data", None)
    if isinstance(data, dict):
        return data
    # v2.x older: `.structured_content` holds the raw dict.
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    # Ultra-defensive: fall through to `.content[0].text` JSON-decoded.
    content = getattr(result, "content", None)
    if content:
        first = content[0]
        text = getattr(first, "text", None)
        if isinstance(text, str):
            return json.loads(text)
    raise AssertionError(f"Cannot extract dict result from {result!r}")


@pytest.mark.asyncio
async def test_list_tools_exposes_all_tools(mocked_ingest_env: None) -> None:
    """MCP handshake: `list_tools()` returns exactly push_activity + push_artifacts."""
    server = build_server()
    async with Client(server) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}
        assert names == {"push_activity", "push_artifacts", "push_manifest"}, names

        for tool in tools:
            schema = tool.inputSchema or {}
            properties = schema.get("properties", {})
            # FR-1 tool contract: both parameters optional, both strings.
            assert "program_id" in properties, (tool.name, properties)
            assert "workspace_root" in properties, (tool.name, properties)


@respx.mock
@pytest.mark.asyncio
async def test_call_push_activity_over_mcp(
    tmp_path: Path, mocked_ingest_env: None
) -> None:
    """MCP invocation: `call_tool("push_activity", ...)` runs the tool body end-to-end."""
    _write_program_yaml(tmp_path)
    _write_activity(tmp_path, [{"seq": i} for i in range(3)])

    route = respx.post(ACTIVITY_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "received": 3,
                "valid": 3,
                "inserted": 3,
                "updated": 0,
                "rejected": [],
                "rollup_summaries": {"month_2026_09": 3},
            },
        )
    )

    server = build_server()
    async with Client(server) as client:
        raw = await client.call_tool(
            "push_activity",
            {"workspace_root": str(tmp_path)},
        )
        result = _tool_result_to_dict(raw)

    assert route.call_count == 1
    assert result["success"] is True
    assert result["files_read"] == 1
    assert result["rows_read"] == 3
    assert result["batches"] == 1
    assert result["inserted"] == 3
    assert result["updated"] == 0
    assert result["rejected"] == []
    assert result["rollups"] == {"month_2026_09": 3}


@respx.mock
@pytest.mark.asyncio
async def test_call_push_artifacts_over_mcp(
    tmp_path: Path, mocked_ingest_env: None
) -> None:
    """MCP invocation: `call_tool("push_artifacts", ...)` runs the tool body end-to-end."""
    _write_program_yaml(tmp_path)

    route = respx.post(ARTIFACTS_URL).mock(
        return_value=httpx.Response(
            200,
            json={"rows_received": 5, "rows_upserted": 5, "rejections": []},
        )
    )

    server = build_server()
    async with Client(server) as client:
        raw = await client.call_tool(
            "push_artifacts",
            {"workspace_root": str(tmp_path)},
        )
        result = _tool_result_to_dict(raw)

    assert route.call_count == 1
    assert result["success"] is True
    # Body posted to /api/ingest/artifacts carries the counts assembled from
    # the constant sources in the fixture.
    sent = route.calls[0].request
    payload = json.loads(sent.content)
    assert payload["program_id"] == PROGRAM_ID
    assert payload["kind"] == "artifacts"
    assert payload["counts"] == {
        "prd": 7,
        "user_story": 11,
        "test_case": 13,
        "arch_diagram": 2,
        "api_spec": 3,
    }


@pytest.mark.asyncio
async def test_call_push_activity_program_id_override(
    tmp_path: Path, mocked_ingest_env: None
) -> None:
    """FR-1: `program_id` argument overrides the YAML `programId`."""
    _write_program_yaml(tmp_path)
    _write_activity(tmp_path, [{"seq": 1}])

    with respx.mock(base_url=BASE_URL) as router:
        route = router.post("/api/ingest/activity").mock(
            return_value=httpx.Response(
                200,
                json={
                    "received": 1,
                    "valid": 1,
                    "inserted": 1,
                    "updated": 0,
                    "rejected": [],
                    "rollup_summaries": {},
                },
            )
        )

        server = build_server()
        async with Client(server) as client:
            await client.call_tool(
                "push_activity",
                {"program_id": "override-id", "workspace_root": str(tmp_path)},
            )

        sent = json.loads(route.calls[0].request.content)
        assert sent["program_id"] == "override-id"
        assert sent["program_id"] != PROGRAM_ID
