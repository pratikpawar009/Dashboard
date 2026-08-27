"""Unit tests for app/utils/format.py — BED-02-TC-11..13.

app/utils/format.py's module docstring (see D-09, docs/features/BED-02/DECISIONS.md)
is the authoritative boundary contract for format_number/format_duration. These
tests assert that documented contract, including the promotion-on-rounding
regression that D-09 records: bucket selection must be chosen from the value as
*rendered* (rounded), not from the raw unrounded magnitude, or the suffix and the
number it prefixes can disagree (e.g. the old "1000.0K" defect).

No B/billions bucket exists yet (AF-04, open product question) — deliberately not
asserted here in either direction; asserting today's unbounded-M output would lock
in an unresolved question.
"""

import re
from pathlib import Path

import pytest

from app.utils.format import format_duration, format_number

# ---------------------------------------------------------------------------
# BED-02-TC-11 — format_number magnitude boundaries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (999, "999"),
        (1000, "1.0K"),
        (2000, "2.0K"),
        (2500, "2.5K"),
        # round-half-to-even on the underlying binary float: 2.549 -> 2.5, not 2.6.
        (2549, "2.5K"),
        (1000000, "1.0M"),
        (1500000, "1.5M"),
        (0, "0"),
        (-2500, "-2.5K"),
        (-999999, "-1.0M"),
    ],
)
def test_format_number_boundaries(value: int | float, expected: str) -> None:
    assert format_number(value) == expected


# Regression tests for D-09's correction: bucket selection must follow the
# *rounded* quotient, not the raw magnitude — these three values are exactly
# where the old implementation disagreed with itself ("1000.0K" instead of
# promoting to "1.0M"). Do not weaken or remove these if format.py changes;
# they are what catches that class of defect coming back.
def test_format_number_promotes_on_rounding_regression_fractional_input() -> None:
    """Regression for D-09: 999.6 rounds to 1000 in the sub-K path and must
    promote to the K bucket rather than rendering the bare int '1000'."""
    assert format_number(999.6) == "1.0K"


def test_format_number_promotes_on_rounding_regression_just_under_1m() -> None:
    """Regression for D-09: 999950's K-quotient (999.95) rounds to 1000.0,
    which must promote to M ('1.0M'), not render as the un-abbreviated
    '1000.0K' the old bucket-from-raw-magnitude logic produced."""
    assert format_number(999950) == "1.0M"


def test_format_number_promotes_on_rounding_regression_original_defect_value() -> None:
    """Regression for D-09: format_number(999_999) is the exact value the
    original defect was reported against — it returned '1000.0K' with plain
    integer input instead of promoting to '1.0M'."""
    assert format_number(999999) == "1.0M"


# ---------------------------------------------------------------------------
# BED-02-TC-12 — format_duration boundaries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [
        (0, "0m"),
        (45, "45m"),
        (60, "1h"),
        (120, "2h"),
        (125, "2h 5m"),
    ],
)
def test_format_duration_boundaries(minutes: int, expected: str) -> None:
    assert format_duration(minutes) == expected


def test_format_duration_negative_raises_value_error() -> None:
    """Per D-09: divmod floors toward negative infinity for a negative
    dividend, which would silently render a negative duration as a positive
    one. format_duration rejects negative input instead of coercing it."""
    with pytest.raises(ValueError):
        format_duration(-5)


# ---------------------------------------------------------------------------
# BED-02-TC-13 — no duplicate frontend M/K or h/m formatting utility (FR-2)
# ---------------------------------------------------------------------------

# Forbidden identifiers from the test case's test_data.forbidden_patterns,
# plus generic K/M-suffix and h/m-suffix construction idioms a rewritten
# frontend formatter might use under a different name. Matched as whole
# identifiers (word boundaries) so this does not false-positive on unrelated
# code that merely contains the substrings "K" or "format" (e.g. "Ok",
# "reformat", "formatCurrency", "formData").
_FORBIDDEN_PATTERNS = [
    "formatNumber",
    "formatMK",
    "formatDuration",
    "formatHoursMinutes",
]

# Source extensions a frontend formatting utility could plausibly live in.
_SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx"}


def _iter_web_source_files() -> list[Path]:
    web_src = Path(__file__).resolve().parents[4] / "apps" / "web" / "src"
    if not web_src.is_dir():
        return []
    return [p for p in web_src.rglob("*") if p.is_file() and p.suffix in _SOURCE_SUFFIXES]


def test_no_duplicate_frontend_formatter_exists() -> None:
    web_src = Path(__file__).resolve().parents[4] / "apps" / "web" / "src"
    files = _iter_web_source_files()

    # apps/web/src exists and is a real (non-empty) source tree in this repo
    # (layout.tsx, page.tsx, etc.) — assert that precondition explicitly so
    # this test fails loudly, rather than vacuously passing, if the frontend
    # tree is ever removed or the path convention changes.
    assert web_src.is_dir(), f"expected apps/web source tree at {web_src}"
    assert files, f"expected at least one .ts/.tsx source file under {web_src}"

    forbidden_re = re.compile(r"\b(" + "|".join(re.escape(p) for p in _FORBIDDEN_PATTERNS) + r")\b")
    # Generic K/M or h/m suffix string-construction idiom: a template literal
    # or concatenation ending the value in a bare "K"/"M" or "h"/"m" suffix
    # character, e.g. `${n}K` or `hours + "h"`. Deliberately narrow (requires
    # the suffix immediately after an interpolation/number) so it does not
    # match ordinary prose or unrelated identifiers containing K/M/h/m.
    suffix_re = re.compile(r"\$\{[^}]+\}\s*[\"'`]?\s*[KMhm]\b")

    offenders: list[str] = []
    for f in files:
        text = f.read_text(encoding="utf-8", errors="ignore")
        if forbidden_re.search(text):
            offenders.append(f"{f}: forbidden identifier match")
        if suffix_re.search(text):
            offenders.append(f"{f}: K/M or h/m suffix construction match")

    assert not offenders, "duplicate frontend formatting utility suspected:\n" + "\n".join(
        offenders
    )
