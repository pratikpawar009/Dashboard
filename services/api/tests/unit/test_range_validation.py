"""Unit/integration tests for app/dependencies/range.py — BED-02-TC-01, 02, 03,
04, 14, 19, 20 (PLAN.md §7 Test Strategy row 1; T-11 notes/ac_refs include
BED-02-NFR-observability, hence TC-20 is covered here alongside the TC-19
security case, not split into a separate file).

Mirrors BED-02-TC-01's own pattern used by `tests/unit/test_pagination.py`:
a tiny FastAPI app with throwaway Depends()-wired test routes, defined only
in this module and never wired into production routes (out of BED-02 scope;
see `app/main.py` for the real router assembly). Per PLAN.md §7 this file
uses `httpx.ASGITransport` + `AsyncClient` (async, unlike test_pagination.py's
synchronous `TestClient`) so the two consumer routers for TC-14/AC-7 and the
real logging path for TC-19/TC-20 exercise the dependency exactly as a real
async route handler would.

`register_exception_handlers(app)` is wired once on the shared module-level
app so every 400 in this file — including the two independent consumer
routers used by TC-14 — goes through the real `error_body()` envelope
machinery (app/core/errors.py), matching FR-1/AC-7.

TC-19/TC-20's logging assertions do NOT depend on the process-wide root
logger, `configure_logging()`, or `capsys` — see `_range_logger_capture`'s
docstring for why (AF-08-carry: alembic's `fileConfig(disable_existing_
loggers=True)` in `migrations/env.py:19` permanently disables any
already-existing logger, including this module's `app.dependencies.range`
logger, once `tests/test_migrations.py` has run earlier in the same
session). Both attach directly to the real, named `app.dependencies.range`
logger instead, so the real `validate_range()` rejection path is still
exercised end-to-end while staying immune to that ambient state.
"""

import io
import json
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.errors import register_exception_handlers
from app.core.logging import JSONFormatter
from app.dependencies.range import range_to_start, validate_range

FROZEN_NOW = datetime(2026, 8, 27, 0, 0, 0, tzinfo=UTC)
EXPECTED_WINDOW_START = {
    "7d": datetime(2026, 8, 20, 0, 0, 0, tzinfo=UTC),
    "30d": datetime(2026, 7, 28, 0, 0, 0, tzinfo=UTC),
    "90d": datetime(2026, 5, 29, 0, 0, 0, tzinfo=UTC),
}
INVALID_RANGE_VALUES = ["invalid", "60d", "", "7D", "0d"]
EXPECTED_ERROR_BODY = {"error": {"code": "http_400", "message": "invalid_range", "details": None}}
FORBIDDEN_LOG_FIELDS = ("user_id", "email", "session_id", "ip", "authorization")

app = FastAPI()
register_exception_handlers(app)

router = APIRouter()


@router.get("/test-range")
async def _range_route(range: str = Depends(validate_range)) -> dict:
    """BED-02-TC-01/02: echoes the accepted range plus its computed window
    start, against the frozen clock, so acceptance AND correct query scoping
    are both observable from one response."""
    start = range_to_start(range, now=FROZEN_NOW)
    return {"range": range, "start": start.isoformat()}


app.include_router(router)

# BED-02-TC-14 (AC-7): two independent consumers of the same shared
# validate_range dependency, mounted on different paths.
consumer_a = APIRouter(prefix="/consumer-a")
consumer_b = APIRouter(prefix="/consumer-b")


@consumer_a.get("/items")
async def _consumer_a_items(range: str = Depends(validate_range)) -> dict:
    return {"range": range}


@consumer_b.get("/reports")
async def _consumer_b_reports(range: str = Depends(validate_range)) -> dict:
    return {"range": range}


app.include_router(consumer_a)
app.include_router(consumer_b)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


class _RecordCapturingHandler(logging.Handler):
    """Stores emitted LogRecord instances verbatim, without formatting them.

    Mirrors `tests/unit/test_logging.py`'s `_RecordCapturingHandler`,
    duplicated locally rather than imported — this file and test_logging.py
    are independently-owned, throwaway test modules (F-11 vs F-15) and
    neither should import test internals from the other.
    """

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _isolated_range_logger() -> Iterator[logging.Logger]:
    """Force-resets and yields the real `app.dependencies.range` logger,
    isolated from ambient process state, restoring it in a `finally`.

    `validate_range()` logs through `logging.getLogger(__name__)` —
    `app.dependencies.range` — a process-wide singleton object (repeated
    `logging.getLogger()` calls with the same name always return the same
    object). `tests/test_migrations.py` runs Alembic earlier in the same
    pytest session; `migrations/env.py:19` calls `logging.config.fileConfig`
    with the stdlib default `disable_existing_loggers=True`, which sets
    `.disabled = True` on every logger that already exists at that point and
    isn't named in the fileConfig — including this one — for the rest of
    the process (AF-08-carry, BED-01, deferred). A disabled logger drops
    every `logger.warning(...)` call as a no-op before a LogRecord is even
    built, so neither `caplog` nor a root-attached handler nor
    `configure_logging()` + `capsys` ever sees anything, regardless of test
    order within the file. Forcing `.disabled = False` and `.propagate =
    False` here, and attaching a handler directly to this named logger
    (bypassing root entirely), makes the capture immune to that — the real
    `validate_range()` rejection path is still exercised end-to-end.
    """
    logger = logging.getLogger("app.dependencies.range")
    original_disabled = logger.disabled
    original_propagate = logger.propagate
    original_level = logger.level
    logger.disabled = False
    logger.propagate = False
    logger.setLevel(logging.WARNING)
    try:
        yield logger
    finally:
        logger.disabled = original_disabled
        logger.propagate = original_propagate
        logger.setLevel(original_level)


@pytest.fixture
def range_logger_records() -> Iterator[list[logging.LogRecord]]:
    """TC-19: captures raw LogRecords from the real validate_range() logger,
    formatted after the fact through JSONFormatter() to assert the shape."""
    with _isolated_range_logger() as logger:
        handler = _RecordCapturingHandler()
        logger.addHandler(handler)
        try:
            yield handler.records
        finally:
            logger.removeHandler(handler)


@pytest.fixture
def range_logger_json_stream() -> Iterator[io.StringIO]:
    """TC-20: wires the production `StreamHandler` + `JSONFormatter` pair —
    the exact classes `configure_logging()` uses — directly onto the real
    validate_range() logger and an in-memory stream, so the real emit/format
    pipeline runs end-to-end without touching the process-wide root logger
    or stdout."""
    with _isolated_range_logger() as logger:
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        try:
            yield stream
        finally:
            logger.removeHandler(handler)


# BED-02-TC-01 (AC-1): all three documented range values are accepted and
# reach the handler.
@pytest.mark.asyncio
@pytest.mark.parametrize("range_value", ["7d", "30d", "90d"])
async def test_accepts_documented_range_values(client: AsyncClient, range_value: str) -> None:
    resp = await client.get("/test-range", params={"range": range_value})
    assert resp.status_code == 200
    assert resp.json()["range"] == range_value


# BED-02-TC-02 (AC-1): an accepted range maps to the correct lookback-window
# start against a frozen clock.
@pytest.mark.asyncio
@pytest.mark.parametrize("range_value", ["7d", "30d", "90d"])
async def test_range_maps_to_correct_window_start(client: AsyncClient, range_value: str) -> None:
    resp = await client.get("/test-range", params={"range": range_value})
    assert resp.status_code == 200
    assert resp.json()["start"] == EXPECTED_WINDOW_START[range_value].isoformat()


# BED-02-TC-02 / D-06: a naive `now` is rejected, not silently assumed UTC.
def test_range_to_start_rejects_naive_now() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        range_to_start("7d", now=datetime(2026, 8, 27, 0, 0, 0))


# BED-02-TC-03 (AC-2): out-of-set values return HTTP 400, never FastAPI's
# default 422 type-coercion error.
@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_value", INVALID_RANGE_VALUES)
async def test_invalid_range_returns_400_not_422(client: AsyncClient, invalid_value: str) -> None:
    resp = await client.get("/test-range", params={"range": invalid_value})
    assert resp.status_code == 400
    assert resp.status_code != 422


# BED-02-TC-04 (FR-1): the 400 body is exactly error_body()'s envelope shape.
@pytest.mark.asyncio
async def test_invalid_range_error_envelope_matches_error_body_shape(
    client: AsyncClient,
) -> None:
    resp = await client.get("/test-range", params={"range": "60d"})
    assert resp.status_code == 400
    assert resp.json() == EXPECTED_ERROR_BODY


# BED-02-TC-14 (AC-7): two independent consumers of the shared dependency
# return byte-identical status + body for the same invalid value.
@pytest.mark.asyncio
async def test_two_consumer_routers_return_identical_rejection(client: AsyncClient) -> None:
    resp_a = await client.get("/consumer-a/items", params={"range": "60d"})
    resp_b = await client.get("/consumer-b/reports", params={"range": "60d"})

    assert resp_a.status_code == resp_b.status_code == 400
    assert resp_a.json() == resp_b.json() == EXPECTED_ERROR_BODY


# BED-02-TC-19 (NFR-security): rejection logs exactly {route, param,
# rejected_value} — no PII, no extraneous request context
# (.claude/rules/security-baseline.md). Captured via the real
# validate_range() dependency's logger.warning() call, not a synthetic
# LogRecord (see `range_logger_records`/`_isolated_range_logger` for why
# this doesn't use `caplog`/root); formatted through the real JSONFormatter
# to assert the shape actually shipped to stdout in production.
@pytest.mark.asyncio
async def test_invalid_range_logs_only_documented_fields(
    client: AsyncClient, range_logger_records: list[logging.LogRecord]
) -> None:
    resp = await client.get("/test-range", params={"range": "60d"})

    assert resp.status_code == 400
    assert len(range_logger_records) == 1

    payload = json.loads(JSONFormatter().format(range_logger_records[0]))
    custom_fields = set(payload) - {"timestamp", "level", "logger", "message"}
    assert custom_fields == {"route", "param", "rejected_value"}
    assert payload["route"] == "/test-range"
    assert payload["param"] == "range"
    assert payload["rejected_value"] == "60d"

    serialized = json.dumps(payload)
    for forbidden in FORBIDDEN_LOG_FIELDS:
        assert forbidden not in payload
        assert forbidden not in serialized


# BED-02-TC-20 (NFR-observability): end-to-end of FR-3 — the real
# validate_range() rejection path, through the production StreamHandler +
# JSONFormatter pair (see `range_logger_json_stream`), emits exactly one
# structured WARNING JSON line carrying route/param/rejected_value.
@pytest.mark.asyncio
async def test_invalid_range_end_to_end_json_log_line(
    client: AsyncClient, range_logger_json_stream: io.StringIO
) -> None:
    resp = await client.get("/test-range", params={"range": "abc"})
    assert resp.status_code == 400

    lines = [line for line in range_logger_json_stream.getvalue().splitlines() if line]
    assert len(lines) == 1

    payload = json.loads(lines[0])
    assert payload["level"] == "WARNING"
    assert payload["route"] == "/test-range"
    assert payload["param"] == "range"
    assert payload["rejected_value"] == "abc"
