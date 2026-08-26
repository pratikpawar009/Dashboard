# Story: ING-04 — MCP server tool exposure (push_activity / push_artifacts)

**Epic**: ING
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#43 (https://github.com/pratikpawar009/Dashboard/issues/43)

## User story

As a developer running Claude Code (or another MCP-capable client) locally, I want an MCP
server exposing `push_activity` and `push_artifacts` tools, so that I can push my local AI
activity and artifact counts into the platform without a central data-engineering dependency.

## Acceptance criteria

1. Given the MCP server is started (`python -m agentrise_mcp.server` or the `agentrise-mcp`
   console script), when a client connects, then it exposes exactly two tools —
   `push_activity(program_id?, workspace_root?)` and `push_artifacts(program_id?,
   workspace_root?)` — over FastMCP streamable HTTP at path `/mcp`, default bind
   `0.0.0.0:3010` (FR-ING-01, `mcp-tools` contract).
2. Given `.harness/profile.yaml`'s `files:` entries (`kind: activity`), when `push_activity`
   runs, then it parses each file as NDJSON (skipping blank/malformed lines), batches rows 500
   per request, and POSTs each batch as `{program_id, kind:"activity", rows}` to
   `POST /api/ingest/files` with the configured bearer token (per the `ingest-files-api`
   contract, `docs/requirements/api.md#ingest-files-api`), returning a result with
   `files_read`, `rows_read`, `batches`, `inserted`, `skipped_duplicate`, `rejected`, `rollups`
   (FR-ING-02).
3. Given the `artifacts:` block of `.harness/profile.yaml` (source kinds `glob-count`,
   `json-key-count`, `json-field-sum`, `constant`), when `push_artifacts` runs, then it resolves
   each entry to an integer count against the local filesystem and POSTs
   `{program_id, kind:"artifacts", counts, as_of}` to `POST /api/ingest/artifacts` with the
   configured bearer token (per the `ingest-artifacts-api` contract,
   `docs/requirements/api.md#ingest-artifacts-api`), returning a push-artifacts result
   (FR-ING-03).
4. Given `workspace_root` is supplied to either tool, when it runs, then `.harness/profile.yaml`
   and every relative path inside it are resolved against `workspace_root` instead of the
   server process's current working directory.
5. Given the ingest endpoint responds `401` (missing/revoked/expired bearer) or `403` (target
   `program_id` not in the token's `allowed_program_ids`, no wildcard) — per the
   `ingest-token-auth` contract underlying both ingest endpoints — when either tool receives
   that response, then it surfaces the failure in its returned result (no rows/counts reported
   as inserted) instead of raising an unhandled exception to the MCP client.
6. Given no ingest bearer token is configured in the local MCP environment, when either tool is
   invoked, then it fails fast with a client-side error before attempting any HTTP call to the
   ingest API.

## Non-functional requirements

- Performance: every ingest POST from either tool is bounded by an explicit 5s-connect /
  30s-total timeout, with up to 3 retry attempts using exponential backoff + jitter on
  network-level failures (not on 4xx responses) — assumption; the PRD gives no numeric budget
  for MCP→ingest calls, but `.claude/rules/performance-baseline.md` ("I/O has explicit
  timeouts...", "Every retry has bounded attempts and exponential backoff with jitter")
  requires a bound regardless (see Decision log).
- Security: the ingest bearer token is read from the local MCP env file only (per PRD "Local
  MCP env file (raw ingest token...)", confirmed in ING-05's Decision log as owned by this
  story), never logged, and never echoed back in a tool's returned result.
- Accessibility: N/A — headless local MCP server, no UI surface.
- Observability: each tool invocation logs its outcome (success/partial/failure, row/count
  totals, HTTP status) to the server process's stdout/stderr via Python `logging` — assumption;
  the PRD's NFR-011 structured-event set is backend-RBAC-specific and does not name an
  MCP-tool-invocation event (see Decision log).

## Dependencies

- Upstream: ING-02 via `ingest-files-api` contract (`docs/requirements/api.md#ingest-files-api`)
  — `push_activity` POSTs to `POST /api/ingest/files`; ING-03 via `ingest-artifacts-api`
  contract (`docs/requirements/api.md#ingest-artifacts-api`) — `push_artifacts` POSTs to
  `POST /api/ingest/artifacts`. Both are contract dependencies (buildable against stubs), not
  sibling code.
- Downstream: ING-05 consumes this story's `mcp-tools` contract
  (`docs/requirements/api.md#mcp-tools`) to bridge Copilot Chat sessions into the same pipeline.

## Test mapping

- E2E: NA — no UI; headless local tool, exercised indirectly via ING-05's manual Copilot-bridge
  check.
- Unit: `services/mcp-server/src/agentrise_mcp/server.py` (tool registration, transport/bind
  config), `services/mcp-server/src/agentrise_mcp/tools/push_activity.py` (NDJSON parsing,
  batching, result shape), `services/mcp-server/src/agentrise_mcp/tools/push_artifacts.py`
  (count resolution per source kind, result shape) — auth-failure surfacing and missing-token
  fail-fast paths for both tools.
- Manual: run the MCP server locally against a running (or stubbed) backend; invoke
  `push_activity`/`push_artifacts` via an MCP client and confirm the returned result matches a
  known local `.harness/profile.yaml` fixture — no e2e framework is configured
  (`test_e2e` empty in `docs/config/project-commands.yaml`) and CI is `none` (per `CLAUDE.md`).

## Clarifications

## Decision log

- 2026-08-26 Ingest-call timeout/retry budget: 5s connect / 30s total, 3 retries with
  exponential backoff + jitter on network failures only — assumption; PRD gives no numeric
  budget for this call, sized to keep a multi-batch `push_activity` run bounded, per
  `.claude/rules/performance-baseline.md`.
- 2026-08-26 Missing-token fail-fast behavior: tool returns a client-side error before any HTTP
  attempt — assumption; PRD documents the local-env-file token model (see PRD "Local MCP env
  file" data-classification row) but not this specific failure-path behavior.
- 2026-08-26 Observability: tool-invocation outcomes logged to stdout/stderr via Python
  `logging`, no dedicated event name — assumption; NFR-011's named event set is backend-RBAC
  specific and doesn't cover MCP-tool invocations.
- 2026-08-26 Unit-test paths use `services/mcp-server/src/agentrise_mcp/...` (PRD §6/§8.1
  Source-column path for the carried-over MCP server), not `services/api` — this component is
  a separate local service from the FastAPI backend scaffolded at `services/api`.
