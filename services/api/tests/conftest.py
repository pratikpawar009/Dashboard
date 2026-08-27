"""Shared fixtures for tests needing a live, disposable test Postgres database.

Fixtures only — no test functions live here. Consumed by `tests/test_migrations.py`
(and any `tests/test_models.py` case that needs a live DB).

Test-DB URL convention (T-10): no existing convention was found in
`app.core.config.Settings` or `.env.example` (both declare only `DATABASE_URL`,
pointed at the local dev database) — this establishes one:

- `TEST_DATABASE_URL` env var wins if set (CI / custom local setups).
- Otherwise the test DB is derived from `settings.database_url` by suffixing
  its database name with `_test` (e.g. `.../dashboard` -> `.../dashboard_test`),
  keeping host/port/user/password identical to local dev. This never points at
  the dev database itself, so a test run cannot clobber dev data.

Alembic invocation: programmatic, via `alembic.command.upgrade`/`downgrade`
against a constructed `alembic.config.Config` — never a shelled-out `alembic`
CLI subprocess (matches this project's existing async, in-process migration
runner in `migrations/env.py`; see alembic-patterns skill).

Gotcha this file works around: `migrations/env.py` reads its connection URL
from `app.core.config.settings.database_url` directly
(`config.set_main_option("sqlalchemy.url", settings.database_url)`,
`migrations/env.py:20`) rather than from the `Config` object passed to
`alembic.command.*`. Setting `sqlalchemy.url` on our own `Config` instance
alone would therefore be silently overridden back to the dev DB by `env.py`.
`AlembicRunner` below works around this by monkeypatching the shared
`settings.database_url` singleton for the duration of each upgrade/downgrade
call and restoring it in a `finally`, rather than duplicating/forking `env.py`'s
URL-resolution logic here.

Fixture scoping choice (documented per research's caveat — no pre-existing
pytest convention in this repo to follow, see pytest-patterns skill): the
`migrated_db` fixture is function-scoped and runs a full `upgrade head` /
`downgrade base` around every test, rather than a session-scoped schema with
per-test truncation. This story's schema is small (18 tables) and
`test_migrations.py`'s subject under test IS the migration's up/down
correctness (round-trip, `alembic check` zero-diff) — a shared, once-migrated
session-scoped schema would hide exactly the bugs those tests exist to catch.
The cost (each test pays a full upgrade+downgrade) is acceptable at this table
count.
"""

import os
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest
import pytest_asyncio
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

API_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = API_ROOT / "alembic.ini"


def _derive_test_database_url() -> str:
    """Resolve the disposable test-DB URL per the module docstring's convention."""
    override = os.environ.get("TEST_DATABASE_URL")
    if override:
        return override
    parts = urlsplit(settings.database_url)
    if not parts.path or parts.path == "/":
        raise RuntimeError(
            "settings.database_url has no database name to derive a "
            f"'_test' suffix from: {settings.database_url!r}"
        )
    test_path = f"{parts.path}_test"
    return urlunsplit((parts.scheme, parts.netloc, test_path, parts.query, parts.fragment))


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Disposable test-DB URL — never the dev DB. See module docstring."""
    return _derive_test_database_url()


@pytest.fixture(scope="session")
def alembic_config() -> AlembicConfig:
    """Programmatic Alembic `Config`, pointed at this project's `alembic.ini`.

    `script_location` resolves via `alembic.ini`'s own `%(here)s` token
    (Alembic >=1.13, pinned in `pyproject.toml`) — no override needed here.
    """
    return AlembicConfig(str(ALEMBIC_INI))


def _run_in_thread(fn: Any, *args: Any) -> None:
    """Run a sync callable in a fresh worker thread and propagate its result.

    `migrations/env.py`'s online path calls `asyncio.run(...)` internally
    (`run_migrations_online`, `migrations/env.py:83`). That's fine when
    `alembic.command.upgrade`/`downgrade` is invoked during plain sync pytest
    fixture setup/teardown (no event loop running yet) — but `test_migrations.py`
    also needs to call `migrated_db.upgrade`/`.downgrade` directly from inside
    `async def` test bodies (e.g. the round-trip / broken-downgrade meta-tests),
    where pytest-asyncio already has a loop running on the current thread and
    `asyncio.run()` raises `RuntimeError: asyncio.run() cannot be called from a
    running event loop`. Running the alembic call in its own worker thread
    sidesteps this unconditionally, in both call contexts, since a fresh thread
    never has a running loop of its own. `ThreadPoolExecutor.submit(...).result()`
    blocks the caller until the worker finishes and re-raises any exception.
    """
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(fn, *args).result()


@dataclass
class AlembicRunner:
    """Programmatic `alembic upgrade`/`downgrade` against the disposable test DB.

    See module docstring for why `settings.database_url` is monkeypatched
    around each call rather than set on `config` alone, and `_run_in_thread`
    for why the call is dispatched to a worker thread.
    """

    config: AlembicConfig
    database_url: str

    def upgrade(self, revision: str = "head") -> None:
        original = settings.database_url
        settings.database_url = self.database_url
        try:
            _run_in_thread(alembic_command.upgrade, self.config, revision)
        finally:
            settings.database_url = original

    def downgrade(self, revision: str = "base") -> None:
        original = settings.database_url
        settings.database_url = self.database_url
        try:
            _run_in_thread(alembic_command.downgrade, self.config, revision)
        finally:
            settings.database_url = original


@pytest.fixture(scope="session")
def alembic_runner(alembic_config: AlembicConfig, test_database_url: str) -> AlembicRunner:
    """Session-scoped runner — cheap to construct, safe to reuse across tests."""
    return AlembicRunner(config=alembic_config, database_url=test_database_url)


@pytest.fixture
def migrated_db(alembic_runner: AlembicRunner) -> Iterator[AlembicRunner]:
    """Function-scoped: `upgrade head` before the test, `downgrade base` after.

    Yields the `alembic_runner` so a test can also drive `upgrade`/`downgrade`
    directly mid-test (e.g. round-trip or broken-downgrade meta-tests) without
    losing the guaranteed teardown.
    """
    alembic_runner.upgrade("head")
    try:
        yield alembic_runner
    finally:
        alembic_runner.downgrade("base")


@pytest_asyncio.fixture(scope="session")
async def test_engine(test_database_url: str) -> AsyncIterator[AsyncEngine]:
    """Session-scoped async SQLAlchemy engine against the disposable test DB.

    Does not run migrations itself — pair with `migrated_db` in tests that
    need a live schema before querying/inserting through this engine.
    """
    engine = create_async_engine(test_database_url)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def test_session(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Function-scoped `AsyncSession` bound to `test_engine`."""
    session_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
