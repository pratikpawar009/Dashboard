---
feature_id: ING-04
title: MCP server tool exposure (push_activity / push_artifacts)
author: Research Agent
date: 2026-09-14
status: Complete
---

# Research Assessment: ING-04

## Upstream Dependencies

| ID | Story | Status | Verdict | Impact |
|----|-------|--------|---------|--------|
| ING-02 | Ingest files API (activity rows) | Merged (PR #296, commit 615df21) | GO-WITH-CONDITIONS | Endpoint live: `POST /api/ingest/activity` via generic router (ADR-0013). URL drift: story text says `/api/ingest/files`; actual endpoint is `/api/ingest/activity` per ING-03 planning. |
| ING-03 | Ingest artifacts API (governance counts) | Merged (PR #302, commit 3bcb944) | GO | Endpoint live: `POST /api/ingest/artifacts` via generic router (ADR-0013). ING-04 depends on both endpoints being live and accepting bearer-token auth per `ingest-token-auth` contract. |

Both endpoints are **live on main** and accepting requests. ING-04 is a consumer of frozen contracts.

---

## Codebase Map

### Existing Ingest Infrastructure (ING-02, ING-03)

**Router layer** (`services/api/app/api/ingest.py`)
- Single generic handler `POST /api/ingest/{kind}` (ADR-0013)
- Dispatches by `kind` path-param: `"activity"` → activity service, `"artifacts"` → artifacts service
- Accepts kinds from `app/core/ingest_kind.py::_ACCEPTED_KINDS = {"activity", "artifacts"}`
- Auth gating via `get_ingest_token(program_id, credentials, session)` called directly (body-bound program_id, not path-param)
- Row-cap enforcement (5000) at router tier before any service dispatch
- Structured logging per FR-8 (PII allowlist enforced)

**Service layer** (`services/api/app/services/`)
- `activity_ingest.py`: NDJSON parsing, chunked upsert (2730 rows/chunk), intra-batch dedup on `(program_id, session_id, cmd_ts)`, org-rollup dispatch via `on_org_rebuild` callback (ADR-0012, out-of-band)
- `ingest_artifacts.py`: Single-transaction upsert of canonical-type counts (5 types), no rollup dispatch (D-03, ADR-0012 non-applicable)

**Auth layer** (`services/api/app/core/ingest_auth.py`)
- Bearer token resolution via SHA-256 hash lookup on `ingest_tokens.token_hash`
- Program-scope enforcement via `allowed_program_ids` list (wildcard `"*"` or empty = allow-all per ADR-0006)
- Returns `IngestToken` row directly; three-step denial logic (missing/unknown/revoked/expired/scope)

**Schema layer** (`services/api/app/schemas/ingest_*.py`)
- `ActivityRowIn`: Pydantic v2, `extra="ignore"`, `populate_by_name=True`, 19 fields with 5 wire→column aliases
- `IngestFilesResponse` / `IngestArtifactsResponse`: Flat counts + rejection list
- `RejectionEntry`: `{index, reason}` only (no row content per PII discipline)

### Target Service (To Be Scaffolded)

**Path**: `services/mcp-server/` (does not exist)
- Expected package: `agentrise_mcp`
- Entry point: `python -m agentrise_mcp.server` or console script `agentrise-mcp`
- Framework: **FastMCP** (lightweight MCP server, streamable HTTP)
- Default bind: `0.0.0.0:3010`, path `/mcp`
- Two tools: `push_activity(program_id?, workspace_root?)`, `push_artifacts(program_id?, workspace_root?)`

**Scaffolding scope**:
- Alembic-free Python package (no database migrations)
- Own `pyproject.toml` with dependencies (FastMCP, httpx, pyyaml)
- Own test suite (`tests/unit/`)
- Directory structure mirrors `services/api/` conventions where applicable (separation of concerns, but no database layer)

### Key Config Files

**`.harness/program.yaml`** (existing, root repo)
- Committed identity + roster + activity/artifact source paths
- `team[]`: roster entries with email/name/role/aliases
- `files[]`: activity source entries (path, kind, mode) — ING-04 reads this
- `artifacts{}`: governance-count source entries (path, source_kind, type) — ING-04 reads this

**`docs/config/project-commands.yaml`** (existing)
- No MCP-server-specific commands yet; ING-04 should add preflight/test commands for the new service

### Related ADRs & Decisions

- **ADR-0013** (ingest router topology): Generic `/api/ingest/{kind}` handler, not separate `/files` and `/artifacts` routes. URL is `/api/ingest/activity`, not `/api/ingest/files`.
- **ADR-0012** (org-rollup scheduling): Out-of-band via BackgroundTasks (activity path only; artifacts path has no rollup dependency).
- **ADR-0006** (ingest-token scope): Empty `allowed_program_ids` = allow-all (deliberate, accepted risk).
- **ING-04 Decisions** (story DECISIONS.md):
  - Timeout/retry: 5s connect, 30s total, 3 retries with expo+jitter on network failures only
  - Missing-token fail-fast: client-side error before HTTP
  - Observability: Python `logging` to stdout/stderr (no structured event name per PRD NFR-011)

---

## Pattern Map

### 1. MCP Server Layout & Tool Registration

**Status**: Not yet present in codebase (new stack element).

ING-04 story assumes `agentrise_mcp` is "carried over unchanged from reference implementation" (PRD §4.2, C-009). This means:
- External reference exists (likely github.com/anthropics/mcp or similar)
- ING-04 ports/vendors that reference implementation into `services/mcp-server/`
- Tool registration is via FastMCP's `@server.tool()` decorator or equivalent

**Pattern to establish**: 
```python
# services/mcp-server/src/agentrise_mcp/server.py
from mcp.server import Server
from fastapi_mcp import FastMCP

server = FastMCP("agentrise-mcp")

@server.tool()
def push_activity(program_id: str | None = None, workspace_root: str | None = None) -> dict:
    """Push activity from .harness/profile.yaml to the ingest endpoint."""
    ...

@server.tool()
def push_artifacts(program_id: str | None = None, workspace_root: str | None = None) -> dict:
    """Push artifact counts from .harness/profile.yaml to the ingest endpoint."""
    ...

if __name__ == "__main__":
    server.run()
```

### 2. HTTP Client with Timeout & Retry

**Status**: Existing `httpx` dependency in `services/api/pyproject.toml:23` (for Keycloak JWKS fetch). Reusable pattern at `services/api/app/core/retry.py`.

**Existing retry pattern** (from FastAPI patterns skill):
```python
# services/api/app/core/retry.py — only module defining retry, per idioms
def retry_with_backoff(fn, max_retries=3, initial_delay=0.1, ...):
    ...
```

**MCP server needs parallel pattern**:
- Create `services/mcp-server/src/agentrise_mcp/core/http_client.py`
- Timeout config: 5s connect, 30s total (as per ING-04 D-01)
- Retry on network failures only (not 4xx/5xx response codes)
- Exponential backoff + jitter per performance-baseline.md
- Use `httpx.AsyncClient` for consistency with backend

### 3. NDJSON Parsing & Batching

**Pattern to establish**:
- Read `.harness/profile.yaml` via `pyyaml` (already in api's dependencies)
- For each `files[]` entry: read NDJSON file, skip blank/malformed lines
- Parse rows (Pydantic validation? Or raw dict?)
- Batch 500 rows/request per AC-2 (not per service's 2730-row chunk limit)
- POST to `POST /api/ingest/activity` with envelope `{program_id, kind:"activity", rows[]}`

**Note**: Do NOT re-implement the same Pydantic validation as `ActivityRowIn` — the schema lives in the backend. MCP reads raw NDJSON and passes it as-is to the backend. The backend's schema layer validates.

### 4. Artifact Count Resolution (Source Kinds)

**Four source kinds** (AC-3):
- `glob-count`: Count files matching glob under path
- `json-key-count`: Count keys in a JSON object
- `json-field-sum`: Sum values of a field across JSON objects  
- `constant`: Fixed integer

**Pattern to establish**:
- Create `services/mcp-server/src/agentrise_mcp/core/source_resolver.py`
- For each `artifacts{}` entry: resolve source kind to integer count against local filesystem/JSON
- Risk: glob pattern and JSON path are unbounded user input — validate paths (no `../` traversal, within workspace root)
- POST to `POST /api/ingest/artifacts` with envelope `{program_id, kind:"artifacts", counts{}, as_of}`

### 5. Bearer Token Auth

**Pattern from backend** (ING-02 FR-6 / ING-04 AC-6):
- Token read from **local MCP environment file** only (not env var, not .env)
- Never logged, never echoed in response
- Missing-token → fail-fast with client-side error before HTTP attempt
- Auth failures (401/403) → surface in tool result, not raise unhandled exception to MCP client

**MCP server structure**:
- Token source: `AGENTRISE_MCP_INGEST_TOKEN` env var (or read from `.agentrise-mcp/config` file — TBD)
- Guard in tool body: if token missing, return `{success: false, error: "no_ingest_token"}` before HTTP
- HTTP response handling: if 401/403, capture status + detail in result struct, do not raise

### 6. Profile YAML Resolution

**Pattern to establish**:
- Read `.harness/profile.yaml` (or `program.yaml` per ING-10 layout — story AC-2 says `profile.yaml`, carry-forward risk noted)
- Resolve relative paths against `workspace_root` (default: current working directory)
- Handle both local-dev fixture files and committed paths

### 7. Structured Logging

**Requirement** (AC NFR, story assumptions):
- Each tool invocation logs outcome to stdout/stderr
- Success/partial/failure status
- Row/count totals
- HTTP status if applicable
- No token hash, no raw PII (user emails, commands)

**Pattern to establish**:
```python
import logging
logger = logging.getLogger(__name__)

# In tool body:
logger.info("push_activity_started", extra={"program_id": program_id, ...})
# ... work ...
logger.info("push_activity_completed", extra={
    "program_id": program_id,
    "rows_read": 1000,
    "batches_sent": 2,
    "inserted": 950,
    "rejected": 50,
    "http_status": 200,
})
```

---

## Risk Register

| # | Risk | Category | Severity | Probability | Impact | Mitigation |
|---|------|----------|----------|-------------|--------|-----------|
| **R-01** | **URL drift: Story says `/api/ingest/files`, real endpoint is `/api/ingest/activity` (ADR-0013)** | Contract drift | LOW | HIGH | Tool hard-codes wrong URL, fails 404 on live endpoint | Reference ADR-0013 directly in tool docstring; add unit test that fetches endpoint URL from ADR fixture; code review gate must flag hardcoded URLs. |
| **R-02** | **MCP/FastMCP not covered by existing patterns skills** — No `mcp-patterns` or `fastmcp-patterns` skill exists; tool author must reverse-engineer FastMCP from examples or reference impl | Pattern coverage | MEDIUM | MEDIUM | Inconsistent tool registration, wrong transport config, missed lifecycle hooks | Vendor FastMCP docs + reference implementation into PR description; code review focuses on transport wiring; add FastMCP version pin to pyproject.toml with explicit dependency note. |
| **R-03** | **New service scaffolding scope** — `services/mcp-server/` structure, pyproject.toml, test harness, console-script entry point all TBD | Ops / Build | MEDIUM | HIGH | Missing .venv setup, test runner config, or build artifacts | Add MCP server to `docs/config/project-commands.yaml::preflight` (install check) and `::test` (pytest in services/mcp-server); write pyproject.toml with explicit test entry point. |
| **R-04** | **Profile YAML location drift** — Story AC-2 reads `.harness/profile.yaml`, but ING-10 moves activity/artifact sources to `.harness/program.yaml` (committed) | Scope / Contract | HIGH | HIGH | Tool looks for files/artifacts in wrong YAML file, finds nothing, silently reports zero rows | Documented carry-forward (ING-02 research, line 189). Acceptable: story was written pre-ING-10 decision. Mitigation: story logic should accept BOTH layouts gracefully (check program.yaml first, fall back to profile.yaml for local dev), OR explicitly gate on ING-10's completion. Decision needed in PLAN phase. |
| **R-05** | **Batch size × unbounded file/artifact count** — If `.harness/profile.yaml` lists 1000 files, tool sends 1000 batches. Each batch HTTP POST is a round-trip. | Perf | LOW | MEDIUM | Tool runs slowly on large profiles, timeout on single batch exceeds 30s | Constraint not in AC; story assumes reasonable profile size (single-digit files/artifacts). Mitigate via observability: log batch count + total time; recommend profile authors keep files[] under 20 entries. No hard limit needed for MVP. |
| **R-06** | **Glob pattern / JSON path injection** — User-controlled glob/path in profile.yaml is passed unsanitized to filesystem/JSON resolver | Security | HIGH | MEDIUM | Malicious glob traverses workspace, reads sensitive files outside intended scope; JSON path traversal reads arbitrary JSON fields | Input validation: glob patterns must not contain `..`, must stay within workspace_root; JSON paths must not contain `$` or `@` or complex expressions. Enforce via explicit allowlist of safe patterns OR sandboxed path resolution. Carry-forward to PLAN phase. |
| **R-07** | **Token secret handling** — Env-var leak (e.g., env printed in logs, leaked in error output) | Security | HIGH | MEDIUM | Bearer token exposed in logs, stack traces, or error responses | Establish MCP server's logging config to suppress env-var printing. Review all exception handlers to ensure token is never in `extra` dict passed to logger. Add "check for INGEST_TOKEN in logs" to unit test allowlist. Use environment-variable masking in framework if available (e.g., FastMCP's own logging config). |
| **R-08** | **Missing-token fail-fast implementation detail** — AC-6 says "fail fast with client-side error before any HTTP call" but MCP client expects a specific result structure | Contract | MEDIUM | MEDIUM | Tool raises exception or returns malformed result; MCP client cannot parse outcome | Define result shape for missing-token case: `{success: false, error: "missing_ingest_token", message: "..."}`. Add unit test for this exact path. |
| **R-09** | **Workspace root resolution** — AC-4 says use supplied `workspace_root` if given, else current working directory. Path normalization edge cases (symlinks, relative paths). | Integration | LOW | MEDIUM | Tool resolves paths incorrectly, misses files or reads wrong files | Explicit path normalization: `pathlib.Path(workspace_root or ".").resolve()` before any file operations. Unit tests: relative paths, absolute paths, symlinks, non-existent paths. |
| **R-10** | **Performance-baseline compliance: timeout/retry config** — Story D-01 specifies 5s connect, 30s total, 3 retries. httpx client must enforce these exactly. | Perf | LOW | MEDIUM | Tool hangs on slow network, violates baseline, or does not retry transient failures | Explicit httpx config: `timeout=httpx.Timeout(5.0, pool=30.0)`, `retry_with_backoff(max_retries=3)`. Add integration test: mock slow server (>5s connect), confirm timeout; mock transient 503, confirm retry + eventual success. |

---

## Open Clarifications

### C-01: FastMCP vs mcp-python library selection

[NEEDS CLARIFICATION: The story and PRD both reference "FastMCP" and a "reference implementation" in `agentrise_mcp`, but do not name the exact library/version. Is this `fastapi-mcp` (a FastAPI plugin), the standalone `mcp` library from Anthropic, or a third-party agentrise-specific fork?]

**Impact**: Low if a reference implementation exists to copy; HIGH if team must build FastMCP integration from scratch.

**Resolution path**: Provide link to reference GitHub repository or PyPI package name in story's PLAN phase.

---

## Scoring Rubric (5-Dimension, 0–20 per dimension, /100 total)

### 1. Scope Clarity: 16/20

**Strengths**:
- Frozen contracts (ING-02, ING-03 endpoints live and documented)
- Explicit ACs with tool signature, batching rules (500 rows), source kinds
- Carries-over pattern from reference implementation (no net-new design needed)
- Story-level assumptions documented in Decision log (timeout/retry, token handling, logging)

**Gaps**:
- Profile YAML location (R-04): Story references `.harness/profile.yaml`, but ING-10 layout uses `.harness/program.yaml` — story doesn't specify branching logic for both layouts
- FastMCP library choice unclear (C-01)
- Token source (env var vs file) not explicitly stated

**Deduction**: -4 for YAML layout ambiguity + library choice gap.

### 2. Codebase Fit: 14/20

**Strengths**:
- Ingest endpoints proven (ING-02, ING-03 live, tested, validated)
- Backend auth patterns ready (bearer token, `ingest_token_auth` contract)
- FastAPI backend and new MCP service share language (Python), can share Pydantic imports
- HTTP client pattern exists in backend (`app/core/retry.py`)

**Gaps**:
- New service type (MCP server) not in existing `docs/config/project-commands.yaml`
- No MCP-specific patterns skill (R-02)
- Service scaffolding (pyproject.toml, test runner, entry point) TBD
- No existing reference to `services/mcp-server/` anywhere in tree

**Deduction**: -6 for scaffolding scope + missing pattern skill.

### 3. Complexity: 15/20

**Strengths**:
- Core logic is straight-forward: read YAML → parse NDJSON → batch → HTTP POST
- Token validation and HTTP retry already proven in backend
- No database layer, no rollup rebuild logic

**Gaps**:
- Four source-kind resolvers (glob, json-key-count, json-field-sum, constant) introduce branching
- Artifact-count resolution must handle filesystem and JSON parsing robustly
- Glob pattern validation (R-06) adds input-validation complexity
- YAML layout branching (R-04) adds conditional logic

**Deduction**: -5 for artifact-count resolver complexity + input validation scope.

### 4. Risk & Mitigation: 12/20

**Strengths**:
- All identified risks have clear mitigations (code review, tests, input validation)
- No unknown unknowns; assumptions documented in story's Decision log
- Carry-forwards acknowledged (profile YAML drift from ING-02 research)

**Gaps**:
- High-severity risks present (R-04 profile layout, R-06 glob injection, R-07 token secret)
- Glob pattern injection (R-06) requires defensive coding; no sandbox available
- Token secret handling (R-07) is systemic (every tool invocation must guard it)
- Test coverage for all four source kinds (glob, json-key-count, json-field-sum, constant) not yet scoped

**Deduction**: -8 for three HIGH risks + testing scope for artifact resolvers.

### 5. Testability: 18/20

**Strengths**:
- Tool functions are pure (no side effects beyond HTTP)
- HTTP calls can be mocked via `respx` (already in backend's dev dependencies)
- YAML parsing testable with fixtures
- Happy path and error paths (missing token, 401/403, 4xx envelope validation) all mockable
- NDJSON parsing testable with fixtures

**Gaps**:
- Glob pattern fixtures require filesystem mock (doable but adds setup complexity)
- JSON path resolution requires fixture JSON files + path language (JSONPath? Custom format?)
- Performance test for batch throughput (R-05) TBD

**Deduction**: -2 for artifact-resolver test setup complexity.

---

## Summary Scores

| Dimension | Score | Notes |
|-----------|-------|-------|
| Scope Clarity | 16/20 | Frozen contracts + explicit ACs; profile YAML layout ambiguity and FastMCP library choice gap. |
| Codebase Fit | 14/20 | Ingest endpoints proven; MCP service scaffolding TBD, no existing pattern skill. |
| Complexity | 15/20 | Core NDJSON/batch logic simple; artifact resolvers and glob validation add branching. |
| Risk & Mitigation | 12/20 | Three HIGH risks (profile layout drift, glob injection, token secrets); all mitigable but require discipline. |
| Testability | 18/20 | Pure functions, mockable HTTP, fixtures ready; artifact-resolver fixtures add setup complexity. |
| **TOTAL** | **75/100** | Feasible; mid-range complexity; mitigable risks. GO-WITH-CONDITIONS recommended. |

---

## Verdict

**GO-WITH-CONDITIONS**

### Rationale

ING-04 is **buildable and featurally complete** against frozen backend contracts (ING-02, ING-03). The high-level tool logic is straightforward, and core patterns (NDJSON parsing, batching, HTTP retry) are well-established in the backend. The reference implementation model (carry-over + port) reduces design work.

However, **three HIGH-severity risks** require explicit resolution before implementation:

1. **Profile YAML layout drift (R-04)**: Story assumes `.harness/profile.yaml`, but ING-10's canonical layout uses committed `.harness/program.yaml`. Needs decision: accept both layouts in tool logic, or gate on ING-10 completion?
2. **Glob pattern / JSON path injection (R-06)**: User-controlled patterns in profile.yaml must be validated (no `../`, no arbitrary JSON path traversal). Requires explicit allowlist or sandbox.
3. **Token secret handling (R-07)**: Every tool invocation must ensure bearer token never reaches logs, error responses, or stack traces. Needs logging-config discipline + test assertion.

### Blocking Issues

None. All risks are mitigable via code review gates + unit tests.

### Conditions

Before implementation begins:

1. **Resolve C-01** (FastMCP library choice): Provide PyPI package name or GitHub reference for the `agentrise_mcp` reference implementation. Code review must verify entry point (`python -m agentrise_mcp.server`) and console script (`agentrise-mcp`) work as promised.
2. **Decide on YAML layout (R-04)**: Accept both `.harness/profile.yaml` (local dev) and `.harness/program.yaml` (ING-10 canonical) in tool logic? Or gate on ING-10 completion? Document decision in PLAN.md.
3. **Explicit glob/JSON validation rules (R-06)**: Define allowlist for safe glob patterns and JSON path expressions. Add to PLAN.md before implementation.
4. **Add MCP service to build config**: Update `docs/config/project-commands.yaml::preflight` to include `services/mcp-server` install and test commands.

---

## Recommendations

### For Implementation Planning

1. **Scaffold `services/mcp-server/` as a sibling to `services/api/`**: Separate `pyproject.toml`, own `tests/unit/` suite, shared logging + retry patterns where applicable.
2. **Do NOT re-validate request rows**: MCP tools pass raw NDJSON to backend. The backend's Pydantic schema layer validates. This keeps MCP tools thin and the backend the source of truth for row validation.
3. **Test matrix for artifact resolvers**: Fixture-based tests for each of the four source kinds (glob-count, json-key-count, json-field-sum, constant). Use `tmp_path` pytest fixture for filesystem mocks.
4. **Guard token at entry to every tool**: Missing or empty token → return error result before any HTTP. Add unit test `test_push_activity_missing_token` and `test_push_artifacts_missing_token`.

### For Code Review Gates

1. Verify no hardcoded ingest endpoint URL (reference ADR-0013 + fixture test).
2. Verify FastMCP version pin + any workarounds for transport/lifecycle noted in PR description.
3. Search PR diff for `INGEST_TOKEN`, env-var printing, stack-trace logging — all should be absent.
4. Verify `services/mcp-server/pyproject.toml` includes explicit timeout config (5s connect, 30s total).

### For Cross-Cutting Standards

- Add `mcp-patterns` skill if more MCP work is planned (ING-05 on deck); for this story, inline FastMCP reference in PLAN.md is sufficient.
- Align token-handling discipline with backend's own `ingest_auth.py` (no leakage, no echo).

---

## Evidence Summary

- **Codebase scan**: Confirmed ING-02/ING-03 endpoints live, auth patterns ready, ingest infrastructure ready for consumption.
- **Pattern review**: Retry, NDJSON parsing, batching, token validation patterns all reusable from backend or testable via mocks.
- **Risk assessment**: Mitigable via code discipline + tests. No architectural blockers.
- **Feasibility**: Score 75/100 → GO-WITH-CONDITIONS. Conditions are process gates, not technical blockers.

---

## Report Artifacts

- **Research report file**: `/Users/pratik.pawar/Desktop/dashboard/docs/research/ING-04.md` (this document)
- **Feature state directory**: `/Users/pratik.pawar/Desktop/dashboard/docs/features/ING-04/` (to be created with state.json)
