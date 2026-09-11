"""Three-tier persona resolver: env override -> YAML override -> Postgres system-of-record.

`PersonaResolver` maps an IdP `role` claim onto one of the product personas,
consulted by downstream RBAC checks (AUTH-03) and the persona-header UI
(SHP-01). Tier-1 (`Settings.persona_role_map`, `PERSONA_ROLE_MAP` env JSON)
and Tier-2 (this module's Tier-2 YAML file) are operator-editable override
layers; Tier-3 (`app.models.ingestion.PersonaConfig` in Postgres) is the
system-of-record fallback (AUTH-02-FR-1/2/3).

AUTH-07-FR-6/AC-20: the SAME 3-tier mechanism additionally sources an
ordered persona-PRECEDENCE list, used to pick a single deterministic
winner when a token carries several mappable roles. Tier-1
`Settings.persona_precedence_order` (`PERSONA_PRECEDENCE_ORDER` env JSON
array), Tier-2 a root-level `precedence:` key in this module's Tier-2 YAML
file, Tier-3 `app.models.ingestion.PersonaPrecedence` (`ORDER BY rank`);
all three unset falls back to the hardcoded default order (ADR-0011).
`_resolve_precedence_order` loads and caches the order; `resolve_precedence`
(AUTH-07-AC-19/FR-6, DECISIONS.md D-06) is the public method that consumes
it to select a single winning role among several candidates.

Cache scope: per-worker, in-process only -- one `PersonaResolver` instance
lives on `app.state.persona_resolver` per FastAPI app/Uvicorn worker, same
trade-off as AUTH-01's `JwksCache` (no Redis in the stack). There is no
cross-worker coherence; Postgres is the source of truth and each worker
independently re-reads a role's mapping after its own 300s TTL expires. An
app restart is the hard-refresh lever (flushes every worker's cache).

Fail-closed contract: an unmapped role (all three tiers miss) raises
`PersonaNotFoundError`. The resolver never returns a default persona.

PII invariant: the two structured log events this module emits carry role
slugs and tier names only, never `user_id`, `email`, `groups`, `session_id`,
or any other request-scoped context (`.claude/rules/security-baseline.md`).
`persona_mapping_loaded` carries `{role, persona, tier, timestamp}`, plus
`tier3_latency_ms` on a fresh Tier-3 query only (D-11).
`persona_mapping_not_found` (AUTH-07-AC-25/AC-26/FR-8, D-04) carries
`{roles, tiers_consulted, timestamp}` and fires from two call shapes --
`resolve()`'s own single-role all-3-tier-miss and `resolve_precedence`'s
aggregated multi-role miss -- before either raises `PersonaNotFoundError`.

TTL: 300s per role, tracked via `time.monotonic()` (wall-clock is wrong for
a TTL -- a system clock adjustment must not affect cache freshness).
"""

import logging
import time
from asyncio import Lock, wait_for
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.db import SessionLocal
from app.models.ingestion import PersonaConfig, PersonaPrecedence

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 300.0
_TIER3_TIMEOUT_SECONDS = 3.0

_TIER1_ENV = "tier-1-env"
_TIER2_YAML = "tier-2-yaml"
_TIER3_POSTGRES = "tier-3-postgres"

# AUTH-07-FR-6/AC-20 (ADR-0011): hardcoded fallback when Tier-1, Tier-2, and
# Tier-3 precedence are all unset -- no working deployment must configure
# anything to get today's intended order.
_DEFAULT_PERSONA_PRECEDENCE: list[str] = [
    "cio",
    "architect",
    "product-manager",
    "engineering-manager",
    "developer",
]

# DATA-DESIGN.md AUTH-07 §6: a reserved cache key for the precedence order,
# kept in its OWN dict (`PersonaResolver._precedence_cache`) rather than the
# per-role `self._cache` above -- the two hold structurally different values
# (a single persona/tier pair per role vs. one ordered list overall), so
# sharing a dict would force `self._cache`'s value type wider for every
# existing per-role read. The leading NUL byte makes collision with a real
# (casefolded) IdP role string impossible by construction, not just unlikely.
_PRECEDENCE_CACHE_KEY = "\x00persona-precedence-order"

# Reused as the `role` field of `PersonaResolutionError` on a Tier-3
# precedence-query timeout (see `_resolve_tier3_precedence`) -- there is no
# real role in play, only a fixed, readable label identifying which lookup
# timed out.
_PRECEDENCE_ERROR_LABEL = "persona-precedence-order"

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


def _casefold_tier_map(mapping: dict[str, str]) -> dict[str, str]:
    """Casefold `mapping`'s keys for case-insensitive lookup (AC-18/FR-7).

    Lookup-side normalization only -- the tier's own stored values are
    untouched, only the key used to look them up. Raises
    `PersonaResolutionError(role=<casefolded key>,
    reason="ambiguous_case_collision")` if two distinct original keys in
    `mapping` casefold to the same string (AC-22/D-03) -- fully data-driven,
    no branch keys on a specific role string.
    """
    folded: dict[str, str] = {}
    originals: dict[str, str] = {}
    for original_key, persona in mapping.items():
        folded_key = original_key.casefold()
        if folded_key in originals and originals[folded_key] != original_key:
            raise PersonaResolutionError(folded_key, reason="ambiguous_case_collision")
        originals[folded_key] = original_key
        folded[folded_key] = persona
    return folded


def _validate_tier2_precedence_order(value: object) -> list[str] | None:
    """Validate the Tier-2 YAML `precedence:` root-level key (AUTH-07-FR-6/AC-20).

    `None` means the key was absent from the document -- a legitimate
    Tier-2 miss, falling through to Tier-3. Any other value that is not a
    list of strings is a startup error (`ValueError`), propagating
    uncaught through `create_app()` exactly like a malformed Tier-2 YAML
    document already does (D-05) -- a malformed precedence override must
    never silently degrade to Tier-3 or the hardcoded default.
    """
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(
            f"persona_role_map.yaml 'precedence' must be a list of strings, got {value!r}"
        )
    return list(value)


class PersonaResolver:
    """Resolves an IdP role to a persona via Tier-1 env -> Tier-2 YAML -> Tier-3 Postgres.

    Construction does I/O (D-02): the Tier-2 YAML file is loaded once, here,
    synchronously. A missing file raises `FileNotFoundError`; malformed YAML
    raises `yaml.YAMLError`; a syntactically valid document whose root-level
    `precedence:` key is present but not a list of strings (AUTH-07-FR-6/
    AC-20) raises `ValueError`. All three propagate uncaught -- there is no
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
            raw_tier2_document: dict[str, Any] = yaml.safe_load(handle) or {}
        # AUTH-07-FR-6/AC-20: `precedence:` is a root-level sibling key of
        # the role map in the SAME YAML document, not a nested "role map"
        # section -- pop it out before casefolding so a document carrying
        # both never leaks a literal "precedence" role into `self._tier2_map`.
        raw_tier2_precedence = raw_tier2_document.pop("precedence", None)
        # AC-18/AC-22/FR-7: casefold both operator-editable tiers once here,
        # at construction -- a same-tier collision (two distinct original
        # keys casefolding identically) is a startup failure, propagating
        # uncaught through `create_app()` exactly like a malformed Tier-2
        # YAML file already does, never reachable at request time for these
        # two tiers (D-03).
        self._tier1_map: dict[str, str] = _casefold_tier_map(settings.persona_role_map or {})
        self._tier2_map: dict[str, str] = _casefold_tier_map(raw_tier2_document)
        self._tier2_precedence_order: list[str] | None = _validate_tier2_precedence_order(
            raw_tier2_precedence
        )
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
        # AUTH-07-FR-6/AC-20 (DATA-DESIGN.md §6): a dedicated single-entry
        # cache for the precedence order, guarded by the SAME `self._lock`
        # and TTL as the per-role cache above -- see `_PRECEDENCE_CACHE_KEY`.
        self._precedence_cache: dict[str, tuple[list[str], float]] = {}

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

        The cache key is `role.casefold()` (AC-23/FR-7): `Architect` and
        `architect` share one entry and never alternate between hit and
        miss on casing alone.
        """
        cache_key = role.casefold()
        cached = self._cache.get(cache_key)
        if cached is not None and time.monotonic() < cached[2]:
            persona, tier, _ = cached
            self._log_resolution(role, persona, tier)
            return persona

        tier3_latency_ms: float | None = None
        async with self._lock:
            cached = self._cache.get(cache_key)
            if cached is not None and time.monotonic() < cached[2]:
                persona, tier, _ = cached
            else:
                persona, tier, tier3_latency_ms = await self._resolve_uncached(role)
                self._cache[cache_key] = (persona, tier, time.monotonic() + _CACHE_TTL_SECONDS)

        self._log_resolution(role, persona, tier, tier3_latency_ms)
        return persona

    async def resolve_precedence(self, roles: list[str]) -> str:
        """Select a single winning role from `roles` via persona-precedence
        order (AUTH-07-AC-19/FR-6, DECISIONS.md D-06).

        `roles` must already be filtered of Keycloak system roles by the
        caller (`app.core.auth._is_keycloak_system_role`, D-09) -- this
        method does not re-filter; `get_current_user` (T-06) owns that
        boundary, the same as it already does for the single-role
        `_parse_role` path.

        For each role, in original token order, attempts the SAME cached,
        non-raising 3-tier lookup `_cached_lookup` performs (itself
        delegating to `_lookup_tiers` on a cold entry) -- a losing candidate
        never aborts the loop and never logs anything on its own (D-04's
        whole point: a token carrying one persona role plus unrelated
        business roles must not spuriously log `persona_mapping_not_found`
        for the unrelated ones). The winner is the FIRST persona in
        precedence order (`_resolve_precedence_order`) that appears among the collected
        candidates -- never the first surviving role in token order, a
        materially different algorithm (AC-19: a token with
        `['Architect', 'Developer', 'developer']` must resolve to
        `architect` regardless of array order).

        Returns the CASEFOLDED winning ROLE string, never the persona --
        `CurrentUser.role` stays "one of the token's own roles" (frozen
        invariant), casefolded for the same reason every other tier lookup
        here is (AC-18/FR-7). Per-candidate lookups go through
        `_cached_lookup` (AUTH-07-AC-7 fix), which reads/writes the SAME
        `self._cache` `resolve()` uses -- a role warmed by one entry point
        is a cache hit on the other, and a repeated `resolve_precedence`
        call for the same roles issues no additional Tier-1/2/3 lookup
        while the 300s cache stays warm.

        Fail-closed (AC-26): if no candidate's persona also appears in the
        precedence order (including the "no candidate at all" case),
        emits ONE aggregated `persona_mapping_not_found` (D-04(b)) --
        `roles` is the full list attempted, never one event per losing
        candidate -- then raises `PersonaNotFoundError`.
        """
        candidates: dict[str, str] = {}
        for role in roles:
            result = await self._cached_lookup(role)
            if result is not None:
                persona = result[0]
                candidates.setdefault(persona, role.casefold())

        if candidates:
            order = await self._resolve_precedence_order()
            for persona in order:
                if persona in candidates:
                    return candidates[persona]

        self._log_not_found(list(roles))
        raise PersonaNotFoundError(",".join(roles))

    async def _cached_lookup(self, role: str) -> tuple[str, str, float | None] | None:
        """Non-raising 3-tier lookup for `role`, consulting the SAME per-role
        cache (`self._cache`) and TTL `resolve()` uses (AUTH-07-AC-7 fix).

        `resolve_precedence` calls this exclusively for its per-candidate
        lookups -- a role already warmed by a `resolve()` call (or a prior
        `resolve_precedence` call) is a cache hit here, and a role this
        method resolves is a cache hit for a LATER `resolve()` call too:
        one shared cache, read and written from both entry points, never a
        second cache/lock/TTL (D-05, DATA-DESIGN.md AUTH-07 §6/§8).

        Same double-checked-locking shape as `resolve()`'s own inline cache
        handling: a fast, lock-free read of a warm entry, then acquire
        `self._lock` and re-check before running `_lookup_tiers`, so a
        burst of concurrent candidate resolutions for the same role
        collapses to one Tier-3 query, not one per waiter.

        Returns `(persona, tier, tier3_latency_ms)` on a hit --
        `tier3_latency_ms` is `None` on a warm-cache hit (no query ran this
        call, matching `resolve()`'s own warm-hit contract: never replaying
        a prior measurement) and only non-`None` on a FRESH Tier-3 query.
        Returns `None` on an all-tiers miss -- a miss is NEVER cached
        (AC-26: an operator fixing a Tier-3 row must see it on the very
        next call for that role, not up to 300s later).
        """
        cache_key = role.casefold()
        cached = self._cache.get(cache_key)
        if cached is not None and time.monotonic() < cached[2]:
            persona, tier, _ = cached
            return persona, tier, None

        async with self._lock:
            cached = self._cache.get(cache_key)
            if cached is not None and time.monotonic() < cached[2]:
                persona, tier, _ = cached
                return persona, tier, None

            result = await self._lookup_tiers(role)
            if result is None:
                return None

            persona, tier, tier3_latency_ms = result
            self._cache[cache_key] = (persona, tier, time.monotonic() + _CACHE_TTL_SECONDS)
            return persona, tier, tier3_latency_ms

    async def _resolve_uncached(self, role: str) -> tuple[str, str, float | None]:
        """Run the 3-tier fallthrough. Raises `PersonaNotFoundError` if all three miss.

        Returns `(persona, tier, tier3_latency_ms)`; the third element is
        `None` for a Tier-1/Tier-2 hit, which ran no query.

        Delegates the actual lookup to `_lookup_tiers` (AUTH-07-D-06) -- the
        same non-raising helper `_cached_lookup` uses on a cold entry for
        `resolve_precedence`'s own multi-role fallthrough, so the 3-tier
        lookup logic lives in exactly one place. A miss (`_lookup_tiers`
        returns `None`) emits
        `persona_mapping_not_found` (AC-25/AC-26/FR-8, D-04(a)) with
        `roles=[role]` before raising -- the single-role counterpart to
        `resolve_precedence`'s aggregated multi-role emission.
        """
        result = await self._lookup_tiers(role)
        if result is not None:
            return result

        self._log_not_found([role])
        raise PersonaNotFoundError(role)

    async def _lookup_tiers(self, role: str) -> tuple[str, str, float | None] | None:
        """Non-raising 3-tier fallthrough shared by `_resolve_uncached`
        (`resolve()`'s single-role cold path) and `_cached_lookup`
        (`resolve_precedence`'s multi-role cold path, D-06). Returns
        `(persona, tier, tier3_latency_ms)` on a hit, `None` on an
        all-tiers miss -- never raises, so a caller trying several
        candidate roles can attempt every one without a losing candidate
        aborting the loop.

        Fully data-driven (D-03): no branch here keys on a specific role
        string -- every role, including an empty one, goes through the same
        three lookups.

        `role` is casefolded once here and the folded value is reused
        across all three tiers (AC-18/FR-7): Tier-1/Tier-2 lookups are
        against the pre-casefolded maps built in `__init__`; Tier-3's own
        query casefolds at the SQL layer against this same folded value.
        """
        folded_role = role.casefold()
        if folded_role in self._tier1_map:
            return self._tier1_map[folded_role], _TIER1_ENV, None

        if folded_role in self._tier2_map:
            return self._tier2_map[folded_role], _TIER2_YAML, None

        started = time.perf_counter()
        persona = await self._resolve_tier3(folded_role)
        latency_ms = (time.perf_counter() - started) * 1000.0
        if persona is not None:
            return persona, _TIER3_POSTGRES, latency_ms

        return None

    async def _resolve_tier3(self, casefolded_role: str) -> str | None:
        """Query `PersonaConfig` for `casefolded_role`, bounded by a 3.0s hard
        timeout (FR-3).

        The `WHERE` clause casefolds the stored role at the SQL layer
        (`func.lower`) rather than comparing exactly, since Tier-3 data can
        change without a restart and is not pre-casefolded like Tier-1/
        Tier-2 (AC-18/FR-7). Raises
        `PersonaResolutionError(reason="ambiguous_case_collision")` if the
        result set carries more than one distinct persona for this role
        (AC-22/D-03) -- a same-tier collision only detectable at query time,
        unlike Tier-1/Tier-2's construction-time check.
        """

        async def _query() -> str | None:
            async with self._session_factory() as session:
                result = await session.execute(
                    select(PersonaConfig).where(func.lower(PersonaConfig.role) == casefolded_role)
                )
                personas = {row.persona for row in result.scalars().all()}
                if len(personas) > 1:
                    raise PersonaResolutionError(casefolded_role, reason="ambiguous_case_collision")
                return next(iter(personas), None)

        try:
            return await wait_for(_query(), timeout=_TIER3_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            raise PersonaResolutionError(
                casefolded_role, "Tier-3 query timeout after 3.0s"
            ) from exc

    async def _resolve_precedence_order(self) -> list[str]:
        """Return the persona-precedence order (AUTH-07-FR-6/AC-20), consulting
        the dedicated precedence cache before any tier -- same warm/cold,
        double-checked-locking shape as `resolve()`'s per-role cache, reusing
        `self._lock` and `_CACHE_TTL_SECONDS` rather than a second lock or TTL
        (DATA-DESIGN.md AUTH-07 §6). At most one Tier-3 precedence query runs
        per 300s per worker in steady state.

        Loading only -- this does not select a winner among several
        candidate personas. `resolve_precedence` (DECISIONS.md D-06) is the
        caller that consumes this order to pick one.
        """
        cached = self._precedence_cache.get(_PRECEDENCE_CACHE_KEY)
        if cached is not None and time.monotonic() < cached[1]:
            return cached[0]

        async with self._lock:
            cached = self._precedence_cache.get(_PRECEDENCE_CACHE_KEY)
            if cached is not None and time.monotonic() < cached[1]:
                return cached[0]
            order = await self._resolve_precedence_order_uncached()
            self._precedence_cache[_PRECEDENCE_CACHE_KEY] = (
                order,
                time.monotonic() + _CACHE_TTL_SECONDS,
            )
            return order

    async def _resolve_precedence_order_uncached(self) -> list[str]:
        """Tier-1 -> Tier-2 -> Tier-3 -> hardcoded default (AC-20).

        Fully data-driven (D-03's spirit): no branch here keys on a specific
        persona string. An empty list from Tier-1 or Tier-2 is still a
        deliberate override (an operator's own choice) and is honored as-is
        -- only an ABSENT tier (settings field `None`, YAML key absent, zero
        Tier-3 rows) falls through to the next tier.
        """
        if self._settings.persona_precedence_order is not None:
            return self._settings.persona_precedence_order

        if self._tier2_precedence_order is not None:
            return self._tier2_precedence_order

        tier3_order = await self._resolve_tier3_precedence()
        if tier3_order is not None:
            return tier3_order

        return list(_DEFAULT_PERSONA_PRECEDENCE)

    async def _resolve_tier3_precedence(self) -> list[str] | None:
        """Query `PersonaPrecedence` ORDER BY rank, bounded by the SAME 3.0s
        hard timeout `_resolve_tier3` uses -- no second timeout value
        introduced (DATA-DESIGN.md AUTH-07 §5).

        An empty table is a legitimate steady state (no migration backfill,
        `005_persona_precedence.py`) -- returns `None`, exactly like an
        unset Tier-1/Tier-2, so the caller falls through to the hardcoded
        default rather than treating "no rows" as a distinct outcome.
        """

        async def _query() -> list[str] | None:
            async with self._session_factory() as session:
                result = await session.execute(
                    select(PersonaPrecedence).order_by(PersonaPrecedence.rank)
                )
                rows = result.scalars().all()
                return [row.persona for row in rows] if rows else None

        try:
            return await wait_for(_query(), timeout=_TIER3_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            raise PersonaResolutionError(
                _PRECEDENCE_ERROR_LABEL, "Tier-3 precedence query timeout after 3.0s"
            ) from exc

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

    def _log_not_found(self, roles: list[str]) -> None:
        """Emit `persona_mapping_not_found` (AC-25/AC-26/FR-8, D-04). Same
        PII-allowlist discipline as `_log_resolution`: role slugs and tier
        names only, never `user_id`/`email`/`name`/`groups`. Called from
        both emission points D-04 requires -- `_resolve_uncached`'s own
        single-role all-3-tier-miss (`roles=[role]`) and
        `resolve_precedence`'s aggregated multi-role miss (`roles=` every
        surviving role attempted) -- always fired BEFORE the caller raises
        `PersonaNotFoundError` (fail-closed unchanged, AC-26). Distinct
        event name from both `persona_mapping_loaded` (success) and
        `rbac_check_org_access outcome=denied` (an RBAC denial) -- the name
        alone makes an unmapped role grep-distinguishable from either.
        """
        payload: dict[str, object] = {
            "roles": list(roles),
            "tiers_consulted": [_TIER1_ENV, _TIER2_YAML, _TIER3_POSTGRES],
            "timestamp": datetime.now(UTC).isoformat() + "Z",
        }
        logger.info("persona_mapping_not_found", extra=payload)


def get_persona_resolver(request: Request) -> PersonaResolver:
    """FastAPI dependency returning the per-app `PersonaResolver` (D-07 addendum).

    `create_app` constructs exactly one `PersonaResolver` per app instance and
    assigns it to `app.state.persona_resolver`; consumers reach it via
    `Depends(get_persona_resolver)`, never a module global.
    """
    return request.app.state.persona_resolver
