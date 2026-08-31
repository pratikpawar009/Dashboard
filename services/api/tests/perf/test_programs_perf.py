"""Performance test for GET /api/programs -- AUTH-04-TC-17
(`AUTH-04-NFR-performance`, research condition C-4): end-to-end latency
(persona resolution + DB query + serialization) stays p95 < 300ms at a
100-program / 50-scoped baseline.

Structure mirrors this repo's other perf tests (`tests/perf/test_rbac_perf.py`,
`tests/perf/test_persona_resolver_perf.py`): plain `time.perf_counter()`, no
dedicated benchmark tool -- this task's own file-plan reason names those two
files as the pattern to match, and no new runner/tooling is introduced here.
`_percentile` below is copied rather than imported, per this repo's
established precedent of each perf file keeping its own small copy instead
of a shared `perf_utils` module (reusability-baseline.md: "extract on the
third repetition, not the first" -- scoped to a module's own repeated code,
not cross-file duplication of a five-line, dependency-free helper).

Real end-to-end path, not a throwaway route: this measures the actual
`/api/programs` router (`app/api/programs.py`) mounted by the real
`create_app` factory (D-07 `build_app`/`async_client_for` fixtures,
`tests/conftest.py`), driven through a real bearer token minted by
`POST /auth/dev-bypass` (same pattern as `tests/unit/test_auth_dev_bypass.py`
TC-40) -- not a hand-forged JWT and not a mocked Keycloak. The DB query
itself is real: `app.core.db.get_db` is overridden (`app.dependency_overrides`)
to serve sessions from the disposable `migrated_db`/`test_engine` test
database (`tests/conftest.py`) that this test seeds with 100 `program_summary`
rows, instead of the app's own dev-DB-bound engine.

Only the persona resolver is a stub -- TC-17's own precondition: "Stub
persona resolver resolves immediately (no simulated I/O); the DB query
itself is real, not mocked." A minimal, local `_StubPersonaResolver`
(mirrors `test_rbac_perf.py::_StubPersonaResolver`) is installed onto
`app.state.persona_resolver` (the same seam `app/core/persona_resolver.py`'s
`get_persona_resolver` reads) after `build_app()` constructs the app's real
one -- this bypasses only Tier-1/2/3 persona-mapping I/O, not the veto-gate
call: `app.core.rbac.program_visibility` (called once per request by the
route, FR-2) never consults the persona resolver at all (open-aggregate
check, AUTH-03 D-03; see `test_rbac_perf.py` module docstring), so
`rbac.configure()`'s state (still pointed at the real resolver `create_app`
built) is never exercised by this endpoint either way.

Non-cio persona, scoped to 50 of 100: the dev-bypass token is minted with
`programs=` set to 50 of the 100 seeded `program_id`s (mapped to `groups`
via `PROGRAM_GROUP_PREFIX`, parsed back by `get_current_user`, AUTH-01-FR-5)
and a role the stub resolver maps to a fixed non-`cio` persona -- the
`cio`-sees-all path would skip the `WHERE program_id IN (...)` scoping
clause TC-17 is measuring.

Logging cost is part of the timed window, not excluded: the route
unconditionally emits an INFO `programs_list_returned` record on every call
(FR-1). The `production_logging` fixture (copied from
`test_persona_resolver_perf.py`/`test_rbac_perf.py` -- same rationale,
restore mechanics, JSON-stdout `configure_logging()` setup) ensures it
actually formats and writes rather than short-circuiting at
`Logger.isEnabledFor(INFO)` with no handler attached, so the measured
numbers include the real cost a deployed process pays per request.

Token minting (`POST /auth/dev-bypass`) happens once, before the measured
loop -- TC-17's own steps measure only "GET /api/programs latency", not
sign-in.

Honest measurement: if the p95 budget breaches, that is reported as a
finding with the measured number -- not hidden by loosening the budget,
adding unrequested warm-up iterations, or reducing the iteration/row counts
TC-17 pins.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.db import get_db
from app.core.logging import configure_logging
from app.models.rollup import ProgramSummary
from tests.conftest import AlembicRunner

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

# AUTH-04-TC-17 test_data -- do not relax.
SEEDED_PROGRAM_COUNT = 100
SCOPED_PROGRAM_COUNT = 50
ITERATIONS = 50
P95_BUDGET_MS = 300.0

# Non-cio persona the stub resolver always returns -- the cio-sees-all path
# would skip the WHERE-clause scoping this test measures.
_STUB_PERSONA = "developer"
_DEV_BYPASS_ROLE = "developer"


@pytest.fixture
def production_logging() -> Iterator[None]:
    """Configure the same JSON-stdout logging `create_app()` sets up at
    import time (`app/core/logging.py::configure_logging`), then restore the
    previous root-logger state so this doesn't leak into other test files
    sharing this pytest session.

    Copied from `test_persona_resolver_perf.py`/`test_rbac_perf.py` --
    identical rationale: without a real handler attached, an INFO-level call
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


def _percentile(sorted_values_ms: list[float], pct: float) -> float:
    """Nearest-rank percentile over an already-sorted list, in milliseconds.

    index = ceil(pct * N) - 1 -- copied from `test_rbac_perf.py::_percentile`
    / `test_persona_resolver_perf.py::_percentile` (same deterministic,
    dependency-free method; no numpy/statistics.quantiles interpolation
    ambiguity to document).
    """
    n = len(sorted_values_ms)
    rank = math.ceil(pct * n)
    return sorted_values_ms[rank - 1]


class _StubPersonaResolver:
    """Minimal local stub -- returns a fixed persona immediately, no I/O.

    Mirrors `test_rbac_perf.py::_StubPersonaResolver`. Installed onto
    `app.state.persona_resolver` (see module docstring) rather than passed
    to `rbac.configure()` -- `program_visibility` never reaches the resolver
    at all (see module docstring).
    """

    def __init__(self, persona: str) -> None:
        self._persona = persona

    async def resolve(self, role: str) -> str:
        return self._persona


def _build_program_summary(program_id: str) -> ProgramSummary:
    """One representative `program_summary` row -- field values are
    arbitrary (TC-17 doesn't assert on response content, only latency); only
    `program_id` needs to be unique per row and `as_of_timestamp` needs a
    real tz-aware datetime (`program_summary.as_of_timestamp` is NOT NULL,
    `app/models/rollup.py`).
    """
    now = datetime.now(UTC)
    return ProgramSummary(
        program_id=program_id,
        name=f"Program {program_id}",
        icon="rocket",
        type="engineering",
        description="perf-baseline seed row",
        monthly_token_sparkline=[],
        tokens=0,
        releases=0,
        features=0,
        active_contributors=0,
        repos_with_harness_installed=0,
        repos_total=0,
        commands_executed=0,
        lines_of_code_generated=0,
        user_stories_delivered=0,
        as_of_timestamp=now,
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("production_logging")
async def test_programs_list_p95_under_300ms_at_100_program_baseline_tc17(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """AUTH-04-TC-17 / C-4: 100 seeded `program_summary` rows, a non-cio
    persona scoped to 50 of them, 50 measured `GET /api/programs` calls --
    p95 must stay under `P95_BUDGET_MS`. See module docstring for the full
    setup rationale.
    """
    program_ids = [f"perf-prog-{i:03d}" for i in range(SEEDED_PROGRAM_COUNT)]
    for program_id in program_ids:
        test_session.add(_build_program_summary(program_id))
    await test_session.commit()

    scoped_program_ids = program_ids[:SCOPED_PROGRAM_COUNT]

    app = build_app()
    app.state.persona_resolver = _StubPersonaResolver(persona=_STUB_PERSONA)

    test_session_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    latencies_ms: list[float] = []
    async with async_client_for(app) as client:
        issue_resp = await client.post(
            "/auth/dev-bypass",
            json={"role": _DEV_BYPASS_ROLE, "programs": scoped_program_ids},
        )
        assert issue_resp.status_code == 200, issue_resp.text
        token = issue_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        last_body: dict[str, object] = {}
        for _ in range(ITERATIONS):
            started = time.perf_counter()
            resp = await client.get("/api/programs", headers=headers)
            elapsed_ms = (time.perf_counter() - started) * 1000
            assert resp.status_code == 200, resp.text
            last_body = resp.json()
            latencies_ms.append(elapsed_ms)

    returned_count = len(last_body["programs"])  # type: ignore[arg-type]
    assert returned_count == SCOPED_PROGRAM_COUNT, (
        f"expected {SCOPED_PROGRAM_COUNT} scoped programs in the response, "
        f"got {returned_count} -- the measured latency would not reflect "
        "TC-17's 50-scoped baseline if this scoping is wrong"
    )

    latencies_ms.sort()
    p95 = _percentile(latencies_ms, 0.95)

    # C-4: capture the measured baseline for future optimization stories,
    # visible with `pytest -s` (this task's own run instruction).
    print(
        f"\nAUTH-04-TC-17 baseline -- p95={p95:.2f}ms across {ITERATIONS} "
        f"calls (100 seeded / 50 scoped programs); "
        f"min={latencies_ms[0]:.2f}ms max={latencies_ms[-1]:.2f}ms"
    )

    assert p95 < P95_BUDGET_MS, (
        f"GET /api/programs p95 latency {p95:.2f}ms exceeded the AUTH-04-TC-17 "
        f"/ NFR-performance budget of {P95_BUDGET_MS}ms across {ITERATIONS} "
        "calls at the 100-program / 50-scoped baseline (persona resolution "
        "stubbed per TC-17 preconditions; DB query + serialization real). "
        "Do not relax this budget; report the measured baseline for "
        "escalation/optimization (research condition C-4)."
    )
