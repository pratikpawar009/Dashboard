# PLAN — PGD-05: Project team table + per-member usage popup

Status: VALIDATED

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log). Five entries:
D-01 (two-SELECT aggregation, merged in Python — the story's single highest-risk choice,
research C-1/Risk #1), D-02 (new composite index `(program_id, user, ts)` on `usage_events`,
promoted to ADR-0016 — `blast:data`), D-03 (popup calls `personal-usage-api` via a same-origin
ADR-0008 proxy, no PGD-05-owned relay, per research C-2), D-04 (`member_in_program_visibility`
enforced by a new PGD-05 sibling route, not by editing SHP-02's route/schema), D-05 (the popup
UI itself is design-gated — represented as a single blocked task, not planned or invented).
Only D-02 carries `blast:data`; it is promoted to `docs/adr/0016-usage-events-program-team-index.md`.
The other four are `blast:feature` / `rev:mechanical`, staying DECISIONS.md-only.

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan`.

### Module hierarchy

```
services/api/
├── migrations/versions/008_program_team_index.py   [NEW]
│   - Index(ix_usage_events_program_id_user_ts, program_id, user, ts) (D-02/ADR-0016)
├── app/models/ingestion.py                          [MODIFIED]
│   - UsageEvent.__table_args__ declares the same index (schema-diff gate)
├── app/services/program_team.py                     [NEW]
│   - input:  db: AsyncSession, program_id: str, range_value: str
│   - output: list[ProgramTeamRow] (app.schemas.program_detail)
│   - public: async fetch_program_team(db, program_id, range_value) -> ProgramTeamResponse
│   - two SELECTs merged in Python by user_id/user (D-01); never a SQL join
├── app/schemas/program_detail.py                     [MODIFIED]
│   - adds ProgramTeamRow, ProgramTeamResponse (field order locked, FR-2)
└── app/api/overview.py                               [MODIFIED]
    - GET /program-detail/{program_id}/team            (5th sibling route)
      - calls program_visibility() once, no existence lookup, no 404
      - calls fetch_program_team(), logs program_team_fetched
    - GET /program-detail/{program_id}/team/{member_id}/usage   (6th sibling route, D-04)
      - calls member_in_program_visibility() FIRST -- 403 short-circuits before any
        personal-usage service call (AC-12 mutual exclusivity by construction)
      - on pass, calls SHP-02's fetch_card_totals/fetch_daily_token_series/
        fetch_commands_breakdown directly, returns PersonalUsageResponse verbatim

apps/web/src/
├── types/programTeam.ts                              [NEW] -- wire type mirror
├── lib/programTeamApi.ts                              [NEW] -- server-only fetcher
├── lib/teamAvatarStyle.ts                             [NEW]
│   - input:  memberName: string, role: string
│   - output: { initials: string, avBg: string }
│   - public: getTeamAvatarStyle(memberName, role) -> {initials, avBg}
│   - client-owned per DESIGN.md ("Avatar colour and initials -- not supplied by this
│     story's API"); avBg keyed by role via docs/design/tokens.md Persona colors
├── app/api/proxy/program-detail/[program_id]/team/route.ts        [NEW]
│   - input:  incoming Request (dashboard_session cookie), path param program_id
│   - output: NextResponse (200 ProgramTeamResponse JSON | 401 session_expired | 502)
├── app/api/proxy/personal-usage/[user_id]/route.ts                 [NEW]
│   - input:  incoming Request, path param user_id, program_id forwarded
│   - output: NextResponse (200 PersonalUsageResponse JSON | 403 denied, no body |
│     401 session_expired | 502)
│   - proxies to the NEW PGD-05 sibling route (T-04), not SHP-02's own route directly (D-03/D-04)
├── components/ProgramTeamPanel.tsx                    [NEW]
│   - input:  ProgramTeamResult (ok | unauthorized | error)
│   - output: rendered team table (populated / loading / empty / error states)
│   - public: <ProgramTeamPanel result={...} />
└── components/ProgramDetailView.tsx                    [MODIFIED]
    - mounts <ProgramTeamPanel> in the COMMANDS+TEAM two-up section (entry-registration
      site for ProgramTeamPanel.tsx)
```

No navigation/routing map beyond the existing `/programs/[program_id]` page (existing route,
new panel mounted within it) — no new route/screen ships for AC-1..8.

### Design-gated scope (T-16)

The per-member usage popup **component** (row trigger, modal chrome, denied/loading/error
states) has NO module entry above and NO `file_plan` entries — see § 6 and DECISIONS.md D-05.
`/arh-iterate-design PGD-05` must produce DESIGN.md § Screen 2 content before those files can be
named. The popup's *backend* (the new sibling route + its proxy) is fully planned above and is
NOT blocked — it needs no visual design.

## 3. Module Hierarchy

See § 2 above — the module hierarchy is included there per the pinned pointer format (§2 body
is the `tasks.json` pointer plus this narrative).

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md`. Summary: two read-only SELECTs merged in
Python (`program_members` snapshot + range-scoped `usage_events` aggregate); one new Alembic
migration adding a composite index on `usage_events` (promoted to ADR-0016); a new sibling route
delegating to SHP-02's existing service functions for the popup's data (no schema/table change
there); no cache, no async/messaging surface.

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks`. Execution order derives from
`predecessors`; parallelism derives from the DAG. 16 tasks total (S/M/L split: 6 S, 8 M, 2 L).
T-16 is `status: blocked` — see § 6 Design gate below; it carries no `file_plan` entries by
design and its `ac_refs` (AC-9..12) are represented only as a blocked placeholder, never
implemented speculatively.

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/PGD-05.md` § Risk register. HIGH/CRITICAL risks are addressed by a
task id below; MED/LOW risks inherit their mitigation from the research doc.

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|--------------|
| R-1 | HIGH | T-01, T-02, T-08 (new index + two-SELECT service + perf test with query-count spy) |
| R-2 | MED | T-03 (usage-derived name/role documented in service docstring, no manual enrichment) |
| R-3 | MED | T-04, T-14 (relay-vs-direct decided — D-03/D-04 — and implemented) |
| R-4 | LOW | T-05 (zero-members empty-list test, TC-07) |
| R-5 | MED | T-03, T-09 (exact response shape locked in code + contract doc) |
| R-6 | LOW | T-06 (rounding-rule test, TC-06) |
| R-7 | LOW | T-06 (ordering-assumption test) |
| R-8 | LOW | T-02 docstring note (synchronous BED-03 rebuild verified, no async coordination needed) |

No risk is carried forward as "accepted" — all eight are addressed by a task above.

### Conditions for GO (research_verdict GO-WITH-CONDITIONS)

| Cond | Condition (verbatim, abbreviated) | Addressed by |
|------|-----------------------------------|--------------|
| C-1  | New index `(program_id, user, ts)` on `usage_events`; perf test asserts 2-SELECT bound + ≤2s | T-01, T-08 |
| C-2  | Popup relay-vs-direct decision recorded in PLAN | D-03/D-04 (DECISIONS.md), implemented by T-04, T-14 |
| C-3  | Decision log entries for the five 2026-08-26 assumptions | Carried into DECISIONS.md D-01 (context) and PGD-05's own `docs/stories/PGD-05.md` § Decision log (already recorded); no new entries needed — sourced verbatim |
| C-4  | `ProgramTeamResponse`/`ProgramTeamRow` exact schema, field order locked | T-02 (schema), T-09 (contract doc) |
| C-5  | PLAN.md file plan uses real paths (`overview.py`, `services/program_team.py`, `schemas/program_detail.py`) | T-02, T-03 — verified against `file_plan` F-04/F-05/F-06 above, no invented paths |

### Design gate (REQUIREMENTS.md § Constraints — not a research condition, but load-bearing)

The popup (AC-9..12) has no mockup backing it anywhere in `docs/design/mockups/` — no trigger,
no modal chrome, no denied/loading/error states are designed (DESIGN.md § "The popup is not in
this mockup"). `/arh-iterate-design PGD-05` MUST run and produce DESIGN.md § Screen 2 content
before AC-9..12's **UI** can be planned in detail or implemented. This PLAN:

- Ships AC-1..8 (team table endpoint + UI) in full via T-01..T-03, T-05, T-06, T-09..T-13,
  T-15 — independently implementable today, no design dependency.
- Ships the popup's backend wiring (the `member_in_program_visibility`-gated sibling route and
  its Next.js proxy — D-03/D-04) via T-04, T-07, T-14 — implementable today, since neither
  requires a visual design decision (no chrome, no copy, no interaction states).
- Represents the popup's **frontend component** (row trigger, modal chrome, denied/loading/error
  rendering, NFR-008 accessibility obligation) as **T-16, `status: blocked`**, with zero
  `file_plan` entries and an explicit precondition naming `/arh-iterate-design PGD-05` as the
  unblocking event. No file paths, chrome, or copy are invented for it (CLAUDE.md § Design
  system). Once the design lands, a plan amendment expands T-16 into estimable subtasks with
  real `file_plan` entries.

### Cross-Feature Dependency Notes

`ARC-01`, `DEV-01`, `PMD-01`, `EMD-01`, `SHP-07` consume `program-team-api`
(`docs/requirements/api.md#program-team-api`, filled by T-09) — none of those stories are in
flight concurrently with PGD-05; no cross-feature file contention. `ProgramTeamPanel.tsx` (T-15)
is claimed by no other story as of this plan (verified 2026-09-17 against ARC-01/DEV-01/PMD-01/
EMD-01/PGD-06/07).

## 7. Test Strategy

| Layer       | Test path                                                                   | TCs covered            | Notes |
|-------------|------------------------------------------------------------------------------|-------------------------|-------|
| Integration | `services/api/tests/unit/test_program_team_route.py`                        | TC-01,02,03,04,05,07,08,17 | Route-level, mirrors `test_program_commands_route.py` naming/shape |
| Contract    | `services/api/tests/unit/test_program_team_service.py`                      | TC-06                   | `avg_tokens_per_session: int` rounding assertion, folded into the service test file (matches this repo's existing `type: contract` handling) |
| Integration | `services/api/tests/unit/test_program_team_service.py`                      | TC-17                   | Direct-service ordering assertion (descending by `tokens`), colocated with TC-06 |
| Integration | `services/api/tests/unit/test_program_team_member_usage_route.py`           | TC-09,10                | Popup sibling route: verbatim SHP-02 shape for self/cio |
| Contract    | `services/api/tests/unit/test_program_team_member_usage_route.py`           | TC-11                   | Asserts no PGD-05-specific field added/removed vs `PersonalUsageResponse` |
| Security    | `services/api/tests/unit/test_program_team_member_usage_route.py`           | TC-12,13,18             | 403 + `member_view_denied` log (not `individual_view_denied`); no data body on denial; gate-function spy |
| Performance | `services/api/tests/perf/test_program_team_perf.py`                         | TC-14,15                | Budget: each of `7d`/`30d`/`90d` ≤2000ms at ≥5,000 seeded `usage_events` rows / ≥20 members; query-count spy asserts exactly 2 SELECTs |
| Frontend    | `apps/web/src/app/api/proxy/program-detail/[program_id]/team/route.test.ts` | — (no TC id, proxy-only, mirrors token-trend/commands proxy precedent) | Status-mapping + no-token-leak |
| Frontend    | `apps/web/src/app/api/proxy/personal-usage/[user_id]/route.test.ts`         | — (no TC id, proxy-only) | Status-mapping incl. 403 no-body-leak, no-token-leak |
| Frontend    | `apps/web/src/components/ProgramTeamPanel.test.tsx`                         | — (no TC id, component-level, covers DESIGN.md's four permitted states) | Populated/loading/empty/error rendering, client-side M/K formatting delegation |

Every TC in `docs/test-cases/PGD-05.json` (TC-01..TC-18) that maps to AC-1..8/FR-1..2 appears in
the table above. TC-10..13,18 (AC-9,11,12/FR-3) are the popup's **backend** contract and ARE
covered above (T-04/T-07's sibling route is not design-gated). No TC targets the popup's visual
UI directly — DESIGN.md § Screen 2 records that the popup's trigger/chrome/states are undesigned;
those TCs are satisfied at the API layer today and the corresponding frontend rendering is
deferred to T-16 once `/arh-iterate-design PGD-05` completes. E2E: N/A — no `type: e2e` TC exists
in `docs/test-cases/PGD-05.json` (all 18 are `integration`/`contract`/`performance`/`security`),
so no e2e runner-setup task is required. `performance`-typed TCs run under the
already-provisioned `pytest`/`pytest-asyncio` runner (no new tool to install).

### Coverage gates

- Unit/integration coverage threshold: 80% (no `harness.yaml` override found).
- No E2E suite exists for this story — nothing to gate green pre-commit beyond the above.

### No-placeholder check

`grep -nEi` for the forbidden-pattern list against this file: zero hits (verified before
finalizing this document; T-16's "blocked" status names a concrete, checkable precondition —
`/arh-iterate-design PGD-05` completing — rather than deferring the decision indefinitely).

## Plan validation

- Date: 2026-09-17T16:45:00Z
- Verdict: PASS
- Wiring:                PASS  (F-04/F-05's consumer `F-06` is a `modify` entry (T-03); F-06/F-07's own consumer for the popup path is `F-18` (proxy, T-14) which is a `create` entry consuming both; F-14/F-15's consumer `F-16` is a `create` entry (T-13); F-16/F-15's caller `F-20` (`ProgramTeamPanel.tsx`) is a `create` entry consuming both (T-15); F-20's mount site `F-23` (`ProgramDetailView.tsx`) is listed as a `modify` entry (T-15) — the entry-registration site for the new panel; F-21/F-22 (avatar map + token) are consumed by F-20, same task. T-16 (the design-gated popup UI) intentionally has NO `file_plan` entries and is excluded from this check by design — it is `status: blocked`, not a shipped module needing a wiring site.)
- Docs:                  PASS  (T2 fires — two new HTTP routes, `/team` and `/team/{member_id}/usage` — addressed by T-10 (root `README.md` API table) and T-09 (`docs/requirements/api.md#program-team-api` shared contract, filled per plan-authoring step 10, already inline in this PLAN's companion edit); T1/T3/T4 do not fire — no new runnable surface, env var, or service/port)
- Runner-setup:          PASS  (no TC of type `e2e` in `docs/test-cases/PGD-05.json`; `performance`-typed TCs (TC-14, TC-15) and `contract`-typed TCs (TC-06, TC-11, TC-16) run under the already-provisioned `pytest`/`pytest-asyncio` runner — no new runner to install, matching PGD-02/03/04 precedent)
- Cross-section:         PASS  (DAG acyclic, checked by hand: T-01→T-02→{T-03,T-06}→{T-04→T-07,T-05,T-08,T-09,T-10,T-11→T-12→T-13→T-14←T-07}→{T-15←T-13}→T-16←{T-14,T-15}, no cycle; every `file_plan` F-NN referenced by ≥1 task's `files[]` except T-16 which is intentionally `file_plan`-empty per the design gate — no orphaned F-NN exists since T-16 declares none; every task `files[]` id resolves in `file_plan`; no two DAG-independent tasks share a file — F-06/F-07 are both touched only by T-03/T-04 which are DAG-ordered (T-04 predecessors include T-03); every test-strategy layer has a backing task)
- Config drift:          PASS  (C1 does not fire — no new runtime dependency; C2 does not fire — no new service/port; C3 fires implicitly only in the sense of a new index, which is a schema change tracked via T-01's migration, not a `stack-smoke.md`/`preflight:` concern — no port, service, or dependency changes, so neither config file needs an edit)
- Decision-promotion:    PASS  (D-02 is `blast:data` and carries `adr:ADR-0016` — promoted via `docs/adr/0016-usage-events-program-team-index.md`, index updated; D-01, D-03, D-04, D-05 are all `blast:feature`/`rev:mechanical` and correctly left at `adr:—`)
- Rounds:                1
