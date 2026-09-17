# PGD-06 — Data Design

State & data management for the daily session-time series endpoint. Each concern is specified or
marked `N/A — <reason>`.

## 1. Data model

No new table, no new column. This story reads an existing table (`session_series`, BED-01)
read-only.

```
erDiagram
    session_series {
        string id PK
        string org_id "part of composite unique(org_id, program_id, member_id, date)"
        string program_id "part of composite unique; query filter column"
        string member_id "part of composite unique; nullable in schema but never null in practice (D-01)"
        datetime date "part of composite unique; grouping key"
        int session_time_seconds
        datetime as_of_timestamp
    }
```

### `session_series` (postgres table, existing — `app/models/rollup.py::SessionSeries`)

| Field | Type | Key/Constraint | Class | Notes |
|---|---|---|---|---|
| id | String (uuid4) | PK | — | Owned by BED-01; not touched by this story |
| org_id | String | part of `uq_session_series_org_id_program_id_member_id_date` | — | NOT read or filtered by this story (DECISIONS.md D-03) — hardcoded single-org singleton (`_ORG_ID = "org-1"`), no multi-tenancy exists |
| program_id | String | part of the same unique constraint | — | Primary query filter: `WHERE program_id = :pid` |
| member_id | String, nullable in schema | part of the same unique constraint | — | Never actually null in production data (`_build_session_series` always sets it, D-01); optional query filter when `?member_id=` is supplied |
| date | DateTime(timezone=True) | part of the same unique constraint | — | Grouping key; one row per (program, member, day) |
| session_time_seconds | Integer | — | — | Summed into `period_total_seconds`; `points[].session_time_seconds` is this column's raw value (or its cross-member SUM for the org-wide view) |
| as_of_timestamp | DateTime(timezone=True) | — | — | Not read by this story |

This story introduces no new entity, no new column, no new constraint, no new index.

## 2. Migrations

_N/A — no schema change. `session_series` and its `uq_session_series_org_id_program_id_member_id_date`
unique constraint already exist on `origin/main`, shipped by BED-01. REQUIREMENTS.md's corrected
Addressing Research Conditions (C-1) explicitly states no new migration ships in this story — see
DECISIONS.md D-02 for the accepted no-new-index rationale._

## 3. Ownership & tenancy

No new owned resource. This endpoint reads program-scoped rows filtered by the `program_id` path
parameter, matching every other PGD sibling. Enforcement mechanism: `program_visibility(current_user,
program_id)` (AUTH-03, open-aggregate — any authenticated session passes for any `program_id`) gates
the unfiltered/self view; `member_in_program_visibility(current_user, program_id, member_id)` (self
OR cio, called AFTER `program_visibility` per its own internal contract) additionally gates a
non-self `member_id` filter, called BEFORE any `session_series` query executes (PGD-06-FR-6,
research Condition C-3). No RLS policy, no `_load_owned` guard — the open-aggregate model is the
accepted enforcement mechanism, unchanged from PGD-02/04/05. `org_id` plays no role in tenancy here
(DECISIONS.md D-03).

## 4. Data classification & retention

No PII. `session_time_seconds`/`date`/`program_id`/`member_id` are aggregate usage telemetry — the
`member_id` is an opaque internal identifier, not a name or email. Retention/encryption-at-rest
policy is inherited unchanged from `session_series`'s existing BED-01 classification — this story
adds no new retention rule and performs no writes (read-only `SELECT`). Soft-deleted roster members
(`program_roster.removed_at` populated) still have their historical `session_series` rows included
in aggregates — the query filters only on `session_series` data, never on roster status (research
Condition C-4, `PGD-06-TC-13`).

## 5. Consistency & concurrency

Read-only endpoint — no write path, no transaction boundary to define, no idempotency key needed.
One grouped `SELECT` per request (org-wide) or one filtered `SELECT` per request (member-scoped);
no concurrent-write conflict is possible from this story's code. Underlying row freshness (how
current `session_series` is relative to the ingest pipeline) is BED-01/BED-03's concern
(`rebuild_program_rollups()`, already verified to run on every ingest) — not re-specified here.

## 6. Caching

No cache layer. Every request issues a fresh `SELECT` — matching every other PGD sibling
(`fetch_program_token_trend`, `fetch_program_team`, `fetch_program_commands`), none of which cache.
`no TTL — always live query` is the deliberate choice: the 2s range/member-filter refresh budget
(NFR-002, `PGD-06-TC-17`) is met by a single aggregate query without caching, per the existing
sibling precedent.

## 7. Ephemeral / session state

_N/A — no `apps/web` component ships in this story (DECISIONS.md D-05). The range/member-filter
selection UI state (where it would live: component-local React state, matching
`DailyTokenTrendChart`'s existing `useState` pattern) is deferred to the follow-on story that
renders the chart against a real design._

## 8. Query-path & access-path performance

Org-wide view: one grouped `SELECT date, SUM(session_time_seconds) FROM session_series WHERE
program_id = :pid AND date >= :range_start GROUP BY date` — no `member_id` filter, so it does not
benefit from the existing unique constraint's leading `member_id` position; it scans by
`(org_id, program_id, date)`-equivalent predicates, a strict prefix-minus-one of the existing
4-column constraint. Member-scoped view: one `SELECT date, session_time_seconds FROM session_series
WHERE program_id = :pid AND member_id = :member_id AND date >= :range_start` — this shape DOES
match the constraint's `(program_id, member_id, date)` prefix once `org_id` is fixed per request,
so it is fully indexed. Both shapes are exactly one query per request, no N+1
(`.claude/rules/performance-baseline.md`). DECISIONS.md D-02 records the accepted no-new-index
choice for the org-wide shape at current data volume; `PGD-06-TC-17` is the mandatory perf test
(≤2s at ≥5,000 rows / ≥50 members / 90 days, single-query assertion). Zero-padding is a pure
in-memory walk over the fixed range length (7/30/90 iterations), no additional query — mirroring
`_zero_padded_points` in `program_detail_token_trend.py`. No pagination needed — response is
bounded to a fixed maximum of 90 points by the `{7d,30d,90d}` range vocabulary itself.

## 9. Contract (API / interface)

Contract: `program-session-series-api` → `docs/requirements/api.md#program-session-series-api`

The registered cross-story contract sketch (`produced_by: PGD-06`, `consumed_by: [EMD-01]`) is
filled with this story's concrete shape directly in `docs/requirements/api.md` (see Task T-11 in
`tasks.json`) — not duplicated here. Summary for local orientation only: `GET
/api/overview/program-detail/{program_id}/session-time-series?range=7d|30d|90d&member_id=<optional>`
(default range `30d`), response `SessionSeriesResponse {points: list[{date: str,
session_time_seconds: int}], period_total_seconds: int, avg_seconds_per_day: int}` — raw integers
throughout (DECISIONS.md D-04), RBAC via `program_visibility` (unfiltered/self) +
`member_in_program_visibility` (non-self `member_id`, gate-before-query per FR-6), 400
`invalid_range` for an out-of-set `range`, 401 for a missing/invalid bearer token, no 404 for an
unknown `program_id` (all-zero series instead).

## 10. Async & messaging

_N/A — purely synchronous request/response; no event, job, or queue is produced or consumed by
this story. `session_series` freshness is produced by BED-03's existing `rebuild_program_rollups()`
pipeline, out of scope for this story's own async surface._
