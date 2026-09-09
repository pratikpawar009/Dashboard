"""Generate the AC-6 golden-snapshot fixtures from the SHIPPED (pre-rewrite)
`app.services.rollup_rebuild` implementation, at 20k/40k/160k seeded
`usage_events` rows (BED-05-FR-1 / research condition C-3).

Standalone CLI, stdlib `argparse` only (`mint_ingest_token.py` precedent) —
run as:

    DATABASE_URL="postgresql+psycopg://<user>:<pass>@<host>:<port>/<db>" \\
        uv run python scripts/generate_rollup_golden_snapshots.py

from `services/api/`, against a disposable database that already has the
schema migrated to head (`uv run alembic upgrade head` first) — this script
does not create the database or run migrations itself, matching
`mint_ingest_token.py`'s own assumption that the target database already
exists and is schema-ready. `DATABASE_URL` is read once at process start by
`app.core.config.settings` / `app.core.db.engine` (see those modules) — never
point this at a real dev/prod database; it truncates every seeded table
between sizes.

MUST run before `rollup_rebuild.py`'s aggregation logic is rewritten (see
`docs/features/BED-05/PLAN.md` § 5 "Ordering constraint"). The output of this
script IS the AC-6 truth model; once the SQL-aggregation rewrite lands, the
pre-rewrite Python behaviour this script captures no longer exists anywhere
and cannot be regenerated.

Row-generation shape (deliberately reused from
`tests/perf/test_rollup_rebuild_perf.py::_build_rows`, extended with a
round-robin `program_id` so multiple programs — and therefore `rebuild_org_
rollups`' cross-program aggregation — are meaningfully exercised): each row's
`ts`/`cmd_ts` is `BASE_TS + timedelta(seconds=i)` for its 0-based index `i`
in the full seeded set for that size (one second apart, exactly like the
perf test); `session_id` is `f"sess-{i}"` (one session per row — the perf
test's own simplest-uniqueness-at-volume shape for `uq_usage_events_program_
session_cmd_ts`); `user` cycles `f"user-{i % USER_COUNT}"`; `command` cycles
`COMMAND_CYCLE`; `program_id` cycles `PROGRAMS` (round-robin). Every other
`usage_events` column not set below is left NULL (nullable in the model;
every `_build_*` aggregate treats a NULL numeric as 0 via `or 0`), matching
the perf test's own column set exactly — this script does not invent
additional richness beyond that established shape.

For each requested size, in order: TRUNCATE `usage_events` and all 10 rollup
tables (so each size's snapshot reflects that size in isolation, not
cumulative growth from a prior size); bulk-insert (chunked, not per-row ORM
adds) that size's `usage_events` rows; call the shipped `rebuild_program_
rollups` for every program in `PROGRAMS`, then the shipped `rebuild_org_
rollups`; export every rollup table's rows (every column, including `id` and
the `as_of_timestamp`/`created_at`/`updated_at` clock columns — the
comparison test this feeds, not this script, is what excludes them) to
`tests/fixtures/rollup_golden_<size//1000>k.json`, rows ordered by each
table's natural business key (not `id` or insertion order) so the fixture is
stable and diff-friish for whatever re-seeds the same shape later. JSON is
written compact (no indentation) — `user_sessions` gets one row per
`usage_events` row by this data shape's own design, so the 160k-row fixture
is large; compact encoding avoids inflating it further with whitespace.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.models as models
from app.core.config import NON_PRODUCTION_ENVIRONMENTS, settings
from app.core.db import SessionLocal
from app.services.rollup_rebuild import rebuild_org_rollups, rebuild_program_rollups

API_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = API_ROOT / "tests" / "fixtures"

COMMAND_CYCLE: tuple[str, ...] = ("cmd-a", "cmd-b", "cmd-c", "cmd-d", "cmd-e")
USER_COUNT = 200
BASE_TS = datetime(2026, 1, 1, tzinfo=UTC)
INSERT_CHUNK_SIZE = 5000
DEFAULT_SIZES: tuple[int, ...] = (20_000, 40_000, 160_000)
DEFAULT_PROGRAM_COUNT = 4

# Every rollup table this script exports, with the sort key that makes the
# exported rows order-stable across independent re-seeds/re-runs (natural
# business key, never `id` — ids are freshly generated uuid4s on every
# rebuild and carry no ordering meaning across runs).
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

# usage_events truncated alongside the 10 rollup tables above, between sizes.
_ALL_SEEDED_MODELS: tuple[type[Any], ...] = (models.UsageEvent, *(m for _, m, _ in ROLLUP_TABLES))


def _programs(count: int) -> tuple[str, ...]:
    return tuple(f"prog-golden-{n}" for n in range(count))


def _build_rows(total: int, programs: tuple[str, ...]) -> list[dict[str, Any]]:
    """`total` distinct `usage_events` rows, round-robin across `programs`.

    See module docstring "Row-generation shape" for the exact formula and its
    provenance (`tests/perf/test_rollup_rebuild_perf.py::_build_rows`).
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


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


async def _truncate_all(session: AsyncSession) -> None:
    for model in _ALL_SEEDED_MODELS:
        await session.execute(delete(model))
    await session.commit()


async def _seed(session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    for start in range(0, len(rows), INSERT_CHUNK_SIZE):
        chunk = rows[start : start + INSERT_CHUNK_SIZE]
        await session.execute(sa.insert(models.UsageEvent), chunk)
    await session.commit()


async def _export_table(
    session: AsyncSession, model: type[Any], sort_cols: tuple[str, ...]
) -> list[dict[str, Any]]:
    columns = [c.name for c in model.__table__.columns]
    order_by = [getattr(model, c) for c in sort_cols]
    result = await session.execute(select(model).order_by(*order_by))
    return [
        {col: _serialize(getattr(row, col)) for col in columns} for row in result.scalars().all()
    ]


async def _generate_one_size(
    total: int, programs: tuple[str, ...]
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, float]]:
    timings: dict[str, float] = {}
    async with SessionLocal() as session:
        t0 = time.perf_counter()
        await _truncate_all(session)
        timings["truncate_s"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        rows = _build_rows(total, programs)
        await _seed(session, rows)
        timings["seed_s"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        for program_id in programs:
            await rebuild_program_rollups(session, program_id)
        await rebuild_org_rollups(session)
        timings["rebuild_s"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        snapshot = {
            table_name: await _export_table(session, model, sort_cols)
            for table_name, model, sort_cols in ROLLUP_TABLES
        }
        timings["export_s"] = time.perf_counter() - t0

    return snapshot, timings


def _assert_safe_to_truncate(assume_yes: bool) -> str | None:
    """Refuse to run unless BOTH guards pass. Returns an error message, or None.

    BED-05 F-SEC-1 (High, security review 2026-09-09). `_truncate_all()` deletes
    every row from `usage_events` and all 10 rollup tables against whatever
    `DATABASE_URL` is in the ambient environment. Before this guard the script had
    no confirmation, no flag, and no environment check, so pointing it at a
    production URL would irreversibly destroy the ingest history and every rollup.

    Two independent layers, because the operation cannot be undone:

    1. **Environment allow-list** — membership in `NON_PRODUCTION_ENVIRONMENTS`,
       reusing `app.core.config`'s own frozenset rather than restating the values
       here (a second copy would drift the moment that one is edited). This is
       fail-closed by allow-list, not a `!= "production"` deny-check: nothing named
       `production` needs to be enumerated for it to be refused, and an
       unanticipated value -- a typo, an abbreviation, an unnamed real environment
       like `staging` -- is denied by default. Same discipline as
       `Settings.dev_bypass_enabled` / `/auth/dev-bypass` (config D-01).
    2. **Explicit `--yes`** — an allow-listed environment is not on its own consent.
       A developer whose `ENVIRONMENT` happens to say `dev` while `DATABASE_URL`
       points at a shared database still has to opt in per invocation.
    """
    if settings.environment not in NON_PRODUCTION_ENVIRONMENTS:
        return (
            f"refusing to run: ENVIRONMENT is {settings.environment!r}, which is not in the "
            f"allow-list {sorted(NON_PRODUCTION_ENVIRONMENTS)}. This script TRUNCATES "
            f"usage_events and all rollup tables; it is a local fixture-generation tool only."
        )
    if not assume_yes:
        return (
            "refusing to run without --yes: this script DELETES every row in usage_events "
            "and all 10 rollup tables on the database DATABASE_URL points at. Re-run with "
            "--yes once you have confirmed the target is a disposable database."
        )
    return None


async def _run(sizes: list[int], programs: tuple[str, ...], output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    for size in sizes:
        label = f"{size // 1000}k"
        print(
            f"[{label}] seeding {size} usage_events across {len(programs)} programs...",
            file=sys.stderr,
        )
        started = time.perf_counter()
        snapshot, timings = await _generate_one_size(size, programs)
        total_elapsed = time.perf_counter() - started

        out_path = output_dir / f"rollup_golden_{label}.json"
        payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
        out_path.write_text(payload + "\n")
        size_bytes = out_path.stat().st_size

        row_counts = {name: len(rows) for name, rows in snapshot.items()}
        print(
            f"[{label}] wrote {out_path} ({size_bytes:,} bytes) in {total_elapsed:.2f}s "
            f"(truncate={timings['truncate_s']:.2f}s seed={timings['seed_s']:.2f}s "
            f"rebuild={timings['rebuild_s']:.2f}s export={timings['export_s']:.2f}s)",
            file=sys.stderr,
        )
        print(f"[{label}] row counts per table: {row_counts}", file=sys.stderr)
    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="generate_rollup_golden_snapshots.py",
        description=(
            "Generate AC-6 golden-snapshot fixtures from the shipped "
            "(pre-rewrite) rollup_rebuild.py implementation."
        ),
    )
    parser.add_argument(
        "--sizes",
        default=",".join(str(s) for s in DEFAULT_SIZES),
        help=f"Comma-separated total usage_events row counts (default: {DEFAULT_SIZES}).",
    )
    parser.add_argument(
        "--program-count",
        type=int,
        default=DEFAULT_PROGRAM_COUNT,
        help=(
            "Number of distinct programs to round-robin rows across "
            f"(default: {DEFAULT_PROGRAM_COUNT})."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory to write rollup_golden_<size>.json into (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help=(
            "Confirm the destructive truncate of usage_events and all rollup tables. "
            "Required; see _assert_safe_to_truncate (BED-05 F-SEC-1)."
        ),
    )
    return parser.parse_args(argv)


def main() -> int:
    args = _parse_args(sys.argv[1:])
    refusal = _assert_safe_to_truncate(args.yes)
    if refusal is not None:
        print(f"generate_rollup_golden_snapshots.py: {refusal}", file=sys.stderr)
        return 2
    sizes = [int(s.strip()) for s in args.sizes.split(",") if s.strip()]
    programs = _programs(args.program_count)
    return asyncio.run(_run(sizes, programs, args.output_dir))


if __name__ == "__main__":
    sys.exit(main())
