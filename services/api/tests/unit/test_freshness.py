"""Unit tests for `app/services/freshness.py`'s `FreshnessAccessor` --
BED-04-TC-01, BED-04-TC-02 (`docs/test-cases/BED-04.json`), plus internal
cache-mechanics coverage authored per that file's `coverage_audit.audit_notes`
("unit-shaped cases... belong in docs/features/BED-04/tasks.json"). TC-03
(warm-read p95 / TTL-expiry boundary) belongs to
`tests/perf/test_freshness_perf.py`, not here.

Fixture split: TC-01/TC-02 need a real `system_metadata` row (or its absence)
and run against the disposable test Postgres via `migrated_db`/`test_engine`/
`test_session` (`tests/conftest.py`), passing a REAL
`async_sessionmaker(bind=test_engine)` -- mirrors
`tests/unit/test_persona_resolver.py`'s TC-03/TC-14 live-DB pattern. The
cache-mechanics tests are pure-mock -- no live DB -- via `FakeSessionFactory`,
a hand-rolled stand-in mirroring that same file's `_FakeRow`/`_FakeResult`
shapes but returning a `SystemMetadata`-shaped row (`.last_successful_run_at`)
instead of a persona row.

Log-capture idiom: a `_RecordCapturingHandler` attached directly to the real
`app.services.freshness` logger, force-enabled and depropagated --
`test_persona_resolver.py`'s documented idiom, immune to both the
`configure_logging()`+`capsys` stdout trap and Alembic's
`fileConfig(disable_existing_loggers=True)` sweep.

Imported, never re-typed: `_NOT_RUN_MESSAGE` is imported directly from
`app.services.freshness` (not `app.services`, which does not re-export it --
D-01/T-04) so a future edit to the constant fails these assertions instead of
silently passing against a stale duplicate literal.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import app.services.freshness as freshness
from app.core.logging import JSONFormatter
from app.models.ingestion import SystemMetadata
from app.services.freshness import _NOT_RUN_MESSAGE, _QUERY_TIMEOUT_MESSAGE, FreshnessAccessor
from tests.conftest import AlembicRunner

_SEEDED_AT = datetime(2026, 9, 3, 9, 15, 0, tzinfo=UTC)


# -----------------------------------------------------------------------------
# Log capture -- mirrors test_persona_resolver.py's documented idiom.
# -----------------------------------------------------------------------------


class _RecordCapturingHandler(logging.Handler):
    """Stores emitted LogRecord instances verbatim, without formatting them."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _capture_logger(name: str, level: int = logging.WARNING) -> Iterator[list[logging.LogRecord]]:
    logger = logging.getLogger(name)
    original_disabled = logger.disabled
    original_propagate = logger.propagate
    original_level = logger.level
    logger.disabled = False
    logger.propagate = False
    logger.setLevel(level)
    handler = _RecordCapturingHandler()
    logger.addHandler(handler)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)
        logger.disabled = original_disabled
        logger.propagate = original_propagate
        logger.setLevel(original_level)


# -----------------------------------------------------------------------------
# BED-04-TC-01 (AC-1) -- seeded row returns a timezone-aware datetime.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seeded_row_returns_timezone_aware_datetime_tc01(
    migrated_db: AlembicRunner,
    test_engine: AsyncEngine,
    test_session: AsyncSession,
) -> None:
    """BED-04-TC-01."""
    await test_session.execute(
        sa.insert(SystemMetadata).values(key="ingestion", last_successful_run_at=_SEEDED_AT)
    )
    await test_session.commit()

    accessor = FreshnessAccessor(
        session_factory=async_sessionmaker(bind=test_engine, expire_on_commit=False)
    )

    with _capture_logger("app.services.freshness") as records:
        result = await accessor.get_last_successful_run()

    assert isinstance(result, datetime)
    assert result.tzinfo is not None
    assert result.utcoffset() == timedelta(0)
    assert result == _SEEDED_AT
    assert records == []  # no warning-level log on this path


# -----------------------------------------------------------------------------
# BED-04-TC-02 (FR-1) -- absent row raises the exact message and logs once.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_absent_row_raises_exact_message_and_logs_warning_tc02(
    migrated_db: AlembicRunner,
    test_engine: AsyncEngine,
    test_session: AsyncSession,
) -> None:
    """BED-04-TC-02."""
    precondition = await test_session.execute(
        sa.select(SystemMetadata).where(SystemMetadata.key == "ingestion")
    )
    assert precondition.scalar_one_or_none() is None  # step 1: table has no 'ingestion' row

    accessor = FreshnessAccessor(
        session_factory=async_sessionmaker(bind=test_engine, expire_on_commit=False)
    )

    with _capture_logger("app.services.freshness") as records:
        with pytest.raises(HTTPException) as exc_info:
            await accessor.get_last_successful_run()

    assert exc_info.value.status_code == 500
    assert str(exc_info.value.detail) == _NOT_RUN_MESSAGE

    assert len(records) == 1
    record = records[0]
    assert record.levelname == "WARNING"
    assert record.getMessage() == _NOT_RUN_MESSAGE

    # No PII: the emitted payload's key set is exactly JSONFormatter's
    # first-class fields plus the internal `reason` code -- no user
    # identifier, email, session id, or request content.
    payload = json.loads(JSONFormatter().format(record))
    assert set(payload.keys()) == {"timestamp", "level", "logger", "message", "reason"}
    assert payload["reason"] == "system_metadata row not found"


# -----------------------------------------------------------------------------
# Pure-mock `session_factory` stand-in (no live DB) -- mirrors
# test_persona_resolver.py's FakeSessionFactory shape, returning a
# SystemMetadata-shaped row instead of a persona row.
# -----------------------------------------------------------------------------


class _FakeRow:
    def __init__(self, last_successful_run_at: datetime) -> None:
        self.last_successful_run_at = last_successful_run_at


class _FakeResult:
    def __init__(self, row: _FakeRow | None) -> None:
        self._row = row

    def scalar_one_or_none(self) -> _FakeRow | None:
        return self._row


class _FakeSessionCtx:
    def __init__(self, row: _FakeRow | None, delay_seconds: float) -> None:
        self._row = row
        self._delay_seconds = delay_seconds

    async def __aenter__(self) -> _FakeSessionCtx:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> None:
        return None

    async def execute(self, _stmt: Any) -> _FakeResult:
        # Always yields to the event loop, even with delay_seconds=0.0 --
        # `asyncio.sleep(0)` still suspends the current task, letting other
        # concurrent callers genuinely interleave. A fake that never awaits
        # anything would let the first caller run to completion before a
        # second one even starts, making a concurrency assertion vacuous.
        await asyncio.sleep(self._delay_seconds)
        return _FakeResult(self._row)


class FakeSessionFactory:
    """`call_count` records how many times the underlying query was actually
    issued -- every "warm hit skipped the DB" / "N concurrent calls collapsed
    to one query" assertion below reads it directly rather than trusting that
    `get_last_successful_run()` merely returned the right value.

    `rows` is consumed by call index (clamped to the last entry once
    exhausted), letting a test vary what successive calls see -- e.g. D-03's
    absent-then-present sequence.
    """

    def __init__(
        self,
        rows: Sequence[_FakeRow | None] = (None,),
        *,
        delay_seconds: float = 0.0,
    ) -> None:
        self._rows = list(rows)
        self.delay_seconds = delay_seconds
        self.call_count = 0

    def __call__(self) -> _FakeSessionCtx:
        index = min(self.call_count, len(self._rows) - 1)
        row = self._rows[index]
        self.call_count += 1
        return _FakeSessionCtx(row, self.delay_seconds)


def _accessor(factory: FakeSessionFactory) -> FreshnessAccessor:
    return FreshnessAccessor(session_factory=cast(async_sessionmaker[AsyncSession], factory))


# -----------------------------------------------------------------------------
# Cache-mechanics -- warm hit does zero I/O.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_warm_cache_hit_performs_zero_session_factory_calls() -> None:
    factory = FakeSessionFactory([_FakeRow(_SEEDED_AT)])
    accessor = _accessor(factory)

    first = await accessor.get_last_successful_run()
    second = await accessor.get_last_successful_run()

    assert first == second == _SEEDED_AT
    assert factory.call_count == 1  # the second call performed zero factory calls


# -----------------------------------------------------------------------------
# Cache-mechanics -- lock bounds N concurrent cold calls to one SELECT (D-01).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_cold_calls_collapse_to_one_underlying_select() -> None:
    factory = FakeSessionFactory([_FakeRow(_SEEDED_AT)], delay_seconds=0.01)
    accessor = _accessor(factory)

    tasks = [asyncio.create_task(accessor.get_last_successful_run()) for _ in range(10)]
    results = await asyncio.gather(*tasks)

    assert results == [_SEEDED_AT] * 10
    assert factory.call_count == 1


# -----------------------------------------------------------------------------
# Cache-mechanics -- no negative-caching: a row-absent raise is never cached,
# so the next call re-queries and can succeed (D-03).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_negative_caching_absent_row_not_cached() -> None:
    updated = datetime(2026, 9, 3, 9, 47, 0, tzinfo=UTC)
    factory = FakeSessionFactory([None, _FakeRow(updated)])
    accessor = _accessor(factory)

    with pytest.raises(HTTPException) as exc_info:
        await accessor.get_last_successful_run()
    assert exc_info.value.status_code == 500

    result = await accessor.get_last_successful_run()

    assert result == updated
    assert factory.call_count == 2  # the absent outcome was not cached -- re-queried


# -----------------------------------------------------------------------------
# Query timeout -- review finding F-1 (REVIEW.md, HIGH): the `system_metadata`
# read had no explicit timeout, so a stalled connection would hang forever
# inside `self._lock`, blocking every concurrent caller. Unit-shaped, so it
# lives here rather than as a `docs/test-cases/BED-04.json` case -- that file
# is user-capped at 3 cases and its own `coverage_audit.audit_notes` routes
# unit-shaped coverage to `tasks.json`, not to itself; this was not an
# oversight.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stalled_read_times_out_raises_500_and_is_not_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fix for review finding F-1 (D-04, DECISIONS.md). Patches
    `_QUERY_TIMEOUT_SECONDS` down to keep the suite fast rather than waiting
    out the real 3.0s bound; the stalling `FakeSessionFactory`'s delay is set
    just above the patched value so the timeout fires deterministically.
    """
    monkeypatch.setattr(freshness, "_QUERY_TIMEOUT_SECONDS", 0.01)
    factory = FakeSessionFactory([_FakeRow(_SEEDED_AT)], delay_seconds=0.05)
    accessor = _accessor(factory)

    with _capture_logger("app.services.freshness") as records:
        with pytest.raises(HTTPException) as exc_info:
            await accessor.get_last_successful_run()

    assert exc_info.value.status_code == 500
    assert str(exc_info.value.detail) == _QUERY_TIMEOUT_MESSAGE

    assert len(records) == 1
    record = records[0]
    assert record.levelname == "WARNING"
    assert record.getMessage() == _QUERY_TIMEOUT_MESSAGE

    # No PII -- same allowlisted key set as the row-absent path.
    payload = json.loads(JSONFormatter().format(record))
    assert set(payload.keys()) == {"timestamp", "level", "logger", "message", "reason"}

    # Not cached: with the stall removed, the next call re-queries and succeeds.
    factory.delay_seconds = 0.0
    result = await accessor.get_last_successful_run()

    assert result == _SEEDED_AT
    assert factory.call_count == 2  # 1 timed-out attempt + 1 successful re-query
