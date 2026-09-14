"""PII allowlist enforcement for the `ingest_artifacts_write` structured
log event (ING-03 T-09 / F-15; ING-03 FR-5).

Mirrors `tests/unit/test_ingest_write_completed_pii.py` (ING-02 T-11):
attach a `_RecordCapturingHandler` to the real, named
`app.services.ingest_artifacts` logger and force-reset
`.disabled=False` / `.propagate=False` for the test's duration
(`migrations/env.py`'s `fileConfig(disable_existing_loggers=True)`
permanently disables loggers once `test_migrations.py` runs in the same
session; `caplog` is blind to that).

Diff-shape assertions (allowlist, not denylist): the captured record's
`extra` payload key set MUST equal `_LOG_FIELD_ALLOWLIST` EXACTLY. Any
drift on either side -- the service widens the allowlist, or a test
forgets to update this snapshot -- trips a test regardless of which
side moves first.

Denylist probes (belt-and-braces): `user_email`, `token_hash`, raw
`counts` values, and `as_of` MUST be absent from every captured record
and every formatted JSON payload.

Scope: drives the emitter directly (`log_ingest_artifacts_write` is a
public helper on `app.services.ingest_artifacts`). The router/HTTP
wire path is out of scope -- F-17 (`test_ingest_route_generic.py`) owns
that; F-19 (perf) exercises the full path against a live DB.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from app.core.logging import JSONFormatter
from app.services.ingest_artifacts import (
    _LOG_EVENT_NAME,
    _LOG_FIELD_ALLOWLIST,
    log_ingest_artifacts_write,
)

_PROGRAM_ID = "prog-pii-ing03"
_TOKEN_LABEL = "zzyzx-artifacts-label-t09"  # unique probe -- must not leak
_JSON_META_FIELDS = frozenset({"timestamp", "level", "logger", "message"})


class _RecordCapturingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _isolated_artifacts_logger() -> Iterator[logging.Logger]:
    """Force-reset the real `app.services.ingest_artifacts` logger's
    `.disabled` / `.propagate` / level for the test's duration, then
    restore. Same disabled-logger trap idiom as ING-02 T-11."""
    logger = logging.getLogger("app.services.ingest_artifacts")
    original_disabled = logger.disabled
    original_propagate = logger.propagate
    original_level = logger.level
    logger.disabled = False
    logger.propagate = False
    logger.setLevel(logging.INFO)
    try:
        yield logger
    finally:
        logger.disabled = original_disabled
        logger.propagate = original_propagate
        logger.setLevel(original_level)


@pytest.fixture
def artifacts_logger_records() -> Iterator[list[logging.LogRecord]]:
    with _isolated_artifacts_logger() as logger:
        handler = _RecordCapturingHandler()
        logger.addHandler(handler)
        try:
            yield handler.records
        finally:
            logger.removeHandler(handler)


def _write_events(records: list[logging.LogRecord]) -> list[logging.LogRecord]:
    return [r for r in records if r.getMessage() == _LOG_EVENT_NAME]


def _formatted_payloads(records: list[logging.LogRecord]) -> list[dict[str, Any]]:
    return [json.loads(JSONFormatter().format(r)) for r in records]


def test_write_record_extra_keys_equal_allowlist_exactly(
    artifacts_logger_records: list[logging.LogRecord],
) -> None:
    """FR-5: every allowlisted field is present on the LogRecord's
    attribute set (via `extra=`), and no non-allowlisted field with a
    known-PII name leaked onto the record."""
    log_ingest_artifacts_write(
        program_id=_PROGRAM_ID,
        token_label=_TOKEN_LABEL,
        types_written=["prd"],
    )

    write_records = _write_events(artifacts_logger_records)
    assert len(write_records) == 1
    record = write_records[0]

    for field in _LOG_FIELD_ALLOWLIST:
        assert hasattr(record, field), (
            f"FR-5 violated: allowlisted field {field!r} missing from "
            f"the ingest_artifacts_write LogRecord"
        )
    for forbidden in ("user_email", "token_hash", "as_of", "counts"):
        assert not hasattr(record, forbidden), (
            f"FR-5 violated: field {forbidden!r} leaked onto the "
            f"ingest_artifacts_write LogRecord"
        )


def test_formatted_json_payload_key_set_within_allowlist_plus_meta(
    artifacts_logger_records: list[logging.LogRecord],
) -> None:
    """FR-5: the SAME allowlist survives `JSONFormatter` -- the
    on-disk / stdout payload carries only the allowlisted keys plus
    `JSONFormatter`'s own meta (`timestamp/level/logger/message`).
    Guards against a formatter-tier field leak the record-level check
    would miss."""
    log_ingest_artifacts_write(
        program_id=_PROGRAM_ID,
        token_label=_TOKEN_LABEL,
        types_written=["prd", "test_case"],
    )
    payloads = _formatted_payloads(_write_events(artifacts_logger_records))
    assert payloads
    allowed = _LOG_FIELD_ALLOWLIST | _JSON_META_FIELDS
    for payload in payloads:
        extras = set(payload) - allowed
        assert not extras, (
            f"FR-5 violated: unexpected keys in JSON log payload: "
            f"{sorted(extras)}"
        )


def test_token_label_and_program_id_appear_but_pii_probes_do_not(
    artifacts_logger_records: list[logging.LogRecord],
) -> None:
    """FR-5 defence-in-depth: the token label is allowlisted (it's a
    non-secret debug identifier per ADR-0006), so it MUST appear; but
    unique probe strings representing `user_email` / `token_hash` MUST
    NOT appear anywhere in the serialised payload."""
    user_email_probe = "sneaky-pii@example.invalid"  # noqa: S105 -- probe
    token_hash_probe = "hash-should-never-appear-t09"  # noqa: S105 -- probe

    log_ingest_artifacts_write(
        program_id=_PROGRAM_ID,
        token_label=_TOKEN_LABEL,
        types_written=["prd"],
    )
    combined = json.dumps(
        _formatted_payloads(_write_events(artifacts_logger_records))
    )
    assert _PROGRAM_ID in combined
    assert _TOKEN_LABEL in combined
    assert user_email_probe not in combined
    assert token_hash_probe not in combined
