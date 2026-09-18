"""Tests for `GET /api/overview/program-board`
(`app/api/overview.py::get_program_board`, `app/services/program_board.py`) --
OVW-04-TC-01, TC-02, TC-03, TC-04, TC-05, TC-08, TC-09, TC-10, TC-11
(`docs/test-cases/OVW-04.json`).

Scaffold mirrors `test_program_releases_route.py` (`build_app`/`async_client_for`/
`migrated_db`/`test_session` from `tests/conftest.py`, `POST /auth/dev-bypass`
bearer tokens): this route's RBAC gate is `org_access` (cio-only, persona-resolving),
NOT the open-aggregate `program_visibility` its `program-detail/*` siblings use, but a
dev-bypass token still resolves a real persona from its `role` claim through the same
`PersonaResolver` `create_app()` constructs (Tier-2 `persona_role_map.yaml` default
maps every canonical role name to itself), so dev-bypass tokens are sufficient here too
-- no Keycloak/JWKS fixture needed, mirroring the `program_releases`/`program_commands`
route-test precedent rather than `test_overview.py`'s heavier `build_access_token` one.

Log assertions self-witness per the known Alembic `fileConfig` trap
(`.claude/agent-memory/implementation-agent/alembic-fileconfig-disables-app-loggers.md`,
`test_program_releases_route.py::test_program_visibility_server_side_no_dedicated_audit_event_tc21`'s
precedent): TC-05 asserts the `rbac_check_org_access` event fires on BOTH outcomes
(authorized + denied) rather than only asserting an event's absence, so a silently
disabled logger cannot produce a false pass.

Performance tests (TC-02, TC-11) are plain pytest -- no `@pytest.mark.perf`, no new
runner (this repo's `perf` marker is deselected by default `addopts` in
`pyproject.toml`, and PLAN.md is explicit this task uses "plain pytest, no new
runner"). Honest measurement: assertions are on the actual measured p95 and query
plan; never loosened to make a breach disappear.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.db import get_db
from app.models.rollup import ProgramSummary
from app.services.program_board import _compute_mom, _validate_sparkline
from tests.conftest import AlembicRunner

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]


# -----------------------------------------------------------------------------
# App + DB-override scaffold. Mirrors test_program_releases_route.py's
# _build_releases_app / _db_override precedent.
# -----------------------------------------------------------------------------


def _db_override(session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _get_db() -> AsyncIterator[AsyncSession]:
        yield session

    return _get_db


def _build_board_app(
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


async def _get_board(
    client: AsyncClient,
    *,
    token: str | None,
    page: int | None = None,
    page_size: int | None = None,
) -> Response:
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    params: dict[str, Any] = {}
    if page is not None:
        params["page"] = page
    if page_size is not None:
        params["page_size"] = page_size
    return await client.get("/api/overview/program-board", headers=headers, params=params)


# -----------------------------------------------------------------------------
# Seed helpers.
# -----------------------------------------------------------------------------


def _program_summary_row(program_id: str, **overrides: Any) -> dict[str, Any]:
    """One `program_summary` row dict with every NOT NULL column
    (`app/models/rollup.py::ProgramSummary`) defaulted -- override only what a given
    test needs to assert on. Mirrors `test_overview.py::_program_summary_row`."""
    row: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "program_id": program_id,
        "name": f"Program {program_id}",
        "icon": "rocket",
        "type": "Greenfield feature development",
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


async def _seed_program_summary_rows(
    test_session: AsyncSession, rows: list[dict[str, Any]]
) -> None:
    for row in rows:
        test_session.add(ProgramSummary(**row))
    await test_session.commit()


# -----------------------------------------------------------------------------
# Log capture -- mirrors test_overview.py::_capture_rbac_logger /
# test_program_releases_route.py::_capture_overview_logger idiom, duplicated
# locally per those files' own precedent of each topic file owning its scaffold.
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


def _org_access_events(records: list[logging.LogRecord]) -> list[logging.LogRecord]:
    return [r for r in records if r.getMessage() == "rbac_check_org_access"]


# =============================================================================
# OVW-04-TC-01 -- contract/response shape, ordering, no-inline-css.
# =============================================================================


@pytest.mark.asyncio
async def test_contract_ordering_and_shape_no_inline_css_tc01(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """OVW-04-TC-01: 3 seeded rows return ordered tokens DESC, each item carries
    FR-1's exact per-card shape (identity, sparkline, metrics, raw repo counts,
    href), metrics are format_number()-formatted strings, sparkline points/repo
    counts are raw ints, and no derived presentation field
    (cardStyle/avatarStyle/typeChip/momColor/momBg/repoBarStyle) is present
    anywhere in the response."""
    sparkline = [{"month": "2026-07", "tokens": 1000}, {"month": "2026-08", "tokens": 1200}]
    rows = [
        _program_summary_row(
            "program-a",
            name="Alpha",
            tokens=500_000,
            releases=3,
            features=5,
            active_contributors=4,
            repos_with_harness_installed=2,
            repos_total=3,
            monthly_token_sparkline=sparkline,
        ),
        _program_summary_row(
            "program-b",
            name="Bravo",
            tokens=2_000_000,
            releases=10,
            features=20,
            active_contributors=12,
            repos_with_harness_installed=6,
            repos_total=6,
            monthly_token_sparkline=sparkline,
        ),
        _program_summary_row(
            "program-c",
            name="Charlie",
            tokens=1_200_000,
            releases=7,
            features=9,
            active_contributors=8,
            repos_with_harness_installed=4,
            repos_total=5,
            monthly_token_sparkline=sparkline,
        ),
    ]
    app = _build_board_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="cio")
        await _seed_program_summary_rows(test_session, rows)
        resp = await _get_board(client, token=token)

    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert [item["program_id"] for item in body["items"]] == [
        "program-b",
        "program-c",
        "program-a",
    ]

    forbidden_keys = {"cardStyle", "avatarStyle", "typeChip", "momColor", "momBg", "repoBarStyle"}
    raw_body_text = resp.text
    for key in forbidden_keys:
        assert f'"{key}"' not in raw_body_text, f"derived presentation field {key} leaked on wire"

    program_b = next(item for item in body["items"] if item["program_id"] == "program-b")
    assert set(program_b.keys()) == {
        "program_id",
        "name",
        "type",
        "icon",
        "description",
        "href",
        "sparkline",
        "metrics",
        "repos_with_harness_installed",
        "repos_total",
    }
    assert program_b["href"] == "/programs/program-b"
    assert program_b["repos_with_harness_installed"] == 6
    assert isinstance(program_b["repos_with_harness_installed"], int)
    assert program_b["repos_total"] == 6

    metrics = {m["label"]: m["value"] for m in program_b["metrics"]}
    assert metrics["Total tokens"] == "2.0M"
    assert metrics["Releases via Harness"] == "10"
    assert metrics["Features via Harness"] == "20"
    assert metrics["Active contributors"] == "12"
    for m in program_b["metrics"]:
        assert isinstance(m["value"], str)

    sparkline_points = program_b["sparkline"]["points"]
    assert sparkline_points == [
        {"month": "2026-07", "tokens": 1000},
        {"month": "2026-08", "tokens": 1200},
    ]
    for point in sparkline_points:
        assert isinstance(point["tokens"], int)


# =============================================================================
# OVW-04-TC-03 -- null/missing/malformed JSONB sparkline all fall back to [].
# =============================================================================


@pytest.mark.asyncio
async def test_null_missing_malformed_sparkline_falls_back_to_empty_tc03(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """OVW-04-TC-03 (research C-2): null, missing (column default via explicit []),
    and malformed (non-list) `monthly_token_sparkline` values all render
    `sparkline.points: []` with `mom_change_percent`/`mom_direction` both null, and
    the request succeeds with 200, never a 500. The route's response model requires
    `monthly_token_sparkline` be present at the DB layer (NOT NULL JSONB column per
    `app/models/rollup.py::ProgramSummary`), so "missing" is exercised as an
    explicit `[]` default rather than an absent column -- this still exercises the
    validator's non-list/empty-list branch identically to a truly absent value."""
    rows = [
        _program_summary_row("prog-null", monthly_token_sparkline=None),
        _program_summary_row("prog-missing", monthly_token_sparkline=[]),
        _program_summary_row("prog-malformed", monthly_token_sparkline={"not": "a list"}),
    ]
    app = _build_board_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="cio")
        await _seed_program_summary_rows(test_session, rows)
        resp = await _get_board(client, token=token)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 3

    by_id = {item["program_id"]: item for item in body["items"]}
    for program_id in ("prog-null", "prog-missing", "prog-malformed"):
        item = by_id[program_id]
        assert item["sparkline"]["points"] == []
        assert item["sparkline"]["mom_change_percent"] is None
        assert item["sparkline"]["mom_direction"] is None
        # No side effect on the rest of the card -- other fields still populate.
        assert item["name"] == f"Program {program_id}"
        assert len(item["metrics"]) == 4


def test_validate_sparkline_never_raises_on_deviant_shapes() -> None:
    """OVW-04-TC-03 unit half: `_validate_sparkline` degrades to `[]` for None, a
    non-list, and a list containing a malformed element -- never raises."""
    assert _validate_sparkline(None) == []
    assert _validate_sparkline({"not": "a list"}) == []
    assert _validate_sparkline([]) == []
    assert _validate_sparkline([{"month": "2026-07"}]) == []  # missing tokens key
    assert _validate_sparkline([{"month": "2026-07", "tokens": True}]) == []  # bool excluded
    assert _validate_sparkline(["not-a-dict"]) == []
    assert _validate_sparkline([{"month": "2026-07", "tokens": 1000}]) == [("2026-07", 1000)]


# =============================================================================
# OVW-04-TC-04 -- MoM 0/1/>=2 point edge cases, including divide-by-zero guard.
# =============================================================================


@pytest.mark.asyncio
async def test_mom_edge_cases_0_1_and_2_plus_points_tc04(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """OVW-04-TC-04 (research C-3): 0-point and 1-point sparklines render
    mom_change_percent/mom_direction both null; a 2-point increasing series
    computes percent + 'up'; a 2-point flat series (within +/-0.05%) computes
    'flat'; a 2-point series with a zero previous value renders
    mom_change_percent null (divide-by-zero guard) while mom_direction still
    reflects the raw delta."""
    rows = [
        _program_summary_row("prog-0pt", monthly_token_sparkline=[]),
        _program_summary_row(
            "prog-1pt", monthly_token_sparkline=[{"month": "2026-08", "tokens": 1000}]
        ),
        _program_summary_row(
            "prog-2pt-up",
            monthly_token_sparkline=[
                {"month": "2026-07", "tokens": 1000},
                {"month": "2026-08", "tokens": 1200},
            ],
        ),
        _program_summary_row(
            "prog-2pt-flat",
            monthly_token_sparkline=[
                {"month": "2026-07", "tokens": 1000},
                {"month": "2026-08", "tokens": 1000},
            ],
        ),
        _program_summary_row(
            "prog-2pt-zero-prev",
            monthly_token_sparkline=[
                {"month": "2026-07", "tokens": 0},
                {"month": "2026-08", "tokens": 500},
            ],
        ),
    ]
    app = _build_board_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="cio")
        await _seed_program_summary_rows(test_session, rows)
        resp = await _get_board(client, token=token, page_size=100)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    by_id = {item["program_id"]: item["sparkline"] for item in body["items"]}

    assert by_id["prog-0pt"]["mom_change_percent"] is None
    assert by_id["prog-0pt"]["mom_direction"] is None

    assert by_id["prog-1pt"]["mom_change_percent"] is None
    assert by_id["prog-1pt"]["mom_direction"] is None

    assert by_id["prog-2pt-up"]["mom_change_percent"] == 20.0
    assert by_id["prog-2pt-up"]["mom_direction"] == "up"

    assert by_id["prog-2pt-flat"]["mom_direction"] == "flat"

    assert by_id["prog-2pt-zero-prev"]["mom_change_percent"] is None
    assert by_id["prog-2pt-zero-prev"]["mom_direction"] == "up"


def test_compute_mom_unit_boundaries() -> None:
    """OVW-04-TC-04 unit half: `_compute_mom` boundary table, including the
    divide-by-zero guard's up/down/flat sub-cases and the +/-0.05% threshold."""
    assert _compute_mom([]) == (None, None)
    assert _compute_mom([("2026-08", 1000)]) == (None, None)
    assert _compute_mom([("2026-07", 1000), ("2026-08", 1200)]) == (20.0, "up")
    assert _compute_mom([("2026-07", 1000), ("2026-08", 800)]) == (-20.0, "down")
    assert _compute_mom([("2026-07", 1000), ("2026-08", 1000)]) == (0.0, "flat")
    # Divide-by-zero guard: previous == 0.
    assert _compute_mom([("2026-07", 0), ("2026-08", 500)]) == (None, "up")
    assert _compute_mom([("2026-07", 0), ("2026-08", 0)]) == (None, "flat")
    prev_result = _compute_mom([("2026-07", 500), ("2026-08", 0)])
    assert prev_result[1] == "down"


# =============================================================================
# OVW-04-TC-05 -- non-CIO 403 no body; rbac_check_org_access logged both outcomes.
# =============================================================================


_NON_CIO_PERSONAS = ("architect", "developer", "product-manager", "engineering-manager")


@pytest.mark.asyncio
async def test_non_cio_403_no_body_and_rbac_check_org_access_logged_tc05(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """OVW-04-TC-05 (AC-2): cio succeeds (200); every other persona is rejected
    403 with no data body; `rbac_check_org_access` is logged once per call, with
    outcome=authorized for cio and outcome=denied for every other persona.

    Self-witnessing per the Alembic fileConfig trap: the cio call's `authorized`
    event is asserted as deliberately as the four `denied` ones, so a silently
    disabled logger (which would make every assertion here vacuously pass on
    an all-absent read) cannot slip through -- an empty event list fails this
    test outright rather than only failing a "no denial event" check."""
    await _seed_program_summary_rows(
        test_session, [_program_summary_row("program-a", tokens=100)]
    )
    app = _build_board_app(build_app, test_session)

    async with async_client_for(app) as client:
        with _capture_rbac_logger() as records:
            cio_resp = await _get_board(
                client, token=await _mint_dev_bypass_token(client, role="cio")
            )
            denied: dict[str, Response] = {}
            for persona in _NON_CIO_PERSONAS:
                denied[persona] = await _get_board(
                    client, token=await _mint_dev_bypass_token(client, role=persona)
                )

    assert cio_resp.status_code == 200, cio_resp.text
    cio_body = cio_resp.json()
    assert "items" in cio_body

    for persona, resp in denied.items():
        assert resp.status_code == 403, f"{persona} should be denied"
        body = resp.json()
        assert set(body.keys()) == {"error"}, f"{persona} leaked a data body: {body}"
        assert "items" not in body

    events = _org_access_events(records)
    assert len(events) == 5, f"expected one rbac_check_org_access event per call, got {len(events)}"

    by_persona: dict[str, logging.LogRecord] = {}
    for record in events:
        persona_value: object = getattr(record, "persona", None)
        assert isinstance(persona_value, str), (
            f"rbac_check_org_access event carries no persona: {record!r}"
        )
        by_persona[persona_value] = record

    assert set(by_persona) == {"cio", *_NON_CIO_PERSONAS}
    assert getattr(by_persona["cio"], "outcome", None) == "authorized"
    for persona in _NON_CIO_PERSONAS:
        assert getattr(by_persona[persona], "outcome", None) == "denied"
        assert getattr(by_persona[persona], "user_id", None)


# =============================================================================
# OVW-04-TC-08 -- empty org returns 200 with empty items, not an error.
# =============================================================================


@pytest.mark.asyncio
async def test_empty_org_returns_200_empty_items_tc08(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """OVW-04-TC-08 (AC-5): zero `program_summary` rows -> 200 with
    {items: [], page: 1, page_size: 20, total: 0}, never a 404/500."""
    app = _build_board_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="cio")
        resp = await _get_board(client, token=token)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"items": [], "page": 1, "page_size": 20, "total": 0}


# =============================================================================
# OVW-04-TC-09 -- pagination defaults; clamp above 100 (never 422).
# =============================================================================


@pytest.mark.asyncio
async def test_pagination_default_and_clamp_above_100_tc09(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """OVW-04-TC-09 (FR-2/AC-6): omitting params defaults to page=1/page_size=20
    (20 items, total=150); page_size=500 clamps to 100 (never 422-rejected),
    returning 100 items. Ordering (tokens DESC) is preserved across both calls."""
    rows = [
        _program_summary_row(f"program-{i:03d}", tokens=i)
        for i in range(150)
    ]
    app = _build_board_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="cio")
        await _seed_program_summary_rows(test_session, rows)

        default_resp = await _get_board(client, token=token)
        oversized_resp = await _get_board(client, token=token, page_size=500)

    assert default_resp.status_code == 200, default_resp.text
    default_body = default_resp.json()
    assert default_body["page"] == 1
    assert default_body["page_size"] == 20
    assert len(default_body["items"]) == 20
    assert default_body["total"] == 150

    default_program_ids = [item["program_id"] for item in default_body["items"]]
    assert default_program_ids == [f"program-{i:03d}" for i in range(149, 129, -1)]

    assert oversized_resp.status_code == 200, oversized_resp.text
    assert oversized_resp.status_code != 422
    oversized_body = oversized_resp.json()
    assert oversized_body["page_size"] == 100
    assert len(oversized_body["items"]) == 100


# =============================================================================
# OVW-04-TC-10 -- page<1 / page_size<1 rejected with 422.
# =============================================================================


@pytest.mark.asyncio
async def test_page_and_page_size_below_1_rejected_422_tc10(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """OVW-04-TC-10 (FR-2): page=0 and page_size=0 are both rejected 422 per the
    ge=1 constraint, never silently coerced."""
    await _seed_program_summary_rows(
        test_session, [_program_summary_row("program-a", tokens=1)]
    )
    app = _build_board_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="cio")
        page_zero_resp = await _get_board(client, token=token, page=0)
        page_size_zero_resp = await _get_board(client, token=token, page_size=0)

    assert page_zero_resp.status_code == 422
    assert page_size_zero_resp.status_code == 422


# =============================================================================
# OVW-04-TC-02 / TC-11 -- performance: indexed order, single query, p95 < 300ms.
# =============================================================================

_PERF_SEED_ROW_COUNT = 200
_PERF_MEASURED_REQUESTS = 20
_PERF_P95_BUDGET_MS = 300.0


def _percentile(sorted_values_ms: list[float], pct: float) -> float:
    """Nearest-rank percentile over an already-sorted list, in milliseconds.
    Mirrors `tests/perf/test_program_releases_perf.py::_percentile` (deterministic,
    dependency-free; per-file precedent, not shared/imported)."""
    import math

    n = len(sorted_values_ms)
    rank = math.ceil(pct * n)
    return sorted_values_ms[rank - 1]


async def _seed_perf_rows(test_session: AsyncSession, test_engine: AsyncEngine) -> None:
    rows = [
        _program_summary_row(f"program-perf-{i:04d}", tokens=1000 + i)
        for i in range(_PERF_SEED_ROW_COUNT)
    ]
    await _seed_program_summary_rows(test_session, rows)
    async with test_engine.begin() as conn:
        await conn.execute(text("ANALYZE program_summary"))


@pytest.mark.asyncio
async def test_program_board_p95_latency_under_budget_at_default_page_size_tc02_tc11(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """OVW-04-TC-02 / TC-11 (latency half): 200 seeded rows, 20 sequential
    requests at default page_size=20 -- p95 latency stays under the 300ms
    budget. Honest measurement: the real number is printed and asserted, never
    hidden by loosening the budget or seeding fewer rows."""
    await _seed_perf_rows(test_session, test_engine)
    app = _build_board_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="cio")

        latencies_ms: list[float] = []
        for _ in range(_PERF_MEASURED_REQUESTS):
            started = time.perf_counter()
            resp = await _get_board(client, token=token)
            elapsed_ms = (time.perf_counter() - started) * 1000
            assert resp.status_code == 200, resp.text
            latencies_ms.append(elapsed_ms)

    latencies_ms.sort()
    p95 = _percentile(latencies_ms, 0.95)

    print(
        f"\nOVW-04-TC-02/TC-11 baseline -- program-board (page_size=20, "
        f"{_PERF_SEED_ROW_COUNT} seeded rows) p95={p95:.2f}ms across "
        f"{_PERF_MEASURED_REQUESTS} requests (budget {_PERF_P95_BUDGET_MS}ms)"
    )
    assert p95 < _PERF_P95_BUDGET_MS, (
        f"GET /api/overview/program-board p95 latency {p95:.2f}ms exceeded the "
        f"OVW-04-TC-02/TC-11 budget of {_PERF_P95_BUDGET_MS}ms across "
        f"{_PERF_MEASURED_REQUESTS} measured requests against {_PERF_SEED_ROW_COUNT} "
        "seeded rows. Do not relax this budget; report the measured p95 for "
        "escalation/optimization."
    )


@pytest.mark.asyncio
async def test_program_board_query_uses_tokens_index_not_seq_scan_tc02(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
) -> None:
    """OVW-04-TC-02 (index-usage half, research C-1): `EXPLAIN ANALYZE` on the
    service's actual query shape (`fetch_program_board`'s row-fetch statement,
    reproduced here verbatim via raw SQL) shows the planner using
    `ix_program_summary_tokens`, not a sequential scan on `program_summary`, at
    200 seeded rows with fresh planner statistics."""
    await _seed_perf_rows(test_session, test_engine)

    async with test_engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                EXPLAIN ANALYZE
                SELECT * FROM program_summary
                ORDER BY tokens DESC
                OFFSET :offset LIMIT :limit
                """
            ),
            {"offset": 0, "limit": 20},
        )
        plan_lines = [row[0] for row in result.fetchall()]

    plan_text = "\n".join(plan_lines)
    print(f"\nOVW-04-TC-02 EXPLAIN ANALYZE plan:\n{plan_text}")

    assert "ix_program_summary_tokens" in plan_text, (
        "EXPLAIN ANALYZE did not reference ix_program_summary_tokens (research C-1) "
        f"at {_PERF_SEED_ROW_COUNT} seeded rows. Do not weaken this assertion; "
        f"investigate the real cause (e.g. stale planner statistics) instead. "
        f"Plan:\n{plan_text}"
    )
    assert "Seq Scan on program_summary" not in plan_text, (
        f"EXPLAIN ANALYZE shows a sequential scan on program_summary at "
        f"{_PERF_SEED_ROW_COUNT} seeded rows -- the tokens index is not being used. "
        f"Do not weaken this assertion; investigate the real cause instead. "
        f"Plan:\n{plan_text}"
    )


@pytest.mark.asyncio
async def test_program_board_single_query_no_n_plus_one_tc11(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """OVW-04-TC-11 (query-budget half): exactly one indexed-order SELECT plus
    the paired COUNT(*) run against `program_summary` per request -- no
    per-card fan-out (`fetch_program_board`'s documented 2-query pattern), by
    counting the actual SQL statements sent to the driver."""
    await _seed_program_summary_rows(
        test_session,
        [_program_summary_row(f"program-{i:03d}", tokens=i) for i in range(30)],
    )
    app = _build_board_app(build_app, test_session)

    executed_statements: list[str] = []

    from sqlalchemy import event

    def _before_cursor_execute(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        if "program_summary" in statement:
            executed_statements.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        async with async_client_for(app) as client:
            token = await _mint_dev_bypass_token(client, role="cio")
            resp = await _get_board(client, token=token)
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", _before_cursor_execute)

    assert resp.status_code == 200, resp.text
    # Exactly 2 statements against program_summary: the row fetch + the COUNT(*)
    # (fetch_program_board's documented paired-query pattern) -- no N+1 fan-out
    # per card.
    assert len(executed_statements) == 2, (
        f"expected exactly 2 program_summary statements (row fetch + COUNT), got "
        f"{len(executed_statements)}: {executed_statements}"
    )
