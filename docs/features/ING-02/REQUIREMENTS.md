# Feature: ING-02 — POST /api/ingest/files — activity ingest

## Problem

The MCP `push_activity` tool, the manual CLI ingester, and the scheduled ingestion job (ING-04/ING-06/ING-09) have no server-side endpoint to receive `activity.jsonl` batches. `services/api/app/api/ingest.py` is an unregistered scaffold stub, and `app/main.py:78-88` still carries a dangling "will be registered by ING-02" comment. Every downstream dashboard tile that renders `usage_events`-derived rollups is dark until this endpoint ships.

## Outcome

`POST /api/ingest/files` accepts a bearer-token-authenticated `{program_id, kind:"activity", rows[≤5000]}` batch, upserts idempotently into `usage_events` on `unique(program_id, session_id, cmd_ts)`, and returns `{received, valid, inserted, updated, rejected[], rollup_summaries}`. Program-scoped rollups are rebuilt synchronously; org rollups are rebuilt out-of-band (see FR-1). A freshly captured activity row is visible on the developer's next dashboard load. Field-set contract with the six mockups is enforced via `docs/requirements/api.md#ingest-files-api`.

## Constraints

- Auth: bearer-token only via existing `ingest-token-auth` contract (ING-01 shipped, `app/core/ingest_auth.py:45`); never session-cookie.
- Data source of truth: `usage_events` schema per `db-schema` contract (BED-01 shipped). Additive migration required for `source` and `copilot_credits` columns (per Q-01 resolution).
- Rollup engine is FROZEN (BED-05 shipped 2026-09-09). This story consumes `rebuild_program_rollups(session, program_id)` and `rebuild_org_rollups(session)` from `app/services/rollup_rebuild.py`; no edits to that module.
- Postgres bind-parameter ceiling: 65,535. At 22 `usage_events` columns × 5,000 rows the naïve INSERT overflows — chunking is mandatory (see FR-2).
- Verdict `GO-WITH-CONDITIONS` (81/100, 2026-09-11) — every condition below is addressed in this PRD.
- p95 latency budget: ≤3s for a 5,000-row batch (validate + upsert + program rebuild), sized from BED-05's measured 4,805 ms `rebuild_program_rollups` at 160k rows plus validation/upsert overhead. NFR re-indexed to accumulated table size AND batch size (see NFR section, C-8).

## Solution sketch

Mirror `app/api/manifest.py` verbatim in shape: `APIRouter(prefix="/api/ingest")` in a new module `app/api/ingest_files.py`, raw-dict body access via `await request.json()` (never whole-body Pydantic bind), manual `await get_ingest_token(program_id=..., credentials=..., session=db)` because `program_id` lives in the body, two-tier validation (413 aborts with zero writes; per-row failures land in `rejected[]`). A new `app/services/activity_ingest.py` performs Python-side dedup on `(program_id, session_id, cmd_ts)`, chunks `pg_insert(...).on_conflict_do_update()` at a named constant ≤ 2,978 rows/statement, commits the write, then calls `rebuild_program_rollups(session, program_id)` synchronously. `rebuild_org_rollups(session)` is scheduled out-of-band (see FR-1). The unregistered `app/api/ingest.py` stub is deleted; router is registered in `app/main.py` at the site of the current 78-88 comment.

## Addressing Research Conditions

The research doc (`docs/research/ING-02.md`, verdict GO-WITH-CONDITIONS) enumerates its blocking items under `## Top 3 planning recommendations` (C-1..C-3) plus `## Recommendations for planning` (C-4..C-11). One bullet per condition with the concrete PRD-level mitigation:

- **C-1** — Chunk `pg_insert(...).on_conflict_do_update()` at a named module-level constant `_MAX_ROWS_PER_INSERT ≤ 2_978` (65,535 bind-param limit ÷ 22 `usage_events` columns), inside one transaction. Ceiling asserted by a test that reads the model's `__table__.columns` count and fails if a future column addition would silently exceed the limit. Mitigates Risk #4. → **FR-2**.
- **C-2** — Python-side dedup on `(program_id, session_id, cmd_ts)` (last-wins on collision, matching upsert semantics) BEFORE the upsert, so `ON CONFLICT DO UPDATE cannot affect row a second time` (`CardinalityViolation`) cannot abort the batch. Deduplicated rows count into `rejected[]` with distinct reason `"intra_batch_duplicate"`. AC-5's rejection enumeration is extended to include this reason. Mitigates Risk #5. → **FR-3**.
- **C-3** — Write the full `rows[]` field list into `docs/requirements/api.md#ingest-files-api` before ING-04/06/09 plan against it. Includes: (a) field names — raw `activity.jsonl` names on the wire, with the five API aliases for columns whose `usage_events` column names differ (per Q-01); (b) types per `db-schema`; (c) unknown-field policy — unknown fields on a row are dropped silently, not rejected (row still commits). Blocking write; scheduled as an implementation task in `/arh-plan-implementation`. Mitigates Risk #7. → **FR-4** + Docs section.
- **C-4** — Auth wiring mirrors `app/api/manifest.py` verbatim in shape: manual `await get_ingest_token(...)` call, not `Depends()`, because `program_id` is in the body. A fresh private `HTTPBearer(auto_error=False)` instance per module (never import `ingest_auth.py`'s private `_http_bearer`). → **FR-5**.
- **C-5** — Delete `app/api/ingest.py` (unregistered stub); create `app/api/ingest_files.py` with `prefix="/api/ingest"`. `app/schemas/activity.py` orphan handled explicitly: delete alongside the stub and update `.claude/skills/pydantic-patterns/SKILL.md` in the same task (SKILL.md currently cites the file as a canonical Pydantic example). Zero runtime risk — `/ingest/events` is 404 today. → **FR-6** + Docs section.
- **C-6** — Envelope `kind` gets ONE owning module (`app/core/ingest_kind.py` or equivalent, on the `app/core/role_map.py` shape) shared with ING-03. This story creates the module and validates `kind == "activity"` at request-level (AC-4 tier). Row-level `usage_events.kind` is stored verbatim, unvalidated (per Q-02). → **FR-7**.
- **C-7** — PII-logging discipline mirrors ING-10's `test_manifest_pii_logging.py`: fixed field allowlist on `ingest_write_completed` = `{program_id, rows_received, rows_inserted, rows_updated, rows_rejected, duration_ms}` — never `user` (email), `command`, or `feature`. Rejection reasons in the response body carry row **index** + reason code only, never row content. New `test_ingest_pii_logging.py` asserts the allowlist. Mitigates Risk #11. → NFR Observability + FR-8.
- **C-8** — p95 latency NFR re-indexed to BOTH batch size AND accumulated `usage_events` table size (5,000 rows × up-to-160k accumulated events). Stated in NFR Performance below. Perf test must seed the target table size before measuring (C-10).
- **C-9** — `rebuild_org_rollups()` is REMOVED from the request path. `rebuild_program_rollups(session, program_id)` stays synchronous (small programs, table-size-indexed under BED-05 D-01, fits budget). Org rebuild runs out-of-band — implementation path pinned by `/arh-plan-implementation` to one of {startup + on-write scheduler tick, or a background worker}. This is a **delta from story AC-1**, which reads "run synchronously"; PRD supersedes on the strength of Research Rec #2 and Product Gate approval. Decision recorded here for gate review. Mitigates Risk #1 residual. → **FR-1**.
- **C-10** — Perf test (`tests/perf/test_ingest_files_perf.py`) seeds a pre-populated `usage_events` table (20k / 40k / 160k rows across programs) BEFORE running the 5,000-row push, mirroring BED-05's own seeded fixture. Empty-table perf tests are exactly why BED-03's cost curve was missed. → NFR Performance test note.
- **C-11** — Correct `docs/requirements/data.md#rollup-rebuild` `invariant:` text — "O(events for the affected program)" is false at org scope per BED-03's own `DATA-DESIGN.md:54`. Text-only correction to the invariant line; no code reopens BED-03/BED-05. → Docs section.

## Scope

- **In**: `POST /api/ingest/files` router + `activity_ingest` service; additive migration adding `source` + `copilot_credits` columns to `usage_events`; Python dedup + chunked idempotent upsert; program-scoped rollup rebuild synchronous in request path; org rebuild scheduled out-of-band; PII-safe structured logging; shared `ingest_kind` module for envelope validation; deletion of `app/api/ingest.py` stub + `app/schemas/activity.py` orphan + `pydantic-patterns` SKILL.md citation update; write of `rows[]` field list into `api.md#ingest-files-api`; correction of `data.md#rollup-rebuild` invariant text.
- **Out**:
  - Any modification to `app/services/rollup_rebuild.py` (BED-05 owns; frozen).
  - Retry / staleness semantics on rebuild failure — per BED-05 D-05, ING-02 accepts the shipped divergence (write commits, rebuild fails, 500 propagates); no bespoke recovery this story.
  - MCP tool / CLI ingester surface (ING-04, ING-06).
  - Scheduled ingestion daemon (ING-09).
  - Not a UI story. The 6 dashboard mockups consume rollups fed by this endpoint but do not invoke it directly. Field-set contract with the mockups is enforced via `docs/requirements/api.md#ingest-files-api` (see Addressing Research Conditions § C-3).
  - Carry-forward from research (not this story's to fix): `docs/config/stack-smoke.md` port 5432 vs dev container 5442 mismatch; ING-04's ACs read `files:`/`artifacts:` from `profile.yaml` but ING-10 moved both to `program.yaml`; `ingest_tokens.last_used_at` never updated (ING-01 lifecycle owner); `.claude/skills/pydantic-patterns/SKILL.md` cites `app/schemas/activity.py` (updated as part of C-5 in this story — carry-forward closes on ship); BED-05's carry-forward `app/main.py:78-88` dangling comment (closed when router registers in this story).

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/ING-02.md` for canonical wording. New impl constraints introduced below:

**ING-02-FR-1** — Out-of-band `rebuild_org_rollups()` scheduling  *(extends AC-1 with: `rebuild_org_rollups()` is NOT called synchronously in the request path)*

The request path calls `rebuild_program_rollups(session, program_id)` synchronously after commit, per BED-05 D-05 ordering. It does NOT call `rebuild_org_rollups(session)` inline. Org rebuild is scheduled out-of-band (mechanism selected in `/arh-plan-implementation`: on-write scheduler tick, or a background worker consuming a queue). Response's `rollup_summaries` field carries the program-scope `RebuildResult` only; org-scope rebuild reports via its own emitter downstream. This delta from AC-1 rests on Research Recommendation #2 (org rebuild is the single cause of the prior latency curve and concurrency 500s; even with BED-05's fixes, keeping it inline over-couples request success to org-wide table-size cost). Approved by Product Gate below.

**ING-02-FR-2** — Chunked upsert with bind-param ceiling assertion  *(extends AC-1 with: chunking + testable ceiling)*

Upsert chunk size = named module-level constant `_MAX_ROWS_PER_INSERT` ≤ 2_978 (derived from `min(5000, floor(65_535 / column_count))`). All chunks execute inside ONE transaction; commit-or-rollback is whole-batch atomic. A unit test computes `len(UsageEvent.__table__.columns) * _MAX_ROWS_PER_INSERT ≤ 65_500` (safety margin) and fails if a future column addition would silently break the ceiling.

**ING-02-FR-3** — Intra-batch dedup, last-wins  *(extends AC-5 with: new rejection reason)*

Before upsert, the row list is deduplicated in Python on the composite key `(program_id, session_id, cmd_ts)`; on collision, the last row wins (matching `ON CONFLICT DO UPDATE` semantics). Dropped rows count into `rejected[]` with reason enum `"intra_batch_duplicate"`. AC-5's rejection reason enumeration is thereby: `{"malformed_iso_date", "missing_required_field", "unrecognized_row_kind_ignored" (not rejected — see FR-7), "intra_batch_duplicate"}`. Reason codes carry row **index** in the input array, never row content.

**ING-02-FR-4** — `rows[]` wire-shape contract, additive migration  *(extends AC-1 with: field-name aliasing + additive columns)*

Wire uses raw `activity.jsonl` field names; API aliases the five that differ from `usage_events` column names (list settled in `docs/requirements/api.md#ingest-files-api` at implementation time, per Q-01). `source` and `copilot_credits` are STORED (not dropped) via an additive Alembic migration adding both columns to `usage_events` (nullable, no backfill). Unknown row-level fields are dropped silently; the row still commits.

**ING-02-FR-5** — Auth wiring shape mirrors `app/api/manifest.py` verbatim  *(extends AC-2/AC-3 with: no `Depends(get_ingest_token)`)*

`program_id` is parsed from the raw JSON body once, then passed to `get_ingest_token(program_id=..., credentials=..., session=db)` called directly as a coroutine (not `Depends()`) — the same reason `manifest.py` does it: `get_ingest_token`'s `program_id: str` has no `Path`/`Query` annotation and FastAPI would otherwise bind it as an undocumented required query parameter. A fresh private `HTTPBearer(auto_error=False)` instance per module; `ingest_auth.py`'s own private `_http_bearer` is never imported.

**ING-02-FR-6** — Stub cleanup + orphan handling  *(no AC extension — housekeeping preconditions)*

Same task set: (a) delete `services/api/app/api/ingest.py`; (b) delete `services/api/app/schemas/activity.py`; (c) update `.claude/skills/pydantic-patterns/SKILL.md` to remove/replace the citation of `app/schemas/activity.py`; (d) replace `services/api/app/main.py:78-88` comment with `include_router(ingest_files_router)`. Ordering: (a)+(b)+(c) land in the same PR as (d); no orphan reference survives commit.

**ING-02-FR-7** — Envelope `kind` shared vocabulary module  *(extends AC-4 with: shared owner; extends AC-5 with: rewording)*

New module `app/core/ingest_kind.py` (or equivalent) owns the envelope `kind` vocabulary, shared with ING-03. This story lists `{"activity"}` as its accepted envelope kind; ING-03 will add `"artifacts"` in its own scope. Envelope `kind != "activity"` fails at request level (AC-4 abort tier — 400 or 413-tier reject-all, exact status pinned in `/arh-plan-implementation`), zero writes. Row-level `usage_events.kind` is stored verbatim, unvalidated (per Q-02). AC-5 is thereby reworded to drop its "unrecognized `kind`" per-row rejection clause; unrecognized row-level `kind` values are stored, not rejected.

**ING-02-FR-8** — Structured log event `ingest_write_completed` with fixed allowlist  *(extends story NFR Observability with: PII allowlist enforcement)*

Emit once per completed request. Fields — exact allowlist: `{event: "ingest_write_completed", program_id, rows_received, rows_inserted, rows_updated, rows_rejected, duration_ms}`. Never `user`, `command`, `feature`, or any row content. `test_ingest_pii_logging.py` asserts the allowlist by capturing emitted records and diffing fields against the whitelist.

## Non-functional requirements

- **Performance**: p95 ≤ 3s for a 5,000-row batch measured against a pre-seeded `usage_events` table at up to 160k accumulated rows (validate + Python-dedup + chunked upsert + `rebuild_program_rollups` synchronous). Excludes `rebuild_org_rollups` (out-of-band, FR-1). BED-05 measured `rebuild_program_rollups` p95 = 455.6ms at 5k in-program / 20k total; validation + upsert budget = ~2.5s residual. Perf test (`tests/perf/test_ingest_files_perf.py`) MUST seed the table to each target size before measurement (C-10) — empty-table perf tests hid the BED-03 cost curve and cannot repeat.
- **Security**: Per `.claude/rules/security-baseline.md`: applies to the new endpoint. Bearer-token auth only, program-scoped by `allowed_program_ids` (`"*"` wildcard, empty-list = allow-all, per ING-01). Request/row payload is confidential individual-activity detail per PRD Data Classification.
- **Accessibility**: N/A — backend HTTP endpoint, no UI surface.
- **Observability**: Per `.claude/rules/security-baseline.md` (no-PII-in-logs): fixed field allowlist on `ingest_write_completed` (FR-8). Rejection reasons in response body carry row index + reason code only, never row content. `test_ingest_pii_logging.py` asserts both.

## Visual spec

N/A — backend HTTP endpoint, no UI surface.

## Rollout plan

- **Strategy**: bang-bang — new endpoint, backwards-compatible (adds a route; no existing caller is displaced). Router registration is the single wire-up point.
- **Feature flag**: none. New route; enabling it is deploying it.
- **Backout plan**: revert the router-registration commit in `app/main.py` (endpoint returns 404); usage_events writes stop, existing rows unaffected. Additive `source`/`copilot_credits` migration stays (nullable, forward-compatible).
- **Success signal**: `ingest_write_completed` events observed with `rows_inserted > 0` within 24h of first MCP/CLI push; p95 `duration_ms` ≤ 3000 against production `usage_events` size.

## Documentation requirements

- **README updates**:
  - `services/api/README.md` — add `POST /api/ingest/files` to the API table (precedent: ING-10 added `/api/ingest/manifest`).
  - Root `README.md` — mirror the same one-line entry in the top-level API table.
- **Runbook**: none. Same operational posture as `/api/ingest/manifest`; no new runtime concerns.
- **API reference**: `docs/requirements/api.md#ingest-files-api` — write the full `rows[]` field list (C-3), including field names + aliases, types, and unknown-field policy. Blocking write.
- **Inline code comments**: `app/api/ingest_files.py` module docstring mirroring `app/api/manifest.py`'s explanation of manual `get_ingest_token()` wiring (FR-5) and PII allowlist (FR-8).
- **Examples / how-to**: none — internal contract; MCP/CLI (ING-04/06) will document the caller side.
- **Data contract correction**: `docs/requirements/data.md#rollup-rebuild` `invariant:` line — replace "O(events for the affected program) per write" with wording that reflects BED-03 DATA-DESIGN.md:54 (org rebuild is O(all events), program rebuild is O(events for the affected program)). Text-only. (C-11)
- **Skill correction**: `.claude/skills/pydantic-patterns/SKILL.md` — remove/replace citation of `app/schemas/activity.py` (deleted in FR-6). Same PR.

## Open questions

None — all research-time clarifications resolved and recorded in `state[ING-02].clarifications` (Q-01/Q-02/Q-03, answered 2026-09-09).

Decisions logged in `docs/stories/ING-02.md` § Decision log.

## Test strategy

Downstream `test-case-agent` will generate structured test cases for AC-1..AC-6 in Phase 2.

**Operator directive — test-case count cap = 2** (soft override, below the AC×1 baseline). Rationale: the six ACs collapse to two highest-value scenarios: (a) end-to-end idempotent upsert + program rebuild + response shape (covers AC-1, AC-6, envelope-kind AC-4 tier, and Python dedup AC-5 reason), and (b) auth/authz + row-cap denial paths (covers AC-2, AC-3, AC-4 413 branch, and AC-5 per-row rejection enumeration). Consolidating avoids duplicative fixture setup; residual coverage (perf test C-10, bind-param ceiling test C-1, PII allowlist test C-7) rides as targeted unit tests scheduled in `/arh-plan-implementation`, not as AC-mapped test cases. Downstream tracking should read the below-baseline count against this directive, not as missing coverage.

## Approvals

- **2026-09-11** — Pratik Pawar (PO + Designer + BA, single-approver mode covers all when one human): **APPROVE**
  - Feature Summary, FRs, User Flows reviewed
  - UI specs reviewed in `DESIGN.md`: N/A for backend-only feature (no epic in `docs/design/schema.json`)
  - Edge Cases, Open Questions, test-case completeness reviewed
  - No-placeholder check ✓ · `[NEEDS CLARIFICATION]` count = 0
  - Research verdict GO-WITH-CONDITIONS (all 11 conditions C-1..C-11 addressed above)
  - **FR-1 delta from story AC-1 reviewed and accepted** (org rebuild out-of-band per Research Rec #2, supersedes BED-05 D-05 for ING-02's request-path behaviour)
  - **Test-case coverage gap accepted** — 2-cap operator directive; FR-4 / FR-6 / NFR-performance dispositioned to `/arh-plan-implementation` per `docs/test-cases/ING-02.json` `coverage_audit.operator_directive.uncovered_disposition`
  - Tracker subtask: pratikpawar009/Dashboard#292
