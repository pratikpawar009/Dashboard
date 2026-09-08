"""Unit tests for `app/services/manifest_ingest.py`'s `ingest_manifest_write`
log event -- ING-10-TC-02 (PII half); risk R-01 (top HIGH-severity risk,
research condition C-2).

`docs/features/ING-10/REQUIREMENTS.md` FR-2 pins the exact field allowlist:

    Required: {program_id, token_label, identity_written, roster_received,
               roster_valid, roster_created, roster_updated, roster_removed,
               roster_rejected, duration_ms}
    Optional: {}

`email`/`name` never appear -- not as structured fields, not interpolated
into the message string. Pattern: `AUTH-02`'s
`test_persona_mapping_loaded_event_contains_no_pii_tc15`
(`tests/unit/test_persona_resolver.py`) for the allowlist-not-denylist
assertion shape, and `tests/unit/test_ingest_token_auth.py`'s
`test_log_event_key_set_exact_allowlist_tc18` for asserting the RAW
formatted record string never contains a seeded PII value (interpolation
leak, not just a missing structured field).

Log-capture idiom (duplicated locally, matching this repo's established
per-file-ownership precedent -- see `test_ingest_token_auth.py`'s own
docstring): a handler is attached directly to the real, named
`app.services.manifest_ingest` logger, forcing `.disabled = False` /
`.propagate = False` for the test's duration. `migrations/env.py:19`'s
`fileConfig(disable_existing_loggers=True)` permanently disables any
already-existing logger (including this one) once `tests/test_migrations.py`
has run earlier in the same pytest session -- `caplog`, a root-attached
handler, and `configure_logging()` + `capsys` are all blind to a disabled
logger regardless of test order.

Every test calls `ingest_manifest()` directly against a real Postgres test
DB via `migrated_db`/`test_session` (no mocks at the integration boundary),
matching `test_ingest_token_auth.py`'s own direct-call convention for
`get_ingest_token()`.

Every outcome path FR-2 requires log coverage for is exercised: happy path
(200), a row-level rejection mix (unmapped role slug + malformed email,
D-09), the request-level `400` abort (`program.type` enum miss, D-05), and
-- service-level only, per AF-09 -- the `413` payload-cap path. AF-09: the
router's own FR-5 cap check short-circuits before `ingest_manifest()` is
ever called, so a real oversized HTTP request never reaches this module's
413 logging branch; only a direct service-level caller (this test) does.
No HTTP-level 413 log event exists to assert on.

Synthetic PII (`.claude/rules/security-baseline.md`): every email/name
value here is an obviously-fabricated placeholder (`zzyzx.*@example.invalid`
-- `.invalid` is the RFC 2606 reserved not-a-real-domain TLD; `zzyzx` is a
distinctive, never-otherwise-used token), never anything resembling a real
person.
"""

import json
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import JSONFormatter
from app.services.manifest_ingest import ingest_manifest
from tests.conftest import AlembicRunner

# -----------------------------------------------------------------------------
# FR-2's exact field allowlist (Required set) plus JSONFormatter's own
# first-class meta fields. Asserted as a full set equality on every test --
# not just "email/name absent" -- so an unexpected new field (PII or not)
# fails the test the same way a missing required field would.
# -----------------------------------------------------------------------------

_FR2_REQUIRED_FIELDS = {
    "program_id",
    "token_label",
    "identity_written",
    "roster_received",
    "roster_valid",
    "roster_created",
    "roster_updated",
    "roster_removed",
    "roster_rejected",
    "duration_ms",
}
_JSON_FORMATTER_META_FIELDS = {"timestamp", "level", "logger", "message"}
_EXPECTED_KEY_SET = _FR2_REQUIRED_FIELDS | _JSON_FORMATTER_META_FIELDS


# -----------------------------------------------------------------------------
# Log-capture idiom -- mirrors test_ingest_token_auth.py's
# `_RecordCapturingHandler` / `_isolated_ingest_auth_logger` (see module
# docstring for the disabled-logger trap this works around).
# -----------------------------------------------------------------------------


class _RecordCapturingHandler(logging.Handler):
    """Stores emitted LogRecord instances verbatim, without formatting them."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _isolated_manifest_ingest_logger() -> Iterator[logging.Logger]:
    """Force-resets and yields the real `app.services.manifest_ingest` logger,
    isolated from ambient process state, restoring it in a `finally` -- see
    module docstring for the disabled-logger trap this works around."""
    logger = logging.getLogger("app.services.manifest_ingest")
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
def manifest_ingest_logger_records() -> Iterator[list[logging.LogRecord]]:
    """Captures raw LogRecords from the real `ingest_manifest()` logger,
    formatted after the fact through the real `JSONFormatter` per test."""
    with _isolated_manifest_ingest_logger() as logger:
        handler = _RecordCapturingHandler()
        logger.addHandler(handler)
        try:
            yield handler.records
        finally:
            logger.removeHandler(handler)


def _formatted_payloads(records: list[logging.LogRecord]) -> list[dict[str, Any]]:
    return [json.loads(JSONFormatter().format(r)) for r in records]


def _write_events(records: list[logging.LogRecord]) -> list[logging.LogRecord]:
    return [r for r in records if r.getMessage() == "ingest_manifest_write"]


# -----------------------------------------------------------------------------
# ING-10-TC-02 (PII half) -- happy path (200).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_write_log_matches_fr2_allowlist_no_pii(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    manifest_ingest_logger_records: list[logging.LogRecord],
) -> None:
    """A fully successful manifest push. `ingest_manifest_write`'s structured
    fields match FR-2's allowlist exactly, and neither the structured fields
    nor the rendered message string carry the synthetic email/name/alias
    seeded into this request's one `team[]` entry."""
    program_id = f"prog-pii-happy-{uuid.uuid4().hex[:8]}"
    synthetic_email = "zzyzx.happyroster@example.invalid"
    synthetic_alias_email = "zzyzx.happyroster.alias@example.invalid"
    synthetic_name = "Zzyzx Happyroster Synthetic"
    token_label = "tc10-happy-token"

    payload = {
        "programId": program_id,
        "program": {
            "name": "Zzyzx Test Program",
            "type": "Greenfield",
            "description": "Synthetic program for T-10 PII logging coverage",
        },
        "team": [
            {
                "email": synthetic_email,
                "name": synthetic_name,
                "role": "dev",
                "aliases": [synthetic_alias_email],
            }
        ],
    }

    response = await ingest_manifest(
        db=test_session, program_id=program_id, payload=payload, token_label=token_label
    )
    assert response.roster.valid == 1  # sanity: the write actually happened

    events = _write_events(manifest_ingest_logger_records)
    assert len(events) == 1
    record = events[0]
    formatted = _formatted_payloads([record])[0]

    # Allowlist, not a denylist: the key set is exactly FR-2's Required
    # fields plus JSONFormatter's own first-class meta.
    assert set(formatted.keys()) == _EXPECTED_KEY_SET
    assert "email" not in formatted
    assert "name" not in formatted

    assert formatted["program_id"] == program_id
    assert formatted["token_label"] == token_label
    assert formatted["identity_written"] is True
    assert formatted["roster_received"] == 1
    assert formatted["roster_valid"] == 1
    assert formatted["roster_created"] == 1
    assert formatted["roster_updated"] == 0
    assert formatted["roster_removed"] == 0
    assert formatted["roster_rejected"] == 0
    assert isinstance(formatted["duration_ms"], int)
    assert formatted["duration_ms"] >= 0

    raw_formatted = JSONFormatter().format(record)
    assert synthetic_email not in raw_formatted
    assert synthetic_alias_email not in raw_formatted
    assert synthetic_name not in raw_formatted


# -----------------------------------------------------------------------------
# ING-10-TC-02 (PII half) -- row-level rejection mix (D-09): one valid entry,
# one unmapped-role-slug rejection, one malformed-email rejection. Identity
# and the valid entry still commit; both rejections are row-scoped only.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_row_level_rejection_log_matches_fr2_allowlist_no_pii(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    manifest_ingest_logger_records: list[logging.LogRecord],
) -> None:
    """A request mixing one valid `team[]` entry with two row-level
    rejections (an unmapped role slug and a malformed email format, D-09).
    Every entry -- valid or rejected -- carries its own distinctive synthetic
    PII; none of it reaches the log event."""
    program_id = f"prog-pii-reject-{uuid.uuid4().hex[:8]}"
    token_label = "tc10-reject-token"

    valid_email = "zzyzx.validmember@example.invalid"
    valid_name = "Zzyzx Validmember Synthetic"
    unmapped_role_email = "zzyzx.unmappedrole@example.invalid"
    unmapped_role_name = "Zzyzx Unmappedrole Synthetic"
    malformed_email = "zzyzx-not-an-email-format"
    malformed_email_name = "Zzyzx Malformedemail Synthetic"

    payload = {
        "programId": program_id,
        "program": {
            "name": "Zzyzx Test Program",
            "type": "Brownfield",
            "description": "Synthetic program for T-10 PII logging coverage",
        },
        "team": [
            {"email": valid_email, "name": valid_name, "role": "dev", "aliases": []},
            {
                "email": unmapped_role_email,
                "name": unmapped_role_name,
                "role": "not-a-mapped-slug",
                "aliases": [],
            },
            {
                "email": malformed_email,
                "name": malformed_email_name,
                "role": "dev",
                "aliases": [],
            },
        ],
    }

    response = await ingest_manifest(
        db=test_session, program_id=program_id, payload=payload, token_label=token_label
    )
    assert response.roster.valid == 1
    assert response.roster.rejected == 2

    events = _write_events(manifest_ingest_logger_records)
    assert len(events) == 1
    record = events[0]
    formatted = _formatted_payloads([record])[0]

    assert set(formatted.keys()) == _EXPECTED_KEY_SET
    assert "email" not in formatted
    assert "name" not in formatted

    assert formatted["identity_written"] is True
    assert formatted["roster_received"] == 3
    assert formatted["roster_valid"] == 1
    assert formatted["roster_created"] == 1
    assert formatted["roster_rejected"] == 2

    raw_formatted = JSONFormatter().format(record)
    for pii in (
        valid_email,
        valid_name,
        unmapped_role_email,
        unmapped_role_name,
        malformed_email,
        malformed_email_name,
    ):
        assert pii not in raw_formatted


# -----------------------------------------------------------------------------
# ING-10-TC-02 (PII half) -- request-level 400 abort (FR-1/D-05): a
# `program.type` enum miss aborts the whole request before any team[] entry
# is parsed or written. T-06 claimed the PII-safe log event still fires on
# this aborted path -- this test makes that an actual assertion.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_level_abort_log_matches_fr2_allowlist_no_pii(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    manifest_ingest_logger_records: list[logging.LogRecord],
) -> None:
    """`program.type` outside the allowed enum aborts with `400` and zero
    writes. The `team[]` entry accompanying the malformed `program:` block is
    never parsed, but its synthetic email/name must still never reach the
    log event emitted on the way out."""
    program_id = f"prog-pii-abort-{uuid.uuid4().hex[:8]}"
    token_label = "tc10-abort-token"
    synthetic_email = "zzyzx.abortedroster@example.invalid"
    synthetic_name = "Zzyzx Abortedroster Synthetic"

    payload = {
        "programId": program_id,
        "program": {
            "name": "Zzyzx Test Program",
            "type": "NotARealProgramType",
            "description": "Synthetic program for T-10 PII logging coverage",
        },
        "team": [
            {
                "email": synthetic_email,
                "name": synthetic_name,
                "role": "dev",
                "aliases": [],
            }
        ],
    }

    with pytest.raises(HTTPException) as exc_info:
        await ingest_manifest(
            db=test_session, program_id=program_id, payload=payload, token_label=token_label
        )
    assert exc_info.value.status_code == 400

    events = _write_events(manifest_ingest_logger_records)
    assert len(events) == 1
    record = events[0]
    formatted = _formatted_payloads([record])[0]

    assert set(formatted.keys()) == _EXPECTED_KEY_SET
    assert "email" not in formatted
    assert "name" not in formatted

    assert formatted["identity_written"] is False
    assert formatted["roster_received"] == 1
    assert formatted["roster_valid"] == 0
    assert formatted["roster_created"] == 0
    assert formatted["roster_updated"] == 0
    assert formatted["roster_removed"] == 0
    assert formatted["roster_rejected"] == 0

    raw_formatted = JSONFormatter().format(record)
    assert synthetic_email not in raw_formatted
    assert synthetic_name not in raw_formatted


# -----------------------------------------------------------------------------
# ING-10-TC-02 (PII half) -- FR-5's 500-entry cap, SERVICE level only (AF-09).
# The router's own FR-5 check short-circuits before `ingest_manifest()` is
# ever called, so a real oversized HTTP request never reaches this branch's
# logging -- only a direct service-level caller (this test) does. Do NOT
# assert an HTTP-level 413 log event; none is emitted.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_service_level_413_cap_log_matches_fr2_allowlist_no_pii(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    manifest_ingest_logger_records: list[logging.LogRecord],
) -> None:
    """501 raw `team[]` entries (one over the FR-5 cap), called directly
    against `ingest_manifest()` -- never through the HTTP router, whose own
    cap check would short-circuit before this branch runs (AF-09)."""
    program_id = f"prog-pii-cap-{uuid.uuid4().hex[:8]}"
    token_label = "tc10-cap-token"
    synthetic_email = "zzyzx.capbreaker@example.invalid"
    synthetic_name = "Zzyzx Capbreaker Synthetic"

    oversized_team: list[dict[str, Any]] = [
        {
            "email": f"zzyzx.capfiller{i}@example.invalid",
            "name": "Zzyzx Capfiller Synthetic",
            "role": "dev",
            "aliases": [],
        }
        for i in range(500)
    ]
    oversized_team.append(
        {"email": synthetic_email, "name": synthetic_name, "role": "dev", "aliases": []}
    )
    assert len(oversized_team) == 501

    payload = {
        "programId": program_id,
        "program": {
            "name": "Zzyzx Test Program",
            "type": "Greenfield",
            "description": "Synthetic program for T-10 PII logging coverage",
        },
        "team": oversized_team,
    }

    with pytest.raises(HTTPException) as exc_info:
        await ingest_manifest(
            db=test_session, program_id=program_id, payload=payload, token_label=token_label
        )
    assert exc_info.value.status_code == 413

    events = _write_events(manifest_ingest_logger_records)
    assert len(events) == 1
    record = events[0]
    formatted = _formatted_payloads([record])[0]

    assert set(formatted.keys()) == _EXPECTED_KEY_SET
    assert "email" not in formatted
    assert "name" not in formatted

    assert formatted["identity_written"] is False
    assert formatted["roster_received"] == 501
    assert formatted["roster_valid"] == 0
    assert formatted["roster_created"] == 0
    assert formatted["roster_updated"] == 0
    assert formatted["roster_removed"] == 0
    assert formatted["roster_rejected"] == 0

    raw_formatted = JSONFormatter().format(record)
    assert synthetic_email not in raw_formatted
    assert synthetic_name not in raw_formatted
