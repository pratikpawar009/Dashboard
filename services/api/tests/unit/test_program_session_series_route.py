"""Route-level tests for `GET /api/overview/program-detail/{program_id}/session-time-series`
(`app/api/overview.py::get_program_session_series`) -- PGD-06-TC-03, TC-08, TC-09, TC-10,
TC-11, TC-12, TC-14, TC-15, TC-16 (`docs/test-cases/PGD-06.json`).

Mirrors `tests/unit/test_program_team_member_usage_route.py` / `test_program_commands_route.py`'s
scaffold (`build_app`/`async_client_for`/`migrated_db`/`test_session` from `tests/conftest.py`,
`POST /auth/dev-bypass` bearer tokens) exactly: `program_visibility` is a hardcoded
open-aggregate no-op, and `member_in_program_visibility` (only invoked when `member_id` is
supplied) resolves self-or-cio -- see `app/core/rbac.py`.

TC-08's gate-before-query assertion borrows `test_auth_groups.py`'s / T-03's own
`before_cursor_execute` query-spy pattern (`_QuerySpy`/`_query_spy`), duplicated locally per
this project's independent-ownership precedent, attached to `test_engine` (the same engine
`test_session` is bound to, so it observes queries issued over HTTP through the dependency
override) and scoped to statements touching `session_series`.

TC-16's `program_drilldown` log assertion mirrors `test_program_commands_route.py`'s
`_capture_overview_logger` idiom: it is a POSITIVE existence assertion (the completion log
itself), not a "no event fired" check, so it is self-witnessing against the known Alembic
`fileConfig(disable_existing_loggers=True)` trap -- if that logger were silently disabled, the
positive assertion fails loudly instead of a negative assertion passing vacuously.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core import rbac
from app.core.db import get_db
from app.core.persona_resolver import PersonaResolver
from app.models.rollup import SessionSeries
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


def _build_session_series_app(
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


def _decode_unverified_claims(token: str) -> dict[str, Any]:
    """Read a JWT's payload claims WITHOUT verifying its signature -- mirrors
    `test_program_team_member_usage_route.py`'s own technique. Needed for the self-filter
    cases, where `member_id` must equal the requester's own `sub`."""
    import base64
    import json

    payload_segment = token.split(".")[1]
    padding = "=" * (-len(payload_segment) % 4)
    return json.loads(base64.urlsafe_b64decode(payload_segment + padding))


async def _mint_dev_bypass_token_with_sub(client: AsyncClient, *, role: str) -> tuple[str, str]:
    token = await _mint_dev_bypass_token(client, role=role)
    return token, str(_decode_unverified_claims(token)["sub"])


async def _get_session_series(
    client: AsyncClient,
    program_id: str,
    *,
    token: str | None,
    range_param: str | None = "__omit__",
    member_id: str | None = None,
) -> Response:
    """Issue the session-time-series GET. `range_param="__omit__"` (default) sends no `range`
    query param at all; any other value (including `""`) sends it. `member_id`, when not None,
    is forwarded as the `member_id` query param."""
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    params: dict[str, Any] = {} if range_param == "__omit__" else {"range": range_param}
    if member_id is not None:
        params["member_id"] = member_id
    return await client.get(
        f"/api/overview/program-detail/{program_id}/session-time-series",
        headers=headers,
        params=params,
    )


async def _seed_session_series_row(
    test_session: AsyncSession,
    *,
    program_id: str,
    member_id: str,
    day_offset: int,
    session_time_seconds: int,
    now: datetime,
    org_id: str = "org-fixture",
) -> None:
    """Insert one `session_series` row with every NOT NULL column
    (`app/models/rollup.py::SessionSeries`) explicitly set."""
    day = (now - timedelta(days=day_offset)).replace(hour=0, minute=0, second=0, microsecond=0)
    test_session.add(
        SessionSeries(
            id=str(uuid.uuid4()),
            org_id=org_id,
            program_id=program_id,
            member_id=member_id,
            date=day,
            session_time_seconds=session_time_seconds,
            as_of_timestamp=now,
        )
    )
    await test_session.commit()


# -----------------------------------------------------------------------------
# Stub persona resolver (D-06's `rbac.configure()` seam) -- mirrors
# test_program_team_member_usage_route.py's own stub, duplicated locally per
# each file's independent-ownership precedent.
# -----------------------------------------------------------------------------


class _StubPersonaResolver:
    def __init__(self, *, mapping: dict[str, str]) -> None:
        self._mapping = mapping

    async def resolve(self, role: str) -> str:
        return self._mapping[role]


@pytest.fixture(autouse=True)
def _reset_rbac_state() -> Iterator[None]:
    yield
    rbac._persona_resolver = None


# -----------------------------------------------------------------------------
# Log capture -- two independent logger families are exercised in this file:
# `app.core.rbac` (member_view_denied, TC-08) and `app.api.overview`
# (program_drilldown, TC-16). Duplicated locally per each sibling file's own
# independent-ownership precedent (test_program_team_member_usage_route.py /
# test_program_commands_route.py).
# -----------------------------------------------------------------------------


class _RecordCapturingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _capture_logger(name: str, level: int = logging.INFO) -> Iterator[list[logging.LogRecord]]:
    logger = logging.getLogger(name)
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


def _events(records: list[logging.LogRecord], message: str) -> list[logging.LogRecord]:
    return [r for r in records if r.getMessage() == message]


# -----------------------------------------------------------------------------
# Query spy -- mirrors test_auth_groups.py's / test_program_session_series_service.py's
# (T-03) `before_cursor_execute` pattern, duplicated locally per this project's
# independent-ownership precedent. Attached to `test_engine` (the engine
# `test_session` -- and therefore the HTTP-level `get_db` override -- is bound
# to), scoped to statements mentioning `session_series`.
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class _CapturedQuery:
    statement: str


class _QuerySpy:
    def __init__(self) -> None:
        self.all: list[_CapturedQuery] = []

    def record(self, statement: str) -> None:
        self.all.append(_CapturedQuery(statement=statement))

    def matching(self, pattern: re.Pattern[str]) -> list[_CapturedQuery]:
        return [q for q in self.all if pattern.search(q.statement)]


_SESSION_SERIES_RE = re.compile(r"\bsession_series\b", re.IGNORECASE)


@contextmanager
def _query_spy(engine: AsyncEngine) -> Iterator[_QuerySpy]:
    spy = _QuerySpy()
    sync_engine = engine.sync_engine

    def _before_cursor_execute(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        spy.record(statement)

    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield spy
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before_cursor_execute)


_SESSION_SERIES_RESPONSE_KEYS = {"points", "period_total_seconds", "avg_seconds_per_day"}


def _assert_no_session_series_fields(obj: Any, path: str = "$") -> None:
    """Recursively assert none of the response fields appear anywhere in `obj`."""
    if isinstance(obj, dict):
        for key in _SESSION_SERIES_RESPONSE_KEYS:
            assert key not in obj, f"found forbidden key {key!r} at {path}"
        for key, value in obj.items():
            _assert_no_session_series_fields(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            _assert_no_session_series_fields(item, f"{path}[{index}]")


# -----------------------------------------------------------------------------
# PGD-06-TC-03 -- unknown program_id -> 200 all-zero, never 404.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_program_id_returns_200_all_zero_series_tc03(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-06-TC-03 (FR-3): a program_id absent from program_summary and session_series
    returns 200 (explicitly NOT 404) with a zero-padded 30-entry all-zero series."""
    app = _build_session_series_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        resp = await _get_session_series(
            client, "does-not-exist-999", token=token, range_param="30d"
        )

    assert resp.status_code == 200, resp.text
    assert resp.status_code != 404
    body = resp.json()
    assert len(body["points"]) == 30
    assert all(p["session_time_seconds"] == 0 for p in body["points"])
    assert body["period_total_seconds"] == 0
    assert body["avg_seconds_per_day"] == 0


# -----------------------------------------------------------------------------
# PGD-06-TC-08 -- gate-before-query: non-self, non-cio member_id filter denied
# 403 BEFORE any session_series query runs.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_self_non_cio_member_filter_denied_before_query_tc08(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-06-TC-08 (FR-6, security-critical): structural proof that
    `member_in_program_visibility` denies BEFORE `fetch_program_session_series` issues any
    `session_series` query -- a query-spy count of zero, not merely a 403 status code."""
    program_id = "prog-001"
    app = _build_session_series_app(build_app, test_session)

    rbac.configure(
        cast(PersonaResolver, _StubPersonaResolver(mapping={"developer": "developer"}))
    )

    async with async_client_for(app) as client:
        token, _requester_user_id = await _mint_dev_bypass_token_with_sub(client, role="developer")
        target_member_id = "member-M"

        with (
            _query_spy(test_engine) as spy,
            _capture_logger("app.core.rbac") as rbac_records,
        ):
            resp = await _get_session_series(
                client,
                program_id,
                token=token,
                range_param="30d",
                member_id=target_member_id,
            )

    assert resp.status_code == 403

    session_series_queries = spy.matching(_SESSION_SERIES_RE)
    assert session_series_queries == [], (
        "fetch_program_session_series must never be invoked once "
        "member_in_program_visibility denies -- structural gate-before-query proof"
    )

    denied_events = _events(rbac_records, "member_view_denied")
    assert len(denied_events) == 1

    body = resp.json()
    assert set(body.keys()) == {"error"}
    _assert_no_session_series_fields(body)


# -----------------------------------------------------------------------------
# PGD-06-TC-09 -- self-filtered member_id authorized via program_visibility alone.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_self_filtered_member_id_authorized_tc09(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-06-TC-09 (AC-6): a requester filtering to their own member_id succeeds with 200,
    gated only by program_visibility -- no member_in_program_visibility denial."""
    program_id = "prog-001"
    now = datetime.now(UTC)
    app = _build_session_series_app(build_app, test_session)

    async with async_client_for(app) as client:
        token, member_id = await _mint_dev_bypass_token_with_sub(client, role="developer")
        await _seed_session_series_row(
            test_session,
            program_id=program_id,
            member_id=member_id,
            day_offset=1,
            session_time_seconds=120,
            now=now,
        )

        resp = await _get_session_series(
            client, program_id, token=token, range_param="30d", member_id=member_id
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["period_total_seconds"] == 120


# -----------------------------------------------------------------------------
# PGD-06-TC-10 -- unfiltered request authorized for any authenticated session
# regardless of program membership; byte-identical across personas.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unfiltered_request_authorized_across_personas_tc10(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-06-TC-10 (AC-6): developer, cio, and architect personas (none a member of
    prog-001) each get 200 with a byte-identical, unfiltered response body."""
    program_id = "prog-001"
    now = datetime.now(UTC)
    app = _build_session_series_app(build_app, test_session)

    await _seed_session_series_row(
        test_session,
        program_id=program_id,
        member_id="member-a",
        day_offset=2,
        session_time_seconds=200,
        now=now,
    )

    async with async_client_for(app) as client:
        bodies = []
        for role in ("developer", "cio", "architect"):
            token = await _mint_dev_bypass_token(client, role=role)
            resp = await _get_session_series(client, program_id, token=token, range_param="30d")
            assert resp.status_code == 200, resp.text
            bodies.append(resp.json())

    assert bodies[0] == bodies[1] == bodies[2]


# -----------------------------------------------------------------------------
# PGD-06-TC-11 -- invalid range -> exactly 400, never 422.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_range_returns_400_not_422_tc11(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-06-TC-11 (AC-7): an out-of-range value rejects with exactly 400 invalid_range,
    never FastAPI's default 422."""
    program_id = "prog-001"
    app = _build_session_series_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        resp = await _get_session_series(client, program_id, token=token, range_param="1y")

    assert resp.status_code == 400
    assert resp.status_code != 422
    assert resp.json() == {
        "error": {"code": "http_400", "message": "invalid_range", "details": None}
    }


# -----------------------------------------------------------------------------
# PGD-06-TC-12 -- unauthenticated request -> 401.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_request_returns_401_tc12(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-06-TC-12 (NFR-security): no bearer token, and an invalid bearer token, both 401."""
    program_id = "prog-001"
    app = _build_session_series_app(build_app, test_session)

    async with async_client_for(app) as client:
        no_token_resp = await _get_session_series(
            client, program_id, token=None, range_param="30d"
        )
        invalid_token_resp = await _get_session_series(
            client, program_id, token="not-a-real-token", range_param="30d"
        )

    assert no_token_resp.status_code == 401
    assert invalid_token_resp.status_code == 401


# -----------------------------------------------------------------------------
# PGD-06-TC-14 -- omitted range defaults to 30d, byte-identical to explicit
# ?range=30d.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_omitted_range_defaults_to_30d_tc14(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-06-TC-14 (AC-2): omitting `range` computes as if range=30d -- byte-identical to
    an explicit `?range=30d` call."""
    program_id = "prog-001"
    now = datetime.now(UTC)
    app = _build_session_series_app(build_app, test_session)

    await _seed_session_series_row(
        test_session,
        program_id=program_id,
        member_id="member-a",
        day_offset=5,
        session_time_seconds=90,
        now=now,
    )

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        omitted_resp = await _get_session_series(client, program_id, token=token)
        explicit_resp = await _get_session_series(
            client, program_id, token=token, range_param="30d"
        )

    assert omitted_resp.status_code == 200, omitted_resp.text
    assert explicit_resp.status_code == 200, explicit_resp.text
    assert len(omitted_resp.json()["points"]) == 30
    assert omitted_resp.json() == explicit_resp.json()


# -----------------------------------------------------------------------------
# PGD-06-TC-15 -- 7d/30d/90d each return their own window and length.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_each_range_returns_own_window_and_length_tc15(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-06-TC-15 (AC-2): points_7d/30d/90d have 7/30/90 entries respectively, and
    period_total_seconds differs between at least two of the three given the seeded
    fixture (some rows within 7 days, some between 8-90 days ago)."""
    program_id = "prog-multi-window"
    now = datetime.now(UTC)
    app = _build_session_series_app(build_app, test_session)

    await _seed_session_series_row(
        test_session,
        program_id=program_id,
        member_id="member-a",
        day_offset=1,
        session_time_seconds=100,
        now=now,
    )
    await _seed_session_series_row(
        test_session,
        program_id=program_id,
        member_id="member-a",
        day_offset=45,
        session_time_seconds=300,
        now=now,
    )

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        resp_7d = await _get_session_series(
            client, program_id, token=token, range_param="7d"
        )
        resp_30d = await _get_session_series(
            client, program_id, token=token, range_param="30d"
        )
        resp_90d = await _get_session_series(
            client, program_id, token=token, range_param="90d"
        )

    assert resp_7d.status_code == 200, resp_7d.text
    assert resp_30d.status_code == 200, resp_30d.text
    assert resp_90d.status_code == 200, resp_90d.text

    body_7d, body_30d, body_90d = resp_7d.json(), resp_30d.json(), resp_90d.json()
    assert len(body_7d["points"]) == 7
    assert len(body_30d["points"]) == 30
    assert len(body_90d["points"]) == 90

    totals = {
        body_7d["period_total_seconds"],
        body_30d["period_total_seconds"],
        body_90d["period_total_seconds"],
    }
    assert len(totals) >= 2, "expected at least two distinct period_total_seconds across ranges"


# -----------------------------------------------------------------------------
# PGD-06-TC-16 -- program_drilldown structured log on the 200 path.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_program_drilldown_log_emitted_on_success_tc16(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-06-TC-16 (NFR-observability): a successful fetch emits a `program_drilldown`
    structured log line with method/path/program_id/range/status/latency_ms.

    This is a POSITIVE existence assertion on `app.api.overview`'s own logger -- the very
    completion event under test -- so it is self-witnessing against the Alembic
    `fileConfig(disable_existing_loggers=True)` trap: if that logger were silently disabled,
    this assertion fails loudly (zero captured records) instead of a "no event" check
    passing vacuously.
    """
    program_id = "prog-001"
    app = _build_session_series_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")

        with _capture_logger("app.api.overview") as records:
            resp = await _get_session_series(client, program_id, token=token, range_param="30d")

    assert resp.status_code == 200, resp.text

    completion_events = _events(records, "program_drilldown")
    assert len(completion_events) == 1, (
        "program_drilldown must be captured exactly once on the app.api.overview logger -- "
        "an empty list here means the logger is silently disabled (Alembic fileConfig trap), "
        "not that the event legitimately did not fire"
    )
    record = completion_events[0]

    assert record.__dict__["method"] == "GET"
    assert "/session-time-series" in record.__dict__["path"]
    assert record.__dict__["program_id"] == program_id
    assert record.__dict__["range"] == "30d"
    assert record.__dict__["status"] == 200
    assert isinstance(record.__dict__["latency_ms"], int)
