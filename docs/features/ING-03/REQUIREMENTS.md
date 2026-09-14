# Feature: ING-03 — POST /api/ingest/artifacts

## Problem

The Artifacts Generated panel (per `docs/prd/ai-sdlc-adoption-dashboards.md` §8.4, `program_artifacts` schema) and every downstream governance view that renders per-type artifact counts have no server-side write path. `program_artifacts` was created by BED-01 migration `001_initial_schema.py` with unique `(program_id, type)`, but no endpoint pushes rows into it. The MCP `push_artifacts` tool (ING-04, downstream) has no target contract to code against, and manual entry is not an option because the counts must update on every commit-time hook fire.

## Outcome

`POST /api/ingest/artifacts` accepts a bearer-token-authenticated `{program_id, kind: "artifacts", counts, as_of}` envelope, validates every `counts` key against the 5 canonical types (`prd`, `user_story`, `test_case`, `arch_diagram`, `api_spec`) at the router tier, and upserts the listed types into `program_artifacts` in a single transaction. Idempotent (same payload → same end state), partial-payload-safe (omitted types left unchanged, not zeroed), and never triggers `rebuild_org_rollups()` (ADR-0012 does not apply — `program_artifacts` is a direct counts table with no rollup dependency). Field-set contract with the `ingest-artifacts-api` consumer (ING-04's `push_artifacts` MCP tool) is enforced via `docs/requirements/api.md#ingest-artifacts-api`.

## Constraints

- Auth: bearer-token only via existing `ingest-token-auth` contract (ING-01 shipped, `services/api/app/core/ingest_auth.py`); never session-cookie (per NFR-006).
- Data source of truth: `program_artifacts` per `db-schema` contract (BED-01 shipped, unique `(program_id, type)`, `type` ∈ {`prd`, `user_story`, `test_case`, `arch_diagram`, `api_spec`}, `count`, `as_of_timestamp`). No migration required — table already exists.
- Envelope-kind gate `services/api/app/core/ingest_kind.py` is the SHARED owner (ING-02 D-03). This story extends `_ACCEPTED_KINDS` from `{"activity"}` to `{"activity", "artifacts"}`; the module ships with ING-02 (`phase: review`, PR #296).
- ADR-0012 (`docs/adr/0012-ingest-org-rollup-out-of-band.md`) does NOT apply. `program_artifacts` is a leaf counts table with no rollup source relationship; this endpoint MUST NOT dispatch `rebuild_org_rollups()` or `rebuild_program_rollups()`.
- Router pattern established by ING-02 (`services/api/app/api/ingest_files.py`): raw-dict body via `await request.json()`, manual `await get_ingest_token(program_id=..., credentials=..., session=db)` (never `Depends()`, because `program_id` lives in the body), router-tier kind check BEFORE auth per `api.md` ordering.
- Verdict `GO` (92/100, 2026-09-13) — no research conditions to address.
- p95 latency budget: < 300 ms per request for ≤5-row upsert in a single transaction, no rollup rebuild (story NFR, verbatim).

## Solution sketch

Add a new `@router.post("/artifacts", ...)` handler on the shared `/api/ingest` prefix in `services/api/app/api/ingest_files.py`, dispatching to a new service `services/api/app/services/ingest_artifacts.py` (function `ingest_artifacts(db, program_id, counts, as_of, token_label)`). Router-tier flow mirrors ING-02: parse envelope → check `kind == "artifacts"` against `_ACCEPTED_KINDS` (400) → auth via `get_ingest_token(program_id=...)` (401/403) → validate every `counts` key against the 5-type frozenset (400, zero writes on failure). Service performs a single `pg_insert(program_artifacts).values(...).on_conflict_do_update(index_elements=["program_id", "type"], set_=...)` in one transaction and returns before any rollup dispatch (the service signature has no `on_org_rebuild` parameter, by construction). Request schema in a new `services/api/app/schemas/ingest_artifacts.py`. Structured JSON log event `ingest_artifacts_write` emitted once per completed write with fixed allowlist `{event, program_id, token_label, types_written}` — never user email, token hash, or request body.

## Scope

- **In**: new `POST /api/ingest/artifacts` route on the existing `/api/ingest` router; new `app/services/ingest_artifacts.py` (single-transaction idempotent upsert, no rollup dispatch); new `app/schemas/ingest_artifacts.py` (request `ArtifactCountsIn`, response `{"status": "ok"}` per Open question below); extension of `app/core/ingest_kind.py` `_ACCEPTED_KINDS` from `{"activity"}` to `{"activity", "artifacts"}` (coordination point with ING-02 — same-PR extension so `test_ingest_kind.py` exercises both kinds); structured log event `ingest_artifacts_write` with fixed field allowlist; write of the `ingest-artifacts-api` contract's response-shape field into `docs/requirements/api.md`.
- **Out**:
  - Any modification to `services/api/app/services/activity_ingest.py` (ING-02 owns; artifact path is a distinct service module).
  - Any dispatch of `rebuild_program_rollups()` or `rebuild_org_rollups()` — ADR-0012 does not apply to this story (see Constraints).
  - MCP tool / CLI ingester surface (ING-04 consumes the `ingest-artifacts-api` contract this story establishes).
  - Alembic migration — `program_artifacts` already exists (BED-01 migration 001).
  - UI for the Artifacts Generated panel — a separate downstream story renders `program_artifacts` reads.
  - Not a UI story. No dashboard mockup consumes this endpoint directly; the ING epic has no mockup in `docs/design/schema.json`.

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/ING-03.md` for canonical wording. New impl constraints introduced below:

**ING-03-FR-1** — Envelope-kind gate extension  *(extends AC-1 with: shared-module coordination)*

`services/api/app/core/ingest_kind.py` `_ACCEPTED_KINDS` is extended from `{"activity"}` to `{"activity", "artifacts"}` in the same PR that registers the `/api/ingest/artifacts` route. Ordering: extension lands before the route is wired, so the router-tier check accepts `kind: "artifacts"` at first request. `test_ingest_kind.py` is updated to exercise membership of both `"activity"` and `"artifacts"` explicitly, so an accidental revert to the singleton set fails the test suite. Router-tier check runs BEFORE auth per `api.md` ordering (400 on unknown kind, zero writes, no token lookup).

**ING-03-FR-2** — Canonical-type validation, request-tier, before DB write  *(extends AC-4 with: exact-string enum + pre-DB enforcement)*

Every key in the `counts` mapping is checked for exact-string membership in `frozenset({"prd", "user_story", "test_case", "arch_diagram", "api_spec"})`. Case-sensitive; no normalisation, no aliasing. On any key outside the set: response is 400, zero rows written, no partial commit. Check runs at the router / schema tier (Pydantic enum on the request model) so the service never sees an invalid key.

**ING-03-FR-3** — Single-transaction idempotent upsert  *(extends AC-5 with: ON CONFLICT semantics + no rollup dispatch)*

The service performs one `pg_insert(program_artifacts).values(rows).on_conflict_do_update(index_elements=["program_id", "type"], set_={"count": ..., "as_of_timestamp": ...})` inside one transaction. Same-payload re-POST yields the same end state (identical row count, identical values, no duplicates — enforced by the unique `(program_id, type)` constraint). The service signature has NO `on_org_rebuild` parameter and MUST NOT call `rebuild_program_rollups()` or `rebuild_org_rollups()` — ADR-0012 does not apply (see Constraints).

**ING-03-FR-4** — Partial-payload semantics: omitted types unchanged  *(extends AC-6 with: explicit non-zeroing contract)*

When `counts` lists a subset of the 5 canonical types (e.g., only `prd` and `test_case`), only the listed types are upserted. Omitted types' existing rows are neither deleted nor zeroed. The upsert statement's `values(rows)` list contains one entry per listed type only; the `ON CONFLICT DO UPDATE` set-clause never touches an omitted type's row. Behaviour verified by a test that POSTs `{prd: 3}`, then POSTs `{test_case: 5}`, then asserts both rows exist with their respective counts and `arch_diagram`/`user_story`/`api_spec` are unchanged (absent or previously-set).

**ING-03-FR-5** — Structured log event `ingest_artifacts_write`, fixed allowlist  *(extends story NFR Observability with: PII allowlist enforcement)*

Emit once per completed write. Fields — exact allowlist: `{event: "ingest_artifacts_write", program_id, token_label, types_written}` (`types_written` is the list of type strings actually upserted in this request). Never `user_email`, `token_hash`, the raw `counts` values, or the `as_of` timestamp. Mirrors ING-02's `ingest_write_completed` allowlist discipline (`app/services/activity_ingest.py`). A `test_ingest_artifacts_pii_logging.py` unit test captures emitted records and diffs field names against the whitelist (allowlist diff, not denylist).

## Non-functional requirements

- **Performance**: p95 < 300 ms per request for a single ≤5-row upsert in one transaction, no rollup rebuild (verbatim from story NFR). No accumulated-table-size dependency (unlike ING-02's `usage_events` p95): `program_artifacts` is at most 5 rows per program × ~O(programs), and the unique-index lookup for `ON CONFLICT` is O(log n). No perf-test seeding requirement.
- **Security**: Per `.claude/rules/security-baseline.md`: applies to the new endpoint. Bearer-token auth only via `ingest-token-auth` contract, program-scoped by `allowed_program_ids` (`"*"` wildcard, empty-list = allow-all, per ING-01). Never session-cookie (per NFR-006). Envelope-level program-scope check via `get_ingest_token(program_id=...)`; no per-row scope check needed (the artifacts envelope is single-program, unlike ING-02's per-row activity).
- **Accessibility**: N/A — backend HTTP endpoint, no UI surface.
- **Observability**: Per `.claude/rules/security-baseline.md` (no-PII-in-logs): fixed field allowlist on `ingest_artifacts_write` (FR-5). Log event name `ingest_artifacts_write` extends NFR-011's structured-logging convention (which named an RBAC/telemetry event set but no ingest-artifacts-specific event). Emitted at INFO level, once per successful write. No log emission on 400/401/403 denial branches — those go through the existing `ingest_token_auth_failed` event (ING-01) or the router's schema-validation error path.

## Visual spec

Not applicable — `integrations.design = none` for this backend/API story (ING epic has no mockup in `docs/design/schema.json`).

## Rollout plan

- **Strategy**: bang-bang — new endpoint, backwards-compatible (adds a route on an existing router; no existing caller displaced). Router registration is the single wire-up point.
- **Feature flag**: none. New route; enabling it is deploying it.
- **Backout plan**: revert the commit that adds the `@router.post("/artifacts", ...)` handler in `services/api/app/api/ingest_files.py` (endpoint returns 404); `program_artifacts` writes stop, existing rows unaffected. The `_ACCEPTED_KINDS` extension can stay or revert independently — an accepted kind with no route is harmless (unknown route → 404 before the kind check runs). No schema or data changes to revert.
- **Success signal**: `ingest_artifacts_write` events observed with a non-empty `types_written` list within 24h of first MCP `push_artifacts` invocation (ING-04); p95 `duration_ms` for the endpoint < 300 ms measured against production over the first 7 days.

## Documentation requirements

- **README updates**:
  - `services/api/README.md` — add `POST /api/ingest/artifacts` to the API table (precedent: ING-02 added `/api/ingest/files`, ING-10 added `/api/ingest/manifest`).
  - Root `README.md` — mirror the same one-line entry in the top-level API table.
- **Runbook**: none. Same operational posture as `/api/ingest/files` and `/api/ingest/manifest`; no new runtime concerns.
- **API reference**: `docs/requirements/api.md#ingest-artifacts-api` — pin the response shape (see Open questions Q-02 resolution). Current contract omits the response-body field; write it before ING-04 plans against it. Blocking write.
- **Inline code comments**: `services/api/app/api/ingest_files.py` — extend the module docstring to note the two routes (`/files` for activity, `/artifacts` for counts) share auth wiring but dispatch to distinct services. `services/api/app/services/ingest_artifacts.py` — module docstring stating explicitly that this service does NOT dispatch rollup rebuilds (ADR-0012 non-applicability, contrast with `activity_ingest.py`).
- **Examples / how-to**: none — internal contract; the MCP tool (ING-04) will document the caller side.

## Open questions

None — Q-01 and Q-02 resolved at Product Gate 2026-09-13 (see § Resolved questions).

## Resolved questions

- **Q-01 — endpoint path topology** — RESOLVED (Product Gate 2026-09-13, user): **single generic path** `POST /api/ingest/{kind}`. One router handler on the existing `/api/ingest` prefix takes `kind` as a path parameter and dispatches by kind — `"activity"` → `activity_ingest` service (existing, ING-02), `"artifacts"` → `ingest_artifacts` service (new). The story's `POST /api/ingest/artifacts` AC-1 wording is satisfied by the generic route because `kind="artifacts"` resolves to that exact URL. Consequence: the existing `POST /api/ingest/files` handler in `services/api/app/api/ingest_files.py` is retired in favour of the generic `POST /api/ingest/{kind}` in the same module (or a rename to `ingest.py`) — this is a coordinated refactor of a route already at `phase: review` (PR #296) and must be planned to preserve ING-02's shipped semantics byte-for-byte for `kind="activity"` (same request body, same response shape, same 400/401/403/413 ordering). Router-tier gate stays: `kind` path-param is validated against `app/core/ingest_kind.py` `_ACCEPTED_KINDS` BEFORE auth (400 on unknown kind, zero writes, no token lookup). A `kind` value of `"files"` is NOT accepted (backwards compat with the old `POST /api/ingest/files` URL is a plan-time decision — see § Rollout plan).
- **Q-02 — response shape** — RESOLVED (Product Gate 2026-09-13, user): mirror ING-02's `IngestFilesResponse` shape, keyed as `rows_upserted`. Response body is a symmetric envelope: `{rows_received: int, rows_upserted: int, rejections: []}` (204 becomes 200 with `rows_upserted = 0` if all keys are rejected — but the router-tier canonical-type check makes that path unreachable; `rejections` is included for symmetry with `/activity` and stays empty on the artifacts happy path). This supersedes the Solution-sketch and § Scope earlier mention of `{"status": "ok"}` — response is `{rows_received, rows_upserted, rejections}`. New Pydantic model `IngestArtifactsResponse` in `services/api/app/schemas/ingest_artifacts.py` mirrors `IngestFilesResponse` field-for-field. `docs/requirements/api.md#ingest-artifacts-api` gains the `response_body` field with this exact shape.

Decisions logged in `docs/stories/ING-03.md` § Decision log.

## Approvals

- **2026-09-13** — Product Owner (single-approver mode: PO + Designer + BA when one human): **APPROVE**
  - Feature Summary, FRs, User Flows reviewed
  - UI specs: N/A for this backend-only story (`integrations.design = none`)
  - Edge Cases, Open Questions, test-case completeness reviewed
  - No-placeholder check ✓ · `[NEEDS CLARIFICATION]` count=0 (Q-01, Q-02 resolved — see § Resolved questions)
  - Research verdict GO (no conditions to address)
  - Tracker subtask: pratikpawar009/Dashboard#298
  - **Test-case coverage GAP acknowledged** — user imposed a 2-TC cap at intake; TC-01 (idempotent-upsert happy path) + TC-02 (auth/validation denial matrix) cover AC-1..AC-6; FR-5 (log allowlist), NFR performance p95<300ms, and NFR observability event-name are intentionally deferred to implementation-time evidence and unit tests, not gated by the test-case manifest.
