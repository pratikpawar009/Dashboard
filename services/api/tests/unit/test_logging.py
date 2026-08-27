"""Unit tests for app/core/logging.py's JSONFormatter — BED-02-TC-15, TC-16.

Pure-unit: no DB, no app boot. Every test drives `JSONFormatter().format()`
directly against a real `logging.LogRecord` obtained from an actual
`logging.Logger` call (never a hand-built dict standing in for one), captured
via a throwaway `logging.Handler` that stores the record without formatting
it — mirroring how `configure_logging()`'s real `StreamHandler` receives
records, minus the stdout write.

Deliberately does NOT call `configure_logging()`: it installs a
`StreamHandler` bound to `sys.stdout` at construction time, and pytest swaps
its capture object between setup and call phases, so a fixture-time
`configure_logging()` + body-time `capsys` read yields zero captured lines.
Formatting through a bare `JSONFormatter()` instance sidesteps that entirely.
Each test also uses its own logger name, disables propagation, and removes
its handler in a `finally` — the root logger is never touched, so nothing
here can leak state into other test files.
"""

from __future__ import annotations

import json
import logging

from app.core.logging import JSONFormatter


class _RecordCapturingHandler(logging.Handler):
    """Stores emitted LogRecord instances verbatim, without formatting them."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _emit(logger_name: str, message: str, *, extra: dict | None = None) -> logging.LogRecord:
    """Log one WARNING through a real, isolated Logger and return its LogRecord."""
    logger = logging.getLogger(logger_name)
    logger.propagate = False
    logger.setLevel(logging.WARNING)
    handler = _RecordCapturingHandler()
    logger.addHandler(handler)
    try:
        logger.warning(message, extra=extra)
    finally:
        logger.removeHandler(handler)
    return handler.records[0]


# BED-02-TC-15 (FR-3) — regression test for the T-04 fix: this test MUST fail
# against a formatter that builds its payload from a fixed key set and never
# reads record.__dict__, and MUST pass now that the extras merge is in place.
def test_regression_fr3_extras_surface_in_json_payload() -> None:
    extra = {"route": "/api/activities", "param": "range", "rejected_value": "60d"}
    record = _emit("test.bed02.logging.extras", "invalid_range", extra=extra)

    payload = json.loads(JSONFormatter().format(record))

    assert payload["route"] == "/api/activities"
    assert payload["param"] == "range"
    assert payload["rejected_value"] == "60d"


# BED-02-TC-16 (FR-3) — the extras merge must not also leak Python's standard
# LogRecord attributes. Asserted against the *actual* attribute set the real,
# captured LogRecord carries (record.__dict__), not a list hand-copied from
# _RESERVED_LOGRECORD_ATTRS — a copied list would only prove the set was
# transcribed twice. Using the live record also catches the drift risk D-04
# accepted deliberately: if a future Python version adds a new LogRecord
# attribute (3.12 added `taskName`) before _RESERVED_LOGRECORD_ATTRS is
# updated, that new name shows up in record.__dict__ and this test fails;
# a test built from a copied list would not.
def test_regression_fr3_reserved_logrecord_attrs_do_not_leak() -> None:
    record = _emit("test.bed02.logging.reserved", "test message")

    intrinsic_names = set(vars(record).keys())
    payload = json.loads(JSONFormatter().format(record))

    first_class_keys = {"timestamp", "level", "logger", "message"}
    # exc_info is a genuine intrinsic LogRecord attribute AND a first-class
    # payload key the formatter deliberately emits when an exception is
    # present; no exception was raised here so it must be absent from both.
    allowed = first_class_keys | {"exc_info"}

    for name in intrinsic_names - allowed:
        assert name not in payload, f"reserved LogRecord attribute {name!r} leaked into payload"

    # Spot-check the specific names TC-16's test_data calls out explicitly.
    for name in ["pathname", "funcName", "args", "msg", "levelno", "process", "thread"]:
        assert name not in payload

    # No exception was logged, so the payload is exactly the four first-class
    # keys — nothing else, reserved or otherwise.
    assert set(payload.keys()) == first_class_keys


# AF-01 — pins current behaviour: an `extra` key colliding with a first-class
# payload key is silently dropped, first-class always wins. Uses `logger` as
# the colliding key rather than FLAGS.md's `message` example: Python's own
# `Logger.makeRecord` special-cases and rejects `extra={"message": ...}` with
# a KeyError before the record is even built (verified against this repo's
# pinned Python), so `message` can never reach the formatter this way.
# `logger`/`level`/`timestamp` are first-class payload keys but are not
# intrinsic LogRecord attribute names, so `extra={"logger": ...}` is accepted
# by the stdlib and is a genuine, reachable collision case.
def test_extra_key_colliding_with_first_class_field_is_silently_dropped() -> None:
    record = _emit(
        "test.bed02.logging.collision", "real message", extra={"logger": "forged-logger-name"}
    )

    payload = json.loads(JSONFormatter().format(record))

    assert payload["logger"] == "test.bed02.logging.collision"
    assert payload["logger"] != "forged-logger-name"


# AF-02 — an unserialisable `extra` value degrades to its str() via
# `json.dumps(..., default=str)` rather than raising, so a careless call site
# can't crash the request path it's observing.
def test_unserialisable_extra_value_degrades_to_str_instead_of_raising() -> None:
    class _Unserialisable:
        def __repr__(self) -> str:
            return "<Unserialisable obj>"

    record = _emit(
        "test.bed02.logging.unserialisable",
        "has odd extra",
        extra={"weird": _Unserialisable()},
    )

    formatted = JSONFormatter().format(record)  # must not raise
    payload = json.loads(formatted)

    assert payload["weird"] == "<Unserialisable obj>"
