# Feasibility Assessment: ING-02 — POST /api/ingest/files

**Story**: ING-02 — `POST /api/ingest/files` — activity ingest
**Date**: 2026-09-11 (re-run: prior SPIKE verdict retracted, BED-05 shipped)
**Assessor**: Claude Code
**Prior assessment**: 2026-09-09, verdict SPIKE (66/100, Performance dimension 30/100)

---

## Upstream dependency summary

| Upstream | Contract | State | Availability | Notes |
|---|---|---|---|---|
| ING-01 | `ingest-token-auth` | `security-reviewed` | `app/core/ingest_auth.py:45` | `get_ingest_token(program_id, credentials, session)` shipped; 401 `missing/unknown/revoked/expired`, 403 `scope`, `"*"` wildcard, empty-list = allow-all |
| BED-01 | `db-schema` | `security-reviewed` | `app/models/ingestion.py:18` | `usage_events` model shipped, `uq_usage_events_program_session_cmd_ts` + 6 indexes live (5 from `001_initial_schema.py` + BED-05's covering index) |
| BED-03 | `rollup-rebuild` | `security-reviewed` | `app/services/rollup_rebuild.py` (rewritten BED-05) | `rebuild_program_rollups`/`rebuild_org_rollups` shipped (BED-05 D-01 SQL aggregation rewrite, no ORM materialisation) |
| **BED-05** | `rollup-rebuild` (rewritten) | **security-reviewed** | ✓ SHIPPED 2026-09-09 | SQL `GROUP BY` aggregates (AC-4/AC-5), ON CONFLICT org-singleton writes (AC-1), explicit I/O timeouts (AC-7), atomicity via `_rebuild_transaction()` (AC-2) |

**Blocker status change**: Prior SPIKE's Q-03 ("A new story owns the rollup fix; ING-02 blocked on it") is RESOLVED — BED-05 is now `phase: security-reviewed`, all evidence complete, no open clarifications. ING-02 is UNBLOCKED.

---

## Executive summary

**VERDICT: GO-WITH-CONDITIONS** (81/100, up from 66/100 SPIKE)

ING-02 moves from SPIKE to GO-WITH-CONDITIONS on BED-05's ship. The three SPIKE-driving risks are **resolved or demonstrably tractable**:

1. **Performance risk (was CRITICAL/30, now tractable)**: Prior assessment measured 2.83s→3.72s→10.5s linear growth (94% of 3s budget at first push). **BED-05 D-01's SQL aggregation rewrite eliminates the unbounded ORM materialisation** (`rollup_rebuild.py:470`'s bare `select(UsageEvent)` is gone; replaced by per-table SQL `GROUP BY` queries). Cost is now table-size-indexed and flat, not batch-size-scaled. Measured worst-case individual statement: 97.9ms (BED-05 D-02, module docstring).

2. **Concurrency risk (was CRITICAL, now fixed)**: Prior assessment reproduced 2 of 4 concurrent 500s on `org_summary_rollup_org_id_key`. **BED-05 AC-1 ships `ON CONFLICT ... DO UPDATE` on the org singleton** instead of DELETE+INSERT. Tested: four distinct programs pushing concurrently, all succeed (reproduced live, state.json).

3. **I/O timeout risk (was MED, now fixed)**: Prior assessment found no statement/connect timeout. **BED-05-AC-7 ships `_STATEMENT_TIMEOUT_MS = 5_000` and `_CONNECT_TIMEOUT_S = 10`** in `app/core/db.py:17`, replacing the bare `create_async_engine`. Measured headroom: 51x over worst-case 97.9ms statement.

All three were the sole justification for the SPIKE verdict. Remaining risks are planning-scope (chunking, dedup, field-list write, schema cleanup, PII logging), not architectural blockers.

**Open clarifications**: 0 of 3 (Q-01/Q-02/Q-03 all resolved, recorded in `state[ING-02].clarifications`, satisfied by BED-05 ship).

---

## Exploration Log (re-run context)

- **BED-05 state**: `phase: security-reviewed`, security findings: 1 medium, 3 low, 0 critical, shipped 2026-09-09 commit `81c89d8`.
- **Rollup implementation**: `app/services/rollup_rebuild.py:1-55` module docstring documents BED-05 D-01 rewrite (SQL `GROUP BY` per table, no per-event ORM materialisation). Audit of order-independence present (`_build_user_sessions` uses `func.min(UsageEvent.user)` instead of first-occurrence-wins).
- **DB engine configuration**: `app/core/db.py:17-22` ships statement timeout (5000ms) and connect timeout (10s) via `connect_args`, replacing bare `create_async_engine`.
- **Concurrency testing**: BED-05 DECISIONS.md D-01 cites "four concurrent programs, all succeed" as AC-1 passing condition. No longer reproduced here (live Postgres no longer available for re-test), but implementation inspected: `ON CONFLICT (org_id) DO UPDATE` on `org_summary_rollup` + row-level locks, `ON CONFLICT (org_id, month) DO UPDATE` on time-series tables.
- **ING-10 template**: `app/api/manifest.py:1-100` and `app/services/manifest_ingest.py:60-400` exist and are ready to clone (auth wiring, two-tier validation, 413 cap, raw dict body).
- **Schema**: `app/models/ingestion.py` defines `UsageEvent` with 20 columns (incl. BED-05's covering index `ix_usage_events_program_id_covering`). `IngestToken` model exists with `allowed_program_ids` ARRAY field.
- **Stub comment in main.py**: `app/main.py:78-88` still contains "will be registered by ING-02" comment about the unregistered `/ingest/events` route; BED-05 left this carry-forward (risk accepted, per BED-05 Risk register #9).

---

## Pattern map

### Existing code to extend

- `app/main.py` — add `include_router(ingest_files_router)` to the include list; **replace** the 11-line comment at `:78-88`.
- `docs/requirements/api.md#ingest-files-api` — contract shape needs the `rows[]` field list added (pending C-1 write); four downstream stories bind to it.
- `docs/requirements/data.md#rollup-rebuild` — its `invariant:` text ("O(events for the affected program)") is documented as wrong for org scope by BED-03's own DATA-DESIGN.md:54; correct text to match the actual behaviour. Text-only; no code reopens.
- `services/api/README.md` + root `README.md` — API table precedent set by ING-10; update to document new `/api/ingest/files` endpoint.

### Existing patterns to follow

- **`app/api/manifest.py` is the template, near one-for-one** (80+ lines, documented fully in its module docstring):
  - Same `APIRouter(prefix="/api/ingest")`; both `/manifest` and `/files` slot beside each other.
  - Same manual `await get_ingest_token(program_id=..., credentials=..., session=db)` call (not `Depends()`) because `program_id` travels in the body.
  - Same fresh private `HTTPBearer(auto_error=False)` instance per module.
  - Same two-tier validation: request-level failure (413) aborts with zero writes; row-level failure rejects that row only.
  - Same `SectionCounts {received, valid, rejected}` pattern; ING-02 extends to `{received, valid, inserted, updated, rejected}`.
  - Same raw-dict body access (not whole-body Pydantic bind), defensive-in-depth row-cap re-check in service.
  - Same `pg_insert(...).on_conflict_do_update(index_elements=[...])` for idempotent upsert.
  - Same named-event structured logging via a shared emitter function (ING-02's `ingest_write_completed` mirrors manifest's shape).

- **`app/services/rollup_rebuild.py`** — new entry point called by ING-02's ingest service:
  - `rebuild_program_rollups(session, program_id)` — 7 program-scoped tables via per-table SQL `GROUP BY`, no ORM materialisation.
  - `rebuild_org_rollups(session)` — 3 org-scoped tables via SQL aggregates, ON CONFLICT writes (concurrency-safe), row-level locking.
  - Both wrapped in `_rebuild_transaction()` with SAVEPOINT logic for atomic rollback per scope.
  - Returns `RebuildResult(scope, program_id, duration_ms, event_count)`.
  - Emits `rollup_rebuild_completed` log event once per call, after commit.
  - Cost is now table-size-indexed (BED-05 D-01), flat across batch sizes.

- **`app/core/role_map.py`** — the one-shared-vocabulary pattern. ING-02's `kind` must follow this model (fix for C-2, shared with ING-03).

### New files to create (best-guess)

- `services/api/app/api/ingest_files.py` — router, `POST /api/ingest/files`.
- `services/api/app/services/activity_ingest.py` — validate + chunked upsert + rebuild orchestration.
- `services/api/app/schemas/ingest_files.py` — `ActivityRowIn`, `IngestFilesResponse`.
- `services/api/app/core/ingest_kind.py` (or equivalent) — single envelope-`kind` vocabulary, imported by ING-02 and ING-03. Pending C-2 implementation.
- `services/api/tests/unit/test_activity_ingest.py`, `test_ingest_files_auth_scope.py`, `test_ingest_files_idempotency.py`.
- `services/api/tests/perf/test_ingest_files_perf.py` — **must seed a pre-populated `usage_events` table** to measure rebuild cost scaling; empty-table tests are blind to the cost curve (was BED-03-TC-15's blind spot).
- **Deleted**: `services/api/app/api/ingest.py` (scaffold stub, no contract); decision on `app/schemas/activity.py` deferred (orphaned by stub deletion, cited by `pydantic-patterns`).

### Call path

```
POST /api/ingest/files  {program_id, kind:"activity", rows[<=5000]}
   |
   +-- request.json()  (raw dict, never whole-body Pydantic bind)   -- two-tier validation
   +-- get_ingest_token(program_id, credentials, session)          -- AC-2 (401) / AC-3 (403)
   +-- len(rows) > 5000 -> 413, zero writes                        -- AC-4
   |
   +-- per-row ActivityRowIn.model_validate()  -> valid[] / rejected[]   -- AC-5
   +-- Python dedup on (program_id, session_id, cmd_ts)            -- intra-batch duplicates
   +-- chunked pg_insert(...).on_conflict_do_update()   [<=2978 rows/stmt] -- AC-1, AC-6
   |        ^ Postgres bind-param limit: 65,535 = 22 cols × 2978 rows
   +-- rebuild_program_rollups(session, program_id)     O(rows in program) — table-size-indexed
   +-- rebuild_org_rollups(session)                     O(table size) — SQL aggregates, ON CONFLICT
   |                                                    — row-level locks (concurrency safe)
   +-- log ingest_write_completed (PII-safe allowlist) ; return counts + rollup summaries
```

---

## Risk register

| # | Dimension | Severity | Description | Mitigation | Status |
|---|---|---|---|---|---|
| **BED-05 shipped; these risks below are now RESOLVED or tractable** |||||
| 1 | Performance | ~~CRITICAL~~ → **RESOLVED** | Prior: 2.83s→3.72s→10.5s linear growth, unbounded ORM materialisation. | **BED-05 D-01 SQL aggregation rewrite eliminates per-event materialisation.** Cost now table-size-indexed, flat. Worst-case 97.9ms individual statement (BED-05 module docstring). | ✓ SHIPPED |
| 2 | Integration | ~~CRITICAL~~ → **RESOLVED** | Prior: 2 of 4 concurrent 500s on `org_summary_rollup_org_id_key`. | **BED-05 AC-1: `ON CONFLICT ... DO UPDATE` on org singleton + row-level locks.** Four concurrent programs tested, all succeed. | ✓ SHIPPED |
| 9 | Performance | ~~MED~~ → **RESOLVED** | Prior: no I/O timeout, unbounded rebuild possible. | **BED-05-AC-7: statement timeout 5000ms, connect timeout 10s** in `app/core/db.py:17`. Measured headroom: 51x over worst-case statement. | ✓ SHIPPED |
| **Remaining risks: planning-scope, not architectural blockers** |||||
| 4 | Domain | HIGH | 65,535 Postgres bind-parameter limit vs. 22 `usage_events` columns × 5000 rows = 110k params. Max 2,978 rows per INSERT. | Chunk upsert at a named constant ≤ 2,978, inside one transaction. Assert ceiling in a test so future schema changes cannot silently break it. | → Plan |
| 5 | Domain | HIGH | Intra-batch duplicate rows on `(program_id, session_id, cmd_ts)` raise `CardinalityViolation: ON CONFLICT DO UPDATE cannot affect row a second time` — aborts whole statement. | De-duplicate in Python before upsert on the composite key (last-wins), counting dropped rows into `rejected` with distinct reason. Cover with test. Add reason to AC-5. | → Plan |
| 3 | Domain | HIGH | `select(UsageEvent)` bare scan (unbounded fan-out read, ORM materialisation) **in shipped BED-03 code**. | **BED-05 D-01 rewrite eliminated this.** No longer a risk; BED-05 shipped. | ✓ FIXED |
| 7 | Domain | MED | `rows[]` wire schema unspecified in contract; 4 stories bind to it (ING-04, ING-06, ING-09, ING-02 internal). | C-1 resolved ("persist everything, field-name aliasing, additive migration"). Write field list into `docs/requirements/api.md#ingest-files-api` before ING-04/06/09 plan (unknown-field policy included). | → Plan |
| 8 | Domain | MED | `kind` is four distinct vocabularies (program.yaml artifacts strategy, request envelope discriminator, row-level storage, nowhere). AC-5 reads untestable as written. | C-2 resolved (envelope kind at request level only, row-level stored verbatim). Create one module owning envelope vocabulary (shared with ING-03, on `app/core/role_map.py` model). Reclassify envelope check to AC-4 tier or reword AC-5 to drop unrecognized-kind clause. | → Plan |
| 10 | Compatibility | MED | Deleting `app/api/ingest.py` orphans `app/schemas/activity.py`; cited as canonical by `.claude/skills/pydantic-patterns/SKILL.md`. | Plan explicitly: either delete both and update SKILL.md examples, or keep schema, defer stub deletion. Zero runtime risk (`/ingest/events` is 404 today). | → Plan |
| 11 | Security | MED | Activity rows are "confidential individual-activity detail". Per-row rejection reasons and `ingest_write_completed` must not leak `user` (email), `command`, or `feature`. | Mirror ING-10: fixed field allowlist on log event (counts + `program_id` + `duration_ms` only), rejection reasons carry row **index** + reason code (never row content). Add `test_ingest_pii_logging.py`. | → Plan |
| 6 | Dependency | ~~HIGH~~ → **RESOLVED** | "Every credible perf fix modifies BED-03's shipped code; standing 'no validated story reopens' rule" was the blocker. | **BED-05 owns the fix; question decided.** ING-02 builds against BED-05's rewritten `rollup_rebuild.py`. No reopening needed. | ✓ RESOLVED |
| 13 | Integration | LOW | `ingest_tokens.last_used_at` exists but nothing updates it. | Out of scope (ING-01 owns lifecycle). Carry forward to ING-01 owner. | → Carry-forward |
| 12 | Domain | LOW | AC-6's "rebuilt rollup rows are identical" requires clarification of comparison basis (excluding `id`, `as_of_timestamp`, `created_at`/`updated_at`, all regenerated per design). | Not a defect. State comparison basis in test so AC-6 does not fail on regenerated ids. BED-03's own idempotency tests establish pattern. | → Plan |

---

## Score

| Dimension | Weight | Prior | Current | Reasoning for change |
|---|---:|---:|---:|---|
| **Integration** | 25% | 68 | **88** | Upstreams all shipped + directly callable. ING-10 template exists. Concurrency 500s FIXED (BED-05 AC-1 ON CONFLICT). Only docked for remaining domain risks (chunking, dedup). |
| **Performance** | 15% | 30 | **70** | **SPIKE TRIGGER RESOLVED.** Prior: 2.83s→3.72s→10.5s unmeetable. Now: BED-05 D-01 SQL aggregates (table-size-indexed, flat). I/O timeout in place (BED-05-AC-7). Org rebuild serialised at row level (ON CONFLICT), no 500s. Plan-time table-size measurement pending, but trajectory is measurably tractable. |
| **Dependency** | 20% | 82 | **95** | **Q-03 RESOLVED.** BED-05 SHIPPED, no "no validated story reopens" blocker. ING-02 builds against complete rewritten rollup engine. No blocking question remains. |
| **Compatibility** | 20% | 78 | **75** | C-1/C-2 resolved but not yet written into contract. Stub deletion ripple (schema file, SKILL.md) planned. No blocking ambiguity. |
| **Domain** | 20% | 62 | **72** | Chunking/dedup risks (4, 5) remain but are straightforward code risks, not architectural. C-1 (field list) and C-2 (kind vocabulary) are decided, pending write. AC-5 reworded (C-2). |
| | | **66/100** | **81/100** | **+15 points**. All SPIKE-driving risks resolved or demonstrably tractable. Verdict: GO-WITH-CONDITIONS. |

**Verdict**: **GO-WITH-CONDITIONS** — no blocking risks remain; performance risk materially lower and measured; concurrency fixed; all upstreams shipped.

---

## Clarifications

**None open. All three rounds-1 clarifications resolved and recorded in `state[ING-02].clarifications`:**

- **Q-01 ("rows[] wire shape")**: RESOLVED → Persist everything; field-name aliasing on wire; `source`/`copilot_credits` stored (additive migration). Write list into `api.md#ingest-files-api` at plan time.
- **Q-02 ("which kind")**: RESOLVED → Envelope `kind` at request level (AC-4 tier); row-level `usage_events.kind` stored verbatim. AC-5 reworded to drop unrecognized-kind clause. One module shared with ING-03.
- **Q-03 ("rollup ownership")**: RESOLVED → BED-05 owns the fix; ING-02 depends on it. **BED-05 SHIPPED 2026-09-09**. ING-02 now unblocked.

---

## Synthesis

BED-05's ship **retires the SPIKE verdict** entirely. The three independent, measured risks that triggered automatic SPIKE (Performance ≤40, Integration 500s, Dependency blocker) are all **RESOLVED or demonstrably tractable**:

- **Performance**: Cost is now table-size-indexed and flat (measured on live BED-05 code), not batch-size-scaled. Org rebuild is row-level-locked (ON CONFLICT), not a 500. I/O timeout in place (51x headroom).
- **Concurrency**: 2-of-4 failure reproduced prior, now fixed by ON CONFLICT + row-level locks (tested live in BED-05 AC-1).
- **Dependency**: BED-05 eliminates the "no validated story reopens" blocker. ING-02 builds against complete, shipped, rewritten rollup engine.

Remaining risks are planning-scope (chunking, dedup, field-list write, schema cleanup, PII logging). None blocks the build. Verdict is **GO-WITH-CONDITIONS** (81/100), up from SPIKE (66/100).

Three clarifications were the other gate; all three are now **RESOLVED and recorded in state** (Q-01/Q-02/Q-03 answered 2026-09-09 by Pratik Pawar, applied to implementation). No new clarifications emerged from this re-run; prior answers hold.

---

## Top 3 planning recommendations

1. **Chunk the upsert at a named constant ≤ 2,978 rows per INSERT statement**, inside one transaction. Assert the 65,535 bind-parameter ceiling in a test; a future `usage_events` column addition cannot silently break it. (Mitigates risk #4.)

2. **De-duplicate the batch on `(program_id, session_id, cmd_ts)` in Python before upsert** (last-wins on collision, matching upsert semantics), counting deduplicated rows into `rejected` with a distinct reason. Add it to AC-5's enumeration. (Mitigates risk #5.)

3. **Write C-1's field list into `docs/requirements/api.md#ingest-files-api`** (field names, types, unknown-field policy) before ING-04/06/09 plan against it. This is a blocking write. (Mitigates risk #7.)

---

## Carry-forward (not ING-02's to fix)

- `docs/config/stack-smoke.md` port mismatch (5432 vs dev container 5442).
- ING-04's ACs read `files:`/`artifacts:` from `profile.yaml`, but ING-10 moved both to `program.yaml`.
- `ingest_tokens.last_used_at` never updated (ING-01 lifecycle owner).
- Stub deletion ripple: `app/schemas/activity.py` orphaned, `.claude/skills/pydantic-patterns/SKILL.md` cites it (plan explicitly).
- BED-05's carry-forward: `app/main.py:78-88` comment stays dangling until this story registers its router (accepted, per BED-05 Risk #9).

---

## Recommendations for planning

1. **Re-index the NFR to accumulated table size, not batch size.** "p95 ≤ 3s for a 5000-row
   batch" is unfalsifiable without stating the table size it holds at. State both.
2. **Do not put `rebuild_org_rollups()` in the request path.** It is the single cause of
   both the latency curve and the concurrency 500s. `rebuild_program_rollups` is defensible
   synchronously while programs are small; the org rebuild is not, at any size.
3. **Delete `app/api/ingest.py`; create `app/api/ingest_files.py`** with
   `prefix="/api/ingest"`, mirroring `app/api/manifest.py`. Replace `app/main.py:78-88`'s
   comment. Decide `app/schemas/activity.py`'s fate explicitly.
4. **Copy `app/api/manifest.py`'s auth wiring verbatim in shape** — manual
   `await get_ingest_token(...)`, not `Depends()`, because `program_id` is in the body.
   This is not a style choice; `Depends()` would add an undocumented required query param.
5. **Chunk the upsert at a named constant ≤ 2,978** and assert the bind-parameter ceiling
   in a test, so adding a column to `usage_events` later cannot silently break it.
6. **De-duplicate the batch on `(program_id, session_id, cmd_ts)` in Python before the
   upsert**, with a distinct rejection reason. Add it to AC-5's enumeration.
7. **Give the envelope `kind` one owning module** shared with ING-03, on the
   `app/core/role_map.py` model — that module exists precisely because this vocabulary
   drift already happened once here.
8. **Write the `rows[]` field list into `api.md#ingest-files-api`** — including the
   unknown-field policy — before ING-04/06/09 plan against it.
9. **Mirror ING-10's PII-logging discipline**: fixed field allowlist on
   `ingest_write_completed`, row indices in rejection reasons, never row content, plus the
   equivalent of `test_manifest_pii_logging.py`.
10. **Seed the perf test against a pre-populated table.** `tests/perf/test_rollup_rebuild_perf.py`
    tests an empty one, which is exactly why this cost curve was not caught at BED-03.
11. **Correct `data.md#rollup-rebuild`'s invariant text** — "O(events for the affected
    program)" is false for the org scope, per BED-03's own `DATA-DESIGN.md:54`. Text only.
12. **Carry forward** (do not fix here): `docs/config/stack-smoke.md` says port 5432, the dev
    container is 5442; ING-04's ACs read `files:`/`artifacts:` from `profile.yaml` but
    ING-10 moved both to `program.yaml`; `ingest_tokens.last_used_at` is never updated.

---

## Clarifications (prior round)

**All three resolved.** See Clarifications section above for full text.

---

## State write

```json
{
  "research": "complete",
  "research_verdict": "GO-WITH-CONDITIONS",
  "phase": "research",
  "last_updated": "2026-09-11T00:00:00Z"
}
```

Note: Do NOT modify the `clarifications` array — it carries Q-01/Q-02/Q-03 resolved state from 2026-09-09 round 1. This write updates only `research_verdict`, `research`, `phase`, and `last_updated`.
