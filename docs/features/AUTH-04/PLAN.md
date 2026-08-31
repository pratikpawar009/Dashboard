# AUTH-04 — Implementation Plan

`GET /api/programs` — persona-scoped program list for "Switch program" selectors.
Research verdict: GO-WITH-CONDITIONS, 84/100, CERTIFIED 2026-08-31. Product Gate: APPROVE
2026-08-31.

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log). Two entries
this phase: D-01 (`dotStyle`'s colour source — a deterministic server-side palette function, not
a `program_summary` column) and D-02 (router module path corrected to
`services/api/app/api/programs.py`, superseding the story's stale
`backend/app/routers/programs.py`). Both `blast:feature`, `rev:mechanical` — no ADR promotion.

The response-shape decision itself (C-0) was already settled pre-plan as **ADR-0005**
(`docs/adr/0005-programs-api-switcher-shape.md`, Accepted) — not re-decided here.

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan`. 8 files: 4 created
(`app/schemas/programs.py`, `app/api/programs.py`, `tests/unit/test_programs.py`,
`tests/perf/test_programs_perf.py`), 4 modified (`app/core/persona_resolver.py`,
`app/utils/format.py`, `app/main.py`, root `README.md`).

## 3. Module Hierarchy

```
app/
├── schemas/programs.py                              [F-03, new]
│   - input:  none (data-only Pydantic models)
│   - output: ProgramEntry, ProgramsListResponse
│   - public: ProgramEntry{program_id: str, label: str, href: str, dotStyle: str}
│             ProgramsListResponse{programs: list[ProgramEntry]}
│             (field literally named `dotStyle`, not `dot_style` — matches the
│             mockup binding + ADR-0005's exact key set, TC-06)
│
├── api/programs.py                                  [F-04, new]
│   - input:  CurrentUser (Depends(get_current_user), AUTH-01)
│             PersonaResolver (Depends(get_persona_resolver), F-01)
│             AsyncSession (Depends(get_db), app/core/db.py)
│   - output: 200 ProgramsListResponse | 403 "Access denied" (fail-closed, FR-3)
│   - public: router = APIRouter(prefix="/api/programs", tags=["programs"]) (D-02)
│   - contract: docs/requirements/api.md#programs-api (DATA-DESIGN.md §9)
│
├── core/persona_resolver.py                          [F-01, +1 function]
│   - input:  Request
│   - output: PersonaResolver (from request.app.state.persona_resolver)
│   - public: get_persona_resolver(request) -> PersonaResolver
│             (mirrors get_settings/get_jwks_cache's app.state read pattern —
│             rbac.py's own _resolver() is private and not reused here)
│
└── utils/format.py                                   [F-02, +1 function]
    - input:  program_id: str
    - output: str — pre-formatted, bindable CSS (e.g. "background-color: #4F46E5;")
    - public: dot_style_for_program(program_id) -> str   (D-01)
```

No navigation/routing map — backend-only feature, no UI surface, no new trigger/event map
(§10 Async & messaging in `DATA-DESIGN.md` is N/A).

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md`. Summary: read-only against the existing
`program_summary` table (no migration); scoping enforced server-side from
`current_user.programs`, never a client filter; `programs_list_returned` logs a 4-field PII-clean
allowlist; no new caching (reuses AUTH-02's existing persona-resolution cache); no pagination
(~9-program org size, validated to hold at 2x scale per condition C-4).

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks`. Execution order derives from
`predecessors`; parallelism derives from the DAG. 13 tasks: T-01..T-03 (dependency seam +
palette function + schemas, no shared files, parallel-eligible) → T-04 (route) → T-05 (wiring) →
{T-06..T-11 test chain on `test_programs.py`, sequential; T-12 perf test; T-13 docs} — the last
three are parallel-eligible with each other and with the test chain (disjoint files).

## 6. Carry-Forward Risks and Conditions

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|--------------|
| R-05    | HIGH     | T-03, T-04, T-08 — ADR-0005's response shape (`{program_id, label, href, dotStyle}`) implemented in the schema + route, verified by TC-06/07/08's key-set-equality contract tests. Originally "response field set contradicts the switcher mockups" (research Risk #5); closed pre-plan by ADR-0005, implemented here. |

### Risks accepted (carry-forward)

None. R-05 is the only HIGH/CRITICAL risk in the research register and it is addressed above,
not accepted. MEDIUM/LOW risks (research #1–4, #6, #7) inherit their mitigation from
`docs/research/AUTH-04.md` § Risk Register and need no re-statement — each maps to a
`### Conditions for GO` row below or (research #7, pagination deferral) is an already-accepted
PRD Scope decision, not a new risk this plan carries.

### Conditions for GO (research_verdict GO-WITH-CONDITIONS)

C-0 (response shape) is already DONE via ADR-0005 pre-plan — no task. The remaining five:

| Cond | Condition (verbatim) | Addressed by |
|------|----------------------|--------------|
| C-1  | `programs_list_returned` payload is exactly `{user_id, persona, returned_count, timestamp}` — unit test asserts key-set equality (AUTH-02 TC-15 pattern) | T-04, T-09 |
| C-2  | `program_visibility` is a veto gate, called at most once as a session-validity check, never per-program; scoping is entirely the WHERE clause | T-04, T-08 |
| C-3  | `PersonaNotFoundError`/`PersonaResolutionError` fail closed: WARN log + `HTTPException(403, "Access denied")`, never a 500 | T-04, T-10 |
| C-4  | Performance baseline: ~100 seeded programs, non-cio scoped to 50, p95 < 300ms end-to-end, baseline captured | T-12 |
| C-5  | A `program_id` in `session.programs` absent from `program_summary` is filtered, never raised; WARN when `returned_count < len(current_user.programs)` | T-04, T-11 |

### Cross-Feature Dependency Notes

PGD-01 and EMD-01 consume this story's `programs-api` contract for their "Switch program"
selectors; neither is implemented yet, so this story has no inbound blocking dependency — it is
the producer. No other in-flight feature shares a task or file with this plan.

## 7. Test Strategy

| Layer | Test path | TCs covered | Notes |
|---|---|---|---|
| Unit | `services/api/tests/unit/test_programs.py` | TC-01, TC-02, TC-05, TC-09, TC-11, TC-15, TC-16 | `migrated_db`/`test_session` live-DB fixtures (`tests/conftest.py`, postgres-patterns); AC-1/AC-2/AC-4/AC-6, FR-2, FR-4 |
| Security | `services/api/tests/unit/test_programs.py` | TC-03, TC-04, TC-10, TC-12, TC-13, TC-14, TC-18 | same file; 401 fail-fast + call-recording spies (AC-3), FR-1 PII-allowlist key-set equality, FR-3 fail-closed persona-error handling, NFR-security client-filter-ignored |
| Contract | `services/api/tests/unit/test_programs.py` | TC-06, TC-07, TC-08 | ADR-0005 exact key-set + `href`/`dotStyle` assertions — plain pytest, no separate contract-test framework; precedent: AUTH-03's TC-25 tripwire in `test_rbac.py` |
| Performance | `services/api/tests/perf/test_programs_perf.py` | TC-17 | reuses the existing `tests/perf/` runner (plain `time.perf_counter()`, precedent `test_rbac_perf.py`/`test_persona_resolver_perf.py`) — no new runner-setup task needed; 100 seeded / 50 scoped, p95 < 300ms |
| E2E | NA | — | no UI surface in this story (story Test mapping); PGD-01/EMD-01 cover switcher rendering when they implement |

### Coverage gates

- Unit coverage threshold: 80% (no `harness.yaml` override found — framework default).
- No e2e suite exists or is required for this story; nothing to gate green pre-commit beyond
  the unit/security/contract/performance layers above.
- Performance test (T-12) runs as part of the standard `pytest` invocation
  (`docs/config/project-commands.yaml` `test`/`test_unit`) — this repo's existing `tests/perf/`
  convention is not gated behind a separate `perf` CI label (no CI configured, per `CLAUDE.md`
  Integrations: `CI: none`).

### No-placeholder check

Grepped for `TBD|to be determined|TODO|FIXME|as appropriate|as needed|add error handling|similar to|details to follow|lorem ipsum|placeholder text` — zero hits.

## Plan validation

- Date: 2026-08-31
- Verdict: PASS
- Wiring:                PASS  (new module `app/api/programs.py` [F-04] has its entry-registration site `app/main.py` [F-05, modify] listed; `app/core/persona_resolver.py`/`app/utils/format.py` additions are functions on existing modules, not new modules, so no separate registration is required; `app/schemas/programs.py` is a leaf consumed by import from F-04)
- Docs:                  PASS  (T2 new-HTTP-route trigger fires for `GET /api/programs`; T-13 updates root `README.md`'s API table, the established primary API-doc location per AUTH-01 precedent, superseding the PRD's stated `services/api/README.md` target. `services/api/README.md` does exist, but carries no endpoint table — it is the behavioural/runbook doc, and its § RBAC checks already contains AUTH-03's "`program_visibility` is a veto gate, not a roster source" section, i.e. condition C-2's content is documented there upstream. No edit to it is needed. T1/T3/T4 do not fire: no new runnable surface, no new env var, no new service/port)
- Runner-setup:          PASS  (performance TC-17 and contract TC-06/07/08 both reuse pre-existing runners — `tests/perf/` plain-`perf_counter` harness already used by `test_rbac_perf.py`/`test_persona_resolver_perf.py`, and "contract" tests are plain pytest assertions, precedented by AUTH-03's TC-25 in `test_rbac.py` — no new runner/tool to install or configure; T-12/T-08 add test files only, not runner setup)
- Cross-section:         PASS  (DAG acyclic, no self-references, every `predecessors` id resolves — T-01..T-03 have no predecessors; T-04→T-05→{T-06..T-11 chain, T-12, T-13} all resolve. Every test-strategy TC type (unit/security/contract/performance) is matched to ≥1 task. Every `file_plan` F-NN id is referenced by ≥1 task's `files[]`, and every task `files[]` id resolves in `file_plan`. Parallel-safety: T-06..T-11 share `F-06` but are serialized via a strict predecessor chain; T-12 (F-07) and T-13 (F-08) touch disjoint files from that chain and from each other, so their DAG-independence is safe)
- Config drift:          PASS  (no new runtime dependency, no new service, no new port — FastAPI/SQLAlchemy/Pydantic/pytest are all already installed; `docs/config/project-commands.yaml` and `docs/config/stack-smoke.md` need no edit)
- Decision-promotion:    PASS  (D-01 and D-02 are both `blast:feature`/`rev:mechanical` — neither meets the `blast:{system,data}` or `rev:effectively-irreversible` promotion trigger, so `adr:—` is correct for both; ADR-0005, the one decision that did meet the bar (response shape reaches PGD-01/EMD-01, `blast:system`), was already promoted pre-plan)
- Rounds:                1
