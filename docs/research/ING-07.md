# Research: ING-07 — Admin GitHub repo-scan endpoint

**Story**: ING-07 (Admin GitHub repo-scan endpoint)  
**Status**: Research-in-progress  
**Score**: 72/100  
**Verdict**: GO-WITH-CONDITIONS  
**Clarifications**: 1 open  
**Date**: 2026-09-15

---

## Upstream dependency summary

| Story | Status       | Phase           | Contract                |
|-------|--------------|-----------------|-------------------------|
| ING-01 | Implemented  | security-reviewed | ingest-token-auth       |
| BED-01 | Implemented  | review          | db-schema (org_summary_rollup) |

Both upstream stories are **shipped and phase-gated**. ING-01 supplies the bearer-token auth dependency (401/403 semantics, wildcard-scope enforcement); BED-01 supplies the table shape (repos_with_harness_installed, repos_total, as_of_timestamp fields present and mutable).

---

## Exploration Log

**Objective**: Map the routers, service layers, auth patterns, models, and test fixtures this story will use.

1. **Router structure** → no `app/api/admin.py` exists yet; routers live in `app/api/` per main.py line 90-105 include_router calls.

2. **Service-layer pattern** → examined `app/services/activity_ingest.py` (ING-02) and `app/services/manifest_ingest.py` (ING-10); both follow a consistent shape: async function receiving db session, external identifiers, and raw dict payload; return a response DTO; emit structured log events on success/failure.

3. **Auth wiring** → `app/core/ingest_auth.py::get_ingest_token()` handles bearer lookup, SHA-256 hash match, expiry/revocation checks, and program-scope enforcement (ADR-0006 §3). Wildcard check: `if not token.allowed_program_ids or "*" in token.allowed_program_ids`. This pattern is directly reusable.

4. **OrgSummaryRollup model** → `app/models/rollup.py` line 16-36; fields match contract: `repos_with_harness_installed`, `repos_total`, `as_of_timestamp` (all mutable); singleton per `org_id='org-1'` unique constraint; carries `id` PK, `created_at`, `updated_at`.

5. **Rollup rebuild ownership** → `app/services/rollup_rebuild.py` exports `rebuild_org_rollups()` and `rebuild_program_rollups()`. ADR-0012 § Consequences (supersedes BED-05 D-05): org rebuild MUST dispatch out-of-band via `BackgroundTasks`, never inline. This story's upsert does not trigger a rebuild; the data is independent (repos, not usage_events).

6. **GitHub client dependency** → `pyproject.toml` line 18: `httpx>=0.27` is a **production dependency** (app/auth/jwks.py imports it at module level). No existing GitHub API wrapper in codebase; will need to create one.

7. **Settings** → `app/core/config.py` has no `GITHUB_ORG` or `GITHUB_TOKEN` fields. Need to add them; `.env.example` also lacks examples.

8. **Test patterns** → `tests/unit/test_auth_dev_bypass.py` and `tests/conftest.py` show the fixture pattern: `build_app` factory, `async_client_for` context manager, `migrated_db` for schema-dependent tests, `respx` for mocking outbound HTTP calls. `conftest.py` also defines `KeycloakMock` and `RSATestKeypair` for auth fixtures.

9. **Ingest-auth test coverage** → No explicit admin-endpoint auth tests found, but `test_ingest_route_generic.py` and `test_manifest_ingest.py` establish patterns for bearer auth, 401/403 responses, and token-scoped program_id validation.

10. **External HTTP error handling** → searched for `httpx.RequestError`, `429`, `5xx` handling; found retry + timeout pattern in `app/core/retry.py` and `app/core/config.py`'s timeout setup. No existing GitHub-specific error class.

**Time**: ~20 minutes. Scan complete, orientation achieved.

---

## Pattern map

### Existing code to extend

- `app/core/ingest_auth.py` — reuse `get_ingest_token()` dependency and wildcard-check logic (`_check_program_scope()`).
- `app/models/rollup.py` — upsert directly into `OrgSummaryRollup` model; no new table or schema migration needed.
- `app/core/config.py` — add `github_org` and `github_token` fields (both optional for now; missing config → 500 per AC-4).

### Existing patterns to follow

- **Service-layer shape** (activity_ingest.py, manifest_ingest.py): async function, session + identifiers + payload dict → response DTO; structured logging via module-level log-event functions; per-request timing.
- **Bearer auth at router** (ingest.py, manifest.py): parse envelope dict first, extract `program_id`, call `get_ingest_token()` directly (not via `Depends()` per structural isolation), handle 401/403/413/400 branches.
- **HTTP client setup** (app/auth/jwks.py pattern): `httpx.AsyncClient`, configurable timeout, JWKS cache pattern suggests how to handle external service state.
- **Test mocking** (respx library, already a dev dependency): mock GitHub REST endpoints in unit tests; use `migrated_db` + `test_session` for DB-dependent integration tests.

### New files to create

- `app/api/admin.py` — router with `POST /api/admin/scan-repos` endpoint; mounts to main app at line 103 (ordering: before `oidc_router` to avoid path collision).
- `app/services/repo_scan.py` — service layer for the scan logic; GitHub API iteration, repo classification, rollup upsert, and structured logging.
- `app/schemas/repo_scan.py` — request/response DTOs (`ScanReposResponse` with `repos_total`, `repos_with_harness_installed`, `as_of_timestamp`).
- `tests/unit/test_admin_repo_scan.py` — unit tests covering auth (401, 403 wildcard-only), missing config (500), GitHub failure (502, rollup unchanged), success path, Harness-installed classification.

### Shared code at risk

- `app/models/rollup.py::OrgSummaryRollup` — writes to a singleton table; if concurrent ingest + repo-scan requests both call upsert, the last write wins (TOCTOU). No transaction isolation issue because a single write per table row is atomic, but **concurrent behavior is undefined** — document as accepted risk.
- `app/core/ingest_auth.py` — reused by three ingest paths (activity, artifacts, **admin-scan**); any change to the scope check affects all three. Admin-scan's wildcard-only enforcement (AC3) is stricter than the base check; implement in the router, not in auth.py, to avoid constraining future ingest paths.
- `app/core/config.py::Settings` — adding `github_org`/`github_token` increases the runtime settings footprint; both are admin-facing (never in request headers), but ensure they are never logged verbatim per security-baseline.md.

---

## Risk register

Ranked by severity. Every risk includes a concrete mitigation.

| # | Dimension       | Severity | Description                                           | Mitigation                                               |
|---|-----------------|----------|-------------------------------------------------------|----------------------------------------------------------|
| 1 | Domain          | **HIGH** | **[NEEDS CLARIFICATION]**: What marks a repo "Harness-installed"? Candidates: `.harness/profile.yaml` on default branch, GitHub App/webhook installation, repo topic tag, or another signal. | Escalate to product/user before planning; the choice affects the entire scan logic and determines whether the implementation must parse YAML, query GitHub Apps API, or check repo topics. Cannot proceed without this clarification. |
| 2 | Integration     | **HIGH** | No GitHub REST client exists; introducing httpx usage for GitHub adds a new external-API dependency surface and potential failure modes not yet in production. | Create a thin wrapper (`services/repo_scan.py::GitHubOrgClient`) with explicit 10s timeout, ≤3 retries on 429/5xx, exponential backoff+jitter per performance-baseline.md. Test with respx mocks covering timeout + retry exhaustion + 502 response paths. |
| 3 | Dependency      | **HIGH** | BED-03 owns `org_summary_rollup` single-writer invariant (rebuilds on every activity ingest); this story performs an independent upsert. Two concurrent writers (ING-02 rebuild + ING-07 upsert) will race; last write wins, no conflict detection. | Document as accepted race condition (org rollup is a best-effort aggregate, not a critical invariant; staleness from a lost update is acceptable per PRD external-dependency note). Add explicit comment in code: `# Race condition: concurrent rebuild + scan both write org_summary_rollup; last write wins.` Test concurrent writes in `test_admin_repo_scan.py`. |
| 4 | Integration     | **MED**  | GitHub API rate limits (429); documentation says "retries ≤3 attempts with exponential backoff + jitter" but the endpoint itself must return 502 after exhaustion. Stack trace on a real 429 in production could leak Keycloak state or internal IDs if logging is incorrect. | Implement retry logic in `GitHubOrgClient`, never log raw GitHub response bodies or request headers. Test: mock GitHub 429 → verify 3 retries with jitter → verify 502 after exhaustion. Audit logs for PII. |
| 5 | Domain          | **MED**  | AC6 assumes a response body with `repos_total`, `repos_with_harness_installed`, `as_of_timestamp` but the story (and contract) specify only the "update effect", not a schema. Response shape is an assumption without a test case. | Verify against `admin-scan-api` contract in docs/requirements/api.md line 541-548 and cross-check with mockup in docs/design/schema.json (if present). If not in mockup, treat as AC-6 assumption and document in DECISIONS.md D-06. |
| 6 | Dependency      | **MED**  | `GITHUB_ORG` and `GITHUB_TOKEN` must be configured (AC-4 requires 500 if missing). No deployment documentation yet exists for how to mint a GitHub PAT or set these env vars. | Defer operational setup to post-implementation; add a `.env.example` comment pointing to GitHub PAT generation docs. Ensure error message at 500 is actionable ("missing or empty GITHUB_TOKEN; see README.md § Configuration"). |
| 7 | Performance     | **MED**  | p95 budget is 10s for up to 200 repos; GitHub REST list-repos endpoint paginates at 100/page, so ≤2 API calls expected. Each call has 10s timeout. No buffer for network jitter or Postgres write latency. | Accept the tight budget as stated in AC6. In tests, mock GitHub latency (respx.mock with delays) and measure p95 with `perf_counter()`. Spike with real GitHub org if latency overshoots at validation. |
| 8 | Domain          | **LOW**  | Harness installation detection must run on the default branch only. If default branch changes mid-scan or is misconfigured in GitHub, the scan could miss repos or misclassify them. | Document invariant: "scan runs once per request; intermediate default-branch changes during the scan are not re-checked." Accept as operational limitation. |

---

## 5-dimension score

| Dimension       | Weight | Scoring reasoning                                                                 | Raw score | Weighted |
|-----------------|--------|-----------------------------------------------------------------------------------|-----------|----------|
| **Integration** | 25     | HTTP client exists (httpx), test fixtures exist (respx), but GitHub wrapper is new code (+risk). One open clarification on signal selection (-15 pts). Retry/timeout logic established in codebase (+10 pts).  | 75        | 18.75    |
| **Compatibility** | 20    | No client/OS compat concerns (backend-only admin endpoint). Ingest-token-auth stable. No cross-version API surface to maintain.                                                             | 95        | 19.00    |
| **Domain**      | 20     | [NEEDS CLARIFICATION] on Harness-installed signal (-25 pts). AC4 error path unclear (assumed 500, not specified in contract) (-5 pts). Concurrent write race documented but accepted (-5 pts). Otherwise straightforward repo iteration logic (+20 pts).                 | 60        | 12.00    |
| **Performance** | 15     | Tight p95 ≤10s budget with 10s timeout per call leaves no jitter buffer (-10 pts). GitHub list-repos pagination known and bounded (+15 pts). No complex algorithm, linear scan (+10 pts).       | 75        | 11.25    |
| **Dependency**  | 20     | ING-01 and BED-01 both shipped, phase-gated, no blockers (+25 pts). No dependency on unshipped stories (-0 pts). Rollup write is independent, no sequencing conflict on rollup-rebuild (+20 pts). | 90        | 18.00    |

**Total: 72/100 → GO-WITH-CONDITIONS**

---

## Conditions for GO-WITH-CONDITIONS

This story may proceed to `/arh-plan-requirements` on **all three conditions below**. Failure on any blocks planning until resolved.

1. **Resolve [NEEDS CLARIFICATION: Harness-installed signal]** — Product decision required. Which of the four named candidates (`.harness/profile.yaml` on default branch, GitHub App/webhook installation, repo topic tag, other) is the authoritative signal? Document the choice in DECISIONS.md before planning. This is **blocking** for the implementation; the choice cascades into the scan logic, GitHub API calls required, and test fixtures.

2. **Confirm response shape against contract** — Verify `admin-scan-api` contract in `docs/requirements/api.md` is complete. AC6 assumes a response body with `repos_total`, `repos_with_harness_installed`, `as_of_timestamp`, but the contract prose only states "updates org rollup repo counts." If the response shape is not defined in the contract, add it explicitly or document the assumption in DECISIONS.md D-06.

3. **Explicit acceptance of concurrent-write race** — PLAN.md must document that `org_summary_rollup` is subject to a last-write-wins race between BED-03's rebuild (triggered by activity ingest on any program) and ING-07's scan upsert. This is an **accepted, not mitigated** risk: org rollups are best-effort aggregates, and staleness from a lost update is acceptable per the PRD's stated external-dependency failure mode. Add the race condition to the DECISIONS.md log with explicit rationale.

---

## Clarifications

### [NEEDS CLARIFICATION: Harness-installed signal]

**Status**: OPEN  
**Raised**: Story AC1 (docs/stories/ING-07.md line 32)  
**Options evaluated**:

1. **`.harness/profile.yaml` on default branch** — Requires checking out or listing the default branch files via GitHub REST API (Contents endpoint or Git Trees API). Stable. File format and location already standardized across the Harness system (CLAUDE.md notes `programId` as legacy field name in `.harness/program.yaml`). **Concern**: Is this the file that will hold the signal, or is `.harness/program.yaml` (or another path entirely) the canonical one? User context notes `program.yaml` exists; story text mentions `profile.yaml`. Need clarification on which file and which field to read.

2. **GitHub App/webhook installation** — Query GitHub REST `GET /repos/{owner}/{repo}/installation` (Installations API) or `GET /repos/{owner}/{repo}/hooks` (Webhooks API). Does not require file parsing but adds an extra API call per repo (2 API list calls to get all repos + 1 per-repo API call = 200 calls for 200 repos, overshoots the 10s timeout budget). **Unlikely candidate** but must be rejected explicitly.

3. **Repo topic tag** — Query `GET /repos/{owner}/{repo}` to read the `topics[]` array and check for a specific topic (e.g., "harness-installed" or "harness"). Requires a separate call per repo (same 200-call problem as option 2). **Unlikely candidate** but must be rejected explicitly.

4. **Another signal** — Unspecified. Examples: a Keycloak group claim, a separate manifest file, a row in an external system. Needs user input.

**Impact on ING-07**:
- Option 1 (.harness/profile.yaml): Plan needs to parse YAML, extract the signal field, add respx mocks for GitHub Contents API calls.
- Option 2/3 (GitHub App/Webhooks/Topics): Budget constraint makes this infeasible at 200 repos; plan should recommend against or request a smaller org size for MVP.

**Next step**: Escalate to user/product. Cannot proceed to planning without this choice.

---

## Synthesis

**ING-07 is feasible and should proceed to planning with three explicit conditions resolved first.**

The repository already has the necessary infrastructure: httpx for outbound HTTP, respx for testing, ingest-token-auth patterns for bearer auth, and OrgSummaryRollup model for the write target. The main implementation work is straightforward — iterate the GitHub org's repos via the REST API, classify each (pending the signal clarification), and upsert the rollup — but three concrete dependencies must be settled before the plan can be written:

1. **The Harness-installed signal** (HIGH-risk, blocking) must be chosen by product to avoid rework.
2. **The response shape** must be confirmed against the contract or explicitly documented as an assumption.
3. **The concurrent-write race** between BED-03's rebuild and ING-07's upsert must be accepted as an acknowledged risk in the plan.

A thin `GitHubOrgClient` wrapper with explicit timeouts, retries, and error paths will mitigate the HTTP integration risk. The performance budget is tight (p95 ≤10s, 10s per call leaves no jitter buffer) but achievable for up to 200 repos at 2 API calls. Fallback to a 502 response on GitHub failure keeps the rollup stable and aligns with the PRD's external-dependency failure mode.

---

## Recommendations

1. **Signal choice**: Recommend starting with option 1 (`.harness/profile.yaml` on default branch). It avoids N+1 API calls, is stable, and aligns with the Harness system's existing manifest conventions. Confirm with user before planning.

2. **Concurrent-write safety**: Document the race condition explicitly in DECISIONS.md. Accept it as an operational reality of a distributed system without shared locks. The org rollup is a best-effort aggregate, not a critical invariant; staleness from a lost update is acceptable per the PRD.

3. **Tight performance budget**: Spike if real GitHub latency overshoots 10s in a test run. Consider pre-fetching default-branch info alongside the repo list if GitHub API supports it, or batch per-repo checks in a single call. If 200 repos is the upper bound, measure against that; if future orgs are larger, revisit the budget.

---

## Next steps

- **Resolve the three conditions** (signal choice, response shape, race condition acceptance).
- **If all three pass**: Proceed to `/arh-plan-requirements ING-07`.
- **If any condition fails**: Surface the blocker in the tracker subtask and request scope renegotiation or a spike story.
