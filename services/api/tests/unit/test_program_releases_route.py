"""Route-level tests for `GET /api/overview/program-detail/{program_id}/releases`
(`app/api/overview.py::get_program_releases`) -- PGD-03-TC-01, TC-02, TC-05, TC-06,
TC-07, TC-08, TC-09, TC-10, TC-11, TC-17, TC-18, TC-19, TC-21, TC-22
(`docs/test-cases/PGD-03.json`).

Mirrors `tests/unit/test_program_token_trend_route.py`'s scaffold (`build_app`/
`async_client_for`/`migrated_db`/`test_session` from `tests/conftest.py`,
`POST /auth/dev-bypass` bearer tokens) exactly: this route's only RBAC call is
`program_visibility` (`app/core/rbac.py`), a hardcoded open-aggregate no-op that never
resolves a persona, so a dev-bypass token (hermetic, no JWKS/RSA fixture needed) is
sufficient for every case here, including the multi-persona TC-08.

No ingest path exists for `program_releases` (DECISIONS.md D-06) -- rows are seeded
directly via the ORM, bypassing rollup rebuild entirely.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.rollup import ProgramReleases, ProgramSummary
from tests.conftest import AlembicRunner

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]


# -----------------------------------------------------------------------------
# App + DB-override scaffold. Mirrors test_program_token_trend_route.py's
# _build_token_trend_app / _db_override precedent.
# -----------------------------------------------------------------------------


def _db_override(session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _get_db() -> AsyncIterator[AsyncSession]:
        yield session

    return _get_db


def _build_releases_app(
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


async def _get_releases(
    client: AsyncClient,
    program_id: str,
    *,
    token: str | None,
    range_param: str | None = "__omit__",
    offset: int | None = None,
    limit: int | None = None,
) -> Response:
    """Issue the releases GET. `range_param="__omit__"` (default) sends no `range`
    query param at all; any other value (including `""`) sends it."""
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    params: dict[str, Any] = {} if range_param == "__omit__" else {"range": range_param}
    if offset is not None:
        params["offset"] = offset
    if limit is not None:
        params["limit"] = limit
    return await client.get(
        f"/api/overview/program-detail/{program_id}/releases",
        headers=headers,
        params=params,
    )


# -----------------------------------------------------------------------------
# Seed helpers.
# -----------------------------------------------------------------------------

_KIND_MAP: dict[str, str] = {
    "Feature release": "#1f8a5b",
    "Patch release": "#2a6fdb",
    "Hotfix": "#d1495b",
}


def _release_row(
    *,
    program_id: str,
    days_ago: int,
    now: datetime,
    version: str = "v1.0.0",
    release_type: str = "Feature release",
    story_count: int = 3,
    pr_count: int = 5,
) -> dict[str, Any]:
    """One `program_releases` row with every NOT NULL column
    (`app/models/rollup.py::ProgramReleases`) explicitly set."""
    return {
        "id": str(uuid.uuid4()),
        "program_id": program_id,
        "version": version,
        "type": release_type,
        "date": now - timedelta(days=days_ago),
        "story_count": story_count,
        "pr_count": pr_count,
        "as_of_timestamp": now,
    }


async def _seed_releases(
    test_session: AsyncSession, rows: list[dict[str, Any]]
) -> None:
    await test_session.execute(sa.insert(ProgramReleases), rows)
    await test_session.commit()


async def _seed_program_summary(
    test_session: AsyncSession, program_id: str, *, program_type: str = "Migration"
) -> None:
    """Minimal `program_summary` row so the route's 404-vs-200 lookup passes and
    `_tag_colors_for_program` resolves via `program_type`."""
    now = datetime.now(UTC)
    row = ProgramSummary(
        id=str(uuid.uuid4()),
        program_id=program_id,
        name=f"Program {program_id}",
        icon="icon",
        type=program_type,
        description="desc",
        monthly_token_sparkline=[],
        tokens=0,
        releases=0,
        features=0,
        active_contributors=0,
        repos_with_harness_installed=0,
        repos_total=0,
        commands_executed=0,
        lines_of_code_generated=0,
        user_stories_delivered=0,
        as_of_timestamp=now,
    )
    test_session.add(row)
    await test_session.commit()


# -----------------------------------------------------------------------------
# Log capture -- mirrors test_personal_usage.py's `_RecordCapturingHandler`/
# `_capture_logger` idiom, duplicated locally per that file's own precedent.
# Captures `app.api.overview`'s named logger (`program_releases_fetched`
# completion event), NOT `app.core.rbac` (no event to capture there -- see
# TC-21 test below).
# -----------------------------------------------------------------------------


class _RecordCapturingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _capture_overview_logger(level: int = logging.INFO) -> Iterator[list[logging.LogRecord]]:
    logger = logging.getLogger("app.api.overview")
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
# PGD-03-TC-01 -- default query params: 30d window, offset 0, limit 20, full
# row shape.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_params_30d_offset0_limit20_full_shape_tc01(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-03-TC-01: omitting all query params defaults to range=30d, offset=0,
    limit=20; rows shaped exactly {ver, label, dot, date, stories, prs}, with
    relTotal/tagColor/tagBg at top level; only in-30d rows returned."""
    program_id = "prog-001"
    now = datetime.now(UTC)
    app = _build_releases_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        await _seed_program_summary(test_session, program_id)
        # 25 rows within 30d, 3 rows outside (spanning >90 days per precondition).
        in_window = [
            _release_row(program_id=program_id, days_ago=d, now=now) for d in range(0, 25)
        ]
        out_of_window = [
            _release_row(program_id=program_id, days_ago=d, now=now) for d in (100, 150, 200)
        ]
        await _seed_releases(test_session, in_window + out_of_window)

        resp = await _get_releases(client, program_id, token=token, range_param="__omit__")

    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert len(body["items"]) <= 20
    assert len(body["items"]) == 20  # default limit
    assert body["relTotal"] == "25"

    for item in body["items"]:
        assert set(item.keys()) == {"ver", "label", "dot", "date", "stories", "prs"}
        assert isinstance(item["stories"], str)
        assert isinstance(item["prs"], str)
        assert item["date"].split()[0] in {
            "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
        }
        # "Jul 15" has no 4-digit year component.
        assert not any(part.isdigit() and len(part) == 4 for part in item["date"].split())


# -----------------------------------------------------------------------------
# PGD-03-TC-02 -- tagColor/tagBg hoisted to top level, absent per-row.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tag_color_bg_hoisted_top_level_not_per_row_tc02(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-03-TC-02 (FR-2): tagColor/tagBg are top-level response fields, never
    duplicated per row, even with mixed release types seeded."""
    program_id = "prog-001"
    now = datetime.now(UTC)
    app = _build_releases_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        await _seed_program_summary(
            test_session, program_id, program_type="Greenfield feature development"
        )
        await _seed_releases(
            test_session,
            [
                _release_row(
                    program_id=program_id, days_ago=1, now=now, release_type="Feature release"
                ),
                _release_row(
                    program_id=program_id, days_ago=2, now=now, release_type="Patch release"
                ),
                _release_row(program_id=program_id, days_ago=3, now=now, release_type="Hotfix"),
            ],
        )

        resp = await _get_releases(client, program_id, token=token, range_param="30d")

    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "tagColor" in body
    assert "tagBg" in body
    assert body["tagColor"] == "#1f8a5b"
    assert body["tagBg"] == "#e8f5ee"

    for item in body["items"]:
        assert "tagColor" not in item
        assert "tagBg" not in item


# -----------------------------------------------------------------------------
# PGD-03-TC-05 -- limit above 50 clamped to 50, never rejected.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_limit_above_50_clamped_not_rejected_tc05(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-03-TC-05 (FR-5): limit=200 is clamped to 50 rows, status 200 -- the
    single most important pagination assertion (never a 422)."""
    program_id = "prog-001"
    now = datetime.now(UTC)
    app = _build_releases_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        await _seed_program_summary(test_session, program_id)
        # 80 releases, all within the 30d window (days_ago 0-29, repeated) so the
        # clamp (not the range filter) is what bounds the returned row count.
        await _seed_releases(
            test_session,
            [_release_row(program_id=program_id, days_ago=d % 30, now=now) for d in range(0, 80)],
        )

        resp = await _get_releases(
            client, program_id, token=token, range_param="30d", limit=200
        )

    assert resp.status_code == 200, resp.text
    assert resp.status_code != 422
    body = resp.json()
    assert len(body["items"]) == 50
    assert body["relTotal"] == "80"


# -----------------------------------------------------------------------------
# PGD-03-TC-06 -- limit exactly 50 passed through unclamped.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_limit_exactly_50_accepted_unclamped_tc06(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-03-TC-06 (FR-5): limit=50, the inclusive boundary, is honored exactly."""
    program_id = "prog-001"
    now = datetime.now(UTC)
    app = _build_releases_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        await _seed_program_summary(test_session, program_id)
        # 60 releases, all within the 30d window (days_ago 0-29, repeated) so the
        # boundary limit=50 -- not the range filter -- bounds the returned rows.
        await _seed_releases(
            test_session,
            [_release_row(program_id=program_id, days_ago=d % 30, now=now) for d in range(0, 60)],
        )

        resp = await _get_releases(
            client, program_id, token=token, range_param="30d", limit=50
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 50


# -----------------------------------------------------------------------------
# PGD-03-TC-07 -- invalid range -> explicit 400, never FastAPI's default 422.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_range_returns_explicit_400_not_422_tc07(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-03-TC-07 (AC-3): range=1y 400s via the explicit validate_range() check,
    never FastAPI's default 422 -- asserts the exact status and error body."""
    program_id = "prog-001"
    app = _build_releases_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        resp = await _get_releases(client, program_id, token=token, range_param="1y")

    assert resp.status_code == 400
    assert resp.status_code != 422
    assert resp.json() == {
        "error": {"code": "http_400", "message": "invalid_range", "details": None}
    }


# -----------------------------------------------------------------------------
# PGD-03-TC-08 -- cross-persona byte-identical response.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_byte_identical_response_across_personas_tc08(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-03-TC-08 (AC-4): developer and cio sessions requesting the same
    program/range get HTTP 200 and byte-identical response bodies."""
    program_id = "prog-001"
    now = datetime.now(UTC)
    app = _build_releases_app(build_app, test_session)

    async with async_client_for(app) as client:
        await _seed_program_summary(test_session, program_id)
        await _seed_releases(
            test_session,
            [_release_row(program_id=program_id, days_ago=d, now=now) for d in range(0, 10)],
        )

        dev_token = await _mint_dev_bypass_token(client, role="developer")
        cio_token = await _mint_dev_bypass_token(client, role="cio")

        dev_resp = await _get_releases(client, program_id, token=dev_token, range_param="30d")
        cio_resp = await _get_releases(client, program_id, token=cio_token, range_param="30d")

    assert dev_resp.status_code == 200, dev_resp.text
    assert cio_resp.status_code == 200, cio_resp.text
    assert dev_resp.content == cio_resp.content


# -----------------------------------------------------------------------------
# PGD-03-TC-09 -- any authenticated persona succeeds regardless of program
# membership scoping.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_access_granted_regardless_of_program_membership_tc09(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-03-TC-09 (AC-4): a session not scoped to prog-002 via session.programs
    still gets 200 -- program_visibility never gates by membership."""
    program_id = "prog-002"
    now = datetime.now(UTC)
    app = _build_releases_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        await _seed_program_summary(test_session, program_id)
        await _seed_releases(
            test_session,
            [_release_row(program_id=program_id, days_ago=d, now=now) for d in range(0, 5)],
        )

        resp = await _get_releases(client, program_id, token=token, range_param="30d")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 5


# -----------------------------------------------------------------------------
# PGD-03-TC-10 -- missing bearer token -> 401.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_bearer_token_returns_401_tc10(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-03-TC-10 (AC-5): no Authorization header -> 401."""
    program_id = "prog-001"
    app = _build_releases_app(build_app, test_session)

    async with async_client_for(app) as client:
        resp = await _get_releases(client, program_id, token=None, range_param="30d")

    assert resp.status_code == 401


# -----------------------------------------------------------------------------
# PGD-03-TC-11 -- unknown program_id -> 404 with JSON error body.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_program_id_returns_404_json_body_tc11(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-03-TC-11 (AC-6): a program_id absent from program_summary 404s with a
    JSON error body, matching the PGD-01 sibling endpoint's convention."""
    app = _build_releases_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        resp = await _get_releases(
            client, "nonexistent-999", token=token, range_param="30d"
        )

    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["message"] == "program not found"


# -----------------------------------------------------------------------------
# PGD-03-TC-17 -- relTotal window parity across all three range values.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rel_total_window_parity_across_ranges_tc17(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-03-TC-17 (FR-6): relTotal for each range equals the count of releases
    actually within that window -- 3 at 2d, 5 at 20d, 10 at 60d, 20 at 150d.
    range=7d -> relTotal 3; range=30d -> relTotal 8; range=90d -> relTotal 18
    (150d-old releases excluded from both relTotal and rows in every case)."""
    program_id = "prog-001"
    now = datetime.now(UTC)
    app = _build_releases_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        await _seed_program_summary(test_session, program_id)

        rows = (
            [_release_row(program_id=program_id, days_ago=2, now=now) for _ in range(3)]
            + [_release_row(program_id=program_id, days_ago=20, now=now) for _ in range(5)]
            + [_release_row(program_id=program_id, days_ago=60, now=now) for _ in range(10)]
            + [_release_row(program_id=program_id, days_ago=150, now=now) for _ in range(20)]
        )
        await _seed_releases(test_session, rows)

        resp_7d = await _get_releases(
            client, program_id, token=token, range_param="7d", limit=50
        )
        resp_30d = await _get_releases(
            client, program_id, token=token, range_param="30d", limit=50
        )
        resp_90d = await _get_releases(
            client, program_id, token=token, range_param="90d", limit=50
        )

    assert resp_7d.status_code == 200, resp_7d.text
    assert resp_30d.status_code == 200, resp_30d.text
    assert resp_90d.status_code == 200, resp_90d.text

    body_7d, body_30d, body_90d = resp_7d.json(), resp_30d.json(), resp_90d.json()

    assert body_7d["relTotal"] == "3"
    assert len(body_7d["items"]) == 3

    assert body_30d["relTotal"] == "8"
    assert len(body_30d["items"]) == 8

    assert body_90d["relTotal"] == "18"
    assert len(body_90d["items"]) == 18


# -----------------------------------------------------------------------------
# PGD-03-TC-18 -- relTotal reflects full window count even when limit
# truncates rows.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rel_total_independent_of_pagination_limit_tc18(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-03-TC-18 (FR-6): 35 releases within 30d, limit=10 -> exactly 10 rows
    but relTotal == 35, not 10."""
    program_id = "prog-001"
    now = datetime.now(UTC)
    app = _build_releases_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        await _seed_program_summary(test_session, program_id)
        # 35 releases, all within the 30d window (days_ago 0-29, repeated) so
        # relTotal reflects the full in-window count, not a range-filtered subset.
        await _seed_releases(
            test_session,
            [_release_row(program_id=program_id, days_ago=d % 30, now=now) for d in range(0, 35)],
        )

        resp = await _get_releases(
            client, program_id, token=token, range_param="30d", limit=10, offset=0
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 10
    assert body["relTotal"] == "35"


# -----------------------------------------------------------------------------
# PGD-03-TC-19 -- date field pre-formatted without a year.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_date_field_preformatted_without_year_tc19(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-03-TC-19 (FR-2): a release dated 2026-07-15 serializes date as
    'Jul 15' exactly, with no year present."""
    program_id = "prog-001"
    release_date = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    now = datetime.now(UTC)
    app = _build_releases_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        await _seed_program_summary(test_session, program_id)
        row = _release_row(program_id=program_id, days_ago=0, now=now, version="v9.9.9")
        row["date"] = release_date
        await _seed_releases(test_session, [row])

        resp = await _get_releases(client, program_id, token=token, range_param="90d")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    matching = [item for item in body["items"] if item["ver"] == "v9.9.9"]
    assert len(matching) == 1
    assert matching[0]["date"] == "Jul 15"


# -----------------------------------------------------------------------------
# PGD-03-TC-21 -- program_visibility is server-side, open-aggregate, and emits
# no dedicated audit event.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_program_visibility_server_side_no_dedicated_audit_event_tc21(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-03-TC-21 (NFR-security): an authenticated request succeeds (200)
    regardless of persona/program membership, and no org_access/
    individual_view_denied/member_view_denied event is emitted for this
    endpoint's program_visibility check. An unauthenticated request is
    rejected server-side (401), proving enforcement is not UI-only.

    Robust to the known Alembic fileConfig trap (disables every `app.*`
    logger process-wide once `test_migrations.py` has run in this session):
    this test first POSITIVELY asserts the `program_releases_fetched`
    completion log IS captured on the SAME logger family being checked for
    absence, proving the capture mechanism is live, before asserting the
    audit events are absent from those same captured records.
    """
    program_id = "prog-001"
    now = datetime.now(UTC)
    app = _build_releases_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        await _seed_program_summary(test_session, program_id)
        await _seed_releases(
            test_session,
            [_release_row(program_id=program_id, days_ago=1, now=now)],
        )

        with _capture_overview_logger() as records:
            ok_resp = await _get_releases(
                client, program_id, token=token, range_param="30d"
            )

        no_auth_resp = await _get_releases(
            client, program_id, token=None, range_param="30d"
        )

    assert ok_resp.status_code == 200, ok_resp.text
    assert no_auth_resp.status_code == 401

    # Capture mechanism is live: the route's own completion log fired.
    completion_events = [r for r in records if r.getMessage() == "program_releases_fetched"]
    assert len(completion_events) == 1

    # No dedicated audit event for the open-aggregate program_visibility check.
    denial_event_names = {"org_access", "individual_view_denied", "member_view_denied"}
    audit_events = [r for r in records if r.getMessage() in denial_event_names]
    assert audit_events == []


# -----------------------------------------------------------------------------
# PGD-03-TC-22 -- structured request log with required fields.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_structured_request_log_has_required_fields_tc22(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-03-TC-22 (NFR-observability): a completed request emits a structured
    log line containing method, path, program_id, range, offset, limit, status,
    latency."""
    program_id = "prog-001"
    now = datetime.now(UTC)
    app = _build_releases_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        await _seed_program_summary(test_session, program_id)
        await _seed_releases(
            test_session,
            [_release_row(program_id=program_id, days_ago=1, now=now)],
        )

        with _capture_overview_logger() as records:
            resp = await _get_releases(
                client, program_id, token=token, range_param="30d", offset=0, limit=20
            )

    assert resp.status_code == 200, resp.text

    completion_events = [r for r in records if r.getMessage() == "program_releases_fetched"]
    assert len(completion_events) == 1
    record = completion_events[0]

    assert record.__dict__["method"] == "GET"
    assert "path" in record.__dict__
    assert record.__dict__["program_id"] == program_id
    assert record.__dict__["range"] == "30d"
    assert record.__dict__["offset"] == 0
    assert record.__dict__["limit"] == 20
    assert record.__dict__["status"] == 200
    assert "latency_ms" in record.__dict__
