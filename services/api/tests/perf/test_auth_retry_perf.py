"""Performance tests for the bounded-retry + backoff/jitter policy on
outbound Keycloak calls — AUTH-01-TC-30.

DB-free: the retry policy under test (`app/core/retry.py::retry_with_backoff`,
consumed by `app/auth/oidc.py::_post_token_endpoint`) has no database
dependency (DATA-DESIGN §1/§2) — this file never imports
`migrated_db`/`test_session` and needs no Postgres. The only outbound call is
the mocked Keycloak token endpoint via `keycloak_mock` (`tests/conftest.py`).

Structure mirrors this repo's other perf tests
(`tests/perf/test_auth_jwks_perf.py`, `tests/perf/test_rollup_rebuild_perf.py`,
`tests/perf/test_range_pagination_perf.py`): plain `time.perf_counter()`, no
dedicated benchmark tool.

Scope — why `_post_token_endpoint` directly, not a full `/auth/refresh`
route round trip: same isolation rationale as `test_auth_jwks_perf.py` timing
`JwksCache.get_signing_key()` directly — this measures the retry/backoff/
timeout mechanism itself, not ASGI-dispatch or route-body overhead that
AUTH-01-NFR-performance does not attribute to this policy.
`_post_token_endpoint` (`app/auth/oidc.py`) and `app/auth/jwks.py`'s
`_fetch_and_cache` share byte-for-byte the same outbound-call rules (5s
timeout, `retry_with_backoff(max_attempts=3, base_delay_s=0.25)`, 4xx never
retries — see both modules' docstrings), so exercising either call site pins
the one shared policy; this file uses the token endpoint because
`tests/conftest.py` already exposes purpose-built mock helpers for it
(`token_transient_then_success` / `token_always_transient_error` /
`token_error`).

Route-level coverage already exists: `tests/unit/test_auth_refresh.py` (T-15,
TC-07/21/27/31) asserts the SAME attempt counts through the full
`/auth/refresh` route and separately asserts Keycloak-status-to-HTTP-status
mapping (e.g. a 4xx maps to a route-level 401). That status-mapping
assertion is deliberately NOT repeated here — this file's job is the TIMING
dimension TC-30 actually names: that backoff is genuinely applied (not a
fixed delay, not skipped), that its growth matches the pinned 250ms base,
and that every attempt carries an explicit 5s timeout. Attempt-count
assertions are retained anyway because they are the necessary complement
that makes each timing assertion meaningful — an elapsed-time bound alone
doesn't say how many attempts produced it.

Jitter (see `docs/features/AUTH-01/FLAGS.md` § AF-04 for the sibling perf
file's own timing trap, and `app/core/retry.py`): each retry sleep is
`random.uniform(0, delay)` — FULL jitter, not a fixed delay. A strict LOWER
bound on elapsed wall-clock time is therefore not a safe assertion — jitter
can legitimately draw ~0 for every retry (verified by hand: one run of the
exhausted-retry test below measured ~0.21s elapsed against a theoretical max
of 0.75s). An UPPER bound on elapsed time IS safe: the sum of maximum
per-attempt delays is fixed regardless of jitter's draw. To additionally
prove the exponential-growth FORMULA itself (not just an elapsed-time
envelope), one test below patches `random.uniform` deterministically
(records its ceiling argument, returns 0.0) instead of asserting on
wall-clock timing — the "seed or patch random.uniform deterministically"
option this task's brief names, chosen because it proves the exact growth
sequence (250ms, then 500ms) with zero flakiness, which timing alone cannot.

Timeout assertion: inspecting the constructed client's configured timeout is
more reliable than trying to trigger a real 5s timeout (which would also
make this file slow). `_post_token_endpoint` constructs a fresh
`httpx.AsyncClient(timeout=...)` per attempt (a local variable, not
injectable), so the timeout test below monkeypatches
`httpx.AsyncClient.__init__` to record the `timeout` kwarg every time a
client is constructed. Verified by hand that this coexists safely with
`respx`: respx intercepts at the transport layer, not by replacing
`AsyncClient` itself, so a captured `timeout` alongside a working
respx-mocked response is not a coincidence of mocking order.
"""

from __future__ import annotations

import random
import time
from typing import Any

import httpx
import pytest

from app.auth.oidc import _post_token_endpoint
from tests.conftest import TEST_OIDC_ISSUER, KeycloakCallSpy, KeycloakMock

# AUTH-01-TC-30 test_data — do not relax.
PINNED_TIMEOUT_SECONDS = 5.0  # test_data.timeout_s
PINNED_MAX_RETRIES = 2  # test_data.max_retries
PINNED_TOTAL_ATTEMPTS = PINNED_MAX_RETRIES + 1  # 1 initial + 2 retries = 3
PINNED_BACKOFF_BASE_SECONDS = 0.25  # test_data.backoff_base_ms

# Exponential-backoff formula from app/core/retry.py::retry_with_backoff:
#   delay(attempt) = min(max_delay_s, base_delay_s * 2 ** (attempt - 1))
# With base_delay_s=0.25 and PINNED_TOTAL_ATTEMPTS=3 (attempts 1 and 2 sleep;
# attempt 3 is the last and never sleeps), the two per-attempt delay
# ceilings are:
EXPECTED_BACKOFF_CEILINGS = [
    PINNED_BACKOFF_BASE_SECONDS * (2**0),  # 0.25s, after attempt 1
    PINNED_BACKOFF_BASE_SECONDS * (2**1),  # 0.50s, after attempt 2
]
# Upper bound for the exhausted-retry case's wall-clock elapsed time: the sum
# of the maximum possible jittered delays, plus headroom for the mocked HTTP
# round trips and Python/event-loop overhead. A LOWER bound is not safe here
# — see module docstring on full jitter.
MAX_POSSIBLE_BACKOFF_SECONDS = sum(EXPECTED_BACKOFF_CEILINGS)  # 0.75s
ELAPSED_UPPER_BOUND_SECONDS = MAX_POSSIBLE_BACKOFF_SECONDS + 0.5  # 1.25s

_REFRESH_FORM_DATA = {
    "grant_type": "refresh_token",
    "refresh_token": "test-refresh-token",
    "client_id": "dashboard-web",
    "client_secret": "test-client-secret",
}


@pytest.mark.asyncio
async def test_persistent_transient_fault_bounds_attempts_at_pinned_maximum(
    keycloak_mock: KeycloakMock,
    keycloak_call_spy: KeycloakCallSpy,
) -> None:
    """AUTH-01-TC-30: a Keycloak call that fails transiently on every
    attempt makes EXACTLY `PINNED_TOTAL_ATTEMPTS` (3) outbound calls, never
    more.

    "Bounded" is the safety property under test: an unbounded retry loop
    against a struggling IdP is an outage amplifier
    (.claude/rules/performance-baseline.md "Every retry has bounded
    attempts"). Also captures elapsed wall-clock time, asserted against
    `ELAPSED_UPPER_BOUND_SECONDS` — see module docstring for why only an
    upper bound is safe under full jitter.
    """
    keycloak_mock.token_always_transient_error()

    started = time.perf_counter()
    with pytest.raises(httpx.HTTPError):
        await _post_token_endpoint(TEST_OIDC_ISSUER, _REFRESH_FORM_DATA)
    elapsed = time.perf_counter() - started

    keycloak_call_spy.assert_call_count(keycloak_mock.token_route, PINNED_TOTAL_ATTEMPTS)
    assert elapsed < ELAPSED_UPPER_BOUND_SECONDS, (
        f"exhausted-retry elapsed time {elapsed:.3f}s exceeded the upper bound of "
        f"{ELAPSED_UPPER_BOUND_SECONDS:.3f}s ({MAX_POSSIBLE_BACKOFF_SECONDS:.3f}s max possible "
        "backoff + 0.5s headroom). A lower bound is deliberately not asserted here — "
        "retry_with_backoff uses full jitter (random.uniform(0, delay)), so a run where every "
        "jitter draw is ~0 is a legitimate, non-flaky outcome, not a bug. Do not relax this "
        "upper bound; investigate a real regression instead."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_attempts", [0, 1, 2])
async def test_transient_fault_that_clears_succeeds_with_exact_call_count(
    failing_attempts: int,
    keycloak_mock: KeycloakMock,
    keycloak_call_spy: KeycloakCallSpy,
) -> None:
    """AUTH-01-TC-30: a transient fault that clears on attempt N succeeds,
    and the observed call count is exactly N — no extra attempt is made once
    a call has already succeeded. `failing_attempts=2` is TC-30's own pinned
    scenario (fails on attempts 1-2, succeeds on the 3rd); 0 and 1 are
    included to prove the "no extra attempts after success" property holds
    at every recovery point, not only the pinned one.
    """
    keycloak_mock.token_transient_then_success(failures=failing_attempts)

    response = await _post_token_endpoint(TEST_OIDC_ISSUER, _REFRESH_FORM_DATA)

    assert response.status_code == 200
    keycloak_call_spy.assert_call_count(keycloak_mock.token_route, failing_attempts + 1)


@pytest.mark.asyncio
async def test_4xx_response_makes_exactly_one_attempt_with_no_backoff_delay(
    keycloak_mock: KeycloakMock,
    keycloak_call_spy: KeycloakCallSpy,
) -> None:
    """AUTH-01-TC-30 / DATA-DESIGN §8: a 4xx response from Keycloak is never
    fed into the retry loop, so it produces EXACTLY ONE outbound call and no
    backoff sleep.

    `tests/unit/test_auth_refresh.py::test_4xx_refresh_error_never_retried_tc31`
    (T-15) already asserts this call count at the route level and separately
    asserts the route's 4xx-to-401 status mapping — that status-mapping
    assertion is deliberately NOT repeated here. This test's job is the
    timing/attempt-count property: near-zero elapsed time is direct evidence
    that no backoff sleep occurred, which a call-count-only assertion cannot
    show (a buggy retry loop that immediately re-raised without sleeping
    would still pass a call-count-only check).
    """
    keycloak_mock.token_error(status_code=400)

    started = time.perf_counter()
    response = await _post_token_endpoint(TEST_OIDC_ISSUER, _REFRESH_FORM_DATA)
    elapsed = time.perf_counter() - started

    # Sanity that `_post_token_endpoint` returned the 4xx untouched (it must
    # not raise for a 4xx) — the route-level 4xx-to-401 mapping itself is
    # T-15's assertion, not repeated here.
    assert response.status_code == 400
    keycloak_call_spy.assert_call_count(keycloak_mock.token_route, 1)
    assert elapsed < PINNED_BACKOFF_BASE_SECONDS, (
        f"a single 4xx attempt took {elapsed * 1000:.2f}ms, at or above the "
        f"{PINNED_BACKOFF_BASE_SECONDS * 1000:.0f}ms backoff base — suggests a backoff sleep ran "
        "even though a 4xx response must never retry."
    )


@pytest.mark.asyncio
async def test_backoff_delays_follow_the_pinned_exponential_formula(
    monkeypatch: pytest.MonkeyPatch,
    keycloak_mock: KeycloakMock,
) -> None:
    """AUTH-01-TC-30: backoff grows exponentially from the pinned 250ms base
    (`app/core/retry.py::retry_with_backoff`:
    `base_delay_s * 2 ** (attempt - 1)`), not a fixed constant delay —
    proven deterministically rather than via wall-clock timing.

    Chosen approach (see module docstring): patch `random.uniform` to
    record its delay-ceiling argument and return 0.0, instead of asserting
    on elapsed time. `retry_with_backoff` calls `random.uniform(0, delay)` —
    full jitter — so the actual sleep DURATION is random by design and
    cannot itself prove the formula; the CEILING passed into
    `random.uniform` is deterministic and is what this test captures.
    """
    keycloak_mock.token_always_transient_error()
    recorded_ceilings: list[float] = []
    patched_uniform = random.uniform

    def _record_ceiling_and_skip_sleep(low: float, high: float) -> float:
        assert low == 0.0, "expected full jitter's lower bound to stay 0"
        recorded_ceilings.append(high)
        return 0.0

    monkeypatch.setattr(random, "uniform", _record_ceiling_and_skip_sleep)

    with pytest.raises(httpx.HTTPError):
        await _post_token_endpoint(TEST_OIDC_ISSUER, _REFRESH_FORM_DATA)

    # Sanity: the patch was actually installed (guards against a silent
    # monkeypatch target-path typo making this test vacuously pass).
    assert random.uniform is not patched_uniform
    assert recorded_ceilings == EXPECTED_BACKOFF_CEILINGS, (
        f"expected backoff delay ceilings {EXPECTED_BACKOFF_CEILINGS} (exponential from the "
        f"{PINNED_BACKOFF_BASE_SECONDS}s pinned base, one per retry), got {recorded_ceilings}"
    )


@pytest.mark.asyncio
async def test_every_outbound_attempt_carries_the_pinned_explicit_timeout(
    monkeypatch: pytest.MonkeyPatch,
    keycloak_mock: KeycloakMock,
    keycloak_call_spy: KeycloakCallSpy,
) -> None:
    """AUTH-01-TC-30: every outbound call is configured with the pinned 5s
    explicit timeout, never httpx's library default (no timeout at all).

    Chosen approach (see module docstring): inspecting the constructed
    client's configured `timeout` kwarg is more reliable than trying to
    trigger a genuine 5s timeout, which would also make this test slow.
    `httpx.AsyncClient.__init__` is monkeypatched to record every `timeout`
    kwarg passed to it; verified by hand that this coexists with `respx`'s
    mocking, which intercepts at the transport layer rather than replacing
    `AsyncClient` itself. Runs against the retry-exhaustion scenario so the
    assertion covers EVERY attempt (`PINNED_TOTAL_ATTEMPTS` of them), not
    just the first.
    """
    keycloak_mock.token_always_transient_error()
    captured_timeouts: list[Any] = []
    real_init = httpx.AsyncClient.__init__

    def _capture_timeout(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
        captured_timeouts.append(kwargs.get("timeout"))
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _capture_timeout)

    with pytest.raises(httpx.HTTPError):
        await _post_token_endpoint(TEST_OIDC_ISSUER, _REFRESH_FORM_DATA)

    keycloak_call_spy.assert_call_count(keycloak_mock.token_route, PINNED_TOTAL_ATTEMPTS)
    assert captured_timeouts == [PINNED_TIMEOUT_SECONDS] * PINNED_TOTAL_ATTEMPTS, (
        f"expected every one of {PINNED_TOTAL_ATTEMPTS} outbound attempts to construct its "
        f"httpx.AsyncClient with timeout={PINNED_TIMEOUT_SECONDS}, got {captured_timeouts} — an "
        "attempt using the library default (no timeout) would silently violate the I/O-bound "
        "budget (AUTH-01-NFR-performance / .claude/rules/performance-baseline.md)."
    )
