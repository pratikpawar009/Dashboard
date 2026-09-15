"""Shared fixtures for tests needing a live, disposable test Postgres database.

Fixtures only — no test functions live here. Consumed by `tests/test_migrations.py`
(and any `tests/test_models.py` case that needs a live DB).

Test-DB URL convention (T-10): no existing convention was found in
`app.core.config.Settings` or `.env.example` (both declare only `DATABASE_URL`,
pointed at the local dev database) — this establishes one:

- `TEST_DATABASE_URL` env var wins if set (CI / custom local setups).
- Otherwise the test DB is derived from `settings.database_url` by suffixing
  its database name with `_test` (e.g. `.../dashboard` -> `.../dashboard_test`),
  keeping host/port/user/password identical to local dev. This never points at
  the dev database itself, so a test run cannot clobber dev data.

Alembic invocation: programmatic, via `alembic.command.upgrade`/`downgrade`
against a constructed `alembic.config.Config` — never a shelled-out `alembic`
CLI subprocess (matches this project's existing async, in-process migration
runner in `migrations/env.py`; see alembic-patterns skill).

Gotcha this file works around: `migrations/env.py` reads its connection URL
from `app.core.config.settings.database_url` directly
(`config.set_main_option("sqlalchemy.url", settings.database_url)`,
`migrations/env.py:20`) rather than from the `Config` object passed to
`alembic.command.*`. Setting `sqlalchemy.url` on our own `Config` instance
alone would therefore be silently overridden back to the dev DB by `env.py`.
`AlembicRunner` below works around this by monkeypatching the shared
`settings.database_url` singleton for the duration of each upgrade/downgrade
call and restoring it in a `finally`, rather than duplicating/forking `env.py`'s
URL-resolution logic here.

Fixture scoping choice (documented per research's caveat — no pre-existing
pytest convention in this repo to follow, see pytest-patterns skill): the
`migrated_db` fixture is function-scoped and runs a full `upgrade head` /
`downgrade base` around every test, rather than a session-scoped schema with
per-test truncation. This story's schema is small (18 tables) and
`test_migrations.py`'s subject under test IS the migration's up/down
correctness (round-trip, `alembic check` zero-diff) — a shared, once-migrated
session-scoped schema would hide exactly the bugs those tests exist to catch.
The cost (each test pays a full upgrade+downgrade) is acceptable at this table
count.
"""

import asyncio
import hashlib
import logging
import os
import re
import secrets
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
import pytest
import pytest_asyncio
import respx
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from authlib.jose import JsonWebKey, Key, jwt
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, settings
from app.models.ingestion import IngestToken
from app.models.rollup import OrgSummaryRollup
from app.services.rollup_rebuild import RebuildResult, rebuild_org_rollups, rebuild_program_rollups

API_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = API_ROOT / "alembic.ini"


def _test_db_discriminator() -> str:
    """Per-runner suffix so concurrent pytest runs do not share one test DB.

    AF-11 (ING-10, triaged 2026-09-08): `migrated_db` below runs a full
    `alembic upgrade head` / `downgrade base` around EVERY test. When two
    pytest processes hit the same database, one process's `downgrade base`
    drops the schema another is mid-test against, producing errors like
    `UndefinedObject: index ... does not exist` and `UniqueViolation` on
    `pg_type`. Worse, each run reports its own suite green because it happens
    to hold the DB at that instant -- a **false green**, which is how a broken
    test file can look passing. Three separate workers hit this during ING-10.

    Discriminators, in precedence order:

    1. `TEST_DATABASE_URL` -- an explicit full override, handled by the caller.
    2. `PYTEST_XDIST_WORKER` (`gw0`, `gw1`, ...) -- set automatically by
       pytest-xdist, so `-n auto` isolates without any further setup.
    3. `HARNESS_TEST_DB_SUFFIX` -- for concurrent *separate* pytest processes,
       which is the case that actually bit ING-10 (parallel agent workers, not
       xdist). A runner that sets this gets its own database.

    Returns `""` when none is set, which reproduces the historical
    single-`_test`-database behaviour EXACTLY -- so a plain serial `uv run
    pytest` is unchanged and no existing invocation has to be updated.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if worker:
        return f"_{worker}"
    suffix = os.environ.get("HARNESS_TEST_DB_SUFFIX")
    if suffix:
        return f"_{re.sub(r'[^A-Za-z0-9_]', '_', suffix)}"
    return ""


def _derive_test_database_url() -> str:
    """Resolve the disposable test-DB URL per the module docstring's convention."""
    override = os.environ.get("TEST_DATABASE_URL")
    if override:
        return override
    parts = urlsplit(settings.database_url)
    if not parts.path or parts.path == "/":
        raise RuntimeError(
            "settings.database_url has no database name to derive a "
            f"'_test' suffix from: {settings.database_url!r}"
        )
    test_path = f"{parts.path}_test{_test_db_discriminator()}"
    return urlunsplit((parts.scheme, parts.netloc, test_path, parts.query, parts.fragment))


def repopulate(stmt: Any) -> Any:
    """Force a SELECT to re-read committed rows instead of the identity map.

    AF-14 (ING-10, triaged 2026-09-08): services in this codebase mutate rows
    with raw Core statements -- e.g. `manifest_ingest.py`'s
    `pg_insert(...).on_conflict_do_update(...)`. Postgres's `ON CONFLICT DO
    UPDATE` **preserves the existing row's primary key**, so a session that
    already loaded that row keeps serving the pre-update object out of its
    identity map. A test that calls a service twice and re-fetches in between
    therefore asserts against STALE data -- and, being an assertion that
    happens to pass, it is another silent false green.

    Wrap any post-service re-fetch in a direct-session test with this:

        row = (await session.execute(repopulate(select(Model).where(...)))).scalar_one()

    `session.expire_all()` is the blunter alternative; this keeps the
    invalidation scoped to the one query that needs it.
    """
    return stmt.execution_options(populate_existing=True)


def _ensure_database_exists(url: str) -> None:
    """`CREATE DATABASE` the derived test DB when it is missing.

    Needed because `_test_db_discriminator()` (AF-11) can point at a database
    nobody has created yet -- an xdist worker's `..._test_gw3`, or a
    `HARNESS_TEST_DB_SUFFIX` runner's own. Without this, isolating a run would
    mean provisioning its database by hand first, which nobody would do, and
    the isolation would go unused.

    Connects to the server's default `postgres` maintenance database with
    autocommit (Postgres forbids `CREATE DATABASE` inside a transaction) and is
    a no-op when the database already exists -- so the historical
    `<db>_test` path is untouched. The database is deliberately NOT dropped
    afterwards: a drop would be another cross-process footgun of exactly the
    kind AF-11 is about, and an empty migrated-then-downgraded DB costs nothing
    to leave behind.
    """
    import psycopg

    parts = urlsplit(url)
    dbname = parts.path.lstrip("/")
    admin = urlunsplit((parts.scheme, parts.netloc, "/postgres", "", ""))
    # psycopg speaks plain libpq URLs, not SQLAlchemy's `+driver` dialect form.
    admin = admin.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(admin, autocommit=True) as conn:
        exists = conn.execute(
            "select 1 from pg_database where datname = %s", (dbname,)
        ).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{dbname}"')


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Disposable test-DB URL — never the dev DB. See module docstring."""
    url = _derive_test_database_url()
    _ensure_database_exists(url)
    return url


@pytest.fixture(scope="session")
def alembic_config() -> AlembicConfig:
    """Programmatic Alembic `Config`, pointed at this project's `alembic.ini`.

    `script_location` resolves via `alembic.ini`'s own `%(here)s` token
    (Alembic >=1.13, pinned in `pyproject.toml`) — no override needed here.
    """
    return AlembicConfig(str(ALEMBIC_INI))


def _run_in_thread(fn: Any, *args: Any) -> None:
    """Run a sync callable in a fresh worker thread and propagate its result.

    `migrations/env.py`'s online path calls `asyncio.run(...)` internally
    (`run_migrations_online`, `migrations/env.py:83`). That's fine when
    `alembic.command.upgrade`/`downgrade` is invoked during plain sync pytest
    fixture setup/teardown (no event loop running yet) — but `test_migrations.py`
    also needs to call `migrated_db.upgrade`/`.downgrade` directly from inside
    `async def` test bodies (e.g. the round-trip / broken-downgrade meta-tests),
    where pytest-asyncio already has a loop running on the current thread and
    `asyncio.run()` raises `RuntimeError: asyncio.run() cannot be called from a
    running event loop`. Running the alembic call in its own worker thread
    sidesteps this unconditionally, in both call contexts, since a fresh thread
    never has a running loop of its own. `ThreadPoolExecutor.submit(...).result()`
    blocks the caller until the worker finishes and re-raises any exception.
    """
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(fn, *args).result()


@dataclass
class AlembicRunner:
    """Programmatic `alembic upgrade`/`downgrade` against the disposable test DB.

    See module docstring for why `settings.database_url` is monkeypatched
    around each call rather than set on `config` alone, and `_run_in_thread`
    for why the call is dispatched to a worker thread.
    """

    config: AlembicConfig
    database_url: str

    def upgrade(self, revision: str = "head") -> None:
        original = settings.database_url
        settings.database_url = self.database_url
        try:
            _run_in_thread(alembic_command.upgrade, self.config, revision)
        finally:
            settings.database_url = original

    def downgrade(self, revision: str = "base") -> None:
        original = settings.database_url
        settings.database_url = self.database_url
        try:
            _run_in_thread(alembic_command.downgrade, self.config, revision)
        finally:
            settings.database_url = original


@pytest.fixture(scope="session")
def alembic_runner(alembic_config: AlembicConfig, test_database_url: str) -> AlembicRunner:
    """Session-scoped runner — cheap to construct, safe to reuse across tests."""
    return AlembicRunner(config=alembic_config, database_url=test_database_url)


@pytest.fixture
def migrated_db(alembic_runner: AlembicRunner) -> Iterator[AlembicRunner]:
    """Function-scoped: `upgrade head` before the test, `downgrade base` after.

    Yields the `alembic_runner` so a test can also drive `upgrade`/`downgrade`
    directly mid-test (e.g. round-trip or broken-downgrade meta-tests) without
    losing the guaranteed teardown.
    """
    alembic_runner.upgrade("head")
    try:
        yield alembic_runner
    finally:
        alembic_runner.downgrade("base")


@pytest_asyncio.fixture(scope="session")
async def test_engine(test_database_url: str) -> AsyncIterator[AsyncEngine]:
    """Session-scoped async SQLAlchemy engine against the disposable test DB.

    Does not run migrations itself — pair with `migrated_db` in tests that
    need a live schema before querying/inserting through this engine.
    """
    engine = create_async_engine(test_database_url)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def test_session(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Function-scoped `AsyncSession` bound to `test_engine`."""
    session_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


# =============================================================================
# BED-05 (T-02, F-05) — four-distinct-program concurrent-session fixture
# (research condition C-4, BED-05-FR-4). Consumed by
# `tests/unit/test_rollup_rebuild_concurrency.py` (BED-05-TC-01 / AC-1, T-10 —
# a different task/worker; this file supplies only the fixture, never that
# test).
#
# Why a new fixture: `migrated_db`/`test_session` above are both single-session
# — every existing rollup_rebuild test (`tests/perf/test_rollup_rebuild_perf.py`,
# `tests/unit/test_rollup_rebuild_transaction.py`, ...) runs its call pair on
# ONE `AsyncSession`, so two calls on the same session are always ordered by
# that session's own transaction boundary and can never race. AC-1's scenario
# is four *distinct* ingest-token callers, each with their own session,
# hitting `rebuild_org_rollups`' org-singleton write path (`org_summary_rollup`,
# `token_series`, `mau_series` — `DECISIONS.md` D-01) at the same time.
# Reproducing that needs four independently-connected `AsyncSession`s racing
# through real Postgres I/O, not four coroutines sharing one
# session/connection.
#
# The sessions below are bound to the shared, session-scoped `test_engine`
# (never a fresh per-fixture engine) so each gets its own pooled connection
# and their statements genuinely overlap at the wire level — real psycopg
# network I/O yields control back to the event loop at each `await`, so
# `asyncio.gather` across four such sessions is genuine concurrency, not the
# false-concurrency trap `tests/perf/test_auth_jwks_perf.py`'s docstring
# documents for a purely synchronous mock (AF-04, that file). A single shared
# `AsyncSession` here would collapse this fixture back to the serial case it
# exists to avoid; `run_concurrent_rebuild_pairs` below is how genuine
# concurrency was verified for this fixture, not assumed.
# =============================================================================

#: Fixed, distinct program ids for the AC-1 four-program case. Not reused by
#: any other test's seeded `usage_events` (grep before adding a new
#: rollup_rebuild test that also seeds a "prog-concurrent-*" program).
FOUR_CONCURRENT_PROGRAM_IDS: tuple[str, str, str, str] = (
    "prog-concurrent-1",
    "prog-concurrent-2",
    "prog-concurrent-3",
    "prog-concurrent-4",
)


@dataclass
class ConcurrentRebuildSession:
    """One AC-1 program's `program_id` plus its own dedicated `AsyncSession`.

    Sessions are independent — never shared across entries — so each can be
    mid-transaction at the same wall-clock instant as the others.
    """

    program_id: str
    session: AsyncSession


@pytest_asyncio.fixture
async def four_program_concurrent_sessions(
    test_engine: AsyncEngine,
) -> AsyncIterator[list[ConcurrentRebuildSession]]:
    """C-4/BED-05-FR-4: four distinct programs, each on its own `AsyncSession`
    bound to `test_engine`, for AC-1's real-concurrency case.

    Pair with `migrated_db` for a live schema and `run_concurrent_rebuild_pairs`
    to drive the four sessions' call pairs concurrently. Every session is
    closed on teardown regardless of how the test exits.
    """
    session_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    concurrent_sessions = [
        ConcurrentRebuildSession(program_id=program_id, session=session_factory())
        for program_id in FOUR_CONCURRENT_PROGRAM_IDS
    ]
    try:
        yield concurrent_sessions
    finally:
        for entry in concurrent_sessions:
            await entry.session.close()


async def run_concurrent_rebuild_pairs(
    concurrent_sessions: list[ConcurrentRebuildSession],
) -> list[tuple[RebuildResult, RebuildResult] | BaseException]:
    """Run `rebuild_program_rollups(session, program_id)` ->
    `rebuild_org_rollups(session)` for every entry in `concurrent_sessions`,
    all four launched together via `asyncio.gather(..., return_exceptions=True)`.

    Each program's own two calls stay ordered on its OWN session (the program
    rebuild is awaited before that session starts its org rebuild) — it is
    only the four *sessions'* call pairs that race against each other, which
    is exactly AC-1's scenario: four independent callers hitting the org-scope
    singleton at once (`DECISIONS.md` D-01).

    `return_exceptions=True` is deliberate: AC-1's whole point is to observe
    what happens when four callers hit `org_summary_rollup`'s unique
    constraint concurrently (an `IntegrityError` on the pre-rewrite
    implementation, zero on the rewritten one — `DECISIONS.md` D-01) — a bare
    `asyncio.gather` would cancel the other three in-flight calls the moment
    the first exception surfaced, hiding their outcomes from the caller.
    """

    async def _call_pair(entry: ConcurrentRebuildSession) -> tuple[RebuildResult, RebuildResult]:
        program_result = await rebuild_program_rollups(entry.session, entry.program_id)
        org_result = await rebuild_org_rollups(entry.session)
        return program_result, org_result

    return await asyncio.gather(
        *(_call_pair(entry) for entry in concurrent_sessions),
        return_exceptions=True,
    )


# =============================================================================
# AUTH-01 (T-02, F-11) — Keycloak mock fixtures, RSA/JWT test-builder helpers,
# outbound-call spy, and the D-07 app-factory fixture.
#
# Scheduling note: this task runs concurrently with T-03 (app/core/config.py
# OIDC Settings fields) and T-09 (app/main.py create_app()) — neither exists
# yet at the time this section is written. Everything above the "App-factory
# fixture" heading below is self-contained (RSA keys, JWT signing, respx) and
# collects/imports cleanly today. `build_app`/`async_client_for` defer their
# `app.core.config`/`app.main` imports to inside the fixture's returned
# callable for exactly that reason — see that section's docstring.
# =============================================================================

# Keycloak's documented realm endpoint layout: {issuer}/protocol/openid-connect/
# {auth,token,certs}. This has been Keycloak's stable OIDC endpoint shape since
# its earliest OIDC support (mirrors what its own `.well-known/openid-configuration`
# discovery document publishes) — verified against that documented convention, not
# against a live call to the real issuer host, since these tests must never depend
# on the real Apexon realm being reachable (D-03). `TEST_OIDC_ISSUER` is the actual
# confirmed issuer from ADR-0004 (non-secret); `respx`'s `assert_all_mocked=True`
# (see `keycloak_mock` below) guarantees a test can never silently fall through to
# a real network call against it even if a route is left unmocked.
TEST_OIDC_ISSUER = "https://lab.apexonlab.com/apexonlogin/realms/Apexon"
TEST_AUTHORIZATION_ENDPOINT = f"{TEST_OIDC_ISSUER}/protocol/openid-connect/auth"
TEST_TOKEN_ENDPOINT = f"{TEST_OIDC_ISSUER}/protocol/openid-connect/token"
TEST_JWKS_URI = f"{TEST_OIDC_ISSUER}/protocol/openid-connect/certs"

# Shared default `aud` claim for `build_access_token` and a plausible
# `oidc_client_id` value for tests that want a "fully configured" `Settings`
# via `build_app(oidc_client_id=TEST_OIDC_CLIENT_ID, ...)`.
TEST_OIDC_CLIENT_ID = "dashboard-web"


# -----------------------------------------------------------------------------
# RSA test keypair + JWT builder (authlib.jose, verified at authlib==0.15.6 —
# see this task's `authlib_0156_api_notes` hand-off for the full derivation).
# -----------------------------------------------------------------------------


@dataclass
class RSATestKeypair:
    """An RSA keypair for signing/verifying test JWTs, plus its JWKS document.

    `private_key`/`public_key` are Authlib `Key` instances (dict subclasses).
    `jwks_document` is a plain, JSON-serializable `{"keys": [...]}` dict ready
    to hand to `KeycloakMock.jwks_success`.
    """

    kid: str
    private_key: Key
    public_key: Key
    jwks_document: dict[str, Any]


def _generate_rsa_test_keypair(kid: str) -> RSATestKeypair:
    """Build one `RSATestKeypair`. Not a fixture itself — shared by
    `rsa_test_keypair` and `rsa_test_keypair_alt` so both go through the same,
    once-verified construction path.

    Authlib 0.15.6 gotcha: `JsonWebKey.generate_key(..., options={"kid": ...})`
    silently drops the `kid` — `RSAKey.generate_key`/the module-level
    `import_key` helper it calls never merges `options` into the key's own
    dict when generating from a fresh raw key (only used for a PEM
    passphrase in the PEM-import path). Since `Key` subclasses `dict`, plain
    item assignment (`key["kid"] = ...`) is the supported workaround and is
    what this repo uses everywhere a `kid` is needed.
    """
    private_key = JsonWebKey.generate_key("RSA", 2048, is_private=True)
    private_key["kid"] = kid
    # `JsonWebKey.import_key` on a raw (non-PEM, non-dict) key object requires
    # an explicit `kty` — without it, it assumes PEM bytes and raises.
    public_key = JsonWebKey.import_key(private_key.get_public_key(), options={"kty": "RSA"})
    public_key["kid"] = kid
    return RSATestKeypair(
        kid=kid,
        private_key=private_key,
        public_key=public_key,
        jwks_document={"keys": [public_key.as_dict()]},
    )


@pytest.fixture(scope="session")
def rsa_test_keypair() -> RSATestKeypair:
    """The primary signing keypair. Its public JWK is what `keycloak_mock`'s
    JWKS route is expected to serve for the "known kid" path — pass
    `rsa_test_keypair.jwks_document` to `KeycloakMock.jwks_success`.

    Session-scoped: RSA-2048 generation is pure and expensive enough to
    amortize once across the whole test session (the resulting `Key` objects
    are not mutated by any fixture/test after `kid` assignment above).
    """
    return _generate_rsa_test_keypair("test-signing-key-1")


@pytest.fixture(scope="session")
def rsa_test_keypair_alt() -> RSATestKeypair:
    """A second keypair, deliberately never included in the JWKS document
    `keycloak_mock` serves by default. Use for the negative paths D-04 exists
    to cover:

    - An unrecognized `kid` (`build_access_token(kid=rsa_test_keypair_alt.kid)`)
      — fetch-once-then-401 (TC-28/29).
    - A forged header: sign with this key but claim the *primary* key's
      `kid` (`build_access_token(signing_key=rsa_test_keypair_alt.private_key)`,
      leaving `kid` at its default) — signature verification must fail even
      though the `kid` matches a known key (NFR-security, TC-33).
    """
    return _generate_rsa_test_keypair("test-signing-key-2")


@pytest.fixture
def build_access_token(rsa_test_keypair: RSATestKeypair) -> Callable[..., str]:
    """Callable fixture minting a signed RS256 access token string via
    `authlib.jose.jwt.encode(header, payload, key)` (exact signature verified
    at authlib==0.15.6 — see `authlib_0156_api_notes`).

    Defaults produce a token that verifies cleanly against
    `rsa_test_keypair.jwks_document`. Per-call overrides:

    - `sub`, `email`, `iss`, `aud` — straightforward claim overrides.
      `email=None` omits the `email` claim entirely.
    - `role` — written as `realm_access.roles: [role]` (Keycloak's realm-role
      claim shape). `role=None` omits `realm_access` entirely. For a client
      role or multiple roles, use `extra_claims` (e.g.
      `extra_claims={"realm_access": {"roles": ["a", "b"]}}` or
      `{"resource_access": {...}}`).
    - `groups` — written verbatim as the `groups` claim. `groups=None`
      (default) omits the claim entirely — use this to test a missing-claim
      boundary case; pass `[]` or a real list to set it explicitly
      (program-group parsing, TC-18/19/20).
    - `exp_in_s` — expiry as seconds-from-now (default 300). For an absolute
      `exp` override, use `extra_claims={"exp": ...}`.
    - `kid` — header `kid`; defaults to `rsa_test_keypair.kid`. Pass
      `rsa_test_keypair_alt.kid` (or any unregistered string) for the
      unrecognized-kid paths (D-04, TC-28/29).
    - `signing_key` — an Authlib `Key` to sign with instead of
      `rsa_test_keypair.private_key`; see `rsa_test_keypair_alt`'s docstring
      for the forged-header scenario this enables.
    - `extra_claims` — merged into the payload last (highest precedence),
      so it can add or override any claim not named above.
    """

    def _build(
        *,
        sub: str = "test-user-id",
        email: str | None = "test-user@example.com",
        role: str | None = "member",
        groups: list[str] | None = None,
        exp_in_s: int = 300,
        iss: str = TEST_OIDC_ISSUER,
        aud: str = TEST_OIDC_CLIENT_ID,
        kid: str | None = None,
        signing_key: Key | None = None,
        extra_claims: dict[str, Any] | None = None,
    ) -> str:
        now = int(time.time())
        header = {"alg": "RS256", "kid": kid if kid is not None else rsa_test_keypair.kid}
        payload: dict[str, Any] = {
            "sub": sub,
            "iss": iss,
            "aud": aud,
            "iat": now,
            "exp": now + exp_in_s,
        }
        if email is not None:
            payload["email"] = email
        if role is not None:
            payload["realm_access"] = {"roles": [role]}
        if groups is not None:
            payload["groups"] = groups
        if extra_claims:
            payload.update(extra_claims)
        key = signing_key if signing_key is not None else rsa_test_keypair.private_key
        token_bytes: bytes = jwt.encode(header, payload, key)
        return token_bytes.decode("ascii")

    return _build


# -----------------------------------------------------------------------------
# respx MockRouter fixtures — Keycloak token (code exchange + refresh, same
# endpoint per D-06) and JWKS endpoints. Plus the outbound-call spy (D-06).
# -----------------------------------------------------------------------------


@dataclass
class KeycloakMock:
    """Convenience wrapper over a `respx.MockRouter` pre-wired with named
    routes for Keycloak's token endpoint (`token_route` — serves BOTH the
    authorization_code exchange and the refresh_token grant; Keycloak uses one
    endpoint for both, distinguished only by the `grant_type` form field, so
    one route covers both call sites) and its JWKS endpoint (`jwks_route`).

    Routes start unconfigured (no response set). Call the `.token_*`/
    `.jwks_*` setter matching the scenario under test before making the
    request, then assert on `.token_route.call_count` / `.jwks_route
    .call_count`, or via `keycloak_call_spy`.
    """

    router: respx.MockRouter
    token_route: respx.Route
    jwks_route: respx.Route

    def token_success(
        self,
        *,
        access_token: str = "test-access-token",
        refresh_token: str = "test-refresh-token",
        expires_in: int = 300,
        token_type: str = "Bearer",
    ) -> None:
        """200 `{access_token, refresh_token, expires_in, token_type}` —
        shape shared by code exchange and refresh grant."""
        self.token_route.mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_in": expires_in,
                    "token_type": token_type,
                },
            )
        )

    def token_error(
        self,
        *,
        status_code: int = 400,
        error: str = "invalid_grant",
        error_description: str = "Invalid refresh token",
    ) -> None:
        """A 4xx/401 IdP error response — must never trigger a retry (TC-31)."""
        self.token_route.mock(
            return_value=httpx.Response(
                status_code, json={"error": error, "error_description": error_description}
            )
        )

    def token_transient_then_success(
        self,
        *,
        failures: int = 2,
        access_token: str = "test-access-token",
        refresh_token: str = "test-refresh-token",
        expires_in: int = 300,
    ) -> None:
        """`failures` transient connection errors, then a 200. Default
        `failures=2` matches TC-30: fails on attempts 1-2, succeeds on the
        3rd (the bounded-retry policy's exact `max_attempts=3`)."""
        success = httpx.Response(
            200,
            json={
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_in": expires_in,
                "token_type": "Bearer",
            },
        )
        side_effect: list[httpx.Response | Exception] = [
            httpx.ConnectError("connection refused") for _ in range(failures)
        ]
        side_effect.append(success)
        self.token_route.mock(side_effect=side_effect)

    def token_always_transient_error(self) -> None:
        """Every attempt raises a transient connection error — for
        retry-exhaustion tests (all `max_attempts` fail)."""
        self.token_route.mock(side_effect=httpx.ConnectError("connection refused"))

    def jwks_success(self, jwks_document: dict[str, Any]) -> None:
        """200 JWKS document — typically `rsa_test_keypair.jwks_document`."""
        self.jwks_route.mock(return_value=httpx.Response(200, json=jwks_document))

    def jwks_error(self, status_code: int = 500) -> None:
        """A transient/5xx JWKS-fetch failure."""
        self.jwks_route.mock(
            return_value=httpx.Response(status_code, json={"error": "jwks_unavailable"})
        )


@pytest.fixture
def keycloak_mock() -> Iterator[KeycloakMock]:
    """respx MockRouter mocking Keycloak's token and JWKS endpoints.

    `assert_all_mocked=True`: any outbound call this router doesn't recognize
    (wrong URL, or a real network call slipping through) raises immediately
    instead of silently hitting the network — this is itself part of what
    makes `keycloak_call_spy.assert_zero_calls()` trustworthy for the
    dev-bypass test (TC-08): if dev-bypass code path ever regressed to call
    Keycloak, the call would raise here rather than pass mocked-but-uncounted.
    `assert_all_called=False`: most tests only exercise one of the two routes.
    """
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        token_route = router.post(TEST_TOKEN_ENDPOINT, name="token")
        jwks_route = router.get(TEST_JWKS_URI, name="jwks")
        yield KeycloakMock(router=router, token_route=token_route, jwks_route=jwks_route)


@dataclass
class KeycloakCallSpy:
    """Thin, obviously-named wrapper over respx's own call tracking
    (`Route.call_count` / `MockRouter.calls`) — exists so every test file
    reads outbound-call counts the same way rather than re-deriving which
    respx attribute to use.

    - `assert_zero_calls()` — AUTH-01-FR-7 / TC-08: dev-bypass must make zero
      outbound Keycloak calls.
    - `assert_call_count(route, n)` — D-04 / TC-29: an unrecognized `kid`
      triggers exactly one fresh JWKS fetch, not a retry loop.
    """

    router: respx.MockRouter

    @property
    def total_calls(self) -> int:
        return len(self.router.calls)

    def assert_zero_calls(self) -> None:
        assert self.total_calls == 0, (
            f"expected zero outbound Keycloak calls, got {self.total_calls}: "
            f"{[str(call.request.url) for call in self.router.calls]}"
        )

    def assert_call_count(self, route: respx.Route, expected: int) -> None:
        assert route.call_count == expected, (
            f"expected {expected} call(s) to route {route.name!r}, got {route.call_count}"
        )


@pytest.fixture
def keycloak_call_spy(keycloak_mock: KeycloakMock) -> KeycloakCallSpy:
    """Spy over `keycloak_mock`'s router — see `KeycloakCallSpy`. Depends on
    `keycloak_mock` so requesting this fixture is enough to also have the
    outbound Keycloak calls mocked/intercepted (never real network)."""
    return KeycloakCallSpy(router=keycloak_mock.router)


# -----------------------------------------------------------------------------
# App-factory fixture (D-07). NOT LIVE YET — see module-level scheduling note
# at the top of this section. `create_app` (T-09, app/main.py) and the OIDC
# `Settings` fields (T-03, app/core/config.py) do not exist at the time this
# task (T-02) runs; both imports are deferred to inside `_build`'s body so
# this module keeps collecting cleanly under pytest right now. Calling
# `build_app(...)` before T-03/T-09 land raises `ImportError` at call time
# (verified by this task's own throwaway scratch-test run, which exercises
# only the fixtures above this heading — see this task's hand-off payload).
# -----------------------------------------------------------------------------

# Every field D-07 pins on `Settings` for OIDC/CORS/environment gets an
# explicit hermetic default here. pydantic-settings' documented field-value
# precedence is: constructor kwargs > environment variables > `.env` file >
# field defaults — so passing every one of these fields explicitly guarantees
# a test's `Settings` never silently inherits a real `OIDC_CLIENT_ID`,
# `ENVIRONMENT`, `CORS_ORIGINS`, etc. from the developer's shell or a stray
# `.env` file in `services/api/` (`Settings.model_config` reads both). A
# per-call `**overrides` value still wins over this dict (see `build_app`).
_HERMETIC_SETTINGS_DEFAULTS: dict[str, Any] = {
    "app_name": "dashboard-api-test",
    "environment": "test",
    "log_level": "INFO",
    "oidc_client_id": None,
    "oidc_client_secret": None,
    "oidc_issuer": None,
    "oidc_realm": None,
    # Omitted from this dict until 2026-09-08, which broke the moment a real
    # `OIDC_REDIRECT_URI` was set in `services/api/.env` (AUTH-05's deployment
    # step): `test_login_redirects_to_keycloak_with_valid_authorization_request`
    # asserts the DERIVED fallback (`http://test/auth/callback`) and had only
    # ever passed because the var happened to be unset everywhere. Pinning it
    # to None here is what the comment above already promises — the derived
    # branch is now exercised deterministically, and the two tests that assert
    # a configured value still override it per-call.
    "oidc_redirect_uri": None,
    # Derived, never a literal (review F-1/F-12). This pin is a *constructor
    # kwarg* — highest precedence, above env and the field default — so a stale
    # literal here silently shadows the shipped default for every `build_app()`
    # test in the suite, which is exactly what AUTH-06 hit when it dropped
    # `groups` from the scope. Reading the default keeps hermeticity identical
    # (a real `.env` value still cannot leak in, per the `oidc_redirect_uri`
    # incident above) while making that class of drift impossible rather than
    # merely corrected. `program_group_prefix` was pinned here too and is now
    # deleted from `Settings`; `extra="ignore"` swallowed it, so it never erred
    # — it just read as live config forever. Removed rather than left dead.
    "oidc_scope": Settings.model_fields["oidc_scope"].default,
    "cors_origins": [],
    # AUTH-07 (T-01) added both fields; pinned here for the same reason the
    # `oidc_redirect_uri` incident above documents. `frontend_login_url` is the
    # fourth value `GET /auth/logout`'s completeness gate requires, so leaving
    # it unpinned makes every "unset -> 501" assertion pass or fail on whether
    # the developer happens to have `FRONTEND_LOGIN_URL` in their shell or
    # `services/api/.env` — the identical failure mode, on an identical
    # config-gate shape. `persona_precedence_order` is Tier-1 of the persona
    # precedence order, so pinning it to None keeps the all-tiers-unset
    # hardcoded-default branch (`_DEFAULT_PERSONA_PRECEDENCE`) the deterministic
    # one under test. Both stay None; the tests that need a configured value
    # override per-call, exactly as the two `oidc_redirect_uri` tests do.
    "frontend_login_url": None,
    "persona_precedence_order": None,
    # ING-07 (T-06): same AUTH-05-style hermetic pin discipline documented
    # above. `Settings.github_org` / `github_token` are optional-at-import
    # (`None` = unset -> 500 at request time per FR-5); pinning them to None
    # as constructor kwargs keeps a stray `GITHUB_ORG` / `GITHUB_TOKEN` in
    # the developer's shell or `services/api/.env` from silently unlocking
    # the "GitHub configured" branch of every `build_app()` test that did
    # not explicitly override. Tests that need a configured value override
    # per-call via `build_app(github_org=..., github_token=...)`, exactly as
    # the `oidc_redirect_uri` and `frontend_login_url` cases above do; see
    # the ING-07 `settings_github_configured` fixture family below.
    "github_org": None,
    "github_token": None,
}


@pytest.fixture
def build_app() -> Callable[..., FastAPI]:
    """Factory fixture: `build_app(**overrides) -> FastAPI`, per D-07.

    Constructs `Settings(**{**_HERMETIC_SETTINGS_DEFAULTS, **overrides})` and
    returns `create_app(settings_override=that_settings)`. Never mutates the
    module-level `app.core.config.settings` singleton, never
    `importlib.reload`s anything — D-07 rules both out explicitly. Each call
    gets its own `Settings`/`FastAPI` instance, so concurrent tests booting
    the app under different configs (e.g. different `ENVIRONMENT` values for
    TC-09/22/23/37/38/39) don't interfere with each other.
    """

    def _build(**overrides: Any) -> FastAPI:
        from app.core.config import Settings

        # Imported inside the closure, not at module scope: `app.main` imports
        # the whole router graph, and a conftest-time import would drag it into
        # every test session including the DB-only ones (D-07).
        from app.main import create_app

        settings_kwargs = {**_HERMETIC_SETTINGS_DEFAULTS, **overrides}
        return create_app(settings_override=Settings(**settings_kwargs))

    return _build


def issue_oauth_state(app: FastAPI) -> str:
    """Mint a valid, single-use OAuth `state` for `app`'s own state store.

    `GET /auth/callback` verifies `state` against the per-app
    `OAuthStateStore` (app/auth/state_store.py), so any test exercising the
    callback must present a state that store actually issued. Reaching into
    `app.state.oauth_state_store` mints one directly, which keeps a callback
    test focused on the callback instead of first driving `/auth/login`
    through a second request whose redirect it would only be parsing for the
    state anyway.

    Returns only the `state`; the companion PKCE `code_verifier` stays in the
    store, which is exactly what the callback needs to find there.

    Single-use: call once per callback request. A test asserting the
    replay/expiry rejections should NOT use this helper -- it should reuse or
    fabricate a value on purpose.
    """
    store: Any = app.state.oauth_state_store
    return str(store.issue().state)


@pytest.fixture
def async_client_for() -> Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]]:
    """`async_client_for(app) -> AsyncClient` async context manager, over
    `httpx.ASGITransport` — matches this repo's existing in-process app
    testing convention (`tests/unit/test_range_validation.py`). Usage::

        app = build_app(environment="test")
        async with async_client_for(app) as client:
            resp = await client.get("/auth/login")
    """

    @asynccontextmanager
    async def _client_for(
        app: FastAPI, *, base_url: str = "http://test"
    ) -> AsyncIterator[httpx.AsyncClient]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
            yield client

    return _client_for


# =============================================================================
# ING-07 (T-06, F-12) — Admin repo-scan endpoint test fixtures.
#
# Names and shapes mirror `docs/test-cases/ING-07.json`'s `fixtures[]` arrays
# verbatim (audited before authoring): every fixture referenced by a TC exists
# here, and every fixture here is referenced by at least one TC (excluding
# `caplog`, which is a built-in pytest fixture). Consumed by T-07's
# `tests/unit/test_admin_repo_scan.py` and T-08's
# `tests/perf/test_admin_repo_scan_perf.py`.
#
# Log-capture note (naming vs. implementation): `structlog_capture` below
# hooks the STDLIB `logging` module, not structlog. `app/services/repo_scan.py`
# (T-03) emits via `logging.getLogger(__name__).info/.warning` with `extra={}`;
# there is no structlog anywhere under `services/api/**`. The JSON test-case
# names were chosen at plan-authoring time for consistency with earlier
# stories' fixture vocabulary; the T-06 dispatch directive requires matching
# them exactly and flagging the mismatch (see AF flag emitted by this task).
#
# `pytest-patterns/SKILL.md` is a scaffold placeholder ("fill body with team
# conventions"); the idioms here follow pytest v8 + respx v0.21+ documented
# patterns plus the existing keycloak_mock/build_access_token precedent above.
# =============================================================================


_ADMIN_SCAN_ORG_ID: str = "org-1"
_ADMIN_SCAN_TEST_ORG: str = "acme"
_ADMIN_SCAN_TEST_PAT: str = "ghp_TEST_GITHUB_TOKEN_DO_NOT_LOG"  # noqa: S105 - synthetic test fixture value
_ADMIN_SCAN_SENTINEL_PAT: str = "ghp_SENTINEL_DO_NOT_LOG_ABC123"  # noqa: S105 - TC-17 sentinel
_ADMIN_SCAN_GITHUB_LIST_URL: str = (
    f"https://api.github.com/orgs/{_ADMIN_SCAN_TEST_ORG}/repos"
)
_ADMIN_SCAN_GITHUB_LIST_PAGE1: str = f"{_ADMIN_SCAN_GITHUB_LIST_URL}?per_page=100&page=1"
_ADMIN_SCAN_GITHUB_LIST_PAGE2: str = f"{_ADMIN_SCAN_GITHUB_LIST_URL}?per_page=100&page=2"


def _github_probe_url(repo: str, default_branch: str = "main") -> str:
    """Match the URL shape `app.services.repo_scan._probe_program_yaml` builds."""
    return (
        f"https://api.github.com/repos/{_ADMIN_SCAN_TEST_ORG}/{repo}"
        f"/contents/.harness/program.yaml?ref={default_branch}"
    )


def _list_repos_body(names: tuple[str, ...], default_branch: str = "main") -> list[dict[str, str]]:
    """Just the two fields `_list_org_repos` reads; the rest of GitHub's payload
    is deliberately absent so a regression that starts reading additional
    fields will fail here rather than pass mocked-but-wrong."""
    return [{"name": name, "default_branch": default_branch} for name in names]


# -----------------------------------------------------------------------------
# (a) Ingest-token fixtures — seed one `ingest_tokens` row per fixture, return
# the raw bearer + the row. Mirrors the local `_seed_token` helper in
# `tests/unit/test_ingest_token_auth.py` (that file keeps its own copy per
# this repo's per-file-ownership precedent; this fixture family is shared
# because ING-07 needs the same seed shape across T-07's whole test file).
# `hrn_pat_` prefix + `secrets.token_hex(32)` matches ADR-0006 SS1.
# -----------------------------------------------------------------------------


@dataclass
class SeededIngestToken:
    """Raw bearer string + the persisted `IngestToken` row it hashes to.

    `bearer` is what tests put on the `Authorization: Bearer …` header;
    `row` is the ORM instance already committed to `test_session`.
    """

    bearer: str
    row: IngestToken


async def _seed_ingest_token(
    session: AsyncSession, *, label: str, allowed_program_ids: list[str]
) -> SeededIngestToken:
    raw_bearer = "hrn_pat_" + secrets.token_hex(32)
    row = IngestToken(
        token_hash=hashlib.sha256(raw_bearer.encode()).hexdigest(),
        label=label,
        user_email="ing-07-fixture@example.com",
        allowed_program_ids=allowed_program_ids,
    )
    session.add(row)
    await session.commit()
    return SeededIngestToken(bearer=raw_bearer, row=row)


@pytest_asyncio.fixture
async def ingest_token_wildcard(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> SeededIngestToken:
    """`allowed_program_ids=['*']` — the wildcard-strict path FR-2 requires."""
    return await _seed_ingest_token(
        test_session, label="ing-07-wildcard", allowed_program_ids=["*"]
    )


@pytest_asyncio.fixture
async def ingest_token_program_scoped(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> SeededIngestToken:
    """`allowed_program_ids=['dashboard']` — program-scoped, TC-06 asserts 403."""
    return await _seed_ingest_token(
        test_session, label="ing-07-program-scoped", allowed_program_ids=["dashboard"]
    )


@pytest_asyncio.fixture
async def ingest_token_allow_all_empty(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> SeededIngestToken:
    """`allowed_program_ids=[]` — ADR-0006 allow-all-empty; TC-13 asserts the
    router's wildcard-strict re-check rejects it with 403 even though
    `get_ingest_token()`'s shared scope check passes."""
    return await _seed_ingest_token(
        test_session, label="ing-07-allow-all-empty", allowed_program_ids=[]
    )


# -----------------------------------------------------------------------------
# (b) `org_summary_rollup` seed fixtures. Non-owned NOT-NULL columns are set
# to 0 (matches `repo_scan._upsert_org_rollup`'s own INSERT bootstrap and
# BED-03's `_build_org_summary`). Owned columns take the fixture's values.
# -----------------------------------------------------------------------------


async def _seed_org_summary_rollup(
    session: AsyncSession,
    *,
    repos_total: int,
    repos_with_harness_installed: int,
    as_of_timestamp: datetime,
) -> OrgSummaryRollup:
    row = OrgSummaryRollup(
        org_id=_ADMIN_SCAN_ORG_ID,
        programs_using_ai_count=0,
        programs_total=0,
        total_token_consumption=0,
        lines_of_code_generated=0,
        releases_using_harness=0,
        repos_with_harness_installed=repos_with_harness_installed,
        repos_total=repos_total,
        as_of_timestamp=as_of_timestamp,
        created_at=as_of_timestamp,
        updated_at=as_of_timestamp,
    )
    session.add(row)
    await session.commit()
    return row


@pytest_asyncio.fixture
async def org_summary_rollup_seed(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> OrgSummaryRollup:
    """Sentinel-valued row (99 / 1 / 2000-01-01T00Z). Any TC that ends with
    "rollup unchanged" asserts against these values bytes-identically."""
    return await _seed_org_summary_rollup(
        test_session,
        repos_total=99,
        repos_with_harness_installed=1,
        as_of_timestamp=datetime(2000, 1, 1, 0, 0, 0, tzinfo=UTC),
    )


@pytest_asyncio.fixture
async def org_summary_rollup_prior_values(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> OrgSummaryRollup:
    """Realistic prior values (42 / 17 / 2026-08-01T00Z) — TC-11 / TC-15 /
    TC-20 assert every mutable column individually against these to catch a
    partial commit that happens to preserve some columns but not others."""
    return await _seed_org_summary_rollup(
        test_session,
        repos_total=42,
        repos_with_harness_installed=17,
        as_of_timestamp=datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC),
    )


# -----------------------------------------------------------------------------
# (c) Settings-override kwarg dicts. Tests spread these into `build_app(...)`
# so `Settings.github_org` / `github_token` land as constructor kwargs — the
# highest-precedence tier, above the hermetic `None` pins in
# `_HERMETIC_SETTINGS_DEFAULTS`. See that dict's ING-07 comment above.
# -----------------------------------------------------------------------------


@pytest.fixture
def settings_github_configured() -> dict[str, Any]:
    """Fully-configured GitHub settings — happy-path TCs."""
    return {"github_org": _ADMIN_SCAN_TEST_ORG, "github_token": _ADMIN_SCAN_TEST_PAT}


@pytest.fixture
def settings_missing_github_token() -> dict[str, Any]:
    """Empty PAT — FR-5 500 branch (TC-07)."""
    return {"github_org": _ADMIN_SCAN_TEST_ORG, "github_token": ""}


@pytest.fixture
def settings_missing_github_org() -> dict[str, Any]:
    """Empty org — FR-5 500 branch (TC-08)."""
    return {"github_org": "", "github_token": _ADMIN_SCAN_TEST_PAT}


@pytest.fixture
def settings_github_configured_sentinel_pat() -> dict[str, Any]:
    """PAT is the TC-17 sentinel — the assertion is that this exact string
    never appears in captured logs, response body, or exception messages."""
    return {"github_org": _ADMIN_SCAN_TEST_ORG, "github_token": _ADMIN_SCAN_SENTINEL_PAT}


# -----------------------------------------------------------------------------
# (d) respx GitHub route factories. `respx_mock` is the router; each named
# factory below is a callable fixture that mounts its route(s) on that
# router and returns the mounted `respx.Route` for `.call_count` assertions.
#
# `assert_all_mocked=True`: any outbound call whose URL doesn't match a
# mounted route raises immediately — the "no GitHub call was made" assertion
# in TC-04/05/06/07/08/13 relies on this trap firing rather than silently
# passing a fall-through to the real network.
# `assert_all_called=False`: TC-15 deliberately mounts a probe route that
# may or may not be hit depending on iteration order.
# -----------------------------------------------------------------------------


@pytest.fixture
def respx_mock() -> Iterator[respx.MockRouter]:
    """Standalone respx MockRouter — GitHub-only. Do NOT combine with
    `keycloak_mock` in the same test; that fixture opens its own router."""
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        yield router


def _mount_list_repos_json(
    router: respx.MockRouter,
    *,
    names: tuple[str, ...],
    name: str,
) -> respx.Route:
    """Mount `GET /orgs/{org}/repos?per_page=100&page=1` → 200 with the given repos."""
    return router.get(_ADMIN_SCAN_GITHUB_LIST_PAGE1, name=name).mock(
        return_value=httpx.Response(200, json=_list_repos_body(names))
    )


@pytest.fixture
def github_list_repos_200_mixed(
    respx_mock: respx.MockRouter,
) -> Callable[..., respx.Route]:
    """Mount the list-repos route with a customizable repo tuple; default is
    the 3-repo mixed set the classification TCs use (TC-01 / TC-12 / TC-15 /
    TC-18 / TC-19 / TC-20)."""

    def _mount(names: tuple[str, ...] = ("repo-a", "repo-b", "repo-c")) -> respx.Route:
        return _mount_list_repos_json(respx_mock, names=names, name="list_repos_mixed")

    return _mount


@pytest.fixture
def github_list_repos_200_all_installed(
    respx_mock: respx.MockRouter,
) -> Callable[..., respx.Route]:
    """TC-02: every repo will be probed to 200 — same list shape as `_mixed`,
    named separately so the TC's fixtures[] traces to a distinct helper."""

    def _mount(names: tuple[str, ...] = ("repo-a", "repo-b", "repo-c")) -> respx.Route:
        return _mount_list_repos_json(respx_mock, names=names, name="list_repos_all_installed")

    return _mount


@pytest.fixture
def github_list_repos_200_none_installed(
    respx_mock: respx.MockRouter,
) -> Callable[..., respx.Route]:
    """TC-03: every repo will be probed to 404 — same list shape."""

    def _mount(names: tuple[str, ...] = ("repo-a", "repo-b", "repo-c")) -> respx.Route:
        return _mount_list_repos_json(respx_mock, names=names, name="list_repos_none_installed")

    return _mount


@pytest.fixture
def github_list_repos_500(respx_mock: respx.MockRouter) -> Callable[[], respx.Route]:
    """TC-09 / TC-11 / TC-15: list-repos returns 503 on every attempt — the
    retry wrapper exhausts (`max_attempts=4`, one initial + three retries)
    and `_get_with_retry` raises `GitHubScanError('upstream_5xx')`."""

    def _mount() -> respx.Route:
        return respx_mock.get(_ADMIN_SCAN_GITHUB_LIST_PAGE1, name="list_repos_500").mock(
            return_value=httpx.Response(503, json={"message": "service unavailable"})
        )

    return _mount


@pytest.fixture
def github_list_repos_timeout(respx_mock: respx.MockRouter) -> Callable[[], respx.Route]:
    """TC-10: every attempt raises `httpx.ReadTimeout` — deterministic, no real
    sleep. Pair with `no_sleep` if you want the whole test wall-clock under 1 s."""

    def _mount() -> respx.Route:
        return respx_mock.get(_ADMIN_SCAN_GITHUB_LIST_PAGE1, name="list_repos_timeout").mock(
            side_effect=httpx.ReadTimeout("timed out")
        )

    return _mount


@pytest.fixture
def github_list_repos_429_then_200(
    respx_mock: respx.MockRouter,
) -> Callable[..., respx.Route]:
    """TC-14: attempt 1 → 429 (retryable), attempt 2 → 200 with the given
    repos. Pair with `no_sleep` so the backoff between the two attempts is
    a coroutine no-op."""

    def _mount(names: tuple[str, ...] = ("repo-a",)) -> respx.Route:
        return respx_mock.get(
            _ADMIN_SCAN_GITHUB_LIST_PAGE1, name="list_repos_429_then_200"
        ).mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "1"}, json={"message": "slow down"}),
                httpx.Response(200, json=_list_repos_body(names)),
            ]
        )

    return _mount


@pytest.fixture
def github_list_repos_paginated_2pages(
    respx_mock: respx.MockRouter,
) -> Callable[..., tuple[respx.Route, respx.Route]]:
    """TC-16 perf: 200 repos across 2 pages of 100 each. Page 1 carries a
    `Link: <page-2-url>; rel="next"` header that `_next_page_url` follows
    (`app/services/repo_scan.py::_next_page_url`); page 2 carries no `Link`
    so pagination terminates."""

    def _mount(
        page1: tuple[str, ...] | None = None,
        page2: tuple[str, ...] | None = None,
    ) -> tuple[respx.Route, respx.Route]:
        p1 = page1 if page1 is not None else tuple(f"repo-p1-{i:03d}" for i in range(100))
        p2 = page2 if page2 is not None else tuple(f"repo-p2-{i:03d}" for i in range(100))
        route1 = respx_mock.get(
            _ADMIN_SCAN_GITHUB_LIST_PAGE1, name="list_repos_paginated_page1"
        ).mock(
            return_value=httpx.Response(
                200,
                json=_list_repos_body(p1),
                headers={"Link": f'<{_ADMIN_SCAN_GITHUB_LIST_PAGE2}>; rel="next"'},
            )
        )
        route2 = respx_mock.get(
            _ADMIN_SCAN_GITHUB_LIST_PAGE2, name="list_repos_paginated_page2"
        ).mock(return_value=httpx.Response(200, json=_list_repos_body(p2)))
        return route1, route2

    return _mount


@pytest.fixture
def github_list_repos_500_secret_bearing_body(
    respx_mock: respx.MockRouter,
) -> Callable[[], respx.Route]:
    """TC-17: 503 with a body containing the sentinel PAT — proves
    `_get_with_retry` does not surface response bodies via `str(exc)` or
    logs. Pair with `settings_github_configured_sentinel_pat`."""

    def _mount() -> respx.Route:
        return respx_mock.get(
            _ADMIN_SCAN_GITHUB_LIST_PAGE1, name="list_repos_500_secret_bearing"
        ).mock(
            return_value=httpx.Response(
                503,
                text=f"upstream error mentioning {_ADMIN_SCAN_SENTINEL_PAT}",
            )
        )

    return _mount


@pytest.fixture
def github_contents_program_yaml_200(
    respx_mock: respx.MockRouter,
) -> Callable[..., respx.Route]:
    """Probe → 200 for one repo. Call once per repo whose probe should be
    installed. TC-01 / TC-02 / TC-14 / TC-18."""

    def _mount(repo: str, *, default_branch: str = "main") -> respx.Route:
        return respx_mock.get(
            _github_probe_url(repo, default_branch), name=f"probe_200_{repo}"
        ).mock(return_value=httpx.Response(200, json={}))

    return _mount


@pytest.fixture
def github_contents_program_yaml_404(
    respx_mock: respx.MockRouter,
) -> Callable[..., respx.Route]:
    """Probe → 404 for one repo (not installed). TC-01 / TC-03 / TC-18."""

    def _mount(repo: str, *, default_branch: str = "main") -> respx.Route:
        return respx_mock.get(
            _github_probe_url(repo, default_branch), name=f"probe_404_{repo}"
        ).mock(return_value=httpx.Response(404, json={"message": "Not Found"}))

    return _mount


@pytest.fixture
def github_contents_program_yaml_500(
    respx_mock: respx.MockRouter,
) -> Callable[..., respx.Route]:
    """Probe → 503 on every attempt for one repo (retry exhaustion). TC-15."""

    def _mount(repo: str, *, default_branch: str = "main") -> respx.Route:
        return respx_mock.get(
            _github_probe_url(repo, default_branch), name=f"probe_500_{repo}"
        ).mock(return_value=httpx.Response(503, json={"message": "service unavailable"}))

    return _mount


@pytest.fixture
def github_contents_program_yaml_mixed(
    github_contents_program_yaml_200: Callable[..., respx.Route],
    github_contents_program_yaml_404: Callable[..., respx.Route],
) -> Callable[..., dict[str, respx.Route]]:
    """Mount 200 for `installed` repos and 404 for `not_installed` repos in
    one call. Returns `{repo: route}` so a test can look up counts per repo.
    TC-12 / TC-18 / TC-19 / TC-20."""

    def _mount(
        installed: tuple[str, ...] = ("repo-a",),
        not_installed: tuple[str, ...] = ("repo-b",),
        *,
        default_branch: str = "main",
    ) -> dict[str, respx.Route]:
        routes: dict[str, respx.Route] = {}
        for repo in installed:
            routes[repo] = github_contents_program_yaml_200(repo, default_branch=default_branch)
        for repo in not_installed:
            routes[repo] = github_contents_program_yaml_404(repo, default_branch=default_branch)
        return routes

    return _mount


@pytest.fixture
def github_contents_program_yaml_200_latency(
    respx_mock: respx.MockRouter,
) -> Callable[..., respx.Route]:
    """TC-16 perf: probe → 200 after `latency_s` of `asyncio.sleep`. Deterministic
    per-call latency so the p95 measurement is reproducible in CI. Default
    20 ms matches the PLAN test-data figure. Registers ONE catch-all route
    matching every probe URL for this org via a URL regex."""

    def _mount(
        latency_s: float = 0.02, *, default_branch: str = "main"
    ) -> respx.Route:
        async def _delayed(request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(latency_s)
            return httpx.Response(200, json={})

        pattern = re.compile(
            r"^https://api\.github\.com/repos/"
            + re.escape(_ADMIN_SCAN_TEST_ORG)
            + r"/[^/]+/contents/\.harness/program\.yaml\?ref="
            + re.escape(default_branch)
            + r"$"
        )
        return respx_mock.get(url__regex=pattern, name="probe_200_latency").mock(
            side_effect=_delayed
        )

    return _mount


# -----------------------------------------------------------------------------
# (e) Infrastructure fixtures.
# -----------------------------------------------------------------------------


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch `app.core.retry`'s view of `asyncio.sleep` to a coroutine no-op
    so backoff-retry TCs (TC-14) do not spend real wall-clock on the
    exponential+jitter delay. Scoped to `app.core.retry`'s module-level
    `asyncio` name: the global `asyncio.sleep` is untouched, and other
    async code (respx, httpx, the test's own event loop) still sleeps as
    normal.
    """
    import types

    import app.core.retry as _retry_module

    async def _noop_sleep(*_args: Any, **_kwargs: Any) -> None:
        return None

    shim = types.SimpleNamespace(sleep=_noop_sleep)
    monkeypatch.setattr(_retry_module, "asyncio", shim)


class _RepoScanLogHandler(logging.Handler):
    """Stores emitted `LogRecord`s verbatim so tests can inspect
    `record.msg` (the event name) and `record.__dict__` (the `extra={}`
    fields `app.services.repo_scan` attaches — `repos_total`,
    `github_api_calls`, `error_kind`, etc.)."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def structlog_capture() -> Iterator[list[logging.LogRecord]]:
    """Capture every `LogRecord` emitted by `app.services.repo_scan` for the
    test's duration.

    Naming caveat: the fixture is called `structlog_capture` to match the
    verbatim reference in `docs/test-cases/ING-07.json`, but the codebase
    uses stdlib `logging` (no structlog anywhere in `services/api/**`).
    Records are plain `logging.LogRecord` — inspect `.msg` for the event
    name and `.__dict__` for the `extra={...}` fields the service attaches.

    Resets `.disabled = False` because `migrations/env.py`'s
    `fileConfig(disable_existing_loggers=True)` permanently disables every
    already-existing logger the first time `tests/test_migrations.py` runs
    in the same pytest session — the ambient `caplog` handler and any root-
    attached listener are blind to a disabled logger regardless of test
    order. Same trap `_isolated_ingest_auth_logger` in
    `tests/unit/test_ingest_token_auth.py` documents.

    `propagate` is preserved (not forced to False) so `caplog` — which
    attaches at the root — can also observe the same records; TC-17 asserts
    against BOTH `structlog_capture` and `caplog`.
    """
    scan_logger = logging.getLogger("app.services.repo_scan")
    original_disabled = scan_logger.disabled
    original_level = scan_logger.level
    scan_logger.disabled = False
    scan_logger.setLevel(logging.DEBUG)
    handler = _RepoScanLogHandler()
    scan_logger.addHandler(handler)
    try:
        yield handler.records
    finally:
        scan_logger.removeHandler(handler)
        scan_logger.disabled = original_disabled
        scan_logger.setLevel(original_level)


@pytest.fixture
def openapi_schema() -> Callable[[httpx.AsyncClient], Awaitable[dict[str, Any]]]:
    """`await openapi_schema(client)` → parsed `/openapi.json` dict. TC-12
    uses this to look up the `ScanReposResponse` component and assert its
    property set matches the runtime response body."""

    async def _fetch(client: httpx.AsyncClient) -> dict[str, Any]:
        response = await client.get("/openapi.json")
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]

    return _fetch


@pytest.fixture
def background_rebuild_task(
    test_engine: AsyncEngine,
) -> Callable[[], "asyncio.Task[RebuildResult]"]:
    """Schedule BED-03's `rebuild_org_rollups(...)` as an `asyncio.Task` on
    its OWN independently-connected `AsyncSession` bound to `test_engine`
    (mirroring `four_program_concurrent_sessions` above) — TC-20 uses this
    to race the rebuild against the scan endpoint on the same
    `org_summary_rollup` row.

    A single `AsyncSession` cannot be `commit()`ed by two coroutines at once
    (SQLAlchemy `IllegalStateChangeError`), so the rebuild task must NOT
    share the endpoint's session. Both writers still hit the same Postgres
    database, so the caller's post-scan read on its own session observes
    whichever writer committed last (D-02's accepted last-write-wins race).

    The task owns its session's lifecycle (the `async with` closes it on
    completion or exception). The caller MUST `await` the returned task
    after the endpoint POST completes so any exception surfaces at the
    test boundary rather than being swallowed by the task's
    `Task exception was never retrieved` warning.
    """

    session_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    async def _rebuild_on_own_session() -> RebuildResult:
        async with session_factory() as session:
            return await rebuild_org_rollups(session)

    def _launch() -> "asyncio.Task[RebuildResult]":
        return asyncio.create_task(_rebuild_on_own_session())

    return _launch
