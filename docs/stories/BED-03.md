# Story: BED-03 — Rollup rebuild engine (idempotent upsert + full rebuild)

**Epic**: BED
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#13 (https://github.com/pratikpawar009/Dashboard/issues/13)
**Tracker Research**: pratikpawar009/Dashboard#65 (https://github.com/pratikpawar009/Dashboard/issues/65)

## User story

As a backend service (invoked by the ingestion write paths), I want every rollup table fully re-derived from `usage_events` on each successful ingest write, so that reads are always consistent with the raw event log and retried writes never double-count.

## Acceptance criteria

1. Given `usage_events` holds rows for program `P`, when `rebuild_program_rollups(P)` runs, then every program-scoped rollup table (`program_summary`, `program_releases`, `program_commands`, `program_members`, `session_series`, `program_token_series`, `user_sessions`) is fully replaced with values derived solely from `usage_events` rows for `P` — never an incremental patch (per FR-BE-07, A-002, data.md `rollup-rebuild` contract).
2. Given `usage_events` holds rows across all programs, when `rebuild_org_rollups()` runs, then every org-scoped rollup table (`org_summary_rollup`, `token_series`, `mau_series`) is fully replaced with values derived from `usage_events` across all programs — never an incremental patch (per FR-BE-07, A-002).
3. Given an ingest write posts the same payload twice, when the second write's rebuild completes, then `usage_events` has no duplicate row (unique on `[program_id, session_id, cmd_ts]`, per data.md `db-schema` contract) and the rebuilt rollup rows are identical to the first run — no double-counting (per FR-BE-06, NFR-012).
4. Given `rebuild_program_rollups(P)` is invoked, when it completes, then only program `P`'s rollup rows change — other programs' rollup rows are untouched, confirming the rebuild is scoped to O(events for `P`), not a global scan (per NFR-004, data.md `rollup-rebuild` invariant).

## Non-functional requirements

- Performance: rebuild cost is O(events for the affected program) per write (per NFR-004, data.md `rollup-rebuild` invariant). No PRD-specified per-rebuild latency target exists; assumed budget: ≤2s for a program with ≤5,000 `usage_events` rows — assumption, sized to NFR-002's 2s read-refresh target as the nearest analog (see Decision log).
- Security: `rebuild_program_rollups`/`rebuild_org_rollups` have no direct external HTTP surface — invoked only from the bearer-token-authenticated ingest write paths (ING-01 auth, NFR-006), per data.md `rollup-rebuild` contract's `consumed_by: [ING-02, ING-06]`.
- Accessibility: N/A — backend service function, no UI surface.
- Observability: structured log event `rollup_rebuild_completed` (fields: `scope` [`program`|`org`], `program_id` nullable, `duration_ms`, `event_count`) emitted on each rebuild — assumption, NFR-011 defines the structlog/JSON logging mechanism generally but does not name a rollup-specific event (see Decision log).

## Dependencies

- Upstream: BED-01 via `db-schema` contract (docs/requirements/data.md) — the 17-table shape, including `usage_events` and every rollup table this story rebuilds from/into.
- Downstream: ING-02 (activity ingest), ING-06 (manual CLI ingester) — both consume this story's `rollup-rebuild` contract (`rebuild_program_rollups`/`rebuild_org_rollups`) per docs/requirements/data.md.

## Test mapping

- E2E: NA — no user-facing flow; exercised indirectly by ING-02/ING-06 ingest-endpoint E2E tests.
- Unit: `backend/app/services/ingest.py` (`rebuild_program_rollups`, `rebuild_org_rollups`) — idempotency (re-run produces identical output), full-replace-not-patch behavior per table, program-scope isolation.
- Manual: NA.

## Clarifications

## Decision log

- 2026-08-26 Rebuild latency budget: ≤2s for a program with ≤5,000 `usage_events` rows — assumption, PRD gives no rebuild-specific latency target; sized to NFR-002's 2s read-refresh budget as the nearest analog.
- 2026-08-26 Observability event: `rollup_rebuild_completed` (scope, program_id, duration_ms, event_count) — assumption, NFR-011 defines the logging mechanism but doesn't enumerate a rollup-specific event name.
