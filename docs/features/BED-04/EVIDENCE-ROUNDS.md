# BED-04 — Evidence pass rounds

| Round | FAILing dims | Action | Result |
|-------|--------------|--------|--------|
| 1 | format (informal, not one of the 6 dims), runtime, compile | Full packet run. Found `services/api/README.md` (T-05, in-scope) had one `ruff format` violation in the newly-added `## Freshness accessor` code fence (line-too-long `__init__` signature) — root cause: T-05 added a Python code fence that `ruff format` (0.16.4) reformats like a real source file; fixed surgically (wrapped the signature across 3 lines), leaving the file's one pre-existing, unrelated violation (line 26, `## Data access` section, predates BED-04) untouched per `surgical-changes`. Re-ran `ruff check`/`ruff format --check` — BED-04's own hunk clean. Also found a single, repeated pre-existing root cause blocking 5 of 6 apps/web command halves (typecheck, unit_tests, lint, runtime, compile) — see below. | format (BED-04 hunk) fixed ✓; environment blocker persists, cannot be fixed in-scope — escalating instead of burning rounds 2–3 on an identical re-run (see "Early escalation" below) |

## Early escalation — why round 1 is final

`docs/config/project-commands.yaml`'s composite commands span both stacks. Running the `apps/web` half of **every** command that touches it (`typecheck`, `lint` (`eslint`), `unit_tests` (`vitest`), `runtime` (`pnpm dev`), `compile` (`pnpm build`)) hits the **exact same** failure, byte-for-byte:

```
[ERR_PNPM_IGNORED_BUILDS] Ignored build scripts: unrs-resolver@1.12.2
Run "pnpm approve-builds" to pick which dependencies should be allowed to run scripts.
[ERROR] Command failed with exit code 1: pnpm install
```

Root cause: pnpm 11.20.0's pre-command dependency-status check (`runDepsStatusCheck`) now refuses to run **any** pnpm script (`install`, `exec`, `dev`, `build`, `test`) while `unrs-resolver`'s postinstall build script is neither approved nor denied for this project. No `.npmrc` / `pnpm-workspace.yaml` / `package.json` build-script policy exists yet in `apps/web`. Confirmed pre-existing and 100% unrelated to BED-04:

- `git diff main --stat -- apps/web/package.json apps/web/pnpm-lock.yaml` → empty (zero changes on this branch).
- `unrs-resolver@1.12.2` has been in `pnpm-lock.yaml` since the initial commit (`b4cad8c`).
- Every prior feature's recorded `impl_evidence` (AUTH-01..04, BED-01..03, ING-01) shows `typecheck/unit_tests/lint/runtime/compile` all `PASS` — this gate did not manifest during any of those runs, confirming it is new machine/tooling drift (pnpm was recently updated locally — its own output shows `Update available! 11.20.0 → 11.25.0`), not something any story caused.
- A sandboxed permission check declined my attempt to even inspect `pnpm approve-builds`/`--ignore-scripts` flags — correctly treating "approve an unreviewed dependency's build script" as a decision outside this agent's authority, not a code fix.

This is exactly the fix-loop's documented early-exit: *"Agent reports 'can't fix without config / spec / ADR change' → escalate to the user mid-loop."* Two more mechanical rounds re-running an environment gate with an unchanged root cause would not change the outcome. Escalating now. See `EVIDENCE-ESCALATION.md`.

## Re-run (2026-09-03T09:26:12Z) — supersedes the BLOCKED record above

AF-03 was fixed (`apps/web/pnpm-workspace.yaml` now records `allowBuilds: { unrs-resolver: true }`). The full six-dimension packet was regenerated from scratch against the current tree — not taken on trust:

| Round | FAILing dims | Action | Result |
|-------|--------------|--------|--------|
| 1 | none | Full packet re-run, both stacks, every command re-executed independently: `typecheck` (mypy 0 errors/91 files + tsc exit 0), `unit_tests` (pytest full suite 430/0/38.58s + vitest 1/1), `lint` (ruff check clean + eslint exit 0), `runtime` (uvicorn boot+/health 200 clean + next dev boot+GET / 200 clean), `compile` (next build 5/5 static pages, run via `node_modules/.bin/next build --turbopack` per this session's permission constraint on `pnpm -C apps/web build`), `design_check` (N/A, AF-04 reused, unchanged). One transient issue found and resolved without a code change: the directive's port 3010 collided with a pre-existing, unrelated IPv4 listener (`python -m agentrise_mcp.server`, pid 518) also bound to `*:3010`, producing a nondeterministic 404-vs-200 result depending on `127.0.0.1` vs `localhost` resolution. Re-ran the web boot check on port 3011 (single listener confirmed via `lsof`) — clean 200 on both. Not a BED-04 defect; no fix needed, no round-2 required. | All six dimensions ✓ — VERDICT: READY |

**Factual correction to the prior escalation's "orchestrator correction" section** (informational only — not gating, `format` is not one of the six dimensions, and `EVIDENCE-ESCALATION.md` is left unedited per instruction): re-running `uv run ruff format --check .` on this pass shows `ruff 0.16.4` **does** reformat Python code fences embedded in Markdown files (verified directly: `ruff format --check README.md` alone reproduces the `README.md:26` finding). The original round-1 claim that `README.md:26` had a real `ruff format` finding was correct; the appended "orchestrator correction" asserting ruff never reads Markdown does not hold for this ruff version. This changes no verdict: `git diff main -- services/api/README.md` confirms line 26 (the `## Data access` section) predates BED-04 — T-05 only added the `## Freshness accessor` section further down, which remains format-clean. `README.md:26`, `app/api/programs.py:121`, and `tests/unit/test_programs.py` (4 hunks) are all still pre-existing/AUTH-04, still correctly carry-forward, still not touched.

See `docs/features/BED-04/state.json` `.impl_evidence` for the full per-dimension record.
