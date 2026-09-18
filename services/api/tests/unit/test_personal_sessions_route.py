"""Route-level tests for `GET /api/personal-usage/{user_id}/sessions`
(`app/api/personal_usage.py::get_personal_sessions`) -- SHP-03-TC-03 through
TC-11 (`docs/test-cases/SHP-03.json`). PLAN.md § 7 assigns this ONE file all of
the unit/contract + security + integration coverage for the route (TC-01/TC-02
are the meta-composite/ordering cases owned elsewhere per tasks.json's file
plan -- not duplicated here).

Scaffold mirrors `tests/unit/test_personal_usage.py` exactly (same file, same
router, same `user_sessions` table): `build_app`/`async_client_for`/
`migrated_db`/`test_session` fixtures from `tests/conftest.py`, the `get_db`
dependency override, `POST /auth/dev-bypass` token minting with the token's
own `sub` claim decoded back out (unverified -- minted in-process, nothing to
distrust) as the real seeded `user_id`, and the local `rbac.configure()` +
`_capture_rbac_logger` stubs for the cross-user RBAC cases.

TC-06 clarification note: the story's own AC-3 text says `page_size > 100`
returns HTTP 400. The PRD's FR-3, `app/dependencies/pagination.py`'s
`get_page_params()`, and `docs/test-cases/SHP-03.json` TC-06 all agree the
shipped behaviour is CLAMP-to-100 + 200, not reject. This file tests the
clamp, matching every other paginated consumer in this codebase -- see
`get_page_params`'s own docstring and `app/api/personal_usage.py`'s module
docstring "SHP-03-FR-3" section. FLIP per TC-06's own instructions if the PO
ever signs off on the story's literal 400 instead.

Log-absence non-vacuity: this repo's Alembic `fileConfig` disables every
`app.*` logger process-wide (prior verified finding -- see this project's
implementation-agent memory on the subject), so a bare "logger did not fire"
assertion after a `migrated_db` test can pass for the wrong reason (the
logger being silently disabled, not because nothing happened). Every self-
access "not logged" assertion below is therefore paired, in the SAME test, on
the SAME captured handler, with a positive control: a cross-user request in
the identical test that DOES trigger `individual_view_denied` and is asserted
to have fired. That proves the handler/logger plumbing was live for the whole
test, so the earlier absence assertion has teeth.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core import rbac
from app.core.db import get_db
from app.core.logging import JSONFormatter
from app.core.persona_resolver import PersonaResolver
from app.models.rollup import UserSessions
from tests.conftest import AlembicRunner

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

# Cross-story aggregate is enforced elsewhere (ADR-0009) -- this value only
# needs to satisfy the NOT NULL `program_id` column on `user_sessions`.
_FIXTURE_PROGRAM_ID = "prog-shp03-tc-fixture"

_USER_SESSIONS_RE = re.compile(r"\buser_sessions\b")


# -----------------------------------------------------------------------------
# App + DB-override scaffold (mirrors test_personal_usage.py).
# -----------------------------------------------------------------------------


def _db_override(session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _get_db() -> AsyncIterator[AsyncSession]:
        yield session

    return _get_db


def _build_personal_usage_app(
    build_app: Callable[..., FastAPI], test_session: AsyncSession, **settings_overrides: Any
) -> FastAPI:
    """Real `create_app()` (`build_app` fixture) wired for HTTP-level testing
    against a live DB. Hermetic default settings already set
    `environment="test"` (in `NON_PRODUCTION_ENVIRONMENTS`), so
    `/auth/dev-bypass` is registered and its tokens verify without any OIDC
    config."""
    app = build_app(**settings_overrides)
    app.dependency_overrides[get_db] = _db_override(test_session)
    return app


def _decode_unverified_claims(token: str) -> dict[str, Any]:
    """Read a JWT's payload claims WITHOUT verifying its signature -- the
    token was just minted in-process by this same test, there is nothing to
    distrust. Mirrors `test_personal_usage.py::_decode_unverified_claims`."""
    payload_segment = token.split(".")[1]
    padding = "=" * (-len(payload_segment) % 4)
    return json.loads(base64.urlsafe_b64decode(payload_segment + padding))


async def _mint_dev_bypass_token(
    client: AsyncClient, *, role: str = "developer"
) -> tuple[str, str]:
    """`POST /auth/dev-bypass` and return `(access_token, user_id)`, where
    `user_id` is the token's own `sub` claim (see module docstring)."""
    resp = await client.post("/auth/dev-bypass", json={"role": role})
    assert resp.status_code == 200, resp.text
    token = str(resp.json()["access_token"])
    return token, str(_decode_unverified_claims(token)["sub"])


# -----------------------------------------------------------------------------
# Seeding helpers.
# -----------------------------------------------------------------------------


def _user_session_row(
    *,
    id_: str | None = None,
    user_id: str,
    days_ago: int,
    tokens: int = 1000,
    duration_seconds: int = 600,
    now: datetime,
    session_identifier: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    """One `user_sessions` row with every NOT NULL column
    (`app/models/rollup.py::UserSessions`) explicitly set."""
    row_id = id_ or str(uuid.uuid4())
    return {
        "id": row_id,
        "user_id": user_id,
        "program_id": _FIXTURE_PROGRAM_ID,
        "session_identifier": session_identifier or f"sess-{user_id}-{days_ago}-{row_id}",
        "name": name or f"session {days_ago}d ago",
        "started_at": now - timedelta(days=days_ago),
        "duration_seconds": duration_seconds,
        "tokens": tokens,
    }


# -----------------------------------------------------------------------------
# Log capture -- mirrors test_personal_usage.py's own
# `_RecordCapturingHandler`/`_capture_rbac_logger`, duplicated locally per that
# file's independent-ownership precedent.
# -----------------------------------------------------------------------------


class _RecordCapturingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _capture_rbac_logger(level: int = logging.INFO) -> Iterator[list[logging.LogRecord]]:
    """Attach a real handler to the actual `app.core.rbac` logger, forcing it
    enabled for the duration of the block.

    This is the fix for the Alembic `fileConfig` gotcha: `disabled` is
    explicitly forced to `False` here (not merely left alone), so an
    absence assertion made against `records` inside this context is
    guaranteed to reflect "the logger ran and emitted nothing", never
    "the logger was silently disabled and nothing could have been
    captured regardless of what happened".
    """
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


class _StubPersonaResolver:
    """Mirrors `test_personal_usage.py`'s own stub -- `individual_usage_
    visibility`'s non-self path resolves persona through `app.core.rbac`'s
    module-global `configure()` seam, not `request.app.state.persona_
    resolver`."""

    def __init__(self, *, mapping: dict[str, str]) -> None:
        self._mapping = mapping

    async def resolve(self, role: str) -> str:
        return self._mapping[role]


@contextmanager
def _stub_persona_resolver(mapping: dict[str, str]) -> Iterator[None]:
    """Swap in a stub `PersonaResolver` for the duration of the block,
    restored in `finally` so no test can leak a stub resolver into a later
    test/file."""
    original_persona_resolver = rbac._persona_resolver
    rbac.configure(cast(PersonaResolver, _StubPersonaResolver(mapping=mapping)))
    try:
        yield
    finally:
        rbac._persona_resolver = original_persona_resolver


# -----------------------------------------------------------------------------
# Query-count spy for TC-11 -- mirrors
# `tests/perf/test_personal_usage_perf.py::_count_personal_usage_selects`,
# scoped to `user_sessions` only (this route never touches `usage_events`).
# -----------------------------------------------------------------------------


@dataclass
class _SelectCounter:
    count: int = 0
    statements: list[str] = field(default_factory=list)


@contextmanager
def _count_user_sessions_selects(engine: AsyncEngine) -> Iterator[_SelectCounter]:
    counter = _SelectCounter()
    sync_engine = engine.sync_engine

    def _before_cursor_execute(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        is_select = statement.strip().upper().startswith("SELECT")
        if is_select and _USER_SESSIONS_RE.search(statement):
            counter.count += 1
            counter.statements.append(statement)

    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield counter
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before_cursor_execute)


# -----------------------------------------------------------------------------
# SHP-03-TC-03 -- zero sessions -> 200 {items: [], total: 0}, defaults intact.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zero_sessions_returns_empty_page_not_error_tc03(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    app = _build_personal_usage_app(build_app, test_session)

    async with async_client_for(app) as client:
        token, user_id = await _mint_dev_bypass_token(client)
        # No user_sessions rows seeded for this user_id.
        resp = await client.get(
            f"/api/personal-usage/{user_id}/sessions",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"items": [], "page": 1, "page_size": 20, "total": 0}


# -----------------------------------------------------------------------------
# SHP-03-TC-04 -- page far beyond the result set -> 200 {items: [], total: N}.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_page_beyond_available_range_returns_empty_items_true_total_tc04(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    app = _build_personal_usage_app(build_app, test_session)

    async with async_client_for(app) as client:
        token, user_id = await _mint_dev_bypass_token(client)

        now = datetime.now(UTC)
        rows = [
            _user_session_row(user_id=user_id, days_ago=d, now=now) for d in (0, 1, 2)
        ]
        await test_session.execute(sa.insert(UserSessions), rows)
        await test_session.commit()

        resp = await client.get(
            f"/api/personal-usage/{user_id}/sessions?page=5&page_size=20",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 3
    assert body["page"] == 5
    assert body["page_size"] == 20


# -----------------------------------------------------------------------------
# SHP-03-TC-05 -- page<1 / page_size<1 reject 422 via Query(ge=1), no data body.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_page_lt_1_and_page_size_lt_1_reject_422_tc05(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    app = _build_personal_usage_app(build_app, test_session)

    async with async_client_for(app) as client:
        token, user_id = await _mint_dev_bypass_token(client)

        now = datetime.now(UTC)
        await test_session.execute(
            sa.insert(UserSessions), [_user_session_row(user_id=user_id, days_ago=0, now=now)]
        )
        await test_session.commit()

        resp_page = await client.get(
            f"/api/personal-usage/{user_id}/sessions?page=0&page_size=20",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp_page_size = await client.get(
            f"/api/personal-usage/{user_id}/sessions?page=1&page_size=0",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp_page.status_code == 422
    assert "items" not in resp_page.json()
    assert resp_page_size.status_code == 422
    assert "items" not in resp_page_size.json()


# -----------------------------------------------------------------------------
# SHP-03-TC-06 -- [CLARIFICATION-SENSITIVE] page_size>100 CLAMPS to 100 + 200,
# NOT the story's literal AC-3 400 text. See module docstring / TC-06's own
# "FLIP THIS TEST" instructions in docs/test-cases/SHP-03.json.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_page_size_over_100_clamps_to_100_returns_200_not_400_tc06(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PRD FR-3 resolution of the story-vs-shipped-code conflict: `page_size=250`
    clamps to 100 and returns 200 with exactly 100 items, `total` unaffected.
    Do NOT "fix" this to expect 400 -- see `app/api/personal_usage.py`'s
    "SHP-03-FR-3" docstring section and `app/dependencies/pagination.py`
    (sealed cross-story contract, BED-02 D-01)."""
    app = _build_personal_usage_app(build_app, test_session)

    async with async_client_for(app) as client:
        token, user_id = await _mint_dev_bypass_token(client)

        now = datetime.now(UTC)
        rows = [
            _user_session_row(user_id=user_id, days_ago=d, now=now) for d in range(105)
        ]
        await test_session.execute(sa.insert(UserSessions), rows)
        await test_session.commit()

        resp = await client.get(
            f"/api/personal-usage/{user_id}/sessions?page=1&page_size=250",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["page_size"] == 100
    assert len(body["items"]) == 100
    assert body["total"] == 105


# -----------------------------------------------------------------------------
# SHP-03-TC-07 / TC-08 / TC-09 -- RBAC: self always allowed, cross-user
# non-cio denied 403 (no data body, individual_view_denied logged), cross-user
# cio allowed. Combined into one test per user_id so the positive control
# (denial firing) and the negative control (self access not firing) share the
# SAME live-forced logger handler -- see module docstring on non-vacuity.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_self_access_allowed_and_not_logged_tc07(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """SHP-03-TC-07 (self access allowed, independent of persona) PLUS the
    D-04/R-03 "not logged on self-access" assertion, made non-vacuous by a
    positive control fired in the SAME test on the SAME captured handler:
    a cross-user request that DOES trigger individual_view_denied."""
    app = _build_personal_usage_app(build_app, test_session)

    async with async_client_for(app) as client:
        token, user_id = await _mint_dev_bypass_token(client, role="architect")

        now = datetime.now(UTC)
        await test_session.execute(
            sa.insert(UserSessions),
            [_user_session_row(user_id=user_id, days_ago=0, now=now, name="own session")],
        )
        await test_session.commit()

        with _capture_rbac_logger() as records:
            self_resp = await client.get(
                f"/api/personal-usage/{user_id}/sessions",
                headers={"Authorization": f"Bearer {token}"},
            )

            # Positive control (proves the handler is live, non-vacuous
            # negative assertion below): a cross-user request in the SAME
            # capture window that DOES deny + log.
            with _stub_persona_resolver({"architect": "architect"}):
                other_user_id = f"usr-shp03-tc07-other-{uuid.uuid4()}"
                cross_resp = await client.get(
                    f"/api/personal-usage/{other_user_id}/sessions",
                    headers={"Authorization": f"Bearer {token}"},
                )

    assert self_resp.status_code == 200, self_resp.text
    body = self_resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["title"] == "own session"

    assert cross_resp.status_code == 403

    denied_events = [r for r in records if r.getMessage() == "individual_view_denied"]
    # Positive control fired -- proves the handler was live for this window.
    assert len(denied_events) == 1
    # Only the cross-user call produced a denial; the self-access call above
    # produced none, given the handler was demonstrably capable of capturing
    # one in this same window.
    assert denied_events[0].target_user_id == other_user_id  # type: ignore[attr-defined]


# -----------------------------------------------------------------------------
# SHP-03-TC-08 -- cross-user + non-cio denied 403, no data body, logged once.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_user_non_cio_denied_bare_403_logged_tc08(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    app = _build_personal_usage_app(build_app, test_session)

    with _stub_persona_resolver({"developer": "developer"}):
        async with async_client_for(app) as client:
            token, _requester_user_id = await _mint_dev_bypass_token(client, role="developer")
            target_user_id = f"usr-shp03-tc08-target-{uuid.uuid4()}"

            now = datetime.now(UTC)
            await test_session.execute(
                sa.insert(UserSessions),
                [_user_session_row(user_id=target_user_id, days_ago=0, now=now)],
            )
            await test_session.commit()

            with _capture_rbac_logger() as records:
                resp = await client.get(
                    f"/api/personal-usage/{target_user_id}/sessions",
                    headers={"Authorization": f"Bearer {token}"},
                )

    assert resp.status_code == 403
    assert resp.json() == {"error": {"code": "http_403", "message": "Forbidden", "details": None}}
    body_keys = set(resp.json().keys())
    assert "items" not in body_keys and "total" not in body_keys

    denied_events = [r for r in records if r.getMessage() == "individual_view_denied"]
    assert len(denied_events) == 1

    payload = json.loads(JSONFormatter().format(denied_events[0]))
    assert payload["outcome"] == "denied"
    assert set(payload.keys()) == {
        "timestamp",
        "level",
        "logger",
        "message",
        "user_id",
        "target_user_id",
        "outcome",
    }


# -----------------------------------------------------------------------------
# SHP-03-TC-09 -- cio persona requesting another user's sessions -> 200,
# no individual_view_denied logged.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cio_cross_user_access_allowed_no_denial_logged_tc09(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    app = _build_personal_usage_app(build_app, test_session)

    with _stub_persona_resolver({"cio": "cio"}):
        async with async_client_for(app) as client:
            token, _cio_user_id = await _mint_dev_bypass_token(client, role="cio")
            target_user_id = f"usr-shp03-tc09-target-{uuid.uuid4()}"

            now = datetime.now(UTC)
            await test_session.execute(
                sa.insert(UserSessions),
                [
                    _user_session_row(
                        user_id=target_user_id, days_ago=0, now=now, name="target session"
                    )
                ],
            )
            await test_session.commit()

            with _capture_rbac_logger() as records:
                resp = await client.get(
                    f"/api/personal-usage/{target_user_id}/sessions",
                    headers={"Authorization": f"Bearer {token}"},
                )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["title"] == "target session"

    denied_events = [r for r in records if r.getMessage() == "individual_view_denied"]
    assert len(denied_events) == 0


# -----------------------------------------------------------------------------
# SHP-03-TC-10 -- missing/invalid bearer token -> 401, no RBAC log, no data.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_or_invalid_bearer_token_returns_401_tc10(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    app = _build_personal_usage_app(build_app, test_session)

    async with async_client_for(app) as client:
        user_id = f"usr-shp03-tc10-{uuid.uuid4()}"
        now = datetime.now(UTC)
        await test_session.execute(
            sa.insert(UserSessions), [_user_session_row(user_id=user_id, days_ago=0, now=now)]
        )
        await test_session.commit()

        with _capture_rbac_logger() as records:
            resp_missing = await client.get(f"/api/personal-usage/{user_id}/sessions")
            resp_malformed = await client.get(
                f"/api/personal-usage/{user_id}/sessions",
                headers={"Authorization": "Bearer not-a-real-jwt"},
            )

    assert resp_missing.status_code == 401
    assert "items" not in resp_missing.json()
    assert resp_malformed.status_code == 401
    assert "items" not in resp_malformed.json()

    # 401 is an authn failure, distinct from the individual_view_denied authz
    # event -- neither call should reach the RBAC check at all.
    denied_events = [r for r in records if r.getMessage() == "individual_view_denied"]
    assert len(denied_events) == 0


# -----------------------------------------------------------------------------
# SHP-03-TC-11 -- single indexed SELECT (+ at most one COUNT), no N+1.
# Latency/p95 is NOT asserted here (that lives in a dedicated
# tests/perf/*.py per this codebase's own perf/unit split, e.g.
# test_personal_usage_perf.py) -- this route test covers the query-count
# half of NFR-performance only.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sessions_page_single_indexed_select_no_n_plus_1_tc11(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    app = _build_personal_usage_app(build_app, test_session)

    async with async_client_for(app) as client:
        token, user_id = await _mint_dev_bypass_token(client)

        now = datetime.now(UTC)
        rows = [_user_session_row(user_id=user_id, days_ago=d, now=now) for d in range(60)]
        await test_session.execute(sa.insert(UserSessions), rows)
        await test_session.commit()

        with _count_user_sessions_selects(test_engine) as counter:
            resp = await client.get(
                f"/api/personal-usage/{user_id}/sessions?page=2&page_size=20",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 20
    assert body["total"] == 60

    # Exactly 2 SELECTs against user_sessions: the paginated row lookup + the
    # COUNT(*) for total -- no per-row fan-out (query_count_budget: 2).
    assert counter.count == 2, (
        f"expected exactly 2 user_sessions SELECTs, got {counter.count}: {counter.statements}"
    )
