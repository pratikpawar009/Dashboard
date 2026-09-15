"""Live end-to-end verification script for ING-04.

Runs the MCP tools through `fastmcp.Client` (in-memory transport) against a
live FastAPI backend on http://localhost:8000. Not a pytest test — this is a
one-shot proof invoked by hand when the docker + API stack is up. Prints the
tool result envelopes to stdout for manual inspection.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from fastmcp import Client

# Import AFTER env is set, so config.py reads the runtime values.
# (`build_server()` itself does not read config, but the tool bodies do.)
os.environ.setdefault("AGENTRISE_INGEST_BASE_URL", "http://localhost:8000")
if not os.environ.get("AGENTRISE_INGEST_TOKEN"):
    print("AGENTRISE_INGEST_TOKEN not set", file=sys.stderr)
    sys.exit(2)

from agentrise_mcp.server import build_server  # noqa: E402


def _to_dict(result: object) -> dict:
    data = getattr(result, "data", None)
    if isinstance(data, dict):
        return data
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    content = getattr(result, "content", None)
    if content:
        first = content[0]
        text = getattr(first, "text", None)
        if isinstance(text, str):
            return json.loads(text)
    raise AssertionError(f"cannot extract dict from {result!r}")


async def _run() -> int:
    server = build_server()
    async with Client(server) as client:
        tools = await client.list_tools()
        print(f"tools: {sorted(t.name for t in tools)}")

        pa = _to_dict(
            await client.call_tool("push_activity", {"workspace_root": os.getcwd()})
        )
        print("push_activity:", json.dumps(pa, indent=2))

        par = _to_dict(
            await client.call_tool("push_artifacts", {"workspace_root": os.getcwd()})
        )
        print("push_artifacts:", json.dumps(par, indent=2))

        if not pa.get("success") or not par.get("success"):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
