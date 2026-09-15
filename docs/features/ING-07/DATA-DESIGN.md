# ING-07 — Data Design

State & data management for the Admin GitHub repo-scan endpoint. Each concern is
specified or marked `N/A — <reason>`.

## 1. Data model

No new tables or columns. The endpoint writes to the existing singleton row on
`org_summary_rollup` (BED-01 / `docs/requirements/data.md#db-schema`).

### org_summary_rollup (postgres table — existing, additive-write-only)

Mutating columns (write scope of THIS feature):

| Field | Type | Key/Constraint | Class | Notes |
|---|---|---|---|---|
| `org_id` | `String` | `unique`, default `'org-1'` — singleton | — | Filter target; never mutated by this feature. |
| `repos_total` | `Integer` | — | — | Written to the scan's total repo count. |
| `repos_with_harness_installed` | `Integer` | — | — | Written to the count of repos whose default branch carries `.harness/program.yaml`. |
| `as_of_timestamp` | `DateTime(timezone=True)` | — | — | Written to `datetime.now(UTC)` at successful upsert; also echoed in the response body (FR-1). |
| `updated_at` | `DateTime(timezone=True)` | — | — | Set to `datetime.now(UTC)` on upsert (existing model convention). |

Columns NOT touched (BED-03 owns): `programs_using_ai_count`, `programs_total`,
`total_token_consumption`, `lines_of_code_generated`, `releases_using_harness`.
Race with BED-03 accepted per D-02.

### External data source — GitHub REST API (consumer)

| Resource | Shape | Notes |
|---|---|---|
| `GET https://api.github.com/orgs/{org}/repos?per_page=100&page={n}` | Paginated JSON list; each element carries `name` and `default_branch`. | Pagination bounded ≤2 pages for ≤200 repos (PRD NFR). |
| `GET https://api.github.com/repos/{org}/{repo}/contents/.harness/program.yaml?ref={default_branch}` | 200 = installed, 404 = not-installed; body deliberately discarded — mere presence is the signal (Story Clarifications 2026-09-15). | One call per repo. |

## 2. Migrations

_N/A — no schema change_. `org_summary_rollup.repos_total`,
`repos_with_harness_installed`, `as_of_timestamp` already exist and are already
mutable per BED-01 / BED-03. Zero Alembic changes; `docs/adr/README.md` and
`services/api/migrations/` untouched.

## 3. Ownership & tenancy

Singleton scope — `org_id='org-1'` is currently the only row and this endpoint
only ever writes to that row. Enforcement mechanism: server guard at the router
via `ingest-token-auth` bearer + wildcard-strict scope re-check (FR-2, D-05).
No RLS, no per-tenant partitioning, no client cache. Multi-org expansion is
out of scope for ING-07 (would require an `org_id` query/body parameter and a
matching `org_summary_rollup` upsert filter — an unshipped, unplanned change).

## 4. Data classification & retention

`GITHUB_TOKEN` (PAT) is the only sensitive value the feature handles. It is:

- read from `Settings.github_token` server-side only (never from a request header),
- never logged (raw or hashed) per `.claude/rules/security-baseline.md`,
- never included in the response body, exception messages, or the
  `admin_scan_completed` structured event's field allowlist
  (`repos_total`, `repos_with_harness_installed`, `duration_ms`, `github_api_calls`).

Raw GitHub response bodies and request headers are likewise never logged
(TC-17 asserts this against a sentinel PAT + upstream error body containing it).
Retention: no new persistent columns; the counts written to `org_summary_rollup`
are already-retained best-effort aggregates (not PII).

## 5. Consistency & concurrency

**Per-request atomicity (FR-4)**: the entire scan (GitHub list + N probes + rollup
upsert) commits as one transaction on the request-scoped `AsyncSession`. Any GitHub
failure (retry-exhausted 429/5xx, `httpx.ReadTimeout`), any missing-config check,
or any auth failure aborts before the rollup upsert commits. TC-11 and TC-15
assert byte-identical prior-value preservation on 502; TC-07/TC-08 assert on 500.

**Concurrent-writer race (D-02, accepted)**: BED-03's `rebuild_org_rollups()`
(dispatched out-of-band via `BackgroundTasks` per ADR-0012) and this endpoint's
upsert both write the singleton row. Last-write-wins, no lock, no version column.
TC-20 asserts the endpoint completes 200 under a concurrent rebuild without
deadlock or serialisation error.

**Idempotency**: two consecutive scans over unchanged GitHub state produce
identical repo counts (TC-19). `as_of_timestamp` advances on every write and is
NOT part of the equality assertion.

## 6. Caching

_N/A — no cache_. Every request re-lists the org and re-probes every repo.
Rationale: a caller-triggered admin scan by definition wants fresh state.
Adding a cache would defeat the purpose (the whole point of invoking the endpoint
is to refresh the counts). GitHub itself has an `ETag` cache but honoring it is
out of scope — the perf budget (p95 ≤ 10 s for ≤200 repos at 20 ms mocked
latency, TC-16) already fits without it.

## 7. Ephemeral / session state

_N/A — stateless request handler_. No per-connection state, no server session,
no client store. `httpx.AsyncClient` is constructed per-request inside
`repo_scan.py` and disposed via `async with`; no module-level client is kept
(unlike `app/auth/jwks.py`'s process-wide `JwksCache`, which serves a different
lifecycle — deliberate divergence per D-03).

## 8. Query-path & access-path performance

**Write path**: one `INSERT ... ON CONFLICT (org_id) DO UPDATE` against the
singleton row. O(1). The existing `unique(org_id)` index (`db-schema` §
`org_summary_rollup`) is the conflict target.

**GitHub fan-out**: bounded — 2 list pages + N probes where N ≤ 200 (PRD NFR).
Explicit `httpx.Timeout(10.0)` per call; ≤3 retries with jittered exponential
backoff bounded at 2 s per delay (`app.core.retry.max_delay_s`). Per-repo probes
run sequentially in v1 (concurrent `asyncio.gather` is a `rev:mechanical`
follow-up if the perf budget slips — see D-04). At 20 ms mocked latency
`TC-16` measures p95 ≤ 10 000 ms over N=30 iterations.

**No N+1 on the DB side**: one SELECT + one UPSERT per request against a
1-row table. Pagination not applicable (singleton write).

## 9. Contract (API / interface)

**Registered cross-story contract** — this feature *produces* `admin-scan-api`
(`docs/requirements/api.md#admin-scan-api`, `consumed_by: []`).

Contract: `admin-scan-api` → `docs/requirements/api.md#admin-scan-api`

The contract's `shape:` block currently specifies `endpoint`, `auth`, `effect`
only — no response body. PRD ING-07-FR-1 pins `ScanReposResponse` as this
story's assumed shape (D-01). Extending the contract itself is a non-blocking
follow-up carried in PLAN §6; this plan does NOT edit `docs/requirements/api.md`.

Feature-owned surface:

- Router: `services/api/app/api/admin.py` — `POST /api/admin/scan-repos`.
- Consumed dependency: `ingest-token-auth` (`docs/requirements/auth.md#ingest-token-auth`).
- Consumed model: `OrgSummaryRollup` (`db-schema` § `org_summary_rollup`).
- Emitted DTO: `ScanReposResponse @ services/api/app/schemas/repo_scan.py` —
  three fields `{repos_total: int, repos_with_harness_installed: int,
  as_of_timestamp: datetime}` serialised as `{int, int, ISO-8601 UTC string}`.
- FastAPI-emitted `/openapi.json` is the authoritative published schema (TC-12
  asserts the exported component matches the runtime body); no hand-authored
  `docs/openapi/*.yaml` is added or maintained by this story.

## 10. Async & messaging

_N/A — no message broker, no queue, no scheduled job_. The endpoint is synchronous
request/response. The concurrent rebuild race (D-02) is with a
`BackgroundTasks`-dispatched call (BED-03/ADR-0012) but this story does NOT
dispatch any background task itself — the upsert commits inline in the request
path.
