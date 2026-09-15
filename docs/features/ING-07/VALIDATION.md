# Validation report — ING-07

- Story: ING-07 (Admin GitHub repo-scan endpoint)
- Branch: `feature/ING-07` @ `be444ae54ebafcdb6c71b6650b336e2b9ca1f095`
- Date: 2026-09-15T11:02:23Z
- Mode: full (invoked by `/arh-implement` Step 2, READ-ONLY of source; write scope limited to `docs/test-cases/ING-07.json`, this report, and `state.json .validation` per SKILL)
- **Verdict: PASS**
- Total: 20   Passed: 20   Failed: 0   Errored: 0   Flaky: 0   Skipped manual: 0
- Duration: ~13 min (started 2026-09-15T10:49:26Z, ended 2026-09-15T11:02:23Z)

Evidence-pass dimensions (typecheck/lint/build/runtime/compile/design_check) were **not** re-run per the orchestrator directive — verdict READY at `state.json .impl_evidence` (2 rounds, 6 dims PASS/N-A) already covers those. This report focuses on E2E TC execution, task-completion audit, contract conformance, and proof-of-run.

## Summary

| Layer        | Total | Pass | Fail | Error | Flaky |
|--------------|-------|------|------|-------|-------|
| Stack smoke  |   1   |   1  |   0  |   0   |   0   |
| Unit         |  17   |  17  |   0  |   0   |   0   |
| Contract     |   1   |   1  |   0  |   0   |   0   |
| Security     |   1   |   1  |   0  |   0   |   0   |
| Performance  |   1   |   1  |   0  |   0   |   0   |

Layer mapping (TC `type` field):
- Unit → `type: integration` (16) + `type: unit`-shaped (0) — TCs 01–11, 14, 15, 18, 19, 20
- Contract → `type: contract` — TC-12
- Security → `type: security` — TC-13, TC-17 (2 TCs; TC-13 counted here, TC-17 also has security nature; the summary rolls TC-13 into unit for brevity — full per-TC breakdown below)
- Performance → `type: performance` — TC-16 (measured p95=4613.28ms << 10000ms budget → `budget_pass: true`)

Stack-smoke row: `fastapi-2` — real uvicorn boot against Postgres 16 (host :15432, remapped from :5432 due to host `Postgres.app` on :5432), alembic migrations applied, `/health` returned 200 in 1s, `POST /api/admin/scan-repos` unauth returned `401 {"error":{"code":"http_401","message":"missing","details":null}}` (ADR-0002 envelope confirmed).

## Task completion verification (MANDATORY)

Cross-check of every entry in `docs/features/ING-07/tasks.json` `tasks[]` against on-disk artifacts.

| Task | Target file(s) | Existence | Section match | Verdict |
|------|----------------|-----------|---------------|---------|
| T-01 | [services/api/app/core/config.py](services/api/app/core/config.py#L108-L109) (`github_org` + `github_token` added); [services/api/.env.example](services/api/.env.example#L105-L119) (`GITHUB_ORG=` / `GITHUB_TOKEN=` block) | ✓ | ✓ (grep `github_org`, `github_token`, `GITHUB_ORG`, `GITHUB_TOKEN`) | **PASS** |
| T-02 | [services/api/app/schemas/repo_scan.py](services/api/app/schemas/repo_scan.py) (`ScanReposResponse`) | ✓ | ✓ (module created; TC-12 asserts three-key contract + `Z` suffix) | **PASS** |
| T-03 | [services/api/app/services/repo_scan.py](services/api/app/services/repo_scan.py) (`scan_org_repos`, `GitHubScanError`, `admin_scan_completed`) | ✓ | ✓ (TC-18 verifies event + fields; TC-17 verifies no-leak; TCs 09/10/14/15 exercise retry/timeout/atomicity) | **PASS** |
| T-04 | [services/api/app/api/admin.py](services/api/app/api/admin.py) (`POST /api/admin/scan-repos`, wildcard-strict, 500/502 mapping) | ✓ | ✓ (TC-04/05/06/07/08/12/13 all pass) | **PASS** |
| T-05 | [services/api/app/main.py](services/api/app/main.py#L5) (`admin_router` import) + [L104](services/api/app/main.py#L104) (`include_router(admin_router)`) | ✓ | ✓ (grep hit; smoke-boot confirmed route mounted) | **PASS** |
| T-06 | [services/api/tests/conftest.py](services/api/tests/conftest.py) (27 ING-07 fixtures) | ✓ | ✓ (all 19 unit tests + 1 perf test use these fixtures and pass) | **PASS** |
| T-07 | [services/api/tests/unit/test_admin_repo_scan.py](services/api/tests/unit/test_admin_repo_scan.py) (19 tests, TC-01..TC-15, TC-17..TC-20) | ✓ | ✓ (19/19 PASSED) | **PASS** |
| T-08 | [services/api/tests/perf/test_admin_repo_scan_perf.py](services/api/tests/perf/test_admin_repo_scan_perf.py) (TC-16, `@pytest.mark.perf`) | ✓ | ✓ (1/1 PASSED, p95=4613ms) | **PASS** |
| T-09 | [README.md](README.md#L75-L76) (`GITHUB_ORG` + `GITHUB_TOKEN` rows in `## Environment variables` table) | ✓ | ✓ (grep `GITHUB_ORG` / `GITHUB_TOKEN` hit L75–L76) | **PASS** |
| T-10 | [services/api/README.md](services/api/README.md#L298-L312) (`## Admin scan` sub-section) | ✓ | ✓ (grep `^## Admin scan` hit L298; status matrix + config bullets present) | **PASS** |

All 10 tasks `status: done` in `tasks.json` — file existence, sanction section headings, and code-under-test all present. Zero blocked, zero skipped.

## Passed

| TC id            | Type         | Test node |
|------------------|--------------|-----------|
| ING-07-TC-01 | integration  | `tests/unit/test_admin_repo_scan.py::test_tc01_happy_path_mixed_org_classifies_and_upserts_rollup` |
| ING-07-TC-02 | integration  | `tests/unit/test_admin_repo_scan.py::test_tc02_all_repos_installed_full_count` |
| ING-07-TC-03 | integration  | `tests/unit/test_admin_repo_scan.py::test_tc03_no_repos_installed_zero_count` |
| ING-07-TC-04 | integration  | `tests/unit/test_admin_repo_scan.py::test_tc04_missing_authorization_header_returns_401_no_side_effects` |
| ING-07-TC-05 | integration  | `tests/unit/test_admin_repo_scan.py::test_tc05_unknown_bearer_returns_401_no_side_effects` |
| ING-07-TC-06 | integration  | `tests/unit/test_admin_repo_scan.py::test_tc06_program_scoped_bearer_returns_403` |
| ING-07-TC-07 | integration  | `tests/unit/test_admin_repo_scan.py::test_tc07_missing_github_token_returns_500_no_side_effects` |
| ING-07-TC-08 | integration  | `tests/unit/test_admin_repo_scan.py::test_tc08_missing_github_org_returns_500_no_side_effects` |
| ING-07-TC-09 | integration  | `tests/unit/test_admin_repo_scan.py::test_tc09_list_repos_5xx_after_retries_returns_502` |
| ING-07-TC-10 | integration  | `tests/unit/test_admin_repo_scan.py::test_tc10_list_repos_timeout_returns_502_within_1s` |
| ING-07-TC-11 | integration  | `tests/unit/test_admin_repo_scan.py::test_tc11_502_preserves_each_prior_column_individually` |
| ING-07-TC-12 | contract     | `tests/unit/test_admin_repo_scan.py::test_tc12_response_and_openapi_pin_scan_repos_response_contract` |
| ING-07-TC-13 | security     | `tests/unit/test_admin_repo_scan.py::test_tc13_allow_all_empty_bearer_rejected_by_router_wildcard_recheck` |
| ING-07-TC-14 | integration  | `tests/unit/test_admin_repo_scan.py::test_tc14_429_then_200_retries_once_and_succeeds` |
| ING-07-TC-15 | integration  | `tests/unit/test_admin_repo_scan.py::test_tc15_mid_scan_probe_failure_returns_502_no_partial_write` |
| ING-07-TC-16 | performance  | `tests/perf/test_admin_repo_scan_perf.py::test_scan_repos_p95_under_10s_at_200_repo_baseline_tc16` — measured p95=4613.28ms vs 10000ms budget (`budget_pass: true`) |
| ING-07-TC-17 | security     | `tests/unit/test_admin_repo_scan.py::test_tc17_pat_and_upstream_body_never_leak_into_logs_or_response` |
| ING-07-TC-18 | integration  | `tests/unit/test_admin_repo_scan.py::test_tc18_admin_scan_completed_emitted_once_with_required_fields` |
| ING-07-TC-19 | integration  | `tests/unit/test_admin_repo_scan.py::test_tc19_two_consecutive_scans_produce_identical_counts` |
| ING-07-TC-20 | integration  | `tests/unit/test_admin_repo_scan.py::test_tc20_scan_completes_while_bed03_rebuild_races` |

## Failed (bug blocks)

N/A — no failures.

## Flaky tests

N/A — no retries triggered; every attempt was first-attempt PASS.

## Manual follow-up

N/A — every TC is `automatable: true`.

## Contract conformance (Phase 3b)

Grepped `docs/requirements/*.md` for sections with `produced_by: ING-07`.

- No `produced_by: ING-07` entries found in `docs/requirements/*.md`. TC-12 already pins the runtime `ScanReposResponse` shape (three keys, int/int/UTC-`Z` datetime) against the OpenAPI component export, which is the on-branch contract surface. Result: **N/A** — no contract drift to detect.

## Coverage audit (from `docs/test-cases/ING-07.json`)

Every AC / FR / NFR is covered by ≥1 passing TC.

| Requirement | Covered by (all PASS) |
|---|---|
| ING-07-AC-1 | TC-01, TC-02, TC-03, TC-19, TC-20 |
| ING-07-AC-2 | TC-04, TC-05 |
| ING-07-AC-3 | TC-06 |
| ING-07-AC-4 | TC-07, TC-08 |
| ING-07-AC-5 | TC-09, TC-10, TC-11 |
| ING-07-AC-6 | TC-12 |
| ING-07-FR-1 | TC-12 |
| ING-07-FR-2 | TC-13 |
| ING-07-FR-3 | TC-14, TC-10 |
| ING-07-FR-4 | TC-15, TC-11 |
| ING-07-FR-5 | TC-07, TC-08 |
| ING-07-NFR-performance  | TC-16 (p95=4613ms ≤ 10000ms budget) |
| ING-07-NFR-security     | TC-17, TC-13 |
| ING-07-NFR-observability| TC-18 |

`coverage_audit.uncovered` in the test-case JSON is empty (verified post-patch).

## Proof of run

| field | value |
|---|---|
| session_id                | validation-ing07-2026-09-15T10:49:26Z |
| started_at (UTC)          | 2026-09-15T10:49:26Z |
| ended_at (UTC)            | 2026-09-15T11:02:23Z |
| duration                  | ~777s wall (dominated by full-suite 190.36s + perf 136.90s + smoke boot) |
| branch                    | `feature/ING-07` |
| head_sha                  | `be444ae54ebafcdb6c71b6650b336e2b9ca1f095` |
| tree_anchor (pre-run)     | `d5f14759a0cdcb131b2ab863317dd38d424e73340563de7f7b06007815982d69` |
| tree_anchor (post-run)    | `ae0d31f72f74c4f46537e0f11909f9512438a46ef2090da9ba7504ec839aa262` (delta = `docs/test-cases/ING-07.json` per-TC `last_run`/`execution_status` updates + this report + `tmp/validation-ing07/*` artefacts; source unchanged) |
| bash_invocations          | 30 |
| test_runner_runs          | 3 (`pytest tests/` full suite, `pytest tests/unit/test_admin_repo_scan.py -v`, `pytest tests/perf/test_admin_repo_scan_perf.py -m perf`) |
| stack_smoke_runs          | 1 (`fastapi-2`: postgres:16 + alembic upgrade head + uvicorn /health + POST /api/admin/scan-repos unauth) |
| preflight_commands        | 5 (pnpm install --frozen-lockfile; uv sync; `import app.main`; `import authlib`; `import respx`; `import yaml`) — all exit 0 |
| **runtime versions** | |
| Python (services/api venv) | 3.11.9 |
| pytest                    | 9.1.1 |
| uv                        | 0.9.26 |
| Node.js                   | v22.17.1 |
| pnpm                      | 11.20.0 |
| Docker                    | 29.6.2 (postgres:16 image for smoke) |
| **commands executed** | |
| preflight step 1 | `pnpm -C apps/web install --frozen-lockfile` → `Already up to date` |
| preflight step 2 | `cd services/api && uv sync` → `Audited 47 packages` |
| preflight step 3 | `uv run python -c "import app.main"` → exit 0 |
| preflight step 4 | `uv run python -c "import authlib; print(authlib.__version__)"` → `0.15.6` |
| preflight step 5 | `uv run python -c "import respx; print(respx.__version__)"` → `0.23.1` |
| preflight step 6 | `uv run python -c "import yaml; print(yaml.__version__)"` → `6.0.3` |
| full-suite unit  | `uv run pytest tests/ -q` → `700 passed, 5 deselected in 190.36s` — log: `tmp/validation-ing07/pytest-unit.log` |
| ING-07 verbose   | `uv run pytest tests/unit/test_admin_repo_scan.py -v --tb=short` → `19 passed in 4.66s` — log: `tmp/validation-ing07/pytest-ing07-unit-verbose.log` |
| perf TC-16       | `uv run pytest tests/perf/test_admin_repo_scan_perf.py -m perf -s` → `1 passed in 136.90s`; measured `p95=4613.28ms across 30 scans` — log: `tmp/validation-ing07/pytest-perf-tc16.log` |
| stack-smoke deps | `docker run --rm -d --name dashboard-postgres-ing07-smoke -p 15432:5432 …` (remapped from :5432 because host `Postgres.app` PID 436 holds :5432) |
| stack-smoke migrate | `DATABASE_URL=…:15432/… uv run alembic upgrade head` → all 6 migrations applied, exit 0 |
| stack-smoke start   | `DATABASE_URL=…:15432/… .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info &` (PID 10039) |
| stack-smoke health  | `curl http://127.0.0.1:8000/health` → `200 {"status":"ok"}` (1s) |
| stack-smoke endpoint | `curl -X POST http://127.0.0.1:8000/api/admin/scan-repos` (no auth) → `401 {"error":{"code":"http_401","message":"missing","details":null}}` (ADR-0002 envelope confirmed) |
| stack-smoke teardown | `kill 10039 && docker rm -f dashboard-postgres-ing07-smoke` → both cleaned, `:8000` and container gone |
| boot-log grep  | `grep -cE "Traceback\|ERROR\|CRITICAL" smoke-fastapi-2.log` → `0` |
| **environment deviations** | |
| Postgres port | Ephemeral smoke postgres bound to host `:15432` (container `:5432`) because host `Postgres.app` (PID 436) already holds `:5432`. This is a smoke-only override via `DATABASE_URL`; unit tests use their own `migrated_db` fixture and are unaffected. Per skill: port-squatter identified (Postgres.app / macOS host service) → NOT killed (shared user resource); adapted with alt host port + env override. |
| Stale uvicorn on :8000 | PID 6287 (stale from evidence-pass Round-2 runtime check) held :8000. Killed to run fresh smoke boot. |

### Artefacts

- `tmp/validation-ing07/pytest-unit.log` — full 700-test suite log
- `tmp/validation-ing07/pytest-ing07-unit-verbose.log` — per-TC verbose ING-07 log
- `tmp/validation-ing07/pytest-perf-tc16.log` — TC-16 perf log with measured p95
- `tmp/validation-ing07/smoke-fastapi-2.log` — uvicorn boot + /health + /api/admin/scan-repos log
- `tmp/validation-ing07/started_at.txt`, `ended_at.txt` — timestamps
- `docs/test-cases/ING-07.json` — patched with per-TC `last_run` + `execution_status` + `execution_evidence` + `executed_at`

### Verdict justification

- All 20 TCs → PASS (19 unit + 1 perf; no retries; no flakes).
- Task audit → 10/10 PASS; no `blocked` or `skipped`.
- Stack smoke → PASS (fresh boot, migrations, /health 200, endpoint reachable, ADR-0002 wrapper confirmed on unauth).
- Contract conformance → N/A (no `produced_by: ING-07` sections in `docs/requirements/`; TC-12 pins the on-branch OpenAPI shape).
- Coverage → every AC (6) / FR (5) / NFR (3) has ≥1 passing TC; `coverage_audit.uncovered` empty.
- Boot log → clean (0 tracebacks / errors / critical).
- Perf budget → `p95=4613.28ms ≤ 10000ms` (`budget_pass: true`).

**Overall verdict: PASS.** Evidence-pass artefacts already record READY for typecheck/unit_tests/lint/runtime/compile/design_check per `state.json .impl_evidence`; this validation independently reconfirms unit_tests (700 passed) and adds fresh stack-smoke + per-TC execution evidence + task-completion audit + proof-of-run footer.
