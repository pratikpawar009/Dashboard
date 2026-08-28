# Agent flags — AUTH-02

Raised by implementation workers during `/arh-implement`. Triage with `/arh-human-review AUTH-02`.

### AF-01: D-09's "uv.lock unchanged" premise does not hold literally

- **status**: triaged
- **disposition**: accepted — reword D-09 to "no new package or version enters the resolved graph". Documentation only; the lockfile diff is correct and must not be reverted.
- **triaged_by**: user, 2026-08-28 (inline triage during /arh-implement Step 1 flag gate)
- **kind**: inconsistency
- **task**: T-01
- **source**: `services/api/uv.lock`, `docs/features/AUTH-02/DECISIONS.md` § D-09

D-09 records "uv sync to confirm uv.lock unchanged" as its verification step. Adding the direct
`pyyaml>=6.0` pin produces a 2-line `uv.lock` diff: `pyyaml` is added to the `api` workspace
member's own `dependencies` / `requires-dist` mirror, which tracks `pyproject.toml` and is separate
from the resolved-package table.

D-09's **substantive** claim holds — no new `[[package]]` entry appeared, and `pyyaml` stays
resolved at exactly `6.0.3`, the same wheel `uvicorn[standard]` was already pulling. Only the
literal "unchanged" wording is wrong.

The worker did not revert the lockfile: reverting it while `pyproject.toml` declares `pyyaml`
directly would desync the two and make `uv lock --check` / `uv sync --locked` fail — a worse
outcome than an accurate 2-line diff.

**Suggested resolution**: amend D-09's wording to "no new package or version enters the resolved
graph" rather than "uv.lock unchanged". Documentation-only; no code impact.

### AF-02: Tier-3 tests need a TEST_DATABASE_URL override in this environment

- **status**: triaged
- **disposition**: accepted — pre-existing environment drift (BED-01 `AF-06-carry`), not introduced by AUTH-02. Runners need `TEST_DATABASE_URL` or a fixed local Postgres.
- **triaged_by**: user, 2026-08-28 (inline triage during /arh-implement Step 1 flag gate)
- **kind**: environment
- **task**: T-07, T-08
- **source**: `services/api/tests/conftest.py`, local Postgres on `localhost:5432`

Both live-DB test cases — `AUTH-02-TC-03`/`TC-14` (T-07) and `AUTH-02-TC-13` (T-08) — required
`TEST_DATABASE_URL` to be pointed at a disposable Postgres before they would run. The machine's
`localhost:5432` is a non-Docker local Postgres whose credentials do not match
`Settings.database_url`'s `postgres`/`postgres` default.

This is **pre-existing environment drift, not introduced by AUTH-02** — it is the same condition
BED-01 already recorded as `AF-06-carry` in `tests/perf/test_range_pagination_perf.py`'s docstring.

Recorded here because it has a live consequence for the gate: anyone re-running these suites
verbatim, including Step 2's `validation-agent`, needs the same override or a fixed local Postgres,
or the Tier-3 cases will fail for environmental reasons rather than code ones. Neither worker left
a container or tracked file behind.

### AF-03: `tests/perf/` is load-sensitive; AUTH-02 adds one more flaky case

- **status**: triaged
- **disposition**: accepted — repo-wide `tests/perf/` p99-over-100 fragility affecting AUTH-01 and BED-03 equally. Medians are far under budget in every configuration. Whether `tests/perf/` belongs in the default gating run is a project-commands decision spanning three stories.
- **triaged_by**: user, 2026-08-28 (inline triage during /arh-implement Step 1 flag gate)
- **kind**: test-reliability
- **task**: evidence pass
- **source**: `services/api/tests/perf/`

Across 6 consecutive full-suite runs, three different perf tests failed at least once, and no
single run failed the same set:

| Test | Owner | Failures |
|---|---|---|
| `test_auth_jwks_perf.py::test_jwt_validation_latency_cold_then_warm_within_budget` | AUTH-01 | 1/6 |
| `test_rollup_rebuild_perf.py::test_rebuild_program_rollups_completes_within_budget_for_5000_events` | BED-03 | 2/6 |
| `test_persona_resolver_perf.py::test_warm_cache_hit_latency_baseline_p99_under_1ms` | **AUTH-02** | 1/6 |

Every one of them passes in isolation — AUTH-02's warm-cache test measures p99 = 0.183ms alone
against a 1ms budget, a 5x margin. They fail only when run after the rest of the suite, or under
concurrent machine load (the first observed failure pair occurred while `pnpm install` ran
alongside).

**Root cause is statistical, not a code defect.** `REQUIREMENTS.md` specifies "100 iterations,
assert p99 < 1ms", and a nearest-rank p99 over 100 samples is effectively the 99th-slowest sample —
one GC pause or scheduler preemption in a hundred iterations breaches it. AUTH-01 and BED-03's perf
tests share the same construction, so this is a **pre-existing repo-wide pattern**, not something
AUTH-02 introduced.

AUTH-02's test was left implementing the requirement literally rather than being quietly widened to
p95 or given a longer budget — changing it would deviate from `REQUIREMENTS.md` and diverge from how
the other two perf suites are already written.

**Measured during the Step 2 fix loop** — the budget is not actually marginal in any realistic
deployment. Warm-hit p99 over 100 iterations, after a 20-call warm-up, with FR-5's per-call log fully
active:

| stdout target | p50 | p95 | p99 | verdict |
|---|---|---|---|---|
| terminal (tty-attached) | — | — | **1.1175ms** | breaches |
| file (production-like) | 0.015ms | 0.019–0.045ms | 0.022–0.174ms | 6–50x under |
| `/dev/null` | 0.013ms | 0.013–0.050ms | 0.014–0.103ms | 10–70x under |

**Correction from gate round 3**: the trigger is not tty-only. `validation-agent` observed a breach
(p99 = 1.4965ms) with stdout redirected to a **file**, while running the 14-test `tests/perf` batch
together; an isolated re-run went 3/3 clean and a second full `tests/perf` run went 14/14 clean. So
batch contention alone can push the 99th-of-100 sample over, independent of the stdout target. The
measured medians remain far under budget in every configuration, so the conclusion is unchanged --
this is the p99-over-100 statistic catching a pause, not a latency problem -- but the earlier
"terminal-only" framing was too narrow.

A terminal-attached stdout is the *worst* configuration, and the service never has one in production — the `Dockerfile` runs uvicorn with stdout piped to the platform's log collector.
So the resolver comfortably meets the NFR, and the occasional in-suite failure is the p99-over-100
statistic catching a GC pause, not a real latency problem.

**Suggested resolution** (repo-wide, not AUTH-02-local): decide once whether `tests/perf/` belongs in
the default `pytest tests/` run at all, or behind a marker (`-m perf`) excluded from the gating suite
and run deliberately. That is a project-commands decision affecting three stories, so it is recorded
here rather than fixed inline.

### AF-04: design_check dimension is N/A — no tool wired

- **status**: triaged
- **disposition**: accepted N/A — confirmed by the user 2026-08-28. Backend-only story, no UI surface, and no a11y/perf tool is wired in `project-commands.yaml`.
- **triaged_by**: user, 2026-08-28 (inline triage during /arh-implement Step 1 flag gate)
- **kind**: evidence-na
- **task**: evidence pass
- **source**: `docs/config/project-commands.yaml`

`design_check` is deliberately empty in `docs/config/project-commands.yaml` — no accessibility,
console-error-scan, or perf tool has been chosen or installed for this project yet. AUTH-02 is a
backend-only story (`design: n/a` in state, zero `apps/web` files in the F-01..F-11 file plan), so
there is no UI surface for such a tool to check even if one were wired.

Recorded as accepted-N/A. Please confirm.
