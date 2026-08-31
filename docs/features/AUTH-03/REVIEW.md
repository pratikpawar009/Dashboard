# Code Review — AUTH-03 (working tree, gate round 1)

- Date: 2026-08-31T14:00:00Z
- Mode: story (GATE MODE — report-only, `/arh-implement` Validate ∥ Review gate)
- Files reviewed: 5 (`services/api/app/core/rbac.py`, `services/api/tests/unit/test_rbac.py`, `services/api/tests/perf/test_rbac_perf.py`, `services/api/app/main.py`, `services/api/README.md`)
- Verdict: **PASS**

## Executive summary

AUTH-03 adds `app/core/rbac.py` — five async, pure-function RBAC checks — plus a 37-test unit/security/contract suite, a 5-test perf suite, a one-call `main.py` wiring edit, and an insertion-only README section. The diff matches `tasks.json`'s `file_plan` exactly (F-01..F-05, no extra files), matches PLAN.md §3's module hierarchy line-for-line (function names, private-helper split, docstring content), and honors every one of DECISIONS.md's D-01..D-06 as binding, not as a design suggestion. `PersonaNotFoundError`/`PersonaResolutionError` except-clause ordering is correct (subclass caught first) and TC-18 would genuinely fail if it were reversed. FR-4's two cascade orders are proven with real call-order spies (TC-10, TC-15, TC-16), not outcome-only assertions, so they'd catch a regression even though `program_visibility` never denies today under D-03. Module-global test isolation (D-06) is handled correctly in both new test files via autouse reset fixtures and `monkeypatch`. README is accurate against the code field-for-field. `impl_evidence` in `state.json` already shows a clean full-suite run (377 passed) plus lint/typecheck/compile PASS.

🟢 No CRITICAL or HIGH findings — nothing blocks this gate round.
⚠️ Two LOW observations (below), one already tracked as AF-01.
🛑 None.

## Findings summary

| Severity | Count | Category distribution |
|----------|-------|------------------------|
| CRITICAL | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 0 | — |
| LOW | 2 | integration (1), testability (1) |

ADR violations: 0. Scope-creep: 0. Contract-drift: 0.

## Detailed findings

### LOW

#### F-1 — integration: `persona` field presence is outcome-dependent on two events (AF-01, already tracked)
- Category: Integration points
- Path: `services/api/app/core/rbac.py:306-326` (`_EVENT_OPTIONAL_FIELDS`)
- Source: `docs/features/AUTH-03/FLAGS.md` AF-01 (status: open); `DECISIONS.md` D-02
- Description: `rbac_check_org_access`/`rbac_check_governance_visibility` carry `persona` when resolution succeeded and omit the key entirely on the two resolver-failure denial branches (`_resolve_persona_or_deny`'s `except` clauses). This is within D-02's intent — an allowlist is an upper bound, and TC-17/TC-18/TC-19 only assert level/outcome on that path, not the full key set — so no locked assertion is breached, matching the orchestrator's existing adjudication. A schema-on-read log consumer (e.g. the AUTH-04 success-signal check in `REQUIREMENTS.md` § Rollout plan) does need to treat `persona` as optional rather than assuming a constant key set per event name. README documents the optional-field rule (`services/api/README.md`, "The four log events" section), so this is not an undocumented gap.
- Suggested fix: no code change required for this gate. Triage AF-01 as planned — if a downstream consumer wants a constant key set, switch to `persona: None` on the failure branches rather than omitting the key; either satisfies the current tests.

#### F-2 — testability: module-global `_persona_resolver` (D-06) is a single process-wide write per `create_app()` call
- Category: Testability
- Path: `services/api/app/core/rbac.py:63,70-82`; `services/api/app/main.py:45-50`
- Source: `DECISIONS.md` D-06 (the accepted trade-off vs. D-07); `DATA-DESIGN.md` §7
- Description: Within this diff's own test files (`test_rbac.py`, `test_rbac_perf.py`) isolation is correct — both carry autouse `_reset_rbac_state` fixtures and the `program_visibility` monkeypatch self-reverts. The residual risk is downstream: D-06 explicitly notes `rbac.py`'s own unit tests avoid the multi-instance problem by never building a FastAPI app; a future downstream story's integration test suite that constructs more than one `create_app()` instance concurrently in the same process (e.g. two `TestClient`s built from different `Settings`) would have the *last* `configure()` call win for both, since `_persona_resolver` is process-lifetime, not per-app. This is an accepted, already-documented consequence of D-06, not a defect introduced by this diff.
- Suggested fix: no action needed in AUTH-03. Worth a one-line note in a future downstream story's test setup (or a shared `conftest.py` fixture that calls `rbac.configure()` per-test) once a consumer's integration suite actually needs two concurrent apps.

## Adjudicated non-findings (checked, not raised)

- **403 vs. `security-baseline.md`'s 404-for-foreign/nonexistent rule**: correctly not violated. All five checks perform zero resource lookups — `individual_usage_visibility` denies identically whether `target_user_id` exists or not, since the check only compares it against `current_user.user_id`/a resolved persona, never queries a datastore. There is nothing here for a 403 to confirm the existence of. The 404 rule binds a downstream `_load_owned`-style consumer that loads a real row after this check passes; that obligation sits with the 16 consuming stories, not AUTH-03.
- **`_log_event`'s `raise AssertionError` on a bad field set**: checked, fine. It uses an explicit `raise AssertionError(...)`, not a bare `assert`, so `python -O`/`PYTHONOPTIMIZE` (which strips only `assert` statements) does not disable it — and neither is used anywhere in this repo's run commands (`Dockerfile:15`, `README.md`'s `uv run uvicorn` invocations are both flag-free). The condition it guards is a call-site invariant fully controlled by four hardcoded call sites inside this same module, never influenced by request input, so it cannot fire from attacker-controlled data. If it ever did fire (a future edit breaking the allowlist), it propagates uncaught to FastAPI's catch-all `Exception` → 500 handler (`app/core/errors.py`, fastapi-patterns), which denies the request and leaks no internal detail — fail-closed, not a silent default-permit.
- **D-01 exception ordering**: verified correct. `PersonaNotFoundError(PersonaResolutionError)` (`persona_resolver.py:78`) is caught in the `except PersonaNotFoundError:` clause before `except PersonaResolutionError:` in `_resolve_persona_or_deny` (`rbac.py:286-303`). Confirmed a reversed order would make TC-18 fail (it asserts `levelno == logging.INFO` for a `PersonaNotFoundError` raise; a reversed order would route it through the ERROR branch instead) — the test genuinely guards this, not just documents it.
- **FR-4 cascade order, genuinely proven**: TC-10 (`member_in_program_visibility`) and TC-15/TC-16 (`governance_visibility`) all use `_ProgramVisibilitySpy`/shared `order` lists and assert on `spy.calls`/`order`, not just the end-to-end HTTPException outcome — so all three would catch an order regression even under D-03's current program_visibility-never-denies behavior.
- **Scope discipline**: `main.py` diff is exactly one import + one call (+ explanatory comment); `README.md` diff is 66/0 insertion-only. Both match `tasks.json` F-05/F-04 exactly, no unrelated hunks.
- **Docs accuracy**: every field name, event name, exception name, and signature in the new README section matches `rbac.py` verbatim (cross-checked table-by-table).
- **R-003 (`program_visibility` open-aggregate)**: correctly still OPEN per D-03 — `program_visibility` never reads `current_user.programs` (TC-27, structural) and never branches on `program_id` (TC-04), matching AC3 exactly. Not re-raised as a new finding; already flagged for `/arh-security-review`.

## What went well

- Locked `rbac-checks` contract enforced with a genuine tripwire (TC-25, full signature/param-order/count introspection), not a partial check.
- PII-audit tests (TC-20..23) assert the exact payload key set via the real `JSONFormatter`, matching AUTH-02's precedent pattern.
- Perf suite times the real logging cost (production-configured handler, not a stubbed-out logger) and states plainly it won't loosen the budget to pass.
- Module docstring and inline comments consistently point back to the specific decision (D-01..D-06) or FR driving each non-obvious choice — easy to audit against DECISIONS.md.

## Recommendation

**PASS.** No CRITICAL or HIGH findings; both LOW observations are informational (one already tracked as AF-01, the other a downstream-consumer note). Nothing in this diff needs a fix round.
