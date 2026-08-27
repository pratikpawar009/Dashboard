"""Unit tests for app/services/rollup_compute.py and app/services/guardrail_compute.py
— BED-02-TC-09, TC-10, TC-17.

Per D-02 (`docs/features/BED-02/DECISIONS.md`), every derived-value function
is DB-session-free: it takes an already-fetched ORM row (or sequence of rows)
and returns a dict merging the raw counts with the computed field — so these
tests build unattached `OrgSummaryRollup`/`ProgramGuardrail` instances
directly (no session, no flush) and never import `migrated_db`/`test_session`
from conftest.py. No Postgres connection is required to run this file.
"""

from app.models.governance import ProgramGuardrail
from app.models.rollup import OrgSummaryRollup
from app.services.guardrail_compute import compute_guardrail_summary
from app.services.rollup_compute import (
    compute_adoption_percent,
    compute_average,
    compute_period_delta,
)

# ---------------------------------------------------------------------------
# BED-02-TC-09 (AC-5): adoption_percent computed server-side, raw counts
# alone are never the sole payload.
# ---------------------------------------------------------------------------


def test_compute_adoption_percent_returns_correct_value() -> None:
    rollup = OrgSummaryRollup(programs_using_ai_count=6, programs_total=8)
    result = compute_adoption_percent(rollup)
    assert result["adoption_percent"] == 75.0


def test_compute_adoption_percent_merges_computed_field_with_raw_counts() -> None:
    """D-02: the payload is a merge, not raw counts alone — TC-09 requires the
    computed field to be present, not just derivable by the caller."""
    rollup = OrgSummaryRollup(programs_using_ai_count=6, programs_total=8)
    result = compute_adoption_percent(rollup)
    assert result["programs_using_ai_count"] == 6
    assert result["programs_total"] == 8
    assert "adoption_percent" in result
    assert set(result.keys()) == {"programs_using_ai_count", "programs_total", "adoption_percent"}


# D-07 regression: programs_total == 0 must return None, not raise
# ZeroDivisionError and not return 0.0 (that would misreport "0% adoption").
def test_compute_adoption_percent_none_when_programs_total_zero() -> None:
    rollup = OrgSummaryRollup(programs_using_ai_count=0, programs_total=0)
    result = compute_adoption_percent(rollup)
    assert result["adoption_percent"] is None


# ---------------------------------------------------------------------------
# BED-02-TC-10 (AC-5): "X/Y passing" guardrail summary computed server-side.
# ---------------------------------------------------------------------------


def test_compute_guardrail_summary_returns_expected_string() -> None:
    guardrails = [ProgramGuardrail(status="Enforced") for _ in range(4)] + [
        ProgramGuardrail(status="Warning") for _ in range(2)
    ]
    result = compute_guardrail_summary(guardrails)
    assert result["summary"] == "4/6 passing"
    assert result["passing_count"] == 4
    assert result["total_count"] == 6


# D-05: only status == "Enforced" counts toward the numerator; Warning and
# NotImplemented count toward the denominator only. Assert all three enum
# values explicitly so a future change to the mapping breaks this test.
def test_compute_guardrail_summary_only_enforced_counts_as_passing() -> None:
    guardrails = [
        ProgramGuardrail(status="Enforced"),
        ProgramGuardrail(status="Warning"),
        ProgramGuardrail(status="NotImplemented"),
    ]
    result = compute_guardrail_summary(guardrails)
    assert result["passing_count"] == 1
    assert result["total_count"] == 3
    assert result["summary"] == "1/3 passing"


# D-08: empty sequence returns a literal "0/0 passing" — no None, unlike
# D-07's null treatment, because no division occurs (no denominator to guard).
def test_compute_guardrail_summary_empty_sequence_returns_zero_over_zero() -> None:
    result = compute_guardrail_summary([])
    assert result["passing_count"] == 0
    assert result["total_count"] == 0
    assert result["summary"] == "0/0 passing"


# ---------------------------------------------------------------------------
# compute_period_delta — delta_percent None when prior_total == 0.
# ---------------------------------------------------------------------------


def test_compute_period_delta_computes_percent_change() -> None:
    result = compute_period_delta(current_total=150, prior_total=100)
    assert result["delta_percent"] == 50.0


def test_compute_period_delta_none_when_prior_total_zero() -> None:
    result = compute_period_delta(current_total=150, prior_total=0)
    assert result["delta_percent"] is None


# ---------------------------------------------------------------------------
# compute_average — bare float (not a dict) per api.md contract; 0.0 on
# count == 0.
# ---------------------------------------------------------------------------


def test_compute_average_computes_value_and_returns_bare_float() -> None:
    result = compute_average(total=30, count=4)
    assert result == 7.5
    assert isinstance(result, float)
    assert not isinstance(result, dict)


def test_compute_average_zero_when_count_zero() -> None:
    result = compute_average(total=30, count=0)
    assert result == 0.0


# ---------------------------------------------------------------------------
# BED-02-TC-17 (FR-4): every derived-value function's docstring states its
# aggregation formula, so downstream consumer stories don't have to
# reverse-engineer the math.
#
# Balance struck: matching one exact prose sentence would break on any
# harmless rewording of the docstring; asserting merely that __doc__ is
# non-empty tests nothing (a one-line description would still pass). Instead
# each check asserts the formula's *substance* — the operand names that must
# appear (the fields the formula actually reads) plus the operator character
# that expresses the aggregation ("=" for the assignment, "/" for the
# division each formula performs, or the literal word this function
# formats instead of dividing) — so the docstring can be reworded freely as
# long as it keeps naming what the function actually computes from.
# ---------------------------------------------------------------------------


def _assert_formula_docstring(fn: object, operands: list[str]) -> None:
    doc = getattr(fn, "__doc__", None) or ""
    assert doc.strip(), f"{fn!r} has no docstring"
    assert "=" in doc, f"{fn!r} docstring has no formula ('=') expression"
    for operand in operands:
        assert operand in doc, f"{fn!r} docstring does not name operand {operand!r}"


def test_compute_adoption_percent_docstring_states_formula() -> None:
    _assert_formula_docstring(
        compute_adoption_percent,
        ["adoption_percent", "programs_using_ai_count", "programs_total", "/"],
    )


def test_compute_period_delta_docstring_states_formula() -> None:
    _assert_formula_docstring(compute_period_delta, ["delta", "current_total", "prior_total", "/"])


def test_compute_average_docstring_states_formula() -> None:
    _assert_formula_docstring(compute_average, ["average", "total", "count", "/"])


def test_compute_guardrail_summary_docstring_states_formula() -> None:
    _assert_formula_docstring(
        compute_guardrail_summary, ["passing_count", "total_count", "summary", "passing"]
    )
