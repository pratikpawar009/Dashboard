"""Async SQLAlchemy session factory (D-02: module-level singleton, no per-request engine).

`engine`/`SessionLocal` are constructed once at import time — Python's import
caching guarantees a process-wide singleton. `app.main` imports `engine` from
here at module level (alongside its existing `configure_logging()` import-time
pattern) so the engine is built deterministically at app boot, and disposes it
on shutdown. Every DB-touching module must obtain a session via `get_db()` /
`SessionLocal`, never construct its own engine (see postgres-patterns skill).
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(settings.database_url)
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield a request-scoped `AsyncSession` from the shared engine."""
    async with SessionLocal() as session:
        yield session
