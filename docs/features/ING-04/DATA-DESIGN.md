# ING-04 — Data Design

State & data management for the MCP server exposing `push_activity` / `push_artifacts`. This feature owns NO durable state (no database, no schema, no migration) — it is a stateless local HTTP client of the frozen ingest API. Each concern below is specified or marked `N/A — <reason>`.

## 1. Data model

No new tables. No new documents. No new KV keys. The MCP server holds no durable state of its own; every field it touches originates in `.harness/program.yaml` (read-only) or a frozen upstream response schema.

### `.harness/program.yaml` (repository-committed YAML, read-only) — the reads

| Field path | Type | Class | Notes |
|---|---|---|---|
| `programId` | `str` | — | Default `program_id` when the tool caller omits the argument. |
| `files[]` | `list[{path:str, kind:str, mode:str}]` | — | Read by `push_activity` only. `kind == "activity"` entries are streamed as NDJSON; other kinds ignored. |
| `artifacts{}` | `dict[str, dict]` | — | Read by `push_artifacts` only. Keys are canonical types (5-entry closed vocabulary, D-04 / ADR-0013 downstream). Per-entry `kind` selects the source resolver (`glob-count` / `json-key-count` / `json-field-sum` / `constant`). |

Loaded via `yaml.safe_load` (NEVER `yaml.load` — no arbitrary Python object construction; NFR-Security bullet). File path is hard-coded to `<workspace_root>/.harness/program.yaml` in `core/profile.py` (F-11); `.harness/profile.yaml` is NEVER read by either tool (D-04).

### `<NDJSON file>` (repository-committed, read-only) — the reads

Each `files[]` entry names an NDJSON path (e.g. `docs/activity/activity.jsonl`). One JSON object per line; blank lines skipped silently; malformed lines counted as `rejected` with reason `malformed_ndjson_line` (row index is the 0-based position within the batch). The tool passes each parsed row through to the backend AS-IS — no per-row Pydantic validation on the client (the backend's `ActivityRowIn` is the source of truth, PRD § Solution sketch + § Scope / Out).

## 2. Migrations

N/A — no database schema, no persistent state, no document store. Nothing to migrate. Nothing to backfill. `services/api/tests/test_migrations.py` and `services/api/alembic/versions/` are untouched by this story.

## 3. Ownership & tenancy

Envelope-tier only, at the upstream. The MCP tool reads `program_id` from the caller argument (falling back to `program.yaml::programId`), embeds it in every POST envelope, and the backend's `POST /api/ingest/{kind}` runs the standard `ingest-token-auth` bearer scope check (`allowed_program_ids` per ADR-0006) against it. Denial is a 401/403 response; the tool surfaces this in the tool-result envelope per FR-5 (`{success: false, error: "unauthorized"|"forbidden", http_status: 401|403, ...}`) and never raises to the MCP client. No row-level scope, no local ACL, no per-tenant partitioning inside the MCP server — it is single-user by construction (the developer running it on their own laptop).

## 4. Data classification & retention

- **Bearer token (`AGENTRISE_INGEST_TOKEN`)** — SENSITIVE. Read once at process start from env-var (D-06), held in-process, never persisted to disk, never emitted to any log level (NFR-Security explicit), never echoed in a tool-result dict, never interpolated into an error message, never present in a stack trace. Enforced by F-37 (`test_logging_no_token_leak.py`, T-05) which captures records on both the happy path and the auth-failure path and asserts token absence via substring check.
- **NDJSON row content** — POTENTIALLY PII (rows carry `email`, `command` free-text per `ActivityRowIn` shape). The MCP tool passes rows through to the backend WITHOUT logging them (event allowlist per FR-8 excludes `user_email` and raw command text). Retention on the MCP side: zero — the tool holds each batch only for the duration of one POST, and reads NDJSON files line-by-line (never buffering an entire file).
- **Retention (MCP-side)**: none. The tool holds no persistent state. On restart, all in-memory state is discarded. The bearer token is re-read from the env at the next process start.

## 5. Consistency & concurrency

- **Transaction boundary**: N/A on the client — every POST is a self-contained HTTP request. The backend's own `POST /api/ingest/activity` has its own transaction semantics (chunked upsert per ING-02); `POST /api/ingest/artifacts` has its own (single-transaction upsert per ING-03). The MCP tool is downstream of both.
- **Idempotency**: inherited from the backend. Both endpoints are idempotent on re-POST (activity uses `unique(program_id, session_id, cmd_ts)`; artifacts uses `unique(program_id, type)`). The MCP tool is safe to re-run — a `push_activity` call that failed mid-run (e.g. auth revoked after batch 2 of 5) can be re-invoked and the successfully-committed batches will be dedup'd on the backend side.
- **Batch semantics (`push_activity`)**: N batches per invocation, where N = `ceil(total_rows / 500)`. Batches are POSTed in order. On a 4xx auth failure mid-run (FR-5), the tool stops issuing further batches — a batch either fully commits (200) or is not sent, per D-05. Batches never "half-succeed" client-side.
- **Batch semantics (`push_artifacts`)**: exactly one POST per invocation (5 canonical types max, no batching needed).
- **Concurrent invocations**: the MCP server serves one MCP client per process; concurrent tool calls from the same client execute in the order the FastMCP transport dispatches them (per-request async). No cross-invocation state, no lock needed. Two developers running two MCP servers concurrently is not a client-side concern — the backend serialises the write path.

## 6. Caching

N/A — no cache is introduced or consumed. The MCP server is a request-scoped HTTP client; every invocation re-reads `program.yaml`, re-resolves every source, and re-POSTs. Caching `program.yaml`'s parsed content across invocations was rejected: the file is small and reading it fresh guarantees the tool never uses a stale view when the developer edits it between runs.

## 7. Ephemeral / session state

The MCP server holds the bearer token in-process for the lifetime of the process (D-06). No cookies, no session store, no per-connection state beyond the FastMCP transport's own request handling. Structured-log records are emitted to stdout / stderr per invocation and NOT retained in-process. Every tool invocation is a fresh execution of `push_activity` / `push_artifacts` — no shared mutable state between invocations.

## 8. Query-path & access-path performance

- **`push_activity`** — per-batch cost = one httpx POST (5 s connect / 30 s total timeout, D-05 batch cap 500 rows). Aggregate wall time for N batches ≤ N × 30 s worst case. NDJSON is streamed line-by-line (no whole-file buffering), so memory footprint is O(batch_size × row_size) not O(file_size).
- **`push_artifacts`** — exactly one httpx POST per invocation. Total wall time bounded by the same 30 s per-POST budget. Source-resolver cost is O(files_matched × parse_cost); `glob-count` scans the filesystem; `json-key-count` and `json-field-sum` `yaml.safe_load` (or `json.load`) each file once.
- **Retry policy**: `retry_with_backoff(max_retries=3)` — network-level failures only (`httpx.NetworkError`, connect errors, read timeouts). NEVER on 4xx responses (a 401 is captured in the tool-result envelope, not retried — retrying a 401 would just replay the missing / revoked token). Exponential backoff + jitter per `.claude/rules/performance-baseline.md`.
- **N+1 avoidance**: the MCP tool never issues per-row HTTP calls (batched at 500 for activity, 1 for artifacts). File I/O is bounded by `program.yaml`'s size (small — dozens of entries at most).
- **No pagination** — bounded-size inputs by construction (activity limited by NDJSON file size, artifacts limited by 5-entry canonical vocabulary).

## 9. Contract (API / interface)

The MCP server both consumes an upstream HTTP contract and produces a downstream MCP-tools contract. Both are registered cross-story contracts in `docs/requirements/api.md` — this section carries bookmarks per plan-authoring § Contract, not duplicate specs.

### Consumed (upstream)

The MCP server is a **consumer** of both frozen ingest contracts shipped by ING-02 / ING-03:

- Contract: `ingest-files-api` → `docs/requirements/api.md#ingest-files-api` (kind = "activity", URL `POST /api/ingest/activity`, response `IngestFilesResponse{files_read, rows_read, batches, inserted, skipped_duplicate, rejected, rollups}`, per ADR-0013 URL topology).
- Contract: `ingest-artifacts-api` → `docs/requirements/api.md#ingest-artifacts-api` (kind = "artifacts", URL `POST /api/ingest/artifacts`, response `IngestArtifactsResponse{rows_received, rows_upserted, rejections}`, per ING-03 D-02).
- Auth contract: `ingest-token-auth` → `docs/requirements/api.md#ingest-token-auth` (bearer token, program-scope via `allowed_program_ids`, per ADR-0006).

The tool result envelopes wrap these upstream responses and add MCP-tool-specific fields (`success`, `http_status`, `error`) per FR-2 / FR-3 / FR-5.

### Produced (downstream)

The MCP server produces the `mcp-tools` contract that ING-05 (Copilot-Chat bridge) will consume:

- Contract: `mcp-tools` → `docs/requirements/api.md#mcp-tools` (F-43, filled by T-11). Shape:
  - `server`: `services/mcp-server`, package `agentrise_mcp`, FastMCP streamable HTTP, bind `0.0.0.0:3010`, path `/mcp`, boot via console script `agentrise-mcp` OR `python -m agentrise_mcp`.
  - `tools[0]`: `push_activity(program_id: str | None = None, workspace_root: str | None = None) -> dict` — returns `{success: bool, files_read: int, rows_read: int, batches: int, inserted: int, skipped_duplicate: int, rejected: list, rollups: dict, http_status?: int, error?: str}`.
  - `tools[1]`: `push_artifacts(program_id: str | None = None, workspace_root: str | None = None) -> dict` — returns `{success: bool, rows_received: int, rows_upserted: int, rejections: list, http_status?: int, error?: str}`.
  - `env_vars`: `AGENTRISE_INGEST_TOKEN` (required, bearer token per `ingest-token-auth`, D-06).

The MCP tool result envelope shape is the authoritative wire spec for ING-05's bridge; the shared contract file (`docs/requirements/api.md#mcp-tools`) is the single reference, filled by T-11 (F-43).

## 10. Async & messaging

N/A — the MCP server is a purely-synchronous request/response tool. No message broker, no queue, no scheduled job, no cron. FastMCP's own transport is async-Python internally, but the tool logic (invocation → YAML read → HTTP POST → return) is single-request-scoped. No `BackgroundTask` on either the client or the backend for the artifacts branch (ADR-0012 non-applicable on `kind="artifacts"` per ING-03 D-03; on `kind="activity"` the org-rebuild dispatch happens server-side inside `activity_ingest`, invisible to the MCP tool).
