"""Glob-count source resolver (ING-04 T-07 · FR-3, FR-7, R-06).

Per PRD FR-3: `path` is a DIRECTORY under `workspace_root`, `glob` is the
leaf pattern relative to that directory. `exclude` is a list of glob patterns
matched (fnmatch, `**` honoured) against each candidate's workspace-relative
path; matches are dropped from the count.

Re-runs the FR-7 glob allowlist on entry (defense-in-depth: T-06 already
validated at parse time, but resolvers are a directly-callable API surface).

Every match is resolved and asserted to remain under `workspace_root` — a
symlink pointing outside the workspace raises `SourceError`. This is the R-06
containment barrier.
"""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

from agentrise_mcp.core.allowlist import validate_glob
from agentrise_mcp.core.profile import ArtifactSource

__all__ = ["SourceError", "resolve"]


class SourceError(Exception):
    """Raised on I/O failure or workspace-root escape during glob resolution."""


def resolve(source: ArtifactSource, workspace_root: Path) -> int:
    """Return the count of files under `<workspace_root>/<source.path>` matching `source.glob`.

    Raises `AllowlistError` on invalid glob, `SourceError` on filesystem escape.
    """
    if source.path is None:
        raise SourceError("glob-count source requires 'path'")
    if source.glob is None:
        raise SourceError("glob-count source requires 'glob'")

    validate_glob(source.path)
    validate_glob(source.glob)
    for excl in source.exclude:
        validate_glob(excl)

    root_resolved = workspace_root.resolve()
    scan_root = workspace_root / source.path

    if not scan_root.exists():
        return 0

    pattern = source.glob
    if pattern.startswith("**/"):
        matches = scan_root.rglob(pattern[3:])
    else:
        matches = scan_root.glob(pattern)

    count = 0
    for match in matches:
        if not match.is_file():
            continue

        try:
            match_resolved = match.resolve()
        except OSError as exc:
            raise SourceError(f"failed to resolve match {match}: {exc}") from exc

        if not match_resolved.is_relative_to(root_resolved):
            raise SourceError(
                f"glob escaped workspace_root: {match} -> {match_resolved}"
            )

        rel = match.relative_to(workspace_root).as_posix()
        if any(fnmatch(rel, excl) for excl in source.exclude):
            continue

        count += 1

    return count
