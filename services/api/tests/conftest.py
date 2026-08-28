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

import os
import time
from collections.abc import AsyncIterator, Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
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

from app.core.config import settings

API_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = API_ROOT / "alembic.ini"


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
    test_path = f"{parts.path}_test"
    return urlunsplit((parts.scheme, parts.netloc, test_path, parts.query, parts.fragment))


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Disposable test-DB URL — never the dev DB. See module docstring."""
    return _derive_test_database_url()


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
    "oidc_scope": "openid profile email groups",
    "program_group_prefix": "program-",
    "cors_origins": [],
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
