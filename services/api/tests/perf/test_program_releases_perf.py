"""Performance test for `GET /api/overview/program-detail/{program_id}/releases`
(`app/api/overview.py::get_program_releases`) -- PGD-03-TC-20 (`PGD-03-NFR-performance`,
FR-PGD03-7 index-coverage precondition).

Structure mirrors `tests/perf/test_program_token_trend_perf.py` /
`tests/perf/test_admin_repo_scan_perf.py`: plain `time.perf_counter()`, a real
`create_app()` app via `build_app`/`async_client_for`, a locally-copied nearest-rank
`_percentile` helper (per this repo's per-file precedent -- reusability-baseline.md:
"extract on the third repetition, not the first"), no new benchmark tool. Marked
`@pytest.mark.perf` (`services/api/pyproject.toml:58-61` deselects it from the default
run via `addopts = "-m 'not perf'"`; opt in with `pytest -m perf`), matching
`test_ingest_artifacts_perf.py` / `test_admin_repo_scan_perf.py`.

Seeding: >=5000 `program_releases` rows for ONE `program_id` via a single bulk
`insert(...).values([...])` (not 5000 ORM `add()`s / commits) so seeding itself doesn't
dominate the test's own runtime, plus one `ProgramSummary` row (the route's 404 lookup and
`tagColor`/`tagBg` resolution both depend on it existing). An explicit `ANALYZE
program_releases` follows the bulk insert -- see the index-usage assertion below for why
this matters: bulk-loading rows via `INSERT` does not implicitly refresh planner
statistics, and the Postgres autovacuum daemon's ANALYZE is scheduled, not synchronous, so a
test could race it and observe a stale plan even though the index exists and is used at
matching data volumes in the real deployment.

Two assertions per the module's task (T-08 / TC-20):

1. p95 latency across 50 sequential requests to the endpoint (range=90d, the story's
   representative window) is under NFR-002's 2000ms end-to-end budget.
2. `EXPLAIN ANALYZE` on the service's actual query shape -- `WHERE program_id = :pid AND
   date >= :range_start ORDER BY date DESC OFFSET .. LIMIT ..` (`app/services
   /program_releases.py::fetch_program_releases`'s row-fetch query, reproduced verbatim
   here via raw SQL against the same `program_releases` table) -- shows the planner choosing
   `ix_program_releases_program_id_date` (ADR-0015), not a sequential scan.

Honest measurement: if either assertion breaches, that is reported as a finding with the
measured number / plan text -- not hidden by loosening the budget, weakening the index
assertion, or seeding fewer rows to make the planner cooperate.
"""

from __future__ import annotations

import math
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.db import get_db
from app.models.rollup import ProgramReleases, ProgramSummary
from tests.conftest import AlembicRunner

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

# PGD-03-TC-20 test_data -- do not relax.
PROGRAM_ID = "prog-heavy"
SEED_ROW_COUNT = 5000
MEASURED_REQUESTS = 50
P95_BUDGET_MS = 2000.0  # NFR-002 / FR-PGD03-7
RANGE_VALUE = "90d"

_RELEASE_TYPES = ("Feature release", "Patch release", "Hotfix")


def _percentile(sorted_values_ms: list[float], pct: float) -> float:
    """Nearest-rank percentile over an already-sorted list, in milliseconds.

    index = ceil(pct * N) - 1 -- copied from `test_programs_perf.py::_percentile` /
    `test_admin_repo_scan_perf.py::_percentile` (same deterministic, dependency-free
    method; no numpy/statistics.quantiles interpolation ambiguity to document).
    """
    n = len(sorted_values_ms)
    rank = math.ceil(pct * n)
    return sorted_values_ms[rank - 1]


def _release_row(*, program_id: str, days_ago: int, now: datetime, index: int) -> dict[str, Any]:
    """One `program_releases` row with every NOT NULL column explicitly set
    (`app/models/rollup.py::ProgramReleases`). `days_ago` is spread across the seed set
    (see `_seed_releases`) so `date >= range_start` genuinely filters rather than matching
    every row identically; `type` cycles the closed 3-entry vocabulary so
    `_release_presentation` never raises on a seeded row.
    """
    return {
        "id": str(uuid.uuid4()),
        "program_id": program_id,
        "version": f"v1.{index}.0",
        "type": _RELEASE_TYPES[index % len(_RELEASE_TYPES)],
        "date": now - timedelta(days=days_ago),
        "story_count": 1 + (index % 5),
        "pr_count": 1 + (index % 3),
        "as_of_timestamp": now,
    }


def _build_program_summary(program_id: str) -> ProgramSummary:
    """One representative `program_summary` row -- the route 404s before calling the
    service if this is absent (`app/api/overview.py::get_program_releases`)."""
    now = datetime.now(UTC)
    return ProgramSummary(
        program_id=program_id,
        name="Apex Heavy Load Program",
        icon="rocket",
        type="Migration",
        description="perf-baseline seed row",
        monthly_token_sparkline=[],
        tokens=2_500_000,
        releases=SEED_ROW_COUNT,
        features=45,
        active_contributors=0,
        repos_with_harness_installed=5,
        repos_total=6,
        commands_executed=8500,
        lines_of_code_generated=125_000,
        user_stories_delivered=320,
        as_of_timestamp=now,
    )


async def _seed_releases(
    test_session: AsyncSession, test_engine: AsyncEngine, now: datetime
) -> None:
    """Bulk-insert `SEED_ROW_COUNT` `program_releases` rows for `PROGRAM_ID`, spread over
    0..179 days ago (comfortably beyond the 90d window under test, so the row query and
    count query both do real filtering work rather than matching every seeded row), plus
    one `ProgramSummary` row. `ANALYZE program_releases` runs after the bulk insert so the
    planner has fresh statistics before either the timed requests or the `EXPLAIN ANALYZE`
    below -- see module docstring for why this step is required, not optional.
    """
    rows = [
        _release_row(program_id=PROGRAM_ID, days_ago=i % 180, now=now, index=i)
        for i in range(SEED_ROW_COUNT)
    ]
    await test_session.execute(insert(ProgramReleases), rows)
    test_session.add(_build_program_summary(PROGRAM_ID))
    await test_session.commit()

    async with test_engine.begin() as conn:
        await conn.execute(text("ANALYZE program_releases"))


def _build_releases_app(build_app: Callable[..., FastAPI], test_session: AsyncSession) -> FastAPI:
    """Real `create_app()` wired for HTTP-level testing against a live DB, matching
    `test_program_token_trend_perf.py::_build_token_trend_app`. Hermetic default settings
    set `environment="test"`, so `/auth/dev-bypass` is registered."""

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield test_session

    app = build_app()
    app.dependency_overrides[get_db] = _override_get_db
    return app


@pytest.mark.perf
@pytest.mark.asyncio
async def test_releases_p95_latency_under_nfr_budget_tc20(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-03-TC-20 (latency half): 50 sequential GET requests against a 5000+-row seeded
    program, range=90d -- p95 latency must stay under `P95_BUDGET_MS` (NFR-002's literal
    end-to-end 2000ms figure, per TC-20's own `expected_results`, not a tightened internal
    slice -- this is the actual endpoint under a real Postgres, not a throwaway route).
    """
    now = datetime.now(UTC)
    await _seed_releases(test_session, test_engine, now)

    app = _build_releases_app(build_app, test_session)

    async with async_client_for(app) as client:
        issue_resp = await client.post("/auth/dev-bypass", json={})
        assert issue_resp.status_code == 200, issue_resp.text
        token = issue_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        latencies_ms: list[float] = []
        for _ in range(MEASURED_REQUESTS):
            started = time.perf_counter()
            resp = await client.get(
                f"/api/overview/program-detail/{PROGRAM_ID}/releases",
                params={"range": RANGE_VALUE},
                headers=headers,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
            assert resp.status_code == 200, resp.text
            latencies_ms.append(elapsed_ms)

    latencies_ms.sort()
    p95 = _percentile(latencies_ms, 0.95)

    # Honest measurement: report the actual number, don't hide a breach.
    print(
        f"\nPGD-03-TC-20 baseline -- releases (range=90d, {SEED_ROW_COUNT} seeded rows) "
        f"p95={p95:.2f}ms across {MEASURED_REQUESTS} requests (budget {P95_BUDGET_MS}ms)"
    )
    assert p95 < P95_BUDGET_MS, (
        f"GET /api/overview/program-detail/{{program_id}}/releases (range={RANGE_VALUE}) "
        f"p95 latency {p95:.2f}ms exceeded the PGD-03-TC-20 / NFR-002 budget of "
        f"{P95_BUDGET_MS}ms across {MEASURED_REQUESTS} measured requests against "
        f"{SEED_ROW_COUNT} seeded rows. Do not relax this budget; report the measured "
        "p95 for escalation/optimization."
    )


@pytest.mark.perf
@pytest.mark.asyncio
async def test_releases_query_uses_compound_index_not_seq_scan_tc20(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
) -> None:
    """PGD-03-TC-20 (index-usage half) / FR-PGD03-7: `EXPLAIN ANALYZE` on the service's
    actual query shape (`fetch_program_releases`'s row-fetch statement, reproduced here
    verbatim via raw SQL against the same table/predicate/ordering/pagination clause) shows
    the planner choosing `ix_program_releases_program_id_date` (ADR-0015), not a sequential
    scan on `program_releases`.

    At small row counts Postgres's planner can legitimately prefer a sequential scan over
    an index scan (lower fixed overhead) even with the index present and usable -- this is
    why TC-20 requires the 5000+-row seed and why `_seed_releases` runs `ANALYZE
    program_releases` immediately after the bulk insert: without fresh statistics the
    planner may still estimate the table as empty/small and skip the index regardless of
    real row count.
    """
    now = datetime.now(UTC)
    await _seed_releases(test_session, test_engine, now)

    range_start = now - timedelta(days=90)

    async with test_engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                EXPLAIN ANALYZE
                SELECT * FROM program_releases
                WHERE program_id = :program_id AND date >= :range_start
                ORDER BY date DESC
                OFFSET :offset LIMIT :limit
                """
            ),
            {
                "program_id": PROGRAM_ID,
                "range_start": range_start,
                "offset": 0,
                "limit": 20,
            },
        )
        plan_lines = [row[0] for row in result.fetchall()]

    plan_text = "\n".join(plan_lines)

    # Honest measurement: print the real plan, don't hide a breach.
    print(f"\nPGD-03-TC-20 EXPLAIN ANALYZE plan:\n{plan_text}")

    assert "ix_program_releases_program_id_date" in plan_text, (
        "EXPLAIN ANALYZE did not reference ix_program_releases_program_id_date "
        f"(ADR-0015) at {SEED_ROW_COUNT} seeded rows. Do not weaken this assertion; "
        f"investigate the real cause (e.g. stale planner statistics) instead. Plan:\n"
        f"{plan_text}"
    )
    assert "Seq Scan on program_releases" not in plan_text, (
        f"EXPLAIN ANALYZE shows a sequential scan on program_releases at "
        f"{SEED_ROW_COUNT} seeded rows -- the compound index is not being used. Do not "
        f"weaken this assertion; investigate the real cause instead. Plan:\n{plan_text}"
    )
