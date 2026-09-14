"""`push_artifacts` MCP tool body (ING-04 · FR-3 / FR-5 / FR-6 / FR-7 / FR-8).

Reads `.harness/program.yaml::artifacts.<canonical_type>` entries under
`workspace_root`, resolves each source via its resolver, assembles a single
`counts` mapping, and POSTs one call to `_INGEST_ARTIFACTS_PATH =
"/api/ingest/artifacts"` (D-03 / ADR-0013) with envelope
`{program_id, kind: "artifacts", counts, as_of}`. There is no batching:
canonical types are ≤5 by construction.

Fail-fast: `load_config()` runs BEFORE any HTTP is opened (FR-6 / D-06);
missing `AGENTRISE_INGEST_TOKEN` returns the PRD FR-6 envelope
(`error: "missing_ingest_token"`) and never touches the network. Any 401 or
403 is surfaced as the FR-5 auth-failure envelope
(`error: "unauthorized" | "forbidden"`).

An `AllowlistError` from any resolver aborts the entire POST per FR-7 / FR-8
discipline — no partial payload is ever sent when a user-supplied glob or
JSON key is rejected. Non-security `SourceError` (I/O, parse, unknown kind)
is collected into a `resolver_errors` list and the remaining canonical types
are still sent.

The token is NEVER passed to the logger and NEVER embedded in the returned
dict (R-07); the T-05 allowlist + token filter is defence-in-depth. Only
allowlisted event names are emitted.

This module implements the tool body only. The `@server.tool()` registration
lives in `server.py`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from agentrise_mcp.core.allowlist import AllowlistError
from agentrise_mcp.core.config import ConfigError, load_config
from agentrise_mcp.core.http_client import HttpClient
from agentrise_mcp.core.logging import get_logger
from agentrise_mcp.core.profile import ArtifactSource, ProgramYamlError, load_program
from agentrise_mcp.core.retry import NETWORK_RETRY_EXCEPTIONS
from agentrise_mcp.sources import constant, glob_count, json_field_sum, json_key_count
from agentrise_mcp.sources.constant import SourceError as ConstantSourceError
from agentrise_mcp.sources.glob_count import SourceError as GlobCountSourceError
from agentrise_mcp.sources.json_field_sum import SourceError as JsonFieldSumSourceError
from agentrise_mcp.sources.json_key_count import SourceError as JsonKeyCountSourceError

__all__ = ["push_artifacts"]

# Pinned URL per D-03 / ADR-0013 — path `{kind}` must equal envelope `kind`.
_INGEST_ARTIFACTS_PATH = "/api/ingest/artifacts"

# Kind literals MUST match `_ALLOWED_SOURCE_KINDS` in core/profile.py.
_RESOLVERS: dict[str, Callable[[ArtifactSource, Any], int]] = {
    "constant": constant.resolve,
    "glob-count": glob_count.resolve,
    "json-key-count": json_key_count.resolve,
    "json-field-sum": json_field_sum.resolve,
}

_SOURCE_ERRORS: tuple[type[Exception], ...] = (
    ConstantSourceError,
    GlobCountSourceError,
    JsonKeyCountSourceError,
    JsonFieldSumSourceError,
)

# Per-kind mapping from the abort-reason FR-7 / FR-8 codes.
_ALLOWLIST_ERROR_BY_KIND: dict[str, str] = {
    "glob-count": "unsafe_glob_pattern",
    "json-key-count": "unsafe_json_key",
    "json-field-sum": "unsafe_json_key",
    "constant": "unsafe_glob_pattern",
}

_MISSING_TOKEN_ENVELOPE: dict[str, Any] = {
    "success": False,
    "error": "missing_ingest_token",
    "message": "Set AGENTRISE_INGEST_TOKEN before invoking this tool.",
}


def push_artifacts(
    program_id: str | None = None,
    workspace_root: str | None = None,
) -> dict[str, Any]:
    """Push canonical-artifact counts from `.harness/program.yaml` to the ingest backend.

    `program_id` — when supplied, overrides the `programId` field in
    `.harness/program.yaml`. When `None`, the YAML value is used (FR-1).

    Returns a result envelope (dict) and never raises to the MCP layer.
    """
    try:
        cfg = load_config()
    except ConfigError:
        return dict(_MISSING_TOKEN_ENVELOPE)

    logger = get_logger(token=cfg.ingest_token)

    try:
        program = load_program(workspace_root)
    except ProgramYamlError as exc:
        return {"success": False, "error": str(exc)}

    effective_program_id = program_id or program.program_id

    counts: dict[str, int] = {}
    resolver_errors: list[dict[str, str]] = []

    for canonical_type, source in program.artifacts.items():
        resolver = _RESOLVERS.get(source.kind)
        if resolver is None:
            resolver_errors.append(
                {
                    "canonical_type": canonical_type,
                    "kind": source.kind,
                    "error": f"unknown source kind: {source.kind!r}",
                }
            )
            continue

        try:
            counts[canonical_type] = int(resolver(source, program.workspace_root))
        except AllowlistError as exc:
            # FR-7 / FR-8 discipline: abort the whole POST on any allowlist
            # rejection. No partial payload leaves the process.
            error_code = _ALLOWLIST_ERROR_BY_KIND.get(source.kind, "unsafe_glob_pattern")
            return {
                "success": False,
                "error": error_code,
                "entry_key": canonical_type,
                "offending_value": str(exc),
            }
        except _SOURCE_ERRORS as exc:
            resolver_errors.append(
                {
                    "canonical_type": canonical_type,
                    "kind": source.kind,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue

    if not counts:
        return {
            "success": False,
            "error": "no artifact counts resolved",
            "resolver_errors": resolver_errors,
        }

    body: dict[str, object] = {
        "program_id": effective_program_id,
        "kind": "artifacts",
        "counts": counts,
        "as_of": datetime.now(UTC).isoformat(),
    }

    logger.info(
        "push_artifacts started",
        extra={
            "event": "push_artifacts_started",
            "program_id": effective_program_id,
            "types_configured": len(counts),
        },
    )

    with HttpClient(base_url=cfg.ingest_base_url, token=cfg.ingest_token) as client:
        try:
            resp = client.post_json(_INGEST_ARTIFACTS_PATH, body)
        except NETWORK_RETRY_EXCEPTIONS as exc:
            logger.error(
                "push_artifacts network error",
                extra={
                    "event": "push_artifacts_batch_failed",
                    "program_id": effective_program_id,
                    "http_status": 0,
                },
            )
            return {
                "success": False,
                "error": f"network error: {type(exc).__name__}",
            }

        if resp.status_code in (401, 403):
            error_label = "unauthorized" if resp.status_code == 401 else "forbidden"
            logger.error(
                "push_artifacts auth failed",
                extra={
                    "event": "push_artifacts_auth_failed",
                    "program_id": effective_program_id,
                    "http_status": resp.status_code,
                },
            )
            return {
                "success": False,
                "error": error_label,
                "http_status": resp.status_code,
                "batches_sent": 1,
                "batches_failed": 1,
                "inserted": 0,
            }

        if resp.status_code not in (200, 202):
            logger.error(
                "push_artifacts backend error",
                extra={
                    "event": "push_artifacts_batch_failed",
                    "program_id": effective_program_id,
                    "http_status": resp.status_code,
                },
            )
            return {
                "success": False,
                "http_status": resp.status_code,
                "error": f"backend error: HTTP {resp.status_code}",
            }

        try:
            resp_body = resp.json()
        except json.JSONDecodeError as exc:
            return {"success": False, "error": f"invalid JSON response: {exc}"}
        if not isinstance(resp_body, dict):
            return {
                "success": False,
                "error": f"invalid response body type: {type(resp_body).__name__}",
            }

    logger.info(
        "push_artifacts completed",
        extra={
            "event": "push_artifacts_completed",
            "program_id": effective_program_id,
            "types_written": list(counts.keys()),
        },
    )

    result: dict[str, Any] = {
        "success": True,
        "rows_received": int(resp_body.get("rows_received", 0) or 0),
        "rows_upserted": int(resp_body.get("rows_upserted", 0) or 0),
        "rejections": resp_body.get("rejections") or [],
    }
    if resolver_errors:
        result["resolver_errors"] = resolver_errors
    return result
