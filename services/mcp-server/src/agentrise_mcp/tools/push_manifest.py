"""`push_manifest` MCP tool body — program identity + roster.

Reads `.harness/program.yaml::program` (name/type/description) and `::team[]`
(email/name/role/aliases) under `workspace_root` and POSTs ONE call to
`_INGEST_MANIFEST_PATH = "/api/ingest/manifest"` with the frozen envelope
`{programId, program: {name, type, description}, team: [...]}`.

Why this tool exists: `push_activity` and `push_artifacts` send metrics keyed
by `program_id`, and the backend's rollup rebuild creates a `program_summary`
row with EMPTY identity strings for any `program_id` it sees. Nothing else
writes `program_summary.name`/`type`/`description` -- only this endpoint does
(`app/services/manifest_ingest.py`). Without this tool a program shows up on
the dashboard with real token counts and a blank label, and `program_roster`
stays empty so no usage attributes to a named person.

`programId` travels in the BODY, not the path, matching the other ingest
tools. Note the wire field is camelCase `programId` here (the one aliased
field on `ManifestIn`), unlike activity/artifacts which use `program_id`.

Two-tier validation is the backend's: a bad `program.type` aborts the whole
request with 400 and writes nothing, whereas one malformed `team[]` entry is
rejected on its own while the identity write and every other entry commit.
This tool therefore does not pre-validate role slugs -- `role_map.py` owns
that vocabulary and reports per-entry outcomes in the response.

Fail-fast: `load_config()` runs BEFORE any HTTP is opened, mirroring
`push_artifacts`; a missing `AGENTRISE_INGEST_TOKEN` returns the shared
missing-token envelope and never touches the network. The token is NEVER
logged and NEVER embedded in the returned dict.

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

__all__ = ["push_manifest"]

_INGEST_MANIFEST_PATH = "/api/ingest/manifest"

_MISSING_TOKEN_ENVELOPE: dict[str, Any] = {
    "success": False,
    "error": "missing_ingest_token",
    "message": "Set AGENTRISE_INGEST_TOKEN before invoking this tool.",
}


def push_manifest(
    program_id: str | None = None,
    workspace_root: str | None = None,
) -> dict[str, Any]:
    """Push program identity + team roster from `.harness/program.yaml`.

    `program_id` — when supplied, overrides the `programId` field in
    `.harness/program.yaml`. When `None`, the YAML value is used.

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

    if program.identity is None:
        return {
            "success": False,
            "error": "missing_program_identity",
            "message": (
                "program.yaml has no 'program:' block (name/type/description); "
                "nothing to push."
            ),
        }

    effective_program_id = program_id or program.program_id

    body: dict[str, object] = {
        "programId": effective_program_id,
        "program": {
            "name": program.identity.name,
            "type": program.identity.type,
            "description": program.identity.description,
        },
        "team": [
            {
                "email": member.email,
                "name": member.name,
                "role": member.role,
                "aliases": list(member.aliases),
            }
            for member in program.team_members
        ],
    }

    logger.info(
        "push_manifest started",
        extra={
            "event": "push_manifest_started",
            "program_id": effective_program_id,
            "team_entries": len(program.team_members),
        },
    )

    with HttpClient(base_url=cfg.ingest_base_url, token=cfg.ingest_token) as client:
        try:
            resp = client.post_json(_INGEST_MANIFEST_PATH, body)
        except NETWORK_RETRY_EXCEPTIONS as exc:
            logger.error(
                "push_manifest network error",
                extra={
                    "event": "push_manifest_failed",
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
                "push_manifest auth failed",
                extra={
                    "event": "push_manifest_auth_failed",
                    "program_id": effective_program_id,
                    "http_status": resp.status_code,
                },
            )
            return {
                "success": False,
                "error": error_label,
                "http_status": resp.status_code,
            }

        if resp.status_code not in (200, 202):
            logger.error(
                "push_manifest backend error",
                extra={
                    "event": "push_manifest_failed",
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
        "push_manifest completed",
        extra={
            "event": "push_manifest_completed",
            "program_id": effective_program_id,
            "team_entries": len(program.team_members),
        },
    )

    return {
        "success": True,
        "program_id": effective_program_id,
        "identity": resp_body.get("identity"),
        "roster": resp_body.get("roster"),
        "roster_detail": resp_body.get("roster_detail"),
    }
