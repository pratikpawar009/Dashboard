"""`push_activity` MCP tool body (ING-04 · FR-2 / FR-5 / FR-6).

Reads `.harness/program.yaml::files[]` glob patterns under `workspace_root`,
matches NDJSON files, reads each line as a JSON row (skipping blank / `#`
comment lines; malformed lines land in `rejected` with reason
`malformed_ndjson_line` and do NOT crash the batch), batches rows at
`_MCP_BATCH_SIZE = 500` per POST (D-05), and POSTs each batch to
`_INGEST_ACTIVITY_PATH = "/api/ingest/activity"` (D-03 / ADR-0013) with
envelope `{program_id, kind: "activity", rows: [...]}`.

The `500`-row cap is the **MCP HTTP batch cap** and is UNRELATED to the
backend service's internal 2730-row per-INSERT DB chunk
(`activity_ingest._MAX_ROWS_PER_INSERT`, ING-02) — that is DB batching, not
HTTP batching (D-05, PRD § Documentation requirements).

Fail-fast: `load_config()` runs BEFORE any HTTP is opened (FR-6 / D-06);
missing `AGENTRISE_INGEST_TOKEN` returns the PRD FR-6 envelope
(`error: "missing_ingest_token"`) and never touches the network. Any 401 or
403 stops further batches immediately and returns the FR-5 auth-failure
envelope (`error: "unauthorized" | "forbidden"`). The token is NEVER passed
to the logger and NEVER embedded in the returned dict (R-07); the T-05
allowlist + token filter is defence-in-depth, not the sole guarantee.

Result envelope on success matches PRD FR-2 exactly:
    {success, files_read, rows_read, batches, inserted, updated, rejected, rollups}

The backend's `IngestFilesResponse` shape (`{received, valid, inserted,
updated, rejected, rollup_summaries}`) is aggregated across batches:
`inserted`/`updated` are summed; `rejected` is concatenated; `rollups` merges
per-batch `rollup_summaries` dicts with last-write-wins on key collision.

This module implements the tool body only. The `@server.tool()` registration
lives in `server.py`.
"""

from __future__ import annotations

import json
from typing import Any

from agentrise_mcp.core.config import ConfigError, load_config
from agentrise_mcp.core.http_client import HttpClient
from agentrise_mcp.core.logging import get_logger
from agentrise_mcp.core.profile import ProgramYamlError, load_program
from agentrise_mcp.core.retry import NETWORK_RETRY_EXCEPTIONS

__all__ = ["push_activity"]

# Pinned URL per D-03 / ADR-0013 — path `{kind}` must equal envelope `kind`.
_INGEST_ACTIVITY_PATH = "/api/ingest/activity"

# D-05 MCP batch cap. Unrelated to backend's 2730-row DB chunk.
_MCP_BATCH_SIZE = 500

_MISSING_TOKEN_ENVELOPE: dict[str, Any] = {
    "success": False,
    "error": "missing_ingest_token",
    "message": "Set AGENTRISE_INGEST_TOKEN before invoking this tool.",
}


def push_activity(
    program_id: str | None = None,
    workspace_root: str | None = None,
) -> dict[str, Any]:
    """Push all activity events under `workspace_root` to the ingest backend.

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
    root = program.workspace_root
    rows: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    files_read = 0

    for source in program.activity_files:
        for matched in sorted(root.glob(source.path)):
            resolved = matched.resolve()
            # FR-7 defence-in-depth — glob output must not escape workspace_root
            # via symlink (allowlist already blocks `..` in the literal pattern).
            if not resolved.is_relative_to(root):
                continue
            if not resolved.is_file():
                continue
            files_read += 1
            with resolved.open("r", encoding="utf-8") as fh:
                for raw in fh:
                    stripped = raw.strip()
                    if not stripped or stripped.startswith("#"):
                        continue
                    try:
                        rows.append(json.loads(stripped))
                    except json.JSONDecodeError:
                        # Parse-error rejection index is the row's 0-based
                        # position within its (would-be) batch. rows[] holds
                        # every parsed row so far; new parse errors slot at
                        # `len(rows) % _MCP_BATCH_SIZE`.
                        rejected.append(
                            {
                                "index": len(rows) % _MCP_BATCH_SIZE,
                                "reason": "malformed_ndjson_line",
                            }
                        )

    # rows_read = attempted JSON parses (successful + malformed), per PRD FR-2.
    rows_read = len(rows) + len(rejected)

    logger.info(
        "push_activity started",
        extra={
            "event": "push_activity_started",
            "program_id": effective_program_id,
            "workspace_root": str(root),
            "files_configured": len(program.activity_files),
        },
    )

    batches_sent = 0
    inserted_total = 0
    updated_total = 0
    rollups: dict[str, Any] = {}

    with HttpClient(base_url=cfg.ingest_base_url, token=cfg.ingest_token) as client:
        for start in range(0, len(rows), _MCP_BATCH_SIZE):
            batch = rows[start : start + _MCP_BATCH_SIZE]
            batch_index = start // _MCP_BATCH_SIZE
            try:
                resp = client.post_json(
                    _INGEST_ACTIVITY_PATH,
                    {
                        "program_id": effective_program_id,
                        "kind": "activity",
                        "rows": batch,
                    },
                )
            except NETWORK_RETRY_EXCEPTIONS as exc:
                logger.error(
                    "push_activity network error",
                    extra={
                        "event": "push_activity_batch_failed",
                        "program_id": effective_program_id,
                        "batch_index": batch_index,
                        "http_status": 0,
                    },
                )
                return {
                    "success": False,
                    "error": f"network error: {type(exc).__name__}",
                    "http_status": 0,
                    "batches_sent": batches_sent,
                    "batches_failed": 1,
                    "files_read": files_read,
                    "rows_read": rows_read,
                    "inserted": inserted_total,
                    "updated": updated_total,
                    "rejected": rejected,
                    "rollups": rollups,
                }

            batches_sent += 1

            if resp.status_code in (401, 403):
                error_label = "unauthorized" if resp.status_code == 401 else "forbidden"
                logger.error(
                    "push_activity auth failed",
                    extra={
                        "event": "push_activity_auth_failed",
                        "program_id": effective_program_id,
                        "http_status": resp.status_code,
                    },
                )
                return {
                    "success": False,
                    "error": error_label,
                    "http_status": resp.status_code,
                    "batches_sent": batches_sent,
                    "batches_failed": 1,
                    "files_read": files_read,
                    "rows_read": rows_read,
                    "inserted": inserted_total,
                    "updated": updated_total,
                    "rejected": rejected,
                    "rollups": rollups,
                }

            if resp.status_code not in (200, 202):
                logger.error(
                    "push_activity backend error",
                    extra={
                        "event": "push_activity_batch_failed",
                        "program_id": effective_program_id,
                        "batch_index": batch_index,
                        "http_status": resp.status_code,
                    },
                )
                return {
                    "success": False,
                    "error": f"backend error: HTTP {resp.status_code}",
                    "http_status": resp.status_code,
                    "batches_sent": batches_sent,
                    "batches_failed": 1,
                    "files_read": files_read,
                    "rows_read": rows_read,
                    "inserted": inserted_total,
                    "updated": updated_total,
                    "rejected": rejected,
                    "rollups": rollups,
                }

            try:
                body = resp.json()
            except json.JSONDecodeError as exc:
                return {
                    "success": False,
                    "error": f"invalid JSON response: {exc}",
                }
            if not isinstance(body, dict):
                return {
                    "success": False,
                    "error": f"invalid response body type: {type(body).__name__}",
                }

            inserted_total += int(body.get("inserted", 0) or 0)
            updated_total += int(body.get("updated", 0) or 0)
            batch_rejected = body.get("rejected") or []
            if isinstance(batch_rejected, list):
                rejected.extend(batch_rejected)
            batch_rollups = body.get("rollup_summaries") or {}
            if isinstance(batch_rollups, dict):
                # Last-write-wins on key collision (documented — PRD FR-2).
                rollups.update(batch_rollups)

    logger.info(
        "push_activity completed",
        extra={
            "event": "push_activity_completed",
            "program_id": effective_program_id,
            "files_read": files_read,
            "rows_read": rows_read,
            "batches_sent": batches_sent,
            "inserted": inserted_total,
            "updated": updated_total,
            "rejected": len(rejected),
        },
    )

    return {
        "success": True,
        "files_read": files_read,
        "rows_read": rows_read,
        "batches": batches_sent,
        "inserted": inserted_total,
        "updated": updated_total,
        "rejected": rejected,
        "rollups": rollups,
    }
