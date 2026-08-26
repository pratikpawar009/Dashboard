# Story: AUTH-02 — Persona resolver (3-tier, cached)

**Epic**: AUTH
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#16 (https://github.com/pratikpawar009/Dashboard/issues/16)

## User story

As the backend RBAC layer, I want to resolve a signed-in session's `role` claim to one of the
five product personas via a cached, three-tier lookup, so that downstream RBAC checks and the
persona header/context shell (AUTH-03, SHP-01) always have a consistent persona without a code
change or deploy when a role mapping changes.

## Acceptance criteria

1. Given a `role` mapped in the env-JSON source, when the resolver runs, then it returns the
   persona from that tier (`cio | architect | developer | product-manager |
   engineering-manager`) without needing the config-file or Postgres tiers to be consulted.
2. Given a `role` with no env-JSON mapping but a mapping in the config file, when the resolver
   runs, then it returns the config-file tier's persona (tier-2 fallback).
3. Given a `role` with no env-JSON or config-file mapping but a row in the Postgres
   `persona_config` table, when the resolver runs, then it returns that row's persona
   (tier-3 fallback).
4. Given a `role` with no mapping in any of the three sources, when the resolver runs, then it
   raises (does not return a persona value or default silently), so the caller cannot mint a
   persona-scoped session for an unmapped role.
5. Given a resolved persona is already cached for a `role`, when the resolver is called again
   for the same `role` within 5 minutes of the first resolution, then the cached value is
   returned and the underlying sources are not re-read.
6. Given a role→persona mapping is added or changed in any one of the three sources, when the
   resolver's 5-minute cache for that role next expires and it is called again, then it returns
   the updated mapping — no code change or deploy required.
7. Given an additional executive role slug (e.g. `cxo`, `board_member`) is added to any of the
   three sources mapped to `cio`, when the resolver runs for that role, then it returns `cio`.

## Non-functional requirements

- Performance: 5-minute in-process cache TTL per role (per `persona-resolver` contract,
  `docs/requirements/auth.md`), so at most one Postgres tier-3 read per role per 5-minute
  window. The tier-3 Postgres query itself times out at 3s — assumption, source gives no
  explicit budget; chosen per `.claude/rules/performance-baseline.md`'s "I/O has explicit
  timeouts" rule, well under typical request timeouts.
- Security: fail-closed — raises when all three sources are empty for a role rather than
  defaulting to any persona (per PRD §3.4 anti-persona case: "persona resolution throws when a
  role has no mapping in any configured source; such a user cannot reach any dashboard").
- Accessibility: N/A — backend resolver, no UI surface.
- Observability: emits the `persona_mapping_loaded` structured log event on every resolution
  (role, resolved persona, source tier, timestamp), per NFR-011 (`docs/prd/ai-sdlc-adoption-dashboards.md`).

## Dependencies

- Upstream: AUTH-01 via `session` contract (`docs/requirements/auth.md` — supplies the
  decoded session's `role` field this resolver takes as input); BED-01 via `db-schema`
  contract (`docs/requirements/data.md` — supplies the Postgres `persona_config` table,
  `role String primary key -> persona String`, the tier-3 source).
- Downstream: AUTH-03 (`rbac-checks`, consumes `persona-resolver`), SHP-01 (persona
  header/context shell, consumes `persona-resolver`).

## Test mapping

- E2E: NA — backend-only resolver; exercised indirectly via downstream persona-gated routes
  once AUTH-03/SHP-01 land.
- Unit: `services/api/tests/core/test_persona_resolver.py` against
  `services/api/app/core/persona_resolver.py` — one case per tier precedence, cache-hit,
  cache-expiry re-read, all-sources-empty raise, and the executive-role-to-`cio` mapping.
- Manual: NA — fully covered by unit tests.

## Clarifications

## Decision log

- 2026-08-26 Tier-3 Postgres query timeout: 3s — assumption, source (`persona-resolver`
  contract, PRD) gives no explicit I/O budget; chosen conservatively per
  `.claude/rules/performance-baseline.md`'s explicit-timeout rule.
