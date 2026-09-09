# AUTH-06 — Implementation Plan

Roster-sourced program membership — `session.programs` derives from `program_roster` (ING-10),
never Keycloak `groups`. Research verdict: GO-WITH-CONDITIONS, 78/100. Product Gate: APPROVE
2026-09-08.

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log). The overarching
choice — program membership comes from `program_roster`, never Keycloak groups — is a standing
project boundary already settled in REQUIREMENTS.md/the story's own Decision log, not re-decided
here. Four planning-time entries this phase makes: D-01 (the roster DB session travels as
`get_current_user`'s own `Depends(get_db)` parameter, not a `PersonaResolver`-style
resolver-owned `session_factory` — leverages the `get_db`-override convention 4+ existing test
files already use), D-02 (dev-bypass drops the `groups` claim entirely rather than leaving it
empty), D-03 (cold cache-miss perf budget set to p95 < 100ms, mirroring `PersonaResolver`'s own
Tier-3 budget), D-04 (test-file scope widens to 7 files, not the 3 REQUIREMENTS.md names, as a
structural consequence of `get_current_user`'s new dependency signature — see § 6). All four
`blast:feature`, `rev:mechanical` — no ADR promotion.

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan`. 16 files: 2 created
(`app/core/program_roster_resolver.py`, `tests/perf/test_program_roster_resolver_perf.py`), 14
modified (`app/core/auth.py`, `app/core/config.py`, `app/auth/dev_bypass.py`, `app/main.py`,
`services/api/.env.example`, root `README.md`, `docs/requirements/auth.md`, and 7 test files —
`test_auth_groups.py`, `test_auth_dev_bypass.py`, `test_auth_config.py`,
`test_auth_jwt_validation.py`, `test_ingest_token_isolation.py`, `test_programs.py`,
`test_programs_perf.py`).

## 3. Module Hierarchy

```
app/
├── core/program_roster_resolver.py                   [F-01, new]
│   - input:  email: str, db: AsyncSession (per-call, D-01)
│   - output: list[str] (distinct, non-removed program_ids) | raises
│             ProgramRosterResolutionError on a 3.0s query timeout
│   - public: class ProgramRosterResolver:
│               async def resolve(self, email, db) -> list[str]
│             get_program_roster_resolver(request) -> ProgramRosterResolver
│   - cache:  {email: (program_ids, expiry_ts)}, 300s TTL, time.monotonic(),
│             asyncio.Lock double-checked re-read (mirrors PersonaResolver)
│
├── core/auth.py                                       [F-02, modified]
│   - input:  Authorization: Bearer <jwt>, Depends(get_settings),
│             Depends(get_jwks_cache), Depends(get_db) [new],
│             Depends(get_program_roster_resolver) [new]
│   - output: CurrentUser{user_id, email, role, groups, programs}
│   - change: _parse_programs deleted; programs now derives from
│             program_roster_resolver.resolve(email, db), EXCEPT on the
│             kid == DEV_BYPASS_KID branch, which reads claims['programs']
│             directly with zero roster query (FR-3)
│
├── auth/dev_bypass.py                                 [F-04, modified]
│   - input:  DevBypassRequest{role?, email?, programs?}
│   - output: TokenResponse (claims carry 'programs' as a top-level key;
│             'groups' key removed entirely, D-02)
│
└── core/config.py                                     [F-03, modified]
    - change: program_group_prefix field deleted; oidc_scope default
              'openid profile email' (groups no longer requested)
```

No navigation/routing map, no new trigger/event map (`DATA-DESIGN.md` §10 is N/A) — backend-only
session-construction change, no new route, no UI surface.

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md`. Summary: read-only against the existing
`program_roster` table (ING-10, no migration); the resolver's own cache is the only new ephemeral
state (per-process, 300s TTL, TTL-expiry-only invalidation — a documented, accepted limitation,
Condition 3/Risk #2); `program_membership_resolved` logs a 3-field PII-free allowlist; no new
runtime dependency (`asyncio.Lock`/`wait_for` only).

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks`. Execution order derives from
`predecessors`; parallelism derives from the DAG. 17 tasks: T-01 (resolver module) → {T-02 (wiring),
T-03 (auth.py branch)} parallel-eligible; T-04 (dev_bypass.py claim) independent from the start →
T-05 (config.py field deletion, waits on both T-03 and T-04) → {T-06 (.env.example), T-07 (README),
T-08 (auth.md contract fill)} parallel-eligible. Test cluster: T-09 → T-10 (same file, sequential)
for roster-derivation + cache mechanics; T-11 (dev-bypass discriminator test); T-12 (config test);
T-13/T-14 (stub-resolver wiring for two discovered custom-app test files); T-15 (`test_programs.py`
fixture rewrite); T-16 (comment-only fix); T-17 (Condition-1 perf prototype, depends only on T-01).

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/AUTH-06.md` § Risk register (numbered 1–9 there; referenced as `R-01`
through `R-09` below, per this repo's `plan-authoring` convention). HIGH/CRITICAL risks must be
addressed by at least one task id or explicitly accepted.

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|--------------|
| R-01 (Integration: roster query on every request adds auth-path latency) | HIGH | T-01, T-02, T-03, T-10, T-17 |
| R-03 (Domain: dev-bypass mechanism, resolved pre-plan via the kid discriminator) | HIGH (resolved) | T-03, T-04, T-11 |
| R-04 (Dependency: `_parse_programs`/`program_group_prefix` used across ~15 sites) | MED | T-03, T-04, T-05, T-06, T-07, T-12, T-13, T-14, T-15, T-16 |
| R-05 (Performance: cache-miss becomes a per-request DB round trip if TTL is insufficient) | MED | T-01, T-10, T-17 |
| R-06 (Compatibility: `test_auth_groups.py`'s claim-based tests must become roster-fixture tests) | MED | T-09, T-10, T-15 |
| R-07 (Security: email must never be logged in the roster-lookup path) | LOW | T-01, T-10 |
| R-09 (Domain: `program_roster` vs `program_members` clarity) | LOW | T-03 (query targets `program_roster` only, verified by T-09's query spy) |

### Risks accepted (carry-forward)

| Risk id | Severity | Rationale |
|---------|----------|-----------|
| R-02 (Domain: TTL eventual consistency — a roster re-push is invisible for up to 300s per worker) | HIGH | accepted per REQUIREMENTS.md Scope § Out ("Cache invalidation triggered by ING-10's `POST /api/ingest/manifest` — future work") — documented operator-facing in README via T-07; revisit if a future story adds a push-invalidation hook from the ingest endpoint. |
| R-08 (Integration: `dev_bypass.py`'s Settings dependency on `program_group_prefix`) | LOW | resolved by construction (D-02/T-04 removes the dependency outright, per the AC-4 resolution already settled at research time) rather than an accepted residual risk — listed here only because research's own table still carries it; no separate acceptance action needed. |

### Conditions for GO (research_verdict GO-WITH-CONDITIONS)

| Cond | Condition (verbatim) | Addressed by |
|------|----------------------|--------------|
| C-1  | Profile AUTH-04 p95 latency budget fit in PLAN — a dedicated prototype task must measure the cache-miss (`db_query`) tier's latency against the dev database before implementation sign-off | T-17 |
| C-2  | Test refactoring scope review in PLAN — a scoped, estimated task for fixturing `program_roster` state and rewriting claim-based assertions, sized as its own unit of work | T-09, T-10, T-11, T-12, T-13, T-14, T-15 |
| C-3  | Document OIDC_SCOPE default change and eventual-consistency TTL as known limitations | T-06, T-07 |

### Cross-Feature Dependency Notes

None. Both upstreams (ING-10's `program-roster-schema`, AUTH-01's `session`) are shipped on `main`
(PR #244, and AUTH-01 at `phase: review`). No other in-flight feature shares a task or file with
this plan — `GET /api/programs` (AUTH-04) is a downstream consumer with zero code changes (AC-8),
not a concurrent editor of any file this plan touches.

## 7. Test Strategy

| Layer | Test path | TCs covered | Notes |
|---|---|---|---|
| Integration | `services/api/tests/unit/test_auth_groups.py` | AUTH-06-TC-01 | `migrated_db`/`test_session` live-DB fixtures + `ProgramRoster` seeding; AC-1/AC-2/AC-3/AC-9, FR-1; query-spy proves `program_roster`-only reads with `removed_at IS NULL` |
| Performance | `services/api/tests/unit/test_auth_groups.py` | AUTH-06-TC-03 | Same file (sequential after TC-01); cache/lock/timeout mechanics, AC-5/FR-2, NFR-performance/observability; PII-free log-record assertions |
| Security | `services/api/tests/unit/test_auth_dev_bypass.py` | AUTH-06-TC-02 | `kid == DEV_BYPASS_KID` regression guard — forged-Keycloak-token-with-programs-claim negative case, AC-4/FR-3/NFR-security |
| Unit | `services/api/tests/unit/test_auth_config.py` | manual (AC-6) | `Settings` field/default deletion — no dedicated TC id in `docs/test-cases/AUTH-06.json` (AC-6 is inspection-verified per the story's accepted coverage gap) |
| Unit | `services/api/tests/unit/test_auth_jwt_validation.py`, `test_ingest_token_isolation.py`, `test_programs.py` | manual (regression) | Discovered ripple (D-04) — stub-resolver wiring + fixture rewrites protecting existing coverage from silently breaking or silently passing for the wrong reason; not new TC coverage, existing TC ids unchanged |
| Performance | `services/api/tests/perf/test_program_roster_resolver_perf.py` | manual (Condition 1) | Dedicated prototype: cold `db_query`-tier p95 < 100ms against a live migrated test DB — no TC id (a research-condition deliverable, not a story AC), reuses the existing `tests/perf/` plain-`perf_counter` runner |
| E2E | N/A | — | No UI surface in this story (Test mapping: E2E N/A) |

`AUTH-06-AC-6`, `AUTH-06-AC-7`, `AUTH-06-AC-8` are the story's accepted coverage gap
(`docs/features/AUTH-06/REQUIREMENTS.md` § Accepted at gate) — verified by inspection at
`/arh-validate-feature`, not by a dedicated automated TC. This PLAN's T-05/T-06/T-07/T-12/T-15
tasks implement and regression-protect the underlying behaviour those ACs describe even though no
TC id maps to them directly.

### Coverage gates

- Unit coverage threshold: 80% (no `harness.yaml` override — framework default).
- No e2e suite exists or is required for this story.
- Performance test (T-17) runs as part of the standard `pytest` invocation
  (`docs/config/project-commands.yaml` `test`/`test_unit`) — this repo's existing `tests/perf/`
  convention is not gated behind a separate `perf` CI label (`CI: none` per `CLAUDE.md`).

### No-placeholder check

Grepped for `TBD|to be determined|TODO|FIXME|as appropriate|as needed|add error handling|similar to|details to follow|lorem ipsum|placeholder text` — zero hits.

## Plan validation

- Date: 2026-09-08
- Verdict: PASS
- Wiring:                PASS  (new module `app/core/program_roster_resolver.py` [F-01] has its entry-registration site `app/main.py` [F-05, modify] listed — `app.state.program_roster_resolver` construction, mirroring `app.state.persona_resolver`; its consumer `app/core/auth.py` [F-02, modify] is also listed. No new router/route to register — the module is consumed via `Depends()`, not mounted)
- Docs:                  PASS  (T3-adjacent: this story RETIRES an env var rather than adding one, so the literal T3 trigger does not fire, but REQUIREMENTS.md's own AC-6/AC-7 mandate root `README.md` + `.env.example` updates regardless — T-06/T-07 cover both explicitly. T1/T2/T4 do not fire: no new runnable surface, no new/changed HTTP route (AC-8: zero change to `app/api/programs.py`), no new service/port)
- Runner-setup:          PASS  (TC-01/02/03 are integration/security/performance types, but all reuse pre-existing infrastructure — `migrated_db`/`test_session` live-DB fixtures already used by `test_manifest_ingest.py`/`test_programs.py`, and the `tests/perf/` plain-`perf_counter` runner already used by `test_persona_resolver_perf.py`/`test_programs_perf.py`. No new runner/tool to install; T-17 adds a test file only)
- Cross-section:         PASS  (DAG acyclic, no self-references, every `predecessors` id resolves — verified programmatically. Every test-strategy layer/TC type — integration/performance/security/unit — is matched to ≥1 task. Every `file_plan` F-NN id is referenced by ≥1 task's `files[]`, and every task `files[]` id resolves in `file_plan` — verified programmatically, 16/16 files used, 0 orphans. Parallel-safety: no two DAG-independent tasks share a file — verified programmatically across all 17×16/2 task pairs, 0 violations; the one shared-file pair (T-09/T-10 on F-09) is serialized via a direct `predecessors` edge)
- Config drift:          PASS  (no new runtime dependency — `asyncio.Lock`/`wait_for` only, already stdlib; no new service; no new port. `docs/config/project-commands.yaml` `preflight:` and `docs/config/stack-smoke.md` need no edit)
- Decision-promotion:    PASS  (all four `DECISIONS.md` entries — D-01 through D-04 — are `blast:feature`/`rev:mechanical`; none meets the `blast:{system,data}` or `rev:effectively-irreversible` promotion trigger, so `adr:—` is correct for all four. The overarching groups-retirement architecture is a pre-decided standing project boundary, not a new planning-time decision, and is not logged in `DECISIONS.md` at all — mirrors AUTH-04's precedent of not re-logging ADR-0005's pre-decided response shape)
- Rounds:                1
