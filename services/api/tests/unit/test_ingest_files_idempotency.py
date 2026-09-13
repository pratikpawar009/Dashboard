"""Integration tests for `POST /api/ingest/files` (ING-02 F-18 / T-13 --
ING-02-TC-01, tracker `pratikpawar009/Dashboard#293`).

Traces AC-1 (validate + upsert + program rebuild in the request path),
AC-3 (row-level malformed timestamp rejected without aborting siblings),
AC-4 (envelope `kind=activity` accepted), AC-5 (row rejection enumeration
with FR-3 vocabulary), AC-6 (idempotent re-post produces zero new rows +
identical program-scope summary), FR-1 (org-scope rebuild NOT in the sync
response body), FR-2 (chunked upsert commits), FR-3 (`intra_batch_duplicate`
reason emitted), FR-5 (bearer auth wiring resolves via `get_ingest_token`),
FR-8 / NFR-observability (single `ingest_write_completed` log per push whose
key set equals `_LOG_FIELD_ALLOWLIST` + `JSONFormatter` meta only).

Scope split (per PLAN.md § File plan): T-13 owns this file (happy-path,
idempotency, dedup, mixed rejection, rollup rebuild ran, log allowlist).
T-14 owns `test_ingest_files_auth_denial.py` (auth/authz matrix, 413 row-cap,
envelope-kind reject, PII discipline of response bodies). Per T-13's task
directive: do NOT add auth tests here, do NOT add perf tests, do NOT mock
the DB -- exercise the real `POST` handler against the disposable test
Postgres via the same `_db_override`/`async_client_for` pattern
`tests/unit/test_manifest_ingest.py` established.

BackgroundTask stub (see `_stub_dispatch_org_rebuild` below): the shipped
router wires `on_org_rebuild=lambda: background_tasks.add_task(
dispatch_org_rebuild)`. `dispatch_org_rebuild` opens its OWN
`SessionLocal()` bound to `settings.database_url` at import time -- the
DEV database, not the disposable test one (`tests/conftest.py`'s
`AlembicRunner` only monkeypatches `settings.database_url` around the
alembic call, not around the request). httpx `ASGITransport` executes
BackgroundTasks before `client.post()` returns, so without the stub the
dev DB gets an incidental org-rollup rebuild every test. The stub is
autouse and PATH-BOUND to the router module (`app.api.ingest_files`), not
the service module -- the router imports the symbol at its own module
scope, and the lambda's late-bound lookup resolves against that module,
not `app.services.activity_ingest`.

Log-capture idiom mirrored from `test_ingest_write_completed_pii.py` (T-11):
attach a `_RecordCapturingHandler` to the real, named
`app.services.activity_ingest` logger and force-reset `.disabled=False` /
`.propagate=False` for the test's duration. `migrations/env.py:19`'s
`fileConfig(disable_existing_loggers=True)` permanently disables loggers
once `test_migrations.py` runs in the same session; `caplog` is blind to
that (see T-11's docstring for the full trap).

Synthetic PII (`.claude/rules/security-baseline.md`): every user/session/
command value is a placeholder using RFC 2606's reserved `.invalid` TLD or
an obviously-fabricated slug -- never anything resembling a real person.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, contextmanager
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import ingest_files as ingest_files_router
from app.core.db import get_db
from app.core.logging import JSONFormatter
from app.models.ingestion import IngestToken, UsageEvent
from app.models.rollup import ProgramSummary
from tests.conftest import AlembicRunner

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

_INGEST_FILES_PATH = "/api/ingest/files"

# Pin FR-8's allowlist literally (T-11 keeps the service-side frozenset as
# runtime source of truth; snapshotting it here as well means any drift on
# either side trips a test regardless of which side moves first).
_FR8_ALLOWLIST_LITERAL = frozenset(
    {
        "program_id",
        "rows_received",
        "rows_inserted",
        "rows_updated",
        "rows_rejected",
        "duration_ms",
    }
)
_JSON_FORMATTER_META_FIELDS = {"timestamp", "level", "logger", "message"}
_EXPECTED_LOG_KEY_SET = _FR8_ALLOWLIST_LITERAL | _JSON_FORMATTER_META_FIELDS


# -----------------------------------------------------------------------------
# App + DB-override scaffold -- same shape as `test_manifest_ingest.py`
# (`_db_override` / `_build_manifest_app`): the override yields the caller's
# own `test_session` so seeding, the HTTP call, and post-call verification
# queries share one live connection to the disposable test DB.
# -----------------------------------------------------------------------------


def _db_override(session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _get_db() -> AsyncIterator[AsyncSession]:
        yield session

    return _get_db


def _build_ingest_files_app(
    build_app: Callable[..., FastAPI], test_session: AsyncSession
) -> FastAPI:
    app = build_app()
    app.dependency_overrides[get_db] = _db_override(test_session)
    return app


# -----------------------------------------------------------------------------
# Ingest-token seeding helper -- mirrors `test_manifest_ingest.py::
# _seed_ingest_token` (duplicated locally per this repo's per-file test-helper
# convention).
# -----------------------------------------------------------------------------


async def _seed_ingest_token(
    test_session: AsyncSession, *, label: str, allowed_program_ids: list[str]
) -> str:
    """Seed one `ingest_tokens` row and return its raw (pre-hash) token."""
    raw_token = "hrn_pat_" + secrets.token_hex(32)
    row = IngestToken(
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        label=label,
        user_email="ingest-owner@example.invalid",
        allowed_program_ids=allowed_program_ids,
    )
    test_session.add(row)
    await test_session.commit()
    return raw_token


# -----------------------------------------------------------------------------
# Row builder -- wire shape from `docs/requirements/api.md#ingest-files-api`.
# `ts` defaults to `cmd_ts` so a malformed `cmd_ts` also renders `ts`
# malformed; that matches how a real producer would emit the row, and
# `_classify_row_error` will map either `ts`/`cmd_ts` loc to
# `malformed_iso_date`.
# -----------------------------------------------------------------------------


def _row(
    *,
    program_id: str,
    session_id: str,
    cmd_ts: str,
    ts: str | None = None,
    user: str = "zzyzx.contributor@example.invalid",
    command: str = "zzyzx-command",
    kind: str = "chat",
    duration_s: int = 1,
    outcome: str = "success",
    total: int = 100,
) -> dict[str, Any]:
    return {
        "program_id": program_id,
        "ts": ts if ts is not None else cmd_ts,
        "cmd_ts": cmd_ts,
        "user": user,
        "session_id": session_id,
        "kind": kind,
        "command": command,
        "duration_s": duration_s,
        "outcome": outcome,
        "total": total,
    }


async def _count_usage_events(session: AsyncSession, program_id: str) -> int:
    result = await session.execute(
        sa.select(sa.func.count(UsageEvent.id)).where(UsageEvent.program_id == program_id)
    )
    return int(result.scalar_one())


# -----------------------------------------------------------------------------
# BackgroundTask stub -- see module docstring for why (`dispatch_org_rebuild`
# opens SessionLocal() -> dev DB, not the disposable test DB). Autouse:
# every test in this file goes through the router, therefore every test needs
# this stub.
# -----------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _stub_dispatch_org_rebuild(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop() -> None:
        return None

    monkeypatch.setattr(ingest_files_router, "dispatch_org_rebuild", _noop)


# -----------------------------------------------------------------------------
# Log capture -- mirrored from T-11's `_RecordCapturingHandler` /
# `_isolated_activity_ingest_logger`. See module docstring for the
# disabled-logger trap this works around.
# -----------------------------------------------------------------------------


class _RecordCapturingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _isolated_activity_ingest_logger() -> Iterator[logging.Logger]:
    logger = logging.getLogger("app.services.activity_ingest")
    original_disabled = logger.disabled
    original_propagate = logger.propagate
    original_level = logger.level
    logger.disabled = False
    logger.propagate = False
    logger.setLevel(logging.INFO)
    try:
        yield logger
    finally:
        logger.disabled = original_disabled
        logger.propagate = original_propagate
        logger.setLevel(original_level)


@pytest.fixture
def activity_ingest_logger_records() -> Iterator[list[logging.LogRecord]]:
    with _isolated_activity_ingest_logger() as logger:
        handler = _RecordCapturingHandler()
        logger.addHandler(handler)
        try:
            yield handler.records
        finally:
            logger.removeHandler(handler)


# =============================================================================
# ING-02-TC-01 -- Test 1: happy-path insert then idempotent update.
# =============================================================================


@pytest.mark.asyncio
async def test_ingest_files_idempotent_insert_then_update_happy_path_tc01(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """Two identical POSTs of a 3-row activity batch:
    - First returns 200 with `inserted=3, updated=0` and no `rejected`.
    - Second returns 200 with `inserted=0, updated=3` and no `rejected`
      (idempotent upsert per AC-6).
    - `usage_events` row count stays at 3 across both pushes (no duplicates).
    - Response envelope carries a program-scope rollup summary keyed
      correctly and no org-scope entry (FR-1 / ADR-0012 -- org rebuild
      runs out-of-band via BackgroundTasks).
    """
    program_id = "PROG-INGEST-T13-A"
    token = await _seed_ingest_token(
        test_session, label="tc01-happy", allowed_program_ids=[program_id]
    )
    app = _build_ingest_files_app(build_app, test_session)

    rows = [
        _row(
            program_id=program_id,
            session_id=f"S-{i:03d}",
            cmd_ts=f"2026-09-11T12:00:{i:02d}Z",
        )
        for i in range(3)
    ]
    payload = {"program_id": program_id, "kind": "activity", "rows": rows}
    auth = {"Authorization": f"Bearer {token}"}

    async with async_client_for(app) as client:
        resp_a = await client.post(_INGEST_FILES_PATH, json=payload, headers=auth)
        assert resp_a.status_code == 200, resp_a.text
        body_a = resp_a.json()
        assert body_a["received"] == 3
        assert body_a["valid"] == 3
        assert body_a["inserted"] == 3
        assert body_a["updated"] == 0
        assert body_a["rejected"] == []

        # FR-1 / ADR-0012: program scope reported in the sync response;
        # org scope is scheduled out-of-band and MUST NOT appear here.
        summaries = body_a["rollup_summaries"]
        assert set(summaries.keys()) == {"program"}
        assert summaries["program"]["scope"] == "program"
        assert summaries["program"]["program_id"] == program_id
        assert summaries["program"]["event_count"] == 3

        resp_b = await client.post(_INGEST_FILES_PATH, json=payload, headers=auth)
        assert resp_b.status_code == 200, resp_b.text
        body_b = resp_b.json()
        assert body_b["received"] == 3
        assert body_b["valid"] == 3
        assert body_b["inserted"] == 0
        assert body_b["updated"] == 3
        assert body_b["rejected"] == []

    assert await _count_usage_events(test_session, program_id) == 3


# =============================================================================
# ING-02-TC-01 -- Test 2: intra-batch dedup within a single request (AC-4 /
# FR-3 last-wins vocabulary).
# =============================================================================


@pytest.mark.asyncio
async def test_ingest_files_intra_batch_dedup_last_wins_marks_earlier_index_rejected(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """5-row batch, rows at indices 0 and 4 share `(program_id, session_id,
    cmd_ts)`. Per `activity_ingest._dedup` (last-wins, module docstring
    FR-3 / C-2), the LATER occurrence wins and the EARLIER index lands in
    `rejected[]` with reason `intra_batch_duplicate`. Only 4 rows are
    committed to `usage_events`.
    """
    program_id = "PROG-INGEST-T13-B"
    token = await _seed_ingest_token(
        test_session, label="tc01-dedup", allowed_program_ids=[program_id]
    )
    app = _build_ingest_files_app(build_app, test_session)

    dup_session = "S-DUP"
    dup_cmd_ts = "2026-09-11T12:00:00Z"
    rows = [
        _row(program_id=program_id, session_id=dup_session, cmd_ts=dup_cmd_ts, command="early"),
        _row(program_id=program_id, session_id="S-A", cmd_ts="2026-09-11T12:00:01Z"),
        _row(program_id=program_id, session_id="S-B", cmd_ts="2026-09-11T12:00:02Z"),
        _row(program_id=program_id, session_id="S-C", cmd_ts="2026-09-11T12:00:03Z"),
        _row(program_id=program_id, session_id=dup_session, cmd_ts=dup_cmd_ts, command="late-wins"),
    ]
    payload = {"program_id": program_id, "kind": "activity", "rows": rows}
    auth = {"Authorization": f"Bearer {token}"}

    async with async_client_for(app) as client:
        resp = await client.post(_INGEST_FILES_PATH, json=payload, headers=auth)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["received"] == 5
        assert body["valid"] == 4
        assert body["inserted"] == 4
        assert body["updated"] == 0
        assert body["rejected"] == [{"index": 0, "reason": "intra_batch_duplicate"}]

    assert await _count_usage_events(test_session, program_id) == 4


# =============================================================================
# ING-02-TC-01 -- Test 3: mixed accept + `malformed_iso_date` rejection
# (AC-3 partial -- row-level rejection does not abort siblings, FR-3).
# =============================================================================


@pytest.mark.asyncio
async def test_ingest_files_mixed_batch_malformed_iso_date_rejects_only_bad_row(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """4-row batch, index 1 carries an unparseable `cmd_ts`. The row is
    rejected with reason `malformed_iso_date` (FR-3 / AC-5 vocabulary via
    `ActivityRowIn._parse_iso_timestamp` + `_classify_row_error`); the
    three valid siblings commit. Response is 200, not 400 -- row-level
    failure is NOT a request-level abort (contrast: envelope `kind` and
    row-cap, which T-14 covers).
    """
    program_id = "PROG-INGEST-T13-C"
    token = await _seed_ingest_token(
        test_session, label="tc01-mixed", allowed_program_ids=[program_id]
    )
    app = _build_ingest_files_app(build_app, test_session)

    rows = [
        _row(program_id=program_id, session_id="S-M1", cmd_ts="2026-09-11T12:00:00Z"),
        _row(program_id=program_id, session_id="S-BAD", cmd_ts="not-a-timestamp"),
        _row(program_id=program_id, session_id="S-M2", cmd_ts="2026-09-11T12:00:02Z"),
        _row(program_id=program_id, session_id="S-M3", cmd_ts="2026-09-11T12:00:03Z"),
    ]
    payload = {"program_id": program_id, "kind": "activity", "rows": rows}
    auth = {"Authorization": f"Bearer {token}"}

    async with async_client_for(app) as client:
        resp = await client.post(_INGEST_FILES_PATH, json=payload, headers=auth)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["received"] == 4
        assert body["valid"] == 3
        assert body["inserted"] == 3
        assert body["updated"] == 0
        assert body["rejected"] == [{"index": 1, "reason": "malformed_iso_date"}]

    assert await _count_usage_events(test_session, program_id) == 3


# =============================================================================
# ING-02-TC-01 -- Test 4: program-scope rollup was rebuilt in the request
# path (AC-5 via BED-05 contract). Org-scope rebuild ran out-of-band via
# BackgroundTasks (D-01 / ADR-0012) and is NOT asserted here -- the stub
# above short-circuits it, matching the ADR's "sync response only guarantees
# program-scope" contract.
# =============================================================================


@pytest.mark.asyncio
async def test_ingest_files_program_scope_rollup_rebuilt_after_successful_push(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """After a 3-row successful push, `program_summary` gains a row for the
    program (BED-05 `rebuild_program_rollups` runs synchronously in the
    request path, D-01) and the response body's
    `rollup_summaries.program.event_count` matches the inserted count.
    """
    program_id = "PROG-INGEST-T13-D"
    token = await _seed_ingest_token(
        test_session, label="tc01-rollup", allowed_program_ids=[program_id]
    )
    app = _build_ingest_files_app(build_app, test_session)

    inserted_count = 3
    rows = [
        _row(
            program_id=program_id,
            session_id=f"S-R{i}",
            cmd_ts=f"2026-09-11T12:00:{i:02d}Z",
        )
        for i in range(inserted_count)
    ]
    payload = {"program_id": program_id, "kind": "activity", "rows": rows}
    auth = {"Authorization": f"Bearer {token}"}

    async with async_client_for(app) as client:
        resp = await client.post(_INGEST_FILES_PATH, json=payload, headers=auth)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["inserted"] == inserted_count
        assert body["rollup_summaries"]["program"]["event_count"] == inserted_count

    summary_row = (
        await test_session.execute(
            sa.select(ProgramSummary).where(ProgramSummary.program_id == program_id)
        )
    ).scalar_one_or_none()
    assert summary_row is not None, (
        "program_summary row missing after program-scope rebuild (AC-5 / BED-05)"
    )


# =============================================================================
# ING-02-TC-01 -- Test 5: exactly one `ingest_write_completed` log record per
# successful push; the record's key set equals FR-8's allowlist plus
# `JSONFormatter` meta only. NFR-observability.
# =============================================================================


@pytest.mark.asyncio
async def test_ingest_files_emits_one_write_completed_log_with_fr8_allowlist_fields_only(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    activity_ingest_logger_records: list[logging.LogRecord],
) -> None:
    """One POST -> exactly one `ingest_write_completed` LogRecord. The
    formatted key set equals `_LOG_FIELD_ALLOWLIST` | JSONFormatter meta;
    a stray extra field (e.g. `token_label`, `user`, `command`) fails
    here just like a missing allowlist entry.
    """
    program_id = "PROG-INGEST-T13-E"
    token = await _seed_ingest_token(
        test_session, label="tc01-log", allowed_program_ids=[program_id]
    )
    app = _build_ingest_files_app(build_app, test_session)

    row_count = 2
    rows = [
        _row(
            program_id=program_id,
            session_id=f"S-L{i}",
            cmd_ts=f"2026-09-11T12:00:{i:02d}Z",
        )
        for i in range(row_count)
    ]
    payload = {"program_id": program_id, "kind": "activity", "rows": rows}
    auth = {"Authorization": f"Bearer {token}"}

    async with async_client_for(app) as client:
        resp = await client.post(_INGEST_FILES_PATH, json=payload, headers=auth)
        assert resp.status_code == 200, resp.text

    write_events = [
        r for r in activity_ingest_logger_records if r.getMessage() == "ingest_write_completed"
    ]
    assert len(write_events) == 1
    formatted = json.loads(JSONFormatter().format(write_events[0]))

    assert set(formatted.keys()) == _EXPECTED_LOG_KEY_SET
    assert formatted["program_id"] == program_id
    assert formatted["message"] == "ingest_write_completed"
    assert formatted["rows_received"] == row_count
    assert formatted["rows_inserted"] == row_count
    assert formatted["rows_updated"] == 0
    assert formatted["rows_rejected"] == 0
    assert isinstance(formatted["duration_ms"], int)
    assert formatted["duration_ms"] >= 0
