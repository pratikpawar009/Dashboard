# AUTH-03 — Implementation Plan

RBAC check library (org-access, program-visibility, individual-usage, member-in-program, governance). Backend-only, no UI surface, no routes of its own — five pure-function checks published via the `rbac-checks` contract for 16 downstream consumers.

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log). Six entries (D-01..D-06); none require ADR promotion (`blast:` is `feature`/`service`, `rev:` is `mechanical` on every entry — none reach `blast:system`/`blast:data`/`rev:effectively-irreversible`).

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan`.

## 3. Module Hierarchy

```
services/api/app/core/
└── rbac.py                                                          [NEW — F-01]
    module state:
    ├── _persona_resolver: PersonaResolver | None = None             (D-06 — process-lifetime, set once)
    └── _GOVERNANCE_PERSONAS: tuple[str, ...] =
            ("architect", "product-manager", "developer")            (D-04, AUTH-03-FR-3 — hardcoded)

    configure(persona_resolver: PersonaResolver) -> None              (D-06)
    - input:  a live PersonaResolver instance
    - output: none — sets the module-level reference
    - public: called exactly once, by app/main.py::create_app() (F-05), immediately after
      app.state.persona_resolver is constructed

    org_access(current_user: CurrentUser) -> None                     (AC1, AC2)
    - input:  current_user
    - output: None (authorized) | raises HTTPException(403) (denied)
    - public: persona == "cio" via _resolver().resolve(current_user.role);
      logs rbac_check_org_access (both outcomes, {user_id, persona, outcome, timestamp})

    program_visibility(current_user: CurrentUser, program_id: str) -> None   (AC3)
    - input:  current_user, program_id
    - output: None, always — open-aggregate (D-03/C-3); never raises, never reads
      current_user.programs, never resolves persona, emits no log event (AUTH-03-FR-2)
    - public: veto gate only — R-003 stays OPEN (flagged for /arh-security-review); downstream
      consumers must read CurrentUser.programs directly for roster questions, never infer
      membership from a passing call here

    individual_usage_visibility(current_user: CurrentUser, target_user_id: str) -> None   (AC4)
    - input:  current_user, target_user_id
    - output: None (self OR cio) | raises HTTPException(403) + individual_view_denied
      ({user_id, target_user_id, outcome, timestamp}, denial only)
    - public: self path never resolves persona at all

    member_in_program_visibility(current_user, program_id: str, target_member_id: str) -> None   (AC5)
    - input:  current_user, program_id, target_member_id
    - output: None (program_visibility passes AND (self OR cio)) | raises HTTPException(403)
      + member_view_denied ({user_id, program_id, target_member_id, outcome, timestamp}, denial only)
    - public: calls program_visibility(current_user, program_id) FIRST (AUTH-03-FR-4) — its
      denial short-circuits before self-or-cio is ever evaluated (AUTH-03-TC-10)

    governance_visibility(current_user, program_id: str | None = None) -> None   (AC6, AC7)
    - input:  current_user, optional program_id
    - output: None (persona in _GOVERNANCE_PERSONAS AND, if program_id given, program_visibility
      passes) | raises HTTPException(403) + rbac_check_governance_visibility (both outcomes,
      {user_id, persona, outcome, timestamp})
    - public: persona gate evaluated BEFORE program_visibility (AUTH-03-FR-4) — a persona denial
      short-circuits before program_visibility is ever called (AUTH-03-TC-15); a passing persona
      gate does not itself pass the check when program_id is given and program_visibility denies
      (AUTH-03-TC-14)

    private helpers (no downstream contract — internal to rbac.py only):
    ├── _resolver() -> PersonaResolver
    │     raises RuntimeError("rbac.configure() was never called") if _persona_resolver is None
    ├── _resolve_persona_or_deny(current_user, event_name, extra_fields) -> str
    │     raises HTTPException(403); catches PersonaResolutionError -> logs at ERROR (D-01/C-1),
    │     PersonaNotFoundError -> logs at INFO (D-01/C-1) — two separate except clauses, never
    │     a bare `except Exception`
    └── _log_event(event_name: str, outcome: Literal["authorized", "denied"], **fields) -> None
          enforces the exact per-event field allowlist (D-02/C-2) and the literal outcome string
          (C-4) — the single place every one of the four events is emitted from
```

No navigation/routing map — backend library, no routes, no trigger map (`REQUIREMENTS.md` § Scope, Out: "Route wiring — deferred to each consuming story"). `F-05` (`app/main.py` modify) is the one wiring entry this story needs: `create_app()` must call `rbac.configure(app.state.persona_resolver)` right after constructing the resolver (D-06), or every persona-resolving check raises `RuntimeError` at first call in a real running process. No other consumer/registration site exists inside AUTH-03 itself — the 16 downstream stories each add their own `from app.core.rbac import <check>` import when they wire their own routes, one story at a time, starting with AUTH-04; that wiring is out of scope here by design and is not planned in this PLAN.

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md`.

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks`. Execution order derives from `predecessors`; parallelism derives from the DAG. Seven tasks (T-01..T-07): T-01 (L) scaffolds `rbac.py` with `org_access` + `program_visibility` + the shared fail-closed/logging/`configure()` helpers + the `app/main.py` wiring (F-05); T-02 (M) adds `individual_usage_visibility`; T-03 (M) adds `member_in_program_visibility`; T-04 (L) adds `governance_visibility`; T-05/T-06/T-07 (all S) are the contract test, the performance test, and the README doc, each independent of the other two once T-04 lands.

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/AUTH-03.md` § Risk Register. HIGH-severity risks are #1 (Domain — AC3 open-aggregate model, tracked as PRD risk R-003), #2 (Integration — PersonaResolutionError vs PersonaNotFoundError handling), #3 (Observability — PII compliance in log events), #4 (Performance — persona-resolution N+1 across multiple checks in one request). MEDIUM/LOW risks (#5–#10) inherit their mitigation from the research doc and are not re-stated here.

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|--------------|
| R-01 (research #1 — AC3 open-aggregate model; corresponds to PRD-tracked risk **R-003**) | HIGH | T-01 |
| R-02 (research #2 — PersonaResolutionError/PersonaNotFoundError handling) | HIGH | T-01, T-02, T-03, T-04 |
| R-03 (research #3 — PII compliance in the four log events) | HIGH | T-01, T-02, T-03, T-04 |

R-01/**R-003** is implemented exactly as specified (D-03) — `program_visibility` never reads `current_user.programs`, never branches on `program_id`. This is a faithful implementation of an already-approved architectural model (ADR A-004), not a mitigation that closes the risk: **R-003 stays OPEN**, explicitly not accepted or closed at this Product Gate, and is flagged for `/arh-security-review` re-examination (`REQUIREMENTS.md` § Approvals, 2026-08-31).

### Risks accepted (carry-forward)

| Risk id | Severity | Rationale |
|---------|----------|-----------|
| R-04 (research #4 — persona-resolution N+1 across multiple RBAC checks in one request) | HIGH | accepted (D-05) — AUTH-02's per-role 300s cache bounds the worst case to N warm reads (<1ms each, AUTH-02-TC-12), not N Tier-3 queries; request-scoped memoization across checks in a single request is deferred to a post-launch optimization story if cache-hit-rate/latency monitoring shows it is actually needed (`REQUIREMENTS.md` § Scope, Out) |

### Conditions for GO (research_verdict GO-WITH-CONDITIONS)

| Cond | Condition (verbatim, `docs/research/AUTH-03.md` § Verdict & Conditions) | Addressed by |
|------|----------------------------------------------------------------------|--------------|
| C-1  | Clarify PersonaResolutionError handling: return HTTP 403 (fail-closed) + log at ERROR level; PersonaNotFoundError also 403, at normal INFO level | T-01 |
| C-2  | Specify exact log event payloads: four fixed allowlists per `AUTH-03-FR-2` | T-01 |
| C-3  | Document AC3 open-aggregate risk: implement as specified per A-004, R-003 stays OPEN, flagged for `/arh-security-review` | T-01 |
| C-4  | Specify outcome field semantics: literal `"authorized"` / `"denied"` strings, never boolean, never free text | T-01 |
| C-5  | Write unit tests before implementation (test-driven) | T-01, T-02, T-03, T-04, T-05, T-06 |

### Cross-Feature Dependency Notes

None. AUTH-03's only upstream dependencies — AUTH-01 (`session` contract) and AUTH-02 (`persona-resolver` contract) — are both complete and merged to `main` (PR #106, PR #110); neither is in-flight. The 16 downstream consumers (AUTH-04, OVW-01..04, PGD-01..06, SHP-02..06) are not yet planned; none of this story's tasks depend on their artefacts.

## 7. Test Strategy

All 28 test cases in `docs/test-cases/AUTH-03.json` are automatable (26 Must, 2 Should); `coverage_audit.uncovered == []`. Every TC appears in the table below — none is `manual: true`.

| Layer | Test path | TCs covered | Notes |
|---|---|---|---|
| Unit | `services/api/tests/unit/test_rbac.py` | TC-01..TC-16, TC-24, TC-28 | Pure logic, pass/deny branches for all five checks, the AC5/AC7 cascade call-order/short-circuit assertions (TC-10, TC-13..TC-16), the hardcoded governance tuple (TC-24), and program_visibility's silent-no-event contract (TC-28). `CurrentUser` fixture builder + stub persona resolver test double (configurable to return a persona or raise `PersonaResolutionError`/`PersonaNotFoundError`) + `_capture_logger` context manager attached to `app.core.rbac`, mirroring `tests/unit/test_persona_resolver.py`'s `_RecordCapturingHandler`/`_capture_logger` idiom. |
| Security | `services/api/tests/unit/test_rbac.py` (same file) | TC-17..TC-23, TC-27 | Fail-closed exception handling per-check (TC-17..19, C-1/D-01), the four PII-audit tests asserting each event's payload key set equals its `AUTH-03-FR-2` allowlist exactly (TC-20..23, pattern: AUTH-02's `test_persona_mapping_loaded_event_contains_no_pii_tc15`), and the structural R-003 assertion that `program_visibility` never accesses `current_user.programs` (TC-27, a `CurrentUser` test double whose `.programs` raises `AssertionError` if read). |
| Contract | `services/api/tests/unit/test_rbac.py` (same file) | TC-25 | `inspect.iscoroutinefunction` + `inspect.signature` over all five exported names, asserting the locked `rbac-checks` contract shape — same plain-pytest introspection pattern as `tests/unit/test_rollup_rebuild_contract.py`'s TC-09; no dedicated contract-testing framework. |
| Performance | `services/api/tests/perf/test_rbac_perf.py` | TC-26 | Plain `time.perf_counter()` p95 measurement across 100 consecutive calls per check with a stub resolver returning immediately, same convention as `tests/perf/test_persona_resolver_perf.py`; own small `_percentile` helper copied rather than imported (`test_range_pagination_perf.py`'s copy is the second instance, this is the third — still below the reusability-baseline "extract on the third repetition" threshold since these are two separate existing files, not yet a shared module). |

**Reliability NFR coverage** — `docs/test-cases/AUTH-03.json`'s `coverage_audit.non_functional_requirements` enumerates only performance, security, and observability; it does not separately enumerate `REQUIREMENTS.md`'s Reliability NFR ("fail-closed on every resolver error path — `PersonaResolutionError` and `PersonaNotFoundError` both deny; zero default-permit outcomes across all five checks"). That NFR is substantively covered by TC-17/TC-18/TC-19 (both exception types fail closed with 403, verified independently at `org_access` and `governance_visibility` call sites) — named explicitly here so the gap in the coverage-audit's enumeration does not silently propagate into implementation as an untested requirement.

**Runner-setup** — the Performance and Contract layers both run under the project's existing `pytest` runner (`docs/config/project-commands.yaml` `test`/`test_unit`: `cd services/api && uv run pytest`), already configured via `testpaths = ["tests"]` (`pyproject.toml:39`) and already exercising `tests/perf/` today (five existing perf files: `test_auth_jwks_perf.py`, `test_auth_retry_perf.py`, `test_persona_resolver_perf.py`, `test_range_pagination_perf.py`, `test_rollup_rebuild_perf.py`) and `tests/unit/test_rollup_rebuild_contract.py`'s plain-introspection contract-test pattern. Neither layer needs a dedicated benchmark tool (no k6/locust/pytest-benchmark) or a dedicated contract-testing framework — both are plain pytest test files under directories `pytest` already discovers, so no separate runner-install/config task is required beyond T-06 (writes `tests/perf/test_rbac_perf.py`) and T-05 (writes the contract test into the already-planned `tests/unit/test_rbac.py`, F-02).

Unit coverage threshold: 80% (no project-specific override in `harness.yaml`). No E2E layer — backend library with no standalone UI flow, exercised indirectly via each of the 16 downstream consumers' own E2E suites (`docs/stories/AUTH-03.md` § Test mapping). No manual/deferred layer — every TC executes at author time within its own task (T-01..T-06), none deferred to `/arh-validate-feature`.

## Plan validation

- Date: 2026-08-31T13:00:00Z
- Verdict: PASS
- Wiring:                PASS  (F-05 `app/main.py` modify entry covers the one real registration site — `create_app()` calling `rbac.configure(app.state.persona_resolver)`, D-06; `rbac.py` itself has no in-story consumer by explicit, documented scope — `REQUIREMENTS.md` § Scope, Out: "Route wiring — deferred to each consuming story")
- Docs:                  PASS  (no trigger fires — no new runnable surface, no new HTTP route, no new env var, no new service/port; `T-07` documents the five checks in `services/api/README.md` per `REQUIREMENTS.md` § Documentation requirements regardless)
- Runner-setup:          PASS  (Performance/TC-26 and Contract/TC-25 both run under the project's existing, already-configured `pytest` runner — five precedent perf files and one precedent contract-test file already exercise the same `tests/perf/`/`tests/unit/` discovery path with no dedicated tool; T-05/T-06 author the specs, no separate install/config task needed)
- Cross-section:         PASS  (verified programmatically: `predecessors` acyclic, every `file_plan` entry covered by ≥1 task, every task `files[]` id resolves, no two DAG-independent tasks share a file; every test-strategy TC type — unit/security/contract/performance — has a matched task)
- Config drift:          PASS  (no new runtime dependency, service, or port — confirmed against `services/api/pyproject.toml`; `fastapi.HTTPException` and `logging` are already-installed stdlib/existing deps)
- Decision-promotion:    PASS  (all six `DECISIONS.md` entries carry `blast:feature` or `blast:service` with `rev:mechanical` — none reach `blast:system`/`blast:data`/`rev:effectively-irreversible`, so `adr:—` is correct on every entry)
- Rounds:                1

### Plan validation rounds

| Round | Verdict | Failing dimensions | Action |
|-------|---------|---------------------|--------|
| 1     | PASS    | —                   | Continue to Phase 5 (tracker push, orchestrator-owned) |
