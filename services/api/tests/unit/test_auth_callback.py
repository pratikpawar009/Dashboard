"""Unit tests for `app/auth/oidc.py`'s `GET /auth/callback` route — AUTH-01-TC-03,
TC-16, TC-26, TC-36 (AUTH-01-FR-3, AUTH-01-FR-10).

DB-free: the callback route has no database dependency (DATA-DESIGN §1/§2) —
this file never imports `migrated_db`/`test_session`. Outbound calls (Keycloak
token endpoint, JWKS endpoint) are mocked via `keycloak_mock` (`tests/conftest
.py`); no real network call is ever made (`assert_all_mocked=True` on that
fixture guarantees it).

Boots the REAL app via `build_app`/`create_app` (D-07) rather than a throwaway
local app (unlike `test_auth_jwt_validation.py`/`test_auth_groups.py`, both of
which predate `app/main.py::create_app` landing) — this exercises the actual
router wiring, CORS, and error-envelope registration exactly as production
does.

Log-capture idiom: mirrors `tests/unit/test_range_validation.py`'s
`_isolated_range_logger` — attach a handler directly to the real, named
`app.auth.oidc` logger and force `.disabled = False`/`.propagate = False`,
bypassing root/`capsys`/`caplog` entirely. Two independent reasons this file
does NOT use `configure_logging()` + `capsys` (see `tests/unit/test_logging
.py`'s module docstring for the first):

1. `app.main` (imported lazily inside `build_app`'s closure) calls
   `configure_logging()` at import time, binding its `StreamHandler` to
   whichever `sys.stdout` object exists at THAT moment — not the one
   `capsys` swaps in per-test-phase. A `capsys` read after the app is built
   sees zero captured lines regardless of what was logged.
2. Whichever pytest session eventually runs this file alongside
   `tests/test_migrations.py` (AF-08-carry): `migrations/env.py:19`'s
   `logging.config.fileConfig(disable_existing_loggers=True)` permanently
   disables every already-instantiated logger not named in that config,
   including `app.auth.oidc` once its module has been imported. A disabled
   logger's `emit()` short-circuits before any handler — including
   `caplog`'s — ever sees the record, so `caplog` is not a safe alternative
   here either. Forcing `.disabled = False` on the named logger directly
   (this file's `_isolated_oidc_logger`) is the one idiom immune to both
   gotchas.

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
    issue_oauth_state,
)

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

# Success-path default JWT claims (AUTH-01-TC-26's pinned test_data: sub ==
# 'user-42'), and the sentinel `_log_dashboard_login` falls back to on any
# decode/verify failure — asserted against directly so TC-26 never passes
# vacuously on the fallback path.
_TC26_SUB = "user-42"
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


async def _get_callback(
    async_client_for: AsyncClientFactory, app: FastAPI, code: str = "test-auth-code-1"
) -> Any:
    """`GET /auth/callback?code=<code>&state=<valid>` against `app`, via a fresh client.

    The `state` is minted from `app`'s own store because the callback now
    rejects an unverifiable one before it ever reaches the code exchange --
    every test here is about what happens AFTER that gate, so each request
    carries a freshly issued, single-use value.
    """
    async with async_client_for(app) as client:
        return await client.get(
            "/auth/callback", params={"code": code, "state": issue_oauth_state(app)}
        )


# -----------------------------------------------------------------------------
# Log-capture idiom — direct attachment to the real `app.auth.oidc` logger.
# See module docstring for why this, not `configure_logging()` + `capsys`/
# `caplog`.
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
    ambient process state, restoring it in a `finally` — see module docstring.
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
    """TC-26: captures raw LogRecords from the real `app.auth.oidc` logger,
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
# AUTH-01-TC-03 — exact success-path response shape.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_callback_returns_exact_token_response_shape_tc03(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-01-TC-03: 200 with a body whose key set is EXACTLY {access_token,
    refresh_token, expires_in} — an accidental extra field (e.g. `token_type`,
    `scope`) leaking through must fail this assertion, not merely go
    unnoticed."""
    app = build_app(**_configured_overrides())
    token = build_access_token(sub=_TC26_SUB)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    keycloak_mock.token_success(
        access_token=token, refresh_token="test-refresh-token", expires_in=300
    )

    resp = await _get_callback(async_client_for, app, code="test-auth-code-1")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"access_token", "refresh_token", "expires_in"}
    assert body["access_token"] == token
    assert body["refresh_token"] == "test-refresh-token"
    assert body["expires_in"] == 300


# -----------------------------------------------------------------------------
# AUTH-01-TC-16 (security) — no Set-Cookie header, success or failure.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_set_cookie_header_on_success_or_failure_tc16(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-01-TC-16: neither a successful nor a failed code exchange ever
    sets a Set-Cookie header, per the bearer-JWT-only session contract.
    `get_list` (not a truthiness check) so a header present-but-empty would
    still be caught."""
    app = build_app(**_configured_overrides())
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)

    keycloak_mock.token_success(access_token=build_access_token(sub=_TC26_SUB))
    success_resp = await _get_callback(async_client_for, app, code="test-auth-code-success")
    assert success_resp.status_code == 200
    assert success_resp.headers.get_list("set-cookie") == []

    keycloak_mock.token_error(status_code=400)
    failure_resp = await _get_callback(async_client_for, app, code="test-auth-code-invalid")
    assert failure_resp.status_code != 200
    assert failure_resp.headers.get_list("set-cookie") == []


# -----------------------------------------------------------------------------
# AUTH-01-TC-36 (contract) — expires_in passthrough, never hardcoded.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expires_in",
    [
        600,  # TC-36's own pinned test_data value — deliberately not the 300s realm default.
        1337,  # a second, unmistakably-distinctive value in the same run — see module docstring.
    ],
)
async def test_expires_in_passes_through_keycloak_value_tc36(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
    expires_in: int,
) -> None:
    """AUTH-01-TC-36: `expires_in` in the response equals whatever Keycloak's
    mocked token response carried, never the 300s fixture-default constant.
    Parametrized over two distinct, non-300 values so a hardcoded constant
    could never coincidentally satisfy both."""
    app = build_app(**_configured_overrides())
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    keycloak_mock.token_success(
        access_token=build_access_token(sub=_TC26_SUB), expires_in=expires_in
    )

    resp = await _get_callback(async_client_for, app, code="test-auth-code-1")

    assert resp.status_code == 200
    assert resp.json()["expires_in"] == expires_in
    assert resp.json()["expires_in"] != 300


# -----------------------------------------------------------------------------
# AUTH-01-TC-26 — dashboard_login observability event.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_callback_emits_exactly_one_dashboard_login_event_tc26(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
    oidc_logger_records: list[logging.LogRecord],
) -> None:
    """AUTH-01-TC-26: exactly one `dashboard_login` JSON event, carrying only
    `user_id` (== the verified token's real `sub` claim, never the
    `_log_dashboard_login` fallback sentinel `"unknown"`) — no email, name, or
    token value anywhere in the serialized line."""
    app = build_app(**_configured_overrides())
    token = build_access_token(sub=_TC26_SUB, email="user-42@example.com")
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    keycloak_mock.token_success(access_token=token, refresh_token="test-refresh-token-tc26")

    resp = await _get_callback(async_client_for, app, code="test-auth-code-1")

    assert resp.status_code == 200
    assert len(oidc_logger_records) == 1

    payload = json.loads(JSONFormatter().format(oidc_logger_records[0]))
    assert payload["message"] == "dashboard_login"
    assert payload["logger"] == "app.auth.oidc"

    # The heart of TC-26: a REAL user_id, proven by resolving it against the
    # mocked JWKS/verified claims — not the fallback sentinel a vacuous test
    # would still pass under.
    assert payload["user_id"] == _TC26_SUB
    assert payload["user_id"] != _FALLBACK_SENTINEL

    custom_fields = set(payload) - {"timestamp", "level", "logger", "message"}
    assert custom_fields == {"user_id"}

    serialized = json.dumps(payload)
    for forbidden in ("email", "name", "user-42@example.com", token, "test-refresh-token-tc26"):
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_failed_callback_emits_no_dashboard_login_event(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    oidc_logger_records: list[logging.LogRecord],
) -> None:
    """FR-10 fires only on success — a failed code exchange must never emit
    `dashboard_login` (and therefore leaks nothing, trivially satisfying "no
    token value in captured log output" on this path)."""
    app = build_app(**_configured_overrides())
    keycloak_mock.token_error(status_code=400)

    resp = await _get_callback(async_client_for, app, code="test-auth-code-invalid")

    assert resp.status_code != 200
    assert oidc_logger_records == []


# -----------------------------------------------------------------------------
# Additional coverage: failed exchange status/no-retry, and FR-2 config gate.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_code_exchange_returns_401_with_single_outbound_call(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    keycloak_call_spy: KeycloakCallSpy,
) -> None:
    """A 4xx from Keycloak's token endpoint maps to the route's 401 error
    status, and the outbound call is attempted exactly ONCE — a 4xx must
    never feed the bounded-retry loop (AUTH-01-NFR-performance)."""
    app = build_app(**_configured_overrides())
    keycloak_mock.token_error(status_code=400)

    resp = await _get_callback(async_client_for, app, code="test-auth-code-invalid")

    assert resp.status_code == 401
    keycloak_call_spy.assert_call_count(keycloak_mock.token_route, 1)


@pytest.mark.asyncio
async def test_callback_with_oidc_unconfigured_returns_501(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """FR-2 gates the callback route too: with OIDC config incomplete
    (`build_app()`'s hermetic defaults leave every `oidc_*` field unset), the
    route returns 501 through the standard error envelope rather than
    attempting an exchange against a `None` issuer."""
    app = build_app()

    resp = await _get_callback(async_client_for, app, code="irrelevant")

    assert resp.status_code == 501
    assert resp.json() == {
        "error": {"code": "http_501", "message": "oidc_not_configured", "details": None}
    }
