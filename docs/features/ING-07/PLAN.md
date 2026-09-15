# ING-07 — Implementation Plan

**Story**: ING-07 — Admin GitHub repo-scan endpoint
**Tracker**: [pratikpawar009/Dashboard#46](https://github.com/pratikpawar009/Dashboard/issues/46) · PRD subtask [#331](https://github.com/pratikpawar009/Dashboard/issues/331)
**Design**: N/A — backend-only (state `design=n/a`).
**Branch**: `feature/ING-07` (per repo branch convention).

A new admin FastAPI router mounts `POST /api/admin/scan-repos` at
`services/api/app/api/admin.py`. It authenticates with an `ingest-token-auth`
bearer, enforces wildcard-strict scope in the router itself (D-05), delegates to
a new `services/api/app/services/repo_scan.py` that pages the configured GitHub
org and probes each repo for `.harness/program.yaml` on the default branch
(200 = installed, 404 = not; no YAML parse), and atomically upserts
`org_summary_rollup.{repos_total, repos_with_harness_installed, as_of_timestamp}`
per request. Response body `ScanReposResponse` is pinned by PRD D-01 (assumed
against a contract that specifies only the update effect).

## 1. Architecture Decisions

Technical decisions are recorded in [DECISIONS.md](DECISIONS.md) (this feature's
decision log). Six entries (D-01..D-06); none promoted to a full ADR — every
decision is `blast:feature`/`service` + `rev:mechanical`/`medium` per the
`decide` promotion rule, so no `docs/adr/` entry is added by this story.

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in
[tasks.json](tasks.json) `file_plan`.

## 3. Module Hierarchy

```
services/api/app/
├── api/
│   └── admin.py                     (F-01, new)
│       - input:   POST /api/admin/scan-repos
│                   headers: Authorization: Bearer <ingest-token>
│                   body:    (none)
│       - output:  200 ScanReposResponse
│                | 401 (missing / unknown / revoked / expired) — via get_ingest_token()
│                | 403 (scope — router-level wildcard-strict re-check)
│                | 500 {"detail": "missing configuration: GITHUB_TOKEN|GITHUB_ORG"}
│                | 502 (GitHub retry exhaustion / ReadTimeout — no rollup commit)
│       - public: scan_repos(request, session=Depends(get_db), ...)
│
├── services/
│   └── repo_scan.py                 (F-02, new)
│       - input:   session: AsyncSession, github_org: str, github_token: str
│       - output:  ScanReposResponse — three fields; see DECISIONS.md § D-07
│                  (`ScanReposResult` sentinel type dropped; `github_api_calls`
│                  and `duration_ms` propagate on the `admin_scan_completed`
│                  structured log record only, asserted by TC-18)
│                  raises GitHubScanError on retry exhaustion / timeout
│       - public: async def scan_org_repos(...) -> ScanReposResponse
│       - private: _list_org_repos(client, org)  — paginated 100/page
│                   _probe_program_yaml(client, org, repo, ref)  — 200/404
│                   _upsert_org_rollup(session, counts, now_utc)  — INSERT ... ON CONFLICT
│                   GitHubScanError  (typed sentinel for router → 502 mapping)
│
└── schemas/
    └── repo_scan.py                 (F-03, new)
        - public: class ScanReposResponse(BaseModel):
                    repos_total: int
                    repos_with_harness_installed: int
                    as_of_timestamp: datetime
```

### Wiring (entry-registration sites)

- `admin_router` (F-01) → mounted in `app/main.py::create_app()` (F-04, modify).
- `perform_scan()` (F-02) → consumed by `admin.py` (F-01).
- `ScanReposResponse` (F-03) → consumed by `admin.py` (F-01) and referenced by
  the OpenAPI schema (TC-12 asserts export).
- `Settings.github_org` / `Settings.github_token` (F-05, modify) → read by
  `admin.py` via `request.app.state.settings` per the existing `create_app(cfg)` seam.
- Meta planning artifacts (this PLAN.md, DECISIONS.md, DATA-DESIGN.md,
  tasks.json, per-feature and index state files) are written by this planning
  phase itself — deliberately NOT in `file_plan`, which enumerates
  implementation-phase files consumed by `/arh-implement`.

### Navigation / routing map

_N/A — backend-only endpoint, no frontend route._ One new HTTP route:
`POST /api/admin/scan-repos → app/api/admin.py::scan_repos` (server handler).

## 4. State and Data Management

State & data design is maintained in [DATA-DESIGN.md](DATA-DESIGN.md).

## 5. Task Breakdown

Task DAG + live status is maintained in [tasks.json](tasks.json) `tasks`.
Execution order derives from `predecessors`; parallelism derives from the DAG.

DAG shape (for reviewer navigation):

```
T-01 (config)   → T-03, T-06, T-09
T-02 (schema)   → T-03, T-04
T-03 (service)  → T-04
T-04 (router)   → T-05
T-05 (wiring)   → T-07, T-08, T-10
T-06 (fixtures) → T-07, T-08
```

Complexity split: **S=5** (T-01, T-02, T-05, T-09, T-10) · **M=4** (T-03, T-04,
T-06, T-08) · **L=1** (T-07). Total 10 tasks.

## 6. Carry-Forward Risks and Conditions

### Conditions for GO (research_verdict GO-WITH-CONDITIONS)

All three research conditions were closed at REQUIREMENTS.md time
(§ Addressing Research Conditions):

- **C-1 — Harness-installed signal**: RESOLVED 2026-09-15 at story level =
  presence of `.harness/program.yaml` on default branch, probed via
  `GET /contents` (200/404). Cited in this plan's Solution Sketch above and
  enforced by T-03 (`_probe_program_yaml`).
- **C-2 — Response shape**: PRD FR-1 pins `ScanReposResponse` per D-01 above;
  TC-12 asserts. Contract-extension follow-up carried below.
- **C-3 — Concurrent-write race**: PRD D-02 accepted last-write-wins; D-02
  in this plan carries it verbatim; TC-20 asserts endpoint completes 200 under
  a concurrent rebuild.

### Risks carried from research (with owners)

Every HIGH/MEDIUM row in `docs/research/ING-07.md` § Risk register is either
owned by a T-NN or explicitly accepted:

| # | Risk (source: research §Risk register) | Sev | Owner |
|---|---|---|---|
| R-1 | Harness-installed signal ambiguity | HIGH | RESOLVED 2026-09-15 (story-level, C-1); no live owner |
| R-2 | No GitHub REST client exists — new external-dep surface | HIGH | T-03 (dedicated wrapper per D-03; retry via existing `retry.py` per D-04) |
| R-3 | Concurrent-write race BED-03 ↔ ING-07 on `org_summary_rollup` | HIGH | Accepted per D-02; TC-20 asserts no deadlock; T-03 comment cites D-02 at upsert site |
| R-4 | 429 log leakage (PAT / raw body) | MED | T-03 field-allowlist logging; TC-17 asserts sentinel never appears in structlog / caplog / response body |
| R-5 | Response shape assumption without a contract row | MED | D-01; T-02 pins DTO; TC-12 asserts runtime body + OpenAPI export; contract-extension follow-up below |
| R-6 | GITHUB_ORG / GITHUB_TOKEN operational setup undocumented | MED | T-01 (settings), T-09 (root README env table), T-10 (services/api/README `## Admin scan`) |
| R-7 | Tight p95 ≤10s budget with no jitter buffer | MED | T-08 (TC-16 measures p95 over N=30 with 20 ms mocked latency) |
| R-8 | Mid-scan default-branch flip could misclassify | LOW | Accepted operational limitation (scan runs once per request; intermediate default-branch changes are NOT re-checked). T-03 reads `default_branch` from the list-repos response and passes it through to the probe without re-fetching. |

### Non-blocking follow-ups (do NOT block implementation)

- **F-U1 — Contract extension**: propose adding a response-body schema to
  `docs/requirements/api.md#admin-scan-api`'s `shape:` block, matching
  `ScanReposResponse` (D-01). This plan deliberately does NOT edit that
  contract file (surgical-changes + do-not-drift-contracts rule). Follow-up
  story or an RTM decisions entry, not this feature.
- **F-U2 — `Retry-After` respect on 429**: `retry_with_backoff` currently
  uses jittered exponential only. If observability shows 429s hitting the
  10 s budget in practice, extend `retry.py` OR add a per-caller wrapper
  (`rev:mechanical` — D-04).
- **F-U3 — Concurrent probes via `asyncio.gather`**: v1 iterates probes
  sequentially. If TC-16 p95 slips at 200 repos in real (not mocked) latency,
  bounded concurrency is a `rev:mechanical` follow-up (D-04).

### Cross-Feature Dependency Notes

- ING-05 and ING-06 are WONTFIX (retired 2026-09-15, PR #329). This plan does
  NOT reference `ingest-files-api` or `rollup-rebuild-api`, and does NOT touch
  `services/mcp-server/**` or `.github/hooks/**` (frozen contracts).
- `admin-scan-api` `consumed_by: []` (docs/requirements/api.md line 545) — no
  downstream story reads this endpoint, so response-shape churn is contained.

## 7. Test Strategy

Source of truth: [`docs/test-cases/ING-07.json`](../../test-cases/ING-07.json)
— 20 cases, 15 pushed to tracker on TC-01..TC-15. Layer split:

| Layer | Cases | Task | Runner setup |
|---|---|---|---|
| **integration** | TC-01, TC-02, TC-03 (classification); TC-04, TC-05 (401); TC-06 (403); TC-07, TC-08 (500 config); TC-09, TC-10, TC-11 (502 external failure); TC-13 (403 wildcard-strict); TC-14 (429-retry); TC-15 (mid-scan atomicity); TC-18 (observability event); TC-19 (idempotency); TC-20 (concurrent rebuild) | T-07 | Existing — `pytest` + `pytest-asyncio` + `respx` are already declared in `services/api/pyproject.toml [dependency-groups].dev`; `build_app` / `async_client_for` / `migrated_db` fixtures already ship in `tests/conftest.py`. No install task. |
| **contract** | TC-12 (`ScanReposResponse` shape + OpenAPI export) | T-07 | Same as integration — FastAPI's built-in `/openapi.json` handler is the "contract runner"; no new tool. |
| **security** | TC-13 (authz enforcement location — dual-tagged); TC-17 (sentinel-PAT never logged / never in response body / never in exception message) | T-07 | Same as integration — `structlog_capture` + `caplog` fixtures. See note below on TC-17. |
| **performance** | TC-16 (p95 ≤ 10 000 ms over N=30 at 20 ms mocked latency, 200-repo org) | T-08 | Existing — `perf` marker declared in `services/api/pyproject.toml [tool.pytest.ini_options]`; opt-in via `-m perf`. No install task. |
| **unit** | (none — every case is integration+ per test-cases JSON) | — | — |
| **e2e** | (none — backend-only story) | — | — |

**Note on TC-17 (sentinel PAT test)**: this test IS included in the test suite
and runs in CI under the standard pytest invocation. It is flagged by the
tracker-push scanner as containing what looks like a credential
(`ghp_SENTINEL_DO_NOT_LOG_ABC123`) and is deliberately DROPPED from the
tracker sync — that scanner behaviour is expected and no code change is needed
in this feature. The sentinel is a synthetic string, never a real PAT.

**Runner-setup (plan-validation dimension)**: no new runner install task is
declared because all runners required by the declared TC types are already
installed and configured in the shipped repo (see the "Runner setup" column
above). Adding empty install tasks would violate surgical-changes.

**Fixtures** (added under T-06 in `tests/conftest.py`) mirror the
`fixtures[]` arrays in `docs/test-cases/ING-07.json` verbatim, so a reviewer
can trace each fixture reference in the JSON to a real fixture in
`conftest.py`.

## Plan validation

- Date: 2026-09-15T07:20:00Z
- Verdict: PASS
- Wiring:                PASS  (F-01 registered via F-04 modify; F-02/F-03 consumed by F-01; F-05 config consumed by F-01 via `app.state.settings`; F-06 consumed at process start; F-10/F-11/F-12 are leaf test files.)
- Docs:                  PASS  (T3 env var → T-09 modifies root README env-var table AND T-01 modifies `.env.example` via F-06; T2 new HTTP route → T-10 modifies `services/api/README.md` `## Admin scan` sub-section, the shipped primary API doc — root README carries no route table today. T1/T4 do not fire — no new project root, no new service dir, no new port, no new docker-compose service.)
- Runner-setup:          PASS  (contract TC-12 + performance TC-16 both use the already-declared pytest + pytest-asyncio + respx + `perf` marker in `services/api/pyproject.toml` — no new runner install required. Explicit note in §7.)
- Cross-section:         PASS  (DAG acyclic — root {T-01, T-02, T-06}; longest path T-01 → T-03 → T-04 → T-05 → T-07 (5 nodes). Every `file_plan` F-NN appears in ≥1 task's `files[]`. Every task's `files[]` id exists in `file_plan`. Every declared TC layer (integration/contract/security/performance) has a matched task. Parallel-safety: T-07 and T-08 are DAG-independent but write disjoint files (F-10 vs F-11); T-09 and T-10 disjoint (F-07 vs F-08); no other unordered write pair.)
- Config drift:          PASS  (C1 no new runtime dep — `httpx>=0.27` already in `services/api/pyproject.toml [project].dependencies`; C2 no new service dir / no new docker-compose service; C3 `GITHUB_ORG` / `GITHUB_TOKEN` are neither `*_PORT` nor `*_HOST` nor `*_URL` — no port/host trigger; env vars themselves flow through Docs T3 handled above.)
- Decision-promotion:    PASS  (D-01..D-06 all carry `blast:feature`/`service` + `rev:mechanical`/`medium`; per `decide` promotion rule (§ *When a decision must be promoted to a full ADR*) none qualify. `adr:—` on every entry is correct. No ADR added.)
- Rounds:                1
