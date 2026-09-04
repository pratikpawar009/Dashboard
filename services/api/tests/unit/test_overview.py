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
"""

from __future__ import annotations

import ast
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import overview as overview_module
from app.core.db import get_db
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
