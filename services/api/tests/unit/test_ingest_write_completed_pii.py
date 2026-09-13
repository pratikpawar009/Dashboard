"""Unit tests for `ingest_write_completed`'s PII-safe field allowlist and the
response body's rejection-entry discipline (ING-02 F-16 / T-11 -- C-7 / FR-8;
research risk R-11).

Contract (`docs/features/ING-02/REQUIREMENTS.md` FR-8, C-7): the
`ingest_write_completed` structured log event carries EXACTLY
`{program_id, rows_received, rows_inserted, rows_updated, rows_rejected,
duration_ms}` -- never `user` (email), `command`, `feature`, `session_id`, or
any other row content, and not as an interpolated substring of the rendered
message either. Row-level rejection outcomes in `IngestFilesResponse.rejected`
are `{index, reason}` only -- the offending row's payload is never embedded.

Test slice: mirrors `services/api/tests/unit/test_manifest_pii_logging.py`'s
`_EXPECTED_KEY_SET` allowlist shape (T-10, ING-10-TC-02) and reuses
`test_ingest_intra_batch_dedup.py`'s fake `AsyncSession` + monkeypatched
`rebuild_program_rollups` seam (T-09) -- no real DB touch, no HTTP router.
`token_label` NOT in the allowlist is asserted directly per T-04's own
`# noqa: ARG001 -- reserved for parity with manifest_ingest; not in log
allowlist per FR-8` guard.

Log-capture idiom: mirrored from `test_manifest_pii_logging.py`. Attaches a
`_RecordCapturingHandler` to the real, named `app.services.activity_ingest`
logger and force-resets `.disabled=False` / `.propagate=False` for the test's
duration. `migrations/env.py:19`'s `fileConfig(disable_existing_loggers=True)`
permanently disables loggers once `tests/test_migrations.py` has run in the
same session -- `caplog` is blind to a disabled logger regardless of test
order (see `test_manifest_pii_logging.py`'s docstring for the full trap).

Synthetic PII (`.claude/rules/security-baseline.md`): every email/session/
command value here is an obviously-fabricated placeholder using RFC 2606's
reserved `.invalid` TLD plus a distinctive `zzyzx` token that never appears
in real content -- never anything resembling a real person.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import pytest

from app.core.logging import JSONFormatter
from app.services import activity_ingest
from app.services.rollup_rebuild import RebuildResult

# -----------------------------------------------------------------------------
# FR-8 / C-7's exact field allowlist -- the frozenset live in the service
# module is the source of truth; a snapshot below pins the literal set as a
# regression sentinel. `JSONFormatter`'s own first-class meta fields are added
# for the full-record equality assertion (matches _EXPECTED_KEY_SET shape from
# test_manifest_pii_logging.py).
# -----------------------------------------------------------------------------

_FR8_ALLOWLIST_LITERAL = frozenset(
    {
        "program_id",
        "rows_received",
        "rows_inserted",
        "rows_updated",
        "rows_rejected",
        "duration_ms",
    }
)
_JSON_FORMATTER_META_FIELDS = {"timestamp", "level", "logger", "message"}
_EXPECTED_KEY_SET = _FR8_ALLOWLIST_LITERAL | _JSON_FORMATTER_META_FIELDS

_PROGRAM_ID = "prog-pii-t11"
_TOKEN_LABEL = "zzyzx-token-label-t11"  # PII probe -- must not appear in log
_TS = "2026-09-11T10:00:00Z"


# -----------------------------------------------------------------------------
# Log-capture idiom -- mirrors test_manifest_pii_logging.py's
# `_RecordCapturingHandler` / `_isolated_manifest_ingest_logger`.
# -----------------------------------------------------------------------------


class _RecordCapturingHandler(logging.Handler):
    """Stores emitted LogRecord instances verbatim, without formatting them."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _isolated_activity_ingest_logger() -> Iterator[logging.Logger]:
    """Force-resets and yields the real `app.services.activity_ingest` logger,
    isolated from ambient process state, restoring it in a `finally` -- see
    module docstring for the disabled-logger trap this works around."""
    logger = logging.getLogger("app.services.activity_ingest")
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
def activity_ingest_logger_records() -> Iterator[list[logging.LogRecord]]:
    """Captures raw LogRecords from the real `ingest_files()` logger,
    formatted after the fact through the real `JSONFormatter` per test."""
    with _isolated_activity_ingest_logger() as logger:
        handler = _RecordCapturingHandler()
        logger.addHandler(handler)
        try:
            yield handler.records
        finally:
            logger.removeHandler(handler)


def _formatted_payloads(records: list[logging.LogRecord]) -> list[dict[str, Any]]:
    return [json.loads(JSONFormatter().format(r)) for r in records]


def _write_events(records: list[logging.LogRecord]) -> list[logging.LogRecord]:
    return [r for r in records if r.getMessage() == "ingest_write_completed"]


# -----------------------------------------------------------------------------
# DB seam -- reuses T-09's fake AsyncSession + pg_insert probe shape, so the
# test drives real `ingest_files()` end-to-end without hitting Postgres. The
# service's log emit is what we assert on; the write path is out of scope
# (integration T-13/T-14 covers it against a real DB).
# -----------------------------------------------------------------------------


class _FakeExecuteResult:
    def tuples(self) -> _FakeExecuteResult:
        return self

    def all(self) -> list[tuple[str, datetime]]:
        return []


class _FakeSession:
    async def execute(self, _stmt: Any) -> _FakeExecuteResult:
        return _FakeExecuteResult()

    async def commit(self) -> None:
        return None


async def _noop_rebuild(_session: Any, program_id: str) -> RebuildResult:
    return RebuildResult(
        scope="program", program_id=program_id, duration_ms=0, event_count=0
    )


@pytest.fixture(autouse=True)
def _stub_program_rebuild(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test here calls `ingest_files`; the program rebuild is not the
    subject under test and is stubbed at the module boundary."""
    monkeypatch.setattr(activity_ingest, "rebuild_program_rollups", _noop_rebuild)


@pytest.fixture(autouse=True)
def _stub_pg_insert(monkeypatch: pytest.MonkeyPatch) -> None:
    """Intercept `pg_insert(UsageEvent).values(...).on_conflict_do_update(...)`
    so `_FakeSession.execute()` is exercised without a real Postgres dialect
    or bind params. The insert path is not the subject under test here."""

    class _FakeInsert:
        def values(self, _chunk: list[dict[str, Any]]) -> _FakeInsert:
            return self

        def on_conflict_do_update(self, **_kwargs: Any) -> _FakeInsert:
            return self

        class _Excluded:
            def __getattr__(self, _name: str) -> None:
                return None

        @property
        def excluded(self) -> _FakeInsert._Excluded:
            return _FakeInsert._Excluded()

    monkeypatch.setattr(activity_ingest, "pg_insert", lambda _model: _FakeInsert())


def _valid_row(
    *,
    session_id: str,
    cmd_ts: str = _TS,
    user: str = "zzyzx.contributor@example.invalid",
    command: str = "zzyzx-command-probe",
) -> dict[str, Any]:
    """Build a wire-shaped `activity.jsonl` row. `user` and `command` carry
    distinctive synthetic PII probes -- an interpolation leak into the log or
    a rejection body would surface these substrings."""
    return {
        "program_id": _PROGRAM_ID,
        "ts": _TS,
        "cmd_ts": cmd_ts,
        "user": user,
        "session_id": session_id,
        "command": command,
        "duration_s": 1,
        "outcome": "success",
        "total": 100,
    }


async def _run(rows: list[dict[str, Any]]) -> Any:
    """Drive `ingest_files` and return its response envelope."""
    return await activity_ingest.ingest_files(
        db=_FakeSession(),  # type: ignore[arg-type]
        program_id=_PROGRAM_ID,
        payload={"rows": rows},
        token_label=_TOKEN_LABEL,
        on_org_rebuild=lambda: None,
    )


# -----------------------------------------------------------------------------
# T-11 / C-7 / FR-8 -- allowlist snapshot: the service-module frozenset is the
# runtime source of truth, but the LITERAL set is pinned here as a regression
# sentinel. Any future edit that adds `user` / `command` / `feature` (etc.)
# to the allowlist trips this test before the log record test.
# -----------------------------------------------------------------------------


def test_log_field_allowlist_matches_fr8_snapshot() -> None:
    """`_LOG_FIELD_ALLOWLIST` is exactly the set FR-8 pins. If T-04 shipped a
    wider allowlist (added `user`/`command`/`feature`/`token_label`/row data),
    this fails FIRST -- before the log-record assertion -- so the failure
    diagnostic points at the source constant, not at a downstream symptom."""
    assert activity_ingest._LOG_FIELD_ALLOWLIST == _FR8_ALLOWLIST_LITERAL


# -----------------------------------------------------------------------------
# T-11 / C-7 / FR-8 -- happy path: emitted record's structured fields are
# EXACTLY the allowlist plus JSONFormatter meta; neither structured fields
# nor the rendered message string carry any synthetic PII probe.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_log_matches_fr8_allowlist_no_pii(
    activity_ingest_logger_records: list[logging.LogRecord],
) -> None:
    """Happy-path batch: three distinct-key rows, all commit, one
    `ingest_write_completed` event emitted. The full formatted key set is
    equal to (allowlist | JSONFormatter meta) -- allowlist, not denylist, so
    a future extra field fails just like a missing one. `user`, `command`,
    `session_id`, `token_label` never appear as structured fields OR as
    substrings of the rendered payload."""
    synthetic_user = "zzyzx.happy@example.invalid"
    synthetic_command = "zzyzx-happy-command"
    synthetic_session = "zzyzx-happy-session-id"
    rows = [
        _valid_row(
            session_id=synthetic_session,
            cmd_ts="2026-09-11T10:00:00Z",
            user=synthetic_user,
            command=synthetic_command,
        ),
        _valid_row(session_id="zzyzx-s2", cmd_ts="2026-09-11T10:00:01Z"),
        _valid_row(session_id="zzyzx-s3", cmd_ts="2026-09-11T10:00:02Z"),
    ]

    response = await _run(rows)
    assert response.received == 3
    assert response.valid == 3

    events = _write_events(activity_ingest_logger_records)
    assert len(events) == 1
    record = events[0]
    formatted = _formatted_payloads([record])[0]

    # Allowlist, not denylist: the key set is exactly FR-8's allowlist plus
    # JSONFormatter's own first-class meta. A future stray field fails here.
    assert set(formatted.keys()) == _EXPECTED_KEY_SET

    # Explicit spot checks for the fields that would carry PII if they leaked.
    assert "user" not in formatted
    assert "email" not in formatted
    assert "command" not in formatted
    assert "feature" not in formatted
    assert "session_id" not in formatted
    assert "cmd_ts" not in formatted
    assert "rows" not in formatted
    assert "row" not in formatted

    assert formatted["program_id"] == _PROGRAM_ID
    assert formatted["message"] == "ingest_write_completed"
    assert formatted["rows_received"] == 3
    assert formatted["rows_inserted"] + formatted["rows_updated"] == 3
    assert formatted["rows_rejected"] == 0
    assert isinstance(formatted["duration_ms"], int)
    assert formatted["duration_ms"] >= 0

    # Interpolation-leak probe: no synthetic PII value survives into the
    # rendered payload string (structured fields OR message).
    raw_formatted = JSONFormatter().format(record)
    assert synthetic_user not in raw_formatted
    assert synthetic_command not in raw_formatted
    assert synthetic_session not in raw_formatted


# -----------------------------------------------------------------------------
# T-11 / C-7 / FR-8 -- `token_label` is NOT in the log allowlist per FR-8.
# T-04 signals this intent with `# noqa: ARG001 -- ... not in log allowlist
# per FR-8` on the `ingest_files` parameter; this test pins the runtime
# behaviour so a future accidental `extra={"token_label": ...}` regresses.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_label_never_in_log_record(
    activity_ingest_logger_records: list[logging.LogRecord],
) -> None:
    """`token_label` is passed into `ingest_files()` but MUST NOT appear in
    the emitted log record -- not as a structured field, not interpolated
    into the message. `_TOKEN_LABEL`'s `zzyzx-token-label-t11` is a
    distinctive substring that would surface any leak."""
    rows = [_valid_row(session_id="zzyzx-s-token", cmd_ts="2026-09-11T10:00:00Z")]

    await _run(rows)

    events = _write_events(activity_ingest_logger_records)
    assert len(events) == 1
    record = events[0]
    formatted = _formatted_payloads([record])[0]

    assert "token_label" not in formatted
    raw_formatted = JSONFormatter().format(record)
    assert _TOKEN_LABEL not in raw_formatted


# -----------------------------------------------------------------------------
# T-11 / C-7 / FR-8 -- rejection body carries `{index, reason}` only. Two
# rows fail Pydantic validation via malformed `cmd_ts`; both rejection
# entries expose row index + short reason slug, never the offending payload.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejection_entries_carry_indices_only_no_row_content() -> None:
    """Inject two rows with unparseable `cmd_ts` values (triggers
    `malformed_iso_date` reason per `_classify_row_error`). The response
    `rejected[]` list carries `{index, reason}` and nothing else -- no
    `user`, no `command`, no `session_id`, no free-form `error` payload
    dump. `reason` is a short slug (not a raised message with row
    interpolation) per `_classify_row_error`'s fixed vocabulary."""
    synthetic_bad_user = "zzyzx.rejected@example.invalid"
    synthetic_bad_command = "zzyzx-rejected-command"
    synthetic_bad_session = "zzyzx-rejected-session"

    rows = [
        _valid_row(session_id="zzyzx-ok", cmd_ts="2026-09-11T10:00:00Z"),
        _valid_row(
            session_id=synthetic_bad_session,
            cmd_ts="this-is-not-a-timestamp",
            user=synthetic_bad_user,
            command=synthetic_bad_command,
        ),
        _valid_row(
            session_id="zzyzx-bad-2",
            cmd_ts="also-not-a-timestamp",
            user=synthetic_bad_user,
            command=synthetic_bad_command,
        ),
    ]

    response = await _run(rows)

    assert response.received == 3
    assert response.valid == 1
    assert len(response.rejected) == 2

    for entry in response.rejected:
        # RejectionEntry's schema pins `{index, reason}` -- the Pydantic v2
        # model's own fields set is the boundary. Assert it here anyway so
        # a future schema drift (adding e.g. a `context`/`payload` field)
        # trips this test rather than leaking PII silently.
        dumped = entry.model_dump()
        assert set(dumped.keys()) == {"index", "reason"}
        assert isinstance(dumped["index"], int)
        assert isinstance(dumped["reason"], str)
        # `reason` is a short slug from the fixed vocabulary, never a raised
        # message with row content interpolated. `_classify_row_error`
        # emits `malformed_iso_date` for the bad-`cmd_ts` path.
        assert dumped["reason"] == "malformed_iso_date"
        # Belt-and-braces: no synthetic PII survives into the reason string.
        assert synthetic_bad_user not in dumped["reason"]
        assert synthetic_bad_command not in dumped["reason"]
        assert synthetic_bad_session not in dumped["reason"]

    # Response envelope as a whole must not carry row content either -- a
    # JSON round-trip of the entire response is the final belt-and-braces
    # check that no PII probe slipped through any other envelope field.
    serialised = response.model_dump_json()
    assert synthetic_bad_user not in serialised
    assert synthetic_bad_command not in serialised
    assert synthetic_bad_session not in serialised
