"""Performance test for GET /api/overview/program-detail/{program_id} --
PGD-01-TC-04 (`PGD-01-NFR-performance`, `program_drilldown` half of FR-5/
NFR-observability): a single bounded `SELECT` against `program_summary` (no
N+1 fan-out), the handler's own duration under its latency budget, and
exactly one `program_drilldown` structured log event carrying `{program_id}`
and no PII.

Structure mirrors `tests/perf/test_programs_perf.py`: plain
`time.perf_counter()`, no dedicated benchmark tool -- this task's own
file-plan reason names that file as the pattern to match, and no new
runner/tooling is introduced here. TC-04's own `test_data` pins a single
measured call against a fixed budget (`handler_duration_budget_ms`), not a
percentile across an iteration loop like TC-17 -- so no `_percentile` helper
is needed here.

Real end-to-end path, not a throwaway route: this measures the actual
`GET /api/overview/program-detail/{program_id}` router (`app/api/overview.py`)
mounted by the real `create_app` factory (`build_app`/`async_client_for`
fixtures, `tests/conftest.py`), driven through a real bearer token minted by
`POST /auth/dev-bypass` (same pattern as `test_programs_perf.py`) -- not a
hand-forged JWT. `app.core.db.get_db` is overridden (`app.dependency_overrides`)
to serve sessions from the disposable `migrated_db`/`test_engine` test
database this test seeds with one `program_summary` row.

No persona-resolver stub is installed (unlike `test_programs_perf.py`):
`app/api/overview.py` calls `app.core.rbac.program_visibility`, an
open-aggregate veto gate that never consults `app.state.persona_resolver`
(DECISIONS.md D-05/D-06 for `programs-api`, mirrored here per this
endpoint's own module docstring, "Clarification C-3") -- there is nothing
for a stub to intercept.

Query-count spy: `before_cursor_execute` is a sync SQLAlchemy core event --
attached to `test_engine.sync_engine` (the underlying sync `Engine` an
`AsyncEngine` wraps), scoped to statements that (a) start with `SELECT` and
(b) reference `program_summary` via a word-boundary regex. Mirrors
`tests/unit/test_rollup_rebuild_query_plan.py::_count_usage_events_selects`,
adapted to this endpoint's table. Always detached in a `finally`, so it
never leaks into sibling tests sharing the session-scoped `test_engine`.

`production_logging` fixture (copied from `test_programs_perf.py`/
`test_rbac_perf.py` -- same rationale, restore mechanics, JSON-stdout
`configure_logging()` setup): ensures `program_drilldown` actually formats
and writes rather than short-circuiting at `Logger.isEnabledFor(INFO)` with
no handler attached, so the measured duration includes the real cost a
deployed process pays per request. A second, LOCAL handler is attached
directly to `app.api.overview`'s logger purely to capture the emitted
`LogRecord` for the content/PII assertions below -- unlike
`tests/unit/test_programs.py::_capture_programs_logger`, this does NOT set
`propagate = False`: the record must still reach the root stdout handler
`production_logging` installs, so the measured duration keeps paying the
real formatting/write cost that fixture exists to include.

No `X-Program-Switch-From` header is sent -- this exercises the
`program_drilldown` path only (D-07: absent header -> `program_drilldown
{program_id}`). The `program_switch` half of D-07/FR-5 is a deliberate,
disclosed test-case gap, not an oversight: `docs/test-cases/PGD-01.json`
`coverage_audit.audit_notes` records that the PRD/story never specifies how
the backend would distinguish a switcher-triggered fetch from an initial
page load well enough to test it, and declines to fabricate a mechanism for
that purpose. D-07 designs and implements the header-based mechanism
(`app/api/overview.py`, T-02) regardless -- TC-04 simply does not exercise
that second branch.

Honest measurement: if the duration budget breaches, that is reported as a
finding with the measured number -- not hidden by loosening the budget or
excluding the log call from the timed window.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api import overview as overview_module
from app.core.db import get_db
from app.core.logging import JSONFormatter, configure_logging
from app.models.rollup import ProgramSummary
from tests.conftest import AlembicRunner

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

# PGD-01-TC-04 test_data -- do not relax.
PROGRAM_ID = "prog-042"
QUERY_COUNT_BUDGET = 1
HANDLER_DURATION_BUDGET_MS = 500.0

_PROGRAM_SUMMARY_RE = re.compile(r"\bprogram_summary\b", re.IGNORECASE)


@pytest.fixture
def production_logging() -> Iterator[None]:
    """Configure the same JSON-stdout logging `create_app()` sets up at
    import time (`app/core/logging.py::configure_logging`), then restore the
    previous root-logger state so this doesn't leak into other test files
    sharing this pytest session.

    Copied from `test_programs_perf.py`/`test_rbac_perf.py` -- identical
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

    Structurally copied from `tests/unit/test_programs.py::_RecordCapturingHandler`.
    """

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _capture_overview_logger() -> Iterator[list[logging.LogRecord]]:
    """Captures records from the real `app.api.overview` logger, IN ADDITION
    to the root stdout handler `production_logging` installs.

    `logger.disabled` is force-reset to `False` -- `migrated_db`'s Alembic
    upgrade runs `env.py`'s `fileConfig(disable_existing_loggers=True)`
    sweep (Alembic's own template boilerplate), which disables every
    already-imported logger not explicitly named in `alembic.ini`, including
    this module's (imported at this test file's collection time). Same
    gotcha `tests/unit/test_programs.py::_capture_programs_logger` documents
    and works around.

    Unlike that helper, `propagate` is left at its existing value (default
    `True`): the record must still reach the root handler and pay the real
    formatting/write cost `production_logging` exists to measure. This
    handler exists solely to inspect the record's content afterward.
    """
    logger = logging.getLogger(overview_module.__name__)
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
    """Captures every SELECT statement referencing `program_summary` seen
    while this counter's context manager is active."""

    count: int = 0
    statements: list[str] = field(default_factory=list)


@contextmanager
def _count_program_summary_selects(engine: AsyncEngine) -> Iterator[_SelectCounter]:
    """Attach a `before_cursor_execute` listener to `engine.sync_engine` for
    the duration of the `with` block, counting SELECTs against
    `program_summary`.

    Mirrors `tests/unit/test_rollup_rebuild_query_plan.py::_count_usage_events_selects`.
    Detaches in `finally` so the listener cannot leak into sibling tests that
    share the session-scoped `test_engine` fixture.
    """
    counter = _SelectCounter()
    sync_engine = engine.sync_engine

    def _before_cursor_execute(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        if statement.strip().upper().startswith("SELECT") and _PROGRAM_SUMMARY_RE.search(statement):
            counter.count += 1
            counter.statements.append(statement)

    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield counter
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before_cursor_execute)


def _build_program_summary(program_id: str) -> ProgramSummary:
    """One representative `program_summary` row -- field values are
    arbitrary (TC-04 doesn't assert on response content, only query count/
    duration/log shape); only `program_id` needs to be the id under test and
    `as_of_timestamp` needs a real tz-aware datetime (`program_summary
    .as_of_timestamp` is NOT NULL, `app/models/rollup.py`).
    """
    now = datetime.now(UTC)
    return ProgramSummary(
        program_id=program_id,
        name="Apex Core Migration",
        icon="rocket",
        type="Platform",
        description="perf-baseline seed row",
        monthly_token_sparkline=[],
        tokens=2_500_000,
        releases=12,
        features=45,
        active_contributors=0,
        repos_with_harness_installed=5,
        repos_total=6,
        commands_executed=8500,
        lines_of_code_generated=125_000,
        user_stories_delivered=320,
        as_of_timestamp=now,
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("production_logging")
async def test_program_detail_single_select_budget_and_program_drilldown_event_tc04(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-01-TC-04: one seeded `program_summary` row, one
    `GET /api/overview/program-detail/{program_id}` call (no
    `X-Program-Switch-From` header -- the `program_drilldown` path) --
    exactly 1 SELECT against `program_summary`, handler duration under
    `HANDLER_DURATION_BUDGET_MS`, and exactly one `program_drilldown` log
    record with `{program_id}` and no PII.

    The `program_switch` half of D-07/FR-5 is a deliberate, disclosed gap --
    see module docstring -- and is not exercised here.
    """
    test_session.add(_build_program_summary(PROGRAM_ID))
    await test_session.commit()

    app = build_app()

    test_session_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    async with async_client_for(app) as client:
        issue_resp = await client.post("/auth/dev-bypass", json={})
        assert issue_resp.status_code == 200, issue_resp.text
        token = issue_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        with (
            _count_program_summary_selects(test_engine) as counter,
            _capture_overview_logger() as records,
        ):
            started = time.perf_counter()
            resp = await client.get(f"/api/overview/program-detail/{PROGRAM_ID}", headers=headers)
            elapsed_ms = (time.perf_counter() - started) * 1000

    assert resp.status_code == 200, resp.text

    assert counter.count == QUERY_COUNT_BUDGET, (
        f"expected exactly {QUERY_COUNT_BUDGET} SELECT against program_summary, "
        f"got {counter.count}: {counter.statements}"
    )

    # C-4-style honest measurement: report the actual number, don't hide a breach.
    print(
        f"\nPGD-01-TC-04 baseline -- program-detail handler duration={elapsed_ms:.2f}ms "
        f"(budget {HANDLER_DURATION_BUDGET_MS}ms)"
    )
    assert elapsed_ms < HANDLER_DURATION_BUDGET_MS, (
        f"GET /api/overview/program-detail/{{program_id}} took {elapsed_ms:.2f}ms, "
        f"exceeding the PGD-01-TC-04 / NFR-performance budget of "
        f"{HANDLER_DURATION_BUDGET_MS}ms. Do not relax this budget; report the "
        "measured duration for escalation/optimization."
    )

    events = [r for r in records if r.getMessage() == "program_drilldown"]
    assert len(events) == 1, f"expected exactly one program_drilldown log record, got {len(events)}"
    payload = json.loads(JSONFormatter().format(events[0]))
    assert set(payload.keys()) == {"timestamp", "level", "logger", "message", "program_id"}
    assert payload["program_id"] == PROGRAM_ID
    for pii_key in ("email", "groups", "user_id", "name", "description", "path"):
        assert pii_key not in payload, f"unexpected key {pii_key!r} in program_drilldown payload"
