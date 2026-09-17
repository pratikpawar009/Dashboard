"""Query/aggregation layer for `GET /api/overview/program-detail/{program_id}/team`
(PGD-05, DECISIONS.md D-01/D-02).

D-01 (critical): exactly TWO SELECTs, merged in Python by user id -- NEVER a SQL join, which
would risk a Cartesian product between the roster snapshot and the range-scoped event rows.
(1) `program_members` filtered by `program_id` for identity fields (`user_id`, `name`, `role`)
-- a to-date snapshot with no temporal columns, so it cannot itself answer a ranged question.
(2) `usage_events` filtered by `program_id` + `ts >= range_start`, grouped by `"user"`, using the
new `ix_usage_events_program_id_user_ts` covering index (migration 008, ADR-0016) -- the existing
`program_id+user` and `program_id+ts` indexes each cover only two of this query's three
predicates. `sessions` is `COUNT(DISTINCT session_id)`; `tokens` is `SUM(total)` -- `UsageEvent`
has no column literally named `tokens` (see `rollup_rebuild.py`'s own `usage_events` aggregates,
which all sum `UsageEvent.total` for the same "tokens" wire concept).

A roster member with zero in-range `usage_events` rows is EXCLUDED from `items` (active-in-range
contract, D-01) -- the two result sets are merged by `user_id`/`user` in Python, so an event-only
id absent from the roster snapshot is also dropped (the roster is authoritative for
`member_name`/`role`, which the aggregate alone cannot supply).

R-8 (LOW, addressed by docstring note per PLAN.md): `program_members` is rebuilt synchronously by
BED-03 on every ING-02 ingest (verified, research Exploration Log) -- no async rebuild
coordination is needed here; a request during an in-flight rebuild simply reads whatever the
current committed row is, same read-committed behavior every other PGD sibling already accepts.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.range import range_to_start
from app.models.ingestion import UsageEvent
from app.models.rollup import ProgramMembers
from app.schemas.program_detail import ProgramTeamResponse, ProgramTeamRow


async def fetch_program_team(
    db: AsyncSession, program_id: str, range_value: str
) -> ProgramTeamResponse:
    """Range-scoped team table over `program_members` (identity) + `usage_events` (metrics).

    Exactly two SELECTs (D-01, research Condition C-1):
      1. `SELECT user_id, name, role FROM program_members WHERE program_id = :pid`
      2. `SELECT "user", COUNT(DISTINCT session_id), SUM(total) FROM usage_events
         WHERE program_id = :pid AND ts >= :range_start GROUP BY "user"`

    Merged in Python by `user_id`/`user` -- never a SQL join. `avg_tokens_per_session` is
    `round(tokens / sessions)`, computed server-side as an int; `sessions` cannot be 0 for a row
    that survives the merge (a row only exists in the aggregate result if it has at least one
    in-range event, hence at least one session), so no zero-division guard is needed. Rows are
    ordered descending by `tokens`. Zero active members yields `ProgramTeamResponse(items=[])`,
    never an error (D-01, active-in-range contract).
    """
    range_start = range_to_start(range_value)

    roster_stmt = select(
        ProgramMembers.user_id, ProgramMembers.name, ProgramMembers.role
    ).where(ProgramMembers.program_id == program_id)
    roster_result = await db.execute(roster_stmt)
    roster_by_user_id = {
        user_id: (name, role) for user_id, name, role in roster_result.all()
    }

    metrics_stmt = (
        select(
            UsageEvent.user,
            func.count(func.distinct(UsageEvent.session_id)),
            func.sum(UsageEvent.total),
        )
        .where(UsageEvent.program_id == program_id, UsageEvent.ts >= range_start)
        .group_by(UsageEvent.user)
    )
    metrics_result = await db.execute(metrics_stmt)

    rows: list[ProgramTeamRow] = []
    for user_id, sessions, tokens in metrics_result.all():
        identity = roster_by_user_id.get(user_id)
        if identity is None:
            # Event rows with no matching roster snapshot entry are dropped --
            # the roster is authoritative for member_name/role (D-01).
            continue
        name, role = identity
        tokens = int(tokens or 0)
        rows.append(
            ProgramTeamRow(
                member_id=user_id,
                member_name=name,
                role=role,
                sessions=sessions,
                tokens=tokens,
                avg_tokens_per_session=round(tokens / sessions),
            )
        )

    rows.sort(key=lambda row: row.tokens, reverse=True)
    return ProgramTeamResponse(items=rows)
