"""Tests for `GET /api/artifacts/{program_id}` (`app/api/artifacts.py`,
`app/services/artifacts.py`) -- SHP-04-TC-01..TC-08 (`docs/test-cases/SHP-04.json`).

Scaffold mirrors `test_program_board.py` (`build_app`/`async_client_for`/`migrated_db`/
`test_session` from `tests/conftest.py`, `POST /auth/dev-bypass` bearer tokens): a
dev-bypass token resolves a real persona from its `role` claim through the same
`PersonaResolver` `create_app()` constructs (Tier-2 `persona_role_map.yaml` default maps
every canonical role name to itself), so no Keycloak/JWKS fixture is needed here either.

`governance_visibility` is THIS gate's first live route consumer (module docstring,
`app/core/rbac.py:196-243`) -- it has zero prior route-level exercise, so this file is the
highest-value RBAC coverage in the story: both excluded personas (`cio`,
`engineering-manager`) must be proven denied, not just the three allowed ones, and the
denial must be shown to happen BEFORE any `program_artifacts` read (query spy).

Log assertions self-witness per the known Alembic `fileConfig` trap
(`.claude/agent-memory/implementation-agent/alembic-fileconfig-disables-app-loggers.md`,
`test_program_board.py::test_non_cio_403_no_body_and_rbac_check_org_access_logged_tc05`'s
precedent): TC-04 asserts the `rbac_check_governance_visibility` event fires on BOTH
outcomes (authorized + denied) before asserting the absence of a separate
`governance_view_denied` event, so a silently disabled logger cannot produce a false pass.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.db import get_db
from app.models.governance import ProgramArtifact
from tests.conftest import AlembicRunner

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

# _ARTIFACT_PRESENTATION order (app/services/artifacts.py) -- the frozen FR-1 order.
_CANONICAL_TAG_ORDER = ["PRD", "US", "TC", "AD", "API"]

_ALLOWED_PERSONAS = ("architect", "product-manager", "developer")
_DENIED_PERSONAS = ("cio", "engineering-manager")


# -----------------------------------------------------------------------------
# App + DB-override scaffold. Mirrors test_program_board.py's
# _db_override / _build_board_app precedent.
# -----------------------------------------------------------------------------


def _db_override(session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _get_db() -> AsyncIterator[AsyncSession]:
        yield session

    return _get_db


def _build_artifacts_app(
    build_app: Callable[..., FastAPI], test_session: AsyncSession, **settings_overrides: Any
) -> FastAPI:
    """Real `create_app()` wired for HTTP-level testing against a live DB. Hermetic
    default settings set `environment="test"`, so `/auth/dev-bypass` is registered and
    its tokens verify with no OIDC config."""
    app = build_app(**settings_overrides)
    app.dependency_overrides[get_db] = _db_override(test_session)
    return app


async def _mint_dev_bypass_token(client: AsyncClient, *, role: str) -> str:
    resp = await client.post("/auth/dev-bypass", json={"role": role})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


async def _get_artifacts(client: AsyncClient, *, token: str | None, program_id: str) -> Response:
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    return await client.get(f"/api/artifacts/{program_id}", headers=headers)


# -----------------------------------------------------------------------------
# Seed helpers.
# -----------------------------------------------------------------------------


def _artifact_row(program_id: str, artifact_type: str, count: int) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "program_id": program_id,
        "type": artifact_type,
        "count": count,
        "as_of_timestamp": datetime.now(UTC),
    }


async def _seed_artifact_rows(test_session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        test_session.add(ProgramArtifact(**row))
    await test_session.commit()


_DASHBOARD_LIVE_COUNTS: dict[str, int] = {
    "prd": 4,
    "user_story": 45,
    "test_case": 274,
    "arch_diagram": 0,
    "api_spec": 0,
}


async def _seed_dashboard_program(
    test_session: AsyncSession, program_id: str = "dashboard"
) -> None:
    await _seed_artifact_rows(
        test_session,
        [
            _artifact_row(program_id, artifact_type, count)
            for artifact_type, count in _DASHBOARD_LIVE_COUNTS.items()
        ],
    )


# -----------------------------------------------------------------------------
# Log capture -- mirrors test_program_board.py::_capture_rbac_logger idiom,
# duplicated locally per that file's own precedent of each topic file owning
# its scaffold.
# -----------------------------------------------------------------------------


class _RecordCapturingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _capture_rbac_logger(level: int = logging.INFO) -> Iterator[list[logging.LogRecord]]:
    """Attach a capturing handler to the REAL `app.core.rbac` logger, force-enabled
    and depropagated -- required because Alembic's `env.py` runs
    `fileConfig(disable_existing_loggers=True)`, which disables every already-created
    `app.*` logger process-wide once `migrated_db` has run in this session."""
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


def _governance_events(records: list[logging.LogRecord]) -> list[logging.LogRecord]:
    return [r for r in records if r.getMessage() == "rbac_check_governance_visibility"]


def _forbidden_denial_events(records: list[logging.LogRecord]) -> list[logging.LogRecord]:
    return [r for r in records if r.getMessage() == "governance_view_denied"]


# -----------------------------------------------------------------------------
# Query spy -- mirrors test_auth_groups.py::_QuerySpy / _query_spy idiom,
# duplicated locally per this project's per-file scaffold-ownership precedent.
# -----------------------------------------------------------------------------


class _QuerySpy:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def take(self) -> list[str]:
        return list(self.statements)


@contextmanager
def _query_spy(engine: AsyncEngine) -> Iterator[_QuerySpy]:
    """Attach a `before_cursor_execute` recorder for the duration of the block,
    capturing only statements touching `program_artifacts`."""
    spy = _QuerySpy()
    sync_engine = engine.sync_engine

    def _before_cursor_execute(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        if "program_artifacts" in statement:
            spy.statements.append(statement)

    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield spy
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before_cursor_execute)


# =============================================================================
# TC-01 -- fixed 5-row order, exact field set, raw-int count.
# =============================================================================


@pytest.mark.asyncio
async def test_fixed_order_field_set_and_raw_int_count_tc01(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """SHP-04-TC-01: response is {items: [...]} with exactly 5 entries in the order
    prd, user_story, test_case, arch_diagram, api_spec, each carrying exactly
    tag/name/count/bg/color, count is a raw JSON int (never a formatted string), and
    bg/color are non-empty strings identical across repeat calls."""
    app = _build_artifacts_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="architect")
        await _seed_dashboard_program(test_session)
        resp = await _get_artifacts(client, token=token, program_id="dashboard")
        resp_repeat = await _get_artifacts(client, token=token, program_id="dashboard")

    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert list(body.keys()) == ["items"]
    items = body["items"]
    assert len(items) == 5
    assert [item["tag"] for item in items] == _CANONICAL_TAG_ORDER

    expected_counts = [4, 45, 274, 0, 0]
    for item, expected_count in zip(items, expected_counts, strict=True):
        assert set(item.keys()) == {"tag", "name", "count", "bg", "color"}
        assert item["count"] == expected_count
        assert isinstance(item["count"], int)
        assert not isinstance(item["count"], bool)
        assert isinstance(item["bg"], str) and item["bg"]
        assert isinstance(item["color"], str) and item["color"]

    # raw int, never a formatted string -- the wire text must show a bare digit,
    # never a quoted "4"/"45"/"274".
    raw_text = resp.text
    assert '"count": "4"' not in raw_text
    assert '"count": "274"' not in raw_text

    # Server-owned constants: identical bg/color across repeat calls.
    assert resp_repeat.status_code == 200, resp_repeat.text
    assert resp_repeat.json() == body


# =============================================================================
# TC-02 -- all 3 allowed personas -> 200, byte-identical payload.
# =============================================================================


@pytest.mark.asyncio
async def test_allowed_personas_all_200_byte_identical_tc02(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """SHP-04-TC-02: architect, product-manager, and developer each receive 200 with
    the full 5-item response, and all 3 payloads are byte-identical for the same
    program_id -- no persona-specific branching."""
    app = _build_artifacts_app(build_app, test_session)

    async with async_client_for(app) as client:
        await _seed_dashboard_program(test_session)
        responses: dict[str, Response] = {}
        for persona in _ALLOWED_PERSONAS:
            token = await _mint_dev_bypass_token(client, role=persona)
            responses[persona] = await _get_artifacts(client, token=token, program_id="dashboard")

    bodies = []
    for persona, resp in responses.items():
        assert resp.status_code == 200, f"{persona} should be authorized: {resp.text}"
        body = resp.json()
        assert len(body["items"]) == 5
        bodies.append(body)

    assert bodies[0] == bodies[1] == bodies[2]


# =============================================================================
# TC-03 -- cio AND engineering-manager both 403, zero SELECTs against
# program_artifacts (denial happens before any data read).
# =============================================================================


@pytest.mark.asyncio
async def test_cio_and_engineering_manager_both_403_no_body_no_select_tc03(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """SHP-04-TC-03 (the highest-value RBAC assertion in this story): both cio and
    engineering-manager are rejected 403 with no `items`/artifact data in the body --
    counter-intuitive for cio, which passes org_access/program_visibility elsewhere --
    and a query spy over `program_artifacts` proves the denial happens before any read
    (zero SELECTs for either call)."""
    await _seed_dashboard_program(test_session)
    app = _build_artifacts_app(build_app, test_session)

    denied: dict[str, Response] = {}
    async with async_client_for(app) as client:
        with _query_spy(test_engine) as spy:
            for persona in _DENIED_PERSONAS:
                token = await _mint_dev_bypass_token(client, role=persona)
                denied[persona] = await _get_artifacts(client, token=token, program_id="dashboard")

    for persona, resp in denied.items():
        assert resp.status_code == 403, f"{persona} should be denied: {resp.text}"
        body = resp.json()
        assert "items" not in body
        assert set(body.keys()) == {"error"}

    assert spy.take() == [], (
        "governance_visibility must deny cio/engineering-manager before any "
        f"program_artifacts SELECT runs; observed: {spy.take()}"
    )


# =============================================================================
# TC-04 -- rbac_check_governance_visibility logged on both outcomes; no
# separate governance_view_denied event; self-witnessing.
# =============================================================================


@pytest.mark.asyncio
async def test_governance_visibility_logging_contract_self_witnessing_tc04(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """SHP-04-TC-04 (FR-2): the architect call emits
    `rbac_check_governance_visibility` outcome=authorized; the cio call emits the same
    event outcome=denied; zero `governance_view_denied` events are ever emitted; the
    route adds no additional log line of its own around the gate.

    Self-witnessing per the known Alembic fileConfig trap: the authorized-case emission
    is asserted as deliberately as the denied one (and as the absence check), so a
    silently disabled logger -- which would make an absence-only assertion vacuously
    pass -- cannot slip through undetected.
    """
    await _seed_dashboard_program(test_session)
    app = _build_artifacts_app(build_app, test_session)

    async with async_client_for(app) as client:
        with _capture_rbac_logger() as records:
            architect_token = await _mint_dev_bypass_token(client, role="architect")
            architect_resp = await _get_artifacts(
                client, token=architect_token, program_id="dashboard"
            )

            cio_token = await _mint_dev_bypass_token(client, role="cio")
            cio_resp = await _get_artifacts(client, token=cio_token, program_id="dashboard")

    assert architect_resp.status_code == 200, architect_resp.text
    assert cio_resp.status_code == 403, cio_resp.text

    # Self-witnessing: prove the authorized emission actually happened FIRST, before
    # asserting any absence -- an empty/disabled logger fails this outright rather than
    # only failing a "no denial event" check that would pass vacuously.
    governance_events = _governance_events(records)
    assert len(governance_events) == 2, (
        f"expected exactly 2 rbac_check_governance_visibility events (1 authorized, "
        f"1 denied), got {len(governance_events)}: {[r.getMessage() for r in records]}"
    )

    by_outcome: dict[str, logging.LogRecord] = {}
    for record in governance_events:
        outcome = getattr(record, "outcome", None)
        assert outcome in ("authorized", "denied"), f"missing/invalid outcome: {record!r}"
        by_outcome[outcome] = record

    assert set(by_outcome) == {"authorized", "denied"}
    assert getattr(by_outcome["authorized"], "persona", None) == "architect"
    assert getattr(by_outcome["denied"], "persona", None) == "cio"
    assert getattr(by_outcome["authorized"], "user_id", None)
    assert getattr(by_outcome["denied"], "user_id", None)

    # Only now assert the absence -- the self-witnessing precondition above already
    # proved the log pipeline is live.
    assert _forbidden_denial_events(records) == [], (
        "governance_view_denied must never be emitted -- "
        "rbac_check_governance_visibility with outcome is the only denial event"
    )


# =============================================================================
# TC-05 -- persona-resolution failure (unmapped role, all 3 tiers miss) -> 403,
# zero program_artifacts SELECTs.
# =============================================================================


@pytest.mark.asyncio
async def test_persona_resolution_failure_403_no_select_tc05(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """SHP-04-TC-05: a bearer token whose role claim maps to no persona in any of the
    3 tiers (Tier-1 env unset, Tier-2 YAML has no entry for it, Tier-3 Postgres
    persona_config has no row for it either) is rejected 403 via the gate's fail-closed
    `_resolve_persona_or_deny` path, with no data body and zero program_artifacts
    SELECTs -- the resolver failure denies before the service layer is ever reached."""
    await _seed_dashboard_program(test_session)
    app = _build_artifacts_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="totally-unmapped-role-zzz")
        with _query_spy(test_engine) as spy:
            resp = await _get_artifacts(client, token=token, program_id="dashboard")

    assert resp.status_code == 403, resp.text
    body = resp.json()
    assert "items" not in body

    assert spy.take() == [], (
        f"persona-resolution failure must deny before any program_artifacts read; "
        f"observed: {spy.take()}"
    )


# =============================================================================
# TC-06 -- unknown program_id is NOT rejected by the gate; 200 all-zero, no 404.
# =============================================================================


@pytest.mark.asyncio
async def test_unknown_program_id_not_rejected_200_all_zero_tc06(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """SHP-04-TC-06 (FR-3): an unknown/nonexistent program_id is never 404'd here --
    the persona gate passes, program_visibility's open-aggregate cascade does not
    reject on the unknown id, and the response is 200 with all 5 canonical types at
    count 0, produced by the service layer's zero-fill, not by the gate."""
    app = _build_artifacts_app(build_app, test_session)

    async with async_client_for(app) as client:
        with _capture_rbac_logger() as records:
            token = await _mint_dev_bypass_token(client, role="architect")
            resp = await _get_artifacts(client, token=token, program_id="nonexistent-program-zzz")

    assert resp.status_code == 200, resp.text
    assert resp.status_code != 404
    body = resp.json()
    items = body["items"]
    assert len(items) == 5
    assert [item["tag"] for item in items] == _CANONICAL_TAG_ORDER
    for item in items:
        assert item["count"] == 0

    governance_events = _governance_events(records)
    assert len(governance_events) == 1
    assert getattr(governance_events[0], "outcome", None) == "authorized"


# =============================================================================
# TC-07 -- real program, zero program_artifacts rows -> 200 all-zero, all 5
# canonical types present.
# =============================================================================


@pytest.mark.asyncio
async def test_program_with_no_artifact_rows_200_all_zero_tc07(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """SHP-04-TC-07 (AC-3): a program with zero program_artifacts rows still renders
    all 5 canonical types at count 0, never an error and never a subset of types."""
    app = _build_artifacts_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        resp = await _get_artifacts(client, token=token, program_id="empty-program")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    items = body["items"]
    assert len(items) == 5
    assert [item["tag"] for item in items] == _CANONICAL_TAG_ORDER
    for item in items:
        assert item["count"] == 0


# =============================================================================
# TC-08 -- real zero-count row and missing row render identically; no drops.
# =============================================================================


@pytest.mark.asyncio
async def test_real_zero_count_row_matches_missing_row_no_drop_tc08(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """SHP-04-TC-08 (AC-4): using the documented live dataset (prd=4, user_story=45,
    test_case=274, arch_diagram=0, api_spec=0 -- arch_diagram/api_spec have REAL rows
    with count=0, not missing rows), every type's count matches its persisted row
    exactly, and the two zero-count types are present, never dropped for being zero."""
    await _seed_dashboard_program(test_session)
    app = _build_artifacts_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="product-manager")
        resp = await _get_artifacts(client, token=token, program_id="dashboard")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    items = body["items"]
    assert len(items) == 5

    by_tag = {item["tag"]: item["count"] for item in items}
    assert by_tag["PRD"] == 4
    assert by_tag["US"] == 45
    assert by_tag["TC"] == 274
    assert by_tag["AD"] == 0
    assert by_tag["API"] == 0
    # Not dropped: both zero-count entries are present as real keys.
    assert "AD" in by_tag
    assert "API" in by_tag
