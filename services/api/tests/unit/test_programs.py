"""Unit/security/contract tests for `GET /api/programs` (`app/api/programs.py`)
-- AUTH-04-TC-01..18 (`docs/test-cases/AUTH-04.json`).

Bundles every layer (unit, security/PII-audit, contract, performance-adjacent
boundary) into one topic file, matching `test_rbac.py`'s precedent (AUTH-03).
Perf (TC-17) belongs to `tests/perf/test_programs_perf.py`, not here.

T-06 owns this file's scaffold and covers TC-01, TC-02, TC-05 (AC-1/AC-2/
AC-4). T-07 adds TC-03/04/09/18 (401 fail-fast, no per-program 403,
client-filter ignored). T-08 adds TC-06/07/08/11 (contract: exact key set,
href, dotStyle, FR-2 call-count). T-09 adds TC-10 (programs_list_returned
payload allowlist). T-10 adds TC-12/13/14 (fail-closed persona-resolution
errors). T-11 adds TC-15/16 (defensive missing-program filtering +
discrepancy WARN). Every later task reuses the scaffold below unchanged.

Scaffold pieces (for T-07..T-11 to reuse, not duplicate):

- `_StubPersonaResolver` -- configurable persona resolver test double
  (`mapping` / `raises`), call-recording via `.calls`. Mirrors
  `test_rbac.py::_StubPersonaResolver`'s shape; redefined locally per that
  file's own precedent of each topic file owning its scaffold rather than
  sharing test doubles via `conftest.py` (outside this task's file plan --
  see this task's queued question about promoting it later if duplication
  across topic files becomes a problem).
- `_program_summary_row` / `_seed_programs` -- seed `program_summary` rows
  via `migrated_db`/`test_session` (`tests/conftest.py`), matching
  `test_rollup_rebuild_program.py::_insert_events`'s seed-then-commit
  pattern against the same disposable test database.
- `_db_override` / `_build_programs_app` -- wires a real `create_app()`
  instance (`build_app` fixture, D-07) for HTTP-level testing against a live
  DB: `app.state.persona_resolver` is swapped for a stub/spy (the
  `get_persona_resolver` dependency reads `request.app.state.persona_resolver`
  at request time, per its own docstring), and `app.core.db.get_db` --  a
  module-level singleton bound to `settings.database_url` (the dev DB), NOT
  per-app state like `get_settings`/`get_jwks_cache` -- is pointed at the
  disposable `test_session` via FastAPI's own documented
  `app.dependency_overrides` mechanism. No route in this codebase queries the
  DB over HTTP yet (`app/api/activities.py`'s DB layer is still a
  `TODO(implementation)` stub), so this is newly established here rather
  than copied from an existing precedent -- it is the framework's own
  well-known testing convention for a DB-backed route, per
  `.claude/rules/pattern-consistency.md`'s "nothing like this exists yet"
  branch.
- `_get_programs` -- issues the `GET /api/programs` request; `token=None`
  omits the `Authorization` header entirely (for T-07's no-header case)
  rather than needing a second request helper.

TC-02 note: the test case's `preconditions` prose names literal groups
`['program-2','program-4']`, but its own `test_data.session_programs` is
`['prog-2','prog-4']` and `CurrentUser.programs` is always SERVER-DERIVED
from the `groups` claim via `_parse_programs` (`app/core/auth.py`), never
settable directly. This test builds a token whose `groups` claim
(`['program-prog-2','program-prog-4']`) parses, under the default
`program_group_prefix='program-'`, to `programs=['prog-2','prog-4']` --
matching `test_data`'s actual intent and every `expected_results` assertion
(`{prog-2, prog-4}`), not the preconditions' literal (inconsistent with the
seeded `prog-N` ids) groups string.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, contextmanager
from datetime import UTC, datetime
from typing import Any, cast

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import programs as programs_module
from app.core.db import get_db
from app.core.logging import JSONFormatter
from app.core.persona_resolver import (
    PersonaNotFoundError,
    PersonaResolutionError,
    PersonaResolver,
)
from app.models.rollup import ProgramSummary
from tests.conftest import (
    TEST_OIDC_CLIENT_ID,
    TEST_OIDC_ISSUER,
    AlembicRunner,
    KeycloakMock,
    RSATestKeypair,
)

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

# -----------------------------------------------------------------------------
# Stub persona resolver (D-06's `app.state.persona_resolver` seam). See module
# docstring for why this is redefined locally rather than imported from
# `test_rbac.py`.
# -----------------------------------------------------------------------------


class _StubPersonaResolver:
    def __init__(
        self,
        *,
        persona: str | None = None,
        mapping: dict[str, str] | None = None,
        raises: type[PersonaResolutionError] | None = None,
    ) -> None:
        self.persona = persona
        self.mapping = mapping or {}
        self.raises = raises
        self.calls: list[str] = []

    async def resolve(self, role: str) -> str:
        self.calls.append(role)
        if self.raises is not None:
            if self.raises is PersonaNotFoundError:
                raise PersonaNotFoundError(role)
            raise PersonaResolutionError(role, "stub: forced failure")
        if role in self.mapping:
            return self.mapping[role]
        if self.persona is not None:
            return self.persona
        raise PersonaNotFoundError(role)


def _configure_persona_resolver(stub: _StubPersonaResolver) -> PersonaResolver:
    """`cast` is safe here: structurally compatible (a single async
    `resolve(role) -> str` method) without literally subclassing
    `PersonaResolver` -- same idiom as `test_rbac.py::_configure`."""
    return cast(PersonaResolver, stub)


# -----------------------------------------------------------------------------
# program_summary seeding helpers (migrated_db/test_session, tests/conftest.py).
# -----------------------------------------------------------------------------


def _program_summary_row(program_id: str, **overrides: Any) -> dict[str, Any]:
    """One `program_summary` row dict with every NOT NULL column
    (`app/models/rollup.py::ProgramSummary`) defaulted -- only `program_id`
    (and occasionally `name`) typically need overriding per test."""
    row: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "program_id": program_id,
        "name": f"Program {program_id}",
        "icon": "rocket",
        "type": "product",
        "description": f"Test description for {program_id}",
        "monthly_token_sparkline": [],
        "tokens": 0,
        "releases": 0,
        "features": 0,
        "active_contributors": 0,
        "repos_with_harness_installed": 0,
        "repos_total": 0,
        "commands_executed": 0,
        "lines_of_code_generated": 0,
        "user_stories_delivered": 0,
        "intervention_count": None,
        "tool_rejections": None,
        "as_of_timestamp": datetime.now(UTC),
    }
    row.update(overrides)
    return row


async def _seed_programs(test_session: AsyncSession, program_ids: list[str]) -> None:
    """Insert one `program_summary` row per id, default fields from
    `_program_summary_row`, then commit -- mirrors
    `test_rollup_rebuild_program.py::_insert_events`'s seed-then-commit
    pattern against this same disposable test database."""
    rows = [_program_summary_row(pid) for pid in program_ids]
    await test_session.execute(sa.insert(ProgramSummary), rows)
    await test_session.commit()


# -----------------------------------------------------------------------------
# App + DB-override scaffold. See module docstring for why `get_db` needs
# `app.dependency_overrides` rather than a `Depends(get_settings)`-style
# per-app-state seam.
# -----------------------------------------------------------------------------


def _db_override(session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _get_db() -> AsyncIterator[AsyncSession]:
        yield session

    return _get_db


def _build_programs_app(
    build_app: Callable[..., FastAPI],
    test_session: AsyncSession,
    persona_resolver: PersonaResolver,
    **settings_overrides: Any,
) -> FastAPI:
    """Real `create_app()` instance (`build_app` fixture, D-07) wired for
    `/api/programs` testing: `app.state.persona_resolver` swapped for
    `persona_resolver` (directly, matching this task's own instructions --
    `get_persona_resolver` reads `request.app.state.persona_resolver`), and
    `get_db` overridden to the shared disposable `test_session`.

    `oidc_issuer`/`oidc_client_id` default to the mocked Keycloak realm
    (`TEST_OIDC_ISSUER`/`TEST_OIDC_CLIENT_ID`) so a real bearer JWT verifies;
    override via `**settings_overrides` for scenarios that need OIDC left
    unconfigured.
    """
    app = build_app(
        oidc_issuer=TEST_OIDC_ISSUER, oidc_client_id=TEST_OIDC_CLIENT_ID, **settings_overrides
    )
    app.state.persona_resolver = persona_resolver
    app.dependency_overrides[get_db] = _db_override(test_session)
    return app


async def _get_programs(
    async_client_for: AsyncClientFactory,
    app: FastAPI,
    *,
    token: str | None = None,
    query_string: str = "",
) -> Response:
    """Issue `GET /api/programs<query_string>`. `token=None` omits the
    `Authorization` header entirely -- exercises the no-header path (T-07's
    TC-03) without a separate request helper."""
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    async with async_client_for(app) as client:
        return await client.get(f"/api/programs{query_string}", headers=headers)


# -----------------------------------------------------------------------------
# AUTH-04-TC-01 (AC-1) -- cio persona sees every seeded program, groups=[].
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cio_persona_sees_all_programs_regardless_of_groups_tc01(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-04-TC-01: a cio persona's response includes every seeded
    `program_summary` row even with an empty `groups` claim -- groups is
    never consulted for cio (AC-1)."""
    seeded_ids = ["prog-1", "prog-2", "prog-3", "prog-4", "prog-5"]
    await _seed_programs(test_session, seeded_ids)
    persona_resolver = _configure_persona_resolver(_StubPersonaResolver(mapping={"cio": "cio"}))
    app = _build_programs_app(build_app, test_session, persona_resolver)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(role="cio", groups=[])

    resp = await _get_programs(async_client_for, app, token=token)

    assert resp.status_code == 200
    body = resp.json()
    returned_ids = {entry["program_id"] for entry in body["programs"]}
    assert returned_ids == set(seeded_ids)
    assert len(body["programs"]) == 5


# -----------------------------------------------------------------------------
# AUTH-04-TC-02 (AC-2) -- non-cio persona scoped to 2 of 5 sees exactly those.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_cio_persona_scoped_to_two_of_five_sees_exactly_those_tc02(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-04-TC-02: a non-cio persona scoped to `session.programs=
    ['prog-2','prog-4']` sees exactly those two of the 5 seeded rows. See
    module docstring for the groups-claim -> programs derivation note."""
    seeded_ids = ["prog-1", "prog-2", "prog-3", "prog-4", "prog-5"]
    await _seed_programs(test_session, seeded_ids)
    persona_resolver = _configure_persona_resolver(
        _StubPersonaResolver(mapping={"developer": "developer"})
    )
    app = _build_programs_app(build_app, test_session, persona_resolver)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(role="developer", groups=["program-prog-2", "program-prog-4"])

    resp = await _get_programs(async_client_for, app, token=token)

    assert resp.status_code == 200
    body = resp.json()
    returned_ids = {entry["program_id"] for entry in body["programs"]}
    assert returned_ids == {"prog-2", "prog-4"}
    assert len(body["programs"]) == 2


# -----------------------------------------------------------------------------
# AUTH-04-TC-05 (AC-4) -- non-cio, programs=[], 200 + empty list, not an error.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_cio_with_empty_programs_returns_200_and_empty_list_tc05(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-04-TC-05: a non-cio session whose `groups` claim matches zero
    seeded programs (`groups=[]` -> `programs=[]`) is a valid empty result --
    `200` with `programs: []`, never a 403/404."""
    seeded_ids = ["prog-1", "prog-2", "prog-3", "prog-4", "prog-5"]
    await _seed_programs(test_session, seeded_ids)
    persona_resolver = _configure_persona_resolver(
        _StubPersonaResolver(mapping={"developer": "developer"})
    )
    app = _build_programs_app(build_app, test_session, persona_resolver)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(role="developer", groups=[])

    resp = await _get_programs(async_client_for, app, token=token)

    assert resp.status_code == 200
    body = resp.json()
    assert body["programs"] == []


# -----------------------------------------------------------------------------
# T-07 scaffold addition -- call-recording spy on `AsyncSession.execute`, for
# TC-03/04's "no program_summary query ran before the 401" assertion.
# `_StubPersonaResolver.calls` (above) already covers the persona-resolver
# half; this covers the DB-query half. Instance-level monkeypatch on the
# shared `test_session` fixture -- restored automatically at teardown.
# -----------------------------------------------------------------------------


def _spy_on_execute(monkeypatch: pytest.MonkeyPatch, session: AsyncSession) -> list[Any]:
    """Wrap `session.execute` with a call-recording spy that still delegates
    to the real method -- returns the list of recorded call-arg tuples,
    which TC-03/04 assert stayed empty."""
    calls: list[Any] = []
    original_execute = session.execute

    async def _execute(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return await original_execute(*args, **kwargs)

    monkeypatch.setattr(session, "execute", _execute)
    return calls


# -----------------------------------------------------------------------------
# AUTH-04-TC-03 (AC-3) -- no Authorization header -> 401, fail-fast before
# persona resolution or the program_summary query.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_bearer_token_returns_401_before_scoping_tc03(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AUTH-04-TC-03: a request with no `Authorization` header is rejected
    with 401 by the shared auth dependency before persona resolution or the
    `program_summary` query ever run."""
    await _seed_programs(test_session, ["prog-1"])
    stub = _StubPersonaResolver(mapping={"cio": "cio"})
    persona_resolver = _configure_persona_resolver(stub)
    app = _build_programs_app(build_app, test_session, persona_resolver)
    query_calls = _spy_on_execute(monkeypatch, test_session)

    resp = await _get_programs(async_client_for, app, token=None)

    assert resp.status_code == 401
    assert stub.calls == []
    assert query_calls == []


# -----------------------------------------------------------------------------
# AUTH-04-TC-04 (AC-3) -- malformed bearer token -> 401, fail-fast before
# persona resolution or the program_summary query.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_bearer_token_returns_401_before_scoping_tc04(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AUTH-04-TC-04: a bearer token that fails JWT/JWKS validation is
    rejected with 401 before persona resolution or the `program_summary`
    query ever run. `test_data.bearer_token` is a deliberately invalid
    literal, reviewed and accepted at the Product Gate -- used as given."""
    await _seed_programs(test_session, ["prog-1"])
    stub = _StubPersonaResolver(mapping={"cio": "cio"})
    persona_resolver = _configure_persona_resolver(stub)
    app = _build_programs_app(build_app, test_session, persona_resolver)
    query_calls = _spy_on_execute(monkeypatch, test_session)

    resp = await _get_programs(
        async_client_for, app, token="not-a-real-jwt.invalid.signature"
    )

    assert resp.status_code == 401
    assert stub.calls == []
    assert query_calls == []


# -----------------------------------------------------------------------------
# AUTH-04-TC-09 (AC-6) -- program_visibility is an open-aggregate session
# gate, never a per-program 403 filter.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_per_program_403_open_aggregate_gate_tc09(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-04-TC-09: both a cio and a scoped non-cio session get a single
    200, with no per-item error/403 marker on any entry; scenario B's
    response contains both prog-1 and prog-3."""
    seeded_ids = ["prog-1", "prog-2", "prog-3", "prog-4", "prog-5"]
    await _seed_programs(test_session, seeded_ids)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)

    # Scenario A -- cio.
    resolver_a = _configure_persona_resolver(_StubPersonaResolver(mapping={"cio": "cio"}))
    app_a = _build_programs_app(build_app, test_session, resolver_a)
    token_a = build_access_token(role="cio", groups=[])
    resp_a = await _get_programs(async_client_for, app_a, token=token_a)

    # Scenario B -- non-cio scoped to prog-1/prog-3.
    resolver_b = _configure_persona_resolver(
        _StubPersonaResolver(mapping={"developer": "developer"})
    )
    app_b = _build_programs_app(build_app, test_session, resolver_b)
    token_b = build_access_token(role="developer", groups=["program-prog-1", "program-prog-3"])
    resp_b = await _get_programs(async_client_for, app_b, token=token_b)

    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    for resp in (resp_a, resp_b):
        for entry in resp.json()["programs"]:
            assert "error" not in entry
            assert entry.get("status") != 403
    returned_ids_b = {entry["program_id"] for entry in resp_b.json()["programs"]}
    assert {"prog-1", "prog-3"} <= returned_ids_b


# -----------------------------------------------------------------------------
# AUTH-04-TC-18 (NFR-security) -- a client-supplied `?programs=...` query
# string never widens scope beyond session.programs.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_supplied_programs_query_param_ignored_tc18(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-04-TC-18: a client-supplied `?programs=...` query string is
    ignored -- scoping stays derived solely from `session.programs`, never
    widened by a client-supplied filter."""
    seeded_ids = ["prog-1", "prog-2", "prog-3", "prog-4", "prog-5"]
    await _seed_programs(test_session, seeded_ids)
    persona_resolver = _configure_persona_resolver(
        _StubPersonaResolver(mapping={"developer": "developer"})
    )
    app = _build_programs_app(build_app, test_session, persona_resolver)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(role="developer", groups=["program-prog-1"])

    resp = await _get_programs(
        async_client_for,
        app,
        token=token,
        query_string="?programs=prog-1,prog-2,prog-3,prog-4,prog-5",
    )

    assert resp.status_code == 200
    body = resp.json()
    returned_ids = {entry["program_id"] for entry in body["programs"]}
    assert returned_ids == {"prog-1"}


# -----------------------------------------------------------------------------
# T-08 scaffold addition -- call-recording spy on `program_visibility`, bound
# by name inside `app.api.programs` (the route imports it via `from
# app.core.rbac import program_visibility`, so the call site resolves the
# module-local name). Mirrors T-07's `_spy_on_execute`: wraps and still
# delegates to the real (no-op) implementation.
# -----------------------------------------------------------------------------


def _spy_on_program_visibility(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Wrap `app.api.programs.program_visibility` with a call-recording spy
    that still delegates to the real function -- returns the list of
    recorded call-arg tuples, which TC-11 asserts has exactly one entry."""
    calls: list[Any] = []
    original = programs_module.program_visibility

    async def _spy(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))
        return await original(*args, **kwargs)

    monkeypatch.setattr(programs_module, "program_visibility", _spy)
    return calls


# -----------------------------------------------------------------------------
# AUTH-04-TC-06 (AC-5) -- a program entry's key set equals exactly
# {program_id, label, href, dotStyle}; set equality, not subset containment.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_program_entry_key_set_matches_adr_0005_exactly_tc06(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-04-TC-06: a program entry's key set equals exactly
    {program_id, label, href, dotStyle} -- set equality, not subset
    containment. The stale AC-5 field names (type, name, icon, description)
    and client-derived presentation fields (current, rowStyle) are absent."""
    await test_session.execute(
        sa.insert(ProgramSummary), [_program_summary_row("prog-1", name="Alpha")]
    )
    await test_session.commit()
    persona_resolver = _configure_persona_resolver(_StubPersonaResolver(mapping={"cio": "cio"}))
    app = _build_programs_app(build_app, test_session, persona_resolver)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(role="cio", groups=[])

    resp = await _get_programs(async_client_for, app, token=token)

    assert resp.status_code == 200
    entry = resp.json()["programs"][0]
    assert set(entry.keys()) == {"program_id", "label", "href", "dotStyle"}
    for absent_key in ("type", "name", "icon", "description", "current", "rowStyle"):
        assert absent_key not in entry


# -----------------------------------------------------------------------------
# AUTH-04-TC-07 (AC-5) -- href is the exact server-derived frontend page route
# for the entry's program_id (PGD-01 D-04: not the program-detail-api path).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_href_routes_to_program_detail_api_path_tc07(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-04-TC-07: href equals the exact server-derived frontend page route
    for the entry's program_id, not a client-constructed value (PGD-01 D-04
    fixed this from the program-detail-api JSON path to a navigable route)."""
    await _seed_programs(test_session, ["prog-1"])
    persona_resolver = _configure_persona_resolver(_StubPersonaResolver(mapping={"cio": "cio"}))
    app = _build_programs_app(build_app, test_session, persona_resolver)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(role="cio", groups=[])

    resp = await _get_programs(async_client_for, app, token=token)

    assert resp.status_code == 200
    entry = resp.json()["programs"][0]
    assert entry["href"] == "/programs/prog-1"


# -----------------------------------------------------------------------------
# AUTH-04-TC-08 (AC-5) -- dotStyle arrives pre-formatted CSS, not a raw
# palette key needing client-side transformation.
# -----------------------------------------------------------------------------

_CSS_DECLARATION_RE = re.compile(r"^[a-zA-Z-]+\s*:\s*\S.*;$")


@pytest.mark.asyncio
async def test_dot_style_is_pre_formatted_bindable_css_tc08(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-04-TC-08: dotStyle is a non-empty, directly bindable CSS
    declaration -- not the bare icon-name enum AC-5's superseded 'icon'
    field would have carried. Asserts the observable shape (a `property:
    value;` declaration), not a specific literal color -- the exact source
    is an implementation choice per ADR-0005 Flagged gaps."""
    await _seed_programs(test_session, ["prog-1"])
    persona_resolver = _configure_persona_resolver(_StubPersonaResolver(mapping={"cio": "cio"}))
    app = _build_programs_app(build_app, test_session, persona_resolver)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(role="cio", groups=[])

    resp = await _get_programs(async_client_for, app, token=token)

    assert resp.status_code == 200
    entry = resp.json()["programs"][0]
    dot_style = entry["dotStyle"]
    assert isinstance(dot_style, str)
    assert dot_style != ""
    assert _CSS_DECLARATION_RE.match(
        dot_style
    ), f"dotStyle {dot_style!r} is not a bindable CSS declaration"


# -----------------------------------------------------------------------------
# AUTH-04-TC-11 (FR-2) -- program_visibility is a single veto-gate call,
# never once per returned program.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_program_visibility_called_once_not_once_per_program_tc11(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AUTH-04-TC-11: program_visibility's call count is exactly 1 for a
    request scoped to 5 seeded programs -- never once per program row."""
    seeded_ids = ["prog-1", "prog-2", "prog-3", "prog-4", "prog-5"]
    await _seed_programs(test_session, seeded_ids)
    persona_resolver = _configure_persona_resolver(
        _StubPersonaResolver(mapping={"developer": "developer"})
    )
    app = _build_programs_app(build_app, test_session, persona_resolver)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(
        role="developer",
        groups=[f"program-{pid}" for pid in seeded_ids],
    )
    visibility_calls = _spy_on_program_visibility(monkeypatch)

    resp = await _get_programs(async_client_for, app, token=token)

    assert resp.status_code == 200
    assert len(resp.json()["programs"]) == 5
    assert len(visibility_calls) == 1


# -----------------------------------------------------------------------------
# T-09 scaffold addition -- log-capture handler for the real `app.api.programs`
# logger. Nothing in this file's own scaffold captures LogRecords (only
# `_spy_on_execute`/`_spy_on_program_visibility`, call-recording spies) --
# mirrors `test_persona_resolver.py`'s documented `_RecordCapturingHandler`/
# `_capture_logger` idiom (AUTH-02 TC-15 precedent): force-enabled and
# depropagated, immune to `configure_logging()`'s stdout trap and Alembic's
# `fileConfig(disable_existing_loggers=True)` sweep.
# -----------------------------------------------------------------------------


class _RecordCapturingHandler(logging.Handler):
    """Stores emitted `LogRecord` instances verbatim, without formatting them."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _capture_programs_logger(
    level: int = logging.INFO,
) -> Iterator[list[logging.LogRecord]]:
    """Captures records from the real `app.api.programs` logger."""
    logger = logging.getLogger(programs_module.__name__)
    original_disabled = logger.disabled
    original_propagate = logger.propagate
    original_level = logger.level
    logger.disabled = False
    logger.propagate = False
    logger.setLevel(level)
    handler = _RecordCapturingHandler()
    logger.addHandler(handler)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)
        logger.disabled = original_disabled
        logger.propagate = original_propagate
        logger.setLevel(original_level)


# -----------------------------------------------------------------------------
# AUTH-04-TC-10 (FR-1) -- programs_list_returned payload key set equals
# exactly {timestamp, level, logger, message, user_id, persona,
# returned_count} -- no email, no groups, no request path (C-1).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_programs_list_returned_log_payload_allowlist_tc10(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-04-TC-10: the emitted `programs_list_returned` log payload's key
    set equals exactly JSONFormatter's four first-class meta keys plus FR-1's
    three-field allowlist -- {timestamp, level, logger, message, user_id,
    persona, returned_count}. `email`/`groups` are populated on the token so
    their absence from the payload proves deliberate exclusion, not that they
    were never present to log (C-1; mirrors AUTH-02 TC-15 / AUTH-03 TC-20)."""
    await _seed_programs(test_session, ["alpha"])
    persona_resolver = _configure_persona_resolver(
        _StubPersonaResolver(mapping={"developer": "developer"})
    )
    app = _build_programs_app(build_app, test_session, persona_resolver)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(
        sub="u-900",
        email="dev@example.com",
        role="developer",
        groups=["program-alpha"],
    )

    with _capture_programs_logger() as records:
        resp = await _get_programs(async_client_for, app, token=token)

    assert resp.status_code == 200
    events = [r for r in records if r.getMessage() == "programs_list_returned"]
    assert len(events) == 1
    payload = json.loads(JSONFormatter().format(events[0]))

    # Allowlist, not a denylist (task instruction): set equality, not subset
    # containment.
    assert set(payload.keys()) == {
        "timestamp",
        "level",
        "logger",
        "message",
        "user_id",
        "persona",
        "returned_count",
    }
    for absent_key in ("email", "groups", "path", "request_path", "url"):
        assert absent_key not in payload
    assert payload["user_id"] == "u-900"
    assert payload["persona"] == "developer"
    assert payload["returned_count"] == 1


# -----------------------------------------------------------------------------
# T-10 scaffold addition -- FR-3/C-3 fail-closed persona resolution. All three
# tests below reuse `_StubPersonaResolver(raises=...)` and
# `_capture_programs_logger()` (T-09) unchanged. The route
# (`app/api/programs.py`) catches `PersonaNotFoundError` before its own base
# class `PersonaResolutionError` and logs the SAME event name
# ("programs_persona_resolution_failed") from both branches -- TC-12/TC-13
# distinguish which branch ran via the log record's `reason` extra
# ("not_found" vs "resolution_error"), not the event name, since a wrong catch
# order would still produce a 403 either way but would flip that field.
# -----------------------------------------------------------------------------

# TC-14's bound: comfortably below `PersonaResolver`'s real 3.0s Tier-3 timeout
# (`test_persona_resolver.py::test_tier3_query_timeout_raises_persona_resolution_error_tc11`)
# but generous enough for CI jitter -- proves the route surfaces the mocked
# failure promptly rather than via an unbounded/hanging wait, without actually
# sleeping for real (per this task's own instruction to follow that file's
# `_TIER3_TIMEOUT_SECONDS`-monkeypatch precedent rather than a real sleep).
_TC14_WALL_CLOCK_BOUND_SECONDS = 2.0


# -----------------------------------------------------------------------------
# AUTH-04-TC-12 (FR-3) -- PersonaNotFoundError fails closed: 403 "Access
# denied", exactly one WARNING log record, never a 500.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persona_not_found_error_fails_closed_403_tc12(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-04-TC-12: `persona_resolver.resolve` raising `PersonaNotFoundError`
    fails closed -- 403 "Access denied", exactly one WARNING log record, never
    a 500. The "not_found" `reason` on the emitted record proves the
    `PersonaNotFoundError` branch ran (see T-10 scaffold-addition note above)."""
    persona_resolver = _configure_persona_resolver(
        _StubPersonaResolver(raises=PersonaNotFoundError)
    )
    app = _build_programs_app(build_app, test_session, persona_resolver)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(role="unmapped-role", groups=[])

    with _capture_programs_logger(level=logging.WARNING) as records:
        resp = await _get_programs(async_client_for, app, token=token)

    assert resp.status_code == 403
    assert resp.status_code != 500
    assert resp.json()["error"]["message"] == "Access denied"

    warnings = [r for r in records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert warnings[0].getMessage() == "programs_persona_resolution_failed"
    assert warnings[0].__dict__["reason"] == "not_found"


# -----------------------------------------------------------------------------
# AUTH-04-TC-13 (FR-3) -- PersonaResolutionError fails closed: 403 "Access
# denied", exactly one WARNING log record, never a 500.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persona_resolution_error_fails_closed_403_tc13(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-04-TC-13: `persona_resolver.resolve` raising
    `PersonaResolutionError` (its own base class, distinct from
    `PersonaNotFoundError`) fails closed -- 403 "Access denied", exactly one
    WARNING log record, never a 500. The "resolution_error" `reason` on the
    emitted record proves the `PersonaResolutionError` branch ran, not the
    `PersonaNotFoundError` one (see T-10 scaffold-addition note above) --
    genuinely distinguishing TC-12 from TC-13, not just re-asserting 403
    twice."""
    persona_resolver = _configure_persona_resolver(
        _StubPersonaResolver(raises=PersonaResolutionError)
    )
    app = _build_programs_app(build_app, test_session, persona_resolver)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(role="cio", groups=[])

    with _capture_programs_logger(level=logging.WARNING) as records:
        resp = await _get_programs(async_client_for, app, token=token)

    assert resp.status_code == 403
    assert resp.status_code != 500
    assert resp.json()["error"]["message"] == "Access denied"

    warnings = [r for r in records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert warnings[0].getMessage() == "programs_persona_resolution_failed"
    assert warnings[0].__dict__["reason"] == "resolution_error"


# -----------------------------------------------------------------------------
# AUTH-04-TC-14 (FR-3, C-3) -- mocked Tier-3 timeout surfacing as
# PersonaResolutionError fails closed: 403, prompt (bounded) response, exactly
# one WARNING log record, never a 500/hang.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mocked_tier3_timeout_fails_closed_within_wall_clock_bound_tc14(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-04-TC-14: `persona_resolver.resolve` mocked to raise
    `PersonaResolutionError` immediately -- simulating a Tier-3 Postgres
    timeout per AUTH-02's resolver contract -- fails closed within a bounded
    wall-clock window rather than hanging: 403 "Access denied", exactly one
    WARNING log record, never a 500. Per this task's instruction, the timeout
    itself is mocked (not a real sleep) -- same precedent as
    `test_persona_resolver.py`'s `_TIER3_TIMEOUT_SECONDS` monkeypatch -- and
    the wall-clock timer proves the route path carries no unbounded wait on
    top of that."""
    persona_resolver = _configure_persona_resolver(
        _StubPersonaResolver(raises=PersonaResolutionError)
    )
    app = _build_programs_app(build_app, test_session, persona_resolver)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(role="cio", groups=[])

    with _capture_programs_logger(level=logging.WARNING) as records:
        started = time.perf_counter()
        resp = await _get_programs(async_client_for, app, token=token)
        elapsed = time.perf_counter() - started

    assert elapsed < _TC14_WALL_CLOCK_BOUND_SECONDS, (
        f"GET /api/programs took {elapsed:.3f}s under a mocked Tier-3 timeout, "
        f"exceeding the {_TC14_WALL_CLOCK_BOUND_SECONDS}s bound -- possible "
        "unbounded wait"
    )
    assert resp.status_code == 403
    assert resp.status_code != 500
    assert resp.json()["error"]["message"] == "Access denied"

    warnings = [r for r in records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert warnings[0].getMessage() == "programs_persona_resolution_failed"
    assert warnings[0].__dict__["reason"] == "resolution_error"


# -----------------------------------------------------------------------------
# AUTH-04-TC-15 (FR-4, C-5) -- a session program_id absent from
# `program_summary` is silently filtered by the WHERE clause, never raised.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_program_silently_filtered_from_response_tc15(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-04-TC-15: `current_user.programs` contains `prog-99`, which has
    no matching `program_summary` row -- the WHERE clause silently excludes
    it, response is 200 (no exception), and `returned_count` reflects only
    the two real rows."""
    await _seed_programs(test_session, ["prog-1", "prog-2"])
    persona_resolver = _configure_persona_resolver(
        _StubPersonaResolver(mapping={"developer": "developer"})
    )
    app = _build_programs_app(build_app, test_session, persona_resolver)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(
        role="developer",
        groups=["program-prog-1", "program-prog-2", "program-prog-99"],
    )

    resp = await _get_programs(async_client_for, app, token=token)

    assert resp.status_code == 200
    body = resp.json()
    returned_ids = {entry["program_id"] for entry in body["programs"]}
    assert returned_ids == {"prog-1", "prog-2"}
    assert "prog-99" not in returned_ids
    assert len(body["programs"]) == 2


# -----------------------------------------------------------------------------
# AUTH-04-TC-16 (FR-4, C-5) -- the same discrepancy fires a separately named
# WARN event (`programs_missing_from_summary`) exactly once, alongside (not
# instead of) `programs_list_returned`. Also asserts the negative case the
# plan called out: a `cio` request with a small `groups` list must never
# emit the discrepancy WARN, since `returned_count` there is the full table
# size and the comparison against `current_user.programs` is meaningless.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discrepancy_warn_logged_alongside_programs_list_returned_tc16(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-04-TC-16: non-cio scenario -- the `prog-1`/`prog-2`/`prog-99`
    discrepancy from TC-15 emits exactly one `programs_missing_from_summary`
    WARNING (event name distinct from `programs_list_returned`), carrying
    `{user_id, expected_count, returned_count}` with `expected_count (3) >
    returned_count (2)`, alongside a separate `programs_list_returned` INFO
    record (`returned_count == 2`) -- both present, neither replacing the
    other. cio scenario -- the same seeded table with a `groups` claim
    naming an unseeded program never emits the discrepancy WARN, since the
    comparison is meaningless on the cio path (AC-1: `returned_count` is the
    full table size, not derived from `current_user.programs`)."""
    await _seed_programs(test_session, ["prog-1", "prog-2"])
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)

    # Non-cio: discrepancy present -> WARN fires alongside programs_list_returned.
    developer_resolver = _configure_persona_resolver(
        _StubPersonaResolver(mapping={"developer": "developer"})
    )
    developer_app = _build_programs_app(build_app, test_session, developer_resolver)
    developer_token = build_access_token(
        sub="u-901",
        role="developer",
        groups=["program-prog-1", "program-prog-2", "program-prog-99"],
    )

    with _capture_programs_logger() as developer_records:
        developer_resp = await _get_programs(
            async_client_for, developer_app, token=developer_token
        )

    assert developer_resp.status_code == 200

    discrepancy_events = [
        r for r in developer_records if r.getMessage() == "programs_missing_from_summary"
    ]
    assert len(discrepancy_events) == 1
    discrepancy = discrepancy_events[0]
    assert discrepancy.levelno == logging.WARNING
    assert discrepancy.getMessage() != "programs_list_returned"
    assert discrepancy.__dict__["user_id"] == "u-901"
    assert discrepancy.__dict__["expected_count"] == 3
    assert discrepancy.__dict__["returned_count"] == 2
    assert discrepancy.__dict__["expected_count"] > discrepancy.__dict__["returned_count"]

    returned_events = [
        r for r in developer_records if r.getMessage() == "programs_list_returned"
    ]
    assert len(returned_events) == 1
    assert returned_events[0].__dict__["returned_count"] == 2

    # cio negative case: small groups list naming an unseeded program must
    # never trigger the discrepancy WARN on the cio path.
    cio_resolver = _configure_persona_resolver(_StubPersonaResolver(mapping={"cio": "cio"}))
    cio_app = _build_programs_app(build_app, test_session, cio_resolver)
    cio_token = build_access_token(sub="u-902", role="cio", groups=["program-prog-99"])

    with _capture_programs_logger() as cio_records:
        cio_resp = await _get_programs(async_client_for, cio_app, token=cio_token)

    assert cio_resp.status_code == 200
    assert len(cio_resp.json()["programs"]) == 2
    cio_discrepancy_events = [
        r for r in cio_records if r.getMessage() == "programs_missing_from_summary"
    ]
    assert cio_discrepancy_events == []
