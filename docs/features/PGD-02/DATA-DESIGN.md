# PGD-02 — Data Design

State & data management for the daily program token trend chart. Each concern is specified or marked `N/A — <reason>`.

## 1. Data model

No new table. This story reads an existing table (`program_token_series`, BED-01) read-only.

```
erDiagram
    program_token_series {
        string id PK
        string program_id "part of composite unique(program_id, date)"
        datetime date "part of composite unique(program_id, date)"
        bigint tokens
        int input_tokens
        int output_tokens
        int cache_read_tokens
        int cache_write_tokens
        datetime as_of_timestamp
    }
```

### `program_token_series` (postgres table, existing — `app/models/rollup.py::ProgramTokenSeries`)

| Field | Type | Key/Constraint | Class | Notes |
|---|---|---|---|---|
| id | String (uuid4) | PK | — | Owned by BED-01; not touched by this story |
| program_id | String | unique(program_id, date) | — | Query filter column; this story adds `WHERE program_id = :id AND date >= :range_start` |
| date | DateTime(timezone=True) | unique(program_id, date) | — | Grouping key; one row per calendar day per program |
| tokens | BigInteger | — | — | Summed into `period_total`; `points[].tokens` is this column's raw value |
| input_tokens / output_tokens / cache_read_tokens / cache_write_tokens | Integer | — | — | Not read by this story — `tokens` is the only column this endpoint consumes |
| as_of_timestamp | DateTime(timezone=True) | — | — | Not read by this story |

This story introduces no new entity, no new column, no new constraint. `id`/`input_tokens`/etc. above are cited only for completeness of the existing table this story reads from.

## 2. Migrations

_N/A — no schema change. `program_token_series` and its `uq_program_token_series_program_id_date` unique constraint (which backs this story's query) already exist on `origin/main`, shipped by BED-01. Research Condition C-3 confirmed no new index is required (REQUIREMENTS.md § Addressing Research Conditions)._

## 3. Ownership & tenancy

No new owned resource — this endpoint reads program-scoped rows filtered by the `program_id` path parameter, matching PGD-01's existing `program-detail` endpoint. Enforcement mechanism: the AUTH-03 `program_visibility(current_user, program_id)` veto gate (open-aggregate — any authenticated session passes for any `program_id`, per AC-7/D-03). This is not per-user ownership; it is org-wide-visible program telemetry by design (REQUIREMENTS.md § Constraints, story Decision log). No RLS policy, no `_load_owned` guard — the open-aggregate model is the accepted enforcement mechanism, unchanged from PGD-01.

## 4. Data classification & retention

No PII. `tokens`/`date`/`program_id` are aggregate usage telemetry, not personal data. Retention/encryption-at-rest policy is inherited unchanged from `program_token_series`'s existing BED-01 classification — this story adds no new retention rule and performs no writes (read-only `SELECT`).

## 5. Consistency & concurrency

Read-only endpoint — no write path, no transaction boundary to define, no idempotency key needed. A single `SELECT ... GROUP BY date` per request; no concurrent-write conflict is possible from this story's code. Underlying row freshness (how current `program_token_series` is relative to the ingest pipeline) is BED-01's concern, not re-specified here.

## 6. Caching

No cache layer. Every request issues a fresh grouped `SELECT` — matching SHP-02's `fetch_daily_token_series` precedent (no caching there either). `no TTL — always live query` is the deliberate choice: range-toggle refresh has its own 2s latency budget (NFR-002, TC-10) which a single indexed grouped SELECT meets without caching (research risk #3 mitigation).

## 7. Ephemeral / session state

Client-side: the selected range (`7d`/`30d`/`90d`) is component-local React state inside `DailyTokenTrendChart` (`useState`, initial value `"30d"` per DESIGN.md's mockup default), not persisted to a store, URL param, or session — consistent with `ProgramDetailView.tsx`'s existing pattern of component-local state for UI-only selections (e.g. `isSwitcherOpen`). Switching programs (via `ProgramSwitcher`) does not currently reset this component's range state or refetch — see § 9 Contract for the fetch trigger; range resets to the component's own default `"30d"` on every fresh mount, which occurs when `DailyTokenTrendChart` remounts under a new `programId` key (mirroring `ProgramSummaryCards`' re-render-on-`result.data` pattern already in `ProgramDetailView.tsx`).

## 8. Query-path & access-path performance

Single grouped `SELECT date_trunc('day', date), sum(tokens) FROM program_token_series WHERE program_id = :id AND date >= :range_start GROUP BY 1`, backed by the existing `uq_program_token_series_program_id_date` unique index's leading `program_id` column (C-3, no new index needed) — same one-grouped-SELECT-per-request shape as SHP-02's `fetch_daily_token_series`, so no N+1. Zero-padding (`_zero_padded_points`) is a pure in-memory walk over the fixed range length (7/30/90 iterations), no additional query. No pagination needed — the response is bounded to a fixed maximum of 90 points by the `{7d,30d,90d}` range vocabulary itself, so no offset/cursor scheme applies here (`.claude/rules/performance-baseline.md`'s pagination requirement is satisfied by this fixed upper bound, same reasoning SHP-02 applies).

## 9. Contract (API / interface)

Contract: `program-token-trend-api` → `docs/requirements/api.md#program-token-trend-api`

The registered cross-story contract sketch (`produced_by: PGD-02`, `consumed_by: [EMD-01]`) is filled with this story's concrete shape directly in `docs/requirements/api.md` (see Task T-11) — not duplicated here. Summary for local orientation only: `GET /api/overview/program-detail/{program_id}/token-trend?range=7d|30d|90d` (default `30d`), response `ProgramTokenTrendResponse {points: list[{date: str, tokens: int}], period_total: int, avg_per_day: int}` — raw integers throughout (D-02/D-04), RBAC via open-aggregate `program_visibility`, 400 `invalid_range` for an out-of-set `range`, 401 for a missing/invalid bearer token.

## 10. Async & messaging

_N/A — purely synchronous request/response; no event, job, or queue is produced or consumed by this story._
