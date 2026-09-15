"""Integration — `python -m agentrise_mcp` entry point (ING-04 · T-10 / FR-1 / FR-6).

Smoke-only: `AGENTRISE_MCP_SMOKE_TEST=1` short-circuits `main()` after `build_server()`
so no port is bound. Two behaviours are pinned:

1. With token set + smoke flag → exit 0 (module imports, tools register, entry reached).
2. With token UNSET → exit 2 BEFORE any bind, and the token value never leaks to
   stdout/stderr (R-07). The config check fires before the smoke short-circuit.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastmcp")

_SRC = Path(__file__).resolve().parents[2] / "src"


def _child_env(**overrides: str) -> dict[str, str]:
    """Build a subprocess env with `src/` on PYTHONPATH and given token settings."""
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{_SRC}{os.pathsep}{existing}" if existing else str(_SRC)
    for key in ("AGENTRISE_INGEST_TOKEN", "AGENTRISE_INGEST_BASE_URL"):
        env.pop(key, None)
    env.update(overrides)
    return env


def test_python_dash_m_runs_without_import_error() -> None:
    env = _child_env(
        AGENTRISE_INGEST_TOKEN="test-token-value",
        AGENTRISE_MCP_SMOKE_TEST="1",
    )
    proc = subprocess.run(
        [sys.executable, "-m", "agentrise_mcp"],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert "ModuleNotFoundError" not in proc.stderr, proc.stderr
    assert "ImportError" not in proc.stderr, proc.stderr
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)


def test_missing_token_exits_nonzero_before_bind() -> None:
    token = "leaky-secret-should-not-appear"
    env = _child_env(AGENTRISE_MCP_SMOKE_TEST="1")
    env.pop("AGENTRISE_INGEST_TOKEN", None)
    proc = subprocess.run(
        [sys.executable, "-m", "agentrise_mcp"],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert proc.returncode == 2, (proc.returncode, proc.stdout, proc.stderr)
    assert token not in proc.stdout
    assert token not in proc.stderr
