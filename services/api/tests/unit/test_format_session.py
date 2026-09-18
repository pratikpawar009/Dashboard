"""Unit tests for app/utils/format.py's SHP-03 formatters — SHP-03-TC-01/TC-02.

`format_session_duration`/`format_session_tokens` are the two new formatters T-01
added for the personal-usage sessions panel (DESIGN.md § Value formats). They are
siblings of `format_number`/`format_duration`, not a change to them — see the
D-01/D-02 seal test at the bottom of this file, which pins that those two sealed
cross-story contracts (SHP-02/PGD-04/PGD-05) still produce their original values.

Two boundary behaviours are deliberately pinned here per FLAGS.md § F-02 as
design-source consequences, not bugs:

- `format_session_tokens(999_999) == "1000K"` — the K tier has no promote-to-M
  rule, unlike the sibling `format_number()`, which would promote this same
  value to `"1.0M"`.
- `format_session_tokens(2_500) == "2K"` — Python's `round()` is banker's
  rounding (half-to-even), so exact `.5` multiples of 1000 differ from the JS
  mockup generator's `Math.round`, which is half-up (would give `"3K"`).

Pinning both means a future edit that changes either fails loudly instead of
silently.
"""

import pytest

from app.utils.format import (
    format_duration,
    format_number,
    format_session_duration,
    format_session_tokens,
)

# ---------------------------------------------------------------------------
# SHP-03-TC-01 — format_session_duration boundaries (0m, exact hours, zero-
# padded minutes)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("duration_seconds", "expected"),
    [
        (0, "0h 00m"),
        (1800, "0h 30m"),
        (2700, "0h 45m"),
        (3600, "1h 00m"),
        (7620, "2h 07m"),
    ],
)
def test_format_session_duration_boundaries(duration_seconds: int, expected: str) -> None:
    assert format_session_duration(duration_seconds) == expected


# ---------------------------------------------------------------------------
# SHP-03-TC-02 — format_session_tokens boundaries (sub-1K, 1K, 1M)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (0, "0K"),
        (500, "0K"),
        (850, "1K"),
        (1000, "1K"),
        (840000, "840K"),
        (1000000, "1.0M"),
        (1200000, "1.2M"),
        (15300000, "15.3M"),
    ],
)
def test_format_session_tokens_boundaries(tokens: int, expected: str) -> None:
    assert format_session_tokens(tokens) == expected


def test_format_session_tokens_no_promote_to_m_below_1m_regression() -> None:
    """FLAGS.md § F-02 point 1: 999_999 is one token below the 1M threshold, so
    it stays in the K tier and renders "1000K" — unlike format_number(), which
    would promote the same magnitude to "1.0M". This is a design-source
    consequence (the mockup generator's K branch never promotes), not a bug;
    do not "fix" this to match format_number()'s promotion behaviour."""
    assert format_session_tokens(999_999) == "1000K"


def test_format_session_tokens_banker_rounding_regression() -> None:
    """FLAGS.md § F-02 point 2: Python's round() is banker's rounding
    (half-to-even), so the exact .5-multiple 2500 tokens (2.5K) rounds down to
    "2K", not up to "3K" as JS's half-up Math.round would produce. Pinned so a
    future switch to a half-up rounding helper fails loudly."""
    assert format_session_tokens(2_500) == "2K"


# ---------------------------------------------------------------------------
# D-01/D-02 seal — format_number()/format_duration() are sealed cross-story
# contracts (SHP-02/PGD-04/PGD-05); the new sibling formatters above must not
# have altered their original behaviour.
# ---------------------------------------------------------------------------


def test_format_number_seal_unchanged() -> None:
    assert format_number(840_000) == "840.0K"


def test_format_duration_seal_unchanged() -> None:
    assert format_duration(120) == "2h"
