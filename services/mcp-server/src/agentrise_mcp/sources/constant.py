"""Constant source resolver (ING-04 T-07 · FR-3).

Returns `source.value` verbatim. Used when the workspace does not carry the
raw data for a canonical artifact type (e.g. `arch_diagram`, `api_spec` in
`.harness/program.yaml`).
"""

from __future__ import annotations

from pathlib import Path

from agentrise_mcp.core.profile import ArtifactSource

__all__ = ["SourceError", "resolve"]


class SourceError(Exception):
    """Raised on malformed `ArtifactSource` for kind=constant."""


def resolve(source: ArtifactSource, workspace_root: Path) -> int:  # noqa: ARG001
    """Return `source.value` unchanged.

    Raises `SourceError` when `value` is missing.
    """
    if source.value is None:
        raise SourceError("constant source requires 'value'")
    return int(source.value)
