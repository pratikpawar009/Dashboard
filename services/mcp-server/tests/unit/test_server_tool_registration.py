"""Unit — `build_server()` registers exactly the two required tools (ING-04 · T-10 / FR-1).

Asserts the visible boot surface without booting HTTP:
- exactly three tools named `push_activity`, `push_artifacts` and `push_manifest` are registered
- each tool's callable takes one optional `workspace_root: str | None` param
- the server object carries the pinned name `agentrise-mcp` and exposes `.run(...)`

fastmcp v2 exposes tools via `get_tools()` (async) returning `dict[str, Tool]`; older /
patch versions expose `_tool_manager._tools` directly. The helper below tries both so the
test survives minor API drift within the `>=2.0,<3.0` pin (D-02).
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

import pytest

pytest.importorskip("fastmcp")

from agentrise_mcp.server import build_server  # noqa: E402


def _list_tools(server: Any) -> dict[str, Any]:
    """Return the registered-tool mapping across fastmcp v2 minor versions."""
    get_tools = getattr(server, "get_tools", None)
    if callable(get_tools):
        result = get_tools()
        if inspect.iscoroutine(result):
            result = asyncio.run(result)
        if isinstance(result, dict):
            return result
    manager = getattr(server, "_tool_manager", None)
    tools = getattr(manager, "_tools", None) if manager is not None else None
    if isinstance(tools, dict):
        return tools
    raise AssertionError(
        "fastmcp did not expose a recognised tool registry (tried get_tools() and "
        "_tool_manager._tools)"
    )


def _tool_callable(tool: Any) -> Any:
    """Extract the wrapped Python callable from a fastmcp Tool object."""
    for attr in ("fn", "func", "callable", "handler"):
        candidate = getattr(tool, attr, None)
        if callable(candidate):
            return candidate
    if callable(tool):
        return tool
    raise AssertionError(f"cannot locate callable on tool object: {tool!r}")


def test_build_server_registers_exactly_three_tools() -> None:
    server = build_server()
    tools = _list_tools(server)
    assert set(tools.keys()) == {
        "push_activity",
        "push_artifacts",
        "push_manifest",
    }, tools.keys()


def test_tool_signatures_optional_program_id_and_workspace_root() -> None:
    server = build_server()
    tools = _list_tools(server)
    for name in ("push_activity", "push_artifacts", "push_manifest"):
        fn = _tool_callable(tools[name])
        sig = inspect.signature(fn)
        params = list(sig.parameters.values())
        assert len(params) == 2, f"{name}: expected 2 params, got {params!r}"
        by_name = {p.name: p for p in params}
        assert "program_id" in by_name, f"{name}: missing program_id param"
        assert "workspace_root" in by_name, f"{name}: missing workspace_root param"
        assert by_name["program_id"].default is None, (
            f"{name}: program_id default {by_name['program_id'].default!r}"
        )
        assert by_name["workspace_root"].default is None, (
            f"{name}: workspace_root default {by_name['workspace_root'].default!r}"
        )


def test_server_name_is_agentrise_mcp() -> None:
    server = build_server()
    name = getattr(server, "name", None)
    assert name == "agentrise-mcp", name


def test_server_has_run_method() -> None:
    server = build_server()
    assert hasattr(server, "run"), "FastMCP server must expose .run(...) for main()"
