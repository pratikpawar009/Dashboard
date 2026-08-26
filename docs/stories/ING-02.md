# Story: ING-02 — POST /api/ingest/files — activity ingest

**Epic**: ING
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#41 (https://github.com/pratikpawar009/Dashboard/issues/41)

## User story

As the MCP server / CLI ingester (via `push_activity` or the manual CLI), I want to POST a batch of activity rows to `/api/ingest/files` and have them validated, upserted into `usage_events`, and rolled up synchronously, so that a developer's freshly captured activity is visible on their dashboard on next page load.

## Acceptance criteria

1. Given a bearer-token-authenticated request with `{program_id, kind:"activity", rows}` where `rows.length <= 5000` and every row passes schema validation, when the endpoint processes it, then all rows are upserted into `usage_events` (unique on `[program_id, session_id, cmd_ts]`), `rebuild_program_rollups(program_id)` and `rebuild_org_rollups()` run synchronously, and the response reports `received/valid/inserted/updated/rejected` counts plus rollup summaries (per FR-ING-04, `ingest-files-api` and `rollup-rebuild` contracts).
2. Given a request with a missing, revoked, or expired bearer token, when the endpoint authenticates it, then it returns `401` and writes nothing to `usage_events` (per `ingest-token-auth` contract).
3. Given a request with a valid token whose `allowed_program_ids` does not include the target `program_id` and contains no `"*"` wildcard, when the endpoint authorizes it, then it returns `403` and writes nothing (per `ingest-token-auth` contract).
4. Given a request whose `rows` array exceeds 5000 entries, when the endpoint validates the batch size, then it returns `413` before any row is processed (per FR-ING-04, NFR row on ingest payload size).
5. Given a batch containing one row with a malformed ISO date, a missing required field, or an unrecognized `kind`, when the endpoint validates rows, then that row is dropped into the `rejected` bucket with a reason, while the other valid rows in the same batch still commit (per PRD malformed-activity-rows error case, §6).
6. Given the same valid payload is POSTed twice, when the second request's rebuild completes, then `usage_events` has no duplicate row and the rebuilt rollup rows are identical to the first run — no double-counting (per FR-BE-06, NFR-012, `rollup-rebuild` contract).

## Non-functional requirements

- Performance: p95 response time <= 3s for a maximum-size 5000-row batch (the request cap per FR-ING-04, AC-4) covering validate + upsert + synchronous rollup rebuild — assumption, no PRD-specific ingest-endpoint latency target exists; sized from BED-03's ≤2s/≤5000-events rebuild budget plus validation/upsert overhead (see Decision log).
- Security: bearer-token auth only, never session-cookie auth, scoped by `allowed_program_ids` (per NFR-006); request/row payload is confidential individual-activity detail (per PRD Data Classification, `usage_events` row).
- Accessibility: N/A — backend endpoint, no UI surface.
- Observability: structured log event `ingest_write_completed` (fields: `program_id`, `rows_received`, `rows_inserted`, `rows_updated`, `rows_rejected`, `duration_ms`) — assumption, NFR-011 defines the structlog/JSON logging mechanism and names an event set that does not include an ingest-specific event (see Decision log).

## Dependencies

- Upstream: ING-01 via `ingest-token-auth` contract (docs/requirements/auth.md) — bearer hash lookup, 401/403 semantics, program-scope allowlist; BED-01 via `db-schema` contract (docs/requirements/data.md) — `usage_events` table shape and unique constraint; BED-03 via `rollup-rebuild` contract (docs/requirements/data.md) — `rebuild_program_rollups`/`rebuild_org_rollups` invoked synchronously after upsert.
- Downstream: ING-04 (MCP tool exposure), ING-06 (manual CLI ingester), ING-09 (scheduled ingestion) — all consume this story's `ingest-files-api` contract (docs/requirements/api.md).

## Test mapping

- E2E: NA — no user-facing flow; exercised indirectly via ING-04/ING-06 MCP-push and CLI E2E tests hitting this endpoint.
- Unit: `backend/app/routers/ingest.py`, `backend/app/services/ingest.py` — auth/authz (401/403), row validation (413 cap, per-row rejection reasons), idempotent upsert, rollup-rebuild invocation.
- Manual: NA.

## Clarifications

## Decision log

- 2026-08-26 Ingest-endpoint latency budget: p95 <= 3s for a 5000-row batch — assumption, PRD gives no ingest-specific latency target; sized from BED-03's rebuild budget (≤2s/≤5000 events) plus validation/upsert overhead.
- 2026-08-26 Observability event: `ingest_write_completed` (program_id, rows_received, rows_inserted, rows_updated, rows_rejected, duration_ms) — assumption, NFR-011 defines the logging mechanism and event set generally but does not name an ingest-write event.
