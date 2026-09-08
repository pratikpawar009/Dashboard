# SHP-02 — Implementation Plan

Status: Complete

Personal usage panel backend: `GET /api/personal-usage/{user_id}` — 4 to-date summary cards, a
ranged daily token series, a ranged commands breakdown. research_verdict: GO-WITH-CONDITIONS
(78/100, 5 conditions). gate: APPROVE (2026-09-07). Backend-only story — `design: n/a`, no
`apps/web` change.

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log) — 5 entries,
D-01..D-05. D-04 (the `personal-usage-api` response envelope) is promoted to
`docs/adr/0009-personal-usage-api-response-shape.md` (`blast:system` — a sealed contract consumed
by 4 not-yet-built sibling features, ARC-01/DEV-01/PMD-01/PGD-05). Every other entry stays
feature-local (`blast:feature`, `rev:mechanical`) per the `decide` skill's promotion rule.

Summary of what's decided (full Context/Decision prose in `DECISIONS.md`):

- D-01: `user_sessions` backs the 4 cards + daily chart, `usage_events` backs commands only —
  exactly 3 bounded `SELECT`s per request (Condition C-2). The new index migration uses plain
  `op.create_index(...)`, not `postgresql_concurrently=True` — the production write-lock tradeoff
  is disclosed, not silently introduced (no deploy runbook/CI exists in this project today to
  require it, and no precedent for `autocommit_block()` exists anywhere in this codebase).
- D-02: default-range wiring is a story-local `_range_with_default` wrapper around the shared
  `validate_range()` — `app/dependencies/range.py` is never edited (Condition C-3).
- D-03: `bar_style_for_share()` is added to the shared `app/utils/format.py`, purely additive,
  alongside `dot_style_for_program()`'s "producer computes CSS" precedent.
- D-04 (ADR-0009): the full response envelope — 4 order-locked, 5-key cards (no `delta`, ever),
  range-scoped `daily_tokens`/`commands`, `count / max(counts) * 100` bar formula (not
  `count / total`, resolving AC3's prose-vs-mockup discrepancy) — locked before ARC-01/DEV-01/
  PMD-01/PGD-05 build fixtures against it (Condition C-4).
- D-05: the new indexes are mirrored into `UserSessions`/`UsageEvent`'s ORM `__table_args__`,
  matching this repo's existing index-declaration convention (`ProgramReleases`,
  `ProgramCommands`, `ProgramMembers`).

Note on ADR-0009's number: `docs/requirements/RTM.md` § Decisions (2026-09-07) records that a
prior tracker comment fabricated a nonexistent "ADR-0009" for a *different*, still-unsettled
decision (frontend chart-rendering approach). This plan's ADR-0009 is a legitimate, freshly
authored document for the (in-scope, backend) response-shape decision — see the ADR's own Scope
note for the full disambiguation. Frontend chart rendering remains open, out of this story's scope.

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan` — 11 entries (7 create,
4 modify; all backend + one root-doc edit — no `apps/web` file).

## 3. Module Hierarchy

```
app/api/personal_usage.py
  - input:  user_id: str (path), range: str (Depends(_range_with_default)),
            current_user: CurrentUser (Depends(get_current_user)), db: AsyncSession (Depends(get_db))
  - output: PersonalUsageResponse (200) | HTTPException(403, no body) | HTTPException(400, "invalid_range")
  - public: async def get_personal_usage(...) -> PersonalUsageResponse
  - private: _range_with_default(request: Request, range: str = Query("30d")) -> str  (D-02)

app/services/personal_usage.py
  - input:  db: AsyncSession, user_id: str, range_value: str
  - output: card totals (session_count, total_duration_seconds, total_tokens);
            list[DailyTokenPoint] + period_total/avg_per_day; CommandsPanel
  - public: fetch_card_totals(db, user_id) -> CardTotals
            fetch_daily_token_series(db, user_id, range_value) -> DailyTokenSeries
            fetch_commands_breakdown(db, user_id, range_value) -> CommandsPanel
  - reads:  user_sessions (cards, daily series); usage_events (commands only) — D-01

app/schemas/personal_usage.py
  - input:  n/a (pure data model)
  - output: PersonalUsageCard{glyph,value,label,iconBg,iconColor}; DailyTokenPoint{date,value};
            DailyTokenSeries{points,period_total,avg_per_day};
            CommandEntry{command,count,barStyle}; CommandsPanel{total_runs,items};
            PersonalUsageResponse{cards,daily_tokens,commands}
  - public: class PersonalUsageResponse(BaseModel)   -- ADR-0009

app/utils/format.py  (modified, additive)
  - new public: bar_style_for_share(count: int, max_count: int) -> str   -- D-03
```

No wiring gap: `app.main` is the only consumer of the new router (registered via
`app.include_router`, F-04/T-07, immediately after `overview_router`). `app/utils/format.py`'s new
function has no registration site of its own to wire (a pure library function, imported directly by
`app/services/personal_usage.py`, T-05).

Backend-only story — no navigation/routing map (no route/screen is added to `apps/web`).

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md`. One additive schema change (2 new indexes,
no new table/column); no cache; no server-side session; no client state (backend-only story).

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks` (11 tasks, T-01..T-11). Execution
order derives from `predecessors`; parallelism derives from the DAG (verified acyclic, every
`file_plan` entry covered, zero unordered same-file conflicts).

Three independent chains can start immediately in parallel: T-01 (migration) → T-02 (ORM index
mirror); T-03 (`bar_style_for_share`); T-04 (schemas) — all `predecessors: []`. They converge at
T-05 (service layer, needs T-03+T-04) → T-06 (router) → T-07 (wiring) → {T-08→T-09 (unit tests,
serialized on the shared test file), T-10 (perf test, also needs T-01), T-11 (docs)}.

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/SHP-02.md` § Risk register. Only R-01 is HIGH severity; R-02..R-07 are
MED/LOW and inherit their mitigation from the research doc (per the verification rule) — all are
in fact fully addressed by the Conditions-for-GO mapping below, not merely inherited.

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|--------------|
| R-01    | HIGH     | T-01 (index migration), T-02 (ORM mirror), T-10 (perf test proving the 2s budget + bounded SELECT count) |

### Risks accepted (carry-forward)

None — the one HIGH risk is addressed by tasks above, not accepted unaddressed.

### Conditions for GO (research_verdict == GO-WITH-CONDITIONS)

| Cond | Condition (verbatim, abridged) | Addressed by |
|------|----------------------|--------------|
| C-1  | New index migration + query-count-spy perf test under NFR-002's ≤2s budget | T-01, T-02, T-10 |
| C-2  | Table-to-panel mapping fixed before coding: `user_sessions` (cards+chart), `usage_events` (commands only) | T-05 (DECISIONS.md D-01) |
| C-3  | Default-range wiring via a story-local wrapper, no edit to `app/dependencies/range.py` | T-06 (DECISIONS.md D-02) |
| C-4  | Full 5-field card set + order-lock + max-of-range bar formula, sourced from the decoded mockup | T-04, T-05, T-06 (DECISIONS.md D-04, ADR-0009) |
| C-5  | Real file paths in the plan (`services/api/app/...`, never `backend/app/...`) | `tasks.json` `file_plan` (this plan) |

### Cross-Feature Dependency Notes

- R-07 (LOW, no task needed): `personal-usage-api` carries no `program_id` by contract — PGD-05
  reuses this endpoint verbatim for its per-member popup, so that popup necessarily shows an
  org-wide figure regardless of which program's page opened it. Already settled by contract
  (`docs/requirements/RTM.md` § Decisions, 2026-08-26) — carried forward as an informational note
  for PGD-05's own planning, not a gap this story leaves open.
- ARC-01, DEV-01, PMD-01, PGD-05 (all `story-validated`, none implemented) build their own fixtures
  against `docs/requirements/api.md#personal-usage-api` / `docs/adr/0009-...` once each is planned —
  no in-flight cross-feature task reference is needed today.
- Frontend chart-rendering for `daily_tokens.points` (`{{ tokChart }}`) is explicitly **not**
  decided by this plan or by ADR-0009 — `docs/requirements/RTM.md` § Decisions (2026-09-07) flags
  it unresolved; whichever of ARC-01/DEV-01/PMD-01 is planned first should settle it as its own ADR.

## 7. Test Strategy

| Layer | Test path | TCs covered | Notes |
|-------|-----------|--------------|-------|
| Contract (backend, pytest) | `services/api/tests/unit/test_personal_usage.py` | SHP-02-TC-01 | Full-envelope assertion (cards+daily_tokens+commands, no `delta` anywhere, max-of-range bar formula). `type: contract` runs under the already-configured `pytest` (matches PGD-01/AUTH-04 precedent) — no new runner. |
| Security (backend, pytest) | `services/api/tests/unit/test_personal_usage.py` | SHP-02-TC-02 | Bare-403 envelope + `individual_view_denied` PII-free log, same file as TC-01, separate test function (T-09). |
| Unit — disclosed coverage gap (backend, pytest) | `services/api/tests/unit/test_personal_usage.py` | none (PRD `coverage_audit.uncovered`) | Per `test-case-generation`, unit tests close a disclosed gap without becoming a numbered TC: `SHP-02-AC-5`/`SHP-02-FR-6` (default `range` + `HTTP 400` on an invalid value, T-09) and `SHP-02-FR-5` (zero-session `avg_tokens_per_session = 0.0`, T-08) are both asserted here, per the PRD § Approvals' explicit instruction that `PLAN.md` back both C-1/C-3 and FR-5 with `tasks.json` entries. |
| Performance (backend, pytest) | `services/api/tests/perf/test_personal_usage_perf.py` | SHP-02-NFR-performance | Disclosed coverage gap, closed here (not a numbered TC): mirrors `tests/perf/test_overview_perf.py`'s convention — plain `time.perf_counter()`, no k6/Locust, no new runner. Query-count spy (budget 3), duration budget 2000ms (NFR-002's literal figure), parametrized across `{7d,30d,90d}` (T-10). |

E2E: N/A — no e2e framework configured (`test_e2e` empty, `docs/config/project-commands.yaml`);
none of SHP-02-TC-01/02 is `type: e2e`, so no Runner-setup task is required. Manual: N/A per the
story's own Test mapping.

Coverage gate: 80% (no `harness.yaml` override found). E2E suite gate: N/A (no e2e suite exists).

Config drift: N/A — no new runtime dependency, service, or port is introduced by this story (2 new
`Index()` calls and one additive function are not a new dependency); `docs/config/project-
commands.yaml` `preflight:` and `docs/config/stack-smoke.md` need no edit.

### Plan validation rounds

| Round | Verdict | Failing dimensions | Action |
|-------|---------|---------------------|--------|
| 1     | PASS    | —                   | Proceed to `/arh-implement` |

## Plan validation

- Date: 2026-09-07
- Verdict: PASS
- Wiring: PASS (new backend module `personal_usage.py` router registered in `app.main` via
  F-04/T-07; `app/services/personal_usage.py` and `app/schemas/personal_usage.py` are consumed
  only by the new router, created in this same story; `bar_style_for_share` is a pure library
  addition to an existing module with no registration site of its own)
- Docs: PASS (T2 new route `GET /api/personal-usage/{user_id}` → T-11 root `README.md` API table
  row; T1/T3/T4 do not fire — no new runnable surface, no new env var, no new service/port)
- Runner-setup: PASS (`SHP-02-TC-01` `type: contract`, `SHP-02-TC-02` `type: security`, and the
  performance test all run under the already-installed `pytest` — see §7 notes and the PGD-01/
  AUTH-04 precedent; none is `type: e2e`/`contract-tool`-requiring, no new runner needed)
- Cross-section: PASS (`tasks.json` DAG is acyclic — verified programmatically; every
  `predecessors` id resolves; every `file_plan` entry is referenced by ≥1 task's `files[]`; every
  task `files[]` id exists in `file_plan`; every §7 TC type has a backing task; the one shared-file
  pair, T-08/T-09 on F-09, carries the required `predecessors` edge — zero unordered conflicts)
- Config drift: PASS (C1: no new runtime dependency — `bar_style_for_share` and the two `Index()`
  calls use already-pinned `sqlalchemy`/`alembic`; C2: no new service; C3: no new port or
  `*_PORT`/`*_HOST`/`*_URL` env var)
- Decision-promotion: PASS (only D-04 carries `blast:system`, and it is promoted —
  `adr:ADR-0009`; D-01, D-02, D-03, D-05 are all `blast:feature`/`rev:mechanical` and correctly
  left at `adr:—`, each with an explicit rationale in `DECISIONS.md` for why promotion was not
  warranted — D-01 in particular explains why an index-only migration stays un-promoted)
- Rounds: 1
