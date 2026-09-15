# ING-07 — Decisions

Story-scoped decision log for the Admin GitHub repo-scan endpoint. Every non-trivial
technical choice this plan commits to lives here; PLAN.md §1 is a pointer to this file.

### D-01: Response body shape declared here as a PRD-level assumption · blast:feature · rev:mechanical · adr:—

**Context**: `admin-scan-api` (`docs/requirements/api.md#admin-scan-api`) specifies
`endpoint`, `auth`, and `effect` only — its `shape:` block declares no response body.
Story AC-6, PRD FR-1, and TC-12 all pin an assumed shape, so the plan must either
extend the contract or make the assumption authoritative for this story.

**Decision**: PRD ING-07-FR-1 pins `ScanReposResponse =
{repos_total: int, repos_with_harness_installed: int, as_of_timestamp: ISO-8601 UTC}`
as the story-scoped source of truth; the contract file is NOT edited from within this
plan (avoids silent inline contract drift). The DTO lives at
`services/api/app/schemas/repo_scan.py::ScanReposResponse`, is exported on the route,
and TC-12 asserts the runtime body + the OpenAPI schema component both match verbatim.
The follow-up to extend `admin-scan-api` itself is carried in §6 as non-blocking.

### D-02: Concurrent-write race on `org_summary_rollup` accepted last-write-wins · blast:service · rev:medium · adr:—

**Context**: BED-03's `rebuild_org_rollups()` (out-of-band `BackgroundTasks` dispatch
per ADR-0012) and this endpoint's upsert both write the singleton
`org_summary_rollup` row for `org_id='org-1'`. No advisory lock, no serialisation,
no version column exists on the model (`services/api/app/models/rollup.py`
`OrgSummaryRollup`).

**Decision**: Verbatim from PRD D-02 — the race is accepted last-write-wins, not
mitigated. Rationale: the org rollup is a best-effort aggregate; short staleness on
a lost update is acceptable per the PRD's external-dependency failure mode (repo
counts refresh on the next successful scan or ingest). Reversal is `rev:medium`
(add an advisory lock or a version column later without data loss).
`app/services/repo_scan.py` carries a one-line comment at the upsert call site
citing this entry. TC-20 asserts the endpoint completes 200 under a concurrent
`rebuild_org_rollups()` writer without deadlock or serialisation error; no
assertion is made on which writer wins.

### D-03: GitHub REST client is a dedicated per-feature seam, not a shared http wrapper · blast:service · rev:mechanical · adr:—

**Context**: No GitHub client exists in the codebase. `httpx>=0.27` is a
production dep (`services/api/pyproject.toml`) already used by `app/auth/jwks.py`
for JWKS fetches with different auth (JWKS URL, no bearer), different retry
semantics, and a different failure model (401 on JWKS fetch is a fatal server
misconfiguration; 502 on GitHub is a bounded upstream failure). Research risk #2
flags introducing a GitHub-specific external surface.

**Decision**: A single, feature-owned wrapper lives in
`services/api/app/services/repo_scan.py`. It is the ONLY module importing `httpx`
for GitHub calls. Two operations only — list org repos (paginated 100/page) and
probe `.harness/program.yaml` on a repo's default branch (200 vs 404). Every call
uses a 10 s connect/read timeout via `httpx.Timeout(10.0)` and delegates retries
to the existing `app.core.retry.retry_with_backoff` (≤3 attempts, exponential
backoff + full jitter — reuses ADR-0002's bounded-retry primitive, no new library).
Retry exhaustion raises a typed `GitHubScanError`; the router maps it to 502.
Never merged with `app/auth/jwks.py`'s client. Deliberately NOT promoted to an ADR
because the choice is `blast:service` + `rev:mechanical` — a future migration to a
GitHub App auth model is a rewrite of this one module.

### D-04: Retry via existing `app.core.retry.retry_with_backoff`, no new dep · blast:feature · rev:mechanical · adr:—

**Context**: `app/core/retry.py` already ships a bounded exponential-backoff-with-jitter
retry helper used on the ingest path (ADR-0002). The alternative is adding `tenacity` or
similar as a new dep to get richer retry policies (jittered exponential + retry-after
respect + per-exception filters).

**Decision**: Reuse `retry_with_backoff` unchanged. Its 3-attempt/backoff/jitter shape
matches FR-3's `≤3 retries` budget exactly; the caller (`repo_scan.py`) is responsible
for raising on retryable statuses (429/5xx) so the helper's raise-to-retry contract is
respected. `Retry-After` is NOT honored in v1 — jittered backoff bounded by 2 s max
(`retry.py::max_delay_s`) stays within the 10 s per-call budget in the worst case; a
`Retry-After` implementation is a `rev:mechanical` follow-up if 429s become common.

### D-05: Router-level wildcard-strict re-check, `get_ingest_token()` invoked directly (not via `Depends()`) · blast:feature · rev:mechanical · adr:—

**Context**: FR-2 requires wildcard-STRICT enforcement at the router (`['*']` verbatim
membership, allow-all-empty rejected) without changing
`app/core/ingest_auth.py::get_ingest_token()`'s shared semantics (still consumed by
ING-02, ING-03). `get_ingest_token`'s signature also carries a mandatory `program_id:
str` parameter which FastAPI would otherwise bind as a required query parameter — a
query string this contract does not accept. Precedent for a router-owned direct call
lives in `services/api/app/api/manifest.py` (documented in that module's docstring).

**Decision**: Follow the `manifest.py` pattern. The admin router creates its own
`HTTPBearer(auto_error=False)`, resolves `credentials` + `session`, and calls
`get_ingest_token()` as a plain coroutine passing the literal string `"*"` as
`program_id`. The shared dependency's scope check then passes for both allow-all-empty
AND wildcard tokens; the router immediately re-checks `"*" in token.allowed_program_ids`
and raises 403 if absent, so allow-all-empty legacy tokens (ADR-0006 accepted default)
are rejected as required. TC-13 asserts the router-level 403 for allow-all-empty.

### D-06: Endpoint tests colocated in `tests/unit/`, perf test in `tests/perf/` — follow existing repo layout · blast:feature · rev:mechanical · adr:—

**Context**: `docs/test-cases/ING-07.json` labels 18/20 cases as `integration` (plus
one `contract`, one `security`, one `performance`), but `services/api/tests/` has no
`tests/integration/` directory — every existing endpoint test (auth, manifest, ingest,
overview, freshness) lives under `tests/unit/`. `docs/config/project-commands.yaml`
`test_integration` is deliberately empty ("not yet scaffolded — no tests/integration
dir or fixtures yet").

**Decision**: Endpoint tests (TC-01..TC-15, TC-17..TC-20) go into
`services/api/tests/unit/test_admin_repo_scan.py` matching the repo's shipped
convention (`test_manifest_ingest.py`, `test_ingest_token_auth.py`). Performance test
TC-16 goes to `services/api/tests/perf/test_admin_repo_scan_perf.py` under the
existing `perf` marker (`services/api/pyproject.toml [tool.pytest.ini_options]`).
No new test-runner install or config file — pytest + `pytest-asyncio` + `respx` are
all already declared in `[dependency-groups].dev`. Test-strategy §7 records the
mapping. Establishing `tests/integration/` for this one story is out of scope
(would require its own conftest + preflight update).

### D-07: Service returns `ScanReposResponse` directly; `github_api_calls`/`duration_ms` propagate via structured log only · blast:service · rev:mechanical · adr:—

**Context**: PLAN.md §3 declared a five-field `ScanReposResult` sentinel type (`repos_total`, `repos_with_harness_installed`, `as_of_timestamp`, `github_api_calls`, `duration_ms`) as the service-layer return contract, on the assumption the router would want to consume the two operational fields for a header or response wrapper. In practice the router does not — no PRD field maps to `github_api_calls` or `duration_ms`, and TC-01/TC-12 pin the wire response to exactly `{repos_total, repos_with_harness_installed, as_of_timestamp}` (the `ScanReposResponse` DTO). Adding an intermediate `ScanReposResult` shape adds a mapper for zero external benefit. AF-05 self-reported this drift at implementation time; F-3 in REVIEW.md rediscovered it and rated it MEDIUM (`pattern-consistency`).

**Decision**: The service returns `ScanReposResponse` directly (three fields). `github_api_calls` (int) and `duration_ms` (int) are emitted on the `admin_scan_completed` structured log record only — TC-18 asserts the two fields exist on the log payload, TC-16 measures perf independently. This removes a phantom type from PLAN §3 without touching runtime behaviour. Reversal is `rev:mechanical`: reintroducing an internal sentinel later is a one-file service change.

**Affected sections**: PLAN.md §3 (points to this entry as authoritative). No code change; retroactive documentation only.

### D-08: `docs/requirements/api.md#admin-scan-api` `shape:` block intentionally under-declared until F-U1 lands · blast:doc · rev:mechanical · adr:—

**Context**: The `admin-scan-api` contract's `shape:` block still enumerates only `endpoint`, `auth`, `effect` — it does not declare the response body. This story's runtime source of truth for the wire shape is TC-12 (OpenAPI pin) + `ScanReposResponse` (`services/api/app/schemas/repo_scan.py`). PLAN §6 F-U1 already lists the extension as a non-blocking follow-up. F-1 in REVIEW.md flagged the doc-vs-code drift (MEDIUM, downgraded because `consumed_by: []` — no downstream story binds to the shape yet).

**Decision**: Do NOT edit `docs/requirements/api.md` in this feature branch. Rationale: (a) the contract file's `consumed_by: []` means no story observes the drift; (b) `surgical-changes.md` and the do-not-drift-contracts rule keep produced-contract edits out of the producing feature's diff; (c) PLAN §6 F-U1 already schedules the follow-up. This decision explicitly acknowledges the deferral so `contract-drift` reviews record an intentional gap, not an oversight. When the first downstream story `consumed_by:` lands, F-U1 becomes blocking and this decision is superseded.
