"""Performance test for `GET /api/overview/program-detail/{program_id}/commands`
(`app/api/overview.py::get_program_commands`, `app/services/program_commands.py::
fetch_program_commands`) -- PGD-04-TC-16 (`PGD-04-NFR-performance`, #438).

Structure mirrors `tests/perf/test_personal_usage_perf.py` exactly, per this task's own
notes (R-5: "perf test, single-query construction") -- `fetch_program_commands` is a
near-verbatim swap of `fetch_commands_breakdown` (`WHERE program_id` instead of `WHERE
user`), so its perf test reuses the same query-count-spy technique rather than
`test_program_releases_perf.py`'s `EXPLAIN ANALYZE`/p95 approach: TC-16 asks for a
single-aggregate-query assertion (no N+1 fan-out), which a `before_cursor_execute` listener
proves directly, plus a per-request wall-clock budget across all three `range` values, which
`test_personal_usage_perf.py` already does per-range via `@pytest.mark.parametrize`.

Real `create_app()` app (`build_app`/`async_client_for`, `tests/conftest.py`), a bearer
token minted via `POST /auth/dev-bypass`, `time.perf_counter()`, no new benchmark tool.
Marked `@pytest.mark.perf` (`pyproject.toml:58-61` deselects it from the default run via
`addopts = "-m 'not perf'"`; opt in with `pytest -m perf`), matching every other file in
`tests/perf/`.

Query-count spy: scoped to SELECT statements referencing `usage_events` (this route's ONLY
query -- `fetch_program_commands` issues exactly one grouped SELECT, D-01/D-02: no
`program_summary` existence lookup precedes it, unlike the releases route). Word-boundary
regex mirrors `test_personal_usage_perf.py::_USER_SESSIONS_OR_USAGE_EVENTS_RE`. Always
detached in a `finally` so it can never leak into sibling tests sharing the session-scoped
`test_engine` fixture.

Seeding: >=5000 `usage_events` rows for ONE `program_id` (`prog-perf`, per TC-16's own
`test_data`) via a single bulk `insert(...).values([...])`, spread across 90 days with
>=10 distinct commands (TC-16 preconditions), so every measured `range` does real,
non-trivial filtering/grouping work rather than matching every seeded row identically or
grouping a single command.

Honest measurement: if either budget breaches, that is reported as a finding with the
measured number -- not hidden by loosening the budget, weakening the query-count assertion,
or seeding fewer rows to make it pass.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import event, insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.db import get_db
from app.models.ingestion import UsageEvent
from tests.conftest import AlembicRunner

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

# PGD-04-TC-16 test_data -- do not relax.
PROGRAM_ID = "prog-perf"
SEED_ROW_COUNT = 5000
DAYS_SPREAD = 90
COMMAND_COUNT = 12  # >= 10 distinct commands per TC-16 preconditions
QUERY_COUNT_BUDGET = 1  # single aggregate query, no N+1 fan-out
DURATION_BUDGET_MS = 2000.0  # NFR-002

_RANGE_DAYS: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90}
_USAGE_EVENTS_RE = re.compile(r"\busage_events\b", re.IGNORECASE)

_COMMANDS = [f"/cmd-{i}" for i in range(COMMAND_COUNT)]


@dataclass
class _SelectCounter:
    """Captures every SELECT statement referencing `usage_events` seen while this
    counter's context manager is active."""

    count: int = 0
    statements: list[str] = field(default_factory=list)


@contextmanager
def _count_usage_events_selects(engine: AsyncEngine) -> Iterator[_SelectCounter]:
    """Attach a `before_cursor_execute` listener to `engine.sync_engine` for the duration
    of the `with` block, counting SELECTs against `usage_events`.

    Mirrors `tests/perf/test_personal_usage_perf.py::_count_personal_usage_selects`.
    Detaches in `finally` so the listener cannot leak into sibling tests that share the
    session-scoped `test_engine` fixture.
    """
    counter = _SelectCounter()
    sync_engine = engine.sync_engine

    def _before_cursor_execute(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        is_select = statement.strip().upper().startswith("SELECT")
        if is_select and _USAGE_EVENTS_RE.search(statement):
            counter.count += 1
            counter.statements.append(statement)

    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield counter
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before_cursor_execute)


def _usage_event_row(
    *, program_id: str, days_ago: int, command: str, now: datetime
) -> dict[str, Any]:
    """One `usage_events` row with every NOT NULL column explicitly set
    (`app/models/ingestion.py::UsageEvent`)."""
    ts = now - timedelta(days=days_ago)
    return {
        "id": str(uuid.uuid4()),
        "program_id": program_id,
        "ts": ts,
        "cmd_ts": ts,
        "user": f"perf-user-{days_ago}",
        "session_id": f"perf-sess-{program_id}-{days_ago}-{uuid.uuid4()}",
        "command": command,
        "duration_seconds": 1,
        "outcome": "success",
        "total": 0,
    }


async def _seed_usage_events(test_session: AsyncSession, now: datetime) -> None:
    """Bulk-insert `SEED_ROW_COUNT` `usage_events` rows for `PROGRAM_ID`, spread over
    0..(DAYS_SPREAD-1) days ago across `COMMAND_COUNT` distinct commands, so every measured
    `range` (7d/30d/90d) genuinely filters and groups rather than matching/grouping
    everything identically.
    """
    rows = [
        _usage_event_row(
            program_id=PROGRAM_ID,
            days_ago=i % DAYS_SPREAD,
            command=_COMMANDS[i % COMMAND_COUNT],
            now=now,
        )
        for i in range(SEED_ROW_COUNT)
    ]
    await test_session.execute(insert(UsageEvent), rows)
    await test_session.commit()


def _build_commands_app(build_app: Callable[..., FastAPI], test_session: AsyncSession) -> FastAPI:
    """Real `create_app()` wired for HTTP-level testing against a live DB, matching
    `test_program_releases_perf.py::_build_releases_app`. Hermetic default settings set
    `environment="test"`, so `/auth/dev-bypass` is registered."""

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield test_session

    app = build_app()
    app.dependency_overrides[get_db] = _override_get_db
    return app


@pytest.mark.perf
@pytest.mark.asyncio
@pytest.mark.parametrize("range_value", ["7d", "30d", "90d"])
async def test_program_commands_query_count_and_duration_budget_tc16(
    range_value: str,
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-04-TC-16: for a program with >=5000 seeded `usage_events` rows across 90 days
    and >=10 distinct commands, `GET .../commands?range={range_value}` completes in under
    `DURATION_BUDGET_MS` (NFR-002's 2000ms budget) via exactly `QUERY_COUNT_BUDGET`
    (single) `usage_events` SELECT -- no per-command N+1 fan-out.
    """
    now = datetime.now(UTC)
    await _seed_usage_events(test_session, now)

    app = _build_commands_app(build_app, test_session)

    async with async_client_for(app) as client:
        issue_resp = await client.post("/auth/dev-bypass", json={})
        assert issue_resp.status_code == 200, issue_resp.text
        token = issue_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        with _count_usage_events_selects(test_engine) as counter:
            started = time.perf_counter()
            resp = await client.get(
                f"/api/overview/program-detail/{PROGRAM_ID}/commands",
                params={"range": range_value},
                headers=headers,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000

    assert resp.status_code == 200, resp.text

    assert counter.count == QUERY_COUNT_BUDGET, (
        f"range={range_value}: expected exactly {QUERY_COUNT_BUDGET} SELECT against "
        f"usage_events (single aggregate query, no N+1 fan-out), got {counter.count}: "
        f"{counter.statements}"
    )

    # Honest measurement: report the actual number, don't hide a breach.
    print(
        f"\nPGD-04-TC-16 baseline -- range={range_value} commands endpoint "
        f"({SEED_ROW_COUNT} seeded rows, {COMMAND_COUNT} distinct commands) "
        f"duration={elapsed_ms:.2f}ms (budget {DURATION_BUDGET_MS}ms)"
    )
    assert elapsed_ms < DURATION_BUDGET_MS, (
        f"GET /api/overview/program-detail/{{program_id}}/commands?range={range_value} "
        f"took {elapsed_ms:.2f}ms, exceeding the PGD-04-TC-16 / NFR-002 budget of "
        f"{DURATION_BUDGET_MS}ms across {SEED_ROW_COUNT} seeded rows. Do not relax this "
        "budget; report the measured duration for escalation/optimization."
    )
