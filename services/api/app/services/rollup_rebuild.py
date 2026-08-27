"""Rollup rebuild engine: full-replace derivation of the 10 rollup tables from
`usage_events` (BED-03).

Two entry points, both taking an injected `AsyncSession` (FR-1 — neither
function constructs its own session/engine; callers obtain one via
`app.core.db.get_db()`/`SessionLocal`):

- `rebuild_program_rollups(session, program_id)` rebuilds the 7 program-scoped
  tables (`program_summary`, `program_releases`, `program_commands`,
  `program_members`, `session_series`, `program_token_series`,
  `user_sessions`).
- `rebuild_org_rollups(session)` rebuilds the 3 org-scoped tables
  (`org_summary_rollup`, `token_series`, `mau_series`).

Each issues exactly one `SELECT` against `usage_events` (D-05) and computes
every table's aggregate values in Python from that single in-memory result
set — never a per-table scan, never hand-written multi-CTE SQL. Each rebuild
wraps its own scope's DELETE+INSERT statements in one transaction (D-01,
FR-2) via `_rebuild_transaction()` — `session.begin()` on a fresh session
(the expected per-call shape from `get_db()`), or a `SAVEPOINT` when the
caller has already read from the same session (e.g. the idempotency
mechanics of FR-4/D-04: rebuild, snapshot via `SELECT`, rebuild again) so a
second call never hits `session.begin()`'s "already begun" error. Either way,
a mid-rebuild failure rolls back only that scope's mutations, and the two
scopes are never combined into a single cross-scope transaction. `id`,
`as_of_timestamp`, `created_at`/`updated_at` are regenerated on every call by
design (D-04) — idempotency is judged on the remaining business-value
columns.

Fields with no `usage_events` analog default deterministically per D-03:
string fields to `""`, numeric fields to `0`, the one JSON field
(`program_summary.monthly_token_sparkline`) to `[]`. `program_members.name`/
`user_sessions.name` fall back to the `usage_events.user` identifier — the
only identity signal present. `program_releases` has zero derivable columns:
this module deletes its rows for the program and inserts none.

No HTTP route is added by this module (Security NFR) — see
`app.services.rollup_rebuild` module of the barrel export
(`app/services/__init__.py`) for the intended call sites (ING-02/ING-06, out
of this story's scope). No PII is read or logged: `usage_events.user` is an
opaque identifier used only for grouping, never emitted in the
`rollup_rebuild_completed` log event (NFR-security,
`.claude/rules/security-baseline.md`).
"""

import logging
import time
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingestion import UsageEvent
from app.models.rollup import (
    MauSeries,
    OrgSummaryRollup,
    ProgramCommands,
    ProgramMembers,
    ProgramReleases,
    ProgramSummary,
    ProgramTokenSeries,
    SessionSeries,
    TokenSeries,
    UserSessions,
)

logger = logging.getLogger(__name__)

# D-03 / DATA-DESIGN.md §1: the org singleton convention this story reads and
# writes against — matches `org_summary_rollup.org_id`'s own model default.
_ORG_ID = "org-1"


@dataclass(frozen=True)
class RebuildResult:
    """Outcome of one rebuild call (D-06).

    `program_id` carries the rebuilt program's id for `scope="program"`, and
    is `None` for `scope="org"` (an org-wide rebuild isn't scoped to a single
    program). `event_count` is the number of `usage_events` rows scanned by
    this call's single `SELECT` (D-05); `duration_ms` spans the full
    transaction, measured via `time.perf_counter()`.
    """

    scope: Literal["program", "org"]
    program_id: str | None
    duration_ms: int
    event_count: int


@asynccontextmanager
async def _rebuild_transaction(session: AsyncSession) -> AsyncIterator[None]:
    """Open this rebuild call's own transaction scope (D-01, FR-2).

    `AsyncSession` autobegins an implicit transaction on any statement — a
    caller that reads the session between two rebuild calls on the same
    session (exactly what the idempotency mechanics require: rebuild,
    snapshot via `SELECT`, rebuild again, per FR-4/D-04) leaves an open
    transaction behind. Calling `session.begin()` when one is already open
    raises `InvalidRequestError`. A `SAVEPOINT` (`begin_nested()`) gives this
    call the same rollback-only-this-scope guarantee (D-01, TC-10) without
    assuming exclusive ownership of the session's outermost transaction;
    `session.begin()` is used when the session is genuinely idle (the
    expected shape for a fresh per-call session from `get_db()`).
    """
    if session.in_transaction():
        async with session.begin_nested():
            yield
    else:
        async with session.begin():
            yield


def _day(ts: datetime) -> datetime:
    """Truncate a timestamp to its calendar day, preserving tzinfo."""
    return ts.replace(hour=0, minute=0, second=0, microsecond=0)


def _month(ts: datetime) -> str:
    """Format a timestamp as a "YYYY-MM" month bucket key (string columns)."""
    return ts.strftime("%Y-%m")


def _build_program_summary(
    program_id: str, events: list[UsageEvent], now: datetime
) -> ProgramSummary:
    """`program_summary` (DATA-DESIGN.md §1): one singleton row per program.

    Direct-source fields: `tokens` (SUM `total`), `commands_executed`
    (COUNT events), `active_contributors` (COUNT DISTINCT `user`),
    `lines_of_code_generated` (SUM `lines_added`), `intervention_count`/
    `tool_rejections` (SUM). Remaining fields have no `usage_events` analog
    and default per D-03: strings to `""`, numerics to `0`,
    `monthly_token_sparkline` to `[]`.
    """
    return ProgramSummary(
        program_id=program_id,
        name="",
        icon="",
        type="",
        description="",
        monthly_token_sparkline=[],
        tokens=sum(e.total for e in events),
        releases=0,
        features=0,
        active_contributors=len({e.user for e in events}),
        repos_with_harness_installed=0,
        repos_total=0,
        commands_executed=len(events),
        lines_of_code_generated=sum(e.lines_added or 0 for e in events),
        user_stories_delivered=0,
        intervention_count=sum(e.intervention_count or 0 for e in events),
        tool_rejections=sum(e.tool_rejections or 0 for e in events),
        as_of_timestamp=now,
    )


def _build_program_commands(
    program_id: str, events: list[UsageEvent], now: datetime
) -> list[ProgramCommands]:
    """`program_commands` (DATA-DESIGN.md §1): one row per distinct `command`
    — `run_count` (COUNT), `period_start`/`period_end` (MIN/MAX `ts`).
    """
    groups: dict[str, list[UsageEvent]] = defaultdict(list)
    for e in events:
        groups[e.command].append(e)
    return [
        ProgramCommands(
            program_id=program_id,
            name=command,
            run_count=len(group),
            period_start=min(e.ts for e in group),
            period_end=max(e.ts for e in group),
            as_of_timestamp=now,
        )
        for command, group in groups.items()
    ]


def _build_program_members(
    program_id: str, events: list[UsageEvent], now: datetime
) -> list[ProgramMembers]:
    """`program_members` (DATA-DESIGN.md §1): one row per distinct `user` —
    `sessions` (COUNT DISTINCT `session_id`), `tokens` (SUM `total`),
    `last_active_date` (MAX `ts`). `name` has no `usage_events` analog and
    falls back to the `user` identifier (D-03); `role` defaults to `""`.
    """
    groups: dict[str, list[UsageEvent]] = defaultdict(list)
    for e in events:
        groups[e.user].append(e)
    return [
        ProgramMembers(
            program_id=program_id,
            user_id=user,
            name=user,
            role="",
            sessions=len({e.session_id for e in group}),
            tokens=sum(e.total for e in group),
            last_active_date=max(e.ts for e in group),
            as_of_timestamp=now,
        )
        for user, group in groups.items()
    ]


def _build_session_series(
    program_id: str, events: list[UsageEvent], now: datetime
) -> list[SessionSeries]:
    """`session_series` (DATA-DESIGN.md §1): one row per (`user`, day) —
    `member_id`, `date` (`ts` truncated to day), `session_time_seconds` (SUM
    `duration_seconds`). `org_id` has no `usage_events` analog and defaults to
    the org singleton convention (D-03, `_ORG_ID`).
    """
    groups: dict[tuple[str, datetime], list[UsageEvent]] = defaultdict(list)
    for e in events:
        groups[(e.user, _day(e.ts))].append(e)
    return [
        SessionSeries(
            org_id=_ORG_ID,
            program_id=program_id,
            member_id=user,
            date=day,
            session_time_seconds=sum(e.duration_seconds for e in group),
            as_of_timestamp=now,
        )
        for (user, day), group in groups.items()
    ]


def _build_program_token_series(
    program_id: str, events: list[UsageEvent], now: datetime
) -> list[ProgramTokenSeries]:
    """`program_token_series` (DATA-DESIGN.md §1): one row per day — `tokens`
    (SUM `total`), `input_tokens`/`output_tokens`/`cache_read_tokens`/
    `cache_write_tokens` (SUM per day, missing per-event values treated as 0).
    """
    groups: dict[datetime, list[UsageEvent]] = defaultdict(list)
    for e in events:
        groups[_day(e.ts)].append(e)
    return [
        ProgramTokenSeries(
            program_id=program_id,
            date=day,
            tokens=sum(e.total for e in group),
            input_tokens=sum(e.input_tokens or 0 for e in group),
            output_tokens=sum(e.output_tokens or 0 for e in group),
            cache_read_tokens=sum(e.cache_read_tokens or 0 for e in group),
            cache_write_tokens=sum(e.cache_write_tokens or 0 for e in group),
            as_of_timestamp=now,
        )
        for day, group in groups.items()
    ]


def _build_user_sessions(
    program_id: str, events: list[UsageEvent], now: datetime
) -> list[UserSessions]:
    """`user_sessions` (DATA-DESIGN.md §1): one row per distinct `session_id`
    — `started_at` (MIN `ts`), `duration_seconds`/`tokens` (SUM). `name` has
    no `usage_events` analog and falls back to the `user` identifier (D-03).
    """
    groups: dict[str, list[UsageEvent]] = defaultdict(list)
    for e in events:
        groups[e.session_id].append(e)
    return [
        UserSessions(
            user_id=group[0].user,
            program_id=program_id,
            session_identifier=session_id,
            name=group[0].user,
            started_at=min(e.ts for e in group),
            duration_seconds=sum(e.duration_seconds for e in group),
            tokens=sum(e.total for e in group),
        )
        for session_id, group in groups.items()
    ]


async def rebuild_program_rollups(session: AsyncSession, program_id: str) -> RebuildResult:
    """Full-replace rebuild of the 7 program-scoped rollup tables for `program_id`.

    One `SELECT * FROM usage_events WHERE program_id = :pid` (D-05), then one
    `async with session.begin():` transaction (D-01) that DELETEs each
    program-scoped table's existing rows for `program_id` and INSERTs freshly
    aggregated rows (FR-2). `program_releases` is delete-only — no release
    signal exists in `usage_events` (D-03). Emits `rollup_rebuild_completed`
    once, after commit (FR-5).
    """
    start = time.perf_counter()
    async with _rebuild_transaction(session):
        result = await session.execute(
            select(UsageEvent).where(UsageEvent.program_id == program_id)
        )
        events = list(result.scalars().all())
        now = datetime.now(UTC)

        await session.execute(delete(ProgramSummary).where(ProgramSummary.program_id == program_id))
        await session.execute(
            delete(ProgramReleases).where(ProgramReleases.program_id == program_id)
        )
        await session.execute(
            delete(ProgramCommands).where(ProgramCommands.program_id == program_id)
        )
        await session.execute(delete(ProgramMembers).where(ProgramMembers.program_id == program_id))
        await session.execute(delete(SessionSeries).where(SessionSeries.program_id == program_id))
        await session.execute(
            delete(ProgramTokenSeries).where(ProgramTokenSeries.program_id == program_id)
        )
        await session.execute(delete(UserSessions).where(UserSessions.program_id == program_id))

        session.add(_build_program_summary(program_id, events, now))
        # program_releases: D-03 — no derivable columns, delete-only, insert nothing.
        session.add_all(_build_program_commands(program_id, events, now))
        session.add_all(_build_program_members(program_id, events, now))
        session.add_all(_build_session_series(program_id, events, now))
        session.add_all(_build_program_token_series(program_id, events, now))
        session.add_all(_build_user_sessions(program_id, events, now))

    duration_ms = int((time.perf_counter() - start) * 1000)
    event_count = len(events)
    logger.info(
        "rollup_rebuild_completed",
        extra={
            "scope": "program",
            "program_id": program_id,
            "duration_ms": duration_ms,
            "event_count": event_count,
        },
    )
    return RebuildResult(
        scope="program", program_id=program_id, duration_ms=duration_ms, event_count=event_count
    )


def _build_org_summary(events: list[UsageEvent], now: datetime) -> OrgSummaryRollup:
    """`org_summary_rollup` (DATA-DESIGN.md §1): singleton org-wide row.

    `programs_using_ai_count`/`programs_total` both derive from COUNT
    DISTINCT `program_id` — no separate program registry exists in this
    story's read set to distinguish "using AI" from "total" (D-03).
    `total_token_consumption` (SUM `total`), `lines_of_code_generated` (SUM
    `lines_added`). `releases_using_harness`/`repos_with_harness_installed`/
    `repos_total` have no `usage_events` analog and default to `0` (D-03).
    """
    program_count = len({e.program_id for e in events})
    return OrgSummaryRollup(
        org_id=_ORG_ID,
        programs_using_ai_count=program_count,
        programs_total=program_count,
        total_token_consumption=sum(e.total for e in events),
        lines_of_code_generated=sum(e.lines_added or 0 for e in events),
        releases_using_harness=0,
        repos_with_harness_installed=0,
        repos_total=0,
        as_of_timestamp=now,
        created_at=now,
        updated_at=now,
    )


def _build_token_series(events: list[UsageEvent], now: datetime) -> list[TokenSeries]:
    """`token_series` (DATA-DESIGN.md §1): one row per month across all
    programs — `value` (SUM `total` tokens per month).
    """
    groups: dict[str, list[UsageEvent]] = defaultdict(list)
    for e in events:
        groups[_month(e.ts)].append(e)
    return [
        TokenSeries(
            org_id=_ORG_ID, month=month, value=sum(e.total for e in group), as_of_timestamp=now
        )
        for month, group in groups.items()
    ]


def _build_mau_series(events: list[UsageEvent], now: datetime) -> list[MauSeries]:
    """`mau_series` (DATA-DESIGN.md §1): one row per month — COUNT DISTINCT
    `user` per month. Role breakdown (`developer`/`architect`/
    `product_manager`/`engineering_manager`) requires a `user_roles` join,
    out of this story's read set (D-03/DATA-DESIGN §1): every active user for
    the month is bucketed into `developer` until a future story wires that
    join; the other three role columns are always `0`. Which single column
    receives the bucket is this implementation's reading of DATA-DESIGN §1,
    not an explicit decision — flagged for confirmation.
    """
    groups: dict[str, set[str]] = defaultdict(set)
    for e in events:
        groups[_month(e.ts)].add(e.user)
    return [
        MauSeries(
            org_id=_ORG_ID,
            month=month,
            developer=len(users),
            architect=0,
            product_manager=0,
            engineering_manager=0,
            as_of_timestamp=now,
        )
        for month, users in groups.items()
    ]


async def rebuild_org_rollups(session: AsyncSession) -> RebuildResult:
    """Full-replace rebuild of the 3 org-scoped rollup tables.

    One unfiltered `SELECT * FROM usage_events` (D-05), then one `async with
    session.begin():` transaction (D-01) that DELETEs each org-scoped table's
    existing rows for the org singleton and INSERTs freshly aggregated rows
    (FR-2). Emits `rollup_rebuild_completed` once, after commit, with
    `program_id` omitted (FR-5 — org scope has no single program).
    """
    start = time.perf_counter()
    async with _rebuild_transaction(session):
        result = await session.execute(select(UsageEvent))
        events = list(result.scalars().all())
        now = datetime.now(UTC)

        await session.execute(delete(OrgSummaryRollup).where(OrgSummaryRollup.org_id == _ORG_ID))
        await session.execute(delete(TokenSeries).where(TokenSeries.org_id == _ORG_ID))
        await session.execute(delete(MauSeries).where(MauSeries.org_id == _ORG_ID))

        session.add(_build_org_summary(events, now))
        session.add_all(_build_token_series(events, now))
        session.add_all(_build_mau_series(events, now))

    duration_ms = int((time.perf_counter() - start) * 1000)
    event_count = len(events)
    logger.info(
        "rollup_rebuild_completed",
        extra={"scope": "org", "duration_ms": duration_ms, "event_count": event_count},
    )
    return RebuildResult(
        scope="org", program_id=None, duration_ms=duration_ms, event_count=event_count
    )
