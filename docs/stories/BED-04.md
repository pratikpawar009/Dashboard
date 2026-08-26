# Story: BED-04 — Ingestion freshness accessor

**Epic**: BED
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#14 (https://github.com/pratikpawar009/Dashboard/issues/14)

## User story

As a dashboard viewer (any persona), I want every dashboard view to show when ingestion data was last successfully refreshed, so that I can judge how current the numbers I'm looking at are.

## Acceptance criteria

1. Given the `system_metadata` table has a row with `key='ingestion'`, when the freshness accessor is called, then it returns `last_successful_run_at` as a timezone-aware datetime.
2. Given the `system_metadata` table has no row with `key='ingestion'` (fresh DB, never ingested), when the freshness accessor is called, then it raises an error whose message clearly states "ingestion job may not have run yet" (per PRD Error/Edge-case table, FR-BE-05).
3. Given the accessor was called within the last [NEEDS CLARIFICATION: cache TTL for the freshness accessor — PRD names it "cached" (FR-BE-05) but gives no duration, unlike the persona resolver's explicit 5-minute cache] and the underlying row has not changed, when it is called again, then it returns the cached value without a new database read.
4. Given a successful ingestion write updates `system_metadata.last_successful_run_at`, when the cache TTL from AC-3 has elapsed and the accessor is called again, then it returns the updated timestamp (cache is not stale beyond the documented TTL).

## Non-functional requirements

- Performance: cached read completes in < 10ms p95 (in-process cache, no network hop) — assumption, PRD gives no explicit budget for this accessor.
- Security: read-only accessor; no persona/role gating — the freshness timestamp is shown on every dashboard view regardless of persona (per PRD "Freshness timestamp" glossary entry, surfaced on every dashboard view), so no RBAC check applies to this story's endpoint.
- Accessibility: N/A — backend accessor, no UI surface in this story.
- Observability: log a warning-level event when the accessor raises the "ingestion job may not have run yet" error, so operators can distinguish a fresh/unseeded DB from an ingestion outage — assumption, PRD names the error but not an observability hook for it.

## Dependencies

- Upstream: BED-01 via `db-schema` contract (`docs/requirements/data.md#db-schema`) — consumes the `system_metadata` singleton table (`key` primary key, `last_successful_run_at DateTime(timezone=True)`) that BED-01's migrations create.
- Downstream: OVW-01, ARC-01, DEV-01, PMD-01, EMD-01 consume this story's `freshness-api` contract (`docs/requirements/api.md#freshness-api`) to render the freshness timestamp on their respective dashboard views.

## Test mapping

- E2E: NA — no UI in this story; downstream consumers cover rendering.
- Unit: `backend/app/services/freshness.py` — row-present path, row-absent error path, cache-hit/cache-expiry paths.
- Manual: NA

## Clarifications

- [NEEDS CLARIFICATION: cache TTL for the freshness accessor — PRD names it "cached" (FR-BE-05) but gives no duration, unlike the persona resolver's explicit 5-minute cache]

## Decision log

- 2026-08-26 Error message: "ingestion job may not have run yet" (per PRD Error/Edge-case table line 236 and FR-BE-05, `docs/prd/ai-sdlc-adoption-dashboards.md`).
- 2026-08-26 Module path: `backend/app/services/freshness.py` (per PRD FR-BE-05 Source column and Implementation-mapping table).
- 2026-08-26 Table/key shape: `system_metadata` singleton, `key='ingestion'`, `last_successful_run_at DateTime(timezone=True)` (per PRD data-model section, `docs/requirements/data.md#db-schema`).
- 2026-08-26 No RBAC gating on this accessor — assumption, per PRD glossary "Freshness timestamp ... surfaced on every dashboard view as the as-of time for the data shown" (no persona restriction named).
- 2026-08-26 Performance budget < 10ms p95 for cached read — assumption, no source budget given; sized to an in-process cache read with no I/O.
- 2026-08-26 Warning-level log on row-absent error — assumption, PRD names the error message but not an observability hook.
