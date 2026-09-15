# ING-07 — Agent flags

Observations raised during implementation. Each block has status `open` until triaged via `/arh-human-review ING-07`.

---

### AF-01: T-01 — new Settings fields use plain Optional[str], no validator
- kind: design-note
- task: T-01
- source: services/api/app/core/config.py:99-108
- resolution: accepted — matches PRD FR-5 semantics (presence-only, empty == unset). D-01 records the auth precedence; no validator warranted.
- status: resolved

New fields `github_org` / `github_token` are `str | None = None` (no NoDecode / validator) — presence-only usage; the request-time router check compares with `bool(value)` so empty string == unset, matching PRD FR-5 "missing or empty value on either produces HTTP 500". Flagging so the T-04 router author does not add a length/format validator here.

---

### AF-02: T-01 — .env.example inlines PAT-scope guidance in a comment
- kind: design-note
- task: T-01
- source: services/api/.env.example (end of file)
- resolution: accepted — PAT-scope hint in `.env.example` is documentation, not runtime; aids operator least-privilege setup.
- status: resolved

`GITHUB_TOKEN` example uses `ghp_...` as a commented illustrative prefix (no live value); PAT-generation URL + minimum scope guidance (read-only Contents on org repos) inlined so operators don't over-provision.

---

### AF-03: T-02 — class name is `ScanReposResponse`, not `RepoScanResponse`
- kind: risky-pattern
- task: T-02
- source: services/api/app/schemas/repo_scan.py
- resolution: accepted — `ScanReposResponse` is the shipped class name; PLAN §3 now references it via D-07. Reader landed on the correct symbol.
- status: resolved

Orchestrator's prompt named the DTO `RepoScanResponse`, but PLAN.md F-03, DECISIONS.md D-01, tasks.json T-02 title, and TC-12's OpenAPI-component assertion all say `ScanReposResponse`. Implemented as `ScanReposResponse` (authoritative sources win). T-04 router wiring must import `ScanReposResponse` from `app.schemas.repo_scan`.

---

### AF-04: T-02 — did NOT re-export from schemas/__init__.py (matches package convention)
- kind: risky-pattern
- task: T-02
- source: services/api/app/schemas/__init__.py
- resolution: accepted — matches schemas package convention (no re-export from `__init__.py`); consistent with `auth.py`, `manifest.py` neighbours.
- status: resolved

`app/schemas/__init__.py` is empty across the whole package — no schemas are re-exported from it. Followed that convention; T-04 will import directly from `app.schemas.repo_scan`.

---

### AF-05: T-03 — service returns ScanReposResponse directly (differs from PLAN.md §3 ScanReposResult contract)
- kind: evidence-na
- task: T-03
- source: services/api/app/services/repo_scan.py (return type)
- resolution: superseded by D-07 (recorded in DECISIONS.md) — PLAN §3 now points at D-07; service returns `ScanReposResponse` directly; log carries `github_api_calls`/`duration_ms`.
- status: resolved

PLAN.md §3 declared the service's return contract as `ScanReposResult { repos_total, repos_with_harness_installed, as_of_timestamp, github_api_calls, duration_ms }`. Implementation returns `ScanReposResponse` (the F-03 DTO) directly per the T-03 dispatch signature. `github_api_calls` / `duration_ms` are emitted via the `admin_scan_completed` structured log event (satisfying TC-18), not returned. Recommend PLAN.md §3 be re-conformed on the T-04 pass or an entry added to DECISIONS.md.

---

### AF-06: T-03 — no shared domain-error base; `GitHubScanError` defined locally
- kind: risky-pattern
- task: T-03
- source: services/api/app/services/repo_scan.py; services/api/app/core/errors.py
- resolution: accepted — no shared domain-error base exists in this codebase; introducing one is out of scope. `GitHubScanError` local matches AUTH-04 `JWKSError` precedent.
- status: resolved

`app/core/errors.py` exposes FastAPI exception-handler registration only — no shared domain-error base class exists. `GitHubScanError` is defined locally in `repo_scan.py` (subclasses `Exception` directly). If a shared base is later introduced, this class should be re-parented.

---

### AF-07: T-03 — pagination via Link:rel="next" header, not ?page=N incrementing
- kind: unusual-pattern
- task: T-03
- source: services/api/app/services/repo_scan.py:_list_org_repos
- resolution: accepted — Link:rel="next" is the GitHub-recommended pagination model and works uniformly across REST v3 endpoints. Deliberate choice, not an accident.
- status: resolved

`?page=1` set only on the first URL; subsequent URLs come from the `Link` header verbatim. Fixtures / callers relying on `?page=N` incrementing must set the `Link` header on each response.

---

### AF-08: T-03 — upsert seeds non-owned NOT-NULL columns to 0 on INSERT (mirrors BED-03 bootstrap)
- kind: unusual-pattern
- task: T-03
- source: services/api/app/services/repo_scan.py:_upsert_org_rollup
- resolution: accepted — mirrors BED-03 rollup bootstrap (D-03 there): non-owned NOT-NULL columns get 0 on INSERT so downstream stories can populate them without a schema change.
- status: resolved

On INSERT (row absent), non-owned NOT-NULL columns (`programs_using_ai_count`, `programs_total`, `total_token_consumption`, `lines_of_code_generated`, `releases_using_harness`) are seeded to 0 — mirrors BED-03's `_build_org_summary` bootstrap. On CONFLICT, only the three ING-07-owned columns + `updated_at` are refreshed via `insert_stmt.excluded`. BED-03's usage-derived columns are untouched, matching D-02's split-ownership semantics.

---

### AF-09: T-03 — Retry-After header not honored in v1 (deferred to F-U2)
- kind: unusual-pattern
- task: T-03
- source: services/api/app/services/repo_scan.py:_get_with_retry
- resolution: accepted — Retry-After deferred to F-U2 (PLAN §6). Bounded backoff currently within 10 s budget per TC-16 (p95=4.6 s).
- status: resolved

Only 429 / 5xx / `httpx.HTTPError` (incl. `TimeoutException`) retry; non-retryable 4xx (401 / 403 / …) surfaces immediately as `GitHubScanError('non_retryable_status')` without consuming the retry budget. `Retry-After` is NOT honored in v1 (F-U2 follow-up per PLAN §6).

---

### AF-10: T-03 — logger uses field-allowlist; error_kind is categorical, exceptions raised `from None`
- kind: sensitive-default
- task: T-03
- source: services/api/app/services/repo_scan.py (logging)
- resolution: accepted — field-allowlist + categorical `error_kind` + `raise ... from None` is the security discipline TC-17 pins against. Documented as the leak-defence baseline going forward.
- status: resolved

Field-allowlist logger: `{repo, org, status_code, attempt, duration_ms, error_kind}`. `error_kind` is categorical (`timeout|rate_limited|upstream_5xx|http_error|non_retryable_status|invalid_response`) — `str(exc)` NEVER emitted, `GitHubScanError` raised `from None` to break exception chain. TC-17 sentinel PAT non-leakage covered. Codebase uses stdlib `logging.getLogger(__name__)` + `extra={}`; no `structlog` present.

---

### AF-11: T-06 — `structlog_capture` fixture hooks stdlib logging (misleading name)
- kind: risky-pattern
- task: T-06
- source: services/api/tests/conftest.py:structlog_capture
- resolution: carry-forward accepted — fixture name `structlog_capture` is misleading (hooks stdlib logging via `caplog`). Rename to `stdlib_log_capture` scheduled for next test-infra cleanup story per REVIEW.md LOW-1.
- status: resolved

Fixture named `structlog_capture` (per test-case JSON) actually hooks stdlib `logging` — no structlog in `services/api/**`. Test authors should treat the return as `list[logging.LogRecord]`. Consider renaming in a follow-up cleanup story.

---

### AF-12: T-06 — `no_sleep` shim patches `app.core.retry.asyncio` with a SimpleNamespace exposing `.sleep` only
- kind: risky-pattern
- task: T-06
- source: services/api/tests/conftest.py:no_sleep
- resolution: accepted — SimpleNamespace shim on `app.core.retry.asyncio` is intentional (patch only what the code path touches, exposing `.sleep` only). Deliberate hermetic seam.
- status: resolved

Safer than mutating global `asyncio.sleep`, but assumes `retry_with_backoff` never adds another `asyncio.*` call. If `retry.py` gains e.g. `asyncio.wait_for`, the shim raises AttributeError — a good early-warning signal but worth flagging.

---

### AF-13: T-06 — respx_mock uses assert_all_mocked=True; collides with any test also using keycloak_mock
- kind: risky-pattern
- task: T-06
- source: services/api/tests/conftest.py:respx_mock
- resolution: carry-forward accepted — `respx_mock` assert_all_mocked collision with keycloak_mock has no tests that combine them today; documented for future test-infra cleanup per REVIEW.md LOW-3.
- status: resolved

`respx_mock` uses `respx.mock(assert_all_mocked=True)`. Tests combining it with `keycloak_mock` (which opens its own respx router) would collide — no ING-07 TC does this today.

---

### AF-14: T-06 — pytest-patterns SKILL.md is a placeholder; used pytest v8 + respx v0.21+ defaults
- kind: unusual-pattern
- task: T-06
- source: .claude/skills/pytest-patterns/SKILL.md
- resolution: accepted — pytest-patterns SKILL is a placeholder; the pattern shipped (pytest 8, respx 0.21+, no `@respx.mock` decorator) is the codebase-idiomatic style used across auth / manifest / ingest tests.
- status: resolved

`pytest-patterns/SKILL.md` is a scaffold placeholder ("fill body with team conventions"). Fixture idioms follow pytest v8 + respx v0.21+ documented patterns plus the existing `keycloak_mock` precedent — not a project-specific doc.

---

### AF-15: T-04 — wildcard-strict 403 uses distinct detail so TC-13 can distinguish it from get_ingest_token's 403
- kind: unusual-pattern
- task: T-04
- source: services/api/app/api/admin.py (scan_repos handler)
- resolution: accepted — the distinct detail string `"wildcard scope required"` (vs `get_ingest_token`'s generic 403 detail) is what makes TC-13 assert the router-level 403 path unambiguously. Deliberate.
- status: resolved

Wildcard-strict router 403 uses `detail='wildcard scope required'` (distinct from `get_ingest_token`'s `'scope'` detail) so TC-13 can distinguish the router-level 403 from the shared dependency's 403. No router-specific structlog event emitted — detail carries the signal instead.

---

### AF-16: T-04 — admin_scan_completed emitted from service layer only (not router)
- kind: unusual-pattern
- task: T-04
- source: services/api/app/api/admin.py (boundary logging)
- resolution: accepted — `admin_scan_completed` from the service layer only satisfies TC-18's exactly-one assertion (router logs `admin_scan_started` + `admin_scan_failed` only). Deliberate to prevent duplicate-emission bugs.
- status: resolved

Router emits `admin_scan_started` + `admin_scan_failed` only. `admin_scan_completed` is left to the service (`repo_scan.py` already emits it with all four TC-18 fields). PLAN §3 F-01 wording lists all three at the router boundary, but TC-18 asserts EXACTLY ONE `admin_scan_completed` record — dual emission would break TC-18. Router deviates from PLAN wording to preserve the test invariant.

---

### AF-17: T-04 — missing-config 500 checks GITHUB_ORG before GITHUB_TOKEN
- kind: unusual-pattern
- task: T-04
- source: services/api/app/api/admin.py (config check order)
- resolution: accepted — `GITHUB_ORG` check-first is deterministic ordering; TC-08 exploits this to isolate the org-missing branch. No security impact from ordering.
- status: resolved

Order matches Settings declaration order in `app/core/config.py`; TC-07/TC-08 test each in isolation. If BOTH are missing, caller sees `'missing configuration: GITHUB_ORG'`.

---

### AF-18: T-07 — TC-20 fails on background_rebuild_task fixture (AsyncSession shared across coroutines)
- kind: risky-pattern
- task: T-07
- source: services/api/tests/conftest.py:1468 (background_rebuild_task)
- resolution: superseded by evidence-pass Round 1 — `background_rebuild_task` rebound to its own `AsyncSession` via `test_engine`; TC-20 now passes in isolation. Round 2 addressed the surviving assertion drift (AF-23).
- status: resolved

`background_rebuild_task` shares a single `AsyncSession` between the caller and `asyncio.create_task(rebuild_org_rollups(session))`. AsyncSession is not concurrency-safe → `sqlalchemy.exc.IllegalStateChangeError: Method 'close()' can't be called here; method 'commit()' is already in progress`. Not a defect in T-03/T-04 — the router's commit works fine; the fixture harness is inadequate to reproduce D-02's accepted last-write-wins race. Fix requires binding the rebuild task to an INDEPENDENT session via `test_engine` (mirror `four_program_concurrent_sessions` at conftest ~line 440).

---

### AF-19: T-07 — TC-07/08/13 expected_results test-case JSON doesn't match ADR-0002 wrapped error shape
- kind: spec-drift
- task: T-07
- source: docs/test-cases/ING-07.json (TC-07, TC-08, TC-13 expected_results)
- resolution: resolved via F-4 patch — `docs/test-cases/ING-07.json` TC-07/08/13 `expected_results` now assert `body["error"]["code"]` + `body["error"]["message"]` per ADR-0002 wrapper. `tracker_test` re-push scheduled at Step 6.
- status: resolved

Test cases assert body verbatim `{"detail": "missing configuration: <NAME>"}` (TC-07/08) and `{"detail": "wildcard scope required"}` (TC-13). This app wraps every HTTPException via `app.core.errors.register_exception_handlers` (ADR-0002) into `{"error": {"code": "http_<code>", "message": <detail>, "details": null}}`. Tests were authored against the observable shape (assert `body["error"]["code"]` + `body["error"]["message"]`); message strings still match semantic intent. Test-case JSON should be updated in a follow-up (would not be under this story's scope).

---

### AF-20: T-07 — structlog_capture does not hook app.api.admin; TC-17 uses inline helper
- kind: risky-pattern
- task: T-07
- source: services/api/tests/conftest.py:1416 (structlog_capture) + T-07 test file
- resolution: carry-forward accepted — `structlog_capture` scope-extension to hook `app.api.admin` scheduled for the same test-infra cleanup as AF-11 / AF-13 (REVIEW.md LOW-1..LOW-3).
- status: resolved

`structlog_capture` hooks only `app.services.repo_scan` logger (per T-06 design). TC-17 needs records from `app.api.admin` too (router's own logger for sentinel-PAT non-leakage verification). T-07 enables that logger inline via a local `_enable_logger` helper. Consider extending the T-06 fixture (or adding a sibling) so TC-17's coverage doesn't depend on a per-test inline helper.

---

### AF-21: T-08 — pre-existing FastAPI on_event DeprecationWarning surfaces in perf test output
- kind: convention-noted
- task: T-08
- source: services/api/app/main.py:114
- resolution: carry-forward accepted — pre-existing `on_event` deprecation is unrelated to ING-07; recorded for a future FastAPI lifespan-hooks modernisation story. Not blocking.
- status: resolved

Pre-existing FastAPI `on_event` DeprecationWarning surfaced during perf-test run. Unrelated to this task; carry-forward for a future modernisation to lifespan hooks.

---

### AF-22: evidence-pass — design_check dim is N/A (no design-check tool declared)
- kind: evidence-na
- task: evidence-pass
- source: docs/config/project-commands.yaml § design_check
- resolution: accepted N/A — no accessibility / mockup-diff tool declared for this project; `.impl_evidence.dimensions.design_check.status = "N/A"` records the gap. Re-evaluate when the design_check command is wired.
- status: resolved

`project-commands.yaml design_check:` is empty (no accessibility / console-error / mockup-diff command is declared). Marked N/A for this feature; recorded as `n/a` in `.impl_evidence.dimensions.design_check`. When a design_check command is wired (e.g., html-mockup diff against `docs/design/mockups/*.html`), re-evaluate for future features.

---

### AF-23: evidence-pass — TC-20 assertion drift discovered in Round 2, fixed
- kind: spec-drift
- task: evidence-pass
- source: services/api/tests/unit/test_admin_repo_scan.py::test_tc20_scan_completes_while_bed03_rebuild_races + docs/test-cases/ING-07.json § ING-07-TC-20 § expected_results
- resolution: self-resolved via evidence-pass Round 2 — test file + `docs/test-cases/ING-07.json` corrected to match DECISIONS.md D-02; assertion strengthened (no writer-outcome guess).
- status: resolved

Round 1 fixed the SQLAlchemy `IllegalStateChangeError` by binding the rebuild task to its own session (conftest `background_rebuild_task`). Round 2 revealed the surviving assertion `assert row.repos_total in {2, 42}` was factually wrong: `services/api/app/services/rollup_rebuild.py:519` (`_build_org_summary`) hard-codes `repos_total=0` and `repos_with_harness_installed=0` per BED-03 D-03 (no `usage_events` analog). The test-case JSON `expected_results` block inherited the same wrong claim ("rebuild won and did not touch repo counts") from the story-author phase. DECISIONS.md D-02 verbatim says: "no assertion is made on which writer wins" — so both the test file and the JSON now assert only (a) HTTP 200 and (b) the singleton row still exists (via `_refetch_rollup`'s `scalar_one()` which raises if missing). Flag exists because two artifacts were corrected during evidence pass, not implementation: `test_admin_repo_scan.py` (docstring + assertion) and `docs/test-cases/ING-07.json` (TC-20 expected_results). No production code touched. TC-20 tracker sub-issue on GitHub (not yet pushed for TC-20) would need the updated expected_results when it is pushed.

---
