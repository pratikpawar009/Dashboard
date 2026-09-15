---
feature_id: ING-05
title: Copilot Chat activity-hook bridge
story_id: ING-05
tracker_story: pratikpawar009/Dashboard#44
tracker_research: pratikpawar009/Dashboard#322
author: product-spec-agent
date: 2026-09-15
status: Draft
---

# Feature: ING-05 — Copilot Chat activity-hook bridge

## Problem

Developers using VS Code Copilot Chat (not Claude Code) get zero dashboard visibility today. ING-04 shipped the local MCP server (`services/mcp-server/`, FastMCP streamable HTTP on `0.0.0.0:3010/mcp`, PR #323, commit `7e2b8c6`) exposing `push_activity`, and ING-02 shipped `POST /api/ingest/activity`. Two draft hook scripts already sit in the tree (`.github/hooks/copilot-activity.mjs`, `.github/hooks/harness-mcp-push.mjs`) but never fire on Copilot Chat `sessionEnd`, and when they did during ING-04's live E2E they produced 141× `missing_required_field` on `program_id` — every row was rejected before reaching `usage_events`. The activity and per-developer panels stay empty for Copilot-Chat users, and Copilot slash-command usage is invisible to EMs, PMs, and executives.

## Outcome

A `sessionEnd` fire from VS Code Copilot Chat produces exactly one appended-or-upserted row in `docs/activity/activity.jsonl` keyed by `(session_id, cmd_ts)`, carrying a populated `program_id` alongside the shipped `ActivityRowIn` field set. Immediately after the write, `copilot-activity.mjs` spawns `harness-mcp-push.mjs` as a **detached** child (non-blocking, `child.unref()`, hook returns within 2 s p95) that runs the MCP JSON-RPC sequence `initialize → notifications/initialized → tools/call push_activity → DELETE` against `HARNESS_MCP_URL` (default `http://127.0.0.1:3010/mcp`), bounded by a single 10 s per-call timeout, and appends the outcome to `docs/activity/.mcp-push.log`. Ingest succeeds end-to-end: the row lands in `usage_events` via `push_activity` → `POST /api/ingest/activity`, and the dashboard's Activity panel shows Copilot-Chat rows next to the existing Claude/harness rows.

## Constraints

- **Row schema is fixed by `services/api/app/schemas/ingest_files.py::ActivityRowIn`** — REQUIRED (per row): `program_id, ts, cmd_ts, user, session_id, command, duration_seconds, outcome, total`. Nullable: `kind, feature, intervention_count, files_created, files_modified, lines_added, tool_rejections, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, models, source, copilot_credits`. Aliases: `duration_s`, `input_token`, `output_token`, `cache_read`, `cache_write`. Envelope also enforces `program_id` match — drift emits `program_id_mismatch`.
- **MCP contract is frozen by ING-04** — `services/mcp-server/src/agentrise_mcp/tools/push_activity.py` sends `{program_id, kind:"activity", rows}`. The tool **does not** patch per-row `program_id`; that is the hook's job. Effective envelope `program_id` = tool arg `program_id` OR `.harness/program.yaml → program_id`.
- **Push transport is frozen by AC-3 / AC-4** — MCP streamable HTTP, IPv4 loopback default (`http://127.0.0.1:3010/mcp`, never `localhost`, to dodge Windows IPv6 resolution failures). Env overrides: `HARNESS_MCP_URL`, `HARNESS_PROGRAM_ID`.
- **Fire-and-forget is contractual (AC-2)** — the push child is detached and never blocks Copilot Chat's Stop event. Retry logic is FORBIDDEN in the hook because a retry loop would violate that contract (the child would live longer than the Stop event's timeout window and users would see a stuck Copilot Chat).
- **Local-only feature** — bearer-token custody stays on the MCP server (ING-04 owns `AGENTRISE_INGEST_TOKEN`). This hook talks only to `127.0.0.1:3010` over loopback and MUST NOT read or forward any credential.
- Research verdict: **GO-WITH-CONDITIONS** (66/100) — all 7 conditions addressed in § Addressing Research Conditions below; all 5 open clarifications resolved 2026-09-15.

## Solution sketch

`copilot-activity.mjs` runs on VS Code Copilot Chat `sessionEnd`. It resolves the VS Code workspace hash by scanning `workspaceStorage/*/workspace.json` for a folder URI that matches the project root (longest-match wins), reads the two-layer Copilot journals (`chatSessions/<uuid>.jsonl` + `GitHub.copilot-chat/transcripts/<uuid>.jsonl`), and replays kinds `{0, 1, 2}` under a pinned `JOURNAL_CODEC_VERSION = "1"` constant — any other `kind` is skipped and logged once as `journal_codec_unknown_kind`, never aborts the batch. For each Copilot slash-command invocation it assembles a row matching the `ActivityRowIn` schema, populates `program_id` from `HARNESS_PROGRAM_ID` env (else `.harness/program.yaml → program_id`), parses `feature` via `^/\S+\s+([A-Z]{2,4}-\d+)\b` (bare-token positional argument only; anything else → `null`), emits `cache_read=0`/`cache_write=0` (accepted as-is by the nullable schema), and NDJSON-appends-or-upserts by `(session_id, cmd_ts)` into `docs/activity/activity.jsonl`. Then it spawns `harness-mcp-push.mjs` detached (`spawn(process.execPath, ..., {detached: true, stdio: 'ignore'}).unref()`) and returns. `harness-mcp-push.mjs` runs the MCP JSON-RPC sequence against `HARNESS_MCP_URL`, each HTTP call bounded by a single 10 s `AbortController` budget with no retry, and appends the outcome (`success | http_error | timeout | network_error`) to `docs/activity/.mcp-push.log` (rotated at 100 lines / 32 KB). A push failure is silent to Copilot Chat — the log is the only surface.

## Addressing Research Conditions

Verdict: `GO-WITH-CONDITIONS`. Every numbered condition from `docs/research/ING-05.md` § Verdict → Conditions is addressed below with concrete mitigations. All 5 implementation directives promoted from resolved clarifications (§ Open Clarifications tail) map 1:1 to an FR or NFR with an observable acceptance signal.

Research conditions:

- **C-1 — Add row-level `program_id` to every emitted activity row** → addressed by **ING-05-FR-1**. Root cause of ING-04's live-E2E 141× `missing_required_field`. Observable: every row appended to `docs/activity/activity.jsonl` has a non-empty `program_id` string.
- **C-2 — Unit test coverage for `copilot-activity.mjs` (journal parsing, line-count heuristics, upsert-key logic, three journal kinds)** → addressed by § Documentation requirements → Test fixtures and by `ING-05-FR-2` / `ING-05-FR-3` (each FR carries a named unit test in Test fixtures). PLAN adds `.github/hooks/__tests__/copilot-activity.test.mjs` with fixtures covering kinds 0/1/2 plus an unknown-kind fixture.
- **C-3 — Unit test coverage for `harness-mcp-push.mjs` (JSON-RPC handshake, timeout, log-file writes) with mocked fetch** → addressed by § Documentation requirements → Test fixtures. PLAN adds `.github/hooks/__tests__/harness-mcp-push.test.mjs` asserting the abort fires by 10.5 s (see `ING-05-NFR-performance`) and that the log rotator keeps the file bounded (see `ING-05-NFR-observability`).
- **C-4 — Clarify timeout NFR** → RESOLVED and addressed by **ING-05-NFR-performance**. Bound is 10 s total per HTTP call, single attempt, no retry (aligns story AC-5 with the fire-and-forget contract). `TIMEOUT_MS = 10_000` in `harness-mcp-push.mjs` — reduced from the drifted `15_000` in the current draft.
- **C-5 — Document VS Code Copilot Chat setup (extension install, MCP server config, `HARNESS_MCP_URL` / `HARNESS_PROGRAM_ID` env vars, troubleshooting)** → addressed by § Documentation requirements → `docs/how-to/copilot-chat-setup.md`.
- **C-6 — `.mcp-push.log` rotation / retention policy** → addressed by **ING-05-NFR-observability**. Bounded at 100 lines / 32 KB — whichever hits first triggers a truncate-and-rewrite of the tail. Observable: after 200 pushes, `wc -l .mcp-push.log ≤ 100` and `wc -c .mcp-push.log ≤ 32768`.
- **C-7 — Run E2E validation (real Copilot Chat session end → `activity.jsonl` → `.mcp-push.log` → backend row)** → addressed by § Test mapping in `docs/stories/ING-05.md` (Manual entry) and re-carried into § Documentation requirements → Manual validation walkthrough (`docs/how-to/copilot-chat-setup.md § Troubleshooting`). CI: none, per `CLAUDE.md`; automation is not possible for the Copilot Chat lifecycle event.

Implementation directives promoted from resolved clarifications (all 5):

- **Directive 1 — `program_id` on every row** → **ING-05-FR-1**. Observable signal: fixture unit test asserts `program_id` is present and non-empty on every generated row; live-run row inspection shows `.program_id` matches `HARNESS_PROGRAM_ID` env / `.harness/program.yaml → program_id`.
- **Directive 2 — `JOURNAL_CODEC_VERSION = "1"` module constant** → **ING-05-FR-2**. Observable: unit test asserts an unknown-kind fixture (e.g., `kind: 99`) skips + emits exactly one `journal_codec_unknown_kind` log line per session-end and never aborts the batch (row for the surrounding valid kinds is still emitted).
- **Directive 3 — `cache_read` / `cache_write` = 0** → **ING-05-FR-3**. Observable: fixture asserts both fields are literal `0` in the emitted row; a companion test round-trips the row through `ActivityRowIn` and confirms no schema rejection.
- **Directive 4 — Feature parsing (bare-token positional only)** → **ING-05-FR-4**. Observable: parametrised unit test — `/arh-plan-implementation BED-01` → `feature="BED-01"`; `/arh-plan-implementation --feature BED-01` → `feature=null`; `/arh-plan-implementation` (no arg) → `feature=null`.
- **Directive 5 — MCP push `TIMEOUT_MS = 10_000`, single attempt, no retry** → **ING-05-FR-5** + **ING-05-NFR-performance**. Observable: unit test with a fetch stub that never resolves asserts the `AbortController` fires by 10.5 s wall-clock and the run logs exactly one `timeout` line (no retry attempt).

## Scope

- **In**:
  - `.github/hooks/copilot-activity.mjs` — journal reader, row assembler, NDJSON append/upsert on `(session_id, cmd_ts)`, detached spawn of `harness-mcp-push.mjs`, `JOURNAL_CODEC_VERSION` module constant, `program_id` resolution + write per row, feature parser (bare-token positional), `cache_read=0`/`cache_write=0` emit, updated header comment pinning `JOURNAL_CODEC_VERSION` and the observed schema shape "as of 2026-09-15".
  - `.github/hooks/harness-mcp-push.mjs` — MCP JSON-RPC sequence, IPv4 loopback default, `TIMEOUT_MS = 10_000` (reduced from 15_000), single attempt, silent-exit on failure, structured log write to `.mcp-push.log`, log rotation at 100 lines / 32 KB.
  - `docs/activity/.mcp-push.log` — bounded log file (rotation lives inside the push script).
  - `docs/how-to/copilot-chat-setup.md` — new how-to covering VS Code Copilot Chat setup, MCP server startup, `HARNESS_MCP_URL` + `HARNESS_PROGRAM_ID` env vars, and `.mcp-push.log` troubleshooting.
  - Unit-test suite under `.github/hooks/__tests__/` (Node built-in `node:test`, matching the runtime the hooks already assume): `copilot-activity.test.mjs`, `harness-mcp-push.test.mjs`, plus journal fixtures covering kinds 0/1/2 + one unknown kind.
- **Out**:
  - Claude Code activity bridge — already shipped as `.github/hooks/harness-activity.mjs` (existing 16-row corpus in `activity.jsonl`); this story reuses the same schema and MCP tool but adds no code to that path.
  - Any change to `services/mcp-server/` — ING-04 owns the MCP surface; this story is a pure client of the frozen `mcp-tools` contract.
  - Any change to `services/api/app/schemas/ingest_files.py` or `activity_ingest.py` — this story emits rows the shipped schema already accepts.
  - Backend schema changes to add a `copilot_credits`-first source signal — the current nullable field is enough; downstream analytics reads are out of scope for ING-05.
  - Retry / resend on push failure — forbidden by AC-2 (fire-and-forget). Missed events stay missed; the developer's next successful session re-establishes the pipeline.
  - Codespaces / remote-VS-Code storage layout — hook targets local macOS / Windows / Linux `workspaceStorage/` only; a Codespaces bridge is a separate future story.
  - Multi-workspace or multi-VS-Code-instance disambiguation beyond longest-path-match — noted as a documented limitation in `docs/how-to/copilot-chat-setup.md § Troubleshooting`, not a new heuristic here.
  - Health-check notifications from the hook into the VS Code output panel — out of scope; `.mcp-push.log` is the only observability surface.

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/ING-05.md` for canonical wording. New impl constraints introduced below (the `program_id` write, the codec constant, feature parsing, cache-token literal, and the tightened push timeout are the deltas that the shipped hook draft does not yet enforce):

**ING-05-FR-1** — `program_id` populated on every emitted row  *(extends AC-1 with: source resolution + fail-fast on missing)*

Every row `copilot-activity.mjs` appends or upserts into `docs/activity/activity.jsonl` MUST include a non-empty `program_id` string. Resolution order at row-assembly time:

1. `process.env.HARNESS_PROGRAM_ID` when non-empty.
2. Fallback: parse `<workspace_root>/.harness/program.yaml` and read the top-level `program_id` (also accepted as the legacy key `programId` — the file may use either; prefer `program_id` on write).
3. Neither source available → the hook exits with a `program_id_unresolved` line in `.mcp-push.log` and NDJSON append is skipped for that session-end. NO row is written with an empty or placeholder `program_id`, because the envelope check in `push_activity` would then emit `program_id_mismatch` and the ingest side would 141×-reject as it did during ING-04's live E2E.

Observable signal: `.github/hooks/__tests__/copilot-activity.test.mjs::test_program_id_env_wins` and `::test_program_id_yaml_fallback` and `::test_program_id_unresolved_skips_write` all pass.

**ING-05-FR-2** — Journal codec version pinned; unknown kinds skipped  *(extends AC-1 with: forward-compat contract)*

`copilot-activity.mjs` MUST expose a module-level constant `const JOURNAL_CODEC_VERSION = "1";` and treat only the known kind set `{0, 1, 2}` as replayable. Any other numeric or string `kind` value MUST be:

- Skipped silently for the purpose of row assembly (no partial-state exception, no batch abort).
- Logged exactly once per session-end as a single line `journal_codec_unknown_kind kind=<value> codec_version="1"` to `.mcp-push.log` (via the same log writer as the push script).
- Not counted as a rejection in any downstream metric (the row for surrounding valid kinds still emits normally).

Observable signal: unit test replays a fixture stream `[{kind:0,...}, {kind:99,...}, {kind:1,...}]` and asserts exactly one row is emitted and exactly one `journal_codec_unknown_kind` log line fires.

**ING-05-FR-3** — `cache_read` / `cache_write` emitted as literal `0`  *(extends AC-1 with: explicit schema-alignment note)*

Copilot Chat journals do not split cache tokens per layer, so `copilot-activity.mjs` MUST emit `cache_read: 0` and `cache_write: 0` (and their `cache_read_tokens` / `cache_write_tokens` aliases, whichever the row builder picks — the shipped `ActivityRowIn` accepts both) on every Copilot-sourced row. Backend accepts these as-is: both fields are declared `int | None = Field(default=None, alias="…")` per `services/api/app/schemas/ingest_files.py::ActivityRowIn`. Not `null`, not omitted — the literal `0` preserves the "measured and known-zero" semantics, distinct from "not measured".

Observable signal: unit test asserts `row.cache_read === 0 && row.cache_write === 0` for a Copilot-source fixture; a round-trip through a Python `ActivityRowIn(**row)` under `services/api/tests/` fixture confirms no rejection.

**ING-05-FR-4** — `feature` parsed as bare-token positional only  *(extends AC-1 with: exact regex + rejection rule)*

`copilot-activity.mjs` MUST parse the `feature` field from the Copilot slash-command text using ONLY the regex `^/\S+\s+([A-Z]{2,4}-\d+)\b`. The match target is a bare-token positional argument immediately after the command name. Anything else — `--feature <id>`, `-f <id>`, `feature=<id>`, or the id anywhere but the first positional slot — MUST yield `feature: null`. `feature` is `str | None` on `ActivityRowIn`, so `null` is a legal wire value.

Observable signal: parametrised unit test — inputs `[/plan BED-01, /plan --feature BED-01, /plan, /plan BED-01 extra]` → outputs `["BED-01", null, null, "BED-01"]`.

**ING-05-FR-5** — MCP push single-attempt discipline  *(extends AC-2 + AC-5 with: retry ban + timeout constant)*

`harness-mcp-push.mjs` MUST expose a module-level constant `const TIMEOUT_MS = 10_000;` (reduced from the drifted `15_000` in the current draft) and MUST run each of the four MCP RPC calls (`initialize`, `notifications/initialized`, `tools/call push_activity`, `DELETE`) as a SINGLE `fetch()` attempt bounded by one `AbortController` with `setTimeout(controller.abort, TIMEOUT_MS)`. Retry is FORBIDDEN — a retry loop would extend the detached child's wall-clock beyond the Stop-event window and violate the fire-and-forget contract of AC-2. On timeout / non-2xx / network error, the script writes exactly one summary line to `.mcp-push.log` (`{event, ts, http_status | error_code, duration_ms}`), calls `process.exit(0)`, and never re-attempts.

Observable signal: unit test stubs `fetch` to hang; asserts abort fires by 10.5 s and log records exactly one `timeout` line (no second `initialize` attempt).

## Non-functional requirements

- **Performance**: Per `.claude/rules/performance-baseline.md`: applies to every outbound HTTP call from `harness-mcp-push.mjs` and to the hook's return time. Feature-specific numeric budgets:
  - `TIMEOUT_MS = 10_000` per HTTP call, single attempt, no retry (see ING-05-FR-5). This is the SAME 10 s ceiling for all four RPC calls — the script does not multiplex a single wall-clock across the sequence; each call has its own budget.
  - `copilot-activity.mjs` MUST return within **2 s p95** from `sessionEnd` fire. The heavy work (journal read, row assembly, NDJSON write) runs before the spawn; the spawn itself is `spawn(process.execPath, [...], {detached: true, stdio: 'ignore'}).unref()` and returns immediately. Observable: manual timing of 20 sequential Copilot Chat session ends against a running MCP server records p95 < 2 s in the walkthrough log.
- **Security**: Per `.claude/rules/security-baseline.md`: applies to every path in this hook. Feature-specific additions:
  - Zero credentials in the hook. Neither script reads any bearer or ingest token. The MCP server (ING-04) holds `AGENTRISE_INGEST_TOKEN` and injects it at the outbound `POST /api/ingest/activity` call. The hook talks only to `127.0.0.1:3010` over loopback.
  - No PII in `.mcp-push.log`. Field allowlist per event: `{event, ts, http_status | error_code, duration_ms, mcp_url_host}`. Never `user_email`, never raw command text, never journal contents, never a program_id (which some setups derive from a customer identifier).
  - Loopback default is IPv4 literal `127.0.0.1` (NOT `localhost`) per AC-4 — avoids Windows IPv6-resolution failures that would time out the push silently. `HARNESS_MCP_URL` env override MAY point elsewhere but MUST be a loopback URL; the script MUST refuse (log `mcp_url_non_loopback` and exit 0) any URL whose host does not resolve to `127.0.0.1` or `::1`.
- **Accessibility**: N/A — background Node hook, no UI surface.
- **Observability**: Per `.claude/rules/performance-baseline.md` ("Cache invalidation is explicit. Document TTL and the invalidating event."), applied here to the log surface:
  - `.mcp-push.log` MUST be bounded: hard caps 100 lines AND 32 KB. Whichever cap is hit first triggers a truncate-and-rewrite that keeps the tail (the most recent lines that fit under both caps). Rotation happens at write time, in-process — no external cron, no logrotate.
  - Every session-end produces exactly one summary line, either from `harness-mcp-push.mjs` (push outcome) or from `copilot-activity.mjs` when the hook short-circuits (e.g., `program_id_unresolved` per ING-05-FR-1, `journal_codec_unknown_kind` per ING-05-FR-2, `mcp_url_non_loopback` per NFR-Security).
  - Log line shape: single-line JSON `{"event": <name>, "ts": <iso8601>, ...}`. Grep-parseable, event names stable.

## Visual spec

Not applicable — background Node hook, no UI surface. design_mode=none override from integrations.design=html-mockup.

## Rollout plan

- **Strategy**: bang-bang. Local-only feature. Installation is opting in — a developer wires the `sessionEnd` hook to `.github/hooks/copilot-activity.mjs` in their VS Code Copilot Chat config (see `docs/how-to/copilot-chat-setup.md`). No shared infrastructure changes.
- **Feature flag**: none. Opt-in by installation is the enable gate; no runtime toggle. Backward-compatible with the existing Claude Code activity flow because both hooks share the `ActivityRowIn` schema and the same MCP tool.
- **Backout plan**: revert `.github/hooks/copilot-activity.mjs` and `.github/hooks/harness-mcp-push.mjs` to their previous commit (or remove the VS Code Copilot Chat hook wiring locally). The MCP server, ingest endpoints, and existing `activity.jsonl` rows are unaffected. No database or schema change to unwind.
- **Success signal**: within 7 days of the story merging, at least 2 distinct developers (roster emails from `.harness/program.yaml::team[]`) show a `push_activity` success line in their `.mcp-push.log` AND a matching Copilot-source row (identified by `source: "copilot"`) in `docs/activity/activity.jsonl`, AND the corresponding `usage_events` row is visible in the dashboard's Activity panel. Zero `program_id_mismatch` rejections in the backend ingest log across the same window (the ING-04 141× regression does not recur).

## Documentation requirements

- **README updates**: none required at the repo root — the how-to below is discoverable via `docs/how-to/`. Add a one-line entry to `docs/activity/README.md` (if present; otherwise skip) pointing at the new how-to.
- **Runbook**: none — local-machine hook, no operational surface owned by a platform team.
- **API reference**: none — this story consumes the frozen `mcp-tools` contract (`docs/requirements/api.md#mcp-tools`) and the shipped `ActivityRowIn` schema. No new endpoints or contract fields.
- **Inline code comments**:
  - `.github/hooks/copilot-activity.mjs` header comment MUST pin `JOURNAL_CODEC_VERSION = "1"` verbatim and document the observed Copilot Chat journal schema shape "as of 2026-09-15" (kind 0 snapshot, kind 1 set, kind 2 push; nested `requests[]`; `modelId`, `promptTokens`, `completionTokens`, `copilotCredits`). Two-line rationale: (a) this shape is reverse-engineered, not documented by Microsoft; (b) any future break is traceable via a single grep for the constant.
  - `.github/hooks/harness-mcp-push.mjs` header comment MUST note the `TIMEOUT_MS = 10_000` decision (single attempt, no retry, fire-and-forget contract per AC-2) and reference this PRD's ING-05-FR-5.
- **Examples / how-to**: `docs/how-to/copilot-chat-setup.md` — new file with the following sections (structure only; PLAN owns the content):
  - Prerequisites — VS Code + Copilot Chat extension installed, `services/mcp-server/` running locally with `AGENTRISE_INGEST_TOKEN` set, `.harness/program.yaml` present with `program_id`.
  - Wire the hook — Copilot Chat `sessionEnd` → `.github/hooks/copilot-activity.mjs`.
  - Env vars — `HARNESS_MCP_URL` (default `http://127.0.0.1:3010/mcp`), `HARNESS_PROGRAM_ID` (fallback to `.harness/program.yaml → program_id`).
  - Verify — trigger one Copilot Chat command, tail `docs/activity/activity.jsonl` (row appended?), tail `docs/activity/.mcp-push.log` (success line?).
  - Troubleshooting — reading `.mcp-push.log`, the four canonical failure events (`timeout`, `http_error`, `network_error`, `program_id_unresolved`), the multi-workspace / multi-VS-Code-instance limitation (longest-path-match heuristic), the Codespaces limitation (unsupported), and the manual E2E walkthrough that closes research condition C-7.

## Open questions

None open. All 5 research clarifications (per `docs/research/ING-05.md § Open Clarifications`) were resolved 2026-09-15 and promoted into FRs / NFRs above. No new PRD-level questions were introduced.

Decisions logged in `docs/stories/ING-05.md` § Decision log.

## Approvals

- **2026-09-15** — Product Owner (single-approver mode: PO + Designer + BA): **APPROVE**
  - Feature Summary, FRs, User Flows reviewed
  - UI specs: N/A for this background Node-hook story (`design_mode = none` override; `integrations.design = html-mockup`)
  - Edge Cases, Open Questions, test-case completeness reviewed
  - No-placeholder check ✓ · `[NEEDS CLARIFICATION]` count = 0
  - Research verdict `GO-WITH-CONDITIONS` — all 7 conditions addressed in § Addressing Research Conditions; all 5 implementation directives promoted to FRs / NFRs
  - Test-case coverage: 3/3 automatable, deliberate small-batch cap; 7 uncovered IDs (`AC-1, AC-3, AC-4, FR-2, FR-3, FR-4, NFR-security`) acknowledged and accepted — remaining coverage exercised by manual E2E (AC-5)
  - Tracker subtask: pratikpawar009/Dashboard#323
