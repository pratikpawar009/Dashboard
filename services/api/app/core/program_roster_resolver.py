"""Single-tier program-membership resolver: `program_roster` -> `session.programs`.

`ProgramRosterResolver` maps a session's verified `email` claim onto the distinct
set of `program_id`s that email is rostered into. `get_current_user`
(`app/core/auth.py`) consults it on every non-dev-bypass session construction
(AUTH-06-AC-1/AC-2/AC-3, FR-1). `program_roster` (ING-10, file-authoritative,
ADR-0010) is the ONLY table read -- `program_members` (rebuilt from
`usage_events` on every activity ingest) and `user_roles` (ING-08 AC-4:
reference/audit only) are never consulted on this path (AC-9).

Precedent: this mirrors `app/core/persona_resolver.py`'s `PersonaResolver`
(AUTH-02), the in-repo pattern FR-2 names -- same 300s TTL, same
`time.monotonic()` clock, same `asyncio.Lock` double-checked re-read on the miss
path, same 3.0s `asyncio.wait_for` query bound, same PII-free structured log
event. Two deliberate differences:

- Single tier. No env/YAML/Postgres fallthrough: one query, one source of truth.
  A zero-row result is a legitimate answer (`[]`, AC-2), not a fail-closed miss
  -- so there is no analogue of `PersonaNotFoundError`.
  `ProgramRosterResolutionError` signals only that resolution could not COMPLETE.
- No `session_factory` (D-01). The `AsyncSession` is a per-call argument, not
  resolver state. `resolve()` runs on the critical path of every authenticated
  request, where `get_current_user` already holds a `Depends(get_db)` session;
  taking it as an argument keeps the existing `app.dependency_overrides[get_db]`
  test convention transparently correct for the roster query too. The resolver
  itself holds only the cache dict and its lock.

Cache scope: per-worker, in-process only -- one instance lives on
`app.state.program_roster_resolver` per FastAPI app/Uvicorn worker (no Redis in
the stack; same trade-off as `PersonaResolver` and AUTH-01's `JwksCache`).

TTL expiry is the SOLE invalidating event (300s, per email, per worker). There
is deliberately no write-triggered invalidation: a roster re-push via ING-10's
`POST /api/ingest/manifest` does not signal this cache in any way, so a
membership change stays invisible to an already-warm worker until that worker's
own next expiry. An app restart (which flushes every worker at once) is the only
faster lever, and is the documented ops procedure (README.md). Accepted
limitation, not an oversight -- research Risk #2 / Condition 3; a
push-invalidation hook from the ingest endpoint is out of AUTH-06's scope.

PII invariant: `email` is PII (`.claude/rules/security-baseline.md`). The only
structured log event this module emits, `program_membership_resolved`, carries
an exact 3-field allowlist -- `{tier, program_count, timestamp}` -- never the
email it resolved and never the resolved `program_id` list (FR-2, NFR-security).
`ProgramRosterResolutionError` carries no email in its message either, since
exception text reaches logs.

TTL clock: `time.monotonic()`, not wall-clock -- a system clock adjustment must
not affect cache freshness (same rationale as `PersonaResolver`).
"""

import logging
import time
from asyncio import Lock, wait_for
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.roster import ProgramRoster

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 300.0
_QUERY_TIMEOUT_SECONDS = 3.0

_TIER_CACHE_HIT = "cache_hit"
_TIER_DB_QUERY = "db_query"


class ProgramRosterResolutionError(Exception):
    """Raised when the roster lookup could not complete (e.g. a query timeout).

    Not raised for a zero-row result: no roster row for an email is a valid
    answer (`[]`, AC-2), not a failure. Deliberately carries no `email` --
    exception text reaches logs, and email is PII.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class ProgramRosterResolver:
    """Resolves a session email to its distinct, non-removed `program_id` list.

    Construction does no I/O and takes no arguments (unlike `PersonaResolver`,
    which reads its Tier-2 YAML in `__init__`) -- safe to construct
    unconditionally, once per app/worker, in `create_app()`.
    """

    def __init__(self) -> None:
        # {email: (program_ids, expiry_ts)} guarded by an asyncio.Lock alone --
        # no threading.Lock: every access is on the single event loop and there
        # is no synchronous call site to share a thread lock with (mirrors
        # PersonaResolver's D-04 rationale).
        self._cache: dict[str, tuple[list[str], float]] = {}
        self._lock = Lock()

    async def resolve(self, email: str, db: AsyncSession) -> list[str]:
        """Return the distinct non-removed `program_id`s rostered to `email`.

        Fast path: a warm, non-expired cache entry returns without acquiring
        the lock or touching the database, logging `tier=cache_hit`. Miss path:
        acquire the lock, then re-check the cache -- a coroutine that waited on
        the lock while another one already resolved this email must reuse that
        result, not query again; this double-checked re-read is what bounds a
        burst of concurrent cold calls for the same email to exactly one
        `program_roster` query (FR-2).

        `tier` reports which path served THIS call, not whether a query ran on
        it: every call that reaches the lock reports `db_query`, including a
        waiter served by the double-checked re-read. So two coalesced callers
        both log `db_query` while issuing one query between them -- deliberate,
        so the event answers "did this session construction take the fast
        path?", the question the cache exists to make true.

        Only a successful resolution is cached; a raise is never
        negative-cached. Returns a copy of the cached list, never the cached
        list itself -- `CurrentUser` is a plain dataclass (no validating copy),
        so handing out the live object would let any downstream mutation of
        `session.programs` silently rewrite every later session for that email.
        """
        cached = self._cache.get(email)
        if cached is not None and time.monotonic() < cached[1]:
            self._log_resolution(_TIER_CACHE_HIT, len(cached[0]))
            return list(cached[0])

        async with self._lock:
            cached = self._cache.get(email)
            if cached is not None and time.monotonic() < cached[1]:
                program_ids = cached[0]
            else:
                program_ids = await self._resolve_uncached(email, db)
                self._cache[email] = (program_ids, time.monotonic() + _CACHE_TTL_SECONDS)

        self._log_resolution(_TIER_DB_QUERY, len(program_ids))
        return list(program_ids)

    async def _resolve_uncached(self, email: str, db: AsyncSession) -> list[str]:
        """Run the roster read under a 3.0s hard timeout (FR-2), translating a stall.

        `wait_for` cancels the read on timeout, so the caller's request-scoped
        session may be left mid-statement -- acceptable: the raise propagates
        out of `get_current_user` and `get_db`'s context manager tears that
        session down with the request. Nothing here retries: an unbounded or
        unbudgeted retry on the auth critical path is exactly what
        `.claude/rules/performance-baseline.md` forbids.
        """
        try:
            return await wait_for(self._query_roster(email, db), timeout=_QUERY_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            raise ProgramRosterResolutionError("program_roster query timeout after 3.0s") from exc

    async def _query_roster(self, email: str, db: AsyncSession) -> list[str]:
        """The single query (FR-1), unbounded on its own -- callers wrap it in a timeout.

        `SELECT DISTINCT program_id FROM program_roster WHERE email = :email AND
        removed_at IS NULL` -- one round trip on `ix_program_roster_email`. The
        `removed_at IS NULL` predicate is AC-3: a soft-deleted row is excluded
        even when the same email still holds a live row for another program.
        Alias identities need no special handling (AC-1) -- ING-10 writes one
        `program_roster` row per alias, so the equality match covers them.
        """
        result = await db.execute(
            select(distinct(ProgramRoster.program_id)).where(
                ProgramRoster.email == email,
                ProgramRoster.removed_at.is_(None),
            )
        )
        return list(result.scalars().all())

    def _log_resolution(self, tier: str, program_count: int) -> None:
        """Emit `program_membership_resolved` (FR-2). Field allowlist is exact.

        `{tier, program_count, timestamp}` and nothing else: no `email`, no
        `program_id` list. This is a security requirement (NFR-security,
        `.claude/rules/security-baseline.md`), not a style choice -- do not add
        request-scoped context here.

        The `timestamp` passed here is inert, as in `PersonaResolver` (D-08):
        `JSONFormatter` writes its own `timestamp` key first and never lets an
        `extra` overwrite an existing payload key. Emitted literally anyway, per
        the shape FR-2 specifies.
        """
        logger.info(
            "program_membership_resolved",
            extra={
                "tier": tier,
                "program_count": program_count,
                "timestamp": datetime.now(UTC).isoformat() + "Z",
            },
        )


def get_program_roster_resolver(request: Request) -> ProgramRosterResolver:
    """FastAPI dependency returning the per-app `ProgramRosterResolver`.

    `create_app` constructs exactly one instance per app and assigns it to
    `app.state.program_roster_resolver`; consumers reach it via
    `Depends(get_program_roster_resolver)`, never a module global (mirrors
    `get_persona_resolver`).
    """
    return request.app.state.program_roster_resolver
