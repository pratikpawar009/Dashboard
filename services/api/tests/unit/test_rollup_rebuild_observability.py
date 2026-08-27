"""`rollup_rebuild_completed` observability event (BED-03-TC-13, TC-14, TC-17).

Covers:
- TC-13: `rebuild_program_rollups` emits exactly one `rollup_rebuild_completed`
  line with `scope='program'`, `program_id`, `duration_ms` (int), and
  `event_count` matching the seeded row count.
- TC-14: `rebuild_org_rollups` emits exactly one line (not one per org-scoped
  table) with `scope='org'`. Per `rollup_rebuild.py`'s actual `extra={...}`
  construction (`rebuild_org_rollups`, no `program_id` key at all), the field
  is *omitted*, never emitted as `null` — asserted against that real
  behaviour rather than the task note's "null or absent" either/or.
- TC-17: end-to-end via the real production logging pipeline —
  `configure_logging()` called exactly as `app/main.py` calls it at startup,
  real `stdout` captured via `capsys`, asserting a genuinely parseable JSON
  line per call. This is the test that proves the `extra={}` values survive
  the real `JSONFormatter` (BED-02's passthrough seam), not a mock.

TC-13/TC-14 capture logs via a handler attached directly to
`rollup_rebuild.py`'s own module logger (`app.services.rollup_rebuild`) —
mirroring `tests/unit/test_logging.py`'s `_RecordCapturingHandler` idiom, but
against a real call's `LogRecord` rather than a hand-built one. Every test
restores the logger's/root logger's original level, propagation, and handlers
in a `finally` block so nothing leaks into sibling test files running in the
same session (`.claude/rules/context-economy.md`-adjacent hygiene, and this
task's explicit teardown requirement).

Against the disposable test database via `migrated_db`/`test_session`
(`tests/conftest.py`), matching `tests/unit/test_rollup_rebuild_program.py`'s
established live-DB seeding pattern.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

import app.models as models
from app.core.logging import JSONFormatter, configure_logging
from app.services import rollup_rebuild as rollup_rebuild_module
from app.services.rollup_rebuild import rebuild_org_rollups, rebuild_program_rollups
from tests.conftest import AlembicRunner


def _usage_event_row(**overrides: Any) -> dict[str, Any]:
    """One `usage_events` row dict with required-field defaults, matching
    `tests/unit/test_rollup_rebuild_program.py::_usage_event_row`'s shape.
    """
    row: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "program_id": "prog-log-1",
        "ts": datetime.now(UTC),
        "cmd_ts": datetime.now(UTC),
        "user": "test-user",
        "session_id": "sess-abc",
        "command": "test-command",
        "duration_seconds": 1,
        "outcome": "success",
        "total": 100,
    }
    row.update(overrides)
    return row


async def _insert_events(test_session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    await test_session.execute(sa.insert(models.UsageEvent), rows)
    await test_session.commit()


class _RecordCapturingHandler(logging.Handler):
    """Stores emitted LogRecord instances verbatim, without formatting them."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _capture_module_logs() -> Iterator[_RecordCapturingHandler]:
    """Attach a capturing handler directly to rollup_rebuild.py's module
    logger for the duration of the `with` block.

    Forces the logger's own level to INFO, disables propagation, and forces
    `disabled = False` so a `rollup_rebuild_completed` call is captured
    regardless of root logger configuration in the current test session.

    The `disabled` reset is required, not defensive: `migrated_db`'s
    `alembic upgrade`/`downgrade` calls run `migrations/env.py:19`'s
    `fileConfig(config.config_file_name)` on every invocation, and
    `logging.config.fileConfig` defaults to `disable_existing_loggers=True` —
    which sets `.disabled = True` on every already-instantiated logger not
    named in `alembic.ini`'s `[loggers]` section (`root`, `sqlalchemy.engine`,
    `alembic` only). `app.services.rollup_rebuild`'s module logger already
    exists by the time `migrated_db.upgrade("head")` runs (import happens at
    test collection), so it gets silently disabled before every test body
    runs — without this reset, `logger.info(...)` is a no-op and zero
    records are ever captured, regardless of level/propagate. Original
    level/propagate/disabled are restored on exit so no state leaks into
    sibling test files.
    """
    target = rollup_rebuild_module.logger
    original_level = target.level
    original_propagate = target.propagate
    original_disabled = target.disabled
    handler = _RecordCapturingHandler()
    target.addHandler(handler)
    target.setLevel(logging.INFO)
    target.propagate = False
    target.disabled = False
    try:
        yield handler
    finally:
        target.removeHandler(handler)
        target.setLevel(original_level)
        target.propagate = original_propagate
        target.disabled = original_disabled


def _completed_records(handler: _RecordCapturingHandler) -> list[logging.LogRecord]:
    return [r for r in handler.records if r.getMessage() == "rollup_rebuild_completed"]


@pytest.mark.asyncio
async def test_program_scope_emits_exactly_one_completed_log_line(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """BED-03-TC-13: 6 seeded events for prog-log-1 -> exactly one
    `rollup_rebuild_completed` line, `scope='program'`,
    `program_id='prog-log-1'`, `duration_ms` a non-negative int,
    `event_count == 6`, no PII field.
    """
    program_id = "prog-log-1"
    events = [
        _usage_event_row(
            program_id=program_id,
            session_id=f"sess-log-{i}",
            user=f"user-log-{i}",
            command="cmd-log",
            ts=datetime(2026, 1, 1, 10 + i, 0, 0, tzinfo=UTC),
            cmd_ts=datetime(2026, 1, 1, 10 + i, 0, 0, tzinfo=UTC),
        )
        for i in range(6)
    ]
    await _insert_events(test_session, events)

    with _capture_module_logs() as handler:
        result = await rebuild_program_rollups(test_session, program_id)

    completed = _completed_records(handler)
    assert len(completed) == 1, (
        f"expected exactly one rollup_rebuild_completed line, got {len(completed)}"
    )

    payload = json.loads(JSONFormatter().format(completed[0]))
    assert payload["scope"] == "program"
    assert payload["program_id"] == program_id
    assert isinstance(payload["duration_ms"], int)
    assert payload["duration_ms"] >= 0
    assert payload["event_count"] == 6
    assert result.event_count == 6

    for forbidden in ("email", "user_email", "raw_content", "prompt_text"):
        assert forbidden not in payload


@pytest.mark.asyncio
async def test_org_scope_emits_exactly_one_completed_log_line_with_program_id_omitted(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """BED-03-TC-14: 10 seeded events across 2 programs -> exactly one
    `rollup_rebuild_completed` line (not one per org-scoped table),
    `scope='org'`, `program_id` omitted from the payload entirely — matching
    `rebuild_org_rollups`'s actual `extra={...}` construction, which never
    includes a `program_id` key (not even as `None`).
    """
    events = [
        _usage_event_row(
            program_id="prog-log-a" if i < 5 else "prog-log-b",
            session_id=f"sess-log-org-{i}",
            user=f"user-log-org-{i}",
            command="cmd-log-org",
            ts=datetime(2026, 2, 1, 10 + i, 0, 0, tzinfo=UTC),
            cmd_ts=datetime(2026, 2, 1, 10 + i, 0, 0, tzinfo=UTC),
        )
        for i in range(10)
    ]
    await _insert_events(test_session, events)

    with _capture_module_logs() as handler:
        result = await rebuild_org_rollups(test_session)

    completed = _completed_records(handler)
    assert len(completed) == 1, (
        f"expected exactly one rollup_rebuild_completed line, got {len(completed)}"
    )

    payload = json.loads(JSONFormatter().format(completed[0]))
    assert payload["scope"] == "org"
    assert "program_id" not in payload
    assert isinstance(payload["duration_ms"], int)
    assert payload["duration_ms"] >= 0
    assert payload["event_count"] == 10
    assert result.event_count == 10
    assert result.program_id is None


def _save_root_logging_state() -> tuple[list[logging.Handler], int, bool]:
    """Snapshot both the root logger's handlers/level (what `configure_logging()`
    rewires) and rollup_rebuild.py's module logger `.disabled` flag.

    The latter is required for the same reason `_capture_module_logs` resets
    it: `migrated_db`'s alembic upgrade/downgrade runs `fileConfig()`
    (`migrations/env.py:19`) with `disable_existing_loggers=True`, which
    disables `app.services.rollup_rebuild`'s already-instantiated logger
    before this test body runs. `configure_logging()` only replaces the
    *root* logger's handlers/level — it never touches a child logger's own
    `.disabled` flag — so a disabled module logger drops every
    `rollup_rebuild_completed` record before it ever reaches the root
    handler, independent of level/propagate being correct.
    """
    root = logging.getLogger()
    return list(root.handlers), root.level, rollup_rebuild_module.logger.disabled


def _restore_root_logging_state(
    handlers: list[logging.Handler], level: int, module_logger_disabled: bool
) -> None:
    root = logging.getLogger()
    root.handlers = handlers
    root.setLevel(level)
    rollup_rebuild_module.logger.disabled = module_logger_disabled


def _rollup_completed_lines(stdout_text: str) -> list[dict[str, Any]]:
    """Parse captured stdout into the JSON payloads named 'rollup_rebuild_completed'.

    A non-JSON or non-matching line is skipped rather than failing the parse
    outright — other loggers/handlers in the process are free to write their
    own lines to the same stdout stream.
    """
    lines: list[dict[str, Any]] = []
    for raw_line in stdout_text.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if payload.get("message") == "rollup_rebuild_completed":
            lines.append(payload)
    return lines


@pytest.mark.asyncio
async def test_end_to_end_emits_one_well_formed_json_line_per_scope(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """BED-03-TC-17: `configure_logging()` exactly as `app/main.py` calls it
    at startup, real stdout capture, both scopes -> one parseable JSON
    `rollup_rebuild_completed` line each, produced by the real
    `JSONFormatter` passthrough seam end-to-end (not a hand-built LogRecord).

    Root logger handlers/level, plus rollup_rebuild.py's module logger
    `.disabled` flag (see `_save_root_logging_state`'s docstring — alembic's
    `fileConfig()` via `migrated_db` disables it before this test body runs;
    `configure_logging()` alone does not clear that), are saved before
    `configure_logging()` runs and restored in `finally`, so this test's
    logging wiring cannot leak into sibling test files.
    """
    saved_handlers, saved_level, saved_module_disabled = _save_root_logging_state()
    try:
        configure_logging()
        rollup_rebuild_module.logger.disabled = False

        program_id = "prog-obs-1"
        program_events = [
            _usage_event_row(
                program_id=program_id,
                session_id=f"sess-e2e-{i}",
                user=f"user-e2e-{i}",
                command="cmd-e2e",
                ts=datetime(2026, 3, 1, 10 + i, 0, 0, tzinfo=UTC),
                cmd_ts=datetime(2026, 3, 1, 10 + i, 0, 0, tzinfo=UTC),
            )
            for i in range(4)
        ]
        await _insert_events(test_session, program_events)
        capsys.readouterr()  # drop any stdout produced before the call under test
        await rebuild_program_rollups(test_session, program_id)
        program_stdout = capsys.readouterr().out

        # rebuild_org_rollups scans usage_events unfiltered (D-05) — the 4
        # program_events rows above are still present, so the org scope's
        # event_count reflects all 10 rows seeded across both blocks.
        org_events = [
            _usage_event_row(
                program_id="prog-e2e-a" if i < 3 else "prog-e2e-b",
                session_id=f"sess-e2e-org-{i}",
                user=f"user-e2e-org-{i}",
                command="cmd-e2e-org",
                ts=datetime(2026, 3, 2, 10 + i, 0, 0, tzinfo=UTC),
                cmd_ts=datetime(2026, 3, 2, 10 + i, 0, 0, tzinfo=UTC),
            )
            for i in range(6)
        ]
        await _insert_events(test_session, org_events)
        await rebuild_org_rollups(test_session)
        org_stdout = capsys.readouterr().out
    finally:
        _restore_root_logging_state(saved_handlers, saved_level, saved_module_disabled)

    program_lines = _rollup_completed_lines(program_stdout)
    assert len(program_lines) == 1, (
        f"expected exactly one rollup_rebuild_completed line, got {len(program_lines)}"
    )
    program_payload = program_lines[0]
    assert program_payload["scope"] == "program"
    assert program_payload["program_id"] == program_id
    assert isinstance(program_payload["duration_ms"], int)
    assert program_payload["event_count"] == 4

    org_lines = _rollup_completed_lines(org_stdout)
    assert len(org_lines) == 1, (
        f"expected exactly one rollup_rebuild_completed line, got {len(org_lines)}"
    )
    org_payload = org_lines[0]
    assert org_payload["scope"] == "org"
    assert "program_id" not in org_payload
    assert isinstance(org_payload["duration_ms"], int)
    assert org_payload["event_count"] == 10
