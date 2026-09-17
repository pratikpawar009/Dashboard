# PLAN — PGD-04: Program command activity

Status: VALIDATED

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log). Four entries:
D-01 (data source: `usage_events`, never `program_commands` — the story's single highest-risk
choice, R-6/C-4), D-02 (no-404 empty response, deliberately inconsistent with the sibling
`/releases` route), D-03 (reuse `CommandsPanel`/`CommandEntry` from `personal_usage.py`, no new
schema module), D-04 (Next.js proxy route ships in this story per REQUIREMENTS.md § Scope). No
entry carries `blast:system`/`blast:data`/`rev:effectively-irreversible` — all four are
`blast:feature` / `rev:mechanical`, so none is promoted to a full ADR.

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan`.

### Module hierarchy

```
services/api/app/
├── services/program_commands.py               [NEW]
│   - input:  db: AsyncSession, program_id: str, range_value: str
│   - output: CommandsPanel (app.schemas.personal_usage)
│   - public: async fetch_program_commands(db, program_id, range_value) -> CommandsPanel
│   - reads usage_events only (D-01); mirrors personal_usage.py::fetch_commands_breakdown
│     with WHERE program_id=:program_id swapped for WHERE "user"=:user_id
├── schemas/personal_usage.py                    [MODIFIED — docstring only]
│   - no class change; co-consumer note added (D-03)
└── api/overview.py                              [MODIFIED]
    - adds GET /program-detail/{program_id}/commands as a 4th route on the existing router
    - calls program_visibility() once, NO ProgramSummary existence lookup (D-02)
    - calls fetch_program_commands(), logs program_commands_fetched

apps/web/src/
├── types/programCommands.ts                     [NEW] — wire type mirror
├── lib/programCommandsApi.ts                    [NEW] — server-only fetcher
│   - input:  programId: string, range?: string, opts?: {accessToken?: string}
│   - output: ProgramCommandsResult (ok | not_found | unauthorized | error)
└── app/api/proxy/program-detail/[program_id]/commands/route.ts   [NEW]
    - input:  incoming Request (dashboard_session cookie), path param program_id
    - output: NextResponse (200 CommandsPanel JSON | 401 session_expired | 502 upstream_error)
    - public: GET handler (Next.js Route Handler convention)
```

No navigation/routing map — no page/screen ships (REQUIREMENTS.md § Scope, backend-only).

## 3. Module Hierarchy

See § 2 above — the module hierarchy is included there per the pinned pointer format (§2 body
is the `tasks.json` pointer plus this narrative).

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md`. Summary: read-only aggregate over the
existing `usage_events` table via the existing `ix_usage_events_program_id_command` index; no
migration, no new table, no cache, no async/messaging surface.

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks`. Execution order derives from
`predecessors`; parallelism derives from the DAG. 14 tasks total (S/M/L split: 9 S, 5 M, 0 L).

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/PGD-04.md` § Risk register. HIGH/CRITICAL risks are addressed by a
task id below; MED/LOW risks inherit their mitigation from the research doc.

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|--------------|
| R-1     | HIGH     | T-03 (path settled: `/api/overview/program-detail/{program_id}/commands`, no PLAN action left — see Conditions below) |
| R-6     | HIGH     | T-01, T-05 (differential-range test #427 is the mandatory guard) |
| R-2     | MED      | T-03, T-04 (no-404 empty-shape behavior, D-02) |
| R-3     | MED      | T-01, T-02 (schema reuse, D-03) |
| R-4     | LOW      | T-01 (max-of-range `barStyle` formula, D-01/FR-3) |
| R-5     | LOW      | T-06 (perf test, single-query construction) |

No risk is carried forward as "accepted" — all six are addressed by a task above.

### Conditions for GO (research_verdict GO-WITH-CONDITIONS)

| Cond | Condition (verbatim, abbreviated) | Addressed by |
|------|----------------------------------|--------------|
| C-1  | Path decision: `/api/overview/program-detail/{program_id}/commands` (settled 2026-09-17) | T-03 (follows the settled path; no PLAN action needed beyond implementing it) |
| C-2  | Empty-program behavior: `200 {total_runs:"0", items:[]}`, no existence lookup, no 404 | T-03, T-04 |
| C-3  | Schema ownership: import from `personal_usage.py`, add co-consumer note, no `schemas/program_commands.py` | T-01, T-02 |
| C-4  | Data source: aggregate from `usage_events`, never `program_commands`; must carry the differential-range test | T-01, T-05 |
| C-5  | Frontend scope: state explicitly whether PGD-04 ships backend-only or scopes the component | T-12 (proxy ships per REQUIREMENTS.md § Scope; `CommandsActivity.tsx` explicitly NOT created — see § Cross-Feature Dependency Notes below) |

### Cross-Feature Dependency Notes

`ARC-01`, `DEV-01`, `PMD-01`, `EMD-01` consume `program-commands-api` (`docs/requirements/
api.md#program-commands-api`, filled by T-08) — none of those stories are in flight
concurrently with PGD-04; no cross-feature file contention. `CommandsActivity.tsx` (the panel
component rendering this contract) is explicitly out of scope for PGD-04 (REQUIREMENTS.md §
Scope) and is not claimed by any other RTM story as of this plan (verified 2026-09-17 against
ARC-01/DEV-01/PMD-01/EMD-01/PGD-05/06/07) — a follow-on frontend story must scope it against
this contract before it renders.

## 7. Test Strategy

| Layer       | Test path                                                    | TCs covered           | Notes |
|-------------|---------------------------------------------------------------|------------------------|-------|
| Integration | `services/api/tests/unit/test_program_commands_route.py`     | TC-01,02,03,04,06,07,08,09,10,11,12,13,14 | Route-level, mirrors `test_program_releases_route.py` naming/shape |
| Integration | `services/api/tests/unit/test_program_commands_route.py`     | TC-17                 | Structured-log assertion, folded into the route test file (T-07) |
| Unit        | `services/api/tests/unit/test_program_commands_service.py`   | TC-05, TC-15           | TC-05 (#427) is the mandatory differential-range guard (R-6/C-4) — asserts `7d`/`90d` totals differ on seeded multi-window data; TC-15 asserts computation independence from `personal_usage.py`'s commands panel |
| Performance | `services/api/tests/perf/test_program_commands_perf.py`      | TC-16                 | Budget: each of `7d`/`30d`/`90d` <2000ms at ≥5,000 seeded `usage_events` rows / ≥10 commands; single-query assertion (no N+1), mirrors `test_program_releases_perf.py` |
| Contract    | `services/api/tests/unit/test_program_commands_route.py`     | TC-14                 | Wire-type assertion: `count` raw int, `total_runs`/`command`/`barStyle` string types — folded into the route test file, not a separate contract-layer file (matches this repo's existing `type: contract` handling, which lives inside route test files, not a distinct test tree) |
| Frontend    | `apps/web/src/app/api/proxy/program-detail/[program_id]/commands/route.test.ts` | — (no TC id; proxy has no story TC of its own, mirrors token-trend proxy's own untested-by-TC precedent) | Status-mapping + no-token-leak unit tests for the new proxy route (T-13) |

Every TC in `docs/test-cases/PGD-04.json` (TC-01..TC-17) appears in the table above. E2E: N/A
per the story's own Test mapping and REQUIREMENTS.md § Scope — backend-only, no `type: e2e` TC
exists in the manifest, so no runner-setup task is required (Runner-setup dimension: no
`e2e`/`performance`/`contract`-typed TC needs a NEW runner — `performance` and `contract` here
both run under the already-provisioned `pytest`/`pytest-asyncio` runner, same as PGD-02/03's
perf tests; no new tool to install).

### Coverage gates

- Unit/integration coverage threshold: 80% (no `harness.yaml` override found).
- No E2E suite exists for this story — nothing to gate green pre-commit beyond the above.

### No-placeholder check

`grep -nEi` for the forbidden-pattern list against this file: zero hits (verified before
finalizing this document).

## Plan validation

- Date: 2026-09-17T00:00:00Z
- Verdict: PASS
- Wiring:                PASS  (F-01's consumer `F-03` (`overview.py`) is a `modify` entry, wired via T-03; F-09/F-10's consumer `F-11` (proxy route) is a `create` entry consuming both, wired via T-12; F-11 itself has no consumer yet by design — `CommandsActivity.tsx` is explicitly out of scope, D-04 — so it is a leaf for this story, not an unwired module)
- Docs:                  PASS  (T2 fires — new HTTP route — addressed by T-09 (root `README.md` API table) and T-08 (`docs/requirements/api.md#program-commands-api` shared contract, filled per plan-authoring step 10); T1/T3/T4 do not fire — no new runnable surface, env var, or service/port)
- Runner-setup:          PASS  (no TC of type `e2e` in `docs/test-cases/PGD-04.json`; `performance`- and `contract`-typed TCs (TC-16, TC-14) run under the already-provisioned `pytest`/`pytest-asyncio` runner — no new runner to install, matching PGD-02/03 precedent)
- Cross-section:         PASS  (DAG acyclic, checked by hand: T-01/T-02 → T-03 → {T-04,T-06,T-07(also←T-04),T-08,T-09,T-10→T-11→T-12→T-13} → T-14←{T-03,T-12}, no cycle; every `file_plan` F-NN referenced by ≥1 task's `files[]`; every task `files[]` id resolves in `file_plan`; only F-04 is shared by two tasks (T-04, T-07) and they are DAG-ordered (T-07 predecessors include T-04), so no two DAG-independent tasks share a file; every test-strategy layer has a backing task)
- Config drift:          PASS  (C1/C2/C3 do not fire — no new runtime dependency, no new service/port; T-14 makes this an explicit, auditable check against the final diff rather than a silent assumption)
- Decision-promotion:    PASS  (all 4 `DECISIONS.md` entries are `blast:feature`/`rev:mechanical`; none requires `adr:` promotion)
- Rounds:                1
