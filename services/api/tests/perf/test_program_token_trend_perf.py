"""Performance tests for `GET /api/overview/program-detail/{program_id}/token-trend`
(`app/api/overview.py::get_program_token_trend`) -- PGD-02-TC-10 (`PGD-02-NFR-performance`,
range-toggle refresh <=2s, NFR-002) and PGD-02-TC-11 (initial render <=3s, NFR-001).

Structure mirrors `tests/perf/test_overview_perf.py` exactly, per PLAN.md Section 7 and
DECISIONS.md D-05: plain `time.perf_counter()`, a real `create_app()` app via
`build_app`/`async_client_for`, no new benchmark tool. `program_visibility`
(`app/core/rbac.py`) is an open-aggregate veto gate that never resolves a persona
(`app/api/overview.py`'s own module docstring, PGD-02 AC-7), so a `POST /auth/dev-bypass`
bearer token is sufficient -- same rationale `tests/unit/test_program_token_trend_route.py`
already documents for the route-level tests; no Keycloak-mock/JWKS scaffold is needed here.

Backend-slice budgets, not the full NFR-001/NFR-002 end-to-end budgets: TC-10/TC-11's own
`test_data.budget_ms` (2000 / 3000) covers browser render + network + handler. This test can
only measure the handler's own duration, so it asserts a materially tighter budget than the
end-to-end figure -- the same "measurement fence, report don't hide a breach" discipline
`test_rollup_rebuild_perf.py`'s module docstring documents, and the same proportional
tightening `test_overview_perf.py::ORG_SUMMARY_HANDLER_DURATION_BUDGET_MS` (500ms against a
3000ms end-to-end NFR) already establishes as this repo's convention for a backend perf
slice. Following that same ~1/6 ratio here: 2000ms/6 ~ 333ms and 3000ms/6 = 500ms, rounded to
round numbers with headroom for a query against a 90-day-seeded table (busier than the
single-row lookups those precedents measure) -- HANDLER budgets of 400ms (toggle) and 500ms
(initial render) below.

Seeding: 90 daily `program_token_series` rows for one program -- every day in the 90d window
has data, so neither the zero-padding path nor a mostly-empty aggregate makes the measurement
vacuous (per T-06 task instructions). TC-11 (initial render) exercises the default `30d`
request; TC-10 (range-toggle refresh) exercises a subsequent `90d` request -- the toggle's
worst case, since it scans the most rows of the three supported ranges.

Not flaky by construction: budgets are set well above the range this handler shape should
ever cost (a single indexed range-scoped SELECT plus Python-side zero-padding/aggregation
over at most 90 rows), matching `test_overview_perf.py`'s stated headroom philosophy rather
than pinning to a locally measured figure. Do not relax these budgets to hide a real
regression; report the measured number instead (see assertion messages).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.rollup import ProgramTokenSeries
from tests.conftest import AlembicRunner

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

# PGD-02-TC-10/TC-11 test_data -- do not relax.
PROGRAM_ID = "prog-token-trend-perf"
SEED_DAYS = 90
# Backend handler-duration slice of the end-to-end NFR budgets (see module docstring for the
# ~1/6 derivation from TC-10's 2000ms / TC-11's 3000ms end-to-end figures).
TOGGLE_HANDLER_DURATION_BUDGET_MS = 400.0
INITIAL_RENDER_HANDLER_DURATION_BUDGET_MS = 500.0


def _series_row(*, program_id: str, days_ago: int, now: datetime) -> dict[str, Any]:
    """One `program_token_series` row with every NOT NULL column explicitly set
    (`app/models/rollup.py::ProgramTokenSeries`), matching
    `test_program_token_trend_route.py::_series_row`. `tokens` varies per day so the
    handler's aggregation/summation does real work rather than summing a constant."""
    return {
        "id": str(uuid.uuid4()),
        "program_id": program_id,
        "date": now - timedelta(days=days_ago),
        "tokens": 1000 + days_ago,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "as_of_timestamp": now,
    }


async def _seed_ninety_days(test_session: AsyncSession, now: datetime) -> None:
    """`SEED_DAYS` consecutive daily rows for `PROGRAM_ID`, covering every day in the
    90d window (and therefore also the nested 30d/7d windows) so neither the initial
    30d request nor the toggled 90d request hits the zero-padding path."""
    rows = [_series_row(program_id=PROGRAM_ID, days_ago=d, now=now) for d in range(SEED_DAYS)]
    await test_session.execute(insert(ProgramTokenSeries), rows)
    await test_session.commit()


def _build_token_trend_app(
    build_app: Callable[..., FastAPI], test_session: AsyncSession
) -> FastAPI:
    """Real `create_app()` wired for HTTP-level testing against a live DB, matching
    `test_program_token_trend_route.py::_build_token_trend_app`. Hermetic default
    settings set `environment="test"`, so `/auth/dev-bypass` is registered."""

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield test_session

    app = build_app()
    app.dependency_overrides[get_db] = _override_get_db
    return app


@pytest.mark.asyncio
async def test_initial_render_default_30d_budget_tc11(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-02-TC-11: the default (no `range` param, i.e. `30d`) request -- the
    initial-render path -- completes under `INITIAL_RENDER_HANDLER_DURATION_BUDGET_MS`.
    """
    now = datetime.now(UTC)
    await _seed_ninety_days(test_session, now)

    app = _build_token_trend_app(build_app, test_session)

    async with async_client_for(app) as client:
        issue_resp = await client.post("/auth/dev-bypass", json={})
        assert issue_resp.status_code == 200, issue_resp.text
        token = issue_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        started = time.perf_counter()
        resp = await client.get(
            f"/api/overview/program-detail/{PROGRAM_ID}/token-trend", headers=headers
        )
        elapsed_ms = (time.perf_counter() - started) * 1000

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["points"]) == 30

    # Honest measurement: report the actual number, don't hide a breach.
    print(
        f"\nPGD-02-TC-11 baseline -- token-trend (30d, initial render) handler "
        f"duration={elapsed_ms:.2f}ms (budget {INITIAL_RENDER_HANDLER_DURATION_BUDGET_MS}ms)"
    )
    assert elapsed_ms < INITIAL_RENDER_HANDLER_DURATION_BUDGET_MS, (
        f"GET /api/overview/program-detail/{{program_id}}/token-trend (range=30d, "
        f"initial render) took {elapsed_ms:.2f}ms, exceeding the PGD-02-TC-11 backend "
        f"handler-duration budget of {INITIAL_RENDER_HANDLER_DURATION_BUDGET_MS}ms "
        "(the backend slice of NFR-001's 3000ms end-to-end budget). Do not relax this "
        "budget; report the measured duration for escalation/optimization."
    )


@pytest.mark.asyncio
async def test_range_toggle_refresh_90d_budget_tc10(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-02-TC-10: a range-toggle refresh to `90d` -- the worst-case (largest) range --
    completes under `TOGGLE_HANDLER_DURATION_BUDGET_MS`. Mirrors a real toggle: the
    initial `30d` request is issued first (unmeasured), then the `90d` toggle request is
    the one under budget, matching the given/when in `docs/test-cases/PGD-02.json`
    PGD-02-TC-10 ("page rendered with 30D active" -> "user toggles to ... 90D").
    """
    now = datetime.now(UTC)
    await _seed_ninety_days(test_session, now)

    app = _build_token_trend_app(build_app, test_session)

    async with async_client_for(app) as client:
        issue_resp = await client.post("/auth/dev-bypass", json={})
        assert issue_resp.status_code == 200, issue_resp.text
        token = issue_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Unmeasured initial 30d render, matching the given precondition.
        initial_resp = await client.get(
            f"/api/overview/program-detail/{PROGRAM_ID}/token-trend", headers=headers
        )
        assert initial_resp.status_code == 200, initial_resp.text

        # Measured toggle to 90d -- the worst case of the three supported ranges.
        started = time.perf_counter()
        resp = await client.get(
            f"/api/overview/program-detail/{PROGRAM_ID}/token-trend",
            params={"range": "90d"},
            headers=headers,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["points"]) == 90

    # Honest measurement: report the actual number, don't hide a breach.
    print(
        f"\nPGD-02-TC-10 baseline -- token-trend (range-toggle to 90d) handler "
        f"duration={elapsed_ms:.2f}ms (budget {TOGGLE_HANDLER_DURATION_BUDGET_MS}ms)"
    )
    assert elapsed_ms < TOGGLE_HANDLER_DURATION_BUDGET_MS, (
        f"GET /api/overview/program-detail/{{program_id}}/token-trend (range-toggle to "
        f"90d) took {elapsed_ms:.2f}ms, exceeding the PGD-02-TC-10 backend "
        f"handler-duration budget of {TOGGLE_HANDLER_DURATION_BUDGET_MS}ms (the backend "
        "slice of NFR-002's 2000ms end-to-end budget). Do not relax this budget; report "
        "the measured duration for escalation/optimization."
    )
