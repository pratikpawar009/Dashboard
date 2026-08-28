"""Cross-route security + observability sweep over every `/auth/*` route —
AUTH-01-TC-32, TC-35 (AUTH-01-NFR-security, AUTH-01-NFR-observability), plus
the PII and FR-10 emission-scope angles the two NFRs also cover.

Boots the REAL app via `build_app`/`async_client_for` (D-07) and exercises
`/auth/login`, `/auth/callback` (success AND failure), `/auth/refresh`
(success AND failure), and `/auth/dev-bypass` in one continuous sweep per
test, so "no secret leaks" and "every line is valid JSON" are asserted
across the whole `/auth/*` surface, not one route in isolation.

Log-capture idiom (deliberately reused, not invented): attach a
`_RecordCapturingHandler` directly to the real, named `app.auth.oidc`
logger, forcing `.disabled = False` / `.propagate = False` / level `INFO`
for the test's duration and restoring afterward — identical to
`tests/unit/test_auth_callback.py`'s `_isolated_oidc_logger`/
`oidc_logger_records` fixtures (duplicated locally per that file's own
precedent: each test file is independently owned and none imports another's
test internals). This survives BOTH documented traps:

1. `configure_logging()` + `capsys` (see `tests/unit/test_logging.py`'s
   module docstring): `app.main` binds a `StreamHandler` to whatever
   `sys.stdout` object exists at import time, which is not the object
   `capsys` swaps in per test phase — a `capsys` read afterward sees
   nothing regardless of what was logged. This file never calls
   `configure_logging()` or reads `capsys`; it attaches its own handler
   directly to the logger object.
2. Alembic's `fileConfig(disable_existing_loggers=True)`
   (`migrations/env.py:19`, see `tests/unit/test_range_validation.py`'s
   `_range_logger_capture` docstring): once `tests/test_migrations.py` has
   run earlier in the same session, every already-instantiated logger not
   named in that fileConfig — including `app.auth.oidc` — gets
   `.disabled = True` for the rest of the process. A disabled logger's
   `Logger.handle()` short-circuits before `callHandlers` ever runs, so
   *no* handler anywhere (root-attached or otherwise) would see the
   record. Forcing `.disabled = False` on the named logger directly, every
   time, is what makes this immune regardless of test execution order.

`app/auth/dev_bypass.py` never imports `logging` at all (FR-8: the
`dashboard_login` call is skipped entirely, not filtered), so it is
structurally incapable of emitting through this or any logger — this file's
dev-bypass step is expected to capture zero records, and that is the
*correct* result, not a symptom of a broken capture. See "Vacuous-pass
guard" below for how each test proves the mechanism itself is alive before
trusting that zero.

Vacuous-pass guard: a capture that silently produced zero lines (e.g. from
an un-worked-around disabled logger) would make every "secret absent"
assertion trivially, uselessly true. Every test below first asserts a
non-zero record count from the sweep's two log-emitting steps (callback
success, refresh success) *before* asserting anything about content — a
broken capture mechanism fails that assertion loudly instead of passing by
default.

Search style: TC-32's forbidden-substring checks run against the RAW
`JSONFormatter().format(record)` string for each captured record (never a
re-serialized/parsed view), so a secret embedded anywhere in the formatted
line — not just in a specific expected field — would still be caught.

Scope boundary: TC-10 (black-box, root-logger, "no audit event anywhere for
a served dev-bypass request") and TC-24 (white-box, spies
`oidc.logger.info` directly) both already live in
`tests/unit/test_auth_dev_bypass.py` (T-16) — this file does not
re-implement that mechanism. Dev-bypass is included in this file's sweep
only to complete the cross-route picture (secrets/PII/valid-JSON), not to
re-prove route registration or 404 gating, which is also T-16's job.

Never weakens an assertion to force a pass — see this task's returned
`flags` for anything observed but out of scope to fix here.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from contextlib import AbstractAsyncContextManager, contextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.logging import JSONFormatter
from tests.conftest import TEST_OIDC_CLIENT_ID, TEST_OIDC_ISSUER, KeycloakMock, RSATestKeypair

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

# -----------------------------------------------------------------------------
# Distinctive sentinel values — one per secret/PII category, per call site, so
# a substring match is always unambiguous (never a value a fixture default or
# another test could coincidentally also produce).
# -----------------------------------------------------------------------------

_SEC_CLIENT_SECRET = "sentinel-oidc-client-secret-91ac5f30"
_SEC_AUTH_CODE_FAILURE = "sentinel-auth-code-failure-3b7f0192"
_SEC_AUTH_CODE_SUCCESS = "sentinel-auth-code-success-6e5d4c3b"
_SEC_REFRESH_TOKEN_CALLBACK_OUT = "sentinel-refresh-tok-callback-out-5d9ae7be"
_SEC_REFRESH_TOKEN_REFRESH_OUT = "sentinel-refresh-tok-refresh-out-e02d6455"
_SEC_REFRESH_TOKEN_INCOMING_FAILURE = "sentinel-incoming-refresh-tok-failure-1a2b3c4d"
_SEC_REFRESH_TOKEN_INCOMING_SUCCESS = "sentinel-incoming-refresh-tok-success-9f8e7d6c"
_SUB_CALLBACK = "sentinel-sub-callback-2f6b91a4"
_SUB_REFRESH = "sentinel-sub-refresh-7a41dd3f"
_SEC_EMAIL_CALLBACK = "sentinel-callback-pii-4c26ab@example.com"
_SEC_EMAIL_DEV_BYPASS = "sentinel-devbypass-pii-9e71fd@example.com"


# -----------------------------------------------------------------------------
# Log-capture idiom — reused verbatim from test_auth_callback.py.
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
    """Captures raw LogRecords from the real `app.auth.oidc` logger, formatted
    after the fact through the real `JSONFormatter` in each test below."""
    with _isolated_oidc_logger() as logger:
        handler = _RecordCapturingHandler()
        logger.addHandler(handler)
        try:
            yield handler.records
        finally:
            logger.removeHandler(handler)


def _formatted(records: list[logging.LogRecord]) -> list[str]:
    """Each record through the real `JSONFormatter`, matching production."""
    return [JSONFormatter().format(r) for r in records]


# -----------------------------------------------------------------------------
# Route sweep — one continuous capture spanning every /auth/* route.
# -----------------------------------------------------------------------------


@dataclass
class _SweepResult:
    responses: dict[str, Any]
    steps: dict[str, list[logging.LogRecord]]
    all_records: list[logging.LogRecord] = field(default_factory=list)


async def _drive_auth_route_sweep(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
    oidc_logger_records: list[logging.LogRecord],
) -> _SweepResult:
    """Exercise `/auth/login`, `/auth/callback` (failure then success),
    `/auth/refresh` (failure then success), and `/auth/dev-bypass` — in that
    order — against one app/capture, using distinctive sentinel values for
    every secret/PII value in play. Returns each response plus the exact
    slice of `oidc_logger_records` emitted during each step.
    """
    app = build_app(
        environment="development",
        oidc_client_id=TEST_OIDC_CLIENT_ID,
        oidc_client_secret=_SEC_CLIENT_SECRET,
        oidc_issuer=TEST_OIDC_ISSUER,
    )
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)

    responses: dict[str, Any] = {}
    steps: dict[str, list[logging.LogRecord]] = {}

    async with async_client_for(app) as client:
        mark = len(oidc_logger_records)
        responses["login"] = await client.get("/auth/login")
        steps["login"] = oidc_logger_records[mark:]

        mark = len(oidc_logger_records)
        keycloak_mock.token_error(status_code=400)
        responses["callback_failure"] = await client.get(
            "/auth/callback", params={"code": _SEC_AUTH_CODE_FAILURE}
        )
        steps["callback_failure"] = oidc_logger_records[mark:]

        mark = len(oidc_logger_records)
        callback_access_token = build_access_token(sub=_SUB_CALLBACK, email=_SEC_EMAIL_CALLBACK)
        keycloak_mock.token_success(
            access_token=callback_access_token,
            refresh_token=_SEC_REFRESH_TOKEN_CALLBACK_OUT,
        )
        responses["callback_success"] = await client.get(
            "/auth/callback", params={"code": _SEC_AUTH_CODE_SUCCESS}
        )
        steps["callback_success"] = oidc_logger_records[mark:]

        mark = len(oidc_logger_records)
        keycloak_mock.token_error(status_code=400)
        responses["refresh_failure"] = await client.post(
            "/auth/refresh", json={"refresh_token": _SEC_REFRESH_TOKEN_INCOMING_FAILURE}
        )
        steps["refresh_failure"] = oidc_logger_records[mark:]

        mark = len(oidc_logger_records)
        refresh_access_token = build_access_token(sub=_SUB_REFRESH)
        keycloak_mock.token_success(
            access_token=refresh_access_token,
            refresh_token=_SEC_REFRESH_TOKEN_REFRESH_OUT,
        )
        responses["refresh_success"] = await client.post(
            "/auth/refresh", json={"refresh_token": _SEC_REFRESH_TOKEN_INCOMING_SUCCESS}
        )
        steps["refresh_success"] = oidc_logger_records[mark:]

        mark = len(oidc_logger_records)
        responses["dev_bypass"] = await client.post(
            "/auth/dev-bypass",
            json={"role": "developer", "email": _SEC_EMAIL_DEV_BYPASS, "programs": ["alpha"]},
        )
        steps["dev_bypass"] = oidc_logger_records[mark:]

    return _SweepResult(responses=responses, steps=steps, all_records=list(oidc_logger_records))


# -----------------------------------------------------------------------------
# AUTH-01-TC-32 — no secret value ever appears in captured log output.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_secrets_leak_across_auth_route_sweep_tc32(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
    oidc_logger_records: list[logging.LogRecord],
) -> None:
    """AUTH-01-TC-32: across the full route sweep, no captured log line
    (searched as raw formatted text, not a parsed field) ever contains the
    access token, the refresh token (either direction), the authorization
    `code`, or `oidc_client_secret`."""
    result = await _drive_auth_route_sweep(
        build_app,
        async_client_for,
        keycloak_mock,
        rsa_test_keypair,
        build_access_token,
        oidc_logger_records,
    )

    # Vacuous-pass guard: the mechanism must have actually captured
    # something before the "secret absent" assertions below mean anything.
    assert len(result.all_records) > 0, (
        "capture produced zero log lines -- capture mechanism is broken "
        "(see module docstring's disabled-logger trap); every assertion "
        "below would otherwise pass vacuously"
    )
    assert len(result.steps["callback_success"]) == 1
    assert len(result.steps["refresh_success"]) == 1

    raw_text = "\n".join(_formatted(result.all_records))
    forbidden = (
        callback_access_token := result.responses["callback_success"].json()["access_token"],
        result.responses["refresh_success"].json()["access_token"],
        _SEC_REFRESH_TOKEN_CALLBACK_OUT,
        _SEC_REFRESH_TOKEN_REFRESH_OUT,
        _SEC_REFRESH_TOKEN_INCOMING_FAILURE,
        _SEC_REFRESH_TOKEN_INCOMING_SUCCESS,
        _SEC_AUTH_CODE_FAILURE,
        _SEC_AUTH_CODE_SUCCESS,
        _SEC_CLIENT_SECRET,
    )
    assert callback_access_token  # sanity: the success response really carried a token
    for secret in forbidden:
        assert secret not in raw_text, f"secret leaked into log output: {secret!r}"


# -----------------------------------------------------------------------------
# AUTH-01-TC-35 — every captured /auth/* log line is valid JSON with the
# formatter's first-class keys.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_auth_routes_emit_valid_json_log_lines_tc35(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
    oidc_logger_records: list[logging.LogRecord],
) -> None:
    """AUTH-01-TC-35: every log line captured across the route sweep parses
    with `json.loads` and carries `timestamp`, `level`, `logger`, `message`.

    `login`, `callback_failure`, `refresh_failure`, and `dev_bypass` emit
    zero lines through this logger today (none of those code paths call
    it), which trivially satisfies "every line is valid JSON" for those
    steps; the non-trivial, guarded assertion is on the two steps that do
    emit (`callback_success`, `refresh_success`)."""
    result = await _drive_auth_route_sweep(
        build_app,
        async_client_for,
        keycloak_mock,
        rsa_test_keypair,
        build_access_token,
        oidc_logger_records,
    )

    assert len(result.all_records) > 0, "capture produced zero log lines -- see module docstring"
    assert len(result.steps["callback_success"]) == 1
    assert len(result.steps["refresh_success"]) == 1
    assert result.steps["login"] == []
    assert result.steps["callback_failure"] == []
    assert result.steps["refresh_failure"] == []
    assert result.steps["dev_bypass"] == []

    for record in result.all_records:
        formatted = JSONFormatter().format(record)
        payload = json.loads(formatted)  # raises -> fails the test if not valid JSON
        assert {"timestamp", "level", "logger", "message"} <= payload.keys()


# -----------------------------------------------------------------------------
# PII (AUTH-01-NFR-security / FR-10) — email never logged, either arrival path.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_never_logged_via_jwt_claim_or_dev_bypass_request(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
    oidc_logger_records: list[logging.LogRecord],
) -> None:
    """`email` must never be logged on either path it can arrive by:
    (1) a JWT `email` claim on the OIDC callback path, (2) caller-supplied
    `DevBypassRequest.email` on the dev-bypass path."""
    result = await _drive_auth_route_sweep(
        build_app,
        async_client_for,
        keycloak_mock,
        rsa_test_keypair,
        build_access_token,
        oidc_logger_records,
    )

    # Path 1: JWT claim (callback_success's token carries _SEC_EMAIL_CALLBACK).
    # Vacuous-pass guard, scoped to this test: this step really did capture a
    # record, proving the mechanism is alive before trusting any absence.
    assert len(result.steps["callback_success"]) == 1
    callback_text = "\n".join(_formatted(result.steps["callback_success"]))
    assert _SEC_EMAIL_CALLBACK not in callback_text
    assert "email" not in json.loads(_formatted(result.steps["callback_success"])[0])

    # Path 2: caller-supplied DevBypassRequest.email. dev_bypass.py never
    # imports `logging` (FR-8: the call is skipped, not filtered) -- zero
    # captured records here is the correct result, not a broken capture;
    # the guard above already proved this same mechanism, in this same
    # test, does capture real records when the code path actually logs.
    assert result.responses["dev_bypass"].status_code == 200
    assert result.steps["dev_bypass"] == []
    all_text = "\n".join(_formatted(result.all_records))
    assert _SEC_EMAIL_DEV_BYPASS not in all_text


# -----------------------------------------------------------------------------
# FR-10 scope — dashboard_login fires on success (callback, refresh) only,
# never on failure, never on dev-bypass.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_login_presence_absence_matrix(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
    oidc_logger_records: list[logging.LogRecord],
) -> None:
    """AUTH-01-FR-10: `dashboard_login` fires exactly once on a successful
    callback and exactly once on a successful refresh, and never on a
    failed callback, a failed refresh, or dev-bypass (FR-8) -- asserted as
    one table across all five cases."""
    result = await _drive_auth_route_sweep(
        build_app,
        async_client_for,
        keycloak_mock,
        rsa_test_keypair,
        build_access_token,
        oidc_logger_records,
    )

    expected_presence = {
        "callback_success": True,
        "callback_failure": False,
        "refresh_success": True,
        "refresh_failure": False,
        "dev_bypass": False,  # FR-8
    }
    for step, expect_present in expected_presence.items():
        messages = [json.loads(f)["message"] for f in _formatted(result.steps[step])]
        if expect_present:
            assert messages.count("dashboard_login") == 1, (
                f"{step}: expected exactly one dashboard_login event, got {messages}"
            )
        else:
            assert "dashboard_login" not in messages, (
                f"{step}: dashboard_login must never fire here, got {messages}"
            )

    # Corroborate the matrix against the actual response outcomes.
    assert result.responses["callback_success"].status_code == 200
    assert result.responses["callback_failure"].status_code != 200
    assert result.responses["refresh_success"].status_code == 200
    assert result.responses["refresh_failure"].status_code != 200
    assert result.responses["dev_bypass"].status_code == 200
