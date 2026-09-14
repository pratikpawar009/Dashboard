"""Observability contract for the artifacts write path (ING-03 T-12 /
F-18; ING-03 FR-5).

Traces:

- **FR-5 (observability, single event per write)** -- the ingest
  service MUST emit exactly one INFO record per completed write, and
  the record's `.msg` MUST be the string literal
  `"ingest_artifacts_write"`. A silent copy-paste of ING-02's
  `"ingest_write_completed"` at write time (or drift on
  `_LOG_EVENT_NAME`) would leave dashboards blind on the artifacts
  branch -- the metric name they aggregate on wouldn't exist yet.

- **F-15 orthogonality** -- F-15 (`test_ingest_artifacts_pii_logging.py`)
  owns *what fields* are allowed in the payload. This file owns *what
  the event is called*, and that it fires exactly once per write, and
  that it never accidentally reuses ING-02's event name (which would
  merge two structurally-different payload shapes under one dashboard
  key).

Scope: drives the emitter directly (`log_ingest_artifacts_write`) -- no
HTTP, no DB. F-19 (perf) will exercise the full path against a live DB.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from app.services.ingest_artifacts import (
    _LOG_EVENT_NAME,
    log_ingest_artifacts_write,
)

_ACTIVITY_EVENT_NAME = "ingest_write_completed"  # ING-02's event -- must NOT be reused


class _RecordCapturingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _isolated_artifacts_logger() -> Iterator[logging.Logger]:
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


def test_event_name_constant_is_ingest_artifacts_write_literal() -> None:
    """FR-5: the module-level constant that dashboards will aggregate
    on is the string literal `"ingest_artifacts_write"`. Snapshotted as
    a literal (not re-import) so a rename to `_LOG_EVENT_NAME` here
    without updating dashboards fails this test loudly."""
    assert _LOG_EVENT_NAME == "ingest_artifacts_write"


def test_event_name_does_not_collide_with_activity_ingest_event_name() -> None:
    """FR-5 / audit trail: the artifacts write event MUST NOT reuse
    ING-02's `"ingest_write_completed"`. Reuse would merge two
    structurally different payload shapes under one dashboard key."""
    assert _LOG_EVENT_NAME != _ACTIVITY_EVENT_NAME


def test_write_emits_exactly_one_info_record_with_expected_msg(
    artifacts_logger_records: list[logging.LogRecord],
) -> None:
    """FR-5: one call to `log_ingest_artifacts_write` produces exactly
    one INFO record whose `.msg` is the pinned event name."""
    log_ingest_artifacts_write(
        program_id="prog-t12",
        token_label="tok-t12",
        types_written=["prd"],
    )

    assert len(artifacts_logger_records) == 1
    record = artifacts_logger_records[0]
    assert record.levelno == logging.INFO
    assert record.msg == "ingest_artifacts_write"
    assert record.getMessage() == "ingest_artifacts_write"


def test_multiple_writes_emit_one_record_each(
    artifacts_logger_records: list[logging.LogRecord],
) -> None:
    """FR-5: N writes emit N records, and every record uses the same
    pinned event name. Guards against a batching/coalescing regression
    that would silently drop write events under load."""
    for i in range(3):
        log_ingest_artifacts_write(
            program_id=f"prog-t12-{i}",
            token_label="tok-t12",
            types_written=["prd"],
        )

    assert len(artifacts_logger_records) == 3
    assert all(r.msg == "ingest_artifacts_write" for r in artifacts_logger_records)
