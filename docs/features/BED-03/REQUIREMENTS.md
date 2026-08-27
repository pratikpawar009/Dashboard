# Feature: BED-03 — Rollup rebuild engine (idempotent upsert + full rebuild)

## Problem
No aggregation/rebuild layer exists yet between `usage_events` and the 10 rollup tables (7 program-scoped, 3 org-scoped) BED-01 created. `app/api/ingest.py`'s `_persist()` is a TODO stub with no rollup side-effect. Without a rebuild engine, every downstream dashboard read (OVW-01..04, PGD-01..06, SHP-02..06) either reads stale/absent rollup rows or each consumer re-derives aggregates independently — inconsistent numbers, and retried ingest writes would double-count events into any hand-rolled incremental-patch logic.

## Outcome
Two service functions — `rebuild_program_rollups(session, program_id)` and `rebuild_org_rollups(session)` — fully re-derive their respective rollup tables from `usage_events` alone, callable by any ingest write path (ING-02, ING-06). A rebuild run twice on the same event set produces byte-identical rollup rows (idempotent); a rebuild scoped to program `P` never touches another program's rollup rows; and a rebuild over 5,000 `usage_events` rows completes in ≤2s.

## Constraints
- `app/core/db.py` (session factory) does not exist yet — this story creates it (research condition 1; blocking for implementation). Both this story's rebuild functions and any future route must use the one factory.
- The idempotency anchor is `usage_events`'s unique constraint on `(program_id, session_id, cmd_ts)` (`app/models/ingestion.py`) — must not be loosened or bypassed by rebuild logic.
- Rebuild functions have no HTTP route of their own (per story Security NFR) — they are internal service functions invoked from the bearer-token-authenticated ingest write paths (ING-02, ING-06); no route handler is added in this story.
- Story's Test-mapping cites a stale `backend/app/services/ingest.py` path (pre-dates the `backend/` → `services/api/` correction BED-02 already made for its own story). This PRD settles the real module as `services/api/app/services/rollup_rebuild.py` — see § Addressing Research Conditions C-1 and **BED-03-FR-1**.
- Schema is the 18-table `db-schema` contract (`docs/requirements/data.md`); story prose's "17-table shape" is stale and already resolved by research (§ Resolved clarifications, 2026-08-27) — no schema action needed, AC1/AC2's per-table counts (7 program + 3 org = 10 rollups rebuilt) are correct as written.
- All 13 rollup-table mutations (7 program-scoped + 3 org-scoped, minus overlap accounted in AC1/AC2 scoping) for a single rebuild call must commit or roll back together — no partial rebuild left visible to a concurrent reader.

## Solution sketch
Add `services/api/app/services/rollup_rebuild.py` exporting `rebuild_program_rollups()` and `rebuild_org_rollups()`, each opening one `async with session.begin():` transaction that DELETEs the affected scope's existing rollup rows and INSERTs freshly aggregated rows computed from a single indexed scan of `usage_events`. Add `app/core/db.py` with an `async_sessionmaker`-based factory (`get_db()` `Depends()`), wired at app startup, shared by rebuild functions and (in a later story) routes. Every rebuild emits a `rollup_rebuild_completed` structured log event via the existing `JSONFormatter` seam. No route or ingest-route wiring is added here — ING-02/ING-06 call these functions from their own write paths.

## Addressing Research Conditions
- C-1 (Session factory, required): `app/core/db.py` is created in this story, exporting `engine = create_async_engine(settings.database_url)` and `SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)`, plus a FastAPI `Depends()` helper `async def get_db() -> AsyncIterator[AsyncSession]`. Wired once via `app/main.py`'s startup path (module-level `engine`, not per-request construction). Rebuild functions accept an injected `AsyncSession` parameter rather than constructing their own — see **BED-03-FR-1**.
- C-2 (Single-pass rebuild queries, required): resolved as **BED-03-FR-3** — one filtered scan of `usage_events` per scope (`WHERE program_id = :pid` for program scope, unfiltered grouped scan for org scope), using CTEs/window functions to derive all of that scope's rollup rows in one pass. Query plan documented inline in `rollup_rebuild.py`; index usage on `(program_id, ts)` verified via `EXPLAIN ANALYZE` captured in a test/dev note (not a runtime assertion — Postgres query plans aren't asserted in application code).
- C-3 (Idempotency test, required): resolved as **BED-03-FR-4** — `tests/unit/test_rollup_rebuild.py` (or `tests/test_rebuild_idempotency.py`) seeds `usage_events`, rebuilds, snapshots per-table row checksums + `COUNT(*)`, re-inserts the identical payload (asserts `UniqueViolation` on `(program_id, session_id, cmd_ts)`), rebuilds again, and asserts checksums/counts are byte-identical to the first run.
- C-4 (Performance benchmark, required): resolved as **BED-03-FR-5's companion test** — `tests/perf/test_rollup_rebuild_perf.py` (matching the `tests/perf/` directory BED-02 already established) seeds 5,000 `usage_events` rows for one program and asserts `rebuild_program_rollups()` wall-clock ≤2s via `time.perf_counter()`.
- C-5 (Observability instrumentation, required): resolved as **BED-03-FR-5** — `rollup_rebuild_completed` log event (`scope`, `program_id`, `duration_ms`, `event_count`) emitted once per rebuild call via the existing `app/core/logging.py` `JSONFormatter` seam (BED-02 already extended it to pass `extra={...}` fields through). Test suite captures logs and asserts emission + field shape.

## Scope
- In: `rebuild_program_rollups(session, program_id)` and `rebuild_org_rollups(session)` service functions in `services/api/app/services/rollup_rebuild.py`; `app/core/db.py` session factory + `get_db()` dependency, wired at app startup; full-replace (delete+insert, single transaction) logic for all 10 rollup tables; single-pass aggregation query design; idempotency test; ≤2s/5,000-event performance benchmark; `rollup_rebuild_completed` observability event.
- Out: wiring these functions into `app/api/ingest.py`'s `_persist()` / `ingest_event()` write path (ING-02 scope, per story Dependencies — this story delivers the callable contract, not the call site); a manual/admin HTTP rebuild-trigger endpoint (not requested, and would need its own bearer-token auth per Security NFR); `usage_events` retention/archival (BED-01 scope, explicitly out of that story too); chunked/paginated rebuild for programs exceeding 5,000 events (documented scaling assumption, deferred); any dashboard read query consuming these rollup tables (OVW-01..04, PGD-01..06, SHP-02..06 scope).

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/BED-03.md` for canonical wording.
New impl constraints introduced below:

**BED-03-FR-1** — Module path, function signatures, and session injection  *(extends AC #1/#2 with: exact module, signatures, DI mechanism)*

`services/api/app/services/rollup_rebuild.py` exports `async def rebuild_program_rollups(session: AsyncSession, program_id: str) -> RebuildResult` and `async def rebuild_org_rollups(session: AsyncSession) -> RebuildResult`, where `RebuildResult` is a small `dataclass`/`NamedTuple` carrying `scope: Literal["program", "org"]`, `program_id: str | None`, `duration_ms: int`, `event_count: int`. Neither function constructs its own session — callers inject one via `app/core/db.py`'s `get_db()`/`SessionLocal`. This settles the story's stale `backend/app/services/ingest.py` test-mapping path and the research's tentative `rebuild.py`/`rollup.py` naming: the module follows the `<domain>_<verb>.py` naming pattern BED-02 already established (`rollup_compute.py`, `guardrail_compute.py`), and is kept as a distinct module from `rollup_compute.py` because rebuild is session-based DELETE+INSERT orchestration, architecturally different from `rollup_compute.py`'s pure, DB-session-free compute functions (per BED-02 D-02/D-03 boundary — see that module's docstring).

**BED-03-FR-2** — Full-replace mechanics, not row-level patch  *(extends AC #1/#2/#4 with: exact delete+insert + transaction shape)*

Each rollup table in scope is rebuilt as `DELETE ... WHERE program_id = :pid` (program scope) or `DELETE ...` scoped to the org's full row set (org scope) immediately followed by `INSERT` of freshly computed rows, both statements inside one `async with session.begin():` block per rebuild call — never `UPDATE`/`ON CONFLICT DO UPDATE` upsert patches. Program-scoped deletes/inserts filter strictly on `program_id`, which is what AC #4's isolation guarantee (other programs' rows untouched) depends on.

**BED-03-FR-3** — Single-pass query design  *(extends AC #1/#2 with: query plan)*

`rebuild_program_rollups()` issues one filtered read of `usage_events WHERE program_id = :pid` (using the `(program_id, ts)` index) and derives all 7 program-scoped rollups' values from that one result set via CTEs/window functions — not 7 separate full scans. `rebuild_org_rollups()` issues one grouped read across all programs and derives all 3 org-scoped rollups similarly. Each query's business logic (which columns feed which rollup field) is documented as an inline comment/docstring per rollup table.

**BED-03-FR-4** — Idempotency verification  *(extends AC #3 with: test mechanics)*

Test seeds `usage_events`, calls the rebuild function, snapshots every affected table's row set (checksum + `COUNT(*)`), re-inserts the identical event payload (asserting it raises a unique-constraint violation on `(program_id, session_id, cmd_ts)`, caught at the caller/ingest boundary — rebuild itself is not responsible for catching this), calls the rebuild function again, and asserts the second snapshot is byte-identical to the first.

**BED-03-FR-5** — Observability event schema and emission point  *(extends the story's Observability NFR with: exact schema, timing mechanism, emission point)*

Each rebuild call emits exactly one `rollup_rebuild_completed` log line (not one per rollup table) via `logging.getLogger(__name__).info("rollup_rebuild_completed", extra={...})`, fields: `scope` (`"program"` or `"org"`), `program_id` (string for program scope, omitted/`None` for org scope), `duration_ms` (`int`, measured via `time.perf_counter()` spanning the full transaction), `event_count` (`int`, `usage_events` row count scanned for this rebuild). No PII fields (per security-baseline).

## Non-functional requirements

- Performance: `rebuild_program_rollups()` wall-clock ≤2s for a program with ≤5,000 `usage_events` rows (story NFR, Decision log 2026-08-26 assumption — no PRD-specified rebuild latency target exists; sized to NFR-002's 2s read-refresh budget as the nearest analog). Verified by **BED-03-FR-5**'s companion perf test (research condition 4).
- Performance: Per `.claude/rules/performance-baseline.md`: rebuild cost scales O(events for the affected program), not O(all events) — enforced by the `program_id`-filtered scan in **BED-03-FR-3**; no N+1 query pattern (one scan per scope, not one query per rollup table).
- Security: Per `.claude/rules/security-baseline.md`: no PII (user email, raw content) read or logged during rebuild — only event metadata (tokens, counts, dates, opaque ids). Rebuild functions expose no HTTP route; invoked only from ING-01-authenticated ingest write paths (ING-02, ING-06).
- Accessibility: N/A — backend service function, no UI surface.
- Observability: `rollup_rebuild_completed` structured log event on every rebuild call (schema in **BED-03-FR-5**), via the existing `app/core/logging.py` `JSONFormatter` seam (already extended by BED-02 to pass `extra={...}` fields through).

## Visual spec

Not applicable — `integrations.design = none`. Backend / API / data feature.

## Rollout plan
- **Strategy**: bang-bang — internal service functions with no route wired to them yet in this story; nothing live to migrate or stage.
- **Feature flag**: none — not a runtime-toggleable behaviour; no caller exists yet outside tests.
- **Backout plan**: revert `services/api/app/services/rollup_rebuild.py` and `app/core/db.py`; no production code path depends on them until ING-02/ING-06 wire the call site.
- **Success signal**: idempotency test (**BED-03-FR-4**) and performance benchmark (**BED-03-FR-5** companion, ≤2s/5,000 events) both pass — gates ING-02 and ING-06's `/arh-plan-requirements`.

## Documentation requirements
- **README updates**: `services/api/README.md` — document `rebuild_program_rollups()`/`rebuild_org_rollups()` as the rollup-rebuild contract (signatures, full-replace semantics, idempotency guarantee) and the `app/core/db.py` session-factory convention new modules must reuse.
- **Runbook**: none — no operational runbook for an internal service function with no route.
- **API reference**: none — no HTTP endpoints introduced by this story.
- **Inline code comments**: per-rollup-table aggregation logic documented in `rollup_rebuild.py` per **BED-03-FR-3**; `RebuildResult` fields documented per **BED-03-FR-1**; `rollup_rebuild_completed` event schema documented per **BED-03-FR-5**.
- **Examples / how-to**: none.

## Open questions

<!-- None open. Research (docs/research/BED-03.md) carried 0 unresolved clarifications  -->
<!-- into this phase; all 5 GO-WITH-CONDITIONS conditions are addressed in              -->
<!-- § Addressing Research Conditions above. Decisions are logged in                     -->
<!-- docs/stories/BED-03.md § Decision log.                                              -->
<!--                                                                                     -->
<!-- Kept as a comment deliberately: the `phase-preconditions` clarification gate        -->
<!-- treats ANY non-blank, non-comment line in this section as an unresolved open        -->
<!-- question and aborts the next phase. Prose saying "None" trips it.                   -->

## Approvals

| Role | Approver | Date | Verdict |
|---|---|---|---|
| Product Owner / BA | Pratik Pawar (pratik.pawar@apexon.com) | 2026-08-27 | APPROVE |
| Designer | — | 2026-08-27 | N/A — backend-only, `design_mode = none` |

Product Gate passed at `/arh-plan-requirements` Phase 4. Checklist evidence at approval time: 5/5 research conditions addressed with concrete mitigations; 0 unresolved `[NEEDS CLARIFICATION]` markers; no-placeholder check clean (the single grep hit cites the pre-existing `# TODO(implementation)` at `services/api/app/api/ingest.py:19`); test-case coverage audit `uncovered == []` across 17 cases (17 automatable), every `requirement_id` resolving to a real AC/FR/NFR id.
