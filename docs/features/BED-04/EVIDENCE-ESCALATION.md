# BED-04 — Evidence pass escalation

Rounds run: 1 (early-exit — see `EVIDENCE-ROUNDS.md` "Early escalation"). Not a code defect: **BED-04's entire actual scope (`services/api`) is green on every dimension.** The block is a pre-existing, repo-wide `apps/web` pnpm environment policy gate, unrelated to this story, that this agent has no authority to resolve unilaterally.

## What is green (BED-04's real surface, `services/api`)

| Dimension | Command | Result | Evidence |
|---|---|---|---|
| typecheck | `uv run mypy .` | PASS — 0 errors, 91 source files | `evidence/typecheck.log` |
| unit_tests | `uv run pytest` | PASS — 430 passed, 0 failed, 38.95s (full suite, not just BED-04's 2 files) | `evidence/unit-tests.log` |
| lint | `uv run ruff check .` | PASS — "All checks passed!" | `evidence/lint.log` |
| runtime | `uvicorn app.main:app` (port 8010, dev Postgres on 5432) | PASS — `/health` → 200, boot log clean (no Error\|Exception\|Panic\|FATAL) | `evidence/runtime-api.log` |
| — | smoke-imports (`app.main`, `authlib`, `respx`, `yaml`, `from app.services import FreshnessAccessor`) | PASS — all 5 | `evidence/preflight-smoke.log` |
| format (not an official dimension, checked anyway) | `uv run ruff format --check .` | BED-04's own new content (`README.md` § Freshness accessor) fixed in-round; 3 pre-existing, unrelated files/hunks left untouched per `surgical-changes` (see Carry-forward) | `evidence/format.log` |

## What is blocked (`apps/web`, not touched by BED-04)

| Dimension | Command | Result | Evidence |
|---|---|---|---|
| typecheck (web half) | `pnpm -C apps/web exec tsc --noEmit` | FAIL — never reaches `tsc`, fails during pnpm's own dependency check | `evidence/typecheck-web.log` |
| unit_tests (web half) | `pnpm -C apps/web test` | FAIL — same | `evidence/unit-tests-web.log` |
| lint (web half) | `pnpm -C apps/web exec eslint .` | FAIL — same | `evidence/lint-web.log` |
| runtime (web stack) | `pnpm -C apps/web dev --port 3010` | FAIL — `next dev` never starts | `evidence/runtime-web.log` |
| compile | `pnpm -C apps/web build` | FAIL — same | `evidence/compile.log` |
| design_check | (empty in `project-commands.yaml`) | N/A — see AF-04 below | — |

## Root cause

`<pnpm 11.20.0's pre-command dependency-status check (runDepsStatusCheck)> produces <every apps/web pnpm invocation failing with ERR_PNPM_IGNORED_BUILDS> because <unrs-resolver@1.12.2's postinstall build script is neither approved nor denied anywhere in this repo (no .npmrc / pnpm-workspace.yaml / package.json policy exists), and this pnpm version refuses to proceed with install/exec/dev/build/test until a human runs `pnpm approve-builds` (or explicitly denies it)>`.

Confirmed pre-existing and unrelated to BED-04:
- `git diff main --stat -- apps/web/package.json apps/web/pnpm-lock.yaml` is empty — zero changes to any apps/web manifest on this branch.
- `unrs-resolver@1.12.2` has been present in `pnpm-lock.yaml` since the initial commit (`b4cad8c`).
- Every previously merged feature's `impl_evidence` record (AUTH-01, AUTH-02, AUTH-03, AUTH-04, BED-01, BED-02, BED-03, ING-01) shows `typecheck`/`unit_tests`/`lint`/`runtime`/`compile` all `PASS` — this gate did not exist/trigger during any of those runs. pnpm itself reports `Update available! 11.20.0 → 11.25.0`, consistent with a recent local pnpm/corepack update introducing or newly enforcing this check — machine/tooling drift, not anything any story's code did.
- I attempted to check for a safe, non-destructive way to inspect this policy (`pnpm help install`, `pnpm approve-builds --help`) — the environment's own permission classifier declined the action, correctly treating "decide whether to trust an unreviewed dependency's install script" as outside an autonomous agent's authority.
- Side effect noted and cleaned up each time: attempting any of the above pnpm commands causes pnpm to auto-write a stub `apps/web/pnpm-workspace.yaml` (`allowBuilds: { unrs-resolver: set this to true or false }`); removed after each attempt so it doesn't leak into the diff — do not commit it as-is if a human fills it in, review the value chosen first.

## Fix required (one-time, repo-wide, NOT a BED-04 code change)

A human runs, once, from `apps/web/`:
```
pnpm approve-builds        # interactively approve or deny unrs-resolver's postinstall script
```
then re-invokes the evidence pass (or just the 5 blocked `apps/web` commands) to confirm green. This resolves the gate for every future story's evidence pass, not just BED-04.

## Carry-forward (pre-existing, unrelated — not fixed inline per `surgical-changes`)

- `services/api/README.md:26` — one `ruff format` violation in the pre-existing `## Data access` section's Python code fence (`engine = create_async_engine(...)`), predates BED-04, not part of T-05's diff.
- `services/api/app/api/programs.py:121` — one `ruff format` violation (long `select(...)` line), unrelated file, not touched by any BED-04 task.
- `services/api/tests/unit/test_programs.py` — four `ruff format` violations, unrelated file, not touched by any BED-04 task.

## Recommendation

Accept BED-04's evidence packet on its actual merits: `services/api` (the entirety of this story's `file_plan`) is fully green across typecheck, unit tests (full 430-test suite), lint, and runtime. Triage AF-03 (this environment gate) and AF-04 (`design_check` N/A) at `/arh-human-review`; AF-03's fix is orthogonal to BED-04 and should not need to re-run this story's implementation once resolved.

---

## Orchestrator correction, RETRACTED (`/arh-implement` Step 1)

An earlier correction was appended here claiming this escalation was wrong about `ruff format` and
`services/api/README.md`. **That correction was itself wrong and is fully retracted.** It has been
removed rather than left standing, since a false claim in a governance record is worse than none.

What the retracted text asserted, and why it was wrong:

- It claimed `ruff format` processes `.py`/`.pyi`/`.ipynb` only and never reads Markdown. **False.**
  `ruff 0.16.4` formats Python code fences inside `.md` files. Verified directly:
  `uv run ruff format --check README.md` alone reproduces a finding at `README.md:26:54`, inside the
  pre-existing `## Data access` section's ```python fence.
- It therefore voided this escalation's `format` row and its `README.md:26` carry-forward entry.
  **Both were correct as originally written and are reinstated.**

Root cause of the bad correction: the enumeration behind it only ever tested `.py` files
(`git ls-files '*.py'` and `find . -name '*.py'`), so it was structurally incapable of finding a
Markdown hit. It found 2 offenders while `ruff format --check .` reported 3, and that unexplained
discrepancy — the README — was the very file in dispute. The count mismatch was visible at the time
and should have been resolved before asserting the correction.

**Consequences reinstated:**

1. The `format` row above is accurate: T-05's own new `## Freshness accessor` content did trip
   `ruff format --check` (its one-line `__init__` signature exceeded the 100-char `line-length`), and
   the evidence pass's in-round fix — wrapping that signature across 3 lines inside the code fence —
   was a **legitimate, tool-required fix**, not a cosmetic edit made on a false premise. The
   `## Freshness accessor` fence is now format-clean; the only remaining hit in the file is the
   pre-existing line-26 one.
2. **Authoritative carry-forward** for the PR body (supersedes every earlier list in this file):
   - `services/api/README.md:26` — pre-existing `ruff format` violation in `## Data access`'s fence,
     predates BED-04, outside T-05's diff.
   - `services/api/app/api/programs.py:121` — pre-existing `ruff format` violation (AUTH-04).
   - `services/api/tests/unit/test_programs.py` — 4 pre-existing `ruff format` violations (AUTH-04).

All four BED-04 **Python** files remain format-clean (`app/services/freshness.py`,
`app/services/__init__.py`, `tests/unit/test_freshness.py`, `tests/perf/test_freshness_perf.py`) —
that part of the retracted correction was right, but it was never in dispute.

`format` is not one of the six gating dimensions, so none of the above changes any verdict.

## Status: SUPERSEDED

This escalation is historical. AF-03's pnpm gate was fixed (`apps/web/pnpm-workspace.yaml`,
`allowBuilds: { unrs-resolver: true }`) and the re-run evidence pass returned **READY** with all six
dimensions PASS or accepted-N/A. See `EVIDENCE-ROUNDS.md` § Re-run and `state.json` `.impl_evidence`.
