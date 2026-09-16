"""Route-level tests for `GET /api/overview/program-detail/{program_id}/token-trend`
(`app/api/overview.py::get_program_token_trend`) -- PGD-02-TC-01 (integration half),
TC-02, TC-03, TC-04, TC-08, TC-12, TC-13, TC-14, TC-15, TC-16, TC-17
(`docs/test-cases/PGD-02.json`).

Mirrors `tests/unit/test_personal_usage.py`'s scaffold (`build_app`/`async_client_for`/
`migrated_db`/`test_session` from `tests/conftest.py`, `POST /auth/dev-bypass` bearer
tokens) rather than `test_overview.py`'s Keycloak-mock scaffold: this route's only RBAC
call is `program_visibility` (`app/core/rbac.py`), a hardcoded open-aggregate no-op that
never resolves a persona, so a dev-bypass token (hermetic, no JWKS/RSA fixture needed) is
sufficient to exercise every case here, including the multi-persona TC-14.

Service-layer concerns (zero-padding internals, avg_per_day arithmetic, window-boundary
inclusivity) belong to T-04's service unit tests, not here -- this file only asserts what
is observable at the HTTP boundary: response shape/types, the 400-vs-422 range-validation
contract, and RBAC/auth outcomes.
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
from app.models.rollup import ProgramTokenSeries
from tests.conftest import AlembicRunner

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]


# -----------------------------------------------------------------------------
# App + DB-override scaffold. Mirrors test_personal_usage.py's
# _build_personal_usage_app / _db_override precedent.
# -----------------------------------------------------------------------------


def _db_override(session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _get_db() -> AsyncIterator[AsyncSession]:
        yield session

    return _get_db


def _build_token_trend_app(
    build_app: Callable[..., FastAPI], test_session: AsyncSession, **settings_overrides: Any
) -> FastAPI:
    """Real `create_app()` (D-07) wired for HTTP-level testing against a live DB.
    Hermetic default settings set `environment="test"`, so `/auth/dev-bypass` is
    registered and its tokens verify with no OIDC config."""
    app = build_app(**settings_overrides)
    app.dependency_overrides[get_db] = _db_override(test_session)
    return app


async def _mint_dev_bypass_token(client: AsyncClient, *, role: str) -> str:
    resp = await client.post("/auth/dev-bypass", json={"role": role})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


async def _get_token_trend(
    client: AsyncClient,
    program_id: str,
    *,
    token: str | None,
    range_param: str | None = "__omit__",
) -> Response:
    """Issue the token-trend GET. `range_param="__omit__"` (default) sends no
    `range` query param at all; any other value (including `""`) sends it."""
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    params = {} if range_param == "__omit__" else {"range": range_param}
    return await client.get(
        f"/api/overview/program-detail/{program_id}/token-trend",
        headers=headers,
        params=params,
    )


def _series_row(*, program_id: str, days_ago: int, tokens: int, now: datetime) -> dict[str, Any]:
    """One `program_token_series` row with every NOT NULL column
    (`app/models/rollup.py::ProgramTokenSeries`) explicitly set."""
    return {
        "id": str(uuid.uuid4()),
        "program_id": program_id,
        "date": now - timedelta(days=days_ago),
        "tokens": tokens,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "as_of_timestamp": now,
    }


async def _seed_series(
    test_session: AsyncSession,
    program_id: str,
    day_token_pairs: list[tuple[int, int]],
    now: datetime,
) -> None:
    rows = [
        _series_row(program_id=program_id, days_ago=d, tokens=t, now=now)
        for d, t in day_token_pairs
    ]
    await test_session.execute(sa.insert(ProgramTokenSeries), rows)
    await test_session.commit()


# -----------------------------------------------------------------------------
# PGD-02-TC-01 (integration half) -- no range param defaults to 30d, 30 points.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_range_param_defaults_to_30d_tc01(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-02-TC-01: omitting `range` entirely defaults to `30d` -- proven via
    `len(points) == 30`, not just a bare 200."""
    program_id = "PROG-100"
    now = datetime.now(UTC)
    app = _build_token_trend_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        await _seed_series(test_session, program_id, [(d, 10) for d in range(0, 30, 3)], now)
        resp = await _get_token_trend(client, program_id, token=token, range_param="__omit__")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["points"]) == 30
    dates = {p["date"] for p in body["points"]}
    assert len(dates) == 30, "each point must cover a distinct calendar day"


# -----------------------------------------------------------------------------
# PGD-02-TC-02/03/04 -- range=7d/30d/90d returns exactly N points shaped
# {date, tokens}.
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("range_value,expected_points", [("7d", 7), ("30d", 30), ("90d", 90)])
@pytest.mark.asyncio
async def test_range_returns_exact_point_count_shaped_date_tokens_tc02_03_04(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    range_value: str,
    expected_points: int,
) -> None:
    """PGD-02-TC-02/03/04: `range=7d|30d|90d` returns exactly 7/30/90 points,
    each with exactly the keys `date` (str) and `tokens` (int) -- a test that
    would still pass if a `value` (pre-formatted string) field were added
    alongside would be useless here, so the key set is asserted exactly."""
    program_id = "PROG-100"
    now = datetime.now(UTC)
    app = _build_token_trend_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        seed_days = min(expected_points, 5)
        await _seed_series(
            test_session, program_id, [(d, 100 + d) for d in range(0, seed_days)], now
        )
        resp = await _get_token_trend(client, program_id, token=token, range_param=range_value)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    points = body["points"]
    assert len(points) == expected_points
    for point in points:
        assert set(point.keys()) == {"date", "tokens"}
        assert isinstance(point["date"], str)
        assert isinstance(point["tokens"], int)


# -----------------------------------------------------------------------------
# PGD-02-TC-08 -- period_total/avg_per_day are raw ints, never format_number()
# strings.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_period_total_and_avg_per_day_are_raw_ints_not_formatted_tc08(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-02-TC-08 (FR-2): `period_total`/`avg_per_day` are raw JSON integers,
    never `format_number()`-style magnitude strings like "12.0K".

    Concretely: 30 days of `program_token_series` rows summing to 12000
    tokens must yield `period_total == 12000` (the raw int) -- if the route
    wrapped this in `format_number()`, the JSON value would come back as the
    STRING "12.0K" and `type(period_total) is int` below would fail (a
    string equality check like `period_total == "12000"` would NOT catch
    that regression, which is why this asserts the JSON type explicitly, not
    just the value)."""
    program_id = "PROG-100"
    now = datetime.now(UTC)
    app = _build_token_trend_app(build_app, test_session)

    # 30 rows of 400 tokens each = 12000 total, matching test_data's
    # "Program PROG-100 has program_token_series rows summing to 12000
    # tokens across 30 days" precondition exactly (one row per day, no gaps).
    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        await _seed_series(test_session, program_id, [(d, 400) for d in range(0, 30)], now)
        resp = await _get_token_trend(client, program_id, token=token, range_param="30d")

    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert type(body["period_total"]) is int
    assert body["period_total"] == 12000
    assert type(body["avg_per_day"]) is int

    for point in body["points"]:
        assert type(point["tokens"]) is int

    # No field anywhere in the envelope is a magnitude-formatted string.
    assert body["period_total"] != "12.0K"
    assert not isinstance(body["period_total"], str)
    assert not isinstance(body["avg_per_day"], str)


# -----------------------------------------------------------------------------
# PGD-02-TC-12/TC-13 -- range validation: out-of-set / empty-string -> 400,
# never 422.
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("range_value", ["15d", ""])
@pytest.mark.asyncio
async def test_invalid_range_returns_explicit_400_not_422_tc12_tc13(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    range_value: str,
) -> None:
    """PGD-02-TC-12/TC-13: an out-of-set `range` value (`"15d"`) and an
    empty-string `range` value both 400 via the explicit `validate_range()`
    check, never FastAPI's default 422 -- and the body matches the shared
    `invalid_range` error envelope every other `validate_range()` consumer
    produces (`app/dependencies/range.py`).

    Distinguishing 400 from 422 here means asserting the EXACT status code
    (`== 400`, not `>= 400` or `in {400, 422}`) plus the exact error body --
    a `resp.status_code != 200` assertion alone would pass just as happily
    on a 422 and would not catch a regression to FastAPI's default Query()
    validation path."""
    program_id = "PROG-100"
    app = _build_token_trend_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        resp = await _get_token_trend(client, program_id, token=token, range_param=range_value)

    assert resp.status_code == 400
    assert resp.status_code != 422
    assert resp.json() == {
        "error": {"code": "http_400", "message": "invalid_range", "details": None}
    }


# -----------------------------------------------------------------------------
# PGD-02-TC-14 -- any authenticated persona gets a byte-identical response,
# no persona branching.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_byte_identical_response_across_personas_tc14(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-02-TC-14 (AC-7): a `developer` session and a `cio` session
    requesting the same program's token-trend with the same range get
    HTTP 200 and byte-identical response bodies -- proving the open-
    aggregate RBAC model performs no per-persona response branching."""
    program_id = "PROG-100"
    now = datetime.now(UTC)
    app = _build_token_trend_app(build_app, test_session)

    async with async_client_for(app) as client:
        await _seed_series(test_session, program_id, [(d, 50 + d) for d in range(0, 30)], now)

        dev_token = await _mint_dev_bypass_token(client, role="developer")
        cio_token = await _mint_dev_bypass_token(client, role="cio")

        dev_resp = await _get_token_trend(client, program_id, token=dev_token, range_param="30d")
        cio_resp = await _get_token_trend(client, program_id, token=cio_token, range_param="30d")

    assert dev_resp.status_code == 200, dev_resp.text
    assert cio_resp.status_code == 200, cio_resp.text
    assert dev_resp.content == cio_resp.content


# -----------------------------------------------------------------------------
# PGD-02-TC-15 -- authenticated session granted access regardless of
# program_id (open-aggregate, no per-program membership gate).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_access_granted_regardless_of_program_id_tc15(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-02-TC-15 (AC-7): a `developer` session (dev-bypass tokens carry no
    `programs` scoping the route reads) is granted access to an arbitrary
    program's token-trend -- `program_visibility` never gates on
    `current_user.programs`, so no per-program membership check blocks this
    endpoint even for a program the session has no explicit tie to."""
    program_id = "PROG-300"
    now = datetime.now(UTC)
    app = _build_token_trend_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        await _seed_series(test_session, program_id, [(d, 20) for d in range(0, 30)], now)
        resp = await _get_token_trend(client, program_id, token=token, range_param="30d")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["points"]) == 30


# -----------------------------------------------------------------------------
# PGD-02-TC-16/TC-17 -- missing / invalid bearer token -> 401.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_bearer_token_returns_401_tc16(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-02-TC-16: a request with no `Authorization` header at all is
    rejected with 401 and no series data in the body."""
    program_id = "PROG-100"
    app = _build_token_trend_app(build_app, test_session)

    async with async_client_for(app) as client:
        resp = await _get_token_trend(client, program_id, token=None, range_param="30d")

    assert resp.status_code == 401
    body = resp.json()
    assert "points" not in body
    assert "period_total" not in body


@pytest.mark.asyncio
async def test_invalid_bearer_token_returns_401_tc17(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-02-TC-17: a request carrying a malformed/invalid bearer token is
    rejected with 401 and no series data in the body."""
    program_id = "PROG-100"
    app = _build_token_trend_app(build_app, test_session)

    async with async_client_for(app) as client:
        resp = await _get_token_trend(
            client, program_id, token="not-a-real-jwt.invalid.signature", range_param="30d"
        )

    assert resp.status_code == 401
    body = resp.json()
    assert "points" not in body
    assert "period_total" not in body
