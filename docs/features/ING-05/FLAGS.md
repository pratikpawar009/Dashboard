# FLAGS — ING-05

Engineer-facing observations queued by implementation-agent workers. Run `/arh-human-review ING-05` to triage.


### AF-01: risky-pattern (T-01)

- **source**: `.github/hooks/copilot-activity.mjs:659-661`
- **summary**: SPAWN_ERROR and OUTER_ERROR (pre-ING-05 events) were converted to structured `writeLog('spawn_error'|'outer_error', {error_code})` for uniformity per F-01(g). These two event names are NOT in DATA-DESIGN.md § 1 enum (which lists success/http_error/timeout/network_error/program_id_unresolved/journal_codec_unknown_kind/mcp_url_non_loopback). If enum is strictly authoritative, either extend the enum or drop these emit points.
- **status**: acknowledged
- **triaged_at**: 2026-09-15T05:19:40Z
- **triage_verdict**: informational — accepted; no source change required
- **raised_at**: 2026-09-15T04:07:31Z

### AF-02: inconsistency (T-01)

- **source**: `.github/hooks/copilot-activity.mjs:79` (regex `^\s*(program_id|programId)\s*:\s*(.+?)\s*$`)
- **summary**: F-01.reason specifies the hand-rolled YAML scan regex with leading `\s*`, tolerating indented keys — this would match nested (non-top-level) `program_id` entries in a multi-doc yaml. profile.py uses `yaml.safe_load` (top-level only). Low-risk for current single-doc flat program.yaml, but worth pinning if program.yaml is ever nested.
- **status**: acknowledged
- **triaged_at**: 2026-09-15T05:19:40Z
- **triage_verdict**: informational — accepted; no source change required
- **raised_at**: 2026-09-15T04:07:31Z

### AF-03: risky-pattern (T-03)

- **source**: `.github/hooks/__tests__/fixtures/transcript.jsonl:6`
- **summary**: F-06 spec conflict — user directive listed transcript events with numeric ms timestamps, `sessionId`, `parentId`, `commandTs`, `duration_ms` + `evt-NNN` chaining, but the hook actually reads `type` + ISO-string `timestamp` + `data.content` / `data.toolCallId` (none of the above). Implemented per PLAN.md F-06 verbatim (5 canonical events with ISO timestamps) + appended one `session.end` line to satisfy ≥6-line check. If T-04/F-03 tests assume the user-directive shape, this fixture needs a revisit.
- **status**: acknowledged
- **triaged_at**: 2026-09-15T05:19:40Z
- **triage_verdict**: informational — accepted; no source change required
- **raised_at**: 2026-09-15T04:07:31Z


### AF-04: risky-pattern (T-04)

- **source**: `.github/hooks/__tests__/copilot-activity.test.mjs:407-490` (sub-test h)
- **summary**: Sub-test (h) originally attempted to intercept `spawn` via a `--import` preload that monkey-patched `node:child_process`'s ESM namespace, but the hook's `const { spawn } = await import("node:child_process")` binds the static named export at link time, so in-process mutation is invisible. Fell back to a behavioural check (parent-exit budget < 1.5s, `ps -o pgid=` for process-group leadership, `fstatSync(0).isCharacterDevice()` for `stdio[0]==='ignore'`). Contract is proven, but `child.unref()` cannot be asserted directly — only inferred from the fast-parent-exit signal.
- **status**: acknowledged
- **triaged_at**: 2026-09-15T05:19:40Z
- **triage_verdict**: informational — accepted; no source change required
- **raised_at**: 2026-09-15T04:58:48Z

### AF-05: risky-pattern (T-04)

- **source**: `.github/hooks/__tests__/copilot-activity.test.mjs:407-490` (sub-test h)
- **summary**: The (h) test uses POSIX-only signals (`ps -o pgid=` and `S_IFCHR` for `/dev/null`). It will silently fail on Windows. Given CLAUDE.md's local-dev + macOS/Linux posture and `CI: none`, acceptable but worth pinning as a documented limitation.
- **status**: acknowledged
- **triaged_at**: 2026-09-15T05:19:40Z
- **triage_verdict**: informational — accepted; no source change required
- **raised_at**: 2026-09-15T04:58:48Z

### AF-06: inconsistency (T-07)

- **source**: `docs/features/ING-05/REQUIREMENTS.md:66` and `docs/features/ING-05/DECISIONS.md` D-01
- **summary**: PRD § Scope and D-01 reference the Claude Code activity hook as `.github/hooks/harness-activity.mjs`; the actual file lives at `.claude/hooks/harness-activity.mjs` (verified via `.claude/settings.json` hook wiring). The how-to (T-07 output) uses the correct `.claude/hooks/` path; PRD/DECISIONS carry the drift. Low-impact today (only cited in prose, no code depends on the wrong path), but a future reader will fail to find the file.
- **status**: acknowledged
- **triaged_at**: 2026-09-15T05:19:40Z
- **triage_verdict**: informational — accepted; no source change required
- **raised_at**: 2026-09-15T04:58:48Z

### AF-07: risky-pattern (T-05)

- **source**: `.github/hooks/__tests__/harness-mcp-push.test.mjs` (sub-test a)
- **summary**: AC-4 verified via source-file regex grep of the default URL literal rather than by exercising the module — the push module auto-runs main() at import and exposes no exports, so no in-process constant read is possible without spawning a full run against port 3010 (which would collide with a locally running MCP dev server). Regex asserts both positive (127.0.0.1:3010) and negative (no 'localhost'), but a rename of the env var or the `||` fallback expression would evade both patterns.
- **status**: acknowledged
- **triaged_at**: 2026-09-15T05:19:40Z
- **triage_verdict**: informational — accepted; no source change required
- **raised_at**: 2026-09-15T04:58:48Z


<!-- All flags AF-01..AF-07 triaged 2026-09-15T05:19:40Z — batch verdict: acknowledged, informational, no source change -->
