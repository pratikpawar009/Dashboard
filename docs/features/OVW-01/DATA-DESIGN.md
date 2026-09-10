# OVW-01 — Data Design

State & data management for the org-summary-cards + adoption-indicator page. Each of the ten
concerns is specified or marked `N/A — <reason>`.

## 1. Data model

No new entity, no schema change. `GET /api/overview/summary` reads two existing, already-migrated
tables (BED-01/`db-schema`), both singleton-shaped.

### `org_summary_rollup` (postgres table — read-only reference, not modified by this story)

| Field | Type | Key/Constraint | Class | Notes |
|---|---|---|---|---|
| `org_id` | String | unique (`org-1`) | — | selects the single org-wide row |
| `programs_using_ai_count` | Integer | required | — | card 1 value + `programs_using_ai.count` |
| `programs_total` | Integer | required | — | `programs_using_ai.total`; `0` drives the AC-2/FR-4 null-percent path |
| `total_token_consumption` | BigInteger | required | — | card 2, via `format_number()` |
| `lines_of_code_generated` | BigInteger | required | — | card 3, via `format_number()` |
| `releases_using_harness` | Integer | required | — | card 4, via `format_number()` |
| `repos_with_harness_installed` | Integer | required | — | card 5, via `format_number()` — a **plain count**, not a ratio |
| `repos_total` | Integer | required | — | **not rendered.** No card reads it; kept for the `db-schema` contract's own shape |
| `programs_using_ai_count` / `programs_total` | Integer | required | — | card **1**, rendered as the literal ratio `"{count} / {total}"`, exempt from `format_number()`; also drives `programs_using_ai` and card 1's `sub` |

**Corrected 2026-09-10 (code-review finding F-1).** These rows described card 5 as a
ratio over `repos_total` and card 1 as a `format_number()` count — the *pre-correction*
design. `DECISIONS.md` D-02 reversed that on 2026-09-09 after extracting the mockup's
embedded sample-data script: the ratio belongs to **card 1**, and card 5 is a plain
count that never reads `repos_total`. The shipped schema, handler, `api.md`, `README.md`
and every test already implement the corrected form; this file was the one artefact the
propagation sweep missed. Recorded rather than silently overwritten, because the miss is
the instructive part: flag AF-03's own lesson was that a post-approval correction needs a
propagation sweep — and a sweep still left one behind.

Row absent (fresh/never-ingested org, AC-2) → all-zero fallback envelope; no other
`org_summary_rollup` column (`as_of_timestamp`, `created_at`, `updated_at`) is read by this story.

### `system_metadata` (postgres table — read-only reference, not modified by this story)

| Field | Type | Key/Constraint | Class | Notes |
|---|---|---|---|---|
| `key` | String | PK (`"ingestion"`) | — | selects the freshness singleton |
| `last_successful_run_at` | DateTime(tz) | required | — | read via `FreshnessAccessor`; never returned to the client (AC-6, backend-only) |

Row absent → `FreshnessAccessor` raises `HTTPException(500, "ingestion job may not have run yet")`
(AC-7) — this read is unconditioned by whether `org_summary_rollup` returned a row (FR-3).

## 2. Migrations

N/A — no schema change. Both tables already exist at head (`004_rollup_query_indexes`); this story
is read-only against them.

## 3. Ownership & tenancy

Neither table carries a per-row owner column — both are org-wide singletons (`org_id`/`key` unique
keys, not per-user/per-tenant). Access is gated once per request by `org_access(current_user)`
(`rbac-checks`, AUTH-03, `app/core/rbac.py`) — `cio`-only; every other persona denies with a bare
403 (no data body, AC-3). This is the entire enforcement mechanism: there is no per-resource
ownership check to perform, since the resource itself (the org-wide rollup) has exactly one row and
no narrower scope to leak across. `rbac_check_org_access` logs both outcomes (AC-8, NFR-011).

## 4. Data classification & retention

No PII in the fields this endpoint returns — all fields are aggregate org-wide counts/ratios, no
user- or program-identifying data. No new retention policy introduced; retention of both source
tables is BED-01's/ING-02's concern, unchanged here.

## 5. Consistency & concurrency

Two independent single read-only `SELECT`s (freshness, then rollup — see § Ordering below), zero
writes, no transaction boundary beyond the implicit read transaction each `AsyncSession`/accessor
call opens. No idempotency key needed (GET is naturally idempotent). No concurrent-write handling
needed — this story performs no writes to either table.

**Ordering (FR-3, the one invariant this story is strict about)**: the freshness read
(`FreshnessAccessor.get_last_successful_run()`) runs unconditioned by the `org_summary_rollup`
lookup's outcome — always, exactly once per request, before the rollup query. A raised
`HTTPException` from the freshness call propagates as the response (500) even on an otherwise-valid
all-zero payload. This is what keeps AC-7's "clear error, not a silent/empty state" true on a
genuinely fresh database, where both rows are absent together (`OVW-01-TC-04`).

## 6. Caching

`FreshnessAccessor` carries its own 300s TTL cache (`BED-04`/`freshness-api`), but this route
constructs a **new** `FreshnessAccessor()` instance per request (no `app.state` singleton exists
yet, per `freshness-api`'s own contract note that each consumer owns/shares its instance) — so in
practice this cache never warms across requests for this route (research risk #4, MED, accepted;
no task addresses it, per the verification rule for MED/LOW risks). No other cache exists in this
story's data path — `org_summary_rollup` is read fresh every request (single indexed row, <100ms
measured in research).

## 7. Ephemeral / session state

N/A — no client-side state. The page is a single server-side fetch with no client refetch, no URL
query state, no form state.

## 8. Query-path & access-path performance

Both reads are single indexed-row lookups (`org_summary_rollup.org_id` unique index,
`system_metadata.key` primary key) — no joins, no fan-out, no pagination needed (each table has at
most one relevant row). Research measured the rollup read at <100ms; `OVW-01-TC-08` asserts exactly
one `SELECT` against `org_summary_rollup` (no N+1) and a handler duration budget of 500ms, well
inside NFR-001's 3s page-render budget (`.claude/rules/performance-baseline.md`).

## 9. Contract (API / interface)

Contract: `overview-summary-api` → `docs/requirements/api.md#overview-summary-api` (concrete shape
filled by this plan — response model, card literals, freshness-ordering, RBAC, error shape).
`consumed_by: []` — no downstream story consumes this contract yet.

Consumed (unchanged by this story):
- `rbac-checks` → `docs/requirements/api.md#rbac-checks` (AUTH-03) — `org_access` only.
- `api-conventions` → `docs/requirements/api.md#api-conventions` (BED-02) — `format_number()`,
  `compute_adoption_percent()`.
- `freshness-api` → `docs/requirements/api.md#freshness-api` (BED-04) — `FreshnessAccessor`.
- `db-schema` → `docs/requirements/data.md#db-schema` (BED-01) — `org_summary_rollup`,
  `system_metadata` tables, read-only.

## 10. Async & messaging

N/A — purely synchronous request/response; no queue, topic, or background job is introduced.
