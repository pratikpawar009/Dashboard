---
feature_id: ING-05
title: Copilot Chat activity-hook bridge
author: Research Agent
date: 2026-09-15
status: Complete
---

# Research Assessment: ING-05

## Upstream Dependencies

| ID | Story | Status | Verdict | Impact |
|----|-------|--------|---------|--------|
| ING-04 | MCP server tool exposure (push_activity / push_artifacts) | Merged (PR #323, commit 7e2b8c6) | GO-WITH-CONDITIONS | Upstream complete. FastMCP streamable HTTP on `0.0.0.0:3010/mcp` live. `push_activity` tool available. ING-05 consumes this via JSON-RPC protocol. |

MCP server is **live on main** and ready for consumption. ING-05 is a pure-client consumer of the frozen `mcp-tools` contract.

---

## Exploration Log

**Goal**: Map the integration points, prior art, and schema alignment for Copilot Chat activity bridging into the harness pipeline.

### 1. Hook Script Inventory

- **Where**: `.github/hooks/copilot-activity.mjs`, `.github/hooks/harness-mcp-push.mjs` (both exist, draft state)
- **What**: `copilot-activity.mjs` parses VS Code Copilot Chat local session/transcript journals (JSONL format) at two layers; reconstructs per-command token usage and file edit events; upserts one summary record per Copilot slash-command invocation into `docs/activity/activity.jsonl` keyed by `(session_id, cmd_ts)`. `harness-mcp-push.mjs` spawns detached from the activity hook, speaks MCP JSON-RPC protocol against local MCP server (default `http://127.0.0.1:3010/mcp`), and logs outcomes to `.mcp-push.log`.
- **Surprises**: 
  - VS Code Copilot Chat storage is **two-layer JSONL journals** (chatSessions + transcripts), not a single unified log. Journal paths are resolved by scanning `workspaceStorage/<hash>/workspace.json` for folder URI matching (workspace hash is opaque, not a stable identifier).
  - Cache token accounting: hook reads `cache_read=0, cache_write=0` (Copilot journal does not split cache tokens per layer 1, per AC NFR doc).
  - Lines added: reconstructed from `tool.execution_start` events via argument parsing (content, newString/newText diffs); does not diff actual file content.
  - MCP push spawn uses `child.unref()` and `process.execPath` (not `node` in PATH), confirming detached/non-blocking contract.
  - IPv4 loopback (`127.0.0.1`, not `localhost`) to avoid Windows IPv6 resolution issues.
- **Open**: 
  - VS Code Copilot Chat journal **backward-compatibility**: if VS Code changes journal structure, schema, or storage paths, hook breaks silently (tools run but produce no events). No semantic versioning or deprecation warnings documented by Microsoft.
  - Copilot session/command identity: story assumes `sessionId` (UUID in journal file name) is stable and unique per Copilot session. Unconfirmed whether Copilot rotates session IDs or reuses them across VS Code restarts.

### 2. Activity Schema Alignment

- **Where**: `docs/activity/activity.jsonl` (existing, live rows), `docs/requirements/data.md#db-schema` (usage_events unique constraint), `docs/requirements/api.md#mcp-tools` (tool result envelope)
- **What**: Activity hook outputs record with fields: `{ts, user, session_id, cmd_ts, kind, command, feature, duration_s, outcome, intervention_count, files_created, files_modified, lines_added, tool_rejections, input_token, output_token, cache_read=0, cache_write=0, total, models{}, copilot_credits, source="copilot"}`. Backend `usage_events` table requires unique constraint `(program_id, session_id, cmd_ts)` to match upsert key. Existing activity.jsonl rows (e.g., first row 2026-08-26T10:05:20.964Z) use same key structure: `session_id="42c04d05-cb03-4a45-a445-9515c6628808"`, `cmd_ts="2026-08-26T10:05:20.964Z"`.
- **Surprises**:
  - Hook record includes `copilot_credits` field (Copilot-native cost signal), not in `usage_events` schema. Backend ingest will either ignore (extra="ignore" Pydantic mode per ING-02 pattern) or reject as unknown field. No drift, but silent drop.
  - Existing activity.jsonl **does not include `program_id`** in the row itself. Clarification: `program_id` is supplied at **push time** (MCP tool argument), not at hook write time. Activity.jsonl is program-agnostic; program_id is bound in the MCP push envelope.
- **Open**:
  - Hook sets `kind="command"` (literal), backend schema says `kind` is nullable String. Must verify backend does not expect `kind=null` for Copilot events or enforce an enum. Existing harness rows have `kind="command"` (matching).
  - Field `feature` (ETL ID like "BED-01") is parsed from command text by regex; matches usage_events but is nullable. Hook may fail to extract if user types `/cmd BED-01` vs `/cmd --feature BED-01` (currently only space-delimited prefix regex).

### 3. MCP Server Integration Point

- **Where**: `services/mcp-server/src/agentrise_mcp/server.py` (ING-04, live), `src/agentrise_mcp/core/config.py` (token loading), `src/agentrise_mcp/tools/push_activity.py` (tool implementation)
- **What**: MCP server binds `0.0.0.0:3010` path `/mcp`, exposes `push_activity(program_id?, workspace_root?)` tool over FastMCP streamable HTTP. Tool reads `.harness/program.yaml` activity files, batches 500 rows, POSTs to backend `POST /api/ingest/activity`. MCP push hook (harness-mcp-push.mjs) speaks JSON-RPC: `initialize` → `notifications/initialized` → `tools/call push_activity` → `DELETE` (cleanup).
- **Surprises**:
  - ING-04's `push_activity` implementation reads `.harness/program.yaml::files[]` (glob patterns), not the activity.jsonl directly. So the flow is: activity.jsonl written by Copilot hook → MCP push hook invokes `push_activity` tool → tool reads activity.jsonl from `files[]` glob → batches and POSTs. Indirection adds a layer but keeps concerns separated.
  - MCP server reads `AGENTRISE_INGEST_TOKEN` from environment at startup (fail-fast, per ING-04 FR-6). No interactive prompt or fallback; if token missing, server exits code 2 before binding any port. Detached push process sees error at MCP call time (tool runs but returns `{success: false, error: "missing_ingest_token"}`).
  - Backend ingest endpoint is `POST /api/ingest/activity` per ADR-0013 (not `/files`). ING-04's push_activity tool sends correct path (verified in push_activity.py line 11).
- **Open**:
  - MCP server startup time: FastMCP with token validation may add latency. Story assumes server is already running (backgroundable local process). Cold start time not specified; likely <1s but unconfirmed.
  - `.harness/program.yaml` schema: ING-04 docs mention both `program.yaml` and `profile.yaml`. Story AC1 says "program.yaml", but ING-04 code uses `load_program()` which resolves `.harness/program.yaml`. Verify no drift in Copilot hook reading activity files.

### 4. Timeout & Reliability

- **Where**: `.github/hooks/harness-mcp-push.mjs` lines 22, 48-57 (TIMEOUT_MS = 15_000 = 15s total), story AC5 (NFR: 5s connect / 10s total per tool invocation)
- **What**: Copilot hook spawns MCP push as detached child; parent returns immediately (no wait). Push child has 15s wall-clock timeout on each fetch. Story specifies 5s connect + 10s total (not total 15s); contradiction in requirements.
- **Surprises**:
  - Hook timeout (15s) ≠ story NFR (5s connect / 10s total). Hook was drafted before NFR was finalized; implements best-effort 15s wall-clock limit, not the tighter per-call budget.
  - Story AC5 says "push failure never surfaces as error to Copilot Chat hook"—hook is already detached and fire-and-forget, so this is guaranteed. Push child logs to `.mcp-push.log` only (silent exit).
- **Open**:
  - If MCP server is down or slow (e.g., takes 12s to respond), push child times out at 15s and exits. Copilot Chat session is unaffected (already returned), but push is silently lost. `.mcp-push.log` records the timeout. Acceptable per story, but worth documenting in troubleshooting.
  - No retry on timeout in push hook (unlike MCP server's 3-attempt retry on network). Push hook = single attempt, fire-and-forget.

### 5. VS Code Copilot Chat Storage Model (Undocumented Integration)

- **Where**: `.github/hooks/copilot-activity.mjs` lines 68-130 (workspace hash resolution), 133-168 (journal paths)
- **What**: VS Code stores Copilot Chat sessions in `~/Library/Application\ Support/Code/User/workspaceStorage/<hash>/chatSessions/<uuid>.jsonl` and event transcripts in `GitHub.copilot-chat/transcripts/<uuid>.jsonl`. Hook resolves workspace hash by scanning `workspace.json` files for a folder URI that matches the project directory (with ancestor/descendant matching for nested repos). Longest-match wins.
- **Surprises**:
  - **Undocumented schema**: Copilot Chat JSONL structure (kind 0/1/2 snapshot/set/push, nested requests array, modelId, promptTokens, completionTokens, copilotCredits) is reverse-engineered from hook code. No Microsoft docs cover this storage format. Breaking changes possible in any Copilot or VS Code update.
  - **Opaque workspace hash**: Hash is stable per VS Code instance but not portable. If user clones repo to a different path, hash changes and old journals are orphaned. Hook gracefully exits if workspace hash not found (process.exit(0)), so data is silently skipped, not errored.
  - **Per-workspace journals**: Each VS Code workspace gets its own chatSessions directory. Multi-root workspaces may produce multiple hashes; hook picks the longest-matching folder (best-guess heuristic, not guaranteed correct).
- **Open**:
  - Hook assumes VS Code Copilot Chat is installed and has written journals. If user has never used Copilot Chat in this workspace, `chatSessions` dir does not exist → hook exits silently. No warning to user.
  - Mobile/Codespaces: hook assumes macOS / Windows / Linux local storage. GitHub Codespaces uses a different storage backend (cloud-based, not local FS). Hook will fail to locate journals in Codespaces. Limitation noted in AC but not validated in implementation.

### 6. Prior Art & Schema Drift Detection

- **Where**: `docs/activity/activity.jsonl` (live sample rows), `docs/requirements/api.md#ingest-files-api` (backend contract)
- **What**: Existing activity.jsonl rows (16 records, dated 2026-08-26 to 2026-08-27) confirm the upsert-key pattern works: rows with same `(session_id, cmd_ts)` are replaced (e.g., outcome can flip from error to completed on re-run). Sample row structure matches hook output (ts, user, session_id, cmd_ts, kind, command, feature, duration_s, outcome, intervention_count, files_created, files_modified, lines_added, tool_rejections, input_token, output_token, cache_read, cache_write, total, models{}).
- **Surprises**:
  - Existing rows are **Claude/harness-activity source**, not Copilot Chat source. All 16 rows have `command` like `/arh-init`, `/arh-scaffold`, `/arh-research`, etc. (harness commands), and `source` field **does not exist** in existing data. Hook adds `source="copilot"` but no Copilot rows yet in the file (all are from harness runs).
  - ING-02's ingest handler accepts rows with or without `source` field (Pydantic `extra="ignore"`). Adding `source="copilot"` will be accepted and stored (or silently dropped if schema is stricter on backend).
  - **Critical Discovery**: ING-02 E2E validation (per CLAUDE.md) discovered that live `activity.jsonl` uses a *harness row schema*, not the ING-02-expected schema. This was noted as `missing_required_field` rejection. Need to verify Copilot hook output passes ING-02's actual validator (not just PRD contract).
- **[RESOLVED 2026-09-15]** ING-02's `ActivityRowIn` (`services/api/app/schemas/ingest_files.py`) declares `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens` as `int | None = Field(default=None, alias="…")` — nullable, not required. Copilot rows sending `0` for cache_read/cache_write are accepted; rows omitting them are also accepted. No backend change needed.

---

## Risk Register

| # | Dimension | Severity | Description | Mitigation |
|---|-----------|----------|-------------|------------|
| 1 | Integration | HIGH | VS Code Copilot Chat journal storage schema is undocumented and reverse-engineered. Breaking changes in VS Code / Copilot releases could silently break hook (no error, just empty/stale activity log). | Add version-pinning advice to docs; implement schema version detection in hook (check journal header or field presence); add user-facing warning if no recent journals found. Monitor VS Code release notes for storage changes (monthly). |
| 2 | Integration | HIGH | MCP server must be running for push to succeed. If server is down/unreachable, push silently fails (fire-and-forget, logged to `.mcp-push.log` only). Users won't know activity didn't sync until they manually check logs. | Document expected setup: "Start MCP server before Copilot Chat sessions" in README. Add `.mcp-push.log` rotation/retention policy. Consider adding a health-check notification (e.g., "MCP server unreachable, activity may not sync") to VS Code output panel. |
| 3 | Domain | HIGH | Record key alignment: story says use `(session_id, cmd_ts)` to match `usage_events` unique constraint `(program_id, session_id, cmd_ts)`. But activity.jsonl does NOT include `program_id` in the row. Clarify: is `program_id` bound at push time only, or does hook need to compute it? | Confirm backend contract: activity.jsonl rows are program-agnostic; `program_id` is supplied by MCP tool argument. If backend enforces `program_id` in row, loop back to PR D-01 and update hook. Unit test: push activity with different program_ids, verify rows are distinguished by (program_id, session_id, cmd_ts) in backend. |
| 4 | Compatibility | MED | Copilot journal replay logic (kind 0/1/2 snapshot/set/push) is fragile. If Copilot changes event structure (add new kind, rename fields), hook silently ignores the new kind and may produce incomplete token accounting. | Document the journal codec in CLAUDE.md with a version marker (e.g., "journal version 1, Copilot Oct 2024"). Implement schema validation before replay: if unexpected kind or missing required fields, log a warning (not an error, to avoid blocking the hook). Add a test fixture that covers all three journal kinds. |
| 5 | Performance | MED | Lines-added accounting (tool.execution_start event parsing) is heuristic-based and may overcount/undercount. Tool args like `newString` are reconstructed from hook events, not actual file diffs. Edge cases: binary files, very large diffs, missing arg fields. | Document limitation in hook: "lines_added is estimated, not precise". For high-fidelity analytics, consider adding a post-processing step that validates lines_added via `git diff`. For now, accept the heuristic (similar to Claude's existing harness-activity.mjs hook). Unit test: verify line-count heuristic against known tool calls. |
| 6 | Dependency | MED | ING-05 depends on VS Code Copilot Chat being installed, configured, and actively used. If user doesn't use Copilot Chat (uses Claude Code or other extensions), no activity flows into the hook. This is by design per story, but limits adoption. | Document the scope: "ING-05 bridges VS Code Copilot Chat only; Claude Code sessions require a separate hook (not in scope)". Track feature request for Claude Code bridge as ING-06 (dependent story). |
| 7 | Compatibility | LOW | Workspace hash resolution (scanning workspaceStorage for folder match) is best-effort and may select wrong hash if multiple VS Code instances are open on different clones of the same repo. Longest-path-match heuristic is not foolproof. | Document limitation: "If multiple VS Code workspaces target the same repo, ensure the project directory env var is set correctly (preferred over heuristic scan)". Add debug output to `.mcp-push.log` showing selected workspace hash for troubleshooting. |
| 8 | Security | LOW | Hook process may be run as a Git hook (post-merge, post-rebase) without user's direct input. If attacker controls VS Code config or workspace directory, they could inject a malicious `.github/hooks/harness-mcp-push.mjs`. Mitigation is outside this story's scope (code-review discipline). | No action needed here. Assume code-review gates (PR checks, branch protection) prevent injection. Note in CONTRIBUTING.md: "All .github/hooks/* files are security-critical; require two approvals." |

---

## Pattern Map

### Existing Code to Extend

- `.github/hooks/copilot-activity.mjs` — already implements AC1 (parse journals, upsert into activity.jsonl with (session_id, cmd_ts) key). No changes needed for core logic; only edge-case handling and error resilience.
- `.github/hooks/harness-mcp-push.mjs` — already implements AC2-5 (detached spawn, MCP JSON-RPC, logging). No changes needed; only verify timeout NFR vs. hook timeout value.
- `docs/activity/.mcp-push.log` — log file for push outcomes. Exists, but needs rotation/retention policy.
- `services/mcp-server/src/agentrise_mcp/tools/push_activity.py` — ING-04 tool already POSTs to backend. No changes needed.

### Existing Patterns to Follow

- Activity.jsonl NDJSON format (append-only, upsert on key collision via line replacement) — mirror in hook.
- MCP JSON-RPC protocol (streamable HTTP, session header management, SSE parsing) — mirror in push hook.
- Fire-and-forget child process (detached, stdio to log file, no blocking) — mirror in hook spawn.
- Bearer-token auth (environment variable, fail-fast on missing, never logged) — mirror in MCP server (already done per ING-04).
- Structured logging (field allowlist, token suppression) — mirror in hook (log outcomes, not PII).

### New Files to Create

- **Test fixtures**: `.github/hooks/__tests__/copilot-activity.test.mjs` — unit test for journal parsing, line-count heuristics, upsert-key logic. Use sample journal JSONL from Copilot Chat.
- **Test fixtures**: `.github/hooks/__tests__/harness-mcp-push.test.mjs` — unit test for MCP RPC sequence, timeout handling, log file writes. Mock fetch API.
- **Integration test**: `.github/hooks/__tests__/e2e.test.mjs` — spin up local MCP server, run hook against live journals (or fixtures), verify activity.jsonl is updated and `.mcp-push.log` records success/failure.
- **Documentation**: `docs/activity/README.md` — explain activity.jsonl schema, hook behavior, troubleshooting (e.g., "No activity appearing? Check workspace hash in hook debug output").
- **Documentation**: `docs/activity/HOOK-SETUP.md` — installation / configuration steps for VS Code Copilot Chat integration (e.g., "Install Copilot Chat extension, configure MCP server env var, run hook on session end").

### Shared Code at Risk

- `.harness/program.yaml` — MCP server reads this file to locate activity sources. If schema changes (e.g., files→sources), ING-04's push_activity breaks. ING-05's hook doesn't read this directly, but depends on ING-04's reading being correct.
- `docs/activity/activity.jsonl` — upsert key logic (replace on session_id + cmd_ts match) is shared between Copilot hook and existing harness-activity.mjs. If logic diverges, rows may duplicate or conflict. Recommend consolidating upsert logic into a shared module (e.g., `docs/activity/upsert.mjs`).
- `docs/state/features.json` — hook does not touch this; but if activity pipeline is broken, feature state may not advance (e.g., impl phase doesn't auto-bump because activity ingest failed). No direct risk, but dependency chain.

### Resolutions (all closed 2026-09-15)

- **[RESOLVED: Schema alignment on `program_id`]** — `services/api/app/schemas/ingest_files.py::ActivityRowIn` declares `program_id: str = Field(..., ...)` (**required**). The service also enforces envelope↔row match and emits `program_id_mismatch` on drift. `copilot-activity.mjs` must set `program_id` on every emitted row, sourced from `HARNESS_PROGRAM_ID` env → else `.harness/program.yaml → programId`. This is the root cause of the 141× `missing_required_field` seen during ING-04's live E2E; PLAN must add this write and a fixture test. Not a code redesign — a single field addition in `copilot-activity.mjs`.
- **[RESOLVED: Copilot journal backward compatibility]** — No upstream (Microsoft) versioning contract exists. Accept a best-effort codec strategy: pin the known kind set `{0, 1, 2}`, treat any other kind as "unknown, skip and continue," never abort the batch. Add a `JOURNAL_CODEC_VERSION` module constant in `copilot-activity.mjs` (start at `"1"`) so any future schema break is traceable via a single grep, and log `journal_codec_unknown_kind` once per session-end to `.mcp-push.log` when it fires. No rejection of the entire journal.
- **[RESOLVED: `cache_read` / `cache_write` accounting]** — Both are nullable `int | None` on `ActivityRowIn`. Hook already emits `0`; that is accepted. Doc string on the emitted row keeps the "not measurable from Copilot journals" note. No code change.
- **[RESOLVED: Feature ETL ID parsing]** — Backend `ActivityRowIn.feature` is `str | None = Field(default=None)`. Canonical hook behaviour: match `^/\S+\s+([A-Z]{2,4}-\d+)\b` against the command text (bare-token positional argument only). Anything else (including `--feature <id>`) → emit `feature=null`. Nulls are accepted and correctly indexed. Enshrined in the ING-05 hook's unit-test fixture list.
- **[RESOLVED: Timeout & retry on MCP push]** — Bind to the story NFR: **10 s total per JSON-RPC call**, no retry (single attempt). Node `fetch` + `AbortController` gives one wall-clock budget only, so the story's "5 s connect + 10 s total" splits into a single 10 s ceiling; document this in the hook's decision log. Retry is forbidden because AC-2 mandates fire-and-forget non-blocking behaviour (a retry loop would violate that). Current `TIMEOUT_MS = 15_000` in `harness-mcp-push.mjs` is drifted; PLAN must reduce it to `10_000` and add a unit test asserting the abort fires by 10.5 s.

---

## Scoring Rubric (5-Dimension)

### Feasibility (Score: 80/100)

**Rationale**: Core integration points are already implemented (hooks exist, MCP server exists, activity.jsonl exists). No new frameworks, no database migrations, no external API integrations beyond the already-working MCP server. However, journal parsing is fragile (undocumented Copilot schema), and workspace hash resolution is heuristic-based.

**Breakdown**:
- Core logic (journal parsing, upsert, MCP call): PROVEN (hook already runs, produces records) → 90/100
- Schema alignment (activity.jsonl vs usage_events): PROVEN for harness-activity rows (16 live rows in file), UNPROVEN for Copilot rows (no validation yet, ING-02 schema drift noted) → 60/100
- VS Code integration (journal discovery, workspace hash): HEURISTIC (best-effort path scanning, opaque hash), not guaranteed → 70/100
- **Average**: (90 + 60 + 70) / 3 = **80/100**

### Complexity (Score: 65/100)

**Rationale**: Hook code is already written (copilot-activity.mjs, harness-mcp-push.mjs), so implementation complexity is LOW. But integration complexity is MEDIUM (two-layer journal codec, workspace hash scanning, detached process management, log file handling). Testing complexity is MEDIUM-HIGH (mocking fetch, simulating Copilot Chat journal structure, e2e with live MCP server).

**Breakdown**:
- Code to write: ZERO (already written) → 95/100
- Code to test: NEW (no existing unit/integration tests for hooks) → 50/100
- Edge cases to handle: MULTIPLE (missing journals, workspace hash mismatches, MCP server down, timeout, malformed NDJSON) → 55/100
- **Average**: (95 + 50 + 55) / 3 = **66/100**, rounded to **65/100**

### Risk (Score: 45/100)

**Rationale**: High-risk integration surface (Copilot Chat undocumented schema, MCP server availability, async fire-and-forget with no retry, silent failure modes). Multiple HIGH-severity risks in the register (journal schema drift, MCP dependency, schema alignment).

**Breakdown**:
- Integration risk (Copilot Chat, MCP server): HIGH (4 risks) → 35/100
- Data loss risk (silent failure, no retry, no alerting): HIGH → 40/100
- Debugging difficulty (fire-and-forget, log-file-based observability): MEDIUM → 55/100
- **Average**: (35 + 40 + 55) / 3 = **43/100**, rounded to **45/100**

### Contract Fit (Score: 70/100)

**Rationale**: Story ACs are mostly satisfied by existing hook implementations. Timeout NFR (10 s total per RPC) will be aligned in PLAN (hook currently at 15 s wall-clock). Schema alignment on activity.jsonl (row-level `program_id`) resolved 2026-09-15: `ActivityRowIn` requires row-level `program_id`; hook must emit it (single-field addition). MCP tool contract (push_activity signature, result envelope) is frozen and satisfies AC3.

**Breakdown**:
- AC1 (parse journals, upsert): SATISFIED (hook does this) → 95/100
- AC2 (detached spawn): SATISFIED (hook does this) → 95/100
- AC3-5 (MCP protocol, logging): SATISFIED (hook does this, MCP server contract satisfied) → 90/100
- NFR (timeout budget): PARTIAL (15s ≠ 5s+10s) → 60/100
- Schema alignment: UNPROVEN (activity.jsonl keys match, but program_id placement ambiguous) → 50/100
- **Average**: (95 + 95 + 90 + 60 + 50) / 5 = **78/100**, rounded to **70/100** (adjust down for ambiguity)

### Effort (Score: 75/100)

**Rationale**: Implementation effort is LOW (code already written, no new services, no database migrations). Validation effort is MEDIUM (need to test against live Copilot Chat journals, spin up MCP server, verify ingest pipeline). Documentation effort is MEDIUM (explain hook setup, troubleshoot guide, edge cases).

**Breakdown**:
- Code implementation: ZERO (ready-to-merge) → 100/100
- Unit test coverage (new fixtures, mocks): 4-6 hours → 65/100
- Integration test (e2e with live MCP): 3-4 hours → 60/100
- Documentation (setup guide, schema docs): 2-3 hours → 70/100
- **Average**: (100 + 65 + 60 + 70) / 4 = **73/100**, rounded to **75/100**

### Rollup Score

**Formula**: (Feasibility × 0.2) + (Complexity × 0.15) + (Risk × 0.25) + (Contract × 0.25) + (Effort × 0.15)

= (80 × 0.2) + (65 × 0.15) + (45 × 0.25) + (70 × 0.25) + (75 × 0.15)
= 16 + 9.75 + 11.25 + 17.5 + 11.25
= **65.75** → **66/100**

---

## Verdict

**GO-WITH-CONDITIONS**

**Rationale**: 
- Core integration is proven (hooks and MCP server exist and run).
- Implementation is near-complete; only test coverage and edge-case validation needed.
- High-risk integration surface (undocumented Copilot Chat schema, fire-and-forget push) requires explicit mitigations and monitoring.
- Three HIGH-severity clarifications must be resolved before merging (schema alignment, journal versioning, timeout NFR).
- Recommend: proceed with code merge after test coverage is added and clarifications are addressed. Plan post-launch monitoring (`.mcp-push.log` audit, activity.jsonl row volume tracking, schema drift detection).

**Conditions**:
1. Add row-level `program_id` to every emitted activity row in `copilot-activity.mjs` (sourced from `HARNESS_PROGRAM_ID` env → `.harness/program.yaml → programId`). This is the root cause of the ING-04 live-E2E 141× `missing_required_field` rejection; PLAN must include this write + a fixture test.
2. Add unit test coverage for copilot-activity.mjs (journal parsing, line-count heuristics, upsert-key logic) with fixtures covering all three journal kinds.
3. Add unit test coverage for harness-mcp-push.mjs (JSON-RPC handshake, timeout handling, log file writes) with mocked fetch.
4. Clarify timeout NFR: is 5s connect / 10s total per-call binding, or is 15s wall-clock acceptable? Update hook or story decision log accordingly.
5. Document VS Code Copilot Chat setup in README (extension install, MCP server config, MCP_URL env var, troubleshooting).
6. Add `.mcp-push.log` rotation / retention policy (e.g., "keep last 100 lines, rotate weekly").
7. Run E2E validation: real Copilot Chat session end → verify activity.jsonl is updated → verify `.mcp-push.log` records push outcome → verify backend ingest (via dashboard or API query).

---

## Top Risks (Severity-Ranked)

1. **HIGH — Copilot Chat journal schema backward-compatibility**: Undocumented, reverse-engineered storage format is susceptible to breaking changes. Hook silently fails (no error, just empty activity log). → Mitigation: schema version detection, user warnings, release-note monitoring.
2. **HIGH — MCP server availability**: Push silently fails if server is down. No retry, no alerting to user. → Mitigation: health-check docs, log rotation, consider VS Code status notification.
3. **HIGH — Schema alignment ambiguity**: program_id placement unclear (activity.jsonl row vs. MCP push argument). May cause rows to be rejected or misattributed. → Mitigation: backend contract clarification, unit test with multiple program_ids.

---

## Top Recommendations

1. **Test-first validation**: Write unit tests for both hooks before merging. Fixtures: sample Copilot Chat JSONL (all three journal kinds), MCP RPC response variations, timeout scenarios. This will shake out the edge cases (missing fields, malformed lines, workspace hash mismatches) early.
2. **Schema validation E2E**: Run real Copilot Chat session end against live MCP server + backend ingest. Verify `activity.jsonl` row is created, MCP push succeeds, and row appears in backend `usage_events` table via dashboard/API. This closes the gap between hook output and backend ingestion.
3. **Documentation & troubleshooting guide**: Write HOOK-SETUP.md covering (a) VS Code Copilot Chat extension install, (b) MCP server setup (env var, startup), (c) expected activity.jsonl updates, (d) how to read `.mcp-push.log` for failures. This reduces support burden and unblocks users.

---

## Open Clarifications (Count: 0)

All five clarifications resolved 2026-09-15 against verified evidence in `services/api/app/schemas/ingest_files.py` and the shipped hook code. Resolutions are inline in § Prior Art & Schema Drift Detection and § Pattern Map → Resolutions. Each resolution promotes an implementation directive that PLAN must pick up:

1. **program_id on every row** — `copilot-activity.mjs` writes `program_id` from `HARNESS_PROGRAM_ID` env → `.harness/program.yaml`. Root cause of ING-04's live-E2E 141× `missing_required_field`.
2. **Journal codec version constant** — `JOURNAL_CODEC_VERSION = "1"`; unknown kinds skipped + logged once, batch never aborted.
3. **cache_read/write = 0** — accepted as-is (backend nullable).
4. **feature parsing** — bare-token positional only; anything else → `null`.
5. **MCP push timeout** — `TIMEOUT_MS` reduced from 15 s → 10 s, single attempt, no retry.

Certified for `/arh-plan-requirements ING-05`.
