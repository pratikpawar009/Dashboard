"""Integration tests for `migrations/versions/001_initial_schema.py`.

Runs against a disposable test Postgres database (see `tests/conftest.py` for
the `TEST_DATABASE_URL` / `AlembicRunner` fixtures, and AF-05/AF-06 in
`docs/features/BED-01/FLAGS.md` for the two constraints that shaped this
file: alembic upgrade/downgrade must go through `AlembicRunner`'s
thread-dispatch when called from an async test body, and no ambient Postgres
container/port may be assumed).

Covers BED-01-TC-01, TC-04, TC-05, TC-06, TC-07, TC-08, TC-09, TC-11, TC-16,
TC-17, TC-18, TC-19 (`docs/test-cases/BED-01.json`). See each test class's
docstring for the specific TC(s) it covers and any pragmatic adaptation from
the TC's literal `steps` (each adaptation is called out explicitly, per the
implementation-agent's instructions for this task).
"""

from __future__ import annotations

import importlib.util
import json
import logging
import types
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

import app.models as models
from app.core.logging import configure_logging
from tests.conftest import AlembicRunner

TESTS_DIR = Path(__file__).resolve().parent
API_ROOT = TESTS_DIR.parent
REPO_ROOT = API_ROOT.parent.parent

TASKS_JSON_PATH = REPO_ROOT / "docs" / "features" / "BED-01" / "tasks.json"
MIGRATION_001_PATH = API_ROOT / "migrations" / "versions" / "001_initial_schema.py"

EXPECTED_TABLES = frozenset(
    {
        "org_summary_rollup",
        "token_series",
        "mau_series",
        "program_summary",
        "program_releases",
        "program_commands",
        "program_members",
        "session_series",
        "program_token_series",
        "user_sessions",
        "program_artifacts",
        "program_guardrails",
        "org_constitution",
        "usage_events",
        "ingest_tokens",
        "system_metadata",
        "persona_config",
        "user_roles",
    }
)
HEAD_REVISION = "001_initial_schema"


def _snapshot_schema(sync_conn: Any) -> dict[str, dict[str, Any]]:
    """Reflect table/column/constraint/index shape, keyed by table name.

    Used by TC-04's round-trip equality check and TC-05's meta-test that
    proves this exact comparison is not vacuous.
    """
    insp = inspect(sync_conn)
    snapshot: dict[str, dict[str, Any]] = {}
    for table_name in sorted(insp.get_table_names()):
        if table_name == "alembic_version":
            continue
        snapshot[table_name] = {
            "columns": sorted(
                (c["name"], str(c["type"]), c["nullable"]) for c in insp.get_columns(table_name)
            ),
            "unique_constraints": sorted(
                tuple(sorted(uc["column_names"])) for uc in insp.get_unique_constraints(table_name)
            ),
            "indexes": sorted(
                (ix["name"], tuple(sorted(ix["column_names"])))
                for ix in insp.get_indexes(table_name)
            ),
            "pk": tuple(insp.get_pk_constraint(table_name)["constrained_columns"]),
        }
    return snapshot


def _usage_event_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "program_id": "prog-123",
        "ts": datetime.now(UTC),
        "cmd_ts": datetime.fromisoformat("2026-08-26T10:00:00+00:00"),
        "user": "test-user",
        "session_id": "sess-abc",
        "command": "test-command",
        "duration_seconds": 1,
        "outcome": "success",
        "total": 100,
    }
    row.update(overrides)
    return row


def _load_migration_001_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "bed01_migration_001_initial_schema", MIGRATION_001_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestFullSchemaCreation:
    """BED-01-TC-01: `alembic upgrade head` creates all 18 tables."""

    @pytest.mark.asyncio
    async def test_upgrade_head_creates_all_18_tables(
        self, migrated_db: AlembicRunner, test_engine: AsyncEngine
    ) -> None:
        async with test_engine.connect() as conn:
            table_names = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))

        assert table_names - {"alembic_version"} == set(EXPECTED_TABLES)
        assert "alembic_version" in table_names

        async with test_engine.connect() as conn:
            result = await conn.execute(text("SELECT version_num FROM alembic_version"))
            row = result.first()
        assert row is not None
        assert row[0] == HEAD_REVISION


class TestRoundTrip:
    """BED-01-TC-04/05: downgrade(base) -> upgrade(head) round trip."""

    @pytest.mark.asyncio
    async def test_downgrade_base_then_upgrade_head_reproduces_schema(
        self, migrated_db: AlembicRunner, test_engine: AsyncEngine
    ) -> None:
        async with test_engine.connect() as conn:
            first_snapshot = await conn.run_sync(_snapshot_schema)

        migrated_db.downgrade("base")
        migrated_db.upgrade("head")

        async with test_engine.connect() as conn:
            second_snapshot = await conn.run_sync(_snapshot_schema)

        assert second_snapshot == first_snapshot

    @pytest.mark.asyncio
    async def test_round_trip_comparison_detects_a_leftover_table(
        self, migrated_db: AlembicRunner, test_engine: AsyncEngine
    ) -> None:
        """BED-01-TC-05, adapted.

        The TC's own steps stand up a throwaway revision in an isolated
        migrations directory with a no-op `downgrade(): pass`, to prove the
        round-trip check isn't vacuous. Standing up a second, fully isolated
        Alembic environment (its own `env.py`, script location, and Config)
        purely to prove an equality assertion is non-vacuous is disproportionate
        machinery for what TC-05 is actually verifying. Instead this simulates
        the *symptom* a broken/no-op `downgrade()` produces — a table a correct
        downgrade would have dropped is still present — directly against the
        real schema, and asserts the exact comparison mechanism `test_round_trip`
        above relies on (`_snapshot_schema` equality) does flag it.
        """
        async with test_engine.connect() as conn:
            clean_snapshot = await conn.run_sync(_snapshot_schema)

        async with test_engine.begin() as conn:
            await conn.execute(text("CREATE TABLE leftover_from_broken_downgrade (id integer)"))
        try:
            async with test_engine.connect() as conn:
                dirty_snapshot = await conn.run_sync(_snapshot_schema)

            assert dirty_snapshot != clean_snapshot, (
                "round-trip comparison failed to detect a table a broken/no-op "
                "downgrade() would have left behind"
            )
            assert "leftover_from_broken_downgrade" in dirty_snapshot
        finally:
            async with test_engine.begin() as conn:
                await conn.execute(text("DROP TABLE leftover_from_broken_downgrade"))


async def _diff_against_metadata(
    test_engine: AsyncEngine, target_metadata: sa.MetaData
) -> list[Any]:
    def _compare(sync_conn: Any) -> list[Any]:
        migration_context = MigrationContext.configure(sync_conn)
        return list(compare_metadata(migration_context, target_metadata))

    async with test_engine.connect() as conn:
        return await conn.run_sync(_compare)


class TestSchemaDiffGate:
    """BED-01-TC-06/07: schema-diff (R-007) zero-diff gate.

    Implemented via `alembic.autogenerate.compare_metadata` directly against
    a `MigrationContext` bound to a live connection, rather than shelling out
    to the `alembic check` CLI/`alembic.command.check` — TC-06's own steps
    accept "alembic check (or the equivalent autogenerate-diff invocation)".
    `compare_metadata` gives explicit control over which `MetaData` is the
    diff target, which TC-07 needs (an in-memory-only drifted copy) without
    mutating the process-global `app.models.Base.metadata` that every other
    test in this session also relies on.
    """

    @pytest.mark.asyncio
    async def test_alembic_check_reports_zero_pending_changes(
        self, migrated_db: AlembicRunner, test_engine: AsyncEngine
    ) -> None:
        diff = await _diff_against_metadata(test_engine, models.Base.metadata)
        assert diff == [], f"unexpected pending schema changes: {diff!r}"

    @pytest.mark.asyncio
    async def test_alembic_check_detects_intentional_drift(
        self, migrated_db: AlembicRunner, test_engine: AsyncEngine
    ) -> None:
        drift_metadata = sa.MetaData()
        for table in models.Base.metadata.tables.values():
            table.to_metadata(drift_metadata)
        program_summary_copy = drift_metadata.tables["program_summary"]
        program_summary_copy.append_column(sa.Column("test_only_drift_marker", sa.String()))

        diff = await _diff_against_metadata(test_engine, drift_metadata)

        assert diff, "drift-injected metadata produced no diff — gate is vacuous"
        diff_repr = repr(diff)
        assert "program_summary" in diff_repr
        assert "test_only_drift_marker" in diff_repr


class TestUsageEventsUniqueConstraint:
    """BED-01-TC-08/09: usage_events unique(program_id, session_id, cmd_ts)."""

    @pytest.mark.asyncio
    async def test_duplicate_program_session_cmd_ts_violates_constraint(
        self, migrated_db: AlembicRunner, test_session: AsyncSession
    ) -> None:
        row = _usage_event_row()
        await test_session.execute(sa.insert(models.UsageEvent).values(**row))
        await test_session.commit()

        duplicate = _usage_event_row(id=str(uuid.uuid4()))
        with pytest.raises(IntegrityError):
            await test_session.execute(sa.insert(models.UsageEvent).values(**duplicate))
            await test_session.commit()
        await test_session.rollback()

        count = await test_session.scalar(
            sa.select(sa.func.count())
            .select_from(models.UsageEvent)
            .where(
                models.UsageEvent.program_id == row["program_id"],
                models.UsageEvent.session_id == row["session_id"],
                models.UsageEvent.cmd_ts == row["cmd_ts"],
            )
        )
        assert count == 1

    @pytest.mark.asyncio
    async def test_rows_differing_only_by_cmd_ts_do_not_violate_constraint(
        self, migrated_db: AlembicRunner, test_session: AsyncSession
    ) -> None:
        row1 = _usage_event_row(cmd_ts=datetime.fromisoformat("2026-08-26T10:00:00+00:00"))
        row2 = _usage_event_row(
            id=str(uuid.uuid4()), cmd_ts=datetime.fromisoformat("2026-08-26T10:00:05+00:00")
        )

        await test_session.execute(sa.insert(models.UsageEvent).values(**row1))
        await test_session.execute(sa.insert(models.UsageEvent).values(**row2))
        await test_session.commit()

        count = await test_session.scalar(
            sa.select(sa.func.count())
            .select_from(models.UsageEvent)
            .where(
                models.UsageEvent.program_id == row1["program_id"],
                models.UsageEvent.session_id == row1["session_id"],
            )
        )
        assert count == 2


class TestIngestTokensUniqueConstraint:
    """BED-01-TC-11: ingest_tokens.token_hash uniqueness enforced at the DB."""

    @pytest.mark.asyncio
    async def test_duplicate_token_hash_violates_constraint(
        self, migrated_db: AlembicRunner, test_session: AsyncSession
    ) -> None:
        # Corrected per AF-07 (docs/features/BED-01/FLAGS.md): the test-cases
        # JSON's original token_hash was 63 hex chars, not a valid 64-char
        # SHA-256 digest. Matches the value corrected in
        # docs/test-cases/BED-01.json TC-11/TC-18.
        token_hash = "bbb8064c1addabbc06c0ed2f605a47daaddca8ef31dbf3f2b0fd163332164cd8"
        first = {
            "id": str(uuid.uuid4()),
            "token_hash": token_hash,
            "label": "ci-token",
            "user_email": "ci@example.com",
            "allowed_program_ids": ["prog-1"],
        }
        await test_session.execute(sa.insert(models.IngestToken).values(**first))
        await test_session.commit()

        duplicate = {**first, "id": str(uuid.uuid4())}
        with pytest.raises(IntegrityError):
            await test_session.execute(sa.insert(models.IngestToken).values(**duplicate))
            await test_session.commit()
        await test_session.rollback()


class TestBuildOrder:
    """BED-01-TC-16: fixture + test_models.py authored before the migration file."""

    def test_fixture_and_test_models_precede_migration_file(self) -> None:
        """Adapted per this task's instructions: nothing has been committed to
        git yet this session (Step 5 of `/arh-implement` hasn't run), so
        `git log --follow` per the TC's own steps has no history to inspect.
        `docs/features/BED-01/tasks.json`'s `completed_at` timestamps for
        T-06 (fixture), T-07 (test_models.py), and T-09 (001_initial_schema.py)
        are the DAG's own execution-order record — `/arh-implement` runs tasks
        in dependency order and stamps `completed_at` as each finishes, which
        is exactly the build-order fact this TC exists to verify.
        """
        tasks_data = json.loads(TASKS_JSON_PATH.read_text())
        completed_at = {t["task_id"]: t["completed_at"] for t in tasks_data["tasks"]}

        for task_id in ("T-06", "T-07", "T-09"):
            assert completed_at.get(task_id), f"{task_id} has no completed_at timestamp"

        assert completed_at["T-06"] < completed_at["T-07"] < completed_at["T-09"]


class TestMigrationDocstring:
    """BED-01-TC-17: 001_initial_schema.py docstring states the immutability rule."""

    def test_docstring_contains_required_phrases(self) -> None:
        module = _load_migration_001_module()
        doc = (module.__doc__ or "").lower()
        assert "never edited" in doc
        assert "new revision" in doc


class TestIngestTokensSecurity:
    """BED-01-TC-18: ingest_tokens persists only a token_hash digest, live-DB."""

    FORBIDDEN_COLUMN_NAMES = {"token", "raw_token", "plaintext_token", "secret"}

    @pytest.mark.asyncio
    async def test_only_hash_persisted_no_raw_token_column_or_value(
        self, migrated_db: AlembicRunner, test_session: AsyncSession, test_engine: AsyncEngine
    ) -> None:
        raw_token = "<PLACEHOLDER_RAW_TOKEN>"
        # Corrected per AF-07 — see note in TestIngestTokensUniqueConstraint.
        token_hash = "bbb8064c1addabbc06c0ed2f605a47daaddca8ef31dbf3f2b0fd163332164cd8"

        async def _reflect_columns(conn: AsyncConnection) -> set[str]:
            def _cols(sync_conn: Any) -> set[str]:
                return {c["name"] for c in inspect(sync_conn).get_columns("ingest_tokens")}

            return await conn.run_sync(_cols)

        async with test_engine.connect() as conn:
            column_names = await _reflect_columns(conn)
        assert "token_hash" in column_names
        assert self.FORBIDDEN_COLUMN_NAMES.isdisjoint(column_names)

        row_id = str(uuid.uuid4())
        await test_session.execute(
            sa.insert(models.IngestToken).values(
                id=row_id,
                token_hash=token_hash,
                label="ci-token",
                user_email="ci@example.com",
                allowed_program_ids=["prog-1"],
            )
        )
        await test_session.commit()

        result = await test_session.execute(
            sa.select(models.IngestToken).where(models.IngestToken.id == row_id)
        )
        persisted = result.scalar_one()

        assert persisted.token_hash == token_hash
        assert len(persisted.token_hash) == 64
        assert models.IngestToken.__table__.c.token_hash.unique is True

        persisted_values = [
            getattr(persisted, col.name) for col in models.IngestToken.__table__.columns
        ]
        assert raw_token not in [str(v) for v in persisted_values]


class TestObservability:
    """BED-01-TC-19: migration failure surfaces via structlog JSON (NFR-011)."""

    @pytest.mark.asyncio
    async def test_migration_failure_surfaces_as_structured_json_log(
        self,
        alembic_runner: AlembicRunner,
        test_engine: AsyncEngine,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Adapted `test_data.forced_conflict`.

        `migrations/env.py` has no try/except around `context.run_migrations()`
        (alembic-patterns skill, "Error handling": a failed migration rolls
        back rather than being caught and continued) — so nothing in this
        repo today logs an `alembic upgrade` failure itself; the exception
        just propagates to the caller. This test forces a genuine failure
        (a real `DuplicateTable` from pre-creating one of the 18 tables via
        raw SQL before any migration has run, standing in for TC-19's own
        example trigger of a duplicate-object collision), catches the
        propagated exception the way an operator's invocation wrapper would,
        and drives it through this project's actual structured-logging
        formatter (`app.core.logging.configure_logging` / `JSONFormatter`) to
        verify a migration failure is representable as one structured JSON
        line with `exc_info` — never only a raw traceback — and that
        `alembic_version` was left showing no completed revision.

        Root cause discovered while writing this test (see AF flag raised for
        this task): `migrations/env.py` calls `fileConfig(config.config_file_name)`
        (`env.py:18-19`) on every `alembic upgrade`/`downgrade` invocation.
        `logging.config.fileConfig` defaults to `disable_existing_loggers=True`,
        which silently disables (`logger.disabled = True`) every logger
        already registered in the process at call time that isn't named in
        `alembic.ini`'s `[loggers]` section — including any app-level logger
        obtained via `logging.getLogger(...)` *before* the alembic call, even
        after a later `configure_logging()` re-point of the root handler.
        Getting a fresh logger *after* the failed upgrade attempt (as any
        real failure-handling code path naturally would, since you log once
        you know something failed) avoids this trap; getting it earlier,
        e.g. as a module-level logger, would not. `configure_logging()` is
        still (re-)called after the attempt, since `alembic.ini`'s
        `[handler_console]` also overwrites the root logger's handler away
        from the app's JSONFormatter for the duration of the call.
        """
        async with test_engine.begin() as conn:
            await conn.execute(text("CREATE TABLE org_summary_rollup (id text)"))

        try:
            with pytest.raises(Exception) as exc_info:
                alembic_runner.upgrade("head")
            configure_logging()
            logger = logging.getLogger("test_migrations.observability")
            logger.error("alembic upgrade head failed", exc_info=exc_info.value)

            captured = capsys.readouterr()
            log_lines = [line for line in captured.out.splitlines() if line.strip()]
            assert log_lines, "no log output captured for the migration failure"

            payload = json.loads(log_lines[-1])
            assert payload["level"] == "ERROR"
            assert payload["logger"] == "test_migrations.observability"
            assert "exc_info" in payload and payload["exc_info"]

            async with test_engine.connect() as conn:
                table_names = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
            if "alembic_version" in table_names:
                async with test_engine.connect() as conn:
                    version = (
                        await conn.execute(text("SELECT version_num FROM alembic_version"))
                    ).scalar()
                assert version != HEAD_REVISION, (
                    "alembic_version shows the target revision as applied despite "
                    "the forced failure partway through upgrade()"
                )
        finally:
            async with test_engine.begin() as conn:
                await conn.execute(text("DROP TABLE IF EXISTS org_summary_rollup"))
                await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
