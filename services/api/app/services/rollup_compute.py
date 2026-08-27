"""Rollup-group derived-value computations (org-level aggregates).

Pure, DB-session-free functions per D-02 (`docs/features/BED-02/DECISIONS.md`):
every function here takes an already-fetched ORM model instance (or raw
totals) as input and returns a `dict` merging the raw counts with the
computed field(s) — never the raw counts alone. Query construction stays
with the router/persistence layer; this module only computes.

Owns the rollup group only (adoption %, period delta, average) per D-03 —
the governance-group `compute_guardrail_summary` lives in
`app.services.guardrail_compute`.
"""

from app.models.rollup import OrgSummaryRollup


def compute_adoption_percent(rollup: OrgSummaryRollup) -> dict:
    """Compute the org-wide AI adoption percentage from a rollup row.

    Formula: adoption_percent = programs_using_ai_count / programs_total * 100

    `adoption_percent` is `None` when `programs_total == 0` (no programs
    registered yet — matching `compute_period_delta`'s no-baseline
    treatment, not `compute_average`'s `0.0`: "0% adoption" would assert
    every one of zero programs failed to adopt AI, which is a category
    error when there are no programs to have adopted anything).

    Returns a dict merging the raw counts (`programs_using_ai_count`,
    `programs_total`) with the computed `adoption_percent` field.
    """
    if rollup.programs_total == 0:
        adoption_percent = None
    else:
        adoption_percent = rollup.programs_using_ai_count / rollup.programs_total * 100
    return {
        "programs_using_ai_count": rollup.programs_using_ai_count,
        "programs_total": rollup.programs_total,
        "adoption_percent": adoption_percent,
    }


def compute_period_delta(current_total: int | float, prior_total: int | float) -> dict:
    """Compute the percent change between two period totals.

    Formula: delta = (current_total - prior_total) / prior_total * 100

    `delta_percent` is `None` when `prior_total == 0` (no prior baseline to
    compare against — a division-by-zero guard that returned 0 would
    misreport "no change" instead of "no comparison possible").

    Returns a dict merging the raw totals (`current_total`, `prior_total`)
    with the computed `delta_percent` field.
    """
    if prior_total == 0:
        delta_percent = None
    else:
        delta_percent = (current_total - prior_total) / prior_total * 100
    return {
        "current_total": current_total,
        "prior_total": prior_total,
        "delta_percent": delta_percent,
    }


def compute_average(total: int | float, count: int) -> float:
    """Compute the average of `total` over `count` items.

    Formula: average = total / count

    Returns `0.0` when `count == 0` (no items to average over — a
    division-by-zero guard, not a real average).
    """
    if count == 0:
        return 0.0
    return total / count
