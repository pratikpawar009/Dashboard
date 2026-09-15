# Feature: ING-07 — Admin GitHub repo-scan endpoint

## Problem

Org-wide Harness adoption metrics on the CIO Overview (`repos_with_harness_installed`, `repos_total`) can only be refreshed by editing `org_summary_rollup` in the database by hand. The ingest path (BED-03's rebuild) recomputes usage-derived rollups but never touches the repo-count columns — those are populated by scanning GitHub, which today has no endpoint. Org admins have no supported way to trigger a repo scan, so the counts silently drift from reality until someone patches the DB.

## Outcome

An authenticated (bearer ingest-token, wildcard `"*"` scope) `POST /api/admin/scan-repos` call scans the configured GitHub org, classifies each repo as Harness-installed by the presence of `.harness/program.yaml` on its default branch, upserts `org_summary_rollup.repos_total` / `.repos_with_harness_installed` / `.as_of_timestamp`, and returns the new counts. On external failure or bad config the rollup is left at its prior values (no partial write) and the caller receives a terminal error code — no silent staleness beyond the caller's knowledge.

## Constraints

- **Contract**: `admin-scan-api` (docs/requirements/api.md § `admin-scan-api`) — endpoint path `POST /api/admin/scan-repos`, `ingest-token-auth` bearer, effect = scan configured org + update org rollup repo counts. The contract prose does NOT specify a response body; the response shape is a PRD-level assumption — see `## Decisions log` D-01.
- **Upstream auth**: `ingest-token-auth` (docs/requirements/auth.md § `ingest-token-auth`) — bearer + SHA-256 hash lookup, 401 semantics (missing / unknown / revoked / expired), and the `allowed_program_ids` wildcard `"*"` element. This story is the third consumer of that contract (`consumed_by: [ING-02, ING-03, ING-07]`).
- **Upstream data**: `db-schema` (docs/requirements/data.md § `db-schema`) — `org_summary_rollup` is a singleton per `org_id` with the mutable columns `repos_with_harness_installed`, `repos_total`, `as_of_timestamp`. No schema migration.
- **Concurrent-write acceptance**: BED-03's `rebuild_org_rollups()` (ADR-0012 out-of-band background task) and this endpoint's upsert both write the same singleton row. Last-write-wins is accepted, not mitigated — see `## Decisions log` D-02.
- **Perf budget** — p95 ≤ 10 s per scan for an org of up to 200 repos; each GitHub call ≤ 10 s timeout and ≤ 3 retries with exponential backoff + jitter on 429 / 5xx (story NFR, Decision log 2026-08-26).
- **Security posture**: PAT never logged; wildcard-only scope check for this endpoint; secrets read from server-side settings per `.claude/rules/security-baseline.md`.
- **Signal (resolved 2026-09-15)**: Harness-installed ≡ `.harness/program.yaml` present on the repo's default branch — probed via `GET /repos/{org}/{repo}/contents/.harness/program.yaml?ref={default_branch}` (200 = installed, 404 = not). File content is NOT parsed at scan time. Ruled-out alternatives and rationale live in `docs/stories/ING-07.md` § Clarifications 2026-09-15 and § Decision log — cited, not re-derived.

## Solution sketch

A new admin router (`app/api/admin.py`) mounts `POST /api/admin/scan-repos` at the FastAPI app. On request it (a) resolves the bearer token via the existing `get_ingest_token()` dependency pattern, (b) enforces wildcard-only scope at the router (not inside `ingest_auth.py`, to keep the shared dependency's semantics unchanged for ING-02/ING-03), (c) reads `GITHUB_ORG` + `GITHUB_TOKEN` from settings (500 if either is missing), (d) delegates to a new service (`app/services/repo_scan.py`) that pages the org's repos via GitHub REST and issues one `GET /contents/.harness/program.yaml` probe per repo through a thin `httpx.AsyncClient` wrapper with the story's timeout / retry budget, (e) on scan success upserts `org_summary_rollup` in the request-scoped session and returns the counts, (f) on any post-retry GitHub failure returns 502 and rolls back / never commits the rollup upsert. Response body is `{repos_total, repos_with_harness_installed, as_of_timestamp}` (see D-01).

## Addressing Research Conditions

Research verdict: **GO-WITH-CONDITIONS** (72/100). Three conditions from `docs/research/ING-07.md § Conditions for GO-WITH-CONDITIONS`, each with its concrete resolution in this PRD.

- **C-1 — Resolve [NEEDS CLARIFICATION: Harness-installed signal].**
  **Closure**: already resolved at story level on 2026-09-15. Signal = presence of `.harness/program.yaml` on the repo's default branch, probed via `GET /repos/{org}/{repo}/contents/.harness/program.yaml?ref={default_branch}` (200 = installed, 404 = not; mere presence is sufficient — no YAML parse at scan time). Full rationale and the ruled-out alternatives (`.harness/profile.yaml`, GitHub App / webhook, repo topic) live in `docs/stories/ING-07.md` § Clarifications 2026-09-15 and § Decision log. No new PRD decision required; cited verbatim in `## Constraints` above and enforced by ING-07-FR-1 below.

- **C-2 — Confirm response shape against `admin-scan-api` contract.**
  **Closure**: verified against `docs/requirements/api.md` § `admin-scan-api` — the contract's `shape:` block specifies `endpoint`, `auth`, and `effect` only; no response body schema is declared. The PRD declares the response shape as an assumption (does NOT edit the contract), recorded in `## Decisions log` D-01: `{repos_total: int, repos_with_harness_installed: int, as_of_timestamp: ISO-8601 UTC}`. FR-1 pins the shape to `ScanReposResponse`; the follow-up to extend the contract itself is tracked in `## Open questions` as non-blocking.

- **C-3 — Explicit acceptance of the `org_summary_rollup` concurrent-write race.**
  **Closure**: BED-03's `rebuild_org_rollups()` (dispatched out-of-band via FastAPI `BackgroundTasks` per ADR-0012) and this endpoint's upsert both write the singleton `org_summary_rollup` row for `org_id='org-1'`. Race is accepted last-write-wins, not mitigated — no advisory lock, no serialisation, no version column. Rationale: the org rollup is a best-effort aggregate; short staleness on a lost update is acceptable per the PRD's external-dependency failure mode (repo counts refresh on the next successful scan or ingest). Recorded in `## Decisions log` D-02 so it survives verbatim into PLAN.md's own DECISIONS.md.

## Scope

- **In**:
  - New `POST /api/admin/scan-repos` endpoint under a new `app/api/admin.py` router mounted in `app/main.py`.
  - Bearer auth via existing `get_ingest_token()` dependency, plus wildcard-only scope enforcement at the router.
  - GitHub REST integration for (a) org repo listing (paginated, 100/page) and (b) per-repo `.harness/program.yaml` presence probe on the default branch, via a thin `httpx.AsyncClient`-based wrapper with the story's timeout / retry budget.
  - Upsert of `org_summary_rollup.repos_total`, `.repos_with_harness_installed`, `.as_of_timestamp` for the singleton `org_id='org-1'` row.
  - Settings additions: `GITHUB_ORG`, `GITHUB_TOKEN` on `app/core/config.Settings` (both optional at import time; missing at request time → 500).
  - Structured log event `admin_scan_completed` (fields per story NFR, Decision log 2026-08-26); PAT and raw GitHub response bodies never logged.
  - Unit tests covering auth (401 branches, 403 wildcard-only), missing-config 500, GitHub-failure 502 with rollup untouched, Harness-installed classification (200 vs 404), and the response-shape assumption.

- **Out**:
  - No user-facing UI. No browser-based invocation path.
  - No YAML parsing of `.harness/program.yaml` at scan time (content parsing is ING-10's `POST /api/ingest/manifest`).
  - No cron / scheduled auto-scan — endpoint is caller-triggered only.
  - No modification of `ingest-token-auth`'s shared scope check in `app/core/ingest_auth.py`; the wildcard-only rule for this endpoint is enforced at the router to keep the dependency's semantics unchanged for ING-02 / ING-03.
  - No change to BED-03's `rollup-rebuild` contract or its `consumed_by` list.
  - No addition or change to `program_summary.repos_*` fields (this endpoint writes org-level counts only).
  - No `admin-scan-api` contract edit (response-shape declaration lives here as an assumption; contract extension is a non-blocking follow-up in `## Open questions`).
  - No new Alembic migration.

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/ING-07.md` for canonical wording.
New impl constraints introduced below:

**ING-07-FR-1** — Response body shape  *(extends AC #1 and AC #6 with: an explicit response DTO)*

The endpoint returns HTTP 200 with body `{"repos_total": int, "repos_with_harness_installed": int, "as_of_timestamp": string}` where `as_of_timestamp` is ISO-8601 UTC (matches `org_summary_rollup.as_of_timestamp` after the upsert). The DTO name is `ScanReposResponse`. Rationale: the `admin-scan-api` contract does not declare a response body; this PRD pins one (see `## Decisions log` D-01).

**ING-07-FR-2** — Wildcard-only scope enforcement at the router  *(extends AC #3 with: enforcement location)*

The 403 wildcard-only check MUST be enforced in `app/api/admin.py`, NOT in `app/core/ingest_auth.py::get_ingest_token()`. The shared dependency's semantics (empty `allowed_program_ids` = allow-all, `["*"]` = wildcard, otherwise exact-string membership on the caller-supplied `program_id`) MUST remain unchanged for ING-02 / ING-03. The admin endpoint has no `program_id`; it passes an admin sentinel (e.g. the literal `"*"`) so the shared check succeeds only for allow-all or wildcard tokens, then re-checks in-router that the resolved token carries a literal `"*"` in `allowed_program_ids` and rejects allow-all-empty tokens with 403. Rationale: admin scan is org-wide, and allow-all-empty is the ADR-0006 default for legacy tokens which must not silently gain org-admin power.

**ING-07-FR-3** — GitHub client isolation  *(extends AC #1 and AC #5 with: encapsulation contract)*

A dedicated GitHub REST wrapper lives in `app/services/repo_scan.py` (or a co-located module). It is the ONLY module that imports `httpx` for GitHub calls in this feature. It exposes list-repos-of-org and probe-file-on-default-branch operations; every outbound call carries a 10 s connect/read timeout and the ≤ 3-retry / exponential-backoff-with-jitter policy on 429 / 5xx; retry exhaustion raises a bounded, typed error the router converts to 502. No raw response bodies or request headers are logged. Rationale: contains new external-dependency surface (research risk #2) behind one seam so future changes (rate-limit tuning, App-token migration) don't leak.

**ING-07-FR-4** — Rollup-upsert atomicity per request  *(extends AC #5 with: no-partial-write rule)*

`org_summary_rollup` is upserted in a single transaction after the scan completes successfully. Any GitHub failure after retry exhaustion, any settings failure, and any auth failure MUST leave the row unchanged — the router MUST NOT commit a partial update (e.g. `repos_total` set but `repos_with_harness_installed` still stale). Rationale: AC-5's "no partial update" guarantee; the row is the singleton adoption metric and a half-written state is worse than staleness.

**ING-07-FR-5** — Missing-config detection point  *(extends AC #4 with: check location)*

The `GITHUB_ORG` / `GITHUB_TOKEN` presence check runs BEFORE any GitHub API call and BEFORE any DB write. A missing or empty value on either produces HTTP 500 with a stable configuration-error body (`{"detail": "missing configuration: GITHUB_ORG"}` or `... GITHUB_TOKEN`) and MUST leave `org_summary_rollup` and the `admin_scan_completed` log unchanged. Rationale: AC-4's "no GitHub API call" and "leaves org_summary_rollup unchanged" guarantees.

## Non-functional requirements

- Performance: p95 ≤ 10 s per scan for an org of up to 200 repos (story NFR). Per-call GitHub HTTP timeout = 10 s connect/read; retries ≤ 3 with exponential backoff + jitter on 429 / 5xx (bounded per `.claude/rules/performance-baseline.md`). No unbounded fan-out reads; pagination on the GitHub list-repos call.
- Security: Per `.claude/rules/security-baseline.md`: applies to `POST /api/admin/scan-repos` and to `app/services/repo_scan.py`. Additions: `GITHUB_TOKEN` is read only from server-side settings, never echoed in responses, never emitted in structured log fields, and never present in exception messages; raw GitHub response bodies and request headers MUST NOT be logged; the endpoint accepts bearer ingest-token auth only, never a session cookie.
- Accessibility: N/A — backend endpoint, no UI surface.
- Observability: structured log event `admin_scan_completed` with fields `{repos_total, repos_with_harness_installed, duration_ms, github_api_calls}` (story NFR, Decision log 2026-08-26). Failure branches (401, 403, 500, 502) MUST emit at least one structured event so operators can distinguish auth denial from external-dependency failure without inspecting stack traces.
- Reusability: Per `.claude/rules/reusability-baseline.md`: applies to the new `app/services/repo_scan.py` module. GitHub REST wrapper is a single-responsibility seam (list + probe); no shared code with `app/auth/jwks.py`'s JWKS `httpx` client (different auth model, different retry semantics — do not merge).

## Visual spec

Not applicable — `integrations.design = none`. Backend / API / data feature.

## Rollout plan

- **Strategy**: bang-bang.
- **Feature flag**: none. Endpoint is admin-only, gated by wildcard-scope bearer token (no such token exists in the current deploy for anyone but the operator minting it via `scripts/mint_ingest_token.py --program-ids "*"`), so the blast radius is bounded by token minting, not by deployment.
- **Backout plan**: revert the admin router registration in `app/main.py` (one-line `include_router` removal) via a follow-up PR; existing rollup data is untouched. No data migration to reverse.
- **Success signal**: first successful invocation returns `repos_total > 0` and `admin_scan_completed` is emitted with `duration_ms ≤ 10000`; `org_summary_rollup.as_of_timestamp` advances. Failure signal: two consecutive 502s within one hour → operator investigates GitHub PAT / rate-limit budget.

## Documentation requirements

- **README updates**: `services/api/README.md` — add a `## Admin scan` sub-section under the existing ingest-auth documentation covering the endpoint path, required token scope (wildcard-only), the `GITHUB_ORG` / `GITHUB_TOKEN` settings, and the response shape. Cross-link to the story.
- **Runbook**: none — no new operational role introduced; failure modes are covered by the structured log events above.
- **API reference**: FastAPI auto-emitted OpenAPI is authoritative; ensure the `ScanReposResponse` DTO is exported and documented on the route.
- **Inline code comments**: `app/services/repo_scan.py` — one-line docstring on the module noting the concurrent-write acceptance (references D-02) at the rollup-upsert call site.
- **Examples / how-to**: `.env.example` — add commented-out `GITHUB_ORG=` and `GITHUB_TOKEN=` entries with a pointer to GitHub PAT-generation docs.

## Open questions

- Should the `admin-scan-api` contract in `docs/requirements/api.md` be extended to declare the response body schema this PRD pins in D-01? **Non-blocking** — this PRD is authoritative for ING-07's implementation via FR-1; the follow-up is a documentation task only and does not gate planning or implementation.

Decisions logged in `docs/stories/ING-07.md` § Decision log.

## Decisions log

- **D-01 — Response body shape declared here as a PRD-level assumption.** The `admin-scan-api` contract's `shape:` block specifies `endpoint`, `auth`, and `effect` only; no response schema. This PRD pins `ScanReposResponse = {repos_total: int, repos_with_harness_installed: int, as_of_timestamp: ISO-8601 UTC string}` (FR-1) as the story-scoped source of truth. Does NOT edit the contract. Follow-up to extend the contract is tracked in `## Open questions` (non-blocking).
- **D-02 — Concurrent-write race on `org_summary_rollup` accepted last-write-wins.** BED-03's `rebuild_org_rollups()` (out-of-band `BackgroundTasks` per ADR-0012) and this endpoint's upsert both write the singleton row. No advisory lock, no serialisation, no version column. Rationale: the org rollup is a best-effort aggregate; short staleness on a lost update is acceptable per the source PRD's external-dependency failure mode (repo counts refresh on the next successful scan or ingest). This decision MUST survive verbatim into PLAN.md's DECISIONS.md.

## Approvals

- **2026-09-15** — Product Owner (single-approver mode: PO + Designer + BA covered by one human): **APPROVE**
  - Feature Summary, FRs, User Flows reviewed
  - UI specs reviewed in `DESIGN.md`: N/A — backend-only feature, `integrations.design = none`
  - Edge Cases, Open Questions, test-case completeness reviewed
  - No-placeholder check ✓ · `[NEEDS CLARIFICATION]` count=0
  - Research verdict GO-WITH-CONDITIONS (all three conditions addressed in `## Addressing Research Conditions`)
  - Tracker subtask: pratikpawar009/Dashboard#331
  - Test cases: 20 (all automatable) · coverage PASS (ACs 6/6, FRs 5/5, NFRs 3/3, uncovered=[])
