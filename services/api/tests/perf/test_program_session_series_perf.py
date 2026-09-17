"""Performance test for `GET /api/overview/program-detail/{program_id}/session-time-series`
(`app/api/overview.py::get_program_session_series`, `app/services/program_session_series.py::
fetch_program_session_series`) -- PGD-06-TC-17 (`PGD-06-NFR-performance`, research R-4,
DECISIONS.md D-02).

Structure mirrors `tests/perf/test_program_commands_perf.py` exactly -- a query-count spy via
a `before_cursor_execute` SQLAlchemy event listener, a real `create_app()` app
(`build_app`/`async_client_for`, `tests/conftest.py`), a bearer token minted via
`POST /auth/dev-bypass`, `time.perf_counter()`, no new benchmark tool. Marked
`@pytest.mark.perf` (`pyproject.toml:58-61` deselects it from the default run via
`addopts = "-m 'not perf'"`; opt in with `pytest -m perf`), matching every other file in
`tests/perf/`.

R-4/D-02: the org-wide (unfiltered) query has no dedicated index -- the only index touching
`session_series` is the 4-column unique constraint `uq_session_series_org_id_program_id_
member_id_date` on `(org_id, program_id, member_id, date)`, whose leading columns do not serve
an unfiltered `WHERE program_id = :pid AND date >= :range_start` scan. D-02 accepted this scan
at current data volume; this test is the guard that makes that acceptance safe -- both the
query-count (single aggregate query, no N+1) and the wall-clock budget must hold at a seeded
volume large enough that a regression to a per-day-loop or per-member fan-out would visibly
blow the budget.

Query-count spy: scoped to SELECT statements referencing `session_series` (this route's ONLY
query -- `fetch_program_session_series` issues exactly one grouped SELECT for both the
unfiltered and the member-filtered branch, per its own docstring: no `program_summary`
existence lookup precedes it, matching the commands/team siblings' no-404 empty-behaviour
contract). Word-boundary regex mirrors `test_program_commands_perf.py::_USAGE_EVENTS_RE`.
Always detached in a `finally` so it can never leak into sibling tests sharing the
session-scoped `test_engine` fixture.

Seeding: PGD-06-TC-17's own preconditions require program_id=prog-perf with >=50 members and
>=5,000 `session_series` rows spread across 90 days -- bulk-inserted via a single
`insert(...).values([...])`, one row per (member, day) pair (50 members x 100 days = 5,000
rows, comfortably clearing both TC-17 floors) so every measured `range` (7d/30d/90d) and the
self-filtered case do real, non-trivial per-day grouping/filtering work rather than matching
every seeded row identically.

Honest measurement: if either budget breaches, that is reported as a finding with the
measured number -- not hidden by loosening the budget, weakening the query-count assertion,
or seeding fewer rows to make it pass.
"""

from __future__ import annotations

import base64
import json
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
from app.models.rollup import SessionSeries
from tests.conftest import AlembicRunner

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

# PGD-06-TC-17 test_data -- do not relax.
PROGRAM_ID = "prog-perf"
ORG_ID = "org-perf"
MEMBER_COUNT = 50  # >= 50 members per TC-17 preconditions
DAYS_SPREAD = 100  # 50 members x 100 days = 5,000 rows, >= 5,000 floor per TC-17 preconditions
SEED_ROW_COUNT = MEMBER_COUNT * DAYS_SPREAD
QUERY_COUNT_BUDGET = 1  # single aggregate query, no N+1 fan-out (R-4/D-02)
DURATION_BUDGET_MS = 2000.0  # NFR-002

_SESSION_SERIES_RE = re.compile(r"\bsession_series\b", re.IGNORECASE)


@dataclass
class _SelectCounter:
    """Captures every SELECT statement referencing `session_series` seen while this
    counter's context manager is active."""

    count: int = 0
    statements: list[str] = field(default_factory=list)


@contextmanager
def _count_session_series_selects(engine: AsyncEngine) -> Iterator[_SelectCounter]:
    """Attach a `before_cursor_execute` listener to `engine.sync_engine` for the duration
    of the `with` block, counting SELECTs against `session_series`.

    Mirrors `tests/perf/test_program_commands_perf.py::_count_usage_events_selects`.
    Detaches in `finally` so the listener cannot leak into sibling tests that share the
    session-scoped `test_engine` fixture.
    """
    counter = _SelectCounter()
    sync_engine = engine.sync_engine

    def _before_cursor_execute(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        is_select = statement.strip().upper().startswith("SELECT")
        if is_select and _SESSION_SERIES_RE.search(statement):
            counter.count += 1
            counter.statements.append(statement)

    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield counter
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before_cursor_execute)


def _session_series_row(
    *, program_id: str, member_id: str, days_ago: int, now: datetime
) -> dict[str, Any]:
    """One `session_series` row with every NOT NULL column explicitly set
    (`app/models/rollup.py::SessionSeries`)."""
    return {
        "id": str(uuid.uuid4()),
        "org_id": ORG_ID,
        "program_id": program_id,
        "member_id": member_id,
        "date": now - timedelta(days=days_ago),
        "session_time_seconds": 900,
        "as_of_timestamp": now,
    }


async def _seed_session_series(test_session: AsyncSession, now: datetime) -> str:
    """Bulk-insert `SEED_ROW_COUNT` `session_series` rows for `PROGRAM_ID`, one per
    (member, day) pair across `MEMBER_COUNT` distinct members and `DAYS_SPREAD` days, so
    every measured `range` (7d/30d/90d) and the self-filtered case genuinely filter/group
    rather than matching/grouping everything identically. Returns the member_id used for
    the self-filtered case (the first seeded member)."""
    member_ids = [f"perf-member-{i}" for i in range(MEMBER_COUNT)]

    rows = [
        _session_series_row(program_id=PROGRAM_ID, member_id=member_id, days_ago=day, now=now)
        for member_id in member_ids
        for day in range(DAYS_SPREAD)
    ]
    await test_session.execute(insert(SessionSeries), rows)
    await test_session.commit()
    return member_ids[0]


def _build_session_series_app(
    build_app: Callable[..., FastAPI], test_session: AsyncSession
) -> FastAPI:
    """Real `create_app()` wired for HTTP-level testing against a live DB, matching
    `test_program_commands_perf.py::_build_commands_app`. Hermetic default settings set
    `environment="test"`, so `/auth/dev-bypass` is registered."""

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield test_session

    app = build_app()
    app.dependency_overrides[get_db] = _override_get_db
    return app


@pytest.mark.perf
@pytest.mark.asyncio
@pytest.mark.parametrize("range_value", ["7d", "30d", "90d"])
async def test_program_session_series_query_count_and_duration_budget_tc17(
    range_value: str,
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-06-TC-17 (unfiltered): for a program with >=5000 seeded `session_series` rows
    across 90 days and >=50 distinct members, `GET .../session-time-series?range=
    {range_value}` completes in under `DURATION_BUDGET_MS` (NFR-002's 2000ms budget) via
    exactly `QUERY_COUNT_BUDGET` (single) `session_series` SELECT -- no per-day or
    per-member N+1 fan-out.
    """
    now = datetime.now(UTC)
    await _seed_session_series(test_session, now)

    app = _build_session_series_app(build_app, test_session)

    async with async_client_for(app) as client:
        issue_resp = await client.post("/auth/dev-bypass", json={})
        assert issue_resp.status_code == 200, issue_resp.text
        token = issue_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        with _count_session_series_selects(test_engine) as counter:
            started = time.perf_counter()
            resp = await client.get(
                f"/api/overview/program-detail/{PROGRAM_ID}/session-time-series",
                params={"range": range_value},
                headers=headers,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000

    assert resp.status_code == 200, resp.text

    assert counter.count == QUERY_COUNT_BUDGET, (
        f"range={range_value} (unfiltered): expected exactly {QUERY_COUNT_BUDGET} SELECT "
        f"against session_series (single aggregate query, no N+1 fan-out), got "
        f"{counter.count}: {counter.statements}"
    )

    # Honest measurement: report the actual number, don't hide a breach.
    print(
        f"\nPGD-06-TC-17 baseline -- range={range_value} unfiltered session-time-series "
        f"({SEED_ROW_COUNT} seeded rows, {MEMBER_COUNT} members) "
        f"duration={elapsed_ms:.2f}ms (budget {DURATION_BUDGET_MS}ms), "
        f"queries={counter.count} (budget {QUERY_COUNT_BUDGET})"
    )
    assert elapsed_ms < DURATION_BUDGET_MS, (
        f"GET /api/overview/program-detail/{{program_id}}/session-time-series?"
        f"range={range_value} took {elapsed_ms:.2f}ms, exceeding the PGD-06-TC-17 / "
        f"NFR-002 budget of {DURATION_BUDGET_MS}ms across {SEED_ROW_COUNT} seeded rows "
        f"(R-4/D-02: no dedicated index on the org-wide scan). Do not relax this budget; "
        "report the measured duration for escalation/optimization."
    )


@pytest.mark.perf
@pytest.mark.asyncio
async def test_program_session_series_self_filtered_query_count_and_duration_budget_tc17(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-06-TC-17 (self-filtered): `GET .../session-time-series?range=30d&member_id=<self>`
    completes in under `DURATION_BUDGET_MS` via exactly `QUERY_COUNT_BUDGET` (single)
    `session_series` SELECT. `member_id` is set to the requester's own dev-bypass `sub`
    claim, mirroring `tests/unit/test_program_session_series_route.py::
    _mint_dev_bypass_token_with_sub` -- the self-filter path is authorized via
    `program_visibility` alone (no `member_in_program_visibility` HTTP round trip), so this
    case is not merely a stricter WHERE clause, it also confirms the RBAC gate branch stays
    a single-query path.
    """
    now = datetime.now(UTC)
    await _seed_session_series(test_session, now)

    app = _build_session_series_app(build_app, test_session)

    async with async_client_for(app) as client:
        issue_resp = await client.post("/auth/dev-bypass", json={})
        assert issue_resp.status_code == 200, issue_resp.text
        token = issue_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        payload_segment = token.split(".")[1]
        padding = "=" * (-len(payload_segment) % 4)
        requester_member_id = str(
            json.loads(base64.urlsafe_b64decode(payload_segment + padding))["sub"]
        )

        # Seed a session_series row for the requester's own member_id so the self-filtered
        # query has real data to aggregate, not an all-zero series.
        await test_session.execute(
            insert(SessionSeries),
            [
                _session_series_row(
                    program_id=PROGRAM_ID, member_id=requester_member_id, days_ago=day, now=now
                )
                for day in range(DAYS_SPREAD)
            ],
        )
        await test_session.commit()

        with _count_session_series_selects(test_engine) as counter:
            started = time.perf_counter()
            resp = await client.get(
                f"/api/overview/program-detail/{PROGRAM_ID}/session-time-series",
                params={"range": "30d", "member_id": requester_member_id},
                headers=headers,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000

    assert resp.status_code == 200, resp.text

    assert counter.count == QUERY_COUNT_BUDGET, (
        f"range=30d (self-filtered): expected exactly {QUERY_COUNT_BUDGET} SELECT against "
        f"session_series, got {counter.count}: {counter.statements}"
    )

    # Honest measurement: report the actual number, don't hide a breach.
    print(
        f"\nPGD-06-TC-17 baseline -- range=30d self-filtered session-time-series "
        f"duration={elapsed_ms:.2f}ms (budget {DURATION_BUDGET_MS}ms), "
        f"queries={counter.count} (budget {QUERY_COUNT_BUDGET})"
    )
    assert elapsed_ms < DURATION_BUDGET_MS, (
        f"GET /api/overview/program-detail/{{program_id}}/session-time-series?range=30d"
        f"&member_id=<self> took {elapsed_ms:.2f}ms, exceeding the PGD-06-TC-17 / NFR-002 "
        f"budget of {DURATION_BUDGET_MS}ms. Do not relax this budget; report the measured "
        "duration for escalation/optimization."
    )
