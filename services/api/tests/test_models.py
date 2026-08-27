"""Fixture-driven model/reflection assertions for the BED-01 schema (18 tables).

Pure SQLAlchemy model reflection against `tests/fixtures/prd_8_4_schema.json`
via `model.__table__.c` — no live database connection (research condition
C-1's acceptance gate).

Covers BED-01-TC-02 (per-table fixture-vs-model field shape, plus
table-level `constraints` block — multi-column UniqueConstraint/Index — per
research condition C-1's "fields/constraints" gate), TC-03
(deliberate-mismatch meta-test, both column- and constraint-level), TC-10
(ingest_tokens forbidden-column reflection), TC-12/13/14/15
(BigInteger/JSONB/ARRAY/discriminator type-mapping assertions).
"""

import json
import re
from pathlib import Path
from typing import Any, cast

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

import app.models as models

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "prd_8_4_schema.json"
FIXTURE: dict[str, Any] = json.loads(FIXTURE_PATH.read_text())

MODELS_BY_TABLENAME: dict[str, type[models.Base]] = {
    getattr(models, name).__tablename__: getattr(models, name)
    for name in models.__all__
    if name != "Base"
}

TABLE_NAMES = sorted(FIXTURE["tables"].keys())


def _type_matches(fixture_type: str, sa_type: sa.types.TypeEngine) -> bool:
    """Map a PRD §8.4 fixture type name to the SQLAlchemy type it must be."""
    if fixture_type == "BigInteger":
        return isinstance(sa_type, sa.BigInteger)
    if fixture_type == "Integer":
        return isinstance(sa_type, sa.Integer) and not isinstance(sa_type, sa.BigInteger)
    if fixture_type == "String":
        return isinstance(sa_type, sa.String)
    if fixture_type == "DateTime(timezone=True)":
        return isinstance(sa_type, sa.DateTime) and sa_type.timezone is True
    if fixture_type == "JSONB":
        return isinstance(sa_type, (postgresql.JSONB, sa.JSON))
    if fixture_type == "ARRAY(String)":
        return isinstance(sa_type, postgresql.ARRAY) and isinstance(sa_type.item_type, sa.String)
    raise ValueError(f"tests/fixtures/prd_8_4_schema.json: unknown fixture type {fixture_type!r}")


def _default_matches(fixture_default: Any, column: Any) -> bool:
    """A null fixture default means PRD §8.4 does not mandate one — an
    implementation-level default (e.g. `id`'s uuid4 generator) is out of
    scope for this comparison. A non-null fixture default must match the
    model's scalar default value exactly.
    """
    if fixture_default is None:
        return True
    default = column.default
    if default is None or not getattr(default, "is_scalar", False):
        return False
    return bool(default.arg == fixture_default)


def _compare_column(table_name: str, fixture_col: dict[str, Any], column: Any) -> list[str]:
    """Return mismatch descriptions between a fixture column entry and the
    live SQLAlchemy column. Empty list means match. Shared by TC-02's
    parametrized pass and TC-03's deliberate-mismatch meta-test so the same
    comparison logic is what gets proven non-vacuous.
    """
    prefix = f"{table_name}.{fixture_col['name']}"
    mismatches: list[str] = []
    if not _type_matches(fixture_col["type"], column.type):
        mismatches.append(
            f"{prefix}: type mismatch (fixture={fixture_col['type']!r}, actual={column.type!r})"
        )
    if column.nullable != fixture_col["nullable"]:
        mismatches.append(
            f"{prefix}: nullable mismatch (fixture={fixture_col['nullable']!r}, "
            f"actual={column.nullable!r})"
        )
    if not _default_matches(fixture_col["default"], column):
        mismatches.append(
            f"{prefix}: default mismatch (fixture={fixture_col['default']!r}, "
            f"actual={column.default!r})"
        )
    if bool(column.unique) != fixture_col["unique"]:
        mismatches.append(
            f"{prefix}: unique mismatch (fixture={fixture_col['unique']!r}, "
            f"actual={bool(column.unique)!r})"
        )
    return mismatches


_CONSTRAINT_PATTERN = re.compile(r"^(unique|index)\(\s*([^)]+?)\s*\)")


def _parse_fixture_constraints(entries: list[str]) -> set[tuple[str, tuple[str, ...]]]:
    """Parse `unique(col[, col...])` / `index(col[, col...])` prefixes out of
    a fixture table's `constraints` list into normalized (kind, columns)
    tuples. Entries without that prefix are prose-only notes (e.g.
    ingest_tokens' "no column stores the raw token..." entry, already
    covered by `TestIngestTokensNoRawTokenColumn`) and are skipped rather
    than hand-transcribed.
    """
    parsed: set[tuple[str, tuple[str, ...]]] = set()
    for entry in entries:
        match = _CONSTRAINT_PATTERN.match(entry)
        if not match:
            continue
        kind, cols_str = match.groups()
        columns = tuple(c.strip() for c in cols_str.split(","))
        parsed.add((kind, columns))
    return parsed


def _actual_table_constraints(table: Any) -> set[tuple[str, tuple[str, ...]]]:
    """Normalize a live (or cloned) `sa.Table`'s UniqueConstraints and
    Indexes into the same (kind, columns) shape as
    `_parse_fixture_constraints`. `mapped_column(..., unique=True)` already
    materializes as a single-column `UniqueConstraint` on `table.constraints`
    (verified via reflection), so single-column fixture `unique(...)`
    entries are covered here too, not only by `_compare_column`'s
    `column.unique` check.
    """
    actual: set[tuple[str, tuple[str, ...]]] = set()
    for constraint in table.constraints:
        if isinstance(constraint, sa.UniqueConstraint):
            actual.add(("unique", tuple(col.name for col in constraint.columns)))
    for index in table.indexes:
        actual.add(("index", tuple(col.name for col in index.columns)))
    return actual


def _compare_constraints(table_name: str, fixture_constraints: list[str], table: Any) -> list[str]:
    """Return mismatch descriptions between a fixture table's `constraints`
    list and the live table's UniqueConstraint/Index shape. Empty list means
    match. Shared by TestFixtureDrivenTableConstraints's parametrized pass
    and the deliberate-mismatch meta-test below, mirroring
    `_compare_column`/TC-03's pattern.
    """
    expected = _parse_fixture_constraints(fixture_constraints)
    actual = _actual_table_constraints(table)

    mismatches: list[str] = []
    for kind, columns in sorted(expected - actual):
        mismatches.append(f"{table_name}: missing {kind}({', '.join(columns)}) per fixture")
    for kind, columns in sorted(actual - expected):
        mismatches.append(f"{table_name}: unexpected {kind}({', '.join(columns)}) not in fixture")
    return mismatches


class TestFixtureDrivenModelShape:
    """BED-01-TC-02: every table/column in the fixture matches the model."""

    @pytest.mark.parametrize("table_name", TABLE_NAMES)
    def test_table_matches_fixture(self, table_name: str) -> None:
        assert table_name in MODELS_BY_TABLENAME, f"no model registered for table {table_name!r}"
        table_columns = MODELS_BY_TABLENAME[table_name].__table__.c

        all_mismatches: list[str] = []
        for fixture_col in FIXTURE["tables"][table_name]["columns"]:
            name = fixture_col["name"]
            assert name in table_columns, (
                f"{table_name}.{name}: declared in fixture but missing on model"
            )
            all_mismatches.extend(_compare_column(table_name, fixture_col, table_columns[name]))

        assert not all_mismatches, "\n".join(all_mismatches)


class TestFixtureComparisonDetectsMismatch:
    """BED-01-TC-03: prove the TC-02 comparison isn't a vacuous pass."""

    def test_deliberate_nullable_mismatch_is_detected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        table_name = "usage_events"
        column_name = "session_id"
        column = MODELS_BY_TABLENAME[table_name].__table__.c[column_name]
        fixture_col = next(
            c for c in FIXTURE["tables"][table_name]["columns"] if c["name"] == column_name
        )
        assert fixture_col["nullable"] is False  # sanity: PRD §8.4 declares NOT NULL

        monkeypatch.setattr(column, "nullable", True)

        mismatches = _compare_column(table_name, fixture_col, column)

        assert mismatches, "comparison helper failed to detect a deliberate nullable mismatch"
        assert any("nullable mismatch" in m for m in mismatches)
        # monkeypatch reverts `column.nullable` automatically at test teardown.


class TestFixtureDrivenTableConstraints:
    """BED-01-TC-02 (constraint-level): every table's UniqueConstraint/Index
    set matches the fixture's `constraints` block. Closes the gap flagged in
    REVIEW.md F-1 — TC-02 previously asserted column shape only, leaving
    multi-column UniqueConstraint/Index definitions on 11/18 tables with no
    fixture-vs-model verification anywhere.
    """

    @pytest.mark.parametrize("table_name", TABLE_NAMES)
    def test_table_constraints_match_fixture(self, table_name: str) -> None:
        table = MODELS_BY_TABLENAME[table_name].__table__
        mismatches = _compare_constraints(
            table_name, FIXTURE["tables"][table_name]["constraints"], table
        )
        assert not mismatches, "\n".join(mismatches)


class TestConstraintComparisonDetectsMismatch:
    """BED-01-TC-03, constraint-level: prove the table-constraint comparison
    isn't a vacuous pass. Deliberately drops the multi-column UniqueConstraint
    from a cloned copy of token_series's table (never the real model's
    `Base.metadata`, which every other test in this session also relies on)
    and asserts `_compare_constraints` flags it as missing.
    """

    def test_deliberate_missing_unique_constraint_is_detected(self) -> None:
        table_name = "token_series"
        real_table = cast(sa.Table, MODELS_BY_TABLENAME[table_name].__table__)
        drift_metadata = sa.MetaData()
        cloned_table = real_table.to_metadata(drift_metadata)

        uq = next(c for c in cloned_table.constraints if isinstance(c, sa.UniqueConstraint))
        cloned_table.constraints.discard(uq)

        mismatches = _compare_constraints(
            table_name, FIXTURE["tables"][table_name]["constraints"], cloned_table
        )

        assert mismatches, (
            "comparison helper failed to detect a deliberately removed UniqueConstraint"
        )
        assert any("missing unique" in m for m in mismatches)


class TestIngestTokensNoRawTokenColumn:
    """BED-01-TC-10: ingest_tokens exposes only token_hash, never a raw token."""

    FORBIDDEN_COLUMN_NAMES = {"token", "raw_token", "plaintext_token", "secret"}

    def test_only_token_hash_present(self) -> None:
        columns = models.IngestToken.__table__.c
        assert "token_hash" in columns
        assert columns["token_hash"].unique is True
        assert self.FORBIDDEN_COLUMN_NAMES.isdisjoint(columns.keys())


class TestTypeMapping:
    """BED-01-TC-12/13/14/15: Prisma -> SQLAlchemy type-mapping rules (PRD §8.4)."""

    @pytest.mark.parametrize(
        "table_name,column_name",
        [
            ("org_summary_rollup", "total_token_consumption"),
            ("token_series", "value"),
        ],
    )
    def test_bigint_fields_map_to_biginteger(self, table_name: str, column_name: str) -> None:
        column = MODELS_BY_TABLENAME[table_name].__table__.c[column_name]
        assert isinstance(column.type, sa.BigInteger)

    @pytest.mark.parametrize(
        "table_name,column_name",
        [
            ("program_summary", "monthly_token_sparkline"),
            ("usage_events", "models"),
        ],
    )
    def test_json_fields_map_to_json_or_jsonb(self, table_name: str, column_name: str) -> None:
        column = MODELS_BY_TABLENAME[table_name].__table__.c[column_name]
        assert isinstance(column.type, (sa.JSON, postgresql.JSONB))

    def test_string_array_field_maps_to_postgresql_array_of_string(self) -> None:
        column = models.IngestToken.__table__.c["allowed_program_ids"]
        assert isinstance(column.type, postgresql.ARRAY)
        assert isinstance(column.type.item_type, sa.String)

    @pytest.mark.parametrize(
        "table_name,column_name",
        [
            ("program_releases", "type"),
            ("program_guardrails", "status"),
        ],
    )
    def test_discriminator_fields_stay_plain_string_no_enum(
        self, table_name: str, column_name: str
    ) -> None:
        column = MODELS_BY_TABLENAME[table_name].__table__.c[column_name]
        assert isinstance(column.type, sa.String)
        assert not isinstance(column.type, postgresql.ENUM)
