"""Performance test for `POST /api/ingest/artifacts` -- ING-03-NFR-performance
(F-19; test-case GAP #3 per `docs/features/ING-03/PLAN.md` § 7).

Structure follows the ING-02 perf convention
(`test_ingest_files_perf.py`): plain `time.perf_counter()` under the
existing pytest runner, a locally-copied nearest-rank `_percentile`
helper, and a "do not relax this budget" failure message. Marked
`@pytest.mark.perf` per D-05 -- opt-in via `pytest -m perf`; excluded
from the default `pytest` invocation by
`services/api/pyproject.toml:58-61`'s `-m 'not perf'` addopt.

NFR budget: **p95 < 300 ms** for one `<=5-row` artifacts upsert against
a program-artifacts table pre-seeded with two OTHER programs' artifacts
rows (per `docs/features/ING-03/DATA-DESIGN.md` § 8 "NFR budget"). N=50
iterations against a real Postgres.

What the request-path timing window includes, exactly (ADR-0013):
    bearer-token lookup (`get_ingest_token`)
    + `ArtifactCountsIn.model_validate` (Pydantic validation)
    + one `pg_insert(program_artifacts).on_conflict_do_update(
      index_elements=["program_id","type"], set_={"count": excluded.count,
      "as_of_timestamp": excluded.as_of_timestamp})`
    + one `db.commit()`
    + `log_ingest_artifacts_write` emit
    + JSON serialisation of the `IngestArtifactsResponse`

What the request-path timing window EXCLUDES, and how:
    NO `BackgroundTasks.add_task` scheduling call on the artifacts
    branch (D-03 / ADR-0012 non-applicability -- unlike the activity
    branch's `background_tasks.add_task(dispatch_org_rebuild)`). So no
    ADR-0012-style boundary monkeypatch is needed here; the artifacts
    path just does not schedule any background work.

Seeding shape: two OTHER programs' artifacts rows (one row per program
per canonical type, 10 rows total) exist at the moment the timed push
starts. The `pg_insert(...).on_conflict_do_update(index_elements=
["program_id","type"])` lookup is `O(log n)` on the composite unique
index, independent of the total table size in practice; the seed's job
is to prove the p95 budget holds against a non-empty, program-scope-
mixed table -- not to grow the table to a specific accumulated size
(unlike ING-02's `usage_events` cost curve, where in-program row count
drives `rebuild_program_rollups`'s cost -- `program_artifacts` has no
rollup source relationship, D-03).

Warmup discipline: one unmeasured POST at the same payload shape
precedes the timed loop. Same reasoning as
`test_ingest_files_perf.py`'s module docstring "Warmup discipline"
section: absorbs one-off costs (connection-pool warmup, prepared-
statement cache, ASGI transport warmup, Python function-call/JIT
settling) so the first timed iteration is not systematically slower.
"""

from __future__ import annotations

import hashlib
import math
import secrets
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.governance import ProgramArtifact
from app.models.ingestion import IngestToken
from app.schemas.ingest_artifacts import _CANONICAL_ARTIFACT_TYPES
from tests.conftest import AlembicRunner

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

_INGEST_PATH = "/api/ingest/artifacts"
P95_BUDGET_SECONDS = 0.300  # ING-03-NFR-performance -- do not relax
ITERATIONS = 50
TARGET_PROGRAM_ID = "prog-perf-ing03-target"
OTHER_PROGRAM_IDS: tuple[str, str] = (
    "prog-perf-ing03-other-a",
    "prog-perf-ing03-other-b",
)
_AS_OF = datetime(2026, 9, 13, 10, 0, 0, tzinfo=UTC)


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Nearest-rank percentile over an already-sorted list.

    Copied from `test_ingest_files_perf.py` per this repo's per-file-
    ownership precedent for a small, dependency-free helper.
    """
    n = len(sorted_values)
    rank = math.ceil(pct * n)
    return sorted_values[rank - 1]


def _seed_artifact(index: int, program_id: str, artifact_type: str) -> dict[str, Any]:
    """One `program_artifacts` seed row, unique per (program_id, type)
    per the composite UNIQUE constraint
    `uq_program_artifacts_program_id_type`."""
    return {
        "id": str(uuid.uuid4()),
        "program_id": program_id,
        "type": artifact_type,
        "count": index + 1,
        "as_of_timestamp": _AS_OF,
    }


async def _seed_other_programs(session: AsyncSession) -> None:
    """Bulk-seed one row per (OTHER program × canonical type). Runs
    OUTSIDE every measured window; committed once so the router's
    `test_session` sees committed rows on the timed post."""
    rows: list[dict[str, Any]] = []
    idx = 0
    for program_id in OTHER_PROGRAM_IDS:
        for artifact_type in sorted(_CANONICAL_ARTIFACT_TYPES):
            rows.append(_seed_artifact(idx, program_id, artifact_type))
            idx += 1
    await session.execute(sa.insert(ProgramArtifact), rows)
    await session.commit()


async def _seed_ingest_token(session: AsyncSession) -> str:
    """Seed one `ingest_tokens` row scoped to `TARGET_PROGRAM_ID` and
    return its raw bearer token."""
    raw_token = "hrn_pat_" + secrets.token_hex(32)
    session.add(
        IngestToken(
            token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
            label="ing-03-perf-t13",
            user_email="ing-03-perf@example.invalid",
            allowed_program_ids=[TARGET_PROGRAM_ID],
        )
    )
    await session.commit()
    return raw_token


def _db_override(session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _get_db() -> AsyncIterator[AsyncSession]:
        yield session

    return _get_db


def _push_payload() -> dict[str, Any]:
    """Realistic <=5-row artifacts payload. Full canonical vocabulary
    exercises the ON CONFLICT path against all five (program_id, type)
    composite keys per iteration -- five upserts, one round-trip."""
    return {
        "program_id": TARGET_PROGRAM_ID,
        "kind": "artifacts",
        "counts": {t: idx + 1 for idx, t in enumerate(sorted(_CANONICAL_ARTIFACT_TYPES))},
        "as_of": _AS_OF.isoformat().replace("+00:00", "Z"),
    }


@pytest.mark.perf
@pytest.mark.asyncio
async def test_push_artifacts_p95_under_300ms(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """ING-03-NFR-performance: N=50 iterations of the artifacts push
    against a pre-seeded (two OTHER programs) `program_artifacts` table
    stays under 300 ms p95 end-to-end request-path latency. See module
    docstring for what the timing window includes; F-16
    (`test_ingest_artifacts_no_rollup_dispatch.py`) enforces that
    NOTHING off-request-path exists to elide."""
    await _seed_other_programs(test_session)
    raw_token = await _seed_ingest_token(test_session)

    app = build_app()
    app.dependency_overrides[get_db] = _db_override(test_session)
    headers = {"Authorization": f"Bearer {raw_token}"}
    payload = _push_payload()

    latencies: list[float] = []
    async with async_client_for(app) as client:
        # Unmeasured warmup -- same reasoning as ING-02's perf test.
        warmup = await client.post(_INGEST_PATH, json=payload, headers=headers)
        assert warmup.status_code == 200, warmup.text

        for _ in range(ITERATIONS):
            started = time.perf_counter()
            resp = await client.post(_INGEST_PATH, json=payload, headers=headers)
            elapsed = time.perf_counter() - started
            assert resp.status_code == 200, resp.text
            latencies.append(elapsed)

    latencies.sort()
    p95 = _percentile(latencies, 0.95)
    p50 = _percentile(latencies, 0.50)

    print(
        f"\nING-03-NFR-performance -- POST /api/ingest/artifacts "
        f"N={ITERATIONS} p50={p50 * 1000:.1f}ms p95={p95 * 1000:.1f}ms "
        f"(budget {P95_BUDGET_SECONDS * 1000:.0f}ms)"
    )

    assert p95 < P95_BUDGET_SECONDS, (
        f"POST /api/ingest/artifacts p95 took {p95 * 1000:.1f}ms across "
        f"N={ITERATIONS} iterations, exceeding the "
        f"ING-03-NFR-performance budget of "
        f"{P95_BUDGET_SECONDS * 1000:.0f}ms. Do not relax this budget; "
        f"D-03 already applies (no background dispatch is in the path) "
        f"-- a breach means the on-path work (bearer-lookup + Pydantic "
        f"validation + single-txn ON CONFLICT DO UPDATE + commit) has "
        f"regressed. Report the measured p95 for escalation."
    )
