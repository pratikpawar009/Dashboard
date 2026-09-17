"""Route-level tests for `GET /api/overview/program-detail/{program_id}/commands`
(`app/api/overview.py::get_program_commands`) -- PGD-04-TC-01, TC-02, TC-03, TC-04,
TC-06, TC-07, TC-08, TC-09, TC-10, TC-11, TC-14 (`docs/test-cases/PGD-04.json`).

Mirrors `tests/unit/test_program_releases_route.py` / `test_program_token_trend_route.py`'s
scaffold (`build_app`/`async_client_for`/`migrated_db`/`test_session` from
`tests/conftest.py`, `POST /auth/dev-bypass` bearer tokens) exactly: this route's only RBAC
call is `program_visibility` (`app/core/rbac.py`), a hardcoded open-aggregate no-op that
never resolves a persona, so a dev-bypass token (hermetic, no JWKS/RSA fixture needed) is
sufficient for every case here, including the multi-persona TC-10.

Rows are seeded directly into `usage_events` via the ORM (DECISIONS.md D-01) -- this route
aggregates the raw per-event table, never the lifetime `program_commands` rollup, so no
ingest/rollup path is exercised here.

T-07 appends a structured-logging test (`program_commands_fetched`, PGD-04-TC-17) to the
bottom of this same file -- keep new tests appended after the existing ones, following this
file's own `_capture_overview_logger` helper.
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
from app.models.ingestion import UsageEvent
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


def _build_commands_app(
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


async def _get_commands(
    client: AsyncClient,
    program_id: str,
    *,
    token: str | None,
    range_param: str | None = "__omit__",
) -> Response:
    """Issue the commands GET. `range_param="__omit__"` (default) sends no `range`
    query param at all; any other value (including `""`) sends it."""
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    params: dict[str, Any] = {} if range_param == "__omit__" else {"range": range_param}
    return await client.get(
        f"/api/overview/program-detail/{program_id}/commands",
        headers=headers,
        params=params,
    )


# -----------------------------------------------------------------------------
# Seed helpers.
# -----------------------------------------------------------------------------


def _usage_event_row(
    *,
    program_id: str,
    days_ago: int,
    now: datetime,
    command: str = "/build",
    user: str = "user-A",
) -> dict[str, Any]:
    """One `usage_events` row with every NOT NULL column (`app/models/ingestion.py::
    UsageEvent`) explicitly set."""
    ts = now - timedelta(days=days_ago)
    return {
        "id": str(uuid.uuid4()),
        "program_id": program_id,
        "ts": ts,
        "cmd_ts": ts,
        "user": user,
        "session_id": str(uuid.uuid4()),
        "kind": "command",
        "command": command,
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
        "total": 1,
        "models": None,
        "source": None,
    }


async def _seed_usage_events(test_session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    await test_session.execute(sa.insert(UsageEvent), rows)
    await test_session.commit()


# -----------------------------------------------------------------------------
# PGD-04-TC-01/02/03 -- valid range=7d/30d/90d each return 200 with the
# CommandsPanel shape.
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("range_value", ["7d", "30d", "90d"])
@pytest.mark.asyncio
async def test_valid_range_returns_200_commands_panel_shape_tc01_02_03(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    range_value: str,
) -> None:
    """PGD-04-TC-01/02/03: an explicit range=7d|30d|90d returns 200 with the
    CommandsPanel shape ({total_runs, items: [{command, count, barStyle}]})."""
    program_id = "prog-001"
    now = datetime.now(UTC)
    app = _build_commands_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        await _seed_usage_events(
            test_session,
            [
                _usage_event_row(program_id=program_id, days_ago=1, now=now, command="/build"),
                _usage_event_row(program_id=program_id, days_ago=1, now=now, command="/test"),
            ],
        )

        resp = await _get_commands(client, program_id, token=token, range_param=range_value)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {"total_runs", "items"}
    assert isinstance(body["total_runs"], str)
    for item in body["items"]:
        assert set(item.keys()) == {"command", "count", "barStyle"}


# -----------------------------------------------------------------------------
# PGD-04-TC-04 -- omitted range defaults to 30d.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_omitted_range_defaults_to_30d_tc04(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-04-TC-04: omitting `range` entirely behaves identically to an
    explicit `?range=30d` -- byte-identical response bodies."""
    program_id = "prog-001"
    now = datetime.now(UTC)
    app = _build_commands_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        await _seed_usage_events(
            test_session,
            [_usage_event_row(program_id=program_id, days_ago=d, now=now) for d in range(0, 10)],
        )

        omitted_resp = await _get_commands(
            client, program_id, token=token, range_param="__omit__"
        )
        explicit_resp = await _get_commands(
            client, program_id, token=token, range_param="30d"
        )

    assert omitted_resp.status_code == 200, omitted_resp.text
    assert explicit_resp.status_code == 200, explicit_resp.text
    assert omitted_resp.content == explicit_resp.content


# -----------------------------------------------------------------------------
# PGD-04-TC-06 -- invalid range -> explicit 400, never FastAPI's default 422.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_range_returns_explicit_400_not_422_tc06(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-04-TC-06 (AC-2): range=1y 400s via the explicit validate_range() check,
    never FastAPI's default 422 -- asserts the exact status and error body,
    matching the sibling token-trend/releases behavior."""
    program_id = "prog-001"
    app = _build_commands_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        resp = await _get_commands(client, program_id, token=token, range_param="1y")

    assert resp.status_code == 400
    assert resp.status_code != 422
    assert resp.json() == {
        "error": {"code": "http_400", "message": "invalid_range", "details": None}
    }


# -----------------------------------------------------------------------------
# PGD-04-TC-07 -- unknown/nonexistent program_id -> 200 empty shape, NEVER 404.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_program_id_returns_200_empty_shape_never_404_tc07(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-04-TC-07 (FR-1): an unknown `program_id` (no row anywhere in
    `program_summary` or `usage_events`) returns 200 with
    `{"total_runs": "0", "items": []}` -- explicitly NOT 404.

    This deliberately differs from the sibling `/releases` route
    (`test_program_releases_route.py::test_unknown_program_id_returns_404_json_body_tc11`),
    per DECISIONS.md D-02: this route performs no `program_summary` existence
    lookup, so an unknown program_id is indistinguishable from a known-but-quiet
    one. Do NOT "fix" this into a 404 by analogy with `/releases`.
    """
    app = _build_commands_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        resp = await _get_commands(
            client, "does-not-exist-999", token=token, range_param="30d"
        )

    assert resp.status_code == 200, resp.text
    assert resp.status_code != 404
    assert resp.json() == {"total_runs": "0", "items": []}


# -----------------------------------------------------------------------------
# PGD-04-TC-08 -- known program with zero in-range activity returns the same
# empty shape.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_known_program_zero_in_range_activity_same_empty_shape_tc08(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-04-TC-08 (FR-1): a known, valid program_id with no usage_events rows
    within the selected range returns the same empty shape as an unknown
    program_id -- only older, out-of-window events exist."""
    program_id = "prog-quiet"
    now = datetime.now(UTC)
    app = _build_commands_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        # Only events older than the 7d window -- program "exists" via usage
        # history, but has zero in-range activity.
        await _seed_usage_events(
            test_session,
            [_usage_event_row(program_id=program_id, days_ago=30, now=now)],
        )

        resp = await _get_commands(client, program_id, token=token, range_param="7d")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"total_runs": "0", "items": []}


# -----------------------------------------------------------------------------
# PGD-04-TC-09 -- unauthenticated request -> 401.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_request_returns_401_tc09(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-04-TC-09 (AC-5): no Authorization header, and a malformed bearer
    token, both -> 401."""
    program_id = "prog-001"
    app = _build_commands_app(build_app, test_session)

    async with async_client_for(app) as client:
        no_header_resp = await _get_commands(
            client, program_id, token=None, range_param="30d"
        )
        invalid_token_resp = await _get_commands(
            client,
            program_id,
            token="not-a-real-jwt.invalid.signature",
            range_param="30d",
        )

    assert no_header_resp.status_code == 401
    assert invalid_token_resp.status_code == 401


# -----------------------------------------------------------------------------
# PGD-04-TC-10 -- any authenticated persona succeeds, byte-identical response
# (open-aggregate, no persona branching).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_byte_identical_response_across_personas_tc10(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-04-TC-10 (AC-4): developer, cio, and architect sessions requesting
    the same program/range all get HTTP 200 with byte-identical response
    bodies -- `program_visibility` is open-aggregate and never gates by
    persona or membership."""
    program_id = "prog-001"
    now = datetime.now(UTC)
    app = _build_commands_app(build_app, test_session)

    async with async_client_for(app) as client:
        await _seed_usage_events(
            test_session,
            [_usage_event_row(program_id=program_id, days_ago=d, now=now) for d in range(0, 5)],
        )

        dev_token = await _mint_dev_bypass_token(client, role="developer")
        cio_token = await _mint_dev_bypass_token(client, role="cio")
        architect_token = await _mint_dev_bypass_token(client, role="architect")

        dev_resp = await _get_commands(client, program_id, token=dev_token, range_param="30d")
        cio_resp = await _get_commands(client, program_id, token=cio_token, range_param="30d")
        architect_resp = await _get_commands(
            client, program_id, token=architect_token, range_param="30d"
        )

    assert dev_resp.status_code == 200, dev_resp.text
    assert cio_resp.status_code == 200, cio_resp.text
    assert architect_resp.status_code == 200, architect_resp.text
    assert dev_resp.content == cio_resp.content == architect_resp.content


# -----------------------------------------------------------------------------
# PGD-04-TC-11 -- items ordered by count descending.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_items_ordered_by_count_descending_tc11(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-04-TC-11 (AC-3): items[] is ordered by count descending -- cmd-b
    (120) first, cmd-a (50) second, cmd-c (10) last."""
    program_id = "prog-ordered"
    now = datetime.now(UTC)
    app = _build_commands_app(build_app, test_session)

    counts = {"cmd-a": 50, "cmd-b": 120, "cmd-c": 10}
    rows = [
        _usage_event_row(program_id=program_id, days_ago=1, now=now, command=command)
        for command, count in counts.items()
        for _ in range(count)
    ]

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        await _seed_usage_events(test_session, rows)

        resp = await _get_commands(client, program_id, token=token, range_param="30d")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [item["command"] for item in body["items"]] == ["cmd-b", "cmd-a", "cmd-c"]
    for i in range(len(body["items"]) - 1):
        assert body["items"][i]["count"] >= body["items"][i + 1]["count"]


# -----------------------------------------------------------------------------
# PGD-04-TC-14 -- count is a raw int, total_runs a pre-formatted string, wire
# field is barStyle (camelCase), not bar_style.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_count_raw_int_total_runs_string_barstyle_camel_case_tc14(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-04-TC-14: `count` is a raw JSON integer while `total_runs` is a
    pre-formatted JSON string (comma/magnitude-formatted when >= 1000), per
    the ADR-0009-inherited asymmetry -- and the wire field is the camelCase
    alias `barStyle`, never the snake_case `bar_style`."""
    program_id = "prog-001"
    now = datetime.now(UTC)
    app = _build_commands_app(build_app, test_session)

    # 1000 events for one command -- large enough that a formatted total_runs
    # would visibly differ from the raw int (e.g. "1,000" or "1.0K").
    rows = [
        _usage_event_row(program_id=program_id, days_ago=1, now=now, command="/build")
        for _ in range(1000)
    ]

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        await _seed_usage_events(test_session, rows)

        resp = await _get_commands(client, program_id, token=token, range_param="30d")

    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert isinstance(body["total_runs"], str)
    assert body["total_runs"] != 1000

    assert len(body["items"]) == 1
    item = body["items"][0]
    assert type(item["count"]) is int
    assert item["count"] == 1000
    assert not isinstance(item["count"], str)

    assert "barStyle" in item
    assert "bar_style" not in item


# -----------------------------------------------------------------------------
# Log capture -- mirrors test_program_releases_route.py's
# `_RecordCapturingHandler`/`_capture_overview_logger` idiom, duplicated
# locally per that file's own precedent. Captures `app.api.overview`'s named
# logger (`program_commands_fetched` completion event).
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
# PGD-04-TC-17 -- structured request log with required fields, and no
# dedicated audit event for the open-aggregate program_visibility check.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_structured_request_log_and_no_rbac_audit_event_tc17(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-04-TC-17 (NFR-observability): a completed request emits a
    `program_commands_fetched` structured log line containing method, path,
    program_id, range, status, latency_ms; no dedicated
    org_access/individual_view_denied/member_view_denied audit event fires
    for this route's open-aggregate `program_visibility` check.

    Robust to the known Alembic fileConfig trap (disables every `app.*`
    logger process-wide once `test_migrations.py` has run in this session):
    this test first POSITIVELY asserts the `program_commands_fetched`
    completion log IS captured on the SAME logger family being checked for
    absence, proving the capture mechanism is live, before asserting the
    audit events are absent from those same captured records. If the
    positive capture ever fails, that is a real logging regression, not a
    passing "no audit event" assertion.
    """
    program_id = "prog-001"
    now = datetime.now(UTC)
    app = _build_commands_app(build_app, test_session)

    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")
        await _seed_usage_events(
            test_session,
            [_usage_event_row(program_id=program_id, days_ago=1, now=now, command="/build")],
        )

        with _capture_overview_logger() as records:
            resp = await _get_commands(client, program_id, token=token, range_param="30d")

    assert resp.status_code == 200, resp.text

    # Capture mechanism is live: the route's own completion log fired. This
    # makes the negative assertion below self-witnessing rather than
    # vacuously true.
    completion_events = [r for r in records if r.getMessage() == "program_commands_fetched"]
    assert len(completion_events) == 1
    record = completion_events[0]

    assert record.__dict__["method"] == "GET"
    assert "/commands" in record.__dict__["path"]
    assert record.__dict__["program_id"] == program_id
    assert record.__dict__["range"] == "30d"
    assert record.__dict__["status"] == 200
    assert isinstance(record.__dict__["latency_ms"], int)

    # No dedicated audit event for the open-aggregate program_visibility check.
    denial_event_names = {"org_access", "individual_view_denied", "member_view_denied"}
    audit_events = [r for r in records if r.getMessage() in denial_event_names]
    assert audit_events == []
