# Story: ING-05 — Copilot Chat activity-hook bridge

**Epic**: ING
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#44 (https://github.com/pratikpawar009/Dashboard/issues/44)

## User story

As a developer using VS Code Copilot Chat (not Claude Code), I want my Copilot Chat slash-command sessions to flow into the same activity pipeline automatically, so that my usage shows up on the dashboard without me running any manual ingestion step.

## Acceptance criteria

1. Given a VS Code Copilot Chat slash-command session ends (`sessionEnd`/`Stop` event fires), when `copilot-activity.mjs` runs, then it parses the local chat-session + transcript journals and appends/upserts one JSON record — keyed by `session_id`+`cmd_ts`, matching `usage_events`' unique constraint (per `docs/requirements/data.md#db-schema`) — into `docs/activity/activity.jsonl`, containing per-command duration, intervention count, files created/modified, lines added, tool rejections, outcome, and per-model token aggregates.
2. Given the `docs/activity/activity.jsonl` record has been written, when `copilot-activity.mjs` completes, then it spawns `harness-mcp-push.mjs` as a **detached** process and returns without waiting on it (the calling hook is never blocked by the push).
3. Given `harness-mcp-push.mjs` runs, when it pushes the freshly written activity, then it speaks the MCP streamable-HTTP JSON-RPC protocol against `HARNESS_MCP_URL` in the sequence `initialize` → `notifications/initialized` → `tools/call push_activity` (per the `mcp-tools` contract, `docs/requirements/api.md#mcp-tools`) → `DELETE`.
4. Given `HARNESS_MCP_URL` is not set in the environment, when `harness-mcp-push.mjs` runs, then it defaults to `http://127.0.0.1:3010/mcp` (IPv4 loopback, deliberately not `localhost`, to avoid Windows IPv6-resolution failures).
5. Given the MCP push either succeeds or fails (network error, non-2xx, timeout), when `harness-mcp-push.mjs` finishes, then it logs the outcome to `docs/activity/.mcp-push.log` and exits without raising — a push failure never surfaces as an error to the Copilot Chat hook that spawned it.

## Non-functional requirements

- Performance: every `harness-mcp-push.mjs` HTTP call (`initialize`, `tools/call`, `DELETE`) is bounded by an explicit 5s-connect / 10s-total timeout — assumption, PRD specifies "best-effort" and non-blocking behavior but no numeric budget; per `.claude/rules/performance-baseline.md` ("I/O has explicit timeouts. No silent infinite waits.") a bound is required regardless.
- Security: no bearer token or credential lives in this hook — `push_activity` on the MCP server (ING-04) owns the ingest token stored in the local MCP env file; `harness-mcp-push.mjs` only talks to the local MCP server over loopback (per PRD §"Developer pushing local AI activity" flow).
- Accessibility: N/A — background Node hook script, no UI surface.
- Observability: every session-end event produces one line in `docs/activity/.mcp-push.log` recording the push outcome (success/failure/timeout) (per FR-ING-07, AC-5 above).

## Dependencies

- Upstream: ING-04 via `mcp-tools` contract (`docs/requirements/api.md#mcp-tools`) — invokes the `push_activity` tool exposed by the local MCP server (`services/mcp-server`, FastMCP streamable HTTP, default `0.0.0.0:3010`, path `/mcp`).
- Downstream: none.

## Test mapping

- E2E: NA — no UI; hook is triggered by VS Code Copilot Chat lifecycle events, not a browser flow.
- Unit: `.github/hooks/copilot-activity.mjs` (journal parsing, append/upsert keyed by `session_id`+`cmd_ts`), `.github/hooks/harness-mcp-push.mjs` (JSON-RPC handshake sequence, default-URL fallback, timeout, best-effort/non-blocking exit).
- Manual: trigger a real Copilot Chat session end against a running local MCP server; confirm `docs/activity/activity.jsonl` is updated and `docs/activity/.mcp-push.log` records the push outcome — VS Code Copilot Chat lifecycle events cannot be simulated by CI tooling (CI: none, per `CLAUDE.md`).

## Clarifications

## Decision log

- 2026-08-26 Record key: `session_id`+`cmd_ts` (per FR-ING-07, matching `usage_events`' unique constraint in `docs/requirements/data.md#db-schema`).
- 2026-08-26 MCP push HTTP timeout: 5s connect / 10s total — assumption, PRD gives no numeric budget; sized to keep the detached push process from hanging, per `.claude/rules/performance-baseline.md`.
- 2026-08-26 Default `HARNESS_MCP_URL`: `http://127.0.0.1:3010/mcp` (per FR-ING-07, PRD explicitly names this default and the IPv4-over-Windows-IPv6 rationale).
- 2026-08-26 No auth/token handling in this story's files — assumption, per PRD's "Developer pushing local AI activity" flow, which places ingest-token custody on the MCP server (ING-04), not the hook bridge.
