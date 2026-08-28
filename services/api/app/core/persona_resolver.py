"""Three-tier persona resolver: env override -> YAML override -> Postgres system-of-record.

`PersonaResolver` maps an IdP `role` claim onto one of the product personas,
consulted by downstream RBAC checks (AUTH-03) and the persona-header UI
(SHP-01). Tier-1 (`Settings.persona_role_map`, `PERSONA_ROLE_MAP` env JSON)
and Tier-2 (this module's Tier-2 YAML file) are operator-editable override
layers; Tier-3 (`app.models.ingestion.PersonaConfig` in Postgres) is the
system-of-record fallback (AUTH-02-FR-1/2/3).

Cache scope: per-worker, in-process only -- one `PersonaResolver` instance
lives on `app.state.persona_resolver` per FastAPI app/Uvicorn worker, same
trade-off as AUTH-01's `JwksCache` (no Redis in the stack). There is no
cross-worker coherence; Postgres is the source of truth and each worker
independently re-reads a role's mapping after its own 300s TTL expires. An
app restart is the hard-refresh lever (flushes every worker's cache).

Fail-closed contract: an unmapped role (all three tiers miss) raises
`PersonaNotFoundError`. The resolver never returns a default persona.

PII invariant: the only structured log event this module emits,
`persona_mapping_loaded`, carries `{role, persona, tier, timestamp}`, plus
`tier3_latency_ms` on a fresh Tier-3 query only (D-11) -- never
`user_id`, `email`, `groups`, `session_id`, or any other request-scoped
context (`.claude/rules/security-baseline.md`).

TTL: 300s per role, tracked via `time.monotonic()` (wall-clock is wrong for
a TTL -- a system clock adjustment must not affect cache freshness).
"""

import logging
import time
from asyncio import Lock, wait_for
from datetime import UTC, datetime
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.db import SessionLocal
from app.models.ingestion import PersonaConfig

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 300.0
_TIER3_TIMEOUT_SECONDS = 3.0

_TIER1_ENV = "tier-1-env"
_TIER2_YAML = "tier-2-yaml"
_TIER3_POSTGRES = "tier-3-postgres"

# D-05: __file__-anchored, not a `services/api/`-prefixed literal -- every
# documented run/test command already sets cwd to `services/api`, so a
# cwd-relative literal would resolve to a nonexistent nested path. Mirrors
# `tests/conftest.py`'s `API_ROOT = Path(__file__).resolve().parent.parent`
# idiom for `ALEMBIC_INI`. This file lives at
# `services/api/app/core/persona_resolver.py`, three parents up from
# `services/api/`.
_DEFAULT_TIER2_PATH = (
    Path(__file__).resolve().parent.parent.parent / "config" / "persona_role_map.yaml"
)


class PersonaResolutionError(Exception):
    """Raised when tier resolution itself fails (e.g. a Tier-3 timeout).

    Distinct from `PersonaNotFoundError`: this signals resolution could not
    complete, not that it completed and found no mapping.
    """

    def __init__(self, role: str, reason: str) -> None:
        self.role = role
        self.reason = reason
        super().__init__(f"persona resolution failed for role={role!r}: {reason}")


class PersonaNotFoundError(PersonaResolutionError):
    """Raised when a role has no mapping in any of the three tiers (AC-4, fail-closed)."""

    def __init__(self, role: str) -> None:
        super().__init__(role, "no mapping in any tier")


class PersonaResolver:
    """Resolves an IdP role to a persona via Tier-1 env -> Tier-2 YAML -> Tier-3 Postgres.

    Construction does I/O (D-02): the Tier-2 YAML file is loaded once, here,
    synchronously. A missing file raises `FileNotFoundError`; malformed YAML
    raises `yaml.YAMLError`. Both propagate uncaught -- there is no
    lifespan try/except wrapper (D-07); a bad Tier-2 file is a startup
    failure, by design.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._settings = settings
        tier2_path = settings.persona_config_file or _DEFAULT_TIER2_PATH
        with open(tier2_path, encoding="utf-8") as handle:
            self._tier2_map: dict[str, str] = yaml.safe_load(handle) or {}
        # D-06: injectable so tests can point Tier-3 at a disposable test
        # database instead of the dev `SessionLocal` this defaults to.
        self._session_factory = session_factory or SessionLocal
        # D-04: {role: (persona, tier, expiry_ts)} guarded by an asyncio.Lock
        # alone -- no threading.Lock, since every access is on the single
        # event loop and there is no synchronous call site to share a
        # thread lock with (unlike JwksCache's dev-bypass keypair). `tier`
        # is retained so a cache hit can still emit `persona_mapping_loaded`
        # with the tier the value actually came from (FR-5), without
        # re-reading any tier to get it (AC-5).
        self._cache: dict[str, tuple[str, str, float]] = {}
        self._lock = Lock()

    async def resolve(self, role: str) -> str:
        """Return the persona for `role`, consulting the cache before any tier.

        Fast path: a warm, non-expired cache entry returns without
        acquiring the lock or consulting any tier (AC-5) -- it still emits
        `persona_mapping_loaded` (FR-5: every `resolve()` call that returns
        a persona logs, cache hit or miss), reusing the tier recorded when
        the entry was resolved rather than re-deriving one. Miss path:
        acquire the lock, then re-check (a coroutine that waited on the
        lock while another one already resolved this role must reuse that
        result, not resolve again -- this is what bounds a burst of
        concurrent cold calls for the same role to exactly one Tier-3
        query, D-04). Only a successful resolution is cached; a raise is
        never negative-cached, and never logged.

        `tier3_latency_ms` rides along only on a *fresh* Tier-3 query. A
        warm hit whose stored tier is `tier-3-postgres` deliberately omits
        it: no query ran, so there is no latency to report, and re-emitting
        the original measurement would double-count every cached read into
        the p95 alert REQUIREMENTS.md builds on that field.
        """
        cached = self._cache.get(role)
        if cached is not None and time.monotonic() < cached[2]:
            persona, tier, _ = cached
            self._log_resolution(role, persona, tier)
            return persona

        tier3_latency_ms: float | None = None
        async with self._lock:
            cached = self._cache.get(role)
            if cached is not None and time.monotonic() < cached[2]:
                persona, tier, _ = cached
            else:
                persona, tier, tier3_latency_ms = await self._resolve_uncached(role)
                self._cache[role] = (persona, tier, time.monotonic() + _CACHE_TTL_SECONDS)

        self._log_resolution(role, persona, tier, tier3_latency_ms)
        return persona

    async def _resolve_uncached(self, role: str) -> tuple[str, str, float | None]:
        """Run the 3-tier fallthrough. Raises `PersonaNotFoundError` if all three miss.

        Returns `(persona, tier, tier3_latency_ms)`; the third element is
        `None` for a Tier-1/Tier-2 hit, which ran no query.

        Fully data-driven (D-03): no branch here keys on a specific role
        string -- every role, including an empty one, goes through the same
        three lookups.
        """
        tier1_map = self._settings.persona_role_map
        if tier1_map and role in tier1_map:
            return tier1_map[role], _TIER1_ENV, None

        if role in self._tier2_map:
            return self._tier2_map[role], _TIER2_YAML, None

        started = time.perf_counter()
        persona = await self._resolve_tier3(role)
        latency_ms = (time.perf_counter() - started) * 1000.0
        if persona is not None:
            return persona, _TIER3_POSTGRES, latency_ms

        raise PersonaNotFoundError(role)

    async def _resolve_tier3(self, role: str) -> str | None:
        """Query `PersonaConfig` for `role`, bounded by a 3.0s hard timeout (FR-3)."""

        async def _query() -> str | None:
            async with self._session_factory() as session:
                result = await session.execute(
                    select(PersonaConfig).where(PersonaConfig.role == role).limit(1)
                )
                row = result.scalar_one_or_none()
                return row.persona if row is not None else None

        try:
            return await wait_for(_query(), timeout=_TIER3_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            raise PersonaResolutionError(role, "Tier-3 query timeout after 3.0s") from exc

    def _log_resolution(
        self, role: str, persona: str, tier: str, tier3_latency_ms: float | None = None
    ) -> None:
        """Emit `persona_mapping_loaded` (FR-5). Field allowlist is exact -- no PII.

        The base schema is FR-5's `{role, persona, tier, timestamp}`. A
        fresh Tier-3 resolution adds one further field, `tier3_latency_ms`
        -- mandated by the `persona-resolver` contract
        (`docs/requirements/auth.md`, consumed by AUTH-03/SHP-01),
        REQUIREMENTS.md C-4, and the NFR that alerts when its p95 exceeds
        200ms. FR-5's "nothing else" bars *user context*, not this
        non-PII operational measure; no other field may be added.

        D-08: the `timestamp` passed here is inert -- `JSONFormatter` sets
        its own `timestamp` key first and never lets an `extra` value
        overwrite an existing payload key, so the emitted value always
        comes from the formatter, not this computed one. Implemented
        literally anyway, per FR-5's specified call shape.
        """
        payload: dict[str, object] = {
            "role": role,
            "persona": persona,
            "tier": tier,
            "timestamp": datetime.now(UTC).isoformat() + "Z",
        }
        if tier3_latency_ms is not None:
            payload["tier3_latency_ms"] = round(tier3_latency_ms, 3)
        logger.info("persona_mapping_loaded", extra=payload)
