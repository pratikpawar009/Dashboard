# SHP-02 — Evidence pass escalation (BLOCKED after 3 rounds)

`unit_tests` did not reach a clean exit code across 3 internal fix-loop rounds. See
`docs/features/SHP-02/EVIDENCE-ROUNDS.md` for the full round table and cross-run causality
matrix. This document is the round-3 escalation required by the `evidence-pass` skill.

## What is genuinely SHP-02's responsibility — all green

- `services/api/tests/unit/test_personal_usage.py` (5 tests) — green in every run.
- `services/api/tests/perf/test_personal_usage_perf.py` (3 tests) — green in every run.
- `services/api/tests/test_migrations.py` (12 tests) — green in every run.
- `services/api/tests/test_models.py` (46 tests, BED-01-owned) — **one real regression, fixed
  in Round 1**: T-02's authorized new indexes (DECISIONS.md D-01/D-05) were not reflected in the
  stale fixture `tests/fixtures/prd_8_4_schema.json`; corrected with a 2-line, minimal-diff edit.
  46/46 green in every run since.

## What is blocking — not SHP-02's responsibility

Six perf-budget test files, none in SHP-02's `file_plan` (`tasks.json`), none touching
`app/schemas/personal_usage.py`, `app/services/personal_usage.py`, or `app/api/personal_usage.py`:

- `tests/perf/test_auth_jwks_perf.py` (AUTH-01)
- `tests/perf/test_ingest_token_auth_perf.py` (AUTH-01/ING-01)
- `tests/perf/test_overview_perf.py` (PGD-01)
- `tests/perf/test_persona_resolver_perf.py` (AUTH-02)
- `tests/perf/test_programs_perf.py` (AUTH-04)
- `tests/perf/test_rollup_rebuild_perf.py` (BED-04)

**Root cause**: `<system load from ~10 concurrent Claude Code agent sessions on this shared
machine (uptime load averages 141–147 against a machine sized for far fewer)> produces
<intermittent, non-reproducible perf-budget test failures across a rotating subset of the six
files above> because <each test asserts a real wall-clock p95/p99/single-call latency budget as
tight as ≤1ms–≤300ms against a live Postgres, and CPU scheduling delays under this level of
oversubscription push actual latencies over budget non-deterministically, independent of which
code is under test>.`

**Proof, not assertion** (full detail in EVIDENCE-ROUNDS.md):
- Two full-suite runs with SHP-02's tracked+untracked changes completely removed (`git stash
  push -u` / `pop`) reproduced perf failures from the *same pool* of six files.
- No test shows the "always fails with SHP-02 present, never without" signature a genuine
  regression would produce — `test_rollup_rebuild_perf` and `test_auth_jwks_perf` failed in
  nearly every run regardless of whether SHP-02's code was present at all.
- The specific failing subset changed on every one of 5 total runs of materially the same code,
  which is the signature of environmental flakiness, not a deterministic code defect.

## Why this was not "fixed" in the loop

- No file in the 6 failing perf-test files is in SHP-02's `tasks.json` `file_plan` — editing them
  would violate `surgical-changes` (touch only what the task requires) and `pattern-consistency`.
- Loosening any of the asserted perf budgets is explicitly forbidden by the evidence-pass
  anti-suppression rules ("NEVER loosen a perf budget").
- Reducing concurrent load on the shared machine (the actual root cause) is outside this agent's
  authority and outside SHP-02's scope entirely — it requires either running the packet on a
  quieter machine/window, or a human/team decision on perf-test isolation (e.g., dedicated CI
  runner, `pytest-rerunfailures` policy for wall-clock perf assertions, or per-worker resource
  reservation). None of those are code changes this agent can make inside one story's file plan.

## Recommendation

1. Treat `docs/features/SHP-02` `impl_evidence.checks.unit_tests` as the authoritative record:
   SHP-02's own 20 tests + the previously-blocking `test_models.py` regression are proven green;
   the residual FAIL is a documented, cross-run-verified pre-existing/environmental condition.
2. Re-run `cd services/api && uv run pytest` once machine load is materially lower (e.g., no other
   concurrent agent sessions) to obtain a clean exit-0 confirmation, or
3. Raise a team-level decision (new AF, or a promoted ADR/DECISIONS entry) on how this repo wants
   wall-clock perf-budget tests to behave under concurrent-agent load — this affects every future
   story's evidence pass, not just SHP-02's, and is a sibling condition to the already-accepted
   `FLAGS.md` AF-03 (shared-DB contention under concurrent pytest workers).

This is a genuine BLOCKED handoff per the `evidence-pass` skill's round-3 escalation path — not a
disguised PASS. A human should decide whether to accept the above evidence as sufficient to
proceed past this dimension, or wait for a clean re-run.
