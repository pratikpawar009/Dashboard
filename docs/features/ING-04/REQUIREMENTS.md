---
feature_id: ING-04
title: MCP server tool exposure (push_activity / push_artifacts)
story_id: ING-04
tracker_story: pratikpawar009/Dashboard#43
tracker_research: pratikpawar009/Dashboard#303
author: product-spec-agent
date: 2026-09-14
status: Draft
---

# Feature: ING-04 — MCP server tool exposure (push_activity / push_artifacts)

## Problem

Individual contributors (developers) running Claude Code / Cursor / other MCP-capable clients on their own machines have no thin, standardised way to push local AI activity rows (`.harness/program.yaml::files[]`) and governance-artifact counts (`.harness/program.yaml::artifacts{}`) into the platform. ING-02 (`POST /api/ingest/activity`) and ING-03 (`POST /api/ingest/artifacts`) are live on `main` (PRs #296, #302; commits `615df21`, `3bcb944`) — the ingest side is done — but nothing calls them from a developer's laptop. Without a per-developer producer, the dashboard's activity and governance-count panels stay empty for actual local work, and downstream ING-05's Copilot-Chat bridge has no `mcp-tools` contract to plug into.

## Outcome

A separately-deployable local Python service `services/mcp-server/` (package `agentrise_mcp`, exposed via FastMCP streamable HTTP on `0.0.0.0:3010`, path `/mcp`) exposes exactly two MCP tools — `push_activity(program_id?, workspace_root?)` and `push_artifacts(program_id?, workspace_root?)`. Each tool reads the committed `.harness/program.yaml`, resolves either `files[]` (activity, NDJSON) or `artifacts{}` (governance counts across 5 canonical types) against a supplied `workspace_root`, and POSTs the frozen envelope to the live ingest endpoints with the developer's bearer token — bounded timeout, bounded retries, no unhandled exceptions to the MCP client, no token or PII in logs. The `mcp-tools` contract (`docs/requirements/api.md#mcp-tools`) is fulfilled, unblocking ING-05.

## Constraints

- **Endpoint URLs are fixed by ADR-0013** — the shipped routes are `POST /api/ingest/activity` and `POST /api/ingest/artifacts`, both served by the generic `POST /api/ingest/{kind}` handler in `services/api/app/api/ingest.py`. The URL path `{kind}` and the envelope `kind` field MUST agree; disagreement is rejected 400 `unknown envelope kind` at the router tier, before auth. Every prior story reference to `POST /api/ingest/files` is stale (see § Open questions → Resolved).
- **YAML source of truth** — `.harness/program.yaml` is the ONLY source for `files[]` and `artifacts{}` (see § Open questions → Resolved / R-04). `.harness/profile.yaml` is a local, gitignored identity file (email, name, role); it MUST NOT be treated as a fallback source for activity or artifact data.
- **Contracts consumed (both frozen, live on `main`)** — `docs/requirements/api.md#ingest-files-api` (activity branch, `IngestFilesResponse` shape) and `docs/requirements/api.md#ingest-artifacts-api` (`IngestArtifactsResponse` shape). Auth per `docs/requirements/api.md#ingest-token-auth` (bearer, program-scope via token's `allowed_program_ids`).
- **Contract produced** — `docs/requirements/api.md#mcp-tools`, consumed by ING-05.
- **Framework choice fixed** — standalone `fastmcp` PyPI package (`jlowin/fastmcp`, v2.x; https://pypi.org/project/fastmcp/). NOT `fastapi-mcp` (FastAPI plugin) and NOT Anthropic's low-level `mcp` SDK. Provides `@server.tool()` decorator + streamable HTTP transport out of the box (see § Open questions → Resolved / C-01).
- **Deployment topology** — `services/mcp-server/` is a separately-deployed sibling service to `services/api/`. Own `pyproject.toml`, own tests, own commands, own deploy pipeline. It MUST NOT be wired into the root `docs/config/project-commands.yaml::preflight` of the main API. Any `mcp_server:*` namespace in the root commands file is optional and out of scope for this PRD (defer to PLAN — see § Open questions → Resolved / D-01).
- **Row-cap upstream (informational)** — the backend router enforces a 5000 rows/request cap on `POST /api/ingest/activity` (413 before DB work); the MCP batch cap MUST stay well below this.
- Research verdict: **GO-WITH-CONDITIONS** (75/100) — all four conditions addressed in § Addressing Research Conditions below.

## Solution sketch

Scaffold `services/mcp-server/` as a Python package with entry point `python -m agentrise_mcp.server` and console script `agentrise-mcp`. Register two `@server.tool()`-decorated functions using `fastmcp`; expose over streamable HTTP on `0.0.0.0:3010` at path `/mcp`. On invocation each tool reads `.harness/program.yaml` (resolved under `workspace_root` or the process CWD), guards the bearer token (fail-fast if missing), then dispatches by tool:

- `push_activity`: for each `files[]` entry, stream the NDJSON file, skip blank/malformed lines, batch rows at **500 per HTTP POST**, and POST `{program_id, kind:"activity", rows}` to `POST /api/ingest/activity`. Aggregate the per-batch `IngestFilesResponse` counts into a single tool result (`files_read, rows_read, batches, inserted, skipped_duplicate, rejected, rollups`). Note: the backend service's internal 2730-row per-INSERT chunk (`activity_ingest._MAX_ROWS_PER_INSERT`) is unrelated to the MCP batch cap — that is the DB batch size, not the HTTP one.
- `push_artifacts`: resolve each `artifacts{}` entry to an integer via one of four source kinds (`glob-count`, `json-key-count`, `json-field-sum`, `constant`) against the local filesystem, assemble a single `counts` dict, and POST `{program_id, kind:"artifacts", counts, as_of}` to `POST /api/ingest/artifacts` in ONE HTTP call (no batching — 5 canonical types max).

Both tools share one `httpx.AsyncClient` wrapper configured with an explicit 5s-connect / 30s-total timeout and a `retry_with_backoff(max_retries=3)` helper (exponential + jitter on network-level failures only, never on 4xx). Bearer token is loaded once at process start from an env-var and never surfaces in logs or tool return dicts. Auth failures (401/403) are captured into the tool result envelope (`{success: false, error, http_status, ...}`) rather than raised. Structured Python `logging` writes to stdout/stderr with a fixed field allowlist per event.

## Addressing Research Conditions

Verdict: `GO-WITH-CONDITIONS`. Conditions from `docs/research/ING-04.md` § Verdict → Conditions, each with concrete mitigation in this PRD:

- **C-1 — Resolve FastMCP library choice (C-01)** — RESOLVED. Standalone `fastmcp` PyPI package (`jlowin/fastmcp`, v2.x) is pinned in § Constraints. PLAN pins the exact version in `services/mcp-server/pyproject.toml`; code review verifies entry point (`python -m agentrise_mcp.server`) and console script (`agentrise-mcp`) both boot the FastMCP streamable-HTTP server on `0.0.0.0:3010` at `/mcp` (ING-04-FR-1).
- **C-2 — Decide YAML layout (R-04)** — RESOLVED as single-source. `.harness/program.yaml` is the ONLY source for `files[]` and `artifacts{}` (§ Constraints). `.harness/profile.yaml` is IDENTITY ONLY. AC-2/AC-3 wording in the story text is stale (pre-ING-10) and corrected here in ING-04-FR-2 and ING-04-FR-3. No dual-layout branching in the tool — a fallback is explicitly out of scope.
- **C-3 — Explicit glob / JSON-key allowlist rules (R-06)** — ADDRESSED in this PRD as first-class FRs (ING-04-FR-7 for glob patterns, ING-04-FR-8 for JSON key/field names). PLAN cannot silently drop them because they trace 1:1 to their own FR ids and belong to the security-baseline scope.
- **C-4 — Add MCP service to build config** — NOT taken. Superseded by the D-01 decision recorded in `docs/features/ING-04/state.json`: `services/mcp-server/` is a separately-deployed sibling service and MUST NOT be wired into the main API's `docs/config/project-commands.yaml::preflight`. PLAN may add an optional `mcp_server:*` namespace to the root commands file, but that is a PLAN-level decision, not a PRD requirement.

## Scope

- **In**:
  - New Python service `services/mcp-server/` (package `agentrise_mcp`) with own `pyproject.toml` pinning `fastmcp`, `httpx`, `pyyaml`.
  - Entry point `python -m agentrise_mcp.server` and console script `agentrise-mcp`.
  - FastMCP streamable-HTTP server bound to `0.0.0.0:3010` at path `/mcp`, exposing exactly two tools: `push_activity(program_id?, workspace_root?)`, `push_artifacts(program_id?, workspace_root?)`.
  - YAML reader for `.harness/program.yaml` (`files[]`, `artifacts{}`) resolved against a supplied `workspace_root` (defaults to process CWD).
  - NDJSON parser + 500-row batcher for `push_activity`.
  - Four artifact source-kind resolvers for `push_artifacts` (`glob-count`, `json-key-count`, `json-field-sum`, `constant`).
  - Explicit input-validation allowlist for glob patterns and JSON key/field names (ING-04-FR-7, ING-04-FR-8).
  - `httpx` client wrapper with 5s connect / 30s total timeout and 3-attempt exponential-backoff-with-jitter retry on network failures only.
  - Bearer-token guard: env-var read at process start, missing-token → fail-fast client-side error before any HTTP call; token never logged or echoed.
  - Auth-failure surfacing: 401 / 403 captured in tool result envelope; no unhandled exception.
  - Structured `logging` to stdout/stderr with per-tool event names (`push_activity_*`, `push_artifacts_*`) and a fixed PII allowlist.
  - Unit-test suite in `services/mcp-server/tests/unit/`.
  - Write of the `mcp-tools` contract's `server` / `tools` fields into `docs/requirements/api.md#mcp-tools` (already stubbed; confirm content).
- **Out**:
  - Copilot-Chat activity-hook bridge — owned by ING-05.
  - Server-side / centrally-hosted MCP server — this story is local-machine only.
  - Automatic tool discovery / installation UX beyond the two entry points listed above.
  - Wiring `services/mcp-server/` into the main API's `docs/config/project-commands.yaml::preflight` (D-01: separate deploy).
  - Any change to `services/api/app/api/ingest.py`, `activity_ingest.py`, or `ingest_artifacts.py` — this story is a consumer of frozen contracts.
  - Re-validating request rows in the MCP tool — raw NDJSON is passed straight through; the backend's Pydantic layer is the source of truth for row validation.
  - Alembic migration — no database owned by the MCP server.
  - UI — headless local service; NFR-Accessibility is `N/A`.
  - Copilot-Chat bridge or session-token exchange (defer to ING-05).

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/ING-04.md` for canonical wording. New impl constraints introduced below (URL corrections, allowlist rules, and tool-result envelope shape are the deltas):

**ING-04-FR-1** — FastMCP transport + tool registration  *(extends AC-1 with: exact framework choice + boot surface)*

`services/mcp-server/src/agentrise_mcp/server.py` uses the standalone `fastmcp` package (PyPI `fastmcp`, `jlowin/fastmcp`, v2.x — pin exact version in `pyproject.toml`) to construct a `FastMCP("agentrise-mcp")` server and register exactly two tools via `@server.tool()`: `push_activity(program_id: str | None = None, workspace_root: str | None = None) -> dict` and `push_artifacts(program_id: str | None = None, workspace_root: str | None = None) -> dict`. Transport is streamable HTTP, default bind `0.0.0.0:3010`, path `/mcp`. Both `python -m agentrise_mcp.server` and console script `agentrise-mcp` MUST boot the same server. No additional tools, resources, or prompts are exposed.

**ING-04-FR-2** — `push_activity` reads `program.yaml`, batches 500, POSTs to `/api/ingest/activity`  *(supersedes AC-2 story wording, which is stale on both YAML path and endpoint URL)*

`push_activity` reads `<workspace_root>/.harness/program.yaml` (NOT `.harness/profile.yaml` — see § Open questions → Resolved / R-04), iterates `files[]` (`kind: activity`), parses each file as NDJSON one line at a time (skip blank lines; skip lines that fail JSON parse — count as `rejected` with reason `malformed_ndjson_line`; row indices in rejections are the row's 0-based position within the batch, matching backend's `RejectionEntry.index` semantics). Batch parsed rows at **500 per HTTP POST** (the MCP → API batch cap; this is UNRELATED to the backend service's internal 2730-row per-INSERT chunk, which is a DB batch size). For each batch, POST envelope `{program_id, kind:"activity", rows}` to `POST /api/ingest/activity` (per ADR-0013 — NOT `/api/ingest/files`) with the configured bearer token. Aggregate the per-batch `IngestFilesResponse` fields into a single tool result: `{success: bool, files_read: int, rows_read: int, batches: int, inserted: int, updated: int, rejected: list[RejectionEntry], rollups: dict}`. Envelope `kind` MUST equal `"activity"` verbatim — the backend rejects 400 `unknown envelope kind` otherwise.

**ING-04-FR-3** — `push_artifacts` reads `program.yaml`, one HTTP POST per invocation, POSTs to `/api/ingest/artifacts`  *(supersedes AC-3 story wording, which is stale on YAML path only; endpoint URL is unchanged)*

`push_artifacts` reads `<workspace_root>/.harness/program.yaml` (NOT `.harness/profile.yaml` — see § Open questions → Resolved / R-04), iterates the `artifacts{}` mapping (keys are ProgramArtifact.type values, restricted to the 5 canonical types documented in `docs/requirements/api.md#ingest-artifacts-api::canonical_types`: `prd`, `user_story`, `test_case`, `arch_diagram`, `api_spec`). For each entry, resolve to an integer count against the local filesystem per `kind`:

- `glob-count` — count files matching `glob` under `path` (dir), skipping any relative path matching an entry in `exclude` (fnmatch, `**` honoured).
- `json-key-count` — read `path` (JSON file), count top-level object keys, skipping keys listed in `exclude`.
- `json-field-sum` — for every JSON file matching `glob` under `path`, add the length of the array at literal key `field` (missing → 0).
- `constant` — fixed integer at `value`.

Assemble one `counts: dict[str, int]` for all resolved entries and issue **exactly one** HTTP POST per invocation — the envelope `{program_id, kind:"artifacts", counts, as_of}` to `POST /api/ingest/artifacts` with the configured bearer token. No batching (the canonical vocabulary has 5 entries maximum). `as_of` is generated client-side as an ISO-8601 UTC timestamp (`datetime.now(UTC).isoformat()`). Return the backend's `IngestArtifactsResponse` fields wrapped in the tool-result envelope: `{success: bool, rows_received: int, rows_upserted: int, rejections: list}`.

**ING-04-FR-4** — `workspace_root` path resolution  *(extends AC-4 with: explicit normalisation rule)*

When `workspace_root` is supplied, resolve `<workspace_root>/.harness/program.yaml` and every relative path inside `program.yaml` against it. Normalise via `pathlib.Path(workspace_root).resolve()` before any filesystem operation. When `workspace_root` is omitted, use the server process's current working directory (`Path.cwd().resolve()`) as the anchor. Symlink resolution runs BEFORE the symlink-escape check in ING-04-FR-7. Non-existent `workspace_root` → tool result `{success: false, error: "workspace_root_not_found", ...}` before any HTTP call.

**ING-04-FR-5** — Auth-failure surfacing in tool result  *(extends AC-5 with: exact envelope shape)*

When the ingest endpoint responds `401` (missing/revoked/expired bearer per `ingest-token-auth`) or `403` (envelope `program_id` not in the token's `allowed_program_ids`; empty list or `"*"` = allow-all per ADR-0006), the tool MUST capture the failure in its returned result envelope and MUST NOT raise an unhandled exception to the MCP client. Envelope shape: `{success: false, error: "unauthorized" | "forbidden", http_status: 401 | 403, batches_sent: int, batches_failed: int, inserted: 0, ...}`. On mid-run auth failure (e.g., token revoked between batches 2 and 3 of a 5-batch `push_activity` run), the tool stops issuing further batches and returns aggregate counts for the batches that succeeded, plus the failure record — batches never "half-succeed" on a 4xx.

**ING-04-FR-6** — Missing-token fail-fast, no HTTP attempt  *(extends AC-6 with: exact error code + read-time)*

The bearer token is loaded at process start from environment variable `AGENTRISE_INGEST_TOKEN` (pin this name; PLAN may add a fallback file-based source but MUST NOT change this env-var name). When the env-var is empty or unset, EITHER tool invocation returns `{success: false, error: "missing_ingest_token", message: "Set AGENTRISE_INGEST_TOKEN before invoking this tool."}` BEFORE constructing the httpx client, BEFORE any DNS lookup, and BEFORE any HTTP attempt. No YAML read, no filesystem enumeration, no glob traversal. This path MUST be covered by a dedicated unit test per tool (`test_push_activity_missing_token`, `test_push_artifacts_missing_token`).

**ING-04-FR-7** — Glob-pattern allowlist (path-traversal & symlink-escape defence)  *(new — from R-06 carry-forward to PLAN)*

Every glob pattern from `artifacts{}.*.glob` and every `path` from `artifacts{}.*.path` MUST be validated before resolution:

- The literal string MUST NOT contain the segment `..` (parent-directory traversal). Reject the entry with `{error: "unsafe_glob_pattern", entry_key: "<type>"}`; the invocation returns `{success: false}` — the whole POST is aborted, no partial payload sent.
- After `pathlib.Path.resolve()`, the resolved path MUST be inside `workspace_root.resolve()`. Symlink-based escape is caught by comparing against `workspace_root` AFTER `resolve()` (which follows symlinks). A resolved path outside `workspace_root` → same rejection as above.
- Glob patterns MUST NOT contain shell metacharacters other than `*`, `**`, `?`, `[...]` (the fnmatch-supported set). Backticks, `$(...)`, `|`, `;`, `&` → rejected.

Enforced at the source-kind resolver's entry point (before any `pathlib.Path.glob()` call). Unit tests exercise each rejection reason.

**ING-04-FR-8** — JSON key / field-name allowlist (no expression evaluation)  *(new — from R-06 carry-forward to PLAN)*

The `field` value in `json-field-sum` entries and every key in `json-key-count`'s `exclude` list (and any future `path`-like field addressing a JSON structure) MUST be treated as a LITERAL key name — not as a JSONPath, JMESPath, or any expression language. Rejection rules:

- MUST NOT contain `.` (path-descent), `$` (JSONPath root), `@` (JMESPath current-node), `[` `]` (subscripting), `*` (wildcard), or whitespace.
- MUST be a non-empty string of alphanumerics + `_` + `-`.
- Violation → `{error: "unsafe_json_key", entry_key: "<type>", offending_value: "<value>"}` and the whole POST is aborted (same discipline as ING-04-FR-7). Unit tests assert that a field value of `"$..secret"` never reaches any JSON traversal code.

## Non-functional requirements

- **Performance**: Per `.claude/rules/performance-baseline.md`: applies to every outbound HTTP call from either tool. Feature-specific numeric budgets — httpx timeout MUST be exactly 5.0 s connect, 30.0 s total per POST; retry MUST be at most 3 attempts, exponential backoff with jitter, ON NETWORK-LEVEL FAILURES ONLY (connect errors, read timeouts, `httpx.NetworkError`) — NEVER on 4xx responses (per `.claude/rules/performance-baseline.md`, bounded attempts on retries). A `push_activity` run over N batches SHOULD complete inside `N × 30s` worst case; the aggregate wall time is NOT an SLO but is what the timeout budget bounds.
- **Security**: Per `.claude/rules/security-baseline.md`: applies to token handling, YAML input, filesystem traversal, and outbound HTTP. Feature-specific additions:
  - Bearer token read once at process start from env-var `AGENTRISE_INGEST_TOKEN` (name pinned by ING-04-FR-6). NEVER printed to any log level (INFO / DEBUG / ERROR), NEVER included in the tool's returned dict, NEVER copied into an `extra=` logging dict, NEVER interpolated into an error message, NEVER embedded in a stack trace. A dedicated unit test captures log records on both the happy path AND the auth-failure path and asserts token absence via a substring check against the raw record buffer.
  - Missing-token → fail-fast client-side per ING-04-FR-6 (no HTTP attempt).
  - Glob and JSON key allowlists per ING-04-FR-7 and ING-04-FR-8 — every user-controlled string from `program.yaml` is validated before it reaches the filesystem or JSON traversal code.
  - YAML parsing uses `yaml.safe_load` — never `yaml.load` (no arbitrary Python object construction).
- **Accessibility**: N/A — headless local MCP server, no UI surface.
- **Observability**: Python `logging` to stdout/stderr. Event names follow the convention `push_activity_started | push_activity_completed | push_activity_auth_failed | push_activity_missing_token | push_activity_batch_failed` and analogously for `push_artifacts_*`. Field allowlist per event (never `user_email`, never raw command text from NDJSON rows, never the token value, never a token hash):
  - `push_activity_started` — `{event, program_id, workspace_root, files_configured}`
  - `push_activity_completed` — `{event, program_id, files_read, rows_read, batches_sent, inserted, updated, rejected, duration_ms}`
  - `push_activity_batch_failed` — `{event, program_id, batch_index, http_status, duration_ms}` (no response body)
  - `push_activity_auth_failed` — `{event, program_id, http_status}` (401 or 403)
  - `push_activity_missing_token` — `{event, program_id}` (no token value)
  - `push_artifacts_*` — analogous, with `types_written: list[str]` on `push_artifacts_completed` and `types_configured: int` on `push_artifacts_started`.

  Emitted at INFO level. Enforced by a unit test that captures records and diffs field names against the allowlist per event (allowlist diff, not denylist).

## Visual spec

Not applicable — backend / MCP-tool story with no UI surface. `integrations.design = none` at the per-feature level (no epic in `docs/design/schema.json` for the MCP tools lane).

## Rollout plan

- **Strategy**: bang-bang. `services/mcp-server/` is a brand-new sibling service; enabling it is deploying it (or having a developer `pip install` and run it locally). Backwards-compatible with the ingest API (which was already accepting these envelopes from any bearer-token caller since ING-02 / ING-03 shipped).
- **Feature flag**: none. Developers who don't want the tool simply don't run it. The bearer token itself is the enable gate (per-developer).
- **Backout plan**: revert the `services/mcp-server/` package (the whole directory); developers stop the local process. The ingest endpoints and `program_artifacts` / `usage_events` tables are unaffected because they were shipped by ING-02 / ING-03 and are consumed by nothing else in this story's diff. No schema or data changes to revert.
- **Success signal**: within 7 days of shipping, at least 2 distinct developers (roster emails from `.harness/program.yaml::team[]`) have `push_activity_completed` events observed against the ingest endpoint, and their local `usage_events` rows appear in the dashboard's Activity panel. `push_artifacts_completed` events observed with a non-empty `types_written` list within the same window.

## Documentation requirements

- **README updates**:
  - New `services/mcp-server/README.md` — quickstart (install, set `AGENTRISE_INGEST_TOKEN`, `python -m agentrise_mcp.server` OR `agentrise-mcp`), MCP client config snippet (host + port + path), the two tool signatures, the two env-vars, links to `program.yaml` schema.
  - Root `README.md` — one-line entry pointing at the new service directory (precedent: BED / ING service entries).
- **Runbook**: none — local-machine service; no operational monitoring surface owned by the platform team for this story.
- **API reference**: `docs/requirements/api.md#mcp-tools` — confirm the `server` and `tools` fields match ING-04-FR-1 exactly. No new endpoint contracts (consumer only).
- **Inline code comments**: `services/mcp-server/src/agentrise_mcp/server.py` module docstring — declare the FastMCP version pin rationale (C-01 resolution) and the ADR-0013 endpoint-URL correction. `services/mcp-server/src/agentrise_mcp/tools/push_activity.py` and `tools/push_artifacts.py` module docstrings — explicitly note the 500-row MCP batch cap is UNRELATED to the backend's 2730-row DB chunk.
- **Examples / how-to**: none for this story — the `services/mcp-server/README.md` quickstart is enough for a local developer.

## Open questions

None open. Everything blocking is resolved below.

### Resolved

- **C-01 — FastMCP library choice** (RESOLVED 2026-09-14, main session) — Use standalone `fastmcp` PyPI package (`jlowin/fastmcp`, v2.x; https://pypi.org/project/fastmcp/). NOT `fastapi-mcp` and NOT anthropic's `mcp` SDK. Pinned in § Constraints and ING-04-FR-1. See `docs/features/ING-04/state.json::resolved_clarifications[C-01]`.
- **R-04 — Profile YAML location drift** (RESOLVED 2026-09-14, main session) — Single source: `.harness/program.yaml` for both `files[]` and `artifacts{}`. `.harness/profile.yaml` is identity-only (email/name/role, gitignored, per-machine) and MUST NOT be treated as a fallback data source. Story AC-2 / AC-3 references to `.harness/profile.yaml` are stale (pre-ING-10); corrected in ING-04-FR-2 and ING-04-FR-3 verbatim. See `docs/features/ING-04/state.json::risks[R-04]`.
- **D-01 — Deployment topology** (RECORDED 2026-09-14, main session) — `services/mcp-server/` is a separately-deployed sibling service with its own `pyproject.toml`, tests, commands, and deploy pipeline. It MUST NOT be wired into the main API's `docs/config/project-commands.yaml::preflight`. Any `mcp_server:*` namespace in the root commands file is optional and out of scope for this PRD. See `docs/features/ING-04/state.json::decisions[D-01]`.
- **URL correction (story text drift)** — Story AC-2 and AC-3 reference `POST /api/ingest/files` and `POST /api/ingest/artifacts`. Per ADR-0013 the live routes are `POST /api/ingest/activity` and `POST /api/ingest/artifacts`, both served by the generic `POST /api/ingest/{kind}` handler. ING-04-FR-2 and ING-04-FR-3 use the correct URLs verbatim. No new decision — ADR-0013 is the settling record.

Two HIGH-severity research risks are carry-forward-to-PLAN and are now first-class FRs in this PRD (see ING-04-FR-7 for R-06 glob defence, ING-04-FR-8 for R-06 JSON-key defence, and NFR-Security bullet for R-07 token handling). PLAN cannot silently drop them.

Decisions logged in `docs/stories/ING-04.md` § Decision log.

## Approvals

- **YYYY-MM-DD** — <Approver name> (PO + Designer + BA, single-approver mode covers all when one human): **APPROVE | CHANGES**
  - Feature Summary, FRs, User Flows reviewed
  - UI specs: N/A for this backend / MCP-tool story (`integrations.design = none`)
  - Edge Cases, Open Questions, test-case completeness reviewed
  - No-placeholder check ✓ · `[NEEDS CLARIFICATION]` count=0
  - Research verdict `GO-WITH-CONDITIONS` (all four conditions addressed in § Addressing Research Conditions)
  - Tracker subtask: <KEY-XX>
