"""Route-level tests for `GET /api/overview/program-detail/{program_id}/team`
(`app/api/overview.py::get_program_team`) -- PGD-05-TC-01, TC-02, TC-03, TC-04,
TC-05, TC-07, TC-08, TC-09, TC-17 (`docs/test-cases/PGD-05.json`).

Mirrors `tests/unit/test_program_commands_route.py` / `test_program_releases_route.py`'s
scaffold (`build_app`/`async_client_for`/`migrated_db`/`test_session` from
`tests/conftest.py`, `POST /auth/dev-bypass` bearer tokens) exactly: this route's only
RBAC call is `program_visibility` (`app/core/rbac.py`), a hardcoded open-aggregate no-op
that never resolves a persona, so a dev-bypass token (hermetic, no JWKS/RSA fixture
needed) is sufficient for every case here, including the multi-persona TC-07/TC-09.

Rows are seeded directly via the ORM into both `program_members` (roster identity
snapshot) and `usage_events` (range-scoped metrics) -- `fetch_program_team()` merges
the two with exactly two SELECTs in Python (D-01), never a SQL join. `usage_events` has
no column literally named `tokens`; the service sums `UsageEvent.total`, so fixtures
here seed `total` and assert against the wire field `tokens`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.ingestion import UsageEvent
from app.models.rollup import ProgramMembers
from tests.conftest import AlembicRunner

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]


# -----------------------------------------------------------------------------
# App + DB-override scaffold. Mirrors test_program_commands_route.py's
# _build_commands_app / _db_override precedent.
# -----------------------------------------------------------------------------


def _db_override(session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _get_db() -> AsyncIterator[AsyncSession]:
        yield session

    return _get_db


def _build_team_app(
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


async def _get_team(
    client: AsyncClient,
    program_id: str,
    *,
    token: str | None,
    range_param: str | None = "__omit__",
) -> Response:
    """Issue the team GET. `range_param="__omit__"` (default) sends no `range`
    query param at all; any other value (including `""`) sends it."""
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    params: dict[str, Any] = {} if range_param == "__omit__" else {"range": range_param}
    return await client.get(
        f"/api/overview/program-detail/{program_id}/team",
        headers=headers,
        params=params,
    )


# -----------------------------------------------------------------------------
# Seed helpers.
# -----------------------------------------------------------------------------


def _member_row(
    *,
    program_id: str,
    user_id: str,
    name: str,
    role: str,
    now: datetime,
) -> dict[str, Any]:
    """One `program_members` roster row with every NOT NULL column
    (`app/models/rollup.py::ProgramMembers`) explicitly set. `sessions`/`tokens`/
    `last_active_date` here are the roster snapshot's own columns -- unrelated to
    (and never read by) `fetch_program_team()`'s range-scoped `usage_events`
    aggregate, which is the sole source of the wire `sessions`/`tokens` fields."""
    return {
        "id": str(uuid.uuid4()),
        "program_id": program_id,
        "user_id": user_id,
        "name": name,
        "role": role,
        "sessions": 0,
        "tokens": 0,
        "last_active_date": now,
        "as_of_timestamp": now,
    }


async def _seed_members(test_session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    await test_session.execute(sa.insert(ProgramMembers), rows)
    await test_session.commit()


def _usage_event_row(
    *,
    program_id: str,
    days_ago: int,
    now: datetime,
    user: str,
    total: int = 100,
    session_id: str | None = None,
) -> dict[str, Any]:
    """One `usage_events` row with every NOT NULL column (`app/models/ingestion.py::
    UsageEvent`) explicitly set. `total` is the column the service sums for the
    wire `tokens` field (no literal `tokens` column exists)."""
    ts = now - timedelta(days=days_ago)
    return {
        "id": str(uuid.uuid4()),
        "program_id": program_id,
        "ts": ts,
        "cmd_ts": ts,
        "user": user,
        "session_id": session_id or str(uuid.uuid4()),
        "kind": "command",
        "command": "/build",
        "feature": None,
        "duration_seconds": 1,
        "outcome": "success",
        "intervention_count": None,
        "files_created": None,
        "files_modified": None,
        "lines_added": None,
        "tool_rejections": None,
        "input_tokens": None,
        "output_tokens": None,
        "cache_read_tokens": None,
        "cache_write_tokens": None,
        "total": total,
        "models": None,
        "source": None,
    }


async def _seed_usage_events(test_session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    await test_session.execute(sa.insert(UsageEvent), rows)
    await test_session.commit()


# -----------------------------------------------------------------------------
# PGD-05-TC-01 -- one row per active member with all five required fields.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_row_per_active_member_with_required_fields_tc01(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-05-TC-01 (AC-1): 3 distinct members active within 30d each produce
    one row with member_id, member_name, role, sessions, tokens,
    avg_tokens_per_session (D-06 amends in member_id)."""
    program_id = "prog-001"
    now = datetime.now(UTC)
    app = _build_team_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        await _seed_members(
            test_session,
            [
                _member_row(
                    program_id=program_id, user_id="u-a", name="Alice A", role="Developer", now=now
                ),
                _member_row(
                    program_id=program_id, user_id="u-b", name="Bob B", role="QA Engineer", now=now
                ),
                _member_row(
                    program_id=program_id,
                    user_id="u-c",
                    name="Cara C",
                    role="Architect",
                    now=now,
                ),
            ],
        )
        await _seed_usage_events(
            test_session,
            [
                _usage_event_row(program_id=program_id, days_ago=1, now=now, user="u-a"),
                _usage_event_row(program_id=program_id, days_ago=2, now=now, user="u-b"),
                _usage_event_row(program_id=program_id, days_ago=3, now=now, user="u-c"),
            ],
        )

        resp = await _get_team(client, program_id, token=token, range_param="30d")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 3
    for item in body["items"]:
        assert set(item.keys()) == {
            "member_id",
            "member_name",
            "role",
            "sessions",
            "tokens",
            "avg_tokens_per_session",
        }


# -----------------------------------------------------------------------------
# PGD-05-TC-02 -- omitted range defaults to 30d.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_omitted_range_defaults_to_30d_tc02(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-05-TC-02 (AC-2): omitting `range` entirely behaves identically to an
    explicit `?range=30d` -- byte-identical response bodies."""
    program_id = "prog-001"
    now = datetime.now(UTC)
    app = _build_team_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        await _seed_members(
            test_session,
            [
                _member_row(
                    program_id=program_id, user_id="u-a", name="Alice A", role="Developer", now=now
                )
            ],
        )
        await _seed_usage_events(
            test_session,
            [
                _usage_event_row(program_id=program_id, days_ago=d, now=now, user="u-a")
                for d in range(0, 10)
            ],
        )

        omitted_resp = await _get_team(client, program_id, token=token, range_param="__omit__")
        explicit_resp = await _get_team(client, program_id, token=token, range_param="30d")

    assert omitted_resp.status_code == 200, omitted_resp.text
    assert explicit_resp.status_code == 200, explicit_resp.text
    assert omitted_resp.content == explicit_resp.content


# -----------------------------------------------------------------------------
# PGD-05-TC-03 -- range=7d scopes sessions/tokens/avg to the 7-day window.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_range_7d_scopes_metrics_to_7_day_window_tc03(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-05-TC-03 (AC-3): member-A's sessions/tokens for range=7d reflect only
    events within the last 7 days -- an out-of-window event (days_ago=20) is
    excluded from both counts."""
    program_id = "prog-multi-window"
    now = datetime.now(UTC)
    app = _build_team_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        await _seed_members(
            test_session,
            [
                _member_row(
                    program_id=program_id,
                    user_id="u-a",
                    name="Member A",
                    role="Developer",
                    now=now,
                )
            ],
        )
        await _seed_usage_events(
            test_session,
            [
                # In-window (7d): 2 sessions, 300 tokens total.
                _usage_event_row(
                    program_id=program_id, days_ago=1, now=now, user="u-a", total=100,
                    session_id="s1",
                ),
                _usage_event_row(
                    program_id=program_id, days_ago=2, now=now, user="u-a", total=200,
                    session_id="s2",
                ),
                # Out-of-window for 7d: must not be counted.
                _usage_event_row(
                    program_id=program_id, days_ago=20, now=now, user="u-a", total=9000,
                    session_id="s3",
                ),
            ],
        )

        resp = await _get_team(client, program_id, token=token, range_param="7d")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 1
    row = body["items"][0]
    assert row["sessions"] == 2
    assert row["tokens"] == 300
    assert row["avg_tokens_per_session"] == 150


# -----------------------------------------------------------------------------
# PGD-05-TC-04 -- range-scoping reads usage_events per-window, not a static
# snapshot: 30d vs 90d differ.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_30d_vs_90d_differ_proving_per_window_read_tc04(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-05-TC-04 (AC-3): member-A's tokens for range=30d differ from
    range=90d because an event at days_ago=60 falls inside the 90d window but
    outside the 30d window."""
    program_id = "prog-multi-window"
    now = datetime.now(UTC)
    app = _build_team_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        await _seed_members(
            test_session,
            [
                _member_row(
                    program_id=program_id,
                    user_id="u-a",
                    name="Member A",
                    role="Developer",
                    now=now,
                )
            ],
        )
        await _seed_usage_events(
            test_session,
            [
                _usage_event_row(
                    program_id=program_id,
                    days_ago=1,
                    now=now,
                    user="u-a",
                    total=100,
                    session_id="s1",
                ),
                _usage_event_row(
                    program_id=program_id,
                    days_ago=60,
                    now=now,
                    user="u-a",
                    total=500,
                    session_id="s2",
                ),
            ],
        )

        resp_30d = await _get_team(client, program_id, token=token, range_param="30d")
        resp_90d = await _get_team(client, program_id, token=token, range_param="90d")

    assert resp_30d.status_code == 200, resp_30d.text
    assert resp_90d.status_code == 200, resp_90d.text
    tokens_30d = resp_30d.json()["items"][0]["tokens"]
    tokens_90d = resp_90d.json()["items"][0]["tokens"]
    assert tokens_30d != tokens_90d
    assert tokens_30d == 100
    assert tokens_90d == 600


# -----------------------------------------------------------------------------
# PGD-05-TC-05 -- invalid range -> explicit 400, never FastAPI's default 422.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_range_returns_explicit_400_not_422_tc05(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-05-TC-05 (AC-4): range=1y 400s via the explicit validate_range() check,
    never FastAPI's default 422 -- asserts the exact status and error body,
    matching the sibling token-trend/releases/commands behavior."""
    program_id = "prog-001"
    app = _build_team_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        resp = await _get_team(client, program_id, token=token, range_param="1y")

    assert resp.status_code == 400
    assert resp.status_code != 422
    assert resp.json() == {
        "error": {"code": "http_400", "message": "invalid_range", "details": None}
    }


# -----------------------------------------------------------------------------
# PGD-05-TC-07 -- byte-identical response across personas (cio vs
# engineering-manager).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_byte_identical_response_cio_vs_engineering_manager_tc07(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-05-TC-07 (AC-6): cio and engineering-manager sessions requesting the
    same program/range get HTTP 200 with byte-identical response bodies --
    program_visibility is open-aggregate and never gates by persona."""
    program_id = "prog-001"
    now = datetime.now(UTC)
    app = _build_team_app(build_app, test_session)

    async with async_client_for(app) as client:
        await _seed_members(
            test_session,
            [
                _member_row(
                    program_id=program_id, user_id="u-a", name="Alice A", role="Developer", now=now
                )
            ],
        )
        await _seed_usage_events(
            test_session,
            [_usage_event_row(program_id=program_id, days_ago=1, now=now, user="u-a")],
        )

        cio_token = await _mint_dev_bypass_token(client, role="cio")
        em_token = await _mint_dev_bypass_token(client, role="engineering-manager")

        cio_resp = await _get_team(client, program_id, token=cio_token, range_param="30d")
        em_resp = await _get_team(client, program_id, token=em_token, range_param="30d")

    assert cio_resp.status_code == 200, cio_resp.text
    assert em_resp.status_code == 200, em_resp.text
    assert cio_resp.content == em_resp.content


# -----------------------------------------------------------------------------
# PGD-05-TC-08 -- zero active members -> 200 with items: [], not an error.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zero_active_members_returns_200_empty_list_tc08(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-05-TC-08 (AC-7): a quiet program with no in-range usage_events rows
    returns 200 with `{"items": []}`, not an error and not a 404."""
    program_id = "prog-quiet"
    app = _build_team_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        resp = await _get_team(client, program_id, token=token, range_param="7d")

    assert resp.status_code == 200, resp.text
    assert resp.status_code != 404
    assert resp.json() == {"items": []}


# -----------------------------------------------------------------------------
# PGD-05-TC-09 -- every downstream persona matches the cio baseline exactly.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_persona_matches_cio_baseline_tc09(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-05-TC-09 (AC-8): architect, developer, product-manager, and
    engineering-manager each get a response byte-identical to the cio
    baseline, per the program-team-api contract (no persona branching)."""
    program_id = "prog-001"
    now = datetime.now(UTC)
    app = _build_team_app(build_app, test_session)

    async with async_client_for(app) as client:
        await _seed_members(
            test_session,
            [
                _member_row(
                    program_id=program_id, user_id="u-a", name="Alice A", role="Developer", now=now
                )
            ],
        )
        await _seed_usage_events(
            test_session,
            [_usage_event_row(program_id=program_id, days_ago=1, now=now, user="u-a")],
        )

        cio_token = await _mint_dev_bypass_token(client, role="cio")
        baseline_resp = await _get_team(client, program_id, token=cio_token, range_param="30d")

        other_personas = ["architect", "developer", "product-manager", "engineering-manager"]
        other_responses = []
        for persona in other_personas:
            token = await _mint_dev_bypass_token(client, role=persona)
            resp = await _get_team(client, program_id, token=token, range_param="30d")
            other_responses.append(resp)

    assert baseline_resp.status_code == 200, baseline_resp.text
    for persona, resp in zip(other_personas, other_responses, strict=True):
        assert resp.status_code == 200, f"{persona}: {resp.text}"
        assert resp.content == baseline_resp.content, f"{persona} diverged from cio baseline"


# -----------------------------------------------------------------------------
# PGD-05-TC-17 -- items ordered descending by tokens.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_items_ordered_descending_by_tokens_tc17(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-05-TC-17: items[] is ordered descending by tokens -- member-B (900)
    first, member-A (500) second, member-C (100) last."""
    program_id = "prog-ordered"
    now = datetime.now(UTC)
    app = _build_team_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        await _seed_members(
            test_session,
            [
                _member_row(
                    program_id=program_id,
                    user_id="u-a",
                    name="Member A",
                    role="Developer",
                    now=now,
                ),
                _member_row(
                    program_id=program_id,
                    user_id="u-b",
                    name="Member B",
                    role="Architect",
                    now=now,
                ),
                _member_row(
                    program_id=program_id,
                    user_id="u-c",
                    name="Member C",
                    role="QA Engineer",
                    now=now,
                ),
            ],
        )
        await _seed_usage_events(
            test_session,
            [
                _usage_event_row(program_id=program_id, days_ago=1, now=now, user="u-a", total=500),
                _usage_event_row(program_id=program_id, days_ago=1, now=now, user="u-b", total=900),
                _usage_event_row(program_id=program_id, days_ago=1, now=now, user="u-c", total=100),
            ],
        )

        resp = await _get_team(client, program_id, token=token, range_param="30d")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [item["member_name"] for item in body["items"]] == ["Member B", "Member A", "Member C"]
    for i in range(len(body["items"]) - 1):
        assert body["items"][i]["tokens"] >= body["items"][i + 1]["tokens"]
