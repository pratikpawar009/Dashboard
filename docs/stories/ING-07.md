# Story: ING-07 — Admin GitHub repo-scan endpoint

**Epic**: ING
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#46 (https://github.com/pratikpawar009/Dashboard/issues/46)

## User story

As an org admin (via an authenticated ingest token, not the browser UI), I want to trigger a scan of the configured GitHub org's repositories and have the org-wide Harness-installed repo counts refreshed, so that the CIO Overview's adoption metrics (`repos_with_harness_installed`, `repos_total`) reflect current reality without a manual DB edit.

## Acceptance criteria

1. Given a bearer-token-authenticated `POST /api/admin/scan-repos` request whose token carries the `"*"` wildcard in `allowed_program_ids`, when the endpoint processes it, then it lists every repository in the configured GitHub org via the GitHub REST API (PAT auth), classifies each as [NEEDS CLARIFICATION: what marks a repo "Harness-installed" — presence of `.harness/profile.yaml` on the default branch, a GitHub App/webhook installation record, a repo topic tag, or another signal?], and upserts `org_summary_rollup.repos_with_harness_installed`, `.repos_total`, and `.as_of_timestamp` with the result (per FR-ING-09, `admin-scan-api` contract).
2. Given a request with a missing, revoked, or expired bearer token, when the endpoint authenticates it, then it returns `401`, makes no GitHub API call, and leaves `org_summary_rollup` unchanged (per `ingest-token-auth` contract).
3. Given a request with a valid token whose `allowed_program_ids` does not include the `"*"` wildcard, when the endpoint authorizes it, then it returns `403` and makes no GitHub API call — a repo-scan is org-wide, not scoped to any single program, so only a wildcard-scoped token may run it (per `ingest-token-auth` contract; scope rule is an assumption, see Decision log).
4. Given the server has no `GITHUB_ORG` or `GITHUB_TOKEN` configured, when the endpoint is invoked, then it returns `500` with a configuration-error body and makes no GitHub API call (per FR-ING-09, "requires GitHub org + token settings").
5. Given the GitHub API call fails after retries are exhausted (network error, `5xx`, or `429` rate-limit), when the endpoint handles the failure, then it returns `502` and `org_summary_rollup`'s repo counts remain at their prior values — no partial update (per PRD external-dependency note: "repo-scan endpoint fails; repo counts go stale until manually corrected or retried").
6. Given a successful scan, when the endpoint responds, then the response body reports `repos_total`, `repos_with_harness_installed`, and `as_of_timestamp` — assumption, `admin-scan-api` contract specifies the update effect but not a response schema (see Decision log).

## Non-functional requirements

- Performance: p95 <= 10s per scan for an org of up to 200 repos (GitHub REST list-repos paginated 100/page, so <=2 list calls); each GitHub API call has an explicit 10s connect/read timeout and retries <=3 attempts with exponential backoff + jitter on `429`/`5xx` before the scan fails — assumption, PRD gives no repo-scan-specific latency/retry budget; sized to satisfy the project's bounded-retry/explicit-timeout baseline (see Decision log).
- Security: GitHub PAT is read from server-side `GITHUB_TOKEN` config, never logged or echoed in the response; endpoint requires bearer ingest-token auth scoped by wildcard `"*"` only, never session-cookie auth (per NFR-006, PRD §"no browser-based creation/editing UI" note).
- Accessibility: N/A — backend endpoint, no UI surface.
- Observability: structured log event `admin_scan_completed` (fields: `repos_total`, `repos_with_harness_installed`, `duration_ms`, `github_api_calls`) — assumption, NFR-011 defines the structlog/JSON logging mechanism and an event set that does not include a scan-specific event (see Decision log).

## Dependencies

- Upstream: ING-01 via `ingest-token-auth` contract (docs/requirements/auth.md) — bearer hash lookup, 401/403 semantics, wildcard-scope check; BED-01 via `db-schema` contract (docs/requirements/data.md) — `org_summary_rollup` table shape (`repos_with_harness_installed`, `repos_total`, `as_of_timestamp`).
- Downstream: none — `admin-scan-api`'s `consumed_by` list is empty; OVW-01 reads `org_summary_rollup` via its own `db-schema` dependency, not via this contract.

## Test mapping

- E2E: NA — admin-only maintenance endpoint, no user-facing UI flow.
- Unit: `backend/app/routers/admin.py`, `backend/app/services/repo_scan.py` — auth/authz (`401`/`403`, wildcard-only rule), missing-config path (`500`), GitHub-API-failure path with retry/timeout (`502`, rollup untouched), Harness-installed classification, rollup upsert, response shape.
- Manual: NA.

## Clarifications

- [NEEDS CLARIFICATION: what marks a repo "Harness-installed" — presence of `.harness/profile.yaml` on the default branch, a GitHub App/webhook installation record, a repo topic tag, or another signal?]

## Decision log

- 2026-08-26 Auth scope for repo-scan: requires a bearer token with `"*"` wildcard `allowed_program_ids`; a program-scoped-only token is rejected `403` — assumption, `ingest-token-auth` contract defines a program-scope check but the scan operation isn't program-scoped so no program id can satisfy it.
- 2026-08-26 Missing-config failure code: `500` — assumption, FR-ING-09 says the endpoint "requires GitHub org + token settings" but doesn't name a status code.
- 2026-08-26 GitHub-API-failure code: `502`, rollup left unchanged — assumption, sourced from the PRD's stated effect ("repo counts go stale until manually corrected or retried") but the PRD doesn't name a status code.
- 2026-08-26 Response body shape (`repos_total`, `repos_with_harness_installed`, `as_of_timestamp`) — assumption, `admin-scan-api` contract states the update effect only, no response schema.
- 2026-08-26 Performance/retry/timeout budget (p95 <=10s/200 repos, 10s per-call timeout, <=3 retries with backoff+jitter) — assumption, no PRD-specific repo-scan budget exists; sized to satisfy the project's bounded-retry and explicit-timeout baseline.
- 2026-08-26 Observability event `admin_scan_completed` (repos_total, repos_with_harness_installed, duration_ms, github_api_calls) — assumption, NFR-011 defines the logging mechanism and event set generally but does not name a repo-scan event.
