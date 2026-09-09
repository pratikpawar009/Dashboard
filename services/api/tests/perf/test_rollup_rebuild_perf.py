"""Performance tests for BED-05-TC-02 (AC-4/AC-5/AC-8): rollup rebuild cost is
budgeted against a pinned **table size**, never a batch size, and the growth
curve is asserted rather than assumed.

Replaces BED-03-TC-15's single `EVENT_COUNT = 5000` / `BUDGET_SECONDS = 2.0`
assertion. That test seeded one program into an otherwise **empty** table, so it
could not observe the cost-growth curve at all -- which is the thing this story
exists to change (AC-8: "seeds a populated, growing `usage_events` table ...
asserts each function's duration against a pinned table size -- never batch
size").

Structure follows this repo's perf convention (`test_range_pagination_perf.py`):
plain `time.perf_counter()` under the existing pytest runner, a copied
nearest-rank `_percentile`, named budget constants, and a "do not relax this
budget" failure message. No new benchmarking dependency.

Every budget below is **measured, not guessed** (DECISIONS.md D-02). Earlier
phases deliberately refused to invent a rebuild budget before the aggregation
rewrite existed; T-06 measured the rewritten implementation against a
004-migrated database and those figures are recorded in `tasks.json` T-06's
completion `reason`. The constants here sit roughly 2-3x above the measured p95
so ordinary CI variance does not turn them into flakes, while a genuine
regression to the pre-rewrite cost model still trips them by a wide margin.

What the three tests divide up, and why it takes three:

- `test_org_rebuild_budget_and_growth_curve` -- `rebuild_org_rollups` aggregates
  the **whole** table, so its cost necessarily grows with total rows. AC-4 asks
  it to meet a budget, not to be flat. Asserted: absolute budget at both pinned
  sizes, plus a growth-ratio ceiling well inside the pre-rewrite baseline's
  9.3x (417ms -> 3,864ms across 20k -> 160k, measured live in research).
- `test_program_rebuild_budget_by_in_program_size` -- absolute budgets for
  `rebuild_program_rollups` at both pinned sizes.
- `test_program_rebuild_does_not_track_total_history` -- **this one encodes AC-5
  and is the sharpest guard in the file.** AC-5 forbids the program rebuild
  tracking *total history*, so the only honest test holds in-program rows fixed
  and grows the rest of the table underneath it. The two other shapes cannot
  distinguish "tracks total" from "tracks in-program", because the story's own
  baseline grew both together (5k in-program at 20k total -> 40k in-program at
  160k total).

Known limitation, recorded rather than hidden (flag AF-08): the program rebuild
is flat in *total* rows but still scales with a single program's **own**
accumulated rows -- ~3.6s p95 at 40k in-program. That exceeds ING-02's entire
end-to-end p95 <= 3s ceiling on its own, so `_PROGRAM_BUDGET_40K_SECONDS` below
is a *measurement fence*, not evidence that the in-request rebuild fits the
product budget at that scale. Do not read a passing test here as clearance for
arbitrarily large programs.

Seeding is chunked and runs outside every measured window; only the rebuild
calls themselves are timed. These tests seed 20k/160k/160k rows and are
correspondingly slow -- see AF-08/AF-07 on this repo having no slow-test marker
convention to opt them out of the default run.
"""

from __future__ import annotations

import math
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

import app.models as models
from app.services.rollup_rebuild import rebuild_org_rollups, rebuild_program_rollups
from tests.conftest import AlembicRunner

# --- seed shape (unchanged from BED-03-TC-15 / the golden-snapshot generator) ---
COMMAND_CYCLE = ("cmd-a", "cmd-b", "cmd-c", "cmd-d", "cmd-e")
USER_COUNT = 200
BASE_TS = datetime(2026, 1, 1, tzinfo=UTC)
INSERT_CHUNK_SIZE = 5000

PROGRAMS = ("prog-perf-0", "prog-perf-1", "prog-perf-2", "prog-perf-3")
TARGET_PROGRAM = PROGRAMS[0]

# --- pinned table sizes (AC-8: table size, never batch size) ---
SMALL_TOTAL = 20_000  # 5,000 rows in each of 4 programs
LARGE_TOTAL = 160_000  # 40,000 rows in each of 4 programs
FIXED_IN_PROGRAM = 5_000  # held constant by the total-independence test

MEASURED_REPS = 3  # nearest-rank p95 over 3 reps == the slowest, deliberately conservative

# --- budgets: measured p95 (T-06) -> constant, with headroom. Do not relax. ---
# rebuild_program_rollups, 5,000 in-program rows        measured p95 0.53s
_PROGRAM_BUDGET_5K_SECONDS = 1.5
# rebuild_program_rollups, 40,000 in-program rows       measured p95 3.65s
_PROGRAM_BUDGET_40K_SECONDS = 7.0
# rebuild_org_rollups, 20,000 total rows                measured p95 0.07s
_ORG_BUDGET_20K_SECONDS = 0.5
# rebuild_org_rollups, 160,000 total rows               measured p95 0.49s
_ORG_BUDGET_160K_SECONDS = 1.5

# Growth-curve ceilings (AC-8: "fails on a growth-curve regression").
# Org: measured 6.7x for an 8x row increase; pre-rewrite baseline was 9.3x.
_ORG_GROWTH_MAX_RATIO = 8.0
# Program vs TOTAL rows: measured 1.02x for an 8x total increase. This is AC-5.
_TOTAL_INDEPENDENCE_MAX_RATIO = 1.5


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Nearest-rank percentile over an already-sorted list.

    Copied from `test_range_pagination_perf.py` rather than shared, matching
    that file's own note: deterministic and dependency-free, with no
    numpy/`statistics.quantiles` interpolation ambiguity to document.
    """
    n = len(sorted_values)
    rank = math.ceil(pct * n)
    return sorted_values[rank - 1]


def _row(index: int, program_id: str) -> dict[str, Any]:
    """One `usage_events` row.

    `session_id`/`cmd_ts` vary per row to satisfy
    `uq_usage_events_program_session_cmd_ts`; `user`/`command` cycle through
    small pools so the rebuild's per-table grouping does real aggregation work
    instead of degenerating to one group per row.
    """
    ts = BASE_TS + timedelta(seconds=index)
    return {
        "id": str(uuid.uuid4()),
        "program_id": program_id,
        "ts": ts,
        "cmd_ts": ts,
        "user": f"user-{index % USER_COUNT}",
        "session_id": f"sess-{index}",
        "command": COMMAND_CYCLE[index % len(COMMAND_CYCLE)],
        "duration_seconds": 10 + (index % 50),
        "outcome": "success",
        "total": 100 + (index % 500),
    }


def _round_robin_rows(total: int) -> list[dict[str, Any]]:
    """`total` rows spread evenly across `PROGRAMS`."""
    return [_row(i, PROGRAMS[i % len(PROGRAMS)]) for i in range(total)]


def _skewed_rows(total: int, in_program: int) -> list[dict[str, Any]]:
    """`in_program` rows for `TARGET_PROGRAM`, the remainder for the others.

    This is what makes the total-independence assertion possible: it decouples
    one program's row count from the size of the table around it.
    """
    rows = [_row(i, TARGET_PROGRAM) for i in range(in_program)]
    rows += [
        _row(in_program + i, PROGRAMS[1 + (i % (len(PROGRAMS) - 1))])
        for i in range(total - in_program)
    ]
    return rows


async def _reseed(session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    """Truncate `usage_events` and bulk-insert `rows`, outside any timed window."""
    await session.execute(sa.text("TRUNCATE usage_events"))
    await session.commit()
    for start in range(0, len(rows), INSERT_CHUNK_SIZE):
        await session.execute(sa.insert(models.UsageEvent), rows[start : start + INSERT_CHUNK_SIZE])
    await session.commit()


async def _time_program_rebuild(session: AsyncSession, program_id: str) -> float:
    """p95 wall-clock seconds for `rebuild_program_rollups` over `MEASURED_REPS`."""
    samples: list[float] = []
    for _ in range(MEASURED_REPS):
        started = time.perf_counter()
        await rebuild_program_rollups(session, program_id)
        samples.append(time.perf_counter() - started)
    return _percentile(sorted(samples), 0.95)


async def _time_org_rebuild(session: AsyncSession) -> float:
    """p95 wall-clock seconds for `rebuild_org_rollups` over `MEASURED_REPS`."""
    samples: list[float] = []
    for _ in range(MEASURED_REPS):
        started = time.perf_counter()
        await rebuild_org_rollups(session)
        samples.append(time.perf_counter() - started)
    return _percentile(sorted(samples), 0.95)


@pytest.mark.asyncio
async def test_org_rebuild_budget_and_growth_curve(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """AC-4: `rebuild_org_rollups` meets its budget at two pinned table sizes,
    and its growth stays well inside the pre-rewrite baseline's curve.

    The org rebuild aggregates the whole table, so growth with total rows is
    expected and correct -- AC-4 asks for a budget, not flatness.
    """
    await _reseed(test_session, _round_robin_rows(SMALL_TOTAL))
    small_p95 = await _time_org_rebuild(test_session)

    await _reseed(test_session, _round_robin_rows(LARGE_TOTAL))
    large_p95 = await _time_org_rebuild(test_session)

    assert small_p95 <= _ORG_BUDGET_20K_SECONDS, (
        f"rebuild_org_rollups p95 {small_p95:.3f}s at {SMALL_TOTAL:,} total rows exceeds the "
        f"{_ORG_BUDGET_20K_SECONDS}s budget (measured p95 was 0.07s). Do not relax this budget "
        f"-- investigate the regression."
    )
    assert large_p95 <= _ORG_BUDGET_160K_SECONDS, (
        f"rebuild_org_rollups p95 {large_p95:.3f}s at {LARGE_TOTAL:,} total rows exceeds the "
        f"{_ORG_BUDGET_160K_SECONDS}s budget (measured p95 was 0.49s). Do not relax this budget "
        f"-- investigate the regression."
    )

    ratio = large_p95 / small_p95
    assert ratio <= _ORG_GROWTH_MAX_RATIO, (
        f"rebuild_org_rollups grew {ratio:.1f}x across an {LARGE_TOTAL // SMALL_TOTAL}x row "
        f"increase, above the {_ORG_GROWTH_MAX_RATIO}x ceiling (measured 6.7x; the pre-rewrite "
        f"baseline was 9.3x, 417ms -> 3,864ms). A growth-curve regression means the SQL "
        f"aggregation has partially reverted to row materialisation."
    )


@pytest.mark.asyncio
async def test_program_rebuild_budget_by_in_program_size(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """AC-5: `rebuild_program_rollups` meets its budget at two pinned sizes.

    See the module docstring's "Known limitation": the 40k budget is a
    measurement fence, not clearance that an in-request rebuild fits ING-02's
    product budget at that scale.
    """
    await _reseed(test_session, _round_robin_rows(SMALL_TOTAL))
    small_p95 = await _time_program_rebuild(test_session, TARGET_PROGRAM)

    await _reseed(test_session, _round_robin_rows(LARGE_TOTAL))
    large_p95 = await _time_program_rebuild(test_session, TARGET_PROGRAM)

    assert small_p95 <= _PROGRAM_BUDGET_5K_SECONDS, (
        f"rebuild_program_rollups p95 {small_p95:.3f}s at "
        f"{SMALL_TOTAL // len(PROGRAMS):,} in-program rows exceeds the "
        f"{_PROGRAM_BUDGET_5K_SECONDS}s budget (measured p95 was 0.53s). Do not relax this "
        f"budget -- investigate the regression."
    )
    assert large_p95 <= _PROGRAM_BUDGET_40K_SECONDS, (
        f"rebuild_program_rollups p95 {large_p95:.3f}s at "
        f"{LARGE_TOTAL // len(PROGRAMS):,} in-program rows exceeds the "
        f"{_PROGRAM_BUDGET_40K_SECONDS}s budget (measured p95 was 3.65s). Do not relax this "
        f"budget -- investigate the regression."
    )


@pytest.mark.asyncio
async def test_program_rebuild_does_not_track_total_history(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """AC-5's actual claim: duration must not track **total** history.

    In-program rows are held at `FIXED_IN_PROGRAM` while the table around them
    grows 8x. Pre-rewrite this scaled with the whole table, because
    `rebuild_program_rollups` read every row via a bare `select(UsageEvent)`.

    This is the assertion that would catch a reintroduced unfiltered scan even
    if the absolute budgets above still happened to pass.
    """
    await _reseed(test_session, _skewed_rows(SMALL_TOTAL, FIXED_IN_PROGRAM))
    at_small_total = await _time_program_rebuild(test_session, TARGET_PROGRAM)

    await _reseed(test_session, _skewed_rows(LARGE_TOTAL, FIXED_IN_PROGRAM))
    at_large_total = await _time_program_rebuild(test_session, TARGET_PROGRAM)

    ratio = at_large_total / at_small_total
    assert ratio <= _TOTAL_INDEPENDENCE_MAX_RATIO, (
        f"rebuild_program_rollups grew {ratio:.2f}x ({at_small_total:.3f}s -> "
        f"{at_large_total:.3f}s) when TOTAL rows grew {LARGE_TOTAL // SMALL_TOTAL}x while "
        f"in-program rows stayed at {FIXED_IN_PROGRAM:,}. AC-5 requires duration not track total "
        f"history; measured ratio was 1.02x. Above {_TOTAL_INDEPENDENCE_MAX_RATIO}x means the "
        f"per-program aggregation is reading rows outside its own program again -- do not relax "
        f"this ceiling, it is the story's core invariant."
    )
