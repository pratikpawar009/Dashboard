"""Route-level tests for `app/auth/dev_bypass.py` — AUTH-01-TC-08, TC-09,
TC-10, TC-22, TC-23, TC-24, TC-37, TC-38, TC-39, TC-40, plus AUTH-06-TC-02.

Boots the real `create_app` app factory via the D-07 `build_app`/
`async_client_for` fixtures (`tests/conftest.py`) for every case — TC-09's
own precondition ("Test app booted with ENVIRONMENT=production") and TC-40's
AF-05 regression both require the real factory, not a throwaway local app.

Scope boundary: `Settings.dev_bypass_enabled`'s own semantics (which
`ENVIRONMENT` values normalize to which boolean, and the allow-list's exact
membership) are `test_auth_config.py`'s (T-10) job — already covered there
for all nine values this file also exercises. This file is strictly about
what those values mean at the ROUTE layer: is `/auth/dev-bypass` registered
at all, does it issue a usable token, does that token verify against a real
`Depends(get_current_user)`-guarded route, and does it ever touch Keycloak
or the audit log.

DB-free for every AUTH-01 case (DATA-DESIGN §1/§2: AUTH-01 adds no entity,
no migration). AUTH-06-TC-02 at the bottom of this file is the one deliberate
exception, and it is not a drift from that intent: proving the NON-dev-bypass
branch resolves membership from `program_roster` requires a real row in that
table, so that test alone takes `migrated_db`/`test_session` and points its
app's `get_db` at the disposable test database. Every AUTH-01 case above it
still touches no database at all.

AUTH-06-TC-02 (`app/core/auth.py`'s roster-skip branch) also changes what the
dev-bypass CLAIM SHAPE means, and every AUTH-01 assertion in this file was
re-checked against it: `dev_bypass.py` now emits `programs` as its own
top-level JWT claim and omits `groups` ENTIRELY (AUTH-06-AC-4/AC-6, D-02),
where it previously emitted a synthetic `groups: ["<prefix><program>"]` that
`get_current_user` parsed back. No assertion here changed — TC-40's
`accepted_body["programs"] == ["alpha"]` is stated at the ROUTE layer, where
the two mechanisms are observationally identical; nothing in this file ever
asserted on the synthetic `groups` shape itself.

Log-capture idiom for TC-10 (black-box): a `StreamHandler`+`JSONFormatter`
pair bound to an OWNED `io.StringIO`, attached directly to the root logger —
never `configure_logging()` + `capsys`. `tests/unit/test_logging.py`'s own
docstring documents why that combination doesn't work here:
`configure_logging()` binds `logging.StreamHandler(sys.stdout)` to whatever
object `sys.stdout` names at the instant it runs, and pytest's `capsys`
swaps `sys.stdout` for a new capture object between fixture setup and the
test body — the handler goes on writing into an object nothing is reading
from any more, so `capsys.readouterr()` sees nothing regardless of what was
actually logged. Owning the stream (mirrors
`tests/unit/test_range_validation.py`'s `range_logger_json_stream`)
sidesteps the swap entirely. Attached to the ROOT logger, not one named
logger: TC-10's assertion is black-box and unscoped ("no dashboard_login,
and no OTHER audit-log event") — every app logger (`app.auth.oidc`'s
included) propagates to root by default, so this sees everything a served
request could emit.

TC-24 is the white-box counterpart: it spies `app.auth.oidc`'s own `logger`
object (the real call site `_log_dashboard_login` uses) and asserts it is
never invoked, proving the call is *skipped*, not merely filtered out of a
log line after the fact.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, contextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import Mock

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.auth import oidc
from app.auth.jwks import DEV_BYPASS_KID
from app.core.auth import CurrentUser, get_current_user
from app.core.config import NON_PRODUCTION_ENVIRONMENTS
from app.core.db import get_db
from app.core.logging import JSONFormatter
from app.models.roster import ProgramRoster
from tests.conftest import (
    TEST_OIDC_CLIENT_ID,
    TEST_OIDC_ISSUER,
    AlembicRunner,
    KeycloakCallSpy,
    KeycloakMock,
    RSATestKeypair,
)

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

# app/core/errors.py::error_body() shape, exactly as Starlette's own
# unmatched-route 404 renders it through register_exception_handlers.
_EXPECTED_404_BODY = {"error": {"code": "http_404", "message": "Not Found", "details": None}}

# D-01 fail-closed set: every value that must leave the router UNREGISTERED
# (a genuine 404, not a reachable-but-rejecting handler). TC-09 (production),
# TC-22 (PRODUCTION — case-normalization), TC-23 (Prod — mixed-case
# abbreviation), TC-37 (staging — a real, unlisted deployment name), TC-38
# (produciton — the realistic typo). "prod" (already-lowercase abbreviation)
# has no dedicated TC id but is the exact value a bare
# `environment.lower() != "production"` deny-check would misread as
# non-production — included as extra coverage of the same AUTH-01-FR-7
# property TC-23 exists to prove.
_GATED_ENVIRONMENTS = [
    pytest.param("production", id="production-tc09"),
    pytest.param("PRODUCTION", id="PRODUCTION-tc22"),
    pytest.param("Prod", id="Prod-tc23"),
    pytest.param("prod", id="prod-extra-tc23-property"),
    pytest.param("staging", id="staging-tc37"),
    pytest.param("produciton", id="produciton-tc38"),
]

# TC-40's throwaway guarded route. `create_app` mounts only
# health/ingest/activities/auth (none guarded by `get_current_user` yet) —
# this router is mounted ONLY onto apps built inside this test module,
# never onto application code (surgical-changes; this task's own explicit
# instruction).
_GUARDED_ROUTE_PATH = "/test-only/current-user"
_guarded_router = APIRouter()


@_guarded_router.get(_GUARDED_ROUTE_PATH)
async def _current_user_probe(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    return {
        "user_id": user.user_id,
        "email": user.email,
        "role": user.role,
        "groups": user.groups,
        "programs": user.programs,
    }


@pytest.fixture
def root_log_capture() -> Iterator[io.StringIO]:
    """See module docstring "Log-capture idiom for TC-10". Restores the root
    logger's original handlers/level/disabled state in a `finally` so this
    file cannot leak logging state into any test that runs after it."""
    root = logging.getLogger()
    original_handlers = root.handlers
    original_level = root.level
    original_disabled = root.disabled
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JSONFormatter())
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    root.disabled = False
    try:
        yield stream
    finally:
        root.handlers = original_handlers
        root.setLevel(original_level)
        root.disabled = original_disabled


# -----------------------------------------------------------------------------
# AUTH-01-TC-08 — happy path: token issued, zero outbound Keycloak calls.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dev_bypass_issues_token_without_contacting_keycloak_tc08(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_call_spy: KeycloakCallSpy,
) -> None:
    """Role/email/programs overrides in an allow-listed env -> 200, body
    exactly {access_token, refresh_token, expires_in}, zero outbound
    Keycloak calls — via the shared respx-backed spy (D-06), not a
    hand-rolled counter, so a regression that added a real network call
    would raise inside respx's own `assert_all_mocked=True` router rather
    than silently going uncounted."""
    app = build_app(environment="development")

    async with async_client_for(app) as client:
        resp = await client.post(
            "/auth/dev-bypass",
            json={
                "role": "engineering_manager",
                "email": "dev-user@example.com",
                "programs": ["alpha"],
            },
        )

    assert resp.status_code == 200
    assert set(resp.json().keys()) == {"access_token", "refresh_token", "expires_in"}
    assert "set-cookie" not in resp.headers
    keycloak_call_spy.assert_zero_calls()


# -----------------------------------------------------------------------------
# AUTH-01-TC-09/22/23/37/38 (FR-7, D-01) — the fail-closed property. Heart of
# this file: the route must be UNREGISTERED, not reachable-and-rejecting.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", _GATED_ENVIRONMENTS)
async def test_dev_bypass_route_is_unregistered_for_gated_environment(
    environment: str,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """The route is UNREGISTERED — a real 404 via FastAPI's own routing,
    rendered through the standard error envelope — never a reachable
    handler that merely rejects. A route that returned 401/403 here would
    still be a live attack surface a misconfigured deployment could probe;
    D-01's fail-closed guarantee is specifically that it never routes at
    all."""
    app = build_app(environment=environment)

    async with async_client_for(app) as client:
        resp = await client.post(
            "/auth/dev-bypass", json={"role": "engineering_manager", "email": "x@example.com"}
        )

    assert resp.status_code == 404
    assert resp.json() == _EXPECTED_404_BODY
    assert "access_token" not in resp.text
    assert "refresh_token" not in resp.text


# -----------------------------------------------------------------------------
# AUTH-01-TC-39 — allow-list completeness: fail-closed must not lock out
# every legitimate non-production environment.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", sorted(NON_PRODUCTION_ENVIRONMENTS))
async def test_dev_bypass_reachable_for_every_allow_listed_environment_tc39(
    environment: str,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_call_spy: KeycloakCallSpy,
) -> None:
    """Every member of the allow-list keeps dev-bypass reachable — guards
    against over-tightening D-01's allow-list (too narrow locks developers/
    CI out just as badly as too wide exposes production). Parametrized over
    the real `NON_PRODUCTION_ENVIRONMENTS` constant, not a second hardcoded
    literal list, so this stays in lockstep with the allow-list's actual
    membership; the allow-list's own CONTENT is pinned once, in
    `test_auth_config.py` (this file's module docstring, Scope boundary)."""
    app = build_app(environment=environment)

    async with async_client_for(app) as client:
        resp = await client.post("/auth/dev-bypass", json={})

    assert resp.status_code == 200
    assert set(resp.json().keys()) == {"access_token", "refresh_token", "expires_in"}
    assert "set-cookie" not in resp.headers
    keycloak_call_spy.assert_zero_calls()


# -----------------------------------------------------------------------------
# AUTH-01-TC-10 (AC-10, black-box) — no audit-log event, no PII, in captured
# output across a served dev-bypass request.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_dashboard_login_or_pii_logged_for_served_request_tc10(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    root_log_capture: io.StringIO,
) -> None:
    """No `dashboard_login` event, and nothing containing the issued tokens
    or the caller-supplied email (PII, `.claude/rules/security-baseline.md`),
    appears anywhere in captured log output for a served dev-bypass
    request."""
    app = build_app(environment="development")
    email = "dev-user@example.com"
    request_body: dict[str, Any] = {
        "role": "engineering_manager",
        "email": email,
        "programs": ["alpha"],
    }

    async with async_client_for(app) as client:
        resp = await client.post("/auth/dev-bypass", json=request_body)

    assert resp.status_code == 200
    body = resp.json()

    captured = root_log_capture.getvalue()
    for line in (candidate for candidate in captured.splitlines() if candidate):
        record = json.loads(line)  # every captured line must still be valid JSON
        assert "dashboard_login" not in record.get("message", "")
    assert "dashboard_login" not in captured
    assert email not in captured
    assert body["access_token"] not in captured
    assert body["refresh_token"] not in captured


# -----------------------------------------------------------------------------
# AUTH-01-TC-24 (FR-8, white-box) — the dashboard_login logging CALL itself
# is absent from this path (skipped, not called-and-filtered).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_login_logging_call_never_invoked_tc24(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spies the REAL logger object `app/auth/oidc.py::_log_dashboard_login`
    calls (`oidc.logger.info`) and asserts it is never invoked while serving
    a dev-bypass request. `dev_bypass.py` never imports the OIDC module at
    all, so this is not a trivial grep-substitute: it proves the actual,
    shared logging call site is untouched, and would catch a future
    regression that had dev-bypass reach into it, rather than only
    inspecting a filtered/suppressed log line (that is TC-10's job, above)."""
    spy = Mock()
    monkeypatch.setattr(oidc.logger, "info", spy)

    app = build_app(environment="development")
    async with async_client_for(app) as client:
        resp = await client.post(
            "/auth/dev-bypass", json={"role": "qa", "email": "dev@example.com"}
        )

    assert resp.status_code == 200
    spy.assert_not_called()


# -----------------------------------------------------------------------------
# AUTH-01-TC-40 (regression-AF-05) — a dev-bypass token is accepted by a real
# get_current_user-protected route, and rejected in production.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dev_bypass_token_accepted_by_guarded_route_and_rejected_in_production_tc40(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_call_spy: KeycloakCallSpy,
) -> None:
    """Closes AF-05: a token obtained from `POST /auth/dev-bypass` in an
    allow-listed environment is ACCEPTED on a `Depends(get_current_user)`
    route with derived role/programs matching the overrides (D-08's
    ephemeral signing key resolved via the same JWKS path every bearer
    token goes through — no second trust path). The SAME token is then
    REJECTED 401 when the app is built with `ENVIRONMENT=production` — the
    dev `kid` is never served there (D-01's fail-closed allow-list gates
    `JwksCache.get_signing_key`'s dev-kid branch too, not just router
    registration). Zero outbound Keycloak calls throughout — dev-bypass has
    no access to a live IdP and must not need one."""
    dev_app = build_app(environment="development")
    dev_app.include_router(_guarded_router)

    async with async_client_for(dev_app) as client:
        issue_resp = await client.post(
            "/auth/dev-bypass",
            json={"role": "qa", "email": "dev@example.com", "programs": ["alpha"]},
        )
        assert issue_resp.status_code == 200
        token = issue_resp.json()["access_token"]

        accepted_resp = await client.get(
            _GUARDED_ROUTE_PATH, headers={"Authorization": f"Bearer {token}"}
        )

    assert accepted_resp.status_code == 200
    accepted_body = accepted_resp.json()
    assert accepted_body["role"] == "qa"
    assert accepted_body["programs"] == ["alpha"]

    prod_app = build_app(environment="production")
    prod_app.include_router(_guarded_router)

    async with async_client_for(prod_app) as prod_client:
        rejected_resp = await prod_client.get(
            _GUARDED_ROUTE_PATH, headers={"Authorization": f"Bearer {token}"}
        )

    assert rejected_resp.status_code == 401
    keycloak_call_spy.assert_zero_calls()


# =============================================================================
# AUTH-06-TC-02 (AC-4, FR-3, NFR-security) — the kid-discriminator regression
# guard. `docs/test-cases/AUTH-06.json` calls this the highest-severity risk in
# `docs/research/AUTH-06.md`'s register, and it is the reason this file grew a
# database dependency (see module docstring).
#
# Scaffold below is local to this section, matching this repo's per-topic-file
# precedent (`test_programs.py` / `test_personal_usage.py` each own their
# `_db_override` and seeding helpers rather than sharing them via conftest).
# =============================================================================

# The two membership sets are disjoint ON PURPOSE, so a pass and a fail can
# never be confused for one another: PROG-Q exists only in `program_roster`,
# PROG-Z exists only inside the forged token's own claim. If `session.programs`
# ever comes back as PROG-Z, the branch read the caller's claim.
_TC02_DEV_BYPASS_PROGRAMS = ["PROG-X", "PROG-Y"]
_TC02_FORGED_EMAIL = "eve@example.com"
_TC02_ROSTER_PROGRAM = "PROG-Q"
_TC02_FORGED_CLAIM_PROGRAM = "PROG-Z"

_PROGRAM_ROSTER_RE = re.compile(r"\bprogram_roster\b", re.IGNORECASE)


def _db_override(session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    """`app.dependency_overrides[get_db]` value pointing at `session`.

    `app.core.db.get_db` is backed by a module-level engine bound to
    `settings.database_url` (the dev DB), not per-app state like
    `get_settings`/`get_jwks_cache` — so FastAPI's own `dependency_overrides`
    is the seam, exactly as `test_programs.py` established it.
    """

    async def _get_db() -> AsyncIterator[AsyncSession]:
        yield session

    return _get_db


def _decode_unverified_segment(token: str, index: int) -> dict[str, Any]:
    """Base64/JSON-decode one JWT segment WITHOUT verifying the signature.

    Mirrors `app.core.auth._peek_kid`'s own decode-without-verify technique
    (and `tests/unit/test_personal_usage.py::_decode_unverified_claims`). Used
    here only to prove what was MINTED, never to make a trust decision — the
    real verification happens inside the route under test.
    """
    segment = token.split(".")[index]
    padding = "=" * (-len(segment) % 4)
    decoded: dict[str, Any] = json.loads(base64.urlsafe_b64decode(segment + padding))
    return decoded


def _decode_unverified_header(token: str) -> dict[str, Any]:
    return _decode_unverified_segment(token, 0)


def _decode_unverified_claims(token: str) -> dict[str, Any]:
    return _decode_unverified_segment(token, 1)


class _RosterSelectSpy:
    """Every SELECT against `program_roster` captured while attached."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.parameters: list[Any] = []

    @property
    def count(self) -> int:
        return len(self.statements)

    def bound_values(self) -> list[Any]:
        """Flatten the captured statements' bound parameters into one list.

        SQLAlchemy's psycopg3 dialect binds named (pyformat) parameters, so
        each entry is normally a dict; the sequence branch covers an
        executemany-shaped capture rather than assuming the dict case.
        """
        flat: list[Any] = []
        for params in self.parameters:
            if isinstance(params, dict):
                flat.extend(params.values())
            else:
                flat.extend(params or [])
        return flat


@contextmanager
def _spy_program_roster_selects(engine: AsyncEngine) -> Iterator[_RosterSelectSpy]:
    """Record `program_roster` SELECTs on `engine` for the `with` block.

    Same `before_cursor_execute` mechanism as
    `test_rollup_rebuild_query_plan.py::_count_usage_events_selects` and
    `test_persona_resolver.py::_count_persona_config_selects`; detached in
    `finally` so it cannot leak into a sibling test through the
    session-scoped `test_engine`. Statements AND their bound parameters are
    kept, because TC-02 asserts on the predicate, not just the count.
    """
    spy = _RosterSelectSpy()
    sync_engine = engine.sync_engine

    def _before_cursor_execute(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        if statement.strip().upper().startswith("SELECT") and _PROGRAM_ROSTER_RE.search(statement):
            spy.statements.append(statement)
            spy.parameters.append(parameters)

    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield spy
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before_cursor_execute)


async def _seed_roster_row(session: AsyncSession, *, email: str, program_id: str) -> None:
    """Insert one active `program_roster` row and commit.

    Mirrors `tests/perf/test_program_roster_resolver_perf.py`'s seeding: the
    ORM supplies no `created_at`/`updated_at` default (the migration carries
    no `server_default` either — `app/models/roster.py`), so both are passed
    explicitly.
    """
    now = datetime.now(UTC)
    session.add(
        ProgramRoster(
            program_id=program_id,
            email=email,
            name="Eve Tester",
            role="developer",
            source="file",
            removed_at=None,
            created_at=now,
            updated_at=now,
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_kid_is_sole_roster_skip_discriminator_tc02(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-06-TC-02: `kid == DEV_BYPASS_KID` is the SOLE roster-skip
    discriminator (AC-4, FR-3, NFR-security).

    Two tokens hit the same `Depends(get_current_user)` route on the same app:

    - a GENUINE dev-bypass token, minted through the real `POST /auth/dev-bypass`
      (not hand-forged), carrying `programs: ["PROG-X","PROG-Y"]` as its own
      top-level claim — must be honoured verbatim, with the roster never queried;
    - a FORGED Keycloak-style token, signed by a real keypair under a `kid` that
      is NOT `DEV_BYPASS_KID`, smuggling `programs: ["PROG-Z"]` — must be
      resolved from `program_roster` (which grants it `PROG-Q` and nothing else),
      with its own claim ignored.

    The second half is the whole security value of this test. The two
    alternatives `app/core/auth.py`'s inline comment records as REJECTED are
    both exercised here: the forged token HAS a `programs` claim (so a
    presence-based discriminator would wrongly skip the roster) and it HAS a
    caller-chosen `email` (so a `payload.email`-based one would too). Both are
    caller-forgeable; `kid` is not, because it only ever resolves to a signing
    key inside AUTH-01's fail-closed environment allow-list.
    """
    await _seed_roster_row(test_session, email=_TC02_FORGED_EMAIL, program_id=_TC02_ROSTER_PROGRAM)

    app = build_app(
        environment="development",
        oidc_issuer=TEST_OIDC_ISSUER,
        oidc_client_id=TEST_OIDC_CLIENT_ID,
    )
    app.include_router(_guarded_router)
    app.dependency_overrides[get_db] = _db_override(test_session)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)

    async with async_client_for(app) as client:
        issue_resp = await client.post(
            "/auth/dev-bypass", json={"programs": _TC02_DEV_BYPASS_PROGRAMS}
        )
        assert issue_resp.status_code == 200, issue_resp.text
        dev_token = str(issue_resp.json()["access_token"])

        # TC-02 step 1 — the minted token really does have the new shape:
        # dev `kid`, `programs` as its OWN top-level claim, and no `groups`
        # key at all (AUTH-06-AC-4/AC-6, D-02 — omitted entirely, not empty).
        dev_header = _decode_unverified_header(dev_token)
        dev_claims = _decode_unverified_claims(dev_token)
        assert dev_header["kid"] == DEV_BYPASS_KID
        assert dev_claims["programs"] == _TC02_DEV_BYPASS_PROGRAMS
        assert "groups" not in dev_claims, (
            "AUTH-06-D-02: a dev-bypass token must carry NO `groups` claim at "
            f"all — not an empty one. Got groups={dev_claims.get('groups')!r}."
        )

        # TC-02 step 2 — same signing/claims path as any real Keycloak token
        # in this suite (`build_access_token`), differing only in the forged
        # `programs` claim. Its `kid` is the JWKS-served one, never the dev kid.
        forged_token = build_access_token(
            email=_TC02_FORGED_EMAIL,
            extra_claims={"programs": [_TC02_FORGED_CLAIM_PROGRAM]},
        )
        forged_claims = _decode_unverified_claims(forged_token)
        # False-green guard. Every assertion below compares "what the roster
        # says" against "what the token claimed" — if the token never actually
        # carried the smuggled claim (a silently-dropped `extra_claims`, a
        # renamed key), that comparison proves nothing while still passing.
        assert _decode_unverified_header(forged_token)["kid"] != DEV_BYPASS_KID
        assert forged_claims["programs"] == [_TC02_FORGED_CLAIM_PROGRAM], (
            "the forged token must genuinely carry the smuggled `programs` "
            "claim, or this test is vacuous. Claims were: "
            f"{forged_claims!r}"
        )
        assert forged_claims["email"] == _TC02_FORGED_EMAIL

        with _spy_program_roster_selects(test_engine) as dev_spy:
            dev_resp = await client.get(
                _GUARDED_ROUTE_PATH, headers={"Authorization": f"Bearer {dev_token}"}
            )

        with _spy_program_roster_selects(test_engine) as forged_spy:
            forged_resp = await client.get(
                _GUARDED_ROUTE_PATH, headers={"Authorization": f"Bearer {forged_token}"}
            )

    # Neither token may 401 or 500 — a session that fails to construct would
    # make every membership assertion below vacuously "safe".
    assert dev_resp.status_code == 200, dev_resp.text
    assert forged_resp.status_code == 200, forged_resp.text
    dev_body = dev_resp.json()
    forged_body = forged_resp.json()

    # --- dev-bypass branch: own claim, honoured verbatim, roster untouched ---
    assert dev_body["programs"] == _TC02_DEV_BYPASS_PROGRAMS, (
        "AUTH-06-AC-4: a dev-bypass session's programs must be its own "
        f"top-level claim verbatim, expected {_TC02_DEV_BYPASS_PROGRAMS!r}, "
        f"got {dev_body['programs']!r}. Dev-bypass runs with zero roster seed "
        "data by design, so reading the roster here would break it outright."
    )
    assert dev_body["groups"] == [], (
        "AUTH-06-D-02: `dev_bypass.py` emits no `groups` claim, so "
        f"`CurrentUser.groups` must fall back to []. Got {dev_body['groups']!r} "
        "— a non-empty value means the retired synthetic-groups construction "
        "is back."
    )
    assert dev_spy.count == 0, (
        "AUTH-06-FR-3: the `kid == DEV_BYPASS_KID` branch must skip the roster "
        f"query ENTIRELY, but {dev_spy.count} program_roster SELECT(s) ran: "
        f"{dev_spy.statements!r}"
    )

    # --- forged Keycloak token: roster wins, claim ignored (the whole point) ---
    assert forged_body["programs"] == [_TC02_ROSTER_PROGRAM], (
        "SECURITY REGRESSION — AUTH-06-FR-3 / NFR-security / TC-02. A "
        f"Keycloak-issued token (kid != {DEV_BYPASS_KID!r}) that smuggled "
        f"`programs: [{_TC02_FORGED_CLAIM_PROGRAM!r}]` was granted "
        f"caller-declared membership: expected [{_TC02_ROSTER_PROGRAM!r}] from "
        f"program_roster, got {forged_body['programs']!r}. On the non-dev-bypass "
        "branch `session.programs` MUST come from program_roster alone. The "
        "roster-skip branch fires if and only if `kid == DEV_BYPASS_KID` — "
        "never on the PRESENCE of a `programs` claim (this token has one) and "
        "never on `payload.email` (caller-supplied, forgeable). If you widened "
        "that branch, that is the regression this assertion exists to catch; "
        "do not relax it to match the new behaviour."
    )
    assert _TC02_FORGED_CLAIM_PROGRAM not in forged_body["programs"], (
        f"{_TC02_FORGED_CLAIM_PROGRAM!r} exists ONLY inside the forged token's "
        "own claim and in no roster row — its appearance in session.programs "
        "means the caller's claim was read on the Keycloak branch (FR-3)."
    )
    assert forged_spy.count == 1, (
        "AUTH-06-FR-1: exactly one program_roster SELECT per non-dev-bypass "
        f"session construction, got {forged_spy.count}: {forged_spy.statements!r}"
    )

    normalized_statement = " ".join(forged_spy.statements[0].upper().split())
    assert "REMOVED_AT IS NULL" in normalized_statement, (
        "AUTH-06-AC-3/FR-1: the roster query must filter soft-deleted rows "
        f"(`removed_at IS NULL`). Statement was: {forged_spy.statements[0]!r}"
    )
    assert _TC02_FORGED_EMAIL in forged_spy.bound_values(), (
        "AUTH-06-FR-1: the roster query must be bound to the VERIFIED `email` "
        f"claim ({_TC02_FORGED_EMAIL!r}). Bound parameters were: "
        f"{forged_spy.parameters!r}"
    )
