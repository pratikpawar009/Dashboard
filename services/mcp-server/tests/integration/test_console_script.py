"""Integration — `agentrise-mcp` console script entry (ING-04 · T-10 / FR-1).

Skipped when the console script is not on PATH — this is the expected state until
`pip install -e services/mcp-server` runs. When installed, the script must invoke
`agentrise_mcp.server:main` and exit 0 under the smoke-test env-var.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

_CONSOLE_SCRIPT = "agentrise-mcp"
_SCRIPT_PATH = shutil.which(_CONSOLE_SCRIPT)

pytestmark = pytest.mark.skipif(
    _SCRIPT_PATH is None,
    reason=f"{_CONSOLE_SCRIPT} not installed; run `pip install -e services/mcp-server`",
)


def test_console_script_installed_and_boots() -> None:
    env = os.environ.copy()
    env["AGENTRISE_INGEST_TOKEN"] = "test-token-value"
    env["AGENTRISE_MCP_SMOKE_TEST"] = "1"
    proc = subprocess.run(
        [_CONSOLE_SCRIPT],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)


def test_console_script_missing_token_exits_two() -> None:
    env = os.environ.copy()
    env.pop("AGENTRISE_INGEST_TOKEN", None)
    env["AGENTRISE_MCP_SMOKE_TEST"] = "1"
    proc = subprocess.run(
        [_CONSOLE_SCRIPT],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert proc.returncode == 2, (proc.returncode, proc.stdout, proc.stderr)
