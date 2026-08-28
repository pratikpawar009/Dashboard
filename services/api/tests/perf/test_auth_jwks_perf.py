"""Performance tests for `app/auth/jwks.py`'s `JwksCache` — AUTH-01-TC-28, TC-29.

DB-free: `JwksCache` has no database dependency (DATA-DESIGN §1/§2) — this
file never imports `migrated_db`/`test_session` and needs no Postgres. The
only outbound call is the mocked Keycloak JWKS endpoint via `keycloak_mock`
(`tests/conftest.py`).

Structure mirrors this repo's two other perf tests
(`tests/perf/test_rollup_rebuild_perf.py`, `tests/perf/test_range_pagination_perf.py`):
plain `time.perf_counter()`, no dedicated benchmark tool.

TC-28 times `JwksCache.get_signing_key()` directly rather than a full
route/signature-verification round trip. DATA-DESIGN §8 ties the <10ms/<100ms
budgets to exactly this call ("Per-request JWT verification cost is the
performance-critical path: budget <10ms with a warm JWKS cache, <100ms on a
cold/uncached fetch") — an end-to-end route call would add RSA
signature-verification and ASGI-dispatch overhead this NFR does not budget
for here.

Cold-path mock latency (TC-28): the JWKS route is mocked with an immediate,
0-delay `return_value` response — no `asyncio.sleep` — so the cold-call
timing reflects `JwksCache`'s own logic (lock acquire, one httpx round trip
through respx's in-process transport, cache write), not an artificially
injected delay. This matches TC-28's own precondition: "JWKS endpoint mocked
with a fast, deterministic in-process response so the measurement isolates
validation-logic overhead."

Stampede case mock latency (AF-04, `docs/features/AUTH-01/FLAGS.md`): the
concurrent test below is the one case in this file that DOES need an
artificial delay. Verified by hand (see this task's scratch run) that a
purely synchronous mock response never yields control back to the event
loop: `asyncio.gather`-launched coroutines then run to completion one at a
time without ever genuinely overlapping, so a burst of N calls each
independently observes "nothing changed since I captured `_fetched_at`" and
each triggers its own fetch — 10 fetches instead of 1, a false failure
unrelated to the lock. Giving the mocked response a genuine
`await asyncio.sleep(...)` (an `async def` respx side effect) forces all N
waiters to actually be in-flight together, which is what exercises
`JwksCache`'s `asyncio.Lock`-guarded double-checked fetch at all. With the
sleep, the same 10-way burst collapses to exactly 1 fetch.
"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest
from fastapi import HTTPException

from app.auth.jwks import JwksCache
from app.core.config import Settings
from tests.conftest import TEST_OIDC_ISSUER, KeycloakCallSpy, KeycloakMock, RSATestKeypair

# AUTH-01-TC-28 test_data — do not relax.
BUDGET_COLD_SECONDS = 0.100  # test_data.budget_uncached_ms
BUDGET_WARM_MEAN_SECONDS = 0.010  # test_data.budget_cached_ms
WARM_ITERATIONS = 20  # test_data.warm_iterations

# AUTH-01-TC-29 test_data.missing_kid.
MISSING_KID = "test-kid-rotated"

# Stampede case: T-20 requirement 3 — N >= 10 simultaneous callers.
STAMPEDE_CONCURRENCY = 10

# Suspension point forced into the mocked JWKS response for the stampede case
# only (AF-04) — long enough that all STAMPEDE_CONCURRENCY tasks are
# scheduled and past their pre-lock cache read before the first one resumes.
STAMPEDE_MOCK_DELAY_SECONDS = 0.05


def _settings() -> Settings:
    """A minimal `Settings` with only `oidc_issuer` set.

    `JwksCache` reads exactly one `Settings` field (`oidc_issuer`) — see
    `app/auth/jwks.py::JwksCache._fetch_and_cache`. Passing it as a
    constructor kwarg wins over any ambient env var/`.env` value under
    pydantic-settings' documented precedence (kwargs > env > `.env` >
    defaults), so this is hermetic for the one field that matters here
    without needing the full `_HermeticSettings` dance
    `tests/unit/test_auth_config.py` uses for settings whose *other* fields
    are also under test.
    """
    return Settings(oidc_issuer=TEST_OIDC_ISSUER)


@pytest.mark.asyncio
async def test_jwt_validation_latency_cold_then_warm_within_budget(
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
) -> None:
    """AUTH-01-TC-28: cold (uncached) call < 100ms; mean of 20 warm
    (cached) calls < 10ms.

    Timing windows cover only the `get_signing_key` call each time, never
    fixture/mock setup — mirrors `test_rollup_rebuild_perf.py`'s convention
    of excluding seeding from the measured window.
    """
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    cache = JwksCache(_settings())
    kid = rsa_test_keypair.kid

    # Cache starts empty (TC-28 step "Clear the JWKS cache") — this first
    # call is the cold/uncached path.
    started = time.perf_counter()
    key = await cache.get_signing_key(kid)
    cold_elapsed = time.perf_counter() - started
    assert key["kid"] == kid

    assert cold_elapsed < BUDGET_COLD_SECONDS, (
        f"cold JWKS validation took {cold_elapsed * 1000:.2f}ms, exceeding "
        f"the AUTH-01-TC-28 budget of {BUDGET_COLD_SECONDS * 1000:.0f}ms. "
        "Headroom note: the mocked JWKS response has zero injected delay, so "
        "this budget is dominated by real per-call overhead (lock acquire, "
        "one respx-intercepted httpx.AsyncClient round trip, cache write) — "
        "not network latency. Do not relax; investigate a real regression."
    )

    warm_total = 0.0
    for _ in range(WARM_ITERATIONS):
        started = time.perf_counter()
        await cache.get_signing_key(kid)
        warm_total += time.perf_counter() - started
    warm_mean = warm_total / WARM_ITERATIONS

    assert warm_mean < BUDGET_WARM_MEAN_SECONDS, (
        f"mean warm JWKS validation took {warm_mean * 1000:.4f}ms over "
        f"{WARM_ITERATIONS} calls, exceeding the AUTH-01-TC-28 budget of "
        f"{BUDGET_WARM_MEAN_SECONDS * 1000:.0f}ms. The warm path does no "
        "I/O and no lock acquisition (JwksCache.get_signing_key's fast-path "
        "cache hit) — a regression here likely means the fast path started "
        "doing work it shouldn't. Do not relax; investigate."
    )


@pytest.mark.asyncio
async def test_unrecognized_kid_triggers_exactly_one_fresh_fetch_then_fails(
    keycloak_mock: KeycloakMock,
    keycloak_call_spy: KeycloakCallSpy,
    rsa_test_keypair: RSATestKeypair,
) -> None:
    """AUTH-01-TC-29: a cache holding a key set without `MISSING_KID`
    triggers exactly one fresh JWKS fetch, then a 401 — no retry/refetch
    loop even though the refetch also lacks the kid.
    """
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    cache = JwksCache(_settings())

    # Step 1 (precondition): warm the cache with a key set — TTL live,
    # `MISSING_KID` absent — via one ordinary fetch for the *known* kid.
    await cache.get_signing_key(rsa_test_keypair.kid)
    keycloak_call_spy.assert_call_count(keycloak_mock.jwks_route, 1)

    # Step 2: reset the fetch-count spy so the assertion below counts only
    # the fetch triggered by the missing-kid request that follows, not this
    # precondition warm-up call.
    keycloak_mock.jwks_route.reset()

    # Step 3: request `MISSING_KID`; the fresh refetch serves the same
    # document, which also does not contain it.
    with pytest.raises(HTTPException) as exc_info:
        await cache.get_signing_key(MISSING_KID)

    assert exc_info.value.status_code == 401
    keycloak_call_spy.assert_call_count(keycloak_mock.jwks_route, 1)


@pytest.mark.asyncio
async def test_concurrent_unrecognized_kid_requests_collapse_to_single_fetch(
    keycloak_mock: KeycloakMock,
    keycloak_call_spy: KeycloakCallSpy,
    rsa_test_keypair: RSATestKeypair,
) -> None:
    """AUTH-01-TC-29 (stampede case): `STAMPEDE_CONCURRENCY` simultaneous
    `get_signing_key()` calls for the same unrecognized kid produce exactly
    one fetch (D-04's `asyncio.Lock`-guarded double-checked fetch), not N.

    AF-04: the mocked JWKS response below uses an `async def` respx side
    effect with a genuine `await asyncio.sleep(...)` — verified by hand
    (scratch run, not committed) that without this delay the same burst
    produces 10 fetches (one per task, since a purely synchronous mock never
    lets the event loop interleave the gathered tasks), which would fail
    this assertion for a reason unrelated to the lock. With the delay, all
    `STAMPEDE_CONCURRENCY` tasks are genuinely in-flight together and the
    lock's single-fetch guarantee is what makes the count 1.
    """

    async def _delayed_jwks_response(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(STAMPEDE_MOCK_DELAY_SECONDS)
        return httpx.Response(200, json=rsa_test_keypair.jwks_document)

    keycloak_mock.jwks_route.mock(side_effect=_delayed_jwks_response)
    cache = JwksCache(_settings())

    results = await asyncio.gather(
        *(cache.get_signing_key(MISSING_KID) for _ in range(STAMPEDE_CONCURRENCY)),
        return_exceptions=True,
    )

    assert all(isinstance(r, HTTPException) and r.status_code == 401 for r in results), (
        f"expected every one of {STAMPEDE_CONCURRENCY} concurrent callers to "
        f"see a 401, got: {results!r}"
    )
    keycloak_call_spy.assert_call_count(keycloak_mock.jwks_route, 1)
