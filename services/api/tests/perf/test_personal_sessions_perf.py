"""Performance test for GET /api/personal-usage/{user_id}/sessions --
SHP-03-NFR-performance (SHP-03-TC-11): a bounded 2-SELECT query-count budget
(items page + total count, DATA-DESIGN.md / PLAN.md § 7) and a p95 duration
under the 2s page-navigation budget across a 10-call sample.

NOTE on TC id: PLAN.md § 7's Test Strategy table cites this file against
"SHP-03-TC-14", but `docs/test-cases/SHP-03.json` only declares TC-01..TC-11
-- there is no TC-14. The one `type: performance` case in that file is
SHP-03-TC-11 ("Single indexed lookup on (user_id, started_at), no N+1,
page-navigation refresh within 2s budget"), whose `given`/`when`/`then` and
`test_data` (250 seeded rows, `page=2&page_size=20`, `query_count_budget: 2`,
`latency_budget_ms: 2000`) match this file's scope exactly. This test is
written against SHP-03-TC-11's content; the TC-14 label in PLAN.md appears
to be a plan-authoring typo and is reported to the orchestrator rather than
silently "corrected" in PLAN.md.

Structure mirrors `tests/perf/test_personal_usage_perf.py` closely: real
`create_app()` (`build_app`/`async_client_for`, `tests/conftest.py`), a
bearer token minted via `POST /auth/dev-bypass`, a `before_cursor_execute`
query-count spy on `test_engine.sync_engine`, the `production_logging`
fixture, and plain `time.perf_counter()` -- no new benchmark tool/runner/
dependency.

Self-view path only: `app/api/personal_usage.py::get_personal_sessions`
calls `individual_usage_visibility(current_user, user_id)` with
`user_id == current_user.user_id`, which short-circuits on the self path in
`app/core/rbac.py` before any persona resolution -- same precedent as
`test_personal_usage_perf.py`. A dev-bypass token always mints a fresh
`uuid4()` `sub` claim (`app/auth/dev_bypass.py`) with no field to override
it, so this file mints the token first and decodes its own `sub` back out
(unverified -- minted in-process, nothing to distrust) to use as the seeded
user id.

Query-count spy: scoped to SELECT statements referencing `user_sessions`
only (this route never touches `usage_events`), word-boundary regex
mirroring `test_personal_usage_perf.py`'s own `_USER_SESSIONS_OR_USAGE_
EVENTS_RE`. Always detached in a `finally` so it can never leak into
sibling tests sharing the session-scoped `test_engine` fixture.

Strictness split (this task's own instructions): the query-count assertion
(exactly 2 SELECTs) is the durable, CI-stable half of this test and is
STRICT -- a third SELECT, or a fetch-all-then-slice rewrite, is exactly the
N+1 / unbounded-fan-out regression `.claude/rules/performance-baseline.md`
guards against, and this repo has an existing precedent
(`test_personal_usage_perf.py`) for enforcing an exact SELECT budget as a
hard assertion. The p95 wall-clock assertion is GENEROUS and clearly
commented: wall-clock timing is inherently machine-dependent, and this repo
has no existing perf-test precedent that tightens the 2000ms NFR budget
below its literal value -- so this file keeps the full 2000ms budget from
TC-11's own `latency_budget_ms` rather than inventing a tighter number.

Honest measurement (matches `test_personal_usage_perf.py`'s own convention):
if the p95 budget is missed, this reports the actual measured value for
escalation -- never loosens the budget, never adds a warmup/retry to hide
the number.
"""

from __future__ import annotations

import base64
import json
import re
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.db import get_db
from app.models.rollup import UserSessions
from tests.conftest import AlembicRunner

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

# SHP-03-TC-11 test_data -- do not relax (this task's own instructions: the
# query-count budget is the strict half of this test).
QUERY_COUNT_BUDGET = 2
LATENCY_BUDGET_MS = 2000.0

_SEEDED_ROW_COUNT = 250
_SAMPLE_CALLS = 10
_PAGE = 2
_PAGE_SIZE = 20
_FIXTURE_PROGRAM_ID = "prog-shp03-perf-fixture"
_USER_SESSIONS_RE = re.compile(r"\buser_sessions\b", re.IGNORECASE)


@dataclass
class _SelectCounter:
    """Captures every SELECT statement referencing `user_sessions` seen while
    this counter's context manager is active."""

    count: int = 0
    statements: list[str] = field(default_factory=list)


@contextmanager
def _count_user_sessions_selects(engine: AsyncEngine) -> Iterator[_SelectCounter]:
    """Attach a `before_cursor_execute` listener to `engine.sync_engine` for
    the duration of the `with` block, counting SELECTs against
    `user_sessions` (SHP-03-TC-11's 2-SELECT budget: the paginated row
    lookup + `count(*)`).

    Mirrors `tests/perf/test_personal_usage_perf.py::_count_personal_usage_
    selects`. Detaches in `finally` so the listener cannot leak into sibling
    tests that share the session-scoped `test_engine` fixture.
    """
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


def _decode_unverified_claims(token: str) -> dict[str, Any]:
    """Read a JWT's payload claims WITHOUT verifying its signature.

    Mirrors `tests/perf/test_personal_usage_perf.py::_decode_unverified_
    claims` -- the token was just minted in-process by this same test, so
    there is nothing to distrust.
    """
    payload_segment = token.split(".")[1]
    padding = "=" * (-len(payload_segment) % 4)
    return json.loads(base64.urlsafe_b64decode(payload_segment + padding))


async def _mint_dev_bypass_token(client: AsyncClient) -> tuple[str, str]:
    """`POST /auth/dev-bypass` and return `(access_token, user_id)`, where
    `user_id` is the token's own `sub` claim -- see module docstring."""
    resp = await client.post("/auth/dev-bypass", json={})
    assert resp.status_code == 200, resp.text
    token = str(resp.json()["access_token"])
    return token, str(_decode_unverified_claims(token)["sub"])


def _user_session_row(*, user_id: str, idx: int, now: datetime) -> dict[str, Any]:
    """One `user_sessions` row with every NOT NULL column
    (`app/models/rollup.py::UserSessions`) explicitly set.

    `started_at` staggers by `idx` minutes so `ORDER BY started_at DESC, id
    ASC` (SHP-03-FR-2) has real, non-degenerate ordering to do across 250
    rows, matching TC-11's own precondition.
    """
    return {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "program_id": _FIXTURE_PROGRAM_ID,
        "session_identifier": f"perf-sess-{user_id}-{idx}-{uuid.uuid4()}",
        "name": f"perf session {idx}",
        "started_at": now - timedelta(minutes=idx),
        "duration_seconds": 600,
        "tokens": 1000 * (idx + 1),
    }


async def _seed_personal_sessions_rows(test_session: AsyncSession, *, user_id: str) -> None:
    """Seed `_SEEDED_ROW_COUNT` (250, per TC-11) `user_sessions` rows for
    `user_id`, so both budgeted SELECTs (the page lookup and the count) do
    real, non-trivial work.
    """
    now = datetime.now(UTC)
    rows = [
        _user_session_row(user_id=user_id, idx=idx, now=now) for idx in range(_SEEDED_ROW_COUNT)
    ]
    await test_session.execute(sa.insert(UserSessions), rows)
    await test_session.commit()


@pytest.mark.asyncio
async def test_personal_sessions_query_count_and_p95_budget(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """SHP-03-TC-11: exactly `QUERY_COUNT_BUDGET` (2) SELECTs against
    `user_sessions` per call, and p95 duration under `LATENCY_BUDGET_MS`
    across a `_SAMPLE_CALLS`-call sample, for a self-view
    `GET /api/personal-usage/{user_id}/sessions?page=2&page_size=20` request
    against 250 seeded rows.
    """
    app = build_app()

    test_session_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    async with async_client_for(app) as client:
        token, user_id = await _mint_dev_bypass_token(client)
        await _seed_personal_sessions_rows(test_session, user_id=user_id)
        headers = {"Authorization": f"Bearer {token}"}

        durations_ms: list[float] = []
        per_call_query_counts: list[int] = []
        last_statements: list[str] = []

        for _ in range(_SAMPLE_CALLS):
            with _count_user_sessions_selects(test_engine) as counter:
                started = time.perf_counter()
                resp = await client.get(
                    f"/api/personal-usage/{user_id}/sessions"
                    f"?page={_PAGE}&page_size={_PAGE_SIZE}",
                    headers=headers,
                )
                elapsed_ms = (time.perf_counter() - started) * 1000

            assert resp.status_code == 200, resp.text
            durations_ms.append(elapsed_ms)
            per_call_query_counts.append(counter.count)
            last_statements = counter.statements

    # Strict: exactly 2 SELECTs (items page + count(*)) on EVERY call in the
    # sample -- a third query or a fetch-all-then-slice rewrite is the
    # regression this test exists to catch (.claude/rules/performance-
    # baseline.md: no N+1, no unbounded fan-out).
    for call_idx, count in enumerate(per_call_query_counts):
        assert count == QUERY_COUNT_BUDGET, (
            f"call {call_idx}: expected exactly {QUERY_COUNT_BUDGET} SELECTs against "
            f"user_sessions, got {count}: {last_statements}"
        )

    durations_ms.sort()
    p95_index = min(int(len(durations_ms) * 0.95), len(durations_ms) - 1)
    p95_ms = durations_ms[p95_index]

    # Honest measurement: report the actual number, don't hide a breach.
    print(
        f"\nSHP-03-TC-11 baseline -- personal-sessions handler p95={p95_ms:.2f}ms "
        f"over {_SAMPLE_CALLS} calls (budget {LATENCY_BUDGET_MS}ms), "
        f"raw durations={[f'{d:.2f}' for d in durations_ms]}"
    )

    # Generous/commented on purpose (this task's own instructions): wall-clock
    # timing is machine-dependent and this repo has no existing perf-test
    # precedent tightening the NFR's literal 2000ms budget below its own
    # value -- so this assertion keeps the full budget from TC-11's own
    # `latency_budget_ms` rather than a stricter derived number. The
    # query-count assertion above is the strict, CI-stable half of this test.
    assert p95_ms < LATENCY_BUDGET_MS, (
        f"GET /api/personal-usage/{{user_id}}/sessions p95 latency {p95_ms:.2f}ms "
        f"exceeds the SHP-03-TC-11 budget of {LATENCY_BUDGET_MS}ms over {_SAMPLE_CALLS} calls. "
        "Do not relax this budget; report the measured value for escalation/optimization."
    )
