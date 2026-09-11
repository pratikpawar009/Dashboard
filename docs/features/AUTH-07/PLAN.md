# AUTH-07 — Implementation Plan

Status: PASS
Story: Session identity endpoint (`GET /api/me`), app-wide logout, and deterministic case-insensitive
persona resolution. Research verdict: GO-WITH-CONDITIONS (78/100). Three mechanisms, deliberately bundled
into one story (RTM Decisions 2026-09-10 "Cost of the merge") but sequenced below so each lands and
reviews independently: **A** session identity, **B** app-wide logout, **C** persona resolution rework.

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log) — 8 entries (D-01..D-08).
One is promoted to a full ADR: `D-05` → [ADR-0011](../../adr/0011-persona-precedence-new-table.md) (new
`persona_precedence` table, `blast:data`). The remaining 7 (`_LOGOUT_PATH` constant, the `name`-claim
fallback chain, the `ambiguous_case_collision` reason string, the `persona_mapping_not_found` event
shape, the `get_current_user`↔`PersonaResolver` coupling + multi-role selection design, test-file
placement, and `dashboard_logout`'s `user_id` sourcing) stay story-local (`blast:feature|service`,
`rev:mechanical`).

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan` — 21 entries, 6 create / 15
modify, spanning `services/api` (16 files) and `apps/web` (2 files) plus root `README.md` and
`services/api/.env.example`. Module hierarchy follows.

## 3. Module Hierarchy

```
services/api/app/
├── core/
│   ├── config.py                        [MODIFY]
│   │   - input:  env / .env
│   │   - output: Settings (adds frontend_login_url, persona_precedence_order)
│   │   - public: settings, get_settings(request) -> Settings
│   ├── persona_resolver.py              [MODIFY]
│   │   - input:  role: str | roles: list[str]
│   │   - output: persona: str
│   │   - public: resolve(role: str) -> str                (UNCHANGED signature)
│   │             resolve_precedence(roles: list[str]) -> str   (NEW, additive)
│   │   - reshaped internals: casefolded tier lookup, same-tier collision detection,
│   │     casefolded cache key, 3-tier precedence loading, persona_mapping_not_found event
│   └── auth.py                          [MODIFY]
│       - input:  Authorization: Bearer <jwt>, PersonaResolver (new Depends)
│       - output: CurrentUser (adds name: str | None, roles: list[str])
│       - public: get_current_user(...) -> CurrentUser      (Depends signature unchanged
│                 in shape — one more Depends param, same call convention)
├── api/
│   └── me.py                            [CREATE]
│       - input:  CurrentUser, PersonaResolver
│       - output: MeResponse {name, persona}
│       - public: GET /api/me
├── schemas/
│   └── me.py                            [CREATE]
│       - public: MeResponse(BaseModel, extra="forbid") { name: str | None, persona: str }
├── auth/
│   └── oidc.py                          [MODIFY]
│       - input:  Settings, optional Authorization: Bearer <jwt>
│       - output: 302 Location / 501
│       - public: GET /auth/logout
│       - new private: _LOGOUT_PATH, _log_dashboard_logout(...)
├── models/
│   ├── ingestion.py                     [MODIFY] — + PersonaPrecedence(rank, persona)
│   └── __init__.py                      [MODIFY] — export PersonaPrecedence
└── main.py                              [MODIFY] — app.include_router(me_router) [WIRING]

services/api/migrations/versions/
└── 005_persona_precedence.py            [CREATE] — additive: persona_precedence table

apps/web/src/app/logout/
└── route.ts                             [CREATE]
    - input:  (browser navigation, no params)
    - output: 302 redirect | 502
    - public: GET /logout
```

#### Navigation / routing map

```
routes/
├── /api/me            (FastAPI)        → app/api/me.py::list... GET /api/me (server, no UI)
├── /auth/logout        (FastAPI)        → app/auth/oidc.py::oidc_logout (server, no UI)
└── /logout             (Next.js)        → apps/web/src/app/logout/route.ts (server Route Handler,
                                            direct-URL-navigation only per AC-15 — no mockup link/button)
```

No screen, component, or mockup is touched by this story (`design: n/a`, `docs/design/schema.json` has
no `AUTH` key) — the table above is the full routing surface this story adds.

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md` — one new Postgres table (`persona_precedence`,
table #20), an in-process 300s precedence cache, and three registered-contract bookmarks (no
feature-internal API authored inline).

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks` — 10 tasks (T-01..T-10; complexity 2×S /
6×M / 2×L). Execution order derives from `predecessors`; parallelism derives from the DAG. Mechanism
independence, concretely: **B** (`T-08` logout route, `T-09` frontend handler) depends only on `T-01`
(Settings) — it runs, merges, and reviews entirely in parallel with **C**'s resolver rework (`T-02`
through `T-06`), which is the highest-risk chain and therefore sequenced first internally. **A**
(`T-07`, `GET /api/me`) necessarily depends on **C**'s finished `auth.py` rework (`T-06`) because the
route reads both `current_user.name` (added there) and the precedence-resolved `current_user.role` — an
unavoidable coupling given `AUTH-07-FR-1`/`FR-6`, not an artificial one. `T-10` (docs) closes the story,
depending on both `T-07` and `T-08` so the README accurately describes both finished routes.

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/AUTH-07.md` § Risk register (7 risks). All 7 are addressed by tasks below —
none are accepted/carried forward, so `pending_carry_forward[]` stays empty for this story.

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|---------------|
| R-1 (Integration — missing frontend-origin config) | HIGH | T-01, T-08 |
| R-2 (Domain — persona precedence config plumbing unbuilt) | HIGH | T-02, T-04, T-05 |
| R-3 (Domain — case-collision + casefolded cache key rework) | HIGH | T-03 |
| R-4 (Domain — `roles: list[str]` ordering semantics) | MED | T-06 |
| R-5 (Integration — AC-25 test strategy, fileConfig logger trap) | MED | T-05 |
| R-6 (Performance — `GET /api/me` rides existing cache, no new budget) | LOW | T-05, T-07 |
| R-7 (Compatibility — AC-21 no-regression under casefolding) | LOW | T-03 |

### Conditions for GO (research_verdict GO-WITH-CONDITIONS)

| Cond | Condition (verbatim, `docs/research/AUTH-07.md` § Conditions for Planning) | Addressed by |
|------|------|------|
| C-1 | Frontend-origin config (AC-10/AC-12): add a new env var to `Settings`, document as required for logout. | T-01, T-08 |
| C-2 | Persona precedence schema (AC-20): specify exact Tier-1/2/3 structure; unset-at-all-tiers falls back to the hardcoded default order. | T-02, T-04 |
| C-3 | Case-collision handling (AC-22): design collision detection — fail on init for Tier-1/Tier-2, raise on Tier-3 query-result dedup. | T-03 |
| C-4 | Test strategy for AC-25 (unmapped-role event): confirm `_RecordCapturingHandler` reuse, no new test infrastructure. | T-05 |
| C-5 | Acceptance-criteria cross-check: every AC (1–26) mapped to a concrete test. | See § Test strategy — 2 formal test cases (`AUTH-07-TC-01`/`TC-02`) cover 8 ACs under this run's Product-Gate-approved 2-TC cap (`docs/test-cases/AUTH-07.json`); the remaining 18 ACs + all 8 FRs + the NFR-performance id are carried as explicit, named unit/integration tests bundled into their owning task (`ac_refs` on T-01 through T-09 above — every id in `coverage_audit.uncovered` resolves to a task, per REQUIREMENTS.md § Open questions' explicit instruction to widen the cap or carry the gap into PLAN.md tasks). |

### Cross-Feature Dependency Notes

None. All three upstreams (AUTH-01, AUTH-02, AUTH-05) are shipped and frozen; both downstream consumers
(OVW-05, PGD-07) build against the now-filled `session-identity-api` contract shape (`docs/requirements/
api.md#session-identity-api`), not against this story's code or tasks.

## 7. Test Strategy

`docs/test-cases/AUTH-07.json` holds exactly 2 test cases (`AUTH-07-TC-01`, `AUTH-07-TC-02`), hard-capped
by explicit user directive at plan-requirements time — **not** a completeness judgment.
`coverage_audit.uncovered` lists 25 ids: `AUTH-07-AC-1`..`AC-17`, `AC-22`, `AC-24`, `AUTH-07-FR-1`..`FR-5`,
`AUTH-07-NFR-performance`. Per the PRD's own `## Open questions` instruction, this gap is carried
explicitly below rather than papered over: every uncovered id is assigned to a named task and a named
test file/case in the table below — none are silently left untested.

| Layer | Test path | TCs / ACs covered | Notes |
|---|---|---|---|
| Unit | `services/api/tests/unit/test_auth_config.py` | FR-3 (`frontend_login_url`), FR-6 Tier-1 (`persona_precedence_order` fail-open parse) | T-01 |
| Unit | `services/api/tests/test_migrations.py` + `tests/fixtures/prd_8_4_schema.json` + `tests/test_models.py` (fixture-parametrized, no code change needed there) | FR-6 (`persona_precedence` schema-diff + fixture-constraint gates) | T-02; mirrors `003_program_roster`'s 3-file update discipline (alembic-patterns skill) |
| Unit | `services/api/tests/unit/test_persona_resolver.py` | AC-18, AC-20, AC-21, AC-22, AC-23, AC-25, AC-26, FR-6, FR-7, FR-8, NFR-performance | T-03, T-04, T-05 (sequenced, same file); `_RecordCapturingHandler` direct-attach pattern for every log assertion (C-4) |
| Unit | `services/api/tests/unit/test_auth_jwt_validation.py` | AC-2, AC-6, AC-19, AC-24, FR-2 | T-06 |
| Unit + Integration | `services/api/tests/unit/test_me.py` | AC-1, AC-3, AC-4, AC-5, AC-7, FR-1, **`AUTH-07-TC-01`** (→ `pratikpawar009/Dashboard#281`, type `integration`) | T-07; TC-01 exercised end-to-end via `GET /api/me` (3 token-role-order variants → identical `architect` persona) |
| Security | `services/api/tests/unit/test_persona_resolver.py` | **`AUTH-07-TC-02`** (→ `pratikpawar009/Dashboard#282`, type `security`), AC-25, AC-26 | T-05; `_RecordCapturingHandler` attached directly to `app.core.persona_resolver`'s logger, force-enabled + de-propagated — immune to Alembic's `fileConfig(disable_existing_loggers=True)` sweep |
| Unit | `services/api/tests/unit/test_auth_logout.py` | AC-10, AC-11, AC-12, AC-16, FR-4 | T-08 |
| Unit (vitest) | `apps/web/src/app/logout/route.test.ts` | AC-8, AC-9, AC-14, AC-15, FR-5 | T-09; mirrors `login/route.test.ts`'s native-mock idiom (no MSW) |
| Manual | local verification checklist (PR description) | AC-13 (Keycloak ends SSO; `/login` re-renders its own form, not silent re-auth), AC-14 (all six dashboard routes redirect through sign-in) | No local Keycloak in `docker-compose.yml`; `test_e2e` is empty in `docs/config/project-commands.yaml` (no Playwright/Cypress) — the full RP-initiated round trip is verified against the real Apexon realm, per story `## Test mapping` and research risk register. This is the ONLY manually-verified item; everything else in this table is automated in this story. |

### Coverage gates

- Unit coverage threshold: 80% (no `harness.yaml` override found).
- E2E suite: N/A for this story — `test_e2e` is empty (no runner installed); no e2e/performance/contract-
  typed TC exists in `docs/test-cases/AUTH-07.json` (both are `integration`/`security`), so the
  Runner-setup plan-validation dimension has no trigger and needs no setup task.
- Performance: no new latency budget is introduced (NFR-Performance) — `T-05`'s call-count assertion
  (bounded Tier-3 queries) is the concrete regression guard; no new file under `tests/perf/` is warranted,
  since there is no new budget to benchmark against.

### Plan validation rounds

| Round | Verdict | Failing dimensions | Action |
|-------|---------|---------------------|--------|
| 1 | PASS | — | None — proceed to hand-off |

## Plan validation

- Date: 2026-09-10
- Verdict: PASS
- Wiring: PASS (`app.main` router registration for `app/api/me.py` is `F-14`, a `modify` entry in `T-07`; `app/models/__init__.py` export for `PersonaPrecedence` is `F-05`, a `modify` entry in `T-02`. `apps/web/src/app/logout/route.ts` needs no registration file — Next.js App Router auto-registers by file convention, same as the shipped `/login` precedent.)
- Docs: PASS (T2 new HTTP routes `GET /api/me`/`GET /auth/logout` and T3 new env vars `FRONTEND_LOGIN_URL`/`PERSONA_PRECEDENCE_ORDER` both fire → `T-10` updates root `README.md` API table + Environment variables table + `services/api/.env.example`. T1/T4 do not fire — no new runnable surface, service, or port is introduced.)
- Runner-setup: PASS (no `e2e`/`performance`/`contract`-typed TC exists in `docs/test-cases/AUTH-07.json` — both declared TCs are `integration`/`security`, runnable on the already-installed `pytest`/`pytest-asyncio` runner; no new runner setup required.)
- Cross-section: PASS (`tasks.json` verified programmatically: 10 tasks `T-01`..`T-10`, acyclic, every `predecessors`/`files` id resolves; every `file_plan` entry covered by ≥1 task; no two DAG-independent tasks share a file (checked exhaustively); every § 7 test-layer type — unit, security, manual — has a backing task; no e2e/perf/contract type is declared, so none is required.)
- Config drift: PASS — N/A (no new runtime dependency added (C1), no new service/stack entry (C2), no new port (C3) — `docs/config/project-commands.yaml preflight:` and `docs/config/stack-smoke.md` need no edit. `FRONTEND_LOGIN_URL`/`PERSONA_PRECEDENCE_ORDER` are plain env vars on the existing `fastapi-2` stack, handled by the Docs dimension above, not Config drift.)
- Decision-promotion: PASS (`DECISIONS.md` has one `blast:data` entry, `D-05`, and it carries `adr:ADR-0011`. All other entries are `blast:feature` or `blast:service` with `rev:mechanical`, correctly left at `adr:—`.)
- Rounds: 1
