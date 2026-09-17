# PGD-04 — Data Design

State & data management. Each concern is specified or marked `N/A — <reason>`.

## 1. Data model

No new table, column, or index. Reads the existing `usage_events` table (Postgres, SQLAlchemy
ORM, `services/api/app/models/ingestion.py`) — schema unchanged by this story.

### usage_events (postgres table, existing — read-only here)

| Field | Type | Key/Constraint | Class | Notes |
|---|---|---|---|---|
| program_id | str | part of `ix_usage_events_program_id_command` | — | filter predicate |
| command | str | part of `ix_usage_events_program_id_command` | — | verbatim passthrough on the wire (leading `/` preserved, never synthesized) |
| ts | datetime (tz-aware UTC) | — | — | range predicate (`ts >= range_start`) |
| id | — | PK | — | used only as `count()` target |

`program_commands` (`app/models/rollup.py::ProgramCommands`) is explicitly NOT read by this
story (D-01) — lifetime-only rollup, wrong shape for a ranged query. No write path touches it
either; BED-01's `rollup_rebuild` remains its sole writer.

## 2. Migrations

N/A — no schema change. `ix_usage_events_program_id_command` already exists and already
supports this query's `WHERE program_id = :pid` grouping.

## 3. Ownership & tenancy

No per-user or per-tenant scoping — `program_visibility()` (AUTH-03) is called once as an
open-aggregate veto gate (passes for any authenticated session, never filters by
`current_user.programs`), matching PGD-01/02/03. No row-level ownership check beyond
authentication; `.claude/rules/security-baseline.md`'s "validate untrusted input at trust
boundaries" is satisfied by the `range` Depends validation (400, not 422) and by `program_id`
being an opaque string path param with no existence lookup performed (D-02) — there is nothing
to authorize per-row since the query is a `GROUP BY` aggregate, not a row fetch.

## 4. Data classification & retention

No PII/sensitive field is added to the response. `command` values are Harness CLI command
names (e.g. `/arh-init`), not user-identifying. Retention of `usage_events` itself is owned by
its original ingest story (ING-02), unchanged here.

## 5. Consistency & concurrency

Single read-only `SELECT ... GROUP BY command` per request — no write, no transaction boundary
to declare, no concurrent-write conflict possible. No idempotency key needed (GET, no
side-effect).

## 6. Caching

No cache. Every request re-runs the aggregate query — matching PGD-01/02/03's precedent (no
cache layer exists on this router). `no TTL — no cache` is the deliberate answer, not an
oversight.

## 7. Ephemeral / session state

N/A on the backend (stateless request/response). On the frontend, once a consumer exists, the
selected range chip (`7d`/`30d`/`90d`) is client-owned UI state per DESIGN.md — out of scope
for this backend-only story.

## 8. Query-path & access-path performance

One grouped `SELECT command, count(*) FROM usage_events WHERE program_id = :pid AND ts >=
:range_start GROUP BY command ORDER BY count(*) DESC, command` per request — backed by
`ix_usage_events_program_id_command` (composite, leading `program_id`). No N+1: exactly one
query, matching PGD-02/03/SHP-02 (`.claude/rules/performance-baseline.md`). No pagination
needed — the mockup places no cap on row count (DESIGN.md § Not specified by the mockup) and
per-program distinct-command cardinality is bounded by the small, fixed set of Harness CLI
commands, not user-generated data. NFR-002 (≤2s range refresh) is met by construction, same
single-aggregate-query shape as PGD-02/03 which already meet it at seeded volume (PGD-04-TC-16
verifies with ≥5,000 rows / ≥10 commands).

## 9. Contract (API / interface)

Registered cross-story contract: `program-commands-api` (`docs/requirements/api.md#program-commands-api`,
`produced_by: PGD-04`, `consumed_by: [ARC-01, DEV-01, PMD-01, EMD-01]`). The concrete shape is
authored there (this story fills in the sketch — see PLAN.md § Task Breakdown T-08). This
section is a bookmark, not a copy:

Contract: `program-commands-api` → `docs/requirements/api.md#program-commands-api`

Route summary (full detail in the contract above and in `README.md`'s API table):
`GET /api/overview/program-detail/{program_id}/commands?range=7d|30d|90d` (default `30d`) →
`200 CommandsPanel { total_runs: str, items: [{command: str, count: int, barStyle: str}] }`;
`400 invalid_range`; `401` unauthenticated. No `404` (D-02).

## 10. Async & messaging

N/A — purely synchronous request/response; no event, job, or queue involved.
