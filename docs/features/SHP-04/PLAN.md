# PLAN: SHP-04 — Artifacts generated panel

Status: VALIDATED

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log). Five entries
(D-01..D-05), all `blast:feature`/`rev:mechanical` — none promoted to a full ADR.

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan`.

### Module hierarchy

```
services/api/app/
├── schemas/artifacts.py (new)
│   - input:  n/a (pure response schema)
│   - output: ArtifactItem {tag, name, count, bg, color}; ArtifactsResponse {items: list[ArtifactItem]}
│   - public: ArtifactsResponse (response_model), extra="forbid" on ArtifactItem
├── services/artifacts.py (new)
│   - input:  AsyncSession, program_id
│   - output: ArtifactsResponse
│   - public: fetch_program_artifacts(db, program_id) -> ArtifactsResponse
│   - private: _ARTIFACT_PRESENTATION (fixed 5-tuple constant, D-03)
└── api/artifacts.py (new)
    - input:  program_id (path), CurrentUser, AsyncSession
    - output: ArtifactsResponse | HTTPException(403)
    - public: GET /api/artifacts/{program_id} -> governance_visibility(current_user, program_id)
              [bare await, first statement, D-02], then fetch_program_artifacts()

app/main.py (modify)
└── app.include_router(artifacts_router) — entry-registration site for the new router (D-04 wiring)

apps/web/src/
├── types/artifacts.ts (new)         — ArtifactItemData / ArtifactsData / ArtifactsResult
├── lib/
│   ├── artifactsApi.ts (new)        — fetchProgramArtifacts(), server-only, direct-to-FastAPI
│   └── artifactsApi.client.ts (new) — fetchProgramArtifacts(), client-only, targets /api/proxy/artifacts/*
├── app/api/proxy/artifacts/[program_id]/route.ts (new)
│   - input:  Request, { params: { program_id } }
│   - output: NextResponse (ArtifactsData JSON | {error} + status)
│   - public: GET — full server-to-server proxy (ADR-0008); entry-registration site for
│             artifactsApi.client.ts's fetch target
└── components/
    ├── ArtifactsPanel.tsx (new)       — self-fetching client component
    │   - input:  programId: string
    │   - output: rendered card (loading skeleton / populated rows incl. zero-count / error)
    └── ArtifactsPanel.module.css (new) — card shell, row anatomy, tag-chip styling
```

No dashboard page imports `<ArtifactsPanel>` in this story (D-04) — ARC-01/DEV-01/PMD-01 own
mounting it, per `REQUIREMENTS.md` § Scope Out ("dashboard composition beyond this one panel").

### Navigation / routing map

N/A — `ArtifactsPanel` is an embedded panel with no route of its own (`REQUIREMENTS.md` § Screen
inventory: `Route: —`). The only routing surface this story adds is the `/api/proxy/artifacts/
[program_id]` Route Handler (data proxy, not a page), listed in the module hierarchy above.

## 3. Module Hierarchy

See § 2 above (module hierarchy is inlined there per `plan-authoring`'s file-plan/module-hierarchy
pairing).

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md`.

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks`. Execution order derives from
`predecessors`; parallelism derives from the DAG. 15 tasks: S×9 (T-01, T-04, T-06, T-07, T-08,
T-09, T-11, T-14, T-15), M×4 (T-02, T-03, T-10, T-13), L×2 (T-05, T-12).

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/SHP-04.md` § Risk register. All 5 risks are MED/LOW — none HIGH/CRITICAL,
so none require a mandatory addressed-by row under the verification rule, but every risk is
nonetheless addressed by a task below (no risk is silently dropped).

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|--------------|
| R-01 (response JSON shape ambiguity) | MED | T-01, T-02, T-07 — shape is now frozen by `SHP-04-FR-1`/`DECISIONS.md` D-05, not inferred |
| R-02 (governance-denial logging event undefined) | MED | T-03, T-05 — resolved by `DECISIONS.md` D-01; TC-04 asserts no `governance_view_denied` is ever emitted |
| R-03 (RBAC gate first live consumer) | MED | T-03, T-05 — explicit authorized/denied/resolver-failure route-level coverage (TC-02, TC-03, TC-05), not assumed from the existing unit suite |
| R-04 (no dedicated E2E; deferred to composition stories) | LOW | accepted — E2E execution is deferred to ARC-01/DEV-01/PMD-01 per `docs/stories/SHP-04.md` § Test mapping and `docs/config/project-commands.yaml`'s `test_e2e` deferred-execution policy; T-06/T-13 cover this story's own layer in full |
| R-05 (mockup identical across 3 personas — no divergence risk) | LOW | T-12, T-13 — confirmed no persona branching in the component or its test |
| R-06 (tag-chip contrast below WCAG AA) | LOW | accepted (see below) |

### Risks accepted (carry-forward)

| Risk id | Severity | Rationale |
|---------|----------|-----------|
| R-06 (tag-chip contrast, 4 of 5 pairs 2.78–4.20:1, below the 4.5:1/3:1 AA bars) | LOW | accepted — `DESIGN.md` § Design QA: systemic to the design system's tint-on-tint chip recipe, already shipped as persona tag pills elsewhere (`tokens.md` § Persona colors, SHP-01); any fix is a token-level decision with six-dashboard blast radius, not this story's to make. Mitigated in place: `a.name` sits in full-contrast ink immediately beside every chip (17.46:1), so color is never the sole indicator of artifact type — the accessibility NFR is satisfied independent of the chip's own contrast. |

### Cross-Feature Dependency Notes

`ArtifactsPanel` (F-12) is built and tested standalone in this story; ARC-01, DEV-01, and PMD-01
each depend on it via the `artifacts-api` contract (`docs/requirements/api.md#artifacts-api`) and
the component export, but none of those stories' tasks are tracked here — they own their own
composition tasks against this story's shipped artifact.

## 7. Test Strategy

| Layer | Test path | TCs covered | Notes |
|---|---|---|---|
| Contract/Unit | `services/api/tests/unit/test_artifacts_route.py` | TC-01, TC-06, TC-07, TC-08 | pytest + httpx `AsyncClient` against the in-process ASGI app; fixed-order/raw-int shape, unknown-program zero-fill, empty-program zero-fill, real-zero-row vs missing-row parity |
| Security | `services/api/tests/unit/test_artifacts_route.py` | TC-02, TC-03, TC-04, TC-05 | same file, security-tagged cases: 3-persona allow, cio+engineering-manager deny (with query-spy proving zero `program_artifacts` SELECTs), log-capture assertion for `rbac_check_governance_visibility` (self-witnessing precondition per `alembic-fileconfig-disables-app-loggers` guard), resolver-failure fail-closed path |
| Integration | `apps/web/src/components/ArtifactsPanel.test.tsx` | TC-09, TC-10 | vitest + Testing Library, mocked fetch boundary (`artifactsApi.client.ts`); TC-10 mounts the standalone component 3× with an identical fixture (no ARC-01/DEV-01/PMD-01 page exists yet to render against — see `tasks.json` T-13 notes) |
| Integration | `apps/web/src/app/api/proxy/artifacts/[program_id]/route.test.ts` | — (proxy plumbing, not a numbered TC) | vitest; ok/401/error status-mapping, mirrors `team/route.test.ts` |
| Performance | `services/api/tests/unit/test_artifacts_performance.py` | TC-11 | pytest; query-counter spy asserts exactly 1 SELECT/call, p95 < 3000ms over a 10-call sample |
| E2E | N/A | — | Deferred to ARC-01/DEV-01/PMD-01 dashboard-composition E2E suites (`docs/stories/SHP-04.md` § Test mapping); `docs/config/project-commands.yaml`'s `test_e2e` (Playwright) execution is itself deferred to `/arh-validate-feature` for every story, not SHP-04-specific. No runner-setup task needed here: SHP-04 declares zero TCs of `type: e2e | performance-requiring-new-runner | contract-requiring-new-runner` — TC-11 (`type: performance`) and TC-01 (`type: contract`) both run under the already-configured pytest runner (no new runner install required); Playwright itself is already installed/configured per `docs/config/project-commands.yaml`'s existing `preflight:` `playwright --version` smoke-check (PGD-02 T-16), not newly introduced by this story. |

### Coverage gates

- Unit/contract coverage threshold: 80% (no `harness.yaml` override found).
- All 11 TCs in `docs/test-cases/SHP-04.json` map to a row above; `coverage_audit.uncovered == []`
  per the source JSON.

## Plan validation

- Date: 2026-09-18
- Verdict: PASS
- Wiring:                PASS  (F-03's new router wired via F-04 `app.main` modify entry; F-09's client fetch lib wired via F-10 proxy route modify/create entry — both new modules have an explicit entry-registration site in `file_plan`)
- Docs:                  PASS  (T2 fires — new HTTP route `GET /api/artifacts/{program_id}` — addressed by T-14 updating root `README.md` API table. T1/T3/T4 do not fire: no new runnable surface, no new env var, no new service/port.)
- Runner-setup:          PASS  (no TC of type `e2e` declared; TC-11 `performance` and TC-01 `contract` both run under the already-installed pytest/vitest runners — no new runner install required. Playwright is pre-existing infra per `project-commands.yaml` preflight, not newly introduced here.)
- Cross-section:         PASS  (`tasks.json` verified programmatically: acyclic DAG, every `file_plan` entry covered by ≥1 task, every task `files[]` id resolves, zero DAG-independent tasks share a file. Every test-strategy layer — contract/unit/security/integration/performance — has a backing task; E2E is explicitly deferred with a documented reason, not silently dropped.)
- Config drift:          PASS  (no new runtime dependency, no new service, no new port introduced by this story — `program_artifacts`/`governance_visibility` both pre-exist. No `preflight:`/`stack-smoke.md` edit needed.)
- Decision-promotion:    PASS  (all 5 `DECISIONS.md` entries are `blast:feature`/`rev:mechanical` — none require `adr:` promotion.)
- Rounds:                1

### Plan validation rounds

| Round | Verdict | Failing dimensions | Action |
|-------|---------|---------------------|--------|
| 1     | PASS    | —                   | Continue to tracker push (orchestrator) |
