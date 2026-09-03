"""Tests for `get_ingest_token()` -- ING-01-TC-06..TC-20, TC-24
(ING-01-FR-3 scope-check order, FR-4 401/403 classification, FR-5 log-event
field allowlist; ING-01-AC-3, AC-4, AC-5).

Every test calls `get_ingest_token()` directly against a real Postgres test
DB via `migrated_db`/`test_session` (no mocks at the integration boundary,
PRD § Addressing Research Conditions C-5) -- matching
`tests/perf/test_ingest_token_auth_perf.py`'s own direct-call convention for
this same function. Rows are seeded straight through `test_session`, never
via the mint script (that is `test_mint_ingest_token.py`'s job).

Token values: `hrn_pat_` + `secrets.token_hex(32)` (64 hex chars, ADR-0006
SS1) -- never the story AC-1 48-char figure, which ADR-0006 SS1 supersedes.

Log-capture idiom (duplicated locally per this repo's established
per-file-ownership precedent -- see `tests/unit/test_range_validation.py`'s
`_isolated_range_logger` / `tests/unit/test_auth_logging_security.py`'s
`_isolated_oidc_logger`): a handler is attached directly to the real, named
`app.core.ingest_auth` logger, forcing `.disabled = False` / `.propagate =
False` for the test's duration. `migrations/env.py:19`'s
`fileConfig(disable_existing_loggers=True)` permanently disables any
already-existing logger (including this one) once `tests/test_migrations.py`
has run earlier in the same pytest session -- `caplog`, a root-attached
handler, and `configure_logging()` + `capsys` are all blind to a disabled
logger regardless of test order.

TC-15's frozen-clock boundary: `get_ingest_token()` has no injectable `now`
parameter (unlike `app/dependencies/range.py`'s `now=` kwarg) and no
frozen-clock library (e.g. freezegun) is a project dependency. `_FrozenClock`
monkeypatches the `datetime` name inside `app.core.ingest_auth`'s own module
namespace for the duration of one test -- Python resolves a module-level
global at call time, so this pins `datetime.now(UTC)` to an exact instant
without editing the module under test.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import secrets
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ingest_auth as ingest_auth_module
from app.core.db import get_db
from app.core.errors import register_exception_handlers
from app.core.ingest_auth import get_ingest_token
from app.core.logging import JSONFormatter
from app.models.ingestion import IngestToken
from tests.conftest import AlembicRunner

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

# -----------------------------------------------------------------------------
# Seeding + credential-building helpers.
# -----------------------------------------------------------------------------


async def _seed_token(
    test_session: AsyncSession,
    *,
    label: str,
    allowed_program_ids: list[str],
    user_email: str = "owner@example.com",
    revoked_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> tuple[str, IngestToken]:
    """Seed one `ingest_tokens` row directly, returning `(raw_token, row)`.

    No `refresh()` after commit: `test_session`'s factory sets
    `expire_on_commit=False` (`tests/conftest.py:193`), so `row`'s
    Python-side attributes -- including the client-side-generated `id`
    (`IngestToken.id`'s `default=lambda: str(uuid.uuid4())`) -- stay exactly
    as constructed. This also means `get_ingest_token()`'s own SELECT
    resolves the same identity-mapped object rather than a freshly
    round-tripped one, which is what makes TC-15's frozen-clock comparison
    exact.
    """
    raw_token = "hrn_pat_" + secrets.token_hex(32)
    row = IngestToken(
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        label=label,
        user_email=user_email,
        allowed_program_ids=allowed_program_ids,
        expires_at=expires_at,
        revoked_at=revoked_at,
    )
    test_session.add(row)
    await test_session.commit()
    return raw_token, row


def _credentials(raw_token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=raw_token)


# -----------------------------------------------------------------------------
# TC-11 real-header round-trip -- throwaway app wired with `get_ingest_token`
# only, mirroring `test_ingest_token_isolation.py::_build_dual_dependency_app`
# (D-03's established pattern) minus the `get_current_user` half, which TC-11
# has no need for. Driven over `httpx`/`ASGITransport` via `conftest.py`'s
# `async_client_for`, so a genuine `Authorization: Basic ...` header round-
# trips through FastAPI's own `HTTPBearer(auto_error=False)` resolution
# instead of assuming its `credentials=None` mapping by direct call.
# -----------------------------------------------------------------------------

_INGEST_ONLY_ROUTE_PATH = "/test-only/ingest-auth"


def _build_ingest_only_app(test_session: AsyncSession) -> FastAPI:
    """Throwaway app, never `app.main.create_app` (D-03): one route
    declaring `Depends(get_ingest_token)` only. `get_db` is overridden to
    yield the caller's own `test_session` so the hash lookup hits the
    disposable test DB, never the dev database.
    """
    app = FastAPI()
    register_exception_handlers(app)

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield test_session

    app.dependency_overrides[get_db] = _override_get_db

    router = APIRouter()

    @router.get(_INGEST_ONLY_ROUTE_PATH)
    async def _ingest_only_probe(
        ingest_token: IngestToken = Depends(get_ingest_token),
    ) -> dict[str, Any]:
        return {"ingest_token_id": ingest_token.id}  # pragma: no cover -- unreachable by TC-11

    app.include_router(router)
    return app


# -----------------------------------------------------------------------------
# Log-capture idiom -- mirrors test_range_validation.py's
# `_RecordCapturingHandler` / `_isolated_range_logger` (see module docstring).
# -----------------------------------------------------------------------------


class _RecordCapturingHandler(logging.Handler):
    """Stores emitted LogRecord instances verbatim, without formatting them."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _isolated_ingest_auth_logger() -> Iterator[logging.Logger]:
    """Force-resets and yields the real `app.core.ingest_auth` logger,
    isolated from ambient process state, restoring it in a `finally` -- see
    module docstring for the disabled-logger trap this works around."""
    logger = logging.getLogger("app.core.ingest_auth")
    original_disabled = logger.disabled
    original_propagate = logger.propagate
    original_level = logger.level
    logger.disabled = False
    logger.propagate = False
    logger.setLevel(logging.INFO)
    try:
        yield logger
    finally:
        logger.disabled = original_disabled
        logger.propagate = original_propagate
        logger.setLevel(original_level)


@pytest.fixture
def ingest_auth_logger_records() -> Iterator[list[logging.LogRecord]]:
    """Captures raw LogRecords from the real `get_ingest_token()` logger,
    formatted after the fact through the real `JSONFormatter` per test."""
    with _isolated_ingest_auth_logger() as logger:
        handler = _RecordCapturingHandler()
        logger.addHandler(handler)
        try:
            yield handler.records
        finally:
            logger.removeHandler(handler)


def _formatted_payloads(records: list[logging.LogRecord]) -> list[dict[str, Any]]:
    return [json.loads(JSONFormatter().format(r)) for r in records]


# -----------------------------------------------------------------------------
# TC-15 frozen-clock helper -- see module docstring.
# -----------------------------------------------------------------------------


class _FrozenClock:
    """Replaces `app.core.ingest_auth`'s `datetime` name for one test, so
    `datetime.now(UTC)` inside `get_ingest_token()` returns a fixed instant."""

    def __init__(self, frozen_now: datetime) -> None:
        self._frozen_now = frozen_now

    def now(self, tz: Any = None) -> datetime:
        return self._frozen_now


# -----------------------------------------------------------------------------
# ING-01-TC-06 (FR-3) -- empty allowed_program_ids passes for any program_id.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_allowed_program_ids_passes_scope_check_tc06(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    raw_token, row = await _seed_token(test_session, label="tc06-allow-all", allowed_program_ids=[])

    for program_id in ("prog-anything", "prog-something-else"):
        token = await get_ingest_token(
            program_id=program_id, credentials=_credentials(raw_token), session=test_session
        )
        assert token.id == row.id


# -----------------------------------------------------------------------------
# ING-01-TC-07 (FR-3) -- wildcard ["*"] passes for any program_id.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wildcard_array_passes_scope_check_tc07(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    raw_token, row = await _seed_token(
        test_session, label="tc07-wildcard", allowed_program_ids=["*"]
    )

    for program_id in ("prog-7", "prog-other"):
        token = await get_ingest_token(
            program_id=program_id, credentials=_credentials(raw_token), session=test_session
        )
        assert token.id == row.id


# -----------------------------------------------------------------------------
# ING-01-TC-08 (AC-3) -- membership hit in a specific-ids array passes.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_membership_hit_passes_scope_check_tc08(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    raw_token, row = await _seed_token(
        test_session, label="tc08-membership", allowed_program_ids=["prog-8", "prog-9"]
    )

    token = await get_ingest_token(
        program_id="prog-9", credentials=_credentials(raw_token), session=test_session
    )
    assert token.id == row.id


# -----------------------------------------------------------------------------
# ING-01-TC-09 (AC-5) -- membership miss on a non-wildcard array raises 403.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_membership_miss_raises_403_tc09(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    raw_token, _row = await _seed_token(
        test_session, label="tc09-miss", allowed_program_ids=["prog-10"]
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_ingest_token(
            program_id="prog-11", credentials=_credentials(raw_token), session=test_session
        )
    assert exc_info.value.status_code == 403


# -----------------------------------------------------------------------------
# ING-01-TC-10 (AC-4) -- missing Authorization header raises 401 "missing".
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_authorization_header_raises_401_missing_tc10(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await get_ingest_token(program_id="prog-1", credentials=None, session=test_session)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "missing"


# -----------------------------------------------------------------------------
# ING-01-TC-11 (FR-4) -- a non-Bearer scheme raises 401 "missing".
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_bearer_scheme_raises_401_missing_tc11(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    async_client_for: AsyncClientFactory,
) -> None:
    """Strengthened (fix directive, advisory validation finding): sends a
    genuine `Authorization: Basic ...` header through FastAPI's own
    `HTTPBearer(auto_error=False)` resolution on a real route, rather than
    asserting equivalence to TC-10 by passing `credentials=None` directly.
    `HTTPBearer.__call__` maps a non-Bearer scheme (e.g. `Basic
    dXNlcjpwYXNz`) to `credentials=None` before `get_ingest_token` ever runs
    (module docstring, `app/core/ingest_auth.py` lines 57-60) -- this
    round-trips that mapping through the real machinery instead of assuming
    it, so a regression in `HTTPBearer`'s own resolution would be caught.
    """
    app = _build_ingest_only_app(test_session)
    async with async_client_for(app) as client:
        resp = await client.get(
            _INGEST_ONLY_ROUTE_PATH,
            params={"program_id": "prog-1"},
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
    assert resp.status_code == 401
    assert resp.json()["error"]["message"] == "missing"


# -----------------------------------------------------------------------------
# ING-01-TC-12 (AC-4) -- an unknown token hash raises 401 "unknown".
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_token_hash_raises_401_unknown_tc12(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    raw_token = "hrn_pat_" + secrets.token_hex(32)  # never seeded

    with pytest.raises(HTTPException) as exc_info:
        await get_ingest_token(
            program_id="prog-1", credentials=_credentials(raw_token), session=test_session
        )
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "unknown"


# -----------------------------------------------------------------------------
# ING-01-TC-13 (AC-4) -- a revoked token raises 401 "revoked".
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoked_token_raises_401_revoked_tc13(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    raw_token, _row = await _seed_token(
        test_session,
        label="tc13-revoked",
        allowed_program_ids=[],
        revoked_at=datetime(2026, 8, 1, tzinfo=UTC),
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_ingest_token(
            program_id="prog-1", credentials=_credentials(raw_token), session=test_session
        )
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "revoked"


# -----------------------------------------------------------------------------
# ING-01-TC-14 (AC-4) -- an expired token raises 401 "expired".
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expired_token_raises_401_expired_tc14(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    raw_token, _row = await _seed_token(
        test_session,
        label="tc14-expired",
        allowed_program_ids=[],
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_ingest_token(
            program_id="prog-1", credentials=_credentials(raw_token), session=test_session
        )
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "expired"


# -----------------------------------------------------------------------------
# ING-01-TC-15 (FR-4) -- expires_at == now() is expired; +1s is not.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expires_at_boundary_now_vs_one_second_future_tc15(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen_now = datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(ingest_auth_module, "datetime", _FrozenClock(frozen_now))

    raw_at_now, _row_a = await _seed_token(
        test_session, label="tc15-at-now", allowed_program_ids=[], expires_at=frozen_now
    )
    raw_future, row_b = await _seed_token(
        test_session,
        label="tc15-future",
        allowed_program_ids=[],
        expires_at=frozen_now + timedelta(seconds=1),
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_ingest_token(
            program_id="prog-1", credentials=_credentials(raw_at_now), session=test_session
        )
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "expired"

    token = await get_ingest_token(
        program_id="prog-1", credentials=_credentials(raw_future), session=test_session
    )
    assert token.id == row_b.id


# -----------------------------------------------------------------------------
# ING-01-TC-16 (AC-3) -- valid, active, in-scope token resolves (happy path).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_active_in_scope_token_resolves_tc16(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    raw_token, row = await _seed_token(
        test_session, label="tc16-happy-path", allowed_program_ids=["prog-12"]
    )

    token = await get_ingest_token(
        program_id="prog-12", credentials=_credentials(raw_token), session=test_session
    )
    assert token.id == row.id


# -----------------------------------------------------------------------------
# ING-01-TC-17 (FR-4) -- scope check uses the caller-supplied program_id.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scope_check_uses_caller_supplied_program_id_tc17(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    signature = inspect.signature(get_ingest_token)
    program_id_param = signature.parameters["program_id"]
    assert program_id_param.default is inspect.Parameter.empty, (
        "program_id must be a required parameter, distinct from the "
        "Depends()-defaulted credentials/session parameters"
    )

    raw_token, row = await _seed_token(
        test_session, label="tc17-caller-supplied", allowed_program_ids=["prog-13"]
    )

    token = await get_ingest_token(
        program_id="prog-13", credentials=_credentials(raw_token), session=test_session
    )
    assert token.id == row.id

    with pytest.raises(HTTPException) as exc_info:
        await get_ingest_token(
            program_id="prog-99", credentials=_credentials(raw_token), session=test_session
        )
    assert exc_info.value.status_code == 403


# -----------------------------------------------------------------------------
# ING-01-TC-18 (FR-5) -- log event key set equals the exact allowlist.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_event_key_set_exact_allowlist_tc18(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    ingest_auth_logger_records: list[logging.LogRecord],
) -> None:
    raw_token, row = await _seed_token(
        test_session,
        label="tc18-key-set",
        user_email="owner@example.com",
        allowed_program_ids=[],
        revoked_at=datetime(2026, 8, 1, tzinfo=UTC),
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_ingest_token(
            program_id="prog-14", credentials=_credentials(raw_token), session=test_session
        )
    assert exc_info.value.status_code == 401

    assert len(ingest_auth_logger_records) == 1
    payload = _formatted_payloads(ingest_auth_logger_records)[0]

    # Allowlist, not a denylist: the key set is exactly the FR-5 fields
    # (token_id, reason, program_id) plus JSONFormatter's own first-class
    # meta (timestamp, level, logger, message) -- never a bare four-key dict.
    assert set(payload.keys()) == {
        "timestamp",
        "level",
        "logger",
        "message",
        "token_id",
        "reason",
        "program_id",
    }
    assert "user_email" not in payload
    assert payload["reason"] == "revoked"
    assert payload["token_id"] == row.id
    assert payload["program_id"] == "prog-14"

    raw_formatted = JSONFormatter().format(ingest_auth_logger_records[0])
    assert raw_token not in raw_formatted
    assert row.token_hash not in raw_formatted
    assert "owner@example.com" not in raw_formatted


# -----------------------------------------------------------------------------
# ING-01-TC-19 (FR-5) -- reason takes each of the five literal values.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reason_takes_each_of_five_literal_values_tc19(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    ingest_auth_logger_records: list[logging.LogRecord],
) -> None:
    raw_unknown = "hrn_pat_a3b4c5d6a3b4c5d6a3b4c5d6a3b4c5d6a3b4c5d6a3b4c5d6a3b4c5d6a3b4c5d6"
    raw_revoked, _row_revoked = await _seed_token(
        test_session,
        label="tc19-revoked",
        allowed_program_ids=[],
        revoked_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    raw_expired, _row_expired = await _seed_token(
        test_session,
        label="tc19-expired",
        allowed_program_ids=[],
        expires_at=datetime.now(UTC) - timedelta(seconds=60),
    )
    raw_scope, _row_scope = await _seed_token(
        test_session, label="tc19-scope", allowed_program_ids=["prog-other"]
    )

    branches: list[tuple[str, str | None, str]] = [
        ("missing", None, "prog-1"),
        ("unknown", raw_unknown, "prog-1"),
        ("revoked", raw_revoked, "prog-1"),
        ("expired", raw_expired, "prog-1"),
        ("scope", raw_scope, "prog-15"),
    ]

    reasons: list[str] = []
    for expected_reason, raw_token, program_id in branches:
        mark = len(ingest_auth_logger_records)
        with pytest.raises(HTTPException):
            await get_ingest_token(
                program_id=program_id,
                credentials=_credentials(raw_token) if raw_token is not None else None,
                session=test_session,
            )
        new_records = ingest_auth_logger_records[mark:]
        assert len(new_records) == 1
        payload = _formatted_payloads(new_records)[0]
        assert payload["reason"] == expected_reason
        reasons.append(payload["reason"])

    assert set(reasons) == {"missing", "unknown", "revoked", "expired", "scope"}


# -----------------------------------------------------------------------------
# ING-01-TC-20 (FR-5) -- no log event is emitted on a successful check.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_log_event_emitted_on_success_tc20(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    ingest_auth_logger_records: list[logging.LogRecord],
) -> None:
    raw_token, row = await _seed_token(
        test_session, label="tc20-success-silent", allowed_program_ids=[]
    )

    token = await get_ingest_token(
        program_id="prog-16", credentials=_credentials(raw_token), session=test_session
    )
    assert token.id == row.id
    assert ingest_auth_logger_records == []


# -----------------------------------------------------------------------------
# ING-01-TC-24 (FR-3) -- scope check is an opaque string comparison, no UUID
# parsing/canonicalization.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_program_id_scope_check_is_opaque_string_comparison_tc24(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    uuid_program_id = "550e8400-e29b-41d4-a716-446655440000"
    slug_program_id = "prog-slug-18"

    raw_uuid, row_uuid = await _seed_token(
        test_session, label="tc24-uuid-scope", allowed_program_ids=[uuid_program_id]
    )
    raw_slug, row_slug = await _seed_token(
        test_session, label="tc24-slug-scope", allowed_program_ids=[slug_program_id]
    )

    token_uuid = await get_ingest_token(
        program_id=uuid_program_id, credentials=_credentials(raw_uuid), session=test_session
    )
    assert token_uuid.id == row_uuid.id

    token_slug = await get_ingest_token(
        program_id=slug_program_id, credentials=_credentials(raw_slug), session=test_session
    )
    assert token_slug.id == row_slug.id

    # Uppercase-hex variant of the same UUID must NOT match -- a literal
    # string comparison, never a UUID-aware canonicalization.
    with pytest.raises(HTTPException) as exc_info:
        await get_ingest_token(
            program_id=uuid_program_id.upper(),
            credentials=_credentials(raw_uuid),
            session=test_session,
        )
    assert exc_info.value.status_code == 403
