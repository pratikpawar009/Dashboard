"""Performance test for `POST /api/admin/scan-repos` -- ING-07-TC-16
(`ING-07-NFR-performance`): end-to-end scan latency for a 200-repo org
(2 list pages x 100 + 200 per-repo probes) stays p95 <= 10 000 ms at a
deterministic 20 ms per-call upstream latency.

Structure mirrors this repo's other perf tests (`tests/perf/test_programs_perf.py`,
`tests/perf/test_ingest_token_auth_perf.py`): plain `time.perf_counter()`, no
dedicated benchmark tool or new dependency (PLAN.md §7 requires no runner
installation); `_percentile` copied rather than imported per this repo's
per-file precedent (reusability-baseline.md: "extract on the third
repetition, not the first" -- scoped to a module's own repeated code, not
cross-file duplication of a five-line, dependency-free helper).

Real end-to-end path, not a throwaway route: this measures the actual
`/api/admin/scan-repos` router (`app/api/admin.py`) mounted by the real
`create_app` factory (D-07 `build_app`/`async_client_for` fixtures,
`tests/conftest.py`). Delegates to `app/services/repo_scan.py::scan_org_repos`
verbatim -- list-repos pagination, per-repo probe loop, rollup upsert, real
`get_db` request-scoped session. `app.core.db.get_db` is overridden
(`app.dependency_overrides`) to serve sessions from the disposable
`test_engine` (`tests/conftest.py`), so the router's commit lands on the
test database, not the app's dev-DB-bound engine.

Deterministic upstream latency, not real network: `respx` intercepts every
GitHub URL and returns a canned 200 after `await asyncio.sleep(0.02)` per
probe (via the `github_contents_program_yaml_200_latency` fixture's async
side effect). The list-repos routes return immediately with no injected
delay -- TC-16 only pins per-probe latency at 20 ms. `respx_mock` is opened
with `assert_all_mocked=True` (`tests/conftest.py`) so any leak to the real
network raises at request time rather than silently degrading the measured
p95 with real DNS/TCP latency.

No `no_sleep` fixture: TC-16 uses REAL `asyncio.sleep(0.02)` per probe as
the mechanism that produces the target latency profile -- patching it out
would collapse the measurement to instant. The retry-backoff path
(`app.core.retry`) is never entered because every mocked response is 200,
so the fact that its `asyncio.sleep` remains real costs nothing here.

Serial probe cost: `scan_org_repos` iterates repos serially (single
`for entry in repos:` loop, `app/services/repo_scan.py`), so 200 probes at
20 ms each is ~4 s per scan of upstream-blocking time -- well under the
10 s budget with headroom for router/service/DB overhead. N=30 iterations
per TC-16 gives a ~2-3 minute total test runtime; the file is opt-in via
`-m perf` per this repo's `[tool.pytest.ini_options]` addopts.

Rollup upsert is on the measured path (each iteration commits one
`org_summary_rollup` upsert per scan_org_repos -> router-commit). TC-16's
third expected result asserts the final row has `repos_total=200` after
the loop, which also proves the upsert path completed on every iteration.

Honest measurement: if the p95 budget breaches, that is reported as a
finding with the measured number -- not hidden by loosening the budget,
adding unrequested warm-up iterations, or trimming outliers to get under
the line.
"""

from __future__ import annotations

import math
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager

import pytest
import respx
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.db import get_db
from app.models.rollup import OrgSummaryRollup
from tests.conftest import AlembicRunner, SeededIngestToken

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

# ING-07-TC-16 test_data -- do not relax.
REPO_COUNT = 200
ITERATIONS = 30
PER_CALL_LATENCY_S = 0.02
P95_BUDGET_MS = 10_000.0

# Singleton org_id `_upsert_org_rollup` writes -- matches conftest's
# `_ADMIN_SCAN_ORG_ID` and the `org_summary_rollup_seed` fixture row.
_ORG_ID = "org-1"


def _percentile(sorted_values_ms: list[float], pct: float) -> float:
    """Nearest-rank percentile over an already-sorted list, in milliseconds.

    index = ceil(pct * N) - 1 -- copied from `test_programs_perf.py::_percentile`
    / `test_ingest_token_auth_perf.py::_percentile` (same deterministic,
    dependency-free method; no numpy/statistics.quantiles interpolation
    ambiguity to document).
    """
    n = len(sorted_values_ms)
    rank = math.ceil(pct * n)
    return sorted_values_ms[rank - 1]


@pytest.mark.perf
@pytest.mark.asyncio
async def test_scan_repos_p95_under_10s_at_200_repo_baseline_tc16(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    ingest_token_wildcard: SeededIngestToken,
    org_summary_rollup_seed: OrgSummaryRollup,
    settings_github_configured: dict[str, object],
    github_list_repos_paginated_2pages: Callable[..., tuple[respx.Route, respx.Route]],
    github_contents_program_yaml_200_latency: Callable[..., respx.Route],
) -> None:
    """ING-07-TC-16: 200-repo org (2 list pages x 100), 20 ms mocked probe
    latency, N=30 measured `POST /api/admin/scan-repos` calls -- p95 must
    stay under `P95_BUDGET_MS`. See module docstring for the full setup
    rationale.
    """
    # Mount respx routes -- both fixtures share the module-scoped `respx_mock`
    # router (`tests/conftest.py`), so all three routes coexist in one mock.
    github_list_repos_paginated_2pages()
    github_contents_program_yaml_200_latency(latency_s=PER_CALL_LATENCY_S)

    app = build_app(**settings_github_configured)

    # Serve one fresh session per request from the test engine so the
    # router's rollup upsert lands on the test DB, matching prod's
    # request-scoped `get_db` semantics. Mirrors `test_programs_perf.py`'s
    # override shape.
    test_session_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    headers = {"Authorization": f"Bearer {ingest_token_wildcard.bearer}"}

    latencies_ms: list[float] = []
    async with async_client_for(app) as client:
        for _ in range(ITERATIONS):
            started = time.perf_counter()
            resp = await client.post("/api/admin/scan-repos", headers=headers)
            elapsed_ms = (time.perf_counter() - started) * 1000
            assert resp.status_code == 200, resp.text
            latencies_ms.append(elapsed_ms)

    # TC-16 expected result 3: final rollup row has repos_total=200.
    # Refresh the seed row from the DB -- `test_session` is a separate
    # session from the router's request-scoped sessions above, so the
    # in-memory `org_summary_rollup_seed` instance still holds the sentinel
    # values from fixture setup; the committed row does not.
    await test_session.commit()  # end any pending fixture tx before re-reading
    result = await test_session.execute(
        sa.select(OrgSummaryRollup).where(OrgSummaryRollup.org_id == _ORG_ID)
    )
    final_row = result.scalar_one()
    await test_session.refresh(final_row)
    assert final_row.repos_total == REPO_COUNT, (
        f"expected final rollup repos_total={REPO_COUNT} after {ITERATIONS} "
        f"scans, got {final_row.repos_total} -- the measured latency would "
        "not reflect TC-16's 200-repo baseline if the scan did not fully "
        "process every repo"
    )

    latencies_ms.sort()
    p95 = _percentile(latencies_ms, 0.95)

    # Capture the measured baseline for future optimization stories, visible
    # with `pytest -s` (mirrors `test_programs_perf.py`'s baseline print).
    print(
        f"\nING-07-TC-16 baseline -- p95={p95:.2f}ms across {ITERATIONS} "
        f"scans (200 repos, {int(PER_CALL_LATENCY_S * 1000)}ms per-probe "
        f"latency); min={latencies_ms[0]:.2f}ms max={latencies_ms[-1]:.2f}ms"
    )

    assert p95 <= P95_BUDGET_MS, (
        f"POST /api/admin/scan-repos p95 latency {p95:.2f}ms exceeded the "
        f"ING-07-TC-16 / NFR-performance budget of {P95_BUDGET_MS:.0f}ms "
        f"across {ITERATIONS} calls at the 200-repo / 20ms-per-probe "
        "baseline. Do not relax this budget or trim outliers to get under "
        "the line; report the measured number as a finding for the engineer."
    )
