# Story: ING-09 — Scheduled ingestion (cron)

**Epic**: ING
**Status**: Validated
**Priority**: P3
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#48 (https://github.com/pratikpawar009/Dashboard/issues/48)

## User story

As a platform operator, I want ingestion to run automatically on a defined schedule so that dashboard data stays fresh without a developer manually triggering the CLI ingester or MCP push.

## Acceptance criteria

1. Given the scheduler is running, when the configured cron cadence elapses, then the scheduled job invokes the same validate → upsert → rebuild-rollups pipeline as `ingest-files-api` (POST /api/ingest/files) for the configured program(s), without manual intervention.
2. Given a scheduled run completes successfully, when the job finishes, then `system_metadata.last_successful_run_at` is updated to the run's completion timestamp.
3. Given a scheduled run fails (network error, ingest-token-auth rejection, or row validation failure), when the failure occurs, then the job logs the failure reason, leaves `last_successful_run_at` unchanged, and retries on a later cadence rather than updating the timestamp or crashing the scheduler process.
4. Given the ingest token configured for the scheduler is invalid or out of program scope, when a run is attempted, then the job logs an authentication/authorization failure (per `ingest-files-api`'s bearer-auth contract) and does not mark the run successful.
5. Given a previous scheduled run is still in progress, when the next cadence fires, then the job skips the new trigger rather than running two ingestion passes concurrently against the same program.

## Non-functional requirements

- Performance: each scheduled run has an explicit end-to-end timeout of 10 minutes per program, per the project's no-silent-infinite-wait baseline — assumption, source gives no per-run budget.
- Security: reuses the `ingest-token-auth` bearer token established in ING-01; the token is read from job configuration/environment, never logged in plaintext.
- Accessibility: N/A — backend batch job, no UI surface.
- Observability: log `job_run_id, status, rows_processed, duration_ms` per run; retries capped at 3 attempts with exponential backoff and jitter, per the project's bounded-retry baseline — assumption, no source retry count given.

## Dependencies

- Upstream: ING-02 via `ingest-files-api` (POST /api/ingest/files: bearer auth, 5000-rows/request cap, received/valid/inserted/updated/rejected counts + rollup summaries) — the scheduler drives this endpoint's pipeline on a cadence instead of a manual CLI/MCP trigger.
- Downstream: none — no other RTM row lists ING-09 as a dependency.

## Test mapping

- E2E: N/A — no user-facing flow; covered by integration test of the scheduled-job pipeline.
- Unit: scheduler cadence-trigger logic, overlap/skip guard, failure logging, and `system_metadata.last_successful_run_at` update, in the backend scheduler module (candidate: APScheduler in-process job per FR-ING-11).
- Manual: verify the cron trigger fires on the configured cadence in a staging environment — clock-based scheduling is impractical to assert deterministically in the automated unit/integration suite.

## Clarifications

## Decision log

- 2026-08-26 Scheduler mechanism: APScheduler in-process job — assumption, per FR-ING-11's candidate list (PRD gives "APScheduler in-process, or an external cron calling the CLI ingester / MCP push" as options with no final decision); in-process avoids adding new external infra.
- 2026-08-26 Cadence: hourly — assumption, source (FR-ING-11) requires only "a defined cadence" with no specific value.
- 2026-08-26 Per-run timeout: 10 minutes — assumption, per project performance-baseline (explicit I/O timeouts, no silent infinite waits); no source budget given.
- 2026-08-26 Retry policy: 3 attempts, exponential backoff + jitter — assumption, per project performance-baseline (bounded retries required); no source count given.
- 2026-08-26 Concurrency guard (AC5): skip overlapping runs rather than queue — assumption, source is silent on concurrent-run behavior; skip chosen over queueing to avoid unbounded backlog per the no-unbounded-fan-out baseline.
