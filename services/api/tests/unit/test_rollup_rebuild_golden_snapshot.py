"""AC-6 golden-snapshot output-equivalence test for the SQL-aggregation
rewrite of `rollup_rebuild.py` (BED-05 T-09).

This is the load-bearing coverage for research risk #1 (HIGH). The Product
Gate's test-case manifest was capped at 2 cases by explicit instruction,
leaving `BED-05-AC-6`/`BED-05-FR-1` with no behavioural test case; the gate
was approved on the explicit condition that this unit-level comparison
carries the risk (`docs/features/BED-05/REQUIREMENTS.md` Approvals). Do not
narrow the table/column coverage below, add an exclusion beyond
`EXCLUDED_COLUMNS`, or relax the assertion to make a future rewrite pass --
if the rewrite and this test disagree, the rewrite is what's wrong.

Truth model: `tests/fixtures/rollup_golden_{20k,40k,160k}.json`, captured by
T-01 from the SHIPPED (pre-rewrite) implementation before T-03's rewrite
landed -- that Python-materialising behaviour no longer exists anywhere and
these fixtures cannot be regenerated. This test re-seeds `usage_events` to
each size (identical content to the fixture generator's own seed -- see
`_build_rows` below), runs the *rewritten* `rebuild_program_rollups` per
program and `rebuild_org_rollups`, and diffs every one of the 10 rollup
tables against the matching snapshot, row-by-row and column-by-column,
excluding only `EXCLUDED_COLUMNS` (regenerated every call by design, per the
story Decision log / BED-03 D-04 precedent).

T-03 already ran an ad-hoc version of this comparison during the rewrite and
reported "ALL MATCH" at 20k and 160k (see `tasks.json` T-03 `reason`) -- that
code was scratch and was deleted. This file is the durable, committed
version and does not assume that result: if it finds a mismatch T-03's
throwaway check missed, that is a genuine finding to report, not a bug in
this test to silence.

Comparison strategy (AF-02): `_build_user_sessions` emits one row per
`usage_events` row, so at 160k rows `user_sessions` is 160,000 of the
~162,600 exported rows and by far the dominant cost. `_compare_table` below
streams the actual (rewritten) side of every table via `AsyncSession.stream()`
-- a server-side cursor -- keyed by each table's natural business key (never
`id`, which is regenerated every call), so no table's actual output is ever
fully materialised into a second Python structure before comparing. The
expected (golden-snapshot) side is unavoidably fully loaded already -- the
JSON fixture is one document, and no streaming JSON parser is a project
dependency -- this only avoids a *second* full load plus a whole-structure
deep-diff.

Runtime (per the dispatch instructions): this repo registers no pytest
markers (`services/api/pyproject.toml` `[tool.pytest.ini_options]` sets only
`testpaths`) and no test anywhere in `tests/perf/` or `tests/unit/` uses an
unregistered mark or an env-var skip to separate "slow" from "fast" runs --
both `test:` and `test_unit:` in `docs/config/project-commands.yaml` already
run the whole `tests/` tree unconditionally, `tests/perf/` included. Inventing
a new marker/skip scheme here would be a scheme this project doesn't have,
not a convention it does -- so the 160k case is deliberately left
unconditional, and the cost is instead bounded structurally: chunked bulk
insert (`INSERT_CHUNK_SIZE`, matching the fixture generator's own chunking)
and the streaming, keyed comparison above, rather than a naive load-everything
diff.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.models as models
from app.services.rollup_rebuild import rebuild_org_rollups, rebuild_program_rollups
from tests.conftest import API_ROOT, AlembicRunner

FIXTURES_DIR: Path = API_ROOT / "tests" / "fixtures"

# Row-generation shape duplicated -- not imported -- from
# scripts/generate_rollup_golden_snapshots.py::_build_rows. That script
# produced the golden snapshots this test compares against, so re-seeding
# must reproduce identical usage_events content; any drift here would seed
# different input than the snapshot was captured from and invalidate the
# whole comparison silently rather than fail it loudly. Duplicated rather
# than imported because scripts/ holds one-off CLI entry points (the
# `mint_ingest_token.py` precedent), never a library surface another module
# imports from -- see tests/unit/test_mint_ingest_token.py, which exercises
# that script as a subprocess for the same reason.
COMMAND_CYCLE: tuple[str, ...] = ("cmd-a", "cmd-b", "cmd-c", "cmd-d", "cmd-e")
USER_COUNT = 200
BASE_TS = datetime(2026, 1, 1, tzinfo=UTC)
INSERT_CHUNK_SIZE = 5000
PROGRAM_COUNT = 4
PROGRAMS: tuple[str, ...] = tuple(f"prog-golden-{n}" for n in range(PROGRAM_COUNT))

# Excluded per story Decision log / BED-03 D-04 precedent: `id` and the three
# clock columns are regenerated on every rebuild call by design and are never
# part of the AC-6 output-identity contract. Not every table carries all
# four -- e.g. `user_sessions` has no `as_of_timestamp` column at all -- so
# this is applied as a set difference against each table's real columns,
# never assumed present.
EXCLUDED_COLUMNS = frozenset({"id", "as_of_timestamp", "created_at", "updated_at"})

# (table name, model, natural business key) -- mirrors, not imports,
# scripts/generate_rollup_golden_snapshots.py::ROLLUP_TABLES (same
# scripts-are-not-a-library-surface rationale as `_build_rows` above).
ROLLUP_TABLES: tuple[tuple[str, type[Any], tuple[str, ...]], ...] = (
    ("org_summary_rollup", models.OrgSummaryRollup, ("org_id",)),
    ("token_series", models.TokenSeries, ("month",)),
    ("mau_series", models.MauSeries, ("month",)),
    ("program_summary", models.ProgramSummary, ("program_id",)),
    ("program_releases", models.ProgramReleases, ("program_id",)),
    ("program_commands", models.ProgramCommands, ("program_id", "name")),
    ("program_members", models.ProgramMembers, ("program_id", "user_id")),
    ("session_series", models.SessionSeries, ("program_id", "member_id", "date")),
    ("program_token_series", models.ProgramTokenSeries, ("program_id", "date")),
    ("user_sessions", models.UserSessions, ("program_id", "session_identifier")),
)


def _build_rows(total: int, programs: tuple[str, ...]) -> list[dict[str, Any]]:
    """Reproduces `generate_rollup_golden_snapshots.py::_build_rows` exactly
    -- see module docstring "Row-generation shape".
    """
    rows: list[dict[str, Any]] = []
    for i in range(total):
        ts = BASE_TS + timedelta(seconds=i)
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "program_id": programs[i % len(programs)],
                "ts": ts,
                "cmd_ts": ts,
                "user": f"user-{i % USER_COUNT}",
                "session_id": f"sess-{i}",
                "command": COMMAND_CYCLE[i % len(COMMAND_CYCLE)],
                "duration_seconds": 10 + (i % 50),
                "outcome": "success",
                "total": 100 + (i % 500),
            }
        )
    return rows


async def _seed_usage_events(
    session: AsyncSession, total: int, programs: tuple[str, ...]
) -> None:
    """Chunked bulk insert (`INSERT_CHUNK_SIZE`, matching the fixture
    generator's own chunking) rather than one `total`-row statement or a
    per-row `session.add` loop.
    """
    rows = _build_rows(total, programs)
    for start in range(0, len(rows), INSERT_CHUNK_SIZE):
        chunk = rows[start : start + INSERT_CHUNK_SIZE]
        await session.execute(sa.insert(models.UsageEvent), chunk)
    await session.commit()


def _load_snapshot(size_label: str) -> dict[str, list[dict[str, Any]]]:
    path = FIXTURES_DIR / f"rollup_golden_{size_label}.json"
    result: dict[str, list[dict[str, Any]]] = json.loads(path.read_text())
    return result


def _normalize(value: Any) -> Any:
    """Mirrors the golden-snapshot generator's own `_serialize`: a `datetime`
    became an ISO string on export, so a live query's `datetime` values must
    be converted the same way before comparing against (or keying against)
    the loaded JSON.
    """
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _row_key(row: dict[str, Any], natural_key: tuple[str, ...]) -> tuple[Any, ...]:
    return tuple(_normalize(row.get(k)) for k in natural_key)


def _key_desc(row: dict[str, Any], natural_key: tuple[str, ...]) -> str:
    return ", ".join(f"{k}={_normalize(row.get(k))!r}" for k in natural_key)


async def _compare_table(
    session: AsyncSession,
    table_name: str,
    model: type[Any],
    natural_key: tuple[str, ...],
    expected_rows: list[dict[str, Any]],
) -> list[str]:
    """Row-by-row, column-by-column diff of one rewritten-rebuild table
    against its golden-snapshot rows, keyed by `natural_key` (AF-02).

    Streams the actual side via a server-side cursor (`AsyncSession.stream`)
    and matches each streamed row against a key->row dict built from the
    already-loaded expected side, rather than sorting both sides and zipping
    positionally -- this needs no assumption that Postgres's collation
    ordering for the natural-key columns is identical across the two
    (potentially different) database instances the snapshot was captured
    from and this comparison runs against. Only one full-table structure is
    ever held at once (`expected_rows`/`expected_by_key`); the actual side is
    never materialised beyond one streamed row at a time.
    """
    columns = tuple(c.name for c in model.__table__.columns)
    expected_by_key: dict[tuple[Any, ...], dict[str, Any]] = {
        _row_key(row, natural_key): row for row in expected_rows
    }
    assert len(expected_by_key) == len(expected_rows), (
        f"{table_name}: golden snapshot has duplicate rows for natural key "
        f"{natural_key} -- the fixture itself is not well-formed"
    )

    diffs: list[str] = []
    seen_keys: set[tuple[Any, ...]] = set()
    stmt = select(*(getattr(model, col) for col in columns))
    result = await session.stream(stmt)
    try:
        async for row in result:
            actual = dict(zip(columns, row, strict=True))
            key = _row_key(actual, natural_key)
            seen_keys.add(key)
            expected = expected_by_key.get(key)
            if expected is None:
                diffs.append(
                    f"{table_name}[{_key_desc(actual, natural_key)}]: row present in "
                    "the rewritten output but absent from the golden snapshot"
                )
                continue
            for col in columns:
                if col in EXCLUDED_COLUMNS:
                    continue
                exp_val = expected.get(col)
                act_val = _normalize(actual.get(col))
                if exp_val != act_val:
                    diffs.append(
                        f"{table_name}[{_key_desc(actual, natural_key)}]: column "
                        f"{col!r} expected={exp_val!r} actual={act_val!r}"
                    )
    finally:
        await result.close()

    for key in expected_by_key.keys() - seen_keys:
        missing_row = expected_by_key[key]
        diffs.append(
            f"{table_name}[{_key_desc(missing_row, natural_key)}]: row present in the "
            "golden snapshot but missing from the rewritten output"
        )
    return diffs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "size_label,total_events",
    [("20k", 20_000), ("40k", 40_000), ("160k", 160_000)],
)
async def test_rewritten_rebuild_matches_golden_snapshot(
    size_label: str,
    total_events: int,
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
) -> None:
    """BED-05-AC-6 / FR-1: re-seed `usage_events` to `total_events` rows
    (identical content to the golden-snapshot generator's own seed -- see
    `_build_rows`), run the *rewritten* `rebuild_program_rollups` for every
    program in `PROGRAMS` then `rebuild_org_rollups`, and diff every one of
    the 10 rollup tables against `tests/fixtures/rollup_golden_<size_label>.json`
    -- captured from the shipped (pre-rewrite) implementation by T-01, before
    T-03's SQL-aggregation rewrite existed. See module docstring for why this
    is the load-bearing coverage for research risk #1 (HIGH) and why it must
    not be weakened.

    `migrated_db` runs a fresh `upgrade head` before this test and
    `downgrade base` after (function-scoped, `tests/conftest.py`) -- each
    parametrized size starts from a genuinely empty, freshly migrated schema,
    matching the golden-snapshot generator's own per-size TRUNCATE-then-seed
    shape without needing to replicate the TRUNCATE step here.
    """
    await _seed_usage_events(test_session, total_events, PROGRAMS)

    for program_id in PROGRAMS:
        await rebuild_program_rollups(test_session, program_id)
    await rebuild_org_rollups(test_session)

    expected = _load_snapshot(size_label)
    all_diffs: list[str] = []
    for table_name, model, natural_key in ROLLUP_TABLES:
        all_diffs.extend(
            await _compare_table(
                test_session, table_name, model, natural_key, expected[table_name]
            )
        )

    shown = all_diffs[:50]
    remainder = len(all_diffs) - len(shown)
    detail = "\n".join(shown) + (f"\n... and {remainder} more" if remainder > 0 else "")
    assert not all_diffs, (
        f"AC-6 output-identity violated at {size_label} against the golden snapshot "
        f"({len(all_diffs)} row/column mismatch(es)):\n{detail}"
    )
