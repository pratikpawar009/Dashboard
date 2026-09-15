# Code Review — feature/ING-07 (Admin GitHub repo-scan endpoint)

- Date: 2026-09-15T09:45:00Z
- Mode: story (`/arh-implement` Step 2, standalone with resolved story id ING-07)
- Target ref: `feature/ING-07` working tree vs `main` (`be444ae`)
- Tree anchor: `d5f14759a0cdcb131b2ab863317dd38d424e73340563de7f7b06007815982d69`
- Files reviewed: 17 (9 modified, 8 new; `docs/activity/activity.jsonl` and untracked `tmp/` excluded per anti-scope)
- Verdict: **PASS WITH WARNINGS**

## Executive summary

Implementation faithfully honors the seven pinned PLAN sections, D-01..D-06, and every applicable `.claude/rules/*-baseline.md`. The admin router (`services/api/app/api/admin.py`) implements the exact D-05 pattern (router-owned `HTTPBearer`, `get_ingest_token(program_id="*")` invoked directly, wildcard-strict re-check, ordered 401 → 403 → 500 → 502), and `services/api/app/services/repo_scan.py` is the sole GitHub `httpx` importer per D-03, with a field-allowlist logger and a `from None` exception chain that closes the TC-17 PAT-leak surface convincingly. Nineteen unit tests, one perf test, twenty-seven fixtures, and a real ADR-0002 wrapper-aware assertion shape land the observable contract accurately.

Four MEDIUM findings all live in *documentation coherence*, not in the shipping code path: the `docs/requirements/api.md#admin-scan-api` `shape:` block still declares no response body (F-1), the `scripts/` directory was authored PRD-phase and never entered `tasks.json.file_plan` (F-2), PLAN.md §3 still describes a `ScanReposResult` DTO the service does not return (F-3), and the pushed test-case JSON entries for TC-07/TC-08/TC-13 assert an unwrapped `{"detail": ...}` shape the tests themselves rightly disregard (F-4). Four LOW findings mirror agent flags AF-11/AF-12/AF-13/openapi-fixture. Nothing here blocks merge; every MEDIUM has a documented follow-up path in PLAN §6 or the FLAGS log.

🟢 strengths   |  ⚠️ warnings (4 MEDIUM, 4 LOW, 2 INFO)   |  🛑 blockers (none)

## Findings summary

| Severity | Count | Category distribution                                                                     |
|----------|-------|-------------------------------------------------------------------------------------------|
| CRITICAL |   0   | —                                                                                         |
| HIGH     |   0   | —                                                                                         |
| MEDIUM   |   4   | contract-drift (1), scope-creep (1), design-patterns (1), testability (1)                 |
| LOW      |   4   | design-patterns (3), testability (1)                                                      |
| INFO     |   2   | module-structure (1), design-patterns (1)                                                 |

## Detailed findings

### CRITICAL

_None._

### HIGH

_None._

### MEDIUM

#### F-1 — contract-drift: `admin-scan-api` `shape:` block not updated with `ScanReposResponse`

- Category: contract-drift
- Path: `docs/requirements/api.md:541-548` (contract) vs `services/api/app/schemas/repo_scan.py:18-40`, `services/api/app/api/admin.py:79-91` (surface)
- Source: `docs/requirements/api.md#admin-scan-api` (contract this story `produced_by:` — see PLAN.md §6 F-U1)
- Description: The `admin-scan-api` contract's `shape:` block still enumerates only `endpoint`, `auth`, `effect`. This story ships a fully-formed produced-surface (response body `ScanReposResponse` = `{repos_total: int, repos_with_harness_installed: int, as_of_timestamp: ISO-8601-UTC-Z}`, `response_model` pinned on the route, OpenAPI component exported), asserted by TC-12 as the story's runtime source of truth. Per `review-assessment` § *contract-drift*: a surface change to a produced contract without a same-diff update to the `.md` section is a HIGH-shaped finding. Downgraded to MEDIUM because (a) `consumed_by: []` — no downstream story binds to the shape, so no consumer sees a stale contract, and (b) the deferral is explicit in PLAN.md §6 F-U1 and PRD D-01, both authored before implementation.
- Suggested fix: File F-U1 as a follow-up documentation task (post-merge) and either extend `shape:` with the response body, OR add an `RTM decisions` entry acknowledging the contract is intentionally under-declared. Do not silently leave the drift permanent.

#### F-2 — scope-creep: `scripts/push-test-cases-ING-07.py` is not in `tasks.json.file_plan`

- Category: scope-creep
- Path: `scripts/push-test-cases-ING-07.py` (untracked, ~130 LOC)
- Source: `docs/features/ING-07/tasks.json` `file_plan` F-01..F-12 — none declare `scripts/**`
- Description: The PRD-phase test-case tracker-push helper was written into a top-level `scripts/` directory that did not previously exist in the repo (`file_search scripts/**` returns only `services/api/scripts/**` and `services/mcp-server/scripts/**`). No task's `files[]` references it and no F-NN covers it. Per `.claude/rules/surgical-changes.md` and the `scope-creep` category, a file introduced outside the declared file plan is a finding regardless of intent. Additionally, `scripts/` sits above the two established service-nested `scripts/` locations, breaking the repo's directory convention (`.claude/rules/pattern-consistency.md`).
- Suggested fix: One of (a) move to a service-nested `services/api/scripts/` or a new `tools/` directory with a rationale in DECISIONS.md; (b) delete the file (the tracker push it performed is already committed to `docs/test-cases/ING-07.json` via `tracker_test` back-refs); or (c) add to `.gitignore` if it must stay local-only and add an entry in PLAN.md §6 as a carry-forward.

#### F-3 — design-patterns: PLAN.md §3 declares `ScanReposResult` DTO the service does not return

- Category: design-patterns
- Path: `docs/features/ING-07/PLAN.md:66-74` (declares `ScanReposResult { repos_total, repos_with_harness_installed, as_of_timestamp, github_api_calls, duration_ms }`) vs `services/api/app/services/repo_scan.py:270,346-350` (returns `ScanReposResponse` DTO, three fields)
- Source: `docs/features/ING-07/PLAN.md §3` (module hierarchy); AF-05 (self-reported at implementation time)
- Description: The plan declares the service layer's return contract as a five-field `ScanReposResult` sentinel type. The actual implementation returns `ScanReposResponse` directly (three fields) and emits `github_api_calls` + `duration_ms` on the `admin_scan_completed` log record only. This works — TC-18 asserts the log fields exist and TC-01/TC-12 assert the response body — but the PLAN artifact now describes a shape that no code produces. Per `.claude/rules/pattern-consistency.md`, a plan section that documents phantom types loses its value as a review reference. AF-05 correctly flags the same drift and suggests either PLAN edit or a DECISIONS.md entry.
- Suggested fix: Add a one-line entry to `docs/features/ING-07/DECISIONS.md` (e.g. D-07) recording "service returns `ScanReposResponse` directly; `github_api_calls`/`duration_ms` propagate via structured log only" and update PLAN.md §3 to point at it. `rev:mechanical` — no code change.

#### F-4 — testability: TC-07/TC-08/TC-13 `expected_results` in `docs/test-cases/ING-07.json` still assert the unwrapped `{"detail": ...}` shape

- Category: testability
- Path: `docs/test-cases/ING-07.json` (ING-07-TC-07, ING-07-TC-08, ING-07-TC-13 `expected_results`) vs `services/api/tests/unit/test_admin_repo_scan.py:395-401,428-434,631-637`
- Source: `docs/adr/0002-*.md` (error envelope), AF-19 (self-reported at implementation time)
- Description: The test cases assert body `{"detail": "missing configuration: GITHUB_ORG|GITHUB_TOKEN"}` (TC-07/08) and `{"detail": "wildcard scope required"}` (TC-13). The shipping app wraps every `HTTPException` via `app.core.errors.register_exception_handlers` (ADR-0002) into `{"error": {"code": "http_<code>", "message": <detail>, "details": null}}`. The Python test file correctly asserts the wrapped shape, so tests pass — but a reader (or a tracker-linked reviewer) opening the pushed GitHub issues for TC-07/08/13 will see a shape that does not match the runtime response. The semantic intent (message strings) is preserved on both sides. Same class of finding as F-1: doc-vs-code drift with no functional impact.
- Suggested fix: Update the three `expected_results` blocks in `docs/test-cases/ING-07.json` to reference the ADR-0002 wrapped shape (`body["error"]["code"] == "http_500"`, `body["error"]["message"] == "..."`). The tracker sub-issues can then be edited via a one-shot re-push if desired. No production or test code change.

### LOW

#### L-1 — design-patterns: `structlog_capture` fixture actually hooks stdlib `logging`, not structlog

- Category: design-patterns
- Path: `services/api/tests/conftest.py:1416-1448`
- Source: `.claude/rules/pattern-consistency.md`, AF-11 (self-reported)
- Description: Fixture is named `structlog_capture` (matching `docs/test-cases/ING-07.json` `fixtures[]` verbatim) but the codebase has no structlog import anywhere under `services/api/**`. The fixture hooks `logging.getLogger("app.services.repo_scan")` and captures `LogRecord` objects. The name promises a structlog contract it does not fulfil; a future test author reading only the fixture reference in a JSON `fixtures[]` array will assume structlog is present.
- Suggested fix: Rename to `repo_scan_log_capture` (or the shipped project's stdlib-`logging` idiom) in a follow-up cleanup story, update both `docs/test-cases/ING-07.json` and the fixture definition atomically. Not blocking — the fixture works today.

#### L-2 — design-patterns: `no_sleep` shim replaces `app.core.retry.asyncio` with a `SimpleNamespace` exposing only `.sleep`

- Category: design-patterns
- Path: `services/api/tests/conftest.py:1379-1395`
- Source: `.claude/rules/reusability-baseline.md`, AF-12 (self-reported)
- Description: The shim patches the module-level `asyncio` name inside `app.core.retry` with `types.SimpleNamespace(sleep=_noop_sleep)`. If `app/core/retry.py` gains any other `asyncio.*` reference (e.g., `asyncio.wait_for`, `asyncio.TaskGroup`) the shim raises `AttributeError` at retry time. Early-warning is a feature, but a future consumer might over-index on the fragility.
- Suggested fix: Prefer `monkeypatch.setattr(_retry_module.asyncio, "sleep", _noop_sleep)` (patches the attribute in place, leaves other names intact). One-line change; consider deferring until `retry.py` grows.

#### L-3 — design-patterns: `respx_mock` fixture uses `assert_all_mocked=True`; would collide with `keycloak_mock` if combined in one test

- Category: design-patterns
- Path: `services/api/tests/conftest.py:1119-1123`
- Source: AF-13 (self-reported)
- Description: Both `respx_mock` (this feature) and `keycloak_mock` (pre-existing) open their own `respx.mock(...)` router. Combining them in a single test would nest routers and the outer `assert_all_mocked=True` would reject any call the inner router owns. No ING-07 TC combines them today, but the pattern is a landmine for future auth-touching endpoint tests.
- Suggested fix: Document the mutual-exclusion in the fixture docstring, or refactor toward a single top-level `respx` router (a broader cleanup story).

#### L-4 — testability: `# type: ignore[no-any-return]` on `openapi_schema` fixture

- Category: testability
- Path: `services/api/tests/conftest.py:1462`
- Source: `.claude/rules/project-standards.md`
- Description: The fixture returns `response.json()` with a `# type: ignore[no-any-return]` comment. Since the callable is annotated `Awaitable[dict[str, Any]]`, adding `cast(dict[str, Any], response.json())` would remove the suppression without changing behavior. Minor.
- Suggested fix: Replace the ignore with an explicit `cast` from `typing`.

### INFO

#### I-1 — module-structure: untracked `tmp/` directory in the working tree

- Category: module-structure
- Path: `tmp/`
- Source: `.claude/rules/surgical-changes.md`
- Description: `git status` shows an untracked `tmp/` directory. Contents include validation working notes (per one of the terminal cwds). Not shipped (untracked) and outside the diff scope requested for this review, but it should not be committed by accident.
- Suggested fix: Add `tmp/` to root `.gitignore` before the next commit, or clear the directory. No functional impact.

#### I-2 — design-patterns: `app.core.retry.retry_with_backoff` uses bare `except Exception`

- Category: design-patterns
- Path: `services/api/app/core/retry.py:29`
- Source: `.claude/rules/security-baseline.md`, PLAN.md D-04
- Description: The retry helper catches `except Exception` broadly, which is what D-04 depends on to make `_RetryableStatus` retryable and `httpx.TimeoutException` retryable via a single sentinel. This is pre-existing code (ADR-0002), not part of ING-07's diff, and the `# noqa: BLE001` marker is in place. Recorded as INFO to make explicit that ING-07 depends on this shape — a future tightening of the retry helper must preserve the retryable-Exception contract or ING-07's `_get_with_retry` needs a redesign.
- Suggested fix: None for ING-07. When the retry helper is next touched, encode the retryable-exception contract in its docstring or types.

## Six-dimension assessment

| # | Dimension                           | Result                                                                                                                                      |
|---|-------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------|
| 1 | Module structure & boundaries       | PASS. New router / service / schema mount cleanly; wiring per PLAN F-04 (`main.py` line ordering respects ADR-0013 manifest precedent).      |
| 2 | Design patterns                     | PASS with LOW-severity naming drift (L-1, L-2, L-3). D-03 (dedicated GitHub client), D-04 (existing retry helper reused), D-05 (manifest.py auth pattern replicated) all honored. |
| 3 | Component / module architecture     | PASS. Router owns transaction boundary (D-02); service performs the upsert on the passed session without commit; `from None` exception re-raise breaks upstream body propagation (TC-17). |
| 4 | Integration points                  | PASS. Error envelope wrapped by ADR-0002 handler; retry via `retry_with_backoff` bounded 4 attempts (FR-3); `httpx.Timeout(10.0)` per-call; response DTO pinned via `response_model=`. |
| 5 | Testability                         | PASS with MEDIUM (F-4) and LOW (L-4). 19 unit + 1 perf test; no `pytest.mark.skip`, no xfail; no blanket `except`; the two `# type: ignore` markers are on legitimate `LogRecord` dynamic attribute access. |
| 6 | Safety & security                   | PASS. TC-17 sentinel-PAT test covers logger + `caplog` + response body across router (via `_enable_logger`) and service. `Authorization` header value never logged. `github_token` treated as a secret in Settings (docstring cites `.claude/rules/security-baseline.md`). |

## Scoped categories

| Category         | Result                                                                                                                              |
|------------------|-------------------------------------------------------------------------------------------------------------------------------------|
| scope-creep      | 1 MEDIUM (F-2) — `scripts/push-test-cases-ING-07.py` outside `file_plan`.                                                          |
| adr-violation    | 0. Every DECISIONS.md entry (D-01..D-06) honored verbatim. ADR-0002 error-wrapper shape respected in tests. No ADR contradiction.  |
| contract-drift   | 1 MEDIUM (F-1) — `admin-scan-api` `shape:` block not extended; downgraded because `consumed_by: []` and the deferral is explicit in PLAN §6 F-U1. |

## What went well

- **D-05 replication is exemplary**: `admin.py`'s module docstring cites `manifest.py`'s precedent, threads `program_id="*"` as a sentinel, adds a distinct 403 detail (`"wildcard scope required"`) so TC-13 can distinguish router-level vs shared-dependency rejection. AF-15's concern is neutralized by the distinct detail choice.
- **Field-allowlist logger discipline** (`services/api/app/services/repo_scan.py:154-186,342-352`) is the strongest PAT-leak defense I've reviewed in this codebase: no `str(exc)`, categorical `error_kind`, `raise ... from None` at the `GitHubScanError` seam, and TC-17 asserts across three log capture surfaces plus response body.
- **Transaction boundary** is correctly owned by the router. On `GitHubScanError`, `get_db()`'s `async with SessionLocal()` closes without a commit → the queued upsert never lands → FR-4 no-partial-write is enforced by SQLAlchemy's session lifecycle, not by conditional code paths that could regress.
- **TC-16 perf test is honest**: no warm-up trimming, no outlier removal, N=30 iterations against a real 200-repo pagination + 200 sequential probes; the module docstring calls out the discipline explicitly.
- **Evidence-pass Round 2 fix on TC-20** correctly reflected D-02's "no assertion is made on which writer wins" contract in both the test file and `docs/test-cases/ING-07.json`. AF-23 documents the diagnosis path; no code was regressed to make the test pass.

## Recommendation

**PASS WITH WARNINGS**. Merge is not blocked. Before or immediately after merge:

1. Land the four MEDIUM follow-ups as either (a) a single "ING-07 doc coherence" carry-forward story or (b) discrete tracker items — F-1 (contract extend), F-2 (`scripts/` disposition), F-3 (PLAN §3 reconciliation), F-4 (test-case JSON re-push).
2. LOW findings roll into a future test-infrastructure cleanup story (rename `structlog_capture`, harden `no_sleep`, document `respx_mock` mutual exclusion).
3. Delete or `.gitignore` the `tmp/` working directory before the next commit (I-1).
