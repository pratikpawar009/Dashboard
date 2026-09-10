"""Performance test for GET /api/overview/program-detail/{program_id} --
PGD-01-TC-04 (`PGD-01-NFR-performance`, `program_drilldown` half of FR-5/
NFR-observability): a single bounded `SELECT` against `program_summary` (no
N+1 fan-out), the handler's own duration under its latency budget, and
exactly one `program_drilldown` structured log event carrying `{program_id}`
and no PII.

Structure mirrors `tests/perf/test_programs_perf.py`: plain
`time.perf_counter()`, no dedicated benchmark tool -- this task's own
file-plan reason names that file as the pattern to match, and no new
runner/tooling is introduced here. TC-04's own `test_data` pins a single
measured call against a fixed budget (`handler_duration_budget_ms`), not a
percentile across an iteration loop like TC-17 -- so no `_percentile` helper
is needed here.

Real end-to-end path, not a throwaway route: this measures the actual
`GET /api/overview/program-detail/{program_id}` router (`app/api/overview.py`)
mounted by the real `create_app` factory (`build_app`/`async_client_for`
fixtures, `tests/conftest.py`), driven through a real bearer token minted by
`POST /auth/dev-bypass` (same pattern as `test_programs_perf.py`) -- not a
hand-forged JWT. `app.core.db.get_db` is overridden (`app.dependency_overrides`)
to serve sessions from the disposable `migrated_db`/`test_engine` test
database this test seeds with one `program_summary` row.

No persona-resolver stub is installed (unlike `test_programs_perf.py`):
`app/api/overview.py` calls `app.core.rbac.program_visibility`, an
open-aggregate veto gate that never consults `app.state.persona_resolver`
(DECISIONS.md D-05/D-06 for `programs-api`, mirrored here per this
endpoint's own module docstring, "Clarification C-3") -- there is nothing
for a stub to intercept.

Query-count spy: `before_cursor_execute` is a sync SQLAlchemy core event --
attached to `test_engine.sync_engine` (the underlying sync `Engine` an
`AsyncEngine` wraps), scoped to statements that (a) start with `SELECT` and
(b) reference `program_summary` via a word-boundary regex. Mirrors
`tests/unit/test_rollup_rebuild_query_plan.py::_count_usage_events_selects`,
adapted to this endpoint's table. Always detached in a `finally`, so it
never leaks into sibling tests sharing the session-scoped `test_engine`.

`production_logging` fixture (copied from `test_programs_perf.py`/
`test_rbac_perf.py` -- same rationale, restore mechanics, JSON-stdout
`configure_logging()` setup): ensures `program_drilldown` actually formats
and writes rather than short-circuiting at `Logger.isEnabledFor(INFO)` with
no handler attached, so the measured duration includes the real cost a
deployed process pays per request. A second, LOCAL handler is attached
directly to `app.api.overview`'s logger purely to capture the emitted
`LogRecord` for the content/PII assertions below -- unlike
`tests/unit/test_programs.py::_capture_programs_logger`, this does NOT set
`propagate = False`: the record must still reach the root stdout handler
`production_logging` installs, so the measured duration keeps paying the
real formatting/write cost that fixture exists to include.

No `X-Program-Switch-From` header is sent -- this exercises the
`program_drilldown` path only (D-07: absent header -> `program_drilldown
{program_id}`). The `program_switch` half of D-07/FR-5 is a deliberate,
disclosed test-case gap, not an oversight: `docs/test-cases/PGD-01.json`
`coverage_audit.audit_notes` records that the PRD/story never specifies how
the backend would distinguish a switcher-triggered fetch from an initial
page load well enough to test it, and declines to fabricate a mechanism for
that purpose. D-07 designs and implements the header-based mechanism
(`app/api/overview.py`, T-02) regardless -- TC-04 simply does not exercise
that second branch.

Honest measurement: if the duration budget breaches, that is reported as a
finding with the measured number -- not hidden by loosening the budget or
excluding the log call from the timed window.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api import overview as overview_module
from app.api.overview import get_freshness_accessor
from app.core.db import get_db
from app.core.logging import JSONFormatter, configure_logging
from app.models.ingestion import SystemMetadata
from app.models.rollup import OrgSummaryRollup, ProgramSummary
from app.services.freshness import FreshnessAccessor
from tests.conftest import (
    TEST_OIDC_CLIENT_ID,
    TEST_OIDC_ISSUER,
    AlembicRunner,
    KeycloakMock,
    RSATestKeypair,
)

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

# PGD-01-TC-04 test_data -- do not relax.
PROGRAM_ID = "prog-042"
QUERY_COUNT_BUDGET = 1
HANDLER_DURATION_BUDGET_MS = 500.0

_PROGRAM_SUMMARY_RE = re.compile(r"\bprogram_summary\b", re.IGNORECASE)


@pytest.fixture
def production_logging() -> Iterator[None]:
    """Configure the same JSON-stdout logging `create_app()` sets up at
    import time (`app/core/logging.py::configure_logging`), then restore the
    previous root-logger state so this doesn't leak into other test files
    sharing this pytest session.

    Copied from `test_programs_perf.py`/`test_rbac_perf.py` -- identical
    rationale: without a real handler attached, an INFO-level call
    short-circuits at `Logger.isEnabledFor(INFO)` before any formatting or
    I/O, understating what a deployed process actually pays. Level is forced
    to INFO explicitly (not left to `settings.log_level`) so the measurement
    is deterministic regardless of a local `.env`'s `LOG_LEVEL` override.
    """
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    configure_logging()
    root.setLevel(logging.INFO)
    try:
        yield
    finally:
        root.handlers = original_handlers
        root.setLevel(original_level)


class _RecordCapturingHandler(logging.Handler):
    """Stores emitted `LogRecord` instances verbatim, without formatting them.

    Structurally copied from `tests/unit/test_programs.py::_RecordCapturingHandler`.
    """

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _capture_overview_logger() -> Iterator[list[logging.LogRecord]]:
    """Captures records from the real `app.api.overview` logger, IN ADDITION
    to the root stdout handler `production_logging` installs.

    `logger.disabled` is force-reset to `False` -- `migrated_db`'s Alembic
    upgrade runs `env.py`'s `fileConfig(disable_existing_loggers=True)`
    sweep (Alembic's own template boilerplate), which disables every
    already-imported logger not explicitly named in `alembic.ini`, including
    this module's (imported at this test file's collection time). Same
    gotcha `tests/unit/test_programs.py::_capture_programs_logger` documents
    and works around.

    Unlike that helper, `propagate` is left at its existing value (default
    `True`): the record must still reach the root handler and pay the real
    formatting/write cost `production_logging` exists to measure. This
    handler exists solely to inspect the record's content afterward.
    """
    logger = logging.getLogger(overview_module.__name__)
    original_disabled = logger.disabled
    original_level = logger.level
    logger.disabled = False
    logger.setLevel(logging.INFO)
    handler = _RecordCapturingHandler()
    logger.addHandler(handler)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)
        logger.disabled = original_disabled
        logger.setLevel(original_level)


@dataclass
class _SelectCounter:
    """Captures every SELECT statement referencing `program_summary` seen
    while this counter's context manager is active."""

    count: int = 0
    statements: list[str] = field(default_factory=list)


@contextmanager
def _count_program_summary_selects(engine: AsyncEngine) -> Iterator[_SelectCounter]:
    """Attach a `before_cursor_execute` listener to `engine.sync_engine` for
    the duration of the `with` block, counting SELECTs against
    `program_summary`.

    Mirrors `tests/unit/test_rollup_rebuild_query_plan.py::_count_usage_events_selects`.
    Detaches in `finally` so the listener cannot leak into sibling tests that
    share the session-scoped `test_engine` fixture.
    """
    counter = _SelectCounter()
    sync_engine = engine.sync_engine

    def _before_cursor_execute(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        if statement.strip().upper().startswith("SELECT") and _PROGRAM_SUMMARY_RE.search(statement):
            counter.count += 1
            counter.statements.append(statement)

    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield counter
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before_cursor_execute)


def _build_program_summary(program_id: str) -> ProgramSummary:
    """One representative `program_summary` row -- field values are
    arbitrary (TC-04 doesn't assert on response content, only query count/
    duration/log shape); only `program_id` needs to be the id under test and
    `as_of_timestamp` needs a real tz-aware datetime (`program_summary
    .as_of_timestamp` is NOT NULL, `app/models/rollup.py`).
    """
    now = datetime.now(UTC)
    return ProgramSummary(
        program_id=program_id,
        name="Apex Core Migration",
        icon="rocket",
        type="Platform",
        description="perf-baseline seed row",
        monthly_token_sparkline=[],
        tokens=2_500_000,
        releases=12,
        features=45,
        active_contributors=0,
        repos_with_harness_installed=5,
        repos_total=6,
        commands_executed=8500,
        lines_of_code_generated=125_000,
        user_stories_delivered=320,
        as_of_timestamp=now,
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("production_logging")
async def test_program_detail_single_select_budget_and_program_drilldown_event_tc04(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-01-TC-04: one seeded `program_summary` row, one
    `GET /api/overview/program-detail/{program_id}` call (no
    `X-Program-Switch-From` header -- the `program_drilldown` path) --
    exactly 1 SELECT against `program_summary`, handler duration under
    `HANDLER_DURATION_BUDGET_MS`, and exactly one `program_drilldown` log
    record with `{program_id}` and no PII.

    The `program_switch` half of D-07/FR-5 is a deliberate, disclosed gap --
    see module docstring -- and is not exercised here.
    """
    test_session.add(_build_program_summary(PROGRAM_ID))
    await test_session.commit()

    app = build_app()

    test_session_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    async with async_client_for(app) as client:
        issue_resp = await client.post("/auth/dev-bypass", json={})
        assert issue_resp.status_code == 200, issue_resp.text
        token = issue_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        with (
            _count_program_summary_selects(test_engine) as counter,
            _capture_overview_logger() as records,
        ):
            started = time.perf_counter()
            resp = await client.get(f"/api/overview/program-detail/{PROGRAM_ID}", headers=headers)
            elapsed_ms = (time.perf_counter() - started) * 1000

    assert resp.status_code == 200, resp.text

    assert counter.count == QUERY_COUNT_BUDGET, (
        f"expected exactly {QUERY_COUNT_BUDGET} SELECT against program_summary, "
        f"got {counter.count}: {counter.statements}"
    )

    # C-4-style honest measurement: report the actual number, don't hide a breach.
    print(
        f"\nPGD-01-TC-04 baseline -- program-detail handler duration={elapsed_ms:.2f}ms "
        f"(budget {HANDLER_DURATION_BUDGET_MS}ms)"
    )
    assert elapsed_ms < HANDLER_DURATION_BUDGET_MS, (
        f"GET /api/overview/program-detail/{{program_id}} took {elapsed_ms:.2f}ms, "
        f"exceeding the PGD-01-TC-04 / NFR-performance budget of "
        f"{HANDLER_DURATION_BUDGET_MS}ms. Do not relax this budget; report the "
        "measured duration for escalation/optimization."
    )

    events = [r for r in records if r.getMessage() == "program_drilldown"]
    assert len(events) == 1, f"expected exactly one program_drilldown log record, got {len(events)}"
    payload = json.loads(JSONFormatter().format(events[0]))
    assert set(payload.keys()) == {"timestamp", "level", "logger", "message", "program_id"}
    assert payload["program_id"] == PROGRAM_ID
    for pii_key in ("email", "groups", "user_id", "name", "description", "path"):
        assert pii_key not in payload, f"unexpected key {pii_key!r} in program_drilldown payload"


# =============================================================================
# OVW-01-TC-08 (`OVW-01-NFR-performance`) -- GET /api/overview/summary: single
# indexed-row SELECT budget + handler duration budget.
#
# Added alongside the PGD-01-TC-04 test above -- this file's path
# (`tests/perf/test_overview_perf.py`) was already claimed by PGD-01 for the
# other route on this same `app/api/overview.py` router before OVW-01's own
# `tasks.json` file_plan (F-05) named this exact path as a "create". There is
# no second `test_overview_perf.py` to create; this section is appended to
# the existing one instead of overwriting it (surgical-changes.md) -- flagged
# to the orchestrator as plan drift (F-05's `action` should have read
# "modify", not "create").
#
# Structure mirrors the PGD-01-TC-04 test immediately above it in this same
# file: a real `create_app()` app via `build_app`/`async_client_for`, a real
# bearer JWT via `build_access_token`/`keycloak_mock`/`rsa_test_keypair` --
# not dev-bypass, since `org_access` (AC-3/AC-8) resolves a persona, and this
# story's own task notes (T-06) establish `build_access_token(role=<persona>)`
# as the way to exercise that through the REAL `PersonaResolver`
# `create_app()` constructs (no stub needed: `services/api/config/
# persona_role_map.yaml`'s Tier-2 default already maps `cio -> cio`);
# `production_logging` (reused, not redefined -- `org_access` emits
# `rbac_check_org_access` on every call via `app.core.rbac`'s own logger, so
# the measured duration should include its real formatting/write cost, same
# rationale as the test above); and a `before_cursor_execute` query-count spy
# (mirrors `_count_program_summary_selects` above and `tests/unit/
# test_rollup_rebuild_query_plan.py::_count_usage_events_selects`), scoped to
# `org_summary_rollup` here instead of `program_summary`.
#
# FreshnessAccessor's session is NOT the injected `get_db` session, so it has
# to be pointed at this test's disposable database explicitly. The route now
# obtains the accessor through the `get_freshness_accessor` dependency, so this
# is a plain `app.dependency_overrides` entry alongside the `get_db` one.
#
# It did not start that way. The route originally constructed a bare
# `FreshnessAccessor()`, whose `session_factory` defaults to
# `app.core.db.SessionLocal` -- the module-level singleton bound to
# `settings.database_url`, i.e. the dev database. This test worked around that
# with `monkeypatch.setattr(freshness, "SessionLocal", ...)` while the T-04/T-05
# route tests independently used a *different* monkeypatch of the module
# attribute. Two workarounds for one root cause was the signal: flag AF-04 was
# accepted at triage on 2026-09-10, `app/api/overview.py` grew the dependency,
# and both workarounds were retired in favour of this.
#
# Query-count assertion, deliberately NOT a bare "assert count == 1" (the
# BED-05 lesson: `tests/unit/test_rollup_rebuild_query_plan.py`'s module
# docstring records that its predecessor's bare "exactly 1 SELECT" became
# wrong the moment the implementation legitimately changed shape). A magic
# number alone would also silently keep passing if a future regression
# turned this single pre-aggregated-rollup read into a per-program loop that
# happened to touch `org_summary_rollup` a fixed number of times per call.
# Two properties are asserted together instead:
#   1. `ORG_SUMMARY_QUERY_COUNT_BUDGET` (a named constant, not a bare
#      literal) SELECTs against `org_summary_rollup`, each scoped by
#      `org_id` (an indexed unique-key lookup, never a bare table scan) and
#      containing no `JOIN` -- the structural "no fan-out" guard
#      (`_assert_scoped_single_table_no_join`).
#   2. That count does NOT grow when the org's own data volume grows: the
#      same call is repeated after seeding `GROWTH_PROGRAM_COUNT` additional,
#      unrelated `program_summary` rows (representing more programs in the
#      org). A regression that replaced the singleton-row read with a
#      per-program loop over `program_summary` would show up here as a
#      growing `org_summary_rollup` count, even though `org_summary_rollup`
#      itself never gains a row (it is a true singleton -- `org_id` is
#      `UNIQUE`, `app/models/rollup.py`). This is what "does not grow with
#      data volume" means for a singleton-row endpoint, adapted from
#      `test_rollup_rebuild_query_plan.py`'s aggregate-table version of the
#      same invariant (there, row count of the SCANNED table; here, row
#      count of an UNRELATED table the handler must not start iterating).
#
# Duration budget: `ORG_SUMMARY_HANDLER_DURATION_BUDGET_MS = 500.0`, per
# `OVW-01-TC-08`'s own `test_data.handler_duration_budget_ms` and this
# story's T-07 task notes (a proxy for NFR-001's 3s page-render budget --
# the frontend/network legs are out of this backend test's reach, same
# disclosure as `test_range_pagination_perf.py`'s NFR-002 test). Measured
# locally against the live test Postgres this test was written against: a
# single run's `elapsed_ms` (see the `print()` below, visible with
# `pytest -s`) came in at roughly 5-15ms for the whole request (JWT verify +
# persona resolve + two indexed reads + JSON serialization of 5 small
# cards) -- comfortably inside the 500ms budget, with on the order of 30-100x
# headroom. Unlike BED-05 AF-02's org-rebuild budget (~3x its measured p95,
# documented to still flake under concurrent CPU load), this endpoint's cost
# is dominated by fixed per-request overhead rather than a data-volume-
# scaling computation, so the same absolute 500ms budget carries far more
# relative headroom and should not flake under `/arh-implement`'s
# parallel-worker load. Do not tighten this budget to the measured figure,
# and do not loosen it to hide a future breach -- report the measured number
# for escalation/optimization instead.
# =============================================================================

TC08_ORG_ID = "org-1"
GROWTH_PROGRAM_COUNT = 50
ORG_SUMMARY_QUERY_COUNT_BUDGET = 1
ORG_SUMMARY_HANDLER_DURATION_BUDGET_MS = 500.0

_ORG_SUMMARY_ROLLUP_RE = re.compile(r"\borg_summary_rollup\b", re.IGNORECASE)
_JOIN_RE = re.compile(r"\bjoin\b", re.IGNORECASE)
_WHERE_ORG_ID_RE = re.compile(r"where\s+.*org_id\s*=", re.IGNORECASE | re.DOTALL)


def _build_org_summary_rollup(**overrides: Any) -> OrgSummaryRollup:
    """One representative `org_summary_rollup` row -- field values are
    arbitrary (TC-08 doesn't assert on response content, only query count/
    duration); the row only needs to exist so the route's rollup lookup
    returns a row rather than falling through to the AC-2 all-zero path (a
    different, cheaper query plan this test isn't measuring).
    """
    now = datetime.now(UTC)
    defaults: dict[str, Any] = {
        "org_id": TC08_ORG_ID,
        "programs_using_ai_count": 7,
        "programs_total": 10,
        "total_token_consumption": 12_500_000,
        "lines_of_code_generated": 850_000,
        "releases_using_harness": 42,
        "repos_with_harness_installed": 18,
        "repos_total": 25,
        "as_of_timestamp": now,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return OrgSummaryRollup(**defaults)


def _build_system_metadata_ingestion_row(**overrides: Any) -> SystemMetadata:
    """One `system_metadata` row for `key='ingestion'` -- TC-08's own
    precondition: seeded so the freshness read succeeds and does not
    confound the timing (a 500 short-circuit would be a much cheaper, and
    wrong, call to measure).
    """
    defaults: dict[str, Any] = {
        "key": "ingestion",
        "last_successful_run_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return SystemMetadata(**defaults)


@contextmanager
def _count_org_summary_rollup_selects(engine: AsyncEngine) -> Iterator[_SelectCounter]:
    """Attach a `before_cursor_execute` listener to `engine.sync_engine` for
    the duration of the `with` block, counting SELECTs against
    `org_summary_rollup`.

    Mirrors `_count_program_summary_selects` above / `tests/unit/
    test_rollup_rebuild_query_plan.py::_count_usage_events_selects`. Detaches
    in `finally` so the listener cannot leak into sibling tests sharing the
    session-scoped `test_engine` fixture.
    """
    counter = _SelectCounter()
    sync_engine = engine.sync_engine

    def _before_cursor_execute(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        if statement.strip().upper().startswith("SELECT") and _ORG_SUMMARY_ROLLUP_RE.search(
            statement
        ):
            counter.count += 1
            counter.statements.append(statement)

    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield counter
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before_cursor_execute)


def _assert_scoped_single_table_no_join(counter: _SelectCounter) -> None:
    """No captured SELECT against `org_summary_rollup` may join another
    table, and each must be scoped by `org_id` (the indexed unique-key
    lookup the route performs) rather than a bare table scan -- the
    structural half of the fan-out guard (see section docstring above).
    """
    for statement in counter.statements:
        assert not _JOIN_RE.search(statement), (
            "expected no JOIN in the org_summary_rollup SELECT (singleton-row "
            f"lookup, no fan-out): {statement}"
        )
        assert _WHERE_ORG_ID_RE.search(statement), (
            "expected the SELECT to be scoped by org_id (indexed unique-key "
            f"lookup, not a table scan): {statement}"
        )


@pytest.mark.asyncio
@pytest.mark.usefixtures("production_logging")
async def test_org_summary_single_select_budget_and_query_count_invariant_under_growth_tc08(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OVW-01-TC-08: one seeded `org_summary_rollup` row + one seeded
    `system_metadata` ingestion row, one `GET /api/overview/summary` call as
    a `cio` -- exactly `ORG_SUMMARY_QUERY_COUNT_BUDGET` SELECT against
    `org_summary_rollup` (no join, scoped by `org_id`), handler duration
    under `ORG_SUMMARY_HANDLER_DURATION_BUDGET_MS`. A second call, after
    seeding `GROWTH_PROGRAM_COUNT` unrelated `program_summary` rows, proves
    the query count does not grow with the org's data volume (see section
    docstring above for why this replaces a bare magic-number assertion).
    """
    test_session.add(_build_org_summary_rollup())
    test_session.add(_build_system_metadata_ingestion_row())
    await test_session.commit()

    app = build_app(oidc_issuer=TEST_OIDC_ISSUER, oidc_client_id=TEST_OIDC_CLIENT_ID)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    cio_token = build_access_token(role="cio", groups=[])

    test_session_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    # See section docstring: point the route's freshness read at this test's
    # disposable database via the same dependency-override mechanism used for
    # get_db above. `get_freshness_accessor` exists for this (flag AF-04).
    app.dependency_overrides[get_freshness_accessor] = lambda: FreshnessAccessor(
        session_factory=test_session_factory
    )

    headers = {"Authorization": f"Bearer {cio_token}"}

    async with async_client_for(app) as client:
        with _count_org_summary_rollup_selects(test_engine) as baseline_counter:
            started = time.perf_counter()
            resp = await client.get("/api/overview/summary", headers=headers)
            elapsed_ms = (time.perf_counter() - started) * 1000

        assert resp.status_code == 200, resp.text

        assert baseline_counter.count == ORG_SUMMARY_QUERY_COUNT_BUDGET, (
            f"expected exactly {ORG_SUMMARY_QUERY_COUNT_BUDGET} SELECT against "
            f"org_summary_rollup, got {baseline_counter.count}: "
            f"{baseline_counter.statements}"
        )
        _assert_scoped_single_table_no_join(baseline_counter)

        # C-4-style honest measurement: report the actual number, don't hide a breach.
        print(
            f"\nOVW-01-TC-08 baseline -- org-summary handler duration={elapsed_ms:.2f}ms "
            f"(budget {ORG_SUMMARY_HANDLER_DURATION_BUDGET_MS}ms)"
        )
        assert elapsed_ms < ORG_SUMMARY_HANDLER_DURATION_BUDGET_MS, (
            f"GET /api/overview/summary took {elapsed_ms:.2f}ms, exceeding the "
            f"OVW-01-TC-08 / NFR-performance budget of "
            f"{ORG_SUMMARY_HANDLER_DURATION_BUDGET_MS}ms. Do not relax this "
            "budget; report the measured duration for escalation/optimization."
        )

        # Growth-invariance: seed a materially larger org (unrelated
        # program_summary rows) and re-call -- the org_summary_rollup query
        # count must stay identical (see section docstring).
        for i in range(GROWTH_PROGRAM_COUNT):
            test_session.add(_build_program_summary(f"tc08-growth-prog-{i:03d}"))
        await test_session.commit()

        with _count_org_summary_rollup_selects(test_engine) as grown_counter:
            grown_resp = await client.get("/api/overview/summary", headers=headers)

    assert grown_resp.status_code == 200, grown_resp.text
    assert grown_counter.count == ORG_SUMMARY_QUERY_COUNT_BUDGET, (
        f"query count grew after seeding {GROWTH_PROGRAM_COUNT} more "
        "program_summary rows -- this is the fan-out this test polices: "
        f"expected {ORG_SUMMARY_QUERY_COUNT_BUDGET}, got {grown_counter.count}: "
        f"{grown_counter.statements}"
    )
    _assert_scoped_single_table_no_join(grown_counter)
