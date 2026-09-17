# Research: PGD-04 — Program command activity

**Story**: PGD-04  
**Date**: 2026-09-16  
**Researcher**: Claude Code  
**Upstream dependencies**: BED-01 (GO-WITH-CONDITIONS, security-reviewed), AUTH-03 (GO-WITH-CONDITIONS, security-review), BED-02 (GO-WITH-CONDITIONS, security-reviewed)

## Upstream summary

- **BED-01** (`db-schema`): `program_commands` table exists with `program_id, name, run_count, period_start, period_end, as_of_timestamp` columns — no schema risk.
- **AUTH-03** (`rbac-checks`): `program_visibility()` open-aggregate gate available; no persona-scoped filtering; gate under security review (security=null in state).
- **BED-02** (`api-conventions`): `validate_range()` Depends, `format_number()`, error envelope available; all routes established the pattern.

All three complete; no blocking dependencies for research.

## Exploration Log

- **Existing routes & patterns**: `/api/overview/program-detail/{program_id}` (PGD-01), `.../token-trend` (PGD-02), `.../releases` (PGD-03) all live on `overview` router in `services/api/app/api/overview.py:80`. Same open-aggregate `program_visibility()` gate; same `_range_with_default()` wrapper pattern; same pagination helpers via `_releases_offset_limit()`.
- **Story decision log assumption**: endpoint path is `GET /api/program-detail/{program_id}/commands`. README.md tables all sibling routes under `/api/overview/program-detail/` — **path divergence flagged as risk below**.
- **Response contract**: `program-commands-api` in `docs/requirements/api.md:188-195` lists only fields (`program-level command name + run_count for the selected range, total run count`), no shape detail. Personal usage schema in `services/api/app/schemas/personal_usage.py:56-79` shows `CommandsPanel {total_runs, items: [{command, count, barStyle}]}` for SHP-02's per-user version — same structure applies here per AC-3 / FR-PD-12.
- **Database model**: `ProgramCommands` in `app/models/rollup.py` has `program_id, name, run_count, period_start, period_end, as_of_timestamp` — designed for rollup storage, not transient compute. Read-only at query time per BED-01's schema ownership; no ingest producer yet (state notes "currently has no ingest producer" for program_releases, same will apply here).
- **Schemas & services**: `personal_usage.py` provides `CommandEntry` (command, count, bar_style) + `CommandsPanel` (total_runs, items). No `program_commands` aggregation service exists yet; both `/api/personal-usage` and `/api/overview/program-detail/.../commands` compute from `usage_events` + `program_commands` table.
- **Testing**: Test mapping lists `backend/app/services/program_detail.py` for command aggregation, `backend/app/routers/program_detail.py` for endpoint/range validation/RBAC — structure mirrors PGD-02/PGD-03 refactor to `program_detail_token_trend.py` / `program_releases.py` service modules, not inlined route logic.
- **SHP-02 contract independence**: AC-6 — the two (personal "Your commands", program "Commands executed") are "computed independently and neither derives from the other" — distinct aggregation logic, distinct range windows.

## Pattern map

### Existing code to extend

1. **Router assembly** (`app/api/overview.py:80`): add new endpoint handler to existing router instance; follow PGD-03 pattern (`get_program_releases:214-264`).
2. **Dependency wiring** (`app/api/overview.py:165-173`): reuse `_range_with_default()` verbatim; no new dependency.
3. **Validation & RBAC** (`app/api/overview.py:134,197,238`): call `program_visibility(current_user, program_id)` once at handler start, before any 404 lookup or range work.
4. **Error envelope** (`app/core/errors.py`): existing HTTPException handlers; 400 `invalid_range` from `validate_range()` dependency, 404 for unknown program_id, 401 for auth failure.

### Existing patterns to follow

1. **Open-aggregate gate signature**: `await program_visibility(current_user, program_id)` — mirrors PGD-01/02/03; never filters response by membership; never 403.
2. **Range validation**: `range: str = Depends(_range_with_default)` — reuse exact wrapper from token-trend route; returns one of `{7d, 30d, 90d}` or raises 400.
3. **Response schema**: `CommandsPanel` already defined in `personal_usage.py:74-78` — import and reuse; no new schema class.
4. **Logging**: structured JSON log with method, path, program_id, range, status, latency_ms (see PGD-03's `program_releases_fetched` at line 250-262).
5. **Ordering**: commands descending by run_count per AC-3 (bar proportionality requires ranking).

### New files to create

1. **`services/api/app/services/program_commands.py`**: aggregation service — mirrors `program_detail_token_trend.py` / `program_releases.py` pattern.
   - Function: `async def fetch_program_commands(db: AsyncSession, program_id: str, range: str) -> CommandsPanel`
   - Reads from `program_commands` table (BED-01 model); filters by program_id + range window; orders by run_count DESC; computes total_runs via format_number(); builds bar_style per SHP-02 formula.
2. **`services/api/app/schemas/program_commands.py`**: response envelope — contains only `CommandsPanel` (import from `personal_usage.py` or duplicate; decision below).
   - **RESOLVED (2026-09-17)**: import `CommandsPanel` + `CommandEntry` from `app/schemas/personal_usage.py`; do NOT duplicate. Verified shipped: `CommandEntry` emits wire fields `command` / `count` (raw int) / `barStyle`, and `CommandsPanel` emits `total_runs` (pre-formatted) + `items` — byte-identical to what this story's AC-1/AC-3 need. `services/api/app/schemas/program_commands.py` is therefore NOT created; the response envelope is `CommandsPanel` itself. AC-6's independence requirement is about *computation*, not schema identity — two callers of one shape do not derive from each other. Add a line to `personal_usage.py`'s module docstring recording the PGD-04 co-consumer, and a carry-forward for a shared `schemas/commands.py` if a third consumer appears.

### Shared code at risk

1. **`app/models/rollup.py::ProgramCommands`**: read-only at this layer; BED-01 owns writes via rollup rebuild. No migration or schema change needed.
2. **`app/core/rbac.py`**: `program_visibility()` called here as open-aggregate gate; any change to its semantics (unlikely) affects all 5 routes (PGD-01/02/03/04, plus `/api/overview/summary`).
3. **`app/dependencies/range.py`**: validates range param; shared across 4 endpoints (token-trend, releases, commands, plus SHP-02's personal-usage). Any NFR-002 perf regression impacts all.

### Design/API contract risks

1. **Path vs. story assumption**: Story decision log specifies `GET /api/program-detail/{program_id}/commands`; README and sibling routes use `/api/overview/program-detail/...`. **Risk-flagged below** as DECISION to settle.
2. **barStyle formula**: SHP-02-FR-3 / ADR-0009 context point 3 specifies `round(count / max(all in-range counts) * 100)%` — NOT `count / total_run_count * 100` as AC-3 prose literally reads. Mockup settles the conflict; no ambiguity for implementation.
3. **Empty result behavior**: **RESOLVED (2026-09-17)** — return `200 {total_runs: "0", items: []}` for an unknown `program_id`; no 404. The sibling split is not arbitrary and the principle decides this case: `/releases` 404s because it answers "tell me about this program's releases" and a missing `program_summary` row makes the question unanswerable; `/token-trend` returns a zero-filled series because it answers "how much activity in this window", where "none" is a true answer, not an error. Commands is the second kind — an empty panel is the honest rendering of a program with no in-range activity, which is a real state for a live program, not just an unknown id. PGD-02's security review (`docs/features/PGD-02/SECURITY-20260916-1330.md:104`) already cleared the no-404 path as not an enumeration oracle under the same open-aggregate gate, so this inherits that clearance. Consequence: the handler performs no `program_summary` existence lookup at all.

## Risk register

| # | Dimension       | Severity | Description                                              | Mitigation                                  |
|---|-----------------|----------|----------------------------------------------------------|---------------------------------------------|
| 1 | Integration     | HIGH     | Endpoint path diverges from sibling routes (story assumption vs. README table; `/program-detail` vs. `/overview/program-detail`) — breaks URL consistency and the "switch program" switcher re-load expectation | Verify with stakeholder: use `/api/overview/program-detail/{program_id}/commands` to match PGD-01/02/03 precedent and README; update story assumption in decision log |
| 2 | Domain          | MED      | Unknown program_id response code unclear — token-trend returns 200-empty, releases returns 404; neither story nor api.md settle this for commands | Adopt token-trend pattern (200 empty series) to keep behavior consistent with sibling aggregation endpoints (token-trend, token series, session series); all read-only queries, no 404 unless resource genuinely not found (program_summary row) |
| 3 | Domain          | MED      | CommandsPanel / CommandEntry schema decision — duplicate in program_commands.py or move to shared module — impacts future schema hygiene | Import from personal_usage.py (already defined, no breaking existing code); document in schema module docstring that SHP-02 + PGD-04 share the exact same shape; capture schema consolidation as a carry-forward cleanup task |
| 4 | Compatibility   | LOW      | barStyle formula: AC-3 prose says `count/total_run_count * 100`, mockup says `max-of-range`, ADR-0009 confirms max-of-range | No action needed — ADR-0009 is authority per CLAUDE.md § Design system; implement max-of-range formula; document in service code as established by SHP-02 precedent |
| 5 | Performance     | LOW      | NFR-002 ≤2s refresh on `range` parameter change — identical to PGD-02/03 budget | Same `program_visibility()` + single table read + sort pattern as PGD-02/03; no N+1 or unbounded reads; meets budget by construction |
| 6 | Domain          | HIGH     | **Wrong data source.** `program_commands` stores lifetime, unranged counts (`rollup_rebuild.py:246`, no time filter; `period_start`/`period_end` are MIN/MAX metadata). Reading it for a ranged endpoint makes `?range=` a no-op — every range returns identical numbers, violating AC-1 while naive tests still pass | Aggregate from `usage_events` (per-event `ts`), mirroring SHP-02's `_fetch_command_rows` with `program_id` swapped for `user`; index `ix_usage_events_program_id_command` already supports it. **Mandatory test**: assert `7d` and `90d` return different totals on seeded multi-window data — a test that only asserts `200`+non-empty cannot catch this |

## Score + verdict

| Dimension       | Weight | Score | Rationale |
|-----------------|--------|-------|-----------|
| Integration     | 25     | 65    | Path divergence (story vs. README/shipped routes) must be resolved before planning; decision made now, no blocker. Upstreams available; no unresolved API contract. |
| Compatibility   | 20     | 80    | No client-breaking changes; response shape mirrors SHP-02; 401/400/404 errors established by prior stories. |
| Domain          | 20     | 70    | Empty-result behavior ambiguous (200 vs. 404); barStyle formula known (ADR-0009 is authority). Schema consolidation deferred to carry-forward. |
| Performance     | 15     | 85    | Single table read + sort; NFR-002 ≤2s is guaranteed by PGD-02/03 precedent; no new perf constraints. |
| Dependency      | 20     | 90    | All upstreams complete (BED-01 schema, AUTH-03 gate, BED-02 conventions); no blocking external work. |

**Weighted total: (65×0.25) + (80×0.20) + (70×0.20) + (85×0.15) + (90×0.20) = 16.25 + 16 + 14 + 12.75 + 18 = 77**

**Total: 77/100 → GO-WITH-CONDITIONS**

### Conditions for proceeding

PLAN.md must address:

1. **Path decision**: settled 2026-09-17 — `GET /api/overview/program-detail/{program_id}/commands`,
   a fourth route on the existing `overview` router (`prefix="/api/overview"`,
   `services/api/app/api/overview.py:80`), with the browser-facing Next.js proxy at
   `/api/proxy/program-detail/{program_id}/commands` per ADR-0008. `docs/stories/PGD-04.md` AC-1
   and its decision log are corrected; the superseded 2026-08-26 entry is kept for provenance.
   No action left for PLAN.md beyond following it.
2. **Empty-program behavior**: settled — see C-1. `200` with `{total_runs: "0", items: []}`, no
   existence lookup, no 404 path.
3. **Schema ownership**: settled — see C-2. Import from `personal_usage.py`; add the co-consumer
   note to its module docstring; carry-forward a shared `schemas/commands.py` only on a third consumer.
4. **Data source** (added 2026-09-17, see R-6 + § Post-assessment correction): aggregate from
   `usage_events`, never `program_commands`. PLAN.md must carry the differential range test
   (`7d` total ≠ `90d` total on seeded data) — without it the defect is invisible to a passing suite.
5. **Frontend scope**: the story's Test-mapping asserts `frontend/.../CommandsActivity.tsx` "is
   unchanged and already consumes this shape". **Verified false** — no commands component exists
   anywhere under `apps/web/src` (checked 2026-09-17). PLAN.md must either scope the component in
   or state explicitly that PGD-04 ships backend-only and the panel stays unrendered; it cannot
   silently rely on a component that was never built.

## Synthesis

PGD-04 is architecturally straightforward — a third sibling on the `overview` router following PGD-02/03's established patterns for range validation, RBAC, error handling, and logging. The database model (`program_commands` table) and response schema (`CommandsPanel` + `CommandEntry`) are already in place. The main research risks are a path name divergence between the story's assumption and the shipped
sibling convention (settle in PLAN.md, not a blocker) and — found while resolving the clarifications
on 2026-09-17 — a wrong data source in this report's own pattern map: `program_commands` holds
lifetime counts, so a ranged endpoint must read `usage_events` (R-6, § Post-assessment correction).
That correction raises no new feasibility doubt; the replacement query is SHP-02's, already shipped
and indexed. No upstream blocking; no new NFR or security concerns beyond those cleared by AUTH-03.
Both original clarifications are resolved (C-1, C-2); proceed to planning with the conditions above.

## Clarifications

All resolved 2026-09-17 (main session, with the user). None open.

| # | Question | Resolution | Basis |
|---|---|---|---|
| C-1 | Unknown `program_id` → `200` empty or `404`? | `200 {total_runs: "0", items: []}`; no existence lookup | The sibling split is principled, not arbitrary: `/releases` 404s because a missing program makes "its releases" unanswerable; `/token-trend` zero-fills because "no activity in window" is a true answer. Commands is the latter — an empty panel is the honest render of a real, live, quiet program. PGD-02's security review already cleared this path as not an enumeration oracle under the same open-aggregate gate. |
| C-2 | Reuse `CommandsPanel` or duplicate it? | Import `CommandsPanel` + `CommandEntry` from `app/schemas/personal_usage.py`; create no `schemas/program_commands.py` | Shipped SHP-02 shape (`command`/`count` raw int/`barStyle`; `total_runs`/`items`) already matches AC-1/AC-3 exactly. AC-6's independence is about computation, not schema identity. |
| C-3 | *(raised during resolution, not by the agent)* Is `program_commands` a valid source for a **ranged** query? | **No — read `usage_events` instead.** | See R-6 below. This invalidates the report's own "New files to create" §1 premise. |
| C-4 | Endpoint path — story's `/api/program-detail/...` vs shipped siblings? | `/api/overview/program-detail/{program_id}/commands` (backend) + `/api/proxy/program-detail/{program_id}/commands` (browser-facing) | The `overview` router's own `prefix="/api/overview"` applies to every route on it; the story's path matches no registered router and would need a new one. Story AC-1 + decision log corrected 2026-09-17. |

## Post-assessment correction (2026-09-17)

The Pattern map above proposes a service that "reads from `program_commands` table; filters by
program_id + range window". **That is not implementable as written**, and the error is upstream of
both clarifications:

`_build_program_commands` (`services/api/app/services/rollup_rebuild.py:246-268`) groups
`usage_events` by `command` with **no time filter** — one lifetime row per (program, command).
`period_start`/`period_end` are `MIN(ts)`/`MAX(ts)` of the observed data: descriptive metadata
describing the rows that were counted, **not** a selectable window. Filtering `program_commands`
by a range window is therefore meaningless — `?range=7d` and `?range=90d` would return byte-identical
lifetime counts, silently violating AC-1 while every test that only asserts "200 with items" passes.

The range-capable source is `usage_events`, which carries per-event `ts`. This is exactly what
SHP-02's `_fetch_command_rows` (`app/services/personal_usage.py:172-191`) does for the per-user
cut, and the composite index `ix_usage_events_program_id_command`
(`app/models/ingestion.py:38`) already exists for precisely this program-scoped grouping — strong
evidence the schema was designed for this query. The PGD-04 query is SHP-02's with the
`WHERE "user" = :user_id` predicate swapped for `WHERE program_id = :program_id`.

This also strengthens AC-6 (program vs. personal totals computed independently): the two read the
same table through different predicates, neither derived from the other.

**Carry-forward (not this story's scope):** `program_commands` now has no reader. Either a later
story gives it a lifetime-totals consumer, or it should be dropped as dead rollup surface. Do not
delete it under PGD-04 — `rollup_rebuild` writes it and that write is out of scope here.
