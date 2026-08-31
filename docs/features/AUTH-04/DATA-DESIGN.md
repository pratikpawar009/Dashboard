# AUTH-04 — Data Design

State & data management for `GET /api/programs`. Each concern is specified or marked
`N/A — <reason>`.

## 1. Data model

No new entity. Reads the existing `program_summary` table (Postgres, BED-01-owned,
`app/models/rollup.py::ProgramSummary`) read-only — no columns added, no new table.

| Field (read) | Type | Key/Constraint | Class | Notes |
|---|---|---|---|---|
| `program_id` | str | unique | — | scoping key: `WHERE program_id IN current_user.programs` (non-cio) / no filter (cio) |
| `name` | str | — | — | maps to response `label` |

Every other `ProgramSummary` column (metrics, `icon`, `type`, `description`, `as_of_timestamp`)
is out of scope for this endpoint's SELECT — ADR-0005 excludes `type`/`description` from the
response, and the metrics columns belong to `program-detail-api`/`program-board-api`.

## 2. Migrations

N/A — no schema change. `dotStyle` is a computed value (D-01), not a persisted column.

## 3. Ownership & tenancy

No row-level ownership column change. Enforcement is the existing AUTH-01/AUTH-03 model:
scoping is derived server-side from `current_user.programs` (parsed from the verified JWT's
`groups` claim), never a client-supplied filter (AUTH-04-NFR-security, TC-18) and never a DB
row-level-security policy. `program_visibility` (AUTH-03) is called once as a session-validity
veto gate — it does not perform the scoping itself (AUTH-04-FR-2).

## 4. Data classification & retention

No PII in the response body (`program_id`, `label`, `href`, `dotStyle` are non-PII program
attributes). The one PII-adjacent surface is the `programs_list_returned` log event, whose
payload is an exact 4-field allowlist — `{user_id, persona, returned_count, timestamp}` — no
`email`, `groups`, or request path (AUTH-04-FR-1, condition C-1). `program_summary` retention is
unchanged from BED-01 — this story only reads it.

## 5. Consistency & concurrency

N/A — single read-only `SELECT`, no writes, no transaction boundary beyond the implicit
per-request session, no idempotency concern.

## 6. Caching

No new cache. Persona resolution reuses AUTH-02's existing per-worker 300s-TTL
`PersonaResolver` cache unchanged — this endpoint adds no cache of its own for the
`program_summary` read (dataset is small; ~100-row worst case per the C-4 baseline).

## 7. Ephemeral / session state

N/A — stateless, per AUTH-01's `session` contract (no server-side session store). The endpoint
receives no active-program input; `current`/`rowStyle` are client-derived by the switcher
consumer (ADR-0005), not server state.

## 8. Query-path & access-path performance

Single query: `SELECT ... FROM program_summary [WHERE program_id IN (:ids)]` — one round trip,
no N+1, indexed on `program_summary`'s unique `program_id` constraint. No pagination (PRD
Scope: ~9-program org size, no `api-conventions`/BED-02 dependency for this story) — the C-4
condition validates this unpaginated shape still holds its budget at 2x scale (100 seeded, 50
scoped, p95 < 300ms end-to-end: persona resolution + query + serialization).

## 9. Contract (API / interface)

Contract: `programs-api` → `docs/requirements/api.md#programs-api`. Already filled with the
concrete `fields`/`authority`/`excluded`/`client_derived` keys at the research/PRD gate (ADR-0005
resolution) — no further edit needed this phase; verified concrete, not a decomposition-time
sketch.

## 10. Async & messaging

N/A — purely synchronous request/response; no event, queue, or scheduled job.
