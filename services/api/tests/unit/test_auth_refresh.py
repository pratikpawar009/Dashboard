"""Unit tests for `app/auth/oidc.py`'s `POST /auth/refresh` route — AUTH-01-TC-06,
TC-07, TC-21, TC-27, TC-31 (AUTH-01-FR-6, AUTH-01-NFR-performance).

DB-free: the refresh route has no database dependency (DATA-DESIGN §1/§2) —
this file never imports `migrated_db`/`test_session`. Outbound calls
(Keycloak token endpoint, JWKS endpoint) are mocked via `keycloak_mock`
(`tests/conftest.py`); no real network call is ever made
(`assert_all_mocked=True` on that fixture guarantees it).

Boots the REAL app via `build_app`/`create_app` (D-07), exercising the actual
router wiring, CORS, and error-envelope registration exactly as production
does.

Log-capture idiom duplicated from `tests/unit/test_auth_callback.py` rather
than imported: this task's file scope is `test_auth_refresh.py` only, and
that file's helpers are module-private. See its module docstring for the
full rationale (why `configure_logging()` + `capsys`/`caplog` are unsafe:
`app.main`'s `configure_logging()` binds to `sys.stdout` at import time, and
`migrations/env.py`'s `fileConfig(disable_existing_loggers=True)` can
permanently disable this named logger in a shared test session) — forcing
`.disabled = False`/`.propagate = False` directly on the real
`app.auth.oidc` logger is the one idiom immune to both gotchas.

Never weakens an assertion to force a pass — see this task's returned
`flags` for anything observed but not in scope to fix here.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from contextlib import AbstractAsyncContextManager, contextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.logging import JSONFormatter
from tests.conftest import (
    TEST_OIDC_CLIENT_ID,
    TEST_OIDC_ISSUER,
    KeycloakCallSpy,
    KeycloakMock,
    RSATestKeypair,
)

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

# TC-27's pinned test_data (jwt_claims.sub) and the sentinel
# `_log_dashboard_login` falls back to on any decode/verify failure —
# asserted against directly so TC-27 never passes vacuously on the fallback.
_TC27_SUB = "user-42"
_FALLBACK_SENTINEL = "unknown"


def _configured_overrides(**overrides: Any) -> dict[str, Any]:
    """`build_app(**overrides)` kwargs for a fully OIDC-configured app.

    `oidc_client_secret` here is a fixture-only placeholder, never a real
    secret (`.claude/rules/security-baseline.md`) — this file only ever
    talks to the mocked Keycloak endpoints via `keycloak_mock` (D-03).
    """
    return {
        "oidc_client_id": TEST_OIDC_CLIENT_ID,
        "oidc_client_secret": "test-oidc-client-secret",
        "oidc_issuer": TEST_OIDC_ISSUER,
        **overrides,
    }


async def _post_refresh(
    async_client_for: AsyncClientFactory,
    app: FastAPI,
    refresh_token: str = "test-refresh-token-in",
) -> Any:
    """`POST /auth/refresh` with `{refresh_token}` against `app`, via a fresh client."""
    async with async_client_for(app) as client:
        return await client.post("/auth/refresh", json={"refresh_token": refresh_token})


# -----------------------------------------------------------------------------
# Log-capture idiom — direct attachment to the real `app.auth.oidc` logger.
# See module docstring / `test_auth_callback.py` for why this, not
# `configure_logging()` + `capsys`/`caplog`.
# -----------------------------------------------------------------------------


class _RecordCapturingHandler(logging.Handler):
    """Stores emitted LogRecord instances verbatim, without formatting them."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _isolated_oidc_logger() -> Iterator[logging.Logger]:
    """Force-resets and yields the real `app.auth.oidc` logger, isolated from
    ambient process state, restoring it in a `finally`.
    """
    logger = logging.getLogger("app.auth.oidc")
    original_disabled = logger.disabled
    original_propagate = logger.propagate
    original_level = logger.level
    logger.disabled = False
    logger.propagate = False
    logger.setLevel(logging.INFO)
    try:
        yield logger
    finally:
        logger.disabled = original_disabled
        logger.propagate = original_propagate
        logger.setLevel(original_level)


@pytest.fixture
def oidc_logger_records() -> Iterator[list[logging.LogRecord]]:
    """TC-27: captures raw LogRecords from the real `app.auth.oidc` logger,
    formatted after the fact through the real `JSONFormatter` to assert the
    shape actually shipped to stdout in production."""
    with _isolated_oidc_logger() as logger:
        handler = _RecordCapturingHandler()
        logger.addHandler(handler)
        try:
            yield handler.records
        finally:
            logger.removeHandler(handler)


# -----------------------------------------------------------------------------
# AUTH-01-TC-06 — success path: exact response shape + expires_in passthrough.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_refresh_token_returns_new_token_pair_tc06(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    keycloak_call_spy: KeycloakCallSpy,
) -> None:
    """AUTH-01-TC-06 test_data: mocked Keycloak refresh response
    {access_token, refresh_token, expires_in: 300}. Assert the response key
    set is EXACTLY {access_token, refresh_token, expires_in} — an accidental
    extra field (e.g. `token_type`) leaking through must fail this
    assertion — and the returned values match the mocked Keycloak response."""
    app = build_app(**_configured_overrides())
    keycloak_mock.token_success(
        access_token="new-access-token", refresh_token="new-refresh-token", expires_in=300
    )

    resp = await _post_refresh(async_client_for, app)

    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"access_token", "refresh_token", "expires_in"}
    assert body["access_token"] == "new-access-token"
    assert body["refresh_token"] == "new-refresh-token"
    assert body["expires_in"] == 300
    keycloak_call_spy.assert_call_count(keycloak_mock.token_route, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expires_in",
    [
        600,  # deliberately not the 300s realm-default/fixture value.
        1337,  # a second, unmistakably-distinctive value in the same run.
    ],
)
async def test_refresh_expires_in_passes_through_keycloak_value_never_constant(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    expires_in: int,
) -> None:
    """Complements TC-06: `expires_in` must equal whatever Keycloak's mocked
    refresh response carried, never a hardcoded constant. Parametrized over
    two distinct, non-300 values so a hardcoded constant could never
    coincidentally satisfy both."""
    app = build_app(**_configured_overrides())
    keycloak_mock.token_success(expires_in=expires_in)

    resp = await _post_refresh(async_client_for, app)

    assert resp.status_code == 200
    assert resp.json()["expires_in"] == expires_in
    assert resp.json()["expires_in"] != 300


# -----------------------------------------------------------------------------
# AUTH-01-TC-07 — expired/revoked refresh_token -> 401, standard error envelope.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expired_or_revoked_refresh_token_returns_401_tc07(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
) -> None:
    """AUTH-01-TC-07 test_data: Keycloak returns 400 invalid_grant. The route
    must map this to 401 through the standard error envelope
    (`app/core/errors.py`), never a raw passthrough, and never return a new
    token pair."""
    app = build_app(**_configured_overrides())
    keycloak_mock.token_error(status_code=400, error="invalid_grant")

    resp = await _post_refresh(async_client_for, app)

    assert resp.status_code == 401
    assert resp.json() == {
        "error": {"code": "http_401", "message": "refresh_failed", "details": None}
    }


# -----------------------------------------------------------------------------
# AUTH-01-TC-21 — any non-2xx from Keycloak maps to 401, never a passthrough.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("upstream_status", [400, 401, 403, 404, 500, 503])
async def test_any_non_2xx_from_keycloak_maps_to_401_tc21(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    upstream_status: int,
) -> None:
    """AUTH-01-TC-21: regardless of Keycloak's raw upstream status, the route
    always returns 401 with the same fixed envelope — never
    `return Response(status_code=upstream.status_code)`. TC-21's own
    test_data pins the 500 case explicitly; parametrized over a spread of
    both 4xx and 5xx statuses to prove the mapping isn't special-cased to
    any one status, and that no upstream status/body ever leaks through.

    Call-count is deliberately NOT asserted here: TC-21's expected_results
    pin only the final response status/body, not the outbound attempt
    count. A 5xx status is transient enough to feed
    `retry_with_backoff` (AUTH-01-NFR-performance's transient-fault
    retry policy), so those cases are retried up to `max_attempts` times
    before the exhausted retry loop is mapped to this same 401 — that is
    intended behavior per the NFR (only 4xx must never retry), not a defect;
    see `test_4xx_refresh_error_never_retried_tc31` below for the
    call-count assertion that pins the 4xx case specifically.
    """
    app = build_app(**_configured_overrides())
    keycloak_mock.token_error(status_code=upstream_status)

    resp = await _post_refresh(async_client_for, app)

    assert resp.status_code == 401
    assert resp.json() == {
        "error": {"code": "http_401", "message": "refresh_failed", "details": None}
    }


# -----------------------------------------------------------------------------
# AUTH-01-TC-27 — dashboard_login observability event on successful refresh.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_refresh_emits_exactly_one_dashboard_login_event_tc27(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
    oidc_logger_records: list[logging.LogRecord],
) -> None:
    """AUTH-01-TC-27 test_data: jwt_claims.sub == 'user-42'. Exactly one
    dashboard_login event is logged, carrying only `user_id` (== the
    verified token's real `sub` claim, never the `_log_dashboard_login`
    fallback sentinel `"unknown"`) — no email, name, or token value anywhere
    in the serialized line."""
    app = build_app(**_configured_overrides())
    token = build_access_token(sub=_TC27_SUB, email="user-42@example.com")
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    keycloak_mock.token_success(access_token=token, refresh_token="new-refresh-token-tc27")

    resp = await _post_refresh(async_client_for, app)

    assert resp.status_code == 200
    assert len(oidc_logger_records) == 1

    payload = json.loads(JSONFormatter().format(oidc_logger_records[0]))
    assert payload["message"] == "dashboard_login"
    assert payload["logger"] == "app.auth.oidc"

    # The heart of TC-27: a REAL user_id, proven by resolving it against the
    # mocked JWKS/verified claims — not the fallback sentinel a vacuous test
    # would still pass under.
    assert payload["user_id"] == _TC27_SUB
    assert payload["user_id"] != _FALLBACK_SENTINEL

    custom_fields = set(payload) - {"timestamp", "level", "logger", "message"}
    assert custom_fields == {"user_id"}

    serialized = json.dumps(payload)
    for forbidden in ("email", "name", "user-42@example.com", token, "new-refresh-token-tc27"):
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_failed_refresh_emits_no_dashboard_login_event(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    oidc_logger_records: list[logging.LogRecord],
) -> None:
    """FR-10 fires only on success — a failed refresh must never emit
    `dashboard_login` (and therefore leaks nothing in the log output on this
    path either)."""
    app = build_app(**_configured_overrides())
    keycloak_mock.token_error(status_code=400)

    resp = await _post_refresh(async_client_for, app)

    assert resp.status_code == 401
    assert oidc_logger_records == []


# -----------------------------------------------------------------------------
# AUTH-01-TC-31 — a 4xx from Keycloak is never retried.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_4xx_refresh_error_never_retried_tc31(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    keycloak_call_spy: KeycloakCallSpy,
) -> None:
    """AUTH-01-TC-31 test_data: Keycloak's refresh endpoint returns 400 on
    every call. The outbound call must be attempted EXACTLY ONCE — the
    highest-value assertion in this file: `retry_with_backoff` retries on
    ANY exception, so a careless implementation that raises for a 4xx inside
    the wrapped callable would silently retry a revoked refresh token 3
    times, adding latency and hammering the IdP."""
    app = build_app(**_configured_overrides())
    keycloak_mock.token_error(status_code=400)

    resp = await _post_refresh(async_client_for, app)

    assert resp.status_code == 401
    keycloak_call_spy.assert_call_count(keycloak_mock.token_route, 1)


# -----------------------------------------------------------------------------
# Transient-failure behaviour (AUTH-01-NFR-performance) — bounded retry with
# actual attempt-count assertions, complementing TC-30's dedicated perf test.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transient_failure_resolves_within_bounded_retries_then_200(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    keycloak_call_spy: KeycloakCallSpy,
) -> None:
    """A transient fault (connection error) on attempts 1-2, then success on
    the 3rd (`keycloak_mock.token_transient_then_success`'s default
    `failures=2`) resolves to 200 within the pinned `max_attempts=3` retry
    policy — exactly 3 outbound attempts: not fewer (no premature give-up)
    and not more (no retry past the mocked recovery)."""
    app = build_app(**_configured_overrides())
    keycloak_mock.token_transient_then_success(failures=2)

    resp = await _post_refresh(async_client_for, app)

    assert resp.status_code == 200
    keycloak_call_spy.assert_call_count(keycloak_mock.token_route, 3)


@pytest.mark.asyncio
async def test_persistently_transient_failure_bounded_at_max_attempts_then_401(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    keycloak_call_spy: KeycloakCallSpy,
) -> None:
    """A connection error on every attempt is bounded at the pinned
    `max_attempts=3` (1 initial attempt + at most 2 retries) — never retried
    indefinitely — then mapped to 401 once the retry loop is exhausted."""
    app = build_app(**_configured_overrides())
    keycloak_mock.token_always_transient_error()

    resp = await _post_refresh(async_client_for, app)

    assert resp.status_code == 401
    keycloak_call_spy.assert_call_count(keycloak_mock.token_route, 3)


# -----------------------------------------------------------------------------
# Additional coverage: no Set-Cookie header, FR-2 config-completeness gate.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_set_cookie_header_on_success_or_failure(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """Bearer-JWT-only session contract: neither a successful nor a failed
    refresh ever sets a Set-Cookie header. `get_list` (not a truthiness
    check) so a header present-but-empty would still be caught."""
    app = build_app(**_configured_overrides())
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)

    keycloak_mock.token_success(access_token=build_access_token(sub=_TC27_SUB))
    success_resp = await _post_refresh(async_client_for, app, refresh_token="rt-success")
    assert success_resp.status_code == 200
    assert success_resp.headers.get_list("set-cookie") == []

    keycloak_mock.token_error(status_code=400)
    failure_resp = await _post_refresh(async_client_for, app, refresh_token="rt-failure")
    assert failure_resp.status_code == 401
    assert failure_resp.headers.get_list("set-cookie") == []


@pytest.mark.asyncio
async def test_refresh_with_oidc_unconfigured_returns_501(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """FR-2's config-completeness gate applies to the refresh route too:
    with OIDC config incomplete (`build_app()`'s hermetic defaults leave
    every `oidc_*` field unset), the route returns 501 through the standard
    error envelope rather than attempting an exchange against a `None`
    issuer."""
    app = build_app()

    resp = await _post_refresh(async_client_for, app)

    assert resp.status_code == 501
    assert resp.json() == {
        "error": {"code": "http_501", "message": "oidc_not_configured", "details": None}
    }
