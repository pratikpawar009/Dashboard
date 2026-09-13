# ADR-0012: `rebuild_org_rollups()` runs out-of-band from the ingest request path via FastAPI `BackgroundTasks`

- Status: Accepted
- Date: 2026-09-11
- Deciders: Pratik Pawar (PO+Architect, single-approver mode)

## Context

`docs/features/BED-05/DECISIONS.md` D-05 wrote down the ordering ING-02 was expected to implement as the FIRST caller of the `rollup-rebuild` contract: validate + upsert `usage_events`, commit, then call `rebuild_program_rollups(session, program_id)`, then call `rebuild_org_rollups(session)` — both synchronously, inline in the request path. That was BED-05's contract-side write-up, not a call site: `docs/requirements/data.md#rollup-rebuild` `commit_boundary_note` reflects it.

Research (`docs/research/ING-02.md` § Recommendations #2) contradicts it on measured evidence: `rebuild_org_rollups` is O(all events across all programs). Even after BED-05 D-01's SQL-aggregate rewrite it is the single call whose cost keeps scaling with the accumulated `usage_events` size (BED-05 measured 417 ms → 3,864 ms across 20k → 160k rows) — while `rebuild_program_rollups` remains bounded by one program's own events (BED-05 measured 455.6 ms p95 at 5k in-program / 20k total). Keeping the org call inline over-couples every activity push's p95 to the whole-org table size and leaves no residual budget for the ≤3 s NFR (`docs/features/ING-02/REQUIREMENTS.md` § NFR Performance, C-8).

Three mechanisms were considered for pushing the org rebuild off the request path:

1. **FastAPI `BackgroundTasks`** — response is returned first, then a per-request callable runs in the same process before the connection is closed. Zero new dependencies, integrates with the request lifecycle, uses a fresh `AsyncSession` from `SessionLocal` (the request-scoped one is closed by then).
2. **`asyncio.create_task` fire-and-forget** — no supervisor; a lost reference silently drops the task, and exceptions vanish into the loop's default handler. No lifecycle tie to the request.
3. **New bounded thread/task queue** — a new subsystem (queue, workers, backpressure); over-engineered for a call that is already atomic (BED-05 AC-2) and already idempotent (full re-derive).

## Decision

The ingest request path calls `rebuild_program_rollups(session, program_id)` **synchronously** after `usage_events` is committed, matching BED-05 D-05 for the program-scope leg. The org-scope leg is dispatched **out-of-band** via **FastAPI `BackgroundTasks`**: the route handler adds a task that, after the 200 response is sent, opens its own `AsyncSession` from `SessionLocal` and calls `rebuild_org_rollups(session)` inside that session's transaction, then closes it. The response's `rollup_summaries` field carries the program-scope `RebuildResult` only; the org-scope rebuild logs its own `rollup_rebuild_completed` event via BED-05's existing emitter.

`docs/requirements/data.md#rollup-rebuild` `commit_boundary_note` is updated to reflect this ADR (ING-02 T-17 / C-11): the caller-side ordering is (1) commit `usage_events`, (2) sync `rebuild_program_rollups`, (3) enqueue `rebuild_org_rollups` as a background task. Downstream ingest stories (ING-04 MCP, ING-06 CLI, ING-09 scheduled) that route through `POST /api/ingest/files` inherit this ordering for free; they do not re-decide it.

## Consequences

**Positive**

- Removes the single unbounded-cost step from the request path. NFR p95 ≤ 3 s at 160k accumulated rows becomes feasible on the measured evidence — the residual budget after validation + chunked upsert + `rebuild_program_rollups` (~455 ms p95 at 20k) is ~2.5 s.
- Concurrency at the org-scope layer remains handled by BED-05 AC-1's `ON CONFLICT (org_id) DO UPDATE` — running the same call in a background task does not change the shape of the write, only its position relative to the HTTP response boundary.
- One `AsyncSession` per background task, not shared with the request-scoped session — no lifetime coupling between the response and the org rebuild.

**Negative**

- The response can return 200 while a subsequent `rebuild_org_rollups` call raises inside the background task. The caller sees success; the org rollup is stale until the next successful ingest push (any program) rebuilds it. Same divergence shape BED-05 D-05 flagged for the sync path; here the response is committed by design, not swallowed. Background-task exceptions are logged via `rollup_rebuild_completed`'s existing failure branch (or, if `rebuild_org_rollups` never emits one, a defensive `logger.exception(...)` inside the task wrapper — no PII, program_id-less because the org call has no program scope).
- Response's `rollup_summaries` no longer includes the org-scope `RebuildResult`. Downstream stories that expected to read it from the response body (none, per `docs/requirements/api.md#ingest-files-api` `consumed_by: [ING-04, ING-06, ING-09]`, all of which are MCP/CLI callers whose contracts do not require org-scope in the response) are unaffected — but this is a contract-shape change from BED-05 D-05's implied ordering.
- Background tasks run in the same process. A worker crash mid-task loses that task with no retry. Accepted: the rebuild is idempotent (full re-derive) and the next successful ingest push rebuilds it. This deliberately trades stronger "org rollup consistent immediately after push" for the p95 NFR; the ledger-of-events source of truth (`usage_events`) is never affected.

**Reversible?**

Yes — mechanical. Reverting to the inline sync call is a one-line edit in `services/api/app/api/ingest_files.py` (or the service's dispatch helper) plus removing the background-task wiring. No data migrated under this choice; no persistent state depends on the mechanism.
