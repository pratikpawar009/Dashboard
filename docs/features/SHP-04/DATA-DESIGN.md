# SHP-04 — Data Design

State & data management. Each concern is specified or marked `N/A — <reason>`.

## 1. Data model

No new table, no migration. Reads the existing `program_artifacts` table (owned by BED-01, populated by ING-03's `POST /api/ingest/artifacts`).

### `program_artifacts` (postgres table, existing — read-only for this story)

| Field | Type | Key/Constraint | Class | Notes |
|---|---|---|---|---|
| id | String | PK | — | not read by this story |
| program_id | String | part of `uq_program_artifacts_program_id_type` | — | request-path filter |
| type | String | part of `uq_program_artifacts_program_id_type` | — | one of the 5 canonical types; case-sensitive |
| count | Integer | required | — | passes through verbatim as raw int (D-03) |
| as_of_timestamp | DateTime | required | — | not read by this story (no freshness display on this panel) |

No PII/sensitive fields — program-level aggregate counts only.

## 2. Migrations

_N/A — no schema change._ `program_artifacts` and its unique index `uq_program_artifacts_program_id_type` on `(program_id, type)` already exist (BED-01, security-reviewed 2026-09-15).

## 3. Ownership & tenancy

Program-scoped resource, but **not row-level ownership-enforced** — `governance_visibility`'s cascade into `program_visibility` is deliberately open-aggregate (no `WHERE program_id IN current_user.programs` filter), matching every sibling route on `overview.py` (`/token-trend`, `/commands`, `/team`, `/session-time-series`). Enforcement here is persona-only: `governance_visibility` restricts the endpoint to `architect | product-manager | developer`, and a passing call is not proof of program membership. This is a deliberate, PRD-documented posture (`SHP-04-FR-3`), not an oversight — see `.claude/rules/security-baseline.md`'s ownership-check guidance, which this route satisfies via the persona gate rather than a `_load_owned` per-resource check (there is no per-user-owned row here; `program_artifacts` is a program-level aggregate, not a user-owned resource).

## 4. Data classification & retention

No PII/sensitive fields (see § 1). No new retention or deletion policy — this story only reads; `program_artifacts` retention is owned by ING-03/BED-01.

## 5. Consistency & concurrency

Read-only endpoint — no writes, no transaction boundary beyond the implicit single-statement read transaction the async SQLAlchemy session already provides. No idempotency key needed (GET, no side effects). No concurrent-write concern: this story never writes `program_artifacts`.

## 6. Caching

_N/A — no cache layer._ Single indexed lookup over at most 5 rows (NFR-001); no caching needed to meet the ≤3s panel-render budget. No TTL, no invalidation event to document.

## 7. Ephemeral / session state

Frontend `ArtifactsPanel` (D-04) holds local component state only: `status: "loading" | "ok" | "error"` and the fetched `ArtifactsData`, mirroring `ProgramTeamPanel`'s `useState` idiom. No URL-as-state (no query params — this panel has no range/filter control per `DESIGN.md`), no server-held per-connection state.

## 8. Query-path & access-path performance

Single `SELECT type, count FROM program_artifacts WHERE program_id = :program_id` — no `ORDER BY` needed since order is imposed by the fixed `_ARTIFACT_PRESENTATION` iteration in Python (D-03), not by the SQL. Backed by the existing unique index `uq_program_artifacts_program_id_type` (covers `program_id` as its leading column, so the `WHERE program_id = :program_id` predicate is index-scanned). At most 5 rows returned — no pagination needed (fixed 5-row response, closed vocabulary, per `REQUIREMENTS.md` § NFR Performance). No N+1: one query total, zero-fill happens in Python against the query result, not via 5 separate per-type queries.

## 9. Contract (API / interface)

Contract: artifacts-api → docs/requirements/api.md#artifacts-api

## 10. Async & messaging

_N/A — purely synchronous request/response. No event, job, or message produced or consumed by this story._
