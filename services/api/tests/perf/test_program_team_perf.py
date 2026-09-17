"""Performance test for `GET /api/overview/program-detail/{program_id}/team`
(`app/api/overview.py::get_program_team`, `app/services/program_team.py::
fetch_program_team`) -- PGD-05-TC-14/TC-15 (research Condition C-1, mandatory).

Structure mirrors `tests/perf/test_program_commands_perf.py` exactly: a query-count spy
via a `before_cursor_execute` SQLAlchemy event listener, a real `create_app()` app
(`build_app`/`async_client_for`, `tests/conftest.py`), a bearer token minted via
`POST /auth/dev-bypass`, `time.perf_counter()`, no new benchmark tool. Marked
`@pytest.mark.perf` (`pyproject.toml:58-61` deselects it from the default run via
`addopts = "-m 'not perf'"`; opt in with `pytest -m perf`), matching every other file in
`tests/perf/`.

Unlike `test_program_commands_perf.py`'s single-query budget, `fetch_program_team`'s
contract (DECISIONS.md D-01, ADR-0016) is exactly TWO SELECTs per request: one
`program_members` roster snapshot, one range-scoped `usage_events` aggregate, merged in
Python by user id -- never a SQL join, which would risk a Cartesian product between the
two result sets. The spy below counts every SELECT touching EITHER table combined, so a
regression to N+1 (e.g. a per-row roster lookup) or a third query (e.g. an accidental
`program_summary` existence check) fails this test the same way a join would.

Seeding: >=5000 `usage_events` rows for ONE `program_id` (`prog-team-perf`) across >=20
distinct members (TC-14/TC-15 preconditions) over 90 days via a single bulk
`insert(...).values([...])`, plus a matching `program_members` roster row per member, so
every measured `range` (7d/30d/90d) does real, non-trivial filtering/grouping/merge work
rather than matching or grouping every seeded row identically.

Honest measurement: if either budget breaches, that is reported as a finding with the
measured number -- not hidden by loosening the budget, weakening the query-count
assertion, or seeding fewer rows to make it pass.
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
from app.models.rollup import ProgramMembers
from tests.conftest import AlembicRunner

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

# PGD-05-TC-14/TC-15 test_data -- do not relax.
PROGRAM_ID = "prog-team-perf"
SEED_ROW_COUNT = 5000
DAYS_SPREAD = 90
MEMBER_COUNT = 20  # >= 20 members per TC-14/TC-15 preconditions
QUERY_COUNT_BUDGET = 2  # D-01: one program_members SELECT + one usage_events SELECT
DURATION_BUDGET_MS = 2000.0  # NFR-002

_RANGE_DAYS: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90}
_TEAM_TABLES_RE = re.compile(r"\b(usage_events|program_members)\b", re.IGNORECASE)

_ROLES = ["Developer", "QA Engineer", "Architect", "Product Manager"]


@dataclass
class _SelectCounter:
    """Captures every SELECT statement referencing `usage_events` or `program_members`
    seen while this counter's context manager is active."""

    count: int = 0
    statements: list[str] = field(default_factory=list)


@contextmanager
def _count_team_selects(engine: AsyncEngine) -> Iterator[_SelectCounter]:
    """Attach a `before_cursor_execute` listener to `engine.sync_engine` for the duration
    of the `with` block, counting SELECTs against `usage_events` or `program_members`.

    Mirrors `tests/perf/test_program_commands_perf.py::_count_usage_events_selects`,
    extended to both tables D-01's two-SELECT contract spans. Always detached in a
    `finally` so it can never leak into sibling tests sharing the session-scoped
    `test_engine` fixture.
    """
    counter = _SelectCounter()
    sync_engine = engine.sync_engine

    def _before_cursor_execute(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        is_select = statement.strip().upper().startswith("SELECT")
        if is_select and _TEAM_TABLES_RE.search(statement):
            counter.count += 1
            counter.statements.append(statement)

    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield counter
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before_cursor_execute)


def _usage_event_row(
    *, program_id: str, days_ago: int, user_id: str, now: datetime
) -> dict[str, Any]:
    """One `usage_events` row with every NOT NULL column explicitly set
    (`app/models/ingestion.py::UsageEvent`). `total` (not a literal `tokens` column) is
    the field `fetch_program_team` sums for the wire's `tokens` concept."""
    ts = now - timedelta(days=days_ago)
    return {
        "id": str(uuid.uuid4()),
        "program_id": program_id,
        "ts": ts,
        "cmd_ts": ts,
        "user": user_id,
        "session_id": f"perf-sess-{program_id}-{user_id}-{days_ago}-{uuid.uuid4()}",
        "command": "/arh-implement",
        "duration_seconds": 1,
        "outcome": "success",
        "total": 100,
    }


def _member_row(*, program_id: str, user_id: str, index: int, now: datetime) -> dict[str, Any]:
    """One `program_members` roster row with every NOT NULL column explicitly set
    (`app/models/rollup.py::ProgramMembers`)."""
    return {
        "id": str(uuid.uuid4()),
        "program_id": program_id,
        "user_id": user_id,
        "name": f"Perf Member {index}",
        "role": _ROLES[index % len(_ROLES)],
        "sessions": 0,
        "tokens": 0,
        "last_active_date": now,
        "as_of_timestamp": now,
    }


async def _seed_team(test_session: AsyncSession, now: datetime) -> None:
    """Bulk-insert `SEED_ROW_COUNT` `usage_events` rows spread across `MEMBER_COUNT`
    distinct members over `DAYS_SPREAD` days, plus one matching `program_members` roster
    row per member, so every measured `range` (7d/30d/90d) genuinely filters and merges
    rather than matching/merging everything identically.
    """
    member_ids = [f"perf-user-{i}" for i in range(MEMBER_COUNT)]

    event_rows = [
        _usage_event_row(
            program_id=PROGRAM_ID,
            days_ago=i % DAYS_SPREAD,
            user_id=member_ids[i % MEMBER_COUNT],
            now=now,
        )
        for i in range(SEED_ROW_COUNT)
    ]
    await test_session.execute(insert(UsageEvent), event_rows)

    member_rows = [
        _member_row(program_id=PROGRAM_ID, user_id=user_id, index=i, now=now)
        for i, user_id in enumerate(member_ids)
    ]
    await test_session.execute(insert(ProgramMembers), member_rows)
    await test_session.commit()


def _build_team_app(build_app: Callable[..., FastAPI], test_session: AsyncSession) -> FastAPI:
    """Real `create_app()` app wired for HTTP-level testing against a live DB, matching
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
async def test_program_team_query_count_and_duration_budget_tc14_tc15(
    range_value: str,
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-05-TC-14/TC-15: for a program with >=5000 seeded `usage_events` rows across
    90 days and >=20 distinct members (plus a matching `program_members` roster),
    `GET .../team?range={range_value}` completes in under `DURATION_BUDGET_MS` (NFR-002's
    2000ms budget) via exactly `QUERY_COUNT_BUDGET` (two) SELECTs -- one `program_members`
    roster snapshot, one range-scoped `usage_events` aggregate (D-01) -- never a SQL join
    and never a per-row N+1 fan-out.
    """
    now = datetime.now(UTC)
    await _seed_team(test_session, now)

    app = _build_team_app(build_app, test_session)

    async with async_client_for(app) as client:
        issue_resp = await client.post("/auth/dev-bypass", json={})
        assert issue_resp.status_code == 200, issue_resp.text
        token = issue_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        with _count_team_selects(test_engine) as counter:
            started = time.perf_counter()
            resp = await client.get(
                f"/api/overview/program-detail/{PROGRAM_ID}/team",
                params={"range": range_value},
                headers=headers,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000

    assert resp.status_code == 200, resp.text

    assert counter.count == QUERY_COUNT_BUDGET, (
        f"range={range_value}: expected exactly {QUERY_COUNT_BUDGET} SELECTs against "
        f"usage_events/program_members (one roster snapshot + one range-scoped aggregate, "
        f"D-01 -- never a SQL join, never N+1), got {counter.count}: {counter.statements}"
    )

    # Honest measurement: report the actual number, don't hide a breach.
    print(
        f"\nPGD-05-TC-14/TC-15 baseline -- range={range_value} team endpoint "
        f"({SEED_ROW_COUNT} seeded usage_events rows, {MEMBER_COUNT} members) "
        f"duration={elapsed_ms:.2f}ms (budget {DURATION_BUDGET_MS}ms), "
        f"queries={counter.count} (budget {QUERY_COUNT_BUDGET})"
    )
    assert elapsed_ms < DURATION_BUDGET_MS, (
        f"GET /api/overview/program-detail/{{program_id}}/team?range={range_value} "
        f"took {elapsed_ms:.2f}ms, exceeding the PGD-05-TC-14/TC-15 / NFR-002 budget of "
        f"{DURATION_BUDGET_MS}ms across {SEED_ROW_COUNT} seeded rows. Do not relax this "
        "budget; report the measured duration for escalation/optimization."
    )
