"""Performance tests for `GET /api/artifacts/{program_id}`
(`app/api/artifacts.py::get_program_artifacts`, `app/services/artifacts.py`) --
SHP-04-TC-11 (`docs/test-cases/SHP-04.json`).

Scaffold mirrors `test_program_board.py`'s performance section (`_build_board_app`
/ `_mint_dev_bypass_token` / `before_cursor_execute` query-spy precedent): plain
pytest, no `@pytest.mark.perf`, no new runner -- `docs/config/project-commands.yaml`
already runs `test_unit` via bare `pytest`, and PLAN.md's Test Strategy is explicit
this row is "pytest; query-counter spy asserts exactly 1 SELECT/call, p95 < 3000ms
over a 10-call sample" (`docs/features/SHP-04/PLAN.md` § 7).

Budget source: `docs/features/SHP-04/REQUIREMENTS.md` § Non-functional requirements
-- "Performance: panel render <=3s under normal load (NFR-001, sourced from story)"
-- and `docs/test-cases/SHP-04.json` `SHP-04-TC-11.test_data`:
`{"query_count_budget": 1, "latency_budget_ms": 3000}`. Both figures are transcribed
verbatim from those sources, never invented.

Honest measurement: assertions run against the actual measured p95 and the actual
executed-statement count; never loosened to make a breach disappear.
"""

from __future__ import annotations

import math
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.db import get_db
from app.models.governance import ProgramArtifact
from tests.conftest import AlembicRunner

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

# SHP-04-TC-11 test_data (docs/test-cases/SHP-04.json) -- transcribed verbatim,
# never invented. latency_budget_ms mirrors REQUIREMENTS.md's NFR-001 (<=3s).
_QUERY_COUNT_BUDGET = 1
_LATENCY_BUDGET_MS = 3000.0
_PERF_MEASURED_REQUESTS = 10
_PROGRAM_ID = "dashboard"

# `_ARTIFACT_PRESENTATION` canonical types (app/services/artifacts.py) -- seeding
# all 5 mirrors TC-11's precondition: "program_artifacts seeded for
# program_id='dashboard' ... with all 5 types".
_CANONICAL_TYPES = ("prd", "user_story", "test_case", "arch_diagram", "api_spec")


# -----------------------------------------------------------------------------
# App + DB-override scaffold. Mirrors test_program_board.py's
# _db_override / _build_board_app precedent.
# -----------------------------------------------------------------------------


def _db_override(session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _get_db() -> AsyncIterator[AsyncSession]:
        yield session

    return _get_db


def _build_artifacts_app(
    build_app: Callable[..., FastAPI], test_session: AsyncSession, **settings_overrides: Any
) -> FastAPI:
    """Real `create_app()` wired for HTTP-level testing against a live DB."""
    app = build_app(**settings_overrides)
    app.dependency_overrides[get_db] = _db_override(test_session)
    return app


async def _mint_dev_bypass_token(client: AsyncClient, *, role: str) -> str:
    resp = await client.post("/auth/dev-bypass", json={"role": role})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


async def _get_artifacts(client: AsyncClient, *, token: str, program_id: str) -> Response:
    return await client.get(
        f"/api/artifacts/{program_id}", headers={"Authorization": f"Bearer {token}"}
    )


async def _seed_program_artifacts(test_session: AsyncSession, program_id: str) -> None:
    now = datetime.now(UTC)
    for i, artifact_type in enumerate(_CANONICAL_TYPES):
        test_session.add(
            ProgramArtifact(
                id=str(uuid.uuid4()),
                program_id=program_id,
                type=artifact_type,
                count=10 + i,
                as_of_timestamp=now,
            )
        )
    await test_session.commit()


def _percentile(sorted_values_ms: list[float], pct: float) -> float:
    """Nearest-rank percentile over an already-sorted list, in milliseconds.
    Mirrors `test_program_board.py::_percentile` (deterministic,
    dependency-free; per-file precedent, not shared/imported)."""
    n = len(sorted_values_ms)
    rank = math.ceil(pct * n)
    return sorted_values_ms[rank - 1]


# =============================================================================
# SHP-04-TC-11 -- performance: single indexed query, no N+1, p95 < 3000ms.
# =============================================================================


@pytest.mark.asyncio
async def test_artifacts_single_query_no_n_plus_one_tc11(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """SHP-04-TC-11 (query-budget half): exactly one SELECT runs against
    `program_artifacts` per request -- no per-type fan-out (`fetch_program_artifacts`'s
    single-query + O(5) Python zero-fill design), by counting the actual SQL
    statements sent to the driver."""
    await _seed_program_artifacts(test_session, _PROGRAM_ID)
    app = _build_artifacts_app(build_app, test_session)

    executed_statements: list[str] = []

    def _before_cursor_execute(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        if "program_artifacts" in statement:
            executed_statements.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        async with async_client_for(app) as client:
            token = await _mint_dev_bypass_token(client, role="architect")
            resp = await _get_artifacts(client, token=token, program_id=_PROGRAM_ID)
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", _before_cursor_execute)

    assert resp.status_code == 200, resp.text
    assert len(executed_statements) == _QUERY_COUNT_BUDGET, (
        f"expected exactly {_QUERY_COUNT_BUDGET} program_artifacts statement(s) "
        f"(single query, no per-type fan-out), got {len(executed_statements)}: "
        f"{executed_statements}"
    )


@pytest.mark.asyncio
async def test_artifacts_p95_latency_under_budget_tc11(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """SHP-04-TC-11 (latency half): 10 sequential requests against a program
    seeded with all 5 artifact types -- p95 latency stays under the 3000ms
    panel-render budget (REQUIREMENTS.md NFR-001 / test_data.latency_budget_ms).
    Honest measurement: the real number is printed and asserted, never hidden
    by loosening the budget."""
    await _seed_program_artifacts(test_session, _PROGRAM_ID)
    app = _build_artifacts_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="architect")

        latencies_ms: list[float] = []
        for _ in range(_PERF_MEASURED_REQUESTS):
            started = time.perf_counter()
            resp = await _get_artifacts(client, token=token, program_id=_PROGRAM_ID)
            elapsed_ms = (time.perf_counter() - started) * 1000
            assert resp.status_code == 200, resp.text
            latencies_ms.append(elapsed_ms)

    latencies_ms.sort()
    p95 = _percentile(latencies_ms, 0.95)

    print(
        f"\nSHP-04-TC-11 baseline -- GET /api/artifacts/{_PROGRAM_ID} p95={p95:.2f}ms "
        f"across {_PERF_MEASURED_REQUESTS} requests (budget {_LATENCY_BUDGET_MS}ms)"
    )
    assert p95 < _LATENCY_BUDGET_MS, (
        f"GET /api/artifacts/{{program_id}} p95 latency {p95:.2f}ms exceeded the "
        f"SHP-04-TC-11 budget of {_LATENCY_BUDGET_MS}ms across "
        f"{_PERF_MEASURED_REQUESTS} measured requests. Do not relax this budget; "
        "report the measured p95 for escalation/optimization."
    )
