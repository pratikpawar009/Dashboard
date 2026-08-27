"""Governance-group derived-value computations (guardrail pass/fail summary).

Pure, DB-session-free functions per D-02 (`docs/features/BED-02/DECISIONS.md`):
this module takes an already-fetched sequence of ORM model instances as input
and returns a `dict` merging the raw counts with the computed field(s) —
never the raw counts alone. Query construction stays with the router/
persistence layer; this module only computes.

Owns the governance group only (guardrail "X/Y passing") per D-03 — the
rollup-group functions (`compute_adoption_percent`, `compute_period_delta`,
`compute_average`) live in `app.services.rollup_compute`.
"""

from collections.abc import Sequence

from app.models.governance import ProgramGuardrail

# D-05: only this status counts toward the numerator; Warning/NotImplemented
# count toward the denominator (total_count) only.
PASSING_STATUS = "Enforced"


def compute_guardrail_summary(guardrails: Sequence[ProgramGuardrail]) -> dict:
    """Compute the "X/Y passing" guardrail summary from a sequence of rows.

    Formula: passing_count = count(status == "Enforced")
             total_count = len(guardrails)
             summary = f"{passing_count}/{total_count} passing"

    Per D-05 (`docs/features/BED-02/DECISIONS.md`), `program_guardrails.status`
    is a 3-value enum (`Enforced|Warning|NotImplemented`); only `"Enforced"`
    counts as passing — `"Warning"` and `"NotImplemented"` count toward
    `total_count` only, never the numerator.

    An empty `guardrails` sequence (a program with no guardrails configured)
    returns `passing_count=0, total_count=0, summary="0/0 passing"` rather
    than a `None`/guarded field: unlike `compute_adoption_percent` (D-07),
    this formula never divides — it is a literal count pair formatted into
    a string, so "0 of 0" is an accurate, displayable statement and there is
    no division-by-zero to guard against.

    Returns a dict merging the raw counts (`passing_count`, `total_count`)
    with the computed `summary` string.
    """
    total_count = len(guardrails)
    passing_count = sum(1 for g in guardrails if g.status == PASSING_STATUS)
    return {
        "passing_count": passing_count,
        "total_count": total_count,
        "summary": f"{passing_count}/{total_count} passing",
    }
