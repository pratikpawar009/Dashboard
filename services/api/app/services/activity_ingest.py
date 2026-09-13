"""Service layer for `POST /api/ingest/files` (ING-02; ADR-0012, DECISIONS.md).

Wire contract lives at `docs/requirements/api.md#ingest-files-api`; the row
model + rejection vocabulary this module emits are frozen in
`app/schemas/ingest_files.py`. This module owns four load-bearing decisions:

- **Chunked upsert (FR-2 / C-1)**: `_MAX_ROWS_PER_INSERT = 2_730 =
  floor(65_535 / len(UsageEvent.__table__.columns))` at the post-migration
  24-column count. All chunks execute inside ONE transaction; the whole batch
  commits or rolls back together. The ceiling is asserted by
  `tests/unit/test_activity_ingest_chunk_ceiling.py` (T-08), which reads the
  model's column count at runtime -- a future column addition trips the test
  instead of silently overflowing Postgres's 65_535 bind-parameter limit.
- **Intra-batch dedup, last-wins (FR-3 / C-2)**: the row list is deduplicated
  in Python on `(program_id, session_id, cmd_ts)` BEFORE the upsert. Without
  this, Postgres raises `CardinalityViolation: ON CONFLICT DO UPDATE cannot
  affect row a second time` and aborts the entire statement -- one duplicate
  would fail the whole batch (research risk #5, HIGH). Dropped rows carry the
  distinct `intra_batch_duplicate` reason; the WINNER's index is preserved,
  the DROPPED indices land in `rejected[]`.
- **Org rebuild is out-of-band (D-01 / ADR-0012 / FR-1)**: this module NEVER
  calls `rebuild_org_rollups()` directly -- doing so was the shipped BED-05
  concurrency-500 hazard the ADR supersedes. `ingest_files()` invokes the
  caller-supplied `on_org_rebuild` sync callable AFTER the write commits and
  the program rebuild returns; the production caller (router T-05) wires it
  to `background_tasks.add_task(dispatch_org_rebuild)`. `dispatch_org_rebuild`
  is exported at module level: it opens a FRESH `AsyncSession` from
  `SessionLocal` because the request-scoped one is closed by the time the
  BackgroundTask fires (DATA-DESIGN.md § 5).
- **PII discipline (FR-8 / C-7)**: `log_ingest_write_completed` allowlists
  `{program_id, rows_received, rows_inserted, rows_updated, rows_rejected,
  duration_ms}` -- never `user` (email), `command`, `feature`, or row
  content. `RejectionEntry` carries `{index, reason}` only, enforced by the
  schema (F-03).

Envelope-tier checks (`kind` allowlist via `accept_envelope_kind`, 5000-row
cap, bearer auth) are the router's responsibility per PLAN.md § 2 F-01 -- this
service assumes the caller has already gated those. Row-level `program_id`
mismatch against the token-scope-checked envelope value IS enforced here
(DATA-DESIGN.md § 3): a row cannot smuggle a scope the token was not
authorised for.
"""

import logging
import time
import uuid
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal
from app.models.ingestion import UsageEvent
from app.schemas.ingest_files import (
    ActivityRowIn,
    IngestFilesResponse,
    RejectionEntry,
)
from app.services.rollup_rebuild import rebuild_org_rollups, rebuild_program_rollups

logger = logging.getLogger(__name__)

# FR-2 / C-1: chunk size ceiling = floor(65_535 / 24 columns) = 2_730. The
# post-migration 24-column count comes from T-01 (migration 006 + F-06 model
# change). T-08 asserts `len(UsageEvent.__table__.columns) * _MAX_ROWS_PER_INSERT
# <= 65_500` at runtime so a future column addition trips a unit test instead
# of silently overflowing Postgres's bind-parameter limit at runtime.
_MAX_ROWS_PER_INSERT = 2_730

# AC-4 defence-in-depth. The router (T-05, F-01) also enforces this at the
# request tier; this constant is present here as documentation for the shape
# the service assumes on entry -- the service never re-checks it.
_ENVELOPE_ROW_CAP = 5_000

# FR-4 / Q-01 (2026-09-09): wire (`activity.jsonl`) field name -> `usage_events`
# column name for the five columns whose wire and column names differ.
# `ActivityRowIn`'s `Field(alias=...)` declarations are the runtime source of
# truth; this map exists so T-07 (test_activity_ingest_alias_mapper.py) can
# assert both halves without re-deriving them from the schema module. Add an
# entry here IFF a matching `Field(alias=...)` is added to `ActivityRowIn`.
_ROW_SCHEMA_COLUMN_MAP: dict[str, str] = {
    "duration_s": "duration_seconds",
    "input_token": "input_tokens",
    "output_token": "output_tokens",
    "cache_read": "cache_read_tokens",
    "cache_write": "cache_write_tokens",
}

# FR-8 / C-7: exact allowlist emitted on `ingest_write_completed`. Kept as a
# module-level frozenset so T-11 (`test_ingest_files_pii_logging.py`) can
# diff the captured record's keys against this set literally, and any future
# field addition here must be intentional.
_LOG_FIELD_ALLOWLIST: frozenset[str] = frozenset(
    {
        "program_id",
        "rows_received",
        "rows_inserted",
        "rows_updated",
        "rows_rejected",
        "duration_ms",
    }
)

# The subset of `UsageEvent` columns that ON CONFLICT DO UPDATE overwrites --
# every non-key, non-`id` column. Preserving the existing row's `id` on
# conflict keeps referential stability (nothing today references it, but the
# invariant is cheap to hold). Derived at import time from the model's own
# column metadata so a future column addition is picked up automatically.
_CONFLICT_KEY_COLUMNS: frozenset[str] = frozenset({"program_id", "session_id", "cmd_ts"})
_CONFLICT_UPDATE_COLUMNS: tuple[str, ...] = tuple(
    c.name
    for c in UsageEvent.__table__.columns
    if c.name not in _CONFLICT_KEY_COLUMNS and c.name != "id"
)


async def ingest_files(
    db: AsyncSession,
    program_id: str,
    payload: dict[str, Any],
    token_label: str,  # noqa: ARG001 -- reserved for parity with manifest_ingest; not in log allowlist per FR-8
    on_org_rebuild: Callable[[], None],
) -> IngestFilesResponse:
    """Validate + upsert one `activity` batch (ingest-files-api).

    `program_id` is the token-scope-checked identifier the router already
    resolved and authorised against `allowed_program_ids`; the write below
    uses this parameter, never `payload.get("program_id")` a second time.
    Row-level `row.program_id != program_id` is a per-row rejection with
    reason `program_id_mismatch` (DATA-DESIGN.md § 3) -- a row cannot smuggle
    a scope the token was not authorised for.

    Pipeline: per-row Pydantic validation -> row-level program-id filter ->
    intra-batch dedup on `(program_id, session_id, cmd_ts)` last-wins ->
    chunked `pg_insert(...).on_conflict_do_update()` at
    `_MAX_ROWS_PER_INSERT` per chunk (all in one transaction) -> commit ->
    synchronous `rebuild_program_rollups(session, program_id)` -> emit
    `ingest_write_completed` -> invoke `on_org_rebuild()` once. The org
    rebuild NEVER runs inside this coroutine (D-01 / ADR-0012 / FR-1) --
    `on_org_rebuild` is the caller's scheduling hook; the router (T-05)
    wires it to `background_tasks.add_task(dispatch_org_rebuild)`.
    """
    start = time.perf_counter()
    raw_rows: list[Any] = payload.get("rows") or []
    rows_received = len(raw_rows)

    # --- Per-row Pydantic validation (FR-4). Each raw dict is validated on
    # its OWN `ActivityRowIn.model_validate()` call -- never as part of a
    # whole-body model -- so one bad row rejects only that row; siblings still
    # commit. Mirrors `manifest_ingest.py`'s two-tier discipline (D-05/D-09).
    valid_models: list[tuple[int, ActivityRowIn]] = []
    rejected: list[RejectionEntry] = []
    for index, raw_row in enumerate(raw_rows):
        try:
            model = ActivityRowIn.model_validate(raw_row)
        except ValidationError as exc:
            rejected.append(RejectionEntry(index=index, reason=_classify_row_error(exc)))
            continue
        valid_models.append((index, model))

    # --- Row-level program-id mismatch (DATA-DESIGN.md § 3). Rejects rows
    # whose declared program_id disagrees with the URL/token-scope-checked
    # envelope value. The row's own value is never logged or embedded in the
    # reason -- only the row's index (FR-8 / C-7).
    scope_ok: list[tuple[int, ActivityRowIn]] = []
    for index, model in valid_models:
        if model.program_id != program_id:
            rejected.append(RejectionEntry(index=index, reason="program_id_mismatch"))
            continue
        scope_ok.append((index, model))

    # --- Intra-batch dedup (FR-3 / C-2), last-wins. Iterating forward and
    # overwriting the map on each match preserves the LAST occurrence -- the
    # earlier indices become the dropped ones, matching `ON CONFLICT DO
    # UPDATE` semantics (the DB would also keep the last-applied write). The
    # dropped index is what lands in `rejected[]`, never the winner's.
    dedup: dict[tuple[str, str, datetime], tuple[int, ActivityRowIn]] = {}
    for index, model in scope_ok:
        key = (model.program_id, model.session_id, model.cmd_ts)
        if key in dedup:
            rejected.append(
                RejectionEntry(index=dedup[key][0], reason="intra_batch_duplicate")
            )
        dedup[key] = (index, model)

    # --- Materialise rows for the upsert. `model_dump(by_alias=False)` emits
    # column-name keys (Pydantic uses field names when by_alias is False,
    # even for fields declared with `Field(alias=...)`), which is exactly
    # what `pg_insert(UsageEvent).values(...)` binds against. `id` has no
    # analog on the wire; Core inserts don't apply the ORM default, so it is
    # generated here explicitly.
    upsert_rows: list[dict[str, Any]] = [
        {"id": str(uuid.uuid4()), **model.model_dump(by_alias=False)}
        for _index, model in dedup.values()
    ]
    valid_count = len(upsert_rows)

    # --- Pre-read to split inserted vs updated. `pg_insert(...).returning(...)`
    # could compute this with a Postgres-specific `(xmax = 0)` trick, but a
    # pre-read is portable, obvious, and bounded to one small SELECT. The
    # extra I/O is well inside the p95 budget (validate + upsert + program
    # rebuild ~= 2.5s residual, DATA-DESIGN.md § 8).
    existing_pairs: set[tuple[str, datetime]] = set()
    if upsert_rows:
        key_pairs = [(r["session_id"], r["cmd_ts"]) for r in upsert_rows]
        result = await db.execute(
            select(UsageEvent.session_id, UsageEvent.cmd_ts).where(
                UsageEvent.program_id == program_id,
                tuple_(UsageEvent.session_id, UsageEvent.cmd_ts).in_(key_pairs),
            )
        )
        existing_pairs = set(result.tuples().all())

    updated_count = sum(
        1 for r in upsert_rows if (r["session_id"], r["cmd_ts"]) in existing_pairs
    )
    inserted_count = valid_count - updated_count

    # --- Chunked upsert (FR-2 / C-1). All chunks share one transaction: the
    # session-manager (`get_db`) commits on success, rolls back on exception.
    # Whole-batch atomicity means a bind-limit overflow at chunk N does not
    # leave chunks 0..N-1 partially committed.
    for chunk in _chunks(upsert_rows, _MAX_ROWS_PER_INSERT):
        insert_stmt = pg_insert(UsageEvent).values(chunk)
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=["program_id", "session_id", "cmd_ts"],
            set_={
                col: getattr(insert_stmt.excluded, col) for col in _CONFLICT_UPDATE_COLUMNS
            },
        )
        await db.execute(stmt)

    await db.commit()

    # --- Program-scope rebuild synchronously in the request path (BED-05
    # D-05, unchanged). `_rebuild_transaction()` opens `session.begin()`
    # here because the session's transaction was just committed above -- the
    # session is idle at this point.
    program_result = await rebuild_program_rollups(db, program_id)
    rollup_summaries: dict[str, Any] = {
        "program": {
            "scope": program_result.scope,
            "program_id": program_result.program_id,
            "duration_ms": program_result.duration_ms,
            "event_count": program_result.event_count,
        }
    }

    log_ingest_write_completed(
        program_id=program_id,
        rows_received=rows_received,
        rows_inserted=inserted_count,
        rows_updated=updated_count,
        rows_rejected=len(rejected),
        duration_ms=elapsed_ms(start),
    )

    # --- Org-scope rebuild dispatch (D-01 / ADR-0012). This module NEVER
    # calls `rebuild_org_rollups` directly; the caller's hook is invoked
    # once, synchronously (the router's hook is a thin wrapper around
    # `background_tasks.add_task(...)`, which just schedules -- no I/O).
    # Called AFTER the response envelope is fully materialised so a hook
    # exception cannot corrupt what we return.
    on_org_rebuild()

    return IngestFilesResponse(
        received=rows_received,
        valid=valid_count,
        inserted=inserted_count,
        updated=updated_count,
        rejected=rejected,
        rollup_summaries=rollup_summaries,
    )


async def dispatch_org_rebuild() -> None:
    """FastAPI-BackgroundTasks-shaped wrapper around `rebuild_org_rollups`.

    Opens a FRESH `AsyncSession` from `SessionLocal` because the request-scoped
    session is closed by the time this fires (DATA-DESIGN.md § 5 / § 10).
    Catches every exception and logs `ingest_org_rollup_task_failed` with no
    PII -- no program_id (the org call has no program scope), no row content.
    The org rollup is idempotent and self-heals on the next successful ingest
    push anywhere in the system, so a swallowed exception here is the
    accepted degradation (DATA-DESIGN.md § 10 -- there is no retry to bound).
    Never re-raises: a BackgroundTask exception has no meaningful place to go
    once the response is already on the wire.
    """
    try:
        async with SessionLocal() as session:
            await rebuild_org_rollups(session)
    except Exception:  # noqa: BLE001 -- fire-and-forget, see docstring
        logger.exception("ingest_org_rollup_task_failed")


def elapsed_ms(start: float) -> int:
    """Elapsed milliseconds since `start` (a `time.perf_counter()` reading)."""
    return int((time.perf_counter() - start) * 1000)


def log_ingest_write_completed(
    *,
    program_id: str,
    rows_received: int,
    rows_inserted: int,
    rows_updated: int,
    rows_rejected: int,
    duration_ms: int,
) -> None:
    """Emit `ingest_write_completed` (FR-8 / C-7).

    Exactly this field allowlist -- `user`/`command`/`feature` and all row
    content are never emitted, not as structured fields and not interpolated
    into the message string. The keyword-only signature makes the allowlist
    part of the type contract -- a caller cannot silently smuggle an extra
    field via `**kwargs`. The allowlist itself is also exposed as
    `_LOG_FIELD_ALLOWLIST` so T-11 can diff a captured record against it.
    """
    logger.info(
        "ingest_write_completed",
        extra={
            "program_id": program_id,
            "rows_received": rows_received,
            "rows_inserted": rows_inserted,
            "rows_updated": rows_updated,
            "rows_rejected": rows_rejected,
            "duration_ms": duration_ms,
        },
    )


# -----------------------------------------------------------------------------
# Private helpers -- no downstream contract, internal to this module only.
# -----------------------------------------------------------------------------


def _classify_row_error(exc: ValidationError) -> str:
    """Turn an `ActivityRowIn` `ValidationError` into a caller-facing reason.

    Only inspects `type`/`loc` (which pydantic error kind, which field
    failed) -- never `input`/`ctx`, which pydantic's `.errors()` also exposes
    and which DO carry the raw offending value. `user`/`command`/`feature`
    values are PII or free-form text (`.claude/rules/security-baseline.md`)
    and must not appear anywhere in the response body.

    The vocabulary is `{"malformed_iso_date", "missing_required_field"}` --
    the only two per-row Pydantic outcomes `ActivityRowIn` produces (schema
    docstring). `intra_batch_duplicate` / `program_id_mismatch` are picked
    directly by the pipeline above, not here.
    """
    for err in exc.errors():
        etype = err.get("type", "")
        if etype == "missing":
            return "missing_required_field"
        loc = err.get("loc") or ()
        if loc and loc[0] in ("ts", "cmd_ts"):
            return "malformed_iso_date"
        msg = err.get("msg", "")
        if "malformed_iso_date" in msg:
            return "malformed_iso_date"
    # Everything else is treated as a missing/malformed-shape failure. The
    # schema surfaces its own `ValueError("malformed_iso_date")` on the two
    # timestamp fields; other pydantic errors are structural (missing/wrong
    # type on required fields) and land under this bucket.
    return "missing_required_field"


def _chunks(rows: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    """Yield successive `size`-length slices of `rows` (FR-2 / C-1).

    A generator, not a list comprehension: at 5000 rows and chunk size 2_730
    we produce at most two slices, but keeping this lazy also keeps memory
    bounded if a future story raises `_ENVELOPE_ROW_CAP`.
    """
    for i in range(0, len(rows), size):
        yield rows[i : i + size]
