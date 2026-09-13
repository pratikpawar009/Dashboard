"""Unit tests for `ActivityRowIn`'s wire->column alias mapper -- ING-02 T-07
(F-11), FR-4 gap #1.

`ActivityRowIn` (in `app/schemas/ingest_files.py`) declares five `Field(alias=...)`
bindings so producers can POST raw `activity.jsonl` field names while the
service stores `usage_events` column names (DECISIONS.md D-01 / PRD FR-4 /
Q-01, 2026-09-09). `_ROW_SCHEMA_COLUMN_MAP` in `app/services/activity_ingest.py`
mirrors that same table as a plain dict so this test can iterate it -- both
sides must stay in lock-step (see the map's own docstring: "Add an entry here
IFF a matching `Field(alias=...)` is added to `ActivityRowIn`.").

Contract covered:

- Each of the five wire names populates its column-named attribute.
- `populate_by_name=True` accepts the column name directly (service-side and
  test construction path).
- Unknown row-level fields are silently dropped (`extra="ignore"`, FR-4 /
  Q-01) -- the row still validates.
- When both the wire alias and the column name appear on the same row, the
  alias wins (Pydantic v2 default under `populate_by_name=True`); pinning the
  observed behaviour here so an accidental config flip fails visibly.
- A row missing all alias variants of a required field raises
  `pydantic.ValidationError` with `type='missing'` -- the same error type
  `activity_ingest._classify_row_error` maps to `missing_required_field`.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.ingest_files import ActivityRowIn
from app.services.activity_ingest import _ROW_SCHEMA_COLUMN_MAP


def _minimal_row(**overrides: Any) -> dict[str, Any]:
    """Return a minimal valid `ActivityRowIn` payload using column names.

    Overrides let a test replace any field (or add wire-name aliases). The
    base payload uses column names so `populate_by_name=True` is exercised by
    every test that doesn't override the token fields.
    """
    row: dict[str, Any] = {
        "program_id": "prog-a",
        "ts": "2026-09-11T12:00:00Z",
        "cmd_ts": "2026-09-11T11:59:00Z",
        "user": "u-1",
        "session_id": "s-1",
        "command": "cmd",
        "duration_seconds": 3,
        "outcome": "ok",
        "total": 10,
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# The five wire->column aliases resolve (FR-4 / Q-01)
# ---------------------------------------------------------------------------

_ALIAS_PAIRS: list[tuple[str, str]] = sorted(_ROW_SCHEMA_COLUMN_MAP.items())


@pytest.mark.parametrize(("wire_name", "column_name"), _ALIAS_PAIRS)
def test_wire_alias_populates_column_attribute(wire_name: str, column_name: str) -> None:
    payload = _minimal_row(**{wire_name: 123})
    payload.pop(column_name, None)

    row = ActivityRowIn.model_validate(payload)

    assert getattr(row, column_name) == 123


def test_alias_map_covers_exactly_the_five_pinned_pairs() -> None:
    # Guard against silent drift: if a Field(alias=...) is added to
    # ActivityRowIn without a matching _ROW_SCHEMA_COLUMN_MAP entry (or vice
    # versa), this pins the current set so the drift is visible in review.
    assert _ROW_SCHEMA_COLUMN_MAP == {
        "duration_s": "duration_seconds",
        "input_token": "input_tokens",
        "output_token": "output_tokens",
        "cache_read": "cache_read_tokens",
        "cache_write": "cache_write_tokens",
    }


# ---------------------------------------------------------------------------
# populate_by_name=True: column names work too
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("wire_name", "column_name"), _ALIAS_PAIRS)
def test_column_name_accepted_directly_via_populate_by_name(
    wire_name: str, column_name: str
) -> None:
    payload = _minimal_row(**{column_name: 456})

    row = ActivityRowIn.model_validate(payload)

    assert getattr(row, column_name) == 456


# ---------------------------------------------------------------------------
# extra="ignore": unknown row-level fields drop silently, row still validates
# ---------------------------------------------------------------------------


def test_unknown_field_is_silently_dropped() -> None:
    payload = _minimal_row(this_field_does_not_exist="junk", another_unknown=42)

    row = ActivityRowIn.model_validate(payload)

    assert not hasattr(row, "this_field_does_not_exist")
    assert not hasattr(row, "another_unknown")
    assert row.program_id == "prog-a"


def test_unknown_field_does_not_shadow_known_field() -> None:
    # A misspelled alias for a known column (`duration` instead of `duration_s`)
    # is treated as unknown -> dropped, and the required column-named field
    # must still be supplied. This pins that unknown fields cannot substitute
    # for a required one.
    payload = _minimal_row(duration=99)

    row = ActivityRowIn.model_validate(payload)

    assert row.duration_seconds == 3
    assert not hasattr(row, "duration")


# ---------------------------------------------------------------------------
# Both wire alias and column name present -> alias wins (Pydantic v2 default
# under populate_by_name=True). Pin observed behaviour per T-07 directive.
# ---------------------------------------------------------------------------


def test_alias_wins_when_both_wire_and_column_present() -> None:
    payload = _minimal_row(duration_seconds=1, duration_s=2)

    row = ActivityRowIn.model_validate(payload)

    assert row.duration_seconds == 2


# ---------------------------------------------------------------------------
# Missing all-alias-variants of a required field -> ValidationError type=missing
# (activity_ingest._classify_row_error maps this to 'missing_required_field')
# ---------------------------------------------------------------------------


def test_missing_required_column_raises_validation_error_type_missing() -> None:
    payload = _minimal_row()
    payload.pop("duration_seconds")

    with pytest.raises(ValidationError) as excinfo:
        ActivityRowIn.model_validate(payload)

    errors = excinfo.value.errors()
    assert any(
        err.get("type") == "missing" and err.get("loc") == ("duration_s",) for err in errors
    ), errors


def test_missing_required_column_using_wire_alias_variant_also_raises() -> None:
    # Removing both the column name AND the wire alias -> still missing.
    payload = _minimal_row()
    payload.pop("duration_seconds")
    payload.pop("duration_s", None)

    with pytest.raises(ValidationError) as excinfo:
        ActivityRowIn.model_validate(payload)

    assert any(err.get("type") == "missing" for err in excinfo.value.errors())


# ---------------------------------------------------------------------------
# Sanity: aliased fields carry their expected types through validation
# (integer tokens; Decimal copilot_credits) -- protects against a future
# `Field(alias=..., ...)` edit that drops the type on the column side.
# ---------------------------------------------------------------------------


def test_token_aliases_round_trip_as_int() -> None:
    payload = _minimal_row(
        input_token=1, output_token=2, cache_read=3, cache_write=4
    )

    row = ActivityRowIn.model_validate(payload)

    assert row.input_tokens == 1
    assert row.output_tokens == 2
    assert row.cache_read_tokens == 3
    assert row.cache_write_tokens == 4


def test_non_aliased_fields_still_validate() -> None:
    # `copilot_credits` and `source` were added to the schema by migration 006
    # and have no wire alias -- pin they still accept their declared types
    # alongside the aliased fields, so a future alias-table refactor doesn't
    # accidentally regress the non-aliased columns.
    payload = _minimal_row(
        source="harness-mcp-push",
        copilot_credits="1.25",
        input_token=7,
    )

    row = ActivityRowIn.model_validate(payload)

    assert row.source == "harness-mcp-push"
    assert row.copilot_credits == Decimal("1.25")
    assert row.input_tokens == 7
    assert row.ts == datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
