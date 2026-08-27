"""FR-1: range validation as a Depends() dependency — not middleware, not a
per-router inline check.

validate_range() is the single entry point every ranged endpoint wires in via
Depends(); it rejects any value outside {7d, 30d, 90d} with
HTTPException(400, "invalid_range") routed through the existing
error_body()/register_exception_handlers() machinery (app/core/errors.py),
rather than a declarative Query() constraint that would fall through to
FastAPI's default 422 (AC 2). Every consumer of this dependency therefore
returns a byte-identical 400 body (AC 7).
"""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Query, Request

logger = logging.getLogger(__name__)

ALLOWED_RANGES = frozenset({"7d", "30d", "90d"})

_RANGE_DAYS: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90}

# .claude/rules/security-baseline.md forbids logging raw user-supplied content
# at any level: an unbounded `rejected_value` lets `?range=<huge string>`
# inflate log volume without limit, and relies on JSONFormatter's incidental
# json.dumps escaping (a different module's implementation detail, not a
# guarantee made here) to contain a newline-injection attempt. 64 chars keeps
# a genuine typo (e.g. "7days") fully legible while bounding a hostile value
# to a small, fixed cost per log line.
_MAX_LOGGED_VALUE_LEN = 64


def _capped_rejected_value(value: str) -> str:
    """Cap a rejected `range` value before it goes into a log `extra` dict.

    Truncation is marked explicitly (`...<truncated>`) rather than a bare
    slice, so a cut value is never mistaken for a genuinely short one.
    """
    if len(value) <= _MAX_LOGGED_VALUE_LEN:
        return value
    return f"{value[:_MAX_LOGGED_VALUE_LEN]}...<truncated>"


def validate_range(request: Request, range: str = Query(...)) -> str:
    """Validate the `range` query param against {7d, 30d, 90d}.

    The membership check runs explicitly in the function body, ahead of any
    Pydantic-driven coercion of the same parameter, so an invalid value
    always raises HTTPException(400, "invalid_range") instead of a 422.
    """
    if range not in ALLOWED_RANGES:
        logger.warning(
            "invalid_range",
            extra={
                "route": request.url.path,
                "param": "range",
                "rejected_value": _capped_rejected_value(range),
            },
        )
        raise HTTPException(status_code=400, detail="invalid_range")
    return range


def range_to_start(range_value: str, now: datetime | None = None) -> datetime:
    """Resolve a validated range value to its window start timestamp.

    Returns a timezone-aware UTC datetime — every BED-01 timestamp column
    this scopes a query against is `DateTime(timezone=True)`, so a naive
    value would fail (or silently drift) against them.

    `now` is injectable so callers (and tests pinning a frozen clock) control
    the reference time instead of this unconditionally calling
    datetime.now(UTC). A caller-supplied `now` must itself be timezone-aware
    UTC; a naive `now` is rejected rather than silently assumed to be UTC,
    since that assumption could be wrong and would fail silently.
    """
    if now is not None and now.tzinfo is None:
        raise ValueError("range_to_start: now must be timezone-aware (UTC), got a naive datetime")
    reference = now if now is not None else datetime.now(UTC)
    return reference - timedelta(days=_RANGE_DAYS[range_value])
