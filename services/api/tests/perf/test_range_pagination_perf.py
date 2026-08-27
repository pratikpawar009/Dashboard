"""Performance test for BED-02-TC-18 (NFR-002) — floor-check on the shared
contract's own overhead, NOT proof of the 2s range/filter-change refresh
budget end to end.

What this covers: a throwaway FastAPI test route composed exactly as
BED-02-TC-18 specifies — `Depends(validate_range)` + the offset/limit
pagination helper + a services derived-value call
(`compute_guardrail_summary`) over a representative row volume
(`GUARDRAIL_ROW_COUNT` rows, mixed pass/fail statuses) — driven through 5
unmeasured warmup requests followed by 50 measured sequential requests
cycling `range` through 7d/30d/90d, asserting p95 latency stays under the
NFR-002 budget.

What this does NOT cover: BED-02 wires no production routes (out of scope
per REQUIREMENTS.md § Scope) and this endpoint never touches a database —
`compute_guardrail_summary` here runs over in-memory `ProgramGuardrail`
instances built directly in Python, not rows fetched from Postgres. NFR-002's
2s budget is an end-to-end, DB-backed figure (real query + network + JSON
serialization) that cannot be verified until a consumer story (OVW/PGD/SHP)
wires this contract to a real endpoint. This file only proves the shared
layer itself — dependency resolution, range validation, pagination clamping,
and the compute function's iteration — does not eat into that budget.

DB-free by choice, not by default: PLAN.md's Test Strategy row for this file
describes seeding via BED-01's `tests/conftest.py` `migrated_db`/`test_session`
fixtures. Those fixtures require a live, migrated Postgres test database;
`tests/test_migrations.py` currently fails in this sandbox with a Postgres
auth error (`password authentication failed for user "postgres"` —
BED-01 carry-forward AF-06-carry), so a DB-dependent version of this test
would not be runnable here. This version constructs representative
`ProgramGuardrail` rows in-memory instead — sufficient for TC-18's actual
subject under test (the shared contract's own overhead), and it stays
runnable regardless of local Postgres availability.

Threshold choice: the assertion uses NFR-002's literal 2000ms budget
(`P95_BUDGET_SECONDS`), exactly as TC-18's own `expected_results` states it,
rather than a tightened internal figure. The workload under test is pure
in-process Python (dependency resolution, dict/string building, a bounded
loop over `GUARDRAIL_ROW_COUNT` rows) with no I/O, so real p95 latencies are
expected in the sub-millisecond to low-single-digit-millisecond range even
under a loaded shared CI runner — the 2000ms budget carries roughly three
orders of magnitude of headroom over that, so ordinary scheduler jitter
cannot false-fail this test. Tightening the threshold (e.g. to 50ms) was
deliberately avoided: it would silently assert a made-up internal SLA this
story never specified, instead of the one NFR-002 actually states. What this
test can still catch is a genuine regression class — e.g. an accidental
unbounded loop or blocking call introduced into `validate_range`,
`get_offset_limit`, or `compute_guardrail_summary` — not a real end-to-end
timing regression, which only a DB-backed consumer-story test can catch.
"""

import itertools
import math
import time

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_offset_limit, range_to_start, validate_range
from app.models.governance import ProgramGuardrail
from app.services import compute_guardrail_summary

WARMUP_REQUESTS = 5
MEASURED_REQUESTS = 50
RANGE_VALUES_CYCLED = ["7d", "30d", "90d"]
P95_BUDGET_SECONDS = 2.0  # NFR-002 / TC-18 expected_results: "p95 latency < 2000 ms"

# Representative governance row volume ("seeded with representative rollup/
# governance row counts" per TC-18 preconditions) — mixed statuses so
# compute_guardrail_summary does real iteration/branching work, not a
# degenerate all-one-status pass.
GUARDRAIL_ROW_COUNT = 30
_STATUS_CYCLE = ("Enforced", "Warning", "NotImplemented")
GUARDRAIL_ROWS = [
    ProgramGuardrail(
        id=f"guardrail-{i}",
        program_id="program-1",
        name=f"guardrail-{i}",
        status=_STATUS_CYCLE[i % len(_STATUS_CYCLE)],
        document_ref=None,
        display_order=i,
    )
    for i in range(GUARDRAIL_ROW_COUNT)
]

app = FastAPI()


# Composed exactly per TC-18 preconditions: Depends(validate_range) +
# pagination helper + a services derived-value call. Throwaway test route,
# never wired into production routers (BED-02 is out of scope for that —
# see app/main.py for the real router assembly), mirroring the pattern
# established by test_range_validation.py / test_pagination.py.
@app.get("/test-perf")
def _perf_route(
    range: str = Depends(validate_range),
    paged: tuple[int, int] = Depends(get_offset_limit),
) -> dict:
    offset, limit = paged
    start = range_to_start(range)
    summary = compute_guardrail_summary(GUARDRAIL_ROWS)
    return {
        "range": range,
        "offset": offset,
        "limit": limit,
        "start": start.isoformat(),
        **summary,
    }


client = TestClient(app)


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Nearest-rank percentile over an already-sorted list.

    index = ceil(pct * N) - 1 — the standard nearest-rank method,
    deterministic and dependency-free (no numpy/statistics.quantiles
    interpolation-method ambiguity to document).
    """
    n = len(sorted_values)
    rank = math.ceil(pct * n)
    return sorted_values[rank - 1]


# BED-02-TC-18 (NFR-002): 5 unmeasured warmup requests, then 50 measured
# sequential requests cycling range=7d/30d/90d; p95 latency must stay under
# the NFR-002 budget. See module docstring for what this test does and does
# not prove, and for the threshold justification.
def test_shared_contract_p95_latency_under_nfr_budget() -> None:
    range_cycle = itertools.cycle(RANGE_VALUES_CYCLED)

    for _ in range(WARMUP_REQUESTS):
        resp = client.get("/test-perf", params={"range": next(range_cycle)})
        assert resp.status_code == 200

    latencies: list[float] = []
    for _ in range(MEASURED_REQUESTS):
        range_value = next(range_cycle)
        started = time.perf_counter()
        resp = client.get("/test-perf", params={"range": range_value})
        elapsed = time.perf_counter() - started
        assert resp.status_code == 200
        latencies.append(elapsed)

    latencies.sort()
    p95 = _percentile(latencies, 0.95)

    assert p95 < P95_BUDGET_SECONDS, (
        f"p95 latency {p95 * 1000:.2f}ms exceeded the NFR-002 budget of "
        f"{P95_BUDGET_SECONDS * 1000:.0f}ms across {MEASURED_REQUESTS} "
        "measured requests (shared-layer overhead only — see module "
        "docstring)."
    )
