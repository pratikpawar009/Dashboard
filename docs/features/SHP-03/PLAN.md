# PLAN: SHP-03 — Personal session-wise usage list (paginated)

Status: VALIDATED

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log). Seven entries
(D-01..D-07), all `blast:feature`/`rev:mechanical` — none promoted to a full ADR.

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan`.

### Module hierarchy

```
services/api/app/
├── utils/format.py (modify)
│   - input:  int (seconds / raw tokens)
│   - output: pre-formatted display string
│   - public: format_session_duration(duration_seconds) -> "2h 07m"; format_session_tokens(tokens) -> "1.2M"|"840K"
│   - existing format_duration()/format_number() are untouched (D-01/D-02) — new functions added beside them
├── schemas/personal_sessions.py (new)
│   - input:  n/a (pure response schema)
│   - output: PersonalSessionEntry {title, meta, duration, tokens}; PersonalSessionsResponse {items, page, page_size, total}
│   - public: PersonalSessionsResponse (response_model), extra="forbid" on PersonalSessionEntry (D-03)
├── services/personal_usage.py (modify)
│   - input:  AsyncSession, user_id, page, page_size
│   - output: PersonalSessionsResponse
│   - public: fetch_sessions_paginated(db, user_id, page, page_size) -> PersonalSessionsResponse
│   - added beside the existing fetch_card_totals/fetch_daily_token_series/fetch_commands_breakdown — same module, same table (user_sessions)
└── api/personal_usage.py (modify)
    - input:  user_id (path), page/page_size (query), CurrentUser, AsyncSession
    - output: PersonalSessionsResponse | HTTPException(403)
    - public: GET /{user_id}/sessions -> individual_usage_visibility(current_user, user_id)
              [bare await, first statement, D-04, reused unchanged], then fetch_sessions_paginated()
    - router already included in app/main.py — no new wiring needed (SHP-02's router is reused, not a new one)

docs/requirements/api.md (modify)   — personal-sessions-api contract filled with concrete FR-1 shape (D-05)
README.md (modify)                  — new route added to the API table (T2 docs trigger)

apps/web/src/
├── types/personalSessions.ts (new)              — PersonalSessionEntryData / PersonalSessionsData / PersonalSessionsResult
├── lib/
│   ├── personalSessionsApi.ts (new)             — fetchPersonalSessions(userId, page, pageSize), server-only, direct-to-FastAPI
│   └── personalSessionsApi.client.ts (new)      — fetchPersonalSessions(...), client-only, targets /api/proxy/personal-sessions/*
├── app/api/proxy/personal-sessions/[user_id]/route.ts (new)
│   - input:  Request, { params: { user_id } }, forwards ?page/?page_size
│   - output: NextResponse (PersonalSessionsData JSON | {error} + status)
│   - public: GET — full server-to-server proxy (ADR-0008); entry-registration site for
│             personalSessionsApi.client.ts's fetch target
└── components/
    ├── SessionsTable.tsx (new)              — self-fetching client component
    │   - input:  userId: string
    │   - output: rendered table (loading skeleton x20 / populated rows / empty / 403-error)
    └── SessionsTable.module.css (new)       — card shell, grid row anatomy, pagination footer styling
```

No dashboard page imports `<SessionsTable>` in this story (D-06) — ARC-01/DEV-01/PMD-01 own mounting
it, per `REQUIREMENTS.md` § Scope Out ("dashboard composition beyond this one table"), following the
SHP-04 `ArtifactsPanel` precedent exactly.

### Navigation / routing map

N/A — `SessionsTable` is an embedded panel with no route of its own (`REQUIREMENTS.md` § Screen
inventory: `Route: —`). The only routing surface this story adds is the `/api/proxy/personal-sessions/
[user_id]` Route Handler (data proxy, not a page), listed in the module hierarchy above.

## 3. Module Hierarchy

See § 2 above (module hierarchy is inlined there per `plan-authoring`'s file-plan/module-hierarchy
pairing).

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md`.

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks`. Execution order derives from
`predecessors`; parallelism derives from the DAG. 16 tasks: S×11 (T-01, T-02, T-03, T-05, T-07,
T-08, T-09, T-10, T-11, T-13, T-14), M×4 (T-04, T-06, T-12, T-16), L×1 (T-15).

Frontend-scope decision (D-06): SHP-03 ships the `SessionsTable` component + its fetch libs + proxy
route, standalone and tested in isolation (T-10..T-16) — the same posture SHP-04 took for
`ArtifactsPanel`, the closest precedent (a shared panel embedded in the same three not-yet-built
dashboards). Backend-only would leave DESIGN.md's fully-specified component unbuilt with no other
story currently scheduled to build it; building three dashboard pages would be scope creep into
ARC-01/DEV-01/PMD-01's own stories. Shipping the component now, unwired, lets those three stories
each do a pure composition/import when they land.

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/SHP-03.md` § Risk register. All 5 risks are MED/LOW — none HIGH/CRITICAL,
so none require a mandatory addressed-by row under the verification rule, but every risk is
nonetheless addressed by a task below (no risk is silently dropped). Two additional risks (R-06,
R-07) surfaced by DESIGN.md's own Divergences/Accessibility sections are folded in here since they
carry the same "must not be silently dropped" weight as the research risks.

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|---------------|
| R-01 (name/description → single `name` column; response shape) | MED | T-01, T-02, T-03 — settled by `SHP-03-FR-1`/DESIGN.md's mockup-anatomy verification, not inferred |
| R-02 (LIMIT/OFFSET without ORDER BY yields arbitrary order) | MED | T-04, T-06, T-07 — explicit `ORDER BY started_at DESC, id ASC`; T-06 includes a regression test that seeds out-of-insertion-order rows and fails if the ORDER BY were dropped |
| R-03 (denial-only logging on `individual_usage_visibility` may confuse a reader expecting symmetric logging) | LOW | T-05 — route docstring documents this is intentional (AUTH-03-FR-2 precedent), matching SHP-02's own comment |
| R-04 (pagination default/clamp behavior — page_size=20 default vs 100 ceiling) | LOW | T-05, T-06, T-09 — documented in route docstring, tested (page_size=150 clamps to 100, not 400), and documented in the README/api.md docs tasks |
| R-05 (empty-sessions-list must be 200, not 404/error) | LOW | T-06 — explicit test: zero-session user gets `200 {items: [], total: 0}` |
| R-06 (`#4a5261` duration-cell color absent from `docs/design/tokens.md`) | LOW | accepted — see below |
| R-07 (no empty/403 state drawn in the mockup — D-4/D-5) | LOW | T-15, T-16 — component builds an original (non-mockup-sourced) empty/error state per DESIGN.md's own instruction that these need implementation-authored treatment |

### Risks accepted (carry-forward)

| Risk id | Severity | Rationale |
|---------|----------|-----------|
| R-06 (duration-cell color `#4a5261` has no token entry) | LOW | accepted (DECISIONS.md D-07) — mapped to the nearest existing token (`text-700`/`#5b6472`) at implementation time rather than adding a new token; DESIGN.md itself defers this ("not decided here"), and adding a token is a design-system-wide decision outside this story's authority. |

### Cross-Feature Dependency Notes

`SessionsTable` (F-14) is built and tested standalone in this story; ARC-01, DEV-01, and PMD-01
each depend on it via the `personal-sessions-api` contract (`docs/requirements/api.md#personal-
sessions-api`) and the component export, but none of those stories' tasks are tracked here — they
own their own composition tasks against this story's shipped artifact.

Story `docs/stories/SHP-03.md`'s own AC-3 text ("`HTTP 400` on `page_size > 100`") is stale against
the shipped clamp-not-reject convention (REQUIREMENTS.md's one open `[NEEDS CLARIFICATION]`, PO-
approved with the clamp implementation and the correction outstanding). This PLAN implements FR-3's
clamp behavior; the story text itself is a carry-forward correction, not a blocking item, and is not
edited by this PLAN or its tasks — flagged again here so it isn't lost between REQUIREMENTS.md and
implementation.

## 7. Test Strategy

| Layer | Test path | TCs covered | Notes |
|---|---|---|---|
| Unit | `services/api/tests/unit/test_format_session.py` | SHP-03-TC-01, SHP-03-TC-02 | pure formatter boundary tests: `format_session_duration` (0m, exact hours, zero-padded minutes) and `format_session_tokens` (sub-1K/1K/1M boundaries) |
| Unit/Contract | `services/api/tests/unit/test_personal_sessions_route.py` | SHP-03-TC-03, SHP-03-TC-04, SHP-03-TC-05, SHP-03-TC-07 | pytest + httpx `AsyncClient` against the in-process ASGI app; response-shape lock (4 fields, extra=forbid), `meta` composition format, `page`/`page_size`/`total` raw-int envelope |
| Security | `services/api/tests/unit/test_personal_sessions_route.py` | SHP-03-TC-08, SHP-03-TC-09 | same file, security-tagged: self-access allow, cross-user non-cio 403 (no data body), cross-user cio allow, log-capture assertion for `individual_view_denied` on denial only |
| Integration | `services/api/tests/unit/test_personal_sessions_route.py` | SHP-03-TC-06, SHP-03-TC-10, SHP-03-TC-11 | same file: `page_size=150` clamps to 100 (not 400 — carries the flip-instructions note per REQUIREMENTS.md's open clarification); zero-session user returns `200 {items:[], total:0}`; ORDER BY regression test (seeded out-of-order rows, asserts strict `started_at DESC, id ASC`, fails if ORDER BY dropped) |
| Integration | `apps/web/src/components/SessionsTable.test.tsx` | SHP-03-TC-12, SHP-03-TC-13 | vitest + Testing Library, mocked fetch boundary (`personalSessionsApi.client.ts`); table semantics (`<table>`, header association), `aria-current` on active page, accessible prev/next names, empty state, 403 state |
| Integration | `apps/web/src/app/api/proxy/personal-sessions/[user_id]/route.test.ts` | — (proxy plumbing, not a numbered TC) | vitest; ok/401/403/error status-mapping, mirrors `artifacts/[program_id]/route.test.ts` |
| Performance | `services/api/tests/perf/test_personal_sessions_perf.py` | SHP-03-TC-14 | pytest; query-count spy asserts exactly 2 SELECTs/call (items + count), p95 < 2000ms per REQUIREMENTS.md NFR |
| E2E | N/A | — | Deferred to ARC-01/DEV-01/PMD-01 dashboard-composition E2E suites, same posture SHP-04 established. No runner-setup task needed: SHP-03 declares zero TCs of `type: e2e | contract`; the one `type: performance` TC (SHP-03-TC-14) runs under the already-configured pytest runner (no new runner install required). Playwright is already installed/configured per `docs/config/project-commands.yaml`'s existing `preflight:` `playwright --version` smoke-check (PGD-02 T-16), not newly introduced by this story. |

### Coverage gates

- Unit/contract coverage threshold: 80% (no `harness.yaml` override found).
- E2E suite gating: N/A this story — no e2e TCs declared; ARC-01/DEV-01/PMD-01 own that gate for the composed pages.

### No-placeholder check

`grep -nEi "TBD|to be determined|TODO|FIXME|as appropriate|as needed|add error handling|similar to|details to follow|lorem ipsum|placeholder text" docs/features/SHP-03/PLAN.md` — zero hits.

## Plan validation

- Date: 2026-09-18T12:00:00Z
- Verdict: PASS
- Wiring: PASS (no new top-level router/entry-point — `GET /{user_id}/sessions` is added to the already-registered `personal_usage.py` router (F-04), which `app/main.py` already includes; frontend proxy route `F-13` is itself the entry-registration site for `personalSessionsApi.client.ts`'s fetch target, listed as `create`, consistent with SHP-04's identical shape)
- Docs: PASS (T2 fires — new HTTP route `GET /api/personal-usage/{user_id}/sessions` — addressed by T-09 (README.md API table row) and T-08 (docs/requirements/api.md contract fill). T1/T3/T4 do not fire: no new runnable surface, no new env var, no new service/port.)
- Runner-setup: PASS (zero TCs of `type: e2e | contract`; the one `type: performance` TC runs under the already-configured pytest runner, no new runner install required)
- Cross-section: PASS (DAG acyclic — verified by topological walk of `predecessors`, no cycle/self-reference/dangling edge; every test-strategy layer type has a backing task — unit→T-02, unit/contract→T-06, security→T-06, integration(BE)→T-06, integration(FE)→T-16/T-13, performance→T-07; every `F-NN` in `file_plan` appears in ≥1 task's `files[]`; every task `files[]` id resolves in `file_plan`; parallel-safety checked — T-01/T-03 are DAG-independent and file-disjoint (F-01 vs F-02), T-10/T-11/T-12 share no files with T-01..T-09, no two unordered tasks write the same file)
- Config drift: PASS (no new runtime dep, no new service/port introduced — `format_session_duration`/`format_session_tokens` are new functions in an existing module, not a new package; no `preflight:`/`stack-smoke.md` change needed)
- Decision-promotion: PASS (all 7 DECISIONS.md entries carry `blast:feature`/`rev:mechanical` — none require ADR promotion per the `decide` skill's rule; none left at `adr:—` that should have been promoted)
- Rounds: 1
