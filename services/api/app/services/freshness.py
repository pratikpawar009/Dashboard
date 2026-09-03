"""Read-only accessor for the `system_metadata` ingestion-freshness singleton.

`FreshnessAccessor` wraps a single indexed primary-key read against
`system_metadata` (key='ingestion'), following `app.core.persona_resolver.
PersonaResolver`'s cache shape (D-01, docs/features/BED-04/DECISIONS.md): a
monotonic-clock TTL, a warm fast path with no lock, and an `asyncio.Lock`
-guarded double-check on a cache miss.

No route consumes this module yet -- each downstream dashboard-composition
story (OVW-01, ARC-01, DEV-01, PMD-01, EMD-01) owns constructing/sharing its
own instance via the `freshness-api` contract (docs/requirements/api.md).

No writer exists yet either: `system_metadata.last_successful_run_at` is
never written by any merged story (ING-01 only added ingest-token minting
and bearer auth). AC-4 (a TTL-expiry re-read picks up a new value) is
therefore fixture-verified -- proven by seeding/mutating the row directly in
tests, not by a real ingestion write -- until ING-02 lands the writer
(research risk #1 / R-01, docs/research/BED-04.md).

Row-absent status: raises `HTTPException(status_code=500)` rather than 503.
503 is arguably more semantically correct for "dependency has not produced
data yet", but 500 is chosen for consistency with the existing generic
unhandled-exception handler in `app/core/errors.py`, not because it is more
correct -- a consumer that genuinely needs 503 semantics should escalate
that need explicitly rather than this module silently diverging from the
rest of the API's error shape (BED-04-FR-1, research risk #5 / R-05).

Query timeout (D-04, docs/features/BED-04/DECISIONS.md): the single
`system_metadata` read is bounded by an explicit 3.0s `asyncio.wait_for`,
matching `app.core.persona_resolver.PersonaResolver`'s
`_TIER3_TIMEOUT_SECONDS` -- the read otherwise has no timeout to inherit
(`app.core.db.create_async_engine` sets none: no `connect_args`, no
`command_timeout`, no statement timeout), and this read runs inside
`self._lock`, so an unbounded wait would hang every concurrent caller
sharing the instance, not just the slow one
(`.claude/rules/performance-baseline.md`: "I/O has explicit timeouts. No
silent infinite waits."). On timeout: `HTTPException(status_code=500,
detail=_QUERY_TIMEOUT_MESSAGE)` -- 500, not 503, for the same
consistency-with-`app/core/errors.py` reason as the row-absent path above,
plus a `logger.warning()` on the same PII-free `extra={"reason": ...}`
shape. Never negative-cached: like the row-absent outcome, a timeout is
not written to `self._cached_value`/`self._expiry`, so the next call
re-queries.
"""

import logging
import time
from asyncio import Lock, wait_for
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import SessionLocal
from app.models.ingestion import SystemMetadata

logger = logging.getLogger(__name__)

# D-02: 300s, matching `app.core.persona_resolver._CACHE_TTL_SECONDS` --
# duplicated here rather than imported, since that name is module-private in
# its own module and the two caches share no domain concept beyond an
# incidentally-equal duration (docs/features/BED-04/DECISIONS.md D-02). If
# the two ever need to diverge, each module already owns its own value
# independently -- no coordinated cross-module edit is required.
_CACHE_TTL_SECONDS = 300.0

# D-04: 3.0s, matching `app.core.persona_resolver._TIER3_TIMEOUT_SECONDS` --
# the single indexed read otherwise has no timeout to inherit (`app.core.db`
# constructs its engine with none), so this accessor states its own bound
# rather than relying on one that does not exist. Local and private,
# deliberately not imported -- same rationale as `_CACHE_TTL_SECONDS` above
# (D-02): the two modules share no domain concept beyond an incidentally
# -equal value, and each is free to diverge independently later.
_QUERY_TIMEOUT_SECONDS = 3.0

_NOT_RUN_MESSAGE = "ingestion job may not have run yet"
_QUERY_TIMEOUT_MESSAGE = "ingestion freshness query timed out"


class FreshnessAccessor:
    """Resolves the ingestion freshness timestamp via cache -> one DB read.

    Construction does no I/O (unlike `PersonaResolver`, which loads a Tier-2
    YAML file synchronously) -- there is nothing to load ahead of the first
    call.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        # Injectable so tests can point the read at a disposable test
        # database instead of the dev `SessionLocal` this defaults to
        # (mirrors PersonaResolver's D-06 seam).
        self._session_factory = session_factory or SessionLocal
        self._cached_value: datetime | None = None
        self._expiry: float = 0.0
        self._lock = Lock()

    async def get_last_successful_run(self) -> datetime:
        """Return the ingestion freshness timestamp, consulting the cache first.

        Warm-hit fast path: a non-expired cached value returns without
        acquiring the lock and without emitting any log (REQUIREMENTS.md
        Non-functional requirements, Observability, explicitly declines a
        log on this path to keep it allocation-free against the < 10ms p95
        budget). Miss path: acquire `self._lock`, re-check (a coroutine
        that waited on the lock while another one already resolved this
        call must reuse that result rather than querying again -- this
        bounds a burst of concurrent cold calls to exactly one SELECT),
        then issue one indexed primary-key read bounded by a 3.0s hard
        timeout (D-04, see module docstring) -- a stalled connection must
        not hang every caller sharing this lock.

        Row present: caches `(value, time.monotonic() + _CACHE_TTL_SECONDS)`
        and returns `last_successful_run_at` unchanged -- timezone-aware, no
        reformatting, no `str()` (the `freshness-api` contract pins a raw
        datetime, not a display string).

        Row absent: logs a `_NOT_RUN_MESSAGE` warning (`extra` carries only
        an internal reason code -- no user identifier, email, session id,
        or request content, per the security NFR) and raises
        `HTTPException(status_code=500, detail=_NOT_RUN_MESSAGE)`. Never
        negative-cached (D-03): the row-absent outcome is not written to
        `self._cached_value`/`self._expiry`, so the next call re-queries. A
        fresh ingestion write can land at any moment out-of-process and
        nothing can push an invalidation into this cache, so every
        row-absent call must re-check.

        Query timeout: if the read does not complete within
        `_QUERY_TIMEOUT_SECONDS`, logs a `_QUERY_TIMEOUT_MESSAGE` warning
        (same PII-free `extra` shape as the row-absent path) and raises
        `HTTPException(status_code=500, detail=_QUERY_TIMEOUT_MESSAGE)` --
        a distinct message from `_NOT_RUN_MESSAGE`, since "the DB did not
        answer" is a different outcome from "ingestion has never run"
        (D-04). Also never negative-cached.
        """
        if self._cached_value is not None and time.monotonic() < self._expiry:
            return self._cached_value

        async with self._lock:
            if self._cached_value is not None and time.monotonic() < self._expiry:
                return self._cached_value

            async def _query() -> SystemMetadata | None:
                async with self._session_factory() as session:
                    result = await session.execute(
                        select(SystemMetadata).where(SystemMetadata.key == "ingestion").limit(1)
                    )
                    return result.scalar_one_or_none()

            try:
                row = await wait_for(_query(), timeout=_QUERY_TIMEOUT_SECONDS)
            except TimeoutError as exc:
                logger.warning(
                    _QUERY_TIMEOUT_MESSAGE,
                    extra={"reason": "system_metadata query exceeded 3.0s timeout"},
                )
                raise HTTPException(status_code=500, detail=_QUERY_TIMEOUT_MESSAGE) from exc

            if row is None:
                logger.warning(
                    _NOT_RUN_MESSAGE,
                    extra={"reason": "system_metadata row not found"},
                )
                raise HTTPException(status_code=500, detail=_NOT_RUN_MESSAGE)

            self._cached_value = row.last_successful_run_at
            self._expiry = time.monotonic() + _CACHE_TTL_SECONDS
            return self._cached_value
