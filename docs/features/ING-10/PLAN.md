# ING-10 — Implementation Plan

`POST /api/ingest/manifest` — program identity + team roster ingest. Research verdict:
GO-WITH-CONDITIONS (74/100), all three conditions resolved in `REQUIREMENTS.md` §
Addressing Research Conditions. Product Gate: APPROVE, with a deliberate 2-test-case coverage
cap (9 ids uncovered by an approved TC — see § 7).

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log). Nine entries
(D-01..D-09); D-01 (new `program_roster` table, blast:data / rev:effectively-irreversible) is
promoted to `docs/adr/0010-program-roster-new-table.md`. The remaining eight are
`blast:feature`/`service` + `rev:mechanical`, story-local.

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan`.

### Module hierarchy

```
app/
├── models/roster.py
│   - input:  (none — declarative ORM model)
│   - output: program_roster rows (SQLAlchemy 2.0 DeclarativeBase)
│   - public: class ProgramRoster (Base)
├── core/role_map.py
│   - input:  role slug (str)
│   - output: long-form dashboard role (str) | None
│   - public: map_role_slug(slug: str) -> str | None
├── schemas/manifest.py
│   - input:  raw request JSON
│   - output: validated ManifestIn / ManifestResponse models
│   - public: ManifestIn, ProgramIdentityIn, TeamMemberIn, ManifestResponse, SectionCounts,
│             RosterEntryResult
├── services/manifest_ingest.py
│   - input:  ManifestIn, program_id (str), AsyncSession
│   - output: ManifestResponse
│   - public: async def ingest_manifest(db, program_id, payload, token_label)
│             -> ManifestResponse
│             raises HTTPException(400) on a program: schema/enum failure (D-05/D-08)
│             NOTE (AF-08, corrected 2026-09-08): pinned a 3-parameter
│             signature until `token_label` was added. FR-2 makes it a
│             REQUIRED field of ingest_manifest_write, PLAN assigns that
│             event to this service, and only the router can resolve
│             IngestToken.label -- so 4 params is the only shape that
│             satisfies all three. Reasoning: QUESTIONS.md Q-01.
└── api/manifest.py
    - input:  HTTP POST /api/ingest/manifest {programId, program, team[]}
    - output: 200 ManifestResponse | 400 | 401 | 403 | 413
    - public: router (APIRouter), mounted in app/main.py (F-08)
```

### Navigation / routing map

N/A — backend-only story (`design: n/a`, no epic in `docs/design/schema.json`). No trigger map
either: this is a synchronous HTTP endpoint, not an event-source/consumer-group addition.

## 3. Module Hierarchy

See § 2 above — the module tree there **is** this section's content per `plan-authoring`'s
pointer convention (§2/§3 combined: §2 is the `tasks.json` pointer + the hierarchy diagram, since
splitting the diagram into a separate numbered section would duplicate rather than add).

`app/api/ingest.py`'s existing (unregistered) router is explicitly **not** part of this module
tree — D-02 keeps `POST /api/ingest/manifest` on its own router precisely so this story's module
graph never touches that stub.

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md`.

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks`. Execution order derives from
`predecessors`; parallelism derives from the DAG. 19 tasks (T-01..T-19): 13 S, 5 M, 1 L
(T-06, `manifest_ingest.py` — the two-tier-validation + upsert + soft-delete + logging core).

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/ING-10.md` § Risk register. HIGH risks must be addressed by at least
one task id from § 5; MED/LOW risks inherit their mitigation from the research doc and need no
re-statement here except where explicitly accepted below.

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|--------------|
| R-01 (PII logging violation) | HIGH | T-06, T-10 |
| R-02 (partial-commit semantics) | HIGH | T-06, T-09 |

### Risks accepted (carry-forward)

| Risk id | Severity | Rationale |
|---------|----------|-----------|
| R-03 (role-map has no persistence contract) | MED | accepted (D-03) — in-process/`ING-10`-scoped only; wiring `ING-08`'s Keycloak writer onto a shared table remains an undecided scope change to an already-shipped story, not this story's call |
| R-07 (p95 < 500ms budget untested) | MED | accepted — REQUIREMENTS.md's Product Gate explicitly caps this run at 2 test cases and lists `NFR-performance` as a known-uncovered id; no perf runner is declared for the backend stack (`docs/config/project-commands.yaml` `test_e2e`/`test_integration` are empty) to add a k6/locust harness against in this pass |
| R-09 (repo's own `.harness/profile.yaml` non-conforming) | LOW | accepted — explicitly out of this story's scope in REQUIREMENTS.md, touches `ING-06`'s dogfooding path |
| R-10 (`program_members` enrichment from roster deferred) | LOW | accepted — explicitly out of this story's scope in REQUIREMENTS.md, carried forward for `PGD-05` |

### Conditions for GO (research_verdict GO-WITH-CONDITIONS)

| Cond | Condition (verbatim) | Addressed by |
|------|----------------------|--------------|
| C-1  | Confirm AC-5/AC-6 partial-commit semantics with user; update story's AC wording or DECISIONS if ambiguity exists | T-06 (implements the two-tier split exactly as resolved in `REQUIREMENTS.md` § Addressing Research Conditions / story Decision log 2026-09-08) |
| C-2  | Add PII logging lint rule or code-review emphasis; spot-check `manifest_ingest.py` for `email`/`name` in logger statements | T-06 (implements the `ingest_manifest_write` field allowlist, FR-2), T-10 (unit test enforcing it) |
| C-3  | Confirm `Upgradation` color hex with design; update `programStyle.ts` AC-10 fixture if design changes | T-16 (`programStyle.ts` widening — no hex invented, documented fallback per RTM Decisions 2026-09-08), T-18 (`tokens.md` gap recorded) |

### Cross-Feature Dependency Notes

None. `AUTH-06` depends on the `program_roster` table (not this story's HTTP endpoint) and is not
yet planned — no in-flight cross-feature task dependency exists today.

## 7. Test Strategy

| Layer | Test path | TCs covered | Notes |
|---|---|---|---|
| Unit | `services/api/tests/unit/test_role_map.py` | unbacked | 6-slug mapping + unknown-slug behaviour incl. deliberately-unmapped `admin` (FR-3; D-10) |
| Integration | `services/api/tests/unit/test_manifest_ingest.py` | ING-10-TC-01, ING-10-TC-02 (validation half) | Real Postgres via `migrated_db`/`test_session` (ING-01 precedent, no mocks at the integration boundary) |
| Security | `services/api/tests/unit/test_manifest_pii_logging.py` | ING-10-TC-02 (PII half) | `ingest_manifest_write` field-allowlist assertion, mirrors AUTH-03 TC-15 |
| Integration | `services/api/tests/unit/test_manifest_auth_scope.py` | unbacked | Covers AC-1 (401)/AC-2 (403) — route-level wiring smoke only, not a re-test of `ingest_auth`'s own suite |
| Integration | `services/api/tests/unit/test_manifest_roster_removal.py` | unbacked | Covers AC-7 — soft-delete on re-push + un-delete on reappearance |
| Integration | `services/api/tests/unit/test_manifest_payload_cap.py` | unbacked | Covers AC-8/FR-5 — 413 over 500 raw entries, zero writes |
| Integration | `services/api/tests/unit/test_manifest_identity_survives_rebuild.py` | unbacked | Covers AC-9 (the notable residual) — manifest-written identity survives `rebuild_program_rollups()` |
| Unit (regression) | `services/api/tests/test_migrations.py` (modified) | none | Keeps BED-01's `EXPECTED_TABLES` invariant in sync with table #19 |
| Unit (frontend) | `apps/web/src/lib/programStyle.test.ts` (modified) | unbacked | Covers AC-10/FR-6 — new short-name keys + `Upgradation`-still-falls-through regression |

**Coverage disclosure (Product Gate accepted deviation).** The 2 approved test cases
(`ING-10-TC-01`, `ING-10-TC-02`) cover the core upsert/alias/role-mapping mechanism end-to-end and
both HIGH research risks (two-tier validation, PII-in-logs). Per REQUIREMENTS.md, 9 ids are
uncovered by an *approved* test case: `AC-1`, `AC-2`, `AC-7`, `AC-8`+`FR-5`, `AC-9`, `AC-10`+`FR-6`,
`NFR-performance`. This plan adds five **unbacked** plan-level test tasks (T-11..T-14, T-17) that
close real coverage for six of those nine ids (`AC-1`, `AC-2`, `AC-7`, `AC-8`, `FR-5`, `AC-9`,
`AC-10`, `FR-6`) without inventing a new `TC-NN` id in the gated `docs/test-cases/ING-10.json`.
**`NFR-performance` (p95 < 500ms) stays genuinely uncovered** — no perf-test task is added (R-07,
accepted carry-forward, § 6) — and no e2e/performance/contract-typed TC exists in
`docs/test-cases/ING-10.json`, so the Runner-setup validation dimension does not fire for this
plan.

Coverage threshold: 80% (no override in `harness.yaml`). Unit coverage gate per
`.claude/rules/performance-baseline.md`/project defaults; `docs/config/project-commands.yaml`'s
`test` command (`cd services/api && uv run pytest`, plus `pnpm -C apps/web test`) runs every layer
above — no new test runner is introduced (no e2e/performance/contract TC type exists here).

## Plan validation

- Date: 2026-09-08T15:35:00Z
- Verdict: PASS
- Wiring: PASS (new modules `roster.py`→`models/__init__.py` (F-03, `modify`); `manifest.py` router→`app/main.py` (F-08, `modify`) — the mandatory Hard Fact #7 wiring. `role_map.py` (F-04) and `manifest.py` schemas (F-05) each have a single consumer that is itself a new file in this same plan (`manifest_ingest.py`, F-06), which in turn is consumed by `manifest.py`'s router (F-07) — every link in that chain is transitively reachable, terminating at the one `modify` entry (F-08) that proves the whole chain is live and registered, not orphaned. This is the correct application of the dimension's intent (catch a module nothing ever imports) for a same-story new-file-imports-new-file chain, matching `personal_usage.py`'s precedent of a service module with no package-barrel re-export)
- Docs: PASS (T2 fires — new HTTP route `POST /api/ingest/manifest` — addressed by T-19, root `README.md` API table, matching the existing `/auth/*`/`/api/programs`/`/api/overview/program-detail`/`/api/personal-usage` rows' style; T1/T3/T4 do not fire — no new runnable surface, no new env var, no new service/port)
- Runner-setup: PASS (no TC in `docs/test-cases/ING-10.json` is typed `e2e`/`performance`/`contract` — both declared TCs are `integration`/`security` — so no runner-setup task is required)
- Cross-section: PASS (DAG acyclic, 19 tasks, verified by script: no cycles, no dangling `predecessors`, every `file_plan` entry covered by ≥1 task, every task `files[]` id resolves in `file_plan`, zero DAG-independent-pair file collisions; every test-strategy layer type — unit/integration/security — has a backing task)
- Config drift: PASS (no new runtime dependency — D-04 explicitly rejects `pydantic[email]`/`email-validator` to avoid one; no new service, port, or `docker-compose.yml` entry; `docs/config/project-commands.yaml`/`docs/config/stack-smoke.md` need no edit)
- Decision-promotion: PASS (D-01 is the only `blast:data`/`rev:effectively-irreversible` entry in `DECISIONS.md`, promoted to `adr:ADR-0010`; D-02..D-09 are all `blast:feature`/`service` + `rev:mechanical`, correctly left at `adr:—`)
- Rounds: 1
