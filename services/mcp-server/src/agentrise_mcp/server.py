"""Agentrise MCP server: exposes push_activity + push_artifacts over streamable HTTP.

FR-1 pins the transport (fastmcp v2.x streamable-http), bind (`0.0.0.0:3010`), and path
(`/mcp`). FR-6 pins fail-fast on missing `AGENTRISE_INGEST_TOKEN` — `load_config()` runs
BEFORE any port is bound so a missing token exits non-zero without touching the network.
The token is NEVER printed or logged (R-07): `ConfigError` carries only the env-var name,
and the T-05 logger's token-suppression filter is installed with the loaded token as
defence-in-depth (the tool bodies never pass the token to the logger anyway).

The smoke-test env-var `AGENTRISE_MCP_SMOKE_TEST=1` short-circuits `main()` after
`build_server()` — used by the integration tests to verify the boot surface without
binding the port. This is a documented test hook, not a production toggle.
"""

from __future__ import annotations

import os
import sys

from fastmcp import FastMCP

from agentrise_mcp.core.config import ConfigError, load_config
from agentrise_mcp.core.logging import get_logger
from agentrise_mcp.tools import push_activity as _pa_module
from agentrise_mcp.tools import push_artifacts as _pat_module

_SERVER_NAME = "agentrise-mcp"
_HOST = "0.0.0.0"
_PORT = 3010
_PATH = "/mcp"
_SMOKE_ENV = "AGENTRISE_MCP_SMOKE_TEST"


def build_server() -> FastMCP:
    """Construct and return the FastMCP server with both tools registered.

    Separated from `main()` so tests can introspect the server without booting HTTP.
    """
    server = FastMCP(_SERVER_NAME)

    @server.tool()
    def push_activity(
        program_id: str | None = None,
        workspace_root: str | None = None,
    ) -> dict:
        """Push activity events from .harness/program.yaml::files[] to the ingest backend."""
        return _pa_module.push_activity(program_id, workspace_root)

    @server.tool()
    def push_artifacts(
        program_id: str | None = None,
        workspace_root: str | None = None,
    ) -> dict:
        """Push artifact counts from .harness/program.yaml::artifacts{} to the ingest backend."""
        return _pat_module.push_artifacts(program_id, workspace_root)

    return server


def main() -> int:
    """Entry point for the `agentrise-mcp` console script and `python -m agentrise_mcp`.

    Order matters: config load runs BEFORE `build_server()` and BEFORE any bind, so a
    missing token surfaces as exit code 2 with no port touched (FR-6). The token itself
    is never included in the error message — `ConfigError` names only the env-var.
    """
    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2

    logger = get_logger("agentrise_mcp", token=cfg.ingest_token)
    logger.info(
        "agentrise-mcp booting",
        extra={
            "event": "config.loaded",
            "base_url": cfg.ingest_base_url,
            "port": _PORT,
            "path": _PATH,
        },
    )

    server = build_server()

    if os.environ.get(_SMOKE_ENV) == "1":
        return 0

    server.run(transport="streamable-http", host=_HOST, port=_PORT, path=_PATH)
    return 0
