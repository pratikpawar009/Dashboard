# Story: ING-03 — POST /api/ingest/artifacts

**Epic**: ING
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#42 (https://github.com/pratikpawar009/Dashboard/issues/42)

## User story

As the MCP server's `push_artifacts` tool (and any other bearer-token-authenticated ingest client), I want to POST a program's per-type artifact counts to a single endpoint, so that the Artifacts Generated panel and downstream governance views always reflect the latest counts without manual entry.

## Acceptance criteria

1. Given a valid, non-revoked, non-expired ingest token whose `allowed_program_ids` includes the target `program_id` (or is the wildcard `"*"`), when `POST /api/ingest/artifacts` is called with `{program_id, kind:"artifacts", counts, as_of}` and every key in `counts` is one of the 5 canonical types, then the response is `200` and each provided type's row in `program_artifacts` is upserted with the given count and `as_of_timestamp` (per FR-ING-05).
2. Given a request with no bearer token, or a token whose hash has no match, is revoked, or is expired, when `POST /api/ingest/artifacts` is called, then the response is `401` (per `ingest-token-auth` contract).
3. Given a valid token whose `allowed_program_ids` does not include the target `program_id` and is not the wildcard `"*"`, when `POST /api/ingest/artifacts` is called, then the response is `403` (per `ingest-token-auth` contract).
4. Given a `counts` payload containing a key outside the 5 canonical types (`prd`, `user_story`, `test_case`, `arch_diagram`, `api_spec`), when `POST /api/ingest/artifacts` is called, then the response is `400` and no row is written for the unknown type (per FR-ING-05, PRD §8.4 `program_artifacts` schema).
5. Given the identical payload is POSTed twice, when the second request completes, then `program_artifacts` holds the same rows/counts as after the first request — one-transaction idempotent upsert, no duplicate rows (per FR-ING-05, NFR-012).
6. Given a `counts` payload that lists only some of the 5 canonical types, when `POST /api/ingest/artifacts` is called, then only the listed types are upserted and the stored counts for omitted types are left unchanged (not zeroed or deleted).

## Non-functional requirements

- Performance: p95 < 300ms for a single request (upsert of ≤5 rows, one transaction, no rollup rebuild) — assumption, PRD gives no explicit latency budget for this endpoint.
- Security: bearer-token auth, authorization scoped by `allowed_program_ids`, never session-cookie auth (per NFR-006).
- Accessibility: N/A — backend endpoint, no UI surface in this story.
- Observability: structured JSON log event (e.g. `ingest_artifacts_write`, fields: `program_id`, `token_label`, `types_written`) on every write — assumption, extending NFR-011's structured-logging convention, which names an RBAC/telemetry event set but no ingest-artifacts-specific event.

## Dependencies

- Upstream: ING-01 via `ingest-token-auth` contract (`docs/requirements/auth.md#ingest-token-auth`) — bearer hash lookup (401 if missing/revoked/expired) and program-scope check (403 if target program not in `allowed_program_ids` and no wildcard). BED-01 via `db-schema` contract (`docs/requirements/data.md#db-schema`) — consumes the `program_artifacts` table (unique `[program_id, type]`, `type` one of `prd|user_story|test_case|arch_diagram|api_spec`, `count`, `as_of_timestamp`) and the `ingest_tokens` table that BED-01's migrations create.
- Downstream: ING-04 consumes this story's `ingest-artifacts-api` contract (`docs/requirements/api.md#ingest-artifacts-api`) to implement the `push_artifacts` MCP tool.

## Test mapping

- E2E: NA — no UI in this story; the Artifacts Generated panel (reading `program_artifacts`) covers rendering separately.
- Unit: `backend/app/routers/ingest.py`, `backend/app/services/ingest.py` — auth/authz paths (401/403), canonical-type validation (400), idempotent upsert, partial-payload path.
- Manual: NA

## Clarifications

## Decision log

- 2026-08-26 Canonical artifact types: `prd`, `user_story`, `test_case`, `arch_diagram`, `api_spec` (per PRD §8.4 `program_artifacts` schema, `docs/prd/ai-sdlc-adoption-dashboards.md` line 499).
- 2026-08-26 Partial-payload semantics: omitted types left unchanged, not zeroed — assumption, PRD names idempotent upsert (FR-ING-05) but not partial-payload behavior; zeroing on omission would let a partial push silently erase counts.
- 2026-08-26 Performance budget p95 < 300ms — assumption, no PRD budget given; sized to a single small-row upsert with no rollup rebuild (contrast BED-04's <10ms cached-read budget, which is a different operation shape).
- 2026-08-26 Observability event name `ingest_artifacts_write` — assumption, extending NFR-011's structured-logging convention; PRD's named event list does not include an ingest-artifacts event.
- 2026-08-26 Success response code: `200` (AC1) — assumption, PRD names `401`/`403` explicitly (`ingest-token-auth` contract) but no explicit code for a successful artifacts upsert; standard REST success code, consistent with the `200` used for other successful ingest-adjacent responses (e.g. OVW-04's empty-result case).
