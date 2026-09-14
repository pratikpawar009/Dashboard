"""JSON key-count source resolver (ING-04 T-07 · FR-3, FR-8, R-06).

Per PRD FR-3: read `path` (a JSON file under `workspace_root`), count
top-level object keys, skipping any key listed in `exclude`.

Re-runs the FR-8 JSON-key allowlist on entry (defense-in-depth) against every
`exclude` value. The target file is resolved and asserted to remain under
`workspace_root` (R-06).
"""

from __future__ import annotations

import json
from pathlib import Path

from agentrise_mcp.core.allowlist import validate_json_key
from agentrise_mcp.core.profile import ArtifactSource

__all__ = ["SourceError", "resolve"]


class SourceError(Exception):
    """Raised on I/O, JSON-parse, or workspace-root escape during resolution."""


def resolve(source: ArtifactSource, workspace_root: Path) -> int:
    """Return the number of top-level object keys, minus any listed in `exclude`.

    Raises `AllowlistError` on invalid exclude key, `SourceError` on I/O, parse,
    or shape failure.
    """
    if source.path is None:
        raise SourceError("json-key-count source requires 'path'")

    for excl in source.exclude:
        validate_json_key(excl)

    target = _resolve_under_root(workspace_root, source.path)

    try:
        raw = target.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SourceError(f"json file not found: {target}") from exc
    except OSError as exc:
        raise SourceError(f"failed to read {target}: {exc}") from exc

    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SourceError(f"invalid JSON in {target}: {exc}") from exc

    if not isinstance(doc, dict):
        raise SourceError(
            f"json-key-count requires a top-level object, got {type(doc).__name__}"
        )

    excluded = set(source.exclude)
    return sum(1 for k in doc.keys() if k not in excluded)


def _resolve_under_root(workspace_root: Path, relative_path: str) -> Path:
    root_resolved = workspace_root.resolve()
    candidate = (workspace_root / relative_path).resolve()
    if not candidate.is_relative_to(root_resolved):
        raise SourceError(
            f"json path escaped workspace_root: {relative_path} -> {candidate}"
        )
    return candidate
