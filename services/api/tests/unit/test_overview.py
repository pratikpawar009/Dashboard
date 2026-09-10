"""Contract + 404 tests for `GET /api/overview/program-detail/{program_id}`
(`app/api/overview.py`) -- PGD-01-TC-01/TC-02 (`docs/test-cases/PGD-01.json`).

Mirrors `test_programs.py`'s established scaffold (`build_app`/`async_client_for`/
`keycloak_mock`/`build_access_token`/`migrated_db`/`test_session` from
`tests/conftest.py`) but does NOT redefine a `_StubPersonaResolver`: unlike
`/api/programs`, this route's only RBAC call is `program_visibility`
(`app/core/rbac.py`), which is a hardcoded open-aggregate no-op that never
resolves a persona (`return None`, no `_resolver()` call) -- so
`app.state.persona_resolver` never needs overriding here. `create_app()`
constructs a real `PersonaResolver` unconditionally regardless (D-06 in
`app/main.py`), which is enough for the app to boot; this file only overrides
`get_db`, matching `test_programs.py`'s `_db_override`/`_build_programs_app`
precedent (`get_db` is a module-level singleton bound to the dev DB, not
per-app state, so it needs `app.dependency_overrides`, not a settings kwarg).

TC-01 covers AC-1/AC-2/AC-3/AC-6/NFR-security in one pass: bearer-JWT
required (401 with no header), the open-aggregate RBAC gate passing for both
a `cio` and an `engineering-manager` session regardless of `session.programs`,
header field sourcing, per-field `format_number()`/ratio-string formatting
(ADR-0007), the exact `{header, summary}` top-level shape (no cross-program
leakage), and the FR-PD-17/AC-6 byte-identical-across-personas invariant.
TC-02 covers AC-7/FR-3: an unknown `program_id` 404s with the app's existing
single error envelope (`app/core/errors.py`), not a bespoke shape.

OVW-01-T-04 (below) extends this same file with `GET /api/overview/summary`
coverage -- `OVW-01-TC-01`/`TC-02` (tracker #265/#266). Unlike
`program_visibility` above, `org_access` (`app/core/rbac.py`) DOES resolve a
persona from `current_user.role`, but role `"cio"` resolves via
`persona_role_map.yaml`'s Tier-2 default map (every canonical role name maps
to itself) without touching Postgres, so no persona-resolver stub is needed
here either -- see T-06 (a later, serialized task in this same file) for the
multi-persona case that does need one. The one genuinely new scaffold piece:
`app/api/overview.py`'s `get_org_summary` constructs a bare `FreshnessAccessor()`
per request with no session-factory override point of its own -- it defaults
to `app/services/freshness.py`'s `SessionLocal`, bound to `settings.database_url`
(the real dev database) at import time, never this suite's disposable
`test_engine`/`test_session`. `_override_freshness_accessor`
below redirects that construction onto `test_engine` so a seeded/absent
`system_metadata` row is actually what the route's freshness read sees,
without ever touching the dev database.
"""

from __future__ import annotations

import ast
import logging
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api import overview as overview_module
from app.api.overview import get_freshness_accessor
from app.core.db import get_db
from app.models.ingestion import SystemMetadata
from app.models.rollup import OrgSummaryRollup, ProgramSummary
from app.services.freshness import FreshnessAccessor as RealFreshnessAccessor
from tests.conftest import (
    TEST_OIDC_CLIENT_ID,
    TEST_OIDC_ISSUER,
    AlembicRunner,
    KeycloakMock,
    RSATestKeypair,
)

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

# -----------------------------------------------------------------------------
# program_summary seeding helper. Locally redefined per test_programs.py's own
# precedent of each topic file owning its scaffold rather than sharing test
# doubles/helpers via conftest.py.
# -----------------------------------------------------------------------------


def _program_summary_row(program_id: str, **overrides: Any) -> dict[str, Any]:
    """One `program_summary` row dict with every NOT NULL column
    (`app/models/rollup.py::ProgramSummary`) defaulted -- override only what
    a given test needs to assert on."""
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


async def _seed_program_summary(test_session: AsyncSession, row: dict[str, Any]) -> None:
    """Insert one `program_summary` row, then commit -- mirrors
    `test_programs.py::_seed_programs`'s seed-then-commit pattern against the
    same disposable test database."""
    await test_session.execute(sa.insert(ProgramSummary), [row])
    await test_session.commit()


# -----------------------------------------------------------------------------
# App + DB-override scaffold. See module docstring for why no persona-resolver
# override is needed here (unlike test_programs.py's `_build_programs_app`).
# -----------------------------------------------------------------------------


def _db_override(session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _get_db() -> AsyncIterator[AsyncSession]:
        yield session

    return _get_db


def _build_overview_app(
    build_app: Callable[..., FastAPI],
    test_session: AsyncSession,
    **settings_overrides: Any,
) -> FastAPI:
    """Real `create_app()` instance (`build_app` fixture, D-07) wired for
    `/api/overview/program-detail/{program_id}` testing against a live DB.

    `oidc_issuer`/`oidc_client_id` default to the mocked Keycloak realm
    (`TEST_OIDC_ISSUER`/`TEST_OIDC_CLIENT_ID`) so a real bearer JWT verifies."""
    app = build_app(
        oidc_issuer=TEST_OIDC_ISSUER, oidc_client_id=TEST_OIDC_CLIENT_ID, **settings_overrides
    )
    app.dependency_overrides[get_db] = _db_override(test_session)
    return app


async def _get_program_detail(
    async_client_for: AsyncClientFactory,
    app: FastAPI,
    program_id: str,
    *,
    token: str | None = None,
) -> Response:
    """Issue `GET /api/overview/program-detail/{program_id}`. `token=None`
    omits the `Authorization` header entirely (the no-bearer-token case)."""
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    async with async_client_for(app) as client:
        return await client.get(f"/api/overview/program-detail/{program_id}", headers=headers)


# -----------------------------------------------------------------------------
# PGD-01-TC-01 -- bearer-JWT required, RBAC-open, header + 7-card contract,
# byte-identical across personas.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_program_detail_contract_bearer_required_rbac_open_byte_identical_tc01(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """PGD-01-TC-01: seed one `program_summary` row for `prog-042`; a
    no-Authorization-header call is rejected (401); a `cio` and an
    `engineering-manager` session both pass the open-aggregate
    `program_visibility` gate and get 200 with byte-identical bodies; the
    response's header and 7 summary cards match the seeded values via
    `format_number()` (card 4 the unformatted ratio string); the top-level
    shape is exactly `{header, summary}` with no persona-conditional branch
    in the handler source."""
    program_id = "prog-042"
    seeded = _program_summary_row(
        program_id,
        name="Apex Core Migration",
        icon="rocket",
        type="Platform",
        description="Core platform migration to the harness pipeline",
        tokens=2_500_000,
        features=45,
        releases=12,
        repos_with_harness_installed=5,
        repos_total=6,
        commands_executed=8_500,
        lines_of_code_generated=125_000,
        user_stories_delivered=320,
    )
    await _seed_program_summary(test_session, seeded)
    app = _build_overview_app(build_app, test_session)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    cio_token = build_access_token(role="cio", groups=[])
    em_token = build_access_token(role="engineering-manager", groups=["program-prog-042"])

    anon_resp = await _get_program_detail(async_client_for, app, program_id, token=None)
    cio_resp = await _get_program_detail(async_client_for, app, program_id, token=cio_token)
    em_resp = await _get_program_detail(async_client_for, app, program_id, token=em_token)

    # Bearer-JWT enforcement (NFR-security) -- no client-side-only gating.
    assert anon_resp.status_code == 401

    # Open-aggregate RBAC gate -- both personas pass, not 403.
    assert cio_resp.status_code == 200
    assert em_resp.status_code == 200

    # FR-PD-17/AC-6 -- byte-identical response bodies across personas.
    assert cio_resp.content == em_resp.content

    body = cio_resp.json()

    # Full shape: exactly {header, summary}, no cross-program/session data.
    assert set(body.keys()) == {"header", "summary"}

    header = body["header"]
    assert set(header.keys()) == {"icon", "name", "type", "description"}
    for leaked_field in ("avatarStyle", "typeChip"):
        assert leaked_field not in header  # D-05: derived client-side, never shipped
    assert header == {
        "icon": "rocket",
        "name": "Apex Core Migration",
        "type": "Platform",
        "description": "Core platform migration to the harness pipeline",
    }

    summary = body["summary"]
    assert len(summary) == 7
    # DESIGN.md Region 4 order -- order is part of the contract (ADR-0007).
    expected_cards = [
        ("⬡", "2.5M", "Token consumption"),
        ("✦", "45", "Features delivered via Harness"),
        ("⤴", "12", "Releases done via Harness"),
        ("❯", "5 / 6", "Repos with Harness installed"),
        ("›_", "8.5K", "Commands executed"),
        ("</>", "125.0K", "Lines of code generated"),
        ("≡", "320", "User stories delivered"),
    ]
    for card, (glyph, value, label) in zip(summary, expected_cards, strict=True):
        assert set(card.keys()) == {"glyph", "value", "label"}
        assert card["glyph"] == glyph
        assert card["value"] == value
        assert card["label"] == label

    # No persona-conditional branch exists in the request path (test-case
    # step: grep the handler source for a session.persona/role check). Walks
    # the AST rather than substring-matching the raw source text, so the
    # module's own prose docstring describing this very invariant (which
    # necessarily contains the words "current_user.role") can't produce a
    # false positive -- only an actual `current_user.role`/`.persona`
    # attribute access in code would.
    tree = ast.parse(Path(overview_module.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in ("role", "persona"):
            assert not (isinstance(node.value, ast.Name) and node.value.id == "current_user"), (
                f"found current_user.{node.attr} access at line {node.lineno} -- "
                "persona-conditional branch would violate FR-PD-17/AC-6"
            )


# -----------------------------------------------------------------------------
# PGD-01-TC-02 -- unknown program_id returns the standard 404 envelope.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_program_id_returns_standard_404_envelope_tc02(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """PGD-01-TC-02: no `program_summary` row exists for `prog-404` -- the
    response is 404 with `app/core/errors.py`'s single existing error
    envelope (`{"error": {"code", "message", "details"}}`), not a bespoke
    shape or a 200 with empty/null card values. RBAC is open-aggregate, so
    any valid persona reaches the 404-for-unknown-id path under test."""
    app = _build_overview_app(build_app, test_session)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(role="cio", groups=[])

    resp = await _get_program_detail(async_client_for, app, "prog-404", token=token)

    assert resp.status_code == 404
    body = resp.json()
    assert set(body.keys()) == {"error"}
    assert set(body["error"].keys()) == {"code", "message", "details"}
    assert body["error"]["code"] == "http_404"
    assert body["error"]["message"] == "program not found"
    assert body["error"]["details"] is None


# =============================================================================
# OVW-01-T-04 -- GET /api/overview/summary: OVW-01-TC-01 (contract, populated
# org) + OVW-01-TC-02 (all-zero fallback, adoption_percent null). See module
# docstring for why a fresh persona-resolver stub isn't needed here but the
# freshness-accessor redirect is.
# =============================================================================


def _org_summary_rollup_row(**overrides: Any) -> dict[str, Any]:
    """One `org_summary_rollup` row dict with every NOT NULL column
    (`app/models/rollup.py::OrgSummaryRollup`) defaulted -- override only
    what a given test needs to assert on. Mirrors `_program_summary_row`'s
    precedent above."""
    now = datetime.now(UTC)
    row: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "org_id": "org-1",
        "programs_using_ai_count": 0,
        "programs_total": 0,
        "total_token_consumption": 0,
        "lines_of_code_generated": 0,
        "releases_using_harness": 0,
        "repos_with_harness_installed": 0,
        "repos_total": 0,
        "as_of_timestamp": now,
        "created_at": now,
        "updated_at": now,
    }
    row.update(overrides)
    return row


async def _seed_org_summary_rollup(test_session: AsyncSession, row: dict[str, Any]) -> None:
    """Insert one `org_summary_rollup` row, then commit -- mirrors
    `_seed_program_summary`'s seed-then-commit pattern above."""
    await test_session.execute(sa.insert(OrgSummaryRollup), [row])
    await test_session.commit()


async def _seed_system_metadata_ingestion(
    test_session: AsyncSession, last_successful_run_at: datetime
) -> None:
    """Seed the `system_metadata` freshness singleton row (`key='ingestion'`)
    that `FreshnessAccessor` reads. Absent, `FreshnessAccessor` raises a 500
    (`OVW-01-AC-7`/TC-03/TC-04 -- T-05's task, not this one)."""
    await test_session.execute(
        sa.insert(SystemMetadata),
        [{"key": "ingestion", "last_successful_run_at": last_successful_run_at}],
    )
    await test_session.commit()


def _override_freshness_accessor(
    app: FastAPI, test_engine: AsyncEngine
) -> list[None]:
    """Point the route's freshness read at this test's disposable `test_engine`,
    and record each call.

    Uses `app.dependency_overrides[get_freshness_accessor]` -- the same
    mechanism this file already uses for `get_db` -- rather than monkeypatching
    the module attribute. `app/api/overview.py` grew the
    `get_freshness_accessor` dependency for exactly this reason (flag AF-04,
    accepted at triage 2026-09-10): the handler used to construct a bare
    `FreshnessAccessor()`, which silently defaulted to the dev-database-bound
    `SessionLocal`, so a test's seeded/absent `system_metadata` row had no
    influence on what the read observed. Two workers independently reached for
    two different monkeypatches; both are retired in favour of this.

    Delegates to a REAL `FreshnessAccessor` wired at the test engine, so the
    read genuinely exercises the accessor's own row-present/row-absent logic --
    only construction is intercepted. Returns the recorded calls; TC-04 asserts
    `len(calls) == 1` to prove the read is unconditioned by the rollup lookup.
    """
    calls: list[None] = []
    session_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    class _SpyFreshnessAccessor:
        def __init__(self) -> None:
            self._real = RealFreshnessAccessor(session_factory=session_factory)

        async def get_last_successful_run(self) -> datetime:
            calls.append(None)
            return await self._real.get_last_successful_run()

    app.dependency_overrides[get_freshness_accessor] = _SpyFreshnessAccessor
    return calls


async def _get_org_summary(
    async_client_for: AsyncClientFactory,
    app: FastAPI,
    *,
    token: str | None = None,
) -> Response:
    """Issue `GET /api/overview/summary`. `token=None` omits the
    `Authorization` header entirely, mirroring `_get_program_detail`."""
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    async with async_client_for(app) as client:
        return await client.get("/api/overview/summary", headers=headers)


# -----------------------------------------------------------------------------
# OVW-01-TC-01 (AC-1/AC-2/AC-6/FR-1/FR-3) -- populated org: exact 5-card
# mockup-ordered contract, no color/style leakage, freshness read silent.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_org_summary_populated_contract_no_inline_css_freshness_silent_tc01(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OVW-01-TC-01 (tracker #265): a populated `org_summary_rollup` row plus
    a seeded `system_metadata` ingestion row -> 200 with the exact 5-card
    mockup-ordered contract (DECISIONS.md D-01/D-02): card 1
    (`programs_using_ai`) is the literal ratio, exempt from `format_number()`,
    with `sub == "70% adoption"`; cards 2-5 are `format_number()`-formatted
    with `sub is None`; card 5 (`repos_with_harness_installed`) is a PLAIN
    count, not a ratio -- the opposite of an earlier FR-1 revision. No
    color/style key anywhere (FR-2), and the freshness read succeeds exactly
    once with nothing from it reaching the response body (AC-6)."""
    seeded_at = datetime(2026, 9, 8, 3, 15, 0, tzinfo=UTC)
    await _seed_org_summary_rollup(
        test_session,
        _org_summary_rollup_row(
            programs_using_ai_count=7,
            programs_total=10,
            total_token_consumption=12_500_000,
            lines_of_code_generated=850_000,
            releases_using_harness=42,
            repos_with_harness_installed=18,
            repos_total=25,
        ),
    )
    await _seed_system_metadata_ingestion(test_session, seeded_at)
    app = _build_overview_app(build_app, test_session)
    freshness_calls = _override_freshness_accessor(app, test_engine)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(role="cio", groups=[])

    resp = await _get_org_summary(async_client_for, app, token=token)

    assert resp.status_code == 200
    body = resp.json()

    # Full shape: exactly {cards, programs_using_ai} -- no leaked field.
    assert set(body.keys()) == {"cards", "programs_using_ai"}

    cards = body["cards"]
    assert len(cards) == 5
    # DECISIONS.md D-01/D-02 order -- the ratio is card 1, not card 5.
    expected_cards = [
        ("▦", "7 / 10", "Programs using AI SDLC", "70% adoption"),
        ("⬡", "12.5M", "Total token consumption", None),
        ("</>", "850.0K", "Lines of code generated by Harness", None),
        ("⤴", "42", "Releases using Harness", None),
        ("❯", "18", "Repos with Harness installed", None),
    ]
    for card, (glyph, value, label, sub) in zip(cards, expected_cards, strict=True):
        assert set(card.keys()) == {"glyph", "value", "label", "sub"}
        assert card["glyph"] == glyph
        assert card["value"] == value
        assert card["label"] == label
        assert card["sub"] == sub
        # FR-2: no color/style/CSS key ever ships alongside a card.
        for leaked_key in ("color", "style", "css", "iconBg", "iconColor"):
            assert leaked_key not in card

    programs_using_ai = body["programs_using_ai"]
    assert set(programs_using_ai.keys()) == {"count", "total", "adoption_percent"}
    assert programs_using_ai == {"count": 7, "total": 10, "adoption_percent": 70.0}

    # AC-6: the freshness read succeeds exactly once, and nothing it returns
    # (a raw `datetime`) reaches the response body.
    assert len(freshness_calls) == 1
    assert seeded_at.isoformat() not in resp.text


# -----------------------------------------------------------------------------
# OVW-01-TC-02 (AC-2) -- missing org_summary_rollup row, ingestion row
# present: 200, all-zero cards, adoption_percent null.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_org_summary_missing_rollup_all_zero_fallback_tc02(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OVW-01-TC-02 (tracker #266): no `org_summary_rollup` row exists for
    `org_id='org-1'`, but `system_metadata`'s ingestion row IS seeded -- this
    isolates AC-2's all-zero-fallback path from AC-7's freshness-missing path
    (FR-3; the combined-absence case is `OVW-01-TC-04`, T-05's task, not this
    one). Response is 200, not 404/500, with card 1 the all-zero ratio
    `'0 / 0'` and cards 2-5 each `'0'` (DECISIONS.md D-01/D-02 order -- the
    ratio is card 1, not card 5)."""
    await _seed_system_metadata_ingestion(
        test_session, datetime(2026, 9, 8, 3, 15, 0, tzinfo=UTC)
    )
    app = _build_overview_app(build_app, test_session)
    _override_freshness_accessor(app, test_engine)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(role="cio", groups=[])

    resp = await _get_org_summary(async_client_for, app, token=token)

    assert resp.status_code == 200
    body = resp.json()

    expected_cards = [
        ("▦", "0 / 0", "Programs using AI SDLC", None),
        ("⬡", "0", "Total token consumption", None),
        ("</>", "0", "Lines of code generated by Harness", None),
        ("⤴", "0", "Releases using Harness", None),
        ("❯", "0", "Repos with Harness installed", None),
    ]
    for card, (glyph, value, label, sub) in zip(body["cards"], expected_cards, strict=True):
        assert card["glyph"] == glyph
        assert card["value"] == value
        assert card["label"] == label
        assert card["sub"] == sub

    assert body["programs_using_ai"] == {"count": 0, "total": 0, "adoption_percent": None}


# -----------------------------------------------------------------------------
# OVW-01-TC-02 / research Condition 2 -- DEDICATED regression guard, kept
# separate from the broader body-diff test above on purpose (per this task's
# own mandate): a future regression from `None` to `0.0` must fail loudly and
# specifically here, not as one line buried inside a larger dict diff.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_org_summary_missing_rollup_adoption_percent_is_none_not_zero_tc02(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OVW-01-TC-02 / research Condition 2: `programs_using_ai.adoption_percent`
    is JSON `null` (Python `None`), never the number `0.0`, when
    `programs_total == 0`. Deliberately a single narrow, explicitly-named
    `is None` assertion -- not `== 0` / `== 0.0`, either of which would also
    pass for a wrongly-shipped `0.0`."""
    await _seed_system_metadata_ingestion(
        test_session, datetime(2026, 9, 8, 3, 15, 0, tzinfo=UTC)
    )
    app = _build_overview_app(build_app, test_session)
    _override_freshness_accessor(app, test_engine)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(role="cio", groups=[])

    resp = await _get_org_summary(async_client_for, app, token=token)

    assert resp.status_code == 200
    body = resp.json()
    assert body["programs_using_ai"]["adoption_percent"] is None


# =============================================================================
# OVW-01-T-05 -- GET /api/overview/summary: OVW-01-TC-03 (freshness-missing,
# isolated from the rollup-absent case) + OVW-01-TC-04 (fully-fresh database,
# FR-3's own explicit combined-case mandate). Reuses T-04's
# `_override_freshness_accessor` above -- see the module
# docstring (AF-04) for why the freshness read must be redirected onto
# `test_engine`: `get_org_summary` constructs a bare `FreshnessAccessor()`
# with no injectable session factory of its own, so left unpatched it would
# read `app/services/freshness.py`'s module-level `SessionLocal` (the real
# dev database), making these tests' seeded-or-absent `system_metadata`
# state irrelevant to what the freshness read actually observes.
# =============================================================================


# -----------------------------------------------------------------------------
# OVW-01-TC-03 (AC-7) -- org_summary_rollup present, system_metadata absent:
# 500, "ingestion job may not have run yet", no partial cards/programs_using_ai
# payload alongside the error.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_org_summary_missing_ingestion_row_raises_ingestion_not_run_tc03(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OVW-01-TC-03 (tracker #267): `org_summary_rollup` seeded (any values),
    but NO `system_metadata` `key='ingestion'` row -- the isolated
    freshness-missing case (FR-3; the combined-absence case is
    `OVW-01-TC-04` below). `FreshnessAccessor.get_last_successful_run()`
    raises before the rollup lookup's all-zero-fallback branch is ever
    reachable, so this is 500, not a silent/empty 200, and the error body
    carries no partial `cards`/`programs_using_ai` payload alongside it."""
    await _seed_org_summary_rollup(
        test_session,
        _org_summary_rollup_row(
            programs_using_ai_count=3,
            programs_total=5,
            total_token_consumption=1_000,
            lines_of_code_generated=2_000,
            releases_using_harness=4,
            repos_with_harness_installed=1,
            repos_total=2,
        ),
    )
    # No system_metadata 'ingestion' row seeded -- freshness read must raise.
    app = _build_overview_app(build_app, test_session)
    _override_freshness_accessor(app, test_engine)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(role="cio", groups=[])

    resp = await _get_org_summary(async_client_for, app, token=token)

    assert resp.status_code == 500
    body = resp.json()
    # No partial cards/programs_using_ai payload alongside the error.
    assert set(body.keys()) == {"error"}
    assert "cards" not in body
    assert "programs_using_ai" not in body
    assert "ingestion job may not have run yet" in body["error"]["message"]


# -----------------------------------------------------------------------------
# OVW-01-TC-04 (FR-3) -- neither org_summary_rollup nor system_metadata rows
# exist (genuinely fresh database): still 500, same error substring. The
# sharpest case in the story -- proves the freshness read is UNCONDITIONED by
# the rollup lookup, not merely first by coincidence.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_org_summary_fully_fresh_database_still_raises_freshness_error_tc04(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OVW-01-TC-04 (tracker #268): NEITHER `org_summary_rollup` NOR
    `system_metadata` `key='ingestion'` rows exist -- a genuinely fresh,
    never-ingested database. Still 500 with the same error substring as
    `OVW-01-TC-03`, NOT the `OVW-01-TC-02`/AC-2 all-zero 200 payload that the
    rollup-absent branch alone would produce: FR-3 requires the freshness
    read to run unconditioned by whatever the rollup lookup would have
    returned. A spy on `FreshnessAccessor.get_last_successful_run()` proves
    it was actually invoked despite the rollup lookup having no row to
    return -- that invocation, not just the final status code, is what
    proves the call is unconditioned by the rollup result rather than
    merely happening to run first; without it this test would still pass
    against a handler reordered to check the rollup first and only call
    freshness on a rollup miss, which is exactly the regression FR-3 rules
    out."""
    # Neither table seeded: no org_summary_rollup row, no system_metadata row.
    app = _build_overview_app(build_app, test_session)
    freshness_calls = _override_freshness_accessor(app, test_engine)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(role="cio", groups=[])

    resp = await _get_org_summary(async_client_for, app, token=token)

    assert resp.status_code == 500
    body = resp.json()

    # NOT the AC-2 all-zero 200 payload -- no cards/programs_using_ai key at
    # all, only the error envelope. A future regression that let the
    # rollup-absent branch mask this raise would fail here even if it
    # somehow also returned 500 with an unrelated body.
    assert set(body.keys()) == {"error"}
    assert "cards" not in body
    assert "programs_using_ai" not in body
    assert "ingestion job may not have run yet" in body["error"]["message"]

    # Proves the freshness call is unconditioned by the rollup result: it
    # was invoked exactly once even though org_summary_rollup has no row for
    # 'org-1' to return.
    assert len(freshness_calls) == 1


# -----------------------------------------------------------------------------
# OVW-01-TC-05 (AC-3/AC-8) -- non-CIO 403 across all 5 personas, plus the
# rbac_check_org_access audit event on denial AND success alike.
# -----------------------------------------------------------------------------


class _RecordCapturingHandler(logging.Handler):
    """Collect `LogRecord`s in memory. Mirrors `test_rbac.py`'s handler."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _capture_rbac_logger(level: int = logging.INFO) -> Iterator[list[logging.LogRecord]]:
    """Attach a capturing handler to the REAL `app.core.rbac` logger, force-enabled
    and depropagated -- `test_rbac.py`'s and `test_persona_resolver.py`'s documented
    idiom, copied rather than imported (the sibling keeps it module-private).

    The force-enable is not defensive boilerplate: this test depends on
    `migrated_db`, and Alembic's `env.py` runs
    `fileConfig(disable_existing_loggers=True)`, which disables every already-created
    `app.*` logger process-wide. Without resetting `disabled`/`propagate` here, the
    handler would be attached to a silenced logger and the AC-8 assertions below
    would fail for a reason wholly unrelated to the code under test."""
    logger = logging.getLogger("app.core.rbac")
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


def _org_access_events(records: list[logging.LogRecord]) -> list[logging.LogRecord]:
    return [r for r in records if r.getMessage() == "rbac_check_org_access"]


_NON_CIO_PERSONAS = ("architect", "developer", "product-manager", "engineering-manager")


@pytest.mark.asyncio
async def test_org_summary_cio_only_403_for_every_other_persona_with_audit_log_tc05(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OVW-01-TC-05 (tracker #269): `cio` gets 200; every other persona gets 403
    with no data body; and `rbac_check_org_access` is logged for **all five**
    calls, carrying user id, persona, outcome and a timestamp.

    This is `org_access`'s first exercise through a real HTTP route anywhere in
    this codebase -- the sibling `program-detail` route uses
    `program_visibility`, which never resolves a persona, so no existing route
    test covers this path. It is new ground, not a variation on covered ground.

    No persona-resolver stub: `services/api/config/persona_role_map.yaml`'s
    Tier-2 default maps all five canonical role names to themselves
    (`cio->cio`, `architect->architect`, ...), so `build_access_token(role=...)`
    resolves through the REAL `PersonaResolver` that `create_app()` already
    constructs. Stubbing it would hollow out the very integration this test
    exists to cover.

    The success case is asserted as deliberately as the denials. AC-8 requires
    the check be logged on **both** outcomes (`app/core/rbac.py:95-97` emits
    `denied` and `authorized` respectively), so a test inspecting only the four
    403s would leave half the criterion unverified."""
    # A populated rollup + ingestion row so the cio case can genuinely reach 200
    # -- otherwise the positive half of this test would prove nothing.
    await _seed_org_summary_rollup(test_session, _org_summary_rollup_row())
    await _seed_system_metadata_ingestion(test_session, datetime(2026, 9, 8, 3, 15, tzinfo=UTC))
    app = _build_overview_app(build_app, test_session)
    _override_freshness_accessor(app, test_engine)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)

    with _capture_rbac_logger() as records:
        cio_resp = await _get_org_summary(
            async_client_for, app, token=build_access_token(role="cio", groups=[])
        )
        denied: dict[str, Response] = {}
        for persona in _NON_CIO_PERSONAS:
            denied[persona] = await _get_org_summary(
                async_client_for, app, token=build_access_token(role=persona, groups=[])
            )

    # --- cio: authorized, and a real payload came back -------------------------
    assert cio_resp.status_code == 200
    cio_body = cio_resp.json()
    assert set(cio_body.keys()) == {"cards", "programs_using_ai"}
    assert len(cio_body["cards"]) == 5

    # --- every other persona: 403, and NO data body --------------------------
    for persona, resp in denied.items():
        assert resp.status_code == 403, f"{persona} should be denied"
        body = resp.json()
        # security-baseline: a denial leaks no data. Only the error envelope.
        assert set(body.keys()) == {"error"}, f"{persona} leaked a data body: {body}"
        assert "cards" not in body
        assert "programs_using_ai" not in body

    # --- AC-8: the audit event fired on all five calls -----------------------
    events = _org_access_events(records)
    assert len(events) == 5, f"expected one rbac_check_org_access per call, got {len(events)}"

    # Keyed by persona so each call's event is asserted individually rather
    # than in aggregate. Every event must carry a `persona` -- an event without
    # one is itself a failure, so this is asserted before the mapping is built
    # rather than defaulted away with `getattr(..., None)`.
    for record in events:
        assert isinstance(getattr(record, "persona", None), str), (
            f"rbac_check_org_access event carries no persona: {record!r}"
        )
    by_persona: dict[str, logging.LogRecord] = {r.persona: r for r in events}  # type: ignore[attr-defined]
    assert set(by_persona) == {"cio", *_NON_CIO_PERSONAS}

    for logged_persona, record in by_persona.items():
        assert getattr(record, "user_id", None), (
            f"{logged_persona}: no user_id on the audit event"
        )
        assert record.created > 0, f"{logged_persona}: no timestamp on the audit event"
        expected = "authorized" if logged_persona == "cio" else "denied"
        assert getattr(record, "outcome", None) == expected, (
            f"{logged_persona}: outcome should be {expected}"
        )

    # The success case specifically -- half of AC-8, and the half a
    # denials-only test would silently skip.
    assert getattr(by_persona["cio"], "outcome", None) == "authorized"
