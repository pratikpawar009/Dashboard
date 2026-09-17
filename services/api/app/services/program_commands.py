"""Query/aggregation layer for `GET /api/overview/program-detail/{program_id}/commands`
(PGD-04, DECISIONS.md D-01/D-02/D-03).

D-01 (critical): aggregates from `usage_events` (per-event `ts`), NEVER from `program_commands`
-- the latter is a lifetime, unranged rollup (`rollup_rebuild.py:246` groups with no time
filter), so reading it would make `?range=` a silent no-op. Mirrors `app/services/
personal_usage.py::fetch_commands_breakdown` / `_build_commands_panel` exactly, with
`WHERE "user" = :user_id` swapped for `WHERE program_id = :program_id`, backed by the existing
`ix_usage_events_program_id_command` index (`app/models/ingestion.py:38`) -- no migration
needed. D-02: this module performs no existence lookup and never raises for an unknown or quiet
`program_id` -- a zero-row aggregation simply yields `CommandsPanel(total_runs="0", items=[])`.
D-03: returns the existing `CommandsPanel`/`CommandEntry` shape imported from
`app/schemas/personal_usage.py` -- no new schema module.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.range import range_to_start
from app.models.ingestion import UsageEvent
from app.schemas.personal_usage import CommandEntry, CommandsPanel
from app.utils.format import bar_style_for_share, format_number


def _build_commands_panel(rows: list[tuple[str, int]]) -> CommandsPanel:
    """Compute `total_runs` and each command's max-of-range `barStyle` from the grouped rows.

    Empty `rows` (no in-range events, including an unknown `program_id` -- D-02) yields an
    empty `items` list and `total_runs='0'`.
    """
    counts = [count for _, count in rows]
    max_count = max(counts, default=0)
    items = [
        CommandEntry(command=command, count=count, barStyle=bar_style_for_share(count, max_count))
        for command, count in rows
    ]
    return CommandsPanel(total_runs=format_number(sum(counts)), items=items)


async def fetch_program_commands(
    db: AsyncSession, program_id: str, range_value: str
) -> CommandsPanel:
    """Range-scoped commands breakdown over `usage_events` ONLY (PGD-04-FR-2/FR-3).

    One grouped `SELECT command, count(*) FROM usage_events WHERE program_id = :program_id AND
    ts >= :range_start GROUP BY command`, using the existing `ix_usage_events_program_id_command`
    index. `command` passes through verbatim from `usage_events.command` (including its leading
    slash) and `count` stays a raw int on the wire -- the bar formula's own numerator/denominator
    input, not a display value. Performs NO `program_summary` existence lookup (D-02): an unknown
    `program_id` yields zero rows here and resolves to the same empty `CommandsPanel` as a known,
    quiet program.
    """
    range_start = range_to_start(range_value)
    stmt = (
        select(UsageEvent.command, func.count(UsageEvent.id))
        .where(UsageEvent.program_id == program_id, UsageEvent.ts >= range_start)
        .group_by(UsageEvent.command)
        # The mockup renders these as a descending bar ranking, and `barStyle`
        # is already computed against the range's max count -- without an
        # explicit ORDER BY the rows arrive in whatever order the grouping
        # produces, so the longest bar is not necessarily first. `command`
        # breaks ties so equal counts stay in a stable, reproducible order
        # rather than varying between calls.
        .order_by(func.count(UsageEvent.id).desc(), UsageEvent.command)
    )
    result = await db.execute(stmt)
    rows = [(command, count) for command, count in result.all()]
    return _build_commands_panel(rows)
