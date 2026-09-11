"""Roster-derived `session.programs` tests for `app/core/auth.py` —
AUTH-06-TC-01 and AUTH-06-TC-03 (`docs/test-cases/AUTH-06.json`, trackers
#248 / #250).

Full-content rewrite (AUTH-06 D-04 / T-09). This file used to test AUTH-01-FR-5's
`groups`-claim parsing via `app/core/auth.py::_parse_programs`. AUTH-06-AC-6
deleted that helper outright: on the non-dev-bypass path `session.programs` is
now resolved from the `program_roster` table by the verified `email` claim
(`app/core/program_roster_resolver.py`, AC-1/FR-1), and the raw `groups` claim
feeds nothing. Every `_parse_programs` test is therefore gone — not ported, not
skipped: the function no longer exists, so those cases have no subject.

Scope boundary:

- AUTH-06-TC-01 (first half): multi-program distinct-set aggregation,
  alias-row matching (AC-1), same-email cross-program removed-row exclusion
  (AC-3), zero-match success (AC-2), and the exclusive `program_roster` read
  (AC-9, FR-1).
- AUTH-06-TC-03 (second half): the cache / lock / timeout mechanics and the
  PII-free `program_membership_resolved` event (AC-5, FR-2,
  NFR-performance, NFR-observability). It is the one test here that reuses a
  SINGLE app — and therefore a single resolver cache — across several calls;
  TC-01's `_whoami_response` deliberately does the opposite.
- The `kid == DEV_BYPASS_KID` roster-skip discriminator (AUTH-06-TC-02, AC-4/
  FR-3) belongs to `test_auth_dev_bypass.py`.
- Signature verification, expiry, and forged-header cases stay in
  `test_auth_jwt_validation.py`; `Settings` field defaults stay in
  `test_auth_config.py`.

Every JWT built here is a VALID, non-dev-bypass token (`rsa_test_keypair`,
JWKS mocked via `keycloak_mock`) — this file is about where `programs` comes
from, never about whether a token is accepted.

Live database, deliberately: `migrated_db` + `test_session` seed real
`program_roster` rows against the disposable test Postgres, and the app under
test gets a REAL, DB-backed `ProgramRosterResolver` on
`app.state.program_roster_resolver` (not a stub). Roster derivation is this
file's entire subject — a stubbed resolver would assert nothing about it. The
`get_db` dependency is overridden onto the caller's own `test_session` so
seeding and the resolver's read share one connection (mirrors
`test_manifest_ingest.py::_db_override`).

AC-9's "program_roster only" claim is proven by a `before_cursor_execute`
listener on `test_engine` (mirrors `test_persona_resolver.py`'s
`_count_persona_config_selects`), which records the compiled statement and
bound parameters of every statement the three requests issue — so "zero
queries against `program_members` / `user_roles`" is an observation, not an
inference from reading the resolver's source.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.auth.jwks import JwksCache
from app.core import program_roster_resolver as roster_resolver_module
from app.core.auth import CurrentUser, get_current_user
from app.core.config import Settings
from app.core.db import get_db
from app.core.errors import register_exception_handlers
from app.core.logging import JSONFormatter
from app.core.program_roster_resolver import (
    ProgramRosterResolutionError,
    ProgramRosterResolver,
)
from app.models.roster import ProgramRoster
from tests.conftest import (
    TEST_OIDC_CLIENT_ID,
    TEST_OIDC_ISSUER,
    AlembicRunner,
    KeycloakMock,
    RSATestKeypair,
)

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

# TC-01's fixed identities. `ALICE_ALIAS` is a SEPARATE roster row for the same
# human — ING-10 writes one `program_roster` row per alias (ADR-0010), so the
# resolver's plain email equality already covers aliases with no special
# handling. That is exactly what makes it worth asserting: the alias must
# resolve to its OWN row's program only, never inherit the primary's.
ALICE_PRIMARY = "alice@example.com"
ALICE_ALIAS = "alice.rossi@example.com"
BOB_ZERO_MATCH = "bob@example.com"

PROG_ACTIVE_SHARED = "PROG-100"
PROG_ACTIVE_PRIMARY_ONLY = "PROG-200"
PROG_REMOVED = "PROG-300"

# Matches the TC's `removed_at=2026-08-01T00:00:00Z` seed. A fixed past instant,
# not `now - delta`: `removed_at IS NULL` is the predicate under test, so the
# exact value is irrelevant as long as it is non-NULL, and a literal keeps the
# seed readable against docs/test-cases/AUTH-06.json.
REMOVED_AT = datetime(2026, 8, 1, tzinfo=UTC)

_PROGRAM_ROSTER_RE = re.compile(r"\bprogram_roster\b", re.IGNORECASE)
_PROGRAM_MEMBERS_RE = re.compile(r"\bprogram_members\b", re.IGNORECASE)
_USER_ROLES_RE = re.compile(r"\buser_roles\b", re.IGNORECASE)
# SQLAlchemy renders `.is_(None)` as `<col> IS NULL`; the whitespace is
# normalised out so a re-wrapped compiled statement cannot silently fail this.
_REMOVED_AT_IS_NULL_RE = re.compile(r"removed_at\s+IS\s+NULL", re.IGNORECASE)


router = APIRouter()


@router.get("/whoami")
async def _whoami(user: CurrentUser = Depends(get_current_user)) -> dict[str, list[str]]:
    """Echoes `groups` (the raw claim, which now feeds nothing — AUTH-06-AC-6)
    and `programs` (roster-derived, AC-1). `user_id`/`email`/`role` claim
    mapping belongs to sibling task test files, per the module docstring's
    scope boundary."""
    return {"groups": user.groups, "programs": user.programs}


def _db_override(session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    """`get_db` override yielding the caller's own `test_session`.

    Same shape as `test_manifest_ingest.py::_db_override`: seeding and the
    resolver's read then share one live connection to the disposable test DB,
    never the dev database.
    """

    async def _get_db() -> AsyncIterator[AsyncSession]:
        yield session

    return _get_db


class _StubPersonaResolver:
    """Minimal local stub -- no I/O, never actually consulted here.

    Mirrors `tests/perf/test_programs_perf.py::_StubPersonaResolver`, the same
    precedent `_StubProgramRosterResolver` follows. Exists only to satisfy
    `get_persona_resolver`'s `app.state` read: AUTH-07 T-06/D-06 gave
    `get_current_user` a `Depends(get_persona_resolver)` parameter, and FastAPI
    resolves every declared dependency eagerly regardless of which branch of the
    body runs -- so the attribute must be present or EVERY request raises
    `AttributeError: 'State' object has no attribute 'persona_resolver'`.

    Neither method is reachable from this file: `get_current_user` only calls
    `resolve_precedence` when a token carries 2+ surviving roles, and every
    token built here goes through `build_access_token`'s `role=` parameter,
    which writes `realm_access.roles` as a single-element list. Only the
    attribute's existence matters.
    """

    async def resolve(self, role: str) -> str:
        raise AssertionError("unreachable: no test in this file resolves a persona")

    async def resolve_precedence(self, roles: list[str]) -> str:
        raise AssertionError("unreachable: every token here carries a single role")


def _build_app(settings: Settings, test_session: AsyncSession) -> FastAPI:
    """Throwaway app wired per D-07, without `create_app`.

    Sets `app.state.settings` / `app.state.jwks_cache` directly (the historical
    D-07-addendum reason this file never used `create_app`), and now also
    `app.state.program_roster_resolver` — `get_current_user` gained a
    `Depends(get_program_roster_resolver)` parameter in AUTH-06 T-03, which
    reads that attribute eagerly on every request.

    The resolver is a REAL `ProgramRosterResolver`, not a stub (contrast
    `test_auth_jwt_validation.py` / `test_ingest_token_isolation.py`, which
    stub it precisely because they are DB-free by design). A fresh instance per
    app also means a cold per-email cache per call, so TC-01's per-call
    one-query assertions measure a genuine `program_roster` read rather than a
    warm cache entry left behind by an earlier call.

    Takes `test_session` because the roster read needs a live session: the
    `get_db` override is part of this app's wiring now, not an optional extra.
    """
    app = FastAPI()
    register_exception_handlers(app)
    app.state.settings = settings
    app.state.jwks_cache = JwksCache(settings)
    app.state.program_roster_resolver = ProgramRosterResolver()
    app.state.persona_resolver = _StubPersonaResolver()
    app.dependency_overrides[get_db] = _db_override(test_session)
    app.include_router(router)
    return app


def _make_settings(**overrides: Any) -> Settings:
    """`Settings` for this file's tests.

    Every field the route path touches is passed explicitly as a constructor
    kwarg, which wins over any ambient env var / `.env` value under
    pydantic-settings' documented precedence — so no full hermetic-env dance
    like `test_auth_config.py`'s is needed here.

    `oidc_client_id` belongs in that list even though nothing here asserts on
    it: `app/core/auth.py::_claims_options` enforces `aud` against it, so left
    unpinned it falls through to whatever sits in the developer's real `.env`
    and every test in this file 401s on an `aud` mismatch against
    `build_access_token`'s `TEST_OIDC_CLIENT_ID`.

    `program_group_prefix` is deliberately NOT passed any more: AUTH-06-AC-6
    deletes the field, and nothing on this path reads it.
    """
    defaults: dict[str, Any] = {
        "oidc_issuer": TEST_OIDC_ISSUER,
        "oidc_client_id": TEST_OIDC_CLIENT_ID,
    }
    return Settings(**{**defaults, **overrides})


# -----------------------------------------------------------------------------
# `program_roster` seeding.
# -----------------------------------------------------------------------------


async def _seed_roster_row(
    test_session: AsyncSession,
    *,
    email: str,
    program_id: str,
    removed_at: datetime | None,
) -> None:
    """Insert one `program_roster` row directly (no commit — see `_seed_tc01`).

    `created_at`/`updated_at` are `nullable=False` with no server default
    (`app/models/roster.py`), so both must be supplied explicitly — same as
    `tests/perf/test_program_roster_resolver_perf.py`'s seed. `name`/`role`
    are irrelevant to this file's subject; the resolver selects `program_id`
    only.
    """
    now = datetime.now(UTC)
    test_session.add(
        ProgramRoster(
            program_id=program_id,
            email=email,
            name="Roster Fixture",
            role="developer",
            source="file",
            removed_at=removed_at,
            created_at=now,
            updated_at=now,
        )
    )


async def _seed_tc01(test_session: AsyncSession) -> None:
    """Seed exactly the four rows in AUTH-06-TC-01's `program_roster_seed`.

    `bob@example.com` is seeded with nothing on purpose — its zero-row result
    is AC-2's subject, and seeding it would defeat that.
    """
    await _seed_roster_row(
        test_session, email=ALICE_PRIMARY, program_id=PROG_ACTIVE_SHARED, removed_at=None
    )
    await _seed_roster_row(
        test_session, email=ALICE_ALIAS, program_id=PROG_ACTIVE_SHARED, removed_at=None
    )
    await _seed_roster_row(
        test_session, email=ALICE_PRIMARY, program_id=PROG_ACTIVE_PRIMARY_ONLY, removed_at=None
    )
    await _seed_roster_row(
        test_session, email=ALICE_PRIMARY, program_id=PROG_REMOVED, removed_at=REMOVED_AT
    )
    await test_session.commit()


# -----------------------------------------------------------------------------
# SQL query spy (AC-9 / FR-1). Mirrors `test_persona_resolver.py`'s
# `_count_persona_config_selects`, widened from a counter to a recorder because
# AC-9 needs the statement text and bound parameters, not just a count.
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class _CapturedQuery:
    """One `before_cursor_execute` observation: compiled SQL + bound params."""

    statement: str
    parameters: Any

    def touches(self, pattern: re.Pattern[str]) -> bool:
        return bool(pattern.search(self.statement))


def _param_values(parameters: Any) -> list[Any]:
    """Flatten DBAPI bound parameters to a plain value list.

    The shape varies by driver and by executemany-ness (dict of named params,
    sequence of positional params, or a sequence of either). Flattening keeps
    the email assertion independent of which one psycopg hands back.
    """
    if isinstance(parameters, dict):
        return list(parameters.values())
    if isinstance(parameters, (list, tuple)):
        flattened: list[Any] = []
        for entry in parameters:
            if isinstance(entry, dict):
                flattened.extend(entry.values())
            elif isinstance(entry, (list, tuple)):
                flattened.extend(entry)
            else:
                flattened.append(entry)
        return flattened
    return [parameters]


class _QuerySpy:
    """Records every statement executed on the spied engine, in order."""

    def __init__(self) -> None:
        self.all: list[_CapturedQuery] = []
        self._taken = 0

    def record(self, statement: str, parameters: Any) -> None:
        self.all.append(_CapturedQuery(statement=statement, parameters=parameters))

    def take(self) -> list[_CapturedQuery]:
        """Return statements captured since the previous `take()`.

        Lets one spy attribute queries to individual `/whoami` calls without
        needing a spy per call, while `self.all` still backs the across-all-
        three-calls assertions the TC asks for.
        """
        fresh = self.all[self._taken :]
        self._taken = len(self.all)
        return fresh


@contextmanager
def _query_spy(engine: AsyncEngine) -> Iterator[_QuerySpy]:
    """Attach a `before_cursor_execute` recorder for the duration of the block.

    Attached AFTER seeding (TC-01 step 2) so the fixture's own INSERTs are not
    mistaken for lookups made by `get_current_user`.
    """
    spy = _QuerySpy()
    sync_engine = engine.sync_engine

    def _before_cursor_execute(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        spy.record(statement, parameters)

    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield spy
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before_cursor_execute)


async def _whoami_response(
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    test_session: AsyncSession,
    token: str,
    **settings_overrides: Any,
) -> dict[str, Any]:
    """Build a fresh app + settings, mock JWKS, and hit `/whoami` with `token`.

    Asserts the request succeeded before handing back the body, so a caller's
    assertions are only ever about `programs`, never an incidental 401/500.
    """
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    app = _build_app(_make_settings(**settings_overrides), test_session)
    async with async_client_for(app) as client:
        resp = await client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    return dict(resp.json())


def _assert_single_roster_lookup(queries: list[_CapturedQuery], *, email: str, label: str) -> None:
    """One `program_roster` read, filtered on `email` AND `removed_at IS NULL`.

    Asserted per call rather than only in aggregate: a resolver that issued two
    reads for one session, or none at all, would still satisfy an
    across-all-calls total.
    """
    assert len(queries) == 1, (
        f"{label}: expected exactly one statement during this /whoami call, got "
        f"{len(queries)}: {[q.statement for q in queries]}"
    )
    query = queries[0]
    assert query.touches(_PROGRAM_ROSTER_RE), (
        f"{label}: the lookup must read program_roster (AC-9/FR-1), got: {query.statement}"
    )
    assert _REMOVED_AT_IS_NULL_RE.search(query.statement), (
        f"{label}: the program_roster read must carry the `removed_at IS NULL` "
        f"predicate (AC-3), got: {query.statement}"
    )
    assert email in _param_values(query.parameters), (
        f"{label}: the read must be bound to {email!r}, got params: {query.parameters!r}"
    )


# -----------------------------------------------------------------------------
# AUTH-06-TC-01 — roster-derived session.programs, end to end through the real
# `get_current_user` dependency against a live `program_roster`.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_roster_derived_programs_aggregation_alias_and_removed_row_tc01(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-06-TC-01 (AC-1/AC-2/AC-3/AC-9, FR-1) — the story's core swap.

    One scenario, three non-dev-bypass sessions over one seeded roster, because
    the TC's fifth expected result ("zero queries against program_members or
    user_roles across all three calls") is a property of the three calls
    together, not of any one of them.

    - alice primary -> {PROG-100, PROG-200}: distinct-set aggregation across two
      programs, with PROG-300 excluded even though the SAME email holds live
      rows elsewhere (AC-3 — a soft-deleted row is not merely "an email with no
      live rows").
    - alice alias -> {PROG-100}: the alias row resolves on its own, and pointedly
      does NOT pick up PROG-200 from the primary identity (AC-1).
    - bob -> [] with HTTP 200: a zero-row roster result is an answer, not a
      failure (AC-2). `_whoami_response` asserts the 200 itself, so a regression
      to 401/500 fails here rather than surfacing as a confusing decode error.

    Set comparison is deliberate: `SELECT DISTINCT` has no ORDER BY, so row
    order is not a contract and asserting a list would be asserting Postgres's
    plan.
    """
    await _seed_tc01(test_session)

    alice_primary_token = build_access_token(email=ALICE_PRIMARY)
    alice_alias_token = build_access_token(email=ALICE_ALIAS)
    bob_token = build_access_token(email=BOB_ZERO_MATCH)

    with _query_spy(test_engine) as spy:
        alice_primary_body = await _whoami_response(
            async_client_for, keycloak_mock, rsa_test_keypair, test_session, alice_primary_token
        )
        alice_primary_queries = spy.take()

        alice_alias_body = await _whoami_response(
            async_client_for, keycloak_mock, rsa_test_keypair, test_session, alice_alias_token
        )
        alice_alias_queries = spy.take()

        bob_body = await _whoami_response(
            async_client_for, keycloak_mock, rsa_test_keypair, test_session, bob_token
        )
        bob_queries = spy.take()

    # --- AC-1 / AC-3: distinct set across programs, soft-deleted row excluded.
    assert set(alice_primary_body["programs"]) == {PROG_ACTIVE_SHARED, PROG_ACTIVE_PRIMARY_ONLY}
    assert PROG_REMOVED not in alice_primary_body["programs"]
    assert len(alice_primary_body["programs"]) == 2, (
        f"SELECT DISTINCT must not emit duplicates: {alice_primary_body['programs']}"
    )

    # --- AC-1: the alias row resolves independently of the primary's rows.
    assert set(alice_alias_body["programs"]) == {PROG_ACTIVE_SHARED}
    assert PROG_ACTIVE_PRIMARY_ONLY not in alice_alias_body["programs"], (
        "the alias identity must not inherit the primary email's other programs "
        "— roster membership is per row, keyed on the verified email claim"
    )

    # --- AC-2: zero roster rows is [] on a 200, not an error.
    assert bob_body["programs"] == []

    # --- AC-9 corollary: none of the three tokens carried a `groups` claim, so
    # the programs observed above cannot have come from one. AUTH-06-AC-6
    # retired groups-derived membership; `groups` is still echoed verbatim.
    for label, body in (
        ("alice primary", alice_primary_body),
        ("alice alias", alice_alias_body),
        ("bob", bob_body),
    ):
        assert body["groups"] == [], f"{label}: unexpected groups claim on the minted token"

    # --- AC-9 / FR-1: program_roster is the only table read, on every call.
    _assert_single_roster_lookup(alice_primary_queries, email=ALICE_PRIMARY, label="alice primary")
    _assert_single_roster_lookup(alice_alias_queries, email=ALICE_ALIAS, label="alice alias")
    _assert_single_roster_lookup(bob_queries, email=BOB_ZERO_MATCH, label="bob")

    assert [q for q in spy.all if q.touches(_PROGRAM_MEMBERS_RE)] == [], (
        "program_members is rollup-owned (rebuilt from usage_events on every "
        "activity ingest, ADR-0010) and must never back session.programs (AC-9)"
    )
    assert [q for q in spy.all if q.touches(_USER_ROLES_RE)] == [], (
        "user_roles is reference/audit only (ING-08 AC-4) and must never back "
        "session.programs (AC-9)"
    )
    assert all(q.touches(_PROGRAM_ROSTER_RE) for q in spy.all), (
        "every statement issued during the three /whoami calls must target "
        f"program_roster: {[q.statement for q in spy.all]}"
    )


# =============================================================================
# AUTH-06-TC-03 scaffolding — cache / lock / timeout mechanics and the PII-free
# `program_membership_resolved` event (AC-5, FR-2, NFR-performance,
# NFR-observability).
# =============================================================================

# TC-03's single identity, deliberately distinct from TC-01's: neither a roster
# row nor a resolver cache entry may be shared between the two tests.
FRANK = "frank@example.com"
PROG_FRANK = "PROG-M"

# The contract values, read off AUTH-06-TC-03's own `test_data` block rather
# than imported from the resolver's private `_CACHE_TTL_SECONDS` /
# `_QUERY_TIMEOUT_SECONDS`. Importing them would make this test agree with the
# module by construction — a silent change from 300s to 30s would keep passing.
CACHE_TTL_SECONDS = 300.0
QUERY_TIMEOUT_SECONDS = 3.0
SIMULATED_QUERY_DELAY_SECONDS = 5.0

# Turns TC-03's "not indefinitely" clause into an assertion instead of a hung
# suite. Above the simulated stall on purpose: a resolver that sat out the full
# 5.0s must fail as "did not raise" (a wrong-bound bug), not as "hung".
HANG_GUARD_SECONDS = 10.0

MEMBERSHIP_EVENT = "program_membership_resolved"

TIER_CACHE_HIT = "cache_hit"
TIER_DB_QUERY = "db_query"

# The exact rendered payload TC-03 permits: `JSONFormatter`'s four first-class
# keys plus the resolver's two extras. `timestamp` appears ONCE, not twice —
# `JSONFormatter` writes its own first and an `extra` can never overwrite an
# existing payload key (`app/core/logging.py`), so the resolver's inert
# `timestamp` extra is invisible here. No `email`, no `program_id` list.
EXPECTED_EVENT_KEYS = frozenset(
    {"timestamp", "level", "logger", "message", "tier", "program_count"}
)


class _FakeClock:
    """Callable stand-in for `time.monotonic` (mirrors `test_persona_resolver.py`).

    Patched onto the shared `time` module for one step via
    `monkeypatch.setattr(roster_resolver_module.time, "monotonic", clock)`, so
    the resolver's real TTL comparison (`time.monotonic() < expiry`) is what
    decides staleness — rather than the test hand-editing `_cache` and thereby
    asserting nothing about the TTL.

    Start it from the REAL clock, never from 0.0: a live entry's expiry is
    `real_monotonic_at_write + 300`, so a fake clock starting at 0.0 would look
    *fresher* than the entry it is meant to expire.
    """

    def __init__(self, start: float) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


@pytest.fixture
def root_log_capture() -> Iterator[io.StringIO]:
    """Root-logger capture through the REAL `JSONFormatter`
    (mirrors `test_auth_dev_bypass.py::root_log_capture`).

    Formatted output, not raw `LogRecord`s, on purpose: TC-03's PII clause is
    about what reaches a log sink, and `JSONFormatter` is what decides that —
    it merges `extra` into the payload (`app/core/logging.py`), so asserting on
    the rendered JSON keys asserts the real wire shape rather than the
    arguments of the logging call.

    Also force-clears `disabled` on the resolver's own logger: `migrations/
    env.py:19` runs `fileConfig(...)` on every `migrated_db` upgrade, and its
    default `disable_existing_loggers=True` disables every logger not named in
    `alembic.ini` — including `app.core.program_roster_resolver`, already
    imported at collection time. `test_persona_resolver.py::_capture_logger`
    clears the same flag for the same reason. Without it the event assertions
    below would inspect an empty list and pass vacuously.

    Everything mutated is restored in a `finally`, so this fixture cannot leak
    logging state into a later test.
    """
    root = logging.getLogger()
    resolver_logger = logging.getLogger(roster_resolver_module.__name__)
    original_handlers = root.handlers
    original_level = root.level
    original_disabled = root.disabled
    resolver_disabled = resolver_logger.disabled
    resolver_propagate = resolver_logger.propagate
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JSONFormatter())
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    root.disabled = False
    resolver_logger.disabled = False
    resolver_logger.propagate = True
    try:
        yield stream
    finally:
        root.handlers = original_handlers
        root.setLevel(original_level)
        root.disabled = original_disabled
        resolver_logger.disabled = resolver_disabled
        resolver_logger.propagate = resolver_propagate


class _MembershipEventTap:
    """Reads `program_membership_resolved` payloads out of the captured stream.

    `take()` mirrors `_QuerySpy.take()`: it returns only the events emitted
    since the previous call, so each TC-03 step can assert its own `tier`
    without a fixture per step, while `all` still backs the across-all-steps
    PII assertions the TC asks for.
    """

    def __init__(self, stream: io.StringIO) -> None:
        self._stream = stream
        self._taken = 0

    @property
    def lines(self) -> list[str]:
        return [line for line in self._stream.getvalue().splitlines() if line]

    @property
    def all(self) -> list[dict[str, Any]]:
        records = [json.loads(line) for line in self.lines]
        return [r for r in records if r.get("message") == MEMBERSHIP_EVENT]

    def take(self) -> list[dict[str, Any]]:
        fresh = self.all[self._taken :]
        self._taken += len(fresh)
        return fresh


def _tiers(events: list[dict[str, Any]]) -> list[str]:
    return [event["tier"] for event in events]


# -----------------------------------------------------------------------------
# AUTH-06-TC-03 — one app, one resolver, one cache, four steps.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_roster_lookup_cache_lock_and_timeout_mechanics_tc03(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
    root_log_capture: io.StringIO,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AUTH-06-TC-03 (AC-5, FR-2, NFR-performance, NFR-observability).

    One test, four steps, because every step depends on the cache state the
    previous one left behind — which is also why this builds the app ONCE and
    reuses it, instead of calling TC-01's `_whoami_response` (a fresh app per
    call, hence a fresh resolver and a cold cache every time: correct for
    TC-01's per-call one-query claim, fatal to any claim about a cache).

    1. Cold call     -> exactly one `program_roster` query, `tier=db_query`.
    2. Warm call     -> zero queries, `tier=cache_hit`.
    3. Post-expiry, two concurrent calls -> exactly ONE query between them
       (the `asyncio.Lock` + double-checked re-read), `tier=db_query` on both.
    4. Stalled read  -> raises at the 3.0s `wait_for` bound, not at 5.0s and
       not never.

    On step 3's tiers: `tier` reports which PATH served the call, not whether
    that call itself issued a query (`program_roster_resolver.resolve`'s own
    docstring). The waiter served by the double-checked re-read reached the
    lock, so it reports `db_query` too — one query, two `db_query` events is
    the specified behaviour, not a miscount.
    """
    await _seed_roster_row(test_session, email=FRANK, program_id=PROG_FRANK, removed_at=None)
    await test_session.commit()

    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    app = _build_app(_make_settings(), test_session)
    resolver: ProgramRosterResolver = app.state.program_roster_resolver
    headers = {"Authorization": f"Bearer {build_access_token(email=FRANK)}"}
    events = _MembershipEventTap(root_log_capture)

    with _query_spy(test_engine) as spy:
        async with async_client_for(app) as client:
            # --- Step 1: cold cache -> one query, tier=db_query. -------------
            cold = await client.get("/whoami", headers=headers)
            assert cold.status_code == 200, cold.text
            assert cold.json()["programs"] == [PROG_FRANK]
            _assert_single_roster_lookup(spy.take(), email=FRANK, label="step 1 (cold)")
            assert _tiers(events.take()) == [TIER_DB_QUERY]

            # --- Step 2: within TTL -> zero queries, tier=cache_hit. ---------
            warm = await client.get("/whoami", headers=headers)
            assert warm.status_code == 200, warm.text
            assert warm.json()["programs"] == [PROG_FRANK], (
                "a cache hit must return the same membership as the cold read"
            )
            warm_queries = spy.take()
            assert warm_queries == [], (
                "a warm cache entry must be served without touching the database "
                f"(FR-2): {[q.statement for q in warm_queries]}"
            )
            assert _tiers(events.take()) == [TIER_CACHE_HIT]

            # --- Step 3: expire the TTL, then two concurrent calls. ----------
            # The clock is started from the real one and advanced past the TTL:
            # the step-1 entry expires at `written_at + 300`, and `written_at`
            # is necessarily <= the value captured here.
            clock = _FakeClock(start=time.monotonic())
            clock.advance(CACHE_TTL_SECONDS + 1.0)
            monkeypatch.setattr(roster_resolver_module.time, "monotonic", clock)
            first, second = await asyncio.gather(
                client.get("/whoami", headers=headers),
                client.get("/whoami", headers=headers),
            )
            # Restore the real clock before step 4 (mirrors
            # `test_rollup_rebuild_transaction.py:293`'s use of `undo()`): the
            # only patch in force is the clock, and a FROZEN monotonic would
            # stop `wait_for`'s 3.0s timer from ever firing — step 4 needs a
            # clock that genuinely advances.
            monkeypatch.undo()

            for label, resp in (("concurrent A", first), ("concurrent B", second)):
                assert resp.status_code == 200, f"{label}: {resp.text}"
                assert resp.json()["programs"] == [PROG_FRANK], label
            _assert_single_roster_lookup(
                spy.take(), email=FRANK, label="step 3 (both concurrent calls)"
            )
            assert _tiers(events.take()) == [TIER_DB_QUERY, TIER_DB_QUERY]

            # --- Step 4: stalled read must fail at the 3.0s bound. -----------
            # The cache entry is evicted directly rather than clock-expired,
            # for the reason recorded above; `tests/perf/
            # test_program_roster_resolver_perf.py` clears `_cache` the same way.
            resolver._cache.pop(FRANK, None)

            async def _stalled_query(email: str, db: AsyncSession) -> list[str]:
                """Stand-in for the resolver's `_query_roster`, stalled past the bound.

                `_query_roster` and NOT `_resolve_uncached` is the patch point:
                the 3.0s `wait_for` lives inside `_resolve_uncached`, so
                replacing that method would delete the very bound under test.
                Touches no session: `wait_for` cancels this coroutine, and a
                cancelled real query would leave the shared `test_session`
                mid-statement.
                """
                await asyncio.sleep(SIMULATED_QUERY_DELAY_SECONDS)
                return [PROG_FRANK]

            monkeypatch.setattr(resolver, "_query_roster", _stalled_query)

            started = time.perf_counter()
            try:
                with pytest.raises(ProgramRosterResolutionError):
                    await asyncio.wait_for(
                        client.get("/whoami", headers=headers), timeout=HANG_GUARD_SECONDS
                    )
            except TimeoutError:
                pytest.fail(
                    f"the stalled roster read did not fail within {HANG_GUARD_SECONDS}s — the "
                    f"{QUERY_TIMEOUT_SECONDS}s asyncio.wait_for bound is not being applied at "
                    "all, so an unreachable database would hang every authenticated request"
                )
            elapsed = time.perf_counter() - started

            assert QUERY_TIMEOUT_SECONDS - 0.5 <= elapsed < SIMULATED_QUERY_DELAY_SECONDS - 0.5, (
                f"the stalled read must fail at ~{QUERY_TIMEOUT_SECONDS}s, not at "
                f"{SIMULATED_QUERY_DELAY_SECONDS}s and not instantly; measured {elapsed:.3f}s"
            )
            stalled_queries = spy.take()
            assert stalled_queries == [], (
                "the stalled step replaced _query_roster, so no real statement should have "
                f"run: {[q.statement for q in stalled_queries]}"
            )
            assert events.take() == [], (
                "a resolution that raised must not emit program_membership_resolved — "
                "the event is logged only after a successful resolve"
            )

    # --- AC-5 / FR-2: the four steps produced exactly the tier sequence the
    # TC specifies. Asserted as a whole sequence (not four independent counts)
    # so a mis-ordered or duplicated emission cannot slip through, and so the
    # PII loop below can never run over an empty list.
    all_events = events.all
    assert _tiers(all_events) == [
        TIER_DB_QUERY,  # step 1, cold
        TIER_CACHE_HIT,  # step 2, within TTL
        TIER_DB_QUERY,  # step 3, lock winner
        TIER_DB_QUERY,  # step 3, waiter served by the double-checked re-read
    ], f"unexpected program_membership_resolved sequence: {all_events}"

    # --- NFR-security / NFR-observability: the exact 3-field allowlist.
    for index, record in enumerate(all_events):
        rendered = json.dumps(record)
        assert set(record) == set(EXPECTED_EVENT_KEYS), (
            f"event {index} carries fields outside the allowlist "
            f"{sorted(EXPECTED_EVENT_KEYS)}: {sorted(record)}"
        )
        assert "email" not in record, f"event {index} leaks an email key: {rendered}"
        assert record["program_count"] == 1, (
            f"event {index} must report the resolved count, not the payload: {rendered}"
        )
        assert FRANK not in rendered, f"event {index} leaks the resolved email (PII): {rendered}"
        assert PROG_FRANK not in rendered, (
            f"event {index} leaks the resolved program_id list: {rendered}"
        )

    # Widened to the whole capture: `program_membership_resolved` is the only
    # event this path emits, so neither the email nor the resolved program_id
    # may appear anywhere in the output the four steps produced (mirrors
    # `test_auth_dev_bypass.py`'s TC-10 whole-stream PII check).
    captured = root_log_capture.getvalue()
    assert FRANK not in captured, f"the resolved email (PII) reached log output: {captured}"
    assert PROG_FRANK not in captured, f"the resolved program_id reached log output: {captured}"
