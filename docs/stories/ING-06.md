# Story: ING-06 — Manual CLI ingester (dogfooding, self-referential program)

**Epic**: ING
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#45 (https://github.com/pratikpawar009/Dashboard/issues/45)

## User story

As the platform team dogfooding this project's own build activity, I want a CLI command that reads every activity JSONL file under the activity log directory and runs it through the same validate → upsert → rebuild-rollups pipeline as the HTTP ingest route, so that this project's own `/arh-*` command activity lands in a real, self-referential program without needing a bearer token or a running MCP server.

## Acceptance criteria

1. Given one or more JSONL files exist under the activity log directory (`docs/activity/*.jsonl`, e.g. `activity.jsonl` plus rolled-over month files like `2026-07.jsonl`), when the CLI ingester (`backend/app/cli/ingest.py`) runs, then it reads every matching file and parses each line as NDJSON, skipping blank or malformed lines (per FR-ING-08, mirroring FR-ING-02's parse behavior).
2. Given parsed activity rows, when the CLI ingester runs, then it calls the same shared service functions as `POST /api/ingest/files` (`backend/app/services/ingest.py`) to validate each row, upsert into `usage_events` idempotently on `[program_id, session_id, cmd_ts]`, and synchronously rebuild rollups via `rebuild_program_rollups`/`rebuild_org_rollups` (`rollup-rebuild` contract, data.md) — all scoped to the fixed self-referential program id `harness-self` ("AgentRise Harness"), per PRD §"reference implementation dogfoods its own pipeline".
3. Given a row fails Pydantic validation, when the CLI ingester runs, then that row is excluded from the upsert and counted as rejected with a reason, while the remaining valid rows in the same run are still ingested (per `ingest-files-api` contract's received/valid/inserted/updated/rejected response shape).
4. Given the CLI ingester completes a run, when it exits, then it prints/returns received/valid/inserted/updated/rejected counts plus rollup summaries — the same response shape as `ingest-files-api` (per FR-ING-08, data.md `rollup-rebuild` contract).
5. Given the CLI ingester is run twice against the same unchanged JSONL files, when the second run completes, then `usage_events` has no duplicate rows and rebuilt rollups for `harness-self` are identical to the first run — idempotent re-ingest (per NFR-012, FR-BE-06).
6. Given the same activity rows are pushed once via the MCP `push_activity` → `POST /api/ingest/files` path and once via the CLI ingester, when both complete, then the resulting `usage_events` and rollup state for `harness-self` is identical, because both paths invoke the identical shared service functions rather than separate implementations (per FR-ING-08: "CLI and MCP-push paths produce identical DB state for the same input rows").

## Non-functional requirements

- Performance: rollup rebuild is O(events for the affected program) per write (per NFR-004, `rollup-rebuild` contract). No PRD latency target exists for the CLI run itself — it's an operator-triggered manual/batch job, not a user-facing request; assumed acceptable budget: completes without a hard timeout, logging progress per file — assumption, no source target (see Decision log).
- Security: no bearer-token/HTTP auth surface — the CLI runs locally with direct access to the shared service functions (`backend/app/services/ingest.py`), the same trust model as the other local operator CLI, `mint_ingest_token.py` (FR-ING-06); access is controlled by who can execute the CLI on the backend host/deployment, not by `ingest-token-auth` — assumption, PRD doesn't state this explicitly for FR-ING-08 (see Decision log).
- Accessibility: N/A — CLI tool, no UI surface.
- Observability: structured log event `cli_ingest_completed` (fields: `files_read`, `rows_read`, `inserted`, `rejected`, `duration_ms`) per run, using the `structlog`/JSON mechanism NFR-011 defines generally — assumption, NFR-011 doesn't name a CLI-ingest-specific event (see Decision log).

## Dependencies

- Upstream: ING-02 via `ingest-files-api` contract (docs/requirements/api.md) — reuses the validate/upsert service functions and response shape (received/valid/inserted/updated/rejected counts + reasons + rollup summaries) that back `POST /api/ingest/files`. BED-03 via `rollup-rebuild` contract (docs/requirements/data.md) — invokes `rebuild_program_rollups`/`rebuild_org_rollups` after upsert, per the same full-rebuild-not-patch invariant.
- Downstream: ING-09 (scheduled ingestion, P3) depends on this story's CLI entry point per `ingest-files-api` contract's `consumed_by: [ING-04, ING-06, ING-09]`.

## Test mapping

- E2E: NA — no user-facing flow; verified by running the CLI against fixture JSONL files and asserting DB state.
- Unit: `backend/app/cli/ingest.py` — file discovery under the activity log directory, NDJSON parse/skip behavior, fixed `harness-self` program-id scoping, idempotent re-run, and CLI-vs-MCP-push output-parity against `backend/app/services/ingest.py`.
- Manual: NA.

## Clarifications

## Decision log

- 2026-08-26 CLI run latency budget: no hard timeout, log progress per file — assumption, PRD gives no CLI-specific latency target (nearest analog, `rollup-rebuild`'s O(events) invariant, has no fixed number either).
- 2026-08-26 CLI auth/access model: no bearer token, access controlled by host/deployment execution rights — assumption, by analogy to `mint_ingest_token.py` (FR-ING-06), the only other local operator CLI in this epic; PRD doesn't state an access-control mechanism for FR-ING-08 directly.
- 2026-08-26 Observability event name: `cli_ingest_completed` (files_read, rows_read, inserted, rejected, duration_ms) — assumption, NFR-011 defines the logging mechanism but doesn't enumerate a CLI-ingest-specific event.
