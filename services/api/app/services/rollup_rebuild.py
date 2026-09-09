"""Rollup rebuild engine: full-replace derivation of the 10 rollup tables from
`usage_events` (BED-03, rewritten BED-05).

Two entry points, both taking an injected `AsyncSession` (FR-1 — neither
function constructs its own session/engine; callers obtain one via
`app.core.db.get_db()`/`SessionLocal`):

- `rebuild_program_rollups(session, program_id)` rebuilds the 7 program-scoped
  tables (`program_summary`, `program_releases`, `program_commands`,
  `program_members`, `session_series`, `program_token_series`,
  `user_sessions`).
- `rebuild_org_rollups(session)` rebuilds the 3 org-scoped tables
  (`org_summary_rollup`, `token_series`, `mau_series`).

BED-05 D-01 rewrite: BED-03's single `SELECT * FROM usage_events` followed by
Python-side `groupby`/`sum`/`len` aggregation is replaced by one SQL
`GROUP BY`/`func.*` query per rollup table (matching `personal_usage.py`'s
existing pattern) — no per-event ORM materialisation, never a full-table or
full-program row set loaded into Python. `event_count` (part of the frozen
`RebuildResult` contract) now comes from its own `SELECT COUNT(*)` rather than
`len(events)`. BED-03 D-05's "exactly 1 SELECT against usage_events" invariant
is deliberately superseded by this rewrite (BED-05 AC-4/AC-5) — the per-call
query count is now a small bounded constant (one aggregate query per table
plus the identity/count reads), never a per-row fan-out.

Order-independence audit (BED-05 D-01, research condition C-1): of the 9
`_build_*` functions, 8 compute only commutative aggregates (`sum`, `count`,
`count(distinct=True)`, `min`, `max`) — SQL `GROUP BY` reproduces the same
result regardless of row-fetch order. `_build_user_sessions` is the one
function shaped as first-occurrence-wins in the shipped Python version
(`group[0].user`); it is order-independent in practice only because
`session_id` is 1:1 with a single `user` by construction, so this rewrite
expresses that as an explicit `func.min(UsageEvent.user)` grouped by
`session_id` — a provably order-independent aggregate, never an
unaggregated/arbitrary-pick column. This audit is what allows the org-scope
write path below to use `ON CONFLICT DO UPDATE` with no
`pg_advisory_xact_lock` fallback: every concurrent writer computes the
identical final aggregate regardless of scan/commit order.

Each rebuild wraps its own scope's DELETE/write statements in one transaction
(D-01, FR-2) via `_rebuild_transaction()` — `session.begin()` on a fresh
session (the expected per-call shape from `get_db()`), or a `SAVEPOINT` when
the caller has already read from the same session (e.g. the idempotency
mechanics of FR-4/D-04: rebuild, snapshot via `SELECT`, rebuild again) so a
second call never hits `session.begin()`'s "already begun" error. Either way,
a mid-rebuild failure rolls back only that scope's mutations, and the two
scopes are never combined into a single cross-scope transaction. `id`,
`as_of_timestamp`, `created_at`/`updated_at` are regenerated on every call by
design (D-04) — idempotency is judged on the remaining business-value
columns.

Write path per scope (BED-05 D-01, DATA-DESIGN.md §1):
- Program scope (7 tables): unchanged — `DELETE WHERE program_id = :pid` then
  INSERT via `session.add`/`add_all`. No cross-writer collision: each of
  AC-1's four concurrent programs owns disjoint rows.
- Org scope (3 tables), all four AC-1 programs write the SAME rows
  concurrently, so the shipped DELETE+INSERT race (`org_summary_rollup`'s
  `unique(org_id)` violation) is replaced: `org_summary_rollup` (a true 1-row
  singleton) is `INSERT ... ON CONFLICT (org_id) DO UPDATE`;
  `token_series`/`mau_series` (month-keyed) are `DELETE WHERE org_id = :oid
  AND month NOT IN (:computed_months)` (preserves the full-re-derive
  invariant — a month that stops being represented is still dropped) followed
  by `INSERT ... ON CONFLICT (org_id, month) DO UPDATE` per computed row.
  `contention_wait_ms` (log-only, `rollup_rebuild_completed`'s `extra={}`,
  never a `RebuildResult` field — that dataclass shape is frozen) is timed
  around each of these three org-scope write statements and summed: mostly
  ordinary execution time, but it inflates when ≥2 of the four concurrent
  calls target the same row and one waits on Postgres's own row-level lock
  during the `ON CONFLICT` UPDATE path.

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
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import delete, distinct, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
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
    program). `event_count` is the number of `usage_events` rows in scope for
    this call, from a dedicated `SELECT COUNT(*)` (BED-05 D-01 — replaces
    BED-03's `len(events)`); `duration_ms` spans the full transaction,
    measured via `time.perf_counter()`.
    """

    scope: Literal["program", "org"]
    program_id: str | None
    duration_ms: int
    event_count: int


@dataclass(frozen=True)
class _ProgramIdentity:
    """The four descriptive `program_summary` columns carried across a rebuild.

    Held as a plain frozen value rather than the ORM row itself so the values
    survive the DELETE that follows: a detached/deleted `ProgramSummary`
    instance would be expired by the flush, and reading its attributes
    afterwards would re-query or raise.
    """

    name: str
    icon: str
    type: str
    description: str


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


async def _build_program_summary(
    session: AsyncSession,
    program_id: str,
    now: datetime,
    prior_identity: _ProgramIdentity | None = None,
) -> ProgramSummary:
    """`program_summary` (DATA-DESIGN.md §1): one singleton row per program.

    One `GROUP BY`-free aggregate query: `tokens` (SUM `total`),
    `commands_executed` (COUNT `*`), `active_contributors` (COUNT DISTINCT
    `user`), `lines_of_code_generated` (SUM `lines_added`),
    `intervention_count`/`tool_rejections` (SUM). `SUM` returns `NULL` over a
    program with zero events — coerced to `0`; `COUNT` never returns `NULL`.
    Remaining fields have no `usage_events` analog and default per D-03:
    strings to `""`, numerics to `0`, `monthly_token_sparkline` to `[]`.

    The four descriptive identity columns (`name`/`icon`/`type`/`description`)
    are the one carve-out from that default. They are program identity, not a
    derived metric, and two shipped consumers read them directly: PGD-01's
    `GET /api/overview/program-detail/{program_id}` renders them as the page
    header, and AUTH-04's `GET /api/programs` uses `name` as the switcher
    `label`. Defaulting them to `""` on every rebuild blanked both surfaces,
    so `prior_identity` — captured from the existing row before this rebuild's
    DELETE — is carried forward when one exists. D-03's `""` still applies
    when no prior row exists, which keeps a first-ever rebuild deterministic
    and honest (it invents no identity it has no source for). Idempotency is
    preserved: the same events against the same stored identity produce the
    same row, because the carried-forward value is itself the previous
    rebuild's output.
    """
    stmt = select(
        func.sum(UsageEvent.total),
        func.count(),
        func.count(distinct(UsageEvent.user)),
        func.sum(UsageEvent.lines_added),
        func.sum(UsageEvent.intervention_count),
        func.sum(UsageEvent.tool_rejections),
    ).where(UsageEvent.program_id == program_id)
    (
        tokens,
        commands_executed,
        active_contributors,
        lines_of_code_generated,
        intervention_count,
        tool_rejections,
    ) = (await session.execute(stmt)).one()
    return ProgramSummary(
        program_id=program_id,
        name=prior_identity.name if prior_identity else "",
        icon=prior_identity.icon if prior_identity else "",
        type=prior_identity.type if prior_identity else "",
        description=prior_identity.description if prior_identity else "",
        monthly_token_sparkline=[],
        tokens=tokens or 0,
        releases=0,
        features=0,
        active_contributors=active_contributors or 0,
        repos_with_harness_installed=0,
        repos_total=0,
        commands_executed=commands_executed or 0,
        lines_of_code_generated=lines_of_code_generated or 0,
        user_stories_delivered=0,
        intervention_count=intervention_count or 0,
        tool_rejections=tool_rejections or 0,
        as_of_timestamp=now,
    )


async def _build_program_commands(
    session: AsyncSession, program_id: str, now: datetime
) -> list[ProgramCommands]:
    """`program_commands` (DATA-DESIGN.md §1): one row per distinct `command`
    — `run_count` (COUNT), `period_start`/`period_end` (MIN/MAX `ts`).
    """
    stmt = (
        select(UsageEvent.command, func.count(), func.min(UsageEvent.ts), func.max(UsageEvent.ts))
        .where(UsageEvent.program_id == program_id)
        .group_by(UsageEvent.command)
    )
    rows = (await session.execute(stmt)).all()
    return [
        ProgramCommands(
            program_id=program_id,
            name=command,
            run_count=run_count,
            period_start=period_start,
            period_end=period_end,
            as_of_timestamp=now,
        )
        for command, run_count, period_start, period_end in rows
    ]


async def _build_program_members(
    session: AsyncSession, program_id: str, now: datetime
) -> list[ProgramMembers]:
    """`program_members` (DATA-DESIGN.md §1): one row per distinct `user` —
    `sessions` (COUNT DISTINCT `session_id`), `tokens` (SUM `total`),
    `last_active_date` (MAX `ts`). `name` has no `usage_events` analog and
    falls back to the `user` identifier (D-03); `role` defaults to `""`.
    """
    stmt = (
        select(
            UsageEvent.user,
            func.count(distinct(UsageEvent.session_id)),
            func.sum(UsageEvent.total),
            func.max(UsageEvent.ts),
        )
        .where(UsageEvent.program_id == program_id)
        .group_by(UsageEvent.user)
    )
    rows = (await session.execute(stmt)).all()
    return [
        ProgramMembers(
            program_id=program_id,
            user_id=user,
            name=user,
            role="",
            sessions=sessions,
            tokens=tokens or 0,
            last_active_date=last_active_date,
            as_of_timestamp=now,
        )
        for user, sessions, tokens, last_active_date in rows
    ]


async def _build_session_series(
    session: AsyncSession, program_id: str, now: datetime
) -> list[SessionSeries]:
    """`session_series` (DATA-DESIGN.md §1): one row per (`user`, day) —
    `member_id`, `date` (`ts` truncated to day), `session_time_seconds` (SUM
    `duration_seconds`). `org_id` has no `usage_events` analog and defaults to
    the org singleton convention (D-03, `_ORG_ID`). Day truncation is done in
    SQL with an explicit `'UTC'` zone (`func.date_trunc`), not the session's
    ambient `TimeZone` GUC, so the bucket boundary matches the shipped
    Python `_day()` truncation regardless of server configuration.
    """
    day_bucket = func.date_trunc("day", UsageEvent.ts, "UTC")
    stmt = (
        select(UsageEvent.user, day_bucket, func.sum(UsageEvent.duration_seconds))
        .where(UsageEvent.program_id == program_id)
        .group_by(UsageEvent.user, day_bucket)
    )
    rows = (await session.execute(stmt)).all()
    return [
        SessionSeries(
            org_id=_ORG_ID,
            program_id=program_id,
            member_id=user,
            date=day,
            session_time_seconds=seconds or 0,
            as_of_timestamp=now,
        )
        for user, day, seconds in rows
    ]


async def _build_program_token_series(
    session: AsyncSession, program_id: str, now: datetime
) -> list[ProgramTokenSeries]:
    """`program_token_series` (DATA-DESIGN.md §1): one row per day — `tokens`
    (SUM `total`), `input_tokens`/`output_tokens`/`cache_read_tokens`/
    `cache_write_tokens` (SUM per day, missing per-event values treated as 0).
    Day truncation matches `_build_session_series`'s explicit-UTC `date_trunc`.
    """
    day_bucket = func.date_trunc("day", UsageEvent.ts, "UTC")
    stmt = (
        select(
            day_bucket,
            func.sum(UsageEvent.total),
            func.sum(UsageEvent.input_tokens),
            func.sum(UsageEvent.output_tokens),
            func.sum(UsageEvent.cache_read_tokens),
            func.sum(UsageEvent.cache_write_tokens),
        )
        .where(UsageEvent.program_id == program_id)
        .group_by(day_bucket)
    )
    rows = (await session.execute(stmt)).all()
    return [
        ProgramTokenSeries(
            program_id=program_id,
            date=day,
            tokens=tokens or 0,
            input_tokens=input_tokens or 0,
            output_tokens=output_tokens or 0,
            cache_read_tokens=cache_read_tokens or 0,
            cache_write_tokens=cache_write_tokens or 0,
            as_of_timestamp=now,
        )
        for day, tokens, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens in rows
    ]


async def _build_user_sessions(
    session: AsyncSession, program_id: str, now: datetime
) -> list[UserSessions]:
    """`user_sessions` (DATA-DESIGN.md §1): one row per distinct `session_id`
    — `started_at` (MIN `ts`), `duration_seconds`/`tokens` (SUM). `name` has
    no `usage_events` analog and falls back to the `user` identifier (D-03).

    D-01 order-independence audit: the shipped Python version picks
    `group[0].user` (first-occurrence-wins) — safe only because `session_id`
    maps 1:1 to a single `user` by construction, never an actual multi-value
    choice. This rewrite expresses that same intent as an explicit
    `func.min(UsageEvent.user)` grouped by `session_id`, a provably
    order-independent aggregate rather than an arbitrary-pick column.
    """
    stmt = (
        select(
            UsageEvent.session_id,
            func.min(UsageEvent.user),
            func.min(UsageEvent.ts),
            func.sum(UsageEvent.duration_seconds),
            func.sum(UsageEvent.total),
        )
        .where(UsageEvent.program_id == program_id)
        .group_by(UsageEvent.session_id)
    )
    rows = (await session.execute(stmt)).all()
    return [
        UserSessions(
            user_id=user,
            program_id=program_id,
            session_identifier=session_id,
            name=user,
            started_at=started_at,
            duration_seconds=duration_seconds or 0,
            tokens=tokens or 0,
        )
        for session_id, user, started_at, duration_seconds, tokens in rows
    ]


async def rebuild_program_rollups(session: AsyncSession, program_id: str) -> RebuildResult:
    """Full-replace rebuild of the 7 program-scoped rollup tables for `program_id`.

    One `SELECT COUNT(*)` for `event_count` (BED-05 D-01), one `GROUP BY`
    aggregate query per table (via the `_build_*` functions above), then one
    `async with session.begin():` transaction (D-01) that DELETEs each
    program-scoped table's existing rows for `program_id` and INSERTs freshly
    aggregated rows (FR-2). `program_releases` is delete-only — no release
    signal exists in `usage_events` (D-03). Emits `rollup_rebuild_completed`
    once, after commit (FR-5).
    """
    start = time.perf_counter()
    async with _rebuild_transaction(session):
        now = datetime.now(UTC)
        event_count = (
            await session.execute(
                select(func.count(UsageEvent.id)).where(UsageEvent.program_id == program_id)
            )
        ).scalar_one()

        # Capture the existing row's descriptive identity before the DELETE
        # below drops it, so the rebuild carries it forward instead of
        # blanking PGD-01's header and AUTH-04's switcher label (see
        # `_build_program_summary`).
        identity_row = (
            await session.execute(
                select(
                    ProgramSummary.name,
                    ProgramSummary.icon,
                    ProgramSummary.type,
                    ProgramSummary.description,
                ).where(ProgramSummary.program_id == program_id)
            )
        ).first()
        prior_identity = _ProgramIdentity(*identity_row) if identity_row else None

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

        session.add(await _build_program_summary(session, program_id, now, prior_identity))
        # program_releases: D-03 — no derivable columns, delete-only, insert nothing.
        session.add_all(await _build_program_commands(session, program_id, now))
        session.add_all(await _build_program_members(session, program_id, now))
        session.add_all(await _build_session_series(session, program_id, now))
        session.add_all(await _build_program_token_series(session, program_id, now))
        session.add_all(await _build_user_sessions(session, program_id, now))

    duration_ms = int((time.perf_counter() - start) * 1000)
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


async def _build_org_summary(session: AsyncSession, now: datetime) -> dict[str, Any]:
    """`org_summary_rollup` (DATA-DESIGN.md §1): singleton org-wide row.

    Returns a plain value dict (not an ORM instance) — the org-scope write
    path is `INSERT ... ON CONFLICT DO UPDATE` (BED-05 D-01), not
    `session.add`, so a dict of column values is what the caller's `pg_insert`
    statement needs; `id` is minted here since a raw Core `INSERT` never runs
    the model's Python-side default.

    `programs_using_ai_count`/`programs_total` both derive from COUNT
    DISTINCT `program_id` — no separate program registry exists in this
    story's read set to distinguish "using AI" from "total" (D-03).
    `total_token_consumption` (SUM `total`), `lines_of_code_generated` (SUM
    `lines_added`). `releases_using_harness`/`repos_with_harness_installed`/
    `repos_total` have no `usage_events` analog and default to `0` (D-03).
    """
    stmt = select(
        func.count(distinct(UsageEvent.program_id)),
        func.sum(UsageEvent.total),
        func.sum(UsageEvent.lines_added),
    )
    program_count, total_token_consumption, lines_of_code_generated = (
        await session.execute(stmt)
    ).one()
    return {
        "id": str(uuid.uuid4()),
        "org_id": _ORG_ID,
        "programs_using_ai_count": program_count or 0,
        "programs_total": program_count or 0,
        "total_token_consumption": total_token_consumption or 0,
        "lines_of_code_generated": lines_of_code_generated or 0,
        "releases_using_harness": 0,
        "repos_with_harness_installed": 0,
        "repos_total": 0,
        "as_of_timestamp": now,
        "created_at": now,
        "updated_at": now,
    }


async def _build_token_series(session: AsyncSession, now: datetime) -> list[dict[str, Any]]:
    """`token_series` (DATA-DESIGN.md §1): one row per month across all
    programs — `value` (SUM `total` tokens per month). Returns value dicts
    (see `_build_org_summary`) for the ON CONFLICT write path below. Month
    bucketing matches `_build_session_series`'s explicit-UTC `date_trunc`,
    formatted to the shipped `"YYYY-MM"` string key via `to_char`.
    """
    month_bucket = func.to_char(func.date_trunc("month", UsageEvent.ts, "UTC"), "YYYY-MM")
    stmt = select(month_bucket, func.sum(UsageEvent.total)).group_by(month_bucket)
    rows = (await session.execute(stmt)).all()
    return [
        {
            "id": str(uuid.uuid4()),
            "org_id": _ORG_ID,
            "month": month,
            "value": value or 0,
            "as_of_timestamp": now,
        }
        for month, value in rows
    ]


async def _build_mau_series(session: AsyncSession, now: datetime) -> list[dict[str, Any]]:
    """`mau_series` (DATA-DESIGN.md §1): one row per month — COUNT DISTINCT
    `user` per month. Returns value dicts (see `_build_org_summary`). Role
    breakdown (`developer`/`architect`/`product_manager`/
    `engineering_manager`) requires a `user_roles` join, out of this story's
    read set (D-03/DATA-DESIGN §1, unchanged from BED-03): every active user
    for the month is bucketed into `developer` until a future story wires
    that join; the other three role columns are always `0`.
    """
    month_bucket = func.to_char(func.date_trunc("month", UsageEvent.ts, "UTC"), "YYYY-MM")
    stmt = select(month_bucket, func.count(distinct(UsageEvent.user))).group_by(month_bucket)
    rows = (await session.execute(stmt)).all()
    return [
        {
            "id": str(uuid.uuid4()),
            "org_id": _ORG_ID,
            "month": month,
            "developer": developer_count,
            "architect": 0,
            "product_manager": 0,
            "engineering_manager": 0,
            "as_of_timestamp": now,
        }
        for month, developer_count in rows
    ]


async def _upsert_org_summary(session: AsyncSession, row: dict[str, Any]) -> int:
    """Org-scope write path for `org_summary_rollup` (BED-05 D-01): a true
    1-row singleton, so a plain `INSERT ... ON CONFLICT (org_id) DO UPDATE`
    replaces the shipped DELETE+INSERT — the mechanism that raced under the
    AC-1 four-program concurrency case. Every column except the conflict key
    (`org_id`) is refreshed on conflict, including `id`/`created_at`/
    `updated_at`, mirroring the DELETE+INSERT behaviour this replaces (D-04:
    these columns are regenerated on every call by design).

    Returns the wall-clock time (ms) spent executing this statement —
    `contention_wait_ms`'s per-table contribution (D-02): mostly ordinary
    execution time, but it inflates when a concurrent writer holds this row's
    lock during its own `ON CONFLICT` UPDATE (DATA-DESIGN.md §5).
    """
    start = time.perf_counter()
    insert_stmt = pg_insert(OrgSummaryRollup).values(row)
    update_cols = [c for c in row if c != "org_id"]
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=["org_id"],
        set_={c: getattr(insert_stmt.excluded, c) for c in update_cols},
    )
    await session.execute(stmt)
    return int((time.perf_counter() - start) * 1000)


async def _upsert_month_series(
    session: AsyncSession, model: type[Any], rows: list[dict[str, Any]]
) -> int:
    """Org-scope write path for the two month-keyed tables (`token_series`/
    `mau_series`, BED-05 D-01). Two steps in one transaction: (1) `DELETE
    WHERE org_id = :oid AND month NOT IN (:computed_months)` — safe under
    concurrency, since two concurrent rebuilds computing the same current
    month-set delete nothing, and preserves the full-re-derive invariant when
    `usage_events` genuinely stops covering a month; (2) `INSERT ... ON
    CONFLICT (org_id, month) DO UPDATE` per computed row, replacing the
    shipped DELETE+INSERT race.

    Returns the wall-clock time (ms) spent executing these two statements —
    see `_upsert_org_summary` for `contention_wait_ms` semantics.
    """
    start = time.perf_counter()
    computed_months = [row["month"] for row in rows]
    await session.execute(
        delete(model).where(model.org_id == _ORG_ID, model.month.not_in(computed_months))
    )
    if rows:
        insert_stmt = pg_insert(model).values(rows)
        update_cols = [c for c in rows[0] if c not in ("org_id", "month")]
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=["org_id", "month"],
            set_={c: getattr(insert_stmt.excluded, c) for c in update_cols},
        )
        await session.execute(stmt)
    return int((time.perf_counter() - start) * 1000)


async def rebuild_org_rollups(session: AsyncSession) -> RebuildResult:
    """Full-replace rebuild of the 3 org-scoped rollup tables.

    One `SELECT COUNT(*)` for `event_count` (BED-05 D-01), one `GROUP BY`
    aggregate query per table (via the `_build_*` functions above), then one
    `async with session.begin():` transaction (D-01) that writes each
    org-scoped table via its `ON CONFLICT DO UPDATE` mechanism (FR-2) —
    replacing the shipped blanket DELETE+INSERT, which raced under AC-1's
    four-concurrent-program case. `contention_wait_ms` sums the time spent
    executing all three org-scope write statements (D-02) and is added only
    to this call's log `extra={}`, never to `RebuildResult` (frozen contract).
    Emits `rollup_rebuild_completed` once, after commit, with `program_id`
    omitted (FR-5 — org scope has no single program).
    """
    start = time.perf_counter()
    contention_wait_ms = 0
    async with _rebuild_transaction(session):
        now = datetime.now(UTC)
        event_count = (await session.execute(select(func.count(UsageEvent.id)))).scalar_one()

        org_summary_row = await _build_org_summary(session, now)
        token_series_rows = await _build_token_series(session, now)
        mau_series_rows = await _build_mau_series(session, now)

        contention_wait_ms += await _upsert_org_summary(session, org_summary_row)
        contention_wait_ms += await _upsert_month_series(session, TokenSeries, token_series_rows)
        contention_wait_ms += await _upsert_month_series(session, MauSeries, mau_series_rows)

    duration_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "rollup_rebuild_completed",
        extra={
            "scope": "org",
            "duration_ms": duration_ms,
            "event_count": event_count,
            "contention_wait_ms": contention_wait_ms,
        },
    )
    return RebuildResult(
        scope="org", program_id=None, duration_ms=duration_ms, event_count=event_count
    )
