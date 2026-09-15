"""JSON field-sum source resolver (ING-04 T-07 · FR-3, FR-8, R-06).

Per PRD FR-3: for every JSON file matching `glob` under `path` (a directory
under `workspace_root`), add the length of the array at literal key `field`
in the file's top-level object. Missing key → 0 for that file. Non-list value
at `field` is silently skipped (contributes 0).

Re-runs the FR-8 JSON-key allowlist on entry (defense-in-depth). The target
directory is resolved and asserted to remain under `workspace_root` (R-06);
every matched file is likewise required to remain inside the root.
"""

from __future__ import annotations

import json
from pathlib import Path

from agentrise_mcp.core.allowlist import validate_glob, validate_json_key
from agentrise_mcp.core.profile import ArtifactSource

__all__ = ["SourceError", "resolve"]


class SourceError(Exception):
    """Raised on I/O, JSON-parse, shape, or workspace-root escape failures."""


def resolve(source: ArtifactSource, workspace_root: Path) -> int:
    """Return the total len(json[field]) across every JSON file matching (path, glob).

    Raises `AllowlistError` on invalid key or glob, `SourceError` on I/O or parse.
    """
    if source.path is None:
        raise SourceError("json-field-sum source requires 'path'")
    if source.glob is None:
        raise SourceError("json-field-sum source requires 'glob'")
    if source.field is None:
        raise SourceError("json-field-sum source requires 'field'")

    validate_glob(source.path)
    validate_glob(source.glob)
    validate_json_key(source.field)

    root_resolved = workspace_root.resolve()
    scan_root = workspace_root / source.path

    if not scan_root.exists():
        return 0

    pattern = source.glob
    if pattern.startswith("**/"):
        matches = scan_root.rglob(pattern[3:])
    else:
        matches = scan_root.glob(pattern)

    total = 0
    for match in matches:
        if not match.is_file():
            continue

        try:
            match_resolved = match.resolve()
        except OSError as exc:
            raise SourceError(f"failed to resolve match {match}: {exc}") from exc
        if not match_resolved.is_relative_to(root_resolved):
            raise SourceError(
                f"json-field-sum escaped workspace_root: {match} -> {match_resolved}"
            )

        try:
            raw = match.read_text(encoding="utf-8")
        except OSError as exc:
            raise SourceError(f"failed to read {match}: {exc}") from exc
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SourceError(f"invalid JSON in {match}: {exc}") from exc

        if not isinstance(doc, dict):
            continue
        val = doc.get(source.field)
        if isinstance(val, list):
            total += len(val)

    return total
