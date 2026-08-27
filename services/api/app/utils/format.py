"""FR-2: backend-only display formatting (AC 6).

`format_number`/`format_duration` are the single formatting layer for M/K and
h/m display strings — TC-13 scans `apps/web/src` to prove no duplicate
frontend formatter exists. Do not add a frontend equivalent; every consumer
renders the string these functions return as-is.

Boundary behaviour is deliberately decided and documented here (there is no
single "correct" answer to most of it, only a consistent one every one of the
13 downstream consumer stories must match):

- Magnitude bucket is chosen from the value the bucket will actually
  *render*, not from the raw unrounded magnitude — the two must never
  disagree. `format_number` rounds the candidate quotient for a bucket
  first; if that rounded quotient reaches 1000 and a larger bucket exists,
  it promotes to that larger bucket and re-renders there instead. This is
  what keeps `999_999 -> "1.0M"` (not the un-abbreviated `"1000.0K"` a
  naive raw-magnitude bucket choice would produce) and `999.6 -> "1.0K"`
  (not the bare `"1000"` a naive bucket choice would produce).
- Below 1,000 (after the promotion check above), the value renders as a
  bare `int(round(value))` with no suffix: `999 -> "999"`, `0 -> "0"`.
- The K/M branches always keep one decimal place, including a trailing
  `.0` (`2000 -> "2.0K"`, not `"2K"`) — one consistent width across every
  rendered value beats stripping it case-by-case.
- The one decimal place is produced by Python's `round(..., 1)` /
  `:.1f`, which rounds (round-half-to-even on the underlying binary
  float), not truncates: `2549 -> "2.5K"` (2.549 rounds to 2.5).
- Negative values keep their sign and bucket on `abs(value)`:
  `-2500 -> "-2.5K"`, `-999950 -> "-1.0M"`.
- M is the largest bucket this contract defines (`docs/requirements/api.md`
  `#api-conventions` specifies M and K only, no B/billions bucket) and this
  function does not add one on its own authority. Promotion out of K stops
  at M — a magnitude whose M-quotient itself rounds to >= 1000.0 (roughly
  magnitude >= 999_950_000, so this range starts just below the 1e9
  boundary and continues unbounded above it) renders as a 4-or-more-digit
  `"<n>.0M"` string, e.g. `999_999_500 -> "1000.0M"`,
  `1_000_000_000 -> "1000.0M"`, `2_500_000_000 -> "2500.0M"`. This is a
  known, open question — not a silent design choice — pending a B-bucket
  decision; flagged back to the task owner rather than resolved here.

- `format_duration` splits `minutes` into hours/remainder via
  `divmod(minutes, 60)`. Both non-zero -> `"{h}h {m}m"`. Exact hours (a
  zero remainder) drop the minutes term entirely -> `"120 -> 2h"`, not
  `"2h 0m"`. Zero hours -> minutes-only, including `0 -> "0m"` (there is
  no bare "0" case for duration; a duration is always minutes- or
  hours-denominated). Negative `minutes` is rejected with `ValueError` —
  Python's `divmod` floors toward negative infinity for a negative
  dividend (e.g. `divmod(-5, 60) == (-1, 55)`), which would silently
  render a negative duration as a *positive* one; a negative duration is
  a caller bug (durations are a non-negative domain quantity), not a
  value this function should coerce or mask.
"""

# (threshold, suffix) pairs, largest bucket first — the order promotion
# walks toward when a smaller bucket's rounded quotient overflows it.
_MAGNITUDE_BUCKETS: list[tuple[int, str]] = [(1_000_000, "M"), (1_000, "K")]


def format_number(value: int | float) -> str:
    """Format a count with an M/K magnitude suffix (AC 6).

    >>> format_number(999)
    '999'
    >>> format_number(2500)
    '2.5K'
    >>> format_number(1_500_000)
    '1.5M'
    >>> format_number(999_999)
    '1.0M'

    Bucket selection accounts for rounding so the suffix and the rendered
    number never disagree — see the module docstring for the full
    promotion rule and boundary-behaviour decisions.
    """
    sign = "-" if value < 0 else ""
    magnitude = abs(value)

    bucket_idx = 0 if magnitude >= 1_000_000 else (1 if magnitude >= 1_000 else -1)
    while True:
        if bucket_idx == -1:
            rendered = int(round(magnitude))
            if rendered < 1_000:
                return f"{sign}{rendered}"
            bucket_idx = len(_MAGNITUDE_BUCKETS) - 1  # promote into the K bucket
            continue
        threshold, suffix = _MAGNITUDE_BUCKETS[bucket_idx]
        quotient = round(magnitude / threshold, 1)
        if quotient < 1000 or bucket_idx == 0:
            return f"{sign}{quotient:.1f}{suffix}"
        bucket_idx -= 1  # promote to the next larger bucket (K -> M)


def format_duration(minutes: int) -> str:
    """Format a minute count with an h/m suffix (AC 6).

    >>> format_duration(45)
    '45m'
    >>> format_duration(120)
    '2h'
    >>> format_duration(125)
    '2h 5m'
    >>> format_duration(0)
    '0m'

    Raises ValueError for a negative `minutes` — see the module docstring.
    """
    if minutes < 0:
        raise ValueError(f"format_duration: minutes must be non-negative, got {minutes}")
    hours, remaining_minutes = divmod(minutes, 60)
    if hours > 0 and remaining_minutes > 0:
        return f"{hours}h {remaining_minutes}m"
    if hours > 0:
        return f"{hours}h"
    return f"{remaining_minutes}m"
