"""Async SQLAlchemy session factory (D-02: module-level singleton, no per-request engine).

`engine`/`SessionLocal` are constructed once at import time — Python's import
caching guarantees a process-wide singleton. `app.main` imports `engine` from
here at module level (alongside its existing `configure_logging()` import-time
pattern) so the engine is built deterministically at app boot, and disposes it
on shutdown. Every DB-touching module must obtain a session via `get_db()` /
`SessionLocal`, never construct its own engine (see postgres-patterns skill).

I/O bounds (BED-05-AC-7, DECISIONS.md D-02/D-03): the engine sets an explicit
statement timeout and connect timeout, replacing the bare `create_async_engine`
that set none -- no `connect_args`, no `command_timeout`, no statement timeout.
`.claude/rules/performance-baseline.md` requires that every I/O have an explicit
timeout, and an unbounded rollup rebuild is an unbounded hold on a pooled
connection. This also closes the gap `app.services.freshness` documents at its
module level, which had to reach for a call-site `asyncio.wait_for` precisely
because there was no engine-level bound to inherit.

Both values are hardcoded module constants rather than `Settings`/env fields
(D-03): they are properties of the schema and the query shapes, not of a
deployment, and an operator retuning them without re-measuring is more likely
to mask a regression than to fix one.

Derivation of `_STATEMENT_TIMEOUT_MS` (D-02 -- measured, not guessed; earlier
phases deliberately refused to invent it before the aggregation rewrite
existed):

- The slowest *individual* statement in the worst-case rebuild is **97.9ms** --
  a chunked `user_sessions` INSERT during `rebuild_program_rollups` against a
  program holding 40,000 `usage_events` rows. The rebuild's multi-second total
  is the sum of many such chunked writes, not one long statement, so a
  statement bound does not need to be seconds long. 5,000ms leaves ~51x
  headroom over that worst case: generous enough that a legitimate statement
  will not trip it, tight enough to catch a genuinely hung one.
- It sits deliberately *above* `freshness`'s existing 3.0s call-site
  `asyncio.wait_for`, so that tighter bound still fires first on that path.
  Ordering them the other way would make the engine pre-empt a call-site
  timeout the caller chose on purpose, and produce two competing exceptions for
  one slow query (research risk #8).
- Alembic is unaffected: `migrations/env.py` builds its own engine via
  `async_engine_from_config` and never imports this one, so a long
  `CREATE INDEX` cannot trip this bound (research risk #3's worst case).
  `tests/conftest.py` likewise constructs its own engine, so the test suite
  does not inherit this timeout either.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# BED-05-AC-7 / D-02: see module docstring for the measurement these come from.
_STATEMENT_TIMEOUT_MS = 5_000
_CONNECT_TIMEOUT_S = 10

engine = create_async_engine(
    settings.database_url,
    connect_args={
        "options": f"-c statement_timeout={_STATEMENT_TIMEOUT_MS}",
        "connect_timeout": _CONNECT_TIMEOUT_S,
    },
)
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield a request-scoped `AsyncSession` from the shared engine."""
    async with SessionLocal() as session:
        yield session
