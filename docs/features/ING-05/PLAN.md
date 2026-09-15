---
feature_id: ING-05
title: Copilot Chat activity-hook bridge
story_id: ING-05
tracker_story: pratikpawar009/Dashboard#44
tracker_prd: pratikpawar009/Dashboard#323
tracker_research: pratikpawar009/Dashboard#322
plan_owner: impl-planning-agent
date: 2026-09-15
status: Draft
---

# PLAN: ING-05 — Copilot Chat activity-hook bridge

- Story: `docs/stories/ING-05.md` · PRD: `docs/features/ING-05/REQUIREMENTS.md` · Research: `docs/research/ING-05.md` (GO-WITH-CONDITIONS, 66/100) · Test cases: `docs/test-cases/ING-05.json` (3 TCs, deliberate small-batch cap; 7 uncovered ids per D-04 exercised via inline fixture assertions + manual E2E)
- Product Gate: APPROVE (2026-09-15) — all 7 research conditions addressed in the PRD; all 5 implementation directives promoted from resolved clarifications; state.json `gate: APPROVE`
- Design: N/A — background Node hook, no UI surface; NO DESIGN.md (`design == "n/a"` in `docs/features/ING-05/state.json`)
- Feature state: `docs/features/ING-05/state.json`

## Summary

Turn the shipped-but-drifted `.github/hooks/copilot-activity.mjs` + `.github/hooks/harness-mcp-push.mjs` pair from producing 141× `missing_required_field` rejections (ING-04 live E2E, PR #323) into a working Copilot Chat → `usage_events` bridge. Three concrete edits close the gap: (a) every emitted row carries a non-empty `program_id` resolved via `HARNESS_PROGRAM_ID` env → `.harness/program.yaml → program_id` (legacy `programId`) → skip-on-unresolved (ADR-0015); (b) a pinned `JOURNAL_CODEC_VERSION = "1"` treats unknown journal kinds as skip-and-log-once, never batch-abort; (c) the MCP push tightens to a single 10 s `AbortController` budget with no retry — retry logic is FORBIDDEN because a retry loop would extend the detached child's wall-clock past the Copilot Chat `Stop` event window and violate AC-2's fire-and-forget contract. Feature-parse tightens to bare-token positional only (`^/\S+\s+([A-Z]{2,4}-\d+)\b`); cache tokens emit as literal `0` matching the frozen `ActivityRowIn` schema; `.mcp-push.log` bounds at 100 lines / 32 KB with a truncate-and-rewrite rotator. Two `node:test` files cover the 3 automated TCs plus the 7 uncovered ids as inline fixture assertions per D-04; `docs/how-to/copilot-chat-setup.md` documents the manual E2E walkthrough that closes AC-5 and research condition C-7.

## 1. Architecture Decisions

Technical decisions are recorded in `docs/features/ING-05/DECISIONS.md` (this feature's decision log). D-03 promoted to ADR: `docs/adr/0015-program-id-sourcing-precedence.md` (`blast:data` → adr rule fires per `plan-validation` decision-promotion — the row's PK component `(program_id, session_id, cmd_ts)` reaches durable state via `usage_events`' unique constraint; a wrong precedence corrupts every downstream aggregation). D-01 (JOURNAL_CODEC_VERSION pin), D-02 (single-attempt no-retry MCP push), D-04 (3-TC cap, gap accepted) all carry `blast:{feature|service}` + `rev:mechanical` — DECISIONS.md only, `adr:—` per the promotion rule (they bind inside one file / one script and reversing is a one-line edit).

## 2. File and Module Plan

File plan (`F-01` .. `F-10` → path/action/reason) is maintained in `docs/features/ING-05/tasks.json` `file_plan`. Summary: 2 modifications to existing hook scripts (`copilot-activity.mjs`, `harness-mcp-push.mjs`), 5 new files under `.github/hooks/__tests__/` (2 test files + 3 fixture files), 1 new how-to under `docs/how-to/`, 1 new ADR under `docs/adr/`, 1 doc-index edit (`docs/adr/README.md`). Zero touches to `services/api/**` (schema frozen per PRD § Constraints), zero touches to `services/mcp-server/**` (tool contract frozen per ING-04). Zero touches to dashboard UI code.

Every new file in `file_plan` is a leaf (test / fixture / ADR / how-to / index row append) — none of the new files is a runtime module that needs an entry-registration site. The two modifications (F-01, F-02) are the entry surfaces themselves; the external caller is VS Code Copilot Chat's `sessionEnd` hook config, which lives outside the repo per PRD § Rollout plan (opt-in by installation). No inferential wiring gap.

## 3. Module Hierarchy

Two hook scripts, no shared library. Trigger map (there is no URL routing — this is a Node-hook feature):

```
VS Code Copilot Chat sessionEnd
  → .github/hooks/copilot-activity.mjs                    [F-01, entry point]
      · resolves workspace hash (workspaceStorage/*/workspace.json longest match)
      · replays chatSessions/<uuid>.jsonl (kinds 0/1/2 known; else skip+log-once)
      · reads transcripts/<uuid>.jsonl (event chain)
      · resolves program_id (env → .harness/program.yaml → skip)   [ADR-0015]
      · assembles row per ActivityRowIn schema (cache_read=0, cache_write=0, feature via bare-token regex)
      · append-or-upsert on (session_id, cmd_ts) → docs/activity/activity.jsonl
      · spawn(process.execPath, [pushScript], {detached:true, stdio:'ignore'}).unref()
          → .github/hooks/harness-mcp-push.mjs             [F-02, detached child]
              · IPv4-loopback enforce (refuse non-loopback HARNESS_MCP_URL)
              · single-attempt AbortController(TIMEOUT_MS=10_000) per RPC
              · MCP JSON-RPC: initialize → notifications/initialized → tools/call push_activity → DELETE
                  → services/mcp-server (ING-04, frozen contract)
                      → POST /api/ingest/activity → usage_events (backend)
              · writeLog(event, extra) with field allowlist + 100-line / 32 KB rotator → docs/activity/.mcp-push.log
              · process.exit(0) on every outcome
```

Test tree (leaf-only; no wiring — `node:test` auto-discovers via `node --test`):

```
.github/hooks/__tests__/
├── copilot-activity.test.mjs                             [F-03, consumes F-01 + fixtures F-05/F-06/F-07]
├── harness-mcp-push.test.mjs                             [F-04, consumes F-02]
└── fixtures/
    ├── chat-session.jsonl                                [F-05, kinds 0/1/2 + unknown-kind 99]
    ├── transcript.jsonl                                  [F-06, canonical `/plan BED-01` slash-command]
    └── program.yaml                                      [F-07, program_id key; legacy programId variant materialised inline in test]
```

## 4. State and Data Management

State & data design is maintained in `docs/features/ING-05/DATA-DESIGN.md`. Highlights: no relational schema owned (destination `usage_events` is frozen upstream by ING-02; PK `(program_id, session_id, cmd_ts)`); `activity.jsonl` is NDJSON append-or-upsert on `(session_id, cmd_ts)`; `.mcp-push.log` is bounded (100 lines AND 32 KB) with in-process rotator; delivery guarantee for the MCP push is **at-most-once** by design (D-02 forbids retry — at-least-once semantics live one hop upstream inside `services/mcp-server/`); consumed contract is `mcp-tools → push_activity` bookmarked at `docs/requirements/api.md#mcp-tools` (produced by ING-04, no local re-statement).

## 5. Task Breakdown

Task DAG + live status is maintained in `docs/features/ING-05/tasks.json` `tasks`. Execution order derives from `predecessors`; parallelism derives from the DAG. Eight tasks total (S=3, M=5, L=0), grouped into 4 waves:

- **Wave 1** (T-01 ⫽ T-02 ⫽ T-03 ⫽ T-06) — Modify `copilot-activity.mjs`, modify `harness-mcp-push.mjs`, create test fixtures, write ADR-0015 + index. All four have empty predecessors; file-disjoint (F-01 / F-02 / F-05+F-06+F-07 / F-09+F-10); parallel-safe.
- **Wave 2** (T-04 ⫽ T-05 ⫽ T-07) — Author `copilot-activity.test.mjs` (needs T-01 + T-03), author `harness-mcp-push.test.mjs` (needs T-02 + T-03), write `copilot-chat-setup.md` (needs T-01 + T-02 so documented behaviour matches shipped code). File-disjoint (F-03 / F-04 / F-08); parallel-safe.
- **Wave 3** (T-08) — Execute the manual E2E walkthrough documented by T-07 and record evidence. Depends on T-04, T-05, T-07 (needs the automated tests green AND the walkthrough authored).

**Critical path**: T-01 → T-04 → T-08 (or T-02 → T-05 → T-08). Two sequential hops through the M-sized code+test chain plus one S-sized manual verification.

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/ING-05.md` § Risk register. All 3 HIGH-severity risks addressed by ≥1 task in § 5. No accepted (untreated) HIGH/CRITICAL risks — every carry-forward-to-plan HIGH has a concrete mitigating task. MED/LOW risks inherit their mitigation from the research doc.

### Risks addressed by tasks

| Risk id | Severity | Category | Addressed by |
|---|---|---|---|
| R-01 | HIGH | Integration (Copilot journal schema drift) | T-01 (F-01 adds `JOURNAL_CODEC_VERSION = "1"` + unknown-kind skip-and-log-once per D-01), T-07 (F-08 § Troubleshooting documents the `journal_codec_unknown_kind` event, cause, fix) |
| R-02 | HIGH | Integration (MCP server availability) | T-02 (F-02 writes bounded `.mcp-push.log` on every outcome per D-04 rotator), T-05 (F-04 tests all three failure modes), T-07 (F-08 § Troubleshooting documents the four failure events + reading `.mcp-push.log`), T-08 (manual E2E verifies the pipeline lands rows when MCP server is up) |
| R-03 | HIGH | Domain (row-level program_id alignment) | T-01 (F-01 implements the ADR-0015 precedence + skip-on-unresolved), T-04 (F-03 test suite exercises all three resolution paths per TC-01), T-06 (F-09 promotes D-03 to ADR-0015 so future producers of `activity.jsonl` bind the same order) |
| R-04 | MED | Compatibility (journal codec fragility) | T-01 (F-01 pins `JOURNAL_CODEC_VERSION` constant + PRD-mandated header-comment schema shape 'as of 2026-09-15'), T-03 (F-05 fixture covers kinds 0/1/2 + unknown), T-04 (F-03 test asserts unknown-kind logged once, batch not aborted) |
| R-05 | MED | Performance (lines_added heuristic) | Not addressed by a task — inherits research-doc mitigation (heuristic accepted; `.mcp-push.log` records outcomes for observability; matches shipped `harness-activity.mjs` behaviour). Called out in T-07 F-08 § Troubleshooting as a documented limitation |
| R-06 | MED | Dependency (Copilot Chat installed) | Not addressed by a task — inherits research-doc mitigation (documented as scope in PRD § Rollout plan; T-07 F-08 § Prerequisites states VS Code + Copilot Chat as install-time requirements) |
| R-07 | LOW | Compatibility (workspace hash resolution) | T-07 (F-08 § Troubleshooting documents the longest-path-match heuristic + `workspaceFolder` env-var override) |
| R-08 | LOW | Security (hook process injection) | Not addressed by a task — inherits research-doc mitigation (out of scope; PR review + branch protection). T-02 F-02 defence-in-depth: no bearer read in the hook, IPv4-loopback enforce refuses non-loopback URLs, log-field allowlist prevents credential leak |

### Risks accepted (carry-forward)

None. Every HIGH-severity risk has ≥1 mitigating task in § 5. `state.json .pending_carry_forward` is not appended by this plan.

### Conditions for GO (research_verdict == GO-WITH-CONDITIONS)

| Cond | Condition (verbatim from `docs/research/ING-05.md` § Verdict → Conditions) | Addressed by |
|---|---|---|
| C-1 | Add row-level `program_id` to every emitted activity row in `copilot-activity.mjs` (sourced from `HARNESS_PROGRAM_ID` env → `.harness/program.yaml → programId`). This is the root cause of the ING-04 live-E2E 141× `missing_required_field` rejection; PLAN must include this write + a fixture test. | T-01 (F-01 implements the ADR-0015 precedence with legacy-key fallback), T-04 (F-03 test suite covers env-wins / yaml-fallback / unresolved-skips per TC-01), T-06 (F-09 promotes to ADR-0015) |
| C-2 | Add unit test coverage for `copilot-activity.mjs` (journal parsing, line-count heuristics, upsert-key logic) with fixtures covering all three journal kinds. | T-03 (F-05 chat-session fixture covers kinds 0/1/2 + unknown), T-04 (F-03 exercises row assembly, upsert, unknown-kind handling) |
| C-3 | Add unit test coverage for `harness-mcp-push.mjs` (JSON-RPC handshake, timeout handling, log file writes) with mocked fetch. | T-05 (F-04 stubs global fetch; TC-02 timeout, TC-03 three failure modes, RPC sequence-order sub-test, log-field allowlist sub-test) |
| C-4 | Clarify timeout NFR: is 5s connect / 10s total per-call binding, or is 15s wall-clock acceptable? Update hook or story decision log accordingly. | D-02 in DECISIONS.md pins `TIMEOUT_MS = 10_000` single-attempt no-retry; T-02 (F-02 sets the constant); T-05 (F-04 asserts abort by 10.5 s ceiling per TC-02) |
| C-5 | Document VS Code Copilot Chat setup (extension install, MCP server config, MCP_URL env var, troubleshooting). | T-07 (F-08 docs/how-to/copilot-chat-setup.md with the six PRD-mandated sections: Prerequisites / Wire the hook / Environment variables / Verify / Troubleshooting / Manual E2E walkthrough) |
| C-6 | Add `.mcp-push.log` rotation / retention policy (e.g., keep last 100 lines, rotate weekly). | ING-05-NFR-observability pins 100 lines AND 32 KB with in-process rotator; T-02 (F-02 `writeLog` helper does read-truncate-rewrite at write time); T-05 (F-04 pre-fills log to cap and asserts final size/line count) |
| C-7 | Run E2E validation: real Copilot Chat session end → verify `activity.jsonl` is updated → verify `.mcp-push.log` records push outcome → verify backend ingest (via dashboard or API query). | T-07 (F-08 § Manual E2E walkthrough documents the 5-step verification), T-08 (executes the walkthrough and pastes evidence into the tracker task comment). CI is `none` per `CLAUDE.md` — automation is not possible for the Copilot Chat lifecycle event. |

### Cross-Feature Dependency Notes

- **ING-04 (MCP server tool exposure)** — merged (PR #323, commit `7e2b8c6`), live on `main`. ING-05 is a pure client of the frozen `mcp-tools → push_activity` contract. The 141× `missing_required_field` regression observed during ING-04's live E2E is the concrete root cause fixed by T-01 (F-01) + T-06 (F-09 / ADR-0015). No coordination edits required in `services/mcp-server/`.
- **ING-02 (backend ingest)** — merged. `ActivityRowIn` schema in `services/api/app/schemas/ingest_files.py` is frozen; ING-05 aligns row emission to it. No coordination edits required in `services/api/`.
- **Future Claude Code / Codespaces / non-VS-Code bridges** — will consume ADR-0015 as the source-of-truth precedence for row-level `program_id`. No inline coupling introduced by this plan.

## 7. Test Strategy

Reference: `docs/test-cases/ING-05.json` — 3 automated test cases already generated, tracker keys #324 / #325 / #326. Coverage audit records 7 uncovered ids (`AC-1, AC-3, AC-4, FR-2, FR-3, FR-4, NFR-security`) as a **deliberate 3-TC cap** approved at the Product Gate (D-04); these are exercised via inline fixture assertions inside the two `node:test` files PLUS the manual E2E walkthrough per AC-5 Manual and research condition C-7. `NFR-accessibility` is N/A (background Node hook, no UI surface).

**Runner setup**: none required. All tests use Node's built-in `node:test` runner (Node 20+, no install, no config file — invoked as `node --test .github/hooks/__tests__/`), matching the runtime the hooks themselves already assume per PRD § Scope. `docs/test-cases/ING-05.json` declares NO test cases of type `e2e | performance | contract` — every automated TC is `type: unit`. Per `plan-validation` § Runner-setup, no separate runner-install / config task is required. The existing `apps/web/vitest.config.ts` (Next.js frontend, jsdom environment) is **not** reused — hooks are Node-hook scripts, not React components.

**Test types**:

| Layer | Count | Covered TCs | Home | Notes |
|---|---|---|---|---|
| Unit — `copilot-activity.mjs` | 1 file (F-03) | ING-05-TC-01 (tracker #324) + inline sub-tests for AC-1 / AC-2 / FR-2 / FR-3 / FR-4 | `.github/hooks/__tests__/` | Table-driven parametrised sub-tests use fixtures F-05 / F-06 / F-07; env / FS state restored in `after` hooks; a `tmp_path` sandbox per test via `mkdtempSync`. |
| Unit — `harness-mcp-push.mjs` | 1 file (F-04) | ING-05-TC-02 (tracker #325), ING-05-TC-03 (tracker #326) + inline sub-tests for AC-3 (RPC sequence) / AC-4 (default URL) / NFR-security (allowlist diff) / NFR-observability (100-line / 32 KB rotator) | `.github/hooks/__tests__/` | Global fetch stubbed per test; `process.exit` stubbed to capture code without terminating; log-file path substituted via env override. |
| Integration | 0 | — | — | Not warranted — hooks are two-file leaf scripts with no shared runtime module; unit-tier stubs give full coverage. |
| E2E (automated) | 0 | — | — | Not possible — Copilot Chat lifecycle events cannot be simulated by CI (CI: none per `CLAUDE.md`). The manual E2E in T-08 is the substitute. |
| Manual | 1 walkthrough | AC-5 Manual + 7 uncovered ids per D-04 | `docs/how-to/copilot-chat-setup.md § Manual E2E walkthrough` | Documented by T-07 F-08; executed by T-08. Records: activity.jsonl row snippet, .mcp-push.log line, dashboard row or SQL result, p95 timing log for 20 sequential session-ends. |
| Performance formal tests | 0 | — | — | The 10 s per-RPC ceiling is asserted via fetch-stub in F-04 (TC-02); the 2 s p95 hook return budget is verified in T-08 (manual E2E timing log). |

**Test-case JSON hygiene** (recorded for `/arh-implement` awareness — NOT added to `state.json .pending_carry_forward`): `docs/test-cases/ING-05.json` uses two `<PLACEHOLDER>` sentinels (`test_data.harness_mcp_url_env` in TC-02, `test_data.harness_ingest_token_env` in TC-03). Before those TCs are pushed to the tracker (Phase 2 of `/arh-plan-implementation`), verify the placeholders are either filled with a symbolic test-sentinel token like `<INGEST_TOKEN_TEST_SENTINEL>` or removed. This is a test-case-JSON edit, not a code or test change.

## Plan validation

Six-dimension check per `plan-validation` skill.

- Date: 2026-09-15T04:00:00Z
- Verdict: PASS
- Wiring:                PASS  (every file in `file_plan` is a leaf: F-01 / F-02 are the entry points themselves — external caller is VS Code Copilot Chat `sessionEnd` config, not repo code; F-03 / F-04 are `node:test` files auto-discovered by `node --test`; F-05 / F-06 / F-07 are fixtures consumed by F-03; F-08 is a how-to doc; F-09 is an ADR; F-10 is a doc-index-row append. No new runtime module needs a consuming import site.)
- Docs:                  PASS  (T1 no fresh top-level project root or new server entry — hooks already exist and are being modified; T2 no new HTTP route — feature consumes the frozen `mcp-tools` contract; T3 `HARNESS_PROGRAM_ID` and `HARNESS_MCP_URL` are pre-existing env vars in the shipped hook draft, not new — but their resolution semantics are newly documented in T-07 F-08 `docs/how-to/copilot-chat-setup.md § Environment variables` per PRD § Documentation requirements (no `.env.example` exists for hooks; PRD explicitly directs docs to `docs/how-to/`, not root README); T4 no new service dir, no docker-compose change, no new port bind — feature dials into ING-04's already-live `services/mcp-server/` on the already-existing port 3010.)
- Runner-setup:          PASS  (no TCs of type `e2e | performance | contract` in `docs/test-cases/ING-05.json` — all three TCs are `type: unit`; Node's built-in `node:test` is bundled with Node 20+ and requires zero install, zero config file, invoked via `node --test .github/hooks/__tests__/`; the existing `apps/web/vitest.config.ts` is a Next.js/jsdom config and is NOT reused for hook tests — hooks run under plain Node.)
- Cross-section:         PASS  (DAG acyclic: T-01 / T-02 / T-03 / T-06 have empty predecessors; T-04 on {T-01, T-03}; T-05 on {T-02, T-03}; T-07 on {T-01, T-02}; T-08 on {T-04, T-05, T-07} — DFS walk terminates. Every F-01..F-10 covered by ≥1 task's `files[]`: F-01 → T-01; F-02 → T-02; F-03 → T-04; F-04 → T-05; F-05 / F-06 / F-07 → T-03; F-08 → T-07; F-09 / F-10 → T-06. Every task's `files[]` resolves to a valid F-NN or is intentionally empty (T-08 is a manual-walkthrough execution task; the walkthrough steps themselves live in F-08 via T-07). No two DAG-independent tasks share a file — each F-NN appears in exactly one task's `files[]`. Test-strategy declares only `type: unit` (F-03, F-04) — matched by T-04, T-05.)
- Config drift:          PASS  (C1 no new runtime dep — F-01 uses no new npm packages, YAML parse is a hand-rolled top-level scalar scan matching what `services/mcp-server/src/agentrise_mcp/core/profile.py` reads; F-02 adds `node:perf_hooks` (Node built-in, no manifest edit); F-03 / F-04 use only `node:test` + `node:fs` built-ins. `apps/web/package.json` and `services/api/pyproject.toml` untouched. C2 no new service dir — feature stays in `.github/hooks/`. C3 no new port — dials into the already-declared port 3010 of the `# mcp-server` section in `docs/config/stack-smoke.md` (added by ING-04 T-11).)
- Decision-promotion:    PASS  (D-01 `blast:feature` + `rev:mechanical` → `adr:—` per `decide` skill rule; D-02 `blast:service` + `rev:mechanical` → `adr:—`; D-03 `blast:data` + `rev:mechanical` → `adr:ADR-0015` (promotion rule fires because `blast:data`; T-06 F-09 authors the ADR + F-10 updates the index); D-04 `blast:feature` + `rev:mechanical` → `adr:—`.)
- Rounds:                1

### Plan validation rounds

| Round | Timestamp | Verdict | Failing dimensions | Notes |
|---|---|---|---|---|
| 1 | 2026-09-15T04:00:00Z | PASS | — | All 6 dimensions clean on first pass; no revision required. |
