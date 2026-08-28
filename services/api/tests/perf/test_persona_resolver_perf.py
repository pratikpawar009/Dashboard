"""Performance tests for `app/core/persona_resolver.py`'s `PersonaResolver` —
AUTH-02-TC-12 (warm cache hit, p99 < 1ms) and AUTH-02-TC-13 (cold Tier-3 hit,
p95 < 100ms), per REQUIREMENTS.md § Non-functional requirements.

Structure mirrors this repo's other perf tests (`tests/perf/test_auth_jwks_perf.py`,
`tests/perf/test_auth_retry_perf.py`, `tests/perf/test_range_pagination_perf.py`,
`tests/perf/test_rollup_rebuild_perf.py`): plain `time.perf_counter()`, no
dedicated benchmark tool. `_percentile` below is copied from
`test_range_pagination_perf.py::_percentile` rather than imported — this
repo's existing perf files each keep their own small copy instead of a shared
`perf_utils` module, and there's no third one yet to justify introducing one
(reusability-baseline.md: "extract on the third repetition, not the first").

TC-12 is DB-free (cache is seeded directly per its own step "Seed cache with
('cio', 'cio', now+300s)", matching its precondition "Role already resolved
and cached" — no tier lookup is exercised at all). TC-13 requires a live,
migrated Postgres (`migrated_db`/`test_engine`, `tests/conftest.py`) per its
own precondition "Postgres is running and responsive" — D-06's injectable
`session_factory` seam points `PersonaResolver` at the disposable test DB
instead of the dev `SessionLocal`, matching T-07's
`PersonaResolver(session_factory=async_sessionmaker(bind=test_engine))`
convention.

No warm-up prefix is discarded in either test (unlike
`test_range_pagination_perf.py`'s 5-request warmup, which is legitimate
precedent for doing so where a test's own steps call for it) — TC-12's and
TC-13's own `steps` each specify an exact number of *consecutive measured*
calls with no separate warmup phase, and TC-12's precondition is already a
warm cache, so there's no cold-start effect to prime away.

Logging and the warm-path budget (TC-12): `PersonaResolver._log_resolution`
unconditionally emits an INFO `persona_mapping_loaded` record on every
successful `resolve()` call, including cache hits (FR-5) — a deliberate
correction during implementation, not accidental overhead to exclude from
the timed window. Neither test here imports `app.main`, so absent explicit
setup the root logger stays in Python's unconfigured default state (no
handler, effective level WARNING) and that INFO call would short-circuit at
`Logger.isEnabledFor(INFO)` before any formatting or I/O — a "null-handler"
run that understates what a deployed process actually pays. The
`production_logging` fixture below instead configures the same JSON-stdout
handler `app.main`'s `create_app()` sets up at import time
(`app/core/logging.py::configure_logging`), so both tests' measured numbers
include the real formatted-and-written cost a caller experiences in
production — see that fixture's docstring for the restore mechanics.

Honest measurement: if either budget breaches under this configuration, that
is reported as a finding with the measured number — not hidden by loosening
the budget, adding unrequested warm-up iterations, or stubbing out the
logger.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Iterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.logging import configure_logging
from app.core.persona_resolver import PersonaResolver
from app.models.ingestion import PersonaConfig
from tests.conftest import AlembicRunner

# AUTH-02-TC-12 test_data — do not relax.
WARM_ITERATIONS = 100
WARM_P99_BUDGET_MS = 1.0
WARM_CACHE_ROLE = "cio"
WARM_CACHE_PERSONA = "cio"
# Arbitrary valid tier label for the seeded cache entry — only affects the
# `tier` field on the emitted persona_mapping_loaded log event, not timing.
WARM_CACHE_TIER = "tier-1-env"

# AUTH-02-TC-13 test_data — do not relax.
COLD_ITERATIONS = 10
COLD_P95_BUDGET_MS = 100.0
COLD_ROLE = "architect"


@pytest.fixture
def production_logging() -> Iterator[None]:
    """Configure the same JSON-stdout logging `create_app()` sets up at
    import time (`app/core/logging.py::configure_logging`), then restore the
    previous root-logger state so this doesn't leak into other test files
    sharing this pytest session.

    Level is forced to INFO explicitly after `configure_logging()` (not left
    to `settings.log_level`) so the measurement is deterministic regardless
    of a local `.env`'s `LOG_LEVEL` override — this fixture's whole purpose
    is guaranteeing the INFO-level `persona_mapping_loaded` call actually
    formats and writes during the timed window, every run.
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

    index = ceil(pct * N) - 1 — copied from
    `test_range_pagination_perf.py::_percentile` (same deterministic,
    dependency-free method; no numpy/statistics.quantiles interpolation
    ambiguity to document). Note for small N (TC-13's N=10): ceil(0.95*10)=10,
    so p95 there is the 10th/maximum value, not an approximation — expected,
    not a bug, at this sample size.
    """
    n = len(sorted_values_ms)
    rank = math.ceil(pct * n)
    return sorted_values_ms[rank - 1]


@pytest.mark.asyncio
@pytest.mark.usefixtures("production_logging")
async def test_warm_cache_hit_latency_baseline_p99_under_1ms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AUTH-02-TC-12: a warm, non-expired cache entry for `WARM_CACHE_ROLE`
    resolves in p99 < `WARM_P99_BUDGET_MS` across `WARM_ITERATIONS` calls.

    Cache is seeded directly rather than primed via a real `resolve()` call
    (TC-12's own step), so this needs no Tier-1/2/3 lookup and no database.
    `_resolve_uncached` is monkeypatched to raise if the fast path ever calls
    it — proof the warm hit never consults any tier (TC-12 expected_results
    "No Tier-3 queries executed", asserted here more strongly: no tier at
    all, matching the fast path documented in `PersonaResolver.resolve`).
    """
    resolver = PersonaResolver(Settings())

    async def _fail_if_uncached_resolution_attempted(role: str) -> tuple[str, str]:
        raise AssertionError(
            "warm cache hit invoked _resolve_uncached -- expected the fast "
            "path to return before consulting any tier (AC-5)"
        )

    monkeypatch.setattr(resolver, "_resolve_uncached", _fail_if_uncached_resolution_attempted)
    resolver._cache[WARM_CACHE_ROLE] = (
        WARM_CACHE_PERSONA,
        WARM_CACHE_TIER,
        time.monotonic() + 300.0,
    )

    latencies_ms: list[float] = []
    for _ in range(WARM_ITERATIONS):
        started = time.perf_counter()
        persona = await resolver.resolve(WARM_CACHE_ROLE)
        elapsed_ms = (time.perf_counter() - started) * 1000
        assert persona == WARM_CACHE_PERSONA
        latencies_ms.append(elapsed_ms)

    latencies_ms.sort()
    p99 = _percentile(latencies_ms, 0.99)

    assert p99 < WARM_P99_BUDGET_MS, (
        f"warm cache hit p99 latency {p99:.4f}ms exceeded the AUTH-02-TC-12 / "
        f"NFR-performance budget of {WARM_P99_BUDGET_MS}ms across {WARM_ITERATIONS} "
        "calls, including the mandatory persona_mapping_loaded log call (FR-5), "
        "measured with real production log formatting+write (see production_logging "
        "fixture). Do not relax this budget or exclude the log call to get under "
        "the line; investigate a real regression, e.g. in _log_resolution's "
        "field-building or JSONFormatter.format()."
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("production_logging")
async def test_cold_tier3_hit_latency_baseline_p95_under_100ms(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AUTH-02-TC-13: `COLD_ITERATIONS` cold Tier-3 lookups for `COLD_ROLE`,
    cache cleared before every call (TC-13 step "with cache cleared between
    each"), resolve in p95 < `COLD_P95_BUDGET_MS`.

    Live Postgres via `migrated_db`/`test_engine` — TC-13's precondition
    explicitly requires a real, responsive Postgres, not a mock.
    `_resolve_tier3` is wrapped (not replaced) to count calls, proving
    exactly one Tier-3 query ran per cleared-cache call (TC-13
    expected_results).
    """
    test_session.add(PersonaConfig(role=COLD_ROLE, persona=COLD_ROLE))
    await test_session.commit()

    resolver = PersonaResolver(
        Settings(),
        session_factory=async_sessionmaker(bind=test_engine, expire_on_commit=False),
    )

    tier3_call_count = 0
    original_resolve_tier3 = resolver._resolve_tier3

    async def _counting_resolve_tier3(role: str) -> str | None:
        nonlocal tier3_call_count
        tier3_call_count += 1
        return await original_resolve_tier3(role)

    monkeypatch.setattr(resolver, "_resolve_tier3", _counting_resolve_tier3)

    latencies_ms: list[float] = []
    for _ in range(COLD_ITERATIONS):
        resolver._cache.clear()
        started = time.perf_counter()
        persona = await resolver.resolve(COLD_ROLE)
        elapsed_ms = (time.perf_counter() - started) * 1000
        assert persona == COLD_ROLE
        latencies_ms.append(elapsed_ms)

    assert tier3_call_count == COLD_ITERATIONS, (
        f"expected exactly {COLD_ITERATIONS} Tier-3 queries (one per cleared-cache "
        f"call, TC-13 expected_results), got {tier3_call_count}"
    )

    latencies_ms.sort()
    p95 = _percentile(latencies_ms, 0.95)

    assert p95 < COLD_P95_BUDGET_MS, (
        f"cold Tier-3 hit p95 latency {p95:.2f}ms exceeded the AUTH-02-TC-13 / "
        f"NFR-performance budget of {COLD_P95_BUDGET_MS}ms across {COLD_ITERATIONS} "
        "calls against a live Postgres persona_config lookup. Do not relax this "
        "budget; investigate a real regression (e.g. a missing index on "
        "persona_config.role, or connection-pool exhaustion)."
    )
