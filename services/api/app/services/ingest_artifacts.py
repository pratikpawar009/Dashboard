"""Service layer for `POST /api/ingest/artifacts` (ING-03; DECISIONS.md D-01..D-03).

Wire contract lives at `docs/requirements/api.md#ingest-artifacts-api`; the
request/response models are frozen in `app/schemas/ingest_artifacts.py`.
This module owns three load-bearing decisions:

- **Single-transaction ON CONFLICT DO UPDATE (FR-3 / AC-5 / D-02 idempotency
  / DATA-DESIGN.md § 5)**: one
  `pg_insert(program_artifacts).values(rows).on_conflict_do_update(
  index_elements=["program_id", "type"], set_={"count": ...,
  "as_of_timestamp": ...})` inside `session.begin()`. At most 5 rows fit in
  one INSERT (canonical-type set is closed at 5 entries -- schema tier);
  no chunking, no bind-parameter concern (5 * 4 non-key cols = 20 params,
  well below 65_535).
- **ADR-0012 non-applicability (D-03 / research risk R-05)**: `program_artifacts`
  is a leaf counts table; nothing under
  `app.services.rollup_rebuild` reads it. This module MUST NOT import
  `rebuild_program_rollups` or `rebuild_org_rollups`, and
  `ingest_artifacts()`'s signature has NO `on_org_rebuild` parameter --
  by construction, so a copy-paste from `activity_ingest.py` fails at type
  check and at F-16's static-code guard (`test_ingest_artifacts_no_rollup_dispatch.py`).
- **PII discipline (FR-5)**: `log_ingest_artifacts_write` allowlists
  `{event, program_id, token_label, types_written}` -- never `user_email`,
  `token_hash`, `as_of`, the raw `counts` values, or any request-body
  field. `_LOG_FIELD_ALLOWLIST` is a module-level frozenset so
  F-15 (`test_ingest_artifacts_pii_logging.py`) can diff captured
  records literally, and any future field addition must be intentional.

Envelope-tier checks (`kind` allowlist via `accept_envelope_kind`, bearer
auth, canonical-type validation on `counts` keys) are the router's /
schema's responsibility per PLAN.md § 3 -- this service assumes the caller
has already gated those. There is no row-level `program_id` mismatch check
(unlike ING-02): the artifacts envelope is single-program-scoped by
construction.
"""

import logging
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.governance import ProgramArtifact
from app.schemas.ingest_artifacts import IngestArtifactsResponse

logger = logging.getLogger(__name__)

# FR-5 / DATA-DESIGN.md § 4: exact allowlist emitted on
# `ingest_artifacts_write`. Kept as a module-level frozenset so F-15
# (`test_ingest_artifacts_pii_logging.py`) can diff the captured record's
# keys against this set literally, and any future field addition here
# must be intentional.
_LOG_FIELD_ALLOWLIST: frozenset[str] = frozenset(
    {"event", "program_id", "token_label", "types_written"}
)

# Structured event name -- pinned so F-18
# (`test_ingest_artifacts_observability.py`) can assert the string
# literally and catch an accidental copy-paste of
# `"ingest_write_completed"` from `activity_ingest.py`.
_LOG_EVENT_NAME = "ingest_artifacts_write"


async def ingest_artifacts(
    db: AsyncSession,
    program_id: str,
    counts: dict[str, int],
    as_of: datetime,
    token_label: str,
) -> IngestArtifactsResponse:
    """Idempotently upsert one artifacts batch (ingest-artifacts-api).

    `program_id` is the token-scope-checked identifier the router already
    resolved and authorised against `allowed_program_ids`. `counts` has
    already been validated router/schema-tier: every key is in the closed
    canonical vocabulary, values are integers. `as_of` is the
    producer-reported timestamp, stored verbatim.

    Pipeline: materialise one row per (program_id, type) pair from
    `counts` -> single `pg_insert(program_artifacts).on_conflict_do_update(
    index_elements=["program_id","type"], set_={"count": excluded.count,
    "as_of_timestamp": excluded.as_of_timestamp})` inside `session.begin()`
    -> commit -> emit `ingest_artifacts_write` -> return.

    NO `on_org_rebuild` parameter, NO rollup dispatch (D-03 /
    ADR-0012 non-applicability). Contrast with
    `app.services.activity_ingest.ingest_files`.
    """
    rows = [
        {
            "program_id": program_id,
            "type": artifact_type,
            "count": count_value,
            "as_of_timestamp": as_of,
        }
        for artifact_type, count_value in counts.items()
    ]

    if rows:
        insert_stmt = pg_insert(ProgramArtifact).values(rows)
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=["program_id", "type"],
            set_={
                "count": insert_stmt.excluded.count,
                "as_of_timestamp": insert_stmt.excluded.as_of_timestamp,
            },
        )
        await db.execute(stmt)
        await db.commit()

    types_written = sorted(counts.keys())

    log_ingest_artifacts_write(
        program_id=program_id,
        token_label=token_label,
        types_written=types_written,
    )

    return IngestArtifactsResponse(
        rows_received=len(counts),
        rows_upserted=len(counts),
        rejections=[],
    )


def log_ingest_artifacts_write(
    *,
    program_id: str,
    token_label: str,
    types_written: list[str],
) -> None:
    """Emit one INFO record per completed artifacts write (FR-5).

    Keyword-only signature so the allowlist is part of the type contract:
    adding a positional / stray kwarg here surfaces as an mypy failure and
    a test failure in F-15 simultaneously. The `extra` payload's key set
    equals `_LOG_FIELD_ALLOWLIST` -- no `user_email`, no `token_hash`,
    no raw `counts` values, no `as_of`, no request-body field.
    """
    logger.info(
        _LOG_EVENT_NAME,
        extra={
            "event": _LOG_EVENT_NAME,
            "program_id": program_id,
            "token_label": token_label,
            "types_written": types_written,
        },
    )
