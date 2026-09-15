---
feature_id: ING-04
title: MCP server tool exposure (push_activity / push_artifacts)
story_id: ING-04
tracker_story: pratikpawar009/Dashboard#43
tracker_prd: pratikpawar009/Dashboard#304
tracker_research: pratikpawar009/Dashboard#303
plan_owner: impl-planning-agent
date: 2026-09-14
status: Draft
---

# PLAN: ING-04 — MCP server tool exposure (push_activity / push_artifacts)

- Story: `docs/stories/ING-04.md` · PRD: `docs/features/ING-04/REQUIREMENTS.md` · Research: `docs/research/ING-04.md` (GO-WITH-CONDITIONS, 75/100) · Test cases: `docs/test-cases/ING-04.json` (45 TCs, 0 uncovered)
- Product Gate: APPROVE (2026-09-14) — all four research conditions addressed inline in the PRD; state.json `gate: APPROVE`
- Design: N/A — backend / MCP-tool story, no UI surface; NO DESIGN.md
- Feature state: `docs/features/ING-04/state.json`

## Summary

Scaffold `services/mcp-server/` as a separately-deployed sibling Python service (package `agentrise_mcp`) that exposes two MCP tools — `push_activity` and `push_artifacts` — via `fastmcp` v2.x streamable HTTP on `0.0.0.0:3010` path `/mcp`. Each tool reads `.harness/program.yaml` (single-source per D-04), assembles the frozen ingest envelope, and POSTs to the shipped `POST /api/ingest/activity` / `POST /api/ingest/artifacts` endpoints (ADR-0013). Bounded 5 s connect / 30 s total timeout with 3-attempt exponential-backoff-with-jitter retry on network failures only; explicit glob-pattern / JSON-key allowlists guard R-06; strict logging allowlist guards R-07; missing-token fail-fast before any HTTP or filesystem call. The `mcp-tools` contract (`docs/requirements/api.md#mcp-tools`) is filled — unblocking ING-05's Copilot-Chat bridge.

## 1. Architecture Decisions

Technical decisions are recorded in `docs/features/ING-04/DECISIONS.md` (this feature's decision log). D-01 promoted to ADR: `docs/adr/0014-mcp-server-topology.md` (`blast:system` → adr rule fires per `plan-validation` decision-promotion). D-03 tracks ADR-0013 (endpoint URLs, upstream). All other entries (D-02, D-04, D-05, D-06, D-07) are `blast:{feature|service}` + `rev:mechanical` — DECISIONS.md only, `adr:—` per rule.

## 2. File and Module Plan

File plan (`F-01` .. `F-45` → path/action/reason) is maintained in `docs/features/ING-04/tasks.json` `file_plan`. Summary: 43 new files (1 pyproject, 1 service README, 18 source modules under `src/agentrise_mcp/`, 1 conftest, 17 unit tests, 2 integration tests, 1 new ADR under `docs/adr/`, 2 doc edits), 3 doc-file modifications (`docs/adr/README.md`, `docs/requirements/api.md`, `README.md`), 1 config-file modification (`docs/config/stack-smoke.md`). Root `docs/config/project-commands.yaml` is intentionally untouched (D-07).

Every new source module in `file_plan` has its consuming entry-registration site enumerated: `F-05` (server.py) is registered by `F-01` (pyproject.toml `[project.scripts]`) and imported by `F-04` (`__main__.py`); `F-07` and `F-08` (tool implementations) are imported by `F-05` (server.py); every `core/*.py` (F-10..F-15) and `sources/*.py` (F-17..F-20) is imported by `F-07` or `F-08` (or by F-16's dispatcher). No inferential wiring gap.

## 3. Module Hierarchy

```
services/mcp-server/
├── pyproject.toml                                       [F-01, D-01/D-02/D-06 — deps + console script]
├── README.md                                            [F-02, PRD § Documentation requirements]
└── src/agentrise_mcp/
    ├── __init__.py                                      [F-03]
    ├── __main__.py                                      [F-04, FR-1 — `python -m agentrise_mcp` boot]
    │   └── from agentrise_mcp.server import main; main()
    ├── server.py                                        [F-05, FR-1 — FastMCP construction + registration]
    │   - input:  none (bound at import time)
    │   - output: FastMCP server exposing exactly {push_activity, push_artifacts}
    │   - public: main() → server.run(transport="streamable-http", host="0.0.0.0", port=3010, path="/mcp")
    │   ├── @server.tool()(push_activity)                [imports F-07]
    │   └── @server.tool()(push_artifacts)               [imports F-08]
    ├── tools/
    │   ├── __init__.py                                  [F-06 — re-exports for F-05]
    │   ├── push_activity.py                             [F-07, FR-2/FR-5/FR-6/D-03/D-05/D-06]
    │   │   - input:  program_id?, workspace_root?
    │   │   - output: {success, files_read, rows_read, batches, inserted, skipped_duplicate, rejected, rollups, http_status?, error?}
    │   │   - public: async push_activity(program_id, workspace_root) → dict
    │   └── push_artifacts.py                            [F-08, FR-3/FR-5/FR-6/FR-7/FR-8/D-03/D-06]
    │       - input:  program_id?, workspace_root?
    │       - output: {success, rows_received, rows_upserted, rejections, http_status?, error?}
    │       - public: async push_artifacts(program_id, workspace_root) → dict
    ├── core/
    │   ├── __init__.py                                  [F-09]
    │   ├── config.py                                    [F-10, FR-6/D-06 — env-var load]
    │   │   └── load_ingest_token() → str | None; get_ingest_base_url() → str
    │   ├── profile.py                                   [F-11, FR-4/D-04 — workspace + YAML]
    │   │   └── resolve_workspace_root(str | None) → Path; load_program_yaml(Path) → dict  (yaml.safe_load, program.yaml ONLY)
    │   ├── http_client.py                               [F-12, NFR-Performance — 5s/30s timeout]
    │   │   └── make_client() → AsyncClient; async post(client, url, json, token) → Response
    │   ├── retry.py                                     [F-13, NFR-Performance — bounded retry]
    │   │   └── async retry_with_backoff(fn, max_retries=3, jitter=True)   # network failures only, never on 4xx/5xx
    │   ├── allowlist.py                                 [F-14, FR-7/FR-8/R-06]
    │   │   └── validate_glob(pattern, path, workspace_root); validate_json_key(name)
    │   └── logging.py                                   [F-15, NFR-Observability/R-07]
    │       └── get_logger(name); emit(logger, event, **fields)  # per-event allowlist enforced
    └── sources/
        ├── __init__.py                                  [F-16 — dispatcher by kind]
        ├── glob_count.py                                [F-17, FR-3]
        ├── json_key_count.py                            [F-18, FR-3]
        ├── json_field_sum.py                            [F-19, FR-3]
        └── constant.py                                  [F-20, FR-3]

tests/                                                    [F-21..F-40 — see tasks.json]
    conftest.py                                          [F-21 — shared fixtures]
    unit/                                                [17 files, F-22..F-38]
    integration/                                         [2 files, F-39..F-40 — subprocess boot]

docs/
├── adr/0014-mcp-server-topology.md                      [F-41, D-01 promotion, new ADR]
├── adr/README.md                                        [F-42, ADR index update]
└── requirements/api.md #mcp-tools                       [F-43, produced-contract fill — unblocks ING-05]

README.md                                                [F-44, docs T1/T3/T4]
docs/config/stack-smoke.md                               [F-45, config drift C2/C3 — # mcp-server section]
docs/config/project-commands.yaml                        [UNTOUCHED per D-07]
```

Trigger map (headless MCP server — no URL routing): FastMCP transport `POST /mcp` (streamable-HTTP handshake) → `list_tools` returns `{push_activity, push_artifacts}` → each `call_tool` invocation dispatches to `F-07` or `F-08`. Downstream HTTP calls: `POST /api/ingest/activity` (from F-07) and `POST /api/ingest/artifacts` (from F-08), URLs pinned as module constants per D-03 / ADR-0013.

## 4. State and Data Management

State & data design is maintained in `docs/features/ING-04/DATA-DESIGN.md`. The feature is client-only (no database, no schema, no migration); the file records the reads (`.harness/program.yaml`, `<NDJSON files>`), the sensitive material (`AGENTRISE_INGEST_TOKEN`), the batch semantics (500 rows/POST for activity, 1 POST for artifacts), the retry policy (network-only, 3 attempts, exponential backoff + jitter), and the **produced** `mcp-tools` contract bookmark to `docs/requirements/api.md#mcp-tools` (fulfilled by T-11 via F-43). No section is inline-authored here — the shared `mcp-tools` contract is the single reference consuming stories (ING-05) will build against.

## 5. Task Breakdown

Task DAG + live status is maintained in `docs/features/ING-04/tasks.json` `tasks`. Execution order derives from `predecessors`; parallelism derives from the DAG. Twelve tasks total (S=6, M=4, L=2), grouped into 6 waves:

- **Wave 1** (T-01) — Scaffold. Zero predecessors. Unblocks everything.
- **Wave 2** (T-02 ⫽ T-03 ⫽ T-04) — Config, Allowlist, HTTP client. All depend on T-01 only; file-disjoint; parallel-safe.
- **Wave 3** (T-05, T-06) — Logger (depends on T-02 for the token sentinel used by F-37), Profile (depends on T-03 because workspace_root feeds the allowlist's escape check). File-disjoint with each other; parallel-safe.
- **Wave 4** (T-07) — Source resolvers. Depends on T-03 (allowlist) + T-06 (workspace).
- **Wave 5** (T-08 ⫽ T-09) — push_activity (T-02, T-04, T-05, T-06), push_artifacts (T-02, T-04, T-05, T-07). File-disjoint; parallel-safe.
- **Wave 6** (T-10, then T-11 ⫽ T-12) — Server + entry points (depends on T-08 + T-09); Docs and ADR both depend on T-10 (parallel-safe with each other — F-43/F-44/F-45 vs F-41/F-42 are file-disjoint).

**Critical path**: T-01 → {T-02, T-03, T-04} → T-06 → T-07 → T-09 → T-10 → T-11. Six sequential hops through the L-sized T-08 / T-09 chokepoints.

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/ING-04.md` § Risk register. HIGH and MEDIUM risks addressed by ≥1 task in § 5. No accepted (untreated) risks — every carry-forward-to-plan risk has a concrete mitigating task.

### Risks addressed by tasks

| Risk id | Severity | Category | Addressed by |
|---|---|---|---|
| R-01 | LOW | Contract drift (URL) | T-08, T-09 (module-constant URLs pinned to ADR-0013; F-23 / F-26 assert URL string verbatim) |
| R-02 | MED | Pattern coverage (FastMCP) | T-01 (`fastmcp>=2,<3` pinned in F-01), T-10 (F-22 asserts exactly-two-tools registration; F-39 / F-40 assert boot surface via both entry points) |
| R-03 | MED | Ops / Build (scaffolding) | T-01 (F-01 pyproject + F-02 README quickstart), T-11 (F-45 stack-smoke.md `# mcp-server` section per D-07) |
| R-04 | HIGH | Scope / Contract (YAML drift) | RESOLVED at PRD time via D-04 (single-source `.harness/program.yaml`); T-06 hard-codes the path, F-11 has no fallback branch, F-38 asserts the missing-file error envelope |
| R-05 | LOW | Perf (unbounded fan-out) | Not addressed by a task — inherits mitigation from research report (bounded `files[]` in practice; observability logs `batches_sent` for visibility) |
| R-06 | HIGH | Security (glob / JSON injection) | T-03 (allowlist module — F-14; F-34 / F-35 tests exercise every rejection reason), T-09 (F-08 aborts POST on any rejection) |
| R-07 | HIGH | Security (token secret) | T-05 (F-15 logger with per-event allowlist enforcement; F-37 asserts token-substring absence on happy + auth-failure paths for both tools) |
| R-08 | MED | Contract (missing-token envelope shape) | T-08 (F-25 asserts `{success: false, error: "missing_ingest_token", message: "..."}` shape verbatim), T-09 (F-28 same for push_artifacts) |
| R-09 | LOW | Integration (workspace resolution) | T-06 (F-11 + F-38 exercise absolute / relative / omitted / non-existent + symlink cases) |
| R-10 | LOW | Perf (timeout / retry config) | T-04 (F-12 pins `Timeout(connect=5.0, read=30.0, ...)` exactly; F-13 pins `max_retries=3` + network-only retries; F-33 asserts every boundary) |

### Risks accepted (carry-forward)

None. Every HIGH and MEDIUM risk has ≥1 mitigating task in § 5. `state.json .pending_carry_forward` is not appended by this plan.

### Conditions for GO (research_verdict == GO-WITH-CONDITIONS)

| Cond | Condition (verbatim) | Addressed by |
|---|---|---|
| C-1 | Resolve FastMCP library choice (C-01) | D-02 (pinned to jlowin/fastmcp v2.x in DECISIONS.md); T-01 F-01 declares `fastmcp>=2,<3` under `[project].dependencies`; T-10 F-22 / F-39 / F-40 verify the entry-point boot surface |
| C-2 | Decide YAML layout (R-04) | D-04 (single-source `.harness/program.yaml`); T-06 F-11 hard-codes the path with no fallback branch; F-38 asserts missing-file envelope |
| C-3 | Explicit glob / JSON allowlist rules (R-06) | D-04 promoted the rules to first-class FRs (FR-7 / FR-8 in the PRD); T-03 implements F-14 with the FR-7 / FR-8 rejection sets; F-34 / F-35 exercise every rejection reason (TC-25..TC-33) |
| C-4 | Add MCP service to build config | NOT taken (superseded by D-01 — sibling service must NOT be wired into main API preflight); D-07 records the answer at the plan tier — root `docs/config/project-commands.yaml` stays untouched; T-11 F-45 adds a `# mcp-server` section to `docs/config/stack-smoke.md` for boot documentation only |

### Cross-Feature Dependency Notes

- **ING-05 (Copilot-Chat bridge)** — consumes the `mcp-tools` contract this plan fulfils. T-11 (F-43) is the blocking write that replaces the current stub in `docs/requirements/api.md#mcp-tools` with the concrete `server` / `tools` / `env_vars` / `upstream_contracts` shape. Until T-11 completes, ING-05 cannot resolve the produced-contract reference.
- **ING-02 / ING-03 (upstream ingest routes)** — both merged (PR #296, PR #302) and live on `main`. ING-04 is a downstream HTTP client of frozen contracts (`ingest-files-api`, `ingest-artifacts-api`, `ingest-token-auth`); no coordination edits required in `services/api/`.

## 7. Test Strategy

Reference: `docs/test-cases/ING-04.json` — 45 test cases already generated and coverage-audited (`uncovered: []`). Every AC (6), FR (8), NFR (3, minus Accessibility=N/A), and HIGH-severity risk (R-06, R-07) has ≥1 covering TC. No new TCs authored by this plan; PLAN task table references TC IDs, does not restate them.

**Runner setup**: pytest is declared in `services/mcp-server/pyproject.toml` (F-01, T-01). No new runner beyond pytest + pytest-asyncio + respx (all pinned in F-01). `docs/test-cases/ING-04.json` declares NO test cases of type `e2e | performance | contract` — every TC is `type: integration` or `type: unit`. Per `plan-validation` § Runner-setup, no separate runner-install / config task is required.

**Test types**:

| Layer | Count | Covered TCs | Home | Notes |
|---|---|---|---|---|
| Unit — server / tool registration | 1 file (F-22) | TC-01 | `tests/unit/` | FastMCP introspection API asserts exactly-two-tools + no resources + no prompts |
| Unit — push_activity | 3 files (F-23/F-24/F-25) | TC-04..TC-10, TC-20, TC-21, TC-23 | `tests/unit/` | Happy path + auth-failure (mid-run aggregation) + missing-token fail-fast (dedicated per-tool test per FR-6) |
| Unit — push_artifacts | 3 files (F-26/F-27/F-28) | TC-11..TC-16, TC-22, TC-24 | `tests/unit/` | Happy path across all 4 source kinds + auth-failure + missing-token fail-fast |
| Unit — source resolvers | 4 files (F-29..F-32) | (per-resolver behavioural coverage) | `tests/unit/` | glob-count / json-key-count / json-field-sum / constant |
| Unit — HTTP client | 1 file (F-33) | TC-37..TC-41 | `tests/unit/` | 5s/30s timeout + max 3 retries + network-only retry policy |
| Unit — allowlist | 2 files (F-34/F-35) | TC-25..TC-28, TC-29..TC-33 | `tests/unit/` | FR-7 glob rejection matrix + FR-8 JSON-key rejection matrix (R-06 acceptance surface) |
| Unit — config / workspace | 2 files (F-36/F-38) | TC-17..TC-19, TC-34 | `tests/unit/` | Env-var read + workspace_root resolution table |
| Unit — logging | 1 file (F-37) | TC-35, TC-36, TC-42, TC-43, TC-44 | `tests/unit/` | Per-event field allowlist diff (not denylist) + token-substring absence across happy + auth-failure paths (R-07 acceptance surface) |
| Integration — entry points | 2 files (F-39/F-40) | TC-02, TC-03 | `tests/integration/` | subprocess boot of `python -m agentrise_mcp` + console script `agentrise-mcp`; MCP ListTools handshake |
| Manual | — | TC-45 | (not automated) | Live MCP client (Claude Code / MCP Inspector / Cursor) exercises both tools against a stubbed backend; documented in F-02 |

**E2E**: N/A — no UI (see PRD NFR-Accessibility `N/A`). **Performance formal tests**: none — the 30 s per-POST budget is validated via mocked httpx timeouts in F-33; real-network perf is out of scope for a per-developer local tool. **Contract tests**: none — the upstream contracts (`ingest-files-api`, `ingest-artifacts-api`, `ingest-token-auth`) are validated on their producing side (ING-02 / ING-03 test suites); the MCP tool asserts wire-envelope shape via respx mocks in F-23 / F-26.

**Carry-forward** (recorded here for `/arh-implement` awareness — NOT added to `state.json .pending_carry_forward`): TC-34 / TC-35 / TC-36 in `docs/test-cases/ING-04.json` use test tokens rendered as raw strings; before those TCs are pushed to the tracker, they should be wrapped as `<INGEST_TOKEN_TEST_SENTINEL>` symbol references (edit the test-case JSON so the tracker mirror does not accidentally publish a credential-shaped literal). This is a test-case-JSON hygiene edit, not a code or test change.

## Plan validation

Six-dimension check per `plan-validation` skill.

- Date: 2026-09-14T10:30:00Z
- Verdict: PASS
- Wiring:                PASS  (every new module in `file_plan` has its consumer / entry-registration site enumerated: F-05 registered by F-01's `[project.scripts]` + imported by F-04; F-07 / F-08 imported by F-05; every `core/*.py` and `sources/*.py` imported by F-07 / F-08 / F-16)
- Docs:                  PASS  (T1 new runnable surface → T-11 F-44 root README updated with mcp-server layout + getting-started; T2 mcp-tools produced-contract → T-11 F-43 fills `docs/requirements/api.md#mcp-tools`; T3 new env var `AGENTRISE_INGEST_TOKEN` → T-11 F-44 root README env-var table row; T4 new service `services/mcp-server/` + new port 3010 → T-11 F-44 root README Prerequisites + F-45 stack-smoke.md `# mcp-server` section)
- Runner-setup:          PASS  (no TCs of type e2e / performance / contract in `docs/test-cases/ING-04.json`; pytest + pytest-asyncio + respx pinned in F-01 T-01 — the only runners needed)
- Cross-section:         PASS  (DAG acyclic: T-01 has no predecessors; T-02..T-04 depend on T-01; T-05 on T-01+T-02; T-06 on T-01+T-03; T-07 on T-03+T-06; T-08 on T-02+T-04+T-05+T-06; T-09 on T-02+T-04+T-05+T-07; T-10 on T-08+T-09; T-11 on T-10; T-12 on T-10 — DFS walk terminates. Every F-01..F-45 covered by ≥1 task's files[]; every task's files[] resolves to a valid F-NN. No two DAG-independent tasks share a file — each F-NN appears in exactly one task's files[])
- Config drift:          PASS  (C1 new runtime deps `fastmcp / httpx / pyyaml` live only in F-01 `services/mcp-server/pyproject.toml` — sibling service per D-01; main `services/api/pyproject.toml` unchanged; C2 new service `services/mcp-server/` → T-11 F-45 adds `# mcp-server` section to `docs/config/stack-smoke.md` with Run/Env/Check bullets; C3 new port 3010 → documented in the same F-45 section. Root `docs/config/project-commands.yaml` intentionally untouched per D-07 — the sibling service is NOT wired into main API preflight per D-01)
- Decision-promotion:    PASS  (D-01 `blast:system` + `rev:medium` → `adr:ADR-0014` (T-12 F-41 + F-42 index update); D-03 tracks upstream `adr:ADR-0013` — no new promotion needed; D-02, D-04, D-05, D-06, D-07 all `blast:{feature|service}` + `rev:mechanical` → `adr:—` per `decide` skill rule)
- Rounds:                1

### Plan validation rounds

| Round | Timestamp | Verdict | Failing dimensions | Notes |
|---|---|---|---|---|
| 1 | 2026-09-14T10:30:00Z | PASS | — | All 6 dimensions clean on first pass; no revision required. |
