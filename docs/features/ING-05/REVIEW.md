# Code Review — ING-05 (feature/ING-05 @ 5a5d820)

- Date: 2026-09-15T05:35:00Z
- Mode: story (GATE MODE — report-only; state writes deferred to orchestrator)
- Branch: `feature/ING-05` @ `5a5d820404355949a67ceb25383eab7e0e3c844f`
- Snapshot SHA (computed): `9fc5c0f5507d9206da9b91062d3a554056d44bba9c8c30718c411a5b80869c09`
- Snapshot SHA (baseline): `13a86279eddf4f5516529661d74cc72980c03b58818536e72ef62c1359b4cd42`
- Snapshot SHA matches: **false** (order/whitespace drift in `git status --porcelain`; the shipped file set matches the invocation's declared diff exactly)
- Files reviewed: 7 (2 modified hooks, 2 new tests, 3 new fixtures, 1 new how-to)
- Verdict: **PASS WITH WARNINGS**

## Executive summary

The two-file rewrite closes the ING-04 141× `missing_required_field` regression cleanly. `program_id` resolution matches ADR-0015 verbatim (env → `program_id` → legacy `programId` → skip); the codec pin + unknown-kind skip is idiomatic; the push script's `AbortController(10s)` + IPv4-loopback pre-check + field-allowlist + head-drop rotator honour every named PRD constraint. The test suite exercises every AC with real subprocess spawns against real loopback servers — no over-mocking. Documentation is complete.

Two MEDIUM warnings: (1) `copilot-activity.mjs`'s `writeLog` does not enforce the DATA-DESIGN § 1 field allowlist and does not rotate — the invariant is defended in only one of the two writers into `.mcp-push.log`; (2) the child `spawn` is invoked with `stdio: ["ignore", fd, fd]` (child stdout/stderr fanned into the log fd) rather than PLAN.md § 3's declared `stdio: 'ignore'`, so any accidental console output from the push script lands in the log unfiltered and unrotated. Neither leaks credentials today (verified by grep across current call sites and by test (h) of the push suite), but both are contract gaps that will bite a future edit.

Five LOW findings track already-triaged flags (AF-01/04/05/06/07) plus one code-adjacent doc drift for traceability.

🟢 strengths (5)   |   ⚠️ warnings (2 MEDIUM, 5 LOW)   |   🛑 blockers (0)

## Findings summary

| Severity | Count | Category distribution                                                       |
|----------|-------|-----------------------------------------------------------------------------|
| CRITICAL |   0   | —                                                                           |
| HIGH     |   0   | —                                                                           |
| MEDIUM   |   2   | safety-security (1), integration (1)                                        |
| LOW      |   5   | contract-drift (1), testability (3), documentation (1)                     |

## FLAGS.md snapshot

All 7 items (AF-01..AF-07) carry `status: acknowledged` with batch verdict `informational — accepted; no source change required` (triaged 2026-09-15T05:19:40Z). Reviewer disposition per user directive ("a finding stays a finding even if a flag pre-empted it"):

| Flag  | Reviewer disposition                                                               |
|-------|------------------------------------------------------------------------------------|
| AF-01 | Defensible acknowledgement; still recorded below as L-1 (contract-drift) for trace. |
| AF-02 | Defensible — YAML is flat and single-doc in practice; low risk documented.         |
| AF-03 | Defensible — fixture matches the shape the hook actually reads (verified).         |
| AF-04 | Defensible — L-2 records the residual assertion gap for follow-up.                 |
| AF-05 | Defensible — L-3 records the POSIX-only limitation for CI portability audit.       |
| AF-06 | Non-defensible in PRD/DECISIONS prose (drift). L-4 records; how-to itself is correct. |
| AF-07 | Defensible — L-5 records the regex-brittleness for follow-up.                      |

## Detailed findings

### MEDIUM

#### M-1 — safety-security: `copilot-activity.mjs` `writeLog` does not enforce the DATA-DESIGN allowlist and does not rotate

- Category: Safety & security (dim 6)
- Path: `.github/hooks/copilot-activity.mjs:66-83`
- Source: `docs/features/ING-05/DATA-DESIGN.md` § 1 (log-line row: "Field allowlist enforced (allowlist diff, not denylist). Forbidden fields: `user_email`, `command_text`, `journal_contents`, `program_id`, `bearer_token`, `Authorization`"); `.claude/rules/security-baseline.md`; `docs/features/ING-05/REQUIREMENTS.md` § NFR-Security ("No PII in `.mcp-push.log`. Field allowlist per event").
- Description: `harness-mcp-push.mjs` implements the contract in full (allowlist filter loop `writeLog:65-70` + head-drop rotator `writeLog:75-107`). `copilot-activity.mjs`'s parallel writer at lines 70-76 does not: it accepts arbitrary `extra` keys and emits them verbatim with a bare `appendFileSync`, and applies zero rotation. Every existing call site was audited and none passes forbidden fields today, so no runtime leak. But the invariant is only defended in one of two writers, and the sequence `program_id_unresolved` (line 517) → `process.exit(0)` short-circuits before any push-script writeLog would rotate — a burst of unresolved sessions therefore grows the log past its 100-line / 32 KB cap until the next successful spawn triggers rotation. The DATA-DESIGN contract does not distinguish which writer must enforce; both must.
- Suggested fix: Extract a shared `writeLog` (allowlist filter + head-drop rotator, both) into a tiny `.github/hooks/_lib/log.mjs` and import from both scripts. Alternatively, inline the allowlist filter and rotator into the copilot-activity writer to match. Either way: the log's field-set and size invariants must not depend on the push script being spawned.

#### M-2 — integration: child `spawn` stdio diverges from PLAN § 3, bypassing allowlist + rotator

- Category: Integration points (dim 4)
- Path: `.github/hooks/copilot-activity.mjs:582-590`
- Source: `docs/features/ING-05/PLAN.md` § 3 Module Hierarchy ("`spawn(process.execPath, [pushScript], {detached:true, stdio:'ignore'}).unref()`"); `docs/features/ING-05/DATA-DESIGN.md` § 1 (log-line allowlist).
- Description: Actual invocation uses `stdio: ["ignore", fd, fd]` where `fd = openSync(MCP_PUSH_LOG, "a")` — the push child's stdout AND stderr are fanned directly into `.mcp-push.log`. Anything the child writes to console — a stray `console.log`, an uncaught top-level rejection stack trace, a Node built-in deprecation warning — lands in the log verbatim: (a) unfiltered by the allowlist, (b) unrotated, (c) not parseable as JSON-per-line. The current push script does not itself call `console.*` and wraps `main()` in `.catch`, so no observed leak; but the design intent (delegate all `.mcp-push.log` writes through the field-allowlisted `writeLog`) is not enforced at the process boundary. Also a subtle drift from PLAN § 3's declared shape.
- Suggested fix: Change to `stdio: 'ignore'` (matching PLAN § 3) and remove the `openSync` + `fd` plumbing. The child already writes its structured outcome via its own `writeLog`; the parent does not need to capture its console channels.

### LOW

#### L-1 — contract-drift: `.mcp-push.log` emits event values outside DATA-DESIGN § 1 enum

- Category: contract-drift
- Path: `.github/hooks/copilot-activity.mjs:599` (`no_script_found`), `:601` (`spawn`), `:614` (`spawn_error`), `:619` (`outer_error`)
- Source: `docs/features/ING-05/DATA-DESIGN.md` § 1 log-line `event` field: enum `success | http_error | timeout | network_error | program_id_unresolved | journal_codec_unknown_kind | mcp_url_non_loopback`.
- Description: Four event names emitted by `copilot-activity.mjs` are not in the DATA-DESIGN enum. Pre-existing per FLAGS AF-01, batch-triaged as `informational — accepted`. Recording for traceability per invocation directive — the acknowledgement is defensible (the events are structural diagnostics that surfaced during implementation and their addition does not break any downstream reader), but the DATA-DESIGN table remains the authoritative contract and stays out of sync until someone updates it or drops the emit sites.
- Suggested fix: Append the four values to the DATA-DESIGN § 1 enum ("`| spawn | spawn_error | outer_error | no_script_found`") OR drop the two diagnostic emits (`spawn`, `no_script_found`) and collapse `spawn_error`/`outer_error` under `network_error` with a distinguishing `error_code`. Either resolves the drift; the first is lower-risk.

#### L-2 — testability: `child.unref()` not directly asserted (AF-04)

- Category: Testability (dim 5)
- Path: `.github/hooks/__tests__/copilot-activity.test.mjs:407-490` (sub-test h)
- Source: `.claude/skills/vitest-patterns/SKILL.md` (parallel Node built-in `node:test` idioms); FLAGS AF-04.
- Description: The (h) sub-test proves detached + stdio-ignore + target-script via behavioural signals (`ps -o pgid=`, `fstatSync(0).isCharacterDevice()`, `argv[1]` regex) but cannot directly assert `child.unref()` because the hook does `const { spawn } = await import("node:child_process")` — ESM named-export binding is static-linked, so in-process monkey-patch is invisible. The fast-parent-exit budget (< 1500 ms while child sleeps 500 ms) is a strong proxy but not a direct assertion.
- Suggested fix: Accept as-is (AF-04 disposition). Alternate: refactor the spawn call to import the `child_process` module namespace once (`const cp = await import(...)`) and call `cp.spawn(...)` — then a Node `--import` preloader could intercept via namespace-object property write. Cost vs. benefit favours keeping the behavioural check.

#### L-3 — testability: POSIX-only assertions in sub-test (h) (AF-05)

- Category: Testability (dim 5)
- Path: `.github/hooks/__tests__/copilot-activity.test.mjs:407-490`
- Source: FLAGS AF-05; CLAUDE.md target platform (Web, no explicit Windows CI dependency); CI `none`.
- Description: `ps -o pgid=` and `S_IFCHR` characterisation of `/dev/null` are POSIX-only; on Windows the sub-test would silently fail. CLAUDE.md posture is local-dev macOS/Linux + no CI, so acceptable, but not documented in the test file as a top-level limitation.
- Suggested fix: Add a top-of-file `if (process.platform === "win32") { test.skip(...); return; }` guard OR at least a header comment pinning the POSIX-only assumption. Zero code-change alternative: leave as-is per AF-05 disposition.

#### L-4 — documentation: PRD/DECISIONS reference wrong path for Claude Code hook (AF-06)

- Category: Documentation (dim 6, project-standards)
- Path: `docs/features/ING-05/REQUIREMENTS.md:66` ("`.github/hooks/harness-activity.mjs` (existing 16-row corpus)"); `docs/features/ING-05/DECISIONS.md` D-01 (same string)
- Source: `.claude/settings.json` (hook wiring); FLAGS AF-06.
- Description: The Claude Code activity hook lives at `.claude/hooks/harness-activity.mjs`, not `.github/hooks/harness-activity.mjs`. `docs/how-to/copilot-chat-setup.md` uses the correct path (§ 4 and § 6). The drift is prose-only in PRD/DECISIONS. The user's invocation excluded PRD/DECISIONS from the source diff, so this is out-of-scope for the shipped-code review; recording under LOW for the same-branch how-to's benefit — a future reader following the PRD's file path lands nowhere.
- Suggested fix: Follow-up carry-forward — one-line search-and-replace across PRD and DECISIONS after this branch merges. Not blocking.

#### L-5 — testability: AC-4 default URL asserted via source-file regex, not module read (AF-07)

- Category: Testability (dim 5)
- Path: `.github/hooks/__tests__/harness-mcp-push.test.mjs:203-217` (sub-test a)
- Source: FLAGS AF-07.
- Description: The push module has no exports and auto-runs `main()` on import, so the default URL constant is not directly readable in-process. The (a) sub-test reads `PUSH_PATH` from disk and asserts two regexes (positive `127.0.0.1:3010` and negative `!localhost`). A rename of the env var (`HARNESS_MCP_URL` → any other name) or a refactor to a helper (`getMcpUrl()`) evades both patterns while preserving the runtime behaviour. Assertion is brittle.
- Suggested fix: Accept per AF-07 disposition. Alternate: expose the constant via a named export `export const MCP_URL_DEFAULT = "http://127.0.0.1:3010/mcp"` and switch the assertion to an import — but that means splitting the module's boot side-effect from its constants, which is a larger refactor for marginal test signal.

## What went well

- **ADR-0015 implemented verbatim.** `resolveProgramId` at `.github/hooks/copilot-activity.mjs:80-107` matches the four-step precedence exactly (env non-empty → `program_id` key → legacy `programId` key → skip). Tests (a)/(b)/(c)/(d) in `copilot-activity.test.mjs` exercise all four paths against real spawned subprocesses. R-03 (row-level `program_id` alignment) fully closed.
- **Push script's `writeLog` is exemplary.** Allowlist filter (`.github/hooks/harness-mcp-push.mjs:65-70`) + head-drop rotator (`:75-107`) + best-effort try/catch (never throws — honours AC-5 no-non-zero-exit) is the shape DATA-DESIGN § 1 mandated. Test (h) proves the allowlist end-to-end by grepping raw log bytes for six credential-shaped needles and asserting absence.
- **`AbortController(10_000)` per RPC + IPv4-loopback pre-check** — Both NFR-Security and NFR-Performance closed with tests (c) (wall-clock ≤ 10 500 ms), (d) (exactly one fetch), (i) (non-loopback refused in < 3 s, no network I/O). No shell injection surface: spawn uses `process.execPath` + array args.
- **`response body never echoed on !res.ok`** — Line 148-151 constructs `new Error(\`http_${res.status}\`)` and stores `err.http_status`; the response `text` is never attached. Fixes the AC-earlier violation cited in the invocation. `classifyError` at `:172-186` only propagates `http_status` and error `code` — never message content.
- **Test suite honours the two-process reality.** `harness-mcp-push.test.mjs` uses real `http.createServer` on random port + `child_process.spawn` — no fetch mock, no timing mock. Test (b) inspects HTTP call order + method + JSON-RPC body; test (j) pre-fills 100 seed lines and asserts head-drop preserves the tail. Deterministic, portable within POSIX.

## Recommendation

**PASS WITH WARNINGS** — safe to ship. Flag the two MEDIUM findings (M-1 log-writer parity, M-2 spawn stdio) in the PR body as follow-up carry-forward; both are one-file fixes and neither blocks the AC-1..AC-5 landing. Address before the next producer of `activity.jsonl` rows (Claude Code migration, Codespaces bridge) is written — that story will inherit the same log invariant and should not have to redo this discovery.

<!--
GATE MODE — report-only. Per skill review-assessment § State write (mode-conditional),
no state.json / features.json write from this agent. Orchestrator is the single writer
after the Validate ∥ Review join.
-->
