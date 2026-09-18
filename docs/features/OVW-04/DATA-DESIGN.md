# OVW-04 — Data Design

State & data management. Each concern is specified or marked `N/A — <reason>`.

## 1. Data model

No new table. Reads the existing `program_summary` rollup table (owned by BED-01), gains one new
index.

### `program_summary` (postgres table, existing — one column newly indexed)

| Field | Type | Key/Constraint | Class | Notes |
|---|---|---|---|---|
| program_id | String | unique | — | passthrough to `href`/`program_id` on the wire |
| name, type, description, icon | String | required | — | passthrough verbatim (D-04) |
| monthly_token_sparkline | JSONB | required, nullable data in practice | — | validated before use (§ 5, research C-2) |
| tokens | BigInteger | **new: `ix_program_summary_tokens`** (ADR-0017) | — | `ORDER BY tokens DESC` (FR-2) |
| releases, features, active_contributors | Integer | required | — | fed through `format_number()` into `metrics[]` (D-03) |
| repos_with_harness_installed, repos_total | Integer | required | — | raw ints on the wire (FR-1) |

No PII/sensitive fields — program-level aggregates only, no per-user identity.

## 2. Migrations

Forward: `009_program_summary_tokens_index.py` — `op.create_index("ix_program_summary_tokens", "program_summary", ["tokens"])`. Rollback: `op.drop_index(...)` (clean, no data loss — index-only change). No backfill needed (an index build does not alter row data). Not zero-downtime-hardened (`postgresql_concurrently=True` not used) — accepted tradeoff, matching ADR-0015/ADR-0016 precedent (no deploy runbook/CI requiring a maintenance window yet).

## 3. Ownership & tenancy

_N/A — org-wide resource, no per-user/per-tenant scoping._ `program_summary` has no owner column; access is gated entirely by persona (`org_access`, cio-only) at the API layer, not by row-level ownership. This mirrors `/api/overview/summary`'s own unscoped-read + persona-gate pattern, not `program_visibility`'s open-aggregate-per-resource pattern (there is no single `program_id` in the request path here — it's a list of all programs).

## 4. Data classification & retention

No PII/sensitive fields (see § 1). Retention: `program_summary` rows are rebuilt by the existing org-rollup ingest pipeline (BED-01/ADR-0012 territory) — this story adds no new retention or deletion policy; it only reads.

## 5. Consistency & concurrency

Read-only endpoint — no writes, no transaction boundary beyond the implicit single-statement read transaction FastAPI/SQLAlchemy's async session already provides. No idempotency key needed (GET, no side effects other than the D-06 client-side telemetry log, which is fire-and-forget and not part of any transaction).

## 6. Caching

_N/A — no TTL, no cache._ Every request re-queries `program_summary` directly (same as `/api/overview/summary`'s org-rollup read) — no `program_visibility`-style 300s roster cache applies here, since this endpoint reads `program_summary`, not `program_roster`.

## 7. Ephemeral / session state

Frontend: no client-side ephemeral state — the board is server-rendered on initial page load only, no client refetch, no URL-as-state (no query params exposed in the UI; pagination is API-level only per PO resolution #3). `tokenStore`'s existing access-token-in-memory pattern (`apps/web/src/lib/tokenStore`) is reused unchanged for the `callWithAuth` wrapper around `fetchProgramBoard`.

## 8. Query-path & access-path performance

Two queries per request (mirrors `fetch_program_releases`'s paired-query pattern): (1) `SELECT * FROM program_summary ORDER BY tokens DESC OFFSET :offset LIMIT :limit` — index-backed via `ix_program_summary_tokens` (ADR-0017, research C-1); (2) `SELECT count(*) FROM program_summary` for `total` — full-table count, acceptable at this table's expected scale (one row per program, not per event; no `WHERE` clause to index against). No N+1: the JSONB `monthly_token_sparkline` column and all other card fields come from the same row, no per-card follow-up query. Pagination is cursor-free `page`/`page_size` (offset-based) per the `program_releases` precedent — acceptable at program-count scale (tens to low hundreds), not event-count scale.

## 9. Contract (API / interface)

Feature-internal (no `produced_by`/`consumed_by` registration in `docs/requirements/api.md` — confirmed via `docs/stories/OVW-04.md`: `consumed_by: []`). Described inline:

**REST** — `GET /api/overview/program-board`

Request: none besides the bearer token (standard `get_current_user` dependency); optional `?page` (default `1`, `ge=1`) and `?page_size` (default `20`, `ge=1`, clamped to `100`, D-02).

Response `200`:
```json
{
  "items": [
    {
      "program_id": "string", "name": "string", "type": "string", "icon": "string",
      "description": "string", "href": "/programs/{program_id}",
      "sparkline": {
        "points": [{"month": "string", "tokens": 0}],
        "mom_change_percent": 0.0,
        "mom_direction": "up | down | flat | null"
      },
      "metrics": [{"glyph": "string", "label": "string", "value": "string"}],
      "repos_with_harness_installed": 0,
      "repos_total": 0
    }
  ],
  "page": 1, "page_size": 20, "total": 0
}
```

Errors: `403` (non-CIO, no data body, `org_access` gate) · `422` (`page`/`page_size` < 1) · `401` (missing/invalid bearer token).

## 10. Async & messaging

_N/A — purely synchronous read; no event/job/queue involved._
