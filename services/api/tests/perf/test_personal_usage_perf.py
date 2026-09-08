"""Performance test for GET /api/personal-usage/{user_id} --
SHP-02-NFR-performance (Condition C-1): a bounded 3-SELECT query-count
budget (DECISIONS.md D-01 -- 2 SELECTs against `user_sessions`, 1 against
`usage_events`) and the handler's own duration under NFR-002's <=2s budget,
across all 3 supported `range` values.

Structure mirrors `tests/perf/test_overview_perf.py` exactly, per this
task's own file-plan reason: real `create_app()` (`build_app`/
`async_client_for`, `tests/conftest.py`), a bearer token minted via
`POST /auth/dev-bypass`, a `before_cursor_execute` query-count spy on
`test_engine.sync_engine`, the `production_logging` fixture, and plain
`time.perf_counter()` -- no new benchmark tool/runner/dependency.

Self-view path only: `app/api/personal_usage.py` calls
`individual_usage_visibility(current_user, user_id)` with `user_id ==
current_user.user_id` for every request this test drives, which
short-circuits on `app/core/rbac.py`'s self path BEFORE any persona
resolution and BEFORE any log call -- mirroring `test_overview_perf.py`'s
own note that `program_visibility` needs no persona-resolver stub, and
`tests/unit/test_personal_usage.py`'s module docstring on why this
endpoint's self-view path never touches the persona resolver. A dev-bypass
token always mints a fresh `uuid4()` `sub` claim (`app/auth/dev_bypass.py`)
with no field to override it -- this file, like `test_personal_usage.py`,
mints the token FIRST and decodes its own `sub` back out (unverified -- the
token was just minted in-process, there is nothing to distrust) to use as
the real seeded user id.

Query-count spy: scoped to SELECT statements referencing `user_sessions` OR
`usage_events` (DECISIONS.md D-01's exact 3-SELECT budget --
`fetch_card_totals`/`fetch_daily_token_series` query `user_sessions`,
`fetch_commands_breakdown` queries `usage_events`), word-boundary regex
mirroring `test_overview_perf.py`'s own `_PROGRAM_SUMMARY_RE`/
`tests/unit/test_rollup_rebuild_query_plan.py::_count_usage_events_selects`.
Always detached in a `finally` so it can never leak into sibling tests
sharing the session-scoped `test_engine` fixture.

`production_logging` fixture: copied verbatim from `test_overview_perf.py`
-- same rationale (a real handler must be attached so an INFO-level call
pays its real formatting/write cost instead of short-circuiting at
`Logger.isEnabledFor(INFO)`). A second, LOCAL handler is attached directly
to `app.core.rbac`'s logger to capture any emitted `LogRecord` for the
zero-denial-events / no-PII assertions below; like `test_overview_perf.py`'s
own local capture (and UNLIKE `test_personal_usage.py::_capture_rbac_
logger`'s isolated `propagate=False` capture), `propagate` is left at its
existing value so a record -- if the self-view contract were ever broken --
would still pay the real root-handler formatting/write cost the
`production_logging` fixture exists to measure.

One test function, parametrized over `range` in {"7d", "30d", "90d"} --
three seeded scenarios, each with in-range and out-of-range rows for both
tables so every one of the 3 budgeted SELECTs does real, non-trivial work.

Honest measurement (this convention is `test_overview_perf.py`'s own): if a
budget is missed, this reports the actual measured count/duration for
escalation -- never loosens the budget, never adds a warmup/retry to hide
the number. A missed SELECT-count budget is a real defect signal (an N+1 or
a stray query), not a tuning problem, per this task's own instructions.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core import rbac as rbac_module
from app.core.db import get_db
from app.core.logging import JSONFormatter, configure_logging
from app.models.ingestion import UsageEvent
from app.models.rollup import UserSessions
from tests.conftest import AlembicRunner

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

# SHP-02-NFR-performance test_data -- do not relax (DECISIONS.md D-01, task T-10 notes).
QUERY_COUNT_BUDGET = 3
HANDLER_DURATION_BUDGET_MS = 2000.0

_RANGE_DAYS: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90}
_FIXTURE_PROGRAM_ID = "prog-shp02-perf-fixture"
_USER_SESSIONS_OR_USAGE_EVENTS_RE = re.compile(r"\b(user_sessions|usage_events)\b", re.IGNORECASE)


@pytest.fixture
def production_logging() -> Iterator[None]:
    """Configure the same JSON-stdout logging `create_app()` sets up at
    import time (`app/core/logging.py::configure_logging`), then restore the
    previous root-logger state so this doesn't leak into other test files
    sharing this pytest session.

    Copied from `test_overview_perf.py`/`test_programs_perf.py` -- identical
    rationale: without a real handler attached, an INFO-level call
    short-circuits at `Logger.isEnabledFor(INFO)` before any formatting or
    I/O, understating what a deployed process actually pays. Level is forced
    to INFO explicitly (not left to `settings.log_level`) so the measurement
    is deterministic regardless of a local `.env`'s `LOG_LEVEL` override.
    """
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    configure_logging()
    root.setLevel(logging.INFO)
    try:
        yield
    finally:
        root.handlers = original_handlers
        root.setLevel(original_level)


class _RecordCapturingHandler(logging.Handler):
    """Stores emitted `LogRecord` instances verbatim, without formatting them.

    Structurally copied from `tests/perf/test_overview_perf.py::_RecordCapturingHandler`.
    """

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _capture_rbac_logger() -> Iterator[list[logging.LogRecord]]:
    """Captures records from the real `app.core.rbac` logger, IN ADDITION to
    the root stdout handler `production_logging` installs.

    `logger.disabled` is force-reset to `False` -- `migrated_db`'s Alembic
    upgrade runs `env.py`'s `fileConfig(disable_existing_loggers=True)`
    sweep (Alembic's own template boilerplate), which disables every
    already-imported logger not explicitly named in `alembic.ini`, including
    this module's (imported at this test file's collection time). Same
    gotcha `tests/perf/test_overview_perf.py::_capture_overview_logger` and
    `tests/unit/test_personal_usage.py::_capture_rbac_logger` both document.

    Unlike `test_personal_usage.py`'s own `_capture_rbac_logger`, `propagate`
    is left at its existing value (default `True`): a record must still
    reach the root handler and pay the real formatting/write cost
    `production_logging` exists to measure. This handler exists solely to
    inspect record content afterward.
    """
    logger = logging.getLogger(rbac_module.__name__)
    original_disabled = logger.disabled
    original_level = logger.level
    logger.disabled = False
    logger.setLevel(logging.INFO)
    handler = _RecordCapturingHandler()
    logger.addHandler(handler)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)
        logger.disabled = original_disabled
        logger.setLevel(original_level)


@dataclass
class _SelectCounter:
    """Captures every SELECT statement referencing `user_sessions` or
    `usage_events` seen while this counter's context manager is active."""

    count: int = 0
    statements: list[str] = field(default_factory=list)


@contextmanager
def _count_personal_usage_selects(engine: AsyncEngine) -> Iterator[_SelectCounter]:
    """Attach a `before_cursor_execute` listener to `engine.sync_engine` for
    the duration of the `with` block, counting SELECTs against
    `user_sessions` OR `usage_events` combined (DECISIONS.md D-01's 3-SELECT
    budget spans both tables).

    Mirrors `tests/perf/test_overview_perf.py::_count_program_summary_selects`.
    Detaches in `finally` so the listener cannot leak into sibling tests that
    share the session-scoped `test_engine` fixture.
    """
    counter = _SelectCounter()
    sync_engine = engine.sync_engine

    def _before_cursor_execute(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        is_select = statement.strip().upper().startswith("SELECT")
        if is_select and _USER_SESSIONS_OR_USAGE_EVENTS_RE.search(statement):
            counter.count += 1
            counter.statements.append(statement)

    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield counter
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before_cursor_execute)


def _decode_unverified_claims(token: str) -> dict[str, Any]:
    """Read a JWT's payload claims WITHOUT verifying its signature.

    Mirrors `tests/unit/test_personal_usage.py::_decode_unverified_claims`
    (same base64/JSON segment decode) -- the token was just minted
    in-process by this same test, so there is nothing to distrust.
    """
    payload_segment = token.split(".")[1]
    padding = "=" * (-len(payload_segment) % 4)
    return json.loads(base64.urlsafe_b64decode(payload_segment + padding))


async def _mint_dev_bypass_token(client: AsyncClient) -> tuple[str, str]:
    """`POST /auth/dev-bypass` and return `(access_token, user_id)`, where
    `user_id` is the token's own `sub` claim -- see module docstring."""
    resp = await client.post("/auth/dev-bypass", json={})
    assert resp.status_code == 200, resp.text
    token = str(resp.json()["access_token"])
    return token, str(_decode_unverified_claims(token)["sub"])


def _user_session_row(
    *, user_id: str, days_ago: int, tokens: int, duration_seconds: int, now: datetime
) -> dict[str, Any]:
    """One `user_sessions` row with every NOT NULL column
    (`app/models/rollup.py::UserSessions`) explicitly set."""
    return {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "program_id": _FIXTURE_PROGRAM_ID,
        "session_identifier": f"perf-sess-{user_id}-{days_ago}-{uuid.uuid4()}",
        "name": f"perf session {days_ago}d ago",
        "started_at": now - timedelta(days=days_ago),
        "duration_seconds": duration_seconds,
        "tokens": tokens,
    }


def _usage_event_row(*, user_id: str, command: str, ts: datetime, idx: int) -> dict[str, Any]:
    """One `usage_events` row with every NOT NULL column
    (`app/models/ingestion.py::UsageEvent`) explicitly set."""
    return {
        "id": str(uuid.uuid4()),
        "program_id": _FIXTURE_PROGRAM_ID,
        "ts": ts,
        "cmd_ts": ts,
        "user": user_id,
        "session_id": f"perf-sess-evt-{user_id}-{idx}",
        "command": command,
        "duration_seconds": 1,
        "outcome": "success",
        "total": 0,
    }


async def _seed_personal_usage_rows(
    test_session: AsyncSession, *, user_id: str, range_days: int
) -> None:
    """Seed both `user_sessions` and `usage_events` rows inside AND outside
    `range_days`, so every one of the 3 budgeted SELECTs does real,
    non-trivial (not zero-row) work regardless of which `range` this
    scenario measures -- mirrors `test_personal_usage.py`'s TC-01 seed's
    in-range/out-of-range split, sized down for a perf run.
    """
    now = datetime.now(UTC)
    in_range_days_ago = sorted({0, 1, max(range_days // 2, 2), range_days - 1})
    out_of_range_days_ago = range_days + 10

    session_rows = [
        _user_session_row(
            user_id=user_id, days_ago=d, tokens=1000 * (d + 1), duration_seconds=600, now=now
        )
        for d in (*in_range_days_ago, out_of_range_days_ago)
    ]
    await test_session.execute(sa.insert(UserSessions), session_rows)

    in_range_ts = now - timedelta(days=in_range_days_ago[0])
    out_of_range_ts = now - timedelta(days=out_of_range_days_ago)
    event_rows: list[dict[str, Any]] = []
    idx = 0
    for command, count in (("plan", 12), ("implement", 6), ("review", 3)):
        for _ in range(count):
            event_rows.append(
                _usage_event_row(user_id=user_id, command=command, ts=in_range_ts, idx=idx)
            )
            idx += 1
    for _ in range(4):
        event_rows.append(
            _usage_event_row(user_id=user_id, command="deploy", ts=out_of_range_ts, idx=idx)
        )
        idx += 1
    await test_session.execute(sa.insert(UsageEvent), event_rows)
    await test_session.commit()


@pytest.mark.asyncio
@pytest.mark.usefixtures("production_logging")
@pytest.mark.parametrize("range_value", ["7d", "30d", "90d"])
async def test_personal_usage_query_count_and_duration_budget(
    range_value: str,
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """SHP-02-NFR-performance: exactly `QUERY_COUNT_BUDGET` SELECTs against
    `user_sessions`/`usage_events` combined, handler duration under
    `HANDLER_DURATION_BUDGET_MS`, zero `individual_view_denied` log records,
    and no PII in any captured `app.core.rbac` log record -- for a
    self-view GET at `range_value` in {7d, 30d, 90d}.
    """
    app = build_app()

    test_session_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    async with async_client_for(app) as client:
        token, user_id = await _mint_dev_bypass_token(client)
        await _seed_personal_usage_rows(
            test_session, user_id=user_id, range_days=_RANGE_DAYS[range_value]
        )
        headers = {"Authorization": f"Bearer {token}"}

        with (
            _count_personal_usage_selects(test_engine) as counter,
            _capture_rbac_logger() as records,
        ):
            started = time.perf_counter()
            resp = await client.get(
                f"/api/personal-usage/{user_id}?range={range_value}", headers=headers
            )
            elapsed_ms = (time.perf_counter() - started) * 1000

    assert resp.status_code == 200, resp.text

    assert counter.count == QUERY_COUNT_BUDGET, (
        f"range={range_value}: expected exactly {QUERY_COUNT_BUDGET} SELECTs against "
        f"user_sessions/usage_events, got {counter.count}: {counter.statements}"
    )

    # Honest measurement: report the actual number, don't hide a breach.
    print(
        f"\nSHP-02-NFR-performance baseline -- range={range_value} personal-usage "
        f"handler duration={elapsed_ms:.2f}ms (budget {HANDLER_DURATION_BUDGET_MS}ms)"
    )
    assert elapsed_ms < HANDLER_DURATION_BUDGET_MS, (
        f"GET /api/personal-usage/{{user_id}}?range={range_value} took {elapsed_ms:.2f}ms, "
        f"exceeding the SHP-02-NFR-performance budget of {HANDLER_DURATION_BUDGET_MS}ms. "
        "Do not relax this budget; report the measured duration for escalation/optimization."
    )

    denied_events = [r for r in records if r.getMessage() == "individual_view_denied"]
    assert len(denied_events) == 0, (
        "self-view request must never deny -- got "
        f"{len(denied_events)} individual_view_denied record(s): {denied_events}"
    )

    for record in records:
        payload = json.loads(JSONFormatter().format(record))
        for pii_key in ("email", "groups", "name", "token", "access_token", "authorization"):
            assert pii_key not in payload, (
                f"unexpected key {pii_key!r} in {record.getMessage()!r} payload: {payload}"
            )
