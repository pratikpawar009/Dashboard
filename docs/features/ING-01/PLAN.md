# ING-01 — Implementation Plan

Story: ING-01 — Ingest token minting + bearer auth. Research: GO-WITH-CONDITIONS, 76/100 (5 conditions). Design: n/a (no UI surface). Gate: APPROVE.

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log). ADR-0006 (`docs/adr/0006-ingest-token-format-and-scope-semantics.md`) is authoritative on token format, mint surface, scope semantics, and lifetime and is not re-opened here. This plan adds four implementation-surface decisions (D-01..D-04) that ADR-0006 leaves open — none reaches `blast:system`/`blast:data` or `rev:effectively-irreversible`, so **zero new ADRs** are produced by this plan (all four stay `adr:—`, DECISIONS.md only).

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan`. 6 new files, 2 modified files — see § 3 below for the module hierarchy narrative.

## 3. Module Hierarchy

No route ships in this story (`/ingest/*` wiring is ING-02's scope) — there is no navigation/routing map to draw; § below covers the library + script surface only.

```
services/api/
├── app/core/
│   └── ingest_auth.py                              [NEW — F-02]
│       - input:  program_id: str (caller-supplied, e.g. a future route's path param —
│                 resolved by FastAPI the same way any Depends()-chain parameter is;
│                 ING-02 owns the actual route wiring)
│                 credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False))
│                 session: AsyncSession = Depends(get_db)   [app.core.db]
│       - output: IngestToken (app.models.IngestToken row) on success;
│                 raises HTTPException(401) [reason: missing|unknown|revoked|expired] or
│                 HTTPException(403) [reason: scope] on denial
│       - public: async def get_ingest_token(program_id, credentials, session) -> IngestToken
│       - private: _check_program_scope(allowed_program_ids: list[str], program_id: str) -> bool
│                    (ADR-0006 §3 order: empty -> True; "*" in list -> True; membership -> True; else False)
│                  _log_ingest_token_auth_failed(*, token_id: str | None, reason: str, program_id: str) -> None
│                    (INFO level, event name "ingest_token_auth_failed", required fields exactly
│                    {token_id, reason, program_id, timestamp} — token_id is None when no row
│                    resolved, i.e. reason in {missing, unknown})
│       - never imports app/core/auth.py, never shares a route with get_current_user() (FR-6;
│         DECISIONS.md D-01)
│
├── scripts/
│   └── mint_ingest_token.py                        [NEW — F-01, creates services/api/scripts/]
│       - input:  argv — --label (required), --user-email (required),
│                 --program-ids (optional; comma-separated ids or the literal "*"; omitted/empty
│                 -> allowed_program_ids=[], DECISIONS.md D-04)
│       - output: on success — one stdout line matching ^hrn_pat_[0-9a-f]{64}$, exit 0, one
│                 committed ingest_tokens row (token_hash=sha256(raw).hexdigest(), label,
│                 user_email, allowed_program_ids, expires_at=null, revoked_at=null)
│                 on failure (bad/missing argparse arg, or a DB/commit error) — non-zero exit,
│                 nothing on stdout, no row committed (DECISIONS.md D-02)
│       - public: invoked as `uv run python scripts/mint_ingest_token.py ...` from services/api/
│                 (editable-installed `app` package resolves regardless of script cwd — the
│                 project's [tool.hatch.build.targets.wheel] packages=["app"] + `uv sync` already
│                 make `import app.core.db` work from any script location in this venv, the same
│                 way `uv run python -c "import app.main"` already does in preflight)
│       - imports app.core.db.SessionLocal directly (not get_db()) and app.models.IngestToken;
│         never imports app.core.ingest_auth (mint and verify stay independent, ADR-0006 §2/§3)
│
tests/
├── unit/
│   ├── test_mint_ingest_token.py                   [NEW — F-03] TC-01,02,03,04,05,23
│   ├── test_ingest_token_auth.py                    [NEW — F-04] TC-06..20,24
│   └── test_ingest_token_isolation.py               [NEW — F-05] TC-21
└── perf/
    └── test_ingest_token_auth_perf.py                [NEW — F-06] TC-22
```

`app/core/ingest_auth.py` has no barrel/registration site to update: `app/core/__init__.py` is empty (confirmed — no re-export barrel exists for any `app.core.*` module, including the precedent `rbac.py`), and no route consumes `get_ingest_token` in this story (ING-02's job). The **wiring** obligation this story carries is narrower — script executable, dependency importable and exported from its own module — both satisfied by F-01/F-02 existing at the paths above with no further registration step.

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md`.

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks`. Execution order derives from `predecessors`; parallelism derives from the DAG. 8 tasks: T-01/T-02 run first (parallel, file-disjoint); T-03..T-06 each depend on exactly one of T-01/T-02; T-07/T-08 (documentation) depend on both T-01 and T-02.

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/ING-01.md` § Risk Register. All 5 HIGH/CRITICAL risks are addressed by tasks below — none are accepted/carried forward.

### Risks addressed by tasks

| Risk id | Severity | Description (short) | Addressed by |
|---------|----------|----------------------|---------------|
| R-01 | CRITICAL | Minting surface ambiguous | T-02 (implements ADR-0006 §2's settled surface: stdlib argparse, standalone script, local-shell authority) |
| R-02 | HIGH | Two auth paths must coexist without interference | T-01 (structural isolation, no shared code/route), T-05 (TC-21 dual-dependency proof) |
| R-03 | HIGH | Token representation in logs | T-01 (`_log_ingest_token_auth_failed` fixed field allowlist), T-04 (TC-18/19/20 assert the exact key set + denial-only emission) |
| R-04 | HIGH | Scope validation timing (dependency vs. route handler) | T-01 (DECISIONS.md D-01 — check runs inside `get_ingest_token`), T-04 (TC-17/TC-24 assert `program_id` is caller-supplied, never read off the token row) |
| R-05 | HIGH | Wildcard program scope representation | T-01 (implements ADR-0006 §3's exact check order), T-04 (TC-06/07/08/09/24) |

MEDIUM/LOW risks (R-06..R-10 — hash-lookup latency, CLI framework/dependency footprint, logging-allowlist inconsistency, token rotation strategy, prefix collision) inherit their mitigation from `docs/research/ING-01.md` and need no re-statement here; R-06 through R-08 are additionally covered by T-06/T-01/T-04 respectively as a byproduct of the HIGH-risk work above. No risk-table row is accepted/carried-forward in this story — `pending_carry_forward[]` stays empty.

### Conditions for GO (research_verdict GO-WITH-CONDITIONS)

| Cond | Condition (verbatim, condensed) | Addressed by |
|------|----------------------------------|---------------|
| C-1 | Minting surface decision (CLI framework, entry point, authority model, default TTL) | T-02 |
| C-2 | Wildcard program scope representation + exact check order + test cases for both array-of-ids and wildcard | T-01, T-04 |
| C-3 | Logging event field allowlist (exact required/optional fields, validated at log time) | T-01, T-04 |
| C-4 | Dependency isolation (route organization, DI shape, unit test proving non-interference) | T-01, T-05 |
| C-5 | Test surface (unit coverage for mint output/storage, verification valid/revoked/expired/scope) | T-03, T-04, T-05, T-06 |

### Cross-Feature Dependency Notes

None — BED-01 (upstream, `ingest_tokens` table) and AUTH-01 (upstream, `get_current_user`) are both complete and merged. ING-02/03/07 (downstream consumers of the `ingest-token-auth` contract) are not in-flight concurrently with this story.

## 7. Test Strategy

| Layer | Test path | TCs covered | Notes |
|-------|-----------|--------------|-------|
| Integration | `services/api/tests/unit/test_mint_ingest_token.py` | TC-01, TC-02, TC-03, TC-04 | Real disposable Postgres via `migrated_db`+`test_session` (`tests/conftest.py`); mint script invoked as a subprocess per each TC's own `steps`, output/exit-code/row-count asserted |
| Security | `services/api/tests/unit/test_mint_ingest_token.py` | TC-05, TC-23 | Raw-token-never-persisted-or-logged sweep (TC-05); two-mint CSPRNG-distinctness check (TC-23) |
| Integration | `services/api/tests/unit/test_ingest_token_auth.py` | TC-06, TC-07, TC-08, TC-09, TC-10, TC-11, TC-12, TC-13, TC-14, TC-15, TC-16, TC-17, TC-24 | Direct `await get_ingest_token(program_id=..., credentials=..., session=test_session)` calls against `migrated_db`+`test_session` — real DB, no mocks at the integration boundary (PRD Addressing Research Conditions, C-5) |
| Security | `services/api/tests/unit/test_ingest_token_auth.py` | TC-18, TC-19, TC-20 | `ingest_token_auth_failed` field-allowlist-exact-match + denial-only emission, captured-logger idiom mirroring `tests/unit/test_persona_resolver.py::test_persona_mapping_loaded_event_contains_no_pii_tc15` |
| Integration | `services/api/tests/unit/test_ingest_token_isolation.py` | TC-21 | Throwaway app + one mock dual-dependency route, driven via `httpx`/`conftest.py`'s `async_client_for` (DECISIONS.md D-03) |
| Performance | `services/api/tests/perf/test_ingest_token_auth_perf.py` | TC-22 | p95 < 10ms over 100 iterations; existing `tests/perf/` pytest-only runner (no new install — `test_rbac_perf.py`/`test_programs_perf.py` precedent) |

24/24 TCs covered (`docs/test-cases/ING-01.json` `coverage_audit.uncovered = []`); none flagged `manual: true`. No E2E — no UI surface (`design: n/a`, backend-only story). No Contract-type TC — the `ingest-token-auth` shared contract is authored directly in `docs/requirements/auth.md#ingest-token-auth` (§ 9 of `DATA-DESIGN.md`), not exercised through a separate contract-test runner.

### Coverage gates

Unit/integration coverage threshold: 80% (no project-specific override found in `harness.yaml`; falling back to the documented default). E2E gate: N/A, no E2E suite in this story.

### Runner setup

N/A — no `e2e`/`performance`/`contract`-runner installation is required. TC-22 (`performance`) runs on the already-configured `pytest` + `tests/perf/` infrastructure (6 precedent files, no k6/locust/separate runner in this codebase); T-06 only needs to add one new test file, not install or configure a runner.

### Config drift

Confirmed N/A. No new runtime dependency (`services/api/scripts/mint_ingest_token.py` uses only stdlib `argparse`/`hashlib`/`secrets`, ADR-0006 §2) — no `docs/config/project-commands.yaml` `preflight:` update needed. No new service directory, no new `docker-compose.yml` entry, no new port — no `docs/config/stack-smoke.md` update needed.

## Plan validation

- Date: 2026-08-31T19:30:00Z
- Verdict: PASS
- Wiring: PASS (F-01/scripts/mint_ingest_token.py is a self-contained, subprocess-invoked entry point — no registration site exists for a standalone script. F-02/app/core/ingest_auth.py has no barrel to update — `app/core/__init__.py` is empty, confirmed, matching the existing `rbac.py`/`auth.py` precedent of no re-export barrel — and this story deliberately ships no route that consumes `get_ingest_token` (PRD § Rollout plan: "no route calls get_ingest_token() until ING-02 ships"); the consumer is not unknown, it is out of scope by design, so no `[NEEDS CLARIFICATION]` gap applies)
- Docs: PASS (T1 fires — new CLI runnable surface `scripts/mint_ingest_token.py` — addressed by T-08, a `docs(readme)` task on `services/api/README.md`. Root `README.md` is the service-nested-README exception: its own `## API` section documents only shipped HTTP routes, none of which this story adds, and the existing "Rollup rebuild" section already establishes `services/api/README.md` as this repo's primary doc for a service-internal, routeless library — the same shape as this story's deliverable. T2/T3/T4 do not fire: no HTTP route, no new env var, no new service/port)
- Runner-setup: PASS (TC-22 is `type: performance`; `tests/perf/` already exists, pytest-only, 6 precedent files, no k6/locust/separate runner in this codebase — T-06 adds one test file to already-configured infrastructure, not a new runner)
- Cross-section: PASS (DAG acyclic, all `predecessors` resolve; all 3 TC types — integration/security/performance — have a backing task; all 8 `file_plan` entries covered by exactly one task's `files[]`; every task `files[]` id resolves in `file_plan`; no two DAG-independent tasks share a file — checked exhaustively across all task pairs)
- Config drift: PASS (no new runtime dependency, service, or port — confirmed explicitly above; no `preflight:`/`stack-smoke.md` task needed)
- Decision-promotion: PASS (`DECISIONS.md` D-01..D-04 are all `blast:feature`/`blast:service` + `rev:mechanical` — none reaches `blast:system`/`blast:data`/`rev:effectively-irreversible`, so none requires promotion; all correctly carry `adr:—`)
- Rounds: 1

### Plan validation rounds

| Round | Verdict | Failing dimensions | Action |
|-------|---------|---------------------|--------|
| 1 | PASS | — | Continue to /arh-implement |
