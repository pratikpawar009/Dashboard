"""Performance test for `get_ingest_token()` -- ING-01-TC-22
(`ING-01-NFR-performance`): the token verification path (SHA-256 hash +
indexed `token_hash` lookup + ING-01-FR-3 scope check) adds p95 < 10ms to
request latency (`docs/features/ING-01/REQUIREMENTS.md` § Non-functional
requirements; `DATA-DESIGN.md` § 8 -- one indexed point lookup per call, no
fan-out; the PRD labels the 10ms figure an assumption with rationale, not a
measured figure -- this test is what makes it measured).

Structure mirrors this repo's other perf tests (`tests/perf/test_rbac_perf.py`,
`tests/perf/test_programs_perf.py`): plain `time.perf_counter()`, no
dedicated benchmark tool or new dependency (this task's own notes name
those two files as the pattern to match; PLAN.md § 7 § Runner setup
requires no runner installation). `_percentile` below is copied rather than
imported, per this repo's established precedent of each perf file keeping
its own small copy instead of a shared `perf_utils` module
(reusability-baseline.md: "extract on the third repetition, not the
first" -- scoped to a module's own repeated code, not cross-file
duplication of a five-line, dependency-free helper).

Seeded directly, not via the mint script/CLI: one active `IngestToken` row
is inserted through `test_session` with `allowed_program_ids=[]` (TC-22's
own precondition -- "isolate lookup+hash cost from scope-array size", the
allow-all branch, the cheapest possible scope check so the measured window
reflects hash+lookup cost, not scope-array size). `get_ingest_token()` is
called directly with a hand-built `HTTPAuthorizationCredentials` and
`test_session` -- not through a mounted app/route -- so the measured window
is exactly the function body TC-22 names (hash + lookup + scope check),
never HTTP/ASGI/dependency-injection overhead. Fixture setup and row
seeding happen before the timed loop starts, so neither is in the measured
window.

No `production_logging` fixture (unlike `test_rbac_perf.py`/
`test_programs_perf.py`): `get_ingest_token`'s `_log_ingest_token_auth_failed`
call fires on every denial branch but never on success (FR-5,
"denial-only event") -- the measured, all-passing loop below never executes
a logging call, so there is nothing for that fixture to make realistic here.

Structural, not measured, coverage of TC-22's second expected result ("each
call performs exactly one indexed token_hash lookup, no N+1 query
pattern"): `get_ingest_token`'s body (`app/core/ingest_auth.py`) issues
exactly one `select(IngestToken).where(IngestToken.token_hash == ...)`
statement per call and no loop/second query on the passing path -- readable
directly off the function under test, not asserted here via a query-count
spy.

Honest measurement: if the p95 budget breaches, that is reported as a
finding with the measured number -- not hidden by loosening the budget,
adding unrequested warm-up iterations, or trimming outliers to get under
the line.
"""

from __future__ import annotations

import hashlib
import math
import secrets
import time

import pytest
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ingest_auth import get_ingest_token
from app.models.ingestion import IngestToken
from tests.conftest import AlembicRunner

# ING-01-TC-22 test_data -- do not relax.
ITERATIONS = 100
P95_BUDGET_MS = 10.0

_PROGRAM_ID = "prog-perf-1"


def _percentile(sorted_values_ms: list[float], pct: float) -> float:
    """Nearest-rank percentile over an already-sorted list, in milliseconds.

    index = ceil(pct * N) - 1 -- copied from `test_rbac_perf.py::_percentile`
    / `test_programs_perf.py::_percentile` (same deterministic,
    dependency-free method; no numpy/statistics.quantiles interpolation
    ambiguity to document).
    """
    n = len(sorted_values_ms)
    rank = math.ceil(pct * n)
    return sorted_values_ms[rank - 1]


@pytest.mark.asyncio
async def test_get_ingest_token_p95_under_10ms_tc22(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
) -> None:
    """ING-01-TC-22: one active, unscoped (`allowed_program_ids=[]`) row
    seeded, 100 measured passing `get_ingest_token()` calls -- p95 must stay
    under `P95_BUDGET_MS`. See module docstring for the full setup rationale.
    """
    raw_token = "hrn_pat_" + secrets.token_hex(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    test_session.add(
        IngestToken(
            token_hash=token_hash,
            label="perf-baseline-tc22",
            user_email="perf-tc22@example.com",
            allowed_program_ids=[],
            expires_at=None,
            revoked_at=None,
        )
    )
    await test_session.commit()

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=raw_token)

    latencies_ms: list[float] = []
    for _ in range(ITERATIONS):
        started = time.perf_counter()
        await get_ingest_token(
            program_id=_PROGRAM_ID, credentials=credentials, session=test_session
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        latencies_ms.append(elapsed_ms)

    latencies_ms.sort()
    p95 = _percentile(latencies_ms, 0.95)

    # Capture the measured baseline for future optimization stories, visible
    # with `pytest -s` (mirrors test_programs_perf.py's C-4 baseline print).
    print(
        f"\nING-01-TC-22 baseline -- p95={p95:.4f}ms across {ITERATIONS} calls "
        f"(1 seeded row, allow-all scope); min={latencies_ms[0]:.4f}ms "
        f"max={latencies_ms[-1]:.4f}ms"
    )

    assert p95 < P95_BUDGET_MS, (
        f"get_ingest_token() p95 latency {p95:.4f}ms exceeded the ING-01-TC-22 "
        f"/ NFR-performance budget of {P95_BUDGET_MS}ms across {ITERATIONS} "
        "calls on a passing, allow-all-scoped path. Do not relax this budget "
        "or trim outliers to get under the line; report the measured number "
        "as a finding for the engineer."
    )
