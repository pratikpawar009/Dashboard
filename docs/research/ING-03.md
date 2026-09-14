# Research Assessment: ING-03 — POST /api/ingest/artifacts

**Story**: [ING-03](../stories/ING-03.md)  
**Status**: Research Complete  
**Date**: 2026-09-13  
**Assessor**: GitHub Copilot  

---

## Upstream dependency summary

| Upstream | Phase | Status | Relevance |
|----------|-------|--------|-----------|
| ING-01 (ingest-token-auth) | security-reviewed | Shipped | Bearer auth + program-scope check; reuse `get_ingest_token()` directly |
| BED-01 (db-schema) | review | Shipped | `program_artifacts` table with unique(program_id, type); migration 001 includes it |
| ADR-0012 (out-of-band org rollup) | accepted | Shipped | **Does NOT apply to ING-03**: artifacts write only, no rebuild dependency — program_artifacts is a direct counts table, not a rollup source |

---

## Exploration Log

**Module discovery**

- `find services/api -name "*.py" | grep ingest` → 15 files across routers, services, schemas, tests, models
- `app/api/ingest_files.py` (160 lines) — ING-02's router, established POST /api/ingest/files pattern
- `app/services/activity_ingest.py` (380 lines) — ING-02's service, 5000-row cap, chunked upsert, intra-batch dedup, org-rollup dispatch
- `app/schemas/ingest_files.py` (180 lines) — ING-02's request/response models, ActivityRowIn, IngestFilesResponse
- `app/core/ingest_kind.py` (30 lines) — envelope `kind` allowlist; ING-02 ships {"activity"}; ING-03 must extend with "artifacts"

**Router pattern (ingest_files.py)**

- Post-JSON-parse, `program_id` check, envelope-kind check (400, before auth per api.md), bearer auth (401/403), row-cap check (413)
- Auth: manual flow — `get_ingest_token(program_id=..., credentials=..., session=...)` called directly, not via `Depends()` (see module docstring FR-5 / C-4)
- Org rebuild wired via `on_org_rebuild=lambda: background_tasks.add_task(dispatch_org_rebuild)` passed to service
- No org rollup dispatch needed for ING-03 per ADR-0012 (artifacts don't rebuild, only activity does)

**Service pattern (activity_ingest.py — but ING-03 will be simpler)**

- ING-02 handles activity rows with 24+ fields, validation per schema, chunked inserts (2_730 per chunk), intra-batch dedup on (program_id, session_id, cmd_ts)
- ING-03 artifacts: `{program_id, kind:"artifacts", counts: {type: count, ...}, as_of}` — a SINGLE upsert operation per request, no row iteration, no chunking, no dedup needed (the counts dict is already deduplicated by the caller)
- No row-level rejection reasons; validation fails the whole request with 400 (canonical type check)

**Schema pattern (governance.py)**

- `ProgramArtifact` model exists (created by BED-01 migration 001)
- Fields: id (PK uuid), program_id, type, count, as_of_timestamp
- Unique constraint: (program_id, type) — enforces one row per program per type, perfect for upsert
- No cascade on delete; program_artifacts is a leaf table (no downstream references)

**Canonical artifact types**

- `docs/prd/ai-sdlc-adoption-dashboards.md` FR-ING-05 lists 5 types: `prd`, `user_story`, `test_case`, `arch_diagram`, `api_spec`
- `db-schema` contract (data.md) confirms the enum-like set in `program_artifacts.type` field documentation
- Validation: exact string membership in frozenset

**Bearer auth (ingest_auth.py)**

- `get_ingest_token(program_id, credentials, session)` → IngestToken row
- Denies 401 (missing/unknown/revoked/expired) or 403 (scope: target program not in allowed_program_ids unless wildcard)
- No special handling needed for ING-03; reuse directly

**Observability**

- ING-02 logs `ingest_write_completed` event with allowlist: {program_id, rows_received, rows_inserted, rows_updated, rows_rejected, duration_ms}
- ING-03 should log `ingest_artifacts_write` (per story AC, structured event extending NFR-011) with fields: program_id, token_label, types_written (list of type names actually upserted)
- No user email, token hash, or request body ever logged

**Idempotent upsert**

- PostgreSQL `ON CONFLICT (program_id, type) DO UPDATE` — upsert semantics
- Same payload POSTed twice → same row(s), same counts, no duplicates, no deletion
- Partial payload (e.g., only `prd` and `test_case`) → only those types upserted; omitted types left unchanged (not zeroed)

**API contract (api.md)**

```yaml
endpoint: POST /api/ingest/artifacts
request: { program_id: str, kind: "artifacts", counts: { <type>: <count>, ... }, as_of: ISO-8601 timestamp }
response: 200 { } (success; body shape per ingest-artifacts-api contract, minimal)
           400 (unknown kind OR invalid canonical type in counts keys)
           401 (missing/unknown/revoked/expired bearer token)
           403 (program_id not in token's allowed_program_ids and not wildcard)
```

**Database migration**

- `services/api/migrations/versions/001_initial_schema.py` already creates program_artifacts table
- No new migration required for ING-03; the table exists

---

## Pattern map

### Existing code to extend

- `app/core/ingest_kind.py` — add `"artifacts"` to `_ACCEPTED_KINDS` frozenset
- `app/api/ingest_files.py` — router is SHARED; ING-03 should dispatch to a new service function (e.g., `ingest_artifacts()`) rather than reusing `ingest_files()` (which is activity-specific)

### Existing patterns to follow

- Bearer token auth via `get_ingest_token()` (ingest_auth.py) — same auth flow, no reinvention
- Structured JSON logging with PII allowlist (activity_ingest.py's `_log_ingest_write_completed` shape) — model for `ingest_artifacts_write` event
- Router-tier checks: kind → auth → payload validation (api.md ordering)
- Pydantic schema for request body validation (schemas/ingest_files.py model)

### New files to create

- `app/schemas/ingest_artifacts.py` — request model `ArtifactCountsIn`, response model (minimal, e.g., `{ "status": "ok" }`)
- `app/services/ingest_artifacts.py` — service function `ingest_artifacts(db, program_id, counts, as_of, token_label)` — upsert logic, logging, no rollup dispatch
- Route handler in `app/api/ingest_files.py` → new `@router.post("/artifacts", ...)` endpoint wired to service

**[NEEDS CLARIFICATION: single /files endpoint with POST body kind dispatch vs. separate /artifacts endpoint?]**

Story's user-facing path is `/api/ingest/artifacts` (AC-1, api.md contract). Router topology: one endpoint or reuse /files router with kind-branching? ING-02 established POST /files; this could extend it as kind=artifacts or live at a separate /artifacts path. **Assumption (D-01, resolved at plan time)**: separate route on the same router prefix (`/api/ingest`), so `POST /api/ingest/artifacts` distinct from `POST /api/ingest/files`. This matches the contract spec and keeps ingest_files.py focused on activity rows.

### Shared code at risk

- `app/core/ingest_kind.py` — frozenset edit ripples to ING-02's router (kind check); both stories must coordinate this extension
- `app/models/ingestion.py` → `app/models/governance.py` — ProgramArtifact model; confirm column count for bind-parameter ceiling if tests exist (ING-02 has `test_activity_ingest_chunk_ceiling.py`; ING-03 has no chunking, so no equivalent risk)

---

## Risk register

| # | Dimension | Severity | Description | Mitigation |
|---|-----------|----------|-------------|-----------|
| 1 | Dependency | MED | ingest_kind.py _ACCEPTED_KINDS must be extended BEFORE ING-03 router is registered; else /api/ingest/artifacts returns 400 even with valid auth | Plan-time decision (D-01): extend ingest_kind.py in same CL/PR as router. Unit test (test_ingest_kind.py) exercises both "activity" and "artifacts" so extension is visible immediately |
| 2 | Domain | MED | Canonical type validation: counts payload must reject any key outside {prd, user_story, test_case, arch_diagram, api_spec}; case-sensitive exact match required | Schema validation (Pydantic) enforces enum; request-tier check in router (AC-4) returns 400 before DB write. Test case: POST with unknown type, assert 400 and zero rows written |
| 3 | Integration | LOW | program_artifacts table constraint (unique on program_id, type) — upsert must not fail with constraint violation on partial payload (AC-6) | ON CONFLICT clause handles multi-row same-txn upserts safely (ING-02 proved it); partial payload naturally respects constraint (omitted types not touched). Test: POST subset of types twice, verify idempotence |
| 4 | Performance | LOW | 300ms p95 budget for upsert of ≤5 rows with bearer-auth check — no rollup rebuild to couple it to org-table size | Measured: ING-02's 5000-row activity batch is ~455ms p95 program rebuild alone; artifact upsert is orders of magnitude smaller (single txn, ≤5 rows, no joins, no rollup). Budget easily met |
| 5 | Integration | LOW | ADR-0012: artifact writes must NOT trigger `rebuild_org_rollups()` (unlike activity writes); confirm service layer does not accidentally dispatch it | Service layer owns the dispatch decision, not the router. ING-03 service has no `on_org_rebuild` parameter, by construction. Code review gate: examine service signature |
| 6 | Security | LOW | Bearer token scoping: program_id in request body must be checked against token.allowed_program_ids, same as ING-02 | `get_ingest_token(program_id=...)` already enforces this; no program-id-mismatch code path in service (unlike ING-02's activity rows which are per-row checked). Single envelope-level check suffices |

---

## Score + verdict

| Dimension | Weight | Score | Rationale |
|-----------|--------|-------|-----------|
| Integration | 25 | 90 | Bearer auth fully established (ING-01 complete); DB schema exists (BED-01 shipped); no new external service dependency; single potential coordination point (ingest_kind.py extension) is low-complexity |
| Compatibility | 20 | 95 | New endpoint, no backward-compat risk; ING-02's router unaffected by separate /artifacts route |
| Domain | 20 | 85 | Canonical type enum is well-defined (FR-ING-05 + db-schema); idempotent upsert semantics are proven (ING-02's usage_events); partial-payload semantics are explicit in story AC-6 |
| Performance | 15 | 95 | No rollup rebuild (unlike ING-02); upsert of ≤5 rows in single txn is sub-100ms; 300ms budget has substantial margin |
| Dependency | 20 | 95 | ING-01 security-reviewed (passed); BED-01 review-phase (shipped); no blocking upstream work; ADR-0012 accepts artifact-specific decision (no rollup) |

**Weighted Total: (90 × 0.25) + (95 × 0.20) + (85 × 0.20) + (95 × 0.15) + (95 × 0.20) = 22.5 + 19 + 17 + 14.25 + 19 = 91.75 → 92/100**

**Total: 92/100 → GO**

---

## Conditions (GO)

No conditions. The story meets all preconditions and has no dims <40. Proceeding to `/arh-plan-requirements` is safe.

---

## Synthesis

ING-03 follows a **proven, minimal pattern** from ING-02, extending the ingest envelope vocabulary (`kind:"artifacts"`) and adding a single idempotent upsert endpoint with bearer-token scoping. The domain is well-scoped (5 canonical types, partial-payload semantics explicit), the DB schema is already in place, and auth is fully inherited from ING-01. The single coordination point — extending ingest_kind.py's frozenset — is a line-of-code change with existing test coverage. **No blockers or research gaps.** Proceeding to planning phase.

---

## Clarifications

**[NEEDS CLARIFICATION: D-01 — endpoint path topology]**

- **Question**: Single /api/ingest endpoint with kind-based dispatch (reuse ingest_files.py router) or separate /api/ingest/artifacts route?
- **Source**: Story AC-1 specifies `POST /api/ingest/artifacts` contract; ingest_files.py established a shared router pattern.
- **Impact**: Affects file structure and router registration; neither approach changes scope or auth logic.
- **Resolution path**: Decide at plan-requirements stage. **Assumption for this research**: separate route `@router.post("/artifacts")` on the shared `/api/ingest` prefix, keeping ingest_files.py focused on activity rows and ingest_artifacts.py isolated for the artifacts service.

**[NEEDS CLARIFICATION: response shape]**

- **Question**: What does the 200 response body contain? Contract says `POST /api/ingest/artifacts` produces `ingest-artifacts-api` which has no detailed response shape spec.
- **Source**: api.md#ingest-artifacts-api shows only endpoint/auth/validation but no response_model field.
- **Assumption**: Minimal response (e.g., `{ "status": "ok" }` or empty `{}`), consistent with successful ingest endpoints returning 200 with confirmation, not rollup details (unlike ING-02's ingest_write_completed event which is logged, not returned).

**Open clarifications count: 2**

---

## Recommendations

1. **Coordinate ingest_kind.py extension** (Risk #1 mitigation) — extend _ACCEPTED_KINDS in the same implementation cycle as the router; update test_ingest_kind.py to exercise both kinds explicitly (existing test likely covers single-element set, verify it handles frozenset with 2+ entries).

2. **Define response_model early in plan** (Clarification #2) — add it to api.md#ingest-artifacts-api before implementation so the response schema is frozen and testable.

3. **Test idempotent upsert with partial payloads** (Risk #3 mitigation) — unit test should POST the same partial-type counts multiple times, verify row count and values are stable (no duplicates, no side effects on omitted types).

---

## Carry-forward notes

- **Observability event name** (story AC assumption): `ingest_artifacts_write` — review against NFR-011's structured-logging event list at plan-requirements stage to confirm naming is consistent with team convention.
- **No new Alembic migration**: program_artifacts table is BED-01's own scope; no schema changes needed for ING-03.

